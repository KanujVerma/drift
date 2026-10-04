"""B5 60-Session Low Volatility reference strategy (Issue 166).

Ranks eligible securities by exact population variance of 60 close-to-close
analytical returns from corporate-action-consistent analytical return series.
Selects bottom ceil(n / 2) securities (minimum 2 eligible), tie-breaking by
security_id bytes, and allocates whole shares equally across selected names.
"""

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

from drift.analysis.analytical_returns import (
    CorporateActionAdjustment,
    build_analytical_return_series,
)
from drift.baselines.common import (
    build_decision_intent,
    extract_current_close_price,
    extract_security_history,
    get_admitted_securities,
    make_baseline_reference,
    security_order_key,
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

B5_STRATEGY_VERSION = "1"
B5_LOOKBACK_RETURNS = 60
B5_MIN_SESSIONS = B5_LOOKBACK_RETURNS + 1  # 61 sessions required for 60 returns
B5_MIN_ELIGIBLE_SECURITIES = 2

B5_STRATEGY_HASH = content_hash(
    {
        "strategy_id": "drift.baselines.b5_low_volatility",
        "version": B5_STRATEGY_VERSION,
        "lookback_returns": B5_LOOKBACK_RETURNS,
        "min_sessions": B5_MIN_SESSIONS,
        "min_eligible_securities": B5_MIN_ELIGIBLE_SECURITIES,
    }
)


class B5LowVolatilityStrategy:
    """Deterministic 60-session low-volatility reference strategy."""

    def __init__(
        self,
        adjustments_by_security: (
            Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
        ) = None,
        lookback_returns: int = B5_LOOKBACK_RETURNS,
        min_eligible_count: int = B5_MIN_ELIGIBLE_SECURITIES,
    ) -> None:
        self.adjustments_by_security = adjustments_by_security or {}
        self.lookback_returns = lookback_returns
        self.min_sessions = lookback_returns + 1
        self.min_eligible_count = min_eligible_count

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b5_low_volatility",
            version=B5_STRATEGY_VERSION,
            custom_hash=B5_STRATEGY_HASH,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {
            "baseline": "B5",
            "mode": "low_volatility_60_session",
            "lookback_returns": self.lookback_returns,
            "min_sessions": self.min_sessions,
            "min_eligible_count": self.min_eligible_count,
        }

    def _compute_variance(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
        security_id: UUID7,
    ) -> Decimal | None:
        history = extract_security_history(context, security_id)
        if len(history) < self.min_sessions:
            return None

        adjustments = self.adjustments_by_security.get(security_id, ())
        series = build_analytical_return_series(
            security_id=security_id,
            grade="exploratory",
            observations=history,
            adjustments=adjustments,
        )

        sessions = series.sessions
        if len(sessions) < self.min_sessions:
            return None

        # Take the exact last lookback_returns sessions with valid returns
        recent_sessions = sessions[-self.lookback_returns :]
        returns: list[Decimal] = []
        for s in recent_sessions:
            if s.return_from_prior is None:
                return None
            returns.append(s.return_from_prior)

        if len(returns) != self.lookback_returns:
            return None

        # Exact population variance: 1/N * sum((r - mean)^2)
        n = Decimal(str(len(returns)))
        with decimal_context():
            mean = sum(returns) / n
            variance = sum((r - mean) ** 2 for r in returns) / n
        return variance

    def _decide_internal(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        admitted = get_admitted_securities(context)
        if len(admitted) < self.min_eligible_count:
            return build_decision_intent(context, ())

        # Calculate return variance for all admitted securities with sufficient history
        scores: list[tuple[Decimal, bytes, UUID7]] = []
        for sec in admitted:
            var = self._compute_variance(context, sec)
            if var is not None:
                # Rank by variance ascending; tie-break by security_id.bytes ascending
                scores.append((var, security_order_key(sec), sec))

        if len(scores) < self.min_eligible_count:
            # Insufficient eligible securities (minimum 2 required)
            return build_decision_intent(context, ())

        # Sort: variance ascending (score[0]), then UUID bytes ascending
        scores.sort(key=lambda item: (item[0], item[1]))

        # Select bottom ceil(n / 2) lowest volatility
        n = len(scores)
        bottom_k = math.ceil(n / 2)
        selected_securities = [item[2] for item in scores[:bottom_k]]

        if not selected_securities or context.portfolio_nav <= Decimal("0"):
            return build_decision_intent(context, ())

        targets: list[SecurityTargetPositionV1] = []
        count_dec = Decimal(str(len(selected_securities)))
        with decimal_context():
            dollars_per_security = context.portfolio_nav / count_dec
            for sec in selected_securities:
                price = extract_current_close_price(context, sec)
                if price is not None and price > Decimal("0"):
                    qty = int(dollars_per_security // price)
                    if qty > 0:
                        targets.append(
                            SecurityTargetPositionV1(
                                security_id=sec,
                                target_quantity=qty,
                            )
                        )

        return build_decision_intent(context, targets)

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return self._decide_internal(context)
