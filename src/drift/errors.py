class DriftError(Exception):
    """Base class for all Drift errors."""


class LedgerIntegrityError(DriftError):
    """Raised when ledger state fails an integrity check."""


class LedgerMutationError(DriftError):
    """Raised when a ledger mutation is invalid."""


class DuplicateEventError(LedgerMutationError):
    """Raised when an event identifier is already present."""
