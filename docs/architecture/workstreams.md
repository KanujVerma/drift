# Drift Workstream Ownership

GitHub Issues, native dependencies, and PRs are the live work queue. This
document owns durable workstream policy and ownership only.

Do not treat this file as a live status tracker. Do not add current issue
numbers, temporary blockers, live branch names, percent complete, or session
status here.

---

## 1. Purpose

Drift has two long-lived implementation workstreams:

- **kanuj**: research and autonomous R&D
- **krish**: statistics, safety, execution, and live systems

This document is the canonical durable ownership contract for those
workstreams. It tells any zero-context human or coding agent:

- which human/workstream it belongs to;
- which milestones that workstream permanently owns;
- what the other workstream owns;
- how to select the next GitHub issue;
- which files it may modify;
- how to request a cross-workstream contract change;
- how to stop for architecture adjudication;
- how to continue without prior chat memory.

Live task state lives only in GitHub. Implementation truth lives in code,
schemas, tests, and Git history.

---

## 2. One Milestone, One Owner

**Invariant:** one roadmap milestone has exactly one human workstream owner.

Do not split milestone implementation across Kanuj and Krish to increase
short-term parallelism. Within a milestone, its owner owns:

- implementation;
- tests;
- milestone-local contracts;
- milestone-local documentation;
- integration work belonging to that milestone;
- milestone acceptance work unless external architecture review is required.

Ownership transfer is exceptional. Informal chat transfer is invalid. A valid
transfer requires:

1. an explicit GitHub issue stating the transfer, evidence, and remaining
   write-set;
2. a canonical update to the ownership table in this document;
3. GitHub label and assignment updates on affected issues.

There is no permanent `shared` workstream. Cross-workstream work still has
exactly one execution owner.

---

## 3. Exact 8/8 Bounded Milestone Ownership

The bounded roadmap milestones M2 through M17 contain exactly 16 milestone
IDs. Ownership is exactly eight bounded milestones each.

This is 50/50 by bounded milestone count. It is not a 50/50 difficulty split.
The harder statistical, safety, execution, and live-systems milestones are
intentionally skewed to Krish.

### Kanuj owns exactly 8

| Milestone | Title |
|---|---|
| M2 | Deterministic Session-Level Evaluator and Portfolio Accounting Kernel |
| M3 | Deterministic Baselines |
| M4 | Prediction / Outcome Tracking |
| M6 | Structured Research Memory |
| M7 | First AI Research Agent |
| M8 | Recursive R&D Loop |
| M9 | Multi-Agent Research, only if evidence warrants activation |
| M10 | Champion / Challenger Tournament |

Kanuj's chain is:

```text
M2 -> M3 -> M4 -> M6 -> M7 -> M8 -> M9 -> M10
```

M2 is entirely Kanuj-owned. Krish must not modify M2 runtime or M2 task
implementation. Krish may read M2 contracts as future dependencies.

M9 remains conditional. Ownership of M9 does not make M9 ready.

### Krish owns exactly 8

| Milestone | Title |
|---|---|
| M5 | Statistical / Model Scorecards |
| M11 | Promotion & Overfitting Controls |
| M12 | Shadow Broker |
| M13 | Deterministic Hard Risk |
| M14 | Broker-Neutral Execution |
| M15 | Real-World Paper / Shadow Validation |
| M16 | Official Robinhood Agentic MCP Adapter |
| M17 | Tiny-Money Canary |

Krish's chains are:

```text
M5
M11
M12 -> M13 -> M14 -> M15 -> M16 -> M17
then M18+
```

Krish's side intentionally carries the more difficult and risk-sensitive
work: statistical and model evaluation, overfitting and promotion controls,
stateful simulated brokerage, deterministic hard safety, execution
abstraction, real-world validation, official broker integration, real-capital
canary work, and bounded live autonomy.

### M18+ is operationally Krish-owned and excluded from 8/8 parity

M18+ Bounded Autonomy & Improvement belongs operationally to Krish's
execution and safety workstream. Do not count M18+ as one of the eight
bounded Krish milestones. M18+ is an open-ended operating phase, not a
comparable bounded milestone.

---

## 4. Parallelism and Contract Freeze

Architecture principle:

```text
BUILD ORDER != AUTHORIZATION ORDER
MILESTONE OWNERSHIP != STRICT SERIAL IMPLEMENTATION ORDER
```

Long-running parallel work happens across different owned milestones.

A later milestone may begin dependency-safe architecture preparation or
offline/synthetic foundations before earlier scientific authorization gates
are complete, provided all of the following hold:

1. the later milestone has exactly one owner;
2. no required upstream interface is invented speculatively;
3. required upstream contracts are frozen before dependent runtime code uses
   them;
4. earlier authorization gates remain unchanged;
5. no live behavior or promotion authority is advanced prematurely.

Runtime implementation against another workstream's interface waits for an
explicit producer-owned `kind:contract` freeze. Implementing a later
component does not authorize its operational use.

See [ADR 0013](../adr/0013-parallelize-owned-milestones-without-advancing-authorization.md).

Authorized pattern while Kanuj completes M2:

- Krish may begin M12 architecture preparation and dependency mapping.
- Krish may not implement M12 runtime against invented M2 interfaces.
- After the exact required M2/M12 interfaces are externally designed and
  frozen, Krish may begin corresponding offline/synthetic M12 foundation
  work even while Kanuj continues later research milestones.
- Krish may subsequently develop M13, M14, and offline/mockable M16
  foundation work when required predecessor contracts are frozen.

This does not authorize live trading, real capital, bypassing M1e, bypassing
M5/M11, bypassing M15, bypassing M17, strategy promotion, or paper/live
activation merely because code exists.

---

## 5. Live Work Source of Truth

Canonical truth is split:

| Kind | Source |
|---|---|
| Durable architecture and ownership | repository documentation, including this file |
| Live task state | GitHub Issues, native dependencies, labels, and PRs |
| Implementation truth | code, schemas, tests, and Git history |
| Transient issue-bound continuity | GitHub issue and PR comments |

Do not create `CURRENT.md`, `STATUS.md`, `status.json`, `task-state.yaml`, a
continuity database, or a manual GitHub issue mirror.

No issue means no product implementation.

---

## 6. Workstream Identity Bootstrap

Accepted workstream values: `kanuj` and `krish`.

Preferred setup is separate clones. After cloning:

```bash
git clone <private-repo-url>
cd drift
git config --local drift.workstream kanuj   # Kanuj clone only
# or
git config --local drift.workstream krish   # Krish clone only
```

Then run Resume. Do not copy another person's local memory, handoffs, `.env`,
chat history, or credentials. A clean clone plus GitHub access is sufficient
for normal repository work. Provider credentials are provisioned separately
only when an authorized issue requires them.

If multiple worktrees share one Git repository metadata and need different
workstream identities, do not set a shared `git config --local` value. Enable
worktree-specific configuration and set the value per worktree:

```bash
git config extensions.worktreeConfig true
git config --worktree drift.workstream kanuj
# or, in the other worktree:
git config --worktree drift.workstream krish
```

Resume workstream resolution order:

1. explicit per-clone or per-worktree `drift.workstream`;
2. current branch prefix `kanuj/` or `krish/`;
3. active GitHub issue `workstream:*` label;
4. authenticated GitHub assignment or identity if unambiguous.

If identity is still unresolved, **STOP** with `WORKSTREAM_IDENTITY_UNRESOLVED`.
Do not guess. Do not require repeated prompting.

Do not infer `krish` from an unrecognized GitHub login. Record Krish's GitHub
login in GitHub collaborator state and, once known, in an explicit accepted
issue or documentation update. Until then, `drift.workstream` or a `krish/`
branch prefix is required.

---

## 7. Issue-Driven Work Selection

Every executable issue has exactly one execution owner and must include:

- workstream owner;
- roadmap milestone;
- task/slice;
- objective;
- status;
- blockers;
- native blocked-by dependencies where available;
- consumed contracts;
- exact allowed write-set;
- explicit protected/read-only surfaces;
- acceptance criteria;
- test requirements;
- documentation impact;
- stop conditions;
- architecture-review requirement;
- expected branch/PR boundary.

Agents may read outside the write-set. They may not edit outside the write-set
merely because it is convenient. If another owner's code must change, open a
dedicated issue for that owner.

Issue-selection order after Resume:

1. `state:in-progress` issue already bound to the current branch;
2. `priority:p0`;
3. `priority:p1`;
4. `priority:p2`;
5. oldest READY unblocked issue as the deterministic tie-breaker unless the
   issue states otherwise.

Before starting:

1. issue is READY;
2. dependencies are satisfied;
3. issue is owned by this workstream;
4. no open PR already claims the issue;
5. no active issue has an overlapping write-set;
6. no conflicting contract migration is in flight.

Claim flow: change `state:ready` to `state:in-progress`, create the issue
branch, and link the branch/PR to the issue. If write-set overlap appears,
STOP and create an explicit contract or integration issue with one owner.

If no READY issue exists, do not invent implementation work. The agent may
work on an explicitly READY architecture or preparation issue, or report that
its workstream is blocked.

---

## 8. Write-Set Discipline

The issue write-set is the only editable path set for that issue.

- Read any needed contract, spec, ADR, or source file.
- Edit only paths listed in the issue write-set.
- Treat all other paths as read-only unless the issue is amended.
- Do not use `git add .`.
- Stage explicit accepted files only.

Milestone-local files belong to the milestone owner. Shared contracts belong
to the producer workstream through a `kind:contract` issue.

---

## 9. Zero Human Relay

If one workstream requires something owned by the other, the agent must not
ask a human to relay instructions, prompts, or summaries.

Required flow:

1. create a GitHub issue owned by the other workstream;
2. describe the exact required output or change;
3. include evidence and why it is required;
4. include the requested contract or interface;
5. include the allowed write-set;
6. link the blocked issue;
7. create a native blocked-by dependency where supported;
8. comment on the blocked issue;
9. move to the next READY issue in the requester's workstream if one exists.

No human relay is a valid technical dependency. All inter-workstream
requirements must survive in GitHub.

---

## 10. Cross-Workstream Contract Freeze

A contract consumed by both workstreams requires a dedicated `kind:contract`
issue. That issue has exactly one owner: the workstream that owns the
producer module or API.

The contract issue must state:

- producer milestone;
- owner;
- consuming milestones;
- existing interface;
- proposed interface or change;
- compatibility effect;
- migration impact;
- accepted schema/API;
- tests;
- allowed write-set;
- dependent issues.

Dependent issues remain blocked until the contract PR merges. After merge,
consumers code against that frozen interface. Neither workstream may modify
the shared interface opportunistically inside an unrelated PR. A later change
requires another contract issue.

Do not invent a specific M2/M12 contract in advance. M12 architecture
determines what it actually needs. Any M12 implementation requiring
M2-produced interfaces is blocked by an explicit shared-contract freeze
issue owned by Kanuj as the M2 producer.

---

## 11. Cross-Workstream Interface Request

If Krish needs something from a Kanuj-owned producer module, Krish's agent
creates:

```text
[Interface Request][Kanuj] <specific contract>
```

Required fields:

- Requester: Krish
- Owner: Kanuj
- Blocked issue: `#...`
- Existing interface
- Required behavior
- Evidence / reason
- Smallest requested contract change
- Acceptance tests
- Expected paths

Kanuj's Resume queue sees it automatically. Kanuj's agent implements it.
After merge, Krish's blocked issue becomes unblocked. The same flow applies
from Kanuj to Krish.

---

## 12. Architecture Request

Implementation agents do not silently make material architecture decisions.

If an owned issue exposes architecture ambiguity, create:

```text
[Architecture Request] <specific decision>
```

Labels: `kind:architecture`, `needs:architecture`, and
`workstream:<issue-owner>`.

Include a Decision Packet:

1. exact disputed claim;
2. repository or API evidence;
3. strongest argument for the existing architecture;
4. strongest argument against it;
5. why it matters;
6. smallest alternatives;
7. affected milestones and issues.

Mark the implementation issue blocked-by the architecture issue. Move to
another READY issue if available.

---

## 13. Branch and PR Convention

After two-workstream mode is activated, normal implementation must not push
directly to `main`.

Issue branch conventions:

```text
kanuj/<issue-number>-<short-name>
krish/<issue-number>-<short-name>
coord/<short-name>
```

One issue should normally map to one PR. Every PR must reference its issue.
Use `Closes #...` only when the PR actually satisfies the issue.

Forbidden: force pushes, history rewrites, and broad destructive resets. If a
branch falls behind, use a normal safe update or merge strategy that
preserves pushed history.

---

## 14. Documentation-Impact Policy

Every Checkpoint must answer: did this change make any canonical
documentation false or incomplete?

- If no, do not edit docs unnecessarily.
- If yes and the affected doc is inside the issue write-set, update it in the
  same PR.
- If yes and the affected doc is outside the issue write-set, create a
  dedicated `kind:docs` issue with exactly one workstream owner.

A docs issue must identify the stale document, the exact stale statement, the
source issue or PR, the required correction, and whether merge is
safety-critical.

Do not have both workstreams casually edit shared documentation at the same
time.

---

## 15. Milestone-Close Documentation Reconciliation

Before a milestone can close, its owner must reconcile documentation.

Review at minimum when applicable:

- `README.md`
- `AGENTS.md` current implementation boundary
- `docs/architecture/roadmap.md`
- `docs/architecture/overview.md`
- this file's ownership assumptions
- active plan/spec status
- relevant ADR links

Then close the parent GitHub issue and update dependency relationships so
blocked downstream issues can become READY when their remaining blockers are
satisfied.

Do not change ownership policy merely because one milestone closed.

---

## 16. Resume, Checkpoint, and Handoff

These are repository protocols, not personal skills. See
[agent-workflow.md](agent-workflow.md).

- **Resume**: locate repository root, read `AGENTS.md`, verify Git reality,
  resolve workstream identity, and select the next READY unblocked GitHub
  issue.
- **Checkpoint**: verify the slice, audit the write-set, commit explicit
  files, push the issue branch, create or update the PR, and comment on the
  GitHub issue.
- **Handoff**: primary medium is a GitHub issue comment. `docs/handoffs/` is
  only for exceptional unfinished state that cannot reasonably be preserved
  in GitHub issue or PR context.

---

## 17. Onboarding

### Krish, one-time

```bash
git clone <private-repo-url>
cd drift
git config --local drift.workstream krish
```

Run Resume. GitHub Issues for `workstream:krish` are the work queue. Do not
ask Kanuj for chat context, local files, or a prompt relay.

Until two-workstream repository files are on `main`, fetch the open
coordination PR or its branch and read `AGENTS.md`, this file, and
`agent-workflow.md` from that revision.

### Kanuj, existing clone

```bash
git config --local drift.workstream kanuj
```

Do not change a shared worktree config while another agent has an in-flight
direct-`main` slice on that same checkout. Prefer setting identity after that
slice lands, or use `--worktree` configuration if two worktrees must differ.

---

## 18. CODEOWNERS

Milestone ownership does not currently map to stable path ownership. Do not
use `CODEOWNERS` to encode milestone owners. This document and GitHub
`workstream:*` labels are the canonical owner source.
