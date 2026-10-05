"""Unit tests for PersistentOrderIntentJournal (M14-2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import (
    DuplicateIntentRecordError,
    IntentAppendOnlyViolationError,
    PersistentOrderIntentJournal,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY2 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2))


def test_journal_record_and_get_intent() -> None:
    """Verifies order intent recording and retrieval by intent_id and client_id."""
    journal = PersistentOrderIntentJournal()
    intent_id = uuid7()
    sec = uuid7()

    intent = build_order_intent(
        intent_id=intent_id,
        client_order_id="drift-ord-101",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )

    journal.record_intent(intent)

    # Retrieve by intent_id
    retrieved = journal.get_intent(intent_id)
    assert retrieved == intent

    # Retrieve by client_order_id
    by_client = journal.get_intent_by_client_id("drift-ord-101")
    assert by_client == intent

    # Non-existent lookups
    assert journal.get_intent(uuid7()) is None
    assert journal.get_intent_by_client_id("non-existent") is None


def test_journal_duplicate_intent_rejected() -> None:
    """Verifies duplicate intent_id or client_order_id raises error."""
    journal = PersistentOrderIntentJournal()
    intent_id = uuid7()
    sec = uuid7()

    intent1 = build_order_intent(
        intent_id=intent_id,
        client_order_id="drift-ord-dup-1",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    journal.record_intent(intent1)

    # Duplicate intent_id
    with pytest.raises(DuplicateIntentRecordError):
        journal.record_intent(intent1)

    # Duplicate client_order_id with different intent_id
    intent2 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="drift-ord-dup-1",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    with pytest.raises(DuplicateIntentRecordError):
        journal.record_intent(intent2)


def test_journal_list_intents_for_session() -> None:
    """Verifies session-scoped order intent query in sequence order."""
    journal = PersistentOrderIntentJournal()
    sec = uuid7()

    intent_s1_a = build_order_intent(
        intent_id=uuid7(),
        client_order_id="s1-a",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    intent_s1_b = build_order_intent(
        intent_id=uuid7(),
        client_order_id="s1-b",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=20,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    intent_s2_a = build_order_intent(
        intent_id=uuid7(),
        client_order_id="s2-a",
        session_key=KEY2,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=30,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )

    journal.record_intent(intent_s1_a)
    journal.record_intent(intent_s2_a)
    journal.record_intent(intent_s1_b)

    s1_intents = journal.list_intents_for_session(KEY1)
    assert len(s1_intents) == 2
    assert s1_intents[0] == intent_s1_a
    assert s1_intents[1] == intent_s1_b

    s2_intents = journal.list_intents_for_session(KEY2)
    assert len(s2_intents) == 1
    assert s2_intents[0] == intent_s2_a


def test_journal_record_and_query_execution_reports() -> None:
    """Verifies execution report lifecycle recording and latest report query."""
    journal = PersistentOrderIntentJournal()
    intent_id = uuid7()
    rep1_id = uuid7()
    rep2_id = uuid7()

    rep1 = build_execution_report(
        report_id=rep1_id,
        intent_id=intent_id,
        broker_order_id="b-1",
        status=ExecutionStatus.ACKNOWLEDGED,
        cum_quantity=0,
        leaves_quantity=100,
        reported_at=NOW,
    )
    rep2 = build_execution_report(
        report_id=rep2_id,
        intent_id=intent_id,
        broker_order_id="b-1",
        status=ExecutionStatus.FILLED,
        cum_quantity=100,
        leaves_quantity=0,
        last_fill_price=Decimal("150.25"),
        last_fill_quantity=100,
        avg_fill_price=Decimal("150.25"),
        fee_amount=Decimal("1.00"),
        reported_at=NOW,
    )

    journal.record_execution_report(rep1)
    journal.record_execution_report(rep2)

    # Query single report
    assert journal.get_execution_report(rep1_id) == rep1
    assert journal.get_execution_report(rep2_id) == rep2

    # Query reports for intent
    reports = journal.list_execution_reports_for_intent(intent_id)
    assert len(reports) == 2
    assert reports[0] == rep1
    assert reports[1] == rep2

    # Latest report
    latest = journal.get_latest_execution_report(intent_id)
    assert latest == rep2


def test_journal_append_only_triggers() -> None:
    """Verifies database triggers prevent UPDATE and DELETE on journal tables."""
    journal = PersistentOrderIntentJournal()
    intent_id = uuid7()
    report_id = uuid7()

    intent = build_order_intent(
        intent_id=intent_id,
        client_order_id="drift-ord-trig",
        session_key=KEY1,
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    journal.record_intent(intent)

    report = build_execution_report(
        report_id=report_id,
        intent_id=intent_id,
        status=ExecutionStatus.NEW,
        cum_quantity=0,
        leaves_quantity=10,
        reported_at=NOW,
    )
    journal.record_execution_report(report)

    # 1. UPDATE on order_intents
    with pytest.raises(IntentAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE order_intents SET quantity = 20 WHERE intent_id = ?",
                (str(intent_id),),
            )

    # 2. DELETE on order_intents
    with pytest.raises(IntentAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM order_intents WHERE intent_id = ?",
                (str(intent_id),),
            )

    # 3. UPDATE on execution_reports
    with pytest.raises(IntentAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE execution_reports SET status = 'filled' WHERE report_id = ?",
                (str(report_id),),
            )

    # 4. DELETE on execution_reports
    with pytest.raises(IntentAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM execution_reports WHERE report_id = ?",
                (str(report_id),),
            )


def test_journal_persistence_across_connections(tmp_path: Path) -> None:
    """Verifies records persist on disk across SQLite connection restarts."""
    db_file = tmp_path / "intent_journal.db"
    journal1 = PersistentOrderIntentJournal(db_path=db_file)

    intent_id = uuid7()
    intent = build_order_intent(
        intent_id=intent_id,
        client_order_id="disk-ord-1",
        session_key=KEY1,
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    journal1.record_intent(intent)
    journal1.close()

    # Reconnect
    journal2 = PersistentOrderIntentJournal(db_path=db_file)
    retrieved = journal2.get_intent(intent_id)
    assert retrieved == intent
    journal2.close()
