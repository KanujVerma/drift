"""Evidence records that connect experiment runs to retained artifacts."""

from enum import StrEnum

from pydantic import model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, UTCDateTime


class EvidenceVerdict(StrEnum):
    """How a record bears on its associated hypothesis."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    INCONCLUSIVE = "inconclusive"


class EvidenceRecord(FrozenModel):
    """Immutable evidence, including the artifact lineage behind its verdict."""

    evidence_id: UUID7
    experiment_run_id: UUID7
    verdict: EvidenceVerdict
    summary: NonBlankStr
    artifact_references: tuple[ArtifactReference, ...]
    recorded_at: UTCDateTime

    @model_validator(mode="after")
    def validate_artifact_references(self) -> EvidenceRecord:
        if not self.artifact_references:
            msg = "evidence artifact references must not be empty"
            raise ValueError(msg)
        artifact_ids = tuple(
            reference.artifact_id for reference in self.artifact_references
        )
        if len(set(artifact_ids)) != len(artifact_ids):
            msg = "evidence artifact references must be unique"
            raise ValueError(msg)
        return self
