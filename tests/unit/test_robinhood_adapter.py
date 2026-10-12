"""Unit tests for official Robinhood Agentic MCP Broker Adapter (M16-2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import BrokerAdapterProtocol


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_robinhood_adapter_protocol_conformance() -> None:
    """RobinhoodAgenticAdapter satisfies BrokerAdapterProtocol."""
    config = RobinhoodAgenticConfigV1(account_id="acc-01")
    transport = MockRobinhoodMcpTransport()
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    assert isinstance(adapter, BrokerAdapterProtocol)
    assert adapter.config == config
    assert adapter.transport == transport


def test_submit_intent_filled() -> None:
    """Submitting valid order intent produces filled execution report."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={sec_id: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("10000.00"),
        price_map={"AAPL": Decimal("150.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.intent_id == intent.intent_id
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 10
    assert report.leaves_quantity == 0
    assert report.broker_order_id is not None
    assert Decimal(str(report.avg_fill_price)) == Decimal("150.00")

    # Account reflects fill
    acct = adapter.get_account_snapshot()
    assert Decimal(str(acct.cash_balance)) == Decimal("8500.00")

    # Positions reflect fill
    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].security_id == sec_id
    assert positions[0].quantity == 10


def test_submit_intent_unmapped_security_rejected() -> None:
    """Submitting intent for unmapped security returns rejected execution report."""
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={})
    transport = MockRobinhoodMcpTransport()
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-002",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.cum_quantity == 0
    assert report.leaves_quantity == 5
    assert report.rejection_reason is not None
    assert "unmapped security_id" in report.rejection_reason


def test_submit_intent_insufficient_cash_rejected() -> None:
    """Submitting order exceeding buying power produces rejected report."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={sec_id: "GOOGL"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("500.00"),
        price_map={"GOOGL": Decimal("200.00")},
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-003",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("200.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert report.cum_quantity == 0
    assert report.leaves_quantity == 10
    assert report.rejection_reason == "insufficient_buying_power"


def test_submit_intent_queued_and_status_query() -> None:
    """Non-autofill order starts as acknowledged and updates on query."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={sec_id: "MSFT"},
    )
    transport = MockRobinhoodMcpTransport(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-004",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)
    assert report.status == ExecutionStatus.ACKNOWLEDGED
    assert report.cum_quantity == 0
    assert report.leaves_quantity == 5

    queried = adapter.get_intent_status(intent.intent_id)
    assert queried is not None
    assert queried.status == ExecutionStatus.ACKNOWLEDGED


def test_cancel_intent_flow() -> None:
    """Canceling an active order returns canceled status."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={sec_id: "NVDA"},
    )
    transport = MockRobinhoodMcpTransport(auto_fill=False)
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-005",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    adapter.submit_intent(intent)
    cancel_report = adapter.cancel_intent(intent.intent_id)
    assert cancel_report.status == ExecutionStatus.CANCELED


def test_cancel_already_filled_returns_filled() -> None:
    """Attempting to cancel an already-filled order returns existing filled report."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={sec_id: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("10000.00"),
        price_map={"AAPL": Decimal("100.00")},
        auto_fill=True,
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cli-006",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    filled = adapter.submit_intent(intent)
    assert filled.status == ExecutionStatus.FILLED

    res = adapter.cancel_intent(intent.intent_id)
    assert res.status == ExecutionStatus.FILLED


def test_get_intent_status_unknown_returns_none() -> None:
    """Querying status of an unknown intent returns None."""
    config = RobinhoodAgenticConfigV1(account_id="acc-01")
    transport = MockRobinhoodMcpTransport()
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)
    assert adapter.get_intent_status(uuid7()) is None
