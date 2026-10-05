"""Recursive R&D loop components for Drift (Milestone M8)."""

from drift.loop.diagnosis import (
    TrialDiagnosisResult,
    build_automatic_failure_postmortem,
    diagnose_trial_outcome,
)
from drift.loop.evaluator_adapter import (
    DeterministicMockTrialEvaluator,
    TrialEvaluatorProtocol,
)
from drift.loop.runner import ResearchLoopRunner

__all__ = [
    "DeterministicMockTrialEvaluator",
    "ResearchLoopRunner",
    "TrialDiagnosisResult",
    "TrialEvaluatorProtocol",
    "build_automatic_failure_postmortem",
    "diagnose_trial_outcome",
]
