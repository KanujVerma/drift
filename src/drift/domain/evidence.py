"""Evidence records that connect experiment runs to retained artifacts."""

from enum import StrEnum

from pydantic import model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, UTCDateTime


class EvidenceStatus(StrEnum):
    """The explicitly recorded current status of evidence."""

    TENTATIVE = "tentative"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    DEPRECATED = "deprecated"


EvidenceVerdict = EvidenceStatus


class EvidenceType(StrEnum):
    """The source class for an evidence record."""

    EXPERIMENTAL = "experimental"
    OBSERVATIONAL = "observational"
    REVIEW = "review"


class ConfidenceState(StrEnum):
    """The stated confidence level for evidence, not an automatic judgment."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceRecord(FrozenModel):
    """Immutable evidence, including the artifact lineage behind its verdict."""

    evidence_id: UUID7
    created_at: UTCDateTime
    claim: NonBlankStr
    evidence_type: EvidenceType
    supporting_run_ids: tuple[UUID7, ...] = ()
    contradicting_run_ids: tuple[UUID7, ...] = ()
    confidence_state: ConfidenceState
    scope: NonBlankStr
    supersedes: UUID7 | None = None
    status: EvidenceStatus

    @model_validator(mode="after")
    def validate_run_lineage(self) -> EvidenceRecord:
        if not self.supporting_run_ids and not self.contradicting_run_ids:
            msg = "evidence must reference at least one experiment run"
            raise ValueError(msg)
        if len(set(self.supporting_run_ids)) != len(self.supporting_run_ids):
            msg = "supporting run references must be unique"
            raise ValueError(msg)
        if len(set(self.contradicting_run_ids)) != len(self.contradicting_run_ids):
            msg = "contradicting run references must be unique"
            raise ValueError(msg)
        if set(self.supporting_run_ids).intersection(self.contradicting_run_ids):
            msg = "supporting and contradicting run references must not overlap"
            raise ValueError(msg)
        if self.supersedes == self.evidence_id:
            msg = "an evidence record cannot supersede itself"
            raise ValueError(msg)
        return self
