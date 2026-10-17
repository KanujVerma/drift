# ADR 0017: Transfer scientific experiment ownership to Kanuj

## Status and effective boundary

Owner-directed decision recorded October 16, 2026. **Proposed for independent
review; effective only after this coordination PR merges and the issue-specific
GitHub migration receipts are published.** This amendment supersedes only the
accountable experiment owner and dependent activation routing of ADR 0015.
Original historical authorship and evidence remain unchanged.

No Harsha GitHub identity has been verified. This change does not assume one,
impersonate Harsha, or assert he accepted/approved a task.

## Context

The accepted four-owner division placed experiment design, measurement and
scientific eligibility with Harsha, but his activation gate #390 remains
blocked on the unresolved account verification in #370. Kanuj has now
explicitly elected to take responsibility for every unfinished experiment
deliverable. This replaces the prior assumption that his contribution would
only be a small offline news-triage task. Simply relabeling the old issues or
closing #390 as if identity were verified would misstate the evidence.

## Decision

1. **Use the existing `kanuj` workstream, not a shared or simulated Harsha
   identity.** Accountable feature owner: Kanuj. Authenticated publisher:
   `KanujVerma`; every coding agent reports its actual executor and issue.
2. Assign to Kanuj the experiment and scientific validation feature previously
   stewarded by Harsha, while retaining his bounded independent news-triage
   feature. Transfer only open work, not the authorship of prior commits.
3. The scoped queue comprises #377 (preregistered experiment methodology),
   #382 (metric definitions and arithmetic), #392 (EXPERIMENT/ELIGIBILITY
   contract), #397 (release-acceptance evidence), and #383 (auditable
   end-to-end acceptance design); #391 remains a non-executable parent.
   The Harsha-only entry #390 is superseded after migration, **not** marked
   as proof of a Harsha login. #370 is historical unresolved access.
4. **Shipping order and Resume exception:** Kanuj has directed cross-owner
   unblock #392 first, then #382 metric and #397 acceptance contracts, while
   #377 methodology proceeds independently and #383 remains blocked on accepted
   producer contracts (#375, #376, #379, #380, #392), methodology and metrics.
   The normal oldest-P0-first Resume rule is not silently repealed: the scoped
   owner-directed #392-first priority exception must be recorded on the
   applicable issue during migration/claim. Priority does not permit work
   before an issue is individually transferred, READY and writer-eligible.
   Later E1-E6 implementation requires separately authorized issues, exact
   write-sets, accepted producer interfaces and independent reviews.
5. **Keep responsibilities separate.** Kanuj designs and runs the scientific
   study but does not create an alternative account ledger or simulator.
   Matthew alone produces authoritative account RESULT, timing, fills, source
   evidence, mandate and risk. Krish produces research proposals, AI/optimizer
   attempts and evidence-linked learning. Kanuj measures these from immutable
   accepted inputs, reporting incomplete and losing experiments honestly.
6. **Scientific independence:** An experiment producer cannot independently
   accept their own formulas, tests, campaign records, results or release
   claims. Krish reviews research-contract consumption; Matthew independently
   reviews RESULT/risk/execution consumption, study reconciliation and
   producer independence from the implementer. For a claimed economic or
   statistically significant advantage, obtain an independent scientific
   assessment not compromised by authorship or an evaluated strategy.
   Reviewer comments and tested revision identifiers must be recorded.
7. **Preregistration before scoring:** Freeze the primary AI-vs-R question,
   comparators, seeds, unit of analysis, chosen risk and cost rules, data
   windows, metric definitions, uncertainty methods and stopping criteria
   before looking at scored outcomes. Values not previously approved remain
   proposals, not automatic defaults. Synthetic-only test work may proceed
   in disjoint, specifically permitted issue slices without historical claims.
8. **Preserve all permission boundaries.** No new provider credentials,
   historical-source promotion, paid data, paper orders, broker connection,
   live capital, approved portfolio mandate or broad auto-trading rights.
   The M1e Task 8, M11 and operational gates stay closed.
9. **Writer handoff is granular:** Follow original issue and PR reservations.
   An explicit GitHub checkpoint identifies old owner, new accountable
   owner, actor, branch, exact allowed paths, dependency state and independent
   reviewers. Migration is not permission to overwrite another active writer.

## Rejected alternatives

- **Pretend the agent is Harsha:** invalid identity and review history.
- **Create a second experiment/account ledger:** inconsistent economic truth.
- **Reassign all platform and research code:** conflicts with Krish/Matthew
  producer ownership and technical correctness.
- **Self-approve results to save time:** destroys independent validation.
- **Close #370/#390 as successful access verification:** false evidence.
- **Freeze statistical/economic thresholds while drafting ownership:** out of
  scope for this coordination ADR.

## Migration and consequences

The current Harsha-labeled issues remain blocked until the effective
transfer receipt. The responsible coordinator will update one issue at a
time to `workstream:kanuj`, assign `KanujVerma`, preserve old ownership in
comments, and reconcile native dependencies to #390 without misrepresenting
access. #383 remains blocked by its substantive contracts, regardless of
identity migration.

### Required-reading precedence and reconciliation

A governance merge is necessary but **not sufficient** to activate a scientific
issue. Migrate each of #391, #377, #382, #392, #397 and #383 individually,
preserving exact historical ownership evidence. Its GitHub receipt must identify
the old and new accountable owners, authenticated publisher and disclosed
implementation agent, issue/branch/writer reservation, accepted governance
commit, assignee/label change, real native dependency reconciliation and
remaining substantive blockers. For an unmigrated issue, the old Harsha entry
remains blocked. Do not claim #390 or #370 was successfully authenticated.

For a transferred issue **only after its own receipt has been published**, this
ADR, `docs/architecture/workstreams.md`, and the current issue's verified
metadata take precedence over stale Harsha owner/identity/#390 routing lines
in other required-reading documents, including
`docs/architecture/adaptive-experiments/onboarding.md`,
`docs/architecture/adaptive-experiments/requirements-crosswalk.md`,
`docs/architecture/adaptive-experiments/stage1-roadmap.md`,
`docs/architecture/adaptive-experiments/design.md`, and
historical roadmaps/delivery notes. A new agent performing Resume must not
stop *solely because of these historical owner strings* when an authentic
migration receipt resolves the identity; it must still stop for any genuine
mismatch, missing receipt, unaccepted contract, blocker or writer conflict.
This precedence changes **owner attribution only**. It does not override
technical requirements, source rights, accepted D01-D17, independently
reviewed S01-S38 revisions, permissions, safety or review obligations.

### Separate-owner downstream documentation updates

`onboarding.md` and `stage1-roadmap.md` are reserved under coordination
issue [#418](https://github.com/KanujVerma/drift/issues/418) and draft
PR [#419](https://github.com/KanujVerma/drift/pull/419); their current writer
must reconcile stale Harsha routing, or explicitly release those paths first.
The required `requirements-crosswalk.md` owner corrections are routed to
[#431](https://github.com/KanujVerma/drift/issues/431) with a distinct narrow
write-set. Neither path group is editable through this governance PR.
Canonical implementation-agent prompt and handoff requirements are captured
in [#427](https://github.com/KanujVerma/drift/issues/427); they do not
automatically authorize runtime work. Old PRs and issues remain historical
evidence.

## References

- [ADR 0015](0015-three-feature-workstreams-and-explicit-writer-handoffs.md)
- [Workstreams](../architecture/workstreams.md)
- [Agent workflow](../architecture/agent-workflow.md)
- [Experiment parent #391](https://github.com/KanujVerma/drift/issues/391)
- [Harsha activation #390](https://github.com/KanujVerma/drift/issues/390)
- [Owner transfer issue #425](https://github.com/KanujVerma/drift/issues/425)
