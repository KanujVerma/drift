# Trust boundaries and retention

## Boundary map

Research inputs enter M0 as validated local objects. Their claims, metrics,
locations, and artifacts are still untrusted research output. Validation proves
that an object matches the M0 schema. It does not prove that the underlying
dataset, experiment, or claim is correct.

The SQLite file is a local integrity boundary. The ledger detects accidental or
unauthorized changes that leave inconsistent sequence, hash, checkpoint, or
canonical storage evidence. It is not a security boundary against a privileged
actor who can rewrite the database and recompute every affected value.

No production zone exists in M0. There are no broker credentials, broker
interfaces, market-data interfaces, order flows, network clients, language
models, agents, backtesting, or deployment configuration. A later promotion
control plane, if approved, must read hashed research outputs without granting
research code credentials or write access to production execution state.

## What verification establishes

Verification uses one SQLite read snapshot. It establishes that the returned
tuple has a contiguous database sequence, correct predecessor links and event
hashes, a checkpoint for every event, matching checkpoint hashes, and canonical
raw stored values. Replay returns that same verified snapshot.

This protects against a later read seeing a different state after a successful
verification. It does not establish who created an event, whether a referenced
artifact exists, whether an artifact hash was honestly supplied, or whether an
attacker has replaced an entire database with a coordinated rewrite.

## Retention policy

Retain compact provenance immutably:

- hypotheses and parent lineage;
- dataset references, versions, policies, and content hashes;
- experiment specifications, run metadata, parameters, metrics, and failures;
- evidence records, supersession lineage, audit events, and checkpoints;
- future promotion decisions and their links to the research evidence.

Potentially bulky materials may later expire under an explicit policy: raw
datasets, temporary logs, model checkpoints, and duplicated intermediate
artifacts. M0 retains their references and hashes, not the artifact bytes, and
does not currently delete or expire them. Any future expiry policy must preserve
the compact provenance needed to explain what an expired artifact represented.
