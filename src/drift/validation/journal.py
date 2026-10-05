"""Append-only persistent shadow validation journal with SQL triggers (M15-2).

Provides durable, append-only SQLite storage for market ticks, execution drift
reports, and shadow validation summaries with SQL triggers preventing mutation
or deletion.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from drift.domain.paper_validation import (
    ExecutionDriftReportV1,
    MarketTickV1,
    ShadowValidationSummaryV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.serialization.canonical import canonical_json

__all__ = [
    "DuplicateValidationRecordError",
    "PersistentShadowValidationJournal",
    "ValidationAppendOnlyViolationError",
    "ValidationJournalError",
]


class ValidationJournalError(DriftError):
    """Base exception for shadow validation journal failures."""


class DuplicateValidationRecordError(ValidationJournalError):
    """Raised on unique constraint violations (duplicate tick or drift report)."""


class ValidationAppendOnlyViolationError(ValidationJournalError):
    """Raised when an UPDATE or DELETE statement is attempted on append-only tables."""


_CREATE_MARKET_TICKS_TABLE = """
CREATE TABLE IF NOT EXISTS market_ticks (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id TEXT NOT NULL UNIQUE,
    security_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    last_price TEXT NOT NULL,
    last_size INTEGER NOT NULL,
    bid_price TEXT,
    bid_size INTEGER,
    ask_price TEXT,
    ask_size INTEGER,
    tick_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_ticks_security
ON market_ticks (security_id);
CREATE INDEX IF NOT EXISTS idx_market_ticks_timestamp
ON market_ticks (timestamp);

CREATE TRIGGER IF NOT EXISTS market_ticks_no_update
BEFORE UPDATE ON market_ticks
BEGIN
    SELECT RAISE(ABORT, 'market_ticks is append-only');
END;

CREATE TRIGGER IF NOT EXISTS market_ticks_no_delete
BEFORE DELETE ON market_ticks
BEGIN
    SELECT RAISE(ABORT, 'market_ticks is append-only');
END;
"""

_CREATE_EXECUTION_DRIFT_TABLE = """
CREATE TABLE IF NOT EXISTS execution_drift_reports (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    drift_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    intended_price TEXT NOT NULL,
    fill_price TEXT NOT NULL,
    slippage_bps TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    drift_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_drift_intent
ON execution_drift_reports (intent_id);
CREATE INDEX IF NOT EXISTS idx_execution_drift_security
ON execution_drift_reports (security_id);

CREATE TRIGGER IF NOT EXISTS execution_drift_no_update
BEFORE UPDATE ON execution_drift_reports
BEGIN
    SELECT RAISE(ABORT, 'execution_drift_reports is append-only');
END;

CREATE TRIGGER IF NOT EXISTS execution_drift_no_delete
BEFORE DELETE ON execution_drift_reports
BEGIN
    SELECT RAISE(ABORT, 'execution_drift_reports is append-only');
END;
"""

_CREATE_SHADOW_SUMMARIES_TABLE = """
CREATE TABLE IF NOT EXISTS shadow_validation_summaries (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    total_ticks_processed INTEGER NOT NULL,
    orders_generated INTEGER NOT NULL,
    orders_approved INTEGER NOT NULL,
    orders_rejected_risk INTEGER NOT NULL,
    orders_filled INTEGER NOT NULL,
    total_slippage_bps TEXT NOT NULL,
    mean_slippage_bps TEXT NOT NULL,
    max_slippage_bps TEXT NOT NULL,
    final_equity TEXT NOT NULL,
    summary_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_summaries_session
ON shadow_validation_summaries (session_key);

CREATE TRIGGER IF NOT EXISTS shadow_summaries_no_update
BEFORE UPDATE ON shadow_validation_summaries
BEGIN
    SELECT RAISE(ABORT, 'shadow_validation_summaries is append-only');
END;

CREATE TRIGGER IF NOT EXISTS shadow_summaries_no_delete
BEFORE DELETE ON shadow_validation_summaries
BEGIN
    SELECT RAISE(ABORT, 'shadow_validation_summaries is append-only');
END;
"""


def _session_key_to_str(session_key: SessionKeyV1) -> str:
    return (
        f"{session_key.mic}:{session_key.session_scope}:"
        f"{session_key.local_date.isoformat()}"
    )


class PersistentShadowValidationJournal:
    """Thread-confined append-only SQLite journal for paper validation telemetry."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None
        self._init_schema()

    def _ensure_connected(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                str(self._path),
                isolation_level=None,
                check_same_thread=False,
                timeout=30.0,
            )
            self._connection.row_factory = sqlite3.Row
            if str(self._path) != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA foreign_keys = ON;")
            self._connection.execute("PRAGMA busy_timeout = 5000;")
        return self._connection

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
                raise ValidationAppendOnlyViolationError(msg) from error
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
                raise DuplicateValidationRecordError(msg) from error
            raise ValidationJournalError(msg) from error
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        conn = self._ensure_connected()
        conn.executescript(
            _CREATE_MARKET_TICKS_TABLE
            + _CREATE_EXECUTION_DRIFT_TABLE
            + _CREATE_SHADOW_SUMMARIES_TABLE
        )

    def close(self) -> None:
        """Close SQLite database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def record_tick(self, tick: MarketTickV1) -> None:
        """Record an inbound market tick."""
        payload_bytes = canonical_json(tick.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO market_ticks (
                    tick_id, security_id, timestamp, last_price, last_size,
                    bid_price, bid_size, ask_price, ask_size, tick_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(tick.tick_id),
                    str(tick.security_id),
                    tick.timestamp.isoformat(),
                    str(tick.last_price),
                    tick.last_size,
                    str(tick.bid_price) if tick.bid_price is not None else None,
                    tick.bid_size,
                    str(tick.ask_price) if tick.ask_price is not None else None,
                    tick.ask_size,
                    tick.tick_hash,
                    payload_str,
                ),
            )

    def get_tick(self, tick_id: UUID) -> MarketTickV1 | None:
        """Retrieve market tick by tick_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM market_ticks WHERE tick_id = ?",
                (str(tick_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return MarketTickV1.model_validate_json(row["payload_json"])

    def list_ticks_for_security(
        self,
        security_id: UUID,
    ) -> tuple[MarketTickV1, ...]:
        """List all market ticks for a security in sequence order."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM market_ticks
                WHERE security_id = ?
                ORDER BY sequence ASC
                """,
                (str(security_id),),
            )
            rows = cursor.fetchall()
            return tuple(
                MarketTickV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def get_latest_tick(self, security_id: UUID) -> MarketTickV1 | None:
        """Retrieve latest recorded market tick for a security."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM market_ticks
                WHERE security_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (str(security_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return MarketTickV1.model_validate_json(row["payload_json"])

    def record_drift_report(self, report: ExecutionDriftReportV1) -> None:
        """Record an execution drift report."""
        payload_bytes = canonical_json(report.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_drift_reports (
                    drift_id, intent_id, security_id, intended_price,
                    fill_price, slippage_bps, recorded_at, drift_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(report.drift_id),
                    str(report.intent_id),
                    str(report.security_id),
                    str(report.intended_price),
                    str(report.fill_price),
                    str(report.slippage_bps),
                    report.recorded_at.isoformat(),
                    report.drift_hash,
                    payload_str,
                ),
            )

    def get_drift_report(self, drift_id: UUID) -> ExecutionDriftReportV1 | None:
        """Retrieve execution drift report by drift_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM execution_drift_reports WHERE drift_id = ?",
                (str(drift_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ExecutionDriftReportV1.model_validate_json(row["payload_json"])

    def list_drift_reports_for_security(
        self,
        security_id: UUID,
    ) -> tuple[ExecutionDriftReportV1, ...]:
        """List all execution drift reports for a security in sequence order."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM execution_drift_reports
                WHERE security_id = ?
                ORDER BY sequence ASC
                """,
                (str(security_id),),
            )
            rows = cursor.fetchall()
            return tuple(
                ExecutionDriftReportV1.model_validate_json(r["payload_json"])
                for r in rows
            )

    def record_summary(self, summary: ShadowValidationSummaryV1) -> None:
        """Record a shadow validation summary."""
        payload_bytes = canonical_json(summary.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")
        session_str = _session_key_to_str(summary.session_key)

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO shadow_validation_summaries (
                    validation_id, session_key, total_ticks_processed,
                    orders_generated, orders_approved, orders_rejected_risk,
                    orders_filled, total_slippage_bps, mean_slippage_bps,
                    max_slippage_bps, final_equity, summary_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(summary.validation_id),
                    session_str,
                    summary.total_ticks_processed,
                    summary.orders_generated,
                    summary.orders_approved,
                    summary.orders_rejected_risk,
                    summary.orders_filled,
                    str(summary.total_slippage_bps),
                    str(summary.mean_slippage_bps),
                    str(summary.max_slippage_bps),
                    str(summary.final_equity),
                    summary.summary_hash,
                    payload_str,
                ),
            )

    def get_summary(
        self,
        validation_id: UUID,
    ) -> ShadowValidationSummaryV1 | None:
        """Retrieve shadow validation summary by validation_id."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM shadow_validation_summaries
                WHERE validation_id = ?
                """,
                (str(validation_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ShadowValidationSummaryV1.model_validate_json(row["payload_json"])
