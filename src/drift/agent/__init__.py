"""Autonomous AI research agent package for Drift (Milestone M7)."""

from drift.agent.context import (
    DEFAULT_STRATEGY_TYPES,
    LEGACY_STRATEGY_TYPE_ALIASES,
    ResearchContextSynthesizer,
)
from drift.agent.gemini_agent import (
    GeminiAgentSchemaOutput,
    GeminiResearchAgent,
    GeminiResearchAgentError,
)
from drift.agent.mock_agent import DeterministicMockResearchAgent
from drift.agent.protocol import ResearchAgentProtocol
from drift.agent.runner import ResearchAgentRunner
from drift.agent.validator import ProposalValidator

__all__ = [
    "DEFAULT_STRATEGY_TYPES",
    "DeterministicMockResearchAgent",
    "GeminiAgentSchemaOutput",
    "GeminiResearchAgent",
    "GeminiResearchAgentError",
    "LEGACY_STRATEGY_TYPE_ALIASES",
    "ProposalValidator",
    "ResearchAgentProtocol",
    "ResearchAgentRunner",
    "ResearchContextSynthesizer",
]
