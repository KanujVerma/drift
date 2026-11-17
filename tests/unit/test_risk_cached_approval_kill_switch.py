"""Previously allowed orders cannot bypass a later durable emergency stop."""

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from test_execution_safety_risk import NOW, _make_intent
from test_risk_gatekeeper import KEY1, _make_policy

from drift.domain.execution import ExecutionReportV1, OrderIntentV1
from drift.domain.risk import RiskVerdictStatus
from drift.domain.shadow_broker import build_simulated_order
from drift.errors import DriftError
from drift.execution.adapter import MockBrokerAdapter
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal

PRICE = Decimal("100")


class CountingAdapter(MockBrokerAdapter):
    """Count actual submission attempts, including rejected attempts."""

    def __init__(self) -> None:
        super().__init__(initial_cash=Decimal("1000"), default_fee=Decimal("1"))
        self.submit_calls = 0

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        self.submit_calls += 1
        return super().submit_intent(intent)


@pytest.mark.parametrize("entry", ["order", "intent", "simulated"])
@pytest.mark.parametrize("reopen", [False, True])
def test_cached_approval_is_blocked_after_durable_trip(
    tmp_path: Path, entry: str, reopen: bool
) -> None:
    db = tmp_path / "risk.db"
    journal = PersistentRiskJournal(db)
    gate = HardRiskGatekeeper(policy=_make_policy(), journal=journal)
    order = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
    simulated = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=order.security_id,
        side="buy",
        quantity=1,
        created_at=NOW,
    )
    original = gate.evaluate_order(
        simulated if entry == "simulated" else order,
        current_price=PRICE,
        evaluation_time=NOW,
    )
    assert original.status == RiskVerdictStatus.ALLOWED
    # A separately connected writer commits the latch after the approval.
    with PersistentRiskJournal(db) as writer:
        latch = writer.trip_kill_switch(reason="test emergency", tripped_at=NOW)
    if reopen:
        journal.close()
        journal = PersistentRiskJournal(db)
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=journal)
    try:
        for _ in range(2):
            with pytest.raises(DriftError, match="active kill switch") as blocked:
                if entry == "intent":
                    gate.evaluate_intent(order, current_price=PRICE)
                else:
                    gate.evaluate_order(
                        simulated if entry == "simulated" else order,
                        current_price=PRICE,
                    )
            assert type(blocked.value).__name__ == "CachedRiskApprovalBlockedError"
            assert journal.list_verdicts() == (original,)
            assert journal.get_current_kill_switch_state() == latch
    finally:
        journal.close()


@pytest.mark.parametrize("reopen", [False, True])
def test_configured_router_never_dispatches_cached_approval_after_trip(
    tmp_path: Path, reopen: bool
) -> None:
    db = tmp_path / "risk.db"
    risk = PersistentRiskJournal(db)
    gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
    intent = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
    original = gate.evaluate_intent(intent, current_price=PRICE)
    assert original.status == RiskVerdictStatus.ALLOWED
    latch = risk.trip_kill_switch(reason="test emergency", tripped_at=NOW)
    if reopen:
        risk.close()
        risk = PersistentRiskJournal(db)
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
    adapter = CountingAdapter()
    adapter.set_price(intent.security_id, PRICE)
    try:
        with closing(PersistentOrderIntentJournal()) as execution:
            router = BrokerNeutralExecutionRouter(
                adapter=adapter,
                journal=execution,
                risk_gatekeeper=gate,
            )
            with pytest.raises(DriftError, match="active kill switch") as blocked:
                router.route_intent(intent, current_price=PRICE)
            assert type(blocked.value).__name__ == "CachedRiskApprovalBlockedError"
            assert execution.get_intent(intent.intent_id) == intent
            assert execution.list_execution_reports_for_intent(intent.intent_id) == ()
            assert adapter.submit_calls == 0
            assert adapter.get_account_snapshot().cash_balance == Decimal("1000")
            assert adapter.get_positions() == ()
            assert risk.list_verdicts() == (original,)
            assert risk.get_current_kill_switch_state() == latch
    finally:
        risk.close()


@pytest.mark.parametrize("via_router", [False, True])
def test_cached_approval_has_no_fallback_when_latch_read_fails(
    monkeypatch: pytest.MonkeyPatch, via_router: bool
) -> None:
    with (
        PersistentRiskJournal() as risk,
        closing(PersistentOrderIntentJournal()) as execution,
    ):
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=PRICE)
        adapter = CountingAdapter()
        adapter.set_price(intent.security_id, PRICE)
        router = BrokerNeutralExecutionRouter(
            adapter=adapter,
            journal=execution,
            risk_gatekeeper=gate,
        )

        def fail_read() -> bool:
            raise sqlite3.OperationalError("latch read unavailable")

        monkeypatch.setattr(risk, "is_kill_switch_tripped", fail_read)
        with pytest.raises(sqlite3.OperationalError, match="latch read unavailable"):
            if via_router:
                router.route_intent(intent, current_price=PRICE)
            else:
                gate.evaluate_intent(intent, current_price=PRICE)
        assert adapter.submit_calls == 0
        assert adapter.get_account_snapshot().cash_balance == Decimal("1000")
        assert adapter.get_positions() == ()
        assert execution.list_execution_reports_for_intent(intent.intent_id) == ()
        assert risk.list_verdicts() == (original,)


def test_untripped_cached_approval_stays_idempotent() -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=PRICE)
        assert original.status == RiskVerdictStatus.ALLOWED
        for _ in range(2):
            assert gate.evaluate_order(intent, current_price=PRICE) == original
            assert risk.list_verdicts() == (original,)


@pytest.mark.parametrize("trip", [False, True])
def test_cached_denial_is_preserved(trip: bool) -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=None)
        assert original.status == RiskVerdictStatus.REJECTED
        if trip:
            risk.trip_kill_switch(reason="test emergency", tripped_at=NOW)
        assert gate.evaluate_order(intent, current_price=PRICE) == original
        assert risk.list_verdicts() == (original,)


def test_fresh_order_still_gets_a_journaled_kill_switch_verdict() -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        risk.trip_kill_switch(reason="test emergency", tripped_at=NOW)
        verdict = gate.evaluate_intent(intent, current_price=PRICE)
        assert verdict.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
        assert gate.evaluate_intent(intent, current_price=PRICE) == verdict
        assert risk.list_verdicts() == (verdict,)
