"""Compact audit-event draft factories for immutable dataset evidence."""

from drift.datasets.hashing import manifest_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationDecisionV2,
    DatasetValidationError,
)
from drift.domain.manifests import DatasetManifestV1, DatasetManifestV2
from drift.ledger.interface import AuditEventDraft
from drift.serialization.canonical import content_hash


def build_manifest_recorded_event(
    manifest: DatasetManifestV1,
    manifest_reference: ArtifactReference,
) -> AuditEventDraft:
    """Build an unhashed compact draft for one content-bound manifest."""
    digest = manifest_hash(manifest)
    if manifest_reference.kind is not ArtifactKind.DATASET:
        raise DatasetValidationError.single("manifest_artifact_kind")
    if manifest_reference.content_hash != digest:
        raise DatasetValidationError.single("manifest_hash_mismatch")
    return AuditEventDraft(
        event_id=manifest_reference.artifact_id,
        event_type="dataset.manifest.recorded",
        timestamp=manifest.created_at,
        entity_type="dataset_manifest",
        entity_id=manifest.dataset_id,
        payload={
            "manifest_id": str(manifest_reference.artifact_id),
            "manifest_hash": digest,
            "hash_profile": manifest.hash_profile,
            "schema_version": manifest.manifest_schema_version,
        },
        schema_version="1",
    )


def build_validation_completed_event(
    manifest: DatasetManifestV1,
    decision: DatasetValidationDecisionV1,
) -> AuditEventDraft:
    """Build an unhashed compact draft for an exact validation decision."""
    if decision.manifest_hash != manifest_hash(manifest):
        raise DatasetValidationError.single("manifest_hash_mismatch")
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


def build_manifest_v2_recorded_event(
    manifest: DatasetManifestV2,
    manifest_reference: ArtifactReference,
) -> AuditEventDraft:
    """Build a schema-explicit draft for one V2 manifest."""
    digest = manifest_hash(manifest)
    if manifest_reference.kind is not ArtifactKind.DATASET:
        raise DatasetValidationError.single("manifest_artifact_kind")
    if manifest_reference.content_hash != digest:
        raise DatasetValidationError.single("manifest_hash_mismatch")
    return AuditEventDraft(
        event_id=manifest_reference.artifact_id,
        event_type="dataset.manifest.v2.recorded",
        timestamp=manifest.created_at,
        entity_type="dataset_manifest",
        entity_id=manifest.dataset_id,
        payload={
            "manifest_id": str(manifest_reference.artifact_id),
            "manifest_hash": digest,
            "manifest_schema_version": manifest.manifest_schema_version,
            "dataset_role_hash": content_hash(manifest.dataset_role),
            "temporal_contract_kind": manifest.temporal_contract.kind.value,
        },
        schema_version="2",
    )


def build_validation_v2_completed_event(
    manifest: DatasetManifestV2,
    decision: DatasetValidationDecisionV2,
) -> AuditEventDraft:
    """Build a schema-explicit draft for an exact V2 validation decision."""
    if decision.manifest_hash != manifest_hash(manifest):
        raise DatasetValidationError.single("manifest_hash_mismatch")
    if decision.dataset_role_hash != content_hash(manifest.dataset_role):
        raise DatasetValidationError.single("dataset_role_hash_mismatch")
    if decision.manifest_schema_version != manifest.manifest_schema_version:
        raise DatasetValidationError.single("manifest_schema_version_mismatch")
    if decision.schema_hash != manifest.schema_definition.schema_hash:
        raise DatasetValidationError.single("schema_hash_mismatch")
    if decision.temporal_contract_kind is not manifest.temporal_contract.kind:
        raise DatasetValidationError.single("temporal_contract_kind_mismatch")
    contract = manifest.temporal_contract.contract
    if decision.temporal_contract_version != contract.contract_version:
        raise DatasetValidationError.single("temporal_contract_version_mismatch")
    if decision.temporal_contract_hash != content_hash(contract):
        raise DatasetValidationError.single("temporal_contract_hash_mismatch")
    return AuditEventDraft(
        event_id=decision.decision_id,
        event_type="dataset.validation.v2.completed",
        timestamp=decision.checked_at,
        entity_type="dataset_manifest",
        entity_id=manifest.dataset_id,
        payload={
            "manifest_hash": decision.manifest_hash,
            "decision_hash": content_hash(decision),
            "decision_schema_version": decision.decision_schema_version,
            "result": decision.result.value,
            "validation_scope": decision.validation_scope.value,
            "temporal_contract_kind": decision.temporal_contract_kind.value,
        },
        schema_version="2",
    )
