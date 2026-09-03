# Drift

Drift currently implements an M0 research evidence kernel plus M1a temporal
provenance, not a trading system or equity backtester. M1a provides exact-byte
manifests, explicit channel-scoped evidence, immutable revisions, exact-object
validation records, and per-query tri-state cutoff decisions. Preserve that
boundary unless an explicitly approved milestone changes it.

## Current boundary

- M1a uses synthetic fixtures and has no real source, historical market
  semantics, evaluator, backtester, or trading capability. M1b identity/universe
  semantics and M1c event/observation semantics remain required before
  historical US-equity evaluation claims.
- Do not add broker or market-data connections, order placement, trading,
  backtesting, agent orchestration, production configuration, credentials, or
  network side effects during M0 or M1a maintenance.
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
