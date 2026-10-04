"""Predictive power and calibration metrics engine (M5-2, Issue 191).

Provides pure-Python deterministic implementations of:
- Fractional rank derivation with symmetric tie-breaking;
- Cross-sectional Spearman rank correlation and Pearson correlation;
- Time-series Information Coefficient (IC) aggregation and quantile monotonicity;
- Probabilistic and directional calibration (Brier score, ECE, MCE, reliability bins);
- End-to-end prediction scorecard generation linking M4 prediction sets and outcomes.
"""

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from drift.domain.common import UTCDateTime
from drift.domain.evaluator_bundles import EvaluationRunIdentityV2
from drift.domain.evaluator_portfolio import EvaluationLane
from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    RealizedOutcomeBatchV1,
    RealizedOutcomeRecordV1,
)
from drift.domain.predictions import (
    DirectionalPredictionV1,
    ExAntePredictionSetV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.domain.scorecards import (
    CalibrationBinV1,
    CalibrationSummaryV1,
    InformationCoefficientSummaryV1,
    PredictionScorecardV1,
    build_prediction_scorecard,
)

FOUR_PLACES = Decimal("0.0001")
SIX_PLACES = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")


def _quantize_decimal(val: Decimal, precision: Decimal = FOUR_PLACES) -> Decimal:
    """Round Decimal to target precision with half-even rounding."""
    return val.quantize(precision, rounding=ROUND_HALF_EVEN)


def fractional_ranks(values: Sequence[Decimal]) -> list[Decimal]:
    """Compute 1-based fractional ranks with average tie-breaking.

    For example, [10, 20, 20, 30] -> [1.0, 2.5, 2.5, 4.0].
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [ONE]

    indexed_values = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks: list[Decimal] = [ZERO] * n

    i = 0
    while i < n:
        j = i
        val = indexed_values[i][1]
        while j < n and indexed_values[j][1] == val:
            j += 1
        # Indices i through j-1 have identical values.
        # Their 1-based ranks are (i+1) through j.
        # Average rank is sum(k for k in range(i+1, j+1)) / (j - i).
        avg_rank = Decimal(i + 1 + j) / TWO
        for k in range(i, j):
            original_idx = indexed_values[k][0]
            ranks[original_idx] = avg_rank
        i = j

    return ranks


def compute_pearson_correlation(
    x: Sequence[Decimal], y: Sequence[Decimal]
) -> Decimal | None:
    """Compute Pearson correlation coefficient between two numeric sequences."""
    n = len(x)
    if n != len(y) or n < 2:
        return None

    mean_x = sum(x, ZERO) / Decimal(n)
    mean_y = sum(y, ZERO) / Decimal(n)

    cov = ZERO
    var_x = ZERO
    var_y = ZERO

    for xi, yi in zip(x, y, strict=True):
        dx = xi - mean_x
        dy = yi - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy

    if var_x == ZERO or var_y == ZERO:
        return ZERO

    denom = Decimal(str(math.sqrt(float(var_x * var_y))))
    if denom == ZERO:
        return ZERO

    r = cov / denom
    # Clamp to [-1, 1] to avoid float precision overflow.
    if r > ONE:
        r = ONE
    elif r < -ONE:
        r = -ONE

    return _quantize_decimal(r)


def compute_spearman_rank_correlation(
    x: Sequence[Decimal], y: Sequence[Decimal]
) -> Decimal | None:
    """Compute Spearman rank correlation using fractional ranks."""
    if len(x) != len(y) or len(x) < 2:
        return None

    rank_x = fractional_ranks(x)
    rank_y = fractional_ranks(y)
    return compute_pearson_correlation(rank_x, rank_y)


def aggregate_information_coefficients(
    epoch_spearman_ics: Sequence[Decimal],
    epoch_pearson_ics: Sequence[Decimal] | None = None,
    *,
    sessions_per_year: int = 252,
    quantile_returns: Sequence[Sequence[Decimal]] | None = None,
) -> InformationCoefficientSummaryV1:
    """Aggregate time-series Information Coefficients across decision epochs."""
    t = len(epoch_spearman_ics)
    if t == 0:
        return InformationCoefficientSummaryV1(
            mean_spearman_ic=ZERO,
            std_spearman_ic=ZERO,
            information_ratio_ic=ZERO,
            t_statistic_ic=ZERO,
            positive_ic_ratio=ZERO,
            mean_pearson_ic=ZERO,
            evaluated_sessions=0,
            quantile_spread_return=None,
            is_rank_monotonic=None,
        )

    dec_t = Decimal(t)
    mean_spearman = sum(epoch_spearman_ics, ZERO) / dec_t

    if t > 1:
        sum_sq_diff = sum((ic - mean_spearman) ** 2 for ic in epoch_spearman_ics)
        sample_variance = sum_sq_diff / Decimal(t - 1)
        std_spearman = Decimal(str(math.sqrt(float(sample_variance))))
    else:
        std_spearman = ZERO

    if std_spearman > ZERO:
        annual_factor = Decimal(str(math.sqrt(sessions_per_year)))
        ir_ic = (mean_spearman / std_spearman) * annual_factor
        se = std_spearman / Decimal(str(math.sqrt(t)))
        t_stat = mean_spearman / se if se > ZERO else ZERO
    else:
        ir_ic = ZERO
        t_stat = ZERO

    positive_count = sum(1 for ic in epoch_spearman_ics if ic > ZERO)
    pos_ratio = Decimal(positive_count) / dec_t

    if epoch_pearson_ics and len(epoch_pearson_ics) == t:
        mean_pearson = sum(epoch_pearson_ics, ZERO) / dec_t
    else:
        mean_pearson = mean_spearman

    spread_return: Decimal | None = None
    is_monotonic: bool | None = None

    if quantile_returns and len(quantile_returns) > 0:
        num_quantiles = len(quantile_returns[0])
        if (
            all(len(qr) == num_quantiles for qr in quantile_returns)
            and num_quantiles > 1
        ):
            avg_quantile_returns: list[Decimal] = []
            for q_idx in range(num_quantiles):
                q_mean = sum(qr[q_idx] for qr in quantile_returns) / Decimal(
                    len(quantile_returns)
                )
                avg_quantile_returns.append(q_mean)
            spread_return = _quantize_decimal(
                avg_quantile_returns[-1] - avg_quantile_returns[0]
            )
            is_monotonic = all(
                avg_quantile_returns[i] <= avg_quantile_returns[i + 1]
                for i in range(num_quantiles - 1)
            )

    return InformationCoefficientSummaryV1(
        mean_spearman_ic=_quantize_decimal(mean_spearman),
        std_spearman_ic=_quantize_decimal(std_spearman),
        information_ratio_ic=_quantize_decimal(ir_ic),
        t_statistic_ic=_quantize_decimal(t_stat),
        positive_ic_ratio=_quantize_decimal(pos_ratio),
        mean_pearson_ic=_quantize_decimal(mean_pearson),
        evaluated_sessions=t,
        quantile_spread_return=spread_return,
        is_rank_monotonic=is_monotonic,
    )


def compute_calibration_summary(
    predictions: Sequence[Decimal],
    ground_truth: Sequence[Decimal],
    *,
    num_bins: int = 10,
    is_binary: bool = True,
) -> CalibrationSummaryV1:
    """Compute calibration metrics, error statistics, and reliability bins."""
    n = len(predictions)
    if n == 0 or len(ground_truth) != n:
        return CalibrationSummaryV1()

    dec_n = Decimal(n)
    sum_abs_err = ZERO
    sum_sq_err = ZERO

    for p, y in zip(predictions, ground_truth, strict=True):
        err = p - y
        sum_abs_err += abs(err)
        sum_sq_err += err * err

    mae = _quantize_decimal(sum_abs_err / dec_n)
    rmse = _quantize_decimal(Decimal(str(math.sqrt(float(sum_sq_err / dec_n)))))

    if not is_binary:
        return CalibrationSummaryV1(
            mean_absolute_error=mae,
            root_mean_squared_error=rmse,
        )

    # Binary directional calibration metrics
    brier_score = _quantize_decimal(sum_sq_err / dec_n)

    # Bin partitioning over [0.0, 1.0]
    bin_step = ONE / Decimal(num_bins)
    bin_samples: list[list[tuple[Decimal, Decimal]]] = [[] for _ in range(num_bins)]

    for p, y in zip(predictions, ground_truth, strict=True):
        clamped_p = max(ZERO, min(ONE, p))
        bin_idx = int(clamped_p / bin_step)
        if bin_idx >= num_bins:
            bin_idx = num_bins - 1
        bin_samples[bin_idx].append((clamped_p, y))

    bins: list[CalibrationBinV1] = []
    ece_acc = ZERO
    mce_val = ZERO

    for b_idx in range(num_bins):
        b_lower = Decimal(b_idx) * bin_step
        b_upper = Decimal(b_idx + 1) * bin_step
        samples = bin_samples[b_idx]
        count = len(samples)

        if count > 0:
            dec_count = Decimal(count)
            avg_conf = sum((s[0] for s in samples), ZERO) / dec_count
            avg_acc = sum((s[1] for s in samples), ZERO) / dec_count
            bin_gap = abs(avg_conf - avg_acc)
            ece_acc += (dec_count / dec_n) * bin_gap
            if bin_gap > mce_val:
                mce_val = bin_gap
        else:
            avg_conf = (b_lower + b_upper) / TWO
            avg_acc = ZERO

        bins.append(
            CalibrationBinV1(
                bin_index=b_idx,
                bin_lower=_quantize_decimal(b_lower),
                bin_upper=_quantize_decimal(b_upper),
                predicted_confidence=_quantize_decimal(avg_conf),
                empirical_accuracy=_quantize_decimal(avg_acc),
                sample_count=count,
            )
        )

    # Calibration slope and intercept: linear regression of y on p
    mean_p = sum(predictions, ZERO) / dec_n
    mean_y = sum(ground_truth, ZERO) / dec_n
    var_p = sum(((p - mean_p) ** 2 for p in predictions), ZERO)
    cov_py = sum(
        (
            (p - mean_p) * (y - mean_y)
            for p, y in zip(predictions, ground_truth, strict=True)
        ),
        ZERO,
    )

    if var_p > ZERO:
        slope = cov_py / var_p
        intercept = mean_y - slope * mean_p
        cal_slope = _quantize_decimal(slope)
        cal_intercept = _quantize_decimal(intercept)
    else:
        cal_slope = None
        cal_intercept = None

    return CalibrationSummaryV1(
        brier_score=brier_score,
        expected_calibration_error=_quantize_decimal(ece_acc),
        maximum_calibration_error=_quantize_decimal(mce_val),
        calibration_slope=cal_slope,
        calibration_intercept=cal_intercept,
        mean_absolute_error=mae,
        root_mean_squared_error=rmse,
        bins=tuple(bins),
    )


def generate_prediction_scorecard(
    *,
    prediction_sets: Sequence[ExAntePredictionSetV1],
    outcome_batches: Sequence[RealizedOutcomeBatchV1],
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    prediction_target: PredictionTargetType,
    as_of_time: UTCDateTime,
    scorecard_id: UUID | None = None,
    num_calibration_bins: int = 10,
    num_rank_quantiles: int = 5,
) -> PredictionScorecardV1:
    """Generate an immutable PredictionScorecardV1 linking inputs."""
    # Build fast lookup mapping outcome records by prediction_id
    outcomes_by_pred_id: dict[UUID, RealizedOutcomeRecordV1] = {}
    for batch in outcome_batches:
        for rec in batch.outcomes:
            outcomes_by_pred_id[rec.prediction_id] = rec

    total_predictions = 0
    resolved_count = 0
    indeterminate_count = 0
    delisted_count = 0

    all_pred_values: list[Decimal] = []
    all_realized_values: list[Decimal] = []

    epoch_spearman_ics: list[Decimal] = []
    epoch_pearson_ics: list[Decimal] = []
    epoch_quantile_returns: list[list[Decimal]] = []

    # Process prediction sets ordered by session date
    sorted_sets = sorted(prediction_sets, key=lambda ps: ps.session_date)

    for pred_set in sorted_sets:
        epoch_preds: list[Decimal] = []
        epoch_reals: list[Decimal] = []

        for pred in pred_set.predictions:
            total_predictions += 1
            outcome = outcomes_by_pred_id.get(pred.prediction_id)

            if outcome is None:
                indeterminate_count += 1
                continue

            if outcome.status == OutcomeResolutionStatus.RESOLVED:
                resolved_count += 1
                if outcome.realized_value is not None:
                    # Extract scalar prediction value
                    pred_val: Decimal | None = None
                    val = pred.prediction_value
                    if isinstance(val, ScalarPointPredictionV1):
                        pred_val = val.point_value
                    elif isinstance(val, DirectionalPredictionV1):
                        conf = val.confidence
                        if val.direction == "up":
                            pred_val = conf
                        elif val.direction == "down":
                            pred_val = ONE - conf
                        else:
                            pred_val = Decimal("0.5")

                    if pred_val is not None:
                        epoch_preds.append(pred_val)
                        epoch_reals.append(outcome.realized_value)
                        all_pred_values.append(pred_val)
                        all_realized_values.append(outcome.realized_value)

            elif outcome.status in (
                OutcomeResolutionStatus.DELISTED_WITH_OUTCOME,
                OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME,
            ):
                delisted_count += 1
            else:
                indeterminate_count += 1

        # Calculate epoch-level cross-sectional rank and linear correlation
        if len(epoch_preds) >= 2:
            s_ic = compute_spearman_rank_correlation(epoch_preds, epoch_reals)
            p_ic = compute_pearson_correlation(epoch_preds, epoch_reals)
            if s_ic is not None:
                epoch_spearman_ics.append(s_ic)
            if p_ic is not None:
                epoch_pearson_ics.append(p_ic)

            # Quantile partition for rank monotonicity if enough assets
            if len(epoch_preds) >= num_rank_quantiles:
                # Rank predictions and partition into quantiles
                paired = sorted(
                    zip(epoch_preds, epoch_reals, strict=True), key=lambda pair: pair[0]
                )
                n_epoch = len(paired)
                q_size = n_epoch / num_rank_quantiles
                q_returns: list[Decimal] = []
                for q_i in range(num_rank_quantiles):
                    start_i = int(q_i * q_size)
                    end_i = (
                        int((q_i + 1) * q_size)
                        if q_i < num_rank_quantiles - 1
                        else n_epoch
                    )
                    chunk = paired[start_i:end_i]
                    if chunk:
                        avg_q_ret = sum((c[1] for c in chunk), ZERO) / Decimal(
                            len(chunk)
                        )
                        q_returns.append(avg_q_ret)
                    else:
                        q_returns.append(ZERO)
                epoch_quantile_returns.append(q_returns)

    # Aggregate IC metrics across all evaluated epochs
    ic_summary = aggregate_information_coefficients(
        epoch_spearman_ics,
        epoch_pearson_ics,
        quantile_returns=epoch_quantile_returns if epoch_quantile_returns else None,
    )

    # Determine whether target is binary (directional) or continuous
    is_binary_target = prediction_target == PredictionTargetType.DIRECTIONAL_RETURN
    if is_binary_target and all_realized_values:
        # Convert realized returns to binary indicators (1 for positive, 0 otherwise)
        binary_ground_truth = [ONE if r > ZERO else ZERO for r in all_realized_values]
        calibration_summary = compute_calibration_summary(
            all_pred_values,
            binary_ground_truth,
            num_bins=num_calibration_bins,
            is_binary=True,
        )
    else:
        calibration_summary = compute_calibration_summary(
            all_pred_values,
            all_realized_values,
            num_bins=num_calibration_bins,
            is_binary=False,
        )

    sc_id = scorecard_id or UUID("018f3a5b-6c7d-7890-8123-456789abcd01")

    return build_prediction_scorecard(
        scorecard_id=sc_id,
        run_identity=run_identity,
        lane=lane,
        prediction_target=prediction_target,
        ic_summary=ic_summary,
        calibration_summary=calibration_summary,
        total_predictions=total_predictions,
        resolved_predictions=resolved_count,
        indeterminate_predictions=indeterminate_count,
        delisted_predictions=delisted_count,
        created_at=as_of_time,
    )
