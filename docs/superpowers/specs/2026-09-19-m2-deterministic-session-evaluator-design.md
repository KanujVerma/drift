# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification

Date: 2026-09-19. Status: Canonical architecture design specification for Drift M2 (incorporating external architectural rulings).
Canonical Baseline: Implementation baseline is commit `68092d299f5618fb0da86049ce6f364b9e5a9f3c` (with earlier M2 checkpoints at `3aa0a5b` and `8c954f1`, and the underlying verified M1e Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`, preserved in history).
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

**Amendment, cross-slice adversarial finding F4.** The `input_bundle_hash = bundle_hash` link above was declared but never enforced, so a valid `EvaluationRunIdentityV1` could bind a promotion admission hash over a bundle that admission never admitted. `build_evaluation_run_identity` now takes the admission and the bundle as objects rather than two independent hashes, and fails closed unless `admission.input_bundle_hash == bundle.bundle_hash`.

### 4.3 Distinct Immutable Admission and Result Types
The domain model enforces disjoint type hierarchies:

```python
class ExploratoryEvaluationAdmissionV1(FrozenModel):
    """Admission proof for exploratory evaluation using development-grade data."""

    schema_version: Literal["1"] = "1"
    lane: Literal["exploratory"] = "exploratory"
    input_bundle_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    admission_hash: SHA256Hash


class PromotionEvaluationAdmissionV1(FrozenModel):
    """Admission proof strictly requiring verified M1e positive completion evidence across both consumer purposes."""

    schema_version: Literal["1"] = "1"
    lane: Literal["promotion"] = "promotion"
    m1e_completion_record_hash: SHA256Hash
    m1e_profile_set_hash: SHA256Hash
    decision_handoff_hash: SHA256Hash
    audit_handoff_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    provenance_proof_hash: SHA256Hash
    admission_hash: SHA256Hash


type EvaluationAdmissionV1 = Annotated[
    ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1,
    Field(discriminator="lane"),
]

Note on admission determinism: Admissions do not carry operational wall-clock creation timestamps (`admitted_at`) or redundant identifier fields (`admission_id`). Operational timestamps belong to M0 `ExperimentRun`, audit events, and upstream M1e completion records. The semantic identity is a single self-excluding `admission_hash = content_hash(...)`. Re-evaluating the identical bundle with identical qualification evidence yields bitwise identical `admission_hash`.

Dual-purpose M1e binding via QualifiedSourceHandoffV1: A promotion evaluation relies on two distinct epistemic roles: `HISTORICAL_DECISION_INPUT` (for point-in-time information the strategy was permitted to know at decision cutoffs) and `RETROSPECTIVE_AUDIT` (for ex-post accounting truth, settlements, terminal liquidations, and evaluation reconstruction). Both purposes are bound authoritatively through `decision_handoff_hash` and `audit_handoff_hash`, pointing to M1e `QualifiedSourceHandoffV1` objects. Those handoffs bind the exact profile, report, target, snapshot, environment closure, and replay authorization hashes, eliminating redundant duplicated fields from the admission token while maintaining unbroken cryptographic provenance.


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

### 6.3 Security-Level Targets and Historical Listing Resolution
Strategies target economic securities (`security_id`), NOT historical listings (`listing_id`) or exchange tickers:
- **No Stale Listing Selection in Strategy**: Strategies do not pick exchange venues or track historical listing migrations.
- **Evaluator Execution-Listing Policy**: The evaluator resolves the execution listing dynamically at Phase 2 (Open Execution) using M1b structural eligibility evidence: "execute through the uniquely resolved eligible historical primary listing for the execution session."
- **Fail-Closed Resolution**: If no exact eligible listing exists for an admitted security on the execution date, or if multiple candidate listings cannot be uniquely resolved, execution halts fail-closed to `INDETERMINATE`. The resolved `listing_id` and venue are recorded on `FillTraceEventV1`.

### 6.4 Whole-Share Target Positions and Explicit Omission Rule
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

## 7. Proof-Carrying Evaluation Input Bundle and Epistemic Input Separation

An evaluation run operates on a self-contained, content-addressed bundle of authentic Drift artifacts. M2 does NOT flatten away M1b-M1d provenance into self-authored convenience facts, nor does it launder retrospective data into historical decision evidence.

### 7.1 Exploratory Reconstructed Session Observation vs True Decision Information

Free development providers (such as Alpaca) provide current snapshots of historical bars and corporate actions, but lack historical provider assertion vintages, publication cutoffs, and halt telemetry. Strict M1d normalization requires authentic `RealizedSessionVersionV1` authority (`bind_observation_session` only classifies an observation as fully bound through realized open/close evidence), so scheduled-only exploratory history must never be forced through `materialize_observation_decision`/`materialize_observation_outcome`: it would either fail honestly or fabricate realized history. Fabrication is forbidden.

Nor may exploratory inputs claim M1b structural authority. `resolve_structural_eligibility(...)` accepts only `ResolutionMode.AS_KNOWN` with `InformationRole.DECISION_INFORMATION` by deliberate fail-closed M1b invariant (`structural_decision_mode_required`); `CURRENT_INTERPRETATION` + `EX_POST_OUTCOME` structural evidence does not exist and must not be built by M2. Exploratory evaluation therefore operates over an explicitly predeclared bounded security cohort instead of a historical universe.

M2 defines exploratory-only contracts:

**ExploratoryCohortAuthorizationV1** (`schema_version="1"`, `kind="predeclared_bounded_security_cohort"`, `cohort_id`, `cohort_version`, `security_ids: tuple[UUID7, ...]` nonempty/unique/canonically sorted, self-excluding `cohort_hash`): experiment SCOPE authorization only. It asserts only that these securities are authorized exploratory subjects. It is NOT proof of universe membership, survivorship-free selection, structural listing eligibility, primary listing, or the historical availability of any record. It carries no listing/ticker, timestamp, provider, or random fields. Its use mechanically requires the exploratory admission to acknowledge `ALPACA_LIMITATION_BOUNDED_COHORT`.

**ExploratoryReconstructionPolicyV1** (`schema_version="1"`, `policy_id`, `policy_version`, `mode="source_basis_scheduled_session_reconstruction_v1"`, `required_fields` exactly `("close", "high", "low", "open", "volume")` canonically ordered, `required_basis="unadjusted"`, `semantic_policy_hash`, self-excluding `policy_hash`): immutable, content-addressed, no network/provider/clock/random fields. The scheduled exploratory path is source-basis UNADJUSTED only; it never produces `basis_mode="split_normalized"` and never re-implements M1d split normalization.

**ExploratoryReconstructedFieldV1**: binds `field_name` (exactly one of open/high/low/close/volume), exact Decimal `source_value` (float/NaN/Infinity rejected), `method_id`, field `meaning` (price for OHLC, share_volume for volume), and `source_field_hash`. Methods must exist in the selected `ObservationContractV1` with unadjusted semantics; unknown or fallback semantics fail closed.

**ExploratoryReconstructedSessionObservationV1** (`kind="exploratory_reconstructed_session_observation"`): binds `session_key`, `security_id`, `listing_id`, `venue`, `cohort_hash`, the exact source observation / observation contract / scheduled-session hashes with their selection proofs, the schedule artifact and generated row hashes, the `ObservationOutcomeQueryV1` hash, source context hash, `evidence_vintage_cutoff`, `reconstruction_policy_hash`, `currency`, canonical `fields`, `acknowledged_limitations` (always at least `ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION` and `ALPACA_LIMITATION_UNVERSIONED_BARS`), and a self-excluding `reconstruction_hash`. The builder replays existing `select_observation_records` selection and `generate_schedule` generation; it never calls `bind_observation_session`, the M1d materializers, or the M1b structural resolver.

An `ExploratoryReconstructedSessionObservationV1` is NOT: `DerivedObservationViewV1`, `ObservationDecisionReferenceV1`, `ObservationOutcomeReferenceV1`, an M1d `NormalizationResultV1`, proof of historical publication availability, proof of a realized session, proof of the absence of halts, or promotion-grade evidence.

**Epistemic Contract**:
- **Retrospective Knowledge Warning**: A reconstructed observation may contain corrections, corporate action revisions, or source adjustments published AFTER the historical session; `evidence_vintage_cutoff` is that retrospective cutoff.
- **Scientific Utility**: Valid and authorized for engineering validation, harness closure, indicator calculation, and exploratory strategy screening over the declared cohort.
- **Strict Prohibition**: NEVER historical-decision proof; NEVER promotion-grade; NEVER convertible into promotion evidence.
- **Promotion Lane Prohibition**: Any promotion evaluation that encounters an `ExploratoryReconstructedSessionObservationV1` is immediately rejected by structural validation.

**Amendment, issue 46 (the issue 42 adjudication of ADR 0012 Option B).** Reconstructed observations may drive strategy decisions in the EXPLORATORY lane only, through a dedicated exploratory-only type. `src/drift/domain/evaluator_exploratory_strategy.py` defines `ExploratoryStrategyDecisionContextV1`, whose evidence members are `ExploratoryReconstructedDecisionViewV1` groups of `ExploratoryReconstructedSessionObservationV1` (one per session, in business-time order), and `ExploratoryReconstructedRuntimeStrategy.decide_exploratory`, which answers it. `StrategyDecisionViewV1`, `StrategyDecisionContextV1`, and `RuntimeStrategy.decide` are unchanged and are not unions; the only union is the engine's lane-dispatch strategy parameter. The context carries literal `lane="exploratory"`, `evidence_grade="exploratory_reconstructed"`, and `is_promotion_grade_evidence=False`; refuses any decision session without `scheduled_reconstruction` authority; decides at exactly the scheduled close its generated calendar row states (13:00 on an early close, never an artificial 16:00); requires a reconstruction for its own decision session bound to that session's scheduled record and generated row; refuses any reconstruction from a later session; and must acknowledge the scheduled-clock, bounded-cohort, and reconstruction limitations. `SessionEvaluatorEngine` fixes the lane at construction: an `ExploratoryEvaluationAdmissionV1` over a `scheduled_session_reconstruction` clock, with its `ExploratoryCohortAuthorizationV1` supplied as `SessionEvaluatorEvidence.exploratory_cohort`, takes the reconstructed lane after `validate_exploratory_admission`, the bounded-cohort acknowledgement, and a per-reconstruction cohort and calendar-row binding; every other exploratory admission takes the realized lane unchanged; and a `PromotionEvaluationAdmissionV1` over any bundle carrying exploratory reconstructions, or with an exploratory cohort, is refused at construction. Each reconstructed decision reads only reconstructions for clock sessions already stepped, and is traced as `ExploratoryStrategyDecisionTraceEventV1` (never `StrategyDecisionTraceEventV1`), naming every reconstruction read and every limitation carried. Scope boundary: the ruling authorizes reconstructed evidence for decisions only. A scheduled-reconstruction bundle still carries no authorized accounting evidence, so Phase 2 execution of any traded security and Phase 4 marking of any held position remain `INDETERMINATE` until accounting over reconstructed evidence is separately decided.

**Amendment, issue 55 (ruled in #62, Q1).** A reconstruction's self-excluding `reconstruction_hash` proves only that it is self-consistent, never that a source produced it, so once reconstructions drive decisions they are trusted only by canonical re-derivation. `ExploratoryReconstructionReplay` (`src/drift/evaluator/reconstruction.py`) carries the shared `ExploratoryReconstructionPolicyV1` and one `(ObservationOutcomeQueryV1, M1dResolutionContext)` request per reconstruction; together with the declared cohort these are exactly the inputs of `build_exploratory_reconstructed_session_observation`, the one canonical builder. `verify_exploratory_reconstructions` re-derives every request and requires exact canonical equality over the multiset in both directions, so no carried reconstruction goes unverified and none re-derived is missing. That single equality proves every field (source observation, observation contract, selection proofs, generated schedule, source context hash, policy, OHLCV values, currency, limitations, and hash) is exactly what the canonical builder derives from the replay's own M1d context; it does not prove that context authentic, which is the replayed source evidence itself, as it is for authentic views. Two further bindings sit beside it. The clock is bound separately by `require_scheduled_calendar_row`: each reconstruction's scheduled session and generated row hashes must be among its clock session's authority records. And at the bundle boundary, `build_evaluation_input_bundle` and `verify_evaluation_input_bundle` replay every request against the one context they are handed, refusing any query naming another (the builder's own M1d guard then refuses a request whose context object does not match its query), and apply the calendar-row binding to a scheduled clock. `SessionEvaluatorEvidence.exploratory_reconstruction_replay` is required exactly when the reconstructed lane is taken and refused everywhere else, like `exploratory_cohort`; the lane gate re-derives after the cohort and calendar-row binding and before any decision reads a reconstruction. Trust boundary: reconstructions riding a realized-clock bundle are never re-derived by the engine, because that lane never reads them as decision or accounting evidence (only their limitations propagate into the admission and result); they are only as trusted as `verify_evaluation_input_bundle` makes them. The grade is unchanged: re-derived reconstructions remain EXPLORATORY evidence and upgrade nothing.

**Amendment, issue 54 (ruled in #62, Q2, option C).** This supersedes the issue 46 scope boundary on accounting. In the EXPLORATORY reconstructed lane only, and only after the issue 55 gate has re-derived every reconstruction, Phase 2 prices each traded security from the execution session's reconstructed open and Phase 4 marks each holding at that session's reconstructed close, through the dedicated `ExploratoryReconstructedAccountingPriceV1` (`src/drift/domain/evaluator_exploratory_accounting.py`). The record is not a `DerivedObservationViewV1` and shares no domain base with one. It binds security, listing, venue, session, `field_role` (`open` or `close`), the unadjusted source-basis price, currency, the reconstruction hash, the source field hash, the scheduled session and generated row hashes, and every limitation of the reconstruction, with literal `evidence_grade="exploratory_reconstructed"` and `is_promotion_grade_evidence=False` and a self-excluding `price_hash`. A mark's `MarkEvidenceV1` is graded `exploratory` and names that `price_hash`. Every price a phase consumes is traced, in full, as `ExploratoryAccountingPriceTraceEventV1` (never folded into a fill or mark event), which also states at least every limitation the reconstructed grade carries. A missing reconstruction, more than one reconstruction for a security and session, a price that is not strictly positive, or a price in a currency other than the book's halts the run `INDETERMINATE`; nothing is defaulted. Known limitation, ruling requested in #76: an absent corporate-action outcome is read as no corporate action in either lane, so until closed-world corporate-action coverage is required, a reconstructed trading run across an unrecorded split or dividend can complete with wrong numbers; trading-baseline evidence waits on that ruling. A realized-clock bundle never prices from a riding reconstruction. `EvaluationRunArtifactsV1` refuses a promotion result bound to any `exploratory_accounting_price` event, in addition to the promotion lane's existing refusal of exploratory mark grades.

### 7.2 Exploratory Business-Time Causality Invariant

Exploratory relaxation of publication vintages does NOT permit future business-time leakage:
- **Historical Business-Time Ordering**: The strategy at session $D$ post-close may see only historical business-time facts up through session $D$ under its declared reconstruction policy.
- **Strictly Prohibited at Session $D$**:
  - Session $D+1$ or later market prices (open, high, low, close, volume).
  - Later-session returns or future price movements.
  - Future corporate action effective dates before their business-time occurrence.
  - Ex-post labels, future universe exits, or target forward outcomes.
- **What Exploratory Relaxes**: Provider publication/revision availability timestamps (e.g. a corrected 2022 bar retrieved in 2026 may be used in an exploratory backtest of 2022). It does NOT relax chronological business-time ordering.

### 7.3 Promotion Inputs: Authentic Decision Information

Promotion lane strategy inputs strictly require:
- `InformationRole.DECISION_INFORMATION`
- `ResolutionMode.AS_KNOWN` where applicable
- `ObservationDecisionReferenceV1` / decision-role normalization
- Historical publication and availability cutoffs verified under positive M1e qualification.

### 7.4 Input Bundle and Replay-Bound Preparation

A compact runtime bundle exposes numeric views for execution efficiency, but bundle preparation must verify that every view derives from exact upstream Drift kernel replays rather than untrusted Pydantic construction:

**Amendment, cross-slice adversarial finding F2 (lane leakage).** Replay-boundness alone did not stop a bundle from carrying evidence for sessions its own clock never contained, which let evidence from one corpus ride into an evaluation authorized over another. `EvaluationInputBundleV1` now fails closed in its own validator when any `authentic_decision_views[*].source_session`, any `authentic_accounting_views[*].source_session`, or any `exploratory_reconstructed_observations[*].session_key` is absent from `session_clock`, and when the clock's span escapes `evaluation_interval`. A split-normalization `anchor_session` is deliberately exempt: it is a normalization reference point, not evidence consumed over the interval. This is complementary to the issue 34 provenance proof, which binds contents to a snapshot rather than to the clock.

```python
class EvaluationInputBundleV1(FrozenModel):
    """Complete, proof-carrying input bundle for an evaluation interval."""

    schema_version: Literal["1"] = "1"
    evaluation_interval: TemporalIntervalClaimV1
    source_snapshot_hash: SHA256Hash | None = None  # Bound for M1e promotion
    session_clock: SessionClockV1
    security_identities: tuple[SecurityV1, ...]
    listing_identities: tuple[ListingV1, ...]
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...]
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...]
    authentic_decision_views: tuple[DerivedObservationViewV1, ...]
    authentic_accounting_views: tuple[DerivedObservationViewV1, ...]
    exploratory_reconstructed_observations: tuple[
        ExploratoryReconstructedSessionObservationV1, ...
    ] = ()
    bundle_hash: SHA256Hash  # self-excluding canonical content hash

    @property
    def has_exploratory_reconstructions(self) -> bool:
        return bool(self.exploratory_reconstructed_observations) or (
            self.session_clock.mode == "scheduled_session_reconstruction"
        )
```

**Preparation Boundary (`build_evaluation_input_bundle` / `verify_evaluation_input_bundle`)**:
1. **Promotion Decision Views**: Replays and materializes each view using `materialize_observation_decision(reference, query, context)` with `M1dResolutionContext`, verifying exact match with `ObservationDecisionReferenceV1`.
2. **Accounting Outcome Views**: Replays and materializes unadjusted views using `materialize_observation_outcome(reference, query, context)`.
3. **Exploratory Strategy Views**: Constructs `ExploratoryReconstructedSessionObservationV1` through `build_exploratory_reconstructed_session_observation(query, context, cohort, policy)` under an `ObservationOutcomeQueryV1`, using existing M1d source selection and schedule generation, with explicit retrospective/unversioned limitations. It never yields `ObservationDecisionReferenceV1`, `ObservationOutcomeReferenceV1`, or `DerivedObservationViewV1`. Issue 55: `build_evaluation_input_bundle` derives them itself from `exploratory_cohort` and `exploratory_reconstruction_replay` and never accepts them from the caller, and `verify_evaluation_input_bundle` re-derives them and requires exact equality; both replay them against the same `M1dResolutionContext` as the views and bind a scheduled clock's calendar rows, and a bundle carrying reconstructions without replay inputs is refused.
4. **M1b Universes**: Replays and verifies `StructuralEligibilityResultV1` against selection context. Promotion strictly requires `ResolutionMode.AS_KNOWN` plus `InformationRole.DECISION_INFORMATION`. Exploratory evaluation is scoped by `ExploratoryCohortAuthorizationV1` instead of historical structural eligibility, because `resolve_structural_eligibility` correctly accepts only as-known decision information; `CURRENT_INTERPRETATION` plus `EX_POST_OUTCOME` structural evidence does not exist and must not be built by M2. The cohort mechanically binds `ALPACA_LIMITATION_BOUNDED_COHORT` in the exploratory admission.
5. **M1c Economics**: Replays and verifies `EconomicOutcomeResolutionV1` against M1c selection context, proving terms, occurred effects, and delivered settlements independently.

**Amendment, issue 80 (part of the issue 31 Decision 4 ruling; Decision 4 is not complete).** Items 4 and 5 were specified but never implemented, and the session clock was never re-derived either: structural eligibility, economic outcomes, security and listing identity, and session-clock authority were bound only by their own content hashes, so a realized clock with invented authority, a scheduled calendar row relabelled as realized, and a fabricated `AS_KNOWN` universe each obtained a proof through build, mint and gate. `verify_evaluation_input_bundle` now takes `session_queries`, `structural_requests` (each a `(ListingV1, security_id, NormalizedSelectionQueryV1)` triple) and `economic_requests` (each a `MarketSelectionQueryV1`), the way it takes `(reference, query)` view requests, and re-derives each class through its one canonical builder against the one M1d context it is handed, requiring exact canonical equality: the clock through `build_realized_session_clock` or `build_scheduled_reconstruction_clock`, chosen by the bundle clock's own mode (`verify_session_clock`); structural eligibility through `resolve_structural_eligibility` over the context's M1b evidence (`structural_context`, `research_definition`, `issuer_id`, `structural_methodology_id`, all bound by the context identity); and economic outcomes through `resolve_economic_facts` over the context's M1c evidence. A bundle carrying a structural eligibility or an economic outcome without its request is refused by count, as a view is. A realized clock without its session queries is refused. A scheduled-reconstruction clock is re-derived whenever its queries are supplied; without them it is not re-derived here. That is a known gap, not a safety argument: such a clock's session times are then only as trusted as the caller that built it. It cannot reach promotion, because the promotion gate refuses its mode, and requiring its queries is left to the scheduled-lane clock work of issue 84, which it overlaps. Minting always supplies the queries, and every other present caller of the verifier is a test; the Alpaca bridge never calls it. `mint_bundle_provenance_proof` requires `session_queries` (keyword-only, no default), passes every request to verification, and also binds every `SecurityV1` and `ListingV1` the bundle carries, every member of both, to an identity that an `ASSIGNED` record of the context's M1b identity assignments carries; an unassignment record attests nothing, the venue is part of a listing's identity, and a bundle carrying identities over a context with no M1b evidence cannot mint. `BundleProvenanceProofV1` gains `session_request_hashes`, `structural_request_hashes` and `economic_request_hashes`. The change is construction-additive but hash-changing: each field defaults to `()`, so every existing construction still validates, and each is covered by `proof_hash`, so every proof hash changes. `build_evaluation_input_bundle` is unchanged and still accepts a caller-supplied clock, eligibilities, outcomes and identities; they become trusted only once verification or minting re-derives or binds them. Decision 4 coverage is not complete with this amendment. The engine's `SessionEvaluatorEvidence` is not yet bound to the qualified context, and the request sets are chosen by the caller, so omitting a session or a structural eligibility can still change an evaluation result. Both are tracked separately.

**Amendment, issue 92 (owner ruling A).** A dataset-level limitation had no bundle evidence obliging it. The Alpaca bridge's admission acknowledges all six Alpaca limitations, and five were already obliged: the scheduled clock and the reconstructions declare their own, and the engine's lane gate requires the bounded-cohort acknowledgement. The sixth, `ALPACA_LIMITATION_TRUNCATED_CA`, describes the bridge's corporate-action data window, which no evidence member declares, so an admission minted outside the bridge over the exact bridge bundle could omit it and the run still completed. `EvaluationInputBundleV1` gains `dataset_limitations: tuple[NonBlankStr, ...] = ()`, the producer's declarations about its dataset itself. It follows the sibling limitation fields of `SessionClockV1` and `ExploratoryReconstructedSessionObservationV1`: free non-blank strings, duplicates refused, canonically sorted. It is deliberately not a closed vocabulary. A limitation only ever obliges more acknowledgement and keeps a bundle out of promotion, so an unknown string grants nothing, and refusing one would add no safety while making every new producer amend the domain module. The field is covered by `bundle_hash` and is part of `required_limitations`, so `validate_exploratory_admission`, and through it the engine's lane gate, refuses an admission omitting any declared dataset limitation, and the promotion gate's existing refusal of a bundle declaring any limitation covers it unchanged. Nothing re-derives a producer's declaration: verification and minting bind it only through the bundle hash, so a bundle declaring one still builds and mints, and the promotion gate refuses it. `assemble_evaluation_input_bundle` and `build_evaluation_input_bundle` take `dataset_limitations` as a keyword argument defaulting to `()`. The Alpaca bridge declares exactly `ALPACA_LIMITATION_TRUNCATED_CA` through it; its admission still acknowledges the same six limitations, and every other member of its bundle is byte-identical. The change is construction-additive but hash-changing: the field defaults to `()`, so every existing construction still validates, and the canonical dump includes it, so every bundle hash changes, and with it every admission, run identity and result hash that binds one. No evaluation bundle hash is persisted or pinned in the repository. Residual: the obligation is only as complete as the producer's declaration. A bundle re-assembled from the bridge's members without it is a different bundle under a different hash, which the bridge never emits.

### 7.5 Session Clock Contract (Realized vs Scheduled Reconstruction)

M2 defines two distinct clock authority modes via `SessionClockMode = Literal["realized_session_authority", "scheduled_session_reconstruction"]`:

```python
class EvaluationSessionV1(FrozenModel):
    """One evaluation session boundary with bound proof authority."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    opened_at: UTCDateTime
    closed_at: UTCDateTime  # must be strictly after opened_at
    authority: Literal["realized", "scheduled_reconstruction"]
    authority_record_hashes: tuple[SHA256Hash, ...]
    authority_proof_hashes: tuple[SHA256Hash, ...]
    session_hash: SHA256Hash  # self-excluding canonical content hash


class SessionClockV1(FrozenModel):
    """Immutable content-addressed sequence of evaluation sessions."""

    schema_version: Literal["1"] = "1"
    mode: SessionClockMode
    sessions: tuple[EvaluationSessionV1, ...]  # nonempty, unique keys, chronological
    acknowledged_limitations: tuple[NonBlankStr, ...]
    clock_hash: SHA256Hash  # self-excluding canonical content hash
```

- **`PROMOTION` Lane**: Strictly requires `mode == "realized_session_authority"`, whose sessions bind authentic selected `RealizedSessionVersionV1` instances with proven `outcome="opened"` and non-null `actual_open`/`actual_close` (`closed` strictly after `opened`), plus their exact selection proof and record identity hashes. A `did_not_open` or `unknown` realized outcome can never produce an evaluation session. Early closes use the proven `actual_close`; nothing hardcodes 16:00 or 09:30.
- **`EXPLORATORY` Lane**: Uses realized authority when genuinely available, or `scheduled_session_reconstruction` built from existing M1d scheduled selection plus the `generate_schedule(...)` pipeline. An included scheduled session requires artifact `classification == "generated"`, output `interpretation_status == "authorized"`, state in (`regular`, `early_close`), and non-null generated UTC open/close. Early closes preserve the exact generated close. The clock's limitations include `ALPACA_LIMITATION_ABSENT_HALTS` and `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`.
  - Under scheduled reconstruction the clock NEVER manufactures synthetic `RealizedSessionVersionV1` instances and NEVER claims "no halt occurred" or "actual open proven."
  - If a scheduled session is expected open but required market observations fail to materialize, later evaluation is `INDETERMINATE`; the clock records neither `did_not_open` nor a halt cause.
- **Anti-Laundering Gate**: Promotion admission strictly rejects any bundle configured with `scheduled_session_reconstruction`.

**Amendment, issue 84 (clock integrity).** `SessionClockV1` orders sessions by their UTC boundaries (`session_order_key`) and refuses any session that opens before its predecessor closes. It now also requires local dates to be non-decreasing in clock order; with unique (MIC, local date) keys, each venue's dates then strictly increase. Together these carry the ordering guarantee: every stepped session has closed by the next open, so the stepped prefix is exactly the history closed at a decision cutoff, and the issue 66 history filter in `reconstructed_history_sessions` is defense in depth behind the non-overlap guard. These guards refuse decreasing-date inversions only; they do not prove that a session's UTC stamps belong to its local date. Restriction: a multi-venue clock whose sessions overlap in UTC (including the issue 66 case, a same-date session opening first and closing after an early close), or whose later local date precedes an earlier one in UTC, is out of scope for M2 and refused. A non-overlapping multi-venue clock with two sessions on one local date is admitted by the clock, and refused at engine construction (the issue 97 amendment, section 13.1). In the EXPLORATORY reconstructed lane the issue 55 principle now covers clock sessions as well: after re-deriving the reconstructions, the lane gate rebuilds each replay request's session with `build_scheduled_reconstruction_clock((query,), context)` and requires every clock session a reconstruction is on to equal one of the sessions re-derived for it exactly. The selection proofs a session carries name the query that selected its row, so only a request sharing that query can reproduce them: a scheduled clock must be built from the replay's own queries, and a genuine session selected by any other query is refused. Every other request on the session names the same calendar row through `require_scheduled_calendar_row`, and so the same boundaries; a session naming the records of two rows at once, which that binding alone admits, is refused as well. A refusal names what differs: the boundaries, the calendar records, or only the selection proofs. A clock session no reconstruction is on is not re-derived here. It is still stepped and checkpointed, so a warmup session without one appears in the run, but it is never priced or decided on: a decision, a trade, or a held mark on it is `INDETERMINATE` under the missing-bar rule above. Known residual: the engine never re-derives the boundaries of a realized clock, which an exploratory admission may evaluate. A lagged realized clock, whose local dates stay non-decreasing while each session carries a later session's UTC stamps, passes every issue 84 guard, and a decision can then fill at an open printed before its cutoff. Closing that residual is a follow-up issue; re-deriving a realized clock for promotion is issue 80.

**Amendment, issue 96 (the EXPLORATORY realized lane's trust boundary; owner ruling B together with A).** This closes the issue 84 known residual at the preparation boundary, and for the clock it supersedes the section 7.4 issue 80 statement that `build_evaluation_input_bundle` accepts a caller-supplied clock unverified. `build_evaluation_input_bundle` now takes `session_queries` and holds the clock to the one rule `verify_evaluation_input_bundle` applies, through the same `verify_session_clock` re-derivation rather than a second one: a realized clock is rebuilt from its session queries over the one M1d context the builder is handed and must equal that build exactly, so a clock differing in any session, boundary, authority record, proof, or limitation is refused as not matching its canonical re-derivation, and a realized clock without its session queries is refused. The lagged clock of the issue 95 review (DAY_0 on its own times, DAY_1 on DAY_2's, DAY_2 on DAY_3's, every session key and authority hash genuine) is therefore refused where it is built, as are invented authority hashes, a scheduled calendar row relabelled as realized, and a session added to, or omitted from, what the queries select. The caller still names the clock it expects, and the builder carries it once it is proven equal to its derivation, so a genuine clock builds a byte-identical bundle. `session_queries` defaults to `None` because, as in verification, a scheduled-reconstruction clock is re-derived only when its queries are supplied: the Alpaca bridge supplies none, and the lane gate re-derives the sessions its reconstructions sit on (issue 84). Which sessions the queries request is the caller's choice, exactly as for verification; complete request coverage is issue 101, a prerequisite for re-enabling the promotion lane. Trust boundary: in the EXPLORATORY realized lane trust enters at the preparation boundary, `build_evaluation_input_bundle` and `verify_evaluation_input_bundle`, and nowhere later. The engine does not re-derive a realized clock, in contrast with reconstructions, which its lane gate re-derives (issue 55) together with the clock sessions they sit on (issue 84). A bundle assembled directly, through `assemble_evaluation_input_bundle` or model construction, bypasses the preparation boundary and is test-only; no production path assembles one. The engine runs whatever such a bundle carries, a lagged realized clock included, and whatever evidence any exploratory run yields is exploratory and non-promotable (section 4.4). The engine is unchanged.

### 7.6 No False Halt Syntheses
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
The regular trading session close is NOT hardcoded to 16:00 ET:
- **Promotion Lane**: On scheduled or unscheduled early-close sessions (e.g. 13:00 ET on Christmas Eve or day before July 4th), Phase 5 post-close decision occurs immediately after the proven realized close (`actual_close`). No artificial delay to 16:00 is enforced. Execution at Phase 2 occurs at the next proven realized `actual_open`.
- **Exploratory Lane (Scheduled Reconstruction)**: When realized history is unavailable, the clock derives the early close directly from `ScheduledSessionVersionV1` (e.g. 13:00 close). Phase 5 executes immediately after 13:00, carrying `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`.

### 8.2 Explicit Warmup Schedule and Transition
- **Strict Protocol Requirement**: Evaluation protocols require `warmup_session_count >= 1`. A warmup session count of zero is out of scope for M2 V1 and is rejected by `EvaluationProtocolV1` validation.
- The session clock derives `is_warmup: bool = (session_index < W)` using 0-based session index $0 \le \text{session\_index} < N$.
- Warmup observations populate strategy indicators and rolling state.
- **Sessions $0$ through $W - 2$** (the first $W - 1$ warmup sessions): Phase 5 does NOT invoke `strategy.decide()`; no target intents are staged.
- **Session $W - 1$ Post-Close** (the $W$-th warmup session): Phase 5 invokes `strategy.decide()` for the first time (`session_index >= W - 1`). Target positions are staged for execution at Session $W$ open.
- **Session $W$** (the $(W+1)$-th session, and first non-warmup trading session): Phase 2 (Open Execution) executes trades and fills for the first time.

---

## 9. Universe Admission and Historical Survivorship Rules

### 9.1 Sourced M1b Universe Authority
- Evaluator universe membership is derived session-by-session from `StructuralEligibilityResultV1` (replay under `AS_KNOWN` / `DECISION_INFORMATION`). This M1b replay applies to the promotion lane; exploratory evaluation is scoped by `ExploratoryCohortAuthorizationV1` instead (Section 7.1), which asserts experiment scope only and makes no universe-membership claim.
- `StructuralEligibilityClassification.ELIGIBLE` admits the security to the decision universe.
- `INELIGIBLE` or `INDETERMINATE` removes the security from eligibility.
- Indeterminate membership is never treated as eligible.

**Amendment, issue 85.** Admission at a decision cutoff reads only the as-known results known by that cutoff and evaluated at or before it, and within them only the answers at the security's latest instant across all its listings, ordered by `(evaluation_time, knowledge_cutoff)`. That order lets an answer about a later time outrank a later restatement about an earlier time. M1b answers every listing of a security at one instant and marks each non-primary listing `INELIGIBLE`, so at that instant a security is admitted when some listing is `ELIGIBLE`, none is `INDETERMINATE`, and no listing has conflicting answers. A listing the latest instant does not answer is not carried forward: an incomplete answer set fails closed, so a retired listing's old `ELIGIBLE` answer never keeps a security admitted, while an `INELIGIBLE` secondary listing answered beside an `ELIGIBLE` primary does not remove it, and a migration answered at one instant keeps it. Results under several universe definitions for one security are not distinguished by definition; conflicting answers across them admit nothing.

### 9.2 Liquidations Permitted for Excluded Positions
If a security currently held in the portfolio is removed from the universe (e.g. dropped from an index or becoming `INELIGIBLE`), the strategy is permitted to emit `target_quantity = 0` to liquidate the holding. Target quantities with `target_quantity > 0` (new entries or additions) for non-admitted securities are strictly rejected.

### 9.3 Anti-Survivorship Invariant
Today's constituent list (e.g. current S&P 500 or active Alpaca assets) cannot be projected backward as a historical universe. Any run attempting to project current symbols historically without dated interval eligibility fails validation.

---

## 10. Accounting Basis vs. Decision Data (Unadjusted Sourced Prices)

| Domain Layer | Data Basis | Source Authority | Purpose |
|---|---|---|---|
| **Strategy Decision Context (PROMOTION)** | Split-Normalized / Causal Views | Authentic M1d Decision Views (`AS_KNOWN`) | Point-in-time decision indicators, moving averages, signals. |
| **Strategy Decision Context (EXPLORATORY)** | Split-Normalized / Causal Views OR Source-Basis UNADJUSTED | Authentic M1d Decision Views when genuinely available, OR `ExploratoryReconstructedSessionObservationV1` (source-basis only, with retrospective limitations) | Exploratory screening, prototype indicators, signals. |
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
To guarantee bitwise replay determinism and prevent hash collisions across same-date distributions, `PendingCashClaimV1.claim_id` binds exact M1c occurrence and component identities. Claim identity is **source-scoped** and **date-independent**:
$$\text{claim\_id} = \text{content\_hash}(\text{source\_id}, \text{security\_id}, \text{action\_kind}, \text{occurrence\_id}, \text{component\_id})$$
Identity is source-scoped because M1c occurrence identity is source-scoped: `EconomicDeliveryGroupV1` keys a delivered occurrence on `source_id` together with `native_occurrence_id`, so two sources that reuse one native occurrence id describe two occurrences and must not collide onto a single claim. Identity is date-independent because M1c models payable and entitlement dates as revisable source claims (`EconomicDateFactV1` role `"payable"`, carried inside a revision envelope). A revisable date must never determine identity: putting `payable_session` in the preimage lets a payable-date revision mint a second `claim_id` for one economic entitlement, and both settled-claim guards are keyed on `claim_id`, so neither would fire and the same distribution would pay out twice. `entitlement_session` and `payable_session` are therefore **attributes** of the claim. A payable-date revision resolves by **supersession of the same identity** (`PortfolioAccountingKernel.supersede_claim`), never by recording a second claim, and a settled claim id remains unpayable no matter how its dates are later revised.

### 11.4 Cost Basis Relief and Realized PnL Formulas
When whole shares are sold ($\Delta q_{\text{sell}} > 0$):
$$\text{Cost Basis Sold} = \Delta q_{\text{sell}} \times \left(\frac{\text{current\_cost\_basis}}{\text{current\_quantity}}\right)$$
$$\text{Gross Realized PnL} = (\Delta q_{\text{sell}} \times P_{\text{fill}}) - \text{Cost Basis Sold}$$
$$\text{Net Realized PnL} = \text{Gross Realized PnL} - \text{Transaction Costs}$$

**Amendment, issue 88 (known bounds, from the #8 final acceptance review).**
- Staging accepts only an `int` share count, so a forged fractional, Decimal, float, or bool target is REJECTED rather than failing the run.
- Portfolio arithmetic runs in the pinned 34-digit decimal context. A partial sale's relieved and remaining cost basis therefore conserve the original basis to within that context's last digit, not beyond it.
- The cost model and protocol hashes are content hashes of their exact decimal spellings, so `1.0` and `1.00` name different identities. Two identities are never equal over different economics, but the same economics must be spelled canonically to share one.
- Pending claims are valued when staged, at `effective_on`, using the aggregate-sale cash-in-lieu rate and liquidation proceeds the source reports, which may be set later. They enter the net asset value a strategy sees before settlement. This is an accepted limitation of ex-post accounting, recorded for the M3 strategy-interface freeze, which decides whether pending claims are exposed apart from NAV.

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
   - `round_nearest`: `round_nearest` alone does not define tie-breaking semantics (bankers rounding vs half-up vs half-away-from-zero). M2 V1 directly supports integral, `round_down`, and `round_up`. For `round_nearest`, an exact interpreted tie-breaking rule artifact from source evidence is required; if unavailable, fail closed to `INDETERMINATE`.
   - `aggregate_sale_cash`: retain whole shares; convert fractional entitlement into a pending cash-in-lieu claim only after explicit subsequent M1c settlement/effect evidence proves the actual cash rate.
   - `fraction_issued`: unsupported by M2 V1 whole-share holding model; fail closed to `INDETERMINATE`.
   - `unknown`: fail closed to `INDETERMINATE`.

### 12.2 Staged Target Scaling Across Splits
When an overnight split occurs in Phase 1 (Pre-Open), pending staged target positions are translated using the exact same rational ratio:
$$\text{staged\_target}' = \text{staged\_target} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$$
If $\text{staged\_target}'$ is non-integral and cannot be resolved by an admitted fraction treatment, the run halts as `INDETERMINATE` due to unsupported corporate-action target translation. Targets are never arbitrarily rounded.

**Amendment, issue 81.** Translation applies to every share-mutating action, not only splits; a target left in pre-action units made the next open trade shares no decision asked for, and the run still read `COMPLETE`. Each action has its own rule:
- *Splits and `STOCK_DIVIDEND`.* The target is restated through the exact function its holding goes through: the same ratio, `ratio_meaning`, `FractionTreatmentV1`, and tie-breaking rule, with the rule above for a fraction the treatment cannot resolve. Any aggregate-sale residual is dropped, since a target is owed no cash in lieu. A stock dividend therefore multiplies the target by $1 + n/d$, and a split booked as a stock dividend translates identically. This holds with or without a holding behind the target.
- *`STOCK_ACQUISITION` and `MIXED_ACQUISITION`.* The predecessor target is mapped onto the acquirer through that same function, added to any acquirer target, and the predecessor target is set to 0. The mapping is allowed only for a hold or a sale: the mapped target may not exceed the whole acquirer shares the holding receives, which is 0 when nothing is held. A staged increase or entry would otherwise buy the acquirer at the open, a security no admitted decision named (section 6.4), so it is `INDETERMINATE`, as the issue 97 ruling (option A, section 13.1) confirms.
- *`SPINOFF`.* The child target is not a translation of the parent target. The parent target is unchanged, because parent shares are unchanged. The child target is credited with exactly the whole child shares the holding received, so the child is held rather than traded, and only when the parent carries a staged target, since otherwise no decision is staged. With no parent holding, no child shares are received and no child target changes.
- *`CASH_ACQUISITION`.* The target is set to 0 once the ended claim is proven, whether or not a holding stands behind it.

Two further rules:
- A cash or share acquisition of a security with no holding and no positive staged target (no target, or an explicit 0) finds no exposure, so its evidence, such as an unended claim status, cannot halt the run.
- A spin-off child or acquirer that is already held but has no staged target, while the source target is staged, is `INDETERMINATE`: treating its missing target as 0 would sell a holding no decision named.

A `LIQUIDATION` sets the staged target to 0 once its claim is proven `extinguished`, and leaves it unchanged when the claim is `continuing` (section 12.6).

### 12.3 Dividend and Due-Bill Entitlement Logic
M2 does NOT globally equate ex-date with entitlement:
- An economic receivable (`PendingCashClaimV1`) is created ONLY when M1c occurred effect evidence proves that the holding became legally entitled under the event's exact rule.
- **Ordinary Cash Dividends**: Entitlement aligns with the admitted ex-date rule.
- **Special and Due-Bill Distributions**: A due-bill redemption date alone does not encode the complete holder entitlement rule. M1c preserves `due_bill_start`, `due_bill_end`, `due_bill_redemption`, `ex`, `record`, `payable`, and `rule_reference`. For M2 V1:
  - Special distributions with an explicitly implemented and evidence-bound executable rule may be supported.
  - Using a generic shortcut like `due_bill_redemption_date == entitlement_date` is strictly prohibited.
  - If the exact retained due-bill rule cannot be deterministically interpreted under M2 V1 execution semantics, the run fails closed to `INDETERMINATE`.
- **Delivered Cash Settlement**: Settlement into available cash occurs in Phase 3 when `current_session.date >= claim.payable_session` and M1c delivered settlement evidence proves payment. Terms alone never credit cash.

**Amendment, issue 82.** Three rules, previously implicit, are now stated. The first two cover evidence dated off the clock; the third covers delivered cash that no claim matches.
- *Session windows.* The Phase 1 pass of each clock session owns every effect and entitlement dated after the previous clock session, up to and including its own date. A split, stock dividend, spin-off, acquisition, or liquidation dated on a weekend or a did-not-open day is therefore applied at the next pre-open, where nothing has traded since the prior close. It is never dropped, and never applied twice. The first clock session owns only its own date: the opening book is taken to reflect every earlier effect, including any entitlement it carries as a pending claim. The pass applies share actions by security id and record hash, never by time, and a window spans several dates when the clock skips days. So two or more share actions touching one security (as actor, or as a child or acquirer) in one window, on one date or several, and across all of the pass's outcomes (so a chain where one outcome's acquirer is another's subject counts), are `INDETERMINATE` for a book exposed to any security those actions touch, because their order is unproven. Exposure is judged against both the prior close's book and the book the pass leaves. The pass dispatches every share action, across all of its outcomes, before any cash distribution. Within a window, a cash distribution's pre-action share count is the prior close's. Its post-action count is the count after the security's own single continuing share action (a split, a reverse split, or a stock dividend), which re-denominates the prior close's holding. The ex-date rule entitles only the prior close's holdings, and M1c's share basis says only which share count the source divides its cash by, so two other post-action counts are `INDETERMINATE` for an exposed book (issue 83). One includes shares another outcome's share action delivered into the holding in the same window (a spin-off child, or an acquirer): whether the source counts those shares is unproven. The other belongs to a holding the security's own disposal or conversion removed in the same window: it has no post-action count at all, and dropping the distribution would be a guess. Either halt names the security, the distribution and the share action. A pre-action quote in either shape is owed on the prior close's holding. Known limitation (amended by issue 83): M2 V1 does not prove a same-date order from the effects' intraday instants, so a split at 10:00 followed by a cash acquisition at 15:00 of one date fails closed rather than applying in time order; proving that order is future work.
- *Ex-date entitlement.* Without due-bill evidence, a cash distribution (ordinary or special) vests at the pre-open of the first session on or after its M1c `ex` date, against the prior close's holdings. The record date is not read: a share bought at the ex-date open is on the register by a T+2 record date and is still not entitled. A distribution without an `ex` fact is `INDETERMINATE` whenever the book holds the security at a pre-open on or after the effect's effective date; before then it is not yet evidence about the book. An occurred effect must be effective on or before its `ex` date, since an entitlement never vests before the occurrence that proves it; otherwise the run is `INDETERMINATE`. A proven due-bill rule whose entitlement session is not a clock session is `INDETERMINATE`, because no M2 V1 rule says which other session those holders are counted on.
- *Unmatched delivered cash.* Delivered cash that matches no pending claim is never credited. For a security the book holds, or has a pending claim on, it is `INDETERMINATE` unless the evidence shows the book was never owed it. That requires exactly one occurred effect of the same source and occurrence, owing that exact component (a share component, for cash in lieu), whose entitlement has vested by the current session. An effect M1c places before its evidence window is never applied, so it qualifies only when its entitlement vested before the clock's first session. Such an effect that fails the occurred-effect proof, or duplicates another report of its occurrence, is dropped rather than halting the run: it proves nothing, so it explains nothing, and a delivery that needed it still halts for want of an explanation. That entitlement vested with no claim, so it paid other holders, such as those at the prior close of an ex date this book bought on. This proof relies on Phase 1 having run for every clock session in order.

Exposure throughout Phase 1 means a holding or a positive staged target. An explicit zero target on an unheld security trades nothing, so unsupported evidence about that security cannot halt the run. Exposure to evidence a pass cannot apply (an unsupported outcome, or an action kind with no M2 accounting rule) is judged against the book the pass leaves, so a security first held through an earlier dispatch of the same pass, such as a spin-off child, is exposed. An action kind with no M2 accounting rule is judged against the prior close's book as well (issue 83): a disposal in the same outcome may leave no holding behind, and the pass would otherwise realize PnL on shares whose fate the unmodelled action leaves unproven. It is judged in every pass whatever window its effective date falls in, so a later holding or staged buy of the security it acted on halts too. An unsupported outcome is never applied, and only a security's own outcome removes its holding or zeroes its target, so the book the pass leaves is exposed to it whenever the prior close's was.

### 12.4 Mergers and Acquisitions
- `CASH_ACQUISITION`: Target holding converts to cash claim upon effective date; settled when payment delivered.
- `STOCK_ACQUISITION`: Target holding converts to acquirer shares using exact ratio and `FractionTreatmentV1`.
- `MIXED_ACQUISITION`: Simultaneously applies stock conversion and cash claim.

### 12.5 Spin-offs (`SPINOFF`)
Creates a new `SecurityHoldingV1` in the child security using the exact distribution ratio and `FractionTreatmentV1`.
- **NAV Invariant**: If closing market prices for both parent and child are observable, portfolio NAV is marked normally. If tax cost-basis allocation percentages are unannounced, child holding cost basis is marked indeterminate; realized PnL upon eventual sale fails closed to `INDETERMINATE`, but daily portfolio NAV remains `COMPLETE`.

### 12.6 Terminations and Delistings
Delisting is NOT zero; bankruptcy is NOT zero. Terminal value requires explicit M1c liquidation terms or realized terminal distributions. If terminal proceeds are unknown, the evaluation outcome becomes `INDETERMINATE`. Zero cannot be fabricated.

**Amendment, issue 83.** Liquidation now reads the occurred effect's `claim_status`, and corporate-action disposals now realize PnL.
- *Extinguished liquidation.* A `LIQUIDATION` erases shares only when its claim is `extinguished`. The holding is removed for its proven cash claims, and any staged target is set to 0, so the open never re-buys the liquidated shares.
- *Continuing liquidation.* A liquidation whose claim is `continuing` is a partial liquidating distribution. Every share, its basis, and its target survive, and it is entitled, ordered after the pass's share actions, and reconciled exactly as a cash distribution under section 12.3 (its `ex` date governs). So an instalment quoted per post-action share in the same window as the final extinguishing liquidation, which removes the holding, is `INDETERMINATE`, while one quoted per pre-action share is owed on the prior close's holding. Changing no share count, it is not a share action for the issue 82 rule on windows that span several dates.
- *Unproven claim.* A `converted` or `unknown` claim status leaves it unknown whether any share survives, so it is `INDETERMINATE` for an exposed book. The same holds, as a pass-level rule, for the claim status M1c composes across all of an outcome's effects. When that is `unknown` (two liquidations at one instant with conflicting statuses, a continuing effect after an extinguishing one, or an effect whose own status is unknown), any effect of the outcome that commits in the pass's window halts a book exposed to any security the outcome touches, judged against both the prior close's book and the book the pass leaves. An effect commits in the window when its effective date is in it, or, for a cash distribution, when its entitlement date is. A cash distribution whose entitlement date cannot be resolved (one with no `ex` fact, for example) counts as committing in every window from the one it becomes effective, since it could vest in any of them; before it is effective it commits nothing. This covers splits, stock dividends, spin-offs, dividends, acquisitions and liquidations alike, even though each effect reads cleanly alone.
- *Disposal PnL.* A `CASH_ACQUISITION`, or an extinguished `LIQUIDATION`, is a disposal. The whole basis of the holding is relieved into realized gross and net PnL against the owed proceeds, in the pass of the first clock session on or after the effective date. The action fixes the price, so the gain or loss is realized then, although the proceeds are still receivable, and no transaction cost is charged. The realized-PnL identity therefore closes for every book whose corporate-action disposals are whole-holding extinguishments: cash + pending claims + remaining basis = initial cash + realized net PnL + distribution income. Mixed-acquisition cash legs, aggregate-sale cash in lieu, and liquidation instalments relieve no basis yet (#105), so a book with any of those does not close it.
- *Out of scope, unchanged.* A `MIXED_ACQUISITION` still carries the whole basis into the acquirer, with its cash leg treated as a claim rather than a partial disposal. An aggregate-sale cash-in-lieu fraction still relieves no basis.

Known limitation (#103): section 12.5's indeterminate spin-off child basis is not yet enforced. The child still enters at zero basis, so a later sale or corporate-action disposal of it overstates realized PnL, and the parent keeps its whole basis, so a later disposal of the parent understates its realized PnL by the same amount. Carrying an indeterminate basis from the spin-off to a later sale needs a basis-status field on `SecurityHoldingV1` (or an equivalent on `PortfolioStateV1`), and both are M2 contracts under the #50 freeze proposal. That decision is escalated rather than taken here.

---

## 13. Deterministic Fill Model (Atomic Plan-Then-Commit)

### 13.1 Next-Open Execution Policy
All target deltas execute at session $D+1$ regular session open.

**Amendment, issue 84.** The engine records the session whose close staged the pending decision, and Phase 2 refuses to execute that decision unless the execution session opens at or after the decision cutoff (the decision session's close) and carries a later local date. A refusal halts the run `INDETERMINATE` with an `indeterminate_execution` cause in `OPEN_EXECUTION`, whether or not the staged targets trade. On a single venue the clock guards of section 7.5 already make every next session qualify, and the check does not rely on them. Together they refuse decreasing-date inversions; neither detects a lagged clock whose local dates trail their UTC stamps (the section 7.5 residual, which issue 96 closes at the preparation boundary by re-deriving the realized clock in `build_evaluation_input_bundle`; the engine's pair check still cannot see it). On a legal multi-venue clock a same-date open on another venue is refused rather than read as the next open. Since the issue 97 ruling below, such a clock never reaches Phase 2, and this check stays as defense in depth.

**Amendment, issue 97 (owner ruling of 2026-09-24 on four fail-closed choices).** Each ruling can be reopened only by a new Decision Packet carrying contradicting repository evidence.
- *Same-date multi-venue clocks (option A).* `SessionEvaluatorEngine` refuses at construction, with `SameDateMultiVenueClockError` (a `ValueError`) from `refuse_same_date_multi_venue_clock` in `src/drift/evaluator/clock.py`, any clock that steps two sessions on one local date, such as XNYS on day D followed by a non-overlapping XNAS on day D. The refusal runs on the revalidated bundle before the lane is resolved, so it covers every lane and both clock modes. Dates are compared across venues. Keys are unique per venue, so every single-venue clock, and a venue change across dates, is unchanged. `SessionClockV1` and the clock builders still admit the shape (section 7.5); only its evaluation is refused. This supersedes the issue 84 runtime halt for this shape, and `require_next_open_execution` stays in Phase 2 as defense in depth.
- *A staged increase through a share acquisition (option A).* It stays `INDETERMINATE` (section 12.2, issue 81): a mapped target may not exceed the whole acquirer shares the holding receives, so no buy of the acquirer is carried forward.
- *The spin-off child's staged target.* The current rule is kept (section 12.2): the child target is credited with exactly the whole child shares the holding received, never the parent target times the ratio, so a staged parent exit keeps the child until the next decision and nothing buys a security no decision named.
- *Special cash distributions without due-bill facts.* The ex-date rule of section 12.3 (issue 82) is confirmed: such a special vests at the pre-open of its `ex` date against the prior close's holdings, exactly as an ordinary dividend.

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

Amendment, issue 46: in the EXPLORATORY scheduled-reconstruction lane, Phase 5 constructs `ExploratoryStrategyDecisionContextV1` instead, invokes `decide_exploratory(context)`, validates against the declared cohort, and records `ExploratoryStrategyDecisionTraceEventV1` (section 7.1 amendment). The realized lane is unchanged.

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
- `ExploratoryStrategyDecisionTraceEventV1` (issue 46: EXPLORATORY scheduled-reconstruction decisions only)
- `ExploratoryAccountingPriceTraceEventV1` (issue 54: EXPLORATORY reconstructed prices one open-execution or close-mark phase consumed)
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

**Amendment, issue 86.** Evidence outside the bundle changes results too, so `EvaluationRunIdentityV1` also binds `evaluator_evidence_hash`, the canonical identity of everything the engine consults beyond its hashed inputs: the book currency, and every `SessionEvaluatorEvidence` member, namely listing role, termination, and lifecycle records, economic outcome records, tie-breaking, due-bill, and cash-in-lieu registries, and the exploratory cohort and replay (each collection by its sorted member content hashes, each replay context by its M1d context hash). The engine refuses a run identity that does not name the evidence it consults or the strategy that runs, and refuses to be built unless the economic outcome records it is handed match the bundle's declared resolutions exactly, so a declared corporate action can never be read as no action by omission. `execute_experiment_run` refuses a specification whose dataset is not the run identity's bundle, or whose running strategy is not the one the identity names.

**Amendment, issue 63 (stage 1 of the Q6 ruling on #62).** The M1d evidence identity that every M1d normalization, action-session, session-binding, session-generation, selection and usability record binds as `implementation_hash`, and that therefore reaches `input_bundle_hash`, is the versioned `m1d-evidence-v1` semantic attestation (`m1d_evidence_attestation_hash()` in `src/drift/domain/semantic_attestation.py`, returned by `m1d_implementation_hash()`), not the whole installed source inventory. An edit outside its declared closure, such as a comment in `drift/evaluator/engine.py`, no longer moves a source-basis bundle, admission, result or trace hash, and retained source-basis M1d results and schedule policies re-validate under later code. Per the Q6 ruling, code-version provenance is kept separate from this identity: the whole-tree inventory, `drift_source_inventory_hash()` (value-identical to the pre-#63 identity), is build and repository provenance. In an evaluation run it belongs only in `code_hash` (`EvaluationRunIdentityV1.code_version_hash`), outside runs only in the Alpaca bridge's collector provenance, and never in the bundle. No production runner binds it as `code_version_hash` yet; canonical runs must bind it before canonical M3 evidence is recorded (tracked as #109). #63 stage 2 must keep `drift_source_inventory_hash()` the whole-tree build and repository provenance accessor even if it changes the role of `economic_implementation_hash()`. Stage 2 is still pending: M1c identities are still whole-tree, so split-normalized evidence is the stage-2 residual (a retained split-normalized reference still refuses under later code, on the M1c validator identity) and every bundle member that carries M1c identities still moves on unrelated edits. Both stages must land before canonical M3 evidence is recorded. Historical M1d fixtures are unchanged and keep replaying under their original identity from their archived source commits.

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
ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION = "session-clock-reconstructed-from-scheduled-calendar-without-independent-realized-history"
ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION = (
    "strategy-inputs-retrospectively-reconstructed-from-audit-vintage-bars"
)
```

---

## 20. Promotion Lane Admission and Authentic M1e Gatekeeper

An admission gatekeeper operates outside the pure evaluator core, binding authentic M1e qualification evidence across both consumer purposes (`HISTORICAL_DECISION_INPUT` and `RETROSPECTIVE_AUDIT`).

In Task 1, `validate_m1e_promotion_evidence` validates the M1e qualification artifacts and `QualifiedSourceHandoffV1` objects against `PromotionEvaluationAdmissionV1`. Task 2 is internally sequenced for implementation: slice 2A delivers the exploratory cohort authorization, exploratory reconstruction policy/fields/observation, and the realized/scheduled session-clock contracts and builders; slice 2B then delivers the immutable `EvaluationInputBundleV1`, replay-bound preparation, admission-to-bundle gates, and the deterministic evaluation-run identity. In Task 2B, `validate_promotion_admission` composes the Task 1 evidence check with `EvaluationInputBundleV1` structural anti-laundering validation.

**Amendment, issues 31 and 34 (supersedes this section where they conflict).** Adversarial review found that `EvaluationInputBundleV1.source_snapshot_hash` is an unverified self-declaration: views can be materialized through genuine M1d replay over a resolution context entirely unrelated to the qualified snapshot the bundle names, and the gate as originally specified admits it. Replay-boundness was proven; provenance was not. The specification itself contained the gap, so the API is changed rather than preserved.

`src/drift/domain/replay_provenance.py` adds the proof-bearing chain: `ReplayContextIdentityV1` (deterministic identity derived from an `M1dResolutionContext` by pure function, with the context itself unmodified), `SnapshotBindingEntryV1`, `QualifiedReplayContextV1` (a context identity bound to a `RealSourceSnapshotV1` by a retained, canonically sorted containment witness plus its digest), and `BundleProvenanceProofV1` (`proof_version = "m2-bundle-provenance-v1"`).

Binding is total, not sampled: every artifact a context supplies appears exactly once in the witness, every witness entry resolves to a real snapshot replay input entry that attests that artifact, and `snapshot_binding_proof_hash` is recomputed over the sorted witness so a tampered witness cannot keep a stale digest. `component_hashes` covers all six authority-bearing classes (decision views, accounting views, structural eligibility, economic outcomes, security and listing identity, session-clock authority); a bundle member absent from the proof fails closed.

Minting is split from validation. `mint_bundle_provenance_proof` runs replay verification once and emits the proof; `validate_promotion_admission` gains a required `proof` parameter and revalidates cheaply and fail-closed, with no full M1d replay inside admission. `PromotionEvaluationAdmissionV1` gains `provenance_proof_hash`. `EvaluationInputBundleV1` gains nothing, so the hash graph stays acyclic: the proof references the bundle, never the reverse. The exploratory lane is unaffected; an unqualified context stays constructible and usable, and the wrapper is required only where a promotion-grade claim is made.

**Second amendment, issue 31 reopened (supersedes the paragraph above where they conflict).** A required `proof` parameter alone was not sufficient, and the residual recorded when issue 31 was first closed rested on a cost argument that does not hold. The gate validated `proof.proof_hash`, `proof.bundle_hash`, `proof.source_snapshot_hash` and component coverage, but never read `proof.qualified_context_hash`, and had no parameter through which a `QualifiedReplayContextV1` or a `RealSourceSnapshotV1` could reach it. A hand-constructed qualified replay context naming a foreign snapshot, over a real context identity and with invented `snapshot_entry_hash` values, is fully valid under its own contract, because proving the containment witness requires the snapshot and the model never sees one. Such a context passed `mint_bundle_provenance_proof` and the gate admitted the result. The stated justification was that the ruling forbade M1d replay inside admission; `verify_snapshot_binding` performs no M1d replay at all, only `content_hash` recomputation and dictionary lookups over `snapshot.replay_inputs`, so the cost constraint never applied to the check that closes the gap.

`validate_promotion_admission` therefore requires `qualified_context: QualifiedReplayContextV1` and `snapshot: RealSourceSnapshotV1` alongside `proof`, and adds three fail-closed checks: `qualified_context.qualified_hash == proof.qualified_context_hash`; `qualified_context.source_snapshot_hash == bundle.source_snapshot_hash`; and `verify_snapshot_binding(qualified=qualified_context, snapshot=snapshot)`. The intermediate signature that took a proof without the evidence behind it is not preserved for compatibility. The pure-assembly helper becomes module-private as `_build_bundle_provenance_proof`, so the module boundary rather than a docstring enforces that production reaches a proof only through minting.

**Amendment, issue 80 (snapshot, purpose and context identity binding; supersedes the paragraphs above where they conflict).** `verify_snapshot_binding` compared the declared `snapshot_hash` and never recomputed it, so a snapshot object that kept the qualified hash while attesting another corpus was admitted. It, `bind_context_identity_to_snapshot`, and the public `verify_snapshot_binding_purpose` each require `real_source_snapshot_hash(snapshot) == snapshot.snapshot_hash` before anything else. `verify_snapshot_binding` also applies the binder's own ambiguity rule and refuses a witnessed artifact that the snapshot attests more than once; before, a witness built by hand could choose among an artifact's entries, for example the decision-purpose one, and pass the re-audit of a context the sanctioned binder refuses to qualify. Witness entries were matched by content hash alone, so decision evidence attested only as retrospective-audit input, under a foreign profile, in a snapshot of a foreign profile set, was admitted. `validate_promotion_admission` now also requires `snapshot.profile_set_hash == admission.m1e_profile_set_hash`; both the decision and the audit profile hash in `snapshot.authorized_profile_hashes`; and, through `verify_snapshot_binding_purpose`, every witnessed snapshot entry, each one and not only the first, to attest its artifact as `HISTORICAL_DECISION_INPUT` under the decision profile when the bundle carries decision views, and as `RETROSPECTIVE_AUDIT` under the audit profile when it carries accounting views. These are hashing and lookups over the snapshot in hand, so admission still runs no replay. Known consequence, ruling requested: the frozen witness records one snapshot entry per artifact (a second entry for the same artifact is refused as ambiguous), and one M1d context backs both view classes, so a promotion bundle carrying both decision and accounting views cannot satisfy both clauses and fails closed until dual-purpose attestation of one context is decided. Since the gate also requires at least one decision view, a promotion bundle can currently carry decision views only, and therefore cannot trade: fills and marks price only from authorized accounting views, so any trade, or any held position to mark, halts `INDETERMINATE`. `ReplayContextIdentityV1` gains `schedule_generation_policy_hash`, so two contexts that name different supplied artifacts as the schedule policy no longer share an identity, and a qualification of one cannot mint for the other. The change is construction-additive but hash-changing: the field defaults to `None`, so every existing construction still validates, and it is covered by `identity_hash`, so every context identity hash, and every qualified context hash over one, changes.

**Amendment, issue 79 (the owner ruling of 2026-09-24, option 1; supersedes this section where it conflicts).** The engine never ran this gate: `validate_promotion_admission` had no production caller, and `SessionEvaluatorEngine` accepted any `PromotionEvaluationAdmissionV1`, so a hand-made admission with invented M1e and proof hashes, over an exploratory bundle with no snapshot, sealed a `PromotionEvaluationResultV1` with `is_promotion_grade_evidence=True`, and `execute_experiment_run` recorded it as `lane=promotion`. The promotion lane is therefore **disabled**, and M2 closes with it disabled. Every `PromotionEvaluationAdmissionV1`, a fully genuine one that this gate admits included, is refused with `PromotionLaneDisabledError` (a `DriftError` and a `ValueError`, defined in `src/drift/evaluator/engine.py`) at four enforcement points: engine construction, first and before any other processing, reading the admission alone (and again on the revalidated admission); the start of `SessionEvaluatorEngine.run`; the result sealing site, which no longer seals a promotion result, so no production path can yield one; and `execute_experiment_run`, which refuses a promotion admission before running and a promotion result before recording, so no M0 experiment run and no audit event records `lane=promotion`. The runner trusts no object an engine returns (the PR 120 review): it refuses anything naming the promotion lane or whose `is_promotion_grade_evidence` is not exactly `False`, rebuilds the artifacts through canonical JSON (not a python-mode dump, which keeps subclassed leaves, see issue 123), refuses the rebuilt result in turn, and records only from the rebuilt objects; a `PromotionLaneDisabledError` raised inside the run propagates instead of being recorded as a `FAILED` run, and `summary_metrics_payload` refuses a promotion result as well. Exploratory runs are byte-identical. This is a deliberate fail-closed state, not a deletion: the promotion architecture stays, including this gate, `mint_bundle_provenance_proof`, `verify_evaluation_input_bundle`, the admission and result types, and their gate-level tests, which keep exercising the gate directly. A `PromotionEvaluationResultV1` still validates on its own over an exploratory trace (finding F9), because a result binds its trace by hash only; closing that needs cross-object data, so it stays prerequisite P9. Re-enabling the lane requires every prerequisite tracked in issue 115, each implemented with independent adversarial review, and a fresh owner decision.

**Authoritative landing corrections** (superseding the illustrative pseudocode below): handoff integrity is `qualified_source_handoff_hash(handoff) == handoff.handoff_hash`, and the admission binds `decision_handoff.handoff_hash` / `audit_handoff.handoff_hash` exactly (`handoff_hash` is SELF-EXCLUDING; a whole-object `content_hash(handoff)` would include that field and must never be bound). For positive M1e evidence, every one of the 12 final dimension results in BOTH purpose reports must be `REACHED`, carry evidence, and match the owning report purpose; only profile-critical dimensions must additionally `PASS` with `admitted_purpose=True` (a non-critical reached `PARTIAL` is permitted); a positive completion must not carry `blocking_dimensions` or `blocking_evidence_hashes`.

```python
def validate_m1e_promotion_evidence(
    admission: PromotionEvaluationAdmissionV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
) -> None:
    """Verify promotion admission against authentic M1e qualification evidence across both purposes."""
    if admission.lane != "promotion":
        raise ValueError("admission must belong to promotion lane")
    if completion.completion_kind != M1eCompletionKind.COMPLETED_POSITIVE:
        raise ValueError("promotion requires positive M1e completion")
    if content_hash(completion) != admission.m1e_completion_record_hash:
        raise ValueError("completion record hash mismatch with admission")
    if content_hash(profile_set) != admission.m1e_profile_set_hash:
        raise ValueError("pilot profile set hash mismatch with admission")
    if completion.profile_set_hash != admission.m1e_profile_set_hash:
        raise ValueError("completion record profile set binding mismatch")

    # Decision profile and report checks
    if decision_profile.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision profile must have historical_decision_input purpose")
    if decision_profile not in profile_set.profiles:
        raise ValueError("decision profile is not a member of bound profile set")
    dec_prof_hash = qualification_profile_hash(decision_profile)
    if decision_report.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision report must have historical_decision_input purpose")
    if decision_report.target.profile_hash != dec_prof_hash:
        raise ValueError("decision report target profile hash mismatch")
    if decision_report not in completion.purpose_reports:
        raise ValueError("decision report is not bound in completion record")

    # Audit profile and report checks
    if audit_profile.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit profile must have retrospective_audit purpose")
    if audit_profile not in profile_set.profiles:
        raise ValueError("audit profile is not a member of bound profile set")
    audit_prof_hash = qualification_profile_hash(audit_profile)
    if audit_report.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit report must have retrospective_audit purpose")
    if audit_report.target.profile_hash != audit_prof_hash:
        raise ValueError("audit report target profile hash mismatch")
    if audit_report not in completion.purpose_reports:
        raise ValueError("audit report is not bound in completion record")

    # Purpose states checks
    dec_state = next(
        (
            s
            for s in completion.purpose_states
            if s.purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT
        ),
        None,
    )
    if dec_state is None:
        raise ValueError("missing historical_decision_input purpose state")
    if dec_state.profile_hash != dec_prof_hash:
        raise ValueError("decision purpose state profile hash mismatch")
    if dec_state.stage != PilotStage.COMPLETED_POSITIVE:
        raise ValueError("decision purpose state not completed_positive")
    if dec_state.terminal_blocker is not None:
        raise ValueError("decision purpose state has terminal blocker")

    audit_state = next(
        (
            s
            for s in completion.purpose_states
            if s.purpose == ConsumerPurpose.RETROSPECTIVE_AUDIT
        ),
        None,
    )
    if audit_state is None:
        raise ValueError("missing retrospective_audit purpose state")
    if audit_state.profile_hash != audit_prof_hash:
        raise ValueError("audit purpose state profile hash mismatch")
    if audit_state.stage != PilotStage.COMPLETED_POSITIVE:
        raise ValueError("audit purpose state not completed_positive")
    if audit_state.terminal_blocker is not None:
        raise ValueError("audit purpose state has terminal blocker")

    # Shared snapshot checks across both reports
    if (
        not decision_report.target.snapshot_hash
        or not audit_report.target.snapshot_hash
    ):
        raise ValueError("reports must have non-null snapshot hashes")
    if decision_report.target.snapshot_hash != audit_report.target.snapshot_hash:
        raise ValueError(
            "decision and audit reports must reference identical snapshot hash"
        )
    shared_snapshot = decision_report.target.snapshot_hash

    # QualifiedSourceHandoffV1 checks
    if qualified_source_handoff_hash(decision_handoff) != decision_handoff.handoff_hash:
        raise ValueError("inconsistent decision handoff hash")
    if decision_handoff.handoff_hash != admission.decision_handoff_hash:
        raise ValueError("decision handoff hash mismatch with admission")
    if decision_handoff.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision handoff purpose mismatch")
    if decision_handoff.profile_hash != dec_prof_hash:
        raise ValueError("decision handoff profile hash mismatch")
    if decision_handoff.report_hash != content_hash(decision_report):
        raise ValueError("decision handoff report hash mismatch")
    if decision_handoff.target_hash != content_hash(decision_report.target):
        raise ValueError("decision handoff target hash mismatch")
    if decision_handoff.snapshot_hash != shared_snapshot:
        raise ValueError("decision handoff snapshot hash mismatch")
    if decision_handoff.environment_closure_hash is None:
        raise ValueError("decision handoff missing environment closure hash")
    if decision_handoff.replay_authorization_hash is None:
        raise ValueError("decision handoff missing replay authorization hash")

    if qualified_source_handoff_hash(audit_handoff) != audit_handoff.handoff_hash:
        raise ValueError("inconsistent audit handoff hash")
    if audit_handoff.handoff_hash != admission.audit_handoff_hash:
        raise ValueError("audit handoff hash mismatch with admission")
    if audit_handoff.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit handoff purpose mismatch")
    if audit_handoff.profile_hash != audit_prof_hash:
        raise ValueError("audit handoff profile hash mismatch")
    if audit_handoff.report_hash != content_hash(audit_report):
        raise ValueError("audit handoff report hash mismatch")
    if audit_handoff.target_hash != content_hash(audit_report.target):
        raise ValueError("audit handoff target hash mismatch")
    if audit_handoff.snapshot_hash != shared_snapshot:
        raise ValueError("audit handoff snapshot hash mismatch")
    if audit_handoff.environment_closure_hash is None:
        raise ValueError("audit handoff missing environment closure hash")
    if audit_handoff.replay_authorization_hash is None:
        raise ValueError("audit handoff missing replay authorization hash")

    # Check all 12 dimensions in both reports
    for report, profile in (
        (decision_report, decision_profile),
        (audit_report, audit_profile),
    ):
        results_by_dim = {res.dimension: res for res in report.results}
        if len(results_by_dim) != 12 or set(results_by_dim.keys()) != set(
            QualificationDimension
        ):
            raise ValueError(
                f"report for {profile.purpose} must contain all 12 qualification dimensions"
            )
        for crit_dim in profile.critical_dimensions:
            res = results_by_dim.get(crit_dim)
            if res is None:
                raise ValueError(
                    f"critical dimension {crit_dim} missing from {profile.purpose} report"
                )
            if res.status != QualificationStatus.PASS:
                raise ValueError(
                    f"critical dimension {crit_dim} did not PASS in {profile.purpose} report"
                )
            if res.reachability != ExecutionReachability.REACHED:
                raise ValueError(
                    f"critical dimension {crit_dim} was not REACHED in {profile.purpose} report"
                )
            if not res.admitted_purpose:
                raise ValueError(
                    f"critical dimension {crit_dim} did not admit {profile.purpose}"
                )


def validate_promotion_admission(
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
    proof: BundleProvenanceProofV1,
    qualified_context: QualifiedReplayContextV1,
    snapshot: RealSourceSnapshotV1,
) -> None:
    """Full promotion admission validator composing M1e evidence verification with bundle anti-laundering and provenance-proof gates."""
    validate_m1e_promotion_evidence(
        admission=admission,
        profile_set=profile_set,
        completion=completion,
        decision_profile=decision_profile,
        audit_profile=audit_profile,
        decision_report=decision_report,
        audit_report=audit_report,
        decision_handoff=decision_handoff,
        audit_handoff=audit_handoff,
    )

    # Input bundle and snapshot checks
    if bundle.bundle_hash != admission.input_bundle_hash:
        raise ValueError("input bundle hash mismatch with admission")
    if bundle.source_snapshot_hash != decision_handoff.snapshot_hash:
        raise ValueError("input bundle snapshot mismatch with promotion admission")

    # Provenance chain, validated cheaply and fail-closed (issues 31, 34)
    if proof.proof_hash != bundle_provenance_proof_hash(proof):
        raise ValueError("inconsistent provenance proof hash")
    if proof.bundle_hash != bundle.bundle_hash:
        raise ValueError("provenance proof bundle hash mismatch")
    if proof.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError("provenance proof snapshot mismatch")

    # Provenance evidence, re-verified rather than named (issue 31 reopened).
    # All hashing and dictionary lookups: no M1d replay runs here.
    if proof.qualified_context_hash != qualified_context.qualified_hash:
        raise ValueError("provenance proof qualified context mismatch")
    if qualified_context.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError("qualified replay context snapshot mismatch with bundle")
    verify_snapshot_binding(qualified=qualified_context, snapshot=snapshot)

    validate_bundle_component_coverage(proof=proof, bundle=bundle)
    if admission.provenance_proof_hash != proof.proof_hash:
        raise ValueError("admission is not bound to the provenance proof")

    # Structural anti-laundering checks on input bundle
    if bundle.has_exploratory_reconstructions:
        raise ValueError(
            "promotion evaluation cannot consume exploratory reconstructed inputs"
        )
    if bundle.session_clock.mode != "realized_session_authority":
        raise ValueError(
            "promotion evaluation requires authentic realized session authority"
        )
    if any(
        session.authority != "realized" for session in bundle.session_clock.sessions
    ):
        raise ValueError(
            "promotion evaluation requires realized session evidence for every session"
        )
```

---

## 21. Alpaca Development Bridge and Acquisition Isolation

The Alpaca development bridge is an operational data preparation utility that executes strictly outside the evaluator core.

### 21.1 Layered Data Pipeline
The bridge follows a strict layered pipeline preserving provenance:
```
Alpaca REST API Responses
  |
  +--> 1. Retain Exact Native Response Bytes in private storage outside Git
  +--> 2. Generate AcquisitionReceiptV1 and Dataset Manifest
  +--> 3. Map native payloads to standard Drift source records (M1b/M1c/M1d)
  +--> 4. Validate datasets via Drift public validators (DatasetValidationDecisionV2)
  +--> 5. Execute standard M1b/M1c/M1d selection/normalization functions
  +--> 6. Reconstruct ExploratoryReconstructedSessionObservationV1 (source-basis, with explicit limitations)
  +--> 7. Emit EvaluationInputBundleV1 for evaluator core
```

### 21.2 Strict Layering Prohibitions
- **NO Manual Derived Views**: The bridge must NEVER construct `DerivedObservationViewV1` manually from provider JSON. Views must be derived through existing M1d normalization routines.
- **NO Fake Realized Sessions**: Scheduled calendar rows must NEVER be converted into `RealizedSessionVersionV1`. The bridge produces `ScheduledSessionVersionV1` and operates under `scheduled_session_reconstruction`.
- **NO Invented Corporate Action Effects or Settlements**: Alpaca corporate actions records must be mapped conservatively:
  - If a record establishes terms only: map terms only.
  - If occurrence/effect semantics are explicitly supported: map the exact supported effect.
  - If delivered settlement cannot be proven: do NOT mint `EconomicSettlementVersionV1`. Missing settlements fail closed to `INDETERMINATE` if required for portfolio cash.
- **Quiet-Window Exploratory Smoke Run**: For the Task 8 smoke run, select a bounded cohort and date window with valid free SIP historical bars, scheduled calendar rows, and minimal corporate action complexity, verifying pipeline plumbing end-to-end. Full corporate action accounting is verified via pinned/synthetic fixtures in Tasks 3-7.

---

## 22. Adversarial Acceptance Test Matrix

The M2 implementation must pass the following explicit adversarial acceptance tests:

| Category | Invariant Tested | Attack Scenario / Input | Expected Result |
|---|---|---|---|
| **Causality** | Same-Bar Close Lookahead | Strategy requests execution at session D close using session D close price | Rejected by protocol validation. |
| **Causality** | Post-Cutoff Observation Leakage | Observation with availability timestamp > decision cutoff passed to strategy | Filtered out or triggers fail-closed error. |
| **Causality** | Early-Close Realized Timing | Session closes at 13:00; strategy decision evaluated after 13:00 | Accepted; uses actual realized close, not 16:00. |
| **Causality** | Future Corporate Action Knowledge | Strategy context contains corporate action announced after decision date | Rejected by M1c causal selection query. |
| **Epistemic Lanes** | 2026 Downloaded Bar as Decision Ref | Alpaca 2022 bar downloaded in 2026 submitted as M1d `ObservationDecisionReferenceV1` | Rejected; cannot produce decision-role reference without vintage. |
| **Epistemic Lanes** | Reconstructed Observation in Promotion | `ExploratoryReconstructedSessionObservationV1` submitted to PROMOTION evaluation | Structural rejection; gatekeeper fails closed. |
| **Epistemic Lanes** | Reconstructed Observation in Exploratory | 2022 session reconstructed as `ExploratoryReconstructedSessionObservationV1` (source-basis) with retrospective limitations | Permitted in EXPLORATORY lane only, over the predeclared cohort. |
| **Universe** | Current Interpretation as As-Known | M1b `CURRENT_INTERPRETATION` submitted as `AS_KNOWN` in PROMOTION | Rejected; promotion requires authentic as-known authority. |
| **Universe** | Survivorship Bias | Current active asset list used as historical universe | Rejected; requires historical universe definition. |
| **Universe** | Indeterminate Eligibility | Security with `MembershipStatus.INDETERMINATE` admitted to trading | Rejected; indeterminate is not eligible. |
| **Universe** | Post-Delisting Liquidation | Strategy emits target=0 for held security dropped from universe | Permitted; exits non-admitted holding cleanly. |
| **Universe** | Listing Migration at Execution | Security changes primary listing before execution session open | Phase 2 resolves exact new historical listing; does not use stale listing. |
| **Clock Authority** | Scheduled Row as Realized Session | Alpaca scheduled calendar row passed as `RealizedSessionVersionV1` | Prohibited; scheduled rows cannot mint realized sessions. |
| **Clock Authority** | Scheduled Exploratory Early Close | Scheduled 13:00 close evaluated under `scheduled_session_reconstruction` on EXPLORATORY-only reconstructed decision evidence | Accepted; the exploratory decision executes post-close at the 13:00 scheduled close with explicit limitations, no `RealizedSessionVersionV1` is fabricated, and the result stays exploratory and non-promotable. |
| **Clock Authority** | Missing Bar on Scheduled Open | Scheduled session expected open, but required market bars missing | Fails closed to `INDETERMINATE`; does not infer halt. |
| **Replay Integrity** | View Hash vs M1d Replay | Self-consistent fabricated view without successful M1d replay | Bundle preparation rejects; requires exact M1d replay. |
| **Accounting** | Double-Counting Adjustment | Accounting configured with split-adjusted prices while applying M1c splits | Validation rejects adjusted accounting prices. |
| **Accounting** | Premature Dividend Settlement | Dividend cash credited to available cash on ex-date before payable date | Rejected; ex-date creates receivable, not cash. |
| **Accounting** | Generic Due-Bill Shortcut | Generic `due_bill_redemption_date == entitlement_date` applied to special dividend | Rejected; requires explicit executable rule, else `INDETERMINATE`. |
| **Accounting** | Round Nearest Without Rule | `round_nearest` applied without source tie-breaking rule artifact | Fails closed to `INDETERMINATE`. |
| **Accounting** | Terms-Only Corporate Action | Alpaca terms record without occurred effect or settlement | No portfolio cash/share mutation committed. |
| **Accounting** | Fabricated Delisting Recovery | Security delists without liquidation terms; accounting assumes zero or recovery | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Fractional Split Unknown Treatment | Reverse split yields non-integral shares with unknown fraction treatment | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Missing Close Forward-Fill | Held position has missing close price; evaluator forward-fills prior close | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Multiple Same-Date Cash Claims | Two dividends on same date share security ID and dates | Distinct claim IDs via M1c component/occurrence hash. |
| **Execution** | Close-for-Open Fallback | Missing open price replaced by prior or current close price | Execution fails closed to `INDETERMINATE`. |
| **Execution** | Negative Target Position | Strategy emits negative whole-share target quantity (short position) | Intent rejected; run classified as `REJECTED`. |
| **Execution** | Fractional Share Target | Strategy emits floating-point target quantity (e.g. 10.5 shares) | Intent rejected; whole shares only. |
| **Execution** | Unfunded Rebalance Shortfall | Target rebalance exceeds cash after planned sells | 0 fills committed; stepping halts; classified `REJECTED`. |
| **Execution** | Zero Warmup Session Count | Protocol declared with `warmup_session_count = 0` | Rejected by protocol validation; requires W >= 1. |
| **Gatekeeper** | Missing Audit Purpose Report | Promotion admission has decision report but lacks retrospective audit report | Rejected by gatekeeper; requires both purpose reports. |
| **Gatekeeper** | Audit Critical Dimension Failed | Decision report passes, but Retrospective Audit critical dimension fails | Rejected by gatekeeper. |
| **Gatekeeper** | Report Profile Hash Mismatch | `report.target.profile_hash` does not equal bound profile hash | Rejected by gatekeeper. |
| **Gatekeeper** | Profile Not in Profile Set | Profile is not a member of bound `PilotProfileSetV1.profiles` | Rejected by gatekeeper. |
| **Gatekeeper** | Fake PASS Report | Report has PASS but M1e completion record is NEGATIVE | Promotion admission rejected by gatekeeper. |
| **Gatekeeper** | Promotion Evidence Scope | Caller treats `PromotionEvaluationResultV1` as M10 strategy approval | Disallowed; M2 provides evidence, not approval. |
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
