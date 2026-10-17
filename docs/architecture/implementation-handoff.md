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

### 1.1 Owner: Kanuj
- Makes material product, scientific, scope, architectural escalation, authorization, and priority decisions.
- Issues binding governance determinations and approves workstream transitions.
- Authorizes release and promotion gates.

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
6. **Explicitly Labelled Proposed or Draft Specifications**: Unmerged PRs (e.g., PR #419, PR #426) and draft design documents.
7. **Conversation Context and Assistant Memory**: Transient chat memory and prompt history.

### Operational Precedence Rules
- Conversation context helps interpret intent, but can NEVER silently override accepted repository code or live GitHub issue authority.
- If accepted sources conflict, the coding agent must stop only the affected operation, formulate a concise decision packet, and escalate the conflict to the owner.
- Historical Harsha ownership strings in mandatory reading documents are superseded by accepted ADR 0017 once an individual issue migration receipt is published.
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
- Push to an issue-specific branch (`kanuj/<issue>-<slug>`).
- Open a draft pull request linking the issue.
- Record exact base SHA, head SHA, and test outcomes on the PR.
- Request independent review from designated contributors.

### 4.6 HANDOFF Phase
- Post a structured checkpoint comment on the GitHub issue.
- State verified progress, actual test evidence, remaining blockers, and the next executable task.
- Never self-approve or autonomously merge pull requests.

---

## 5. Concrete Drift Example: Self-Contained Implementation Specification

The following worked example illustrates how an architect provides complete, unambiguous requirements for a hypothetical Stage 1A experiment integration test:

```markdown
### TASK SPECIFICATION: SYNTHETIC B-VERSUS-R ORCHESTRATION TEST

1. Project: Drift (KanujVerma/drift)
2. Owner: Kanuj | Implementer: Gemini / Antigravity
3. Issue: #383 (Acceptance Design Verification)
4. Mission: Verify deterministic orchestration and dual-ledger accounting for Arm B vs. Arm R on synthetic fixtures.
5. Architecture: Stage 1A selector evaluation. Arm B (AI selector) vs. Arm R (conventional comparator) choosing among {B3, B4, B5}.
6. Existing Components:
   - B3: src/drift/baselines/b3_monthly_equal_weight_rebalance.py
   - B4: src/drift/baselines/b4_momentum.py (min 253 sessions)
   - B5: src/drift/baselines/b5_low_volatility.py (min 61 sessions)
7. Candidate Cohort: Provisional 12-ETF universe (VOO, IJH, IJR, QQQ, VEA, VWO, SHY, IEF, TLT, TIP, LQD, GLD).
8. Execution Timeline: 253 warmup sessions + 126 unscored observation sessions. Fresh accounts ($10,000.00 USD each) initialize for scored phase. Both start in Strategy B3. First switch evaluated after first scored month.
9. Producer Authority:
   - Matthew owns authoritative portfolio RESULT, cash, positions, and trading costs.
   - Krish owns candidate proposals, attempts, model replay, and raw_cost receipts.
   - Kanuj owns derived scientific cost-attribution view.
10. Synthetic Input Fixture:
   - Arm B: Initial NAV $10,000.00, Gross gain +$150.00, Trading costs $30.00 -> Net gain +$120.00, Terminal NAV $10,120.00. Operating cost $25.00.
   - Arm R: Initial NAV $10,000.00, Gross gain +$80.00, Trading costs $20.00 -> Net gain +$60.00, Terminal NAV $10,060.00. Operating cost $5.00.
11. Expected Analytical Calculations:
   - Arm B Net Return: (10120 - 10000) / 10000 = 0.0120 (1.20%)
   - Arm R Net Return: (10060 - 10000) / 10000 = 0.0060 (0.60%)
   - Paired Net Return Difference: 0.0120 - 0.0060 = 0.0060 (0.60 percentage points)
   - Arm B Economic Gain: 120.00 - 25.00 = 95.00 USD
   - Arm R Economic Gain: 60.00 - 5.00 = 55.00 USD
   - Comparative Economic Advantage: 95.00 - 55.00 = 40.00 USD
12. Required Assertions:
   - Account B NAV == 10120.00; Account R NAV == 10060.00.
   - Net return difference == 0.0060; Economic advantage == 40.00 USD.
   - Zero operating costs debited from portfolio cash balances.
   - Trading costs deducted exactly once inside platform NAV.
   - Accounts B and R remain strictly isolated.
13. Status and Limitations:
   - This example specifies a future synthetic test harness; it does not implement runtime code.
   - It does NOT demonstrate real-world AI investment profitability.
   - R's exact utility formula remains an open decision packet (DP-R6) requiring formal approval before scored evaluation.
```

---

## 6. Continuity Checkpoint Template

To preserve durable continuity across sessions, agents must record checkpoints on GitHub issues using this exact template:

```markdown
## Continuity Checkpoint

- **Task / Issue**: [e.g., #427 Standard Coding-Agent Implementation Handoff]
- **Accountable Owner**: [e.g., Kanuj]
- **Actual Execution Agent**: [e.g., Gemini / Antigravity]
- **GitHub Publisher**: [e.g., KanujVerma]
- **Current Branch**: [e.g., kanuj/427-implementation-handoff]
- **Base SHA**: [e.g., 5583f112dfb45b8f6e8bc652de1cc4334ef8a247]
- **Head SHA**: [e.g., a1b2c3d4e5f6...]
- **Exact Modified Paths**:
  - [e.g., docs/architecture/implementation-handoff.md]
- **Accepted Architecture References**:
  - [e.g., AGENTS.md, docs/architecture/workstreams.md]
- **Draft or Unresolved Dependencies**:
  - [e.g., PR #426 unmerged, PR #419 unmerged]
- **Tests Actually Executed**:
  - [e.g., git diff --check, relative link validation script]
- **Observed Results**:
  - [e.g., All checks passed; 0 whitespace errors, 0 em dashes]
- **Tests Not Run**:
  - [e.g., Full pytest suite (docs-only task)]
- **Review Findings**:
  - [e.g., None]
- **Independent Approvals**:
  - [e.g., Awaiting review from @Krish-Verma]
- **Remaining Blockers**:
  - [e.g., Independent review sign-off and PR merge]
- **Next Executable Action**:
  - [e.g., Coordinate navigation update once PR #419 releases stage1-roadmap.md]
```

### Checkpoint Invariants
- Never claim a test result without citing concrete execution evidence.
- Never infer that an architecture proposal is accepted merely because a draft PR exists.
- Do not mirror live session state into permanent architectural documentation.

---

## 7. Cold-Start Resume Protocol

A replacement agent resuming a Drift task without access to prior assistant chat memory must follow this ten-step protocol:

1. **Read Universal Bootstrap**: Read [AGENTS.md](../../AGENTS.md) to understand core constraints, machine paths, and operating rules.
2. **Resolve Workstream Identity**: Check `git config --get drift.workstream` and issue labels to confirm active workstream (`kanuj`, `krish`, or `matthew`).
3. **Read Resume Protocol**: Read the Resume and Checkpoint guidelines in [agent-workflow.md](agent-workflow.md).
4. **Inspect Assigned Issue**: Query the active GitHub issue (`gh issue view <id>`), including all recent comments and linked PRs.
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
5. **Permission Boundary Exceeded**: The task requires live broker credentials, network access, or paid service interaction.
6. **Architectural Contradiction**: Accepted repository specifications contain mutually contradictory requirements.

### Escalation and Parallel Progress
- When a stop condition fires, the agent must formulate a concise decision packet for the owner:
  - What was discovered.
  - Why a decision is needed.
  - Viable options with tradeoffs.
  - Recommended option.
  - Exact question requiring a ruling.
- Halting an affected branch does not mean stopping all work: the agent must immediately proceed with other unblocked, authorized tasks (such as documentation or independent verification) while awaiting resolution.
