"""Canary Settlement and Fill Reconciliation Grader (M17-3).

Evaluates execution fills against expected bounds, calculates slippage in
basis points, and reconciles cash balance deltas against fill notionals and
fees per ADR 0011, ADR 0013, and ADR 0014.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

from drift.domain.canary import (
    CanaryPolicyV1,
    CanarySettlementReportV1,
    build_canary_settlement_report,
)
from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.execution import ExecutionReportV1, OrderIntentV1, OrderSide

__all__ = [
    "CanarySettlementGrader",
]


class CanarySettlementGrader:
    """Grader evaluating execution report fills and broker cash settlement."""

    def __init__(self, *, policy: CanaryPolicyV1) -> None:
        self._policy = policy

    @property
    def policy(self) -> CanaryPolicyV1:
        """Active canary policy configuration."""
        return self._policy

    def grade_settlement(
        self,
        *,
        intent: OrderIntentV1,
        report: ExecutionReportV1,
        initial_cash: Decimal,
        final_cash: Decimal,
        expected_fill_price: Decimal | None = None,
    ) -> CanarySettlementReportV1:
        """Evaluate fill slippage and exact broker cash reconciliation."""
        now = datetime.now(UTC)

        with decimal_context():
            # Determine expected price
            if expected_fill_price is not None:
                exp_price = expected_fill_price
            elif intent.limit_price is not None:
                exp_price = intent.limit_price
            elif report.avg_fill_price is not None:
                exp_price = report.avg_fill_price
            else:
                exp_price = Decimal("0")

            expected_notional = canonical_money(Decimal(intent.quantity) * exp_price)

            fill_price = (
                report.avg_fill_price
                if report.avg_fill_price is not None
                else Decimal("0")
            )
            actual_fill_notional = canonical_money(
                Decimal(report.cum_quantity) * fill_price
            )
            fee = canonical_money(report.fee_amount)
            cash_delta = canonical_money(final_cash - initial_cash)

            if intent.side == OrderSide.BUY:
                expected_cash_delta = canonical_money(-(actual_fill_notional + fee))
            else:
                expected_cash_delta = canonical_money(actual_fill_notional - fee)

            diff = canonical_money(abs(cash_delta - expected_cash_delta))

            if exp_price > Decimal("0") and report.avg_fill_price is not None:
                price_diff = abs(report.avg_fill_price - exp_price)
                slippage_bps = (price_diff / exp_price) * Decimal("10000")
            else:
                slippage_bps = Decimal("0")

            is_settled = (diff == Decimal("0")) and (
                slippage_bps <= Decimal(self._policy.max_slippage_bps)
            )

        return build_canary_settlement_report(
            report_id=uuid7(),
            intent_id=intent.intent_id,
            broker_order_id=report.broker_order_id,
            is_settled=is_settled,
            expected_notional=expected_notional,
            actual_fill_notional=actual_fill_notional,
            fee_amount=fee,
            cash_balance_delta=cash_delta,
            reconciliation_difference=diff,
            slippage_bps=slippage_bps,
            evaluated_at=now,
        )
