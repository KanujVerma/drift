"""Unit tests for Stage 1 conventional policy, N1 oracle math, and N2 tie breaking."""

from decimal import Decimal

import pytest

from drift.intelligence.stage1_conventional_policy import (
    break_r_ties,
    compute_r_utility,
)


def test_n1_returns_and_126_interval_r_statistics() -> None:
    # NAV path: 100, 110, 99, followed by 124 marks of 99 (127 total marks)
    navs = [Decimal("100"), Decimal("110")] + [Decimal("99")] * 125
    assert len(navs) == 127

    res = compute_r_utility(
        navs,
        lambda_v=Decimal("0.25"),
        lambda_d=Decimal("0.50"),
        transition_cost=Decimal("0.001"),
    )

    assert res.compounded_return == Decimal("-0.01")
    assert res.mean_return == Decimal("0")
    assert res.sample_variance == Decimal("0.00016")
    assert res.maximum_drawdown == Decimal("0.10")

    # Cross-check against 80-digit oracle: absolute error must be below 1e-30
    oracle_80 = Decimal("-0.09649647869859769625540396974936970229")
    abs_err = abs(res.utility - oracle_80)
    assert abs_err < Decimal("1e-30")


def test_n2_exact_versus_approximate_ties() -> None:
    # 1. B3 utility 0.0100000000, B4 0.0100000005, B3 incumbent: B4 wins
    scores_1 = {
        "B3": Decimal("0.0100000000"),
        "B4": Decimal("0.0100000005"),
    }
    assert break_r_ties(scores_1, incumbent="B3") == "B4"

    # 2. Exactly equal utilities and valid B5 incumbent: B5 wins
    scores_equal = {
        "B3": Decimal("0.0500000000"),
        "B4": Decimal("0.0500000000"),
        "B5": Decimal("0.0500000000"),
    }
    assert break_r_ties(scores_equal, incumbent="B5") == "B5"

    # 3. Exactly equal utilities and no valid eligible incumbent: B3 wins
    assert break_r_ties(scores_equal, incumbent=None) == "B3"

    # 4. Permuting pool order changes nothing
    scores_permuted = {
        "B5": Decimal("0.0500000000"),
        "B4": Decimal("0.0500000000"),
        "B3": Decimal("0.0500000000"),
    }
    assert break_r_ties(scores_permuted, incumbent="B5") == "B5"
    assert break_r_ties(scores_permuted, incumbent=None) == "B3"


def test_r_utility_rejects_invalid_mark_counts() -> None:
    with pytest.raises(ValueError, match="R_UTILITY_REQUIRES_127_MARKS"):
        compute_r_utility(
            [Decimal("100")] * 126,
            lambda_v=Decimal("0.25"),
            lambda_d=Decimal("0.50"),
            transition_cost=Decimal("0"),
        )


def test_r_utility_rejects_non_positive_nav() -> None:
    navs = [Decimal("100")] * 126 + [Decimal("0")]
    with pytest.raises(ValueError, match="R_UTILITY_NON_POSITIVE_NAV"):
        compute_r_utility(
            navs,
            lambda_v=Decimal("0.25"),
            lambda_d=Decimal("0.50"),
            transition_cost=Decimal("0"),
        )
