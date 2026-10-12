"""Bounded Autonomy and Continuous Improvement subsystem (M18+).

Provides dynamic allocation governors, audited evidence ledgers, and
autonomous improvement loops per ADR 0011, ADR 0013, and ADR 0014.
"""

from drift.autonomy.governor import AllocationExpansionGovernor
from drift.autonomy.ledger import (
    GovernanceAppendOnlyViolationError,
    GovernanceChainIntegrityError,
    GovernanceLedgerError,
    PersistentEvidenceLedger,
)
from drift.autonomy.orchestrator import BoundedAutonomyOrchestrator

__all__ = [
    "AllocationExpansionGovernor",
    "BoundedAutonomyOrchestrator",
    "GovernanceAppendOnlyViolationError",
    "GovernanceChainIntegrityError",
    "GovernanceLedgerError",
    "PersistentEvidenceLedger",
]
