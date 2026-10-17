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

1. Read [AGENTS.md](../../../../AGENTS.md), [decisions.md](../decisions.md) (D01-D17),
   [design.md](../design.md), [workstreams.md](../../workstreams.md),
   [requirements-crosswalk.md](../requirements-crosswalk.md),
   [stage1-decisions.md](../stage1-decisions.md) (S01-S38), and
   [stage1-roadmap.md](../stage1-roadmap.md).
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
- `PASS`: Requirement independently tested and verified against exact evidence.
- `FAIL`: Requirement tested and failed to meet acceptance criteria.
- `NOT_RUN`: Test specification exists, but test has not been executed on current head.
- `BLOCKED`: Test cannot run due to an unresolved dependency or unmerged PR.
- `UNAVAILABLE`: Required source data, hardware environment, or baseline evidence missing.

---

### Matrix: Core Scientific and Platform Requirements

| Ref | Requirement Description | Authoritative Contract | Concrete Test Cases | Required Evidence | Producer | Independent Reviewer | Current Status |
|---|---|---|---|---|---|---|---|
| **REQ-01** | Preregistered primary estimand is paired net terminal return | #377, #392 | POS: Paired net returns evaluated.<br>NEG: Rejection of un-paired comparison.<br>ADV: Arithmetic return sum rejected. | TrialRecordV1, StudyReportV1 citing preregistration hash. | Kanuj | Independent Scientific Reviewer | `NOT_RUN` (blocked on #426) |
| **REQ-02** | True periodic excess-return Sharpe ratio (never geometric) | #382 | POS: Case 1 golden fixture = 0.0000.<br>NEG: Zero volatility yields UNDEFINED.<br>ADV: Legacy ann_ret/vol rejected. | Unit test reproducing all 12 golden arithmetic cases. | Kanuj | Matthew / Independent Reviewer | `NOT_RUN` (blocked on #426) |
| **REQ-03** | Immutable trial event log with canonical preimage hashing | #392 | POS: Monotonic event indexing.<br>NEG: Byte alteration rejected.<br>ADV: Out-of-order event rejected. | TrialEventV1 stream with valid event_hash chain. | Kanuj | Matthew | `NOT_RUN` (blocked on #426) |
| **REQ-04** | Causal availability and strict cutoff timestamp enforcement | #392, #376 | POS: Pre-cutoff data admitted.<br>NEG: Post-cutoff news marked INVALID.<br>ADV: Lookahead bar rejected. | Pinned market bar timestamps <= decision_cutoff. | Matthew | Kanuj | `NOT_RUN` (blocked on #376) |
| **REQ-05** | Research attempt tracking with exact attempt denominators | #375, #392 | POS: Multi-attempt proposal logged.<br>NEG: Retry inflating proposal count blocked.<br>ADV: Discarded attempts logged. | Krish attempt receipts with logical_request_id lineage. | Krish | Kanuj | `NOT_RUN` (blocked on #375) |
| **REQ-06** | Single authoritative account ledger with zero duplicate trades | #376, #392 | POS: Net NAV matches platform ledger.<br>NEG: Competing scientific ledger blocked.<br>ADV: Crash recovery idempotency. | Matthew platform RESULT matching portfolio account. | Matthew | Kanuj / Independent Reviewer | `NOT_RUN` (blocked on #376) |
| **REQ-07** | Dual-ledger scientific cost attribution without double debit | #392, #382 | POS: Case 10 attribution verified.<br>NEG: Trading costs subtracted twice blocked.<br>ADV: Unknown cost yields MISSING_COST. | StudyReportV1 economic ledger matching raw_cost. | Kanuj | Krish / Matthew | `NOT_RUN` (blocked on #426) |
| **REQ-08** | Seed determinism and exact replay reproducibility | #375, #392 | POS: Replay of frozen seed matches.<br>NEG: Stochastic divergence flagged.<br>ADV: Replay zero inference bill. | Replay records yielding identical output hash. | Krish | Kanuj | `NOT_RUN` (blocked on #375) |
| **REQ-09** | Recovery Target F: feature-off on corrected current kernel | #395 (PR #416) | POS: Kernel boots with adaptive off.<br>NEG: Adaptive execution blocked.<br>ADV: Partial state rollback clean. | Kernel verification receipt with feature flag disabled. | Matthew | Independent Reviewer | `BLOCKED` (PR #416 draft) |
| **REQ-10** | Recovery Target O: original runtime/state reconstruction | #395 (PR #416) | POS: Isolated manifest restore.<br>NEG: Incompatible DB attach blocked.<br>ADV: Corrupt snapshot rejected. | Manifest hash matching isolated reconstruction. | Matthew | Independent Reviewer | `BLOCKED` (PR #416 draft) |
| **REQ-11** | Recovery Target A: frozen baseline on corrected kernel | #395 (PR #416) | POS: Arm A executes baseline B3.<br>NEG: Uncertified kernel rejected.<br>ADV: Divergent baseline halted. | Authoritative RESULT for Arm A on corrected kernel. | Matthew | Kanuj | `BLOCKED` (PR #416 draft) |
| **REQ-12** | Worker containment: external filesystem & network denial | #396 (PR #417) | POS: Confined worker writes scratch.<br>NEG: Write outside scratch denied.<br>ADV: Worker unconfined retry denied. | OS sandbox denial logs (Case A01-A11 in PR #417). | Matthew | Independent Reviewer | `BLOCKED` (PR #417 draft) |
| **REQ-13** | Multi-testing control & dependence-aware uncertainty | #377, #382 | POS: Stationary block bootstrap run.<br>NEG: Naive i.i.d. assumption blocked.<br>ADV: Holm-Bonferroni correction. | Bootstrap p-values with data-driven block length. | Kanuj | Independent Scientific Reviewer | `NOT_RUN` (blocked on #426) |

---

## 3. Recovery Acceptance Cases (Derived from PR #416)

Per Matthew's recovery specification ([PR #416](https://github.com/KanujVerma/drift/pull/416) `recovery.md`),
acceptance requires concrete verification of three distinct recovery targets:

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
- **Evidence Required:** Manifest SHA-256 match, isolated mount receipt, and zero-leakage attestation.

### Case REC-03: Target A (Frozen Scientific Baseline on Corrected Kernel)
- **Positive Test:** Arm A executes the frozen baseline strategy (e.g., B3 monthly rebalance)
  on the independently accepted corrected kernel, generating valid platform `RESULT` records.
- **Negative Test:** If the kernel commit hash does not match the certified corrected
  kernel SHA, Arm A refuses execution (`UNCERTIFIED_KERNEL_HALT`).
- **Evidence Required:** Signed kernel acceptance receipt, execution log, and platform `RESULT`.

---

## 4. Containment Acceptance Cases (Derived from PR #417)

Per Matthew's containment specification ([PR #417](https://github.com/KanujVerma/drift/pull/417) `containment.md`),
worker confinement must be verified through actual authorized external operating-system enforcement.
Do not assume a particular firewall, iptables setup, container runtime, or host security policy exists unless independently evidenced.
Prompt-level rules are not security boundaries:

### Case CON-01: Filesystem Write Boundary Enforcement
- **Positive Test:** Untrusted worker processes read allowed input contexts and write
  transient outputs strictly to designated scratch paths (`.local-artifacts/` or scratch directory).
- **Negative Test (External Denial):** Worker executes a direct subprocess attempting to
  modify tracked repository files (`src/drift/`), configuration files, or parent directories.
  The host operating system / container sandbox raises `EACCES` / permission denied.
- **Evidence Required:** Kernel audit log showing syscall denial (`SYS_openat` with write flags blocked).

### Case CON-02: Network Egress Confinement
- **Positive Test:** Worker operates completely offline using pre-cached, point-in-time
  market and context fixtures.
- **Negative Test (Network Denial):** Worker initiates an outbound socket connection
  (e.g., DNS lookup, HTTP request to external provider, raw TCP socket). The request is
  immediately dropped by iptables / firewall rules.
- **Evidence Required:** Packet filter drop counter increment and connection timeout receipt.

### Case CON-03: Refusal of Unconfined Fallback
- **Negative Test:** When a confined execution path fails or encounters resource limits,
  the worker requests an unconfined execution retry. The orchestrator rejects the request
  with `UNCONFINED_FALLBACK_PROHIBITED`.
- **Evidence Required:** Orchestrator event log and trial record marked `REFUSED`.

---

## 5. Independent Reviewer Certification Protocol

Before any experiment can be certified for release, the following formal audit
receipt must be signed by an independent reviewer:

```json
{
  "acceptance_record_id": "ACCEPT-STAGE1A-20261017-001",
  "tested_code_commit": "5583f112dfb45b8f6e8bc652de1cc4334ef8a247",
  "tested_contracts": {
    "experiment_contract_hash": "a1b2c3d4...",
    "metric_contract_hash": "e5f6a7b8...",
    "recovery_contract_hash": "c9d0e1f2...",
    "containment_contract_hash": "3a4b5c6d..."
  },
  "dataset_manifest_hash": "f1e2d3c4...",
  "test_environment": {
    "os": "macOS / Linux Container",
    "python_version": "3.14.6",
    "uv_lock_hash": "locked_hash_val"
  },
  "matrix_results": {
    "total_requirements": 13,
    "pass_count": 0,
    "fail_count": 0,
    "not_run_count": 8,
    "blocked_count": 5
  },
  "independent_reviewer": {
    "name": "Independent Scientific Auditor",
    "affiliation": "External Verification Workstream",
    "conflict_of_interest_attestation": "I certify that I am not the author of the code, contracts, or strategies under test."
  },
  "final_verdict": "BLOCKED_ON_GOVERNANCE_AND_DEPENDENT_CONTRACTS"
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
