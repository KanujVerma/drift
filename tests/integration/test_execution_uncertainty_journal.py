"""Synthetic journal component tests, not execution or settlement integration."""

import multiprocessing
import os
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

import pytest

from drift.domain.execution import (
    OrderIntentV1,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import (
    DuplicateIntentRecordError,
    ExecutionJournalError,
    PersistentOrderIntentJournal,
)
from drift.serialization.canonical import canonical_json


def _intent(token: str) -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=token,
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1)
        ),
        security_id=uuid7(),
        side="buy",
        quantity=1,
        order_type="market",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )


def _crash_after_reservation(db: str, intent_json: str, attempt_id: UUID) -> None:
    journal = PersistentOrderIntentJournal(db)
    intent = OrderIntentV1.model_validate_json(intent_json)
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )
    os._exit(23)


def _crash_before_commit(db: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """INSERT INTO synthetic_potential_sends_v1
           (account_key, attempt_id, intent_id, client_order_id,
            intent_hash, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "synthetic-account-1",
            str(uuid7()),
            str(uuid7()),
            "synthetic-token",
            "a" * 64,
            "{}",
        ),
    )
    os._exit(24)


def _contend(db: str, start: Any, ready: Any, results: Any, index: int) -> None:
    journal = PersistentOrderIntentJournal(db)
    intent = _intent(f"synthetic-token-{index}")
    ready.put(index)
    if not start.wait(15):
        results.put("timeout")
        return
    try:
        journal.record_synthetic_potential_send(
            "synthetic-account-1", intent, attempt_id=uuid7()
        )
        results.put("reserved")
    except DuplicateIntentRecordError:
        results.put("refused")
    finally:
        journal.close()


def test_reservation_persists_intent_and_potential_send_together(
    tmp_path: Path,
) -> None:
    db = tmp_path / "synthetic.sqlite"
    intent = _intent("synthetic-token-1")
    journal = PersistentOrderIntentJournal(db)
    attempt_id = uuid7()
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )
    journal.close()

    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_synthetic_potential_send("synthetic-account-1") == (
        attempt_id,
        intent,
    )
    reopened.close()


@pytest.mark.parametrize("db_path", [":memory:", ""])
def test_transient_sqlite_databases_refuse_synthetic_reservations(db_path: str) -> None:
    journal = PersistentOrderIntentJournal(db_path)
    with pytest.raises(ExecutionJournalError, match="durable"):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    journal.close()


def test_weak_sqlite_sync_refuses_reservation(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.execute("PRAGMA synchronous = OFF")
    with pytest.raises(ExecutionJournalError, match="durable sync"):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_duplicate_and_fresh_intents_refused_without_overwriting(
    tmp_path: Path,
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    intent = _intent("synthetic-token-1")
    attempt_id = uuid7()
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )
    for candidate in (intent, _intent("synthetic-token-2")):
        with pytest.raises(DuplicateIntentRecordError):
            journal.record_synthetic_potential_send(
                "synthetic-account-1", candidate, attempt_id=uuid7()
            )
    with pytest.raises(DuplicateIntentRecordError):
        journal.record_synthetic_potential_send(
            "synthetic-account-2", intent, attempt_id=uuid7()
        )
    assert journal.get_synthetic_potential_send("synthetic-account-1") == (
        attempt_id,
        intent,
    )
    journal.close()


def test_fake_send_sees_committed_intent_and_marker_on_other_connection(
    tmp_path: Path,
) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    intent, attempt_id = _intent("synthetic-token"), uuid7()
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )

    def fake_send() -> None:
        independent = PersistentOrderIntentJournal(db)
        assert independent.get_synthetic_potential_send("synthetic-account-1") == (
            attempt_id,
            intent,
        )
        independent.close()

    fake_send()
    journal.close()


def test_replace_cannot_overwrite_synthetic_reservation(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    intent, attempt_id = _intent("synthetic-token"), uuid7()
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )
    with pytest.raises(sqlite3.IntegrityError):
        journal.connection.execute(
            """INSERT OR REPLACE INTO synthetic_potential_sends_v1
               (account_key, attempt_id, intent_id, client_order_id,
                intent_hash, payload_json) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "synthetic-account-1",
                str(uuid7()),
                str(uuid7()),
                "new",
                "a" * 64,
                "{}",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        journal.connection.execute("DELETE FROM synthetic_potential_sends_v1")
    with pytest.raises(sqlite3.IntegrityError):
        journal.connection.execute(
            "UPDATE synthetic_potential_sends_v1 SET payload_json = '{}'"
        )
    assert journal.get_synthetic_potential_send("synthetic-account-1") == (
        attempt_id,
        intent,
    )
    journal.close()


def test_failed_insert_is_atomic_and_never_reaches_fake_send(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.execute(
        """CREATE TRIGGER fail_synthetic_insert BEFORE INSERT
           ON synthetic_potential_sends_v1 BEGIN
           SELECT RAISE(ABORT, 'synthetic failure'); END"""
    )
    called: list[str] = []
    with pytest.raises(ExecutionJournalError, match="synthetic failure"):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token-1"), attempt_id=uuid7()
        )
        called.append("fake send")
    assert called == []
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_commit_failure_rolls_back_record_before_fake_send(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.executescript(
        """CREATE TABLE synthetic_parent (id INTEGER PRIMARY KEY);
        CREATE TABLE synthetic_child (
            parent_id INTEGER REFERENCES synthetic_parent(id)
            DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TRIGGER synthetic_commit_failure AFTER INSERT
        ON synthetic_potential_sends_v1 BEGIN
            INSERT INTO synthetic_child(parent_id) VALUES (1);
        END;"""
    )
    called: list[str] = []
    with pytest.raises(ExecutionJournalError):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
        called.append("fake send")
    assert called == []
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_crashed_process_reopens_with_original_barrier(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    intent = _intent("synthetic-token-1")
    attempt_id = uuid7()
    ctx = multiprocessing.get_context("spawn")
    worker = ctx.Process(
        target=_crash_after_reservation,
        args=(str(db), intent.model_dump_json(), attempt_id),
    )
    worker.start()
    worker.join(20)
    assert worker.exitcode == 23
    journal = PersistentOrderIntentJournal(db)
    assert journal.get_synthetic_potential_send("synthetic-account-1") == (
        attempt_id,
        intent,
    )
    with pytest.raises(DuplicateIntentRecordError):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token-fresh"), attempt_id=uuid7()
        )
    journal.close()


def test_process_crash_before_commit_leaves_no_partial_record(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    PersistentOrderIntentJournal(db).close()
    worker = multiprocessing.get_context("spawn").Process(
        target=_crash_before_commit, args=(str(db),)
    )
    worker.start()
    worker.join(20)
    assert worker.exitcode == 24
    journal = PersistentOrderIntentJournal(db)
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_processes_contend_with_independent_sqlite_connections(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    PersistentOrderIntentJournal(db).close()
    ctx = multiprocessing.get_context("spawn")
    start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
    workers = [
        ctx.Process(target=_contend, args=(str(db), start, ready, results, i))
        for i in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        for _ in workers:
            ready.get(timeout=20)
        start.set()
        outcomes = sorted(results.get(timeout=20) for _ in workers)
        assert outcomes == ["refused", "refused", "refused", "reserved"]
        for worker in workers:
            worker.join(20)
            assert worker.exitcode == 0
    finally:
        start.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        ready.close()
        results.close()


def test_legacy_rows_and_payload_bytes_are_preserved(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    intent = _intent("legacy-token")
    journal.record_intent(intent)
    report = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        status="rejected",
        cum_quantity=0,
        leaves_quantity=1,
        rejection_reason="legacy-timeout",
        reported_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    journal.record_execution_report(report)
    before = tuple(journal.connection.execute("SELECT * FROM order_intents").fetchone())
    report_before = tuple(
        journal.connection.execute("SELECT * FROM execution_reports").fetchone()
    )
    assert before[-1].encode() == canonical_json(intent.model_dump(mode="python"))
    assert report_before[-1].encode() == canonical_json(
        report.model_dump(mode="python")
    )
    journal.close()
    journal = PersistentOrderIntentJournal(db)
    journal.record_synthetic_potential_send(
        "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
    )
    after = tuple(journal.connection.execute("SELECT * FROM order_intents").fetchone())
    assert after == before
    assert (
        tuple(journal.connection.execute("SELECT * FROM execution_reports").fetchone())
        == report_before
    )
    assert journal.get_intent(intent.intent_id) == intent
    assert journal.get_execution_report(report.report_id) == report
    with pytest.raises(sqlite3.IntegrityError):
        journal.connection.execute("DELETE FROM order_intents")
    journal.close()
