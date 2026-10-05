"""Unit tests for statistical promotion gatekeeper engine (M11-2, Issue 257)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

from drift.domain.promotion import (
    PromotionGateVerdict,
    build_promotion_gate_config,
)
from drift.promotion.gatekeeper import (
    PromotionGatekeeper,
    calculate_deflated_sharpe_ratio,
    estimate_probability_backtest_overfitting,
    evaluate_regime_stress,
    evaluate_walk_forward_consistency,
)


def test_calculate_deflated_sharpe_ratio_single_trial() -> None:
    """Single trial with positive Sharpe has high DSR due to zero selection bias."""
    dsr = calculate_deflated_sharpe_ratio(
        observed_sharpe=Decimal("1.80"),
        trials_k=1,
        variance_of_sharpes=Decimal("0.0"),
        sample_size_n=252,
    )
    assert dsr >= Decimal("0.95")


def test_calculate_deflated_sharpe_ratio_multiple_testing_deflation() -> None:
    """Large trial count K=100 deflates modest observed Sharpe ratio."""
    # Modest Sharpe 1.20 with K=100 and variance 0.25
    dsr = calculate_deflated_sharpe_ratio(
        observed_sharpe=Decimal("1.20"),
        trials_k=100,
        variance_of_sharpes=Decimal("0.25"),
        sample_size_n=252,
    )
    assert dsr < Decimal("0.50")

    # Truly exceptional Sharpe 3.50 survives K=100 multiple testing
    dsr_high = calculate_deflated_sharpe_ratio(
        observed_sharpe=Decimal("3.50"),
        trials_k=100,
        variance_of_sharpes=Decimal("0.25"),
        sample_size_n=252,
    )
    assert dsr_high >= Decimal("0.95")


def test_estimate_probability_backtest_overfitting() -> None:
    """PBO accurately detects overfitted trial selections."""
    # Trial 0 has high returns in first 3 blocks but severe losses in last 3 blocks
    overfit_matrix = [
        [10.0, 10.0, 10.0, -10.0, -10.0, -10.0],
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0],
    ]
    pbo = estimate_probability_backtest_overfitting(overfit_matrix)
    assert pbo >= Decimal("0.40")

    # Uniformly superior trial 0 across all blocks has zero PBO
    stable_matrix = [
        [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
    ]
    pbo_stable = estimate_probability_backtest_overfitting(stable_matrix)
    assert pbo_stable == Decimal("0.0000")


def test_evaluate_walk_forward_consistency() -> None:
    """Walk-forward consistency measures positive fold proportion."""
    # 5 folds, 4 positive, 1 negative
    folds = [
        [0.01, 0.02, 0.01],
        [0.02, 0.01, 0.03],
        [-0.01, -0.02, 0.01],  # negative fold
        [0.01, 0.01, 0.02],
        [0.03, 0.02, 0.01],
    ]
    pos_frac, cum_ret = evaluate_walk_forward_consistency(folds)
    assert pos_frac == Decimal("0.8000")
    assert cum_ret > Decimal("0.0")


def test_evaluate_regime_stress() -> None:
    """Regime stress accurately measures drawdown across volatility regimes."""
    # Returns with large shock
    returns = [
        0.01,
        -0.01,
        0.02,
        -0.02,
        0.01,
        -0.01,
        0.05,
        -0.30,  # 30% drop in high vol
        0.02,
    ]
    max_dd, reg_dds = evaluate_regime_stress(returns)
    assert max_dd >= Decimal("0.25")
    assert "high_volatility" in reg_dds


def test_promotion_gatekeeper_rejections() -> None:
    """Gatekeeper fails closed on any breached statistical criteria."""
    now = datetime.now(UTC)
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        min_dsr=Decimal("0.95"),
        max_pbo=Decimal("0.30"),
        min_positive_folds_fraction=Decimal("0.80"),
        max_regime_drawdown=Decimal("0.25"),
        is_promotion_grade_authorized=False,
    )
    gk = PromotionGatekeeper(config)

    # 1. PnL incompleteness rejection
    rec1 = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.0"),
        is_pnl_complete=False,
    )
    assert rec1.verdict == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    assert "incomplete_realized_pnl_basis" in rec1.rejection_reasons

    # 2. Deflated Sharpe ratio rejection
    rec2 = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        trials_explored_k=100,
        observed_sharpe=Decimal("1.20"),
        trial_sharpes=[Decimal("1.20"), Decimal("0.80"), Decimal("-0.20")],
        is_pnl_complete=True,
    )
    assert rec2.verdict == PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    assert "deflated_sharpe_ratio_below_threshold" in rec2.rejection_reasons

    # 3. PBO overfitting rejection
    rec3 = gk.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        trial_block_matrix=[
            [10.0, 10.0, 10.0, -10.0, -10.0, -10.0],
            [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        ],
        is_pnl_complete=True,
    )
    assert rec3.verdict == PromotionGateVerdict.REJECTED_PBO_OVERFITTING
    assert "pbo_exceeds_threshold" in rec3.rejection_reasons


def test_promotion_gatekeeper_exploratory_vs_promotion_authorization() -> None:
    """Anti-laundering boundary prevents exploratory results from promotion status."""
    now = datetime.now(UTC)

    # Config without authorization
    cfg_unauth = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=False,
    )
    gk_unauth = PromotionGatekeeper(cfg_unauth)

    # Passes all statistical tests, but exploratory data
    rec_exp = gk_unauth.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="b" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=False,
    )
    assert rec_exp.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
    assert len(rec_exp.rejection_reasons) == 0

    # Passes all statistical tests with promotion-grade evidence, but config unauth
    rec_tamper = gk_unauth.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="b" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )
    # Must remain EXPLORATORY_PASSED because config has
    # is_promotion_grade_authorized=False
    assert rec_tamper.verdict == PromotionGateVerdict.EXPLORATORY_PASSED

    # Config WITH promotion authorization and promotion-grade evidence
    cfg_auth = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=True,
    )
    gk_auth = PromotionGatekeeper(cfg_auth)
    rec_promo = gk_auth.evaluate_candidate(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="b" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )
    assert rec_promo.verdict == PromotionGateVerdict.PROMOTION_QUALIFIED
