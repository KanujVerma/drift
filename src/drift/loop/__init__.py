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

__all__ = [
    "DeterministicMockTrialEvaluator",
    "TrialDiagnosisResult",
    "TrialEvaluatorProtocol",
    "build_automatic_failure_postmortem",
    "diagnose_trial_outcome",
]
