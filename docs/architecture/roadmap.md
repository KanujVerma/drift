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
Final independent M1b review had no open Critical or Important findings. All 793
tests and the full runtime gate passed at that synthetic-fixture checkpoint. The final
acceptance record is the Git commit titled `docs: complete M1b identity milestone`;
its actual hash is read from Git rather than embedded self-referentially.

## M1c, complete

M1c is Corporate Actions and Economic Outcomes. It implements immutable terms,
occurred/cancelled effects, reported settlements, exact cash/share/property
components, query-bound associations, claim and residual outcomes, coverage,
and separate decision/outcome selection and replay. It consumes M1a/M1b without
prices, sessions, derived adjustment factors, holdings or portfolio accounting.

Runtime and synthetic integration acceptance is complete through
`8f2621d20c2b010ffc105b2e1aded65acaa9c091`, including final evidence/temporal
hardening. Independent final review has no unresolved findings. All 1,093 tests
and the full repository gate pass; the focused compatibility entry points pass
366 tests. The
[completed implementation plan](../superpowers/plans/2026-09-05-m1c-corporate-actions-economic-outcomes.md)
records exact scope, reviewed corrections, immutable v1/current v2 fixture
bindings, and verification. Documentation publication uses the commit subject
`docs: complete M1c economic fact milestone`; the controller reports its actual
hash and post-commit Checkpoint result after publication.
No provider, network, broker, dependency, evaluator or trading capability was added.

## M1d, designed only and not started

M1d is Source Observations, Sessions, and Normalization. It will represent
source-defined daily observations, pinned schedule and realized-session facts,
orthogonal missingness, narrow research-session eligibility, and cutoff-safe
source/split-normalized views. Normalization joins observations with M1c actions;
preserving a source observation does not itself require an action dataset.
Total-return accounting and evaluation remain later responsibilities.

The canonical successor design is
`docs/superpowers/specs/2026-09-05-historical-economic-events-and-observations-design.md`;
the decision is recorded in ADR 0009. It supersedes the original umbrella's
combined M1c scope, not completed M1b contracts. M1c's implementation plan is now
a completed historical record. M1d has no executable plan or implementation;
any M1d planning or execution requires a new explicit authorization.
Completed/superseded M1b plans and the old M1b handoff are historical records,
not instructions to restart earlier work.

M1 is not complete until M1a, M1b, M1c, and M1d are complete. The design is not
authorization to build a market-data platform, download live data, evaluate
strategies, adopt a research framework, connect a broker, or add agents.

After M1, reassess evaluator and run contracts before deterministic baselines.
External tools remain candidates and must satisfy Drift-defined contracts; see
ADR 0005 and `docs/architecture/tool-evaluation.md`.
