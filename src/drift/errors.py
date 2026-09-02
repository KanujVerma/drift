class DriftError(Exception):
    """Base class for all Drift errors."""


class LedgerIntegrityError(DriftError):
    """Raised when ledger state fails an integrity check."""


class LedgerMutationError(DriftError):
    """Raised when a ledger mutation is invalid."""


class DuplicateEventError(LedgerMutationError):
    """Raised when an event identifier is already present."""


class LedgerCursorError(DriftError):
    """Raised when a ledger query cursor is invalid or cannot be resolved."""


class CanonicalSerializationError(DriftError):
    """Raised when a value cannot be represented canonically."""


class ArtifactResolutionError(DriftError):
    """Raised when an artifact cannot be safely resolved."""


class ArtifactIntegrityError(DriftError):
    """Raised when resolved artifact bytes fail an integrity check."""
