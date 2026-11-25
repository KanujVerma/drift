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
from drift.domain.execution_observation import (
    SyntheticBrokerFactV2,
    build_synthetic_observation,
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


@pytest.mark.parametrize("level", ["OFF", "NORMAL"])
def test_weak_sqlite_sync_refuses_reservation(tmp_path: Path, level: str) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.execute(f"PRAGMA synchronous = {level}")
    with pytest.raises(ExecutionJournalError, match="durable sync"):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


@pytest.mark.parametrize("mode", ["OFF", "MEMORY", "DELETE"])
def test_unsupported_journal_mode_refuses_reservation(
    tmp_path: Path, mode: str
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    actual_mode = journal.connection.execute(
        f"PRAGMA journal_mode = {mode}"
    ).fetchone()[0]
    assert actual_mode == mode.lower()
    with pytest.raises(ExecutionJournalError, match="WAL"):
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_durability_pragmas_are_checked_inside_the_reservation_transaction(
    tmp_path: Path,
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    assert journal.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert journal.connection.execute("PRAGMA synchronous").fetchone()[0] >= 2
    trace: list[str] = []
    journal.connection.set_trace_callback(trace.append)
    journal.record_synthetic_potential_send(
        "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
    )
    journal.connection.set_trace_callback(None)
    statements = [item.upper().strip() for item in trace]
    begin = statements.index("BEGIN IMMEDIATE")
    mode = statements.index("PRAGMA JOURNAL_MODE")
    sync = statements.index("PRAGMA SYNCHRONOUS")
    insert = next(i for i, stmt in enumerate(statements) if stmt.startswith("INSERT"))
    commit = statements.index("COMMIT")
    assert begin < mode < insert < commit
    assert begin < sync < insert
    journal.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interrupted_transaction_is_rolled_back(
    tmp_path: Path, interruption: type[BaseException]
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    with pytest.raises(interruption, match="synthetic interrupt"):
        with journal._transaction() as cursor:
            cursor.execute(
                """INSERT INTO synthetic_potential_sends_v1
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("synthetic-account-1", str(uuid7()), str(uuid7()), "t", "h", "{}"),
            )
            raise interruption("synthetic interrupt")
    assert not journal.connection.in_transaction
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_sqlite_automatic_rollback_keeps_original_trigger_error(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.executescript(
        """CREATE TRIGGER synthetic_rollback BEFORE INSERT
           ON synthetic_potential_sends_v1 BEGIN
           SELECT RAISE(ROLLBACK, 'original trigger error'); END;"""
    )
    with pytest.raises(ExecutionJournalError, match="original trigger error") as caught:
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    assert isinstance(caught.value.__cause__, sqlite3.IntegrityError)
    assert not journal.connection.in_transaction
    assert journal.get_synthetic_potential_send("synthetic-account-1") is None
    journal.close()


def test_failed_rollback_quarantines_connection_without_masking_error(
    tmp_path: Path,
) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    conn = journal.connection

    def deny_rollback(
        action: int,
        arg1: str | None,
        arg2: str | None,
        db_name: str | None,
        source: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "ROLLBACK":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_rollback)
    with pytest.raises(KeyboardInterrupt, match="original interruption") as caught:
        with journal._transaction() as cursor:
            cursor.execute(
                """INSERT INTO synthetic_potential_sends_v1
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("synthetic-account-1", str(uuid7()), str(uuid7()), "t", "h", "{}"),
            )
            raise KeyboardInterrupt("original interruption")
    assert any("rollback failed" in note for note in caught.value.__notes__)
    journal.close()
    with pytest.raises(ExecutionJournalError, match="quarantin"):
        journal.get_synthetic_potential_send("synthetic-account-1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_synthetic_potential_send("synthetic-account-1") is None
    reopened.close()


def test_rollback_failure_preserves_original_sqlite_error(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    conn = journal.connection
    conn.executescript(
        """CREATE TRIGGER synthetic_abort BEFORE INSERT
           ON synthetic_potential_sends_v1 BEGIN
           SELECT RAISE(ABORT, 'original synthetic failure'); END;"""
    )

    def deny_rollback(
        action: int,
        arg1: str | None,
        arg2: str | None,
        db_name: str | None,
        source: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == "ROLLBACK":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(deny_rollback)
    with pytest.raises(
        sqlite3.IntegrityError, match="original synthetic failure"
    ) as exc:
        journal.record_synthetic_potential_send(
            "synthetic-account-1", _intent("synthetic-token"), attempt_id=uuid7()
        )
    assert any("rollback failed" in note for note in exc.value.__notes__)
    with pytest.raises(ExecutionJournalError, match="quarantin"):
        _ = journal.connection


def test_legacy_write_auto_rollback_preserves_trigger_error(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.executescript(
        """CREATE TRIGGER legacy_rollback BEFORE INSERT ON order_intents BEGIN
           SELECT RAISE(ROLLBACK, 'legacy trigger error'); END;"""
    )
    with pytest.raises(ExecutionJournalError, match="legacy trigger error") as caught:
        journal.record_intent(_intent("legacy-token"))
    assert isinstance(caught.value.__cause__, sqlite3.IntegrityError)
    assert not journal.connection.in_transaction
    journal.close()


def test_preexisting_transaction_is_not_rolled_back_by_journal(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "synthetic.sqlite")
    journal.connection.execute("BEGIN IMMEDIATE")
    with pytest.raises(ExecutionJournalError, match="already in transaction"):
        journal.get_synthetic_potential_send("synthetic-account-1")
    assert journal.connection.in_transaction
    journal.connection.rollback()
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


def test_conflicting_and_not_sent_fixture_claims_do_not_release_reservation(
    tmp_path: Path,
) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    intent, attempt_id = _intent("synthetic-token"), uuid7()
    journal.record_synthetic_potential_send(
        "synthetic-account-1", intent, attempt_id=attempt_id
    )
    common: dict[str, Any] = dict(
        attempt_id=attempt_id,
        intent_id=intent.intent_id,
        intent_hash=intent.intent_hash,
        account_key="synthetic-account-1",
        observed_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    confirmed = build_synthetic_observation(
        observation_id=uuid7(),
        knowledge="CONFIRMED",
        reason_code=None,
        broker_fact=SyntheticBrokerFactV2(status="filled", cumulative_quantity=1),
        **common,
    )
    conflicting = build_synthetic_observation(
        observation_id=uuid7(),
        knowledge="CONFIRMED",
        reason_code=None,
        broker_fact=SyntheticBrokerFactV2(status="rejected"),
        **common,
    )
    not_sent = build_synthetic_observation(
        observation_id=uuid7(),
        knowledge="NOT_SENT",
        reason_code="authorization_refused",
        **common,
    )
    assert (
        len(
            {
                confirmed.observation_hash,
                conflicting.observation_hash,
                not_sent.observation_hash,
            }
        )
        == 3
    )
    journal.close()
    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_synthetic_potential_send("synthetic-account-1") == (
        attempt_id,
        intent,
    )
    with pytest.raises(DuplicateIntentRecordError):
        reopened.record_synthetic_potential_send(
            "synthetic-account-1", _intent("fresh-token"), attempt_id=uuid7()
        )
    reopened.close()


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
