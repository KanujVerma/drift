"""Tests for immutable, asset-neutral dataset manifests."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from drift.datasets.hashing import (
    derived_temporal_coverage,
    manifest_body,
    manifest_hash,
    schema_body,
    schema_hash,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV1,
    DeterminismClaim,
    EvidenceGranularity,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LineageDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    RecordTemporalContractV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
)
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind
from drift.serialization.canonical import canonical_json

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
FIXED_DATASET_ID = UUID("019b8240-0000-7000-8000-000000000001")
FIXED_PARTITION_ID = UUID("019b8240-0000-7000-8000-000000000002")
FIXED_SOURCE_ARTIFACT_ID = UUID("019b8240-0000-7000-8000-000000000003")
FIXED_ACQUISITION_ARTIFACT_ID = UUID("019b8240-0000-7000-8000-000000000004")
FIXED_LICENSE_ARTIFACT_ID = UUID("019b8240-0000-7000-8000-000000000005")
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="source")
VENDOR = AvailabilityChannelV1(kind=ChannelKind.VENDOR, identifier="vendor")


def artifact(
    content_hash_value: str = HASH_A,
    *,
    location: str = "evidence/reference.json",
    artifact_id: UUID | None = None,
) -> ArtifactReference:
    """Build a valid retained artifact reference."""
    return ArtifactReference(
        artifact_id=artifact_id or uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=content_hash_value,
        location=location,
    )


FIELD_A = FieldDescriptorV1(
    field_id="availability_at",
    name="available_at",
    logical_type=LogicalType.DATETIME,
    nullable=False,
)
FIELD_B = FieldDescriptorV1(
    field_id="fact_id",
    name="fact_id",
    logical_type=LogicalType.STRING,
    nullable=False,
)
FIELD_C = FieldDescriptorV1(
    field_id="null_reason",
    name="null_reason",
    logical_type=LogicalType.STRING,
    nullable=True,
)
FIELD_D = FieldDescriptorV1(
    field_id="revision_id",
    name="revision_id",
    logical_type=LogicalType.STRING,
    nullable=False,
)
FIELD_E = FieldDescriptorV1(
    field_id="source_sequence",
    name="source_sequence",
    logical_type=LogicalType.INTEGER,
    nullable=False,
)
FIELD_F = FieldDescriptorV1(
    field_id="supersedes",
    name="supersedes",
    logical_type=LogicalType.STRING,
    nullable=True,
)
FIELD_G = FieldDescriptorV1(
    field_id="valid_end",
    name="valid_end",
    logical_type=LogicalType.DATETIME,
    nullable=False,
)
FIELD_H = FieldDescriptorV1(
    field_id="valid_start",
    name="valid_start",
    logical_type=LogicalType.DATETIME,
    nullable=False,
)
FIELD_I = FieldDescriptorV1(
    field_id="value",
    name="value",
    logical_type=LogicalType.DECIMAL,
    nullable=True,
    unit="USD",
)
FIELD_J = FieldDescriptorV1(
    field_id="alternate_value",
    name="alternate_value",
    logical_type=LogicalType.DECIMAL,
    nullable=True,
)
FIELDS = (
    FIELD_A,
    FIELD_B,
    FIELD_C,
    FIELD_D,
    FIELD_E,
    FIELD_F,
    FIELD_G,
    FIELD_H,
    FIELD_I,
    FIELD_J,
)


def schema(
    *, fields: tuple[FieldDescriptorV1, ...] = FIELDS, **changes: object
) -> SchemaDescriptorV1:
    """Build a schema with the correct self-excluding hash."""
    values: dict[str, object] = {"schema_version": "1", "fields": fields}
    values.update(changes)
    stored_hash = values.pop("schema_hash", None)
    if stored_hash is None:
        provisional_values = cast(
            Any,
            {
                **values,
                "fields": tuple(sorted(fields, key=lambda field: field.field_id)),
            },
        )
        provisional = SchemaDescriptorV1.model_construct(
            **provisional_values,
            schema_hash=HASH_A,
        )
        stored_hash = schema_hash(provisional)
    return SchemaDescriptorV1.model_validate({**values, "schema_hash": stored_hash})


def contract(**changes: object) -> RecordTemporalContractV1:
    """Build the required record-level temporal field bindings."""
    values: dict[str, object] = {
        "logical_key_field_ids": ("fact_id",),
        "valid_start_field_id": "valid_start",
        "valid_end_field_id": "valid_end",
        "availability_field_id": "availability_at",
        "revision_id_field_id": "revision_id",
        "supersedes_field_id": "supersedes",
        "source_sequence_field_id": "source_sequence",
        "value_field_id": "value",
        "null_reason_field_id": "null_reason",
        "declared_channels": (PUBLIC,),
    }
    values.update(changes)
    return RecordTemporalContractV1.model_validate(values)


def partition(
    partition_key: str = "year=2021",
    content_hash_value: str = HASH_A,
    *,
    schema_definition: SchemaDescriptorV1 | None = None,
    **changes: object,
) -> PartitionDescriptorV1:
    """Build a partition bound to its schema."""
    schema_value = schema_definition or schema()
    values: dict[str, object] = {
        "partition_id": uuid7(),
        "partition_key": partition_key,
        "artifact": artifact(
            content_hash_value,
            location=f"drift+sha256://{content_hash_value}",
        ),
        "byte_size": 1,
        "media_type": "application/json",
        "format_version": "1",
        "row_count": 1,
        "schema_hash": schema_value.schema_hash,
        "coverage": TemporalCoverage(started_at=NOW, ended_at=NOW),
    }
    values.update(changes)
    return PartitionDescriptorV1.model_validate(values)


def lineage(
    *, output_schema_hash: str | None = None, **changes: object
) -> LineageDescriptorV1:
    """Build deterministic derived-data provenance."""
    values: dict[str, object] = {
        "input_manifest_hashes": (HASH_B,),
        "transformation_reference": artifact(HASH_B),
        "configuration_hash": HASH_C,
        "implementation_reference": artifact(HASH_C),
        "environment_hash": HASH_A,
        "output_schema_hash": output_schema_hash or schema().schema_hash,
        "executed_at": NOW,
        "determinism": DeterminismClaim.DETERMINISTIC,
    }
    values.update(changes)
    return LineageDescriptorV1.model_validate(values)


def manifest(
    *,
    fields: tuple[FieldDescriptorV1, ...] = FIELDS,
    partitions: tuple[PartitionDescriptorV1, ...] | None = None,
    **changes: object,
) -> DatasetManifestV1:
    """Build a valid source-data manifest."""
    schema_definition = schema(fields=fields)
    partition_values = (
        partitions
        if partitions is not None
        else (partition(schema_definition=schema_definition),)
    )
    values: dict[str, object] = {
        "dataset_id": uuid7(),
        "dataset_version": "1",
        "dataset_kind": DatasetKind.SOURCE_FACTS,
        "created_at": NOW,
        "source": SourceDescriptorV1(
            source_id="source-1",
            publisher="Example Publisher",
            product="Example Product",
            evidence_reference=artifact(),
        ),
        "acquisition": AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="collector",
            collector_version="1",
            evidence_reference=artifact(HASH_B),
        ),
        "license": LicenseDescriptorV1(
            provider_legal_name="Example Provider",
            license_reference="agreement-1",
            acquired_at=NOW,
            terms_evidence_reference=artifact(HASH_C),
        ),
        "schema_definition": schema_definition,
        "partitions": partition_values,
        "temporal_contract": contract(),
        "lineage": None,
    }
    values.update(changes)
    return DatasetManifestV1.model_validate(values)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ({"manifest_schema_version": "2"}, "manifest_schema_version"),
        ({"partitions": ()}, "partitions"),
        ({"temporal_contract": contract(availability_field_id="missing")}, "field"),
        (
            {"lineage": lineage(), "dataset_kind": DatasetKind.SOURCE_FACTS},
            "lineage",
        ),
        ({"dataset_kind": DatasetKind.DERIVED_FACTS, "lineage": None}, "lineage"),
    ),
)
def test_manifest_rejects_invalid_contracts(
    mutation: dict[str, object], message: str
) -> None:
    """Manifest-level provenance contracts fail closed."""
    values = manifest().model_dump(mode="python")
    values.update(mutation)
    with pytest.raises(ValidationError, match=message):
        DatasetManifestV1.model_validate(values)


def test_manifest_hash_sorts_partitions_by_key_and_content_hash() -> None:
    """Partition insertion order cannot affect manifest identity."""
    schema_definition = schema()
    first = partition("year=2021", HASH_A, schema_definition=schema_definition)
    second = partition("year=2022", HASH_B, schema_definition=schema_definition)
    dataset_id = uuid7()
    left = manifest(
        partitions=(first, second),
        dataset_id=dataset_id,
        schema_definition=schema_definition,
    )
    right = manifest(
        partitions=(second, first),
        dataset_id=dataset_id,
        schema_definition=schema_definition,
        source=left.source,
        acquisition=left.acquisition,
        license=left.license,
    )
    assert manifest_hash(left) == manifest_hash(right)


def test_equivalent_input_orders_have_equal_models_bytes_and_hashes() -> None:
    """Ordering canonicalization occurs at model construction time."""
    schema_definition = schema()
    first = partition("year=2021", HASH_A, schema_definition=schema_definition)
    second = partition("year=2022", HASH_B, schema_definition=schema_definition)
    dataset_id = uuid7()
    left = manifest(
        fields=tuple(reversed(FIELDS)),
        partitions=(second, first),
        dataset_id=dataset_id,
    )
    right = manifest(
        fields=FIELDS,
        partitions=(first, second),
        dataset_id=dataset_id,
        source=left.source,
        acquisition=left.acquisition,
        license=left.license,
    )
    assert left == right
    assert canonical_json(left) == canonical_json(right)
    assert manifest_hash(left) == manifest_hash(right)


def test_no_availability_default_exists_on_manifest_or_partition() -> None:
    """Availability remains explicit at the record level."""
    assert "availability" not in DatasetManifestV1.model_fields
    assert "availability" not in PartitionDescriptorV1.model_fields


def test_channel_and_lineage_input_ordering_is_canonical() -> None:
    """Unordered channel and lineage input sets cannot alter manifest identity."""
    baseline = manifest()
    left = baseline.model_copy(
        update={"temporal_contract": contract(declared_channels=(VENDOR, PUBLIC))}
    )
    right = baseline.model_copy(
        update={"temporal_contract": contract(declared_channels=(PUBLIC, VENDOR))}
    )
    assert left == right
    assert canonical_json(left) == canonical_json(right)
    assert manifest_hash(left) == manifest_hash(right)

    unordered_lineage = lineage(input_manifest_hashes=(HASH_B, HASH_A))
    derived_left = baseline.model_copy(
        update={
            "dataset_kind": DatasetKind.DERIVED_FACTS,
            "lineage": unordered_lineage,
        }
    )
    derived_right = baseline.model_copy(
        update={
            "dataset_kind": DatasetKind.DERIVED_FACTS,
            "lineage": unordered_lineage.model_copy(
                update={"input_manifest_hashes": (HASH_A, HASH_B)}
            ),
        }
    )
    assert derived_left == derived_right
    assert canonical_json(derived_left) == canonical_json(derived_right)
    assert manifest_hash(derived_left) == manifest_hash(derived_right)


@pytest.mark.parametrize(
    ("fields", "message"),
    (
        (FIELDS + (FIELD_A,), "field IDs"),
        (FIELDS + (FIELD_B.model_copy(update={"field_id": "other"}),), "field names"),
    ),
)
def test_schema_rejects_duplicate_field_identity(
    fields: tuple[FieldDescriptorV1, ...], message: str
) -> None:
    """Field IDs and names are separately stable identities."""
    with pytest.raises(ValidationError, match=message):
        schema(fields=fields)


def test_schema_rejects_a_mismatched_stored_hash() -> None:
    """The stored schema digest must bind the canonical schema body."""
    with pytest.raises(ValidationError, match="schema hash"):
        schema(schema_hash=HASH_A)


def test_reversed_partition_coverage_is_rejected() -> None:
    """Partition coverage keeps M0's inclusive ordered interval contract."""
    with pytest.raises(ValidationError, match="coverage"):
        partition(
            coverage=TemporalCoverage(
                started_at=datetime(2026, 9, 2, tzinfo=UTC),
                ended_at=NOW,
            )
        )


def test_manifest_rejects_duplicate_partition_ids_and_keys() -> None:
    """Partitions cannot ambiguously identify the same bytes or key."""
    schema_definition = schema()
    first = partition("year=2021", HASH_A, schema_definition=schema_definition)
    duplicate_id = partition(
        "year=2022",
        HASH_B,
        schema_definition=schema_definition,
        partition_id=first.partition_id,
    )
    duplicate_key = partition("year=2021", HASH_B, schema_definition=schema_definition)
    with pytest.raises(ValidationError, match="partition IDs"):
        manifest(partitions=(first, duplicate_id))
    with pytest.raises(ValidationError, match="partition keys"):
        manifest(partitions=(first, duplicate_key))


def test_manifest_rejects_partition_schema_hash_mismatch() -> None:
    """Every partition must declare the manifest schema digest."""
    with pytest.raises(ValidationError, match="schema hash"):
        manifest(partitions=(partition(schema_hash=HASH_B),))


def test_temporal_contract_requires_existing_fields_and_unique_channels() -> None:
    """Record bindings and claimed channels are explicit and unambiguous."""
    with pytest.raises(ValidationError, match="field"):
        manifest(temporal_contract=contract(value_field_id="missing"))
    with pytest.raises(ValidationError, match="channels"):
        manifest(temporal_contract=contract(declared_channels=(PUBLIC, PUBLIC)))


def test_lineage_requires_unique_inputs_and_matching_output_schema() -> None:
    """Derived manifests bind a reproducible distinct-input lineage."""
    with pytest.raises(ValidationError, match="input"):
        lineage(input_manifest_hashes=(HASH_A, HASH_A))
    with pytest.raises(ValidationError, match="output schema"):
        manifest(
            dataset_kind=DatasetKind.DERIVED_FACTS,
            lineage=lineage(output_schema_hash=HASH_A),
        )


def test_naive_provenance_times_are_rejected() -> None:
    """All retained provenance timestamps must identify a timezone."""
    naive = datetime(2026, 9, 1, 12)
    with pytest.raises(ValidationError, match="timezone-aware"):
        AcquisitionDescriptorV1(
            acquired_at=naive,
            collector_id="collector",
            collector_version="1",
            evidence_reference=artifact(),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        manifest(created_at=naive)
    with pytest.raises(ValidationError, match="timezone-aware"):
        lineage(executed_at=naive)


def test_source_evidence_locator_rejects_credentials() -> None:
    """A retained source locator cannot preserve a credential."""
    with pytest.raises(ValidationError, match="credentials"):
        SourceDescriptorV1(
            source_id="source-1",
            publisher="Example Publisher",
            product="Example Product",
            evidence_reference=artifact(location="https://user:secret@example.test/a"),
        )


@pytest.mark.parametrize(
    "location",
    (
        "https://example.test/evidence?api_key=secret",
        "https://example.test/evidence?token=secret",
        "https://example.test/evidence?signature=secret",
        "https://example.test/evidence?signed=true",
        "https://example.test/evidence?X-Amz-Credential=credential",
    ),
)
def test_source_evidence_locator_rejects_credential_query_parameters(
    location: str,
) -> None:
    """Credential and signed URL query fields cannot enter immutable provenance."""
    with pytest.raises(ValidationError, match="credentials"):
        SourceDescriptorV1(
            source_id="source-1",
            publisher="Example Publisher",
            product="Example Product",
            evidence_reference=artifact(location=location),
        )


def test_source_evidence_locator_allows_credential_free_reference() -> None:
    """A retained public source reference remains valid without credential data."""
    source = SourceDescriptorV1(
        source_id="source-1",
        publisher="Example Publisher",
        product="Example Product",
        evidence_reference=artifact(location="https://example.test/evidence?id=123"),
    )
    assert source.evidence_reference.location == "https://example.test/evidence?id=123"


@pytest.mark.parametrize(
    "location",
    (
        "partitions/year=2021.json",
        "https://example.test/partition.json",
        "s3://bucket/partition.json",
        f"drift+sha256://{HASH_B}",
    ),
)
def test_partition_artifact_requires_matching_stable_content_uri(location: str) -> None:
    """A partition cannot bind its digest to a mutable locator or different digest."""
    with pytest.raises(ValidationError, match="stable content URI"):
        partition(artifact=artifact(HASH_A, location=location))


def test_partition_artifact_accepts_exact_stable_content_uri() -> None:
    """A partition retains only a content-addressed artifact locator."""
    partition_value = partition()
    assert partition_value.artifact.location == f"drift+sha256://{HASH_A}"


def test_license_version_is_optional_provenance() -> None:
    """No legal conclusion is required when a retained version is absent."""
    assert manifest().license.license_version is None


def test_derived_temporal_coverage_uses_inclusive_partition_bounds() -> None:
    """Manifest coverage is the min/max inclusive coverage of its partitions."""
    schema_definition = schema()
    earlier = partition(
        "year=2021",
        HASH_A,
        schema_definition=schema_definition,
        coverage=TemporalCoverage(
            started_at=datetime(2021, 1, 1, tzinfo=UTC),
            ended_at=datetime(2021, 12, 31, tzinfo=UTC),
        ),
    )
    later = partition(
        "year=2022",
        HASH_B,
        schema_definition=schema_definition,
        coverage=TemporalCoverage(
            started_at=datetime(2022, 1, 1, tzinfo=UTC),
            ended_at=datetime(2022, 12, 31, tzinfo=UTC),
        ),
    )
    assert derived_temporal_coverage((later, earlier)) == TemporalCoverage(
        started_at=earlier.coverage.started_at,
        ended_at=later.coverage.ended_at,
    )


def test_schema_hash_mutation_table_binds_every_identity_field() -> None:
    """Every schema identity input changes both body and digest."""
    baseline = schema()
    mutations = (
        schema(schema_version="2"),
        schema(fields=FIELDS[:-1]),
        schema(fields=(FIELD_A.model_copy(update={"field_id": "other"}),) + FIELDS[1:]),
        schema(fields=(FIELD_A.model_copy(update={"name": "other"}),) + FIELDS[1:]),
        schema(
            fields=(FIELD_A.model_copy(update={"logical_type": LogicalType.STRING}),)
            + FIELDS[1:]
        ),
        schema(fields=(FIELD_A.model_copy(update={"nullable": True}),) + FIELDS[1:]),
        schema(fields=(FIELD_A.model_copy(update={"unit": "seconds"}),) + FIELDS[1:]),
    )
    for changed in mutations:
        assert schema_body(changed) != schema_body(baseline)
        assert schema_hash(changed) != schema_hash(baseline)
    reordered = schema(fields=tuple(reversed(FIELDS)))
    assert reordered == baseline
    assert schema_hash(reordered) == schema_hash(baseline)


def test_canonical_hashes_match_pinned_literals() -> None:
    """Fixed schema and manifest inputs produce independently pinned digests."""
    schema_definition = schema()
    source = SourceDescriptorV1(
        source_id="source-1",
        publisher="Example Publisher",
        product="Example Product",
        evidence_reference=artifact(
            artifact_id=FIXED_SOURCE_ARTIFACT_ID,
            location="https://example.test/source-evidence?id=1",
        ),
    )
    acquisition = AcquisitionDescriptorV1(
        acquired_at=NOW,
        collector_id="collector",
        collector_version="1",
        evidence_reference=artifact(
            HASH_B,
            artifact_id=FIXED_ACQUISITION_ARTIFACT_ID,
        ),
    )
    license_descriptor = LicenseDescriptorV1(
        provider_legal_name="Example Provider",
        license_reference="agreement-1",
        acquired_at=NOW,
        terms_evidence_reference=artifact(
            HASH_C,
            artifact_id=FIXED_LICENSE_ARTIFACT_ID,
        ),
    )
    partition_value = partition(
        schema_definition=schema_definition,
        partition_id=FIXED_PARTITION_ID,
        artifact=artifact(
            artifact_id=FIXED_PARTITION_ID,
            location=f"drift+sha256://{HASH_A}",
        ),
    )
    manifest_value = manifest(
        dataset_id=FIXED_DATASET_ID,
        source=source,
        acquisition=acquisition,
        license=license_descriptor,
        schema_definition=schema_definition,
        partitions=(partition_value,),
    )
    assert (schema_hash(schema_definition), manifest_hash(manifest_value)) == (
        "079ca973b9fbf91cfbcaf6b93a229a73c848821f1c43495e430486f4ac364c4d",
        "a45ab8ade7ee8e9000cfe84c3877b8ab3830d1f610de7c348ab7384cc6b49fc4",
    )


def test_manifest_hash_mutation_table_binds_every_manifest_descriptor() -> None:
    """Manifest identity includes all retained top-level descriptor content."""
    baseline = manifest()
    baseline_partition = baseline.partitions[0]
    changed_schema = schema(
        fields=(FIELD_A.model_copy(update={"name": "available_timestamp"}),)
        + FIELDS[1:]
    )
    changed_schema_partition = baseline_partition.model_copy(
        update={"schema_hash": changed_schema.schema_hash}
    )
    changed_part = baseline_partition.model_copy(update={"partition_key": "year=2022"})
    changed_source_evidence = baseline.source.evidence_reference.model_copy(
        update={"content_hash": HASH_B}
    )
    changed_acquisition_evidence = baseline.acquisition.evidence_reference.model_copy(
        update={"content_hash": HASH_C}
    )
    changed_terms_evidence = baseline.license.terms_evidence_reference.model_copy(
        update={"content_hash": HASH_B}
    )
    mutations = (
        baseline.model_copy(update={"dataset_id": uuid7()}),
        baseline.model_copy(update={"dataset_version": "2"}),
        baseline.model_copy(
            update={"created_at": datetime(2026, 9, 2, 12, tzinfo=UTC)}
        ),
        baseline.model_copy(
            update={
                "source": baseline.source.model_copy(update={"source_id": "source-2"})
            }
        ),
        baseline.model_copy(
            update={"source": baseline.source.model_copy(update={"publisher": "Other"})}
        ),
        baseline.model_copy(
            update={"source": baseline.source.model_copy(update={"product": "Other"})}
        ),
        baseline.model_copy(
            update={
                "source": baseline.source.model_copy(update={"source_version": "2"})
            }
        ),
        baseline.model_copy(
            update={
                "source": baseline.source.model_copy(
                    update={"evidence_reference": changed_source_evidence}
                )
            }
        ),
        baseline.model_copy(
            update={
                "acquisition": baseline.acquisition.model_copy(
                    update={"acquired_at": datetime(2026, 9, 2, 12, tzinfo=UTC)}
                )
            }
        ),
        baseline.model_copy(
            update={
                "acquisition": baseline.acquisition.model_copy(
                    update={"collector_id": "other"}
                )
            }
        ),
        baseline.model_copy(
            update={
                "acquisition": baseline.acquisition.model_copy(
                    update={"collector_version": "2"}
                )
            }
        ),
        baseline.model_copy(
            update={
                "acquisition": baseline.acquisition.model_copy(
                    update={"evidence_reference": changed_acquisition_evidence}
                )
            }
        ),
        baseline.model_copy(
            update={
                "license": baseline.license.model_copy(
                    update={"provider_legal_name": "Other"}
                )
            }
        ),
        baseline.model_copy(
            update={
                "license": baseline.license.model_copy(
                    update={"license_reference": "agreement-2"}
                )
            }
        ),
        baseline.model_copy(
            update={
                "license": baseline.license.model_copy(update={"license_version": "2"})
            }
        ),
        baseline.model_copy(
            update={
                "license": baseline.license.model_copy(
                    update={"acquired_at": datetime(2026, 9, 2, 12, tzinfo=UTC)}
                )
            }
        ),
        baseline.model_copy(
            update={
                "license": baseline.license.model_copy(
                    update={"terms_evidence_reference": changed_terms_evidence}
                )
            }
        ),
        baseline.model_copy(
            update={
                "schema_definition": changed_schema,
                "partitions": (changed_schema_partition,),
            }
        ),
        baseline.model_copy(update={"partitions": (changed_part,)}),
        baseline.model_copy(
            update={
                "temporal_contract": baseline.temporal_contract.model_copy(
                    update={"logical_key_field_ids": ("alternate_value",)}
                )
            }
        ),
        baseline.model_copy(
            update={
                "temporal_contract": baseline.temporal_contract.model_copy(
                    update={"declared_channels": (PUBLIC, VENDOR)}
                )
            }
        ),
    )
    for changed in mutations:
        assert manifest_body(changed) != manifest_body(baseline)
        assert manifest_hash(changed) != manifest_hash(baseline)

    version_mutations = (
        DatasetManifestV1.model_construct(
            **{**baseline.__dict__, "manifest_schema_version": "2"}
        ),
        DatasetManifestV1.model_construct(
            **{**baseline.__dict__, "hash_profile": "alternate"}
        ),
    )
    for changed in version_mutations:
        assert manifest_body(changed) != manifest_body(baseline)
        assert manifest_hash(changed) != manifest_hash(baseline)


def test_manifest_hash_mutation_table_binds_partition_fields_and_lineage() -> None:
    """Each physical partition fact and lineage detail is identity-bearing."""
    baseline = manifest()
    partition_value = baseline.partitions[0]
    partition_mutations = (
        partition_value.model_copy(update={"partition_id": uuid7()}),
        partition_value.model_copy(update={"partition_key": "year=2022"}),
        partition_value.model_copy(
            update={
                "artifact": partition_value.artifact.model_copy(
                    update={
                        "content_hash": HASH_B,
                        "location": f"drift+sha256://{HASH_B}",
                    }
                )
            }
        ),
        partition_value.model_copy(update={"byte_size": 2}),
        partition_value.model_copy(update={"media_type": "application/x-parquet"}),
        partition_value.model_copy(update={"format_version": "2"}),
        partition_value.model_copy(update={"row_count": 2}),
        partition_value.model_copy(
            update={
                "coverage": TemporalCoverage(
                    started_at=NOW,
                    ended_at=datetime(2026, 9, 2, tzinfo=UTC),
                )
            }
        ),
    )
    for changed_partition in partition_mutations:
        changed = baseline.model_copy(update={"partitions": (changed_partition,)})
        assert manifest_hash(changed) != manifest_hash(baseline)

    derived = baseline.model_copy(
        update={
            "dataset_kind": DatasetKind.DERIVED_FACTS,
            "lineage": lineage(
                output_schema_hash=baseline.schema_definition.schema_hash
            ),
        }
    )
    assert derived.lineage is not None
    base_lineage = derived.lineage
    changed_transformation_reference = base_lineage.transformation_reference.model_copy(
        update={"content_hash": HASH_A}
    )
    changed_implementation_reference = base_lineage.implementation_reference.model_copy(
        update={"content_hash": HASH_A}
    )
    lineage_mutations = (
        base_lineage.model_copy(update={"input_manifest_hashes": (HASH_A, HASH_B)}),
        base_lineage.model_copy(
            update={"transformation_reference": changed_transformation_reference}
        ),
        base_lineage.model_copy(update={"configuration_hash": HASH_A}),
        base_lineage.model_copy(
            update={"implementation_reference": changed_implementation_reference}
        ),
        base_lineage.model_copy(update={"environment_hash": HASH_B}),
        base_lineage.model_copy(
            update={"executed_at": datetime(2026, 9, 2, 12, tzinfo=UTC)}
        ),
        base_lineage.model_copy(update={"determinism": DeterminismClaim.UNKNOWN}),
    )
    for changed_lineage in lineage_mutations:
        changed = derived.model_copy(update={"lineage": changed_lineage})
        assert manifest_hash(changed) != manifest_hash(derived)


def test_manifest_identity_table_binds_kind_contract_and_cross_hashes() -> None:
    """Every remaining manifest identity field is covered independently."""
    baseline = manifest()
    alternate_field_id = "alternate_value"
    temporal_binding_fields = (
        "logical_key_field_ids",
        "valid_start_field_id",
        "valid_end_field_id",
        "availability_field_id",
        "revision_id_field_id",
        "supersedes_field_id",
        "source_sequence_field_id",
        "value_field_id",
        "null_reason_field_id",
    )
    for field_name in temporal_binding_fields:
        value: tuple[str, ...] | str = (
            (alternate_field_id,)
            if field_name == "logical_key_field_ids"
            else alternate_field_id
        )
        changed = baseline.model_copy(
            update={
                "temporal_contract": baseline.temporal_contract.model_copy(
                    update={field_name: value}
                )
            }
        )
        assert manifest_body(changed) != manifest_body(baseline)
        assert manifest_hash(changed) != manifest_hash(baseline)

    changed_kind = DatasetManifestV1.model_construct(
        **{**baseline.__dict__, "dataset_kind": DatasetKind.DERIVED_FACTS}
    )
    assert manifest_body(changed_kind) != manifest_body(baseline)
    assert manifest_hash(changed_kind) != manifest_hash(baseline)

    changed_partition = PartitionDescriptorV1.model_construct(
        **{**baseline.partitions[0].__dict__, "schema_hash": HASH_B}
    )
    changed_partition_manifest = DatasetManifestV1.model_construct(
        **{**baseline.__dict__, "partitions": (changed_partition,)}
    )
    assert manifest_body(changed_partition_manifest) != manifest_body(baseline)
    assert manifest_hash(changed_partition_manifest) != manifest_hash(baseline)
    with pytest.raises(ValidationError, match="partition schema hash"):
        baseline.model_copy(update={"partitions": (changed_partition,)})

    derived = baseline.model_copy(
        update={
            "dataset_kind": DatasetKind.DERIVED_FACTS,
            "lineage": lineage(
                output_schema_hash=baseline.schema_definition.schema_hash
            ),
        }
    )
    assert derived.lineage is not None
    changed_lineage = derived.lineage.model_copy(update={"output_schema_hash": HASH_B})
    changed_lineage_manifest = DatasetManifestV1.model_construct(
        **{**derived.__dict__, "lineage": changed_lineage}
    )
    assert manifest_body(changed_lineage_manifest) != manifest_body(derived)
    assert manifest_hash(changed_lineage_manifest) != manifest_hash(derived)
    with pytest.raises(ValidationError, match="output schema hash"):
        derived.model_copy(update={"lineage": changed_lineage})


def test_record_contract_declares_only_record_granularity() -> None:
    """M1a does not establish dataset-level availability defaults."""
    assert contract().evidence_granularity is EvidenceGranularity.RECORD
