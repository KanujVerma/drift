"""Hypothesis provenance models."""

from enum import StrEnum

from pydantic import model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, UTCDateTime


class HypothesisStatus(StrEnum):
    """The current research disposition of a hypothesis."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    ARCHIVED = "archived"


class Hypothesis(FrozenModel):
    """An immutable research claim and its explicit parent lineage."""

    hypothesis_id: UUID7
    title: NonBlankStr
    statement: NonBlankStr
    rationale: NonBlankStr
    created_at: UTCDateTime
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    parent_hypothesis_ids: tuple[UUID7, ...] = ()
    tags: tuple[NonBlankStr, ...] = ()

    @model_validator(mode="after")
    def validate_lineage(self) -> Hypothesis:
        if self.hypothesis_id in self.parent_hypothesis_ids:
            msg = "a hypothesis cannot reference itself as a parent"
            raise ValueError(msg)
        if len(set(self.parent_hypothesis_ids)) != len(self.parent_hypothesis_ids):
            msg = "parent hypothesis references must be unique"
            raise ValueError(msg)
        if len(set(self.tags)) != len(self.tags):
            msg = "hypothesis tags must be unique"
            raise ValueError(msg)
        return self
