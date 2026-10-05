"""Structured research memory package for Drift (Milestone M6)."""

from drift.memory.hypothesis import (
    HypothesisFalsificationCriteria,
    HypothesisManager,
    HypothesisNotFoundError,
    InvalidStateTransitionError,
)
from drift.memory.postmortem import (
    FORBIDDEN_VARIATION_TEMPLATES,
    FailurePostmortemEngine,
)
from drift.memory.recorder import (
    HYPOTHESIS_ENTITY_TYPE,
    POSTMORTEM_ENTITY_TYPE,
    TRIAL_ENTITY_TYPE,
    ResearchMemoryError,
    ResearchMemoryRecorder,
    deterministic_memory_uuid7,
)

__all__ = [
    "FORBIDDEN_VARIATION_TEMPLATES",
    "HYPOTHESIS_ENTITY_TYPE",
    "POSTMORTEM_ENTITY_TYPE",
    "TRIAL_ENTITY_TYPE",
    "FailurePostmortemEngine",
    "HypothesisFalsificationCriteria",
    "HypothesisManager",
    "HypothesisNotFoundError",
    "InvalidStateTransitionError",
    "ResearchMemoryError",
    "ResearchMemoryRecorder",
    "deterministic_memory_uuid7",
]
