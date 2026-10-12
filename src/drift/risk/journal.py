"""Persistent SQLite risk journal and latching kill switch (M13-2).

Stores kill switch state transitions and pre-execution risk verdicts in a
dedicated SQLite database protected by SQL-level append-only triggers.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from drift.domain.risk import (
    KillSwitchStateV1,
    KillSwitchStatus,
    RiskVerdictV1,
    build_kill_switch_state,
)
from drift.errors import DriftError
from drift.serialization.canonical import canonical_json

__all__ = [
    "DuplicateRiskRecordError",
    "PersistentRiskJournal",
    "RiskAppendOnlyViolationError",
    "RiskJournalError",
]


class RiskJournalError(DriftError):
    """Base exception for risk journal errors."""


class DuplicateRiskRecordError(RiskJournalError):
    """Raised when inserting a duplicate risk record."""


class RiskAppendOnlyViolationError(RiskJournalError):
    """Raised when attempting to modify or delete existing risk records."""


_CREATE_KILL_SWITCH_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS kill_switch_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    tripped_at TEXT,
    trip_reason TEXT,
    cleared_at TEXT,
    clear_reason TEXT,
    state_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS kill_switch_events_no_update
BEFORE UPDATE ON kill_switch_events
BEGIN
    SELECT RAISE(ABORT, 'kill_switch_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS kill_switch_events_no_delete
BEFORE DELETE ON kill_switch_events
BEGIN
    SELECT RAISE(ABORT, 'kill_switch_events is append-only');
END;
"""

_CREATE_RISK_VERDICTS_TABLE = """
CREATE TABLE IF NOT EXISTS risk_verdicts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    reason TEXT,
    evaluated_at TEXT NOT NULL,
    verdict_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_verdicts_order
ON risk_verdicts (order_id);

CREATE TRIGGER IF NOT EXISTS risk_verdicts_no_update
BEFORE UPDATE ON risk_verdicts
BEGIN
    SELECT RAISE(ABORT, 'risk_verdicts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS risk_verdicts_no_delete
BEFORE DELETE ON risk_verdicts
BEGIN
    SELECT RAISE(ABORT, 'risk_verdicts is append-only');
END;
"""


class PersistentRiskJournal:
    """Persistent SQLite risk journal and latching kill switch engine."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        self._connection: sqlite3.Connection | None = None
        self._ensure_connected()
        self._init_schema()

    def _ensure_connected(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self._db_path,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            if self._db_path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA foreign_keys = ON;")
            self._connection.execute("PRAGMA busy_timeout = 5000;")
        return self._connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Active underlying SQLite connection."""
        return self._ensure_connected()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        conn = self._ensure_connected()
        cursor = conn.cursor()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            conn.execute("ROLLBACK")
            msg = str(error)
            if "append-only" in msg:
                raise RiskAppendOnlyViolationError(msg) from error
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
                raise DuplicateRiskRecordError(msg) from error
            raise RiskJournalError(msg) from error
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        conn = self._ensure_connected()
        conn.executescript(
            _CREATE_KILL_SWITCH_EVENTS_TABLE + _CREATE_RISK_VERDICTS_TABLE
        )

    def trip_kill_switch(
        self,
        *,
        reason: str,
        tripped_at: datetime,
    ) -> KillSwitchStateV1:
        """Trip emergency kill switch and persist state transition."""
        state = build_kill_switch_state(
            status=KillSwitchStatus.TRIPPED,
            tripped_at=tripped_at,
            trip_reason=reason,
        )
        payload_bytes = canonical_json(state.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO kill_switch_events (
                    status, tripped_at, trip_reason, cleared_at,
                    clear_reason, state_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.status,
                    tripped_at.isoformat(),
                    reason,
                    None,
                    None,
                    state.state_hash,
                    payload_str,
                ),
            )
        return state

    def clear_kill_switch(
        self,
        *,
        reason: str,
        cleared_at: datetime,
    ) -> KillSwitchStateV1:
        """Reset emergency kill switch to ACTIVE with operator confirmation."""
        state = build_kill_switch_state(
            status=KillSwitchStatus.ACTIVE,
            cleared_at=cleared_at,
            clear_reason=reason,
        )
        payload_bytes = canonical_json(state.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO kill_switch_events (
                    status, tripped_at, trip_reason, cleared_at,
                    clear_reason, state_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.status,
                    None,
                    None,
                    cleared_at.isoformat(),
                    reason,
                    state.state_hash,
                    payload_str,
                ),
            )
        return state

    def get_current_kill_switch_state(self) -> KillSwitchStateV1:
        """Return the current latching kill switch state."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM kill_switch_events
                ORDER BY sequence DESC LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row is None:
                return build_kill_switch_state(status=KillSwitchStatus.ACTIVE)
            return KillSwitchStateV1.model_validate_json(row["payload_json"])

    def is_kill_switch_tripped(self) -> bool:
        """Whether the persistent kill switch is currently in TRIPPED state."""
        return self.get_current_kill_switch_state().status == KillSwitchStatus.TRIPPED

    def record_verdict(self, verdict: RiskVerdictV1) -> None:
        """Record pre-execution order evaluation verdict."""
        payload_bytes = canonical_json(verdict.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO risk_verdicts (
                    order_id, status, reason, evaluated_at, verdict_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(verdict.order_id),
                    verdict.status,
                    verdict.reason,
                    verdict.evaluated_at.isoformat(),
                    verdict.verdict_hash,
                    payload_str,
                ),
            )

    def get_verdict_for_order(self, order_id: UUID) -> RiskVerdictV1 | None:
        """Retrieve verdict for a specific order by order_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM risk_verdicts WHERE order_id = ?",
                (str(order_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return RiskVerdictV1.model_validate_json(row["payload_json"])

    def list_verdicts(self) -> tuple[RiskVerdictV1, ...]:
        """List all recorded risk verdicts in sequence order."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM risk_verdicts ORDER BY sequence ASC"
            )
            rows = cursor.fetchall()
            return tuple(
                RiskVerdictV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def close(self) -> None:
        """Close SQLite database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
