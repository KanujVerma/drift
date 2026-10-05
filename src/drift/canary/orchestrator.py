"""Canary Execution Orchestrator integrating gatekeeper, router, and grader (M17-4).

Coordinates pre-trade micro-capital limits, execution routing, and post-trade
settlement grading for Tiny-Money Canary operations per ADR 0011, ADR 0013,
and ADR 0014.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.canary.settlement import CanarySettlementGrader
from drift.domain.canary import CanarySettlementReportV1
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    build_execution_report,
)
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper

__all__ = [
    "CanaryExecutionOrchestrator",
]


class CanaryExecutionOrchestrator:
    """Orchestrates tiny-money canary order flow from admission to settlement."""

    def __init__(
        self,
        *,
        router: BrokerNeutralExecutionRouter,
        gatekeeper: CanaryAllocationGatekeeper,
        settlement_grader: CanarySettlementGrader,
        risk_gatekeeper: HardRiskGatekeeper | None = None,
    ) -> None:
        self._router = router
        self._gatekeeper = gatekeeper
        self._settlement_grader = settlement_grader
        self._risk_gatekeeper = risk_gatekeeper

    @property
    def router(self) -> BrokerNeutralExecutionRouter:
        """Underlying execution router."""
        return self._router

    @property
    def gatekeeper(self) -> CanaryAllocationGatekeeper:
        """Canary allocation gatekeeper."""
        return self._gatekeeper

    @property
    def settlement_grader(self) -> CanarySettlementGrader:
        """Canary settlement grader."""
        return self._settlement_grader

    @property
    def risk_gatekeeper(self) -> HardRiskGatekeeper | None:
        """Optional hard risk gatekeeper."""
        return self._risk_gatekeeper

    def submit_canary_intent(
        self,
        intent: OrderIntentV1,
        reference_price: Decimal | None = None,
    ) -> tuple[ExecutionReportV1, CanarySettlementReportV1 | None]:
        """Validate, route, and grade a tiny-money canary order intent."""
        now = datetime.now(UTC)

        # 1. Evaluate canary allocation policy
        eval_res = self._gatekeeper.evaluate_intent(intent, reference_price)
        if eval_res.decision == "refused":
            rejection_text = f"canary_refusal: {'; '.join(eval_res.refusal_reasons)}"
            rejected_report = build_execution_report(
                report_id=uuid7(),
                intent_id=intent.intent_id,
                broker_order_id=None,
                status=ExecutionStatus.REJECTED,
                cum_quantity=0,
                leaves_quantity=intent.quantity,
                rejection_reason=rejection_text,
                reported_at=now,
            )
            return (rejected_report, None)

        # 2. Evaluate hard risk gatekeeper if configured
        if self._risk_gatekeeper is not None:
            # Check if kill switch is tripped
            if self._risk_gatekeeper.journal.is_kill_switch_tripped():
                rejected_report = build_execution_report(
                    report_id=uuid7(),
                    intent_id=intent.intent_id,
                    broker_order_id=None,
                    status=ExecutionStatus.REJECTED,
                    cum_quantity=0,
                    leaves_quantity=intent.quantity,
                    rejection_reason="risk_halt: kill switch is tripped",
                    reported_at=now,
                )
                return (rejected_report, None)

        # 3. Capture initial cash balance
        initial_cash = self._router.adapter.get_account_snapshot().cash_balance

        # 4. Route intent to broker
        exec_report = self._router.route_intent(intent)

        # 5. Grade settlement if order was filled
        if exec_report.status == ExecutionStatus.FILLED:
            final_cash = self._router.adapter.get_account_snapshot().cash_balance
            settlement_report = self._settlement_grader.grade_settlement(
                intent=intent,
                report=exec_report,
                initial_cash=initial_cash,
                final_cash=final_cash,
                expected_fill_price=reference_price,
            )
            return (exec_report, settlement_report)

        return (exec_report, None)
