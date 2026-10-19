# Independent Release-Acceptance Specification

## Start here: authority before action

This is the canonical specification for **INDEPENDENT RELEASE ACCEPTANCE**,
produced under [#397](https://github.com/KanujVerma/drift/issues/397) as the binding
governance gate for Drift's adaptive experiments.

**This is a contract specification proposal. It implements no runtime code,
persisted database schemas, or autonomous trading permissions.** It defines the
requirement-to-test evidence matrix, conflict of interest prohibitions, and
verification standards that must be independently satisfied before any Stage 1
adaptive experiment can be promoted, certified, or granted operational authority.

A fresh Antigravity agent or human reviewer should note:

1. Read [AGENTS.md](../../../AGENTS.md), [decisions.md](decisions.md) (D01-D17),
   [design.md](design.md), [workstreams.md](../workstreams.md),
   [requirements-crosswalk.md](requirements-crosswalk.md),
   [stage1-decisions.md](stage1-decisions.md) (S01-S38), and
   [stage1-roadmap.md](stage1-roadmap.md).
2. **Four distinct verification tiers:**
   - Tier 1: Engineering Tests Passing (unit/regression tests green).
   - Tier 2: Contract Acceptance (producers/consumers agree on interface types).
   - Tier 3: Scientific Efficacy Acceptance (independent audit of hypotheses and statistics).
   - Tier 4: Operational Release Authorization (formal sign-off to trade or deploy).
   **No tier grants the next stage automatically.** A passing test suite does not
   establish contract acceptance; contract acceptance does not prove scientific efficacy;
   and scientific efficacy does not grant operational trading permission.
3. **Strict conflict of interest boundaries:**
   - Kanuj and his implementing agents cannot independently approve their own scientific
     implementation, test fixtures, or empirical scorecards.
   - Krish may review research interface compatibility, but cannot solely certify
     scientific claims regarding his own research producer.
   - Matthew may review platform compatibility, but cannot solely certify his own
     recovery, execution, or containment mechanisms.
   - Any claim of credible investment advantage requires an independent scientific
     review by an unconflicted third party.
4. **Authoritative lineage:** Consumes Matthew's recovery contract (PR #416
   `recovery.md` under [#395](https://github.com/KanujVerma/drift/issues/395)) and
   containment contract (PR #417 `containment.md` under
   [#396](https://github.com/KanujVerma/drift/issues/396)).
5. **No missing evidence treated as PASS:** Acceptance status values are strictly:
   `PASS`, `FAIL`, `NOT_RUN`, `BLOCKED`, and `UNAVAILABLE`. Missing evidence is
   classified as `UNAVAILABLE` or `BLOCKED`, never as `PASS`.

---

## 1. Scope, Non-Goals, and Separation of Stages

### 1.1 Four Non-Conflated Stages of Authority

```
+-----------------------------------------------------------------------------+
| Stage 1: Engineering Tests Passing                                          |
| - Scope: Local pytest, Ruff, mypy, and whitespace gates pass.               |
| - Authority: Code compiles and meets mechanical quality standards.          |
| - Boundary: DOES NOT prove interface compatibility or experimental truth.  |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Stage 2: Contract Acceptance                                                |
| - Scope: Producers and consumers sign off on exact wire schemas & types.    |
| - Authority: Krish accepts research; Matthew accepts platform/mandate.      |
| - Boundary: DOES NOT prove strategy efficacy or release safety.             |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Stage 3: Scientific Efficacy Acceptance                                     |
| - Scope: Independent scientific audit of preregistration, data, and stats.  |
| - Authority: Unconflicted reviewer certifies statistical advantage claims.  |
| - Boundary: DOES NOT grant live capital, broker access, or deployment.      |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
| Stage 4: Operational Release Authorization                                  |
| - Scope: Explicit human governance grant for paper/live operational action.  |
| - Authority: Repository owner / compliance authorization under Gate G6.     |
+-----------------------------------------------------------------------------+
```

### 1.2 Explicit Conflict of Interest Rules

| Workstream | What They Produce | What They CAN Review | What They CANNOT Solely Approve |
|---|---|---|---|
| **Kanuj** (Scientific) | Experiment orchestrator, trial records, metric arithmetic, study reports. | Study preregistration, trial aggregation, scientific criteria. | Cannot self-certify own scientific methodology, metrics, or empirical scorecards. |
| **Krish** (Research) | Proposal engine, attempt lifecycle, model replay, raw cost receipts. | Research context consumption, prompt/feedback compatibility. | Cannot solely certify scientific claims about research producer efficacy. |
| **Matthew** (Platform) | Account ledger, risk gatekeeper, execution engine, recovery, containment. | Platform RESULT consumption, execution timing, mandate checks. | Cannot solely certify recovery, containment, or single-ledger reconciliation. |
| **Independent Reviewer** | Unconflicted audit receipts binding to exact Git SHA and report fingerprints. | Full end-to-end scientific audit, statistical assumptions, containment proof. | N/A (serves as the external validation authority). |

---

## 2. Requirement-to-Test Acceptance Matrix

Every release requirement is bound to its authoritative contract, concrete test cases,
required evidence, responsible producer, and required independent reviewer.

### Acceptance Status Definitions
- `PASS`: The requirement was executed and independently
  verified against authenticated evidence bound to the
  exact tested revision and environment.
- `FAIL`: The requirement was executed and demonstrably
  failed its acceptance criteria. Record the actual
  failing check and evidence.
- `NOT_RUN`: The required check has not been executed on
  the evaluated revision, and no specific verified
  dependency currently prevents attempting that check.
  This status never implies that the requirement passed
  or that supporting contracts have been accepted.
- `BLOCKED`: A concrete unresolved dependency, required
  unaccepted producer contract, missing authorization,
  or explicitly blocking upstream PR prevents execution
  of the required check. Identify the specific blocker.
  An unexecuted requirement with a verified blocking
  dependency must not be classified as `NOT_RUN`.
- `UNAVAILABLE`: Required source data, hardware
  environment, baseline material, or other evidence is
  unavailable. Identify the missing resource and retain
  its distinct evidence status. Unavailability is not
  success and must not be converted to `NOT_RUN` merely
  because the test did not execute.
Statuses are mutually exclusive for each requirement
at an evaluated revision. `PASS` and `FAIL` require
actual executed evidence. A requirement transitions
from `BLOCKED` to `NOT_RUN` only after its relevant
blocking conditions are verified resolved and the check
has still not been executed. Neither status can become
`PASS` without the independently verified test result.
Documentation completion, green documentation CI, and
an author's self-review are not acceptance evidence.

---

### Matrix: Core Scientific and Platform Requirements

| Ref | Requirement Description | Authoritative Contract | Concrete Test Cases | Required Evidence | Producer | Independent Reviewer | Current Status |
|---|---|---|---|---|---|---|---|
| **REQ-01** | Preregistered primary estimand is paired net terminal return | #377, #392 | POS: Paired net returns evaluated.<br>NEG: Rejection of un-paired comparison.<br>ADV: Arithmetic return sum rejected. | TrialRecordV1, StudyReportV1 citing preregistration hash. | Kanuj | Independent Scientific Reviewer | `BLOCKED` (blocked on frozen G3 preregistration and implemented bound trial/report evaluation) |
| **REQ-02** | True periodic excess-return Sharpe ratio (never geometric) | #382 | POS: Case 1 golden fixture = 0.0000.<br>NEG: Zero volatility yields UNDEFINED.<br>ADV: Legacy ann_ret/vol rejected. | Unit test reproducing all 12 golden arithmetic cases. | Kanuj | Matthew / Independent Reviewer | `BLOCKED` (blocked on accepted corrected metric runtime #445 / #446 and its verification) |
| **REQ-03** | Immutable trial event log with canonical preimage hashing | #392 | POS: Monotonic event indexing.<br>NEG: Byte alteration rejected.<br>ADV: Out-of-order event rejected. | TrialEventV1 stream with valid event_hash chain. | Kanuj | Matthew | `BLOCKED` (blocked on implemented trial-event/hash-chain validation, not merely the #392 document) |
| **REQ-04** | Causal availability and strict cutoff timestamp enforcement | #392, #376 | POS: Pre-cutoff data admitted.<br>NEG: Post-cutoff news marked INVALID.<br>ADV: Lookahead bar rejected. | Pinned market bar timestamps <= decision_cutoff. | Matthew | Kanuj | `BLOCKED` (required platform SRC producer contract #376 / PR #407 remains unaccepted; cutoff verification cannot yet be independently executed) |
| **REQ-05** | Research attempt tracking with exact attempt denominators | #375, #392 | POS: Multi-attempt proposal logged.<br>NEG: Retry inflating proposal count blocked.<br>ADV: Discarded attempts logged. | Krish attempt receipts with logical_request_id lineage. | Krish | Kanuj | `BLOCKED` (required research attempt producer contract #375 / PR #400 remains unaccepted) |
| **REQ-06** | Single authoritative account ledger with zero duplicate trades | #376, #392 | POS: Net NAV matches platform ledger.<br>NEG: Competing scientific ledger blocked.<br>ADV: Crash recovery idempotency. | Matthew platform RESULT matching portfolio account. | Matthew | Kanuj / Independent Reviewer | `BLOCKED` (required platform RESULT producer contract #376 / PR #407 remains unaccepted) |
| **REQ-07** | Single portfolio ledger and derived scientific cost attribution without double debit | #392, #382 | POS: Case 10 attribution verified.<br>NEG: Trading costs subtracted twice blocked.<br>ADV: Unknown cost yields MISSING_COST. | StudyReportV1 economic scorecard matching derived cost view and raw_cost. | Kanuj | Krish / Matthew | `BLOCKED` (blocked on accepted producer adapters and implemented report-level cost attribution) |
| **REQ-08** | Seed determinism and exact replay reproducibility | #375, #392 | POS: Replay of frozen seed matches.<br>NEG: Stochastic divergence flagged.<br>ADV: Replay zero inference bill. | Replay records yielding identical output hash. | Krish | Kanuj | `BLOCKED` (required research replay producer contract #375 / PR #400 remains unaccepted) |
| **REQ-09** | Recovery Target F: feature-off on corrected current kernel | #395 (PR #416) | POS: Kernel boots with adaptive off.<br>NEG: Adaptive execution blocked.<br>ADV: Partial state rollback clean. | Separate CODE / PRIVATE_STATE / RUNTIME results (or justified N/A), configuration and kernel verification receipts with feature flag disabled. | Matthew | Independent Reviewer | `BLOCKED` (PR #416 draft) |
| **REQ-10** | Recovery Target O: original runtime/state reconstruction | #395 (PR #416) | POS: Isolated manifest restore.<br>NEG: Incompatible DB attach blocked.<br>ADV: Corrupt snapshot rejected. | Separate CODE / PRIVATE_STATE / RUNTIME results, scoped manifest, custody/grant and isolated reconstruction receipts. | Matthew | Independent Reviewer | `BLOCKED` (PR #416 draft) |
| **REQ-11** | Recovery Target A: frozen A policy/configuration on corrected kernel | #395 (PR #416) | POS: Frozen A policy/configuration executes on corrected kernel.<br>NEG: Uncertified kernel rejected.<br>ADV: Divergent baseline halted. | Separate CODE / PRIVATE_STATE / RUNTIME results (or justified N/A) and authoritative RESULT for Target A on corrected kernel. | Matthew | Kanuj | `BLOCKED` (PR #416 draft) |
| **REQ-12** | Worker containment: external filesystem & network denial | #396 (PR #417) | POS: Confined worker writes scratch.<br>NEG: Write outside scratch denied.<br>ADV: Worker unconfined retry denied. | Accepted-enforcer denial and matched allowed-control receipts, protected-object before/after identities (applicable Cases A01-A11 in PR #417). | Matthew | Independent Reviewer | `BLOCKED` (PR #417 draft) |
| **REQ-13** | Multi-testing control & dependence-aware uncertainty | #377, #382 | POS: Stationary block bootstrap run.<br>NEG: Naive i.i.d. assumption blocked.<br>ADV: Holm-Bonferroni correction. | Bootstrap p-values with data-driven block length. | Kanuj | Independent Scientific Reviewer | `BLOCKED` (blocked on frozen DP-M1 uncertainty/multiplicity/stopping rules and their implementation) |

---

## 3. Recovery Acceptance Cases (Derived from PR #416)

Per Matthew's recovery specification ([PR #416](https://github.com/KanujVerma/drift/pull/416) `recovery.md`),
acceptance requires concrete verification of three distinct recovery targets:

For **each** target, report `CODE`, `PRIVATE_STATE`, and `RUNTIME` separately,
following recovery.md Section 5. Bind each component result to its exact revision,
manifest, scope, authorization/custody reference, run and environment, supporting
receipts, and independent verifier. A component that is not required is explicitly
identified as not applicable with a reason; it is never silently passed. Preserve passed,
failed, pending, cancelled, blocked, not-run and unavailable evidence separately.
A matching manifest hash alone is not verification of reconstructed code, retained
private state, or a working pinned runtime. Preserve subsequent trials, costs,
losses and audit lineage; a recovery target does not authorize their deletion.
Public receipts retain safe references rather than private bytes or credentials.

### Case REC-01: Target F (Feature-Off on Corrected Kernel)
- **Positive Test:** System initializes with adaptive strategy selection disabled via
  authoritative configuration (`adaptive_experiments_enabled = false`). All standard
  portfolio evaluation and reporting operations function normally.
- **Negative Test:** Any attempt by an intelligence agent or worker to schedule an
  adaptive switch or access experimental memory is rejected by the kernel.
- **Evidence Required:** Kernel startup log, configuration hash, and audit receipt
  confirming zero adaptive processes active.

### Case REC-02: Target O (Isolated Reconstruction Against Scoped Manifest)
- **Positive Test:** Original code, private state, and runtime environment are
  reconstructed in an isolated container/worktree matching a verified historical manifest.
- **Negative Test:** Reconstructed environment attempts to connect to the current
  production database or shared cache; operation is strictly blocked by network/socket isolation.
- **Evidence Required:** The separate `CODE`, `PRIVATE_STATE`, and `RUNTIME` results above, with the scoped manifest identity, authorized custodian/grant, isolated mount and environment receipts, verified reconstruction/replay results, and independent isolation evidence. Missing original state or unavailable runtime remains explicit even when manifest bytes match.

### Case REC-03: Target A (Frozen Policy/Configuration on Corrected Kernel)
- **Positive Test:** Target A executes the frozen baseline strategy/policy configuration (derived from the approved manifest, rather than hardcoded assumptions) on the independently accepted corrected kernel, generating valid platform `RESULT` records.
- **Negative Test:** If the kernel commit hash does not match the certified corrected
  kernel SHA, Target A refuses execution (`UNCERTIFIED_KERNEL_HALT`).
- **Evidence Required:** Signed kernel acceptance receipt, execution log, and platform `RESULT`.

---

## 4. Containment Acceptance Cases (Derived from PR #417)

Per Matthew's containment specification ([PR #417](https://github.com/KanujVerma/drift/pull/417) `containment.md`),
worker confinement must be verified through actual authorized external operating-system enforcement.
Do not assume a particular firewall, iptables setup, container runtime, or host security policy exists unless independently evidenced.
Prompt-level rules are not security boundaries:

Acceptance follows the independently accepted **actual enforcer and tested
environment**. For every applicable #417 A01-A11 case, retain authenticated
commands, exits/output, matched permitted controls and effective denial receipts,
plus protected-object before/after identities. A broken test environment, missing
logs, or prompt refusal is not proof of containment. Syscall names, firewall
counters and timeout behavior below are examples, not requirements to choose a
particular OS or enforcement mechanism. No probe or host change is authorized by
this document.

### Case CON-01: Filesystem Write Boundary Enforcement
- **Positive Test:** Untrusted worker processes read allowed input contexts and write
  transient outputs strictly to designated scratch paths (`.local-artifacts/` or scratch directory).
- **Negative Test (External Denial):** Worker executes a direct subprocess attempting to
  modify tracked repository files (`src/drift/`), configuration files, or parent directories.
  The accepted external enforcer denies the operation with its recorded permission-denial result (for example `EACCES`); the protected object remains unchanged.
- **Evidence Required:** Trusted denial evidence from the accepted enforcer, matched allowed read/write controls, and protected-object before/after identities bound to the tested principal, policy and environment. A Linux audit log for blocked `SYS_openat` write flags is one possible receipt, not the only accepted mechanism.

### Case CON-02: Network Egress Confinement
- **Positive Test:** Worker operates completely offline using pre-cached, point-in-time
  market and context fixtures.
- **Negative Test (Network Denial):** Worker initiates an outbound socket connection
  (e.g., DNS lookup, HTTP request to external provider, raw TCP socket). The request is
  denied by the independently accepted network policy and actual external enforcer; record whether it rejects immediately or produces the policy's bounded timeout.
- **Evidence Required:** Authenticated effective-egress-denial receipts from the actual enforcer, matched permitted fixture/network-stack controls within the authorized probe scope, and bound destination/principal/policy/environment identities. A packet-filter drop counter and bounded timeout are examples; an authenticated immediate denial may satisfy the accepted policy without either.

### Case CON-03: Refusal of Unconfined Fallback
- **Negative Test:** When a confined execution path fails or encounters resource limits,
  the worker requests an unconfined execution retry. The orchestrator rejects the request
  with `UNCONFINED_FALLBACK_PROHIBITED`.
- **Evidence Required:** Orchestrator event log and trial record marked `REFUSED`.

---

## 5. Independent Reviewer Certification Protocol

> **ILLUSTRATIVE TEMPLATE ONLY.**
> **NOT A SIGNED OR AUTHENTICATED REVIEW RECEIPT.**

The schema template below illustrates the structural format for future independent review certification. Real acceptance verdicts must come from authenticated review receipts and actual executed evidence. This template does not claim an actual reviewer certification or evaluated verdict:

```json
{
  "acceptance_record_id": "ACCEPT-RECORD-SYNTHETIC-TEMPLATE-001",
  "tested_code_commit": "0000000000000000000000000000000000000000",
  "tested_contracts": {
    "experiment_contract_hash": "placeholder_sha256_experiment_contract_hash",
    "metric_contract_hash": "placeholder_sha256_metric_contract_hash",
    "recovery_contract_hash": "placeholder_sha256_recovery_contract_hash",
    "containment_contract_hash": "placeholder_sha256_containment_contract_hash"
  },
  "dataset_manifest_hash": "placeholder_sha256_dataset_manifest_hash",
  "test_environment": {
    "os": "macOS / Linux Container",
    "python_version": "3.14.6",
    "uv_lock_hash": "placeholder_uv_lock_hash"
  },
  "matrix_results": {
    "total_requirements": 13,
    "pass_count": 0,
    "fail_count": 0,
    "not_run_count": 0,
    "blocked_count": 13
  },
  "independent_reviewer": {
    "name": "Placeholder Reviewer Name",
    "affiliation": "External Verification Workstream",
    "conflict_of_interest_attestation": "I certify that I am not the author of the code, contracts, or strategies under test."
  },
  "final_verdict": "NOT_ASSESSED_TEMPLATE"
}
```

---

## 6. Document Acceptance Matrix

| Acceptance Requirement | Status in this Document | Verification Section |
|---|---|---|
| Complete requirement-to-test matrix | Complete | Section 2 (Table REQ-01 to REQ-13) |
| Four non-conflated stages defined | Complete | Section 1.1 |
| Explicit conflict of interest rules | Complete | Section 1.2 |
| Distinct acceptance status values | Complete | Section 2 (PASS, FAIL, NOT_RUN, BLOCKED, UNAVAILABLE) |
| Derived recovery cases (PR #416) | Complete | Section 3 (Cases REC-01, REC-02, REC-03) |
| Derived containment cases (PR #417) | Complete | Section 4 (Cases CON-01, CON-02, CON-03) |
| External enforcement over prompt refusal | Complete | Section 4 (CON-01, CON-02) |
| Binding audit receipt schema | Complete | Section 5 |
| Zero Unicode em dashes (U+2014) | Enforced | Automated scan passed |
