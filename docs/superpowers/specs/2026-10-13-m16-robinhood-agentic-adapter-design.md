# Milestone M16: Official Robinhood Agentic MCP Adapter Design Specification

- **Milestone**: M16
- **Workstream**: `workstream:krish`
- **Issue**: #314 (Parent #24)
- **Status**: Proposed
- **Author**: Krish Verma
- **Date**: 2026-10-13

---

## 1. Executive Summary

Milestone M16 provides the official live brokerage adapter connecting Drift's
broker-neutral execution layer (M14) to Robinhood's Agentic Trading protocol per
ADR 0011.

Drift forbids unofficial private APIs, scraping, or browser automation. Execution
relies entirely on official Model Context Protocol (MCP) tool schemas and APIs
designed for autonomous agent accounts. Core research, backtesting, and risk
engines retain zero dependency on Robinhood protocols, formats, or credentials.

---

## 2. Invariants and Architectural Boundaries

1. **Broker-Neutral Core Preservation**: The adapter implements `BrokerAdapterProtocol`
   from `drift.execution.adapter`. No Robinhood types or concepts leak into strategy,
   portfolio accounting, or risk models (ADR 0002, ADR 0011).
2. **Offline-First & Mock Transport**: All CI tests and offline simulations execute
   against `MockRobinhoodMcpTransport` without requiring external network connectivity
   or live credentials.
3. **Dry-Run Safety Mode**: Default mode is `dry_run=True`. Real order transmission
   requires explicit runtime opt-in and is subject to authorization gates (ADR 0013).
4. **Idempotency Token Mapping**: Robinhood client order tokens map deterministically
   from Drift `client_order_id` / `intent_id`. Re-transmissions cannot double-execute.
5. **Fail-Closed Error Handling**: Unrecognized responses, network drops, or rejected
   orders map to `ExecutionStatus.REJECTED` or fail-closed exceptions.
6. **Zero Em Dashes**: Pure ASCII hyphen (-) across all code, tests, docs, and commits.
7. **Pure Standard-Library Math**: `Decimal` precision for all money and share quantities.

---

## 3. Data Models and Configurations

### 3.1. Adapter Configuration (`RobinhoodAgenticConfigV1`)

- `account_id`: NonBlankStr (Robinhood agentic account identifier)
- `dry_run`: bool (defaults to True)
- `request_timeout_seconds`: float = 10.0
- `max_retries`: int = 3
- `symbol_map`: Mapping[UUID, str] (maps Drift security UUIDs to market tickers)

### 3.2. Robinhood MCP Transport Protocol (`RobinhoodMcpTransportProtocol`)

Specifies the low-level JSON-RPC / MCP tool call methods:
- `call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]`

Official MCP tools modeled:
- `robinhood_place_order(symbol, side, quantity, order_type, limit_price, client_token)`
- `robinhood_cancel_order(order_id)`
- `robinhood_get_order(order_id)`
- `robinhood_get_account()`
- `robinhood_get_positions()`

---

## 4. Implementation Slice Plan

1. **M16-P0: Architecture & Design Specification** (Issue #314):
   `docs/superpowers/specs/2026-10-13-m16-robinhood-agentic-adapter-design.md`.
2. **M16-1: Configuration Models and MCP Transport Protocol** (Issue #315):
   `src/drift/adapters/robinhood/config.py` and `src/drift/adapters/robinhood/transport.py`
   specifying `RobinhoodAgenticConfigV1`, `RobinhoodMcpTransportProtocol`, and `MockRobinhoodMcpTransport`.
3. **M16-2: Official Robinhood Agentic Broker Adapter** (Issue #316):
   `src/drift/adapters/robinhood/adapter.py` implementing `BrokerAdapterProtocol` with
   order translation, status mapping, and dry-run protection.
4. **M16-3: Account Snapshot and Position Synchronizer** (Issue #317):
   `src/drift/adapters/robinhood/sync.py` polling and transforming Robinhood balances and
   positions into canonical `BrokerAccountSnapshotV1` and `BrokerPositionSnapshotV1`.
5. **M16-4: Adversarial Acceptance Suite for Robinhood Adapter** (Issue #318):
   `tests/adversarial/test_m16_robinhood_adapter_adversarial.py` testing dry-run enforcement,
   rate-limit 429 throttling, malformed tool outputs, network timeout recovery, and
   duplicate client token idempotency.

---

## 5. Verification Commands

```bash
uv run pytest tests/unit/test_robinhood*.py tests/adversarial/test_m16_robinhood_adapter_adversarial.py
uv run ruff check src/drift/adapters/robinhood tests/unit/test_robinhood*.py tests/adversarial/test_m16_robinhood_adapter_adversarial.py
uv run mypy src/drift/adapters/robinhood tests/unit/test_robinhood*.py tests/adversarial/test_m16_robinhood_adapter_adversarial.py
```
