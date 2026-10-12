"""Unit tests for Robinhood Agentic MCP config and mock transport (M16-1)."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from drift.adapters.robinhood.config import (
    ROBINHOOD_ADAPTER_SCHEMA_VERSION,
    RobinhoodAgenticConfigV1,
)
from drift.adapters.robinhood.transport import (
    MockRobinhoodMcpTransport,
    RobinhoodMcpError,
    RobinhoodMcpTransportProtocol,
)


def test_robinhood_config_valid_defaults() -> None:
    """Config initializes with valid defaults and schema version."""
    config = RobinhoodAgenticConfigV1(account_id="rh-acc-123")
    assert config.schema_version == ROBINHOOD_ADAPTER_SCHEMA_VERSION
    assert config.account_id == "rh-acc-123"
    assert config.dry_run is True
    assert config.request_timeout_seconds == 10.0
    assert config.max_retries == 3
    assert config.symbol_map == {}


def test_robinhood_config_custom_values() -> None:
    """Config accepts custom valid parameters."""
    sym_id = uuid4()
    config = RobinhoodAgenticConfigV1(
        account_id="custom-acc",
        dry_run=False,
        request_timeout_seconds=5.0,
        max_retries=1,
        symbol_map={sym_id: "AAPL"},
    )
    assert config.account_id == "custom-acc"
    assert config.dry_run is False
    assert config.request_timeout_seconds == 5.0
    assert config.max_retries == 1
    assert config.symbol_map[sym_id] == "AAPL"


def test_robinhood_config_immutability() -> None:
    """Config is frozen and immutable."""
    config = RobinhoodAgenticConfigV1(account_id="rh-acc-123")
    with pytest.raises(ValidationError):
        config.dry_run = False


def test_robinhood_config_validations() -> None:
    """Config rejects blank account_id, invalid timeout, and negative retries."""
    with pytest.raises(ValidationError):
        RobinhoodAgenticConfigV1(account_id="")

    with pytest.raises(ValidationError):
        RobinhoodAgenticConfigV1(account_id="   ")

    with pytest.raises(ValidationError):
        RobinhoodAgenticConfigV1(account_id="acc", request_timeout_seconds=0.0)

    with pytest.raises(ValidationError):
        RobinhoodAgenticConfigV1(account_id="acc", request_timeout_seconds=-1.0)

    with pytest.raises(ValidationError):
        RobinhoodAgenticConfigV1(account_id="acc", max_retries=-1)


def test_mock_transport_protocol_conformance() -> None:
    """MockRobinhoodMcpTransport satisfies RobinhoodMcpTransportProtocol."""
    transport = MockRobinhoodMcpTransport()
    assert isinstance(transport, RobinhoodMcpTransportProtocol)


def test_mock_transport_unknown_tool() -> None:
    """Invoking an unsupported tool raises RobinhoodMcpError."""
    transport = MockRobinhoodMcpTransport()
    with pytest.raises(
        RobinhoodMcpError, match="unknown Robinhood MCP tool: unknown_tool"
    ):
        transport.call_tool("unknown_tool", {})


def test_mock_transport_account_and_positions_initial() -> None:
    """Initial account state has cash, equity, and zero positions."""
    transport = MockRobinhoodMcpTransport(
        account_id="test-acc",
        initial_cash=Decimal("50000.00"),
    )
    acct = transport.call_tool("robinhood_get_account", {})
    assert acct["account_id"] == "test-acc"
    assert Decimal(acct["cash"]) == Decimal("50000.00")
    assert Decimal(acct["buying_power"]) == Decimal("50000.00")
    assert Decimal(acct["portfolio_equity"]) == Decimal("50000.00")

    pos = transport.call_tool("robinhood_get_positions", {})
    assert pos["positions"] == []


def test_mock_transport_buy_order_fill() -> None:
    """Buy order executes, updates cash and positions, and records call history."""
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("10000.00"),
        price_map={"AAPL": Decimal("150.00")},
    )
    result = transport.call_tool(
        "robinhood_place_order",
        {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "client_token": "token-1",
        },
    )
    assert result["status"] == "filled"
    assert result["cum_quantity"] == 10
    assert Decimal(result["avg_fill_price"]) == Decimal("150.00")
    assert result["client_token"] == "token-1"

    # Verify account
    acct = transport.call_tool("robinhood_get_account", {})
    assert Decimal(acct["cash"]) == Decimal("8500.00")
    assert Decimal(acct["portfolio_equity"]) == Decimal("10000.00")

    # Verify positions
    positions = transport.call_tool("robinhood_get_positions", {})["positions"]
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == 10
    assert Decimal(positions[0]["cost_basis"]) == Decimal("1500.00")

    # Verify call history
    assert len(transport.call_history) == 3


def test_mock_transport_buy_insufficient_cash_rejected() -> None:
    """Buy order exceeding cash is rejected."""
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("1000.00"),
        price_map={"AAPL": Decimal("150.00")},
    )
    result = transport.call_tool(
        "robinhood_place_order",
        {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "client_token": "token-fail",
        },
    )
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "insufficient_buying_power"

    acct = transport.call_tool("robinhood_get_account", {})
    assert Decimal(acct["cash"]) == Decimal("1000.00")


def test_mock_transport_sell_order_fill() -> None:
    """Sell order executes, credits cash, and updates held shares."""
    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("10000.00"),
        price_map={"AAPL": Decimal("100.00")},
    )
    # Buy 20 shares at $100 ($2,000)
    transport.call_tool(
        "robinhood_place_order",
        {"symbol": "AAPL", "side": "buy", "quantity": 20},
    )
    # Price moves to $110
    transport.set_market_price("AAPL", Decimal("110.00"))

    # Sell 10 shares at $110 ($1,100 proceeds)
    sell_result = transport.call_tool(
        "robinhood_place_order",
        {"symbol": "AAPL", "side": "sell", "quantity": 10},
    )
    assert sell_result["status"] == "filled"
    assert Decimal(sell_result["avg_fill_price"]) == Decimal("110.00")

    # Cash: 10000 - 2000 + 1100 = 9100.00
    acct = transport.call_tool("robinhood_get_account", {})
    assert Decimal(acct["cash"]) == Decimal("9100.00")

    # Equity: 9100 + 10 * 110 = 10200.00
    assert Decimal(acct["portfolio_equity"]) == Decimal("10200.00")

    positions = transport.call_tool("robinhood_get_positions", {})["positions"]
    assert len(positions) == 1
    assert positions[0]["quantity"] == 10
    assert Decimal(positions[0]["cost_basis"]) == Decimal("1000.00")


def test_mock_transport_sell_insufficient_shares_rejected() -> None:
    """Sell order without position is rejected."""
    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("10000.00"))
    result = transport.call_tool(
        "robinhood_place_order",
        {"symbol": "AAPL", "side": "sell", "quantity": 5},
    )
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "insufficient_shares"


def test_mock_transport_manual_fill_and_cancellation() -> None:
    """Queued order can be inspected and canceled when auto_fill is False."""
    transport = MockRobinhoodMcpTransport(auto_fill=False)
    order = transport.call_tool(
        "robinhood_place_order",
        {"symbol": "MSFT", "side": "buy", "quantity": 5, "client_token": "tok-q"},
    )
    order_id = order["order_id"]
    assert order["status"] == "queued"
    assert order["cum_quantity"] == 0

    fetched = transport.call_tool("robinhood_get_order", {"order_id": order_id})
    assert fetched["status"] == "queued"

    canceled = transport.call_tool("robinhood_cancel_order", {"order_id": order_id})
    assert canceled["status"] == "canceled"

    # Cancel already filled order does not change status
    transport_auto = MockRobinhoodMcpTransport(auto_fill=True)
    filled_order = transport_auto.call_tool(
        "robinhood_place_order",
        {"symbol": "MSFT", "side": "buy", "quantity": 5},
    )
    cancel_attempt = transport_auto.call_tool(
        "robinhood_cancel_order",
        {"order_id": filled_order["order_id"]},
    )
    assert cancel_attempt["status"] == "filled"


def test_mock_transport_order_not_found_errors() -> None:
    """Getting or canceling nonexistent order raises RobinhoodMcpError."""
    transport = MockRobinhoodMcpTransport()
    with pytest.raises(RobinhoodMcpError, match="order non-existent not found"):
        transport.call_tool("robinhood_get_order", {"order_id": "non-existent"})

    with pytest.raises(RobinhoodMcpError, match="order non-existent not found"):
        transport.call_tool("robinhood_cancel_order", {"order_id": "non-existent"})
