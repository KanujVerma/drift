# Drift

Drift is an evidence-driven, self-improving quantitative research and trading
system. Its core objective is to discover whether a strategy has repeatable
predictive and risk-adjusted value without fooling itself through lookahead
bias, survivorship bias, or ungrounded simulation assumptions.

Research outputs in Drift remain strictly untrusted until validated through a
tamper-evident, append-only evidence history and explicit promotion gates.

> **Current Boundary**: Drift is not yet an equity backtester or a live trading bot.
> Completed milestones (M0 through M1d) provide a tamper-evident, append-only research evidence
> kernel, temporal provenance, historical identity/universes, economic action
> terms, and normalized observations using synthetic local fixtures. M1e
> (real-source qualification and offline replay closure) is currently in progress.
> Drift has no live broker connection, active order execution, or live capital.

---

## Core Philosophy

1. **Evidence First**: All hypotheses, datasets, experiments, models, and
   outcomes are recorded in a tamper-evident, append-only, hash-chained ledger.
2. **Point-in-Time Truth**: Data contracts strictly enforce what was observable
   and available at each exact historical instant. Future information leakage is
   a hard failure.
3. **Research / Safety Separation**: Autonomous AI agents may propose research
   hypotheses and strategy models, but live execution safety, hard risk limits,
   position caps, and emergency kill switches are enforced deterministically
   outside the agent's context.

---

## Architecture Flow

Drift's roadmap runs from M0 through M18+, with M1 split into independently accepted submilestones:

```text
historical source evidence
  -> provenance and point-in-time reconstruction
  -> evaluator and backtester
  -> deterministic baselines
  -> prediction and outcome tracking
  -> structured research memory
  -> AI research agent
  -> recursive R&D loop
  -> champion / challenger tournament
  -> promotion and anti-overfitting gates
  -> shadow broker
  -> deterministic hard risk
  -> broker-neutral execution interface
  -> live validation
  -> official Robinhood Agentic MCP
  -> tiny-money canary
  -> bounded autonomy
```

---

## Current Project Status

- **M0: Auditable Evidence Kernel**: Complete (monotonically sequenced SQLite ledger).
- **M1a: Temporal Provenance**: Complete (exact manifests, availability, cutoff gates).
- **M1b: Historical Identity and Universes**: Complete (issuer/security/listing separation, survivor-free universes).
- **M1c: Corporate Actions and Economic Outcomes**: Complete (action terms, occurred effects, reported settlements).
- **M1d: Observations, Sessions, and Normalization**: Complete (raw source claims, realized sessions, split normalization).
- **M1e: Real-Source Qualification and Replay Closure**: In Progress / Deferred.
  Tasks 1 through 7 are complete (offline macOS/arm64 environment closure, golden case
  grader G01-G18, replay harness). Task 8 (paid promotion-grade qualification) is deferred
  under ADR 0012 until economically justified by exploratory research.
  (See [M1e Provider Selection](docs/architecture/m1e-provider-selection.md) and [ADR 0012](docs/adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md)).
- **M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel**: Next Milestone.
  Exploratory evaluator development with free development data (Alpaca Basic) is authorized
  under ADR 0012; promotion-grade evaluation remains strictly gated on positive M1e qualification.
  (See [M2 Design](docs/superpowers/specs/2026-09-19-m2-deterministic-session-evaluator-design.md)
  and [M2 Plan](docs/superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md)).

---

## Quick Start and Verification

Drift requires Python 3.14 or later and [uv](https://docs.astral.sh/uv/).

`requires-python = ">=3.14"` is the package compatibility contract. The
development and pinned-replay environment is a separate, exact contract:
CPython 3.14.6, pinned in [`.python-version`](.python-version), which uv
selects automatically and CI reads. Every M1d normalization derivation binds
the exact interpreter patch version (`python_identity`), so pinned M1d replay
under any other interpreter fails before replay starts with
`PINNED_REPLAY_ENVIRONMENT_MISMATCH expected cpython-3.14.6 found cpython-X.Y.Z`.
Pinned replay failures are always one of four named classes: environment
mismatch, environment artifact unavailable, semantic replay mismatch, or
fixture or inventory integrity failure (see
[`tests/_pinned_m1d.py`](tests/_pinned_m1d.py)).

Changing the pin is an explicit environment migration: change
`.python-version`, run the complete suite, investigate any semantic
difference, and mint a new replay baseline and supersession record only if
equivalence is demonstrated, as
[`tests/fixtures/m1d-replay-baselines/cpython-3.14.6/`](tests/fixtures/m1d-replay-baselines/cpython-3.14.6/supersession.json)
does for 3.14.5 to 3.14.6. Never regenerate replay expectations merely because
a new patch release exists.

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs
the verification suite below, plus `git diff --check`, on every pull request
and on every push to `main`, under the same pinned interpreter. CI never
regenerates fixtures or baselines.

```bash
# Sync development dependencies
uv sync --dev

# Run standard verification suite
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

To initialize and verify the local audit ledger:

```bash
uv run python scripts/init_local_db.py .drift/ledger.db
uv run python scripts/verify_ledger.py .drift/ledger.db
```

---

## Canonical Documentation Map

- **Operating Contract for AI/Engineers**: [`AGENTS.md`](AGENTS.md)
- **Workstream Ownership**: [`docs/architecture/workstreams.md`](docs/architecture/workstreams.md)
- **Agent Operating Workflow & Continuity**: [`docs/architecture/agent-workflow.md`](docs/architecture/agent-workflow.md)
- **Architecture Overview**: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- **Project Roadmap (M0 to M18+)**: [`docs/architecture/roadmap.md`](docs/architecture/roadmap.md)
- **M1e Provider Selection & Screening**: [`docs/architecture/m1e-provider-selection.md`](docs/architecture/m1e-provider-selection.md)
- **Trust Boundaries & Data Retention**: [`docs/architecture/trust-boundaries.md`](docs/architecture/trust-boundaries.md)
- **Accepted Architecture Decision Records**: [`docs/adr/`](docs/adr/)
- **Active Implementation Plan**: [`docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md`](docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md)
