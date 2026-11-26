"""Offline regressions for same-intent dispatch and uncertain cancellation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event, RLock
from typing import Any
from uuid import UUID, uuid7

import pytest

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import ExecutionOutcomeUnknown
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter


def _intent() -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=str(uuid7()),
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1)
        ),
        security_id=uuid7(),
        side="buy",
        quantity=1,
        order_type="market",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )


class FakeTransport(MockRobinhoodMcpTransport):
    def __init__(self) -> None:
        super().__init__(auto_fill=False)
        self.entered = Event()
        self.release = Event()
        self.pause_submit = False
        self.fail_cancel = False

    def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
        if tool_name == "robinhood_place_order" and self.pause_submit:
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError("fake submit timed out")
        if tool_name == "robinhood_cancel_order" and self.fail_cancel:
            raise TimeoutError("fake cancel uncertain")
        return super().call_tool(tool_name, arguments)


def _adapter(
    intent: OrderIntentV1, transport: FakeTransport
) -> RobinhoodAgenticAdapter:
    return RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(
            account_id="fake", symbol_map={intent.security_id: "FAKE"}
        ),
        transport=transport,
    )


def test_direct_same_intent_concurrent_submissions_send_once() -> None:
    intent = _intent()
    transport = FakeTransport()
    transport.pause_submit = True
    adapter = _adapter(intent, transport)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adapter.submit_intent, intent)
        assert transport.entered.wait(5)
        second = pool.submit(adapter.submit_intent, intent)
        transport.release.set()
        one, two = first.result(timeout=5), second.result(timeout=5)
    assert one == two
    assert (
        sum(name == "robinhood_place_order" for name, _ in transport.call_history) == 1
    )


@pytest.mark.parametrize("blocked_operation", ["submit", "status"])
@pytest.mark.parametrize("via_router", [False, True])
def test_unrelated_cancel_reaches_transport_while_intent_is_stalled(
    blocked_operation: str, via_router: bool, tmp_path: Path
) -> None:
    class PausedTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.pause_status = False
            self.cancel_entered = Event()

        def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
            if tool_name == "robinhood_cancel_order":
                self.cancel_entered.set()
            if tool_name == "robinhood_get_order" and self.pause_status:
                self.entered.set()
                if not self.release.wait(10):
                    raise TimeoutError("fake status timed out")
            return super().call_tool(tool_name, arguments)

    first, stalled = _intent(), _intent()
    transport = PausedTransport()
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(
            account_id="fake",
            symbol_map={first.security_id: "FAKE", stalled.security_id: "FAKE"},
        ),
        transport=transport,
    )
    journal = PersistentOrderIntentJournal(tmp_path / "execution.sqlite")
    try:
        router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

        def submit(intent: OrderIntentV1) -> ExecutionReportV1:
            if via_router:
                return router.route_intent(intent)
            return adapter.submit_intent(intent)

        def status() -> ExecutionReportV1 | None:
            if via_router:
                return router.get_intent_status(stalled.intent_id)
            return adapter.get_intent_status(stalled.intent_id)

        def cancel() -> ExecutionReportV1:
            if via_router:
                return router.cancel_intent(first.intent_id)
            return adapter.cancel_intent(first.intent_id)

        assert submit(first).status is ExecutionStatus.ACKNOWLEDGED
        if blocked_operation == "status":
            assert submit(stalled).status is ExecutionStatus.ACKNOWLEDGED
            transport.pause_status = True
        else:
            transport.pause_submit = True

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = (
                pool.submit(submit, stalled)
                if blocked_operation == "submit"
                else pool.submit(status)
            )
            try:
                assert transport.entered.wait(5)
                cancellation = pool.submit(cancel)
                assert transport.cancel_entered.wait(3)
                assert cancellation.result(timeout=3).status is ExecutionStatus.CANCELED
                assert not pending.done()
            finally:
                transport.release.set()
            assert pending.result(timeout=5) is not None
        if via_router:
            reports = journal.list_execution_reports_for_intent(first.intent_id)
            assert reports[-1].status is ExecutionStatus.CANCELED
    finally:
        journal.close()


@pytest.mark.parametrize("operation", ["cancel", "status"])
def test_same_intent_operations_wait_for_pending_submission(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _intent()
    transport = FakeTransport()
    transport.pause_submit = True
    adapter = _adapter(intent, transport)
    lock_obtained = Event()
    original_lock_for_intent = adapter._lock_for_intent

    def observed_lock(intent_id: UUID) -> RLock:
        lock = original_lock_for_intent(intent_id)
        lock_obtained.set()
        return lock

    with ThreadPoolExecutor(max_workers=2) as pool:
        submission = pool.submit(adapter.submit_intent, intent)
        try:
            assert transport.entered.wait(5)
            monkeypatch.setattr(adapter, "_lock_for_intent", observed_lock)
            pending = (
                pool.submit(adapter.cancel_intent, intent.intent_id)
                if operation == "cancel"
                else pool.submit(adapter.get_intent_status, intent.intent_id)
            )
            assert lock_obtained.wait(5)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.2)
        finally:
            transport.release.set()
        assert submission.result(timeout=5).status is ExecutionStatus.ACKNOWLEDGED
        report = pending.result(timeout=5)
        assert report is not None
        assert report.status is (
            ExecutionStatus.CANCELED
            if operation == "cancel"
            else ExecutionStatus.ACKNOWLEDGED
        )
        assert (
            sum(name == "robinhood_place_order" for name, _ in transport.call_history)
            == 1
        )


def test_same_intent_waiter_does_not_retry_uncertain_submission() -> None:
    class UnknownTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.sends = 0

        def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
            if tool_name == "robinhood_place_order":
                self.sends += 1
                self.entered.set()
                if not self.release.wait(5):
                    raise RuntimeError("fake transport was not released")
                raise TimeoutError("fake submission outcome unknown")
            return super().call_tool(tool_name, arguments)

    intent = _intent()
    transport = UnknownTransport()
    adapter = _adapter(intent, transport)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adapter.submit_intent, intent)
        try:
            assert transport.entered.wait(5)
            second = pool.submit(adapter.submit_intent, intent)
            transport.release.set()
            with pytest.raises(ExecutionOutcomeUnknown):
                first.result(timeout=5)
            with pytest.raises(ExecutionOutcomeUnknown):
                second.result(timeout=5)
        finally:
            transport.release.set()
    assert transport.sends == 1


def test_uncertain_cancel_does_not_replay_old_ack_after_restart(tmp_path: Path) -> None:
    intent = _intent()
    transport = FakeTransport()
    adapter = _adapter(intent, transport)
    db = tmp_path / "execution.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    ack = router.route_intent(intent)
    transport.fail_cancel = True
    with pytest.raises(ExecutionOutcomeUnknown):
        router.cancel_intent(intent.intent_id)
    assert journal.get_execution_report(ack.report_id) == ack
    with pytest.raises(ExecutionOutcomeUnknown):
        router.route_intent(intent)
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    restarted = BrokerNeutralExecutionRouter(
        adapter=_adapter(intent, transport), journal=journal
    )
    try:
        with pytest.raises(ExecutionOutcomeUnknown):
            restarted.route_intent(intent)
        with pytest.raises(ExecutionOutcomeUnknown):
            restarted.get_intent_status(intent.intent_id)
        assert journal.get_execution_report(ack.report_id) == ack
    finally:
        journal.close()


def test_restart_after_uncertain_submit_never_sends_again(tmp_path: Path) -> None:
    class UnknownSubmit(FakeTransport):
        def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
            if tool_name == "robinhood_place_order":
                raise TimeoutError("fake send outcome unknown")
            return super().call_tool(tool_name, arguments)

    intent = _intent()
    transport = UnknownSubmit()
    db = tmp_path / "execution.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(
        adapter=_adapter(intent, transport), journal=journal
    )
    with pytest.raises(ExecutionOutcomeUnknown):
        router.route_intent(intent)
    journal.close()
    fresh_transport = FakeTransport()
    journal = PersistentOrderIntentJournal(db)
    restarted = BrokerNeutralExecutionRouter(
        adapter=_adapter(intent, fresh_transport), journal=journal
    )
    try:
        with pytest.raises(ExecutionOutcomeUnknown):
            restarted.route_intent(intent)
        assert not fresh_transport.call_history
    finally:
        journal.close()


def test_confirmed_cancel_is_retained_and_replayed_after_reopen(tmp_path: Path) -> None:
    intent = _intent()
    transport = FakeTransport()
    db = tmp_path / "execution.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(
        adapter=_adapter(intent, transport), journal=journal
    )
    ack = router.route_intent(intent)
    canceled = router.cancel_intent(intent.intent_id)
    assert canceled.status is ExecutionStatus.CANCELED
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    try:
        restarted = BrokerNeutralExecutionRouter(
            adapter=_adapter(intent, transport), journal=journal
        )
        assert restarted.route_intent(intent) == canceled
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            ack,
            canceled,
        )
    finally:
        journal.close()


def test_interrupted_operation_blocks_replay_after_reopen(tmp_path: Path) -> None:
    intent = _intent()
    transport = FakeTransport()
    db = tmp_path / "execution.sqlite"
    journal = PersistentOrderIntentJournal(db)
    router = BrokerNeutralExecutionRouter(
        adapter=_adapter(intent, transport), journal=journal
    )
    ack = router.route_intent(intent)
    assert journal.begin_router_operation(intent.intent_id, uuid7(), kind="cancel")
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    try:
        restarted = BrokerNeutralExecutionRouter(
            adapter=_adapter(intent, transport), journal=journal
        )
        with pytest.raises(ExecutionOutcomeUnknown):
            restarted.route_intent(intent)
        with pytest.raises(ExecutionOutcomeUnknown):
            restarted.cancel_intent(intent.intent_id)
        assert journal.get_execution_report(ack.report_id) == ack
    finally:
        journal.close()


def test_overlapping_router_cancels_do_not_call_transport_twice(tmp_path: Path) -> None:
    class PausedCancel(FakeTransport):
        def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
            if tool_name == "robinhood_cancel_order":
                self.entered.set()
                if not self.release.wait(5):
                    raise TimeoutError("fake cancel timed out")
            return super().call_tool(tool_name, arguments)

    intent = _intent()
    transport = PausedCancel()
    adapter = _adapter(intent, transport)
    db = tmp_path / "execution.sqlite"
    first_journal = PersistentOrderIntentJournal(db)
    second_journal = PersistentOrderIntentJournal(db)
    first = BrokerNeutralExecutionRouter(adapter=adapter, journal=first_journal)
    second = BrokerNeutralExecutionRouter(adapter=adapter, journal=second_journal)
    try:
        ack = first.route_intent(intent)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first.cancel_intent, intent.intent_id)
            assert transport.entered.wait(5)
            with pytest.raises(ExecutionOutcomeUnknown):
                second.cancel_intent(intent.intent_id)
            with pytest.raises(ExecutionOutcomeUnknown):
                second.route_intent(intent)
            transport.release.set()
            assert future.result(timeout=5).status is ExecutionStatus.CANCELED
        assert first_journal.get_execution_report(ack.report_id) == ack
        assert (
            sum(name == "robinhood_cancel_order" for name, _ in transport.call_history)
            == 1
        )
    finally:
        transport.release.set()
        first_journal.close()
        second_journal.close()


def test_direct_adapter_restart_remains_unguarded() -> None:
    """A fresh adapter has no journal or authenticated account-wide fencing."""
    intent = _intent()
    transport = FakeTransport()
    _adapter(intent, transport).submit_intent(intent)
    _adapter(intent, transport).submit_intent(intent)
    assert (
        sum(name == "robinhood_place_order" for name, _ in transport.call_history) == 2
    )


def test_nonterminal_cancel_response_remains_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _intent()
    transport = FakeTransport()
    adapter = _adapter(intent, transport)
    journal = PersistentOrderIntentJournal(tmp_path / "execution.sqlite")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)
    ack = router.route_intent(intent)
    monkeypatch.setattr(adapter, "cancel_intent", lambda _: ack)
    try:
        with pytest.raises(ExecutionOutcomeUnknown):
            router.cancel_intent(intent.intent_id)
        with pytest.raises(ExecutionOutcomeUnknown):
            router.route_intent(intent)
        assert journal.get_execution_report(ack.report_id) == ack
    finally:
        journal.close()
