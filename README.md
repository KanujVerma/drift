# Drift

Drift's long-term ambition is an evidence-driven, self-improving quantitative
research and trading system. Its current implemented scope is an M0 research
evidence kernel plus M1a temporal provenance. M0 records structured research
metadata and a hash-chained audit history. M1a adds exact-byte dataset
manifests, explicit channel-scoped availability evidence, immutable fact
revisions, exact-object validation records, and per-query tri-state cutoff
decisions.

Drift is not a trading system or an equity backtester. M1a uses only synthetic
fixtures and has no real data source, historical market semantics, evaluator,
backtester, broker, strategy-execution, agent, network, order-management,
portfolio-management, production configuration, or production-credential
capability. M1b identity/universe semantics and M1c event/observation semantics
remain required before Drift can make historical US-equity evaluation claims.
`StrategyArtifact` is compact provenance metadata, not executable strategy code.

## Core philosophy

The goal is not to make an AI trade frequently. The goal is to build a system
capable of discovering whether it has repeatable predictive or
portfolio-management value without fooling itself. Research outputs remain
untrusted until a future, explicit promotion process approves them.

## Long-term architecture

Future milestones may extend the evidence kernel through this controlled flow:

```text
research -> experiments -> evidence -> challengers -> gated promotion
-> production strategy -> deterministic risk/execution
```

M0 and M1a implement only the research and temporal-provenance foundations.
They do not implement any later stage in that flow.

## Install and verify

Drift requires Python 3.14 or later and [uv](https://docs.astral.sh/uv/).

```text
uv sync --dev
uv run python scripts/init_local_db.py [path]
uv run python scripts/verify_ledger.py [path]
```

`[path]` is optional and defaults to `.drift/ledger.db`. Initialization creates
the local parent directory if needed and verifies the resulting ledger.
Verification does not create a missing database. Use the installed `uv run
python` commands above. Direct source-checkout execution through a script
shebang is not a supported invocation.

Run the maintainer checks with:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

## What the ledger guarantees

Domain objects are frozen Pydantic models. Canonical JSON normalizes supported
values before SHA-256 hashing and rejects naive datetimes and non-finite floats.
The SQLite ledger assigns a monotonic sequence, gives each event the preceding
event hash, and writes an append-only checkpoint for every event in the same
transaction. Database triggers reject ordinary updates and deletes of both
event and checkpoint rows.

Verification reads the events and checkpoints from one SQLite read snapshot.
It checks contiguous sequence numbers, the previous-hash link, recomputed event
hashes, checkpoint correspondence, and canonical raw-row storage. The
raw-row comparison matters: a database value that parses to the same logical
object but is not in the canonical stored representation is rejected. Replay
returns the exact verified snapshot in database sequence order, rather than a
later query result.

This is tamper-evident, not tamper-proof. A privileged actor who can coordinate
a database rewrite, restore checkpoints, and recompute the chain can produce a
new internally consistent ledger. M0 supplies local integrity evidence; it does
not provide external anchoring, access control, key management, or independent
attestation.

## Retention

Keep compact provenance immutable: hypotheses, specifications and runs, hashes,
parameters, metrics, dataset references, evidence lineage, failures, and any
future promotion history. Bulky artifacts, including raw datasets, temporary
logs, model checkpoints, and duplicate intermediate outputs, can expire under
explicit future retention rules. M0 records their locations and hashes but does
not expire or manage those artifacts.

See [the architecture overview](docs/architecture/overview.md),
[trust boundaries](docs/architecture/trust-boundaries.md), and the
[M1 roadmap](docs/architecture/roadmap.md).
