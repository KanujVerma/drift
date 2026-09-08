# ADR 0009: Separate Economic Events and Observation Semantics

## Status

Independently reviewed design decision, 2026-09-05. M1c is implemented and
accepted in the [completed M1c execution record](../superpowers/plans/2026-09-05-m1c-corporate-actions-economic-outcomes.md).
M1d has a [reviewed executable plan](../superpowers/plans/2026-09-07-m1d-source-observations-sessions-normalization.md)
as of 2026-09-07 and remains unimplemented. Execution requires separate authorization.
The canonical design, evidence, support matrix, adversarial requirements, and
review record are in the
[historical economic events and observations specification](../superpowers/specs/2026-09-05-historical-economic-events-and-observations-design.md).
This decision supersedes the original umbrella's combined M1c sketches. It does
not reopen completed M1b at `14bad1733222758ee3836568a10a90f2a16aeac3`.

## Context and alternatives

One combined milestone makes the normalization join testable immediately, but
couples event/claim evidence with source-specific observation and session
interpretation. Separate typed layers can each be falsified with synthetic
fixtures. A generic market-event stream would still require these typed
contracts and adds dispatch/schema machinery without a present consumer.

Repository evidence matters: M1b distinguishes security identity from listing
termination, and ADRs 0006 through 0008 require independent facts, exact dependent
replay, and selected-value integrity. M1b's query purposes and proof algorithm are
closed persisted contracts, not an extensible market-fact authorization API.

Primary evidence supports the separation: the SEC describes equity claims that
continue after exchange delisting; Nasdaq publishes distinct payment, ex-date,
and due-bill dates; its feed specification assigns different inclusion rules to
high/low, last sale, and volume. These facts do not prescribe Drift's milestone
names, but invalidate several simplifying assumptions. Exact sources and the
strongest arguments on both sides are retained in the specification.

## Decision

- M1c owns source-reported action terms, occurrence/entitlement/settlement facts,
  corrections, fixed cash/share consideration, claim-level economic outcomes,
  coverage, and purpose-bound causal selection. No prices or calendar engine.
- M1d owns source observations, schedule and realized-session artifacts,
  orthogonal missingness, narrow research-session eligibility, and explicitly
  derived source/split-normalized views. Its integration gate joins M1c action
  facts with observations and pinned sessions. Source observations can be
  preserved independently; faithful storage alone is not normalization readiness.
- Economic outcomes attach to security claims/actions. Listing terminations
  are optional verified context, never universal proof of extinguishment or zero
  proceeds. Known, partial, and unknown outcomes remain distinct.
- Preserve independently sourced payments when prior terms/effect associations
  are unresolved. A source report is not necessarily a distinct payout. Initial
  composition binds non-overlapping reporting authority by fact kind and
  occurrence scope; unresolved overlap blocks composition instead of summing
  corroborating reports. No generic event matcher is introduced.
- Simple mandatory fixed cash/share events, including basic spinoffs and
  conversions, belong in first fact support. Complex elections, contingent
  property, or unresolved valuation remain explicitly unsupported for complete
  economic evaluation. Out-of-scope property receipts are evidence, not an
  expanded investable universe. Future unsupported events cannot retroactively
  delete historical candidates.
- Use additive market query/proof/reference families. Preserve M0/M1a bytes,
  M1b wire contracts, its closed role/mode pairing, and versioned interpreter
  behavior. Decision and outcome references are not interchangeable. Immutable
  models and hashes provide integrity, not process isolation or authentication.
- Own scientific contracts in Drift; evaluate external libraries behind those
  contracts later under ADR 0005. A calendar producer is not historical authority.
  Retain source claims that conflict with schedules, but deny their unqualified
  use rather than rewriting or dropping them.
- Before experiments, bind data, semantics, code, environment, and generated
  artifact bytes with retrievable replay artifacts. Git alone and a mutable
  environment are insufficient. No replay infrastructure is built in this task.

## Consequences and boundaries

The M1c plan refines source associations into query-neutral persisted claims and
query-bound resolved references. It also uses finite-cutoff M1a selection for
M1c identity dependencies: existing M1b `current_interpretation` intentionally
selects the current retained revision and is not a finite-V selector. Neither
refinement changes M1b source models, query modes, algorithms, or hashes.

The split adds an explicit M1d composition review. It does not establish that
every conceivable action can be priced, nor promise real-data completeness.
Total-return accounting, holding conversion, imputation, and execution remain
outside both milestones. Missing facts block dependent claims, not independent
identity or historical universe evidence.

M1c synthetic implementation and acceptance are recorded in the linked plan.
Real provider semantics, historical coverage, licensing, and full schedule
validation remain later acceptance gates, not reasons to block provider-neutral
fact contracts. The M1d plan refines per-field source methods, independent realized
sessions, exact TZif provenance, orthogonal missingness, finite-cutoff M1b reuse,
and M1c action/session mapping without changing older contracts. It retains one
milestone with a mandatory joined normalization gate and explicit pinned-code
legacy replay. These are planning decisions, not implementation acceptance. The original
design decision itself added no runtime. M1c implementation added no dependency,
provider, broker, credential, agent functionality, or trading capability.
