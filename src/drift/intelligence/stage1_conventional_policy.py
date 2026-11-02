"""Stage 1 conventional selector policy with exact 34-digit Decimal objective.

Implements locked R utility:
G_s - lambda_v * sqrt(126) * sigma_s - lambda_d * D_s - C_s
Exact tie-breaking: prefer valid eligible incumbent; otherwise B3, then B4, then B5.
No epsilon bands, no hidden score perturbations, no candidate-ID-dependent preferences.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Literal

from drift.domain.common import FrozenModel

R_DECIMAL_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
STAGE1_TIE_ORDER: tuple[Literal["B3", "B4", "B5"], ...] = ("B3", "B4", "B5")


class RUtilityBreakdownV1(FrozenModel):
    utility: Decimal
    compounded_return: Decimal
    mean_return: Decimal
    sample_variance: Decimal
    sample_volatility: Decimal
    maximum_drawdown: Decimal
    transition_cost: Decimal


def compute_r_utility(
    nav_series: Sequence[Decimal],
    *,
    lambda_v: Decimal,
    lambda_d: Decimal,
    transition_cost: Decimal,
    context: Context = R_DECIMAL_CONTEXT,
) -> RUtilityBreakdownV1:
    """Computes exact 34-digit Decimal utility over 127 NAV marks (126 returns)."""
    if len(nav_series) != 127:
        raise ValueError(f"R_UTILITY_REQUIRES_127_MARKS: got {len(nav_series)}")

    # 126 completed returns
    returns: list[Decimal] = []
    for i in range(1, 127):
        prev = nav_series[i - 1]
        curr = nav_series[i]
        if prev <= Decimal(0) or curr <= Decimal(0):
            raise ValueError("R_UTILITY_NON_POSITIVE_NAV")
        r_i = context.subtract(context.divide(curr, prev), Decimal(1))
        returns.append(r_i)

    # G_s = product(1 + r_i) - 1
    prod = Decimal(1)
    for r in returns:
        prod = context.multiply(prod, context.add(Decimal(1), r))
    g_s = context.subtract(prod, Decimal(1))

    # mean_s = sum(r_i) / 126
    total_r = sum(returns)
    mean_s = context.divide(Decimal(total_r), Decimal(126))

    # var_s = sum((r_i - mean_s)^2) / 125
    sum_sq = sum(
        context.power(context.subtract(r, mean_s), Decimal(2)) for r in returns
    )
    var_s = context.divide(Decimal(sum_sq), Decimal(125))
    sigma_s = context.sqrt(var_s)

    # peak_i = max(NAV_0, ..., NAV_i)
    # D_s = max(1 - NAV_i / peak_i) over i=0..126
    cur_peak = Decimal(0)
    max_dd = Decimal(0)
    for nav in nav_series:
        if nav > cur_peak:
            cur_peak = nav
        if cur_peak > Decimal(0):
            dd = context.subtract(Decimal(1), context.divide(nav, cur_peak))
            if dd > max_dd:
                max_dd = dd
    d_s = max_dd

    # U_s = G_s - lambda_v * sqrt(126) * sigma_s - lambda_d * D_s - C_s
    sqrt_126 = context.sqrt(Decimal(126))
    term_vol = context.multiply(lambda_v, context.multiply(sqrt_126, sigma_s))
    term_dd = context.multiply(lambda_d, d_s)
    c_s = transition_cost

    u_s = context.subtract(
        context.subtract(context.subtract(g_s, term_vol), term_dd), c_s
    )

    return RUtilityBreakdownV1(
        utility=u_s,
        compounded_return=g_s,
        mean_return=mean_s,
        sample_variance=var_s,
        sample_volatility=sigma_s,
        maximum_drawdown=d_s,
        transition_cost=c_s,
    )


def break_r_ties(
    scores: dict[str, Decimal],
    *,
    incumbent: str | None = None,
    tie_order: tuple[Literal["B3", "B4", "B5"], ...] = STAGE1_TIE_ORDER,
) -> str:
    """Selects the greatest exact Decimal score with deterministic tie-breaking.

    Among exactly equal maxima:
    1. Prefer currently valid eligible incumbent if it is among the tied maxima.
    2. Otherwise prefer tie_order (default B3, then B4, then B5).
    """
    if not scores:
        raise ValueError("BREAK_R_TIES_EMPTY_SCORES")

    max_score = max(scores.values())
    tied_candidates = [cand for cand, score in scores.items() if score == max_score]

    if len(tied_candidates) == 1:
        return tied_candidates[0]

    # Exactly equal maxima: prefer valid eligible incumbent if tied
    if incumbent is not None and incumbent in tied_candidates:
        return incumbent

    # Otherwise order by tie_order
    for family in tie_order:
        if family in tied_candidates:
            return family

    # Fallback deterministic sort if candidate is not in tie_order
    return sorted(tied_candidates)[0]
