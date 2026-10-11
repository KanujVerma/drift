# Drift Project Roadmap

This document outlines the phased milestone progression of Drift from a
tamper-evident evidence kernel to a bounded, self-improving quantitative trading system.

Milestones are ordered by causal dependency. Milestone numbers do not represent
equal units of engineering effort; earlier milestones establish scientific and
data integrity, while later milestones introduce modeling, evaluation, and live
execution.

Permanent implementation owners for M2 through M18+ are defined in
[workstreams.md](workstreams.md). GitHub Issues and PRs own live task state.
This roadmap does not track current issue numbers, percent complete, or
session status.

[ADR 0014](../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md)
assigns all remaining active roadmap implementation, M2 through M18+, to
Krish. [ADR 0013](../adr/0013-parallelize-owned-milestones-without-advancing-authorization.md)
remains the historical record of the superseded 8/8 split. Its separation of
build order from authorization order still applies. Code availability is not
operational authorization.

---

## Milestone Status Overview

Progress is evaluated across five distinct dimensions:
- **IMPLEMENTED**: Code written and merged into repository.
- **TESTED**: Unit, integration, and adversarial tests passing.
- **INDEPENDENTLY REVIEWED**: Reviewed and accepted by independent architecture review.
- **SCIENTIFICALLY QUALIFIED**: Backed by accepted promotion-grade source data and out-of-sample rigor.
- **OPERATIONALLY AUTHORIZED**: Authorized for live capital or external brokerage execution.

| Milestone | Title | Owner | Implementation & Test | Review | Scientific Qualification | Operational Authority |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M0** | Auditable Evidence Kernel | - | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1a** | Temporal Provenance | - | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1b** | Historical Identity / Universes | - | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1c** | Corporate Actions / Economic Facts | - | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1d** | Observations, Sessions, Normalization | - | COMPLETE | ACCEPTED | QUALIFIED | LOCAL ONLY |
| **M1e** | Real-Source Qualification & Replay | - | TASKS 1-7 COMPLETE | ACCEPTED | DEFERRED (Task 8) | LOCAL ONLY |
| **M2** | Evaluator / Backtester | Krish | COMPLETE | ACCEPTED | EXPLORATORY (ADR 0012) | LOCAL ONLY |
| **M3** | Deterministic Baselines (B0-B5) | Krish | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M4** | Prediction / Outcome Tracking | Krish | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M5** | Statistical / Model Scorecards | Krish | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M6** | Structured Research Memory | Krish | COMPLETE | ACCEPTED | EXPLORATORY | LOCAL ONLY |
| **M7** | First AI Research Agent | Krish | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M8** | Recursive R&D Loop | Krish | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M9** | Multi-Agent Research | Krish | CONDITIONAL | - | UNQUALIFIED | LOCAL ONLY |
| **M10** | Champion / Challenger Tournament | Krish | COMPLETE | PENDING REVIEW | EXPLORATORY | LOCAL ONLY |
| **M11** | Promotion & Overfitting Controls | Krish | QUEUED | - | UNQUALIFIED | UNAUTHORIZED |
| **M12** | Simulated Shadow Broker | Krish | COMPLETE | ACCEPTED | N/A (SIMULATION) | UNAUTHORIZED |
| **M13** | Deterministic Hard Risk | Krish | COMPLETE | ACCEPTED | N/A (RISK GATE) | UNAUTHORIZED |
| **M14** | Broker-Neutral Execution | Krish | COMPLETE | ACCEPTED | N/A (EXECUTION) | UNAUTHORIZED |
| **M15** | Real-World Paper / Shadow Validation | Krish | COMPLETE | ACCEPTED | N/A (SHADOW) | UNAUTHORIZED |
| **M16** | Official Robinhood Agentic MCP Adapter | Krish | COMPLETE | ACCEPTED | N/A (ADAPTER) | **UNAUTHORIZED** |
| **M17** | Tiny-Money Canary | Krish | COMPLETE | ACCEPTED | N/A (CANARY) | **UNAUTHORIZED** |
| **M18+** | Bounded Autonomy & Improvement | Krish | COMPLETE | ACCEPTED | N/A (AUTONOMY) | **UNAUTHORIZED** |

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

### M1e: License-Gated Real-Source Qualification and Replay Closure (In Progress / Deferred)
- **Status**:
  - Tasks 1 through 7 complete and verified across 1,882 tests at commit `4b343f7` (`4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`).
  - Implemented provider-neutral qualification profiles, rights assessments,
    private content store, exact snapshots, golden case grader (G01-G18), macOS/arm64
    environment closure (19 artifact categories), and offline replay harness.
  - Task 8 (Real-Source Pilot): Paid promotion-grade source qualification is
    paused/deferred under ADR 0012 until economically justified by exploratory
    research. Task 8 remains open.
- **Provider Screening Results**:
  - *algoseek*: Sandbox testing proved strong identity and market event semantics,
    but reference-data revisions overwrite historical assertions, preventing its use
    as the sole source for historical decision input.
  - *Databento*: Leading candidate for future promotion-grade qualification (`pit=True`,
    `event_unique_id`, `ts_record`, Security Master from 2005, batch manifests).
    Paid reference subscription is deferred.
  - *Alpaca*: Screened on free Basic plan. Designated under ADR 0012 as the preferred
    FREE DEVELOPMENT source for exploratory evaluator engineering. Explicitly NOT
    M1e-qualified (corporate action mutation replay truncated to ~72 days, derived
    bars unversioned, trading halts absent).
- **Documents**: See [M1e Provider Selection](m1e-provider-selection.md) and
  [ADR 0012](../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

### M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel (Complete)
- **Owner**: Krish. Remaining M2 implementation belongs to workstream `krish`. Historical Task 2A work through `ca055b8011e72b0834075f67a402228df76e18da` was completed under the Kanuj workstream.
- **Status**: Complete. Closed with Issue #1 and Issue #8 (PR #156).
- **Objective**: Implement a single deterministic, provider-neutral evaluator core
  operating across two distinct evaluation lanes:
  - *EXPLORATORY Lane*: Consumes free development data (Alpaca Basic) with known
    explicit limitations for signal exploration, baseline verification, and
    engineering validation. Strictly non-promotable.
  - *PROMOTION Lane*: Strictly gated by positive M1e real-source qualification,
    exact retained source bytes, and verified offline replay closure.
- **Absolute Non-Upgrade Rule**: Exploratory evaluation results can NEVER be
  relabelled, promoted, or converted to promotion-grade evidence. Promotion
  requires a fresh, independent evaluation run executed directly against an
  accepted promotion-qualified M1e dataset.
- **Invariants**: Consumes only accepted provider-neutral M1b-M1d artifacts,
  explicit limitations, and replay identities. Never evaluates with future
  information. Completely decoupled from live brokerage or execution logic. No
  vendor-specific API logic in the evaluator core.
- **Documents**: See [M2 Design Specification](../superpowers/specs/2026-09-19-m2-deterministic-session-evaluator-design.md)
  and [M2 Implementation Plan](../superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md).

### M3: Deterministic Baselines (Complete)
- **Owner**: Krish.
- **Status**: Complete. Closed with Issue #10 and PR #170 (#169).
- **Objective**: Build passive, factor, and mechanical reference strategies against
  which future research models are compared.
- **Delivered**:
  - Deterministic reference baseline strategy library B0 through B5 in `src/drift/baselines/`:
    - B0: Cash (Null Hypothesis)
    - B1: Per-Security Buy-and-Hold
    - B2: Equal-Weight Cohort Buy-and-Hold
    - B3: Monthly Equal-Weight Rebalance
    - B4: 12-1 Momentum (Corporate-action-consistent analytical returns)
    - B5: 60-Session Low Volatility (Exact population return variance)
  - Canonical baseline suite runner in `src/drift/baselines/runner.py` binding
    whole-tree code-version provenance (`drift_source_inventory_hash()`).
  - Comprehensive adversarial acceptance suite in `tests/adversarial/test_m3_baselines_adversarial.py`
    verifying lookahead immunity, cohort survivorship, non-promotability,
    closed-world replay determinism, and fail-closed missingness.
- **Invariants**: Pure deterministic functions of decision contexts; whole-share
  long-only allocations; strictly non-promotable exploratory evidence; zero broker
  or execution authority.

### M4: Prediction and Outcome Tracking (Complete)
- **Owner**: Krish.
- **Status**: Complete. Closed with Issue #11 and PR #184 (#183).
- **Objective**: Record ex-ante model predictions and link them auditably to
  subsequent realized market facts in the ledger, enforcing temporal causality
  and fail-closed completeness.
- **Delivered**:
  - Domain models and ledger schemas in `src/drift/domain/predictions.py` and
    `src/drift/domain/outcomes.py` (`ExAntePredictionRecordV1`, `ExAntePredictionSetV1`,
    `RealizedOutcomeRecordV1`, `RealizedOutcomeBatchV1`).
  - Atomic epoch recorder and M0 ledger persistence in `src/drift/tracking/recorder.py`
    (`PredictionRecorder`, `m4.prediction_set.recorded`).
  - Deterministic outcome resolver and attribution engine in `src/drift/tracking/resolver.py`
    (`OutcomeResolver`, `m4.outcome_batch.resolved`) supporting forward returns,
    directional returns, realized volatility, excess return, and cross-sectional rank.
  - Fail-closed terminal states: `RESOLVED`, `INDETERMINATE`, `DELISTED_WITH_OUTCOME`,
    `DELISTED_WITHOUT_OUTCOME`, and `EXCLUDED_UNAVAILABLE`.
  - Baseline predictor adapters in `src/drift/tracking/adapters.py` (`B4MomentumPredictor`,
    `B5LowVolatilityPredictor`, `NullReferencePredictor`).
  - Evaluation tracking harness in `src/drift/tracking/harness.py` (`PredictionTrackingHarness`).
  - Comprehensive adversarial acceptance suite in `tests/adversarial/test_m4_prediction_tracking_adversarial.py`
    verifying lookahead immunity, causality ordering, anti-cherry-picking, corporate action invariance,
    and replay determinism.
- **Invariants**: Bitwise-reproducible prediction sets and outcome batches; fail-closed
  completeness with zero dropped cohort members; corporate-action-consistent analytical returns;
  strictly non-promotable exploratory evidence; zero broker or execution authority.

### M5: Statistical and Model Scorecards (Complete)
- **Owner**: Krish.
- **Status**: Complete. Closed with Issue #12 and PR #200 (#199).
- **Objective**: Measure calibration, information coefficients, performance attribution, risk profiles, drawdown profiles, and multiple-testing adjustments across strategies and predictive models.
- **Delivered**:
  - Domain models and ledger schemas in `src/drift/domain/scorecards.py` (`PredictionScorecardV1`, `StrategyScorecardV1`, `ModelScorecardV1`, `InformationCoefficientSummaryV1`, `CalibrationSummaryV1`, `DrawdownProfileV1`, `MultipleTestingAdjustmentsV1`, `AuditEventPayloadV1`).
  - Predictive power and calibration metrics engine in `src/drift/scorecards/predictive.py` (fractional ranks with symmetric tie-breaking, Spearman/Pearson correlation, Information Coefficients, Brier score, ECE, reliability bins).
  - Performance attribution, risk profiles, drawdown engine, and PnL completeness validation in `src/drift/scorecards/performance.py` (cumulative/annualized returns, annualized volatility, downside deviation, Sharpe, Sortino, Calmar, underwater drawdown curves, strict propagation of `RealizedPnLCompletenessV1` per Issue #152).
  - Multiple-testing adjustment engine in `src/drift/scorecards/multiple_testing.py` (Deflated Sharpe Ratio per Bailey & Lopez de Prado 2014, Bonferroni, Holm step-down FWER, Benjamini-Hochberg step-up FDR).
  - Composite scorecard generator harness and M0 ledger sealing in `src/drift/scorecards/generator.py` (`ScorecardGeneratorHarness`, `m5.scorecard.recorded` audit events).
  - Comprehensive adversarial acceptance suite in `tests/adversarial/test_m5_scorecards_adversarial.py` (bit-flip tampering, degenerate zero-volatility returns, single-session returns, PnL incompleteness anti-laundering, multiple-testing monotonicity, large-trial selection bias deflation, degenerate prediction bounds, SQLite ledger trigger and cryptographic chain tampering, empty shell model scorecard rejection, empty epoch fail-closed, epoch order invariance).
- **Invariants**: Pure Python standard-library math (Decimal, math.sqrt, statistics.NormalDist) with zero numpy or scipy runtime dependencies; strict non-promotable exploratory lane evidence; fail-closed PnL completeness preservation; tamper-evident cryptographic hash chains; zero broker or execution authority.

### M6: Structured Research Memory (Complete)
- **Owner**: Krish.
- **Status**: Complete. Closed with Issue #13 and PR #208.
- **Objective**: Establish a queryable historical archive of hypotheses, trials, parameter searches, and failure postmortems to prevent repeat errors.
- **Delivered**:
  - Domain models in `src/drift/domain/research_memory.py` (`HypothesisRecordV1`, `ExperimentRunRecordV1`, `NegativeResultPostmortemV1`, `ResearchArchiveQueryV1`).
  - Append-only SQLite research memory journal and query engine in `src/drift/memory/archive.py` (`ResearchMemoryArchive`, SQL append-only triggers).
  - Comprehensive adversarial acceptance suite in `tests/adversarial/test_m6_research_memory_adversarial.py`.
- **Invariants**: Append-only immutability enforced by SQLite triggers; tamper-evident hash chaining; strictly zero Unicode em dashes.

### M7 through M11: Autonomous Research and R&D Loop
- **M7 First AI Research Agent** (Krish; Implemented & Verified): Autonomous Gemini-assisted research agent
  (`src/drift/agent/`) generating testable hypotheses, valid experiment specifications, and parameter
  constraints for canonical baseline strategies (B0-B5) with search space exhaustion detection.
- **M8 Recursive R&D Loop** (Krish; Implemented & Connected to M2): Automated iterative loop
  (`src/drift/loop/`) executing research cycles against authentic deterministic M2 evaluation
  (`src/drift/loop/evaluator_adapter.py`) rather than synthetic mocks. Evaluates within the
  exploratory lane (ADR 0012).
- **M9 Multi-Agent Research** (Krish; Conditional): Specialized agent roles (e.g., hypothesis
  generator, risk critic, feature engineer) to be pursued only if empirical evidence proves
  clear advantage over a unified research agent.
- **M10 Champion / Challenger Tournament** (Krish; Implemented & Fortified): Systematic out-of-sample
  competitions (`src/drift/tournament/`) guarded by a non-negotiable Scientific Integrity Firewall
  that strictly prohibits synthetic return construction, mandates empirical paired return alignments,
### PR #350 Additions: Research Integrity, Real Evaluation, and Parallel Portfolios
- **Status**: PENDING EXTERNAL REVIEW across all components.
- **Lane**: EXPLORATORY ONLY (ADR 0012).
- **Absolute Non-Upgrade Rule**: Exploratory evaluation evidence is strictly non-promotable
  and cannot be upgraded, relabeled, or converted into promotion-grade evidence. Promotion
  requires a fresh, independent evaluation run directly against an accepted promotion-qualified
  M1e dataset. PR #350 does NOT qualify M1e Task 8 and does NOT promote strategies to production.

| Component | Domain Schema | Ledger Events | Service Implementation | Unit Tests | Verification Suite | Status | Lane Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Deterministic Evaluator Adapter** (M2/M8) | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Parallel $10,000 Portfolios Harness** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Scientific Integrity Firewall** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Tournament Evidence Requirements** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |

- **Delivered**:
  - `M2TrialEvaluatorAdapter` bridging M8 recursive research loop to authentic M2 deterministic portfolio accounting kernel.
  - `PortfolioCohortHarness` in `src/drift/experiments/parallel_portfolios.py` running reproducible parallel $10,000 strategy accounts.
  - Supported CLI execution: `python -m drift.experiments.parallel_portfolios`.
  - Non-negotiable Scientific Integrity Firewall enforcing empirical paired returns, fail-closed PnL completeness, and rejecting mock evidence.
  - Cryptographic evidence binding for tournament comparisons (bundle_hash, cost_model_hash, session calendar match).

### M12 through M15: Execution and Risk Architecture (Complete)
- **M12 Shadow Broker** (Krish; Complete): Bridge research into realistic simulated execution, tracking
  intended orders, simulated/expected fills, portfolio exposure, realized outcomes,
  and explicit execution assumptions with deterministic accounting and reconciliation. Closed with Issue #19 and PR #277.
- **M13 Deterministic Hard Risk** (Krish; Complete): Hard-coded, non-negotiable risk limits (position caps,
  daily loss limits, persistent kill switches) running outside the AI agent's control. Closed with Issue #21 and PR #289.
- **M14 Broker-Neutral Execution** (Krish; Complete): Abstract execution protocols and order intent
  journals decoupling strategy logic from broker APIs (ADR 0002). Closed with Issue #22 and PR #301.
- **M15 Real-World Paper / Shadow Validation** (Krish; Complete): Live market feed processing, execution
  drift calculation, and order intent generation running in shadow mode. Closed with Issue #23 and PR #313.

### M16 through M18+: Live Execution and Controlled Autonomy (Complete)
- **M16 Official Robinhood Agentic MCP Adapter** (Krish; Complete): Implemented the live brokerage
  connection using Robinhood's official Agentic Trading protocol (ADR 0011). Closed with Issue #24 and PR #323.
- **M17 Tiny-Money Canary** (Krish; Complete): Micro-capital execution layer with strict capital limits,
  allocation gatekeepers, and fill/settlement reconciliation. Closed with Issue #25 and PR #335.
- **M18+ Bounded Autonomy** (Krish; Complete baseline runtime): Dynamic allocation expansion governors,
  tamper-evident SHA-256 hash-chained evidence ledgers, and monotonic tier state machine. Closed with Issue #26 and PR #347.
