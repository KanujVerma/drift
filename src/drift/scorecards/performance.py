"""Performance attribution, risk profiles, and drawdown engine (M5-3, Issue 193).

Provides pure-Python deterministic implementations of:
- Return and risk attribution (cumulative return, annualized return,
  volatility, downside semi-deviation);
- Risk-adjusted performance ratios (Sharpe, Sortino, Calmar);
- Drawdown profile trajectories (high-water marks, MDD, peak-to-trough,
  recovery duration);
- Portfolio turnover and transaction cost drag;
- Realized PnL completeness validation integrating RealizedPnLCompletenessV1;
- High-level StrategyScorecardV1 generation.
"""

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from drift.domain.common import UTCDateTime
from drift.domain.evaluator_bundles import EvaluationRunIdentityV2
from drift.domain.evaluator_portfolio import EvaluationLane
from drift.domain.evaluator_results import (
    EvaluationResultV1,
    EvaluationSummaryMetricsV1,
    SessionEquityPointV1,
)
from drift.domain.scorecards import (
    DrawdownProfileV1,
    StrategyScorecardV1,
    TurnoverSummaryV1,
    build_strategy_scorecard,
)

FOUR_PLACES = Decimal("0.0001")
SIX_PLACES = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")


def _quantize_decimal(val: Decimal, precision: Decimal = FOUR_PLACES) -> Decimal:
    """Round Decimal to target precision with half-even rounding."""
    return val.quantize(precision, rounding=ROUND_HALF_EVEN)


def compute_return_and_risk(
    equity_series: Sequence[Decimal | SessionEquityPointV1],
    *,
    initial_nav: Decimal,
    sessions_per_year: int = 252,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Compute return and risk metrics from an equity curve.

    Returns:
        (cumulative_return, annualized_return, annualized_volatility,
         downside_deviation, sharpe_ratio, sortino_ratio, calmar_ratio)
    """
    if not equity_series or initial_nav <= ZERO:
        return (ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO)

    navs: list[Decimal] = []
    for item in equity_series:
        if isinstance(item, SessionEquityPointV1):
            navs.append(item.net_asset_value)
        else:
            navs.append(item)

    t = len(navs)
    ending_nav = navs[-1]
    cum_ret = (ending_nav - initial_nav) / initial_nav

    # Calculate session daily returns
    daily_returns: list[Decimal] = []
    prev_nav = initial_nav
    for nav in navs:
        if prev_nav > ZERO:
            r = (nav - prev_nav) / prev_nav
            daily_returns.append(r)
        else:
            daily_returns.append(ZERO)
        prev_nav = nav

    # Annualized return
    dec_t = Decimal(t)
    dec_spy = Decimal(sessions_per_year)
    one_plus_cum = ONE + cum_ret

    if one_plus_cum > ZERO and t > 0:
        power = float(dec_spy / dec_t)
        ann_ret_float = math.pow(float(one_plus_cum), power) - 1.0
        ann_ret = Decimal(str(ann_ret_float))
    else:
        ann_ret = cum_ret

    # Annualized volatility
    if t > 1:
        mean_ret = sum(daily_returns, ZERO) / dec_t
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / Decimal(t - 1)
        daily_vol = Decimal(str(math.sqrt(float(variance))))
        ann_vol = daily_vol * Decimal(str(math.sqrt(sessions_per_year)))
    else:
        ann_vol = ZERO

    # Downside semi-deviation (considering returns below zero)
    downside_sq_sum = sum((min(r, ZERO) ** 2 for r in daily_returns), ZERO)
    downside_var = downside_sq_sum / dec_t
    downside_dev = Decimal(str(math.sqrt(float(downside_var)))) * Decimal(
        str(math.sqrt(sessions_per_year))
    )

    # Sharpe ratio
    if ann_vol > ZERO:
        sharpe = ann_ret / ann_vol
    else:
        sharpe = ZERO

    # Sortino ratio
    if downside_dev > ZERO:
        sortino = ann_ret / downside_dev
    else:
        sortino = ZERO

    # Calmar ratio (needs MDD from equity curve)
    hwm = initial_nav
    mdd = ZERO
    for nav in navs:
        if nav > hwm:
            hwm = nav
        if hwm > ZERO:
            dd = (nav - hwm) / hwm
            if dd < mdd:
                mdd = dd

    abs_mdd = abs(mdd)
    if abs_mdd > ZERO:
        calmar = ann_ret / abs_mdd
    else:
        calmar = ZERO

    return (
        _quantize_decimal(cum_ret),
        _quantize_decimal(ann_ret),
        _quantize_decimal(ann_vol),
        _quantize_decimal(downside_dev),
        _quantize_decimal(sharpe),
        _quantize_decimal(sortino),
        _quantize_decimal(calmar),
    )


def compute_drawdown_profile(
    equity_series: Sequence[Decimal | SessionEquityPointV1],
    *,
    initial_nav: Decimal,
) -> DrawdownProfileV1:
    """Compute comprehensive drawdown trajectory profile."""
    if not equity_series or initial_nav <= ZERO:
        return DrawdownProfileV1(
            maximum_drawdown=ZERO,
            max_drawdown_duration_sessions=0,
            peak_to_trough_sessions=0,
            recovery_sessions=0,
            current_drawdown=ZERO,
            is_recovered=True,
        )

    navs: list[Decimal] = []
    for item in equity_series:
        if isinstance(item, SessionEquityPointV1):
            navs.append(item.net_asset_value)
        else:
            navs.append(item)

    hwm = initial_nav
    mdd = ZERO
    mdd_trough_idx = 0
    mdd_peak_idx = 0

    cur_peak_idx = 0
    cur_drawdown_start = 0
    in_drawdown = False
    max_dd_duration = 0

    for i, nav in enumerate(navs):
        session_idx = i + 1
        if nav >= hwm:
            if in_drawdown:
                # Recovered from previous drawdown
                duration = session_idx - cur_drawdown_start
                if duration > max_dd_duration:
                    max_dd_duration = duration
                in_drawdown = False
            hwm = nav
            cur_peak_idx = session_idx
        else:
            if not in_drawdown:
                in_drawdown = True
                cur_drawdown_start = cur_peak_idx

            dd = (nav - hwm) / hwm
            if dd < mdd:
                mdd = dd
                mdd_trough_idx = session_idx
                mdd_peak_idx = cur_peak_idx

    # If ending while in a drawdown
    if in_drawdown:
        cur_duration = len(navs) - cur_drawdown_start
        if cur_duration > max_dd_duration:
            max_dd_duration = cur_duration

    # Calculate peak-to-trough and recovery for the MDD episode
    if mdd < ZERO:
        peak_to_trough = max(0, mdd_trough_idx - mdd_peak_idx)
        # Find if and when MDD episode was recovered
        recovery_sessions = 0
        mdd_hwm_at_peak = navs[mdd_peak_idx - 1] if mdd_peak_idx > 0 else initial_nav
        for i in range(mdd_trough_idx, len(navs)):
            if navs[i] >= mdd_hwm_at_peak:
                recovery_sessions = (i + 1) - mdd_trough_idx
                break
    else:
        peak_to_trough = 0
        recovery_sessions = 0

    current_dd = (navs[-1] - hwm) / hwm if hwm > ZERO else ZERO
    if current_dd > ZERO:
        current_dd = ZERO

    return DrawdownProfileV1(
        maximum_drawdown=_quantize_decimal(mdd),
        max_drawdown_duration_sessions=max_dd_duration,
        peak_to_trough_sessions=peak_to_trough,
        recovery_sessions=recovery_sessions,
        current_drawdown=_quantize_decimal(current_dd),
        is_recovered=current_dd == ZERO,
    )


def compute_turnover_summary(
    metrics: EvaluationSummaryMetricsV1,
    *,
    sessions_per_year: int = 252,
) -> TurnoverSummaryV1:
    """Compute portfolio turnover and transaction cost drag."""
    t = metrics.evaluated_session_count
    init_nav = metrics.initial_net_asset_value

    if t == 0 or init_nav <= ZERO:
        return TurnoverSummaryV1(
            mean_session_turnover=ZERO,
            annualized_turnover=ZERO,
            estimated_cost_drag=ZERO,
        )

    # One-way turnover: half of gross traded notional divided by NAV
    dec_t = Decimal(t)
    half_notional = metrics.gross_traded_notional / TWO
    session_turnover = (half_notional / init_nav) / dec_t
    ann_turnover = session_turnover * Decimal(sessions_per_year)
    cost_drag = metrics.cumulative_transaction_costs / init_nav

    return TurnoverSummaryV1(
        mean_session_turnover=_quantize_decimal(session_turnover),
        annualized_turnover=_quantize_decimal(ann_turnover),
        estimated_cost_drag=_quantize_decimal(cost_drag),
    )


def generate_strategy_scorecard(
    *,
    result: EvaluationResultV1 | EvaluationSummaryMetricsV1,
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    as_of_time: UTCDateTime,
    scorecard_id: UUID | None = None,
    sessions_per_year: int = 252,
) -> StrategyScorecardV1:
    """Generate an immutable StrategyScorecardV1 from evaluation metrics."""
    metrics: EvaluationSummaryMetricsV1
    if isinstance(result, EvaluationSummaryMetricsV1):
        metrics = result
    else:
        metrics = result.metrics

    cum_ret, ann_ret, ann_vol, down_dev, sharpe, sortino, calmar = (
        compute_return_and_risk(
            metrics.equity_series,
            initial_nav=metrics.initial_net_asset_value,
            sessions_per_year=sessions_per_year,
        )
    )

    drawdown_profile = compute_drawdown_profile(
        metrics.equity_series,
        initial_nav=metrics.initial_net_asset_value,
    )

    turnover_summary = compute_turnover_summary(
        metrics,
        sessions_per_year=sessions_per_year,
    )

    sc_id = scorecard_id or UUID("018f3a5b-6c7d-7890-8123-456789abcd02")

    return build_strategy_scorecard(
        scorecard_id=sc_id,
        run_identity=run_identity,
        lane=lane,
        cumulative_return=cum_ret,
        annualized_return=ann_ret,
        annualized_volatility=ann_vol,
        downside_deviation=down_dev,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        drawdown_profile=drawdown_profile,
        turnover_summary=turnover_summary,
        pnl_completeness=metrics.realized_pnl_completeness,
        created_at=as_of_time,
    )
