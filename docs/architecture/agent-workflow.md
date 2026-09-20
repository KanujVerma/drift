# Agent Operating Workflow and Continuity

## Status

Active operational guide, 2026-09-20.

This document defines the operating contract, authority boundaries, verification
standards, GitHub coordination, and Git lifecycle for autonomous AI agents and
human engineers working on Drift. It is repository-native and applies equally
to Kanuj, Krish, and any compatible coding agent.

Cursor commands `/resume`, `/checkpoint`, and `/handoff` are convenience
wrappers around these protocols. They do not replace this file or root
`AGENTS.md`.

Live task state lives in GitHub Issues, native dependencies, labels, and PRs.
Durable ownership lives in [workstreams.md](workstreams.md).

---

## 1. Authority Boundaries

Drift separates architecture and scientific governance from local implementation:

### External Architecture Reviewer
The external architecture reviewer owns:
- System architecture, domain schemas, and trust boundaries;
- Scientific tradeoffs and roadmap progression;
- Provider selection, qualification rulings, and licensing decisions;
- Final interpretation of adversarial review findings;
- Defining and updating Architecture Decision Records (ADRs).

Implementation agents **must not** independently alter architecture, weaken
invariants, change product scope, or bypass licensing requirements.

### Local Implementation Agent
The local implementation agent owns:
- Repository exploration and code inspection;
- Bounded feature implementation and test-driven development (RED/GREEN);
- Debugging, regression analysis, and mechanical refactors inside established architecture;
- Running focused and integration test suites;
- Executing authenticated local provider/API probes within authorized boundaries;
- Proposing commits, maintaining Checkpoint discipline, and publishing accepted
  slices through issue branches and pull requests.

### Two Workstreams
Implementation work is owned by exactly one of two workstreams: `kanuj` or
`krish`. See [workstreams.md](workstreams.md) and
[ADR 0013](../adr/0013-parallelize-owned-milestones-without-advancing-authorization.md).

Agents do not implement another workstream's milestone. Cross-workstream
needs become GitHub issues. No human is a valid message relay.

### Evidence-Backed Disagreement Protocol
Implementation agents are expected to challenge architecture decisions when
actual repository, compiler, or provider API evidence contradicts them.
A challenge must not be a speculative opinion or silent redesign. It must be
presented as a structured Decision Packet containing:
1. **Exact disputed claim**: What specific requirement or assumption is contradicted.
2. **Repository or API evidence**: Verifiable output, tracebacks, response payloads, or schema definitions.
3. **Strongest argument for the current architecture**: The intended benefit or invariant being protected.
4. **Strongest argument against it**: Why the current architecture fails or is unworkable.
5. **Impact and significance**: Why the resolution matters to the scientific goals.
6. **Affected scope**: Which modules, tests, or milestones are impacted.

If resolving the disagreement requires a material architectural change: **STOP**.
Open a GitHub `kind:architecture` issue with the Decision Packet, block the
implementation issue on it, and do not proceed until the external architect
decides.

---

## 2. Evidence Hierarchy

When resolving technical, historical, or domain questions, agents must adhere to
this strict evidence hierarchy:

1. **Repository Reality**: Executable test behavior, domain models, schemas,
   persisted SQLite contracts, and byte-exact fixtures.
2. **Authenticated Provider Evidence**: Empirically observed API responses,
   downloaded payloads, status codes, and sandbox query traces.
3. **Primary First-Party Documentation**: Official provider manuals, API schemas,
   regulatory filings (SEC EDGAR), and exchange notices.
4. **Measured External Evidence**: Benchmarks, empirical timing measurements, and
   documented technical specifications.
5. **Credible Practitioner Analysis**: Industry engineering reports, postmortems,
   and documented operational case studies.
6. **Model Intuition**: Unsupported completions, training-set memories, or
   generic heuristics.

*Passing test counts alone or reviewer consensus alone is never semantic proof.*
Evidence must be independently verifiable.

---

## 3. Recommended Model Allocation

The following allocation is an operational recommendation to maximize speed and
rigor. Authority resides in the role boundaries, not the specific model brand:

- **External Reviewer / Architect**: Broad research, architectural synthesis,
  ADR drafting, and review of pushed commits.
- **Fast Bounded Prober**: Targeted code edits, local debugging, and
  authenticated schema probes.
- **Local Implementation Root**: Long-running implementation tasks, multi-file
  refactoring, integration testing, and repository publication.
- **Adversarial Specialist**: Deep invariant verification, temporal edge cases,
  and security boundary reviews.
- **High-Ambiguity Audit**: Whole-milestone acceptance audits and architectural
  reconciliation before major milestone transitions.

---

## 4. Workstream Identity

Accepted values: `kanuj` and `krish`. There is no third permanent workstream.

Preferred setup is a separate clone per human:

```bash
git config --local drift.workstream kanuj
# or
git config --local drift.workstream krish
```

If multiple worktrees share one repository metadata and need different
identities, use Git worktree-specific configuration rather than a shared
local value:

```bash
git config extensions.worktreeConfig true
git config --worktree drift.workstream kanuj
```

Resolution order:

1. explicit per-clone or per-worktree `drift.workstream`;
2. current branch prefix `kanuj/` or `krish/`;
3. active GitHub issue `workstream:*` label;
4. authenticated GitHub assignment or identity if unambiguous.

If identity is still unresolved: **STOP** with `WORKSTREAM_IDENTITY_UNRESOLVED`.
Do not guess. Do not prompt repeatedly.

---

## 5. Resume

Resume is a Drift protocol. Every work session must begin here, including
sessions started from Cursor, Codex, Claude, Gemini, Kimi, or a human clone
with no prior chat.

1. Determine repository root: `REPO_ROOT="$(git rev-parse --show-toplevel)"`.
2. Read root `AGENTS.md`.
3. Run `git status -sb`.
4. Run `git log -5 --oneline`.
5. Resolve workstream identity.
6. Inspect the current branch.
7. If this is an issue branch (`kanuj/<n>-...`, `krish/<n>-...`, or a branch
   linked to an issue):
   - identify the issue;
   - read the issue;
   - read the PR if one exists;
   - read native and text dependency relationships.
8. Otherwise query open GitHub issues for `workstream:<self>`.
9. Filter to READY and unblocked issues. An issue is not READY if it has
   unsatisfied `Blocked by` relationships, missing contract freezes, or a
   `state:blocked` label. Skip `state:in-progress` issues unless they are
   already bound to the current branch or this session is the recorded
   claimant. Do not steal another agent's in-progress issue.
10. Select the highest-priority READY issue.
11. Verify no open PR or active issue already owns overlapping write paths.
12. Read linked roadmap, spec, ADR, and contracts.
13. Verify the allowed write-set and treat all other paths as read-only.
14. Begin work only after those checks.

Issue-selection ordering:

1. `state:in-progress` issue already bound to the current branch;
2. `priority:p0`;
3. `priority:p1`;
4. `priority:p2`;
5. oldest READY issue as the deterministic tie-breaker unless the issue
   states otherwise.

If no READY issue exists, do not invent implementation work. The agent may
work on an explicitly READY architecture or preparation issue, or report that
its workstream is blocked.

Repository truth beats prompt claims or chat history. If GitHub and Git show
a task already completed, do not redo it.

---

## 6. Checkpoint

Checkpoint is mandatory after each accepted meaningful slice.

1. Run focused tests.
2. Resolve genuine review findings.
3. Run the full verification gate when the issue or plan requires it.
4. Perform the documentation-impact check: did this change make any canonical
   documentation false or incomplete?
   - If no, do not edit docs unnecessarily.
   - If yes and the doc is inside the issue write-set, update it in this PR.
   - If yes and the doc is outside the write-set, create a `kind:docs` issue
     owned by exactly one workstream.
5. Audit changed files against the issue write-set.
6. Do not use `git add .`.
7. Stage explicit accepted files.
8. Commit the meaningful slice.
9. Push the issue branch. Do not push directly to `main`.
10. Create or update the pull request. Reference the issue. Use `Closes #...`
    only when the PR actually satisfies the issue.
11. Comment a Checkpoint summary on the GitHub issue.
12. Update issue state (`state:in-progress`, `state:review`, or close when
    done).
13. Update dependency relationships if affected.
14. Identify the exact next action.

The GitHub issue and PR are durable cross-agent continuity.

For documentation-only or workflow tasks, do not rerun the full test suite
unless executable code changed. Still run `git diff --check` and any
doc-specific checks required by the issue.

---

## 7. Handoff

Primary handoff medium for issue-bound work is a GitHub issue comment.

A Handoff comment must include:

- workstream;
- issue;
- branch;
- current HEAD;
- exact current state;
- completed work;
- tests already run;
- remaining work;
- known failures;
- architecture questions;
- uncommitted files if any;
- exact next command or action.

Do not create a duplicate repository handoff document for routine
issue-bound work.

`docs/handoffs/` remains available only for exceptional unfinished state that
cannot reasonably be preserved in GitHub issue or PR context. Never invent a
second status database. Never write a handoff after a clean canonical
completion whose GitHub issue and Git history already capture the truth.

---

## 8. GitHub Coordination

### No product implementation without an issue

Every executable issue must name its workstream, milestone, write-set,
consumed contracts, blockers, acceptance criteria, tests, documentation
impact, stop conditions, and expected PR boundary.

### Zero human relay

If this workstream requires something owned by the other workstream, do not
say "ask Kanuj", "tell Krish", or "send this prompt to the other agent".

Instead:

1. create a GitHub issue owned by the other workstream;
2. describe the exact required output or change;
3. include evidence and why it is required;
4. include the requested contract or interface;
5. include the allowed write-set;
6. link the blocked issue;
7. create a native blocked-by dependency where supported;
8. comment on the blocked issue;
9. move to the next READY issue in this workstream if one exists.

### Contract freeze

A contract consumed by both workstreams requires a `kind:contract` issue owned
by the producer. Dependent issues remain blocked until that contract PR
merges. Do not modify a frozen shared interface inside an unrelated PR.

### Interface request

Use:

```text
[Interface Request][<owner-workstream>] <specific contract>
```

Include requester, owner, blocked issue, existing interface, required
behavior, evidence, smallest requested change, acceptance tests, and expected
paths.

### Architecture request

Use:

```text
[Architecture Request] <specific decision>
```

Labels: `kind:architecture`, `needs:architecture`, and the issue owner's
workstream. Include the Decision Packet. Block the implementation issue on
the architecture issue.

### Claiming an issue

Before starting, verify the issue is READY, owned by this workstream,
unblocked, not already claimed by an open PR, and free of write-set overlap.
Then move `state:ready` to `state:in-progress`, create the issue branch, and
link the PR.

If write-set overlap appears, STOP. Create an explicit contract or
integration issue with one owner.

### Milestone close

The milestone owner performs documentation reconciliation before the
milestone can close, then closes the parent issue and updates downstream
dependencies. See [workstreams.md](workstreams.md).

---

## 9. Git and Remote Review Workflow

After two-workstream mode is active, normal implementation must not push
directly to `main`.

### Branch names

```text
kanuj/<issue-number>-<short-name>
krish/<issue-number>-<short-name>
coord/<short-name>
```

### Normal accepted slice

```text
Resume
  -> local edit/test loop inside issue write-set
  -> focused review
  -> accepted meaningful commit
  -> Checkpoint
  -> push issue branch
  -> create or update pull request
  -> GitHub issue comment
```

One issue should normally map to one PR. Do not push microcommits for every
individual edit. Push when a verified, self-contained slice is accepted.

### Architecture or contract review

If a proposed change is substantial, complex, or requires external review
before landing on `main`:
1. Keep the work on the issue branch and open or update the PR.
2. Label `needs:architecture` when architecture adjudication is required.
3. **STOP** and await external architecture review.
4. Merge only after explicit acceptance and satisfied CI or review gates.

### Forbidden Git actions

The following operations are strictly forbidden on Drift repositories:
- `git reset --hard` (unless explicitly instructed on a temporary unpushed
  branch);
- Broad destructive resets (`git clean -fd`, `git restore .`);
- Force pushes (`git push --force` or `git push -f`);
- Rewriting pushed historical commits.

If a branch falls behind, use a normal safe update or merge strategy that
preserves pushed history.

---

## 10. Secret and Credential Handling

Drift enforces strict boundaries regarding sensitive files:
- All credentials, API keys, private tokens, and environment configurations must
  reside in `.env` or external environment variables outside Git.
- `.env` must remain strictly ignored in `.gitignore` and have restricted file
  permissions (`0600`).
- Agents must **never** print `.env`, `cat` secrets into command output, display
  API keys in transcripts or reports, or commit secrets to Git.
- Real provider data payloads, confidential contracts, or private storage paths
  must never be tracked in Git.
- Before pushing to any remote, agents must perform a mandatory pre-push secret
  audit.
- Do not copy another workstream's credentials. Provider credentials are
  provisioned only when an authorized issue requires them.
