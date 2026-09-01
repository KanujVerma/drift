# Architecture overview

## Purpose and scope

Drift M0 is a local research evidence kernel. Its purpose is to preserve what
was proposed, tested, observed, and concluded in a form that can be checked
later. It does not make trading decisions or connect to a trading environment.

The system has four small responsibilities:

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

## Compatibility contract

A future storage adapter, including PostgreSQL, must preserve the event
envelope, canonical hashing rules, database-assigned ordering, deduplication
uniqueness, append-only behavior, checkpoint coverage, and full verification
semantics. M0 does not include that adapter.
