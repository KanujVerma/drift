"""Offline regression tests for cached approvals and the durable kill switch."""

import sqlite3
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest
from risk_test_support import KEY1, NOW, make_intent
from test_risk_gatekeeper import _make_policy

from drift.domain.risk import RiskVerdictStatus
from drift.domain.shadow_broker import build_simulated_order
from drift.risk.gatekeeper import CachedRiskApprovalBlockedError, HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal

PRICE = Decimal("100")


@pytest.mark.parametrize("entry", ["order", "intent", "simulated"])
@pytest.mark.parametrize("reopen", [False, True])
def test_cached_approval_is_blocked_after_durable_trip(
    tmp_path: Path, entry: str, reopen: bool
) -> None:
    db = tmp_path / "risk.db"
    journal = PersistentRiskJournal(db)
    gate = HardRiskGatekeeper(policy=_make_policy(), journal=journal)
    order = make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
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
    with PersistentRiskJournal(db) as writer:
        latch = writer.trip_kill_switch(reason="test emergency", tripped_at=NOW)
    if reopen:
        journal.close()
        journal = PersistentRiskJournal(db)
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=journal)
    try:
        for _ in range(2):
            with pytest.raises(
                CachedRiskApprovalBlockedError, match="active kill switch"
            ):
                if entry == "intent":
                    gate.evaluate_intent(order, current_price=PRICE)
                else:
                    gate.evaluate_order(
                        simulated if entry == "simulated" else order,
                        current_price=PRICE,
                    )
            assert journal.list_verdicts() == (original,)
            assert journal.get_current_kill_switch_state() == latch
    finally:
        journal.close()


def test_cached_approval_has_no_fallback_when_latch_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=PRICE)

        def fail_read() -> bool:
            raise sqlite3.OperationalError("latch read unavailable")

        monkeypatch.setattr(risk, "is_kill_switch_tripped", fail_read)
        with pytest.raises(sqlite3.OperationalError, match="latch read unavailable"):
            gate.evaluate_intent(intent, current_price=PRICE)
        assert risk.list_verdicts() == (original,)


def test_untripped_cached_approval_stays_idempotent() -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=PRICE)
        assert original.status == RiskVerdictStatus.ALLOWED
        for _ in range(2):
            assert gate.evaluate_order(intent, current_price=PRICE) == original
            assert risk.list_verdicts() == (original,)


@pytest.mark.parametrize("trip", [False, True])
def test_cached_denial_is_preserved(trip: bool) -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        original = gate.evaluate_intent(intent, current_price=None)
        assert original.status == RiskVerdictStatus.REJECTED
        if trip:
            risk.trip_kill_switch(reason="test emergency", tripped_at=NOW)
        assert gate.evaluate_order(intent, current_price=PRICE) == original
        assert risk.list_verdicts() == (original,)


def test_fresh_order_still_gets_a_journaled_kill_switch_verdict() -> None:
    with PersistentRiskJournal() as risk:
        gate = HardRiskGatekeeper(policy=_make_policy(), journal=risk)
        intent = make_intent(sec_id=uuid7(), quantity=1, price=PRICE)
        risk.trip_kill_switch(reason="test emergency", tripped_at=NOW)
        verdict = gate.evaluate_intent(intent, current_price=PRICE)
        assert verdict.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
        assert gate.evaluate_intent(intent, current_price=PRICE) == verdict
        assert risk.list_verdicts() == (verdict,)
