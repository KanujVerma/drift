"""B4 12-1 Momentum reference strategy (Issue 166).

Ranks eligible securities by 12-1 momentum (close[t-21] / close[t-252] - 1)
derived from corporate-action-consistent analytical return series.
Selects top ceil(n / 2) securities (minimum 2 eligible), tie-breaking by
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

B4_STRATEGY_VERSION = "1"
B4_FORMATION_SESSIONS = 252
B4_SKIP_SESSIONS = 21
B4_MIN_SESSIONS = B4_FORMATION_SESSIONS + 1  # 253 sessions required
B4_MIN_ELIGIBLE_SECURITIES = 2

B4_STRATEGY_HASH = content_hash(
    {
        "strategy_id": "drift.baselines.b4_momentum",
        "version": B4_STRATEGY_VERSION,
        "formation_sessions": B4_FORMATION_SESSIONS,
        "skip_sessions": B4_SKIP_SESSIONS,
        "min_sessions": B4_MIN_SESSIONS,
        "min_eligible_securities": B4_MIN_ELIGIBLE_SECURITIES,
    }
)


class B4MomentumStrategy:
    """Deterministic 12-1 momentum reference strategy."""

    def __init__(
        self,
        adjustments_by_security: (
            Mapping[UUID7, Sequence[CorporateActionAdjustment]] | None
        ) = None,
        formation_sessions: int = B4_FORMATION_SESSIONS,
        skip_sessions: int = B4_SKIP_SESSIONS,
        min_eligible_count: int = B4_MIN_ELIGIBLE_SECURITIES,
    ) -> None:
        self.adjustments_by_security = adjustments_by_security or {}
        self.formation_sessions = formation_sessions
        self.skip_sessions = skip_sessions
        self.min_sessions = formation_sessions + 1
        self.min_eligible_count = min_eligible_count

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b4_momentum",
            version=B4_STRATEGY_VERSION,
            custom_hash=B4_STRATEGY_HASH,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {
            "baseline": "B4",
            "mode": "momentum_12_1",
            "formation_sessions": self.formation_sessions,
            "skip_sessions": self.skip_sessions,
            "min_sessions": self.min_sessions,
            "min_eligible_count": self.min_eligible_count,
        }

    def _compute_momentum(
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

        # t is index len - 1
        t = len(sessions) - 1
        close_skip = sessions[t - self.skip_sessions].analytical_close
        close_form = sessions[t - self.formation_sessions].analytical_close

        with decimal_context():
            if close_form <= Decimal("0"):
                return None
            return (close_skip / close_form) - Decimal("1")

    def _decide_internal(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        admitted = get_admitted_securities(context)
        if len(admitted) < self.min_eligible_count:
            return build_decision_intent(context, ())

        # Calculate momentum for all admitted securities with sufficient history
        scores: list[tuple[Decimal, bytes, UUID7]] = []
        for sec in admitted:
            mom = self._compute_momentum(context, sec)
            if mom is not None:
                # Rank by momentum descending; tie-break by security_id.bytes ascending
                scores.append((mom, security_order_key(sec), sec))

        if len(scores) < self.min_eligible_count:
            # Insufficient eligible securities (minimum 2 required)
            return build_decision_intent(context, ())

        # Sort: momentum descending (-score[0]), then UUID bytes ascending
        scores.sort(key=lambda item: (-item[0], item[1]))

        # Select top ceil(n / 2)
        n = len(scores)
        top_k = math.ceil(n / 2)
        selected_securities = [item[2] for item in scores[:top_k]]

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
