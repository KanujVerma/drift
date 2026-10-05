"""Append-only SQLite simulation execution journal and replay engine (M12-2).

Records simulated orders, fills, rejections, and reconciliations in a
dedicated SQLite database with strict append-only SQLite triggers.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from drift.domain.evaluator_portfolio import PortfolioFillV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    ExecutionReconciliationV1,
    SimulatedFillV1,
    SimulatedOrderV1,
    SimulatedRejectionV1,
)
from drift.errors import DriftError
from drift.serialization.canonical import canonical_json

__all__ = [
    "DuplicateJournalRecordError",
    "JournalAppendOnlyViolationError",
    "ShadowJournalError",
    "SimulationExecutionJournal",
]


class ShadowJournalError(DriftError):
    """Base exception for shadow broker execution journal errors."""


class DuplicateJournalRecordError(ShadowJournalError):
    """Raised when an attempt is made to insert a duplicate journal record."""


class JournalAppendOnlyViolationError(ShadowJournalError):
    """Raised when an attempt is made to mutate or delete existing journal records."""


_CREATE_SIMULATED_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS simulated_orders (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    security_id TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    limit_price TEXT,
    created_at TEXT NOT NULL,
    order_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simulated_orders_session
ON simulated_orders (session_key);
CREATE INDEX IF NOT EXISTS idx_simulated_orders_security
ON simulated_orders (security_id);

CREATE TRIGGER IF NOT EXISTS simulated_orders_no_update
BEFORE UPDATE ON simulated_orders
BEGIN
    SELECT RAISE(ABORT, 'simulated_orders is append-only');
END;

CREATE TRIGGER IF NOT EXISTS simulated_orders_no_delete
BEFORE DELETE ON simulated_orders
BEGIN
    SELECT RAISE(ABORT, 'simulated_orders is append-only');
END;
"""

_CREATE_SIMULATED_FILLS_TABLE = """
CREATE TABLE IF NOT EXISTS simulated_fills (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    security_id TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    fill_price TEXT NOT NULL,
    transaction_costs TEXT NOT NULL,
    filled_at TEXT NOT NULL,
    fill_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simulated_fills_order
ON simulated_fills (order_id);
CREATE INDEX IF NOT EXISTS idx_simulated_fills_session
ON simulated_fills (session_key);
CREATE INDEX IF NOT EXISTS idx_simulated_fills_security
ON simulated_fills (security_id);

CREATE TRIGGER IF NOT EXISTS simulated_fills_no_update
BEFORE UPDATE ON simulated_fills
BEGIN
    SELECT RAISE(ABORT, 'simulated_fills is append-only');
END;

CREATE TRIGGER IF NOT EXISTS simulated_fills_no_delete
BEFORE DELETE ON simulated_fills
BEGIN
    SELECT RAISE(ABORT, 'simulated_fills is append-only');
END;
"""

_CREATE_SIMULATED_REJECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS simulated_rejections (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    security_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    rejection_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simulated_rejections_session
ON simulated_rejections (session_key);

CREATE TRIGGER IF NOT EXISTS simulated_rejections_no_update
BEFORE UPDATE ON simulated_rejections
BEGIN
    SELECT RAISE(ABORT, 'simulated_rejections is append-only');
END;

CREATE TRIGGER IF NOT EXISTS simulated_rejections_no_delete
BEFORE DELETE ON simulated_rejections
BEGIN
    SELECT RAISE(ABORT, 'simulated_rejections is append-only');
END;
"""

_CREATE_EXECUTION_RECONCILIATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS execution_reconciliations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_id TEXT NOT NULL UNIQUE,
    session_key TEXT NOT NULL,
    reconciled_at TEXT NOT NULL,
    cash TEXT NOT NULL,
    holdings_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    reconciliation_hash TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reconciliations_session
ON execution_reconciliations (session_key);

CREATE TRIGGER IF NOT EXISTS execution_reconciliations_no_update
BEFORE UPDATE ON execution_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'execution_reconciliations is append-only');
END;

CREATE TRIGGER IF NOT EXISTS execution_reconciliations_no_delete
BEFORE DELETE ON execution_reconciliations
BEGIN
    SELECT RAISE(ABORT, 'execution_reconciliations is append-only');
END;
"""


def _session_key_to_str(key: SessionKeyV1) -> str:
    """Format SessionKeyV1 as a deterministic indexing string."""
    return f"{key.mic}:{key.session_scope}:{key.local_date.isoformat()}"


class SimulationExecutionJournal:
    """Append-only simulation execution journal and replay engine.

    Persists simulated orders, fills, rejections, and state reconciliations
    in a dedicated SQLite database protected by SQL-level immutability triggers.
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
                raise JournalAppendOnlyViolationError(msg) from error
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
                raise DuplicateJournalRecordError(msg) from error
            raise ShadowJournalError(msg) from error
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        conn = self._ensure_connected()
        conn.executescript(
            _CREATE_SIMULATED_ORDERS_TABLE
            + _CREATE_SIMULATED_FILLS_TABLE
            + _CREATE_SIMULATED_REJECTIONS_TABLE
            + _CREATE_EXECUTION_RECONCILIATIONS_TABLE
        )

    def record_order(self, order: SimulatedOrderV1) -> None:
        """Record an incoming simulated order."""
        payload_bytes = canonical_json(order.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")
        session_str = _session_key_to_str(order.session_key)

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO simulated_orders (
                    order_id, session_key, security_id, side, quantity,
                    order_type, limit_price, created_at, order_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(order.order_id),
                    session_str,
                    str(order.security_id),
                    order.side,
                    order.quantity,
                    order.order_type,
                    str(order.limit_price) if order.limit_price is not None else None,
                    order.created_at.isoformat(),
                    order.order_hash,
                    payload_str,
                ),
            )

    def record_fill(
        self,
        fill: SimulatedFillV1,
        session_key: SessionKeyV1 | None = None,
    ) -> None:
        """Record a generated simulated fill."""
        payload_bytes = canonical_json(fill.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")

        with self._transaction() as cursor:
            if session_key is None:
                cursor.execute(
                    "SELECT session_key FROM simulated_orders WHERE order_id = ?",
                    (str(fill.order_id),),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ShadowJournalError(
                        f"Order {fill.order_id} not found in journal; "
                        "cannot record fill"
                    )
                session_str = row["session_key"]
            else:
                session_str = _session_key_to_str(session_key)

            cursor.execute(
                """
                INSERT INTO simulated_fills (
                    fill_id, order_id, session_key, security_id, side, quantity,
                    fill_price, transaction_costs, filled_at, fill_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(fill.fill_id),
                    str(fill.order_id),
                    session_str,
                    str(fill.security_id),
                    fill.side,
                    fill.quantity,
                    str(fill.fill_price),
                    str(fill.transaction_costs),
                    fill.filled_at.isoformat(),
                    fill.fill_hash,
                    payload_str,
                ),
            )

    def record_rejection(self, rejection: SimulatedRejectionV1) -> None:
        """Record a rejected order with diagnostic reason."""
        payload_bytes = canonical_json(rejection.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")
        session_str = _session_key_to_str(rejection.session_key)

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO simulated_rejections (
                    order_id, session_key, security_id, reason,
                    rejected_at, rejection_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(rejection.order_id),
                    session_str,
                    str(rejection.security_id),
                    rejection.reason,
                    rejection.rejected_at.isoformat(),
                    rejection.rejection_hash,
                    payload_str,
                ),
            )

    def record_reconciliation(
        self,
        reconciliation: ExecutionReconciliationV1,
    ) -> None:
        """Record a snapshot reconciliation against portfolio state."""
        payload_bytes = canonical_json(reconciliation.model_dump(mode="python"))
        payload_str = payload_bytes.decode("utf-8")
        session_str = _session_key_to_str(reconciliation.session_key)

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO execution_reconciliations (
                    reconciliation_id, session_key, reconciled_at, cash,
                    holdings_count, status, reconciliation_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(reconciliation.reconciliation_id),
                    session_str,
                    reconciliation.reconciled_at.isoformat(),
                    str(reconciliation.cash),
                    reconciliation.holdings_count,
                    reconciliation.status,
                    reconciliation.reconciliation_hash,
                    payload_str,
                ),
            )

    def get_order(self, order_id: UUID) -> SimulatedOrderV1 | None:
        """Retrieve simulated order by order_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM simulated_orders WHERE order_id = ?",
                (str(order_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return SimulatedOrderV1.model_validate_json(row["payload_json"])

    def get_fill_by_order(self, order_id: UUID) -> SimulatedFillV1 | None:
        """Retrieve simulated fill by parent order_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM simulated_fills WHERE order_id = ?",
                (str(order_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return SimulatedFillV1.model_validate_json(row["payload_json"])

    def get_rejection_by_order(self, order_id: UUID) -> SimulatedRejectionV1 | None:
        """Retrieve rejection record by order_id."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT payload_json FROM simulated_rejections WHERE order_id = ?",
                (str(order_id),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return SimulatedRejectionV1.model_validate_json(row["payload_json"])

    def list_orders_for_session(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[SimulatedOrderV1, ...]:
        """List all simulated orders recorded for a session in sequence order."""
        session_str = _session_key_to_str(session_key)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM simulated_orders
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_str,),
            )
            rows = cursor.fetchall()
            return tuple(
                SimulatedOrderV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def list_fills_for_session(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[SimulatedFillV1, ...]:
        """List all simulated fills recorded for a session in sequence order."""
        session_str = _session_key_to_str(session_key)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM simulated_fills
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_str,),
            )
            rows = cursor.fetchall()
            return tuple(
                SimulatedFillV1.model_validate_json(r["payload_json"]) for r in rows
            )

    def list_rejections_for_session(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[SimulatedRejectionV1, ...]:
        """List all simulated rejections recorded for a session in sequence order."""
        session_str = _session_key_to_str(session_key)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM simulated_rejections
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_str,),
            )
            rows = cursor.fetchall()
            return tuple(
                SimulatedRejectionV1.model_validate_json(r["payload_json"])
                for r in rows
            )

    def list_reconciliations_for_session(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[ExecutionReconciliationV1, ...]:
        """List all reconciliations recorded for a session in sequence order."""
        session_str = _session_key_to_str(session_key)
        with self._transaction() as cursor:
            cursor.execute(
                """
                SELECT payload_json FROM execution_reconciliations
                WHERE session_key = ?
                ORDER BY sequence ASC
                """,
                (session_str,),
            )
            rows = cursor.fetchall()
            return tuple(
                ExecutionReconciliationV1.model_validate_json(r["payload_json"])
                for r in rows
            )

    def replay_session_fills(
        self,
        session_key: SessionKeyV1,
    ) -> tuple[PortfolioFillV1, ...]:
        """Project and replay chronological fills to M2 PortfolioFillV1."""
        fills = self.list_fills_for_session(session_key)
        return tuple(fill.to_portfolio_fill() for fill in fills)

    def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
