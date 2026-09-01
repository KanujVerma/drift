"""Hypothesis provenance models."""

from pydantic import model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, UTCDateTime


class Hypothesis(FrozenModel):
    """An immutable research claim and its explicit parent lineage."""

    hypothesis_id: UUID7
    created_at: UTCDateTime
    title: NonBlankStr
    statement: NonBlankStr
    mechanism: NonBlankStr
    expected_direction: NonBlankStr
    universe: NonBlankStr
    horizon: NonBlankStr
    falsification_criteria: NonBlankStr
    parent_hypothesis_ids: tuple[UUID7, ...] = ()
    author_type: NonBlankStr
    author_version: NonBlankStr
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
