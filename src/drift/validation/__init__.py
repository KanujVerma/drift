"""Real-World Paper / Shadow Validation module (M15).

Provides market feed processing, execution drift tracking, and shadow validation
harnesses decoupled from live capital deployment.
"""

from drift.validation.journal import (
    DuplicateValidationRecordError,
    PersistentShadowValidationJournal,
    ValidationAppendOnlyViolationError,
    ValidationJournalError,
)

__all__ = [
    "DuplicateValidationRecordError",
    "PersistentShadowValidationJournal",
    "ValidationAppendOnlyViolationError",
    "ValidationJournalError",
]
