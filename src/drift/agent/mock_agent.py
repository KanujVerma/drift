"""Deterministic mock research agent implementation (M7-4, Issue 223).

Generates reproducible, valid hypothesis and experiment proposals for offline
deterministic verification, regression testing, and CI pipelines without network calls.
"""

from decimal import Decimal
from typing import Any

from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ResearchContextPacketV1,
    build_experiment_specification_proposal,
    build_hypothesis_proposal,
)
from drift.domain.research_memory import ParameterSearchSpaceV1
from drift.memory.recorder import deterministic_memory_uuid7


class DeterministicMockResearchAgent:
    """Deterministic, replayable mock agent for offline testing and CI gates."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._counter: int = 0

    def generate_proposal(
        self,
        context: ResearchContextPacketV1,
        target_strategy_type: str,
        search_space: ParameterSearchSpaceV1 | None = None,
    ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]:
        """Generate a deterministic hypothesis proposal and experiment specification."""
        self._counter += 1
        ts = context.created_at

        hyp_id = deterministic_memory_uuid7(
            f"mock:hyp:{self.seed}:{self._counter}:{context.context_hash[:16]}"
        )
        exp_id = deterministic_memory_uuid7(
            f"mock:exp:{self.seed}:{self._counter}:{context.context_hash[:16]}"
        )

        title = (
            f"Deterministic hypothesis #{self._counter} for {target_strategy_type}"
        )
        rationale = (
            f"Systematic exploration of {target_strategy_type} parameter space "
            f"conditioned on trial count K={context.total_trial_count}."
        )

        # Build parameters adhering to search space dimensions if provided
        parameters: dict[str, Any] = {}
        if search_space is not None and search_space.dimension_names:
            for i, dim in enumerate(search_space.dimension_names):
                parameters[dim] = 10 + (self._counter * 5) + i
        else:
            parameters = {"lookback_sessions": 20 + (self._counter * 2)}

        hyp = build_hypothesis_proposal(
            proposal_id=hyp_id,
            title=title,
            economic_rationale=rationale,
            target_strategy_type=target_strategy_type,
            min_annualized_sharpe=Decimal("0.60"),
            max_drawdown_limit=Decimal("0.20"),
            max_turnover_limit=Decimal("4.00"),
            created_at=ts,
        )

        exp = build_experiment_specification_proposal(
            experiment_proposal_id=exp_id,
            hypothesis_proposal_id=hyp_id,
            strategy_type=target_strategy_type,
            proposed_parameters=parameters,
            universe_id="sp500_historical_v1",
            rebalance_frequency="weekly",
            created_at=ts,
        )

        return hyp, exp
