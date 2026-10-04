"""B3 Monthly Equal-Weight Rebalance reference strategy (Issue 166).

Decides after the final eligible session close of each calendar month, computing
equal-weight target positions against closing portfolio NAV and executing
at the next session open. On intervening sessions, maintains held positions.
"""

from collections.abc import Sequence
from datetime import date, timedelta
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

B3_STRATEGY_VERSION = "1"


def is_month_end_session_day(day: date) -> bool:
    """Heuristic for determining if a weekday is the final session day of the month."""
    # Check next weekday
    step = 3 if day.weekday() == 4 else (2 if day.weekday() == 5 else 1)
    next_business_day = day + timedelta(days=step)
    return next_business_day.month != day.month


class B3MonthlyEqualWeightRebalanceStrategy:
    """Deterministic monthly equal-weight rebalancing strategy."""

    def __init__(
        self,
        rebalance_dates: Sequence[date] | None = None,
        rebalance_on_initial_session: bool = True,
    ) -> None:
        self.rebalance_dates = (
            frozenset(rebalance_dates) if rebalance_dates is not None else None
        )
        self.rebalance_on_initial_session = rebalance_on_initial_session
        self._strategy_hash = content_hash(
            {
                "strategy_id": "drift.baselines.b3_monthly_equal_weight_rebalance",
                "version": B3_STRATEGY_VERSION,
                "rebalance_dates": (
                    sorted(d.isoformat() for d in self.rebalance_dates)
                    if self.rebalance_dates is not None
                    else None
                ),
                "rebalance_on_initial_session": self.rebalance_on_initial_session,
            }
        )

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name="b3_monthly_equal_weight_rebalance",
            version=B3_STRATEGY_VERSION,
            custom_hash=self._strategy_hash,
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {
            "baseline": "B3",
            "mode": "monthly_equal_weight_rebalance",
            "rebalance_dates": (
                tuple(sorted(d.isoformat() for d in self.rebalance_dates))
                if self.rebalance_dates is not None
                else None
            ),
            "rebalance_on_initial_session": self.rebalance_on_initial_session,
        }

    def _is_rebalance_session(
        self,
        current_date: date,
        has_holdings: bool,
    ) -> bool:
        if not has_holdings and self.rebalance_on_initial_session:
            return True
        if self.rebalance_dates is not None:
            return current_date in self.rebalance_dates
        return is_month_end_session_day(current_date)

    def _decide_internal(
        self,
        context: StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        current_date = context.session_key.local_date
        has_holdings = len(context.current_holdings) > 0

        if not self._is_rebalance_session(current_date, has_holdings):
            # Maintain existing holdings
            targets = tuple(
                SecurityTargetPositionV1(
                    security_id=holding.security_id,
                    target_quantity=holding.quantity,
                )
                for holding in context.current_holdings
            )
            return build_decision_intent(context, targets)

        # Monthly rebalance: equal-weight across admitted universe/cohort
        # against portfolio NAV
        admitted = get_admitted_securities(context)
        if not admitted or context.portfolio_nav <= Decimal("0"):
            return build_decision_intent(context, ())

        n = len(admitted)
        target_list: list[SecurityTargetPositionV1] = []
        with decimal_context():
            dollars_per_security = context.portfolio_nav / Decimal(str(n))
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
