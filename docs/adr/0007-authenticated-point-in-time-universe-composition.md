# ADR 0007: Authenticate Point-in-Time Universe Composition

## Status

Accepted on 2026-09-04 within the approved M1b Task 4 preflight scope.
Implemented and independently accepted at `ea35028`, with the full gate passing.

## Context and strongest alternatives

The original Task 4 sketches passed a raw source universe definition to membership
and already-validated result objects to pure structural composition. Their
strongest advantage was a small, deterministic composition layer. Their weakest
assumption was that a caller's plausible status and matching hashes proved how
those results were produced. Task 3's independent review and forged-result test
demonstrate why complete replay matters. Source definitions also carry their own
availability and correction history; treating them as timeless policies bypasses
that contract.

The original timing sketch said an upcoming addition was not current membership.
That does not establish prior exclusion when earlier history is absent. The
strongest argument for default exclusion is ordinary set membership convenience;
the stronger scientific requirement is to distinguish missing evidence from an
explicit historical removal or exclusion. Per-chain revision sequences likewise
order corrections of one event, not unrelated effective business events.

Requiring a currently active source-key assignment for every membership fact was
conservative but conflated association validity with retained identity. A listing
whose association ended can still be the subject of a known index removal.
Conversely, simply accepting a UUID would permit invented or future identities.
The bounded middle ground is causally knowable positive assignment provenance,
with activity assessed separately. This follows the immutable identity model and
[ADR 0006](0006-independent-historical-identity-and-lifecycle-facts.md), without
changing Task 2's resolver or treating `UNASSIGNED` as a business event.

These conclusions follow from repository contracts and direct adversarial tests;
no provider assumption, external integration, or new research dependency is needed.

## Decision

- Research policies are immutable content-addressed artifacts outside the source
  universe bundle. They pin identity and universe bundle hashes, avoiding a hash
  cycle. Policy creation time does not pretend historical source publication.
- Source definitions are selected from a complete, exact validated dataset using
  their own query/proof. Membership replays a supplied definition result and binds
  both its selected definition hash and resolution hash in the subject and result.
- Membership validates all retained records before subject filtering. One universe
  version has one target level. Corrections cannot change the logical event's
  universe, target, or source-event ID. Effect and timing may be corrected.
- A selected withdrawal contributes no event. Explicit membership exclusion remains
  distinct from withdrawal, assignment unassignment, and missing history.
- Known future events are upcoming only. No prior effective event means
  indeterminate; the synthetic index therefore includes a sourced prior exclusion.
  Latest events are selected by effective boundaries, not revision sequences.
  Opposing latest ties or overlaps and unknown effect at E remain indeterminate.
- Membership target authority requires genuine causally knowable retained identity
  evidence at K. Ended association intervals do not erase identity. `UNASSIGNED`
  requires earlier causal positive assignment provenance and does not itself
  create identity or removal. Withdrawn-only and future-only evidence fail closed.
- Public structural resolution accepts frozen contexts of exact records,
  manifests, decisions, and bundles. It reconstructs all component results,
  enforcing active issuer/security/listing assignments and lifecycle at E, before
  calling private pure composition. It accepts no caller classification/status
  result as trusted. Structural decision output rejects ex-post mode.

## Interfaces and persisted evidence

`ValidatedRecords[T]`, `UniverseResolutionContext`, and
`StructuralResolutionContext` are audit-side frozen containers, not registries
or persisted authorities. Persisted definition, source-definition resolution,
membership, and structural-result models are strict frozen V1 contracts.
Their authoritative declarations are in `src/drift/domain/universes.py`.

The structural result stores the full normalized query and exact component hashes.
It retains both issuer and security identity resolution hashes. When identity
cannot be established, downstream component hashes are absent, and eligibility
is indeterminate rather than fabricated. Hash consistency detects accidental
mutation; public replay supplies the scientific validation boundary.

## Compatibility, scope, and verification

M0/M1a and Tasks 1-3 persisted schemas, fixture bytes, hashes, and replay semantics
remain unchanged. The generic M1b validator adds only the two explicit universe
roles, their exact schemas/parsers, and immutable event ownership checks.
New V1 algorithm specifications identify source-definition selection, membership
selection, and retained-target provenance. No source provider, network behavior,
dependency, registry, database, price, session, return, or evaluator is added.

Tests exercise actual resolver chains, including a self-consistent forged source
definition result, complete-record omission, K/E separation, independent event
ordering, correction/withdrawal, retained versus future identity, every excluded
instrument category, missing coverage, and canonical Task 3 fixture composition.
The two new local fixture files are hash-pinned. Task 4's independent review and
commit are complete; the M1b execution record tracks final milestone acceptance.
