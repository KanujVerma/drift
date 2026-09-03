"""Tests for additive assertion-aware dataset manifests."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.datasets.hashing import manifest_hash, schema_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    AssertionEffectiveShape,
    AssertionTemporalContractV1,
    DatasetKind,
    DatasetManifestV1,
    DatasetManifestV2,
    DatasetRoleV1,
    EvidenceGranularity,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    RecordTemporalContractV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="synthetic")


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7 with a readable suffix."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def artifact(suffix: int, digest: str, location: str) -> ArtifactReference:
    """Build a fixed safe artifact."""
    return ArtifactReference(
        artifact_id=uid(suffix),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=location,
    )


FIELDS = (
    FieldDescriptorV1(
        field_id="revision.logical_record_id",
        name="revision.logical_record_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.record_version_id",
        name="revision.record_version_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.revision_kind",
        name="revision.revision_kind",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.supersedes_record_version_id",
        name="revision.supersedes_record_version_id",
        logical_type=LogicalType.STRING,
        nullable=True,
    ),
    FieldDescriptorV1(
        field_id="revision.source_sequence",
        name="revision.source_sequence",
        logical_type=LogicalType.INTEGER,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.availability",
        name="revision.availability",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.source_artifact",
        name="revision.source_artifact",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision.payload_hash",
        name="revision.payload_hash",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="effective_interval",
        name="effective_interval",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="assignment_effect",
        name="assignment_effect",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
)


def schema() -> SchemaDescriptorV1:
    """Build a canonically hashed fixed schema."""
    ordered = tuple(sorted(FIELDS, key=lambda field: field.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash=HASH_A
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )


def assertion_contract(**changes: object) -> AssertionTemporalContractV1:
    """Build the fixed assertion field binding used by these tests."""
    values: dict[str, object] = {
        "contract_version": "1",
        "evidence_granularity": EvidenceGranularity.RECORD,
        "logical_record_id_field_id": "revision.logical_record_id",
        "record_version_id_field_id": "revision.record_version_id",
        "revision_kind_field_id": "revision.revision_kind",
        "supersedes_field_id": "revision.supersedes_record_version_id",
        "source_sequence_field_id": "revision.source_sequence",
        "availability_field_id": "revision.availability",
        "source_artifact_field_id": "revision.source_artifact",
        "payload_hash_field_id": "revision.payload_hash",
        "effective_time_field_id": "effective_interval",
        "effective_shape": AssertionEffectiveShape.INTERVAL,
        "semantic_state_field_ids": ("assignment_effect",),
        "declared_channels": (PUBLIC,),
    }
    values.update(changes)
    return AssertionTemporalContractV1.model_validate(values)


def partition(schema_value: SchemaDescriptorV1) -> PartitionDescriptorV1:
    """Build one content-addressed partition descriptor."""
    return PartitionDescriptorV1(
        partition_id=uid(4),
        partition_key="all",
        artifact=artifact(5, HASH_A, f"drift+sha256://{HASH_A}"),
        byte_size=1,
        media_type="application/json",
        format_version="1",
        row_count=1,
        schema_hash=schema_value.schema_hash,
        coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
    )


def manifest_v2(**changes: object) -> DatasetManifestV2:
    """Build a valid assertion manifest."""
    schema_value = schema()
    values: dict[str, object] = {
        "manifest_schema_version": "2",
        "hash_profile": "drift-canonical-json-sha256-v1",
        "dataset_id": uid(1),
        "dataset_version": "1",
        "dataset_kind": DatasetKind.SOURCE_FACTS,
        "dataset_role": DatasetRoleV1(
            namespace="drift", name="identity_assignment", version="1"
        ),
        "created_at": NOW,
        "source": SourceDescriptorV1(
            source_id="synthetic",
            publisher="Drift",
            product="M1b fixture",
            evidence_reference=artifact(6, HASH_A, "evidence/source.json"),
        ),
        "acquisition": AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="fixture",
            collector_version="1",
            evidence_reference=artifact(7, HASH_B, "evidence/acquisition.json"),
        ),
        "license": LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=NOW,
            terms_evidence_reference=artifact(8, HASH_C, "evidence/license.json"),
        ),
        "schema_definition": schema_value,
        "partitions": (partition(schema_value),),
        "temporal_contract": TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=assertion_contract(),
        ),
        "lineage": None,
    }
    values.update(changes)
    return DatasetManifestV2.model_validate(values)


def test_temporal_contract_binding_rejects_a_mismatched_discriminator() -> None:
    """Changing the wrapper kind must not reinterpret an assertion contract."""
    with pytest.raises(ValidationError, match="kind"):
        TemporalContractBindingV2(
            kind=TemporalContractKindV2.RECORD_TEMPORAL_V1,
            contract=assertion_contract(),
        )


def test_assertion_contract_canonicalizes_state_fields_and_channels() -> None:
    """Insertion order must not change temporal contract identity."""
    vendor = AvailabilityChannelV1(kind=ChannelKind.VENDOR, identifier="synthetic")
    contract = assertion_contract(
        semantic_state_field_ids=("z", "assignment_effect"),
        declared_channels=(vendor, PUBLIC),
    )
    assert contract.semantic_state_field_ids == ("assignment_effect", "z")
    assert contract.declared_channels == (PUBLIC, vendor)


def test_manifest_v2_rejects_contract_fields_missing_from_schema() -> None:
    """A contract cannot claim semantic fields absent from stored bytes."""
    with pytest.raises(ValidationError, match="field"):
        manifest_v2(
            temporal_contract=TemporalContractBindingV2(
                kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
                contract=assertion_contract(
                    semantic_state_field_ids=("missing_state",)
                ),
            )
        )


def test_manifest_v2_hash_binds_dataset_role() -> None:
    """Changing the role must change manifest identity."""
    original = manifest_v2()
    changed = manifest_v2(
        dataset_role=DatasetRoleV1(
            namespace="drift", name="identity_relationship", version="1"
        )
    )
    assert manifest_hash(original) != manifest_hash(changed)


def test_manifest_v1_does_not_accept_v2_wire_data() -> None:
    """Additive V2 data cannot silently deserialize under V1 semantics."""
    values = manifest_v2().model_dump(mode="python")
    with pytest.raises(ValidationError):
        DatasetManifestV1.model_validate(values)


def test_record_contract_can_be_wrapped_without_modifying_it() -> None:
    """V2 may name the existing V1 contract without changing its model."""
    record_contract = RecordTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_key_field_ids=("key",),
        valid_start_field_id="start",
        valid_end_field_id="end",
        availability_field_id="availability",
        revision_id_field_id="revision_id",
        supersedes_field_id="supersedes",
        source_sequence_field_id="sequence",
        value_field_id="value",
        null_reason_field_id="null_reason",
        declared_channels=(PUBLIC,),
    )
    binding = TemporalContractBindingV2(
        kind=TemporalContractKindV2.RECORD_TEMPORAL_V1,
        contract=record_contract,
    )
    assert binding.contract is record_contract
