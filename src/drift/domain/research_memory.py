"""Structured research memory domain models and ledger schemas (M6-1, Issue 205).

Provides immutable domain models for research hypothesis lifecycles,
trial performance tracking, failure postmortems, parameter search
space exploration, content hashing, and M0 research ledger persistence.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

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
from drift.serialization.canonical import content_hash

RESEARCH_MEMORY_SCHEMA_VERSION: Literal["1"] = "1"
TRIAL_EVENT_TYPE: NonBlankStr = "m6.trial.recorded"
POSTMORTEM_EVENT_TYPE: NonBlankStr = "m6.postmortem.recorded"
HYPOTHESIS_STATE_EVENT_TYPE: NonBlankStr = "m6.hypothesis_state.updated"


class HypothesisStatus(StrEnum):
    """The lifecycle state of a formal research hypothesis."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    VALIDATED = "validated"
    FALSIFIED = "falsified"
    ABANDONED = "abandoned"


class TrialOutcome(StrEnum):
    """Evaluation outcome classification for a research trial."""

    SUPERIOR = "superior"
    NEUTRAL = "neutral"
    INFERIOR = "inferior"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class FailureCategory(StrEnum):
    """Root cause categorization for rejected or failed experiments."""

    TURNOVER_DRAG = "turnover_drag"
    NEGATIVE_ALPHA = "negative_alpha"
    DRAWDOWN_BREACH = "drawdown_breach"
    CALIBRATION_FAILURE = "calibration_failure"
    OVERFITTING_REJECTION = "overfitting_rejection"
    DATA_DEFECT = "data_defect"
    EXECUTION_UNVIABLE = "execution_unviable"


class HypothesisLifecycleV1(FrozenModel):
    """Immutable hypothesis lifecycle state record and falsification evidence."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    hypothesis_id: UUID7
    status: HypothesisStatus
    falsification_evidence: tuple[SHA256Hash, ...] = ()
    validation_evidence: tuple[SHA256Hash, ...] = ()
    falsified_at: UTCDateTime | None = None
    validated_at: UTCDateTime | None = None
    notes: str | None = None
    updated_at: UTCDateTime
    lifecycle_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_lifecycle_integrity(self) -> Self:
        if self.status == HypothesisStatus.FALSIFIED:
            if self.falsified_at is None:
                raise ValueError("falsified status requires a falsified_at timestamp")
            if not self.falsification_evidence:
                raise ValueError("falsified status requires falsification evidence")
        elif self.status == HypothesisStatus.VALIDATED:
            if self.validated_at is None:
                raise ValueError("validated status requires a validated_at timestamp")
            if not self.validation_evidence:
                raise ValueError("validated status requires validation evidence")
        elif self.status in (HypothesisStatus.PROPOSED, HypothesisStatus.ACTIVE):
            if self.falsified_at is not None:
                raise ValueError(
                    "unfalsified hypothesis cannot have a falsified_at timestamp"
                )
            if self.validated_at is not None:
                raise ValueError(
                    "unvalidated hypothesis cannot have a validated_at timestamp"
                )

        if len(set(self.falsification_evidence)) != len(self.falsification_evidence):
            raise ValueError("falsification evidence hashes must be unique")
        if len(set(self.validation_evidence)) != len(self.validation_evidence):
            raise ValueError("validation evidence hashes must be unique")

        expected_hash = compute_hypothesis_lifecycle_hash(self)
        if self.lifecycle_hash != expected_hash:
            raise ValueError("hypothesis lifecycle hash mismatch")
        return self


class FailurePostmortemV1(FrozenModel):
    """Immutable postmortem detailing the root cause of an experiment failure."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    postmortem_id: UUID7
    experiment_id: UUID7
    run_id: UUID7
    trial_id: UUID7 | None = None
    failure_category: FailureCategory
    root_cause_summary: NonBlankStr
    falsified_hypotheses: tuple[UUID7, ...] = ()
    evidence_hashes: tuple[SHA256Hash, ...] = ()
    lessons_learned: NonBlankStr
    forbidden_variations: tuple[NonBlankStr, ...] = ()
    created_at: UTCDateTime
    postmortem_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_postmortem_integrity(self) -> Self:
        if len(set(self.falsified_hypotheses)) != len(self.falsified_hypotheses):
            raise ValueError("falsified hypotheses references must be unique")
        if len(set(self.evidence_hashes)) != len(self.evidence_hashes):
            raise ValueError("evidence hashes must be unique")
        if len(set(self.forbidden_variations)) != len(self.forbidden_variations):
            raise ValueError("forbidden variations must be unique")

        expected_hash = compute_failure_postmortem_hash(self)
        if self.postmortem_hash != expected_hash:
            raise ValueError("failure postmortem hash mismatch")
        return self


class ParameterSearchSpaceV1(FrozenModel):
    """Specification of hyperparameter exploration space and frontier coverage."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    search_space_id: UUID7
    strategy_type: NonBlankStr
    dimension_names: tuple[NonBlankStr, ...]
    evaluated_parameter_hashes: tuple[SHA256Hash, ...] = ()
    optimal_parameters_hash: SHA256Hash | None = None
    total_trials: int = Field(default=0, ge=0)
    exhaustion_fraction: Decimal = Field(
        default=Decimal("0.0"), ge=Decimal("0.0"), le=Decimal("1.0")
    )
    created_at: UTCDateTime
    search_space_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_search_space_integrity(self) -> Self:
        if not self.dimension_names:
            raise ValueError("dimension_names must not be empty")
        if len(set(self.dimension_names)) != len(self.dimension_names):
            raise ValueError("dimension_names must be unique")
        if len(set(self.evaluated_parameter_hashes)) != len(
            self.evaluated_parameter_hashes
        ):
            raise ValueError("evaluated parameter hashes must be unique")
        if self.total_trials < len(self.evaluated_parameter_hashes):
            raise ValueError(
                "total_trials cannot be less than evaluated_parameter_hashes count"
            )

        expected_hash = compute_parameter_search_space_hash(self)
        if self.search_space_hash != expected_hash:
            raise ValueError("parameter search space hash mismatch")
        return self


class ResearchTrialRecordV1(FrozenModel):
    """Immutable trial execution summary with parameters, metrics, and outcomes."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    trial_id: UUID7
    hypothesis_id: UUID7
    experiment_id: UUID7
    run_id: UUID7
    scorecard_id: UUID | None = None
    strategy_type: NonBlankStr
    parameters: ImmutableJSON
    parameters_hash: SHA256Hash
    headline_metrics: ImmutableJSON
    trial_outcome: TrialOutcome
    postmortem_id: UUID7 | None = None
    lane: Literal["exploratory", "promotion"] = "exploratory"
    created_at: UTCDateTime
    trial_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_trial_integrity(self) -> Self:
        expected_param_hash = content_hash(self.parameters)
        if self.parameters_hash != expected_param_hash:
            raise ValueError(
                "parameters_hash does not match canonical parameters content hash"
            )

        expected_trial_hash = compute_research_trial_hash(self)
        if self.trial_hash != expected_trial_hash:
            raise ValueError("research trial hash mismatch")
        return self


class TrialRecordedAuditEventPayloadV1(FrozenModel):
    """Payload for m6.trial.recorded audit events sealed into the ledger."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    trial: ResearchTrialRecordV1


class PostmortemRecordedAuditEventPayloadV1(FrozenModel):
    """Payload for m6.postmortem.recorded audit events sealed into the ledger."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    postmortem: FailurePostmortemV1


class HypothesisStateUpdatedAuditEventPayloadV1(FrozenModel):
    """Payload for m6.hypothesis_state.updated audit events sealed into the ledger."""

    schema_version: Literal["1"] = RESEARCH_MEMORY_SCHEMA_VERSION
    lifecycle: HypothesisLifecycleV1


# =========================================================================
# Hash Computation Functions
# =========================================================================


def compute_hypothesis_lifecycle_hash(
    lifecycle: HypothesisLifecycleV1 | Mapping[str, Any],
) -> str:
    """Compute canonical content hash for a hypothesis lifecycle record."""
    if isinstance(lifecycle, Mapping):
        data = {k: v for k, v in lifecycle.items() if k != "lifecycle_hash"}
    else:
        data = {
            k: v
            for k, v in lifecycle.model_dump(mode="python").items()
            if k != "lifecycle_hash"
        }
    return content_hash(data)


def compute_failure_postmortem_hash(
    postmortem: FailurePostmortemV1 | Mapping[str, Any],
) -> str:
    """Compute canonical content hash for a failure postmortem."""
    if isinstance(postmortem, Mapping):
        data = {k: v for k, v in postmortem.items() if k != "postmortem_hash"}
    else:
        data = {
            k: v
            for k, v in postmortem.model_dump(mode="python").items()
            if k != "postmortem_hash"
        }
    return content_hash(data)


def compute_parameter_search_space_hash(
    space: ParameterSearchSpaceV1 | Mapping[str, Any],
) -> str:
    """Compute canonical content hash for a parameter search space record."""
    if isinstance(space, Mapping):
        data = {k: v for k, v in space.items() if k != "search_space_hash"}
    else:
        data = {
            k: v
            for k, v in space.model_dump(mode="python").items()
            if k != "search_space_hash"
        }
    return content_hash(data)


def compute_research_trial_hash(
    trial: ResearchTrialRecordV1 | Mapping[str, Any],
) -> str:
    """Compute canonical content hash for a research trial record."""
    if isinstance(trial, Mapping):
        data = {k: v for k, v in trial.items() if k != "trial_hash"}
    else:
        data = {
            k: v
            for k, v in trial.model_dump(mode="python").items()
            if k != "trial_hash"
        }
    return content_hash(data)


# =========================================================================
# Builder Helper Functions
# =========================================================================


def build_hypothesis_lifecycle(
    *,
    hypothesis_id: UUID,
    status: HypothesisStatus,
    updated_at: UTCDateTime,
    falsification_evidence: tuple[SHA256Hash, ...] = (),
    validation_evidence: tuple[SHA256Hash, ...] = (),
    falsified_at: UTCDateTime | None = None,
    validated_at: UTCDateTime | None = None,
    notes: str | None = None,
) -> HypothesisLifecycleV1:
    """Construct an immutable HypothesisLifecycleV1 with canonical hash."""
    unsigned = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "hypothesis_id": hypothesis_id,
        "status": status,
        "falsification_evidence": falsification_evidence,
        "validation_evidence": validation_evidence,
        "falsified_at": falsified_at,
        "validated_at": validated_at,
        "notes": notes,
        "updated_at": updated_at,
    }
    h_hash = compute_hypothesis_lifecycle_hash(unsigned)
    return HypothesisLifecycleV1.model_validate(
        {
            **unsigned,
            "lifecycle_hash": h_hash,
        }
    )


def build_failure_postmortem(
    *,
    postmortem_id: UUID,
    experiment_id: UUID,
    run_id: UUID,
    failure_category: FailureCategory,
    root_cause_summary: NonBlankStr,
    lessons_learned: NonBlankStr,
    created_at: UTCDateTime,
    trial_id: UUID | None = None,
    falsified_hypotheses: tuple[UUID, ...] = (),
    evidence_hashes: tuple[SHA256Hash, ...] = (),
    forbidden_variations: tuple[NonBlankStr, ...] = (),
) -> FailurePostmortemV1:
    """Construct an immutable FailurePostmortemV1 with canonical hash."""
    unsigned = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "postmortem_id": postmortem_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "trial_id": trial_id,
        "failure_category": failure_category,
        "root_cause_summary": root_cause_summary,
        "falsified_hypotheses": falsified_hypotheses,
        "evidence_hashes": evidence_hashes,
        "lessons_learned": lessons_learned,
        "forbidden_variations": forbidden_variations,
        "created_at": created_at,
    }
    p_hash = compute_failure_postmortem_hash(unsigned)
    return FailurePostmortemV1.model_validate(
        {
            **unsigned,
            "postmortem_hash": p_hash,
        }
    )


def build_parameter_search_space(
    *,
    search_space_id: UUID,
    strategy_type: NonBlankStr,
    dimension_names: tuple[NonBlankStr, ...],
    created_at: UTCDateTime,
    evaluated_parameter_hashes: tuple[SHA256Hash, ...] = (),
    optimal_parameters_hash: SHA256Hash | None = None,
    total_trials: int = 0,
    exhaustion_fraction: Decimal = Decimal("0.0"),
) -> ParameterSearchSpaceV1:
    """Construct an immutable ParameterSearchSpaceV1 with canonical hash."""
    unsigned = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "search_space_id": search_space_id,
        "strategy_type": strategy_type,
        "dimension_names": dimension_names,
        "evaluated_parameter_hashes": evaluated_parameter_hashes,
        "optimal_parameters_hash": optimal_parameters_hash,
        "total_trials": total_trials,
        "exhaustion_fraction": exhaustion_fraction,
        "created_at": created_at,
    }
    s_hash = compute_parameter_search_space_hash(unsigned)
    return ParameterSearchSpaceV1.model_validate(
        {
            **unsigned,
            "search_space_hash": s_hash,
        }
    )


def build_research_trial_record(
    *,
    trial_id: UUID,
    hypothesis_id: UUID,
    experiment_id: UUID,
    run_id: UUID,
    strategy_type: NonBlankStr,
    parameters: Mapping[str, Any],
    headline_metrics: Mapping[str, Any],
    trial_outcome: TrialOutcome,
    created_at: UTCDateTime,
    scorecard_id: UUID | None = None,
    postmortem_id: UUID | None = None,
    lane: Literal["exploratory", "promotion"] = "exploratory",
) -> ResearchTrialRecordV1:
    """Construct an immutable ResearchTrialRecordV1 with canonical hash."""
    frozen_params = _freeze_json(dict(parameters))
    frozen_metrics = _freeze_json(dict(headline_metrics))
    p_hash = content_hash(frozen_params)
    unsigned = {
        "schema_version": RESEARCH_MEMORY_SCHEMA_VERSION,
        "trial_id": trial_id,
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "scorecard_id": scorecard_id,
        "strategy_type": strategy_type,
        "parameters": frozen_params,
        "parameters_hash": p_hash,
        "headline_metrics": frozen_metrics,
        "trial_outcome": trial_outcome,
        "postmortem_id": postmortem_id,
        "lane": lane,
        "created_at": created_at,
    }
    t_hash = compute_research_trial_hash(unsigned)
    return ResearchTrialRecordV1.model_validate(
        {
            **unsigned,
            "trial_hash": t_hash,
        }
    )
