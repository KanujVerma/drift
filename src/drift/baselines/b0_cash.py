"""B0 Cash (Null Hypothesis) reference strategy (Issue 166).

Emits an empty target position set at every session cutoff, holding 100% USD
cash throughout the entire evaluation window with zero transaction costs.
"""

from drift.baselines.common import build_decision_intent, make_baseline_reference
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.strategies import StrategyReference
from drift.serialization.canonical import content_hash

B0_STRATEGY_VERSION = "1"
B0_STRATEGY_HASH = content_hash(
    {
        "strategy_id": "drift.baselines.b0_cash",
        "version": B0_STRATEGY_VERSION,
        "description": (
            "B0 cash baseline holding 100% USD cash throughout the evaluation"
        ),
    }
)


class B0CashStrategy:
    """Deterministic B0 cash baseline strategy."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b0_cash",
            version=B0_STRATEGY_VERSION,
            custom_hash=B0_STRATEGY_HASH,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {"baseline": "B0", "mode": "cash"}

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return build_decision_intent(context, ())

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return build_decision_intent(context, ())
