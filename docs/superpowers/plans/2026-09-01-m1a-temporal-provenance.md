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
5. Query results are immutable evidence objects, not transient booleans. Their canonical identity binds the normalized cutoff, requested channel, policy ID and hash, evaluated evidence, every considered fact version, and the selected version when one exists.
6. M1a supports one rule-derived availability operation: `conservative-upper-bound-v1`. The implementation derives an exact conservative instant from retained raw bounded evidence, preserves its source label and precision, and recomputes the derivation during validation and evaluation. Callers cannot supply trusted derived bounds.
7. Schema fields and manifest partitions are canonically ordered during model construction. Schema and manifest hash preimages are explicit and every identity-bearing mutation must change canonical bytes and hashes.

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
| `src/drift/datasets/events.py` | Compact audit-event draft factories for manifest and validation evidence |
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
- Produces: `ValidPeriodV1`, `ChannelKind`, `AvailabilityShape`, `AvailabilityBasis`, `SourcePrecision`, `CutoffEligibility`, `AvailabilityChannelV1`, `RuleDerivationV1`, `AvailabilityEvidenceV1`, `AvailabilityPolicyV1`, `CutoffEligibilityResultV1`, `derive_conservative_upper_bound(raw_evidence, rule_reference) -> AvailabilityEvidenceV1`, and `evaluate_availability(evidence, channel, policy, cutoff, retained_evidence) -> CutoffEligibilityResultV1`.

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
        ("derived_upper", utc(2022, 5, 6), PUBLIC, STRICT, CutoffEligibility.INELIGIBLE),
        ("derived_upper", utc(2022, 5, 6), PUBLIC, RULE_ALLOWED, CutoffEligibility.ELIGIBLE),
    ),
)
def test_cutoff_eligibility_table(
    case: str,
    cutoff: datetime,
    requested_channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    expected: CutoffEligibility,
) -> None:
    result = evaluate_availability(
        EVIDENCE[case], requested_channel, policy, cutoff, RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is expected
```

Add separate validation cases for a naive cutoff, reversed bounds, equal bounded bounds, exact unequal bounds, unknown with bounds, missing source labels, date precision without an IANA timezone, non-rule date/minute/session evidence marked exact, unknown shape with non-unknown precision, rule basis without rule metadata, non-rule basis with rule metadata, caller-supplied derived bounds, missing retained raw evidence, raw evidence hash mismatch, unapproved rule, and duplicate policy rule hashes.

```python
@pytest.mark.parametrize(
    ("source_time_label", "bound"),
    (
        ("2022-05-05T20:00:00", utc(2022, 5, 5, 20)),
        ("2022-05-05 20:00:00Z", utc(2022, 5, 5, 20)),
        ("2022-05-05T20:00:00Z", utc(2022, 5, 5, 20, 0, 1)),
    ),
)
def test_exact_second_rejects_malformed_unzoned_or_mismatched_labels(
    source_time_label: str,
    bound: datetime,
) -> None:
    with pytest.raises(ValidationError, match="offset-bearing ISO second"):
        exact_source_evidence(source_time_label=source_time_label, bound=bound)


def test_exact_second_normalizes_offset_label_to_equal_utc_bounds() -> None:
    evidence = exact_source_evidence(
        source_time_label="2022-05-05T16:00:00-04:00",
        bound=utc(2022, 5, 5, 20),
    )
    assert evidence.lower_bound == evidence.upper_bound == utc(2022, 5, 5, 20)


def test_rule_derived_channel_mismatch_retains_derivation_input_hash() -> None:
    evidence = EVIDENCE["derived_upper"]
    assert evidence.rule_derivation is not None
    result = evaluate_availability(
        evidence, VENDOR, RULE_ALLOWED, utc(2022, 5, 6), RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is CutoffEligibility.INDETERMINATE
    assert (
        result.derivation_input_evidence_hash
        == evidence.rule_derivation.input_evidence_hash
    )
```

Add behavioral identity tests, not field-presence assertions:

```python
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("cutoff", utc(2022, 5, 6, 0, 1)),
        ("channel", VENDOR),
        ("policy", RULE_ALLOWED),
        ("evidence", EVIDENCE["bounded"]),
    ),
)
def test_cutoff_result_hash_changes_for_every_query_input_mutation(
    field: str,
    value: object,
) -> None:
    arguments = {
        "evidence": EVIDENCE["exact"],
        "channel": PUBLIC,
        "policy": STRICT,
        "cutoff": utc(2022, 5, 6),
        "retained_evidence": RAW_EVIDENCE_BY_HASH,
    }
    result = evaluate_availability(**arguments)
    changed = evaluate_availability(**{**arguments, field: value})
    assert content_hash(changed) != content_hash(result)
```

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
    rule_reference: ArtifactReference
    rule_version: Literal["1"] = "1"
    input_evidence_hash: SHA256Hash


class AvailabilityEvidenceV1(FrozenModel):
    channel: AvailabilityChannelV1
    shape: AvailabilityShape
    lower_bound: UTCDateTime | None = None
    upper_bound: UTCDateTime | None = None
    precision: SourcePrecision
    source_time_label: NonBlankStr | None = None
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
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    evidence: AvailabilityEvidenceV1
    evidence_hash: SHA256Hash
    derivation_input_evidence_hash: SHA256Hash | None = None
```

Use this explicit compatibility matrix:

| Shape | Precision | Permitted basis | Mechanical requirement |
|---|---|---|---|
| `exact` | `second` | non-rule source, vendor, or ingest | Offset-bearing ISO second label parses to both equal UTC bounds |
| `bounded` | `second`, `minute`, `date`, `interval`, or `session` | non-rule source, vendor, or ingest | Ordered bounds and retained source label |
| `exact` | retained raw bounded precision | `rule_derived` only | Constructed only by `conservative-upper-bound-v1` |
| `unknown` | `unknown` | non-rule source, vendor, or ingest | No bounds; optional unparsed source label retained |

Any combination not listed is invalid. In particular, non-rule `date`, `minute`, or `session` evidence cannot be exact, and unknown precision cannot accompany an exact or bounded shape. Date precision requires an IANA timezone and an ISO date label. Convert local midnight at that label and the next local date to UTC, including daylight-saving changes, and require those exact values as the bounds. Minute precision similarly requires an ISO local-minute label and the exact one-minute local window. Session precision remains bounded and requires a source label plus evidence artifact; M1a does not infer session bounds. This makes a date-to-midnight exact timestamp unconstructable while retaining the raw label, precision, and timezone.

```python
_OFFSET_SECOND = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$"
)


def expected_exact_second(source_time_label: str) -> datetime:
    if _OFFSET_SECOND.fullmatch(source_time_label) is None:
        raise ValueError("exact evidence requires an offset-bearing ISO second")
    parsed = datetime.fromisoformat(source_time_label.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("exact evidence requires an offset-bearing ISO second")
    return parsed.astimezone(UTC)
```

For non-rule exact-second evidence, the model validator calls `expected_exact_second` and requires both stored UTC bounds to equal the parsed instant. Fractional seconds, missing offsets, space separators, malformed labels, and label/bound mismatches fail validation.

```python
def expected_source_window(
    source_time_label: str,
    precision: SourcePrecision,
    source_timezone: str,
) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(source_timezone)
    if precision is SourcePrecision.DATE:
        local_date = date.fromisoformat(source_time_label)
        lower = datetime.combine(local_date, time.min, timezone)
        upper = datetime.combine(local_date + timedelta(days=1), time.min, timezone)
    elif precision is SourcePrecision.MINUTE:
        naive = datetime.strptime(source_time_label, "%Y-%m-%dT%H:%M")
        first = naive.replace(tzinfo=timezone, fold=0)
        second = naive.replace(tzinfo=timezone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("ambiguous or nonexistent local minute stays unknown")
        if first.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) != naive:
            raise ValueError("ambiguous or nonexistent local minute stays unknown")
        lower = first
        upper = lower + timedelta(minutes=1)
    else:
        raise ValueError("only date and minute labels define mechanical windows")
    return lower.astimezone(UTC), upper.astimezone(UTC)
```

For raw date or minute evidence, the model validator calls this function and requires exact bound equality. Invalid labels, nonexistent or ambiguous local minutes, and mismatched bounds fail validation. Ambiguous local-minute labels require an offset-bearing second-precision source label or remain unknown; M1a never guesses a `fold` value.

`ValidPeriodV1` is nonempty and half-open. `AvailabilityPolicyV1` contains `policy_id` and unique `permitted_rule_hashes`; it contains no timestamp default.

- [ ] **Step 4: Implement tri-state cutoff evaluation**

```python
CONSERVATIVE_UPPER_BOUND_RULE_SPEC = {
    "rule_id": "conservative-upper-bound",
    "version": "1",
    "algorithm": "derived exact availability equals retained bounded upper bound",
}
CONSERVATIVE_UPPER_BOUND_RULE_HASH = content_hash(
    CONSERVATIVE_UPPER_BOUND_RULE_SPEC
)


def derive_conservative_upper_bound(
    raw_evidence: AvailabilityEvidenceV1,
    rule_reference: ArtifactReference,
) -> AvailabilityEvidenceV1:
    if raw_evidence.shape is not AvailabilityShape.BOUNDED:
        raise ValueError("conservative upper-bound rule requires bounded evidence")
    if raw_evidence.basis is AvailabilityBasis.RULE_DERIVED:
        raise ValueError("rule input must be retained raw evidence")
    if rule_reference.content_hash != CONSERVATIVE_UPPER_BOUND_RULE_HASH:
        raise ValueError("rule artifact does not match conservative-upper-bound-v1")
    assert raw_evidence.upper_bound is not None
    return AvailabilityEvidenceV1(
        channel=raw_evidence.channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=raw_evidence.upper_bound,
        upper_bound=raw_evidence.upper_bound,
        precision=raw_evidence.precision,
        source_time_label=raw_evidence.source_time_label,
        source_timezone=raw_evidence.source_timezone,
        basis=AvailabilityBasis.RULE_DERIVED,
        evidence_reference=raw_evidence.evidence_reference,
        rule_derivation=RuleDerivationV1(
            rule_reference=rule_reference,
            input_evidence_hash=content_hash(raw_evidence),
        ),
    )


def evaluate_availability(
    evidence: AvailabilityEvidenceV1,
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    cutoff: datetime,
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> CutoffEligibilityResultV1:
    cutoff_utc = _normalize_utc(cutoff)
    digest = content_hash(evidence)
    policy_digest = content_hash(policy)
    derivation_input_hash = (
        None
        if evidence.rule_derivation is None
        else evidence.rule_derivation.input_evidence_hash
    )
    common = {
        "cutoff": cutoff_utc,
        "requested_channel": channel,
        "policy": policy,
        "policy_id": policy.policy_id,
        "policy_hash": policy_digest,
        "evidence": evidence,
        "evidence_hash": digest,
        "derivation_input_evidence_hash": derivation_input_hash,
    }
    if evidence.channel != channel:
        return CutoffEligibilityResultV1(
            classification=CutoffEligibility.INDETERMINATE,
            reason="no_evidence_for_requested_channel",
            **common,
        )
    if evidence.shape is AvailabilityShape.UNKNOWN:
        return CutoffEligibilityResultV1(
            classification=CutoffEligibility.INDETERMINATE,
            reason="availability_unknown",
            **common,
        )
    if evidence.basis is AvailabilityBasis.RULE_DERIVED:
        assert evidence.rule_derivation is not None
        derivation = evidence.rule_derivation
        raw = retained_evidence.get(derivation.input_evidence_hash)
        if raw is None or content_hash(raw) != derivation.input_evidence_hash:
            return CutoffEligibilityResultV1(
                classification=CutoffEligibility.INDETERMINATE,
                reason="rule_input_evidence_unavailable",
                **common,
            )
        if derive_conservative_upper_bound(raw, derivation.rule_reference) != evidence:
            return CutoffEligibilityResultV1(
                classification=CutoffEligibility.INDETERMINATE,
                reason="rule_derivation_not_reproducible",
                **common,
            )
        if derivation.rule_reference.content_hash not in policy.permitted_rule_hashes:
            return CutoffEligibilityResultV1(
                classification=CutoffEligibility.INELIGIBLE,
                reason="rule_not_permitted_by_policy",
                **common,
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
        **common,
    )
```

Add a result validator requiring `policy_id == policy.policy_id`, `policy_hash == content_hash(policy)`, `evidence_hash == content_hash(evidence)`, and a derivation input hash exactly when the evaluated evidence is rule-derived. UTC normalization is enforced by `UTCDateTime`. This makes copied or internally inconsistent query results invalid, while the behavioral tests prove that changing any real query input changes canonical result identity.

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
- Produces: `DatasetKind`, `LogicalType`, `EvidenceGranularity`, `DeterminismClaim`, `SourceDescriptorV1`, `AcquisitionDescriptorV1`, `LicenseDescriptorV1`, `FieldDescriptorV1`, `SchemaDescriptorV1`, `PartitionDescriptorV1`, `RecordTemporalContractV1`, `LineageDescriptorV1`, `DatasetManifestV1`, `schema_body(schema) -> dict[str, JSONValue]`, `schema_hash(schema) -> str`, `manifest_body(manifest) -> dict[str, JSONValue]`, `manifest_hash(manifest) -> str`, and `derived_temporal_coverage(partitions) -> TemporalCoverage`.

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


def test_equivalent_input_orders_have_equal_models_bytes_and_hashes() -> None:
    left = manifest(fields=(FIELD_B, FIELD_A), partitions=(PARTITION_B, PARTITION_A))
    right = manifest(fields=(FIELD_A, FIELD_B), partitions=(PARTITION_A, PARTITION_B))
    assert left == right
    assert canonical_json(left) == canonical_json(right)
    assert manifest_hash(left) == manifest_hash(right)


def test_no_availability_default_exists_on_manifest_or_partition() -> None:
    assert "availability" not in DatasetManifestV1.model_fields
    assert "availability" not in PartitionDescriptorV1.model_fields
```

Also test duplicate field IDs/names, duplicate partition IDs/keys, schema-hash mismatch, reversed coverage, raw data with lineage, derived data without lineage, duplicate lineage inputs, mismatched lineage output schema, naive acquisition/creation/execution times, source locators containing credentials, and an absent optional license version.

Use deterministic mutation tables to prove every identity-bearing field changes its preimage and digest. The schema table mutates version, each field ID/name/type/nullability/unit, field membership, and order-normalized content. The manifest table mutates schema/hash profile versions, dataset ID/version/kind, creation time, every source/acquisition/license field, schema hash or content, every partition field and artifact hash, temporal bindings/channels, and every lineage field. Input ordering alone must not change model equality, canonical bytes, or hashes.

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

    @field_validator("partitions")
    @classmethod
    def canonicalize_partitions(
        cls, partitions: tuple[PartitionDescriptorV1, ...]
    ) -> tuple[PartitionDescriptorV1, ...]:
        if not partitions:
            raise ValueError("manifest partitions must not be empty")
        if len({item.partition_id for item in partitions}) != len(partitions):
            raise ValueError("partition IDs must be unique")
        if len({item.partition_key for item in partitions}) != len(partitions):
            raise ValueError("partition keys must be unique")
        return tuple(
            sorted(
                partitions,
                key=lambda item: (item.partition_key, item.artifact.content_hash),
            )
        )
```

`SourceDescriptorV1` records source ID, publisher, product, optional source version, and a retained evidence reference, never credentials. `AcquisitionDescriptorV1` records `acquired_at`, collector ID/version, and acquisition evidence. `LicenseDescriptorV1` records only the legal source and retained terms evidence. It is provenance, not a legal rules engine.

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

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[FieldDescriptorV1, ...]
    ) -> tuple[FieldDescriptorV1, ...]:
        if not fields:
            raise ValueError("schema fields must not be empty")
        if len({field.field_id for field in fields}) != len(fields):
            raise ValueError("schema field IDs must be unique")
        if len({field.name for field in fields}) != len(fields):
            raise ValueError("schema field names must be unique")
        return tuple(sorted(fields, key=lambda field: field.field_id))
```

`SchemaDescriptorV1` has a version, nonempty `FieldDescriptorV1` tuple, and schema hash. Fields use a small closed logical-type enum and stable IDs. The temporal contract binds only existing field IDs, declares record evidence, and has no default evidence or cutoff policy. Require nonempty, unique declared channels because every record must carry evidence for each channel the dataset claims to support.

Use these provenance-only license fields:

```python
class LicenseDescriptorV1(FrozenModel):
    provider_legal_name: NonBlankStr
    license_reference: NonBlankStr
    license_version: NonBlankStr | None = None
    acquired_at: UTCDateTime
    terms_evidence_reference: ArtifactReference
```

Do not encode allowed use, redistribution, derivation, retention, or other legal conclusions in M1a. A later operation that needs rights confirmation must use separately reviewed evidence and policy.

- [ ] **Step 4: Implement canonical ordering and hashing**

```python
def schema_body(schema: SchemaDescriptorV1) -> dict[str, JSONValue]:
    body = canonical_data(schema)
    assert isinstance(body, dict)
    del body["schema_hash"]
    return body


def schema_hash(schema: SchemaDescriptorV1) -> str:
    return content_hash(schema_body(schema))


def manifest_body(manifest: DatasetManifestV1) -> dict[str, JSONValue]:
    body = canonical_data(manifest)
    assert isinstance(body, dict)
    return body


def manifest_hash(manifest: DatasetManifestV1) -> str:
    return content_hash(manifest_body(manifest))
```

The schema hash preimage is every schema field except its own stored `schema_hash`. The manifest has no stored manifest hash, so its preimage is every canonical manifest field, including the validated schema hash. Use field validators during model construction to sort schema fields by stable field ID and partitions by `(partition_key, artifact.content_hash)`. Reject duplicates before returning the canonical tuples. Validate the supplied schema hash after ordering. This guarantees equivalent model instances have equal canonical JSON, rather than merely making `manifest_hash` sort a copy.

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
- Produces: `ResolverLimits`, `VerifiedArtifactBytes`, `read_verified_local_artifact(root, relative_path, expected_hash, limits) -> VerifiedArtifactBytes`, and `verify_partition_bytes(partition, verified) -> None`.

- [ ] **Step 1: Write failing path, file-kind, size, mutation, and mismatch tests**

```python
@pytest.mark.parametrize(
    "relative",
    ("", "../secret.json", "/tmp/secret.json", "a/../../b"),
)
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

Add deterministic cases for NULs, symlink path components, symlink escape, FIFO or other nonregular file, missing file, file above `max_bytes`, descriptor identity, declared partition size mismatch, and partition hash mismatch. `verify_partition_bytes` returns `None` on success and raises typed `ArtifactIntegrityError` for a size or hash mismatch; it does not return finding strings before the finding model exists.

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
    if (
        not relative.parts
        or "\0" in relative_path
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ArtifactResolutionError("artifact path must be confined to its root")
    root_fd = os.open(root.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY)
    opened_dirs: list[int] = [root_fd]
    try:
        directory_fd = root_fd
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        for part in relative.parts[:-1]:
            directory_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=directory_fd,
            )
            opened_dirs.append(directory_fd)
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | nofollow,
            dir_fd=directory_fd,
        )
        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise ArtifactResolutionError("artifact must be a regular file")
            if opened.st_size > limits.max_bytes:
                raise ArtifactResolutionError("artifact exceeds configured size limit")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                data = stream.read(limits.max_bytes + 1)
            if len(data) > limits.max_bytes:
                raise ArtifactResolutionError("artifact exceeds configured size limit")
            digest = sha256(data).hexdigest()
            if digest != expected_hash:
                raise ArtifactIntegrityError("artifact SHA-256 does not match")
            return VerifiedArtifactBytes(
                data=data, byte_size=len(data), content_hash=digest
            )
        finally:
            os.close(file_fd)
    finally:
        for descriptor in reversed(opened_dirs):
            os.close(descriptor)
```

The empty-parts check occurs before any `relative.parts[-1]` access, so an empty path raises `ArtifactResolutionError` instead of leaking `IndexError`. The local fixture resolver is intentionally small. It opens each directory component with `O_NOFOLLOW` when the platform provides it, opens the file exactly once, checks the opened descriptor with `fstat`, and performs the bounded read and hash through that same descriptor. Every parser consumes `VerifiedArtifactBytes.data`; it never reopens a path. A future large-file adapter must hash and parse the same descriptor or use an immutable content-addressed object.

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
- Produces: `FindingSeverity`, `ValidationFindingV1`, `DatasetValidationError`, `RevisionKind`, `LogicalFactKeyV1`, `FactVersionV1`, `FactSelectionResultV1`, `fact_version_payload(version) -> dict[str, JSONValue]`, `validate_revision_chain(versions) -> tuple[ValidationFindingV1, ...]`, and `select_fact_version(versions, channel, policy, cutoff, retained_evidence) -> FactSelectionResultV1`.

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
    result = select_fact_version(
        CHAINS[case], PUBLIC, STRICT, cutoff, RAW_EVIDENCE_BY_HASH
    )
    assert result.classification is expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value
```

Add validation cases for duplicate version IDs, missing or multiple initial roots, missing predecessor, key mismatch, branching, cycle, decreasing source sequence, duplicate channel evidence, missing source artifact, payload-hash mismatch, withdrawal with a value, nonwithdrawal without a value and null reason, and naive cutoff.

Add this behavioral result-identity test. It changes real query inputs and reruns selection instead of mutating serialized output fields:

```python
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("cutoff", utc(2022, 8, 11)),
        ("channel", VENDOR),
        ("policy", RULE_ALLOWED),
        ("versions", CHAINS["restated_plus_correction"]),
    ),
)
def test_selection_result_hash_changes_for_every_query_input_mutation(
    field: str,
    value: object,
) -> None:
    arguments = {
        "versions": CHAINS["restated"],
        "channel": PUBLIC,
        "policy": STRICT,
        "cutoff": utc(2022, 8, 10),
        "retained_evidence": RAW_EVIDENCE_BY_HASH,
    }
    original = select_fact_version(**arguments)
    changed = select_fact_version(**{**arguments, field: value})
    assert canonical_json(changed) != canonical_json(original)
    assert content_hash(changed) != content_hash(original)
```

Reordering the same input versions without changing their canonical source-sequence order must produce equal canonical result bytes and hashes.

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
    cutoff: UTCDateTime
    requested_channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    policy_id: NonBlankStr
    policy_hash: SHA256Hash
    considered_versions: tuple[FactVersionV1, ...]
    considered_version_hashes: tuple[SHA256Hash, ...]
    selected_version_hash: SHA256Hash | None = None
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
    retained_evidence: Mapping[SHA256Hash, AvailabilityEvidenceV1],
) -> FactSelectionResultV1:
    findings = validate_revision_chain(versions)
    if findings:
        raise DatasetValidationError(findings)
    cutoff_utc = _normalize_utc(cutoff)
    ordered = tuple(sorted(versions, key=lambda version: version.source_sequence))
    query_identity = {
        "cutoff": cutoff_utc,
        "requested_channel": channel,
        "policy": policy,
        "policy_id": policy.policy_id,
        "policy_hash": content_hash(policy),
        "considered_versions": ordered,
        "considered_version_hashes": tuple(content_hash(item) for item in ordered),
    }
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
                cutoff_utc,
                retained_evidence,
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
                selected_version_hash=None,
                **query_identity,
            )
        return FactSelectionResultV1(
            classification=CutoffEligibility.ELIGIBLE,
            reason="latest_definitely_available_version",
            selected_version=selected,
            selected_version_hash=content_hash(selected),
            **query_identity,
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
        selected_version_hash=None,
        **query_identity,
    )
```

Validate that `policy_id == policy.policy_id`, `policy_hash == content_hash(policy)`, each considered hash equals the corresponding considered version's full canonical hash, and `selected_version_hash` is present exactly when `selected_version` is present and equals `content_hash(selected_version)`. Require unique considered hashes in source-sequence order and require a selected version to be a member of the considered tuple. Before `max`, require that all eligible versions form one predecessor path and source sequence is strictly increasing. A later indeterminate revision does not introduce future data and does not erase an earlier definitely available revision. A malformed or ambiguous chain raises typed validation findings rather than returning a favorable result.

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
    "context_field",
    (
        "decision_id",
        "validator_version",
        "validator_implementation_hash",
        "validation_profile_id",
        "validation_profile_hash",
        "checked_at",
    ),
)
def test_decision_hash_binds_every_validation_context_field(
    context_field: str,
) -> None:
    original = validate_synthetic_fact_dataset(MANIFEST, VERIFIED, CONTEXT)
    changed = validate_synthetic_fact_dataset(
        MANIFEST, VERIFIED, mutate_context(CONTEXT, context_field)
    )
    assert content_hash(changed) != content_hash(original)


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
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime
    validation_scope: ValidationScope
    result: ValidationResult
    validated_artifact_hashes: tuple[SHA256Hash, ...]
    validated_record_hashes: tuple[SHA256Hash, ...] = ()
    checked_contracts: tuple[NonBlankStr, ...]
    findings: tuple[ValidationFindingV1, ...]


class ValidationRunContextV1(FrozenModel):
    decision_id: UUID7
    validator_version: NonBlankStr
    validator_implementation_hash: SHA256Hash
    validation_profile_id: NonBlankStr
    validation_profile_hash: SHA256Hash
    checked_at: UTCDateTime
```

Copy every `ValidationRunContextV1` field unchanged into `DatasetValidationDecisionV1`; no context field may remain implicit or be regenerated. Enforce `PASS` only when there are no error findings, unique sorted artifact and record hashes, and the expected scope fields are present. `MANIFEST_ONLY` has no record hashes. `RECORDS` requires nonempty record hashes and the `record-temporal-v1` checked contract. The decision contains no cutoff, promotion, dataset-wide PIT status, or eligibility permission.

`parse_synthetic_fact_bytes` accepts only a versioned JSON object with a `fact_versions` array, rejects unknown fields through Pydantic, and parses directly from `VerifiedArtifactBytes.data`. `validate_synthetic_fact_dataset` verifies every partition before parsing, checks manifest schema bindings, record counts, coverage, payload hashes, revision chains, declared-channel evidence, source label/precision/bound consistency, recomputable rule derivations against retained raw evidence, and derived lineage. It never reopens a path and never evaluates a historical cutoff.

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

- [ ] **Step 5: Verify every preexisting persisted source and M0 behavior**

Run: `git diff --exit-code 1605246 -- $(git ls-tree -r --name-only 1605246 src/drift)`

Expected: no diff. The path list comes from the pre-M1 tree, so new M1a files are not mistaken for regressions while every preexisting domain, configuration, error, serialization, and ledger source file is protected.

Run: `uv run pytest tests/unit/test_canonical_serialization.py tests/unit/test_domain_models.py tests/unit/test_hashing.py tests/unit/test_ids.py tests/unit/test_ledger.py tests/unit/test_project_contract.py tests/integration/test_replay.py tests/integration/test_scripts.py tests/integration/test_tamper_detection.py tests/integration/test_m1_m0_compatibility.py -v`

Expected: all preexisting tests plus the pinned M1/M0 compatibility test pass; canonical bytes, hashes, ledger append behavior, replay, and tamper detection remain unchanged.

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
- Create: `tests/fixtures/datasets/m1a/derived-upper-bound.json`
- Create: `tests/fixtures/datasets/m1a/bounded-release.json`
- Create: `tests/fixtures/datasets/m1a/unknown-release.json`
- Create: `tests/fixtures/datasets/m1a/late-ingest.json`
- Create: `tests/fixtures/datasets/m1a/withdrawal.json`
- Create: `tests/integration/test_m1a_leakage.py`
- Create: `tests/integration/test_m1_dataset_audit.py`

**Interfaces:**
- Consumes: Tasks 1 through 5 and existing generic audit-event hashing/ledger APIs.
- Produces: fixed synthetic fixture bytes, `build_manifest_recorded_event(manifest, manifest_reference) -> AuditEventDraft`, and `build_validation_completed_event(manifest, decision) -> AuditEventDraft`.

- [ ] **Step 1: Add readable fixtures with pinned expected hashes**

Every fixture uses schema version `1`, fixed UUIDv7 values, explicit record evidence, raw `source_time_label`, and UTC bounds. Keep expected fixture SHA-256 values in `test_m1a_leakage.py`, so changed bytes fail before parsing. A date-only release represents the local calendar day as a bounded UTC interval and preserves its ISO date label, IANA timezone, and `date` precision. Vendor delay contains separate public and vendor evidence. Late ingestion contains separate public and system evidence.

`derived-upper-bound.json` retains the raw bounded evidence and the immutable rule artifact reference. Its derived evidence is produced by `derive_conservative_upper_bound` during fixture construction, not authored with caller-supplied exact bounds. Parsing and validation recompute the input evidence hash and the derived evidence. Add negative byte fixtures that mutate the raw upper bound, rule artifact hash, input evidence hash, and derived instant independently. No fixture contains a market identifier, listing, universe, corporate action, bar, or session.

- [ ] **Step 2: Write the deterministic adversarial result table**

```python
CASES = (
    ("late-fundamental.json", "public", "strict", "2022-04-30T23:59:59Z", "ineligible", None),
    ("late-fundamental.json", "public", "strict", "2022-05-05T20:00:00Z", "eligible", "1.20"),
    ("restated-fundamental.json", "public", "strict", "2022-06-01T00:00:00Z", "eligible", "1.20"),
    ("restated-fundamental.json", "public", "strict", "2022-08-10T00:00:00Z", "eligible", "0.90"),
    ("macro-vintage.json", "public", "strict", "2022-02-01T00:00:00Z", "eligible", "initial"),
    ("macro-vintage.json", "public", "strict", "2022-03-01T00:00:00Z", "eligible", "revised"),
    ("vendor-delay.json", "public", "strict", "2022-05-05T20:00:00Z", "eligible", "released"),
    ("vendor-delay.json", "vendor", "strict", "2022-05-05T20:00:00Z", "ineligible", None),
    ("date-only-release.json", "public", "strict", "2022-05-05T12:00:00Z", "indeterminate", None),
    ("date-only-release.json", "public", "strict", "2022-05-06T04:00:00Z", "eligible", "released"),
    ("derived-upper-bound.json", "public", "rule_allowed", "2022-05-06T04:00:00Z", "eligible", "released"),
    ("unknown-release.json", "public", "strict", "2030-01-01T00:00:00Z", "indeterminate", None),
    ("late-ingest.json", "system", "strict", "2022-05-06T00:00:00Z", "ineligible", None),
    ("withdrawal.json", "public", "strict", "2022-09-01T00:00:00Z", "ineligible", None),
)


@pytest.mark.parametrize(
    (
        "filename",
        "channel_id",
        "policy_id",
        "cutoff",
        "expected_class",
        "expected_value",
    ),
    CASES,
)
def test_adversarial_cutoff_table(
    filename: str,
    channel_id: str,
    policy_id: str,
    cutoff: str,
    expected_class: str,
    expected_value: str | None,
) -> None:
    verified = read_verified_local_artifact(
        FIXTURES, filename, EXPECTED_HASHES[filename], ResolverLimits(max_bytes=64_000)
    )
    versions = parse_synthetic_fact_bytes(verified)
    result = select_fact_version(
        versions,
        CHANNELS[channel_id],
        POLICIES[policy_id],
        parse_utc(cutoff),
        retained_evidence_by_hash(verified),
    )
    assert result.classification.value == expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value
```

Add separate deterministic rejection tests for broken predecessor, cycle, duplicate version ID, reversed chronology, changed bytes, schema drift, traversal, and lineage mismatch. Do not use property-based generation.

- [ ] **Step 3: Run leakage tests and fix only contract or fixture defects**

Run: `uv run pytest tests/integration/test_m1a_leakage.py -v`

Expected: all cases pass without adding a provider adapter or market-specific type.

- [ ] **Step 4: Write failing audit-draft integration tests**

```python
def test_dataset_factories_return_unhashed_drafts_and_ledger_assigns_hashes(
    tmp_path: Path,
) -> None:
    manifest_draft = build_manifest_recorded_event(MANIFEST, MANIFEST_REFERENCE)
    validation_draft = build_validation_completed_event(MANIFEST, DECISION)
    assert isinstance(manifest_draft, AuditEventDraft)
    assert isinstance(validation_draft, AuditEventDraft)
    assert "previous_event_hash" not in manifest_draft.model_fields
    assert "event_hash" not in manifest_draft.model_fields

    ledger = SQLiteLedger(tmp_path / "ledger.sqlite3")
    manifest_event = ledger.append(manifest_draft)
    validation_event = ledger.append(validation_draft)
    assert validation_event.previous_event_hash == manifest_event.event_hash
    ledger.verify_chain()
```

- [ ] **Step 5: Run audit tests RED**

Run: `uv run pytest tests/integration/test_m1_dataset_audit.py -v`

Expected: FAIL because the draft factories do not exist.

- [ ] **Step 6: Implement compact audit-event draft factories**

```python
def build_validation_completed_event(
    manifest: DatasetManifestV1,
    decision: DatasetValidationDecisionV1,
) -> AuditEventDraft:
    return AuditEventDraft(
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
        schema_version="1",
    )
```

Create the manifest draft with manifest ID, manifest hash, hash profile, and schema version. Factories never accept a predecessor hash and never call `build_audit_event`; only the ledger assigns `previous_event_hash` and `event_hash`. Do not store raw bytes, physical paths, license prose, cutoff results, or credentials in SQLite. A per-query result remains a return value, not a durable dataset permission.

- [ ] **Step 7: Run audit tests GREEN**

Run: `uv run pytest tests/integration/test_m1_dataset_audit.py tests/integration/test_replay.py tests/integration/test_tamper_detection.py -v`

Expected: all tests pass; append assigns the chain hashes and replay/tamper behavior is unchanged.

- [ ] **Step 8: Run M1a and complete M0 gates**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv build`

Expected: all commands exit 0.

- [ ] **Step 9: Commit adversarial evidence**

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
- Verify: repository contradiction/status audits plus all M0 and M1a tests.

**Interfaces:**
- Consumes: the complete M1a diff and verification evidence.
- Produces: accurate repository capability/status text, no M1b claim, and a clean verified M1a checkpoint.

- [ ] **Step 1: Document only implemented capability and limitations**

Update the root guidance from "M0 only" to "M0 evidence kernel plus M1a temporal provenance". State that M1a provides exact-byte manifests, explicit channel-scoped evidence, immutable revisions, exact-object validation records, and per-query tri-state cutoff decisions. State that it has no real source, market semantics, evaluator, backtester, or trading capability, and that M1b remains required before historical US-equity evaluation claims.

Mark this plan complete only after the gate passes. Update the umbrella design status to say M1a implemented and M1b deferred without rewriting its research or presenting the M1a implementation rulings as completed M1b design.

- [ ] **Step 2: Run status and contradiction audits**

Run: `rg -n "M0 research evidence kernel|M0 only|M1a|M1b|equity-backtest ready|equity backtest ready" README.md AGENTS.md docs/architecture docs/superpowers`

Expected: inspect every match. Current status consistently says M0 plus M1a is implemented, M1b is deferred, and Drift is not ready for equity backtesting. Superseded documents are explicitly historical and do not present unchecked work as active.

Run: `rg -n '^- \[ \]' docs/superpowers/plans`

Expected: unchecked steps occur only in this active M1a plan until it is marked complete. The superseded mixed plan and deferred M1b outline have none.

- [ ] **Step 3: Run explicit scope and compatibility scans**

Run: `rg -n "(security_id|listing_id|ticker|universe|corporate.action|split|dividend|delist|exchange.calendar|market.session|tradability)" src tests`

Expected: no M1b production abstraction was added. Inspect fixture prose matches instead of treating names alone as failures.

Run: `rg -n "(robinhood|alpaca|place_order|submit_order|api[_-]?key|oauth|langgraph|openai|rd-agent|hypothesis)" src tests pyproject.toml`

Expected: no forbidden capability or dependency was added. Inspect every match.

Run: `git diff --exit-code 1605246 -- $(git ls-tree -r --name-only 1605246 src/drift)`

Expected: no diff in any preexisting persisted domain, configuration, error, serialization, or ledger source file. New M1a paths are absent from the baseline path list and therefore do not create false regressions.

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
git add README.md AGENTS.md docs/architecture/roadmap.md docs/superpowers/specs/2026-09-01-m1-point-in-time-data-design.md docs/superpowers/plans/2026-09-01-m1a-temporal-provenance.md
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
