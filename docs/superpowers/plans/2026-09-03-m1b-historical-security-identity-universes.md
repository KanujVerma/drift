# Drift M1b Historical Security Identity and Universes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Planned and not started. This is the only active executable M1b plan. It is not authorization to implement M1b until the user approves execution.

**Prerequisite:** Start from `main` with umbrella-design commit `6086a1f` present. M1a is complete at `0385493`.

**Goal:** Build reproducible, point-in-time issuer, security, listing, lifecycle, and universe semantics without prices, corporate-action accounting, sessions, evaluation, or trading.

**Architecture:** Add assertion-specific temporal and manifest contracts beside unchanged M0/M1a V1 contracts, then build frozen M1b records and audit-side resolvers over immutable synthetic datasets. Identity corrections remain assertions, historical experiments remain pinned to exact manifests, and decision-facing references expose only selected record hashes.

**Tech Stack:** Python 3.14, Pydantic 2, standard library, pytest, Ruff, mypy, and Hatchling through `uv`. Add no dependency.

**Spec:** `docs/superpowers/specs/2026-09-02-m1b-m1c-historical-equity-semantics-design.md`

## Global Constraints

- M1b owns identity, lifecycle, historical universes, structural eligibility, point-in-time availability, synthetic fixtures, and M0/M1a compatibility only.
- M1c remains unplanned and unimplemented. Do not add prices, actions, outcomes, bars, calendars, sessions, missing-observation semantics, tradability, portfolio accounting, or backtesting.
- Use only synthetic local records. Do not add providers, downloads, network clients, credentials, broker interfaces, agents, LLM calls, production configuration, or order placement.
- Preserve `DatasetManifestV1`, `RecordTemporalContractV1`, `DatasetValidationDecisionV1`, `FactVersionV1`, canonical bytes, stored hashes, ledger events, and replay behavior exactly.
- All new persisted models are frozen, strict, extra-forbid, explicitly schema-versioned, canonically serializable, and content-hashable.
- UUIDv7 values name entities and versions. Reproducibility comes from retained assignment datasets, never UUID regeneration or a mutable global registry.
- Every historical query binds a knowledge cutoff, evaluation time, channel, policy, manifest, passing exact-object validation decision, and considered plus selected record hashes.
- `as_known` is the only mode permitted in decision-information references. `current_interpretation` is audit-only and ex-post.
- Unknown, bounded, contradictory, malformed, or unavailable evidence fails closed as `indeterminate` or a validation failure. It is never guessed into eligibility.
- The initial scope is domestic operating-company common shares with one evidenced primary listing on XNYS, XNAS, or XASE. Every listed exclusion remains unsupported.
- Do not read, stage, modify, or commit the unrelated root `.DS_Store`.
- Before each implementation commit run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, and `uv build`.

---

## Blocking Decisions and Architecture Corrections

### Open-question classification

| Umbrella question | Classification | M1b decision |
| --- | --- | --- |
| 1. Classification vocabulary | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Use the small enums in Task 3. Strict eligibility requires `operating_company`, `common_share`, and `domestic`; unsupported categories are explicit; unknown or conflict is indeterminate. |
| 2. Initial target level | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Generic contracts allow one `security` or `listing` level, but the initial structural universe and its fixtures target listings only. |
| 3. Relationship kinds | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Implement only `issuer_has_security`, `security_has_listing`, `equivalent_to`, `distinct_from`, `successor_of`, and `reorganized_from`. Unrecognized source relations do not enter the mapped dataset. |
| 4. Canonical equivalent identity | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Return a UUID-sorted equivalence set. Do not choose a canonical representative or create mutable union-find state. |
| 5. Admission boundary | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Preserve `admitted` evidence, but structural activity begins only when `first_regular_trade` is definitely effective. Bounded and unknown evidence remains uncertain. |
| 6. Synthetic index | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Require one synthetic addition/removal fixture to test announcement versus effect. Select no real index family. |
| 7. Termination vocabulary | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Use seven broad families plus optional source-native code/text. Do not grow a provider ontology. |
| 8. M1c action variants | DEFER TO M1c | No M1b type, fixture, or plan step. |
| 9. Split-normalization timing | DEFER TO M1c | No M1b behavior. |
| 10. OHLC and close conventions | DEFER TO REAL PROVIDER ADAPTER | This also requires M1c first. |
| 11. Provider-missing evidence | DEFER TO REAL PROVIDER ADAPTER | No missing-row classification in M1b. |
| 12. Schedule producer | DEFER TO M1c | No calendar dependency or artifact. |
| 13. Unknown terminal-outcome policy | DEFER TO EVALUATOR | M1b retains only known/partial/unknown outcome-evidence status. |
| 14. Manifest V2 wire schema | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Implement Task 1's exact additive wrapper, assertion contract, and content-bound dataset role. V1 stays unchanged. One role per record family prevents a generic manifest pass from masquerading as semantic record validation. |
| 15. Materialized cutoff views | MUST RESOLVE BEFORE M1b IMPLEMENTATION | Do not materialize M1b cutoff views. Emit audit proofs and selected-hash decision references. M1c may revisit observation views. |
| 16. Decision process boundary | CAN RESOLVE DURING M1b IMPLEMENTATION | Task 1 separates audit proof construction from selected-record resolution. Process isolation and evaluator wiring remain future work. |

### Admission-boundary evidence

The SEC treats the first reported listing-exchange transaction as the boundary after which other exchanges may extend IPO trading privileges. An NYSE data specification separately defines initial NYSE Group listing date and notes first-trade date use in other cases. NYSE also documents venue-specific early and core sessions. Those are different facts, so Drift must not infer one universal instant. M1b records source-native boundaries and activates the initial daily structural universe only after a definitely effective `first_regular_trade` event.

- [SEC Rule 12f-2 final rule](https://www.sec.gov/rules-regulations/2000/08/unlisted-trading-privileges)
- [NYSE Group ADR Master specification](https://www.nyse.com/publicdocs/nyse/data/NYSE_ADR_Master_Spec_v1.1.0.pdf)
- [NYSE trading sessions](https://www.nyse.com/trade/trading-information)

### Smallest corrections to the umbrella sketches

1. `create | affirm | retract | replace` overlaps with `RevisionKind`, and `replace` has no target. Use `IdentityAssignmentEffect.ASSIGNED | UNASSIGNED`; use the envelope for corrections; use relationships for equivalence, distinction, and succession.
2. Venue transfer is assigned to lifecycle, but the lifecycle sketch has no related-listing field. Add `related_listing_id`, require it only for `venue_transfer`, and validate old/new listings belong to the same security.
3. One `DatasetManifestV2` has one schema, role, and temporal contract, so it cannot be the singular container for all identity or universe families. Add a content-addressed `ValidatedDatasetBundleV1` containing exact role/manifest/passing-decision hashes. Individual selection proofs bind one member manifest; experiment definitions and composite results bind the bundle hash.
4. Absence of a termination record is not proof that no termination occurred. Add a sourced `ListingHistoryCoverageVersionV1` that states whether lifecycle/termination history is complete through a boundary for one listing. Active resolution requires complete coverage through E; partial/unknown coverage is indeterminate. This is lifecycle-event coverage, not M1c market-observation coverage.

No other approved architectural choice is reopened.

## File Map

| File | Responsibility |
| --- | --- |
| `src/drift/domain/assertions.py` | Effective-time claims, revision envelopes, query/proof/reference records, and hash bindings. |
| `src/drift/domain/manifests.py` | Additive assertion temporal contract, V2 discriminator wrapper, and `DatasetManifestV2`. |
| `src/drift/domain/dataset_validation.py` | Additive V2 decision and validated-dataset bundle contracts. |
| `src/drift/datasets/hashing.py` | V2 manifest typing and assertion payload preimage. |
| `src/drift/datasets/assertions.py` | Generic V2 validation, causal selection, and selected-hash resolution. |
| `src/drift/datasets/events.py` | V2-only manifest and validation event factories. |
| `src/drift/domain/securities.py` | Identity, mapping, classification, role, lifecycle, and termination records. |
| `src/drift/markets/identity.py` | Audit-side identity, mapping, classification, role, and lifecycle resolution. |
| `src/drift/domain/universes.py` | Universe definitions, memberships, and structural results. |
| `src/drift/markets/universes.py` | Membership and structural-eligibility resolution. |
| `src/drift/markets/validation.py` | M1b parsers, schemas, and cross-record validation. |
| `tests/unit/test_assertions.py` | Boundary, interval, chain, proof, and capability tests. |
| `tests/unit/test_manifest_v2.py` | V2 discriminator and V1 compatibility tests. |
| `tests/unit/test_dataset_validation_v2.py` | Exact-object V2 decision and event tests. |
| `tests/unit/test_security_identity.py` | Identity, endpoints, assignment, equivalence, split, and target tests. |
| `tests/unit/test_listing_semantics.py` | Mapping, classification, role, admission, transfer, and termination tests. |
| `tests/unit/test_universes.py` | Definition, membership, timing, and structural eligibility tests. |
| `tests/integration/test_m1b_identity_history.py` | Ticker, share-class, correction, and transfer histories. |
| `tests/integration/test_m1b_universe_leakage.py` | Announcement/effect, current-state leakage, and delisted retention. |
| `tests/integration/test_m1b_m1a_compatibility.py` | Pinned M0/M1a bytes, hashes, events, replay, and scope checks. |
| `tests/fixtures/datasets/m1b/*.json` | Canonical, hash-pinned synthetic identity/listing/universe histories only. |

## Shared Interfaces Locked by This Plan

```python
# src/drift/domain/assertions.py
class BoundaryShape(StrEnum):
    EXACT = "exact"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class EffectiveTimeStatus(StrEnum):
    NOT_EFFECTIVE = "not_effective"
    EFFECTIVE = "effective"
    INDETERMINATE = "indeterminate"


class IntervalStatus(StrEnum):
    BEFORE = "before"
    ACTIVE = "active"
    ENDED = "ended"
    INDETERMINATE = "indeterminate"


class ResolutionMode(StrEnum):
    AS_KNOWN = "as_known"
    CURRENT_INTERPRETATION = "current_interpretation"


class InformationRole(StrEnum):
    DECISION_INFORMATION = "decision_information"
    EX_POST_OUTCOME = "ex_post_outcome"


class M1bSelectionPurpose(StrEnum):
    IDENTITY_RESOLUTION = "identity_resolution"
    STRUCTURAL_ELIGIBILITY = "structural_eligibility"
    UNIVERSE_MEMBERSHIP = "universe_membership"
    LISTING_LIFECYCLE = "listing_lifecycle"
    LISTING_TERMINATION = "listing_termination"


class TemporalBoundaryClaimV1(FrozenModel):
    schema_version: Literal["1"]
    shape: BoundaryShape
    lower_bound: UTCDateTime | None
    upper_bound: UTCDateTime | None
    source_precision: SourcePrecision
    source_time_label: NonBlankStr | None
    source_timezone: NonBlankStr | None
    evidence_reference: ArtifactReference | None


class TemporalIntervalClaimV1(FrozenModel):
    schema_version: Literal["1"]
    start: TemporalBoundaryClaimV1
    end: TemporalBoundaryClaimV1 | None


class HistoryCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class RevisionEnvelopeV1(FrozenModel):
    schema_version: Literal["1"]
    logical_record_id: UUID7
    record_version_id: UUID7
    revision_kind: RevisionKind
    supersedes_record_version_id: UUID7 | None
    source_sequence: Annotated[int, Field(ge=0)]
    availability: tuple[AvailabilityEvidenceV1, ...]
    history_completeness: HistoryCompleteness
    source_native_revision_label: NonBlankStr | None
    source_artifact: ArtifactReference
    payload_hash: SHA256Hash


class AssertionVersionProjectionV1(FrozenModel):
    revision: RevisionEnvelopeV1
    record_hash: SHA256Hash


class AssertionSelectionResultV1(FrozenModel):
    schema_version: Literal["1"]
    classification: CutoffEligibility
    reason: NonBlankStr
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_versions: tuple[AssertionVersionProjectionV1, ...]
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hash: SHA256Hash | None


class NormalizedSelectionQueryV1(FrozenModel):
    schema_version: Literal["1"]
    purpose: M1bSelectionPurpose
    information_role: InformationRole
    resolution_mode: ResolutionMode
    subject_hash: SHA256Hash
    source_manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash
    context_bundle_hashes: tuple[SHA256Hash, ...]
    dataset_role_hash: SHA256Hash
    record_contract_hash: SHA256Hash
    schema_hash: SHA256Hash
    knowledge_cutoff: UTCDateTime
    evaluation_time: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash


class CutoffSelectionProofV1(FrozenModel):
    schema_version: Literal["1"]
    source_manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash
    selection_algorithm: Literal["drift-m1b-cutoff-selection-v1"]
    selection_implementation_hash: SHA256Hash
    normalized_query: NormalizedSelectionQueryV1
    normalized_query_hash: SHA256Hash
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hashes: tuple[SHA256Hash, ...]
    classification: CutoffEligibility
    reasons: tuple[NonBlankStr, ...]


class DecisionSelectionReferenceV1(FrozenModel):
    schema_version: Literal["1"]
    selection_proof_hash: SHA256Hash
    normalized_query_hash: SHA256Hash
    purpose: M1bSelectionPurpose
    information_role: Literal[InformationRole.DECISION_INFORMATION]
    selected_record_hashes: tuple[SHA256Hash, ...]


class ResolutionEvidenceV1(FrozenModel):
    schema_version: Literal["1"]
    normalized_query: NormalizedSelectionQueryV1
    normalized_query_hash: SHA256Hash
    considered_record_hashes: tuple[SHA256Hash, ...]
    selected_record_hashes: tuple[SHA256Hash, ...]
    selection_proof_hashes: tuple[SHA256Hash, ...]


# src/drift/domain/dataset_validation.py
class ValidatedDatasetMemberV1(FrozenModel):
    dataset_role: DatasetRoleV1
    manifest_hash: SHA256Hash
    validation_decision_hash: SHA256Hash


class ValidatedDatasetBundleV1(FrozenModel):
    schema_version: Literal["1"]
    bundle_id: UUID7
    bundle_version: NonBlankStr
    members: tuple[ValidatedDatasetMemberV1, ...]
    created_at: UTCDateTime
```

`RevisionEnvelopeV1.payload_hash` is the canonical hash of the owning assertion with only `revision.payload_hash` removed. `record_hash` is the canonical hash of the complete owning assertion. The dataset-specific parser must verify that parent binding.

Every normalized query uses sorted unique `context_bundle_hashes`, `dataset_role_hash=content_hash(manifest.dataset_role)`, `record_contract_hash=content_hash(manifest.temporal_contract.contract)`, `schema_hash=manifest.schema_definition.schema_hash`, and `validation_decision_hash=content_hash(decision)`. The selected manifest/decision must be a member of one named context bundle. Purpose-specific resolvers require `subject_hash` to equal the canonical hash of their exact typed subject inputs.

Bundle members are sorted by role name and must have unique roles and manifest hashes. `build_validated_dataset_bundle` accepts actual `(DatasetManifestV2, DatasetValidationDecisionV2)` pairs, requires every decision to pass and match its manifest/role/contracts, and returns the frozen bundle. `content_hash(bundle)` is the bundle identity; no mutable registry or stored self-hash is added.

The M1b purpose matrix is closed:

| Records/query | Purpose | Permitted decision mode/role |
| --- | --- | --- |
| assignment, relationship, identifier mapping | `identity_resolution` | `as_known`, `decision_information` |
| classification and primary role | `structural_eligibility` | `as_known`, `decision_information` |
| lifecycle events | `listing_lifecycle` | `as_known`, `decision_information` |
| termination facts needed by a historical decision | `listing_termination` | `as_known`, `decision_information` |
| universe additions/removals | `universe_membership` | `as_known`, `decision_information` |
| final audit inspection | same record-specific purpose | `current_interpretation`, `ex_post_outcome`, with no decision-reference conversion |

Final economic termination accounting and outcome references remain M1c. The ex-post role here only labels audit interpretation of M1b facts.

Boundary rules are exact: exact claims have equal non-null bounds and `SECOND` precision; bounded claims have ordered bounds and reuse M1a source-label/timezone window validation; unknown claims have null bounds and `UNKNOWN` precision. `evaluate_boundary_at` is not effective before the lower bound, effective at or after the upper bound, and indeterminate inside a bounded window or for unknown evidence. `evaluate_interval_at` returns before/active/ended/indeterminate; `end=None` means open-ended, not unknown.

---

### Task 1: Add Assertion Temporality, Manifest V2, and Least-Privilege Selection

**Files:**
- Create: `src/drift/domain/assertions.py`
- Create: `src/drift/datasets/assertions.py`
- Modify: `src/drift/domain/manifests.py`
- Modify: `src/drift/domain/dataset_validation.py`
- Modify: `src/drift/datasets/hashing.py`
- Modify: `src/drift/datasets/events.py`
- Test: `tests/unit/test_assertions.py`
- Test: `tests/unit/test_manifest_v2.py`
- Test: `tests/unit/test_dataset_validation_v2.py`
- Test: `tests/integration/test_m1b_m1a_compatibility.py`

**Interfaces:**
- Consumes: M1a availability evaluation, `RevisionKind`, V1 manifest provenance descriptors, validation findings/context, verified bytes, and canonical hashing.
- Produces: shared interfaces above plus `AssertionTemporalContractV1`, `TemporalContractBindingV2`, `DatasetManifestV2`, `DatasetValidationDecisionV2`, `build_validated_dataset_bundle`, `validate_assertion_chain`, `select_assertion_version`, `decision_reference_from_proof`, `resolve_selected_records`, and V2 event factories.

- [ ] **Step 1: Pin existing V1 compatibility outputs**

Add exact expected bytes and hashes for a fixed `DatasetManifestV1`, `DatasetValidationDecisionV1`, `FactVersionV1`, and the two existing dataset event drafts, following `test_m1_m0_compatibility.py`.

- [ ] **Step 2: Verify the baseline is green**

Run: `uv run pytest tests/integration/test_m1b_m1a_compatibility.py -v`

Expected: PASS against `6086a1f`; otherwise stop and reconcile the fixture. Define local `parse_utc` and `boundary_case` helpers with fixed UTC values for the table before adding the parametrized test.

- [ ] **Step 3: Write failing boundary and interval tests**

```python
@pytest.mark.parametrize(
    ("case", "instant", "expected"),
    (
        ("exact", "2020-01-02T14:30:00Z", "effective"),
        ("bounded_before", "2020-01-01T23:59:59Z", "not_effective"),
        ("bounded_inside", "2020-01-02T12:00:00Z", "indeterminate"),
        ("bounded_after", "2020-01-03T00:00:00Z", "effective"),
        ("unknown", "2030-01-01T00:00:00Z", "indeterminate"),
    ),
)
def test_effective_boundary_is_conservative(case, instant, expected):
    assert (
        evaluate_boundary_at(boundary_case(case), parse_utc(instant)).value == expected
    )
```

Also prove open-ended intervals stay active, unknown ends are indeterminate, malformed windows fail, and credential-bearing locators are rejected.

- [ ] **Step 4: Verify boundary tests are RED**

Run: `uv run pytest tests/unit/test_assertions.py -v`

Expected: collection FAIL because `drift.domain.assertions` does not exist.

- [ ] **Step 5: Implement the shared assertion models and temporal evaluators**

Implement the interfaces above. Reuse M1a timezone/source-window helpers. Keep boundary claims free of channel and availability basis.

- [ ] **Step 6: Verify boundary tests are GREEN**

Run: `uv run pytest tests/unit/test_assertions.py -v`

Expected: PASS for exact, bounded, unknown, open-ended, invalid-window, and safe-reference cases.

- [ ] **Step 7: Write failing V2 contract tests**

Use these exact persisted models:

```python
class AssertionEffectiveShape(StrEnum):
    BOUNDARY = "boundary"
    INTERVAL = "interval"


class AssertionTemporalContractV1(FrozenModel):
    contract_version: Literal["1"]
    evidence_granularity: Literal[EvidenceGranularity.RECORD]
    logical_record_id_field_id: NonBlankStr
    record_version_id_field_id: NonBlankStr
    revision_kind_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr
    source_sequence_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    source_artifact_field_id: NonBlankStr
    payload_hash_field_id: NonBlankStr
    effective_time_field_id: NonBlankStr
    effective_shape: AssertionEffectiveShape
    semantic_state_field_ids: tuple[NonBlankStr, ...]
    declared_channels: tuple[AvailabilityChannelV1, ...]


class TemporalContractKindV2(StrEnum):
    RECORD_TEMPORAL_V1 = "record_temporal_v1"
    ASSERTION_TEMPORAL_V1 = "assertion_temporal_v1"


class TemporalContractBindingV2(FrozenModel):
    kind: TemporalContractKindV2
    contract: RecordTemporalContractV1 | AssertionTemporalContractV1


class DatasetRoleV1(FrozenModel):
    namespace: Literal["drift"]
    name: NonBlankStr
    version: Literal["1"]


class DatasetManifestV2(FrozenModel):
    manifest_schema_version: Literal["2"]
    hash_profile: Literal["drift-canonical-json-sha256-v1"]
    dataset_id: UUID7
    dataset_version: NonBlankStr
    dataset_kind: DatasetKind
    dataset_role: DatasetRoleV1
    created_at: UTCDateTime
    source: SourceDescriptorV1
    acquisition: AcquisitionDescriptorV1
    license: LicenseDescriptorV1
    schema_definition: SchemaDescriptorV1
    partitions: tuple[PartitionDescriptorV1, ...]
    temporal_contract: TemporalContractBindingV2
    lineage: LineageDescriptorV1 | None


class DatasetValidationDecisionV2(FrozenModel):
    decision_schema_version: Literal["2"]
    decision_id: UUID7
    manifest_hash: SHA256Hash
    manifest_schema_version: Literal["2"]
    dataset_role_hash: SHA256Hash
    schema_hash: SHA256Hash
    temporal_contract_kind: TemporalContractKindV2
    temporal_contract_version: Literal["1"]
    temporal_contract_hash: SHA256Hash
    validator_version: NonBlankStr
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    validated_artifact_hashes: tuple[SHA256Hash, ...]
    validated_record_hashes: tuple[SHA256Hash, ...]
    checked_contracts: tuple[NonBlankStr, ...]
    findings: tuple[ValidationFindingV1, ...]
```

M1b uses exactly these `DatasetRoleV1.name` values, one per manifest and record schema:

```text
identity_assignment
identity_relationship
external_identifier_mapping
security_classification
listing_role
listing_lifecycle
listing_termination
listing_history_coverage
source_universe_definition
universe_membership
```

`ResearchUniverseDefinitionV1` is a directly content-addressed, research-authored policy artifact, not a sourced assertion dataset. A partition never mixes role names or record unions.

Every role schema contains the common field IDs below. Nested objects use `LogicalType.JSON`; IDs/enums/text use `STRING`; source sequence uses `INTEGER`.

```text
schema_version
revision.logical_record_id
revision.record_version_id
revision.revision_kind
revision.supersedes_record_version_id
revision.source_sequence
revision.availability
revision.history_completeness
revision.source_native_revision_label
revision.source_artifact
revision.payload_hash
```

Role-specific field IDs are exact: assignment adds `identity`, `source_namespace`, `source_key`, `assignment_effect`, `effective_interval`; relationship adds `left`, `right`, `relationship_kind`, `resolution_status`, `effective_interval`, `source_relationship_code`; mapping adds `namespace`, `identifier_value`, `target`, `mapping_status`, `effective_interval`; classification adds every named classification field and `effective_interval`; listing role adds `security_id`, `listing_id`, `role`, `methodology_id`, `methodology_version`, `effective_interval`; lifecycle adds `listing_id`, `event_kind`, `effective_time`, `related_listing_id`; termination adds every named termination field and `effective_time`; listing-history coverage adds `listing_id`, `coverage_status`, `complete_through`; source universe definition adds every named definition field and `effective_interval`; membership adds every named membership field and `effective_time`. Define one `SchemaDescriptorV1` constant and one typed document parser per role. Do not infer schemas from Pydantic at runtime.

Reject kind/contract mismatches, duplicate fields/channels, and schema bindings to absent field IDs. `DatasetValidationDecisionV2` adds `decision_schema_version="2"`, `manifest_schema_version`, `dataset_role_hash`, `schema_hash`, `temporal_contract_kind`, `temporal_contract_version`, and `temporal_contract_hash` to V1's exact validation data. Each dataset-specific validator accepts one exact role name and rejects all others.

- [ ] **Step 8: Verify V2 tests are RED**

Run: `uv run pytest tests/unit/test_manifest_v2.py tests/unit/test_dataset_validation_v2.py -v`

Expected: FAIL because V2 models are absent.

- [ ] **Step 9: Implement additive V2 models, validation, hashing, and events**

Do not refactor V1 into a shared base. Add separate `validate_manifest_v2_structure`, `build_manifest_v2_recorded_event`, and `build_validation_v2_completed_event`. V2 event payloads include manifest, temporal-contract, and decision schema discriminators and reject V1 decisions. Add:

```python
def build_validated_dataset_bundle(
    bundle_id: UUID7,
    bundle_version: str,
    created_at: datetime,
    validated_datasets: Sequence[tuple[DatasetManifestV2, DatasetValidationDecisionV2]],
) -> ValidatedDatasetBundleV1: ...
```

Test rejection of a failed, mismatched, duplicate-role, or duplicate-manifest member.

- [ ] **Step 10: Write failing causal-chain and capability tests**

Test duplicate IDs, roots, missing predecessors, branching, cycles, logical-record mismatch, sequence, and backward availability. A source correction first observed locally is `INITIAL` with partial/unknown history, never complete. Define local `proof_with` to build a fully hash-consistent proof from explicit considered/selected tuples, then add:

```python
def test_decision_reference_cannot_resolve_considered_or_future_records():
    proof = proof_with(considered=(OLD, FUTURE), selected=(OLD,))
    reference = decision_reference_from_proof(proof)
    assert resolve_selected_records(reference, {OLD: b"old"}) == {OLD: b"old"}
    with pytest.raises(DatasetValidationError, match="unauthorized_record_hash"):
        resolve_selected_records(reference, {OLD: b"old", FUTURE: b"future"})
```

- [ ] **Step 11: Implement causal selection and selected-hash resolution**

```python
def validate_assertion_chain(
    versions: Sequence[AssertionVersionProjectionV1],
) -> tuple[ValidationFindingV1, ...]: ...


def select_assertion_version(
    versions: Sequence[AssertionVersionProjectionV1],
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> AssertionSelectionResultV1: ...


def build_cutoff_selection_proof(
    query: NormalizedSelectionQueryV1,
    selections: Sequence[AssertionSelectionResultV1],
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    selection_implementation_hash: SHA256Hash,
) -> CutoffSelectionProofV1: ...


def decision_reference_from_proof(
    proof: CutoffSelectionProofV1,
) -> DecisionSelectionReferenceV1: ...


def resolve_selected_records[T](
    reference: DecisionSelectionReferenceV1,
    records_by_hash: Mapping[SHA256Hash, T],
) -> Mapping[SHA256Hash, T]: ...
```

`build_cutoff_selection_proof` requires a passing V2 decision whose manifest, role, schema, and temporal-contract hashes match the query and manifest. It sorts/deduplicates record hashes and verifies every selected hash was considered and validated. Its availability classification is indeterminate if any component selection is indeterminate, eligible if at least one component is selected and none is indeterminate, otherwise ineligible. Business conflict/status remains in the purpose-specific resolution result. Require supplied record keys to equal, not contain, selected hashes. Refuse conversion of current-interpretation or non-decision proofs to decision references.

- [ ] **Step 12: Run focused and full gates**

Run: `uv run pytest tests/unit/test_assertions.py tests/unit/test_manifest_v2.py tests/unit/test_dataset_validation_v2.py tests/integration/test_m1b_m1a_compatibility.py -v`

Then run the full gate from Global Constraints. Expected: all pass and V1 bytes/hashes are unchanged.

- [ ] **Step 13: Commit the additive foundation**

```bash
git add src/drift/domain/assertions.py src/drift/domain/manifests.py src/drift/domain/dataset_validation.py src/drift/datasets/assertions.py src/drift/datasets/hashing.py src/drift/datasets/events.py tests/unit/test_assertions.py tests/unit/test_manifest_v2.py tests/unit/test_dataset_validation_v2.py tests/integration/test_m1b_m1a_compatibility.py
git commit -m "feat: add assertion temporal dataset contracts"
```

---

### Task 2: Add Immutable Identity Assignments and Correctable Relationships

**Files:**
- Create: `src/drift/domain/securities.py`
- Create: `src/drift/markets/__init__.py`
- Create: `src/drift/markets/identity.py`
- Create: `src/drift/markets/validation.py`
- Test: `tests/unit/test_security_identity.py`
- Test: `tests/integration/test_m1b_identity_history.py`
- Fixture: `tests/fixtures/datasets/m1b/identity-assignments.json`
- Fixture: `tests/fixtures/datasets/m1b/identity-relationships.json`

**Interfaces:**
- Consumes: Task 1 assertion envelope, interval evaluator, V2 validation, causal selection/proof APIs, canonical hashing, and verified bytes.
- Produces: identity records below, `validate_identity_dataset`, `resolve_identity_assignment`, `resolve_identity`, `IdentityAssignmentResolutionResultV1`, and `IdentityResolutionResultV1`.

- [ ] **Step 1: Write failing hierarchy and endpoint tests**

Use these exact records:

```python
class IdentityKind(StrEnum):
    ISSUER = "issuer"
    SECURITY = "security"
    LISTING = "listing"


class ListingVenue(StrEnum):
    XNYS = "XNYS"
    XNAS = "XNAS"
    XASE = "XASE"


class IssuerV1(FrozenModel):
    schema_version: Literal["1"]
    issuer_id: UUID7


class SecurityV1(FrozenModel):
    schema_version: Literal["1"]
    security_id: UUID7


class ListingV1(FrozenModel):
    schema_version: Literal["1"]
    listing_id: UUID7
    venue: ListingVenue


class IdentityReferenceV1(FrozenModel):
    kind: IdentityKind
    internal_id: UUID7


class IdentityAssignmentEffect(StrEnum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"


class IdentityAssignmentVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    identity: IssuerV1 | SecurityV1 | ListingV1
    source_namespace: NonBlankStr
    source_key: NonBlankStr
    assignment_effect: IdentityAssignmentEffect
    effective_interval: TemporalIntervalClaimV1


class IdentityRelationshipKind(StrEnum):
    ISSUER_HAS_SECURITY = "issuer_has_security"
    SECURITY_HAS_LISTING = "security_has_listing"
    EQUIVALENT_TO = "equivalent_to"
    DISTINCT_FROM = "distinct_from"
    SUCCESSOR_OF = "successor_of"
    REORGANIZED_FROM = "reorganized_from"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    DISPUTED = "disputed"
    INDETERMINATE = "indeterminate"


class IdentityRelationshipVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    left: IdentityReferenceV1
    right: IdentityReferenceV1
    relationship_kind: IdentityRelationshipKind
    resolution_status: ResolutionStatus
    effective_interval: TemporalIntervalClaimV1
    source_relationship_code: NonBlankStr | None
```

Assert the full endpoint matrix: issuer-to-security, security-to-listing, same-kind equivalence/distinction, and same-kind issuer/security succession/reorganization. Reject self-relations, listing succession through generic relationships, wrong UUID kind, and venues outside XNYS/XNAS/XASE. Prove issuer grouping does not collapse two security IDs.

- [ ] **Step 2: Verify model tests are RED**

Run: `uv run pytest tests/unit/test_security_identity.py -v`

Expected: collection FAIL because `drift.domain.securities` does not exist.

- [ ] **Step 3: Implement identity records and parent payload-hash checks**

Require unique sorted availability channels and safe source artifacts. Dataset parsing recomputes `revision.payload_hash` from the parent assertion and its complete record hash. Core identity objects contain no issuer name, ticker, mutable alias, or provider field. Add `identity_reference(identity: IssuerV1 | SecurityV1 | ListingV1) -> IdentityReferenceV1` and use it everywhere a relationship endpoint is needed. The retained assignment record is the provenance for creation of the typed identity object, including a listing's fixed venue.

- [ ] **Step 4: Write failing correction and equivalence tests**

Use fixed UUIDv7 values and these histories:

- Version A assigns `synthetic:alpha` to security S1.
- A later manifest asserts S1 equivalent to S2. Resolution returns `(S1, S2)` sorted by UUID and retains both IDs.
- A still later manifest asserts S1 distinct from S2. Before that assertion the equivalence resolves; after it the result is `conflict`; replay of the earlier manifest is unchanged.
- A mistaken one-security interpretation is corrected by minting S3 plus a distinct/successor assertion. No old ID or assignment changes.
- A wrong issuer-security relationship is superseded under the same logical record ID.

Assert no serialized parent pointer, path-compression state, or chosen canonical identity exists.

- [ ] **Step 5: Verify correction tests are RED**

Run: `uv run pytest tests/unit/test_security_identity.py -k "correction or equivalent or distinct or manifest" -v`

Expected: FAIL because validation and resolution functions are absent.

- [ ] **Step 6: Implement identity validation and audit-side resolution**

```python
class IdentityResolutionClassification(StrEnum):
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class IdentityAssignmentSubjectV1(FrozenModel):
    identity_kind: IdentityKind
    source_namespace: NonBlankStr
    source_key: NonBlankStr


class IdentityAssignmentResolutionResultV1(FrozenModel):
    schema_version: Literal["1"]
    subject: IdentityAssignmentSubjectV1
    assigned_identities: tuple[IdentityReferenceV1, ...]
    classification: IdentityResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class IdentityResolutionResultV1(FrozenModel):
    schema_version: Literal["1"]
    subject: IdentityReferenceV1
    resolved_identities: tuple[IdentityReferenceV1, ...]
    classification: IdentityResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    identity_bundle_hash: SHA256Hash
    resolution_mode: ResolutionMode
    knowledge_cutoff: UTCDateTime
    evaluation_time: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_assertion_hashes: tuple[SHA256Hash, ...]
    selected_assertion_hashes: tuple[SHA256Hash, ...]
    selection_proof_hashes: tuple[SHA256Hash, ...]


def validate_identity_dataset(
    manifest: DatasetManifestV2,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV2: ...


def resolve_identity_assignment(
    subject: IdentityAssignmentSubjectV1,
    assignments: Sequence[IdentityAssignmentVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> IdentityAssignmentResolutionResultV1: ...


def resolve_identity(
    subject: IdentityReferenceV1,
    assignments: Sequence[IdentityAssignmentVersionV1],
    relationships: Sequence[IdentityRelationshipVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> IdentityResolutionResultV1: ...
```

Reject non-passing or mismatched validation decisions. `as_known` selects only causally available and effective versions. `current_interpretation` uses active records in the pinned manifest, is ex-post, and cannot become a decision reference.

`resolve_identity_assignment` requires `query.subject_hash == content_hash(subject)`. A selected `assigned` assertion adds its typed identity; a selected `unassigned` assertion removes that exact source-key/identity association. Multiple active assigned identities are conflict unless selected relationship assertions explicitly resolve them as equivalent. Independent rebuilds given the same assignment manifest produce the same typed IDs.

Build equivalence components only from resolved active assertions. Sort records and IDs. Active equivalent/distinct contradictions or cycles return conflict; disputed evidence returns indeterminate. Never choose a winner.

- [ ] **Step 7: Create and hash-pin the identity fixture**

`identity-assignments.json` contains the issuer, two share classes, and listing assignments. `identity-relationships.json` contains equivalent IDs on 2020-01-01, a distinct correction effective 2021-01-01 and available 2021-02-01, and a superseded wrong issuer link. Store each exact SHA-256 in the integration test and read through `read_verified_local_artifact` only. Each file has its own matching role/schema/manifest.

Build identity bundle version `1` from the two passing role decisions. Pin `content_hash(bundle)` and prove a rebuild from the same members yields the same bundle hash and assignment results.

- [ ] **Step 8: Run focused and full gates**

Run: `uv run pytest tests/unit/test_security_identity.py tests/integration/test_m1b_identity_history.py -v`

Then run the full gate. Expected: all pass; old manifests replay unchanged; no mutable registry exists.

- [ ] **Step 9: Commit identity primitives and corrections**

```bash
git add src/drift/domain/securities.py src/drift/markets/__init__.py src/drift/markets/identity.py src/drift/markets/validation.py tests/unit/test_security_identity.py tests/integration/test_m1b_identity_history.py tests/fixtures/datasets/m1b/identity-assignments.json tests/fixtures/datasets/m1b/identity-relationships.json
git commit -m "feat: add immutable historical security identity"
```

---

### Task 3: Add Identifier, Classification, Primary-Listing, and Lifecycle Semantics

**Files:**
- Modify: `src/drift/domain/securities.py`
- Modify: `src/drift/markets/identity.py`
- Modify: `src/drift/markets/validation.py`
- Modify: `tests/integration/test_m1b_identity_history.py`
- Test: `tests/unit/test_listing_semantics.py`
- Fixture: `tests/fixtures/datasets/m1b/external-identifiers.json`
- Fixture: `tests/fixtures/datasets/m1b/security-classifications.json`
- Fixture: `tests/fixtures/datasets/m1b/listing-roles.json`
- Fixture: `tests/fixtures/datasets/m1b/listing-lifecycle.json`
- Fixture: `tests/fixtures/datasets/m1b/listing-terminations.json`
- Fixture: `tests/fixtures/datasets/m1b/listing-history-coverage.json`

**Interfaces:**
- Consumes: validated identities and Task 1 cutoff proofs.
- Produces: mappings, source classifications, listing roles/lifecycle/termination records, and their audit-side resolvers.

Resolution outputs are fixed before implementation:

```python
class RecordResolutionClassification(StrEnum):
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class ExternalIdentifierResolutionResultV1(FrozenModel):
    schema_version: Literal["1"]
    namespace: ExternalIdentifierNamespaceV1
    identifier_value: NonBlankStr
    targets: tuple[IdentityReferenceV1, ...]
    classification: RecordResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class SecurityClassificationStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


class SecurityClassificationResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    issuer_id: UUID7
    security_id: UUID7
    classification: SecurityClassificationStatus
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class PrimaryListingResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    security_id: UUID7
    methodology_id: NonBlankStr
    listing_id: UUID7 | None
    classification: RecordResolutionClassification
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class ListingLifecycleResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingLifecycleStatus
    selected_termination_version_id: UUID7 | None
    termination_resolution_hash: SHA256Hash
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class ListingHistoryCoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ListingHistoryCoverageResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingHistoryCoverageStatus
    complete_through: TemporalBoundaryClaimV1
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1


class ListingTerminationStatus(StrEnum):
    TERMINATED = "terminated"
    NOT_TERMINATED = "not_terminated"
    INDETERMINATE = "indeterminate"


class ListingTerminationResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    listing_id: UUID7
    status: ListingTerminationStatus
    selected_termination_version_id: UUID7 | None
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
```

- [ ] **Step 1: Write failing external-identifier tests**

```python
class ExternalIdentifierKind(StrEnum):
    TICKER = "ticker"
    CIK = "cik"
    CUSIP = "cusip"
    FIGI = "figi"
    PROVIDER = "provider"
    EXCHANGE_SYMBOL = "exchange_symbol"
    OTHER = "other"


class ExternalIdentifierNamespaceV1(FrozenModel):
    kind: ExternalIdentifierKind
    scheme: NonBlankStr
    authority: NonBlankStr
    target_level: IdentityKind
    venue: ListingVenue | None


class MappingStatus(StrEnum):
    ASSERTED = "asserted"
    AMBIGUOUS = "ambiguous"
    WITHDRAWN = "withdrawn"


class ExternalIdentifierMappingVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    namespace: ExternalIdentifierNamespaceV1
    identifier_value: NonBlankStr
    target: IdentityReferenceV1
    mapping_status: MappingStatus
    effective_interval: TemporalIntervalClaimV1
```

Require namespace target level to equal target kind. Ticker and exchange-symbol schemes target listings and require venue; CIK targets issuers and forbids venue. CUSIP, FIGI, provider, and other schemes retain an explicit target level and forbid venue unless their versioned scheme explicitly defines listing-venue scope. Collision identity includes authority, scheme, identifier kind, target level, exact normalized text, and venue. Reject overlapping asserted mappings to distinct targets unless all overlapping records are ambiguous. Reject mapping intervals outside the selected target identity/lifecycle interval.

- [ ] **Step 2: Write failing ticker and transfer history tests**

Use this exact synthetic history:

```text
2019-01-02: Security SA, Listing LA on XNAS, ticker OLD
2020-06-01: same SA and LA, ticker NEW
2021-12-31: LA terminates for venue_transfer
2022-01-03: same SA, new Listing LB on XNYS, ticker NEW
2024-01-02: unrelated Security SC and Listing LC on XNAS receive ticker OLD
```

Each K/E query resolves the period-specific mapping. Equal text never merges SA/SC. Ticker change mints no identity. Venue transfer mints a listing, not a security.

- [ ] **Step 3: Verify mapping tests are RED**

Run: `uv run pytest tests/unit/test_listing_semantics.py -k "mapping or ticker or transfer" -v`

Expected: FAIL because mapping/lifecycle models are absent.

- [ ] **Step 4: Implement mapping validation and resolution**

Implement this exact signature and validate `query.subject_hash == content_hash({"namespace": namespace, "identifier_value": value})`:

```python
def resolve_external_identifier(
    namespace: ExternalIdentifierNamespaceV1,
    value: str,
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> ExternalIdentifierResolutionResultV1: ...
```

Bind manifest/decision/query and considered/selected hashes. Return typed targets with resolved/conflict/indeterminate. The initial synthetic ticker scheme uses exact uppercase text; no unversioned punctuation normalization is allowed.

- [ ] **Step 5: Write failing classification and primary-role tests**

```python
class IssuerForm(StrEnum):
    OPERATING_COMPANY = "operating_company"
    FUND = "fund"
    REIT = "reit"
    TRUST = "trust"
    ACQUISITION_COMPANY = "acquisition_company"
    OTHER = "other"
    UNKNOWN = "unknown"


class InstrumentForm(StrEnum):
    COMMON_SHARE = "common_share"
    PREFERRED = "preferred"
    RECEIPT = "receipt"
    UNIT = "unit"
    WARRANT = "warrant"
    RIGHT = "right"
    OTHER = "other"
    UNKNOWN = "unknown"


class DomesticStatus(StrEnum):
    DOMESTIC = "domestic"
    FOREIGN = "foreign"
    INDETERMINATE = "indeterminate"


class ClassificationValueStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class SourcedTextValueV1(FrozenModel):
    status: ClassificationValueStatus
    value: NonBlankStr | None


class SecurityClassificationVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    issuer_id: UUID7
    security_id: UUID7
    issuer_form: IssuerForm
    issuer_domicile: SourcedTextValueV1
    incorporation_country: SourcedTextValueV1
    instrument_form: InstrumentForm
    share_class_label: SourcedTextValueV1
    domestic_status: DomesticStatus
    effective_interval: TemporalIntervalClaimV1
    source_taxonomy_id: NonBlankStr
    source_taxonomy_version: NonBlankStr
    source_fields: ImmutableJSON


class ListingRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    INDETERMINATE = "indeterminate"


class ListingRoleVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    security_id: UUID7
    listing_id: UUID7
    role: ListingRole
    methodology_id: NonBlankStr
    methodology_version: NonBlankStr
    effective_interval: TemporalIntervalClaimV1
```

Known text requires a value; unknown text forbids one. Test every excluded issuer/instrument category, foreign/indeterminate status, conflicting assertions, two share classes, a timeless-primary attempt, same-methodology primary overlap, and cross-methodology disagreement.

- [ ] **Step 6: Implement classification and primary-role resolution**

`resolve_security_classification(issuer_id, security_id, classifications, query, identity_bundle, manifest, decision, policy, retained_evidence) -> SecurityClassificationResolutionV1` returns supported/unsupported/conflict/indeterminate. Its subject hash binds both IDs, and the classification manifest/decision must be an identity-bundle member. Only explicit excluded evidence is unsupported; unknown/conflict is indeterminate.

`resolve_primary_listing(security_id, methodology_id, roles, selected_security_listing_relationships, query, identity_bundle, manifest, decision, policy, retained_evidence) -> PrimaryListingResolutionV1` requires one active primary under one selected methodology. Its subject hash binds the security and methodology, and the role manifest/decision must be an identity-bundle member. Two primaries in one methodology fail validation. A role listing must have a selected `security_has_listing` relationship.

- [ ] **Step 7: Write failing lifecycle and termination tests**

```python
class ListingLifecycleEventKind(StrEnum):
    ADMITTED = "admitted"
    FIRST_REGULAR_TRADE = "first_regular_trade"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    VENUE_TRANSFER = "venue_transfer"


class ListingLifecycleVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    event_kind: ListingLifecycleEventKind
    effective_time: TemporalBoundaryClaimV1
    related_listing_id: UUID7 | None


class ListingTerminationReason(StrEnum):
    ACQUISITION = "acquisition"
    MERGER = "merger"
    BANKRUPTCY = "bankruptcy"
    EXCHANGE_DELISTING = "exchange_delisting"
    VOLUNTARY_WITHDRAWAL = "voluntary_withdrawal"
    VENUE_TRANSFER = "venue_transfer"
    REORGANIZATION = "reorganization"
    UNKNOWN = "unknown"


class OutcomeEvidenceStatus(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ListingTerminationVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    reason: ListingTerminationReason
    source_reason_code: NonBlankStr | None
    source_reason_text: NonBlankStr | None
    last_regular_trade_time: TemporalBoundaryClaimV1
    effective_time: TemporalBoundaryClaimV1
    successor_relationship_ids: tuple[UUID7, ...]
    outcome_evidence_status: OutcomeEvidenceStatus


class ListingHistoryCoverageVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    listing_id: UUID7
    coverage_status: ListingHistoryCoverageStatus
    complete_through: TemporalBoundaryClaimV1
```

Test pre-admission, admitted but not first-traded, active, suspended, resumed, terminated, bounded first/last trade, all termination families, unknown reason, and an observation-shaped input that cannot create termination. Require complete listing-history coverage through E before absence of termination means not terminated; partial, unknown, or short coverage yields indeterminate. Require `related_listing_id` only for transfer, require a different related listing under the same security, and require the matching sole termination record. Every `successor_relationship_id` must resolve to a selected `successor_of` or `reorganized_from` security relationship, never a listing transfer. Never add `terminated` to `ListingLifecycleEventKind`.

- [ ] **Step 8: Implement lifecycle validation and resolution**

```python
class ListingLifecycleStatus(StrEnum):
    NOT_YET_LISTED = "not_yet_listed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    INDETERMINATE = "indeterminate"


def resolve_listing_lifecycle(
    listing_id: UUID7,
    events: Sequence[ListingLifecycleVersionV1],
    termination: ListingTerminationResolutionV1,
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> ListingLifecycleResolutionV1: ...


def resolve_listing_termination(
    listing_id: UUID7,
    terminations: Sequence[ListingTerminationVersionV1],
    coverage: ListingHistoryCoverageResolutionV1,
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> ListingTerminationResolutionV1: ...


def resolve_listing_history_coverage(
    listing_id: UUID7,
    coverage_versions: Sequence[ListingHistoryCoverageVersionV1],
    query: NormalizedSelectionQueryV1,
    identity_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> ListingHistoryCoverageResolutionV1: ...
```

Resolve coverage first with a `listing_lifecycle` query. Run termination with a separate `listing_termination` query, then lifecycle with its event query; require matching subject, K, E, channel, policy, and bundle throughout. A selected termination yields terminated. No selected termination yields not-terminated only when selected coverage is complete through E; otherwise it is indeterminate. Only definitely effective first regular trade yields active. Admission alone is not-yet-listed or indeterminate. Suspension/resumption alternates causally. Missing records never imply termination.

- [ ] **Step 9: Create and hash-pin the listing fixture**

The six role-specific files contain the fixed ticker/transfer/reuse history, two share classes, two simultaneous listings, a primary-methodology conflict, every termination family, one unknown reason, and complete/partial/unknown coverage examples. Each has its own schema/manifest and pinned SHA-256. They contain no prices, bars, payout, share ratio, cash, return, or schedule.

Build identity bundle version `2` from the unchanged Task 2 members plus these six role manifests and passing decisions. Version `1` remains replayable and is never rewritten.

- [ ] **Step 10: Run focused and full gates**

Run: `uv run pytest tests/unit/test_listing_semantics.py tests/integration/test_m1b_identity_history.py -v`

Then run the full gate. Expected: all pass; ticker/listing are not identity shortcuts; termination has no economic result.

- [ ] **Step 11: Commit listing semantics**

```bash
git add src/drift/domain/securities.py src/drift/markets/identity.py src/drift/markets/validation.py tests/unit/test_listing_semantics.py tests/integration/test_m1b_identity_history.py tests/fixtures/datasets/m1b/external-identifiers.json tests/fixtures/datasets/m1b/security-classifications.json tests/fixtures/datasets/m1b/listing-roles.json tests/fixtures/datasets/m1b/listing-lifecycle.json tests/fixtures/datasets/m1b/listing-terminations.json tests/fixtures/datasets/m1b/listing-history-coverage.json
git commit -m "feat: add historical listing semantics"
```

---

### Task 4: Add Historical Universes and Structural Eligibility

**Files:**
- Create: `src/drift/domain/universes.py`
- Create: `src/drift/markets/universes.py`
- Modify: `src/drift/markets/validation.py`
- Test: `tests/unit/test_universes.py`
- Test: `tests/integration/test_m1b_universe_leakage.py`
- Fixture: `tests/fixtures/datasets/m1b/source-universe-definitions.json`
- Fixture: `tests/fixtures/datasets/m1b/universe-memberships.json`

**Interfaces:**
- Consumes: selected identity, classification, primary listing, lifecycle, termination, and Task 1 proof/reference results.
- Produces: universe records, `resolve_universe_membership`, and `resolve_structural_eligibility`.

```python
class UniverseMembershipResolutionV1(FrozenModel):
    schema_version: Literal["1"]
    universe_id: UUID7
    universe_version: NonBlankStr
    target_level: UniverseTargetLevel
    target_id: UUID7
    status: MembershipStatus
    known_upcoming_effects: tuple[MembershipEffect, ...]
    reasons: tuple[NonBlankStr, ...]
    evidence: ResolutionEvidenceV1
```

- [ ] **Step 1: Write failing definition and target-level tests**

```python
class UniverseTargetLevel(StrEnum):
    SECURITY = "security"
    LISTING = "listing"


class SourceUniverseKind(StrEnum):
    INDEX = "index"
    PROVIDER_COVERAGE = "provider_coverage"


class ResearchUniverseDefinitionV1(FrozenModel):
    schema_version: Literal["1"]
    universe_id: UUID7
    universe_version: NonBlankStr
    universe_kind: Literal["structural"]
    target_level: UniverseTargetLevel
    methodology_reference: ArtifactReference
    methodology_hash: SHA256Hash
    identity_bundle_hash: SHA256Hash
    classification_contract_hash: SHA256Hash
    created_at: UTCDateTime


class SourceUniverseDefinitionVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    universe_id: UUID7
    universe_version: NonBlankStr
    universe_kind: SourceUniverseKind
    target_level: UniverseTargetLevel
    methodology_reference: ArtifactReference
    methodology_hash: SHA256Hash
    identity_bundle_hash: SHA256Hash
    effective_interval: TemporalIntervalClaimV1
```

Require safe methodology references whose content hash equals `methodology_hash`. One version has one target level. Issuer and mixed-level definitions fail. The initial structural fixture targets listing; the generic source contract may target security or listing.

- [ ] **Step 2: Verify definition tests are RED**

Run: `uv run pytest tests/unit/test_universes.py -k "definition or target" -v`

Expected: collection FAIL because universe contracts do not exist.

- [ ] **Step 3: Implement definitions without strategy screens**

Do not add price, volume, market-cap, liquidity, factor, feature, or rank fields. `classification_contract_hash` identifies the exact strict-scope mapping policy; changing the policy changes definition identity.

- [ ] **Step 4: Write failing membership timing and correction tests**

```python
class MembershipEffect(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


class UniverseMembershipVersionV1(FrozenModel):
    schema_version: Literal["1"]
    revision: RevisionEnvelopeV1
    universe_id: UUID7
    universe_version: NonBlankStr
    target_level: UniverseTargetLevel
    target_id: UUID7
    membership_effect: MembershipEffect
    effective_time: TemporalBoundaryClaimV1
    source_event_id: NonBlankStr


class MembershipStatus(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    INDETERMINATE = "indeterminate"
```

Test a synthetic addition available on 2020-05-20 and effective 2020-06-01: it is known upcoming on May 25 but not current membership; it is included June 1. Test later exclusion, correction of announcement evidence, correction of effective boundary, and withdrawal of a bad assertion. `revision_kind=withdrawal` is never a membership exclusion.

- [ ] **Step 5: Implement membership resolution with separate K and E**

```python
def resolve_universe_membership(
    definition: ResearchUniverseDefinitionV1 | SourceUniverseDefinitionVersionV1,
    target_level: UniverseTargetLevel,
    target_id: UUID7,
    memberships: Sequence[UniverseMembershipVersionV1],
    query: NormalizedSelectionQueryV1,
    universe_bundle: ValidatedDatasetBundleV1,
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
    policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> UniverseMembershipResolutionV1: ...
```

First select causally available assertions by K, then evaluate business effect at E. A current snapshot without historical events is indeterminate for an earlier period. Target mismatch is a validation error.

- [ ] **Step 6: Write failing structural-eligibility tests**

```python
class StructuralEligibilityClassification(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class StructuralEligibilityResultV1(FrozenModel):
    schema_version: Literal["1"]
    listing_id: UUID7
    security_id: UUID7
    classification: StructuralEligibilityClassification
    reasons: tuple[NonBlankStr, ...]
    knowledge_cutoff: UTCDateTime
    evaluation_time: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    identity_bundle_hash: SHA256Hash
    universe_bundle_hash: SHA256Hash
    identity_assignment_resolution_hashes: tuple[SHA256Hash, ...]
    identity_resolution_hash: SHA256Hash
    classification_resolution_hash: SHA256Hash
    primary_listing_resolution_hash: SHA256Hash
    lifecycle_resolution_hash: SHA256Hash
    membership_resolution_hash: SHA256Hash
    selection_proof_hashes: tuple[SHA256Hash, ...]
```

Strict eligibility requires resolved issuer-security-listing links; operating-company/common-share/domestic classification; XNYS/XNAS/XASE venue; exactly one primary under the selected methodology; definitely effective first trade; complete lifecycle/termination coverage through E; no effective suspension/termination; and effective inclusion in the listing-target structural universe.

Explicit exclusion is ineligible. Missing, unknown, bounded-at-E, conflicting, or unavailable evidence is indeterminate. Both fail admission, but remain distinct.

- [ ] **Step 7: Implement structural eligibility as pure composition**

Implement this exact composition boundary:

```python
def resolve_structural_eligibility(
    definition: ResearchUniverseDefinitionV1,
    listing: ListingV1,
    security_id: UUID7,
    identity_assignments: tuple[IdentityAssignmentResolutionResultV1, ...],
    identity: IdentityResolutionResultV1,
    classification: SecurityClassificationResolutionV1,
    primary_listing: PrimaryListingResolutionV1,
    lifecycle: ListingLifecycleResolutionV1,
    membership: UniverseMembershipResolutionV1,
    query: NormalizedSelectionQueryV1,
) -> StructuralEligibilityResultV1: ...
```

The assignment tuple must prove exactly one issuer, the named security, and the named listing under matching query context. The function operates on already validated exact results. It must not read manifests, fetch records, infer sessions, inspect observations, or calculate tradability. Reject mismatched K, E, channel, policy, manifest, target, and proof purpose.

- [ ] **Step 8: Create and hash-pin the universe fixture**

The source-definition and membership files have separate roles/manifests and together cover:

| Fixture | Required result |
| --- | --- |
| New listing | Not eligible before first trade; eligible only after membership effect. |
| Explicit exclusions | Fund/ETF-like, REIT, acquisition company/SPAC-like, receipt/ADR-like, preferred, unit, warrant, right, foreign, and other fail strict eligibility. |
| Unknown classification | Indeterminate and not admitted. |
| Synthetic index | Addition/removal each separate announcement availability from effect. |
| Current snapshot leakage | Modern constituents cannot prove 2020 membership. |
| Delisted retention | Historically eligible listing remains resolvable after later termination/removal. |
| Membership correction | Old manifest reproduces old interpretation; new manifest selects the correction. |
| Target mismatch | Security ID cannot enter the listing-target structural universe. |

Use no actual index name, real constituent, or market observation.

Build universe bundle version `1` from the passing source-definition and membership manifests/decisions. The research structural definition binds identity bundle version `2` and the universe bundle hash.

- [ ] **Step 9: Run focused and full gates**

Run: `uv run pytest tests/unit/test_universes.py tests/integration/test_m1b_universe_leakage.py -v`

Then run the full gate. Expected: all pass; leakage, survivorship deletion, unknown-as-eligible, and early membership fail mechanically.

- [ ] **Step 10: Commit historical universe semantics**

```bash
git add src/drift/domain/universes.py src/drift/markets/universes.py src/drift/markets/validation.py tests/unit/test_universes.py tests/integration/test_m1b_universe_leakage.py tests/fixtures/datasets/m1b/source-universe-definitions.json tests/fixtures/datasets/m1b/universe-memberships.json
git commit -m "feat: add point-in-time research universes"
```

---

### Task 5: Adversarial Hardening, Compatibility, and Lifecycle Documentation

**Files:**
- Modify: `tests/integration/test_m1b_identity_history.py`
- Modify: `tests/integration/test_m1b_universe_leakage.py`
- Modify: `tests/integration/test_m1b_m1a_compatibility.py`
- Modify: `tests/unit/test_security_identity.py`
- Modify: `tests/unit/test_listing_semantics.py`
- Modify: `tests/unit/test_universes.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/architecture/roadmap.md`
- Modify: `docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md`

**Interfaces:**
- Consumes: all M1b results.
- Produces: closed adversarial evidence and canonical lifecycle status. No new runtime capability.

- [ ] **Step 1: Complete the adversarial review matrix**

Add or confirm one named test for every row:

| Attempted cheat | Mechanical defense |
| --- | --- |
| Join by today's ticker | Historical mapping selects the period-specific listing. |
| Treat ticker change as new security | Same security/listing persist across OLD to NEW. |
| Collapse ticker reuse | OLD maps to a distinct later listing/security. |
| Collapse issuer/share class | Kind-safe endpoints reject it. |
| Collapse two classes | One issuer retains two securities. |
| Timeless primary | Query selects methodology and E; overlap fails. |
| Rewrite correction | Old manifest/result remain reproducible. |
| Pick arbitrary equivalent ID | Resolver returns sorted equivalence set. |
| Apply current constituents historically | Earlier query is indeterminate. |
| Add member at announcement | Upcoming is known but not effective. |
| Drop terminated firm | Earlier listing/membership remain resolvable. |
| Unknown classification is eligible | Result is indeterminate and admission fails. |
| Mix target levels | Validation fails. |
| Infer termination from bar absence | No M1b API accepts observation absence. |
| Treat missing termination row as proof of activity | Complete listing-history coverage through E is required. |
| Store economic outcome in termination | Cash, ratio, payout, return, and value fields fail `extra="forbid"`. |
| Inject considered/future records | Selected-record resolver rejects every extra hash. |

- [ ] **Step 2: Keep invariant testing dependency-free**

Do not add Hypothesis. These invariants use finite enums, an endpoint matrix, causal chains, and boundary partitions with deterministic oracles. Use `itertools.product` to exhaust relationship-kind/endpoint-kind triples and strict classification combinations. Keep example histories for temporal graph behavior. Reconsider a dependency only if implementation exposes a stronger generator-friendly invariant not covered by exhaustive tables.

- [ ] **Step 3: Run scope and forbidden-capability checks**

```text
git diff 6086a1f -- pyproject.toml uv.lock
rg -n -i "robinhood|alpaca|broker|place_order|submit_order|oauth|api[_-]?key|secret|websocket|httpx|requests" src tests pyproject.toml
rg -n -i "price|ohlc|dividend|split|cash consideration|terminal return|portfolio|backtest|calendar|session" src/drift/domain/assertions.py src/drift/domain/securities.py src/drift/domain/universes.py src/drift/markets
```

Expected: dependency diff empty. Inspect every search hit. Only negative tests, scope comments, ex-post role vocabulary, and outcome-evidence status are allowed.

- [ ] **Step 4: Prove M0/M1a compatibility**

```text
uv run pytest tests/integration/test_m1b_m1a_compatibility.py tests/integration/test_m1_m0_compatibility.py tests/integration/test_replay.py tests/integration/test_tamper_detection.py -v
uv run pytest tests/unit/test_canonical_serialization.py tests/unit/test_manifests.py tests/unit/test_dataset_validation.py tests/unit/test_revisions.py tests/unit/test_temporal.py -v
```

Expected: all pinned bytes, hashes, decisions, dataset events, and replay tests pass unchanged.

- [ ] **Step 5: Update canonical documentation**

Only after gates pass, update README/overview to say M1b supplies synthetic identity/universe semantics and M1c still blocks observations/backtesting; update AGENTS.md boundaries; mark M1b complete in the roadmap at its commit; retain M1c as designed/not started with no plan; record commit hashes and verification in this plan. Do not create a session-continuity database.

- [ ] **Step 6: Run the final completion gate**

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
rg -n "T[B]D|T[O]DO|implement l[a]ter|fill in d[e]tails|Similar to T[a]sk" docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md
rg -n $'\u2014' AGENTS.md README.md src tests docs
git diff --check
git status -sb
```

Expected: all code gates pass; placeholder and U+2014 scans have no matches; diff check is clean; only M1b files plus unrelated `.DS_Store` appear before commit.

- [ ] **Step 7: Perform a final requirements review**

Read umbrella sections 210-642, 849-978, 1076-1144, 1216-1273, and 1338-1401 plus every plan item. Record PASS/FAIL for identity, correction, mapping, classification, primary role, lifecycle, termination, universe, selection boundary, compatibility, scope, and docs. Fix each FAIL before committing.

- [ ] **Step 8: Commit hardening and lifecycle docs**

```bash
git add AGENTS.md README.md docs/architecture/overview.md docs/architecture/roadmap.md docs/superpowers/plans/2026-09-03-m1b-historical-security-identity-universes.md tests/integration/test_m1b_identity_history.py tests/integration/test_m1b_universe_leakage.py tests/integration/test_m1b_m1a_compatibility.py tests/unit/test_security_identity.py tests/unit/test_listing_semantics.py tests/unit/test_universes.py
git commit -m "docs: complete M1b identity milestone"
```

- [ ] **Step 9: Run Checkpoint**

Verify Git status/log/diff and the full gate against the final commit. Do not create a Session Handoff if repository and plan are canonical. Do not create an M1c plan.

## Completion Criteria

M1b is complete only when every box above is checked and fresh evidence proves:

- identity assignment/correction is immutable, validated, manifest-pinned, and replayable;
- issuer, security, and listing stay distinct under ticker change/reuse, classes, and transfers;
- equivalence returns a deterministic set and conflict never picks a winner;
- mapping, classification, primary role, lifecycle, termination, and membership resolve separately by K and E;
- activity begins only after definitely effective first regular trade;
- active status requires explicit complete lifecycle/termination coverage through E;
- termination is authoritative only from `ListingTerminationVersionV1` and has no economic result;
- listing-target structural eligibility fails closed on excluded, unknown, or conflicting classification;
- synthetic index timing, current-state leakage, and delisted-retention tests pass;
- audit proofs retain considered hashes while decision resolution exposes only selected hashes;
- V2 validates exact objects without changing M0/M1a bytes, hashes, events, or replay;
- no M1c, evaluator, provider, network, broker, credential, or trading capability exists;
- the full gate passes and the tree is clean except for pre-existing `.DS_Store`.

## Implementation Commit Sequence

1. `feat: add assertion temporal dataset contracts`
2. `feat: add immutable historical security identity`
3. `feat: add historical listing semantics`
4. `feat: add point-in-time research universes`
5. `docs: complete M1b identity milestone`

These are implementation-time commits. This planning document's commit does not count as M1b implementation.

## Explicit M1c and Later Deferrals

No task may add source/raw/normalized prices; actions or economic outcomes; cash payouts or returns; sessions/calendars/bars/missingness/tradability; evaluator screens/features; portfolio/backtest/risk/execution; providers/APIs/networks/credentials/databases; or an executable M1c plan.

## Resume Rule

At each implementation session run Resume first. Repository state wins. Confirm `6086a1f`, locate the first unchecked task, inspect uncommitted files, and continue only there. Checkpoint after each accepted commit. Never store development continuity in Drift's scientific ledger or a duplicate continuity database.
