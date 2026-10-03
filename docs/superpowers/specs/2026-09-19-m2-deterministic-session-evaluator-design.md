# Drift M2: Deterministic Session-Level Evaluator and Portfolio Accounting Kernel Design Specification

Date: 2026-09-19. Status: Canonical architecture design specification for Drift M2 (incorporating external architectural rulings).
Canonical Baseline: Implementation baseline is commit `68092d299f5618fb0da86049ce6f364b9e5a9f3c` (with earlier M2 checkpoints at `3aa0a5b` and `8c954f1`, and the underlying verified M1e Task 7 checkpoint at `4b343f77a0cb60d0c4ba56f066dc33ac538a9b8d`, preserved in history).
Related Architecture Decisions: [ADR 0010](../../adr/0010-qualify-real-source-rights-and-replay-before-evaluation.md), [ADR 0012](../../adr/0012-permit-exploratory-evaluation-before-promotion-grade-source-qualification.md).

---

## 1. Objective

M2 constructs the deterministic evaluation and portfolio accounting kernel that powers all quantitative research, strategy screening, and model comparison across Drift.

The evaluator answers one central question:

> Given one exact strategy version, one exact evaluation protocol, one exact evidence lane, one exact provider-neutral historical input bundle, and one exact set of accounting and execution assumptions, what sequence of decisions, fills, economic effects, portfolio states, and resulting wealth occurred?

M2 makes that answer:
- **Deterministic**: Bitwise reproducible across identical inputs, code, and environments.
- **Content-addressed**: Identified by canonical hashing of all constituent parameters, artifacts, and traces without wall-clock or random identifier contamination.
- **Replayable**: Verifiable offline without network access or non-deterministic state.
- **Temporally causal**: Structurally protected against forward-looking leakage, same-bar lookahead, and unannounced corporate actions.
- **Provider-neutral**: Completely decoupled from vendor schemas, raw payloads, or proprietary APIs.
- **Audit-friendly**: Emitting a granular, content-addressed ledger trace of every phase, mark, fill, cash flow, and valuation.
- **Proof-carrying**: Anchored directly to authenticated M1b identity/eligibility, M1c occurred economic effects and settlements, and M1d realized sessions and observations.
- **Structurally protected against evidence laundering**: Incapable of upgrading exploratory development results into promotion-grade validation evidence.

M2 is an accounting and evaluation engine, not a strategy promotion authority. M2 outputs deterministic evidence traces. Strategy promotion decisions, champion/challenger tournaments (M10), and statistical overfitting controls (M11) consume M2 traces rather than living inside M2.

---

## 2. Scope and V1 Domain Boundaries

M2 V1 establishes a rigorous, minimal accounting kernel strictly bounded to regular daily trading sessions for US cash equities.

### 2.1 Admitted Scope (V1)
- **Asset Class**: US cash equities (common stocks, ETFs, American Depositary Receipts admitted through M1b).
- **Session Resolution**: Regular daily trading sessions only (`SessionScope.REGULAR`), bounded by authenticated M1d realized session open and close timestamps (e.g. normal 09:30-16:00 ET, early-close 09:30-13:00 ET).
- **Decision Resolution**: Daily, session-by-session evaluation cycles.
- **Currency**: Single-currency USD cash accounting.
- **Portfolio Constraint**: Fully funded, long-only equity holdings (cash balance >= 0, share quantities >= 0).
- **Position Quantities**: Whole-share integers only.
- **Corporate Action Economics**: First-class M1c occurred effects and delivered settlements (splits, dividends, spin-offs, acquisitions, liquidations, terminations) with exact fraction treatments.
- **Execution**: Target whole-share deltas executed at the next eligible realized regular-session open via an atomic plan-then-commit rebalance.
- **Pricing Basis**: Source-basis unadjusted prices for accounting, marks, and fills.

### 2.2 Explicitly Excluded Scope (V1 Hard Boundaries)
Attempts to evaluate configurations outside this admitted domain fail closed with explicit validation errors:
- **No Intraday Execution**: No intraday bar clocks, tick execution, TWAP/VWAP engines, or minute-level scheduling.
- **No Shorting or Margin**: No negative share balances, borrowing fees, margin calls, or leverage calculations. Attempts to emit negative target positions are rejected.
- **No Fractional Shares**: Whole shares only in holdings; non-integral entitlements are processed according to explicit M1c fraction treatments or fail closed to `INDETERMINATE`.
- **No Options or Derivatives**: Cash equities only; warrants, rights, and convertibles with unsupported property terms fail closed.
- **No Multi-Currency**: Single currency (USD) cash accounting only.
- **No Tax Accounting**: Wash sales, tax-lot identification (FIFO/LIFO/HIFO), and capital gains tax liabilities are execution/tax concerns outside M2.
- **No Live Brokerage or Order Submission**: M2 contains zero network access, broker adapters, or order placement mechanisms.
- **No Strategy Promotion Authority**: M2 outputs evidence quality classifications; it does NOT decide strategy promotion, which belongs exclusively to M10 and M11.

---

## 3. Two-Lane Architecture (ADR 0012)

In accordance with ADR 0012, Drift maintains exactly ONE provider-neutral evaluator core engine operating across two structurally segregated evidence lanes:

```
+-----------------------------------------------------------------------------------+
|                                Drift Evaluator Core                               |
|                                                                                   |
|  - Provider-neutral domain contracts only (M0-M1d)                                |
|  - Causal session clock (Post-Realized-Close Decision -> Next Realized-Open Fill) |
|  - Source-basis unadjusted accounting + M1c occurred effect & settlement logic    |
|  - 5-phase deterministic session schedule (Atomic Plan-Then-Commit Rebalance)     |
|  - Pure runtime strategy interface (Decision Context -> Whole-Share Intent)       |
|  - Content-addressed execution trace & scientific classification                  |
+-----------------------------------------------------------------------------------+
                                         ^
                                         | Consumes
        +--------------------------------+--------------------------------+
        |                                                                 |
+------------------------------------+          +------------------------------------+
|          EXPLORATORY Lane          |          |           PROMOTION Lane           |
|                                    |          |                                    |
| - Purpose: Prototyping, baselines, |          | - Purpose: High-rigor empirical    |
|   signal screening, engineering.   |          |   evidence for M10/M11 analysis.   |
| - Input: Free development data     |          | - Input: Positive M1e qualified    |
|   (Alpaca Basic).                  |          |   sources (e.g. Databento PIT).    |
| - Limitation: Binds explicit known |          | - Requirement: Verified rights,    |
|   flaws (truncated CA replay, etc).|          |   native bytes, positive M1e       |
| - Epistemic Status: Strictly       |          |   completion record, replay match. |
|   non-upgradeable development data.|          | - Epistemic Status: Certified      |
|                                    |          |   promotion-grade evidence.        |
+------------------------------------+          +------------------------------------+
```

### 3.1 Exploratory Development Lane (`EXPLORATORY`)
- **Purpose**: Fast, cost-free engineering verification, baseline establishment (M3), signal exploration, and preliminary hypothesis screening.
- **Authorized Input**: Free development data (default: Alpaca Basic historical SIP bars and REST corporate actions).
- **Known Limitations**: Input bundles carry explicit documented limitations (e.g. truncated corporate action mutation history, unversioned derived bars, missing trading halt telemetry, bounded cohort).
- **Epistemic Constraint**: Results are permanently exploratory. They cannot be submitted to champion/challenger tournaments (M10), overfitting gates (M11), or live execution approval (M16+).

### 3.2 Promotion-Grade Lane (`PROMOTION`)
- **Purpose**: Authoritative empirical evidence for subsequent strategy promotion analysis in M10/M11.
- **Authorized Input**: Datasets produced exclusively by a fully qualified, positively verified M1e real-source profile with positive completion (`M1eCompletionKind.COMPLETED_POSITIVE`).
- **Qualification Requirements**: Every critical dimension declared by the profile must PASS (`QualificationStatus.PASS`, `ExecutionReachability.REACHED`, `admitted_purpose=True`), every dimension must have an explicit evidenced status, exact native bytes must be retained in private storage, rights must authorize internal algorithmic use and indefinite offline retention, and offline replay closure must verify bitwise identical output.
- **Current Operational Status**: Paused/deferred under ADR 0012. Tested in M2 exclusively through synthetic qualification fixtures to verify fail-closed enforcement.

---

## 4. Structural Anti-Upgrade Enforcement

To guarantee that exploratory evidence cannot be laundered into promotion-grade claims, lane separation is enforced at the type and schema layer, not via a mutable boolean flag.

### 4.1 Invariant: No Mutable Lane Field or Promotable Claims
An evaluation run cannot be toggled from exploratory to promotion by flipping a flag.
Furthermore, M2 does NOT output `is_promotable=True`. M2 certifies the *evidence grade* of the run, not whether the strategy itself is approved or promoted.

### 4.2 Acyclic Admission Dependency Graph
The relationship between market data input bundles, admissions, and evaluation runs is strictly acyclic:
$$\text{Market Data} \longrightarrow \text{EvaluationInputBundleV1} (\text{bundle\_hash}) \longrightarrow \text{EvaluationAdmissionV1} (\text{input\_bundle\_hash} = \text{bundle\_hash}) \longrightarrow \text{EvaluationRunIdentity}$$

`EvaluationInputBundleV1` does NOT hold a reference to `admission_hash`. The input bundle is immutable historical evidence independent of the evaluation lane under which it is evaluated. The admission token authorizes the bundle.

**Amendment, cross-slice adversarial finding F4.** The `input_bundle_hash = bundle_hash` link above was declared but never enforced, so a valid `EvaluationRunIdentityV1` could bind a promotion admission hash over a bundle that admission never admitted. `build_evaluation_run_identity` now takes the admission and the bundle as objects rather than two independent hashes, and fails closed unless `admission.input_bundle_hash == bundle.bundle_hash`.

### 4.3 Distinct Immutable Admission and Result Types
The domain model enforces disjoint type hierarchies:

```python
class ExploratoryEvaluationAdmissionV1(FrozenModel):
    """Admission proof for exploratory evaluation using development-grade data."""

    schema_version: Literal["1"] = "1"
    lane: Literal["exploratory"] = "exploratory"
    input_bundle_hash: SHA256Hash
    acknowledged_limitations: tuple[NonBlankStr, ...]
    admission_hash: SHA256Hash


class PromotionEvaluationAdmissionV1(FrozenModel):
    """Admission proof strictly requiring verified M1e positive completion evidence across both consumer purposes."""

    schema_version: Literal["1"] = "1"
    lane: Literal["promotion"] = "promotion"
    m1e_completion_record_hash: SHA256Hash
    m1e_profile_set_hash: SHA256Hash
    decision_handoff_hash: SHA256Hash
    audit_handoff_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    provenance_proof_hash: SHA256Hash
    admission_hash: SHA256Hash


type EvaluationAdmissionV1 = Annotated[
    ExploratoryEvaluationAdmissionV1 | PromotionEvaluationAdmissionV1,
    Field(discriminator="lane"),
]

Note on admission determinism: Admissions do not carry operational wall-clock creation timestamps (`admitted_at`) or redundant identifier fields (`admission_id`). Operational timestamps belong to M0 `ExperimentRun`, audit events, and upstream M1e completion records. The semantic identity is a single self-excluding `admission_hash = content_hash(...)`. Re-evaluating the identical bundle with identical qualification evidence yields bitwise identical `admission_hash`.

Dual-purpose M1e binding via QualifiedSourceHandoffV1: A promotion evaluation relies on two distinct epistemic roles: `HISTORICAL_DECISION_INPUT` (for point-in-time information the strategy was permitted to know at decision cutoffs) and `RETROSPECTIVE_AUDIT` (for ex-post accounting truth, settlements, terminal liquidations, and evaluation reconstruction). Both purposes are bound authoritatively through `decision_handoff_hash` and `audit_handoff_hash`, pointing to M1e `QualifiedSourceHandoffV1` objects. Those handoffs bind the exact profile, report, target, snapshot, environment closure, and replay authorization hashes, eliminating redundant duplicated fields from the admission token while maintaining unbroken cryptographic provenance.


class EvaluationSummaryMetricsV1(FrozenModel):
    """Raw deterministic accounting metrics summary emitted by the evaluator core."""

    initial_cash: Decimal
    ending_cash: Decimal
    ending_holdings_value: Decimal
    ending_pending_claims_value: Decimal
    ending_net_asset_value: Decimal
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
    total_turnover_notional: Decimal
    total_fill_count: int
    total_session_count: int
    daily_equity_series: tuple[tuple[date, Decimal], ...]


class ExploratoryEvaluationResultV1(FrozenModel):
    """Deterministic exploratory evaluation result; permanently non-promotion-grade."""

    schema_version: Literal["1"] = "1"
    result_id: SHA256Hash  # Content-addressably derived from deterministic payload
    lane: Literal["exploratory"] = "exploratory"
    admission_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    protocol_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1

    @property
    def is_promotion_grade_evidence(self) -> bool:
        return False


class PromotionEvaluationResultV1(FrozenModel):
    """Deterministic promotion-grade evaluation result; verified against M1e positive completion."""

    schema_version: Literal["1"] = "1"
    result_id: SHA256Hash  # Content-addressably derived from deterministic payload
    lane: Literal["promotion"] = "promotion"
    admission_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    protocol_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    evaluation_hash: SHA256Hash
    trace_hash: SHA256Hash
    classification: EvaluationClassification
    summary_metrics: EvaluationSummaryMetricsV1

    @property
    def is_promotion_grade_evidence(self) -> bool:
        return True


type EvaluationResultV1 = Annotated[
    ExploratoryEvaluationResultV1 | PromotionEvaluationResultV1,
    Field(discriminator="lane"),
]
```

### 4.4 Absolute Non-Upgrade Rule
There is no constructor, helper, API endpoint, or migration function that converts an `ExploratoryEvaluationResultV1` into a `PromotionEvaluationResultV1`.
If an exploratory evaluation run demonstrates promising performance, that result serves solely as justification to invest capital in acquiring promotion-qualified M1e data. Promotion validation requires an entirely NEW, independent evaluation run executed against the newly qualified dataset.

---

## 5. Evaluator Core Boundary

The evaluator core is a pure Python engine with zero network, filesystem, or provider dependencies.

```
+-----------------------------------------------------------------------------+
|                             Drift Domain Layer                              |
|                                                                             |
|  [M1b Universes]   [M1c Corporate Actions]   [M1d Sessions & Observations]  |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                 EvaluationInputBundleV1 (Proof-Carrying)                    |
|                                                                             |
|  - M1b StructuralEligibilityResultV1 instances & proof hashes               |
|  - M1c EconomicOutcomeResolutionV1 & DeliveryGroup proof hashes             |
|  - M1d RealizedSessionVersionV1 & ScheduledSessionVersionV1 instances        |
|  - M1d unadjusted source-basis DerivedObservationViewV1 instances           |
|  - M1d causal split-normalized DerivedObservationViewV1 instances           |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                             Evaluator Engine                                |
|                                                                             |
|  Input: Strategy + InputBundle + Protocol + CostModel + Admission           |
|  Output: TraceLog + EvaluationSummaryMetrics + Classified Result            |
+-----------------------------------------------------------------------------+
```

The evaluator core accepts:
1. An executable `RuntimeStrategy` conforming to the pure strategy protocol.
2. A validated `EvaluationInputBundleV1`.
3. A declared `EvaluationProtocolV1`.
4. An explicit `EvaluationCostModelV1`.
5. An admitted `EvaluationAdmissionV1`.

The core never interacts with:
- Raw provider bytes, files, or responses (Alpaca, Databento, algoseek).
- Network sockets or HTTP clients.
- Global mutable state, random number generators, or system clocks.
- Broker accounts, orders, or paper trading endpoints.

---

## 6. Runtime Strategy Protocol and Whole-Share Target Intent

### 6.1 Strategy Provenance Separation
Existing M0 domain models (`StrategyReference`, `StrategyArtifact`) are immutable provenance records storing code hashes, artifact references, and hypothesis links. They remain untouched.

### 6.2 Pure Strategy Protocol
M2 introduces a runtime protocol executed during the post-close decision phase:

```python
class PositionViewV1(FrozenModel):
    """Causal, point-in-time view of an existing portfolio holding."""

    security_id: UUID7
    quantity: int
    cost_basis: Decimal
    average_cost_per_share: Decimal


class StrategyDecisionViewV1(FrozenModel):
    """Canonical, causally anchored decision view for one security."""

    security_id: UUID7
    views: tuple[DerivedObservationViewV1, ...]


class StrategyDecisionContextV1(FrozenModel):
    """Causal, point-in-time information set provided to a strategy."""

    session_key: SessionKeyV1
    decision_cutoff: UTCDateTime
    admitted_universe: tuple[UUID7, ...]  # Canonical sorted security_ids
    current_holdings: tuple[PositionViewV1, ...]  # Canonical sorted holdings
    current_cash: Decimal
    portfolio_nav: Decimal
    decision_views: tuple[StrategyDecisionViewV1, ...]  # Canonical sorted views


class SecurityTargetPositionV1(FrozenModel):
    """Target position intent emitted for one admitted security."""

    security_id: UUID7
    target_quantity: int  # Must be >= 0 (whole shares, long-only)


class StrategyDecisionIntentV1(FrozenModel):
    """Complete portfolio intent emitted by a strategy at a decision cutoff."""

    session_key: SessionKeyV1
    decision_time: UTCDateTime  # Must strictly match context.decision_cutoff
    targets: tuple[SecurityTargetPositionV1, ...]
    strategy_state_artifact: ArtifactReference | None = None


class RuntimeStrategy(Protocol):
    """Pure strategy interface invoked by the evaluator engine."""

    @property
    def strategy_reference(self) -> StrategyReference: ...

    def decide(
        self, context: StrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1: ...
```

Note on decision determinism: The evaluator engine strictly validates that `intent.decision_time == context.decision_cutoff`. Strategies are prohibited from populating `decision_time` using system wall-clock functions like `datetime.now(timezone.utc)`. If a strategy returns an intent with a mismatched timestamp, validation fails closed with `ValueError("decision intent decision_time must strictly match context.decision_cutoff")`.

**Amendment, issue 111 (gap G6 of the strategy-surface contract inventory, #113, as revised by two rounds of PR 119 review).** The engine no longer stages the intent a strategy returns as returned. In both decision lanes, the answer of `decide` or `decide_exploratory` is checked in three steps before staging, as issue 78 revalidates every engine input, and each step refuses rather than repairs. First, its structure is walked using only type identity and the models' own field state, so no method a strategy could define runs. The answer must be exactly a `StrategyDecisionIntentV1`, not a subclass and not any other object, `None` and dicts included. Its session key and each target must be exactly `SessionKeyV1` and `SecurityTargetPositionV1`, and `targets` exactly a `tuple`. Every string must be exactly `str`, the target quantity exactly `int` (so not `bool`), the security identifier exactly `uuid.UUID` holding an exact `int` within the 128-bit range, and the session date exactly `date`. `decision_time` must be exactly `datetime` with `tzinfo` the `datetime.UTC` singleton, which is the only form `UTCDateTime` validation produces, so another zone, or `ZoneInfo("UTC")`, at an equal instant is refused. Every model's instance dictionary must be exactly a `dict`, since pydantic reads its raw storage while a subclass could show the walk other values. No model may carry state beside its declared fields: an instance-dictionary key that is not exactly a declared `str`, extra or private state, or a `__pydantic_fields_set__` that is not exactly a `set` of exact `str` of the kind a construction produces. Subclasses are refused because strict validation keeps a subclass instance, and its overridden comparisons would then reach staging. Second, the intent must pass the declared type's strict validation. Third, the canonical content of the rebuilt intent must equal that of the returned one, so a value a validator would normalize, such as an unsorted target set or a padded venue code, is refused rather than silently repaired. Each refusal raises `StrategyIntentRejectedError`, so the run halts `REJECTED` before any fill with a named cause in `rejection_reason`, exactly as a staging refusal does. An accepted intent is then rebuilt once more through JSON, so the staged intent holds only fresh objects the strategy never saw. A python-mode rebuild keeps the strategy's own `uuid.UUID` instances, which a strategy that kept one could rewrite after the decision was staged, traced and filled. A genuine intent's trace and result hashes are unchanged. A refused return is traced with `intent_hash` over its canonical content, with three exceptions, where it is over `{"uncanonical_return_type": "<module>.<qualname>"}` of the return's type: an intent the walk refuses, whose leaves could otherwise run their own code while hashed; an intent the walk accepts whose content still cannot be serialized, such as a lone surrogate in a string; and any other return without a canonical form, such as an arbitrary object. Both names are read through `type` itself, so no metaclass runs, and a name that is not exactly a `str` is written `<unnamed>`. Hashing a refused return that is not a `StrategyDecisionIntentV1`, such as a dict subclass, can still run the strategy's own code (iteration, a serializer, or `repr`). If that code raises, the exception propagates and the M0 run records `FAILED`, which is what #113 D6 (a) rules for a strategy that raises. An exception raised inside `decide` or `decide_exploratory`, a `ValidationError` included, likewise propagates and the run records `FAILED`. Residual: strategy code runs in-process with the engine. Staging is isolated from the strategy's returned objects, but the context route, in which the strategy receives the engine's own objects, is tracked in #123 and is not changed here.

**Amendment, issue 123 (the PR 119 review, F1, R2-F2 and R3-F1, the PR 126 review residual, and two rounds of PR 131 review; supersedes the issue 78 python-mode rebuild and the context residual of the issue 111 amendment).** Issue 78 rebuilt every engine input as `declared.model_validate(model.model_dump(mode="python"))`. Strict validation keeps an instance of a `uuid.UUID`, `datetime` or `date` subclass, and a python-mode dump hands back that same leaf, so a forged input kept its own `__eq__`, `__hash__` and `__str__` inside the engine. Canonical hashing, which reads the string form, and the engine's comparisons, which read `__eq__`, `__hash__` and the integer value, could then disagree about which security, instant or date a value names. `SessionEvaluatorEngine` still validates every input that way, so every issue 78 refusal is unchanged, and then rebuilds the validated model through canonical JSON (`declared.model_validate_json(validated.model_dump_json())`), keeping only that rebuild: the bundle, the admission (as a member of the lane union), the protocol, the cost model, every evaluator evidence model (the listing role, termination and lifecycle records, the economic outcomes, the three interpretation registries, the exploratory cohort, and the replay policy and queries) and the run identity. Every leaf the engine uses is then a fresh, exact built-in value, every later comparison and hash reads the one canonical value, and the declared type's own hash validators check that value again. A forged leaf that keeps its genuine string form therefore runs exactly as its canonical value, and one whose string form differs from its value fails its input's hash check. Each replay request's M1d resolution context is rebuilt too (PR 131 review, F1). M1d replay compares the records it parses from a context's artifact bytes with the records the context holds, with the held records on the right, so a held record whose `Decimal` open held 500.000, spelled 100.000 and equalled every value passed that check, the canonical builder re-derived 500.000 from it, and a bundle's self-consistent 500 reconstruction passed verification: the engine filled a buy at 500. The engine now rebuilds the context from its declared type hints: every model it holds, at any depth (dataset records, manifests, validation runs, decisions, bundles, availability policies and evidence, and the structural and economic contexts' records), as `_revalidated` rebuilds an engine input, every other scalar through canonical JSON under its declared hint, artifact bytes only if exactly `bytes`, and every dataclass, the context included, as its declared class from those members. A member that is not an instance of its declared model, dataclass, tuple or mapping type, a scalar that fails strict validation, a union member the declaration does not admit, and a mapping holding two keys that rebuild to one are each refused, never repaired. A context shared by several requests is rebuilt once. That record is then refused, since its real digits do not match its payload hash. The realized lane consumes no M1d context: its evidence is models only. The engine's only plain constructor arguments, `book_currency_namespace` and `book_currency_code`, must be exactly `str`, or construction raises `NonCanonicalEngineInputError` (a `DriftError` and a `TypeError`, in `src/drift/evaluator/engine.py`); only those exact strings reach the evidence hash, the price currency checks and the corporate action processor (PR 131 round 2, G1: held as given, an `EUR` book code equal to every string filled USD prices and ended `COMPLETE` under the evidence hash of an honest `EUR` book, which halts `INDETERMINATE`). The intent a strategy returns keeps its issue 111 checks unchanged, strict validation in python mode first included, so a leaf that cannot be serialized, such as a lone surrogate, is still refused `REJECTED` before the JSON rebuild. Each strategy is also handed a canonical JSON-rebuilt copy of its decision context, in both lanes, sharing no object with the engine's bundle, admission, evidence or loop state. Before this, the admitted universe and the holdings held the engine's own `UUID` instances, so a strategy rewriting one in place (`object.__setattr__` on its `int`) could end a run `COMPLETE` with a trace naming an unadmitted security. The context hash is still taken over the engine's own context. `execute_experiment_run` likewise rebuilds each caller input it compares or records through canonical JSON with its declared type's `TypeAdapter`, before any comparison: the context's run identity, the specification's dataset and strategy references, the running strategy's reference, the start and completion instants, and the run, experiment, result artifact, trace artifact and audit event identifiers. Only those copies are compared, passed to the engine and recorded, in the M0 row and in its audit event, whose timestamp is the canonical completion instant (PR 131 review, F2: python-mode validation of the row and the event kept a `datetime` or `UUID` subclass, so an audit event could be stamped 2000-01-01, before the run's checked start, or name another run). Comparing a rebuilt value with the caller's own object is not enough, because Python asks a right operand that subclasses the left one first. A caller input that fails its rebuild raises its validation error before the engine runs and records nothing: a context identity whose bundle hash equals every string, which only the dataset check on the result used to refuse, now fails its own identity hash. The residual probe's cases (a lying identity subclass or lying identity leaves, alone or with a lying dataset reference, behind a stand-in engine returning another run) each raise `ForeignRunArtifactsError` and record nothing. Genuine inputs are byte-identical: every bundle, admission, evidence, run identity, context, trace and result hash, every M0 row, and every audit event. Residuals. M1d validation's own comparison of parsed and held records, at the build and verify boundary outside the engine, still lets the held record's reflected `__eq__` answer; that is a separate follow-up issue, since the M1d modules are byte-pinned. Per the #113 freeze note, strategy code runs in-process with the engine, so a hostile strategy can still reach engine state through `gc`, frames or other introspection. The context copy removes only the direct object-sharing route. Isolating hostile strategy code is out of scope here, and a prerequisite only for untrusted strategy code (M7, M8). Enum members are singletons, so a rebuild shares them with the input and the strategy's copy shares them with the engine. The engine also still reads the strategy's self-declared `strategy_reference.code_hash` as given when it binds the run identity; the runner compares a canonical copy of it first.

**Amendment, issue 112 (gap G1 of the strategy-surface contract inventory, #113, decision D2, ruled option (b) on 2026-09-24).** `ParameterizedStrategy` (in `src/drift/domain/evaluator_strategy.py`) is a runtime-checkable protocol addition beside the two lane protocols, which are unchanged: a strategy answers `decide` or `decide_exploratory` for its lane, and may also expose `strategy_parameters`, the canonical parameters the instance runs with. Only a run under an `EvaluationRunIdentityV2` (section 18, issue 112 amendment) reads it, exactly once per run, in the engine's binding before any session is stepped, in either lane; the experiment runner does not read it, and a V1 run never reads it. Under V2 a strategy without the member is refused, and so is one whose parameters are not canonical JSON data or whose `strategy_parameters_hash()` differs from the identity's `strategy_parameters_hash`, each with `StrategyParametersBindingError` (a `DriftError` and a `ValueError`, in `src/drift/domain/evaluator_bundles.py`). Canonical JSON data means exactly a `dict` or `types.MappingProxyType` (the frozen form an `ExperimentSpecification` holds) with exact `str` keys, a `list` or `tuple`, and exact `str`, `int`, finite `float`, `bool` or `None` leaves. Every key, leaf, list, tuple and dict is accepted on its exact type alone, so none of their own methods runs, and a subclass of any of them (a `StrEnum` member included), any other mapping type, a `Decimal`, a set, a non-finite float, a string with no UTF-8 form, an integer longer than the interpreter will write, and parameters nested too deeply to copy are each refused, never repaired: a key or leaf equal to every value, and a dict, list or tuple whose methods show other contents than its storage, would otherwise pass Python equality or a method-reading content hash as parameters they do not hold. A mapping proxy is accepted whatever it wraps: it is read once, through the wrapped mapping's `items()`, which is caller or strategy code when that mapping is not exactly a dict, and a key that read yields twice is refused. Each check therefore hashes the one copy its single read yields and never reads the parameters again, so the digest compared is the digest recorded (issue 112 review, F1, F2 and F4). Per the #113 freeze note, the member is a declaration by trusted strategy code, not a sandbox: it binds what the strategy says it runs with, as `strategy_reference.code_hash` does for its code.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** `PositionViewV1.cost_basis` and `average_cost_per_share` are `Decimal | None`, and both are `None` exactly when the holding's basis is indeterminate (section 11.2), so a strategy is shown that the basis is unknown, never a number no evidence supports; a view with one of the two unset is refused. `position_view` projects a `SecurityHoldingV2`. A view of a known basis dumps exactly as before, so the decision `context_hash` of a book whose bases are all known is unchanged; a decision that sees an indeterminate basis moves its context hash, and with it the trace and result hashes (section 18). The #113 D9(i)(a) sequencing places the `PositionViewV1` freeze after this change.

### 6.3 Security-Level Targets and Historical Listing Resolution
Strategies target economic securities (`security_id`), NOT historical listings (`listing_id`) or exchange tickers:
- **No Stale Listing Selection in Strategy**: Strategies do not pick exchange venues or track historical listing migrations.
- **Evaluator Execution-Listing Policy**: The evaluator resolves the execution listing dynamically at Phase 2 (Open Execution) using M1b structural eligibility evidence: "execute through the uniquely resolved eligible historical primary listing for the execution session."
- **Fail-Closed Resolution**: If no exact eligible listing exists for an admitted security on the execution date, or if multiple candidate listings cannot be uniquely resolved, execution halts fail-closed to `INDETERMINATE`. The resolved `listing_id` and venue are recorded on `FillTraceEventV1`.

### 6.4 Whole-Share Target Positions and Explicit Omission Rule
Strategies emit target WHOLE-SHARE quantities rather than fractional weights or raw buy/sell orders:
- **No Evaluator Capital Allocation Guessing**: The evaluator does not guess how to round fractional shares or allocate remaining cash. The strategy specifies exact target share counts.
- **Explicit Complete Target Set Rule**:
  Any currently held security that is NOT present in `targets` is treated as an explicit liquidation:
  $$\text{target\_quantity} = 0 \quad (\Delta q = -\text{current\_quantity})$$
  If a strategy wishes to maintain an existing holding, it must explicitly include that security in `targets` with `target_quantity = current_quantity`.
- **Long-Only Validation**: Any target quantity $< 0$ immediately triggers a `REJECTED` evaluation classification.
- **Phase 5 vs. Phase 2 Validation Boundary**:
  - In Phase 5 (Post-Close Decision), the engine validates: targets are whole-share integers, targets are non-negative, and new entries (`target > 0`) belong to `admitted_universe`. Phase 5 does NOT validate cash solvency, because next-session open prices and slippage are strictly future unknowns.
  - In Phase 2 (Open Execution), actual cash solvency is enforced when open prices are materialized.

---

## 7. Proof-Carrying Evaluation Input Bundle and Epistemic Input Separation

An evaluation run operates on a self-contained, content-addressed bundle of authentic Drift artifacts. M2 does NOT flatten away M1b-M1d provenance into self-authored convenience facts, nor does it launder retrospective data into historical decision evidence.

### 7.1 Exploratory Reconstructed Session Observation vs True Decision Information

Free development providers (such as Alpaca) provide current snapshots of historical bars and corporate actions, but lack historical provider assertion vintages, publication cutoffs, and halt telemetry. Strict M1d normalization requires authentic `RealizedSessionVersionV1` authority (`bind_observation_session` only classifies an observation as fully bound through realized open/close evidence), so scheduled-only exploratory history must never be forced through `materialize_observation_decision`/`materialize_observation_outcome`: it would either fail honestly or fabricate realized history. Fabrication is forbidden.

Nor may exploratory inputs claim M1b structural authority. `resolve_structural_eligibility(...)` accepts only `ResolutionMode.AS_KNOWN` with `InformationRole.DECISION_INFORMATION` by deliberate fail-closed M1b invariant (`structural_decision_mode_required`); `CURRENT_INTERPRETATION` + `EX_POST_OUTCOME` structural evidence does not exist and must not be built by M2. Exploratory evaluation therefore operates over an explicitly predeclared bounded security cohort instead of a historical universe.

M2 defines exploratory-only contracts:

**ExploratoryCohortAuthorizationV1** (`schema_version="1"`, `kind="predeclared_bounded_security_cohort"`, `cohort_id`, `cohort_version`, `security_ids: tuple[UUID7, ...]` nonempty/unique/canonically sorted, self-excluding `cohort_hash`): experiment SCOPE authorization only. It asserts only that these securities are authorized exploratory subjects. It is NOT proof of universe membership, survivorship-free selection, structural listing eligibility, primary listing, or the historical availability of any record. It carries no listing/ticker, timestamp, provider, or random fields. Its use mechanically requires the exploratory admission to acknowledge `ALPACA_LIMITATION_BOUNDED_COHORT`.

**ExploratoryReconstructionPolicyV1** (`schema_version="1"`, `policy_id`, `policy_version`, `mode="source_basis_scheduled_session_reconstruction_v1"`, `required_fields` exactly `("close", "high", "low", "open", "volume")` canonically ordered, `required_basis="unadjusted"`, `semantic_policy_hash`, self-excluding `policy_hash`): immutable, content-addressed, no network/provider/clock/random fields. The scheduled exploratory path is source-basis UNADJUSTED only; it never produces `basis_mode="split_normalized"` and never re-implements M1d split normalization.

**ExploratoryReconstructedFieldV1**: binds `field_name` (exactly one of open/high/low/close/volume), exact Decimal `source_value` (float/NaN/Infinity rejected), `method_id`, field `meaning` (price for OHLC, share_volume for volume), and `source_field_hash`. Methods must exist in the selected `ObservationContractV1` with unadjusted semantics; unknown or fallback semantics fail closed.

**ExploratoryReconstructedSessionObservationV1** (`kind="exploratory_reconstructed_session_observation"`): binds `session_key`, `security_id`, `listing_id`, `venue`, `cohort_hash`, the exact source observation / observation contract / scheduled-session hashes with their selection proofs, the schedule artifact and generated row hashes, the `ObservationOutcomeQueryV1` hash, source context hash, `evidence_vintage_cutoff`, `reconstruction_policy_hash`, `currency`, canonical `fields`, `acknowledged_limitations` (always at least `ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION` and `ALPACA_LIMITATION_UNVERSIONED_BARS`), and a self-excluding `reconstruction_hash`. The builder replays existing `select_observation_records` selection and `generate_schedule` generation; it never calls `bind_observation_session`, the M1d materializers, or the M1b structural resolver.

An `ExploratoryReconstructedSessionObservationV1` is NOT: `DerivedObservationViewV1`, `ObservationDecisionReferenceV1`, `ObservationOutcomeReferenceV1`, an M1d `NormalizationResultV1`, proof of historical publication availability, proof of a realized session, proof of the absence of halts, or promotion-grade evidence.

**Epistemic Contract**:
- **Retrospective Knowledge Warning**: A reconstructed observation may contain corrections, corporate action revisions, or source adjustments published AFTER the historical session; `evidence_vintage_cutoff` is that retrospective cutoff.
- **Scientific Utility**: Valid and authorized for engineering validation, harness closure, indicator calculation, and exploratory strategy screening over the declared cohort.
- **Strict Prohibition**: NEVER historical-decision proof; NEVER promotion-grade; NEVER convertible into promotion evidence.
- **Promotion Lane Prohibition**: Any promotion evaluation that encounters an `ExploratoryReconstructedSessionObservationV1` is immediately rejected by structural validation.

**Amendment, issue 46 (the issue 42 adjudication of ADR 0012 Option B).** Reconstructed observations may drive strategy decisions in the EXPLORATORY lane only, through a dedicated exploratory-only type. `src/drift/domain/evaluator_exploratory_strategy.py` defines `ExploratoryStrategyDecisionContextV1`, whose evidence members are `ExploratoryReconstructedDecisionViewV1` groups of `ExploratoryReconstructedSessionObservationV1` (one per session, in business-time order), and `ExploratoryReconstructedRuntimeStrategy.decide_exploratory`, which answers it. `StrategyDecisionViewV1`, `StrategyDecisionContextV1`, and `RuntimeStrategy.decide` are unchanged and are not unions; the only union is the engine's lane-dispatch strategy parameter. The context carries literal `lane="exploratory"`, `evidence_grade="exploratory_reconstructed"`, and `is_promotion_grade_evidence=False`; refuses any decision session without `scheduled_reconstruction` authority; decides at exactly the scheduled close its generated calendar row states (13:00 on an early close, never an artificial 16:00); requires a reconstruction for its own decision session bound to that session's scheduled record and generated row; refuses any reconstruction from a later session; and must acknowledge the scheduled-clock, bounded-cohort, and reconstruction limitations. `SessionEvaluatorEngine` fixes the lane at construction: an `ExploratoryEvaluationAdmissionV1` over a `scheduled_session_reconstruction` clock, with its `ExploratoryCohortAuthorizationV1` supplied as `SessionEvaluatorEvidence.exploratory_cohort`, takes the reconstructed lane after `validate_exploratory_admission`, the bounded-cohort acknowledgement, and a per-reconstruction cohort and calendar-row binding; every other exploratory admission takes the realized lane unchanged; and a `PromotionEvaluationAdmissionV1` over any bundle carrying exploratory reconstructions, or with an exploratory cohort, is refused at construction. Each reconstructed decision reads only reconstructions for clock sessions already stepped, and is traced as `ExploratoryStrategyDecisionTraceEventV1` (never `StrategyDecisionTraceEventV1`), naming every reconstruction read and every limitation carried. Scope boundary: the ruling authorizes reconstructed evidence for decisions only. A scheduled-reconstruction bundle still carries no authorized accounting evidence, so Phase 2 execution of any traded security and Phase 4 marking of any held position remain `INDETERMINATE` until accounting over reconstructed evidence is separately decided.

**Amendment, issue 55 (ruled in #62, Q1).** A reconstruction's self-excluding `reconstruction_hash` proves only that it is self-consistent, never that a source produced it, so once reconstructions drive decisions they are trusted only by canonical re-derivation. `ExploratoryReconstructionReplay` (`src/drift/evaluator/reconstruction.py`) carries the shared `ExploratoryReconstructionPolicyV1` and one `(ObservationOutcomeQueryV1, M1dResolutionContext)` request per reconstruction; together with the declared cohort these are exactly the inputs of `build_exploratory_reconstructed_session_observation`, the one canonical builder. `verify_exploratory_reconstructions` re-derives every request and requires exact canonical equality over the multiset in both directions, so no carried reconstruction goes unverified and none re-derived is missing. That single equality proves every field (source observation, observation contract, selection proofs, generated schedule, source context hash, policy, OHLCV values, currency, limitations, and hash) is exactly what the canonical builder derives from the replay's own M1d context; it does not prove that context authentic, which is the replayed source evidence itself, as it is for authentic views. Two further bindings sit beside it. The clock is bound separately by `require_scheduled_calendar_row`: each reconstruction's scheduled session and generated row hashes must be among its clock session's authority records. And at the bundle boundary, `build_evaluation_input_bundle` and `verify_evaluation_input_bundle` replay every request against the one context they are handed, refusing any query naming another (the builder's own M1d guard then refuses a request whose context object does not match its query), and apply the calendar-row binding to a scheduled clock. `SessionEvaluatorEvidence.exploratory_reconstruction_replay` is required exactly when the reconstructed lane is taken and refused everywhere else, like `exploratory_cohort`; the lane gate re-derives after the cohort and calendar-row binding and before any decision reads a reconstruction. Trust boundary: reconstructions riding a realized-clock bundle are never re-derived by the engine, because that lane never reads them as decision or accounting evidence (only their limitations propagate into the admission and result); they are only as trusted as `verify_evaluation_input_bundle` makes them. The grade is unchanged: re-derived reconstructions remain EXPLORATORY evidence and upgrade nothing.

**Amendment, issue 54 (ruled in #62, Q2, option C).** This supersedes the issue 46 scope boundary on accounting. In the EXPLORATORY reconstructed lane only, and only after the issue 55 gate has re-derived every reconstruction, Phase 2 prices each traded security from the execution session's reconstructed open and Phase 4 marks each holding at that session's reconstructed close, through the dedicated `ExploratoryReconstructedAccountingPriceV1` (`src/drift/domain/evaluator_exploratory_accounting.py`). The record is not a `DerivedObservationViewV1` and shares no domain base with one. It binds security, listing, venue, session, `field_role` (`open` or `close`), the unadjusted source-basis price, currency, the reconstruction hash, the source field hash, the scheduled session and generated row hashes, and every limitation of the reconstruction, with literal `evidence_grade="exploratory_reconstructed"` and `is_promotion_grade_evidence=False` and a self-excluding `price_hash`. A mark's `MarkEvidenceV1` is graded `exploratory` and names that `price_hash`. Every price a phase consumes is traced, in full, as `ExploratoryAccountingPriceTraceEventV1` (never folded into a fill or mark event), which also states at least every limitation the reconstructed grade carries. A missing reconstruction, more than one reconstruction for a security and session, a price that is not strictly positive, or a price in a currency other than the book's halts the run `INDETERMINATE`; nothing is defaulted. Known limitation, ruling requested in #76: an absent corporate-action outcome is read as no corporate action in either lane, so until closed-world corporate-action coverage is required, a reconstructed trading run across an unrecorded split or dividend can complete with wrong numbers; trading-baseline evidence waits on that ruling. A realized-clock bundle never prices from a riding reconstruction. `EvaluationRunArtifactsV1` refuses a promotion result bound to any `exploratory_accounting_price` event, in addition to the promotion lane's existing refusal of exploratory mark grades.

**Amendment, issue 76 (owner ruling of 2026-09-24, option A, with decisions D1 to D9 recorded on #76).** This supersedes the known-limitation sentence of the issue 54 amendment: an absent corporate-action outcome is no longer read as no corporate action, in either lane. A security the book is exposed to at a pre-open, by a holding at the prior close or a positive staged target, judged against the opening book and again against the book the pass leaves, must be closed-world covered over that session's corporate-action window, or the run halts `INDETERMINATE` in `PRE_OPEN_EFFECTS` (section 12 amendment, C1 to C6). Coverage is either an exploratory `ClosedWorldCorporateActionCoverageV1` record (the M1 design spec, section 6 amendment), admitted only under an exploratory admission, or the security's own M1c-native outcome whose terms, effect and settlement coverage results are complete over the whole action vocabulary with a one-day margin each side and no reason that can hide an action (the promotion-grade form). The records ride in the bundle as `EvaluationInputBundleV1.corporate_action_coverage` (D8-a), covered by the bundle hash and so by every admission; every record's limitations, at least `corporate-action-absence-read-from-current-provider-snapshot`, are required limitations of the bundle, so an exploratory admission omitting one is refused and the promotion gate refuses any bundle carrying a record with no new code. The bundle refuses a record for a security it does not identify (`ca_coverage_security_not_in_bundle`) and a security covered by both kinds of evidence (`ca_coverage_mixed_sources`, V11); the bundle boundaries re-verify every record's bytes and bound artifacts (V4) under the running `m1c-corporate-action-coverage-v1` identity (V10); the engine refuses exploratory coverage under a promotion admission (V12) and, in the reconstructed lane, a record whose bytes the replay contexts do not retain (C7). The grade follows the source: exploratory coverage is exploratory only, and nothing makes it promotion grade. The field is construction-additive but hash-changing, so every bundle hash moved once; the pinned run hashes that bind a bundle were re-pinned at their pins with that cause, and a field-by-field diff shows no non-hash leaf moving other than admissions acknowledging the new limitation. Non-trading runs (B0) are unaffected: nothing is exposed, so nothing needs coverage. Decision packet DP-1 is resolved from first-party evidence: Alpaca's API reference for `GET /v1/corporate-actions` (API version 1.1, page last updated 2026-05-27) enumerates 16 `types` values, the bridge requests all 16, and a quiet window under a positive record now evidences no action. A measured request that omits a type the bridge declares is refused at intake (`ca_coverage_action_classes_incomplete`, V8); records are non-positive only when the bridge's own declared list omits a documented type, and then their exposed windows halt `INDETERMINATE` (section 21 amendment, issue 76). Known residual (as for issue 71's V5): the Drift core cannot re-parse provider bytes, so a hand-minted, self-consistent record whose bound artifacts are retained evidences whatever it states; it remains exploratory evidence only. Known residual (V8 is bridge-only, like V5): the core is provider-neutral and cannot know a provider's documented action types, so the record's own V8 check is only that `requested_action_classes` is nonempty, sorted and unique; the full documented set is enforced by the bridge alone (`ca_coverage_action_classes_incomplete`, and the structural check behind `requested_types_documented`). A hand-minted record naming fewer classes, with `requested_types_documented` set, is positive in the core; it too remains exploratory evidence only. This corrects the contract draft on #76, which listed V8 under the M1c domain as well as the bridge.

**Amendment, issue 72 (owner ruling of 2026-09-24, option C; supersedes the issue 55 trust boundary on riding reconstructions).** The review of issue 55 found that the engine never re-derives a reconstruction riding a realized-clock bundle: only the reconstructed lane takes the cohort and replay that re-derivation needs. Reviewer probe P1 showed a forged, self-consistent reconstruction (close 250.000 and an invented limitation) riding a realized bundle through an exploratory run, bound into its result by bundle hash and carried in its admission. No production producer builds that shape (the Alpaca bridge builds a scheduled clock, and a promotion bundle carries no reconstruction), so the shape itself is refused. `require_reconstructions_on_scheduled_clock` (`src/drift/domain/evaluator_bundles.py`) refuses any `exploratory_reconstructed_observations` on a clock whose mode is not `scheduled_session_reconstruction`, naming issue 72. The `EvaluationInputBundleV1` model validator applies it, so every construction route refuses the shape: `assemble_evaluation_input_bundle`, `build_evaluation_input_bundle` even from a genuine cohort and replay, direct construction, and `model_validate`. The engine revalidates every bundle at construction (issue 78), so a bundle built past validation with `model_construct` is refused before any lane is resolved, and both bundle boundaries (`build_evaluation_input_bundle` and `verify_evaluation_input_bundle`) apply the same rule themselves, so such a bundle cannot verify against genuine replay either. A reconstruction therefore only ever rides a scheduled clock, whose lane re-derives every one before anything reads it. `validate_exploratory_admission` is unchanged and still runs for every exploratory admission (issue 56); on a realized clock it now obliges only the clock's and the dataset's limitations, because no riding reconstruction remains to oblige one. The issue 54 statement that a realized-clock bundle never prices from a riding reconstruction now holds because no such reconstruction exists. The grade is unchanged.

**Amendment, issue 87 (owner ruling A, extended to contiguity under the owner's fail-closed operating rule recorded on #62; causality finding F4 of the #8 final acceptance).** The reconstructed decision context was satisfied when any cohort member had a reconstruction for the decision session. A member missing its bar therefore reached the strategy with history ending at an earlier session, read as current: a lookback indexed by position spanned misaligned sessions, a target for the member filled at the next open, and the run was COMPLETE. The context now guarantees contiguous, current history per member. Each reconstructed decision selects its history as before (issue 66). It then requires every cohort member with at least one reconstruction in that history to have one for every history session, in clock order, from its first reconstructed session through the decision session itself. If any member has a gap, Phase 5 halts `INDETERMINATE` (`indeterminate_valuation`, phase `post_close_decision`) before the context is built and before the strategy is asked, so nothing is staged at that close and nothing fills from it. The cause names the decision session and, in canonical security order, every gapped member with its first reconstructed session and each session it lacks. The halt applies whether or not the strategy would trade the member, because the context is incomplete either way. A member whose reconstructions stop therefore halts the first decision after its last bar. A warmup session takes no decision, so a gap on one halts the first decision whose history contains it. After the warmup every session decides, so a gap there halts at its own decision. A member with no reconstructed history at the decision cutoff follows the existing rules. It has no view in the context and stays in `admitted_cohort`, so a target for it stages, and it trades only if the execution session carries its reconstructed open; otherwise Phase 2 halts `INDETERMINATE` on the missing price. A member whose first reconstruction comes later joins the context at that session, and the sessions before its first reconstruction are not gaps. When no member has a reconstruction for the decision session, the existing halt for missing decision evidence still applies, and a held member missing its bar still halts earlier, at the Phase 4 mark. A context in which every member with history is contiguous and current is unchanged, byte for byte.

**Amendment, issue 130 (decided under the owner's fail-closed operating rule recorded on #62; finding F2 of the PR 129 review).** This refines the issue 87 rule for members without history, for targets only. Where they conflict, it supersedes that amendment's statement that such a member stays in `admitted_cohort` and a target for it stages, and the issue 46 Phase 5 note that staging validates against the declared cohort. A cohort member with no reconstruction at or before the decision cutoff had no view in the context but stayed admitted, so a strategy could target it with no decision-time evidence at all. When the member's first reconstruction followed, the target filled at that first-ever reconstructed open and the run was COMPLETE. A cohort chosen after the fact therefore disclosed that the security would exist and trade later, which is lookahead carried by cohort construction. Each reconstructed decision's `admitted_cohort` is now the declared cohort restricted to the members with reconstructed history at or before its cutoff, selected as in issue 66. After the issue 87 contiguity check these are exactly the members the context carries a view for. `stage_exploratory_decision_targets` stages against that set unchanged, so a positive target naming any other member is REJECTED at staging with the existing unadmitted-target cause (`a positive target requires an admitted security: <security>`). Nothing is staged at that close and nothing fills. A zero target is never refused for want of admission, and a held security the intent omits is still staged at zero, so an exit is never blocked; a member without history cannot be held in this lane anyway. A late starter is admitted, and so targetable, from the first decision whose history holds its first reconstruction, including a first reconstruction on a warmup session. The context still carries no view for a member without history, and `cohort_hash` still binds the declared cohort. A run in which every declared member has history at every decision is unchanged, byte for byte. A run in which the admitted set shrinks at some decision changes only the `context_hash` of each such decision, and through it the trace hash and the result's `trace_hash` and `result_hash`. Its intents, staged targets, fills, marks and metrics are unchanged unless it targets a member the decision no longer admits.

**Amendment, issue 141 (owner ruling A of 2026-09-28, the realized counterpart of the issue 87 amendment above, extended to contiguity under the owner's fail-closed operating rule recorded on #62 (comment of 2026-09-25T17:43:45Z) exactly as issue 87 was; finding FA1 F3 of the M2 final acceptance rerun).** The issue 87 ruling closed the stale-as-current hazard for the reconstructed lane only. In the realized lane, `_decision_views` selects a security's decision evidence by its query's decision time, and neither it nor `StrategyDecisionContextV1` required a security with evidence at the cutoff to carry a view sourced from the decision session, or from any session in between. A security whose newest evidence was an earlier session therefore reached the strategy as though it were current: in the reviewer probe, a 2026-01-07 decision where SEC_A's newest view was its 2026-01-06 bar while SEC_B was current, 10 SEC_A filled at the 2026-01-08 open and the run was COMPLETE. Separately, `StrategyDecisionViewV1.canonicalize_views` held a security's views in content-hash order, so the probe's history read 2026-01-06 before 2026-01-05. The owner's ruling adopted the halt and the date order, mirroring the protection established for issue 87; because that protection was extended to contiguity under the fail-closed rule, which prefers the safer option for implementation decisions it covers, the realized rule is extended the same way, as an implementation decision under that rule. Two rules now hold. First, the realized context guarantees contiguous, current history per security. Each realized decision takes as its history the clock sessions the reconstructed lane selects (issue 66): the stepped sessions closed by the decision cutoff, in clock order, ending at the decision session. After the context is built, and so after its causality checks have refused any view sourced after the decision session or otherwise acausal (those still fail loudly, never as a halt), every security with at least one decision view at the cutoff must have a view sourced from every history session, in clock order, from its first viewed session through the decision session itself. A session is its full key (venue, scope and date), so a same-date view from another venue does not count, and a date the clock does not step, such as a weekend or holiday, is not a session and never a gap. If any security has a gap, Phase 5 halts `INDETERMINATE` (`indeterminate_valuation`, phase `post_close_decision`) before the strategy is asked, so nothing is staged at that close and nothing fills from it. The cause reads `incomplete decision context at the realized decision session <MIC> <date>: ` followed, in canonical security order, by one clause per gapped security, `security <id> has decision evidence from <MIC> <date> but no view sourced from <MIC> <date>, ...`, naming its first viewed session and each session it lacks in clock order. The halt applies at every decision, the first included, whether or not the strategy would trade the security and whether or not the universe admits it, because the context is incomplete either way. A security whose first view comes later joins the context at that session, and the sessions before its first view are not gaps. A security with no decision evidence at the cutoff has no view and follows the existing rules, and when no security has any, the existing halt for missing decision evidence still applies. A view sourced from a session outside the decision's history is refused loudly (`ValueError`) rather than judged; the bundle holds only clock sessions, the context refuses a later date, and a same-date multi-venue clock is refused at engine construction (issue 97), so that refusal is defense in depth. Second, `canonicalize_views` orders each security's views by source session (local date, then venue, then scope, as the reconstructed lane orders its observations), breaking a tie between views of one session by content hash, so a strategy reads its history oldest first whatever order the views arrive in. Uniqueness and every other check are unchanged. A context in which every security is contiguous and current and each security's views were already in session order is unchanged, byte for byte; a multi-view context whose hash order differed from session order moves its `context_hash`, and with it the trace and result hashes, and a run that completed on stale or gapped evidence now halts `INDETERMINATE`, which is the defect being fixed. No pinned run hash moves, because every pinned realized run carries one view per security at each decision; a field-by-field diff against `3fecbf2` of two-security runs carrying full history, or history starting after the clock's first session, shows only the `context_hash` of the two decisions whose hash order differed, the trace hash and the result hash moving. `tests/adversarial/test_m2_realized_stale_member.py` pins both rules.

### 7.2 Exploratory Business-Time Causality Invariant

Exploratory relaxation of publication vintages does NOT permit future business-time leakage:
- **Historical Business-Time Ordering**: The strategy at session $D$ post-close may see only historical business-time facts up through session $D$ under its declared reconstruction policy.
- **Strictly Prohibited at Session $D$**:
  - Session $D+1$ or later market prices (open, high, low, close, volume).
  - Later-session returns or future price movements.
  - Future corporate action effective dates before their business-time occurrence.
  - Ex-post labels, future universe exits, or target forward outcomes.
- **What Exploratory Relaxes**: Provider publication/revision availability timestamps (e.g. a corrected 2022 bar retrieved in 2026 may be used in an exploratory backtest of 2022). It does NOT relax chronological business-time ordering.

### 7.3 Promotion Inputs: Authentic Decision Information

Promotion lane strategy inputs strictly require:
- `InformationRole.DECISION_INFORMATION`
- `ResolutionMode.AS_KNOWN` where applicable
- `ObservationDecisionReferenceV1` / decision-role normalization
- Historical publication and availability cutoffs verified under positive M1e qualification.

### 7.4 Input Bundle and Replay-Bound Preparation

A compact runtime bundle exposes numeric views for execution efficiency, but bundle preparation must verify that every view derives from exact upstream Drift kernel replays rather than untrusted Pydantic construction:

**Amendment, cross-slice adversarial finding F2 (lane leakage).** Replay-boundness alone did not stop a bundle from carrying evidence for sessions its own clock never contained, which let evidence from one corpus ride into an evaluation authorized over another. `EvaluationInputBundleV1` now fails closed in its own validator when any `authentic_decision_views[*].source_session`, any `authentic_accounting_views[*].source_session`, or any `exploratory_reconstructed_observations[*].session_key` is absent from `session_clock`, and when the clock's span escapes `evaluation_interval`. A split-normalization `anchor_session` is deliberately exempt: it is a normalization reference point, not evidence consumed over the interval. This is complementary to the issue 34 provenance proof, which binds contents to a snapshot rather than to the clock.

```python
class EvaluationInputBundleV1(FrozenModel):
    """Complete, proof-carrying input bundle for an evaluation interval."""

    schema_version: Literal["1"] = "1"
    evaluation_interval: TemporalIntervalClaimV1
    source_snapshot_hash: SHA256Hash | None = None  # Bound for M1e promotion
    session_clock: SessionClockV1
    security_identities: tuple[SecurityV1, ...]
    listing_identities: tuple[ListingV1, ...]
    structural_eligibilities: tuple[StructuralEligibilityResultV1, ...]
    economic_outcomes: tuple[EconomicOutcomeResolutionV1, ...]
    authentic_decision_views: tuple[DerivedObservationViewV1, ...]
    authentic_accounting_views: tuple[DerivedObservationViewV1, ...]
    exploratory_reconstructed_observations: tuple[
        ExploratoryReconstructedSessionObservationV1, ...
    ] = ()
    bundle_hash: SHA256Hash  # self-excluding canonical content hash

    @property
    def has_exploratory_reconstructions(self) -> bool:
        return bool(self.exploratory_reconstructed_observations) or (
            self.session_clock.mode == "scheduled_session_reconstruction"
        )
```

**Preparation Boundary (`build_evaluation_input_bundle` / `verify_evaluation_input_bundle`)**:
1. **Promotion Decision Views**: Replays and materializes each view using `materialize_observation_decision(reference, query, context)` with `M1dResolutionContext`, verifying exact match with `ObservationDecisionReferenceV1`.
2. **Accounting Outcome Views**: Replays and materializes unadjusted views using `materialize_observation_outcome(reference, query, context)`.
3. **Exploratory Strategy Views**: Constructs `ExploratoryReconstructedSessionObservationV1` through `build_exploratory_reconstructed_session_observation(query, context, cohort, policy)` under an `ObservationOutcomeQueryV1`, using existing M1d source selection and schedule generation, with explicit retrospective/unversioned limitations. It never yields `ObservationDecisionReferenceV1`, `ObservationOutcomeReferenceV1`, or `DerivedObservationViewV1`. Issue 55: `build_evaluation_input_bundle` derives them itself from `exploratory_cohort` and `exploratory_reconstruction_replay` and never accepts them from the caller, and `verify_evaluation_input_bundle` re-derives them and requires exact equality; both replay them against the same `M1dResolutionContext` as the views and bind a scheduled clock's calendar rows, and a bundle carrying reconstructions without replay inputs is refused.
4. **M1b Universes**: Replays and verifies `StructuralEligibilityResultV1` against selection context. Promotion strictly requires `ResolutionMode.AS_KNOWN` plus `InformationRole.DECISION_INFORMATION`. Exploratory evaluation is scoped by `ExploratoryCohortAuthorizationV1` instead of historical structural eligibility, because `resolve_structural_eligibility` correctly accepts only as-known decision information; `CURRENT_INTERPRETATION` plus `EX_POST_OUTCOME` structural evidence does not exist and must not be built by M2. The cohort mechanically binds `ALPACA_LIMITATION_BOUNDED_COHORT` in the exploratory admission.
5. **M1c Economics**: Replays and verifies `EconomicOutcomeResolutionV1` against M1c selection context, proving terms, occurred effects, and delivered settlements independently.

**Amendment, issue 80 (part of the issue 31 Decision 4 ruling; Decision 4 is not complete).** Items 4 and 5 were specified but never implemented, and the session clock was never re-derived either: structural eligibility, economic outcomes, security and listing identity, and session-clock authority were bound only by their own content hashes, so a realized clock with invented authority, a scheduled calendar row relabelled as realized, and a fabricated `AS_KNOWN` universe each obtained a proof through build, mint and gate. `verify_evaluation_input_bundle` now takes `session_queries`, `structural_requests` (each a `(ListingV1, security_id, NormalizedSelectionQueryV1)` triple) and `economic_requests` (each a `MarketSelectionQueryV1`), the way it takes `(reference, query)` view requests, and re-derives each class through its one canonical builder against the one M1d context it is handed, requiring exact canonical equality: the clock through `build_realized_session_clock` or `build_scheduled_reconstruction_clock`, chosen by the bundle clock's own mode (`verify_session_clock`); structural eligibility through `resolve_structural_eligibility` over the context's M1b evidence (`structural_context`, `research_definition`, `issuer_id`, `structural_methodology_id`, all bound by the context identity); and economic outcomes through `resolve_economic_facts` over the context's M1c evidence. A bundle carrying a structural eligibility or an economic outcome without its request is refused by count, as a view is. A realized clock without its session queries is refused. A scheduled-reconstruction clock is re-derived whenever its queries are supplied; without them it is not re-derived here. That is a known gap, not a safety argument: such a clock's session times are then only as trusted as the caller that built it. It cannot reach promotion, because the promotion gate refuses its mode, and requiring its queries is left to the scheduled-lane clock work of issue 84, which it overlaps. Minting always supplies the queries, and every other present caller of the verifier is a test; the Alpaca bridge never calls it. `mint_bundle_provenance_proof` requires `session_queries` (keyword-only, no default), passes every request to verification, and also binds every `SecurityV1` and `ListingV1` the bundle carries, every member of both, to an identity that an `ASSIGNED` record of the context's M1b identity assignments carries; an unassignment record attests nothing, the venue is part of a listing's identity, and a bundle carrying identities over a context with no M1b evidence cannot mint. `BundleProvenanceProofV1` gains `session_request_hashes`, `structural_request_hashes` and `economic_request_hashes`. The change is construction-additive but hash-changing: each field defaults to `()`, so every existing construction still validates, and each is covered by `proof_hash`, so every proof hash changes. `build_evaluation_input_bundle` is unchanged and still accepts a caller-supplied clock, eligibilities, outcomes and identities; they become trusted only once verification or minting re-derives or binds them. Decision 4 coverage is not complete with this amendment. The engine's `SessionEvaluatorEvidence` is not yet bound to the qualified context, and the request sets are chosen by the caller, so omitting a session or a structural eligibility can still change an evaluation result. Both are tracked separately.

**Amendment, issue 92 (owner ruling A).** A dataset-level limitation had no bundle evidence obliging it. The Alpaca bridge's admission acknowledges all six Alpaca limitations, and five were already obliged: the scheduled clock and the reconstructions declare their own, and the engine's lane gate requires the bounded-cohort acknowledgement. The sixth, `ALPACA_LIMITATION_TRUNCATED_CA`, describes the bridge's corporate-action data window, which no evidence member declares, so an admission minted outside the bridge over the exact bridge bundle could omit it and the run still completed. `EvaluationInputBundleV1` gains `dataset_limitations: tuple[NonBlankStr, ...] = ()`, the producer's declarations about its dataset itself. It follows the sibling limitation fields of `SessionClockV1` and `ExploratoryReconstructedSessionObservationV1`: free non-blank strings, duplicates refused, canonically sorted. It is deliberately not a closed vocabulary. A limitation only ever obliges more acknowledgement and keeps a bundle out of promotion, so an unknown string grants nothing, and refusing one would add no safety while making every new producer amend the domain module. The field is covered by `bundle_hash` and is part of `required_limitations`, so `validate_exploratory_admission`, and through it the engine's lane gate, refuses an admission omitting any declared dataset limitation, and the promotion gate's existing refusal of a bundle declaring any limitation covers it unchanged. Nothing re-derives a producer's declaration: verification and minting bind it only through the bundle hash, so a bundle declaring one still builds and mints, and the promotion gate refuses it. `assemble_evaluation_input_bundle` and `build_evaluation_input_bundle` take `dataset_limitations` as a keyword argument defaulting to `()`. The Alpaca bridge declares exactly `ALPACA_LIMITATION_TRUNCATED_CA` through it; its admission still acknowledges the same six limitations, and every other member of its bundle is byte-identical. The change is construction-additive but hash-changing: the field defaults to `()`, so every existing construction still validates, and the canonical dump includes it, so every bundle hash changes, and with it every admission, run identity and result hash that binds one. No evaluation bundle hash is persisted or pinned in the repository. Residual: the obligation is only as complete as the producer's declaration. A bundle re-assembled from the bridge's members without it is a different bundle under a different hash, which the bridge never emits.

### 7.5 Session Clock Contract (Realized vs Scheduled Reconstruction)

M2 defines two distinct clock authority modes via `SessionClockMode = Literal["realized_session_authority", "scheduled_session_reconstruction"]`:

```python
class EvaluationSessionV1(FrozenModel):
    """One evaluation session boundary with bound proof authority."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    opened_at: UTCDateTime
    closed_at: UTCDateTime  # must be strictly after opened_at
    authority: Literal["realized", "scheduled_reconstruction"]
    authority_record_hashes: tuple[SHA256Hash, ...]
    authority_proof_hashes: tuple[SHA256Hash, ...]
    session_hash: SHA256Hash  # self-excluding canonical content hash


class SessionClockV1(FrozenModel):
    """Immutable content-addressed sequence of evaluation sessions."""

    schema_version: Literal["1"] = "1"
    mode: SessionClockMode
    sessions: tuple[EvaluationSessionV1, ...]  # nonempty, unique keys, chronological
    acknowledged_limitations: tuple[NonBlankStr, ...]
    clock_hash: SHA256Hash  # self-excluding canonical content hash
```

- **`PROMOTION` Lane**: Strictly requires `mode == "realized_session_authority"`, whose sessions bind authentic selected `RealizedSessionVersionV1` instances with proven `outcome="opened"` and non-null `actual_open`/`actual_close` (`closed` strictly after `opened`), plus their exact selection proof and record identity hashes. A `did_not_open` or `unknown` realized outcome can never produce an evaluation session. Early closes use the proven `actual_close`; nothing hardcodes 16:00 or 09:30.
- **`EXPLORATORY` Lane**: Uses realized authority when genuinely available, or `scheduled_session_reconstruction` built from existing M1d scheduled selection plus the `generate_schedule(...)` pipeline. An included scheduled session requires artifact `classification == "generated"`, output `interpretation_status == "authorized"`, state in (`regular`, `early_close`), and non-null generated UTC open/close. Early closes preserve the exact generated close. The clock's limitations include `ALPACA_LIMITATION_ABSENT_HALTS` and `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`.
  - Under scheduled reconstruction the clock NEVER manufactures synthetic `RealizedSessionVersionV1` instances and NEVER claims "no halt occurred" or "actual open proven."
  - If a scheduled session is expected open but required market observations fail to materialize, later evaluation is `INDETERMINATE`; the clock records neither `did_not_open` nor a halt cause.
- **Anti-Laundering Gate**: Promotion admission strictly rejects any bundle configured with `scheduled_session_reconstruction`.

**Amendment, issue 84 (clock integrity).** `SessionClockV1` orders sessions by their UTC boundaries (`session_order_key`) and refuses any session that opens before its predecessor closes. It now also requires local dates to be non-decreasing in clock order; with unique (MIC, local date) keys, each venue's dates then strictly increase. Together these carry the ordering guarantee: every stepped session has closed by the next open, so the stepped prefix is exactly the history closed at a decision cutoff, and the issue 66 history filter in `reconstructed_history_sessions` is defense in depth behind the non-overlap guard. These guards refuse decreasing-date inversions only; they do not prove that a session's UTC stamps belong to its local date. Restriction: a multi-venue clock whose sessions overlap in UTC (including the issue 66 case, a same-date session opening first and closing after an early close), or whose later local date precedes an earlier one in UTC, is out of scope for M2 and refused. A non-overlapping multi-venue clock with two sessions on one local date is admitted by the clock, and refused at engine construction (the issue 97 amendment, section 13.1). In the EXPLORATORY reconstructed lane the issue 55 principle now covers clock sessions as well: after re-deriving the reconstructions, the lane gate rebuilds each replay request's session with `build_scheduled_reconstruction_clock((query,), context)` and requires every clock session a reconstruction is on to equal one of the sessions re-derived for it exactly. The selection proofs a session carries name the query that selected its row, so only a request sharing that query can reproduce them: a scheduled clock must be built from the replay's own queries, and a genuine session selected by any other query is refused. Every other request on the session names the same calendar row through `require_scheduled_calendar_row`, and so the same boundaries; a session naming the records of two rows at once, which that binding alone admits, is refused as well. A refusal names what differs: the boundaries, the calendar records, or only the selection proofs. A clock session no reconstruction is on is not re-derived here. It is still stepped and checkpointed, so a warmup session without one appears in the run, but it is never priced or decided on: a decision, a trade, or a held mark on it is `INDETERMINATE` under the missing-bar rule above. Known residual: the engine never re-derives the boundaries of a realized clock, which an exploratory admission may evaluate. A lagged realized clock, whose local dates stay non-decreasing while each session carries a later session's UTC stamps, passes every issue 84 guard, and a decision can then fill at an open printed before its cutoff. The issue 96 amendment below closes that residual at the preparation boundary, superseding the follow-up this paragraph left open; re-deriving a realized clock for promotion is issue 80.

**Amendment, issue 96 (the EXPLORATORY realized lane's trust boundary; owner ruling B together with A).** This closes the issue 84 known residual at the preparation boundary, and for the clock it supersedes the section 7.4 issue 80 statement that `build_evaluation_input_bundle` accepts a caller-supplied clock unverified. `build_evaluation_input_bundle` now takes `session_queries` and holds the clock to the one rule `verify_evaluation_input_bundle` applies, through the same `verify_session_clock` re-derivation rather than a second one: a realized clock is rebuilt from its session queries over the one M1d context the builder is handed and must equal that build exactly, so a clock differing in any session, boundary, authority record, proof, or limitation is refused as not matching its canonical re-derivation, and a realized clock without its session queries is refused. The lagged clock of the issue 95 review (DAY_0 on its own times, DAY_1 on DAY_2's, DAY_2 on DAY_3's, every session key and authority hash genuine) is therefore refused where it is built, as are invented authority hashes, a scheduled calendar row relabelled as realized, and a session added to, or omitted from, what the queries select. Correction (issue 140): that refusal holds only while the M1d realized records are dated correctly. The re-derivation proves that a clock equals what its records say, not that the records' UTC stamps belong to their local dates, so the same lag moved into the records themselves re-derived faithfully and was accepted at both boundaries; the issue 140 amendment below closes that. The caller still names the clock it expects, and the builder carries it once it is proven equal to its derivation, so a genuine clock builds a byte-identical bundle. `session_queries` defaults to `None` because, as in verification, a scheduled-reconstruction clock is re-derived only when its queries are supplied: the Alpaca bridge supplies none, and the lane gate re-derives the sessions its reconstructions sit on (issue 84). Which sessions the queries request is the caller's choice, exactly as for verification; complete request coverage is issue 101, a prerequisite for re-enabling the promotion lane. Trust boundary: in the EXPLORATORY realized lane trust enters at the preparation boundary, `build_evaluation_input_bundle` and `verify_evaluation_input_bundle`, and nowhere later. The engine does not re-derive a realized clock, in contrast with reconstructions, which its lane gate re-derives (issue 55) together with the clock sessions they sit on (issue 84). A bundle assembled directly, through `assemble_evaluation_input_bundle` or model construction, bypasses the preparation boundary and is test-only; no production path assembles one. The engine runs whatever such a bundle carries, a lagged realized clock included, and whatever evidence any exploratory run yields is exploratory and non-promotable (section 4.4). The engine is unchanged.

**Amendment, issue 140 (a realized session's UTC stamps belong to its local date).** `build_realized_session_clock` now refuses, with `RealizedSessionLocalDateError` (a `ValueError`), a selected `opened` realized record whose `actual_open` or `actual_close` does not fall on its `session_key.local_date` in the venue's local time. M1d binds neither stamp to the date (`RealizedSessionVersionV1` checks outcome shape, bound order and payload hash, and M1d session validation adds no stamp-to-date check), and its files are pinned, so the check sits in the realized builder; `verify_session_clock`, `build_evaluation_input_bundle` and `verify_evaluation_input_bundle` inherit it through the issue 80 and issue 96 re-derivation. The venue's local time comes from the venue-time authority M1d holds: the authorized generated schedule row of the same session key, from the `generate_schedule` pipeline the scheduled clock uses. Its UTC boundaries are its local labels less row-bound historical offsets, each proven by a retained authority artifact available by the query's cutoff and agreeing with the exact TZif reconstruction, so a label less its authorized UTC instant is that boundary's offset on that date. Each stamp is read at its own boundary's offset (the open at the open's, the close at the close's) and must land on the record's local date: a stamp past UTC midnight but on its local date is admitted, and each stamp is checked on its own. A realized opening whose date has no authorized generated open and close (a closed, unknown or indeterminate calendar row, or none) is refused as unplaceable rather than read against the UTC calendar. M1d holds no other venue-local time, so a realized clock now needs the schedule generation policy and the scheduled-session and coverage bindings a scheduled clock needs. The source-record form of the issue 95 lag (2026-11-27 stamped with 2026-11-30's regular hours and 2026-11-30 with 2026-12-01's, every other byte of the corpus genuine) is refused at the clock build and at both bundle boundaries, and a genuine realized clock is byte-identical. A scheduled clock needs no such check: its UTC boundaries are derived from local labels that M1d validation holds to the session key's date. Known limitation: a stamp is read at the offset authorized for its scheduled boundary, not at one reconstructed for the stamp's own instant, so an offset change between the two would shift the reading by that change. The section 13.1 issue 84 amendment's statement that issue 96 closes the section 7.5 residual is qualified in the same way: issue 96 closes the lag in a clock, and issue 140 closes it in the realized records.

**Amendment, issue 147 (a split view's anchor stamps belong to its local date; owner ruling C on 2026-09-28: option B now as M2 closure scope, option A as issue 151).** Split normalization reads realized session stamps without checking whether they belong to their local date. When an anchor record's stamps are moved across its boundary, its split factor can flip between 1 and the split's ratio: in the reviewer probe, an unadjusted close of 100 on an anchored 2:1 split materialized as 50 (applied a session early) or 100 (split dropped), and `build_evaluation_input_bundle` and `verify_evaluation_input_bundle` accepted both, as did `StrategyDecisionContextV1` causality. It is not lookahead: M1d still gates the split, its transition bound and the anchor open to the cutoff, and accounting views are source basis, so fills and marks are unaffected. No production producer reaches it today, because the Alpaca bridge mints no realized session and emits no derived view. `build_evaluation_input_bundle` and `verify_evaluation_input_bundle` (the latter right after decision-view replay, and so `mint_bundle_provenance_proof`, which verifies) now hold every split-normalized decision view's anchor evidence to the issue 140 check, and refuse a view whose anchor stamp is off the anchor's local date with `AnchorSessionLocalDateError` (a `DriftError` and a `ValueError`, in `src/drift/evaluator/bundles.py`). The refusal names the view's security, its anchor session, the evidence, the boundary, the stamp and the local date it falls on (`split-normalized decision view of security ... anchored on XNYS 2026-11-27: the anchor's realized session actual open 2026-11-28T14:30:00+00:00 falls on venue local date 2026-11-28, not its session date (issue 147)`). The anchor is checked directly, rather than required to be a clock session, because an anchor legitimately need not be one, and reading it needs no pinned M1d file. Its evidence is re-read exactly as M1d reads it. The anchor query is the view's own observation query moved to the anchor's date. When that query selects one completed `opened` realized record, the anchor open was that record's `actual_open`, and both of its stamps are checked, as the realized clock checks a record. For an anchor that is the view's own source session, this is the record the source binding selects. Otherwise the view materialized on the record's opening evidence, and the open of the one `AnchorOpeningEvidenceV1` that the view's fresh normalization cites (it must replay the view itself) is checked. An anchor open that cannot be located that way is refused too, as is a split-normalized view carrying no anchor. There is one reading, `realized_stamps_local_date_refusal` in `src/drift/evaluator/clock.py`. It is extracted from the issue 140 builder, whose behaviour and messages are byte-identical. It reads each stamp at its own boundary's authorized offset on the anchor date's generated schedule row, so across an in-session offset change the open is read at the open's offset and the close at the close's. An anchor date without an authorized generated open and close is refused as unplaceable, so, as a realized clock does since issue 140, a bundle carrying a split-normalized decision view now needs the schedule generation policy and the scheduled-session and coverage bindings of its anchor dates (the Alpaca bridge requests no decision view, and is unaffected). A stamp past UTC midnight but on the anchor's local date is admitted. A source-basis view has no anchor, and nothing is read for it. No realized record other than an anchor's is read. Every genuine bundle, hash and run is therefore unchanged. Known limitations: this guard does not fix the M1d defect, and it closes the factor path only inside a bundle. M1d's recorded action-mapping provenance stays uncorrected: a misdated record strictly between source and anchor leaves the factor unchanged but records a false first-post-session mapping, and the guard, which reads only the anchor, admits such a view. Split views outside a bundle stay uncorrected (an outcome-role view, or any consumer of M1d normalization directly), and so does observation binding. The issue 140 limitation applies unchanged: a stamp is read at its scheduled boundary's offset, not at one reconstructed for its own instant. The canonical fix is M1d's, issue 151: refuse, with a distinct reason, any realized stamp off its local date at the generated row's per-boundary offset, in `_realized_bounds`, `_anchor_basis` and `bind_observation_session`, under a new M1d freeze supersession. It is mandatory before any realized-session provider is admitted (a prerequisite of issue 115 and of M1e Task 8), and this guard is not a substitute for it.

**Amendment, issue 71 (scheduled clock density; ruling Q18 of #62, decisions D1 to D9).** Next-open execution (section 13.1), the kernel's advance and the corporate-action session windows all read "not a clock session" as "not a trading date". A scheduled-reconstruction clock now earns that reading from evidence. M1d gains `ClosedWorldSessionCoverageV1` and its derivation (the M1 design spec, section 8.1 amendment): a date is `scheduled_open`, `evidenced_non_trading` or `indeterminate`, and `indeterminate` never defaults to closed. Consumer rules, each failing closed: (R1) the Alpaca bridge refuses at intake a window whose run span holds an INDETERMINATE date (section 21 amendment, issue 71); (R3, R4, R7, D8-b) in the EXPLORATORY reconstructed lane the engine's lane gate, after the issue 84 re-derivation, calls `require_evidenced_clock_density` (`src/drift/evaluator/bundles.py`). It re-verifies every closed-world record the replay's own M1d contexts carry, refusing an integrity failure by its code, and requires every local date strictly between two consecutive clock sessions to be `evidenced_non_trading` for the venues of both. A date that is instead scheduled open (a clock that skips a trading day) or INDETERMINATE (uncovered, or in conflict) halts the evaluation `INDETERMINATE` at construction, raising `IndeterminateExecutionError` that names every such date; the engine never skips to the next known open. A clock session on a date the evidence reads as `evidenced_non_trading` is a conflict (D7-a) and halts the same way. This is D6-c's defense in depth, applied before any session is stepped rather than when the run reaches the date, which is stricter. The clock itself is still built over the returned dates only (R2 as drafted, one clock query per calendar date, is not used): the pinned generator answers `indeterminate` for a closed date under the bridge's schedule policy, so density is proven by the record and not by the generator. (R8) Closed-world coverage is exploratory-grade only (D3-a); promotion already refuses scheduled clocks, the promotion lane stays disabled, and any future realized-clock use (#101) must refuse exploratory-grade records. Realized clocks are out of scope here and left to #101. Known residual (D4-A): the plain M1d validators cannot tell a derived closed row from a provider-printed one, so the enforcement points must stay exhaustive; the next one is the M3 runner re-validation (#68, M3-R5). Known residual (V5 is bridge-only): the Drift core may not read the provider format, so only the bridge re-parses the retained calendar bytes into the record's returned dates. In a hand-built context, a forged but self-consistent record (re-sealed, its bound artifacts retained, its open rows over the covered interval exactly its returned dates, its closed rows exactly its expansion and its coverage row exactly its hull) passes `verify_closed_world_session_coverage` and evidences whatever returned dates it claims, so the lane gate can read a trading date it omits as non-trading. Such a context is still exploratory evidence only and can never be promoted. The density check's two-venue case is exercised both directly and through the engine: the lane gate re-derives only the clock sessions a replay request sits on, so a session on another venue that no request derives reaches the density walk, which checks the venues of both sessions of every step (PR 137 re-review, L1).

### 7.6 No False Halt Syntheses
M2 removes artificial boolean flags like `is_halted: bool = False`. If an observation source (such as Alpaca) does not provide authenticated halt telemetry, halt status is `UNKNOWN`. The evaluator core relies on M1d realized session facts (`outcome="opened"` vs `"did_not_open"`) rather than inventing "not halted" claims.

---

## 8. Temporal Decision Clock and Session Scheduling

M2 implements a strictly causal, lookahead-free evaluation clock driven by authenticated M1d realized session timestamps:

```
Session D (Realized Trading: actual_open -> actual_close)
  |
  +-- Session D actual_close reached (e.g. 16:00 ET normal, 13:00 ET early close)
  |
  +-- Post-Close Cutoff: Session D observations seal under M1d decision cutoff
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D close information set
        Strategy emits target intent for Session D+1
        NO same-day execution permitted
  |
  v
Session D+1 (Next Eligible Realized Regular Trading Session)
  |
  +-- [PHASE 1: PRE_OPEN_EFFECTS]
  |     Apply occurred corporate action share conversions (with FractionTreatmentV1)
  |     Adjust staged target quantities for corporate action splits
  |     Record dividend receivables where M1c proves holding entitlement
  |
  +-- [PHASE 2: OPEN_EXECUTION] (at Session D+1 actual_open)
  |     Plan-then-commit atomic rebalance:
  |       1. Fetch unadjusted open prices from M1d source-basis views
  |       2. Calculate all sell proceeds and buy costs
  |       3. Verify complete target rebalance is 100% funded
  |       4. If funded: commit sells first, buys second
  |       5. If unfunded: reject rebalance, commit NO fills, mark REJECTED
  |
  +-- [PHASE 3: INTRASESSION_EFFECTS]
  |     Settle pending cash claims where delivered settlement proves delivery
  |
  +-- [PHASE 4: CLOSE_MARK] (at Session D+1 actual_close)
  |     Mark portfolio at Session D+1 unadjusted CLOSE price
  |     Record session NAV and trace
  |
  +-- [PHASE 5: POST_CLOSE_DECISION]
        Strategy receives Session D+1 close information set...
```

### 8.1 Variable Session Hours (Early Closes)
The regular trading session close is NOT hardcoded to 16:00 ET:
- **Promotion Lane**: On scheduled or unscheduled early-close sessions (e.g. 13:00 ET on Christmas Eve or day before July 4th), Phase 5 post-close decision occurs immediately after the proven realized close (`actual_close`). No artificial delay to 16:00 is enforced. Execution at Phase 2 occurs at the next proven realized `actual_open`.
- **Exploratory Lane (Scheduled Reconstruction)**: When realized history is unavailable, the clock derives the early close directly from `ScheduledSessionVersionV1` (e.g. 13:00 close). Phase 5 executes immediately after 13:00, carrying `ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION`.

### 8.2 Explicit Warmup Schedule and Transition
- **Strict Protocol Requirement**: Evaluation protocols require `warmup_session_count >= 1`. A warmup session count of zero is out of scope for M2 V1 and is rejected by `EvaluationProtocolV1` validation.
- The session clock derives `is_warmup: bool = (session_index < W)` using 0-based session index $0 \le \text{session\_index} < N$.
- Warmup observations populate strategy indicators and rolling state.
- **Sessions $0$ through $W - 2$** (the first $W - 1$ warmup sessions): Phase 5 does NOT invoke `strategy.decide()`; no target intents are staged.
- **Session $W - 1$ Post-Close** (the $W$-th warmup session): Phase 5 invokes `strategy.decide()` for the first time (`session_index >= W - 1`). Target positions are staged for execution at Session $W$ open.
- **Session $W$** (the $(W+1)$-th session, and first non-warmup trading session): Phase 2 (Open Execution) executes trades and fills for the first time.

---

## 9. Universe Admission and Historical Survivorship Rules

### 9.1 Sourced M1b Universe Authority
- Evaluator universe membership is derived session-by-session from `StructuralEligibilityResultV1` (replay under `AS_KNOWN` / `DECISION_INFORMATION`). This M1b replay applies to the promotion lane; exploratory evaluation is scoped by `ExploratoryCohortAuthorizationV1` instead (Section 7.1), which asserts experiment scope only and makes no universe-membership claim.
- `StructuralEligibilityClassification.ELIGIBLE` admits the security to the decision universe.
- `INELIGIBLE` or `INDETERMINATE` removes the security from eligibility.
- Indeterminate membership is never treated as eligible.

**Amendment, issue 85.** Admission at a decision cutoff reads only the as-known results known by that cutoff and evaluated at or before it, and within them only the answers at the security's latest instant across all its listings, ordered by `(evaluation_time, knowledge_cutoff)`. That order lets an answer about a later time outrank a later restatement about an earlier time. M1b answers every listing of a security at one instant and marks each non-primary listing `INELIGIBLE`, so at that instant a security is admitted when some listing is `ELIGIBLE`, none is `INDETERMINATE`, and no listing has conflicting answers. A listing the latest instant does not answer is not carried forward: an incomplete answer set fails closed, so a retired listing's old `ELIGIBLE` answer never keeps a security admitted, while an `INELIGIBLE` secondary listing answered beside an `ELIGIBLE` primary does not remove it, and a migration answered at one instant keeps it. Results under several universe definitions for one security are not distinguished by definition; conflicting answers across them admit nothing.

**Amendment, issue 77 (exploratory execution-listing authority; owner ruling A on 2026-09-24).** The Alpaca bridge supplies no M1b `ListingRoleVersionV1` evidence, leaving cohort securities without primary execution listing authority at `resolve_execution_listings`. In the EXPLORATORY reconstructed lane, `ExploratoryCohortListingRoleV1` provides dedicated, typed execution-listing authority derived from the predeclared cohort authorization (`AlpacaCohortMember` specifies each member's security ID, listing ID, and venue). Each role binds to the cohort hash (`role.cohort_hash == cohort.cohort_hash`) and explicitly carries the limitation `ALPACA_LIMITATION_COHORT_LISTING_ROLE` (`"execution-listing-declared-by-cohort-not-historical-role-evidence"`). The promotion lane strictly refuses exploratory listing roles; promotion requires authoritative historical M1b listing-role evidence. The exploratory reconstructed lane requires every cohort listing role's `cohort_hash` to match the admitted `cohort.cohort_hash`, and requires the admission to acknowledge `ALPACA_LIMITATION_COHORT_LISTING_ROLE`. In `resolve_execution_listing`, when no active historical primary listing role is found in authoritative M1b records, an exploratory cohort listing role provides unique primary execution listing authority for that security in the exploratory lane. If no role is found or if multiple distinct listing IDs are found for a security, resolution fails closed to `IndeterminateExecutionError`.

### 9.2 Liquidations Permitted for Excluded Positions
If a security currently held in the portfolio is removed from the universe (e.g. dropped from an index or becoming `INELIGIBLE`), the strategy is permitted to emit `target_quantity = 0` to liquidate the holding. Target quantities with `target_quantity > 0` (new entries or additions) for non-admitted securities are strictly rejected.

### 9.3 Anti-Survivorship Invariant
Today's constituent list (e.g. current S&P 500 or active Alpaca assets) cannot be projected backward as a historical universe. Any run attempting to project current symbols historically without dated interval eligibility fails validation.

---

## 10. Accounting Basis vs. Decision Data (Unadjusted Sourced Prices)

| Domain Layer | Data Basis | Source Authority | Purpose |
|---|---|---|---|
| **Strategy Decision Context (PROMOTION)** | Split-Normalized / Causal Views | Authentic M1d Decision Views (`AS_KNOWN`) | Point-in-time decision indicators, moving averages, signals. |
| **Strategy Decision Context (EXPLORATORY)** | Split-Normalized / Causal Views OR Source-Basis UNADJUSTED | Authentic M1d Decision Views when genuinely available, OR `ExploratoryReconstructedSessionObservationV1` (source-basis only, with retrospective limitations) | Exploratory screening, prototype indicators, signals. |
| **Portfolio Accounting** | Source-Basis UNADJUSTED Prices | M1d Unadjusted Views | Cash movements, fill prices, portfolio close marks, NAV. |
| **Corporate Action Economics** | Occurred Effects & Settlements | M1c Resolutions | Share ratio adjustments, cash dividend receivables, mergers. |

### 10.1 Double-Counting Prevention
Applying split-adjusted or dividend-adjusted prices in portfolio accounting while simultaneously crediting M1c dividends and adjusting share counts double-counts economic gains.
The M2 accounting kernel strictly uses source-basis unadjusted prices (`basis_mode="source_basis"` from M1d). An evaluation configuration attempting to use split-adjusted or total-return prices for portfolio accounting is rejected at validation.

### 10.2 Causal Split Normalization Anchoring
When split-normalized views are provided to `StrategyDecisionContextV1` at Session $S$, they must be causally anchored to Session $S$ (`anchor_session == session_S`). Normalizing historical bars against a future anchor session (e.g. the end of a multi-year backtest) is strictly prohibited as lookahead leakage.

**Amendment, issue 142 (D1, finding F1 of the #8 final acceptance rerun).** The realized lane binds every accounting price it reads to the book currency, as the reconstructed lane already did. Before this, a book declared `ISO-4217 EUR` filled and marked the USD prices of the M1d views it was handed, accepted a EUR dividend on the same security, and ended `COMPLETE` with one net asset value summing EUR cash and USD marks. `DerivedObservationViewV1` carries no currency field, so the currency is read from the evidence the view already cites, and no input is added: the view's query names, by `profile_hash`, the M1d observation profile its source observation was admitted under, and the pinned regular-session trade-bar profile states `"currency": "USD"` (M1d usability refuses a contract in any other currency under that profile, and admits no other profile). `accounting_view_currency` in `src/drift/evaluator/engine.py` returns that currency, and a view citing a profile no pinned specification states a currency for raises `IndeterminateValuationError` (`accounting view for security ... cites observation profile ..., which pins no price currency`). Every realized-lane open fill and close mark compares that currency with the book's currency code and, on a mismatch, raises `IndeterminateValuationError` (`accounting open price for security ... is in USD, not the book currency EUR`), so the run halts `INDETERMINATE` at first use, the same cause family as the reconstructed lane's refusal. A EUR book over USD views therefore commits no fill, and since every realized holding is bought at a checked open and marked at a checked close, no dividend can settle into a net asset value priced in another currency. M1d states a currency code with no namespace, so codes are compared, exactly as the reconstructed lane compares its M1d contract currency code; the book namespace is still compared with every M1c cash component and cash-in-lieu rate. Genuine USD runs, and every bundle, evidence, result and trace hash, are unchanged.

---

## 11. Portfolio State, Cash Accounting, Positions, and Pending Claims Kernel

### 11.1 Identity-Keyed Positions
Holdings are keyed by permanent `security_id` (UUID7), not mutable tickers or primary listings. Changing tickers, exchange transfers, or CUSIP updates do not alter economic position identity. Fills record the specific `listing_id` and venue through which execution occurred.

### 11.2 Portfolio State Model
```python
class SecurityHoldingV1(FrozenModel):
    """Whole-share holding in one admitted equity security."""

    security_id: UUID7
    quantity: int  # Must be > 0
    cost_basis: Decimal  # Total acquisition cost including fees

    @property
    def average_cost_per_share(self) -> Decimal:
        return self.cost_basis / Decimal(self.quantity)


class PendingCashClaimV1(FrozenModel):
    """Receivable for an earned but uncollected cash distribution."""

    claim_id: SHA256Hash  # Content-addressably derived from M1c occurrence
    security_id: UUID7
    action_kind: ActionKind
    occurrence_id: NonBlankStr
    component_id: NonBlankStr
    entitled_quantity: int
    cash_per_share: Decimal
    total_cash_expected: Decimal
    entitlement_session: date
    payable_session: date


class PortfolioStateV1(FrozenModel):
    """Complete immutable snapshot of portfolio state after a session mark."""

    session_key: SessionKeyV1
    cash_balance: Decimal  # Must be >= 0
    holdings: tuple[SecurityHoldingV1, ...]
    pending_cash_claims: tuple[PendingCashClaimV1, ...]
    holdings_market_value: Decimal
    pending_claims_value: Decimal
    net_asset_value: Decimal  # cash + holdings_market_value + pending_claims_value
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
```

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** The M2 stack books into versioned successors of these models. `SecurityHoldingV1`, `PendingCashClaimV1`, `PortfolioFillV1`, the mark models, `PortfolioStateV1`, `RebalanceOutcomeV1` and `EvaluationRunArtifactsV1` stay byte-identical, pinned by schema fingerprints and a V1 book's content hash (`tests/unit/test_evaluator_portfolio_v2.py`; the one exception is that issue 112 widens a result's `run_identity` to either identity version, which the `EvaluationRunArtifactsV1` schema nests, so that one fingerprint moves once, while a V1-identity pair still dumps the same bytes), because `content_hash` dumps every field, defaults included, so even a defaulted field would move V1 bytes. The successors live beside them in `src/drift/domain/evaluator_portfolio.py`, with no inheritance and no V1-to-V2 lift: a V1 holding cannot say whether its basis is known, and a lift would launder the zero basis a V1 spin-off child carries as a known one.
- `SecurityHoldingV2` adds `basis_status: known | indeterminate` (required, no default). A known basis is exact and non-negative and names no cause. An indeterminate basis has `cost_basis=None` and a sorted, unique, non-empty `basis_indeterminate_by` tuple of the applied-effect ids (section 11.3) that made it indeterminate. `average_cost_per_share` is `None` exactly then.
- `PortfolioStateV2` adds `applied_effect_ids`, canonically sorted and unique, and requires every indeterminacy cause of every holding to be one of them. `applied_effect_ids` and `settled_claim_ids` are both required, with no default (#139 review F2), so a rehydrated book that lost either record is refused rather than read as a book that applied or settled nothing. All V1 cash, claim, mark and NAV invariants hold through one shared validation function. A mark prices quantities only and never reads a basis status, so NAV stays `COMPLETE` over an indeterminate basis.
- `initial_portfolio_state`, `PortfolioAccountingKernel`, `CorporateActionProcessor`, `AtomicRebalanceEngine` (returning `RebalanceOutcomeV2`) and `SessionEvaluatorEngine` (returning `EvaluationRunArtifactsV2`, which keeps every `EvaluationRunArtifactsV1` binding) take and return V2 only, so there is one accounting truth. `positions_digest` stays quantity-only. `EffectAlreadyAppliedError` and `IndeterminateBasisError` are `IndeterminateValuationError`s declared in `evaluator_portfolio.py`, not in `drift/errors.py`, which both M1d semantic closures hold.

### 11.3 Deterministic Replay and Claim IDs
To guarantee bitwise replay determinism and prevent hash collisions across same-date distributions, `PendingCashClaimV1.claim_id` binds exact M1c occurrence and component identities. Claim identity is **source-scoped** and **date-independent**:
$$\text{claim\_id} = \text{content\_hash}(\text{source\_id}, \text{security\_id}, \text{action\_kind}, \text{occurrence\_id}, \text{component\_id})$$
Identity is source-scoped because M1c occurrence identity is source-scoped: `EconomicDeliveryGroupV1` keys a delivered occurrence on `source_id` together with `native_occurrence_id`, so two sources that reuse one native occurrence id describe two occurrences and must not collide onto a single claim. Identity is date-independent because M1c models payable and entitlement dates as revisable source claims (`EconomicDateFactV1` role `"payable"`, carried inside a revision envelope). A revisable date must never determine identity: putting `payable_session` in the preimage lets a payable-date revision mint a second `claim_id` for one economic entitlement, and both settled-claim guards are keyed on `claim_id`, so neither would fire and the same distribution would pay out twice. `entitlement_session` and `payable_session` are therefore **attributes** of the claim. A payable-date revision resolves by **supersession of the same identity** (`PortfolioAccountingKernel.supersede_claim`), never by recording a second claim, and a settled claim id remains unpayable no matter how its dates are later revised.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** Share mutations were not idempotent, and `PortfolioStateV1` could not show a re-applied split, so a checkpoint taken after a pre-open and replayed (#20 Q3) split a split position again. The applied-effect identity is
$$\text{applied\_effect\_id} = \text{content\_hash}(\text{profile}=\texttt{drift-applied-economic-effect-v1}, \text{source\_id}, \text{security\_id}, \text{occurrence\_id})$$
It is source-scoped and date-independent like claim identity, and it excludes every revisable field: the effective time, the ratio and components, the record version and its hash, and the action kind, so a revision that reclassifies an occurrence cannot mint a fresh identity and apply twice (the #4 double-pay pattern in share form). The cost is that two share mutations of one occurrence on one security share an identity, and that collision fails closed. Every Phase 1 pass records the identity of every share action it owns (section 12.3 amendment, issue 82: an in-window split, reverse split, stock dividend, spin-off, acquisition, or liquidation on a claim that does not continue, of a supported outcome), exposed or not, and refuses with `EffectAlreadyAppliedError` one whose identity the book already holds when the book is exposed to a security it touches. The replay is judged first, against the prior close's book, and again against the book the pass leaves; the second check is defense in depth, since exposure the pass gains to a security comes only through another share action touching it, which conflicts with the replayed one. It is a refusal, not a proven no-op, because staged targets are not state. The cash path consults the record too (#139 review F3): a cash distribution or continuing liquidation instalment whose applied-effect identity the book already holds, recorded by a share action or an instalment of the same occurrence, is refused with `EffectAlreadyAppliedError` when its entitlement vests in the pass and the book holds the security, at the prior close or after the pass's share actions. A revision that reclassifies a recorded split as a distribution or an instalment therefore cannot book the cash on top of the shares the split moved, and a replayed instalment pass is refused as a replay. Cash claims stay idempotent by claim identity, and a pass that only records keeps its book and mark. Deferred, recorded here: a pre-open pass marker; two sources reporting one split in different windows (two identities); and the reverse reclassification. A cash-only occurrence (a dividend or cash distribution) records no applied effect, so a revision that reclassifies a booked cash distribution as a share action or as a liquidation instalment is applied again (the split direction is pinned in `tests/unit/test_evaluator_portfolio_v2.py`). Recording one would move no hash: the record lives only in the book, and no trace event, result or M0 row carries it (#139 re-review M1). Its cost is behavioural: a dividend replayed through the pass it vests in, or revised to vest in a later pass, would be refused instead of staying idempotent by claim identity (a plain re-read at a later session is outside that pass's window and never reaches the guard), and so would a dividend followed by a share action of the same occurrence. The record also refuses readings no revision relates (#139 re-review L1): one source reporting one occurrence under two native records, as a share action and as a cash distribution vesting in a later pass, has the cash reading refused, and because the record is kept whether or not the book was exposed, so does a book that bought the security only after an unexposed share action, where the refusal's "already applied to this book" overstates what happened. Both readings in one window are both booked, as a genuine combined occurrence is. Either way the refusal fails closed and no amount is wrong. Two residuals older than this record are named here too (#139 re-review L3): a paid regular dividend revised into a special cash distribution with a later ex date books a second claim, because claim identity includes the action kind; and a split one source reports that another source reports as a dividend books both readings, because the identity is source-scoped.

### 11.4 Cost Basis Relief and Realized PnL Formulas
When whole shares are sold ($\Delta q_{\text{sell}} > 0$):
$$\text{Cost Basis Sold} = \Delta q_{\text{sell}} \times \left(\frac{\text{current\_cost\_basis}}{\text{current\_quantity}}\right)$$
$$\text{Gross Realized PnL} = (\Delta q_{\text{sell}} \times P_{\text{fill}}) - \text{Cost Basis Sold}$$
$$\text{Net Realized PnL} = \text{Gross Realized PnL} - \text{Transaction Costs}$$

**Amendment, issue 88 (known bounds, from the #8 final acceptance review).**
- Staging accepts only an `int` share count, so a forged fractional, Decimal, float, or bool target is REJECTED rather than failing the run.
- Portfolio arithmetic runs in the pinned 34-digit decimal context. A partial sale's relieved and remaining cost basis therefore conserve the original basis to within that context's last digit, not beyond it.
- The cost model and protocol hashes are content hashes of their exact decimal spellings, so `1.0` and `1.00` name different identities. Two identities are never equal over different economics, but the same economics must be spelled canonically to share one.
- Pending claims are valued when staged, at `effective_on`, using the aggregate-sale cash-in-lieu rate and liquidation proceeds the source reports, which may be set later. They enter the net asset value a strategy sees before settlement. This is an accepted limitation of ex-post accounting, recorded for the M3 strategy-interface freeze, which decides whether pending claims are exposed apart from NAV.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** These formulas apply to a known basis only.
- *Realization fails closed.* A kernel sale, a corporate-action disposal (section 12.6) and a funded rebalance that sells a holding with an indeterminate basis raise `IndeterminateBasisError`. The rebalance judges it after funding, so an unfunded plan is still a fully evidenced `REJECTED`, and before commit: inside the commit the kernel's refusal would surface as `AtomicRebalanceCommitError` and crash the run rather than classify it `INDETERMINATE`.
- *Pooling.* Shares received into a holding of the same security (a buy, a spin-off child, an acquirer) pool to a known basis only if both sides are known, as their exact sum; otherwise the pool is indeterminate and names every cause either side carried.
- *Cash in lieu of one pool.* When a re-denomination of one known basis pool (a split, a reverse split, a stock dividend, a stock-for-stock acquisition) sells a residual fraction for cash (section 12.1), the fraction carries $\text{basis} \times \text{residual} / \text{exact}$ of the pool, where exact is the exact entitlement the pool became. That is relieved in the pinned decimal context and realized against the cash-in-lieu proceeds in the same pass, as a disposal is, even when the relief leaves the holding unchanged, as a zero basis does (#139 review F4). The realized-PnL identity of section 12.6 therefore closes for every book whose basis is determinate.
- *Realized PnL covers determinate bases only* (#139 review F1). `realized_gross_pnl` and `realized_net_pnl`, in the book and in `EvaluationSummaryMetricsV1`, are the PnL realized on proven bases. They exclude the cash of any partial disposal whose basis allocation no source gives: the cash leg of a share acquisition on a held position (every `MIXED_ACQUISITION`, section 12.4), cash in lieu of a cross-security residual such as a spin-off child fraction (sections 12.1 and 12.5), and cash in lieu of an indeterminate pool (section 12.1). That cash is recorded as a pending claim, so NAV and net PnL are exact, and the basis it carried away stays inside the indeterminate holding, whose later sale or disposal fails closed. The run still reads `COMPLETE`, and nothing recorded shows the omission: the result, its summary metrics and the trace carry no basis status, which lives only in the final `PortfolioStateV2` and, through the position views, in the decision `context_hash`. A continuing liquidation instalment within a known basis is not such a case, since both of its readings realize 0. A result-level realized-PnL completeness status is an architecture follow-up and is not implemented here.

**Amendment, issue 142 (D4, finding F2 of the #8 final acceptance rerun).** `canonical_money` re-spells money and never re-values it. Normalizing under the pinned 34-digit context rounds a value with more significant digits than the context holds, so `canonical_money(1.000000000000000000000000000000000049)` returned `1`, and a 39-digit cash balance, a 37-digit fill price and a 37-digit close price were each stored rounded. Such a value is now refused with `ValueError` (`monetary amount ... cannot be held exactly in the pinned 34-digit portfolio context; it is refused, not rounded`), which every `CanonicalMoney` field raises as a `ValidationError`: cash, cost basis, fill and close prices, claim amounts, and the result and trace amounts. Zeros beyond 34 digits are not significant and still collapse to the canonical spelling. The #88 bound above is unchanged: kernel decimal arithmetic runs in the same context, so every amount it computes by decimal arithmetic has at most 34 significant digits and validates exactly as before. The exact rational conversion `exact_decimal`, which spells a per-share cash amount and cash in lieu, is not bounded by the context: a 31-digit M1c amount per 1024 shares can be an exact 38-digit cash per share. A value the book cannot hold exactly is missing evidence for the book, as a price in another currency is (D1), so where it is read it halts the run `INDETERMINATE` with `IndeterminateValuationError` (`... cannot be held exactly in the pinned 34-digit portfolio context`), rather than being rounded, or raising out of the run so that the M0 row records `FAILED` (review F1 of PR 145): `exact_decimal` refuses such a result, and the realized lane's accounting open and close prices (`_accounting_price`) and the reconstructed lane's (`_reconstructed_price`) are refused, after their currency check, before any fill or mark reads them. A wide price no fill or mark reads changes nothing. `EvaluationProtocolV1` refuses an `initial_cash` the context cannot hold exactly, so no run starts from one, and `EvaluationCostModelV1` refuses a commission, fee or basis-point parameter it cannot hold exactly, which cost arithmetic would otherwise round into every fill. A value fits when it has at most 34 significant digits and lies inside the context's exponent range (`fits_portfolio_context`); a finite value past that range, such as `1E+1000000`, does not fit, so it too halts `INDETERMINATE` or is refused rather than raising `decimal.Overflow` out of the run, and `exact_decimal` builds its amount from exact digits, never from a text rendering bounded by CPython's 4300-digit integer conversion limit (round-2 review of PR 145). No genuine run, hash or recorded amount changes.

---

## 12. Corporate Actions as First-Class Accounting Events

M2 processes corporate actions natively from M1c occurred effects (`EconomicEffectVersionV1`) and delivered settlements (`EconomicSettlementVersionV1`):

**Amendment, issue 76 (closed-world corporate-action coverage; C1 to C6).** Corporate actions are applied only from supplied evidence, and the absence of a record is never evidence that nothing happened. `CorporateActionProcessor` takes a mandatory `CorporateActionCoverageIndex` (`src/drift/evaluator/corporate_action_coverage.py`; D7-b), and `apply_pre_open_actions` holds every exposed security to it. (C1) Exposure is the processor's own: a holding at the prior close, or a positive staged target (every buy, and every sell of a holding), judged against the opening book and against the book the pass leaves, so a spin-off child or a conversion recipient the pass delivers is exposure too; an explicit zero target on an unheld security and a pending cash claim alone are not. (C2) The window is the session's own: every date after the previous clock session through its own date, or the first session's own date; the windows partition every date of the clock, and a second session on the date of the one before it owns no date. (C3) A window is covered when exploratory records read it `evidenced_no_action` (exploratory admissions only) or the security's M1c outcome is native coverage over it; a window in which any returned action carries any date (D4-a) halts naming each action by native kind and id, because the bridge mints no effect for it; a window with no coverage, including one before the 2021-08-02 REST evidence floor, one no positive assertion covers, one two records disagree about (V9) or one an undated returned action may lie in, halts naming the security and its dates. Every halt is an `IndeterminateValuationError` in `PRE_OPEN_EFFECTS`; an integrity failure of the evidence is refused by its code instead. (C4) An M1c-native covered outcome is evidenced no action, not unsupported evidence, only when it carries no record of any family: no effect projection, delivery group, unknown effect or uncomposed settlement, no selected or upcoming terms record and no cancelled action, no association, residual resolution or safe projection, and no terms or effect record bound to the outcome. An outcome carrying any record, an in-window terms record alone included, is judged by the support rules as before issue 76, so an exposed book halts on an unsupported one (review F2, decided under the owner's fail-closed operating rule on #62). (C5) The engine builds the index at construction from the bundle and the admission. (C6) The rule is lane-independent; while the promotion lane is disabled (issue 79) it applies to both exploratory lanes, and a promotion admission may be covered only by M1c-native coverage (issue 115, P8). Dates are read through the base `date` type only (issue 123).

### 12.1 Sourced Fraction Treatment (No Silent Truncation)
M2 strictly forbids arbitrary Python `int(...)` truncation of corporate action share ratios. Calculations must use exact rational arithmetic using Python's standard library `fractions.Fraction(int(ratio.numerator), int(ratio.denominator))` or exact integer quotient and remainder; floating-point arithmetic is strictly prohibited.

For reverse splits, stock acquisitions, spin-offs, and stock dividends:
1. Inspect M1c `ShareComponentV1.ratio_meaning`:
   - If `ratio_meaning == "resulting_per_predecessor"` (forward/reverse splits, stock acquisitions):
     $$\text{exact\_shares} = \text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$$
   - If `ratio_meaning == "additional_per_predecessor"` and recipient is the same security (stock dividend):
     $$\text{exact\_shares} = \text{current\_quantity} + \left(\text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}\right)$$
   - If `ratio_meaning == "additional_per_predecessor"` and recipient is a child security (spinoff):
     Parent shares remain unchanged; child shares entitlement $= \text{current\_quantity} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$.
2. If $\text{exact\_shares}$ is integral, materialize that whole-share quantity.
3. If $\text{exact\_shares}$ is non-integral, apply the explicit `FractionTreatmentV1` proved by M1c:
   - `round_down`: truncate fraction, keep whole shares.
   - `round_up`: ceiling fraction to next whole share.
   - `round_nearest`: `round_nearest` alone does not define tie-breaking semantics (bankers rounding vs half-up vs half-away-from-zero). M2 V1 directly supports integral, `round_down`, and `round_up`. For `round_nearest`, an exact interpreted tie-breaking rule artifact from source evidence is required; if unavailable, fail closed to `INDETERMINATE`.
   - `aggregate_sale_cash`: retain whole shares; convert fractional entitlement into a pending cash-in-lieu claim only after explicit subsequent M1c settlement/effect evidence proves the actual cash rate.
   - `fraction_issued`: unsupported by M2 V1 whole-share holding model; fail closed to `INDETERMINATE`.
   - `unknown`: fail closed to `INDETERMINATE`.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** An `aggregate_sale_cash` residual relieves basis only from the one known pool it re-denominates (section 11.4). A residual of an indeterminate pool relieves nothing: the pool stays indeterminate and also names the effect. A cross-security residual, such as a fraction of a spin-off child sold for cash, relieves nothing from the parent, which the spin-off already left indeterminate (section 12.5).

### 12.2 Staged Target Scaling Across Splits
When an overnight split occurs in Phase 1 (Pre-Open), pending staged target positions are translated using the exact same rational ratio:
$$\text{staged\_target}' = \text{staged\_target} \times \frac{\text{ratio.numerator}}{\text{ratio.denominator}}$$
If $\text{staged\_target}'$ is non-integral and cannot be resolved by an admitted fraction treatment, the run halts as `INDETERMINATE` due to unsupported corporate-action target translation. Targets are never arbitrarily rounded.

**Amendment, issue 81.** Translation applies to every share-mutating action, not only splits; a target left in pre-action units made the next open trade shares no decision asked for, and the run still read `COMPLETE`. Each action has its own rule:
- *Splits and `STOCK_DIVIDEND`.* The target is restated through the exact function its holding goes through: the same ratio, `ratio_meaning`, `FractionTreatmentV1`, and tie-breaking rule, with the rule above for a fraction the treatment cannot resolve. Any aggregate-sale residual is dropped, since a target is owed no cash in lieu. A stock dividend therefore multiplies the target by $1 + n/d$, and a split booked as a stock dividend translates identically. This holds with or without a holding behind the target.
- *`STOCK_ACQUISITION` and `MIXED_ACQUISITION`.* The predecessor target is mapped onto the acquirer through that same function, added to any acquirer target, and the predecessor target is set to 0. The mapping is allowed only for a hold or a sale: the mapped target may not exceed the whole acquirer shares the holding receives, which is 0 when nothing is held. A staged increase or entry would otherwise buy the acquirer at the open, a security no admitted decision named (section 6.4), so it is `INDETERMINATE`, as the issue 97 ruling (option A, section 13.1) confirms.
- *`SPINOFF`.* The child target is not a translation of the parent target. The parent target is unchanged, because parent shares are unchanged. The child target is credited with exactly the whole child shares the holding received, so the child is held rather than traded, and only when the parent carries a staged target, since otherwise no decision is staged. With no parent holding, no child shares are received and no child target changes.
- *`CASH_ACQUISITION`.* The target is set to 0 once the ended claim is proven, whether or not a holding stands behind it.

Two further rules:
- A cash or share acquisition of a security with no holding and no positive staged target (no target, or an explicit 0) finds no exposure, so its evidence, such as an unended claim status, cannot halt the run.
- A spin-off child or acquirer that is already held but has no staged target, while the source target is staged, is `INDETERMINATE`: treating its missing target as 0 would sell a holding no decision named.

A `LIQUIDATION` sets the staged target to 0 once its claim is proven `extinguished`, and leaves it unchanged when the claim is `continuing` (section 12.6).

### 12.3 Dividend and Due-Bill Entitlement Logic
M2 does NOT globally equate ex-date with entitlement:
- An economic receivable (`PendingCashClaimV1`) is created ONLY when M1c occurred effect evidence proves that the holding became legally entitled under the event's exact rule.
- **Ordinary Cash Dividends**: Entitlement aligns with the admitted ex-date rule.
- **Special and Due-Bill Distributions**: A due-bill redemption date alone does not encode the complete holder entitlement rule. M1c preserves `due_bill_start`, `due_bill_end`, `due_bill_redemption`, `ex`, `record`, `payable`, and `rule_reference`. For M2 V1:
  - Special distributions with an explicitly implemented and evidence-bound executable rule may be supported.
  - Using a generic shortcut like `due_bill_redemption_date == entitlement_date` is strictly prohibited.
  - If the exact retained due-bill rule cannot be deterministically interpreted under M2 V1 execution semantics, the run fails closed to `INDETERMINATE`.
- **Delivered Cash Settlement**: Settlement into available cash occurs in Phase 3 when `current_session.date >= claim.payable_session` and M1c delivered settlement evidence proves payment. Terms alone never credit cash.

**Amendment, issue 82.** Three rules, previously implicit, are now stated. The first two cover evidence dated off the clock; the third covers delivered cash that no claim matches.
- *Session windows.* The Phase 1 pass of each clock session owns every effect and entitlement dated after the previous clock session, up to and including its own date. A split, stock dividend, spin-off, acquisition, or liquidation dated on a weekend or a did-not-open day is therefore applied at the next pre-open, where nothing has traded since the prior close. It is never dropped, and never applied twice. The first clock session owns only its own date: the opening book is taken to reflect every earlier effect, including any entitlement it carries as a pending claim. The pass applies share actions by security id and record hash, never by time, and a window spans several dates when the clock skips days. So two or more share actions touching one security (as actor, or as a child or acquirer) in one window, on one date or several, and across all of the pass's outcomes (so a chain where one outcome's acquirer is another's subject counts), are `INDETERMINATE` for a book exposed to any security those actions touch, because their order is unproven. Exposure is judged against both the prior close's book and the book the pass leaves. The pass dispatches every share action, across all of its outcomes, before any cash distribution. Within a window, a cash distribution's pre-action share count is the prior close's. Its post-action count is the count after the security's own single continuing share action (a split, a reverse split, a stock dividend, or the parent's own spin-off), which re-denominates the prior close's holding or, for the spin-off, leaves it unchanged. For an exposed book that action is continuing: issue 117 refuses one whose own claim status is `extinguished` or `converted`, and one on a claim M1c composes as either when no ending effect follows it. The ex-date rule entitles only the prior close's holdings, and M1c's share basis says only which share count the source divides its cash by, so two other post-action counts are `INDETERMINATE` for an exposed book (issue 83). One includes shares another outcome's share action delivered into the holding in the same window (a spin-off child, or an acquirer): whether the source counts those shares is unproven. The other belongs to a holding the security's own disposal or share acquisition removed in the same window: it has no post-action count at all, and dropping the distribution would be a guess. Either halt names the security, the distribution and the share action. A pre-action quote in either shape is owed on the prior close's holding. Known limitation (amended by issue 83): M2 V1 does not prove a same-date order from the effects' intraday instants, so a split at 10:00 followed by a cash acquisition at 15:00 of one date fails closed rather than applying in time order; proving that order is future work.
- *Ex-date entitlement.* Without due-bill evidence, a cash distribution (ordinary or special) vests at the pre-open of the first session on or after its M1c `ex` date, against the prior close's holdings. The record date is not read: a share bought at the ex-date open is on the register by a T+2 record date and is still not entitled. A distribution without an `ex` fact is `INDETERMINATE` whenever the book holds the security at a pre-open on or after the effect's effective date; before then it is not yet evidence about the book. An occurred effect must be effective on or before its `ex` date, since an entitlement never vests before the occurrence that proves it; otherwise the run is `INDETERMINATE`. A proven due-bill rule whose entitlement session is not a clock session is `INDETERMINATE`, because no M2 V1 rule says which other session those holders are counted on.
- *Unmatched delivered cash.* Delivered cash that matches no pending claim is never credited. For a security the book holds, or has a pending claim on, it is `INDETERMINATE` unless the evidence shows the book was never owed it. That requires exactly one occurred effect of the same source and occurrence, owing that exact component (a share component, for cash in lieu), whose entitlement has vested by the current session. An effect M1c places before its evidence window is never applied, so it qualifies only when its entitlement vested before the clock's first session. Such an effect that fails the occurred-effect proof, or duplicates another report of its occurrence, is dropped rather than halting the run: it proves nothing, so it explains nothing, and a delivery that needed it still halts for want of an explanation. That entitlement vested with no claim, so it paid other holders, such as those at the prior close of an ex date this book bought on. This proof relies on Phase 1 having run for every clock session in order.

Exposure throughout Phase 1 means a holding or a positive staged target. An explicit zero target on an unheld security trades nothing, so unsupported evidence about that security cannot halt the run. Exposure to evidence a pass cannot apply (an unsupported outcome, or an action kind with no M2 accounting rule) is judged against the book the pass leaves, so a security first held through an earlier dispatch of the same pass, such as a spin-off child, is exposed. An action kind with no M2 accounting rule is judged against the prior close's book as well (issue 83): a disposal in the same outcome may leave no holding behind, and the pass would otherwise realize PnL on shares whose fate the unmodelled action leaves unproven. It is judged in every pass whatever window its effective date falls in, so a later holding or staged buy of the security it acted on halts too. An unsupported outcome is never applied, and only a security's own outcome removes its holding or zeroes its target, so the book the pass leaves is exposed to it whenever the prior close's was.

### 12.4 Mergers and Acquisitions
- `CASH_ACQUISITION`: Target holding converts to cash claim upon effective date; settled when payment delivered.
- `STOCK_ACQUISITION`: Target holding converts to acquirer shares using exact ratio and `FractionTreatmentV1`.
- `MIXED_ACQUISITION`: Simultaneously applies stock conversion and cash claim.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** A share acquisition carries the predecessor's basis status into the acquirer shares, pooled with any acquirer already held (section 11.4); a residual fraction relieves the predecessor pool before it pools. A cash leg of a share acquisition on a held position, which every `MIXED_ACQUISITION` has, is a partial disposal no source allocates basis to, so the acquirer holding becomes `INDETERMINATE` at the pass, caused by the acquisition: carrying the whole basis forward would publish the cash leg's realized PnL as 0 as if it were proven. Its cash claims are recorded as before, so NAV is unchanged, and a later sale or disposal of the acquirer fails closed.

### 12.5 Spin-offs (`SPINOFF`)
Creates a new `SecurityHoldingV1` in the child security using the exact distribution ratio and `FractionTreatmentV1`.
- **NAV Invariant**: If closing market prices for both parent and child are observable, portfolio NAV is marked normally. If tax cost-basis allocation percentages are unannounced, child holding cost basis is marked indeterminate; realized PnL upon eventual sale fails closed to `INDETERMINATE`, but daily portfolio NAV remains `COMPLETE`.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** This supersedes the invariant's first clause on the parent. No M1c field carries a source basis allocation, so a spin-off on a held parent makes the parent **and** the child `INDETERMINATE`, caused by the spin-off's applied-effect identity, whatever child quantity the holding receives (also none, as with a rounded-down fraction). Keeping the parent whole would overstate its basis, and a zero child basis would book the child's sale as pure gain. A child received into a held child pools as indeterminate. A later sale or corporate-action disposal of either side fails closed with `IndeterminateBasisError`; holding both keeps NAV `COMPLETE`. A spin-off with a source-reported allocation would be split exactly in V2, but no such input exists, so it is not implemented; the follow-up is an evidenced allocation registry. Deferred: basis pools, so that a full exit of both parent and child is determinate (a V3 if ever needed).

### 12.6 Terminations and Delistings
Delisting is NOT zero; bankruptcy is NOT zero. Terminal value requires explicit M1c liquidation terms or realized terminal distributions. If terminal proceeds are unknown, the evaluation outcome becomes `INDETERMINATE`. Zero cannot be fabricated.

**Amendment, issue 83.** Liquidation now reads the occurred effect's `claim_status`, and corporate-action disposals now realize PnL.
- *Extinguished liquidation.* A `LIQUIDATION` erases shares only when its claim is `extinguished`. The holding is removed for its proven cash claims, and any staged target is set to 0, so the open never re-buys the liquidated shares.
- *Continuing liquidation.* A liquidation whose claim is `continuing` is a partial liquidating distribution. Every share, its basis, and its target survive, and it is entitled, ordered after the pass's share actions, and reconciled exactly as a cash distribution under section 12.3 (its `ex` date governs). So an instalment quoted per post-action share in the same window as the final extinguishing liquidation, which removes the holding, is `INDETERMINATE`, while one quoted per pre-action share is owed on the prior close's holding. Changing no share count, it is not a share action for the issue 82 rule on windows that span several dates.
- *Unproven claim.* A `converted` or `unknown` claim status leaves it unknown whether any share survives, so it is `INDETERMINATE` for an exposed book. The same holds, as a pass-level rule, for the claim status M1c composes across all of an outcome's effects. When that is `unknown` (two liquidations at one instant with conflicting statuses, a continuing effect after an extinguishing one, or an effect whose own status is unknown), any effect of the outcome that commits in the pass's window halts a book exposed to any security the outcome touches, judged against both the prior close's book and the book the pass leaves. An effect commits in the window when its effective date is in it, or, for a cash distribution, when its entitlement date is. A cash distribution whose entitlement date cannot be resolved (one with no `ex` fact, for example) counts as committing in every window from the one it becomes effective, since it could vest in any of them; before it is effective it commits nothing. This covers splits, stock dividends, spin-offs, dividends, acquisitions and liquidations alike, even though each effect reads cleanly alone.
- *Disposal PnL.* A `CASH_ACQUISITION`, or an extinguished `LIQUIDATION`, is a disposal. The whole basis of the holding is relieved into realized gross and net PnL against the owed proceeds, in the pass of the first clock session on or after the effective date. The action fixes the price, so the gain or loss is realized then, although the proceeds are still receivable, and no transaction cost is charged. The realized-PnL identity therefore closes for every book whose corporate-action disposals are whole-holding extinguishments: cash + pending claims + remaining basis = initial cash + realized net PnL + distribution income. Mixed-acquisition cash legs, aggregate-sale cash in lieu, and liquidation instalments relieve no basis yet (#105), so a book with any of those does not close it.
- *Out of scope, unchanged.* A `MIXED_ACQUISITION` still carries the whole basis into the acquirer, with its cash leg treated as a claim rather than a partial disposal. An aggregate-sale cash-in-lieu fraction still relieves no basis.

Known limitation (#103): section 12.5's indeterminate spin-off child basis is not yet enforced. The child still enters at zero basis, so a later sale or corporate-action disposal of it overstates realized PnL, and the parent keeps its whole basis, so a later disposal of the parent understates its realized PnL by the same amount. Carrying an indeterminate basis from the spin-off to a later sale needs a basis-status field on `SecurityHoldingV1` (or an equivalent on `PortfolioStateV1`), and both are M2 contracts under the #50 freeze proposal. That decision is escalated rather than taken here.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** This supersedes the known limitation above, the issue 83 disposal-PnL sentence that mixed-acquisition cash legs, aggregate-sale cash in lieu and liquidation instalments relieve no basis yet, and its *Out of scope, unchanged* bullet. A disposal of an indeterminate basis raises `IndeterminateBasisError` (section 11.4). The cash leg and the cash in lieu follow sections 12.4 and 11.4. A *continuing liquidation instalment* returns capital or pays income, and no source says which. Within a known basis (instalment total $\le$ basis) both readings realize 0 and leave different bases, so the holding becomes `INDETERMINATE`, caused by the instalment, whose identity the book records, and the later extinguishing disposal then halts. Above the basis, return of capital would realize a gain income would not, and on an already indeterminate basis nothing tells them apart, so the pass raises `IndeterminateBasisError`. So does an instalment owed (per pre-action share) on a holding the same window's extinguishing disposal or conversion removed: the disposal, dispatched first, relieved the whole basis, the two readings differ in realized PnL, and no holding is left to carry the difference as an indeterminate basis. The realized-PnL identity is asserted over every determinate book (`tests/adversarial/test_m2_portfolio_state_v2.py`).

**Amendment, issue 117.** A split, a reverse split, a stock dividend and a spin-off act on a claim that continues, and a `REGULAR_CASH_DIVIDEND` or `SPECIAL_CASH_DISTRIBUTION` pays on shares that all continue, so M1c claim evidence that the claim ended contradicts them.
- *Own status.* Any of them whose own `claim_status` is `extinguished` or `converted` is contradictory evidence. M1c classifies such a distribution as supported and composes its status, so it used to be paid as an ordinary distribution while the shares were kept on an ended claim. A `LIQUIDATION` keeps its issue 83 rules instead.
- *Composed status.* So is one of the share actions on a claim M1c composes as `extinguished` or `converted` when no effect of the same outcome whose own status ends the claim definitely follows it. M1c composes the status of the claim's latest effect, so the claim had then ended by the action. An end that definitely follows the action, such as a split and then a cash acquisition in a later window, is the history of a live claim: the split applies in its own window and the acquisition in its own. An ending effect that is itself contradictory, such as a later dividend whose own status is `extinguished`, then halts in its own window. M1c never composes an ended status for a continuing action unless an ending effect strictly follows it, so this branch is defense in depth against evidence M1c did not compose.
- *Exposure.* Either is `INDETERMINATE` for a book exposed to the acted security (a holding or a positive staged target) in a window the effect commits in: the window of its effective date, and for a distribution also that of its entitlement date. A distribution whose entitlement date cannot be resolved (one with no `ex` fact, for example) is judged in every window from its effective one onward, since it could vest in any of them. It is judged against both the prior close's book and the book the pass leaves, like the composed-unknown rule above, except that that rule judges every security the outcome touches and this one only the acted security. The halt names the security, the effect and the status. The prior close's book matters because a reverse split may restate a staged buy as 0, and the book the pass leaves because a spin-off or conversion may deliver the security that a distribution on an ended claim pays on. For an unexposed book the evidence is unrelated, and the effect is a no-op.
- *Unchanged.* A `continuing` claim is unchanged, and a composed `unknown` claim stays under the issue 83 rule.

---

## 13. Deterministic Fill Model (Atomic Plan-Then-Commit)

### 13.1 Next-Open Execution Policy
All target deltas execute at session $D+1$ regular session open.

**Amendment, issue 84.** The engine records the session whose close staged the pending decision, and Phase 2 refuses to execute that decision unless the execution session opens at or after the decision cutoff (the decision session's close) and carries a later local date. A refusal halts the run `INDETERMINATE` with an `indeterminate_execution` cause in `OPEN_EXECUTION`, whether or not the staged targets trade. On a single venue the clock guards of section 7.5 already make every next session qualify, and the check does not rely on them. Together they refuse decreasing-date inversions; neither detects a lagged clock whose local dates trail their UTC stamps (the section 7.5 residual, which issue 96 closes at the preparation boundary by re-deriving the realized clock in `build_evaluation_input_bundle`; the engine's pair check still cannot see it). On a legal multi-venue clock a same-date open on another venue is refused rather than read as the next open. Since the issue 97 ruling below, such a clock never reaches Phase 2, and this check stays as defense in depth.

**Amendment, issue 97 (owner ruling of 2026-09-24 on four fail-closed choices).** Each ruling can be reopened only by a new Decision Packet carrying contradicting repository evidence.
- *Same-date multi-venue clocks (option A).* `SessionEvaluatorEngine` refuses at construction, with `SameDateMultiVenueClockError` (a `ValueError`) from `refuse_same_date_multi_venue_clock` in `src/drift/evaluator/clock.py`, any clock that steps two sessions on one local date, such as XNYS on day D followed by a non-overlapping XNAS on day D. The refusal runs on the revalidated bundle before the lane is resolved, so it covers every lane and both clock modes. Dates are compared across venues, in any venue order, and through the base `date` type (`date.toordinal`, and `date.isoformat` in the message), so no method of the value runs: a `local_date` of a `date` subclass whose equality, hash, order, ordinal or ISO form lies is refused too. This hardens only this refusal; canonicalizing the leaf values of every engine input, which revalidation still keeps subclassed, is issue 123. Keys are unique per venue, so every single-venue clock, and a venue change across dates, is unchanged. `SessionClockV1` and the clock builders still admit the shape (section 7.5); only its evaluation is refused. This supersedes the issue 84 runtime halt for this shape, and `require_next_open_execution` stays in Phase 2 as defense in depth.
- *A staged increase through a share acquisition (option A).* It stays `INDETERMINATE` (section 12.2, issue 81): a mapped target may not exceed the whole acquirer shares the holding receives, so no buy of the acquirer is carried forward.
- *The spin-off child's staged target.* The current rule is kept (section 12.2): the child target is credited with exactly the whole child shares the holding received, never the parent target times the ratio, so a staged parent exit keeps the child until the next decision and nothing buys a security no decision named.
- *Special cash distributions without due-bill facts.* The ex-date rule of section 12.3 (issue 82) is confirmed: such a special vests at the pre-open of its `ex` date against the prior close's holdings, exactly as an ordinary dividend.

### 13.2 Atomic Plan-Then-Commit Rebalance
To eliminate order-dependent partial fills and portfolio corruption:
At Phase 2 (Open Execution):
1. **Fetch Open Prices**: Retrieve unadjusted source-basis $P_{\text{open}}$ for all securities with non-zero target deltas ($\Delta q_i = \text{staged\_target}_i - \text{current\_quantity}_i$).
2. **Missing Open Check**: If any required $P_{\text{open}}$ is missing or invalid, immediately halt evaluation as `INDETERMINATE`. Do not substitute close or prior open.
3. **Plan Sells**: Calculate all proceeds from position reductions ($\Delta q_{\text{sell}} > 0$):
   $$\text{Gross Sells} = \sum (\Delta q_{\text{sell}} \times P_{\text{open}}(1 - \text{slippage})) - \text{Sell Costs}$$
4. **Plan Buys**: Calculate all cash required for position expansions ($\Delta q_{\text{buy}} > 0$):
   $$\text{Required Cash} = \sum (\Delta q_{\text{buy}} \times P_{\text{open}}(1 + \text{slippage})) + \text{Buy Costs}$$
5. **Solvency Verification**:
   $$\text{Hypothetical Cash} = \text{current\_cash} + \text{Gross Sells} - \text{Required Cash}$$
6. **Atomic Decision**:
   - **If $\text{Hypothetical Cash} < 0$**: The target intent is unfunded. The engine logs `FillRejectionTraceEventV1` detailing the cash shortfall. It commits **ZERO** fills and **ZERO** portfolio mutations for that rebalance. To guarantee execution determinism and prevent divergent post-rejection trajectories, the engine halts subsequent session stepping immediately. The evaluation is classified scientifically as `EvaluationClassification.REJECTED`. The software status completes as `ExperimentRunStatus.COMPLETED`.
   - **If $\text{Hypothetical Cash} \ge 0$**: The rebalance is fully committed. Sells are applied first (updating cash and holdings), followed by buys, in canonical order sorted by `security_id` UUID bytes.

---

## 14. Versioned Cost and Slippage Model

```python
class EvaluationCostModelV1(FrozenModel):
    """Explicit deterministic cost and slippage parameters."""

    schema_version: Literal["1"] = "1"
    model_id: NonBlankStr
    commission_per_share: Decimal  # USD per share (e.g. Decimal("0.005"))
    fixed_fee_per_order: Decimal  # USD per order (e.g. Decimal("1.00"))
    notional_fee_basis_points: Decimal  # Basis points on traded value
    adverse_slippage_basis_points: Decimal  # Basis points applied against trade
    cost_model_hash: SHA256Hash
```

- Buy Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 + \frac{\text{slippage\_bps}}{10000}\right)$
- Sell Fill Price: $P_{\text{fill}} = P_{\text{open}} \times \left(1 - \frac{\text{slippage\_bps}}{10000}\right)$
- Total Transaction Cost:
  $$\text{Cost} = (\text{shares} \times \text{comm\_per\_share}) + \text{fixed\_fee} + \left(\text{shares} \times P_{\text{open}} \times \frac{\text{fee\_bps}}{10000}\right)$$

---

## 15. Missingness, Indeterminacy, and Fail-Closed Semantics

| Missing Event | Prohibited Behavior | Enforced Evaluator Behavior |
|---|---|---|
| Held security missing close price | Forward-fill from previous close | Mark valuation as `INDETERMINATE`; halt stepping. |
| Intended fill missing open price | Fall back to close; synthesize zero | Mark evaluation as `INDETERMINATE`; halt stepping. |
| Corporate action fraction treatment unknown | Truncate via `int(...)` silently | Mark corporate action as `INDETERMINATE`; halt stepping. |
| Security delisted without terms | Mark position value as zero | Mark portfolio terminal NAV as `INDETERMINATE`. |
| Strategy emits negative quantity | Clip to zero silently | Reject strategy intent (`REJECTED`). |
| Strategy attempts to buy beyond cash | Execute partial; allow margin | Log `FillRejectionTraceEventV1`; commit 0 fills; mark `REJECTED`. |

When a fatal indeterminate event occurs, the engine emits `IndeterminateCauseTraceEventV1`, halts subsequent session processing, and marks the result `classification=INDETERMINATE` with `status=COMPLETED`.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** Two more rows. A replayed share mutation on an exposed book is never applied again, and cash is never booked on an occurrence the book already recorded while it holds the security: `EffectAlreadyAppliedError`, `INDETERMINATE` (section 11.3). Realizing an indeterminate cost basis, by a sale, a disposal or an instalment the rules above cannot book, is never booked at zero or at a carried basis: `IndeterminateBasisError`, `INDETERMINATE` with an `indeterminate_valuation` cause, in `PRE_OPEN_EFFECTS` for a corporate action and in `OPEN_EXECUTION` for a rebalance. Holding an indeterminate basis is not an indeterminacy: NAV and the equity series stay `COMPLETE`.

---

## 16. Deterministic Per-Session Phase Ordering

```
+-----------------------------------------------------------------------------------+
|                           Canonical Per-Session Phases                            |
+-----------------------------------------------------------------------------------+
| PHASE 1: PRE_OPEN_EFFECTS                                                         |
|   - Apply M1c occurred corporate action share conversions (with FractionTreatment)|
|   - Scale staged target positions by split ratios.                                |
|   - Record pending cash dividend claims where M1c proves legal entitlement.       |
|   - Update share quantities, cost bases, and pending receivables.                 |
+-----------------------------------------------------------------------------------+
| PHASE 2: OPEN_EXECUTION                                                           |
|   - Retrieve staged target positions.                                             |
|   - Derive deltas: Delta q = staged_target - current_quantity.                    |
|   - Fetch unadjusted session open prices from M1d source-basis views.             |
|   - Atomic Plan-Then-Commit: verify complete rebalance is 100% funded.            |
|   - If unfunded: emit FillRejectionTraceEventV1, commit 0 fills, mark REJECTED.   |
|   - If funded: execute Sells first, Buys second; record FillTraceEventV1.         |
+-----------------------------------------------------------------------------------+
| PHASE 3: INTRASESSION_ECONOMIC_EFFECTS                                            |
|   - Settle pending cash claims where payable_session <= current_session.date      |
|     and M1c delivered settlement proves payment.                                  |
|   - Process daytime security distributions or tender completions.                 |
+-----------------------------------------------------------------------------------+
| PHASE 4: CLOSE_MARK                                                               |
|   - Fetch unadjusted close prices at actual realized session close.               |
|   - Compute market value of holdings and Net Asset Value (NAV).                   |
|   - Record SessionMarkTraceEventV1 in the execution trace.                        |
+-----------------------------------------------------------------------------------+
| PHASE 5: POST_CLOSE_DECISION                                                      |
|   - If current session is >= warmup_count W:                                      |
|     - Construct causal StrategyDecisionContextV1 anchored to session close.       |
|     - Invoke runtime strategy `decide(context)`.                                  |
|     - Validate emitted targets (long-only, whole shares, universe constraints).   |
|     - Apply complete target set rule (omitted holdings get target = 0).           |
|     - Stage valid targets for Session S+1 open.                                   |
+-----------------------------------------------------------------------------------+
```

Amendment, issue 46: in the EXPLORATORY scheduled-reconstruction lane, Phase 5 constructs `ExploratoryStrategyDecisionContextV1` instead, invokes `decide_exploratory(context)`, validates against the declared cohort, and records `ExploratoryStrategyDecisionTraceEventV1` (section 7.1 amendment). The realized lane is unchanged.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** Phase 1 first refuses an exposed replay of a share action the book already absorbed, refuses a vesting cash entitlement on a held security whose occurrence the book already recorded (section 11.3), then records the applied-effect identity of every share action it owns and of every instalment that left a basis indeterminate, and sets basis status by sections 11.4 and 12.4 to 12.6. Phase 2 judges an indeterminate-basis sale after the solvency verification and before the atomic commit. Phase 5 shows an indeterminate basis as `None` in the position view. Neither the record nor a basis status is traced: `CorporateActionAppliedTraceEventV1` still fires only when holdings quantities, staged targets or recorded claims change.

---

## 17. Evaluation Result and Canonical Trace Contracts

### 17.1 Granular Trace Events
The evaluator generates an immutable sequence of typed trace events:
- `SessionStartTraceEventV1`
- `CorporateActionAppliedTraceEventV1`
- `FillTraceEventV1`
- `FillRejectionTraceEventV1`
- `ClaimSettledTraceEventV1`
- `SessionMarkTraceEventV1`
- `StrategyDecisionTraceEventV1`
- `ExploratoryStrategyDecisionTraceEventV1` (issue 46: EXPLORATORY scheduled-reconstruction decisions only)
- `ExploratoryAccountingPriceTraceEventV1` (issue 54: EXPLORATORY reconstructed prices one open-execution or close-mark phase consumed)
- `IndeterminateCauseTraceEventV1`

The complete sequence hashes into `trace_hash = content_hash(tuple(trace_events))`.

### 17.2 Separation of Deterministic Content from Orchestration Metadata
- The evaluation result artifact (`ExploratoryEvaluationResultV1` / `PromotionEvaluationResultV1`) contains ONLY deterministic values derived from inputs and historical facts.
- No random UUIDs and no wall-clock completion timestamps.
- Operational execution metadata (`run_id`, `started_at`, `completed_at`, `status=COMPLETED`) belong exclusively to M0 `ExperimentRun`, which references the deterministic result artifact via `artifact_references`.
- Replaying the same evaluation under two different `ExperimentRun` IDs produces the exact same `evaluation_hash` and `trace_hash`.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** The deterministic run output is `EvaluationRunArtifactsV2`, whose `final_state` is a `PortfolioStateV2`; the result and the trace are unchanged types, and no trace event carries the applied-effect record or a basis status. The experiment runner rebuilds and records the V2 artifacts.

**Amendment, issue 142 (D3, finding F2 of the #8 final acceptance rerun).** A result binds its admission's bundle to its run identity's bundle. `EvaluationRunIdentityV1` holds bare hashes, and the section 4.2 link `admission.input_bundle_hash == bundle_hash` was enforced only where an identity is built and in the engine, so a result could carry an admission of bundle X under an identity naming bundle Y, and a stand-in engine returning one had `execute_experiment_run` record a `COMPLETED` row for Y. Result validation, in both lanes, now refuses `run_identity.bundle_hash != admission.input_bundle_hash` (`result run identity must bind the bundle its admission admits`). Building an `EvaluationRunArtifactsV1` re-runs the validation of the result it pairs, whether that result is handed in unvalidated or with a top-level field rewritten in place after validation, so the artifact pair refuses the same pairing. It re-runs the result's own checks, not those of the models nested inside it, and validating a pair that is already built re-runs nothing, so a nested model rewritten in place under a resealed result hash, such as the result's admission, is not refused by the pair (review F2 of PR 145). The runner relies on neither: it rebuilds returned artifacts through canonical JSON, which re-validates every nested model, so it refuses both the bundle mismatch and such a rewrite, and records nothing. Every genuine result already satisfied the link, so no hash moves.

---

## 18. Replay Integrity and Content-Addressed Identity

An evaluation run is uniquely identified by its canonical evaluation hash:

$$\text{RunHash} = \text{content\_hash}(\text{strategy\_ref}, \text{params}, \text{input\_bundle\_hash}, \text{protocol\_hash}, \text{cost\_model\_hash}, \text{admission\_hash}, \text{code\_hash}, \text{environment\_hash})$$

Re-executing an evaluation with identical inputs, strategy version, protocol, costs, and software environment produces bitwise-identical trace events, identical accounting numbers, and an identical result hash.

**Amendment, issue 86.** Evidence outside the bundle changes results too, so `EvaluationRunIdentityV1` also binds `evaluator_evidence_hash`, the canonical identity of everything the engine consults beyond its hashed inputs: the book currency, and every `SessionEvaluatorEvidence` member, namely listing role, termination, and lifecycle records, economic outcome records, tie-breaking, due-bill, and cash-in-lieu registries, and the exploratory cohort and replay (each collection by its sorted member content hashes, each replay context by its M1d context hash). The engine refuses a run identity that does not name the evidence it consults or the strategy that runs, and refuses to be built unless the economic outcome records it is handed match the bundle's declared resolutions exactly, so a declared corporate action can never be read as no action by omission. `execute_experiment_run` refuses a specification whose dataset is not the run identity's bundle, or whose running strategy is not the one the identity names.

**Amendment, issue 63 (stage 1 of the Q6 ruling on #62).** The M1d evidence identity that every M1d normalization, action-session, session-binding, session-generation, selection and usability record binds as `implementation_hash`, and that therefore reaches `input_bundle_hash`, is the versioned `m1d-evidence-v1` semantic attestation (`m1d_evidence_attestation_hash()` in `src/drift/domain/semantic_attestation.py`, returned by `m1d_implementation_hash()`), not the whole installed source inventory. An edit outside its declared closure, such as a comment in `drift/evaluator/engine.py`, no longer moves a source-basis bundle, admission, result or trace hash, and retained source-basis M1d results and schedule policies re-validate under later code. Per the Q6 ruling, code-version provenance is kept separate from this identity: the whole-tree inventory, `drift_source_inventory_hash()` (value-identical to the pre-#63 identity), is build and repository provenance. In an evaluation run it belongs only in `code_hash` (`EvaluationRunIdentityV1.code_version_hash`), outside runs only in the Alpaca bridge's collector provenance, and never in the bundle. No production runner binds it as `code_version_hash` yet; canonical runs must bind it before canonical M3 evidence is recorded (tracked as #109). #63 stage 2 must keep `drift_source_inventory_hash()` the whole-tree build and repository provenance accessor even if it changes the role of `economic_implementation_hash()`. Stage 2 is still pending: M1c identities are still whole-tree, so split-normalized evidence is the stage-2 residual (a retained split-normalized reference still refuses under later code, on the M1c validator identity) and every bundle member that carries M1c identities still moves on unrelated edits. Both stages must land before canonical M3 evidence is recorded. Historical M1d fixtures are unchanged and keep replaying under their original identity from their archived source commits.

**Amendment, issue 63 (stage 2 of the Q6 ruling on #62).** The M1c identities are versioned semantic attestations too, declared in `src/drift/domain/semantic_attestation.py` beside the two M1d closures. The M1c validator run identity, which every M1c validation run and decision binds as `validator_implementation_hash` (`economic_validator_implementation_hash()`, name kept), is the `m1c-source-validation-v1` attestation (`m1c_validation_attestation_hash()`). M1c selection proofs, safe fact projections and outcome resolutions bind the `m1c-evidence-v1` attestation (`m1c_evidence_attestation_hash()`) as `selection_implementation_hash`, `projection_implementation_hash` and `composition_implementation_hash`. No persisted field is renamed and no schema or validator version changes. Each M1c closure is a strict subset of the matching M1d closure, because M1d executes M1c code in process, so an M1c edit moves the M1d identities as well, while an M1d-only edit moves neither M1c identity, and a selection or composition edit does not stale validated M1c datasets. As a result, split-normalized evidence and every bundle member, admission, evaluator evidence hash, result and trace that carries an M1c identity no longer move on an edit outside the declared closures, such as a comment in `drift/evaluator/engine.py`: a retained split-normalized result and a retained bundle carrying a genuine M1c outcome re-verify under later code. `economic_implementation_hash()` and `drift_source_inventory_hash()` are unchanged and value-identical, and are build and repository provenance only; neither is an evidence identity, and in a run that provenance belongs only in `code_hash` (#109). This paragraph supersedes the stage-1 paragraph's statements that stage 2 is still pending and that split-normalized evidence is the stage-2 residual; both stages have now landed, as the Q6 ruling requires before canonical M3 evidence is recorded. Historical M1c fixtures are unchanged and keep replaying under their original whole-tree identity from their archived source commits; the live-tree M1c byte freeze moves forward by its first supersession link, `m1c-v3`, and the M1d freeze by `m1d-v7`.

**Amendment, issue 112 (gap G1 of the strategy-surface contract inventory, #113, decision D2, ruled option (b) on 2026-09-24).** `EvaluationRunIdentityV1` binds the strategy's `code_hash` and not its parameters, contrary to the `params` term above and to its own docstring: two parameterizations of one strategy version shared one `run_identity_hash` while their result hashes differed (probe P1). `EvaluationRunIdentityV2` binds every V1 field and `strategy_parameters_hash`, the `strategy_parameters_hash()` of the parameters the run declares, which is `content_hash` of an exact copy of canonical JSON data (section 6, issue 112 amendment) and so equals `content_hash(specification.parameters)` for every genuine specification. It is built by `build_evaluation_run_identity_v2` and hashed by `evaluation_run_identity_v2_hash` over a document carrying `schema_version="2"` and the `strategy_parameters_hash` key, so no V2 identity can share a hash with a V1 one, and it shares no base class with V1. The engine accepts either version (the `EvaluationRunIdentity` union, discriminated by `schema_version`), rebuilds it canonically, and under V2 binds the parameters the strategy exposes before any session (`require_bound_strategy_parameters`, in `src/drift/evaluator/engine.py`). Under V2, `execute_experiment_run` reads the specification's parameters once, into one exact canonical copy. It refuses before the engine runs, and records nothing, when that digest is not the identity's `strategy_parameters_hash`, and it records that same digest as the M0 row's `parameters_hash`, never a second read (issue 112 review, F1: a mapping proxy over a dict whose `items()` and storage disagree passed the check and recorded other parameters through a second, differently implemented read). The running strategy's parameters are bound by the engine alone, read once. The runner re-raises the engine's `StrategyParametersBindingError` exactly as it re-raises `PromotionLaneDisabledError`, so a parameters refusal is never recorded as a FAILED run (review, F2: the runner read the strategy's parameters too, so a strategy answering differently on its second read was refused by the engine and recorded FAILED). Both errors are refusals only where the engine raises them, before any session and while sealing its result. Strategy code that raises either during a session is failing, not refusing: the engine re-raises it as `StrategyRaisedRefusalError`, chained to it, and the runner records the run `FAILED`, as the issue 111 amendment records any exception raised inside `decide` (round-2 review, R2-1: before this, a strategy could keep its own failed run out of the M0 ledger by raising either). The wrap covers every strategy call inside a session, `decide` and `decide_exploratory` and the hashing of a refused return alike, and its message names the raised type read through `type` itself, never formatting the error, whose own `__str__` is strategy code. Residual: before any session the engine reads the strategy's `strategy_reference` and, under V2, its `strategy_parameters` (and the protocol checks behind them), and a read that raises either error propagates unrecorded, as any caller input the runner cannot rebuild does; strategy code is trusted at the process level (#113). A second residual was tracked on #149: issue 149 closes the runner formatting residual: the runner reads the type name through type itself, safely evaluates str(error) falling back to "<unprintable>" on failure or non-str, and formats error_details without running strategy code, so an exception whose __str__ or type name raises records FAILED with one audit event; issue 150 closes the strategy indeterminate-error halt residual: the engine guards decide, decide_exploratory and the hashing of a refused return, re-raising `IndeterminateValuationError` and `IndeterminateExecutionError` as `StrategyRaisedIndeterminateError`, named through type itself and never formatting the strategy error, so any indeterminate error raised by strategy code fails the run FAILED through the runner, while genuine accounting and execution indeterminacies continue to halt INDETERMINATE. On the runner path the strategy's `strategy_reference` is read twice, once by the runner, which compares its canonical `code_hash` with the specification and the identity, and once by the engine, so a reference whose code hash changes between the two reads is refused by the engine's binding check and the run records `FAILED` with no artifact, never a `COMPLETED` row or an M0 row that disagrees with its identity (round-2 review, R2-2). In either version the engine reads the strategy's `strategy_reference` once and compares only the `code_hash` of its canonical JSON rebuild as a `StrategyReference`, refusing a reference with no canonical form with `NonCanonicalEngineInputError` (review, F5). This closes the issue 123 amendment's residual that the engine read that code hash as given: a `str` subclass spelling another version could answer the comparison with its reflected `__ne__`. A result's `run_identity` holds either version. A V1 identity dumps exactly as before, so every V1 identity, trace and result hash is byte-identical, as the M2 anti-laundering pins, a V1 schema fingerprint and a synthetic V1 identity hash (`tests/adversarial/test_m2_run_identity_parameters.py`) check; a synthetic V2 identity hash pins the V2 hash document. `EvaluationRunIdentityV1` stays frozen: it and `build_evaluation_run_identity` are unchanged, a V1 run never reads strategy parameters, and two parameterizations of one strategy version still share a V1 identity by design. Canonical M3 runs, every B1 per-member run included, must use V2.

**Amendment, issues 49, 103 and 105 (the #49 design record and the owner rulings of 2026-09-24 on #49, #103 and #105).** The change is construction-additive but hash-changing, following the issue 80 precedent. Position digests are quantity-only and a known position view dumps exactly as before, so a run with no spin-off, mixed acquisition, aggregate-sale residual or continuing liquidation instalment on an exposed security keeps its exact trace and result hashes; every pinned exploratory run hash is unchanged. A run whose decision sees an indeterminate or relieved basis moves its decision `context_hash`, and so its trace and result hashes; a relieved residual also moves realized gross and net PnL; and a run that used to read `COMPLETE` while realizing an indeterminate basis now halts `INDETERMINATE`, which is the defect being fixed. Ten corporate-action runs pin this in `tests/adversarial/test_m2_portfolio_state_v2.py`, each move recorded at its pin with the only leaves a field-by-field diff shows moving.

**Amendment, issue 142 (D2, finding F1 of the #8 final acceptance rerun).** One run identity gives one result, whatever order its evidence is handed in. The issue 86 evidence hash identifies each collection by its sorted member content hashes, but the engine kept the caller's order, and execution-listing resolution raises its first fail-closed cause in record order, so two orders of the same termination records shared one identity yet halted on different causes, with different trace and result hashes. The engine now holds every evidence collection (listing role, termination and lifecycle records, economic outcomes, and the tie-breaking, due-bill and cash-in-lieu registries) in the content-hash order of its members, and the replay requests in the order of the hash of each query and its M1d context hash, exactly the keys the evidence hash sorts, so behaviour depends only on content the identity binds. Duplicate members are kept, as the evidence hash keeps them. The evidence hash itself is unchanged, and every existing pinned run identity, result and trace hash is unchanged.

---

## 19. Exploratory Lane Admission Contracts

Canonical strings for acknowledged Alpaca limitations:
```python
ALPACA_LIMITATION_TRUNCATED_CA = (
    "corporate-action-mutation-replay-truncated-to-approx-72-days"
)
ALPACA_LIMITATION_UNVERSIONED_BARS = (
    "derived-bars-unversioned-without-provider-vintages"
)
ALPACA_LIMITATION_ABSENT_HALTS = "trading-halt-telemetry-absent-from-api"
ALPACA_LIMITATION_BOUNDED_COHORT = "evaluation-restricted-to-declared-bounded-cohort"
ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION = "session-clock-reconstructed-from-scheduled-calendar-without-independent-realized-history"
ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION = (
    "strategy-inputs-retrospectively-reconstructed-from-audit-vintage-bars"
)
```

---

## 20. Promotion Lane Admission and Authentic M1e Gatekeeper

An admission gatekeeper operates outside the pure evaluator core, binding authentic M1e qualification evidence across both consumer purposes (`HISTORICAL_DECISION_INPUT` and `RETROSPECTIVE_AUDIT`).

In Task 1, `validate_m1e_promotion_evidence` validates the M1e qualification artifacts and `QualifiedSourceHandoffV1` objects against `PromotionEvaluationAdmissionV1`. Task 2 is internally sequenced for implementation: slice 2A delivers the exploratory cohort authorization, exploratory reconstruction policy/fields/observation, and the realized/scheduled session-clock contracts and builders; slice 2B then delivers the immutable `EvaluationInputBundleV1`, replay-bound preparation, admission-to-bundle gates, and the deterministic evaluation-run identity. In Task 2B, `validate_promotion_admission` composes the Task 1 evidence check with `EvaluationInputBundleV1` structural anti-laundering validation.

**Amendment, issues 31 and 34 (supersedes this section where they conflict).** Adversarial review found that `EvaluationInputBundleV1.source_snapshot_hash` is an unverified self-declaration: views can be materialized through genuine M1d replay over a resolution context entirely unrelated to the qualified snapshot the bundle names, and the gate as originally specified admits it. Replay-boundness was proven; provenance was not. The specification itself contained the gap, so the API is changed rather than preserved.

`src/drift/domain/replay_provenance.py` adds the proof-bearing chain: `ReplayContextIdentityV1` (deterministic identity derived from an `M1dResolutionContext` by pure function, with the context itself unmodified), `SnapshotBindingEntryV1`, `QualifiedReplayContextV1` (a context identity bound to a `RealSourceSnapshotV1` by a retained, canonically sorted containment witness plus its digest), and `BundleProvenanceProofV1` (`proof_version = "m2-bundle-provenance-v1"`).

Binding is total, not sampled: every artifact a context supplies appears exactly once in the witness, every witness entry resolves to a real snapshot replay input entry that attests that artifact, and `snapshot_binding_proof_hash` is recomputed over the sorted witness so a tampered witness cannot keep a stale digest. `component_hashes` covers all six authority-bearing classes (decision views, accounting views, structural eligibility, economic outcomes, security and listing identity, session-clock authority); a bundle member absent from the proof fails closed.

Minting is split from validation. `mint_bundle_provenance_proof` runs replay verification once and emits the proof; `validate_promotion_admission` gains a required `proof` parameter and revalidates cheaply and fail-closed, with no full M1d replay inside admission. `PromotionEvaluationAdmissionV1` gains `provenance_proof_hash`. `EvaluationInputBundleV1` gains nothing, so the hash graph stays acyclic: the proof references the bundle, never the reverse. The exploratory lane is unaffected; an unqualified context stays constructible and usable, and the wrapper is required only where a promotion-grade claim is made.

**Second amendment, issue 31 reopened (supersedes the paragraph above where they conflict).** A required `proof` parameter alone was not sufficient, and the residual recorded when issue 31 was first closed rested on a cost argument that does not hold. The gate validated `proof.proof_hash`, `proof.bundle_hash`, `proof.source_snapshot_hash` and component coverage, but never read `proof.qualified_context_hash`, and had no parameter through which a `QualifiedReplayContextV1` or a `RealSourceSnapshotV1` could reach it. A hand-constructed qualified replay context naming a foreign snapshot, over a real context identity and with invented `snapshot_entry_hash` values, is fully valid under its own contract, because proving the containment witness requires the snapshot and the model never sees one. Such a context passed `mint_bundle_provenance_proof` and the gate admitted the result. The stated justification was that the ruling forbade M1d replay inside admission; `verify_snapshot_binding` performs no M1d replay at all, only `content_hash` recomputation and dictionary lookups over `snapshot.replay_inputs`, so the cost constraint never applied to the check that closes the gap.

`validate_promotion_admission` therefore requires `qualified_context: QualifiedReplayContextV1` and `snapshot: RealSourceSnapshotV1` alongside `proof`, and adds three fail-closed checks: `qualified_context.qualified_hash == proof.qualified_context_hash`; `qualified_context.source_snapshot_hash == bundle.source_snapshot_hash`; and `verify_snapshot_binding(qualified=qualified_context, snapshot=snapshot)`. The intermediate signature that took a proof without the evidence behind it is not preserved for compatibility. The pure-assembly helper becomes module-private as `_build_bundle_provenance_proof`, so the module boundary rather than a docstring enforces that production reaches a proof only through minting.

**Amendment, issue 80 (snapshot, purpose and context identity binding; supersedes the paragraphs above where they conflict).** `verify_snapshot_binding` compared the declared `snapshot_hash` and never recomputed it, so a snapshot object that kept the qualified hash while attesting another corpus was admitted. It, `bind_context_identity_to_snapshot`, and the public `verify_snapshot_binding_purpose` each require `real_source_snapshot_hash(snapshot) == snapshot.snapshot_hash` before anything else. `verify_snapshot_binding` also applies the binder's own ambiguity rule and refuses a witnessed artifact that the snapshot attests more than once; before, a witness built by hand could choose among an artifact's entries, for example the decision-purpose one, and pass the re-audit of a context the sanctioned binder refuses to qualify. Witness entries were matched by content hash alone, so decision evidence attested only as retrospective-audit input, under a foreign profile, in a snapshot of a foreign profile set, was admitted. `validate_promotion_admission` now also requires `snapshot.profile_set_hash == admission.m1e_profile_set_hash`; both the decision and the audit profile hash in `snapshot.authorized_profile_hashes`; and, through `verify_snapshot_binding_purpose`, every witnessed snapshot entry, each one and not only the first, to attest its artifact as `HISTORICAL_DECISION_INPUT` under the decision profile when the bundle carries decision views, and as `RETROSPECTIVE_AUDIT` under the audit profile when it carries accounting views. These are hashing and lookups over the snapshot in hand, so admission still runs no replay. Known consequence, ruling requested: the frozen witness records one snapshot entry per artifact (a second entry for the same artifact is refused as ambiguous), and one M1d context backs both view classes, so a promotion bundle carrying both decision and accounting views cannot satisfy both clauses and fails closed until dual-purpose attestation of one context is decided. Since the gate also requires at least one decision view, a promotion bundle can currently carry decision views only, and therefore cannot trade: fills and marks price only from authorized accounting views, so any trade, or any held position to mark, halts `INDETERMINATE`. `ReplayContextIdentityV1` gains `schedule_generation_policy_hash`, so two contexts that name different supplied artifacts as the schedule policy no longer share an identity, and a qualification of one cannot mint for the other. The change is construction-additive but hash-changing: the field defaults to `None`, so every existing construction still validates, and it is covered by `identity_hash`, so every context identity hash, and every qualified context hash over one, changes.

**Amendment, issue 79 (the owner ruling of 2026-09-24, option 1; supersedes this section where it conflicts).** The engine never ran this gate: `validate_promotion_admission` had no production caller, and `SessionEvaluatorEngine` accepted any `PromotionEvaluationAdmissionV1`, so a hand-made admission with invented M1e and proof hashes, over an exploratory bundle with no snapshot, sealed a `PromotionEvaluationResultV1` with `is_promotion_grade_evidence=True`, and `execute_experiment_run` recorded it as `lane=promotion`. The promotion lane is therefore **disabled**, and M2 closes with it disabled. Every `PromotionEvaluationAdmissionV1`, a fully genuine one that this gate admits included, is refused with `PromotionLaneDisabledError` (a `DriftError` and a `ValueError`, defined in `src/drift/evaluator/engine.py`) at four enforcement points: engine construction, first and before any other processing, reading the admission alone (and again on the revalidated admission); the start of `SessionEvaluatorEngine.run`; the result sealing site, which no longer seals a promotion result, so no production path can yield one; and `execute_experiment_run`, which refuses a promotion admission before running and a promotion result before recording, so no M0 experiment run and no audit event records `lane=promotion`. The runner trusts no object an engine returns (the PR 120 review): it refuses anything naming the promotion lane or whose `is_promotion_grade_evidence` is not exactly `False`, rebuilds the artifacts through canonical JSON (not a python-mode dump, which keeps subclassed leaves, see issue 123), refuses the rebuilt result in turn, and records only from the rebuilt objects; a `PromotionLaneDisabledError` the engine raises inside the run propagates instead of being recorded as a `FAILED` run (one raised by strategy code during a session is a failed run, the issue 112 amendment in section 18), and `summary_metrics_payload` refuses a promotion result as well. Exploratory runs are byte-identical. This is a deliberate fail-closed state, not a deletion: the promotion architecture stays, including this gate, `mint_bundle_provenance_proof`, `verify_evaluation_input_bundle`, the admission and result types, and their gate-level tests, which keep exercising the gate directly. A `PromotionEvaluationResultV1` still validates on its own over an exploratory trace (finding F9), because a result binds its trace by hash only; closing that needs cross-object data, so it stays prerequisite P9. Re-enabling the lane requires every prerequisite tracked in issue 115, each implemented with independent adversarial review, and a fresh owner decision.

**Amendment, issue 124 (the PR 120 round-2 review, R3, R5 and N2; lane-neutral).** A valid rebuild proves the returned artifacts are well-formed, not that they are this run's: a stand-in engine returning a genuine exploratory run over another bundle was recorded `COMPLETED` under an M0 row naming this run's dataset. After the rebuild, `execute_experiment_run` therefore refuses, with `ForeignRunArtifactsError` (a `DriftError` and a `ValueError`, defined in `src/drift/evaluator/experiment_runner.py`), a rebuilt result whose `run_identity` is not exactly the context's run identity, which binds the bundle, protocol, cost model, strategy, admission, evaluator evidence, code version and environment closure (issue 86), and a rebuilt result whose own `bundle_hash` is not the dataset hash the M0 row records, checked against the result itself so no claim in the context can pair the row with a result evaluated on another bundle. Neither refusal records an M0 run or an audit event. `EvaluationRunArtifactsV1` bound its final book to its result by admission hash only, so it accepted an exploratory result paired with a book in the promotion lane marked `promotion_grade`. It now refuses a `final_state` whose `lane` is not the result's lane, and a final mark priced at any grade other than the one the result's lane grants (`LANE_GRANTED_MARK_GRADE`, equal to the engine's `LANE_MARK_GRADE`: `exploratory` for the exploratory lane, `promotion_grade` for the promotion lane). The exploratory lane still admits promotion-grade evidence (`LANE_ADMISSIBLE_MARK_GRADES`), but an exploratory run grades every mark from its own admission, so a promotion-grade mark in its final book is one the run never made. A test now pins that a truthy non-bool `is_promotion_grade_evidence` (for example `1`) is refused by name before the rebuild. Genuine runs record byte-identically: the M0 run, its metrics and artifact references, and the audit event.

**Authoritative landing corrections** (superseding the illustrative pseudocode below): handoff integrity is `qualified_source_handoff_hash(handoff) == handoff.handoff_hash`, and the admission binds `decision_handoff.handoff_hash` / `audit_handoff.handoff_hash` exactly (`handoff_hash` is SELF-EXCLUDING; a whole-object `content_hash(handoff)` would include that field and must never be bound). For positive M1e evidence, every one of the 12 final dimension results in BOTH purpose reports must be `REACHED`, carry evidence, and match the owning report purpose; only profile-critical dimensions must additionally `PASS` with `admitted_purpose=True` (a non-critical reached `PARTIAL` is permitted); a positive completion must not carry `blocking_dimensions` or `blocking_evidence_hashes`.

```python
def validate_m1e_promotion_evidence(
    admission: PromotionEvaluationAdmissionV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
) -> None:
    """Verify promotion admission against authentic M1e qualification evidence across both purposes."""
    if admission.lane != "promotion":
        raise ValueError("admission must belong to promotion lane")
    if completion.completion_kind != M1eCompletionKind.COMPLETED_POSITIVE:
        raise ValueError("promotion requires positive M1e completion")
    if content_hash(completion) != admission.m1e_completion_record_hash:
        raise ValueError("completion record hash mismatch with admission")
    if content_hash(profile_set) != admission.m1e_profile_set_hash:
        raise ValueError("pilot profile set hash mismatch with admission")
    if completion.profile_set_hash != admission.m1e_profile_set_hash:
        raise ValueError("completion record profile set binding mismatch")

    # Decision profile and report checks
    if decision_profile.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision profile must have historical_decision_input purpose")
    if decision_profile not in profile_set.profiles:
        raise ValueError("decision profile is not a member of bound profile set")
    dec_prof_hash = qualification_profile_hash(decision_profile)
    if decision_report.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision report must have historical_decision_input purpose")
    if decision_report.target.profile_hash != dec_prof_hash:
        raise ValueError("decision report target profile hash mismatch")
    if decision_report not in completion.purpose_reports:
        raise ValueError("decision report is not bound in completion record")

    # Audit profile and report checks
    if audit_profile.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit profile must have retrospective_audit purpose")
    if audit_profile not in profile_set.profiles:
        raise ValueError("audit profile is not a member of bound profile set")
    audit_prof_hash = qualification_profile_hash(audit_profile)
    if audit_report.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit report must have retrospective_audit purpose")
    if audit_report.target.profile_hash != audit_prof_hash:
        raise ValueError("audit report target profile hash mismatch")
    if audit_report not in completion.purpose_reports:
        raise ValueError("audit report is not bound in completion record")

    # Purpose states checks
    dec_state = next(
        (
            s
            for s in completion.purpose_states
            if s.purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT
        ),
        None,
    )
    if dec_state is None:
        raise ValueError("missing historical_decision_input purpose state")
    if dec_state.profile_hash != dec_prof_hash:
        raise ValueError("decision purpose state profile hash mismatch")
    if dec_state.stage != PilotStage.COMPLETED_POSITIVE:
        raise ValueError("decision purpose state not completed_positive")
    if dec_state.terminal_blocker is not None:
        raise ValueError("decision purpose state has terminal blocker")

    audit_state = next(
        (
            s
            for s in completion.purpose_states
            if s.purpose == ConsumerPurpose.RETROSPECTIVE_AUDIT
        ),
        None,
    )
    if audit_state is None:
        raise ValueError("missing retrospective_audit purpose state")
    if audit_state.profile_hash != audit_prof_hash:
        raise ValueError("audit purpose state profile hash mismatch")
    if audit_state.stage != PilotStage.COMPLETED_POSITIVE:
        raise ValueError("audit purpose state not completed_positive")
    if audit_state.terminal_blocker is not None:
        raise ValueError("audit purpose state has terminal blocker")

    # Shared snapshot checks across both reports
    if (
        not decision_report.target.snapshot_hash
        or not audit_report.target.snapshot_hash
    ):
        raise ValueError("reports must have non-null snapshot hashes")
    if decision_report.target.snapshot_hash != audit_report.target.snapshot_hash:
        raise ValueError(
            "decision and audit reports must reference identical snapshot hash"
        )
    shared_snapshot = decision_report.target.snapshot_hash

    # QualifiedSourceHandoffV1 checks
    if qualified_source_handoff_hash(decision_handoff) != decision_handoff.handoff_hash:
        raise ValueError("inconsistent decision handoff hash")
    if decision_handoff.handoff_hash != admission.decision_handoff_hash:
        raise ValueError("decision handoff hash mismatch with admission")
    if decision_handoff.purpose != ConsumerPurpose.HISTORICAL_DECISION_INPUT:
        raise ValueError("decision handoff purpose mismatch")
    if decision_handoff.profile_hash != dec_prof_hash:
        raise ValueError("decision handoff profile hash mismatch")
    if decision_handoff.report_hash != content_hash(decision_report):
        raise ValueError("decision handoff report hash mismatch")
    if decision_handoff.target_hash != content_hash(decision_report.target):
        raise ValueError("decision handoff target hash mismatch")
    if decision_handoff.snapshot_hash != shared_snapshot:
        raise ValueError("decision handoff snapshot hash mismatch")
    if decision_handoff.environment_closure_hash is None:
        raise ValueError("decision handoff missing environment closure hash")
    if decision_handoff.replay_authorization_hash is None:
        raise ValueError("decision handoff missing replay authorization hash")

    if qualified_source_handoff_hash(audit_handoff) != audit_handoff.handoff_hash:
        raise ValueError("inconsistent audit handoff hash")
    if audit_handoff.handoff_hash != admission.audit_handoff_hash:
        raise ValueError("audit handoff hash mismatch with admission")
    if audit_handoff.purpose != ConsumerPurpose.RETROSPECTIVE_AUDIT:
        raise ValueError("audit handoff purpose mismatch")
    if audit_handoff.profile_hash != audit_prof_hash:
        raise ValueError("audit handoff profile hash mismatch")
    if audit_handoff.report_hash != content_hash(audit_report):
        raise ValueError("audit handoff report hash mismatch")
    if audit_handoff.target_hash != content_hash(audit_report.target):
        raise ValueError("audit handoff target hash mismatch")
    if audit_handoff.snapshot_hash != shared_snapshot:
        raise ValueError("audit handoff snapshot hash mismatch")
    if audit_handoff.environment_closure_hash is None:
        raise ValueError("audit handoff missing environment closure hash")
    if audit_handoff.replay_authorization_hash is None:
        raise ValueError("audit handoff missing replay authorization hash")

    # Check all 12 dimensions in both reports
    for report, profile in (
        (decision_report, decision_profile),
        (audit_report, audit_profile),
    ):
        results_by_dim = {res.dimension: res for res in report.results}
        if len(results_by_dim) != 12 or set(results_by_dim.keys()) != set(
            QualificationDimension
        ):
            raise ValueError(
                f"report for {profile.purpose} must contain all 12 qualification dimensions"
            )
        for crit_dim in profile.critical_dimensions:
            res = results_by_dim.get(crit_dim)
            if res is None:
                raise ValueError(
                    f"critical dimension {crit_dim} missing from {profile.purpose} report"
                )
            if res.status != QualificationStatus.PASS:
                raise ValueError(
                    f"critical dimension {crit_dim} did not PASS in {profile.purpose} report"
                )
            if res.reachability != ExecutionReachability.REACHED:
                raise ValueError(
                    f"critical dimension {crit_dim} was not REACHED in {profile.purpose} report"
                )
            if not res.admitted_purpose:
                raise ValueError(
                    f"critical dimension {crit_dim} did not admit {profile.purpose}"
                )


def validate_promotion_admission(
    admission: PromotionEvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    profile_set: PilotProfileSetV1,
    completion: M1eCompletionRecordV1,
    decision_profile: QualificationProfileV1,
    audit_profile: QualificationProfileV1,
    decision_report: PurposeQualificationReportV1,
    audit_report: PurposeQualificationReportV1,
    decision_handoff: QualifiedSourceHandoffV1,
    audit_handoff: QualifiedSourceHandoffV1,
    proof: BundleProvenanceProofV1,
    qualified_context: QualifiedReplayContextV1,
    snapshot: RealSourceSnapshotV1,
) -> None:
    """Full promotion admission validator composing M1e evidence verification with bundle anti-laundering and provenance-proof gates."""
    validate_m1e_promotion_evidence(
        admission=admission,
        profile_set=profile_set,
        completion=completion,
        decision_profile=decision_profile,
        audit_profile=audit_profile,
        decision_report=decision_report,
        audit_report=audit_report,
        decision_handoff=decision_handoff,
        audit_handoff=audit_handoff,
    )

    # Input bundle and snapshot checks
    if bundle.bundle_hash != admission.input_bundle_hash:
        raise ValueError("input bundle hash mismatch with admission")
    if bundle.source_snapshot_hash != decision_handoff.snapshot_hash:
        raise ValueError("input bundle snapshot mismatch with promotion admission")

    # Provenance chain, validated cheaply and fail-closed (issues 31, 34)
    if proof.proof_hash != bundle_provenance_proof_hash(proof):
        raise ValueError("inconsistent provenance proof hash")
    if proof.bundle_hash != bundle.bundle_hash:
        raise ValueError("provenance proof bundle hash mismatch")
    if proof.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError("provenance proof snapshot mismatch")

    # Provenance evidence, re-verified rather than named (issue 31 reopened).
    # All hashing and dictionary lookups: no M1d replay runs here.
    if proof.qualified_context_hash != qualified_context.qualified_hash:
        raise ValueError("provenance proof qualified context mismatch")
    if qualified_context.source_snapshot_hash != bundle.source_snapshot_hash:
        raise ValueError("qualified replay context snapshot mismatch with bundle")
    verify_snapshot_binding(qualified=qualified_context, snapshot=snapshot)

    validate_bundle_component_coverage(proof=proof, bundle=bundle)
    if admission.provenance_proof_hash != proof.proof_hash:
        raise ValueError("admission is not bound to the provenance proof")

    # Structural anti-laundering checks on input bundle
    if bundle.has_exploratory_reconstructions:
        raise ValueError(
            "promotion evaluation cannot consume exploratory reconstructed inputs"
        )
    if bundle.session_clock.mode != "realized_session_authority":
        raise ValueError(
            "promotion evaluation requires authentic realized session authority"
        )
    if any(
        session.authority != "realized" for session in bundle.session_clock.sessions
    ):
        raise ValueError(
            "promotion evaluation requires realized session evidence for every session"
        )
```

---

## 21. Alpaca Development Bridge and Acquisition Isolation

The Alpaca development bridge is an operational data preparation utility that executes strictly outside the evaluator core.

### 21.1 Layered Data Pipeline
The bridge follows a strict layered pipeline preserving provenance:
```
Alpaca REST API Responses
  |
  +--> 1. Retain Exact Native Response Bytes in private storage outside Git
  +--> 2. Generate AcquisitionReceiptV1 and Dataset Manifest
  +--> 3. Map native payloads to standard Drift source records (M1b/M1c/M1d)
  +--> 4. Validate datasets via Drift public validators (DatasetValidationDecisionV2)
  +--> 5. Execute standard M1b/M1c/M1d selection/normalization functions
  +--> 6. Reconstruct ExploratoryReconstructedSessionObservationV1 (source-basis, with explicit limitations)
  +--> 7. Emit EvaluationInputBundleV1 for evaluator core
```

### 21.2 Strict Layering Prohibitions
- **NO Manual Derived Views**: The bridge must NEVER construct `DerivedObservationViewV1` manually from provider JSON. Views must be derived through existing M1d normalization routines.
- **NO Fake Realized Sessions**: Scheduled calendar rows must NEVER be converted into `RealizedSessionVersionV1`. The bridge produces `ScheduledSessionVersionV1` and operates under `scheduled_session_reconstruction`.
- **NO Invented Corporate Action Effects or Settlements**: Alpaca corporate actions records must be mapped conservatively:
  - If a record establishes terms only: map terms only.
  - If occurrence/effect semantics are explicitly supported: map the exact supported effect.
  - If delivered settlement cannot be proven: do NOT mint `EconomicSettlementVersionV1`. Missing settlements fail closed to `INDETERMINATE` if required for portfolio cash.
- **Quiet-Window Exploratory Smoke Run**: For the Task 8 smoke run, select a bounded cohort and date window with valid free SIP historical bars, scheduled calendar rows, and minimal corporate action complexity, verifying pipeline plumbing end-to-end. Full corporate action accounting is verified via pinned/synthetic fixtures in Tasks 3-7.

**Amendment, issue 71 (the bridge's session coverage; ruling Q18 of #62, decisions D1 to D9).** The one-week ceiling is lifted with evidence, not by inference. The bridge reads the calendar response it already fetches and retains (D1-a; still `GET /v2/calendar` on the paper host, no new endpoint, route, host, key use or dependency) closed-world over the bracketed hull of the dates it returned (D2-b), as one `ClosedWorldSessionCoverageV1` (section 7.5 amendment, issue 71), and materializes every evidenced non-trading date as an explicit closed schedule row bound to it. Its `SessionCoverageVersionV1` covers exactly that hull and names the record as its source artifact. The bridge refuses a calendar row outside the requested window by name, re-parses the retained bytes into the returned dates (V5), holds the requested interval to the receipt and the expected object (V6), and refuses a window whose run span holds an INDETERMINATE date, naming the dates, rather than truncating it (R1, D6-a). A two-week window with its weekend, or with a weekday the calendar omits, is admitted; dates after the last returned session stay INDETERMINATE and outside the run. The inference stays visible (D3-a): `ALPACA_LIMITATION_CALENDAR_CLOSED_WORLD` (`calendar-absence-read-as-closure-under-closed-world-assumption`) joins `ALPACA_EXPLORATORY_LIMITATIONS`, which now holds seven limitations, and the bridge bundle declares it as a dataset limitation beside `ALPACA_LIMITATION_TRUNCATED_CA`, so an admission omitting it is refused. This supersedes the issue 92 amendment's statements that the bridge declares exactly `ALPACA_LIMITATION_TRUNCATED_CA` and acknowledges six limitations. Coverage is schedule evidence only: no `RealizedSessionVersionV1` and no `did_not_open` is ever minted from it (D7-a, 21.2).

**Amendment, issue 76 (the bridge's corporate-action coverage; B1 to B7).** (B1) The corporate-actions request stays one `GET /v1/corporate-actions` on `data.alpaca.markets`, with no new endpoint, route, host, key use or dependency, and its `types` filter widens from `cash_dividend` to every type in `ALPACA_ACTION_TYPES`; the CLI sends the adapter's declared parameters for every endpoint. (B2) The measured origin records the exact request target the transport sent, and its retained origin record gains schema version 2 when it does (a measurement without a target keeps the version 1 bytes exactly); the request declaration's `canonical_parameters` become per-endpoint and state exactly the parameters each endpoint's measured request target names, symbols and types included, or `"unmeasured"` for an endpoint whose origin records no target, so a replay of bytes retained before issue 76 claims no parameter it was not fetched with (review F6). A retained response whose measured origin carries no target, which every response retained before issue 76 is, yields no coverage record, only the named refusal `ca_coverage_request_unmeasured`: replaying old bytes can never claim coverage of every type. (B3) Every group of the response is parsed; a group with no M1c counterpart is kept with no action kind, a row with no identifier is content-addressed, and a malformed date, a repeated action or a paginated page refuses intake. A key repeated inside any JSON object of any retained Alpaca response (bars, calendar or corporate actions) refuses intake by name (`alpaca_response_duplicate_key`), and so does the V5 re-parse: last-wins decoding would read a repeated group or page token as a quiet, closed page (review F1). A row is attributed to every cohort member any of its symbol fields names, or to every member when it names none; cash-dividend terms mapping is unchanged. (B4) One `ClosedWorldCorporateActionCoverageV1` per cohort member, a member with no returned action included, binding the requested window, the request declaration, the retained response bytes, the measured origin record and a completeness assertion whose basis is the publication status of the retained `alpaca-corporate-actions-closed-world` statement; its covered interval is the requested window, never before 2021-08-02 and never after the acquisition date. The bridge re-parses the bytes into each record's returned actions (V5) and holds the measured request to the declared route, host, window and cohort (V6) and to every requested type (V8), refusing a mismatch by code. (B5) Intake never refuses for thin or non-positive coverage (D6-b); only an exposed evaluation halts on it. (B6) `ALPACA_LIMITATION_CA_SNAPSHOT_ABSENCE` (`corporate-action-absence-read-from-current-provider-snapshot`) joins `ALPACA_EXPLORATORY_LIMITATIONS`, which now holds eight limitations, and every record carries it; this supersedes the issue 71 amendment's statement that the list holds seven. (B7) The records ride in the bundle; `economic_outcomes` stays empty and no effect or settlement is ever minted. DP-1, resolved: `ALPACA_ACTION_TYPES` is the 16-value `types` enumeration of Alpaca's API reference for `GET /v1/corporate-actions` (https://docs.alpaca.markets/reference/corporateactions-1, API version 1.1, page last updated 2026-05-27), including `partial_call`, `reorganization` and `capital_gains_distribution`, whose groups are parsed and attributed like every other and carry no M1c kind, and `ALPACA_DOCUMENTED_ACTION_TYPE_COUNT` is 16, cited from it. The structural check stays: a record's assertion is positive only if the measured request named that many distinct types and exactly the ones the bridge declares, so a request whose declared types omit a documented type is read but non-positive, while a measured request contradicting the declaration refuses intake (V8).

---

## 22. Adversarial Acceptance Test Matrix

The M2 implementation must pass the following explicit adversarial acceptance tests:

| Category | Invariant Tested | Attack Scenario / Input | Expected Result |
|---|---|---|---|
| **Causality** | Same-Bar Close Lookahead | Strategy requests execution at session D close using session D close price | Rejected by protocol validation. |
| **Causality** | Post-Cutoff Observation Leakage | Observation with availability timestamp > decision cutoff passed to strategy | Filtered out or triggers fail-closed error. |
| **Causality** | Early-Close Realized Timing | Session closes at 13:00; strategy decision evaluated after 13:00 | Accepted; uses actual realized close, not 16:00. |
| **Causality** | Future Corporate Action Knowledge | Strategy context contains corporate action announced after decision date | Rejected by M1c causal selection query. |
| **Epistemic Lanes** | 2026 Downloaded Bar as Decision Ref | Alpaca 2022 bar downloaded in 2026 submitted as M1d `ObservationDecisionReferenceV1` | Rejected; cannot produce decision-role reference without vintage. |
| **Epistemic Lanes** | Reconstructed Observation in Promotion | `ExploratoryReconstructedSessionObservationV1` submitted to PROMOTION evaluation | Structural rejection; gatekeeper fails closed. |
| **Epistemic Lanes** | Reconstructed Observation in Exploratory | 2022 session reconstructed as `ExploratoryReconstructedSessionObservationV1` (source-basis) with retrospective limitations | Permitted in EXPLORATORY lane only, over the predeclared cohort. |
| **Universe** | Current Interpretation as As-Known | M1b `CURRENT_INTERPRETATION` submitted as `AS_KNOWN` in PROMOTION | Rejected; promotion requires authentic as-known authority. |
| **Universe** | Survivorship Bias | Current active asset list used as historical universe | Rejected; requires historical universe definition. |
| **Universe** | Indeterminate Eligibility | Security with `MembershipStatus.INDETERMINATE` admitted to trading | Rejected; indeterminate is not eligible. |
| **Universe** | Post-Delisting Liquidation | Strategy emits target=0 for held security dropped from universe | Permitted; exits non-admitted holding cleanly. |
| **Universe** | Listing Migration at Execution | Security changes primary listing before execution session open | Phase 2 resolves exact new historical listing; does not use stale listing. |
| **Clock Authority** | Scheduled Row as Realized Session | Alpaca scheduled calendar row passed as `RealizedSessionVersionV1` | Prohibited; scheduled rows cannot mint realized sessions. |
| **Clock Authority** | Scheduled Exploratory Early Close | Scheduled 13:00 close evaluated under `scheduled_session_reconstruction` on EXPLORATORY-only reconstructed decision evidence | Accepted; the exploratory decision executes post-close at the 13:00 scheduled close with explicit limitations, no `RealizedSessionVersionV1` is fabricated, and the result stays exploratory and non-promotable. |
| **Clock Authority** | Missing Bar on Scheduled Open | Scheduled session expected open, but required market bars missing | Fails closed to `INDETERMINATE`; does not infer halt. |
| **Replay Integrity** | View Hash vs M1d Replay | Self-consistent fabricated view without successful M1d replay | Bundle preparation rejects; requires exact M1d replay. |
| **Accounting** | Double-Counting Adjustment | Accounting configured with split-adjusted prices while applying M1c splits | Validation rejects adjusted accounting prices. |
| **Accounting** | Premature Dividend Settlement | Dividend cash credited to available cash on ex-date before payable date | Rejected; ex-date creates receivable, not cash. |
| **Accounting** | Generic Due-Bill Shortcut | Generic `due_bill_redemption_date == entitlement_date` applied to special dividend | Rejected; requires explicit executable rule, else `INDETERMINATE`. |
| **Accounting** | Round Nearest Without Rule | `round_nearest` applied without source tie-breaking rule artifact | Fails closed to `INDETERMINATE`. |
| **Accounting** | Terms-Only Corporate Action | Alpaca terms record without occurred effect or settlement | No portfolio cash/share mutation committed. |
| **Accounting** | Fabricated Delisting Recovery | Security delists without liquidation terms; accounting assumes zero or recovery | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Fractional Split Unknown Treatment | Reverse split yields non-integral shares with unknown fraction treatment | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Missing Close Forward-Fill | Held position has missing close price; evaluator forward-fills prior close | Valuation fails closed to `INDETERMINATE`. |
| **Accounting** | Multiple Same-Date Cash Claims | Two dividends on same date share security ID and dates | Distinct claim IDs via M1c component/occurrence hash. |
| **Execution** | Close-for-Open Fallback | Missing open price replaced by prior or current close price | Execution fails closed to `INDETERMINATE`. |
| **Execution** | Negative Target Position | Strategy emits negative whole-share target quantity (short position) | Intent rejected; run classified as `REJECTED`. |
| **Execution** | Fractional Share Target | Strategy emits floating-point target quantity (e.g. 10.5 shares) | Intent rejected; whole shares only. |
| **Execution** | Unfunded Rebalance Shortfall | Target rebalance exceeds cash after planned sells | 0 fills committed; stepping halts; classified `REJECTED`. |
| **Execution** | Zero Warmup Session Count | Protocol declared with `warmup_session_count = 0` | Rejected by protocol validation; requires W >= 1. |
| **Gatekeeper** | Missing Audit Purpose Report | Promotion admission has decision report but lacks retrospective audit report | Rejected by gatekeeper; requires both purpose reports. |
| **Gatekeeper** | Audit Critical Dimension Failed | Decision report passes, but Retrospective Audit critical dimension fails | Rejected by gatekeeper. |
| **Gatekeeper** | Report Profile Hash Mismatch | `report.target.profile_hash` does not equal bound profile hash | Rejected by gatekeeper. |
| **Gatekeeper** | Profile Not in Profile Set | Profile is not a member of bound `PilotProfileSetV1.profiles` | Rejected by gatekeeper. |
| **Gatekeeper** | Fake PASS Report | Report has PASS but M1e completion record is NEGATIVE | Promotion admission rejected by gatekeeper. |
| **Gatekeeper** | Promotion Evidence Scope | Caller treats `PromotionEvaluationResultV1` as M10 strategy approval | Disallowed; M2 provides evidence, not approval. |
| **Replay** | Replay Across ExperimentRuns | Identical input evaluated under different ExperimentRun UUIDs | Bitwise identical evaluation hash and trace hash. |
| **Replay** | Overnight Split Target Scaling | Staged target scaled across forward split before Open Execution | Delta correctly matches intended economic target. |
| **Provider Boundary** | Raw Vendor Payload Leakage | Raw Alpaca JSON dictionary passed into strategy or evaluator core | Prohibited; core accepts only Drift domain models. |
| **Provider Boundary** | Missing Halt Synthesized | Alpaca missing halt data interpreted as affirmative "not halted" | Prohibited; missing halt remains unknown. |

---

## 23. Explicit Non-Goals

M2 does NOT implement:
- Strategy promotion decisions, champion/challenger tournaments, or approval (M10/M11).
- Alpha generation or predictive quantitative models (M3+).
- Statistical scorecards, Sharpe ratios, or drawdown analysis (M5).
- Machine learning, reinforcement learning, or LLM agents (M7+).
- Intraday bars, tick data, or high-frequency order books.
- Short selling, margin, leverage, or stock borrowing mechanics.
- Options, futures, foreign exchange, or fixed income.
- Live trading, broker order submission, or Robinhood integration.

---

## 24. Future Architectural Extension Points

1. **Intraday Session Expansion**: The `SessionScope` and `SessionKeyV1` models natively support adding extended hours or hourly intervals without altering accounting kernel mechanics.
2. **Shorting and Margin Facilities**: A future margin kernel can introduce `BorrowAgreementV1` and short position accounts beside the long-only kernel.
3. **Multi-Currency Valuations**: Cash balances can expand to `Mapping[CurrencyCode, Decimal]` with explicit causal exchange-rate mark events.
4. **Market Impact Simulation**: `EvaluationCostModelV1` can incorporate quadratic or square-root volume participation impact models in M12 without breaking V1 linear costs.
