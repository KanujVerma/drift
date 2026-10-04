# Drift M5: Statistical and Model Scorecards Architecture Design Specification

Date: 2026-10-04.
Status: Canonical architecture design specification for Drift M5 (incorporating external architectural rulings and dependency mappings).
Canonical Baseline: Commit `bac3cd0` (Milestones M0 through M4 complete and verified).
Related Architecture Decisions: [ADR 0001](../../adr/0001-evidence-first-architecture.md), [ADR 0003](../../adr/0003-append-only-research-ledger.md), [ADR 0004](../../adr/0004-research-production-separation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), [ADR 0014](../../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).
Related Issues: Parent Issue #12, Follow-up Issue #152 (Realized PnL Completeness).

---

## 1. Objective and Scientific Mission

Milestone M5 constructs the deterministic statistical and model scorecard kernel that bridges empirical prediction tracking (M4) and deterministic session accounting (M2/M3) to rigorous quantitative research evaluation.

In quantitative financial research, raw backtests and backfilled simulations are notoriously vulnerable to false discoveries:
- **Selection Bias / P-Hacking:** Evaluating hundreds of parameter variations and selectively reporting the single configuration that yielded high backtest Sharpe ratios;
- **Calibration Neglect:** Focusing exclusively on directional sign hit rate while ignoring severe probability miscalibration or tail risks;
- **Survivorship & Missingness Obfuscation:** Excluding delisted names, missing sessions, or indeterminate cost bases to artificially suppress drawdown and enhance returns;
- **Turnover Blindness:** Generating theoretically profitable signals whose alpha is completely destroyed by transaction costs, slippage, and portfolio churn;
- **Unadjusted Significance:** Treating standard t-statistics as valid when hundreds of dependent hypotheses were evaluated over the same market sample.

M5 provides an immutable, tamper-evident statistical scorecard engine that:
1. **Measures Predictive Alpha:** Evaluates cross-sectional rank correlation (Spearman IC), linear correlation (Pearson IC), Information Ratio of IC, and quantile monotonicity across sealed ex-ante prediction sets (M4);
2. **Evaluates Probabilistic Calibration:** Quantifies Brier scores, Expected Calibration Error (ECE), Maximum Calibration Error (MCE), and empirical reliability diagrams for probabilistic and directional forecasts;
3. **Quantifies Realized Performance & Risk:** Computes annualized returns, downside semi-deviation, Sortino/Calmar/Sharpe ratios, drawdown curves, maximum drawdown duration, turnover drag, and enforces strict realized PnL completeness verification (`RealizedPnLCompletenessV1`);
4. **Applies Multiple-Testing Adjustments:** Implements Deflated Sharpe Ratio (DSR) (Bailey & Lopez de Prado 2014), Family-Wise Error Rate (Bonferroni, Holm), and False Discovery Rate (Benjamini-Hochberg, Benjamini-Yekutieli) corrections across historical research trials;
5. **Seals Scorecards to the M0 Ledger:** Emits immutable, bitwise-reproducible `m5.scorecard.recorded` audit events bound to exact experiment and code version provenance.

---

## 2. Scope and Domain Boundaries

### 2.1 Admitted Scope (V1)
- **Inputs Consumed:**
  - `ExAntePredictionSetV1` and `ExAntePredictionRecordV1` (M4 domain models);
  - `RealizedOutcomeBatchV1` and `RealizedOutcomeRecordV1` (M4 domain models);
  - `EvaluationResultV1`, `EvaluationSummaryMetricsV1`, and `PortfolioStateV2` (M2/M3 evaluator domain models);
  - `RealizedPnLCompletenessV1` (Issue #152 explicit PnL completeness signal);
  - Reference baseline evaluations (B0 cash, B1 buy-and-hold, B2 equal-weight, B4 momentum, B5 low volatility).
- **Metric Modules:**
  - `InformationCoefficientSummaryV1`: Cross-sectional Spearman rank IC, Pearson IC, time-series mean, standard deviation, Information Ratio, t-statistic, positive hit rate, and quantile monotonicity spread;
  - `CalibrationSummaryV1`: Brier score, ECE, MCE, reliability curve coordinate bins, calibration slope and intercept, MAE, and RMSE;
  - `RiskAttributionSummaryV1`: Cumulative return, annualized geometric return, annualized arithmetic return, annualized volatility, downside semi-variance, Sharpe ratio, Sortino ratio, and Calmar ratio;
  - `DrawdownProfileV1`: High-water mark series, maximum drawdown (MDD), peak-to-trough duration, recovery duration, and underwater series;
  - `TurnoverSummaryV1`: Per-session one-way turnover, annualized turnover, and fee/cost drag;
  - `MultipleTestingSummaryV1`: Number of evaluated trials $K$, cross-trial Sharpe variance, Deflated Sharpe Ratio (DSR) p-value, Bonferroni adjusted p-values, Holm-Bonferroni adjusted p-values, and Benjamini-Hochberg (BH) false discovery rates.
- **Output Artifacts:**
  - `PredictionScorecardV1`: Focuses on forecast quality, IC, and calibration;
  - `StrategyScorecardV1`: Focuses on session portfolio accounting, risk-adjusted return, drawdowns, turnover, and PnL completeness;
  - `ModelScorecardV1`: Composite container combining prediction metrics, strategy accounting, and multiple-testing adjustments;
  - `m5.scorecard.recorded` audit event committed to the M0 SQLite research ledger.

### 2.2 Excluded Scope (V1 Hard Boundaries)
- **No In-Sample Overfitting:** M5 evaluates sealed out-of-sample prediction sets and evaluator traces; it does not train or fit ML model parameters.
- **No Execution or Broker Integration:** M5 does not trade, place orders, or connect to brokerage accounts.
- **No Promotion Relabeling:** Scorecards computed over exploratory data (`lane="exploratory"`) are strictly non-promotable (ADR 0012).
- **No Post-Hoc Trial Filtering:** Multiple-testing deflations must account for all executed trials in a declared experiment suite; cherry-picking sub-trials is strictly forbidden.

---

## 3. Two-Lane Architecture and Promotion Boundary

Per ADR 0012:
- **Exploratory Lane:** Scorecards generated from exploratory evaluations or simulated runs carry `lane="exploratory"` and are strictly non-promotable.
- **Promotion Lane:** Currently disabled fail-closed. When enabled via M1e Task 8, promotion-grade scorecards require authenticated, license-qualified source evaluation evidence.
- **Zero Evidence Laundering:** An exploratory scorecard can never be relabeled or admitted into promotion qualification.

---

## 4. Mathematical and Algorithmic Specifications

### 4.1 Information Coefficient (IC) & Monotonicity
For cross-sectional prediction set $P_t = \{(\hat{y}_{i,t}, y_{i,t})\}_{i=1}^{M_t}$ at session $t$:
1. **Spearman Rank Correlation:**
   $$IC_{rank, t} = 1 - \frac{6 \sum_{i=1}^{M_t} d_i^2}{M_t(M_t^2 - 1)}$$
   where $d_i = \text{rank}(\hat{y}_{i,t}) - \text{rank}(y_{i,t})$.
2. **Pearson Linear Correlation:**
   $$IC_{linear, t} = \frac{\sum_{i=1}^{M_t} (\hat{y}_{i,t} - \bar{\hat{y}}_t)(y_{i,t} - \bar{y}_t)}{\sqrt{\sum (\hat{y}_{i,t} - \bar{\hat{y}}_t)^2 \sum (y_{i,t} - \bar{y}_t)^2}}$$
3. **Time-Series Aggregation Across $T$ Sessions:**
   $$\overline{IC} = \frac{1}{T}\sum_{t=1}^T IC_t, \quad \sigma_{IC} = \sqrt{\frac{1}{T-1}\sum_{t=1}^T (IC_t - \overline{IC})^2}$$
   $$IR_{IC} = \frac{\overline{IC}}{\sigma_{IC}} \times \sqrt{252}, \quad t_{IC} = \frac{\overline{IC}}{\sigma_{IC} / \sqrt{T}}$$
4. **Quantile Spread & Monotonicity:**
   Partition $M_t$ into $Q$ rank quantiles (e.g. quintiles $Q=5$). Measure the mean realized return $\bar{r}_{q}$ for each quantile $q \in \{1, \dots, Q\}$. Monotonicity requires:
   $$\bar{r}_1 \le \bar{r}_2 \le \dots \le \bar{r}_Q$$
   Quantile spread is defined as $\text{Spread}_{Q-1} = \bar{r}_Q - \bar{r}_1$.

### 4.2 Probabilistic & Directional Calibration
For directional binary hit $y_i \in \{0, 1\}$ and predicted probability $p_i \in [0, 1]$:
1. **Brier Score:**
   $$BS = \frac{1}{N}\sum_{i=1}^N (p_i - y_i)^2$$
2. **Expected Calibration Error (ECE) & Maximum Calibration Error (MCE):**
   Group predictions into $B$ equal-width bins $I_b = (\frac{b-1}{B}, \frac{b}{B}]$.
   $$\text{acc}(B_b) = \frac{1}{|B_b|}\sum_{i \in B_b} y_i, \quad \text{conf}(B_b) = \frac{1}{|B_b|}\sum_{i \in B_b} p_i$$
   $$ECE = \sum_{b=1}^B \frac{|B_b|}{N} |\text{acc}(B_b) - \text{conf}(B_b)|$$
   $$MCE = \max_{b \in \{1, \dots, B\}} |\text{acc}(B_b) - \text{conf}(B_b)|$$
3. **Continuous Accuracy Metrics:**
   $$MAE = \frac{1}{N}\sum_{i=1}^N |\hat{y}_i - y_i|, \quad RMSE = \sqrt{\frac{1}{N}\sum_{i=1}^N (\hat{y}_i - y_i)^2}$$

### 4.3 Risk-Adjusted Attribution, Drawdown & PnL Completeness
1. **Return & Risk:**
   - Annualized Geometric Return: $R_{geom} = \left(\prod_{t=1}^T (1 + r_t)\right)^{252 / T} - 1$;
   - Annualized Volatility: $\sigma_{ann} = \text{std}(r_t) \times \sqrt{252}$;
   - Downside Semi-Deviation: $\sigma_{down} = \sqrt{\frac{1}{T}\sum_{t=1}^T (\min(r_t, 0))^2} \times \sqrt{252}$;
   - Annualized Sharpe Ratio: $SR = \frac{\overline{r} \times 252}{\sigma_{ann}}$;
   - Sortino Ratio: $\text{Sortino} = \frac{\overline{r} \times 252}{\sigma_{down}}$.
2. **Drawdown Profile:**
   Given cumulative equity curve $E_t$:
   - High-Water Mark: $HWM_t = \max_{s \le t} E_s$;
   - Underwater Drawdown: $DD_t = \frac{E_t - HWM_t}{HWM_t}$;
   - Maximum Drawdown: $MDD = \min_{t} DD_t$;
   - Peak-to-Trough Duration: Sessions between $HWM$ peak and the trough;
   - Recovery Duration: Sessions between trough and new $HWM$.
3. **Turnover Metrics:**
   - One-Way Session Turnover: $\tau_t = \frac{1}{2} \sum_{i} |w_{i,t} - w_{i, t-1}|$;
   - Annualized Turnover: $\tau_{ann} = \frac{1}{T}\sum_{t=1}^T \tau_t \times 252$.
4. **Realized PnL Completeness Guard:**
   - Consumes `RealizedPnLCompletenessV1` from M2/M3 results.
   - If `is_complete == False`, the scorecard sets `pnl_complete = False`, lists excluded disposals, and flags PnL-dependent metrics as partial.

### 4.4 Multiple-Testing Adjustments & Overfitting Controls
When testing $K$ hypothesis variants / parameter sweeps:
1. **Deflated Sharpe Ratio (DSR) (Bailey & Lopez de Prado 2014):**
   Given an observed Sharpe ratio $\widehat{SR}$ across $N$ sample sessions, sample skewness $\hat{\gamma}_3$, sample kurtosis $\hat{\gamma}_4$, and variance of Sharpe ratios across $K$ trials $V[\{SR_k\}]$:
   Expected maximum Sharpe under null hypothesis of no skill:
   $$SR^* = \sqrt{V} \left( (1 - \gamma)\Phi^{-1}\left(1 - \frac{1}{K}\right) + \gamma\Phi^{-1}\left(1 - \frac{1}{K e}\right) \right)$$
   where $\gamma \approx 0.5772156649$ is the Euler-Mascheroni constant, and $\Phi$ is the standard normal CDF.
   Deflated Sharpe Ratio:
   $$DSR = \Phi\left( \frac{(\widehat{SR} - SR^*) \sqrt{N - 1}}{\sqrt{1 - \hat{\gamma}_3 \widehat{SR} + \frac{\hat{\gamma}_4 - 1}{4} \widehat{SR}^2}} \right)$$
   A candidate strategy is rejected unless $DSR \ge 0.95$ (statistically significant at $5\%$ level adjusted for selection bias).
2. **Family-Wise Error Rate (FWER) Controls:**
   - Bonferroni: Adjusted p-value $p^{Bonf}_k = \min(1.0, K \cdot p_k)$;
   - Holm-Bonferroni: Sort $p_{(1)} \le \dots \le p_{(K)}$. Adjusted p-value $p^{Holm}_{(k)} = \min(1.0, (K - k + 1) \cdot p_{(k)})$.
3. **False Discovery Rate (FDR) Controls:**
   - Benjamini-Hochberg (BH): Sort $p_{(1)} \le \dots \le p_{(K)}$. Find largest $k$ such that $p_{(k)} \le \frac{k}{K} q^*$. All hypotheses with $i \le k$ are declared significant at FDR level $q^*$.

---

## 5. Domain Models and Schemas

```python
class ScorecardType(StrEnum):
    """Classification of scorecard artifact."""

    PREDICTION = "prediction"
    STRATEGY = "strategy"
    COMPOSITE = "composite"


class MetricSummaryV1(FrozenModel):
    """Scalar metric with statistical bounds."""

    metric_name: NonBlankStr
    value: Decimal
    standard_error: Decimal | None = None
    t_statistic: Decimal | None = None
    p_value: Decimal | None = None
    sample_size: int


class InformationCoefficientSummaryV1(FrozenModel):
    """Rank and linear correlation summary across decision epochs."""

    mean_spearman_ic: Decimal
    std_spearman_ic: Decimal
    information_ratio_ic: Decimal
    t_statistic_ic: Decimal
    positive_ic_ratio: Decimal
    mean_pearson_ic: Decimal
    evaluated_sessions: int
    quantile_spread_return: Decimal | None = None
    is_rank_monotonic: bool | None = None


class CalibrationBinV1(FrozenModel):
    """Empirical calibration bin for reliability diagrams."""

    bin_index: int
    bin_lower: Decimal
    bin_upper: Decimal
    predicted_confidence: Decimal
    empirical_accuracy: Decimal
    sample_count: int


class CalibrationSummaryV1(FrozenModel):
    """Probabilistic and directional calibration summary."""

    brier_score: Decimal | None = None
    expected_calibration_error: Decimal | None = None
    maximum_calibration_error: Decimal | None = None
    calibration_slope: Decimal | None = None
    calibration_intercept: Decimal | None = None
    mean_absolute_error: Decimal | None = None
    root_mean_squared_error: Decimal | None = None
    bins: tuple[CalibrationBinV1, ...] = ()


class DrawdownProfileV1(FrozenModel):
    """Drawdown and underwater trajectory profile."""

    maximum_drawdown: Decimal
    max_drawdown_duration_sessions: int
    peak_to_trough_sessions: int
    recovery_sessions: int
    current_drawdown: Decimal
    is_recovered: bool


class TurnoverSummaryV1(FrozenModel):
    """Portfolio turnover and cost impact metrics."""

    mean_session_turnover: Decimal
    annualized_turnover: Decimal
    estimated_cost_drag: Decimal


class MultipleTestingSummaryV1(FrozenModel):
    """Multiple-testing and selection-bias adjustments."""

    trial_count: int
    sharpe_trial_variance: Decimal
    expected_max_null_sharpe: Decimal
    deflated_sharpe_ratio: Decimal
    is_dsr_significant_at_95: bool
    bonferroni_adjusted_p_value: Decimal
    holm_adjusted_p_value: Decimal
    benjamini_hochberg_fdr_q: Decimal


class PredictionScorecardV1(FrozenModel):
    """Ex-ante prediction quality and calibration scorecard."""

    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    prediction_target: PredictionTargetType
    ic_summary: InformationCoefficientSummaryV1
    calibration_summary: CalibrationSummaryV1
    total_predictions: int
    resolved_predictions: int
    indeterminate_predictions: int
    delisted_predictions: int
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash


class StrategyScorecardV1(FrozenModel):
    """Session portfolio accounting, risk, and drawdown scorecard."""

    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    cumulative_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal
    downside_deviation: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    drawdown_profile: DrawdownProfileV1
    turnover_summary: TurnoverSummaryV1
    pnl_completeness: RealizedPnLCompletenessV1
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash


class ModelScorecardV1(FrozenModel):
    """Composite quantitative scorecard combining prediction, strategy, and testing."""

    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    prediction_scorecard: PredictionScorecardV1 | None = None
    strategy_scorecard: StrategyScorecardV1 | None = None
    multiple_testing: MultipleTestingSummaryV1 | None = None
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash
```

---

## 6. M0 Research Ledger Event Integration

Scorecards are sealed into the append-only SQLite research ledger:
- **Event Kind:** `m5.scorecard.recorded`
- **Envelope:** `AuditEventDraft` with payload containing canonical JSON serialization of `ModelScorecardV1`, `PredictionScorecardV1`, or `StrategyScorecardV1`.
- **Integrity Validation:** SHA-256 content hashing guarantees bitwise immutability.

---

## 7. Child Implementation Slices Plan

1. **M5-P0 (Issue #187):** Architecture preparation and design specification (this document).
2. **M5-1:** Domain models, metric summaries, and ledger event schemas (`src/drift/domain/scorecards.py`, `m5.scorecard.recorded`).
3. **M5-2:** Predictive power and calibration metrics engine (`src/drift/scorecards/predictive.py`: Spearman/Pearson IC, IR, t-statistic, Brier score, ECE/MCE reliability curves).
4. **M5-3:** Performance attribution, risk profiles, drawdown engine, and PnL completeness verification (`src/drift/scorecards/performance.py`: Sharpe, Sortino, Calmar, MDD, turnover, PnL completeness validation).
5. **M5-4:** Multiple-testing adjustment engine (`src/drift/scorecards/multiple_testing.py`: Deflated Sharpe Ratio, Bonferroni, Holm, Benjamini-Hochberg).
6. **M5-5:** Composite scorecard generator harness and M2/M4 pipeline integration (`src/drift/scorecards/generator.py`).
7. **M5-6:** Adversarial acceptance suite (`tests/adversarial/test_m5_scorecards_adversarial.py`: determinism, missing data immunity, PnL incompleteness handling, multiple-testing monotonicity).
8. **M5-7:** Milestone M5 completion, documentation reconciliation, and ledger audit.

---

## 8. Invariants and Architectural Guarantees

1. **Zero Lookahead:** All metric calculations respect evaluation horizons and point-in-time boundaries.
2. **Fail-Closed Completeness:** Indeterminate or missing outcomes/disposals are never omitted; partial PnL explicitly sets completeness flags.
3. **Bitwise Determinism:** Scorecard calculations are pure deterministic functions of inputs, with invariant content hashes.
4. **Strictly Non-Promotable:** Scorecards carrying `lane="exploratory"` are non-promotable.
5. **Zero Em Dashes:** Strict compliance with ASCII hyphen (-) only across all code, docstrings, and commits.
