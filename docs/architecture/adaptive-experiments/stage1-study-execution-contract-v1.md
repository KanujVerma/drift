# Stage 1 Study Execution Contract v1

**Specification Version:** drift-stage1-study-execution-contract/1  
**Scope:** Stage 1 G3/G4 study artifacts, execution plans, calibration, uncertainty quantification, and canonical report serialization.  
**Predecessor References:** [Stage 1 Decisions](stage1-decisions.md), [G3 Freeze Contract](stage1-g3-freeze.md), [G3 Protocol v1](stage1-g3-protocol-v1.md).

---

## 1. Dimensional Integrity and Completion Boundaries

Execution tracking and verification in Stage 1 strictly separates distinct operational dimensions. No dimension may be collapsed into another or inferred from partial progress:

1. **IMPLEMENTED**: Code, data structures, and CLI orchestrators exist in the repository with complete type annotations and unit test coverage.
2. **TESTED**: Full automated test suites (unit, integration, adversarial) pass with zero errors, zero warnings, and clean linting under the pinned CPython 3.14.6 runtime.
3. **INDEPENDENTLY_ACCEPTED**: Evidence artifacts and receipts are signed or issued by designated independent roots (e.g., Matthew, Krish) and verified fail-closed by `ProductionStudyEvidenceVerifier`.
4. **SOURCE_QUALIFIED**: Market data and underlying time series satisfy qualification checks, admission bounds, and calendar completeness for the 12-instrument Stage 1 universe.
5. **FROZEN**: All protocol parameters, model bindings, cutoff points, and candidate seeds are immutably bound and fingerprinted via SHA-256 canonical hashing before evaluation begins.
6. **EXECUTED**: Historical or prospective simulation sessions have executed and generated verifiable execution receipts.
7. **OPERATIONALLY_AUTHORIZED**: Live operational permissions (e.g., broker dispatch, capital movement, order placement). In Stage 1, this capability is explicitly forbidden and refused.

---

## 2. Core Artifact Contracts

### 2.1 Execution Plan (`Stage1ExecutionPlanV1`)
Defines the experimental framework across development, validation, and historical evaluation periods:
- **Development Window:** 2021-01-01 to 2023-12-31 (parameter fitting allowed).
- **Validation Window:** 2024-01-01 to 2024-12-31 (held-out validation, no parameter changes).
- **Historical Evaluation Window:** 2025-01-01 to 2025-12-31 (retrospective study).
- **Cutoff Binding:** `Stage1CutoffBindingV2` immutably binds session indices and trading dates.

### 2.2 Calibration Plan & Results (`DevelopmentCalibrationPlanV1`, `CalibrationResultV1`)
- Parameter grid consists of 9 ordered pairs `(lambda_v, lambda_d)`:
  - `lambda_v in {0.5, 1.0, 1.5}`
  - `lambda_d in {0.25, 0.5, 1.0}`
- Deterministic ranking key:
  `(-terminal_net_return, absolute_maximum_drawdown, total_gross_turnover, lambda_v, lambda_d)`
- Exact 34-digit `Decimal` context with `ROUND_HALF_EVEN` arithmetic for risk-adjusted net return calculation:
  `R = G_s - lambda_v * sqrt(126) * sigma_s - lambda_d * D_s - C_s`

### 2.3 Uncertainty Quantification (`PairedUncertaintyArtifactV1`)
- Paired Politis-Romano stationary bootstrap over 10,000 replications.
- Reference random seed: `575`.
- Block length selection computed via isolated subproject worker (`tools/stage1-statistics/block_length_worker.py`) using `arch 8.0.0`.
- Exact quantile evaluation using Decimal linear interpolation at position `9999 * p`.

### 2.4 Outcome Classification (`StudyOutcomeClassificationV1`)
Strict precedence resolution:
1. `INVALID`: Missing evidence, tampered artifacts, unverified roots, or protocol violations.
2. `UNAVAILABLE`: Missing required market data or external resources.
3. `UNSUCCESSFUL`: Executed cleanly, but failed materiality hurdle or risk limits.
4. `SUCCESS`: Statistically significant primary economic advantage exceeding hurdle ($100 at 252 sessions, $200 at 504 sessions) with risk limits satisfied.
5. `PROMISING_BUT_INCONCLUSIVE`: Positive point advantage meeting hurdles, but bootstrap confidence interval crosses zero.

---

## 3. Canonical Serialization & Hash Integrity

All study artifacts inherit from `drift.domain.common.FrozenModel` with canonical JSON serialization (`drift.serialization.canonical.canonical_json`):
- All dictionaries have sorted keys.
- Numbers are formatted with canonical precision.
- Every artifact includes a SHA-256 `*_hash` field validating the exact content payload excluding the hash itself.
- Verification is fail-closed: any hash mismatch raises a validation error immediately.
