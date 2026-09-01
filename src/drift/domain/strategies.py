"""Strategy provenance models, without strategy behavior."""

from enum import StrEnum

from pydantic import model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime


class StrategyArtifactStatus(StrEnum):
    """The review state recorded for a research strategy artifact."""

    RESEARCH = "research"
    CHALLENGER = "challenger"
    APPROVED = "approved"
    RETIRED = "retired"


class StrategyReference(FrozenModel):
    """A versioned, content-addressed strategy reference for an experiment."""

    strategy_id: UUID7
    strategy_version: NonBlankStr
    code_hash: SHA256Hash
    artifact_reference: ArtifactReference


class StrategyArtifact(FrozenModel):
    """Candidate strategy provenance, without implementation behavior."""

    strategy_id: UUID7
    strategy_version: NonBlankStr
    code_hash: SHA256Hash
    created_at: UTCDateTime
    parent_strategy_version: NonBlankStr | None = None
    hypothesis_ids: tuple[UUID7, ...]
    artifact_reference: ArtifactReference
    status: StrategyArtifactStatus

    @model_validator(mode="after")
    def validate_hypothesis_ids(self) -> StrategyArtifact:
        if self.parent_strategy_version == self.strategy_version:
            msg = "a strategy version cannot be its own parent"
            raise ValueError(msg)
        if not self.hypothesis_ids:
            msg = "strategy hypothesis references must not be empty"
            raise ValueError(msg)
        if len(set(self.hypothesis_ids)) != len(self.hypothesis_ids):
            msg = "strategy hypothesis references must be unique"
            raise ValueError(msg)
        return self
