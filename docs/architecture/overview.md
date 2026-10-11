# Architecture Overview

## Long-Term Vision and End-to-End Pipeline

Drift is an evidence-driven, self-improving quantitative research and trading
system. Its core objective is to discover whether a strategy has repeatable
predictive and risk-adjusted value without fooling itself through lookahead
bias, survivorship bias, or ungrounded simulation assumptions.

The system is organized around two evaluation lanes separating untrusted exploratory
research from promotion-grade live execution safety:

```text
               [Free Development Data (Alpaca Basic)]
                                  │
                                  ▼
               [Exploratory Evaluator / R&D (M2-M9)]
                                  │
                                  ▼
               [Candidate Worth Promotion Validation?]
                        │                   │
                     No │                   │ Yes
                        ▼                   ▼
                 [Iterate / Retire]  [M1e Promotion Qualification]
                                            │
                                            ▼
                                     [Fresh Promotion Run]
                                            │
                                            ▼
                               [Champion / Challenger (M10)]
                                            │
                                            ▼
                              [Overfitting Controls (M11)]
                                            │
                                            ▼
                                   [Shadow Broker (M12)]
                                            │
                                            ▼
                               [Deterministic Hard Risk (M13)]
                                            │
                                            ▼
                              [Broker-Neutral Execution (M14)]
                                            │
                                            ▼
                                   [Live Validation (M15)]
                                            │
                                            ▼
                                 [Robinhood MCP Live (M16)]
                                            │
                                            ▼
                                  [Tiny-Money Canary (M17)]
                                            │
                                            ▼
                                   [Bounded Autonomy (M18+)]
```

### Core Architecture Principles

1. **Two Evaluation Lanes (ADR 0012)**:
   - *Exploratory Lane*: Consumes free, imperfect development data (Alpaca Basic)
     to build evaluator mechanics, test baselines, explore signals, and discover
     promising hypotheses. Strictly non-promotable.
   - *Promotion Lane*: Gated by positive M1e real-source qualification, exact
     retained source bytes, and verified offline replay closure.
2. **Absolute Non-Upgrade Rule**:
   Exploratory evaluation results can NEVER be relabeled, converted, or upgraded
   into promotion-grade evidence. Promotion requires a fresh, independent
   evaluation run against an accepted promotion-qualified M1e dataset.
3. **Research / Safety Separation**:
   - *Untrusted Research*: Strategies, hypotheses, predictive models, and agent
     reasoning are treated as untrusted experimental outputs. They can propose
     intent but have zero direct access to order placement or live market controls.
   - *Deterministic Live Safety*: Execution, risk limits, position sizing, and
     account safeguards are implemented in deterministic, audited runtime code
     outside the AI agent's prompt or reasoning context.

---

## Implemented Foundations (M0-M1d) and Current M1e

The codebase currently implements the foundational evidence, temporal, and
semantic layers:

### Implemented Research Foundations (M0 through M6)
- **M0 Evidence Kernel**: Monotonically sequenced SQLite ledger with SHA-256 hash chaining.
- **M1a-M1d Provenance & Normalization**: Temporal manifests, survivor-free universes, corporate action replay, and cutoff-safe split-normalized views.
- **M1e Source Qualification (Tasks 1-7)**: macOS/arm64 offline closure and Table 1401 golden case invariant grader (Task 8 deferred under ADR 0012).
- **M2 Deterministic Evaluator**: Provider-neutral session evaluator and portfolio accounting kernel operating across exploratory and promotion lanes.
- **M3 Deterministic Baselines**: Reference benchmark strategies B0 through B5 with whole-tree inventory provenance.
- **M4 Prediction and Outcome Tracking**: Ex-ante prediction sets and deterministic outcome batches with fail-closed missingness.
- **M5 Statistical and Model Scorecards**: Predictive calibration, performance attribution, DSR multiple-testing adjustments, and PnL completeness propagation.
- **M6 Structured Research Memory**: Append-only SQLite research memory journal and query engine.

### Autonomous Research Loop and Tournament (M7, M8, M10)
- **M7 AI Research Agent**: Autonomous Gemini-assisted hypothesis and experiment specification with strict parameter validation.
- **M8 Recursive R&D Loop**: Iterative research refinement connected directly to authentic M2 deterministic session evaluation via `M2TrialEvaluatorAdapter`.
- **M10 Champion / Challenger Tournament**: Model tournaments guarded by a non-negotiable Scientific Integrity Firewall eliminating synthetic returns and enforcing empirical paired series.
- **Parallel Research Portfolios**: Isolated $10,000 portfolio cohort harness (`drift.experiments.parallel_portfolios`) for reproducible multi-strategy evaluation.

### PR #350 Additions (Research Integrity & Parallel Portfolios)

| Component | Domain Schema | Ledger Events | Service Implementation | Unit Tests | Verification Suite | Status | Lane Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Deterministic Evaluator Adapter** (M2/M8) | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Parallel $10,000 Portfolios Harness** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Scientific Integrity Firewall** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |
| **Tournament Evidence Requirements** | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE | PENDING EXTERNAL REVIEW | EXPLORATORY ONLY |

> **Exploratory Lane Non-Upgrade Invariant**: Evidence generated within the exploratory lane
> is strictly non-promotable and cannot be upgraded into promotion-grade evidence. Promotion
> requires a fresh run against an accepted promotion-qualified M1e dataset. PR #350 does NOT
> qualify M1e Task 8 or promote strategies to live trading.
> Supported CLI execution: `python -m drift.experiments.parallel_portfolios`.

---

## Execution and Risk Architecture (M12 through M18+)

> **Operational Boundary**: Milestones M12 through M18+ are fully implemented in runtime
> code and verified across unit and adversarial test suites. However, in accordance with
> ADR 0011, ADR 0012, and ADR 0014, live broker connection, active order placement, and
> live capital remain strictly **UNAUTHORIZED**.

### Implemented Execution Components
1. **M12 Simulated Shadow Broker**: In-memory broker simulator tracking orders, fills, and exposures.
2. **M13 Deterministic Hard Risk**: Non-negotiable risk gatekeeper enforcing position limits, gross exposure caps, drawdown stops, and persistent kill switches.
3. **M14 Broker-Neutral Execution**: Abstract router and persistent order intent journal enforcing strict idempotency and position reconciliation.
4. **M15 Shadow Validation**: Live tick streamer, execution drift tracker, and shadow validation telemetry.
5. **M16 Official Robinhood Agentic MCP Adapter**: Official Agentic Trading protocol integration behind broker-neutral execution (ADR 0011).
6. **M17 Tiny-Money Canary**: Micro-capital execution layer with allocation gatekeepers and settlement grading.
7. **M18+ Bounded Autonomy**: Tier-based capital expansion governors with audited evidence ledgers.

---

## Canonical Documentation Map

- **Roadmap and Milestone Status**: [roadmap.md](roadmap.md)
- **Workstream Ownership**: [workstreams.md](workstreams.md)
- **Agent Operating Workflow and Authority**: [agent-workflow.md](agent-workflow.md)
- **Trust Boundaries and Retention**: [trust-boundaries.md](trust-boundaries.md)
- **Execution Safety Audit**: [execution-safety-audit.md](execution-safety-audit.md)
- **M1e Provider Selection State**: [m1e-provider-selection.md](m1e-provider-selection.md)
- **Accepted Architecture Decisions**: [docs/adr/](../adr/)
- **Active Executable Plan**: [docs/superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md](../superpowers/plans/2026-09-19-m2-deterministic-session-evaluator.md)
