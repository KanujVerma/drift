"""Promotion gatekeeping, statistical validation, and overfitting controls (M11)."""

from drift.promotion.archive import PromotionArchive
from drift.promotion.gatekeeper import (
    PromotionGatekeeper,
    calculate_deflated_sharpe_ratio,
    estimate_probability_backtest_overfitting,
    evaluate_regime_stress,
    evaluate_walk_forward_consistency,
)
from drift.promotion.recorder import (
    PROMOTION_CERTIFICATION_ENTITY_TYPE,
    PROMOTION_EVALUATION_ENTITY_TYPE,
    PROMOTION_REJECTION_ENTITY_TYPE,
    PromotionRecorder,
)
from drift.promotion.runner import (
    CandidatePromotionRequestV1,
    PromotionBatchResultV1,
    PromotionRecorderProtocol,
    PromotionRunner,
)

__all__ = [
    "CandidatePromotionRequestV1",
    "PROMOTION_CERTIFICATION_ENTITY_TYPE",
    "PROMOTION_EVALUATION_ENTITY_TYPE",
    "PROMOTION_REJECTION_ENTITY_TYPE",
    "PromotionArchive",
    "PromotionBatchResultV1",
    "PromotionGatekeeper",
    "PromotionRecorder",
    "PromotionRecorderProtocol",
    "PromotionRunner",
    "calculate_deflated_sharpe_ratio",
    "estimate_probability_backtest_overfitting",
    "evaluate_regime_stress",
    "evaluate_walk_forward_consistency",
]
