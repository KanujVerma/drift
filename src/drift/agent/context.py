"""Research context packet synthesis engine (M7-2, Issue 219).

Provides deterministic synthesis of ResearchContextPacketV1 instances from the
historical M6 ResearchMemoryArchive, computing multiple-testing summary metrics
and negative knowledge constraints to condition autonomous research agents.
"""

from decimal import Decimal

from drift.domain.common import UTCDateTime
from drift.domain.research_agent import (
    ResearchAgentRole,
    ResearchContextPacketV1,
    build_research_context_packet,
)
from drift.domain.research_memory import HypothesisStatus
from drift.memory.archive import ResearchMemoryArchive

DEFAULT_STRATEGY_TYPES: tuple[str, ...] = (
    "b0_passive_equal_weight",
    "b1_market_cap_weight",
    "b2_fixed_universe_rebalance",
    "b3_mean_reversion",
    "b4_momentum",
    "b5_low_volatility",
)


class ResearchContextSynthesizer:
    """Deterministic synthesizer creating context packets from M6 archive."""

    def __init__(self, archive: ResearchMemoryArchive) -> None:
        self.archive = archive

    def synthesize_packet(
        self,
        *,
        agent_role: ResearchAgentRole,
        as_of_time: UTCDateTime,
        available_strategy_types: tuple[str, ...] = DEFAULT_STRATEGY_TYPES,
    ) -> ResearchContextPacketV1:
        """Synthesize an immutable ResearchContextPacketV1 from memory state."""
        trial_count = self.archive.get_trial_count()
        sharpe_distribution = self.archive.get_trial_sharpe_distribution()

        median_sharpe: Decimal | None = None
        max_sharpe: Decimal | None = None

        if sharpe_distribution:
            sorted_sharpes = sorted(sharpe_distribution)
            max_sharpe = sorted_sharpes[-1]
            n = len(sorted_sharpes)
            if n % 2 == 1:
                median_sharpe = sorted_sharpes[n // 2]
            else:
                median_sharpe = (
                    sorted_sharpes[n // 2 - 1] + sorted_sharpes[n // 2]
                ) / Decimal("2")

        falsified_hypotheses = self.archive.find_falsified_hypotheses()
        falsified_count = len(falsified_hypotheses)
        falsified_summaries = tuple(
            f"Hypothesis {h.hypothesis_id}: {h.notes or 'falsified'}"
            for h in falsified_hypotheses
        )

        # Count active hypotheses from archive internal index
        active_count = sum(
            1
            for h in self.archive._hypotheses.values()
            if h.status == HypothesisStatus.ACTIVE
        )

        forbidden_set: list[str] = []
        for pm in self.archive.get_postmortems():
            for v in pm.forbidden_variations:
                if v not in forbidden_set:
                    forbidden_set.append(v)
        forbidden_variations = tuple(forbidden_set)

        return build_research_context_packet(
            agent_role=agent_role,
            total_trial_count=trial_count,
            active_hypotheses_count=active_count,
            falsified_hypotheses_count=falsified_count,
            created_at=as_of_time,
            median_sharpe_ratio=median_sharpe,
            max_sharpe_ratio=max_sharpe,
            falsified_hypothesis_summaries=falsified_summaries,
            forbidden_variations=forbidden_variations,
            available_strategy_types=available_strategy_types,
        )
