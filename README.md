# Drift

Drift's long-term ambition is an evidence-driven, self-improving quantitative
research and trading system. Its current implemented scope is an M0 research
evidence kernel, M1a temporal provenance, M1b historical identity and universes,
M1c historical economic facts, and M1d source observations, sessions, and
normalization.
M0 records structured research
metadata and a hash-chained audit history. M1a adds exact-byte dataset
manifests, explicit channel-scoped availability evidence, immutable fact
revisions, exact-object validation records, and per-query tri-state cutoff
decisions. M1b adds immutable issuer/security/listing identities, dated identifier
and primary-listing assertions, lifecycle and termination facts, historical
universe membership, and structural eligibility over exact validated evidence.
M1c adds immutable action terms, occurred/cancelled effects, reported settlements,
exact cash/share/property components, coverage and separate decision/outcome
selection with complete dependent replay.

Drift is not a trading system or an equity backtester. Its market semantics use
synthetic local fixtures. It has no real data source, evaluator,
backtester, broker, strategy-execution, agent, network, order-management,
portfolio-management, production configuration, or production-credential
capability. M1c is complete; its
[implementation and acceptance record](docs/superpowers/plans/2026-09-05-m1c-corporate-actions-economic-outcomes.md)
documents the tested boundary. M1d is complete; its
[implementation and acceptance record](docs/superpowers/plans/2026-09-07-m1d-source-observations-sessions-normalization.md)
documents immutable source claims, pinned schedule and realized-session facts,
orthogonal missingness, finite M1b composition, M1c action-to-session mapping,
cutoff-safe source/split views, and fixture-only replay across the 81-row
acceptance matrix. This establishes neither provider acceptance nor evaluator,
backtester, broker, trading, returns, portfolio, network, dependency, or
environment-closure capability.
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

M0, M1a, M1b, and M1c implement the evidence, temporal-provenance, historical
identity/universe, and economic-fact foundations.
They do not implement any later stage in that flow.

## Historical identity and candidacy

M1b distinguishes what an identifier referred to, what is known about a listing's
lifecycle, and whether the listing meets a declared historical universe policy.
A known mapping does not prove activity. Membership facts can remain known after
an association ends; structural eligibility independently requires valid identity
links, supported classification, the selected primary methodology, lifecycle
evidence, and effective membership.

Every query binds its knowledge cutoff, evaluation time, channel, policy, exact
datasets, and supporting proofs. Later corrections create a new reproducible
interpretation. Audit-only current interpretation cannot become historical
decision information. See the [architecture overview](docs/architecture/overview.md)
and [milestone record](docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md).

## Historical economic facts

M1c keeps promises, actual effects and reported deliveries separate. It selects
source revisions before comparing reports of the same evidenced occurrence,
so corrections and corroborating reports do not mint additional payouts.
Known payments can survive missing parents; delisting does not imply claim
extinction or zero proceeds. Partial evidence and unsupported economic shapes
remain explicit rather than being converted to complete results.

Decision and outcome references are not interchangeable. Exact-byte validation
must pass, supplied values are checked in a stable snapshot, and replay binds
the query, source policy, identity evidence and interpreter. Semantic-rule hashes
and the conservative installed-source fingerprint have different purposes.
Immutable fixtures retain old source bytes and code bindings instead of silently
rewriting them. These guarantees use synthetic evidence; they establish neither
real-market completeness nor valuation or backtest readiness.

## Source observations, sessions, and normalization

M1d preserves immutable source observation claims instead of treating them as
objective market truth. It retains schedule and realized-session facts separately,
keeps missingness dimensions independent, uses finite M1b composition for narrow
research-session eligibility, maps selected M1c occurred effects to proven
sessions, and materializes query-bound source-basis or exact split-normalized
views with fixture-only replay.

This is not provider acceptance or a real-market coverage claim. Drift still has
no evaluator, backtester, broker, trading, return, portfolio, network, new
dependency, or environment-closure capability.

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
