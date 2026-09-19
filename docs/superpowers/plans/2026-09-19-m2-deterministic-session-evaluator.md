# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Drift M2: a deterministic, provider-neutral session-level evaluator and portfolio accounting kernel operating across two structurally distinct evidence lanes (`EXPLORATORY` and `PROMOTION`) with zero lookahead, unadjusted source-basis accounting, native M1c corporate actions, content-addressed execution traces, and strict anti-laundering enforcement.

**Architecture:** A single provider-neutral evaluator core consumes validated `EvaluationInputBundleV1` artifacts and executes a 5-phase deterministic daily session schedule (Pre-Open Effects, Open Execution, Intrasession Effects, Close Mark, Post-Close Decision). Lane separation is structurally enforced at the type layer (`ExploratoryEvaluationAdmissionV1` / `ExploratoryEvaluationResultV1` vs `PromotionEvaluationAdmissionV1` / `PromotionEvaluationResultV1`). Economic holdings are keyed by `security_id` (UUID7), accounting uses source-basis unadjusted prices, and execution deltas are filled at the next regular session open. The Alpaca exploratory bridge is isolated in Task 8 as an offline intake script outside the evaluator core.

**Tech Stack:** Existing Python 3.14+, Pydantic (FrozenModel), pytest, Ruff, mypy, uv, and Python standard library only. Decimal arithmetic for all prices, cash balances, and fees. No new dependencies, database migrations, broker connections, or live trading capabilities.

**Execution Status:** Planning and architecture specification approved. Implementation authorized task-by-task under this plan.

**Spec:** [M2 Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification](../specs/2026-09-19-m2-deterministic-session-evaluator-design.md), [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), and [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## Global Constraints

- **Workspace Boundary**: Work strictly in `/Users/kanuj/Documents/projects/drift`. Never touch external mirrors or unapproved local directories.
- **Repository Truth**: Canonical baseline is commit `ef24c2c` (and underlying verified Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
- **Protected Prior Milestones**: M0 through M1e Tasks 1-7 are complete and protected. Do not mutate persisted models, schemas, or fixtures in `src/drift/domain/experiments.py`, `strategies.py`, `securities.py`, `universes.py`, `observations.py`, or `qualification.py`. Add M2 evaluator contracts beside them.
- **Strict Two-Lane Anti-Upgrade Invariant**: Exploratory evaluation results can NEVER be upgraded, converted, or relabeled into promotion evidence. No constructor, helper, or mutable field may bridge the two lanes. Promotion strictly requires an independent, fresh evaluation run against verified M1e promotion-qualified data.
- **Acyclic Admission Hashing**: The dependency graph is strictly acyclic: Market Data -> `EvaluationInputBundleV1` (`bundle_hash`) -> `EvaluationAdmissionV1` (`input_bundle_hash = bundle_hash`) -> `EvaluationRunIdentity`. `EvaluationInputBundleV1` does NOT hold a reference to `admission_hash`.
- **Zero Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden across all code, docstrings, markdown documents, and commit messages. Always use the ASCII hyphen (U+002D).
- **Offline / Network-Free Core**: The evaluator core and all standard unit test suites must run 100% offline with zero network access or socket activity.
- **Decimal Precision**: All currency balances, prices, execution marks, dividends, fees, and slippage calculations must use Python `Decimal` or exact integer strings. Floating-point arithmetic for portfolio accounting is strictly forbidden.
- **Lookahead Prevention**: Session D post-close decisions execute exclusively at session D+1 regular session open. No same-bar close execution.
- **Accounting Basis**: Accounting and marks strictly use source-basis unadjusted prices. Corporate actions come exclusively from M1c economic facts. Split-adjusted prices are forbidden in portfolio accounting.
- **Missingness Fail-Closed**: Missing prices, missing corporate action terms, or unprovable outcomes fail closed to `INDETERMINATE`. Never forward-fill close marks, substitute close for open, or synthesize zero. Encountering fatal indeterminacy halts further session stepping.
- **Secret Handling**: Alpaca credentials reside exclusively in `.env` (mode 0600, gitignored). Never print, log, commit, or pass credentials to the evaluator core.
- **TDD Workflow**: Every task requires meaningful RED tests confirming failure before implementation, followed by GREEN acceptance, focused verification, adversarial review, full gate, and Checkpoint commit.

---

## Task Decomposition Overview

- **Task 1: Evaluation Lane Contracts, Protocol Definitions, Cost Models, and Admission Gatekeeper**
  Establish immutable admission types, protocol parameters, versioned cost/slippage models, and promotion gatekeeper logic.
- **Task 2: Provider-Neutral Evaluation Input Bundle, Session Clock, and Deterministic Replay Identity**
  Build the self-contained input bundle contract (acyclic, snapshot-bound), session clock schedule, and canonical replay hashing.
- **Task 3: Portfolio State, Cash Accounting, Whole-Share Positions, and Pending Claims Kernel**
  Implement long-only whole-share holdings, USD cash accounting, deterministic dividend receivables, and weekend settlement logic.
- **Task 4: First-Class M1c Corporate Action and Economic Outcome Accounting**
  Process forward/reverse splits, staged target split-scaling, cash dividends, mergers, spin-offs, and terminations natively from M1c facts.
- **Task 5: Target-Position Strategy Protocol, Deterministic Next-Open Fill Engine, and Cost Application**
  Implement runtime strategy interface, whole-share delta derivation with explicit omission rule, sell-first/buy-second fills, and Phase 2 cash solvency enforcement.
- **Task 6: Deterministic Session Evaluator Engine, Canonical Trace Generation, and M0 Integration**
  Assemble the 5-phase session evaluator loop, content-addressed trace logger, scientific classification system, and M0 ExperimentRun binding.
- **Task 7: Comprehensive Adversarial Verification, Anti-Laundering Invariants, and Closed-World Replay Testing**
  Execute the complete 28-case adversarial matrix, anti-upgrade invariants, and bitwise replay validation.
- **Task 8: Bounded Alpaca Development Bridge and End-to-End Exploratory Smoke Validation**
  Build the offline Alpaca intake adapter, map bounded historical data to M1b-M1d, bind canonical limitation constants, and execute an exploratory smoke run.

---

## Task 1: Evaluation Lane Contracts, Protocol Definitions, Cost Models, and Admission Gatekeeper

### 1. Objective
Define the fundamental M2 domain contracts for evaluation lane admission (`ExploratoryEvaluationAdmissionV1` vs `PromotionEvaluationAdmissionV1`), evaluation protocol configuration (`EvaluationProtocolV1`), versioned transaction cost/slippage parameters (`EvaluationCostModelV1`), canonical Alpaca limitation constants, and the external promotion gatekeeper function.

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
  - `ALPACO_LIMITATION_TRUNCATED_CA = "corporate-action-mutation-replay-truncated-to-approx-72-days"`
  - `ALPACA_LIMITATION_UNVERSIONED_BARS = "derived-bars-unversioned-without-provider-vintages"`
  - `ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"`
  - `ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"`
- `ExploratoryEvaluationAdmissionV1(FrozenModel)`:
  - `admission_id: UUID7`
  - `lane: Literal["exploratory"] = "exploratory"`
  - `development_source_profile_hash: SHA256Hash`
  - `input_bundle_hash: SHA256Hash`
  - `acknowledged_limitations: tuple[NonBlankStr, ...]` (must not be empty)
  - `admitted_at: UTCDateTime`
  - `admission_hash: SHA256Hash`
- `PromotionEvaluationAdmissionV1(FrozenModel)`:
  - `admission_id: UUID7`
  - `lane: Literal["promotion"] = "promotion"`
  - `m1e_qualification_report_hash: SHA256Hash`
  - `m1e_purpose: Literal["historical_decision_input"]`
  - `m1e_snapshot_hash: SHA256Hash`
  - `m1e_rights_assessment_hash: SHA256Hash`
  - `m1e_replay_result_hash: SHA256Hash`
  - `input_bundle_hash: SHA256Hash`
  - `admitted_at: UTCDateTime`
  - `admission_hash: SHA256Hash`
- `EvaluationAdmissionV1 = Annotated[ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1, Field(discriminator="lane")]`
- `validate_promotion_admission(admission, bundle_snapshot_hash, report)`:
  - Validates that `admission.lane == "promotion"`.
  - Validates that `bundle_snapshot_hash == admission.m1e_snapshot_hash`.
  - Validates that `admission.m1e_purpose == "historical_decision_input"`.
  - Validates that `report.purpose == "historical_decision_input"`.
  - Validates that all 12 dimensions in `report.results` evaluate to `QualificationStatus.PASS`.
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
  - `warmup_session_count: int` (must be >= 0)
  - `initial_cash: Decimal` (must be > 0)
  - `protocol_hash: SHA256Hash`

### 4. RED Acceptance Criteria
- Unit tests fail initially because domain modules and admission gatekeeper do not exist.

### 5. GREEN Acceptance Criteria
- `ExploratoryEvaluationAdmissionV1` validates that `acknowledged_limitations` is non-empty.
- Self-excluding canonical hashing verifies `admission_hash`, `cost_model_hash`, and `protocol_hash`.
- `validate_promotion_admission` rejects any report where a dimension is not PASS or where snapshot hashes diverge.
- Discriminator `lane` correctly deserializes either admission variant from JSON.
- `EvaluationCostModelV1` enforces non-negative Decimals and computes exact costs for sample orders.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_lanes.py tests/unit/test_evaluator_protocol.py tests/unit/test_evaluator_costs.py tests/unit/test_evaluator_admission_gatekeeper.py -v
```

### 7. Adversarial Test Cases
- Attempt to create `ExploratoryEvaluationAdmissionV1` with empty limitations -> ValueError.
- Attempt to mutate `admission_hash` without changing payload -> ValueError mismatch.
- Promotion admission pointing to an M1e report with a failed or unknown dimension -> ValueError.
- Bundle snapshot hash not matching promotion admission snapshot hash -> ValueError.
- Attempt to pass negative basis points or negative fees into `EvaluationCostModelV1` -> ValueError.

### 8. Review and Commit Boundary
- Independent review covering lane separation, gatekeeper verification, hashing integrity, and Decimal precision.
- Commit message: `feat: add M2 evaluation lane admission, cost models, and promotion gatekeeper`
- Checkpoint execution.

---

## Task 2: Provider-Neutral Evaluation Input Bundle, Session Clock, and Deterministic Replay Identity

### 1. Objective
Implement the provider-neutral `EvaluationInputBundleV1` contract (acyclic, snapshot-linked), explicit schemas for session calendar entries and unadjusted session observations, the causal session scheduler (`SessionClockV1`) with warmup transition, and canonical evaluation run replay hashing.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_bundles.py`
- `src/drift/domain/evaluator_clock.py`
- `src/drift/evaluator/bundles.py`
- `tests/unit/test_evaluator_bundles.py`
- `tests/unit/test_evaluator_clock.py`

### 3. Contracts and Interfaces
- `SessionCalendarEntryV1(FrozenModel)`:
  - `session_key: SessionKeyV1`
  - `session_date: date`
  - `open_time_utc: UTCDateTime`
  - `close_time_utc: UTCDateTime`
  - `session_scope: Literal["regular"] = "regular"`
- `UnadjustedSessionObservationV1(FrozenModel)`:
  - `security_id: UUID7`
  - `session_key: SessionKeyV1`
  - `open_price: Decimal`
  - `close_price: Decimal`
  - `share_volume: int`
  - `is_halted: bool = False`
- `EvaluationInputBundleV1(FrozenModel)`:
  - `bundle_id: UUID7`
  - `evaluation_interval: TemporalIntervalClaimV1`
  - `source_snapshot_hash: SHA256Hash | None = None` (present for M1e promotion-qualified bundles)
  - `universe_bundle_hash: SHA256Hash`
  - `economic_context_hash: SHA256Hash`
  - `observation_context_hash: SHA256Hash`
  - `session_context_hash: SHA256Hash`
  - `normalization_policy_hashes: tuple[SHA256Hash, ...]`
  - `security_identities: tuple[SecurityV1, ...]`
  - `listing_identities: tuple[ListingV1, ...]`
  - `session_calendar: tuple[SessionCalendarEntryV1, ...]`
  - `unadjusted_observations: tuple[UnadjustedSessionObservationV1, ...]`
  - `decision_observation_views: tuple[DerivedObservationViewV1, ...]`
  - `corporate_action_occurrences: tuple[CorporateActionTermsVersionV1, ...]`
  - `bundle_hash: SHA256Hash`
- `SessionClockV1`:
  - Sequence of realized sessions within `evaluation_interval`.
  - Identifies warmup sessions: for session indices $0$ to $W-1$, `is_warmup == True`.
  - Warmup transition: session $W-1$ post-close is the first decision point where strategy targets are staged for session $W$ open execution.
- `evaluation_run_identity(...) -> SHA256Hash`:
  - Computes canonical hash over `(strategy_reference, parameters, input_bundle, protocol, cost_model, admission, code_hash, environment_hash)`.

### 4. RED Acceptance Criteria
- Unit tests fail with `ModuleNotFoundError` for `evaluator_bundles` and `evaluator_clock`.

### 5. GREEN Acceptance Criteria
- Input bundle self-hash validation verifies integrity without circular dependence on admission.
- Session clock correctly iterates regular sessions in strictly ascending calendar order.
- Warmup interval correctly flags the first $W$ sessions as non-trading, with session $W$ executing initial fills.
- Any change in constituent parameters, code hash, or environment hash alters `evaluation_run_identity`.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_bundles.py tests/unit/test_evaluator_clock.py -v
```

### 7. Adversarial Test Cases
- Circular hash deadlock test: verify `bundle_hash` computes cleanly without requiring admission.
- Out-of-order session calendar entries -> ValueError.
- Observation timestamp outside declared evaluation interval -> ValueError.
- Replaying with altered parameter dict yields distinct run hash.

### 8. Review and Commit Boundary
- Independent review covering calendar causality, bundle acyclic hashing, and snapshot linkage.
- Commit message: `feat: add M2 evaluation input bundle and session clock`
- Checkpoint execution.

---

## Task 3: Portfolio State, Cash Accounting, Whole-Share Positions, and Pending Claims Kernel

### 1. Objective
Implement the long-only, whole-share portfolio state representation, USD cash accounting, deterministic dividend receivables (`PendingCashClaimV1`), and weekend/holiday dividend settlement logic.

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
  - `claim_id: SHA256Hash` (deterministically derived from `security_id, action_kind, ex_session, payable_session`)
  - `security_id: UUID7`
  - `action_kind: ActionKind`
  - `entitled_quantity: int`
  - `cash_per_share: Decimal`
  - `total_cash_expected: Decimal`
  - `ex_session: date`
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
  - Methods: `apply_fill(fill)`, `record_claim(claim)`, `settle_claims(current_session_date)`, `mark_close(close_prices)`.
  - `settle_claims` settles all claims where `current_session_date >= claim.payable_session`.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_portfolio.py` and portfolio accounting classes do not exist.

### 5. GREEN Acceptance Criteria
- Adding holdings and updating cash balances enforces exact Decimal arithmetic.
- Deterministic claim ID generation produces identical hash across repeated runs.
- Claims payable on weekend dates settle cleanly on the first subsequent trading session.
- Marking portfolio at close computes exact holdings market value using unadjusted close prices.
- Pending claims contribute to NAV but do not alter `cash_balance` until settled.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_portfolio.py -v
```

### 7. Adversarial Test Cases
- Attempt to create `SecurityHoldingV1` with quantity <= 0 -> ValueError.
- Non-deterministic ID injection attack: verify identical inputs produce identical `claim_id`.
- Dividend payable on Saturday: verify claim settles on Monday trading session.
- Missing close mark for a currently held position -> IndeterminateValuationError.

### 8. Review and Commit Boundary
- Independent review covering Decimal precision, NAV reconciliation, and deterministic claim IDs.
- Commit message: `feat: add M2 portfolio state and cash accounting kernel`
- Checkpoint execution.

---

## Task 4: First-Class M1c Corporate Action and Economic Outcome Accounting

### 1. Objective
Implement the corporate action processing engine that applies M1c economic facts (splits, dividends, spin-offs, mergers, terminations) directly to portfolio state during Pre-Open and Intrasession phases, with automatic staged target scaling for overnight splits.

### 2. Exact Files Expected
- `src/drift/domain/evaluator_corporate_actions.py`
- `src/drift/evaluator/corporate_actions.py`
- `tests/unit/test_evaluator_corporate_actions.py`

### 3. Contracts and Interfaces
- `CorporateActionProcessor`:
  - `apply_pre_open_actions(portfolio_state, staged_targets, actions, current_session) -> tuple[PortfolioStateV1, tuple[SecurityTargetPositionV1, ...]]`
  - `apply_intrasession_settlements(portfolio_state, current_session) -> PortfolioStateV1`
- Action Handlers:
  - `ActionKind.FORWARD_SPLIT` / `REVERSE_SPLIT`:
    - Holdings quantity: $\text{new\_quantity} = \text{int}(\text{current\_quantity} \times n / d)$.
    - Cost basis preserved; average cost per share divides by $n / d$.
    - Staged target positions scaled: $\text{staged\_target}' = \text{int}(\text{staged\_target} \times n / d)$.
  - `ActionKind.REGULAR_CASH_DIVIDEND` / `SPECIAL_CASH_DISTRIBUTION`:
    - Ex-date creates `PendingCashClaimV1`.
    - Payable date settles into `cash_balance`.
  - `ActionKind.CASH_ACQUISITION`: removes target position, credits cash entitlement.
  - `ActionKind.STOCK_ACQUISITION`: converts target holding into acquirer holding using exchange ratio.
  - `ActionKind.MIXED_ACQUISITION`: credits cash entitlement and acquirer share holding.
  - `ActionKind.SPINOFF`: creates child security holding; if parent and child closing prices exist, NAV calculation is complete.
  - `ActionKind.LIQUIDATION`: credits known liquidation proceeds; missing terms fail closed to `INDETERMINATE`.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_corporate_actions.py` does not exist.

### 5. GREEN Acceptance Criteria
- 2-for-1 forward split doubles holdings AND doubles staged target positions, preserving intended delta.
- Cash dividend on ex-date logs receivable; payable date credits cash.
- Spin-off marks NAV cleanly when market prices exist, without requiring tax allocation percentages.
- Double-adjustment check: rejects any input where observations are already split-adjusted.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_corporate_actions.py -v
```

### 7. Adversarial Test Cases
- Split ratio with 0 denominator -> ValueError.
- Staged target scaling across split: verify post-split delta execution matches intended target.
- Bankruptcy delisting assumed to be zero without M1c proof -> IndeterminateValuationError.
- Dividend with missing cash per share -> IndeterminateValuationError.

### 8. Review and Commit Boundary
- Independent review covering staged target split-scaling, ActionKind alignment, and NAV spin-off decoupling.
- Commit message: `feat: add M2 corporate action accounting kernel`
- Checkpoint execution.

---

## Task 5: Target-Position Strategy Boundary, Deterministic Next-Open Fill Engine, and Cost Application

### 1. Objective
Implement the runtime strategy interface, `PositionViewV1`, the explicit complete target set omission rule, the sell-first/buy-second execution engine, Phase 2 cash solvency enforcement, and versioned cost/slippage application.

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
- `StrategyDecisionContextV1`:
  - `session_key: SessionKeyV1`
  - `decision_cutoff: UTCDateTime`
  - `admitted_universe: tuple[UUID7, ...]`
  - `current_holdings: tuple[PositionViewV1, ...]`
  - `current_cash: Decimal`
  - `portfolio_nav: Decimal`
  - `decision_views: Mapping[str, tuple[DerivedObservationViewV1, ...]]`
- `SecurityTargetPositionV1`:
  - `security_id: UUID7`
  - `execution_listing_id: UUID7`
  - `target_quantity: int` (must be >= 0)
- `StrategyDecisionIntentV1`:
  - `session_key: SessionKeyV1`
  - `decision_time: UTCDateTime`
  - `targets: tuple[SecurityTargetPositionV1, ...]`
- Explicit Complete Target Set Rule:
  - Any held security omitted from `targets` is assigned `target_quantity = 0` (liquidate all).
  - Securities removed from `admitted_universe` are permitted to have `target_quantity = 0`.
- `FillExecutionEngine`:
  - Delta calculation: $\Delta q_i = \text{staged\_target}_i - \text{current\_quantity}_i$.
  - Executes sells first ($\Delta q_i < 0$), buys second ($\Delta q_i > 0$).
  - Canonical order: sorted by `security_id` UUID bytes within phase.
  - Adverse slippage: Buy $P_{\text{open}}(1 + \text{bps}/10000)$, Sell $P_{\text{open}}(1 - \text{bps}/10000)$.
  - Transaction costs deducted from cash.
  - Cash solvency enforcement: if cash after sells is insufficient to fund all buys, emit `FillRejectionTraceEventV1`, reject unfunded buys, and classify evaluation as `EvaluationClassification.REJECTED`.

### 4. RED Acceptance Criteria
- Tests fail because `evaluator_strategy` and `evaluator_execution` do not exist.

### 5. GREEN Acceptance Criteria
- Strategy omitting a held security generates an automatic liquidation order ($\Delta q = -\text{current}$).
- Sells execute first, replenishing cash so subsequent buys succeed within the same open execution phase.
- Adverse slippage strictly increases buy prices and decreases sell prices.
- Cash shortfall emits `FillRejectionTraceEventV1` and marks scientific classification `REJECTED` without crashing.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_strategy.py tests/unit/test_evaluator_execution.py -v
```

### 7. Adversarial Test Cases
- Negative target quantity emitted in Phase 5 -> Rejected immediately.
- Strategy attempts entry (`target > 0`) for non-admitted security -> Rejected.
- Strategy attempts liquidation (`target = 0`) for non-admitted security -> Allowed.
- Cash exhaustion scenario: buy orders exceed cash -> `FillRejectionTraceEventV1` emitted, classified `REJECTED`.

### 8. Review and Commit Boundary
- Independent review covering omission liquidation semantics, sell-first sequencing, and Phase 2 cash solvency.
- Commit message: `feat: add M2 strategy protocol and next-open execution engine`
- Checkpoint execution.

---

## Task 6: Deterministic Session Evaluator Engine, Canonical Trace Generation, and M0 Integration

### 1. Objective
Assemble the complete 5-phase session evaluator loop, content-addressed trace logger, scientific classification system, complete result models (`ExploratoryEvaluationResultV1`, `PromotionEvaluationResultV1`, `EvaluationSummaryMetricsV1`), and integration with M0 `ExperimentSpecification` and `ExperimentRun`.

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
  - `ExploratoryEvaluationResultV1(FrozenModel)`: carries `lane: Literal["exploratory"]`, binds `ExploratoryEvaluationAdmissionV1`, `is_promotable = False`.
  - `PromotionEvaluationResultV1(FrozenModel)`: carries `lane: Literal["promotion"]`, binds `PromotionEvaluationAdmissionV1`, `is_promotable = True`.
- Fatal Indeterminacy Halting:
  - Encountering fatal missing price or unprovable outcome emits `IndeterminateCauseTraceEventV1`, immediately halts session stepping, and marks result `INDETERMINATE`.
- `SessionEvaluatorEngine.run(...) -> EvaluationResult`:
  - Orchestrates phases 1-5 for each session.
- `execute_experiment_run(spec, runner_context) -> ExperimentRun`:
  - Wraps M2 evaluator in M0 experiment runner, attaching trace and result artifact references.

### 4. RED Acceptance Criteria
- Tests fail because `engine.py`, `evaluator_trace.py`, and `evaluator_results.py` do not exist.

### 5. GREEN Acceptance Criteria
- Multi-session synthetic evaluation executes end-to-end through all 5 phases.
- Content-addressed trace log reproduces bitwise-identical hash on rerun.
- Fatal indeterminacy cleanly halts stepping and records `classification=INDETERMINATE` with `status=COMPLETED`.
- `ExperimentRun` records `status=COMPLETED`, binds artifact references, and includes metrics summary.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_evaluator_trace.py tests/unit/test_evaluator_engine.py tests/integration/test_evaluator_experiment_run.py -v
```

### 7. Adversarial Test Cases
- Attempt to construct `PromotionEvaluationResultV1` with `ExploratoryEvaluationAdmissionV1` -> Type/Validation error.
- Fatal missing open price: verify evaluator halts subsequent sessions and outputs `classification=INDETERMINATE`.
- Unhandled Python exception correctly marks `ExperimentRun` as `FAILED` with `error_details`.

### 8. Review and Commit Boundary
- Independent review covering 5-phase execution, fatal indeterminacy halting, and M0 experiment provenance.
- Commit message: `feat: add M2 session evaluator engine and trace logger`
- Checkpoint execution.

---

## Task 7: Comprehensive Adversarial Verification, Anti-Laundering Invariants, and Closed-World Replay Testing

### 1. Objective
Implement the complete 28-case adversarial acceptance test suite covering causality, universe rules, accounting basis, execution constraints, evidence lanes anti-laundering, and bitwise replay determinism.

### 2. Exact Files Expected
- `tests/adversarial/test_m2_causality.py`
- `tests/adversarial/test_m2_accounting.py`
- `tests/adversarial/test_m2_anti_laundering.py`
- `tests/adversarial/test_m2_replay_determinism.py`

### 3. Adversarial Invariants Tested (Table 25 of Spec)
- **Causality**: Same-bar close lookahead rejection, post-cutoff observation leakage rejection, terminal ticker fallback rejection, future corporate action leak rejection.
- **Universe**: Survivorship bias rejection, indeterminate eligibility exclusion, post-delisting entry rejection, post-delisting liquidation permission.
- **Accounting**: Double-adjustment rejection, premature dividend cash settlement rejection, vanishing receivables prevention, unevidenced delisting recovery rejection, unquantified merger rejection, missing close mark indeterminacy halting, negative cash balance prevention.
- **Execution**: Close-for-open fallback rejection, negative target rejection, fractional share rejection, sell-before-buy verification, cash shortfall rejection event.
- **Cost**: Cost parameter mutation run identity change, positive slippage rejection.
- **Evidence Lanes**: Circular hash deadlock prevention, lane upgrade impossibility, mutable boolean override impossibility, unqualified promotion admission rejection, exploratory bundle in promotion run rejection.
- **Replay Determinism**: Bitwise reproducibility of trace and NAV series across identical runs; parameter alteration changing run hash; deterministic claim IDs across re-runs.
- **Provider Boundary**: Raw vendor JSON rejection, missing halt inference rejection.

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
Build the bounded, offline Alpaca exploratory intake bridge to acquire free development market data for a declared cohort, map records into provider-neutral M1b-M1d contracts, bind canonical limitation constants in an `ExploratoryEvaluationAdmissionV1`, and execute an end-to-end exploratory smoke evaluation.

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
  - Acquired bytes stored in private root outside Git; writes `AcquisitionReceiptV1`.
  - Maps to `SecurityV1`, `ListingV1`, `UnadjustedSessionObservationV1`, `CorporateActionTermsVersionV1`.
  - Runs Drift public validators (`DatasetValidationDecisionV2`).
  - Mints `ExploratoryEvaluationAdmissionV1` binding the four canonical limitation constants:
    1. `ALPACO_LIMITATION_TRUNCATED_CA`
    2. `ALPACA_LIMITATION_UNVERSIONED_BARS`
    3. `ALPACA_LIMITATION_ABSENT_HALTS`
    4. `ALPACA_LIMITATION_BOUNDED_COHORT`
  - Emits `EvaluationInputBundleV1`.
- `intake_alpaca_exploratory.py`: CLI tool for bounded cohort acquisition.
- `test_alpaca_exploratory_smoke.py`:
  - Executes a complete exploratory evaluation run using the Alpaca development bundle and a simple reference strategy.
  - Confirms `ExploratoryEvaluationResultV1` is produced with `is_promotable=False`.
  - Standard CI/test execution uses recorded/pinned fixture bytes; network access is never required.

### 4. RED Acceptance Criteria
- Tests fail because `alpaca_exploratory.py` and smoke integration tests do not exist.

### 5. GREEN Acceptance Criteria
- Adapter maps Alpaca bars and corporate actions into valid Drift M1b-M1d domain instances.
- Drift public validators accept the mapped datasets.
- Exploratory admission artifact correctly records all four canonical limitation constants.
- Smoke evaluation executes end-to-end, producing an `ExploratoryEvaluationResultV1` and a complete trace log.
- All unit and integration tests run completely offline without `.env` or network access using pinned fixtures.

### 6. Focused Tests
```bash
uv run pytest tests/unit/test_alpaca_exploratory_adapter.py tests/integration/test_alpaca_exploratory_smoke.py -v
```

### 7. Adversarial Test Cases
- Missing API key gracefully skips network acquisition in CLI without raising uncaught exception.
- Evaluator core attempt to call Alpaca adapter directly -> Architecture boundary prevents import or raises error.
- Attempt to emit `PromotionEvaluationAdmissionV1` from Alpaca bridge -> Rejected.

### 8. Review and Commit Boundary
- Independent review covering network isolation, secret hygiene, limitation recording, and non-promotability.
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
