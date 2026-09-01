"""Strategy provenance models, without strategy behavior."""

from enum import StrEnum

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime


class StrategyArtifactKind(StrEnum):
    """The immutable form of a captured strategy artifact."""

    SOURCE = "source"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"


class StrategyReference(FrozenModel):
    """Versioned metadata identifying a research strategy."""

    strategy_id: UUID7
    name: NonBlankStr
    version: NonBlankStr
    description: NonBlankStr
    created_at: UTCDateTime


class StrategyArtifact(FrozenModel):
    """A content-addressed artifact associated with a strategy reference."""

    artifact_id: UUID7
    strategy_id: UUID7
    kind: StrategyArtifactKind
    content_hash: SHA256Hash
    location: NonBlankStr
    created_at: UTCDateTime
