"""Real-World Paper / Shadow Validation module (M15).

Provides market feed processing, execution drift tracking, and shadow validation
harnesses decoupled from live capital deployment.
"""

from drift.validation.engine import (
    RiskHaltValidationError,
    ShadowValidationEngine,
    ValidationEngineError,
)
from drift.validation.feed import (
    FeedEmptyError,
    FeedError,
    MarketDataStreamerProtocol,
    MockMarketDataStreamer,
    NonMonotonicTimestampError,
)
from drift.validation.journal import (
    DuplicateValidationRecordError,
    PersistentShadowValidationJournal,
    ValidationAppendOnlyViolationError,
    ValidationJournalError,
)

__all__ = [
    "DuplicateValidationRecordError",
    "FeedEmptyError",
    "FeedError",
    "MarketDataStreamerProtocol",
    "MockMarketDataStreamer",
    "NonMonotonicTimestampError",
    "PersistentShadowValidationJournal",
    "RiskHaltValidationError",
    "ShadowValidationEngine",
    "ValidationAppendOnlyViolationError",
    "ValidationEngineError",
    "ValidationJournalError",
]
