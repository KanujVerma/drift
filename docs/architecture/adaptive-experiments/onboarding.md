# Onboarding: start from this repository

A fresh agent needs this repository and GitHub. It does not need a prior chat,
a setup ZIP, or a copied prompt. Say which workstream you are: `kanuj`, `krish`,
`matthew` or `harsha`. Then read the pages below and run Resume.

## Reading order

1. [AGENTS.md](../../../AGENTS.md)
2. [Decisions and rationale](decisions.md), including why each decision was made
3. [Design](design.md)
4. [Workstreams](../workstreams.md) and [ADR 0015](../../adr/0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
5. [Requirements crosswalk](requirements-crosswalk.md)
6. [Workflow](../agent-workflow.md)
7. The linked GitHub issue, its latest comments, pull request, reviews and blockers

Accepted intent lives in the decisions, design and ADRs. Live progress lives in
GitHub issues and pull requests. Implemented behavior lives in code, tests and
Git history. A draft pull request is not main. A passing check is not
architectural acceptance, source qualification or permission to trade.

## What the system is

Drift compares adaptive research with frozen controls under one simulator.
Each of A, B, C, D and R is a separate simulated account starting at USD 10,000.
They are counterfactual arms, not pooled capital. Matthew's RESULT is the
account arithmetic. Harsha analyzes that RESULT and does not replace it.
Krish proposes allocations inside approved strategy families and updates only
permitted learning state after outcomes actually exist. Kanuj turns a normalized
event into a candidate alert or an explicit non-alert. Unresolved thresholds
stay unresolved until the owning specification issue accepts them.

The seventeen decisions and their rationale are D01 through D17 in
[decisions.md](decisions.md). Do not replace them with a shorter list.

## Who owns what

| Workstream | Accountable human | Owns | Does not own |
|---|---|---|---|
| kanuj | Kanuj | Offline triage and its tests/docs | Ingestion, models, accounting, execution, mandatory global review |
| krish | Krish | Inner learning loop, proposals, optimizer R, model replay, raw attempt receipts | Scientific success criteria, the account ledger, operational permissions |
| matthew | Matthew | Data, the one simulator, accounting, execution, risk, recovery and containment mechanisms | A second analysis engine, unilateral eligibility rules |
| harsha | Harsha | Study orchestration, trial completeness, metrics, reports, scientific eligibility evidence | A second backtester, generic QA for every PR, self-certified acceptance |

Stable login mappings, not a live assignee list: `KanujVerma` is kanuj,
`Krish-Verma` is krish, and `matthew-philip` is matthew. Do not guess a login
from a personal name. Harsha's login is not stored on this page. Read #370 and
the latest activation receipt for current access and assignees. A newer receipt
overrides this page. Do not treat an old sentence here as a current blocker.

Producer contracts, all still specifications rather than implemented APIs:

| Contract | Producer | Specification issue |
|---|---|---|
| Minimal SRC envelope for triage, the only definition | Matthew | #394 |
| Broader SRC and RESULT, citing #394 rather than redefining it | Matthew | #376 |
| EXEC | Matthew | #379 |
| MANDATE/APPROVAL | Matthew | #380 |
| TRIAGE behavior and output | Kanuj | #393 |
| TRIAGE runtime | Kanuj | #381, after accepted #393 and #394 |
| CONTEXT/CANDIDATE and attempt replay | Krish | #375 |
| EXPERIMENT/ELIGIBILITY | Harsha | #392 |

## Next legitimate task

Resolve the workstream from the invocation, the issue label and the branch
prefix. If those disagree, stop with WORKSTREAM_IDENTITY_UNRESOLVED. Read the
workstream activation issue. If it is blocked, the next action is that blocker.
Do not start coding. Parents #372, #373, #374 and #391 are not executable.

Resume then selects the oldest unblocked executable issue at the highest
priority: p0, then p1, then p2. Several p0 issues may be eligible together.
That is a candidate set, not a chain. Do not invent a blocker to force a
preferred order.

| Workstream | Entry gate | Eligible executable issues once that gate is open | Resume selects |
|---|---|---|---|
| kanuj | #387 | #393 is the design issue. #381 stays blocked until accepted #393 and #394 revisions are named. | #393. Branch `kanuj/393-triage-design`. |
| krish | #388 | #375. It is not blocked by #369 or #370. | #375, the only Krish p0 design issue on this gate. Branch `krish/375-k-contract`. |
| matthew | #389 | #376, #378, #379, #380 and #394, all p0. #376 is older than #394. | #376 first. Do not write a second triage envelope in #376. #394 is the only envelope definition and remains an independent later claim. Branch for the selected issue is `matthew/<issue>-<slug>` from that issue. |
| harsha | #390 | #377, #382 and #392, all p0. #377 is the oldest. None blocks the others. | #377. Branch `harsha/377-k-method`. #390 also depends on #370. |

The common routing gate is #386. #369 is the tracker. It does not block #386,
#387, #388, #389 or #390. An open question on #370 blocks #390 only.

A parent issue such as #372, #373, #374 or #391 is not an implementation task.

## Questions that do not start work

"What do I own?" is answered from the table above and [workstreams.md](../workstreams.md).
Do not claim the issue or edit files while answering it.

If a producer contract is missing, open or reuse a producer-owned issue and
continue any other ready work that does not need that contract. Do not invent
the production types. Do not ask a person to relay the request in chat.

If another writer already holds the path, stop the overlap, leave their commits
in place, and record the handoff on the issue. A quiet branch is not a release.

If the local clone is behind or another pull request has merged, fetch and
reread the issue and the current contracts before editing. An older green check
does not cover the new head.

## Authorization answers

- Ten runtime agents: not authorized. #16 remains conditional. The sequence is
  a usable single-agent system, then a separately accepted 1-versus-3 study,
  then ten only if evidence warrants it. Keeping one agent is an acceptable result.
- Broker-connected paper trading or live capital: not authorized by this design,
  by simulation, or by a passing test.
- Missing risk thresholds, ETF lists, model budgets and statistical cutoffs:
  they stay unresolved. The owner may recommend a value with evidence. An agent
  may not accept that value by itself.
- Merging the coordination pull request: only an authorized reviewer merges it.
  Preparing the branch does not merge it, and a local draft is not main.

If no eligible issue is ready, report the blocker, the owner and the issue link.
Do not invent an implementation task to look busy.
