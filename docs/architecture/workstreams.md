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
exclusive all-Krish allocation, a two-identity rule, or the earlier three-person
routing, this document and
[ADR 0015](../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
govern current feature ownership after the adopting coordination PR merges.
Those pages are updated only when no active writer reserves their paths.
An unapplied ownership edit is open coordination work, not finished
reconciliation. A historical COMPLETE status is not live trading, source
qualification, or promotion authorization. The filename of ADR 0015 keeps its
original slug; the decision text is the four-owner policy.

| Workstream | Accountable feature owner | Owns | Explicit exclusions |
|---|---|---|---|
| kanuj | Kanuj | Small offline deterministic news-event triage and its tests/docs. Normalized events become candidate alerts or explicit screening/unavailable results. | No live ingestion, LLM interpretation, accounting, execution, infrastructure rescue, or mandatory global review. |
| krish | Krish | Intelligence and bounded learning. Point-in-time context becomes grounded proposals inside approved families, plus time-eligible learning-state updates, conventional optimizer R, model replay and raw attempt/cost receipts. | No authority to redefine scientific success, authoritative account results, holdout evidence, or risk/operational permissions. No arbitrary generated-strategy execution in the MVP. |
| matthew | Matthew | Data, simulation, accounting and enforcement. Retained inputs and proposals become timing, fills, risk/approval checks, reconciled accounts and audited results. Provenance, calendars, corporate actions, intraday/extended-hours simulation, trading costs, permission enforcement, recovery and containment mechanisms. | No unilateral scientific-success definition, no second experiment-analysis engine, and no broker connection without a separate grant. |
| harsha | Harsha | Experiment system and scientific validation. Frozen studies, campaign orchestration, isolated comparison arms, complete trial records, cost attribution, metrics, uncertainty, reproducible reports and scientific eligibility evidence. | Not a generic QA helper, not the required reviewer of every PR, not a second backtester or account ledger, and not an operational approver. Cannot self-certify his own measurement changes. |

Do not invent effort percentages or equal issue counts. Kanuj's commitment stays
the smallest slice. His unavailable time must not block another owner's fixture
tests. Future unclaimed work moves only through a recorded ownership change.

## Milestone stewardship and path routing

Milestone numbers still organize architecture/history, not equal units of work.
One integration steward reconciles each milestone; one feature owner executes
each issue. Historical authorship and closed issues are not rewritten.

| Steward | Existing areas |
|---|---|
| Matthew | M0-M1e platform/provenance maintenance; M2 accounting and evaluator; M12-M18+ simulation, risk, execution, recovery and operations. |
| Krish | M3 strategy definitions used by the decision-maker; M6-M8 intelligence and bounded learning; M9 producer behavior only if that milestone is separately activated. |
| Harsha | M4 scientific trial records; M5 metrics; M10 comparison measurement; M11 scientific eligibility evidence; experiment-system orchestration. |
| Kanuj | Bounded triage feature, outside the old count-based milestone split. |

File routing is a starting rule, never a blanket write grant:
- Kanuj: reserved new `src/drift/news_triage/` plus its specifically named tests/docs.
- Krish: `src/drift/agent/`, `loop/`, `memory/`, `baselines/`, and a narrowly
  reserved `src/drift/intelligence/` package where the accepted contract needs it.
  This is the inner adaptive loop, not the study orchestrator.
- Harsha: measurement and eligibility surfaces under `scorecards/`, `tracking/`,
  `tournament/` and `promotion/` after any incumbent writer releases them.
  Experiment orchestration uses accepted `experiments/` interfaces or a path
  named by the experiment contract. Do not edit `src/drift/experiments/parallel_portfolios.py`
  while an active pull request reserves it.
- Matthew: `src/drift/adapters/`, `datasets/`, `qualification/`, `markets/`,
  `evaluator/`, `ledger/`, `risk/`, `shadow/`, `execution/`, `canary/`, `autonomy/`
  and corresponding platform configuration. One account ledger. Harsha does not
  add a second backtester.
- `src/drift/domain/`, scripts, integration tests, package exports and top-level
  docs are routed by the producer of the exact contract. They are not jointly
  writable. Each issue lists exact paths. Source-event types belong to Matthew;
  triage types to Kanuj; proposal and learning-state types to Krish; experiment
  and eligibility types to Harsha.

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
`kanuj/<issue>-<slug>`, `krish/<issue>-<slug>`, `matthew/<issue>-<slug>`,
`harsha/<issue>-<slug>`, or `coord/<slug>`. No shared human workstream is introduced.

## Workstream identity

Accepted values: `kanuj`, `krish`, `matthew`, `harsha`. Prefer separate clones.

```bash
git config --local drift.workstream kanuj
# OR, in Krish's separate clone:
git config --local drift.workstream krish
# OR, in Matthew's separate clone:
git config --local drift.workstream matthew
# OR, in Harsha's separate clone:
git config --local drift.workstream harsha
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

Stable login mappings are `KanujVerma` for kanuj, `Krish-Verma` for krish, and
`matthew-philip` for matthew. Do not infer a login from a personal name. This
page does not store Harsha's login and does not store who is currently assigned.
Read #370 and the latest activation receipt for access and assignees. A newer
receipt overrides this page. A missing login blocks only that person's entry
gate. The intended workstream, the accountable human, the execution agent and
the actual GitHub actor are four separate facts. A shared publisher login does
not prove the work belongs to Kanuj.

## Contracts, decisions and reviews

Each shared contract has one producer owner and consumer reviewers. Consumers
wait for the required accepted contract revision; they do not invent production
interfaces. Fixtures may be used only under an accepted interface and labelled
synthetic. New material architecture requires an evidence-backed Decision Packet.

Feature owners maintain local design and tests. Consumer review is specific:
Krish reviews research consumption of platform and experiment contracts; Matthew
reviews platform consumption of proposals and eligibility enforcement; Harsha
reviews scientific consumption of RESULT and attempt receipts; Kanuj reviews
only the triage envelope when he is the consumer. Nobody is the required
reviewer of every pull request. A producer cannot self-certify independent
acceptance, including Harsha's measurement code. Runtime/safety approval requires
a reviewer independent of the implementing agent.

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
