"""Unit tests for M2 Task 5 atomic next-open execution and cost application."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from observation_test_support import uid
from pydantic import ValidationError
from session_test_support import boundary_at, date_evidence, revision

from drift.domain.assertions import TemporalIntervalClaimV1
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    evaluation_session_hash,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_execution import (
    AtomicRebalanceCommitError,
    ExecutionFillV1,
    FillRejectionV1,
    IndeterminateExecutionError,
    RebalanceOutcomeV1,
    RebalancePlanV1,
)
from drift.domain.evaluator_portfolio import (
    PortfolioStateV1,
    SecurityHoldingV1,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import (
    ListingRole,
    ListingRoleVersionV1,
    ListingV1,
    ListingVenue,
)
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.execution import (
    AtomicRebalanceEngine,
    resolve_execution_listing,
    resolve_execution_listings,
)
from drift.evaluator.portfolio import initial_portfolio_state

SEC_A = uid(21)
SEC_B = uid(22)
SEC_C = uid(23)

LISTING_OLD = uid(31)
LISTING_NEW = uid(32)
LISTING_OTHER = uid(33)

EXEC_DATE = date(2026, 11, 30)
EXEC_OPEN = datetime(2026, 11, 30, 14, 30, tzinfo=UTC)
EXEC_CLOSE = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)

BEFORE = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
MIGRATION = datetime(2026, 6, 1, 14, 30, tzinfo=UTC)
AFTER = datetime(2027, 1, 4, 14, 30, tzinfo=UTC)

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64


# --- fixtures ---


def _key(day: date = EXEC_DATE) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _session(
    *, day: date = EXEC_DATE, opened: datetime = EXEC_OPEN
) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_key(day),
        opened_at=opened,
        closed_at=opened + timedelta(hours=6, minutes=30),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _cost_model(
    *,
    model_id: str = "task5_cost_v1",
    commission: str = "0.005",
    fixed_fee: str = "1.00",
    notional_bps: str = "2",
    slippage_bps: str = "10",
) -> EvaluationCostModelV1:
    draft = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id=model_id,
        commission_per_share=Decimal(commission),
        fixed_fee_per_order=Decimal(fixed_fee),
        notional_fee_basis_points=Decimal(notional_bps),
        adverse_slippage_basis_points=Decimal(slippage_bps),
        cost_model_hash=H0,
    )
    return draft.model_copy(
        update={"cost_model_hash": evaluation_cost_model_hash(draft)}
    )


ZERO_COST = _cost_model(
    model_id="zero_cost_v1",
    commission="0.00",
    fixed_fee="0.00",
    notional_bps="0",
    slippage_bps="0",
)


def _interval(start: datetime, end: datetime | None) -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(
        schema_version="1",
        start=boundary_at(start, 701),
        end=None if end is None else boundary_at(end, 702),
    )


def _role_record(
    *,
    listing_id: UUID,
    security_id: UUID7 = SEC_A,
    role: ListingRole = ListingRole.PRIMARY,
    start: datetime = BEFORE,
    end: datetime | None = None,
    interval: TemporalIntervalClaimV1 | None = None,
    suffix: int = 801,
) -> ListingRoleVersionV1:
    return ListingRoleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        security_id=security_id,
        listing_id=listing_id,
        role=role,
        methodology_id="synthetic-primary-v1",
        methodology_version="1",
        effective_interval=_interval(start, end) if interval is None else interval,
    )


def _listing(listing_id: UUID, venue: ListingVenue) -> ListingV1:
    return ListingV1(schema_version="1", listing_id=listing_id, venue=venue)


OLD = _listing(LISTING_OLD, ListingVenue.XNYS)
NEW = _listing(LISTING_NEW, ListingVenue.XNAS)
OTHER = _listing(LISTING_OTHER, ListingVenue.XASE)


def _state(
    *,
    cash: str = "10000.00",
    holdings: tuple[SecurityHoldingV1, ...] = (),
    day: date = EXEC_DATE,
) -> PortfolioStateV1:
    opening = initial_portfolio_state(session_key=_key(day), initial_cash=Decimal(cash))
    if not holdings:
        return opening
    return opening.model_copy(update={"holdings": holdings})


def _holding(security_id: UUID7, quantity: int, basis: str) -> SecurityHoldingV1:
    return SecurityHoldingV1(
        security_id=security_id, quantity=quantity, cost_basis=Decimal(basis)
    )


def _target(security_id: UUID7, quantity: int) -> SecurityTargetPositionV1:
    return SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)


def _listings_for(*securities: UUID7) -> dict[UUID7, ListingV1]:
    return {security_id: NEW for security_id in securities}


# --- listing resolution ---


def test_resolution_selects_the_unique_active_primary_listing() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD, NEW),
    )
    assert resolved == OLD


def test_resolution_follows_a_listing_migration_to_the_new_venue() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD, start=BEFORE, end=MIGRATION),
        _role_record(listing_id=LISTING_NEW, start=MIGRATION, suffix=811),
    )
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=records,
        listings=(OLD, NEW),
    )
    assert resolved == NEW
    assert resolved.venue is ListingVenue.XNAS


def test_resolution_before_a_migration_still_selects_the_old_listing() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD, start=BEFORE, end=MIGRATION),
        _role_record(listing_id=LISTING_NEW, start=MIGRATION, suffix=811),
    )
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(
            day=date(2026, 3, 2), opened=datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
        ),
        role_records=records,
        listings=(OLD, NEW),
    )
    assert resolved == OLD


def test_resolution_fails_closed_without_an_active_primary_listing() -> None:
    with pytest.raises(IndeterminateExecutionError, match="no active primary"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD, start=AFTER, end=None),),
            listings=(OLD,),
        )


def test_resolution_ignores_records_for_another_security() -> None:
    with pytest.raises(IndeterminateExecutionError, match="no active primary"):
        resolve_execution_listing(
            security_id=SEC_B,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD, security_id=SEC_A),),
            listings=(OLD,),
        )


def test_resolution_fails_closed_on_two_active_primary_listings() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(listing_id=LISTING_NEW, suffix=811),
    )
    with pytest.raises(IndeterminateExecutionError, match="not uniquely resolved"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=records,
            listings=(OLD, NEW),
        )


def test_resolution_accepts_duplicate_records_naming_one_listing() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(listing_id=LISTING_OLD, suffix=811),
    )
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=records,
        listings=(OLD,),
    )
    assert resolved == OLD


def test_resolution_fails_closed_on_an_ambiguous_effective_interval() -> None:
    ambiguous = TemporalIntervalClaimV1(
        schema_version="1", start=date_evidence(EXEC_DATE, 703), end=None
    )
    with pytest.raises(IndeterminateExecutionError, match="ambiguous"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD, interval=ambiguous),),
            listings=(OLD,),
        )


def test_resolution_fails_closed_on_an_ambiguous_record_beside_a_clear_one() -> None:
    ambiguous = TemporalIntervalClaimV1(
        schema_version="1", start=date_evidence(EXEC_DATE, 703), end=None
    )
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(listing_id=LISTING_NEW, interval=ambiguous, suffix=811),
    )
    with pytest.raises(IndeterminateExecutionError, match="ambiguous"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=records,
            listings=(OLD, NEW),
        )


def test_resolution_fails_closed_on_an_active_indeterminate_role() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(
            listing_id=LISTING_NEW, role=ListingRole.INDETERMINATE, suffix=811
        ),
    )
    with pytest.raises(IndeterminateExecutionError, match="indeterminate"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=records,
            listings=(OLD, NEW),
        )


def test_resolution_ignores_an_active_secondary_role() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(listing_id=LISTING_NEW, role=ListingRole.SECONDARY, suffix=811),
    )
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=records,
        listings=(OLD, NEW),
    )
    assert resolved == OLD


def test_resolution_fails_closed_without_the_resolved_listing_identity() -> None:
    with pytest.raises(IndeterminateExecutionError, match="listing identity"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(NEW,),
        )


def test_resolution_of_many_securities_returns_one_listing_each() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD, security_id=SEC_A),
        _role_record(listing_id=LISTING_NEW, security_id=SEC_B, suffix=811),
    )
    resolved = resolve_execution_listings(
        security_ids=(SEC_B, SEC_A),
        execution_session=_session(),
        role_records=records,
        listings=(OLD, NEW),
    )
    assert resolved == {SEC_A: OLD, SEC_B: NEW}


# --- planning and cost application ---


def test_plan_applies_adverse_slippage_and_costs_to_a_buy() -> None:
    engine = AtomicRebalanceEngine(cost_model=_cost_model())
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    (fill,) = plan.planned_fills
    assert fill.side == "buy"
    assert fill.quantity == 10
    assert fill.unadjusted_open_price == Decimal("100.00")
    assert fill.fill_price == Decimal("100.10")
    assert fill.gross_notional == Decimal("1001.00")
    assert fill.transaction_costs == Decimal("1.25")
    assert fill.cash_delta == Decimal("-1002.25")
    assert plan.required_cash == Decimal("1002.25")
    assert plan.gross_sell_proceeds == Decimal("0")
    assert plan.projected_cash == Decimal("8997.75")
    assert plan.is_funded


def test_plan_applies_adverse_slippage_and_costs_to_a_sell() -> None:
    engine = AtomicRebalanceEngine(cost_model=_cost_model())
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_A, 20, "800.00"),)),
        staged_targets=(_target(SEC_A, 0),),
        open_prices={SEC_A: Decimal("50.00")},
        execution_listings=_listings_for(SEC_A),
    )
    (fill,) = plan.planned_fills
    assert fill.side == "sell"
    assert fill.fill_price == Decimal("49.95")
    assert fill.gross_notional == Decimal("999.00")
    assert fill.transaction_costs == Decimal("1.30")
    assert fill.cash_delta == Decimal("997.70")
    assert plan.gross_sell_proceeds == Decimal("999.00")
    assert plan.sell_transaction_costs == Decimal("1.30")


def test_notional_fee_uses_the_unadjusted_open_price() -> None:
    engine = AtomicRebalanceEngine(
        cost_model=_cost_model(
            commission="0.00", fixed_fee="0.00", notional_bps="100", slippage_bps="1000"
        )
    )
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    (fill,) = plan.planned_fills
    assert fill.fill_price == Decimal("110.00")
    assert fill.transaction_costs == Decimal("1.00")


def test_plan_records_the_resolved_execution_listing_and_venue() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings={SEC_A: NEW},
    )
    (fill,) = plan.planned_fills
    assert fill.listing_id == LISTING_NEW
    assert fill.venue is ListingVenue.XNAS


def test_plan_skips_a_zero_delta_and_requires_no_price_for_it() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_A, 5, "50.00"),)),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={},
        execution_listings={},
    )
    assert plan.planned_fills == ()
    assert plan.projected_cash == Decimal("10000.00")


def test_plan_fails_closed_on_a_missing_open_price() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError, match="open price"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={},
            execution_listings=_listings_for(SEC_A),
        )


def test_plan_fails_closed_on_a_non_positive_open_price() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    for bad in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(IndeterminateExecutionError, match="open price"):
            engine.plan(
                state=_state(),
                staged_targets=(_target(SEC_A, 1),),
                open_prices={SEC_A: bad},
                execution_listings=_listings_for(SEC_A),
            )


def test_plan_fails_closed_without_a_resolved_execution_listing() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError, match="execution listing"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: Decimal("10.00")},
            execution_listings={},
        )


def test_plan_requires_staged_targets_to_cover_every_holding() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    with pytest.raises(ValueError, match="every held security"):
        engine.plan(
            state=_state(holdings=(_holding(SEC_B, 5, "50.00"),)),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: Decimal("10.00"), SEC_B: Decimal("10.00")},
            execution_listings=_listings_for(SEC_A, SEC_B),
        )


def test_plan_rejects_duplicate_staged_targets() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    with pytest.raises(ValueError, match="unique"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1), _target(SEC_A, 2)),
            open_prices={SEC_A: Decimal("10.00")},
            execution_listings=_listings_for(SEC_A),
        )


def test_plan_rejects_a_forged_negative_staged_target() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    forged = SecurityTargetPositionV1.model_construct(
        schema_version="1", security_id=SEC_A, target_quantity=-1
    )
    with pytest.raises(ValueError, match="non-negative"):
        engine.plan(
            state=_state(),
            staged_targets=(forged,),
            open_prices={SEC_A: Decimal("10.00")},
            execution_listings=_listings_for(SEC_A),
        )


def test_plan_orders_sells_before_buys_by_security_uuid_bytes() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(
            holdings=(_holding(SEC_B, 4, "40.00"), _holding(SEC_C, 4, "40.00"))
        ),
        staged_targets=(_target(SEC_A, 2), _target(SEC_B, 0), _target(SEC_C, 1)),
        open_prices={
            SEC_A: Decimal("10.00"),
            SEC_B: Decimal("10.00"),
            SEC_C: Decimal("10.00"),
        },
        execution_listings=_listings_for(SEC_A, SEC_B, SEC_C),
    )
    assert tuple((f.side, f.security_id) for f in plan.planned_fills) == (
        ("sell", SEC_B),
        ("sell", SEC_C),
        ("buy", SEC_A),
    )


def test_plan_is_immune_to_an_ambient_decimal_context() -> None:
    engine = AtomicRebalanceEngine(cost_model=_cost_model())
    pinned = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 7),),
        open_prices={SEC_A: Decimal("123.456789")},
        execution_listings=_listings_for(SEC_A),
    )
    with localcontext() as context:
        context.prec = 6
        hostile = engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 7),),
            open_prices={SEC_A: Decimal("123.456789")},
            execution_listings=_listings_for(SEC_A),
        )
    assert hostile == pinned


# --- atomic commit ---


def test_execution_commits_sells_before_buys() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    state = _state(cash="10.00", holdings=(_holding(SEC_B, 10, "500.00"),))
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 9), _target(SEC_B, 0)),
        open_prices={SEC_A: Decimal("110.00"), SEC_B: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "executed"
    assert outcome.state.cash_balance == Decimal("20.00")
    assert outcome.state.holdings == (_holding(SEC_A, 9, "990.00"),)


def test_execution_applies_slippage_and_deducts_transaction_costs() -> None:
    engine = AtomicRebalanceEngine(cost_model=_cost_model())
    outcome = engine.rebalance(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.state.cash_balance == Decimal("8997.75")
    assert outcome.state.holdings == (_holding(SEC_A, 10, "1002.25"),)
    assert outcome.state.cumulative_transaction_costs == Decimal("1.25")


def test_execution_clears_a_stale_mark() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert not outcome.state.is_marked
    assert outcome.state.holdings_market_value == Decimal("0")


def test_unfunded_rebalance_commits_zero_fills_and_halts() -> None:
    engine = AtomicRebalanceEngine(cost_model=_cost_model())
    state = _state(cash="100.00")
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.classification == "rejected"
    assert outcome.committed_fills == ()
    assert outcome.halt_stepping
    assert outcome.state == state
    assert outcome.state.holdings == ()
    assert outcome.state.cash_balance == Decimal("100.00")
    assert outcome.rejection is not None
    assert outcome.rejection.reason == "insufficient_cash"
    assert outcome.rejection.projected_cash == Decimal("-902.25")
    assert outcome.rejection.cash_shortfall == Decimal("902.25")


def test_multi_buy_shortfall_commits_zero_fills() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    state = _state(cash="1500.00")
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 10), _target(SEC_B, 10)),
        open_prices={SEC_A: Decimal("100.00"), SEC_B: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "rejected"
    assert outcome.committed_fills == ()
    assert outcome.state.holdings == ()
    assert outcome.state.cash_balance == Decimal("1500.00")
    assert outcome.rejection is not None
    assert outcome.rejection.required_cash == Decimal("2000.00")


def test_shortfall_in_one_buy_blocks_the_affordable_buy_too() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="1000.00"),
        staged_targets=(_target(SEC_A, 1), _target(SEC_B, 100)),
        open_prices={SEC_A: Decimal("10.00"), SEC_B: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "rejected"
    assert outcome.state.holdings == ()


def test_exactly_funded_rebalance_executes() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="1000.00"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.classification == "executed"
    assert outcome.state.cash_balance == Decimal("0")


def test_one_cent_short_rebalance_is_rejected() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="999.99"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: Decimal("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.classification == "rejected"
    assert outcome.rejection is not None
    assert outcome.rejection.cash_shortfall == Decimal("0.01")


def test_execute_rejects_a_plan_built_for_another_session() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(day=date(2026, 11, 27)),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    with pytest.raises(ValueError, match="session"):
        engine.execute(state=_state(), plan=plan)


def test_execute_rejects_a_plan_built_against_another_cash_balance() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    with pytest.raises(ValueError, match="cash"):
        engine.execute(state=_state(cash="9000.00"), plan=plan)


def test_execute_rejects_a_plan_built_against_other_holdings() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    moved = _state(cash="10000.00", holdings=(_holding(SEC_A, 3, "30.00"),))
    with pytest.raises(ValueError, match="plan positions"):
        engine.execute(state=moved, plan=plan)


def test_execute_rejects_a_plan_built_against_another_security() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00", holdings=(_holding(SEC_A, 3, "30.00"),)),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    swapped = _state(cash="10000.00", holdings=(_holding(SEC_B, 3, "30.00"),))
    with pytest.raises(ValueError, match="plan positions"):
        engine.execute(state=swapped, plan=plan)


def test_plan_positions_hash_tracks_held_quantities() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)

    def _hash_for(quantity: int) -> str:
        return engine.plan(
            state=_state(
                cash="10000.00", holdings=(_holding(SEC_B, quantity, "40.00"),)
            ),
            staged_targets=(_target(SEC_B, quantity),),
            open_prices={},
            execution_listings={},
        ).opening_positions_hash

    assert _hash_for(4) == _hash_for(4)
    assert _hash_for(4) != _hash_for(5)


def test_execute_refuses_to_partially_apply_an_unbookable_plan() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    state = _state(cash="1000.00")
    plan = engine.plan(
        state=state,
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    forged_fill = plan.planned_fills[0].model_copy(
        update={
            "quantity": 1,
            "side": "sell",
            "cash_delta": plan.planned_fills[0].gross_notional,
        }
    )
    forged_plan = plan.model_construct(
        **(dict(plan) | {"planned_fills": (forged_fill,)})
    )
    with pytest.raises(AtomicRebalanceCommitError):
        engine.execute(state=state, plan=forged_plan)


def test_execution_end_to_end_uses_the_migrated_primary_listing() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    records = (
        _role_record(listing_id=LISTING_OLD, start=BEFORE, end=MIGRATION),
        _role_record(listing_id=LISTING_NEW, start=MIGRATION, suffix=811),
    )
    session = _session()
    listings = resolve_execution_listings(
        security_ids=(SEC_A,),
        execution_session=session,
        role_records=records,
        listings=(OLD, NEW),
    )
    outcome = engine.rebalance(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=listings,
    )
    assert outcome.classification == "executed"
    (fill,) = outcome.committed_fills
    assert fill.listing_id == LISTING_NEW
    assert fill.venue is ListingVenue.XNAS


# --- execution contract invariants ---


def _fill(**overrides: object) -> ExecutionFillV1:
    base: dict[str, object] = {
        "security_id": SEC_A,
        "listing_id": LISTING_NEW,
        "venue": ListingVenue.XNAS,
        "side": "buy",
        "quantity": 10,
        "unadjusted_open_price": Decimal("100.00"),
        "fill_price": Decimal("100.10"),
        "gross_notional": Decimal("1001.00"),
        "transaction_costs": Decimal("1.25"),
        "cash_delta": Decimal("-1002.25"),
    }
    return ExecutionFillV1.model_validate(base | overrides)


def test_fill_accepts_the_reference_buy() -> None:
    assert _fill().to_portfolio_fill().fill_price == Decimal("100.10")


def test_fill_rejects_a_forged_gross_notional() -> None:
    with pytest.raises(ValidationError, match="gross notional"):
        _fill(gross_notional=Decimal("1.00"))


def test_fill_rejects_a_forged_cash_delta() -> None:
    with pytest.raises(ValidationError, match="cash delta"):
        _fill(cash_delta=Decimal("-1.00"))


def test_fill_rejects_a_sell_signed_as_a_cash_outflow() -> None:
    with pytest.raises(ValidationError, match="cash delta"):
        _fill(side="sell", cash_delta=Decimal("-1002.25"))


def test_fill_rejects_a_non_positive_price() -> None:
    with pytest.raises(ValidationError, match="price"):
        _fill(
            unadjusted_open_price=Decimal("0.00"),
            fill_price=Decimal("0.00"),
            gross_notional=Decimal("0.00"),
            cash_delta=Decimal("-1.25"),
        )


def test_fill_rejects_negative_transaction_costs() -> None:
    with pytest.raises(ValidationError, match="transaction costs"):
        _fill(
            transaction_costs=Decimal("-1.25"),
            cash_delta=Decimal("-999.75"),
        )


def test_rejection_requires_a_negative_projected_cash() -> None:
    with pytest.raises(ValidationError, match="projected cash"):
        FillRejectionV1(
            session_key=_key(),
            reason="insufficient_cash",
            current_cash=Decimal("100.00"),
            gross_sell_proceeds=Decimal("0"),
            sell_transaction_costs=Decimal("0"),
            required_cash=Decimal("50.00"),
            projected_cash=Decimal("50.00"),
            cash_shortfall=Decimal("0"),
        )


def test_rejection_requires_an_exact_shortfall() -> None:
    with pytest.raises(ValidationError, match="shortfall"):
        FillRejectionV1(
            session_key=_key(),
            reason="insufficient_cash",
            current_cash=Decimal("100.00"),
            gross_sell_proceeds=Decimal("0"),
            sell_transaction_costs=Decimal("0"),
            required_cash=Decimal("150.00"),
            projected_cash=Decimal("-50.00"),
            cash_shortfall=Decimal("10.00"),
        )


def _plan_and_state() -> tuple[RebalancePlanV1, PortfolioStateV1]:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    state = _state(cash="1000.00")
    plan = engine.plan(
        state=state,
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    return plan, state


def test_outcome_rejects_a_rejection_that_committed_fills() -> None:
    plan, state = _plan_and_state()
    rejection = FillRejectionV1(
        session_key=_key(),
        reason="insufficient_cash",
        current_cash=Decimal("1000.00"),
        gross_sell_proceeds=Decimal("0"),
        sell_transaction_costs=Decimal("0"),
        required_cash=Decimal("1010.00"),
        projected_cash=Decimal("-10.00"),
        cash_shortfall=Decimal("10.00"),
    )
    with pytest.raises(ValidationError, match="zero fills"):
        RebalanceOutcomeV1(
            classification="rejected",
            plan=plan,
            committed_fills=plan.planned_fills,
            rejection=rejection,
            state=state,
            halt_stepping=True,
        )


def test_outcome_rejects_a_rejection_that_does_not_halt() -> None:
    plan, state = _plan_and_state()
    rejection = FillRejectionV1(
        session_key=_key(),
        reason="insufficient_cash",
        current_cash=Decimal("1000.00"),
        gross_sell_proceeds=Decimal("0"),
        sell_transaction_costs=Decimal("0"),
        required_cash=Decimal("1010.00"),
        projected_cash=Decimal("-10.00"),
        cash_shortfall=Decimal("10.00"),
    )
    with pytest.raises(ValidationError, match="halt"):
        RebalanceOutcomeV1(
            classification="rejected",
            plan=plan,
            committed_fills=(),
            rejection=rejection,
            state=state,
            halt_stepping=False,
        )


def test_outcome_rejects_an_execution_carrying_a_rejection() -> None:
    plan, state = _plan_and_state()
    rejection = FillRejectionV1(
        session_key=_key(),
        reason="insufficient_cash",
        current_cash=Decimal("1000.00"),
        gross_sell_proceeds=Decimal("0"),
        sell_transaction_costs=Decimal("0"),
        required_cash=Decimal("1010.00"),
        projected_cash=Decimal("-10.00"),
        cash_shortfall=Decimal("10.00"),
    )
    with pytest.raises(ValidationError, match="rejection"):
        RebalanceOutcomeV1(
            classification="executed",
            plan=plan,
            committed_fills=plan.planned_fills,
            rejection=rejection,
            state=state,
            halt_stepping=False,
        )


def test_outcome_requires_an_execution_to_commit_the_whole_plan() -> None:
    plan, state = _plan_and_state()
    with pytest.raises(ValidationError, match="every planned fill"):
        RebalanceOutcomeV1(
            classification="executed",
            plan=plan,
            committed_fills=(),
            rejection=None,
            state=state,
            halt_stepping=False,
        )


def test_plan_rejects_a_forged_projected_cash() -> None:
    plan, _ = _plan_and_state()
    with pytest.raises(ValidationError, match="projected cash"):
        plan.model_copy(update={"projected_cash": Decimal("999999.00")})


def test_plan_rejects_a_forged_required_cash() -> None:
    plan, _ = _plan_and_state()
    with pytest.raises(ValidationError, match="required cash"):
        plan.model_copy(update={"required_cash": Decimal("0.00")})


def test_plan_rejects_uncanonical_fill_order() -> None:
    engine = AtomicRebalanceEngine(cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_B, 4, "40.00"),)),
        staged_targets=(_target(SEC_A, 2), _target(SEC_B, 0)),
        open_prices={SEC_A: Decimal("10.00"), SEC_B: Decimal("10.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    with pytest.raises(ValidationError, match="canonical"):
        plan.model_copy(update={"planned_fills": tuple(reversed(plan.planned_fills))})
