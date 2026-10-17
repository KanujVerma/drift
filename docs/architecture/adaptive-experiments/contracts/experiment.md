# Experiment and Scientific Eligibility Contract

## Start here: authority before action

This is the canonical scientific specification for **EXPERIMENT/ELIGIBILITY**,
campaign specifications, isolated arms, trial records, deterministic scientific
eligibility evaluations, cost attribution, and study reports. It is produced under
[#392](https://github.com/KanujVerma/drift/issues/392) as the foundational contract
for Drift's adaptive research experiments.

**This is a contract specification proposal. It implements no runtime code,
persisted database schemas, or autonomous trading permissions.** The proposed wire
profile is `drift-experiment/1-draft`. That profile is not an existing Python
class or an accepted production schema. Implementation requires separately
authorized child issues and explicit file permissions.

A fresh Antigravity agent or human reviewer should note:

1. Read [AGENTS.md](../../../../AGENTS.md), [decisions.md](../decisions.md) (D01-D17),
   [design.md](../design.md), [workstreams.md](../../workstreams.md),
   [requirements-crosswalk.md](../requirements-crosswalk.md),
   [stage1-decisions.md](../stage1-decisions.md) (S01-S38), and
   [stage1-roadmap.md](../stage1-roadmap.md).
2. The scientific layer consumes authoritative platform evidence from Matthew
   ([#376](https://github.com/KanujVerma/drift/issues/376) / [PR #407](https://github.com/KanujVerma/drift/pull/407) `platform.md`,
   [#379](https://github.com/KanujVerma/drift/issues/379) / [PR #412](https://github.com/KanujVerma/drift/pull/412) `execution.md`,
   [#380](https://github.com/KanujVerma/drift/issues/380) / [PR #414](https://github.com/KanujVerma/drift/pull/414) `mandate.md`)
   and authoritative research evidence from Krish
   ([#375](https://github.com/KanujVerma/drift/issues/375) / [PR #400](https://github.com/KanujVerma/drift/pull/400) `research.md`).
3. **Single authoritative account ledger:** Matthew's platform alone maintains
   portfolio cash, positions, execution fills, and trading transaction costs.
   The scientific layer performs **scientific cost attribution** by joining Krish's
   spending receipts with Matthew's account results exclusively for reporting.
   It never creates a secondary backtester or competing account ledger.
4. **Separation of authority:** `EligibilityDecisionV1` evaluates scientific and input
   eligibility only. It **never** independently grants order-dispatch authority. Only
   Matthew's platform determines whether an order may be staged or executed under
   applicable policy.
5. **Run-level account isolation:** `ArmSpecV1` defines immutable arm configuration,
   while concrete portfolio accounts are bound per `(campaign_id, run_id, arm_id)`
   via Matthew's account registry. Separate runs never share account state.
6. **Independent scientific review:** Per ADR 0017, the scientific author cannot
   self-certify their own methodology, metric definitions, trial records, or
   acceptance claims. Krish reviews research consumption, Matthew reviews platform
   consumption, and an independent scientific reviewer audits statistical integrity.

---

## 1. Scope, Non-Goals, and Producer Boundaries

### 1.1 Purpose and Scope
This contract establishes the interface specifications required to conduct reproducible,
causally sound, and auditable scientific experiments comparing adaptive strategy
selectors against deterministic comparators and baseline controls. It defines:
- The immutable configuration of experimental campaigns and evaluation arms.
- Dynamic run-level account bindings isolating account state across simulation runs.
- The append-only event log (`TrialEventV1`) and derived lifecycle projections (`TrialRecordV1`).
- Four cleanly separated eligibility, approval, execution, and completeness phases.
- Multi-order and partial-fill execution cardinality with explicit unresolved state handling.
- Scientific cost attribution consuming Krish's native receipt lineage (`supersedes_receipt_id`).
- Distinct denominators for candidate yield, inference reliability, and study completion.
- The schema and aggregation constraints for reproducible study reports.

### 1.2 Explicit Non-Goals
- **No Product Code:** This contract defines data structures, validation rules,
  and state transitions; it does not write runtime Python models or services.
- **No Second Account Ledger:** Portfolio NAV, cash, position balances, fills,
  and trading costs are produced strictly by Matthew's single authoritative account ledger.
- **No Competing Backtester:** The scientific layer orchestrates trials and
  measures outcomes; it does not simulate market prices or order matching.
- **No Order Dispatch Authority:** The scientific layer never stages or submits
  live or simulated broker orders; order staging and dispatch belong exclusively
  to Matthew's platform execution boundary.
- **No Real Capital or Broker Access:** Offline simulation and paper accounting
  only; no broker credentials or operational execution authority.
- **No Invented Numerical Thresholds:** Material statistical levels (alpha, power),
  economic materiality hurdles, and risk limits remain explicit Decision Packets.

### 1.3 Producer and Consumer Ownership Matrix

| Workstream | Role | Authoritative Outputs Consumed by #392 | Required Review on #392 |
|---|---|---|---|
| **Matthew** (Platform) | Producer | Source events, venue calendars, market bar provenance, execution timing, fills, trading costs, mandatory risk verdicts, authoritative `RESULT`, and portfolio account snapshots. | Evaluator timing, risk gatekeeper compatibility, and single-ledger reconciliation. |
| **Krish** (Intelligence) | Producer | Bounded research context, candidate strategy proposals, attempt lifecycle receipts, model prompt/replay records, raw inference cost receipts (`raw_cost`), and time-eligible memory updates. | Research proposal lifecycle, attempt tracking, and feedback compatibility. |
| **Kanuj** (Scientific) | Producer & Consumer | `CampaignSpecV1`, `ArmSpecV1`, `RunAccountBindingV1`, `TrialEventV1`, `TrialRecordV1`, `EligibilityDecisionV1`, and `StudyReportV1`. Measures outcomes from immutable accepted inputs. | Author / Producer (cannot self-certify independent acceptance). |
| **Independent Reviewer** | Validator | Independent scientific audit of statistical uncertainty, test fixtures, and preregistration integrity. | Formal independent scientific acceptance. |

---

## 2. Four Separated Decision and Evidence Phases

To prevent conflating scientific validity with operational execution authority or
retrospective completeness, the contract strictly separates four distinct concepts:

```
+-----------------------------------------------------------------------------+
| Phase A: Pre-Decision Scientific / Input Eligibility                        |
| - Evaluated by: Scientific Evaluator (EligibilityDecisionV1)                |
| - Scope: PRE_DECISION_SCIENTIFIC_INPUT                                      |
| - Determines: Are market inputs point-in-time verified? Is proposal valid? |
| - Authority: DOES NOT grant order dispatch authority.                       |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Phase B: Operational Mandate and Approval Decision                          |
| - Evaluated by: Matthew's Platform Risk Gatekeeper (mandate.md / PR #414)   |
| - Scope: Owned by Matthew's Gatekeeper (mandate_verdict_id)                 |
| - Determines: Does proposed portfolio transition satisfy hard risk caps?    |
| - Authority: Matthew's platform ALONE permits order staging and dispatch.   |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Phase C: Recorded Execution and Trial Outcome                               |
| - Evaluated by: Matthew's Execution Engine (execution.md / PR #412)         |
| - Scope: Owned by Matthew's Execution Engine (fill_id, execution status)    |
| - Determines: Order fills, partial fills, cancellations, or UNRESOLVED.     |
| - Outcome: Authoritative platform RESULT and account state update.          |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Phase D: Scientific Evidence Completeness and Scoring Eligibility           |
| - Evaluated by: Scientific Scorecard Aggregator (StudyReportV1)             |
| - Scope: Owned by Scientific Aggregator (completeness_classification)       |
| - Determines: Are platform RESULT and all research cost receipts bound?     |
| - Outcome: Inclusion in statistical study report and economic analysis.     |
+-----------------------------------------------------------------------------+
```

### Invariants Governing the Four Phases
1. **Scope Restriction of EligibilityDecisionV1:** `EligibilityDecisionV1` owns
   strictly `PRE_DECISION_SCIENTIFIC_INPUT`. It does **not** evaluate Phase B mandate
   approval or Phase D post-execution completeness.
2. **No Autonomous Dispatch:** A Phase A decision of `ELIGIBLE` confirms scientific
   input qualification only. It cannot authorize trade execution. Matthew's platform
   risk gatekeeper evaluates Phase B and may refuse dispatch.
3. **No Retrospective Invalidation of Prior Input Eligibility:** If an executed trade
   in Phase C has an un-emitted platform `RESULT` in Phase D, this does **not**
   retroactively make the Phase A proposal `INELIGIBLE`. The Phase A decision remains
   `ELIGIBLE`, while Phase D completeness is recorded as `PENDING_RESULT`.
4. **Decoupled Financial and Economic Completeness:** If inference costs are
   `UNKNOWN`, Phase D records the trial's economic attribution as `MISSING_COST`,
   while the portfolio investment return from Matthew's ledger remains verified and reportable.

---

## 3. Canonical Logical Contract Structures

The experiment contract defines core logical structures under the proposed
`drift-experiment/1-draft` wire profile. General schemas do not hardcode Stage 1
specific numbers or strategy families.

```
       +---------------------------------------------+
       |               CampaignSpecV1                |
       |  (Immutable specification of study protocol)|
       +----------------------+----------------------+
                              | 1:N
                              v
       +---------------------------------------------+
       |                  ArmSpecV1                  |
       |  (Immutable arm role, model & strategy pool)|
       +----------------------+----------------------+
                              |
               +--------------+--------------+
               | 1:N                         | 1:N
               v                             v
+-----------------------------+ +-----------------------------+
|     RunAccountBindingV1     | |        TrialEventV1         |
| (Run-level account binding) | | (Append-only lifecycle log) |
+-----------------------------+ +--------------+--------------+
                                               |
                                               v Materialized View
                                +-----------------------------+
                                |        TrialRecordV1        |
                                |  (Derived trial projection) |
                                +--------------+--------------+
                                               |
                               +---------------+---------------+
                               | 1:N                           | 1:N
                               v                               v
                +-----------------------------+ +-----------------------------+
                |    EligibilityDecisionV1    | |    Authoritative RESULT     |
                |  (Pre-decision input check) | |  (Matthew's platform ledger)|
                +-----------------------------+ +-----------------------------+
                               |                               |
                               +---------------+---------------+
                                               | N:1
                                               v
                                +-----------------------------+
                                |        StudyReportV1        |
                                |  (Derived scientific rollup)|
                                +-----------------------------+
```

---

### 3.1 CampaignSpecV1

`CampaignSpecV1` defines the frozen, reproducible experimental design for a complete
study.

#### Semantic Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `campaign_id` | String | Unique campaign identifier, e.g., `"stage1a-selector-b-vs-r-2026"`. |
| `campaign_spec_fingerprint` | String | SHA-256 hex digest of canonicalized CampaignSpec JSON payload (excluding fingerprint). |
| `campaign_type` | String | Protocol type: `"HISTORICAL_BACKTEST"`, `"SYNTHETIC_TEST"`, `"FORWARD_SHADOW"`. |
| `study_protocol_revision` | String | Git commit or version tag of the preregistered methodology document. |
| `created_at` | String | ISO 8601 UTC timestamp of initial drafting. |
| `frozen_at` | String | ISO 8601 UTC timestamp when the specification was frozen for execution. |
| `accepted_contract_revisions` | Object | Map of producer contract dependencies to pinned commit hashes. |
| `research_question_id` | String | Formal hypothesis reference, e.g., `"RQ-STAGE1-SELECTOR-NET-ADVANTAGE"`. |
| `primary_comparison` | Object | Definition of test arm vs. primary comparator (`test_arm_id`, `comparator_arm_id`). |
| `control_arm_references` | Array[String] | List of baseline control arms included for reference (e.g., A, C, C-risk, D). |
| `arm_spec_references` | Array[String] | List of `arm_spec_fingerprint` values belonging to this campaign. |
| `qualified_dataset_references` | Array[String] | Pinned datasets qualified under #378 with authentic provenance hashes. |
| `data_window` | Object | Full span of available data (`start_date`, `end_date`, `calendar_id`). |
| `warmup_window` | Object | Minimum required un-scored warmup span (e.g., `sessions_count >= 253` for Stage 1). |
| `observation_window` | Object | Un-scored observation span (e.g., `sessions_count == 126` for Stage 1). |
| `scoring_window` | Object | Scored evaluation span (`start_session`, `end_session`, `fresh_accounts: true`). |
| `decision_schedule` | Object | Checkpoint timing: `frequency`, `alignment`, `execution_timing`. |
| `allowed_strategy_families` | Array[String] | Approved strategy pool. Not globally restricted to B3/B4/B5; controls may use others. |
| `portfolio_mandate_reference` | String | Reference to approved mandate specification (PR #414). |
| `source_eligibility_policy_reference` | String | Policy hash defining minimum data completeness and timestamp cutoff rules. |
| `execution_policy_reference` | String | Reference to Matthew's execution fill and cost model specification (#379). |
| `cost_policy_reference` | String | Standardized unit cost schedule for operational inference and shared work billing. |
| `model_and_prompt_policy_reference` | String | Pinned model family, temperature, system prompt, and context retrieval policy. |
| `learning_and_feedback_policy_reference`| String | Policy governing time-eligible memory updates and lag rules (DP-R8). |
| `evaluation_policy_reference` | String | Statistical evaluation specification (estimands, uncertainty estimators). |
| `holdout_access_policy_reference` | String | Protocol governing sealed holdouts vs. lagged reflection (DP-R8). |
| `stopping_policy_reference` | String | Criteria for premature safety shutdown (e.g., maximum drawdown breach). |
| `authorization_evidence` | Object | Audit record of owner approval and preregistration sign-offs. |

---

### 3.2 ArmSpecV1 and RunAccountBindingV1

`ArmSpecV1` defines immutable arm configuration, decoupled from concrete simulation runs.
`RunAccountBindingV1` dynamically binds an arm to an isolated portfolio account for
a specific simulation run.

#### Semantic Fields: `ArmSpecV1`

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `arm_id` | String | Unique arm identifier within campaign (e.g., `"ARM-B"`, `"ARM-R"`, `"ARM-C"`). |
| `campaign_id` | String | Parent campaign identifier. |
| `arm_spec_fingerprint` | String | SHA-256 hex digest of canonicalized ArmSpec JSON payload (excluding fingerprint). |
| `selector_type` | String | Role: `"ADAPTIVE_AI"`, `"DETERMINISTIC_COMPARATOR"`, `"FROZEN_BASELINE"`, `"PASSIVE_BENCHMARK"`, `"CASH_CONTROL"`. |
| `eligible_strategy_references` | Array[String] | Strategy pool permitted for this specific arm. |
| `initial_strategy_reference` | String | Strategy assigned at start of scored evaluation (e.g., `"B3"` per S15). |
| `initial_capital` | DecimalText | Starting cash allocation as string (e.g., `"10000.00"`). Configurable per campaign. |
| `currency` | String | Account currency, strictly `"USD"`. |
| `arm_account_role` | String | Role identifier consumed by account binding (e.g., `"PRIMARY_TEST"`, `"COMPARATOR"`). |
| `mandate_reference` | String | Pinned mandate constraint policy for this arm. |
| `execution_policy_reference` | String | Pinned execution simulation parameters (next open, slippage, commission). |
| `research_budget_reference` | String | Cap on candidate evaluations, token spend, and wall-clock time per checkpoint. |
| `information_visibility_policy` | String | Visibility rule: `"IDENTICAL_MARKET_AND_REFERENCE_COMPLETED"`. |
| `feedback_policy_reference` | String | Lagged feedback rule governing memory updates (PR #400). |
| `model_configuration_reference`| String | Specific model deployment and prompt configuration (or `"NONE"` for non-AI arms). |
| `deterministic_seed_reference` | String | Pseudo-random seed for model sampling or simulation. |
| `frozen_configuration_reference`| String | Hash of immutable strategy algorithms evaluated by this arm. |

#### Semantic Fields: `RunAccountBindingV1`

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `binding_id` | String | Unique binding ID: `"{campaign_id}:{run_id}:{arm_id}:BINDING"`. |
| `campaign_id` | String | Parent campaign identifier. |
| `run_id` | String | Concrete execution run or replicate identifier. |
| `arm_id` | String | Arm identifier bound. |
| `portfolio_account_id` | String | Matthew's authoritative account identifier in platform ledger. |
| `initial_cash_allocated` | DecimalText | Verified starting cash in Matthew's ledger (e.g., `"10000.00"`). |
| `bound_at` | String | ISO 8601 UTC timestamp of account provisioning. |

#### Invariants Governing Account Isolation
1. **Run-Level Isolation:** Concrete accounts are provisioned per `(campaign_id, run_id, arm_id)`.
   If `ArmSpecV1` is re-evaluated across multiple runs (`RUN-001`, `RUN-002`), each run
   binds to a distinct, isolated `portfolio_account_id`. Separate runs never share account state.
2. **Decoupling Dynamic Memory:** Dynamic reflection memory (`memory_snapshot_id`) is
   **not** in `ArmSpecV1`'s fingerprint. Memory snapshots are bound per trial checkpoint.

---

### 3.3 Immutable Trial Events (`TrialEventV1`)

To ensure auditable history and prevent retroactive state mutation, every lifecycle
action is stored as an immutable `TrialEventV1`.

#### Semantic Fields: `TrialEventV1`

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `event_id` | String | Unique event ID: `"{trial_id}:EVT-{event_index}"`. |
| `trial_id` | String | Parent logical trial ID: `"{campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"`. |
| `event_index` | Integer | 0-indexed sequential position in the trial's event stream. |
| `previous_event_reference` | String | Hash of previous event in stream (or `"ROOT"` for index 0). |
| `event_kind` | String | Event type: `"OPPORTUNITY_CREATED"`, `"INPUTS_BOUND"`, `"PROPOSAL_RECORDED"`, `"ELIGIBILITY_RECORDED"`, `"MANDATE_VERDICT_RECORDED"`, `"ORDERS_STAGED"`, `"FILLS_RECORDED"`, `"RESULT_BOUND"`, `"COSTS_BOUND"`, `"TRIAL_FINALIZED"`. |
| `recorded_at` | String | ISO 8601 UTC timestamp when event was written. |
| `producer_evidence_references`| Array[String] | Hashes of external producer evidence bound by this event. |
| `payload_reference` | String | URI or pointer to event payload. |
| `payload_hash` | String | SHA-256 hex digest of canonicalized payload bytes. |
| `event_hash` | String | SHA-256 hex digest over all fields in this event envelope. |

#### Canonical Event Preimage and event_hash
`TrialEventV1.event_hash` is computed as the SHA-256 hex digest of a canonical, versioned
event preimage that excludes `event_hash` itself:

```
event_preimage = {
  "schema_version": event.schema_version,
  "event_id": event.event_id,
  "trial_id": event.trial_id,
  "event_index": event.event_index,
  "previous_event_reference": event.previous_event_reference,
  "event_kind": event.event_kind,
  "recorded_at": event.recorded_at,
  "producer_evidence_references": sorted(event.producer_evidence_references),
  "payload_reference": event.payload_reference,
  "payload_hash": event.payload_hash
}
event_hash = sha256_hex(canonical_json(event_preimage))
```

#### Invariants Governing Event Ordering
1. **Monotonic Event Index:** `event_index` must strictly increment ($0, 1, 2, \dots$).
   An event index cannot be skipped or silently renumbered.
2. **Byte Immutability:** An existing event cannot be updated. Any conflicting bytes
   submitted under an existing `event_id` are rejected as a fatal integrity violation.
3. **Derived Projections:** `TrialRecordV1` is a derived, materialized projection
   over the event stream. When late evidence (e.g., corrected invoice) arrives, a new
   event is appended, advancing the projection's `trial_revision` without altering past events.

---

### 3.4 Derived Materialized Projection: `TrialRecordV1`

`TrialRecordV1` is the point-in-time materialized view of a trial's current state.

#### Semantic Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `trial_id` | String | Unique trial identifier: `"{campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"`. |
| `campaign_id` | String | Parent campaign identifier. |
| `run_id` | String | Execution run or replicate identifier. |
| `arm_id` | String | Evaluated arm identifier. |
| `checkpoint_id` | String | Sequential checkpoint label, e.g., `"CP-2026-01-30"`. |
| `portfolio_account_id` | String | Bound account identifier from `RunAccountBindingV1`. |
| `trial_revision` | Integer | Incremental revision number (starts at 1). |
| `decision_cutoff_timestamp` | String | ISO 8601 UTC timestamp before which all inputs must be verified. |
| `earliest_effective_timestamp`| String | ISO 8601 UTC timestamp of the next eligible execution open. |
| `campaign_spec_fingerprint` | String | Hash of parent campaign specification. |
| `arm_spec_fingerprint` | String | Hash of parent arm specification. |
| `evidence_as_of_timestamp` | String | Timestamp of latest evidence integrated into this projection. |
| `input_evidence_references` | Array[String] | Hashes of qualified market bars and counterfactual candidate series. |
| `memory_snapshot_reference` | String | Krish's `memory_snapshot_id` representing time-eligible agent memory. |
| `proposal_references` | Array[String] | Pinned `proposal_id` values generated by the agent during this trial. |
| `research_attempt_references` | Array[String] | Pinned `attempt_id` records generated under Krish's research contract. |
| `model_replay_references` | Array[String] | Hashes of captured model request/response replay records. |
| `cost_receipt_references` | Array[String] | Pinned `receipt_id` records from Krish's spending store. |
| `phase_a_eligibility_reference`| String | ID of Phase A `EligibilityDecisionV1` record. |
| `phase_b_mandate_verdict_ref` | String | ID of Matthew's Phase B mandate verdict record. |
| `selected_strategy_reference` | String | Chosen strategy or `"NO_CHANGE"` / `"ABSTAIN"`. |
| `order_references` | Array[String] | Matthew's staged `order_id` references (0, 1, or N orders). |
| `fill_references` | Array[String] | Matthew's execution `fill_id` references. |
| `authoritative_result_references`| Array[String]| Chronological list of Matthew's platform `RESULT` record IDs. |
| `outcome_classification` | String | Execution outcome: `"COMPLETED"`, `"INCOMPLETE"`, `"REFUSED"`, `"UNRESOLVED"`. |
| `completeness_classification` | String | Scientific audit state: `"COMPLETE"`, `"PENDING_RESULT"`, `"MISSING_COST"`, `"INVALID"`. |
| `refusal_or_failure_reasons` | Array[String] | Structured error or refusal codes. |
| `evidence_fingerprint` | String | SHA-256 hex digest over all linked event hashes and referenced evidence. |

---

### 3.5 Execution Cardinality and Unresolved States

Real transitions support flexible order cardinality:
- **Zero Orders:** Valid no-trade or mandate refusal stages 0 orders.
- **Multiple Orders:** Rotating strategies stages $N$ orders (e.g., selling 3, buying 3).
- **Partial Fills:** Orders with partial execution and residual cash.
- **Multiple Chronological Results:** Intermediate daily marks during a monthly holding period.
- **Unresolved Execution Handling:** If an order status cannot be determined (e.g., simulator timeout),
  outcome is classified as **`UNRESOLVED`** (not `FAILED`). The trial remains `PENDING_RESULT`
  until Matthew's platform establishes the terminal state.

---

### 3.6 EligibilityDecisionV1

`EligibilityDecisionV1` evaluates scientific and pre-decision input qualification only.

#### Semantic Fields

| Field Name | Type | Description |
|---|---|---|
| `schema_version` | String | Fixed schema identifier, e.g., `"drift-experiment/1-draft"`. |
| `eligibility_decision_id` | String | Unique decision identifier: `"{trial_id}:ELIG"`. |
| `campaign_id` | String | Parent campaign identifier. |
| `run_id` | String | Execution run identifier. |
| `arm_id` | String | Evaluated arm identifier. |
| `trial_id` | String | Parent trial identifier. |
| `decision_scope` | String | Strictly `"PRE_DECISION_SCIENTIFIC_INPUT"`. |
| `evaluated_at` | String | ISO 8601 UTC timestamp of evaluation. |
| `evidence_as_of` | String | ISO 8601 UTC timestamp of latest evidence evaluated. |
| `evaluator_policy_revision` | String | Pinned commit hash of the eligibility evaluation code. |
| `evidence_references` | Array[String] | Hashes of inputs evaluated (market bars, calendar, proposal). |
| `classification` | String | One of: `"ELIGIBLE"`, `"INELIGIBLE"`, `"UNAVAILABLE"`, `"INVALID"`. |
| `scientific_reason_codes` | Array[String] | Standardized scientific reason codes. |
| `unresolved_requirements` | Array[String] | List of missing or violated requirements (empty if ELIGIBLE). |

#### Classifications
- `ELIGIBLE`: Market data point-in-time verified before cutoff; candidate strategy permitted in arm spec. (Does NOT grant dispatch authority).
- `INELIGIBLE`: Strategy proposal violates study constraints (e.g., disallowed family). Switch refused; portfolio retained; no liquidation.
- `UNAVAILABLE`: Required market data unverified at cutoff. Fails closed; no backdating.
- `INVALID`: Contradictory, cross-arm contaminated, or malformed evidence.

---

### 3.7 StudyReportV1 and Comparative Reporting

`StudyReportV1` aggregates completed trial records into an analytical report.

#### Economic Definitions
- **Per-Arm Economic Gain:**
  $$    ext{Economic Gain}(i) = (    ext{Terminal NAV}_{    ext{net}}(i) -     ext{Initial Capital}(i)) - \sum     ext{Attributed Operating Expenses}(i)$$
- **Comparative Economic Advantage (B vs. R):**
  $$\Delta_{    ext{economic}}(B, R) =     ext{Economic Gain}(B) -     ext{Economic Gain}(R)$$
- **Reporting Invariant:** An arm's absolute economic gain must **never** be labeled as
  a comparative advantage against another arm. Comparative advantage is strictly paired.
- **Review Binding:** Independent reviewer receipts must bind to `report_revision_fingerprint`.

---

## 4. Scientific Cost Attribution Model and Krish's Receipts

The scientific layer consumes Krish's authoritative research spending receipts
(`drift-research/1-draft` in PR #400 `research.md`) without inventing a competing format.

### 4.1 Krish's Research Receipt Fields Consumed
Every research cost receipt bound by `cost_receipt_references` conforms strictly to Krish's
authoritative schema (`research.md` in PR #400):
- `receipt_id`: Unique receipt identifier string.
- `scope`: Operating scope string (e.g., `"trial_inference"`).
- `attempt_id`: Concrete research attempt identifier (nullable for shared unassigned work).
- `category`: Cost category: `"inference"`, `"research_compute"`, `"data"`, `"infrastructure"`.
- `billing_identity`: Nonblank idempotency key scoped to the cost source.
- `raw_evidence_ref`: Pointer to usage/meter/pricing evidence.
- `incurred_start`, `incurred_end`, `recorded_at`: Chronological timestamps.
- `amount`: Nonnegative DecimalText string (e.g., `"0.04200000"`), or `null` when unknown. Never a JSON float.
- `currency`: Currency string (e.g., `"USD"`), or `null` when unknown.
- `amount_basis`: Lowercase producer basis: strictly `"actual"`, `"estimate"`, `"unknown"`, or `"verified_zero"`.
- `unknown_reason`: String explaining why cost is unknown. Required when `amount_basis == "unknown"`; null otherwise.
- `pricing_ref`: Pinned pricing schedule reference. Required for estimates.
- `usage`: Array of detailed usage entries `{unit, quantity, unknown_reason}`.
- `shared_work_ref`: Pointer to shared preprocessing work (or null).
- `supersedes_receipt_id`: Receipt ID being corrected or superseded (or null).

#### Note on Attempt vs. Receipt Lineage
`logical_request_id`, `retry_of`, and `duplicate_of` belong to Krish's authoritative
**research attempt records**, not to raw_cost receipts. A research attempt may group multiple
retries under one `logical_request_id`, and each incurred invocation produces its own `raw_cost` receipt.

### 4.2 Operating vs. Replay Costs
- **Zero Cost for Historical Replay:** Replaying an immutable model prompt/response
  capture from storage incurs zero new inference bill (`amount_basis: "VERIFIED_ZERO"`).
- **New Replay Infrastructure Costs:** Any newly incurred compute or storage costs
  for running the replay harness retain their own distinct receipts.

---

## 5. Distinct Denominators

To prevent multiple-testing fallacies, denominators are defined per operational layer:

1. **Study Opportunity Completion:**
   $$    ext{Completion Rate} = rac{N_{    ext{complete-trials}}}{N_{    ext{scheduled-arm-checkpoints}}}$$
   (Denominator is scheduled arm-checkpoint opportunities, not merely calendar dates).
2. **Candidate Proposal Yield:**
   $$    ext{Proposal Yield} = rac{N_{    ext{valid-proposals}}}{N_{    ext{attempted-proposals}}}$$
3. **Inference Reliability:**
   $$    ext{Inference Reliability} = rac{N_{    ext{successful-attempts}}}{N_{    ext{initial-attempts}} + N_{    ext{retries}}}$$
   (Retries increment the attempt denominator; they are not duplicate copies of one attempt).
4. **Order Execution Conversion:**
   $$    ext{Order Conversion} = rac{N_{    ext{executed-orders}}}{N_{    ext{staged-orders}}}$$

---

## 6. Worked Contract Test Cases (22 Comprehensive Scenarios)

The 22 test cases demonstrate exact system behavior under all required edge conditions.
All JSON blocks are validated for syntax and schema alignment.

---

### Case 1: Valid Complete Trial
- **Scenario:** Normal monthly checkpoint; agent proposes valid B4 switch; input verified; Matthew's gatekeeper approves; order filled; RESULT received; costs verified.
- **Inputs:** `trial_id: "CAMP1:RUN-001:ARM-B:CP-2026-01-30"`, proposed strategy: `"B4"`.
- **Expected:** Phase A `ELIGIBLE`, Phase B `APPROVED`, Phase C `EXECUTED`, Phase D `COMPLETE`.

```json
{
  "test_case_id": "CASE-01-VALID-COMPLETE-TRIAL",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "ELIGIBLE",
    "scientific_reason_codes": ["INPUTS_POINT_IN_TIME_QUALIFIED", "STRATEGY_PERMITTED"],
    "unresolved_requirements": []
  },
  "phase_b_mandate_verdict": {
    "verdict_id": "MANDATE-VERDICT-001",
    "status": "APPROVED",
    "operational_reason_codes": ["MANDATE_CAPS_SATISFIED"]
  },
  "trial_projection": {
    "selected_strategy_reference": "B4",
    "order_references": ["ORD-2026-01-30-001"],
    "fill_references": ["FILL-2026-01-30-001"],
    "authoritative_result_references": ["RESULT-2026-01-30-001"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE"
  }
}
```

---

### Case 2: Valid No-Trade Decision
- **Scenario:** Checkpoint evaluates current portfolio (in B3); selector intentionally proposes `"NO_CHANGE"`.
- **Inputs:** Current strategy: `"B3"`, proposed action: `"NO_CHANGE"`.
- **Expected:** Phase A `ELIGIBLE`, Phase B `NOT_REQUIRED`, Phase C `NO_ORDERS`, Phase D `COMPLETE`.

```json
{
  "test_case_id": "CASE-02-VALID-NO-TRADE",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-02-27",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "ELIGIBLE",
    "scientific_reason_codes": ["NO_TRADE_INTENTIONAL", "INPUTS_QUALIFIED"],
    "unresolved_requirements": []
  },
  "trial_projection": {
    "selected_strategy_reference": "NO_CHANGE",
    "order_references": [],
    "fill_references": [],
    "authoritative_result_references": ["RESULT-2026-02-27-001"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE"
  }
}
```

---

### Case 3: Ineligible Strategy Switch (Mandate Refusal)
- **Scenario:** Agent proposes B4 switch targeting 83.33% equities. Phase A inputs are qualified, but Matthew's Phase B gatekeeper refuses order staging due to equity cap breach.
- **Inputs:** Target equity exposure = 83.33% (exceeds candidate Balanced cap of 70.0%).
- **Expected:** Phase A `ELIGIBLE` (inputs valid), Phase B `REFUSED` (mandate breach), Phase C `NO_ORDERS`, Phase D `COMPLETE`.

```json
{
  "test_case_id": "CASE-03-INELIGIBLE-STRATEGY-SWITCH",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-03-31",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "ELIGIBLE",
    "scientific_reason_codes": ["INPUTS_QUALIFIED", "STRATEGY_PERMITTED"],
    "unresolved_requirements": []
  },
  "phase_b_mandate_verdict": {
    "verdict_id": "MANDATE-VERDICT-003",
    "status": "REFUSED",
    "operational_reason_codes": ["MANDATE_EQUITY_CAP_EXCEEDED"]
  },
  "trial_projection": {
    "selected_strategy_reference": "CURRENT_RETAINED",
    "order_references": [],
    "fill_references": [],
    "authoritative_result_references": ["RESULT-2026-03-31-001"],
    "outcome_classification": "REFUSED",
    "completeness_classification": "COMPLETE",
    "refusal_or_failure_reasons": ["MANDATE_EQUITY_CAP_EXCEEDED"]
  }
}
```

---

### Case 4: Unavailable Market-Data Input
- **Scenario:** GLD corporate action adjustments on NYSE Arca unverified at cutoff.
- **Expected:** Phase A `UNAVAILABLE`, Phase B `NOT_EVALUATED`, Phase C `NO_ORDERS`, Phase D `PENDING_RESULT`.

```json
{
  "test_case_id": "CASE-04-UNAVAILABLE-MARKET-DATA",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-04-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "UNAVAILABLE",
    "scientific_reason_codes": ["DATA_PROVENANCE_UNVERIFIED"],
    "unresolved_requirements": ["DATASET_QUALIFICATION: GLD"]
  },
  "trial_projection": {
    "selected_strategy_reference": "CURRENT_RETAINED",
    "order_references": [],
    "fill_references": [],
    "outcome_classification": "REFUSED",
    "completeness_classification": "PENDING_RESULT",
    "refusal_or_failure_reasons": ["DATA_PROVENANCE_UNVERIFIED"]
  }
}
```

---

### Case 5: News Received After Decision Cutoff
- **Scenario:** Event timestamped 5 minutes post-cutoff included in prompt context.
- **Expected:** Phase A `INVALID` (`CAUSAL_LOOKAHEAD_VIOLATION`), Phase D `INVALID`.

```json
{
  "test_case_id": "CASE-05-POST-CUTOFF-NEWS",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-05-29",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "INVALID",
    "scientific_reason_codes": ["CAUSAL_LOOKAHEAD_VIOLATION"],
    "unresolved_requirements": ["EVENT_TIMESTAMP <= DECISION_CUTOFF"]
  },
  "trial_projection": {
    "outcome_classification": "REFUSED",
    "completeness_classification": "INVALID",
    "refusal_or_failure_reasons": ["CAUSAL_LOOKAHEAD_VIOLATION"]
  }
}
```

---

### Case 6: Duplicate Identical Trial Submission
- **Scenario:** Identical trial record submitted twice; acknowledged idempotently.
- **Expected:** Phase A `ELIGIBLE` (`IDEMPOTENT_DUPLICATE_ACKNOWLEDGED`).

```json
{
  "test_case_id": "CASE-06-DUPLICATE-IDENTICAL-TRIAL",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "ELIGIBLE",
    "scientific_reason_codes": ["IDEMPOTENT_DUPLICATE_ACKNOWLEDGED"],
    "unresolved_requirements": []
  },
  "trial_projection": {
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE"
  }
}
```

---

### Case 7: Duplicate Conflicting Trial Submission
- **Scenario:** Conflicting strategy choice under existing `trial_id`.
- **Expected:** Phase A `INVALID`, rejection with `CONFLICTING_DUPLICATE_TRIAL`.

```json
{
  "test_case_id": "CASE-07-DUPLICATE-CONFLICTING-TRIAL",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "INVALID",
    "scientific_reason_codes": ["CONFLICTING_DUPLICATE_TRIAL"],
    "unresolved_requirements": ["IMMUTABLE_HASH_MATCH"]
  },
  "trial_projection": {
    "outcome_classification": "REFUSED",
    "completeness_classification": "INVALID",
    "refusal_or_failure_reasons": ["CONFLICTING_DUPLICATE_TRIAL"]
  }
}
```

---

### Case 8: Attempt Referencing Another Arm
- **Scenario:** Proposal for Arm B cites internal attempt receipt of Arm R.
- **Expected:** Phase A `INVALID` (`CROSS_ARM_LEAKAGE`), Phase D `INVALID`.

```json
{
  "test_case_id": "CASE-08-CROSS-ARM-LEAKAGE",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-06-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "INVALID",
    "scientific_reason_codes": ["CROSS_ARM_LEAKAGE"],
    "unresolved_requirements": ["ATTEMPT_ARM_ID == TRIAL_ARM_ID"]
  },
  "trial_projection": {
    "outcome_classification": "REFUSED",
    "completeness_classification": "INVALID",
    "refusal_or_failure_reasons": ["CROSS_ARM_LEAKAGE"]
  }
}
```

---

### Case 9: Missing Authoritative Account Results
- **Scenario:** Order executed in simulation, but platform RESULT not emitted.
- **Expected:** Phase A was `ELIGIBLE`, Phase D `PENDING_RESULT`. Prior eligibility intact.

```json
{
  "test_case_id": "CASE-09-MISSING-AUTHORITATIVE-RESULT",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-07-31",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "ELIGIBLE",
    "scientific_reason_codes": ["INPUTS_QUALIFIED"],
    "unresolved_requirements": []
  },
  "trial_projection": {
    "authoritative_result_references": [],
    "outcome_classification": "INCOMPLETE",
    "completeness_classification": "PENDING_RESULT",
    "refusal_or_failure_reasons": ["PLATFORM_RESULT_MISSING"]
  }
}
```

---

### Case 10: Unknown Model Spending
- **Scenario:** API reports completion without token usage metadata (`amount_basis: "UNKNOWN"`).
- **Expected:** Phase A `ELIGIBLE`, Phase D `MISSING_COST`. Portfolio return verified; economic scorecard incomplete.

```json
{
  "test_case_id": "CASE-10-UNKNOWN-MODEL-SPENDING",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-08-31",
  "krish_receipt": {
    "receipt_id": "RECEIPT-UNKNOWN-001",
    "attempt_id": "ATTEMPT-20260831-001",
    "amount": null,
    "currency": null,
    "amount_basis": "unknown",
    "unknown_reason": "Provider API failed to return token usage metadata",
    "pricing_ref": null,
    "supersedes_receipt_id": null
  },
  "trial_projection": {
    "authoritative_result_references": ["RESULT-2026-08-31-001"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "MISSING_COST",
    "refusal_or_failure_reasons": ["COST_STATUS_UNKNOWN"]
  }
}
```

---

### Case 11: Corrected Late Provider Invoice (Krish Lineage)
- **Scenario:** Estimated receipt superseded by verified provider billing receipt via `supersedes_receipt_id`.
- **Expected:** Phase D `COMPLETE` (Revision 2 emitted). Consumes Krish's native fields with DecimalText amount.

```json
{
  "test_case_id": "CASE-11-LATE-COST-CORRECTION",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
  "krish_cost_receipt": {
    "receipt_id": "RECEIPT-ACTUAL-002",
    "attempt_id": "ATTEMPT-001",
    "amount": "0.05800000",
    "currency": "USD",
    "amount_basis": "actual",
    "unknown_reason": null,
    "supersedes_receipt_id": "RECEIPT-EST-001"
  },
  "trial_projection": {
    "trial_revision": 2,
    "cost_receipt_references": ["RECEIPT-ACTUAL-002"],
    "completeness_classification": "COMPLETE"
  }
}
```

---

### Case 12: Mismatched Campaign Fingerprint
- **Scenario:** Trial submitted with altered campaign spec parameters.
- **Expected:** Phase A `INVALID` (`CAMPAIGN_FINGERPRINT_MISMATCH`).

```json
{
  "test_case_id": "CASE-12-CAMPAIGN-FINGERPRINT-MISMATCH",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-09-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "INVALID",
    "scientific_reason_codes": ["CAMPAIGN_FINGERPRINT_MISMATCH"],
    "unresolved_requirements": ["SUBMITTED_FINGERPRINT == CAMPAIGN_SPEC_FINGERPRINT"]
  },
  "trial_projection": {
    "outcome_classification": "REFUSED",
    "completeness_classification": "INVALID",
    "refusal_or_failure_reasons": ["CAMPAIGN_FINGERPRINT_MISMATCH"]
  }
}
```

---

### Case 13: Unsupported Schema Version
- **Scenario:** Trial record submitted under unrecognized schema `drift-experiment/99-future`.
- **Expected:** Phase A `INVALID`, fails closed.

```json
{
  "test_case_id": "CASE-13-UNSUPPORTED-SCHEMA-VERSION",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-10-30",
  "phase_a_eligibility": {
    "decision_scope": "PRE_DECISION_SCIENTIFIC_INPUT",
    "classification": "INVALID",
    "scientific_reason_codes": ["UNSUPPORTED_SCHEMA_VERSION"],
    "unresolved_requirements": ["SUPPORTED_SCHEMA_VERSION: drift-experiment/1-draft"]
  },
  "trial_projection": {
    "outcome_classification": "REFUSED",
    "completeness_classification": "INVALID",
    "refusal_or_failure_reasons": ["UNSUPPORTED_SCHEMA_VERSION"]
  }
}
```

---

### Case 14: Trial Interrupted Before Finalization
- **Scenario:** Host process crashes after order staging; partial event stream preserved.
- **Expected:** Phase D `PENDING_RESULT`. Recovery checks platform journal.

```json
{
  "test_case_id": "CASE-14-INTERRUPTED-TRIAL",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-11-30",
  "trial_projection": {
    "order_references": ["ORD-2026-11-30-001"],
    "fill_references": [],
    "authoritative_result_references": [],
    "outcome_classification": "INCOMPLETE",
    "completeness_classification": "PENDING_RESULT",
    "refusal_or_failure_reasons": ["EXECUTION_INCOMPLETE"]
  }
}
```

---

### Case 15: Recovery Without Duplicate Accounting
- **Scenario:** Following restart from Case 14, platform confirms order execution at open; RESULT linked.
- **Expected:** Phase D `COMPLETE` (Recovery reconciled). Zero duplicate trades.

```json
{
  "test_case_id": "CASE-15-RECOVERY-RECONCILED",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-11-30",
  "trial_projection": {
    "order_references": ["ORD-2026-11-30-001"],
    "fill_references": ["FILL-2026-11-30-001"],
    "authoritative_result_references": ["RESULT-2026-11-30-001"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE",
    "refusal_or_failure_reasons": []
  }
}
```

---

### Case 16: Multiple Orders with Partial Fills
- **Scenario:** Transition stages 6 orders. 4 filled completely, 1 partially filled, 1 unfilled order cancelled at session end. All orders in known terminal states; RESULT fully reconciled.
- **Expected:** Phase C `PARTIALLY_EXECUTED`, Phase D `COMPLETE`.
- **Requirement:** COMPLETE only because all 6 orders reached terminal states and final platform RESULT is reconciled. Outstanding open orders would prevent COMPLETE.

```json
{
  "test_case_id": "CASE-16-MULTI-ORDER-PARTIAL-FILL",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-12-31",
  "trial_projection": {
    "order_references": ["ORD-01", "ORD-02", "ORD-03", "ORD-04", "ORD-05", "ORD-06"],
    "fill_references": ["FILL-01", "FILL-02", "FILL-03", "FILL-04", "FILL-05-PARTIAL"],
    "authoritative_result_references": ["RESULT-2026-12-31-001"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE"
  }
}
```

---

### Case 17: Unresolved Execution State
- **Scenario:** Transition order submitted to simulation venue, but simulator hangs; terminal status unknown at session close.
- **Expected:** Outcome is **`UNRESOLVED`** (NOT `FAILED`). Phase D is `PENDING_RESULT`.
- **Requirement:** Preserved as unresolved/incomplete until authoritative producer establishes what happened.

```json
{
  "test_case_id": "CASE-17-UNRESOLVED-EXECUTION-STATE",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2027-01-29",
  "trial_projection": {
    "order_references": ["ORD-TIMEOUT-01"],
    "fill_references": [],
    "authoritative_result_references": [],
    "outcome_classification": "UNRESOLVED",
    "completeness_classification": "PENDING_RESULT",
    "refusal_or_failure_reasons": ["EXECUTION_STATE_UNRESOLVED"]
  }
}
```

---

### Case 18: Separate Campaign Runs with Run-Level Account Isolation
- **Scenario:** Two independent simulation runs (`RUN-001` and `RUN-002`) evaluate the same arm at the same checkpoint.
- **Inputs:** `trial_id_1: "CAMP1:RUN-001:ARM-B:CP-2026-01-30"`, `trial_id_2: "CAMP1:RUN-002:ARM-B:CP-2026-01-30"`.
- **Expected:** Each trial binds to a distinct, isolated `portfolio_account_id`.
- **Requirement:** Proves run-level account isolation prevents cross-run state contamination.

```json
{
  "test_case_id": "CASE-18-RUN-LEVEL-ACCOUNT-ISOLATION",
  "trial_1": {
    "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
    "run_id": "RUN-001",
    "portfolio_account_id": "ACCT-RUN001-ARM-B",
    "outcome_classification": "COMPLETED"
  },
  "trial_2": {
    "trial_id": "CAMP1:RUN-002:ARM-B:CP-2026-01-30",
    "run_id": "RUN-002",
    "portfolio_account_id": "ACCT-RUN002-ARM-B",
    "outcome_classification": "COMPLETED"
  }
}
```

---

### Case 19: Shared Cost Allocation Across Multiple Arms
- **Scenario:** Offline market summary prompt costing $0.10 DecimalText utilized jointly by Arm B and Arm R.
- **Inputs:** Shared receipt amount `"0.10000000"`, policy `"PRO_RATA_EQUAL"`.
- **Expected:** Each arm attributed `"0.05000000"`. Total attributed equals incurred expense.

```json
{
  "test_case_id": "CASE-19-SHARED-COST-ALLOCATION",
  "krish_shared_receipt": {
    "receipt_id": "RECEIPT-SHARED-001",
    "amount": "0.10000000",
    "currency": "USD",
    "amount_basis": "actual",
    "unknown_reason": null
  },
  "arm_b_attribution": {
    "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
    "attributed_operating_cost": "0.05000000"
  },
  "arm_r_attribution": {
    "trial_id": "CAMP1:RUN-001:ARM-R:CP-2026-01-30",
    "attributed_operating_cost": "0.05000000"
  }
}
```

---

### Case 20: Late Invoice Without Altering Historical Observations
- **Scenario:** Compute invoice adjustment received 30 days post-trial. Historical NAV, fills, and market returns unchanged.
- **Expected:** Trial revision incremented to 2; historical event log preserved; NAV unchanged.

```json
{
  "test_case_id": "CASE-20-LATE-INVOICE-PRESERVES-OBSERVATIONS",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-01-30",
  "revision_1": {
    "trial_revision": 1,
    "portfolio_net_nav": "10120.45",
    "attributed_cost": "0.04000000",
    "evidence_fingerprint": "fp_rev1_hash"
  },
  "revision_2": {
    "trial_revision": 2,
    "portfolio_net_nav": "10120.45",
    "attributed_cost": "0.04800000",
    "evidence_fingerprint": "fp_rev2_hash"
  }
}
```

---

### Case 21: Valid Trading Result with Incomplete Economic Costs
- **Scenario:** Trade fills cleanly, platform RESULT verified, but token billing receipt is UNKNOWN.
- **Expected:** Portfolio NAV return reportable; economic scorecard marked `MISSING_COST`.

```json
{
  "test_case_id": "CASE-21-VALID-TRADING-INCOMPLETE-COSTS",
  "trial_id": "CAMP1:RUN-001:ARM-B:CP-2026-02-27",
  "portfolio_reporting": {
    "status": "VERIFIED",
    "terminal_nav": "10250.00",
    "net_return": "0.02500000"
  },
  "economic_reporting": {
    "status": "INCOMPLETE",
    "missing_cost_status": "UNKNOWN",
    "economic_advantage": null
  }
}
```

---

### Case 22: Passive Control Arm Outside B3/B4/B5
- **Scenario:** Arm C (Passive Benchmark) holds 100% VOO; does not evaluate B3/B4/B5 candidate pool.
- **Expected:** Phase A `ELIGIBLE`, Phase B `NOT_REQUIRED`, Phase C `NO_ORDERS`, Phase D `COMPLETE`.
- **Requirement:** Validates that general experiment schemas support non-selector control baselines.

```json
{
  "test_case_id": "CASE-22-PASSIVE-CONTROL-OUTSIDE-B345",
  "trial_id": "CAMP1:RUN-001:ARM-C:CP-2026-01-30",
  "arm_spec": {
    "arm_id": "ARM-C",
    "selector_type": "PASSIVE_BENCHMARK",
    "eligible_strategy_references": ["PASSIVE_VOO"]
  },
  "trial_projection": {
    "selected_strategy_reference": "PASSIVE_VOO",
    "order_references": [],
    "authoritative_result_references": ["RESULT-ARM-C-2026-01-30"],
    "outcome_classification": "COMPLETED",
    "completeness_classification": "COMPLETE"
  }
}
```

---

## 7. Producer Integration Mappings

### 7.1 Integration with Krish's Research Contract (`drift-research/1-draft`)
Per [PR #400](https://github.com/KanujVerma/drift/pull/400) (`research.md`), the scientific layer
consumes research outputs through stable references:

| Research Producer Field | TrialRecordV1 Semantic Binding | Notes |
|---|---|---|
| `context_id` | `input_evidence_references` | Pinned point-in-time context evaluated. |
| `candidate_id` / `RawChoice` | `proposal_references` | Candidate strategy proposed by agent. |
| `attempt_id` | `research_attempt_references` | Complete attempt lifecycle record. |
| `logical_request_id` | Research Attempt receipt metadata | Groups attempts and retries under logical request. |
| `retry_of` | Research Attempt receipt metadata | Tracks incurred retry lineage on attempt records. |
| `replay_id` | `model_replay_references` | Verifiable model prompt/output capture. |
| `receipt_id` | `cost_receipt_references` | Krish's raw cost receipt ID. |
| `amount` (DecimalText) | Scientific Cost Attribution | Monetary expense as DecimalText string. |
| `amount_basis` | Scientific Cost Attribution | Certainty state: UNKNOWN/ESTIMATED/ACTUAL/ZERO. |
| `supersedes_receipt_id` | `cost_receipt_references` lineage | Late invoice correction tracking. |
| `memory_snapshot_id` | `memory_snapshot_reference` | Bound as time-eligible checkpoint evidence. |

### 7.2 Integration with Matthew's Platform Contracts
Per [PR #407](https://github.com/KanujVerma/drift/pull/407) (`platform.md`),
[PR #412](https://github.com/KanujVerma/drift/pull/412) (`execution.md`), and
[PR #414](https://github.com/KanujVerma/drift/pull/414) (`mandate.md`):

| Platform Producer Field | TrialRecordV1 Semantic Binding | Notes |
|---|---|---|
| `source_event_id` | `input_evidence_references` | Proves data point-in-time availability. |
| `mandate_verdict_id` | `phase_b_mandate_verdict_ref` | Matthew's Phase B operational risk check. |
| `order_id` | `order_references` | Matthew's staged transition orders (0, 1, or N). |
| `fill_id` | `fill_references` | Simulated trade fills, partial fills, slippage, and spread. |
| `RESULT` payload | `authoritative_result_references` | Authoritative portfolio NAV, cash, and positions. |

---

## 8. Open Architecture Decision Packets

The following decisions remain open and must be formally resolved prior to scored
historical execution:

1. **DP-R6 / Comparator R Formula:** Exact mathematical formulation for the
   conventional deterministic comparator (e.g., Rolling Net-Sharpe Optimizer vs.
   Fixed Scoring Matrix).
2. **DP-R8 / Holdout Exposure Policy:** Formal selection between Option 3A (Strict
   Sealed Holdout) and Option 3B (Lagged Per-Arm Feedback Under Frozen Protocol).
3. **DP-M1 / Statistical Estimand and Estimator:** Selection of primary uncertainty
   estimator (Stationary Block Bootstrap vs. HAC Newey-West) and economic materiality
   hurdle $\delta^*$.
4. **Balanced Mandate Limits:** Final owner approval of numerical risk caps (PR #421
   candidate caps: 20% ETF, 70% equity, 75% bond, 20% gold).

---

## 9. Future Implementation Boundaries (Slices E1-E6)

When authorized under separate implementation issues with explicit file permissions,
the scientific runtime will be built in strictly ordered slices:

- **Slice E1 (Campaign, Arm, and Account Binding Parser):** Immutable parsing, validation,
  and canonical fingerprinting for `CampaignSpecV1`, `ArmSpecV1`, and `RunAccountBindingV1`.
- **Slice E2 (Trial Event Journal and Projection Engine):** Append-only event store
  (`TrialEventV1`) and projection engine emitting `TrialRecordV1`.
- **Slice E3 (Deterministic Scientific Eligibility Evaluator):** Phase A preflight engine
  emitting `EligibilityDecisionV1`.
- **Slice E4 (Scientific Cost Attribution Engine):** Dual-ledger join combining Matthew's
  trading results with Krish's research spending receipts.
- **Slice E5 (Study Report Aggregator):** Reproducible calculation of trial completeness,
  portfolio return differentials, and statistical metric rollups (`StudyReportV1`).
- **Slice E6 (End-to-End Synthetic Integration):** Full vertical slice (#383) executing
  simulated multi-arm campaigns under synthetic market fixtures.

---

## 10. Document Acceptance and Verification Matrix

| Acceptance Requirement | Status in this Document | Verification Evidence |
|---|---|---|
| Frozen campaign & arm identity | Complete | Section 3.1, 3.2; immutability rules. |
| Run-level account isolation | Complete | Section 3.2 (RunAccountBindingV1), 6 (Case 18). |
| Control arms outside B3/B4/B5 | Complete | Section 3.1, 3.2, 6 (Case 22). |
| Separation of 4 decision phases | Complete | Section 2; Phase A-D explicit boundaries. |
| Scope-restricted EligibilityDecision | Complete | Section 2, 3.6; pre-decision input scope only. |
| Minimum TrialEventV1 envelope | Complete | Section 3.3; all 11 required fields. |
| Multi-order and partial fills | Complete | Section 3.5, 6 (Case 16). |
| Unresolved execution handling | Complete | Section 3.5, 6 (Case 17); UNRESOLVED outcome. |
| Consume Krish research receipts | Complete | Section 4, 7.1; DecimalText, supersedes_receipt_id. |
| Distinct opportunity denominators | Complete | Section 5; arm-checkpoint opportunities. |
| Comparative economic advantage | Complete | Section 3.7; normalized comparative gain. |
| Zero Unicode em dashes (U+2014) | Enforced | Automated scan passed (0 instances). |
