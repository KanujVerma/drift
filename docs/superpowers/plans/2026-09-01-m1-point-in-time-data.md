# Drift M1 Point-in-Time Data Implementation Plan

**Status:** Planned and not started. Every checkbox is intentionally unchecked.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add immutable point-in-time dataset contracts and fail-closed validators that bind exact bytes to channel-scoped temporal evidence, then add the minimum historical equity identity, universe, corporate-action, and session semantics required to prevent common leakage.

**Architecture:** M1a adds storage-neutral content manifests, temporal evidence, immutable fact revisions, safe local fixture resolution, and scoped validation decisions. M1b adds stable security/listing identity, historical membership, source action and termination events, price-basis and session contracts. Existing M0 persisted models remain unchanged; `DatasetReference` bridges to a manifest hash.

**Tech Stack:** Python 3.14, Pydantic 2, standard-library hashlib/pathlib/zoneinfo, existing Drift canonical JSON and audit ledger, pytest, Ruff, mypy

**Spec:** `docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md`

## Global Constraints

- Read the spec, ADR 0005, M0 design, and existing domain contracts before execution.
- Implement M1a before M1b. Do not describe M1a alone as equity-backtest ready.
- Do not modify fields, defaults, validators, canonical serialization, or hash behavior of any existing M0 persisted model.
- Python remains `>=3.14`; Pydantic remains the sole runtime dependency.
- Add no vendor download, network client, broker, Robinhood, Alpaca, order, credential, agent, backtester, feature system, model training, calendar library, object store, or executable transformation pipeline.
- Keep exact data bytes outside SQLite. SQLite receives only compact manifest, validation, and audit evidence.
- Unknown availability remains unknown and is never silently inferred.
- New manifests use Drift canonical JSON and SHA-256 under hash profile `drift-canonical-json-sha256-v1`.
- All production code is test-driven. Run the named failing test before its implementation.
- Use no U+2014 em dash in source, tests, fixtures, or documentation.

## File map

| File | Responsibility |
|---|---|
| `src/drift/domain/temporal.py` | Valid periods, information channels, and availability evidence |
| `src/drift/domain/manifests.py` | Source, license, schema, partition, lineage, semantic-contract, and manifest models |
| `src/drift/domain/revisions.py` | Immutable revised facts and cutoff selection |
| `src/drift/domain/dataset_validation.py` | Typed findings and immutable scoped validation decisions |
| `src/drift/domain/securities.py` | Issuer, security, listing, and dated external-identifier mappings |
| `src/drift/domain/universes.py` | Universe definitions and point-in-time membership events |
| `src/drift/domain/corporate_actions.py` | Source action and listing-termination records, price-basis contract |
| `src/drift/domain/calendars.py` | Session observations and immutable calendar references |
| `src/drift/domain/market_data.py` | Parsed raw market observations and explicit missingness |
| `src/drift/datasets/hashing.py` | Canonical manifest body and manifest hash |
| `src/drift/datasets/resolver.py` | Confined local fixture resolver and byte-hash verification |
| `src/drift/datasets/validation.py` | Cross-record manifest, revision, and M1a eligibility validation |
| `src/drift/datasets/market_validation.py` | Identity, universe, action, price, and session validation |
| `src/drift/datasets/references.py` | Additive bridge from a validated M1 manifest to existing `DatasetReference` |
| `tests/fixtures/datasets/` | Small JSON/CSV fixture bytes and expected point-in-time outcomes |
| `tests/unit/test_*.py` | Focused model, hash, resolver, and validator tests |
| `tests/integration/test_m1_*.py` | Adversarial cross-object and M0 compatibility tests |

---

## Phase M1a: Provenance and temporal evidence

### Task 1: Temporal evidence primitives

**Files:**
- Create: `src/drift/domain/temporal.py`
- Test: `tests/unit/test_temporal.py`

**Interfaces:**
- Consumes: `FrozenModel`, `NonBlankStr`, and `UTCDateTime` from `drift.domain.common`.
- Produces: `ValidPeriodV1`, `ChannelKind`, `AvailabilityStatus`, `AvailabilityBasis`, `AvailabilityChannelV1`, `AvailabilityEvidenceV1`, and `definitely_available(evidence, channel, cutoff) -> bool`.

- [ ] **Step 1: Write failing exact, bounded, channel, and unknown tests**

```python
def test_bounded_evidence_fails_inside_window_and_passes_after_upper_bound() -> None:
    evidence = bounded_vendor_evidence(
        lower=utc(2022, 5, 5, 0), upper=utc(2022, 5, 6, 0)
    )
    assert not definitely_available(evidence, evidence.channel, utc(2022, 5, 5, 12))
    assert definitely_available(evidence, evidence.channel, utc(2022, 5, 6, 0))


def test_unknown_evidence_is_never_definitely_available() -> None:
    evidence = unknown_public_evidence()
    assert not definitely_available(evidence, evidence.channel, utc(2030, 1, 1))


def test_evidence_from_another_channel_does_not_pass() -> None:
    evidence = exact_public_evidence(utc(2022, 5, 5, 20))
    assert not definitely_available(
        evidence, vendor_channel("vendor-a", "product-1"), utc(2022, 5, 6)
    )
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run: `uv run pytest tests/unit/test_temporal.py -v`

Expected: collection fails because `drift.domain.temporal` does not exist.

- [ ] **Step 3: Implement strict temporal models and fail-closed selection**

```python
class ValidPeriodV1(FrozenModel):
    started_at: UTCDateTime
    ended_at: UTCDateTime

    def contains(self, instant: datetime) -> bool:
        instant_utc = _normalize_utc(instant)
        return self.started_at <= instant_utc < self.ended_at


class AvailabilityEvidenceV1(FrozenModel):
    channel: AvailabilityChannelV1
    status: AvailabilityStatus
    available_lower: UTCDateTime | None = None
    available_upper: UTCDateTime | None = None
    precision: NonBlankStr
    source_timezone: NonBlankStr | None = None
    basis: AvailabilityBasis
    evidence_reference: ArtifactReference | None = None
    rule_reference: SHA256Hash | None = None


def definitely_available(
    evidence: AvailabilityEvidenceV1,
    channel: AvailabilityChannelV1,
    cutoff: datetime,
) -> bool:
    cutoff_utc = _normalize_utc(cutoff)
    return (
        evidence.channel == channel
        and evidence.status is not AvailabilityStatus.UNKNOWN
        and evidence.available_upper is not None
        and evidence.available_upper <= cutoff_utc
    )
```

Add a model validator that enforces equal bounds for `exact`, ordered non-null
bounds for `bounded`, a rule hash and bounds for `rule_derived`, and absent bounds
for `unknown`. Require `ValidPeriodV1` to be nonempty and treat it as half-open.
Validate IANA timezones with `zoneinfo.ZoneInfo` when present.

- [ ] **Step 4: Run temporal tests, lint, and type checks**

Run: `uv run pytest tests/unit/test_temporal.py -v && uv run ruff check src/drift/domain/temporal.py tests/unit/test_temporal.py && uv run mypy src/drift/domain/temporal.py tests/unit/test_temporal.py`

Expected: all commands exit 0.

- [ ] **Step 5: Commit temporal primitives**

```text
git add src/drift/domain/temporal.py tests/unit/test_temporal.py
git commit -m "feat: add point-in-time availability evidence"
```

### Task 2: Immutable manifest and partition models

**Files:**
- Create: `src/drift/domain/manifests.py`
- Create: `src/drift/datasets/__init__.py`
- Create: `src/drift/datasets/hashing.py`
- Test: `tests/unit/test_manifests.py`
- Test: `tests/unit/test_manifest_hashing.py`

**Interfaces:**
- Consumes: M0 `ArtifactReference`, canonical `content_hash`, and Task 1 temporal types.
- Produces: `DatasetKind`, `SourceDescriptorV1`, `AcquisitionDescriptorV1`,
  `LicenseDescriptorV1`, `FieldDescriptorV1`, `SchemaDescriptorV1`,
  `PartitionDescriptorV1`, `LineageDescriptorV1`, `TemporalContractV1`,
  `ContractKind`, the discriminated `SemanticContractV1` variants,
  `DatasetManifestV1`, `manifest_body(manifest) -> dict[str, JSONValue]`, and
  `manifest_hash(manifest) -> str`.

- [ ] **Step 1: Write failing manifest validation and hash tests**

```python
def test_manifest_rejects_duplicate_partition_keys() -> None:
    first = partition(partition_key="year=2022", digest="a" * 64)
    second = partition(partition_key="year=2022", digest="b" * 64)
    with pytest.raises(ValidationError, match="partition keys must be unique"):
        manifest(partitions=(first, second))


def test_manifest_hash_is_order_independent_for_input_partition_order() -> None:
    first = partition(partition_key="year=2021", digest="a" * 64)
    second = partition(partition_key="year=2022", digest="b" * 64)
    assert manifest_hash(manifest(partitions=(first, second))) == manifest_hash(
        manifest(partitions=(second, first))
    )


def test_derived_manifest_requires_complete_lineage() -> None:
    with pytest.raises(ValidationError, match="derived datasets require lineage"):
        manifest(dataset_kind=DatasetKind.DERIVED, lineage=None)
```

- [ ] **Step 2: Run the tests and confirm the models are missing**

Run: `uv run pytest tests/unit/test_manifests.py tests/unit/test_manifest_hashing.py -v`

Expected: collection fails on missing manifest types.

- [ ] **Step 3: Implement focused immutable descriptor models**

```python
class PartitionDescriptorV1(FrozenModel):
    partition_id: UUID7
    partition_key: NonBlankStr
    artifact: ArtifactReference
    byte_size: Annotated[int, Field(ge=0)]
    media_type: NonBlankStr
    format_version: NonBlankStr
    row_count: Annotated[int, Field(ge=0)]
    schema_hash: SHA256Hash
    coverage: ValidPeriodV1


class TemporalContractV1(FrozenModel):
    policy_id: NonBlankStr
    evidence_granularity: EvidenceGranularity
    allowed_channels: tuple[AvailabilityChannelV1, ...]
    approved_rule_hashes: tuple[SHA256Hash, ...] = ()


class RevisedFactContractV1(FrozenModel):
    kind: Literal[ContractKind.REVISED_FACTS] = ContractKind.REVISED_FACTS
    entity_field_id: NonBlankStr
    concept_field_id: NonBlankStr
    valid_start_field_id: NonBlankStr
    valid_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    revision_id_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr
    value_field_id: NonBlankStr
    unit_field_id: NonBlankStr
    null_reason_field_id: NonBlankStr


class MarketObservationContractV1(FrozenModel):
    kind: Literal[ContractKind.MARKET_OBSERVATIONS] = ContractKind.MARKET_OBSERVATIONS
    listing_id_field_id: NonBlankStr
    source_record_id_field_id: NonBlankStr
    venue_field_id: NonBlankStr
    valid_start_field_id: NonBlankStr
    valid_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    session_date_field_id: NonBlankStr
    interval_count_field_id: NonBlankStr
    interval_unit_field_id: NonBlankStr
    timestamp_convention_field_id: NonBlankStr
    price_basis_field_id: NonBlankStr
    missingness_field_id: NonBlankStr
    open_field_id: NonBlankStr
    high_field_id: NonBlankStr
    low_field_id: NonBlankStr
    close_field_id: NonBlankStr
    volume_field_id: NonBlankStr
    identity_manifest_hash: SHA256Hash
    universe_manifest_hash: SHA256Hash
    corporate_action_manifest_hash: SHA256Hash
    calendar_manifest_hash: SHA256Hash


class UniverseEventContractV1(FrozenModel):
    kind: Literal[ContractKind.UNIVERSE_EVENTS] = ContractKind.UNIVERSE_EVENTS
    universe_id_field_id: NonBlankStr
    listing_id_field_id: NonBlankStr
    action_field_id: NonBlankStr
    effective_start_field_id: NonBlankStr
    effective_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    source_event_id_field_id: NonBlankStr
    source_sequence_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr


class IdentityMappingContractV1(FrozenModel):
    kind: Literal[ContractKind.IDENTITY_MAPPINGS] = ContractKind.IDENTITY_MAPPINGS
    mapping_id_field_id: NonBlankStr
    scope_field_id: NonBlankStr
    internal_id_field_id: NonBlankStr
    identifier_type_field_id: NonBlankStr
    identifier_value_field_id: NonBlankStr
    venue_field_id: NonBlankStr
    valid_start_field_id: NonBlankStr
    valid_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    source_revision_field_id: NonBlankStr


class CorporateActionContractV1(FrozenModel):
    kind: Literal[ContractKind.CORPORATE_ACTIONS] = ContractKind.CORPORATE_ACTIONS
    event_family_field_id: NonBlankStr
    event_id_field_id: NonBlankStr
    logical_event_key_field_id: NonBlankStr
    security_id_field_id: NonBlankStr
    listing_id_field_id: NonBlankStr
    action_or_status_field_id: NonBlankStr
    effective_at_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    source_sequence_field_id: NonBlankStr
    revision_kind_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr
    source_terms_field_id: NonBlankStr


class SessionContractV1(FrozenModel):
    kind: Literal[ContractKind.SESSIONS] = ContractKind.SESSIONS
    calendar_id_field_id: NonBlankStr
    calendar_version_field_id: NonBlankStr
    schedule_hash_field_id: NonBlankStr
    venue_field_id: NonBlankStr
    session_date_field_id: NonBlankStr
    open_at_field_id: NonBlankStr
    close_at_field_id: NonBlankStr
    status_field_id: NonBlankStr
    availability_field_id: NonBlankStr


type SemanticContractV1 = Annotated[
    RevisedFactContractV1
    | MarketObservationContractV1
    | UniverseEventContractV1
    | IdentityMappingContractV1
    | CorporateActionContractV1
    | SessionContractV1,
    Field(discriminator="kind"),
]


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
    temporal_contract: TemporalContractV1
    semantic_contracts: tuple[SemanticContractV1, ...]
    lineage: LineageDescriptorV1 | None = None
```

Use closed enums for rights and determinism. Require a nonempty schema and
partition tuple, unique stable field IDs and names, unique partition IDs and
keys, exactly one dataset-kind-appropriate typed semantic contract, every field
binding to resolve to the schema, every cross-dataset hash to be present for a
market-observation contract, raw source acquisition evidence, derived lineage,
and no credential-bearing source locator. Do not allow a free-form string or
JSON policy to satisfy a semantic contract.

- [ ] **Step 4: Implement canonical partition ordering and manifest hashing**

```python
def manifest_body(manifest: DatasetManifestV1) -> dict[str, JSONValue]:
    body = canonical_data(manifest)
    assert isinstance(body, dict)
    partitions = body["partitions"]
    assert isinstance(partitions, list)
    body["partitions"] = sorted(
        partitions,
        key=lambda value: canonical_json(
            [value["partition_key"], value["artifact"]["content_hash"]]
        ),
    )
    return body


def manifest_hash(manifest: DatasetManifestV1) -> str:
    return content_hash(manifest_body(manifest))
```

- [ ] **Step 5: Run the focused tests and full M0 regression suite**

Run: `uv run pytest tests/unit/test_manifests.py tests/unit/test_manifest_hashing.py tests/unit/test_canonical_serialization.py tests/unit/test_domain_models.py -v`

Expected: all tests pass and existing M0 serialization behavior is unchanged.

- [ ] **Step 6: Commit manifest contracts**

```text
git add src/drift/domain/manifests.py src/drift/datasets tests/unit/test_manifests.py tests/unit/test_manifest_hashing.py
git commit -m "feat: add immutable dataset manifests"
```

### Task 3: Safe local artifact resolver and byte verification

**Files:**
- Create: `src/drift/datasets/resolver.py`
- Test: `tests/unit/test_dataset_resolver.py`
- Create: `tests/fixtures/datasets/files/valid.csv`
- Create: `tests/fixtures/datasets/files/changed.csv`

**Interfaces:**
- Consumes: `PartitionDescriptorV1` and M0 `SHA256Hash`.
- Produces: `ResolverLimits`, `VerifiedArtifactBytes`,
  `read_verified_local_artifact(root, relative_path, expected_hash, limits) -> VerifiedArtifactBytes`,
  and `verify_partition_bytes(partition, verified) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing traversal, symlink, size, and mismatch tests**

```python
def test_resolver_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ArtifactResolutionError, match="confined"):
        read_verified_local_artifact(tmp_path, "../secret.csv", "0" * 64, limits())


def test_resolver_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        read_verified_local_artifact(tmp_path, "data.csv", "0" * 64, limits())


def test_resolver_rejects_file_over_limit(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_bytes(b"12345")
    with pytest.raises(ArtifactResolutionError, match="size limit"):
        read_verified_local_artifact(
            tmp_path,
            "data.csv",
            sha256(b"12345").hexdigest(),
            ResolverLimits(max_bytes=4),
        )


def test_parsing_uses_verified_bytes_after_same_path_replacement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.csv"
    original = b"value\n1\n"
    path.write_bytes(original)
    verified = read_verified_local_artifact(
        tmp_path, "data.csv", sha256(original).hexdigest(), limits()
    )
    path.write_bytes(b"value\n9\n")
    assert verified.data == original
```

- [ ] **Step 2: Run the tests and confirm resolver imports fail**

Run: `uv run pytest tests/unit/test_dataset_resolver.py -v`

Expected: collection fails because the resolver does not exist.

- [ ] **Step 3: Implement confined, regular-file-only byte reads**

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
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ArtifactResolutionError("artifact path must be confined to its root")
    root_resolved = root.resolve(strict=True)
    candidate = (root_resolved / relative_path).resolve(strict=True)
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        raise ArtifactResolutionError("artifact must be a confined regular file")
    declared_size = candidate.stat().st_size
    if declared_size > limits.max_bytes:
        raise ArtifactResolutionError("artifact exceeds configured size limit")
    with candidate.open("rb") as stream:
        data = stream.read(limits.max_bytes + 1)
    byte_size = len(data)
    if byte_size > limits.max_bytes:
        raise ArtifactResolutionError("artifact exceeds configured size limit")
    digest = sha256(data).hexdigest()
    if digest != expected_hash:
        raise ArtifactIntegrityError("artifact SHA-256 does not match")
    return VerifiedArtifactBytes(
        data=data,
        byte_size=byte_size,
        content_hash=digest,
    )
```

Reject devices, FIFOs, symlink escapes, NULs, credential-like logical URIs, and
files over the bound before retaining their contents. All M1 synthetic parsers
must consume `VerifiedArtifactBytes.data`, never reopen its pathname. Do not parse
CSV, Parquet, archives, or object columns in this task. A future large-file
adapter must hash and parse the same open descriptor with before/after identity
checks, or consume an immutable content-addressed object.

- [ ] **Step 4: Run resolver tests and security-focused static checks**

Run: `uv run pytest tests/unit/test_dataset_resolver.py -v && uv run ruff check src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py && uv run mypy src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py`

Expected: all commands exit 0.

- [ ] **Step 5: Commit safe resolution**

```text
git add src/drift/datasets/resolver.py tests/unit/test_dataset_resolver.py tests/fixtures/datasets/files
git commit -m "feat: verify confined dataset artifacts"
```

### Task 4: Immutable fact revisions and cutoff resolution

**Files:**
- Create: `src/drift/domain/revisions.py`
- Create: `src/drift/domain/dataset_validation.py`
- Create: `src/drift/datasets/validation.py`
- Test: `tests/unit/test_revisions.py`

**Interfaces:**
- Consumes: Task 1 temporal models and M0 artifact/hash/JSON types.
- Produces: `FindingSeverity`, `ValidationFindingV1`, `DatasetValidationError`,
  `RevisionKind`, `LogicalFactKeyV1`, `FactVersionV1`,
  `validate_revision_chain(versions) -> tuple[ValidationFindingV1, ...]`, and
  `select_fact_version(versions, channel, cutoff) -> FactVersionV1 | None`.

- [ ] **Step 1: Write failing revision and selection tests**

```python
def test_cutoff_selects_original_before_restatement() -> None:
    original = eps_version("1.20", available=utc(2022, 5, 5), revision="initial")
    restated = eps_version(
        "0.90",
        available=utc(2022, 8, 10),
        revision="restatement",
        supersedes=original.fact_version_id,
    )
    assert (
        select_fact_version(
            (original, restated), original.availability[0].channel, utc(2022, 6, 1)
        )
        == original
    )


def test_revision_cycle_is_rejected() -> None:
    first, second = cyclic_versions()
    findings = validate_revision_chain((first, second))
    assert "revision_cycle" in {finding.code for finding in findings}


def test_unknown_availability_yields_no_version() -> None:
    version = fact_with_unknown_availability()
    assert (
        select_fact_version(
            (version,), version.availability[0].channel, utc(2030, 1, 1)
        )
        is None
    )
```

- [ ] **Step 2: Run the tests and confirm revisions are missing**

Run: `uv run pytest tests/unit/test_revisions.py -v`

Expected: collection fails on missing revision types.

- [ ] **Step 3: Implement immutable versions and deterministic selection**

```python
class ValidationFindingV1(FrozenModel):
    code: NonBlankStr
    severity: FindingSeverity
    message: NonBlankStr
    artifact_references: tuple[ArtifactReference, ...] = ()


class DatasetValidationError(DriftError):
    def __init__(self, findings: Sequence[ValidationFindingV1]) -> None:
        self.findings = tuple(findings)
        super().__init__("; ".join(item.code for item in self.findings))

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


def select_fact_version(
    versions: Sequence[FactVersionV1],
    channel: AvailabilityChannelV1,
    cutoff: datetime,
) -> FactVersionV1 | None:
    findings = validate_revision_chain(versions)
    if findings:
        raise DatasetValidationError(findings)
    candidates = [
        version
        for version in versions
        if any(
            definitely_available(evidence, channel, cutoff)
            for evidence in version.availability
        )
    ]
    if not candidates:
        return None
    by_id = {version.fact_version_id: version for version in candidates}
    superseded = {
        version.supersedes_fact_version_id
        for version in candidates
        if version.supersedes_fact_version_id in by_id
    }
    active = [
        version for version in candidates if version.fact_version_id not in superseded
    ]
    if len(active) != 1 or active[0].revision_kind is RevisionKind.WITHDRAWAL:
        return None
    return active[0]
```

Require the same logical key across a chain, unique IDs, an initial root, an
acyclic single-successor sequence, retained source artifacts, and one evidence
record per channel.

- [ ] **Step 4: Run revision and temporal tests**

Run: `uv run pytest tests/unit/test_revisions.py tests/unit/test_temporal.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit revision semantics**

```text
git add src/drift/domain/revisions.py src/drift/datasets/validation.py tests/unit/test_revisions.py
git commit -m "feat: preserve point-in-time fact revisions"
```

### Task 5: Scoped validation decisions and M0 bridge

**Files:**
- Modify: `src/drift/domain/dataset_validation.py`
- Create: `src/drift/datasets/references.py`
- Modify: `src/drift/datasets/validation.py`
- Test: `tests/unit/test_dataset_validation.py`
- Test: `tests/integration/test_m1_m0_compatibility.py`

**Interfaces:**
- Consumes: manifest hash, Task 1 channels, M0 `DatasetReference`, `ArtifactReference`, `TemporalCoverage`, and audit events.
- Produces: `ValidationScope`, `ValidationResult`, `UsageEligibility`,
  `DatasetUse`, `DatasetValidationDecisionV1`, `DatasetEligibilityBindingV1`,
  `BoundDatasetInputV1`,
  `validate_manifest_structure_findings(manifest, verified_artifacts) -> tuple[ValidationFindingV1, ...]`,
  `validate_manifest_structure(manifest, resolved_artifacts) -> DatasetValidationDecisionV1`,
  `validate_revised_fact_dataset(manifest, resolved_artifacts, fact_versions, checked_channel) -> DatasetValidationDecisionV1`,
  `build_validation_decision(manifest, validation_scope, result, usage_eligibility, declared_use, validated_coverage, checked_channels, findings) -> DatasetValidationDecisionV1`,
  `build_dataset_reference(manifest, manifest_reference, decision) -> DatasetReference`,
  `build_eligibility_binding(dataset_reference, decision, decision_reference, declared_use, channel, coverage) -> DatasetEligibilityBindingV1`,
  and `verify_bound_dataset_input(bound_input, declared_use, channel, coverage) -> tuple[ValidationFindingV1, ...]`.

- [ ] **Step 1: Write failing fail-closed eligibility and bridge tests**

```python
def test_manifest_only_validation_is_always_exploratory() -> None:
    decision = validate_manifest_structure(valid_manifest(), resolved_files())
    assert decision.result is ValidationResult.PASS
    assert decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert decision.usage_eligibility is UsageEligibility.EXPLORATORY_ONLY


def test_unknown_record_availability_is_exploratory_only() -> None:
    decision = validate_revised_fact_dataset(
        revised_fact_manifest(),
        resolved_files(),
        (fact_with_unknown_availability(),),
        public_channel(),
    )
    assert decision.result is ValidationResult.PASS
    assert decision.validation_scope is ValidationScope.RECORDS_AND_EVENTS
    assert decision.usage_eligibility is UsageEligibility.EXPLORATORY_ONLY


def test_reference_hash_must_equal_manifest_and_artifact_hash() -> None:
    current = valid_manifest()
    decision = eligible_decision(current)
    with pytest.raises(DatasetValidationError, match="manifest hash"):
        build_dataset_reference(current, artifact(digest="0" * 64), decision)


def test_exploratory_decision_cannot_create_eligibility_binding() -> None:
    current = valid_manifest()
    decision = manifest_only_decision(current)
    reference = build_dataset_reference(current, manifest_artifact(current), decision)
    with pytest.raises(DatasetValidationError, match="historical eligibility"):
        build_eligibility_binding(
            reference,
            decision,
            decision_artifact(decision),
            DatasetUse.REVISED_FACT_HISTORY,
            public_channel(),
            full_coverage(current),
        )


def test_binding_rejects_unchecked_channel_or_coverage() -> None:
    current, reference, decision = eligible_revised_fact_dataset()
    with pytest.raises(DatasetValidationError, match="channel or coverage"):
        build_eligibility_binding(
            reference,
            decision,
            decision_artifact(decision),
            DatasetUse.REVISED_FACT_HISTORY,
            vendor_channel("other", "1"),
            full_coverage(current),
        )


def test_m0_fixture_serialization_and_event_hashes_are_unchanged() -> None:
    assert canonical_json(existing_m0_dataset_reference()) == M0_REFERENCE_BYTES
    assert compute_event_hash(existing_m0_unsigned_event()) == M0_EVENT_HASH
```

- [ ] **Step 2: Run the tests and confirm validation-decision types are missing**

Run: `uv run pytest tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py -v`

Expected: collection fails without the new modules; existing M0 tests still pass.

- [ ] **Step 3: Implement immutable findings and scoped decisions**

```python
class DatasetValidationDecisionV1(FrozenModel):
    decision_id: UUID7
    manifest_hash: SHA256Hash
    validator_version: NonBlankStr
    validator_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    usage_eligibility: UsageEligibility
    declared_use: DatasetUse
    validated_coverage: ValidPeriodV1
    checked_channels: tuple[AvailabilityChannelV1, ...]
    checked_dataset_kinds: tuple[DatasetKind, ...]
    findings: tuple[ValidationFindingV1, ...]


class DatasetEligibilityBindingV1(FrozenModel):
    binding_id: UUID7
    dataset_reference: DatasetReference
    validation_decision_id: UUID7
    validation_decision_reference: ArtifactReference
    declared_use: DatasetUse
    channel: AvailabilityChannelV1
    validated_coverage: ValidPeriodV1


@dataclass(frozen=True, slots=True)
class BoundDatasetInputV1:
    manifest: DatasetManifestV1
    verified_artifacts: tuple[VerifiedArtifactBytes, ...]
    validation_decision: DatasetValidationDecisionV1
    eligibility_binding: DatasetEligibilityBindingV1
```

Enforce `PASS` only with no error findings. `HISTORICAL_EVALUATION_ELIGIBLE`
requires `PASS`, `RECORDS_AND_EVENTS` scope, a checked channel, exact or
conservatively bounded evidence for all required records, complete hashes and
lineage, and all dataset-kind semantic validators. Manifest-only validation is
always `EXPLORATORY_ONLY`. The M1a record validator reads the synthetic JSON
fact fixtures, verifies their partition byte hash and schema, constructs
`FactVersionV1` values, and checks every record. A later real-format adapter must
provide its own versioned implementation and cannot reuse the fixture validator
hash.

- [ ] **Step 4: Implement the additive `DatasetReference` bridge**

```python
def build_dataset_reference(
    manifest: DatasetManifestV1,
    manifest_reference: ArtifactReference,
    decision: DatasetValidationDecisionV1,
) -> DatasetReference:
    digest = manifest_hash(manifest)
    has_corporate_actions = any(
        contract.kind is ContractKind.CORPORATE_ACTIONS
        for contract in manifest.semantic_contracts
    )
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
        point_in_time_policy=manifest.temporal_contract.policy_id,
        corporate_action_policy=(
            "source_events_v1" if has_corporate_actions else "not_applicable"
        ),
        availability_timestamp_policy=(
            manifest.temporal_contract.evidence_granularity.value
        ),
        manifest_reference=manifest_reference,
    )
```

If the manifest lacks a corporate-action contract, use the explicit summary
`not_applicable`, never an empty string. Do not modify `DatasetReference`.

Implement `build_eligibility_binding` as the permission boundary. Require the
decision reference hash to equal `content_hash(decision)`, the dataset reference
hash to equal `decision.manifest_hash`, result `PASS`, scope
`RECORDS_AND_EVENTS`, eligibility `HISTORICAL_EVALUATION_ELIGIBLE`, exact
declared-use equality, the requested channel in `checked_channels`, and requested
coverage contained by `validated_coverage`. `build_dataset_reference` alone
produces provenance only. A future evaluator must accept the binding, not a bare
reference, before evidence can contribute to promotion.

Define `DatasetUse` with separate closed values for revised facts, identity
history, universe history, corporate-action/termination history, calendar
history, and equity market history. `verify_bound_dataset_input` requires the
manifest hash, every partition's verified byte hash, decision hash, binding
hash/reference, declared use, channel, and coverage to match. The runtime
dataclass deliberately carries the exact verified byte values, which are not
serialized into M0 or the manifest.

- [ ] **Step 5: Verify M0 replay and hash compatibility**

Run: `uv run pytest tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py tests/integration/test_replay.py tests/integration/test_tamper_detection.py -v`

Expected: all tests pass; the pinned M0 reference bytes and event hash are exact.

- [ ] **Step 6: Commit validation evidence and bridge**

```text
git add src/drift/domain/dataset_validation.py src/drift/datasets tests/unit/test_dataset_validation.py tests/integration/test_m1_m0_compatibility.py
git commit -m "feat: gate dataset references with validation evidence"
```

### Task 6: M1a adversarial fixtures and audit-event integration

**Files:**
- Create: `tests/fixtures/datasets/m1a/*.json`
- Create: `tests/integration/test_m1a_leakage.py`
- Create: `tests/integration/test_m1_dataset_audit.py`

**Interfaces:**
- Consumes: Tasks 1 through 5.
- Produces: pinned fixtures for late earnings, restatements, vendor delay, late
  local ingestion, date-only release, macro revision, correction, withdrawal,
  missing bar, bad bytes, schema drift, and hostile paths; audit payload
  conventions for `dataset.manifest.recorded`, `dataset.validation.completed`,
  `dataset.eligibility.bound`, and `dataset.superseded`.

- [ ] **Step 1: Add small source-like fixture bytes and expected cutoff table**

Create JSON fixtures whose top-level object contains `case_id`, `channel`,
`cutoffs`, `fact_versions`, and `expected_fact_version_id`. Use fixed UUIDv7
values, UTC timestamps, and SHA-256 hashes. Include this date-only case:

```json
{
  "case_id": "date-only-release",
  "channel": {"kind": "public", "identifier": "issuer-site", "version": "1"},
  "cutoffs": [
    {"at": "2022-05-05T12:00:00.000000Z", "expected": null},
    {"at": "2022-05-06T00:00:00.000000Z", "expected": "0180a111-1111-7111-8111-111111111111"}
  ]
}
```

- [ ] **Step 2: Write parameterized failing leakage tests**

```python
class CutoffExpectationV1(FrozenModel):
    at: UTCDateTime
    expected: UUID7 | None


class M1AFixtureCase(FrozenModel):
    case_id: NonBlankStr
    channel: AvailabilityChannelV1
    cutoffs: tuple[CutoffExpectationV1, ...]
    versions: tuple[FactVersionV1, ...]


def parse_m1a_case(data: bytes) -> M1AFixtureCase:
    return M1AFixtureCase.model_validate_json(data)


@pytest.mark.parametrize("case_path", sorted(M1A_FIXTURES.glob("*.json")))
def test_m1a_fixture_never_selects_a_future_version(case_path: Path) -> None:
    verified = read_verified_local_artifact(
        M1A_FIXTURES,
        case_path.name,
        EXPECTED_FIXTURE_HASHES[case_path.name],
        ResolverLimits(max_bytes=64_000),
    )
    case = parse_m1a_case(verified.data)
    for cutoff in case.cutoffs:
        selected = select_fact_version(case.versions, case.channel, cutoff.at)
        selected_id = None if selected is None else selected.fact_version_id
        assert selected_id == cutoff.expected
```

- [ ] **Step 3: Run the fixtures and fix only contract or fixture defects**

Run: `uv run pytest tests/integration/test_m1a_leakage.py -v`

Expected: all listed cases pass without adding source-specific production adapters.

- [ ] **Step 4: Write and pass audit integration tests**

```python
def test_manifest_and_validation_events_replay_without_schema_changes(
    tmp_path: Path,
) -> None:
    ledger = SQLiteAuditLedger(tmp_path / "ledger.sqlite3")
    manifest_event, validation_event, binding_event = dataset_events(
        eligible_revised_fact_dataset()
    )
    for event in (manifest_event, validation_event, binding_event):
        ledger.append(event)
    assert verify_chain(ledger.list_events()).valid
    assert replay_events(ledger.list_events()) == (
        manifest_event,
        validation_event,
        binding_event,
    )
```

Payloads contain schema version `1`, manifest or decision hashes, and compact
references. Do not put raw datasets, license prose, credentials, or physical
paths in SQLite.

- [ ] **Step 5: Run the M1a and complete M0 gates**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: all commands exit 0.

- [ ] **Step 6: Commit M1a adversarial evidence**

```text
git add tests/fixtures/datasets/m1a tests/integration/test_m1a_leakage.py tests/integration/test_m1_dataset_audit.py
git commit -m "test: prove temporal leakage is rejected"
```

### Task 7: M1a review gate

**Files:**
- Modify only files from Tasks 1 through 6 when review finds a concrete defect.
- Test: all M0 and M1a tests.

**Interfaces:**
- Consumes: the complete M1a diff.
- Produces: a review record in the implementing task's commentary and a clean, tested M1a checkpoint. It does not mark M1 complete.

- [ ] **Step 1: Review M1a against every spec section through validation eligibility**

Confirm exact-byte hashing, storage neutrality, unknown preservation,
channel-specific evidence, bounded date semantics, revision immutability,
license/source provenance, derived lineage, M0 compatibility, and hostile-path
limits each have a direct test.

- [ ] **Step 2: Run explicit scope and compatibility scans**

Run: `rg -n "(robinhood|alpaca|place_order|submit_order|api[_-]?key|oauth|langgraph|openai|rd-agent)" src tests pyproject.toml`

Expected: no capability is added. Inspect every textual match rather than
assuming a name is a violation.

Run: `git diff 4587745 -- src/drift/domain/datasets.py src/drift/domain/artifacts.py src/drift/domain/experiments.py src/drift/domain/events.py src/drift/serialization/canonical.py`

Expected: no diff in M0 compatibility-sensitive files.

- [ ] **Step 3: Run the complete gate and checkpoint M1a**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build && git status --short`

Expected: verification passes. Git status is clean after any review-fix commit.
Checkpoint the verified commit, but state that M1b is still required.

---

## Phase M1b: Historical market semantics

### Task 8: Stable security, listing, and identifier mappings

**Files:**
- Create: `src/drift/domain/securities.py`
- Create: `src/drift/datasets/market_validation.py`
- Test: `tests/unit/test_securities.py`

**Interfaces:**
- Consumes: Task 1 validity and availability models.
- Produces: `IssuerV1`, `SecurityV1`, `ListingV1`, `IdentifierScope`,
  `IdentifierMappingV1`,
  `validate_identifier_mappings(mappings) -> tuple[ValidationFindingV1, ...]`,
  and `validate_security_identity(issuers, securities, listings, mappings) -> tuple[ValidationFindingV1, ...]`.

- [ ] **Step 1: Write failing ticker reuse, rename, overlap, and share-class tests**

```python
def test_ticker_reuse_maps_to_distinct_security_ids() -> None:
    old, new = reused_ticker_mappings()
    assert old.internal_id != new.internal_id
    assert old.valid_period.ended_at <= new.valid_period.started_at
    assert not validate_identifier_mappings((old, new))


def test_overlapping_same_venue_ticker_mapping_is_rejected() -> None:
    first, second = overlapping_ticker_mappings()
    findings = validate_identifier_mappings((first, second))
    assert "ambiguous_identifier_mapping" in {item.code for item in findings}


def test_two_share_classes_never_collapse_to_issuer_identity() -> None:
    issuer, class_a, class_b = issuer_with_two_share_classes()
    assert class_a.issuer_id == class_b.issuer_id == issuer.issuer_id
    assert class_a.security_id != class_b.security_id
```

- [ ] **Step 2: Run the tests and confirm identity types are missing**

Run: `uv run pytest tests/unit/test_securities.py -v`

Expected: collection fails on missing identity types.

- [ ] **Step 3: Implement opaque IDs and dated mappings**

```python
class IdentifierMappingV1(FrozenModel):
    mapping_id: UUID7
    scope: IdentifierScope
    internal_id: UUID7
    identifier_type: NonBlankStr
    identifier_value: NonBlankStr
    venue: NonBlankStr | None = None
    valid_period: ValidPeriodV1
    availability: AvailabilityEvidenceV1
    source_revision: NonBlankStr
```

Require listing-scoped ticker mappings to name a venue, prohibit self-inconsistent
valid intervals, and report overlap for the same type/value/venue unless a later
explicit ambiguity contract is added. Never infer continuity from equal text.

- [ ] **Step 4: Run identity tests, lint, and mypy**

Run: `uv run pytest tests/unit/test_securities.py -v && uv run ruff check src/drift/domain/securities.py src/drift/datasets/market_validation.py tests/unit/test_securities.py && uv run mypy src/drift/domain/securities.py src/drift/datasets/market_validation.py tests/unit/test_securities.py`

Expected: all commands exit 0.

- [ ] **Step 5: Commit identity contracts**

```text
git add src/drift/domain/securities.py src/drift/datasets/market_validation.py tests/unit/test_securities.py
git commit -m "feat: add stable historical security identity"
```

### Task 9: Point-in-time universe membership

**Files:**
- Create: `src/drift/domain/universes.py`
- Modify: `src/drift/datasets/market_validation.py`
- Test: `tests/unit/test_universes.py`

**Interfaces:**
- Consumes: stable security/listing IDs, Task 1 temporal evidence, and typed findings.
- Produces: `UniverseEligibilityBasis`, `UniverseDefinitionV1`,
  `MembershipAction`, `UniverseMembershipV1`,
  `validate_membership(events, listings) -> tuple[ValidationFindingV1, ...]`,
  and `is_universe_member(events, universe_id, listing_id, listings, channel, cutoff) -> bool`.

- [ ] **Step 1: Write failing current-snapshot and listing-bound tests**

```python
def test_june_addition_is_not_member_in_january() -> None:
    event = index_addition(effective=utc(2022, 6, 1), available=utc(2022, 5, 20))
    assert not is_universe_member(
        (event,),
        event.universe_id,
        event.listing_id,
        (active_listing(event.listing_id),),
        event.availability.channel,
        utc(2022, 1, 15),
    )
    assert is_universe_member(
        (event,),
        event.universe_id,
        event.listing_id,
        (active_listing(event.listing_id),),
        event.availability.channel,
        utc(2022, 6, 1),
    )


def test_membership_outside_listing_period_is_rejected() -> None:
    findings = validate_membership(
        (membership_before_listing(),), (listing_starting_later(),)
    )
    assert "membership_outside_listing" in {item.code for item in findings}


def test_event_from_another_universe_never_grants_membership() -> None:
    event = index_addition()
    assert not is_universe_member(
        (event,),
        new_entity_id(),
        event.listing_id,
        (active_listing(event.listing_id),),
        event.availability.channel,
        event.effective_period.started_at,
    )


def test_terminated_listing_is_not_a_member_after_last_tradable_time() -> None:
    event = index_addition()
    listing = listing_ending_before(event.effective_period.ended_at)
    assert not is_universe_member(
        (event,),
        event.universe_id,
        event.listing_id,
        (listing,),
        event.availability.channel,
        listing.tradable_period.ended_at,
    )


def test_conflicting_equal_sequence_events_are_rejected() -> None:
    first, second = conflicting_membership_events()
    findings = validate_membership((first, second), (active_listing(first.listing_id),))
    assert "membership_sequence_conflict" in {item.code for item in findings}
```

- [ ] **Step 2: Run the tests and confirm universe types are missing**

Run: `uv run pytest tests/unit/test_universes.py -v`

Expected: collection fails on missing universe types.

- [ ] **Step 3: Implement effective membership with availability cutoff**

```python
class UniverseMembershipV1(FrozenModel):
    membership_id: UUID7
    source_event_id: NonBlankStr
    universe_id: UUID7
    listing_id: UUID7
    effective_period: ValidPeriodV1
    availability: AvailabilityEvidenceV1
    action: MembershipAction
    source_sequence: Annotated[int, Field(ge=0)]
    supersedes_membership_id: UUID7 | None = None
    source_revision: NonBlankStr


def is_universe_member(
    events: Sequence[UniverseMembershipV1],
    universe_id: UUID7,
    listing_id: UUID7,
    listings: Sequence[ListingV1],
    channel: AvailabilityChannelV1,
    cutoff: datetime,
) -> bool:
    findings = validate_membership(events, listings)
    if findings:
        raise DatasetValidationError(findings)
    listing = next(
        (candidate for candidate in listings if candidate.listing_id == listing_id),
        None,
    )
    if listing is None or not listing.tradable_period.contains(cutoff):
        return False
    eligible = [
        event
        for event in events
        if event.universe_id == universe_id
        and event.listing_id == listing_id
        and event.effective_period.contains(cutoff)
        and definitely_available(event.availability, channel, cutoff)
    ]
    if not eligible:
        return False
    latest = max(eligible, key=lambda event: event.source_sequence)
    return latest.action is MembershipAction.ADD
```

Validate unique Drift membership IDs, provider source-event IDs, and source
sequences per universe/listing,
acyclic same-key correction links, single successors, nonconflicting effective
intervals, and membership within the listing's tradable period. Reject equal
sequence conflicts rather than using input order. Preserve explicit additions,
removals, and corrections. Absence from a snapshot is never synthesized into a
removal.

- [ ] **Step 4: Run universe and identity tests**

Run: `uv run pytest tests/unit/test_universes.py tests/unit/test_securities.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit universe contracts**

```text
git add src/drift/domain/universes.py src/drift/datasets/market_validation.py tests/unit/test_universes.py
git commit -m "feat: add historical universe membership"
```

### Task 10: Corporate actions, terminations, and price basis

**Files:**
- Create: `src/drift/domain/corporate_actions.py`
- Modify: `src/drift/datasets/market_validation.py`
- Test: `tests/unit/test_corporate_actions.py`

**Interfaces:**
- Consumes: stable IDs, availability evidence, M0 artifact references, and typed findings.
- Produces: `PriceBasis`, `CorporateActionType`, `CorporateActionEventV1`,
  `TerminationStatus`, `ListingTerminationEventV1`,
  `validate_action_versions(actions) -> tuple[ValidationFindingV1, ...]`,
  `validate_termination_versions(terminations) -> tuple[ValidationFindingV1, ...]`,
  `validate_corporate_actions(actions, listings) -> tuple[ValidationFindingV1, ...]`,
  `select_action_version(actions, logical_action_key, channel, cutoff) -> CorporateActionEventV1 | None`,
  and `action_known(action, channel, cutoff) -> bool`.

- [ ] **Step 1: Write failing future split, dividend, and delisting tests**

```python
def test_future_split_is_not_known_at_feature_cutoff() -> None:
    action = split_action(available=utc(2022, 8, 1), effective=utc(2022, 8, 15))
    assert not action_known(action, action.availability.channel, utc(2022, 7, 31))


def test_unknown_delisting_value_remains_unknown() -> None:
    event = unknown_delisting()
    assert event.final_value is None
    assert event.delisting_return is None
    assert event.outcome_known is False


def test_raw_and_total_return_price_basis_are_distinct() -> None:
    assert PriceBasis.RAW != PriceBasis.TOTAL_RETURN_ADJUSTED


def test_vendor_correction_applies_only_after_its_availability() -> None:
    original, corrected = corrected_split_versions()
    assert (
        select_action_version(
            (original, corrected),
            original.logical_action_key,
            original.availability.channel,
            utc(2022, 7, 1),
        )
        == original
    )
    assert (
        select_action_version(
            (original, corrected),
            original.logical_action_key,
            original.availability.channel,
            utc(2022, 8, 2),
        )
        == corrected
    )


def test_action_revision_cycle_is_rejected() -> None:
    first, second = cyclic_action_versions()
    findings = validate_action_versions((first, second))
    assert "action_revision_cycle" in {item.code for item in findings}
```

- [ ] **Step 2: Run the tests and confirm action types are missing**

Run: `uv run pytest tests/unit/test_corporate_actions.py -v`

Expected: collection fails on missing action models.

- [ ] **Step 3: Implement source events without return calculation**

```python
class CorporateActionEventV1(FrozenModel):
    event_id: UUID7
    logical_action_key: NonBlankStr
    security_id: UUID7
    listing_id: UUID7 | None = None
    action_type: CorporateActionType
    availability: AvailabilityEvidenceV1
    effective_at: UTCDateTime | None = None
    ex_at: UTCDateTime | None = None
    record_at: UTCDateTime | None = None
    payable_at: UTCDateTime | None = None
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None
    cash_amount: Decimal | None = None
    cash_currency: NonBlankStr | None = None
    child_security_id: UUID7 | None = None
    successor_security_id: UUID7 | None = None
    source_terms: ArtifactReference
    source_sequence: Annotated[int, Field(ge=0)]
    revision_kind: RevisionKind
    supersedes_event_id: UUID7 | None = None
    source_revision: NonBlankStr


class ListingTerminationEventV1(FrozenModel):
    event_id: UUID7
    logical_termination_key: NonBlankStr
    listing_id: UUID7
    availability: AvailabilityEvidenceV1
    last_trade_at: UTCDateTime | None
    effective_at: UTCDateTime
    status: TerminationStatus
    reason_family: TerminationReason
    successor_security_id: UUID7 | None = None
    final_value: Decimal | None = None
    final_value_currency: NonBlankStr | None = None
    delisting_return: Decimal | None = None
    outcome_known: bool
    source_terms: ArtifactReference
    source_sequence: Annotated[int, Field(ge=0)]
    revision_kind: RevisionKind
    supersedes_event_id: UUID7 | None = None
    source_revision: NonBlankStr


def select_action_version(
    actions: Sequence[CorporateActionEventV1],
    logical_action_key: str,
    channel: AvailabilityChannelV1,
    cutoff: datetime,
) -> CorporateActionEventV1 | None:
    matching = tuple(
        action for action in actions if action.logical_action_key == logical_action_key
    )
    findings = validate_action_versions(matching)
    if findings:
        raise DatasetValidationError(findings)
    available = tuple(
        action for action in matching if action_known(action, channel, cutoff)
    )
    superseded = {
        action.supersedes_event_id
        for action in available
        if action.supersedes_event_id is not None
    }
    active = tuple(action for action in available if action.event_id not in superseded)
    if len(active) != 1 or active[0].revision_kind is RevisionKind.WITHDRAWAL:
        return None
    return active[0]
```

Validate type-specific required term pairs, positive split ratios, cash/currency
pairs, identity references, unique and monotonic source sequences, matching
logical keys, same-key predecessor links, one successor, and acyclic action and
termination chains. If `last_trade_at` is known, require it not to follow
`effective_at`; preserve unknown rather than deriving it. Implement the same
cutoff resolution for terminations. Do not implement adjustment, position
conversion, cash posting, total-return, tax, settlement, or imputation.

- [ ] **Step 4: Run action and market validation tests**

Run: `uv run pytest tests/unit/test_corporate_actions.py tests/unit/test_securities.py tests/unit/test_universes.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit market action contracts**

```text
git add src/drift/domain/corporate_actions.py src/drift/datasets/market_validation.py tests/unit/test_corporate_actions.py
git commit -m "feat: record point-in-time corporate actions"
```

### Task 11: Calendar references and session observations

**Files:**
- Create: `src/drift/domain/calendars.py`
- Modify: `src/drift/datasets/market_validation.py`
- Test: `tests/unit/test_calendars.py`

**Interfaces:**
- Consumes: availability evidence and M0 artifact references.
- Produces: `SessionKind`, `SessionStatus`, `CalendarReferenceV1`, `SessionObservationV1`, and `validate_sessions(reference, sessions) -> tuple[ValidationFindingV1, ...]`.

- [ ] **Step 1: Write failing early-close, DST, and session-label tests**

```python
def test_early_close_uses_explicit_utc_boundary() -> None:
    session = early_close_session()
    assert session.regular_close_at_utc == utc(2022, 11, 25, 18)
    assert session.status is SessionStatus.EARLY_CLOSE


def test_invalid_iana_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="IANA"):
        calendar_reference(timezone="US/Eastern-ish")


def test_overnight_session_may_open_before_local_label_date() -> None:
    session = overnight_session()
    assert session.regular_open_at_utc < session.regular_close_at_utc
    assert session.session_date_local.isoformat() == "2022-06-02"


def test_session_from_another_calendar_hash_is_rejected() -> None:
    reference = calendar_reference(schedule_hash="a" * 64)
    session = session_observation(schedule_hash="b" * 64)
    findings = validate_sessions(reference, (session,))
    assert "calendar_binding_mismatch" in {item.code for item in findings}
```

- [ ] **Step 2: Run the tests and confirm calendar types are missing**

Run: `uv run pytest tests/unit/test_calendars.py -v`

Expected: collection fails on missing calendar models.

- [ ] **Step 3: Implement immutable calendar identity and observed sessions**

```python
class CalendarReferenceV1(FrozenModel):
    calendar_id: NonBlankStr
    calendar_version: NonBlankStr
    timezone: NonBlankStr
    coverage: ValidPeriodV1
    schedule_artifact: ArtifactReference
    schedule_hash: SHA256Hash
    source_reference: ArtifactReference
    availability: AvailabilityEvidenceV1


class SessionObservationV1(FrozenModel):
    calendar_id: NonBlankStr
    calendar_version: NonBlankStr
    schedule_hash: SHA256Hash
    venue: NonBlankStr
    session_date_local: date
    regular_open_at_utc: UTCDateTime | None
    regular_close_at_utc: UTCDateTime | None
    kind: SessionKind
    status: SessionStatus
    availability: AvailabilityEvidenceV1
```

Validate IANA timezone, source and schedule hashes, coverage, ordered UTC
boundaries, closed-session null boundaries, duplicate venue/date records, and
exact calendar ID/version/schedule-hash equality for every session. Do not
calculate holidays or daylight-saving transitions.

- [ ] **Step 4: Run calendar and temporal tests**

Run: `uv run pytest tests/unit/test_calendars.py tests/unit/test_temporal.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit session contracts**

```text
git add src/drift/domain/calendars.py src/drift/datasets/market_validation.py tests/unit/test_calendars.py
git commit -m "feat: bind datasets to versioned market sessions"
```

### Task 12: Parsed market observations and complete M1b eligibility gate

**Files:**
- Create: `src/drift/domain/market_data.py`
- Modify: `src/drift/datasets/market_validation.py`
- Modify: `src/drift/datasets/validation.py`
- Test: `tests/unit/test_market_data.py`
- Create: `tests/fixtures/datasets/m1b/*.json`
- Create: `tests/integration/test_m1b_market_leakage.py`
- Test: `tests/integration/test_m1_eligibility.py`

**Interfaces:**
- Consumes: all M1a and M1b contracts.
- Produces: `TimestampConvention`, `ObservationStatus`, `BarIntervalUnit`,
  `BarIntervalV1`, `MarketObservationV1`, `MarketDependencyInputsV1`,
  `ParsedMarketDependenciesV1`,
  `validate_identity_dataset(manifest, verified_artifacts, channel, coverage) -> DatasetValidationDecisionV1`,
  `validate_universe_dataset(manifest, verified_artifacts, channel, coverage) -> DatasetValidationDecisionV1`,
  `validate_corporate_action_dataset(manifest, verified_artifacts, channel, coverage) -> DatasetValidationDecisionV1`,
  `validate_calendar_dataset(manifest, verified_artifacts, channel, coverage) -> DatasetValidationDecisionV1`,
  `parse_market_observations(verified_artifacts) -> tuple[MarketObservationV1, ...]`,
  `parse_and_validate_market_dependencies(inputs, channel, coverage) -> ParsedMarketDependenciesV1`,
  `validate_market_contract_hashes(manifest, inputs) -> tuple[ValidationFindingV1, ...]`,
  `validate_market_observations(observations, parsed_dependencies, universe_id, channel, coverage) -> tuple[ValidationFindingV1, ...]`,
  and `validate_market_dataset(manifest, verified_artifacts, dependency_inputs, universe_id, channel, coverage) -> DatasetValidationDecisionV1`;
  plus end-to-end fixtures for historical identity, universe, actions,
  delistings, price basis, missing bars, and sessions.

- [ ] **Step 1: Write failing market-record and eligibility tests**

```python
def test_manifest_raw_claim_cannot_hide_adjusted_record() -> None:
    case = valid_market_case(
        market_record_updates={"price_basis": "total_return_adjusted"}
    )
    decision = validate_market_dataset(
        case.manifest,
        case.verified_artifacts,
        case.dependency_inputs,
        case.universe_id,
        case.channel,
        case.coverage,
    )
    assert decision.result is ValidationResult.FAIL
    assert "non_raw_market_observation" in {item.code for item in decision.findings}


def test_vendor_channel_mismatch_cannot_be_eligible() -> None:
    case = valid_market_case()
    decision = validate_market_dataset(
        case.manifest,
        case.verified_artifacts,
        case.dependency_inputs,
        case.universe_id,
        vendor_channel("other-vendor", "1"),
        case.coverage,
    )
    assert decision.usage_eligibility is UsageEligibility.EXPLORATORY_ONLY


def test_complete_inspected_raw_records_can_be_eligible() -> None:
    case = valid_market_case()
    decision = validate_market_dataset(
        case.manifest,
        case.verified_artifacts,
        case.dependency_inputs,
        case.universe_id,
        case.channel,
        case.coverage,
    )
    assert decision.validation_scope is ValidationScope.RECORDS_AND_EVENTS
    assert decision.declared_use is DatasetUse.EQUITY_MARKET_HISTORY
    assert decision.validated_coverage == case.coverage
    assert decision.checked_channels == (case.channel,)
    assert decision.usage_eligibility is (
        UsageEligibility.HISTORICAL_EVALUATION_ELIGIBLE
    )
```

- [ ] **Step 2: Run the tests and confirm market-record types are missing**

Run: `uv run pytest tests/unit/test_market_data.py tests/integration/test_m1_eligibility.py -v`

Expected: collection fails because `drift.domain.market_data` and the complete
market validator do not exist.

- [ ] **Step 3: Implement parsed raw observations and bound dependency inputs**

```python
class BarIntervalV1(FrozenModel):
    count: Annotated[int, Field(gt=0)]
    unit: BarIntervalUnit


class MarketObservationV1(FrozenModel):
    observation_id: UUID7
    source_record_id: NonBlankStr
    listing_id: UUID7
    venue: NonBlankStr
    valid_period: ValidPeriodV1
    availability: AvailabilityEvidenceV1
    session_date_local: date
    interval: BarIntervalV1
    timestamp_convention: TimestampConvention
    calendar_id: NonBlankStr
    calendar_version: NonBlankStr
    schedule_hash: SHA256Hash
    price_basis: PriceBasis
    status: ObservationStatus
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: Decimal | None = None
    missing_reason: NonBlankStr | None = None


@dataclass(frozen=True, slots=True)
class MarketDependencyInputsV1:
    identity: BoundDatasetInputV1
    universe: BoundDatasetInputV1
    corporate_actions: BoundDatasetInputV1
    calendar: BoundDatasetInputV1


class ParsedMarketDependenciesV1(FrozenModel):
    issuers: tuple[IssuerV1, ...]
    securities: tuple[SecurityV1, ...]
    listings: tuple[ListingV1, ...]
    identifier_mappings: tuple[IdentifierMappingV1, ...]
    memberships: tuple[UniverseMembershipV1, ...]
    actions: tuple[CorporateActionEventV1, ...]
    terminations: tuple[ListingTerminationEventV1, ...]
    calendar_reference: CalendarReferenceV1
    sessions: tuple[SessionObservationV1, ...]
    findings: tuple[ValidationFindingV1, ...]
```

`PRESENT` observations require raw OHLCV fields and no missing reason. `MISSING`
requires null values and a reason. `HALTED` and `ZERO_VOLUME` remain distinct
states. Require positive intervals, internally consistent OHLC values, exact
calendar ID/version/hash binding, and one channel-scoped availability record.

- [ ] **Step 4: Implement the record-and-event validator**

```python
def validate_market_dataset(
    manifest: DatasetManifestV1,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    dependency_inputs: MarketDependencyInputsV1,
    universe_id: UUID7,
    channel: AvailabilityChannelV1,
    coverage: ValidPeriodV1,
) -> DatasetValidationDecisionV1:
    try:
        observations = parse_market_observations(verified_artifacts)
        dependencies = parse_and_validate_market_dependencies(
            dependency_inputs,
            channel,
            coverage,
        )
    except DatasetValidationError as error:
        return build_validation_decision(
            manifest=manifest,
            validation_scope=ValidationScope.RECORDS_AND_EVENTS,
            result=ValidationResult.FAIL,
            usage_eligibility=UsageEligibility.EXPLORATORY_ONLY,
            declared_use=DatasetUse.EQUITY_MARKET_HISTORY,
            validated_coverage=coverage,
            checked_channels=(channel,),
            findings=error.findings,
        )
    findings = [
        *validate_manifest_structure_findings(manifest, verified_artifacts),
        *validate_market_contract_hashes(manifest, dependency_inputs),
        *dependencies.findings,
        *validate_security_identity(
            dependencies.issuers,
            dependencies.securities,
            dependencies.listings,
            dependencies.identifier_mappings,
        ),
        *validate_membership(dependencies.memberships, dependencies.listings),
        *validate_action_versions(dependencies.actions),
        *validate_corporate_actions(dependencies.actions, dependencies.listings),
        *validate_termination_versions(dependencies.terminations),
        *validate_sessions(dependencies.calendar_reference, dependencies.sessions),
        *validate_market_observations(
            observations, dependencies, universe_id, channel, coverage
        ),
    ]
    errors = tuple(
        finding for finding in findings if finding.severity is FindingSeverity.ERROR
    )
    uncertainty_codes = {
        "unknown_availability",
        "unapproved_availability_rule",
        "channel_not_checked",
        "coverage_not_inspected",
    }
    eligibility = UsageEligibility.EXPLORATORY_ONLY
    if not errors and not uncertainty_codes.intersection(
        finding.code for finding in findings
    ):
        eligibility = UsageEligibility.HISTORICAL_EVALUATION_ELIGIBLE
    return build_validation_decision(
        manifest=manifest,
        validation_scope=ValidationScope.RECORDS_AND_EVENTS,
        result=ValidationResult.FAIL if errors else ValidationResult.PASS,
        usage_eligibility=eligibility,
        declared_use=DatasetUse.EQUITY_MARKET_HISTORY,
        validated_coverage=coverage,
        checked_channels=(channel,),
        findings=tuple(findings),
    )
```

`validate_market_contract_hashes` requires a
`MarketObservationContractV1` and exact equality between its four dependency
hashes and the canonical manifest hash in each `MarketDependencyInputsV1` member.
`parse_and_validate_market_dependencies` calls `verify_bound_dataset_input` for
the required identity, universe, action, and calendar `DatasetUse`, channel, and
coverage, then parses issuers, securities, mappings, memberships, actions,
terminations, and sessions from each bound input's exact verified bytes. It
returns no caller-supplied record object. Any binding, hash, use, channel,
coverage, or parse failure becomes a finding and blocks eligibility.

The four dependency validators follow the same pattern as the revised-fact
validator: verify manifest and partition bytes, parse every record from those
bytes, run the Task 8 through 11 cross-record validators, set the exact dependency
`DatasetUse`, channel, and inspected coverage, and grant eligibility only for
`RECORDS_AND_EVENTS` scope with no errors or temporal uncertainty. Their
eligibility bindings are created by Task 5's unchanged gate.

`validate_market_observations` iterates every parsed market record, rejects
non-raw or unknown price basis, requires its listing and session to exist and
cover the record, checks its exact schedule hash and timestamp convention,
checks availability for the requested channel, preserves explicit missingness,
and invokes point-in-time universe and action-chain validation. Every synthetic
JSON parser consumes only `VerifiedArtifactBytes.data`; none reopens a pathname.

- [ ] **Step 5: Add the complete M1b fixture matrix**

Add fixed fixtures for ticker reuse, ticker rename, two share classes, exchange
migration, June index addition, explicit removal, cash acquisition, stock
acquisition, unknown delisting outcome, evidenced worthlessness, future split,
cash dividend, spinoff, vendor action correction, fully adjusted history, missing
bar versus halt, early close, DST boundary, and overnight session.

- [ ] **Step 6: Write and pass parameterized market-leakage tests**

```python
@dataclass(frozen=True, slots=True)
class M1BFixtureCase:
    manifest: DatasetManifestV1
    verified_artifacts: tuple[VerifiedArtifactBytes, ...]
    dependency_inputs: MarketDependencyInputsV1
    universe_id: UUID7
    channel: AvailabilityChannelV1
    coverage: ValidPeriodV1
    expected_finding_codes: tuple[str, ...]


@pytest.mark.parametrize(
    "case_dir",
    sorted(path for path in M1B_FIXTURES.iterdir() if path.is_dir()),
)
def test_market_fixture_matches_expected_findings(case_dir: Path) -> None:
    case = load_bound_m1b_case(
        case_dir,
        PINNED_FIXTURE_HASHES[case_dir.name],
    )
    decision = validate_market_dataset(
        case.manifest,
        case.verified_artifacts,
        case.dependency_inputs,
        case.universe_id,
        case.channel,
        case.coverage,
    )
    assert tuple(item.code for item in decision.findings) == (
        case.expected_finding_codes
    )
```

Each case directory contains `market-data.json`, `identity-data.json`,
`universe-data.json`, `actions-data.json`, `calendar-data.json`,
`manifests.json`, and `expected.json`. The manifest file holds the five
non-self-referential manifest bodies whose partition hashes name the separate
data files. The pinned hash map covers all seven files. `load_bound_m1b_case`
reads each through
`read_verified_local_artifact`, validates each dependency dataset from its bytes,
creates its eligibility binding, and then constructs `MarketDependencyInputsV1`.
No expected finding, manifest hash, or dependency record is accepted from an
unverified path.

- [ ] **Step 7: Run all adversarial and eligibility tests**

Run: `uv run pytest tests/unit/test_market_data.py tests/integration/test_m1a_leakage.py tests/integration/test_m1b_market_leakage.py tests/integration/test_m1_eligibility.py -v`

Expected: every future-information, identity, universe, action, adjustment,
missingness, and session cheat is rejected or explicitly exploratory-only.

- [ ] **Step 8: Commit market validation and M1b adversarial evidence**

```text
git add src/drift/domain/market_data.py src/drift/datasets/validation.py src/drift/datasets/market_validation.py tests/unit/test_market_data.py tests/fixtures/datasets/m1b tests/integration/test_m1b_market_leakage.py tests/integration/test_m1_eligibility.py
git commit -m "test: reject historical market data leakage"
```

### Task 13: Documentation, final review, and M1 completion gate

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/architecture/roadmap.md`
- Modify: `docs/architecture/trust-boundaries.md`
- Create or modify an ADR only if implementation deviates materially from the approved design.
- Modify: this plan only after all implementation and verification are complete.

**Interfaces:**
- Consumes: the implemented M1a and M1b contracts and verification output.
- Produces: accurate user and architecture documentation, explicit non-capabilities,
  final compatibility evidence, and a clean Checkpoint.

- [ ] **Step 1: Write documentation tests before changing status text**

```python
def test_roadmap_does_not_claim_trading_or_backtesting_capability() -> None:
    roadmap = Path("docs/architecture/roadmap.md").read_text(encoding="utf-8")
    assert "M1, complete" in roadmap
    assert "does not backtest" in roadmap
    assert "does not place orders" in roadmap
```

- [ ] **Step 2: Document only implemented contracts and limitations**

Update the repository map, M1 boundary, validation-decision meaning, M0 bridge,
offline fixture workflow, complete verification commands, and non-goals. Preserve
the distinction between a structurally validated manifest and channel/use-scoped
historical eligibility. Do not claim a real vendor dataset has been verified.

- [ ] **Step 3: Run plan self-review and placeholder scans**

Run: `rg -n "T[B]D|T[O]DO|implement la[t]er|fill i[n]|appropriate error handlin[g]|similar to Tas[k]" docs/superpowers/plans/2026-09-01-m1-point-in-time-data.md`

Expected: no plan placeholders. Any match in quoted instructions is removed or
rewritten before completion.

Run: `rg -n $'\xE2\x80\x94' .`

Expected: no U+2014 match.

- [ ] **Step 4: Run compatibility, forbidden-capability, and full quality gates**

Run: `git diff 4587745 -- src/drift/domain/datasets.py src/drift/domain/artifacts.py src/drift/domain/experiments.py src/drift/domain/events.py src/drift/serialization/canonical.py`

Expected: no M0 compatibility-sensitive source diff.

Run: `rg -n "(robinhood|alpaca|place_order|submit_order|broker_url|api[_-]?key|oauth|langgraph|openai|rd-agent)" src tests pyproject.toml`

Expected: no broker, network, agent, credential, or trading capability. Inspect
every textual match.

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: all tests pass; lint, formatting, typing, and build exit 0.

- [ ] **Step 5: Perform a fresh adversarial review**

Attempt each cheat from the design: future fundamentals, current universe,
revised macro history, future action knowledge, ticker collision, post-event
news, unavailable forward fill, adjusted-price leakage, channel mismatch, and
same-path byte substitution. Record a failing test for any newly successful
cheat and fix the smallest contract or validator that closes it.

- [ ] **Step 6: Commit documentation and close the historical plan**

After every preceding checkbox is truthfully complete, change the plan status to
completed, record implementation commit hashes, and mark checkboxes complete.

```text
git add README.md docs src tests
git commit -m "docs: complete point-in-time data milestone"
```

- [ ] **Step 7: Run Checkpoint**

Verify branch, HEAD, complete gate output, clean Git status, scope exclusions,
M0 replay compatibility, and both M1 submilestones. Do not create a Session
Handoff if the implementation is complete, committed, verified, and clean.

## Planned commit boundaries

1. `feat: add point-in-time availability evidence`
2. `feat: add immutable dataset manifests`
3. `feat: verify confined dataset artifacts`
4. `feat: preserve point-in-time fact revisions`
5. `feat: gate dataset references with validation evidence`
6. `test: prove temporal leakage is rejected`
7. M1a review fixes, only if necessary
8. `feat: add stable historical security identity`
9. `feat: add historical universe membership`
10. `feat: record point-in-time corporate actions`
11. `feat: bind datasets to versioned market sessions`
12. `test: reject historical market data leakage`
13. `docs: complete point-in-time data milestone`

The design-only task that created this plan commits the specification and this
unchecked plan separately from all implementation work.
