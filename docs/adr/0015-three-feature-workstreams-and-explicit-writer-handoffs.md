# ADR 0015: Adopt three feature-owned workstreams with protected writer handoffs

## Status

Approved for repository adoption by Kanuj on 2026-10-12. Effective upon merge
of the adopting coordination PR, with active-work migration completed through
its GitHub activation issue. This is a coordination decision, not trading
or source-qualification authorization.

## Context

Kanuj has much less implementation availability than Krish and Matthew.
The approved division is Kanuj on small news triage, Krish on intelligence and
scientific research, and Matthew on market infrastructure, execution and risk.
A count-based 8/8 milestone split and the later all-Krish allocation do not fit
this arrangement. Existing active writers must not be displaced mid-change.

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
   Kanuj owns only the bounded offline triage feature; Krish owns intelligence,
   adaptation and research evaluation; Matthew owns source/evaluator/platform,
   execution, risk and permission enforcement.
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
9. The roughly 10/45/45 capacity split is a planning intention, not measured
   effort or equal issue count. Adjust future unclaimed work through recorded
   ownership changes without changing the approved human roles by inference.
10. Each feature owner owns its docs, tests and handoff. Cross-boundary changes
    require independent consumer review. A producer cannot self-certify its
    change as independently reviewed.

## Alternatives and consequences

Keeping all work under Krish preserves old labels but hides the actual writers.
A universal shared owner weakens routing. Giving every feature owner unrestricted
access to the core invites incompatible changes. Explicit feature ownership,
producer contracts and writer handoffs preserve parallel work with clearer
accountability. They do not guarantee conflict freedom or wake idle agents.

## References

- [Workflow](../architecture/agent-workflow.md)
- [Adaptive design](../architecture/adaptive-experiments/design.md)
- [ADR 0013](0013-parallelize-owned-milestones-without-advancing-authorization.md)
- [ADR 0014](0014-transfer-active-drift-implementation-ownership-to-krish.md)
