# Milestone M15: Real-World Paper / Shadow Validation Design Specification

- **Milestone**: M15
- **Workstream**: `workstream:krish`
- **Issue**: #302 (Parent #23)
- **Status**: Proposed
- **Author**: Krish Verma
- **Date**: 2026-10-12

---

## 1. Executive Summary

Milestone M15 establishes the real-world validation substrate for Drift. It bridges
the offline backtest/evaluator (M2, M3, M4, M5) and research agents (M7, M8, M10, M11)
with live or paper market environments without placing real capital at risk.

M15 ingests real-time or recorded high-resolution streaming market data (quotes and trades),
evaluates strategy signals at realistic temporal cadences, exercises the complete
pre-trade hard risk gatekeeper (M13), routes order intents through the broker-neutral
router (M14), and monitors execution drift and slippage against theoretical marks.

---

## 2. Architectural Boundaries and Invariants

1. **Strictly Non-Discretionary & Pure Simulation**: M15 connects to paper or read-only
   market data streams. Real order routing to funded brokerages is strictly forbidden
   and prohibited by architecture gates until Milestone M16/M17.
2. **Causal Monotonicity**: Incoming market ticks must satisfy non-decreasing timestamps.
   Out-of-order ticks, timestamp rewinds, or future-dated events are rejected immediately.
3. **Fail-Closed Risk Verification**: Every generated order intent is evaluated against
   the persistent `HardRiskGatekeeper` (M13). If any policy breach or kill switch occurs,
   order routing is halted immediately.
4. **Idempotent Audit Journaling**: Every received market tick, evaluated decision,
   outbound intent, risk verdict, and simulated fill is durably persisted in SQLite
   with append-only triggers.
5. **Zero Em Dashes**: Pure ASCII hyphen (-) across all code, tests, docs, and commits.
6. **Pure Standard-Library Math**: `Decimal` for all prices, cash balances, quantities,
   and slippage metrics.

---

## 3. Data Models and Schemas

### 3.1. Market Feed Tick (`MarketTickV1`)

Represents a single point-in-time quote or trade update:
- `tick_id`: UUID7
- `security_id`: UUID7
- `timestamp`: UTC datetime
- `bid_price`: Decimal (optional)
- `bid_size`: int (optional)
- `ask_price`: Decimal (optional)
- `ask_size`: int (optional)
- `last_price`: Decimal
- `last_size`: int
- `tick_hash`: SHA-256 canonical hash

### 3.2. Shadow Order Execution Drift (`ExecutionDriftReportV1`)

Measures divergence between strategy intended price and simulated fill price:
- `drift_id`: UUID7
- `intent_id`: UUID7
- `security_id`: UUID7
- `intended_price`: Decimal
- `fill_price`: Decimal
- `slippage_bps`: Decimal
- `recorded_at`: UTC datetime
- `drift_hash`: SHA-256 canonical hash

### 3.3. Shadow Validation Session Summary (`ShadowValidationSummaryV1`)

Summarizes an end-to-end shadow validation run:
- `validation_id`: UUID7
- `session_key`: SessionKeyV1
- `total_ticks_processed`: int
- `orders_generated`: int
- `orders_approved`: int
- `orders_rejected_risk`: int
- `orders_filled`: int
- `total_slippage_bps`: Decimal
- `mean_slippage_bps`: Decimal
- `max_slippage_bps`: Decimal
- `final_equity`: Decimal
- `summary_hash`: SHA-256 canonical hash

---

## 4. Component Architecture

### 4.1. Market Data Streamer (`MarketDataStreamerProtocol` & `MockMarketDataStreamer`)

Provides asynchronous or synchronous generator yielding `MarketTickV1` events.
Enforces tick monotonicity and sanity validation (e.g. non-negative prices, bid <= ask).

### 4.2. Shadow Validation Engine (`ShadowValidationEngine`)

Coordinates the live paper cycle:
1. Ingests tick from streamer.
2. Updates mock adapter market prices (`adapter.set_price(...)`).
3. Evaluates strategy logic against current market state.
4. Routes generated intents through `HardRiskGatekeeper` (M13).
5. If approved, dispatches intent through `BrokerNeutralExecutionRouter` (M14).
6. Records execution drift and slippage.
7. Periodically reconciles portfolio holdings against adapter state.

### 4.3. Shadow Validation Journal (`PersistentShadowValidationJournal`)

SQLite-backed persistent store with append-only SQL triggers for:
- `market_ticks`
- `execution_drift_reports`
- `shadow_validation_summaries`

---

## 5. Implementation Slices

1. **M15-P0: Architecture & Design Specification** (Issue #302):
   `docs/superpowers/specs/2026-10-12-m15-paper-shadow-validation-design.md`.
2. **M15-1: Domain Models, Schemas, and Drift Metrics** (Issue #303):
   `src/drift/domain/paper_validation.py` with `MarketTickV1`, `ExecutionDriftReportV1`,
   `ShadowValidationSummaryV1`, builders, validators, and hashing.
3. **M15-2: Append-Only Persistent Shadow Validation Journal** (Issue #304):
   `src/drift/validation/journal.py` backed by SQLite with append-only triggers.
4. **M15-3: Streaming Market Feed Protocol and Mock Streamer** (Issue #305):
   `src/drift/validation/feed.py` providing `MarketDataStreamerProtocol` and
   deterministic `MockMarketDataStreamer`.
5. **M15-4: Shadow Validation Engine and Execution Orchestrator** (Issue #306):
   `src/drift/validation/engine.py` orchestrating ticks, risk gatekeeper, router, and drift tracking.
6. **M15-5: Adversarial Acceptance Suite for Paper/Shadow Validation** (Issue #307):
   `tests/adversarial/test_m15_paper_validation_adversarial.py` testing tick timestamp
   rewinds, crossed markets, risk circuit breaker latching, and drift calculation integrity.

---

## 6. Verification Commands

```bash
uv run pytest tests/unit/test_paper_validation*.py tests/adversarial/test_m15_paper_validation_adversarial.py
uv run ruff check src/drift/domain/paper_validation.py src/drift/validation tests/unit/test_paper_validation*.py tests/adversarial/test_m15_paper_validation_adversarial.py
uv run mypy src/drift/domain/paper_validation.py src/drift/validation tests/unit/test_paper_validation*.py tests/adversarial/test_m15_paper_validation_adversarial.py
```
