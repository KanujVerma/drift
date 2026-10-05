"""Production Gemini research agent adapter (M7-5, Issue 225).

Generates quantitative research proposals using Google Gemini models,
enforcing structured JSON schema validation, contextual conditioning on
historical M6 research memory, and untrusted agent firewall boundaries.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ResearchContextPacketV1,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_memory import ParameterSearchSpaceV1
from drift.errors import DriftError
from drift.memory.recorder import deterministic_memory_uuid7


class GeminiAgentSchemaOutput(BaseModel):
    """Schema for structured output generation from Gemini."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(description="Descriptive title of proposed hypothesis")
    economic_rationale: str = Field(
        description="Underlying economic intuition and market mechanism"
    )
    min_annualized_sharpe: float = Field(
        description="Minimum acceptable annualized Sharpe ratio (e.g. 0.50)"
    )
    max_drawdown_limit: float = Field(
        description="Maximum acceptable drawdown limit as positive fraction (e.g. 0.20)"
    )
    max_turnover_limit: float = Field(
        description="Maximum annualized portfolio turnover limit (e.g. 5.0)"
    )
    min_information_coefficient: float | None = Field(
        default=None, description="Optional minimum mean IC threshold"
    )
    proposed_parameters: dict[str, Any] = Field(
        description="Dictionary of strategy hyperparameters"
    )
    universe_id: str = Field(
        default="sp500_historical_v1", description="Target equity universe"
    )
    rebalance_frequency: str = Field(
        default="weekly", description="Portfolio rebalance frequency"
    )


class GeminiResearchAgentError(DriftError):
    """Raised when Gemini agent generation or validation fails."""


class GeminiResearchAgent:
    """Autonomous research agent adapter utilizing Gemini models."""

    def __init__(
        self,
        *,
        model_name: str = "gemini-2.5-flash",
        client: Any | None = None,
        generate_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        self.model_name = model_name
        self.client = client
        self.generate_fn = generate_fn

    def format_prompt(
        self,
        context: ResearchContextPacketV1,
        target_strategy_type: str,
        search_space: ParameterSearchSpaceV1 | None = None,
    ) -> tuple[str, str]:
        """Build system instruction and user prompt from research context."""
        system_instruction = (
            "You are an autonomous quantitative research agent for Drift. "
            "Your mission is to formulate scientifically grounded, non-redundant "
            "economic hypotheses and valid experiment specifications. "
            "You operate strictly in the exploratory lane with zero live "
            "execution authority. "
            "You MUST account for multiple-testing penalties, turnover drag, "
            "and known failure modes. "
            "Do NOT propose parameter variations that match known forbidden "
            "variations."
        )

        dimensions_str = (
            ", ".join(search_space.dimension_names)
            if search_space is not None
            else "standard parameters"
        )

        forbidden_str = (
            "; ".join(context.forbidden_variations)
            if context.forbidden_variations
            else "None recorded"
        )

        falsified_str = (
            "; ".join(context.falsified_hypothesis_summaries)
            if context.falsified_hypothesis_summaries
            else "None recorded"
        )

        user_prompt = (
            f"Target Strategy: {target_strategy_type}\n"
            f"Declared Search Dimensions: {dimensions_str}\n\n"
            f"Historical Research Memory Context:\n"
            f"- Total Historical Trials (K): {context.total_trial_count}\n"
            f"- Median Historical Sharpe: {context.median_sharpe_ratio}\n"
            f"- Max Historical Sharpe: {context.max_sharpe_ratio}\n"
            f"- Active Hypotheses Count: {context.active_hypotheses_count}\n"
            f"- Falsified Hypotheses Count: {context.falsified_hypotheses_count}\n"
            f"- Falsified Summaries: {falsified_str}\n"
            f"- Known Forbidden Variations: {forbidden_str}\n\n"
            f"Generate a novel hypothesis proposal and experiment specification "
            f"for {target_strategy_type}.\n"
            f"Specify strict numeric falsification criteria and ensure all proposed "
            f"parameters adhere to the search dimensions."
        )

        return system_instruction, user_prompt

    def generate_proposal(
        self,
        context: ResearchContextPacketV1,
        target_strategy_type: str,
        search_space: ParameterSearchSpaceV1 | None = None,
    ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]:
        """Generate and parse structured research proposals."""
        system_inst, prompt = self.format_prompt(
            context=context,
            target_strategy_type=target_strategy_type,
            search_space=search_space,
        )

        raw_json: str
        if self.generate_fn is not None:
            raw_json = self.generate_fn(system_inst, prompt)
        elif self.client is not None:
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={
                        "system_instruction": system_inst,
                        "response_mime_type": "application/json",
                    },
                )
                raw_json = response.text
            except Exception as err:
                msg = f"Gemini client generation failed: {err}"
                raise GeminiResearchAgentError(msg) from err
        else:
            msg = (
                "GeminiResearchAgent requires either a client instance or "
                "a generate_fn callback"
            )
            raise GeminiResearchAgentError(msg)

        try:
            parsed = GeminiAgentSchemaOutput.model_validate_json(raw_json)
        except Exception as err:
            msg = f"Failed to validate Gemini response against schema: {err}"
            raise GeminiResearchAgentError(msg) from err

        ts = context.created_at
        hyp_id = deterministic_memory_uuid7(
            f"gemini:hyp:{parsed.title}:{context.context_hash[:16]}"
        )
        exp_id = deterministic_memory_uuid7(
            f"gemini:exp:{parsed.title}:{context.context_hash[:16]}"
        )

        hyp = build_hypothesis_proposal(
            proposal_id=hyp_id,
            title=parsed.title,
            economic_rationale=parsed.economic_rationale,
            target_strategy_type=target_strategy_type,
            min_annualized_sharpe=Decimal(str(parsed.min_annualized_sharpe)),
            max_drawdown_limit=Decimal(str(parsed.max_drawdown_limit)),
            max_turnover_limit=Decimal(str(parsed.max_turnover_limit)),
            min_information_coefficient=(
                Decimal(str(parsed.min_information_coefficient))
                if parsed.min_information_coefficient is not None
                else None
            ),
            created_at=ts,
        )

        exp = build_experiment_specification_proposal(
            experiment_proposal_id=exp_id,
            hypothesis_proposal_id=hyp_id,
            strategy_type=target_strategy_type,
            proposed_parameters=parsed.proposed_parameters,
            universe_id=parsed.universe_id,
            rebalance_frequency=parsed.rebalance_frequency,
            created_at=ts,
        )

        return hyp, exp
