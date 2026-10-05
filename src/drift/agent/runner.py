"""Autonomous research agent orchestration runner (M7-4, Issue 223).

Coordinates the complete research generation lifecycle:
1. Synthesizes memory context from M6 ResearchMemoryArchive;
2. Queries the research agent protocol backend (mock or LLM);
3. Passes proposals through the deterministic ProposalValidator firewall;
4. If accepted, optionally pre-registers hypothesis in HypothesisManager;
5. Emits full validated proposal packet for evaluation.
"""

from drift.agent.context import ResearchContextSynthesizer
from drift.agent.protocol import ResearchAgentProtocol
from drift.agent.validator import ProposalValidator
from drift.domain.common import UTCDateTime
from drift.domain.hypotheses import Hypothesis
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ProposalValidationResultV1,
    ResearchAgentRole,
)
from drift.domain.research_memory import ParameterSearchSpaceV1
from drift.memory.hypothesis import (
    HypothesisFalsificationCriteria,
    HypothesisManager,
)


class ResearchAgentRunner:
    """Orchestrator driving the autonomous research agent cycle."""

    def __init__(
        self,
        *,
        synthesizer: ResearchContextSynthesizer,
        validator: ProposalValidator,
        agent: ResearchAgentProtocol,
        hypothesis_manager: HypothesisManager | None = None,
    ) -> None:
        self.synthesizer = synthesizer
        self.validator = validator
        self.agent = agent
        self.hypothesis_manager = hypothesis_manager

    def run_cycle(
        self,
        *,
        agent_role: ResearchAgentRole,
        target_strategy_type: str,
        as_of_time: UTCDateTime,
        search_space: ParameterSearchSpaceV1 | None = None,
    ) -> tuple[
        HypothesisProposalV1,
        ExperimentSpecificationProposalV1,
        ProposalValidationResultV1,
    ]:
        """Execute one complete proposal generation and validation cycle."""
        # 1. Synthesize memory context
        context = self.synthesizer.synthesize_packet(
            agent_role=agent_role,
            as_of_time=as_of_time,
        )

        # 2. Invoke agent proposal generator
        hyp, exp = self.agent.generate_proposal(
            context=context,
            target_strategy_type=target_strategy_type,
            search_space=search_space,
        )

        # 3. Deterministic firewall validation
        val_result = self.validator.validate_proposal(
            hypothesis=hyp,
            experiment=exp,
            as_of_time=as_of_time,
        )

        # 4. If accepted and manager is configured, pre-register hypothesis
        if val_result.is_accepted and self.hypothesis_manager is not None:
            parents = (
                (hyp.parent_hypothesis_id,)
                if hyp.parent_hypothesis_id is not None
                else ()
            )
            h_domain = Hypothesis(
                hypothesis_id=hyp.proposal_id,
                created_at=as_of_time,
                title=hyp.title,
                statement=hyp.economic_rationale,
                mechanism=hyp.economic_rationale,
                expected_direction="long",
                universe="sp500",
                horizon="medium_term",
                falsification_criteria=(
                    f"Sharpe < {hyp.min_annualized_sharpe} or "
                    f"Drawdown > {hyp.max_drawdown_limit}"
                ),
                parent_hypothesis_ids=parents,
                author_type="ai_agent",
                author_version="1.0.0",
                tags=(target_strategy_type,),
            )
            criteria = HypothesisFalsificationCriteria(
                min_sharpe_ratio=hyp.min_annualized_sharpe,
                max_drawdown_limit=-abs(hyp.max_drawdown_limit),
                min_mean_ic=hyp.min_information_coefficient,
            )
            self.hypothesis_manager.register_hypothesis(
                h_domain,
                criteria=criteria,
                as_of_time=as_of_time,
            )

        return hyp, exp, val_result
