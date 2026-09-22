"""Unit tests for M2 Task 6 canonical trace events and content-addressed log."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from observation_test_support import market_uid
from pydantic import ValidationError

from drift.domain.evaluator_execution import ExecutionFillV1, FillRejectionV1
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.evaluator_trace import (
    ClaimSettledTraceEventV1,
    CorporateActionAppliedTraceEventV1,
    EvaluationPhase,
    EvaluationTraceLogV1,
    EvaluatorTraceEventV1,
    FillRejectionTraceEventV1,
    FillTraceEventV1,
    IndeterminateCauseTraceEventV1,
    SessionMarkTraceEventV1,
    SessionStartTraceEventV1,
    StrategyDecisionTraceEventV1,
    evaluation_trace_log_hash,
    seal_evaluation_trace_log,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1

SEC_A = market_uid(200)
SEC_B = market_uid(300)
LISTING_A = market_uid(201)

DAY_ONE = date(2026, 1, 5)
DAY_TWO = date(2026, 1, 6)
CLOSE_ONE = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def _key(day: date = DAY_ONE) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _start(
    *, sequence: int = 0, session_index: int = 0, day: date = DAY_ONE
) -> SessionStartTraceEventV1:
    return SessionStartTraceEventV1(
        sequence=sequence,
        session_index=session_index,
        session_key=_key(day),
        session_hash=H1,
        opening_cash=Decimal("10000.00"),
        opening_net_asset_value=Decimal("10000.00"),
    )


def _fill(
    *, security_id: UUID = SEC_A, side: str = "buy", quantity: int = 10
) -> ExecutionFillV1:
    gross = Decimal("100.00") * quantity
    return ExecutionFillV1(
        security_id=security_id,
        listing_id=LISTING_A,
        venue=ListingVenue.XNYS,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        unadjusted_open_price=Decimal("100.00"),
        fill_price=Decimal("100.00"),
        gross_notional=gross,
        transaction_costs=Decimal("0"),
        cash_delta=gross if side == "sell" else -gross,
    )


def _fill_event(
    sequence: int, *, security_id: UUID = SEC_A, session_index: int = 0
) -> FillTraceEventV1:
    return FillTraceEventV1(
        sequence=sequence,
        session_index=session_index,
        session_key=_key(),
        commit_index=sequence - 1,
        fill=_fill(security_id=security_id),
    )


def _rejection(day: date = DAY_ONE) -> FillRejectionV1:
    return FillRejectionV1(
        session_key=_key(day),
        reason="insufficient_cash",
        current_cash=Decimal("100.00"),
        gross_sell_proceeds=Decimal("0"),
        sell_transaction_costs=Decimal("0"),
        required_cash=Decimal("1000.00"),
        projected_cash=Decimal("-900.00"),
        cash_shortfall=Decimal("900.00"),
    )


def _mark(
    *, sequence: int = 1, session_index: int = 0, day: date = DAY_ONE
) -> SessionMarkTraceEventV1:
    return SessionMarkTraceEventV1(
        sequence=sequence,
        session_index=session_index,
        session_key=_key(day),
        mark_hash=H2,
        cash_balance=Decimal("9000.00"),
        holdings_market_value=Decimal("1100.00"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("10100.00"),
    )


def _target(security_id: UUID, quantity: int) -> SecurityTargetPositionV1:
    return SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)


def _decision(
    *,
    sequence: int = 1,
    session_index: int = 0,
    outcome: str = "staged",
    staged: tuple[SecurityTargetPositionV1, ...] = (),
    reason: str | None = None,
) -> StrategyDecisionTraceEventV1:
    return StrategyDecisionTraceEventV1(
        sequence=sequence,
        session_index=session_index,
        session_key=_key(),
        decision_cutoff=CLOSE_ONE,
        context_hash=H2,
        intent_hash=H3,
        outcome=outcome,  # type: ignore[arg-type]
        staged_targets=staged,
        rejection_reason=reason,
    )


# --- trace event shape ---


def test_session_start_event_carries_its_session_and_opening_book() -> None:
    event = _start()

    assert event.kind == "session_start"
    assert event.schema_version == "1"
    assert event.opening_net_asset_value == Decimal("10000.00")


def test_corporate_action_event_requires_an_actual_mutation() -> None:
    with pytest.raises(ValidationError, match="records no mutation"):
        CorporateActionAppliedTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(),
            holdings_hash_before=H1,
            holdings_hash_after=H1,
            staged_targets_before=(),
            staged_targets_after=(),
            recorded_claim_ids=(),
        )


def test_corporate_action_event_accepts_a_share_mutation() -> None:
    event = CorporateActionAppliedTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        holdings_hash_before=H1,
        holdings_hash_after=H2,
        staged_targets_before=(),
        staged_targets_after=(),
        recorded_claim_ids=(),
    )

    assert event.kind == "corporate_action_applied"


def test_corporate_action_event_accepts_a_claim_only_mutation() -> None:
    event = CorporateActionAppliedTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        holdings_hash_before=H1,
        holdings_hash_after=H1,
        staged_targets_before=(),
        staged_targets_after=(),
        recorded_claim_ids=(H3,),
    )

    assert event.recorded_claim_ids == (H3,)


def test_corporate_action_event_accepts_a_target_only_mutation() -> None:
    event = CorporateActionAppliedTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        holdings_hash_before=H1,
        holdings_hash_after=H1,
        staged_targets_before=(_target(SEC_A, 10),),
        staged_targets_after=(_target(SEC_A, 20),),
        recorded_claim_ids=(),
    )

    assert event.staged_targets_after[0].target_quantity == 20


def test_corporate_action_event_canonicalizes_claim_ids() -> None:
    event = CorporateActionAppliedTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        holdings_hash_before=H1,
        holdings_hash_after=H2,
        staged_targets_before=(),
        staged_targets_after=(),
        recorded_claim_ids=(H3, H2),
    )

    assert event.recorded_claim_ids == (H2, H3)


def test_corporate_action_event_refuses_repeated_claim_ids() -> None:
    with pytest.raises(ValidationError, match="claim ids must be unique"):
        CorporateActionAppliedTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(),
            holdings_hash_before=H1,
            holdings_hash_after=H2,
            staged_targets_before=(),
            staged_targets_after=(),
            recorded_claim_ids=(H3, H3),
        )


def test_fill_rejection_event_binds_the_rejected_session() -> None:
    with pytest.raises(ValidationError, match="rejection must describe its own"):
        FillRejectionTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(DAY_TWO),
            rejection=_rejection(DAY_ONE),
        )


def test_fill_rejection_event_accepts_its_own_session() -> None:
    event = FillRejectionTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(DAY_ONE),
        rejection=_rejection(DAY_ONE),
    )

    assert event.rejection.cash_shortfall == Decimal("900.00")


def test_claim_settled_event_requires_a_settled_claim() -> None:
    with pytest.raises(ValidationError, match="settlement event requires a claim"):
        ClaimSettledTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(),
            claim_ids=(),
            settled_cash=Decimal("0"),
        )


def test_claim_settled_event_requires_positive_settled_cash() -> None:
    with pytest.raises(ValidationError, match="settled cash must be strictly"):
        ClaimSettledTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(),
            claim_ids=(H2,),
            settled_cash=Decimal("0"),
        )


def test_claim_settled_event_canonicalizes_claim_ids() -> None:
    event = ClaimSettledTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        claim_ids=(H3, H2),
        settled_cash=Decimal("25.00"),
    )

    assert event.claim_ids == (H2, H3)


def test_session_mark_event_reconciles_net_asset_value() -> None:
    with pytest.raises(ValidationError, match="mark net asset value must reconcile"):
        SessionMarkTraceEventV1(
            sequence=1,
            session_index=0,
            session_key=_key(),
            mark_hash=H2,
            cash_balance=Decimal("9000.00"),
            holdings_market_value=Decimal("1100.00"),
            pending_claims_value=Decimal("0"),
            net_asset_value=Decimal("10000.00"),
        )


def test_strategy_decision_event_rejection_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="rejected decision requires its reason"):
        _decision(outcome="rejected", staged=(), reason=None)


def test_strategy_decision_event_rejection_stages_nothing() -> None:
    with pytest.raises(ValidationError, match="rejected decision stages no target"):
        _decision(
            outcome="rejected", staged=(_target(SEC_A, 5),), reason="negative target"
        )


def test_strategy_decision_event_staged_carries_no_reason() -> None:
    with pytest.raises(ValidationError, match="staged decision carries no rejection"):
        _decision(outcome="staged", staged=(), reason="negative target")


def test_strategy_decision_event_canonicalizes_staged_targets() -> None:
    event = _decision(staged=(_target(SEC_B, 3), _target(SEC_A, 4)))

    assert tuple(item.security_id for item in event.staged_targets) == (SEC_A, SEC_B)


def test_strategy_decision_event_refuses_repeated_targets() -> None:
    with pytest.raises(ValidationError, match="staged targets must be unique"):
        _decision(staged=(_target(SEC_A, 3), _target(SEC_A, 4)))


def test_indeterminate_cause_event_names_its_phase_and_cause() -> None:
    event = IndeterminateCauseTraceEventV1(
        sequence=1,
        session_index=0,
        session_key=_key(),
        phase=EvaluationPhase.OPEN_EXECUTION,
        cause_kind="indeterminate_execution",
        cause="no unadjusted open price for security",
    )

    assert event.phase is EvaluationPhase.OPEN_EXECUTION
    assert event.kind == "indeterminate_cause"


def test_evaluation_phase_names_the_five_canonical_phases() -> None:
    assert tuple(phase.value for phase in EvaluationPhase) == (
        "pre_open_effects",
        "open_execution",
        "intrasession_economic_effects",
        "close_mark",
        "post_close_decision",
    )


# --- content-addressed trace log ---


def test_trace_log_hash_is_self_excluding() -> None:
    log = seal_evaluation_trace_log((_start(), _mark()))

    assert log.trace_hash == evaluation_trace_log_hash(log)


def test_trace_log_rejects_a_declared_hash_that_is_not_its_own() -> None:
    log = seal_evaluation_trace_log((_start(), _mark()))
    tampered = EvaluationTraceLogV1.model_construct(
        **(dict(log) | {"events": (log.events[0],)})
    )

    with pytest.raises(ValidationError, match="trace hash mismatch"):
        EvaluationTraceLogV1.model_validate(dict(tampered))


def test_trace_log_hash_changes_when_any_event_changes() -> None:
    first = seal_evaluation_trace_log((_start(), _mark()))
    second = seal_evaluation_trace_log(
        (_start(), _mark().model_copy(update={"mark_hash": H3}))
    )

    assert first.trace_hash != second.trace_hash


def test_trace_log_hash_changes_when_events_are_reordered() -> None:
    forward = seal_evaluation_trace_log(
        (_start(), _fill_event(1), _fill_event(2, security_id=SEC_B))
    )
    backward = seal_evaluation_trace_log(
        (_start(), _fill_event(1, security_id=SEC_B), _fill_event(2))
    )

    assert forward.trace_hash != backward.trace_hash


def test_trace_log_refuses_an_empty_event_sequence() -> None:
    with pytest.raises(ValidationError, match="trace log requires at least one"):
        seal_evaluation_trace_log(())


def test_trace_log_requires_contiguous_sequence_numbers() -> None:
    events: tuple[EvaluatorTraceEventV1, ...] = (_start(sequence=0), _mark(sequence=2))

    with pytest.raises(ValidationError, match="event sequence must be contiguous"):
        seal_evaluation_trace_log(events)


def test_trace_log_must_begin_with_a_session_start() -> None:
    with pytest.raises(ValidationError, match="trace must open a session"):
        seal_evaluation_trace_log((_mark(sequence=0),))


def test_trace_log_requires_session_starts_to_advance_by_one() -> None:
    events: tuple[EvaluatorTraceEventV1, ...] = (
        _start(sequence=0, session_index=0),
        _start(sequence=1, session_index=2, day=DAY_TWO),
    )

    with pytest.raises(ValidationError, match="session index must advance by one"):
        seal_evaluation_trace_log(events)


def test_trace_log_refuses_an_event_attributed_to_another_session() -> None:
    events: tuple[EvaluatorTraceEventV1, ...] = (
        _start(sequence=0, session_index=0),
        _mark(sequence=1, session_index=1),
    )

    with pytest.raises(ValidationError, match="event belongs to the open session"):
        seal_evaluation_trace_log(events)


def test_trace_log_refuses_an_event_keyed_to_another_session() -> None:
    events: tuple[EvaluatorTraceEventV1, ...] = (
        _start(sequence=0, session_index=0, day=DAY_ONE),
        _mark(sequence=1, session_index=0, day=DAY_TWO),
    )

    with pytest.raises(ValidationError, match="event session key must match"):
        seal_evaluation_trace_log(events)


def test_trace_log_accepts_a_two_session_trace() -> None:
    events: tuple[EvaluatorTraceEventV1, ...] = (
        _start(sequence=0, session_index=0, day=DAY_ONE),
        _mark(sequence=1, session_index=0, day=DAY_ONE),
        _start(sequence=2, session_index=1, day=DAY_TWO),
        _mark(sequence=3, session_index=1, day=DAY_TWO),
    )

    log = seal_evaluation_trace_log(events)

    assert len(log.events) == 4
    assert log.trace_hash == evaluation_trace_log_hash(log)


def test_trace_log_is_reproducible_across_independent_constructions() -> None:
    first = seal_evaluation_trace_log((_start(), _mark()))
    second = seal_evaluation_trace_log((_start(), _mark()))

    assert first.trace_hash == second.trace_hash
    assert first == second
