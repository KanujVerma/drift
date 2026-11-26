"""Offline regressions for same-intent dispatch and uncertain cancellation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid7

import pytest

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.domain.execution import ExecutionStatus, OrderIntentV1, build_order_intent
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
