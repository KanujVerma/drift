"""Tests for exact-object V2 validation decisions and dataset bundles."""

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest

from drift.datasets.assertions import (
    build_validated_dataset_bundle,
    validate_manifest_v2_structure,
)
from drift.datasets.events import (
    build_manifest_v2_recorded_event,
    build_validation_v2_completed_event,
)
from drift.datasets.hashing import manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    AssertionEffectiveShape,
    AssertionTemporalContractV1,
    DatasetKind,
    DatasetManifestV2,
    DatasetRoleV1,
    EvidenceGranularity,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
    TemporalContractBindingV2,
    TemporalContractKindV2,
)
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind
from drift.serialization.canonical import content_hash

HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="synthetic")
DATA = b"{}"
DATA_HASH = sha256(DATA).hexdigest()


def uid(suffix: int) -> UUID:
    """Return one fixed UUIDv7."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def artifact(
    suffix: int,
    digest: str,
    location: str,
    kind: ArtifactKind = ArtifactKind.OTHER,
) -> ArtifactReference:
    """Build a fixed artifact reference."""
    return ArtifactReference(
        artifact_id=uid(suffix), kind=kind, content_hash=digest, location=location
    )


def fixed_schema() -> SchemaDescriptorV1:
    """Build the smallest assertion-bound schema used by validation tests."""
    names = (
        "revision.logical_record_id",
        "revision.record_version_id",
        "revision.revision_kind",
        "revision.supersedes_record_version_id",
        "revision.source_sequence",
        "revision.availability",
        "revision.source_artifact",
        "revision.payload_hash",
        "effective_interval",
        "assignment_effect",
    )
    fields = tuple(
        FieldDescriptorV1(
            field_id=name,
            name=name,
            logical_type=(
                LogicalType.INTEGER
                if name == "revision.source_sequence"
                else LogicalType.JSON
                if name
                in {
                    "revision.availability",
                    "revision.source_artifact",
                    "effective_interval",
                }
                else LogicalType.STRING
            ),
            nullable=name == "revision.supersedes_record_version_id",
        )
        for name in names
    )
    ordered = tuple(sorted(fields, key=lambda item: item.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash=HASH_B
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )


def fixed_manifest(role: str = "identity_assignment") -> DatasetManifestV2:
    """Build a one-partition source manifest over exact verified bytes."""
    schema_value = fixed_schema()
    contract = AssertionTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_record_id_field_id="revision.logical_record_id",
        record_version_id_field_id="revision.record_version_id",
        revision_kind_field_id="revision.revision_kind",
        supersedes_field_id="revision.supersedes_record_version_id",
        source_sequence_field_id="revision.source_sequence",
        availability_field_id="revision.availability",
        source_artifact_field_id="revision.source_artifact",
        payload_hash_field_id="revision.payload_hash",
        effective_time_field_id="effective_interval",
        effective_shape=AssertionEffectiveShape.INTERVAL,
        semantic_state_field_ids=("assignment_effect",),
        declared_channels=(PUBLIC,),
    )
    return DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uid(1 if role == "identity_assignment" else 21),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=NOW,
        source=SourceDescriptorV1(
            source_id="synthetic",
            publisher="Drift",
            product="M1b fixture",
            evidence_reference=artifact(2, HASH_B, "evidence/source.json"),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="fixture",
            collector_version="1",
            evidence_reference=artifact(3, HASH_C, "evidence/acquisition.json"),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=NOW,
            terms_evidence_reference=artifact(4, HASH_B, "evidence/license.json"),
        ),
        schema_definition=schema_value,
        partitions=(
            PartitionDescriptorV1(
                partition_id=uid(5),
                partition_key="all",
                artifact=artifact(
                    6,
                    DATA_HASH,
                    f"drift+sha256://{DATA_HASH}",
                    ArtifactKind.DATASET,
                ),
                byte_size=len(DATA),
                media_type="application/json",
                format_version="1",
                row_count=1,
                schema_hash=schema_value.schema_hash,
                coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=contract,
        ),
        lineage=None,
    )


def context(suffix: int = 10) -> ValidationRunContextV1:
    """Build a fixed validation run context."""
    return ValidationRunContextV1(
        decision_id=uid(suffix),
        validator_version="1",
        validator_implementation_hash=HASH_B,
        validation_profile_id="m1b-structure-v1",
        validation_profile_hash=HASH_C,
        checked_at=NOW,
    )


def verified(data: bytes = DATA) -> VerifiedArtifactBytes:
    """Build an exact-byte object whose own digest is truthful."""
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=sha256(data).hexdigest()
    )


def passing_decision(role: str = "identity_assignment") -> DatasetValidationDecisionV2:
    """Produce a real passing decision rather than a mock."""
    return validate_manifest_v2_structure(
        fixed_manifest(role),
        (verified(),),
        context(10 if role == "identity_assignment" else 22),
    )


def test_manifest_v2_validation_binds_exact_contract_and_artifact() -> None:
    """Dropping any manifest discriminator or exact artifact hash must fail."""
    manifest = fixed_manifest()
    decision = validate_manifest_v2_structure(manifest, (verified(),), context())
    assert decision.result is ValidationResult.PASS
    assert decision.manifest_hash == manifest_hash(manifest)
    assert decision.dataset_role_hash == content_hash(manifest.dataset_role)
    assert decision.schema_hash == manifest.schema_definition.schema_hash
    assert decision.temporal_contract_hash == content_hash(
        manifest.temporal_contract.contract
    )
    assert decision.validated_artifact_hashes == (DATA_HASH,)
    assert decision.validated_record_hashes == ()


def test_manifest_v2_validation_fails_for_wrong_verified_bytes() -> None:
    """Self-consistent but undeclared bytes cannot satisfy the manifest."""
    decision = validate_manifest_v2_structure(
        fixed_manifest(), (verified(b'{"tampered":true}'),), context()
    )
    assert decision.result is ValidationResult.FAIL
    assert {finding.code for finding in decision.findings} == {
        "missing_partition_artifact",
        "undeclared_partition_artifact",
    }


def test_decision_v2_rejects_forged_contract_hash() -> None:
    """A bundle cannot accept a decision relabeled for another contract."""
    manifest = fixed_manifest()
    decision = passing_decision()
    values = decision.model_dump(mode="python")
    values["temporal_contract_hash"] = HASH_B
    forged = DatasetValidationDecisionV2.model_validate(values)
    with pytest.raises(ValueError, match="contract"):
        build_validated_dataset_bundle(uid(30), "1", NOW, ((manifest, forged),))


def test_validated_bundle_sorts_and_binds_passing_members() -> None:
    """Member insertion order cannot alter a validated dataset bundle."""
    assignment_manifest = fixed_manifest()
    relationship_manifest = fixed_manifest("identity_relationship")
    assignment_decision = passing_decision()
    relationship_decision = passing_decision("identity_relationship")
    bundle = build_validated_dataset_bundle(
        uid(30),
        "1",
        NOW,
        (
            (relationship_manifest, relationship_decision),
            (assignment_manifest, assignment_decision),
        ),
    )
    assert tuple(member.dataset_role.name for member in bundle.members) == (
        "identity_assignment",
        "identity_relationship",
    )


def test_validated_bundle_rejects_failed_or_duplicate_role_members() -> None:
    """A bundle cannot promote failed validation or ambiguous role ownership."""
    manifest = fixed_manifest()
    passed = passing_decision()
    failed_values = passed.model_dump(mode="python")
    failed_values["result"] = ValidationResult.FAIL
    failed_values["findings"] = (
        ValidationFindingV1(
            code="forced_failure",
            severity=FindingSeverity.ERROR,
            message="forced failure",
        ),
    )
    failed = DatasetValidationDecisionV2.model_validate(failed_values)
    with pytest.raises(ValueError, match="passing"):
        build_validated_dataset_bundle(uid(30), "1", NOW, ((manifest, failed),))
    with pytest.raises(ValueError, match="role"):
        build_validated_dataset_bundle(
            uid(30), "1", NOW, ((manifest, passed), (manifest, passed))
        )


def test_v2_audit_events_expose_schema_discriminators() -> None:
    """V2 audit events must not look like V1 validation evidence."""
    manifest = fixed_manifest()
    decision = passing_decision()
    reference = artifact(
        40,
        manifest_hash(manifest),
        "evidence/manifest-v2.json",
        ArtifactKind.DATASET,
    )
    recorded = build_manifest_v2_recorded_event(manifest, reference)
    completed = build_validation_v2_completed_event(manifest, decision)
    recorded_payload = cast(Mapping[str, object], recorded.payload)
    completed_payload = cast(Mapping[str, object], completed.payload)
    assert recorded.schema_version == "2"
    assert recorded_payload["manifest_schema_version"] == "2"
    assert recorded_payload["temporal_contract_kind"] == "assertion_temporal_v1"
    assert completed.schema_version == "2"
    assert completed_payload["decision_schema_version"] == "2"


def test_v2_validation_event_rejects_mismatched_schema_or_contract() -> None:
    """A relabeled decision cannot become immutable audit evidence."""
    manifest = fixed_manifest()
    decision = passing_decision()
    for field in ("schema_hash", "temporal_contract_hash"):
        forged = decision.model_copy(update={field: HASH_C})
        with pytest.raises(DatasetValidationError, match=field):
            build_validation_v2_completed_event(manifest, forged)
