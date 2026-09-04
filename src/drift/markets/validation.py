"""Exact-byte validation for immutable M1b identity assertion datasets."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from pydantic import ValidationError

from drift.datasets.assertions import (
    validate_assertion_chain,
    validate_manifest_v2_structure,
)
from drift.datasets.hashing import assertion_version_payload, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.assertions import (
    AssertionVersionProjectionV1,
    TemporalBoundaryClaimV1,
    TemporalIntervalClaimV1,
)
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.manifests import (
    AssertionEffectiveShape,
    AssertionTemporalContractV1,
    DatasetManifestV2,
    FieldDescriptorV1,
    LogicalType,
    SchemaDescriptorV1,
)
from drift.domain.revisions import RevisionKind
from drift.domain.securities import (
    ExternalIdentifierMappingVersionV1,
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
    IdentityKind,
    IdentityReferenceV1,
    IdentityRelationshipKind,
    IdentityRelationshipVersionV1,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingRole,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
    MappingStatus,
    ResolutionStatus,
    SecurityClassificationVersionV1,
    identity_reference,
)
from drift.domain.universes import (
    SourceUniverseDefinitionVersionV1,
    UniverseMembershipVersionV1,
)
from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import canonical_json, content_hash

_ASSIGNMENT_ROLE = "identity_assignment"
_RELATIONSHIP_ROLE = "identity_relationship"
_MAPPING_ROLE = "external_identifier_mapping"
_CLASSIFICATION_ROLE = "security_classification"
_LISTING_ROLE = "listing_role"
_LIFECYCLE_ROLE = "listing_lifecycle"
_TERMINATION_ROLE = "listing_termination"
_COVERAGE_ROLE = "listing_history_coverage"
_SOURCE_UNIVERSE_ROLE = "source_universe_definition"
_MEMBERSHIP_ROLE = "universe_membership"

_IDENTITY_BASE_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
}

_EXACT_ASSERTION_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "schema_version": (LogicalType.STRING, False),
    "revision.logical_record_id": (LogicalType.STRING, False),
    "revision.record_version_id": (LogicalType.STRING, False),
    "revision.revision_kind": (LogicalType.STRING, False),
    "revision.supersedes_record_version_id": (LogicalType.STRING, True),
    "revision.source_sequence": (LogicalType.INTEGER, False),
    "revision.availability": (LogicalType.JSON, False),
    "revision.history_completeness": (LogicalType.STRING, False),
    "revision.source_native_revision_label": (LogicalType.STRING, True),
    "revision.source_artifact": (LogicalType.JSON, False),
    "revision.payload_hash": (LogicalType.STRING, False),
}

_SECURITY_CLASSIFICATION_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "issuer_id": (LogicalType.STRING, False),
    "security_id": (LogicalType.STRING, False),
    "issuer_form": (LogicalType.STRING, False),
    "issuer_domicile": (LogicalType.JSON, False),
    "incorporation_country": (LogicalType.JSON, False),
    "instrument_form": (LogicalType.STRING, False),
    "share_class_label": (LogicalType.JSON, False),
    "domestic_status": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
    "source_taxonomy_id": (LogicalType.STRING, False),
    "source_taxonomy_version": (LogicalType.STRING, False),
    "source_fields": (LogicalType.JSON, False),
}

_EXTERNAL_IDENTIFIER_MAPPING_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "namespace": (LogicalType.JSON, False),
    "identifier_value": (LogicalType.STRING, False),
    "target": (LogicalType.JSON, False),
    "mapping_status": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
}

_LISTING_ROLE_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "security_id": (LogicalType.STRING, False),
    "listing_id": (LogicalType.STRING, False),
    "role": (LogicalType.STRING, False),
    "methodology_id": (LogicalType.STRING, False),
    "methodology_version": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
}

_LISTING_LIFECYCLE_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "listing_id": (LogicalType.STRING, False),
    "event_kind": (LogicalType.STRING, False),
    "effective_time": (LogicalType.JSON, False),
    "related_listing_id": (LogicalType.STRING, True),
}

_LISTING_TERMINATION_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "listing_id": (LogicalType.STRING, False),
    "reason": (LogicalType.STRING, False),
    "source_reason_code": (LogicalType.STRING, True),
    "source_reason_text": (LogicalType.STRING, True),
    "last_regular_trade_time": (LogicalType.JSON, False),
    "effective_time": (LogicalType.JSON, False),
    "successor_relationship_ids": (LogicalType.JSON, False),
    "outcome_evidence_status": (LogicalType.STRING, False),
}

_LISTING_HISTORY_COVERAGE_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    **_EXACT_ASSERTION_FIELDS,
    "listing_id": (LogicalType.STRING, False),
    "coverage_status": (LogicalType.STRING, False),
    "complete_through": (LogicalType.JSON, False),
}

_SECURITY_CLASSIFICATION_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _SECURITY_CLASSIFICATION_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "effective_interval"
    )
)
_EXTERNAL_IDENTIFIER_MAPPING_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _EXTERNAL_IDENTIFIER_MAPPING_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "effective_interval"
    )
)
_LISTING_ROLE_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _LISTING_ROLE_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "effective_interval"
    )
)
_LISTING_LIFECYCLE_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _LISTING_LIFECYCLE_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "effective_time"
    )
)
_LISTING_TERMINATION_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _LISTING_TERMINATION_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "effective_time"
    )
)
_LISTING_HISTORY_COVERAGE_SEMANTIC_FIELDS = tuple(
    sorted(
        field_id
        for field_id in _LISTING_HISTORY_COVERAGE_FIELDS
        if field_id not in _EXACT_ASSERTION_FIELDS and field_id != "complete_through"
    )
)


def _exact_schema(
    expected: Mapping[str, tuple[LogicalType, bool]],
) -> SchemaDescriptorV1:
    fields = tuple(
        FieldDescriptorV1(
            field_id=field_id,
            name=field_id,
            logical_type=logical_type,
            nullable=nullable,
        )
        for field_id, (logical_type, nullable) in expected.items()
    )
    ordered = tuple(sorted(fields, key=lambda item: item.field_id))
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash="0" * 64
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )


EXTERNAL_IDENTIFIER_MAPPING_SCHEMA_V1 = _exact_schema(
    _EXTERNAL_IDENTIFIER_MAPPING_FIELDS
)
SECURITY_CLASSIFICATION_SCHEMA_V1 = _exact_schema(_SECURITY_CLASSIFICATION_FIELDS)
LISTING_ROLE_SCHEMA_V1 = _exact_schema(_LISTING_ROLE_FIELDS)
LISTING_LIFECYCLE_SCHEMA_V1 = _exact_schema(_LISTING_LIFECYCLE_FIELDS)
LISTING_TERMINATION_SCHEMA_V1 = _exact_schema(_LISTING_TERMINATION_FIELDS)
LISTING_HISTORY_COVERAGE_SCHEMA_V1 = _exact_schema(_LISTING_HISTORY_COVERAGE_FIELDS)

_SOURCE_UNIVERSE_FIELDS = {
    **_EXACT_ASSERTION_FIELDS,
    "universe_id": (LogicalType.STRING, False),
    "universe_version": (LogicalType.STRING, False),
    "universe_kind": (LogicalType.STRING, False),
    "target_level": (LogicalType.STRING, False),
    "methodology_reference": (LogicalType.JSON, False),
    "methodology_hash": (LogicalType.STRING, False),
    "identity_bundle_hash": (LogicalType.STRING, False),
    "effective_interval": (LogicalType.JSON, False),
}
_MEMBERSHIP_FIELDS = {
    **_EXACT_ASSERTION_FIELDS,
    "universe_id": (LogicalType.STRING, False),
    "universe_version": (LogicalType.STRING, False),
    "target_level": (LogicalType.STRING, False),
    "target_id": (LogicalType.STRING, False),
    "membership_effect": (LogicalType.STRING, False),
    "effective_time": (LogicalType.JSON, False),
    "source_event_id": (LogicalType.STRING, False),
}
SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1 = _exact_schema(_SOURCE_UNIVERSE_FIELDS)
UNIVERSE_MEMBERSHIP_SCHEMA_V1 = _exact_schema(_MEMBERSHIP_FIELDS)

_EXACT_ROLE_CONTRACTS: dict[
    str,
    tuple[
        SchemaDescriptorV1,
        tuple[str, ...],
        str,
        AssertionEffectiveShape,
    ],
] = {
    _SOURCE_UNIVERSE_ROLE: (
        SOURCE_UNIVERSE_DEFINITION_SCHEMA_V1,
        tuple(
            sorted(
                field
                for field in _SOURCE_UNIVERSE_FIELDS
                if field not in _EXACT_ASSERTION_FIELDS
                and field != "effective_interval"
            )
        ),
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    _MEMBERSHIP_ROLE: (
        UNIVERSE_MEMBERSHIP_SCHEMA_V1,
        tuple(
            sorted(
                field
                for field in _MEMBERSHIP_FIELDS
                if field not in _EXACT_ASSERTION_FIELDS and field != "effective_time"
            )
        ),
        "effective_time",
        AssertionEffectiveShape.BOUNDARY,
    ),
    _MAPPING_ROLE: (
        EXTERNAL_IDENTIFIER_MAPPING_SCHEMA_V1,
        _EXTERNAL_IDENTIFIER_MAPPING_SEMANTIC_FIELDS,
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    _CLASSIFICATION_ROLE: (
        SECURITY_CLASSIFICATION_SCHEMA_V1,
        _SECURITY_CLASSIFICATION_SEMANTIC_FIELDS,
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    _LISTING_ROLE: (
        LISTING_ROLE_SCHEMA_V1,
        _LISTING_ROLE_SEMANTIC_FIELDS,
        "effective_interval",
        AssertionEffectiveShape.INTERVAL,
    ),
    _LIFECYCLE_ROLE: (
        LISTING_LIFECYCLE_SCHEMA_V1,
        _LISTING_LIFECYCLE_SEMANTIC_FIELDS,
        "effective_time",
        AssertionEffectiveShape.BOUNDARY,
    ),
    _TERMINATION_ROLE: (
        LISTING_TERMINATION_SCHEMA_V1,
        _LISTING_TERMINATION_SEMANTIC_FIELDS,
        "effective_time",
        AssertionEffectiveShape.BOUNDARY,
    ),
    _COVERAGE_ROLE: (
        LISTING_HISTORY_COVERAGE_SCHEMA_V1,
        _LISTING_HISTORY_COVERAGE_SEMANTIC_FIELDS,
        "complete_through",
        AssertionEffectiveShape.BOUNDARY,
    ),
}


def is_exact_typed_role_manifest(manifest: DatasetManifestV2) -> bool:
    """Return whether a Task 3 role manifest has its exact typed contract."""
    expected = _EXACT_ROLE_CONTRACTS.get(manifest.dataset_role.name)
    if expected is None:
        return False
    schema, semantic_fields, effective_field, effective_shape = expected
    return bool(
        manifest.schema_definition == schema
        and _has_exact_role_contract(
            manifest,
            semantic_fields,
            effective_field,
            effective_shape,
        )
    )


def is_exact_identity_role_manifest(manifest: DatasetManifestV2) -> bool:
    """Return whether a Task 2 assignment or relationship manifest is exact."""
    role = manifest.dataset_role.name
    semantic_fields: tuple[str, ...]
    if role == _ASSIGNMENT_ROLE:
        expected_fields = {
            **_IDENTITY_BASE_FIELDS,
            "assignment_effect": (LogicalType.STRING, False),
        }
        semantic_fields = ("assignment_effect",)
    elif role == _RELATIONSHIP_ROLE:
        expected_fields = {
            **_IDENTITY_BASE_FIELDS,
            "relationship_kind": (LogicalType.STRING, False),
            "resolution_status": (LogicalType.STRING, False),
        }
        semantic_fields = ("relationship_kind", "resolution_status")
    else:
        return False
    return bool(
        _has_exact_identity_schema(manifest.schema_definition.fields, expected_fields)
        and _has_exact_role_contract(
            manifest,
            semantic_fields,
            "effective_interval",
            AssertionEffectiveShape.INTERVAL,
        )
    )


def validate_identity_dataset(
    manifest: DatasetManifestV2,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV2:
    """Validate one role-specific identity dataset and every parsed assertion."""
    structure = validate_manifest_v2_structure(manifest, verified_artifacts, context)
    findings = list(structure.findings)
    records: list[
        IdentityAssignmentVersionV1
        | IdentityRelationshipVersionV1
        | ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
        | SourceUniverseDefinitionVersionV1
        | UniverseMembershipVersionV1
    ] = []
    role = manifest.dataset_role.name
    if role not in {
        _ASSIGNMENT_ROLE,
        _RELATIONSHIP_ROLE,
        _MAPPING_ROLE,
        _CLASSIFICATION_ROLE,
        _LISTING_ROLE,
        _LIFECYCLE_ROLE,
        _TERMINATION_ROLE,
        _COVERAGE_ROLE,
        _SOURCE_UNIVERSE_ROLE,
        _MEMBERSHIP_ROLE,
    }:
        findings.append(_finding("unsupported_identity_dataset_role"))
    else:
        for artifact in verified_artifacts:
            parsed, parse_findings = _parse_identity_records(artifact, role)
            records.extend(parsed)
            findings.extend(parse_findings)

    record_hashes = tuple(sorted({content_hash(record) for record in records}))
    if len(record_hashes) != len(records):
        findings.append(_finding("duplicate_identity_record_hash"))
    if len(records) != sum(partition.row_count for partition in manifest.partitions):
        findings.append(_finding("identity_record_count_mismatch"))
    expected_fields = dict(_IDENTITY_BASE_FIELDS)
    exact_schema: SchemaDescriptorV1 | None = None
    if role == _ASSIGNMENT_ROLE:
        expected_fields["assignment_effect"] = (LogicalType.STRING, False)
    elif role == _RELATIONSHIP_ROLE:
        expected_fields.update(
            {
                "relationship_kind": (LogicalType.STRING, False),
                "resolution_status": (LogicalType.STRING, False),
            }
        )
    elif role in _EXACT_ROLE_CONTRACTS:
        exact_schema = _EXACT_ROLE_CONTRACTS[role][0]
    schema_matches = (
        manifest.schema_definition == exact_schema
        if exact_schema is not None
        else _has_exact_identity_schema(
            manifest.schema_definition.fields, expected_fields
        )
    )
    if not schema_matches:
        findings.append(_finding("identity_role_schema_mismatch"))
    exact_role = _EXACT_ROLE_CONTRACTS.get(role)
    if exact_role is not None and not _has_exact_role_contract(
        manifest,
        exact_role[1],
        exact_role[2],
        exact_role[3],
    ):
        findings.append(_finding("identity_role_contract_mismatch"))
    declared_channels = set(manifest.temporal_contract.contract.declared_channels)
    checked_chains = set()
    for record in records:
        if any(
            item.channel not in declared_channels
            for item in record.revision.availability
        ):
            findings.append(_finding("identity_undeclared_availability_channel"))
        logical_record_id = record.revision.logical_record_id
        if logical_record_id not in checked_chains:
            checked_chains.add(logical_record_id)
            findings.extend(
                validate_assertion_chain(
                    tuple(
                        AssertionVersionProjectionV1(
                            revision=item.revision, record_hash=content_hash(item)
                        )
                        for item in records
                        if item.revision.logical_record_id == logical_record_id
                    )
                )
            )

    findings.extend(
        _universe_ownership_findings(
            tuple(
                record
                for record in records
                if isinstance(
                    record,
                    SourceUniverseDefinitionVersionV1 | UniverseMembershipVersionV1,
                )
            )
        )
    )
    canonical_findings = _canonical_findings(findings)
    return structure.model_copy(
        update={
            "validation_scope": (
                ValidationScope.RECORDS
                if record_hashes
                else ValidationScope.MANIFEST_ONLY
            ),
            "result": (
                ValidationResult.FAIL
                if any(
                    finding.severity is FindingSeverity.ERROR
                    for finding in canonical_findings
                )
                else ValidationResult.PASS
            ),
            "validated_record_hashes": record_hashes,
            "checked_contracts": tuple(
                sorted((*structure.checked_contracts, f"{role.replace('_', '-')}-v1"))
            ),
            "findings": canonical_findings,
        }
    )


def _has_exact_identity_schema(
    fields: Sequence[FieldDescriptorV1],
    expected: Mapping[str, tuple[LogicalType, bool]],
) -> bool:
    """Require exact identity field IDs, logical types, and nullability."""
    if len(fields) != len(expected):
        return False
    return all(
        field.field_id in expected
        and field.name == field.field_id
        and field.logical_type is expected[field.field_id][0]
        and field.nullable is expected[field.field_id][1]
        and field.unit is None
        for field in fields
    )


def _has_exact_role_contract(
    manifest: DatasetManifestV2,
    semantic_fields: tuple[str, ...],
    effective_field: str,
    effective_shape: AssertionEffectiveShape,
) -> bool:
    contract = manifest.temporal_contract.contract
    return bool(
        isinstance(contract, AssertionTemporalContractV1)
        and contract.contract_version == "1"
        and contract.logical_record_id_field_id == "revision.logical_record_id"
        and contract.record_version_id_field_id == "revision.record_version_id"
        and contract.revision_kind_field_id == "revision.revision_kind"
        and contract.supersedes_field_id == "revision.supersedes_record_version_id"
        and contract.source_sequence_field_id == "revision.source_sequence"
        and contract.availability_field_id == "revision.availability"
        and contract.source_artifact_field_id == "revision.source_artifact"
        and contract.payload_hash_field_id == "revision.payload_hash"
        and contract.effective_time_field_id == effective_field
        and contract.effective_shape is effective_shape
        and contract.semantic_state_field_ids == semantic_fields
    )


def _parse_identity_records(
    artifact: VerifiedArtifactBytes,
    role: str,
) -> tuple[
    tuple[
        IdentityAssignmentVersionV1
        | IdentityRelationshipVersionV1
        | ExternalIdentifierMappingVersionV1
        | SecurityClassificationVersionV1
        | ListingRoleVersionV1
        | ListingLifecycleVersionV1
        | ListingTerminationVersionV1
        | ListingHistoryCoverageVersionV1
        | SourceUniverseDefinitionVersionV1
        | UniverseMembershipVersionV1,
        ...,
    ],
    tuple[ValidationFindingV1, ...],
]:
    if role == _ASSIGNMENT_ROLE:
        return _parse_identity_assignment_document(artifact)
    if role == _RELATIONSHIP_ROLE:
        return _parse_identity_relationship_document(artifact)
    if role == _MAPPING_ROLE:
        return _parse_external_identifier_mapping_document(artifact)
    if role == _CLASSIFICATION_ROLE:
        return _parse_security_classification_document(artifact)
    if role == _LISTING_ROLE:
        return _parse_listing_role_document(artifact)
    if role == _LIFECYCLE_ROLE:
        return _parse_listing_lifecycle_document(artifact)
    if role == _TERMINATION_ROLE:
        return _parse_listing_termination_document(artifact)
    if role == _SOURCE_UNIVERSE_ROLE:
        return _parse_typed_identity_document(
            artifact, SourceUniverseDefinitionVersionV1
        )
    if role == _MEMBERSHIP_ROLE:
        return _parse_typed_identity_document(artifact, UniverseMembershipVersionV1)
    return _parse_listing_history_coverage_document(artifact)


def _parse_identity_assignment_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[tuple[IdentityAssignmentVersionV1, ...], tuple[ValidationFindingV1, ...]]:
    return _parse_typed_identity_document(artifact, IdentityAssignmentVersionV1)


def _parse_identity_relationship_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[tuple[IdentityRelationshipVersionV1, ...], tuple[ValidationFindingV1, ...]]:
    return _parse_typed_identity_document(artifact, IdentityRelationshipVersionV1)


def _parse_external_identifier_mapping_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[
    tuple[ExternalIdentifierMappingVersionV1, ...],
    tuple[ValidationFindingV1, ...],
]:
    return _parse_typed_identity_document(artifact, ExternalIdentifierMappingVersionV1)


def _parse_security_classification_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[
    tuple[SecurityClassificationVersionV1, ...], tuple[ValidationFindingV1, ...]
]:
    return _parse_typed_identity_document(artifact, SecurityClassificationVersionV1)


def _parse_listing_role_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[tuple[ListingRoleVersionV1, ...], tuple[ValidationFindingV1, ...]]:
    return _parse_typed_identity_document(artifact, ListingRoleVersionV1)


def _parse_listing_lifecycle_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[tuple[ListingLifecycleVersionV1, ...], tuple[ValidationFindingV1, ...]]:
    return _parse_typed_identity_document(artifact, ListingLifecycleVersionV1)


def _parse_listing_termination_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[tuple[ListingTerminationVersionV1, ...], tuple[ValidationFindingV1, ...]]:
    return _parse_typed_identity_document(artifact, ListingTerminationVersionV1)


def _parse_listing_history_coverage_document(
    artifact: VerifiedArtifactBytes,
) -> tuple[
    tuple[ListingHistoryCoverageVersionV1, ...], tuple[ValidationFindingV1, ...]
]:
    return _parse_typed_identity_document(artifact, ListingHistoryCoverageVersionV1)


def _parse_typed_identity_document[
    T: IdentityAssignmentVersionV1
    | IdentityRelationshipVersionV1
    | ExternalIdentifierMappingVersionV1
    | SecurityClassificationVersionV1
    | ListingRoleVersionV1
    | ListingLifecycleVersionV1
    | ListingTerminationVersionV1
    | ListingHistoryCoverageVersionV1
    | SourceUniverseDefinitionVersionV1
    | UniverseMembershipVersionV1
](
    artifact: VerifiedArtifactBytes,
    model: type[T],
) -> tuple[tuple[T, ...], tuple[ValidationFindingV1, ...]]:
    """Parse one role document only through its exact immutable record model."""
    try:
        document = json.loads(artifact.data)
    except UnicodeDecodeError, json.JSONDecodeError:
        return (), (_finding("identity_dataset_invalid_json"),)
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != "1"
        or not isinstance(document.get("records"), list)
        or set(document) != {"schema_version", "records"}
    ):
        return (), (_finding("identity_dataset_invalid_envelope"),)

    records: list[T] = []
    findings: list[ValidationFindingV1] = []
    for raw_record in document["records"]:
        try:
            record = cast(T, model.model_validate_json(canonical_json(raw_record)))
        except CanonicalSerializationError, TypeError, ValidationError:
            findings.append(_finding("identity_record_invalid"))
            continue
        expected_payload_hash = content_hash(assertion_version_payload(record))
        if record.revision.payload_hash != expected_payload_hash:
            findings.append(_finding("identity_payload_hash_mismatch"))
            continue
        records.append(record)
    return tuple(records), tuple(findings)


def _universe_ownership_findings(
    records: Sequence[SourceUniverseDefinitionVersionV1 | UniverseMembershipVersionV1],
) -> tuple[ValidationFindingV1, ...]:
    owners: dict[object, tuple[object, ...]] = {}
    levels: dict[tuple[object, str], object] = {}
    events: dict[tuple[object, ...], object] = {}
    codes: set[str] = set()
    for record in records:
        universe = (record.universe_id, record.universe_version)
        owner: tuple[object, ...] = (*universe, record.target_level)
        if isinstance(record, UniverseMembershipVersionV1):
            owner += (record.target_id, record.source_event_id)
            if owner in events and events[owner] != record.revision.logical_record_id:
                codes.add("duplicate_membership_source_event")
            events[owner] = record.revision.logical_record_id
        else:
            owner += (record.universe_kind,)
        logical = record.revision.logical_record_id
        if logical in owners and owners[logical] != owner:
            codes.add("universe_revision_owner_changed")
        owners[logical] = owner
        if universe in levels and levels[universe] != record.target_level:
            codes.add("universe_version_target_level_changed")
        levels[universe] = record.target_level
    return tuple(_finding(code) for code in sorted(codes))


def _finding(code: str) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
    )


def _canonical_findings(
    findings: Sequence[ValidationFindingV1],
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.code,
                item.severity.value,
                item.message,
                tuple(reference.content_hash for reference in item.artifact_references),
            ),
        )
    )


def validate_external_identifier_mappings(
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    *,
    target_intervals: Mapping[IdentityReferenceV1, Sequence[TemporalIntervalClaimV1]],
) -> None:
    """Reject possible collisions and mappings outside retained target intervals."""
    findings: list[str] = []
    by_collision: dict[
        tuple[object, str], list[ExternalIdentifierMappingVersionV1]
    ] = {}
    for mapping in mappings:
        collision = (mapping.namespace, mapping.identifier_value)
        by_collision.setdefault(collision, []).append(mapping)
        target_interval_options = target_intervals.get(mapping.target, ())
        if not target_interval_options:
            findings.append("mapping_target_interval_missing")
        elif not any(
            _interval_within(mapping.effective_interval, target_interval)
            for target_interval in target_interval_options
        ):
            findings.append("mapping_interval_outside_target_interval")

    for group in by_collision.values():
        active = [
            mapping
            for mapping in group
            if mapping.mapping_status is not MappingStatus.WITHDRAWN
        ]
        for index, left in enumerate(active):
            for right in active[index + 1 :]:
                if left.target == right.target or not _intervals_overlap(
                    left.effective_interval, right.effective_interval
                ):
                    continue
                if not (
                    left.mapping_status is MappingStatus.AMBIGUOUS
                    and right.mapping_status is MappingStatus.AMBIGUOUS
                ):
                    findings.append("overlapping_asserted_external_identifier_mapping")
    if findings:
        raise DatasetValidationError(
            tuple(_finding(code) for code in sorted(set(findings)))
        )


def validate_identity_bundle_references(
    assignments: Sequence[IdentityAssignmentVersionV1],
    relationships: Sequence[IdentityRelationshipVersionV1],
    mappings: Sequence[ExternalIdentifierMappingVersionV1],
    classifications: Sequence[SecurityClassificationVersionV1],
    roles: Sequence[ListingRoleVersionV1],
    lifecycle_events: Sequence[ListingLifecycleVersionV1],
    terminations: Sequence[ListingTerminationVersionV1],
    coverage_versions: Sequence[ListingHistoryCoverageVersionV1],
) -> None:
    """Reject Task 3 references not closed by typed, active identity history."""
    findings: set[str] = set()
    assigned_intervals: dict[IdentityReferenceV1, list[TemporalIntervalClaimV1]] = {}
    for assignment in assignments:
        if assignment.assignment_effect is IdentityAssignmentEffect.ASSIGNED:
            assigned_intervals.setdefault(
                identity_reference(assignment.identity), []
            ).append(assignment.effective_interval)

    def require_interval_reference(
        reference: IdentityReferenceV1,
        claim: TemporalIntervalClaimV1,
        label: str,
    ) -> None:
        intervals = assigned_intervals.get(reference, ())
        if not intervals:
            findings.add(f"{label}_missing_or_inactive")
        elif not any(_interval_within(claim, interval) for interval in intervals):
            findings.add(f"{label}_interval_incompatible")

    def require_boundary_reference(
        reference: IdentityReferenceV1,
        boundary: TemporalBoundaryClaimV1,
        label: str,
    ) -> None:
        intervals = assigned_intervals.get(reference, ())
        if not intervals:
            findings.add(f"{label}_missing_or_inactive")
        elif not any(
            _boundary_within_interval(boundary, interval) for interval in intervals
        ):
            findings.add(f"{label}_interval_incompatible")

    for relationship in relationships:
        require_interval_reference(
            relationship.left,
            relationship.effective_interval,
            "relationship_left_reference",
        )
        require_interval_reference(
            relationship.right,
            relationship.effective_interval,
            "relationship_right_reference",
        )

    for mapping in mappings:
        require_interval_reference(
            mapping.target,
            mapping.effective_interval,
            "mapping_target_reference",
        )

    for classification in classifications:
        issuer = IdentityReferenceV1(
            kind=IdentityKind.ISSUER, internal_id=classification.issuer_id
        )
        security = IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=classification.security_id
        )
        require_interval_reference(
            issuer, classification.effective_interval, "classification_issuer_reference"
        )
        require_interval_reference(
            security,
            classification.effective_interval,
            "classification_security_reference",
        )
        if not any(
            relationship.left == issuer
            and relationship.right == security
            and relationship.relationship_kind
            is IdentityRelationshipKind.ISSUER_HAS_SECURITY
            and relationship.resolution_status is ResolutionStatus.RESOLVED
            and _interval_within(
                classification.effective_interval, relationship.effective_interval
            )
            for relationship in relationships
        ):
            findings.add("classification_issuer_security_relationship_missing")

    for role in roles:
        security = IdentityReferenceV1(
            kind=IdentityKind.SECURITY, internal_id=role.security_id
        )
        listing = IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=role.listing_id
        )
        require_interval_reference(
            security, role.effective_interval, "listing_role_security_reference"
        )
        require_interval_reference(
            listing, role.effective_interval, "listing_role_listing_reference"
        )
        if not any(
            relationship.left == security
            and relationship.right == listing
            and relationship.relationship_kind
            is IdentityRelationshipKind.SECURITY_HAS_LISTING
            and relationship.resolution_status is ResolutionStatus.RESOLVED
            and _interval_within(
                role.effective_interval, relationship.effective_interval
            )
            for relationship in relationships
        ):
            findings.add("listing_role_security_listing_relationship_missing")

    listing_references: set[IdentityReferenceV1] = set()
    security_references: set[IdentityReferenceV1] = set()
    for mapping in mappings:
        if mapping.target.kind is IdentityKind.LISTING:
            listing_references.add(mapping.target)
        elif mapping.target.kind is IdentityKind.SECURITY:
            security_references.add(mapping.target)
    for classification in classifications:
        security_references.add(
            IdentityReferenceV1(
                kind=IdentityKind.SECURITY, internal_id=classification.security_id
            )
        )
    for role in roles:
        security_references.add(
            IdentityReferenceV1(
                kind=IdentityKind.SECURITY, internal_id=role.security_id
            )
        )
        listing_references.add(
            IdentityReferenceV1(kind=IdentityKind.LISTING, internal_id=role.listing_id)
        )
    for event in lifecycle_events:
        listing = IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=event.listing_id
        )
        listing_references.add(listing)
        require_boundary_reference(
            listing, event.effective_time, "lifecycle_listing_reference"
        )
        if event.related_listing_id is not None:
            related = IdentityReferenceV1(
                kind=IdentityKind.LISTING, internal_id=event.related_listing_id
            )
            listing_references.add(related)
            if related not in assigned_intervals:
                findings.add("lifecycle_related_listing_reference_missing_or_inactive")
    for termination in terminations:
        listing = IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=termination.listing_id
        )
        listing_references.add(listing)
        require_boundary_reference(
            listing, termination.effective_time, "termination_listing_reference"
        )
    selected_relationships = _current_relationship_interpretation(relationships)
    for termination in terminations:
        if not termination.successor_relationship_ids:
            continue
        listing = IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=termination.listing_id
        )
        predecessor_links = tuple(
            relationship
            for relationship in selected_relationships.values()
            if relationship.relationship_kind
            is IdentityRelationshipKind.SECURITY_HAS_LISTING
            and relationship.resolution_status is ResolutionStatus.RESOLVED
            and relationship.right == listing
            and _boundary_within_interval(
                termination.effective_time, relationship.effective_interval
            )
        )
        if len(predecessor_links) != 1:
            findings.add("termination_successor_predecessor_security_unresolved")
            continue
        predecessor_security = predecessor_links[0].left
        for relationship_id in termination.successor_relationship_ids:
            successor = selected_relationships.get(relationship_id)
            if (
                successor is None
                or successor.relationship_kind
                not in {
                    IdentityRelationshipKind.SUCCESSOR_OF,
                    IdentityRelationshipKind.REORGANIZED_FROM,
                }
                or successor.resolution_status is not ResolutionStatus.RESOLVED
                or successor.left.kind is not IdentityKind.SECURITY
                or successor.right != predecessor_security
                or not _boundary_within_interval(
                    termination.effective_time, successor.effective_interval
                )
            ):
                findings.add("termination_successor_relationship_invalid")
    for coverage in coverage_versions:
        listing = IdentityReferenceV1(
            kind=IdentityKind.LISTING, internal_id=coverage.listing_id
        )
        listing_references.add(listing)
        if listing not in assigned_intervals:
            findings.add("coverage_listing_reference_missing_or_inactive")

    for listing in listing_references:
        listing_links = tuple(
            relationship
            for relationship in relationships
            if relationship.right == listing
            and relationship.relationship_kind
            is IdentityRelationshipKind.SECURITY_HAS_LISTING
            and relationship.resolution_status is ResolutionStatus.RESOLVED
        )
        if not listing_links:
            findings.add("listing_security_relationship_missing")
        security_references.update(relationship.left for relationship in listing_links)
    for security in security_references:
        if not any(
            relationship.right == security
            and relationship.relationship_kind
            is IdentityRelationshipKind.ISSUER_HAS_SECURITY
            and relationship.resolution_status is ResolutionStatus.RESOLVED
            for relationship in relationships
        ):
            findings.add("security_issuer_relationship_missing")

    if findings:
        raise DatasetValidationError(tuple(_finding(code) for code in sorted(findings)))


def _current_relationship_interpretation(
    relationships: Sequence[IdentityRelationshipVersionV1],
) -> dict[object, IdentityRelationshipVersionV1]:
    """Select one causal manifest-current relationship version per logical chain."""
    chains: dict[object, list[IdentityRelationshipVersionV1]] = {}
    for relationship in relationships:
        chains.setdefault(relationship.revision.logical_record_id, []).append(
            relationship
        )
    selected: dict[object, IdentityRelationshipVersionV1] = {}
    for logical_record_id, chain in chains.items():
        projections = tuple(
            AssertionVersionProjectionV1(
                revision=relationship.revision,
                record_hash=content_hash(relationship),
            )
            for relationship in chain
        )
        if validate_assertion_chain(projections):
            continue
        ordered = sorted(chain, key=lambda item: item.revision.source_sequence)
        current = ordered[-1]
        if current.revision.revision_kind is not RevisionKind.WITHDRAWAL:
            selected[logical_record_id] = current
    return selected


def validate_listing_roles(roles: Sequence[ListingRoleVersionV1]) -> None:
    """Reject overlapping primary nominations from one methodology."""
    findings: list[str] = []
    primaries = [role for role in roles if role.role is ListingRole.PRIMARY]
    for index, left in enumerate(primaries):
        for right in primaries[index + 1 :]:
            if (
                left.revision.logical_record_id != right.revision.logical_record_id
                and left.security_id == right.security_id
                and left.methodology_id == right.methodology_id
                and left.listing_id != right.listing_id
                and _intervals_overlap(
                    left.effective_interval, right.effective_interval
                )
            ):
                findings.append("overlapping_primary_listing_role")
    if findings:
        raise DatasetValidationError(
            tuple(_finding(code) for code in sorted(set(findings)))
        )


def validate_listing_terminations(
    terminations: Sequence[ListingTerminationVersionV1],
) -> None:
    """Require one logical termination authority per listing history."""
    logical_ids_by_listing: dict[object, set[object]] = {}
    findings: set[str] = set()
    for termination in terminations:
        logical_ids_by_listing.setdefault(termination.listing_id, set()).add(
            termination.revision.logical_record_id
        )
        last_upper = termination.last_regular_trade_time.upper_bound
        effective_lower = termination.effective_time.lower_bound
        if (
            last_upper is not None
            and effective_lower is not None
            and last_upper > effective_lower
        ):
            findings.add("last_regular_trade_after_termination")
    if any(len(logical_ids) > 1 for logical_ids in logical_ids_by_listing.values()):
        findings.add("multiple_sole_termination_records")
    if findings:
        raise DatasetValidationError(tuple(_finding(code) for code in sorted(findings)))


def validate_listing_lifecycle(
    events: Sequence[ListingLifecycleVersionV1],
) -> None:
    """Reject definitely impossible event ordering and state transitions."""
    findings: set[str] = set()
    by_listing: dict[object, list[ListingLifecycleVersionV1]] = {}
    for event in events:
        by_listing.setdefault(event.listing_id, []).append(event)
    for listing_events in by_listing.values():
        by_kind: dict[ListingLifecycleEventKind, list[ListingLifecycleVersionV1]] = {}
        for event in listing_events:
            by_kind.setdefault(event.event_kind, []).append(event)
        for kind in (
            ListingLifecycleEventKind.ADMITTED,
            ListingLifecycleEventKind.FIRST_REGULAR_TRADE,
            ListingLifecycleEventKind.VENUE_TRANSFER,
        ):
            logical_ids = {
                event.revision.logical_record_id for event in by_kind.get(kind, ())
            }
            if len(logical_ids) > 1:
                findings.add(f"multiple_{kind.value}_events")

        admissions = by_kind.get(ListingLifecycleEventKind.ADMITTED, ())
        first_trades = by_kind.get(ListingLifecycleEventKind.FIRST_REGULAR_TRADE, ())
        if first_trades and not admissions:
            findings.add("first_trade_requires_admission")
        elif first_trades and admissions:
            admission = admissions[0].effective_time
            first_trade = first_trades[0].effective_time
            if (
                first_trade.upper_bound is not None
                and admission.lower_bound is not None
                and first_trade.upper_bound < admission.lower_bound
            ):
                findings.add("first_trade_before_admission")

        state_events = tuple(
            event
            for event in listing_events
            if event.event_kind
            in {
                ListingLifecycleEventKind.SUSPENDED,
                ListingLifecycleEventKind.RESUMED,
            }
        )
        if state_events and not first_trades:
            findings.add("suspension_requires_first_trade")
        elif first_trades:
            first_trade_lower = first_trades[0].effective_time.lower_bound
            if first_trade_lower is not None and any(
                event.effective_time.upper_bound is not None
                and event.effective_time.upper_bound < first_trade_lower
                for event in state_events
            ):
                findings.add("suspension_before_first_trade")

        ordered = sorted(
            (
                event
                for event in listing_events
                if event.event_kind
                in {
                    ListingLifecycleEventKind.SUSPENDED,
                    ListingLifecycleEventKind.RESUMED,
                }
                and event.effective_time.lower_bound is not None
                and event.effective_time.upper_bound is not None
            ),
            key=_known_lifecycle_lower_bound,
        )
        suspended = False
        previous = None
        for event in ordered:
            previous_upper: datetime | None = (
                None if previous is None else previous.effective_time.upper_bound
            )
            event_lower = event.effective_time.lower_bound
            if (
                previous_upper is not None
                and event_lower is not None
                and previous_upper > event_lower
            ):
                previous = event
                continue
            if event.event_kind is ListingLifecycleEventKind.SUSPENDED:
                if suspended:
                    findings.add("suspension_resumption_must_alternate")
                suspended = True
            else:
                if not suspended:
                    findings.add("suspension_resumption_must_alternate")
                suspended = False
            previous = event
    if findings:
        raise DatasetValidationError(tuple(_finding(code) for code in sorted(findings)))


def _known_lifecycle_lower_bound(event: ListingLifecycleVersionV1) -> datetime:
    lower_bound = event.effective_time.lower_bound
    assert lower_bound is not None
    return lower_bound


def _intervals_overlap(
    left: TemporalIntervalClaimV1, right: TemporalIntervalClaimV1
) -> bool:
    """Treat intervals as overlapping unless disjointness is certain."""
    left_start = left.start.lower_bound
    right_start = right.start.lower_bound
    left_end = None if left.end is None else left.end.upper_bound
    right_end = None if right.end is None else right.end.upper_bound
    left_definitely_ends_before_right = (
        left_end is not None and right_start is not None and left_end <= right_start
    )
    right_definitely_ends_before_left = (
        right_end is not None and left_start is not None and right_end <= left_start
    )
    return not (left_definitely_ends_before_right or right_definitely_ends_before_left)


def _interval_within(
    inner: TemporalIntervalClaimV1, outer: TemporalIntervalClaimV1
) -> bool:
    """Require containment to be certain over every allowed boundary instant."""
    inner_start = inner.start.lower_bound
    outer_start = outer.start.upper_bound
    if inner_start is None or outer_start is None or inner_start < outer_start:
        return False
    if outer.end is None:
        return True
    if inner.end is None:
        return False
    inner_end = inner.end.upper_bound
    outer_end = outer.end.lower_bound
    return inner_end is not None and outer_end is not None and inner_end <= outer_end


def _boundary_within_interval(
    boundary: TemporalBoundaryClaimV1,
    interval: TemporalIntervalClaimV1,
) -> bool:
    """Require every possible boundary instant to fall inside an identity interval."""
    boundary_start = boundary.lower_bound
    boundary_end = boundary.upper_bound
    interval_start = interval.start.upper_bound
    if (
        boundary_start is None
        or boundary_end is None
        or interval_start is None
        or boundary_start < interval_start
    ):
        return False
    if interval.end is None:
        return True
    interval_end = interval.end.lower_bound
    return interval_end is not None and boundary_end <= interval_end
