"""Broker accounting reconciliation and journal replay engine (M12-4).

Reconciles broker execution state against M2 PortfolioStateV2, records
deterministic ExecutionReconciliationV1 snapshots into SimulationExecutionJournal,
and verifies replay projection bit-exactness.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

from drift.domain.evaluator_clock import SessionClockV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    ExecutionReconciliationV1,
    build_execution_reconciliation,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.shadow.broker import ShadowBroker, ShadowBrokerError

__all__ = [
    "ReconciliationMismatchError",
    "ShadowBrokerReconciler",
]


class ReconciliationMismatchError(ShadowBrokerError):
    """Raised when an execution reconciliation detects a state mismatch."""


class ShadowBrokerReconciler:
    """Reconciles broker execution state with M2 portfolio accounting kernel."""

    def __init__(
        self,
        *,
        broker: ShadowBroker,
    ) -> None:
        self._broker = broker

    @property
    def broker(self) -> ShadowBroker:
        """Underlying shadow broker instance."""
        return self._broker

    def reconcile_session(
        self,
        *,
        session_key: SessionKeyV1,
        reconciled_at: datetime,
        fail_fast: bool = False,
    ) -> ExecutionReconciliationV1:
        """Reconcile broker state for session and record snapshot to journal."""
        discrepancies: list[str] = []
        kernel_state = self._broker.kernel.state
        journal = self._broker.journal

        # 1. Verify session consistency
        if kernel_state.session_key != session_key:
            discrepancies.append(
                f"session_key_mismatch: kernel at {kernel_state.session_key}, "
                f"reconciliation requested for {session_key}"
            )

        # 2. Check cash balance sanity
        if kernel_state.cash_balance < Decimal("0"):
            discrepancies.append(
                f"negative_cash_balance: {kernel_state.cash_balance} < 0"
            )

        # 4. Check holdings consistency (long-only, positive quantities)
        holdings = kernel_state.holdings
        for holding in holdings:
            if holding.quantity <= 0:
                discrepancies.append(
                    f"non_positive_holding: security {holding.security_id} "
                    f"quantity {holding.quantity} <= 0"
                )

        status: Any = "matched" if not discrepancies else "mismatched"

        rec = build_execution_reconciliation(
            reconciliation_id=uuid7(),
            session_key=session_key,
            reconciled_at=reconciled_at,
            cash=kernel_state.cash_balance,
            holdings_count=len(holdings),
            status=status,
            discrepancies=tuple(discrepancies),
        )

        journal.record_reconciliation(rec)

        if fail_fast and discrepancies:
            raise ReconciliationMismatchError(
                f"reconciliation failed with {len(discrepancies)} discrepancies: "
                f"{'; '.join(discrepancies)}"
            )

        return rec

    def verify_replay_projection(
        self,
        *,
        initial_state: PortfolioStateV2,
        session_clock: SessionClockV1,
    ) -> bool:
        """Reconstruct state from journal replay and verify exact match."""
        replay_kernel = PortfolioAccountingKernel(
            initial_state,
            session_clock=session_clock,
        )

        for session in session_clock.sessions:
            if replay_kernel.state.session_key != session.session_key:
                replay_kernel.advance_session(session.session_key)

            fills = self._broker.journal.replay_session_fills(session.session_key)
            for fill in fills:
                replay_kernel.apply_fill(fill)

        live_state = self._broker.kernel.state
        replayed_state = replay_kernel.state

        return (
            replayed_state.cash_balance == live_state.cash_balance
            and replayed_state.holdings == live_state.holdings
            and replayed_state.cumulative_transaction_costs
            == live_state.cumulative_transaction_costs
        )
