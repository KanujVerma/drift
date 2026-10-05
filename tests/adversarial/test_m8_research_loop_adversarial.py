"""Adversarial acceptance suite for Recursive R&D Loop (M8-5, Issue 239).

Attacks recursive loop controller boundary invariants across:
1. Runaway loop prevention under unconstrained proposals (strict max_iterations);
2. Circuit breaker triggering under persistent evaluation failures;
3. Memory feedback loop adaptation preventing repeated forbidden variations;
4. Cryptographic tamper detection on iteration records;
5. Cryptographic tamper detection on loop summaries;
6. Ledger archive resilience against corrupted or malformed audit payloads;
7. Target performance early-exit boundary conditions;
8. Full end-to-end ledger sealing and audit reconstruction immutability.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.mock_agent import DeterministicMockResearchAgent
from drift.agent.validator import ProposalValidator
from drift.domain.common import _freeze_json
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ProposalValidationStatus,
    ResearchContextPacketV1,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_loop import (
    ITERATION_EVENT_TYPE,
    LOOP_EVENT_TYPE,
    IterationStatus,
    LoopTerminationReason,
    ResearchIterationRecordV1,
    ResearchLoopSummaryV1,
    build_research_iteration_record,
    build_research_loop_config,
    build_research_loop_summary,
)
from drift.domain.research_memory import (
    FailureCategory,
    ParameterSearchSpaceV1,
    TrialOutcome,
    build_failure_postmortem,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.archive import ResearchLoopArchive
from drift.loop.evaluator_adapter import (
    DeterministicMockTrialEvaluator,
)
from drift.loop.recorder import ResearchLoopRecorder
from drift.loop.runner import ResearchLoopRunner
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import (
    ResearchMemoryRecorder,
    deterministic_memory_uuid7,
)

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
    ResearchLoopRecorder,
    ResearchLoopArchive,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    ledger = SQLiteLedger(tmp_path / "research_adv.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)
    validator = ProposalValidator(archive)
    agent = DeterministicMockResearchAgent(seed=42)
    loop_rec = ResearchLoopRecorder(ledger)
    loop_arc = ResearchLoopArchive(ledger)
    return (
        ledger,
        recorder,
        archive,
        synthesizer,
        validator,
        agent,
        loop_rec,
        loop_arc,
    )


# -----------------------------------------------------------------------------
# Vector 1: Runaway Loop Prevention
# -----------------------------------------------------------------------------


def test_adv_runaway_loop_prevention(tmp_path: Path) -> None:
    """Ensure unconstrained infinite proposals are halted at max_iterations."""
    (
        ledger,
        rec,
        arc,
        synth,
        val,
        _,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    # Adversarial agent that creates endless novel proposals
    class InfiniteProposalAgent:
        def __init__(self) -> None:
            self.counter = 0

        def generate_proposal(
            self,
            context: ResearchContextPacketV1,
            target_strategy_type: str,
            search_space: ParameterSearchSpaceV1 | None = None,
        ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]:
            self.counter += 1
            idx = self.counter
            hyp = build_hypothesis_proposal(
                proposal_id=deterministic_memory_uuid7(f"hyp:{idx}"),
                title=f"Infinite Hypothesis {idx}",
                economic_rationale=f"Rationale {idx} captures market dynamics",
                target_strategy_type=target_strategy_type,
                min_annualized_sharpe=Decimal("0.50"),
                max_drawdown_limit=Decimal("0.20"),
                max_turnover_limit=Decimal("5.0"),
                created_at=TIMESTAMP,
            )
            exp = build_experiment_specification_proposal(
                experiment_proposal_id=deterministic_memory_uuid7(f"exp:{idx}"),
                hypothesis_proposal_id=hyp.proposal_id,
                strategy_type=target_strategy_type,
                proposed_parameters={"lookback_sessions": 10 + idx},
                universe_id="sp500_historical_v1",
                rebalance_frequency="daily",
                created_at=TIMESTAMP,
            )
            return hyp, exp

    agent = InfiniteProposalAgent()
    evaluator = DeterministicMockTrialEvaluator(
        default_metrics={
            "annualized_sharpe": Decimal("1.20"),
            "max_drawdown": Decimal("0.08"),
            "annualized_turnover": Decimal("2.0"),
        }
    )

    max_limit = 7
    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=max_limit,
        max_consecutive_failures=20,
        stop_on_target_met=False,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synth,
        agent=agent,
        validator=val,
        evaluator=evaluator,
        recorder=rec,
        archive=arc,
        loop_recorder=loop_rec,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.MAX_ITERATIONS_REACHED
    assert summary.total_iterations == max_limit
    assert len(iterations) == max_limit
    assert agent.counter == max_limit


# -----------------------------------------------------------------------------
# Vector 2: Circuit Breaker on Consecutive Failures
# -----------------------------------------------------------------------------


def test_adv_circuit_breaker_consecutive_failures(tmp_path: Path) -> None:
    """Ensure persistent evaluation failures trigger circuit breaker."""
    (
        ledger,
        rec,
        arc,
        synth,
        val,
        agent,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    # Evaluator returning catastrophic metrics
    evaluator = DeterministicMockTrialEvaluator(
        default_metrics={
            "annualized_sharpe": Decimal("-0.80"),
            "max_drawdown": Decimal("0.65"),
            "annualized_turnover": Decimal("25.0"),
        }
    )

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=50,
        max_consecutive_failures=3,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synth,
        agent=agent,
        validator=val,
        evaluator=evaluator,
        recorder=rec,
        archive=arc,
        loop_recorder=loop_rec,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.MAX_CONSECUTIVE_FAILURES
    assert summary.total_iterations == 3
    assert summary.falsified_trials == 3
    assert len(iterations) == 3

    # Confirm postmortems were recorded in memory
    arc.refresh()
    assert len(arc._postmortems) == 3


# -----------------------------------------------------------------------------
# Vector 3: Memory Feedback Loop Prevents Repeated Forbidden Variations
# -----------------------------------------------------------------------------


def test_adv_memory_feedback_loop_prevents_repeats(tmp_path: Path) -> None:
    """Ensure ProposalValidator rejects repeated proposals with forbidden parameters."""
    (
        ledger,
        rec,
        arc,
        synth,
        val,
        _,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    # Pre-record a failure postmortem forbidding lookback_days
    pm = build_failure_postmortem(
        postmortem_id=deterministic_memory_uuid7("pm_turnover"),
        experiment_id=deterministic_memory_uuid7("exp_fail"),
        run_id=deterministic_memory_uuid7("run_fail"),
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Excessive turnover drag with short lookback",
        lessons_learned="Do not use lookback_days below 20",
        forbidden_variations=("lookback_days",),
        created_at=TIMESTAMP,
    )
    rec.record_postmortem(pm)
    arc.refresh()

    class StubbornAgent:
        def generate_proposal(
            self,
            context: ResearchContextPacketV1,
            target_strategy_type: str,
            search_space: ParameterSearchSpaceV1 | None = None,
        ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]:
            hyp = build_hypothesis_proposal(
                proposal_id=deterministic_memory_uuid7("hyp_stubborn"),
                title="Stubborn Hypothesis",
                economic_rationale="Testing forbidden variation persistence",
                target_strategy_type=target_strategy_type,
                min_annualized_sharpe=Decimal("0.50"),
                max_drawdown_limit=Decimal("0.20"),
                max_turnover_limit=Decimal("5.0"),
                created_at=TIMESTAMP,
            )
            exp = build_experiment_specification_proposal(
                experiment_proposal_id=deterministic_memory_uuid7("exp_stubborn"),
                hypothesis_proposal_id=hyp.proposal_id,
                strategy_type=target_strategy_type,
                proposed_parameters={"lookback_days": 10},
                universe_id="sp500_historical_v1",
                rebalance_frequency="daily",
                created_at=TIMESTAMP,
            )
            return hyp, exp

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=3,
        max_consecutive_failures=1,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synth,
        agent=StubbornAgent(),
        validator=val,
        evaluator=DeterministicMockTrialEvaluator(),
        recorder=rec,
        archive=arc,
        loop_recorder=loop_rec,
    )

    summary, iterations = runner.run(TIMESTAMP)

    # Immediately rejected on iteration 0 -> hits max_consecutive_failures (1)
    assert summary.termination_reason == LoopTerminationReason.MAX_CONSECUTIVE_FAILURES
    assert summary.rejected_proposals == 1
    assert len(iterations) == 1
    assert iterations[0].status == IterationStatus.PROPOSAL_REJECTED
    assert (
        iterations[0].validation_status
        == ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION
    )


# -----------------------------------------------------------------------------
# Vector 4: Tamper Detection on ResearchIterationRecordV1
# -----------------------------------------------------------------------------


def test_adv_iteration_record_tamper_detection() -> None:
    """Ensure any modification to iteration record payload breaks content hash."""
    rec = build_research_iteration_record(
        iteration_id=deterministic_memory_uuid7("iter:0"),
        loop_id=LOOP_ID_1,
        iteration_index=0,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        trial_outcome=TrialOutcome.SUPERIOR,
        annualized_sharpe=Decimal("1.25"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    # Attempt to tamper with annualized_sharpe
    tampered_data = rec.model_dump()
    tampered_data["annualized_sharpe"] = Decimal("3.50")

    with pytest.raises(ValidationError, match="hash mismatch"):
        ResearchIterationRecordV1.model_validate(tampered_data)


# -----------------------------------------------------------------------------
# Vector 5: Tamper Detection on ResearchLoopSummaryV1
# -----------------------------------------------------------------------------


def test_adv_loop_summary_tamper_detection() -> None:
    """Ensure any modification to summary payload breaks content hash."""
    summary = build_research_loop_summary(
        loop_id=LOOP_ID_1,
        config_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        termination_reason=LoopTerminationReason.MAX_ITERATIONS_REACHED,
        total_iterations=5,
        accepted_proposals=5,
        rejected_proposals=0,
        validated_trials=5,
        falsified_trials=0,
        best_trial_id=deterministic_memory_uuid7("trial:best"),
        best_annualized_sharpe=Decimal("1.30"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    # Attempt to tamper with best_annualized_sharpe
    tampered_data = summary.model_dump()
    tampered_data["best_annualized_sharpe"] = Decimal("5.00")

    with pytest.raises(ValidationError, match="hash mismatch"):
        ResearchLoopSummaryV1.model_validate(tampered_data)


# -----------------------------------------------------------------------------
# Vector 6: Archive Resilience Against Corrupted Audit Events
# -----------------------------------------------------------------------------


def test_adv_archive_corrupted_payload_resilience(tmp_path: Path) -> None:
    """Ensure archive skips corrupted or malformed audit payloads gracefully."""
    ledger = SQLiteLedger(tmp_path / "corrupted_audit.sqlite3")

    # Insert corrupted iteration event (malformed payload dict)
    bad_draft = AuditEventDraft(
        schema_version="1",
        event_id=deterministic_memory_uuid7("bad_ev_1"),
        event_type=ITERATION_EVENT_TYPE,
        timestamp=TIMESTAMP,
        entity_type="research_iteration",
        entity_id=deterministic_memory_uuid7("bad_ent_1"),
        payload=_freeze_json({"iteration": {"corrupted": "bad_data"}}),
        deduplication_key="bad:1",
    )
    ledger.append(bad_draft)

    # Insert corrupted loop event
    bad_draft_loop = AuditEventDraft(
        schema_version="1",
        event_id=deterministic_memory_uuid7("bad_ev_2"),
        event_type=LOOP_EVENT_TYPE,
        timestamp=TIMESTAMP,
        entity_type="research_loop",
        entity_id=deterministic_memory_uuid7("bad_ent_2"),
        payload=_freeze_json({"summary": "not_a_dict"}),
        deduplication_key="bad:2",
    )
    ledger.append(bad_draft_loop)

    archive = ResearchLoopArchive(ledger)
    # Must not crash, and should report 0 valid loops / iterations
    assert archive.total_completed_loops == 0
    assert archive.total_completed_iterations == 0

    # Now append a valid iteration
    rec = ResearchLoopRecorder(ledger)
    valid_it = build_research_iteration_record(
        iteration_id=deterministic_memory_uuid7("valid_it_1"),
        loop_id=LOOP_ID_1,
        iteration_index=0,
        status=IterationStatus.EVALUATION_COMPLETED,
        validation_status=ProposalValidationStatus.ACCEPTED,
        trial_outcome=TrialOutcome.SUPERIOR,
        annualized_sharpe=Decimal("1.10"),
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )
    rec.record_iteration(valid_it)

    archive.refresh()
    assert archive.total_completed_iterations == 1
    assert archive.list_iterations(LOOP_ID_1)[0] == valid_it


# -----------------------------------------------------------------------------
# Vector 7: Target Performance Early Exit
# -----------------------------------------------------------------------------


def test_adv_target_performance_early_exit_boundary(tmp_path: Path) -> None:
    """Ensure loop stops immediately once target performance metric is achieved."""
    (
        ledger,
        rec,
        arc,
        synth,
        val,
        agent,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    class StepwiseEvaluator:
        def __init__(self) -> None:
            self.call_count = 0

        def evaluate_experiment(
            self, experiment: ExperimentSpecificationProposalV1
        ) -> dict[str, Decimal]:
            self.call_count += 1
            # Step 1: 0.90, Step 2: 1.40, Step 3: 2.10 (exceeds target 2.0)
            sharpes = [Decimal("0.90"), Decimal("1.40"), Decimal("2.10")]
            sharpe = sharpes[min(self.call_count - 1, 2)]
            return {
                "annualized_sharpe": sharpe,
                "max_drawdown": Decimal("0.05"),
                "annualized_turnover": Decimal("1.5"),
            }

    evaluator = StepwiseEvaluator()
    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=10,
        target_annualized_sharpe=Decimal("2.00"),
        stop_on_target_met=True,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synth,
        agent=agent,
        validator=val,
        evaluator=evaluator,
        recorder=rec,
        archive=arc,
        loop_recorder=loop_rec,
    )

    summary, iterations = runner.run(TIMESTAMP)

    assert summary.termination_reason == LoopTerminationReason.TARGET_PERFORMANCE_MET
    assert summary.total_iterations == 3
    assert summary.best_annualized_sharpe == Decimal("2.10")
    assert len(iterations) == 3
    assert evaluator.call_count == 3


# -----------------------------------------------------------------------------
# Vector 8: Full End-to-End Immutability and Reconstruction
# -----------------------------------------------------------------------------


def test_adv_loop_audit_ledger_immutability(tmp_path: Path) -> None:
    """Verify bit-for-bit historical reconstruction through SQLite ledger archive."""
    (
        ledger,
        rec,
        arc,
        synth,
        val,
        agent,
        loop_rec,
        loop_arc,
    ) = _build_test_env(tmp_path)

    evaluator = DeterministicMockTrialEvaluator(
        default_metrics={
            "annualized_sharpe": Decimal("1.45"),
            "max_drawdown": Decimal("0.06"),
            "annualized_turnover": Decimal("2.2"),
        }
    )

    config = build_research_loop_config(
        loop_id=LOOP_ID_1,
        target_strategy_type="b4_momentum",
        max_iterations=4,
        created_at=TIMESTAMP,
    )

    runner = ResearchLoopRunner(
        config=config,
        synthesizer=synth,
        agent=agent,
        validator=val,
        evaluator=evaluator,
        recorder=rec,
        archive=arc,
        loop_recorder=loop_rec,
    )

    summary, iterations = runner.run(TIMESTAMP)

    loop_arc.refresh()
    assert loop_arc.total_completed_loops == 1
    assert loop_arc.total_completed_iterations == 4

    reconstructed_summary = loop_arc.get_loop_summary(LOOP_ID_1)
    assert reconstructed_summary == summary

    reconstructed_iterations = loop_arc.list_iterations(LOOP_ID_1)
    assert reconstructed_iterations == iterations
