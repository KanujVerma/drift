"""Multiple-testing adjustment engine and selection bias controls (M5-4, Issue 195).

Provides pure-Python deterministic implementations of:
- Deflated Sharpe Ratio (DSR) (Bailey & Lopez de Prado 2014);
- Expected maximum Sharpe ratio under the null hypothesis of no skill;
- Sample return moments (mean, variance, skewness, kurtosis);
- Family-Wise Error Rate (FWER) adjustments (Bonferroni, Holm-Bonferroni);
- False Discovery Rate (FDR) adjustments (Benjamini-Hochberg);
- High-level MultipleTestingSummaryV1 generation.
"""

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import NormalDist

from drift.domain.scorecards import MultipleTestingSummaryV1

FOUR_PLACES = Decimal("0.0001")
SIX_PLACES = Decimal("0.000001")
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
THREE = Decimal("3")
FOUR = Decimal("4")

EULER_MASCHERONI = 0.577215664901532860606512090082402431042
_NORMAL = NormalDist(mu=0.0, sigma=1.0)


def compute_sample_moments(
    returns: Sequence[Decimal],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Compute mean, sample variance, skewness, and kurtosis from returns.

    Returns:
        tuple of (mean, variance, skewness, kurtosis).
        For sample size < 2 or zero variance, skewness is 0 and kurtosis is 3.
    """
    n = len(returns)
    if n < 2:
        return ZERO, ZERO, ZERO, THREE

    n_dec = Decimal(str(n))
    mean = sum(returns, ZERO) / n_dec

    diffs = [r - mean for r in returns]
    sum_sq = sum((d * d for d in diffs), ZERO)
    variance = sum_sq / Decimal(str(n - 1))

    if variance <= ZERO:
        return mean.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN), ZERO, ZERO, THREE

    std_dev = Decimal(str(math.sqrt(float(variance))))
    if std_dev <= ZERO:
        return mean.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN), ZERO, ZERO, THREE

    # Skewness: (1/N * sum(d^3)) / (1/N * sum(d^2))^(3/2)
    m2 = sum_sq / n_dec
    sum_cubes = sum((d * d * d for d in diffs), ZERO)
    m3 = sum_cubes / n_dec
    m2_std = Decimal(str(math.sqrt(float(m2))))
    skewness = (m3 / (m2_std * m2_std * m2_std)) if m2_std > ZERO else ZERO

    # Kurtosis: (1/N * sum(d^4)) / (1/N * sum(d^2))^2
    sum_fourths = sum((d * d * d * d for d in diffs), ZERO)
    m4 = sum_fourths / n_dec
    kurtosis = (m4 / (m2 * m2)) if m2 > ZERO else THREE

    return (
        mean.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN),
        variance.quantize(SIX_PLACES, rounding=ROUND_HALF_EVEN),
        skewness.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN),
        kurtosis.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN),
    )


def compute_expected_max_null_sharpe(
    trial_sharpe_ratios: Sequence[Decimal],
) -> tuple[Decimal, Decimal]:
    """Compute trial variance and expected maximum Sharpe under null hypothesis.

    Implements Bailey & Lopez de Prado (2014):
    SR* = sqrt(V) * ((1 - gamma) * Phi^{-1}(1 - 1/K) + gamma * Phi^{-1}(1 - 1/(K*e)))

    Returns:
        tuple of (trial_variance, expected_max_null_sharpe).
    """
    k = len(trial_sharpe_ratios)
    if k <= 0:
        raise ValueError("trial_sharpe_ratios must not be empty")

    if k == 1:
        return ZERO, ZERO

    k_dec = Decimal(str(k))
    mean_sr = sum(trial_sharpe_ratios, ZERO) / k_dec
    sum_sq_diffs = sum(
        ((sr - mean_sr) * (sr - mean_sr) for sr in trial_sharpe_ratios), ZERO
    )
    variance = sum_sq_diffs / Decimal(str(k - 1))

    if variance <= ZERO:
        return ZERO, ZERO

    var_float = float(variance)
    std_float = math.sqrt(var_float)

    # Probabilities for quantile evaluation
    p1 = 1.0 - (1.0 / k)
    p2 = 1.0 - (1.0 / (k * math.e))

    # Clamp probabilities within (0, 1) for numerical stability
    p1 = max(1e-15, min(1.0 - 1e-15, p1))
    p2 = max(1e-15, min(1.0 - 1e-15, p2))

    q1 = _NORMAL.inv_cdf(p1)
    q2 = _NORMAL.inv_cdf(p2)

    sr_star_float = std_float * ((1.0 - EULER_MASCHERONI) * q1 + EULER_MASCHERONI * q2)
    sr_star = Decimal(str(round(sr_star_float, 8))).quantize(
        FOUR_PLACES, rounding=ROUND_HALF_EVEN
    )
    variance_rounded = variance.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)

    return variance_rounded, sr_star


def compute_deflated_sharpe_ratio(
    *,
    candidate_sharpe: Decimal,
    expected_max_null_sharpe: Decimal,
    sample_size_sessions: int,
    sample_skewness: Decimal = ZERO,
    sample_kurtosis: Decimal = THREE,
) -> Decimal:
    """Compute Deflated Sharpe Ratio (DSR) probability.

    Implements Bailey & Lopez de Prado (2014):
    sigma_SR = sqrt((1 - gamma_3 * SR + ((gamma_4 - 1) / 4) * SR^2) / (N - 1))
    z = (SR - SR*) / sigma_SR
    DSR = Phi(z)

    Returns:
        Deflated Sharpe ratio probability in [0, 1].
    """
    if sample_size_sessions < 2:
        raise ValueError("sample_size_sessions must be at least 2")

    sr_f = float(candidate_sharpe)
    sr_star_f = float(expected_max_null_sharpe)
    gamma3_f = float(sample_skewness)
    gamma4_f = float(sample_kurtosis)
    n = sample_size_sessions

    # Variance factor: 1 - gamma_3 * SR + ((gamma_4 - 1) / 4) * SR^2
    var_factor = 1.0 - gamma3_f * sr_f + ((gamma4_f - 1.0) / 4.0) * (sr_f**2)
    if var_factor <= 0.0:
        var_factor = 1e-8

    se_sr = math.sqrt(var_factor / (n - 1))
    if se_sr <= 0.0:
        se_sr = 1e-8

    z = (sr_f - sr_star_f) / se_sr
    dsr_float = _NORMAL.cdf(z)
    dsr_clamped = max(0.0, min(1.0, dsr_float))

    return Decimal(str(round(dsr_clamped, 8))).quantize(
        FOUR_PLACES, rounding=ROUND_HALF_EVEN
    )


def bonferroni_adjustment(p_value: Decimal, trial_count: int) -> Decimal:
    """Adjust a single p-value using the Bonferroni family-wise method."""
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")
    if p_value < ZERO or p_value > ONE:
        raise ValueError("p_value must be within [0, 1]")

    adjusted = p_value * Decimal(str(trial_count))
    clamped = max(ZERO, min(ONE, adjusted))
    return clamped.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)


def bonferroni_adjust_all(p_values: Sequence[Decimal]) -> list[Decimal]:
    """Adjust a sequence of p-values using the Bonferroni method."""
    k = len(p_values)
    if k == 0:
        return []
    return [bonferroni_adjustment(p, k) for p in p_values]


def holm_bonferroni_adjust_all(p_values: Sequence[Decimal]) -> list[Decimal]:
    """Adjust a sequence of p-values using the Holm-Bonferroni step-down method.

    Guarantees monotonicity: p_adj_(k) >= p_adj_(k-1).
    """
    k = len(p_values)
    if k == 0:
        return []

    # Sort with indices to restore original ordering
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])

    adjusted_indexed: list[tuple[int, Decimal]] = []
    prev_adj = ZERO

    for rank_0, (orig_idx, p_val) in enumerate(indexed):
        rank = rank_0 + 1
        multiplier = Decimal(str(k - rank + 1))
        raw_adj = p_val * multiplier
        adj = max(prev_adj, raw_adj)
        adj = max(ZERO, min(ONE, adj))
        prev_adj = adj
        adjusted_indexed.append((orig_idx, adj))

    # Restore original ordering
    adjusted_indexed.sort(key=lambda x: x[0])
    return [
        val.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)
        for _, val in adjusted_indexed
    ]


def benjamini_hochberg_adjust_all(p_values: Sequence[Decimal]) -> list[Decimal]:
    """Adjust a sequence of p-values using the Benjamini-Hochberg step-up FDR method.

    Guarantees step-up monotonicity: q_(k) <= q_(k+1).
    """
    k = len(p_values)
    if k == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    k_dec = Decimal(str(k))

    raw_q_values: list[tuple[int, Decimal]] = []
    for rank_0, (orig_idx, p_val) in enumerate(indexed):
        rank = rank_0 + 1
        rank_dec = Decimal(str(rank))
        raw_q = (p_val * k_dec) / rank_dec
        raw_q = max(ZERO, min(ONE, raw_q))
        raw_q_values.append((orig_idx, raw_q))

    # Enforce step-up monotonicity from largest rank down to 1
    adjusted_indexed: list[tuple[int, Decimal]] = [raw_q_values[-1]]
    for i in range(k - 2, -1, -1):
        orig_idx, q_val = raw_q_values[i]
        next_q = adjusted_indexed[-1][1]
        monotone_q = min(q_val, next_q)
        adjusted_indexed.append((orig_idx, monotone_q))

    # Restore original ordering
    adjusted_indexed.sort(key=lambda x: x[0])
    return [
        val.quantize(FOUR_PLACES, rounding=ROUND_HALF_EVEN)
        for _, val in adjusted_indexed
    ]


def compute_p_value_from_sharpe(sharpe: Decimal, sample_size_sessions: int) -> Decimal:
    """Compute asymptotic two-tailed p-value from Sharpe ratio and sample size."""
    if sample_size_sessions < 2:
        return ONE

    z = float(sharpe) * math.sqrt(sample_size_sessions)
    p_float = 2.0 * (1.0 - _NORMAL.cdf(abs(z)))
    p_clamped = max(0.0, min(1.0, p_float))
    return Decimal(str(round(p_clamped, 8))).quantize(
        FOUR_PLACES, rounding=ROUND_HALF_EVEN
    )


def compute_multiple_testing_summary(
    *,
    candidate_sharpe: Decimal,
    trial_sharpe_ratios: Sequence[Decimal],
    sample_size_sessions: int,
    candidate_p_value: Decimal | None = None,
    trial_p_values: Sequence[Decimal] | None = None,
    sample_skewness: Decimal = ZERO,
    sample_kurtosis: Decimal = THREE,
) -> MultipleTestingSummaryV1:
    """Generate MultipleTestingSummaryV1 with DSR, FWER, and FDR adjustments."""
    trial_count = len(trial_sharpe_ratios)
    if trial_count < 1:
        raise ValueError("trial_sharpe_ratios must not be empty")

    variance, sr_star = compute_expected_max_null_sharpe(trial_sharpe_ratios)

    dsr = compute_deflated_sharpe_ratio(
        candidate_sharpe=candidate_sharpe,
        expected_max_null_sharpe=sr_star,
        sample_size_sessions=sample_size_sessions,
        sample_skewness=sample_skewness,
        sample_kurtosis=sample_kurtosis,
    )
    is_dsr_significant = dsr >= Decimal("0.9500")

    # Resolve p-values
    if trial_p_values is not None and len(trial_p_values) == trial_count:
        p_seq = list(trial_p_values)
        if candidate_p_value is not None and candidate_p_value in p_seq:
            cand_idx = p_seq.index(candidate_p_value)
        else:
            # Match by closest Sharpe or default to index 0
            cand_idx = 0
    else:
        # Derive asymptotic p-values from trial Sharpes
        p_seq = [
            compute_p_value_from_sharpe(sr, sample_size_sessions)
            for sr in trial_sharpe_ratios
        ]
        if candidate_p_value is not None:
            cand_idx = 0
            p_seq[0] = candidate_p_value
        else:
            # Find candidate index in trial_sharpe_ratios
            cand_idx = (
                trial_sharpe_ratios.index(candidate_sharpe)
                if candidate_sharpe in trial_sharpe_ratios
                else 0
            )

    bonf_values = bonferroni_adjust_all(p_seq)
    holm_values = holm_bonferroni_adjust_all(p_seq)
    bh_values = benjamini_hochberg_adjust_all(p_seq)

    bonf_p = bonf_values[cand_idx]
    holm_p = holm_values[cand_idx]
    bh_q = bh_values[cand_idx]

    return MultipleTestingSummaryV1(
        trial_count=trial_count,
        sharpe_trial_variance=variance,
        expected_max_null_sharpe=sr_star,
        deflated_sharpe_ratio=dsr,
        is_dsr_significant_at_95=is_dsr_significant,
        bonferroni_adjusted_p_value=bonf_p,
        holm_adjusted_p_value=holm_p,
        benjamini_hochberg_fdr_q=bh_q,
    )
