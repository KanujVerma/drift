"""Unit tests for recursive R&D loop controller and runner (M8-3, Issue 235)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.mock_agent import DeterministicMockResearchAgent
from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
)
from drift.domain.research_loop import (
    IterationStatus,
    LoopTerminationReason,
    ResearchIterationRecordV1,
    ResearchLoopSummaryV1,
    build_research_loop_config,
)
from drift.domain.research_memory import (
    FailureCategory,
    TrialOutcome,
    build_failure_postmortem,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.evaluator_adapter import (
    DeterministicMockTrialEvaluator,
)
from drift.loop.runner import ResearchLoopRunner
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
LOOP_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd90")


def _build_test_env(
    tmp_path: Path,
) -> tuple[
    SQLiteLedger,
    ResearchMemoryRecorder,
    ResearchMemoryArchive,
    ResearchContextSynthesizer,
    ProposalValidator,
    DeterministicMockResearchAgent,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger = SQLiteLedger(tmp_path / "research_loop.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)
    validator = ProposalValidator(archive)
    agent = DeterministicMockResearchAgent(seed=42)
    return ledger, recorder, archive, synthesizer, validator, agent


def test_runner_terminates_on_max_iterations(tmp_path: Path) -> None:
    ledger, recorder, archive, synthesizer, validator, agent = _build_test_env(tmp_path)
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
        max_consecutive_failures=5,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=evaluator,
        recorder=recorder,
        archive=archive,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.MAX_ITERATIONS_REACHED
    assert summary.total_iterations == 3
    assert summary.accepted_proposals == 3
    assert summary.rejected_proposals == 0
    assert summary.validated_trials == 3
    assert summary.falsified_trials == 0
    assert summary.best_annualized_sharpe == Decimal("1.20")
    assert summary.best_trial_id is not None
    assert len(iterations) == 3

    for idx, it in enumerate(iterations):
        assert it.iteration_index == idx
        assert it.status == IterationStatus.EVALUATION_COMPLETED
        assert it.trial_outcome == TrialOutcome.SUPERIOR

    # Verify trials sealed in archive
    archive.refresh()
    assert archive.get_trial_count() == 3


def test_runner_circuit_breaker_on_consecutive_failures(tmp_path: Path) -> None:
    ledger, recorder, archive, synthesizer, validator, agent = _build_test_env(tmp_path)
    # Evaluator returns failing metrics (turnover too high, Sharpe too low)
    evaluator = DeterministicMockTrialEvaluator(
        default_metrics={
            "annualized_sharpe": Decimal("0.10"),
            "max_drawdown": Decimal("0.35"),
            "annualized_turnover": Decimal("12.00"),
        }
    )

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=10,
        max_consecutive_failures=2,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=evaluator,
        recorder=recorder,
        archive=archive,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.MAX_CONSECUTIVE_FAILURES
    assert summary.total_iterations == 2
    assert summary.falsified_trials == 2
    assert summary.validated_trials == 0
    assert len(iterations) == 2

    # Check postmortems generated
    archive.refresh()
    assert len(archive._postmortems) == 2
    for it in iterations:
        assert it.trial_outcome == TrialOutcome.FAILED
        assert it.failure_category == FailureCategory.CALIBRATION_FAILURE
        assert it.postmortem_id is not None


def test_runner_terminates_on_target_performance_met(tmp_path: Path) -> None:
    ledger, recorder, archive, synthesizer, validator, agent = _build_test_env(tmp_path)

    class DynamicEvaluator:
        def __init__(self) -> None:
            self.calls = 0

        def evaluate_experiment(
            self, experiment: ExperimentSpecificationProposalV1
        ) -> dict[str, Decimal]:
            self.calls += 1
            # Iteration 0 returns 1.10, iteration 1 returns 1.65 (beats target 1.50)
            sharpe = Decimal("1.10") if self.calls == 1 else Decimal("1.65")
            return {
                "annualized_sharpe": sharpe,
                "max_drawdown": Decimal("0.05"),
                "annualized_turnover": Decimal("2.0"),
            }

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=5,
        max_consecutive_failures=3,
        target_annualized_sharpe=Decimal("1.50"),
        stop_on_target_met=True,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=DynamicEvaluator(),
        recorder=recorder,
        archive=archive,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.TARGET_PERFORMANCE_MET
    assert summary.total_iterations == 2
    assert summary.best_annualized_sharpe == Decimal("1.65")
    assert len(iterations) == 2


def test_runner_handles_proposal_rejection(tmp_path: Path) -> None:
    ledger, recorder, archive, synthesizer, validator, agent = _build_test_env(tmp_path)
    evaluator = DeterministicMockTrialEvaluator()

    # Pre-record a postmortem that forbids lookback_sessions
    pm = build_failure_postmortem(
        postmortem_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd20"),
        experiment_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd21"),
        run_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd22"),
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Turnover drag failure",
        lessons_learned="Forbidden parameter lookback_sessions",
        forbidden_variations=("lookback_sessions",),
        created_at=TIMESTAMP,
    )
    recorder.record_postmortem(pm)
    archive.refresh()

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=3,
        max_consecutive_failures=2,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synthesizer,
        agent=agent,
        validator=validator,
        evaluator=evaluator,
        recorder=recorder,
        archive=archive,
    )

    summary, iterations = runner.run(TIMESTAMP)

    # Proposals will be rejected because mock agent proposes lookback_sessions
    assert summary.termination_reason == LoopTerminationReason.MAX_CONSECUTIVE_FAILURES
    assert summary.rejected_proposals == 2
    assert summary.accepted_proposals == 0
    assert len(iterations) == 2
    for it in iterations:
        assert it.status == IterationStatus.PROPOSAL_REJECTED
        assert len(it.rejection_reasons) > 0


def test_runner_reproducibility(tmp_path: Path) -> None:
    def _run_once(
        dir_name: str,
    ) -> tuple[ResearchLoopSummaryV1, tuple[ResearchIterationRecordV1, ...]]:
        ledger, recorder, archive, synth, val, agent = _build_test_env(
            tmp_path / dir_name
        )
        evaluator = DeterministicMockTrialEvaluator(
            default_metrics={
                "annualized_sharpe": Decimal("1.25"),
                "max_drawdown": Decimal("0.07"),
                "annualized_turnover": Decimal("2.10"),
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
            synthesizer=synth,
            agent=agent,
            validator=val,
            evaluator=evaluator,
            recorder=recorder,
            archive=archive,
        )
        return runner.run(TIMESTAMP)

    summary1, iters1 = _run_once("run1")
    summary2, iters2 = _run_once("run2")

    assert summary1 == summary2
    assert iters1 == iters2
