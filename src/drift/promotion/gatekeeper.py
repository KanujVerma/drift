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
from typing import cast
from uuid import UUID, uuid7

from drift.domain.promotion import (
    IncompletePromotionRejectionV2,
    PromotionEvaluationRecordV1,
    PromotionGateConfigV1,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.promotion.recorder import PromotionRecorder
from drift.serialization.canonical import content_hash

EULER_MASCHERONI: float = 0.577215664901532860606512


def _snapshot_evidence(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot_evidence(item) for item in value)
    return value


def _fingerprint_value(value: object) -> object:
    """Represent supported request values without losing type or non-finite values."""
    if value is None:
        return ["none"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        return ["float", value.hex()]
    if isinstance(value, Decimal):
        return ["decimal", str(value)]
    if type(value) is str:
        return ["str", value]
    if isinstance(value, (list, tuple)):
        return ["sequence", [_fingerprint_value(item) for item in value]]
    raise ValueError(
        "request contains evidence that cannot be truthfully fingerprinted"
    )


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (float, int, Decimal)):
        return False
    try:
        return math.isfinite(float(value))
    except ValueError, OverflowError:
        return False


def _require_finite(*values: float) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ArithmeticError("non-finite intermediate calculation")


def _finite_sequence(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(_finite_number(item) for item in value)
    )


def _usable_matrix(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(_finite_sequence(row) for row in value)
        and len(value[0]) >= 2
        and all(len(row) == len(value[0]) for row in value)
    )


def _usable_folds(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(_finite_sequence(row) for row in value)
    )


def calculate_deflated_sharpe_ratio(
    observed_sharpe: Decimal | float,
    trials_k: int,
    variance_of_sharpes: Decimal | float,
    skewness: Decimal | float | None = None,
    kurtosis: Decimal | float | None = None,
    sample_size_n: int | None = None,
) -> Decimal:
    """Compute Deflated Sharpe Ratio (DSR) under multiple testing and non-normality.

    Implements the Bailey & Lopez de Prado (2014) closed-form DSR formulation:
    Adjusts observed Sharpe ratio for number of explored trials K, variance of
    trial Sharpes, return skewness, and kurtosis.
    """
    if (
        type(trials_k) is not int
        or trials_k < 1
        or type(sample_size_n) is not int
        or sample_size_n < 2
        or not all(
            _finite_number(x)
            for x in (observed_sharpe, variance_of_sharpes, skewness, kurtosis)
        )
        or float(variance_of_sharpes) < 0.0
    ):
        raise ValueError("unusable DSR evidence")
    assert skewness is not None
    assert kurtosis is not None
    assert sample_size_n is not None
    sr = float(observed_sharpe)
    k = trials_k
    var_sr = float(variance_of_sharpes)
    sk = float(skewness)
    ku = float(kurtosis)
    n = sample_size_n
    _require_finite(sr, var_sr, sk, ku)

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
    _require_finite(expected_max_sr, var_term)
    if var_term <= 0.0:
        raise ValueError("unusable DSR sampling variance")
    se_sr = math.sqrt(var_term / (n - 1))

    z_score = (sr - expected_max_sr) / se_sr
    _require_finite(se_sr, z_score)
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
    if not _usable_matrix(trial_block_matrix):
        raise ValueError("unusable trial block evidence")

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
        _require_finite(*is_perf, *oos_perf)

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
    if not _usable_folds(fold_returns):
        raise ValueError("unusable walk-forward evidence")

    total_folds = len(fold_returns)
    positive_folds = 0
    total_cum_ret = 0.0

    for fold in fold_returns:
        fold_floats = [float(r) for r in fold]
        if not fold_floats:
            continue
        fold_sum = sum(fold_floats)
        total_cum_ret += fold_sum
        _require_finite(fold_sum, total_cum_ret)
        n_obs = len(fold_floats)
        mean_ret = fold_sum / n_obs
        if n_obs > 1:
            var_fold = sum((r - mean_ret) ** 2 for r in fold_floats) / (n_obs - 1)
            _require_finite(var_fold)
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
    if not _finite_sequence(session_returns):
        raise ValueError("unusable session evidence")
    if volatility_series is not None and (
        not _finite_sequence(volatility_series)
        or len(volatility_series) != len(session_returns)
    ):
        raise ValueError("unusable volatility evidence")

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
            next_equity = equity * (1.0 + r)
            _require_finite(next_equity)
            equity = max(0.0, next_equity)
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
        self.config = PromotionGateConfigV1.model_validate(
            config.model_dump(mode="python")
        )

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
        is_pnl_complete: bool = False,
        is_promotion_grade_evidence: bool = False,
        skewness: Decimal | float | None = None,
        kurtosis: Decimal | float | None = None,
        sample_size_n: int | None = None,
        evaluation_id: UUID | None = None,
        evaluated_at: datetime | None = None,
        recorder: PromotionRecorder | None = None,
    ) -> PromotionEvaluationRecordV1 | IncompletePromotionRejectionV2:
        """Execute four-pillar promotion evaluation pipeline on candidate."""
        if type(recorder) is not PromotionRecorder:
            raise RuntimeError("an audit recorder is required to seal an evaluation")
        if not isinstance(strategy_type, str) or strategy_type != strategy_type.strip():
            raise ValueError("strategy identity must not be normalized")
        if type(is_promotion_grade_evidence) is not bool:
            raise ValueError("invalid promotion grade evidence assertion")
        trial_sharpes = cast(
            Sequence[Decimal | float] | None, _snapshot_evidence(trial_sharpes)
        )
        trial_block_matrix = cast(
            Sequence[Sequence[Decimal | float]] | None,
            _snapshot_evidence(trial_block_matrix),
        )
        walk_forward_fold_returns = cast(
            Sequence[Sequence[Decimal | float]] | None,
            _snapshot_evidence(walk_forward_fold_returns),
        )
        session_returns = cast(
            Sequence[Decimal | float] | None, _snapshot_evidence(session_returns)
        )
        eval_id = uuid7() if evaluation_id is None else evaluation_id
        ts = datetime.now(UTC) if evaluated_at is None else evaluated_at
        incomplete: list[str] = []
        if is_pnl_complete is not True:
            incomplete.append("pnl_completeness_not_confirmed")
        if not _usable_matrix(trial_block_matrix):
            incomplete.append("unusable_trial_block_matrix")
        if not _usable_folds(walk_forward_fold_returns):
            incomplete.append("unusable_walk_forward_fold_returns")
        if not _finite_sequence(session_returns):
            incomplete.append("unusable_session_returns")
        if not _finite_number(observed_sharpe):
            incomplete.append("unusable_observed_sharpe")
        if (trial_sharpes is not None and not _finite_sequence(trial_sharpes)) or (
            type(trials_explored_k) is int
            and trials_explored_k > 1
            and (trial_sharpes is None or len(trial_sharpes) < 2)
        ):
            incomplete.append("unusable_trial_sharpes")
        if not _finite_number(skewness) or not _finite_number(kurtosis):
            incomplete.append("unusable_distribution_inputs")
        if type(trials_explored_k) is not int or trials_explored_k < 1:
            incomplete.append("unusable_trials_explored_k")
        if type(sample_size_n) is not int or sample_size_n < 2:
            incomplete.append("unusable_sample_size_n")

        def seal_incomplete(reasons: tuple[str, ...]) -> IncompletePromotionRejectionV2:
            record = IncompletePromotionRejectionV2(
                evaluation_id=eval_id,
                candidate_id=candidate_id,
                strategy_type=strategy_type,
                parameters_hash=parameters_hash,
                request_hash=content_hash(
                    _fingerprint_value(
                        [
                            self.config.config_hash,
                            trials_explored_k,
                            observed_sharpe,
                            trial_sharpes,
                            trial_block_matrix,
                            walk_forward_fold_returns,
                            session_returns,
                            is_pnl_complete,
                            is_promotion_grade_evidence,
                            skewness,
                            kurtosis,
                            sample_size_n,
                        ]
                    )
                ),
                rejection_reasons=reasons,
                evaluated_at=ts,
            )
            assert recorder is not None
            recorder.record_incomplete(record)
            return record

        if incomplete:
            return seal_incomplete(tuple(incomplete))
        rejection_reasons: list[str] = []

        assert trial_block_matrix is not None
        assert walk_forward_fold_returns is not None
        assert session_returns is not None
        assert skewness is not None
        assert kurtosis is not None
        assert sample_size_n is not None
        try:
            if trial_sharpes and len(trial_sharpes) > 1:
                sharpes_f = [float(s) for s in trial_sharpes]
                mean_s = sum(sharpes_f) / len(sharpes_f)
                var_s = sum((s - mean_s) ** 2 for s in sharpes_f) / (len(sharpes_f) - 1)
            else:
                var_s = 0.0
            _require_finite(var_s)
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

            pbo = estimate_probability_backtest_overfitting(trial_block_matrix)
            if pbo > self.config.max_pbo:
                rejection_reasons.append("pbo_exceeds_threshold")

            pos_fraction, cum_ret = evaluate_walk_forward_consistency(
                walk_forward_fold_returns
            )
            if (
                pos_fraction < self.config.min_positive_folds_fraction
                or cum_ret < Decimal("0.0")
            ):
                rejection_reasons.append("walk_forward_degradation")

            max_regime_dd, _ = evaluate_regime_stress(session_returns)
            if max_regime_dd > self.config.max_regime_drawdown:
                rejection_reasons.append("regime_drawdown_exceeded")
        except ArithmeticError, ValueError:
            return seal_incomplete(("unusable_numeric_calculation",))

        # Determine terminal verdict
        if rejection_reasons:
            if "deflated_sharpe_ratio_below_threshold" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
            elif "pbo_exceeds_threshold" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_PBO_OVERFITTING
            elif "walk_forward_degradation" in rejection_reasons:
                verdict = PromotionGateVerdict.REJECTED_WALK_FORWARD_DEGRADATION
            else:
                verdict = PromotionGateVerdict.REJECTED_REGIME_INSTABILITY
        else:
            # Caller assertions are not authenticated promotion provenance.
            verdict = PromotionGateVerdict.EXPLORATORY_PASSED

        complete_record = build_promotion_evaluation_record(
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
        request_hash = content_hash(
            {
                "config": self.config.model_dump(mode="python"),
                "evaluation_id": complete_record.evaluation_id,
                "candidate_id": complete_record.candidate_id,
                "strategy_type": complete_record.strategy_type,
                "parameters_hash": complete_record.parameters_hash,
                "evaluated_at": complete_record.evaluated_at,
                "inputs": _fingerprint_value(
                    [
                        trials_explored_k,
                        observed_sharpe,
                        trial_sharpes,
                        trial_block_matrix,
                        walk_forward_fold_returns,
                        session_returns,
                        is_pnl_complete,
                        is_promotion_grade_evidence,
                        skewness,
                        kurtosis,
                        sample_size_n,
                    ]
                ),
            }
        )
        recorder.record_evaluation(
            complete_record,
            event_id=deterministic_memory_uuid7(
                f"promotion_eval_request:{complete_record.evaluation_id}:{request_hash}"
            ),
        )
        if verdict != PromotionGateVerdict.EXPLORATORY_PASSED:
            recorder.record_rejection(complete_record)
        return complete_record
