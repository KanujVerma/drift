# Implementation Handoff Standard for Coding Agents

## Status and Governance Boundary

- **Issue Reference**: GitHub Issue #427 (Workstream: Kanuj).
- **Accountable Feature Owner**: Kanuj.
- **Publisher**: KanujVerma.
- **Document Status**: Proposed repository workflow specification under #427. Not automatically accepted until independently reviewed and merged.
- **Operating Rules**: Conforms to repository root [AGENTS.md](../../AGENTS.md), [agent-workflow.md](agent-workflow.md), and [workstreams.md](workstreams.md). Zero Unicode em dashes permitted.

---

## 1. Roles and Responsibilities

Drift engineering workflows divide pair programming and execution into four distinct roles:

### 1.1 Owner: Authenticated Accountable Feature Owner
- **Resolution**: Resolved per feature and issue from:
  - Current accepted workstream governance ([AGENTS.md](../../AGENTS.md), [workstreams.md](workstreams.md)).
  - Assigned GitHub issue, verified assignee, and authenticated actor.
  - Effective ownership migration receipts (e.g., ADR 0017 receipts).
  - Exact feature and subsystem responsibility.
- **Responsibilities**:
  - Makes material product, scientific, scope, architectural escalation, authorization, and priority decisions for that feature.
  - Approves bounded implementations and workstream transitions.
  - Resolves architectural escalations formulated by the implementer.
  - Preserves upstream and downstream contracts and producer boundaries.
- **Workstream Ownership Boundaries**:
  - **Kanuj**: Accountable owner of his own features and the transferred scientific experiment deliverables (under accepted [ADR 0017](../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md) and verified per-issue migration receipts).
  - **Krish**: Accountable intelligence and research producer (owns inner learning loop, candidate generation, R optimizer, and model replay/receipts).
  - **Matthew**: Accountable platform producer (owns data qualification, execution, mandatory risk, accounting ledger, and authoritative `RESULT`).
  - Kanuj does not automatically become the technical owner of Krish's or Matthew's producer code.

### 1.2 Architect: ChatGPT or Designated Architect Agent
- Understands user intent, domain requirements, and macroeconomic constraints.
- Recovers project decisions from accepted specifications and live GitHub state.
- Performs architectural analysis and selects algorithms, interfaces, and state representations.
- Defines data flows, causality boundaries, and accounting rules.
- Produces unambiguous, self-contained implementation instructions.
- Specifies deterministic positive, negative, and adversarial tests with exact expected numerical outcomes.
- Challenges architectural contradictions, scope creep, and unverified assumptions.
- Reviews actual code and documentation deliveries against the architectural plan.

### 1.3 Implementer: Gemini / Antigravity or Other Coding Agent
- Writes explicitly authorized code and documentation files within designated write-sets.
- Wires accepted interfaces without inventing alternative schemas or competing subsystems.
- Handles routine engineering autonomously: syntax, typing, mechanical choices, and debugging.
- Executes automated test suites and verifies output against explicit expected results.
- Creates issue-specific Git branches and draft pull requests.
- Reports empirical test outcomes and observed failures honestly.

### 1.4 Reviewer: Distinct Authenticated Reviewer
- Conducts independent verification and acceptance of pull requests.
- **Independence Principle**: The architect's review of its own specified design constitutes valuable technical quality assurance, but does NOT satisfy independent review requirements.
- **Automated Tool Principle**: Codex automated code reviews provide supplemental technical linting and security checks, but do NOT substitute for human or peer review acceptance.
- Producers cannot self-certify their own work.

---

## 2. Source-of-Truth Priority

When an agent encounters ambiguous or conflicting statements, it must strictly apply the following precedence hierarchy:

1. **Current Accepted Repository Governance**: Universal bootstrap rules in [AGENTS.md](../../AGENTS.md) and operative ownership rules in [workstreams.md](workstreams.md).
2. **Authenticated Live GitHub Issue and PR State**: Current issue ownership, assignees, labels, native blockers, and recorded comment handoffs.
3. **Accepted ADRs and Frozen Contracts**: Durable decisions in `docs/adr/` and accepted producer contracts.
4. **Accepted Code and Tests at Exact Revisions**: Merged implementations under `src/drift/` and passing test suites under `tests/`.
5. **Owner-Directed Decisions Recorded with Provenance**: Binding owner directions recorded on GitHub issues with traceable rationale.
6. **Explicitly Labelled Proposed or Draft Specifications**: Unmerged draft pull requests (verified live on GitHub at Resume time) and draft design documents.
7. **Conversation Context and Assistant Memory**: Transient chat memory and prompt history.

### Operational Precedence Rules
- Conversation context helps interpret intent, but can NEVER silently override accepted repository code or live GitHub issue authority.
- If accepted sources conflict, the coding agent must stop only the affected operation, formulate a concise decision packet, and escalate the conflict to the owner.
- Historical Harsha ownership strings in mandatory reading documents are superseded by accepted [ADR 0017](../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md) once an individual issue migration receipt is published. Historical Harsha records remain readable as historical evidence on older records, but do not authenticate active execution or permission.
- Unmerged pull requests and draft designs must never be treated as accepted runtime truth.

---

## 3. Mandatory Prompt Contract (Architect to Implementer)

Every task handoff from the architect agent to the implementer agent must be self-contained and include the following fifteen explicit components:

1. **Project and Repository**: Exact repository identity and target clone root.
2. **Accountable Owner and Actual Execution Agent**: Named feature owner and agent executor identity.
3. **Issue, Authorization, and Writer Claim**: GitHub issue number, readiness status, and exclusive writer confirmation.
4. **Mission and Measurable Desired Result**: Concise mission statement and objective definition of done.
5. **Exact Approved Architecture**: Concrete architectural choices, eliminating guesswork.
6. **Relevant Existing Code and Interface Locations**: Explicit file paths and class names.
7. **Input and Output Structures and Units**: Precise field types, formats, and dimension units.
8. **Data-Flow and State-Transition Rules**: Sequential pipeline stages and state lifecycles.
9. **Error, Unavailable, and Refusal Behavior**: Defensive handling of missing data, lookahead violations, and mandate rejections.
10. **Exact File Write-Set and Protected Paths**: Exhaustive list of permitted writable paths; all others protected.
11. **Positive and Adversarial Test Fixtures**: Deterministic test inputs covering standard and edge-case execution.
12. **Expected Numerical or Structural Assertions**: Exact analytical figures to verify (e.g., Decimal calculations).
13. **Dependencies and Unresolved Decisions**: Identified upstream contracts and open Decision Packets.
14. **Publication and Review Requirements**: Branch naming, draft PR status, and designated independent reviewers.
15. **Final Reporting Format and Definition of Done**: Structured summary format required upon completion.

**Vagueness Prohibition**: Instructions such as "figure out the architecture" or "implement the experiment system" violate this contract. Implementers may identify architectural contradictions with evidence, but may not silently alter locked specifications.

---

## 4. Implementation Execution Process

Implementation proceeds through six disciplined, sequential phases:

```
[ READ ] ──> [ IMPLEMENT ] ──> [ TEST ] ──> [ VERIFY ] ──> [ PUBLISH ] ──> [ HANDOFF ]
```

### 4.1 READ Phase
- Read the assigned GitHub issue, relevant accepted ADRs, and existing codebase interfaces.
- Verify repository HEAD, workstream configuration, unblocked dependencies, and writer reservations.

### 4.2 IMPLEMENT Phase
- Edit or create only files listed in the explicit write-set.
- Reuse existing producer-owned interfaces; never create competing implementations of canonical logic (e.g., do not add a second backtester or account ledger).

### 4.3 TEST Phase
- Execute relevant deterministic test suites using pinned virtual environment tools.
- Compare actual execution results against explicit expected numerical outputs.
- Execute authorized negative and adversarial test cases.

### 4.4 VERIFY Phase
- Inspect Git diff and staged files (`git status`, `git diff --check`).
- Confirm zero unauthorized file modifications.
- Confirm zero Unicode em dashes (U+2014) introduced.
- Maintain unexecuted test suites as `NOT_RUN` or `BLOCKED`.

### 4.5 PUBLISH Phase
- Commit changes with focused, informative commit messages.
- Push to an issue-specific branch using `<verified-workstream>/<issue>-<slug>` (e.g., `kanuj/<issue>-<slug>`, `krish/<issue>-<slug>`, or `matthew/<issue>-<slug>`).
  - Explicit, accepted coordination-branch exceptions (e.g., `coord/<slug>`) remain permitted.
  - Historical branches are not automatically renamed.
  - The branch prefix alone does not authenticate its owner.
- Open a draft pull request linking the issue.
- Record exact base SHA, head SHA, and test outcomes on the PR.
- Request independent review from designated contributors.

### 4.6 HANDOFF Phase
- Post a structured checkpoint comment on the GitHub issue.
- State verified progress, actual test evidence, remaining blockers, and the next executable task.
- Never self-approve or autonomously merge pull requests.

---

## 5. Concrete Drift Example: Self-Contained Implementation Specification

The following worked example illustrates how an architect provides complete, unambiguous requirements for a hypothetical Stage 1A experiment integration test, satisfying all fifteen mandatory prompt contract components defined in Section 3:

```markdown
### TASK SPECIFICATION: SYNTHETIC B-VERSUS-R ORCHESTRATION TEST (ILLUSTRATIVE FUTURE SPECIFICATION)

1. PROJECT AND REPOSITORY:
   Drift, KanujVerma/drift. Target REPO_ROOT.

2. ACCOUNTABLE OWNER AND ACTUAL EXECUTION AGENT:
   Accountable Owner: Kanuj | Actual Execution Agent: Gemini / Antigravity.

3. ISSUE, AUTHORIZATION, AND WRITER CLAIM:
   Hypothetical future runtime implementation issue (e.g., #999 'Implement Synthetic Stage 1A B/R Integration Test').
   Note: GitHub issue #383 is an acceptance design specification only and does NOT authorize creating runtime code.
   A new, dedicated runtime issue and recorded writer claim are mandatory prior to implementation.

4. MISSION AND MEASURABLE DESIRED RESULT:
   Test one synthetic B-versus-R campaign execution end-to-end and verify account isolation, causal timing,
   scientific eligibility evaluation, trial evidence completeness, and comparative economics without double-counting costs.

5. EXACT APPROVED ARCHITECTURE:
   Stage 1A selector evaluation under Matthew's single authoritative portfolio ledger plus Kanuj's derived scientific
   cost-attribution view. Arm B is the adaptive AI selector; Arm R is the deterministic conventional comparator.
   Both choose strictly among {B3, B4, B5}:
   - B3: Monthly equal-weight rebalance.
   - B4: 12-minus-1 cross-sectional momentum (requires >= 253 history sessions, top ceil(n/2) selection).
   - B5: 60-return low volatility (requires >= 61 history sessions, bottom ceil(n/2) selection).
   Both operate under the identical Balanced portfolio mandate and identical time-eligible information.

6. RELEVANT EXISTING CODE AND INTERFACE LOCATIONS:
   - Existing Implemented Source Modules (on main):
     - B3 Baseline: src/drift/baselines/b3_monthly_equal_weight_rebalance.py
     - B4 Baseline: src/drift/baselines/b4_momentum.py
     - B5 Baseline: src/drift/baselines/b5_low_volatility.py
   - Proposed Contract Dependencies (Unmerged Proposals, Not Implemented Runtime Types):
     - Scientific Contract (#392 / PR #434): docs/architecture/adaptive-experiments/contracts/experiment.md
     - Research Contract (#375 / PR #400): docs/architecture/adaptive-experiments/contracts/research.md
     - Platform and Accounting Contract (#376 / PR #407): docs/architecture/adaptive-experiments/contracts/platform.md
     - Timing and Execution Contract (#379 / PR #412): docs/architecture/adaptive-experiments/contracts/execution.md
     - Mandate and Risk Contract (#380 / PR #414): docs/architecture/adaptive-experiments/contracts/mandate.md
   - Interface Invariants:
     - These contract documents are proposals until their actual accepted revisions are verified; they are NOT currently implemented interfaces or existing Python types.
     - A future implementer must verify acceptance, availability, and pinned revisions at Resume before consumption.
     - No fabricated runtime interfaces, synthetic Python symbol imports, or competing account ledgers.

7. INPUT AND OUTPUT STRUCTURES AND UNITS:
   - Concrete Fixture Identifiers:
     - Fixture ID: `SYNTH-STAGE1A-BR-001`
     - Campaign ID: `SYNTH-CAMPAIGN-001`
     - Run ID: `SYNTH-RUN-001`
   - Arms and Account Bindings:
     - `ARM-B` -> `ACC-SYNTH-B-001` (initial capital: 10000.00 USD; initially selects B3)
     - `ARM-R` -> `ACC-SYNTH-R-001` (initial capital: 10000.00 USD; initially selects B3)
   - Session History Boundaries:
     - Warmup: W001 through W253, inclusive (253 completed synthetic sessions).
     - Observation: O001 through O126, inclusive (126 completed synthetic sessions).
     - Total unscored history: 379 completed synthetic sessions.
     - Scored Phase: After O126, fresh scored accounts initialize.
     - First Scored Month: S001 through S021, inclusive (21 completed synthetic sessions).
     - S021 completes the synthetic first scored month; no selector switch occurs prior to S021.
   - Source and Decision Clocks:
     - Decision Cutoff: `2026-01-30T21:00:00Z`
     - SRC-EARLY Availability: `2026-01-30T20:59:59Z` (time-eligible; available before cutoff)
     - SRC-LATE Availability: `2026-01-30T21:00:01Z` (ineligible; arrives after cutoff)
     - Decision Finalized: `2026-01-30T21:00:05Z` (post-cutoff finalization does not admit late source data)
     - Next Eligible Synthetic Execution Open: `2026-02-02T14:30:00Z` (no same-close execution)
   - Candidate Strategy Proposals (Given Fixture Artifacts):
     - PB-001: Arm B | Current: B3 | Proposed: B4 | Evidence: SRC-EARLY
     - PR-001: Arm R | Current: B3 | Proposed: B3 | Evidence: SRC-EARLY
     - Note: Proposals are GIVEN fixture artifacts; no live Gemini model or R optimizer is invoked.
     - Mock Mandate Responses: PB-001 -> `PERMITTED_BY_MOCK`; PR-001 -> `INCUMBENT_UNCHANGED_BY_MOCK` (illustrative descriptions, not Matthew's accepted API enums).
   - Synthetic Price Sentinels:
     - VOO: Decision close 100.00 USD | Next eligible open 101.00 USD
     - IEF: Decision close 50.00 USD | Next eligible open 49.50 USD
     - Sentinels test that decision close and next open are distinct; prices do not independently generate terminal NAV.
   - Mock Platform RESULT Payloads (Given Values, No Execution Claimed):
     - RESULT-B-001: account_id: `ACC-SYNTH-B-001`, initial_nav: 10000.00, gross_gain: 150.00, trading_cost: 30.00, terminal_net_nav: 10120.00
     - RESULT-R-001: account_id: `ACC-SYNTH-R-001`, initial_nav: 10000.00, gross_gain: 80.00, trading_cost: 20.00, terminal_net_nav: 10060.00
   - Mock Research Cost References (Abbreviated Illustrative Receipts):
     - RCPT-B-001: arm_id: `ARM-B`, amount: "25.00", currency: USD, amount_basis: actual
     - RCPT-R-001: arm_id: `ARM-R`, amount: "5.00", currency: USD, amount_basis: actual
     - Note: Abbreviated records are illustrative, not complete production raw_cost receipts.
   - Numeric Representation: Explicit DecimalText USD values; all outputs classified SYNTHETIC_ONLY.

8. DATA-FLOW AND STATE-TRANSITION RULES:
   Sequential pipeline:
   1. Decision Context Cutoff T(t_k) at session close (`2026-01-30T21:00:00Z`).
   2. Candidate Proposals Generated: PB-001 (B3 -> B4) and PR-001 (B3 -> B3) bound to SRC-EARLY.
   3. Phase A (Scientific Pre-Decision Input Eligibility): Validates source timestamps <= cutoff; SRC-EARLY passes, SRC-LATE rejected.
   4. Phase B (Matthew Operational Mandate Verdict): Mock mandate evaluates Balanced constraints (PB-001 permitted, PR-001 unchanged).
   5. Phase C (Matthew Execution, Fills, Accounting, and Authoritative RESULT): Transition scheduled for next eligible session open (`2026-02-02T14:30:00Z`; no same-close fill); platform ledger updates cash, positions, and NAV, emitting RESULT-B-001 and RESULT-R-001.
   6. Phase D (Scientific Evidence Completeness, Derived Research Cost Attribution, and Comparative Reporting): Krish research receipts RCPT-B-001 and RCPT-R-001 joined into derived scientific cost view without debiting portfolio cash; computes paired return difference and comparative economic advantage.

9. ERROR, UNAVAILABLE, AND REFUSAL BEHAVIOR:
   - Missing lookback history or market data: UNAVAILABLE.
   - Malformed schema, tampered bytes, or corrupted preimage: INVALID.
   - Missing platform RESULT: PENDING_RESULT.
   - Unknown research operating costs: MISSING_COST in derived attribution view (portfolio NAV preserved; no fabricated zero).
   - Unknown execution outcome: UNRESOLVED.
   - Mandate refusal: Rejects transition orders; account retains valid incumbent; never dispatches order.
   - Duplicate event submission: Idempotent processing; zero duplicate orders or charges.
   - Missing history: Never triggers automatic account liquidation.

10. EXACT FILE WRITE-SET AND PROTECTED PATHS:
    - Illustrative Proposed Write-Set: `tests/integration/test_stage1_br_synthetic.py`
    - Protected Surfaces: All production code (`src/drift/`), contracts, and architecture docs remain read-only.
    (This is an illustrative hypothetical write-set only, NOT a currently authorized write-set).

11. POSITIVE AND ADVERSARIAL TEST FIXTURES:
    - Positive Fixture: `SYNTH-STAGE1A-BR-001` as specified in Component 7 above.
    - Negative Fixtures (Explicit Mutations to Positive Baseline):
      - N01 (LATE SOURCE): PB-001 references SRC-LATE (`2026-01-30T21:00:01Z`). Expected: UNAVAILABLE for that decision context; no qualified proposal from late evidence.
      - N02 (MALFORMED PROPOSAL): Remove PB-001.selected_strategy. Expected: INVALID; no mandate evaluation or transition dispatch.
      - N03 (CROSS-ARM LEAKAGE): PB-001 references private ARM-R research evidence. Expected: INVALID; zero cross-arm evidence admission.
      - N04 (MISSING RESULT): Remove RESULT-B-001. Expected: PENDING_RESULT; no invented B terminal NAV; paired economic report refused.
      - N05 (UNKNOWN COST): Set RCPT-B-001.amount = null, amount_basis = unknown, currency = null, nonempty unknown_reason. Expected: Known portfolio NAV remains reportable; economic comparison classified MISSING_COST / UNAVAILABLE (no fabricated zero).
      - N06 (IDEMPOTENT REPLAY): Resubmit identical event ID and payload. Expected: Exactly one logical event processed; zero duplicate orders; zero duplicate cost attribution.
      - N07 (CONFLICTING DUPLICATE): Resubmit identical event ID with modified payload bytes. Expected: Rejection of conflicting duplicate; original immutable evidence preserved.
      - N08 (MANDATE REFUSAL): Change B mandate outcome to REFUSED_BY_MOCK. Expected: No B4 transition order; Arm B retains B3 only with independently verified valid current state, evidence, and mandate compliance; do not reuse positive-case RESULT as proof.
      - N09 (NO SELECTOR SWITCH): PR-001 selects incumbent B3. Expected: No selector-level transition; B3's fixed internal equal-weight rebalancing remains separate.
    All expected classifications are proposed scientific semantics, not proof that runtime types exist.

12. EXPECTED NUMERICAL OR STRUCTURAL ASSERTIONS:
    - Arm B Platform Calculations:
      - Initial NAV: 10,000.00 USD
      - Gross Gain: +150.00 USD
      - Trading Costs: 30.00 USD (deducted within platform ledger)
      - Net Gain: 150.00 - 30.00 = 120.00 USD
      - Terminal Net NAV: 10,000.00 + 120.00 = 10,120.00 USD
      - Portfolio Return: 120.00 / 10,000.00 = 0.0120 (1.20%)
      - Research Operating Cost: 25.00 USD (RCPT-B-001)
      - Economic Gain: 120.00 - 25.00 = 95.00 USD
    - Arm R Platform Calculations:
      - Initial NAV: 10,000.00 USD
      - Gross Gain: +80.00 USD
      - Trading Costs: 20.00 USD (deducted within platform ledger)
      - Net Gain: 80.00 - 20.00 = 60.00 USD
      - Terminal Net NAV: 10,000.00 + 60.00 = 10,060.00 USD
      - Portfolio Return: 60.00 / 10,000.00 = 0.0060 (0.60%)
      - Research Operating Cost: 5.00 USD (RCPT-R-001)
      - Economic Gain: 60.00 - 5.00 = 55.00 USD
    - Comparative Metrics:
      - Paired Return Difference: 0.0120 - 0.0060 = 0.0060 (0.60 percentage points)
      - Comparative Economic Advantage: 95.00 - 55.00 = 40.00 USD
    - Accounting Invariants:
      - Trading expenses are already accounted for inside platform NAV.
      - Research operating expenses NEVER debit portfolio cash.
      - Single authoritative account ledger: no secondary accounting system.

13. DEPENDENCIES AND UNRESOLVED DECISIONS:
    - Producer-integrated Level 2 execution requires accepted, merged producer contracts (#375, #376, #379, #380, #392, #382).
    - The exact R utility formula parameters (DP-R6) and confirmatory statistical thresholds (DP-M1) remain unapproved decisions before Gate G3.
    - Mock Level 1 verification can be separately authorized prior to Level 2.

14. PUBLICATION AND REVIEW REQUIREMENTS:
    - Execute only after a dedicated runtime issue is created, unblocked, and claimed.
    - Implement on an issue-specific branch (e.g., `<verified-workstream>/<issue>-<slug>`) using exact authorized write-set.
    - Execute real test suites and record base and head commit SHAs.
    - Publish as draft PR; request independent reviews from platform owner (Matthew) and research owner (Krish).
    - Never self-approve or merge pull requests autonomously.

15. FINAL REPORTING FORMAT AND DEFINITION OF DONE:
    - Structured report detailing: exact files changed, executed tests, observed vs. expected assertions, negative test outcomes, evidence references, draft PR link, remaining blockers, and next executable action.
    - Missing runtime test execution must be reported as NOT_RUN.
    - Synthetic test results must NOT be claimed as evidence of real-world investment efficacy.
```

**Implementation Boundary and Fixture Acceptance Boundary**:
- The example above illustrates a complete, self-contained implementation handoff contract.
- It DOES NOT implement the fixture.
- It DOES NOT run Krish's research producer.
- It DOES NOT run Matthew's execution engine.
- It DOES NOT prove actual producer compatibility.
- It DOES NOT establish investment profitability, scientific efficacy, broker safety, or trading authority.
- Issue #383 is documentation-only and does NOT authorize writing runtime code.
- A future runtime issue needs its own exact write-set.

---

## 6. Continuity Checkpoint Template

To preserve durable continuity across sessions, agents must record checkpoints on GitHub issues. Drift maintains a single authoritative Checkpoint specification; agents must not define or use competing templates.

The single authoritative source is the [Canonical Checkpoint](agent-workflow.md#checkpoint) defined in `docs/architecture/agent-workflow.md`.

Agents must copy the current canonical template in full at execution time without omitting or renaming mandatory fields:

- Workstream and accountable owner.
- Actual agent and GitHub actor.
- Issue, PR, branch, base and HEAD.
- Task state and exact objective.
- Reserved, changed and released paths.
- Completed verification.
- Focused tests with interpreter and results.
- Full CI SHA, run ID and actual status.
- Contract versions and decision evidence.
- Known failures and limitations.
- Documentation impact.
- Native blockers and affected consumers.
- Uncommitted files.
- Exact next action.

Optional supporting information may be appended, but never replace or omit canonical fields.

### Checkpoint Invariants
- Never claim a test result without citing concrete execution evidence.
- Never infer that an architecture proposal is accepted merely because a draft PR exists.
- Do not mirror live session state into permanent architectural documentation.

---

## 7. Cold-Start Resume Protocol

A replacement agent resuming a Drift task without access to prior assistant chat memory must follow this ten-step protocol:

1. **Read Universal Bootstrap**: Read [AGENTS.md](../../AGENTS.md) to understand core constraints, machine paths, and operating rules.
2. **Resolve Workstream Identity**: Check `git config --get drift.workstream` and issue labels to confirm active workstream (`kanuj`, `krish`, or `matthew`). Historical `harsha` labels and records remain recognizable when inspecting older GitHub evidence, but do not authenticate active execution or permission.
3. **Read Resume Protocol**: Read the Resume and Checkpoint guidelines in [agent-workflow.md](agent-workflow.md).
4. **Inspect Assigned Issue**: Query the active GitHub issue and all recent comments (`gh issue view <id> --comments`). Separately verify linked PRs, native dependencies, and review state via dedicated GitHub queries.
5. **Inspect Accepted ADRs**: Review durable decisions in `docs/adr/` governing the feature area.
6. **Verify Current Git State**: Confirm current branch, remote tracking status, working tree cleanliness, and exact commit SHAs.
7. **Locate Latest Checkpoint**: Identify the most recent GitHub continuity checkpoint comment on the issue.
8. **Reconstruct Scope**: Separate accepted historical milestones from active proposals and unmerged drafts.
9. **Verify Allowed Write-Set**: Confirm the exact writable file paths authorized by the issue.
10. **Execute Next Task**: Resume execution on the next unblocked, authorized task.

**Independence Standard**: A replacement agent following this protocol must be fully capable of continuing work cleanly without requiring past chat transcripts or undocumented private scratch files.

---

## 8. Review and Acceptance Hierarchy

System verification is structured into distinct, non-fungible tiers:

```
[ Tier 1: Syntax & Formatting ]
              │
              ▼
[ Tier 2: Unit Test Execution ]
              │
              ▼
[ Tier 3: Deterministic Integration ]
              │
              ▼
[ Tier 4: Producer Contract Compatibility ]
              │
              ▼
[ Tier 5: Independent Scientific Acceptance ]
              │
              ▼
[ Tier 6: Operational Release Permission ]
```

### Tier Separation Rules
- A successful lower-level verification does NOT automatically grant acceptance at a higher tier.
- A passing Markdown lint check does not establish unit test correctness.
- Passing unit tests do not prove end-to-end integration across subsystems.
- Passing synthetic integration does not prove scientific validity or investment efficacy.
- Passing scientific acceptance does not grant operational trading permission.
- A new Git commit invalidates prior verification evidence; test suites must be rerun on the exact new HEAD commit.
- Reviewer independence is mandatory: authors and implementing agents cannot accept their own pull requests.

---

## 9. Stop Conditions and Escalation Protocol

An implementation agent must immediately halt its active write-branch and formulate a decision packet when any of the following stop conditions occur:

1. **No Authorized Issue**: The requested work lacks an approved, open GitHub issue.
2. **Issue Blocked**: The issue's native prerequisites or activation conditions are unsatisfied.
3. **Writer Reservation Conflict**: Another active pull request or developer workstream reserves the target file path.
4. **Missing Producer Contract**: An upstream contract required for implementation is unaccepted or unavailable.
5. **Permission Boundary Exceeded**: An operation requires network access, provider credentials, spending, broker capabilities, or external services outside the explicit authorization of the assigned issue.
   - Normal authorized GitHub operations remain permitted: reading issues and PRs, fetching repository revisions, publishing authorized issue branches, running approved CI, and requesting reviews.
   - An agent may NOT interpret ordinary GitHub access as authorization for unrelated provider API calls, broker access, paid services, or real capital.
6. **Architectural Contradiction**: Accepted repository specifications contain mutually contradictory requirements.

### Escalation and Parallel Progress
- When a stop condition fires, the agent must formulate a concise decision packet for the owner:
  - What was discovered.
  - Why a decision is needed.
  - Viable options with tradeoffs.
  - Recommended option.
  - Exact question requiring a ruling.
- Halting an affected branch does not mean stopping all work: the agent must immediately proceed with other unblocked, authorized tasks (such as documentation or independent verification) while awaiting resolution.
