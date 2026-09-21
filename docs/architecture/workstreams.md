# Drift Workstream Ownership

GitHub Issues, native dependencies, and PRs are the live work queue. This
document owns durable workstream policy and ownership only.

Do not treat this file as a live status tracker. Do not add current issue
numbers, temporary blockers, live branch names, percent complete, or session
status here.

---

## 1. Purpose

Drift keeps two identity values, `kanuj` and `krish`. The current active
implementation owner for every remaining roadmap milestone is Krish.
`kanuj` remains a valid historical identity and can be reactivated only by
an explicit GitHub transfer plus a canonical documentation update.

This document is the canonical durable ownership contract. It tells any
zero-context human or coding agent:

- which workstream identity it belongs to;
- which milestones that identity currently owns;
- how to select the next GitHub issue;
- which files it may modify;
- how to request a shared-contract change;
- how to stop for architecture adjudication;
- how to continue without prior chat memory.

Live task state lives only in GitHub. Implementation truth lives in code,
schemas, tests, and Git history.

---

## 2. One Milestone, One Owner

**Invariant:** one roadmap milestone has exactly one human workstream owner.

Do not split one milestone across agents to increase short-term
parallelism. Within a milestone, its owner owns:

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

There is no permanent `shared` workstream. Shared-contract work still has
exactly one execution owner.

---

## 3. Current Active Ownership

Historical implementation through
`ca055b8011e72b0834075f67a402228df76e18da` was completed under the Kanuj
workstream. Effective after that commit, all remaining active Drift
implementation ownership is assigned to Krish.

| Milestone | Active owner |
|---|---|
| M2 through M18+ | Krish |

Kanuj currently owns no active roadmap milestone. The `kanuj` identity
remains valid for historical provenance and a possible future transfer.

M9 remains conditional. Ownership does not make M9 ready and does not
satisfy dependencies or authorization gates.

M18+ remains an open-ended operating phase. It is Krish-owned, and it is
not a bounded milestone comparable to M2 through M17.

ADR 0013's exact 8/8 allocation is historical. See
[ADR 0014](../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).

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

Runtime implementation against another milestone's interface waits for an
explicit producer-owned `kind:contract` freeze, even when the same human
owns both milestones. Implementing a later component does not authorize its
operational use.

See [ADR 0013](../adr/0013-parallelize-owned-milestones-without-advancing-authorization.md)
and [ADR 0014](../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).

A single owner may still prepare a later milestone only after its required
upstream contracts are frozen. Owning M2 does not authorize M12 runtime,
paper trading, live trading, real capital, promotion, or bypassing M1e,
M5, M11, M15, or M17.

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

The current active implementation identity is `krish`. A normal active
development clone should set:

```bash
git config --local drift.workstream krish
```

A clone configured as `kanuj` selects only explicitly Kanuj-owned READY
issues. It must not steal Krish issues. If none exist, it reports that
Kanuj has no READY work. Do not reinterpret `kanuj` as `krish`.

GitHub collaborator state is the source for account permissions. Do not
guess a login that is not present there.

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

If an agent requires something outside its issue, it must not ask a human
to relay instructions, prompts, or summaries. This applies between Krish
agents, across milestone boundaries, and to any future ownership change.

Required flow:

1. create a GitHub issue owned by the execution owner of the needed change;
2. describe the exact required output or change;
3. include evidence and why it is required;
4. include the requested contract or interface;
5. include the allowed write-set;
6. link the blocked issue;
7. create a native blocked-by dependency where supported;
8. comment on the blocked issue;
9. move to the next READY issue for this identity if one exists.

No human relay is a valid technical dependency. All requirements between
agents must survive in GitHub.

---

## 10. Cross-Milestone / Shared Contract Freeze

A contract consumed by more than one milestone, or by concurrent agents,
requires a dedicated `kind:contract` issue. That issue has exactly one
owner: the workstream that owns the producer module or API.

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
consumers code against that frozen interface. No agent may modify the
shared interface opportunistically inside an unrelated PR. A later change
requires another contract issue.

Do not invent a specific M2/M12 contract in advance. M12 architecture
determines what it actually needs. Any M12 implementation requiring
M2-produced interfaces is blocked by an explicit shared-contract freeze
issue owned by the M2 producer. One human owning both milestones does not
remove that freeze.

---

## 11. Interface Request

If one issue needs a change in another milestone's producer module, the
requester creates:

```text
[Interface Request][<owner>] <specific contract>
```

Required fields:

- Requester
- Owner
- Blocked issue: `#...`
- Existing interface
- Required behavior
- Evidence / reason
- Smallest requested contract change
- Acceptance tests
- Expected paths

The owner's Resume queue sees it. After the contract PR merges, the blocked
issue can become unblocked. The same flow applies if ownership later returns
to another identity.

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

Run Resume. GitHub Issues for `workstream:krish` are the active work queue.
Do not copy Kanuj's local files, handoffs, `.env`, credentials, or chat
history.

### Kanuj, inactive clone

```bash
git config --local drift.workstream kanuj
```

A Kanuj-configured agent reports no READY implementation work unless an
explicit Kanuj-owned issue exists. Do not retarget that clone to `krish`
merely because Kanuj has stepped away from active implementation.

---

## 18. CODEOWNERS

Milestone ownership does not currently map to stable path ownership. Do not
use `CODEOWNERS` to encode milestone owners. This document and GitHub
`workstream:*` labels are the canonical owner source.
