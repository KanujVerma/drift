"""Official Robinhood Agentic MCP broker adapter (M16-2).

Implements BrokerAdapterProtocol by translating Drift order intents to
official Robinhood Agentic MCP tool calls per ADR 0011 and ADR 0013.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5, uuid7

from drift.adapters.robinhood.config import RobinhoodAgenticConfigV1
from drift.adapters.robinhood.transport import (
    RobinhoodMcpError,
    RobinhoodMcpTransportProtocol,
)
from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.execution import (
    BrokerAccountSnapshotV1,
    BrokerPositionSnapshotV1,
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    build_broker_account_snapshot,
    build_broker_position_snapshot,
    build_execution_report,
)

__all__ = [
    "RobinhoodAgenticAdapter",
]


class RobinhoodAgenticAdapter:
    """Broker adapter translating Drift intents to Robinhood Agentic MCP tools."""

    def __init__(
        self,
        *,
        config: RobinhoodAgenticConfigV1,
        transport: RobinhoodMcpTransportProtocol,
    ) -> None:
        self._config = config
        self._transport = transport
        self._reverse_symbol_map: dict[str, UUID] = {
            sym: sec_id for sec_id, sym in config.symbol_map.items()
        }
        self._intent_to_broker_order: dict[UUID, str] = {}
        self._broker_order_to_intent: dict[str, UUID] = {}
        self._latest_reports: dict[UUID, ExecutionReportV1] = {}
        self._intents: dict[UUID, OrderIntentV1] = {}

    @property
    def config(self) -> RobinhoodAgenticConfigV1:
        """Adapter configuration."""
        return self._config

    @property
    def transport(self) -> RobinhoodMcpTransportProtocol:
        """Underlying MCP transport."""
        return self._transport

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        """Submit an order intent to Robinhood Agentic MCP tools."""
        self._intents[intent.intent_id] = intent
        now = datetime.now(UTC)

        symbol = self._config.symbol_map.get(intent.security_id)
        if symbol is None:
            report = build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason=f"unmapped security_id: {intent.security_id}",
                reported_at=now,
            )
            self._latest_reports[intent.intent_id] = report
            return report

        args: dict[str, Any] = {
            "symbol": symbol,
            "side": intent.side.value,
            "quantity": intent.quantity,
            "order_type": intent.order_type.value,
            "client_token": str(intent.intent_id),
        }
        if intent.limit_price is not None:
            args["limit_price"] = str(intent.limit_price)

        try:
            raw = self._transport.call_tool("robinhood_place_order", args)
        except RobinhoodMcpError as exc:
            report = build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason=f"mcp_error: {exc}",
                reported_at=now,
            )
            self._latest_reports[intent.intent_id] = report
            return report

        broker_order_id = str(raw["order_id"]) if "order_id" in raw else None
        if broker_order_id is not None:
            self._intent_to_broker_order[intent.intent_id] = broker_order_id
            self._broker_order_to_intent[broker_order_id] = intent.intent_id

        raw_status = str(raw.get("status", "")).lower()
        status = self._map_order_status(raw_status)

        cum_qty = int(raw.get("cum_quantity", 0))
        leaves_qty = max(0, intent.quantity - cum_qty)
        avg_price = (
            Decimal(str(raw["avg_fill_price"]))
            if raw.get("avg_fill_price") is not None
            else None
        )
        rejection_reason = raw.get("rejection_reason")
        if status == ExecutionStatus.REJECTED and not rejection_reason:
            rejection_reason = "rejected by robinhood mcp"

        report = build_execution_report(
            report_id=uuid7(),
            intent_id=intent.intent_id,
            broker_order_id=broker_order_id,
            status=status,
            cum_quantity=cum_qty,
            leaves_quantity=leaves_qty,
            last_fill_price=avg_price,
            last_fill_quantity=cum_qty if cum_qty > 0 else None,
            avg_fill_price=avg_price,
            fee_amount=Decimal("0"),
            rejection_reason=str(rejection_reason) if rejection_reason else None,
            reported_at=now,
        )
        self._latest_reports[intent.intent_id] = report
        return report

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        """Cancel an open order intent via Robinhood Agentic MCP tools."""
        now = datetime.now(UTC)
        existing = self._latest_reports.get(intent_id)
        if existing is not None and existing.status == ExecutionStatus.FILLED:
            return existing

        broker_order_id = self._intent_to_broker_order.get(intent_id)
        if broker_order_id is not None:
            try:
                self._transport.call_tool(
                    "robinhood_cancel_order",
                    {"order_id": broker_order_id},
                )
            except RobinhoodMcpError:
                pass

        cum = existing.cum_quantity if existing is not None else 0
        report = build_execution_report(
            report_id=uuid7(),
            intent_id=intent_id,
            broker_order_id=broker_order_id,
            status=ExecutionStatus.CANCELED,
            cum_quantity=cum,
            leaves_quantity=0,
            rejection_reason=None,
            reported_at=now,
        )
        self._latest_reports[intent_id] = report
        return report

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        """Query latest execution report for an order intent."""
        broker_order_id = self._intent_to_broker_order.get(intent_id)
        if broker_order_id is not None:
            try:
                raw = self._transport.call_tool(
                    "robinhood_get_order",
                    {"order_id": broker_order_id},
                )
                now = datetime.now(UTC)
                raw_status = str(raw.get("status", "")).lower()
                status = self._map_order_status(raw_status)
                cum_qty = int(raw.get("cum_quantity", 0))
                intent = self._intents.get(intent_id)
                total_qty = intent.quantity if intent is not None else cum_qty
                leaves_qty = max(0, total_qty - cum_qty)
                avg_price = (
                    Decimal(str(raw["avg_fill_price"]))
                    if raw.get("avg_fill_price") is not None
                    else None
                )
                rejection_reason = raw.get("rejection_reason")
                if status == ExecutionStatus.REJECTED and not rejection_reason:
                    rejection_reason = "rejected by robinhood mcp"

                report = build_execution_report(
                    report_id=uuid7(),
                    intent_id=intent_id,
                    broker_order_id=broker_order_id,
                    status=status,
                    cum_quantity=cum_qty,
                    leaves_quantity=leaves_qty,
                    last_fill_price=avg_price,
                    last_fill_quantity=cum_qty if cum_qty > 0 else None,
                    avg_fill_price=avg_price,
                    fee_amount=Decimal("0"),
                    rejection_reason=(
                        str(rejection_reason) if rejection_reason else None
                    ),
                    reported_at=now,
                )
                self._latest_reports[intent_id] = report
                return report
            except RobinhoodMcpError:
                pass

        return self._latest_reports.get(intent_id)

    def get_account_snapshot(self) -> BrokerAccountSnapshotV1:
        """Query account balances and compute canonical account snapshot."""
        now = datetime.now(UTC)
        raw = self._transport.call_tool("robinhood_get_account", {})
        cash = Decimal(str(raw.get("cash", "0")))
        buying_power = Decimal(str(raw.get("buying_power", "0")))
        equity = Decimal(str(raw.get("portfolio_equity", "0")))

        return build_broker_account_snapshot(
            snapshot_id=uuid7(),
            account_id=str(raw.get("account_id", self._config.account_id)),
            cash_balance=cash,
            buying_power=buying_power,
            portfolio_equity=equity,
            as_of=now,
        )

    def get_positions(self) -> tuple[BrokerPositionSnapshotV1, ...]:
        """Query current positions and compute canonical position snapshots."""
        now = datetime.now(UTC)
        raw = self._transport.call_tool("robinhood_get_positions", {})
        raw_positions = raw.get("positions", [])

        snapshots: list[BrokerPositionSnapshotV1] = []
        for pos in raw_positions:
            sym = str(pos["symbol"])
            qty = int(pos["quantity"])
            if qty <= 0:
                continue

            sec_id = self._reverse_symbol_map.get(sym)
            if sec_id is None:
                sec_id = uuid5(NAMESPACE_DNS, f"drift.equity.{sym}")

            cost_basis = Decimal(str(pos.get("cost_basis", "0")))
            curr_price = (
                Decimal(str(pos["current_price"]))
                if pos.get("current_price") is not None
                else None
            )
            with decimal_context():
                market_val = (
                    canonical_money(Decimal(qty) * curr_price)
                    if curr_price is not None
                    else None
                )

            snapshots.append(
                build_broker_position_snapshot(
                    snapshot_id=uuid7(),
                    security_id=sec_id,
                    quantity=qty,
                    cost_basis=canonical_money(cost_basis),
                    current_price=curr_price,
                    market_value=market_val,
                    as_of=now,
                )
            )

        return tuple(snapshots)

    @staticmethod
    def _map_order_status(raw_status: str) -> ExecutionStatus:
        """Map Robinhood order status string to Drift ExecutionStatus."""
        if raw_status == "filled":
            return ExecutionStatus.FILLED
        if raw_status in ("queued", "new", "pending", "accepted"):
            return ExecutionStatus.ACKNOWLEDGED
        if raw_status == "partially_filled":
            return ExecutionStatus.PARTIALLY_FILLED
        if raw_status in ("canceled", "cancelled"):
            return ExecutionStatus.CANCELED
        if raw_status == "rejected":
            return ExecutionStatus.REJECTED
        if raw_status == "expired":
            return ExecutionStatus.EXPIRED
        return ExecutionStatus.REJECTED
