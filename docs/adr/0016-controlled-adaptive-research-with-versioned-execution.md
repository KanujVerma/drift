# ADR 0016: Adopt controlled adaptive research with versioned execution boundaries

## Status

Approved for repository adoption by Kanuj on 2026-10-12. Effective upon merge
of the adopting coordination PR. The design is accepted; implementation,
source qualification, strategy eligibility and operational authorization are
separate gates.

## Decision

Adopt [D01-D17](../architecture/adaptive-experiments/decisions.md) and the
[system design](../architecture/adaptive-experiments/design.md).

The MVP adapts within approved strategy families. Event-driven proposals may
increase or reduce exposure, but deterministic mandate/risk/execution controls
remain authoritative. The target research platform supports intraday regular,
pre-market and after-hours simulations under verified capabilities. It does
not pretend the existing post-close/next-open evaluator already supports them.

A/B/C/D/R campaign controls, cost accounting, time-eligible inputs, all-trial
recording and prospective validation are required. New strategy eligibility is
not the same as allocation adaptation or live trading permission. Shared
interfaces are reviewed and versioned before runtime consumers depend on them.

Reuse the existing Drift evidence, accounting, research, risk and execution
systems. External patterns can inform narrowly reviewed adapters; do not install
another full trading framework or start a broad dependency migration.

## Boundaries retained

ADRs 0001-0012 remain applicable except for no implied expansion of authority:
exploratory artifacts never become promotion-grade by relabeling. Comparisons
inside an isolated exploratory research campaign must be named as such; they
must not call a promotion-qualified/live activation path just because both
paths use the word tournament or promotion. Any apparent conflict with an
existing promotion gate is resolved in a separate reviewed contract issue.

Historical corporate-action coverage floors, immutable replay identities,
source rights, broker isolation, and conditional M9 activation remain intact.
No live account, paid feed, provider credential, order submission, broker paper
operation or autonomous money movement is authorized by this ADR.

## Why

Separate proposal quality from data, execution and search-budget advantages.
Make fixed and adaptive decisions comparable without freezing legitimate
learning. Keep components replaceable so generated strategies can enter later
without a second evaluator. Known limitations and failed experiments are
part of the evidence, not obstacles to remove from reports.

## References

- [Decisions](../architecture/adaptive-experiments/decisions.md)
- [Design](../architecture/adaptive-experiments/design.md)
- [External evaluation](../architecture/adaptive-experiments/reuse-evaluation.md)
- [ADR 0012](0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md)
