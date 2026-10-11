# Execution Safety Audit: Broker and Risk Integration (Phase 5)

This document presents the empirical architectural audit of Drift's broker,
risk, and execution subsystems (M13 through M18) conducted under Phase 5.
All findings are verified by empirical regression tests in
`tests/unit/test_execution_safety_audit.py`.

In accordance with Drift operating rules and ADR 0014, this audit is read-only
regarding live broker adapters and router authority. Live trading is strictly
prohibited, and all recommended structural remedies are presented as
Architecture Decision Packets for reviewer determination.

---

## 1. Summary of Audited Concerns

| Concern | Component | Symbol | Audit Status | Severity |
| :--- | :--- | :--- | :--- | :--- |
| **S1** | `execution.router`, `validation.engine`, `canary.orchestrator`, `autonomy.orchestrator` | `route_intent`, `submit_canary_intent`, `submit_autonomous_intent` | **CONFIRMED** | High |
| **S2** | `risk.gatekeeper`, `domain.shadow_broker` vs `domain.execution` | `HardRiskGatekeeper.evaluate_order` | **CONFIRMED** | High |
| **S3** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.cancel_intent` | **CONFIRMED** | Critical |
| **S4** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.submit_intent` | **CONFIRMED** | Critical |
| **S5** | `adapters.robinhood.adapter` | `RobinhoodAgenticAdapter.get_positions` | **CONFIRMED** | Critical |

---

## 2. Detailed Technical Audit

### S1. Hard Risk Policy Bypass on Order Submission Routes

- **Exact File and Symbol**:
  - `src/drift/execution/router.py`: `BrokerNeutralExecutionRouter.route_intent`
  - `src/drift/validation/engine.py`: `ShadowValidationEngine.route_intent`
  - `src/drift/canary/orchestrator.py`: `CanaryExecutionOrchestrator.submit_canary_intent`
  - `src/drift/autonomy/orchestrator.py`: `BoundedAutonomyOrchestrator.submit_autonomous_intent`
- **Reproduction Path**:
  - Direct router dispatch: Calling `router.route_intent(intent)` routes directly to `adapter.submit_intent(intent)` with zero gatekeeper evaluation.
  - Orchestrator dispatch: `ShadowValidationEngine`, `CanaryExecutionOrchestrator`, and `BoundedAutonomyOrchestrator` treat `risk_gatekeeper` as optional (`HardRiskGatekeeper | None = None`). When provided, they check only `risk_gatekeeper.journal.is_kill_switch_tripped()`.
  - Rate limit, order size limit, order notional limit, position concentration limit, and gross exposure limits are completely bypassed.
  - Verified in `tests/unit/test_execution_safety_audit.py::test_s1_router_bypasses_hard_risk_gatekeeper` and `test_s1_orchestrators_only_check_kill_switch_not_full_policy`.
- **Safety Invariant Violated**:
  - Non-negotiable pre-execution hard risk enforcement invariant (ADR 0011, ADR 0013): every order intent targeting broker execution must pass deterministic risk limits before reaching the transport adapter.
- **Smallest Safe Contract Change**:
  - Make `HardRiskGatekeeper` a mandatory dependency of `BrokerNeutralExecutionRouter`, or require an immutable, cryptographically hashed `RiskVerdictV1` reference attached to `OrderIntentV1` prior to routing.
- **Impact on Existing Callers**:
  - `route_intent` must receive current portfolio state and reference price, or query account/portfolio state prior to dispatch.
- **Necessary Tests**:
  - Positive: Valid order within all limits produces ALLOWED verdict and routes.
  - Negative: Orders exceeding rate limits, order notional, or exposure limits are rejected at the router boundary even if the kill switch has not latched.
- **Persisted Schema Change Required**:
  - None required for memory evaluation. Optional foreign key `risk_verdict_id` in `order_intents` table of `PersistentOrderIntentJournal`.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 1 below).

---

### S2. Domain Type Mismatch Between Risk Gatekeeper and Execution Router

- **Exact File and Symbol**:
  - `src/drift/risk/gatekeeper.py`: `HardRiskGatekeeper.evaluate_order`
  - `src/drift/domain/shadow_broker.py`: `SimulatedOrderV1`
  - `src/drift/domain/execution.py`: `OrderIntentV1`
- **Reproduction Path**:
  - `HardRiskGatekeeper.evaluate_order` expects `order: SimulatedOrderV1`, which requires simulated order fields (`order_id: UUID`, `side: str`, `price: Decimal`).
  - `BrokerNeutralExecutionRouter` accepts `intent: OrderIntentV1` (`intent_id: UUID`, `client_order_id: str`, `side: OrderSide`, `limit_price: Decimal | None`).
  - Calling `gatekeeper.evaluate_order(intent, ...)` fails with `AttributeError`.
  - Verified in `tests/unit/test_execution_safety_audit.py::test_s2_domain_type_mismatch_between_risk_and_execution`.
- **Safety Invariant Violated**:
  - Domain cohesion across risk and execution layers. The hard risk gatekeeper was coupled to M12 shadow simulation contracts rather than M14 broker-neutral execution contracts.
- **Smallest Safe Contract Change**:
  - Add `evaluate_intent(self, intent: OrderIntentV1, *, portfolio_state: PortfolioStateV2, current_price: Decimal | None, evaluation_time: datetime) -> RiskVerdictV1` to `HardRiskGatekeeper`, or accept a unified protocol implemented by both `SimulatedOrderV1` and `OrderIntentV1`.
- **Impact on Existing Callers**:
  - Zero breaking changes to existing `evaluate_order` callers in M12/M13 simulation harness.
- **Necessary Tests**:
  - Unit tests verifying `evaluate_intent` evaluates order notional, quantity, concentration, and gross exposure for `OrderIntentV1`.
- **Persisted Schema Change Required**:
  - None (`PersistentRiskJournal` stores `order_id: UUID`, which accommodates both `SimulatedOrderV1.order_id` and `OrderIntentV1.intent_id`).
- **Architecture/ADR Decision Required**:
  - Minor amendment to M13/M14 contract boundary (see Decision Packet 1).

---

### S3. Cancellation Failure Swallowed as Authoritative CANCELED

- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.cancel_intent` (lines 152-174)
- **Reproduction Path**:
  - `RobinhoodAgenticAdapter.cancel_intent(intent_id)` invokes `self._transport.call_tool("robinhood_cancel_order", {"order_id": broker_order_id})`.
  - The call is wrapped in `try ... except RobinhoodMcpError: pass`.
  - If the broker tool raises `RobinhoodMcpError` (e.g. HTTP 503, connection loss, or order already too late to cancel), the exception is swallowed.
  - The adapter unconditionally constructs and returns an `ExecutionReportV1` with `status=ExecutionStatus.CANCELED` and `leaves_quantity=0`.
  - The router persists this report, believing the order was cancelled, while the order remains active or filled on the broker.
  - Verified in `tests/unit/test_execution_safety_audit.py::test_s3_robinhood_cancellation_error_swallowed_as_canceled`.
- **Safety Invariant Violated**:
  - Truth-in-reporting invariant: an execution status report must represent actual confirmed broker state, never assumed success upon transport failure.
- **Smallest Safe Contract Change**:
  - If `RobinhoodMcpError` is raised during `robinhood_cancel_order`, do not emit `ExecutionStatus.CANCELED`. Instead, query `robinhood_get_order` to determine the true state. If query is unavailable, raise `RouterExecutionError` or mark intent as `CANCEL_FAILED` / `PENDING_RECONCILIATION`.
- **Impact on Existing Callers**:
  - Callers will not erroneously assume open risk is closed when broker cancellation fails.
- **Necessary Tests**:
  - Cancellation failure returns status reflecting failure or raises recoverable error.
- **Persisted Schema Change Required**:
  - None if `ExecutionStatus.REJECTED` or existing status is used; addition of `CANCEL_FAILED` or `UNKNOWN` if fine-grained status is adopted.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 2).

---

### S4. Ambiguous Submission Error Recorded as Authoritative Rejection

- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.submit_intent` (lines 93-107)
- **Reproduction Path**:
  - During `submit_intent`, `self._transport.call_tool("robinhood_place_order", args)` is invoked.
  - If network timeout, connection reset, or gateway 504 occurs, `RobinhoodMcpError` is raised.
  - The adapter catches the error and immediately constructs an `ExecutionReportV1` with `status=ExecutionStatus.REJECTED` and `broker_order_id=None`.
  - The router records the intent as rejected.
  - However, in reality, the order may have reached Robinhood and executed.
  - If an automated strategy or retry loop subsequently re-submits or assumes zero position, double-execution or unhedged exposure results.
  - Verified in `tests/unit/test_execution_safety_audit.py::test_s4_ambiguous_submission_error_marked_as_definitive_rejection`.
- **Safety Invariant Violated**:
  - Ambiguous state must fail closed to an uncertain state requiring reconciliation, rather than resolving to a false-negative rejection.
- **Smallest Safe Contract Change**:
  - When `RobinhoodMcpError` occurs during submission, do not record terminal `ExecutionStatus.REJECTED`. Mark state as `UNKNOWN` / `AMBIGUOUS_SUBMISSION` and initiate an idempotent query using `client_token` to confirm whether Robinhood accepted the order.
- **Impact on Existing Callers**:
  - Protects automated callers from double-submission hazards.
- **Necessary Tests**:
  - Submission network timeout triggers reconciliation via client token before final status resolution.
- **Persisted Schema Change Required**:
  - Addition of `ExecutionStatus.UNKNOWN` or `ExecutionStatus.PENDING_CONFIRMATION` to `drift.domain.execution.ExecutionStatus`.
- **Architecture/ADR Decision Required**:
  - Yes (see Decision Packet 2).

---

### S5. Unmapped Symbol Maps to Fabricated DNS UUID and Crashes Schema Validation

- **Exact File and Symbol**:
  - `src/drift/adapters/robinhood/adapter.py`: `RobinhoodAgenticAdapter.get_positions` (lines 254-257)
- **Reproduction Path**:
  - When Robinhood reports positions for symbols not present in `config.symbol_map`:
    ```python
    sec_id = self._reverse_symbol_map.get(sym)
    if sec_id is None:
        sec_id = uuid5(NAMESPACE_DNS, f"drift.equity.{sym}")
    ```
  - The adapter fabricates a UUIDv5 from the symbol string.
  - **Critical Empirical Discovery**: In `drift.domain.execution.BrokerPositionSnapshotV1`, the `security_id` field enforces strict UUIDv7 format (`@field_validator: identifiers must be UUIDv7 values`).
  - Because `uuid5` produces a version 5 UUID (not version 7), `build_broker_position_snapshot` raises a Pydantic `ValidationError` and crashes the entire `get_positions()` call!
  - Verified in `tests/unit/test_execution_safety_audit.py::test_s5_unknown_symbol_maps_to_fabricated_uuid`.
- **Safety Invariant Violated**:
  - (1) M0/M1 temporal provenance and security identity invariant: all security identifiers must resolve to verified historical security identities in the Drift evidence kernel, never ad-hoc fabricated UUIDs.
  - (2) Domain schema invariant: UUIDv7 is required for all entity identifiers across Drift domain models.
- **Smallest Safe Contract Change**:
  - Fail closed: unmapped symbols must either raise an `UnmappedSecurityError`, or unmapped positions must be quarantined into a separate unmapped positions collection rather than fabricating arbitrary IDs.
- **Impact on Existing Callers**:
  - Prevents total process crashes on unknown positions; isolates untracked assets from Drift portfolio accounting.
- **Necessary Tests**:
  - Positions with unmapped symbols fail closed or are quarantined cleanly without schema validation crashes.
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
  - *Option B (Cryptographic Risk Verdict Token)*: Require every `OrderIntentV1` to carry a signed/hashed `RiskVerdictV1` reference generated by `HardRiskGatekeeper.evaluate_intent`. The router verifies the verdict token prior to submission.
- **Tradeoffs / Evidence**:
  - Option A centralizes enforcement inside the router, making risk evasion impossible for any caller. However, it tightly couples the router to portfolio state and pricing feeds.
  - Option B keeps the router broker-neutral and stateless, but requires orchestrators to explicitly orchestrate risk evaluation before calling the router.
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
  - Option A guarantees zero unmapped assets exist in the account, but halts trading if any corporate action, dividend share, or manual deposit introduces an untracked ticker.
  - Option B allows portfolio reconciliation to operate cleanly on tracked assets while alerting operators to untracked holdings.
  - Option C dynamically resolves symbols, but introduces a historical provenance dependency into the execution adapter.
- **Recommended Option**:
  Option B: filter and quarantine unmapped positions while logging an alert to prevent schema crashes.
- **Exact Question Needed**:
  *How should broker adapters handle positions in securities that are not present in the configured Drift universe mapping?*
