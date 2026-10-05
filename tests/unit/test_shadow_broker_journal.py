"""Unit tests for Shadow Broker append-only SQLite journal (M12-2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.evaluator_portfolio import PortfolioFillV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    build_execution_reconciliation,
    build_simulated_fill,
    build_simulated_order,
    build_simulated_rejection,
)
from drift.shadow.journal import (
    DuplicateJournalRecordError,
    JournalAppendOnlyViolationError,
    ShadowJournalError,
    SimulationExecutionJournal,
)

NOW = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
KEY = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY_OTHER = SessionKeyV1(
    mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
)


def test_journal_initialization(tmp_path: Path) -> None:
    """Verifies in-memory and on-disk journal creation and schema triggers."""
    db_file = tmp_path / "journal.db"
    with SimulationExecutionJournal(db_file) as journal:
        assert journal.connection is not None
        # Check tables exist
        cursor = journal.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "simulated_orders" in tables
        assert "simulated_fills" in tables
        assert "simulated_rejections" in tables
        assert "execution_reconciliations" in tables


def test_record_and_retrieve_order() -> None:
    """Verifies recording orders and retrieval by ID or session."""
    journal = SimulationExecutionJournal()
    sec1 = uuid7()
    sec2 = uuid7()
    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY,
        security_id=sec1,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY,
        security_id=sec2,
        side="sell",
        quantity=5,
        created_at=NOW,
    )
    ord_other = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY_OTHER,
        security_id=sec1,
        side="buy",
        quantity=20,
        created_at=NOW,
    )

    journal.record_order(ord1)
    journal.record_order(ord2)
    journal.record_order(ord_other)

    # Retrieve by ID
    assert journal.get_order(ord1.order_id) == ord1
    assert journal.get_order(ord2.order_id) == ord2
    assert journal.get_order(uuid7()) is None

    # List by session
    session_orders = journal.list_orders_for_session(KEY)
    assert len(session_orders) == 2
    assert session_orders[0] == ord1
    assert session_orders[1] == ord2

    # Duplicate rejection
    with pytest.raises(DuplicateJournalRecordError):
        journal.record_order(ord1)


def test_record_and_retrieve_fill() -> None:
    """Verifies recording fills linked to orders and session querying."""
    journal = SimulationExecutionJournal()
    sec = uuid7()
    order_id = uuid7()
    order = build_simulated_order(
        order_id=order_id,
        session_key=KEY,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW,
    )
    journal.record_order(order)

    fill_id = uuid7()
    fill = build_simulated_fill(
        fill_id=fill_id,
        order_id=order_id,
        security_id=sec,
        side="buy",
        quantity=50,
        fill_price=Decimal("150.25"),
        transaction_costs=Decimal("0.50"),
        filled_at=NOW,
    )
    journal.record_fill(fill)

    # Retrieve by order
    retrieved = journal.get_fill_by_order(order_id)
    assert retrieved == fill
    assert journal.get_fill_by_order(uuid7()) is None

    # List by session
    session_fills = journal.list_fills_for_session(KEY)
    assert len(session_fills) == 1
    assert session_fills[0] == fill

    # Duplicate fill rejection
    with pytest.raises(DuplicateJournalRecordError):
        journal.record_fill(fill)

    # Fill for unknown order without session_key fails
    orphan_fill = build_simulated_fill(
        fill_id=uuid7(),
        order_id=uuid7(),
        security_id=sec,
        side="sell",
        quantity=10,
        fill_price=Decimal("155.00"),
        filled_at=NOW,
    )
    with pytest.raises(ShadowJournalError, match="not found in journal"):
        journal.record_fill(orphan_fill)


def test_record_and_retrieve_rejection() -> None:
    """Verifies recording and retrieving rejections."""
    journal = SimulationExecutionJournal()
    sec = uuid7()
    order_id = uuid7()

    rej = build_simulated_rejection(
        order_id=order_id,
        session_key=KEY,
        security_id=sec,
        reason="ineligible_security: market halt",
        rejected_at=NOW,
    )
    journal.record_rejection(rej)

    retrieved = journal.get_rejection_by_order(order_id)
    assert retrieved == rej
    assert journal.get_rejection_by_order(uuid7()) is None

    session_rejections = journal.list_rejections_for_session(KEY)
    assert len(session_rejections) == 1
    assert session_rejections[0] == rej

    with pytest.raises(DuplicateJournalRecordError):
        journal.record_rejection(rej)


def test_record_and_retrieve_reconciliation() -> None:
    """Verifies recording and retrieving reconciliations."""
    journal = SimulationExecutionJournal()
    rec_id = uuid7()

    rec = build_execution_reconciliation(
        reconciliation_id=rec_id,
        session_key=KEY,
        reconciled_at=NOW,
        cash=Decimal("50000.00"),
        holdings_count=2,
        status="matched",
    )
    journal.record_reconciliation(rec)

    reconciliations = journal.list_reconciliations_for_session(KEY)
    assert len(reconciliations) == 1
    assert reconciliations[0] == rec

    with pytest.raises(DuplicateJournalRecordError):
        journal.record_reconciliation(rec)


def test_append_only_triggers_prevent_mutation() -> None:
    """Verifies SQLite triggers prevent UPDATE and DELETE on journal tables."""
    journal = SimulationExecutionJournal()
    sec = uuid7()
    order_id = uuid7()
    order = build_simulated_order(
        order_id=order_id,
        session_key=KEY,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    journal.record_order(order)

    # Attempt UPDATE on simulated_orders
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE simulated_orders SET quantity = 999 WHERE order_id = ?",
                (str(order_id),),
            )

    # Attempt DELETE on simulated_orders
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM simulated_orders WHERE order_id = ?",
                (str(order_id),),
            )


def test_replay_session_fills_projection() -> None:
    """Verifies replay_session_fills projects records to M2 PortfolioFillV1."""
    journal = SimulationExecutionJournal()
    sec1 = uuid7()
    sec2 = uuid7()

    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY,
        security_id=sec1,
        side="buy",
        quantity=100,
        created_at=NOW,
    )
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY,
        security_id=sec2,
        side="sell",
        quantity=50,
        created_at=NOW,
    )
    journal.record_order(ord1)
    journal.record_order(ord2)

    fill1 = build_simulated_fill(
        fill_id=uuid7(),
        order_id=ord1.order_id,
        security_id=sec1,
        side="buy",
        quantity=100,
        fill_price=Decimal("150.00"),
        transaction_costs=Decimal("1.50"),
        filled_at=NOW,
    )
    fill2 = build_simulated_fill(
        fill_id=uuid7(),
        order_id=ord2.order_id,
        security_id=sec2,
        side="sell",
        quantity=50,
        fill_price=Decimal("75.25"),
        transaction_costs=Decimal("0.75"),
        filled_at=NOW,
    )
    journal.record_fill(fill1)
    journal.record_fill(fill2)

    # Replay
    portfolio_fills = journal.replay_session_fills(KEY)
    assert len(portfolio_fills) == 2
    assert isinstance(portfolio_fills[0], PortfolioFillV1)
    assert portfolio_fills[0].security_id == sec1
    assert portfolio_fills[0].side == "buy"
    assert portfolio_fills[0].quantity == 100
    assert portfolio_fills[0].fill_price == Decimal("150")
    assert portfolio_fills[0].transaction_costs == Decimal("1.5")

    assert isinstance(portfolio_fills[1], PortfolioFillV1)
    assert portfolio_fills[1].security_id == sec2
    assert portfolio_fills[1].side == "sell"
    assert portfolio_fills[1].quantity == 50
    assert portfolio_fills[1].fill_price == Decimal("75.25")
    assert portfolio_fills[1].transaction_costs == Decimal("0.75")
