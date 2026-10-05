"""Unit tests for BrokerAdapterProtocol and MockBrokerAdapter (M14-3)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import (
    BrokerAdapterProtocol,
    MockBrokerAdapter,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def test_adapter_protocol_structural_subtyping() -> None:
    """Verifies that MockBrokerAdapter satisfies BrokerAdapterProtocol at runtime."""
    adapter = MockBrokerAdapter()
    assert isinstance(adapter, BrokerAdapterProtocol)


def test_mock_adapter_immediate_buy_and_sell_fills() -> None:
    """Verifies immediate execution fills and position tracking on buy and sell."""
    sec = uuid7()
    adapter = MockBrokerAdapter(
        initial_cash=Decimal("50000"),
        default_fee=Decimal("1.50"),
    )
    adapter.set_price(sec, Decimal("100.00"))

    # 1. Buy 100 shares at $100 -> Cost = 10,000 + 1.50 = 10,001.50
    buy_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="buy-01",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=100,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    rep_buy = adapter.submit_intent(buy_intent)
    assert rep_buy.status == ExecutionStatus.FILLED
    assert rep_buy.cum_quantity == 100
    assert rep_buy.last_fill_price == Decimal("100.00")
    assert rep_buy.fee_amount == Decimal("1.50")
    assert adapter.cash == Decimal("39998.50")

    # Verify positions
    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].security_id == sec
    assert positions[0].quantity == 100
    assert positions[0].cost_basis == Decimal("10000.00")

    # Verify account snapshot
    acc = adapter.get_account_snapshot()
    assert acc.cash_balance == Decimal("39998.50")
    assert acc.portfolio_equity == Decimal("49998.50")

    # 2. Sell 40 shares at $120 (price update) -> Proceeds = 4,800 - 1.50 = 4,798.50
    adapter.set_price(sec, Decimal("120.00"))
    sell_intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="sell-01",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.SELL,
        quantity=40,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("120.00"),
        created_at=NOW,
    )
    rep_sell = adapter.submit_intent(sell_intent)
    assert rep_sell.status == ExecutionStatus.FILLED
    assert rep_sell.cum_quantity == 40
    assert adapter.cash == Decimal("44797.00")

    # Remaining position: 60 shares
    pos_after = adapter.get_positions()
    assert len(pos_after) == 1
    assert pos_after[0].quantity == 60
    assert pos_after[0].cost_basis == Decimal("6000.00")


def test_mock_adapter_insufficient_buying_power_rejection() -> None:
    """Verifies that buy orders exceeding available cash balance are rejected."""
    sec = uuid7()
    adapter = MockBrokerAdapter(
        initial_cash=Decimal("1000"),
        default_fee=Decimal("1.00"),
    )
    adapter.set_price(sec, Decimal("100.00"))

    # Attempt to buy 20 shares at $100 = 2,000 > 1,000 cash
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="buy-rej",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=20,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason == "insufficient_buying_power"
    assert adapter.cash == Decimal("1000")
    assert len(adapter.get_positions()) == 0


def test_mock_adapter_insufficient_shares_short_sale_rejection() -> None:
    """Verifies that sell orders for unheld securities are rejected."""
    sec = uuid7()
    adapter = MockBrokerAdapter(initial_cash=Decimal("10000"))

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="sell-rej",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.SELL,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.rejection_reason == "insufficient_held_shares"


def test_mock_adapter_cancellation() -> None:
    """Verifies order cancellation when auto_fill is disabled."""
    sec = uuid7()
    adapter = MockBrokerAdapter(auto_fill=False)

    intent_id = uuid7()
    intent = build_order_intent(
        intent_id=intent_id,
        client_order_id="order-ack-cancel",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    rep_ack = adapter.submit_intent(intent)
    assert rep_ack.status == ExecutionStatus.ACKNOWLEDGED
    assert rep_ack.leaves_quantity == 10

    # Cancel
    rep_cancel = adapter.cancel_intent(intent_id)
    assert rep_cancel.status == ExecutionStatus.CANCELED
    assert rep_cancel.leaves_quantity == 0

    # Query status
    status = adapter.get_intent_status(intent_id)
    assert status == rep_cancel
