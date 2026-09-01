import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid7

import pytest

from drift.errors import DuplicateEventError, LedgerCursorError, LedgerIntegrityError
from drift.ledger.hashing import GENESIS_HASH
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger

FIRST_TIMESTAMP = datetime(2026, 9, 1, 12, tzinfo=UTC)


def valid_event_input(**changes: object) -> AuditEventDraft:
    values: dict[str, object] = {
        "event_id": uuid7(),
        "event_type": "evidence.recorded",
        "timestamp": FIRST_TIMESTAMP,
        "entity_type": "evidence",
        "entity_id": uuid7(),
        "payload": {"result": "accepted"},
        "deduplication_key": None,
        "schema_version": "1",
    }
    values.update(changes)
    return AuditEventDraft.model_validate(values)


def test_append_assigns_genesis_then_previous_hash(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")

    first = ledger.append(valid_event_input(deduplication_key="first"))
    second = ledger.append(valid_event_input(deduplication_key="second"))

    assert first.previous_event_hash == GENESIS_HASH
    assert second.previous_event_hash == first.event_hash


def test_append_preserves_approved_timestamp_and_payload(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    timestamp = datetime(
        2026,
        9,
        1,
        5,
        30,
        45,
        123456,
        tzinfo=timezone(timedelta(hours=-7)),
    )
    draft = valid_event_input(timestamp=timestamp, payload={"nested": [1, None]})

    event = ledger.append(draft)

    assert event.timestamp == timestamp.astimezone(UTC)
    assert event.payload == {"nested": (1, None)}


def test_duplicate_event_id_is_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    draft = valid_event_input()
    ledger.append(draft)

    with pytest.raises(DuplicateEventError, match="event ID or deduplication key"):
        ledger.append(draft)


def test_duplicate_deduplication_key_is_rejected(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    ledger.append(valid_event_input(deduplication_key="source-row-1"))

    with pytest.raises(DuplicateEventError, match="event ID or deduplication key"):
        ledger.append(valid_event_input(deduplication_key="source-row-1"))


def test_null_deduplication_keys_can_repeat(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")

    first = ledger.append(valid_event_input())
    second = ledger.append(valid_event_input())

    assert ledger.events() == (first, second)


def test_get_and_events_return_persisted_events_in_sequence_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    first = ledger.append(valid_event_input(deduplication_key="first"))
    second = ledger.append(valid_event_input(deduplication_key="second"))

    reopened = SQLiteLedger(path)

    assert reopened.get(first.event_id) == first
    assert reopened.get(uuid7()) is None
    assert reopened.events() == (first, second)


def test_events_for_entity_filters_by_type_and_id_in_sequence_order(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    entity_id = uuid7()
    first = ledger.append(
        valid_event_input(entity_type="evidence", entity_id=entity_id)
    )
    ledger.append(valid_event_input(entity_type="hypothesis", entity_id=entity_id))
    second = ledger.append(
        valid_event_input(
            event_type="evidence.superseded",
            entity_type="evidence",
            entity_id=entity_id,
        )
    )
    ledger.append(valid_event_input(entity_type="evidence"))

    assert ledger.events_for_entity("evidence", entity_id) == (first, second)


def test_events_after_event_cursor_returns_strictly_later_rows(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    first = ledger.append(valid_event_input(deduplication_key="first"))
    second = ledger.append(valid_event_input(deduplication_key="second"))
    third = ledger.append(valid_event_input(deduplication_key="third"))

    assert ledger.events_after(first.event_id) == (second, third)
    assert ledger.events_after(third.event_id) == ()


def test_events_after_time_cursor_is_normalized_and_strict(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    first = ledger.append(valid_event_input(timestamp=FIRST_TIMESTAMP))
    second = ledger.append(
        valid_event_input(timestamp=FIRST_TIMESTAMP + timedelta(seconds=1))
    )
    third = ledger.append(
        valid_event_input(timestamp=FIRST_TIMESTAMP + timedelta(seconds=2))
    )
    equivalent_cursor = datetime(
        2026,
        9,
        1,
        5,
        0,
        1,
        tzinfo=timezone(timedelta(hours=-7)),
    )

    assert ledger.events_after(equivalent_cursor) == (third,)
    assert first not in ledger.events_after(equivalent_cursor)
    assert second not in ledger.events_after(equivalent_cursor)


def test_events_after_rejects_missing_event_cursor(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")

    with pytest.raises(LedgerCursorError, match="event cursor was not found"):
        ledger.events_after(uuid7())


@pytest.mark.parametrize("cursor", ["2026-09-01T12:00:00Z", 1, object()])
def test_events_after_rejects_unsupported_cursor_types(
    tmp_path: Path, cursor: object
) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")

    with pytest.raises(LedgerCursorError, match="UUID or timezone-aware datetime"):
        ledger.events_after(cursor)  # type: ignore[arg-type]


def test_events_after_rejects_naive_datetime_cursor(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")

    with pytest.raises(LedgerCursorError, match="timezone-aware"):
        ledger.events_after(datetime(2026, 9, 1, 12))


def test_database_rejects_event_updates_and_deletes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    event = ledger.append(valid_event_input())

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_events SET payload_json = '{}' WHERE event_id = ?",
                (str(event.event_id),),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM audit_events WHERE event_id = ?",
                (str(event.event_id),),
            )


def test_every_event_has_an_ordered_hash_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    first = ledger.append(valid_event_input())
    second = ledger.append(valid_event_input())

    with sqlite3.connect(path) as connection:
        checkpoints = connection.execute(
            "SELECT sequence, event_hash FROM audit_event_checkpoints ORDER BY sequence"
        ).fetchall()

    assert checkpoints == [(1, first.event_hash), (2, second.event_hash)]


def test_database_rejects_checkpoint_updates_and_deletes(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    ledger.append(valid_event_input())

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_event_checkpoints SET event_hash = ? WHERE sequence = 1",
                ("f" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM audit_event_checkpoints WHERE sequence = 1")


def test_verify_chain_accepts_empty_and_valid_ledgers(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    ledger.verify_chain()
    ledger.append(valid_event_input())
    ledger.append(valid_event_input())

    ledger.verify_chain()


def test_verify_chain_detects_final_event_deletion_via_checkpoint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    ledger.append(valid_event_input())
    final = ledger.append(valid_event_input())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER audit_events_no_delete")
        connection.execute(
            "DELETE FROM audit_events WHERE event_id = ?", (str(final.event_id),)
        )

    with pytest.raises(LedgerIntegrityError, match="checkpoint count"):
        ledger.verify_chain()


@pytest.mark.parametrize("tampering", ["missing", "hash"])
def test_verify_chain_detects_checkpoint_tampering(
    tmp_path: Path, tampering: str
) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    ledger.append(valid_event_input())
    with sqlite3.connect(path) as connection:
        if tampering == "missing":
            connection.execute("DROP TRIGGER audit_event_checkpoints_no_delete")
            connection.execute("DELETE FROM audit_event_checkpoints WHERE sequence = 1")
        else:
            connection.execute("DROP TRIGGER audit_event_checkpoints_no_update")
            connection.execute(
                "UPDATE audit_event_checkpoints SET event_hash = ? WHERE sequence = 1",
                ("f" * 64,),
            )

    with pytest.raises(LedgerIntegrityError, match="checkpoint"):
        ledger.verify_chain()


def test_verify_chain_detects_noncontiguous_sequence(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    ledger.append(valid_event_input())
    ledger.append(valid_event_input())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("UPDATE audit_events SET sequence = 3 WHERE sequence = 2")

    with pytest.raises(LedgerIntegrityError, match="sequence"):
        ledger.verify_chain()


def test_audit_event_draft_has_no_hash_fields() -> None:
    assert "previous_event_hash" not in AuditEventDraft.model_fields
    assert "event_hash" not in AuditEventDraft.model_fields
