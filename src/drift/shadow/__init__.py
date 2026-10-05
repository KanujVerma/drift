"""Shadow Broker module (M12).

Provides broker simulation, order execution against unadjusted source prices,
append-only SQLite journal, and accounting reconciliation against
M2 PortfolioAccountingKernel.
"""

from drift.shadow.broker import (
    OrderExecutionError,
    ShadowBroker,
    ShadowBrokerError,
)
from drift.shadow.journal import (
    DuplicateJournalRecordError,
    JournalAppendOnlyViolationError,
    ShadowJournalError,
    SimulationExecutionJournal,
)
from drift.shadow.reconciler import (
    ReconciliationMismatchError,
    ShadowBrokerReconciler,
)

__all__ = [
    "DuplicateJournalRecordError",
    "JournalAppendOnlyViolationError",
    "OrderExecutionError",
    "ReconciliationMismatchError",
    "ShadowBroker",
    "ShadowBrokerError",
    "ShadowBrokerReconciler",
    "ShadowJournalError",
    "SimulationExecutionJournal",
]
