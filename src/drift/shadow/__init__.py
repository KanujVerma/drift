"""Shadow Broker module (M12).

Provides broker simulation, order execution against unadjusted source prices,
append-only SQLite journal, and accounting reconciliation against
M2 PortfolioAccountingKernel.
"""

from drift.shadow.journal import (
    DuplicateJournalRecordError,
    JournalAppendOnlyViolationError,
    ShadowJournalError,
    SimulationExecutionJournal,
)

__all__ = [
    "DuplicateJournalRecordError",
    "JournalAppendOnlyViolationError",
    "ShadowJournalError",
    "SimulationExecutionJournal",
]
