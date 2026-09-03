"""Exact-object tests for M1a dataset validation decisions."""

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.datasets.hashing import manifest_hash, schema_hash
from drift.datasets.references import build_dataset_reference
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.datasets.validation import (
    SYNTHETIC_FACT_SCHEMA_V1,
    parse_synthetic_fact_bytes,
    synthetic_fact_temporal_contract_v1,
    validate_manifest_structure,
    validate_synthetic_fact_dataset,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationError,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV1,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    RecordTemporalContractV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
)
from drift.domain.revisions import FactVersionV1, LogicalFactKeyV1, RevisionKind
from drift.domain.temporal import (
    CONSERVATIVE_UPPER_BOUND_RULE_HASH,
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    RuleDerivationV1,
    SourcePrecision,
    ValidPeriodV1,
    derive_conservative_upper_bound,
)
from drift.serialization.canonical import canonical_json, content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
VALID_START = datetime(2022, 1, 1, tzinfo=UTC)
VALID_END = datetime(2022, 4, 1, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="source")
VENDOR = AvailabilityChannelV1(kind=ChannelKind.VENDOR, identifier="vendor")


def uid(suffix: int) -> UUID:
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def artifact(
    suffix: int,
    digest: str = HASH_A,
    *,
    kind: ArtifactKind = ArtifactKind.OTHER,
    location: str = "evidence/source.json",
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uid(suffix), kind=kind, content_hash=digest, location=location
    )


def exact_evidence(
    *, channel: AvailabilityChannelV1 = PUBLIC
) -> AvailabilityEvidenceV1:
    available = datetime(2022, 5, 5, 20, tzinfo=UTC)
    return AvailabilityEvidenceV1(
        channel=channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=available,
        upper_bound=available,
        precision=SourcePrecision.SECOND,
        source_time_label="2022-05-05T20:00:00Z",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
    )


def version(
    *,
    suffix: int = 1,
    source_sequence: int = 0,
    revision_kind: RevisionKind = RevisionKind.INITIAL,
    supersedes: UUID | None = None,
    availability: tuple[AvailabilityEvidenceV1, ...] | None = None,
    source_id: str = "synthetic-source",
    entity_key: str = "entity-1",
    value: str | None = "1.20",
) -> FactVersionV1:
    values: dict[str, object] = {
        "fact_version_id": uid(100 + suffix),
        "logical_key": LogicalFactKeyV1(
            source_id=source_id,
            entity_key=entity_key,
            concept="reported-value",
            valid_period=ValidPeriodV1(started_at=VALID_START, ended_at=VALID_END),
            unit="USD",
            dimensions={"synthetic": True},
        ),
        "revision_kind": revision_kind,
        "supersedes_fact_version_id": supersedes,
        "source_sequence": source_sequence,
        "value": value,
        "null_reason": None,
        "availability": availability or (exact_evidence(),),
        "source_artifact": artifact(200 + suffix, HASH_B),
    }
    return FactVersionV1.model_validate(
        {**values, "payload_hash": content_hash(values)}
    )


def bounded_evidence() -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.BOUNDED,
        lower_bound=datetime(2022, 5, 5, tzinfo=UTC),
        upper_bound=datetime(2022, 5, 6, tzinfo=UTC),
        precision=SourcePrecision.DATE,
        source_time_label="2022-05-05",
        source_timezone="UTC",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=artifact(250, HASH_C),
    )


def verified_document(
    versions: tuple[FactVersionV1, ...] = (),
    *,
    schema_version: str = "1",
    raw_versions: list[dict[str, object]] | None = None,
    extra: dict[str, object] | None = None,
) -> VerifiedArtifactBytes:
    body: dict[str, object] = {
        "schema_version": schema_version,
        "fact_versions": list(versions) if raw_versions is None else raw_versions,
    }
    if extra:
        body.update(extra)
    data = canonical_json(body)
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )


FIELDS = (
    FieldDescriptorV1(
        field_id="availability",
        name="availability",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="fact_version_id",
        name="fact_version_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.concept",
        name="logical_key.concept",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.dimensions",
        name="logical_key.dimensions",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.entity_key",
        name="logical_key.entity_key",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.source_id",
        name="logical_key.source_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.unit",
        name="logical_key.unit",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.valid_period.ended_at",
        name="logical_key.valid_period.ended_at",
        logical_type=LogicalType.DATETIME,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.valid_period.started_at",
        name="logical_key.valid_period.started_at",
        logical_type=LogicalType.DATETIME,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="null_reason",
        name="null_reason",
        logical_type=LogicalType.STRING,
        nullable=True,
    ),
    FieldDescriptorV1(
        field_id="payload_hash",
        name="payload_hash",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision_kind",
        name="revision_kind",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="source_artifact",
        name="source_artifact",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="source_sequence",
        name="source_sequence",
        logical_type=LogicalType.INTEGER,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="supersedes_fact_version_id",
        name="supersedes_fact_version_id",
        logical_type=LogicalType.STRING,
        nullable=True,
    ),
    FieldDescriptorV1(
        field_id="value",
        name="value",
        logical_type=LogicalType.JSON,
        nullable=True,
    ),
)


def schema(
    *,
    schema_version: str = "1",
    fields: tuple[FieldDescriptorV1, ...] = FIELDS,
) -> SchemaDescriptorV1:
    provisional = SchemaDescriptorV1.model_construct(
        schema_version=schema_version, fields=fields, schema_hash=HASH_A
    )
    return SchemaDescriptorV1.model_construct(
        schema_version=schema_version,
        fields=fields,
        schema_hash=schema_hash(provisional),
    )


def contract(
    declared_channels: tuple[AvailabilityChannelV1, ...] = (PUBLIC,),
    **changes: object,
) -> RecordTemporalContractV1:
    values: dict[str, object] = {
        "contract_version": "1",
        "evidence_granularity": "record",
        "logical_key_field_ids": (
            "logical_key.source_id",
            "logical_key.entity_key",
            "logical_key.concept",
            "logical_key.valid_period.started_at",
            "logical_key.valid_period.ended_at",
            "logical_key.unit",
            "logical_key.dimensions",
        ),
        "valid_start_field_id": "logical_key.valid_period.started_at",
        "valid_end_field_id": "logical_key.valid_period.ended_at",
        "availability_field_id": "availability",
        "revision_id_field_id": "fact_version_id",
        "supersedes_field_id": "supersedes_fact_version_id",
        "source_sequence_field_id": "source_sequence",
        "value_field_id": "value",
        "null_reason_field_id": "null_reason",
        "declared_channels": declared_channels,
    }
    values.update(changes)
    return RecordTemporalContractV1.model_validate(values)


def manifest_for(
    verified: VerifiedArtifactBytes,
    *,
    row_count: int = 1,
    byte_size: int | None = None,
    coverage: TemporalCoverage | None = None,
    temporal_contract: RecordTemporalContractV1 | None = None,
) -> DatasetManifestV1:
    schema_definition = schema()
    partition = PartitionDescriptorV1(
        partition_id=uid(301),
        partition_key="year=2022",
        artifact=artifact(
            302,
            verified.content_hash,
            kind=ArtifactKind.DATASET,
            location=f"drift+sha256://{verified.content_hash}",
        ),
        byte_size=verified.byte_size if byte_size is None else byte_size,
        media_type="application/json",
        format_version="1",
        row_count=row_count,
        schema_hash=schema_definition.schema_hash,
        coverage=coverage
        or TemporalCoverage(started_at=VALID_START, ended_at=VALID_END),
    )
    return DatasetManifestV1(
        manifest_schema_version="1",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(300),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        created_at=NOW,
        source=SourceDescriptorV1(
            source_id="synthetic-source",
            publisher="Synthetic Publisher",
            product="Synthetic Facts",
            evidence_reference=artifact(303, HASH_A),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="fixture-collector",
            collector_version="1",
            evidence_reference=artifact(304, HASH_B),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic Publisher",
            license_reference="fixture-license",
            acquired_at=NOW,
            terms_evidence_reference=artifact(305, HASH_C),
        ),
        schema_definition=schema_definition,
        partitions=(partition,),
        temporal_contract=temporal_contract or contract(),
    )


CONTEXT = ValidationRunContextV1(
    decision_id=uid(400),
    validator_version="1",
    validator_implementation_hash=HASH_A,
    validation_profile_id="m1a-synthetic-facts-v1",
    validation_profile_hash=HASH_B,
    checked_at=NOW,
)


def valid_fixture() -> tuple[DatasetManifestV1, tuple[VerifiedArtifactBytes, ...]]:
    verified = verified_document((version(),))
    return manifest_for(verified), (verified,)


def construct_manifest(
    current: DatasetManifestV1, **changes: object
) -> DatasetManifestV1:
    values = {
        field_name: getattr(current, field_name)
        for field_name in DatasetManifestV1.model_fields
    }
    values.update(changes)
    return DatasetManifestV1.model_construct(**values)


def finding(code: str = "invalid") -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code, severity=FindingSeverity.ERROR, message=code.replace("_", " ")
    )


def test_record_decision_binds_manifest_bytes_and_fact_payloads() -> None:
    current, verified = valid_fixture()
    decision = validate_synthetic_fact_dataset(current, verified, CONTEXT)
    assert decision.result is ValidationResult.PASS
    assert decision.manifest_hash == manifest_hash(current)
    assert decision.validated_artifact_hashes == tuple(
        sorted(item.content_hash for item in verified)
    )
    assert decision.validated_record_hashes == tuple(
        item.payload_hash for item in parse_synthetic_fact_bytes(verified[0])
    )
    assert set(DatasetValidationDecisionV1.model_fields) == {
        "decision_id",
        "manifest_hash",
        "validator_version",
        "validator_implementation_hash",
        "validation_profile_id",
        "validation_profile_hash",
        "checked_at",
        "validation_scope",
        "result",
        "validated_artifact_hashes",
        "validated_record_hashes",
        "checked_contracts",
        "findings",
    }
    assert (
        not {"pit_eligibility", "cutoff", "promotion", "usage_eligibility"}
        & DatasetValidationDecisionV1.model_fields.keys()
    )


def test_pinned_synthetic_schema_describes_the_serialized_fact_format() -> None:
    """Dropping or renaming a serialized path must change the pinned schema."""
    assert SYNTHETIC_FACT_SCHEMA_V1.schema_hash == (
        "aa0b033243bd749e2312353bf6434a79b34825e2a06af8a709890e2fb2dbfe7c"
    )
    assert tuple(
        (field.field_id, field.name, field.logical_type, field.nullable, field.unit)
        for field in SYNTHETIC_FACT_SCHEMA_V1.fields
    ) == (
        ("availability", "availability", LogicalType.JSON, False, None),
        ("fact_version_id", "fact_version_id", LogicalType.STRING, False, None),
        ("logical_key.concept", "logical_key.concept", LogicalType.STRING, False, None),
        (
            "logical_key.dimensions",
            "logical_key.dimensions",
            LogicalType.JSON,
            False,
            None,
        ),
        (
            "logical_key.entity_key",
            "logical_key.entity_key",
            LogicalType.STRING,
            False,
            None,
        ),
        (
            "logical_key.source_id",
            "logical_key.source_id",
            LogicalType.STRING,
            False,
            None,
        ),
        ("logical_key.unit", "logical_key.unit", LogicalType.STRING, False, None),
        (
            "logical_key.valid_period.ended_at",
            "logical_key.valid_period.ended_at",
            LogicalType.DATETIME,
            False,
            None,
        ),
        (
            "logical_key.valid_period.started_at",
            "logical_key.valid_period.started_at",
            LogicalType.DATETIME,
            False,
            None,
        ),
        ("null_reason", "null_reason", LogicalType.STRING, True, None),
        ("payload_hash", "payload_hash", LogicalType.STRING, False, None),
        ("revision_kind", "revision_kind", LogicalType.STRING, False, None),
        ("source_artifact", "source_artifact", LogicalType.JSON, False, None),
        ("source_sequence", "source_sequence", LogicalType.INTEGER, False, None),
        (
            "supersedes_fact_version_id",
            "supersedes_fact_version_id",
            LogicalType.STRING,
            True,
            None,
        ),
        ("value", "value", LogicalType.JSON, True, None),
    )
    expected_contract = synthetic_fact_temporal_contract_v1((PUBLIC,))
    assert expected_contract.logical_key_field_ids == (
        "logical_key.source_id",
        "logical_key.entity_key",
        "logical_key.concept",
        "logical_key.valid_period.started_at",
        "logical_key.valid_period.ended_at",
        "logical_key.unit",
        "logical_key.dimensions",
    )
    assert expected_contract.valid_start_field_id == (
        "logical_key.valid_period.started_at"
    )
    assert expected_contract.valid_end_field_id == "logical_key.valid_period.ended_at"
    assert expected_contract.availability_field_id == "availability"
    assert expected_contract.revision_id_field_id == "fact_version_id"
    assert expected_contract.supersedes_field_id == "supersedes_fact_version_id"
    assert expected_contract.source_sequence_field_id == "source_sequence"
    assert expected_contract.value_field_id == "value"
    assert expected_contract.null_reason_field_id == "null_reason"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("swapped_roles", "synthetic_temporal_contract_mismatch"),
        ("wrong_logical_type", "synthetic_schema_mismatch"),
        ("wrong_nullability", "synthetic_schema_mismatch"),
        ("wrong_unit", "synthetic_schema_mismatch"),
        ("nonexistent_field_path", "synthetic_schema_mismatch"),
    ),
)
def test_synthetic_validator_requires_exact_schema_and_temporal_roles(
    mutation: str, expected_code: str
) -> None:
    """Trusting declarations without fixed bindings accepts a different format."""
    current, verified = valid_fixture()
    if mutation == "swapped_roles":
        changed_contract = contract(
            availability_field_id="value", value_field_id="availability"
        )
        current = current.model_copy(update={"temporal_contract": changed_contract})
    else:
        fields = list(current.schema_definition.fields)
        target_index = next(
            index
            for index, field in enumerate(fields)
            if field.field_id == "availability"
        )
        target = fields[target_index]
        if mutation == "wrong_logical_type":
            target = target.model_copy(update={"logical_type": LogicalType.STRING})
        elif mutation == "wrong_nullability":
            target = target.model_copy(update={"nullable": True})
        elif mutation == "wrong_unit":
            target = target.model_copy(update={"unit": "seconds"})
        else:
            target = target.model_copy(update={"field_id": "record.availability"})
        fields[target_index] = target
        changed_schema = schema(fields=tuple(fields))
        partition = current.partitions[0].model_copy(
            update={"schema_hash": changed_schema.schema_hash}
        )
        updates: dict[str, object] = {
            "schema_definition": changed_schema,
            "partitions": (partition,),
        }
        if mutation == "nonexistent_field_path":
            updates["temporal_contract"] = contract(
                availability_field_id="record.availability"
            )
        current = current.model_copy(update=updates)

    decision = validate_synthetic_fact_dataset(current, verified, CONTEXT)

    assert decision.result is ValidationResult.FAIL
    assert expected_code in {finding.code for finding in decision.findings}


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
    current, verified = valid_fixture()
    original = validate_synthetic_fact_dataset(current, verified, CONTEXT)
    replacements: dict[str, object] = {
        "decision_id": uid(401),
        "validator_version": "unsupported",
        "validator_implementation_hash": HASH_C,
        "validation_profile_id": "other-profile",
        "validation_profile_hash": HASH_C,
        "checked_at": datetime(2026, 9, 1, 13, tzinfo=UTC),
    }
    changed_context = CONTEXT.model_copy(
        update={context_field: replacements[context_field]}
    )
    changed = validate_synthetic_fact_dataset(current, verified, changed_context)
    assert content_hash(changed) != content_hash(original)


@pytest.mark.parametrize(
    "mutation",
    ("changed_bytes", "wrong_schema", "missing_record_evidence", "broken_lineage"),
)
def test_validation_fails_for_unbound_or_incomplete_evidence(mutation: str) -> None:
    current, verified_tuple = valid_fixture()
    verified = verified_tuple[0]
    if mutation == "changed_bytes":
        changed_data = verified.data.replace(b'"1.20"', b'"1.21"')
        verified = replace(verified, data=changed_data)
    elif mutation == "wrong_schema":
        verified = verified_document((version(),), schema_version="2")
        current = manifest_for(verified)
    elif mutation == "missing_record_evidence":
        raw = version().model_dump(mode="python")
        raw["availability"] = ()
        payload = dict(raw)
        payload.pop("payload_hash")
        raw["payload_hash"] = content_hash(payload)
        verified = verified_document(raw_versions=[raw])
        current = manifest_for(verified)
    else:
        current = construct_manifest(
            current, dataset_kind=DatasetKind.DERIVED_FACTS, lineage=None
        )
    decision = validate_synthetic_fact_dataset(current, (verified,), CONTEXT)
    assert decision.result is ValidationResult.FAIL
    assert any(item.severity is FindingSeverity.ERROR for item in decision.findings)


def test_manifest_only_decision_has_no_record_hashes() -> None:
    current, verified = valid_fixture()
    decision = validate_manifest_structure(current, verified, CONTEXT)
    assert decision.result is ValidationResult.PASS
    assert decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert decision.validated_record_hashes == ()
    assert decision.checked_contracts == ("dataset-manifest-v1",)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("unsupported_validator", "unsupported_validator_version"),
        ("unsupported_manifest", "unsupported_manifest_schema_version"),
        ("unsupported_schema", "unsupported_schema_version"),
        ("missing_partition", "missing_partition_artifact"),
        ("duplicate_verified", "duplicate_artifact_hash"),
        ("declared_size", "partition_byte_size_mismatch"),
        ("row_count", "partition_row_count_mismatch"),
        ("coverage", "record_outside_partition_coverage"),
        ("missing_channel", "missing_declared_channel_evidence"),
    ),
)
def test_validation_rejects_incomplete_manifest_or_record_binding(
    mutation: str, expected_code: str
) -> None:
    current, verified = valid_fixture()
    context = CONTEXT
    if mutation == "unsupported_validator":
        context = CONTEXT.model_copy(update={"validator_version": "2"})
    elif mutation == "unsupported_manifest":
        current = construct_manifest(current, manifest_schema_version="2")
    elif mutation == "unsupported_schema":
        invalid_schema = schema(schema_version="2")
        current = construct_manifest(current, schema_definition=invalid_schema)
    elif mutation == "missing_partition":
        verified = ()
    elif mutation == "duplicate_verified":
        verified = (verified[0], verified[0])
    elif mutation == "declared_size":
        changed = current.partitions[0].model_copy(
            update={"byte_size": current.partitions[0].byte_size + 1}
        )
        current = current.model_copy(update={"partitions": (changed,)})
    elif mutation == "row_count":
        changed = current.partitions[0].model_copy(update={"row_count": 2})
        current = current.model_copy(update={"partitions": (changed,)})
    elif mutation == "coverage":
        changed = current.partitions[0].model_copy(
            update={
                "coverage": TemporalCoverage(
                    started_at=datetime(2023, 1, 1, tzinfo=UTC),
                    ended_at=datetime(2023, 12, 31, tzinfo=UTC),
                )
            }
        )
        current = current.model_copy(update={"partitions": (changed,)})
    else:
        current = current.model_copy(
            update={"temporal_contract": contract((PUBLIC, VENDOR))}
        )
    decision = validate_synthetic_fact_dataset(current, verified, context)
    assert decision.result is ValidationResult.FAIL
    assert expected_code in {item.code for item in decision.findings}


def test_duplicate_partition_artifact_hash_fails_closed() -> None:
    current, verified = valid_fixture()
    first = current.partitions[0]
    second = first.model_copy(
        update={"partition_id": uid(306), "partition_key": "year=2023"}
    )
    current = current.model_copy(update={"partitions": (first, second)})
    decision = validate_manifest_structure(current, verified, CONTEXT)
    assert decision.result is ValidationResult.FAIL
    assert "duplicate_artifact_hash" in {item.code for item in decision.findings}


def test_validation_rejects_broken_revision_chain_and_source_binding() -> None:
    initial = version()
    broken_revision = version(
        suffix=2,
        source_sequence=1,
        revision_kind=RevisionKind.REVISION,
        supersedes=uid(999),
    )
    verified = verified_document((initial, broken_revision))
    current = manifest_for(verified, row_count=2)
    chain_decision = validate_synthetic_fact_dataset(current, (verified,), CONTEXT)
    assert "missing_predecessor" in {item.code for item in chain_decision.findings}

    wrong_source = version(source_id="other-source")
    verified = verified_document((wrong_source,))
    current = manifest_for(verified)
    source_decision = validate_synthetic_fact_dataset(current, (verified,), CONTEXT)
    assert "record_source_mismatch" in {item.code for item in source_decision.findings}


def test_validation_rejects_duplicate_fact_id_across_logical_keys() -> None:
    first = version(suffix=1, entity_key="entity-1")
    second = version(suffix=1, entity_key="entity-2")
    assert first.fact_version_id == second.fact_version_id
    assert first.payload_hash != second.payload_hash
    verified = verified_document((first, second))
    current = manifest_for(verified, row_count=2)

    decision = validate_synthetic_fact_dataset(current, (verified,), CONTEXT)

    assert decision.result is ValidationResult.FAIL
    assert "duplicate_fact_version_id" in {item.code for item in decision.findings}


def test_validation_rejects_payload_and_source_time_inconsistency() -> None:
    raw = version().model_dump(mode="python")
    raw["payload_hash"] = HASH_A
    verified = verified_document(raw_versions=[raw])
    payload_decision = validate_synthetic_fact_dataset(
        manifest_for(verified), (verified,), CONTEXT
    )
    assert payload_decision.result is ValidationResult.FAIL

    raw = version().model_dump(mode="python")
    availability = cast(list[dict[str, object]], raw["availability"])
    availability[0]["source_time_label"] = "2022-05-05T19:59:59Z"
    payload = dict(raw)
    payload.pop("payload_hash")
    raw["payload_hash"] = content_hash(payload)
    verified = verified_document(raw_versions=[raw])
    time_decision = validate_synthetic_fact_dataset(
        manifest_for(verified), (verified,), CONTEXT
    )
    assert time_decision.result is ValidationResult.FAIL


def test_validation_recomputes_rule_derivation_from_retained_raw_evidence() -> None:
    raw = bounded_evidence()
    rule_reference = artifact(
        251,
        CONSERVATIVE_UPPER_BOUND_RULE_HASH,
        location="rules/conservative-upper-bound-v1.json",
    )
    valid_derived = derive_conservative_upper_bound(raw, rule_reference)
    raw_record = version(suffix=1, availability=(raw,), entity_key="raw-evidence")
    derived_record = version(
        suffix=2, availability=(valid_derived,), entity_key="derived-evidence"
    )
    verified = verified_document((raw_record, derived_record))
    current = manifest_for(verified, row_count=2)
    assert (
        validate_synthetic_fact_dataset(current, (verified,), CONTEXT).result
        is ValidationResult.PASS
    )

    forged = AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.EXACT,
        lower_bound=datetime(2022, 5, 5, tzinfo=UTC),
        upper_bound=datetime(2022, 5, 5, tzinfo=UTC),
        precision=SourcePrecision.DATE,
        source_time_label="2022-05-05",
        source_timezone="UTC",
        basis=AvailabilityBasis.RULE_DERIVED,
        evidence_reference=raw.evidence_reference,
        rule_derivation=RuleDerivationV1(
            rule_reference=rule_reference,
            rule_version="1",
            input_evidence_hash=content_hash(raw),
        ),
    )
    forged_record = version(
        suffix=2, availability=(forged,), entity_key="derived-evidence"
    )
    verified = verified_document((raw_record, forged_record))
    current = manifest_for(verified, row_count=2)
    decision = validate_synthetic_fact_dataset(current, (verified,), CONTEXT)
    assert decision.result is ValidationResult.FAIL
    assert "rule_derivation_not_reproducible" in {
        item.code for item in decision.findings
    }


def test_parser_rejects_unknown_fields_and_unsupported_document_version() -> None:
    with pytest.raises(DatasetValidationError, match="unsupported_fact_schema_version"):
        parse_synthetic_fact_bytes(verified_document((version(),), schema_version="2"))
    with pytest.raises(DatasetValidationError, match="invalid_fact_document"):
        parse_synthetic_fact_bytes(verified_document((version(),), extra={"other": 1}))


def test_parser_rejects_missing_document_version() -> None:
    data = canonical_json({"fact_versions": [version()]})
    verified = VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )

    with pytest.raises(DatasetValidationError, match="invalid_fact_document"):
        parse_synthetic_fact_bytes(verified)


def test_parser_uses_only_verified_data_bytes() -> None:
    verified = verified_document((version(),))
    assert parse_synthetic_fact_bytes(verified) == (version(),)


def test_decision_hash_binds_findings_and_all_checked_hashes() -> None:
    current, verified = valid_fixture()
    passed = validate_synthetic_fact_dataset(current, verified, CONTEXT)
    changed_hashes = (
        passed.model_copy(update={"manifest_hash": HASH_C}),
        passed.model_copy(update={"validated_artifact_hashes": (HASH_C,)}),
        passed.model_copy(update={"validated_record_hashes": (HASH_C,)}),
    )
    for changed in changed_hashes:
        assert content_hash(changed) != content_hash(passed)

    failed = DatasetValidationDecisionV1(
        **CONTEXT.model_dump(mode="python"),
        manifest_hash=manifest_hash(current),
        validation_scope=ValidationScope.RECORDS,
        result=ValidationResult.FAIL,
        validated_artifact_hashes=(verified[0].content_hash,),
        validated_record_hashes=(
            parse_synthetic_fact_bytes(verified[0])[0].payload_hash,
        ),
        checked_contracts=("dataset-manifest-v1", "record-temporal-v1"),
        findings=(finding("first"),),
    )
    changed_finding = failed.model_copy(update={"findings": (finding("second"),)})
    assert content_hash(changed_finding) != content_hash(failed)


def test_decision_model_rejects_false_pass_and_invalid_scope_bindings() -> None:
    current, verified = valid_fixture()
    values: dict[str, object] = {
        **CONTEXT.model_dump(mode="python"),
        "manifest_hash": manifest_hash(current),
        "validation_scope": ValidationScope.RECORDS,
        "result": ValidationResult.PASS,
        "validated_artifact_hashes": (verified[0].content_hash,),
        "validated_record_hashes": (
            parse_synthetic_fact_bytes(verified[0])[0].payload_hash,
        ),
        "checked_contracts": ("dataset-manifest-v1", "record-temporal-v1"),
        "findings": (finding(),),
    }
    with pytest.raises(ValidationError, match="error findings"):
        DatasetValidationDecisionV1.model_validate(values)
    with pytest.raises(ValidationError, match="sorted and unique"):
        DatasetValidationDecisionV1.model_validate(
            {
                **values,
                "result": ValidationResult.FAIL,
                "validated_artifact_hashes": (HASH_C, HASH_A),
            }
        )
    with pytest.raises(ValidationError, match="record hashes"):
        DatasetValidationDecisionV1.model_validate(
            {
                **values,
                "result": ValidationResult.FAIL,
                "findings": (finding(),),
                "validation_scope": ValidationScope.MANIFEST_ONLY,
            }
        )
    with pytest.raises(ValidationError, match="record-temporal-v1"):
        DatasetValidationDecisionV1.model_validate(
            {
                **values,
                "result": ValidationResult.FAIL,
                "findings": (finding(),),
                "checked_contracts": ("dataset-manifest-v1",),
            }
        )


def test_bridge_builds_provenance_only_m0_reference() -> None:
    current, verified = valid_fixture()
    decision = validate_synthetic_fact_dataset(current, verified, CONTEXT)
    reference = artifact(
        500,
        manifest_hash(current),
        kind=ArtifactKind.DATASET,
        location="manifests/synthetic.json",
    )
    dataset = build_dataset_reference(current, reference, decision)
    assert dataset.content_hash == manifest_hash(current)
    assert dataset.temporal_coverage == TemporalCoverage(
        started_at=VALID_START, ended_at=VALID_END
    )
    assert dataset.point_in_time_policy == "explicit_record_evidence_v1"
    assert dataset.availability_timestamp_policy == "channel_scoped_no_defaults_v1"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("wrong_kind", "manifest_artifact_kind"),
        ("reference_hash", "manifest_hash_mismatch"),
        ("decision_hash", "manifest_hash_mismatch"),
        ("failed_decision", "manifest_not_validated"),
    ),
)
def test_bridge_rejects_failed_or_mismatched_decision(
    mutation: str, expected_code: str
) -> None:
    current, verified = valid_fixture()
    decision = validate_synthetic_fact_dataset(current, verified, CONTEXT)
    reference = artifact(
        500,
        manifest_hash(current),
        kind=ArtifactKind.DATASET,
        location="manifests/synthetic.json",
    )
    if mutation == "wrong_kind":
        reference = reference.model_copy(update={"kind": ArtifactKind.OTHER})
    elif mutation == "reference_hash":
        reference = reference.model_copy(update={"content_hash": HASH_C})
    elif mutation == "decision_hash":
        decision = decision.model_copy(update={"manifest_hash": HASH_C})
    else:
        decision = DatasetValidationDecisionV1(
            **{
                **decision.model_dump(mode="python"),
                "result": ValidationResult.FAIL,
                "findings": (finding("invalid_dataset"),),
            }
        )
    with pytest.raises(DatasetValidationError, match=expected_code):
        build_dataset_reference(current, reference, decision)
