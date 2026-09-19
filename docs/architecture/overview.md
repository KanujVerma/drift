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

### M0: Research Evidence Kernel (Complete)
- Frozen Pydantic domain models for hypotheses, runs, evidence, and artifacts.
- Canonical JSON serialization guaranteeing deterministic byte representation.
- SHA-256 hash-chained audit events recording a tamper-evident, append-only causal history.
- Transactional, append-only local SQLite ledger with monotonic sequencing and
  snapshot verification.

### M1a: Temporal Provenance (Complete)
- Exact-byte dataset manifests with SHA-256 digests and file sizes.
- Channel-scoped availability evidence proving what was accessible when.
- Immutable fact revisions and exact-object validation records.
- Query-bound tri-state cutoff decisions preventing future information leakage.

### M1b: Historical Identity and Universes (Complete)
- Strict separation of issuer, security, and venue listing identities.
- Historical ticker mappings, primary listing venue histories, and delistings.
- Point-in-time universe composition and structural eligibility rules.

### M1c: Historical Economic Facts (Complete)
- Independent modeling of announced action terms, actual occurred effects, and
  reported settlement deliveries.
- Explicit cash, share, and property consideration components.
- Exact multi-source occurrence reconciliation with dependent replay.

### M1d: Observations, Sessions, and Normalization (Complete)
- Immutable source observation claims preserved without lossy assumptions.
- Pinned schedule and realized-session facts capturing early closes and halts.
- Orthogonal missingness dimensions distinguishing no-trade from non-reporting.
- Cutoff-safe source-basis and split-normalized historical views.

### M1e: License-Gated Real-Source Qualification and Replay Closure (In Progress / Deferred)
- Tasks 1 through 7 complete and verified across 1,882 tests.
- Provider-neutral qualification profiles, rights assessments, and private content store.
- Exact source snapshots and Table 1401 golden case invariant grader (G01-G18).
- macOS/arm64 environment closure (19 artifact kinds) and offline replay harness.
- Task 8 (real provider pilot): Paid promotion-grade source qualification is
  paused/deferred under ADR 0012 until economically justified by exploratory
  research. See [M1e Provider Selection](m1e-provider-selection.md) and
  [ADR 0012](../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## Future Execution Architecture (M13 through M16)

### Live Execution Safety Controls (M13 - M15)
When Drift reaches live execution validation, the runtime incorporates strict
safety patterns drawn from institutional trading systems:

1. **Deterministic Position and Order Limits**: Hard-coded caps on maximum order
   notional, maximum open position size, and maximum portfolio leverage.
2. **Persistent Kill Switch**: An external, file-backed emergency stop switch
   that survives process restarts and immediately cancels pending orders.
3. **Pending Order Intent State**: Orders must be recorded in an intent journal
   before submission to prevent duplicate order generation during network latency.
4. **Broker Readback and Reconciliation**: Continuous reconciliation loop matching
   local position intent against actual broker account positions.
5. **Crash Recovery**: Deterministic state reconstruction from the execution
   journal upon startup.
6. **Private Runtime State Outside Git**: All credentials, session tokens, and
   account state live in private local storage outside source control.
7. **Dry-Run / Shadow Preview Mode**: Full validation pipeline running against live
   quotes without order placement.
8. **Tiny-Capital Canary Rollout**: Real-money execution strictly constrained to
   minimal capital allocations (e.g., single-share canary testing).
9. **Cumulative Daily Loss Limits**: Hard automated circuit breakers halting
   trading if realized or unrealized drawdown exceeds daily thresholds.
10. **Asset Allowlists**: Execution restricted strictly to pre-approved, highly
    liquid symbols meeting universe criteria.

### Official Robinhood Agentic MCP Adapter (M16)
Drift integrates with live brokerages exclusively through standard, supported
interfaces (ADR 0002 and ADR 0011):

- **No Unofficial APIs**: Drift forbids reverse-engineered web scrapers,
  `robin_stocks`, browser automation, or private endpoint emulation.
- **Broker-Neutral Interface**: Core trading strategies interact with an
  abstract, broker-neutral execution boundary.
- **Official MCP Connection**: The live execution adapter communicates with
  Robinhood via the official Robinhood Agentic MCP protocol on a dedicated
  Agentic Trading Account.
- **Role Isolation**: Robinhood is live execution and account state
  infrastructure, never Drift's historical research truth source.

---

## Canonical Documentation Map

- **Roadmap and Milestone Status**: [roadmap.md](roadmap.md)
- **Agent Operating Workflow and Authority**: [agent-workflow.md](agent-workflow.md)
- **Trust Boundaries and Retention**: [trust-boundaries.md](trust-boundaries.md)
- **M1e Provider Selection State**: [m1e-provider-selection.md](m1e-provider-selection.md)
- **Accepted Architecture Decisions**: [docs/adr/](../adr/)
- **Active Executable Plan**: [docs/superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md](../superpowers/plans/2026-09-13-m1e-license-gated-real-source-qualification-replay-closure.md)
