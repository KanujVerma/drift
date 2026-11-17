"""Router results must not erase greater cumulative fills already retained."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid7

import pytest

from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import ExecutionJournalError, PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter, RouterExecutionError


def _intent() -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=str(uuid7()),
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
        ),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("100"),
        created_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
    )


def _report(
    intent: OrderIntentV1,
    quantity: int,
    status: ExecutionStatus,
    *,
    time_offset: int = 0,
    anchor: datetime | None = None,
) -> ExecutionReportV1:
    return build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="synthetic-order",
        status=status,
        cum_quantity=quantity,
        leaves_quantity=5 - quantity,
        avg_fill_price=Decimal("100") if quantity else None,
        rejection_reason="synthetic rejection"
        if status is ExecutionStatus.REJECTED
        else None,
        reported_at=(anchor if anchor is not None else intent.created_at)
        + timedelta(seconds=time_offset),
    )


class _ResponseAdapter(MockBrokerAdapter):
    response: ExecutionReportV1 | None = None
    submits = 0

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        self.submits += 1
        return super().submit_intent(intent)

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        return self.response

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        assert self.response is not None
        return self.response


@pytest.mark.parametrize("operation", ["status", "cancel"])
@pytest.mark.parametrize("time_offset", [-1, 1])
@pytest.mark.parametrize(
    ("status", "quantity"),
    [
        (ExecutionStatus.NEW, 0),
        (ExecutionStatus.ACKNOWLEDGED, 0),
        (ExecutionStatus.PARTIALLY_FILLED, 2),
        (ExecutionStatus.CANCELED, 0),
        (ExecutionStatus.REJECTED, 0),
    ],
)
def test_lower_quantity_is_retained_but_never_returned_as_current(
    tmp_path: Path,
    operation: str,
    time_offset: int,
    status: ExecutionStatus,
    quantity: int,
) -> None:
    adapter = _ResponseAdapter(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    intent = _intent()
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        fill = router.route_intent(intent)
        lower = _report(
            intent, quantity, status, time_offset=time_offset, anchor=fill.reported_at
        )
        adapter.response = lower
        for _ in range(2):
            with pytest.raises(RouterExecutionError, match="cumulative quantity"):
                if operation == "status":
                    router.get_intent_status(intent.intent_id)
                else:
                    router.cancel_intent(intent.intent_id)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            fill,
            lower,
        )
        # The journal remains an honest raw arrival-order reader, not a resolver.
        assert journal.get_latest_execution_report(intent.intent_id) == lower
        assert adapter.submits == 1
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


@pytest.mark.parametrize("lookup", ["client", "intent", "journal_fallback"])
def test_cached_lower_quantity_refuses_after_reopen_without_redispatch(
    tmp_path: Path, lookup: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _intent()
    fill = _report(intent, 5, ExecutionStatus.FILLED)
    lower = _report(intent, 0, ExecutionStatus.ACKNOWLEDGED)
    path = tmp_path / "reports.sqlite"
    writer = PersistentOrderIntentJournal(path)
    writer.record_intent(intent)
    writer.record_execution_report(fill)
    writer.record_execution_report(lower)
    writer.close()
    reader = PersistentOrderIntentJournal(path)
    adapter = _ResponseAdapter()
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=reader)
    if lookup == "intent":
        monkeypatch.setattr(reader, "get_intent_by_client_id", lambda _: None)
    try:
        for _ in range(2):
            with pytest.raises(RouterExecutionError, match="cumulative quantity"):
                if lookup == "journal_fallback":
                    router.get_intent_status(intent.intent_id)
                else:
                    router.route_intent(intent)
        assert adapter.submits == 0
        assert adapter.get_positions() == ()
        assert reader.list_execution_reports_for_intent(intent.intent_id) == (
            fill,
            lower,
        )
    finally:
        reader.close()


@pytest.mark.parametrize("status", [ExecutionStatus.NEW, ExecutionStatus.ACKNOWLEDGED])
def test_fill_before_submission_acknowledgement_cannot_regress(
    tmp_path: Path, status: ExecutionStatus
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")

    class FillBeforeAckAdapter(MockBrokerAdapter):
        router: BrokerNeutralExecutionRouter | None = None
        fill: ExecutionReportV1 | None = None
        ack: ExecutionReportV1 | None = None
        submits = 0

        def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
            self.submits += 1
            self.fill = super().submit_intent(intent)
            assert self.router is not None
            assert self.router.get_intent_status(intent.intent_id) == self.fill
            self.ack = _report(intent, 0, status)
            return self.ack

    adapter = FillBeforeAckAdapter(
        initial_cash=Decimal("1000"), default_fee=Decimal("1")
    )
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    adapter.router = router
    intent = _intent()
    try:
        with pytest.raises(RouterExecutionError, match="cumulative quantity"):
            router.route_intent(intent)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            adapter.fill,
            adapter.ack,
        )
        with pytest.raises(RouterExecutionError, match="cumulative quantity"):
            router.route_intent(intent)
        assert adapter.submits == 1
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("quantity", "status"),
    [
        (2, ExecutionStatus.PARTIALLY_FILLED),
        (3, ExecutionStatus.PARTIALLY_FILLED),
        (5, ExecutionStatus.FILLED),
        (2, ExecutionStatus.CANCELED),
        (2, ExecutionStatus.EXPIRED),
    ],
)
def test_equal_or_increasing_quantity_preserves_existing_behavior(
    tmp_path: Path, quantity: int, status: ExecutionStatus
) -> None:
    intent = _intent()
    earlier = _report(intent, 2, ExecutionStatus.PARTIALLY_FILLED)
    candidate = _report(intent, quantity, status)
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    journal.record_intent(intent)
    journal.record_execution_report(earlier)
    adapter = _ResponseAdapter()
    adapter.response = candidate
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        assert router.get_intent_status(intent.intent_id) == candidate
        assert router.get_intent_status(intent.intent_id) == candidate
        assert router.route_intent(intent) == candidate
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            earlier,
            candidate,
        )
        assert adapter.submits == 0
    finally:
        journal.close()


def test_all_retained_history_is_consulted_not_only_previous_arrival(
    tmp_path: Path,
) -> None:
    intent = _intent()
    reports = (
        _report(intent, 5, ExecutionStatus.FILLED),
        _report(intent, 0, ExecutionStatus.ACKNOWLEDGED),
        _report(intent, 2, ExecutionStatus.PARTIALLY_FILLED),
    )
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    journal.record_intent(intent)
    for report in reports[:2]:
        journal.record_execution_report(report)
    adapter = _ResponseAdapter()
    adapter.response = reports[2]
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        with pytest.raises(RouterExecutionError, match="cumulative quantity"):
            router.get_intent_status(intent.intent_id)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == reports
        # Redelivery of a previously retained lower report must also refuse.
        adapter.response = reports[1]
        with pytest.raises(RouterExecutionError, match="cumulative quantity"):
            router.get_intent_status(intent.intent_id)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == reports
    finally:
        journal.close()


def test_another_intents_quantity_does_not_block_this_intent(tmp_path: Path) -> None:
    first, second = _intent(), _intent()
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    journal.record_intent(first)
    journal.record_intent(second)
    journal.record_execution_report(_report(first, 5, ExecutionStatus.FILLED))
    candidate = _report(second, 0, ExecutionStatus.ACKNOWLEDGED)
    adapter = _ResponseAdapter()
    adapter.response = candidate
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        assert router.get_intent_status(second.intent_id) == candidate
        assert router.route_intent(second) == candidate
        assert adapter.submits == 0
    finally:
        journal.close()


@pytest.mark.parametrize("operation", ["new_report", "cached", "fallback"])
def test_unreadable_history_cannot_be_treated_as_zero_fills(
    tmp_path: Path, operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _intent()
    candidate = _report(intent, 0, ExecutionStatus.ACKNOWLEDGED)
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    journal.record_intent(intent)
    if operation != "new_report":
        journal.record_execution_report(candidate)
    adapter = _ResponseAdapter()
    if operation == "new_report":
        adapter.response = candidate
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    failure = ExecutionJournalError("injected history read failure")

    def fail(intent_id: UUID) -> tuple[ExecutionReportV1, ...]:
        raise failure

    monkeypatch.setattr(journal, "list_execution_reports_for_intent", fail)
    try:
        with pytest.raises(ExecutionJournalError) as raised:
            if operation == "cached":
                router.route_intent(intent)
            else:
                router.get_intent_status(intent.intent_id)
        assert raised.value is failure
        assert journal.get_execution_report(candidate.report_id) == candidate
        assert adapter.submits == 0
    finally:
        journal.close()
