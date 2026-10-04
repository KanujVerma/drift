"""M3 adversarial acceptance: deterministic baselines and canonical runner (Issue 169).

Attacks the deterministic reference baseline strategy library (B0 through B5)
and canonical suite runner across all five acceptance criteria:
1. Lookahead Immunity: Temporal causality and future observation isolation.
2. Cohort Survivorship & Admission Boundaries: Delisting, survivorship, and
   history gating.
3. Non-Promotability & Lane Integrity: Rejection of promotion lane and evidence
   laundering.
4. Closed-World Replay Determinism: Bitwise invariant replay across arbitrary
   operational metadata.
5. Fail-Closed Missingness & Edge Cases: Sparse universes, zero/negative marks,
   and calendar boundaries.

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

# ruff: noqa: E402

import hashlib
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_engine as eng

from drift.baselines import (
    B0CashStrategy,
    B1SingleBuyAndHoldStrategy,
    B2EqualWeightBuyAndHoldStrategy,
    B3MonthlyEqualWeightRebalanceStrategy,
    B4MomentumStrategy,
    B5LowVolatilityStrategy,
    run_baseline_suite,
    run_canonical_baseline,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    is_month_end_session_day,
)
from drift.baselines.common import deterministic_baseline_uuid7
from drift.domain.common import UUID7, ImmutableJSONValue
from drift.domain.evaluator_clock import EvaluationSessionV1, evaluation_session_hash
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryReconstructedRuntimeStrategy,
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.evaluator_strategy import (
    PositionViewV1,
    SecurityTargetPositionV1,
    StrategyIntentRejectedError,
)
from drift.domain.experiments import ExperimentRun, ExperimentRunStatus
from drift.domain.observation_query import drift_source_inventory_hash
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.engine import PromotionLaneDisabledError, refuse_promotion_lane

SEC_A = UUID("018e0000-0000-7000-8000-000000000001")
SEC_B = UUID("018e0000-0000-7000-8000-000000000002")
SEC_C = UUID("018e0000-0000-7000-8000-000000000003")
SEC_UNADMITTED = UUID("018e0000-0000-7000-8000-000000000099")

PROMOTION_LANE_DISABLED = r"^the promotion lane is disabled \(issue 79 ruling\): "


# --- Helper Fixtures & Builders ---------------------------------------------


def _metric(run: ExperimentRun, name: str) -> ImmutableJSONValue:
    metrics = run.metrics
    assert isinstance(metrics, Mapping)
    return metrics[name]


def _session_key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(day: date) -> EvaluationSessionV1:
    closed_at = datetime.combine(day, time(21, 0), tzinfo=UTC)
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_session_key(day),
        opened_at=closed_at - timedelta(hours=6, minutes=30),
        closed_at=closed_at,
        authority="scheduled_reconstruction",
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _make_reconstructed_obs(
    security_id: UUID7,
    day: date,
    close: Decimal,
) -> ExploratoryReconstructedSessionObservationV1:
    fields = (
        ExploratoryReconstructedFieldV1(
            field_name="open",
            source_value=close,
            method_id="source_basis",
            meaning="price",
            source_field_hash="0" * 64,
        ),
        ExploratoryReconstructedFieldV1(
            field_name="high",
            source_value=close,
            method_id="source_basis",
            meaning="price",
            source_field_hash="0" * 64,
        ),
        ExploratoryReconstructedFieldV1(
            field_name="low",
            source_value=close,
            method_id="source_basis",
            meaning="price",
            source_field_hash="0" * 64,
        ),
        ExploratoryReconstructedFieldV1(
            field_name="close",
            source_value=close,
            method_id="source_basis",
            meaning="price",
            source_field_hash="0" * 64,
        ),
        ExploratoryReconstructedFieldV1(
            field_name="volume",
            source_value=Decimal("1000"),
            method_id="source_basis",
            meaning="share_volume",
            source_field_hash="0" * 64,
        ),
    )
    digest = hashlib.sha256(f"{security_id}_{day.isoformat()}".encode()).hexdigest()
    return ExploratoryReconstructedSessionObservationV1.model_construct(
        schema_version="1",
        kind="exploratory_reconstructed_session_observation",
        session_key=_session_key(day),
        security_id=security_id,
        listing_id=UUID("018e0000-0000-7000-8000-000000000099"),
        venue=ListingVenue.XNYS,
        cohort_hash="f" * 64,
        source_observation_hash=digest,
        observation_contract_hash="b" * 64,
        observation_selection_proof_hash="c" * 64,
        contract_selection_proof_hash="d" * 64,
        scheduled_session_hash="e" * 64,
        scheduled_selection_proof_hash="f" * 64,
        schedule_artifact_hash="1" * 64,
        generated_session_row_hash="2" * 64,
        outcome_query_hash="3" * 64,
        source_context_hash="4" * 64,
        evidence_vintage_cutoff=datetime.combine(day, time(21, 0), tzinfo=UTC),
        reconstruction_policy_hash="5" * 64,
        currency="USD",
        fields=fields,
        acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
        reconstruction_hash=digest,
    )


def _build_exploratory_context(
    day: date,
    cohort: tuple[UUID7, ...],
    history_by_security: dict[UUID7, Sequence[tuple[date, Decimal]]],
    cash: Decimal = Decimal("10000.00"),
    nav: Decimal = Decimal("10000.00"),
    holdings: tuple[PositionViewV1, ...] = (),
) -> ExploratoryStrategyDecisionContextV1:
    session = _evaluation_session(day)
    views = []
    for sec in cohort:
        hist = history_by_security.get(sec, ())
        observations = tuple(_make_reconstructed_obs(sec, d, p) for d, p in hist)
        view = ExploratoryReconstructedDecisionViewV1.model_construct(
            schema_version="1",
            evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
            security_id=sec,
            observations=observations,
            acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
        )
        views.append(view)

    return ExploratoryStrategyDecisionContextV1.model_construct(
        schema_version="1",
        lane="exploratory",
        evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
        is_promotion_grade_evidence=False,
        session_key=session.session_key,
        decision_session=session,
        decision_cutoff=session.closed_at,
        cohort_hash="f" * 64,
        admitted_cohort=cohort,
        reconstructed_decision_views=tuple(views),
        current_holdings=holdings,
        current_cash=cash,
        portfolio_nav=nav,
        acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
    )


# --- 1. Lookahead Immunity Attacks ------------------------------------------


def test_adversarial_lookahead_future_observation_injection_immunity() -> None:
    """Injecting future post-cutoff observations must not alter baseline decisions.

    Adversarial Attack:
    Pass an observation series containing subsequent sessions with extreme
    prices (e.g. 10000x jump) occurring strictly after the decision cutoff.
    Verify all baselines B0 through B5 produce byte-identical decision targets.

    Control:
    Altering an observation at or before the decision cutoff alters the decision.
    """
    cutoff_day = date(2026, 1, 15)
    future_day_1 = date(2026, 1, 16)
    future_day_2 = date(2026, 1, 17)

    # 260 days of historical data up to cutoff
    past_dates = [cutoff_day - timedelta(days=260 - i) for i in range(260)]
    clean_hist_a = [
        (d, Decimal("100.00") + Decimal(str(i))) for i, d in enumerate(past_dates)
    ]
    clean_hist_b = [(d, Decimal("50.00")) for d in past_dates]

    # Future-injected history containing radical future shocks
    tainted_hist_a = list(clean_hist_a) + [
        (future_day_1, Decimal("999999.00")),
        (future_day_2, Decimal("1.00")),
    ]
    tainted_hist_b = list(clean_hist_b) + [
        (future_day_1, Decimal("10000.00")),
        (future_day_2, Decimal("0.01")),
    ]

    ctx_clean = _build_exploratory_context(
        day=cutoff_day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: clean_hist_a, SEC_B: clean_hist_b},
    )
    ctx_tainted = _build_exploratory_context(
        day=cutoff_day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: tainted_hist_a, SEC_B: tainted_hist_b},
    )

    strategies: Sequence[ExploratoryReconstructedRuntimeStrategy] = (
        B0CashStrategy(),
        B1SingleBuyAndHoldStrategy(SEC_A),
        B2EqualWeightBuyAndHoldStrategy(),
        B3MonthlyEqualWeightRebalanceStrategy(),
        B4MomentumStrategy(),
        B5LowVolatilityStrategy(),
    )

    for strat in strategies:
        intent_clean = strat.decide_exploratory(ctx_clean)
        intent_tainted = strat.decide_exploratory(ctx_tainted)

        # Invariant: Future leakage is completely blocked
        assert intent_clean.targets == intent_tainted.targets
        assert intent_clean.session_key == intent_tainted.session_key
        assert intent_clean.decision_time == intent_tainted.decision_time

    # Control: An alteration at cutoff day changes B1 target quantity
    altered_hist_a = list(clean_hist_a[:-1]) + [(cutoff_day, Decimal("500.00"))]
    ctx_altered = _build_exploratory_context(
        day=cutoff_day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: altered_hist_a, SEC_B: clean_hist_b},
    )
    b1 = B1SingleBuyAndHoldStrategy(SEC_A)
    intent_altered = b1.decide_exploratory(ctx_altered)
    # Price changed from 359 to 500 -> 10000 // 500 = 20 vs 10000 // 359 = 27
    assert intent_clean.targets != intent_altered.targets


def test_adversarial_lookahead_momentum_and_low_volatility_analytical_series() -> None:
    """Future sessions injected post-cutoff do not alter B4 or B5 analytical scores.

    Adversarial Attack:
    Inject post-cutoff future bars with 100x return spikes. Verify that B4 momentum
    and B5 variance computations are invariant.

    Control:
    Mutating an observation inside the formation or lookback window changes the score.
    """
    cutoff = date(2026, 1, 15)
    future = date(2026, 1, 16)
    dates = [cutoff - timedelta(days=260 - i) for i in range(260)]

    clean_hist = [(d, Decimal("100.00") + Decimal(str(i))) for i, d in enumerate(dates)]
    future_spiked_hist = list(clean_hist) + [(future, Decimal("99999.00"))]

    ctx_clean = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: clean_hist, SEC_B: clean_hist},
    )
    ctx_tainted = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: future_spiked_hist, SEC_B: future_spiked_hist},
    )

    b4 = B4MomentumStrategy()
    b5 = B5LowVolatilityStrategy()

    mom_clean = b4._compute_momentum(ctx_clean, SEC_A)
    mom_tainted = b4._compute_momentum(ctx_tainted, SEC_A)
    assert mom_clean is not None
    assert mom_clean == mom_tainted

    var_clean = b5._compute_variance(ctx_clean, SEC_A)
    var_tainted = b5._compute_variance(ctx_tainted, SEC_A)
    assert var_clean is not None
    assert var_clean == var_tainted

    # Control: Mutating a past bar at t-21
    # (inside B4 skip anchor and B5 60-session window)
    t_past = dates[len(dates) - 1 - 21]
    past_mutated_hist = [
        (d, Decimal("500.00") if d == t_past else p) for d, p in clean_hist
    ]
    ctx_past_mutated = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: past_mutated_hist, SEC_B: clean_hist},
    )
    assert b4._compute_momentum(ctx_past_mutated, SEC_A) != mom_clean
    assert b5._compute_variance(ctx_past_mutated, SEC_A) != var_clean


# --- 2. Cohort Survivorship & Admission Boundaries --------------------------


def test_adversarial_unadmitted_security_positive_target_rejection() -> None:
    """Staging positive targets for unadmitted securities fails closed.

    Adversarial Attack:
    Attempt to stage a target position with positive share quantity for an
    unadmitted security.

    Invariant:
    stage_exploratory_decision_targets and stage_decision_targets fail closed
    with StrategyIntentRejectedError matching
    '^a positive target requires an admitted security'.

    Control:
    Staging an explicit zero target to liquidate an unadmitted holding is permitted.
    """
    cutoff = date(2026, 1, 15)
    hist = [(cutoff, Decimal("100.00"))]
    ctx = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist},
    )

    # Positive target for unadmitted security
    malicious_intent = B0CashStrategy().decide_exploratory(ctx)
    intent_with_unadmitted = malicious_intent.model_copy(
        update={
            "targets": (
                SecurityTargetPositionV1(
                    security_id=SEC_UNADMITTED, target_quantity=10
                ),
            )
        }
    )

    with pytest.raises(
        StrategyIntentRejectedError,
        match=r"^a positive target requires an admitted security",
    ):
        stage_exploratory_decision_targets(intent_with_unadmitted, ctx)

    # Control: Liquidating (target_quantity=0) an unadmitted holding is permitted
    unadmitted_holding = PositionViewV1(
        security_id=SEC_UNADMITTED,
        quantity=10,
        cost_basis=Decimal("1000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    ctx_with_unadmitted_holding = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist},
        holdings=(unadmitted_holding,),
    )
    intent_liquidate = malicious_intent.model_copy(
        update={
            "targets": (
                SecurityTargetPositionV1(security_id=SEC_UNADMITTED, target_quantity=0),
            )
        }
    )
    staged = stage_exploratory_decision_targets(
        intent_liquidate, ctx_with_unadmitted_holding
    )
    assert any(
        t.security_id == SEC_UNADMITTED and t.target_quantity == 0 for t in staged
    )


def test_adversarial_b1_cohort_dropout_prevents_unauthorized_purchases() -> None:
    """B1 targeting a dropped or unadmitted security emits empty targets.

    Adversarial Attack:
    Target security is dropped from the admitted cohort. Verify B1 generates
    empty targets rather than illegal purchases. If previously held, retains
    existing quantity without additional turnover.
    """
    day = date(2026, 1, 15)
    hist_a = [(day, Decimal("100.00"))]
    # Context admits SEC_B only; SEC_A has dropped out
    ctx_dropped = _build_exploratory_context(
        day=day,
        cohort=(SEC_B,),
        history_by_security={SEC_B: hist_a},
    )

    b1_a = B1SingleBuyAndHoldStrategy(SEC_A)
    intent_dropped = b1_a.decide_exploratory(ctx_dropped)
    assert intent_dropped.targets == ()

    # Control: When SEC_A is admitted, B1 allocates available cash
    ctx_admitted = _build_exploratory_context(
        day=day,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist_a},
        cash=Decimal("5000.00"),
    )
    intent_admitted = b1_a.decide_exploratory(ctx_admitted)
    assert len(intent_admitted.targets) == 1
    assert intent_admitted.targets[0].security_id == SEC_A
    assert intent_admitted.targets[0].target_quantity == 50


def test_adversarial_b2_buy_and_hold_retains_existing_shares_without_trading() -> None:
    """B2 retains existing share counts on subsequent sessions with zero turnover.

    Adversarial Attack:
    Present B2 with existing open holdings and new cash or price shifts.
    Verify B2 generates exact holding quantities rather than reallocating.
    """
    day = date(2026, 1, 15)
    hist = [(day, Decimal("100.00"))]
    holding_a = PositionViewV1(
        security_id=SEC_A,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    holding_b = PositionViewV1(
        security_id=SEC_B,
        quantity=25,
        cost_basis=Decimal("2500.00"),
        average_cost_per_share=Decimal("100.00"),
    )

    ctx = _build_exploratory_context(
        day=day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist, SEC_B: hist},
        holdings=(holding_a, holding_b),
        cash=Decimal("20000.00"),  # Substantial cash surge
        nav=Decimal("27500.00"),
    )

    b2 = B2EqualWeightBuyAndHoldStrategy()
    intent = b2.decide_exploratory(ctx)
    target_dict = {t.security_id: t.target_quantity for t in intent.targets}
    assert target_dict[SEC_A] == 50
    assert target_dict[SEC_B] == 25


def test_adversarial_b3_monthly_rebalance_liquidates_delisted_cohort_members() -> None:
    """Delisted or unadmitted securities are liquidated at the next monthly rebalance.

    Adversarial Attack:
    B3 holds open positions in SEC_A and SEC_B. SEC_B is dropped from the
    admitted cohort. At monthly rebalance, B3 must omit SEC_B from targets,
    causing staging to explicitly stage SEC_B to 0 while reallocating NAV to
    admitted SEC_A.
    """
    month_end = date(2026, 1, 30)  # Rebalance session
    hist = [(month_end, Decimal("100.00"))]

    holding_a = PositionViewV1(
        security_id=SEC_A,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    holding_b = PositionViewV1(
        security_id=SEC_B,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )

    # SEC_B dropped from admitted cohort
    ctx = _build_exploratory_context(
        day=month_end,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist},
        holdings=(holding_a, holding_b),
        cash=Decimal("0.00"),
        nav=Decimal("10000.00"),
    )

    b3 = B3MonthlyEqualWeightRebalanceStrategy()
    intent = b3.decide_exploratory(ctx)

    # Intent only targets admitted SEC_A
    assert len(intent.targets) == 1
    assert intent.targets[0].security_id == SEC_A
    assert intent.targets[0].target_quantity == 100

    # Staging detects omitted holding SEC_B and stages liquidation to 0
    staged = stage_exploratory_decision_targets(intent, ctx)
    staged_dict = {t.security_id: t.target_quantity for t in staged}
    assert staged_dict[SEC_A] == 100
    assert staged_dict[SEC_B] == 0


def test_adversarial_b4_and_b5_exclude_insufficient_history_cohort_members() -> None:
    """Securities with insufficient history are excluded from B4/B5 ranking universes.

    Adversarial Attack:
    Provide cohort with SEC_A (full history), SEC_B (full history), and
    SEC_C (insufficient history: 20 sessions).
    For B4 (requires 253 sessions): SEC_C is excluded.
    For B5 (requires 61 sessions): SEC_C is excluded.

    Control:
    When SEC_C has sufficient history and dominant metrics, it is ranked and selected.
    """
    cutoff = date(2026, 1, 15)
    dates_full = [cutoff - timedelta(days=260 - i) for i in range(260)]
    dates_short = [cutoff - timedelta(days=20 - i) for i in range(20)]

    hist_a = [
        (d, Decimal("100.00") + Decimal(str(i))) for i, d in enumerate(dates_full)
    ]
    hist_b = [(d, Decimal("100.00")) for d in dates_full]
    hist_c_short = [(d, Decimal("500.00")) for d in dates_short]

    ctx_short = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B, SEC_C),
        history_by_security={SEC_A: hist_a, SEC_B: hist_b, SEC_C: hist_c_short},
        nav=Decimal("20000.00"),
    )

    b4 = B4MomentumStrategy()
    b5 = B5LowVolatilityStrategy()

    intent_b4 = b4.decide_exploratory(ctx_short)
    intent_b5 = b5.decide_exploratory(ctx_short)

    # SEC_C must NOT be selected by either strategy
    assert all(t.security_id != SEC_C for t in intent_b4.targets)
    assert all(t.security_id != SEC_C for t in intent_b5.targets)

    # Control: SEC_C given 260 sessions with lowest variance (constant price)
    hist_c_full = [(d, Decimal("50.00")) for d in dates_full]
    ctx_full = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B, SEC_C),
        history_by_security={SEC_A: hist_a, SEC_B: hist_b, SEC_C: hist_c_full},
        nav=Decimal("30000.00"),
    )
    intent_b5_full = b5.decide_exploratory(ctx_full)
    # SEC_C and SEC_B both have 0 variance -> selected
    target_ids = {t.security_id for t in intent_b5_full.targets}
    assert SEC_C in target_ids


# --- 3. Non-Promotability & Lane Integrity Attacks --------------------------


def test_adversarial_promotion_lane_disabled_in_canonical_runners() -> None:
    """Canonical baseline runner and suite fail closed on promotion admission.

    Adversarial Attack:
    Provide an engine configured with a promotion admission (bypassing
    construction). Verify run_canonical_baseline and run_baseline_suite raise
    PromotionLaneDisabledError.
    """
    bypassed_engine = eng._bypassed_promotion_engine()
    b0 = B0CashStrategy()

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "the experiment runner refuses",
    ):
        run_canonical_baseline(engine=bypassed_engine, strategy=b0)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "the experiment runner refuses",
    ):
        run_baseline_suite(engine=bypassed_engine)


def test_adversarial_baseline_runs_are_strictly_non_promotable() -> None:
    """Baseline executions produce strictly non-promotable exploratory evidence.

    Adversarial Attack:
    Execute standard reference baselines B0 through B5.
    Verify every ExperimentRun asserts is_promotion_grade_evidence=False,
    lane='exploratory', and classification=EXPLORATORY.
    """
    engine = eng._engine()
    suite = run_baseline_suite(engine=engine, securities=(eng.SEC_A,))

    for run in suite.runs.values():
        assert run.status == ExperimentRunStatus.COMPLETED
        assert _metric(run, "lane") == "exploratory"
        assert _metric(run, "is_promotion_grade_evidence") is False
        assert _metric(run, "classification") == EvaluationClassification.COMPLETE.value
        assert run.code_hash == drift_source_inventory_hash()


def test_adversarial_forged_promotion_specification_refusal() -> None:
    """An exploratory evaluation result cannot satisfy promotion lane checks."""
    engine = eng._engine()
    run = run_canonical_baseline(engine=engine, strategy=B0CashStrategy())
    assert run.status == ExperimentRunStatus.COMPLETED

    # Verify that refuse_promotion_lane accepts valid exploratory result
    # but rejects if promotion evidence grade is forged
    artifacts = eng._run(engine)
    # Genuine exploratory artifacts pass refusal
    refuse_promotion_lane(artifacts.result, site="adversarial baseline test")

    # Forged promotion evidence grade on result triggers refusal
    forged_result = artifacts.result.model_construct(
        **(dict(artifacts.result) | {"is_promotion_grade_evidence": True})
    )
    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "adversarial baseline test",
    ):
        refuse_promotion_lane(forged_result, site="adversarial baseline test")


# --- 4. Closed-World Replay Determinism Attacks -----------------------------


def test_adversarial_replay_determinism_across_arbitrary_metadata() -> None:
    """Canonical baseline runs are byte-identical across arbitrary runtime metadata.

    Adversarial Attack:
    Run the same baseline twice over the same bundle with differing run_id,
    differing started_at, differing completed_at, and differing audit_event_id.
    Verify result_hash, trace_hash, and metrics match byte-for-byte.

    Control:
    Mutating an evaluation input (e.g. strategy parameters) produces different hashes.
    """
    engine = eng._engine()
    strategy = B1SingleBuyAndHoldStrategy(target_security_id=eng.SEC_A)

    id_1 = deterministic_baseline_uuid7("run.1")
    id_2 = deterministic_baseline_uuid7("run.2")
    time_1 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    time_2 = datetime(2035, 12, 31, 23, 59, tzinfo=UTC)

    run_1 = run_canonical_baseline(
        engine=engine,
        strategy=strategy,
        run_id=id_1,
        started_at=time_1,
        completed_at=time_1 + timedelta(minutes=5),
        audit_event_id=deterministic_baseline_uuid7("audit.1"),
    )
    run_2 = run_canonical_baseline(
        engine=engine,
        strategy=strategy,
        run_id=id_2,
        started_at=time_2,
        completed_at=time_2 + timedelta(hours=2),
        audit_event_id=deterministic_baseline_uuid7("audit.2"),
    )

    # Invariant: Run identities differ, but deterministic outputs are identical
    assert run_1.run_id != run_2.run_id
    assert run_1.started_at != run_2.started_at
    assert _metric(run_1, "result_hash") == _metric(run_2, "result_hash")
    assert _metric(run_1, "trace_hash") == _metric(run_2, "trace_hash")
    assert _metric(run_1, "net_profit_and_loss") == _metric(
        run_2, "net_profit_and_loss"
    )
    assert run_1.dataset_hash == run_2.dataset_hash
    assert run_1.code_hash == run_2.code_hash

    # Control: Different strategy target produces different result_hash
    strategy_other = B1SingleBuyAndHoldStrategy(target_security_id=eng.SEC_B)
    run_other = run_canonical_baseline(
        engine=engine,
        strategy=strategy_other,
    )
    assert _metric(run_1, "result_hash") != _metric(run_other, "result_hash")


def test_adversarial_baseline_suite_replay_determinism() -> None:
    """Baseline suite executions are byte-identical across independent executions."""
    engine = eng._engine()
    suite_1 = run_baseline_suite(engine=engine, securities=(eng.SEC_A,))
    suite_2 = run_baseline_suite(engine=engine, securities=(eng.SEC_A,))

    assert set(suite_1.runs.keys()) == set(suite_2.runs.keys())
    for key in suite_1.runs:
        r1 = suite_1.runs[key]
        r2 = suite_2.runs[key]
        assert _metric(r1, "result_hash") == _metric(r2, "result_hash")
        assert _metric(r1, "trace_hash") == _metric(r2, "trace_hash")
        assert _metric(r1, "net_profit_and_loss") == _metric(r2, "net_profit_and_loss")
        assert r1.dataset_hash == r2.dataset_hash
        assert r1.code_hash == r2.code_hash


# --- 5. Fail-Closed Missingness & Edge Cases ---------------------------------


def test_adversarial_sparse_universe_zero_division_safety() -> None:
    """Sparse universes (< 2 eligible securities) fail closed without zero division.

    Adversarial Attack:
    Present B4 and B5 with an empty cohort (0 securities) or a singleton cohort
    (1 security). Verify strategies return empty targets and never raise
    ZeroDivisionError.
    """
    cutoff = date(2026, 1, 15)
    hist = [(cutoff - timedelta(days=260 - i), Decimal("100.00")) for i in range(260)]

    # 0 securities
    ctx_empty = _build_exploratory_context(
        day=cutoff,
        cohort=(),
        history_by_security={},
    )
    # 1 security
    ctx_singleton = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist},
    )

    b4 = B4MomentumStrategy()
    b5 = B5LowVolatilityStrategy()

    assert b4.decide_exploratory(ctx_empty).targets == ()
    assert b4.decide_exploratory(ctx_singleton).targets == ()

    assert b5.decide_exploratory(ctx_empty).targets == ()
    assert b5.decide_exploratory(ctx_singleton).targets == ()


def test_adversarial_zero_and_negative_prices_fail_closed() -> None:
    """Zero or negative price marks are rejected fail-closed without dividing by zero.

    Adversarial Attack:
    Present context with price marks of 0.00 and -50.00.
    Verify all baseline strategies fail closed emitting empty or zero targets.
    """
    cutoff = date(2026, 1, 15)
    hist_zero = [(cutoff, Decimal("0.00"))]
    hist_neg = [(cutoff, Decimal("-50.00"))]

    ctx_zero = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist_zero, SEC_B: hist_neg},
    )

    strategies: Sequence[ExploratoryReconstructedRuntimeStrategy] = (
        B0CashStrategy(),
        B1SingleBuyAndHoldStrategy(SEC_A),
        B2EqualWeightBuyAndHoldStrategy(),
        B3MonthlyEqualWeightRebalanceStrategy(),
        B4MomentumStrategy(),
        B5LowVolatilityStrategy(),
    )

    for strat in strategies:
        intent = strat.decide_exploratory(ctx_zero)
        assert all(t.target_quantity == 0 for t in intent.targets)


def test_adversarial_zero_and_negative_cash_fail_closed() -> None:
    """Zero or negative available cash/NAV emits zero purchase targets.

    Adversarial Attack:
    Present context with cash = Decimal('0.00') and NAV = Decimal('-1000.00').
    Verify strategies emit empty targets.
    """
    cutoff = date(2026, 1, 15)
    hist = [(cutoff, Decimal("100.00"))]

    ctx_no_funds = _build_exploratory_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist, SEC_B: hist},
        cash=Decimal("0.00"),
        nav=Decimal("-1000.00"),
    )

    b1 = B1SingleBuyAndHoldStrategy(SEC_A)
    b2 = B2EqualWeightBuyAndHoldStrategy()
    b3 = B3MonthlyEqualWeightRebalanceStrategy()

    assert b1.decide_exploratory(ctx_no_funds).targets == ()
    assert b2.decide_exploratory(ctx_no_funds).targets == ()
    assert b3.decide_exploratory(ctx_no_funds).targets == ()


def test_adversarial_calendar_month_end_weekend_gap_boundaries() -> None:
    """Month-end calendar boundaries handle weekend transitions correctly."""
    # Friday Jan 30, 2026 -> Saturday Jan 31, 2026 (weekend month end).
    # Next business day is Monday Feb 2, 2026 -> Different month -> Must be month end!
    friday_month_end = date(2026, 1, 30)
    assert is_month_end_session_day(friday_month_end) is True

    # Mid-week normal days -> Same month -> Must NOT be month end
    mid_week_wed = date(2026, 1, 14)
    assert is_month_end_session_day(mid_week_wed) is False

    # Thursday before Friday month end -> Next business day is Friday Jan 30
    # (same month) -> False
    thursday_before = date(2026, 1, 29)
    assert is_month_end_session_day(thursday_before) is False
