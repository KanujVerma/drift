"""Unit tests for Stage 1 scientific metric calculation engine.

Tests all 12 analytical golden fixtures from PR #435 Section 5 (#382),
individual calculation functions, and adversarial/negative failure cases
per Issue #445.
"""

import math
from decimal import Decimal

import pytest

from drift.experiments.stage1_metric_math import (
    CALCULATION_PRECISION,
    REASON_EMPTY_SERIES,
    REASON_FLOAT_INPUT_PROHIBITED,
    REASON_INSUFFICIENT_OBSERVATIONS,
    REASON_INVALID_PERIODS_PER_YEAR,
    REASON_IRREGULAR_SPACING,
    REASON_MISSING_MAR_SERIES,
    REASON_MISSING_OPERATING_COST,
    REASON_MISSING_RISK_FREE_SERIES,
    REASON_MISSING_VALUATION_MARK,
    REASON_NAN_OR_INFINITY_INPUT,
    REASON_NEGATIVE_NAV,
    REASON_NEGATIVE_OPERATING_COST,
    REASON_NONPOSITIVE_STARTING_NAV,
    REASON_SERIES_LENGTH_MISMATCH,
    REASON_ZERO_DOWNSIDE_DEVIATION,
    REASON_ZERO_MAXIMUM_DRAWDOWN,
    REASON_ZERO_NAV_DIVISOR,
    REASON_ZERO_SAMPLE_VARIANCE,
    MetricArithmeticValue,
    calculate_calmar_ratio,
    calculate_comparative_economic_advantage,
    calculate_economic_gain,
    calculate_geometric_annualized_return,
    calculate_maximum_drawdown,
    calculate_paired_return_differences,
    calculate_periodic_excess_returns,
    calculate_periodic_excess_sharpe,
    calculate_periodic_returns,
    calculate_sample_excess_variance_and_volatility,
    calculate_sortino_ratio,
    calculate_stage1_arithmetic,
    calculate_terminal_return,
)

# ==============================================================================
# SECTION 1: ALL TWELVE GOLDEN CASES (PR #435 / Issue #445)
# ==============================================================================


def test_golden_case_1_standard_evaluation_sequence() -> None:
    """Golden Case 1: Standard Evaluation Sequence (Primary Fixture).

    NAV: [10000, 11000, 8800, 9680]
    rf: [0, 0, 0], MAR: [0, 0, 0], K: 252
    Terminal Return: -0.0320 (KNOWN)
    MDD: -0.2000 (KNOWN)
    True Periodic Sharpe: 0.0000 (KNOWN)
    """
    nav = [Decimal("10000"), Decimal("11000"), Decimal("8800"), Decimal("9680")]
    rf = [Decimal("0"), Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    # 1. Periodic returns: +0.10, -0.20, +0.10
    assert isinstance(metrics.periodic_returns, tuple)
    assert len(metrics.periodic_returns) == 3
    assert metrics.periodic_returns[0].state == "KNOWN"
    assert metrics.periodic_returns[0].value == Decimal("0.10")
    assert metrics.periodic_returns[1].state == "KNOWN"
    assert metrics.periodic_returns[1].value == Decimal("-0.20")
    assert metrics.periodic_returns[2].state == "KNOWN"
    assert metrics.periodic_returns[2].value == Decimal("0.10")

    # 2. Terminal return: 9680 / 10000 - 1 = -0.0320
    assert metrics.terminal_return.state == "KNOWN"
    assert metrics.terminal_return.value == Decimal("-0.0320")

    # 3. Maximum drawdown: -0.2000
    assert metrics.maximum_drawdown.state == "KNOWN"
    assert metrics.maximum_drawdown.value == Decimal("-0.2000")

    # 4. True Periodic Sharpe: exactly 0.0000 (mean = 0, sample std = sqrt(0.03) > 0)
    assert metrics.periodic_excess_sharpe.state == "KNOWN"
    assert metrics.periodic_excess_sharpe.value == Decimal("0")

    # 5. Geometric Annualized Return: (0.968)^84 - 1 approx -0.93490764
    assert metrics.geometric_annualized_return.state == "KNOWN"
    assert metrics.geometric_annualized_return.value is not None
    assert str(metrics.geometric_annualized_return.value).startswith("-0.93490764")

    # 6. Sortino: 0.0000 (mean shortfall = -0.20/3, downside std = sqrt(0.04/3) > 0)
    assert metrics.sortino.state == "KNOWN"
    assert metrics.sortino.value == Decimal("0")

    # 7. Calmar: R_ann / abs(MDD) = -0.93490764... / 0.20 approx -4.6745...
    assert metrics.calmar.state == "KNOWN"
    assert metrics.calmar.value is not None
    assert str(metrics.calmar.value).startswith("-4.6745")


def test_golden_case_2_constant_cash_zero_volatility() -> None:
    """Golden Case 2: Constant Cash Account (Zero Volatility).

    NAV: [10000, 10000, 10000]
    rf: [0, 0]
    Sharpe: UNDEFINED (ZERO_SAMPLE_VARIANCE), never zero!
    Calmar: UNDEFINED (ZERO_MAXIMUM_DRAWDOWN), never zero!
    """
    nav = [Decimal("10000"), Decimal("10000"), Decimal("10000")]
    rf = [Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.terminal_return.state == "KNOWN"
    assert metrics.terminal_return.value == Decimal("0")

    assert metrics.maximum_drawdown.state == "KNOWN"
    assert metrics.maximum_drawdown.value == Decimal("0")

    # Sharpe is UNDEFINED with reason ZERO_SAMPLE_VARIANCE, not 0.0
    assert metrics.periodic_excess_sharpe.state == "UNDEFINED"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_ZERO_SAMPLE_VARIANCE
    assert metrics.periodic_excess_sharpe.value is None

    # Sortino is UNDEFINED with reason ZERO_DOWNSIDE_DEVIATION
    assert metrics.sortino.state == "UNDEFINED"
    assert metrics.sortino.reason_code == REASON_ZERO_DOWNSIDE_DEVIATION
    assert metrics.sortino.value is None

    # Calmar is UNDEFINED with reason ZERO_MAXIMUM_DRAWDOWN, not 0.0
    assert metrics.calmar.state == "UNDEFINED"
    assert metrics.calmar.reason_code == REASON_ZERO_MAXIMUM_DRAWDOWN
    assert metrics.calmar.value is None


def test_golden_case_3_one_period_insufficient_observations() -> None:
    """Golden Case 3: One-Period Account History (Insufficient Observations).

    NAV: [10000, 10500]
    rf: [0]
    Sharpe: UNAVAILABLE (INSUFFICIENT_OBSERVATIONS)
    """
    nav = [Decimal("10000"), Decimal("10500")]
    rf = [Decimal("0")]
    mar = [Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.terminal_return.state == "KNOWN"
    assert metrics.terminal_return.value == Decimal("0.05")

    assert metrics.periodic_excess_sharpe.state == "UNAVAILABLE"
    assert (
        metrics.periodic_excess_sharpe.reason_code == REASON_INSUFFICIENT_OBSERVATIONS
    )
    assert metrics.periodic_excess_sharpe.value is None


def test_golden_case_4_identical_positive_returns() -> None:
    """Golden Case 4: Identical Positive Returns.

    NAV: [10000, 10200, 10404]
    rf: [0, 0]
    r = [+0.02, +0.02], mean = +0.02, variance = 0.0
    Sharpe: UNDEFINED (ZERO_SAMPLE_VARIANCE)
    """
    nav = [Decimal("10000"), Decimal("10200"), Decimal("10404")]
    rf = [Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.terminal_return.state == "KNOWN"
    assert metrics.terminal_return.value == Decimal("0.0404")

    assert metrics.periodic_excess_sharpe.state == "UNDEFINED"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_ZERO_SAMPLE_VARIANCE
    assert metrics.periodic_excess_sharpe.value is None


def test_golden_case_5_large_loss_partial_recovery() -> None:
    """Golden Case 5: Large Loss Followed by Partial Recovery.

    NAV: [10000, 5000, 7500]
    rf: [0, 0]
    r1 = -0.50, r2 = +0.50
    Terminal: -0.2500, MDD: -0.5000, Sharpe: 0.0000 (KNOWN)
    """
    nav = [Decimal("10000"), Decimal("5000"), Decimal("7500")]
    rf = [Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.terminal_return.state == "KNOWN"
    assert metrics.terminal_return.value == Decimal("-0.2500")

    assert metrics.maximum_drawdown.state == "KNOWN"
    assert metrics.maximum_drawdown.value == Decimal("-0.5000")

    assert metrics.periodic_excess_sharpe.state == "KNOWN"
    assert metrics.periodic_excess_sharpe.value == Decimal("0")


def test_golden_case_6_missing_session_valuation_mark() -> None:
    """Golden Case 6: Missing Session Valuation Mark.

    NAV: [10000, 11000, None, 9680]
    Dependent path metrics = UNAVAILABLE (MISSING_VALUATION_MARK)
    """
    nav = [Decimal("10000"), Decimal("11000"), None, Decimal("9680")]
    rf = [Decimal("0"), Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert isinstance(metrics.periodic_returns, tuple)
    assert metrics.periodic_returns[0].state == "KNOWN"
    assert metrics.periodic_returns[0].value == Decimal("0.10")
    assert metrics.periodic_returns[1].state == "UNAVAILABLE"
    assert metrics.periodic_returns[1].reason_code == REASON_MISSING_VALUATION_MARK
    assert metrics.periodic_returns[2].state == "UNAVAILABLE"
    assert metrics.periodic_returns[2].reason_code == REASON_MISSING_VALUATION_MARK

    # Path metrics are UNAVAILABLE
    assert metrics.periodic_excess_sharpe.state == "UNAVAILABLE"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_MISSING_VALUATION_MARK

    assert metrics.maximum_drawdown.state == "UNAVAILABLE"
    assert metrics.maximum_drawdown.reason_code == REASON_MISSING_VALUATION_MARK

    assert metrics.geometric_annualized_return.state == "UNAVAILABLE"
    assert (
        metrics.geometric_annualized_return.reason_code == REASON_MISSING_VALUATION_MARK
    )

    assert metrics.sortino.state == "UNAVAILABLE"
    assert metrics.sortino.reason_code == REASON_MISSING_VALUATION_MARK

    assert metrics.calmar.state == "UNAVAILABLE"
    assert metrics.calmar.reason_code == REASON_MISSING_VALUATION_MARK


def test_golden_case_7_mixed_irregular_session_spacing() -> None:
    """Golden Case 7: Mixed or Irregular Session Spacing.

    When spacing is not certified uniform, annualization evaluates to
    UNAVAILABLE (IRREGULAR_SPACING).
    """
    nav = [Decimal("10000"), Decimal("10100"), Decimal("10200")]
    rf = [Decimal("0"), Decimal("0")]
    mar = [Decimal("0"), Decimal("0")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
        spacing_verified=False,
    )

    assert metrics.geometric_annualized_return.state == "UNAVAILABLE"
    assert metrics.geometric_annualized_return.reason_code == REASON_IRREGULAR_SPACING


def test_golden_case_8_zero_variance_nonzero_excess_return() -> None:
    """Golden Case 8: Zero Variance with Nonzero Excess Return.

    NAV: [10000, 10100, 10201], rf: [0.005, 0.005]
    r = [0.01, 0.01], e = [0.005, 0.005]
    Sharpe: UNDEFINED (ZERO_SAMPLE_VARIANCE), never infinity or zero!
    """
    nav = [Decimal("10000"), Decimal("10100"), Decimal("10201")]
    rf = [Decimal("0.005"), Decimal("0.005")]
    mar = [Decimal("0.005"), Decimal("0.005")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.periodic_excess_sharpe.state == "UNDEFINED"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_ZERO_SAMPLE_VARIANCE
    assert metrics.periodic_excess_sharpe.value is None


def test_golden_case_9_negative_portfolio_return_valid_volatility() -> None:
    """Golden Case 9: Negative Portfolio Return with Valid Volatility.

    NAV: [10000, 9800, 9702], rf: [0.001, 0.001], K: 252
    r = [-0.02, -0.01], e = [-0.021, -0.011]
    e_bar = -0.016, s_e^2 = 0.00005
    Sharpe approx -35.92 (finite negative real value).
    """
    nav = [Decimal("10000"), Decimal("9800"), Decimal("9702")]
    rf = [Decimal("0.001"), Decimal("0.001")]
    mar = [Decimal("0.001"), Decimal("0.001")]
    k = 252

    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=rf,
        mar_period_returns=mar,
        periods_per_year=k,
    )

    assert metrics.periodic_excess_sharpe.state == "KNOWN"
    assert metrics.periodic_excess_sharpe.value is not None
    # Check that Sharpe is approximately -35.92
    val = float(metrics.periodic_excess_sharpe.value)
    assert math.isclose(val, -35.9199, rel_tol=1e-4)
    assert str(metrics.periodic_excess_sharpe.value).startswith("-35.9199")


def test_golden_case_10_trading_cost_three_tier_attribution() -> None:
    """Golden Case 10: Trading Cost Accounting Fixture (Three-Tier Attribution).

    Initial Net NAV: 10000.00
    Terminal Net NAV: 9960.00 (net of 160 trading transaction cost)
    Research Operating Costs: 80.00
    Economic Gain: 9960 - 10000 - 80 = -120.00 (KNOWN)
    Trading costs (160) are not debited a second time.
    """
    init_nav = Decimal("10000.00")
    term_nav = Decimal("9960.00")
    op_cost = Decimal("80.00")

    gain = calculate_economic_gain(
        initial_net_nav=init_nav,
        terminal_net_nav=term_nav,
        attributed_operating_cost=op_cost,
    )

    assert gain.state == "KNOWN"
    assert gain.value == Decimal("-120.00")


def test_golden_case_11_unknown_operating_expense() -> None:
    """Golden Case 11: Unknown Operating Expense.

    Initial Net NAV: 10000.00, Terminal Net NAV: 9960.00
    Operating Cost: None (unknown)
    Portfolio Terminal Net Return: -0.0040 (KNOWN)
    Total Economic Gain: UNAVAILABLE (MISSING_OPERATING_COST)
    """
    init_nav = Decimal("10000.00")
    term_nav = Decimal("9960.00")

    term_ret = calculate_terminal_return([init_nav, term_nav])
    assert term_ret.state == "KNOWN"
    assert term_ret.value == Decimal("-0.0040")

    gain = calculate_economic_gain(
        initial_net_nav=init_nav,
        terminal_net_nav=term_nav,
        attributed_operating_cost=None,
    )
    assert gain.state == "UNAVAILABLE"
    assert gain.reason_code == REASON_MISSING_OPERATING_COST
    assert gain.value is None


def test_golden_case_12_paired_b_r_comparison() -> None:
    """Golden Case 12: Paired B/R Comparison.

    Computes paired differences d_t = r_b[t] - r_r[t] and comparative
    economic advantage without assuming arm independence or adjacent-day
    independence. No hypothesis test or p-value computed.
    """
    # 126 observation sessions stand-in
    b_rets = [
        MetricArithmeticValue(f"b_{t}", state="KNOWN", value=Decimal("0.001"))
        for t in range(1, 127)
    ]
    r_rets = [
        MetricArithmeticValue(f"r_{t}", state="KNOWN", value=Decimal("0.0005"))
        for t in range(1, 127)
    ]

    diffs = calculate_paired_return_differences(
        b_returns=b_rets,
        r_returns=r_rets,
    )
    assert isinstance(diffs, tuple)
    assert len(diffs) == 126
    for d in diffs:
        assert d.state == "KNOWN"
        assert d.value == Decimal("0.0005")

    # Economic gain comparison
    b_gain = MetricArithmeticValue(
        metric_name="b_gain", state="KNOWN", value=Decimal("250.00")
    )
    r_gain = MetricArithmeticValue(
        metric_name="r_gain", state="KNOWN", value=Decimal("100.00")
    )

    advantage = calculate_comparative_economic_advantage(b_gain, r_gain)
    assert advantage.state == "KNOWN"
    assert advantage.value == Decimal("150.00")

    # Propagates missing/invalid status
    missing_r_gain = MetricArithmeticValue(
        metric_name="r_gain",
        state="UNAVAILABLE",
        reason_code=REASON_MISSING_OPERATING_COST,
    )
    adv_missing = calculate_comparative_economic_advantage(b_gain, missing_r_gain)
    assert adv_missing.state == "UNAVAILABLE"
    assert adv_missing.reason_code == REASON_MISSING_OPERATING_COST
    assert adv_missing.value is None


# ==============================================================================
# SECTION 2: INDIVIDUAL CALCULATION FUNCTIONS DIRECT TESTS
# ==============================================================================


def test_individual_periodic_returns_and_zero_divisor() -> None:
    """Test calculate_periodic_returns with zero NAV divisor."""
    nav = [Decimal("10000"), Decimal("0"), Decimal("5000")]
    rets = calculate_periodic_returns(nav)
    assert isinstance(rets, tuple)
    assert len(rets) == 2
    # t=1: 0 / 10000 - 1 = -1.0
    assert rets[0].state == "KNOWN"
    assert rets[0].value == Decimal("-1.0")
    # t=2: 5000 / 0 - 1 => ZERO_NAV_DIVISOR
    assert rets[1].state == "UNDEFINED"
    assert rets[1].reason_code == REASON_ZERO_NAV_DIVISOR


def test_individual_geometric_annualized_return() -> None:
    """Test calculate_geometric_annualized_return edge cases."""
    # Total loss: R_terminal = -1.0 => R_ann = -1.0
    t_loss = MetricArithmeticValue("terminal", state="KNOWN", value=Decimal("-1.0"))
    ann_loss = calculate_geometric_annualized_return(
        terminal_return=t_loss, completed_periods=252, periods_per_year=252
    )
    assert ann_loss.state == "KNOWN"
    assert ann_loss.value == Decimal("-1.0")

    # Precision check
    assert CALCULATION_PRECISION >= 50


def test_individual_excess_variance_and_volatility() -> None:
    """Test calculate_sample_excess_variance_and_volatility."""
    e_rets = [
        MetricArithmeticValue("e1", state="KNOWN", value=Decimal("0.10")),
        MetricArithmeticValue("e2", state="KNOWN", value=Decimal("-0.20")),
        MetricArithmeticValue("e3", state="KNOWN", value=Decimal("0.10")),
    ]
    var_m, std_m, vol_m = calculate_sample_excess_variance_and_volatility(
        excess_returns=e_rets, periods_per_year=252
    )
    assert var_m.state == "KNOWN"
    assert var_m.value == Decimal("0.03")

    assert std_m.state == "KNOWN"
    assert std_m.value is not None

    assert vol_m.state == "KNOWN"
    assert vol_m.value is not None

    # Sharpe on these excess returns
    sharpe = calculate_periodic_excess_sharpe(
        excess_returns=e_rets, periods_per_year=252
    )
    assert sharpe.state == "KNOWN"
    assert sharpe.value == Decimal("0")


def test_individual_drawdown_and_calmar() -> None:
    """Test calculate_maximum_drawdown and calculate_calmar_ratio."""
    nav = [Decimal("10000"), Decimal("12000"), Decimal("9000"), Decimal("15000")]
    mdd = calculate_maximum_drawdown(nav)
    assert mdd.state == "KNOWN"
    # Peak at 12000, trough at 9000 => 9000/12000 - 1 = -0.25
    assert mdd.value == Decimal("-0.25")

    r_ann = MetricArithmeticValue("ann", state="KNOWN", value=Decimal("0.10"))
    calmar = calculate_calmar_ratio(
        geometric_annualized_return=r_ann, maximum_drawdown=mdd
    )
    assert calmar.state == "KNOWN"
    assert calmar.value == Decimal("0.10") / Decimal("0.25")  # 0.40


def test_individual_periodic_excess_and_sortino() -> None:
    """Test calculate_periodic_excess_returns and calculate_sortino_ratio."""
    p_rets = [
        MetricArithmeticValue("r1", state="KNOWN", value=Decimal("0.05")),
        MetricArithmeticValue("r2", state="KNOWN", value=Decimal("-0.02")),
    ]
    rf = [Decimal("0.01"), Decimal("0.01")]
    excess = calculate_periodic_excess_returns(
        periodic_returns=p_rets, risk_free_period_returns=rf
    )
    assert isinstance(excess, tuple)
    assert len(excess) == 2
    assert excess[0].value == Decimal("0.04")
    assert excess[1].value == Decimal("-0.03")

    sortino = calculate_sortino_ratio(
        periodic_returns=p_rets, mar_period_returns=rf, periods_per_year=252
    )
    assert sortino.state == "KNOWN"
    assert sortino.value is not None


# ==============================================================================
# SECTION 3: ADVERSARIAL AND NEGATIVE CASES
# ==============================================================================


def test_negative_invalid_initial_nav() -> None:
    """Nonpositive initial NAV (<= 0) fails closed with NONPOSITIVE_STARTING_NAV."""
    for bad_init in [Decimal("0"), Decimal("-1000")]:
        metrics = calculate_stage1_arithmetic(
            nav_marks=[bad_init, Decimal("10000")],
            risk_free_period_returns=[Decimal("0")],
            mar_period_returns=[Decimal("0")],
            periods_per_year=252,
        )
        assert metrics.terminal_return.state == "INVALID"
        assert metrics.terminal_return.reason_code == REASON_NONPOSITIVE_STARTING_NAV
        assert metrics.periodic_excess_sharpe.state == "INVALID"


def test_negative_nav_in_series() -> None:
    """Negative NAV in series fails closed with NEGATIVE_NAV."""
    metrics = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000"), Decimal("-500"), Decimal("9000")],
        risk_free_period_returns=[Decimal("0"), Decimal("0")],
        mar_period_returns=[Decimal("0"), Decimal("0")],
        periods_per_year=252,
    )
    assert metrics.terminal_return.state == "INVALID"
    assert metrics.terminal_return.reason_code == REASON_NEGATIVE_NAV


def test_negative_missing_risk_free_series() -> None:
    """Missing risk-free series fails closed into UNAVAILABLE."""
    metrics = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000"), Decimal("11000"), Decimal("12000")],
        risk_free_period_returns=None,
        mar_period_returns=[Decimal("0"), Decimal("0")],
        periods_per_year=252,
    )
    assert metrics.periodic_excess_sharpe.state == "UNAVAILABLE"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_MISSING_RISK_FREE_SERIES
    assert metrics.terminal_return.state == "KNOWN"

    # Missing MAR series fails closed into UNAVAILABLE
    metrics_mar = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000"), Decimal("11000"), Decimal("12000")],
        risk_free_period_returns=[Decimal("0"), Decimal("0")],
        mar_period_returns=None,
        periods_per_year=252,
    )
    assert metrics_mar.sortino.state == "UNAVAILABLE"
    assert metrics_mar.sortino.reason_code == REASON_MISSING_MAR_SERIES


def test_negative_mismatched_array_lengths() -> None:
    """Mismatched array lengths fail closed with SERIES_LENGTH_MISMATCH."""
    nav = [Decimal("10000"), Decimal("11000"), Decimal("12000")]  # n = 2 intervals

    # rf length 1 instead of 2
    metrics = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=[Decimal("0")],
        mar_period_returns=[Decimal("0"), Decimal("0")],
        periods_per_year=252,
    )
    assert metrics.periodic_excess_sharpe.state == "INVALID"
    assert metrics.periodic_excess_sharpe.reason_code == REASON_SERIES_LENGTH_MISMATCH

    # mar length 3 instead of 2
    metrics_mar = calculate_stage1_arithmetic(
        nav_marks=nav,
        risk_free_period_returns=[Decimal("0"), Decimal("0")],
        mar_period_returns=[Decimal("0"), Decimal("0"), Decimal("0")],
        periods_per_year=252,
    )
    assert metrics_mar.sortino.state == "INVALID"
    assert metrics_mar.sortino.reason_code == REASON_SERIES_LENGTH_MISMATCH


def test_negative_float_input_contamination() -> None:
    """Float inputs are prohibited and fail closed with FLOAT_INPUT_PROHIBITED."""
    # Float in nav_marks
    metrics = calculate_stage1_arithmetic(
        nav_marks=[10000.0, 11000.0],  # type: ignore[list-item]
        risk_free_period_returns=[Decimal("0")],
        mar_period_returns=[Decimal("0")],
        periods_per_year=252,
    )
    assert metrics.terminal_return.state == "INVALID"
    assert metrics.terminal_return.reason_code == REASON_FLOAT_INPUT_PROHIBITED

    # Float in risk_free
    metrics_rf = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000"), Decimal("11000")],
        risk_free_period_returns=[0.0],  # type: ignore[list-item]
        mar_period_returns=[Decimal("0")],
        periods_per_year=252,
    )
    assert metrics_rf.periodic_excess_sharpe.state == "INVALID"
    assert (
        metrics_rf.periodic_excess_sharpe.reason_code == REASON_FLOAT_INPUT_PROHIBITED
    )

    # Float in economic gain
    gain = calculate_economic_gain(
        initial_net_nav=10000.0,  # type: ignore[arg-type]
        terminal_net_nav=Decimal("9960.00"),
        attributed_operating_cost=Decimal("80.00"),
    )
    assert gain.state == "INVALID"
    assert gain.reason_code == REASON_FLOAT_INPUT_PROHIBITED


def test_negative_nan_or_infinity_contamination() -> None:
    """Decimal NaN or Infinity values fail closed with NAN_OR_INFINITY_INPUT."""
    for bad_val in [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]:
        metrics = calculate_stage1_arithmetic(
            nav_marks=[Decimal("10000"), bad_val],
            risk_free_period_returns=[Decimal("0")],
            mar_period_returns=[Decimal("0")],
            periods_per_year=252,
        )
        assert metrics.terminal_return.state == "INVALID"
        assert metrics.terminal_return.reason_code == REASON_NAN_OR_INFINITY_INPUT


def test_negative_invalid_periods_per_year() -> None:
    """periods_per_year < 1 fails closed with INVALID_PERIODS_PER_YEAR."""
    metrics = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000"), Decimal("11000")],
        risk_free_period_returns=[Decimal("0")],
        mar_period_returns=[Decimal("0")],
        periods_per_year=0,
    )
    assert metrics.geometric_annualized_return.state == "INVALID"
    assert (
        metrics.geometric_annualized_return.reason_code
        == REASON_INVALID_PERIODS_PER_YEAR
    )


def test_negative_empty_or_singleton_nav() -> None:
    """Empty or singleton series handling."""
    # Empty
    metrics_empty = calculate_stage1_arithmetic(
        nav_marks=[],
        risk_free_period_returns=[],
        mar_period_returns=[],
        periods_per_year=252,
    )
    assert metrics_empty.terminal_return.state == "INVALID"
    assert metrics_empty.terminal_return.reason_code == REASON_EMPTY_SERIES

    # Singleton (n = 0 intervals)
    metrics_single = calculate_stage1_arithmetic(
        nav_marks=[Decimal("10000")],
        risk_free_period_returns=[],
        mar_period_returns=[],
        periods_per_year=252,
    )
    assert metrics_single.terminal_return.state == "KNOWN"
    assert metrics_single.terminal_return.value == Decimal("0")
    assert metrics_single.periodic_returns == ()
    assert metrics_single.periodic_excess_sharpe.state == "UNAVAILABLE"
    assert (
        metrics_single.periodic_excess_sharpe.reason_code
        == REASON_INSUFFICIENT_OBSERVATIONS
    )


def test_negative_operating_cost() -> None:
    """Negative operating cost fails closed with NEGATIVE_OPERATING_COST."""
    gain = calculate_economic_gain(
        initial_net_nav=Decimal("10000.00"),
        terminal_net_nav=Decimal("9960.00"),
        attributed_operating_cost=Decimal("-10.00"),
    )
    assert gain.state == "INVALID"
    assert gain.reason_code == REASON_NEGATIVE_OPERATING_COST


def test_metric_arithmetic_value_invariants() -> None:
    """Assert MetricArithmeticValue invariants and immutability."""
    # Cannot create KNOWN with None value
    with pytest.raises(ValueError, match="must have a non-None value"):
        MetricArithmeticValue(metric_name="test", state="KNOWN", value=None)

    # Cannot create non-KNOWN with a value
    with pytest.raises(ValueError, match="must have value=None"):
        MetricArithmeticValue(
            metric_name="test", state="UNDEFINED", value=Decimal("1.0")
        )

    # Cannot pass float as value
    with pytest.raises(TypeError, match="cannot be a float"):
        MetricArithmeticValue(
            metric_name="test",
            state="KNOWN",
            value=1.5,  # type: ignore[arg-type]
        )

    # Immutability
    val = MetricArithmeticValue(metric_name="test", state="KNOWN", value=Decimal("1.5"))
    with pytest.raises(AttributeError):
        val.state = "INVALID"  # type: ignore[misc]
