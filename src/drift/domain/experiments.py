"""Experiment specification and run provenance models."""

from enum import StrEnum

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    UTCDateTime,
    _freeze_json,
)
from drift.domain.datasets import DatasetReference
from drift.domain.strategies import StrategyReference


class ExperimentRunStatus(StrEnum):
    """The terminal or nonterminal status of an experiment run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExperimentSpecification(FrozenModel):
    """Pre-run, immutable definition of a research experiment."""

    specification_id: UUID7
    hypothesis_id: UUID7
    dataset_references: tuple[DatasetReference, ...]
    strategy_reference: StrategyReference
    parameters: ImmutableJSON
    evaluation_protocol: ImmutableJSON
    cost_assumptions: ImmutableJSON
    created_at: UTCDateTime

    @model_validator(mode="after")
    def validate_dataset_references(self) -> ExperimentSpecification:
        if not self.dataset_references:
            msg = "experiment dataset references must not be empty"
            raise ValueError(msg)
        dataset_ids = tuple(
            reference.dataset_id for reference in self.dataset_references
        )
        if len(set(dataset_ids)) != len(dataset_ids):
            msg = "experiment dataset references must be unique"
            raise ValueError(msg)
        return self


class ExperimentRun(FrozenModel):
    """Immutable observed state for one execution of a specification."""

    run_id: UUID7
    specification_id: UUID7
    status: ExperimentRunStatus
    started_at: UTCDateTime
    parameters: ImmutableJSON = Field(default_factory=lambda: _freeze_json({}))
    metrics: ImmutableJSON = Field(default_factory=lambda: _freeze_json({}))
    completed_at: UTCDateTime | None = None
    error_details: NonBlankStr | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> ExperimentRun:
        terminal_statuses = {
            ExperimentRunStatus.COMPLETED,
            ExperimentRunStatus.FAILED,
            ExperimentRunStatus.CANCELLED,
        }
        if self.status in terminal_statuses and self.completed_at is None:
            msg = "terminal experiment runs require a completion time"
            raise ValueError(msg)
        if self.status not in terminal_statuses and self.completed_at is not None:
            msg = "nonterminal experiment runs cannot have a completion time"
            raise ValueError(msg)
        if self.completed_at is not None and self.completed_at < self.started_at:
            msg = "completion time cannot precede start time"
            raise ValueError(msg)
        if self.status is ExperimentRunStatus.FAILED and self.error_details is None:
            msg = "failed experiment runs require error details"
            raise ValueError(msg)
        if (
            self.status is not ExperimentRunStatus.FAILED
            and self.error_details is not None
        ):
            msg = "only failed experiment runs may include error details"
            raise ValueError(msg)
        return self
