"""Unit tests for Audited Evidence Ledger and SQL triggers (M18-2)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest

from drift.autonomy.ledger import (
    GovernanceChainIntegrityError,
    PersistentEvidenceLedger,
)
from drift.domain.autonomy import (
    AutonomyTier,
    GovernanceTransitionType,
    build_governance_transition,
)


def test_empty_ledger_state(tmp_path: Path) -> None:
    """Empty ledger returns None for latest and empty tuple for list."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        assert ledger.get_latest_transition() is None
        assert ledger.get_latest_chain_hash() is None
        assert ledger.get_all_transitions() == ()
        assert ledger.verify_chain_integrity() is True
    finally:
        ledger.close()


def test_record_and_chain_transitions(tmp_path: Path) -> None:
    """Transitions record sequentially with verified cryptographic chaining."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        now1 = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
        t1 = build_governance_transition(
            event_id=uuid7(),
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_0_CANARY,
            transition_type=GovernanceTransitionType.HOLD,
            trigger_reason="genesis",
            scorecard_summary={"sharpe": "1.2"},
            previous_chain_hash=None,
            evaluated_at=now1,
        )
        ledger.record_transition(t1)

        assert ledger.get_latest_chain_hash() == t1.chain_hash
        assert ledger.get_latest_transition() == t1

        now2 = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
        t2 = build_governance_transition(
            event_id=uuid7(),
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_1_MICRO,
            transition_type=GovernanceTransitionType.PROMOTION,
            trigger_reason="evidence_satisfied",
            scorecard_summary={"sharpe": "1.7"},
            previous_chain_hash=t1.chain_hash,
            evaluated_at=now2,
        )
        ledger.record_transition(t2)

        assert ledger.get_latest_chain_hash() == t2.chain_hash
        assert len(ledger.get_all_transitions()) == 2
        assert ledger.verify_chain_integrity() is True
    finally:
        ledger.close()


def test_broken_chain_hash_rejected(tmp_path: Path) -> None:
    """Recording transition with mismatched previous_chain_hash is rejected."""
    ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    try:
        now1 = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
        t1 = build_governance_transition(
            event_id=uuid7(),
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_0_CANARY,
            transition_type=GovernanceTransitionType.HOLD,
            trigger_reason="genesis",
            previous_chain_hash=None,
            evaluated_at=now1,
        )
        ledger.record_transition(t1)

        # Attempt to insert t2 with fake previous_chain_hash
        t2_corrupted = build_governance_transition(
            event_id=uuid7(),
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_1_MICRO,
            transition_type=GovernanceTransitionType.PROMOTION,
            trigger_reason="evidence_satisfied",
            previous_chain_hash="deadbeef" * 8,
            evaluated_at=datetime.now(UTC),
        )

        with pytest.raises(GovernanceChainIntegrityError):
            ledger.record_transition(t2_corrupted)
    finally:
        ledger.close()


def test_sql_append_only_triggers_prevent_update_and_delete(tmp_path: Path) -> None:
    """SQL append-only triggers prevent UPDATE and DELETE operations."""
    db_file = tmp_path / "gov.db"
    ledger = PersistentEvidenceLedger(db_path=db_file)
    try:
        t1 = build_governance_transition(
            event_id=uuid7(),
            previous_tier=AutonomyTier.TIER_0_CANARY,
            target_tier=AutonomyTier.TIER_0_CANARY,
            transition_type=GovernanceTransitionType.HOLD,
            trigger_reason="genesis",
            previous_chain_hash=None,
            evaluated_at=datetime.now(UTC),
        )
        ledger.record_transition(t1)
    finally:
        ledger.close()

    # Open raw connection and attempt direct tampering
    conn = sqlite3.connect(db_file)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only: no updates"):
            conn.execute(
                "UPDATE governance_transitions SET target_tier = 'tier_3_bounded';"
            )

        with pytest.raises(sqlite3.DatabaseError, match="append-only: no deletes"):
            conn.execute("DELETE FROM governance_transitions;")
    finally:
        conn.close()
