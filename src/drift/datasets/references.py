"""Compatibility bridges from exact M1a provenance into M0 references."""

from drift.datasets.hashing import derived_temporal_coverage, manifest_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationError,
    ValidationResult,
)
from drift.domain.datasets import DatasetReference
from drift.domain.manifests import DatasetManifestV1


def build_dataset_reference(
    manifest: DatasetManifestV1,
    manifest_reference: ArtifactReference,
    decision: DatasetValidationDecisionV1,
) -> DatasetReference:
    """Build provenance only, without certifying a cutoff or authorizing promotion."""
    digest = manifest_hash(manifest)
    if manifest_reference.kind is not ArtifactKind.DATASET:
        raise DatasetValidationError.single("manifest_artifact_kind")
    if manifest_reference.content_hash != digest or decision.manifest_hash != digest:
        raise DatasetValidationError.single("manifest_hash_mismatch")
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("manifest_not_validated")
    return DatasetReference(
        dataset_id=manifest.dataset_id,
        dataset_version=manifest.dataset_version,
        schema_version=manifest.schema_definition.schema_version,
        content_hash=digest,
        created_at=manifest.created_at,
        source=manifest.source.source_id,
        temporal_coverage=derived_temporal_coverage(manifest.partitions),
        point_in_time_policy="explicit_record_evidence_v1",
        corporate_action_policy="not_applicable_m1a",
        availability_timestamp_policy="channel_scoped_no_defaults_v1",
        manifest_reference=manifest_reference,
    )
