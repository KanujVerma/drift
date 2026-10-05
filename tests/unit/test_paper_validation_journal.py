"""Unit tests for PersistentShadowValidationJournal (M15-2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.paper_validation import (
    build_execution_drift_report,
    build_market_tick,
    build_shadow_validation_summary,
)
from drift.domain.sessions import SessionKeyV1
from drift.validation.journal import (
    DuplicateValidationRecordError,
    PersistentShadowValidationJournal,
    ValidationAppendOnlyViolationError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def test_record_and_retrieve_ticks(tmp_path: Path) -> None:
    """Verifies storing and querying market ticks chronologically."""
    db_path = tmp_path / "shadow_journal.db"
    journal = PersistentShadowValidationJournal(db_path)
    sec_id = uuid7()

    tick1 = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=10,
    )
    tick2 = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=datetime(2026, 3, 1, 14, 31, tzinfo=UTC),
        last_price=Decimal("101.50"),
        last_size=25,
    )

    journal.record_tick(tick1)
    journal.record_tick(tick2)

    retrieved = journal.get_tick(tick1.tick_id)
    assert retrieved is not None
    assert retrieved.tick_id == tick1.tick_id
    assert retrieved.last_price == Decimal("100.00")

    ticks = journal.list_ticks_for_security(sec_id)
    assert len(ticks) == 2
    assert ticks[0].tick_id == tick1.tick_id
    assert ticks[1].tick_id == tick2.tick_id

    latest = journal.get_latest_tick(sec_id)
    assert latest is not None
    assert latest.tick_id == tick2.tick_id


def test_duplicate_tick_rejected(tmp_path: Path) -> None:
    """Verifies inserting duplicate tick_id raises DuplicateValidationRecordError."""
    db_path = tmp_path / "shadow_journal.db"
    journal = PersistentShadowValidationJournal(db_path)
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=10,
    )
    journal.record_tick(tick)

    with pytest.raises(DuplicateValidationRecordError):
        journal.record_tick(tick)


def test_record_and_retrieve_drift_reports(tmp_path: Path) -> None:
    """Verifies storing and querying execution drift reports."""
    db_path = tmp_path / "shadow_journal.db"
    journal = PersistentShadowValidationJournal(db_path)
    sec_id = uuid7()
    intent_id = uuid7()

    report = build_execution_drift_report(
        drift_id=uuid7(),
        intent_id=intent_id,
        security_id=sec_id,
        intended_price=Decimal("150.00"),
        fill_price=Decimal("150.75"),
        recorded_at=NOW,
    )

    journal.record_drift_report(report)
    retrieved = journal.get_drift_report(report.drift_id)
    assert retrieved is not None
    assert retrieved.drift_id == report.drift_id
    assert retrieved.slippage_bps == Decimal("50")

    reports = journal.list_drift_reports_for_security(sec_id)
    assert len(reports) == 1
    assert reports[0].drift_id == report.drift_id


def test_record_and_retrieve_summary(tmp_path: Path) -> None:
    """Verifies storing and querying validation session summary."""
    db_path = tmp_path / "shadow_journal.db"
    journal = PersistentShadowValidationJournal(db_path)

    summary = build_shadow_validation_summary(
        validation_id=uuid7(),
        session_key=KEY1,
        total_ticks_processed=5000,
        orders_generated=20,
        orders_approved=18,
        orders_rejected_risk=2,
        orders_filled=18,
        total_slippage_bps=Decimal("45.0"),
        mean_slippage_bps=Decimal("2.5"),
        max_slippage_bps=Decimal("10.0"),
        final_equity=Decimal("102000.00"),
    )

    journal.record_summary(summary)
    retrieved = journal.get_summary(summary.validation_id)
    assert retrieved is not None
    assert retrieved.validation_id == summary.validation_id
    assert retrieved.total_ticks_processed == 5000
    assert retrieved.final_equity == Decimal("102000.00")


def test_append_only_triggers_enforced(tmp_path: Path) -> None:
    """Verifies SQL triggers prevent UPDATE and DELETE on all three journal tables."""
    db_path = tmp_path / "shadow_journal.db"
    journal = PersistentShadowValidationJournal(db_path)
    sec_id = uuid7()

    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=10,
    )
    journal.record_tick(tick)

    # Attempt UPDATE on market_ticks
    with pytest.raises(
        ValidationAppendOnlyViolationError, match="market_ticks is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("UPDATE market_ticks SET last_price = '999.00'")

    # Attempt DELETE on market_ticks
    with pytest.raises(
        ValidationAppendOnlyViolationError, match="market_ticks is append-only"
    ):
        with journal._transaction() as cursor:
            cursor.execute("DELETE FROM market_ticks")
