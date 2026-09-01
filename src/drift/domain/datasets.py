"""Dataset provenance models."""

from enum import StrEnum

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
    _freeze_json,
)


class DatasetKind(StrEnum):
    """The role a dataset plays in a research experiment."""

    MARKET_DATA = "market_data"
    RESEARCH = "research"
    DERIVED = "derived"


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
    name: NonBlankStr
    version: NonBlankStr
    kind: DatasetKind
    content_hash: SHA256Hash
    temporal_coverage: TemporalCoverage
    fields: tuple[NonBlankStr, ...]
    created_at: UTCDateTime
    source_reference: NonBlankStr | None = None
    metadata: ImmutableJSON = Field(default_factory=lambda: _freeze_json({}))

    @model_validator(mode="after")
    def validate_fields(self) -> DatasetReference:
        if not self.fields:
            msg = "dataset fields must not be empty"
            raise ValueError(msg)
        if len(set(self.fields)) != len(self.fields):
            msg = "dataset fields must be unique"
            raise ValueError(msg)
        return self
