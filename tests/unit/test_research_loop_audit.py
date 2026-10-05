"""Unit tests for recursive R&D loop audit events and archive (M8-4, #237)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.mock_agent import DeterministicMockResearchAgent
from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import ProposalValidationStatus
from drift.domain.research_loop import (
    IterationStatus,
    LoopTerminationReason,
    build_research_iteration_record,
    build_research_loop_config,
    build_research_loop_summary,
)
from drift.domain.research_memory import TrialOutcome
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.archive import ResearchLoopArchive
from drift.loop.evaluator_adapter import DeterministicMockTrialEvaluator
from drift.loop.recorder import ResearchLoopRecorder
from drift.loop.runner import ResearchLoopRunner
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
LOOP_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd91")
LOOP_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd92")
TRIAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd93")
TRIAL_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd94")


def test_record_iteration_and_query_archive(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_audit.sqlite3")
    recorder = ResearchLoopRecorder(ledger)
    archive = ResearchLoopArchive(ledger)

    assert archive.total_completed_iterations == 0

    it0 = build_research_iteration_record(
        iteration_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd80"),
        loop_id=LOOP_ID_1,
        iteration_index=0,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        trial_outcome=TrialOutcome.SUPERIOR,
        annualized_sharpe=Decimal("1.10"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )
    it1 = build_research_iteration_record(
        iteration_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd81"),
        loop_id=LOOP_ID_1,
        iteration_index=1,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        trial_outcome=TrialOutcome.SUPERIOR,
        annualized_sharpe=Decimal("1.35"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    recorder.record_iteration(it0)
    recorder.record_iteration(it1)

    archive.refresh()
    assert archive.total_completed_iterations == 2

    iterations = archive.list_iterations(LOOP_ID_1)
    assert len(iterations) == 2
    assert iterations[0].iteration_index == 0
    assert iterations[1].iteration_index == 1
    assert iterations[0] == it0
    assert iterations[1] == it1

    # Empty for unknown loop
    assert archive.list_iterations(LOOP_ID_2) == ()


def test_record_loop_summary_and_query_archive(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_audit.sqlite3")
    recorder = ResearchLoopRecorder(ledger)
    archive = ResearchLoopArchive(ledger)

    assert archive.total_completed_loops == 0

    summary1 = build_research_loop_summary(
        loop_id=LOOP_ID_1,
        config_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        termination_reason=LoopTerminationReason.MAX_ITERATIONS_REACHED,
        total_iterations=5,
        accepted_proposals=5,
        rejected_proposals=0,
        validated_trials=5,
        falsified_trials=0,
        best_trial_id=TRIAL_ID_1,
        best_annualized_sharpe=Decimal("1.40"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )
    summary2 = build_research_loop_summary(
        loop_id=LOOP_ID_2,
        config_hash="fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
        termination_reason=LoopTerminationReason.TARGET_PERFORMANCE_MET,
        total_iterations=3,
        accepted_proposals=3,
        rejected_proposals=0,
        validated_trials=3,
        falsified_trials=0,
        best_trial_id=TRIAL_ID_2,
        best_annualized_sharpe=Decimal("1.80"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    recorder.record_loop_summary(summary1)
    recorder.record_loop_summary(summary2)

    archive.refresh()
    assert archive.total_completed_loops == 2

    assert archive.get_loop_summary(LOOP_ID_1) == summary1
    assert archive.get_loop_summary(LOOP_ID_2) == summary2
    assert (
        archive.get_loop_summary(UUID("018f3a5b-6c7d-7890-8123-456789abcd00")) is None
    )

    summaries = archive.list_loop_summaries()
    assert len(summaries) == 2

    best_trials = archive.get_best_trials_across_loops()
    assert TRIAL_ID_1 in best_trials
    assert TRIAL_ID_2 in best_trials


def test_runner_with_loop_recorder_end_to_end(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research_runner_audit.sqlite3")
    mem_recorder = ResearchMemoryRecorder(ledger)
    mem_archive = ResearchMemoryArchive(ledger)
    loop_recorder = ResearchLoopRecorder(ledger)
    loop_archive = ResearchLoopArchive(ledger)

    synthesizer = ResearchContextSynthesizer(mem_archive)
    validator = ProposalValidator(mem_archive)
    agent = DeterministicMockResearchAgent(seed=42)
    evaluator = DeterministicMockTrialEvaluator(
        default_metrics={
            "annualized_sharpe": Decimal("1.20"),
            "max_drawdown": Decimal("0.08"),
            "annualized_turnover": Decimal("2.50"),
        }
    )

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=3,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=evaluator,
        recorder=mem_recorder,
        archive=mem_archive,
        loop_recorder=loop_recorder,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert len(iterations) == 3
    assert summary.total_iterations == 3

    # Verify everything was sealed into the ledger and reconstructed by archive
    loop_archive.refresh()
    assert loop_archive.total_completed_loops == 1
    assert loop_archive.total_completed_iterations == 3
    assert loop_archive.get_loop_summary(LOOP_ID_1) == summary

    archived_iters = loop_archive.list_iterations(LOOP_ID_1)
    assert len(archived_iters) == 3
    for exp_it, act_it in zip(iterations, archived_iters, strict=True):
        assert exp_it == act_it
