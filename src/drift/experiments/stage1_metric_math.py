"""Stage 1 B-versus-R scientific metric calculation engine.

Implements pure Python and Decimal arithmetic for Stage 1 benchmark
measurement per Issue #445 and contract specification PR #435 (#382).

This module performs pure mathematical calculations on supplied numeric inputs.
It produces no side effects, introduces no persisted scorecard schema, and does
not grant scientific promotion, strategy eligibility, or live execution permissions.

Analytical states:
- KNOWN: Valid mathematical value computed over complete verified inputs.
- UNDEFINED: Mathematically indeterminate (e.g. zero variance, zero MDD).
  Never silently converted to zero or infinity.
- UNAVAILABLE: Input data missing, incomplete, or unverified.
- INVALID: Contradictory, corrupted, float-contaminated, or nonpositive inputs.
"""

from __future__ import annotations

import decimal
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Context, Decimal
from typing import Literal

CALCULATION_PRECISION: int = 50

# Recognized reason codes per PR #435 / Issue #445
REASON_ZERO_SAMPLE_VARIANCE = "ZERO_SAMPLE_VARIANCE"
REASON_ZERO_DOWNSIDE_DEVIATION = "ZERO_DOWNSIDE_DEVIATION"
REASON_ZERO_MAXIMUM_DRAWDOWN = "ZERO_MAXIMUM_DRAWDOWN"
REASON_ZERO_NAV_DIVISOR = "ZERO_NAV_DIVISOR"
REASON_NEGATIVE_COMPOUNDED_BASE = "NEGATIVE_COMPOUNDED_BASE"

REASON_MISSING_VALUATION_MARK = "MISSING_VALUATION_MARK"
REASON_MISSING_RISK_FREE_SERIES = "MISSING_RISK_FREE_SERIES"
REASON_MISSING_MAR_SERIES = "MISSING_MAR_SERIES"
REASON_MISSING_OPERATING_COST = "MISSING_OPERATING_COST"
REASON_INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
REASON_IRREGULAR_SPACING = "IRREGULAR_SPACING"

REASON_NONPOSITIVE_STARTING_NAV = "NONPOSITIVE_STARTING_NAV"
REASON_NEGATIVE_NAV = "NEGATIVE_NAV"
REASON_NEGATIVE_OPERATING_COST = "NEGATIVE_OPERATING_COST"
REASON_FLOAT_INPUT_PROHIBITED = "FLOAT_INPUT_PROHIBITED"
REASON_NAN_OR_INFINITY_INPUT = "NAN_OR_INFINITY_INPUT"
REASON_SERIES_LENGTH_MISMATCH = "SERIES_LENGTH_MISMATCH"
REASON_INVALID_PERIODS_PER_YEAR = "INVALID_PERIODS_PER_YEAR"
REASON_EMPTY_SERIES = "EMPTY_SERIES"

MetricState = Literal["KNOWN", "UNDEFINED", "UNAVAILABLE", "INVALID"]


@dataclass(frozen=True, slots=True)
class MetricArithmeticValue:
    """Immutable representation of a calculated metric with 4-state semantics.

    Guarantees that non-KNOWN states never carry a numeric value, preventing
    silent conversion of undefined or unavailable states to zero.
    """

    metric_name: str
    state: MetricState
    value: Decimal | None = None
    reason_code: str | None = None
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in ("KNOWN", "UNDEFINED", "UNAVAILABLE", "INVALID"):
            raise ValueError(f"Invalid metric state: {self.state}")
        if self.state == "KNOWN":
            if self.value is None:
                raise ValueError("Metric with state 'KNOWN' must have a non-None value")
            if isinstance(self.value, float):
                raise TypeError("Metric value cannot be a float")
            if not isinstance(self.value, Decimal):
                raise TypeError(
                    f"Metric value must be Decimal, got {type(self.value).__name__}"
                )
            if self.value.is_nan() or self.value.is_infinite():
                raise ValueError("Metric value cannot be NaN or Infinity")
        else:
            if self.value is not None:
                raise ValueError(
                    f"Metric with state '{self.state}' must have value=None, "
                    f"got {self.value}"
                )

    @property
    def value_decimal(self) -> Decimal | None:
        """Alias for value to match PR #435 JSON serializable specification."""
        return self.value


@dataclass(frozen=True, slots=True)
class Stage1ArithmeticMetrics:
    """Container for pure mathematical Stage 1 portfolio performance metrics."""

    terminal_return: MetricArithmeticValue
    geometric_annualized_return: MetricArithmeticValue
    periodic_excess_sharpe: MetricArithmeticValue
    maximum_drawdown: MetricArithmeticValue
    sortino: MetricArithmeticValue
    calmar: MetricArithmeticValue
    periodic_returns: tuple[MetricArithmeticValue, ...] | MetricArithmeticValue


def _get_context() -> Context:
    return Context(prec=CALCULATION_PRECISION)


def _check_decimal_input(
    val: object, field_name: str
) -> tuple[Decimal | None, str | None]:
    """Validate that an input value is Decimal, None, or invalid.

    Returns (decimal_value, error_reason_code).
    """
    if val is None:
        return None, None
    if isinstance(val, float):
        return None, REASON_FLOAT_INPUT_PROHIBITED
    if not isinstance(val, Decimal):
        return None, REASON_FLOAT_INPUT_PROHIBITED
    if val.is_nan() or val.is_infinite():
        return None, REASON_NAN_OR_INFINITY_INPUT
    return val, None


def calculate_periodic_returns(
    nav_marks: Sequence[Decimal | None],
) -> tuple[MetricArithmeticValue, ...] | MetricArithmeticValue:
    """Compute periodic returns r[t] = NAV[t] / NAV[t-1] - 1.

    Preconditions:
    - Input sequence must be non-empty and have at least 2 marks for returns.
    - If any mark is float, NaN, or Infinity, returns INVALID.
    - If starting NAV is nonpositive, returns INVALID.
    - If any NAV is negative, returns INVALID.
    - If an intermediate valuation mark is None, the intervals referencing it
      evaluate to UNAVAILABLE with reason MISSING_VALUATION_MARK.
    - If preceding NAV is zero, dependent interval evaluates to UNDEFINED
      with reason ZERO_NAV_DIVISOR.
    """
    if not isinstance(nav_marks, Sequence):
        return MetricArithmeticValue(
            metric_name="periodic_returns",
            state="INVALID",
            reason_code=REASON_FLOAT_INPUT_PROHIBITED,
        )

    if len(nav_marks) == 0:
        return MetricArithmeticValue(
            metric_name="periodic_returns",
            state="INVALID",
            reason_code=REASON_EMPTY_SERIES,
        )

    # Validate elements for float or NaN/Inf
    validated_navs: list[Decimal | None] = []
    for idx, mark in enumerate(nav_marks):
        d_val, err = _check_decimal_input(mark, f"nav_marks[{idx}]")
        if err is not None:
            return MetricArithmeticValue(
                metric_name="periodic_returns",
                state="INVALID",
                reason_code=err,
            )
        validated_navs.append(d_val)

    if validated_navs[0] is not None and validated_navs[0] <= Decimal("0"):
        return MetricArithmeticValue(
            metric_name="periodic_returns",
            state="INVALID",
            reason_code=REASON_NONPOSITIVE_STARTING_NAV,
        )

    for mark in validated_navs:
        if mark is not None and mark < Decimal("0"):
            return MetricArithmeticValue(
                metric_name="periodic_returns",
                state="INVALID",
                reason_code=REASON_NEGATIVE_NAV,
            )

    if len(validated_navs) < 2:
        return ()

    results: list[MetricArithmeticValue] = []
    with decimal.localcontext(_get_context()):
        for t in range(1, len(validated_navs)):
            prev = validated_navs[t - 1]
            curr = validated_navs[t]

            if prev is None or curr is None:
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"periodic_return_{t}",
                        state="UNAVAILABLE",
                        reason_code=REASON_MISSING_VALUATION_MARK,
                    )
                )
            elif prev == Decimal("0"):
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"periodic_return_{t}",
                        state="UNDEFINED",
                        reason_code=REASON_ZERO_NAV_DIVISOR,
                    )
                )
            else:
                ret = (curr / prev) - Decimal("1")
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"periodic_return_{t}",
                        state="KNOWN",
                        value=ret,
                    )
                )

    return tuple(results)


def calculate_terminal_return(
    nav_marks: Sequence[Decimal | None],
) -> MetricArithmeticValue:
    """Compute terminal cumulative return R = NAV[T] / NAV[0] - 1."""
    if not isinstance(nav_marks, Sequence) or len(nav_marks) == 0:
        return MetricArithmeticValue(
            metric_name="terminal_return",
            state="INVALID",
            reason_code=REASON_EMPTY_SERIES,
        )

    for idx, mark in enumerate(nav_marks):
        _, err = _check_decimal_input(mark, f"nav_marks[{idx}]")
        if err is not None:
            return MetricArithmeticValue(
                metric_name="terminal_return",
                state="INVALID",
                reason_code=err,
            )

    first = nav_marks[0]
    last = nav_marks[-1]

    if first is None or last is None:
        return MetricArithmeticValue(
            metric_name="terminal_return",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_VALUATION_MARK,
        )

    if first <= Decimal("0"):
        return MetricArithmeticValue(
            metric_name="terminal_return",
            state="INVALID",
            reason_code=REASON_NONPOSITIVE_STARTING_NAV,
        )

    for mark in nav_marks:
        if mark is not None and mark < Decimal("0"):
            return MetricArithmeticValue(
                metric_name="terminal_return",
                state="INVALID",
                reason_code=REASON_NEGATIVE_NAV,
            )

    with decimal.localcontext(_get_context()):
        val = (last / first) - Decimal("1")
        return MetricArithmeticValue(
            metric_name="terminal_return",
            state="KNOWN",
            value=val,
        )


def calculate_geometric_annualized_return(
    *,
    terminal_return: MetricArithmeticValue,
    completed_periods: int,
    periods_per_year: int,
) -> MetricArithmeticValue:
    """Compute geometric annualized return R_ann = (1 + R_terminal)**(K / n) - 1.

    Preconditions:
    - terminal_return must be KNOWN.
    - completed_periods n >= 1.
    - periods_per_year K >= 1.
    - If 1 + R_terminal == 0 (total loss), evaluates to exact -1.0.
    - If 1 + R_terminal < 0, evaluates to UNDEFINED (negative compounded base).
    """
    if terminal_return.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state=terminal_return.state,
            reason_code=terminal_return.reason_code,
        )

    if completed_periods < 1:
        return MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state="UNAVAILABLE",
            reason_code=REASON_INSUFFICIENT_OBSERVATIONS,
        )

    if periods_per_year < 1:
        return MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state="INVALID",
            reason_code=REASON_INVALID_PERIODS_PER_YEAR,
        )

    assert terminal_return.value is not None

    with decimal.localcontext(_get_context()):
        base = Decimal("1") + terminal_return.value
        if base == Decimal("0"):
            return MetricArithmeticValue(
                metric_name="geometric_annualized_return",
                state="KNOWN",
                value=Decimal("-1.0"),
            )
        if base < Decimal("0"):
            return MetricArithmeticValue(
                metric_name="geometric_annualized_return",
                state="UNDEFINED",
                reason_code=REASON_NEGATIVE_COMPOUNDED_BASE,
            )

        power = Decimal(periods_per_year) / Decimal(completed_periods)
        ann_val = (base**power) - Decimal("1")
        return MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state="KNOWN",
            value=ann_val,
        )


def calculate_periodic_excess_returns(
    *,
    periodic_returns: Sequence[MetricArithmeticValue],
    risk_free_period_returns: Sequence[Decimal | None] | None,
) -> tuple[MetricArithmeticValue, ...] | MetricArithmeticValue:
    """Compute periodic excess returns e[t] = r[t] - rf[t]."""
    if risk_free_period_returns is None:
        return MetricArithmeticValue(
            metric_name="periodic_excess_returns",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_RISK_FREE_SERIES,
        )

    if len(risk_free_period_returns) != len(periodic_returns):
        return MetricArithmeticValue(
            metric_name="periodic_excess_returns",
            state="INVALID",
            reason_code=REASON_SERIES_LENGTH_MISMATCH,
        )

    for idx, rf in enumerate(risk_free_period_returns):
        _, err = _check_decimal_input(rf, f"risk_free_period_returns[{idx}]")
        if err is not None:
            return MetricArithmeticValue(
                metric_name="periodic_excess_returns",
                state="INVALID",
                reason_code=err,
            )

    results: list[MetricArithmeticValue] = []
    with decimal.localcontext(_get_context()):
        for t, (r_val, rf_val) in enumerate(
            zip(periodic_returns, risk_free_period_returns, strict=True), start=1
        ):
            if r_val.state != "KNOWN":
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"excess_return_{t}",
                        state=r_val.state,
                        reason_code=r_val.reason_code,
                    )
                )
            elif rf_val is None:
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"excess_return_{t}",
                        state="UNAVAILABLE",
                        reason_code=REASON_MISSING_RISK_FREE_SERIES,
                    )
                )
            else:
                assert r_val.value is not None
                diff = r_val.value - rf_val
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"excess_return_{t}",
                        state="KNOWN",
                        value=diff,
                    )
                )

    return tuple(results)


def calculate_sample_excess_variance_and_volatility(
    *,
    excess_returns: Sequence[MetricArithmeticValue],
    periods_per_year: int,
) -> tuple[MetricArithmeticValue, MetricArithmeticValue, MetricArithmeticValue]:
    """Calculate sample variance, standard deviation, and annualized volatility.

    Operates on periodic excess returns.
    Returns (sample_variance, sample_std, annualized_volatility).
    Sample variance uses denominator n - 1.
    """
    if periods_per_year < 1:
        err = MetricArithmeticValue(
            metric_name="excess_volatility",
            state="INVALID",
            reason_code=REASON_INVALID_PERIODS_PER_YEAR,
        )
        return err, err, err

    # Check for any non-KNOWN excess returns
    for e in excess_returns:
        if e.state != "KNOWN":
            res = MetricArithmeticValue(
                metric_name="excess_volatility",
                state=e.state,
                reason_code=e.reason_code,
            )
            return res, res, res

    n = len(excess_returns)
    if n < 2:
        insuf = MetricArithmeticValue(
            metric_name="excess_volatility",
            state="UNAVAILABLE",
            reason_code=REASON_INSUFFICIENT_OBSERVATIONS,
        )
        return insuf, insuf, insuf

    with decimal.localcontext(_get_context()):
        values = [e.value for e in excess_returns]
        assert all(v is not None for v in values)
        typed_values = [v for v in values if v is not None]

        mean_e = sum(typed_values) / Decimal(n)
        sum_sq = sum((v - mean_e) ** 2 for v in typed_values)
        variance = sum_sq / Decimal(n - 1)
        sample_std = variance.sqrt()
        ann_vol = sample_std * Decimal(periods_per_year).sqrt()

        var_metric = MetricArithmeticValue(
            metric_name="sample_excess_variance",
            state="KNOWN",
            value=variance,
        )
        std_metric = MetricArithmeticValue(
            metric_name="sample_excess_std",
            state="KNOWN",
            value=sample_std,
        )
        ann_metric = MetricArithmeticValue(
            metric_name="annualized_excess_volatility",
            state="KNOWN",
            value=ann_vol,
        )
        return var_metric, std_metric, ann_metric


def calculate_periodic_excess_sharpe(
    *,
    excess_returns: Sequence[MetricArithmeticValue],
    periods_per_year: int,
) -> MetricArithmeticValue:
    """Compute true periodic excess-return Sharpe ratio.

    Sharpe = (mean(e) / sample_std(e)) * sqrt(K)
    Preconditions:
    - n >= 2 observations.
    - sample_std(e) > 0.
    - If sample_std(e) == 0, evaluates to UNDEFINED (ZERO_SAMPLE_VARIANCE).
    """
    var_m, std_m, _ = calculate_sample_excess_variance_and_volatility(
        excess_returns=excess_returns,
        periods_per_year=periods_per_year,
    )

    if std_m.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="periodic_excess_sharpe",
            state=std_m.state,
            reason_code=std_m.reason_code,
        )

    assert std_m.value is not None

    with decimal.localcontext(_get_context()):
        if std_m.value == Decimal("0"):
            return MetricArithmeticValue(
                metric_name="periodic_excess_sharpe",
                state="UNDEFINED",
                reason_code=REASON_ZERO_SAMPLE_VARIANCE,
            )

        n = len(excess_returns)
        values = [e.value for e in excess_returns if e.value is not None]
        mean_e = sum(values) / Decimal(n)
        k_sqrt = Decimal(periods_per_year).sqrt()
        sharpe = (mean_e / std_m.value) * k_sqrt

        return MetricArithmeticValue(
            metric_name="periodic_excess_sharpe",
            state="KNOWN",
            value=sharpe,
        )


def calculate_maximum_drawdown(
    nav_marks: Sequence[Decimal | None],
) -> MetricArithmeticValue:
    """Compute maximum drawdown MDD = min_{t} (NAV[t] / peak[t] - 1).

    Includes initial capital NAV[0] in peak calculation.
    Drawdown is always nonpositive: MDD <= 0.
    """
    if not isinstance(nav_marks, Sequence) or len(nav_marks) == 0:
        return MetricArithmeticValue(
            metric_name="maximum_drawdown",
            state="INVALID",
            reason_code=REASON_EMPTY_SERIES,
        )

    for idx, mark in enumerate(nav_marks):
        _, err = _check_decimal_input(mark, f"nav_marks[{idx}]")
        if err is not None:
            return MetricArithmeticValue(
                metric_name="maximum_drawdown",
                state="INVALID",
                reason_code=err,
            )

    if any(m is None for m in nav_marks):
        return MetricArithmeticValue(
            metric_name="maximum_drawdown",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_VALUATION_MARK,
        )

    first = nav_marks[0]
    assert first is not None
    if first <= Decimal("0"):
        return MetricArithmeticValue(
            metric_name="maximum_drawdown",
            state="INVALID",
            reason_code=REASON_NONPOSITIVE_STARTING_NAV,
        )

    for m in nav_marks:
        assert m is not None
        if m < Decimal("0"):
            return MetricArithmeticValue(
                metric_name="maximum_drawdown",
                state="INVALID",
                reason_code=REASON_NEGATIVE_NAV,
            )

    with decimal.localcontext(_get_context()):
        running_peak = first
        max_dd = Decimal("0")

        for m in nav_marks:
            assert m is not None
            if m > running_peak:
                running_peak = m
            dd = (m / running_peak) - Decimal("1")
            if dd < max_dd:
                max_dd = dd

        return MetricArithmeticValue(
            metric_name="maximum_drawdown",
            state="KNOWN",
            value=max_dd,
        )


def calculate_sortino_ratio(
    *,
    periodic_returns: Sequence[MetricArithmeticValue],
    mar_period_returns: Sequence[Decimal | None] | None,
    periods_per_year: int,
) -> MetricArithmeticValue:
    """Compute target-adjusted Sortino ratio.

    Sortino = (mean(r - MAR) / downside_std) * sqrt(K)
    where shortfall[t] = min(r[t] - MAR[t], 0)
    downside_variance = (1 / n) * sum(shortfall[t]**2)
    downside_std = sqrt(downside_variance)
    """
    if mar_period_returns is None:
        return MetricArithmeticValue(
            metric_name="sortino",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_MAR_SERIES,
        )

    if len(mar_period_returns) != len(periodic_returns):
        return MetricArithmeticValue(
            metric_name="sortino",
            state="INVALID",
            reason_code=REASON_SERIES_LENGTH_MISMATCH,
        )

    if periods_per_year < 1:
        return MetricArithmeticValue(
            metric_name="sortino",
            state="INVALID",
            reason_code=REASON_INVALID_PERIODS_PER_YEAR,
        )

    for idx, mar in enumerate(mar_period_returns):
        _, err = _check_decimal_input(mar, f"mar_period_returns[{idx}]")
        if err is not None:
            return MetricArithmeticValue(
                metric_name="sortino",
                state="INVALID",
                reason_code=err,
            )

    for r in periodic_returns:
        if r.state != "KNOWN":
            return MetricArithmeticValue(
                metric_name="sortino",
                state=r.state,
                reason_code=r.reason_code,
            )

    for mar in mar_period_returns:
        if mar is None:
            return MetricArithmeticValue(
                metric_name="sortino",
                state="UNAVAILABLE",
                reason_code=REASON_MISSING_MAR_SERIES,
            )

    n = len(periodic_returns)
    if n < 1:
        return MetricArithmeticValue(
            metric_name="sortino",
            state="UNAVAILABLE",
            reason_code=REASON_INSUFFICIENT_OBSERVATIONS,
        )

    with decimal.localcontext(_get_context()):
        diffs: list[Decimal] = []
        shortfalls_sq: list[Decimal] = []

        for r, mar in zip(periodic_returns, mar_period_returns, strict=True):
            assert r.value is not None and mar is not None
            d = r.value - mar
            diffs.append(d)
            shortfall = min(d, Decimal("0"))
            shortfalls_sq.append(shortfall**2)

        downside_variance = sum(shortfalls_sq) / Decimal(n)
        downside_std = downside_variance.sqrt()

        if downside_std == Decimal("0"):
            return MetricArithmeticValue(
                metric_name="sortino",
                state="UNDEFINED",
                reason_code=REASON_ZERO_DOWNSIDE_DEVIATION,
            )

        mean_diff = sum(diffs) / Decimal(n)
        k_sqrt = Decimal(periods_per_year).sqrt()
        sortino_val = (mean_diff / downside_std) * k_sqrt

        return MetricArithmeticValue(
            metric_name="sortino",
            state="KNOWN",
            value=sortino_val,
        )


def calculate_calmar_ratio(
    *,
    geometric_annualized_return: MetricArithmeticValue,
    maximum_drawdown: MetricArithmeticValue,
) -> MetricArithmeticValue:
    """Compute Calmar ratio = R_annualized / abs(MDD).

    Preconditions:
    - Both geometric_annualized_return and maximum_drawdown must be KNOWN.
    - If abs(MDD) == 0, evaluates to UNDEFINED (ZERO_MAXIMUM_DRAWDOWN).
    """
    if geometric_annualized_return.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="calmar",
            state=geometric_annualized_return.state,
            reason_code=geometric_annualized_return.reason_code,
        )

    if maximum_drawdown.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="calmar",
            state=maximum_drawdown.state,
            reason_code=maximum_drawdown.reason_code,
        )

    assert geometric_annualized_return.value is not None
    assert maximum_drawdown.value is not None

    with decimal.localcontext(_get_context()):
        abs_mdd = abs(maximum_drawdown.value)
        if abs_mdd == Decimal("0"):
            return MetricArithmeticValue(
                metric_name="calmar",
                state="UNDEFINED",
                reason_code=REASON_ZERO_MAXIMUM_DRAWDOWN,
            )

        calmar_val = geometric_annualized_return.value / abs_mdd
        return MetricArithmeticValue(
            metric_name="calmar",
            state="KNOWN",
            value=calmar_val,
        )


def calculate_economic_gain(
    *,
    initial_net_nav: Decimal,
    terminal_net_nav: Decimal,
    attributed_operating_cost: Decimal | None,
) -> MetricArithmeticValue:
    """Calculate per-arm total economic gain in View 3.

    Economic Gain = terminal_net_nav - initial_net_nav - attributed_operating_cost

    Trading transaction costs are already embedded in platform net NAV and
    must not be subtracted a second time.
    Unknown operating cost yields UNAVAILABLE with reason MISSING_OPERATING_COST.
    """
    for name, val in [
        ("initial_net_nav", initial_net_nav),
        ("terminal_net_nav", terminal_net_nav),
        ("attributed_operating_cost", attributed_operating_cost),
    ]:
        _, err = _check_decimal_input(val, name)
        if err is not None:
            return MetricArithmeticValue(
                metric_name="economic_gain",
                state="INVALID",
                reason_code=err,
            )

    if attributed_operating_cost is None:
        return MetricArithmeticValue(
            metric_name="economic_gain",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_OPERATING_COST,
        )

    if initial_net_nav <= Decimal("0"):
        return MetricArithmeticValue(
            metric_name="economic_gain",
            state="INVALID",
            reason_code=REASON_NONPOSITIVE_STARTING_NAV,
        )

    if terminal_net_nav < Decimal("0"):
        return MetricArithmeticValue(
            metric_name="economic_gain",
            state="INVALID",
            reason_code=REASON_NEGATIVE_NAV,
        )

    if attributed_operating_cost < Decimal("0"):
        return MetricArithmeticValue(
            metric_name="economic_gain",
            state="INVALID",
            reason_code=REASON_NEGATIVE_OPERATING_COST,
        )

    with decimal.localcontext(_get_context()):
        gain = terminal_net_nav - initial_net_nav - attributed_operating_cost
        return MetricArithmeticValue(
            metric_name="economic_gain",
            state="KNOWN",
            value=gain,
        )


def calculate_comparative_economic_advantage(
    b_gain: MetricArithmeticValue,
    r_gain: MetricArithmeticValue,
) -> MetricArithmeticValue:
    """Compute comparative economic advantage = b_gain - r_gain.

    Propagates missing or invalid status without imputing zero.
    """
    if b_gain.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="comparative_economic_advantage",
            state=b_gain.state,
            reason_code=b_gain.reason_code,
        )

    if r_gain.state != "KNOWN":
        return MetricArithmeticValue(
            metric_name="comparative_economic_advantage",
            state=r_gain.state,
            reason_code=r_gain.reason_code,
        )

    assert b_gain.value is not None
    assert r_gain.value is not None

    with decimal.localcontext(_get_context()):
        adv = b_gain.value - r_gain.value
        return MetricArithmeticValue(
            metric_name="comparative_economic_advantage",
            state="KNOWN",
            value=adv,
        )


def calculate_paired_return_differences(
    *,
    b_returns: Sequence[MetricArithmeticValue],
    r_returns: Sequence[MetricArithmeticValue],
) -> tuple[MetricArithmeticValue, ...] | MetricArithmeticValue:
    """Compute paired return difference series d[t] = r_b[t] - r_r[t].

    Does NOT assume independence between arms or across adjacent days.
    Does NOT compute hypothesis tests, p-values, or multiple-comparison corrections.
    """
    if len(b_returns) != len(r_returns):
        return MetricArithmeticValue(
            metric_name="paired_return_differences",
            state="INVALID",
            reason_code=REASON_SERIES_LENGTH_MISMATCH,
        )

    results: list[MetricArithmeticValue] = []
    with decimal.localcontext(_get_context()):
        for t, (b_ret, r_ret) in enumerate(
            zip(b_returns, r_returns, strict=True), start=1
        ):
            if b_ret.state != "KNOWN":
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"paired_diff_{t}",
                        state=b_ret.state,
                        reason_code=b_ret.reason_code,
                    )
                )
            elif r_ret.state != "KNOWN":
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"paired_diff_{t}",
                        state=r_ret.state,
                        reason_code=r_ret.reason_code,
                    )
                )
            else:
                assert b_ret.value is not None and r_ret.value is not None
                diff = b_ret.value - r_ret.value
                results.append(
                    MetricArithmeticValue(
                        metric_name=f"paired_diff_{t}",
                        state="KNOWN",
                        value=diff,
                    )
                )

    return tuple(results)


def calculate_stage1_arithmetic(
    *,
    nav_marks: Sequence[Decimal | None],
    risk_free_period_returns: Sequence[Decimal | None] | None,
    mar_period_returns: Sequence[Decimal | None] | None,
    periods_per_year: int,
    spacing_verified: bool = True,
) -> Stage1ArithmeticMetrics:
    """Calculate complete Stage 1 arithmetic metrics suite.

    Accepts session closing marks and period returns in Decimal.
    Fails closed into INVALID or UNAVAILABLE states on missing, corrupt,
    or irregular inputs without silently imputing zero.
    """
    # Check general sequence validity
    if not isinstance(nav_marks, Sequence) or len(nav_marks) == 0:
        err = MetricArithmeticValue(
            metric_name="stage1_arithmetic",
            state="INVALID",
            reason_code=REASON_EMPTY_SERIES,
        )
        return Stage1ArithmeticMetrics(
            terminal_return=err,
            geometric_annualized_return=err,
            periodic_excess_sharpe=err,
            maximum_drawdown=err,
            sortino=err,
            calmar=err,
            periodic_returns=err,
        )

    # Check for float or NaN/Inf in nav_marks
    for idx, mark in enumerate(nav_marks):
        _, check_err = _check_decimal_input(mark, f"nav_marks[{idx}]")
        if check_err is not None:
            err = MetricArithmeticValue(
                metric_name="stage1_arithmetic",
                state="INVALID",
                reason_code=check_err,
            )
            return Stage1ArithmeticMetrics(
                terminal_return=err,
                geometric_annualized_return=err,
                periodic_excess_sharpe=err,
                maximum_drawdown=err,
                sortino=err,
                calmar=err,
                periodic_returns=err,
            )

    # Check starting NAV
    if nav_marks[0] is not None and nav_marks[0] <= Decimal("0"):
        err = MetricArithmeticValue(
            metric_name="stage1_arithmetic",
            state="INVALID",
            reason_code=REASON_NONPOSITIVE_STARTING_NAV,
        )
        return Stage1ArithmeticMetrics(
            terminal_return=err,
            geometric_annualized_return=err,
            periodic_excess_sharpe=err,
            maximum_drawdown=err,
            sortino=err,
            calmar=err,
            periodic_returns=err,
        )

    # Check negative NAV
    for mark in nav_marks:
        if mark is not None and mark < Decimal("0"):
            err = MetricArithmeticValue(
                metric_name="stage1_arithmetic",
                state="INVALID",
                reason_code=REASON_NEGATIVE_NAV,
            )
            return Stage1ArithmeticMetrics(
                terminal_return=err,
                geometric_annualized_return=err,
                periodic_excess_sharpe=err,
                maximum_drawdown=err,
                sortino=err,
                calmar=err,
                periodic_returns=err,
            )

    # Check periods_per_year
    if periods_per_year < 1:
        err = MetricArithmeticValue(
            metric_name="stage1_arithmetic",
            state="INVALID",
            reason_code=REASON_INVALID_PERIODS_PER_YEAR,
        )
        return Stage1ArithmeticMetrics(
            terminal_return=err,
            geometric_annualized_return=err,
            periodic_excess_sharpe=err,
            maximum_drawdown=err,
            sortino=err,
            calmar=err,
            periodic_returns=err,
        )

    n_expected = len(nav_marks) - 1

    # Check length of risk_free_period_returns if supplied
    if (
        risk_free_period_returns is not None
        and len(risk_free_period_returns) != n_expected
    ):
        err = MetricArithmeticValue(
            metric_name="stage1_arithmetic",
            state="INVALID",
            reason_code=REASON_SERIES_LENGTH_MISMATCH,
        )
        return Stage1ArithmeticMetrics(
            terminal_return=err,
            geometric_annualized_return=err,
            periodic_excess_sharpe=err,
            maximum_drawdown=err,
            sortino=err,
            calmar=err,
            periodic_returns=err,
        )

    # Check length of mar_period_returns if supplied
    if mar_period_returns is not None and len(mar_period_returns) != n_expected:
        err = MetricArithmeticValue(
            metric_name="stage1_arithmetic",
            state="INVALID",
            reason_code=REASON_SERIES_LENGTH_MISMATCH,
        )
        return Stage1ArithmeticMetrics(
            terminal_return=err,
            geometric_annualized_return=err,
            periodic_excess_sharpe=err,
            maximum_drawdown=err,
            sortino=err,
            calmar=err,
            periodic_returns=err,
        )

    # 1. Periodic returns
    periodic_rets = calculate_periodic_returns(nav_marks)

    # 2. Terminal return
    term_ret = calculate_terminal_return(nav_marks)

    # 3. Geometric annualized return
    if not spacing_verified:
        geom_ann_ret = MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state="UNAVAILABLE",
            reason_code=REASON_IRREGULAR_SPACING,
        )
    elif any(m is None for m in nav_marks):
        # Missing intermediate mark invalidates spacing invariance
        geom_ann_ret = MetricArithmeticValue(
            metric_name="geometric_annualized_return",
            state="UNAVAILABLE",
            reason_code=REASON_MISSING_VALUATION_MARK,
        )
    else:
        geom_ann_ret = calculate_geometric_annualized_return(
            terminal_return=term_ret,
            completed_periods=n_expected,
            periods_per_year=periods_per_year,
        )

    # 4. Maximum drawdown
    mdd = calculate_maximum_drawdown(nav_marks)

    # 5. Excess returns and Sharpe
    if isinstance(periodic_rets, tuple):
        excess_rets = calculate_periodic_excess_returns(
            periodic_returns=periodic_rets,
            risk_free_period_returns=risk_free_period_returns,
        )
        if isinstance(excess_rets, tuple):
            sharpe = calculate_periodic_excess_sharpe(
                excess_returns=excess_rets,
                periods_per_year=periods_per_year,
            )
        else:
            sharpe = MetricArithmeticValue(
                metric_name="periodic_excess_sharpe",
                state=excess_rets.state,
                reason_code=excess_rets.reason_code,
            )
    else:
        sharpe = MetricArithmeticValue(
            metric_name="periodic_excess_sharpe",
            state=periodic_rets.state,
            reason_code=periodic_rets.reason_code,
        )

    # 6. Sortino
    if isinstance(periodic_rets, tuple):
        sortino = calculate_sortino_ratio(
            periodic_returns=periodic_rets,
            mar_period_returns=mar_period_returns,
            periods_per_year=periods_per_year,
        )
    else:
        sortino = MetricArithmeticValue(
            metric_name="sortino",
            state=periodic_rets.state,
            reason_code=periodic_rets.reason_code,
        )

    # 7. Calmar
    calmar = calculate_calmar_ratio(
        geometric_annualized_return=geom_ann_ret,
        maximum_drawdown=mdd,
    )

    return Stage1ArithmeticMetrics(
        terminal_return=term_ret,
        geometric_annualized_return=geom_ann_ret,
        periodic_excess_sharpe=sharpe,
        maximum_drawdown=mdd,
        sortino=sortino,
        calmar=calmar,
        periodic_returns=periodic_rets,
    )
