"""Experiment specification and run provenance models."""

from enum import StrEnum

from pydantic import Field, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
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

    experiment_id: UUID7
    hypothesis_ids: tuple[UUID7, ...]
    strategy_reference: StrategyReference
    dataset_reference: DatasetReference
    parameters: ImmutableJSON
    benchmark: NonBlankStr
    evaluation_protocol: ImmutableJSON
    cost_assumptions: ImmutableJSON
    preregistered_metrics: tuple[NonBlankStr, ...]
    parent_experiment_ids: tuple[UUID7, ...] = ()
    created_at: UTCDateTime

    @model_validator(mode="after")
    def validate_lineage(self) -> ExperimentSpecification:
        if not self.hypothesis_ids:
            msg = "experiment hypothesis references must not be empty"
            raise ValueError(msg)
        if len(set(self.hypothesis_ids)) != len(self.hypothesis_ids):
            msg = "experiment hypothesis references must be unique"
            raise ValueError(msg)
        if not self.preregistered_metrics:
            msg = "preregistered metrics must not be empty"
            raise ValueError(msg)
        if len(set(self.preregistered_metrics)) != len(self.preregistered_metrics):
            msg = "preregistered metrics must be unique"
            raise ValueError(msg)
        if self.experiment_id in self.parent_experiment_ids:
            msg = "an experiment cannot reference itself as a parent"
            raise ValueError(msg)
        if len(set(self.parent_experiment_ids)) != len(self.parent_experiment_ids):
            msg = "parent experiment references must be unique"
            raise ValueError(msg)
        return self


class ExperimentRun(FrozenModel):
    """Immutable observed state for one execution of a specification."""

    run_id: UUID7
    experiment_id: UUID7
    started_at: UTCDateTime
    code_hash: SHA256Hash
    environment_hash: SHA256Hash
    dataset_hash: SHA256Hash
    parameters_hash: SHA256Hash
    status: ExperimentRunStatus
    metrics: ImmutableJSON = Field(default_factory=lambda: _freeze_json({}))
    artifact_references: tuple[ArtifactReference, ...] = ()
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
        artifact_ids = tuple(
            reference.artifact_id for reference in self.artifact_references
        )
        if len(set(artifact_ids)) != len(artifact_ids):
            msg = "experiment run artifact references must be unique"
            raise ValueError(msg)
        if (
            self.status is ExperimentRunStatus.COMPLETED
            and not self.artifact_references
        ):
            msg = "completed experiment runs require artifact references"
            raise ValueError(msg)
        return self
