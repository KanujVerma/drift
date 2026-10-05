"""Unit tests for Gemini research agent adapter (M7-5, Issue 225)."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from drift.agent.gemini_agent import (
    GeminiResearchAgent,
    GeminiResearchAgentError,
)
from drift.agent.protocol import ResearchAgentProtocol
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ResearchAgentRole,
    ResearchContextPacketV1,
    build_research_context_packet,
)
from drift.domain.research_memory import (
    ParameterSearchSpaceV1,
    build_parameter_search_space,
)
from drift.memory.recorder import deterministic_memory_uuid7


def _sample_context_packet() -> ResearchContextPacketV1:
    return build_research_context_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        created_at=datetime.now(tz=UTC),
        total_trial_count=42,
        median_sharpe_ratio=Decimal("0.85"),
        max_sharpe_ratio=Decimal("1.65"),
        active_hypotheses_count=3,
        falsified_hypotheses_count=1,
        forbidden_variations=("lookback=5", "stop_loss=0.01"),
        falsified_hypothesis_summaries=("lookback 5 had excessive turnover",),
    )


def _sample_search_space() -> ParameterSearchSpaceV1:
    return build_parameter_search_space(
        search_space_id=deterministic_memory_uuid7("sample_space"),
        strategy_type="b4_momentum",
        dimension_names=("lookback_days", "rebalance_freq"),
        created_at=datetime.now(tz=UTC),
    )


def test_gemini_research_agent_implements_protocol() -> None:
    agent = GeminiResearchAgent(generate_fn=lambda sys, prompt: "{}")
    assert isinstance(agent, ResearchAgentProtocol)


def test_format_prompt_incorporates_context_and_search_space() -> None:
    agent = GeminiResearchAgent()
    context = _sample_context_packet()
    space = _sample_search_space()

    sys_inst, prompt = agent.format_prompt(
        context=context,
        target_strategy_type="b4_momentum",
        search_space=space,
    )

    assert "autonomous quantitative research agent for Drift" in sys_inst
    assert "Target Strategy: b4_momentum" in prompt
    assert "Declared Search Dimensions: lookback_days, rebalance_freq" in prompt
    assert "Total Historical Trials (K): 42" in prompt
    assert "lookback=5" in prompt
    assert "lookback 5 had excessive turnover" in prompt


def test_generate_proposal_with_generate_fn_success() -> None:
    sample_output = {
        "title": "Dual Momentum Lookback Regime",
        "economic_rationale": "Intermediate momentum captures equity risk premium.",
        "min_annualized_sharpe": 0.65,
        "max_drawdown_limit": 0.18,
        "max_turnover_limit": 4.5,
        "min_information_coefficient": 0.03,
        "proposed_parameters": {"lookback_days": 90, "rebalance_freq": "monthly"},
        "universe_id": "sp500_historical_v1",
        "rebalance_frequency": "monthly",
    }

    def dummy_generate(sys_inst: str, prompt: str) -> str:
        return json.dumps(sample_output)

    agent = GeminiResearchAgent(generate_fn=dummy_generate)
    context = _sample_context_packet()

    hyp, exp = agent.generate_proposal(
        context=context,
        target_strategy_type="b4_momentum",
    )

    assert isinstance(hyp, HypothesisProposalV1)
    assert isinstance(exp, ExperimentSpecificationProposalV1)
    assert hyp.title == "Dual Momentum Lookback Regime"
    assert hyp.min_annualized_sharpe == Decimal("0.65")
    assert hyp.max_drawdown_limit == Decimal("0.18")
    assert hyp.max_turnover_limit == Decimal("4.5")
    assert hyp.min_information_coefficient == Decimal("0.03")
    assert exp.proposed_parameters == {
        "lookback_days": 90,
        "rebalance_freq": "monthly",
    }
    assert exp.universe_id == "sp500_historical_v1"
    assert exp.rebalance_frequency == "monthly"
    assert exp.hypothesis_proposal_id == hyp.proposal_id


def test_generate_proposal_unconfigured_raises_error() -> None:
    agent = GeminiResearchAgent()
    context = _sample_context_packet()

    with pytest.raises(
        GeminiResearchAgentError,
        match="requires either a client instance or a generate_fn",
    ):
        agent.generate_proposal(context=context, target_strategy_type="b4_momentum")


def test_generate_proposal_invalid_json_raises_error() -> None:
    agent = GeminiResearchAgent(generate_fn=lambda s, p: "not-json")
    context = _sample_context_packet()

    with pytest.raises(
        GeminiResearchAgentError, match="Failed to validate Gemini response"
    ):
        agent.generate_proposal(context=context, target_strategy_type="b4_momentum")


def test_generate_proposal_missing_schema_field_raises_error() -> None:
    agent = GeminiResearchAgent(
        generate_fn=lambda s, p: json.dumps({"title": "Incomplete"})
    )
    context = _sample_context_packet()

    with pytest.raises(
        GeminiResearchAgentError, match="Failed to validate Gemini response"
    ):
        agent.generate_proposal(context=context, target_strategy_type="b4_momentum")


def test_generate_proposal_with_gemini_client_mock() -> None:
    sample_output = {
        "title": "Low Volatility Reversal",
        "economic_rationale": "Idiosyncratic volatility penalty generates anomaly.",
        "min_annualized_sharpe": 0.55,
        "max_drawdown_limit": 0.15,
        "max_turnover_limit": 3.0,
        "min_information_coefficient": None,
        "proposed_parameters": {"lookback_days": 30},
        "universe_id": "sp500_historical_v1",
        "rebalance_frequency": "weekly",
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(sample_output)
    mock_client.models.generate_content.return_value = mock_response

    agent = GeminiResearchAgent(client=mock_client)
    context = _sample_context_packet()

    hyp, exp = agent.generate_proposal(
        context=context, target_strategy_type="b5_low_volatility"
    )

    assert hyp.title == "Low Volatility Reversal"
    assert hyp.min_information_coefficient is None
    assert exp.proposed_parameters == {"lookback_days": 30}
    mock_client.models.generate_content.assert_called_once()


def test_generate_proposal_with_gemini_client_exception() -> None:
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError(
        "API rate limit exceeded"
    )

    agent = GeminiResearchAgent(client=mock_client)
    context = _sample_context_packet()

    with pytest.raises(
        GeminiResearchAgentError, match="Gemini client generation failed"
    ):
        agent.generate_proposal(context=context, target_strategy_type="b4_momentum")
