"""Statistical differential comparator and tournament match evaluator (M10-2).

Provides pure Python standard library statistical hypothesis testing on paired
session return series and deterministic multi-criteria gatekeeping for Champion
versus Challenger tournament decisions.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import NormalDist

from drift.domain.tournament import TournamentConfigV1, TournamentDecision

__all__ = [
    "TournamentComparisonResult",
    "compute_paired_returns_statistics",
    "evaluate_head_to_head_match",
]


@dataclass(frozen=True)
class TournamentComparisonResult:
    """Outcome metrics and verdict of a statistical head-to-head comparison."""

    decision: TournamentDecision
    rejection_reasons: tuple[str, ...]
    delta_sharpe: Decimal
    turnover_ratio: Decimal
    paired_t_stat: Decimal
    p_value: Decimal
    evaluated_sessions_count: int


def compute_paired_returns_statistics(
    champion_returns: Sequence[Decimal],
    challenger_returns: Sequence[Decimal],
) -> tuple[Decimal, Decimal, Decimal]:
    """Compute mean paired return differential, paired t-stat, and p-value.

    Returns:
        (mean_diff, t_stat, p_value)
    """
    n = len(champion_returns)
    if n != len(challenger_returns):
        raise ValueError(
            f"Mismatched return sequence lengths: champion={n}, "
            f"challenger={len(challenger_returns)}"
        )
    if n < 2:
        return Decimal("0.0"), Decimal("0.0"), Decimal("1.0")

    diffs = [
        float(chal - champ)
        for champ, chal in zip(champion_returns, challenger_returns, strict=True)
    ]
    mean_diff = sum(diffs) / n

    variance = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
    std_dev = math.sqrt(variance)
    standard_error = std_dev / math.sqrt(n)

    if standard_error == 0.0:
        # Zero variance across sample differences cannot prove significance
        return Decimal(str(round(mean_diff, 8))), Decimal("0.0"), Decimal("1.0")

    t_stat = mean_diff / standard_error

    # Two-sided p-value using standard normal approximation
    norm = NormalDist(0.0, 1.0)
    p_val = 2.0 * (1.0 - norm.cdf(abs(t_stat)))
    p_val = max(0.0, min(1.0, p_val))

    return (
        Decimal(str(round(mean_diff, 8))),
        Decimal(str(round(t_stat, 4))),
        Decimal(str(round(p_val, 6))),
    )


def evaluate_head_to_head_match(
    *,
    config: TournamentConfigV1,
    champion_sharpe: Decimal | None,
    challenger_sharpe: Decimal | None,
    champion_max_drawdown: Decimal | None,
    challenger_max_drawdown: Decimal | None,
    champion_turnover: Decimal | None,
    challenger_turnover: Decimal | None,
    champion_returns: Sequence[Decimal] | None,
    challenger_returns: Sequence[Decimal] | None,
    trials_evaluated_count: int = 1,
    is_pnl_complete: bool = False,
) -> TournamentComparisonResult:
    """Evaluate head-to-head match against configuration bounds."""
    rejection_reasons: list[str] = []
    primary_decision: TournamentDecision | None = None

    # 1. Realized PnL completeness gate (Issue #152)
    if not is_pnl_complete:
        rejection_reasons.append(
            "realized PnL completeness not satisfied; disposals missing cost basis"
        )
        primary_decision = TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE

    # 2. Check for missing required metrics
    if (
        champion_sharpe is None
        or challenger_sharpe is None
        or champion_max_drawdown is None
        or challenger_max_drawdown is None
        or champion_turnover is None
        or challenger_turnover is None
    ):
        rejection_reasons.append("missing required evaluation metric")
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
        c_sharpe = champion_sharpe or Decimal("0.0")
        h_sharpe = challenger_sharpe or Decimal("0.0")
        c_drawdown = champion_max_drawdown or Decimal("0.0")
        h_drawdown = challenger_max_drawdown or Decimal("0.0")
        c_turnover = champion_turnover or Decimal("0.0")
        h_turnover = challenger_turnover or Decimal("0.0")
    else:
        c_sharpe = champion_sharpe
        h_sharpe = challenger_sharpe
        c_drawdown = champion_max_drawdown
        h_drawdown = challenger_max_drawdown
        c_turnover = champion_turnover
        h_turnover = challenger_turnover

    delta_sharpe = h_sharpe - c_sharpe
    denom_turnover = max(c_turnover, Decimal("1.0"))
    turnover_ratio = (h_turnover / denom_turnover).quantize(Decimal("0.0001"))

    # 3. Check session returns completeness and alignment
    if (
        champion_returns is None
        or challenger_returns is None
        or len(champion_returns) == 0
        or len(challenger_returns) == 0
    ):
        rejection_reasons.append("missing session returns sequence")
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
        return TournamentComparisonResult(
            decision=primary_decision,
            rejection_reasons=tuple(rejection_reasons),
            delta_sharpe=delta_sharpe,
            turnover_ratio=turnover_ratio,
            paired_t_stat=Decimal("0.0"),
            p_value=Decimal("1.0"),
            evaluated_sessions_count=0,
        )

    n = len(champion_returns)
    if n != len(challenger_returns):
        rejection_reasons.append(
            f"mismatched return sequence lengths: champion={n}, "
            f"challenger={len(challenger_returns)}"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_INCOMPLETE_EVIDENCE
        return TournamentComparisonResult(
            decision=primary_decision,
            rejection_reasons=tuple(rejection_reasons),
            delta_sharpe=delta_sharpe,
            turnover_ratio=turnover_ratio,
            paired_t_stat=Decimal("0.0"),
            p_value=Decimal("1.0"),
            evaluated_sessions_count=min(n, len(challenger_returns)),
        )

    mean_diff, t_stat, p_value = compute_paired_returns_statistics(
        champion_returns,
        challenger_returns,
    )

    # 4. Evaluation sessions count gate
    if n < config.min_evaluation_sessions:
        rejection_reasons.append(
            f"insufficient evaluation sessions: {n} < {config.min_evaluation_sessions}"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT

    # 5. Minimum Delta Sharpe hurdle
    if delta_sharpe < config.min_delta_sharpe:
        rejection_reasons.append(
            f"delta_sharpe ({delta_sharpe}) below required minimum "
            f"({config.min_delta_sharpe})"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_INSUFFICIENT_OUTPERFORMANCE

    # 6. Statistical significance test with multiple-testing adjustment
    k = max(1, trials_evaluated_count)
    adjusted_alpha = config.significance_alpha / Decimal(str(k))
    if p_value > adjusted_alpha:
        rejection_reasons.append(
            f"p-value ({p_value}) exceeds significance alpha ({adjusted_alpha}) "
            f"with K={k} adjustment"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT

    # 7. Maximum Drawdown risk boundary
    allowed_drawdown = c_drawdown * (Decimal("1.0") + config.max_drawdown_slack)
    if h_drawdown > allowed_drawdown:
        rejection_reasons.append(
            f"challenger max_drawdown ({h_drawdown}) breached allowed limit "
            f"({allowed_drawdown})"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_EXCESSIVE_DRAWDOWN

    # 8. Turnover drag ratio boundary
    if turnover_ratio > config.max_turnover_ratio:
        rejection_reasons.append(
            f"turnover_ratio ({turnover_ratio}) breached maximum allowed limit "
            f"({config.max_turnover_ratio})"
        )
        if primary_decision is None:
            primary_decision = TournamentDecision.REJECTED_EXCESSIVE_TURNOVER

    if not rejection_reasons:
        final_decision = TournamentDecision.PROMOTED
    else:
        final_decision = (
            primary_decision
            if primary_decision is not None
            else TournamentDecision.REJECTED_INSUFFICIENT_OUTPERFORMANCE
        )

    return TournamentComparisonResult(
        decision=final_decision,
        rejection_reasons=tuple(rejection_reasons),
        delta_sharpe=delta_sharpe,
        turnover_ratio=turnover_ratio,
        paired_t_stat=t_stat,
        p_value=p_value,
        evaluated_sessions_count=n,
    )
