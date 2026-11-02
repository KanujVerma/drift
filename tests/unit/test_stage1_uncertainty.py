"""Unit tests for Stage 1 paired uncertainty and N6 quantile interpolation."""

from decimal import Decimal

from drift.experiments.stage1_uncertainty import (
    compute_paired_uncertainty_artifact,
    compute_quantile_linear_interpolation,
    generate_stationary_bootstrap_indices,
)


def test_n6_quantile_linear_interpolation() -> None:
    # Sorted replicate statistics 0 through 9999 produce:
    # 2.5% quantile 249.975 and 97.5% quantile 9749.025
    sorted_values = [Decimal(i) for i in range(10000)]
    q_025 = compute_quantile_linear_interpolation(sorted_values, 0.025)
    q_975 = compute_quantile_linear_interpolation(sorted_values, 0.975)

    assert q_025 == Decimal("249.975")
    assert q_975 == Decimal("9749.025")


def test_n6_identical_returns_paired_differences_are_zero() -> None:
    returns = [Decimal("0.01"), Decimal("-0.01"), Decimal("0.02")] * 40
    artifact = compute_paired_uncertainty_artifact(
        b_returns=returns,
        r_returns=returns,
        initial_capital=Decimal("10000"),
        incremental_operating_costs=Decimal("0"),
        mean_block_length=5,
        seed=575,
    )
    assert artifact.primary_nav_diff_point == Decimal("0")
    assert artifact.primary_economic_point == Decimal("0")
    assert artifact.primary_nav_diff_interval == (Decimal("0"), Decimal("0"))
    assert artifact.primary_economic_interval == (Decimal("0"), Decimal("0"))


def test_paired_bootstrap_indices_reproducible_digest() -> None:
    indices_1, digest_1 = generate_stationary_bootstrap_indices(
        n=100, mean_block_length=5, replicate_count=1000, seed=575
    )
    indices_2, digest_2 = generate_stationary_bootstrap_indices(
        n=100, mean_block_length=5, replicate_count=1000, seed=575
    )
    assert digest_1 == digest_2
    assert len(digest_1) == 64
    assert indices_1 == indices_2


def test_paired_uncertainty_with_daily_operating_costs() -> None:
    b_returns = [Decimal("0.02")] * 50
    r_returns = [Decimal("0.01")] * 50
    daily_costs = [Decimal("0.50")] * 50
    artifact = compute_paired_uncertainty_artifact(
        b_returns=b_returns,
        r_returns=r_returns,
        daily_incremental_operating_costs=daily_costs,
        one_time_operating_costs=Decimal("10.00"),
        mean_block_length=5,
        seed=575,
    )
    assert artifact.primary_economic_point is not None
    assert artifact.primary_economic_interval is not None
