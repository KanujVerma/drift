"""Generic immutable artifact references."""

from enum import StrEnum

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash


class ArtifactKind(StrEnum):
    """Artifact categories that evidence can reference."""

    DATASET = "dataset"
    STRATEGY = "strategy"
    RESULT = "result"
    LOG = "log"
    OTHER = "other"


class ArtifactReference(FrozenModel):
    """A compact content-addressed pointer to a retained artifact."""

    artifact_id: UUID7
    kind: ArtifactKind
    content_hash: SHA256Hash
    location: NonBlankStr
