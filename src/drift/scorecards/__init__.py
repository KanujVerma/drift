"""Statistical and model scorecards module (M5, Issue 12).

Provides quantitative performance attribution, predictive power analysis,
probabilistic calibration curves, drawdown trajectory analysis, portfolio
turnover, and multiple-testing adjustments.
"""

from drift.scorecards.predictive import (
    aggregate_information_coefficients,
    compute_calibration_summary,
    compute_pearson_correlation,
    compute_spearman_rank_correlation,
    fractional_ranks,
    generate_prediction_scorecard,
)

__all__ = [
    "aggregate_information_coefficients",
    "compute_calibration_summary",
    "compute_pearson_correlation",
    "compute_spearman_rank_correlation",
    "fractional_ranks",
    "generate_prediction_scorecard",
]
