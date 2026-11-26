"""Synthetic journal component tests, not execution or settlement integration."""

import multiprocessing
import os
import sqlite3
import threading
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


@pytest.mark.parametrize("legacy_first", [False, True])
@pytest.mark.parametrize("count", [2, 3])
def test_same_connection_interleaving_preserves_outcomes_and_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    legacy_first: bool,
) -> None:
    prechecked, release_first = threading.Event(), threading.Event()
    second_started, second_begun, release_second = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_connect = sqlite3.connect

    class PausedConnection(sqlite3.Connection):
        @property
        def in_transaction(self) -> bool:
            value = super().in_transaction
            if threading.current_thread().name == "first" and not prechecked.is_set():
                prechecked.set()
                if not release_first.wait(5):
                    raise RuntimeError("first thread timed out")
            return value

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = super().execute(sql, parameters)
            if sql == "BEGIN IMMEDIATE" and threading.current_thread().name == "second":
                second_begun.set()
                if not release_second.wait(5):
                    raise RuntimeError("second thread timed out")
            return cursor

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, factory=PausedConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    names = ("first", "second", "third")[:count]
    intents = [_intent(f"synthetic-token-{name}") for name in names]
    attempts = [uuid7() for _ in names]
    outcomes: dict[str, str] = {}

    def reserve(index: int) -> None:
        name = names[index]
        if index == 1:
            second_started.set()
        try:
            if index == 0 and legacy_first:
                journal.record_intent(intents[index])
            else:
                journal.record_synthetic_potential_send(
                    f"synthetic-account-{name}",
                    intents[index],
                    attempt_id=attempts[index],
                )
            outcomes[name] = "success"
        except BaseException as error:
            outcomes[name] = f"{type(error).__name__}: {error}"

    first = threading.Thread(target=reserve, args=(0,), name="first")
    second = threading.Thread(target=reserve, args=(1,), name="second")
    third = (
        threading.Thread(target=reserve, args=(2,), name="third")
        if count == 3
        else None
    )
    first.start()
    try:
        assert prechecked.wait(5)
        second.start()
        assert second_started.wait(5)
        second_begun.wait(0.5)
        if third is not None:
            third.start()
        release_first.set()
        first.join(5)
        release_second.set()
        second.join(5)
        if third is not None:
            third.join(5)
        assert not first.is_alive() and not second.is_alive()
        assert third is None or not third.is_alive()
    finally:
        release_first.set()
        release_second.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
        if third is not None and third.ident is not None:
            third.join(5)
    journal.close()
    reopened = PersistentOrderIntentJournal(db)
    rows = {
        name: (
            reopened.get_intent(intents[index].intent_id)
            if index == 0 and legacy_first
            else reopened.get_synthetic_potential_send(f"synthetic-account-{name}")
        )
        for index, name in enumerate(names)
    }
    reopened.close()
    assert outcomes == dict.fromkeys(names, "success"), (outcomes, rows)
    assert rows == {
        name: (
            intents[index]
            if index == 0 and legacy_first
            else (attempts[index], intents[index])
        )
        for index, name in enumerate(names)
    }


def test_failed_rollback_and_close_leave_escaped_handle_unrevoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = sqlite3.connect
    fail_close = True

    class CloseFailureConnection(sqlite3.Connection):
        def close(self) -> None:
            if fail_close:
                raise sqlite3.OperationalError("injected close failure")
            super().close()

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, factory=CloseFailureConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    escaped = journal.connection

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

    escaped.set_authorizer(deny_rollback)
    with pytest.raises(KeyboardInterrupt, match="original failure") as caught:
        with journal._transaction() as cursor:
            cursor.execute(
                """INSERT INTO synthetic_potential_sends_v1
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("synthetic-account-1", str(uuid7()), str(uuid7()), "t", "h", "{}"),
            )
            raise KeyboardInterrupt("original failure")
    assert any("rollback failed" in note for note in caught.value.__notes__)
    assert any("close failed" in note for note in caught.value.__notes__)
    assert escaped.in_transaction
    assert escaped.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(ExecutionJournalError, match="quarantin"):
        journal.get_synthetic_potential_send("synthetic-account-1")
    fail_close = False
    journal.close()
    with pytest.raises(sqlite3.ProgrammingError):
        escaped.execute("SELECT 1")
    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_synthetic_potential_send("synthetic-account-1") is None
    reopened.close()


def test_three_thread_success_requires_the_reopened_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force the old stale-precheck/foreign-rollback/foreign-commit schedule."""
    events = {
        name: threading.Event()
        for name in (
            "a_checked",
            "b_checked",
            "go_a",
            "go_b",
            "c_begun",
            "go_c",
            "b_begun",
            "throw_b",
            "c_inserted",
            "commit_c",
            "launch_a2",
            "a2_begun",
            "go_a2",
            "a_failed",
            "b_failed",
            "race",
        )
    }
    original_connect = sqlite3.connect
    seen: set[str] = set()

    class ScheduledConnection(sqlite3.Connection):
        @property
        def in_transaction(self) -> bool:
            value = super().in_transaction
            name = threading.current_thread().name
            if name in ("a", "b") and name not in seen:
                seen.add(name)
                events[f"{name}_checked"].set()
                if not events[f"go_{name}"].wait(5):
                    raise RuntimeError("precheck timed out")
            return value

        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            name = threading.current_thread().name
            if events["race"].is_set() and name == "c" and sql == "COMMIT":
                events["c_inserted"].set()
                if not events["commit_c"].wait(5):
                    raise RuntimeError("c commit timed out")
            result = super().execute(sql, parameters)
            if events["race"].is_set() and sql == "BEGIN IMMEDIATE":
                if name == "c":
                    events["c_begun"].set()
                    if not events["go_c"].wait(5):
                        raise RuntimeError("c begin timed out")
                elif name == "b":
                    events["b_begun"].set()
                    if not events["throw_b"].wait(5):
                        raise RuntimeError("b begin timed out")
                    raise RuntimeError("injected b interruption")
                elif name == "a":
                    events["a2_begun"].set()
                    if not events["go_a2"].wait(5):
                        raise RuntimeError("a2 begin timed out")
            return result

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, factory=ScheduledConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    intents = {
        name: _intent(f"synthetic-token-{name}") for name in ("a", "b", "c", "a2")
    }
    attempts = {name: uuid7() for name in intents}
    outcomes: dict[str, str] = {}

    def call(name: str) -> None:
        try:
            journal.record_synthetic_potential_send(
                f"synthetic-account-{name}", intents[name], attempt_id=attempts[name]
            )
            outcomes[name] = "success"
        except BaseException as error:
            outcomes[name] = f"{type(error).__name__}: {error}"

    def worker(name: str) -> None:
        call(name)
        if name in ("a", "b"):
            events[f"{name}_failed"].set()
        if name == "a" and events["race"].is_set():
            if events["launch_a2"].wait(5):
                call("a2")

    workers = {
        name: threading.Thread(target=worker, args=(name,), name=name)
        for name in ("a", "b", "c")
    }
    workers["a"].start()
    try:
        assert events["a_checked"].wait(5)
        workers["b"].start()
        vulnerable = events["b_checked"].wait(0.5)
        if vulnerable:
            events["race"].set()
        workers["c"].start()
        if vulnerable:
            assert events["c_begun"].wait(5)
            events["go_a"].set()
            assert events["a_failed"].wait(5)
            events["go_b"].set()
            assert events["b_begun"].wait(5)
            events["go_c"].set()
            assert events["c_inserted"].wait(5)
            events["throw_b"].set()
            assert events["b_failed"].wait(5)
            events["launch_a2"].set()
            assert events["a2_begun"].wait(5)
            events["commit_c"].set()
            workers["c"].join(5)
            events["go_a2"].set()
        else:
            events["go_a"].set()
            events["go_b"].set()
        for thread in workers.values():
            thread.join(5)
            assert not thread.is_alive()
    finally:
        for event in events.values():
            event.set()
        for thread in workers.values():
            if thread.ident is not None:
                thread.join(5)
    journal.close()
    reopened = PersistentOrderIntentJournal(db)
    rows = {
        name: reopened.get_synthetic_potential_send(f"synthetic-account-{name}")
        for name in ("a", "b", "c")
    }
    reopened.close()
    assert outcomes.get("c") == "success", outcomes
    assert rows["c"] == (attempts["c"], intents["c"]), (outcomes, rows)
    if not vulnerable:
        assert outcomes == {"a": "success", "b": "success", "c": "success"}
        assert rows == {name: (attempts[name], intents[name]) for name in rows}


def test_reentrant_journal_operations_refuse_without_deadlock(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    intent = _intent("legacy-token")
    with journal._transaction() as cursor:
        with pytest.raises(ExecutionJournalError, match="reentrant"):
            journal.get_intent(intent.intent_id)
        with pytest.raises(ExecutionJournalError, match="cannot close"):
            journal.close()
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
    journal.record_intent(intent)
    journal.close()
    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_intent(intent.intent_id) == intent
    reopened.close()


def test_concurrent_close_waits_for_active_transaction(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    journal = PersistentOrderIntentJournal(db)
    entered, release, close_started, close_done = (threading.Event() for _ in range(4))
    outcomes: list[str] = []

    def writer() -> None:
        try:
            with journal._transaction() as cursor:
                cursor.execute("SELECT 1")
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("writer timed out")
            outcomes.append("committed")
        except BaseException as error:
            outcomes.append(f"writer: {error}")

    def closer() -> None:
        close_started.set()
        try:
            journal.close()
            outcomes.append("closed")
        except BaseException as error:
            outcomes.append(f"close: {error}")
        finally:
            close_done.set()

    first = threading.Thread(target=writer)
    second = threading.Thread(target=closer)
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert close_started.wait(5)
        assert not close_done.wait(0.2)
        release.set()
        first.join(5)
        second.join(5)
        assert not first.is_alive() and not second.is_alive()
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert sorted(outcomes) == ["closed", "committed"]


def test_distinct_connections_compete_for_one_synthetic_key(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.sqlite"
    journals = [PersistentOrderIntentJournal(db), PersistentOrderIntentJournal(db)]
    intents = [_intent("synthetic-first"), _intent("synthetic-second")]
    attempts = [uuid7(), uuid7()]
    barrier = threading.Barrier(2, timeout=5)
    outcomes: dict[int, str] = {}

    def reserve(index: int) -> None:
        try:
            barrier.wait()
            journals[index].record_synthetic_potential_send(
                "synthetic-account-1", intents[index], attempt_id=attempts[index]
            )
            outcomes[index] = "success"
        except DuplicateIntentRecordError:
            outcomes[index] = "refused"
        except BaseException as error:
            outcomes[index] = f"{type(error).__name__}: {error}"

    workers = [threading.Thread(target=reserve, args=(i,)) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert not worker.is_alive()
    assert sorted(outcomes.values()) == ["refused", "success"]
    winner = next(index for index, result in outcomes.items() if result == "success")
    for journal in journals:
        journal.close()
    reopened = PersistentOrderIntentJournal(db)
    assert reopened.get_synthetic_potential_send("synthetic-account-1") == (
        attempts[winner],
        intents[winner],
    )
    reopened.close()


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
