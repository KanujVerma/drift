# Drift workstream ownership

GitHub Issues, native dependencies, and PRs are the live work queue. This
document owns durable workstream policy and ownership only. Do not add session
status, temporary blockers, current branch SHAs, percent complete, or an issue
status mirror here.

## Effective ownership

**Owner-directed experiment transfer:** An independently reviewed and merged [ADR 0017](../adr/0017-transfer-scientific-experiment-ownership-to-kanuj.md) establishes the transfer policy, but **does not itself activate any inherited issue or grant a new experiment write claim**. For each transferred issue, Kanuj becomes its operative accountable owner only when the authenticated GitHub issue-specific migration receipt is published, `workstream:kanuj` replaces `workstream:harsha`, `KanujVerma` is assigned, and the obsolete #390 native dependency is explicitly reconciled without claiming Harsha's access was verified. Until that issue-level gate is complete, the issue stays blocked, and a new experiment task cannot rely on this policy table alone to bypass the incomplete migration. ADR 0015 remains historical; every active writer keeps their reservation until an explicit handoff.

See [ADR 0015](../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md) for historical ownership. The historical 8/8 allocation and later all-Krish active allocation are not current issue claims. The table below states the intended destination of transferred responsibilities, subject to the **per-issue migration and writer-release gate above**.

**Required-reading precedence, limited to migrated scientific issues:** After ADR 0017 is merged **and the specific issue's migration receipt exists**, ADR 0017, this ownership document, and the authenticated current issue metadata supersede **only the historical Harsha owner/workstream/activation instructions** in required reading such as `docs/architecture/adaptive-experiments/onboarding.md`, `docs/architecture/adaptive-experiments/requirements-crosswalk.md`, `docs/architecture/adaptive-experiments/stage1-roadmap.md`, and the historical design/roadmap pages. A fresh agent must not treat those stale labels alone as a new identity conflict for an already migrated issue. For an unmigrated issue, conflicting identity, absent receipts, or an unreconciled blocker still requires stopping. This precedence never overrides source qualification, scientific acceptance, accepted interfaces, safety, write reservations or trading permissions. Corrections to other required-reading files must follow their own single-writer authorized issues; this PR does not edit those paths. The filename of ADR 0015 preserves historical lineage.

| Workstream | Accountable feature owner | Owns | Explicit exclusions |
|---|---|---|---|
| kanuj | Kanuj | Offline deterministic news-event triage, plus scientific experiment methodology, frozen campaign design, isolated study orchestration, metrics, trial completeness and cost attribution, reproducible comparison reports, uncertainty and scientific eligibility evidence. | No second backtester or authoritative account ledger, trading, live ingestion, platform/risk redesign, self-certified scientific acceptance, or mandatory global PR review. |
| krish | Krish | Intelligence and bounded learning. Point-in-time context becomes grounded proposals inside approved families, plus time-eligible learning-state updates, conventional optimizer R, model replay and raw attempt/cost receipts. | No authority to redefine scientific success, authoritative account results, holdout evidence, or risk/operational permissions. No arbitrary generated-strategy execution in the MVP. |
| matthew | Matthew | Data, simulation, accounting and enforcement. Retained inputs and proposals become timing, fills, risk/approval checks, reconciled accounts and audited results. Provenance, calendars, corporate actions, intraday/extended-hours simulation, trading costs, permission enforcement, recovery and containment mechanisms. | No unilateral scientific-success definition, no second experiment-analysis engine, and no broker connection without a separate grant. |

Do not invent effort percentages or equal issue counts. Kanuj's original small triage commitment was explicitly expanded by the owner-directed experiment transfer. This is not a default duty to rescue all infrastructure or review every PR. Preserve independent scientific review and issue-specific writer permissions. Historical Harsha issues and PRs are not silently edited or reassigned without an explicit GitHub migration receipt.

## Milestone stewardship and path routing

Milestone numbers still organize architecture/history, not equal units of work.
One integration steward reconciles each milestone; one feature owner executes
each issue. Historical authorship and closed issues are not rewritten.

| Steward | Existing areas |
|---|---|
| Matthew | M0-M1e platform/provenance maintenance; M2 accounting and evaluator; M12-M18+ simulation, risk, execution, recovery and operations. |
| Krish | M3 strategy definitions used by the decision-maker; M6-M8 intelligence and bounded learning; M9 producer behavior only if that milestone is separately activated. |
| Kanuj | M4 scientific trial records; M5 metrics; M10 comparison measurement; M11 scientific eligibility evidence; experiment-system orchestration; plus bounded offline triage. |

File routing is a starting rule, never a blanket write grant:
- Kanuj: reserved new `src/drift/news_triage/` plus its specifically named tests/docs. After accepted experiment-specific contracts and writer handoffs, scientific measurement and eligibility surfaces under `scorecards/`, `tracking/`, `tournament/` and `promotion/`; experiment orchestration consumes accepted `experiments/` interfaces without duplicating the account ledger.
- Krish: `src/drift/agent/`, `loop/`, `memory/`, `baselines/`, and a narrowly
  reserved `src/drift/intelligence/` package where the accepted contract needs it.
  This is the inner adaptive loop, not the study orchestrator.
- Experiment files, including `src/drift/experiments/parallel_portfolios.py`, remain protected by any still-active writer reservation. Transferred ownership is not a blanket write grant.
- Matthew: `src/drift/adapters/`, `datasets/`, `qualification/`, `markets/`,
  `evaluator/`, `ledger/`, `risk/`, `shadow/`, `execution/`, `canary/`, `autonomy/`
  and corresponding platform configuration. One account ledger. Kanuj's
  scientific work does not add a second backtester.
- `src/drift/domain/`, scripts, integration tests, package exports and top-level
  docs are routed by the producer of the exact contract. They are not jointly
  writable. Each issue lists exact paths. Source-event types belong to Matthew;
  triage types to Kanuj; proposal and learning-state types to Krish; experiment
  and eligibility types to Kanuj after an accepted experiment contract.

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
`harsha/<issue>-<slug>` (historical only), or `coord/<slug>`. No shared human workstream is introduced.

## Workstream identity

Active values for newly claimed work: `kanuj`, `krish`, `matthew`. The historical `harsha` workstream label remains readable for old issues and branches, but is not a new active writer or authorization after the ADR 0017 handoff. Prefer separate clones.

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

Stable login mappings are `KanujVerma` for kanuj, `Krish-Verma` for krish, and
`matthew-philip` for matthew. Do not infer a login from a personal name. Harsha's
login was not verified under #370; the transfer does not pretend otherwise. #390
is a historical activation gate to supersede explicitly during issue migration.
Read the current issue's owner, assignee, labels and writer claim. The intended
workstream, accountable human, execution agent and actual GitHub actor are four
separate facts. A shared publisher login is not proof of the accountable owner.

## Contracts, decisions and reviews

Each shared contract has one producer owner and consumer reviewers. Consumers
wait for the required accepted contract revision; they do not invent production
interfaces. Fixtures may be used only under an accepted interface and labelled
synthetic. New material architecture requires an evidence-backed Decision Packet.

Feature owners maintain local design and tests. Consumer review is specific:
Krish reviews research consumption of experiment contracts and producer attempt
receipts; Matthew reviews platform/RESULT, mandate, timing and risk compatibility.
Kanuj owns scientific consumption of RESULT and attempt receipts but **cannot**
independently accept his own methodology, metrics, measurement code or results.
Each significant scientific change needs a distinct authenticated reviewer of
its exact revision and golden/adversarial evidence. Material investment advantage
or release claims also need reviewer independence from the strategy under test;
seek additional independent scientific review when the remaining owners are
conflicted. No person is the mandatory reviewer of every unrelated PR. Runtime,
safety and operational permission remain separately gated.

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
