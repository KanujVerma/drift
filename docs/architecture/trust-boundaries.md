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

## Evidence Quality and Promotion Boundary (ADR 0012)

Research and evaluation evidence is partitioned into two distinct epistemic lanes:

1. **Exploratory Development Evidence (`EXPLORATORY`)**:
   - Generated using development-grade, free, or imperfect datasets (default:
     Alpaca Basic).
   - Serves evaluator engine verification, baseline establishment, signal
     exploration, and preliminary hypothesis screening.
   - Strictly non-promotable: cannot be admitted to champion/challenger
     tournaments (M10), overfitting promotion gates (M11), or live execution
     (M16+).
2. **Promotion-Grade Evidence (`PROMOTION`)**:
   - Gated strictly by positive M1e qualification across all twelve dimensions.
   - Requires verified rights, point-in-time assertion fidelity, exact retained
     native bytes, and isolated offline replay closure.

### Absolute Non-Upgrade Rule
An exploratory result can NEVER be relabeled, promoted, converted, or upgraded
into promotion-grade evidence. Promotion requires an entirely NEW, independent
evaluation run executed directly against an accepted promotion-qualified M1e
dataset. Evidence laundering is strictly prohibited.
