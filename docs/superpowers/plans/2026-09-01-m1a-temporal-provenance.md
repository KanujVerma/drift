# Drift M1a Temporal Provenance Implementation Plan

**Status:** Active and not started. This is the only executable M1 plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add asset-neutral, immutable dataset and revision provenance that answers a channel-, policy-, and cutoff-specific point-in-time eligibility question without inventing temporal precision.

**Architecture:** M1a adds explicit record-level availability evidence, immutable fact revisions, storage-neutral content manifests, confined fixture-byte verification, and immutable validation decisions tied to exact bytes. Query functions return a tri-state result for one channel, policy, and cutoff. Existing M0 persisted models remain unchanged, and no dataset-wide availability default or historical-evaluation permission is created.

**Tech Stack:** Python 3.14, Pydantic 2, Python standard library, existing Drift canonical JSON and audit ledger, deterministic table-driven pytest, Ruff, mypy

**Spec:** `docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md`

## Global Constraints

- Read the umbrella spec, ADR 0005, the M0 plan, and current domain contracts before execution.
- Implement only asset-neutral M1a. M1b remains deferred in `docs/superpowers/plans/2026-09-01-m1b-historical-market-semantics.md`.
- Do not modify fields, defaults, validators, serialization, or hash behavior of existing M0 persisted models.
- Python remains `>=3.14`; Pydantic remains the sole runtime dependency. Do not add Hypothesis or any other dependency.
- Use deterministic, table-driven pytest cases for temporal and revision state spaces.
- Add no provider adapter, download, network client, credential, broker, order, backtester, evaluator, feature system, model training, calendar library, security master, object store, or executable transformation pipeline.
- Keep exact data bytes outside SQLite. Ledger events contain only compact hashes, IDs, schema versions, and references.
- Every synthetic observation and revision carries explicit availability evidence. M1a has no dataset- or partition-level availability defaults.
- Unknown or insufficient evidence remains indeterminate. It is never converted to an exact instant or an eligible result.
- New manifests use existing canonical JSON and SHA-256 under hash profile `drift-canonical-json-sha256-v1`.
- All actual instants are timezone-aware and normalize to UTC. Naive datetimes fail validation.
- All production code is test-driven. Run each named failing test before its implementation.
- Use no U+2014 em dash in source, tests, fixtures, or documentation.

## Implementation Review Rulings

These rulings narrow details in the umbrella design without discarding its research:

1. Availability has three evidence shapes: `exact`, `bounded`, and `unknown`. `rule_derived` is a provenance basis on an exact or bounded result, not a fourth mutually exclusive shape. A rule-derived result retains the rule hash, version, and input hashes.
2. M1a implements no dataset- or partition-level availability default. There is no real uniform source contract to justify one yet. A later adapter may propose defaults only with source evidence and a separate design review.
3. M1a creates no durable dataset-wide `historical_evaluation_eligible` label, promotion binding, or permission artifact. It records immutable validation facts and returns `eligible`, `ineligible`, or `indeterminate` for a specific channel, policy, and cutoff. A later evaluator decides what evidence its use requires.
4. Tests are deterministic pytest tables. Hypothesis is not justified because the closed shape, cutoff, channel, policy, and revision cases can be enumerated directly without expanding the dependency surface.

The first ruling follows the evidence distinction already captured in the umbrella design. ALFRED real-time periods establish that vintages and intervals matter, Qlib establishes selection by revision availability rather than latest value, and the SEC warning that it does not record first-public time shows why rule provenance cannot manufacture an exact observed timestamp. The second and third rulings prevent coarse metadata from becoming false point-in-time confidence.

## File Map

| File | Responsibility |
|---|---|
| `src/drift/domain/temporal.py` | Valid periods, channels, evidence shapes and bases, policies, tri-state cutoff decisions |
| `src/drift/domain/manifests.py` | Asset-neutral source, acquisition, license, schema, partition, lineage, and manifest models |
| `src/drift/domain/revisions.py` | Immutable fact versions and per-cutoff revision selection results |
| `src/drift/domain/dataset_validation.py` | Typed findings and immutable exact-object validation decisions |
| `src/drift/datasets/__init__.py` | Dataset contract package marker |
| `src/drift/datasets/hashing.py` | Canonical manifest and fact payload hashing |
| `src/drift/datasets/resolver.py` | Confined local fixture resolver that returns verified bytes |
| `src/drift/datasets/validation.py` | Manifest, lineage, revision, and synthetic-record validation |
| `src/drift/datasets/references.py` | Additive provenance-only bridge to existing `DatasetReference` |
| `src/drift/datasets/events.py` | Compact audit-event factories for manifest and validation evidence |
| `tests/fixtures/datasets/m1a/*.json` | Small adversarial fact-version fixture bytes |
| `tests/unit/test_temporal.py` | Deterministic availability shape, policy, channel, and cutoff table |
| `tests/unit/test_manifests.py` | Manifest strictness, lineage, ordering, and hash tests |
| `tests/unit/test_dataset_resolver.py` | Path, file kind, size, mutation, and byte-hash tests |
| `tests/unit/test_revisions.py` | Deterministic revision chain and selection table |
| `tests/unit/test_dataset_validation.py` | Exact-byte validation decision and M0 bridge tests |
| `tests/integration/test_m1a_leakage.py` | Adversarial late, revised, bounded, unknown, and channel cases |
| `tests/integration/test_m1_dataset_audit.py` | Manifest and validation event append, replay, and tamper tests |
| `tests/integration/test_m1_m0_compatibility.py` | Pinned M0 serialization, event hash, and replay regression tests |

---

### Task 1: Temporal Evidence and Per-Query Eligibility

**Files:**
- Create: `src/drift/domain/temporal.py`
- Test: `tests/unit/test_temporal.py`

**Interfaces:**
- Consumes: `ArtifactReference`, `FrozenModel`, `NonBlankStr`, `SHA256Hash`, `UTCDateTime`, and existing `content_hash`.
- Produces: `ValidPeriodV1`, `ChannelKind`, `AvailabilityShape`, `AvailabilityBasis`, `SourcePrecision`, `CutoffEligibility`, `AvailabilityChannelV1`, `RuleDerivationV1`, `AvailabilityEvidenceV1`, `AvailabilityPolicyV1`, `CutoffEligibilityResultV1`, and `evaluate_availability(evidence, channel, policy, cutoff) -> CutoffEligibilityResultV1`.

- [ ] **Step 1: Write the deterministic failing availability table**

```python
@pytest.mark.parametrize(
    ("case", "cutoff", "requested_channel", "policy", "expected"),
    (
        ("exact", utc(2022, 5, 5, 19, 59), PUBLIC, STRICT, CutoffEligibility.INELIGIBLE),
        ("exact", utc(2022, 5, 5, 20, 0), PUBLIC, STRICT, CutoffEligibility.ELIGIBLE),
        ("bounded", utc(2022, 5, 5, 0), PUBLIC, STRICT, CutoffEligibility.INDETERMINATE),
        ("bounded", utc(2022, 5, 6, 0), PUBLIC, STRICT, CutoffEligibility.ELIGIBLE),
        ("unknown", utc(2030, 1, 1), PUBLIC, STRICT, CutoffEligibility.INDETERMINATE),
        ("exact", utc(2022, 5, 6), VENDOR, STRICT, CutoffEligibility.INDETERMINATE),
        ("rule_exact", utc(2022, 5, 6), PUBLIC, STRICT, CutoffEligibility.INELIGIBLE),
        ("rule_exact", utc(2022, 5, 6), PUBLIC, RULE_ALLOWED, CutoffEligibility.ELIGIBLE),
    ),
)
def test_cutoff_eligibility_table(
    case: str,
    cutoff: datetime,
    requested_channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    expected: CutoffEligibility,
) -> None:
    result = evaluate_availability(EVIDENCE[case], requested_channel, policy, cutoff)
    assert result.classification is expected
```

Add separate validation cases for a naive cutoff, reversed bounds, equal bounded bounds, exact unequal bounds, unknown with bounds, date precision without an IANA timezone, rule basis without rule metadata, non-rule basis with rule metadata, empty rule inputs, and duplicate policy rule hashes.

- [ ] **Step 2: Run the test and verify the module is absent**

Run: `uv run pytest tests/unit/test_temporal.py -v`

Expected: collection fails because `drift.domain.temporal` does not exist.

- [ ] **Step 3: Implement the strict evidence models**

```python
class AvailabilityShape(StrEnum):
    EXACT = "exact"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class AvailabilityBasis(StrEnum):
    SOURCE_OBSERVED = "source_observed"
    VENDOR_DELIVERY = "vendor_delivery"
    LOCAL_INGEST = "local_ingest"
    RULE_DERIVED = "rule_derived"


class CutoffEligibility(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class ChannelKind(StrEnum):
    PUBLIC = "public"
    VENDOR = "vendor"
    SYSTEM = "system"


class SourcePrecision(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    DATE = "date"
    INTERVAL = "interval"
    SESSION = "session"
    UNKNOWN = "unknown"


class AvailabilityChannelV1(FrozenModel):
    kind: ChannelKind
    identifier: NonBlankStr
    version: NonBlankStr | None = None


class RuleDerivationV1(FrozenModel):
    rule_hash: SHA256Hash
    rule_version: NonBlankStr
    input_hashes: tuple[SHA256Hash, ...]


class AvailabilityEvidenceV1(FrozenModel):
    channel: AvailabilityChannelV1
    shape: AvailabilityShape
    lower_bound: UTCDateTime | None = None
    upper_bound: UTCDateTime | None = None
    precision: SourcePrecision
    source_timezone: NonBlankStr | None = None
    basis: AvailabilityBasis
    evidence_reference: ArtifactReference | None = None
    rule_derivation: RuleDerivationV1 | None = None


class AvailabilityPolicyV1(FrozenModel):
    policy_id: NonBlankStr
    permitted_rule_hashes: tuple[SHA256Hash, ...] = ()


class CutoffEligibilityResultV1(FrozenModel):
    classification: CutoffEligibility
    reason: NonBlankStr
    evidence_hash: SHA256Hash
```

Use a model validator with these exact invariants: exact requires two equal bounds; bounded requires two bounds with `lower_bound < upper_bound`; unknown requires neither bound; date and session precision require a valid `zoneinfo.ZoneInfo`; rule-derived basis requires nonempty, unique input hashes and `RuleDerivationV1`; every other basis forbids it. `ValidPeriodV1` is nonempty and half-open. `AvailabilityPolicyV1` contains `policy_id` and unique `permitted_rule_hashes`; it contains no timestamp default.

- [ ] **Step 4: Implement tri-state cutoff evaluation**

```python
def evaluate_availability(
    evidence: AvailabilityEvidenceV1,
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
) -> CutoffEligibilityResultV1:
    cutoff_utc = _normalize_utc(cutoff)
    digest = content_hash(evidence)
    if evidence.channel != channel:
        return CutoffEligibilityResultV1(
            classification=CutoffEligibility.INDETERMINATE,
            reason="no_evidence_for_requested_channel",
            evidence_hash=digest,
        )
    if evidence.shape is AvailabilityShape.UNKNOWN:
        return CutoffEligibilityResultV1(
            classification=CutoffEligibility.INDETERMINATE,
            reason="availability_unknown",
            evidence_hash=digest,
        )
    if evidence.basis is AvailabilityBasis.RULE_DERIVED:
        assert evidence.rule_derivation is not None
        if evidence.rule_derivation.rule_hash not in policy.permitted_rule_hashes:
            return CutoffEligibilityResultV1(
                classification=CutoffEligibility.INELIGIBLE,
                reason="rule_not_permitted_by_policy",
                evidence_hash=digest,
            )
    assert evidence.lower_bound is not None and evidence.upper_bound is not None
    if evidence.upper_bound <= cutoff_utc:
        classification = CutoffEligibility.ELIGIBLE
        reason = "available_by_cutoff"
    elif evidence.lower_bound > cutoff_utc:
        classification = CutoffEligibility.INELIGIBLE
        reason = "not_available_by_cutoff"
    else:
        classification = CutoffEligibility.INDETERMINATE
        reason = "cutoff_inside_availability_window"
    return CutoffEligibilityResultV1(
        classification=classification,
        reason=reason,
        evidence_hash=digest,
    )
```

- [ ] **Step 5: Run temporal tests, lint, and type checks**

Run: `uv run pytest tests/unit/test_temporal.py -v && uv run ruff check src/drift/domain/temporal.py tests/unit/test_temporal.py && uv run mypy src/drift/domain/temporal.py tests/unit/test_temporal.py`

Expected: all commands exit 0.

- [ ] **Step 6: Commit temporal primitives**

```text
git add src/drift/domain/temporal.py tests/unit/test_temporal.py
git commit -m "feat: add point-in-time availability evidence"
```

### Task 2: Asset-Neutral Immutable Manifests

**Files:**
- Create: `src/drift/domain/manifests.py`
- Create: `src/drift/datasets/__init__.py`
- Create: `src/drift/datasets/hashing.py`
- Test: `tests/unit/test_manifests.py`

**Interfaces:**
- Consumes: M0 `ArtifactReference`, `TemporalCoverage`, common validated types, Task 1 `AvailabilityChannelV1`, and canonical serialization functions.
- Produces: `DatasetKind`, `LogicalType`, `EvidenceGranularity`, `DeterminismClaim`, `SourceDescriptorV1`, `AcquisitionDescriptorV1`, `LicenseDescriptorV1`, `FieldDescriptorV1`, `SchemaDescriptorV1`, `PartitionDescriptorV1`, `RecordTemporalContractV1`, `LineageDescriptorV1`, `DatasetManifestV1`, `manifest_body(manifest) -> dict[str, JSONValue]`, `manifest_hash(manifest) -> str`, and `derived_temporal_coverage(partitions) -> TemporalCoverage`.

- [ ] **Step 1: Write failing manifest and canonical hash tests**

```python
@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ({"manifest_schema_version": "2"}, "manifest_schema_version"),
        ({"partitions": ()}, "partitions"),
        ({"temporal_contract": contract(availability_field_id="missing")}, "field"),
        ({"lineage": None, "dataset_kind": DatasetKind.DERIVED_FACTS}, "lineage"),
    ),
)
def test_manifest_rejects_invalid_contracts(
    mutation: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        manifest(**mutation)


def test_manifest_hash_sorts_partitions_by_key_and_content_hash() -> None:
    first = partition("year=2021", "a" * 64)
    second = partition("year=2022", "b" * 64)
    assert manifest_hash(manifest(partitions=(first, second))) == manifest_hash(
        manifest(partitions=(second, first))
    )


def test_no_availability_default_exists_on_manifest_or_partition() -> None:
    assert "availability" not in DatasetManifestV1.model_fields
    assert "availability" not in PartitionDescriptorV1.model_fields
```

Also test duplicate field IDs/names, duplicate partition IDs/keys, schema-hash mismatch, reversed coverage, raw data with lineage, derived data without lineage, duplicate lineage inputs, mismatched lineage output schema, naive acquisition/creation/execution times, source locators containing credentials, and unknown license rights remaining representable.

- [ ] **Step 2: Run tests and verify the models are absent**

Run: `uv run pytest tests/unit/test_manifests.py -v`

Expected: collection fails on missing manifest types.

- [ ] **Step 3: Implement focused descriptors with no market semantics**

```python
class DatasetKind(StrEnum):
    SOURCE_FACTS = "source_facts"
    DERIVED_FACTS = "derived_facts"


class PartitionDescriptorV1(FrozenModel):
    partition_id: UUID7
    partition_key: NonBlankStr
    artifact: ArtifactReference
    byte_size: Annotated[int, Field(ge=0)]
    media_type: NonBlankStr
    format_version: NonBlankStr
    row_count: Annotated[int, Field(ge=0)]
    schema_hash: SHA256Hash
    coverage: TemporalCoverage


class RecordTemporalContractV1(FrozenModel):
    contract_version: Literal["1"] = "1"
    evidence_granularity: Literal[EvidenceGranularity.RECORD] = (
        EvidenceGranularity.RECORD
    )
    logical_key_field_ids: tuple[NonBlankStr, ...]
    valid_start_field_id: NonBlankStr
    valid_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    revision_id_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr
    source_sequence_field_id: NonBlankStr
    value_field_id: NonBlankStr
    null_reason_field_id: NonBlankStr
    declared_channels: tuple[AvailabilityChannelV1, ...]


class LineageDescriptorV1(FrozenModel):
    input_manifest_hashes: tuple[SHA256Hash, ...]
    transformation_reference: ArtifactReference
    configuration_hash: SHA256Hash
    implementation_reference: ArtifactReference
    environment_hash: SHA256Hash
    output_schema_hash: SHA256Hash
    executed_at: UTCDateTime
    determinism: DeterminismClaim


class DatasetManifestV1(FrozenModel):
    manifest_schema_version: Literal["1"] = "1"
    hash_profile: Literal["drift-canonical-json-sha256-v1"] = (
        "drift-canonical-json-sha256-v1"
    )
    dataset_id: UUID7
    dataset_version: NonBlankStr
    dataset_kind: DatasetKind
    created_at: UTCDateTime
    source: SourceDescriptorV1
    acquisition: AcquisitionDescriptorV1
    license: LicenseDescriptorV1
    schema_definition: SchemaDescriptorV1
    partitions: tuple[PartitionDescriptorV1, ...]
    temporal_contract: RecordTemporalContractV1
    lineage: LineageDescriptorV1 | None = None
```

`SourceDescriptorV1` records source ID, publisher, product, optional source version, and a retained evidence reference, never credentials. `AcquisitionDescriptorV1` records `acquired_at`, collector ID/version, and acquisition evidence. `LicenseDescriptorV1` records provider legal name, agreement ID/version, terms reference, acquired time, and closed `allowed`, `restricted`, or `unknown` values for research use, redistribution, derived use, and retention. It is provenance, not a legal rules engine.

Use these exact descriptor fields:

```python
class SourceDescriptorV1(FrozenModel):
    source_id: NonBlankStr
    publisher: NonBlankStr
    product: NonBlankStr
    source_version: NonBlankStr | None = None
    evidence_reference: ArtifactReference


class AcquisitionDescriptorV1(FrozenModel):
    acquired_at: UTCDateTime
    collector_id: NonBlankStr
    collector_version: NonBlankStr
    evidence_reference: ArtifactReference


class LicenseDescriptorV1(FrozenModel):
    provider_legal_name: NonBlankStr
    agreement_id: NonBlankStr
    agreement_version: NonBlankStr | None = None
    terms_reference: ArtifactReference
    acquired_at: UTCDateTime
    research_use: RightsStatus
    redistribution: RightsStatus
    derived_use: RightsStatus
    retention: RightsStatus


class FieldDescriptorV1(FrozenModel):
    field_id: NonBlankStr
    name: NonBlankStr
    logical_type: LogicalType
    nullable: bool
    unit: NonBlankStr | None = None


class SchemaDescriptorV1(FrozenModel):
    schema_version: NonBlankStr
    fields: tuple[FieldDescriptorV1, ...]
    schema_hash: SHA256Hash
```

`SchemaDescriptorV1` has a version, ordered nonempty `FieldDescriptorV1` tuple, and schema hash. Fields use a small closed logical-type enum and stable IDs. The temporal contract binds only existing field IDs, declares record evidence, and has no default evidence or cutoff policy. Require nonempty, unique declared channels because every record must carry evidence for each channel the dataset claims to support.

- [ ] **Step 4: Implement canonical ordering and hashing**

```python
def manifest_body(manifest: DatasetManifestV1) -> dict[str, JSONValue]:
    body = canonical_data(manifest)
    assert isinstance(body, dict)
    partitions = body["partitions"]
    assert isinstance(partitions, list)
    body["partitions"] = sorted(
        partitions,
        key=lambda item: canonical_json(
            [item["partition_key"], item["artifact"]["content_hash"]]
        ),
    )
    return body


def manifest_hash(manifest: DatasetManifestV1) -> str:
    return content_hash(manifest_body(manifest))
```

`derived_temporal_coverage` returns the minimum partition start and maximum partition end using M0's inclusive `TemporalCoverage`. Do not convert it to the half-open fact-validity contract.

- [ ] **Step 5: Run focused and M0 canonical tests**

Run: `uv run pytest tests/unit/test_manifests.py tests/unit/test_canonical_serialization.py tests/unit/test_hashing.py tests/unit/test_domain_models.py -v`

Expected: all tests pass and pinned M0 behavior is unchanged.

- [ ] **Step 6: Commit manifest contracts**

```text
git add src/drift/domain/manifests.py src/drift/datasets/__init__.py src/drift/datasets/hashing.py tests/unit/test_manifests.py
git commit -m "feat: add immutable dataset manifests"
```

### Task 3: Confined Local Fixture Resolution

**Files:**
- Create: `src/drift/datasets/resolver.py`
- Test: `tests/unit/test_dataset_resolver.py`

**Interfaces:**
- Consumes: `SHA256Hash` and `PartitionDescriptorV1`.
- Produces: `ResolverLimits`, `VerifiedArtifactBytes`, `read_verified_local_artifact(root, relative_path, expected_hash, limits) -> VerifiedArtifactBytes`, and `verify_partition_bytes(partition, verified) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing path, file-kind, size, mutation, and mismatch tests**

```python
@pytest.mark.parametrize("relative", ("../secret.json", "/tmp/secret.json", "a/../../b"))
def test_resolver_rejects_unconfined_paths(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ArtifactResolutionError, match="confined"):
        read_verified_local_artifact(tmp_path, relative, "0" * 64, LIMITS)


def test_resolver_rejects_hash_mismatch(tmp_path: Path) -> None:
    (tmp_path / "data.json").write_bytes(b"{}")
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        read_verified_local_artifact(tmp_path, "data.json", "0" * 64, LIMITS)


def test_parser_keeps_verified_bytes_after_path_replacement(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    original = b'{"value":1}'
    path.write_bytes(original)
    verified = read_verified_local_artifact(
        tmp_path, path.name, sha256(original).hexdigest(), LIMITS
    )
    path.write_bytes(b'{"value":9}')
    assert verified.data == original
```

Add deterministic cases for NULs, symlink path components, symlink escape, FIFO or other nonregular file, missing file, file above `max_bytes`, declared partition size mismatch, and partition hash mismatch.

- [ ] **Step 2: Run the test and verify resolver imports fail**

Run: `uv run pytest tests/unit/test_dataset_resolver.py -v`

Expected: collection fails because the resolver does not exist.

- [ ] **Step 3: Implement bounded regular-file byte reads**

```python
@dataclass(frozen=True, slots=True)
class VerifiedArtifactBytes:
    data: bytes
    byte_size: int
    content_hash: SHA256Hash


def read_verified_local_artifact(
    root: Path,
    relative_path: str,
    expected_hash: SHA256Hash,
    limits: ResolverLimits,
) -> VerifiedArtifactBytes:
    relative = Path(relative_path)
    if "\0" in relative_path or relative.is_absolute() or ".." in relative.parts:
        raise ArtifactResolutionError("artifact path must be confined to its root")
    root_resolved = root.resolve(strict=True)
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactResolutionError("artifact path must not contain symlinks")
    candidate = current.resolve(strict=True)
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        raise ArtifactResolutionError("artifact must be a confined regular file")
    size = candidate.stat().st_size
    if size > limits.max_bytes:
        raise ArtifactResolutionError("artifact exceeds configured size limit")
    with candidate.open("rb") as stream:
        data = stream.read(limits.max_bytes + 1)
    if len(data) > limits.max_bytes:
        raise ArtifactResolutionError("artifact exceeds configured size limit")
    digest = sha256(data).hexdigest()
    if digest != expected_hash:
        raise ArtifactIntegrityError("artifact SHA-256 does not match")
    return VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=digest)
```

The local fixture resolver is intentionally small. Every parser consumes `VerifiedArtifactBytes.data`; it never reopens a path. A future large-file adapter must hash and parse the same descriptor or use an immutable content-addressed object.

- [ ] **Step 4: Run resolver tests and static checks**

Run: `uv run pytest tests/unit/test_dataset_resolver.py -v && uv run ruff check src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py && uv run mypy src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py`

Expected: all commands exit 0.

- [ ] **Step 5: Commit safe resolution**

```text
git add src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py
git commit -m "feat: verify confined dataset artifacts"
```

### Task 4: Immutable Revisions and Cutoff Selection

**Files:**
- Create: `src/drift/domain/revisions.py`
- Create: `src/drift/domain/dataset_validation.py`
- Create: `src/drift/datasets/validation.py`
- Modify: `src/drift/datasets/hashing.py`
- Test: `tests/unit/test_revisions.py`

**Interfaces:**
- Consumes: Task 1 temporal contracts, M0 `ArtifactReference`, `ImmutableJSON`, and canonical hashing.
- Produces: `FindingSeverity`, `ValidationFindingV1`, `DatasetValidationError`, `RevisionKind`, `LogicalFactKeyV1`, `FactVersionV1`, `FactSelectionResultV1`, `fact_version_payload(version) -> dict[str, JSONValue]`, `validate_revision_chain(versions) -> tuple[ValidationFindingV1, ...]`, and `select_fact_version(versions, channel, policy, cutoff) -> FactSelectionResultV1`.

- [ ] **Step 1: Write the deterministic revision-selection table**

```python
@pytest.mark.parametrize(
    ("case", "cutoff", "expected_class", "expected_value"),
    (
        ("original", utc(2022, 5, 4), CutoffEligibility.INELIGIBLE, None),
        ("original", utc(2022, 5, 5), CutoffEligibility.ELIGIBLE, "1.20"),
        ("restated", utc(2022, 6, 1), CutoffEligibility.ELIGIBLE, "1.20"),
        ("restated", utc(2022, 8, 10), CutoffEligibility.ELIGIBLE, "0.90"),
        ("bounded", utc(2022, 5, 5, 12), CutoffEligibility.INDETERMINATE, None),
        ("unknown", utc(2030, 1, 1), CutoffEligibility.INDETERMINATE, None),
        ("withdrawn", utc(2022, 9, 1), CutoffEligibility.INELIGIBLE, None),
    ),
)
def test_revision_selection_table(
    case: str,
    cutoff: datetime,
    expected_class: CutoffEligibility,
    expected_value: str | None,
) -> None:
    result = select_fact_version(CHAINS[case], PUBLIC, STRICT, cutoff)
    assert result.classification is expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value
```

Add validation cases for duplicate version IDs, missing or multiple initial roots, missing predecessor, key mismatch, branching, cycle, decreasing source sequence, duplicate channel evidence, missing source artifact, payload-hash mismatch, withdrawal with a value, nonwithdrawal without a value and null reason, and naive cutoff.

- [ ] **Step 2: Run tests and verify revision types are absent**

Run: `uv run pytest tests/unit/test_revisions.py -v`

Expected: collection fails on missing revision types.

- [ ] **Step 3: Implement immutable fact versions and payload hashes**

```python
class FactVersionV1(FrozenModel):
    fact_version_id: UUID7
    logical_key: LogicalFactKeyV1
    revision_kind: RevisionKind
    supersedes_fact_version_id: UUID7 | None = None
    source_sequence: Annotated[int, Field(ge=0)]
    value: ImmutableJSON
    null_reason: NonBlankStr | None = None
    availability: tuple[AvailabilityEvidenceV1, ...]
    source_artifact: ArtifactReference
    payload_hash: SHA256Hash


class LogicalFactKeyV1(FrozenModel):
    source_id: NonBlankStr
    entity_key: NonBlankStr
    concept: NonBlankStr
    valid_period: ValidPeriodV1
    unit: NonBlankStr
    dimensions: ImmutableJSON


class FactSelectionResultV1(FrozenModel):
    classification: CutoffEligibility
    reason: NonBlankStr
    selected_version: FactVersionV1 | None = None


def fact_version_payload(version: FactVersionV1) -> dict[str, JSONValue]:
    payload = canonical_data(version)
    assert isinstance(payload, dict)
    del payload["payload_hash"]
    return payload
```

`LogicalFactKeyV1` contains source ID, entity key, concept, `ValidPeriodV1`, unit, and immutable dimensions. Validate the supplied payload hash against `content_hash(fact_version_payload(version))`. Require a nonempty availability tuple with unique channels. A withdrawal has canonical null value and `null_reason="withdrawn"`; other null values require an explicit reason.

Define findings and errors once in `drift.domain.dataset_validation` so revision
and dataset validators share the exact type:

```python
class ValidationFindingV1(FrozenModel):
    code: NonBlankStr
    severity: FindingSeverity
    message: NonBlankStr
    artifact_references: tuple[ArtifactReference, ...] = ()


class DatasetValidationError(DriftError):
    def __init__(self, findings: Sequence[ValidationFindingV1]) -> None:
        self.findings = tuple(findings)
        super().__init__("; ".join(finding.code for finding in self.findings))

    @classmethod
    def single(cls, code: str) -> "DatasetValidationError":
        return cls(
            (
                ValidationFindingV1(
                    code=code,
                    severity=FindingSeverity.ERROR,
                    message=code.replace("_", " "),
                ),
            )
        )
```

- [ ] **Step 4: Implement fail-closed chain validation and selection**

```python
def select_fact_version(
    versions: Sequence[FactVersionV1],
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
) -> FactSelectionResultV1:
    findings = validate_revision_chain(versions)
    if findings:
        raise DatasetValidationError(findings)
    decisions = tuple(
        (
            version,
            evaluate_availability(
                next(
                    evidence
                    for evidence in version.availability
                    if evidence.channel == channel
                ),
                channel,
                policy,
                cutoff,
            ),
        )
        for version in versions
        if any(evidence.channel == channel for evidence in version.availability)
    )
    eligible = [item for item in decisions if item[1].classification is CutoffEligibility.ELIGIBLE]
    if eligible:
        selected = max(eligible, key=lambda item: item[0].source_sequence)[0]
        if selected.revision_kind is RevisionKind.WITHDRAWAL:
            return FactSelectionResultV1(
                classification=CutoffEligibility.INELIGIBLE,
                reason="latest_available_version_withdrawn",
                selected_version=None,
            )
        return FactSelectionResultV1(
            classification=CutoffEligibility.ELIGIBLE,
            reason="latest_definitely_available_version",
            selected_version=selected,
        )
    classification = (
        CutoffEligibility.INDETERMINATE
        if not decisions
        or any(
            item[1].classification is CutoffEligibility.INDETERMINATE
            for item in decisions
        )
        else CutoffEligibility.INELIGIBLE
    )
    return FactSelectionResultV1(
        classification=classification,
        reason=(
            "availability_not_established"
            if classification is CutoffEligibility.INDETERMINATE
            else "no_version_available_by_cutoff"
        ),
        selected_version=None,
    )
```

Before `max`, require that all eligible versions form one predecessor path and source sequence is strictly increasing. A later indeterminate revision does not introduce future data and does not erase an earlier definitely available revision. A malformed or ambiguous chain raises typed validation findings rather than returning a favorable result.

- [ ] **Step 5: Run revision and temporal tests**

Run: `uv run pytest tests/unit/test_revisions.py tests/unit/test_temporal.py -v && uv run ruff check src/drift/domain/revisions.py src/drift/domain/dataset_validation.py src/drift/datasets/validation.py tests/unit/test_revisions.py && uv run mypy src/drift/domain/revisions.py src/drift/domain/dataset_validation.py src/drift/datasets/validation.py tests/unit/test_revisions.py`

Expected: all commands exit 0.

- [ ] **Step 6: Commit revision semantics**

```text
git add src/drift/domain/revisions.py src/drift/domain/dataset_validation.py src/drift/datasets/hashing.py src/drift/datasets/validation.py tests/unit/test_revisions.py
git commit -m "feat: preserve point-in-time fact revisions"
```

### Task 5: Exact-Object Validation Decisions and M0 Provenance Bridge

**Files:**
- Modify: `src/drift/domain/dataset_validation.py`
- Modify: `src/drift/datasets/validation.py`
- Create: `src/drift/datasets/references.py`
- Test: `tests/unit/test_dataset_validation.py`
- Create: `tests/integration/test_m1_m0_compatibility.py`

**Interfaces:**
- Consumes: manifest/fact hashes, verified bytes, Task 4 findings, and existing `DatasetReference`.
- Produces: `ValidationScope`, `ValidationResult`, `ValidationRunContextV1`, `DatasetValidationDecisionV1`, `parse_synthetic_fact_bytes(verified) -> tuple[FactVersionV1, ...]`, `validate_manifest_structure(manifest, verified_artifacts, context) -> DatasetValidationDecisionV1`, `validate_synthetic_fact_dataset(manifest, verified_artifacts, context) -> DatasetValidationDecisionV1`, and `build_dataset_reference(manifest, manifest_reference, decision) -> DatasetReference`.

- [ ] **Step 1: Write failing exact-object decision and compatibility tests**

```python
def test_record_decision_binds_manifest_bytes_and_fact_payloads() -> None:
    decision = validate_synthetic_fact_dataset(MANIFEST, VERIFIED, CONTEXT)
    assert decision.result is ValidationResult.PASS
    assert decision.manifest_hash == manifest_hash(MANIFEST)
    assert decision.validated_artifact_hashes == tuple(
        sorted(item.content_hash for item in VERIFIED)
    )
    assert decision.validated_record_hashes == tuple(
        version.payload_hash for version in parse_synthetic_fact_bytes(VERIFIED[0])
    )
    assert "pit_eligibility" not in DatasetValidationDecisionV1.model_fields


@pytest.mark.parametrize(
    "mutation",
    ("changed_bytes", "wrong_schema", "missing_record_evidence", "broken_lineage"),
)
def test_validation_fails_for_unbound_or_incomplete_evidence(mutation: str) -> None:
    decision = validate_synthetic_fact_dataset(
        MANIFESTS[mutation], VERIFIED_CASES[mutation], CONTEXT
    )
    assert decision.result is ValidationResult.FAIL


def test_m0_fixture_serialization_and_event_hashes_are_unchanged() -> None:
    assert canonical_json(existing_m0_dataset_reference()) == M0_REFERENCE_BYTES
    assert compute_event_hash(existing_m0_unsigned_event()) == M0_EVENT_HASH
```

Also test unsupported validator/schema/manifest versions, missing partition, duplicate artifact hash, declared byte size and row count mismatch, parsed record coverage outside its partition, record without evidence for every declared channel, decision hash changing when any finding or checked hash changes, and reference construction from a failed or mismatched decision.

- [ ] **Step 2: Run tests and verify decision APIs are incomplete**

Run: `uv run pytest tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py -v`

Expected: tests fail because decision, parser, validator, and bridge behavior is not implemented.

- [ ] **Step 3: Implement immutable decisions without eligibility labels**

```python
class DatasetValidationDecisionV1(FrozenModel):
    decision_id: UUID7
    manifest_hash: SHA256Hash
    validator_version: NonBlankStr
    validator_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    validated_artifact_hashes: tuple[SHA256Hash, ...]
    validated_record_hashes: tuple[SHA256Hash, ...] = ()
    checked_contracts: tuple[NonBlankStr, ...]
    findings: tuple[ValidationFindingV1, ...]
```

Enforce `PASS` only when there are no error findings, unique sorted artifact and record hashes, and the expected scope fields are present. `MANIFEST_ONLY` has no record hashes. `RECORDS` requires nonempty record hashes and the `record-temporal-v1` checked contract. The decision contains no cutoff, promotion, dataset-wide PIT status, or eligibility permission.

`parse_synthetic_fact_bytes` accepts only a versioned JSON object with a `fact_versions` array, rejects unknown fields through Pydantic, and parses directly from `VerifiedArtifactBytes.data`. `validate_synthetic_fact_dataset` verifies every partition before parsing, checks manifest schema bindings, record counts, coverage, payload hashes, revision chains, declared-channel evidence, and derived lineage. It never reopens a path and never evaluates a historical cutoff.

- [ ] **Step 4: Implement the provenance-only M0 bridge**

```python
def build_dataset_reference(
    manifest: DatasetManifestV1,
    manifest_reference: ArtifactReference,
    decision: DatasetValidationDecisionV1,
) -> DatasetReference:
    digest = manifest_hash(manifest)
    if manifest_reference.kind is not ArtifactKind.DATASET:
        raise DatasetValidationError.single("manifest_artifact_kind")
    if manifest_reference.content_hash != digest or decision.manifest_hash != digest:
        raise DatasetValidationError.single("manifest_hash_mismatch")
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("manifest_not_validated")
    return DatasetReference(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        schema_version=manifest.schema_definition.schema_version,
        content_hash=digest,
        created_at=manifest.created_at,
        source=manifest.source.source_id,
        temporal_coverage=derived_temporal_coverage(manifest.partitions),
        point_in_time_policy="explicit_record_evidence_v1",
        corporate_action_policy="not_applicable_m1a",
        availability_timestamp_policy="channel_scoped_no_defaults_v1",
        manifest_reference=manifest_reference,
    )
```

Document in the function docstring that this is provenance only. It does not certify a cutoff query or authorize promotion. Do not modify `DatasetReference`, `ExperimentSpecification`, or `ExperimentRun`.

- [ ] **Step 5: Verify M0 replay and exact hashes**

Run: `uv run pytest tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py tests/integration/test_replay.py tests/integration/test_tamper_detection.py -v`

Expected: all tests pass; pinned M0 bytes and event hashes are unchanged.

- [ ] **Step 6: Commit validation evidence and bridge**

```text
git add src/drift/domain/dataset_validation.py src/drift/datasets/validation.py src/drift/datasets/references.py tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py
git commit -m "feat: record exact dataset validation evidence"
```

### Task 6: Adversarial Fixtures and Audit Events

**Files:**
- Create: `src/drift/datasets/events.py`
- Create: `tests/fixtures/datasets/m1a/late-fundamental.json`
- Create: `tests/fixtures/datasets/m1a/restated-fundamental.json`
- Create: `tests/fixtures/datasets/m1a/macro-vintage.json`
- Create: `tests/fixtures/datasets/m1a/vendor-delay.json`
- Create: `tests/fixtures/datasets/m1a/date-only-release.json`
- Create: `tests/fixtures/datasets/m1a/bounded-release.json`
- Create: `tests/fixtures/datasets/m1a/unknown-release.json`
- Create: `tests/fixtures/datasets/m1a/late-ingest.json`
- Create: `tests/fixtures/datasets/m1a/withdrawal.json`
- Create: `tests/integration/test_m1a_leakage.py`
- Create: `tests/integration/test_m1_dataset_audit.py`

**Interfaces:**
- Consumes: Tasks 1 through 5 and existing generic audit-event hashing/ledger APIs.
- Produces: fixed synthetic fixture bytes, `build_manifest_recorded_event(manifest, manifest_reference, previous_event_hash) -> AuditEvent`, and `build_validation_completed_event(manifest, decision, previous_event_hash) -> AuditEvent`.

- [ ] **Step 1: Add readable fixtures with pinned expected hashes**

Every fixture uses schema version `1`, fixed UUIDv7 values, explicit record evidence, and UTC bounds. Keep expected fixture SHA-256 values in `test_m1a_leakage.py`, so changed bytes fail before parsing. A date-only release represents the local calendar day as a bounded UTC interval and preserves its IANA timezone and `date` precision. Vendor delay contains separate public and vendor evidence. Late ingestion contains separate public and system evidence. No fixture contains a market identifier, listing, universe, corporate action, bar, or session.

- [ ] **Step 2: Write the deterministic adversarial result table**

```python
CASES = (
    ("late-fundamental.json", "public", "2022-04-30T23:59:59Z", "ineligible", None),
    ("late-fundamental.json", "public", "2022-05-05T20:00:00Z", "eligible", "1.20"),
    ("restated-fundamental.json", "public", "2022-06-01T00:00:00Z", "eligible", "1.20"),
    ("restated-fundamental.json", "public", "2022-08-10T00:00:00Z", "eligible", "0.90"),
    ("macro-vintage.json", "public", "2022-02-01T00:00:00Z", "eligible", "initial"),
    ("macro-vintage.json", "public", "2022-03-01T00:00:00Z", "eligible", "revised"),
    ("vendor-delay.json", "public", "2022-05-05T20:00:00Z", "eligible", "released"),
    ("vendor-delay.json", "vendor", "2022-05-05T20:00:00Z", "ineligible", None),
    ("date-only-release.json", "public", "2022-05-05T12:00:00Z", "indeterminate", None),
    ("date-only-release.json", "public", "2022-05-06T04:00:00Z", "eligible", "released"),
    ("unknown-release.json", "public", "2030-01-01T00:00:00Z", "indeterminate", None),
    ("late-ingest.json", "system", "2022-05-06T00:00:00Z", "ineligible", None),
    ("withdrawal.json", "public", "2022-09-01T00:00:00Z", "ineligible", None),
)


@pytest.mark.parametrize(
    ("filename", "channel_id", "cutoff", "expected_class", "expected_value"),
    CASES,
)
def test_adversarial_cutoff_table(
    filename: str,
    channel_id: str,
    cutoff: str,
    expected_class: str,
    expected_value: str | None,
) -> None:
    verified = read_verified_local_artifact(
        FIXTURES, filename, EXPECTED_HASHES[filename], ResolverLimits(max_bytes=64_000)
    )
    versions = parse_synthetic_fact_bytes(verified)
    result = select_fact_version(
        versions, CHANNELS[channel_id], STRICT, parse_utc(cutoff)
    )
    assert result.classification.value == expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value
```

Add separate deterministic rejection tests for broken predecessor, cycle, duplicate version ID, reversed chronology, changed bytes, schema drift, traversal, and lineage mismatch. Do not use property-based generation.

- [ ] **Step 3: Run leakage tests and fix only contract or fixture defects**

Run: `uv run pytest tests/integration/test_m1a_leakage.py -v`

Expected: all cases pass without adding a provider adapter or market-specific type.

- [ ] **Step 4: Implement compact audit events and replay tests**

```python
def build_validation_completed_event(
    manifest: DatasetManifestV1,
    decision: DatasetValidationDecisionV1,
    previous_event_hash: SHA256Hash,
) -> AuditEvent:
    unsigned = UnsignedAuditEvent(
        event_id=decision.decision_id,
        event_type="dataset.validation.completed",
        timestamp=decision.checked_at,
        entity_type="dataset_manifest",
        entity_id=manifest.dataset_id,
        payload={
            "manifest_hash": decision.manifest_hash,
            "decision_hash": content_hash(decision),
            "result": decision.result.value,
            "validation_scope": decision.validation_scope.value,
        },
        previous_event_hash=previous_event_hash,
        schema_version="1",
    )
    return build_audit_event(unsigned)
```

Create the manifest event with manifest ID, manifest hash, hash profile, and schema version. Test append, chain verification, replay, and tamper detection for both events. Do not store raw bytes, physical paths, license prose, cutoff results, or credentials in SQLite. A per-query result remains a return value, not a durable dataset permission.

- [ ] **Step 5: Run M1a and complete M0 gates**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: all commands exit 0.

- [ ] **Step 6: Commit adversarial evidence**

```text
git add src/drift/datasets/events.py tests/fixtures/datasets/m1a tests/integration/test_m1a_leakage.py tests/integration/test_m1_dataset_audit.py
git commit -m "test: prove temporal leakage is rejected"
```

### Task 7: Capability Documentation and M1a Completion Gate

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/architecture/roadmap.md`
- Modify: `docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md`
- Modify: `docs/superpowers/plans/2026-09-01-m1a-temporal-provenance.md`
- Test: all M0 and M1a tests.

**Interfaces:**
- Consumes: the complete M1a diff and verification evidence.
- Produces: accurate repository capability/status text, no M1b claim, and a clean verified M1a checkpoint.

- [ ] **Step 1: Write documentation assertions before changing status text**

```python
def test_roadmap_marks_m1a_complete_and_m1b_deferred() -> None:
    roadmap = Path("docs/architecture/roadmap.md").read_text(encoding="utf-8")
    assert "M1a" in roadmap and "complete" in roadmap.lower()
    assert "M1b" in roadmap and "deferred" in roadmap.lower()


def test_repository_does_not_claim_equity_backtest_readiness() -> None:
    text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("README.md", "AGENTS.md", "docs/architecture/roadmap.md")
    )
    assert "equity-backtest ready" not in text.lower()
```

Add these to `tests/unit/test_project_contract.py`. Run the focused test and confirm it fails before documentation changes.

- [ ] **Step 2: Document only implemented capability and limitations**

Update the root guidance from "M0 only" to "M0 evidence kernel plus M1a temporal provenance". State that M1a provides exact-byte manifests, explicit channel-scoped evidence, immutable revisions, exact-object validation records, and per-query tri-state cutoff decisions. State that it has no real source, market semantics, evaluator, backtester, or trading capability, and that M1b remains required before historical US-equity evaluation claims.

Mark this plan complete only after the gate passes. Update the umbrella design status to say M1a implemented and M1b deferred without rewriting its research or presenting the M1a implementation rulings as completed M1b design.

- [ ] **Step 3: Run explicit scope, contradiction, and compatibility scans**

Run: `rg -n "(security_id|listing_id|ticker|universe|corporate.action|split|dividend|delist|exchange.calendar|market.session|tradability)" src tests`

Expected: no M1b production abstraction was added. Inspect fixture prose matches instead of treating names alone as failures.

Run: `rg -n "(robinhood|alpaca|place_order|submit_order|api[_-]?key|oauth|langgraph|openai|rd-agent|hypothesis)" src tests pyproject.toml`

Expected: no forbidden capability or dependency was added. Inspect every match.

Run: `git diff 4587745 -- src/drift/domain/datasets.py src/drift/domain/artifacts.py src/drift/domain/experiments.py src/drift/domain/events.py src/drift/serialization/canonical.py`

Expected: no diff in compatibility-sensitive M0 files.

Run: `rg -n --fixed-strings "$(printf '\342\200\224')" . --glob '!uv.lock' && rg -n 'T[B]D|T[O]DO|implement la[t]er|fill in detail[s]|Similar to Tas[k]|appropriate error handlin[g]' docs/superpowers/plans/2026-09-01-m1a-temporal-provenance.md`

Expected: both searches return no matches.

- [ ] **Step 4: Run the full quality and packaging gate**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: all commands exit 0.

- [ ] **Step 5: Perform the final scientific self-review**

Attempt each of these constructions and require a typed failure or non-eligible result: unknown evidence presented with bounds; date-only evidence converted to midnight; rule-derived evidence missing inputs; unapproved rule; mismatched channel; cutoff inside a bounded window; later revision selected before availability; dataset or partition availability default; changed bytes after decision; broken chain; incomplete lineage; a bare `DatasetReference` treated as permission; security/listing/universe/action/calendar data smuggled into generic contracts.

If a concrete defect is found, add a failing deterministic regression case, implement the smallest fix, rerun the focused test, and commit the reviewed fix. Do not broaden scope.

- [ ] **Step 6: Commit documentation and checkpoint M1a**

```text
git add README.md AGENTS.md docs/architecture/roadmap.md docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md docs/superpowers/plans/2026-09-01-m1a-temporal-provenance.md tests/unit/test_project_contract.py
git commit -m "docs: complete M1a temporal provenance"
```

Run: `git status -sb && git log -8 --oneline`

Expected: `main` is clean at the M1a completion commit. Record a Checkpoint that states M1a is complete, M1b is deferred, and Drift is not an equity backtester. Do not create a Session Handoff when the implementation is complete, committed, verified, and clean.

## Planned Commit Boundaries

1. `feat: add point-in-time availability evidence`
2. `feat: add immutable dataset manifests`
3. `feat: verify confined dataset artifacts`
4. `feat: preserve point-in-time fact revisions`
5. `feat: record exact dataset validation evidence`
6. `test: prove temporal leakage is rejected`
7. Review fixes only when a deterministic failing test demonstrates a defect
8. `docs: complete M1a temporal provenance`

## M1a Acceptance Boundary

M1a is complete only when exact bytes, asset-neutral temporal evidence, immutable revisions, exact-object validation decisions, tri-state cutoff results, adversarial fixtures, audit evidence, and M0 compatibility all pass the full repository gate. Completion does not select a provider, validate real market data, model securities, or make Drift ready for equity backtesting. M1b remains a separate future design and execution effort.
