"""Unit tests for M3 reference baseline strategies (Issue 166).

Validates protocol conformance, deterministic decision behavior, whole-share
allocations, and fail-closed handling across B0 through B5.
"""

import hashlib
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
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedFieldV1,
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_strategy import (
    ParameterizedStrategy,
    PositionViewV1,
    RuntimeStrategy,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1

SEC_A = UUID("018e0000-0000-7000-8000-000000000001")
SEC_B = UUID("018e0000-0000-7000-8000-000000000002")
SEC_C = UUID("018e0000-0000-7000-8000-000000000003")


def _session_key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(
    day: date = date(2026, 1, 15),
    authority: str = "realized",
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
            source_value=Decimal("1000"),
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
        reconstruction_hash=hashlib.sha256(
            f"{security_id}_{day.isoformat()}".encode()
        ).hexdigest(),
    )


def _exploratory_context(
    day: date = date(2026, 1, 15),
    cohort: tuple[UUID7, ...] = (SEC_A, SEC_B),
    prices: dict[UUID7, Decimal] | None = None,
    history: dict[UUID7, list[tuple[date, Decimal]]] | None = None,
    holdings: tuple[PositionViewV1, ...] = (),
    cash: Decimal = Decimal("10000.00"),
    nav: Decimal = Decimal("10000.00"),
) -> ExploratoryStrategyDecisionContextV1:
    session = _evaluation_session(day, authority="scheduled_reconstruction")
    prices_map = prices or {sec: Decimal("100.00") for sec in cohort}

    views = []
    for sec in cohort:
        observations = []
        if history and sec in history:
            for h_day, h_close in history[sec]:
                observations.append(_make_reconstructed_obs(sec, h_day, h_close))
        else:
            default_p = prices_map.get(sec, Decimal("100.00"))
            observations.append(_make_reconstructed_obs(sec, day, default_p))

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


def test_baseline_strategies_satisfy_protocols() -> None:
    strategies = [
        B0CashStrategy(),
        B1SingleBuyAndHoldStrategy(SEC_A),
        B2EqualWeightBuyAndHoldStrategy(),
        B3MonthlyEqualWeightRebalanceStrategy(),
        B4MomentumStrategy(),
        B5LowVolatilityStrategy(),
    ]
    for s in strategies:
        assert isinstance(s, RuntimeStrategy)
        assert isinstance(s, ExploratoryReconstructedRuntimeStrategy)
        assert isinstance(s, ParameterizedStrategy)
        ref = s.strategy_reference
        assert isinstance(ref.strategy_id, UUID)
        assert ref.strategy_id.version == 7
        assert ref.strategy_version == "1"
        assert len(ref.code_hash) == 64
        assert ref.artifact_reference.location.startswith("drift/baselines/")
        assert ref.artifact_reference.artifact_id.version == 7
        params = s.strategy_parameters
        assert isinstance(params, dict)


def test_b0_cash_emits_empty_targets() -> None:
    strategy = B0CashStrategy()
    ctx = _exploratory_context()
    intent = strategy.decide_exploratory(ctx)
    assert intent.session_key == ctx.session_key
    assert intent.decision_time == ctx.decision_cutoff
    assert intent.targets == ()


def test_b1_single_buy_and_hold_allocates_whole_shares_and_holds() -> None:
    strategy = B1SingleBuyAndHoldStrategy(SEC_A)

    # Day 1: Cash 10,000, Price 150 -> 10,000 // 150 = 66 shares
    ctx_day1 = _exploratory_context(
        day=date(2026, 1, 15),
        cohort=(SEC_A, SEC_B),
        prices={SEC_A: Decimal("150.00"), SEC_B: Decimal("50.00")},
        cash=Decimal("10000.00"),
    )
    intent1 = strategy.decide_exploratory(ctx_day1)
    assert len(intent1.targets) == 1
    assert intent1.targets[0].security_id == SEC_A
    assert intent1.targets[0].target_quantity == 66

    # Day 2: Holdings exist (66 shares) -> Maintain 66 shares without turnover
    holding = PositionViewV1.model_construct(
        schema_version="1",
        security_id=SEC_A,
        quantity=66,
        cost_basis=Decimal("9900.00"),
        average_cost_per_share=Decimal("150.00"),
    )
    ctx_day2 = _exploratory_context(
        day=date(2026, 1, 16),
        cohort=(SEC_A, SEC_B),
        prices={SEC_A: Decimal("200.00"), SEC_B: Decimal("50.00")},
        holdings=(holding,),
        cash=Decimal("100.00"),
    )
    intent2 = strategy.decide_exploratory(ctx_day2)
    assert len(intent2.targets) == 1
    assert intent2.targets[0].security_id == SEC_A
    assert intent2.targets[0].target_quantity == 66


def test_b1_single_buy_and_hold_unadmitted_or_insufficient_cash() -> None:
    # Target not admitted
    strategy = B1SingleBuyAndHoldStrategy(SEC_C)
    ctx = _exploratory_context(cohort=(SEC_A, SEC_B))
    assert strategy.decide_exploratory(ctx).targets == ()

    # Insufficient cash for 1 share
    strategy_a = B1SingleBuyAndHoldStrategy(SEC_A)
    ctx_low_cash = _exploratory_context(
        cohort=(SEC_A,),
        prices={SEC_A: Decimal("100.00")},
        cash=Decimal("50.00"),
    )
    assert strategy_a.decide_exploratory(ctx_low_cash).targets == ()


def test_b2_equal_weight_buy_and_hold_allocates_equally_and_holds() -> None:
    strategy = B2EqualWeightBuyAndHoldStrategy()

    # Cash 10,000 across 2 securities -> 5,000 each
    # SEC_A price 100 -> 50 shares; SEC_B price 200 -> 25 shares
    ctx1 = _exploratory_context(
        cohort=(SEC_A, SEC_B),
        prices={SEC_A: Decimal("100.00"), SEC_B: Decimal("200.00")},
        cash=Decimal("10000.00"),
    )
    intent1 = strategy.decide_exploratory(ctx1)
    target_dict = {t.security_id: t.target_quantity for t in intent1.targets}
    assert target_dict[SEC_A] == 50
    assert target_dict[SEC_B] == 25

    # Day 2: Holdings exist -> Preserved without turnover
    h_a = PositionViewV1.model_construct(
        schema_version="1",
        security_id=SEC_A,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    h_b = PositionViewV1.model_construct(
        schema_version="1",
        security_id=SEC_B,
        quantity=25,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("200.00"),
    )
    ctx2 = _exploratory_context(
        cohort=(SEC_A, SEC_B),
        holdings=(h_a, h_b),
        cash=Decimal("0.00"),
    )
    intent2 = strategy.decide_exploratory(ctx2)
    target_dict2 = {t.security_id: t.target_quantity for t in intent2.targets}
    assert target_dict2[SEC_A] == 50
    assert target_dict2[SEC_B] == 25


def test_b3_monthly_equal_weight_rebalance_cadence() -> None:
    rebalance_dates = [date(2026, 1, 30), date(2026, 2, 27)]
    strategy = B3MonthlyEqualWeightRebalanceStrategy(
        rebalance_dates=rebalance_dates,
        rebalance_on_initial_session=True,
    )

    # Initial session (Jan 15): enters positions
    ctx_init = _exploratory_context(
        day=date(2026, 1, 15),
        cohort=(SEC_A, SEC_B),
        prices={SEC_A: Decimal("100.00"), SEC_B: Decimal("100.00")},
        nav=Decimal("10000.00"),
    )
    intent_init = strategy.decide_exploratory(ctx_init)
    target_dict = {t.security_id: t.target_quantity for t in intent_init.targets}
    assert target_dict[SEC_A] == 50
    assert target_dict[SEC_B] == 50

    # Non-rebalance session (Jan 20): maintains positions
    h_a = PositionViewV1.model_construct(
        schema_version="1",
        security_id=SEC_A,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    h_b = PositionViewV1.model_construct(
        schema_version="1",
        security_id=SEC_B,
        quantity=50,
        cost_basis=Decimal("5000.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    ctx_mid = _exploratory_context(
        day=date(2026, 1, 20),
        cohort=(SEC_A, SEC_B),
        holdings=(h_a, h_b),
        prices={SEC_A: Decimal("120.00"), SEC_B: Decimal("80.00")},
        nav=Decimal("10000.00"),
    )
    intent_mid = strategy.decide_exploratory(ctx_mid)
    mid_targets = {t.security_id: t.target_quantity for t in intent_mid.targets}
    assert mid_targets[SEC_A] == 50
    assert mid_targets[SEC_B] == 50

    # Rebalance session (Jan 30): NAV is 12,000 -> 6,000 each
    # SEC_A price 120 -> 50 shares; SEC_B price 60 -> 100 shares
    ctx_rebal = _exploratory_context(
        day=date(2026, 1, 30),
        cohort=(SEC_A, SEC_B),
        holdings=(h_a, h_b),
        prices={SEC_A: Decimal("120.00"), SEC_B: Decimal("60.00")},
        nav=Decimal("12000.00"),
    )
    intent_rebal = strategy.decide_exploratory(ctx_rebal)
    rebal_targets = {t.security_id: t.target_quantity for t in intent_rebal.targets}
    assert rebal_targets[SEC_A] == 50
    assert rebal_targets[SEC_B] == 100


def test_b4_momentum_requires_history_and_ranks() -> None:
    strategy = B4MomentumStrategy()

    # With only 10 sessions of history: insufficient (< 253) -> empty targets
    hist_short = [
        (date(2025, 1, 1) + timedelta(days=i), Decimal("100.00")) for i in range(10)
    ]
    ctx_short = _exploratory_context(
        cohort=(SEC_A, SEC_B),
        history={SEC_A: hist_short, SEC_B: hist_short},
    )
    assert strategy.decide_exploratory(ctx_short).targets == ()

    # Generate 255 sessions for SEC_A, SEC_B, SEC_C
    # Start at 2025-01-01
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(255)]
    # SEC_A: climbs 100 to 200 (strong momentum)
    hist_a = [
        (d, Decimal("100") + Decimal(str(i * 100 // 254))) for i, d in enumerate(dates)
    ]
    # SEC_B: flat 100
    hist_b = [(d, Decimal("100.00")) for d in dates]
    # SEC_C: drops 100 to 50 (negative momentum)
    hist_c = [
        (d, Decimal("100") - Decimal(str(i * 50 // 254))) for i, d in enumerate(dates)
    ]

    # Current date is dates[-1]
    ctx_full = _exploratory_context(
        day=dates[-1],
        cohort=(SEC_A, SEC_B, SEC_C),
        history={SEC_A: hist_a, SEC_B: hist_b, SEC_C: hist_c},
        nav=Decimal("30000.00"),
    )
    intent = strategy.decide_exploratory(ctx_full)
    # 3 eligible securities -> top ceil(3/2) = 2 selected: SEC_A and SEC_B
    target_dict = {t.security_id: t.target_quantity for t in intent.targets}
    assert SEC_A in target_dict
    assert SEC_B in target_dict
    assert SEC_C not in target_dict
    # NAV 30,000 / 2 = 15,000 each
    # SEC_A close price is 200 -> 15,000 // 200 = 75
    # SEC_B close price is 100 -> 15,000 // 100 = 150
    assert target_dict[SEC_A] == 75
    assert target_dict[SEC_B] == 150


def test_b5_low_volatility_requires_history_and_selects_lowest_variance() -> None:
    strategy = B5LowVolatilityStrategy()

    # Insufficient history (< 61 sessions)
    dates_short = [date(2025, 1, 1) + timedelta(days=i) for i in range(30)]
    hist_short = [(d, Decimal("100.00")) for d in dates_short]
    ctx_short = _exploratory_context(
        day=dates_short[-1],
        cohort=(SEC_A, SEC_B),
        history={SEC_A: hist_short, SEC_B: hist_short},
    )
    assert strategy.decide_exploratory(ctx_short).targets == ()

    # Generate 65 sessions for SEC_A, SEC_B, SEC_C
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(65)]
    # SEC_A: zero volatility (perfectly constant price 100.00 -> returns are all 0)
    hist_a = [(d, Decimal("100.00")) for d in dates]
    # SEC_B: mild volatility (alternates 100, 101)
    hist_b = [
        (d, Decimal("100.00") if i % 2 == 0 else Decimal("101.00"))
        for i, d in enumerate(dates)
    ]
    # SEC_C: high volatility (alternates 100, 150)
    hist_c = [
        (d, Decimal("100.00") if i % 2 == 0 else Decimal("150.00"))
        for i, d in enumerate(dates)
    ]

    ctx_full = _exploratory_context(
        day=dates[-1],
        cohort=(SEC_A, SEC_B, SEC_C),
        history={SEC_A: hist_a, SEC_B: hist_b, SEC_C: hist_c},
        nav=Decimal("20000.00"),
    )
    intent = strategy.decide_exploratory(ctx_full)
    # 3 eligible -> bottom ceil(3/2) = 2 lowest variance: SEC_A and SEC_B
    target_dict = {t.security_id: t.target_quantity for t in intent.targets}
    assert SEC_A in target_dict
    assert SEC_B in target_dict
    assert SEC_C not in target_dict
    # NAV 20,000 / 2 = 10,000 each
    assert target_dict[SEC_A] > 0
    assert target_dict[SEC_B] > 0
