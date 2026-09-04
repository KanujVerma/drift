"""Hash-pinned immutable identity fixture validation and historical replay."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from drift.datasets.assertions import (
    build_cutoff_selection_proof,
    build_validated_dataset_bundle,
)
from drift.datasets.hashing import assertion_version_payload, schema_hash
from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    CutoffSelectionProofV1,
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    ValidatedDatasetBundleV1,
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
    ExternalIdentifierMappingVersionV1,
    IdentityAssignmentEffect,
    IdentityAssignmentSubjectV1,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    IdentityResolutionResultV1,
    ListingHistoryCoverageResolutionV1,
    ListingHistoryCoverageStatus,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleEventKind,
    ListingLifecycleResolutionV1,
    ListingLifecycleStatus,
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationReason,
    ListingTerminationResolutionV1,
    ListingTerminationStatus,
    ListingTerminationVersionV1,
    RecordResolutionClassification,
    SecurityClassificationStatus,
    SecurityClassificationVersionV1,
)
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityPolicyV1,
    ChannelKind,
)
from drift.markets.identity import (
    _relationship_chains_for_subject,
    _select_identity_chain,
    resolve_external_identifier,
    resolve_identity,
    resolve_identity_assignment,
    resolve_listing_history_coverage,
    resolve_listing_lifecycle,
    resolve_listing_termination,
    resolve_primary_listing,
    resolve_security_classification,
)
from drift.markets.validation import (
    EXTERNAL_IDENTIFIER_MAPPING_SCHEMA_V1,
    LISTING_HISTORY_COVERAGE_SCHEMA_V1,
    LISTING_LIFECYCLE_SCHEMA_V1,
    LISTING_ROLE_SCHEMA_V1,
    LISTING_TERMINATION_SCHEMA_V1,
    SECURITY_CLASSIFICATION_SCHEMA_V1,
    validate_identity_bundle_references,
    validate_identity_dataset,
)
from drift.serialization.canonical import canonical_json, content_hash

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "datasets" / "m1b"
ASSIGNMENTS_HASH = "d47bb481991d63b615fb55e48b5b9d5f41fc7f30404eba5f929646f50f998f96"
RELATIONSHIPS_HASH = "78fdb58ceaac088ecefa0ff36036c01caebd38dace313153c62a2ca219d1b75d"
ASSIGNMENTS_V2_HASH = "9ecafcc7a4a4080c68e6ee3b223e1b578579a06e5a8cc109c0adf3f929ddc6d1"
RELATIONSHIPS_V2_HASH = (
    "7cf23769bc0d26532f8a2ae142ec0ae9548b575cacb0b8170722ade6f41db26f"
)
TASK3_FIXTURE_HASHES = {
    "external_identifier_mapping": (
        "65ac3b52f5894401ed4f6564bb702f3014fac7f05f20aaa93d0354598a3180c7"
    ),
    "security_classification": (
        "cfed335e22f23fea603901fc35b1b817c7b414eef10b46106f0a19989f467336"
    ),
    "listing_role": "075f46482c528af1dac9beb6467af37fae5e60d529a38546fbfd48fb84e140c5",
    "listing_lifecycle": (
        "05844803d91223a61036b31bb219a94f26c5f5cc80700d2d0602f1b54a735305"
    ),
    "listing_termination": (
        "d118d172e8408df849b64bf5fefa02967404b0d0fa7f3807003a2a5f60dc407e"
    ),
    "listing_history_coverage": (
        "67f1ebc7c594b4bd915eda01780acb91bb1ff31e93fbcab7ed169f590d606b28"
    ),
}
TASK3_FIXTURE_FILES = {
    "external_identifier_mapping": "external-identifiers.json",
    "security_classification": "security-classifications.json",
    "listing_role": "listing-roles.json",
    "listing_lifecycle": "listing-lifecycle.json",
    "listing_termination": "listing-terminations.json",
    "listing_history_coverage": "listing-history-coverage.json",
}
TASK3_FIXTURE_ROWS = {
    "external_identifier_mapping": 4,
    "security_classification": 2,
    "listing_role": 4,
    "listing_lifecycle": 11,
    "listing_termination": 9,
    "listing_history_coverage": 4,
}
EXPECTED_BUNDLE_V2_HASH = (
    "ad4e53455227d00d2c4755890d6608d8ef2fe87fff744870631d60996580b561"
)
EXPECTED_BUNDLE_HASH = (
    "df6f114d50a8f8d0b434bdcdb88520e79a8b8446fe747b6bf17abc1f2eb20bde"
)
NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="synthetic")

TASK3_SCHEMAS = {
    "external_identifier_mapping": EXTERNAL_IDENTIFIER_MAPPING_SCHEMA_V1,
    "security_classification": SECURITY_CLASSIFICATION_SCHEMA_V1,
    "listing_role": LISTING_ROLE_SCHEMA_V1,
    "listing_lifecycle": LISTING_LIFECYCLE_SCHEMA_V1,
    "listing_termination": LISTING_TERMINATION_SCHEMA_V1,
    "listing_history_coverage": LISTING_HISTORY_COVERAGE_SCHEMA_V1,
}
TASK3_EFFECTIVE_FIELDS = {
    "external_identifier_mapping": (
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    "security_classification": (
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    "listing_role": ("effective_interval", AssertionEffectiveShape.INTERVAL),
    "listing_lifecycle": ("effective_time", AssertionEffectiveShape.BOUNDARY),
    "listing_termination": ("effective_time", AssertionEffectiveShape.BOUNDARY),
    "listing_history_coverage": (
        "complete_through",
        AssertionEffectiveShape.BOUNDARY,
    ),
}
TASK3_SEMANTIC_FIELDS = {
    "external_identifier_mapping": (
        "identifier_value",
        "mapping_status",
        "namespace",
        "target",
    ),
    "security_classification": (
        "domestic_status",
        "incorporation_country",
        "instrument_form",
        "issuer_domicile",
        "issuer_form",
        "issuer_id",
        "security_id",
        "share_class_label",
        "source_fields",
        "source_taxonomy_id",
        "source_taxonomy_version",
    ),
    "listing_role": (
        "listing_id",
        "methodology_id",
        "methodology_version",
        "role",
        "security_id",
    ),
    "listing_lifecycle": ("event_kind", "listing_id", "related_listing_id"),
    "listing_termination": (
        "last_regular_trade_time",
        "listing_id",
        "outcome_evidence_status",
        "reason",
        "source_reason_code",
        "source_reason_text",
        "successor_relationship_ids",
    ),
    "listing_history_coverage": ("coverage_status", "listing_id"),
}


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
    role: str,
    artifact_hash: str,
    byte_size: int,
    row_count: int,
    *,
    dataset_version: str = "1",
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
            (
                "019b8240-0000-7000-8000-000000000601"
                if role == "identity_assignment"
                else "019b8240-0000-7000-8000-000000000602"
            )
            if dataset_version == "1"
            else (
                "019b8240-0000-7000-8000-000000000801"
                if role == "identity_assignment"
                else "019b8240-0000-7000-8000-000000000802"
            )
        ),
        dataset_version=dataset_version,
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


def task3_manifest(
    role: str,
    artifact_hash: str,
    byte_size: int,
    row_count: int,
) -> DatasetManifestV2:
    """Bind one exact Task 3 role schema and boundary contract to fixture bytes."""
    role_index = tuple(TASK3_FIXTURE_FILES).index(role)
    schema = TASK3_SCHEMAS[role]
    effective_field, effective_shape = TASK3_EFFECTIVE_FIELDS[role]
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
        effective_time_field_id=effective_field,
        effective_shape=effective_shape,
        semantic_state_field_ids=TASK3_SEMANTIC_FIELDS[role],
        declared_channels=(PUBLIC,),
    )
    dataset_suffix = 700 + role_index
    return DatasetManifestV2(
        manifest_schema_version="2",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=UUID(f"019b8240-0000-7000-8000-{dataset_suffix:012d}"),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        dataset_role=DatasetRoleV1(namespace="drift", name=role, version="1"),
        created_at=NOW,
        source=SourceDescriptorV1(
            source_id="synthetic",
            publisher="Drift",
            product=f"M1b {role} fixture",
            evidence_reference=artifact(
                720 + role_index,
                "b" * 64,
                f"evidence/{role}-source.json",
            ),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="fixture",
            collector_version="1",
            evidence_reference=artifact(
                730 + role_index,
                "c" * 64,
                f"evidence/{role}-acquisition.json",
            ),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic",
            license_reference="synthetic-only",
            acquired_at=NOW,
            terms_evidence_reference=artifact(
                740 + role_index,
                "b" * 64,
                f"evidence/{role}-license.json",
            ),
        ),
        schema_definition=schema,
        partitions=(
            PartitionDescriptorV1(
                partition_id=UUID(f"019b8240-0000-7000-8000-{750 + role_index:012d}"),
                partition_key="all",
                artifact=ArtifactReference(
                    artifact_id=UUID(
                        f"019b8240-0000-7000-8000-{760 + role_index:012d}"
                    ),
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
            kind=TemporalContractKindV2.ASSERTION_TEMPORAL_V1,
            contract=contract,
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


def all_object_keys(value: object) -> set[str]:
    """Collect JSON object keys for explicit M1b capability-boundary checks."""
    if isinstance(value, dict):
        return set(value).union(*(all_object_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(all_object_keys(item) for item in value))
    return set()


@dataclass(frozen=True)
class CanonicalTask3Context:
    """Exact fixture records and validation evidence for bundle-v2 replay."""

    assignments: tuple[IdentityAssignmentVersionV1, ...]
    relationships: tuple[IdentityRelationshipVersionV1, ...]
    mappings: tuple[ExternalIdentifierMappingVersionV1, ...]
    classifications: tuple[SecurityClassificationVersionV1, ...]
    roles: tuple[ListingRoleVersionV1, ...]
    events: tuple[ListingLifecycleVersionV1, ...]
    terminations: tuple[ListingTerminationVersionV1, ...]
    coverage: tuple[ListingHistoryCoverageVersionV1, ...]
    assignment_manifest: DatasetManifestV2
    assignment_decision: DatasetValidationDecisionV2
    relationship_manifest: DatasetManifestV2
    relationship_decision: DatasetValidationDecisionV2
    manifests: dict[str, DatasetManifestV2]
    decisions: dict[str, DatasetValidationDecisionV2]
    bundle: ValidatedDatasetBundleV1
    policy: AvailabilityPolicyV1


def canonical_task3_context() -> CanonicalTask3Context:
    """Load and validate every exact member selected by canonical bundle v2."""
    assignment_bytes = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments-v2.json",
        ASSIGNMENTS_V2_HASH,
        ResolverLimits(max_bytes=200_000),
    )
    relationship_bytes = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships-v2.json",
        RELATIONSHIPS_V2_HASH,
        ResolverLimits(max_bytes=200_000),
    )
    assignment_manifest = identity_manifest(
        "identity_assignment",
        assignment_bytes.content_hash,
        assignment_bytes.byte_size,
        21,
        dataset_version="2",
    )
    relationship_manifest = identity_manifest(
        "identity_relationship",
        relationship_bytes.content_hash,
        relationship_bytes.byte_size,
        21,
        dataset_version="2",
    )
    assignment_decision = validate_identity_dataset(
        assignment_manifest, (assignment_bytes,), fixture_context(560)
    )
    relationship_decision = validate_identity_dataset(
        relationship_manifest, (relationship_bytes,), fixture_context(561)
    )
    manifests: dict[str, DatasetManifestV2] = {}
    decisions: dict[str, DatasetValidationDecisionV2] = {}
    documents: dict[str, dict[str, object]] = {}
    for index, role in enumerate(TASK3_FIXTURE_FILES):
        role_bytes = read_verified_local_artifact(
            FIXTURE_ROOT,
            TASK3_FIXTURE_FILES[role],
            TASK3_FIXTURE_HASHES[role],
            ResolverLimits(max_bytes=200_000),
        )
        role_manifest = task3_manifest(
            role,
            role_bytes.content_hash,
            role_bytes.byte_size,
            TASK3_FIXTURE_ROWS[role],
        )
        role_decision = validate_identity_dataset(
            role_manifest, (role_bytes,), fixture_context(570 + index)
        )
        assert role_decision.result is ValidationResult.PASS
        manifests[role] = role_manifest
        decisions[role] = role_decision
        document = json.loads(role_bytes.data)
        assert isinstance(document, dict)
        documents[role] = document
    bundle = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000550"),
        "2",
        NOW,
        (
            (assignment_manifest, assignment_decision),
            (relationship_manifest, relationship_decision),
            *((manifests[role], decisions[role]) for role in TASK3_FIXTURE_FILES),
        ),
    )

    def raw_records(role: str) -> list[object]:
        records = documents[role]["records"]
        assert isinstance(records, list)
        return records

    return CanonicalTask3Context(
        assignments=assignment_records_from(assignment_bytes),
        relationships=relationship_records_from(relationship_bytes),
        mappings=tuple(
            ExternalIdentifierMappingVersionV1.model_validate_json(
                canonical_json(record)
            )
            for record in raw_records("external_identifier_mapping")
        ),
        classifications=tuple(
            SecurityClassificationVersionV1.model_validate_json(canonical_json(record))
            for record in raw_records("security_classification")
        ),
        roles=tuple(
            ListingRoleVersionV1.model_validate_json(canonical_json(record))
            for record in raw_records("listing_role")
        ),
        events=tuple(
            ListingLifecycleVersionV1.model_validate_json(canonical_json(record))
            for record in raw_records("listing_lifecycle")
        ),
        terminations=tuple(
            ListingTerminationVersionV1.model_validate_json(canonical_json(record))
            for record in raw_records("listing_termination")
        ),
        coverage=tuple(
            ListingHistoryCoverageVersionV1.model_validate_json(canonical_json(record))
            for record in raw_records("listing_history_coverage")
        ),
        assignment_manifest=assignment_manifest,
        assignment_decision=assignment_decision,
        relationship_manifest=relationship_manifest,
        relationship_decision=relationship_decision,
        manifests=manifests,
        decisions=decisions,
        bundle=bundle,
        policy=AvailabilityPolicyV1(policy_id="strict"),
    )


def canonical_query(
    context: CanonicalTask3Context,
    role: str,
    purpose: M1bSelectionPurpose,
    subject: object,
    evaluation_time: datetime,
    *,
    knowledge_cutoff: datetime = NOW,
    mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> NormalizedSelectionQueryV1:
    """Bind one canonical K/E query to an exact bundle-v2 member."""
    if role == "identity_assignment":
        manifest = context.assignment_manifest
        decision = context.assignment_decision
    elif role == "identity_relationship":
        manifest = context.relationship_manifest
        decision = context.relationship_decision
    else:
        manifest = context.manifests[role]
        decision = context.decisions[role]
    return NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=purpose,
        information_role=(
            InformationRole.DECISION_INFORMATION
            if mode is ResolutionMode.AS_KNOWN
            else InformationRole.EX_POST_OUTCOME
        ),
        resolution_mode=mode,
        subject_hash=content_hash(subject),
        source_manifest_hash=decision.manifest_hash,
        validation_decision_hash=content_hash(decision),
        context_bundle_hashes=(content_hash(context.bundle),),
        dataset_role_hash=content_hash(manifest.dataset_role),
        record_contract_hash=content_hash(manifest.temporal_contract.contract),
        schema_hash=manifest.schema_definition.schema_hash,
        knowledge_cutoff=knowledge_cutoff,
        evaluation_time=evaluation_time,
        requested_channel=PUBLIC,
        policy_id=context.policy.policy_id,
        policy_hash=content_hash(context.policy),
    )


def canonical_relationship_evidence(
    context: CanonicalTask3Context,
    subject: IdentityReferenceV1,
    evaluation_time: datetime,
    *,
    knowledge_cutoff: datetime = NOW,
    mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> tuple[IdentityResolutionResultV1, CutoffSelectionProofV1]:
    """Replay one exact relationship outcome and its cutoff proof."""
    query = canonical_query(
        context,
        "identity_relationship",
        M1bSelectionPurpose.IDENTITY_RESOLUTION,
        subject,
        evaluation_time,
        knowledge_cutoff=knowledge_cutoff,
        mode=mode,
    )
    result = resolve_identity(
        subject,
        context.assignments,
        context.relationships,
        query,
        context.bundle,
        context.relationship_manifest,
        context.relationship_decision,
        context.policy,
        {},
        assignment_manifest=context.assignment_manifest,
        assignment_decision=context.assignment_decision,
    )
    selections = tuple(
        _select_identity_chain(
            tuple(
                AssertionVersionProjectionV1(
                    revision=record.revision,
                    record_hash=content_hash(record),
                )
                for record in chain
            ),
            query,
            context.policy,
            {},
        )
        for chain in _relationship_chains_for_subject(
            context.relationships, subject
        ).values()
    )
    proof = build_cutoff_selection_proof(
        query,
        selections,
        context.relationship_manifest,
        context.relationship_decision,
        (context.bundle,),
        "bf61c84a232e0d5c11a99b6451f9a43f37f96dab220c1c7036456252394c961d",
    )
    assert result.selection_proof_hashes == (content_hash(proof),)
    return result, proof


def test_hash_pinned_task3_role_fixtures_build_identity_bundle_v2() -> None:
    """Six exact role streams extend, but never rewrite, Task 2 bundle history."""
    task3_artifacts: dict[str, VerifiedArtifactBytes] = {}
    task3_manifests: dict[str, DatasetManifestV2] = {}
    task3_decisions: dict[str, DatasetValidationDecisionV2] = {}
    task3_documents: dict[str, dict[str, object]] = {}
    for index, role in enumerate(TASK3_FIXTURE_FILES):
        artifact_bytes = read_verified_local_artifact(
            FIXTURE_ROOT,
            TASK3_FIXTURE_FILES[role],
            TASK3_FIXTURE_HASHES[role],
            ResolverLimits(max_bytes=200_000),
        )
        manifest = task3_manifest(
            role,
            artifact_bytes.content_hash,
            artifact_bytes.byte_size,
            TASK3_FIXTURE_ROWS[role],
        )
        decision = validate_identity_dataset(
            manifest,
            (artifact_bytes,),
            fixture_context(520 + index),
        )
        assert decision.result is ValidationResult.PASS
        assert decision.validation_scope is ValidationScope.RECORDS
        assert decision.schema_hash == TASK3_SCHEMAS[role].schema_hash
        assert len(decision.validated_record_hashes) == TASK3_FIXTURE_ROWS[role]
        assert f"{role.replace('_', '-')}-v1" in decision.checked_contracts
        task3_artifacts[role] = artifact_bytes
        task3_manifests[role] = manifest
        task3_decisions[role] = decision
        document = json.loads(artifact_bytes.data)
        assert isinstance(document, dict)
        task3_documents[role] = document

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
        assignments_manifest,
        (assignments,),
        fixture_context(501),
    )
    relationships_decision = validate_identity_dataset(
        relationships_manifest,
        (relationships,),
        fixture_context(502),
    )
    assignments_v2 = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-assignments-v2.json",
        ASSIGNMENTS_V2_HASH,
        ResolverLimits(max_bytes=200_000),
    )
    relationships_v2 = read_verified_local_artifact(
        FIXTURE_ROOT,
        "identity-relationships-v2.json",
        RELATIONSHIPS_V2_HASH,
        ResolverLimits(max_bytes=200_000),
    )
    assignments_v2_manifest = identity_manifest(
        "identity_assignment",
        assignments_v2.content_hash,
        assignments_v2.byte_size,
        21,
        dataset_version="2",
    )
    relationships_v2_manifest = identity_manifest(
        "identity_relationship",
        relationships_v2.content_hash,
        relationships_v2.byte_size,
        21,
        dataset_version="2",
    )
    assignments_v2_decision = validate_identity_dataset(
        assignments_v2_manifest,
        (assignments_v2,),
        fixture_context(503),
    )
    relationships_v2_decision = validate_identity_dataset(
        relationships_v2_manifest,
        (relationships_v2,),
        fixture_context(504),
    )
    assert assignments_v2_decision.result is ValidationResult.PASS
    assert relationships_v2_decision.result is ValidationResult.PASS
    version_1 = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000501"),
        "1",
        NOW,
        (
            (assignments_manifest, assignments_decision),
            (relationships_manifest, relationships_decision),
        ),
    )
    version_2 = build_validated_dataset_bundle(
        UUID("019b8240-0000-7000-8000-000000000550"),
        "2",
        NOW,
        (
            (assignments_v2_manifest, assignments_v2_decision),
            (relationships_v2_manifest, relationships_v2_decision),
            *(
                (task3_manifests[role], task3_decisions[role])
                for role in TASK3_FIXTURE_FILES
            ),
        ),
    )
    assert content_hash(version_1) == EXPECTED_BUNDLE_HASH
    assert content_hash(version_2) == EXPECTED_BUNDLE_V2_HASH
    assert version_2.bundle_version == "2"
    assert tuple(member.dataset_role.name for member in version_2.members) == (
        "external_identifier_mapping",
        "identity_assignment",
        "identity_relationship",
        "listing_history_coverage",
        "listing_lifecycle",
        "listing_role",
        "listing_termination",
        "security_classification",
    )

    mappings = task3_documents["external_identifier_mapping"]["records"]
    assert isinstance(mappings, list)
    mapping_records = tuple(
        ExternalIdentifierMappingVersionV1.model_validate_json(canonical_json(record))
        for record in mappings
    )
    assert tuple(record.identifier_value for record in mapping_records) == (
        "OLD",
        "NEW",
        "NEW",
        "OLD",
    )
    assert len({record.target.internal_id for record in mapping_records}) == 3

    classifications = task3_documents["security_classification"]["records"]
    assert isinstance(classifications, list)
    classification_records = tuple(
        SecurityClassificationVersionV1.model_validate_json(canonical_json(record))
        for record in classifications
    )
    assert len({record.issuer_id for record in classification_records}) == 1
    assert len({record.security_id for record in classification_records}) == 2
    assert (
        len({record.share_class_label.value for record in classification_records}) == 2
    )

    roles = task3_documents["listing_role"]["records"]
    assert isinstance(roles, list)
    role_records = tuple(
        ListingRoleVersionV1.model_validate_json(canonical_json(record))
        for record in roles
    )
    assert len({record.listing_id for record in role_records}) >= 2
    assert len({record.methodology_id for record in role_records}) >= 2

    lifecycle = task3_documents["listing_lifecycle"]["records"]
    assert isinstance(lifecycle, list)
    lifecycle_records = tuple(
        ListingLifecycleVersionV1.model_validate_json(canonical_json(record))
        for record in lifecycle
    )
    assert any(
        record.event_kind is ListingLifecycleEventKind.VENUE_TRANSFER
        and record.related_listing_id is not None
        for record in lifecycle_records
    )
    assert (
        sum(
            record.event_kind is ListingLifecycleEventKind.FIRST_REGULAR_TRADE
            for record in lifecycle_records
        )
        >= 3
    )

    terminations = task3_documents["listing_termination"]["records"]
    assert isinstance(terminations, list)
    termination_records = tuple(
        ListingTerminationVersionV1.model_validate_json(canonical_json(record))
        for record in terminations
    )
    assert {record.reason for record in termination_records} == set(
        ListingTerminationReason
    )
    assert any(
        record.reason is ListingTerminationReason.UNKNOWN
        for record in termination_records
    )

    coverage = task3_documents["listing_history_coverage"]["records"]
    assert isinstance(coverage, list)
    coverage_records = tuple(
        ListingHistoryCoverageVersionV1.model_validate_json(canonical_json(record))
        for record in coverage
    )
    assert {record.coverage_status for record in coverage_records} == set(
        ListingHistoryCoverageStatus
    )
    assignment_v2_records = assignment_records_from(assignments_v2)
    relationship_v2_records = relationship_records_from(relationships_v2)
    assert {
        content_hash(record) for record in assignment_records_from(assignments)
    }.issubset({content_hash(record) for record in assignment_v2_records})
    assert {
        content_hash(record) for record in relationship_records_from(relationships)
    }.issubset({content_hash(record) for record in relationship_v2_records})
    validate_identity_bundle_references(
        assignment_v2_records,
        relationship_v2_records,
        mapping_records,
        classification_records,
        role_records,
        lifecycle_records,
        termination_records,
        coverage_records,
    )
    forbidden = {
        "price",
        "prices",
        "bar",
        "bars",
        "payout",
        "share_ratio",
        "cash",
        "return",
        "schedule",
    }
    assert not forbidden.intersection(
        set().union(
            *(all_object_keys(document) for document in task3_documents.values())
        )
    )


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


def test_canonical_bundle_v2_executes_complete_task3_resolution_flow() -> None:
    """The pinned v2 bundle must execute every Task 3 resolver as one context."""
    context = canonical_task3_context()
    validate_identity_bundle_references(
        context.assignments,
        context.relationships,
        context.mappings,
        context.classifications,
        context.roles,
        context.events,
        context.terminations,
        context.coverage,
    )
    listing_old = UUID("019b8240-0000-7000-8000-000000000005")
    issuer = UUID("019b8240-0000-7000-8000-000000000001")
    security = UUID("019b8240-0000-7000-8000-000000000002")
    history_time = datetime(2019, 2, 1, tzinfo=UTC)
    post_transfer_time = datetime(2022, 1, 4, tzinfo=UTC)
    old_namespace = next(
        record.namespace
        for record in context.mappings
        if record.identifier_value == "OLD" and record.target.internal_id == listing_old
    )
    mapping_query = canonical_query(
        context,
        "external_identifier_mapping",
        M1bSelectionPurpose.IDENTITY_RESOLUTION,
        {"namespace": old_namespace, "identifier_value": "OLD"},
        history_time,
    )
    mapping_result = resolve_external_identifier(
        old_namespace,
        "OLD",
        context.mappings,
        mapping_query,
        context.bundle,
        context.manifests["external_identifier_mapping"],
        context.decisions["external_identifier_mapping"],
        context.policy,
        {},
        assignments=context.assignments,
        assignment_manifest=context.assignment_manifest,
        assignment_decision=context.assignment_decision,
        lifecycle_events=context.events,
        lifecycle_manifest=context.manifests["listing_lifecycle"],
        lifecycle_decision=context.decisions["listing_lifecycle"],
        terminations=context.terminations,
        termination_manifest=context.manifests["listing_termination"],
        termination_decision=context.decisions["listing_termination"],
    )
    assert mapping_result.classification is RecordResolutionClassification.RESOLVED
    assert mapping_result.targets == (
        IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=listing_old),
    )
    assert mapping_result.target_lifecycle_proof_hashes

    issuer_ref = IdentityReferenceV1(kind=IdentityKind.ISSUER, internal_id=issuer)
    issuer_resolution, issuer_proof = canonical_relationship_evidence(
        context, issuer_ref, history_time
    )
    classification_query = canonical_query(
        context,
        "security_classification",
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        {"issuer_id": issuer, "security_id": security},
        history_time,
    )
    classification_result = resolve_security_classification(
        issuer,
        security,
        context.classifications,
        classification_query,
        context.bundle,
        context.manifests["security_classification"],
        context.decisions["security_classification"],
        context.policy,
        {},
        identity_assignments=context.assignments,
        assignment_manifest=context.assignment_manifest,
        assignment_decision=context.assignment_decision,
        identity_relationships=context.relationships,
        relationship_resolution=issuer_resolution,
        relationship_proof=issuer_proof,
        relationship_manifest=context.relationship_manifest,
        relationship_decision=context.relationship_decision,
    )
    assert (
        classification_result.classification is SecurityClassificationStatus.SUPPORTED
    )

    security_ref = IdentityReferenceV1(kind=IdentityKind.SECURITY, internal_id=security)
    security_resolution, security_proof = canonical_relationship_evidence(
        context, security_ref, history_time
    )
    primary_query = canonical_query(
        context,
        "listing_role",
        M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        {"security_id": security, "methodology_id": "synthetic-primary-v1"},
        history_time,
    )
    primary_result = resolve_primary_listing(
        security,
        "synthetic-primary-v1",
        context.roles,
        context.relationships,
        primary_query,
        context.bundle,
        context.manifests["listing_role"],
        context.decisions["listing_role"],
        context.policy,
        {},
        identity_assignments=context.assignments,
        assignment_manifest=context.assignment_manifest,
        assignment_decision=context.assignment_decision,
        relationship_resolution=security_resolution,
        relationship_proof=security_proof,
        relationship_manifest=context.relationship_manifest,
        relationship_decision=context.relationship_decision,
    )
    assert primary_result.listing_id == listing_old

    coverage_query = canonical_query(
        context,
        "listing_history_coverage",
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        {"listing_id": listing_old},
        post_transfer_time,
    )
    coverage_result = resolve_listing_history_coverage(
        listing_old,
        context.coverage,
        coverage_query,
        context.bundle,
        context.manifests["listing_history_coverage"],
        context.decisions["listing_history_coverage"],
        context.policy,
        {},
    )
    termination_query = canonical_query(
        context,
        "listing_termination",
        M1bSelectionPurpose.LISTING_TERMINATION,
        {"listing_id": listing_old},
        post_transfer_time,
    )
    termination_result = resolve_listing_termination(
        listing_old,
        context.terminations,
        coverage_result,
        termination_query,
        context.bundle,
        context.manifests["listing_termination"],
        context.decisions["listing_termination"],
        context.policy,
        {},
        coverage_versions=context.coverage,
        coverage_manifest=context.manifests["listing_history_coverage"],
        coverage_decision=context.decisions["listing_history_coverage"],
    )
    assert termination_result.status is ListingTerminationStatus.TERMINATED

    transfer_resolution, transfer_proof = canonical_relationship_evidence(
        context, security_ref, post_transfer_time
    )
    lifecycle_query = canonical_query(
        context,
        "listing_lifecycle",
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        {"listing_id": listing_old},
        post_transfer_time,
    )
    lifecycle_result = resolve_listing_lifecycle(
        listing_old,
        context.events,
        termination_result,
        lifecycle_query,
        context.bundle,
        context.manifests["listing_lifecycle"],
        context.decisions["listing_lifecycle"],
        context.policy,
        {},
        terminations=context.terminations,
        termination_manifest=context.manifests["listing_termination"],
        termination_decision=context.decisions["listing_termination"],
        coverage=coverage_result,
        coverage_versions=context.coverage,
        coverage_manifest=context.manifests["listing_history_coverage"],
        coverage_decision=context.decisions["listing_history_coverage"],
        identity_relationships=context.relationships,
        relationship_resolution=transfer_resolution,
        relationship_proof=transfer_proof,
        relationship_manifest=context.relationship_manifest,
        relationship_decision=context.relationship_decision,
        identity_assignments=context.assignments,
        assignment_manifest=context.assignment_manifest,
        assignment_decision=context.assignment_decision,
    )
    assert lifecycle_result.status is ListingLifecycleStatus.TERMINATED
    assert lifecycle_result.selected_transfer_relationship_record_hashes


def test_canonical_corrections_replay_as_known_and_current_by_stage() -> None:
    """Coverage, termination, and lifecycle retain executable correction history."""
    context = canonical_task3_context()
    listing_id = UUID("019b8240-0000-7000-8000-000000000005")
    pre_correction_cutoff = datetime(2024, 12, 31, tzinfo=UTC)
    terminated_at = datetime(2022, 1, 4, tzinfo=UTC)

    def coverage_for(
        mode: ResolutionMode, evaluation_time: datetime
    ) -> ListingHistoryCoverageResolutionV1:
        return resolve_listing_history_coverage(
            listing_id,
            context.coverage,
            canonical_query(
                context,
                "listing_history_coverage",
                M1bSelectionPurpose.LISTING_LIFECYCLE,
                {"listing_id": listing_id},
                evaluation_time,
                knowledge_cutoff=pre_correction_cutoff,
                mode=mode,
            ),
            context.bundle,
            context.manifests["listing_history_coverage"],
            context.decisions["listing_history_coverage"],
            context.policy,
            {},
        )

    as_known_coverage = coverage_for(ResolutionMode.AS_KNOWN, terminated_at)
    current_coverage = coverage_for(
        ResolutionMode.CURRENT_INTERPRETATION, terminated_at
    )
    assert as_known_coverage.complete_through.lower_bound == datetime(
        2026, 12, 31, tzinfo=UTC
    )
    assert current_coverage.complete_through.lower_bound == datetime(
        2027, 12, 31, tzinfo=UTC
    )

    def termination_for(
        mode: ResolutionMode,
        coverage: ListingHistoryCoverageResolutionV1,
        evaluation_time: datetime,
    ) -> ListingTerminationResolutionV1:
        return resolve_listing_termination(
            listing_id,
            context.terminations,
            coverage,
            canonical_query(
                context,
                "listing_termination",
                M1bSelectionPurpose.LISTING_TERMINATION,
                {"listing_id": listing_id},
                evaluation_time,
                knowledge_cutoff=pre_correction_cutoff,
                mode=mode,
            ),
            context.bundle,
            context.manifests["listing_termination"],
            context.decisions["listing_termination"],
            context.policy,
            {},
            coverage_versions=context.coverage,
            coverage_manifest=context.manifests["listing_history_coverage"],
            coverage_decision=context.decisions["listing_history_coverage"],
        )

    as_known_termination = termination_for(
        ResolutionMode.AS_KNOWN, as_known_coverage, terminated_at
    )
    current_termination = termination_for(
        ResolutionMode.CURRENT_INTERPRETATION, current_coverage, terminated_at
    )
    assert as_known_termination.selected_termination_version_id == UUID(
        "019b8240-0000-7000-8000-000000002550"
    )
    assert current_termination.selected_termination_version_id == UUID(
        "019b8240-0000-7000-8000-000000002551"
    )

    lifecycle_time = datetime(2020, 3, 15, 20, tzinfo=UTC)
    as_known_lifecycle_coverage = coverage_for(ResolutionMode.AS_KNOWN, lifecycle_time)
    current_lifecycle_coverage = coverage_for(
        ResolutionMode.CURRENT_INTERPRETATION, lifecycle_time
    )
    as_known_pretermination = termination_for(
        ResolutionMode.AS_KNOWN,
        as_known_lifecycle_coverage,
        lifecycle_time,
    )
    current_pretermination = termination_for(
        ResolutionMode.CURRENT_INTERPRETATION,
        current_lifecycle_coverage,
        lifecycle_time,
    )

    def lifecycle_for(
        mode: ResolutionMode,
        coverage: ListingHistoryCoverageResolutionV1,
        termination: ListingTerminationResolutionV1,
    ) -> ListingLifecycleResolutionV1:
        return resolve_listing_lifecycle(
            listing_id,
            context.events,
            termination,
            canonical_query(
                context,
                "listing_lifecycle",
                M1bSelectionPurpose.LISTING_LIFECYCLE,
                {"listing_id": listing_id},
                lifecycle_time,
                knowledge_cutoff=pre_correction_cutoff,
                mode=mode,
            ),
            context.bundle,
            context.manifests["listing_lifecycle"],
            context.decisions["listing_lifecycle"],
            context.policy,
            {},
            terminations=context.terminations,
            termination_manifest=context.manifests["listing_termination"],
            termination_decision=context.decisions["listing_termination"],
            coverage=coverage,
            coverage_versions=context.coverage,
            coverage_manifest=context.manifests["listing_history_coverage"],
            coverage_decision=context.decisions["listing_history_coverage"],
        )

    as_known_lifecycle = lifecycle_for(
        ResolutionMode.AS_KNOWN,
        as_known_lifecycle_coverage,
        as_known_pretermination,
    )
    current_lifecycle = lifecycle_for(
        ResolutionMode.CURRENT_INTERPRETATION,
        current_lifecycle_coverage,
        current_pretermination,
    )
    assert as_known_lifecycle.status is ListingLifecycleStatus.ACTIVE
    assert current_lifecycle.status is ListingLifecycleStatus.SUSPENDED


@pytest.mark.parametrize("mutation", ("missing", "mistyped", "inactive", "interval"))
def test_canonical_bundle_rejects_invalid_cross_role_references(mutation: str) -> None:
    """Canonical v2 cannot admit a broken typed or temporal listing reference."""
    context = canonical_task3_context()
    listing_id = UUID("019b8240-0000-7000-8000-000000000008")
    listing_ref = IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=listing_id)
    assignments = list(context.assignments)
    mappings = list(context.mappings)
    if mutation == "missing":
        assignments = [
            record
            for record in assignments
            if record.identity.model_dump(mode="python").get("listing_id") != listing_id
        ]
    elif mutation == "mistyped":
        mapping_index = next(
            index
            for index, record in enumerate(mappings)
            if record.target == listing_ref
        )
        mappings[mapping_index] = mappings[mapping_index].model_copy(
            update={
                "target": IdentityReferenceV1(
                    kind=IdentityKind.LISTING,
                    internal_id=UUID("019b8240-0000-7000-8000-000000000007"),
                )
            }
        )
    else:
        assignment_index = next(
            index
            for index, record in enumerate(assignments)
            if record.identity.model_dump(mode="python").get("listing_id") == listing_id
        )
        if mutation == "inactive":
            assignments[assignment_index] = assignments[assignment_index].model_copy(
                update={"assignment_effect": IdentityAssignmentEffect.UNASSIGNED}
            )
        else:
            assignment = assignments[assignment_index]
            assignments[assignment_index] = assignment.model_copy(
                update={
                    "effective_interval": assignment.effective_interval.model_copy(
                        update={
                            "start": context.mappings[
                                -1
                            ].effective_interval.start.model_copy(
                                update={
                                    "lower_bound": datetime(2025, 1, 1, tzinfo=UTC),
                                    "upper_bound": datetime(2025, 1, 1, tzinfo=UTC),
                                    "source_time_label": "2025-01-01T00:00:00Z",
                                }
                            )
                        }
                    )
                }
            )

    with pytest.raises(DatasetValidationError, match="mapping_target_reference"):
        validate_identity_bundle_references(
            tuple(assignments),
            context.relationships,
            tuple(mappings),
            context.classifications,
            context.roles,
            context.events,
            context.terminations,
            context.coverage,
        )
