# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification

Date: 2026-09-19. Status: Canonical architecture design specification for Drift M2 (incorporating external architectural rulings).
Canonical Baseline: Commit `ef24c2c` (and underlying verified Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
Related Architecture Decisions: [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## 1. Objective

M2 constructs the deterministic evaluation and portfolio accounting kernel that powers all quantitative research, strategy screening, and model comparison across Drift.

The evaluator answers one central question:

> Given one exact strategy version, one exact evaluation protocol, one exact evidence lane, one exact provider-neutral historical input bundle, and one exact set of accounting and execution assumptions, what sequence of decisions, fills, economic effects, portfolio states, and resulting wealth occurred?

M2 makes that answer:
- **Deterministic**: Bitwise reproducible across identical inputs, code, and environments.
- **Content-addressed**: Identified by canonical hashing of all constituent parameters, artifacts, and traces without wall-clock or random identifier contamination.
- **Replayable**: Verifiable offline without network access or non-deterministic state.
- **Temporally causal**: Structurally protected against forward-looking leakage, same-bar lookahead, and unannounced corporate actions.
- **Provider-neutral**: Completely decoupled from vendor schemas, raw payloads, or proprietary APIs.
- **Audit-friendly**: Emitting a granular, content-addressed ledger trace of every phase, mark, fill, cash flow, and valuation.
- **Proof-carrying**: Anchored directly to authenticated M1b identity/eligibility, M1c occurred economic effects and settlements, and M1d realized sessions and observations.
- **Structurally protected against evidence laundering**: Incapable of upgrading exploratory development results into promotion-grade validation evidence.

M2 is an accounting and evaluation engine, not a strategy promotion authority. M2 outputs deterministic evidence traces. Strategy promotion decisions, champion/challenger tournaments (M10), and statistical overfitting controls (M11) consume M2 traces rather than living inside M2.

---

## 2. Scope and V1 Domain Boundaries

M2 V1 establishes a rigorous, minimal accounting kernel strictly bounded to regular daily trading sessions for US cash equities.

### 2.1 Admitted Scope (V1)
- **Asset Class**: US cash equities (common stocks, ETFs, American Depositary Receipts admitted through M1b).
- **Session Resolution**: Regular daily trading sessions only (`SessionScope.REGULAR`), bounded by authenticated M1d realized session open and close timestamps (e.g. normal 09:30-16:00 ET, early-close 09:30-13:00 ET).
- **Decision Resolution**: Daily, session-by-session evaluation cycles.
- **Currency**: Single-currency USD cash accounting.
- **Portfolio Constraint**: Fully funded, long-only equity holdings (cash balance >= 0, share quantities >= 0).
- **Position Quantities**: Whole-share integers only.
- **Corporate Action Economics**: First-class M1c occurred effects and delivered settlements (splits, dividends, spin-offs, acquisitions, liquidations, terminations) with exact fraction treatments.
- **Execution**: Target whole-share deltas executed at the next eligible realized regular-session open via an atomic plan-then-commit rebalance.
- **Pricing Basis**: Source-basis unadjusted prices for accounting, marks, and fills.

### 2.2 Explicitly Excluded Scope (V1 Hard Boundaries)
Attempts to evaluate configurations outside this admitted domain fail closed with explicit validation errors:
- **No Intraday Execution**: No intraday bar clocks, tick execution, TWAP/VWAP engines, or minute-level scheduling.
- **No Shorting or Margin**: No negative share balances, borrowing fees, margin calls, or leverage calculations. Attempts to emit negative target positions are rejected.
- **No Fractional Shares**: Whole shares only in holdings; non-integral entitlements are processed according to explicit M1c fraction treatments or fail closed to `INDETERMINATE`.
- **No Options or Derivatives**: Cash equities only; warrants, rights, and convertibles with unsupported property terms fail closed.
- **No Multi-Currency**: Single currency (USD) cash accounting only.
- **No Tax Accounting**: Wash sales, tax-lot identification (FIFO/LIFO/HIFO), and capital gains tax liabilities are execution/tax concerns outside M2.
- **No Live Brokerage or Order Submission**: M2 contains zero network access, broker adapters, or order placement mechanisms.
- **No Strategy Promotion Authority**: M2 outputs evidence quality classifications; it does NOT decide strategy promotion, which belongs exclusively to M10 and M11.

---

## 3. Two-Lane Architecture (ADR 0012)

In accordance with ADR 0012, Drift maintains exactly ONE provider-neutral evaluator core engine operating across two structurally segregated evidence lanes:

```
+-----------------------------------------------------------------------------------+
|                                Drift Evaluator Core                               |
|                                                                                   |
|  - Provider-neutral domain contracts only (M0-M1d)                                |
|  - Causal session clock (Post-Realized-Close Decision -> Next Realized-Open Fill) |
|  - Source-basis unadjusted accounting + M1c occurred effect & settlement logic    |
|  - 5-phase deterministic session schedule (Atomic Plan-Then-Commit Rebalance)     |
|  - Pure runtime strategy interface (Decision Context -> Whole-Share Intent)       |
|  - Content-addressed execution trace & scientific classification                  |
+-----------------------------------------------------------------------------------+
                                         ^
                                         | Consumes
        +--------------------------------+--------------------------------+
        |                                                                 |
+------------------------------------+          +------------------------------------+
|          EXPLORATORY Lane          |          |           PROMOTION Lane           |
|                                    |          |                                    |
| - Purpose: Prototyping, baselines, |          | - Purpose: High-rigor empirical    |
|   signal screening, engineering.   |          |   evidence for M10/M11 analysis.   |
| - Input: Free development data     |          | - Input: Positive M1e qualified    |
|   (Alpaca Basic).                  |          |   sources (e.g. Databento PIT).    |
| - Limitation: Binds explicit known |          | - Requirement: Verified rights,    |
|   flaws (truncated CA replay, etc).|          |   native bytes, positive M1e       |
| - Epistemic Status: Strictly       |          |   completion record, replay match. |
|   non-upgradeable development data.|          | - Epistemic Status: Certified      |
|                                    |          |   promotion-grade evidence.        |
+------------------------------------+          +------------------------------------+
```

### 3.1 Exploratory Development Lane (`EXPLORATORY`)
- **Purpose**: Fast, cost-free engineering verification, baseline establishment (M3), signal exploration, and preliminary hypothesis screening.
- **Authorized Input**: Free development data (default: Alpaca Basic historical SIP bars and REST corporate actions).
- **Known Limitations**: Input bundles carry explicit documented limitations (e.g. truncated corporate action mutation history, unversioned derived bars, missing trading halt telemetry, bounded cohort).
- **Epistemic Constraint**: Results are permanently exploratory. They cannot be submitted to champion/challenger tournaments (M10), overfitting gates (M11), or live execution approval (M16+).

### 3.2 Promotion-Grade Lane (`PROMOTION`)
- **Purpose**: Authoritative empirical evidence for subsequent strategy promotion analysis in M10/M11.
- **Authorized Input**: Datasets produced exclusively by a fully qualified, positively verified M1e real-source profile with positive completion (`M1eCompletionKind.COMPLETED_POSITIVE`).
- **Qualification Requirements**: Every critical dimension declared by the profile must PASS (`QualificationStatus.PASS`, `ExecutionReachability.REACHED`, `admitted_purpose=True`), every dimension must have an explicit evidenced status, exact native bytes must be retained in private storage, rights must authorize internal algorithmic use and indefinite offline retention, and offline replay closure must verify bitwise identical output.
- **Current Operational Status**: Paused/deferred under ADR 0012. Tested in M2 exclusively through synthetic qualification fixtures to verify fail-closed enforcement.

---

## 4. Structural Anti-Upgrade Enforcement

To guarantee that exploratory evidence cannot be laundered into promotion-grade claims, lane separation is enforced at the type and schema layer, not via a mutable boolean flag.

### 4.1 Invariant: No Mutable Lane Field or Promotable Claims
An evaluation run cannot be toggled from exploratory to promotion by flipping a flag.
Furthermore, M2 does NOT output `is_promotable=True`. M2 certifies the *evidence grade* of the run, not whether the strategy itself is approved or promoted.

### 4.2 Acyclic Admission Dependency Graph
The relationship between market data input bundles, admissions, and evaluation runs is strictly acyclic:
$$\text{Market Data} \longrightarrow \text{EvaluationInputBundleV1} (\text{bundle\_hash}) \longrightarrow \text{EvaluationAdmissionV1} (\text{input\_bundle\_hash} = \text{bundle\_hash}) \longrightarrow \text{EvaluationRunIdentity}$$

`EvaluationInputBundleV1` does NOT hold a reference to `admission_hash`. The input bundle is immutable historical evidence independent of the evaluation lane under which it is evaluated. The admission token authorizes the bundle.

### 4.3 Distinct Immutable Admission and Result Types
The domain model enforces disjoint type hierarchies:

```python
class ExploratoryEvaluationAdmissionV1(FrozenModel):
    """Admission proof for exploratory evaluation using development-grade data."""

    schema_version: Literal["1"] = "1"
    admission_id: SHA256Hash  # Content-addressably derived
    lane: Literal["exploratory"] = "exploratory"
    development_source_profile_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    admitted_at: UTCDateTime  # Deterministically anchored to input bundle evaluation_interval.end_time
    admission_hash: SHA256Hash


class PromotionEvaluationAdmissionV1(FrozenModel):
    """Admission proof strictly requiring verified M1e positive completion evidence."""

    schema_version: Literal["1"] = "1"
    admission_id: SHA256Hash  # Content-addressably derived
    lane: Literal["promotion"] = "promotion"
    m1e_completion_record_hash: SHA256Hash
    m1e_profile_hash: SHA256Hash
    m1e_qualification_report_hash: SHA256Hash
    m1e_purpose: Literal["historical_decision_input"]
    m1e_snapshot_hash: SHA256Hash
    m1e_rights_assessment_hash: SHA256Hash
    m1e_replay_result_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    admitted_at: UTCDateTime  # Deterministically anchored to M1e completion.completed_at
    admission_hash: SHA256Hash


type EvaluationAdmissionV1 = Annotated[
    ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1,
    Field(discriminator="lane"),
]

Note on admission determinism: `admitted_at` must never be populated with wall-clock `datetime.now(timezone.utc)`. For exploratory admission, it is deterministically anchored to `bundle.evaluation_interval.end_time`; for promotion admission, it is deterministically anchored to `completion.completed_at`. Re-minting an admission for the same bundle and source evidence produces bitwise identical `admission_hash`.


class EvaluationSummaryMetricsV1(FrozenModel):
    """Raw deterministic accounting metrics summary emitted by the evaluator core."""

    initial_cash: Decimal
    ending_cash: Decimal
    ending_holdings_value: Decimal
    ending_pending_claims_value: Decimal
    ending_net_asset_value: Decimal
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
    total_turnover_notional: Decimal
    total_fill_count: int
    total_session_count: int
    daily_equity_series: tuple[tuple[date, Decimal], ...]


class ExploratoryEvaluationResultV1(FrozenModel):
    """Deterministic exploratory evaluation result; permanently non-promotion-grade."""

    schema_version: Literal["1"] = "1"
    result_id: SHA256Hash  # Content-addressably derived from deterministic payload
    lane: Literal["exploratory"] = "exploratory"
    admission_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    protocol_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1

    @property
    def is_promotion_grade_evidence(self) -> bool:
        return False


class PromotionEvaluationResultV1(FrozenModel):
    """Deterministic promotion-grade evaluation result; verified against M1e positive completion."""

    schema_version: Literal["1"] = "1"
    result_id: SHA256Hash  # Content-addressably derived from deterministic payload
    lane: Literal["promotion"] = "promotion"
    admission_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    protocol_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1

    @property
    def is_promotion_grade_evidence(self) -> bool:
        return True


type EvaluationResultV1 = Annotated[
    ExploratoryEvaluationResultV1 | PromotionEvaluationResultV1,
    Field(discriminator="lane"),
]
```

### 4.4 Absolute Non-Upgrade Rule
There is no constructor, helper, API endpoint, or migration function that converts an `ExploratoryEvaluationResultV1` into a `PromotionEvaluationResultV1`.
If an exploratory evaluation run demonstrates promising performance, that result serves solely as justification to invest capital in acquiring promotion-qualified M1e data. Promotion validation requires an entirely NEW, independent evaluation run executed against the newly qualified dataset.

---

## 5. Evaluator Core Boundary

The evaluator core is a pure Python engine with zero network, filesystem, or provider dependencies.

```
+-----------------------------------------------------------------------------+
|                             Drift Domain Layer                              |
|                                                                             |
|  [M1b Universes]   [M1c Corporate Actions]   [M1d Sessions & Observations]  |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                 EvaluationInputBundleV1 (Proof-Carrying)                    |
|                                                                             |
|  - M1b StructuralEligibilityResultV1 instances & proof hashes               |
|  - M1c EconomicOutcomeResolutionV1 & DeliveryGroup proof hashes             |
|  - M1d RealizedSessionVersionV1 & ScheduledSessionVersionV1 instances        |
|  - M1d unadjusted source-basis DerivedObservationViewV1 instances           |
|  - M1d causal split-normalized DerivedObservationViewV1 instances           |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                             Evaluator Engine                                |
|                                                                             |
|  Input: Strategy + InputBundle + Protocol + CostModel + Admission           |
|  Output: TraceLog + EvaluationSummaryMetrics + Classified Result            |
+-----------------------------------------------------------------------------+
```

The evaluator core accepts:
1. An executable `RuntimeStrategy` conforming to the pure strategy protocol.
2. A validated `EvaluationInputBundleV1`.
3. A declared `EvaluationProtocolV1`.
4. An explicit `EvaluationCostModelV1`.
5. An admitted `EvaluationAdmissionV1`.

The core never interacts with:
- Raw provider bytes, files, or responses (Alpaca, Databento, algoseek).
- Network sockets or HTTP clients.
- Global mutable state, random number generators, or system clocks.
- Broker accounts, orders, or paper trading endpoints.

---

## 6. Runtime Strategy Protocol and Whole-Share Target Intent

### 6.1 Strategy Provenance Separation
Existing M0 domain models (`StrategyReference`, `StrategyArtifact`) are immutable provenance records storing code hashes, artifact references, and hypothesis links. They remain untouched.

### 6.2 Pure Strategy Protocol
M2 introduces a runtime protocol executed during the post-close decision phase:

```python
class PositionViewV1(FrozenModel):
    """Causal, point-in-time view of an existing portfolio holding."""

    security_id: UUID7
    quantity: int
    cost_basis: Decimal
    average_cost_per_share: Decimal


class StrategyDecisionViewV1(FrozenModel):
    """Canonical, causally anchored decision view for one security."""

    security_id: UUID7
    views: tuple[DerivedObservationViewV1, ...]


class StrategyDecisionContextV1(FrozenModel):
    """Causal, point-in-time information set provided to a strategy."""

    session_key: SessionKeyV1
    decision_cutoff: UTCDateTime
    admitted_universe: tuple[UUID7, ...]  # Canonical sorted security_ids
    current_holdings: tuple[PositionViewV1, ...]  # Canonical sorted holdings
    current_cash: Decimal
    portfolio_nav: Decimal
    decision_views: tuple[StrategyDecisionViewV1, ...]  # Canonical sorted views


class SecurityTargetPositionV1(FrozenModel):
    """Target position intent emitted for one admitted security."""

    security_id: UUID7
    execution_listing_id: UUID7
    target_quantity: int  # Must be >= 0 (whole shares, long-only)


class StrategyDecisionIntentV1(FrozenModel):
    """Complete portfolio intent emitted by a strategy at a decision cutoff."""

    session_key: SessionKeyV1
    decision_time: UTCDateTime  # Must strictly match context.decision_cutoff
    targets: tuple[SecurityTargetPositionV1, ...]
    strategy_state_artifact: ArtifactReference | None = None


class RuntimeStrategy(Protocol):
    """Pure strategy interface invoked by the evaluator engine."""

    @property
    def strategy_reference(self) -> StrategyReference: ...

    def decide(
        self, context: StrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1: ...
```

Note on decision determinism: The evaluator engine strictly validates that `intent.decision_time == context.decision_cutoff`. Strategies are prohibited from populating `decision_time` using system wall-clock functions like `datetime.now(timezone.utc)`. If a strategy returns an intent with a mismatched timestamp, validation fails closed with `ValueError("decision intent decision_time must strictly match context.decision_cutoff")`.

### 6.3 Whole-Share Target Positions and Explicit Omission Rule
Strategies emit target WHOLE-SHARE quantities rather than fractional weights or raw buy/sell orders:
- **No Evaluator Capital Allocation Guessing**: The evaluator does not guess how to round fractional shares or allocate remaining cash. The strategy specifies exact target share counts.
- **Explicit Complete Target Set Rule**:
  Any currently held security that is NOT present in `targets` is treated as an explicit liquidation:
  $$\text{target\_quantity} = 0 \quad (\Delta q = -\text{current\_quantity})$$
  If a strategy wishes to maintain an existing holding, it must explicitly include that security in `targets` with `target_quantity = current_quantity`.
- **Long-Only Validation**: Any target quantity $< 0$ immediately triggers a `REJECTED` evaluation classification.
- **Phase 5 vs. Phase 2 Validation Boundary**:
  - In Phase 5 (Post-Close Decision), the engine validates: targets are whole-share integers, targets are non-negative, and new entries (`target > 0`) belong to `admitted_universe`. Phase 5 does NOT validate cash solvency, because next-session open prices and slippage are strictly future unknowns.
  - In Phase 2 (Open Execution), actual cash solvency is enforced when open prices are materialized.

---

## 7. Proof-Carrying Evaluation Input Bundle

An evaluation run operates on a self-contained, content-addressed bundle of authentic Drift artifacts. M2 does NOT flatten away M1b-M1d provenance into self-authored convenience facts:

```python
class EvaluationInputBundleV1(FrozenModel):
    """Complete, proof-carrying input bundle for an evaluation interval."""

    schema_version: Literal["1"] = "1"
    bundle_id: SHA256Hash  # Content-addressed hash of bundle payload
    evaluation_interval: TemporalIntervalClaimV1
    source_snapshot_hash: SHA256Hash | None = None  # Bound for M1e promotion
    m1b_structural_eligibility_hashes: tuple[SHA256Hash, ...]
    m1c_outcome_resolution_hashes: tuple[SHA256Hash, ...]
    m1d_observation_view_hashes: tuple[SHA256Hash, ...]
    m1d_realized_session_hashes: tuple[SHA256Hash, ...]
    m1d_scheduled_session_hashes: tuple[SHA256Hash, ...]
    security_identities: tuple[SecurityV1, ...]
    listing_identities: tuple[ListingV1, ...]
    scheduled_sessions: tuple[ScheduledSessionVersionV1, ...]
    realized_sessions: tuple[RealizedSessionVersionV1, ...]
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...]
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...]
    unadjusted_observation_views: tuple[DerivedObservationViewV1, ...]
    decision_observation_views: tuple[DerivedObservationViewV1, ...]
    bundle_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_bundle_integrity(self) -> Self:
        # Verify self-excluding canonical hash
        expected = content_hash(
            self.model_dump(mode="python", exclude={"bundle_id", "bundle_hash"})
        )
        if self.bundle_hash != expected or self.bundle_id != expected:
            raise ValueError("input bundle canonical hash mismatch")
        # Verify that all included views, outcomes, and sessions match their bound proof hashes
        actual_eligibility_hashes = tuple(
            sorted(content_hash(item) for item in self.structural_eligibilities)
        )
        if actual_eligibility_hashes != self.m1b_structural_eligibility_hashes:
            raise ValueError("structural eligibility proof hash mismatch")
        actual_outcome_hashes = tuple(
            sorted(content_hash(item) for item in self.economic_outcomes)
        )
        if actual_outcome_hashes != self.m1c_outcome_resolution_hashes:
            raise ValueError("economic outcome resolution proof hash mismatch")
        actual_view_hashes = tuple(
            sorted(
                content_hash(item)
                for item in (
                    *self.unadjusted_observation_views,
                    *self.decision_observation_views,
                )
            )
        )
        if actual_view_hashes != self.m1d_observation_view_hashes:
            raise ValueError("observation view proof hash mismatch")
        actual_scheduled_hashes = tuple(
            sorted(content_hash(item) for item in self.scheduled_sessions)
        )
        if actual_scheduled_hashes != self.m1d_scheduled_session_hashes:
            raise ValueError("scheduled session proof hash mismatch")
        actual_realized_hashes = tuple(
            sorted(content_hash(item) for item in self.realized_sessions)
        )
        if actual_realized_hashes != self.m1d_realized_session_hashes:
            raise ValueError("realized session proof hash mismatch")
        return self
```

### 7.1 Separation of Scheduled and Realized Session Authority
The bundle binds `scheduled_sessions` (from `ScheduledSessionVersionV1`) and `realized_sessions` (from `RealizedSessionVersionV1`) separately. The evaluator session clock uses realized session facts for actual open/close boundaries and missingness determination.

### 7.2 No False Halt Syntheses
M2 removes artificial boolean flags like `is_halted: bool = False`. If an observation source (such as Alpaca) does not provide authenticated halt telemetry, halt status is `UNKNOWN`. The evaluator core relies on M1d realized session facts (`outcome="opened"` vs `"did_not_open"`) rather than inventing "not halted" claims.

---

## 8. Temporal Decision Clock and Session Scheduling

M2 implements a strictly causal, lookahead-free evaluation clock driven by authenticated M1d realized session timestamps:

```
Session D (Realized Trading: actual_open -> actual_close)
  |
  +-- Session D actual_close reached (e.g. 16:00 ET normal, 13:00 ET early close)
  |
  +-- Post-Close Cutoff: Session D observations seal under M1d decision cutoff
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D close information set
        Strategy emits target intent for Session D+1
        NO same-day execution permitted
  |
  v
Session D+1 (Next Eligible Realized Regular Trading Session)
  |
  +-- [PHASE 1: PRE_OPEN_EFFECTS]
  |     Apply occurred corporate action share conversions (with FractionTreatmentV1)
  |     Adjust staged target quantities for corporate action splits
  |     Record dividend receivables where M1c proves holding entitlement
  |
  +-- [PHASE 2: OPEN_EXECUTION] (at Session D+1 actual_open)
  |     Plan-then-commit atomic rebalance:
  |       1. Fetch unadjusted open prices from M1d source-basis views
  |       2. Calculate all sell proceeds and buy costs
  |       3. Verify complete target rebalance is 100% funded
  |       4. If funded: commit sells first, buys second
  |       5. If unfunded: reject rebalance, commit NO fills, mark REJECTED
  |
  +-- [PHASE 3: INTRASESSION_EFFECTS]
  |     Settle pending cash claims where delivered settlement proves delivery
  |
  +-- [PHASE 4: CLOSE_MARK] (at Session D+1 actual_close)
  |     Mark portfolio at Session D+1 unadjusted CLOSE price
  |     Record session NAV and trace
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D+1 close information set...
```

### 8.1 Variable Session Hours (Early Closes)
The regular trading session close is NOT hardcoded to 16:00 ET. On scheduled or unscheduled early-close sessions (e.g. 13:00 ET on Christmas Eve or day before July 4th), Phase 5 post-close decision occurs immediately after the proven realized close (`actual_close`). No artificial delay to 16:00 is enforced. Execution at Phase 2 occurs at the next proven realized `actual_open`.

### 8.2 Explicit Warmup Schedule and Transition
- Evaluation protocols specify an explicit warmup session count $W \ge 1$ (e.g. 50 sessions).
- The session clock derives `is_warmup: bool = (session_index < W)` using 0-based session index $0 \le \text{session\_index} < N$.
- Warmup observations populate strategy indicators and rolling state.
- **Sessions $0$ through $W - 2$** (the first $W - 1$ warmup sessions): Phase 5 does NOT invoke `strategy.decide()`; no target intents are staged.
- **Session $W - 1$ Post-Close** (the $W$-th warmup session): Phase 5 invokes `strategy.decide()` for the first time (`session_index >= W - 1`). Target positions are staged for execution at Session $W$ open.
- **Session $W$** (the $(W+1)$-th session, and first non-warmup trading session): Phase 2 (Open Execution) executes trades and fills for the first time.
- If $W = 0$ is declared, Session $0$ open executes 0 trades (no staged targets exist prior to interval start), and Session $0$ post-close is the first decision point. Next-open execution protocols require $W \ge 1$ for non-empty opening execution.

---

## 9. Universe Admission and Historical Survivorship Rules

### 9.1 Sourced M1b Universe Authority
- Evaluator universe membership is derived session-by-session from `StructuralEligibilityResultV1`.
- `StructuralEligibilityClassification.ELIGIBLE` admits the security to the decision universe.
- `INELIGIBLE` or `INDETERMINATE` removes the security from eligibility.
- Indeterminate membership is never treated as eligible.

### 9.2 Liquidations Permitted for Excluded Positions
If a security currently held in the portfolio is removed from the universe (e.g. dropped from an index or becoming `INELIGIBLE`), the strategy is permitted to emit `target_quantity = 0` to liquidate the holding. Target quantities with `target_quantity > 0` (new entries or additions) for non-admitted securities are strictly rejected.

### 9.3 Anti-Survivorship Invariant
Today's constituent list (e.g. current S&P 500 or active Alpaca assets) cannot be projected backward as a historical universe. Any run attempting to project current symbols historically without dated interval eligibility fails validation.

---

## 10. Accounting Basis vs. Decision Data (Unadjusted Sourced Prices)

| Domain Layer | Data Basis | Source Authority | Purpose |
|---|---|---|---|
| **Strategy Decision Context** | Split-Normalized / Causal Views | M1d Decision Views | Indicator calculations, moving averages, signal formulation. |
| **Portfolio Accounting** | Source-Basis UNADJUSTED Prices | M1d Unadjusted Views | Cash movements, fill prices, portfolio close marks, NAV. |
| **Corporate Action Economics** | Occurred Effects & Settlements | M1c Resolutions | Share ratio adjustments, cash dividend receivables, mergers. |

### 10.1 Double-Counting Prevention
Applying split-adjusted or dividend-adjusted prices in portfolio accounting while simultaneously crediting M1c dividends and adjusting share counts double-counts economic gains.
The M2 accounting kernel strictly uses source-basis unadjusted prices (`basis_mode="source_basis"` from M1d). An evaluation configuration attempting to use split-adjusted or total-return prices for portfolio accounting is rejected at validation.

### 10.2 Causal Split Normalization Anchoring
When split-normalized views are provided to `StrategyDecisionContextV1` at Session $S$, they must be causally anchored to Session $S$ (`anchor_session == session_S`). Normalizing historical bars against a future anchor session (e.g. the end of a multi-year backtest) is strictly prohibited as lookahead leakage.

---

## 11. Portfolio State, Cash Accounting, Positions, and Pending Claims Kernel

### 11.1 Identity-Keyed Positions
Holdings are keyed by permanent `security_id` (UUID7), not mutable tickers or primary listings. Changing tickers, exchange transfers, or CUSIP updates do not alter economic position identity. Fills record the specific `listing_id` and venue through which execution occurred.

### 11.2 Portfolio State Model
```python
class SecurityHoldingV1(FrozenModel):
    """Whole-share holding in one admitted equity security."""

    security_id: UUID7
    quantity: int  # Must be > 0
    cost_basis: Decimal  # Total acquisition cost including fees

    @property
    def average_cost_per_share(self) -> Decimal:
        return self.cost_basis / Decimal(self.quantity)


class PendingCashClaimV1(FrozenModel):
    """Receivable for an earned but uncollected cash distribution."""

    claim_id: SHA256Hash  # Content-addressably derived from M1c occurrence
    security_id: UUID7
    action_kind: ActionKind
    occurrence_id: NonBlankStr
    component_id: NonBlankStr
    entitled_quantity: int
    cash_per_share: Decimal
    total_cash_expected: Decimal
    entitlement_session: date
    payable_session: date


class PortfolioStateV1(FrozenModel):
    """Complete immutable snapshot of portfolio state after a session mark."""

    session_key: SessionKeyV1
    cash_balance: Decimal  # Must be >= 0
    holdings: tuple[SecurityHoldingV1, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    holdings_market_value: Decimal
    pending_claims_value: Decimal
    net_asset_value: Decimal  # cash + holdings_market_value + pending_claims_value
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
```

### 11.3 Deterministic Replay and Claim IDs
To guarantee bitwise replay determinism and prevent hash collisions across same-date distributions, `PendingCashClaimV1.claim_id` binds exact M1c occurrence and component identities:
$$\text{claim\_id} = \text{content\_hash}(\text{security\_id}, \text{action\_kind}, \text{occurrence\_id}, \text{component\_id}, \text{entitlement\_session}, \text{payable\_session})$$

### 11.4 Cost Basis Relief and Realized PnL Formulas
When whole shares are sold ($\Delta q_{\text{sell}} > 0$):
$$\text{Cost Basis Sold} = \Delta q_{\text{sell}} \times \left(\frac{\text{current\_cost\_basis}}{\text{current\_quantity}}\right)$$
$$\text{Gross Realized PnL} = (\Delta q_{\text{sell}} \times P_{\text{fill}}) - \text{Cost Basis Sold}$$
$$\text{Net Realized PnL} = \text{Gross Realized PnL} - \text{Transaction Costs}$$

---

## 12. Corporate Actions as First-Class Accounting Events

M2 processes corporate actions natively from M1c occurred effects (`EconomicEffectVersionV1`) and delivered settlements (`EconomicSettlementVersionV1`):

### 12.1 Sourced Fraction Treatment (No Silent Truncation)
M2 strictly forbids arbitrary Python `int(...)` truncation of corporate action share ratios. Calculations must use exact rational arithmetic using Python's standard library `fractions.Fraction(int(ratio.numerator), int(ratio.denominator))` or exact integer quotient and remainder; floating-point arithmetic is strictly prohibited.

For reverse splits, stock acquisitions, spin-offs, and stock dividends:
1. Inspect M1c `ShareComponentV1.ratio_meaning`:
   - If `ratio_meaning == "resulting_per_predecessor"` (forward/reverse splits, stock acquisitions):
     $$\text{exact\_shares} = \text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$$
   - If `ratio_meaning == "additional_per_predecessor"` and recipient is the same security (stock dividend):
     $$\text{exact\_shares} = \text{current\_quantity} + \left(\text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}\right)$$
   - If `ratio_meaning == "additional_per_predecessor"` and recipient is a child security (spinoff):
     Parent shares remain unchanged; child shares entitlement $= \text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$.
2. If $\text{exact\_shares}$ is integral, materialize that whole-share quantity.
3. If $\text{exact\_shares}$ is non-integral, apply the explicit `FractionTreatmentV1` proved by M1c:
   - `round_down`: truncate fraction, keep whole shares.
   - `round_up`: ceiling fraction to next whole share.
   - `round_nearest`: round to nearest whole share.
   - `aggregate_sale_cash`: retain whole shares; convert fractional entitlement into a pending cash-in-lieu claim once M1c settlement/effect proves the cash rate.
   - `fraction_issued`: unsupported by M2 V1 whole-share holding model; fail closed to `INDETERMINATE`.
   - `unknown`: fail closed to `INDETERMINATE`.

### 12.2 Staged Target Scaling Across Splits
When an overnight split occurs in Phase 1 (Pre-Open), pending staged target positions are translated using the exact same rational ratio:
$$\text{staged\_target}' = \text{staged\_target} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$$
If $\text{staged\_target}'$ is non-integral and cannot be resolved by an admitted fraction treatment, the run halts as `INDETERMINATE` due to unsupported corporate-action target translation. Targets are never arbitrarily rounded.

### 12.3 Dividend and Due-Bill Entitlement Logic
M2 does NOT globally equate ex-date with entitlement:
- An economic receivable (`PendingCashClaimV1`) is created ONLY when M1c occurred effect evidence proves that the holding became legally entitled under the event's exact rule.
- For ordinary dividends, entitlement aligns with the admitted ex-date rule.
- For special dividends subject to due-bill redemption: entitlement follows the explicit due-bill redemption date proven by M1c, not the preliminary calendar date.
- Settlement into available cash occurs in Phase 3 when `current_session.date >= claim.payable_session` and M1c delivered settlement evidence proves payment.

### 12.4 Mergers and Acquisitions
- `CASH_ACQUISITION`: Target holding converts to cash claim upon effective date; settled when payment delivered.
- `STOCK_ACQUISITION`: Target holding converts to acquirer shares using exact ratio and `FractionTreatmentV1`.
- `MIXED_ACQUISITION`: Simultaneously applies stock conversion and cash claim.

### 12.5 Spin-offs (`SPINOFF`)
Creates a new `SecurityHoldingV1` in the child security using the exact distribution ratio and `FractionTreatmentV1`.
- **NAV Invariant**: If closing market prices for both parent and child are observable, portfolio NAV is marked normally. If tax cost-basis allocation percentages are unannounced, child holding cost basis is marked indeterminate; realized PnL upon eventual sale fails closed to `INDETERMINATE`, but daily portfolio NAV remains `COMPLETE`.

### 12.6 Terminations and Delistings
Delisting is NOT zero; bankruptcy is NOT zero. Terminal value requires explicit M1c liquidation terms or realized terminal distributions. If terminal proceeds are unknown, the evaluation outcome becomes `INDETERMINATE`. Zero cannot be fabricated.

---

## 13. Deterministic Fill Model (Atomic Plan-Then-Commit)

### 13.1 Next-Open Execution Policy
All target deltas execute at session $D+1$ regular session open.

### 13.2 Atomic Plan-Then-Commit Rebalance
To eliminate order-dependent partial fills and portfolio corruption:
At Phase 2 (Open Execution):
1. **Fetch Open Prices**: Retrieve unadjusted source-basis $P_{\text{open}}$ for all securities with non-zero target deltas ($\Delta q_i = \text{staged\_target}_i - \text{current\_quantity}_i$).
2. **Missing Open Check**: If any required $P_{\text{open}}$ is missing or invalid, immediately halt evaluation as `INDETERMINATE`. Do not substitute close or prior open.
3. **Plan Sells**: Calculate all proceeds from position reductions ($\Delta q_{\text{sell}} > 0$):
   $$\text{Gross Sells} = \sum (\Delta q_{\text{sell}} \times P_{\text{open}}(1 - \text{slippage})) - \text{Sell Costs}$$
4. **Plan Buys**: Calculate all cash required for position expansions ($\Delta q_{\text{buy}} > 0$):
   $$\text{Required Cash} = \sum (\Delta q_{\text{buy}} \times P_{\text{open}}(1 + \text{slippage})) + \text{Buy Costs}$$
5. **Solvency Verification**:
   $$\text{Hypothetical Cash} = \text{current\_cash} + \text{Gross Sells} - \text{Required Cash}$$
6. **Atomic Decision**:
   - **If $\text{Hypothetical Cash} < 0$**: The target intent is unfunded. The engine logs `FillRejectionTraceEventV1` detailing the cash shortfall. It commits **ZERO** fills and **ZERO** portfolio mutations for that rebalance. To guarantee execution determinism and prevent divergent post-rejection trajectories, the engine halts subsequent session stepping immediately. The evaluation is classified scientifically as `EvaluationClassification.REJECTED`. The software status completes as `ExperimentRunStatus.COMPLETED`.
   - **If $\text{Hypothetical Cash} \ge 0$**: The rebalance is fully committed. Sells are applied first (updating cash and holdings), followed by buys, in canonical order sorted by `security_id` UUID bytes.

---

## 14. Versioned Cost and Slippage Model

```python
class EvaluationCostModelV1(FrozenModel):
    """Explicit deterministic cost and slippage parameters."""

    schema_version: Literal["1"] = "1"
    model_id: NonBlankStr
    commission_per_share: Decimal  # USD per share (e.g. Decimal("0.005"))
    fixed_fee_per_order: Decimal  # USD per order (e.g. Decimal("1.00"))
    notional_fee_basis_points: Decimal  # Basis points on traded value
    adverse_slippage_basis_points: Decimal  # Basis points applied against trade
    cost_model_hash: SHA256Hash
```

- Buy Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 + \frac{\text{slippage\_bps}}{10000}\right)$
- Sell Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 - \frac{\text{slippage\_bps}}{10000}\right)$
- Total Transaction Cost:
  $$\text{Cost} = (\text{shares} \times \text{comm\_per\_share}) + \text{fixed\_fee} + \left(\text{shares} \times P_{\text{open}} \times \frac{\text{fee\_bps}}{10000}\right)$$

---

## 15. Missingness, Indeterminacy, and Fail-Closed Semantics

| Missing Event | Prohibited Behavior | Enforced Evaluator Behavior |
|---|---|---|
| Held security missing close price | Forward-fill from previous close | Mark valuation as `INDETERMINATE`; halt stepping. |
| Intended fill missing open price | Fall back to close; synthesize zero | Mark evaluation as `INDETERMINATE`; halt stepping. |
| Corporate action fraction treatment unknown | Truncate via `int(...)` silently | Mark corporate action as `INDETERMINATE`; halt stepping. |
| Security delisted without terms | Mark position value as zero | Mark portfolio terminal NAV as `INDETERMINATE`. |
| Strategy emits negative quantity | Clip to zero silently | Reject strategy intent (`REJECTED`). |
| Strategy attempts to buy beyond cash | Execute partial; allow margin | Log `FillRejectionTraceEventV1`; commit 0 fills; mark `REJECTED`. |

When a fatal indeterminate event occurs, the engine emits `IndeterminateCauseTraceEventV1`, halts subsequent session processing, and marks the result `classification=INDETERMINATE` with `status=COMPLETED`.

---

## 16. Deterministic Per-Session Phase Ordering

```
+-----------------------------------------------------------------------------------+
|                           Canonical Per-Session Phases                            |
+-----------------------------------------------------------------------------------+
| PHASE 1: PRE_OPEN_EFFECTS                                                         |
|   - Apply M1c occurred corporate action share conversions (with FractionTreatment)|
|   - Scale staged target positions by split ratios.                                |
|   - Record pending cash dividend claims where M1c proves legal entitlement.       |
|   - Update share quantities, cost bases, and pending receivables.                 |
+-----------------------------------------------------------------------------------+
| PHASE 2: OPEN_EXECUTION                                                           |
|   - Retrieve staged target positions.                                             |
|   - Derive deltas: Delta q = staged_target - current_quantity.                    |
|   - Fetch unadjusted session open prices from M1d source-basis views.             |
|   - Atomic Plan-Then-Commit: verify complete rebalance is 100% funded.            |
|   - If unfunded: emit FillRejectionTraceEventV1, commit 0 fills, mark REJECTED.   |
|   - If funded: execute Sells first, Buys second; record FillTraceEventV1.         |
+-----------------------------------------------------------------------------------+
| PHASE 3: INTRASESSION_ECONOMIC_EFFECTS                                            |
|   - Settle pending cash claims where payable_session <= current_session.date      |
|     and M1c delivered settlement proves payment.                                  |
|   - Process daytime security distributions or tender completions.                 |
+-----------------------------------------------------------------------------------+
| PHASE 4: CLOSE_MARK                                                               |
|   - Fetch unadjusted close prices at actual realized session close.               |
|   - Compute market value of holdings and Net Asset Value (NAV).                   |
|   - Record SessionMarkTraceEventV1 in the execution trace.                        |
+-----------------------------------------------------------------------------------+
| PHASE 5: POST_CLOSE_DECISION                                                      |
|   - If current session is >= warmup_count W:                                      |
|     - Construct causal StrategyDecisionContextV1 anchored to session close.       |
|     - Invoke runtime strategy `decide(context)`.                                  |
|     - Validate emitted targets (long-only, whole shares, universe constraints).   |
|     - Apply complete target set rule (omitted holdings get target = 0).           |
|     - Stage valid targets for Session S+1 open.                                   |
+-----------------------------------------------------------------------------------+
```

---

## 17. Evaluation Result and Canonical Trace Contracts

### 17.1 Granular Trace Events
The evaluator generates an immutable sequence of typed trace events:
- `SessionStartTraceEventV1`
- `CorporateActionAppliedTraceEventV1`
- `FillTraceEventV1`
- `FillRejectionTraceEventV1`
- `ClaimSettledTraceEventV1`
- `SessionMarkTraceEventV1`
- `StrategyDecisionTraceEventV1`
- `IndeterminateCauseTraceEventV1`

The complete sequence hashes into `trace_hash = content_hash(tuple(trace_events))`.

### 17.2 Separation of Deterministic Content from Orchestration Metadata
- The evaluation result artifact (`ExploratoryEvaluationResultV1` / `PromotionEvaluationResultV1`) contains ONLY deterministic values derived from inputs and historical facts.
- No random UUIDs and no wall-clock completion timestamps.
- Operational execution metadata (`run_id`, `started_at`, `completed_at`, `status=COMPLETED`) belong exclusively to M0 `ExperimentRun`, which references the deterministic result artifact via `artifact_references`.
- Replaying the same evaluation under two different `ExperimentRun` IDs produces the exact same `evaluation_hash` and `trace_hash`.

---

## 18. Replay Integrity and Content-Addressed Identity

An evaluation run is uniquely identified by its canonical evaluation hash:

$$\text{RunHash} = \text{content\_hash}(\text{strategy\_ref}, \text{params}, \text{input\_bundle\_hash}, \text{protocol\_hash}, \text{cost\_model\_hash}, \text{admission\_hash}, \text{code\_hash}, \text{environment\_hash})$$

Re-executing an evaluation with identical inputs, strategy version, protocol, costs, and software environment produces bitwise-identical trace events, identical accounting numbers, and an identical result hash.

---

## 19. Exploratory Lane Admission Contracts

Canonical strings for acknowledged Alpaca limitations:
```python
ALPACA_LIMITATION_TRUNCATED_CA = (
    "corporate-action-mutation-replay-truncated-to-approx-72-days"
)
ALPACA_LIMITATION_UNVERSIONED_BARS = (
    "derived-bars-unversioned-without-provider-vintages"
)
ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"
ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"
```

---

## 20. Promotion Lane Admission and Authentic M1e Gatekeeper

An admission gatekeeper function operates outside the pure evaluator core:

```python
def validate_promotion_admission(
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    completion: M1eCompletionRecordV1,
    profile: QualificationProfileV1,
    report: PurposeQualificationReportV1,
) -> None:
    """Verify promotion admission against authentic M1e qualification evidence."""
    if admission.lane != "promotion":
        raise ValueError("admission must belong to promotion lane")
    if completion.completion_kind != M1eCompletionKind.COMPLETED_POSITIVE:
        raise ValueError("promotion requires positive M1e completion")
    if content_hash(completion) != admission.m1e_completion_record_hash:
        raise ValueError("completion record hash mismatch with admission")
    if content_hash(profile) != admission.m1e_profile_hash:
        raise ValueError("qualification profile hash mismatch with admission")
    if content_hash(report) != admission.m1e_qualification_report_hash:
        raise ValueError("qualification report hash mismatch with admission")
    if bundle.bundle_hash != admission.input_bundle_hash:
        raise ValueError("input bundle hash mismatch with admission")
    if bundle.source_snapshot_hash != admission.m1e_snapshot_hash:
        raise ValueError("input bundle snapshot mismatch with promotion admission")
    if report not in completion.purpose_reports:
        raise ValueError("qualification report is not bound within completion record")
    if admission.m1e_purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("admission requires historical_decision_input purpose")
    if report.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("qualification report purpose mismatch")
    if profile.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("qualification profile purpose mismatch")

    # Cardinality check: all 12 dimensions must be present in the report
    results_by_dim = {res.dimension: res for res in report.results}
    if len(results_by_dim) != 12 or set(results_by_dim.keys()) != set(
        QualificationDimension
    ):
        raise ValueError(
            "qualification report must contain all 12 qualification dimensions"
        )

    # Critical dimension check: every CRITICAL dimension in the profile must PASS
    for crit_dim in profile.critical_dimensions:
        res = results_by_dim.get(crit_dim)
        if res is None:
            raise ValueError(f"critical dimension {crit_dim} missing from report")
        if res.status != QualificationStatus.PASS:
            raise ValueError(f"critical dimension {crit_dim} did not PASS")
        if res.reachability != ExecutionReachability.REACHED:
            raise ValueError(f"critical dimension {crit_dim} was not REACHED")
        if not res.admitted_purpose:
            raise ValueError(f"critical dimension {crit_dim} did not admit purpose")
```

---

## 21. Alpaca Development Bridge and Acquisition Isolation

The Alpaca development bridge is an operational data preparation utility that executes outside the evaluator core.

### 21.1 Architecture Isolation
- The evaluator core NEVER imports or executes the Alpaca bridge.
- The Alpaca bridge runs as an offline intake script (`scripts/intake_alpaca_exploratory.py`).
- It fetches bounded historical SIP bars and corporate actions via authenticated REST endpoints.
- Acquired bytes are stored in private content-addressed storage outside Git.
- An `AcquisitionReceiptV1` and dataset manifest are generated.
- Sourced records are mapped to standard M1b, M1c, and M1d domain models.
- All mapped datasets are validated using Drift's existing public validators (`DatasetValidationDecisionV2`).
- An `ExploratoryEvaluationAdmissionV1` is minted containing explicit known Alpaca limitations.
- An `EvaluationInputBundleV1` is emitted for the evaluator core.

---

## 22. Adversarial Acceptance Test Matrix

The M2 implementation must pass the following 28 explicit adversarial acceptance tests:

| Category | Invariant Tested | Attack Scenario / Input | Expected Result |
|---|---|---|---|
| **Causality** | Same-Bar Close Lookahead | Strategy requests execution at session D close using session D close price | Rejected by protocol validation. |
| **Causality** | Post-Cutoff Observation Leakage | Observation with availability timestamp > decision cutoff passed to strategy | Filtered out or triggers fail-closed error. |
| **Causality** | Early-Close Realized Timing | Session closes at 13:00; strategy decision evaluated after 13:00 | Accepted; uses actual realized close, not 16:00. |
| **Causality** | Future Corporate Action Knowledge | Strategy context contains corporate action announced after decision date | Rejected by M1c causal selection query. |
| **Universe** | Survivorship Bias | Current active asset list used as historical universe | Rejected; requires historical universe definition. |
| **Universe** | Indeterminate Eligibility | Security with `MembershipStatus.INDETERMINATE` admitted to trading | Rejected; indeterminate is not eligible. |
| **Universe** | Post-Delisting Liquidation | Strategy emits target=0 for held security dropped from universe | Permitted; exits non-admitted holding cleanly. |
| **Accounting** | Double-Counting Adjustment | Accounting configured with split-adjusted prices while applying M1c splits | Validation rejects adjusted accounting prices. |
| **Accounting** | Premature Dividend Settlement | Dividend cash credited to available cash on ex-date before payable date | Rejected; ex-date creates receivable, not cash. |
| **Accounting** | Due-Bill Special Dividend | Generic ex-date entitlement applied to special due-bill dividend | Rejected; follows explicit M1c due-bill rule. |
| **Accounting** | Fabricated Delisting Recovery | Security delists without liquidation terms; accounting assumes zero or recovery | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Fractional Split Unknown Treatment | Reverse split yields non-integral shares with unknown fraction treatment | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Missing Close Forward-Fill | Held position has missing close price; evaluator forward-fills prior close | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Multiple Same-Date Cash Claims | Two dividends on same date share security ID and dates | Distinct claim IDs via M1c component/occurrence hash. |
| **Execution** | Close-for-Open Fallback | Missing open price replaced by prior or current close price | Execution fails closed to `INDETERMINATE`. |
| **Execution** | Negative Target Position | Strategy emits negative whole-share target quantity (short position) | Intent rejected; run classified as `REJECTED`. |
| **Execution** | Fractional Share Target | Strategy emits floating-point target quantity (e.g. 10.5 shares) | Intent rejected; whole shares only. |
| **Execution** | Unfunded Rebalance Shortfall | Target rebalance exceeds cash after planned sells | 0 fills committed; classified `REJECTED`. |
| **Cost** | Cost Parameter Mutation | Cost model modified from 0 bps to 5 bps without changing run identity | Prohibited; cost hash changes run hash. |
| **Cost** | Favorable Slippage Applied | Strategy claims positive price improvement on market order | Prohibited; slippage is strictly adverse. |
| **Evidence Lanes** | Non-Critical Dimension Partial | Optional dimension is PARTIAL in positive M1e completion | Promotion admission permitted if critical PASS. |
| **Evidence Lanes** | Critical Dimension Failed | Profile-critical dimension is FAIL or UNKNOWN in report | Promotion admission rejected by gatekeeper. |
| **Evidence Lanes** | Fake PASS Report | Report has PASS but M1e completion record is NEGATIVE | Promotion admission rejected by gatekeeper. |
| **Evidence Lanes** | Promotion Evidence Scope | Caller treats `PromotionEvaluationResultV1` as M10 strategy approval | Disallowed; M2 provides evidence, not approval. |
| **Replay** | Replay Across ExperimentRuns | Identical input evaluated under different ExperimentRun UUIDs | Bitwise identical evaluation hash and trace hash. |
| **Replay** | Overnight Split Target Scaling | Staged target scaled across forward split before Open Execution | Delta correctly matches intended economic target. |
| **Provider Boundary** | Raw Vendor Payload Leakage | Raw Alpaca JSON dictionary passed into strategy or evaluator core | Prohibited; core accepts only Drift domain models. |
| **Provider Boundary** | Missing Halt Synthesized | Alpaca missing halt data interpreted as affirmative "not halted" | Prohibited; missing halt remains unknown. |

---

## 23. Explicit Non-Goals

M2 does NOT implement:
- Strategy promotion decisions, champion/challenger tournaments, or approval (M10/M11).
- Alpha generation or predictive quantitative models (M3+).
- Statistical scorecards, Sharpe ratios, or drawdown analysis (M5).
- Machine learning, reinforcement learning, or LLM agents (M7+).
- Intraday bars, tick data, or high-frequency order books.
- Short selling, margin, leverage, or stock borrowing mechanics.
- Options, futures, foreign exchange, or fixed income.
- Live trading, broker order submission, or Robinhood integration.

---

## 24. Future Architectural Extension Points

1. **Intraday Session Expansion**: The `SessionScope` and `SessionKeyV1` models natively support adding extended hours or hourly intervals without altering accounting kernel mechanics.
2. **Shorting and Margin Facilities**: A future margin kernel can introduce `BorrowAgreementV1` and short position accounts beside the long-only kernel.
3. **Multi-Currency Valuations**: Cash balances can expand to `Mapping[CurrencyCode, Decimal]` with explicit causal exchange-rate mark events.
4. **Market Impact Simulation**: `EvaluationCostModelV1` can incorporate quadratic or square-root volume participation impact models in M12 without breaking V1 linear costs.
