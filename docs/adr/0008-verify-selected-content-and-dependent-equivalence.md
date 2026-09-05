# ADR 0008: Verify Selected Content and Dependent Equivalence

## Status

Bounded M1b hardening authorized on 2026-09-04. Implementation awaits fresh
independent review and the controller's hardening commit.

## Evidence

The final review found two gaps using actual validator-produced evidence:

- An authentic decision reference admitted a future coverage record placed under
  the selected old record's hash key. The resolver checked keys, not values.
- A genuine `distinct_from` proof admitted a forged two-ID equivalence result in
  optional assignment resolution. Matching metadata did not prove entailment.

The strongest support for the previous implementations was their key-set and
query/proof/bundle checks. The contrary evidence is direct substitution without
forging any manifest, validated record, or original proof. Neither path had an
additional documented content or dependent-result check that closed the gap.

## Decision

Selected-record resolution snapshots the supplied mapping and verifies every
value before returning its mapping proxy. Parsed models and JSON use canonical
`content_hash`; exact `bytes` use SHA-256 of those bytes. Extra/missing keys and
key/value mismatches reject. Input values and their existing mutability are not
changed; integrity is checked at the resolution boundary.

Optional assignment equivalence requires all five inputs: the resolution, proof,
exact relationship records, relationship manifest, and validation decision.
Any partial group fails closed. The existing relationship dependency verifier
reconstructs both proof and complete identity resolution from the actual
assignment and relationship inputs, checks equality and query context, and only
then allows the resulting alias set to resolve multiple assignments.

The added keyword arguments are `equivalence_relationships`,
`equivalence_manifest`, and `equivalence_decision`. Ordinary assignment calls
without equivalence remain unchanged. Callers that previously supplied only an
equivalence result/proof must now supply the exact dependency evidence.

## Compatibility and validation

Genuine content-addressed values and supported equivalence still resolve. No
persisted schema, canonical hash profile, selection algorithm, M0/M1a bytes,
manifest, event envelope, or ledger behavior changes. This enforces existing
content and evidence requirements rather than reinterpreting valid old results.
Hash matching is an integrity check, not a signature or independent attestation.

Regression tests use pinned coverage fixtures and real assignment/relationship
validation. They cover model/JSON/byte substitution under genuine selected keys,
genuine equivalence, a genuine distinction proof with a forged alias set, omitted
optional inputs, and swapped dependency datasets. No dependency, external system,
registry, or M1c functionality is added.
