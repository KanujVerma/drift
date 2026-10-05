"""Broker-Neutral Execution module (M14).

Provides abstract execution protocols, persistent order intent journals, and
broker-neutral execution routing.
"""

from drift.execution.adapter import (
    BrokerAdapterProtocol,
    MockBrokerAdapter,
)
from drift.execution.journal import (
    DuplicateIntentRecordError,
    ExecutionJournalError,
    IntentAppendOnlyViolationError,
    PersistentOrderIntentJournal,
)
from drift.execution.router import (
    BrokerNeutralExecutionRouter,
    DuplicateClientOrderIdError,
    RouterExecutionError,
    UnknownIntentError,
)

__all__ = [
    "BrokerAdapterProtocol",
    "BrokerNeutralExecutionRouter",
    "DuplicateClientOrderIdError",
    "DuplicateIntentRecordError",
    "ExecutionJournalError",
    "IntentAppendOnlyViolationError",
    "MockBrokerAdapter",
    "PersistentOrderIntentJournal",
    "RouterExecutionError",
    "UnknownIntentError",
]
