# Drift

Drift implements an M0 research evidence kernel, M1a temporal provenance,
M1b historical identity/universes, and M1c historical economic facts using
synthetic local fixtures.
It is not a trading system or equity backtester. Current capability and milestone
status belong in `docs/architecture/roadmap.md`.

## Current boundary

- M1c is complete; its historical implementation and acceptance record is
  `docs/superpowers/plans/2026-09-05-m1c-corporate-actions-economic-outcomes.md`.
  M1d remains designed only, with no executable plan or implementation.
  Do not add prices, sessions, observations, normalization, tradability,
  portfolio accounting, evaluation, or backtesting without separate approval.
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
