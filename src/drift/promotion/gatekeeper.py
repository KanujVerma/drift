"""Statistical gatekeeper engine for promotion and overfitting controls (M11-2).

Computes Deflated Sharpe Ratio (DSR), Probability of Backtest Overfitting (PBO),
walk-forward out-of-sample consistency, and volatility regime stress drawdowns
using pure Python standard library mathematics.
"""

import itertools
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from statistics import NormalDist
from uuid import UUID, uuid7

from drift.domain.promotion import (
    PromotionEvaluationRecordV1,
    PromotionGateConfigV1,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
)

EULER_MASCHERONI: float = 0.577215664901532860606512


def calculate_deflated_sharpe_ratio(
    observed_sharpe: Decimal | float,
    trials_k: int,
    variance_of_sharpes: Decimal | float,
    skewness: Decimal | float = 0.0,
    kurtosis: Decimal | float = 3.0,
    sample_size_n: int = 252,
) -> Decimal:
    """Compute Deflated Sharpe Ratio (DSR) under multiple testing and non-normality.

    Implements the Bailey & Lopez de Prado (2014) closed-form DSR formulation:
    Adjusts observed Sharpe ratio for number of explored trials K, variance of
    trial Sharpes, return skewness, and kurtosis.
    """
    sr = float(observed_sharpe)
    k = max(1, trials_k)
    var_sr = max(0.0, float(variance_of_sharpes))
    sk = float(skewness)
    ku = float(kurtosis)
    n = max(2, sample_size_n)

    if k <= 1 or var_sr <= 0.0:
        expected_max_sr = 0.0
    else:
        p1 = max(1e-9, min(1.0 - 1e-9, 1.0 - 1.0 / k))
        p2 = max(1e-9, min(1.0 - 1e-9, 1.0 - 1.0 / (k * math.e)))
        z1 = NormalDist().inv_cdf(p1)
        z2 = NormalDist().inv_cdf(p2)
        expected_max_sr = math.sqrt(var_sr) * (
            (1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2
        )

    var_term = 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr**2)
    if var_term <= 1e-9:
        var_term = 1e-9
    se_sr = math.sqrt(var_term / (n - 1))

    z_score = (sr - expected_max_sr) / se_sr
    dsr_val = NormalDist().cdf(z_score)
    dsr_clamped = max(0.0, min(1.0, dsr_val))
    return Decimal(f"{dsr_clamped:.4f}")


def estimate_probability_backtest_overfitting(
    trial_block_matrix: Sequence[Sequence[Decimal | float]],
) -> Decimal:
    """Estimate Probability of Backtest Overfitting (PBO) via CSCV.

    Partitions performance blocks across trials into combinatorially symmetric
    train/test splits and computes the proportion of splits where the in-sample
    optimal trial underperforms the median out-of-sample rank.
    """
    if not trial_block_matrix or len(trial_block_matrix) < 2:
        return Decimal("0.0000")

    num_trials = len(trial_block_matrix)
    num_blocks = len(trial_block_matrix[0])
    if num_blocks < 2:
        return Decimal("0.0000")

    half_blocks = num_blocks // 2
    combos = list(itertools.combinations(range(num_blocks), half_blocks))
    if not combos:
        return Decimal("0.0000")

    overfit_count = 0
    total_splits = len(combos)

    for is_indices in combos:
        is_set = set(is_indices)
        oos_set = set(range(num_blocks)) - is_set

        is_perf = [
            sum(float(trial_block_matrix[t][b]) for b in is_set)
            for t in range(num_trials)
        ]
        oos_perf = [
            sum(float(trial_block_matrix[t][b]) for b in oos_set)
            for t in range(num_trials)
        ]

        best_is_trial = max(range(num_trials), key=lambda t: is_perf[t])

        better_oos = sum(
            1 for t in range(num_trials) if oos_perf[t] > oos_perf[best_is_trial]
        )
        relative_rank = 1.0 - (better_oos / (num_trials - 1))
        if relative_rank < 0.5:
            overfit_count += 1

    pbo_val = overfit_count / total_splits
    return Decimal(f"{pbo_val:.4f}")


def evaluate_walk_forward_consistency(
    fold_returns: Sequence[Sequence[Decimal | float]],
) -> tuple[Decimal, Decimal]:
    """Evaluate walk-forward out-of-sample consistency across contiguous folds.

    Returns:
        (positive_folds_fraction, cumulative_return)
    """
    if not fold_returns:
        return (Decimal("0.0000"), Decimal("0.0000"))

    total_folds = len(fold_returns)
    positive_folds = 0
    total_cum_ret = 0.0

    for fold in fold_returns:
        fold_floats = [float(r) for r in fold]
        if not fold_floats:
            continue
        fold_sum = sum(fold_floats)
        total_cum_ret += fold_sum
        n_obs = len(fold_floats)
        mean_ret = fold_sum / n_obs
        if n_obs > 1:
            var_fold = sum((r - mean_ret) ** 2 for r in fold_floats) / (n_obs - 1)
            std_fold = math.sqrt(var_fold) if var_fold > 0.0 else 0.0
        else:
            std_fold = 0.0

        sr_fold = (
            (mean_ret / std_fold)
            if std_fold > 0.0
            else (1.0 if mean_ret > 0.0 else (-1.0 if mean_ret < 0.0 else 0.0))
        )
        if sr_fold > 0.0:
            positive_folds += 1

    fraction = Decimal(positive_folds) / Decimal(total_folds)
    return (
        Decimal(f"{fraction:.4f}"),
        Decimal(f"{total_cum_ret:.4f}"),
    )


def evaluate_regime_stress(
    session_returns: Sequence[Decimal | float],
    volatility_series: Sequence[Decimal | float] | None = None,
) -> tuple[Decimal, Mapping[str, Decimal]]:
    """Segment evaluation sessions into volatility regimes and compute drawdowns.

    Returns:
        (max_regime_drawdown, mapping_of_regime_drawdowns)
    """
    if not session_returns:
        return (
            Decimal("0.0000"),
            {
                "low_volatility": Decimal("0.0000"),
                "normal_volatility": Decimal("0.0000"),
                "high_volatility": Decimal("0.0000"),
            },
        )

    returns = [float(r) for r in session_returns]
    n = len(returns)
    if volatility_series is not None and len(volatility_series) == n:
        volatilities = [float(v) for v in volatility_series]
    else:
        volatilities = [abs(r) for r in returns]

    sorted_vols = sorted(volatilities)
    p33 = sorted_vols[n // 3]
    p66 = sorted_vols[(2 * n) // 3]

    regimes: dict[str, list[float]] = {
        "low_volatility": [],
        "normal_volatility": [],
        "high_volatility": [],
    }

    for r, v in zip(returns, volatilities, strict=True):
        if v <= p33:
            regimes["low_volatility"].append(r)
        elif v <= p66:
            regimes["normal_volatility"].append(r)
        else:
            regimes["high_volatility"].append(r)

    def _calc_max_dd(rets: list[float]) -> float:
        if not rets:
            return 0.0
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in rets:
            equity = max(0.0, equity * (1.0 + r))
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0.0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    drawdowns: dict[str, Decimal] = {}
    for regime_name, rets in regimes.items():
        dd_val = _calc_max_dd(rets)
        drawdowns[regime_name] = Decimal(f"{dd_val:.4f}")

    overall_max_dd = max(drawdowns.values()) if drawdowns else Decimal("0.0000")
    return (overall_max_dd, drawdowns)


class PromotionGatekeeper:
    """Four-pillar statistical gatekeeper enforcing promotion invariants."""

    def __init__(self, config: PromotionGateConfigV1) -> None:
        self.config = config

    def evaluate_candidate(
        self,
        *,
        candidate_id: UUID,
        strategy_type: str,
        parameters_hash: str,
        trials_explored_k: int,
        observed_sharpe: Decimal | float,
        trial_sharpes: Sequence[Decimal | float] | None = None,
        trial_block_matrix: Sequence[Sequence[Decimal | float]] | None = None,
        walk_forward_fold_returns: Sequence[Sequence[Decimal | float]] | None = None,
        session_returns: Sequence[Decimal | float] | None = None,
        is_pnl_complete: bool = True,
        is_promotion_grade_evidence: bool = False,
        skewness: Decimal | float = 0.0,
        kurtosis: Decimal | float = 3.0,
        sample_size_n: int = 252,
        evaluation_id: UUID | None = None,
        evaluated_at: datetime | None = None,
    ) -> PromotionEvaluationRecordV1:
        """Execute four-pillar promotion evaluation pipeline on candidate."""
        eval_id = evaluation_id or uuid7()
        ts = evaluated_at or datetime.now(UTC)
        rejection_reasons: list[str] = []

        # 1. PnL completeness validation (Issue #152 fail-closed firewall)
        if not is_pnl_complete:
            rejection_reasons.append("incomplete_realized_pnl_basis")

        # 2. Deflated Sharpe Ratio calculation
        if trial_sharpes and len(trial_sharpes) > 1:
            sharpes_f = [float(s) for s in trial_sharpes]
            mean_s = sum(sharpes_f) / len(sharpes_f)
            var_s = sum((s - mean_s) ** 2 for s in sharpes_f) / (len(sharpes_f) - 1)
        else:
            var_s = 0.0

        dsr = calculate_deflated_sharpe_ratio(
            observed_sharpe=observed_sharpe,
            trials_k=trials_explored_k,
            variance_of_sharpes=var_s,
            skewness=skewness,
            kurtosis=kurtosis,
            sample_size_n=sample_size_n,
        )
        if dsr < self.config.min_dsr:
            rejection_reasons.append("deflated_sharpe_ratio_below_threshold")

        # 3. Probability of Backtest Overfitting estimation
        if trial_block_matrix:
            pbo = estimate_probability_backtest_overfitting(trial_block_matrix)
        else:
            pbo = Decimal("0.0000")

        if pbo > self.config.max_pbo:
            rejection_reasons.append("pbo_exceeds_threshold")

        # 4. Walk-Forward Consistency evaluation
        if walk_forward_fold_returns:
            pos_fraction, cum_ret = evaluate_walk_forward_consistency(
                walk_forward_fold_returns
            )
        else:
            pos_fraction, cum_ret = (Decimal("1.0000"), Decimal("0.0000"))

        if pos_fraction < self.config.min_positive_folds_fraction or cum_ret < Decimal(
            "0.0"
        ):
            rejection_reasons.append("walk_forward_degradation")

        # 5. Volatility Regime Stress evaluation
        if session_returns:
            max_regime_dd, _ = evaluate_regime_stress(session_returns)
        else:
            max_regime_dd = Decimal("0.0000")

        if max_regime_dd > self.config.max_regime_drawdown:
            rejection_reasons.append("regime_drawdown_exceeded")

        # Determine terminal verdict
        if rejection_reasons:
            if "incomplete_realized_pnl_basis" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
            elif "deflated_sharpe_ratio_below_threshold" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
            elif "pbo_exceeds_threshold" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_PBO_OVERFITTING
            elif "walk_forward_degradation" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_WALK_FORWARD_DEGRADATION
            else:
                verdict = PromotionGateVerdict.REJECTED_REGIME_INSTABILITY
        else:
            # Clean qualification: verify promotion authorization versus exploratory
            if (
                is_promotion_grade_evidence
                and self.config.is_promotion_grade_authorized
            ):
                verdict = PromotionGateVerdict.PROMOTION_QUALIFIED
            else:
                verdict = PromotionGateVerdict.EXPLORATORY_PASSED

        return build_promotion_evaluation_record(
            evaluation_id=eval_id,
            candidate_id=candidate_id,
            strategy_type=strategy_type,
            parameters_hash=parameters_hash,
            deflated_sharpe_ratio=dsr,
            pbo_estimate=pbo,
            positive_folds_fraction=pos_fraction,
            max_regime_drawdown=max_regime_dd,
            trials_explored_k=trials_explored_k,
            verdict=verdict,
            rejection_reasons=tuple(rejection_reasons),
            evaluated_at=ts,
        )
