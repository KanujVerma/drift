# Drift

Drift implements an M0 research evidence kernel, M1a temporal provenance,
M1b historical identity/universes, M1c historical economic facts, and M1d
source observations, sessions, and normalization using synthetic local fixtures.
It is not a trading system or equity backtester. Current capability and milestone
status belong in `docs/architecture/roadmap.md`.

## Current boundary

- M1d is complete and accepted as a synthetic-fixture milestone. Its
  [execution and acceptance record](docs/superpowers/plans/2026-09-07-m1d-source-observations-sessions-normalization.md)
  records source claims, sessions, orthogonal missingness, finite M1b
  composition, M1c action mapping, source/split views, and fixture replay.
  This acceptance does not authorize provider acceptance, evaluator or
  backtester work, returns, portfolio accounting, or any production market use.
- M1e has reviewed architecture and an executable implementation plan, but
  implementation is unstarted and unauthorized. It places bounded,
  license-gated real-source qualification and offline replay closure before any
  evaluator. It authorizes no acquisition, provider adapter, dependency,
  credential, environment bundle, or runtime change.
- Do not add broker or market-data connections, order placement, trading,
  backtesting, agent orchestration, production configuration, credentials, or
  network side effects during evidence/identity maintenance.
- Preserve M0/M1a persisted contracts and M1b immutable source history. Known
  mapping or membership is not proof of listing activity or structural eligibility.
- Preserve accepted M1c fixture versions and their implementation bindings.
  Reported terms, effects and deliveries are distinct; unknown is not zero.
- `StrategyArtifact` and `StrategyReference` are immutable provenance metadata,
  not executable strategy or promotion behavior.

## Repository-wide invariants

- Research outputs are untrusted. Preserve experiment and evidence lineage,
  reproducibility, explicit versions, and immutable historical records.
- Never evaluate with future information. Data contracts must state what was
  observable and available at each point in time.
- Canonical serialization, event hashing, append-only storage, and verified
  replay are compatibility-sensitive. Read the M0 spec and relevant ADR before
  changing their contracts.
- A material architecture change requires an ADR update or new ADR. Do not add
  a dependency, framework, configuration layer, or scope expansion without a
  concrete need and current compatibility, license, security, and reproducibility
  review.

## Repository map

- Setup and commands: `README.md`
- Architecture: `docs/architecture/overview.md`
- Trust and retention: `docs/architecture/trust-boundaries.md`
- Proposed milestones: `docs/architecture/roadmap.md`
- Accepted decisions: `docs/adr/`
- Approved specs and execution plans: `docs/superpowers/`

Read the relevant canonical source before changing that area. Do not duplicate
its contents in this file.

## Task lifecycle

- Checkpoint records verified repository state. Session Handoff records only
  unfinished task context that is not already canonical. Resume verifies both
  against Git before continuing.
- Repository state wins every conflict. Never put development/session
  continuity into Drift's scientific evidence ledger.

## Verification

Before completing a material change, run `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run mypy src tests`, and `uv build`.
Inspect every forbidden-capability search match by behavior, not name alone.
