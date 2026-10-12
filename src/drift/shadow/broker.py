"""Shadow broker engine and execution simulator (M12-3).

Simulates whole-share, long-only order execution against unadjusted source
prices, enforces market execution eligibility gating, calculates adverse
slippage and transaction costs, reconciles into M2 PortfolioAccountingKernel,
and records execution events into SimulationExecutionJournal.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid7

from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    EligibilityStatus,
    MarketExecutionEligibilityV1,
    SimulatedFillV1,
    SimulatedOrderV1,
    build_simulated_fill,
    build_simulated_rejection,
)
from drift.errors import DriftError
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.shadow.journal import SimulationExecutionJournal

BASIS_POINT_DENOMINATOR = Decimal("10000")
ONE = Decimal("1")

__all__ = [
    "OrderExecutionError",
    "ShadowBroker",
    "ShadowBrokerError",
]


class ShadowBrokerError(DriftError):
    """Base exception for Shadow Broker operations."""


class OrderExecutionError(ShadowBrokerError):
    """Raised on internal execution error during simulation."""


class ShadowBroker:
    """Deterministic simulated broker engine (M12-3).

    Operates under post_close_decision_next_open_execution cadence.
    """

    def __init__(
        self,
        *,
        kernel: PortfolioAccountingKernel,
        journal: SimulationExecutionJournal,
        cost_model: EvaluationCostModelV1,
    ) -> None:
        self._kernel = kernel
        self._journal = journal
        self._cost_model = cost_model
        self._order_queue: list[SimulatedOrderV1] = []

    @property
    def kernel(self) -> PortfolioAccountingKernel:
        """Consuming M2 canonical portfolio accounting kernel."""
        return self._kernel

    @property
    def journal(self) -> SimulationExecutionJournal:
        """Underlying append-only simulation execution journal."""
        return self._journal

    @property
    def cost_model(self) -> EvaluationCostModelV1:
        """Transaction costs and adverse slippage parameters."""
        return self._cost_model

    def submit_order(self, order: SimulatedOrderV1) -> None:
        """Submit and queue order, immediately logging to journal."""
        self._journal.record_order(order)
        self._order_queue.append(order)

    def execute_order(
        self,
        order: SimulatedOrderV1,
        *,
        open_price: Decimal | None,
        eligibility: MarketExecutionEligibilityV1 | None,
        execution_time: datetime,
    ) -> SimulatedFillV1 | None:
        """Execute a single simulated order against unadjusted open price.

        Returns SimulatedFillV1 if filled, or None if rejected.
        Records fills and rejections to journal and feeds fills to kernel.
        """
        # 1. Eligibility Gating
        if eligibility is None:
            self._reject(
                order,
                reason="missing_eligibility: no eligibility record found for security",
                rejected_at=execution_time,
            )
            return None

        if eligibility.status == EligibilityStatus.INELIGIBLE:
            reason = eligibility.reason or "security ineligible for execution"
            self._reject(
                order,
                reason=f"ineligible_security: {reason}",
                rejected_at=execution_time,
            )
            return None

        if eligibility.status == EligibilityStatus.INDETERMINATE:
            reason = eligibility.reason or "tradability indeterminate"
            self._reject(
                order,
                reason=f"indeterminate_eligibility: {reason}",
                rejected_at=execution_time,
            )
            return None

        if eligibility.status != EligibilityStatus.ELIGIBLE:
            self._reject(
                order,
                reason="unauthorized_eligibility_status",
                rejected_at=execution_time,
            )
            return None

        # 2. Long-Only Short Sale Rejection
        if order.side == "sell":
            held_quantity = 0
            for holding in self._kernel.state.holdings:
                if holding.security_id == order.security_id:
                    held_quantity = holding.quantity
                    break
            if order.quantity > held_quantity:
                self._reject(
                    order,
                    reason=(
                        f"short_sale_rejected: requested sell {order.quantity} "
                        f"exceeds held position {held_quantity}"
                    ),
                    rejected_at=execution_time,
                )
                return None

        # 3. Price Validation
        if (
            open_price is None
            or not open_price.is_finite()
            or open_price <= Decimal("0")
        ):
            self._reject(
                order,
                reason="missing_or_invalid_price: unadjusted open must be positive",
                rejected_at=execution_time,
            )
            return None

        # 4. Adverse Slippage Calculation
        with decimal_context():
            slippage = (
                self._cost_model.adverse_slippage_basis_points / BASIS_POINT_DENOMINATOR
            )
            if order.side == "buy":
                raw_fill_price = open_price * (ONE + slippage)
            else:
                raw_fill_price = open_price * (ONE - slippage)
            fill_price = canonical_money(raw_fill_price)

        # 5. Limit Order Feasibility
        if order.order_type == "limit" and order.limit_price is not None:
            if order.side == "buy" and fill_price > order.limit_price:
                self._reject(
                    order,
                    reason=(
                        f"limit_price_exceeded: fill price {fill_price} "
                        f"exceeds limit {order.limit_price}"
                    ),
                    rejected_at=execution_time,
                )
                return None
            if order.side == "sell" and fill_price < order.limit_price:
                self._reject(
                    order,
                    reason=(
                        f"limit_price_not_met: fill price {fill_price} "
                        f"below limit {order.limit_price}"
                    ),
                    rejected_at=execution_time,
                )
                return None

        # 6. Transaction Costs
        with decimal_context():
            raw_costs = (
                Decimal(order.quantity) * self._cost_model.commission_per_share
                + self._cost_model.fixed_fee_per_order
                + (
                    Decimal(order.quantity)
                    * open_price
                    * self._cost_model.notional_fee_basis_points
                    / BASIS_POINT_DENOMINATOR
                )
            )
            transaction_costs = canonical_money(raw_costs)

        # 7. Cash Solvency Validation (Long-Only, No Margin)
        if order.side == "buy":
            with decimal_context():
                required_cash = canonical_money(
                    fill_price * Decimal(order.quantity) + transaction_costs
                )
            if required_cash > self._kernel.state.cash_balance:
                self._reject(
                    order,
                    reason=(
                        f"insufficient_cash: required {required_cash} "
                        f"exceeds available {self._kernel.state.cash_balance}"
                    ),
                    rejected_at=execution_time,
                )
                return None

        # 8. Build, Record, and Apply Fill
        fill = build_simulated_fill(
            fill_id=uuid7(),
            order_id=order.order_id,
            security_id=order.security_id,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            transaction_costs=transaction_costs,
            filled_at=execution_time,
        )

        self._journal.record_fill(fill, session_key=order.session_key)
        self._kernel.apply_fill(fill.to_portfolio_fill())
        return fill

    def execute_session(
        self,
        *,
        session_key: SessionKeyV1,
        open_prices: Mapping[UUID, Decimal],
        eligibilities: Mapping[UUID, MarketExecutionEligibilityV1],
        execution_time: datetime,
    ) -> tuple[SimulatedFillV1, ...]:
        """Execute all queued orders matching session_key in order received."""
        remaining_queue: list[SimulatedOrderV1] = []
        fills: list[SimulatedFillV1] = []

        for order in self._order_queue:
            if order.session_key == session_key:
                fill = self.execute_order(
                    order,
                    open_price=open_prices.get(order.security_id),
                    eligibility=eligibilities.get(order.security_id),
                    execution_time=execution_time,
                )
                if fill is not None:
                    fills.append(fill)
            else:
                remaining_queue.append(order)

        self._order_queue = remaining_queue
        return tuple(fills)

    def _reject(
        self,
        order: SimulatedOrderV1,
        *,
        reason: str,
        rejected_at: datetime,
    ) -> None:
        rejection = build_simulated_rejection(
            order_id=order.order_id,
            session_key=order.session_key,
            security_id=order.security_id,
            reason=reason,
            rejected_at=rejected_at,
        )
        self._journal.record_rejection(rejection)
