"""Unit tests for research agent protocol, mock adapter, and runner (M7-4)."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.mock_agent import DeterministicMockResearchAgent
from drift.agent.runner import ResearchAgentRunner
from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import (
    ProposalValidationStatus,
    ResearchAgentRole,
    build_research_context_packet,
)
from drift.domain.research_memory import (
    FailureCategory,
    HypothesisStatus,
    build_failure_postmortem,
    build_parameter_search_space,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.hypothesis import HypothesisManager
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")


def test_mock_agent_reproducibility() -> None:
    context = build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        total_trial_count=10,
        active_hypotheses_count=2,
        falsified_hypotheses_count=4,
        created_at=TIMESTAMP,
    )

    agent1 = DeterministicMockResearchAgent(seed=42)
    agent2 = DeterministicMockResearchAgent(seed=42)

    hyp1, exp1 = agent1.generate_proposal(context, "b4_momentum")
    hyp2, exp2 = agent2.generate_proposal(context, "b4_momentum")

    assert hyp1 == hyp2
    assert exp1 == exp2
    assert hyp1.proposal_hash == hyp2.proposal_hash
    assert exp1.parameters_hash == exp2.parameters_hash


def test_mock_agent_adheres_to_search_space_dimensions() -> None:
    context = build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        total_trial_count=10,
        active_hypotheses_count=2,
        falsified_hypotheses_count=4,
        created_at=TIMESTAMP,
    )
    space = build_parameter_search_space(
        search_space_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd10"),
        strategy_type="b4_momentum",
        dimension_names=("lookback_sessions", "holding_sessions", "decay_rate"),
        created_at=TIMESTAMP,
    )

    agent = DeterministicMockResearchAgent(seed=123)
    hyp, exp = agent.generate_proposal(context, "b4_momentum", search_space=space)

    assert set(exp.proposed_parameters.keys()) == set(space.dimension_names)


def test_runner_accepted_cycle_with_hypothesis_manager(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    hyp_manager = HypothesisManager(recorder)

    synthesizer = ResearchContextSynthesizer(archive)
    validator = ProposalValidator(archive)
    agent = DeterministicMockResearchAgent(seed=777)

    runner = ResearchAgentRunner(
        synthesizer=synthesizer,
        validator=validator,
        agent=agent,
        hypothesis_manager=hyp_manager,
    )

    hyp, exp, val_res = runner.run_cycle(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        target_strategy_type="b4_momentum",
        as_of_time=TIMESTAMP,
    )

    assert val_res.is_accepted is True
    assert val_res.status == ProposalValidationStatus.ACCEPTED

    # Verify registered in hypothesis manager
    state = hyp_manager.get_state(hyp.proposal_id)
    assert state.status == HypothesisStatus.PROPOSED
    assert state.hypothesis_id == hyp.proposal_id


def test_runner_rejected_cycle_not_registered(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    # Record postmortem blocking lookback
    pm = build_failure_postmortem(
        postmortem_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd20"),
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Turnover drag failure",
        lessons_learned="Avoid short lookbacks",
        forbidden_variations=("lookback_sessions",),
        created_at=TIMESTAMP,
    )
    recorder.record_postmortem(pm)

    archive = ResearchMemoryArchive(ledger)
    hyp_manager = HypothesisManager(recorder)

    synthesizer = ResearchContextSynthesizer(archive)
    validator = ProposalValidator(archive)
    agent = DeterministicMockResearchAgent(seed=999)

    runner = ResearchAgentRunner(
        synthesizer=synthesizer,
        validator=validator,
        agent=agent,
        hypothesis_manager=hyp_manager,
    )

    hyp, exp, val_res = runner.run_cycle(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        target_strategy_type="b4_momentum",
        as_of_time=TIMESTAMP,
    )

    # Must be rejected due to forbidden variation
    assert val_res.is_accepted is False
    assert val_res.status == ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION

    # Must NOT be registered in hypothesis manager
    assert hyp.proposal_id not in hyp_manager._lifecycles
