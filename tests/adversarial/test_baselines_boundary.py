"""Adversarial boundary and anti-lookahead tests for baseline strategies (Issue 166).

Validates strict anti-lookahead temporal causality, fail-closed handling of
missing/corrupted observations, admitted boundary enforcement, whole-share
allocations, and staging validation across B0 through B5.
"""

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from drift.baselines import (
    B0CashStrategy,
    B1SingleBuyAndHoldStrategy,
    B2EqualWeightBuyAndHoldStrategy,
    B3MonthlyEqualWeightRebalanceStrategy,
    B4MomentumStrategy,
    B5LowVolatilityStrategy,
)
from drift.domain.common import UUID7
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
from drift.domain.evaluator_strategy import PositionViewV1
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1

SEC_A = UUID("018e0000-0000-7000-8000-000000000001")
SEC_B = UUID("018e0000-0000-7000-8000-000000000002")
SEC_C = UUID("018e0000-0000-7000-8000-000000000003")
SEC_UNADMITTED = UUID("018e0000-0000-7000-8000-000000000099")


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


def _make_obs(
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
    obs_digest = hashlib.sha256(f"{security_id}_{day.isoformat()}".encode()).hexdigest()
    return ExploratoryReconstructedSessionObservationV1.model_construct(
        schema_version="1",
        kind="exploratory_reconstructed_session_observation",
        session_key=_session_key(day),
        security_id=security_id,
        listing_id=UUID("018e0000-0000-7000-8000-000000000099"),
        venue=ListingVenue.XNYS,
        cohort_hash="f" * 64,
        source_observation_hash=obs_digest,
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
        reconstruction_hash=obs_digest,
    )


def _build_context(
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
        observations = tuple(_make_obs(sec, d, p) for d, p in hist)
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


def test_anti_lookahead_temporal_causality() -> None:
    """Injecting future observations post-cutoff must not alter decision intents."""
    cutoff_day = date(2026, 1, 15)
    future_day_1 = date(2026, 1, 16)
    future_day_2 = date(2026, 1, 17)

    # 260 days of history up to cutoff
    past_dates = [cutoff_day - timedelta(days=260 - i) for i in range(260)]
    clean_hist = [
        (d, Decimal("100.00") + Decimal(str(i))) for i, d in enumerate(past_dates)
    ]

    # Future-contaminated history contains extra subsequent sessions
    tainted_hist = list(clean_hist) + [
        (future_day_1, Decimal("999.00")),
        (future_day_2, Decimal("1.00")),
    ]

    ctx_clean = _build_context(
        day=cutoff_day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: clean_hist, SEC_B: clean_hist},
    )
    ctx_tainted = _build_context(
        day=cutoff_day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: tainted_hist, SEC_B: tainted_hist},
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

        assert intent_clean.session_key == ctx_clean.session_key
        assert intent_clean.decision_time == ctx_clean.decision_cutoff
        assert intent_clean.targets == intent_tainted.targets


def test_admitted_cohort_boundary_and_staging() -> None:
    """Targets outside admitted cohort must never be generated and must pass staging."""
    day = date(2026, 1, 15)
    hist = [(day, Decimal("50.00"))]

    # Context admits only SEC_A
    ctx = _build_context(
        day=day,
        cohort=(SEC_A,),
        history_by_security={SEC_A: hist},
    )

    # Strategy targeting unadmitted security must emit empty targets
    b1_unadmitted = B1SingleBuyAndHoldStrategy(SEC_UNADMITTED)
    intent = b1_unadmitted.decide_exploratory(ctx)
    assert intent.targets == ()

    # Staging must cleanly validate and accept intent
    staged = stage_exploratory_decision_targets(intent, ctx)
    assert staged == ()

    # B2 across admitted cohort (SEC_A only)
    b2 = B2EqualWeightBuyAndHoldStrategy()
    intent_b2 = b2.decide_exploratory(ctx)
    assert len(intent_b2.targets) == 1
    assert intent_b2.targets[0].security_id == SEC_A

    staged_b2 = stage_exploratory_decision_targets(intent_b2, ctx)
    assert len(staged_b2) == 1
    assert staged_b2[0].security_id == SEC_A


def test_whole_share_non_negative_quantities_and_rounding() -> None:
    """Target quantities must be non-negative whole integers."""
    day = date(2026, 1, 15)
    # Odd price: 10000 / (2 * 33.33) = 150.015... -> 150 shares
    hist_a = [(day, Decimal("33.33"))]
    hist_b = [(day, Decimal("17.77"))]

    ctx = _build_context(
        day=day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist_a, SEC_B: hist_b},
        cash=Decimal("10000.00"),
    )

    b2 = B2EqualWeightBuyAndHoldStrategy()
    intent = b2.decide_exploratory(ctx)
    for target in intent.targets:
        assert isinstance(target.target_quantity, int)
        assert target.target_quantity >= 0

    staged = stage_exploratory_decision_targets(intent, ctx)
    assert len(staged) == 2


def test_fail_closed_on_zero_or_negative_price() -> None:
    """Zero or negative closing prices must fail closed cleanly."""
    day = date(2026, 1, 15)
    hist_zero = [(day, Decimal("0.00"))]
    hist_neg = [(day, Decimal("-10.00"))]

    ctx_zero = _build_context(
        day=day,
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
        # All targets must be 0 or empty for non-positive prices
        assert all(t.target_quantity == 0 for t in intent.targets)


def test_fail_closed_on_zero_or_negative_cash() -> None:
    """Zero or negative available cash must emit 0 purchase targets."""
    day = date(2026, 1, 15)
    hist = [(day, Decimal("100.00"))]

    ctx_no_cash = _build_context(
        day=day,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist, SEC_B: hist},
        cash=Decimal("0.00"),
        nav=Decimal("0.00"),
    )

    b1 = B1SingleBuyAndHoldStrategy(SEC_A)
    b2 = B2EqualWeightBuyAndHoldStrategy()
    assert b1.decide_exploratory(ctx_no_cash).targets == ()
    assert b2.decide_exploratory(ctx_no_cash).targets == ()


def test_b4_momentum_tie_break_determinism() -> None:
    """Identical momentum returns break ties by security_id bytes."""
    cutoff = date(2026, 1, 15)
    dates = [cutoff - timedelta(days=260 - i) for i in range(260)]
    # Exactly identical prices for both securities
    hist = [(d, Decimal("100.00") + Decimal(str(i))) for i, d in enumerate(dates)]

    ctx = _build_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist, SEC_B: hist},
    )

    b4 = B4MomentumStrategy()
    intent = b4.decide_exploratory(ctx)
    # ceil(2 / 2) = 1 security selected
    assert len(intent.targets) == 1
    # SEC_A bytes < SEC_B bytes -> SEC_A is selected
    assert intent.targets[0].security_id == min(SEC_A, SEC_B, key=lambda s: s.bytes)


def test_b5_low_volatility_tie_break_determinism() -> None:
    """Identical variance returns break ties by security_id bytes."""
    cutoff = date(2026, 1, 15)
    dates = [cutoff - timedelta(days=70 - i) for i in range(70)]
    # Flat constant prices for both securities -> variance == 0 for both
    hist = [(d, Decimal("100.00")) for d in dates]

    ctx = _build_context(
        day=cutoff,
        cohort=(SEC_A, SEC_B),
        history_by_security={SEC_A: hist, SEC_B: hist},
    )

    b5 = B5LowVolatilityStrategy()
    intent = b5.decide_exploratory(ctx)
    # ceil(2 / 2) = 1 security selected
    assert len(intent.targets) == 1
    # SEC_A bytes < SEC_B bytes -> SEC_A is selected
    assert intent.targets[0].security_id == min(SEC_A, SEC_B, key=lambda s: s.bytes)
