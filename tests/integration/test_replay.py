import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest

from drift.errors import LedgerIntegrityError
from drift.ledger.interface import AuditEventDraft
from drift.ledger.replay import replay_events
from drift.ledger.sqlite import SQLiteLedger


def _draft(index: int) -> AuditEventDraft:
    return AuditEventDraft.model_validate(
        {
            "event_id": uuid7(),
            "event_type": "evidence.recorded",
            "timestamp": datetime(2026, 9, 1, 12, tzinfo=UTC)
            + timedelta(seconds=index),
            "entity_type": "evidence",
            "entity_id": uuid7(),
            "payload": {"result": index},
            "deduplication_key": f"source-{index}",
            "schema_version": "1",
        }
    )


def test_same_ledger_replays_identically_in_sequence_order(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    appended = tuple(ledger.append(_draft(index)) for index in range(3))

    first_replay = replay_events(ledger)
    second_replay = replay_events(ledger)

    assert isinstance(first_replay, tuple)
    assert first_replay == appended
    assert second_replay == appended


def test_replay_verifies_integrity_before_returning_events(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(path)
    ledger.append(_draft(0))
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute(
            "UPDATE audit_events SET payload_json = ? WHERE sequence = 1",
            ('{"result":999}',),
        )

    with pytest.raises(LedgerIntegrityError):
        replay_events(ledger)
