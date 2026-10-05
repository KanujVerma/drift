"""Unit tests for research agent domain models and proposal schemas (M7-1)."""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.research_agent import (
    RESEARCH_AGENT_SCHEMA_VERSION,
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ProposalValidationResultV1,
    ProposalValidationStatus,
    ResearchAgentRole,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
    build_proposal_validation_result,
    build_research_context_packet,
)

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
PROPOSAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
PROPOSAL_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
VALIDATION_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")


def test_research_context_packet_construction() -> None:
    packet = build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        total_trial_count=42,
        active_hypotheses_count=3,
        falsified_hypotheses_count=12,
        created_at=TIMESTAMP,
        median_sharpe_ratio=Decimal("0.85"),
        max_sharpe_ratio=Decimal("1.92"),
        falsified_hypothesis_summaries=("Falsified B0 random baseline",),
        forbidden_variations=("lookback < 5 with unhedged weights",),
        available_strategy_types=("b4_momentum", "b5_low_volatility"),
    )

    assert packet.schema_version == RESEARCH_AGENT_SCHEMA_VERSION
    assert packet.agent_role == ResearchAgentRole.ALPHA_RESEARCHER
    assert packet.total_trial_count == 42
    assert packet.median_sharpe_ratio == Decimal("0.85")
    assert len(packet.context_hash) == 64

    # Negative trial counts must raise ValueError
    with pytest.raises(ValidationError):
        build_research_context_packet(
            agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
            total_trial_count=-1,
            active_hypotheses_count=0,
            falsified_hypotheses_count=0,
            created_at=TIMESTAMP,
        )


def test_hypothesis_proposal_validation() -> None:
    prop = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Cross-sectional momentum with turnover penalty",
        economic_rationale=(
            "Underreaction to earnings surprises creates persistent drift."
        ),
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.75"),
        max_drawdown_limit=Decimal("0.15"),
        max_turnover_limit=Decimal("4.00"),
        min_information_coefficient=Decimal("0.04"),
        created_at=TIMESTAMP,
    )

    assert prop.schema_version == "1"
    assert prop.proposal_id == PROPOSAL_ID_1
    assert prop.min_annualized_sharpe == Decimal("0.75")
    assert len(prop.proposal_hash) == 64

    # Non-positive Sharpe threshold must fail validation
    with pytest.raises(ValidationError):
        build_hypothesis_proposal(
            proposal_id=PROPOSAL_ID_1,
            title="Invalid",
            economic_rationale="Invalid",
            target_strategy_type="b4_momentum",
            min_annualized_sharpe=Decimal("-0.10"),
            max_drawdown_limit=Decimal("0.15"),
            max_turnover_limit=Decimal("4.00"),
            created_at=TIMESTAMP,
        )

    # Out-of-bounds drawdown (> 1.0) must fail validation
    with pytest.raises(ValidationError):
        build_hypothesis_proposal(
            proposal_id=PROPOSAL_ID_1,
            title="Invalid",
            economic_rationale="Invalid",
            target_strategy_type="b4_momentum",
            min_annualized_sharpe=Decimal("0.50"),
            max_drawdown_limit=Decimal("1.50"),
            max_turnover_limit=Decimal("4.00"),
            created_at=TIMESTAMP,
        )


def test_experiment_specification_proposal() -> None:
    spec = build_experiment_specification_proposal(
        experiment_proposal_id=EXPERIMENT_ID_1,
        hypothesis_proposal_id=PROPOSAL_ID_1,
        strategy_type="b4_momentum",
        proposed_parameters={"lookback_sessions": 20, "holding_sessions": 5},
        universe_id="sp500_historical_v1",
        rebalance_frequency="weekly",
        created_at=TIMESTAMP,
    )

    assert spec.experiment_proposal_id == EXPERIMENT_ID_1
    assert spec.strategy_type == "b4_momentum"
    assert isinstance(spec.proposed_parameters, Mapping)
    assert spec.proposed_parameters["lookback_sessions"] == 20
    assert len(spec.parameters_hash) == 64
    assert len(spec.specification_hash) == 64

    # Tampered parameters_hash must fail validation
    with pytest.raises(ValidationError):
        ExperimentSpecificationProposalV1(
            schema_version="1",
            experiment_proposal_id=EXPERIMENT_ID_1,
            hypothesis_proposal_id=PROPOSAL_ID_1,
            strategy_type="b4_momentum",
            proposed_parameters=spec.proposed_parameters,
            parameters_hash="0" * 64,  # mismatched hash
            universe_id="sp500_historical_v1",
            rebalance_frequency="weekly",
            created_at=TIMESTAMP,
            specification_hash=spec.specification_hash,
        )


def test_proposal_validation_result_integrity() -> None:
    # Accepted result
    accepted = build_proposal_validation_result(
        validation_id=VALIDATION_ID_1,
        proposal_id=PROPOSAL_ID_1,
        status=ProposalValidationStatus.ACCEPTED,
        is_accepted=True,
        evaluated_at=TIMESTAMP,
    )
    assert accepted.is_accepted is True
    assert len(accepted.validation_hash) == 64

    # Rejected result requires reasons
    rejected = build_proposal_validation_result(
        validation_id=VALIDATION_ID_1,
        proposal_id=PROPOSAL_ID_2,
        status=ProposalValidationStatus.REJECTED_DUPLICATE_PARAMETERS,
        is_accepted=False,
        evaluated_at=TIMESTAMP,
        rejection_reasons=("Parameter set already evaluated in Trial 018f3a5b",),
    )
    assert rejected.is_accepted is False
    assert len(rejected.rejection_reasons) == 1

    # Rejected without reasons must fail validation
    with pytest.raises(ValidationError):
        build_proposal_validation_result(
            validation_id=VALIDATION_ID_1,
            proposal_id=PROPOSAL_ID_2,
            status=ProposalValidationStatus.REJECTED_FORBIDDEN_VARIATION,
            is_accepted=False,
            evaluated_at=TIMESTAMP,
            rejection_reasons=(),
        )

    # Inconsistent status and is_accepted must fail validation
    with pytest.raises(ValidationError):
        ProposalValidationResultV1(
            schema_version="1",
            validation_id=VALIDATION_ID_1,
            proposal_id=PROPOSAL_ID_1,
            status=ProposalValidationStatus.ACCEPTED,
            is_accepted=False,
            rejection_reasons=(),
            evaluated_at=TIMESTAMP,
            validation_hash=accepted.validation_hash,
        )


def test_domain_model_immutability() -> None:
    prop = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Momentum",
        economic_rationale="Trend following",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )

    with pytest.raises(ValidationError):
        prop.min_annualized_sharpe = Decimal("1.00")


def test_domain_model_serialization_roundtrip() -> None:
    prop = build_hypothesis_proposal(
        proposal_id=PROPOSAL_ID_1,
        title="Momentum",
        economic_rationale="Trend following",
        target_strategy_type="b4_momentum",
        min_annualized_sharpe=Decimal("0.50"),
        max_drawdown_limit=Decimal("0.20"),
        max_turnover_limit=Decimal("5.00"),
        created_at=TIMESTAMP,
    )

    json_str = prop.model_dump_json()
    reconstituted = HypothesisProposalV1.model_validate_json(json_str)

    assert reconstituted == prop
    assert reconstituted.proposal_hash == prop.proposal_hash
