"""Bounded Autonomy Orchestrator integrating governor, router, and risk (M18-4).

Coordinates tier-based allocation limits, risk gatekeeper halts, and execution
routing for bounded autonomous trading per ADR 0011, ADR 0013, and ADR 0014.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

from drift.autonomy.governor import AllocationExpansionGovernor
from drift.domain.autonomy import GovernanceTransitionV1
from drift.domain.evaluator_portfolio import canonical_money, decimal_context
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    build_execution_report,
)
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper

__all__ = [
    "BoundedAutonomyOrchestrator",
]


class BoundedAutonomyOrchestrator:
    """Orchestrates bounded live execution under continuous evidence governance."""

    def __init__(
        self,
        *,
        governor: AllocationExpansionGovernor,
        router: BrokerNeutralExecutionRouter,
        risk_gatekeeper: HardRiskGatekeeper | None = None,
    ) -> None:
        self._governor = governor
        self._router = router
        self._risk_gatekeeper = risk_gatekeeper

    @property
    def governor(self) -> AllocationExpansionGovernor:
        """Underlying allocation expansion governor."""
        return self._governor

    @property
    def router(self) -> BrokerNeutralExecutionRouter:
        """Underlying execution router."""
        return self._router

    @property
    def risk_gatekeeper(self) -> HardRiskGatekeeper | None:
        """Optional hard risk gatekeeper."""
        return self._risk_gatekeeper

    def submit_autonomous_intent(
        self,
        intent: OrderIntentV1,
        reference_price: Decimal | None = None,
    ) -> ExecutionReportV1:
        """Validate tier limits and risk state, then route intent to broker."""
        now = datetime.now(UTC)
        limits = self._governor.get_active_limits()

        # 1. Tier quantity cap
        if intent.quantity > limits.max_order_quantity:
            return build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason=(
                    f"tier_quantity_limit_exceeded: quantity {intent.quantity} "
                    f"> max {limits.max_order_quantity}"
                ),
                reported_at=now,
            )

        # 2. Tier notional cap
        price = (
            intent.limit_price if intent.limit_price is not None else reference_price
        )
        if price is None or price <= Decimal("0"):
            return build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason="missing_or_invalid_price_for_tier_evaluation",
                reported_at=now,
            )

        with decimal_context():
            order_notional = canonical_money(Decimal(intent.quantity) * price)

        if order_notional > limits.max_order_notional:
            return build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason=(
                    f"tier_notional_limit_exceeded: notional {order_notional} "
                    f"> max {limits.max_order_notional}"
                ),
                reported_at=now,
            )

        # 3. Hard risk kill switch check
        if self._risk_gatekeeper is not None:
            if self._risk_gatekeeper.journal.is_kill_switch_tripped():
                self._governor.record_kill_switch_trip(
                    "kill switch active during submission"
                )
                return build_execution_report(
                    report_id=uuid7(),
                    intent_id=intent.intent_id,
                    broker_order_id=None,
                    status=ExecutionStatus.REJECTED,
                    cum_quantity=0,
                    leaves_quantity=intent.quantity,
                    rejection_reason="emergency_kill_switch_active",
                    reported_at=now,
                )

        # 4. Route through broker-neutral router
        exec_report = self._router.route_intent(intent)

        # 5. Record clean session progression if filled
        if exec_report.status == ExecutionStatus.FILLED:
            self._governor.record_clean_session()

        return exec_report

    def review_evidence_and_update_tier(
        self,
        scorecard: Mapping[str, Any],
        drift_multiplier: Decimal | None = None,
    ) -> GovernanceTransitionV1:
        """Perform periodic evidence review and adjust allocation tier."""
        return self._governor.evaluate_evidence(
            scorecard=scorecard,
            drift_multiplier=drift_multiplier,
        )
