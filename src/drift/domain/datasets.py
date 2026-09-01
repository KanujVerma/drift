"""Dataset provenance models."""

from pydantic import model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)


class TemporalCoverage(FrozenModel):
    """Inclusive UTC interval represented by a dataset."""

    started_at: UTCDateTime
    ended_at: UTCDateTime

    @model_validator(mode="after")
    def validate_range(self) -> TemporalCoverage:
        if self.ended_at < self.started_at:
            msg = "temporal coverage cannot end before it starts"
            raise ValueError(msg)
        return self


class DatasetReference(FrozenModel):
    """Compact immutable provenance for an input dataset."""

    dataset_id: UUID7
    dataset_version: NonBlankStr
    schema_version: NonBlankStr
    content_hash: SHA256Hash
    created_at: UTCDateTime
    source: NonBlankStr
    temporal_coverage: TemporalCoverage
    point_in_time_policy: NonBlankStr
    corporate_action_policy: NonBlankStr
    availability_timestamp_policy: NonBlankStr
    manifest_reference: ArtifactReference
