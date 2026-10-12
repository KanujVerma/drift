"""Append-only persistent order intent journal with SQL triggers (M14-2).

Provides durable, append-only SQLite storage for outbound order intents and
inbound execution reports with SQL triggers preventing modification or deletion.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from drift.domain.execution import (
    ExecutionReportV1,
    OrderIntentV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.serialization.canonical import canonical_json

__all__ = [
    "DuplicateIntentRecordError",
    "ExecutionJournalError",
    "IntentAppendOnlyViolationError",
    "PersistentOrderIntentJournal",
]


class ExecutionJournalError(DriftError):
    """Base exception for order intent journal operations."""


class DuplicateIntentRecordError(ExecutionJournalError):
    """Raised on unique constraint violation (e.g. duplicate intent or report)."""


class IntentAppendOnlyViolationError(ExecutionJournalError):
    """Raised when an UPDATE or DELETE statement is attempted on append-only tables."""


_CREATE_ORDER_INTENTS_TABLE = """
CREATE TABLE IF NOT EXISTS order_intents (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL UNIQUE,
    client_order_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    security_id TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    limit_price TEXT,
    time_in_force TEXT NOT NULL,
    created_at TEXT NOT NULL,
    intent_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_intents_session
ON order_intents (session_key);
CREATE INDEX IF NOT EXISTS idx_order_intents_client
ON order_intents (client_order_id);

CREATE TRIGGER IF NOT EXISTS order_intents_no_update
BEFORE UPDATE ON order_intents
BEGIN
    SELECT RAISE(ABORT, 'order_intents is append-only');
END;

CREATE TRIGGER IF NOT EXISTS order_intents_no_delete
BEFORE DELETE ON order_intents
BEGIN
    SELECT RAISE(ABORT, 'order_intents is append-only');
END;
"""

_CREATE_EXECUTION_REPORTS_TABLE = """
CREATE TABLE IF NOT EXISTS execution_reports (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL,
    broker_order_id TEXT,
    status TEXT NOT NULL,
    cum_quantity INTEGER NOT NULL,
    leaves_quantity INTEGER NOT NULL,
    last_fill_price TEXT,
    last_fill_quantity INTEGER,
    avg_fill_price TEXT,
    fee_amount TEXT NOT NULL,
    rejection_reason TEXT,
    reported_at TEXT NOT NULL,
    report_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_reports_intent
ON execution_reports (intent_id);
CREATE INDEX IF NOT EXISTS idx_execution_reports_broker_order
ON execution_reports (broker_order_id);

CREATE TRIGGER IF NOT EXISTS execution_reports_no_update
BEFORE UPDATE ON execution_reports
BEGIN
    SELECT RAISE(ABORT, 'execution_reports is append-only');
END;

CREATE TRIGGER IF NOT EXISTS execution_reports_no_delete
BEFORE DELETE ON execution_reports
BEGIN
    SELECT RAISE(ABORT, 'execution_reports is append-only');
END;
"""


def _session_key_to_str(key: SessionKeyV1) -> str:
    """Format SessionKeyV1 as a deterministic indexing string."""
    return f"{key.mic}:{key.session_scope}:{key.local_date.isoformat()}"


class PersistentOrderIntentJournal:
    """SQLite-backed append-only persistent order intent journal.

    Maintains immutable records of outbound order intents and inbound execution reports,
    protected by database-level triggers preventing any UPDATE or DELETE operations.
    """

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
                raise IntentAppendOnlyViolationError(msg) from error
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
                raise DuplicateIntentRecordError(msg) from error
            raise ExecutionJournalError(msg) from error
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        conn = self._ensure_connected()
        conn.executescript(
            _CREATE_ORDER_INTENTS_TABLE + _CREATE_EXECUTION_REPORTS_TABLE
        )

    def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def record_intent(self, intent: OrderIntentV1) -> None:
        """Record an outbound order intent."""
        payload_bytes = canonical_json(intent.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")
        session_str = _session_key_to_str(intent.session_key)

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO order_intents (
                    intent_id, client_order_id, session_key, security_id, side,
                    quantity, order_type, limit_price, time_in_force, created_at,
                    intent_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(intent.intent_id),
                    intent.client_order_id,
                    session_str,
                    str(intent.security_id),
                    intent.side.value,
                    intent.quantity,
                    intent.order_type.value,
                    str(intent.limit_price) if intent.limit_price is not None else None,
                    intent.time_in_force.value,
                    intent.created_at.isoformat(),
                    intent.intent_hash,
                    payload_str,
                ),
            )

    def get_intent(self, intent_id: UUID) -> OrderIntentV1 | None:
        """Retrieve order intent by intent_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM order_intents WHERE intent_id = ?",
                (str(intent_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return OrderIntentV1.model_validate_json(row["payload_json"])

    def get_intent_by_client_id(self, client_order_id: str) -> OrderIntentV1 | None:
        """Retrieve order intent by client_order_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM order_intents WHERE client_order_id = ?",
                (client_order_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return OrderIntentV1.model_validate_json(row["payload_json"])

    def list_intents_for_session(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[OrderIntentV1, ...]:
        """List all order intents for a session in sequence order."""
        session_str = _session_key_to_str(session_key)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM order_intents
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_str,),
            )
            rows = cursor.fetchall()
            return tuple(
                OrderIntentV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def record_execution_report(self, report: ExecutionReportV1) -> None:
        """Record an inbound execution report."""
        payload_bytes = canonical_json(report.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_reports (
                    report_id, intent_id, broker_order_id, status, cum_quantity,
                    leaves_quantity, last_fill_price, last_fill_quantity,
                    avg_fill_price, fee_amount, rejection_reason, reported_at,
                    report_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(report.report_id),
                    str(report.intent_id),
                    report.broker_order_id,
                    report.status.value,
                    report.cum_quantity,
                    report.leaves_quantity,
                    (
                        str(report.last_fill_price)
                        if report.last_fill_price is not None
                        else None
                    ),
                    report.last_fill_quantity,
                    (
                        str(report.avg_fill_price)
                        if report.avg_fill_price is not None
                        else None
                    ),
                    str(report.fee_amount),
                    report.rejection_reason,
                    report.reported_at.isoformat(),
                    report.report_hash,
                    payload_str,
                ),
            )

    def get_execution_report(self, report_id: UUID) -> ExecutionReportV1 | None:
        """Retrieve execution report by report_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM execution_reports WHERE report_id = ?",
                (str(report_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ExecutionReportV1.model_validate_json(row["payload_json"])

    def list_execution_reports_for_intent(
        self,
        intent_id: UUID,
    ) -> tuple[ExecutionReportV1, ...]:
        """List all execution reports for an intent in sequence order."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM execution_reports
                WHERE intent_id = ?
                ORDER BY sequence ASC
                """,
                (str(intent_id),),
            )
            rows = cursor.fetchall()
            return tuple(
                ExecutionReportV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def get_latest_execution_report(
        self,
        intent_id: UUID,
    ) -> ExecutionReportV1 | None:
        """Retrieve latest execution report recorded for an intent."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM execution_reports
                WHERE intent_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (str(intent_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ExecutionReportV1.model_validate_json(row["payload_json"])
