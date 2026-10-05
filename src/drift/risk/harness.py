"""Shadow broker and hard risk harness integration (M13-4).

Binds HardRiskGatekeeper directly upstream of ShadowBroker, providing
deterministic, pre-execution risk gating and audit logging.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.risk import (
    RiskVerdictStatus,
    RiskVerdictV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    MarketExecutionEligibilityV1,
    SimulatedFillV1,
    SimulatedOrderV1,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import SimulationExecutionJournal

__all__ = [
    "RiskManagedBroker",
]


class RiskManagedBroker:
    """Deterministic integration harness between HardRiskGatekeeper and ShadowBroker.

    Guarantees that every order intent is evaluated against persistent risk
    rules before routing to the simulation execution queue.
    """

    def __init__(
        self,
        *,
        broker: ShadowBroker,
        gatekeeper: HardRiskGatekeeper,
    ) -> None:
        self._broker = broker
        self._gatekeeper = gatekeeper

    @property
    def broker(self) -> ShadowBroker:
        """Underlying simulation broker."""
        return self._broker

    @property
    def gatekeeper(self) -> HardRiskGatekeeper:
        """Deterministic hard risk gatekeeper."""
        return self._gatekeeper

    @property
    def kernel(self) -> PortfolioAccountingKernel:
        """Canonical portfolio accounting kernel."""
        return self._broker.kernel

    @property
    def execution_journal(self) -> SimulationExecutionJournal:
        """Underlying execution journal."""
        return self._broker.journal

    @property
    def risk_journal(self) -> PersistentRiskJournal:
        """Underlying risk journal and kill switch."""
        return self._gatekeeper.journal

    def submit_order(
        self,
        order: SimulatedOrderV1,
        *,
        current_price: Decimal | None,
        evaluation_time: datetime,
    ) -> RiskVerdictV1:
        """Evaluate order against hard risk gatekeeper and queue if permitted.

        If the verdict is ALLOWED, the order is forwarded to the shadow broker queue
        and recorded in the execution journal.
        If the verdict is REJECTED or KILL_SWITCH_ACTIVE, the order is dropped
        fail-closed and never queued with the shadow broker.
        """
        verdict = self._gatekeeper.evaluate_order(
            order,
            portfolio_state=self._broker.kernel.state,
            current_price=current_price,
            evaluation_time=evaluation_time,
        )
        if verdict.status == RiskVerdictStatus.ALLOWED:
            self._broker.submit_order(order)
        return verdict

    def execute_order(
        self,
        order: SimulatedOrderV1,
        *,
        open_price: Decimal | None,
        eligibility: MarketExecutionEligibilityV1 | None,
        execution_time: datetime,
    ) -> SimulatedFillV1 | None:
        """Execute a single simulated order through shadow broker."""
        return self._broker.execute_order(
            order,
            open_price=open_price,
            eligibility=eligibility,
            execution_time=execution_time,
        )

    def execute_session(
        self,
        *,
        session_key: SessionKeyV1,
        open_prices: Mapping[UUID, Decimal],
        eligibilities: Mapping[UUID, MarketExecutionEligibilityV1],
        execution_time: datetime,
    ) -> tuple[SimulatedFillV1, ...]:
        """Execute all queued session orders through shadow broker."""
        return self._broker.execute_session(
            session_key=session_key,
            open_prices=open_prices,
            eligibilities=eligibilities,
            execution_time=execution_time,
        )

    def submit_and_execute(
        self,
        order: SimulatedOrderV1,
        *,
        current_price: Decimal | None,
        open_price: Decimal | None,
        eligibility: MarketExecutionEligibilityV1 | None,
        execution_time: datetime,
    ) -> tuple[RiskVerdictV1, SimulatedFillV1 | None]:
        """Convenience single-step submit and execute helper.

        Returns (verdict, fill). If verdict is not ALLOWED, fill is None.
        """
        verdict = self.submit_order(
            order,
            current_price=current_price,
            evaluation_time=execution_time,
        )
        if verdict.status != RiskVerdictStatus.ALLOWED:
            return verdict, None

        fill = self.execute_order(
            order,
            open_price=open_price,
            eligibility=eligibility,
            execution_time=execution_time,
        )
        return verdict, fill
