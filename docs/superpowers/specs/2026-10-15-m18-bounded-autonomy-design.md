# Milestone M18+: Bounded Autonomy & Improvement Design Specification

- **Milestone**: M18+
- **Workstream**: `workstream:krish`
- **Issue**: #336 (Parent #26)
- **Status**: Proposed
- **Author**: Krish Verma
- **Date**: 2026-10-15

---

## 1. Executive Summary

Milestone M18+ represents the open-ended operating phase of Drift, establishing
controlled live allocation expansion governed continuously by empirical statistical
evidence per ADR 0011, ADR 0013, and ADR 0014.

Unlike conventional algorithmic trading systems that rely on static allocation
parameters or unmonitored execution, Drift enforces closed-loop statistical
governance. Allocation caps expand only when live execution metrics (M17 settlement,
M15 execution drift, and M5 statistical scorecards) satisfy rigorous empirical
evidence gates, and automatically contract fail-closed upon any statistical
degradation or risk halt.

---

## 2. Invariants and Architectural Boundaries

1. **Evidence-Gated Tier Expansion**: Allocation tiers cannot advance without
   verified minimum session thresholds, passing statistical scorecards, acceptable
   execution drift, and 100% clean settlement reconciliation.
2. **Fail-Closed Automatic Contraction**: Any hard risk event, kill switch trip,
   or statistical degradation triggers immediate demotion of allocation tiers.
3. **Cryptographically Chained Audit Ledger**: Every governance decision, tier
   transition, and allocation change is persisted to an append-only SQLite ledger
   with SHA-256 hash chaining and SQL append-only triggers.
4. **Research-Production Separation**: The governance engine consumes standardized
   evidence models without embedding proprietary broker APIs or model internals
   (ADR 0002, ADR 0004).
5. **Zero Em Dashes**: Pure ASCII hyphen (-) across all code, tests, docs, and commits.
6. **Deterministic Decimal Arithmetic**: `Decimal` precision for all money and
   shares.

---

## 3. Allocation Tiers and Data Models

### 3.1. Operational Allocation Tiers (`AutonomyTier`)

- `TIER_0_CANARY`: Micro-canary ($5 max order, $25 cumulative, 1 share).
- `TIER_1_MICRO`: Micro-live ($25 max order, $100 cumulative, 5 shares).
- `TIER_2_SMALL`: Small-live ($100 max order, $500 cumulative, 20 shares).
- `TIER_3_BOUNDED`: Bounded operating ($500 max order, $2,500 cumulative, 50 shares).

### 3.2. Tier Transition Record (`GovernanceTransitionV1`)

- `event_id`: UUID7
- `previous_tier`: AutonomyTier
- `target_tier`: AutonomyTier
- `transition_type`: Literal["promotion", "demotion", "hold"]
- `trigger_reason`: NonBlankStr
- `scorecard_summary`: Mapping[str, Any]
- `chain_hash`: SHA256Hash
- `evaluated_at`: UTCDateTime

---

## 4. Implementation Slice Plan

1. **M18-P0: Architecture & Design Specification** (Issue #336):
   `docs/superpowers/specs/2026-10-15-m18-bounded-autonomy-design.md`.
2. **M18-1: Autonomy Domain Models and Tier Schemas** (Issue #337):
   `src/drift/domain/autonomy.py` and `tests/unit/test_autonomy_domain.py`
   specifying `AutonomyTier`, `GovernanceTransitionV1`, and tier cap tables.
3. **M18-2: Audited Evidence Ledger with Append-Only Triggers** (Issue #338):
   `src/drift/autonomy/ledger.py` and `tests/unit/test_autonomy_ledger.py`
   providing persistent SQLite storage with cryptographic hash chaining and
   SQL append-only triggers.
4. **M18-3: Dynamic Allocation Expansion Governor** (Issue #339):
   `src/drift/autonomy/governor.py` and `tests/unit/test_autonomy_governor.py`
   evaluating statistical scorecards and execution drift to manage tier expansion
   and contraction.
5. **M18-4: Bounded Autonomy Orchestrator** (Issue #340):
   `src/drift/autonomy/orchestrator.py` and `tests/unit/test_autonomy_orchestrator.py`
   integrating the governor, ledger, risk gatekeeper, and execution pipeline.
6. **M18-5: Adversarial Acceptance Suite for Milestone M18+** (Issue #341):
   `tests/adversarial/test_m18_bounded_autonomy_adversarial.py` testing
   premature promotion attacks, statistical degradation contraction, kill switch
   freezes, drift demotions, and ledger tampering attacks.

---

## 5. Verification Commands

```bash
uv run pytest tests/unit/test_autonomy*.py tests/adversarial/test_m18_bounded_autonomy_adversarial.py
uv run ruff check src/drift/autonomy src/drift/domain/autonomy.py tests/unit/test_autonomy*.py tests/adversarial/test_m18_bounded_autonomy_adversarial.py
uv run mypy src/drift/autonomy src/drift/domain/autonomy.py tests/unit/test_autonomy*.py tests/adversarial/test_m18_bounded_autonomy_adversarial.py
```
