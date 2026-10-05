# Drift M7: First AI Research Agent Architecture Design Specification

Date: 2026-10-05.
Status: Canonical architecture design specification for Drift M7 (incorporating external architectural rulings, trust boundaries, and memory interfaces).
Canonical Baseline: Commit `26958ac` (Milestones M0 through M5 complete; M6 structured research memory active and implemented).
Related Architecture Decisions: [ADR 0001](../../adr/0001-evidence-first-architecture.md), [ADR 0003](../../adr/0003-append-only-research-ledger.md), [ADR 0004](../../adr/0004-research-production-separation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md), [ADR 0014](../../adr/0014-transfer-active-drift-implementation-ownership-to-krish.md).
Related Issues: Parent Issue #14, Architecture Issue #215.

---

## 1. Objective and Scientific Mission

Milestone M7 establishes the First AI Research Agent for Drift: an autonomous quantitative reasoning agent tasked with generating scientifically grounded, non-redundant economic hypotheses and formulating executable, valid experiment specifications.

In quantitative financial machine learning, unconstrained language models produce severe structural vulnerabilities when applied to alpha discovery:
1. **Hallucinatory and Non-Falsifiable Hypotheses:** LLMs routinely invent narrative explanations with vague, subjective criteria that cannot be objectively falsified by backtest data;
2. **Zombie Exploration and Duplicate Trials:** Without structured memory ingestion, agents repeatedly re-invent already-falsified strategies (e.g. unhedged momentum without turnover drag awareness) or redundantly evaluate previously explored parameter combinations;
3. **Selection Bias & Search Inflation Blindness:** Standard LLM agents are unaware of multiple-testing penalties; they evaluate dozens of parameter variations without accounting for trial cardinality $K$ or the deflation of apparent Sharpe ratios (Bailey & Lopez de Prado 2014);
4. **Execution Authority Leakage:** If research agents are granted direct access to trade execution, broker APIs, or immutable ledger writes, any agent defect or hallucination can cause unauthorized capital exposure or data corruption.

M7 resolves these challenges through a strict **evidence-gated, memory-informed research agent kernel**:
1. **Untrusted Agent Boundary:** The AI research agent operates strictly as an untrusted proposal generator outside the trusted evaluation and ledger boundary. It possesses zero execution authority, zero live market access, zero broker connectivity, and zero direct ledger write permissions;
2. **Structured Memory Conditioning:** The agent is conditioned directly on M6 `ResearchMemoryArchive` context, including trial count $K$, empirical Sharpe distribution, falsified hypotheses, known failure postmortems, and forbidden variation constraints;
3. **Strict Structured Output Schemas:** The agent emits strictly typed Pydantic models (`HypothesisProposalV1` and `ExperimentSpecificationProposalV1`) with explicit pre-registered falsification criteria;
4. **Deterministic Proposal Validation Gatekeeper:** Every generated proposal passes through a deterministic fail-closed validator that enforces parameter space limits, rejects duplicate parameter configurations, checks for circular hypothesis derivations, and blocks known forbidden variations;
5. **Pluggable Agent Interface:** The architecture abstracts the agent implementation behind a deterministic protocol, providing a bitwise-reproducible `DeterministicMockResearchAgent` for hermetic testing/CI alongside an official `GeminiResearchAgent` using Google Gemini structured JSON outputs.

---

## 2. Scope and Domain Boundaries

### 2.1 Admitted Scope (V1)
- **Inputs Consumed:**
  - M6 `ResearchMemoryArchive` (past trials, trial count $K$, Sharpe distribution, falsified hypotheses, failure postmortems, forbidden variations);
  - Admitted baseline strategy metadata (M3 baselines B0 through B5);
  - Parameter search spaces (`ParameterSearchSpaceV1`).
- **Core Domain Entities (`src/drift/domain/research_agent.py`):**
  - `ResearchContextPacketV1`: Immutable, deterministic context payload synthesized from `ResearchMemoryArchive` for agent conditioning;
  - `HypothesisProposalV1`: Formal research hypothesis proposal with pre-registered falsification criteria and rationale;
  - `ExperimentSpecificationProposalV1`: Concrete experiment configuration mapping a proposed hypothesis to strategy type, hyperparameters, universe, and evaluation parameters;
  - `ProposalValidationResultV1`: Deterministic validation report recording whether a proposal was accepted or rejected, including explicit rejection reasons;
  - `ResearchAgentRole`: Enumeration of agent personas (`ALPHA_RESEARCHER`, `RISK_CRITIC`, `PORTFOLIO_CONSTRUCTOR`).
- **Agent Interfaces & Implementations (`src/drift/agent/`):**
  - `ResearchAgentProtocol`: Abstract interface for research proposal generators;
  - `DeterministicMockResearchAgent`: Deterministic, replayable mock agent for reproducible regression testing;
  - `GeminiResearchAgent`: Production agent adapter utilizing Gemini models via structured output schemas (`response_schema`).
- **Proposal Validation Engine (`src/drift/agent/validator.py`):**
  - `ProposalValidator`: Deterministic gatekeeper enforcing:
    - Non-circular hypothesis lineage;
    - Hyperparameter search space adherence;
    - Deduplication against already evaluated configurations in `ResearchMemoryArchive`;
    - Violation check against known `FailurePostmortemV1` forbidden variations;
    - Pre-registered falsification criteria stringency (must specify valid numeric thresholds for Sharpe, drawdown, or turnover).
- **Research Agent Runner (`src/drift/agent/runner.py`):**
  - Orchestrator that queries M6 archive, constructs context packets, drives agent proposal generation, validates proposals, and upon validation, seals new hypotheses into the M0 ledger via `HypothesisManager`.

### 2.2 Excluded Scope (V1 Hard Boundaries)
- **No Broker Connections:** Zero live or simulated broker connections. Research agents have no authority to place orders or interact with market execution (ADR 0004).
- **No Automatic Promotion:** All experiments generated by the research agent run exclusively in the exploratory lane. Exploratory evidence is strictly non-promotable (ADR 0012).
- **No Direct Ledger Sealing by Agent:** The agent cannot write directly to SQLite ledgers. All ledger mutations are mediated by trusted validators and `HypothesisManager`.
- **No Unconstrained Natural Language Proposals:** Unstructured text proposals are rejected fail-closed. Every proposal must conform strictly to Pydantic domain models.
- **No Vector Embeddings in Deterministic Core:** Context assembly and deduplication use deterministic exact hashes and relational SQL queries.

---

## 3. Domain Model Architecture

### 3.1 Research Agent Roles
```python
class ResearchAgentRole(StrEnum):
    ALPHA_RESEARCHER = "alpha_researcher"
    RISK_CRITIC = "risk_critic"
    PORTFOLIO_CONSTRUCTOR = "portfolio_constructor"
```

### 3.2 Research Context Packet
Synthesized deterministically from `ResearchMemoryArchive` to condition the agent:
```python
class ResearchContextPacketV1(FrozenModel):
    """Immutable context packet providing historical research memory to an agent."""

    schema_version: Literal["1"] = "1"
    agent_role: ResearchAgentRole
    total_trial_count: int
    median_sharpe_ratio: Decimal | None
    max_sharpe_ratio: Decimal | None
    active_hypotheses_count: int
    falsified_hypotheses_count: int
    falsified_hypothesis_summaries: tuple[str, ...]
    forbidden_variations: tuple[str, ...]
    available_strategy_types: tuple[str, ...]
    created_at: UTCDateTime
    context_hash: SHA256Hash
```

### 3.3 Hypothesis Proposal
Formal structured claim proposed by an autonomous agent:
```python
class HypothesisProposalV1(FrozenModel):
    """Formal hypothesis proposal generated by an AI research agent."""

    schema_version: Literal["1"] = "1"
    proposal_id: UUID7
    title: NonBlankStr
    economic_rationale: NonBlankStr
    target_strategy_type: NonBlankStr
    parent_hypothesis_id: UUID7 | None = None
    min_annualized_sharpe: Decimal
    max_drawdown_limit: Decimal
    max_turnover_limit: Decimal
    min_information_coefficient: Decimal | None = None
    created_at: UTCDateTime
    proposal_hash: SHA256Hash
```

### 3.4 Experiment Specification Proposal
Concrete parameterized backtest configuration generated by the agent:
```python
class ExperimentSpecificationProposalV1(FrozenModel):
    """Concrete experiment specification proposed for empirical evaluation."""

    schema_version: Literal["1"] = "1"
    experiment_proposal_id: UUID7
    hypothesis_proposal_id: UUID7
    strategy_type: NonBlankStr
    proposed_parameters: ImmutableJSON
    parameters_hash: SHA256Hash
    universe_id: NonBlankStr
    rebalance_frequency: NonBlankStr
    created_at: UTCDateTime
    specification_hash: SHA256Hash
```

### 3.5 Proposal Validation Report
Result of deterministic gatekeeping evaluation:
```python
class ProposalValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_DUPLICATE_PARAMETERS = "rejected_duplicate_parameters"
    REJECTED_FORBIDDEN_VARIATION = "rejected_forbidden_variation"
    REJECTED_OUT_OF_BOUNDS = "rejected_out_of_bounds"
    REJECTED_CIRCULAR_LINEAGE = "rejected_circular_lineage"
    REJECTED_INSUFFICIENT_CRITERIA = "rejected_insufficient_criteria"


class ProposalValidationResultV1(FrozenModel):
    """Deterministic validation audit report for an agent proposal."""

    schema_version: Literal["1"] = "1"
    validation_id: UUID7
    proposal_id: UUID7
    status: ProposalValidationStatus
    is_accepted: bool
    rejection_reasons: tuple[str, ...] = ()
    evaluated_at: UTCDateTime
    validation_hash: SHA256Hash
```

---

## 4. Proposal Gatekeeper and Validation Rules

The `ProposalValidator` acts as an impermeable firewall between untrusted LLM outputs and the trusted research ledger:

1. **Parameter Deduplication:**
   Computes the canonical parameters hash of `proposed_parameters`. Queries `archive.is_parameter_set_evaluated(strategy_type, parameters_hash)`. If already evaluated, rejects with `REJECTED_DUPLICATE_PARAMETERS`.
2. **Forbidden Variation Check:**
   Retrieves active forbidden variations from `archive.get_forbidden_variations()`. Evaluates whether proposed parameters or strategy matches a known failed variation pattern (e.g. lookback < 5 with unhedged rebalance). If matched, rejects with `REJECTED_FORBIDDEN_VARIATION`.
3. **Parameter Bounds Check:**
   Validates parameter values against declared `ParameterSearchSpaceV1` bounding intervals. If any hyperparameter is non-numeric, out-of-range, or violates dimension step constraints, rejects with `REJECTED_OUT_OF_BOUNDS`.
4. **Hypothesis Lineage Integrity:**
   If `parent_hypothesis_id` is supplied, verifies that the parent hypothesis exists in the archive and is NOT currently `FALSIFIED` without explicit mutation justification, and that no ancestor references the proposal itself (preventing cyclic graphs). Rejects invalid lineage with `REJECTED_CIRCULAR_LINEAGE`.
5. **Falsification Criteria Sanity:**
   Verifies that:
   - `min_annualized_sharpe` is strictly positive (e.g. >= 0.20);
   - `max_drawdown_limit` is bounded between 0.05 and 0.50 (5% to 50%);
   - `max_turnover_limit` is bounded between 0.10 and 20.00.
   Rejects non-stringent or unbounded criteria with `REJECTED_INSUFFICIENT_CRITERIA`.

---

## 5. Agent Architecture and Adapter Protocol

### 5.1 Protocol Definition
```python
class ResearchAgentProtocol(Protocol):
    """Protocol implemented by research agent backends."""

    def generate_proposals(
        self,
        context: ResearchContextPacketV1,
        search_space: ParameterSearchSpaceV1,
    ) -> tuple[HypothesisProposalV1, ExperimentSpecificationProposalV1]: ...
```

### 5.2 Deterministic Mock Research Agent
For offline tests, CI gates, and deterministic regression:
- Uses a deterministic stateful sequence or pseudo-random seed generator pinned by context hash;
- Systematically traverses parameter coordinates in `ParameterSearchSpaceV1`;
- Avoids evaluated coordinates and generates valid, well-formed proposals without network calls.

### 5.3 Gemini Research Agent
For autonomous alpha exploration:
- Formats `ResearchContextPacketV1` and `ParameterSearchSpaceV1` into a structured prompt;
- Sets strict system instructions emphasizing scientific falsifiability, cost-drag awareness, and forbidden variation avoidance;
- Configures `response_schema` enforcing exact JSON schema matching `HypothesisProposalV1` and `ExperimentSpecificationProposalV1`;
- Deserializes and validates LLM responses through Pydantic `model_validate_json`;
- Retries or fails closed upon schema violation.

---

## 6. Implementation Slice Plan

Milestone M7 is organized into sequential, test-driven slices:

- **Slice 0 (M7-P0, Issue #215):** Architecture and design specification at `docs/superpowers/specs/2026-10-05-m7-first-ai-research-agent-design.md`.
- **Slice 1 (M7-1):** Domain models and schemas (`src/drift/domain/research_agent.py`, `tests/unit/test_research_agent_domain.py`).
- **Slice 2 (M7-2):** Context packet synthesis engine (`src/drift/agent/context.py`, `tests/unit/test_research_agent_context.py`).
- **Slice 3 (M7-3):** Deterministic proposal validator and gatekeeper (`src/drift/agent/validator.py`, `tests/unit/test_research_agent_validator.py`).
- **Slice 4 (M7-4):** Research agent protocol, mock adapter, and runner (`src/drift/agent/runner.py`, `src/drift/agent/mock_agent.py`, `tests/unit/test_research_agent_runner.py`).
- **Slice 5 (M7-5):** Production Gemini agent adapter with structured schemas (`src/drift/agent/gemini_agent.py`, `tests/unit/test_research_agent_gemini.py`).
- **Slice 6 (M7-6):** Comprehensive adversarial acceptance suite (`tests/adversarial/test_m7_research_agent_adversarial.py`).
- **Slice 7 (M7-7):** Milestone completion and documentation reconciliation (Parent Issue #14).

---

## 7. Invariants and Safety Rules

1. **Zero Broker / Execution Authority:** Research agents cannot create broker accounts, submit orders, or access trading credentials.
2. **Untrusted Agent Boundary:** All agent outputs are untrusted strings/JSON that must pass through Pydantic strict parsing and `ProposalValidator` before interacting with the system.
3. **Fail-Closed Gatekeeping:** Any malformed proposal, out-of-bounds parameter, duplicate configuration, or forbidden variation is rejected without side effects.
4. **Strictly Zero Em Dashes:** The Unicode em dash (U+2014) is strictly forbidden across all files; ASCII hyphen (-) is used exclusively.
5. **Pure Python Determinism:** Domain models, context packets, validators, and mock agents use pure Python standard library types and deterministic algorithms.
