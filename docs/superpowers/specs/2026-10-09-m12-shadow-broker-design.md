# Milestone M12: Shadow Broker Design Specification

**Status:** APPROVED
**Milestone:** M12 (Shadow Broker)
**Owner:** Krish (`workstream:krish`)
**Parent Issue:** #19
**Date:** 2026-10-09

---

## 1. Executive Summary & Problem Statement

Milestone M12 bridges research evaluation into realistic simulated execution. The Shadow Broker provides a deterministic execution harness tracking intended orders, simulated fills, portfolio exposure, realized outcomes, and explicit execution assumptions with deterministic accounting and reconciliation.

In pure backtest evaluation (M2-M5), target positions are rebalanced atomically under idealized next-open execution. In real markets, trading strategies face order lifecycles, execution delays, market eligibility constraints, transaction costs, partial fills, and broker reconciliations.

The Shadow Broker acts as a realistic simulated broker running between strategy decisions and portfolio accounting:
1. **Order Lifecycle**: Explicit order submission, queuing, validation, fills, and rejections;
2. **Three-Layer Tradability**: Separates market execution eligibility (M12), risk permissions (M13), and broker capabilities (M14/M16);
3. **Canonical Accounting Consumer**: Reconciles execution into the frozen M2 canonical accounting kernel (`PortfolioAccountingKernel`) without creating competing portfolio accounting semantics;
4. **Independent Append-Only Journal**: Persists execution events in a dedicated simulation journal rather than polluting the M0 research ledger with continuous execution state;
5. **Source Basis Normalization**: Fills and cost basis strictly use unadjusted historical prices and quantities.

---

## 2. Core Invariants & Boundaries

1. **M12 Consumes M2 Accounting (Issue #20 Q1)**: The Shadow Broker never re-implements portfolio state, cash accounting, cost basis, or NAV. It projects simulated fills into canonical `PortfolioFillV1` and applies them through `PortfolioAccountingKernel.apply_fill()`.
2. **Long-Only V1 Scope (Issue #20 Q6)**: Long-only, whole shares, unlevered, no margin, zero shorting.
3. **Source Basis Unadjusted Pricing (Issue #20 Q4)**: Execution prices are unadjusted historical market prices. Split-normalized prices are forbidden for fill simulation.
4. **V1 Cadence Matching (Issue #20 Q7)**: Decisions are made post-close; execution occurs at next-session open (`post_close_decision_next_open_execution`).
5. **Three-Layer Tradability Separation (Issue #20 F8)**: Market execution eligibility (`MarketExecutionEligibilityV1`) is strictly decoupled from M13 risk limits and M14/M16 broker account capabilities.
6. **Separate Append-Only Journal (Issue #20 Q3, U10)**: Simulation events are logged in an append-only SQLite journal. The M0 research ledger records only high-level summary evidence and certificates.
7. **Zero Em Dashes**: ASCII hyphen (-) exclusively across all code, docstrings, and documentation.

---

## 3. Architecture & Data Models

### 3.1. Market Execution Eligibility (`MarketExecutionEligibilityV1`)

```python
class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class MarketExecutionEligibilityV1(FrozenModel):
    security_id: UUID7
    session_key: SessionKeyV1
    status: EligibilityStatus
    reason: NonBlankStr | None = None
    evidence_hash: SHA256Hash | None = None
```

### 3.2. Simulated Order & Fill Models

```python
class SimulatedOrderStatus(StrEnum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SimulatedOrderV1(FrozenModel):
    order_id: UUID7
    session_key: SessionKeyV1
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int  # gt=0, long-only whole shares
    order_type: Literal["market", "limit"] = "market"
    limit_price: CanonicalMoney | None = None
    created_at: UTCDateTime
    order_hash: SHA256Hash


class SimulatedFillV1(FrozenModel):
    fill_id: UUID7
    order_id: UUID7
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int
    fill_price: CanonicalMoney  # unadjusted source basis
    transaction_costs: CanonicalMoney
    filled_at: UTCDateTime
    fill_hash: SHA256Hash
```

---

## 4. Implementation Slice Plan

1. **M12-P0: Architecture & Dependency Map**:
   - `docs/superpowers/specs/2026-10-09-m12-shadow-broker-design.md`: Canonical design specification.
2. **M12-1: Domain Models, Schemas, and Eligibility Layer**:
   - `src/drift/domain/shadow_broker.py`: Orders, fills, status enums, eligibility, content hashing.
   - Unit tests in `tests/unit/test_shadow_broker_domain.py`.
3. **M12-2: Append-Only Simulation Execution Journal**:
   - `src/drift/shadow/journal.py`: SQLite-backed event journal recording orders, rejections, fills, and reconciliations.
   - Unit tests in `tests/unit/test_shadow_broker_journal.py`.
4. **M12-3: Shadow Broker Engine & Execution Simulator**:
   - `src/drift/shadow/broker.py`: Order validation, eligibility gating, fill generation, cost calculation, and M2 kernel integration.
   - Unit tests in `tests/unit/test_shadow_broker_engine.py`.
5. **M12-4: Accounting Reconciliation & Replay Projection**:
   - `src/drift/shadow/reconciler.py`: Reconciles broker state with `PortfolioStateV2` and proves journal replay determinism.
   - Unit tests in `tests/unit/test_shadow_broker_reconciliation.py`.
6. **M12-5: Adversarial Acceptance Suite**:
   - `tests/adversarial/test_m12_shadow_broker_adversarial.py`: Short-sale rejection, ineligible asset rejection, cash exhaustion, unadjusted price enforcement, and journal replay bit-exactness.

---

## 5. Standard Verification Commands

```bash
uv run pytest tests/unit/test_shadow_broker*.py tests/adversarial/test_m12_shadow_broker_adversarial.py
uv run ruff check src/drift/shadow tests/unit/test_shadow_broker*.py tests/adversarial/test_m12_shadow_broker_adversarial.py
```
