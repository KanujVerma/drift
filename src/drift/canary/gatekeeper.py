"""Canary Allocation Gatekeeper enforcing micro-capital boundaries (M17-2).

Enforces non-negotiable micro-capital constraints, single-share quantities,
symbol whitelists, and runtime authorization tokens for Tiny-Money Canary
trading per ADR 0011, ADR 0013, and ADR 0014.
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from drift.domain.canary import CanaryEvaluationResultV1, CanaryPolicyV1
from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.execution import OrderIntentV1

__all__ = [
    "CanaryAllocationGatekeeper",
]


class CanaryAllocationGatekeeper:
    """Gatekeeper enforcing micro-capital canary limits and authorization tokens."""

    def __init__(
        self,
        *,
        policy: CanaryPolicyV1,
        symbol_map: Mapping[UUID, str] | None = None,
    ) -> None:
        self._policy = policy
        self._symbol_map: dict[UUID, str] = dict(symbol_map) if symbol_map else {}
        self._cumulative_allocated_notional = Decimal("0")

    @property
    def policy(self) -> CanaryPolicyV1:
        """Active canary policy configuration."""
        return self._policy

    @property
    def cumulative_allocated_notional(self) -> Decimal:
        """Total cumulative capital allocated across admitted canary orders."""
        return self._cumulative_allocated_notional

    def reset_allocation(self) -> None:
        """Reset cumulative allocated capital counter."""
        self._cumulative_allocated_notional = Decimal("0")

    def evaluate_intent(
        self,
        intent: OrderIntentV1,
        reference_price: Decimal | None = None,
    ) -> CanaryEvaluationResultV1:
        """Evaluate an order intent against the active CanaryPolicyV1."""
        reasons: list[str] = []

        # 1. Authorization check
        if not self._policy.canary_authorized:
            reasons.append("canary_unauthorized")

        # 2. Quantity limit check
        if intent.quantity > self._policy.max_order_quantity:
            reasons.append(
                f"quantity {intent.quantity} exceeds max_order_quantity "
                f"{self._policy.max_order_quantity}"
            )

        # 3. Whitelist check
        if self._policy.whitelisted_symbols:
            sym = self._symbol_map.get(intent.security_id)
            if sym is None or sym not in self._policy.whitelisted_symbols:
                reasons.append(f"symbol {sym} not in whitelisted_symbols")

        # 4. Pricing and notional checks
        price = (
            intent.limit_price if intent.limit_price is not None else reference_price
        )

        if price is None or price <= Decimal("0"):
            reasons.append("missing or non-positive price for notional evaluation")
            order_notional = Decimal("0")
        else:
            with decimal_context():
                order_notional = canonical_money(Decimal(intent.quantity) * price)

            if order_notional > self._policy.max_order_notional:
                reasons.append(
                    f"order notional {order_notional} exceeds max_order_notional "
                    f"{self._policy.max_order_notional}"
                )

            with decimal_context():
                projected_cum = canonical_money(
                    self._cumulative_allocated_notional + order_notional
                )
            if projected_cum > self._policy.max_cumulative_notional:
                reasons.append(
                    f"projected cumulative notional {projected_cum} exceeds "
                    f"max_cumulative_notional {self._policy.max_cumulative_notional}"
                )

        if reasons:
            return CanaryEvaluationResultV1(
                decision="refused",
                refusal_reasons=tuple(reasons),
                order_notional=order_notional,
                cumulative_allocated_notional=self._cumulative_allocated_notional,
            )

        # Admission
        with decimal_context():
            self._cumulative_allocated_notional = canonical_money(
                self._cumulative_allocated_notional + order_notional
            )

        return CanaryEvaluationResultV1(
            decision="admitted",
            refusal_reasons=(),
            order_notional=order_notional,
            cumulative_allocated_notional=self._cumulative_allocated_notional,
        )
