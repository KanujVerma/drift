# Drift M6: Structured Research Memory Architecture Design Specification

Date: 2026-10-04.
Status: Canonical architecture design specification for Drift M6 (incorporating external architectural rulings and dependency mappings).
Canonical Baseline: Commit `ff6c978` (Milestones M0 through M5 complete and verified).
Related Architecture Decisions: [ADR 0001](../../adr/0001-evidence-first-architecture.md), [ADR 0003](../../adr/0003-append-only-research-ledger.md), [ADR 0004](../../adr/0004-research-production-separation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), [ADR 0014](../../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).
Related Issues: Parent Issue #13.

---

## 1. Objective and Scientific Mission

Milestone M6 establishes the Structured Research Memory for Drift: an auditable, queryable, and immutable historical archive of research hypotheses, parameter trials, search space frontiers, and failure postmortems.

In quantitative financial machine learning and autonomous agent research, ungrounded exploration suffers from severe structural failure modes:
1. **Circular Exploration and Zombie Hypotheses:** Researchers and autonomous AI agents repeatedly test variants of already-falsified economic mechanisms (e.g., re-inventing simple technical momentum without transaction costs, or repeatedly proposing unhedged small-cap illiquidity bets);
2. **Untracked Multiple-Testing Search Inflation:** To properly compute the Deflated Sharpe Ratio (DSR per Bailey & Lopez de Prado 2014) and multiple-testing adjustments (M5 / M11), the system must know the exact number of historical trial variations ($K$) and their cross-trial return variance across the search space;
3. **Loss of Negative Knowledge:** Failed experiments are routinely discarded or unindexed, destroying critical negative knowledge about structural market regimes, turnover drag, and failure modes;
4. **Lack of Parameter Search Frontier Tracking:** Without structured memory, parameter exploration cannot systematically identify explored versus unexplored hyperparameter regions or prevent redundant backtests.

M6 provides a tamper-evident, append-only research memory kernel that:
1. **Catalogs Research Hypotheses & Lifecycles:** Tracks formal research claims, explicit parent-child derivation lineage, and verified falsification status (`PROPOSED`, `ACTIVE`, `VALIDATED`, `FALSIFIED`, `ABANDONED`);
2. **Archives Full Research Trials:** Records every evaluated experiment configuration, parameter set, headline performance metrics, and linked M5 scorecards;
3. **Structured Failure Postmortems:** Captures standardized postmortems for rejected trials (categorizing failure causes such as turnover drag, negative alpha, drawdown breaches, tail calibration failures, and overfitting rejections);
4. **Search Space & Exploration Frontier Tracking:** Maps explored parameter spaces, tracks trial counts $K$ and metric distributions for multiple-testing corrections, and flags forbidden parameter regions;
5. **Deterministic Query & Retrieval Interface:** Exposes a fast, deterministic SQL/in-memory query interface over SQLite ledgers, allowing downstream AI research agents (M7/M8) and overfitting gates (M11) to inspect historical evidence before proposing new experiments.

---

## 2. Scope and Domain Boundaries

### 2.1 Admitted Scope (V1)
- **Inputs Consumed:**
  - `Hypothesis` domain model (M0);
  - `ExperimentSpecification` and `ExperimentRun` (M0);
  - `EvaluationResultV1` and `EvaluationSummaryMetricsV1` (M2/M3);
  - `PredictionScorecardV1`, `StrategyScorecardV1`, and `ModelScorecardV1` (M5);
  - `MultipleTestingSummaryV1` (M5).
- **Core Domain Entities (`src/drift/domain/research_memory.py`):**
  - `HypothesisLifecycleV1`: Immutable hypothesis record tracking status transitions and falsification evidence;
  - `ResearchTrialRecordV1`: Compact trial summary binding experiment specification, parameters, headline metrics, linked scorecards, and trial outcome;
  - `FailureCategory`: Strict enumeration of structural failure causes;
  - `FailurePostmortemV1`: Standardized failure postmortem with root causes, lessons learned, and forbidden variation constraints;
  - `ParameterSearchSpaceV1`: Explicit declaration of hyperparameter search dimensions, explored coordinates, and exhaustion metrics;
  - `ResearchMemoryQueryV1`: Structured query specification for memory retrieval.
- **Ledger Audit Events (`src/drift/memory/recorder.py`):**
  - `m6.trial.recorded`: Sealed record of an evaluated trial;
  - `m6.postmortem.recorded`: Sealed record of a failure postmortem;
  - `m6.hypothesis_state.updated`: Sealed record of a hypothesis lifecycle change.
- **Query & Retrieval Engine (`src/drift/memory/archive.py`):**
  - High-performance SQLite query engine retrieving past trials, trial counts $K$, parameter distributions, similar prior experiments, and failure postmortems.

### 2.2 Excluded Scope (V1 Hard Boundaries)
- **No Direct LLM Prompting:** M6 provides the deterministic structured data layer; LLM prompting, agent reasoning loops, and prompt templates belong to M7.
- **No Automated Execution:** M6 does not place orders, trade, or connect to brokerage accounts.
- **No Vector Embeddings in Production Core:** All retrieval in M6 V1 is deterministic, exact-hash, SQL-indexed, and relational. Unreproducible floating-point neural embeddings are not used in M6 deterministic verification.
- **No Evidence Laundering:** Exploratory research memory cannot be promoted or converted to promotion-grade status (ADR 0012).

---

## 3. Domain Model Architecture

### 3.1 Hypothesis Lifecycle States
```python
class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"  # Newly formulated, unexecuted
    ACTIVE = "active"  # Under current evaluation
    VALIDATED = (
        "validated"  # Survived empirical evaluation and multiple-testing thresholds
    )
    FALSIFIED = "falsified"  # Met pre-registered falsification criteria
    ABANDONED = (
        "abandoned"  # Retired due to structural invalidity or superseded mechanism
    )
```

### 3.2 Failure Categories
```python
class FailureCategory(StrEnum):
    TURNOVER_DRAG = "turnover_drag"  # Alpha consumed by costs/fees
    NEGATIVE_ALPHA = "negative_alpha"  # Information coefficient <= 0
    DRAWDOWN_BREACH = "drawdown_breach"  # Exceeded acceptable drawdown bounds
    CALIBRATION_FAILURE = (
        "calibration_failure"  # Severe probability miscalibration (high ECE/Brier)
    )
    OVERFITTING_REJECTION = (
        "overfitting_rejection"  # Rejected by DSR / multiple-testing penalty
    )
    DATA_DEFECT = "data_defect"  # Delisting bias, unallocated basis, or missing data
    EXECUTION_UNVIABLE = "execution_unviable"  # Excessive market impact or illiquidity
```

### 3.3 Research Trial Records
Each execution of an experiment specification yields an immutable `ResearchTrialRecordV1`:
- `trial_id`: UUID7 unique identifier;
- `hypothesis_id`: UUID7 reference to underlying research claim;
- `experiment_id`: UUID7 reference to experiment specification;
- `run_id`: UUID7 reference to evaluator run;
- `scorecard_id`: UUID7 reference to M5 scorecard;
- `strategy_type`: Normalized string strategy classification;
- `parameters`: Immutable frozen JSON parameter mapping;
- `parameters_hash`: SHA-256 canonical hash of parameter payload;
- `headline_metrics`: Standardized key-metric dictionary (Sharpe, annualized return, max drawdown, mean IC, Brier score);
- `trial_outcome`: Classification (`SUPERIOR`, `NEUTRAL`, `INFERIOR`, `FAILED`, `INVALIDATED`);
- `postmortem_id`: Optional UUID7 reference if trial produced a failure postmortem;
- `created_at`: UTC timestamp;
- `trial_hash`: SHA-256 hash sealing the entire record.

---

## 4. Query & Retrieval Interface

The `ResearchMemoryArchive` provides deterministic query operations:
1. `get_trial_count(hypothesis_id: UUID | None = None) -> int`:
   Returns total trial count $K$, essential for Bailey & Lopez de Prado DSR multiple-testing adjustment;
2. `get_trial_sharpe_distribution(hypothesis_id: UUID | None = None) -> list[Decimal]`:
   Returns the complete empirical distribution of trial Sharpe ratios to compute expected maximum null Sharpe;
3. `find_falsified_hypotheses(tags: tuple[str, ...] = ()) -> list[HypothesisLifecycleV1]`:
   Enables M7 research agents to filter out already-falsified research claims before proposing experiments;
4. `get_postmortems_by_category(category: FailureCategory) -> list[FailurePostmortemV1]`:
   Retrieves structured failure postmortems and lessons learned;
5. `is_parameter_region_evaluated(strategy_type: str, parameters_hash: str) -> bool`:
   Checks if an exact parameter configuration has already been executed;
6. `get_parameter_search_frontier(strategy_type: str) -> list[ParameterSearchSpaceV1]`:
   Reports coverage and bounds across explored parameter dimensions.

---

## 5. Implementation Slices and Roadmap Breakdown

The execution of Milestone M6 is structured into discrete, test-driven slices:

- **M6-P0: Architecture Preparation and Design Specification (This Document)**
  - Establish canonical design specification in `docs/superpowers/specs/2026-10-04-m6-structured-research-memory-design.md`.
- **M6-1: Research Memory Domain Models and Ledger Schemas**
  - Implement `src/drift/domain/research_memory.py` (`HypothesisLifecycleV1`, `ResearchTrialRecordV1`, `FailurePostmortemV1`, `ParameterSearchSpaceV1`, `FailureCategory`).
  - Implement serialization, content hashing, and validation unit tests.
- **M6-2: Research Trial Recorder and M0 Ledger Sealing Engine**
  - Implement `src/drift/memory/recorder.py` (`ResearchMemoryRecorder`).
  - Wire transactional sealing of `m6.trial.recorded`, `m6.postmortem.recorded`, and `m6.hypothesis_state.updated` audit events.
- **M6-3: Structured Failure Postmortem and Falsification Engine**
  - Implement automated postmortem extraction from failing M5 scorecards.
  - Implement hypothesis lifecycle tracking (`HypothesisManager`).
- **M6-4: Query and Retrieval Archive Engine**
  - Implement `src/drift/memory/archive.py` (`ResearchMemoryArchive`).
  - Provide SQL-indexed trial search, trial count $K$ extraction, Sharpe distribution aggregation, and duplicate parameter detection.
- **M6-5: Adversarial Acceptance Suite for Structured Research Memory**
  - Implement `tests/adversarial/test_m6_research_memory_adversarial.py`.
  - Attack test coverage: bit-flip hash tampering, duplicate trial deduplication, circular hypothesis lineage rejection, SQLite ledger event tampering, empty archive fail-closed query safety, and selection bias trial accounting.
- **M6-6: Milestone M6 Completion and Roadmap Reconciliation**
  - Documentation reconciliation, parent Issue #13 closure, advance active milestone to M7.

---

## 6. Verification and Invariant Contract

1. **Zero Em Dashes:** The Unicode em dash (U+2014) is strictly forbidden across all code, docstrings, markdown files, and commit messages. Use ASCII hyphen (-) exclusively.
2. **Determinism and Purity:** Pure Python standard library math and standard SQLite operations without floating-point neural vector dependencies in production core.
3. **Non-Promotable Exploratory Boundary:** Memory records generated from exploratory runs carry `lane="exploratory"` and cannot be upgraded to promotion-grade status (ADR 0012).
4. **Append-Only Immutability:** Research memory records once written cannot be updated or deleted; updates create new causal events linked to parent IDs.
