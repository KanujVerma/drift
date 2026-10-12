# Drift workstream ownership

GitHub Issues, native dependencies, and PRs are the live work queue. This
document owns durable workstream policy and ownership only. Do not add session
status, temporary blockers, current branch SHAs, percent complete, or an issue
status mirror here.

## Effective ownership

See [ADR 0015](../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md). The historical 8/8 allocation
and later all-Krish active allocation remain historical records. The feature
ownership below applies after the adopting coordination PR merges; existing
writers retain their files until their GitHub handoff condition is satisfied.

If README.md, the roadmap, or the architecture overview still states an
exclusive all-Krish allocation or a two-identity rule, this document and
[ADR 0015](../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
govern current feature ownership after the adopting coordination PR merges.
Those pages are updated only when no active writer reserves their paths.
An unapplied ownership edit is open coordination work, not finished
reconciliation. A historical COMPLETE status is not live trading, source
qualification, or promotion authorization.

| Workstream | Accountable feature owner | Owns | Explicit exclusions |
|---|---|---|---|
| kanuj | Kanuj | Small, offline deterministic news-event triage and its tests/docs. | No live ingestion, LLM/model hosting, portfolio significance, risk, execution, broad research or mandatory integration/review duties. |
| krish | Krish | Intelligence, event significance, strategy proposals, bounded adaptation, conventional optimizer, experimental methodology, scorecards and scientific eligibility. | No direct source-provider network implementation, accounting rewrite, broker access, risk/permission bypass. |
| matthew | Matthew | Market/news acquisition and provenance, identity/session support, evaluator/accounting, intraday/extended-hours simulation, risk, permissions and operational infrastructure. | No independent change to AI objectives, research-success definitions or statistical acceptance criteria. |

The approximate 10/45/45 workload intention is not an effort estimate. Kanuj
must remain the smallest slice. Krish and Matthew balance future unclaimed
work at feature boundaries; do not manufacture equal issue counts or silently
transfer live work. Kanuj's unavailable time must not block their fixture tests.

## Milestone stewardship and path routing

Milestone numbers still organize architecture/history, not equal units of work.
One integration steward reconciles each milestone; one feature owner executes
each issue. Historical authorship and closed issues are not rewritten.

| Steward | Existing areas |
|---|---|
| Matthew | M0-M1e platform/provenance maintenance; M2 accounting and evaluator; M12-M18+ simulation, risk, execution and operations. |
| Krish | M3 strategy definitions; M4 tracking; M5 statistics; M6-M8 research; M9 only if separately activated; M10 exploratory comparison; M11 scientific eligibility. |
| Kanuj | Bounded triage feature, outside the old count-based milestone split. |

File routing is a starting rule, never a blanket write grant:
- Kanuj: reserved new `src/drift/news_triage/` plus its specifically named tests/docs.
- Krish: `src/drift/agent/`, `loop/`, `memory/`, `baselines/`, `tracking/`,
  `scorecards/`, `tournament/`, `promotion/` and accepted research orchestration
  in `experiments/`. New intelligence code should extend those interfaces or
  use a narrowly reserved `src/drift/intelligence/` package where needed.
- Matthew: `src/drift/adapters/`, `datasets/`, `qualification/`, `markets/`,
  `evaluator/`, `ledger/`, `risk/`, `shadow/`, `execution/`, `canary/`, `autonomy/`
  and corresponding platform configuration.
- `src/drift/domain/`, scripts, integration tests, package exports and top-level
  docs are routed by the producer of the exact contract. They are not jointly
  writable. Each issue lists exact paths. New source-event types belong to
  Matthew; research proposal/experiment types to Krish; triage types to Kanuj.

A consumer change to a producer module requires the producer's issue. Same
human ownership does not remove issue boundaries or the need for a reviewed
shared contract. Every current writer reservation overrides default path
routing until the recorded release/acquisition completes.

## Active writer protection

Maintain one accountable owner and one live writer per overlapping write-set.
An owner change never silently takes an active PR away from its author.
Required handoff: source issue/PR, released paths, branch/HEAD, uncommitted state,
verification status, known defects, remaining work, successor and exact next
step. Record release and successor acquisition in GitHub. A stale timestamp,
closed laptop or absent comment is not proof of release.

Existing branches need not be renamed during migration. Link them to an issue
and record the temporary writer exception. New branches normally use
`kanuj/<issue>-<slug>`, `krish/<issue>-<slug>`, `matthew/<issue>-<slug>`, or
`coord/<slug>`. No shared human workstream is introduced.

## Workstream identity

Accepted values: `kanuj`, `krish`, `matthew`. Prefer separate clones.

```bash
git config --local drift.workstream kanuj
# OR, in Krish's separate clone:
git config --local drift.workstream krish
# OR, in Matthew's separate clone:
git config --local drift.workstream matthew
```

For linked worktrees needing different identities, use Git's worktree-specific
configuration only after ensuring it will not disturb active worktrees. Do not
set a shared local value on someone else's working clone. A single command may
use `git -c drift.workstream=<owner>` without persisting a change during setup.

Resolve identity in this order: explicit per-worktree/per-clone config, owner
branch prefix, linked issue's single workstream label, then authenticated GitHub
identity only when unambiguous. Conflicting explicit identities are errors.
Otherwise stop the affected work with WORKSTREAM_IDENTITY_UNRESOLVED.

Human/workstream identity is distinct from the GitHub token actor and model
brand. A Gemini, Cursor, Codex or Kimi agent must record its actual actor and
issue; it may not pretend to be another person's GitHub account.

Use verified GitHub logins only. `KanujVerma` and `Krish-Verma` are known account
names; Matthew's login/access must be verified through GitHub, not inferred from
his name/email. Missing account resolution does not prevent docs or labelled
issue preparation. It does prevent claiming his authenticated onboarding is done.

## Contracts, decisions and reviews

Each shared contract has one producer owner and consumer reviewers. Consumers
wait for the required accepted contract revision; they do not invent production
interfaces. Fixtures may be used only under an accepted interface and labelled
synthetic. New material architecture requires an evidence-backed Decision Packet.

Feature owners maintain local design and tests. Krish reviews research-side
consumption of platform contracts; Matthew reviews platform consumption and
scientific measurement boundaries independently. Kanuj is not a required reviewer
for unrelated work. Runtime/safety approval requires a reviewer independent of
the implementing agent and appropriate evidence, not two self-reviews.

Global coordination docs have one named writer per issue. Route later global
updates through a docs issue, not an unlimited permanent edit right. Ordinary
implementation detail inside a frozen issue is resolved by its implementation
agent; material scientific, security, schema or permission changes are escalated.

## GitHub-only communication

Open producer-owned interface requests with exact evidence/output, tests,
allowed paths and blocked consumer issue. Use native dependencies where available
and explicit text otherwise. Post Checkpoint/Handoff updates at meaningful changes.
No agent may require a person to copy a prompt to another workstream.

This is communication through a durable queue, not guaranteed real-time agent
messaging. Agents check it on Resume, before claiming/editing and at checkpoints.
Do not promise background monitoring or auto-wake without deployed automation.
No automatic reassignment of stale work is allowed.

## Onboarding and completion

A clean clone, confirmed repository access, workstream config and Resume are
sufficient. Do not copy chat history, local handoff archives, credentials or
someone else's .env. Review the [workflow](agent-workflow.md) and
[adaptive experiment start page](adaptive-experiments/README.md).

Before feature close, reconcile its specification, public contract, relevant
roadmap/overview claims and accepted decision links. Implementation, verification,
independent acceptance, source qualification and operational authorization are
separate claims. Do not close a milestone merely because its code exists.

Do not create CODEOWNERS until required identities/access are verified and the
new path boundaries are stable. CODEOWNERS is review routing, not a file lock.
