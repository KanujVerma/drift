# ADR 0006: Resolve Historical Identity and Lifecycle Facts Independently

## Status

Accepted on 2026-09-04 within the approved M1b semantic-audit scope.
Implemented and independently accepted at `11f5d4b`, with the full gate passing.

## Context and evidence

Task 3 at `1cf3afa` coupled external identifier resolution to usable lifecycle
history. Unknown suspension or last-trade timing, or an unavailable termination,
could erase a causally known mapping. Yet no termination records could permit
mapping without complete history coverage. Successful mapping therefore never
consistently proved activity. The termination resolver also returned indeterminate
for a known effective termination when its last trading instant was unknown.

The strongest argument for this approach was the approved requirement to reject
mappings outside listing lifetimes and to fail closed on unsupported chronology.
Those protections remain necessary. The strongest contrary evidence is the
separate sourced fields and resolvers: mapping identifies a listing, lifecycle
describes its state, and structural eligibility composes the required facts.
Unknown evidence in one fact does not contradict a separately evidenced fact.

Primary documentation supports the distinction, without defining Drift's policy:
[QuantConnect security identifiers](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/security-identifiers)
separates permanent identity from time-specific ticker text and requires a valid
historical mapping date. Its
[corporate-action documentation](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions)
exposes symbol changes and delistings separately.
[SEC Form 25](https://www.sec.gov/files/form25.pdf) describes removal from listing
by the effective delisting date. It does not make reconstruction of the final
trade the authority for that fact. Applying these distinctions to Drift's
uncertainty handling is an engineering decision grounded in its separate records.

## Decision

- Resolve an identifier through its own causally selected mapping and retained
  typed assignment, including namespace, venue, interval, collision, exact role,
  manifest, decision, and bundle checks.
- Check causally selected known admission and termination bounds independently.
  Preserve conservative interval containment against supplied bounded evidence.
  Missing or unknown bounds do not establish an unlimited lifetime. Unavailable
  evidence and uncertain suspension/resumption do not erase independent mapping.
- Determine termination from the selected definitely effective termination fact.
  An unknown last regular trade remains unknown and is named in result reasons.
  Supplied overlapping or reversed trade/termination bounds still fail validation.
- Preserve the complete-coverage-through-E requirement for absence of termination.
  Mapping success cannot authorize activity or structural eligibility.
- Preserve complete dependent-result replay over exact validated sources. Hash
  self-consistency alone is insufficient. Add no cache, registry, trust shortcut,
  provider, dependency, or M1c behavior.

## Compatibility and reproducibility

M0/M1a bytes, schemas, hashes, events, and replay contracts are unchanged. Existing
M1b record schemas, fixtures, and manifests are unchanged. This is an intentional
new M1b interpretation: mapping, termination, and composed lifecycle proof
implementation specifications advance to V2; coverage remains V1. Downstream
result hashes change accordingly even where the final status agrees.

The V1 termination/lifecycle specifications remain in source; their original
implementation hashes are pinned by tests. The previous mapping implementation
hash was `9d554fa6a364cdb46a7a6c4e3fd8da9eb420a58ad307fc565c3b22802c31724b`.
Full V1 executable semantics remain at `1cf3afa`. Retaining specifications is
not runtime dispatch: reproducing an old V1 outcome requires that pinned code
and its retained inputs. Current dependent replay rejects a legacy result even
when its status is still correct. No old proof or historical bundle is rewritten.

## Verification and consequence

Regression tests pair resolved mapping with indeterminate lifecycle under one
validated bundle, and independently enforce each known listing boundary.
Unknown final-trade timing no longer erases definite termination. Existing
coverage, chronology, provenance-forgery, namespace, ticker-history, correction,
and M0/M1a compatibility tests remain required. The change is a bounded semantic
correction inside M1b, not permission to begin M1c or infer tradability or returns.
