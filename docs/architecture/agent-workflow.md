# Drift agent workflow and continuity

This protocol applies to Kanuj, Krish, Matthew and compatible coding agents.
AGENTS.md is the universal bootstrap. Cursor commands are thin wrappers.
GitHub is the live task/decision queue, not a claim that agents run continuously.

## Authority and evidence

Accountable humans approve scope and permissions. Design owners and independent
architecture reviewers resolve material scientific, security, contract and
provider questions through GitHub. Implementation agents implement explicit
accepted slices, test, debug and resolve local mechanical details. They may
challenge architecture with evidence; they may not silently redefine it.

Existing code/tests/persisted contracts establish implemented behavior, not
permission to preserve a demonstrated defect. Accepted requirements establish
intended behavior. When they disagree, record the discrepancy and use a scoped
fix/decision process. Do not change fixture hashes to hide it. Prefer actual
repository/provider evidence and primary documentation over inference. Tests,
hashes and agreement among agents do not authenticate source origin by themselves.

Architecture requests include: disputed claim, exact source/trace/API evidence,
strongest case for and against the current rule, minimal alternatives, impact,
proposed write-set, producer owner, consumer reviewers and affected blockers.
A material unresolved change blocks only dependent work. No silent new strategy,
model, provider, risk threshold, permission, schema or source-grade default.

## Resume

1. Locate `REPO_ROOT` with `git rev-parse --show-toplevel`; read AGENTS.md.
2. Read Git reality: `git status -sb`, `git log -5 --oneline`, current branch,
   tracking refs and relevant worktrees. Do not stash/reset/clean another tree.
3. Resolve workstream per [workstreams.md](workstreams.md). Do not change shared
   clone config just to resolve identity. Record actual GitHub actor separately.
4. If the three-person transition is not activated, locate the open ACTIVATE
   issue by its bootstrap marker. Its designated owner may reconcile its
   blocked state only after the required setup PR is actually merged and
   the activation preconditions are satisfied. Do not activate feature work
   from a branch-local draft. Then read the linked issue, its latest comments, related PR/reviews/checks and
   native/text blockers. If no linked work exists, search the workstream queue.
5. Reconcile actual completion evidence. Do not redo merged work because a stale
   label or handoff says it is pending. Do not infer acceptance from an old CI run.
6. Select an already claimed issue bound to this branch, otherwise the highest
   priority READY/unblocked issue (p0, p1, p2; oldest as tie-breaker).
7. Read accepted scope, applicable decisions, exact contracts, allowed paths and
   protected surfaces. Verify no other active PR/claim overlaps the write-set.
8. Confirm no unresolved source grade, contract, setup activation or permission
   gate blocks the proposed operation. Design readiness is not runtime readiness.
9. Claim the issue in GitHub before editing and reread the claim/state. State the
   intended branch, exact files, base SHA and goal. This is a coordination
   protocol, not an atomic distributed lock. If concurrent claims appear, stop
   the overlapping slice and reconcile through a producer-owned issue.
10. Open an early draft PR once meaningful reviewable changes exist. Consumers
    can read the draft, but it is not a released interface.

If all work is blocked, report specific blockers in GitHub and the handoff.
Do not invent tasks or ask a human to relay instructions. Account identity,
source spending and authorization still require an actual authorized decision.

## During work

Refresh relevant GitHub issues before editing a shared boundary and after a
checkpoint. Post progress when work is claimed, scope changes, a decision is
needed, a verified slice is published, a blocker appears or the agent stops.
Do not publish a heartbeat for every tool call or pretend local changes are
visible on GitHub. A long-running command can have an honest pending status.
Do not repeatedly rerun expensive suites just to generate updates.

Keep one writer per write-set, including subagents. Subagents are read-only by
default; any implementation delegation requires disjoint named paths, a task
boundary and a single integration writer. Never run two bootstrap agents.

Use focused RED/GREEN tests before full verification. Do not change a test's
expected result merely to make new behavior pass. Separate simulation validity,
financial performance and operational safety. A losing valid backtest is valid;
an incomplete profitable-looking backtest is not a successful experiment.

## Checkpoint

1. Finish or explicitly classify the current slice. Run focused tests and review
   genuine findings. Run the full canonical gate when the issue requires it.
2. Ask whether canonical documentation became false or incomplete. Update docs
   in the issue's write-set in the same PR; otherwise file a single-owner docs
   issue naming exact stale claims and whether correction is a merge blocker.
3. Audit all changed/untracked files against the write-set. Exclude private data,
   credentials, logs, temporary scripts and unrelated changes.
4. Stage explicit paths, commit meaningful changes, push normally and update the
   existing draft PR. No `git add .`, force-push, history rewrite or main push.
5. Post a GitHub Checkpoint with the exact template below. Record CI by head SHA,
   run ID and completed result; pending/cancelled/failed are not passed.
6. Update state and blockers from verified evidence. Closing a producer issue
   does not make its consumer READY unless the required contract actually
   merged and every remaining blocker is satisfied.
7. Before moving to review/complete, refresh remote state and disclose relevant
   base changes. Use history-preserving merges, not rebase of published commits.

Template:

```text
Workstream / accountable owner:
Execution agent and actual GitHub actor:
Issue / linked PR / branch / base SHA / HEAD:
State: in-progress | blocked | review | completed
Exact current objective:
Paths reserved / changed / released:
Completed and verified:
Focused tests (command, interpreter, result):
Full CI (exact SHA, run ID, completed result or pending):
Design/contract versions and decision evidence:
Known failures and limitations:
Documentation impact and linked correction issue:
Native/text blockers and affected consumers:
Uncommitted files, if any:
Exact next action:
```

## Handoff and writer release

Use an issue comment as the primary handoff. Include the Checkpoint fields and
explicitly identify released files, pending changes, successor owner and the
conditions for acquisition. The successor must record acquisition before edits.
Do not seize work merely because an agent went quiet. Do not delete old comments
or rewrite historical authorship.

Routine issue-bound continuity does not need a separate handoff document.
`docs/handoffs/` is only for exceptional state that cannot reasonably live in
GitHub. Never expose private artifacts just to make a handoff portable; retain
safe references and limitations.

## Cross-workstream requests

Create an issue titled `[Interface Request][<producer>] <specific output>`.
Include requester, producer, affected issue, existing interface, required
behavior, evidence, smallest change, exact proposed paths, tests, compatibility
and blockers. Native issue dependencies are preferred; where unsupported use
`Blocked by #N`, link both directions and retain `state:blocked`.

PRs are not necessarily valid native dependency objects. Use the producer's
issue as the blocker and explicitly require its contract PR to be merged.
Do not claim a GitHub relationship was created unless readback verifies it.
Do not infer runtime data readiness from a docs-only contract merge.

No person is a technical message relay. A source producer can finish its work
and another agent can discover it at Resume. Idle agents do not automatically
wake. Automated scheduling or notifications are a separate capability, not an
assumption in this protocol.

## Documentation and status discipline

Accepted decisions/rationale live in ADRs and feature specifications. Draft
proposals live in clearly labelled draft docs or issue comments. GitHub issues
and PRs own live status. Code/tests/history own implemented behavior. In a
status claim distinguish: implemented, independently reviewed, verified at a
specific revision, source-qualified, and operationally authorized.

Do not create CURRENT.md, STATUS.md, a continuity database or a hand-edited
status table mirroring every issue. An existing stale completion ledger may be
marked historical and linked to live queries without deleting its audit history.
Every feature owner updates its own documentation. A global-doc edit requires a
single-owner docs issue with a non-overlapping write-set.

Before feature/milestone closure, reconcile its design, relevant roadmap/overview
claims, public contracts, limitations and accepted ADR links. Never advertise
live trading, source qualification or profitable edge just because code merged.

## Verification and safe publication

Use the interpreter pinned in `.python-version` and the existing lockfile.
A fallback interpreter result is diagnostic and must be labelled noncanonical.
Do not change the pin/lockfile or replay baseline in order to pass verification.
Canonical code gate, subject to issue-specific additions:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

Also check the correct base-to-head diff and exact-head hosted checks. A
superseded green run is not evidence for a newer head. Do not alter required
check names or main rulesets during feature work.

For documentation-only coordination work, validate Markdown links, YAML,
frontmatter, allowed paths, whitespace and forbidden em dashes; do not launch
full pytest solely for docs. Existing hosted CI may still run as configured.
Do not disable it. Distinguish local docs checks from a pending full CI result.

No product agent merges autonomously unless that exact action is separately
approved. Draft PRs remain drafts pending independent acceptance. No broker
connection, order, provider purchase or credential access is implied by Resume.
