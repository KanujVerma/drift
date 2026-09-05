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

## M1b, complete

M1b is Historical Security Identity and Universes. Its implemented scope is stable
issuer, security, and listing identity; correctable identity assertions; dated
external-identifier and primary-listing mappings; listing lifecycle and
termination state; historical universe definitions/membership; and structural
eligibility. M1b contains no price, corporate-action accounting, calendar, bar,
or evaluator behavior.

Runtime implementation is independently accepted through `dc1537f`, including
Task 4 at `ea35028`, the semantic correction at `11f5d4b`, and final selected-value
and equivalence-replay hardening. The execution and verification record is
`docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md`.
Final independent review has no open Critical or Important findings. All 793
tests and the full runtime gate pass using synthetic local fixtures. The final
acceptance record is the Git commit titled `docs: complete M1b identity milestone`;
its actual hash is read from Git rather than embedded self-referentially.

## M1c, design proposed and not started

M1c is Market Events and Observation Semantics. It depends on validated M1b
identities and is proposed to cover versioned corporate actions, terminal
economic outcomes, source/raw daily observations, cutoff-aware normalization,
decision-versus-outcome roles, pinned session schedules, typed missingness, and
historical-tradability results.

The umbrella design is
`docs/superpowers/specs/2026-09-02-m1b-m1c-historical-equity-semantics-design.md`.
It is approved as M1b planning input. No executable M1c implementation plan
exists, and M1c has not started.

M1 is not complete until M1a, M1b, and M1c are complete. The design is not
authorization to build a market-data platform, download live data, evaluate
strategies, adopt a research framework, connect a broker, or add agents.

After M1, reassess evaluator and run contracts before deterministic baselines.
External tools remain candidates and must satisfy Drift-defined contracts; see
ADR 0005 and `docs/architecture/tool-evaluation.md`.
