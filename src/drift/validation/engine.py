"""Shadow validation engine and execution orchestrator (M15-4).

Coordinates incoming streaming market ticks from MarketDataStreamerProtocol,
updates broker adapter market prices, routes OrderIntentV1 intents through
BrokerNeutralExecutionRouter (M14), tracks execution drift/slippage in
PersistentShadowValidationJournal, and generates session summary telemetry.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

from drift.domain.evaluator_portfolio import (
    PortfolioStateV2,
    canonical_money,
    decimal_context,
)
from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
)
from drift.domain.paper_validation import (
    MarketTickV1,
    ShadowValidationSummaryV1,
    build_execution_drift_report,
    build_shadow_validation_summary,
)
from drift.domain.sessions import SessionKeyV1
from drift.errors import DriftError
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.validation.feed import MarketDataStreamerProtocol
from drift.validation.journal import PersistentShadowValidationJournal

__all__ = [
    "RiskHaltValidationError",
    "ShadowValidationEngine",
    "ValidationEngineError",
]


class ValidationEngineError(DriftError):
    """Base exception for shadow validation engine operations."""


class RiskHaltValidationError(ValidationEngineError):
    """Raised when an order intent is attempted while kill switch is active."""


class ShadowValidationEngine:
    """Orchestrates paper market feeds, risk gating, and execution validation."""

    def __init__(
        self,
        *,
        streamer: MarketDataStreamerProtocol,
        router: BrokerNeutralExecutionRouter,
        journal: PersistentShadowValidationJournal,
        session_key: SessionKeyV1,
        risk_gatekeeper: HardRiskGatekeeper | None = None,
    ) -> None:
        self._streamer = streamer
        self._router = router
        self._journal = journal
        self._session_key = session_key
        self._risk_gatekeeper = risk_gatekeeper

        self._latest_prices: dict[UUID, Decimal] = {}
        self._ticks_processed: int = 0
        self._orders_generated: int = 0
        self._orders_approved: int = 0
        self._orders_rejected_risk: int = 0
        self._orders_filled: int = 0
        self._slippage_records: list[Decimal] = []

    @property
    def streamer(self) -> MarketDataStreamerProtocol:
        """Underlying market data streamer."""
        return self._streamer

    @property
    def router(self) -> BrokerNeutralExecutionRouter:
        """Underlying execution router."""
        return self._router

    @property
    def journal(self) -> PersistentShadowValidationJournal:
        """Underlying shadow validation journal."""
        return self._journal

    @property
    def session_key(self) -> SessionKeyV1:
        """Active session key."""
        return self._session_key

    def get_latest_price(self, security_id: UUID) -> Decimal | None:
        """Get latest recorded market price for a security."""
        return self._latest_prices.get(security_id)

    def process_next_tick(self) -> MarketTickV1 | None:
        """Consume next market tick, persist telemetry, and update adapter pricing."""
        tick = self._streamer.next_tick()
        if tick is None:
            return None

        # Record tick to journal
        self._ticks_processed += 1
        self._journal.record_tick(tick)
        self._latest_prices[tick.security_id] = tick.last_price

        # Update broker adapter price if adapter supports price configuration
        adapter = self._router.adapter
        if hasattr(adapter, "set_price"):
            adapter.set_price(tick.security_id, tick.last_price)

        return tick

    def route_intent(
        self,
        intent: OrderIntentV1,
        *,
        intended_price: Decimal | None = None,
    ) -> ExecutionReportV1:
        """Route an order intent through risk check and broker-neutral router."""
        self._orders_generated += 1
        now = datetime.now(UTC)

        # Check hard risk kill switch latch if gatekeeper configured
        if self._risk_gatekeeper is not None:
            if self._risk_gatekeeper.journal.is_kill_switch_tripped():
                self._orders_rejected_risk += 1
                raise RiskHaltValidationError(
                    "kill switch active: paper order submission refused"
                )

        self._orders_approved += 1

        # Determine reference intended price for slippage calculation
        ref_price = (
            intended_price
            if intended_price is not None
            else (
                intent.limit_price
                if intent.limit_price is not None
                else self._latest_prices.get(intent.security_id)
            )
        )

        # Dispatch through router
        report = self._router.route_intent(intent)

        if report.status == ExecutionStatus.FILLED:
            self._orders_filled += 1
            if ref_price is not None and report.avg_fill_price is not None:
                drift = build_execution_drift_report(
                    drift_id=uuid7(),
                    intent_id=intent.intent_id,
                    security_id=intent.security_id,
                    intended_price=ref_price,
                    fill_price=report.avg_fill_price,
                    recorded_at=now,
                )
                self._journal.record_drift_report(drift)
                self._slippage_records.append(drift.slippage_bps)

        return report

    def reconcile_portfolio(self, portfolio_state: PortfolioStateV2) -> bool:
        """Reconcile broker adapter positions against target portfolio state."""
        return self._router.reconcile_positions(portfolio_state)

    def finalize_summary(
        self,
        final_equity: Decimal,
    ) -> ShadowValidationSummaryV1:
        """Compute aggregate session metrics, persist summary, and return report."""
        with decimal_context():
            total_slippage = (
                sum(self._slippage_records, Decimal("0"))
                if self._slippage_records
                else Decimal("0")
            )
            mean_slippage = (
                canonical_money(total_slippage / Decimal(len(self._slippage_records)))
                if self._slippage_records
                else Decimal("0")
            )
            max_slippage = (
                canonical_money(max(self._slippage_records))
                if self._slippage_records
                else Decimal("0")
            )

        summary = build_shadow_validation_summary(
            validation_id=uuid7(),
            session_key=self._session_key,
            total_ticks_processed=self._ticks_processed,
            orders_generated=self._orders_generated,
            orders_approved=self._orders_approved,
            orders_rejected_risk=self._orders_rejected_risk,
            orders_filled=self._orders_filled,
            total_slippage_bps=canonical_money(total_slippage),
            mean_slippage_bps=mean_slippage,
            max_slippage_bps=max_slippage,
            final_equity=canonical_money(final_equity),
        )

        self._journal.record_summary(summary)
        return summary
