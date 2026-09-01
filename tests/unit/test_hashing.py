from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.events import AuditEvent, UnsignedAuditEvent
from drift.ledger.hashing import GENESIS_HASH, build_audit_event, compute_event_hash
from drift.serialization.canonical import content_hash

HASH = "a" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def valid_unsigned_event(**changes: object) -> UnsignedAuditEvent:
    values: dict[str, object] = {
        "event_id": uuid7(),
        "event_type": "evidence.recorded",
        "occurred_at": NOW,
        "entity_type": "evidence",
        "entity_id": uuid7(),
        "payload": {"result": "accepted"},
        "previous_event_hash": GENESIS_HASH,
        "deduplication_key": None,
        "schema_version": "1",
    }
    values.update(changes)
    return UnsignedAuditEvent.model_validate(values)


def test_same_unsigned_event_produces_same_hash() -> None:
    unsigned = valid_unsigned_event()

    assert compute_event_hash(unsigned) == compute_event_hash(unsigned)


def test_each_unsigned_event_field_changes_event_hash() -> None:
    first = valid_unsigned_event()
    replacements: dict[str, object] = {
        "event_id": uuid7(),
        "event_type": "evidence.superseded",
        "occurred_at": datetime(2026, 9, 1, 13, tzinfo=UTC),
        "entity_type": "hypothesis",
        "entity_id": uuid7(),
        "payload": {"result": "rejected"},
        "previous_event_hash": HASH,
        "deduplication_key": "import-2026-09-01",
        "schema_version": "2",
    }

    for field, replacement in replacements.items():
        changed = first.model_copy(update={field: replacement})

        assert compute_event_hash(changed) != compute_event_hash(first), field


def test_absent_deduplication_key_is_hashed_as_explicit_null() -> None:
    unsigned = valid_unsigned_event()

    assert unsigned.deduplication_key is None
    assert compute_event_hash(unsigned) == content_hash(
        unsigned.model_dump(mode="python")
    )


def test_builder_sets_computed_hash() -> None:
    unsigned = valid_unsigned_event(previous_event_hash=GENESIS_HASH)

    event = build_audit_event(unsigned)

    assert event.event_hash == compute_event_hash(unsigned)
    assert event.model_dump(exclude={"event_hash"}) == unsigned.model_dump()


def test_signed_and_previous_hashes_must_be_lowercase_sha256() -> None:
    with pytest.raises(ValidationError):
        valid_unsigned_event(previous_event_hash="A" * 64)

    unsigned = valid_unsigned_event()
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            {**unsigned.model_dump(), "event_hash": "not-a-sha256"}
        )
