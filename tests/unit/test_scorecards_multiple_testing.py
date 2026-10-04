"""Unit tests for multiple-testing adjustment engine.

Covers M5-4 (Issue 195).
"""

from decimal import Decimal

import pytest

from drift.domain.scorecards import MultipleTestingSummaryV1
from drift.scorecards.multiple_testing import (
    benjamini_hochberg_adjust_all,
    bonferroni_adjust_all,
    bonferroni_adjustment,
    compute_deflated_sharpe_ratio,
    compute_expected_max_null_sharpe,
    compute_multiple_testing_summary,
    compute_p_value_from_sharpe,
    compute_sample_moments,
    holm_bonferroni_adjust_all,
)


def test_sample_moments_small_sample() -> None:
    returns = [Decimal("0.01")]
    mean, var, skew, kurt = compute_sample_moments(returns)
    assert mean == Decimal("0")
    assert var == Decimal("0")
    assert skew == Decimal("0")
    assert kurt == Decimal("3")


def test_sample_moments_symmetric() -> None:
    returns = [
        Decimal("-0.02"),
        Decimal("-0.01"),
        Decimal("0.00"),
        Decimal("0.01"),
        Decimal("0.02"),
    ]
    mean, var, skew, kurt = compute_sample_moments(returns)
    assert mean == Decimal("0.000000")
    assert var > Decimal("0")
    assert skew == Decimal("0.0000")
    assert kurt > Decimal("0")


def test_sample_moments_skewed() -> None:
    returns = [
        Decimal("-0.05"),
        Decimal("0.01"),
        Decimal("0.01"),
        Decimal("0.01"),
        Decimal("0.02"),
    ]
    mean, var, skew, kurt = compute_sample_moments(returns)
    assert mean == Decimal("0.000000")
    assert skew < Decimal("0")  # Negative skew from left outlier


def test_expected_max_null_sharpe_single_trial() -> None:
    var, sr_star = compute_expected_max_null_sharpe([Decimal("1.5")])
    assert var == Decimal("0")
    assert sr_star == Decimal("0")


def test_expected_max_null_sharpe_multiple_trials() -> None:
    sharpes = [
        Decimal("0.2"),
        Decimal("0.5"),
        Decimal("0.8"),
        Decimal("1.1"),
        Decimal("1.4"),
    ]
    var, sr_star = compute_expected_max_null_sharpe(sharpes)
    assert var > Decimal("0")
    assert sr_star > Decimal("0")


def test_expected_max_null_sharpe_monotonic_in_k() -> None:
    # Adding more trials with similar variance should increase expected max null Sharpe
    sharpes_small = [Decimal("0.2"), Decimal("0.8")]
    sharpes_large = [
        Decimal("0.2"),
        Decimal("0.8"),
        Decimal("0.3"),
        Decimal("0.7"),
        Decimal("0.4"),
        Decimal("0.6"),
        Decimal("0.2"),
        Decimal("0.8"),
        Decimal("0.5"),
        Decimal("0.5"),
    ]
    _, sr_star_small = compute_expected_max_null_sharpe(sharpes_small)
    _, sr_star_large = compute_expected_max_null_sharpe(sharpes_large)
    assert sr_star_large > sr_star_small


def test_deflated_sharpe_ratio_single_trial() -> None:
    # Single trial with high Sharpe and 252 sessions
    dsr = compute_deflated_sharpe_ratio(
        candidate_sharpe=Decimal("2.50"),
        expected_max_null_sharpe=Decimal("0.0"),
        sample_size_sessions=252,
    )
    assert dsr >= Decimal("0.9500")


def test_deflated_sharpe_ratio_deflated_by_selection() -> None:
    # High Sharpe candidate, but expected max null Sharpe under selection is also high
    candidate = Decimal("1.20")
    expected_null_low = Decimal("0.20")
    expected_null_high = Decimal("1.50")

    dsr_undefeated = compute_deflated_sharpe_ratio(
        candidate_sharpe=candidate,
        expected_max_null_sharpe=expected_null_low,
        sample_size_sessions=100,
    )
    dsr_deflated = compute_deflated_sharpe_ratio(
        candidate_sharpe=candidate,
        expected_max_null_sharpe=expected_null_high,
        sample_size_sessions=100,
    )
    assert dsr_undefeated > dsr_deflated
    assert dsr_deflated < Decimal("0.5000")


def test_bonferroni_adjustment() -> None:
    assert bonferroni_adjustment(Decimal("0.01"), 1) == Decimal("0.0100")
    assert bonferroni_adjustment(Decimal("0.01"), 5) == Decimal("0.0500")
    assert bonferroni_adjustment(Decimal("0.25"), 10) == Decimal("1.0000")  # Clamped

    with pytest.raises(ValueError, match="trial_count must be at least 1"):
        bonferroni_adjustment(Decimal("0.05"), 0)

    seq = [Decimal("0.01"), Decimal("0.02"), Decimal("0.05")]
    adjusted = bonferroni_adjust_all(seq)
    assert adjusted == [Decimal("0.0300"), Decimal("0.0600"), Decimal("0.1500")]


def test_holm_bonferroni_adjustment() -> None:
    raw_p = [Decimal("0.01"), Decimal("0.04"), Decimal("0.03")]
    adj = holm_bonferroni_adjust_all(raw_p)

    # Sorted: 0.01 (k=1, mult=3 -> 0.03), 0.03 (k=2, mult=2 -> 0.06),
    # 0.04 (k=3, mult=1 -> 0.04 -> max(0.06, 0.04) = 0.06)
    # Original order restored: [0.0300, 0.0600, 0.0600]
    assert adj[0] == Decimal("0.0300")
    assert adj[1] == Decimal("0.0600")
    assert adj[2] == Decimal("0.0600")


def test_benjamini_hochberg_adjustment() -> None:
    raw_p = [Decimal("0.01"), Decimal("0.04"), Decimal("0.03")]
    adj = benjamini_hochberg_adjust_all(raw_p)

    # Sorted: p_(1)=0.01 (mult 3/1=3 -> 0.03), p_(2)=0.03 (mult 3/2=1.5 -> 0.045),
    # p_(3)=0.04 (mult 3/3=1 -> 0.04)
    # Step-up monotonicity: q_(3)=0.04, q_(2)=min(0.045, 0.04)=0.04,
    # q_(1)=min(0.03, 0.04)=0.03
    # Restored to original indices: [0.0300, 0.0400, 0.0400]
    assert adj[0] == Decimal("0.0300")
    assert adj[1] == Decimal("0.0400")
    assert adj[2] == Decimal("0.0400")


def test_compute_p_value_from_sharpe() -> None:
    # Very high Sharpe -> p-value near 0
    p_high = compute_p_value_from_sharpe(Decimal("3.0"), 252)
    assert p_high < Decimal("0.01")

    # Zero Sharpe -> p-value = 1.0
    p_zero = compute_p_value_from_sharpe(Decimal("0.0"), 252)
    assert p_zero == Decimal("1.0000")


def test_compute_multiple_testing_summary_integration() -> None:
    trials = [
        Decimal("0.5"),
        Decimal("0.8"),
        Decimal("1.2"),
        Decimal("1.8"),
    ]
    summary = compute_multiple_testing_summary(
        candidate_sharpe=Decimal("1.8"),
        trial_sharpe_ratios=trials,
        sample_size_sessions=252,
    )
    assert isinstance(summary, MultipleTestingSummaryV1)
    assert summary.trial_count == 4
    assert summary.sharpe_trial_variance > Decimal("0")
    assert summary.expected_max_null_sharpe > Decimal("0")
    assert Decimal("0") <= summary.deflated_sharpe_ratio <= Decimal("1")
    assert Decimal("0") <= summary.bonferroni_adjusted_p_value <= Decimal("1")
    assert Decimal("0") <= summary.holm_adjusted_p_value <= Decimal("1")
    assert Decimal("0") <= summary.benjamini_hochberg_fdr_q <= Decimal("1")
