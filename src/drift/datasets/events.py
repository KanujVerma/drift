"""Compact audit-event draft factories for immutable dataset evidence."""

from drift.datasets.hashing import manifest_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationError,
)
from drift.domain.manifests import DatasetManifestV1
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
