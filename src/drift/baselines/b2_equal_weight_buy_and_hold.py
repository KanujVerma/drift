"""B2 Equal-Weight Cohort Buy-and-Hold reference strategy (Issue 166).

Allocates available cash equally across all admitted cohort members at the
initial session open, purchasing floor(cash / (n * price)) whole shares, and
holds all positions without subsequent turnover.
"""

from decimal import Decimal

from drift.baselines.common import (
    build_decision_intent,
    extract_current_close_price,
    get_admitted_securities,
    make_baseline_reference,
)
from drift.domain.common import ImmutableJSONValue
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

B2_STRATEGY_VERSION = "1"
B2_STRATEGY_HASH = content_hash(
    {
        "strategy_id": "drift.baselines.b2_equal_weight_buy_and_hold",
        "version": B2_STRATEGY_VERSION,
        "description": "B2 equal-weight cohort buy-and-hold without turnover",
    }
)


class B2EqualWeightBuyAndHoldStrategy:
    """Deterministic equal-weight cohort buy-and-hold strategy."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b2_equal_weight_buy_and_hold",
            version=B2_STRATEGY_VERSION,
            custom_hash=B2_STRATEGY_HASH,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {"baseline": "B2", "mode": "equal_weight_buy_and_hold"}

    def _decide_internal(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        # If we already have open positions, preserve them with zero subsequent turnover
        if context.current_holdings:
            targets = tuple(
                SecurityTargetPositionV1(
                    security_id=holding.security_id,
                    target_quantity=holding.quantity,
                )
                for holding in context.current_holdings
            )
            return build_decision_intent(context, targets)

        admitted = get_admitted_securities(context)
        if not admitted or context.current_cash <= Decimal("0"):
            return build_decision_intent(context, ())

        n = len(admitted)
        target_list: list[SecurityTargetPositionV1] = []
        with decimal_context():
            dollars_per_security = context.current_cash / Decimal(str(n))
            for sec in admitted:
                price = extract_current_close_price(context, sec)
                if price is not None and price > Decimal("0"):
                    qty = int(dollars_per_security // price)
                    if qty > 0:
                        target_list.append(
                            SecurityTargetPositionV1(
                                security_id=sec,
                                target_quantity=qty,
                            )
                        )

        return build_decision_intent(context, target_list)

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)
