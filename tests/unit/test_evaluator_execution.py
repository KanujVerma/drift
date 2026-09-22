"""Unit tests for M2 Task 5 atomic next-open execution and cost application."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from observation_test_support import uid
from pydantic import ValidationError
from session_test_support import boundary_at, date_evidence, revision

from drift.domain.assertions import (
    BoundaryShape,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.common import UUID7
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
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
    ListingOpenPriceV1,
    RebalanceOutcomeV1,
    RebalancePlanV1,
    canonical_fill_order,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    PortfolioStateV1,
    SecurityHoldingV1,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.securities import (
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingRole,
    ListingRoleVersionV1,
    ListingTerminationReason,
    ListingTerminationVersionV1,
    ListingV1,
    ListingVenue,
    OutcomeEvidenceStatus,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.temporal import SourcePrecision
from drift.errors import DriftError
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


def _clock(
    *, sessions: tuple[EvaluationSessionV1, ...] | None = None
) -> SessionClockV1:
    """Realized-authority clock authorizing the execution session under test."""
    members = sessions if sessions is not None else (_session(),)
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=members,
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    candidate = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(candidate.model_dump())


EXEC_CLOCK = _clock()


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

FEE_ONLY = _cost_model(
    model_id="fee_only_v1",
    commission="0.00",
    fixed_fee="1.00",
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


UNKNOWN_TIME = TemporalBoundaryClaimV1(
    schema_version="1",
    shape=BoundaryShape.UNKNOWN,
    lower_bound=None,
    upper_bound=None,
    source_precision=SourcePrecision.UNKNOWN,
    source_time_label=None,
    source_timezone=None,
    evidence_reference=None,
)


def _termination(
    *,
    listing_id: UUID = LISTING_OLD,
    effective: TemporalBoundaryClaimV1 | None = None,
    at: datetime = BEFORE,
    suffix: int = 821,
) -> ListingTerminationVersionV1:
    boundary = boundary_at(at, suffix) if effective is None else effective
    return ListingTerminationVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=listing_id,
        reason=ListingTerminationReason.EXCHANGE_DELISTING,
        source_reason_code=None,
        source_reason_text=None,
        last_regular_trade_time=boundary,
        effective_time=boundary,
        successor_relationship_ids=(),
        outcome_evidence_status=OutcomeEvidenceStatus.UNKNOWN,
    )


def _lifecycle(
    *,
    kind: ListingLifecycleEventKind,
    listing_id: UUID = LISTING_OLD,
    effective: TemporalBoundaryClaimV1 | None = None,
    at: datetime = BEFORE,
    suffix: int = 831,
) -> ListingLifecycleVersionV1:
    return ListingLifecycleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=listing_id,
        event_kind=kind,
        effective_time=boundary_at(at, suffix) if effective is None else effective,
        related_listing_id=None,
    )


def _listing(listing_id: UUID, venue: ListingVenue) -> ListingV1:
    return ListingV1(schema_version="1", listing_id=listing_id, venue=venue)


OLD = _listing(LISTING_OLD, ListingVenue.XNYS)
NEW = _listing(LISTING_NEW, ListingVenue.XNAS)
OTHER = _listing(LISTING_OTHER, ListingVenue.XASE)


def _execution_admission() -> ExploratoryEvaluationAdmissionV1:
    """Exploratory lane admission for books under execution test."""
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash="b" * 64,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash="0" * 64,
    )
    return draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )


EXECUTION_ADMISSION = _execution_admission()


def _state(
    *,
    cash: str = "10000.00",
    holdings: tuple[SecurityHoldingV1, ...] = (),
    day: date = EXEC_DATE,
) -> PortfolioStateV1:
    balance = Decimal(cash)
    # The opening-state factory requires strictly positive seed cash, so a
    # zero-cash book is seeded then drawn down to the balance under test.
    seed = balance if balance > Decimal("0") else Decimal("1.00")
    opening = initial_portfolio_state(
        session_key=_key(day),
        initial_cash=seed,
        admission=EXECUTION_ADMISSION,
    )
    update: dict[str, object] = {}
    if seed != balance:
        update |= {"cash_balance": balance, "net_asset_value": balance}
    if holdings:
        update["holdings"] = holdings
    if not update:
        return opening
    return opening.model_copy(update=update)


def _holding(security_id: UUID7, quantity: int, basis: str) -> SecurityHoldingV1:
    return SecurityHoldingV1(
        security_id=security_id, quantity=quantity, cost_basis=Decimal(basis)
    )


def _target(security_id: UUID7, quantity: int) -> SecurityTargetPositionV1:
    return SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)


def _listings_for(*securities: UUID7) -> dict[UUID7, ListingV1]:
    return {security_id: NEW for security_id in securities}


def _price(amount: str, listing: ListingV1 = NEW) -> ListingOpenPriceV1:
    return ListingOpenPriceV1(
        listing_id=listing.listing_id,
        venue=listing.venue,
        unadjusted_open_price=Decimal(amount),
    )


# --- listing resolution ---


def test_resolution_selects_the_unique_active_primary_listing() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD, NEW),
        termination_records=(),
        lifecycle_records=(),
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
        termination_records=(),
        lifecycle_records=(),
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
        termination_records=(),
        lifecycle_records=(),
    )
    assert resolved == OLD


def test_resolution_fails_closed_without_an_active_primary_listing() -> None:
    with pytest.raises(IndeterminateExecutionError, match="no active primary"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD, start=AFTER, end=None),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(),
        )


def test_resolution_ignores_records_for_another_security() -> None:
    with pytest.raises(IndeterminateExecutionError, match="no active primary"):
        resolve_execution_listing(
            security_id=SEC_B,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD, security_id=SEC_A),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(),
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
            termination_records=(),
            lifecycle_records=(),
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
        termination_records=(),
        lifecycle_records=(),
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
            termination_records=(),
            lifecycle_records=(),
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
            termination_records=(),
            lifecycle_records=(),
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
            termination_records=(),
            lifecycle_records=(),
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
        termination_records=(),
        lifecycle_records=(),
    )
    assert resolved == OLD


def test_resolution_fails_closed_without_the_resolved_listing_identity() -> None:
    with pytest.raises(IndeterminateExecutionError, match="listing identity"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(NEW,),
            termination_records=(),
            lifecycle_records=(),
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
        termination_records=(),
        lifecycle_records=(),
    )
    assert resolved == {SEC_A: OLD, SEC_B: NEW}


def test_resolution_fails_closed_on_contradictory_role_evidence() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD),
        _role_record(listing_id=LISTING_OLD, role=ListingRole.SECONDARY, suffix=811),
    )
    with pytest.raises(IndeterminateExecutionError, match="contradictory"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=records,
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(),
        )


def test_resolution_fails_closed_on_a_terminated_listing() -> None:
    with pytest.raises(IndeterminateExecutionError, match="terminated"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(_termination(at=MIGRATION),),
            lifecycle_records=(),
        )


def test_resolution_ignores_a_termination_that_has_not_happened_yet() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(_termination(at=AFTER),),
        lifecycle_records=(),
    )
    assert resolved == OLD


def test_resolution_ignores_a_termination_of_another_listing() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(_termination(listing_id=LISTING_NEW, at=BEFORE),),
        lifecycle_records=(),
    )
    assert resolved == OLD


def test_resolution_fails_closed_on_a_termination_effective_at_the_open() -> None:
    # A listing terminated exactly as the execution session opens has already
    # terminated for that open, so the boundary is inclusive.
    with pytest.raises(IndeterminateExecutionError, match="terminated"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(_termination(at=EXEC_OPEN),),
            lifecycle_records=(),
        )


def test_resolution_fails_closed_on_an_unknown_termination_time() -> None:
    with pytest.raises(
        IndeterminateExecutionError, match="termination evidence has an ambiguous"
    ):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(_termination(effective=UNKNOWN_TIME),),
            lifecycle_records=(),
        )


def test_resolution_fails_closed_on_a_suspended_listing() -> None:
    with pytest.raises(IndeterminateExecutionError, match="suspended"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=MIGRATION),
            ),
        )


def test_resolution_accepts_a_suspension_that_was_provably_resumed() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(),
        lifecycle_records=(
            _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=BEFORE),
            _lifecycle(
                kind=ListingLifecycleEventKind.RESUMED, at=MIGRATION, suffix=841
            ),
        ),
    )
    assert resolved == OLD


def test_resolution_fails_closed_when_a_resume_precedes_its_suspension() -> None:
    with pytest.raises(IndeterminateExecutionError, match="suspended"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=MIGRATION),
                _lifecycle(
                    kind=ListingLifecycleEventKind.RESUMED, at=BEFORE, suffix=841
                ),
            ),
        )


def test_resolution_ignores_a_suspension_that_has_not_happened_yet() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(),
        lifecycle_records=(
            _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=AFTER),
        ),
    )
    assert resolved == OLD


def test_resolution_ignores_a_non_suspending_lifecycle_event() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(),
        lifecycle_records=(
            _lifecycle(kind=ListingLifecycleEventKind.ADMITTED, at=BEFORE),
        ),
    )
    assert resolved == OLD


def test_resolution_fails_closed_on_a_simultaneous_resumption() -> None:
    with pytest.raises(IndeterminateExecutionError, match="suspended"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=MIGRATION),
                _lifecycle(
                    kind=ListingLifecycleEventKind.RESUMED, at=MIGRATION, suffix=841
                ),
            ),
        )


def test_resolution_does_not_treat_an_admission_as_a_resumption() -> None:
    with pytest.raises(IndeterminateExecutionError, match="suspended"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=BEFORE),
                _lifecycle(
                    kind=ListingLifecycleEventKind.ADMITTED, at=MIGRATION, suffix=841
                ),
            ),
        )


def test_resolution_fails_closed_on_a_suspension_effective_at_the_open() -> None:
    with pytest.raises(IndeterminateExecutionError, match="suspended"):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(kind=ListingLifecycleEventKind.SUSPENDED, at=EXEC_OPEN),
            ),
        )


def test_resolution_fails_closed_on_an_unknown_suspension_time() -> None:
    with pytest.raises(
        IndeterminateExecutionError, match="lifecycle evidence has an ambiguous"
    ):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=_session(),
            role_records=(_role_record(listing_id=LISTING_OLD),),
            listings=(OLD,),
            termination_records=(),
            lifecycle_records=(
                _lifecycle(
                    kind=ListingLifecycleEventKind.SUSPENDED, effective=UNKNOWN_TIME
                ),
            ),
        )


def test_resolution_ignores_a_suspension_of_another_listing() -> None:
    resolved = resolve_execution_listing(
        security_id=SEC_A,
        execution_session=_session(),
        role_records=(_role_record(listing_id=LISTING_OLD),),
        listings=(OLD,),
        termination_records=(),
        lifecycle_records=(
            _lifecycle(
                kind=ListingLifecycleEventKind.SUSPENDED,
                listing_id=LISTING_NEW,
                at=BEFORE,
            ),
        ),
    )
    assert resolved == OLD


def test_many_security_resolution_consults_termination_evidence() -> None:
    records = (
        _role_record(listing_id=LISTING_OLD, security_id=SEC_A),
        _role_record(listing_id=LISTING_NEW, security_id=SEC_B, suffix=811),
    )
    with pytest.raises(IndeterminateExecutionError, match="terminated"):
        resolve_execution_listings(
            security_ids=(SEC_A, SEC_B),
            execution_session=_session(),
            role_records=records,
            listings=(OLD, NEW),
            termination_records=(_termination(listing_id=LISTING_NEW, at=BEFORE),),
            lifecycle_records=(),
        )


# --- planning and cost application ---


def test_plan_applies_adverse_slippage_and_costs_to_a_buy() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=_cost_model())
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: _price("100.00")},
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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=_cost_model())
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_A, 20, "800.00"),)),
        staged_targets=(_target(SEC_A, 0),),
        open_prices={SEC_A: _price("50.00")},
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
        session_clock=EXEC_CLOCK,
        cost_model=_cost_model(
            commission="0.00", fixed_fee="0.00", notional_bps="100", slippage_bps="1000"
        ),
    )
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    (fill,) = plan.planned_fills
    assert fill.fill_price == Decimal("110.00")
    assert fill.transaction_costs == Decimal("1.00")


def test_plan_records_the_resolved_execution_listing_and_venue() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings={SEC_A: NEW},
    )
    (fill,) = plan.planned_fills
    assert fill.listing_id == LISTING_NEW
    assert fill.venue is ListingVenue.XNAS


def test_plan_skips_a_zero_delta_and_requires_no_price_for_it() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_A, 5, "50.00"),)),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={},
        execution_listings={},
    )
    assert plan.planned_fills == ()
    assert plan.projected_cash == Decimal("10000.00")


def test_plan_fails_closed_on_a_missing_open_price() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError, match="open price"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={},
            execution_listings=_listings_for(SEC_A),
        )


def test_open_price_contract_rejects_a_non_positive_amount() -> None:
    for bad in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(ValidationError, match="open price"):
            ListingOpenPriceV1(
                listing_id=LISTING_NEW,
                venue=ListingVenue.XNAS,
                unadjusted_open_price=bad,
            )


def test_plan_fails_closed_on_a_non_positive_open_price() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    for bad in (Decimal("0.00"), Decimal("-1.00")):
        forged = ListingOpenPriceV1.model_construct(
            schema_version="1",
            listing_id=LISTING_NEW,
            venue=ListingVenue.XNAS,
            unadjusted_open_price=bad,
        )
        with pytest.raises(IndeterminateExecutionError, match="open price"):
            engine.plan(
                state=_state(),
                staged_targets=(_target(SEC_A, 1),),
                open_prices={SEC_A: forged},
                execution_listings=_listings_for(SEC_A),
            )


def test_plan_fails_closed_on_a_price_bound_to_another_listing() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError, match="bound to listing"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: _price("10.00", OLD)},
            execution_listings={SEC_A: NEW},
        )


def test_plan_fails_closed_on_a_price_bound_to_another_venue() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    mislabelled = ListingOpenPriceV1(
        listing_id=LISTING_NEW,
        venue=ListingVenue.XNYS,
        unadjusted_open_price=Decimal("10.00"),
    )
    with pytest.raises(IndeterminateExecutionError, match="bound to venue"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: mislabelled},
            execution_listings={SEC_A: NEW},
        )


def test_migrated_security_refuses_the_price_from_its_old_listing() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    records = (
        _role_record(listing_id=LISTING_OLD, start=BEFORE, end=MIGRATION),
        _role_record(listing_id=LISTING_NEW, start=MIGRATION, suffix=811),
    )
    listings = resolve_execution_listings(
        security_ids=(SEC_A,),
        execution_session=_session(),
        role_records=records,
        listings=(OLD, NEW),
        termination_records=(),
        lifecycle_records=(),
    )
    assert listings == {SEC_A: NEW}
    with pytest.raises(IndeterminateExecutionError, match="bound to listing"):
        engine.rebalance(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: _price("10.00", OLD)},
            execution_listings=listings,
        )


def test_plan_fails_closed_without_a_resolved_execution_listing() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError, match="execution listing"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: _price("10.00")},
            execution_listings={},
        )


def test_plan_requires_staged_targets_to_cover_every_holding() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    # An uncovered holding leaves the intended position unknowable, so it
    # belongs to the execution taxonomy rather than to a bare ValueError.
    with pytest.raises(IndeterminateExecutionError, match="every held security"):
        engine.plan(
            state=_state(holdings=(_holding(SEC_B, 5, "50.00"),)),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: _price("10.00"), SEC_B: _price("10.00")},
            execution_listings=_listings_for(SEC_A, SEC_B),
        )


def test_uncovered_holding_stays_inside_the_execution_error_taxonomy() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    with pytest.raises(IndeterminateExecutionError) as caught:
        engine.plan(
            state=_state(holdings=(_holding(SEC_B, 5, "50.00"),)),
            staged_targets=(_target(SEC_A, 1),),
            open_prices={SEC_A: _price("10.00"), SEC_B: _price("10.00")},
            execution_listings=_listings_for(SEC_A, SEC_B),
        )
    assert isinstance(caught.value, DriftError)
    assert "every held security" in str(caught.value)


def test_plan_rejects_duplicate_staged_targets() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    with pytest.raises(ValueError, match="unique"):
        engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 1), _target(SEC_A, 2)),
            open_prices={SEC_A: _price("10.00")},
            execution_listings=_listings_for(SEC_A),
        )


def test_plan_rejects_a_forged_negative_staged_target() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    forged = SecurityTargetPositionV1.model_construct(
        schema_version="1", security_id=SEC_A, target_quantity=-1
    )
    with pytest.raises(ValueError, match="non-negative"):
        engine.plan(
            state=_state(),
            staged_targets=(forged,),
            open_prices={SEC_A: _price("10.00")},
            execution_listings=_listings_for(SEC_A),
        )


def test_plan_orders_sells_before_buys_by_security_uuid_bytes() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(
            holdings=(_holding(SEC_B, 4, "40.00"), _holding(SEC_C, 4, "40.00"))
        ),
        staged_targets=(_target(SEC_A, 2), _target(SEC_B, 0), _target(SEC_C, 1)),
        open_prices={
            SEC_A: _price("10.00"),
            SEC_B: _price("10.00"),
            SEC_C: _price("10.00"),
        },
        execution_listings=_listings_for(SEC_A, SEC_B, SEC_C),
    )
    assert tuple((f.side, f.security_id) for f in plan.planned_fills) == (
        ("sell", SEC_B),
        ("sell", SEC_C),
        ("buy", SEC_A),
    )


def test_plan_orders_sells_by_descending_cash_delta_before_uuid_bytes() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=FEE_ONLY)
    plan = engine.plan(
        state=_state(
            cash="0.00",
            holdings=(_holding(SEC_A, 1, "5.00"), _holding(SEC_B, 10, "500.00")),
        ),
        staged_targets=(_target(SEC_A, 0), _target(SEC_B, 0)),
        open_prices={SEC_A: _price("0.10"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    # SEC_A sorts first by UUID bytes but its fixed fee exceeds its proceeds,
    # so booking it first would drive running cash negative.
    assert SEC_A.bytes < SEC_B.bytes
    assert tuple(fill.security_id for fill in plan.planned_fills) == (SEC_B, SEC_A)
    assert tuple(fill.cash_delta for fill in plan.planned_fills) == (
        Decimal("999.00"),
        Decimal("-0.90"),
    )


def test_funded_rebalance_with_a_fee_heavy_sell_commits() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=FEE_ONLY)
    outcome = engine.rebalance(
        state=_state(
            cash="0.00",
            holdings=(_holding(SEC_A, 1, "5.00"), _holding(SEC_B, 10, "500.00")),
        ),
        staged_targets=(_target(SEC_A, 0), _target(SEC_B, 0)),
        open_prices={SEC_A: _price("0.10"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.plan.projected_cash == Decimal("998.10")
    assert outcome.plan.is_funded
    assert outcome.classification == "executed"
    assert outcome.state.cash_balance == Decimal("998.10")
    assert outcome.state.holdings == ()


def test_fee_heavy_liquidation_outcome_is_invariant_under_swapped_uuids() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=FEE_ONLY)

    def _liquidate(cheap: UUID7, rich: UUID7) -> RebalanceOutcomeV1:
        holdings = tuple(
            sorted(
                (_holding(cheap, 1, "5.00"), _holding(rich, 10, "500.00")),
                key=lambda holding: holding.security_id.bytes,
            )
        )
        return engine.rebalance(
            state=_state(cash="0.00", holdings=holdings),
            staged_targets=tuple(
                sorted(
                    (_target(cheap, 0), _target(rich, 0)),
                    key=lambda target: target.security_id.bytes,
                )
            ),
            open_prices={cheap: _price("0.10"), rich: _price("100.00")},
            execution_listings=_listings_for(cheap, rich),
        )

    forward = _liquidate(SEC_A, SEC_B)
    swapped = _liquidate(SEC_B, SEC_A)
    assert forward.classification == swapped.classification == "executed"
    assert forward.state.cash_balance == swapped.state.cash_balance
    assert forward.state.cash_balance == Decimal("998.10")


def test_plan_rejects_sells_reordered_by_uuid_bytes() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=FEE_ONLY)
    plan = engine.plan(
        state=_state(
            cash="0.00",
            holdings=(_holding(SEC_A, 1, "5.00"), _holding(SEC_B, 10, "500.00")),
        ),
        staged_targets=(_target(SEC_A, 0), _target(SEC_B, 0)),
        open_prices={SEC_A: _price("0.10"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    uuid_ordered = tuple(
        sorted(plan.planned_fills, key=lambda fill: fill.security_id.bytes)
    )
    assert uuid_ordered != plan.planned_fills
    with pytest.raises(ValidationError, match="canonical"):
        plan.model_copy(update={"planned_fills": uuid_ordered})


def test_plan_breaks_equal_sell_cash_deltas_by_security_uuid_bytes() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(
            cash="0.00",
            holdings=(
                _holding(SEC_A, 2, "20.00"),
                _holding(SEC_B, 2, "20.00"),
                _holding(SEC_C, 2, "20.00"),
            ),
        ),
        staged_targets=(_target(SEC_A, 0), _target(SEC_B, 0), _target(SEC_C, 0)),
        open_prices={
            SEC_A: _price("10.00"),
            SEC_B: _price("10.00"),
            SEC_C: _price("10.00"),
        },
        execution_listings=_listings_for(SEC_A, SEC_B, SEC_C),
    )
    assert tuple(fill.cash_delta for fill in plan.planned_fills) == (
        Decimal("20.00"),
        Decimal("20.00"),
        Decimal("20.00"),
    )
    assert tuple(fill.security_id for fill in plan.planned_fills) == (
        SEC_A,
        SEC_B,
        SEC_C,
    )


def _sell_fill(security_id: UUID7, price: str, quantity: int = 1) -> ExecutionFillV1:
    gross = Decimal(price) * quantity
    return ExecutionFillV1(
        security_id=security_id,
        listing_id=LISTING_NEW,
        venue=ListingVenue.XNAS,
        side="sell",
        quantity=quantity,
        unadjusted_open_price=Decimal(price),
        fill_price=Decimal(price),
        gross_notional=gross,
        transaction_costs=Decimal("1.00"),
        cash_delta=gross - Decimal("1.00"),
    )


def test_canonical_order_puts_the_largest_cash_positive_sell_first() -> None:
    cheap = _sell_fill(SEC_A, "0.10")
    rich = _sell_fill(SEC_B, "100.00")
    for supplied in ((cheap, rich), (rich, cheap)):
        assert canonical_fill_order(supplied) == (rich, cheap)


def test_canonical_order_breaks_equal_cash_deltas_by_security_uuid_bytes() -> None:
    first = _sell_fill(SEC_A, "10.00")
    second = _sell_fill(SEC_B, "10.00")
    third = _sell_fill(SEC_C, "10.00")
    assert first.cash_delta == second.cash_delta == third.cash_delta
    # Supplied in reverse UUID order, so a missing tiebreak pass would be
    # invisible if the caller happened to supply them already sorted.
    assert canonical_fill_order((third, second, first)) == (first, second, third)


def test_canonical_order_sorts_buys_by_security_uuid_bytes() -> None:
    first = _fill(security_id=SEC_A)
    second = _fill(security_id=SEC_B)
    third = _fill(security_id=SEC_C)
    assert all(fill.side == "buy" for fill in (first, second, third))
    assert canonical_fill_order((third, first, second)) == (first, second, third)


def test_canonical_order_puts_every_sell_before_every_buy() -> None:
    buy = _fill(security_id=SEC_A)
    sell = _sell_fill(SEC_C, "0.10")
    # The sell is cash-negative after its fee and sorts last by UUID bytes,
    # and still precedes the buy.
    assert sell.cash_delta < Decimal("0")
    assert canonical_fill_order((buy, sell)) == (sell, buy)


def test_canonical_order_is_stable_under_an_ambient_decimal_context() -> None:
    fills = (_sell_fill(SEC_B, "100.0000001"), _sell_fill(SEC_A, "100.0000002"))
    pinned = canonical_fill_order(fills)
    with localcontext() as context:
        context.prec = 4
        hostile = canonical_fill_order(fills)
    assert hostile == pinned == (fills[1], fills[0])


def test_plan_is_immune_to_an_ambient_decimal_context() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=_cost_model())
    pinned = engine.plan(
        state=_state(),
        staged_targets=(_target(SEC_A, 7),),
        open_prices={SEC_A: _price("123.456789")},
        execution_listings=_listings_for(SEC_A),
    )
    with localcontext() as context:
        context.prec = 6
        hostile = engine.plan(
            state=_state(),
            staged_targets=(_target(SEC_A, 7),),
            open_prices={SEC_A: _price("123.456789")},
            execution_listings=_listings_for(SEC_A),
        )
    assert hostile == pinned


# --- atomic commit ---


def test_execution_commits_sells_before_buys() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    state = _state(cash="10.00", holdings=(_holding(SEC_B, 10, "500.00"),))
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 9), _target(SEC_B, 0)),
        open_prices={SEC_A: _price("110.00"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "executed"
    assert outcome.state.cash_balance == Decimal("20.00")
    assert outcome.state.holdings == (_holding(SEC_A, 9, "990.00"),)


def test_execution_applies_slippage_and_deducts_transaction_costs() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=_cost_model())
    outcome = engine.rebalance(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: _price("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.state.cash_balance == Decimal("8997.75")
    assert outcome.state.holdings == (_holding(SEC_A, 10, "1002.25"),)
    assert outcome.state.cumulative_transaction_costs == Decimal("1.25")


def test_execution_clears_a_stale_mark() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert not outcome.state.is_marked
    assert outcome.state.holdings_market_value == Decimal("0")


def test_unfunded_rebalance_commits_zero_fills_and_halts() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=_cost_model())
    state = _state(cash="100.00")
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: _price("100.00")},
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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    state = _state(cash="1500.00")
    outcome = engine.rebalance(
        state=state,
        staged_targets=(_target(SEC_A, 10), _target(SEC_B, 10)),
        open_prices={SEC_A: _price("100.00"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "rejected"
    assert outcome.committed_fills == ()
    assert outcome.state.holdings == ()
    assert outcome.state.cash_balance == Decimal("1500.00")
    assert outcome.rejection is not None
    assert outcome.rejection.required_cash == Decimal("2000.00")


def test_shortfall_in_one_buy_blocks_the_affordable_buy_too() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="1000.00"),
        staged_targets=(_target(SEC_A, 1), _target(SEC_B, 100)),
        open_prices={SEC_A: _price("10.00"), SEC_B: _price("100.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    assert outcome.classification == "rejected"
    assert outcome.state.holdings == ()


def test_exactly_funded_rebalance_executes() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="1000.00"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: _price("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.classification == "executed"
    assert outcome.state.cash_balance == Decimal("0")


def test_one_cent_short_rebalance_is_rejected() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    outcome = engine.rebalance(
        state=_state(cash="999.99"),
        staged_targets=(_target(SEC_A, 10),),
        open_prices={SEC_A: _price("100.00")},
        execution_listings=_listings_for(SEC_A),
    )
    assert outcome.classification == "rejected"
    assert outcome.rejection is not None
    assert outcome.rejection.cash_shortfall == Decimal("0.01")


def test_execute_rejects_a_plan_built_for_another_session() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(day=date(2026, 11, 27)),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    with pytest.raises(ValueError, match="session"):
        engine.execute(state=_state(), plan=plan)


def test_execute_rejects_a_plan_built_against_another_cash_balance() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    with pytest.raises(ValueError, match="cash"):
        engine.execute(state=_state(cash="9000.00"), plan=plan)


def test_execute_rejects_a_plan_built_against_other_holdings() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00"),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    moved = _state(cash="10000.00", holdings=(_holding(SEC_A, 3, "30.00"),))
    with pytest.raises(ValueError, match="plan positions"):
        engine.execute(state=moved, plan=plan)


def test_execute_rejects_a_plan_built_against_another_security() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(cash="10000.00", holdings=(_holding(SEC_A, 3, "30.00"),)),
        staged_targets=(_target(SEC_A, 5),),
        open_prices={SEC_A: _price("10.00")},
        execution_listings=_listings_for(SEC_A),
    )
    swapped = _state(cash="10000.00", holdings=(_holding(SEC_B, 3, "30.00"),))
    with pytest.raises(ValueError, match="plan positions"):
        engine.execute(state=swapped, plan=plan)


def test_plan_positions_hash_tracks_held_quantities() -> None:
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)

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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    state = _state(cash="1000.00")
    plan = engine.plan(
        state=state,
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
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
        termination_records=(),
        lifecycle_records=(),
    )
    outcome = engine.rebalance(
        state=_state(),
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    state = _state(cash="1000.00")
    plan = engine.plan(
        state=state,
        staged_targets=(_target(SEC_A, 1),),
        open_prices={SEC_A: _price("10.00")},
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
    engine = AtomicRebalanceEngine(session_clock=EXEC_CLOCK, cost_model=ZERO_COST)
    plan = engine.plan(
        state=_state(holdings=(_holding(SEC_B, 4, "40.00"),)),
        staged_targets=(_target(SEC_A, 2), _target(SEC_B, 0)),
        open_prices={SEC_A: _price("10.00"), SEC_B: _price("10.00")},
        execution_listings=_listings_for(SEC_A, SEC_B),
    )
    with pytest.raises(ValidationError, match="canonical"):
        plan.model_copy(update={"planned_fills": tuple(reversed(plan.planned_fills))})
