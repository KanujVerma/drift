# Milestone M8 Design Specification: Recursive R&D Loop

- **Status**: Accepted
- **Author**: Krish
- **Workstream**: `workstream:krish`
- **Parent Issue**: #15
- **Architecture Issue**: #229
- **Date**: 2026-10-06

---

## 1. Executive Summary and Problem Statement

Milestone M7 deployed the First AI Research Agent, enabling autonomous formulation of scientifically grounded hypothesis proposals and experiment specifications under deterministic validation gatekeeping. However, single-shot proposal generation does not constitute research. Quantitative research is inherently an iterative, recursive feedback loop:

1. An agent formulates a hypothesis conditioned on current historical memory.
2. The proposal is evaluated through deterministic simulation and statistical scoring.
3. The empirical evaluation results are diagnosed for alpha decay, turnover drag, drawdown breach, or parameter sensitivity.
4. Failure modes are captured as formal postmortems, sealing forbidden variations into memory.
5. Successes establish new benchmark baselines and expand search frontier coverage.
6. The agent inspects these postmortems and performance distributions to propose targeted, non-redundant refinements in the next iteration.

Milestone M8 closes this cycle by establishing the **Recursive R&D Loop**. The recursive loop automates the pipeline from hypothesis generation to empirical execution, scorecard evaluation, postmortem diagnosis, memory ledger sealing, and feedback-conditioned re-prompting.

---

## 2. Trust Boundaries and Authorization Invariants

Per `docs/architecture/trust-boundaries.md`, ADR 0012, and ADR 0014:

1. **Strictly Exploratory Lane**: The recursive R&D loop operates solely in the exploratory research lane. All artifacts, trials, iterations, and scorecards produced are non-promotable exploratory evidence.
2. **Zero Live Execution Authority**: The recursive loop cannot connect to brokers, route live orders, manage capital, or execute real-world trades.
3. **Fail-Closed Stop Conditions**: The loop cannot run indefinitely. It requires deterministic, hard termination bounds:
   - Maximum iteration count ($N_{\max}$);
   - Consecutive falsification limit ($F_{\max}$);
   - Search space exhaustion threshold ($\eta \ge \eta_{\text{target}}$);
   - Target performance threshold achievement (early exit on superior validated alpha).
4. **Pure Standard Library Math**: Core metrics, thresholds, and statistics must use standard library math (`Decimal`, `math`, `statistics`). Zero numpy/scipy runtime dependencies.
5. **Append-Only Auditability**: Every loop iteration and overall loop execution summary must be sealed into the M0 SQLite ledger as tamper-evident audit events (`m8.iteration.completed`, `m8.loop.completed`).

---

## 3. High-Level System Architecture

```
+------------------------------------------------------------------------------------+
|                                    RECURSIVE R&D LOOP                              |
|                                                                                    |
|   +----------------------------------------------------------------------------+   |
|   | 1. CONTEXT SYNTHESIS (M7)                                                  |   |
|   |    Archive -> Synthesizer -> ResearchContextPacketV1 (Trial count K,       |   |
|   |    Sharpe distribution, falsified summaries, forbidden variations)         |   |
|   +----------------------------------------------------------------------------+   |
|                                         |                                          |
|                                         v                                          |
|   +----------------------------------------------------------------------------+   |
|   | 2. AGENT HYPOTHESIS PROPOSAL (M7)                                          |   |
|   |    ResearchAgentProtocol -> (HypothesisProposalV1,                         |   |
|   |                              ExperimentSpecificationProposalV1)            |   |
|   +----------------------------------------------------------------------------+   |
|                                         |                                          |
|                                         v                                          |
|   +----------------------------------------------------------------------------+   |
|   | 3. GATEKEEPER VALIDATION (M7)                                              |   |
|   |    ProposalValidator: Check duplicate params, forbidden variations,       |   |
|   |    search space bounds, minimum stringency -> ProposalValidationResultV1  |   |
|   +----------------------------------------------------------------------------+   |
|                                         |                                          |
|                     [Accepted]          |          [Rejected]                      |
|                         +---------------+---------------+                          |
|                         |                               |                          |
|                         v                               v                          |
|   +---------------------------------------+  +---------------------------------+   |
|   | 4. EVALUATION & SCORECARDS (M2/M3/M5) |  | 4b. RECORD VALIDATION REJECTION |   |
|   |    Run evaluation -> StrategyScorecard|  |     Log reason -> Record in     |   |
|   |    Calculate Sharpe, Drawdown, Turn   |  |     iteration state             |   |
|   +---------------------------------------+  +---------------------------------+   |
|                         |                               |                          |
|                         v                               |                          |
|   +---------------------------------------+             |                          |
|   | 5. OUTCOME & POSTMORTEM DIAGNOSIS (M6)|             |                          |
|   |    Compare metrics vs Falsification   |             |                          |
|   |    criteria -> SUPERIOR/NEUTRAL/FAILED|             |                          |
|   |    If Failed -> FailurePostmortemV1   |             |                          |
|   +---------------------------------------+             |                          |
|                         |                               |                          |
|                         v                               v                          |
|   +----------------------------------------------------------------------------+   |
|   | 6. M0 LEDGER SEALING (M6/M8)                                               |   |
|   |    ResearchMemoryRecorder.record_trial() / record_postmortem()             |   |
|   |    Seal `m8.iteration.completed` audit event                               |   |
|   +----------------------------------------------------------------------------+   |
|                                         |                                          |
|                                         v                                          |
|   +----------------------------------------------------------------------------+   |
|   | 7. STOP CONDITION EVALUATION & NEXT ITERATION DECISION                     |   |
|   |    Check max_iterations, consecutive_failures, exhaustion                  |   |
|   |    If continuing -> Loop back to Step 1 with updated memory!               |   |
|   +----------------------------------------------------------------------------+   |
+------------------------------------------------------------------------------------+
```

---

## 4. Domain Models and Ledger Schemas

### 4.1. Loop Configuration: `ResearchLoopConfigV1`

```python
class ResearchLoopConfigV1(FrozenModel):
    """Configuration governing recursive research loop execution."""

    schema_version: Literal["1"] = "1"
    loop_id: UUID7
    target_strategy_type: NonBlankStr
    max_iterations: int = Field(default=10, ge=1, le=100)
    max_consecutive_failures: int = Field(default=5, ge=1, le=20)
    target_annualized_sharpe: Decimal | None = None
    target_exhaustion_fraction: Decimal = Field(default=Decimal("0.90"), ge=Decimal("0.1"), le=Decimal("1.0"))
    stop_on_target_met: bool = True
    created_at: UTCDateTime
    config_hash: SHA256Hash
```

### 4.2. Iteration Record: `ResearchIterationRecordV1`

```python
class IterationStatus(StrEnum):
    PROPOSAL_ACCEPTED = "proposal_accepted"
    PROPOSAL_REJECTED = "proposal_rejected"
    EVALUATION_COMPLETED = "evaluation_completed"
    EVALUATION_FAILED = "evaluation_failed"


class ResearchIterationRecordV1(FrozenModel):
    """Detailed immutable execution record of a single R&D loop iteration."""

    schema_version: Literal["1"] = "1"
    iteration_id: UUID7
    loop_id: UUID7
    iteration_index: int = Field(ge=0)
    status: IterationStatus
    hypothesis_proposal_id: UUID7 | None = None
    experiment_proposal_id: UUID7 | None = None
    validation_status: ProposalValidationStatus
    trial_outcome: TrialOutcome | None = None
    annualized_sharpe: Decimal | None = None
    max_drawdown: Decimal | None = None
    annualized_turnover: Decimal | None = None
    failure_category: FailureCategory | None = None
    postmortem_id: UUID7 | None = None
    rejection_reasons: tuple[str, ...] = ()
    started_at: UTCDateTime
    completed_at: UTCDateTime
    iteration_hash: SHA256Hash
```

### 4.3. Loop Execution Summary: `ResearchLoopSummaryV1`

```python
class LoopTerminationReason(StrEnum):
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    MAX_CONSECUTIVE_FAILURES = "max_consecutive_failures"
    TARGET_PERFORMANCE_MET = "target_performance_met"
    SEARCH_SPACE_EXHAUSTED = "search_space_exhausted"
    UNEXPECTED_ERROR = "unexpected_error"


class ResearchLoopSummaryV1(FrozenModel):
    """Final outcome summary of a recursive R&D loop execution run."""

    schema_version: Literal["1"] = "1"
    loop_id: UUID7
    config_hash: SHA256Hash
    termination_reason: LoopTerminationReason
    total_iterations: int = Field(ge=0)
    accepted_proposals: int = Field(ge=0)
    rejected_proposals: int = Field(ge=0)
    validated_trials: int = Field(ge=0)
    falsified_trials: int = Field(ge=0)
    best_trial_id: UUID7 | None = None
    best_annualized_sharpe: Decimal | None = None
    final_exhaustion_fraction: Decimal = Decimal("0.0")
    started_at: UTCDateTime
    completed_at: UTCDateTime
    summary_hash: SHA256Hash
```

### 4.4. Ledger Audit Event Payloads

1. `m8.iteration.completed`: Sealed at the end of each iteration containing `ResearchIterationRecordV1`.
2. `m8.loop.completed`: Sealed at loop termination containing `ResearchLoopSummaryV1`.

---

## 5. Failure Diagnosis and Automatic Postmortem Generation

When a trial is evaluated, its metrics are compared against the hypothesis's declared falsification criteria:
- If `realized_sharpe < min_annualized_sharpe`: Diagnosed as `NEGATIVE_ALPHA` or `CALIBRATION_FAILURE`.
- If `realized_drawdown > max_drawdown_limit`: Diagnosed as `DRAWDOWN_BREACH`.
- If `realized_turnover > max_turnover_limit`: Diagnosed as `TURNOVER_DRAG`.

The loop automatically formulates a structured `FailurePostmortemV1`:
- Sets `failure_category` to the primary diagnosed root cause;
- Formulates `root_cause_summary` detailing numeric breaches;
- Extracts exact parameter values to record as `forbidden_variations` (e.g. `lookback_days: 15`);
- Seals the postmortem into M6 memory, ensuring subsequent agent iterations will receive it as context and ProposalValidator will prevent repeat trials.

---

## 6. Implementation Slice Plan

Milestone M8 will be executed across the following bounded child slices:

1. **M8-1: Domain Models, Schemas, and Audit Payloads**:
   - `src/drift/domain/research_loop.py`: `ResearchLoopConfigV1`, `ResearchIterationRecordV1`, `ResearchLoopSummaryV1`, `IterationStatus`, `LoopTerminationReason`.
   - Content hashing and immutable Pydantic v2 schemas.
   - Unit tests in `tests/unit/test_research_loop_domain.py`.

2. **M8-2: Trial Evaluator Adapter and Diagnosis Engine**:
   - `src/drift/loop/evaluator_adapter.py`: Bridge from experiment proposal parameters to deterministic simulation and metric extraction.
   - `src/drift/loop/diagnosis.py`: Automated failure categorization and postmortem builder.
   - Unit tests in `tests/unit/test_research_loop_diagnosis.py`.

3. **M8-3: Recursive R&D Loop Controller and Runner**:
   - `src/drift/loop/runner.py`: `ResearchLoopRunner`.
   - Orchestrates iterative synthesis -> proposal -> validation -> evaluation -> diagnosis -> memory sealing -> stop condition evaluation.
   - Unit tests in `tests/unit/test_research_loop_runner.py`.

4. **M8-4: M0 Ledger Sealing and Audit Trail Integration**:
   - Event types `m8.iteration.completed` and `m8.loop.completed`.
   - Historical loop reconstruction and query engine in `src/drift/loop/archive.py`.
   - Unit tests in `tests/unit/test_research_loop_audit.py`.

5. **M8-5: Adversarial Acceptance Suite and Boundary Verification**:
   - `tests/adversarial/test_m8_research_loop_adversarial.py`:
     - Runaway iteration prevention (strict $N_{\max}$ stop);
     - Consecutive failure circuit breaker triggering;
     - Memory feedback cycle verification (agent never repeats falsified parameter variation);
     - Audit event tamper detection;
     - Fail-closed evaluation under unexpected errors.

---

## 7. Quality Gates and Verification Commands

```bash
uv run pytest tests/unit/test_research_loop*.py tests/adversarial/test_m8_research_loop_adversarial.py
uv run ruff check src/drift/loop tests/unit/test_research_loop*.py
uv run ruff format --check src/drift/loop tests/unit/test_research_loop*.py
uv run mypy src/drift/loop tests/unit/test_research_loop*.py
git diff --check
```
