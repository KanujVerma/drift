"""B1 Per-Security Buy-and-Hold reference strategy (Issue 166).

Commits 100% of available cash to whole shares of a single designated cohort
security at the initial opportunity and holds that exact position without
rebalancing.
"""

from decimal import Decimal

from drift.baselines.common import (
    build_decision_intent,
    extract_current_close_price,
    get_admitted_securities,
    make_baseline_reference,
)
from drift.domain.common import UUID7, ImmutableJSONValue
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.strategies import StrategyReference
from drift.serialization.canonical import content_hash

B1_STRATEGY_VERSION = "1"


class B1SingleBuyAndHoldStrategy:
    """Deterministic single-security buy-and-hold strategy."""

    def __init__(self, target_security_id: UUID7) -> None:
        self.target_security_id = target_security_id
        self._strategy_hash = content_hash(
            {
                "strategy_id": "drift.baselines.b1_single_buy_and_hold",
                "version": B1_STRATEGY_VERSION,
                "target_security_id": str(target_security_id),
            }
        )

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b1_single_buy_and_hold",
            version=B1_STRATEGY_VERSION,
            custom_hash=self._strategy_hash,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {
            "baseline": "B1",
            "target_security_id": str(self.target_security_id),
        }

    def _decide_internal(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        admitted = get_admitted_securities(context)
        if self.target_security_id not in admitted:
            return build_decision_intent(context, ())

        # Check if we already hold a position in the target security
        existing_holding = next(
            (
                h
                for h in context.current_holdings
                if h.security_id == self.target_security_id
            ),
            None,
        )
        if existing_holding is not None:
            # Maintain exact existing position without subsequent turnover
            target = SecurityTargetPositionV1(
                security_id=self.target_security_id,
                target_quantity=existing_holding.quantity,
            )
            return build_decision_intent(context, (target,))

        # First entry: allocate 100% available cash to whole shares
        price = extract_current_close_price(context, self.target_security_id)
        if price is None or price <= Decimal("0"):
            return build_decision_intent(context, ())

        with decimal_context():
            qty = int(context.current_cash // price)

        if qty <= 0:
            return build_decision_intent(context, ())

        target = SecurityTargetPositionV1(
            security_id=self.target_security_id,
            target_quantity=qty,
        )
        return build_decision_intent(context, (target,))

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)
