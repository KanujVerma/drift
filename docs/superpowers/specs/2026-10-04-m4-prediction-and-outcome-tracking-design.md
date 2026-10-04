# Drift M4: Ex-Ante Prediction and Outcome Tracking Architecture Design Specification

Date: 2026-10-04.
Status: Canonical architecture design specification for Drift M4 (incorporating external architectural rulings and dependency mappings).
Canonical Baseline: Commit `0fc6e1f` (Milestones M0 through M3 complete and verified).
Related Architecture Decisions: [ADR 0001](../../adr/0001-evidence-first-architecture.md), [ADR 0003](../../adr/0003-append-only-research-ledger.md), [ADR 0004](../../adr/0004-research-production-separation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), [ADR 0014](../../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).

---

## 1. Objective and Scientific Mission

M4 constructs the deterministic ex-ante prediction and outcome tracking kernel that bridges hypothesis generation (M0/M7) and statistical evaluation (M5).

The fundamental failure mode of quantitative empirical finance is narrative rationalization:
- **Lookahead Leakage:** Evaluating forecasts computed with knowledge of future events;
- **Retroactive Cherry-Picking:** Post-hoc selection of favorable horizons, assets, or models after observing price trajectories;
- **Survivorship Censoring:** Silently dropping liquidated or delisted positions whose adverse outcomes would damage model scorecards;
- **Outcome Tampering:** Evaluating unadjusted price steps across stock splits or mergers rather than true corporate-action-consistent economic returns.

M4 enforces an immutable temporal firewall:
1. **Ex-Ante Sealing:** Every quantitative prediction is sealed into the append-only research ledger (M0) *strictly before* the realization window opens.
2. **Deterministic Outcome Attribution:** When the forward horizon elapses, realized market facts are resolved through corporate-action-consistent analytical return series (`drift.domain.analytical_returns`), yielding bitwise-reproducible attribution and residuals.
3. **Fail-Closed Completeness:** Every admitted asset prediction must resolve to an explicit terminal status (`RESOLVED`, `INDETERMINATE`, `DELISTED_WITH_OUTCOME`, `DELISTED_WITHOUT_OUTCOME`, or `EXCLUDED_UNAVAILABLE`). Unresolved predictions cannot simply vanish from historical record.

M4 records and links predictions and outcomes. It does not compute aggregate performance statistics (Sharpe, information coefficient, calibration plots), which belong exclusively to M5.

---

## 2. Scope and Domain Boundaries

### 2.1 Admitted Scope (V1)
- **Entities:** US cash equities admitted via M1b (`SecurityID`, `ListingID`).
- **Timing Epochs:** Regular daily trading sessions (`SessionScope.REGULAR`).
- **Prediction Cadence:** Session-by-session decision timestamps (matching M2 post-close decision epoch or pre-open schedule).
- **Target Horizons:** Discrete trading session intervals $H = [s_{t+1}, s_{t+k}]$ (e.g. 1-session, 5-session, 21-session forward horizon).
- **Target Quantities:**
  - `FORWARD_RETURN`: Forward cumulative analytical return over horizon $H$;
  - `DIRECTIONAL_RETURN`: Categorical sign ($\text{UP} / \text{DOWN} / \text{FLAT}$) with confidence score;
  - `REALIZED_VOLATILITY`: Sample variance or standard deviation of daily analytical returns across horizon $H$;
  - `CROSS_SECTIONAL_RANK`: Normalized percentile rank $[0.0, 1.0]$ across an admitted universe at epoch $t$.
- **Ground Truth Grounding:** Analytical return series computed from M1d observations and M1c occurred corporate actions (`CorporateActionConsistentReturnSeries`).
- **Ledger Storage:** Transactional, append-only SQLite ledger events with SHA-256 hash chaining.

### 2.2 Excluded Scope (V1 Hard Boundaries)
- **No Intraday Prediction:** No tick-level, minute-bar, or sub-session outcome tracking.
- **No Derivative Payoffs:** No options, futures, or synthetic structured derivatives.
- **No Multiple-Testing Attribution:** False discovery rate (FDR), Family-Wise Error Rate (FWER), and Deflated Sharpe adjustments belong to M5/M11.
- **No Dynamic Horizon Modification:** Target horizons are frozen at prediction registration; post-hoc horizon extension is forbidden.
- **No Live Trading / Execution Authority:** M4 has zero broker connectivity or order submission logic.

---

## 3. Two-Lane Architecture and Lane Integrity

In accordance with ADR 0012:
- **Exploratory Lane:** Predictions and outcomes generated from exploratory development data (e.g., Alpaca Basic reconstructed bars) carry `lane="exploratory"` and are strictly non-promotable.
- **Promotion Lane:** Currently disabled fail-closed (`PromotionLaneDisabledError`). When re-enabled via M1e Task 8, promotion-grade predictions must be derived from authenticated, license-qualified source bytes.
- **Zero Evidence Upgrades:** Exploratory prediction records can never be converted, relabeled, or upgraded into promotion-grade evidence.

---

## 4. Core Domain Models and Schemas

### 4.1 Prediction Target Types
```python
class PredictionTargetType(StrEnum):
    """Admitted quantitative prediction target types."""

    FORWARD_RETURN = "forward_return"
    DIRECTIONAL_RETURN = "directional_return"
    REALIZED_VOLATILITY = "realized_volatility"
    CROSS_SECTIONAL_RANK = "cross_sectional_rank"
    EXCESS_RETURN = "excess_return"
```

### 4.2 Target Horizon Specification
A target horizon defines the exact temporal span over which the predicted phenomenon is measured.
```python
class HorizonSpecificationV1(FrozenModel):
    """Immutable specification of the forward evaluation horizon."""

    horizon_sessions: int  # Number of regular trading sessions (e.g. 1, 5, 21, 63)
    anchor_session_date: SessionDate  # Decision session t (as-of date)
    start_session_date: SessionDate  # First forward session (usually t+1)
    end_session_date: SessionDate  # Terminal forward session (t+k)
```

### 4.3 Prediction Values
Supported prediction payloads:
```python
class ScalarPointPredictionV1(FrozenModel):
    """Single scalar expected value (e.g. predicted return +0.0245)."""

    point_value: Decimal


class DirectionalPredictionV1(FrozenModel):
    """Categorical directional prediction with confidence."""

    direction: Literal["up", "down", "flat"]
    confidence: Decimal  # Normalized [0.0, 1.0]


class QuantileDistributionPredictionV1(FrozenModel):
    """Quantile distribution predictions (e.g. p10, p50, p90)."""

    quantiles: tuple[tuple[Decimal, Decimal], ...]  # Tuple of (quantile, value) pairs
```

### 4.4 Ex-Ante Prediction Record
```python
class ExAntePredictionRecordV1(FrozenModel):
    """An individual ex-ante prediction for a specific asset and horizon."""

    prediction_id: UUID7
    run_id: UUID7
    security_id: SecurityID
    as_of_time: UTCDateTime
    target_type: PredictionTargetType
    target_horizon: HorizonSpecificationV1
    prediction_value: (
        ScalarPointPredictionV1
        | DirectionalPredictionV1
        | QuantileDistributionPredictionV1
    )
    input_context_hash: SHA256Hash
    model_provenance_hash: SHA256Hash
```

### 4.5 Ex-Ante Prediction Set Envelope
Predictions emitted in a single decision cycle are batched into an immutable set:
```python
class ExAntePredictionSetV1(FrozenModel):
    """Atomic batch of ex-ante predictions emitted at a decision epoch."""

    prediction_set_id: UUID7
    run_id: UUID7
    session_date: SessionDate
    as_of_time: UTCDateTime
    predictions: tuple[ExAntePredictionRecordV1, ...]
    set_hash: SHA256Hash
```

### 4.6 Outcome Resolution Status
```python
class OutcomeResolutionStatus(StrEnum):
    """Terminal resolution classification for an ex-ante prediction."""

    RESOLVED = "resolved"
    INDETERMINATE = "indeterminate"
    DELISTED_WITH_OUTCOME = "delisted_with_outcome"
    DELISTED_WITHOUT_OUTCOME = "delisted_without_outcome"
    EXCLUDED_UNAVAILABLE = "excluded_unavailable"
```

### 4.7 Realized Outcome Record
```python
class RealizedOutcomeRecordV1(FrozenModel):
    """Immutable ground-truth realization and attribution for a prediction."""

    outcome_id: UUID7
    prediction_id: UUID7
    status: OutcomeResolutionStatus
    realized_value: Decimal | None
    error: Decimal | None  # realized_value - predicted_point
    directional_match: bool | None
    resolved_at: UTCDateTime
    evidence_hashes: tuple[SHA256Hash, ...]
    indeterminate_reason: NonBlankStr | None = None
```

---

## 5. Ledger Integration and Causality Verification

### 5.1 Audit Event Types
- `m4.prediction_set.recorded`: Emitted when an ex-ante prediction set is sealed.
  - Entity type: `prediction_set`
  - Entity ID: `prediction_set_id`
  - Payload: Canonical JSON representation of `ExAntePredictionSetV1`.
- `m4.outcome_batch.resolved`: Emitted when forward outcomes are evaluated.
  - Entity type: `outcome_batch`
  - Entity ID: `outcome_batch_id`
  - Payload: Canonical JSON representation of resolved outcomes.

### 5.2 Causality Invariants
1. **Timestamp Precedence:** `prediction_set.as_of_time < horizon.start_session_opened_at`.
2. **Ledger Sequence Precedence:** The sequence number of `m4.prediction_set.recorded` must strictly precede any market observation event recorded for dates within the horizon $H$.
3. **No Retrospective Sealing:** Attempts to record a prediction set whose `as_of_time` is after the horizon opening time fail closed with `LookaheadViolationError`.

---

## 6. Ground-Truth Calculation Engine

Outcomes are computed using pure mathematical functions over authenticated evidence:

### 6.1 Forward Return Ground Truth
Given a target security $S$ and forward horizon $[s_{t+1}, s_{t+k}]$:
1. Retrieve the corporate-action-consistent analytical return series $R = (r_{t+1}, \dots, r_{t+k})$ from `drift.domain.analytical_returns`.
2. If any session return in the horizon is indeterminate or missing without explanation:
   - Mark status as `INDETERMINATE`.
   - Record `indeterminate_reason` (e.g., `MissingSessionReturnError`).
3. If security is delisted during horizon:
   - If delisting outcome has authenticated liquidating proceeds (cash/shares), compound return to termination and record `DELISTED_WITH_OUTCOME`.
   - If proceeds unknown, mark `DELISTED_WITHOUT_OUTCOME`.
4. If full determinate series is available:
   $$\text{realized\_return} = \left(\prod_{i=1}^k (1 + r_{t+i})\right) - 1$$
   - Mark status as `RESOLVED`.
   - Compute error: $\text{error} = \text{realized\_return} - \text{predicted\_point}$.
   - Compute directional match: $\text{sign}(\text{realized\_return}) == \text{sign}(\text{predicted\_point})$.

### 6.2 Realized Volatility Ground Truth
For volatility targets over horizon of length $k \ge 2$:
$$\text{realized\_variance} = \frac{1}{k - 1} \sum_{i=1}^k (r_{t+i} - \bar{r})^2$$
$$\text{realized\_volatility} = \sqrt{\text{realized\_variance}}$$

---

## 7. Baseline Model Reference Grounding

To validate M4 end-to-end without waiting for AI research agents (M7):
- **B4 Momentum Adapter:** Generates 21-session forward return forecasts based on historical 12-1 momentum signals.
- **B5 Low Volatility Adapter:** Generates 21-session forward volatility forecasts based on 60-session historical variance.
- **Null Reference:** Generates zero-return forecasts ($0.0$) to anchor baseline residual variance.

---

## 8. Adversarial Acceptance Gates (M4 Acceptance Suite)

The adversarial acceptance suite must prove the following invariants:

1. **Lookahead Immunity:** Injecting future market movements after `as_of_time` into the environment does not alter the recorded prediction set or its hash.
2. **Causality Ordering:** Predictions post-dating the target horizon open are rejected fail-closed.
3. **Anti-Cherry-Picking:** Missing cohort members in a prediction set are detected and flagged.
4. **Corporate Action Invariance:** Outcome returns across 2:1 stock splits, spinoffs, and cash dividends match true economic reality rather than naive unadjusted price ratios.
5. **Replay Determinism:** Identical prediction sets and market evidence produce bitwise-identical `RealizedOutcomeRecordV1` streams.

---

## 9. Child Issues Implementation Decomposition

1. **M4-1 (`kind:contract`):** Prediction and outcome tracking domain models, types, and ledger schemas (`src/drift/domain/predictions.py`, `src/drift/domain/outcomes.py`).
2. **M4-2 (`kind:implementation`):** Ex-ante prediction recorder, atomic epoch sealing, and M0 ledger persistence (`src/drift/tracking/recorder.py`).
3. **M4-3 (`kind:implementation`):** Deterministic outcome resolver and attribution engine using analytical returns (`src/drift/tracking/resolver.py`).
4. **M4-4 (`kind:integration`):** Reference baseline predictor adapters (B4 momentum, B5 low volatility) and evaluation harness integration.
5. **M4-5 (`kind:implementation`):** Adversarial acceptance suite (`tests/adversarial/test_m4_prediction_tracking_adversarial.py`).
6. **M4-6 (`kind:docs`):** Milestone M4 completion, documentation reconciliation, and ledger audit.
