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

## M1a, complete

M1a provides asset-neutral temporal provenance through exact-byte manifests,
explicit channel-scoped availability evidence, immutable fact revisions,
exact-object validation records, and per-query tri-state cutoff decisions. Its
validators and adversarial fixtures fail closed when evidence is late, bounded,
unknown, channel-mismatched, mutated, or structurally incomplete.

M1a uses synthetic fixtures only. It adds no real data source, historical market
semantics, evaluator, backtester, broker, trading behavior, provider connection,
credential, or network side effect. It does not make Drift ready for equity
backtesting.

## M1b, deferred

M1b remains required before any historical US-equity evaluation claim. Its
deferred scope includes stable security and listing identity, dated identifier
mappings, point-in-time universe membership, corporate actions and delistings,
raw-versus-adjusted price meaning, exchange calendars and sessions, explicit
market-data missingness, and tradability semantics.

M1 is not complete until both M1a and M1b are complete. M1b requires its own
approved design and executable plan. Neither M1a nor the deferred M1b scope is
authorization to build a market-data platform, download live data, evaluate
strategies, adopt a research framework, connect a broker, or add agents.

After M1, reassess evaluator and run contracts before deterministic baselines.
External tools remain candidates and must satisfy Drift-defined contracts; see
ADR 0005 and `docs/architecture/tool-evaluation.md`.
