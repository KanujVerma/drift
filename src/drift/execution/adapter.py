"""Broker adapter protocol and deterministic mock adapter (M14-3).

Specifies the vendor-neutral BrokerAdapterProtocol interface and provides an
in-memory reference MockBrokerAdapter for offline testing and paper simulation.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid7

from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.execution import (
    BrokerAccountSnapshotV1,
    BrokerPositionSnapshotV1,
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    build_broker_account_snapshot,
    build_broker_position_snapshot,
    build_execution_report,
)

__all__ = [
    "BrokerAdapterProtocol",
    "MockBrokerAdapter",
]


@runtime_checkable
class BrokerAdapterProtocol(Protocol):
    """Abstract protocol decoupling Drift from vendor-specific brokerage APIs."""

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        """Submit an order intent to the broker adapter."""
        ...

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        """Request cancellation of an active order intent."""
        ...

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        """Query the latest execution report for an order intent."""
        ...

    def get_account_snapshot(self) -> BrokerAccountSnapshotV1:
        """Obtain a point-in-time snapshot of account balances and buying power."""
        ...

    def get_positions(self) -> tuple[BrokerPositionSnapshotV1, ...]:
        """Obtain snapshots of all current positions held at the broker."""
        ...


class MockBrokerAdapter:
    """Deterministic in-memory reference broker adapter for testing and simulation."""

    def __init__(
        self,
        *,
        account_id: str = "mock-broker-001",
        initial_cash: Decimal = Decimal("100000"),
        fill_price_map: Mapping[UUID, Decimal] | None = None,
        auto_fill: bool = True,
        default_fee: Decimal = Decimal("1.00"),
    ) -> None:
        self._account_id = account_id
        self._cash = canonical_money(initial_cash)
        self._fill_price_map: dict[UUID, Decimal] = (
            dict(fill_price_map) if fill_price_map is not None else {}
        )
        self._auto_fill = auto_fill
        self._default_fee = canonical_money(default_fee)
        self._positions: dict[UUID, dict[str, Decimal | int]] = {}
        self._intents: dict[UUID, OrderIntentV1] = {}
        self._latest_reports: dict[UUID, ExecutionReportV1] = {}

    @property
    def account_id(self) -> str:
        """Identifier of the broker account."""
        return self._account_id

    @property
    def cash(self) -> Decimal:
        """Current cash balance."""
        return self._cash

    def set_price(self, security_id: UUID, price: Decimal) -> None:
        """Configure mock market price for a security."""
        self._fill_price_map[security_id] = canonical_money(price)

    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1:
        """Submit order intent and optionally fill or reject immediately."""
        self._intents[intent.intent_id] = intent
        now = datetime.now(UTC)
        broker_order_id = f"mock-ord-{str(intent.intent_id)[:8]}"

        if not self._auto_fill:
            report = build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=broker_order_id,
                status=ExecutionStatus.ACKNOWLEDGED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                reported_at=now,
            )
            self._latest_reports[intent.intent_id] = report
            return report

        # Determine execution price
        if intent.limit_price is not None:
            exec_price = intent.limit_price
        elif intent.security_id in self._fill_price_map:
            exec_price = self._fill_price_map[intent.security_id]
        else:
            exec_price = Decimal("100.00")

        with decimal_context():
            gross_notional = canonical_money(Decimal(intent.quantity) * exec_price)

            if intent.side == OrderSide.BUY:
                total_cost = gross_notional + self._default_fee
                if total_cost > self._cash:
                    report = build_execution_report(
                        report_id=uuid7(),
                        intent_id=intent.intent_id,
                        broker_order_id=broker_order_id,
                        status=ExecutionStatus.REJECTED,
                        cum_quantity=0,
                        leaves_quantity=intent.quantity,
                        rejection_reason="insufficient_buying_power",
                        reported_at=now,
                    )
                    self._latest_reports[intent.intent_id] = report
                    return report

                self._cash = canonical_money(self._cash - total_cost)
                pos = self._positions.setdefault(
                    intent.security_id,
                    {"quantity": 0, "cost_basis": Decimal("0")},
                )
                pos["quantity"] = int(pos["quantity"]) + intent.quantity
                pos["cost_basis"] = canonical_money(
                    Decimal(str(pos["cost_basis"])) + gross_notional
                )

            elif intent.side == OrderSide.SELL:
                held_pos = self._positions.get(intent.security_id)
                current_held = int(held_pos["quantity"]) if held_pos else 0
                if intent.quantity > current_held:
                    report = build_execution_report(
                        report_id=uuid7(),
                        intent_id=intent.intent_id,
                        broker_order_id=broker_order_id,
                        status=ExecutionStatus.REJECTED,
                        cum_quantity=0,
                        leaves_quantity=intent.quantity,
                        rejection_reason="insufficient_held_shares",
                        reported_at=now,
                    )
                    self._latest_reports[intent.intent_id] = report
                    return report

                proceeds = canonical_money(gross_notional - self._default_fee)
                self._cash = canonical_money(self._cash + proceeds)
                new_qty = current_held - intent.quantity
                if current_held > 0 and held_pos:
                    basis_ratio = Decimal(new_qty) / Decimal(current_held)
                    new_basis = canonical_money(
                        Decimal(str(held_pos["cost_basis"])) * basis_ratio
                    )
                else:
                    new_basis = Decimal("0")

                if held_pos:
                    held_pos["quantity"] = new_qty
                    held_pos["cost_basis"] = new_basis

        report = build_execution_report(
            report_id=uuid7(),
            intent_id=intent.intent_id,
            broker_order_id=broker_order_id,
            status=ExecutionStatus.FILLED,
            cum_quantity=intent.quantity,
            leaves_quantity=0,
            last_fill_price=exec_price,
            last_fill_quantity=intent.quantity,
            avg_fill_price=exec_price,
            fee_amount=self._default_fee,
            reported_at=now,
        )
        self._latest_reports[intent.intent_id] = report
        return report

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        """Cancel an open order intent."""
        now = datetime.now(UTC)
        existing = self._latest_reports.get(intent_id)
        if existing is not None and existing.status == ExecutionStatus.FILLED:
            return existing

        cum = existing.cum_quantity if existing is not None else 0
        b_id = existing.broker_order_id if existing is not None else None

        report = build_execution_report(
            report_id=uuid7(),
            intent_id=intent_id,
            broker_order_id=b_id,
            status=ExecutionStatus.CANCELED,
            cum_quantity=cum,
            leaves_quantity=0,
            rejection_reason=None,
            reported_at=now,
        )
        self._latest_reports[intent_id] = report
        return report

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        """Query latest execution report for an intent."""
        return self._latest_reports.get(intent_id)

    def get_account_snapshot(self) -> BrokerAccountSnapshotV1:
        """Compute point-in-time account equity and buying power snapshot."""
        now = datetime.now(UTC)
        with decimal_context():
            total_holdings_val = Decimal("0")
            for sec_id, pos in self._positions.items():
                qty = int(pos["quantity"])
                if qty > 0:
                    px = self._fill_price_map.get(sec_id, Decimal("100.00"))
                    total_holdings_val += Decimal(qty) * px
            equity = canonical_money(self._cash + total_holdings_val)

        return build_broker_account_snapshot(
            snapshot_id=uuid7(),
            account_id=self._account_id,
            cash_balance=self._cash,
            buying_power=self._cash,
            portfolio_equity=equity,
            as_of=now,
        )

    def get_positions(self) -> tuple[BrokerPositionSnapshotV1, ...]:
        """Return snapshots of all non-zero held positions."""
        now = datetime.now(UTC)
        positions_list: list[BrokerPositionSnapshotV1] = []
        for sec_id, pos in sorted(self._positions.items(), key=lambda p: str(p[0])):
            qty = int(pos["quantity"])
            if qty > 0:
                cost_basis = Decimal(str(pos["cost_basis"]))
                px = self._fill_price_map.get(sec_id, Decimal("100.00"))
                with decimal_context():
                    mv = canonical_money(Decimal(qty) * px)
                positions_list.append(
                    build_broker_position_snapshot(
                        snapshot_id=uuid7(),
                        security_id=sec_id,
                        quantity=qty,
                        cost_basis=canonical_money(cost_basis),
                        current_price=px,
                        market_value=mv,
                        as_of=now,
                    )
                )
        return tuple(positions_list)
