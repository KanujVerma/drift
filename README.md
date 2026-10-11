# Drift

Drift is an evidence-driven, self-improving quantitative research and trading
system. Its core objective is to discover whether a strategy has repeatable
predictive and risk-adjusted value without fooling itself through lookahead
bias, survivorship bias, or ungrounded simulation assumptions.

Research outputs in Drift remain strictly untrusted until validated through a
tamper-evident, append-only evidence history and explicit promotion gates.

> **Current Boundary**: Drift is an evidence-first quantitative research system,
> not a live trading bot. Foundations M0 through M6 are complete and verified.
> The research pipeline (M7 research agent, M8 recursive R&D loop, and M10
> champion/challenger tournament) is connected to authentic M2 deterministic
> evaluation and fortified with an empirical scientific integrity firewall.
> Execution architecture (M12 simulated broker, M13 hard risk, M14 broker-neutral
> router, M15 shadow validation, M16 Robinhood adapter, M17 canary, and M18+
> bounded autonomy) is implemented in runtime code, but live broker connection,
> active order placement, and live capital remain strictly **UNAUTHORIZED**.
> Paid promotion qualification (M1e Task 8) is deferred under ADR 0012.

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
  -> statistical and model scorecards
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

Drift evaluates progress across five distinct dimensions:
- **IMPLEMENTED**: Code written and merged in repository.
- **TESTED**: Unit, integration, and adversarial tests passing.
- **INDEPENDENTLY REVIEWED**: Reviewed and accepted through external architectural review.
- **SCIENTIFICALLY QUALIFIED**: Backed by accepted promotion-grade source data and out-of-sample rigor.
- **OPERATIONALLY AUTHORIZED**: Authorized for live capital or external brokerage execution.

| Milestone | Implementation | Tests | Review | Scientific Qualification | Operational Authority |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **M0** Evidence Kernel | COMPLETE | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1a-d** Provenance & Normalization | COMPLETE | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1e** Source Qualification (Tasks 1-7) | COMPLETE | COMPLETE | ACCEPTED | DEFERRED (Task 8) | LOCAL ONLY |
| **M2** Deterministic Evaluator | COMPLETE | COMPLETE | ACCEPTED | EXPLORATORY (ADR 0012) | LOCAL ONLY |
| **M3** Reference Baselines (B0-B5) | COMPLETE | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M4** Prediction / Outcome Tracking | COMPLETE | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M5** Statistical Scorecards | COMPLETE | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M6** Research Memory | COMPLETE | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M7** AI Research Agent | COMPLETE | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M8** Recursive R&D Loop | COMPLETE | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M10** Champion / Challenger | COMPLETE | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M11** Promotion / Overfitting Gates | QUEUED | QUEUED | QUEUED | UNQUALIFIED | UNAUTHORIZED |
| **M12** Simulated Shadow Broker | COMPLETE | COMPLETE | ACCEPTED | N/A (SIMULATION) | UNAUTHORIZED |
| **M13** Deterministic Hard Risk | COMPLETE | COMPLETE | ACCEPTED | N/A (RISK GATE) | UNAUTHORIZED |
| **M14** Broker-Neutral Router | COMPLETE | COMPLETE | ACCEPTED | N/A (EXECUTION) | UNAUTHORIZED |
| **M15** Paper / Shadow Validation | COMPLETE | COMPLETE | ACCEPTED | N/A (SHADOW) | UNAUTHORIZED |
| **M16** Robinhood Agentic MCP Adapter | COMPLETE | COMPLETE | ACCEPTED | N/A (ADAPTER) | **UNAUTHORIZED** |
| **M17** Tiny-Money Canary | COMPLETE | COMPLETE | ACCEPTED | N/A (CANARY) | **UNAUTHORIZED** |
| **M18+** Bounded Autonomy | COMPLETE | COMPLETE | ACCEPTED | N/A (AUTONOMY) | **UNAUTHORIZED** |

### Parallel Research Portfolios ($10,000 Initial Capital)
Drift provides an isolated, deterministic research portfolio cohort harness
(`drift.experiments.parallel_portfolios` / `drift-portfolios` CLI) for evaluating
independent $10,000 strategy accounts in parallel under identical market sessions:
```bash
# Run deterministic parallel research portfolio cohort demo
uv run python -m drift.experiments.parallel_portfolios
# Or via console entry point
uv run drift-portfolios
```

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
