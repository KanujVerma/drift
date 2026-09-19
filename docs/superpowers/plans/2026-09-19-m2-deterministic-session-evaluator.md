# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Drift M2: a deterministic, provider-neutral session-level evaluator and portfolio accounting kernel operating across two structurally distinct evidence lanes (`EXPLORATORY` and `PROMOTION`) with zero lookahead, unadjusted source-basis accounting, proof-carrying M1b-M1d integration, native M1c corporate action effect and settlement processing, atomic plan-then-commit execution, content-addressed execution traces, and strict anti-laundering enforcement.

**Architecture:** A single provider-neutral evaluator core consumes validated, proof-carrying `EvaluationInputBundleV1` artifacts and executes a 5-phase deterministic daily session schedule (Pre-Open Effects, Open Execution, Intrasession Effects, Close Mark, Post-Close Decision). Lane separation is structurally enforced at the type layer (`ExploratoryEvaluationAdmissionV1` / `ExploratoryEvaluationResultV1` vs `PromotionEvaluationAdmissionV1` / `PromotionEvaluationResultV1`). Economic holdings are keyed by `security_id` (UUID7), accounting uses source-basis unadjusted prices, and execution deltas are filled at the next realized regular session open via an atomic plan-then-commit rebalance. The Alpaca exploratory bridge is isolated in Task 8 as an offline intake script outside the evaluator core.

**Tech Stack:** Existing Python 3.14+, Pydantic (FrozenModel), pytest, Ruff, mypy, uv, and Python standard library only. Decimal arithmetic for all prices, cash balances, and fees. No new dependencies, database migrations, broker connections, or live trading capabilities.

**Execution Status:** Planning and architecture specification approved with externally adjudicated corrections. Implementation authorized task-by-task under this plan.

**Spec:** [M2 Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification](../specs/2026-09-19-m2-deterministic-session-evaluator-design.md), [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), and [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## Global Constraints

- **Workspace Boundary**: Work strictly in `/Users/kanuj/Documents/projects/drift`. Never touch external mirrors or unapproved local directories.
- **Repository Truth**: Canonical baseline is commit `ef24c2c` (and underlying verified Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
- **Protected Prior Milestones**: M0 through M1e Tasks 1-7 are complete and protected. Do not mutate persisted models, schemas, or fixtures in `src/drift/domain/experiments.py`, `strategies.py`, `securities.py`, `universes.py`, `observations.py`, or `qualification.py`. Add M2 evaluator contracts beside them.
- **Strict Two-Lane Anti-Upgrade Invariant**: Exploratory evaluation results can NEVER be upgraded, converted, or relabeled into promotion evidence. No constructor, helper, or mutable field may bridge the two lanes. Promotion strictly requires an independent, fresh evaluation run against verified M1e promotion-qualified data with positive completion (`M1eCompletionKind.COMPLETED_POSITIVE`).
- **Evidence Grade Only (No Strategy Promotion)**: M2 certifies evidence quality (`is_promotion_grade_evidence: bool`); it does NOT decide strategy promotion, which belongs exclusively to M10 and M11. Never expose `is_promotable=True`.
- **Acyclic Admission Hashing**: The dependency graph is strictly acyclic: Market Data -> `EvaluationInputBundleV1` (`bundle_hash`) -> `EvaluationAdmissionV1` (`input_bundle_hash = bundle_hash`) -> `EvaluationRunIdentity`. `EvaluationInputBundleV1` does NOT hold a reference to `admission_hash`.
- **Proof-Carrying Input Bundles**: The evaluator must not trust flat self-authored copies. Bundles cryptographically bind authoritative M1b structural eligibility, M1c outcome resolution, and M1d observation view proof hashes.
- **Zero Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden across all code, docstrings, markdown documents, and commit messages. Always use the ASCII hyphen (U+002D).
- **Offline / Network-Free Core**: The evaluator core and all standard unit test suites must run 100% offline with zero network access or socket activity.
- **Decimal Precision**: All currency balances, prices, execution marks, dividends, fees, and slippage calculations must use Python `Decimal` or exact integer strings. Floating-point arithmetic for portfolio accounting is strictly forbidden.
- **Realized Session Clock**: Session boundaries are driven by authenticated M1d realized session open/close timestamps (`actual_open`, `actual_close`), correctly handling variable session hours (early closes). Post-close decisions occur after actual realized close.
- **Atomic Plan-Then-Commit Execution**: Sells and buys in an open rebalance are verified as 100% funded before any fills are committed. If unfunded, 0 fills are committed, `FillRejectionTraceEventV1` is emitted, and the run is classified `REJECTED`.
- **No Fraction Truncation**: Share conversions must never use Python `int(...)` truncation. Compute exact rational entitlements and apply explicit M1c `FractionTreatmentV1` (e.g. `aggregate_sale_cash`, `round_down`, `round_up`). Unknown or unsupported fraction treatments fail closed to `INDETERMINATE`.
- **Due-Bill and Legal Entitlement**: Dividends create receivables only when M1c occurred effect evidence proves legal entitlement under the event's exact rule, correctly handling due-bill redemptions.
- **Missingness Fail-Closed**: Missing prices, unquantified corporate actions, or unprovable outcomes fail closed to `INDETERMINATE` and cleanly halt session stepping. Never forward-fill close marks, substitute close for open, or synthesize zero.
- **No False Halt Syntheses**: Missing halt telemetry remains `UNKNOWN`. Never synthesize `not_halted` by default.
- **Deterministic Replay Identity**: Evaluator results contain only deterministic values derived from inputs and historical evidence. No random UUID7s or wall-clock timestamps inside deterministic result artifacts. Operational metadata belong to M0 `ExperimentRun`.
- **Secret Handling**: Alpaca credentials reside exclusively in `.env` (mode 0600, gitignored). Never print, log, commit, or pass credentials to the evaluator core.
- **TDD Workflow**: Every task requires meaningful RED tests confirming failure before implementation, followed by GREEN acceptance, focused verification, adversarial review, full gate, and Checkpoint commit.

---

## Task Decomposition Overview

- **Task 1: Evaluation Lane Contracts, Protocol Definitions, Cost Models, and Authentic M1e Gatekeeper**
  Establish immutable admission types, protocol parameters, versioned cost/slippage models, canonical Alpaca limitation constants, and the external positive M1e completion gatekeeper.
- **Task 2: Proof-Carrying Evaluation Input Bundle, Session Clock Authority, and Deterministic Replay Identity**
  Build the proof-carrying input bundle contract (with exploratory reconstruction wrapping, M1d replay preparation, and clock authority modes), session clock (realized vs scheduled early-close aware), and canonical replay hashing without wall-clock contamination.
- **Task 3: Portfolio State, Cash Accounting, Whole-Share Positions, and Deterministic Claims Kernel**
  Implement long-only whole-share holdings, USD cash accounting, deterministic occurrence-bound claims, weekend/holiday settlements with delivered claim ID proof, and exact cost basis relief formulas.
- **Task 4: First-Class M1c Corporate Action and Economic Outcome Accounting**
  Process forward/reverse splits, staged target split-scaling, exact `FractionTreatmentV1` handling with tie-breaking rules, conservative due-bill dividend rules (no generic shortcuts), mergers, spin-offs, and liquidations natively from M1c facts.
- **Task 5: Target-Position Strategy Boundary, Atomic Next-Open Fill Engine, and Cost Application**
  Implement runtime strategy interface targeting economic securities, Phase 2 dynamic primary execution listing resolution, explicit complete target set omission rule, and atomic solvency-checked execution.
- **Task 6: Deterministic Session Evaluator Engine, Canonical Trace Generation, and M0 Integration**
  Assemble the 5-phase session evaluator loop, content-addressed trace logger, fatal indeterminacy and shortfall halting, complete result models without random/wall-clock fields, and M0 ExperimentRun binding.
- **Task 7: Comprehensive Adversarial Verification, Anti-Laundering Invariants, and Closed-World Replay Testing**
  Execute the complete 28-case adversarial matrix across causality, epistemic lanes, universe, clock authority, replay integrity, accounting, execution, gatekeeper, replay, and provider boundary invariants.
- **Task 8: Bounded Alpaca Development Bridge and End-to-End Exploratory Smoke Validation**
  Build the layered offline Alpaca intake adapter (native bytes -> receipt -> mapping -> source contracts -> validators -> resolvers -> exploratory wrapper -> input bundle), bind canonical limitation constants, and execute a quiet-window exploratory smoke run.

---

## Task 1: Evaluation Lane Contracts, Protocol Definitions, Cost Models, and Authentic M1e Gatekeeper

### 1. Objective
Define the fundamental M2 domain contracts for evaluation lane admission (`ExploratoryEvaluationAdmissionV1` vs `PromotionEvaluationAdmissionV1`), evaluation protocol configuration (`EvaluationProtocolV1`), versioned transaction cost/slippage parameters (`EvaluationCostModelV1`), canonical Alpaca limitation constants, and the external positive M1e completion gatekeeper function (`validate_promotion_admission`).

### 2. Exact Files Expected
- `src/drift/domain/evaluator_lanes.py`
- `src/drift/domain/evaluator_protocol.py`
- `src/drift/domain/evaluator_costs.py`
- `src/drift/evaluator/admission.py`
- `tests/unit/test_evaluator_lanes.py`
- `tests/unit/test_evaluator_protocol.py`
- `tests/unit/test_evaluator_costs.py`
- `tests/unit/test_evaluator_admission_gatekeeper.py`

### 3. Contracts and Interfaces
- Canonical Alpaca limitation constants:
  - `ALPACA_LIMITATION_TRUNCATED_CA = "corporate-action-mutation-replay-truncated-to-approx-72-days"`
  - `ALPACA_LIMITATION_UNVERSIONED_BARS = "derived-bars-unversioned-without-provider-vintages"`
  - `ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"`
  - `ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"`
  - `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION = "session-clock-reconstructed-from-scheduled-calendar-without-independent-realized-history"`
  - `ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION = "strategy-inputs-retrospectively-reconstructed-from-audit-vintage-bars"`
- `ExploratoryEvaluationAdmissionV1(FrozenModel)`:
  - `lane: Literal["exploratory"] = "exploratory"`
  - `development_source_profile_hash: SHA256Hash`
  - `input_bundle_hash: SHA256Hash`
  - `acknowledged_limitations: tuple[NonBlankStr, ...]` (must not be empty)
  - `admission_hash: SHA256Hash` (self-excluding canonical hash; no wall-clock timestamps or duplicate IDs)
- `PromotionEvaluationAdmissionV1(FrozenModel)`:
  - `lane: Literal["promotion"] = "promotion"`
  - `m1e_completion_record_hash: SHA256Hash`
  - `m1e_profile_set_hash: SHA256Hash`
  - `m1e_decision_profile_hash: SHA256Hash`
  - `m1e_audit_profile_hash: SHA256Hash`
  - `m1e_decision_report_hash: SHA256Hash`
  - `m1e_audit_report_hash: SHA256Hash`
  - `m1e_snapshot_hash: SHA256Hash`
  - `input_bundle_hash: SHA256Hash`
  - `admission_hash: SHA256Hash` (self-excluding canonical hash; no wall-clock timestamps or duplicate IDs)
- `EvaluationAdmissionV1 = Annotated[ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1, Field(discriminator="lane")]`
- `validate_promotion_admission(admission, bundle, profile_set, completion, decision_profile, audit_profile, decision_report, audit_report)`:
  - Verifies `admission.lane == "promotion"`.
  - Verifies `completion.completion_kind == M1eCompletionKind.COMPLETED_POSITIVE`.
  - Verifies `content_hash(completion) == admission.m1e_completion_record_hash`.
  - Verifies `content_hash(profile_set) == admission.m1e_profile_set_hash`.
  - Verifies `completion.profile_set_hash == admission.m1e_profile_set_hash`.
  - Verifies decision profile: in `profile_set.profiles`, `purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT`, hash matches `admission.m1e_decision_profile_hash`.
  - Verifies decision report: in `completion.purpose_reports`, `purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT`, hash matches `admission.m1e_decision_report_hash`, `target.profile_hash` matches decision profile.
  - Verifies audit profile: in `profile_set.profiles`, `purpose == ConsumerPurpose.RETROSPECTIVE_AUDIT`, hash matches `admission.m1e_audit_profile_hash`.
  - Verifies audit report: in `completion.purpose_reports`, `purpose == ConsumerPurpose.RETROSPECTIVE_AUDIT`, hash matches `admission.m1e_audit_report_hash`, `target.profile_hash` matches audit profile.
  - Verifies `bundle.bundle_hash == admission.input_bundle_hash`.
  - Verifies `bundle.source_snapshot_hash == admission.m1e_snapshot_hash == decision_report.target.snapshot_hash`.
  - Verifies structural anti-laundering: `bundle.has_exploratory_reconstructions is False` and `bundle.session_clock_mode == "realized_session_authority"`.
  - Verifies that all 12 dimensions are explicitly present in both reports (`len(results_by_dim) == 12 and set(results_by_dim.keys()) == set(QualificationDimension)`).
  - Verifies that for every dimension in `decision_profile.critical_dimensions` and `audit_profile.critical_dimensions`:
    - `res.status == QualificationStatus.PASS`
    - `res.reachability == ExecutionReachability.REACHED`
    - `res.admitted_purpose is True`
- `EvaluationCostModelV1(FrozenModel)`:
  - `model_id: NonBlankStr`
  - `commission_per_share: Decimal` (must be >= 0)
  - `fixed_fee_per_order: Decimal` (must be >= 0)
  - `notional_fee_basis_points: Decimal` (must be >= 0)
  - `adverse_slippage_basis_points: Decimal` (must be >= 0)
  - `cost_model_hash: SHA256Hash`
- `EvaluationProtocolV1(FrozenModel)`:
  - `protocol_id: NonBlankStr`
  - `decision_clock: Literal["post_close_decision_next_open_execution"]`
  - `session_scope: Literal["regular"]`
  - `warmup_session_count: int` (must be >= 1; 0 is rejected by validation)
  - `initial_cash: Decimal` (must be > 0)
  - `protocol_hash: SHA256Hash`

### 4. RED Acceptance Criteria
- Unit tests fail initially because domain modules and admission gatekeeper do not exist.

### 5. GREEN Acceptance Criteria
- `ExploratoryEvaluationAdmissionV1` validates that `acknowledged_limitations` is non-empty.
- Self-excluding canonical hashing verifies `admission_hash`, `cost_model_hash`, and `protocol_hash`.
- `validate_promotion_admission` validates positive M1e completion and both purpose profiles/reports.
- `validate_promotion_admission` rejects any report where a critical dimension did not PASS, where an audit report is missing, or where exploratory inputs are present in the bundle.
- `EvaluationProtocolV1` rejects `warmup_session_count = 0`.
- Discriminator `lane` correctly deserializes either admission variant from JSON.
- `EvaluationCostModelV1` enforces non-negative Decimals and computes exact costs for sample orders.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_lanes.py tests/unit/test_evaluator_protocol.py tests/unit/test_evaluator_costs.py tests/unit/test_evaluator_admission_gatekeeper.py -v
```

### 7. Adversarial Test Cases
- Attempt to create `ExploratoryEvaluationAdmissionV1` with empty limitations -> ValueError.
- Attempt to mutate `admission_hash` without changing payload -> ValueError mismatch.
- Promotion admission pointing to an M1e completion that is `COMPLETED_NEGATIVE` -> ValueError.
- Critical dimension is `FAIL` while non-critical is `PASS` -> ValueError.
- Missing retrospective audit report in promotion admission -> ValueError.
- Protocol declared with `warmup_session_count = 0` -> ValueError.
- Bundle snapshot hash not matching promotion admission snapshot hash -> ValueError.

### 8. Review and Commit Boundary
- Independent review covering lane separation, gatekeeper verification, critical-dimension logic, and Decimal precision.
- Commit message: `feat: add M2 evaluation lane admission, cost models, and authentic M1e gatekeeper`
- Checkpoint execution.

---

## Task 2: Proof-Carrying Evaluation Input Bundle, Session Clock Authority, and Deterministic Replay Identity

### 1. Objective
Implement the proof-carrying `EvaluationInputBundleV1` contract (acyclic, snapshot-linked, cryptographically validated against M1b-M1d proof hashes, with first-class `ExploratoryReconstructedDecisionInputV1` support), M1d replay preparation via `materialize_observation_decision` and `materialize_observation_outcome`, the dual-mode session scheduler (`SessionClockV1`) supporting both `realized_session_authority` and `scheduled_session_reconstruction` (with early closes and warmup transitions), and canonical evaluation run replay hashing without wall-clock contamination.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_bundles.py`
- `src/drift/domain/evaluator_clock.py`
- `src/drift/evaluator/bundles.py`
- `tests/unit/test_evaluator_bundles.py`
- `tests/unit/test_evaluator_clock.py`

### 3. Contracts and Interfaces
- `SessionClockMode = Literal["realized_session_authority", "scheduled_session_reconstruction"]`
- `ExploratoryReconstructedDecisionInputV1(FrozenModel)`:
  - `reconstruction_id: SHA256Hash` (content-addressed hash over fields)
  - `underlying_observation_hash: SHA256Hash`
  - `historical_decision_session: date`
  - `reconstruction_policy: NonBlankStr`
  - `reconstruction_limitations: tuple[NonBlankStr, ...]`
  - `derived_view: DerivedObservationViewV1`
- `EvaluationInputBundleV1(FrozenModel)`:
  - `bundle_id: SHA256Hash` (content-addressed hash of bundle payload)
  - `evaluation_interval: TemporalIntervalClaimV1` (uses `.start` and `.end`)
  - `source_snapshot_hash: SHA256Hash | None = None`
  - `session_clock_mode: SessionClockMode = "realized_session_authority"`
  - `m1b_structural_eligibility_hashes: tuple[SHA256Hash, ...]`
  - `m1c_outcome_resolution_hashes: tuple[SHA256Hash, ...]`
  - `m1d_observation_view_hashes: tuple[SHA256Hash, ...]`
  - `m1d_realized_session_hashes: tuple[SHA256Hash, ...]`
  - `m1d_scheduled_session_hashes: tuple[SHA256Hash, ...]`
  - `security_identities: tuple[SecurityV1, ...]`
  - `listing_identities: tuple[ListingV1, ...]`
  - `scheduled_sessions: tuple[ScheduledSessionVersionV1, ...]`
  - `realized_sessions: tuple[RealizedSessionVersionV1, ...]`
  - `structural_eligibilities: tuple[StructuralEligibilityResultV1, ...]`
  - `economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...]`
  - `unadjusted_observation_views: tuple[DerivedObservationViewV1, ...]`
  - `decision_observation_views: tuple[DerivedObservationViewV1, ...]`
  - `exploratory_decision_inputs: tuple[ExploratoryReconstructedDecisionInputV1, ...] = ()`
  - `has_exploratory_reconstructions: bool = False`
  - `bundle_hash: SHA256Hash`
  - Validator: verifies that all included entities match their bound proof hashes and that `has_exploratory_reconstructions == bool(exploratory_decision_inputs)`.
- Replay Preparation and Verification Boundary (`src/drift/evaluator/bundles.py`):
  - `build_evaluation_input_bundle(...) -> EvaluationInputBundleV1`:
    - Replays M1d observation views through `materialize_observation_decision` and `materialize_observation_outcome` using Drift normalization routines rather than trusting local view self-hashes.
    - Replay-validates M1b structural eligibilities and M1c outcome resolutions against selection/proof contexts.
    - Enforces exploratory M1b resolution semantics: uses `ResolutionMode.CURRENT_INTERPRETATION` + `InformationRole.EX_POST_OUTCOME` for declared bounded cohorts, binding `ALPACA_LIMITATION_BOUNDED_COHORT`. Never relabels as `AS_KNOWN`.
  - `verify_evaluation_input_bundle(bundle: EvaluationInputBundleV1) -> bool`:
    - Cryptographically re-verifies all hashes, entities, and absence of exploratory reconstructions if claiming promotion compatibility.
- `SessionClockV1`:
  - Sequence of sessions within `evaluation_interval`.
  - Authority modes:
    - `realized_session_authority`: requires authenticated `RealizedSessionVersionV1` with verified `actual_open`, `actual_close`, and halt telemetry.
    - `scheduled_session_reconstruction`: permits reconstruction from `ScheduledSessionVersionV1`, binding `ALPACA_LIMITATION_ABSENT_HALTS` and `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`. Missing observations on scheduled open fail closed to `INDETERMINATE`.
  - Handles early closes:
    - Realized early close: post-close decision occurs immediately after `actual_close` (e.g. 13:00 ET).
    - Scheduled exploratory early close: executes post-close immediately after scheduled close (e.g. 13:00) with explicit limitation, not 16:00.
  - Warmup schedule: 0-based `session_index` derives `is_warmup: bool = (session_index < W)`. Sessions $0$ to $W - 2$ skip `strategy.decide()`. Session $W - 1$ post-close is the first decision point (`session_index >= W - 1`) staging targets for session $W$ open. Protocols strictly require $W \ge 1$; $W=0$ is rejected and out of M2 V1 scope.
- `evaluation_run_identity(...) -> SHA256Hash`:
  - Computes canonical hash over `(strategy_reference, parameters, input_bundle_hash, protocol_hash, cost_model_hash, admission_hash, code_hash, environment_hash)`.
  - Excludes all random UUIDs and wall-clock timestamps.

### 4. RED Acceptance Criteria
- Unit tests fail with `ModuleNotFoundError` for `evaluator_bundles` and `evaluator_clock`.

### 5. GREEN Acceptance Criteria
- Input bundle self-hash validation verifies integrity without circular dependence on admission.
- Bundle rejects fabricated observation views or outcomes that fail M1d replay or do not match bound proof hashes.
- Exploratory decision inputs correctly flag `has_exploratory_reconstructions = True`.
- Session clock correctly identifies session open and close times under both authority modes, including early closes at 13:00 ET.
- Missing market observation on scheduled open fails closed to `INDETERMINATE`.
- Warmup interval correctly flags the first $W$ sessions as non-trading, with session $W$ executing initial fills.
- Re-executing identical evaluation parameters under two different mock runs produces bitwise-identical `evaluation_run_identity`.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_bundles.py tests/unit/test_evaluator_clock.py -v
```

### 7. Adversarial Test Cases
- Circular hash deadlock test: verify `bundle_hash` computes cleanly without requiring admission.
- Bundle validation with fabricated observation view failing M1d replay -> ValueError.
- Reconstructed input submitted without `has_exploratory_reconstructions=True` -> ValueError.
- Early-close session ending at 13:00 ET: verify decision cutoff occurs after 13:00 ET without waiting for 16:00 ET.
- Scheduled session missing market bars on open -> fails closed to `INDETERMINATE`.
- Observation view without anchor session anchored to decision session -> ValueError.

### 8. Review and Commit Boundary
- Independent review covering calendar causality, clock authority modes, bundle proof verification, M1d replay preparation, and acyclic hashing.
- Commit message: `feat: add M2 proof-carrying input bundle and session clock authority`
- Checkpoint execution.

---

## Task 3: Portfolio State, Cash Accounting, Whole-Share Positions, and Deterministic Claims Kernel

### 1. Objective
Implement the long-only, whole-share portfolio state representation, USD cash accounting, deterministic occurrence-bound claims (`PendingCashClaimV1`), weekend/holiday dividend settlement logic, and exact cost basis relief formulas with explicit delivered settlement evidence.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_portfolio.py`
- `src/drift/evaluator/portfolio.py`
- `tests/unit/test_evaluator_portfolio.py`

### 3. Contracts and Interfaces
- `SecurityHoldingV1(FrozenModel)`:
  - `security_id: UUID7`
  - `quantity: int` (must be > 0)
  - `cost_basis: Decimal` (total acquisition cost including fees)
  - `average_cost_per_share: Decimal` (property: `cost_basis / quantity`)
- `PendingCashClaimV1(FrozenModel)`:
  - `claim_id: SHA256Hash` (deterministically derived from `security_id, action_kind, occurrence_id, component_id, entitlement_session, payable_session`)
  - `security_id: UUID7`
  - `action_kind: ActionKind`
  - `occurrence_id: NonBlankStr`
  - `component_id: NonBlankStr`
  - `entitled_quantity: int`
  - `cash_per_share: Decimal`
  - `total_cash_expected: Decimal`
  - `entitlement_session: date`
  - `payable_session: date`
- `PortfolioStateV1(FrozenModel)`:
  - `session_key: SessionKeyV1`
  - `cash_balance: Decimal` (must be >= 0)
  - `holdings: tuple[SecurityHoldingV1, ...]`
  - `pending_cash_claims: tuple[PendingCashClaimV1, ...]`
  - `holdings_market_value: Decimal`
  - `pending_claims_value: Decimal`
  - `net_asset_value: Decimal` ($\text{cash} + \text{holdings} + \text{claims}$)
  - `realized_gross_pnl: Decimal`
  - `realized_net_pnl: Decimal`
  - `cumulative_transaction_costs: Decimal`
- Cost Basis Relief and Realized PnL Formulas:
  - Sold cost basis: $\Delta q_{\text{sell}} \times (\text{current\_cost\_basis} / \text{current\_quantity})$.
  - Gross realized PnL: $(\Delta q_{\text{sell}} \times P_{\text{fill}}) - \text{Sold Cost Basis}$.
  - Net realized PnL: $\text{Gross Realized PnL} - \text{Costs}$.
- `PortfolioAccountingKernel`:
  - Methods: `apply_fill(fill)`, `record_claim(claim)`, `settle_claims(delivered_claim_ids: Container[SHA256Hash])`, `mark_close(close_prices)`.
  - `settle_claims` settles explicit delivered claims proven by M1c delivered settlement evidence (`delivered_claim_ids`). Claims payable on weekend/holiday dates settle on the first subsequent trading session where delivered settlement evidence exists.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_portfolio.py` and portfolio accounting classes do not exist.

### 5. GREEN Acceptance Criteria
- Adding holdings and updating cash balances enforces exact Decimal arithmetic.
- Deterministic claim ID generation produces distinct hashes for multiple components on the same date.
- Claims payable on weekend dates settle cleanly on the first subsequent trading session with delivered settlement evidence.
- Marking portfolio at close computes exact holdings market value using unadjusted close prices.
- Pending claims contribute to NAV but do not alter `cash_balance` until settled.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_portfolio.py -v
```

### 7. Adversarial Test Cases
- Attempt to create `SecurityHoldingV1` with quantity <= 0 -> ValueError.
- Multiple cash components on same date with same security ID: verify distinct `claim_id` generation.
- Dividend payable on Saturday: verify claim settles on Monday trading session.
- Missing close mark for a currently held position -> IndeterminateValuationError.

### 8. Review and Commit Boundary
- Independent review covering Decimal precision, NAV reconciliation, delivered settlement binding, and deterministic claim IDs.
- Commit message: `feat: add M2 portfolio state and cash accounting kernel`
- Checkpoint execution.

---

## Task 4: First-Class M1c Corporate Action and Economic Outcome Accounting

### 1. Objective
Implement the corporate action processing engine that applies M1c occurred economic effects (`EconomicEffectVersionV1`) and delivered settlements (`EconomicSettlementVersionV1`) directly to portfolio state, enforcing exact `FractionTreatmentV1` handling (with required tie-breaking rules, no truncation), staged target split-scaling, and conservative due-bill dividend entitlements (strictly prohibiting generic due-bill shortcuts).

### 2. Exact Files Expected
- `src/drift/domain/evaluator_corporate_actions.py`
- `src/drift/evaluator/corporate_actions.py`
- `tests/unit/test_evaluator_corporate_actions.py`

### 3. Contracts and Interfaces
- `CorporateActionProcessor`:
  - `apply_pre_open_actions(portfolio_state, staged_targets, economic_outcomes, current_session) -> tuple[PortfolioStateV1, tuple[SecurityTargetPositionV1, ...]]`
  - `apply_intrasession_settlements(portfolio_state, economic_outcomes, current_session) -> PortfolioStateV1`
- Action Handlers:
  - Exact rational arithmetic: use `fractions.Fraction(int(ratio.numerator), int(ratio.denominator))` or exact integer quotient/remainder; floats strictly prohibited.
  - Inspect `ShareComponentV1.ratio_meaning`:
    - `resulting_per_predecessor` (splits, stock acquisitions): $\text{exact\_shares} = q \times (n/d)$.
    - `additional_per_predecessor` with same recipient (stock dividends): $\text{exact\_shares} = q + (q \times (n/d))$.
    - `additional_per_predecessor` with child recipient (spinoff): parent shares unchanged, child entitlement $= q \times (n/d)$.
  - `ActionKind.FORWARD_SPLIT` / `REVERSE_SPLIT`:
    - If integral: materialize whole shares.
    - If non-integral: apply explicit `FractionTreatmentV1`:
      - `round_down`: truncate fractional share.
      - `round_up`: round up to next whole share.
      - `round_nearest`: requires an explicit interpreted tie-breaking rule artifact from source evidence (e.g. half-up vs half-even); without this artifact, fails closed to `INDETERMINATE`.
      - `aggregate_sale_cash`: creates whole shares plus a cash-in-lieu pending claim.
      - If treatment is `fraction_issued` or `unknown`, fail closed to `INDETERMINATE`.
    - Scale staged target positions: $\text{staged\_target}' = \text{staged\_target} \times (n/d)$. If non-integral and unresolved, fail closed to `INDETERMINATE`.
  - `ActionKind.REGULAR_CASH_DIVIDEND` / `SPECIAL_CASH_DISTRIBUTION`:
    - Create `PendingCashClaimV1` ONLY when M1c occurred effect evidence proves legal entitlement.
    - Handle due-bill distributions: entitlement follows proven executable due-bill rules. Applying a generic shortcut such as `due_bill_redemption_date == entitlement_date` is strictly prohibited; unevidenced or ambiguous due bills fail closed to `INDETERMINATE`.
    - Payable date settles into `cash_balance` when delivered settlement proves payment.
  - `ActionKind.CASH_ACQUISITION`: removes target position, credits cash entitlement.
  - `ActionKind.STOCK_ACQUISITION`: converts target holding into acquirer holding using exact ratio and `FractionTreatmentV1`.
  - `ActionKind.MIXED_ACQUISITION`: credits cash entitlement and acquirer share holding.
  - `ActionKind.SPINOFF`: creates child security holding using exact distribution ratio and `FractionTreatmentV1`. Daily NAV marks normally if parent/child closing prices exist, without requiring tax allocation percentages.
  - `ActionKind.LIQUIDATION`: credits known liquidation proceeds; missing terms fail closed to `INDETERMINATE`.
  - Terms without Occurred Effect or Delivered Settlement: corporate action terms records without proved occurrence or delivered settlement commit ZERO portfolio cash or share mutations.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_corporate_actions.py` does not exist.

### 5. GREEN Acceptance Criteria
- 1-for-8 reverse split on 10 shares with `aggregate_sale_cash`: creates 1 whole share and a pending cash-in-lieu claim for 0.25 shares.
- Reverse split with `unknown` fraction treatment fails closed to `INDETERMINATE`.
- Reverse split with `round_nearest` and explicit tie-breaking rule executes deterministically.
- Reverse split with `round_nearest` missing tie-breaking rule fails closed to `INDETERMINATE`.
- 2-for-1 forward split doubles holdings AND doubles staged target positions, preserving intended delta.
- Due-bill special dividend correctly defers entitlement until proven due-bill redemption session without generic ex-date shortcuts.
- Spin-off marks NAV cleanly when market prices exist.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_corporate_actions.py -v
```

### 7. Adversarial Test Cases
- Attempt to use `int(...)` truncation on fractional split entitlement -> Rejected.
- Reverse split on non-divisible holding with unknown fraction treatment -> IndeterminateValuationError.
- Round nearest without source tie-breaking rule artifact -> IndeterminateValuationError.
- Special dividend with due bill: generic shortcut `due_bill_redemption_date == entitlement_date` attempted -> Rejected / IndeterminateValuationError.
- Terms record without occurred effect report -> No portfolio mutation committed.

### 8. Review and Commit Boundary
- Independent review covering fraction treatment, tie-breaking rules, due-bill logic, staged target scaling, and M1c outcome binding.
- Commit message: `feat: add M2 corporate action accounting kernel`
- Checkpoint execution.

---

## Task 5: Target-Position Strategy Boundary, Atomic Next-Open Fill Engine, and Cost Application

### 1. Objective
Implement the runtime strategy interface targeting economic securities (`SecurityTargetPositionV1` without execution listing ID), canonical sorted views (`StrategyDecisionViewV1`), `PositionViewV1`, the explicit complete target set omission rule, Phase 2 dynamic primary execution listing resolution via M1b evidence, the atomic plan-then-commit execution engine with solvency checks, and versioned cost/slippage application.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_strategy.py`
- `src/drift/domain/evaluator_execution.py`
- `src/drift/evaluator/execution.py`
- `tests/unit/test_evaluator_strategy.py`
- `tests/unit/test_evaluator_execution.py`

### 3. Contracts and Interfaces
- `PositionViewV1(FrozenModel)`:
  - `security_id: UUID7`
  - `quantity: int`
  - `cost_basis: Decimal`
  - `average_cost_per_share: Decimal`
- `StrategyDecisionViewV1(FrozenModel)`:
  - `security_id: UUID7`
  - `views: tuple[DerivedObservationViewV1, ...]`
- `StrategyDecisionContextV1`:
  - `session_key: SessionKeyV1`
  - `decision_cutoff: UTCDateTime`
  - `admitted_universe: tuple[UUID7, ...]` (canonical sorted tuple)
  - `current_holdings: tuple[PositionViewV1, ...]` (canonical sorted tuple)
  - `current_cash: Decimal`
  - `portfolio_nav: Decimal`
  - `decision_views: tuple[StrategyDecisionViewV1, ...]` (canonical sorted tuple)
- `SecurityTargetPositionV1(FrozenModel)`:
  - `security_id: UUID7`
  - `target_quantity: int` (must be >= 0)
  - Note: does NOT carry `execution_listing_id`. Strategy targets the economic security.
- `StrategyDecisionIntentV1`:
  - `session_key: SessionKeyV1`
  - `decision_time: UTCDateTime` (must strictly match `context.decision_cutoff`; wall-clock `now()` prohibited)
  - `targets: tuple[SecurityTargetPositionV1, ...]`
- Explicit Complete Target Set Rule:
  - Any held security omitted from `targets` is assigned `target_quantity = 0` (liquidate all).
  - Securities removed from `admitted_universe` are permitted to have `target_quantity = 0`.
- Phase 2 Dynamic Primary Execution Listing Resolution:
  - In Phase 2, the evaluator resolves the active historical primary execution listing (`ListingV1`) for each target security using M1b evidence as of the execution session. If a security migrated listings between decision and execution, execution resolves the active listing dynamically.
- `AtomicRebalanceEngine`:
  - Fetch unadjusted open prices for all target deltas at resolved primary listings.
  - Plan sells: calculate proceeds net of costs.
  - Plan buys: calculate required cash including costs.
  - Solvency check: verify `current_cash + Gross Sells - Required Cash >= 0`.
  - If unfunded: emit `FillRejectionTraceEventV1`, commit **ZERO** fills and **ZERO** mutations, immediately halt subsequent session stepping, and classify run as `REJECTED`.
  - If funded: commit sells first, buys second, in canonical order sorted by `security_id` UUID bytes.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_strategy` and `evaluator_execution` do not exist.

### 5. GREEN Acceptance Criteria
- Strategy omitting a held security generates an automatic liquidation order ($\Delta q = -\text{current}$).
- Strategy targets economic security only; Phase 2 resolves the active historical execution listing dynamically.
- Strategy decision context uses explicit sorted tuples rather than unordered mappings.
- Rebalance where buys exceed cash after sells results in ZERO committed fills, immediate stepping halt, and a scientific `REJECTED` classification.
- Valid rebalance executes sells before buys, applying adverse slippage and deducting transaction costs.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_strategy.py tests/unit/test_evaluator_execution.py -v
```

### 7. Adversarial Test Cases
- Negative target quantity emitted in Phase 5 -> Rejected immediately.
- Strategy attempts entry (`target > 0`) for non-admitted security -> Rejected.
- Strategy attempts liquidation (`target = 0`) for non-admitted security -> Allowed.
- Listing migration between decision session and execution session: verify Phase 2 executes on the new primary listing without stale listing error.
- Atomic rebalance shortfall test: multi-buy order where cash is insufficient for one buy -> verify ZERO fills committed and no holdings mutated.

### 8. Review and Commit Boundary
- Independent review covering atomic rebalance execution, dynamic listing resolution, omission liquidation semantics, and canonical collection sorting.
- Commit message: `feat: add M2 strategy protocol and atomic next-open execution engine`
- Checkpoint execution.

---

## Task 6: Deterministic Session Evaluator Engine, Canonical Trace Generation, and M0 Integration

### 1. Objective
Assemble the complete 5-phase session evaluator loop, content-addressed trace logger, fatal indeterminacy and shortfall halting, complete result models without random UUIDs or wall-clock timestamps, and integration with M0 `ExperimentSpecification` and `ExperimentRun`.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_trace.py`
- `src/drift/domain/evaluator_results.py`
- `src/drift/evaluator/engine.py`
- `src/drift/evaluator/experiment_runner.py`
- `tests/unit/test_evaluator_trace.py`
- `tests/unit/test_evaluator_engine.py`
- `tests/integration/test_evaluator_experiment_run.py`

### 3. Contracts and Interfaces
- Trace Events:
  - `SessionStartTraceEventV1`, `CorporateActionAppliedTraceEventV1`, `FillTraceEventV1`, `FillRejectionTraceEventV1`, `ClaimSettledTraceEventV1`, `SessionMarkTraceEventV1`, `StrategyDecisionTraceEventV1`, `IndeterminateCauseTraceEventV1`.
- `EvaluationTraceLogV1`:
  - `events: tuple[EvaluatorTraceEventV1, ...]`
  - `trace_hash: SHA256Hash` (content hash over all events).
- `EvaluationClassification(StrEnum)`: `COMPLETE`, `INDETERMINATE`, `REJECTED`.
- Result Models:
  - `EvaluationSummaryMetricsV1(FrozenModel)`: complete Pydantic schema with initial/ending cash, NAV, PnL, turnover, equity series.
  - `ExploratoryEvaluationResultV1(FrozenModel)`: carries `lane: Literal["exploratory"]`, binds `ExploratoryEvaluationAdmissionV1`, `is_promotion_grade_evidence = False`. `result_id` is content-addressably derived (`result_hash`). No wall-clock timestamps.
  - `PromotionEvaluationResultV1(FrozenModel)`: carries `lane: Literal["promotion"]`, binds `PromotionEvaluationAdmissionV1`, `is_promotion_grade_evidence = True`. `result_id` is content-addressably derived (`result_hash`). No wall-clock timestamps. Strictly represents evidence lane qualification, not strategy approval.
- Fatal Indeterminacy and Rejection Halting:
  - Encountering fatal missing price or unprovable outcome emits `IndeterminateCauseTraceEventV1`, immediately halts session stepping, and marks result `INDETERMINATE`.
  - Encountering an unfunded rebalance emits `FillRejectionTraceEventV1`, immediately halts session stepping, commits **ZERO** fills, and marks result `REJECTED`.
- `SessionEvaluatorEngine.run(...) -> EvaluationResult`:
  - Orchestrates phases 1-5 for each session.
- `execute_experiment_run(spec, runner_context) -> ExperimentRun`:
  - Wraps M2 evaluator in M0 experiment runner, attaching trace and result artifact references. M0 `ExperimentRun` owns operational metadata `run_id`, `started_at`, and `completed_at`, while M2 evaluator result models remain strictly content-addressed and reproducible.

### 4. RED Acceptance Criteria
- Tests fail because `engine.py`, `evaluator_trace.py`, and `evaluator_results.py` do not exist.

### 5. GREEN Acceptance Criteria
- Multi-session synthetic evaluation executes end-to-end through all 5 phases.
- Content-addressed trace log and result artifact reproduce bitwise-identical hash on rerun, even under different `ExperimentRun` IDs.
- Fatal indeterminacy cleanly halts stepping and records `classification=INDETERMINATE` with `status=COMPLETED`.
- Fatal rebalance shortfall cleanly halts stepping, commits zero fills, and records `classification=REJECTED`.
- `ExperimentRun` records `status=COMPLETED`, binds artifact references, and includes metrics summary.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_trace.py tests/unit/test_evaluator_engine.py tests/integration/test_evaluator_experiment_run.py -v
```

### 7. Adversarial Test Cases
- Attempt to construct `PromotionEvaluationResultV1` with `ExploratoryEvaluationAdmissionV1` -> Type/Validation error.
- Replaying identical input under two different `ExperimentRun` UUIDs and timestamps produces bitwise identical `result_hash` and `trace_hash`.
- Fatal missing open price: verify evaluator halts subsequent sessions and outputs `classification=INDETERMINATE`.
- Unhandled Python exception correctly marks `ExperimentRun` as `FAILED` with `error_details`.

### 8. Review and Commit Boundary
- Independent review covering 5-phase execution, fatal indeterminacy halting, deterministic result identity, and M0 experiment provenance.
- Commit message: `feat: add M2 session evaluator engine and trace logger`
- Checkpoint execution.

---

## Task 7: Comprehensive Adversarial Verification, Anti-Laundering Invariants, and Closed-World Replay Testing

### 1. Objective
Implement the complete 28-case adversarial acceptance test suite covering causality, epistemic lanes, universe rules, clock authority, replay integrity, accounting, execution, gatekeeper, replay determinism, and provider boundaries.

### 2. Exact Files Expected
- `tests/adversarial/test_m2_causality.py`
- `tests/adversarial/test_m2_accounting.py`
- `tests/adversarial/test_m2_anti_laundering.py`
- `tests/adversarial/test_m2_replay_determinism.py`

### 3. Adversarial Invariants Tested (Table 22 of Spec)
- **Causality**:
  - Same-Bar Close Lookahead: strategy requesting execution at session D close using session D close price is rejected.
  - Post-Cutoff Observation Leakage: observation with availability timestamp > decision cutoff passed to strategy is filtered or rejected fail-closed.
  - Early-Close Realized Timing: session closing at 13:00 evaluates strategy decision after 13:00 without waiting for 16:00.
  - Future Corporate Action Knowledge: corporate action announced after decision date rejected by causal selection query.
- **Epistemic Lanes**:
  - Downloaded Bar as Decision Ref: Alpaca bar downloaded years later without provider vintage rejected as `ObservationDecisionReferenceV1`.
  - Reconstructed Input in Promotion: `ExploratoryReconstructedDecisionInputV1` submitted to PROMOTION evaluation triggers structural gatekeeper rejection.
  - Reconstructed Input in Exploratory: bar wrapped in `ExploratoryReconstructedDecisionInputV1` with retrospective limitations permitted in EXPLORATORY lane only.
- **Universe**:
  - Current Interpretation as As-Known: M1b `CURRENT_INTERPRETATION` submitted as `AS_KNOWN` in PROMOTION is rejected.
  - Survivorship Bias: current active asset list used as historical universe is rejected.
  - Indeterminate Eligibility: security with `MembershipStatus.INDETERMINATE` admitted to trading is rejected.
  - Post-Delisting Liquidation: strategy emitting target=0 for held security dropped from universe is permitted.
  - Listing Migration at Execution: Phase 2 dynamically resolves new historical primary listing; does not use stale listing.
- **Clock Authority**:
  - Scheduled Row as Realized Session: scheduled calendar row prohibited from minting `RealizedSessionVersionV1`.
  - Scheduled Exploratory Early Close: scheduled 13:00 close evaluated under `scheduled_session_reconstruction` after 13:00 with explicit limitation.
  - Missing Bar on Scheduled Open: missing market observation on scheduled open fails closed to `INDETERMINATE`.
- **Replay Integrity**:
  - View Hash vs M1d Replay: self-consistent fabricated view without successful M1d replay is rejected during bundle preparation.
- **Accounting**:
  - Double-Counting Adjustment: accounting configured with split-adjusted prices while applying M1c splits is rejected.
  - Premature Dividend Settlement: dividend cash credited before payable date is rejected.
  - Generic Due-Bill Shortcut: shortcut `due_bill_redemption_date == entitlement_date` applied to special dividend is rejected; requires explicit executable rule, else `INDETERMINATE`.
  - Round Nearest Without Rule: `round_nearest` applied without source tie-breaking rule artifact fails closed to `INDETERMINATE`.
  - Terms-Only Corporate Action: Alpaca terms record without occurred effect or delivered settlement commits zero cash/share mutation.
  - Fabricated Delisting Recovery: security delisting without terms fails closed to `INDETERMINATE`.
  - Fractional Split Unknown Treatment: reverse split yielding non-integral shares with unknown fraction treatment fails closed to `INDETERMINATE`.
  - Missing Close Forward-Fill: held position with missing close price fails closed to `INDETERMINATE`.
  - Multiple Same-Date Cash Claims: distinct claim IDs verified via M1c component/occurrence hash.
- **Execution**:
  - Close-for-Open Fallback: missing open price replaced by prior or current close price fails closed to `INDETERMINATE`.
  - Negative Target Position: negative target quantity rejected; run classified as `REJECTED`.
  - Fractional Share Target: floating-point target quantity rejected; whole shares only.
  - Unfunded Rebalance Shortfall: target rebalance exceeding cash after planned sells commits 0 fills, halts stepping, classified `REJECTED`.
  - Zero Warmup Session Count: protocol declared with `warmup_session_count = 0` rejected by validation; requires $W \ge 1$.
- **Gatekeeper**:
  - Missing Audit Purpose Report: promotion admission lacking retrospective audit report rejected.
  - Audit Critical Dimension Failed: decision report passes but retrospective audit critical dimension fails -> rejected.
  - Report Profile Hash Mismatch: `report.target.profile_hash` mismatch -> rejected.
  - Profile Not in Profile Set: profile not a member of bound `PilotProfileSetV1.profiles` -> rejected.
  - Fake PASS Report: report indicates PASS but M1e completion record is NEGATIVE -> rejected.
  - Promotion Evidence Scope: treating `PromotionEvaluationResultV1` as M10 strategy approval disallowed.
- **Replay**:
  - Replay Across ExperimentRuns: identical input evaluated under different `ExperimentRun` UUIDs produces bitwise identical result and trace hashes.
  - Overnight Split Target Scaling: staged target scaled across forward split before open execution preserves intended delta.
- **Provider Boundary**:
  - Raw Vendor Payload Leakage: raw Alpaca JSON dictionary passed into strategy or core prohibited.
  - Missing Halt Synthesized: missing halt data interpreted as affirmative "not halted" prohibited; remains unknown.

### 4. RED Acceptance Criteria
- Adversarial tests identify any gaps or lenient defaults in Tasks 1-6.

### 5. GREEN Acceptance Criteria
- All 28 adversarial test scenarios pass unambiguously.
- Anti-laundering tests mathematically prove no exploratory result can satisfy promotion validation.

### 6. Focused Tests
```bash
uv run pytest tests/adversarial/test_m2_causality.py tests/adversarial/test_m2_accounting.py tests/adversarial/test_m2_anti_laundering.py tests/adversarial/test_m2_replay_determinism.py -v
```

### 7. Review and Commit Boundary
- Independent adversarial review with fresh subagents attacking causality, anti-laundering, and accounting invariants.
- Commit message: `test: add comprehensive M2 adversarial and anti-laundering test suite`
- Checkpoint execution.

---

## Task 8: Bounded Alpaca Development Bridge and End-to-End Exploratory Smoke Validation

### 1. Objective
Build the bounded, offline Alpaca exploratory intake bridge to acquire free development market data for a declared cohort, map records into provider-neutral M1b-M1d contracts following the layered data pipeline, bind canonical limitation constants in an `ExploratoryEvaluationAdmissionV1`, and execute an end-to-end exploratory smoke evaluation against a quiet window.

### 2. Exact Files Expected
- `src/drift/adapters/alpaca_exploratory.py`
- `scripts/intake_alpaca_exploratory.py`
- `tests/unit/test_alpaca_exploratory_adapter.py`
- `tests/integration/test_alpaca_exploratory_smoke.py`

### 3. Contracts and Interfaces
- `AlpacaExploratoryAdapter`:
  - Completely decoupled from the evaluator core.
  - Uses read-only REST endpoints (historical bars and corporate actions).
  - Credentials loaded from `.env` without echoing to stdout/logs.
  - Follows strict Layered Data Pipeline:
    1. Retain exact native response bytes in private storage outside Git.
    2. Generate `AcquisitionReceiptV1` and dataset manifest.
    3. Map native payloads to standard Drift source records (`SecurityV1`, `ListingV1`, `ScheduledSessionVersionV1`, `CorporateActionTermsVersionV1`, raw bar records).
    4. Validate datasets via Drift public validators (`DatasetValidationDecisionV2`).
    5. Execute standard M1b/M1c/M1d selection/normalization functions (deriving `DerivedObservationViewV1` through M1d routines).
    6. Wrap in `ExploratoryReconstructedDecisionInputV1` with retrospective limitations.
    7. Emit `EvaluationInputBundleV1` via `build_evaluation_input_bundle`.
  - Strict Layering Prohibitions:
    - **NO Manual Derived Views**: Must never construct `DerivedObservationViewV1` manually from provider JSON.
    - **NO Fake Realized Sessions**: Scheduled calendar rows must never be converted into `RealizedSessionVersionV1`. Operates under `scheduled_session_reconstruction` mode.
    - **NO Invented Corporate Action Effects or Settlements**: Terms records mapped only as terms. Delisted or unprovable settlements are not invented.
  - Mints `ExploratoryEvaluationAdmissionV1` binding the six canonical limitation constants:
    1. `ALPACA_LIMITATION_TRUNCATED_CA`
    2. `ALPACA_LIMITATION_UNVERSIONED_BARS`
    3. `ALPACA_LIMITATION_ABSENT_HALTS`
    4. `ALPACA_LIMITATION_BOUNDED_COHORT`
    5. `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`
    6. `ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION`
- `intake_alpaca_exploratory.py`: CLI tool for bounded cohort acquisition.
- `test_alpaca_exploratory_smoke.py`:
  - Executes a complete exploratory evaluation run using the Alpaca development bundle and a simple reference strategy.
  - Quiet-window exploratory smoke run: selects a bounded cohort and date window with valid free SIP historical bars, scheduled calendar rows, and minimal corporate action complexity. Full corporate action accounting is verified via pinned fixtures in Tasks 3-7.
  - Confirms `ExploratoryEvaluationResultV1` is produced with `is_promotion_grade_evidence=False`.
  - Standard CI/test execution uses recorded/pinned fixture bytes; network access is never required.

### 4. RED Acceptance Criteria
- Tests fail because `alpaca_exploratory.py` and smoke integration tests do not exist.

### 5. GREEN Acceptance Criteria
- Adapter maps Alpaca bars and corporate actions into valid Drift M1b-M1d domain instances via the layered pipeline.
- Drift public validators accept the mapped datasets.
- Exploratory admission artifact correctly records all six canonical limitation constants.
- Smoke evaluation executes end-to-end on quiet window, producing an `ExploratoryEvaluationResultV1` and a complete trace log.
- All unit and integration tests run completely offline without `.env` or network access using pinned fixtures.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_alpaca_exploratory_adapter.py tests/integration/test_alpaca_exploratory_smoke.py -v
```

### 7. Adversarial Test Cases
- Missing API key gracefully skips network acquisition in CLI without raising uncaught exception.
- Evaluator core attempt to call Alpaca adapter directly -> Architecture boundary prevents import or raises error.
- Attempt to emit `PromotionEvaluationAdmissionV1` from Alpaca bridge -> Rejected.
- Attempt to construct `DerivedObservationViewV1` directly from Alpaca JSON without M1d normalization -> Rejected.
- Attempt to convert scheduled calendar row into `RealizedSessionVersionV1` -> Rejected.

### 8. Review and Commit Boundary
- Independent review covering network isolation, layered pipeline conformance, secret hygiene, limitation recording, and non-promotability.
- Commit message: `feat: add bounded Alpaca exploratory development bridge and smoke test`
- Checkpoint execution.

---

## Standing Drift Execution Workflow for Implementation

When implementing this plan task-by-task:
1. **Resume First**: Always run `git status -sb` and `git log -5 --oneline`.
2. **Strict File Staging**: Never run `git add .` or stage whole directories. Stage only the explicit files belonging to the verified task slice.
3. **No Em Dashes**: Enforce ASCII hyphens across code, docstrings, and commit messages.
4. **Independent Adversarial Review**: Every task must undergo adversarial review using a fresh subagent before acceptance.
5. **Standard Verification Gate**:
   ```bash
   uv run pytest <focused-tests>
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src tests
   git diff --check
   ```
6. **Checkpoint and Push**: Commit the accepted task slice, run Checkpoint, and push to `origin main`.
