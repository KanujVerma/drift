"""Research agent interface protocols (M7-4, Issue 223)."""

from typing import Protocol, runtime_checkable

from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
    ResearchContextPacketV1,
)
from drift.domain.research_memory import ParameterSearchSpaceV1


@runtime_checkable
class ResearchAgentProtocol(Protocol):
    """Protocol implemented by research proposal generators."""

    def generate_proposal(
        self,
        context: ResearchContextPacketV1,
        target_strategy_type: str,
        search_space: ParameterSearchSpaceV1 | None = None,
    ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]:
        """Generate a hypothesis proposal and experiment specification proposal."""
        ...
