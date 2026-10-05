"""Unit tests for Shadow Broker domain models, schemas, and payloads (M12-1)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.evaluator_portfolio import PortfolioFillV1
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    EligibilityStatus,
    MarketExecutionEligibilityV1,
    SimulatedFillV1,
    build_market_execution_eligibility,
    build_simulated_fill,
    build_simulated_order,
)

NOW = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
KEY = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def test_market_execution_eligibility_validation() -> None:
    """Verifies eligibility model variants, reasons, and hash validation."""
    sec = uuid7()

    # 1. Eligible
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    assert el.status == EligibilityStatus.ELIGIBLE
    assert el.evidence_hash == "1" * 64

    # 2. Ineligible
    inel = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY,
        status=EligibilityStatus.INELIGIBLE,
        reason="trading_halted",
        evidence_hash="2" * 64,
    )
    assert inel.status == EligibilityStatus.INELIGIBLE
    assert inel.reason == "trading_halted"

    # 3. Indeterminate
    indet = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY,
        status=EligibilityStatus.INDETERMINATE,
        reason="vendor_feed_gap",
    )
    assert indet.status == EligibilityStatus.INDETERMINATE
    assert indet.evidence_hash is None

    # Indeterminate cannot carry evidence hash
    with pytest.raises(ValidationError, match="indeterminate eligibility cannot name"):
        build_market_execution_eligibility(
            security_id=sec,
            session_key=KEY,
            status=EligibilityStatus.INDETERMINATE,
            reason="feed_gap",
            evidence_hash="3" * 64,
        )

    # Tampered hash
    tampered = el.model_dump(mode="python")
    tampered["eligibility_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="eligibility hash mismatch"):
        MarketExecutionEligibilityV1.model_validate(tampered)


def test_simulated_order_validation() -> None:
    """Verifies market/limit orders, positive quantities, and tamper detection."""
    sec = uuid7()
    order_id = uuid7()

    # Market order
    mkt = build_simulated_order(
        order_id=order_id,
        session_key=KEY,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW,
    )
    assert mkt.order_type == "market"
    assert mkt.quantity == 50
    assert mkt.limit_price is None

    # Market order cannot carry limit price
    with pytest.raises(ValidationError, match="market order cannot carry limit price"):
        build_simulated_order(
            order_id=order_id,
            session_key=KEY,
            security_id=sec,
            side="buy",
            quantity=50,
            created_at=NOW,
            order_type="market",
            limit_price=Decimal("150.00"),
        )

    # Limit order
    lim = build_simulated_order(
        order_id=order_id,
        session_key=KEY,
        security_id=sec,
        side="sell",
        quantity=25,
        created_at=NOW,
        order_type="limit",
        limit_price=Decimal("155.50"),
    )
    assert lim.order_type == "limit"
    assert lim.limit_price == Decimal("155.50")

    # Limit order requires positive price
    with pytest.raises(ValidationError, match="limit order requires positive"):
        build_simulated_order(
            order_id=order_id,
            session_key=KEY,
            security_id=sec,
            side="buy",
            quantity=10,
            created_at=NOW,
            order_type="limit",
            limit_price=None,
        )


def test_simulated_fill_and_projection_to_m2_portfolio_fill() -> None:
    """Verifies simulated fill validation and projection to M2 PortfolioFillV1."""
    sec = uuid7()
    fill_id = uuid7()
    order_id = uuid7()

    fill = build_simulated_fill(
        fill_id=fill_id,
        order_id=order_id,
        security_id=sec,
        side="buy",
        quantity=100,
        fill_price=Decimal("142.75"),
        transaction_costs=Decimal("1.25"),
        filled_at=NOW,
    )

    assert fill.quantity == 100
    assert fill.fill_price == Decimal("142.75")
    assert fill.transaction_costs == Decimal("1.25")

    # Project to M2 PortfolioFillV1
    portfolio_fill = fill.to_portfolio_fill()
    assert isinstance(portfolio_fill, PortfolioFillV1)
    assert portfolio_fill.security_id == sec
    assert portfolio_fill.side == "buy"
    assert portfolio_fill.quantity == 100
    assert portfolio_fill.fill_price == Decimal("142.75")
    assert portfolio_fill.transaction_costs == Decimal("1.25")

    # Tampering with fill price
    tampered = fill.model_dump(mode="python")
    tampered["fill_price"] = Decimal("999.99")
    with pytest.raises(ValidationError, match="simulated fill hash mismatch"):
        SimulatedFillV1.model_validate(tampered)
