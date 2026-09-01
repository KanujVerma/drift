import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from uuid import uuid7

import pytest

from drift.domain.events import AuditEvent
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
    SQLiteLedger(path)

    with pytest.raises(LedgerIntegrityError):
        replay_events(ledger)


def test_replay_returns_the_same_snapshot_that_was_verified(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    append_started = Event()
    append_finished = Event()
    writer_errors: list[BaseException] = []
    appended_during_verification: list[AuditEvent] = []
    ledger = _AppendDuringVerificationLedger(path, append_started, append_finished)
    first = ledger.append(_draft(0))
    with sqlite3.connect(path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
    assert journal_mode == ("wal",)
    writer = SQLiteLedger(path)

    def append_concurrently() -> None:
        append_started.wait()
        try:
            appended_during_verification.append(writer.append(_draft(1)))
        except BaseException as error:
            writer_errors.append(error)
        finally:
            append_finished.set()

    thread = Thread(target=append_concurrently)
    thread.start()
    try:
        replayed = replay_events(ledger)
    finally:
        append_started.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert writer_errors == []
    assert replayed == (first,)
    assert ledger.events() == (first, appended_during_verification[0])


class _AppendDuringVerificationLedger(SQLiteLedger):
    """Commit a real append after rows are verified but before replay returns."""

    def __init__(
        self, path: Path, append_started: Event, append_finished: Event
    ) -> None:
        self._append_started = append_started
        self._append_finished = append_finished
        super().__init__(path)

    def _verify_rows(
        self,
        event_rows: list[sqlite3.Row],
        checkpoint_rows: list[sqlite3.Row],
    ) -> None:
        super()._verify_rows(event_rows, checkpoint_rows)
        self._append_started.set()
        if not self._append_finished.wait(timeout=5):
            raise AssertionError("concurrent append did not finish")
