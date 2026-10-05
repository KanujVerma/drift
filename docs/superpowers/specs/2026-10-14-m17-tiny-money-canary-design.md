# Milestone M17: Tiny-Money Canary Design Specification

- **Milestone**: M17
- **Workstream**: `workstream:krish`
- **Issue**: #324 (Parent #25)
- **Status**: Proposed
- **Author**: Krish Verma
- **Date**: 2026-10-14

---

## 1. Executive Summary

Milestone M17 implements the Tiny-Money Canary layer for minimal real-capital
operational validation of live connectivity, fill reporting, and settlement
reconciliation per ADR 0011, ADR 0013, and ADR 0014.

Per ADR 0013 (separation of build order from operational authorization order),
implementing M17 establishes the mechanical safety gates, fail-closed limit
enforcers, and audit log infrastructure without granting unearned authorization
for unconstrained live trading. The canary environment restricts order sizes to
micro-capital amounts (e.g., $1.00 - $5.00 notional, single-share allocations),
whitelisted liquid tickers, and explicit runtime authorization tokens.

---

## 2. Invariants and Architectural Boundaries

1. **Build vs. Authorization Separation**: Creating the canary execution code
   does not authorize live execution. Default mode is unauthorized and dry-run
   only. Live execution requires explicit operator authorization tokens and
   passed promotion gates.
2. **Micro-Capital Allocation Limits**: Non-negotiable hard caps on maximum
   notional per order ($5.00 default cap) and maximum cumulative canary capital
   ($25.00 default cap).
3. **Single-Share / Micro-Lot Enforcer**: Canary orders must not exceed a
   strictly bounded quantity (default `quantity == 1`).
4. **Symbol Whitelist Isolation**: Only pre-approved, highly liquid canary
   symbols are admitted for routing. All other assets are refused fail-closed.
5. **Exact Settlement Reconciliation**: Fill prices and proceeds must reconcile
   to broker cash balance delta with zero tolerance beyond recorded fees.
6. **Zero Em Dashes**: Pure ASCII hyphen (-) across all code, tests, docs, and commits.
7. **Deterministic Decimal Arithmetic**: `Decimal` precision for all money and
   shares.

---

## 3. Data Models and Contracts

### 3.1. Canary Policy Configuration (`CanaryPolicyV1`)

- `schema_version`: Literal["1"]
- `canary_authorized`: bool (default False; must be explicitly enabled)
- `max_order_notional`: CanonicalMoney (default Decimal("5.00"))
- `max_cumulative_notional`: CanonicalMoney (default Decimal("25.00"))
- `max_order_quantity`: int (default 1)
- `whitelisted_symbols`: frozenset[str] (e.g. `frozenset({"AAPL", "MSFT"})`)
- `max_slippage_bps`: int (default 50 basis points)

### 3.2. Canary Evaluation Result (`CanaryEvaluationResultV1`)

- `decision`: Literal["admitted", "refused"]
- `refusal_reasons`: tuple[str, ...]
- `order_notional`: CanonicalMoney
- `cumulative_allocated_notional`: CanonicalMoney

### 3.3. Canary Settlement Report (`CanarySettlementReportV1`)

- `report_id`: UUID7
- `intent_id`: UUID7
- `broker_order_id`: str | None
- `is_settled`: bool
- `expected_notional`: CanonicalMoney
- `actual_fill_notional`: CanonicalMoney
- `fee_amount`: CanonicalMoney
- `cash_balance_delta`: CanonicalMoney
- `reconciliation_difference`: CanonicalMoney
- `slippage_bps`: Decimal
- `evaluated_at`: UTCDateTime

---

## 4. Implementation Slice Plan

1. **M17-P0: Architecture & Design Specification** (Issue #324):
   `docs/superpowers/specs/2026-10-14-m17-tiny-money-canary-design.md`.
2. **M17-1: Canary Domain Models and Policy Configuration** (Issue #325):
   `src/drift/domain/canary.py` and `tests/unit/test_canary_domain.py`
   specifying `CanaryPolicyV1`, `CanaryEvaluationResultV1`, and
   `CanarySettlementReportV1`.
3. **M17-2: Canary Allocation Gatekeeper** (Issue #326):
   `src/drift/canary/gatekeeper.py` and `tests/unit/test_canary_gatekeeper.py`
   enforcing micro-capital limits, single-share constraints, symbol whitelisting,
   and authorization token gates.
4. **M17-3: Canary Settlement and Fill Reconciliation Grader** (Issue #327):
   `src/drift/canary/settlement.py` and `tests/unit/test_canary_settlement.py`
   evaluating execution fill slippage and exact broker cash reconciliation.
5. **M17-4: Canary Execution Orchestrator** (Issue #328):
   `src/drift/canary/orchestrator.py` and `tests/unit/test_canary_orchestrator.py`
   integrating the execution router, risk gatekeeper, broker adapter, and canary
   gatekeeper.
6. **M17-5: Adversarial Acceptance Suite for Milestone M17** (Issue #329):
   `tests/adversarial/test_m17_canary_adversarial.py` attacking unauthorized
   live activation, multi-share over-allocation, cumulative capital breaches,
   unwhitelisted tickers, slippage spikes, and settlement divergences.

---

## 5. Verification Commands

```bash
uv run pytest tests/unit/test_canary*.py tests/adversarial/test_m17_canary_adversarial.py
uv run ruff check src/drift/canary src/drift/domain/canary.py tests/unit/test_canary*.py tests/adversarial/test_m17_canary_adversarial.py
uv run mypy src/drift/canary src/drift/domain/canary.py tests/unit/test_canary*.py tests/adversarial/test_m17_canary_adversarial.py
```
