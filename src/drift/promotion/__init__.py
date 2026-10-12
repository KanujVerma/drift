"""Promotion gatekeeping, statistical validation, and overfitting controls (M11)."""

from drift.promotion.gatekeeper import (
    PromotionGatekeeper,
    calculate_deflated_sharpe_ratio,
    estimate_probability_backtest_overfitting,
    evaluate_regime_stress,
    evaluate_walk_forward_consistency,
)

__all__ = [
    "PromotionGatekeeper",
    "calculate_deflated_sharpe_ratio",
    "estimate_probability_backtest_overfitting",
    "evaluate_regime_stress",
    "evaluate_walk_forward_consistency",
]
