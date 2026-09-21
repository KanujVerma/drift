# ADR 0013: Parallelize Owned Milestones Without Advancing Authorization Gates

## Status

Accepted architecture decision, 2026-09-20.

The exact 8/8 Kanuj/Krish ownership allocation in this ADR is superseded by
[ADR 0014](0014-transfer-active-drift-implementation-ownership-to-krish.md).
One-milestone-one-owner, the separation of build order from authorization
order, contract freeze, and GitHub coordination remain in force unless ADR
0014 says otherwise. The historical rationale below is unchanged.

## Context

Drift's bounded roadmap from M2 through M17 contains sixteen milestone IDs.
Two humans, Kanuj and Krish, and any coding agents they use, need to work in
parallel without splitting a single milestone's implementation, inventing
cross-workstream interfaces, or treating later code availability as operational
authorization.

ADR 0012 already separates exploratory development from promotion-grade
authorization. That distinction is necessary but not sufficient for two-person
development: a later milestone can still be implemented too early against
speculative upstream contracts, or activated because code exists.

The governing constraints are:

1. One roadmap milestone has exactly one human workstream owner.
2. Parallelism is obtained across different owned milestones, not by dividing
   one milestone between Kanuj and Krish.
3. Build order is not the same as scientific or safety authorization order.
4. Milestone ownership is not a requirement that owners wait in lockstep.
5. Cross-workstream communication must survive in GitHub. No human is a valid
   technical relay.

## Decision

1. **Exactly one workstream owner per bounded milestone.**
   Milestones M2 through M17 have exactly one owner. Kanuj and Krish do not
   split implementation, tests, milestone-local contracts, or milestone
   acceptance inside one milestone. Ownership transfer is exceptional and
   requires an explicit GitHub issue plus a canonical update to
   [workstreams.md](../architecture/workstreams.md).

2. **Bounded 8/8 ownership.**
   Kanuj permanently owns M2, M3, M4, M6, M7, M8, M9, and M10.
   Krish permanently owns M5, M11, M12, M13, M14, M15, M16, and M17.
   M18+ belongs operationally to Krish's execution and safety workstream, but
   is an open-ended phase and is not one of the eight bounded Krish
   milestones.

3. **Parallelism across milestones.**
   Long-running parallel work happens on different owned milestones. Do not
   obtain parallelism by having both workstreams edit one milestone.

4. **Dependency-safe early preparation is allowed.**
   A later milestone may begin architecture preparation and dependency mapping
   before earlier scientific authorization gates are complete, provided:
   - the later milestone has exactly one owner;
   - no required upstream interface is invented speculatively;
   - required upstream contracts are frozen before dependent runtime code uses
     them;
   - earlier authorization gates remain unchanged;
   - no live behavior or promotion authority is advanced prematurely.

5. **Runtime implementation waits for contract freeze.**
   Runtime code that consumes another workstream's interface may start only
   after that interface is designed, accepted, and frozen through an explicit
   `kind:contract` GitHub issue owned by the producer workstream.

6. **Authorization order is unchanged.**
   Implementing a later component does not authorize its operational use.
   Exploratory evidence remains non-promotable. Promotion, shadow/paper
   operation, live trading, and real capital remain gated by the canonical
   roadmap and accepted evidence.

7. **Authorized current pattern.**
   While Kanuj completes M2, Krish may begin M12 architecture preparation and
   dependency mapping. That does not authorize M12 runtime implementation
   against invented M2 interfaces.
   Once the exact M2/M12 interface requirements are externally designed and
   frozen, Krish may begin the corresponding offline or synthetic M12
   foundation work even while Kanuj continues M3, M4, or later research
   milestones.
   Krish may subsequently develop M13, M14, and offline/mockable M16
   foundation work when their required predecessor contracts are frozen.

8. **Cross-workstream contracts use GitHub.**
   Shared contracts use explicit GitHub issues. GitHub native dependencies
   express blocking relationships. No human relay is required or valid.

9. **This decision does not authorize:**
   - live trading;
   - real capital;
   - bypassing M1e promotion-grade qualification;
   - bypassing M5 or M11;
   - bypassing M15;
   - bypassing M17;
   - strategy promotion;
   - paper or live operational activation merely because code exists.

## Consequences

- Two workstreams can proceed in parallel without splitting M2 or any other
  milestone.
- Krish can prepare M12 architecture while Kanuj implements M2, then implement
  offline M12 foundations after the required producer contracts freeze.
- Scientific and safety gates remain intact: code availability is not
  operational authorization.
- Agents select work from GitHub Issues and communicate through GitHub rather
  than through ChatGPT, Cursor, or human message relay.

## References

- [Workstream Ownership](../architecture/workstreams.md)
- [Project Roadmap](../architecture/roadmap.md)
- [Agent Operating Workflow](../architecture/agent-workflow.md)
- [ADR 0012: Permit exploratory evaluation before promotion-grade source qualification](0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md)
- [ADR 0002: Broker-neutral core](0002-broker-neutral-core.md)
- [ADR 0004: Research-production separation](0004-research-production-separation.md)
- [Trust Boundaries](../architecture/trust-boundaries.md)
