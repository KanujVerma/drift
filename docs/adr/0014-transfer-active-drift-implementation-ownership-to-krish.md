# ADR 0014: Transfer Active Drift Implementation Ownership to Krish

## Status

Accepted architecture decision, 2026-09-21.
Supersedes the milestone-owner allocation in
[ADR 0013](0013-parallelize-owned-milestones-without-advancing-authorization.md).

## Context

ADR 0013 established an exact 8/8 Kanuj/Krish milestone split so two people
could develop different milestones in parallel.

Actual execution throughput became materially asymmetric. Kanuj is stepping
away from active implementation. Krish has substantially greater current
implementation capacity. Under the old split, Krish became blocked waiting
for Kanuj-owned upstream M2 contracts. Keeping that artificial split creates
idle capacity and slows the critical path.

Historical implementation through `ca055b8011e72b0834075f67a402228df76e18da`
was completed under the Kanuj workstream. That commit closes the M2 Task 2A
external-review reconciliation. Git history remains the detailed record of
who implemented that work.

## Decision

1. All remaining active roadmap milestones M2 through M18+ are assigned to
   Krish.
2. Kanuj currently owns no active implementation milestone.
3. Historical Kanuj/Kimi/Cursor work through
   `ca055b8011e72b0834075f67a402228df76e18da` remains historically attributed.
4. One milestone still has exactly one active implementation owner.
5. GitHub Issues and PRs remain live coordination truth.
6. Milestone dependency relationships remain unchanged.
7. Authorization gates remain unchanged.
8. Architecture-review requirements remain unchanged.
9. A contract or interface freeze remains required where one milestone
   consumes another milestone's interface, even when Krish owns both.
10. Shared interfaces may not be opportunistically modified inside unrelated
    issues.
11. A future ownership transfer requires an explicit GitHub coordination
    issue and a canonical documentation update.
12. `kanuj` remains a valid workstream identity for historical provenance and
    possible future reactivation.
13. `krish` is the sole current active roadmap implementation identity.

## Consequences

- The exact 8/8 active split is no longer operative.
- Cross-human relay is no longer required for normal implementation.
- GitHub issue, dependency, contract, architecture, Checkpoint, and Handoff
  protocols remain, because multiple agents may still work concurrently for
  Krish.
- ADR 0013's ownership allocation is superseded.
- These ADR 0013 principles remain in force:
  - one milestone, one owner;
  - build order is not authorization order;
  - explicit contract freeze;
  - GitHub durable coordination;
  - no premature operational authorization.

## References

- [Workstream Ownership](../architecture/workstreams.md)
- [Project Roadmap](../architecture/roadmap.md)
- [ADR 0013: Parallelize owned milestones without advancing authorization gates](0013-parallelize-owned-milestones-without-advancing-authorization.md)
