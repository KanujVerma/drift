"""Unit tests for research loop domain models and schemas (M8-1, Issue 231)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.research_agent import ProposalValidationStatus
from drift.domain.research_loop import (
    ITERATION_EVENT_TYPE,
    LOOP_EVENT_TYPE,
    RESEARCH_LOOP_SCHEMA_VERSION,
    IterationCompletedAuditEventPayloadV1,
    IterationStatus,
    LoopCompletedAuditEventPayloadV1,
    LoopTerminationReason,
    ResearchLoopConfigV1,
    build_research_iteration_record,
    build_research_loop_config,
    build_research_loop_summary,
)
from drift.domain.research_memory import TrialOutcome

TIMESTAMP_START = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
TIMESTAMP_END = TIMESTAMP_START + timedelta(seconds=120)

LOOP_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
ITERATION_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")


def test_research_loop_config_construction() -> None:
    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=15,
        max_consecutive_failures=3,
        target_annualized_sharpe=Decimal("1.20"),
        target_exhaustion_fraction=Decimal("0.85"),
        stop_on_target_met=True,
        created_at=TIMESTAMP_START,
    )

    assert config.schema_version == RESEARCH_LOOP_SCHEMA_VERSION
    assert config.loop_id == LOOP_ID_1
    assert config.target_strategy_type == "b4_momentum"
    assert config.max_iterations == 15
    assert config.max_consecutive_failures == 3
    assert config.target_annualized_sharpe == Decimal("1.20")
    assert config.target_exhaustion_fraction == Decimal("0.85")
    assert config.stop_on_target_met is True
    assert len(config.config_hash) == 64


def test_research_loop_config_validation_errors() -> None:
    # Non-positive target Sharpe
    with pytest.raises(
        ValidationError, match="target_annualized_sharpe must be strictly positive"
    ):
        build_research_loop_config(
            loop_id=LOOP_ID_1,
            target_strategy_type="b4_momentum",
            target_annualized_sharpe=Decimal("-0.5"),
            created_at=TIMESTAMP_START,
        )

    # Hash mismatch tampering
    valid_cfg = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        created_at=TIMESTAMP_START,
    )
    raw = valid_cfg.model_dump(mode="python")
    first_char = raw["config_hash"][0]
    flipped = "0" if first_char != "0" else "1"
    raw["config_hash"] = flipped + raw["config_hash"][1:]

    with pytest.raises(ValidationError, match="research loop config hash mismatch"):
        ResearchLoopConfigV1.model_validate(raw)


def test_research_iteration_record_construction_accepted() -> None:
    record = build_research_iteration_record(
        iteration_id=ITERATION_ID_1,
        loop_id=LOOP_ID_1,
        iteration_index=0,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        hypothesis_proposal_id=HYPOTHESIS_ID_1,
        experiment_proposal_id=EXPERIMENT_ID_1,
        trial_outcome=TrialOutcome.SUPERIOR,
        annualized_sharpe=Decimal("1.35"),
        max_drawdown=Decimal("0.12"),
        annualized_turnover=Decimal("4.2"),
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )

    assert record.schema_version == RESEARCH_LOOP_SCHEMA_VERSION
    assert record.iteration_id == ITERATION_ID_1
    assert record.iteration_index == 0
    assert record.status == IterationStatus.EVALUATION_COMPLETED
    assert record.trial_outcome == TrialOutcome.SUPERIOR
    assert record.annualized_sharpe == Decimal("1.35")
    assert len(record.iteration_hash) == 64


def test_research_iteration_record_construction_rejected() -> None:
    record = build_research_iteration_record(
        iteration_id=ITERATION_ID_1,
        loop_id=LOOP_ID_1,
        iteration_index=1,
        status=IterationStatus.PROPOSAL_REJECTED,
        validation_status=ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION,
        rejection_reasons=("lookback=15 violates diagnosed failure",),
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )

    assert record.status == IterationStatus.PROPOSAL_REJECTED
    assert (
        record.validation_status
        == ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION
    )
    assert len(record.rejection_reasons) == 1
    assert record.trial_outcome is None


def test_research_iteration_record_time_inversion_rejected() -> None:
    with pytest.raises(ValidationError, match="completed_at cannot precede started_at"):
        build_research_iteration_record(
            iteration_id=ITERATION_ID_1,
            loop_id=LOOP_ID_1,
            iteration_index=0,
            status=IterationStatus.PROPOSAL_ACCEPTED,
            validation_status=ProposalValidationStatus.ACCEPTED,
            started_at=TIMESTAMP_END,
            completed_at=TIMESTAMP_START,
        )


def test_research_loop_summary_construction() -> None:
    summary = build_research_loop_summary(
        loop_id=LOOP_ID_1,
        config_hash="a" * 64,
        termination_reason=LoopTerminationReason.TARGET_PERFORMANCE_MET,
        total_iterations=10,
        accepted_proposals=8,
        rejected_proposals=2,
        validated_trials=5,
        falsified_trials=3,
        best_trial_id=ITERATION_ID_1,
        best_annualized_sharpe=Decimal("1.42"),
        final_exhaustion_fraction=Decimal("0.75"),
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )

    assert summary.schema_version == RESEARCH_LOOP_SCHEMA_VERSION
    assert summary.loop_id == LOOP_ID_1
    assert summary.termination_reason == LoopTerminationReason.TARGET_PERFORMANCE_MET
    assert summary.total_iterations == 10
    assert summary.accepted_proposals == 8
    assert summary.rejected_proposals == 2
    assert summary.validated_trials == 5
    assert summary.best_annualized_sharpe == Decimal("1.42")
    assert len(summary.summary_hash) == 64


def test_research_loop_summary_validation_invariants() -> None:
    # total_iterations mismatch
    with pytest.raises(
        ValidationError,
        match="total_iterations must equal sum of accepted and rejected",
    ):
        build_research_loop_summary(
            loop_id=LOOP_ID_1,
            config_hash="a" * 64,
            termination_reason=LoopTerminationReason.MAX_ITERATIONS_REACHED,
            total_iterations=10,
            accepted_proposals=5,
            rejected_proposals=2,  # sum is 7 != 10
            validated_trials=3,
            falsified_trials=2,
            started_at=TIMESTAMP_START,
            completed_at=TIMESTAMP_END,
        )

    # evaluated trials exceed accepted proposals
    with pytest.raises(
        ValidationError, match="evaluated trials cannot exceed accepted proposal"
    ):
        build_research_loop_summary(
            loop_id=LOOP_ID_1,
            config_hash="a" * 64,
            termination_reason=LoopTerminationReason.MAX_ITERATIONS_REACHED,
            total_iterations=10,
            accepted_proposals=5,
            rejected_proposals=5,
            validated_trials=4,
            falsified_trials=3,  # 4 + 3 = 7 > 5 accepted
            started_at=TIMESTAMP_START,
            completed_at=TIMESTAMP_END,
        )


def test_audit_event_payloads() -> None:
    record = build_research_iteration_record(
        iteration_id=ITERATION_ID_1,
        loop_id=LOOP_ID_1,
        iteration_index=0,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )
    it_payload = IterationCompletedAuditEventPayloadV1(iteration=record)
    assert it_payload.schema_version == RESEARCH_LOOP_SCHEMA_VERSION
    assert it_payload.iteration == record
    assert ITERATION_EVENT_TYPE == "m8.iteration.completed"

    summary = build_research_loop_summary(
        loop_id=LOOP_ID_1,
        config_hash="a" * 64,
        termination_reason=LoopTerminationReason.MAX_ITERATIONS_REACHED,
        total_iterations=5,
        accepted_proposals=5,
        rejected_proposals=0,
        validated_trials=2,
        falsified_trials=3,
        started_at=TIMESTAMP_START,
        completed_at=TIMESTAMP_END,
    )
    loop_payload = LoopCompletedAuditEventPayloadV1(summary=summary)
    assert loop_payload.schema_version == RESEARCH_LOOP_SCHEMA_VERSION
    assert loop_payload.summary == summary
    assert LOOP_EVENT_TYPE == "m8.loop.completed"
