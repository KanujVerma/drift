# Drift Project Roadmap

This document outlines the phased milestone progression of Drift from a
tamper-evident evidence kernel to a bounded, self-improving quantitative trading system.

Milestones are ordered by causal dependency. Milestone numbers do not represent
equal units of engineering effort; earlier milestones establish scientific and
data integrity, while later milestones introduce modeling, evaluation, and live
execution.

---

## Milestone Status Overview

| Milestone | Title | Status | Primary Output / Invariant |
|---|---|---|---|
| **M0** | Auditable Evidence Kernel | **COMPLETE** | Monotonic append-only SQLite ledger with SHA-256 hash chaining. |
| **M1a** | Temporal Provenance | **COMPLETE** | Exact-byte manifests, channel availability, and tri-state cutoffs. |
| **M1b** | Historical Identity / Universes | **COMPLETE** | Issuer/security/listing separation, point-in-time universe composition. |
| **M1c** | Corporate Actions / Economic Facts | **COMPLETE** | Terms, occurred effects, reported settlements, dependent replay. |
| **M1d** | Observations, Sessions, Normalization | **COMPLETE** | Source claims, realized sessions, missingness, split-normalized views. |
| **M1e** | Real-Source Qualification & Replay | **IN PROGRESS** | Tasks 1-7 complete (offline closure); Task 8 provider pilot pending. |
| **M2** | Evaluator / Backtester | Planned | Deterministic point-in-time strategy evaluation without lookahead. |
| **M3** | Deterministic Baselines | Planned | Passive, factor, and mechanical reference benchmark strategies. |
| **M4** | Prediction / Outcome Tracking | Planned | Audited tracking of ex-ante forecasts against realized market facts. |
| **M5** | Statistical / Model Scorecards | Planned | Rigorous performance attribution, calibration, and degradation metrics. |
| **M6** | Structured Research Memory | Planned | Semantic storage of past experiments, failures, and causal insights. |
| **M7** | First AI Research Agent | Planned | Autonomous hypothesis generation and experiment specification. |
| **M8** | Recursive R&D Loop | Planned | Continuous exploration, hypothesis refinement, and model iteration. |
| **M9** | Multi-Agent Research | Planned | Specialized research teams (pursued only if evidence warrants). |
| **M10** | Champion / Challenger Tournament | Planned | Systematic out-of-sample comparison of incumbent and contender models. |
| **M11** | Promotion & Overfitting Controls | Planned | Deflated Sharpe ratios, multiple-testing penalties, strict gatekeeping. |
| **M12** | Shadow Broker | Planned | Realistic simulated broker tracking intended orders, fills, and exposures. |
| **M13** | Deterministic Hard Risk | Planned | Hard-coded executor limits, persistent kill switches, drawdown stops. |
| **M14** | Broker-Neutral Execution | Planned | Abstract execution interfaces decoupling strategies from venues. |
| **M15** | Real-World Paper / Shadow Validation | Planned | Live market feed validation without capital risk. |
| **M16** | Official Robinhood Agentic MCP Adapter | Planned | Integration with Robinhood via official Agentic Trading protocol. |
| **M17** | Tiny-Money Canary | Planned | Minimal real-capital validation (e.g., single-share order routing). |
| **M18+** | Bounded Autonomy & Improvement | Planned | Controlled live allocation with ongoing empirical evidence governance. |

---

## Detailed Milestone Definitions

### M0: Auditable Evidence Kernel (Complete)
- **Status**: Initial M0 implementation landed at commit `301dc9d`.
- **Delivered**: Domain models for research provenance, canonical JSON serialization,
  SHA-256 event hashing, and an append-only SQLite ledger with monotonic sequencing
  and snapshot verification.
- **Boundary**: Deliberately excludes market data, backtesting, brokers, and network access.

### M1a: Temporal Provenance (Complete)
- **Status**: Canonical completion at commit `0385493` (`0385493fb0c46f357f708a709f7331225564bc4c`, `fix: close residual M1a review gaps`).
- **Delivered**: Asset-neutral temporal provenance through exact-byte manifests,
  channel-scoped availability evidence, immutable fact revisions, exact-object
  validation records, and per-query tri-state cutoff decisions.

### M1b: Historical Identity and Universes (Complete)
- **Status**: Canonical completion at commit `14bad17` (`14bad1733222758ee3836568a10a90f2a16aeac3`, `docs: complete M1b identity milestone`).
- **Delivered**: Stable issuer, security, and listing identities; dated identifier
  and primary-listing mappings; listing lifecycle and termination state; point-in-time
  historical universe definitions; and structural eligibility resolvers.

### M1c: Corporate Actions and Economic Outcomes (Complete)
- **Status**: Canonical completion at commit `aecee94` (`aecee94207dbd64aa5154fe03295f35566ec7268`, `docs: complete M1c economic fact milestone`).
- **Delivered**: Immutable announced action terms, occurred effects, reported
  settlements, exact cash/share/property consideration components, coverage
  assertions, and separate decision/outcome selection with dependent replay.

### M1d: Observations, Sessions, and Normalization (Complete)
- **Status**: Canonical final completion at commit `af75cce` (`af75cce0f763de025f8ae3516577a9d0a1acead9`, `fix: close targeted M1d audit residuals`).
- **Delivered**: Immutable source observation claims, pinned schedule and
  realized-session facts, orthogonal missingness dimensions, finite M1b composition
  for research sessions, M1c action-to-session mapping, and cutoff-safe normalized views.

### M1e: License-Gated Real-Source Qualification and Replay Closure (In Progress)
- **Status**:
  - Tasks 1 through 7 complete and verified across 1,882 tests at commit `4b343f7` (`4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
  - Implemented provider-neutral qualification profiles, rights assessments,
    private content store, exact snapshots, golden case grader (G01-G18), macOS/arm64
    environment closure (19 artifact categories), and offline replay harness.
  - Task 8 (Real-Source Pilot) is pending provider empirical screening.
- **Provider Status**:
  - *algoseek*: Sandbox testing proved strong identity and market event semantics,
    but reference-data revisions overwrite historical assertions, preventing its use
    as the sole source for historical decision input.
  - *Databento*: Verified batch download manifests and market feeds; reference data
    requires paid subscription.
  - *Alpaca*: Designated as the next free-path candidate to evaluate corporate
    action mutation streams and historical data before committing capital to Databento.
- **Document**: See [M1e Provider Selection](m1e-provider-selection.md).

### M2: Evaluator and Backtester (Next Major Milestone)
- **Objective**: Implement a deterministic, point-in-time strategy evaluation engine.
- **Prerequisites**: Successful completion of M1e qualification.
- **Invariants**: Consumes only accepted provider-neutral M1b-M1d artifacts,
  explicit limitations, and replay identities. Never evaluates with future information.
  Completely decoupled from live brokerage or execution logic.

### M3 through M6: Quantitative Modeling Foundations
- **M3 Deterministic Baselines**: Build passive, factor, and mechanical reference
  strategies against which all future research models are compared.
- **M4 Prediction and Outcome Tracking**: Record ex-ante model predictions and link
  them auditably to subsequent realized market facts in the ledger.
- **M5 Statistical and Model Scorecards**: Measure calibration, information coefficients,
  drawdown profiles, and turnover with multiple-testing adjustments.
- **M6 Structured Research Memory**: Establish a queryable historical archive of
  hypotheses, trials, parameter searches, and failure postmortems to prevent repeat errors.

### M7 through M11: Autonomous Research and R&D Loop
- **M7 First AI Research Agent**: Deploy an autonomous agent tasked with generating
  testable hypotheses and creating valid experiment specifications.
- **M8 Recursive R&D Loop**: Establish an automated pipeline where the agent inspects
  evaluation results, diagnoses weaknesses, and proposes iterative refinements.
- **M9 Multi-Agent Research**: Introduce specialized agent roles (e.g., hypothesis
  generator, risk critic, feature engineer) only if empirical evidence proves superior
  results over a unified agent.
- **M10 Champion / Challenger Tournament**: Run ongoing out-of-sample competitions
  between current production models and newly promoted contenders.
- **M11 Promotion and Overfitting Controls**: Strict statistical gatekeeping incorporating
  Deflated Sharpe Ratios, Probability of Backtest Overfitting (PBO), multiple-testing
  and search-inflation controls, walk-forward out-of-sample evidence, stability/regime
  testing, and experiment-count awareness.

### M12 through M15: Execution and Risk Architecture
- **M12 Shadow Broker**: Bridge research into realistic simulated execution, tracking
  intended orders, simulated/expected fills, portfolio exposure, realized outcomes,
  and explicit execution assumptions with deterministic accounting and reconciliation.
- **M13 Deterministic Hard Risk**: Hard-coded, non-negotiable risk limits (position caps,
  daily loss limits, persistent kill switches) running outside the AI agent's control.
- **M14 Broker-Neutral Execution**: Abstract execution protocols and order intent
  journals decoupling strategy logic from broker APIs (ADR 0002).
- **M15 Real-World Paper / Shadow Validation**: Live market feed processing and order
  intent generation running in shadow mode.

### M16 through M18+: Live Execution and Controlled Autonomy
- **M16 Official Robinhood Agentic MCP Adapter**: Implement the live brokerage
  connection using Robinhood's official Agentic Trading protocol (ADR 0011).
- **M17 Tiny-Money Canary**: Route minimal real-capital orders (e.g., single-share
  allocations) to validate connectivity, fill reporting, and settlement reconciliation.
- **M18+ Bounded Autonomy**: Gradually expand allocation caps under continuous,
  audited evidence governance.
