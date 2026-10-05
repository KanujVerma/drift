"""Robinhood Agentic MCP transport protocol and deterministic mock transport (M16-1).

Specifies the RobinhoodMcpTransportProtocol interface and provides a reference
MockRobinhoodMcpTransport for offline testing and paper simulation per ADR 0011.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.errors import DriftError

__all__ = [
    "MockRobinhoodMcpTransport",
    "RobinhoodMcpError",
    "RobinhoodMcpTransportProtocol",
]


class RobinhoodMcpError(DriftError):
    """Base exception for Robinhood MCP transport errors."""


@runtime_checkable
class RobinhoodMcpTransportProtocol(Protocol):
    """Protocol for communicating with official Robinhood Agentic MCP service."""

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool with JSON-serializable arguments."""
        ...


class MockRobinhoodMcpTransport:
    """Deterministic in-memory mock simulating Robinhood Agentic MCP tools."""

    def __init__(
        self,
        *,
        account_id: str = "rh-agent-001",
        initial_cash: Decimal = Decimal("100000.00"),
        price_map: Mapping[str, Decimal] | None = None,
        auto_fill: bool = True,
    ) -> None:
        self._account_id = account_id
        self._cash = canonical_money(initial_cash)
        self._price_map: dict[str, Decimal] = (
            dict(price_map) if price_map is not None else {}
        )
        self._auto_fill = auto_fill
        self._orders: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, dict[str, Any]] = {}
        self._call_history: list[tuple[str, dict[str, Any]]] = []

    def set_market_price(self, symbol: str, price: Decimal) -> None:
        """Configure mock market price for a symbol."""
        self._price_map[symbol] = canonical_money(price)

    @property
    def call_history(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        """History of all tool calls invoked on this transport."""
        return tuple(self._call_history)

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Dispatch tool call to simulated handler."""
        args = dict(arguments)
        self._call_history.append((tool_name, args))

        if tool_name == "robinhood_place_order":
            return self._handle_place_order(args)
        if tool_name == "robinhood_cancel_order":
            return self._handle_cancel_order(args)
        if tool_name == "robinhood_get_order":
            return self._handle_get_order(args)
        if tool_name == "robinhood_get_account":
            return self._handle_get_account()
        if tool_name == "robinhood_get_positions":
            return self._handle_get_positions()

        raise RobinhoodMcpError(f"unknown Robinhood MCP tool: {tool_name}")

    def _handle_place_order(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = str(args["symbol"])
        side = str(args["side"]).lower()
        quantity = int(args["quantity"])
        client_token = str(args.get("client_token", ""))

        order_id = f"rh-ord-{len(self._orders) + 1:04d}"
        price = (
            Decimal(str(args["limit_price"]))
            if "limit_price" in args and args["limit_price"] is not None
            else self._price_map.get(symbol, Decimal("100.00"))
        )

        now = datetime.now(UTC).isoformat()
        with decimal_context():
            notional = canonical_money(Decimal(quantity) * price)

        if not self._auto_fill:
            record: dict[str, Any] = {
                "order_id": order_id,
                "client_token": client_token,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": "queued",
                "cum_quantity": 0,
                "avg_fill_price": None,
                "created_at": now,
            }
            self._orders[order_id] = record
            return record

        # Process fill
        if side == "buy":
            if notional > self._cash:
                record = {
                    "order_id": order_id,
                    "client_token": client_token,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "status": "rejected",
                    "rejection_reason": "insufficient_buying_power",
                    "cum_quantity": 0,
                    "avg_fill_price": None,
                    "created_at": now,
                }
                self._orders[order_id] = record
                return record

            self._cash = canonical_money(self._cash - notional)
            pos = self._positions.setdefault(
                symbol, {"quantity": 0, "cost_basis": Decimal("0")}
            )
            pos["quantity"] = int(pos["quantity"]) + quantity
            pos["cost_basis"] = canonical_money(
                Decimal(str(pos["cost_basis"])) + notional
            )

        elif side == "sell":
            existing_pos = self._positions.get(symbol)
            held = int(existing_pos["quantity"]) if existing_pos else 0
            if quantity > held:
                record = {
                    "order_id": order_id,
                    "client_token": client_token,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "status": "rejected",
                    "rejection_reason": "insufficient_shares",
                    "cum_quantity": 0,
                    "avg_fill_price": None,
                    "created_at": now,
                }
                self._orders[order_id] = record
                return record

            self._cash = canonical_money(self._cash + notional)
            new_qty = held - quantity
            if held > 0 and existing_pos:
                ratio = Decimal(new_qty) / Decimal(held)
                new_basis = canonical_money(
                    Decimal(str(existing_pos["cost_basis"])) * ratio
                )
            else:
                new_basis = Decimal("0")

            if existing_pos:
                existing_pos["quantity"] = new_qty
                existing_pos["cost_basis"] = new_basis

        record = {
            "order_id": order_id,
            "client_token": client_token,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "status": "filled",
            "cum_quantity": quantity,
            "avg_fill_price": str(price),
            "created_at": now,
        }
        self._orders[order_id] = record
        return record

    def _handle_cancel_order(self, args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["order_id"])
        record = self._orders.get(order_id)
        if record is None:
            raise RobinhoodMcpError(f"order {order_id} not found")

        if record["status"] == "filled":
            return record

        record["status"] = "canceled"
        return record

    def _handle_get_order(self, args: dict[str, Any]) -> dict[str, Any]:
        order_id = str(args["order_id"])
        record = self._orders.get(order_id)
        if record is None:
            raise RobinhoodMcpError(f"order {order_id} not found")
        return dict(record)

    def _handle_get_account(self) -> dict[str, Any]:
        with decimal_context():
            holdings_value = Decimal("0")
            for sym, pos in self._positions.items():
                qty = int(pos["quantity"])
                if qty > 0:
                    px = self._price_map.get(sym, Decimal("100.00"))
                    holdings_value += Decimal(qty) * px
            equity = canonical_money(self._cash + holdings_value)

        return {
            "account_id": self._account_id,
            "cash": str(self._cash),
            "buying_power": str(self._cash),
            "portfolio_equity": str(equity),
        }

    def _handle_get_positions(self) -> dict[str, Any]:
        positions_list: list[dict[str, Any]] = []
        for sym, pos in sorted(self._positions.items()):
            qty = int(pos["quantity"])
            if qty > 0:
                px = self._price_map.get(sym, Decimal("100.00"))
                positions_list.append(
                    {
                        "symbol": sym,
                        "quantity": qty,
                        "cost_basis": str(pos["cost_basis"]),
                        "current_price": str(px),
                    }
                )
        return {"positions": positions_list}
