"""Unit tests for PersistentRiskJournal and latching kill switch (M13-2)."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.risk import (
    KillSwitchStatus,
    RiskVerdictStatus,
    build_risk_verdict,
)
from drift.risk.journal import (
    DuplicateRiskRecordError,
    PersistentRiskJournal,
    RiskAppendOnlyViolationError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)


def test_risk_journal_initialization(tmp_path: Path) -> None:
    """Verifies schema table creation and default active kill switch."""
    db_path = tmp_path / "risk_test.db"
    with PersistentRiskJournal(db_path) as journal:
        assert journal.is_kill_switch_tripped() is False
        state = journal.get_current_kill_switch_state()
        assert state.status == KillSwitchStatus.ACTIVE


def test_kill_switch_latching_and_crash_persistence(tmp_path: Path) -> None:
    """Verifies kill switch latching and survival across process restarts."""
    db_path = tmp_path / "risk_latch.db"

    # Process 1: Trip kill switch
    with PersistentRiskJournal(db_path) as j1:
        assert j1.is_kill_switch_tripped() is False
        tripped = j1.trip_kill_switch(
            reason="max_drawdown_breach: -5.2%",
            tripped_at=NOW,
        )
        assert tripped.status == KillSwitchStatus.TRIPPED
        assert j1.is_kill_switch_tripped() is True

    # Process 2: Reopen from disk (crash recovery / new session)
    with PersistentRiskJournal(db_path) as j2:
        assert j2.is_kill_switch_tripped() is True
        state = j2.get_current_kill_switch_state()
        assert state.status == KillSwitchStatus.TRIPPED
        assert state.trip_reason == "max_drawdown_breach: -5.2%"

        # Operator clears kill switch
        cleared = j2.clear_kill_switch(
            reason="operator_manual_reset_post_investigation",
            cleared_at=NOW,
        )
        assert cleared.status == KillSwitchStatus.ACTIVE
        assert j2.is_kill_switch_tripped() is False

    # Process 3: Reopen again, confirmed cleared
    with PersistentRiskJournal(db_path) as j3:
        assert j3.is_kill_switch_tripped() is False


def test_record_and_retrieve_verdicts() -> None:
    """Verifies verdict persistence, retrieval by order_id, and duplicate prevention."""
    journal = PersistentRiskJournal()
    ord1 = uuid7()
    ord2 = uuid7()

    v1 = build_risk_verdict(
        order_id=ord1,
        status=RiskVerdictStatus.ALLOWED,
        evaluated_at=NOW,
    )
    v2 = build_risk_verdict(
        order_id=ord2,
        status=RiskVerdictStatus.REJECTED,
        evaluated_at=NOW,
        reason="max_order_notional_exceeded",
    )

    journal.record_verdict(v1)
    journal.record_verdict(v2)

    assert journal.get_verdict_for_order(ord1) == v1
    assert journal.get_verdict_for_order(ord2) == v2
    assert journal.get_verdict_for_order(uuid7()) is None

    verdicts = journal.list_verdicts()
    assert len(verdicts) == 2
    assert verdicts[0] == v1
    assert verdicts[1] == v2

    # Duplicate rejection
    with pytest.raises(DuplicateRiskRecordError):
        journal.record_verdict(v1)


def test_risk_journal_append_only_triggers() -> None:
    """Verifies SQL triggers prevent UPDATE and DELETE on risk tables."""
    journal = PersistentRiskJournal()
    order_id = uuid7()
    v = build_risk_verdict(
        order_id=order_id,
        status=RiskVerdictStatus.ALLOWED,
        evaluated_at=NOW,
    )
    journal.record_verdict(v)

    # Attempt UPDATE on risk_verdicts
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE risk_verdicts SET status = 'rejected' WHERE order_id = ?",
                (str(order_id),),
            )

    # Attempt DELETE on risk_verdicts
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM risk_verdicts WHERE order_id = ?",
                (str(order_id),),
            )

    # Attempt UPDATE on kill_switch_events
    journal.trip_kill_switch(reason="test_halt", tripped_at=NOW)
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute("UPDATE kill_switch_events SET status = 'active'")

    # Attempt DELETE on kill_switch_events
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute("DELETE FROM kill_switch_events")
