"""Adversarial acceptance suite for First AI Research Agent (M7-6, Issue 227).

Attacks research agent boundary invariants across:
1. Hallucinatory criteria injection (domain model level and validator level);
2. Forbidden parameter variation evasion;
3. Duplicate parameter trial re-evaluation attempts;
4. Circular lineage and missing ancestor injection;
5. Context packet cryptographic hash tampering;
6. Parameter search space bounds breach (missing and unexpected dimensions);
7. Multiple-testing trial count (K) suppression attempts;
8. Untrusted agent firewall and execution separation enforcement.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.gemini_agent import GeminiResearchAgent
from drift.agent.runner import ResearchAgentRunner
from drift.agent.validator import ProposalValidator
from drift.domain.research_agent import (
    ProposalValidationStatus,
    ResearchAgentRole,
    ResearchContextPacketV1,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
    build_research_context_packet,
)
from drift.domain.research_memory import (
    FailureCategory,
    ParameterSearchSpaceV1,
    TrialOutcome,
    build_failure_postmortem,
    build_parameter_search_space,
    build_research_trial_record,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import ResearchMemoryRecorder, deterministic_memory_uuid7

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
PROPOSAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")


def _build_test_search_space() -> ParameterSearchSpaceV1:
    return build_parameter_search_space(
        search_space_id=deterministic_memory_uuid7("test_space"),
        strategy_type="b4_momentum",
        dimension_names=("lookback_days", "rebalance_freq"),
        created_at=TIMESTAMP,
    )


# =========================================================================
# Attack 1: Hallucinatory Criteria Injection
# =========================================================================


def test_adversarial_hallucinatory_criteria_model_tier_rejection() -> None:
    # Model tier rejects non-positive Sharpe
    with pytest.raises(
        ValidationError, match="min_annualized_sharpe must be strictly positive"
    ):
        build_hypothesis_proposal(
            proposal_id=PROPOSAL_ID_1,
            title="Negative Sharpe",
            economic_rationale="Rationale",
            target_strategy_type="b4_momentum",
            min_annualized_sharpe=Decimal("-0.5"),
            max_drawdown_limit=Decimal("0.20"),
            max_turnover_limit=Decimal("5.0"),
            created_at=TIMESTAMP,
        )

    # Model tier rejects drawdown > 1.0 (100% loss)
    with pytest.raises(
        ValidationError,
        match="max_drawdown_limit must be strictly between 0 and 1.0",
    ):
        build_hypothesis_proposal(
            proposal_id=PROPOSAL_ID_1,
            title="Excessive Drawdown",
            economic_rationale="Rationale",
            target_strategy_type="b4_momentum",
            min_annualized_sharpe=Decimal("0.5"),
            max_drawdown_limit=Decimal("1.50"),
            max_turnover_limit=Decimal("5.0"),
            created_at=TIMESTAMP,
        )

    # Model tier rejects non-positive turnover
    with pytest.raises(
        ValidationError, match="max_turnover_limit must be strictly positive"
    ):
        build_hypothesis_proposal(
            proposal_id=PROPOSAL_ID_1,
            title="Negative Turnover",
            economic_rationale="Rationale",
            target_strategy_type="b4_momentum",
            min_annualized_sharpe=Decimal("0.5"),
            max_drawdown_limit=Decimal("0.20"),
            max_turnover_limit=Decimal("0.0"),
            created_at=TIMESTAMP,
        )


def test_adversarial_hallucinatory_insufficient_criteria_validator_rejection(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()
    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    # Proposal with Sharpe 0.10 (below MIN_REQUIRED_SHARPE 0.20)
    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Weak Sharpe Proposal",
        economic_rationale="Attempting to pass weak alpha.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.10"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 60, "rebalance_freq": "weekly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_INSUFFICIENT_CRITERIA
    assert any("min_annualized_sharpe" in reason for reason in result.rejection_reasons)


# =========================================================================
# Attack 2: Forbidden Parameter Variations Evasion
# =========================================================================


def test_adversarial_forbidden_parameter_variation_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()

    # Record a failure postmortem forbidding "lookback_days': 15"
    pm = build_failure_postmortem(
        postmortem_id=deterministic_memory_uuid7("pm_1"),
        experiment_id=EXPERIMENT_ID_1,
        run_id=deterministic_memory_uuid7("run_1"),
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Hyperactive trading.",
        lessons_learned="Avoid short lookbacks.",
        created_at=TIMESTAMP,
        forbidden_variations=("lookback_days': 15",),
    )
    recorder.record_postmortem(pm)
    archive.refresh()

    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Forbidden Variation Probe",
        economic_rationale="Attempting to re-run known failing variation.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 15, "rebalance_freq": "weekly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION
    assert any(
        "violates diagnosed failure variation" in reason
        for reason in result.rejection_reasons
    )


# =========================================================================
# Attack 3: Duplicate Parameter Re-Evaluation Collision
# =========================================================================


def test_adversarial_duplicate_parameter_hash_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()

    trial = build_research_trial_record(
        trial_id=deterministic_memory_uuid7("trial_existing"),
        hypothesis_id=deterministic_memory_uuid7("hyp_existing"),
        experiment_id=deterministic_memory_uuid7("exp_existing"),
        run_id=deterministic_memory_uuid7("run_existing"),
        strategy_type="b4_momentum",
        parameters={"lookback_days": 60, "rebalance_freq": "weekly"},
        headline_metrics={
            "annualized_sharpe": "0.60",
            "max_drawdown": "0.18",
            "annualized_turnover": "4.0",
        },
        trial_outcome=TrialOutcome.NEUTRAL,
        created_at=TIMESTAMP,
    )
    recorder.record_trial(trial)
    archive.refresh()

    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Duplicate Trial Proposal",
        economic_rationale="Attempting redundant evaluation.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 60, "rebalance_freq": "weekly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_DUPLICATE_PARAMETERS
    assert any(
        "already been evaluated" in reason for reason in result.rejection_reasons
    )


# =========================================================================
# Attack 4: Circular Lineage & Missing Ancestor Injection
# =========================================================================


def test_adversarial_self_referential_lineage_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()
    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Self-Referential Hypothesis",
        economic_rationale="Circular self-derivation.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        parent_hypothesis_id=PROPOSAL_ID_1,
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 60, "rebalance_freq": "weekly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE
    assert any(
        "cannot reference itself" in reason for reason in result.rejection_reasons
    )


def test_adversarial_missing_parent_ancestor_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()
    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    unknown_parent_id = deterministic_memory_uuid7("unknown_parent")
    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Orphan Proposal",
        economic_rationale="Inventing fictitious lineage.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        parent_hypothesis_id=unknown_parent_id,
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 90, "rebalance_freq": "monthly"},
        universe_id="sp500_historical_v1",
        rebalance_frequency="monthly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_CIRCULAR_LINEAGE
    assert any(
        "does not exist in archive" in reason for reason in result.rejection_reasons
    )


# =========================================================================
# Attack 5: Context Packet Cryptographic Tampering
# =========================================================================


def test_adversarial_context_packet_hash_tampering_rejected() -> None:
    packet = build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        created_at=TIMESTAMP,
        total_trial_count=100,
        active_hypotheses_count=5,
        falsified_hypotheses_count=10,
    )
    raw = packet.model_dump(mode="python")

    # Tamper with trial count without recomputing hash
    raw["total_trial_count"] = 1

    with pytest.raises(ValidationError, match="research context packet hash mismatch"):
        ResearchContextPacketV1.model_validate(raw)


def test_adversarial_context_packet_bit_flip_tampering_rejected() -> None:
    packet = build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        created_at=TIMESTAMP,
        total_trial_count=100,
        active_hypotheses_count=5,
        falsified_hypotheses_count=10,
    )
    raw = packet.model_dump(mode="python")

    # Bit-flip first character of context_hash
    first_char = raw["context_hash"][0]
    flipped = "0" if first_char != "0" else "1"
    raw["context_hash"] = flipped + raw["context_hash"][1:]

    with pytest.raises(ValidationError, match="research context packet hash mismatch"):
        ResearchContextPacketV1.model_validate(raw)


# =========================================================================
# Attack 6: Parameter Search Space Bounds Breach
# =========================================================================


def test_adversarial_missing_dimension_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()
    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Missing Dimension Proposal",
        economic_rationale="Omitting required dimension.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_days": 60},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any(
        "Missing required parameter dimension 'rebalance_freq'" in r
        for r in result.rejection_reasons
    )


def test_adversarial_unexpected_dimension_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    space = _build_test_search_space()
    validator = ProposalValidator(archive=archive, search_spaces={"b4_momentum": space})

    hyp = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Unexpected Dimension Proposal",
        economic_rationale="Injecting unexpected parameter.",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.5"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.0"),
        created_at=TIMESTAMP,
    )
    exp = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={
            "lookback_days": 60,
            "rebalance_freq": "weekly",
            "rogue_param": 999,
        },
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    result = validator.validate_proposal(
        hypothesis=hyp,
        experiment=exp,
        as_of_time=TIMESTAMP,
    )

    assert result.status == ProposalValidationStatus.REJECTED_OUT_OF_BOUNDS
    assert any(
        "Unexpected parameter 'rogue_param'" in r for r in result.rejection_reasons
    )


# =========================================================================
# Attack 7: Multiple-Testing Trial Count (K) Suppression Integrity
# =========================================================================


def test_adversarial_trial_count_preservation_under_failures(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    recorder = ResearchMemoryRecorder(ledger)
    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)

    for i in range(5):
        hyp_id = deterministic_memory_uuid7(f"hyp_{i}")
        exp_id = deterministic_memory_uuid7(f"exp_{i}")
        run_id = deterministic_memory_uuid7(f"run_{i}")
        trial_id = deterministic_memory_uuid7(f"trial_{i}")

        trial = build_research_trial_record(
            trial_id=trial_id,
            hypothesis_id=hyp_id,
            experiment_id=exp_id,
            run_id=run_id,
            strategy_type="b4_momentum",
            parameters={"lookback_days": 10 + i},
            headline_metrics={
                "annualized_sharpe": "0.10",
                "max_drawdown": "0.35",
                "annualized_turnover": "8.0",
            },
            trial_outcome=TrialOutcome.FAILED,
            created_at=TIMESTAMP,
        )
        recorder.record_trial(trial)

    archive.refresh()
    context = synthesizer.synthesize_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        as_of_time=TIMESTAMP,
    )
    assert context.total_trial_count == 5


# =========================================================================
# Attack 8: Firewall & Execution Authority Separation
# =========================================================================


def test_adversarial_untrusted_agent_cannot_bypass_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SQLiteLedger(db_path)
    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)
    validator = ProposalValidator(archive=archive)

    # Agent returns weak alpha proposal (Sharpe 0.05 < 0.20 required)
    def weak_agent(sys_inst: str, prompt: str) -> str:
        return json.dumps(
            {
                "title": "Weak Agent Proposal",
                "economic_rationale": "Subverting bounds.",
                "min_annualized_sharpe": 0.05,
                "max_drawdown_limit": 0.20,
                "max_turnover_limit": 5.0,
                "proposed_parameters": {"lookback_days": 60},
                "universe_id": "sp500_historical_v1",
                "rebalance_frequency": "weekly",
            }
        )

    agent = GeminiResearchAgent(generate_fn=weak_agent)
    runner = ResearchAgentRunner(
        synthesizer=synthesizer,
        validator=validator,
        agent=agent,
    )

    hyp, exp, val = runner.run_cycle(
        target_strategy_type="b4_momentum",
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        as_of_time=TIMESTAMP,
    )
    assert val.status == ProposalValidationStatus.REJECTED_INSUFFICIENT_CRITERIA
    assert not val.is_accepted
