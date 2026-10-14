# Execution Safety Audit: Broker and Risk Integration (Phase 5)

This document presents the empirical architectural audit of Drift's broker,
risk, and execution subsystems (M13 through M18) conducted under Phase 5,
updated to reflect baseline remediations merged in PR #362 and PR #364.
Defect reproduction, positive regressions, and safe-behavior regression tests
are retained in `tests/unit/test_execution_safety_audit.py` and
`tests/unit/test_execution_safety_robinhood.py`. Source observations, test
evidence, and proposed architecture remedies are distinct; a proposed remedy
is not an implemented or accepted control.

In accordance with Drift operating rules and ADR 0014, this audit is read-only
regarding live broker adapters and router authority. Live trading is strictly
prohibited, and all recommended structural remedies are presented as
Architecture Decision Packets for reviewer determination.

---

## 1. Summary of Audited Concerns

The five concerns (S1 through S5) are empirical execution and risk boundaries.
Following the integration of PR #362 (risk gatekeeper support for order intents
and canary orchestrator evaluation) and PR #364 (Robinhood adapter cancellation
and unmapped symbol quarantine), several bounded defects have been addressed,
while core architectural boundaries (direct-router bypass, optional gatekeepers,
and ambiguous timeout classification) remain open.

| Concern | Component | Symbol | Code Status | Live Trading Blocker | Severity |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **S1** | `execution.router`, `validation.engine`, `canary.orchestrator`, `autonomy.orchestrator` | `route_intent`, `submit_canary_intent`, `submit_autonomous_intent` | **PARTIALLY REMEDIATED** | **ABSOLUTE BLOCKER** | High |
| **S2** | `risk.gatekeeper`, `domain.shadow_broker` vs `domain.execution` | `HardRiskGatekeeper.evaluate_order` | **REMEDIATED (BOUNDED)** | **ABSOLUTE BLOCKER** | High |
| **S3** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.cancel_intent` | **PARTIALLY REMEDIATED** | **ABSOLUTE BLOCKER** | Critical |
| **S4** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.submit_intent` | **UNRESOLVED** | **ABSOLUTE BLOCKER** | Critical |
| **S5** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.get_positions` | **REMEDIATED (BOUNDED)** | **RESEARCH/ACCOUNTING LIMITATION** | Critical |

- **S1 (Partially Remediated)**: Configured orchestrator risk enforcement works. When `CanaryExecutionOrchestrator` is configured with a `HardRiskGatekeeper`, non-compliant order intents are evaluated and rejected pre-trade. However, direct-router bypass (`BrokerNeutralExecutionRouter.route_intent`) and optional missing gatekeepers (`risk_gatekeeper: HardRiskGatekeeper | None = None`) remain unresolved.
- **S2 (Remediated - Bounded)**: Original `OrderIntentV1` compatibility issue addressed. `HardRiskGatekeeper.evaluate_order` accepts `OrderIntentV1` and evaluates quantitative limits without raising `AttributeError`. This addresses contract mismatch but does not prove universal execution risk enforcement across all entry points.
- **S3 (Partially Remediated)**: Original unconditional false-CANCELED behavior addressed. `RobinhoodAgenticAdapter.cancel_intent` no longer unconditionally reports `CANCELED` upon transport failure, preserving the `cancellation_failed` reason. However, uncertain broker status after a cancellation failure remains a limitation; falling back to `REJECTED` does not establish that the broker order ceased to exist.
- **S4 (Unresolved)**: Client-token reconciliation was introduced to query existing orders after submission timeouts, but unconfirmed submission timeouts still fall back to `REJECTED`. This ambiguous terminal state leaves open double-execution hazards.
- **S5 (Remediated - Bounded)**: Original fabricated-UUID crash addressed through unmapped-position quarantine. Unmapped ticker symbols are filtered and tracked in `adapter.quarantined_symbols` rather than synthesizing invalid UUIDs that fail UUIDv7 validation. This quarantine isolates untracked assets from Drift accounting but does not constitute complete identity or portfolio-state authentication.

---

## 2. Detailed Technical Audit

### S1. Hard Risk Policy Bypass on Order Submission Routes

- **Status**: **PARTIALLY REMEDIATED** (Configured orchestrator risk enforcement works; direct-router bypass and optional missing gatekeepers remain unresolved)
- **Blocker Status**: **ABSOLUTE LIVE TRADING BLOCKER**
- **Defect Reproduction and Regression Tests**:
  - Direct router bypass reproduction: `tests/unit/test_execution_safety_audit.py::test_s1_reproduce_router_bypasses_hard_risk_gatekeeper`
  - Optional missing gatekeeper negative coverage: `tests/unit/test_execution_safety_audit.py::test_s1_orchestrator_permits_none_gatekeeper_bypassing_risk`
  - Configured orchestrator positive regressions: `tests/unit/test_execution_safety_audit.py::test_s1_configured_orchestrator_rejects_order_violating_hard_risk_policy` and `test_s1_safe_behavior_orchestrator_must_reject_order_exceeding_risk_policy`
  - Safe-behavior router regression (strict xfail): `tests/unit/test_execution_safety_audit.py::test_s1_safe_behavior_router_must_enforce_hard_risk_limits` (marked `@pytest.mark.xfail(strict=True)`)
- **Exact File and Symbol**:
  - `src/drift/execution/router.py`: `BrokerNeutralExecutionRouter.route_intent`
  - `src/drift/validation/engine.py`: `ShadowValidationEngine.route_intent`
  - `src/drift/canary/orchestrator.py`: `CanaryExecutionOrchestrator.submit_canary_intent`
  - `src/drift/autonomy/orchestrator.py`: `BoundedAutonomyOrchestrator.submit_autonomous_intent`
- **Audit Findings and State Reconciliation**:
  - Configured orchestrator enforcement: PR #362 updated `CanaryExecutionOrchestrator.submit_canary_intent` to evaluate `HardRiskGatekeeper.evaluate_order` when `self._risk_gatekeeper` is provided. If `verdict.status != RiskVerdictStatus.ALLOWED`, the order is rejected with `rejection_reason="risk_halt: ..."` prior to routing.
  - Direct router bypass: Calling `router.route_intent(intent)` routes directly to `adapter.submit_intent(intent)` with zero gatekeeper evaluation.
  - Optional missing gatekeeper: `CanaryExecutionOrchestrator` and `BoundedAutonomyOrchestrator` still treat `risk_gatekeeper` as optional (`HardRiskGatekeeper | None = None`). When omitted, order intents bypass hard risk evaluation and fill directly via the router.
  - S1 is not globally fixed. The ability to dispatch without hard-risk authorization remains an open vulnerability.
- **Safety Invariant Violated**:
  - Non-negotiable pre-execution hard risk enforcement invariant (ADR 0011, ADR 0013): every order intent targeting broker execution must pass deterministic risk limits before reaching the transport adapter.
- **Required Remediation**:
  - Proposed remedies are to make `HardRiskGatekeeper` a mandatory dependency of `BrokerNeutralExecutionRouter`, or require a verdict bound to the exact intent and evaluated risk context through a trusted artifact binding or signature. A bare hashed `RiskVerdictV1` reference is insufficient; the authority boundary remains a decision under Packet 1.
- **Impact on Existing Callers**:
  - `route_intent` must receive current portfolio state and reference price, or query account/portfolio state prior to dispatch.
- **Persisted Schema Change Required**:
  - None required for memory evaluation. Optional foreign key `risk_verdict_id` in `order_intents` table of `PersistentOrderIntentJournal`.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 1 below).

---

### S2. Domain Type Mismatch Between Risk Gatekeeper and Execution Router

- **Status**: **REMEDIATED (BOUNDED)** (Original OrderIntentV1 compatibility issue addressed; this does not prove universal execution risk enforcement)
- **Blocker Status**: **ABSOLUTE LIVE TRADING BLOCKER**
- **Defect Reproduction and Regression Tests**:
  - Intent evaluation and limit enforcement regression: `tests/unit/test_execution_safety_audit.py::test_s2_gatekeeper_evaluates_order_intent_v1_and_enforces_limits`
  - Safe-behavior regression: `tests/unit/test_execution_safety_audit.py::test_s2_safe_behavior_gatekeeper_evaluates_order_intent`
  - Risk gatekeeper test suite: `tests/unit/test_execution_safety_risk.py::test_gatekeeper_evaluates_order_intent_v1_without_portfolio_state`
- **Exact File and Symbol**:
  - `src/drift/risk/gatekeeper.py`: `HardRiskGatekeeper.evaluate_order`
  - `src/drift/domain/execution.py`: `OrderIntentV1`
  - `src/drift/domain/shadow_broker.py`: `SimulatedOrderV1`
- **Audit Findings and State Reconciliation**:
  - PR #362 updated `HardRiskGatekeeper.evaluate_order` to support `OrderIntentV1` polymorphically alongside `SimulatedOrderV1`. Rate, order size, notional, and concentration limits are now evaluated cleanly without `AttributeError`.
  - Bounded scope: Addressing contract compatibility allows `HardRiskGatekeeper` to evaluate `OrderIntentV1` when called, but does not prove universal execution risk enforcement across all order entry paths in the system.
- **Safety Invariant Violated**:
  - Domain cohesion across risk and execution layers. The hard risk gatekeeper was coupled to M12 shadow simulation contracts rather than M14 broker-neutral execution contracts.
- **Required Remediation**:
  - Contract compatibility has been implemented. Universal gatekeeper invocation across all dispatch paths remains tied to Decision Packet 1.
- **Impact on Existing Callers**:
  - Zero breaking changes to existing `evaluate_order` callers in M12/M13 simulation harness.
- **Persisted Schema Change Required**:
  - None (`PersistentRiskJournal` stores `order_id: UUID`, accommodating both `SimulatedOrderV1.order_id` and `OrderIntentV1.intent_id`).
- **Architecture/ADR Decision Required**:
  - Contract boundary resolved; architectural enforcement boundary remains under Decision Packet 1.

---

### S3. Cancellation Failure Swallowed as Authoritative CANCELED

- **Status**: **PARTIALLY REMEDIATED** (Original unconditional false-CANCELED behavior addressed; uncertain broker status after a cancellation failure remains a limitation)
- **Blocker Status**: **ABSOLUTE LIVE TRADING BLOCKER**
- **Defect Reproduction and Regression Tests**:
  - Error preservation regression: `tests/unit/test_execution_safety_audit.py::test_s3_cancellation_error_not_swallowed_and_preserves_failure_reason`
  - Safe-behavior regression: `tests/unit/test_execution_safety_audit.py::test_s3_safe_behavior_cancellation_error_fails_closed`
  - Robinhood unit test: `tests/unit/test_execution_safety_robinhood.py::test_s3_cancel_failure_does_not_falsely_emit_canceled`
- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.cancel_intent`
- **Audit Findings and State Reconciliation**:
  - PR #364 modified `RobinhoodAgenticAdapter.cancel_intent` so that transport exceptions (`RobinhoodMcpError`) are no longer silently swallowed to emit `ExecutionStatus.CANCELED`.
  - When cancellation fails, the adapter queries `get_intent_status` or retains existing status with `rejection_reason=f"cancellation_failed: {exc}"`.
  - Limitation: If broker status cannot be determined (e.g. no prior cached report and status query unavailable), the adapter falls back to `ExecutionStatus.REJECTED`. Emitting `REJECTED` or failing to cancel does not establish that the broker order stopped existing. Uncertain cancellation states remain an unresolved risk limitation under Decision Packet 2.
- **Safety Invariant Violated**:
  - Truth-in-reporting invariant: an execution status report must represent actual confirmed broker state, never assumed success upon transport failure.
- **Required Remediation**:
  - Implement an explicit uncertain cancellation state (`CANCEL_FAILED` or `PENDING_RECONCILIATION`) rather than falling back to terminal statuses that could misrepresent open broker commitments.
- **Impact on Existing Callers**:
  - Callers will not erroneously assume open risk is closed when broker cancellation fails.
- **Persisted Schema Change Required**:
  - Whether an existing status can accurately represent cancellation uncertainty remains a contract decision. Any new `CANCEL_FAILED` or `UNKNOWN` persisted enum member requires explicit acceptance and migration review; an existing terminal status must not be assumed to establish the broker outcome.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 2).

---

### S4. Ambiguous Submission Error Recorded as Authoritative Rejection

- **Status**: **UNRESOLVED**
- **Blocker Status**: **ABSOLUTE LIVE TRADING BLOCKER**
- **Defect Reproduction and Regression Tests**:
  - Defect reproduction: `tests/unit/test_execution_safety_audit.py::test_s4_reproduce_ambiguous_submission_error_marked_as_definitive_rejection`
  - Safe-behavior regression (strict xfail): `tests/unit/test_execution_safety_audit.py::test_s4_safe_behavior_submission_timeout_not_marked_rejected` (marked `@pytest.mark.xfail(strict=True)`)
  - Robinhood unit test: `tests/unit/test_execution_safety_robinhood.py::test_s4_submission_timeout_without_broker_order_fails_closed`
- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.submit_intent`
- **Audit Findings and State Reconciliation**:
  - PR #364 added client-token reconciliation (`_try_reconcile_by_client_token`) upon submission timeout.
  - However, when client-token reconciliation does not locate an existing order (or when the reconciliation query itself fails), the adapter constructs an `ExecutionReportV1` with `status=ExecutionStatus.REJECTED`.
  - Authoritatively marking an unconfirmed submission timeout as `REJECTED` remains a safety hazard: network timeouts do not prove non-receipt by the broker. If an automated caller treats the intent as rejected and re-submits, double-execution can occur.
- **Safety Invariant Violated**:
  - Ambiguous state must fail closed to an uncertain state requiring reconciliation, rather than resolving to a false-negative rejection.
- **Required Remediation**:
  - When `RobinhoodMcpError` occurs during submission and reconciliation is indeterminate, do not record terminal `ExecutionStatus.REJECTED`. Mark state as `UNKNOWN` / `AMBIGUOUS_SUBMISSION` and initiate reconciliation or trip the emergency kill switch.
- **Impact on Existing Callers**:
  - Protects automated callers from double-submission hazards.
- **Persisted Schema Change Required**:
  - Addition of `ExecutionStatus.UNKNOWN` or `ExecutionStatus.PENDING_CONFIRMATION` to `drift.domain.execution.ExecutionStatus`.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 2).

---

### S5. Unmapped Symbol Maps to Fabricated DNS UUID and Crashes Schema Validation

- **Status**: **REMEDIATED (BOUNDED)** (Original fabricated-UUID crash addressed through unmapped-position quarantine; quarantine does not constitute complete identity or portfolio-state authentication)
- **Blocker Status**: **RESEARCH AND ACCOUNTING INTEGRITY LIMITATION**
- **Defect Reproduction and Regression Tests**:
  - Quarantine and mapped preservation regression: `tests/unit/test_execution_safety_audit.py::test_s5_unmapped_positions_quarantined_without_crash_or_fabricated_uuid`
  - Safe-behavior regression: `tests/unit/test_execution_safety_audit.py::test_s5_safe_behavior_unmapped_symbol_quarantined_without_crash`
  - Robinhood unit test: `tests/unit/test_execution_safety_robinhood.py::test_s5_unmapped_positions_quarantined_without_schema_crash`
- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.get_positions`
- **Audit Findings and State Reconciliation**:
  - PR #364 eliminated DNS UUIDv5 fabrication. Unknown symbols in `get_positions` are added to `self._quarantined_symbols` and excluded from returned `BrokerPositionSnapshotV1` records, preventing Pydantic `ValidationError` crashes on UUIDv7 constraints.
  - Bounded scope: Quarantining unknown positions prevents crashes but does not provide complete historical identity resolution (M1b) or authenticated account portfolio reconciliation. Untracked holdings in a brokerage account remain unrepresented in Drift portfolio state.
- **Safety Invariant Violated**:
  - (1) M0/M1 temporal provenance and security identity invariant: all security identifiers must resolve to verified historical security identities in the Drift evidence kernel, never ad-hoc fabricated UUIDs.
  - (2) The inspected broker position model requires a UUIDv7 security identifier.
- **Required Remediation**:
  - Quarantine mechanism is active. Long-term dynamic resolution or external portfolio reconciliation remains under Decision Packet 3.
- **Impact on Existing Callers**:
  - Prevents position-query validation crashes when untracked assets exist in a brokerage account.
- **Persisted Schema Change Required**:
  - None.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 3).

---

## 3. Architecture Decision Packets

### Decision Packet 1: Pre-Execution Hard Risk Enforcement Boundary (S1 & S2)

- **What was discovered**:
  `BrokerNeutralExecutionRouter` dispatches `OrderIntentV1` directly to adapters without consulting `HardRiskGatekeeper`. Downstream orchestrators only inspect the boolean kill switch latch, bypassing all quantitative rate, order size, concentration, and exposure limits. Additionally, `HardRiskGatekeeper.evaluate_order` is typed to `SimulatedOrderV1` rather than `OrderIntentV1`.
- **Why a decision is needed**:
  Live or paper order execution cannot rely on optional upstream checks. A single non-negotiable risk barrier must guard the broker adapter boundary.
- **Viable Options**:
  - *Option A (Router-Internal Gating)*: Integrate `HardRiskGatekeeper` directly inside `BrokerNeutralExecutionRouter.route_intent`. The router requires portfolio state and market prices to evaluate risk before dispatching to any adapter.
  - *Option B (Cryptographic Risk Verdict Token)*: Require every `OrderIntentV1` to carry a `RiskVerdictV1` reference generated by a proposed `HardRiskGatekeeper.evaluate_intent`. The router would verify a signature or trusted artifact binding and bind the verdict to the exact intent and evaluated risk context before submission. A bare hash string is not proof of authorization.
- **Tradeoffs / Evidence**:
  - Option A centralizes enforcement for router-routed intents, but still requires all execution paths to respect that boundary. It couples the router to portfolio state and pricing feeds.
  - Option B can keep risk and portfolio evaluation outside the broker-neutral router, but requires callers to obtain a verifiable verdict. The router remains stateful through its persistent intent and execution-report journal.
- **Recommended Option**:
  Option A for single-process operations, or Option B if the router is envisioned as an independent service in future milestones.
- **Exact Question Needed**:
  *Should pre-execution hard risk gating be enforced directly within `BrokerNeutralExecutionRouter`, or should `OrderIntentV1` require an immutable `RiskVerdictV1` token before the router accepts it?*

---

### Decision Packet 2: Broker Cancellation Failure and Ambiguous Submission Protocol (S3 & S4)

- **What was discovered**:
  `RobinhoodAgenticAdapter` swallows cancellation transport errors and reports `ExecutionStatus.CANCELED`. Similarly, submission timeouts/network errors are marked as authoritative `ExecutionStatus.REJECTED`. Both behaviors present serious hazards of false-positive cancellation and double-submission.
- **Why a decision is needed**:
  Broker transport errors represent ambiguous execution states. The system must define an authoritative reconciliation protocol rather than fabricating deterministic terminal states.
- **Viable Options**:
  - *Option A (Fail-Closed with Ambiguous Status)*: Extend `ExecutionStatus` with `UNKNOWN` or `AMBIGUOUS`. Any transport failure during submission or cancellation transitions the intent to `UNKNOWN` and halts further automated actions on that intent until reconciled.
  - *Option B (Automated Client-Token Readback Reconciliation)*: Upon transport error, the adapter automatically executes a status query (`robinhood_get_order` / client token lookup). If reconciliation cannot confirm order status, raise `AmbiguousExecutionError` and trip the risk kill switch.
- **Tradeoffs / Evidence**:
  - Option A provides immediate fail-closed safety without complex retry logic, but requires handling non-terminal states across all orchestrators.
  - Option B minimizes manual intervention for transient network glitches, but requires resilient polling and backoff logic in the adapter.
- **Recommended Option**:
  Option B combined with Option A: attempt client-token lookup; if indeterminate, record `UNKNOWN` and trip the kill switch to halt trading.
- **Exact Question Needed**:
  *What state model and reconciliation policy should `BrokerAdapterProtocol` mandate when submission or cancellation suffers an ambiguous transport failure?*

---

### Decision Packet 3: External Broker Position Symbol Resolution (S5)

- **What was discovered**:
  `RobinhoodAgenticAdapter.get_positions` attempts to map unknown symbols to `uuid5(NAMESPACE_DNS, f"drift.equity.{sym}")`. Because domain models enforce UUIDv7, this triggers a Pydantic `ValidationError` and crashes the entire position query whenever an untracked asset is present in the Robinhood account.
- **Why a decision is needed**:
  Drift requires verified temporal provenance (M1b) for all security identities. Unmapped assets held in a brokerage account must not crash position queries or fabricate identities.
- **Viable Options**:
  - *Option A (Fail-Closed Exception)*: Raise `UnmappedBrokerSecurityError` if any position returned by the broker is not in `config.symbol_map`.
  - *Option B (Quarantined Positions Collection)*: Return recognized positions in `get_positions()` and expose unmapped positions in a separate `get_unmapped_positions()` inspection method.
  - *Option C (Dynamic M1b Security Master Lookup)*: Pass a security master resolver to the adapter to resolve ticker strings to canonical M1b security UUIDs at runtime.
- **Tradeoffs / Evidence**:
  - Option A refuses a position query when an unmapped asset is present. It does not remove that asset from the account, and a corporate action, dividend share, or manual deposit can still introduce an untracked ticker.
  - Option B allows portfolio reconciliation to operate cleanly on tracked assets while alerting operators to untracked holdings.
  - Option C dynamically resolves symbols, but introduces a historical provenance dependency into the execution adapter.
- **Recommended Option**:
  Option B: filter and quarantine unmapped positions while logging an alert to prevent schema crashes.
- **Exact Question Needed**:
  *How should broker adapters handle positions in securities that are not present in the configured Drift universe mapping?*

---

### Decision Packet 4: Tournament Advancement vs M11 Statistical Promotion Gate

- **What was discovered**:
  `TournamentRunner` issues `TournamentDecision.PROMOTED` when a challenger passes its paired comparison gates. M11 (`src/drift/domain/promotion.py`, `src/drift/promotion/gatekeeper.py`) exposes separate promotion and exploratory verdicts:
  `PromotionGateVerdict.PROMOTION_QUALIFIED` vs `PromotionGateVerdict.EXPLORATORY_PASSED`.
  The current M11 implementation selects that lane using caller/configuration booleans and accepts favorable defaults for omitted statistics. These unresolved trust and completeness concerns are tracked by [issue #360](https://github.com/KanujVerma/drift/issues/360); the enum value alone does not prove accepted M1e qualification or artifact provenance.
  Under ADR 0012, exploratory evaluation evidence (e.g. from Alpaca Basic development data) is strictly non-promotable and cannot be upgraded or relabeled into promotion-grade evidence. Promotion requires an independent evaluation run against an accepted promotion-qualified M1e dataset.
- **Why a decision is needed**:
  The term "promotion" is overloaded:
  1. In M10, `TournamentDecision.PROMOTED` denotes *internal research advancement* (a challenger replacing an incumbent champion as the benchmark reference in research memory).
  2. In M11, `PromotionGateVerdict.PROMOTION_QUALIFIED` names the intended scientific qualification outcome. Its current emission does not independently establish authenticated source qualification, and operational authorization remains separately gated.
  Calling an M10 match outcome "PROMOTED" risks confusing internal hypothesis advancement with canonical M11 promotion qualification.
- **Viable Options**:
  - *Option A (Terminology Alignment with Existing Enums)*: Keep existing persisted enums intact without schema migrations. Clarify contractually that `TournamentDecision.PROMOTED` represents internal tournament advancement only. To qualify for downstream milestones, an advanced candidate must subsequently pass M11's `PromotionGatekeeper`, which evaluates `is_promotion_grade_evidence` and `is_promotion_grade_authorized` to emit `PromotionGateVerdict.PROMOTION_QUALIFIED` (or `EXPLORATORY_PASSED`).
  - *Option B (Cap Tournament Outcomes in Exploratory Mode)*: Introduce an accepted representation for an exploratory outcome cap. `TournamentDecision.VALIDATED` is not an existing enum member; any new persisted verdict would require explicit contract and migration review before implementation.
  - *Option C (Introduce Distinct Persisted Enums)*: Migrate `TournamentDecision` schema to rename `PROMOTED` to `ADVANCED_AS_INCUMBENT` to remove all semantic ambiguity.
- **Tradeoffs / Evidence**:
  - Option A can preserve the existing enums without database or schema migration. M11 currently distinguishes verdict labels through caller/configuration flags, while evidence authenticity and omitted-statistics handling remain unresolved under issue #360.
  - Option B eliminates the word "PROMOTED" in exploratory runs, but changes existing M10 tournament behavior where champions are replaced by successful challengers.
  - Option C provides the cleanest vocabulary, but breaks serialized tournament history and backwards compatibility.
- **Recommended Option**:
  Option A: Maintain existing persisted enums (`TournamentDecision.PROMOTED` in M10 and `PromotionGateVerdict` in M11). Treat M10 advancement as internal research selection. M11 is the intended downstream scientific qualification interface, but its current verdict is not authenticated qualification proof while issue #360 is unresolved. Neither milestone authorizes live trading or broker connections.
- **Exact Question Needed**:
  *Should Drift formally designate M10's `TournamentDecision.PROMOTED` as internal research benchmark advancement while reserving canonical promotion authority exclusively for M11's `PromotionGateVerdict.PROMOTION_QUALIFIED`?*

---

### Decision Packet 5: Research Proposal Parameter Correspondence (Universe and Cadence)

- **What was discovered**:
  `ExperimentSpecificationProposalV1` includes `universe_id: str` and `rebalance_frequency: str`. However, M3 deterministic reference strategies operate on whatever universe is embedded in the evaluation input bundle, and their rebalance cadence is governed by strategy constructor parameters (`rebalance_dates` in B3) rather than proposal fields.
- **Why a decision is needed**:
  Proposal parameters that have no semantic effect on instantiated strategies create a false audit trail, where proposals appear to request specific universes and rebalance frequencies that are ignored during execution.
- **Viable Options**:
  - *Option A (Semantic Validation)*: Validate that `proposal.universe_id` strictly matches `bundle.universe_id`, and that `proposal.rebalance_frequency` matches strategy cadence constraints; fail closed on mismatch.
  - *Option B (Parameter Delegation)*: Bind `universe_id` and `rebalance_frequency` directly into strategy instantiation logic (e.g. dynamically generating rebalance dates for B3 based on proposal frequency).
  - *Option C (Schema Cleanup)*: Remove unutilized fields from `ExperimentSpecificationProposalV1` until dynamic universe slicing and schedule generation are implemented.
- **Tradeoffs / Evidence**:
  - Option A can preserve the proposal schema and reject the specified universe/cadence mismatches. Those checks do not establish general scientific integrity or source qualification.
  - Option B increases M3 strategy flexibility but requires substantial scheduling infrastructure.
  - Option C simplifies domain models but requires migrating existing research memory records.
- **Recommended Option**:
  Option A: enforce strict agreement between proposal parameters and bundle/strategy attributes.
- **Exact Question Needed**:
  *How should `universe_id` and `rebalance_frequency` in experiment proposals correspond to evaluation bundle universe and strategy rebalance schedule?*

---

### Decision Packet 6: Replay-Bound Evidence Verification at Tournament Boundary (STATUS: OPEN)

- **What was discovered**:
  M2 deterministic session evaluation binds input bundles, admissions, protocols, cost models, code version, and environment closure into `EvaluationRunArtifactsV2`, generating deterministic `result_hash` and `trace_hash`.
  At the M10 tournament boundary, `TournamentRunner` receives metric dictionaries. In PR #350, `M2TrialEvaluatorAdapter` exposes `result_hash`, `trace_hash`, `bundle_hash`, `cost_model_hash`, and `protocol_hash`.
  At the reviewed source snapshot `e85db5a39d6cce00b94d51079ae736dc8e5a05dd`, the runner rejects explicitly mock or synthetic results in genuine mode; checks bundle, cost, and protocol identity presence/equality; rejects scalar text/binary calendars; and checks nonempty aligned calendars, return counts, and exact True PnL completeness. It does not inspect result/trace hashes, validate hash formats, authenticate retained artifacts, or execute an independent replay verifier.
  Different competitors' result/trace hashes need not match. Identical deterministic evaluations can share hashes; neither equality nor inequality alone establishes authenticity.
  However, standalone `result_hash` and `trace_hash` strings do not cryptographically authenticate an M2 computation. An untrusted or adversarial caller can supply arbitrary matching hash strings in an in-memory dictionary.
  Hash presence and equality provide consistency checks across comparisons; they do NOT by themselves prove:
  - authentic M2 execution;
  - source completeness;
  - source qualification;
  - trace validity;
  - artifact provenance.
  Furthermore, O(1) in-memory hash equality checks cannot replace a trusted, authenticated artifact registry or independent cryptographic replay verification.
- **Why a decision is needed**:
  Running full synchronous M2 session replay inside `TournamentRunner` for every tournament match would add replay computation and may require bundle reconstruction during matches. The compute cost has not been measured; no fixed multiplier is established. Conversely, treating bare hash strings as proof of genuine evaluation without registry attestation or replay checks leaves a verification gap. Protected replay contracts (such as `pyproject.toml`, pinned manifests, and frozen models) must not be weakened or altered.
- **Viable Options**:
  - *Option A (Consistency Hash Checking with Deferred Replay Audit)*: Preserve current identity/calendar consistency checks and consider additional witness presence or format checks only under accepted contracts. This option would require independent M2 replay verification against an authenticated artifact store at the M11 entry boundary before candidate qualification. That downstream verification placement is a proposal, not an implemented or accepted control.
  - *Option B (Synchronous End-to-End Replay in Tournament)*: `TournamentRunner` instantiates a secondary `SessionEvaluatorEngine` and re-runs each strategy to verify bit-for-bit output match before certifying the tournament result.
  - *Option C (Offline Batch Replay Auditor)*: Tournaments execute with consistency hashes, and an asynchronous audit job independently re-verifies traces in authenticated research memory before archiving.
- **Tradeoffs / Evidence**:
  - Option A performs constant-size hash equality work for fixed-size identities, linear calendar equality checks in the session count, and return-count agreement checks during research tournaments. Bare hash presence is only consistency evidence, not proof of authenticity or source qualification; the proposed downstream M11 replay gate is not implemented or accepted.
  - Option B would add synchronous replay computation and any required input reconstruction to tournament rounds. Its runtime and memory costs require measurement, and verification still depends on trusted inputs and replay contracts.
  - Option C provides asynchronous verification, but risks delayed detection of unverified trials.
- **Recommended Option**:
  Proposed Option A: retain strict consistency checks at the tournament boundary and treat them as consistency evidence rather than cryptographic proof. Add a full M2 replay audit against an authenticated artifact store before M11 qualification only after the architecture and consumed contracts are accepted.
- **Status**:
  OPEN - Pending external architecture review. No new persisted evidence schema is implemented and no promotion authority is activated.
- **Exact Question Needed**:
  *Should Drift treat in-memory artifact hashes at the M10 tournament boundary strictly as consistency checks (Option A) and require a full M2 replay audit against an authenticated artifact store at the M11 promotion boundary, rather than executing synchronous replay verification inside every tournament match?*
