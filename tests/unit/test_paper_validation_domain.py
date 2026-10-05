"""Unit tests for paper validation domain models and schemas (M15-1)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.paper_validation import (
    ExecutionDriftReportV1,
    MarketTickV1,
    ShadowValidationSummaryV1,
    build_execution_drift_report,
    build_market_tick,
    build_shadow_validation_summary,
)
from drift.domain.sessions import SessionKeyV1

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def test_market_tick_valid_construction() -> None:
    """Verifies construction and properties of valid MarketTickV1."""
    sec_id = uuid7()
    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("150.25"),
        last_size=100,
        bid_price=Decimal("150.20"),
        bid_size=500,
        ask_price=Decimal("150.30"),
        ask_size=300,
    )

    assert tick.last_price == Decimal("150.25")
    assert tick.bid_price == Decimal("150.20")
    assert tick.ask_price == Decimal("150.30")
    assert tick.last_size == 100
    assert tick.bid_size == 500
    assert tick.ask_size == 300
    assert len(tick.tick_hash) == 64


def test_market_tick_crossed_market_rejected() -> None:
    """Verifies crossed market (bid > ask) is refused."""
    sec_id = uuid7()
    with pytest.raises(ValidationError, match="crossed market condition"):
        build_market_tick(
            tick_id=uuid7(),
            security_id=sec_id,
            timestamp=NOW,
            last_price=Decimal("150.00"),
            last_size=10,
            bid_price=Decimal("151.00"),
            ask_price=Decimal("150.00"),
        )


def test_market_tick_tampering_detected() -> None:
    """Verifies modifying payload without recalculating tick_hash fails."""
    sec_id = uuid7()
    tick = build_market_tick(
        tick_id=uuid7(),
        security_id=sec_id,
        timestamp=NOW,
        last_price=Decimal("100.00"),
        last_size=50,
    )

    tampered = tick.model_dump(mode="python")
    tampered["last_price"] = Decimal("105.00")
    with pytest.raises(ValidationError, match="tick_hash mismatch"):
        MarketTickV1.model_validate(tampered)


def test_execution_drift_report_slippage_calculation() -> None:
    """Verifies drift report calculates slippage in basis points."""
    sec_id = uuid7()
    intent_id = uuid7()

    # Adverse slippage on BUY: intended $100.00, filled $100.50 -> +50 bps
    drift_adverse = build_execution_drift_report(
        drift_id=uuid7(),
        intent_id=intent_id,
        security_id=sec_id,
        intended_price=Decimal("100.00"),
        fill_price=Decimal("100.50"),
        recorded_at=NOW,
    )
    assert drift_adverse.slippage_bps == Decimal("50")

    # Favorable price improvement: intended $100.00, filled $99.80 -> -20 bps
    drift_favorable = build_execution_drift_report(
        drift_id=uuid7(),
        intent_id=intent_id,
        security_id=sec_id,
        intended_price=Decimal("100.00"),
        fill_price=Decimal("99.80"),
        recorded_at=NOW,
    )
    assert drift_favorable.slippage_bps == Decimal("-20")

    # Tampering test
    tampered = drift_adverse.model_dump(mode="python")
    tampered["slippage_bps"] = Decimal("0")
    with pytest.raises(ValidationError, match="drift_hash mismatch"):
        ExecutionDriftReportV1.model_validate(tampered)


def test_shadow_validation_summary_invariants() -> None:
    """Verifies summary invariants and tamper detection."""
    summary = build_shadow_validation_summary(
        validation_id=uuid7(),
        session_key=KEY1,
        total_ticks_processed=10000,
        orders_generated=50,
        orders_approved=45,
        orders_rejected_risk=5,
        orders_filled=40,
        total_slippage_bps=Decimal("120.5"),
        mean_slippage_bps=Decimal("3.01"),
        max_slippage_bps=Decimal("15.2"),
        final_equity=Decimal("105230.50"),
    )

    assert summary.total_ticks_processed == 10000
    assert summary.orders_filled == 40
    assert summary.final_equity == Decimal("105230.50")

    # Invariant: approved + rejected cannot exceed generated
    with pytest.raises(
        ValidationError,
        match="sum of approved and rejected orders cannot exceed generated orders",
    ):
        build_shadow_validation_summary(
            validation_id=uuid7(),
            session_key=KEY1,
            total_ticks_processed=100,
            orders_generated=10,
            orders_approved=8,
            orders_rejected_risk=5,  # 8 + 5 = 13 > 10
            orders_filled=5,
            total_slippage_bps=Decimal("0"),
            mean_slippage_bps=Decimal("0"),
            max_slippage_bps=Decimal("0"),
            final_equity=Decimal("100000"),
        )

    # Invariant: filled cannot exceed approved
    with pytest.raises(
        ValidationError, match="filled orders cannot exceed approved orders"
    ):
        build_shadow_validation_summary(
            validation_id=uuid7(),
            session_key=KEY1,
            total_ticks_processed=100,
            orders_generated=10,
            orders_approved=5,
            orders_rejected_risk=2,
            orders_filled=6,  # 6 > 5
            total_slippage_bps=Decimal("0"),
            mean_slippage_bps=Decimal("0"),
            max_slippage_bps=Decimal("0"),
            final_equity=Decimal("100000"),
        )

    # Tampering test
    tampered = summary.model_dump(mode="python")
    tampered["total_ticks_processed"] = 99999
    with pytest.raises(ValidationError, match="summary_hash mismatch"):
        ShadowValidationSummaryV1.model_validate(tampered)
