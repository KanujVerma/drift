# Milestone M13: Deterministic Hard Risk Design Specification

**Status:** APPROVED
**Milestone:** M13 (Deterministic Hard Risk)
**Owner:** Krish (`workstream:krish`)
**Parent Issue:** #21
**Date:** 2026-10-10

---

## 1. Executive Summary & Problem Statement

Milestone M13 enforces deterministic, non-negotiable risk boundaries that operate strictly outside the control of any strategy, heuristic, or AI agent.

In autonomous trading systems, automated agents and statistical models can suffer from specification errors, regime shifts, feedback loops, or software defects. Without rigid, hard-coded limits that evaluate every intent before routing to execution, rogue orders can cause catastrophic capital loss, margin violations, or market abuse.

Milestone M13 provides:
1. **Hard Risk Gatekeeper**: Deterministic validation of all order intents prior to submission to execution;
2. **Persistent Kill Switch**: System-wide and account-level latching kill switches stored in durable SQLite storage, trip-able by threshold breach or manual operator command;
3. **Three-Layer Tradability Separation**: Clean isolation between market execution eligibility (M12), risk permissions (M13), and broker account capabilities (M14/M16);
4. **Position & Exposure Caps**: Strict single-name concentration caps and gross portfolio exposure limits;
5. **Drawdown Circuit Breakers**: Intra-session loss limits and trailing peak-to-trough portfolio drawdown stops;
6. **Order Frequency & Size Throttling**: Strict bounds on maximum order notional, maximum share size, and order submission frequency.

---

## 2. Core Invariants & Boundaries

1. **Autonomous Separation**: The risk gatekeeper runs outside the strategy agent's loop. The agent cannot modify, relax, bypass, or override risk rules.
2. **Fail-Closed Default**: Any indeterminate valuation, missing position price, database read failure, or unhandled exception in the risk check fails closed and rejects the order intent.
3. **Persistent Latching Kill Switch**: Once tripped, the kill switch remains active across process restarts until an explicit administrative unlock is logged in the audit journal.
4. **Pure Standard Library Math**: Risk arithmetic uses exact `Decimal` arithmetic under `decimal_context()` with zero floating-point approximation.
5. **Three-Layer Tradability Isolation**: Market execution eligibility (`MarketExecutionEligibilityV1`, M12) is verified upstream; M13 evaluates portfolio and risk policy constraints; M14/M16 evaluates broker capability constraints.
6. **Zero Em Dashes**: ASCII hyphen (-) exclusively across all code, docstrings, and documentation.

---

## 3. Data Models & Schemas

### 3.1. Risk Policy Configuration (`RiskPolicyV1`)

```python
class RiskPolicyV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    max_order_notional: CanonicalMoney
    max_order_quantity: int
    max_position_notional: CanonicalMoney
    max_position_weight_basis_points: int  # e.g., 2000 = 20% NAV
    max_gross_exposure_basis_points: int  # e.g., 10000 = 100% NAV (unlevered)
    max_session_drawdown_basis_points: int  # e.g., 300 = 3% session loss
    max_trailing_drawdown_basis_points: int  # e.g., 1000 = 10% peak drawdown
    max_orders_per_minute: int
    policy_hash: SHA256Hash
```

### 3.2. Kill Switch State (`KillSwitchStateV1`)

```python
class KillSwitchStatus(StrEnum):
    ACTIVE = "active"
    TRIPPED = "tripped"


class KillSwitchStateV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    status: KillSwitchStatus
    tripped_at: UTCDateTime | None = None
    trip_reason: NonBlankStr | None = None
    cleared_at: UTCDateTime | None = None
    clear_reason: NonBlankStr | None = None
    state_hash: SHA256Hash
```

### 3.3. Risk Assessment Verdict (`RiskVerdictV1`)

```python
class RiskVerdictStatus(StrEnum):
    ALLOWED = "allowed"
    REJECTED = "rejected"
    KILL_SWITCH_ACTIVE = "kill_switch_active"


class RiskVerdictV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    order_id: UUID7
    status: RiskVerdictStatus
    reason: NonBlankStr | None = None
    evaluated_at: UTCDateTime
    verdict_hash: SHA256Hash
```

---

## 4. Implementation Slice Plan

1. **M13-P0: Architecture & Design Specification**:
   - `docs/superpowers/specs/2026-10-10-m13-deterministic-hard-risk-design.md`: Canonical design specification.
2. **M13-1: Domain Models, Enums, and Risk Schemas**:
   - `src/drift/domain/risk.py`: `RiskPolicyV1`, `KillSwitchStateV1`, `RiskVerdictV1`, builders, content hashing.
   - Unit tests in `tests/unit/test_risk_domain.py`.
3. **M13-2: Persistent SQLite Risk Journal and Kill Switch**:
   - `src/drift/risk/journal.py`: SQLite-backed persistent risk journal storing kill switch state, limits, and verdicts with append-only triggers.
   - Unit tests in `tests/unit/test_risk_journal.py`.
4. **M13-3: Deterministic Hard Risk Gatekeeper Engine**:
   - `src/drift/risk/gatekeeper.py`: Evaluates orders against position caps, notional limits, session drawdown, and rate throttles.
   - Unit tests in `tests/unit/test_risk_gatekeeper.py`.
5. **M13-4: Shadow Broker Integration Harness**:
   - `src/drift/risk/harness.py`: Plugs `HardRiskGatekeeper` directly between strategy intent and `ShadowBroker`.
   - Unit tests in `tests/unit/test_risk_harness.py`.
6. **M13-5: Adversarial Acceptance Suite**:
   - `tests/adversarial/test_m13_hard_risk_adversarial.py`: Position limit breach, kill switch persistence across restarts, runaway order bursts, cash/notional edge breaches, and fail-closed missing price handling.

---

## 5. Standard Verification Commands

```bash
uv run pytest tests/unit/test_risk*.py tests/adversarial/test_m13_hard_risk_adversarial.py
uv run ruff check src/drift/risk tests/unit/test_risk*.py tests/adversarial/test_m13_hard_risk_adversarial.py
uv run mypy src/drift/risk tests/unit/test_risk*.py tests/adversarial/test_m13_hard_risk_adversarial.py
```
