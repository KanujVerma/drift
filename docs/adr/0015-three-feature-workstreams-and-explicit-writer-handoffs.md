# ADR 0015: Adopt four feature-owned workstreams with protected writer handoffs

## Status

Accepted for repository adoption. The initial draft of this ADR described three
feature owners. On 2026-10-12 Kanuj accepted a fourth owner, Harsha, for the
experiment system and scientific validation. This revision is effective when the
adopting coordination pull request merges, with active-work migration completed
through the activation issues. The filename keeps the original three-workstream
slug so existing links do not churn. This is a coordination decision, not
trading or source-qualification authorization.

The earlier recommendation comment on the setup pull request remains historical.
It was not already approved on the date it was posted.

## Context

Kanuj has much less implementation availability than the other owners. The
accepted division is Kanuj on small news triage, Krish on intelligence and
bounded learning, Matthew on data, simulation, accounting, execution and risk,
and Harsha on the experiment system and scientific validation. A count-based
milestone split and the later all-Krish allocation do not fit this arrangement.
Existing active writers must not be displaced mid-change.

Krish builds the decision-maker. Matthew builds the single simulator and
enforcement boundary. Harsha builds the measurement system. Those roles stay
separate so a search process does not redefine its own success and so portfolio
arms do not silently use different account ledgers.

## Decision

1. Supersede ADR 0014's exclusive active-owner allocation and ADR 0013's rigid
   rule that a roadmap milestone may never contain explicitly delegated
   feature work. Preserve their historical record and all evidence, contract,
   and authorization safeguards not explicitly changed here.
2. One feature and one executable issue each have exactly one accountable human
   owner. One active writer has an explicitly published, non-overlapping
   write-set. No permanent shared workstream exists.
3. A historical milestone keeps one integration steward. Explicitly owned
   feature slices may cross milestone boundaries only through producer-owned
   contracts and recorded handoffs. Stewardship is not permission to overwrite
   another active issue's files.
4. The durable owner map is [workstreams.md](../architecture/workstreams.md).
   Kanuj owns only bounded offline triage. Krish owns intelligence, bounded
   learning, optimizer R and raw attempt evidence. Matthew owns source data,
   the evaluator and account ledger, execution, risk and permission enforcement.
   Harsha owns experiment orchestration, metrics and scientific eligibility
   evidence. Harsha does not own a second backtester.
5. Existing PR writers retain their current files until merge or explicit
   release/acquisition is recorded in GitHub. Proposed future ownership does
   not itself release an active writer. Absence of recent commits is not release.
6. GitHub issues, dependencies, PRs and comments are the live coordination
   system. Accepted contracts and ADRs are durable policy. Do not create a
   competing status database or require human prompt relaying.
7. Source/contracts remain producer-owned. Consumers request changes in GitHub
   and may use only clearly synthetic fixtures against accepted interfaces
   while production dependencies remain blocked.
8. Keep Kanuj off the mandatory review, integration and infrastructure critical
   path. No automatic fallback assigns large blocked work to him.
9. Do not invent effort percentages or equal issue counts. Kanuj's slice stays
   the smallest. Adjust future unclaimed work through recorded ownership changes
   without inferring a new human role.
10. Each feature owner owns its docs, tests and handoff. Cross-boundary changes
    require independent consumer review. A producer cannot self-certify its
    change as independently reviewed. That rule includes Harsha's measurement code.
11. Activation is split. A common routing gate records that the accepted policy
    is on main. Each workstream then has its own entry gate. An unresolved login
    blocks only that workstream. The tracking parent must not be the native
    blocker of another owner's eligible design task.
12. Four human contributors and five simulated accounts do not activate
    conditional M9. A usable single-agent system comes first. A 1-versus-3 study
    needs its own accepted gate. Ten runtime agents are not required.

## Alternatives and consequences

Keeping all work under Krish preserves old labels but hides the actual writers.
A universal shared owner weakens routing. Giving every feature owner unrestricted
access to the core invites incompatible changes. A second simulator under the
experiment owner would split economic truth. Explicit feature ownership,
one account ledger, producer contracts and writer handoffs preserve parallel
work. They do not guarantee conflict freedom or wake idle agents.

## References

- [Workflow](../architecture/agent-workflow.md)
- [Onboarding](../architecture/adaptive-experiments/onboarding.md)
- [Adaptive design](../architecture/adaptive-experiments/design.md)
- [Requirements crosswalk](../architecture/adaptive-experiments/requirements-crosswalk.md)
- [ADR 0013](0013-parallelize-owned-milestones-without-advancing-authorization.md)
- [ADR 0014](0014-transfer-active-drift-implementation-ownership-to-krish.md)
