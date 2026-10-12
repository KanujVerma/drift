"""Robinhood account snapshot and position synchronizer (M16-3).

Provides automated synchronization of Robinhood brokerage accounts, positions,
and portfolio reconciliation against Drift's internal books per ADR 0011.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from drift.adapters.robinhood.adapter import RobinhoodAgenticAdapter
from drift.domain.common import FrozenModel, NonBlankStr, UTCDateTime
from drift.domain.execution import (
    BrokerAccountSnapshotV1,
    BrokerPositionSnapshotV1,
)

__all__ = [
    "PositionDiscrepancyV1",
    "ReconciliationReportV1",
    "RobinhoodPortfolioSynchronizer",
]


class PositionDiscrepancyV1(FrozenModel):
    """Discrepancy between internal expected position and broker actual position."""

    security_id: UUID
    symbol: str | None = None
    expected_quantity: int
    actual_quantity: int
    difference_quantity: int


class ReconciliationReportV1(FrozenModel):
    """Result of portfolio position reconciliation between Drift and Robinhood."""

    account_id: NonBlankStr
    synchronized_at: UTCDateTime
    is_reconciled: bool
    discrepancies: tuple[PositionDiscrepancyV1, ...] = ()
    account_snapshot: BrokerAccountSnapshotV1
    position_snapshots: tuple[BrokerPositionSnapshotV1, ...] = ()


class RobinhoodPortfolioSynchronizer:
    """Synchronizes and reconciles broker balances and positions with internal books."""

    def __init__(self, *, adapter: RobinhoodAgenticAdapter) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> RobinhoodAgenticAdapter:
        """Underlying Robinhood broker adapter."""
        return self._adapter

    def sync_account(self) -> BrokerAccountSnapshotV1:
        """Obtain latest account snapshot from broker."""
        return self._adapter.get_account_snapshot()

    def sync_positions(self) -> tuple[BrokerPositionSnapshotV1, ...]:
        """Obtain latest position snapshots from broker."""
        return self._adapter.get_positions()

    def reconcile(
        self,
        expected_positions: Mapping[UUID, int],
    ) -> ReconciliationReportV1:
        """Reconcile expected internal book positions against actual broker holdings."""
        now = datetime.now(UTC)
        acct_snap = self.sync_account()
        pos_snaps = self.sync_positions()

        actual_map: dict[UUID, int] = {
            snap.security_id: snap.quantity for snap in pos_snaps
        }

        all_sec_ids = sorted(
            set(expected_positions.keys()) | set(actual_map.keys()),
            key=lambda uid: str(uid),
        )

        discrepancies: list[PositionDiscrepancyV1] = []
        for sec_id in all_sec_ids:
            exp_qty = expected_positions.get(sec_id, 0)
            act_qty = actual_map.get(sec_id, 0)

            if exp_qty != act_qty:
                sym = self._adapter.config.symbol_map.get(sec_id)
                diff = act_qty - exp_qty
                discrepancies.append(
                    PositionDiscrepancyV1(
                        security_id=sec_id,
                        symbol=sym,
                        expected_quantity=exp_qty,
                        actual_quantity=act_qty,
                        difference_quantity=diff,
                    )
                )

        return ReconciliationReportV1(
            account_id=acct_snap.account_id,
            synchronized_at=now,
            is_reconciled=(len(discrepancies) == 0),
            discrepancies=tuple(discrepancies),
            account_snapshot=acct_snap,
            position_snapshots=pos_snaps,
        )
