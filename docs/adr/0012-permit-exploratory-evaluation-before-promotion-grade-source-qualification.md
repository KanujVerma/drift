# ADR 0012: Permit Exploratory Evaluation Before Promotion-Grade Source Qualification

## Status

Accepted architecture decision, 2026-09-19.
Amends sequencing in [ADR 0010](0010-qualify-real-source-rights-and-replay-before-evaluation.md).

## Context

ADR 0010 originally established that positive M1e real-source qualification and
offline replay closure must precede evaluator or backtester (M2) implementation.
That strict sequencing was architecturally sound when adopted: building an
evaluator before observing real omission, revision, licensing, and session
failure modes risked encoding brittle or unrealistic assumptions.

That uncertainty has now been substantially reduced through empirical provider
screening across three distinct vendors:
1. *algoseek*: Screened in sandbox; confirmed strong security identity and TAQ
   tick microstructure, but reference tables overwrite historical assertions
   without vintage or as-of metadata, disqualifying it as a sole historical
   decision input.
2. *Databento*: Screened on free account; confirmed strong acquisition manifests,
   checksums, and market data downloads. Documented native `pit=True` revision
   history and Security Master temporal intervals make it the leading candidate
   for promotion-grade qualification, but reference datasets require a paid
   annual subscription.
3. *Alpaca*: Screened on free Basic tier; confirmed free historical SIP trades and
   bars, rich Corporate Actions REST coverage, and point-in-time symbol mapping
   via `asof`. However, Corporate Actions mutation replay is empirically
   truncated to approximately 72 days (starting 2026-07-09), derived bars lack
   vintages, and historical trading halts are absent (HTTP 404).

These empirical investigations achieved the primary scientific objective of ADR
0010's sequencing rule: exposing real-world data limitations before designing
evaluation semantics.

However, no zero-cost provider currently satisfies all promotion-grade M1e hard
gates. The user does not wish to commit several thousand dollars annually to
paid reference data before Drift produces enough exploratory research to justify
that expense. Locking evaluator development behind paid data creates an artificial
blocker, whereas permanently weakening M1e's hard gates would destroy Drift's
falsification standards.

## Decision

1. **Two Distinct Evaluation Lanes**:
   Drift formally establishes two distinct evaluation lanes:
   - **Lane 1: Exploratory Development (`EXPLORATORY`)**:
     - *Purpose*: Implement the evaluator core, verify accounting and rebalance
       correctness, build deterministic reference baselines (M3), explore
       predictive signals, develop research tooling, conduct shadow/paper
       research, and determine whether a strategy hypothesis shows enough
       promise to justify paid validation.
     - *Input Data*: Permitted to consume free, imperfect development data. The
       current default development source is Alpaca Basic free historical data.
     - *Status*: Alpaca is explicitly NOT M1e-qualified. Known data limitations
       (e.g., truncated corporate action revision history, unversioned derived
       bars, absent halt records) must remain explicit and must never be
       silently treated as complete truth.
     - *Admissibility*: Exploratory results are strictly development evidence.
       They are admissible for hypothesis generation and relative ranking, but
       are strictly non-promotable.
   - **Lane 2: Promotion-Grade Evaluation (`PROMOTION`)**:
     - *Purpose*: Authorize model promotion, tournament advancement (M10),
       overfitting gate passage (M11), shadow broker deployment (M12), and
       tiny-money live capital allocation (M17).
     - *Input Data*: Gated strictly by positive M1e qualification. Must satisfy
       all M1e hard gates: exact rights, historical-decision suitability,
       provider assertion/revision fidelity, point-in-time availability,
       identity/lifecycle coverage, acquisition completeness, exact retained
       native bytes, durable replay rights, and offline replay closure.

2. **Absolute Non-Upgrade Rule**:
   An exploratory evaluation result can NEVER be relabeled, promoted, converted,
   or upgraded into promotion-grade evidence.
   - A strategy showing exceptional performance under exploratory evaluation
     remains strictly non-promotable.
   - No metadata flag flip, identical code run, matching date window, or later
     provider qualification can convert exploratory output into promotion
     evidence.
   - Promotion requires an entirely NEW, independent evaluation run executed
     directly against an accepted, promotion-qualified M1e dataset. Evidence
     laundering is prohibited.

3. **Single Evaluator Core**:
   Drift will implement ONE deterministic, provider-neutral evaluator engine
   serving both lanes.
   - Drift will not create a toy or separate backtester for exploratory work.
   - The evaluator operates exclusively over provider-neutral Drift contracts
     (M1b through M1d).
   - The evaluator does not consume vendor-specific API clients, JSON structures,
     or proprietary quirks. Development adapters normalize external inputs to
     standard Drift contracts and explicitly document any unmapped or missing
     dimensions.

4. **Sequencing and M1e Lifecycle**:
   - M1e Tasks 1 through 7 remain canonical, verified, and complete.
   - M1e Task 8 (promotion-grade pilot) remains open, but paid provider
     qualification is paused/deferred.
   - M2 evaluator architecture and exploratory development are authorized to
     proceed immediately.
   - The trigger to initiate paid promotion-grade qualification is an external
     economic and research decision when exploratory results justify the cost
     of rigorous falsification. No fixed return or dollar threshold is hardcoded.

## Consequences

- Evaluator (M2) and baseline (M3) engineering can proceed without premature
  vendor subscription expenses.
- M1e standards are preserved without compromise: promotion-grade evaluation
  remains strictly gated on full qualification and exact replay closure.
- Architectural divergence is prevented by committing to a single evaluator
  core rather than separate development and production engines.
- Epistemic hygiene is enforced: exploratory hypothesis generation is cleanly
  decoupled from promotion-grade falsification.

## References

- [ADR 0001: Evidence-first architecture](0001-evidence-first-architecture.md)
- [ADR 0002: Broker-neutral core](0002-broker-neutral-core.md)
- [ADR 0004: Research-production separation](0004-research-production-separation.md)
- [ADR 0010: Qualify real-source rights and replay before evaluation](0010-qualify-real-source-rights-and-replay-before-evaluation.md)
- [M1e Provider Selection State](../architecture/m1e-provider-selection.md)
