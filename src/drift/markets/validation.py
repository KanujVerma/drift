"""Exact-byte validation for immutable M1b identity assertion datasets."""

import json
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from drift.datasets.assertions import (
    validate_assertion_chain,
    validate_manifest_v2_structure,
)
from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.assertions import AssertionVersionProjectionV1
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.manifests import DatasetManifestV2, FieldDescriptorV1, LogicalType
from drift.domain.securities import (
    IdentityAssignmentVersionV1,
    IdentityRelationshipVersionV1,
)
from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import canonical_json, content_hash

_ASSIGNMENT_ROLE = "identity_assignment"
_RELATIONSHIP_ROLE = "identity_relationship"

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


def validate_identity_dataset(
    manifest: DatasetManifestV2,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV2:
    """Validate one role-specific identity dataset and every parsed assertion."""
    structure = validate_manifest_v2_structure(manifest, verified_artifacts, context)
    findings = list(structure.findings)
    records: list[IdentityAssignmentVersionV1 | IdentityRelationshipVersionV1] = []
    role = manifest.dataset_role.name
    if role not in {_ASSIGNMENT_ROLE, _RELATIONSHIP_ROLE}:
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
    if role == _ASSIGNMENT_ROLE:
        expected_fields["assignment_effect"] = (LogicalType.STRING, False)
    elif role == _RELATIONSHIP_ROLE:
        expected_fields.update(
            {
                "relationship_kind": (LogicalType.STRING, False),
                "resolution_status": (LogicalType.STRING, False),
            }
        )
    if not _has_exact_identity_schema(
        manifest.schema_definition.fields, expected_fields
    ):
        findings.append(_finding("identity_role_schema_mismatch"))
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


def _parse_identity_records(
    artifact: VerifiedArtifactBytes,
    role: str,
) -> tuple[
    tuple[IdentityAssignmentVersionV1 | IdentityRelationshipVersionV1, ...],
    tuple[ValidationFindingV1, ...],
]:
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

    model = (
        IdentityAssignmentVersionV1
        if role == _ASSIGNMENT_ROLE
        else IdentityRelationshipVersionV1
    )
    records: list[IdentityAssignmentVersionV1 | IdentityRelationshipVersionV1] = []
    findings: list[ValidationFindingV1] = []
    for raw_record in document["records"]:
        try:
            record = model.model_validate_json(canonical_json(raw_record))
        except CanonicalSerializationError, TypeError, ValidationError:
            findings.append(_finding("identity_record_invalid"))
            continue
        expected_payload_hash = content_hash(assertion_version_payload(record))
        if record.revision.payload_hash != expected_payload_hash:
            findings.append(_finding("identity_payload_hash_mismatch"))
            continue
        records.append(record)
    return tuple(records), tuple(findings)


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
