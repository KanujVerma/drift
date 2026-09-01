"""Standard-library SQLite implementation of the Drift audit ledger."""

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from uuid import UUID

from drift.domain.events import AuditEvent, UnsignedAuditEvent
from drift.errors import (
    DuplicateEventError,
    LedgerCursorError,
    LedgerIntegrityError,
)
from drift.ledger.hashing import GENESIS_HASH, build_audit_event, compute_event_hash
from drift.ledger.interface import AuditEventDraft
from drift.serialization.canonical import canonical_json

_AUDIT_EVENTS_TABLE = """
CREATE TABLE audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_event_hash TEXT NOT NULL,
    deduplication_key TEXT UNIQUE,
    schema_version TEXT NOT NULL,
    event_hash TEXT NOT NULL
)
"""

_AUDIT_EVENT_CHECKPOINTS_TABLE = """
CREATE TABLE audit_event_checkpoints (
    sequence INTEGER PRIMARY KEY,
    event_hash TEXT NOT NULL
)
"""

_AUDIT_EVENTS_NO_UPDATE_TRIGGER = """
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
"""

_AUDIT_EVENTS_NO_DELETE_TRIGGER = """
CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END
"""

_AUDIT_EVENT_CHECKPOINTS_NO_UPDATE_TRIGGER = """
CREATE TRIGGER audit_event_checkpoints_no_update
BEFORE UPDATE ON audit_event_checkpoints
BEGIN
    SELECT RAISE(ABORT, 'audit_event_checkpoints is append-only');
END
"""

_AUDIT_EVENT_CHECKPOINTS_NO_DELETE_TRIGGER = """
CREATE TRIGGER audit_event_checkpoints_no_delete
BEFORE DELETE ON audit_event_checkpoints
BEGIN
    SELECT RAISE(ABORT, 'audit_event_checkpoints is append-only');
END
"""

_REQUIRED_SCHEMA_OBJECTS = {
    ("table", "audit_events"): ("audit_events", _AUDIT_EVENTS_TABLE),
    ("table", "audit_event_checkpoints"): (
        "audit_event_checkpoints",
        _AUDIT_EVENT_CHECKPOINTS_TABLE,
    ),
    ("trigger", "audit_events_no_update"): (
        "audit_events",
        _AUDIT_EVENTS_NO_UPDATE_TRIGGER,
    ),
    ("trigger", "audit_events_no_delete"): (
        "audit_events",
        _AUDIT_EVENTS_NO_DELETE_TRIGGER,
    ),
    ("trigger", "audit_event_checkpoints_no_update"): (
        "audit_event_checkpoints",
        _AUDIT_EVENT_CHECKPOINTS_NO_UPDATE_TRIGGER,
    ),
    ("trigger", "audit_event_checkpoints_no_delete"): (
        "audit_event_checkpoints",
        _AUDIT_EVENT_CHECKPOINTS_NO_DELETE_TRIGGER,
    ),
}

_SCHEMA = (
    ";\n\n".join(
        statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1).replace(
            "CREATE TRIGGER ", "CREATE TRIGGER IF NOT EXISTS ", 1
        )
        for _, statement in _REQUIRED_SCHEMA_OBJECTS.values()
    )
    + ";"
)

_REQUIRED_UNIQUE_INDEXES = {
    (("event_id",), True, "u", False),
    (("deduplication_key",), True, "u", False),
}

_EVENT_COLUMNS = """
event_id,
event_type,
timestamp,
entity_type,
entity_id,
payload_json,
previous_event_hash,
deduplication_key,
schema_version,
event_hash
"""

_EVENT_STORAGE_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "entity_type",
    "entity_id",
    "payload_json",
    "previous_event_hash",
    "deduplication_key",
    "schema_version",
    "event_hash",
)


class SQLiteLedger:
    """A transactional, append-only SQLite audit ledger."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._read_only = False
        with self._connection() as connection:
            connection.executescript(_SCHEMA)

    @classmethod
    def open_existing(cls, path: Path) -> Self:
        """Open an existing ledger without creating or repairing schema objects."""
        ledger = cls.__new__(cls)
        ledger._path = path
        ledger._read_only = True
        return ledger

    def append(self, draft: AuditEventDraft) -> AuditEvent:
        """Assign chain hashes and atomically append an event and checkpoint."""
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                head = connection.execute(
                    "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous_hash = GENESIS_HASH if head is None else str(head[0])
                unsigned = UnsignedAuditEvent.model_validate(
                    {
                        **draft.model_dump(mode="python"),
                        "previous_event_hash": previous_hash,
                    }
                )
                event = build_audit_event(unsigned)
                cursor = connection.execute(
                    f"""
                    INSERT INTO audit_events ({_EVENT_COLUMNS})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _event_parameters(event),
                )
                sequence = cursor.lastrowid
                if sequence is None:
                    raise LedgerIntegrityError(
                        "SQLite did not assign an event sequence"
                    )
                connection.execute(
                    "INSERT INTO audit_event_checkpoints (sequence, event_hash) "
                    "VALUES (?, ?)",
                    (sequence, event.event_hash),
                )
                connection.commit()
                return event
            except sqlite3.IntegrityError as error:
                connection.rollback()
                if _is_duplicate_event(error):
                    message = "event ID or deduplication key already exists"
                    raise DuplicateEventError(message) from error
                raise
            except Exception:
                connection.rollback()
                raise

    def get(self, event_id: UUID) -> AuditEvent | None:
        """Return one event by identifier, or ``None`` when absent."""
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM audit_events WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
        return None if row is None else _row_to_event(row)

    def events(self) -> tuple[AuditEvent, ...]:
        """Return all events in database-assigned sequence order."""
        return self._query_events("ORDER BY sequence")

    def events_for_entity(
        self, entity_type: str, entity_id: UUID
    ) -> tuple[AuditEvent, ...]:
        """Return one entity's events in database-assigned sequence order."""
        return self._query_events(
            "WHERE entity_type = ? AND entity_id = ? ORDER BY sequence",
            (entity_type, str(entity_id)),
        )

    def events_after(self, cursor: UUID | datetime) -> tuple[AuditEvent, ...]:
        """Return events strictly after an event sequence or normalized time."""
        if isinstance(cursor, UUID):
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT sequence FROM audit_events WHERE event_id = ?",
                    (str(cursor),),
                ).fetchone()
            if row is None:
                raise LedgerCursorError("event cursor was not found in this ledger")
            return self._query_events(
                "WHERE sequence > ? ORDER BY sequence", (int(row[0]),)
            )
        if isinstance(cursor, datetime):
            if cursor.tzinfo is None or cursor.utcoffset() is None:
                message = "time cursor must be timezone-aware"
                raise LedgerCursorError(message)
            timestamp = _timestamp_text(cursor.astimezone(UTC))
            return self._query_events(
                "WHERE timestamp > ? ORDER BY sequence", (timestamp,)
            )
        message = "cursor must be an event UUID or timezone-aware datetime"
        raise LedgerCursorError(message)

    def verify_chain(self) -> None:
        """Verify sequence, chain links, hashes, and append checkpoints."""
        self.verified_events()

    def verified_events(self) -> tuple[AuditEvent, ...]:
        """Verify and return events from one explicit read transaction."""
        with self._connection(read_only=True) as connection:
            try:
                connection.execute("BEGIN")
                _verify_required_schema(connection)
                event_rows = connection.execute(
                    f"SELECT sequence, {_EVENT_COLUMNS} "
                    "FROM audit_events ORDER BY sequence"
                ).fetchall()
                checkpoint_rows = connection.execute(
                    "SELECT sequence, event_hash FROM audit_event_checkpoints "
                    "ORDER BY sequence"
                ).fetchall()
                self._verify_rows(event_rows, checkpoint_rows)
                events = tuple(_row_to_event(row, offset=1) for row in event_rows)
                connection.commit()
                return events
            except Exception:
                connection.rollback()
                raise

    def _verify_rows(
        self,
        event_rows: list[sqlite3.Row],
        checkpoint_rows: list[sqlite3.Row],
    ) -> None:
        if len(event_rows) != len(checkpoint_rows):
            message = (
                "event and checkpoint count mismatch: "
                f"{len(event_rows)} events, {len(checkpoint_rows)} checkpoints"
            )
            raise LedgerIntegrityError(message)

        previous_hash = GENESIS_HASH
        for expected_sequence, (event_row, checkpoint_row) in enumerate(
            zip(event_rows, checkpoint_rows, strict=True), start=1
        ):
            event_sequence = int(event_row[0])
            checkpoint_sequence = int(checkpoint_row[0])
            if event_sequence != expected_sequence:
                message = (
                    f"event sequence {event_sequence} is not contiguous at "
                    f"position {expected_sequence}"
                )
                raise LedgerIntegrityError(message)
            if checkpoint_sequence != expected_sequence:
                message = (
                    f"checkpoint sequence {checkpoint_sequence} does not match "
                    f"event sequence {expected_sequence}"
                )
                raise LedgerIntegrityError(message)
            try:
                event = _row_to_event(event_row, offset=1)
            except (TypeError, ValueError) as error:
                message = f"event sequence {expected_sequence} is malformed"
                raise LedgerIntegrityError(message) from error
            _verify_canonical_storage(event_row, event, expected_sequence, offset=1)
            checkpoint_hash = checkpoint_row[1]
            if checkpoint_hash != event.event_hash:
                message = f"checkpoint hash mismatch at sequence {expected_sequence}"
                raise LedgerIntegrityError(message)
            if event.previous_event_hash != previous_hash:
                message = (
                    f"previous event hash mismatch at sequence {expected_sequence}"
                )
                raise LedgerIntegrityError(message)
            if compute_event_hash(event) != event.event_hash:
                message = f"event hash mismatch at sequence {expected_sequence}"
                raise LedgerIntegrityError(message)
            previous_hash = event.event_hash

    def _connect(self, *, read_only: bool | None = None) -> sqlite3.Connection:
        use_read_only = self._read_only if read_only is None else read_only
        if use_read_only:
            connection = sqlite3.connect(
                f"{self._path.resolve().as_uri()}?mode=ro",
                isolation_level=None,
                uri=True,
            )
        else:
            connection = sqlite3.connect(self._path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(
        self, *, read_only: bool | None = None
    ) -> Iterator[sqlite3.Connection]:
        connection = self._connect(read_only=read_only)
        try:
            yield connection
        finally:
            connection.close()

    def _query_events(
        self,
        clause: str,
        parameters: Iterable[str | int] = (),
    ) -> tuple[AuditEvent, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM audit_events {clause}",
                tuple(parameters),
            ).fetchall()
        return tuple(_row_to_event(row) for row in rows)


def _verify_required_schema(connection: sqlite3.Connection) -> None:
    required_names = tuple(name for _, name in _REQUIRED_SCHEMA_OBJECTS)
    placeholders = ", ".join("?" for _ in required_names)
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        f"WHERE name IN ({placeholders})",
        required_names,
    ).fetchall()
    actual_objects = {
        (str(row[0]), str(row[1])): (str(row[2]), _normalize_schema_sql(str(row[3])))
        for row in rows
    }
    for identity, (table_name, definition) in _REQUIRED_SCHEMA_OBJECTS.items():
        expected = (table_name, _normalize_schema_sql(definition))
        if actual_objects.get(identity) != expected:
            object_type, object_name = identity
            message = (
                "required ledger schema object is missing or damaged: "
                f"{object_type} {object_name}"
            )
            raise LedgerIntegrityError(message)

    actual_indexes: set[tuple[tuple[str, ...], bool, str, bool]] = set()
    for row in connection.execute("PRAGMA index_list('audit_events')"):
        index_name = str(row[1])
        columns = tuple(
            str(column[2])
            for column in connection.execute(
                "SELECT seqno, cid, name FROM pragma_index_info(?) ORDER BY seqno",
                (index_name,),
            )
        )
        actual_indexes.add((columns, bool(row[2]), str(row[3]), bool(row[4])))
    if not _REQUIRED_UNIQUE_INDEXES.issubset(actual_indexes):
        message = "required ledger unique indexes are missing or damaged"
        raise LedgerIntegrityError(message)


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.removesuffix(";").split())


def _event_parameters(event: AuditEvent) -> tuple[object, ...]:
    return (
        str(event.event_id),
        event.event_type,
        _timestamp_text(event.timestamp),
        event.entity_type,
        str(event.entity_id),
        canonical_json(event.payload).decode("utf-8"),
        event.previous_event_hash,
        event.deduplication_key,
        event.schema_version,
        event.event_hash,
    )


def _row_to_event(row: sqlite3.Row, *, offset: int = 0) -> AuditEvent:
    return AuditEvent.model_validate(
        {
            "event_id": UUID(str(row[offset])),
            "event_type": str(row[offset + 1]),
            "timestamp": datetime.fromisoformat(str(row[offset + 2])),
            "entity_type": str(row[offset + 3]),
            "entity_id": UUID(str(row[offset + 4])),
            "payload": json.loads(str(row[offset + 5])),
            "previous_event_hash": str(row[offset + 6]),
            "deduplication_key": row[offset + 7],
            "schema_version": str(row[offset + 8]),
            "event_hash": str(row[offset + 9]),
        }
    )


def _verify_canonical_storage(
    row: sqlite3.Row,
    event: AuditEvent,
    sequence: int,
    *,
    offset: int = 0,
) -> None:
    stored_values = tuple(
        row[offset + index] for index in range(len(_EVENT_STORAGE_FIELDS))
    )
    canonical_values = _event_parameters(event)
    for field, stored, canonical in zip(
        _EVENT_STORAGE_FIELDS, stored_values, canonical_values, strict=True
    ):
        if stored != canonical:
            message = f"noncanonical stored {field} at sequence {sequence}"
            raise LedgerIntegrityError(message)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _is_duplicate_event(error: sqlite3.IntegrityError) -> bool:
    message = str(error)
    return (
        "audit_events.event_id" in message
        or "audit_events.deduplication_key" in message
    )
