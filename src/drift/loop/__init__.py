"""Recursive R&D loop components for Drift (Milestone M8)."""

from drift.loop.archive import ResearchLoopArchive
from drift.loop.diagnosis import (
    TrialDiagnosisResult,
    build_automatic_failure_postmortem,
    diagnose_trial_outcome,
)
from drift.loop.evaluator_adapter import (
    CashBaselineStrategy,
    DeterministicMockTrialEvaluator,
    EqualWeightBuyAndHoldBaselineStrategy,
    ExecutionConfigurationV2,
    LowVolatilityBaselineStrategy,
    M2TrialEvaluatorAdapter,
    MockEvaluatorProductionError,
    MomentumBaselineStrategy,
    MonthlyEqualWeightRebalanceBaselineStrategy,
    SingleBuyAndHoldBaselineStrategy,
    StrategyParameterValidationError,
    TrialEvaluatorProtocol,
    UnknownStrategyTypeError,
)
from drift.loop.recorder import ResearchLoopRecorder
from drift.loop.runner import ResearchLoopRunner

__all__ = [
    "CashBaselineStrategy",
    "DeterministicMockTrialEvaluator",
    "EqualWeightBuyAndHoldBaselineStrategy",
    "ExecutionConfigurationV2",
    "LowVolatilityBaselineStrategy",
    "M2TrialEvaluatorAdapter",
    "MockEvaluatorProductionError",
    "MomentumBaselineStrategy",
    "MonthlyEqualWeightRebalanceBaselineStrategy",
    "ResearchLoopArchive",
    "ResearchLoopRecorder",
    "ResearchLoopRunner",
    "SingleBuyAndHoldBaselineStrategy",
    "StrategyParameterValidationError",
    "TrialDiagnosisResult",
    "TrialEvaluatorProtocol",
    "UnknownStrategyTypeError",
    "build_automatic_failure_postmortem",
    "diagnose_trial_outcome",
]
