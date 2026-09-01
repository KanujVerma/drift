# Roadmap

## M0, complete

M0 provides validated immutable research objects, canonical serialization,
SHA-256 hash-chained audit events, and a transactional append-only local SQLite
ledger. It verifies and replays one consistent snapshot, while remaining a
local research-only system.

M0 landed at commit `301dc9d`. Maintenance after that commit may clarify
documentation or verification without starting M1.

M0 deliberately excludes broker access, market-data access, order placement,
trading, backtesting, strategy execution, network clients, language-model or
agent orchestration, production configuration, and production credentials.

## M1, proposed and not started

The proposed next milestone is point-in-time dataset manifests and provenance
validation. Before Drift evaluates strategies, it must establish exactly what
information existed when, which universe was observable, how revisions and
corporate actions are represented, and whether a later evaluator can detect
temporal leakage.

Likely M1 scope is limited to contracts and adversarial fixtures for:

- immutable dataset manifests and file or partition hashes;
- schema and field definitions;
- observation-time and availability-time semantics;
- point-in-time universe membership;
- revision and corporate-action policies;
- timezone and market-calendar metadata;
- source and license metadata;
- revised fundamentals, delistings, index changes, splits, dividends, missing
  bars, and stale availability timestamps.

M1 is not authorization to build a market-data platform, download live data,
evaluate strategies, adopt a research framework, connect a broker, or add
agents. Its design and implementation require separate approval.

After M1, reassess evaluator and run contracts before deterministic baselines.
External tools remain candidates and must satisfy Drift-defined contracts; see
ADR 0005 and `docs/architecture/tool-evaluation.md`.
