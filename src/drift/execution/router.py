"""Broker-neutral execution router and idempotency engine (M14-4).

Routes abstract OrderIntentV1 intents to BrokerAdapterProtocol implementations,
enforces intent idempotency via PersistentOrderIntentJournal, and audits all
outbound intents and inbound execution reports.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    build_execution_report,
)
from drift.domain.risk import RiskVerdictStatus
from drift.errors import DriftError
from drift.execution.adapter import BrokerAdapterProtocol
from drift.execution.journal import (
    PersistentOrderIntentJournal,
)
from drift.risk.gatekeeper import HardRiskGatekeeper

__all__ = [
    "BrokerNeutralExecutionRouter",
    "DuplicateClientOrderIdError",
    "RouterExecutionError",
    "UnknownIntentError",
]


class RouterExecutionError(DriftError):
    """Base exception for execution router failures."""


class DuplicateClientOrderIdError(RouterExecutionError):
    """Raised when a client_order_id is submitted with conflicting intent parameters."""


class UnknownIntentError(RouterExecutionError):
    """Raised when an operation references an intent_id not recorded in the journal."""


class BrokerNeutralExecutionRouter:
    """Deterministic, idempotent router dispatching intents to broker adapters."""

    def __init__(
        self,
        *,
        adapter: BrokerAdapterProtocol,
        journal: PersistentOrderIntentJournal,
        risk_gatekeeper: HardRiskGatekeeper | None = None,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._risk_gatekeeper = risk_gatekeeper

    @property
    def adapter(self) -> BrokerAdapterProtocol:
        """Underlying broker adapter."""
        return self._adapter

    @property
    def journal(self) -> PersistentOrderIntentJournal:
        """Underlying audit journal."""
        return self._journal

    @property
    def risk_gatekeeper(self) -> HardRiskGatekeeper | None:
        """Optional pre-execution hard risk gatekeeper."""
        return self._risk_gatekeeper

    def route_intent(
        self,
        intent: OrderIntentV1,
        *,
        current_price: Decimal | None = None,
    ) -> ExecutionReportV1:
        """Route an order intent to the broker adapter with idempotency guarantees.

        If the client_order_id or intent_id has already been recorded:
        - If the recorded intent matches exactly (idempotent replay), returns
          the latest recorded execution report.
        - If the recorded intent differs (duplicate reuse attack/bug), raises
          DuplicateClientOrderIdError.
        Otherwise:
        - Persists the outbound intent to the journal.
        - Evaluates risk_gatekeeper if configured; returns REJECTED if disallowed.
        - Dispatches the intent to the broker adapter.
        - Persists the resulting execution report to the journal.
        - Returns the execution report.
        """
        # Check idempotency by client_order_id
        existing = self._journal.get_intent_by_client_id(intent.client_order_id)
        if existing is not None:
            if (
                existing.intent_hash != intent.intent_hash
                or existing.intent_id != intent.intent_id
            ):
                raise DuplicateClientOrderIdError(
                    f"client_order_id {intent.client_order_id} already exists "
                    "with different intent"
                )
            latest = self._journal.get_latest_execution_report(existing.intent_id)
            if latest is not None:
                return latest
            adapter_rep = self._adapter.get_intent_status(existing.intent_id)
            if adapter_rep is not None:
                self._journal.record_execution_report(adapter_rep)
                return adapter_rep

        # Check idempotency by intent_id
        existing_id = self._journal.get_intent(intent.intent_id)
        if existing_id is not None:
            if (
                existing_id.intent_hash != intent.intent_hash
                or existing_id.client_order_id != intent.client_order_id
            ):
                raise DuplicateClientOrderIdError(
                    f"intent_id {intent.intent_id} already exists with different intent"
                )
            latest = self._journal.get_latest_execution_report(existing_id.intent_id)
            if latest is not None:
                return latest
            adapter_rep = self._adapter.get_intent_status(existing_id.intent_id)
            if adapter_rep is not None:
                self._journal.record_execution_report(adapter_rep)
                return adapter_rep

        # New intent: record to journal
        self._journal.record_intent(intent)

        # Pre-execution hard risk gatekeeper evaluation
        if self._risk_gatekeeper is not None:
            eval_price = (
                current_price if current_price is not None else intent.limit_price
            )
            verdict = self._risk_gatekeeper.evaluate_order(
                intent,
                current_price=eval_price,
                evaluation_time=intent.created_at,
            )
            if verdict.status != RiskVerdictStatus.ALLOWED:
                rejection_reason = (
                    "risk_gatekeeper_halt: kill switch active"
                    if verdict.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
                    else f"risk_gatekeeper_rejection: {verdict.reason}"
                )
                rejected_report = build_execution_report(
                    report_id=uuid7(),
                    intent_id=intent.intent_id,
                    broker_order_id=None,
                    status=ExecutionStatus.REJECTED,
                    cum_quantity=0,
                    leaves_quantity=intent.quantity,
                    rejection_reason=rejection_reason,
                    reported_at=datetime.now(UTC),
                )
                self._journal.record_execution_report(rejected_report)
                return rejected_report

        # Dispatch to broker adapter
        report = self._adapter.submit_intent(intent)
        self._journal.record_execution_report(report)
        return report

    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1:
        """Request cancellation of an order intent and persist resulting report."""
        existing = self._journal.get_intent(intent_id)
        if existing is None:
            raise UnknownIntentError(f"intent_id {intent_id} not found in journal")

        report = self._adapter.cancel_intent(intent_id)
        self._journal.record_execution_report(report)
        return report

    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None:
        """Query latest execution report for an intent from adapter and journal."""
        adapter_rep = self._adapter.get_intent_status(intent_id)
        if adapter_rep is not None:
            latest_journal = self._journal.get_latest_execution_report(intent_id)
            if (
                latest_journal is None
                or latest_journal.report_id != adapter_rep.report_id
            ):
                self._journal.record_execution_report(adapter_rep)
            return adapter_rep

        return self._journal.get_latest_execution_report(intent_id)

    def get_position_discrepancies(
        self,
        target_state: PortfolioStateV2,
    ) -> tuple[str, ...]:
        """Compute discrepancies between adapter positions and portfolio state."""
        broker_positions = {
            pos.security_id: pos.quantity
            for pos in self._adapter.get_positions()
            if pos.quantity > 0
        }
        portfolio_holdings = {
            h.security_id: h.quantity for h in target_state.holdings if h.quantity > 0
        }

        all_sec_ids = sorted(
            set(broker_positions.keys()) | set(portfolio_holdings.keys()),
            key=lambda uid: str(uid),
        )

        discrepancies: list[str] = []
        for sec_id in all_sec_ids:
            broker_qty = broker_positions.get(sec_id, 0)
            target_qty = portfolio_holdings.get(sec_id, 0)
            if broker_qty != target_qty:
                discrepancies.append(
                    f"security {sec_id}: broker held {broker_qty}, "
                    f"portfolio held {target_qty}"
                )

        return tuple(discrepancies)

    def reconcile_positions(self, target_state: PortfolioStateV2) -> bool:
        """Compare broker positions against canonical portfolio state holdings."""
        return len(self.get_position_discrepancies(target_state)) == 0
