# Drift M1c Corporate Actions and Economic Outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement immutable, causally selected corporate-action terms, actual effects and reported settlements with exact economic components, coverage and replayable outcome composition, using synthetic local evidence only.

**Architecture:** Add a market-specific query/proof/reference family around the existing M1a assertion-selection primitive and M1b retained identity evidence. Three source economic families own terms, effects/owed property, and settlement reports; a separate coverage family supports scoped completeness. A query-bound source policy admits one reporting authority per fact-kind/security occurrence scope before composing facts, without portfolio arithmetic or a cross-source event registry.

**Tech Stack:** Existing Python `>=3.14`, Pydantic, pytest, Ruff, mypy and uv. Standard-library exact decimal/rational validation. No new dependencies or changes to global serialization.

**Spec:** `docs/superpowers/specs/2026-09-05-historical-economic-events-and-observations-design.md`, accepted at `ba1ea66205fda1d649a2bd1034e0c8788c33664d`; ADR 0009. Read both and ADRs 0006-0008 before execution.

**Status:** Implementation in progress, authorized on 2026-09-05 from planning checkpoint `8bc8bbed3abe0ce977445184e4aa495a6a89dd03`. Task 1 is accepted at `055c91ec116357c1502dc0e1a2f4e547147e2e8a`; Task 2 is accepted at `3f4e4455d2fc6a3fa88d1bf5a625a9c7c68e5162`; Task 3 is accepted at `be732c7a73c551795bb2d3605f1d04b91eb2992a`; Task 4 is accepted at `55aa4571d40c7965258dffab6c087dc25de04c2e`; Task 5 is accepted at `4d3f40b447d3ba01f03468c340b72f814431d278`; Task 6 is reviewed and verified for its accepted commit. Task 7 is next; Tasks 7-8 remain pending. This is the sole active M1c plan. The user authorized reviewed task commits and continuation without routine approval stops; M1d has no executable plan or implementation authority.

## Global Constraints

- M0, M1a and M1b are complete; M1b completion is `14bad1733222758ee3836568a10a90f2a16aeac3`.
- “Preserve all M0/M1a/M1b persisted V1 schemas, hashes, fixtures and interpretations.”
- “No dependencies are added.”
- “Enforce these numeric conventions only in additive market-field validators.”
- “No M1b lifecycle or universe record is rewritten because later action/outcome evidence changes.”
- M1c owns historical economic facts only. No prices/OHLCV, observations, normalization, calendars/sessions, action-to-session mapping, missing-observation logic, portfolio accounting, returns, reinvestment, backtest/evaluator, provider/network/broker/runtime-agent capability.
- All source facts and policy/proof artifacts are immutable, explicitly versioned and content-addressed. Hashes and frozen objects establish integrity, not process authorization.
- Initial supported investment scope remains domestic operating-company common shares, primary XNYS/XNAS/XASE, long-only daily research. A receipt may identify excluded property without granting investment eligibility.
- This is the single active executable M1c plan. Its original authoring request stopped after planning; the subsequent 2026-09-05 implementation request authorizes all reviewed M1c slices and commits. Material stop conditions and the M1d boundary still apply.
- Never edit existing source/test/fixture/dependency files as a convenience. Escalate a demonstrated protected-contract change as a material design issue.

---

## Execution preflight, ownership and gates

Run Resume and verify the planning commit against Git before implementation. The design checkpoint is a lower bound, not an instruction to reset the checkout. Preserve all unrelated `.DS_Store` files and `docs/handoffs/2026-09-03-m1b-implementation.md`. Never clean or reformat them. Do not add test package `__init__.py` files; existing tests use peer-module imports such as `from test_assertions import exact_boundary`.

Only additive modules listed below are expected. Existing `src/drift/domain/assertions.py`, `domain/revisions.py`, `domain/manifests.py`, `domain/dataset_validation.py`, `datasets/assertions.py`, `datasets/hashing.py`, `serialization/canonical.py`, all ledger code, M1b runtime, existing tests and existing fixtures are protected. Direct imports avoid changes to old `__init__.py` exports.

| File | Responsibility | First task |
|---|---|---:|
| `src/drift/domain/economic_common.py` | Local numeric types, source keys, recipient/association/date/component types | 1 |
| `src/drift/domain/economic_queries.py` | Closed M1c query variants, proofs, references and binding hashes | 1 |
| `src/drift/domain/economic_events.py` | Terms, effects, settlements, payload/ownership validators | 2 |
| `src/drift/domain/economic_coverage.py` | Coverage, source policy and occurrence-methodology contracts | 3 |
| `src/drift/markets/economic_validation.py` | Four exact role schemas, parsing, full-byte/set validation and context types | 4 |
| `src/drift/markets/economic_selection.py` | Causal selection, retained identity, fresh role references and selected-value replay | 5 |
| `src/drift/domain/economic_results.py` | Association, effect, delivery and outcome projections | 6 |
| `src/drift/markets/economic_outcomes.py` | Policy/coverage/association/occurrence composition and complete replay | 6 |
| `tests/unit/economic_test_support.py` | New deterministic constructors and validated test contexts, no trusted-result shortcuts | 1-6 |
| `tests/unit/test_economic_numbers_queries.py` | Numeric/query wire tests | 1 |
| `tests/unit/test_economic_events.py` | Economic family tests | 2 |
| `tests/unit/test_economic_coverage.py` | Coverage/policy tests | 3 |
| `tests/unit/test_economic_validation.py` | Exact schemas/bytes/sets/empty artifacts | 4 |
| `tests/unit/test_economic_selection.py` | K/E/T, H/V, identity, role/replay attacks | 5 |
| `tests/unit/test_economic_outcomes.py` | Duplication, associations, claim/economic composition | 6 |
| `tests/integration/test_m1c_economic_history.py` | Immutable synthetic histories and support matrix | 7 |
| `tests/fixtures/m1c/v1/` | New immutable source documents/manifests/methodology only | 7 |
| Existing canonical lifecycle documents and this plan | Verified M1c completion, M1d deferred pointers | 8 |

Each load-bearing task has one implementer and a fresh independent reviewer. Tasks 5-7 additionally require a reviewer attacking temporal leakage or economic duplication. The controller verifies findings against actual tests and code. Focused RED precedes production edits; GREEN precedes full gates and review. Do not let an author approve its own task. Do not parallelize writers to a shared file.

The full gate at each accepted slice is:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

The known baseline is 793 passing tests; future tests increase the count. A test that fails only from an import error is initial RED evidence, not enough to establish the eventual assertion's meaning. Once interfaces exist, rerun the behavioral failing assertion before fixing it. Planned commit messages below name review boundaries; execute commits only if the future implementation authorization includes them. Planning approval alone does not grant that authority.

## Settled cross-task contracts

All aliases below are closed `Literal` unions or strict frozen models, not loose strings or generic extension registries. JSON unions use a `kind` discriminator and explicit nullable fields. Unqualified IDs, reasons, source labels and component IDs below are `NonBlankStr`; hash fields are `SHA256Hash`; schema/version literals are explicitly stated. All hash tuples sort uniquely; source component order has a stable `component_id` and is canonicalized by that ID. Unknown evidence uses a typed reason, never fake zero, identity or date. Define ActionKind in economic_common.py in Task 1 using the exact values in contract C, avoiding a query/events import cycle.

### A. Temporal queries and proof meaning

`MarketDecisionQueryV1`: `schema_version='1'`, `kind='decision'`, `purpose='economic_facts'`, `security_id: UUID7`, `action_kinds: tuple[ActionKind,...]` (nonempty, sorted unique), `decision_time: UTCDateTime` (T), `knowledge_cutoff: UTCDateTime` (K), `effective_cutoff: UTCDateTime` (E), `history_start: UTCDateTime`, `requested_channel: AvailabilityChannelV1`, `availability_policy_id: NonBlankStr`, `availability_policy_hash: SHA256Hash`, `source_selection_policy_hash: SHA256Hash`, `input_context_hash: SHA256Hash`. Require `history_start <= E <= T` and `K <= T`.

`MarketOutcomeQueryV1`: same common identity/action-class/channel/policy/context fields, `kind='outcome'`, `purpose='economic_outcome'`, `economic_horizon: UTCDateTime` (H), `evidence_vintage_cutoff: UTCDateTime` (V), `history_start: UTCDateTime`. Require `history_start <= H`; H and V are independently finite, with no invented ordering constraint. If H extends beyond supported evidence, completeness remains unknown/partial; scheduled future events never become actual outcomes. There is no `latest` or M1b `ResolutionMode` field. `MarketSelectionQueryV1` is their discriminated union.

Terms may expose a known scheduled future date as upcoming. Actual application requires the effect/settlement boundary definitely inside the requested window AND definitely no later than K for decisions or V for outcomes: upper<=min(E,K) or min(H,V). Preserve before-window facts for parent/claim evidence, not in-window deliveries. Unknown/overlapping boundaries stay indeterminate. A horizon extending beyond its evidence cutoff has an unknown remainder, even if a source coverage row claims future completeness.

Source-time contradiction is independent of the current query clock. If an occurred/delivered record's actual-boundary lower bound is strictly later than the upper bound of any independently trusted availability evidence on that selected record version, the source says the actual occurrence was known before it could happen. Retain the source claim but mark `actual_claim_predates_occurrence` and withhold realized authority until a correcting record/evidence resolves it. Merely moving K/V past the scheduled date does not cure that defect. Example: actual June1, source availability May1, queried July is still not an occurrence proof without new valid evidence. Overlapping date-only actual/publication bounds are not a definite contradiction and are not rejected globally; normal boundary/availability rules conservatively decide the query. Do not require actual.upper<=publication.lower universally. This rule applies only to actual effect/delivery claims, never legitimate advance terms.

Define `RetainedEconomicIdentityV1` in `src/drift/domain/economic_queries.py` in Task 1: `schema_version='1'`, `identity_kind: Literal['security','listing']`, `identity_id: UUID7`, `cutoff: UTCDateTime`, `channel: AvailabilityChannelV1`, `availability_policy_hash`, `assignment_manifest_hash`, `assignment_decision_hash`, `assignment_bundle_hash`, `selected_assignment_hashes: tuple[SHA256Hash,...]`, `selection_evidence_hashes: tuple[SHA256Hash,...]`, `status: Literal['known','unknown','conflicting']`, `reasons: tuple[NonBlankStr,...]`. Task 5 implements its helper without later changing this wire shape. Listing kind, if queried, proves retained identity only, never affiliation/activity.

`EconomicApplicabilityV1` in Task 1 queries module: `source_record_hash`, `family: Literal['terms','effect','settlement']`, `status: Literal['before_window','in_window','upcoming','indeterminate']`, `reasons`. It is derived from selected source time evidence, not an authorization to expose a raw row.

`MarketSelectionProofV1` fields: `schema_version='1'`, `query: MarketSelectionQueryV1`, `query_hash`, `input_context_hash`, `source_selection_policy_hash`, `selection_algorithm='drift-m1c-economic-selection-v1'`, `selection_algorithm_spec_hash`, `selection_implementation_hash`, `dataset_proofs: tuple[MarketDatasetSelectionV1,...]`, `identity_proofs: tuple[RetainedEconomicIdentityV1,...]`, `revision_selected_record_hashes`, `applicability: tuple[EconomicApplicabilityV1,...]`, `raw_materializable_record_hashes`, `projection_hashes`, `unresolved_chain_hashes`. All unqualified hash collections are sorted unique SHA256Hash tuples. There is no stored proof_hash; every selection_proof_hash is exactly `content_hash(proof)`. `MarketDatasetSelectionV1` fields are `manifest_hash`, `decision_hash`, `bundle_hash`, `role`, `source_id`, `considered_record_hashes`, `chain_selections: tuple[AssertionSelectionResultV1,...]`, `selected_record_hashes` (revision-selected, audit-only). Every validated row participates before subject filtering.

Three sets have different authority: revision-selected records at K/V remain audit-side; applicability interprets economic time for the selected subject/classes/owners; raw-materializable records pass complete nested-identity and role/time checks. Coverage remains audit-only regardless of availability. Composition uses the first two sets and safe projections, never infers no event from absence in the third. A bounded available effect spanning E contributes indeterminacy even though its raw row is withheld. Definitely unavailable future facts do not enter semantic decision conclusions.

`MarketDecisionReferenceV1` and `MarketOutcomeReferenceV1`: `schema_version='1'`, `kind='decision_reference'` or `'outcome_reference'`, `query_hash`, `selection_proof_hash`, `selected_record_hashes` (raw-materializable economic records only), `projection_hashes` (separate derived safe facts). No coverage rows, inventory/methodology payloads, audit context, manifests, considered hashes or alternate records. Empty tuples mean no authorized materialization, not no events. Public replay reconstructs proof/reference equality from actual complete context. Raw APIs return only EconomicRecordV1, never EconomicCoverageVersionV1.

`EconomicComponentGapV1` in Task 1 common module: `component_id`, `source_component_hash`, `reason`, with no recipient/basis UUID. `EconomicSafeFactProjectionV1` in Task 1 queries module: `schema_version='1'`, `query_hash`, `source_record_hash`, `family: Literal['terms','effect','settlement']`, `security_id: UUID7` (causally proved), `action_kind: ActionKind`, `applicability: EconomicApplicabilityV1`, `component_role: Literal['terms','owed','delivered']`, `known_components: tuple[EconomicComponentV1,...]`, `withheld_components: tuple[EconomicComponentGapV1,...]`, `claim_status: Literal['continuing','converted','extinguished','unknown']`, `fact_status: Literal['terms','occurred','cancelled_action','unknown','delivered']`, `consideration_status: Literal['components','explicit_none','unknown']`, `residual_status: Literal['closed_for_occurrence','closed_for_action','outstanding','unknown']`, `optional_context_reasons: tuple[NonBlankStr,...]`, `dependency_proof_hashes`, `projection_algorithm_spec_hash`, `projection_implementation_hash`. No stored self-hash; projection identity is `content_hash(projection)`, distinct from source_record_hash. Projection never copies optional listing_id, raw associations or coverage. This is a derived projection, not a fourth source family. Applicability and source hash bind source time semantics without copying unrelated inventories.

Hash rules for all new derived contracts are uniform: query_hash=`content_hash(query)`, policy hash=`content_hash(policy)`, association/projection/reference/outcome identities=`content_hash(object)`, selection_proof_hash=`content_hash(proof)`. No new proof/result/projection self-hash fields and no arbitrary omitted-field helper. Only existing fixed `revision.payload_hash` and existing schema preimages retain their established exclusions. A context hash binds its explicit canonical input descriptor, not a dataclass repr or unbound path.

Task 5 intrinsic-chronology refinement: source knowability remains requested-channel-specific, but an impossible actual claim is not repaired by transporting the same immutable assertion through a later channel. Evaluate each availability claim on the selected revision with its own channel, the active availability policy and retained evidence, at the actual lower bound. Only independently trusted evidence with upper strictly before actual lower creates the veto. Unknown/unapproved derived evidence and overlapping bounds do not. A genuine correcting selected revision with noncontradictory evidence can restore authority; do not scan older superseded versions to taint it. Root independently replayed the valid dual-channel counterexample at identical July2 H/V: public was indeterminate/raw-withheld while vendor admitted the same source hash. This bounded refinement changes neither M1a selection nor any old schema.

Task 1 execution clarification, supported by failing state-matrix probes: terms projections have fact_status=terms, component_role=terms, claim_status=unknown and residual_status=unknown. Their consideration is components when a known/withheld component exists, otherwise unknown. Only occurred effects may carry sourced claim/consideration/residual state; cancelled_action and unknown effects have role owed, no components, and unknown claim/consideration/residual. Settlement projections have fact_status=delivered, role delivered, claim_status=unknown and component consideration with at least one known/withheld component; all sourced residual states are permitted, including outstanding and closed_for_action. Non-component consideration cannot carry component values or gaps. This closes impossible derived states without adding a new source family or conflating promises/payment with claim-state evidence.

Algorithm-spec hashes and implementation hashes are different. Store `content_hash` of a literal semantic-rule specification dictionary as each `*_algorithm_spec_hash`; pin that dictionary/version in tests. Store a byte-implementation digest as `*_implementation_hash`: add `economic_implementation_hash() -> str` in Task 1 common module, hashing a canonical sorted inventory of relative paths and exact SHA-256 bytes for every `.py` source file under the installed `drift` package. Inventory format is `{'profile':'drift-python-source-inventory-v1','files':[{'path':relative_posix_path,'sha256':digest}]}`. Reject symlinks/unreadable files; never include caches, absolute locations or timestamps. This is a source-code identity hook, not an environment/replay package. All byte hashes bind current exact code; spec hash alone is not code identity. No old hash algorithm changes.

### B. Source keys, associations and components

`EconomicFamily = Literal['terms','effect','settlement','coverage']`.

`EconomicSourceKeyV1`: `source_id`, `family`, `native_record_id`. Stable source logical report identity maps bijectively to `revision.logical_record_id` across supplied artifacts. A correction changes the report version, never generates another economic payment. Never use ticker/date/amount/action label as identity.

`EconomicOccurrenceV1`: `kind: Literal['identified','unknown']`, `native_occurrence_id: NonBlankStr | None`, `evidence_reference: ArtifactReference | None`, `reason: NonBlankStr | None`. Identified requires ID and evidence; unknown requires reason and no ID. This is a sourced semantic occurrence attribution, not the stable source report key. A correction may change unknown-to-identified or identified-to-different-identified within the same report chain. Select the complete chain at K/V before grouping. Many reports may identify one occurrence; distinct IDs prove distinct occurrences only under the selected source's verified occurrence methodology. A source-specific immutability guarantee is methodology evidence, not a global wire restriction.

`EconomicAssociationV1` source claim: `kind: Literal['identified','native_hint','unknown']`, `target: EconomicSourceKeyV1 | None`, `asserted_target_version_hash: SHA256Hash | None`, `native_hint: NonBlankStr | None`, `reason: NonBlankStr | None`. Identified requires target; optional asserted version is a source assertion checked against selected evidence. Hints/unknown do not pretend exact parents. Query-neutral source facts never persist a decision/outcome reference. Query results resolve to exact selected targets or unresolved/conflicting reasons.

`EconomicRecipientV1`: `kind: Literal['security','unresolved_property']`, `security_id: UUID7 | None`, `source_property_key: NonBlankStr | None`, `reason: NonBlankStr | None`. Security requires UUID; unresolved requires source key/reason and no UUID. Storage may retain a reported UUID without causal proof. A safe projection withholds that component's UUID/value behind a typed gap while preserving other independently established components, such as cash in the same row. Optional listing context is source-reported audit context only and does not suppress security-bound cash or imply affiliation, termination or eligibility.

`FractionTreatmentV1`: `kind: Literal['fraction_issued','round_up','round_down','round_nearest','aggregate_sale_cash','unknown']`, `source_rule: NonBlankStr | None`, `evidence_reference: ArtifactReference | None`. All known rules require source rule/evidence; unknown has neither. No cash-in-lieu calculation.

`EconomicUnitBasisV1`: `security_id: UUID7`, `denominator: PositiveRatioV1`, `share_basis: Literal['predecessor_pre_action','predecessor_post_action','as_reported_unknown']`. PositiveRatioV1 is defined in Task 1; the denominator is the explicit number of units to which a cash amount applies. `EconomicShareBasisV1` has only `security_id` and the same `share_basis` field: the share component's ratio already supplies its denominator.

`CashComponentV1`: `kind='cash'`, `component_id`, `amount: CanonicalCash`, `currency_namespace`, `currency_code`, `unit_basis: EconomicUnitBasisV1`, `amount_basis: Literal['gross','net','unknown']`, `applicability: Literal['ordinary_passive_holder','conditional','unknown']`, `conditions: tuple[NonBlankStr]`, `source_amount_text: str | None`, `source_precision: int | None` (nonnegative).

`ShareComponentV1`: `kind='shares'`, `component_id`, `recipient: EconomicRecipientV1`, `ratio: PositiveRatioV1`, `ratio_meaning: Literal['resulting_per_predecessor','additional_per_predecessor']`, `unit_basis: EconomicShareBasisV1`, `fraction_treatment: FractionTreatmentV1`, `applicability`, `conditions` with the same types as cash. Never divide this ratio by another per-unit denominator.

`UnsupportedPropertyComponentV1`: `kind='unsupported_property'`, `component_id`, `recipient`, `source_description: NonBlankStr`, `reason: NonBlankStr`, `evidence_reference: ArtifactReference`. No invented valuation/ratio. `EconomicComponentV1` is the cash/share/unsupported-property union. Property receipts remain evidence, not investment eligibility.

`EconomicDateFactV1`: `role: Literal['announcement','approval','ex','record','payable','due_bill_start','due_bill_end','due_bill_redemption','legal_effect','trading_basis']`, `boundary: TemporalBoundaryClaimV1`, `rule_reference: ArtifactReference | None`. Date roles are unique within a record and no universal cross-role ordering is imposed. Scheduled/effective top-level fields below own their named time; do not duplicate their values under another alias.

### C. Three economic families, not four

Every record has `schema_version='1'`, `revision: RevisionEnvelopeV1`, `source_key: EconomicSourceKeyV1`, `security_id: UUID7`, `listing_id: UUID7 | None`, `occurrence: EconomicOccurrenceV1`, and `source_action_code: NonBlankStr | None`. Hash validation uses unchanged `assertion_version_payload(record)`. Source/family/native report key remain invariant in a revision chain. A sourced correction may change security attribution, action kind, dates or components; select the complete chain before security/date/class filtering. `RevisionKind.WITHDRAWAL` removes the source assertion under M1a and requires `payload=None`; it is not action cancellation, claim extinction or repayment.

`ActionKind` exact values: `forward_split`, `reverse_split`, `regular_cash_dividend`, `special_cash_distribution`, `stock_dividend`, `cash_acquisition`, `stock_acquisition`, `mixed_acquisition`, `spinoff`, `conversion`, `liquidation`, `bankruptcy_reorganization`, `rights_warrants_cvr`, `other_unsupported`.

`CorporateActionTermsVersionV1`: common fields plus `scheduled_effect_time: TemporalBoundaryClaimV1`, `payload: TermsPayloadV1 | None`. TermsPayloadV1 fields: `kind: Literal['fixed','incomplete','unsupported']`, `action_kind: ActionKind`, `components: tuple[EconomicComponentV1]`, `dates: tuple[EconomicDateFactV1]`, `conditions: tuple[NonBlankStr]`, `reason: NonBlankStr | None`. Fixed requires complete applicable components and ordinary holder applicability; incomplete/unsupported requires reason. Terms never assert occurrence or delivery.

`EconomicEffectVersionV1`: common fields plus `effective_time: TemporalBoundaryClaimV1`, `terms_association: EconomicAssociationV1`, `payload: EffectPayloadV1 | None`.

`OccurredEffectV1`: `kind='occurred'`, `action_kind`, `claim_status: Literal['continuing','converted','extinguished','unknown']`, `consideration_status: Literal['components','explicit_none','unknown']`, `owed_components`, `residual: ResidualClaimV1`, `evidence_reference: ArtifactReference`. Components requires a nonempty tuple; explicit_none/unknown require empty tuple. Explicit_none requires the source evidence and names this occurrence's consideration only, not lifetime recovery. `CancelledActionV1`: `kind='cancelled_action'`, `action_kind`, `reason`, `evidence_reference`. It never changes claim status or proves no consideration. `UnknownEffectV1`: `kind='unknown'`, `action_kind`, `reason`. These form EffectPayloadV1.

`ResidualClaimV1`: `kind: Literal['closed_for_occurrence','closed_for_action','outstanding','unknown']`, `scope_occurrence_id: NonBlankStr | None`, `scope_action: EconomicAssociationV1 | None`, `evidence_reference: ArtifactReference | None`, `reason: NonBlankStr | None`. Closed_for_occurrence requires exact occurrence ID and evidence, with no action field. Closed_for_action requires an identified terms/effect source association and evidence asserting no further consideration for that action, with no occurrence ID. Outstanding/unknown require reason and may supply an action association; they cannot establish closure. Query-time action closure applies to prior settlements only after exact causal action association and chronology are established. It never removes deliveries or declares lifetime proceeds zero.

`EconomicSettlementVersionV1`: common fields plus `settled_time: TemporalBoundaryClaimV1`, `terms_association`, `effect_association`, `payload: DeliveredSettlementV1 | None`. DeliveredSettlementV1 fields: `kind='delivered'`, `action_kind`, `delivered_components` (nonempty), `residual`, `evidence_reference`. A known settlement with unknown parents is valid. Promised amount can only occur in terms/owed components; it cannot enter this payload unless the source reports delivery.

### D. Bounded composition and coverage

`EconomicSourceSelectionPolicyV1`: `schema_version='1'`, `policy_id`, `policy_version`, `security_id: UUID7`, `action_kinds: tuple[ActionKind,...]`, `scope='all_security_occurrences'`, `history_start: UTCDateTime`, `through: UTCDateTime`, `owners: tuple[EconomicSourceOwnerV1]`, `input_dataset_bindings: tuple[DatasetBindingV1]`. It is a research policy artifact, not historical source publication. `DatasetBindingV1` fields `manifest_hash`, `decision_hash`, `bundle_hash`, `role`, `source_id`. Owners: `family: Literal['terms','effect','settlement']`, `source_id`, `fact_manifest_hash`, `coverage_manifest_hash`. Require exactly one owner for each family. No within-family/security date partitions, priority fallback or implicit source replacement in V1. Alternate datasets remain in context and bound but are not receipts. Policy scope/history/through/action classes must exactly match query security/window; changing any input/policy changes result identity. Policy binds raw manifest/methodology identities, never a coverage selection proof whose query would contain the policy hash. Dependency order is raw datasets -> policy -> query -> selection -> outcome.

This chooses a smaller allowed ADR 0009 subset: multiple sources can supply different fact families and securities, but V1 declines within-pair occurrence partitioning. It removes a fundamental date/ownership ambiguity without a registry. Switching ownership between runs is a new policy, not reinterpretation of an old result.

`EconomicCoverageVersionV1`: same revision/source/security/listing common fields, but no economic occurrence field; `coverage_interval: TemporalIntervalClaimV1`, `fact_family: Literal['terms','effect','settlement']`, `action_kinds: tuple[ActionKind]`, `target_manifest_hash`, `inventory_artifact_hashes`, `inventory_record_hashes`, `methodology_reference: ArtifactReference`, `methodology_version`, `snapshot_at: UTCDateTime`, `completeness: Literal['complete','partial','unknown']`, `revision_support: Literal['captured_history','current_only','unknown']`, `occurrence_key_semantics: Literal['economic_occurrence_ids','report_ids_only','unknown']`, `gaps: tuple[TemporalIntervalClaimV1]`, `exceptions: tuple[NonBlankStr]`. No self-hash cycle: coverage references fact manifests, not its own manifest. Complete requires verified exact inventory, evidence-bearing methodology, no relevant gaps/exceptions, and precise interval containment. Captured_history is required for no-missing-historical-revisions claims. Current_only facts may be selected only at evidenced vintages; never infer earlier availability.

V1 inventory matching is strict: target_manifest_hash, inventory_artifact_hashes and inventory_record_hashes match that entire retained fact dataset's exact validated inventory, not an old subset claimed to cover a newer manifest. Coverage assertion availability cannot precede its actual inventory snapshot; a complete scope cannot extend past that snapshot or omit a version that its declared inventory contains. Preserve separate immutable old/new dataset, coverage, policy and context snapshots for historically complete composition. On the newer full-chain context at an old V, select the same old report/component values but leave completeness/grouping indeterminate or uncomposed if matching contemporaneous coverage is unavailable. Do not create historical inventory witnesses, flexible subset matching or a fallback archive registry. An older partial coverage assertion must not pretend its inventory equals a later dataset.

Do not sum components numerically. Composition produces distinct delivered occurrence groups and separate owed terms/effects. Group by positively evidenced `(authoritative_source_id, security_id, native_occurrence_id)`; unknown/report-only occurrence semantics yield known uncomposed reports plus `ownership_unknown`. Same identified occurrence with identical canonical economic payload coalesces reports once and retains all report hashes. Same occurrence with conflicting applicable payloads yields conflict; neither amount/date equality nor hash equality across unrelated occurrences is a matching algorithm. Two different IDs count as distinct only when coverage/methodology establishes economic occurrence identity. Corrections replace a report version before grouping, not create another occurrence.

## Task 1: Exact primitives and additive temporal/query contracts

**Files:** Create `src/drift/domain/economic_common.py`, `src/drift/domain/economic_queries.py`, `tests/unit/test_economic_numbers_queries.py`, `tests/unit/economic_test_support.py`.

**Interfaces:** Produces all common types, ActionKind, RetainedEconomicIdentityV1 and query/proof/reference/projection models in contracts A/B, including complete declared fields before consumers import them. Functions: `validate_canonical_cash(value: object) -> str`, `market_cutoff(query: MarketSelectionQueryV1) -> datetime`, `market_horizon(query: MarketSelectionQueryV1) -> datetime`, `economic_implementation_hash() -> str`. PositiveRatioV1 fields are canonical positive integer strings numerator/denominator with gcd one. No floats or Decimal conversion of source input, no arbitrary self-hash helper.

- [x] Write tests including this behavioral RED and query K/E/T pairs:

```python
import pytest
from pydantic import TypeAdapter, ValidationError
from drift.domain.economic_common import CanonicalCash, PositiveRatioV1


@pytest.mark.parametrize(
    "text", ["1e3", "+1", "01", "1.0", "-0", "0.00", "NaN", "Infinity"]
)
def test_noncanonical_cash_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CanonicalCash).validate_python(text)


def test_exact_ratio_and_cash_round_trip() -> None:
    ratio = PositiveRatioV1(numerator="3", denominator="2")
    assert PositiveRatioV1.model_validate_json(ratio.model_dump_json()) == ratio
    assert TypeAdapter(CanonicalCash).validate_python("5.125") == "5.125"
    with pytest.raises(ValidationError):
        PositiveRatioV1(numerator="6", denominator="4")
```

- [x] Run `uv run pytest tests/unit/test_economic_numbers_queries.py -q`; confirm missing interfaces first, then semantic failures for any partial implementation.
- [x] Implement the local validator kernel and strict frozen model validators:

```python
import re
from math import gcd
from typing import Annotated
from pydantic import BeforeValidator, model_validator
from drift.domain.common import FrozenModel


def validate_canonical_cash(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", value) is None
    ):
        raise ValueError("cash requires canonical nonnegative decimal text")
    return value


type CanonicalCash = Annotated[str, BeforeValidator(validate_canonical_cash)]


class PositiveRatioV1(FrozenModel):
    numerator: str
    denominator: str

    @model_validator(mode="after")
    def exact_positive(self) -> PositiveRatioV1:
        if any(
            re.fullmatch(r"[1-9][0-9]*", item) is None
            for item in (self.numerator, self.denominator)
        ):
            raise ValueError("ratio requires positive canonical integers")
        if gcd(int(self.numerator), int(self.denominator)) != 1:
            raise ValueError("ratio must be reduced")
        return self
```

Cash source reports in this first delivered/owed profile are nonnegative; negative adjustments must be detected unsupported, not netted as accounting. Zero is a sourced component, never an unknown fallback. Numeric aliases are local and do not alter existing Decimal serialization.

Query validators compare contract A datetime fields and reject opposite-role fields through extra='forbid'. New hashes always use full external content_hash as specified above. Test self-consistent outcome-reference JSON rejected by the decision-reference discriminator. Add literal digest fixtures for query, policy, proof, reference, association and outcome plus a mutation table asserting each semantically/provenance-relevant field changes the full digest. A later Task adds its result fixture when that type exists; no earlier wire type changes. Test source-byte change alters implementation hash even if the semantic spec dictionary is unchanged.

- [x] Add exact tests: K>T, E>T, start>E, start>H, independently ordered H/V accepted, naive dates, outcome H/V in decision payload, decision T/K/E in outcome payload, zero selected hashes valid reference, canonical source-key/recipient union shape and ratio meaning missing rejected. Valid query fixtures bind literal known hash strings here only; no Task 1 proof claims authenticity.
- [x] Run focused GREEN, full gate and independent review. Proposed accepted boundary: `feat: add exact M1c economic primitives and queries`.

## Task 2: Terms, actual effects and settlement reports

**Files:** Create `src/drift/domain/economic_events.py`, `tests/unit/test_economic_events.py`; extend only `tests/unit/economic_test_support.py`.

**Interfaces:** Consumes Task 1 components. Produces all three record families in contract C, `EconomicRecordV1` union, `economic_record_family(record: EconomicRecordV1) -> EconomicFamily`, and `classify_economic_shape(record: EconomicRecordV1) -> Literal['supported','unsupported','indeterminate']`, implementing the exact shape rules printed in Task 7 now so Task 6 has a defined dependency. Implements `validate_economic_record_ownership(records: Sequence[EconomicRecordV1]) -> tuple[ValidationFindingV1, ...]` with immutable source-report/logical revision identity only; security and occurrence attribution are selected semantic payload. This validates reports, not economic source authority.

Task 2 execution clarification: payload-level terms conditions describe closing/occurrence context and do not by themselves vary the promised consideration. Fixed ordinary-holder components can remain supported terms before shareholder/regulatory approval, without establishing occurrence. Component-level conditions or conditional/unknown applicability describe holder economics and remain unsupported/indeterminate as appropriate. Do not parse free-form condition text to infer either status. The strongest case for a blanket conditions ban is simple validation; the contrary primary evidence is a fixed 1.0192 exchange ratio alongside closing conditions in the [Capital One/Discover agreement filing](https://www.sec.gov/Archives/edgar/data/927628/000119312524042826/d780383d8k.htm). Separate typed component applicability from disclosed closing context, with paired regression tests.

Task 2 classifier repair ruling: complete fixed terms require their applicable full vector, but a settlement report can contain one valid delivered cash/share leg without other legs in that same record. Validate family-local components without inferring action completion or doing aggregation. Unknown/cancelled effects and explicit sourced no-consideration claim cancellation are classified before broad unsupported-family guards. Basic fixed bankruptcy/reorganization cash/share facts are not unsupported solely by their action label; complex or conditional economics remain explicitly limited. Controller probes reproduced both a valid mixed cash leg and a bankruptcy no-consideration cancellation being incorrectly rejected, requiring behavioral regression tests before repair. Action-specific and corrected fixture evidence must state final semantic values, not stale default labels or only changed field names.

- [x] Add test-only constructors with these exact signatures: `seal_record[T: FrozenModel](model: type[T], values: dict[str, object]) -> T`; `cash_component(amount: str='5', component_id: str='cash') -> CashComponentV1`; `terms_record(suffix: int, action_kind: ActionKind='regular_cash_dividend', known_at: str='2020-05-01T00:00:00Z', scheduled_at: str='2020-06-01T00:00:00Z') -> CorporateActionTermsVersionV1`; `effect_record(suffix: int, kind: Literal['occurred','cancelled_action','unknown']='occurred', claim_status: Literal['continuing','converted','extinguished','unknown']='continuing', effective_at: str='2020-06-01T00:00:00Z', known_at: str|None=None) -> EconomicEffectVersionV1`; `settlement_record(suffix: int, amount: str='5', occurrence_id: str|None='payment-1', settled_at: str='2020-06-15T00:00:00Z', known_at: str|None=None) -> EconomicSettlementVersionV1`; `revise_record[T: EconomicRecordV1](record:T, suffix:int, known_at:str, changes:dict[str,object]) -> T`. Effect/settlement known_at defaults to the actual effect/settled instant, never inherited 2018 availability. Deliberate contradictory-source fixtures pass an earlier known_at explicitly.

Use existing uid/revision/bounded_boundary/exact_boundary/public_availability/parse_utc helper shapes without modifying them. The old artifact() helper is permitted only for model-shape tests, never a genuine M1c validated context: its fixed digest has no bytes. Add `economic_evidence(statement: str) -> tuple[ArtifactReference, VerifiedArtifactBytes]`, producing independent canonical bytes `{'schema_version':'1','synthetic_source_statement':statement}`, a SHA-256-addressed ArtifactReference and its actual bytes. Each record constructor creates distinct source statement/effect/settlement evidence with its report ID/amount/action in statement text, substitutes actual references into revision.source_artifact and availability evidence_reference, and into every known occurrence/fraction/date/residual/component reference. Test helper `support_bytes(reference: ArtifactReference) -> VerifiedArtifactBytes` may reconstruct those deterministic synthetic bytes from its encoded safe statement locator, verifying the digest; no runtime registry is added. Raw source bytes precede normalized record/partition bytes, avoiding self-reference. All constructors default to security uid(21), synthetic-a, listing None, unknown associations/residual, and report-{suffix}. Cash uses ISO-4217 USD, denominator 1/1, predecessor_pre_action, gross ordinary passive holder, no conditions. Action-specific tests replace components explicitly.

```python
from drift.datasets.hashing import assertion_version_payload
from drift.serialization.canonical import content_hash
from drift.domain.common import FrozenModel


def seal_record[T: FrozenModel](model: type[T], values: dict[str, object]) -> T:
    from drift.domain.assertions import RevisionEnvelopeV1

    provisional = model.model_construct(**values)
    source_revision = values["revision"]
    if not isinstance(source_revision, RevisionEnvelopeV1):
        raise TypeError("fixture requires a real revision envelope")
    corrected_revision = source_revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return model.model_validate({**values, "revision": corrected_revision})
```

The helper bypass is test-only to compute a self-excluding hash; final construction always validates. `revise_record` retains logical/source report IDs, sets CORRECTION, predecessor version, incremented sequence and new availability, applies supplied semantic changes including security and occurrence-attribution corrections, then seals. Initial payload hashes are computed, never hardcoded as valid.

- [x] Write and run concrete RED:

```python
from economic_test_support import terms_record, effect_record, settlement_record


def test_announcement_cancelled_action_and_payment_are_distinct() -> None:
    terms = terms_record(100)
    cancelled = effect_record(200, kind="cancelled_action")
    paid = settlement_record(300)
    assert terms.payload is not None
    assert cancelled.payload is not None
    assert paid.payload is not None
    assert terms.payload.kind == "fixed"
    assert cancelled.payload.kind == "cancelled_action"
    assert not hasattr(cancelled.payload, "claim_status")
    from drift.domain.economic_common import CashComponentV1

    component = paid.payload.delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"
    assert paid.terms_association.kind == "unknown"
```

Run `uv run pytest tests/unit/test_economic_events.py -q` and confirm the missing event interfaces/behavior before implementation.

- [x] Implement frozen typed models exactly as contract C, component discriminators and local hash checks. Core record validator:

```python
from drift.datasets.hashing import assertion_version_payload
from drift.domain.revisions import RevisionKind
from drift.serialization.canonical import content_hash


def require_economic_payload(record: EconomicRecordV1) -> None:
    withdrawn = record.revision.revision_kind is RevisionKind.WITHDRAWAL
    if withdrawn != (record.payload is None):
        raise ValueError("only withdrawal has no payload")
    if record.revision.payload_hash != content_hash(assertion_version_payload(record)):
        raise ValueError("economic payload hash mismatch")
    if record.source_key.family != economic_record_family(record):
        raise ValueError("economic source family mismatch")
```

`require_economic_payload` is private module-local logic invoked by each record's after-validator, not a caller's authority. Preserve unknown boundary claims. Withdrawal still carries the prior family shape/time metadata but emits no economic effect.

- [x] Test meaningful variants: split 2/1 and reverse 1/10 resulting ratios; fraction round-up; same-security additional stock dividend; spinoff with parent continuing; fixed conversion; cash/stock/mixed acquisition; independent dividend dates/due bills; late/date-only evidence; explicit_none requires evidence/no components; unknown never empty-known; delivered cash with missing parents remains valid. Implement/classify every fixed/unsupported/indeterminate action rule listed in Task 7 in THIS task. Classifier evaluates the facts supplied by each family: terms classification never requires occurrence; cross-family completion is Task 6. This produces the complete classifier before its consumer.
- [x] Test ownership changes: same source record split across two logical IDs and changed source/family reject; known occurrence changed by causal correction and unknown occurrence clarified with evidence remain valid; security/date/amount corrections retain the report chain. Call existing `validate_assertion_chain` on each logical chain as well as ownership checks. Paired old/later cutoffs group one corroborated payment before an occurrence-attribution correction and two genuinely distinct payments afterward, never both versions of the corrected report.
- [x] Run focused GREEN, full gate and fresh economic review. Proposed boundary: `feat: add immutable M1c terms effects and settlements`.

## Task 3: Evidence-bearing coverage and bounded source policy

**Files:** Create `src/drift/domain/economic_coverage.py`, `tests/unit/test_economic_coverage.py`; extend `tests/unit/economic_test_support.py`.

**Interfaces:** Implements all contract D models; `EconomicInputRecordV1 = EconomicRecordV1 | EconomicCoverageVersionV1`; `coverage_contains(coverage: EconomicCoverageVersionV1, start: datetime, through: datetime) -> bool`; `policy_owner(policy: EconomicSourceSelectionPolicyV1, family: Literal['terms','effect','settlement']) -> EconomicSourceOwnerV1`. Absence of owner is invalid policy, not fallback.

Task 3 execution clarification: a coverage row's complete field is a source declaration within its stated scope, not derived historical completeness or occurrence-grouping authority. Preserve current_only, report_ids_only and narrower valid action-class sets; do not reject split-only settlement coverage without comparing an actual query. Tasks 4/6 must verify inventories/methodology and compare requested scope before granting those conclusions. This follows contract D's admitted values and separates current snapshot completeness from captured revision history. Exact zero-row datasets require empty record inventories to remain valid. Revision construction remains test-only, with no production correction builder. The strongest case for stricter wire rejection is simplicity; its demonstrated cost is discarding legitimate limited source evidence instead of reporting the limitation at the correct boundary.

Task 3 review clarification: every selected owner must name matching fact and coverage input bindings under the same source and corresponding role; extra alternate inputs remain valid. A coverage assertion cannot have any known availability upper bound before its inventory snapshot. One late channel cannot rescue a definitely early channel. Exact equality, bounded straddling and unknown evidence remain representable, with authority still dependent on normal requested-channel selection and snapshot gating. The reviewer initially proposed requiring every lower bound after the snapshot; the controller challenged this because M1a selects only at/after the upper bound, so a straddling claim cannot authorize pre-snapshot coverage. The reviewer accepted the narrower definite-contradiction rule. Coverage fixture source bytes must preserve complete acyclic semantics, including security and interval, rather than a hand-picked subset; the controller reproduced distinct security corrections with the same raw source hash before repair.

- [x] Write RED for duplicate owners and coverage-class mismatch; construct policy with owners `(terms,a),(effect,b),(settlement,a)` and reject a second `(settlement,b)` regardless of disjoint-looking dates. Constructors `coverage_record(suffix: int, family: Literal['terms','effect','settlement'], target_manifest_hash: str, inventory_artifact_hashes: tuple[str,...], inventory_record_hashes: tuple[str,...], completeness: Literal['complete','partial','unknown']='complete') -> EconomicCoverageVersionV1` and `source_policy(security_id: UUID, bindings: tuple[DatasetBindingV1,...], owners: tuple[EconomicSourceOwnerV1,...], history_start: datetime, through: datetime) -> EconomicSourceSelectionPolicyV1` are added here. Fixture coverage is half-open 2020-01-01 to 2021-01-02 and explicitly lists applicable action classes, captured_history and economic_occurrence_ids methodology.

```python
def test_source_policy_has_one_authority_per_family() -> None:
    from pydantic import ValidationError
    import pytest
    from economic_test_support import policy_fixture

    policy = policy_fixture()
    assert len(policy.owners) == 3
    duplicate = policy.owners[-1].model_copy(update={"source_id": "synthetic-b"})
    with pytest.raises(ValidationError):
        policy.model_copy(update={"owners": (*policy.owners, duplicate)})
```

`policy_fixture() -> EconomicSourceSelectionPolicyV1` is a new test-only builder using source_policy with security uid(21), exact dates above, one owner per family and distinct fixed hash placeholders. It tests shape only; no resolution test may use its placeholder bindings.

- [x] Run `uv run pytest tests/unit/test_economic_coverage.py -q`; confirm RED. Implement closed model fields and exact scope validation:

```python
def require_owner_partition(policy: EconomicSourceSelectionPolicyV1) -> None:
    families = tuple(owner.family for owner in policy.owners)
    if sorted(families) != ["effect", "settlement", "terms"]:
        raise ValueError("exactly one owner per economic family required")
    if policy.history_start > policy.through:
        raise ValueError("source policy window reversed")
```

Coverage local shape distinguishes complete from partial/unknown; byte inventory/methodology proof is checked in Task 4/6, not magically trusted by this model. Preserve half-open coverage interval semantics: `coverage_contains` requires interval start upper_bound<=start and interval end lower_bound>through to contain the query's inclusive economic horizon; unknown bounds return False. Fixture coverage end is 2021-01-02 for queries through 2021-01-01. No interval-calendar calculations.

- [x] Add tests showing splits-only coverage cannot establish settlements, report_ids_only cannot prove distinct payouts, marketing-only/absent methodology cannot pass complete coverage, current_only cannot establish prior historical revision coverage, correction immutability, duplicate/unsorted inventory hashes rejected and policy hash changes on source/scope/binding edits. Snapshot tests must prove that the same instant with a non-UTC offset normalizes to UTC, removing tzinfo rejects, and a snapshot earlier than an included source version's availability cannot establish complete inventory. The helper's string input is parsed with parse_utc before constructing snapshot_at; the persisted field is UTCDateTime, never lexical ordering of source strings. Task 4 repeats the inconsistent snapshot case through actual bytes/context validation, not only the fixture constructor.
- [x] Run GREEN, full gate and fresh review. Proposed boundary: `feat: add M1c coverage and source selection policy`.

## Task 4: Exact role datasets, empty evidence and closed input contexts

**Files:** Create `src/drift/markets/economic_validation.py`, `tests/unit/test_economic_validation.py`; extend `tests/unit/economic_test_support.py`.

**Interfaces:**

```text
economic_role_schema(role: str) -> SchemaDescriptorV1
economic_role_contract(role: str, channels: tuple[AvailabilityChannelV1, ...]) -> AssertionTemporalContractV1
parse_economic_document(data: bytes, role: str) -> tuple[EconomicInputRecordV1, ...]
validate_economic_dataset(manifest: DatasetManifestV2, verified_artifacts: Sequence[VerifiedArtifactBytes], run: ValidationRunContextV1) -> tuple[DatasetValidationDecisionV2, tuple[EconomicInputRecordV1, ...]]
validate_economic_context(context: EconomicResolutionContext) -> None
economic_context_hash(context: EconomicResolutionContext) -> str
require_m1c_evidence_closure(context: EconomicResolutionContext) -> None
economic_coverage_methodology_supported(record: EconomicCoverageVersionV1, supporting_artifacts: Sequence[VerifiedArtifactBytes]) -> bool
```

Task 4 methodology ruling: reference presence or a hashed document repeating coverage fields does not establish omission/revision/occurrence method. The first implementation recognizes one closed synthetic supporting-artifact profile with exact canonical JSON keys: schema_version='1', kind='drift_economic_coverage_methodology', methodology_version matching the coverage record, omission_detection='closed_artifact_and_record_inventory', revision_tracking='source_sequence_and_supersession', occurrence_identification='stable_economic_occurrence_id'. The pure helper verifies the referenced SHA and length and rejects extra/missing keys or unknown capabilities by returning false. Exact context closure separately rejects missing/corrupt/extra/duplicate evidence bytes; well-hashed unknown or marketing-only method content does not erase independently valid facts. True recognizes only the method capabilities, never derived completeness, grouping or consumer authority. Task 6 must still check weaker declared current_only/report_ids_only limits, exact source/inventory/query scope and causal cutoff. The alternative of reference-only validation is simpler but would admit the marketing-only case that the spec explicitly excludes. This bounded local format is not a provider protocol, registry or new economic source family; real-source methodology admission remains a future reviewed contract.

`EconomicDatasetInput` frozen dataclass: `records: tuple[EconomicInputRecordV1,...]`, `manifest`, `decision`, `verified_artifacts: tuple[VerifiedArtifactBytes,...]`, `validation_run: ValidationRunContextV1`, `bundle: ValidatedDatasetBundleV1`. `EconomicIdentityInput` has the same fields but records are `IdentityAssignmentVersionV1`. `EconomicResolutionContext` frozen dataclass: `datasets: tuple[EconomicDatasetInput,...]`, `identity: EconomicIdentityInput`, `availability_policy: AvailabilityPolicyV1`, `retained_evidence: Mapping[str, AvailabilityEvidenceV1]`, `supporting_artifacts: tuple[VerifiedArtifactBytes,...]`. Snapshot mutable mappings/tuples at public entry; frozen dataclass is not authority.

Context fingerprint binds sorted role/source/manifest/decision/bundle hashes, exact artifact hashes, identity binding, availability policy and retained evidence hashes, supporting artifact hashes and a context schema version. It does not contain source-selection policy, so the policy can bind datasets without a hash cycle. V1 permits one dataset per `(source_id,role)` in a context; multiple providers use separate existing bundles, never duplicate role names in one BundleV1.

Task 4 interface clarification: source-policy input_dataset_bindings covers exactly the economic inputs in context.datasets. The independent context.identity input is bound separately by the context descriptor/hash, not by an invented identity owner or extra source-policy binding. Task 5 must verify this same split, with the full context hash still binding identity evidence into every query/proof.

Four exact role names are economic_terms/economic_effect/economic_settlement/economic_coverage, all DatasetRoleV1(namespace='drift', version='1'). Build exact SchemaDescriptorV1 fields from the following closed table; notation S/I/J/D means LogicalType.STRING/INTEGER/JSON/DATETIME, `?` means nullable and absence of `?` means non-null. The document parser also checks the exact Pydantic model, so descriptors do not replace payload validation.

| Role portion | Exact field IDs, logical types and nullability |
|---|---|
| Shared across all four | schema_version:S, revision.schema_version:S, revision.logical_record_id:S, revision.record_version_id:S, revision.revision_kind:S, revision.supersedes_record_version_id:S?, revision.source_sequence:I, revision.availability:J, revision.history_completeness:S, revision.source_native_revision_label:S?, revision.source_artifact:J, revision.payload_hash:S, source_key:J, security_id:S, listing_id:S? |
| Three economic families only | occurrence:J, source_action_code:S?, payload:J? |
| economic_terms | scheduled_effect_time:J |
| economic_effect | effective_time:J, terms_association:J |
| economic_settlement | settled_time:J, terms_association:J, effect_association:J |
| economic_coverage only | coverage_interval:J, fact_family:S, action_kinds:J, target_manifest_hash:S, inventory_artifact_hashes:J, inventory_record_hashes:J, methodology_reference:J, methodology_version:S, snapshot_at:D, completeness:S, revision_support:S, occurrence_key_semantics:S, gaps:J, exceptions:J |

No extra top-level revision:J descriptor is added: its fixed nested paths above are the manifest fields. `economic_role_contract` binds the unchanged eight revision ID/kind/predecessor/sequence/availability/source/hash paths, the role-specific scheduled_effect_time/effective_time/settled_time as BOUNDARY or coverage_interval as INTERVAL, and semantic_state_field_ids equal every other table field except those eight bound revision paths and the selected effective field. Declared channels are supplied explicitly and canonicalized by the existing contract. Sort fields by field_id; hash via existing schema_hash. No source strings add schema fields, and no dynamic JSON-schema inference or generic registry is introduced. Four local schema/parser constants are exact and hash-pinned before acceptance.

- [x] Add `economic_dataset(role: str, records: tuple[EconomicInputRecordV1,...], source_id: str='synthetic-a') -> EconomicDatasetInput` and `validated_case(records: tuple[EconomicRecordV1,...], *, complete_coverage: bool=True, owner_source: str='synthetic-a', through: str='2021-01-01T00:00:00Z', coverage_snapshot_at: str|None=None) -> EconomicHarness`. EconomicHarness frozen fields are `context: EconomicResolutionContext`, `source_policy: EconomicSourceSelectionPolicyV1`; methods are `decision_query(t: str,k: str,e: str) -> MarketDecisionQueryV1` and `outcome_query(h: str,v: str) -> MarketOutcomeQueryV1`. Both bind actual context/policy hashes, all ActionKind values, PUBLIC and history_start Jan1 2020; E/H must equal policy.through. For synthetic fixtures, coverage end is through plus one ordinary day, not an exchange session calculation. Default snapshot/availability is no earlier than that end and every known included source-version availability upper bound; an explicit earlier incompatible snapshot rejects. Jan1 2021 horizon therefore uses Jan2 snapshot unless later versions require later vintage. Unknown availability limits completeness. Build new immutable snapshots for different inventories; no proof fabrication or frozen-context mutation.

Dataset helper construction follows existing test_listing_semantics.role_dataset behavior without changing/importing its role map: canonical document bytes and SHA-256; fixed_manifest(role) template; replace new source/acquisition/license evidence references with actual economic_evidence artifacts, update schema/contract/partition digest/location/size/count, then real validator and build_validated_dataset_bundle. No fake template references survive into validated M1c context. Construct all fact datasets, including exact empty files, before coverage records referencing them. Coverage methodology uses actual independent bytes describing occurrence-ID/revision semantics. Coverage snapshot/availability must reflect its actual synthetic inventory vintage, not inherited 2018 availability; an inventory containing later source revisions cannot be asserted complete at an earlier source vintage. Historical queries can retain known facts with partial coverage. For the bounded-effect test, construct an explicit small coverage interval ending June2 with snapshot/availability June3, covering the queried June1 E. Default outcome fixtures use Jan2 snapshot/availability for their Jan1 horizon when all included source versions were already reported. Supporting artifacts contain every required unique reference. complete_coverage=False supplies partial assertions, never removes facts. Bundle and context hashes are built only after member decisions exist.

Identity support uses fresh synthetic assigned security `uid(21)` and recipient `uid(22)` through existing `history_assignments`/`assignment_dataset` construction patterns; retain actual assignment bytes and rerun `validate_identity_dataset`. No active listing or universe membership is required. Add `identity_input(assignments: tuple[IdentityAssignmentVersionV1,...]) -> EconomicIdentityInput` with exact bytes/schema/decision/bundle construction. No tests call `passing_decision` for trusted evidence.

- [x] Write this RED and run `uv run pytest tests/unit/test_economic_validation.py -q`:

```python
from economic_test_support import economic_dataset
from drift.domain.dataset_validation import ValidationScope


def test_valid_empty_dataset_is_not_an_event_absence_assertion() -> None:
    dataset = economic_dataset("economic_settlement", ())
    assert dataset.records == ()
    assert dataset.decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert "economic-settlement-v1-exact-empty" in dataset.decision.checked_contracts
    assert dataset.decision.validated_record_hashes == ()
```

- [x] Implement exact-byte validation around the existing primitive:

```python
structure = validate_manifest_v2_structure(manifest, verified_artifacts, run)
if structure.result is ValidationResult.FAIL:
    return structure, ()
records = tuple(
    record
    for artifact in verified_artifacts
    for record in parse_economic_document(artifact.data, manifest.dataset_role.name)
)
record_hashes = tuple(sorted(content_hash(record) for record in records))
if len(set(record_hashes)) != len(record_hashes):
    raise DatasetValidationError.single("duplicate_economic_record_hash")
if len(records) != sum(partition.row_count for partition in manifest.partitions):
    raise DatasetValidationError.single("economic_row_count_mismatch")
```

This kernel is embedded in the typed validator, which returns deterministic findings instead of treating parse exceptions as success. Call structure first and never parse an artifact with failed bytes. Check schema/role/temporal contract equality, source-key source_id agreement with manifest, declared channels, exact record hashes/payloads, complete revision chains and ownership across all parsed rows. Append `economic-{family}-v1` checked marker and an `-exact-empty` marker only after canonical zero-row parsing/count validation; keep MANIFEST_ONLY for empty and RECORDS for nonempty. Never mutate DecisionV2's rules. On failed parsing return FAIL with deterministic findings and no authority; callers reject it.

`validate_economic_context` reruns M1c/identity validators over exact bytes with original validation_run and compares entire decisions/parsed values, verifies exact bundle membership, rejects omitted/extra/duplicate records and conflicting role/source datasets, and calls require_m1c_evidence_closure before returning. For DecisionV2 implementation/profile fields, compare against actual M1c validator spec and byte-implementation hashes, not a passing flag. Preserve M1b validation rules unchanged.

`require_m1c_evidence_closure` enumerates every ArtifactReference reachable from ALL retained new M1c records/coverage, including revision source and availability/temporal evidence, occurrence, date rule, fraction, effect, settlement, residual, unsupported property and methodology references. Also enumerate new M1c manifests' source/acquisition/license references; their partition references are separately closed by verified partition bytes. The unique required support-hash set must exactly equal the supplied supporting_artifacts hash set: no missing, extra or duplicate bytes; recompute SHA-256 and length. A referenced hash that is already a verified partition may be satisfied there only if it introduces no self-reference; normalized records must never cite their containing partition as their own raw source. Use independent raw evidence first, then normalized records/partitions/manifests. Do not recurse into or impose new evidence closure on protected M1b records/manifests. A fabricated source citation cannot pass just because normalized row bytes verify.

- [x] Add RED/GREEN cases: corrupt bytes with a monkeypatched parser that raises AssertionError if called (the parser must not run); wrong role/parser/schema/contract/channels; omitted/extra/duplicate row; invented empty marker; same-role provider in one BundleV1 rejected; separate source bundles accepted; false inventory; omit/substitute/duplicate/add supporting evidence bytes; fake artifact() reference fails real context; coverage self-reference rejected; full supplied set differs from validated hashes rejected. Test effects, availability and fraction references as well as methodology, so closure is not limited to one convenient field.
- [x] Full gate and independent compatibility review. Proposed boundary: `feat: validate exact M1c source datasets and contexts`.

## Task 5: Causal selections, retained identity and strict consumer references

**Files:** Create `src/drift/markets/economic_selection.py`, `tests/unit/test_economic_selection.py`; extend `tests/unit/economic_test_support.py`.

**Interfaces:**

```text
select_market_records(query: MarketSelectionQueryV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> MarketSelectionProofV1
verify_market_selection(proof: MarketSelectionProofV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> None
decision_reference(query: MarketDecisionQueryV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> MarketDecisionReferenceV1
outcome_reference(query: MarketOutcomeQueryV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> MarketOutcomeReferenceV1
resolve_decision_records(reference: MarketDecisionReferenceV1, query: MarketDecisionQueryV1, records_by_hash: Mapping[str, EconomicRecordV1], context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> Mapping[str, EconomicRecordV1]
resolve_outcome_records(reference: MarketOutcomeReferenceV1, query: MarketOutcomeQueryV1, records_by_hash: Mapping[str, EconomicRecordV1], context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> Mapping[str, EconomicRecordV1]
project_market_facts(query: MarketSelectionQueryV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> tuple[EconomicSafeFactProjectionV1,...]
resolve_decision_projections(reference: MarketDecisionReferenceV1, query: MarketDecisionQueryV1, projections_by_hash: Mapping[str, EconomicSafeFactProjectionV1], context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> Mapping[str, EconomicSafeFactProjectionV1]
resolve_outcome_projections(reference: MarketOutcomeReferenceV1, query: MarketOutcomeQueryV1, projections_by_hash: Mapping[str, EconomicSafeFactProjectionV1], context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> Mapping[str, EconomicSafeFactProjectionV1]
```

RetainedEconomicIdentityV1 already has its full Task 1 wire shape. Implement private `select_retained_economic_identity(identity_kind: Literal['security','listing'], identity_id: UUID, query: MarketSelectionQueryV1, context: EconomicResolutionContext) -> RetainedEconomicIdentityV1`, replaying exact assignments each time. This result proves retained identity, not eligibility or listing affiliation. No fields are added to accepted Task 1 models here.

- [x] Write RED using the genuine validated fixture builder:

```python
from economic_test_support import terms_record, validated_case
from drift.markets.economic_selection import decision_reference, select_market_records


def test_may_announcement_is_selected_without_proving_june_occurrence() -> None:
    from drift.serialization.canonical import content_hash

    terms = terms_record(100)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    proof = select_market_records(query, case.context, case.source_policy)
    ref = decision_reference(query, case.context, case.source_policy)
    assert ref.selected_record_hashes == proof.raw_materializable_record_hashes
    assert content_hash(terms) in ref.selected_record_hashes
    assert not hasattr(ref, "considered_record_hashes")
```

This checks causal selection, not occurrence. Task 6 asserts the upcoming/no-delivery outcome explicitly. Run `uv run pytest tests/unit/test_economic_selection.py -q` and confirm RED.

- [x] Implement context and query binding first, then complete-chain selection:

```python
selections = []
for logical_id in sorted(
    {row.revision.logical_record_id for row in dataset.records}, key=str
):
    chain = tuple(
        row for row in dataset.records if row.revision.logical_record_id == logical_id
    )
    projections = tuple(
        AssertionVersionProjectionV1(
            revision=row.revision, record_hash=content_hash(row)
        )
        for row in chain
    )
    selections.append(
        select_assertion_version(
            projections,
            query.requested_channel,
            context.availability_policy,
            market_cutoff(query),
            context.retained_evidence,
        )
    )
```

Preserve every dataset row and full chain in audit proof before filtering selected versions by subject/source authority. No M1b proof builder, closed query, reference cast or old enum extension. Source policy security/window and all bindings match query/context exactly. `MarketDatasetSelectionV1` canonical hashes equal complete validated sets including unrelated-security records. Coverage is selected through the same revision mechanism before completeness interpretation.

Retained identity reuses the causal primitive, not a structural resolver: validate complete assignment dataset first; select complete relevant assignment chains at K/V; a selected ASSIGNED record naming the UUID establishes retained identity even if its association interval has ended. A selected UNASSIGNED record requires a causally selected earlier positive prefix naming the same UUID; each prefix proof is retained. A selected correction naming a different UUID or a withdrawal does not authorize the displaced/future identity. Follow the existing `_retained_target_provenance` behavior as a specification reference but do not import private M1b helpers or alter their implementation. Reject ambiguous competing selected assignment identity claims. Select competing same-kind/source-namespace/source-key claims before target authorization and bind their evidence. Different targets with definite interval overlap are conflicting; uncertain overlap remains fail-closed, while provably disjoint source-key reuse and ended assignments do not erase retained identity. A UNASSIGNED prefix walk must stop at an intervening selected different identity or withdrawal, not skip it to recover an older invalidated positive. These rules do not add a current association/activity gate. No current listing, first trade, classification or universe dependency enters M1c receipt admission.

Do not translate outcome V into M1b CURRENT_INTERPRETATION. At the planning checkpoint `markets/identity.py:2219-2255` selects the latest chain entry in that mode without an availability test. Controller's read-only Jan-initial/Mar-correction/Feb-cutoff probe confirmed AS_KNOWN selects January and CURRENT_INTERPRETATION selects March. This is established old semantics, not an M1b bugfix in scope. The new identity proof uses unchanged `select_assertion_version` at the actual K or V. Add paired pre/post-V identity correction and future initial assignment tests, including ended/UNASSIGNED/withdrawn histories. Optional listing context uses the same retained assignment-kind proof; no old current-mode lifecycle resolver enters M1c.

For every revision-selected, source-authorized economic row, establish predecessor security independently. If it is unavailable, the source claim stays audit-side with a reason, not a consumer projection naming the UUID. Otherwise create one EconomicSafeFactProjectionV1. Check component dependencies separately: cash with a known predecessor/unit basis survives even if another share component's recipient is unavailable. Preserve every safe component's economic/source-semantic fields and evidence content identity, but normalize each nested ArtifactReference.location to `drift+sha256://<content_hash>` in the derived copy; preserve artifact_id, kind and content_hash. Replace each unsafe component with EconomicComponentGapV1 carrying only its source component ID/hash and a stable reason, never its unavailable recipient/basis UUID. Opaque hashes do not grant raw resolution authority.

Task 5 implementation ruling: the original instruction to keep safe components byte-unchanged leaked future data in a valid partial projection. Root and an independent reviewer reproduced a known share's fraction evidence locator embedding the entire raw source statement, including a different withheld recipient UUID. Known unsupported-property evidence has the same structural risk. Opaque content-addressed locators in derived components preserve economic utility and source evidence identity while removing embedded raw-document content. Original source rows/audit evidence remain unchanged; projections retain their own query-bound hash and source_record_hash, and replay binds this normalization rule. Withholding otherwise known components would lose independent economics. The cost is that consumer projections no longer carry navigable original locators; audit retains them, and content hashes are not raw-resolution authority. This is not generic free-text redaction or a promise of arbitrary-process information-flow isolation.

Optional listing_id is source-reported audit context, never authenticated security affiliation/lifecycle. The first raw materialization profile requires listing_id=None; a row with any optional listing context still produces a safe economic projection omitting it with `source_listing_context_omitted`. That omission alone does not make known cash or economic completeness uncertain. No M1b relationship/lifecycle resolver is added for unused listing context. Explicit unresolved_property is retained as source-reported property text when it contains no unavailable UUID; unsupported shape is separate from knowledge.

Raw-materializable hashes include only terms/effect/settlement rows with all nested economic UUIDs causally proved, no optional listing context, and role/time applicability suitable for raw use. Coverage is NEVER raw-materializable or a safe fact projection. Inventory, manifest and methodology hashes remain only in audit proof/results. Safe projections may include known bounded/unknown-time reports with applicability indeterminate: that describes a source report, not an effective delivery. Their known reported components remain distinct from delivery groups applied within E/H.

Primitive selection may retain an earlier definite version under a newer uncertain revision. Preserve it and bind unresolved_chain_hashes separately; audit uncertainty cannot become a complete no-event conclusion. After revision selection, apply the persistent source-time contradiction rule first. For consistent actual claims, applicability uses upper<window_start for before_window, lower>=start and upper<=min(E,K)/min(H,V) for in_window, lower>E/H with actual already evidenced by K/V for upcoming relative to the economic horizon, otherwise indeterminate. Terms use scheduled time descriptively. Actual raw materialization requires a definitely applicable/past boundary plus finite evidence cutoff; safe projections retain indeterminate reports. H>V/E>K leaves uncovered economic time uncertain, never prospective actual occurrence. Completely unavailable later facts do not enter semantic decision projections.

One private selection pipeline returns `(MarketSelectionProofV1, tuple[EconomicSafeFactProjectionV1,...])`; select_market_records and project_market_facts call it and return the respective part. Projections bind query/source/identity dependency hashes, not the outer selection proof, avoiding a cycle. The outer proof binds projection hashes. verify_market_selection rebuilds complete proof/projections from exact context/policy and compares all sets, applicability and dependency evidence. Reference functions rebuild proofs; raw and projection resolvers rebuild the expected reference and verify exact mapping key/value hashes against their respective authorized sets before returning MappingProxyType. No M1b reference cast and no partially redacted model under its original raw hash.

- [x] Add concrete paired projection REDs using `mixed_settlement_case(recipient_known_at: str, listing_id: UUID | None=None) -> EconomicHarness`, defined in new support to build one actual row with USD4 cash plus 1/2 recipient uid(22) shares, known predecessor uid(21), actual settlement 2020-06-15, complete coverage and source evidence, recipient assignment available at the supplied instant. Use through=2021-01-01 and query V=2021-01-02. The optional listing, if supplied, has no assignment and is audit context only:

```python
from economic_test_support import mixed_settlement_case
from drift.domain.economic_common import CashComponentV1
from drift.markets.economic_selection import project_market_facts


def test_mixed_row_preserves_known_cash_without_future_recipient() -> None:
    case = mixed_settlement_case("2021-02-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    projections = project_market_facts(query, case.context, case.source_policy)
    paid = next(item for item in projections if item.family == "settlement")
    cash = paid.known_components[0]
    assert isinstance(cash, CashComponentV1)
    assert cash.amount == "4"
    assert len(paid.withheld_components) == 1
    assert paid.withheld_components[0].reason == "recipient_identity_unavailable"
    assert "019b8240-0000-7000-8000-000000000022" not in paid.model_dump_json()
```

Repeat at V=2021-02-02 to require both components and no gap; with unknown optional listing require unchanged cash and no listing UUID. Add a bounded effect known by June3 spanning June1 E noon: zero effective delivery, an indeterminate applicability/projection, non-known completeness and no false absence. Add a genuine coverage inventory containing another security's hashes and assert coverage cannot enter either raw or projection mapping. An authentic raw row backing a partial projection must still fail raw resolution if its hash was withheld. These tests are required before Task 5 acceptance.

Add source-time REDs: source reports actual June1 with May1 availability, queried in May and again July, must never produce effective/realized authority without a correcting assertion. A valid July correction reporting the actual June1 occurrence may establish it at later V. H June1/V May1 and E June1/K May1 remain partial/unknown, not anticipated actual results. A same-day bounded actual/report pair with overlapping bounds stays valid source evidence and is not globally rejected; query containment may be indeterminate. These cases prevent both scheduled-date-passing inference and overstrict universal chronology.

- [x] Add exact attacks: December settlement at June K; future correction with genuine source validation; wrong policy source/window/hash; changed retained evidence; omitted unrelated chain; forged selected hash with different value; outcome-reference JSON into decision API; borrowed proof at different E/K/T; empty dataset selection valid but no no-events conclusion; unassigned identity with and without prior positive; ended association/terminated listing receipt; future recipient UUID excluded; source correction security A->B gives A only at old K and B only at later V; current_only history does not invent an old K.
- [x] Focused GREEN, full gate, independent temporal and selected-value reviewer. Proposed boundary: `feat: add replayable M1c causal selection and references`.

## Task 6: Association, reporting authority and economic-outcome composition

**Files:** Create `src/drift/domain/economic_results.py`, `src/drift/markets/economic_outcomes.py`, `tests/unit/test_economic_outcomes.py`; extend `tests/unit/economic_test_support.py`.

Task 6 bounded integration repair: add `src/drift/markets/economic_selection.py` and `tests/unit/test_economic_selection.py` to the reviewed repair paths only for shared source-policy model revalidation. A composition attack found that a field-preserving unvalidated policy object could bypass one-owner constraints; controller variant probes showed the same object still authorized public selection/projection even after a composition-only guard. Repair the common M1c boundary without changing wire schemas or any M0/M1a/M1b contract. Exact hash binding alone does not establish model validity. Standard tests must cover the direct entry points as well as composition.

**Interfaces and result models:**

```text
resolve_economic_facts(query: MarketSelectionQueryV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> EconomicOutcomeResolutionV1
verify_economic_outcome(result: EconomicOutcomeResolutionV1, context: EconomicResolutionContext, source_policy: EconomicSourceSelectionPolicyV1) -> None
settlement_occurrence_payload_v1(record: EconomicSettlementVersionV1) -> SettlementEconomicPayloadV1
```

`EconomicAssociationResolutionV1`: `source_record_hash`, `association_field: Literal['terms','effect']`, `status: Literal['resolved','unresolved','conflicting']`, `selected_target_hash: SHA256Hash | None`, `reasons`. Resolved requires exactly one selected target of the specified source key/family with compatible security/occurrence and optional asserted-version match. Native hints and missing/withdrawn/future targets are unresolved. A definite mismatch is conflicting; never fabricate a parent. Query-neutral source association status is not copied as resolved authority.

Task 6 association clarification: parent action/effect occurrence IDs and settlement installment IDs may differ. Compatibility does not require string equality across these distinct identities or universal effect-before-payment chronology. Resolve exact source keys against causally selected target evidence admitted by source authority; definite family/security/asserted-version mismatch is conflicting, while missing/withdrawn/future/non-admitted targets remain unresolved. A resolved reported link alone grants no occurrence, delivery, economic equality or completeness inference. Separate applicability, occurrence comparison and residual-closure chronology retain those responsibilities. This follows the three-family/installment design and avoids inventing source-event equivalence or date rules.

Task 6 review refinement: future means causally unavailable evidence or a non-applicable actual-effect target, not merely a known terms record with a future scheduled date. Owner/class/security-admitted known terms can remain exact link metadata before that date, including accelerated/prepaid settlement; their schedule is not occurrence authority. Actual-effect targets outside or indeterminate for the query must not authorize association/action-state use. Apply the same admission in residual scope normalization and effect fallback, and never bypass a conflicting terms dependency by inventing an effect-key action anchor. Both reviewers accepted this family-local distinction after the controller challenged blanket scheduled-date rejection.

Claim chronology must check all opposing boundary pairs, including exact ties and nested nonadjacent overlaps, before selecting a final state. A relevant unresolved later installment can prevent derived closure without being assigned a fabricated parent or dropping its delivery. Positively distinct actions and definitely out-of-horizon reports must not poison another action scope. These corrections are supported by controller-reproduced false terminal and false closure results; they do not add quantity arithmetic, source-event equivalence or an accounting layer.

`EconomicDeliveryGroupV1`: `source_id`, `security_id`, `native_occurrence_id`, `settled_time`, `delivered_components` (safe known components only), `component_gaps: tuple[EconomicComponentGapV1,...]`, `residual_status`, `contributing_record_hashes` (all corroborating revision-selected reports), `projection_hashes`, `association_result_hashes`. No amount sum or portfolio quantity. Compose using audit-selected applicable reports and their safe projections, not raw-materializable hashes. A mixed row can yield known cash and a component gap even when its raw row is withheld. `EconomicEffectProjectionV1`: `source_record_hash`, `effective_status: Literal['before_window','effective','upcoming','indeterminate']`, `claim_status`, `consideration_status`, `owed_components` (safe only), `component_gaps`, `safe_fact_projection_hash: SHA256Hash`. Cancelled/unknown payload has separate cancelled_action_hashes/unknown_effect_hashes, never an invented claim change. The effect dependency must equal content_hash of the unique EconomicSafeFactProjectionV1 with the same source_record_hash, query and effect family; the effect projection itself has no stored self hash. Delivery-group projection_hashes likewise equal the sorted unique content_hash values of the contributing settlement safe projections for that same query. Reject missing, extra, wrong-family or wrong-query dependencies.

`EconomicCoverageResolutionV1`: `family`, `source_id`, `selected_coverage_hashes`, `target_manifest_hash`, `status: Literal['complete','partial','unknown']`, `occurrence_identity_supported: bool`, `reasons`. Bool is replay-derived, not caller authority. Completeness checks exact requested action-class set, window, inventory, revision support, gaps and source/manifest bindings; only complete selected coverage with verified methodology can prove no relevant rows.

`ActionResidualResolutionV1`: `action_scope: EconomicSourceKeyV1`, `selected_action_record_hash`, `status: Literal['closed','outstanding','unknown','conflicting']`, `covered_settlement_hashes`, `closure_record_hashes`, `reasons`. It is a derived fold, not another source fact.

`EconomicOutcomeResolutionV1`: `schema_version='1'`, `query`, `query_hash`, `selection_proof_hash`, `source_selection_policy_hash`, `input_context_hash`, `composition_algorithm='drift-m1c-economic-composition-v1'`, `composition_algorithm_spec_hash`, `composition_implementation_hash`, `selected_terms_hashes`, `upcoming_terms_hashes`, `effect_projections`, `cancelled_action_hashes`, `unknown_effect_hashes`, `delivery_groups`, `uncomposed_settlement_hashes`, `associations`, `coverage_results`, `residual_resolutions: tuple[ActionResidualResolutionV1,...]`, `safe_projection_hashes`, `claim_status: Literal['continuing','converted','extinguished','unknown']`, `evidence_completeness: Literal['known','partial','unknown']`, `support_status: Literal['supported','unsupported','indeterminate']`, `reasons`. No stored result_hash: identity is content_hash(result). This full result is audit-side and may contain coverage/replay inventories via references; it is NEVER a decision-consumer materialization. Consumer APIs authorize only the safe fact projections and permitted raw economic records through their matching role reference. No outcome result is cast into a decision capability.

- [x] Extend fixture builder with `duplicate_report(record: EconomicSettlementVersionV1, suffix: int) -> EconomicSettlementVersionV1`, which creates distinct report/logical/source-artifact/availability/report/residual evidence, source component IDs/text/precision, while retaining one evidenced occurrence and equal economic comparison payload. `second_installment(record: EconomicSettlementVersionV1, suffix: int, occurrence_id: str) -> EconomicSettlementVersionV1` creates a distinct evidenced occurrence. Both use real support bytes and seal_record. An alternate provider remains separately bound; selecting A cannot turn B into a receipt.

- [x] Write paired RED and run `uv run pytest tests/unit/test_economic_outcomes.py -q`:

```python
from economic_test_support import (
    settlement_record,
    duplicate_report,
    second_installment,
    validated_case,
)
from drift.markets.economic_outcomes import resolve_economic_facts


def test_duplicate_report_is_one_delivery_but_two_installments_are_two() -> None:
    first = settlement_record(300)
    duplicate = duplicate_report(first, 301)
    second = second_installment(first, 302, "payment-2")
    case = validated_case((first, duplicate, second))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert len(result.delivery_groups) == 2
    assert sorted(
        len(group.contributing_record_hashes) for group in result.delivery_groups
    ) == [1, 2]
    from drift.domain.economic_common import CashComponentV1

    amounts = []
    for group in result.delivery_groups:
        component = group.delivered_components[0]
        assert isinstance(component, CashComponentV1)
        amounts.append(component.amount)
    assert amounts == ["5", "5"]
    assert result.evidence_completeness == "partial"
```

Unknown parents/residual remain partial despite known payments. No assertion of numeric ten is needed; preserving two sourced occurrences is the contract.

- [x] Implement composition in this required order: validate/rebuild complete context and selection; select policy owners; resolve selected coverage; filter selected attribution and relevant economic window; resolve associations; establish occurrence identity from selected source methodology; group corroborating reports; derive claim state independently; derive completeness/support; hash exact result. The kernel must not use dates/amounts as keys:

```python
groups: dict[tuple[str, UUID, str], list[EconomicSettlementVersionV1]] = {}
uncomposed: list[str] = []
for record in authorized_settlements:
    occurrence_id = record.occurrence.native_occurrence_id
    if (
        record.occurrence.kind != "identified"
        or occurrence_id is None
        or not occurrence_identity_supported
    ):
        uncomposed.append(content_hash(record))
        continue
    key = (record.source_key.source_id, record.security_id, occurrence_id)
    groups.setdefault(key, []).append(record)
```

Define SettlementEconomicPayloadV1 in `src/drift/domain/economic_results.py`: `schema_version='1'`, `settled_boundary: EconomicBoundaryValueV1`, `components: tuple[EconomicComparisonComponentV1,...]`, `residual: EconomicResidualValueV1`. These comparison models are audit-only and never appear in consumer projections. EconomicBoundaryValueV1 has `shape: BoundaryShape`, `lower_bound: UTCDateTime | None`, `upper_bound: UTCDateTime | None`; omit source precision labels/timezone text/evidence once normalized bounds are retained. Unknown bounds remain unknown, not equal to a guessed instant.

EconomicComparisonComponentV1 is the discriminated union of the following exact frozen models. The projection does not reuse source component objects and accidentally carry report metadata:

| Comparison variant | Included fields |
|---|---|
| CashEconomicValueV1 | kind='cash', amount:CanonicalCash, currency_namespace, currency_code, unit_basis:EconomicUnitBasisV1, amount_basis, applicability, conditions:tuple[NonBlankStr,...] |
| ShareEconomicValueV1 | kind='shares', recipient:EconomicRecipientValueV1, ratio:PositiveRatioV1, ratio_meaning, unit_basis:EconomicShareBasisV1, fraction:FractionEconomicValueV1, applicability, conditions |
| PropertyEconomicValueV1 | kind='unsupported_property', recipient:EconomicRecipientValueV1, source_description:NonBlankStr |

EconomicRecipientValueV1 has kind, security_id or source_property_key using the same mutually exclusive source recipient shape, but excludes explanatory reason. FractionEconomicValueV1 has the same closed fraction kind plus source_rule; excludes evidence_reference. EconomicResidualValueV1 has kind, scope_occurrence_id, scope_action: EconomicAssociationValueV1|None. EconomicAssociationValueV1 has kind, target:EconomicSourceKeyV1|None, asserted_target_version_hash|None, native_hint|None; excludes explanatory reason. Every field's type/literal matches its source counterpart. The action scope participates in equality; evidence references do not. Canonicalize conditions as sorted unique conjunction strings. Source component ID, source amount text/precision, explanatory reasons, source/native report IDs, revision metadata, all source/evidence artifacts and component order are excluded from economic equality, but retained in contributing source lineage.

Components form a canonical MULTISET: sort comparison values by canonical_json bytes, preserve repeated equal values, and never use a set/dictionary that loses multiplicity. Two equal cash components differ from one. Compare payloads only after positive same-occurrence ownership, never as a matcher across unrelated IDs. Equal economics coalesce despite component IDs, precision and provenance differences. Different units, gross/net, currency, recipient, ratio meaning, conditions, fraction semantics, time bounds, residual scope or multiplicity conflicts. Identical unknowns may corroborate an incomplete report; unknown-vs-known or differing partial values conservatively conflict. For equal payload groups, choose the lexicographically smallest source-record hash as a deterministic display representative for known components/gaps; bind every contributing report and projection hash. This is formatting among proven-equal economics, not a priority rule resolving conflict. Preserve the representative's component multiplicity. Support classification does not change equality.

Implement the multiset kernel in settlement_occurrence_payload_v1:

```python
if record.payload is None:
    raise ValueError("withdrawn report has no economic comparison payload")
projected = tuple(
    component_economic_value_v1(item) for item in record.payload.delivered_components
)
components = tuple(sorted(projected, key=canonical_json))
return SettlementEconomicPayloadV1(
    schema_version="1",
    settled_boundary=boundary_economic_value_v1(record.settled_time),
    components=components,
    residual=residual_economic_value_v1(record.payload.residual),
)
```

Private helper signatures in `src/drift/markets/economic_outcomes.py` are `component_economic_value_v1(component: EconomicComponentV1) -> EconomicComparisonComponentV1`, `boundary_economic_value_v1(boundary: TemporalBoundaryClaimV1) -> EconomicBoundaryValueV1`, and `residual_economic_value_v1(residual: ResidualClaimV1) -> EconomicResidualValueV1`. They copy exactly the included fields above. The literal comparison spec dictionary enumerates these included/excluded fields and multiset rule; bind its content_hash as composition_algorithm_spec_hash alongside the separate actual code-byte implementation hash. Terms/owed/delivered are never unioned into receipts.

Claim state is sourced effect state, not listing status or latest settlement. For one security, select definitely effective occurred-effect assertions and fold unambiguously ordered claim assertions. A continuing assertion after converted/extinguished cannot resurrect that predecessor: report conflict/unsupported unless causal revision selection withdrew/corrected the earlier terminal assertion. Opposing ties, overlapping time bounds, unknown claim effects and unsupported ownership leave claim status unknown with reasons. Do not sort competing effects by UUID or per-chain revision sequence. Cancellation of proposed action does not override a separately known claim state. An explicit_none effect applies only to that occurrence: earlier delivered installments remain in result. Claim extinguishment without explicit no-consideration or resolved owed/delivered facts is not a known zero.

Residual closure fold: resolve each settlement's terms association directly, or through its resolved effect's terms association, to one causal selected action key. If terms is absent, a resolved occurred-effect key may anchor scope; conflicting direct/indirect keys stay conflicting. A closed_for_action effect/settlement must identify that same canonical action scope, be definitely effective/settled by E/H and not precede covered installments (each installment upper bound <= closure lower bound). Its explicit no-further-consideration evidence closes earlier outstanding/unknown residuals for all unambiguously linked settlements of that action, without changing their reported residual values or removing deliveries. Unknown or conflicting scope, overlapping chronology, a later outstanding assertion, or an unresolved later installment prevents closure. A later correction of the closure is selected before folding. Closed_for_occurrence closes only that payment occurrence; it cannot close other installments. The final ActionResidualResolutionV1 records exact action/closure/covered-settlement hashes and closure state. Claim extinction still comes independently from occurred-effect claim evidence. No lifetime zero follows from a no-further-consideration statement.

Coverage is one authority per family. Selected coverage must consistently contain the whole requested interval/classes with verified inventories; conflicting overlap is indeterminate. Evidence completeness and consumer support are computed INDEPENDENTLY. Known completeness requires required source families covered, unambiguous applicable report/effect/association/occurrence facts, no unresolved economic component/time/revision gaps, and relevant residuals closed or explicitly not outstanding through the queried scope. No condition requires the action shape to be supported for evaluation. A fully reported CVR/property delivery can be evidence known and support unsupported. Optional listing context omission alone is not an economic evidence gap. Known fragments plus a genuine evidence gap produce partial; no relevant usable facts with uncertain coverage produce unknown. Valid empty complete histories establish no reported events only in exact scope, never lifetime worthlessness.

Use support_status unsupported when the known action/property requires deliberately unimplemented evaluation semantics; use indeterminate when a support-critical classification is uncertain. Fully known unsupported property need not have a valuation in this facts layer. Never turn unavailable valuation into zero or automatically lower complete source evidence. verify_economic_outcome rebuilds the full audit result from result.query and actual context/policy, comparing all fields and external content_hash identity, not a claimed self hash.

- [x] Add `closed_liquidation_case(wrong_scope: bool=False) -> EconomicHarness` and `known_unsupported_case() -> EconomicHarness` to new support. The first contains one selected terms/action, an initial continuing effect, a USD5 delivered installment with outstanding residual, then a later occurred extinguishment with explicit_none and closed_for_action evidence naming the same causally resolved action; all associations, coverage and supporting bytes are exact. wrong_scope names another real action, so the USD5 residual remains partial. The second has fully reported unsupported CVR terms, effect and actual property delivery with retained recipient identity, exact scope closure and complete coverage; no required source fact is unknown. Run these concrete REDs before fixing the fold:

```python
from economic_test_support import closed_liquidation_case, known_unsupported_case
from drift.domain.economic_common import CashComponentV1
from drift.markets.economic_outcomes import resolve_economic_facts


def test_later_action_closure_preserves_prior_payment_and_completes_evidence() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.claim_status == "extinguished"
    assert result.evidence_completeness == "known"
    assert len(result.delivery_groups) == 1
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"
    assert all(item.status == "closed" for item in result.residual_resolutions)


def test_known_unsupported_property_is_not_missing_evidence() -> None:
    case = known_unsupported_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert (result.evidence_completeness, result.support_status) == (
        "known",
        "unsupported",
    )
```

Paired negatives require wrong action scope, unknown/after-H closure, contradictory later outstanding claim and incomplete coverage to remain partial/unknown while preserving USD5. A no-consideration effect without prior payments yields no fabricated zero delivery; prior USD5 plus closure never becomes lifetime zero. Mixed row with unknown recipient retains USD4 in one group with component gap and partial evidence, with no unavailable UUID in safe projection. Optional listing uncertainty alone leaves known cash intact.

- [x] Add exact duplicate-comparison REDs: same occurrence with distinct report/evidence artifacts, component IDs `cash-a`/`payment`, source text `5.00`/`5`, precision 2/0 and condition order changes coalesces once; changing gross to net, pre-action to post-action units, ratio/recipient/fraction/time/residual action scope or component multiplicity conflicts and never sums. The implementation-spec test pins every included/excluded field, not just two copied payloads. Add occurrence reassignment R(v1)->payment1, S->payment1, R(v2)->payment2: old V groups one payment with Rv1/S, later V groups two with Rv2/S and never retains both R versions.

The occurrence-correction test has three arms: old immutable context/coverage at old V yields one group; new immutable context/coverage at new V yields two groups; new full-chain context queried at old V selects Rv1/S and the same safe old component values but cannot claim historical complete composition from later inventory coverage. It returns explicit coverage uncertainty/uncomposed reports. This tests causal selection and honest source-snapshot limits independently, not a weakened duplicate assertion.

- [x] Add attacks: missing terms but known $4 actual payment; conflicting terms target does not erase the source payment; partial residual; second genuine equal-date/equal-amount installment; correction 5->4 leaves one corrected group; duplicate source report same payout; unknown occurrence identity no grouping; equal amount/date with proven distinct IDs stays two; corrected security A->B never counts twice; overlapping owner/date partitions rejected; complete splits coverage cannot prove no settlement; no-consideration cancellation with and without earlier installment; delisting plus continuing claim; unknown bankruptcy; future correction injected via forged dependent result; old outcome used under changed policy/context; extra audit hashes leaked to reference rejected.
- [x] GREEN, full gate, independent duplicate/completeness and temporal review. Proposed boundary: `feat: compose M1c economic outcomes without duplicate receipts`.

## Task 7: Fixed-action integration and immutable adversarial histories

**Files:** Create `tests/integration/test_m1c_economic_history.py` and `tests/fixtures/m1c/v1/liquidation/`; extend `tests/unit/economic_test_support.py` if required. Shape semantics were implemented in Task 2; Task 7 adds integration coverage, not the first classifier. No existing fixture file changes.

**Interfaces:** Consumes Task 2 classify_economic_shape and Task 6 composition. New `load_m1c_history(root: Path) -> EconomicHarness` lives in `tests/integration/test_m1c_economic_history.py`; it reads exact source/manifests/support bytes through verified resolver and real validators, binding actual policy. It never regenerates expected hashes on load. Task 6 must already have focused supported/unsupported/indeterminate tests passing before its accepted boundary.

Action shape rules: forward/reverse split uses one same-security resulting ratio respectively >1/<1; stock dividend uses same-security additional ratio; cash dividend/distribution has cash components; cash acquisition has only cash and occurred conversion/extinguishment; stock acquisition has successor resulting shares plus evidenced fractional cash where present; mixed has cash+successor shares; spinoff additional recipient shares with continuing predecessor; conversion successor resulting shares with converted/extinguished predecessor; liquidation installments use actual cash/share facts; no-consideration cancellation is occurred extinguishment plus explicit_none. Holder-conditioned applicability, elections, proration, collars and formulas cannot validate as ordinary fixed shape; disclosed transaction closing conditions alone do not change an otherwise fixed terms vector. Unknown relevant fields classify indeterminate rather than delete source records. No thresholds derived from prices, no ex-date/session calculation.

- [ ] Build versioned liquidation fixture documents `terms.json`, `effects.json`, `settlements-a.json`, `settlements-b.json`, `coverage-a.json`, `coverage-b.json`, `methodology-a.json`, `methodology-b.json`, plus `manifests.json`, `policy.json` and `expected-hashes.json` under `tests/fixtures/m1c/v1/liquidation/`. The expected hashes file pins exact document/manifests/policy digests independently; it is not an input whose own hash participates recursively. Source versions and corrected records coexist. Later corrections add a new fixture version directory, never rewrite v1 after accepted commit. Initially author files via apply_patch, compute hashes and review once before first acceptance. Other matrix cases use isolated in-memory validated contexts; each hypothetical history has separate security/occurrence ownership. Do not place unrelated mergers, conversions and later continuing claims on one security to satisfy the matrix.

Fixture facts use dates in 2020 and fixed IDs beginning at uid(9000), distinct from existing test helper records. Include each row of the following matrix as a named test. For acceptance references, no mocked `passing_decision` or forged successful result is permitted.

| Case/test name suffix | Required assertion |
|---|---|
| `may_announcement_june_split` | Known terms/upcoming, zero effect/delivery |
| `announced_then_cancelled` | Action cancelled, no claim extinction |
| `forward_reverse_and_fractions` | Exact 2/1 and 1/10 ratio, source round-up retained |
| `regular_and_special_due_bill` | Ex/record/payable independent; payment-before-ex accepted |
| `late_bounded_dates` | Bounded boundary around E stays indeterminate |
| `same_security_stock_dividend` | Additional ratio with same recipient supported |
| `cash_agreement_without_completion` | Promise never delivery |
| `completed_cash_stock_mixed` | Correct fixed components and effect/delivery separation |
| `elective_prorated_formula` | Detected unsupported, no fixed consideration fabrication |
| `spinoff_and_excluded_property` | Parent persists; REIT/right receipt does not widen eligibility |
| `fixed_conversion` | Resulting ratio and predecessor conversion preserved |
| `delisted_claim_continues` | M1b terminated context independent of continuing claim |
| `zero_vs_unknown_cancellation` | Explicit_none differs from unknown bankruptcy |
| `liquidation_installments_and_residual` | Distinct payments, residual uncertainty retained |
| `corrected_installment` | One occurrence, selected corrected amount only |
| `duplicate_report` | One delivery, both corroborating report hashes |
| `equal_date_equal_amount_distinct` | Two positively evidenced occurrences remain two |
| `missing_terms_known_payment` | Known payment survives, completeness partial |
| `conflicting_association` | No invented parent, conflict blocks dependent completeness |
| `security_attribution_corrected` | Old K names A; later V names B; no simultaneous duplicate |
| `coverage_missing_or_wrong_class` | No-event claim withheld |
| `selected_value_substitution` | Genuine selected hash cannot carry another payload |
| `forged_dependent_outcome` | Full replay rejects altered components/status |
| `outcome_into_decision` | Outcome reference cannot satisfy historical decision |
| `later_decision_uses_known_realization` | Fresh later decision query may select past payment |
| `earlier_effective_cutoff` | July K/T and May E do not admit June effect |
| `prior_payment_then_no_further_consideration` | Earlier delivery retained, zero not applied to lifetime proceeds |

- [ ] Write one end-to-end RED with a real fixture and exact expected lineage:

```python
from pathlib import Path
from drift.markets.economic_outcomes import (
    resolve_economic_facts,
    verify_economic_outcome,
)


def test_m1c_fixture_preserves_installment_lineage() -> None:
    root = Path(__file__).parents[1] / "fixtures" / "m1c" / "v1" / "liquidation"
    case = load_m1c_history(root)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    verify_economic_outcome(result, case.context, case.source_policy)
    occurrence_ids = {group.native_occurrence_id for group in result.delivery_groups}
    assert {"liquidation-1", "liquidation-2"}.issubset(occurrence_ids)
    assert "corroborating-report-only" not in occurrence_ids
```

The fixture includes those two exact liquidation IDs and alternate native report key corroborating-report-only sharing the first occurrence. Run `uv run pytest tests/integration/test_m1c_economic_history.py -q`, confirm the required behavioral RED, then complete the typed fixture loader and integration assertions against the existing Task 2 classifier. If integration reveals a classifier bug, fix/review that concrete defect with its focused test, not an undefined new classification layer. Hand-specify expected economic records and independently pin bytes; do not mirror implementation logic.

- [ ] Full gate, immutable fixture hash review, and fresh adversarial reviewer covering all matrix rows. Proposed boundary: `test: prove M1c economic histories and adversarial boundaries`.

## Task 8: Compatibility acceptance and canonical completion

**Files:** New tests only if a discovered regression needs a focused assertion. Minimal edits to this plan, `docs/architecture/roadmap.md`, `docs/architecture/overview.md`, `README.md`, `AGENTS.md`, ADR 0009 status and the accepted specification's lifecycle status only. Preserve historical design review/evidence, old plans and prior handoff. No executable M1d plan.

- [ ] Reconcile actual HEAD and every accepted slice/review with this plan. Leave unresolved slices unchecked; mark completion only with evidence. Read current canonical documents before editing status.
- [ ] Run the full gate and baseline compatibility tests through their existing entry points:

```bash
uv run pytest tests/unit/test_assertions.py tests/unit/test_dataset_validation_v2.py tests/unit/test_listing_semantics.py tests/unit/test_security_identity.py tests/unit/test_universes.py -q
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
git diff --check
```

- [ ] Inspect protected-path and forbidden-capability diff evidence. The command below intentionally uses the fixed design checkpoint to protect all prior runtime/test files; also compare the verified implementation-start revision for attribution of newly added files. Neither baseline authorizes overwriting concurrent user work:

```bash
git diff --name-status ba1ea66205fda1d649a2bd1034e0c8788c33664d -- src tests pyproject.toml uv.lock
git status --short --untracked-files=all
rg -n 'requests|httpx|urllib|socket|openai|langgraph|robinhood|alpaca|broker|backtest|portfolio|OHLCV|TradeBar|market.calendar|normalize.*bar|Sharpe' src/drift/domain/economic_common.py src/drift/domain/economic_queries.py src/drift/domain/economic_events.py src/drift/domain/economic_coverage.py src/drift/domain/economic_results.py src/drift/markets/economic_validation.py src/drift/markets/economic_selection.py src/drift/markets/economic_outcomes.py
rg -n '\x{2014}' docs/superpowers/plans/2026-09-05-m1c-corporate-actions-economic-outcomes.md docs/architecture/roadmap.md docs/architecture/overview.md README.md AGENTS.md
rg -n 'M1c|M1d|unplanned|unimplemented|executable' AGENTS.md README.md docs/architecture/roadmap.md docs/architecture/overview.md docs/adr/0009* docs/superpowers/plans docs/superpowers/specs
```

No match is automatic guilt; inspect every forbidden-capability match by behavior. Protected source and old fixture/test files must have no modifications; all additions must belong to the module map. The U+2014 command uses its code-point escape so the artifact does not contain that character. Check `.DS_Store` and the historical M1b handoff against preflight hashes/stat without modifying them. A dirty unrelated worktree is reported, not cleaned or falsely called clean.

- [ ] Get independent final acceptance covering temporal roles, duplicate/missing settlements, exact replay and M1d scope. No unresolved Important/Critical issue may be represented as complete. Re-run only affected tests and the full gate after material corrections.
- [ ] Update canonical status to M1c complete, M1d designed/unplanned/unimplemented, with actual verification counts and accepted commit/review evidence. Preserve the fact that this plan's original authoring was planning-only. Do not claim evaluator/backtest readiness. Proposed documentation boundary: `docs: complete M1c economic fact milestone`.
- [ ] If separately authorized, commit only reviewed named paths and run Checkpoint. A commit's own hash belongs in the final report, not self-referentially in that commit. Do not create a new Session Handoff when execution completes cleanly.

## Planning decisions, disagreement record and deferred matters

M1c remains one coherent milestone because all slices answer sourced economics/selection questions without observations, calendars or valuation. Simple spinoff/conversion support uses the same fixed share components and retained recipient identity needed by stock mergers; no new accounting machinery is required. The first implementation declines general election/formula/reorganization processing and preserves typed unsupported facts.

One bounded narrowing of ADR 0009 is deliberate: V1 source policy permits one source per fact-kind/security over the whole query scope, declining within-pair partitions. Strongest support for partitions is useful composed-source coverage. Strongest contrary evidence is corrected dates and unknown occurrence association can assign one payout twice, while BundleV1 already requires source separation. The smallest safe alternative is no within-pair partitions, with synthetic rejection of date-based partition/source-switch attempts. Broader proven partitions require a later version, not an implicit fallback.

V1 also requires exact snapshot inventories. Flexible historical subset witnesses could enable complete old-V composition from a modern full-chain artifact, but would require new witness/coverage semantics beyond the current exact-byte contract. The smaller choice is separate retained old/new snapshots for complete composition, plus demonstrably correct old-V selection with explicit incomplete composition when only a newer snapshot is available. This is a documented conservative limitation, not a human decision blocker or a reason to invent early availability for future inventory.

Source report identity is stable; both security and economic occurrence attribution are correctable semantic claims. The initial draft also froze established occurrence attribution for simpler grouping, but independent review supplied a concrete counterexample: a corrected report can move from corroborating installment1 to identifying installment2. Existing validate_assertion_chain freezes causal report identity, not payload attribution. Therefore full-chain K/V selection precedes security/class/time/occurrence grouping; old V retains old attribution and later V sees only its corrected version. No source key is renamed, no old bytes are edited and no payment is minted merely because a correction exists.

No additional persisted entitlement family is necessary: sourced owed property belongs to EconomicEffectVersionV1. Terms are not owed/delivered facts; settlement reports are not automatically distinct payouts. All source association resolution is query-bound; missing parent facts remain missing. Neither listing termination nor no-consideration for one occurrence proves lifetime proceeds zero.

No provider, historical start-year/calendar corpus, license choice or environment packaging question blocks these synthetic contracts. Later acquisition/experiment gates remain deferred. No executable M1d plan, broker/provider choice or evaluator design is produced by this plan. No unresolved fundamental planning choice is intentionally delegated to the implementer; a discovered contradiction with protected contracts requires stopping and surfacing the smallest alternative.

## Completion criteria and planned commit sequence

Completion requires eight independently reviewed slices, all required synthetic cases, full exact-source and dependent replay, source/occurrence deduplication without arithmetic, protected baseline compatibility, no forbidden runtime, immutable new fixture versions, canonical lifecycle pointers and verified final checkpoint. Planned boundaries are the eight task messages above. They are not present-tense claims or authorization to commit during planning.

Planning review was performed by three independent reviewers who did not author this plan: temporal/least privilege, economic composition, and compatibility/scope. Each re-reviewed the corrected plan and returned Approved, with no unresolved Important or Critical finding. The controller checked material findings against the actual repository, the explicit counterexamples, and revised interfaces; consensus alone was not acceptance evidence.

## Planning review and verified checkpoint

This section records completed planning work, not implementation progress.

| Finding group | Accepted correction |
|---|---|
| Finite outcome vintage versus M1b current interpretation | Measured the old latest-revision behavior; use additive K/V selection without changing M1b |
| Audit inventory leakage and bounded-event disappearance | Distinct revision-selected, applicability and materialization sets; coverage audit-only |
| Mixed known cash and unresolved recipient/listing | Independently hashed safe component projections and explicit gaps, never redacted raw rows under old hashes |
| Occurrence attribution and duplicate reports | Stable report identity, corrected occurrence attribution, exact semantic multiset comparison and distinct supporting evidence |
| Prior installments followed by final closure | Causally scoped action residual fold preserves delivered amounts; no lifetime-zero inference |
| Complete but unsupported facts | Evidence completeness and consumer support computed independently |
| Byte evidence, persisted types and hashes | Exact new-reference closure, fail-before-parse, typed snapshot instants, external content hashes and explicit projection dependency hashes |
| Executable task dependencies and examples | Complete wire types before use, classifier before composition, exact paths and narrowed Python examples |

Three source/composition choices remain intentionally conservative: no same-family/security source partitions in V1; no historical subset-inventory witnesses; no lifting source-time contradictions merely as the clock advances. Their alternatives and evidence are stated above. These restrictions do not require a provider choice, a fourth economic family, M1d, a new dependency, or a prior persisted-contract change.

Final checks on 2026-09-05: `uv run pytest` passed all 793 existing tests; `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, and `uv build` passed. The format gate initially found unformatted Python code fences in this plan; only this documentation file was formatted, then the gate passed. The proposed M1c tests were not implemented or run. No runtime/source/test/fixture/dependency/lockfile changes were made during planning.

Documentation checks passed: eight task sections, all 41 implementation steps unchecked, exactly one active M1c plan, no executable M1d plan, prior plans explicitly completed/superseded, current lifecycle pointers consistent, local Markdown links valid, no unresolved placeholders, no U+2014, and a clean whitespace diff. Protected-path comparison against the design checkpoint is empty.

Checkpoint preserves this plan and the minimal canonical lifecycle/refinement updates. All unrelated `.DS_Store` files and the historical M1b handoff remain excluded and matched their starting hashes. No new Session Handoff is needed because the continuation boundary is canonical: implementation is unstarted, Task 1 is next only after authorization, and M1d remains unplanned. The actual planning commit hash and final Git status are reported from Git rather than embedded self-referentially here. Stop after the planning commit/checkpoint; do not offer or begin execution within this planning-only request.

## M1c execution record

Implementation authorization supersedes the planning-only stop above. Start: `main` at `8bc8bbed3abe0ce977445184e4aa495a6a89dd03`, with 793 tests and the full repository gate passing. Task-level evidence and accepted commit/checkpoint summaries are appended here as work earns acceptance. Detailed transient briefs and reports use the established plan-scoped Superpowers scratch workflow, never Drift's scientific ledger. No M1d, external integration, dependency or prior persisted-contract change is authorized.

### Task 1 acceptance

Terra implemented exact primitives and complete query/proof/projection wire contracts; a fresh Sol reviewer required one fix round and then approved spec compliance and code quality. Controller probes confirmed and fixes closed false cancelled-action claim authority, rejection of valid outstanding settlements, symlink omission in the byte fingerprint, and missing boundary/mutation tests. The strict projection matrix above is the source-family authority ruling. Whole-package fingerprinting remains conservative and separate from semantic hashes; disposable package tests prove byte churn and link rejection without modifying protected source.

RED evidence includes six semantic failures before initial validators, then four regression failures before the review repairs. Focused GREEN: 38 tests. Controller full gate: 831 tests passed, Ruff lint/format passed, mypy passed across 72 source files, build passed, and whitespace check passed. Existing source/test/fixture/dependency files and unrelated-file hashes are unchanged. Accepted commit subject: `feat: add exact M1c economic primitives and queries`; resolve its hash from Git. Task 2 must expand the temporary cash_component helper to its already specified signature rather than treat the Task 1 test helper as a new contract.

### Task 2 acceptance

Sol implemented immutable terms, actual effects/cancellations and delivered settlements, residual claim shapes, source-report ownership and family-local action classification. A fresh Sol reviewer required two repair rounds and then approved spec compliance and quality with no open findings. Controller probes verified the classifier defects; the final fixture serializer now traverses all non-reference semantic fields with explicit evidence-presence markers, excluding evidence identities and the payload self-hash from its acyclic source statement. Currency, bases, source precision/text, fraction rules, recipient explanations and optional evidence presence cannot silently retain the same source body.

The original initial RED was a missing-module collection failure only, not proof of each later semantic assertion. This limitation is retained honestly. Review repairs produced genuine behavioral RED/GREEN for partial settlement legs, effect-state precedence and source-body fidelity, including a currency-namespace mutation that failed because its digest did not change. Focused GREEN: 34 tests. Controller full gate on the final worker-DONE snapshot: 865 tests passed (8.47s), Ruff lint/format passed, mypy passed across 74 source files, build and whitespace checks passed. All pre-M1c files/dependencies remain unchanged, and unrelated-file hashes match preflight. Intended accepted subject: `feat: add immutable M1c terms effects and settlements`.

Coverage proof, full cutoff selection and occurrence composition are not claimed complete by this record-model slice. Task 2 validates correction ownership and constructs corrected attribution; the full old/later cutoff grouping proof remains the explicitly planned Task 6 three-arm case. Task 3 is next after commit/Checkpoint; M1d remains unauthorized.

### Task 3 acceptance

Terra implemented the closed coverage/policy models and exact scoped helpers; a fresh Sol reviewer required one repair round and then approved spec compliance and quality with no open findings. Controller review corrected draft tests that confused source declarations with derived historical authority. Independent review found owner/input inconsistency and cross-channel snapshot chronology, while a controller probe reproduced incomplete coverage fixture source semantics. All were repaired and re-reviewed. The reviewer withdrew its initially overstrict lower-bound chronology remedy after the controller showed that M1a eligibility uses the conservative upper bound; the accepted per-channel definite-contradiction rule is documented above.

Initial behavior RED after interfaces: 11 failing tests and 4 passing. Repair RED: 5 failing and 15 passing, covering missing owner binding, early-channel rescue, rejected unknown availability, and omitted coverage/correction source semantics. Final focused GREEN: 20 tests. Controller full gate: 885 tests passed (8.30s), Ruff lint/format passed, mypy passed across 76 source files, build and whitespace checks passed. Source/test changes are confined to the three approved Task 3 paths, all pre-M1c files/dependencies are unchanged, and unrelated-file hashes still match preflight. Intended accepted subject: `feat: add M1c coverage and source selection policy`.

Cross-task proof remains explicit: Task 4 must validate actual fact inventories, supporting/methodology bytes, source-version snapshot consistency and input contexts. Task 6 must prove exact query matching, historical completeness, occurrence grouping and contemporaneous snapshot composition. The local models do not claim those later runtime guarantees. Task 4 is next after commit/Checkpoint; no M1d implementation or plan is authorized.

### Task 4 acceptance

Sol implemented four exact role schemas/parsers, deterministic dataset validation, immutable input contexts, full decision/record/bundle revalidation, exact nested supporting-byte closure, inventory/snapshot checks, and the closed synthetic methodology seam. The source policy binds economic inputs; identity remains independently bound by the context hash. No source-policy hash cycle or trusted PASS shortcut is introduced. Empty datasets receive exact-empty markers only after real validation and retain MANIFEST_ONLY scope.

The first implementation slice had a TDD process gap: semantic tests passed on their first clean execution after code, following only import/attribute and fixture errors. The controller refused acceptance. The unaccepted behavior was reduced to callable scaffolds and rebuilt through observed semantic failures for schema fields, temporal bindings, dropped parsed records, schema/row-count rejection and methodology recognition. These are remediation results, not invented original history. Context/closure then used behavior RED for omitted records, tampered decisions, corrupt partitions, incorrect context hashes and missing/duplicate/extra/corrupt support. A further RED caught fabricated complete coverage over unknown source availability; partial coverage retains those facts.

A fresh Sol reviewer found two Important defects. The controller independently reproduced both: per-row subject/listing checks rejected required whole-manifest inventories and A-to-B corrections, while indented truthful methodology bytes were incorrectly recognized. One scoped repair round removed only the premature subject filter and required exact canonical method bytes. Four behavioral RED cases became GREEN, including unrelated securities, coherent attribution corrections, optional listing context and noncanonical/duplicate-key JSON. The independent reviewer approved spec compliance and quality with no remaining findings; file checksums matched the final reviewed snapshot.

Final focused GREEN: 30 Task 4 tests. Controller full gate: 915 tests passed (10.02s), Ruff lint/format passed, mypy passed across 78 source files, build and whitespace checks passed. All protected pre-M1c source/tests/fixtures/dependencies and unrelated-file hashes remain unchanged. Intended accepted subject: `feat: validate exact M1c source datasets and contexts`. Task 5 must consume complete validated inventories before causal selection and subject filtering; query/consumer authority and outcome composition are not yet implemented. No M1d or external capability is authorized.

### Task 5 acceptance

Sol implemented finite K/V selection, retained identity, source/time applicability, strict raw and safe-projection references, exact dependent replay, immutable returned maps and deterministic proof ordering. Ten observed semantic RED/GREEN slices covered omitted known terms, missing component projections, forged values/proof fields, UNASSIGNED positive prefixes, persistent chronology, runtime role misuse, uncertain revisions, context ordering, direct identity context binding and nested-locator disclosure. No import-only test result was substituted for those behavior failures.

The controller and independent Sol adversarial reviewer found a valid partial projection leaking a withheld UUID through a known component's encoded evidence locator. The bounded derived-locator rule above repaired it without changing economic values, artifact content identity, source rows or old schemas. Independent Terra spec/quality review then found absent competing-identity handling; the controller reproduced that and a prefix walk resurrecting A after an intervening correction to B. A separate Sol adversarial review demonstrated an unchanged impossible actual claim becoming raw-authorized merely by switching to a later vendor channel. These required the documented identity and intrinsic-chronology refinements, not changes to M1a/M1b.

Fix 1 began with six observed behavioral failures and ended with 37 focused tests passing. It binds competing evidence, denies overlapping/uncertain assignment authority, preserves disjoint/ended reuse, stops invalidated prefixes, and checks trusted own-channel evidence on only the selected actual revision. Both reviewers approved the immutable repair snapshot with no open Important/Critical finding. One Minor test-strengthening note remains for final acceptance: explicitly pin the indeterminate-overlap reason in the ambiguous-identity test; current code already preserves it.

Controller full gate: 952 tests passed (13.68s), Ruff lint/format passed, mypy passed across 80 source files, build and whitespace checks passed, and file hashes matched the reviewed snapshot. The implementer had omitted the initial build under a mistaken interpretation of scope; its report was corrected and the controller ran the required build. Malformed temporary-cache command attempts did not constitute verification; final static checks used standard repository commands. No dependency, protected pre-M1c source/test/fixture, or unrelated-file change occurred. Intended accepted subject: `feat: add replayable M1c causal selection and references`.

Task 6 remains responsible for source/occurrence composition, associations, claim/residual folds and completeness/support results. Task 5 does not claim those are implemented, and no M1d or external capability is authorized.

### Task 6 acceptance

Task 6 implements exact economic occurrence comparison and reporting authority, family-local associations, effect/delivery separation, pairwise claim chronology, action-scoped residual folds, independent completeness/support, and full result replay. Sol implemented the slice; fresh independent Sol spec/composition and Sol temporal/dependency reviewers approved the final repair with no open Important/Critical findings. The controller reproduced the original counterexamples before accepting repairs.

One bounded repair round fixed non-admitted actual-effect parents, opposing exact ties and nonadjacent claim overlaps, conflicting-parent effect fallback, and unresolved later installments falsely leaving an action closed. It added the literal comparison-spec hash and exhaustive included/excluded-field matrix plus every named Task 6 attack. Known future-scheduled terms remain admissible link metadata, not occurrence authority. The shared-policy variant search demonstrated that matching hashes did not validate constructor-bypassed policy invariants; the common M1c selection boundary now rebuilds the existing policy model before use, with 12 direct regressions across four public entry points. No prior M0/M1a/M1b contract or wire schema changed.

Final focused tests: 49 selection and 58 outcome cases. Controller full gate: 1,022 tests passed (19.49s), Ruff lint, format check (113 files), mypy (83 files), sdist/wheel build and diff check passed; all six reviewed source/test hashes matched. Independent adversarial re-review additionally passed 23 targeted cases and confirmed both saved residual counterexamples no longer reached their incorrect results. Protected pre-M1c paths are unchanged, and all four intentionally untracked unrelated-file hashes match preflight. Task 7 immutable integration histories are next after commit and Checkpoint; M1d remains unauthorized.
