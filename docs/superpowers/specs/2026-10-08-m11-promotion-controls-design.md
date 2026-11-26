# Milestone M11: Promotion and Overfitting Controls Design Specification

**Status:** APPROVED
**Milestone:** M11 (Promotion and Overfitting Controls)
**Owner:** Krish (`workstream:krish`)
**Parent Issue:** #18
**Date:** 2026-10-08

---

## 1. Executive Summary & Problem Statement

Milestone M11 establishes the final statistical gatekeeping firewall protecting Drift from backtest overfitting, selection bias, and false discovery before candidate trading strategies can be promoted to Shadow Broker validation (M12-M15) or live trading (M16+).

In quantitative research campaigns where autonomous agents explore tens or hundreds of parameter variations (M6-M8) and compete in tournaments (M10), standard backtest metrics (e.g. historical Sharpe ratio) become severely inflated due to multiple testing. Even when true alpha is strictly zero, selecting the maximum Sharpe ratio from $K$ independent trials guarantees an observed Sharpe well above zero.

Milestone M11 formalizes a deterministic multi-stage statistical promotion pipeline:
1. **Deflated Sharpe Ratio (DSR)**: Adjusts the observed Sharpe ratio for the number of trials $K$, the variance of trial Sharpes, return skewness, and kurtosis (Bailey & Lopez de Prado 2014);
2. **Probability of Backtest Overfitting (PBO)**: Quantifies the probability that the in-sample optimal strategy underperforms the median strategy out-of-sample across partition combinations;
3. **Walk-Forward Consistency**: Requires temporal stability and positive out-of-sample performance across contiguous walk-forward folds;
4. **Regime Shift Stress Testing**: Verifies that the strategy maintains strict drawdown and risk limits across diverse volatility regimes;
5. **Exploratory versus Promotion Boundary**: Enforces fail-closed isolation preventing exploratory lane evidence from passing promotion-grade authorization gates.

---

## 2. Core Invariants & Boundaries

1. **Authorization Gate Separation**: M11 is an authorization firewall. Implementing M11 code or executing M11 against exploratory data does not grant promotion authority.
2. **Deterministic Standard Library Math**: All calculations (DSR, PBO, walk-forward folds, regime attribution) use standard library math (`decimal.Decimal`, `math`, `statistics.NormalDist`). Zero third-party runtime dependencies (`numpy`, `scipy`).
3. **Strict Non-Promotable Exploratory Boundary**: Exploratory evidence cannot authorize capital. A complete passing run against non-qualified data is stamped with `EXPLORATORY_PASSED` and cannot be upgraded into `PROMOTION_QUALIFIED`. Incomplete requests are rejected as described in section 5.1.
4. **Complete PnL Integrity**: Incomplete realized PnL evidence (Issue #152) fails the gate immediately (`REJECTED_INCOMPLETE_EVIDENCE`).
5. **Zero Unicode Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden across all files, docstrings, commit messages, and markdown docs. ASCII hyphen (-) is used exclusively.
6. **Immutable Ledger Sealing**: Every gate evaluation and promotion certificate is sealed into the SQLite ledger with SHA-256 content hashes and deduplication keys.

---

## 3. Four Gatekeeping Pillars

### 3.1. Pillar 1: Deflated Sharpe Ratio (DSR)

For an observed annualized Sharpe ratio $\widehat{SR}$ derived over sample length $N$, with return skewness $\hat{\gamma}_3$ and kurtosis $\hat{\gamma}_4$, across a campaign of $K$ explored trials having variance of trial Sharpes $V[\{\widehat{SR}_k\}]$:

1. The expected maximum Sharpe under the null hypothesis of zero true skill is:
   $$\mathbb{E}[\max_{k} \widehat{SR}_k] \approx \sqrt{V[\{\widehat{SR}_k\}]} \cdot \left((1 - \gamma) Z^{-1}\left(1 - \frac{1}{K}\right) + \gamma Z^{-1}\left(1 - \frac{1}{K e}\right)\right)$$
   where $\gamma \approx 0.5772156649$ is the Euler-Mascheroni constant, and $Z^{-1}$ is the inverse standard normal CDF.
2. The standard error of the Sharpe ratio accounting for non-normality is:
   $$\sigma_{\widehat{SR}} = \sqrt{\frac{1 - \hat{\gamma}_3 \widehat{SR} + \frac{\hat{\gamma}_4 - 1}{4} \widehat{SR}^2}{N - 1}}$$
3. The Deflated Sharpe Ratio is:
   $$\text{DSR} = Z\left(\frac{\widehat{SR} - \mathbb{E}[\max_k \widehat{SR}_k]}{\sigma_{\widehat{SR}}}\right)$$
4. Gate Criterion: $\text{DSR} \ge \text{min\_dsr}$ (default 0.95, representing $p \le 0.05$).

### 3.2. Pillar 2: Probability of Backtest Overfitting (PBO)

Using combinatorially partitioned cross-validation folds:
1. Divide historical evaluation sessions into $M$ disjoint contiguous blocks.
2. For combinations of train/test fold splits, measure whether the parameter set that ranked #1 in-sample degraded below the median out-of-sample rank.
3. Compute the relative rank distribution and calculate the proportion of logits exhibiting out-of-sample degradation.
4. Gate Criterion: $\text{PBO} \le \text{max\_pbo}$ (default 0.30).

### 3.3. Pillar 3: Walk-Forward Consistency

1. Partition evaluation into $F$ contiguous walk-forward out-of-sample windows (default 5 folds).
2. Measure out-of-sample Sharpe ratio $SR_f$ and cumulative return for each fold $f \in \{1, \dots, F\}$.
3. Gate Criterion: Positive Sharpe ratio in at least $80\%$ of folds ($\frac{1}{F} \sum \mathbb{I}(SR_f > 0) \ge 0.80$) and non-negative cumulative return across all folds.

### 3.4. Pillar 4: Regime Shift Stress Testing

1. Segment historical evaluation sessions into distinct volatility regimes: Low Volatility (bottom 33%), Normal Volatility (middle 33%), High Volatility (top 33%).
2. Measure maximum drawdown and Sharpe ratio within each regime slice.
3. Gate Criterion: Maximum drawdown in any single volatility regime must not exceed $25\%$ ($\text{MaxDD}_{\text{regime}} \le 0.25$).

---

## 4. Domain Models & Ledger Schemas

Defined in `src/drift/domain/promotion.py`:

```python
class PromotionGateVerdict(StrEnum):
    PROMOTION_QUALIFIED = "promotion_qualified"
    EXPLORATORY_PASSED = "exploratory_passed"
    REJECTED_DEFLATED_SHARPE = "rejected_deflated_sharpe"
    REJECTED_PBO_OVERFITTING = "rejected_pbo_overfitting"
    REJECTED_WALK_FORWARD_DEGRADATION = "rejected_walk_forward_degradation"
    REJECTED_REGIME_INSTABILITY = "rejected_regime_instability"
    REJECTED_INCOMPLETE_EVIDENCE = "rejected_incomplete_evidence"


class PromotionGateConfigV1(FrozenModel):
    config_id: UUID7
    min_dsr: Decimal = Decimal("0.95")
    max_pbo: Decimal = Decimal("0.30")
    min_positive_folds_fraction: Decimal = Decimal("0.80")
    max_regime_drawdown: Decimal = Decimal("0.25")
    is_promotion_grade_authorized: bool = False
    created_at: UTCDateTime
    config_hash: SHA256Hash


class PromotionEvaluationRecordV1(FrozenModel):
    evaluation_id: UUID7
    candidate_id: UUID7
    strategy_type: NonBlankStr
    parameters_hash: SHA256Hash
    deflated_sharpe_ratio: Decimal
    pbo_estimate: Decimal
    positive_folds_fraction: Decimal
    max_regime_drawdown: Decimal
    trials_explored_k: int
    verdict: PromotionGateVerdict
    rejection_reasons: tuple[str, ...] = ()
    evaluated_at: UTCDateTime
    record_hash: SHA256Hash
```

---

## 5. Ledger Audit Event Payloads

The following historical V1 event definitions are amended for the bounded cases
in section 5.1; existing records and historical event bytes are not rewritten.

1. `m11.gate.evaluated`: Sealed at the end of each promotion gate evaluation containing `PromotionEvaluationRecordV1`.
2. `m11.candidate.certified`: Sealed when a candidate satisfies all four pillars and receives `PROMOTION_QUALIFIED` or `EXPLORATORY_PASSED`.
3. `m11.candidate.rejected`: Sealed when a candidate breaches any of the four statistical gate pillars.

### 5.1 Owner-directed containment amendment (#360)

The historical V1 event and record formats remain unchanged. For an incomplete
attempt, a single schema version `2` event `m11.gate.incomplete_rejected`
replaces the V1 evaluated-plus-rejected pair. It records the attempt and
candidate identities, parameters hash, a request consistency hash, the actual
attempt timestamp, `REJECTED_INCOMPLETE_EVIDENCE`, and ordered reasons. It does
not fabricate V1 statistics. The event must be sealed and read back before the
result is returned; missing or failed recording refuses. Retries use the same
attempt identity, timestamp and payload, and a conflicting reuse refuses.

The explicit PnL completeness assertion and usable matrix, folds and session
returns are required. The DSR sample size, skewness and kurtosis must be
explicit rather than supplied by assumed defaults. Mathematical inputs must be
finite and usable; the matrix must contain exactly K trial rows and, for multiple
trials, the Sharpe cohort must contain exactly K entries. The PBO calculation
requires at least two rows. These cardinality checks do not authenticate trial
identities or prove provenance. They are mechanical prerequisites, not a
scientific sufficiency ruling or a new statistical threshold.

For a complete exploratory pass, the existing V1 evaluated event is sealed but
no certification event is created. Caller flags and caller-created records do
not authorize any new certification or promotion. Statistical rejections retain
their historical evaluated and rejected events. Old certification events are
historical facts only, not present authority. Neither a request hash nor a
ledger hash authenticates the origin of its inputs.

New complete evaluations bind their event ID to a canonical, type-preserving
snapshot of the full request and configuration. The existing evaluation-ID
deduplication key and V1 payload remain unchanged. Exact retries read back the
same event; changed requests and pre-existing V1 events without this binding
conflict rather than being assumed identical. Historical events are not rewritten.
The binding establishes consistency, not source origin or authorization.
The public recorder refuses caller-created V1 evaluations; the gatekeeper must
compute them. A rejection must match a sealed evaluation. This does not protect
against an actor with unrestricted generic ledger access.

On an uncertain append or readback, `PromotionAuditUncertain` carries the
evaluation ID and timestamp for retrying the original input, without claiming
whether the event committed. Incomplete-request fingerprints distinguish NaN
bit patterns; retries of older NaN fingerprints may conflict and must not be
assumed equivalent.

`PromotionArchive.list_evaluations()` and `list_rejections()` remain V1 views:
they omit V2 incomplete attempts. Consumers must use `get_attempt()` or
`list_incomplete_rejections()` to see those attempts. The old V1 batch method
refuses because its certified bucket cannot faithfully represent exploratory
results. V2 batches separate exploratory and rejected outcomes. They are not
atomic: an interruption reports completed attempts, the failed attempt,
known sealed events for it (or unknown if readback failed), and the unprocessed
suffix. A retry must use the original immutable request identity and timestamp.

Issue #360 and M2 promotion re-enablement #115 remain open. This amendment
neither authenticates source provenance nor authorizes promotion or operation.

---

## 6. Implementation Slice Plan

1. **M11-1: Domain Models, Schemas, and Audit Payloads**:
   - `src/drift/domain/promotion.py`: `PromotionGateVerdict`, `PromotionGateConfigV1`, `PromotionEvaluationRecordV1`, hash helpers, audit payloads.
   - Unit tests in `tests/unit/test_promotion_domain.py`.

2. **M11-2: Statistical Gatekeeping Engine**:
   - `src/drift/promotion/gatekeeper.py`: `PromotionGatekeeper`. Computes DSR with trial count K, estimates PBO, partitions walk-forward folds, computes regime stress tests.
   - Unit tests in `tests/unit/test_promotion_gatekeeper.py`.

3. **M11-3: Candidate Promotion Runner**:
   - `src/drift/promotion/runner.py`: `PromotionRunner`. Orchestrates candidate evaluation, extracts session metrics, runs gatekeeper, formulates certificate/verdict.
   - Unit tests in `tests/unit/test_promotion_runner.py`.

4. **M11-4: M0 Ledger Sealing and Promotion Registry Archive**:
   - `src/drift/promotion/recorder.py`: `PromotionRecorder`.
   - `src/drift/promotion/archive.py`: `PromotionArchive`. Queries certified candidates, promotion history, rejection reasons.
   - Unit tests in `tests/unit/test_promotion_audit.py`.

5. **M11-5: Adversarial Acceptance Suite and Stress Testing**:
   - `tests/adversarial/test_m11_promotion_adversarial.py`:
     - Overfit trial selection rejection (DSR below threshold under large K);
     - High PBO detection across cross-validation splits;
     - Walk-forward out-of-sample degradation failure;
     - Extreme regime shock drawdown breach;
     - Exploratory evidence anti-laundering gatekeeping;
     - Cryptographic certificate tamper detection.

---

## 7. Verification Commands

```bash
uv run pytest tests/unit/test_promotion*.py tests/adversarial/test_m11_promotion_adversarial.py
uv run ruff check src/drift/promotion tests/unit/test_promotion*.py tests/adversarial/test_m11_promotion_adversarial.py
uv run ruff format --check src/drift/promotion tests/unit/test_promotion*.py tests/adversarial/test_m11_promotion_adversarial.py
uv run mypy src/drift/domain/promotion.py src/drift/promotion
```
