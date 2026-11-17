"""Actual-router regressions for immutable execution report redelivery."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid7

import pytest

from drift.domain.execution import (
    ExecutionReportV1,
    OrderIntentV1,
    OrderSide,
    OrderType,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import (
    DuplicateIntentRecordError,
    ExecutionJournalError,
    PersistentOrderIntentJournal,
)
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


def _changed_fee(report: ExecutionReportV1) -> ExecutionReportV1:
    return build_execution_report(
        report_id=report.report_id,
        intent_id=report.intent_id,
        broker_order_id=report.broker_order_id,
        status=report.status,
        cum_quantity=report.cum_quantity,
        leaves_quantity=report.leaves_quantity,
        last_fill_price=report.last_fill_price,
        last_fill_quantity=report.last_fill_quantity,
        avg_fill_price=report.avg_fill_price,
        fee_amount=report.fee_amount + Decimal("1"),
        rejection_reason=report.rejection_reason,
        reported_at=report.reported_at,
    )


class _SelectedReportAdapter(MockBrokerAdapter):
    response: ExecutionReportV1 | None = None

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        return (
            self.response
            if self.response is not None
            else super().submit_intent(intent)
        )

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        return (
            self.response
            if self.response is not None
            else super().cancel_intent(intent_id)
        )

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        return (
            self.response
            if self.response is not None
            else super().get_intent_status(intent_id)
        )


def _call(
    router: BrokerNeutralExecutionRouter, operation: str, intent: OrderIntentV1
) -> ExecutionReportV1 | None:
    if operation in {"submit", "recover"}:
        return router.route_intent(intent)
    if operation == "cancel":
        return router.cancel_intent(intent.intent_id)
    assert operation == "status"
    return router.get_intent_status(intent.intent_id)


def test_cancel_after_fill_returns_original_report_after_reopen(tmp_path: Path) -> None:
    adapter = MockBrokerAdapter(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    db = tmp_path / "reports.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = _intent()
    fill = router.route_intent(intent)
    original_rows = journal.list_execution_reports_for_intent(intent.intent_id)
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    try:
        assert router.cancel_intent(intent.intent_id) == fill
        assert router.cancel_intent(intent.intent_id) == fill
        assert router.route_intent(intent) == fill
        assert (
            journal.list_execution_reports_for_intent(intent.intent_id) == original_rows
        )
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


def test_nonconsecutive_identical_report_does_not_append_or_fail(
    tmp_path: Path,
) -> None:
    adapter = MockBrokerAdapter(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = _intent()
    try:
        fill = router.route_intent(intent)
        later = build_execution_report(
            report_id=uuid7(),
            intent_id=intent.intent_id,
            broker_order_id=fill.broker_order_id,
            status=fill.status,
            cum_quantity=5,
            leaves_quantity=0,
            avg_fill_price=Decimal("100"),
            fee_amount=Decimal("1"),
            reported_at=fill.reported_at + timedelta(seconds=1),
        )
        journal.record_execution_report(later)
        assert router.get_intent_status(intent.intent_id) == fill
        assert router.get_intent_status(intent.intent_id) == fill
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            fill,
            later,
        )
        assert journal.get_latest_execution_report(intent.intent_id) == later
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


@pytest.mark.parametrize("operation", ["cancel", "status"])
@pytest.mark.parametrize("retain_hash", [False, True])
def test_reused_id_with_changed_payload_is_not_an_identical_delivery(
    tmp_path: Path, operation: str, retain_hash: bool
) -> None:
    adapter = _SelectedReportAdapter(
        initial_cash=Decimal("1000"), default_fee=Decimal("1")
    )
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = _intent()
    try:
        fill = router.route_intent(intent)
        adapter.response = (
            # Deliberately bypass model validation to test a forged claimed hash.
            ExecutionReportV1.model_construct(
                **{**fill.model_dump(mode="python"), "fee_amount": Decimal("2")}
            )
            if retain_hash
            else _changed_fee(fill)
        )
        with pytest.raises(RouterExecutionError, match="conflicting execution report"):
            _call(router, operation, intent)
        assert journal.get_execution_report(fill.report_id) == fill
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (fill,)
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


@pytest.mark.parametrize("operation", ["submit", "recover", "cancel", "status"])
def test_report_for_another_intent_is_refused_before_report_retention(
    tmp_path: Path, operation: str
) -> None:
    adapter = _SelectedReportAdapter(
        initial_cash=Decimal("1000"), default_fee=Decimal("1")
    )
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    requested = _intent()
    other = _intent()
    adapter.response = MockBrokerAdapter().submit_intent(other)
    if operation != "submit":
        journal.record_intent(requested)
    try:
        with pytest.raises(RouterExecutionError, match="execution report intent"):
            _call(router, operation, requested)
        assert journal.list_execution_reports_for_intent(requested.intent_id) == ()
        assert journal.list_execution_reports_for_intent(other.intent_id) == ()
        assert adapter.cash == Decimal("1000") and adapter.get_positions() == ()
    finally:
        journal.close()


class _RacingJournal(PersistentOrderIntentJournal):
    def __init__(self, db_path: Path, *, conflict: bool = False) -> None:
        super().__init__(db_path)
        self.peer = PersistentOrderIntentJournal(db_path)
        self.conflict = conflict
        self.raced = False
        self.retained: ExecutionReportV1 | None = None

    def record_execution_report(self, report: ExecutionReportV1) -> None:
        if not self.raced:
            self.raced = True
            self.retained = _changed_fee(report) if self.conflict else report
            self.peer.record_execution_report(self.retained)
        super().record_execution_report(report)

    def close(self) -> None:
        self.peer.close()
        super().close()


@pytest.mark.parametrize("operation", ["submit", "recover", "cancel", "status"])
@pytest.mark.parametrize("conflict", [False, True])
def test_insert_race_reads_back_and_compares_the_actual_retained_report(
    tmp_path: Path, operation: str, conflict: bool
) -> None:
    adapter = _SelectedReportAdapter(
        initial_cash=Decimal("1000"), default_fee=Decimal("1")
    )
    journal = _RacingJournal(tmp_path / "reports.sqlite", conflict=conflict)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = _intent()
    if operation != "submit":
        journal.record_intent(intent)
        adapter.response = adapter.submit_intent(intent)
    try:
        if conflict:
            with pytest.raises(
                RouterExecutionError, match="conflicting execution report"
            ):
                _call(router, operation, intent)
        else:
            result = _call(router, operation, intent)
            assert result == journal.retained
        assert journal.raced and journal.retained is not None
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            journal.retained,
        )
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()


@pytest.mark.parametrize("operation", ["submit", "recover", "cancel", "status"])
@pytest.mark.parametrize(
    "error_type", [ExecutionJournalError, DuplicateIntentRecordError]
)
def test_unrelated_persistence_failure_is_not_swallowed(
    tmp_path: Path,
    operation: str,
    error_type: type[ExecutionJournalError],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _SelectedReportAdapter()
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    intent = _intent()
    if operation != "submit":
        journal.record_intent(intent)
        adapter.response = adapter.submit_intent(intent)
    failure = error_type("injected persistence failure without a retained report")

    def fail(report: ExecutionReportV1) -> None:
        raise failure

    monkeypatch.setattr(journal, "record_execution_report", fail)
    try:
        with pytest.raises(error_type) as raised:
            _call(router, operation, intent)
        assert raised.value is failure
        assert journal.list_execution_reports_for_intent(intent.intent_id) == ()
    finally:
        journal.close()


def test_fill_observed_during_submit_is_retained_once(tmp_path: Path) -> None:
    class CallbackAdapter(MockBrokerAdapter):
        router: BrokerNeutralExecutionRouter | None = None

        def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
            fill = super().submit_intent(intent)
            assert self.router is not None
            assert self.router.get_intent_status(intent.intent_id) == fill
            return fill

    adapter = CallbackAdapter(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
    journal = PersistentOrderIntentJournal(tmp_path / "reports.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    adapter.router = router
    intent = _intent()
    try:
        fill = router.route_intent(intent)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (fill,)
        assert router.route_intent(intent) == fill
        assert adapter.cash == Decimal("499")
        assert adapter.get_positions()[0].quantity == 5
    finally:
        journal.close()
