"""Recursive research and development loop domain models and schemas (M8-1, Issue 231).

Provides immutable domain models for automated research iteration cycles,
loop configuration and termination bounds, single iteration audit records,
overall loop outcome summaries, and M0 ledger audit event schemas.
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
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.research_agent import ProposalValidationStatus
from drift.domain.research_memory import FailureCategory, TrialOutcome
from drift.serialization.canonical import content_hash

RESEARCH_LOOP_SCHEMA_VERSION: Literal["1"] = "1"
ITERATION_EVENT_TYPE: NonBlankStr = "m8.iteration.completed"
LOOP_EVENT_TYPE: NonBlankStr = "m8.loop.completed"


class IterationStatus(StrEnum):
    """Execution status for a single R&D loop iteration."""

    PROPOSAL_ACCEPTED = "proposal_accepted"
    PROPOSAL_REJECTED = "proposal_rejected"
    EVALUATION_COMPLETED = "evaluation_completed"
    EVALUATION_FAILED = "evaluation_failed"


class LoopTerminationReason(StrEnum):
    """Terminal stop condition triggering loop completion."""

    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    MAX_CONSECUTIVE_FAILURES = "max_consecutive_failures"
    TARGET_PERFORMANCE_MET = "target_performance_met"
    SEARCH_SPACE_EXHAUSTED = "search_space_exhausted"
    UNEXPECTED_ERROR = "unexpected_error"


# =========================================================================
# Hash Computation Functions
# =========================================================================


def compute_research_loop_config_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for a ResearchLoopConfigV1."""
    d = dict(unsigned)
    d.pop("config_hash", None)
    return content_hash(d)


def compute_research_iteration_record_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash for a ResearchIterationRecordV1."""
    d = dict(unsigned)
    d.pop("iteration_hash", None)
    return content_hash(d)


def compute_research_loop_summary_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash for a ResearchLoopSummaryV1."""
    d = dict(unsigned)
    d.pop("summary_hash", None)
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class ResearchLoopConfigV1(FrozenModel):
    """Configuration governing recursive research loop execution."""

    schema_version: Literal["1"] = RESEARCH_LOOP_SCHEMA_VERSION
    loop_id: UUID7
    target_strategy_type: NonBlankStr
    max_iterations: int = Field(default=10, ge=1, le=100)
    max_consecutive_failures: int = Field(default=5, ge=1, le=20)
    target_annualized_sharpe: Decimal | None = None
    target_exhaustion_fraction: Decimal = Field(
        default=Decimal("0.90"), ge=Decimal("0.1"), le=Decimal("1.0")
    )
    stop_on_target_met: bool = True
    created_at: UTCDateTime
    config_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_config_integrity(self) -> Self:
        if (
            self.target_annualized_sharpe is not None
            and self.target_annualized_sharpe <= Decimal("0")
        ):
            raise ValueError("target_annualized_sharpe must be strictly positive")
        expected_hash = compute_research_loop_config_hash(
            self.model_dump(mode="python")
        )
        if self.config_hash != expected_hash:
            raise ValueError("research loop config hash mismatch")
        return self


class ResearchIterationRecordV1(FrozenModel):
    """Detailed immutable execution record of a single R&D loop iteration."""

    schema_version: Literal["1"] = RESEARCH_LOOP_SCHEMA_VERSION
    iteration_id: UUID7
    loop_id: UUID7
    iteration_index: int = Field(ge=0)
    status: IterationStatus
    validation_status: ProposalValidationStatus
    started_at: UTCDateTime
    completed_at: UTCDateTime
    hypothesis_proposal_id: UUID7 | None = None
    experiment_proposal_id: UUID7 | None = None
    trial_outcome: TrialOutcome | None = None
    annualized_sharpe: Decimal | None = None
    max_drawdown: Decimal | None = None
    annualized_turnover: Decimal | None = None
    failure_category: FailureCategory | None = None
    postmortem_id: UUID7 | None = None
    rejection_reasons: tuple[str, ...] = ()
    iteration_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_iteration_integrity(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        expected_hash = compute_research_iteration_record_hash(
            self.model_dump(mode="python")
        )
        if self.iteration_hash != expected_hash:
            raise ValueError("research iteration record hash mismatch")
        return self


class ResearchLoopSummaryV1(FrozenModel):
    """Final outcome summary of a recursive R&D loop execution run."""

    schema_version: Literal["1"] = RESEARCH_LOOP_SCHEMA_VERSION
    loop_id: UUID7
    config_hash: SHA256Hash
    termination_reason: LoopTerminationReason
    total_iterations: int = Field(ge=0)
    accepted_proposals: int = Field(ge=0)
    rejected_proposals: int = Field(ge=0)
    validated_trials: int = Field(ge=0)
    falsified_trials: int = Field(ge=0)
    started_at: UTCDateTime
    completed_at: UTCDateTime
    best_trial_id: UUID7 | None = None
    best_annualized_sharpe: Decimal | None = None
    final_exhaustion_fraction: Decimal = Decimal("0.0")
    summary_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_summary_integrity(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if self.total_iterations != (self.accepted_proposals + self.rejected_proposals):
            raise ValueError(
                "total_iterations must equal sum of accepted and rejected proposals"
            )
        if self.validated_trials + self.falsified_trials > self.accepted_proposals:
            raise ValueError("evaluated trials cannot exceed accepted proposal count")
        expected_hash = compute_research_loop_summary_hash(
            self.model_dump(mode="python")
        )
        if self.summary_hash != expected_hash:
            raise ValueError("research loop summary hash mismatch")
        return self


# =========================================================================
# Ledger Audit Event Payloads
# =========================================================================


class IterationCompletedAuditEventPayloadV1(FrozenModel):
    """Payload for m8.iteration.completed audit events sealed into the ledger."""

    schema_version: Literal["1"] = RESEARCH_LOOP_SCHEMA_VERSION
    iteration: ResearchIterationRecordV1


class LoopCompletedAuditEventPayloadV1(FrozenModel):
    """Payload for m8.loop.completed audit events sealed into the ledger."""

    schema_version: Literal["1"] = RESEARCH_LOOP_SCHEMA_VERSION
    summary: ResearchLoopSummaryV1


# =========================================================================
# Builder Helper Functions
# =========================================================================


def build_research_loop_config(
    *,
    loop_id: UUID,
    target_strategy_type: NonBlankStr,
    created_at: UTCDateTime,
    max_iterations: int = 10,
    max_consecutive_failures: int = 5,
    target_annualized_sharpe: Decimal | None = None,
    target_exhaustion_fraction: Decimal = Decimal("0.90"),
    stop_on_target_met: bool = True,
) -> ResearchLoopConfigV1:
    """Construct an immutable ResearchLoopConfigV1 with computed hash."""
    unsigned = {
        "schema_version": RESEARCH_LOOP_SCHEMA_VERSION,
        "loop_id": loop_id,
        "target_strategy_type": target_strategy_type,
        "max_iterations": max_iterations,
        "max_consecutive_failures": max_consecutive_failures,
        "target_annualized_sharpe": target_annualized_sharpe,
        "target_exhaustion_fraction": target_exhaustion_fraction,
        "stop_on_target_met": stop_on_target_met,
        "created_at": created_at,
    }
    c_hash = compute_research_loop_config_hash(unsigned)
    return ResearchLoopConfigV1.model_validate(
        {
            **unsigned,
            "config_hash": c_hash,
        }
    )


def build_research_iteration_record(
    *,
    iteration_id: UUID,
    loop_id: UUID,
    iteration_index: int,
    status: IterationStatus,
    validation_status: ProposalValidationStatus,
    started_at: UTCDateTime,
    completed_at: UTCDateTime,
    hypothesis_proposal_id: UUID | None = None,
    experiment_proposal_id: UUID | None = None,
    trial_outcome: TrialOutcome | None = None,
    annualized_sharpe: Decimal | None = None,
    max_drawdown: Decimal | None = None,
    annualized_turnover: Decimal | None = None,
    failure_category: FailureCategory | None = None,
    postmortem_id: UUID | None = None,
    rejection_reasons: tuple[str, ...] = (),
) -> ResearchIterationRecordV1:
    """Construct an immutable ResearchIterationRecordV1 with computed hash."""
    unsigned = {
        "schema_version": RESEARCH_LOOP_SCHEMA_VERSION,
        "iteration_id": iteration_id,
        "loop_id": loop_id,
        "iteration_index": iteration_index,
        "status": status,
        "validation_status": validation_status,
        "hypothesis_proposal_id": hypothesis_proposal_id,
        "experiment_proposal_id": experiment_proposal_id,
        "trial_outcome": trial_outcome,
        "annualized_sharpe": annualized_sharpe,
        "max_drawdown": max_drawdown,
        "annualized_turnover": annualized_turnover,
        "failure_category": failure_category,
        "postmortem_id": postmortem_id,
        "rejection_reasons": rejection_reasons,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    i_hash = compute_research_iteration_record_hash(unsigned)
    return ResearchIterationRecordV1.model_validate(
        {
            **unsigned,
            "iteration_hash": i_hash,
        }
    )


def build_research_loop_summary(
    *,
    loop_id: UUID,
    config_hash: SHA256Hash,
    termination_reason: LoopTerminationReason,
    total_iterations: int,
    accepted_proposals: int,
    rejected_proposals: int,
    validated_trials: int,
    falsified_trials: int,
    started_at: UTCDateTime,
    completed_at: UTCDateTime,
    best_trial_id: UUID | None = None,
    best_annualized_sharpe: Decimal | None = None,
    final_exhaustion_fraction: Decimal = Decimal("0.0"),
) -> ResearchLoopSummaryV1:
    """Construct an immutable ResearchLoopSummaryV1 with computed hash."""
    unsigned = {
        "schema_version": RESEARCH_LOOP_SCHEMA_VERSION,
        "loop_id": loop_id,
        "config_hash": config_hash,
        "termination_reason": termination_reason,
        "total_iterations": total_iterations,
        "accepted_proposals": accepted_proposals,
        "rejected_proposals": rejected_proposals,
        "validated_trials": validated_trials,
        "falsified_trials": falsified_trials,
        "best_trial_id": best_trial_id,
        "best_annualized_sharpe": best_annualized_sharpe,
        "final_exhaustion_fraction": final_exhaustion_fraction,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    s_hash = compute_research_loop_summary_hash(unsigned)
    return ResearchLoopSummaryV1.model_validate(
        {
            **unsigned,
            "summary_hash": s_hash,
        }
    )
