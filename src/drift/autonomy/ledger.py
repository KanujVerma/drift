"""Audited Evidence Ledger with append-only SQL triggers (M18-2).

Persists GovernanceTransitionV1 records with cryptographic hash chaining
and SQLite append-only triggers per ADR 0011, ADR 0013, and ADR 0014.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from drift.domain.autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    AutonomyTier,
    GovernanceTransitionType,
    GovernanceTransitionV1,
    compute_governance_transition_hash,
)
from drift.errors import DriftError

__all__ = [
    "GovernanceAppendOnlyViolationError",
    "GovernanceChainIntegrityError",
    "GovernanceLedgerError",
    "PersistentEvidenceLedger",
]

_CREATE_GOVERNANCE_TABLE = """
CREATE TABLE IF NOT EXISTS governance_transitions (
    event_id TEXT PRIMARY KEY,
    previous_tier TEXT NOT NULL,
    target_tier TEXT NOT NULL,
    transition_type TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    scorecard_summary TEXT NOT NULL,
    previous_chain_hash TEXT,
    chain_hash TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

_CREATE_NO_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_gov_no_update
BEFORE UPDATE ON governance_transitions
BEGIN
    SELECT RAISE(ABORT, 'governance_transitions is append-only: no updates');
END;
"""

_CREATE_NO_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_gov_no_delete
BEFORE DELETE ON governance_transitions
BEGIN
    SELECT RAISE(ABORT, 'governance_transitions is append-only: no deletes');
END;
"""


class GovernanceLedgerError(DriftError):
    """Base exception for evidence ledger failures."""


class GovernanceChainIntegrityError(GovernanceLedgerError):
    """Raised when cryptographic hash chaining is broken or mismatched."""


class GovernanceAppendOnlyViolationError(GovernanceLedgerError):
    """Raised when an append-only trigger is violated."""


class PersistentEvidenceLedger:
    """Thread-safe persistent SQLite ledger for governance transition events."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    def _ensure_connected(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                isolation_level=None,
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def _init_schema(self) -> None:
        conn = self._ensure_connected()
        conn.executescript(
            _CREATE_GOVERNANCE_TABLE
            + _CREATE_NO_UPDATE_TRIGGER
            + _CREATE_NO_DELETE_TRIGGER
        )

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get_latest_chain_hash(self) -> str | None:
        """Return chain_hash of the latest recorded transition, or None if empty."""
        conn = self._ensure_connected()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT chain_hash FROM governance_transitions "
                "ORDER BY rowid DESC LIMIT 1;"
            )
            row = cursor.fetchone()
            return str(row[0]) if row else None
        finally:
            cursor.close()

    def record_transition(self, transition: GovernanceTransitionV1) -> None:
        """Record a governance transition, verifying hash chain continuity."""
        conn = self._ensure_connected()
        latest_hash = self.get_latest_chain_hash()

        if transition.previous_chain_hash != latest_hash:
            raise GovernanceChainIntegrityError(
                f"previous_chain_hash mismatch: expected {latest_hash}, "
                f"got {transition.previous_chain_hash}"
            )

        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE;")
            cursor.execute(
                """
                INSERT INTO governance_transitions (
                    event_id, previous_tier, target_tier, transition_type,
                    trigger_reason, scorecard_summary, previous_chain_hash,
                    chain_hash, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(transition.event_id),
                    transition.previous_tier.value,
                    transition.target_tier.value,
                    transition.transition_type.value,
                    transition.trigger_reason,
                    json.dumps(dict(transition.scorecard_summary), sort_keys=True),
                    transition.previous_chain_hash,
                    transition.chain_hash,
                    transition.evaluated_at.isoformat(),
                ),
            )
            cursor.execute("COMMIT;")
        except sqlite3.IntegrityError as exc:
            cursor.execute("ROLLBACK;")
            if "append-only" in str(exc):
                raise GovernanceAppendOnlyViolationError(str(exc)) from exc
            raise GovernanceLedgerError(f"integrity error: {exc}") from exc
        except Exception:
            cursor.execute("ROLLBACK;")
            raise
        finally:
            cursor.close()

    def get_latest_transition(self) -> GovernanceTransitionV1 | None:
        """Query latest recorded governance transition."""
        conn = self._ensure_connected()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT event_id, previous_tier, target_tier, transition_type,
                       trigger_reason, scorecard_summary, previous_chain_hash,
                       chain_hash, evaluated_at
                FROM governance_transitions ORDER BY rowid DESC LIMIT 1;
                """
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_model(row)
        finally:
            cursor.close()

    def get_all_transitions(self) -> tuple[GovernanceTransitionV1, ...]:
        """Query all recorded transitions in append order."""
        conn = self._ensure_connected()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT event_id, previous_tier, target_tier, transition_type,
                       trigger_reason, scorecard_summary, previous_chain_hash,
                       chain_hash, evaluated_at
                FROM governance_transitions ORDER BY rowid ASC;
                """
            )
            rows = cursor.fetchall()
            return tuple(self._row_to_model(r) for r in rows)
        finally:
            cursor.close()

    def verify_chain_integrity(self) -> bool:
        """Verify complete cryptographic hash chaining from genesis to latest."""
        transitions = self.get_all_transitions()
        expected_prev: str | None = None

        for t in transitions:
            if t.previous_chain_hash != expected_prev:
                return False
            expected_hash = compute_governance_transition_hash(
                schema_version=AUTONOMY_SCHEMA_VERSION,
                event_id=t.event_id,
                previous_tier=t.previous_tier.value,
                target_tier=t.target_tier.value,
                transition_type=t.transition_type.value,
                trigger_reason=t.trigger_reason,
                scorecard_summary=t.scorecard_summary,
                previous_chain_hash=t.previous_chain_hash,
                evaluated_at=t.evaluated_at,
            )
            if t.chain_hash != expected_hash:
                return False
            expected_prev = t.chain_hash

        return True

    @staticmethod
    def _row_to_model(row: tuple[Any, ...]) -> GovernanceTransitionV1:
        return GovernanceTransitionV1(
            schema_version=AUTONOMY_SCHEMA_VERSION,
            event_id=UUID(row[0]),
            previous_tier=AutonomyTier(row[1]),
            target_tier=AutonomyTier(row[2]),
            transition_type=GovernanceTransitionType(row[3]),
            trigger_reason=row[4],
            scorecard_summary=json.loads(row[5]),
            previous_chain_hash=row[6],
            chain_hash=row[7],
            evaluated_at=datetime.fromisoformat(row[8]),
        )
