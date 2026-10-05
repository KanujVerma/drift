# Milestone M14: Broker-Neutral Execution Design Specification

**Status:** APPROVED
**Milestone:** M14 (Broker-Neutral Execution)
**Owner:** Krish (`workstream:krish`)
**Parent Issue:** #22
**Date:** 2026-10-11

---

## 1. Executive Summary & Problem Statement

Milestone M14 provides the abstract execution protocol, order-intent journaling, and broker routing layer that decouples Drift's research, portfolio construction, and risk models from vendor-specific brokerage APIs.

Per ADR 0002 (Broker-Neutral Core) and ADR 0011 (Official Robinhood Agentic MCP Behind Broker-Neutral Execution), core research models must never import, link, or depend upon broker client libraries, credentials, or proprietary protocols. When live execution is validated in M16, it connects through an adapter behind this broker-neutral interface.

Milestone M14 provides:
1. **Abstract Order Intent Models**: Immutable, vendor-neutral representations of order desires (`OrderIntentV1`) with cryptographic content hashing;
2. **Execution Report Lifecycle Models**: Deterministic lifecycle reporting (`ExecutionReportV1`) tracking submission, acknowledgement, partial fills, full fills, cancellations, and rejections;
3. **Persistent Order Intent Journal**: SQLite-backed append-only journal storing all outbound order intents and inbound execution reports with SQL triggers preventing tampering or deletion;
4. **Broker Adapter Protocol**: A cleanly typed Python abstract protocol (`BrokerAdapterProtocol`) specifying intent submission, cancellation, account state inspection, and position queries;
5. **Deterministic Mock Adapter**: A reference broker adapter implementation (`MockBrokerAdapter`) for offline testing, paper simulation, and adversarial boundary checks;
6. **Broker-Neutral Execution Router**: An idempotent execution routing engine (`BrokerNeutralExecutionRouter`) that validates intent uniqueness, logs to the intent journal, prevents duplicate submissions, and reconciles execution state against portfolio accounting.

---

## 2. Core Invariants & Boundaries

1. **Broker Isolation (ADR 0002)**: No strategy, portfolio, or risk model may depend on or import any broker-specific API, network client, or authentication library.
2. **Deterministic Idempotency**: Every order intent possesses a unique `intent_id` (UUID7) and `client_order_id`. Re-submitting an already-submitted intent must return the existing state without creating duplicate broker orders.
3. **Append-Only Auditability**: All order intents and execution reports are recorded in an append-only SQLite journal (`PersistentOrderIntentJournal`) with SQL triggers prohibiting `UPDATE` and `DELETE`.
4. **Fail-Closed Routing**: Any unrecognized broker report status, malformed payload, or unknown intent reference fails closed and halts execution.
5. **Pure Standard Library Math**: Monetary amounts, fill prices, fees, and quantities use exact `Decimal` arithmetic under `decimal_context()`.
6. **Zero Em Dashes**: The Unicode em dash (U+2014) is strictly forbidden across all code, docstrings, and documentation. Always use the ASCII hyphen (U+002D).

---

## 3. Data Models & Schemas

### 3.1. Enums

```python
class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


class ExecutionStatus(StrEnum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
```

### 3.2. Order Intent (`OrderIntentV1`)

```python
class OrderIntentV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    intent_id: UUID7
    client_order_id: NonBlankStr
    session_key: SessionKeyV1
    security_id: UUID7
    side: OrderSide
    quantity: int = Field(gt=0)
    order_type: OrderType
    limit_price: CanonicalMoney | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    created_at: UTCDateTime
    intent_hash: SHA256Hash
```

### 3.3. Execution Report (`ExecutionReportV1`)

```python
class ExecutionReportV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    report_id: UUID7
    intent_id: UUID7
    broker_order_id: NonBlankStr | None = None
    status: ExecutionStatus
    cum_quantity: int = Field(ge=0)
    leaves_quantity: int = Field(ge=0)
    last_fill_price: CanonicalMoney | None = None
    last_fill_quantity: int | None = None
    avg_fill_price: CanonicalMoney | None = None
    fee_amount: CanonicalMoney = Decimal("0")
    rejection_reason: NonBlankStr | None = None
    reported_at: UTCDateTime
    report_hash: SHA256Hash
```

### 3.4. Account and Position Snapshots

```python
class BrokerAccountSnapshotV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    snapshot_id: UUID7
    account_id: NonBlankStr
    cash_balance: CanonicalMoney
    buying_power: CanonicalMoney
    portfolio_equity: CanonicalMoney
    as_of: UTCDateTime
    snapshot_hash: SHA256Hash


class BrokerPositionSnapshotV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    snapshot_id: UUID7
    security_id: UUID7
    quantity: int = Field(ge=0)
    cost_basis: CanonicalMoney
    current_price: CanonicalMoney | None = None
    market_value: CanonicalMoney | None = None
    as_of: UTCDateTime
    snapshot_hash: SHA256Hash
```

---

## 4. Architecture & Component Interfaces

### 4.1. Order Intent Journal (`PersistentOrderIntentJournal`)

Stores:
- `order_intents` table: stores raw payload JSON, indexed on `intent_id`, `client_order_id`, and `session_key`. Append-only triggers block `UPDATE` and `DELETE`.
- `execution_reports` table: stores raw report payload JSON, indexed on `report_id`, `intent_id`, and `broker_order_id`. Append-only triggers block `UPDATE` and `DELETE`.

### 4.2. Broker Adapter Protocol (`BrokerAdapterProtocol`)

```python
class BrokerAdapterProtocol(Protocol):
    def submit_intent(self, intent: OrderIntentV1) -> ExecutionReportV1: ...
    def cancel_intent(self, intent_id: UUID) -> ExecutionReportV1: ...
    def get_intent_status(self, intent_id: UUID) -> ExecutionReportV1 | None: ...
    def get_account_snapshot(self) -> BrokerAccountSnapshotV1: ...
    def get_positions(self) -> tuple[BrokerPositionSnapshotV1, ...]: ...
```

### 4.3. Broker-Neutral Execution Router (`BrokerNeutralExecutionRouter`)

Provides:
- `route_intent(intent: OrderIntentV1) -> ExecutionReportV1`:
  1. Checks local journal for existing `client_order_id` / `intent_id` (idempotency check).
  2. If already submitted, returns latest execution report.
  3. Records intent to `PersistentOrderIntentJournal`.
  4. Dispatches to underlying `BrokerAdapterProtocol`.
  5. Records resulting `ExecutionReportV1` to journal.
  6. Returns execution report.
- `cancel_intent(intent_id: UUID) -> ExecutionReportV1`:
  Dispatches cancellation to adapter, records report, and returns report.
- `reconcile_positions(target_state: PortfolioStateV2) -> bool`:
  Compares broker positions against canonical portfolio state holdings.

---

## 5. Implementation Slice Plan

1. **M14-P0: Architecture & Design Specification** (Issue #290):
   - `docs/superpowers/specs/2026-10-11-m14-broker-neutral-execution-design.md`: Canonical design specification.
2. **M14-1: Domain Models, Enums, and Execution Schemas**:
   - `src/drift/domain/execution.py`: `OrderSide`, `OrderType`, `TimeInForce`, `ExecutionStatus`, `OrderIntentV1`, `ExecutionReportV1`, `BrokerAccountSnapshotV1`, `BrokerPositionSnapshotV1`, builders, content hashing.
   - Unit tests in `tests/unit/test_execution_domain.py`.
3. **M14-2: Append-Only Persistent Order Intent Journal**:
   - `src/drift/execution/journal.py`: SQLite-backed `PersistentOrderIntentJournal` with SQL append-only triggers.
   - Unit tests in `tests/unit/test_execution_journal.py`.
4. **M14-3: Broker Adapter Protocol and Mock Broker Adapter**:
   - `src/drift/execution/adapter.py`: `BrokerAdapterProtocol` and deterministic `MockBrokerAdapter`.
   - Unit tests in `tests/unit/test_execution_adapter.py`.
5. **M14-4: Broker-Neutral Execution Router & Idempotency Engine**:
   - `src/drift/execution/router.py`: `BrokerNeutralExecutionRouter` with duplicate intent deduplication, journal auditing, and position reconciliation.
   - Unit tests in `tests/unit/test_execution_router.py`.
6. **M14-5: Adversarial Acceptance Suite for Broker-Neutral Execution**:
   - `tests/adversarial/test_m14_broker_neutral_adversarial.py`: Duplicate intent replay attacks, out-of-order partial fills, SQL trigger tampering, malformed report handling, and simulated network timeout recovery.

---

## 6. Standard Verification Commands

```bash
uv run pytest tests/unit/test_execution*.py tests/adversarial/test_m14_broker_neutral_adversarial.py
uv run ruff check src/drift/execution tests/unit/test_execution*.py tests/adversarial/test_m14_broker_neutral_adversarial.py
uv run mypy src/drift/execution tests/unit/test_execution*.py tests/adversarial/test_m14_broker_neutral_adversarial.py
```
