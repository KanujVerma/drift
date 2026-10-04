"""Statistical and model scorecards module (M5, Issue 12).

Provides quantitative performance attribution, predictive power analysis,
probabilistic calibration curves, drawdown trajectory analysis, portfolio
turnover, and multiple-testing adjustments.
"""

from drift.scorecards.generator import (
    ScorecardGeneratorHarness,
    deterministic_scorecard_uuid7,
    generate_model_scorecard,
)
from drift.scorecards.multiple_testing import (
    benjamini_hochberg_adjust_all,
    bonferroni_adjust_all,
    bonferroni_adjustment,
    compute_deflated_sharpe_ratio,
    compute_expected_max_null_sharpe,
    compute_multiple_testing_summary,
    compute_sample_moments,
    holm_bonferroni_adjust_all,
)
from drift.scorecards.performance import (
    compute_drawdown_profile,
    compute_return_and_risk,
    compute_turnover_summary,
    generate_strategy_scorecard,
)
from drift.scorecards.predictive import (
    aggregate_information_coefficients,
    compute_calibration_summary,
    compute_pearson_correlation,
    compute_spearman_rank_correlation,
    fractional_ranks,
    generate_prediction_scorecard,
)

__all__ = [
    "ScorecardGeneratorHarness",
    "aggregate_information_coefficients",
    "benjamini_hochberg_adjust_all",
    "bonferroni_adjust_all",
    "bonferroni_adjustment",
    "compute_calibration_summary",
    "compute_deflated_sharpe_ratio",
    "compute_drawdown_profile",
    "compute_expected_max_null_sharpe",
    "compute_multiple_testing_summary",
    "compute_pearson_correlation",
    "compute_return_and_risk",
    "compute_sample_moments",
    "compute_spearman_rank_correlation",
    "compute_turnover_summary",
    "deterministic_scorecard_uuid7",
    "fractional_ranks",
    "generate_model_scorecard",
    "generate_prediction_scorecard",
    "generate_strategy_scorecard",
    "holm_bonferroni_adjust_all",
]
