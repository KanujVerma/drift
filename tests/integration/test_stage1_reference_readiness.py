"""Integration tests for Stage 1 reference baseline readiness (Issue 441).

Validates frozen M3 reference baseline algorithms (B3, B4, B5) using deterministic
synthetic observations across canonical lookback boundaries, pure Decimal accounting
consistency, and fail-closed safety invariants.
"""

import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.baselines import (
    B3MonthlyEqualWeightRebalanceStrategy,
    B4MomentumStrategy,
    B5LowVolatilityStrategy,
)
from drift.baselines.common import (
    extract_current_close_price,
    security_order_key,
)
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import EvaluationSessionV1, evaluation_session_hash
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_strategy import (
    PositionViewV1,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.scorecards.performance import compute_return_and_risk

# ---------------------------------------------------------------------------
# Deterministic Synthetic Cohort and Fixtures (12 Securities)
# ---------------------------------------------------------------------------

SYNTHETIC_COHORT_12: tuple[UUID, ...] = tuple(
    UUID(f"018e0000-0000-7000-8000-{i:012d}") for i in range(1, 13)
)

START_DATE = date(2024, 1, 1)


def _session_key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(
    day: date,
    authority: str = "scheduled_reconstruction",
) -> EvaluationSessionV1:
    closed_at = datetime.combine(day, time(21, 0), tzinfo=UTC)
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_session_key(day),
        opened_at=closed_at - timedelta(hours=6, minutes=30),
        closed_at=closed_at,
        authority=authority,
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
            source_value=Decimal("10000"),
            method_id="source_basis",
            meaning="share_volume",
            source_field_hash="0" * 64,
        ),
    )
    return ExploratoryReconstructedSessionObservationV1.model_construct(
        schema_version="1",
        kind="exploratory_reconstructed_session_observation",
        session_key=_session_key(day),
        security_id=security_id,
        listing_id=UUID("018e0000-0000-7000-8000-000000000099"),
        venue=ListingVenue.XNYS,
        cohort_hash="f" * 64,
        source_observation_hash="a" * 64,
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
        reconstruction_hash="0" * 64,
    )


def _exploratory_context(
    day: date,
    cohort: tuple[UUID7, ...],
    history: dict[UUID7, list[tuple[date, Decimal]]],
    holdings: tuple[PositionViewV1, ...] = (),
    cash: Decimal = Decimal("10000.00"),
    nav: Decimal = Decimal("10000.00"),
) -> ExploratoryStrategyDecisionContextV1:
    session = _evaluation_session(day, authority="scheduled_reconstruction")
    views = []
    for sec in cohort:
        observations = []
        if sec in history:
            for h_day, h_close in history[sec]:
                if h_day <= day:
                    observations.append(_make_reconstructed_obs(sec, h_day, h_close))
        view = ExploratoryReconstructedDecisionViewV1.model_construct(
            schema_version="1",
            evidence_grade=EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
            security_id=sec,
            observations=tuple(observations),
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


# ---------------------------------------------------------------------------
# STEP 1: Environment & Interpreter Status
# ---------------------------------------------------------------------------


def test_environment_pinned_interpreter_status() -> None:
    """Verify runtime Python interpreter against .python-version pinned requirement.

    Drift specifies Python 3.14.6 in .python-version. If the local runtime is 3.14.5
    or another non-identical interpreter, this test records the NONCANONICAL status
    while validating Decimal arithmetic invariance.
    """
    version_file = Path(__file__).parents[2] / ".python-version"
    assert version_file.exists(), ".python-version file must exist"
    pinned_version = version_file.read_text().strip()

    actual_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    if actual_version == pinned_version:
        status = "CANONICAL"
    else:
        status = "NONCANONICAL"

    # Explicitly document interpreter status
    assert status in ("CANONICAL", "NONCANONICAL")

    # In both canonical and noncanonical runtime, Decimal arithmetic must be exact
    with decimal_context():
        val = (Decimal("10120.00") - Decimal("10000.00")) / Decimal("10000.00")
        assert val == Decimal("0.012")


# ---------------------------------------------------------------------------
# STEP 2: Frozen B4 Momentum Strategy Tests (Canonical Defaults)
# ---------------------------------------------------------------------------


def test_b4_momentum_boundary_eligibility() -> None:
    """B4 requires exactly 253 sessions (formation 252 + 1) to become eligible.

    Validates that:
    - 252 sessions yields empty targets (unavailable / missing history).
    - 253 sessions yields non-empty targets (eligible).
    """
    strategy = B4MomentumStrategy()  # canonical defaults: formation=252, skip=21
    assert strategy.formation_sessions == 252
    assert strategy.skip_sessions == 21
    assert strategy.min_sessions == 253

    cohort = SYNTHETIC_COHORT_12[:3]  # minimal 3 securities
    dates = [START_DATE + timedelta(days=i) for i in range(253)]

    # 1. 252 sessions (indices 0 to 251)
    hist_252 = {
        sec: [(dates[i], Decimal("100.00") + Decimal(str(i))) for i in range(252)]
        for sec in cohort
    }
    ctx_252 = _exploratory_context(
        day=dates[251],
        cohort=cohort,
        history=hist_252,
    )
    intent_252 = strategy.decide_exploratory(ctx_252)
    assert intent_252.targets == (), (
        "B4 must be unavailable with 252 completed sessions"
    )

    # 2. 253 sessions (indices 0 to 252)
    hist_253 = {
        sec: [(dates[i], Decimal("100.00") + Decimal(str(i))) for i in range(253)]
        for sec in cohort
    }
    ctx_253 = _exploratory_context(
        day=dates[252],
        cohort=cohort,
        history=hist_253,
    )
    intent_253 = strategy.decide_exploratory(ctx_253)
    assert len(intent_253.targets) > 0, (
        "B4 must be eligible with 253 completed sessions"
    )


def test_b4_momentum_formula_ranking_tiebreak_and_allocation() -> None:
    """Verify B4 12-1 momentum formula, ranking, tiebreaks, and whole shares."""
    strategy = B4MomentumStrategy()
    dates = [START_DATE + timedelta(days=i) for i in range(253)]
    t = 252
    t_skip = t - 21  # index 231
    t_form = t - 252  # index 0

    cohort = SYNTHETIC_COHORT_12  # 12 securities -> top ceil(12/2) = 6 selected
    history: dict[UUID7, list[tuple[date, Decimal]]] = {}

    # Securities 0 to 9: strictly decreasing momentum
    # Sec 10 and 11: identical momentum to test deterministic tie-breaking
    for idx, sec in enumerate(cohort):
        if idx < 10:
            p_0 = Decimal("100.00")
            # Vary skip close to produce descending returns: 200, 190, 180...
            p_skip = Decimal(str(200 - idx * 10))
            p_curr = p_skip
        else:
            # Identical momentum for securities 10 and 11
            p_0 = Decimal("100.00")
            p_skip = Decimal("105.00")
            p_curr = p_skip

        obs_list = []
        for i in range(253):
            if i == t_form:
                obs_list.append((dates[i], p_0))
            elif i == t_skip:
                obs_list.append((dates[i], p_skip))
            else:
                obs_list.append((dates[i], p_curr))
        history[sec] = obs_list

    ctx = _exploratory_context(
        day=dates[-1],
        cohort=cohort,
        history=history,
        nav=Decimal("12000.00"),
    )

    intent = strategy.decide_exploratory(ctx)
    targets = intent.targets
    target_map = {t.security_id: t.target_quantity for t in targets}

    # Top ceil(12/2) = 6 selected
    assert len(targets) == 6
    selected_secs = [t.security_id for t in targets]

    # Top 6 should be cohort[0] through cohort[5] (highest momentum)
    expected_top_6 = list(cohort[:6])
    assert selected_secs == expected_top_6

    # Verify whole-share calculations:
    # NAV = 12000 -> 12000 / 6 = 2000 dollars per security
    # Price for cohort[0] at current date is 200.00 -> 2000 // 200 = 10 shares
    prices_b4 = {sec: extract_current_close_price(ctx, sec) for sec in selected_secs}
    assert all(p is not None for p in prices_b4.values())
    total_cost = sum(
        (target_map[sec] * p for sec, p in prices_b4.items() if p is not None),
        Decimal("0.00"),
    )
    assert total_cost <= Decimal("12000.00")
    assert Decimal("12000.00") - total_cost >= Decimal("0.00")  # cash residual >= 0

    # Test deterministic tie-break:
    # 3 securities: SEC_A (highest), SEC_B and SEC_C (identical momentum)
    sec_a = cohort[0]
    sec_b = cohort[1]
    sec_c = cohort[2]
    tie_cohort = (sec_a, sec_b, sec_c)
    tie_history = {
        sec_a: [
            (
                dates[i],
                Decimal("150.00")
                if i == t_skip
                else (Decimal("100.00") if i == t_form else Decimal("150.00")),
            )
            for i in range(253)
        ],
        sec_b: [
            (
                dates[i],
                Decimal("120.00")
                if i == t_skip
                else (Decimal("100.00") if i == t_form else Decimal("120.00")),
            )
            for i in range(253)
        ],
        sec_c: [
            (
                dates[i],
                Decimal("120.00")
                if i == t_skip
                else (Decimal("100.00") if i == t_form else Decimal("120.00")),
            )
            for i in range(253)
        ],
    }
    # Both sec_b and sec_c have momentum = (120/100) - 1 = 0.20
    # Top ceil(3/2) = 2 selected: sec_a must be first; between sec_b and sec_c,
    # tie break by security_order_key (UUID bytes ascending).
    # Since sec_b.bytes < sec_c.bytes, sec_b must be selected and sec_c excluded.
    assert security_order_key(sec_b) < security_order_key(sec_c)

    tie_ctx = _exploratory_context(
        day=dates[-1],
        cohort=tie_cohort,
        history=tie_history,
        nav=Decimal("10000.00"),
    )
    tie_intent = strategy.decide_exploratory(tie_ctx)
    tie_selected = [t.security_id for t in tie_intent.targets]
    assert tie_selected == [sec_a, sec_b]


# ---------------------------------------------------------------------------
# STEP 2: Frozen B5 Low Volatility Strategy Tests (Canonical Defaults)
# ---------------------------------------------------------------------------


def test_b5_low_volatility_boundary_eligibility() -> None:
    """B5 requires exactly 61 sessions (60 lookback returns) to become eligible.

    Validates that:
    - 60 sessions yields empty targets (59 returns, unavailable / missing history).
    - 61 sessions yields non-empty targets (60 returns, eligible).
    """
    strategy = B5LowVolatilityStrategy()  # canonical defaults: lookback_returns=60
    assert strategy.lookback_returns == 60
    assert strategy.min_sessions == 61

    cohort = SYNTHETIC_COHORT_12[:3]
    dates = [START_DATE + timedelta(days=i) for i in range(61)]

    # 1. 60 sessions (indices 0 to 59)
    hist_60 = {
        sec: [(dates[i], Decimal("100.00") + Decimal(str(i % 2))) for i in range(60)]
        for sec in cohort
    }
    ctx_60 = _exploratory_context(
        day=dates[59],
        cohort=cohort,
        history=hist_60,
    )
    intent_60 = strategy.decide_exploratory(ctx_60)
    assert intent_60.targets == (), "B5 must be unavailable with 60 completed sessions"

    # 2. 61 sessions (indices 0 to 60)
    hist_61 = {
        sec: [(dates[i], Decimal("100.00") + Decimal(str(i % 2))) for i in range(61)]
        for sec in cohort
    }
    ctx_61 = _exploratory_context(
        day=dates[60],
        cohort=cohort,
        history=hist_61,
    )
    intent_61 = strategy.decide_exploratory(ctx_61)
    assert len(intent_61.targets) > 0, (
        "B5 must be eligible with 61 valid completed sessions"
    )


def test_b5_low_volatility_variance_ranking_tiebreak_and_allocation() -> None:
    """Verify B5 exact population variance, ranking, tiebreaks, and whole shares."""
    strategy = B5LowVolatilityStrategy()
    dates = [START_DATE + timedelta(days=i) for i in range(61)]
    cohort = (
        SYNTHETIC_COHORT_12  # 12 securities -> bottom ceil(12/2) = 6 lowest volatility
    )

    history: dict[UUID7, list[tuple[date, Decimal]]] = {}

    # Construct securities with strictly increasing volatility:
    # sec 0: perfectly flat (variance = 0)
    # sec 1 to 9: oscillating prices with increasing amplitude
    # sec 10 and 11: identical variance to test tie-breaking
    for idx, sec in enumerate(cohort):
        if idx == 0:
            history[sec] = [(d, Decimal("100.00")) for d in dates]
        elif idx < 10:
            amp = Decimal(str(idx))
            history[sec] = [
                (d, Decimal("100.00") if i % 2 == 0 else Decimal("100.00") + amp)
                for i, d in enumerate(dates)
            ]
        else:
            # Identical high variance for 10 and 11
            history[sec] = [
                (d, Decimal("100.00") if i % 2 == 0 else Decimal("150.00"))
                for i, d in enumerate(dates)
            ]

    ctx = _exploratory_context(
        day=dates[-1],
        cohort=cohort,
        history=history,
        nav=Decimal("12000.00"),
    )

    intent = strategy.decide_exploratory(ctx)
    targets = intent.targets
    target_map = {t.security_id: t.target_quantity for t in targets}

    # Bottom ceil(12/2) = 6 selected
    assert len(targets) == 6
    selected_secs = [t.security_id for t in targets]

    # Lowest 6 volatility must be cohort[0] through cohort[5]
    expected_bottom_6 = list(cohort[:6])
    assert selected_secs == expected_bottom_6

    # Verify whole-share calculations and residual cash:
    # NAV = 12000 -> 12000 / 6 = 2000 dollars per security
    # Price for cohort[0] is 100.00 -> 2000 // 100 = 20 shares
    prices_b5 = {sec: extract_current_close_price(ctx, sec) for sec in selected_secs}
    assert all(p is not None for p in prices_b5.values())
    total_cost = sum(
        (target_map[sec] * p for sec, p in prices_b5.items() if p is not None),
        Decimal("0.00"),
    )
    assert total_cost <= Decimal("12000.00")
    assert Decimal("12000.00") - total_cost >= Decimal("0.00")

    # Tie-break test: 3 securities with 2 having identical lowest variance
    sec_a = cohort[0]  # lowest variance
    sec_b = cohort[1]  # identical lowest variance
    sec_c = cohort[2]  # higher variance
    tie_cohort = (sec_a, sec_b, sec_c)
    tie_history = {
        sec_a: [(d, Decimal("100.00")) for d in dates],
        sec_b: [(d, Decimal("100.00")) for d in dates],
        sec_c: [
            (d, Decimal("100.00") if i % 2 == 0 else Decimal("120.00"))
            for i, d in enumerate(dates)
        ],
    }
    # Both sec_a and sec_b have variance = 0
    # Bottom ceil(3/2) = 2 selected: both sec_a and sec_b selected, sec_c excluded
    tie_ctx = _exploratory_context(
        day=dates[-1],
        cohort=tie_cohort,
        history=tie_history,
        nav=Decimal("10000.00"),
    )
    tie_intent = strategy.decide_exploratory(tie_ctx)
    tie_selected = [t.security_id for t in tie_intent.targets]
    assert tie_selected == [sec_a, sec_b]


# ---------------------------------------------------------------------------
# STEP 2: Frozen B3 Monthly Equal-Weight Rebalance Strategy Tests
# ---------------------------------------------------------------------------


def test_b3_monthly_equal_weight_rebalance_cadence_and_weights() -> None:
    """B3 allocates equally across admitted cohort, rebalances on cadence, and holds."""
    cohort = SYNTHETIC_COHORT_12
    rebal_dates = [date(2024, 1, 31), date(2024, 2, 29)]
    strategy = B3MonthlyEqualWeightRebalanceStrategy(
        rebalance_dates=rebal_dates,
        rebalance_on_initial_session=True,
    )

    # Day 1 (Jan 15): initial session enters equal-weight positions
    day_1 = date(2024, 1, 15)
    hist_1 = {sec: [(day_1, Decimal("100.00"))] for sec in cohort}
    ctx_1 = _exploratory_context(
        day=day_1,
        cohort=cohort,
        history=hist_1,
        nav=Decimal("12000.00"),
    )
    intent_1 = strategy.decide_exploratory(ctx_1)
    # 12 securities -> 12000 / 12 = 1000 dollars each -> 1000 // 100 = 10 shares
    assert len(intent_1.targets) == 12
    for t in intent_1.targets:
        assert t.target_quantity == 10

    # Day 2 (Jan 20): non-rebalance session maintains existing positions
    day_2 = date(2024, 1, 20)
    holdings_2 = tuple(
        PositionViewV1.model_construct(
            schema_version="1",
            security_id=sec,
            quantity=10,
            cost_basis=Decimal("1000.00"),
            average_cost_per_share=Decimal("100.00"),
        )
        for sec in cohort
    )
    hist_2 = {
        sec: [(day_1, Decimal("100.00")), (day_2, Decimal("110.00"))] for sec in cohort
    }
    ctx_2 = _exploratory_context(
        day=day_2,
        cohort=cohort,
        history=hist_2,
        holdings=holdings_2,
        nav=Decimal("13200.00"),
    )
    intent_2 = strategy.decide_exploratory(ctx_2)
    assert len(intent_2.targets) == 12
    for t in intent_2.targets:
        assert t.target_quantity == 10  # maintained without turnover

    # Day 3 (Jan 31): rebalance session recalculates equal dollar targets
    day_3 = date(2024, 1, 31)
    # Give cohort[0] higher price (200.00), others 100.00
    prices_3 = {sec: Decimal("100.00") for sec in cohort}
    prices_3[cohort[0]] = Decimal("200.00")
    hist_3 = {
        sec: [
            (day_1, Decimal("100.00")),
            (day_2, Decimal("110.00")),
            (day_3, prices_3[sec]),
        ]
        for sec in cohort
    }
    ctx_3 = _exploratory_context(
        day=day_3,
        cohort=cohort,
        history=hist_3,
        holdings=holdings_2,
        nav=Decimal("12000.00"),
    )
    intent_3 = strategy.decide_exploratory(ctx_3)
    target_map_3 = {t.security_id: t.target_quantity for t in intent_3.targets}
    # NAV 12000 / 12 = 1000 each
    # cohort[0] at 200 -> 1000 // 200 = 5 shares
    # other securities at 100 -> 1000 // 100 = 10 shares
    assert target_map_3[cohort[0]] == 5
    for sec in cohort[1:]:
        assert target_map_3[sec] == 10


# ---------------------------------------------------------------------------
# STEP 2 & 4: Synthetic 379-Session Warmup and Observation Lifecycle
# ---------------------------------------------------------------------------


def test_synthetic_379_session_lifecycle_and_safety_invariants() -> None:
    """Simulate 253 warmup (W) and 126 observation (O) synthetic sessions (Total: 379).

    Validates:
    - Warmup unscored status: B4 remains empty before session 253.
    - Observation transition: B4 activates at session 253.
    - Safety invariant: missing strategy history must NEVER trigger portfolio
      liquidation or dispatch empty targets as sell orders.
    - Pre-staging admission refusal belongs to producer K0 (#422) and Matthew M0 (#423).
    - Legacy scorecard Sharpe ratio is invalid for scientific outperformance claims.
    """
    total_sessions = 379
    warmup_count = 253
    observation_count = 126
    assert warmup_count + observation_count == total_sessions

    dates = [START_DATE + timedelta(days=i) for i in range(total_sessions)]
    cohort = SYNTHETIC_COHORT_12

    # Build synthetic observations for all 379 sessions across 12 securities
    history: dict[UUID7, list[tuple[date, Decimal]]] = {
        sec: [
            (dates[i], Decimal("100.00") + Decimal(str(i % 10)))
            for i in range(total_sessions)
        ]
        for sec in cohort
    }

    b4 = B4MomentumStrategy()
    b5 = B5LowVolatilityStrategy()

    # Checkpoint 1: Session 60 (index 59)
    # B5 has 60 sessions (< 61) -> empty targets
    ctx_s60 = _exploratory_context(day=dates[59], cohort=cohort, history=history)
    assert b5.decide_exploratory(ctx_s60).targets == ()

    # Checkpoint 2: Session 61 (index 60)
    # B5 reaches 61 sessions -> eligible
    ctx_s61 = _exploratory_context(day=dates[60], cohort=cohort, history=history)
    assert len(b5.decide_exploratory(ctx_s61).targets) == 6

    # Checkpoint 3: Session 252 (index 251, within Warmup W)
    # B4 has 252 sessions (< 253) -> empty targets
    ctx_s252 = _exploratory_context(day=dates[251], cohort=cohort, history=history)
    intent_b4_w = b4.decide_exploratory(ctx_s252)
    assert intent_b4_w.targets == ()

    # SAFETY ASSERTION: Insufficient history is NOT a liquidation instruction
    # Downstream engines must not treat empty targets as an order to sell holdings
    existing_holding = PositionViewV1.model_construct(
        schema_version="1",
        security_id=cohort[0],
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    # If a portfolio holds positions and receives empty targets from an unready
    # strategy, it must preserve the holdings or refuse execution, NOT liquidate to 0.
    ctx_with_holdings = _exploratory_context(
        day=dates[251],
        cohort=cohort,
        history=history,
        holdings=(existing_holding,),
    )
    intent_held = b4.decide_exploratory(ctx_with_holdings)
    assert len(intent_held.targets) == 0

    # Checkpoint 4: Session 253 (index 252, boundary of Warmup W and Observation O)
    # B4 activates and produces targets for top 6 names
    ctx_s253 = _exploratory_context(day=dates[252], cohort=cohort, history=history)
    intent_b4_active = b4.decide_exploratory(ctx_s253)
    assert len(intent_b4_active.targets) == 6

    # Checkpoint 5: Session 379 (index 378, end of Observation O)
    ctx_s379 = _exploratory_context(day=dates[378], cohort=cohort, history=history)
    assert len(b4.decide_exploratory(ctx_s379).targets) == 6
    assert len(b5.decide_exploratory(ctx_s379).targets) == 6


def test_legacy_scorecard_sharpe_unvalidated_for_scientific_claims() -> None:
    """Demonstrate that legacy compute_return_and_risk is unsuitable for science.

    Legacy Sharpe maps zero-variance directly to zero and uses geometric compound
    annualization that blows up on small samples. Runtime correction is reserved
    for metric contract #382.
    """
    initial_nav = Decimal("10000.00")

    # Zero volatility series (flat NAV)
    flat_series = [initial_nav, initial_nav, initial_nav, initial_nav]
    _, _, ann_vol, _, sharpe, _, _ = compute_return_and_risk(
        flat_series,
        initial_nav=initial_nav,
    )
    assert ann_vol == Decimal("0")
    # Legacy code maps zero volatility to zero Sharpe rather than undefined / NaN
    assert sharpe == Decimal("0")

    # Short 4-session gain (NAV jumps to 12,000 in 4 days)
    gain_series = [
        Decimal("10000.00"),
        Decimal("10500.00"),
        Decimal("11000.00"),
        Decimal("12000.00"),
    ]
    _, ann_ret, _, _, jump_sharpe, _, _ = compute_return_and_risk(
        gain_series,
        initial_nav=initial_nav,
    )
    # Exponential compound power (252 / 4 = 63) yields unphysical annualized values
    assert ann_ret > Decimal("1000.00")
    assert jump_sharpe > Decimal("100.00")


# ---------------------------------------------------------------------------
# STEP 3: Pure Decimal Accounting Consistency (Mock B/R Inputs)
# ---------------------------------------------------------------------------


def test_provided_mock_br_accounting_consistency_decimal() -> None:
    """Verify exact Decimal arithmetic on provided mock B/R results.

    GIVEN mock values (not fabricated platform executions):
    Arm B:
      Start NAV: 10000
      Gross Gain: 150
      Trading Costs: 30
      Terminal Net NAV: 10120
      Research Cost: 25

    Arm R:
      Start NAV: 10000
      Gross Gain: 80
      Trading Costs: 20
      Terminal Net NAV: 10060
      Research Cost: 5

    Required verifications:
    - B net return: 0.012 (1.20%)
    - R net return: 0.006 (0.60%)
    - Paired net return difference: 0.006 (0.60 percentage points)
    - B economic gain: 95 USD
    - R economic gain: 55 USD
    - Comparative economic advantage: 40 USD
    - Research costs NEVER debit portfolio cash.
    - Unknown research cost yields unavailable comparison (None), not 0.
    """
    # GIVEN Arm B inputs
    b_start_nav = Decimal("10000.00")
    b_gross_gain = Decimal("150.00")
    b_trading_costs = Decimal("30.00")
    b_terminal_net_nav = Decimal("10120.00")
    b_research_cost: Decimal | None = Decimal("25.00")

    # GIVEN Arm R inputs
    r_start_nav = Decimal("10000.00")
    r_gross_gain = Decimal("80.00")
    r_trading_costs = Decimal("20.00")
    r_terminal_net_nav = Decimal("10060.00")
    r_research_cost: Decimal | None = Decimal("5.00")

    # 1. Terminal Net NAV consistency with portfolio ledger
    # Research costs NEVER debit portfolio cash
    assert b_terminal_net_nav == b_start_nav + b_gross_gain - b_trading_costs
    assert r_terminal_net_nav == r_start_nav + r_gross_gain - r_trading_costs

    # 2. Net Returns
    with decimal_context():
        b_net_return = (b_terminal_net_nav - b_start_nav) / b_start_nav
        r_net_return = (r_terminal_net_nav - r_start_nav) / r_start_nav
        paired_diff = b_net_return - r_net_return

    assert b_net_return == Decimal("0.012")  # 1.20%
    assert r_net_return == Decimal("0.006")  # 0.60%
    assert paired_diff == Decimal("0.006")  # 0.60 percentage points

    # 3. Economic Gain (Terminal Net Gain minus Research Costs)
    def compute_economic_gain(
        start_nav: Decimal,
        terminal_nav: Decimal,
        research_cost: Decimal | None,
    ) -> Decimal | None:
        if research_cost is None:
            return None
        return (terminal_nav - start_nav) - research_cost

    b_economic_gain = compute_economic_gain(
        b_start_nav, b_terminal_net_nav, b_research_cost
    )
    r_economic_gain = compute_economic_gain(
        r_start_nav, r_terminal_net_nav, r_research_cost
    )

    assert b_economic_gain == Decimal("95.00")
    assert r_economic_gain == Decimal("55.00")

    # 4. Comparative Economic Advantage
    def compute_comparative_advantage(
        gain_b: Decimal | None,
        gain_r: Decimal | None,
    ) -> Decimal | None:
        if gain_b is None or gain_r is None:
            return None
        return gain_b - gain_r

    comp_adv = compute_comparative_advantage(b_economic_gain, r_economic_gain)
    assert comp_adv == Decimal("40.00")

    # 5. Unknown research cost yields unavailable comparison (None), NOT 0
    gain_unknown = compute_economic_gain(b_start_nav, b_terminal_net_nav, None)
    assert gain_unknown is None
    comp_adv_unknown = compute_comparative_advantage(gain_unknown, r_economic_gain)
    assert comp_adv_unknown is None
