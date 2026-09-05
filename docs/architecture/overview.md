# Architecture overview

## Purpose and scope

Drift combines a local research evidence kernel (M0), temporal provenance (M1a),
and historical identity/universe semantics (M1b). Its purpose is to preserve what
was proposed, tested, observed, and concluded in a form that can be checked
later. It does not make trading decisions or connect to a trading environment.

The M0 core has four small responsibilities:

1. Frozen domain models validate research objects such as hypotheses, dataset
   references, experiment specifications and runs, evidence, and artifact
   references.
2. Canonical JSON turns supported values into deterministic bytes for hashing.
3. SHA-256 event hashing binds a complete event to the preceding event hash.
4. A SQLite ledger appends and verifies the ordered audit history.

`StrategyArtifact` records a versioned candidate and its content hash. It is
not a strategy runtime and has no executable behavior.

## Data flow

An application creates an `AuditEventDraft` with validated research metadata.
`SQLiteLedger.append` assigns the current predecessor hash, computes the event
hash over the canonical unsigned event, stores the event, and stores the event
hash as an append-only checkpoint in one transaction. SQLite assigns the
sequence number. The sequence, not the timestamp, establishes order.

`SQLiteLedger.verified_events` opens one read transaction, loads the ordered
event rows and checkpoint rows once, and verifies the exact rows it read. It
checks contiguous sequence values, checkpoint count and sequence, checkpoint
hash equality, predecessor links, recomputed hashes, and canonical raw storage.
`replay_events` returns that one verified tuple without a second database read.

Canonical raw-row validation closes a subtle representation gap. For example,
an equivalent but noncanonical UUID, timestamp, or JSON representation is still
rejected because the bytes stored in the ledger must match the canonical output.

## Local interfaces

The only supplied runtime interfaces are local Python imports, a local SQLite
file, and two installed script invocations:

```text
uv run python scripts/init_local_db.py [path]
uv run python scripts/verify_ledger.py [path]
```

The first creates a missing local database and verifies it. The second verifies
an existing database and reports its event count without creating a missing
file. `[path]` defaults to `.drift/ledger.db`.

## Temporal and historical resolution

M1a binds exact source bytes and immutable revisions to explicit availability
evidence. It answers what was knowable through a named channel and policy by a
knowledge cutoff. M1b adds independently versioned identity, mapping,
classification, primary-role, lifecycle, termination, and universe assertions.
Their effective time answers a separate question from source availability.

Local readers verify artifact bytes before role-specific parsing. Exact schemas
and validation decisions bind the parsed records into immutable dataset bundles.
Audit-side resolvers select causal versions at the knowledge cutoff and evaluate
their effect at the requested historical time. They retain considered and selected
record hashes with query and proof bindings. Decision references expose only
selected hashes; ex-post current interpretation cannot acquire decision authority.

Issuer, security, and venue listing remain separate identities. Ticker changes
preserve the listing; reuse names a distinct identity; venue transfer can create
a new listing for the same security. Primary status is temporal and methodology
specific. Known mapping is independent of uncertain lifecycle. An absent
termination record proves neither continued activity nor termination. Asserting
continued activity requires complete lifecycle history through the evaluation time.

Source universe definitions have their own causal selection and replay. Research
policies are directly content-addressed and pin both input bundles. Membership
uses explicit effective events; an upcoming addition or a current snapshot cannot
establish historical inclusion. An ended source-key association does not erase a
retained identity or create a membership removal.

The public structural resolver reconstructs identity, classification, primary,
lifecycle, and membership outcomes from complete validated inputs before pure
composition. It accepts no caller status as trusted evidence. Supported domestic
operating-company common shares require an evidenced primary listing on XNYS,
XNAS, or XASE, definite first trade and lifecycle state, and effective membership.
Unknown or conflicting evidence remains indeterminate and fails admission.

Canonical contracts live in `src/drift/domain/`; audit-side resolvers and exact
role validation live in `src/drift/markets/`. The semantic separations and trust
boundaries are recorded in [ADR 0006](../adr/0006-independent-historical-identity-and-lifecycle-facts.md)
and [ADR 0007](../adr/0007-authenticated-point-in-time-universe-composition.md).
There is no provider connection, price/action accounting, session engine,
historical-tradability model, evaluator, or process-isolated decision runtime.
M1c economic events/outcomes and M1d observations/sessions/normalization remain
separate future milestones. M1c is planned but unimplemented; M1d is designed
only, without an executable plan. Their boundaries are recorded
in [ADR 0009](../adr/0009-separate-economic-events-and-observation-semantics.md)
and the [roadmap](roadmap.md). The roadmap points to the sole active M1c plan;
implementation requires separate authorization.

## Compatibility contract

A future storage adapter, including PostgreSQL, must preserve the event
envelope, canonical hashing rules, database-assigned ordering, deduplication
uniqueness, append-only behavior, checkpoint coverage, and full verification
semantics. M0 does not include that adapter.

M1b's manifest and validation-decision V2 contracts are additive. Existing M0/M1a
canonical bytes, hashes, schemas, event envelopes, ledger behavior, and replay
remain unchanged and covered by pinned compatibility tests. Historical M1b
interpretations also require their pinned interpreter: the Task 3 semantic
correction versions mapping/termination/lifecycle proofs rather than silently
reusing the earlier proof identity. Old records and manifests remain retained.
