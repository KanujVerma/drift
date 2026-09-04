"""Hash-pinned immutable identity fixture validation and historical replay."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from drift.datasets.assertions import build_validated_dataset_bundle
from drift.datasets.hashing import assertion_version_payload, schema_hash
from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
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
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentSubjectV1,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
)
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityPolicyV1,
    ChannelKind,
)
from drift.markets.identity import resolve_identity, resolve_identity_assignment
from drift.markets.validation import validate_identity_dataset
from drift.serialization.canonical import canonical_json, content_hash

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "datasets" / "m1b"
ASSIGNMENTS_HASH = "d47bb481991d63b615fb55e48b5b9d5f41fc7f30404eba5f929646f50f998f96"
RELATIONSHIPS_HASH = "78fdb58ceaac088ecefa0ff36036c01caebd38dace313153c62a2ca219d1b75d"
EXPECTED_BUNDLE_HASH = (
    "df6f114d50a8f8d0b434bdcdb88520e79a8b8446fe747b6bf17abc1f2eb20bde"
)
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="synthetic")


def artifact(suffix: int, digest: str, location: str) -> ArtifactReference:
    """Build one stable, safe provenance artifact reference."""
    return ArtifactReference(
        artifact_id=UUID(f"019b8240-0000-7000-8000-{suffix:012d}"),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=location,
    )


def fixture_schema(role: str) -> SchemaDescriptorV1:
    """Build the assertion schema required by the V2 envelope contract."""
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
        *(
            ("assignment_effect",)
            if role == "identity_assignment"
            else ("relationship_kind", "resolution_status")
        ),
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
    ordered = tuple(sorted(fields, key=lambda field: field.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash="b" * 64
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )


def fixture_context(suffix: int) -> ValidationRunContextV1:
    """Build one immutable validation context for a pinned fixture."""
    return ValidationRunContextV1(
        decision_id=UUID(f"019b8240-0000-7000-8000-{suffix:012d}"),
        validator_version="1",
        validator_implementation_hash="b" * 64,
        validation_profile_id="m1b-identity-fixture-v1",
        validation_profile_hash="c" * 64,
        checked_at=NOW,
    )


def identity_manifest(
    role: str, artifact_hash: str, byte_size: int, row_count: int
) -> DatasetManifestV2:
    """Bind a role-specific V2 manifest to one exact fixture byte stream."""
    schema = fixture_schema(role)
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
        semantic_state_field_ids=(
            ("assignment_effect",)
            if role == "identity_assignment"
            else ("relationship_kind", "resolution_status")
        ),
        declared_channels=(PUBLIC,),
    )
    return DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=UUID(
            "019b8240-0000-7000-8000-000000000601"
            if role == "identity_assignment"
            else "019b8240-0000-7000-8000-000000000602"
        ),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=NOW,
        source=SourceDescriptorV1(
            source_id="synthetic",
            publisher="Drift",
            product="M1b identity fixture",
            evidence_reference=artifact(610, "b" * 64, "evidence/source.json"),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="fixture",
            collector_version="1",
            evidence_reference=artifact(611, "c" * 64, "evidence/acquisition.json"),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=NOW,
            terms_evidence_reference=artifact(612, "b" * 64, "evidence/license.json"),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=UUID("019b8240-0000-7000-8000-000000000603"),
                partition_key="all",
                artifact=ArtifactReference(
                    artifact_id=UUID("019b8240-0000-7000-8000-000000000604"),
                    kind=ArtifactKind.DATASET,
                    content_hash=artifact_hash,
                    location=f"drift+sha256://{artifact_hash}",
                ),
                byte_size=byte_size,
                media_type="application/json",
                format_version="1",
                row_count=row_count,
                schema_hash=schema.schema_hash,
                coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
            ),
        ),
        temporal_contract=TemporalContractBindingV2(
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1, contract=contract
        ),
        lineage=None,
    )


def verified_bytes(data: bytes) -> VerifiedArtifactBytes:
    """Treat controlled test bytes as already read from one verified descriptor."""
    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=sha256(data).hexdigest(),
    )


def assignment_records_from(
    artifact_bytes: VerifiedArtifactBytes,
) -> tuple[IdentityAssignmentVersionV1, ...]:
    """Parse the exact assignment records retained by a verified fixture."""
    return tuple(
        IdentityAssignmentVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in json.loads(artifact_bytes.data)["records"]
    )


def relationship_records_from(
    artifact_bytes: VerifiedArtifactBytes,
) -> tuple[IdentityRelationshipVersionV1, ...]:
    """Parse the exact relationship records retained by a verified fixture."""
    return tuple(
        IdentityRelationshipVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in json.loads(artifact_bytes.data)["records"]
    )


def finding_codes(decision: DatasetValidationDecisionV2) -> set[str]:
    """Return validation finding codes without depending on message text."""
    return {finding.code for finding in decision.findings}


def test_hash_pinned_identity_fixtures_validate_and_rebuild_stably() -> None:
    """Changing fixture bytes or parent payload hashes must fail validation."""
    assignments = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    relationships = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships.json",
        RELATIONSHIPS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    assignments_manifest = identity_manifest(
        "identity_assignment", assignments.content_hash, assignments.byte_size, 8
    )
    relationships_manifest = identity_manifest(
        "identity_relationship",
        relationships.content_hash,
        relationships.byte_size,
        6,
    )
    assignments_decision = validate_identity_dataset(
        assignments_manifest, (assignments,), fixture_context(501)
    )
    relationships_decision = validate_identity_dataset(
        relationships_manifest, (relationships,), fixture_context(502)
    )
    assert assignments_decision.result is ValidationResult.PASS
    assert relationships_decision.result is ValidationResult.PASS
    assignment_records = tuple(
        IdentityAssignmentVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in json.loads(assignments.data)["records"]
    )
    relationship_records = tuple(
        IdentityRelationshipVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in json.loads(relationships.data)["records"]
    )
    assert len(assignment_records) == 8
    assert any(
        record.identity.model_dump(mode="json").get("issuer_id")
        == "019b8240-0000-7000-8000-000000000006"
        for record in assignment_records
    )
    assert any(
        record.identity.model_dump(mode="json").get("security_id")
        == "019b8240-0000-7000-8000-000000000007"
        for record in assignment_records
    )
    assert any(
        record.source_key == "alpha-b"
        and record.assignment_effect is IdentityAssignmentEffect.UNASSIGNED
        for record in assignment_records
    )
    s1 = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=UUID("019b8240-0000-7000-8000-000000000002"),
    )
    s3 = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=UUID("019b8240-0000-7000-8000-000000000007"),
    )
    assert any(
        record.relationship_kind is IdentityRelationshipKind.DISTINCT_FROM
        and {record.left, record.right} == {s1, s3}
        for record in relationship_records
    )
    assert any(
        record.relationship_kind is IdentityRelationshipKind.SUCCESSOR_OF
        and record.left == s3
        and record.right == s1
        for record in relationship_records
    )
    bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000501"),
        "1",
        datetime(2026, 9, 3, 12, tzinfo=UTC),
        (
            (relationships_manifest, relationships_decision),
            (assignments_manifest, assignments_decision),
        ),
    )
    rebuilt = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000501"),
        "1",
        NOW,
        (
            (assignments_manifest, assignments_decision),
            (relationships_manifest, relationships_decision),
        ),
    )
    assert content_hash(bundle) == EXPECTED_BUNDLE_HASH
    assert content_hash(rebuilt) == EXPECTED_BUNDLE_HASH
    assert assignments_decision.validated_record_hashes
    assert relationships_decision.validated_record_hashes

    assignment_subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic",
        source_key="alpha-a",
    )
    policy = AvailabilityPolicyV1(policy_id="strict")

    def assignment_query(bundle_hash: str) -> NormalizedSelectionQueryV1:
        return NormalizedSelectionQueryV1(
            schema_version="1",
            purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
            information_role=InformationRole.DECISION_INFORMATION,
            resolution_mode=ResolutionMode.AS_KNOWN,
            subject_hash=content_hash(assignment_subject),
            source_manifest_hash=assignments_decision.manifest_hash,
            validation_decision_hash=content_hash(assignments_decision),
            context_bundle_hashes=(bundle_hash,),
            dataset_role_hash=content_hash(assignments_manifest.dataset_role),
            record_contract_hash=content_hash(
                assignments_manifest.temporal_contract.contract
            ),
            schema_hash=assignments_manifest.schema_definition.schema_hash,
            knowledge_cutoff=NOW,
            evaluation_time=NOW,
            requested_channel=PUBLIC,
            policy_id=policy.policy_id,
            policy_hash=content_hash(policy),
        )

    first_result = resolve_identity_assignment(
        assignment_subject,
        assignment_records,
        assignment_query(content_hash(bundle)),
        bundle,
        assignments_manifest,
        assignments_decision,
        policy,
        {},
    )
    rebuilt_result = resolve_identity_assignment(
        assignment_subject,
        assignment_records,
        assignment_query(content_hash(rebuilt)),
        rebuilt,
        assignments_manifest,
        assignments_decision,
        policy,
        {},
    )
    assert first_result == rebuilt_result
    assert tuple(item.internal_id for item in first_result.assigned_identities) == (
        UUID("019b8240-0000-7000-8000-000000000002"),
    )


def test_identity_fixture_replays_equivalence_before_later_distinction() -> None:
    """A pinned earlier cutoff must retain equivalence despite a later correction."""
    relationships = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships.json",
        RELATIONSHIPS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    assignments = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    manifest = identity_manifest(
        "identity_relationship",
        relationships.content_hash,
        relationships.byte_size,
        6,
    )
    decision = validate_identity_dataset(
        manifest, (relationships,), fixture_context(502)
    )
    assignment_manifest = identity_manifest(
        "identity_assignment", assignments.content_hash, assignments.byte_size, 8
    )
    assignment_decision = validate_identity_dataset(
        assignment_manifest, (assignments,), fixture_context(501)
    )
    bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000502"),
        "1",
        NOW,
        ((assignment_manifest, assignment_decision), (manifest, decision)),
    )
    document = json.loads(relationships.data)
    relationship_records = tuple(
        IdentityRelationshipVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in document["records"]
    )
    assignment_records = tuple(
        IdentityAssignmentVersionV1.model_validate_json(canonical_json(raw_record))
        for raw_record in json.loads(assignments.data)["records"]
    )
    subject = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=UUID("019b8240-0000-7000-8000-000000000002"),
    )

    def query(cutoff: datetime) -> NormalizedSelectionQueryV1:
        return NormalizedSelectionQueryV1(
            schema_version="1",
            purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
            information_role=InformationRole.DECISION_INFORMATION,
            resolution_mode=ResolutionMode.AS_KNOWN,
            subject_hash=content_hash(subject),
            source_manifest_hash=decision.manifest_hash,
            validation_decision_hash=content_hash(decision),
            context_bundle_hashes=(content_hash(bundle),),
            dataset_role_hash=content_hash(manifest.dataset_role),
            record_contract_hash=content_hash(manifest.temporal_contract.contract),
            schema_hash=manifest.schema_definition.schema_hash,
            knowledge_cutoff=cutoff,
            evaluation_time=cutoff,
            requested_channel=PUBLIC,
            policy_id="strict",
            policy_hash=content_hash(AvailabilityPolicyV1(policy_id="strict")),
        )

    policy = AvailabilityPolicyV1(policy_id="strict")
    before = resolve_identity(
        subject,
        assignment_records,
        relationship_records,
        query(datetime(2020, 2, 1, tzinfo=UTC)),
        bundle,
        manifest,
        decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    after = resolve_identity(
        subject,
        assignment_records,
        relationship_records,
        query(datetime(2021, 2, 2, tzinfo=UTC)),
        bundle,
        manifest,
        decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    assert tuple(item.internal_id for item in before.resolved_identities) == (
        UUID("019b8240-0000-7000-8000-000000000002"),
        UUID("019b8240-0000-7000-8000-000000000003"),
    )
    assert before.classification.value == "resolved"
    assert after.resolved_identities == ()
    assert after.classification.value == "conflict"


def test_earlier_identity_manifest_replays_unchanged_after_later_manifest() -> None:
    """A later correction manifest must not alter an earlier pinned replay."""
    assignments_artifact = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    relationships_artifact = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships.json",
        RELATIONSHIPS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    assignment_records = assignment_records_from(assignments_artifact)
    relationship_document = json.loads(relationships_artifact.data)
    early_document = {
        "schema_version": "1",
        "records": (relationship_document["records"][0],),
    }
    early_artifact = verified_bytes(canonical_json(early_document))
    early_manifest = identity_manifest(
        "identity_relationship",
        early_artifact.content_hash,
        early_artifact.byte_size,
        1,
    )
    early_decision = validate_identity_dataset(
        early_manifest, (early_artifact,), fixture_context(510)
    )
    assignment_manifest = identity_manifest(
        "identity_assignment",
        assignments_artifact.content_hash,
        assignments_artifact.byte_size,
        8,
    )
    assignment_decision = validate_identity_dataset(
        assignment_manifest, (assignments_artifact,), fixture_context(501)
    )
    early_bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000510"),
        "1",
        NOW,
        (
            (assignment_manifest, assignment_decision),
            (early_manifest, early_decision),
        ),
    )
    late_manifest = identity_manifest(
        "identity_relationship",
        relationships_artifact.content_hash,
        relationships_artifact.byte_size,
        6,
    )
    late_decision = validate_identity_dataset(
        late_manifest, (relationships_artifact,), fixture_context(511)
    )
    late_bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000511"),
        "2",
        NOW,
        (
            (assignment_manifest, assignment_decision),
            (late_manifest, late_decision),
        ),
    )
    subject = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=UUID("019b8240-0000-7000-8000-000000000002"),
    )
    policy = AvailabilityPolicyV1(policy_id="strict")

    def query(
        manifest: DatasetManifestV2,
        decision: DatasetValidationDecisionV2,
        bundle_hash: str,
    ) -> NormalizedSelectionQueryV1:
        return NormalizedSelectionQueryV1(
            schema_version="1",
            purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
            information_role=InformationRole.DECISION_INFORMATION,
            resolution_mode=ResolutionMode.AS_KNOWN,
            subject_hash=content_hash(subject),
            source_manifest_hash=decision.manifest_hash,
            validation_decision_hash=content_hash(decision),
            context_bundle_hashes=(bundle_hash,),
            dataset_role_hash=content_hash(manifest.dataset_role),
            record_contract_hash=content_hash(manifest.temporal_contract.contract),
            schema_hash=manifest.schema_definition.schema_hash,
            knowledge_cutoff=NOW,
            evaluation_time=NOW,
            requested_channel=PUBLIC,
            policy_id=policy.policy_id,
            policy_hash=content_hash(policy),
        )

    early_records = relationship_records_from(early_artifact)
    first_replay = resolve_identity(
        subject,
        assignment_records,
        early_records,
        query(early_manifest, early_decision, content_hash(early_bundle)),
        early_bundle,
        early_manifest,
        early_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    late_result = resolve_identity(
        subject,
        assignment_records,
        relationship_records_from(relationships_artifact),
        query(late_manifest, late_decision, content_hash(late_bundle)),
        late_bundle,
        late_manifest,
        late_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    repeated_replay = resolve_identity(
        subject,
        assignment_records,
        early_records,
        query(early_manifest, early_decision, content_hash(early_bundle)),
        early_bundle,
        early_manifest,
        early_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )

    assert tuple(item.internal_id for item in first_replay.resolved_identities) == (
        UUID("019b8240-0000-7000-8000-000000000002"),
        UUID("019b8240-0000-7000-8000-000000000003"),
    )
    assert late_result.classification.value == "conflict"
    assert repeated_replay == first_replay


def test_fixture_replays_unassignment_and_superseded_issuer_link() -> None:
    """The fixture must apply exact unassignment and the corrected issuer link."""
    assignments_artifact = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    relationships_artifact = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships.json",
        RELATIONSHIPS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    assignment_records = assignment_records_from(assignments_artifact)
    relationship_records = relationship_records_from(relationships_artifact)
    assignment_manifest = identity_manifest(
        "identity_assignment",
        assignments_artifact.content_hash,
        assignments_artifact.byte_size,
        8,
    )
    relationship_manifest = identity_manifest(
        "identity_relationship",
        relationships_artifact.content_hash,
        relationships_artifact.byte_size,
        6,
    )
    assignment_decision = validate_identity_dataset(
        assignment_manifest, (assignments_artifact,), fixture_context(503)
    )
    relationship_decision = validate_identity_dataset(
        relationship_manifest, (relationships_artifact,), fixture_context(504)
    )
    bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000503"),
        "1",
        NOW,
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
        ),
    )
    policy = AvailabilityPolicyV1(policy_id="strict")

    def query_for_subject(
        subject_hash: str,
        manifest: DatasetManifestV2,
        decision: DatasetValidationDecisionV2,
    ) -> NormalizedSelectionQueryV1:
        return NormalizedSelectionQueryV1(
            schema_version="1",
            purpose=M1bSelectionPurpose.IDENTITY_RESOLUTION,
            information_role=InformationRole.DECISION_INFORMATION,
            resolution_mode=ResolutionMode.AS_KNOWN,
            subject_hash=subject_hash,
            source_manifest_hash=decision.manifest_hash,
            validation_decision_hash=content_hash(decision),
            context_bundle_hashes=(content_hash(bundle),),
            dataset_role_hash=content_hash(manifest.dataset_role),
            record_contract_hash=content_hash(manifest.temporal_contract.contract),
            schema_hash=manifest.schema_definition.schema_hash,
            knowledge_cutoff=NOW,
            evaluation_time=NOW,
            requested_channel=PUBLIC,
            policy_id=policy.policy_id,
            policy_hash=content_hash(policy),
        )

    assignment_subject = IdentityAssignmentSubjectV1(
        identity_kind=IdentityKind.SECURITY,
        source_namespace="synthetic",
        source_key="alpha-b",
    )
    unassigned = resolve_identity_assignment(
        assignment_subject,
        assignment_records,
        query_for_subject(
            content_hash(assignment_subject), assignment_manifest, assignment_decision
        ),
        bundle,
        assignment_manifest,
        assignment_decision,
        policy,
        {},
    )
    assert unassigned.classification.value == "resolved"
    assert unassigned.assigned_identities == ()

    issuer = IdentityReferenceV1(
        kind=IdentityKind.ISSUER,
        internal_id=UUID("019b8240-0000-7000-8000-000000000001"),
    )
    issuer_result = resolve_identity(
        issuer,
        assignment_records,
        relationship_records,
        query_for_subject(
            content_hash(issuer), relationship_manifest, relationship_decision
        ),
        bundle,
        relationship_manifest,
        relationship_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    issuer_chain = tuple(
        record
        for record in relationship_records
        if record.revision.logical_record_id
        == UUID("019b8240-0000-7000-8000-000000000220")
    )
    corrected = next(
        record for record in issuer_chain if record.revision.source_sequence == 1
    )
    wrong = next(
        record for record in issuer_chain if record.revision.source_sequence == 0
    )
    assert issuer_result.resolved_identities == (issuer,)
    assert content_hash(corrected) in issuer_result.selected_assertion_hashes
    assert content_hash(wrong) not in issuer_result.selected_assertion_hashes

    s3 = IdentityReferenceV1(
        kind=IdentityKind.SECURITY,
        internal_id=UUID("019b8240-0000-7000-8000-000000000007"),
    )
    s3_result = resolve_identity(
        s3,
        assignment_records,
        relationship_records,
        query_for_subject(
            content_hash(s3), relationship_manifest, relationship_decision
        ),
        bundle,
        relationship_manifest,
        relationship_decision,
        policy,
        {},
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
    )
    s3_correction_hashes = {
        content_hash(record)
        for record in relationship_records
        if record.source_relationship_code in {"split-distinct", "split-successor"}
    }
    assert s3_result.resolved_identities == (s3,)
    assert s3_correction_hashes.issubset(s3_result.selected_assertion_hashes)


@pytest.mark.parametrize(
    ("data", "expected_code"),
    (
        (b"", "identity_dataset_invalid_json"),
        (b"{}", "identity_dataset_invalid_envelope"),
        (
            b'{"records":[],"schema_version":"1"}',
            "identity_record_count_mismatch",
        ),
        (
            b'{"records":[NaN],"schema_version":"1"}',
            "identity_record_invalid",
        ),
    ),
)
def test_invalid_identity_envelopes_fail_closed(
    data: bytes, expected_code: str
) -> None:
    """Malformed, empty, or non-canonical data must return deterministic FAIL."""
    artifact_bytes = verified_bytes(data)
    manifest = identity_manifest(
        "identity_assignment", artifact_bytes.content_hash, artifact_bytes.byte_size, 1
    )

    decision = validate_identity_dataset(
        manifest, (artifact_bytes,), fixture_context(505)
    )

    assert decision.result is ValidationResult.FAIL
    assert decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert expected_code in finding_codes(decision)


def test_payload_hash_mutation_fails_identity_validation() -> None:
    """Changing assertion payload bytes without rehashing must not validate."""
    fixture = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    document = json.loads(fixture.data)
    document["records"][0]["source_key"] = "mutated-without-parent-rehash"
    mutated = verified_bytes(canonical_json(document))
    manifest = identity_manifest(
        "identity_assignment", mutated.content_hash, mutated.byte_size, 8
    )

    decision = validate_identity_dataset(manifest, (mutated,), fixture_context(506))

    assert decision.result is ValidationResult.FAIL
    assert "identity_payload_hash_mismatch" in finding_codes(decision)


def test_identity_validation_checks_schema_channel_and_correction_chain() -> None:
    """A PASS must cover role schema, declared channel, and complete chains."""
    fixture = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )

    wrong_schema_manifest = identity_manifest(
        "identity_assignment", fixture.content_hash, fixture.byte_size, 8
    )
    relationship_shape = identity_manifest(
        "identity_relationship", fixture.content_hash, fixture.byte_size, 8
    )
    wrong_schema_manifest = wrong_schema_manifest.model_copy(
        update={
            "schema_definition": relationship_shape.schema_definition,
            "partitions": relationship_shape.partitions,
            "temporal_contract": relationship_shape.temporal_contract,
        }
    )
    wrong_schema = validate_identity_dataset(
        wrong_schema_manifest, (fixture,), fixture_context(507)
    )
    assert wrong_schema.result is ValidationResult.FAIL
    assert "identity_role_schema_mismatch" in finding_codes(wrong_schema)

    channel_document = json.loads(fixture.data)
    channel_record = channel_document["records"][0]
    channel_record["revision"]["availability"][0]["channel"]["identifier"] = (
        "undeclared"
    )
    channel_record["revision"]["payload_hash"] = "a" * 64
    parsed_channel_record = IdentityAssignmentVersionV1.model_validate_json(
        canonical_json(channel_record)
    )
    channel_record["revision"]["payload_hash"] = content_hash(
        assertion_version_payload(parsed_channel_record)
    )
    channel_bytes = verified_bytes(canonical_json(channel_document))
    channel_manifest = identity_manifest(
        "identity_assignment", channel_bytes.content_hash, channel_bytes.byte_size, 8
    )
    channel_decision = validate_identity_dataset(
        channel_manifest, (channel_bytes,), fixture_context(508)
    )
    assert channel_decision.result is ValidationResult.FAIL
    assert "identity_undeclared_availability_channel" in finding_codes(channel_decision)

    chain_document = json.loads(fixture.data)
    unassignment = next(
        record
        for record in chain_document["records"]
        if record["assignment_effect"] == "unassigned"
    )
    unassignment["revision"]["supersedes_record_version_id"] = (
        "019b8240-0000-7000-8000-000000000999"
    )
    unassignment["revision"]["payload_hash"] = "a" * 64
    parsed_unassignment = IdentityAssignmentVersionV1.model_validate_json(
        canonical_json(unassignment)
    )
    unassignment["revision"]["payload_hash"] = content_hash(
        assertion_version_payload(parsed_unassignment)
    )
    chain_bytes = verified_bytes(canonical_json(chain_document))
    chain_manifest = identity_manifest(
        "identity_assignment", chain_bytes.content_hash, chain_bytes.byte_size, 8
    )
    chain_decision = validate_identity_dataset(
        chain_manifest, (chain_bytes,), fixture_context(509)
    )
    assert chain_decision.result is ValidationResult.FAIL
    assert "missing_predecessor" in finding_codes(chain_decision)


def test_identity_validation_rejects_extra_and_mixed_role_fields() -> None:
    """Identity roles must use their exact descriptor sets, not a subset."""
    fixture = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments.json",
        ASSIGNMENTS_HASH,
        ResolverLimits(max_bytes=100_000),
    )
    base = identity_manifest(
        "identity_assignment", fixture.content_hash, fixture.byte_size, 8
    )
    extra_field = FieldDescriptorV1(
        field_id="forbidden_extra",
        name="forbidden_extra",
        logical_type=LogicalType.STRING,
        nullable=False,
    )
    mixed_field = FieldDescriptorV1(
        field_id="resolution_status",
        name="resolution_status",
        logical_type=LogicalType.STRING,
        nullable=False,
    )
    for field in (extra_field, mixed_field):
        fields = tuple(
            sorted(
                (*base.schema_definition.fields, field),
                key=lambda item: item.field_id,
            )
        )
        provisional = SchemaDescriptorV1.model_construct(
            schema_version="1", fields=fields, schema_hash="b" * 64
        )
        schema = SchemaDescriptorV1(
            schema_version="1", fields=fields, schema_hash=schema_hash(provisional)
        )
        manifest = base.model_copy(
            update={
                "schema_definition": schema,
                "partitions": tuple(
                    partition.model_copy(update={"schema_hash": schema.schema_hash})
                    for partition in base.partitions
                ),
            }
        )
        decision = validate_identity_dataset(manifest, (fixture,), fixture_context(512))
        assert decision.result is ValidationResult.FAIL
        assert "identity_role_schema_mismatch" in finding_codes(decision)
