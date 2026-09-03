"""Credential-safety tests for every M1a provenance reference boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import BaseModel, ValidationError

from drift.datasets.hashing import manifest_hash
from drift.datasets.references import build_dataset_reference
from drift.datasets.validation import (
    SYNTHETIC_FACT_SCHEMA_V1,
    synthetic_fact_temporal_contract_v1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationScope,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV1,
    DeterminismClaim,
    LicenseDescriptorV1,
    LineageDescriptorV1,
    PartitionDescriptorV1,
    SourceDescriptorV1,
)
from drift.domain.revisions import (
    FactVersionV1,
    LogicalFactKeyV1,
    RevisionKind,
)
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityShape,
    ChannelKind,
    RuleDerivationV1,
    SourcePrecision,
    ValidPeriodV1,
)
from drift.serialization.canonical import canonical_json, content_hash

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(kind=ChannelKind.PUBLIC, identifier="source")


def reference(location: str, *, digest: str = HASH_A) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=digest,
        location=location,
    )


def source_model(item: ArtifactReference) -> BaseModel:
    return SourceDescriptorV1(
        source_id="source",
        publisher="publisher",
        product="product",
        evidence_reference=item,
    )


def acquisition_model(item: ArtifactReference) -> BaseModel:
    return AcquisitionDescriptorV1(
        acquired_at=NOW,
        collector_id="collector",
        collector_version="1",
        evidence_reference=item,
    )


def license_model(item: ArtifactReference) -> BaseModel:
    return LicenseDescriptorV1(
        provider_legal_name="provider",
        license_reference="license",
        acquired_at=NOW,
        terms_evidence_reference=item,
    )


def lineage_transformation_model(item: ArtifactReference) -> BaseModel:
    return LineageDescriptorV1(
        input_manifest_hashes=(HASH_A,),
        transformation_reference=item,
        configuration_hash=HASH_A,
        implementation_reference=reference("evidence:implementation", digest=HASH_B),
        environment_hash=HASH_A,
        output_schema_hash=HASH_B,
        executed_at=NOW,
        determinism=DeterminismClaim.DETERMINISTIC,
    )


def lineage_implementation_model(item: ArtifactReference) -> BaseModel:
    return LineageDescriptorV1(
        input_manifest_hashes=(HASH_A,),
        transformation_reference=reference("evidence:transformation", digest=HASH_B),
        configuration_hash=HASH_A,
        implementation_reference=item,
        environment_hash=HASH_A,
        output_schema_hash=HASH_B,
        executed_at=NOW,
        determinism=DeterminismClaim.DETERMINISTIC,
    )


def temporal_evidence_model(item: ArtifactReference) -> BaseModel:
    available = datetime(2022, 5, 5, 20, tzinfo=UTC)
    return AvailabilityEvidenceV1(
        channel=PUBLIC,
        shape=AvailabilityShape.EXACT,
        lower_bound=available,
        upper_bound=available,
        precision=SourcePrecision.SECOND,
        source_time_label="2022-05-05T20:00:00Z",
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=item,
    )


def rule_derivation_model(item: ArtifactReference) -> BaseModel:
    return RuleDerivationV1(
        rule_reference=item,
        rule_version="1",
        input_evidence_hash=HASH_B,
    )


def fact_model(item: ArtifactReference) -> BaseModel:
    available = datetime(2022, 5, 5, 20, tzinfo=UTC)
    values = {
        "fact_version_id": uuid7(),
        "logical_key": LogicalFactKeyV1(
            source_id="source",
            entity_key="entity",
            concept="concept",
            valid_period=ValidPeriodV1(
                started_at=datetime(2022, 1, 1, tzinfo=UTC),
                ended_at=datetime(2022, 4, 1, tzinfo=UTC),
            ),
            unit="unit",
            dimensions={},
        ),
        "revision_kind": RevisionKind.INITIAL,
        "supersedes_fact_version_id": None,
        "source_sequence": 0,
        "value": "value",
        "null_reason": None,
        "availability": (
            AvailabilityEvidenceV1(
                channel=PUBLIC,
                shape=AvailabilityShape.EXACT,
                lower_bound=available,
                upper_bound=available,
                precision=SourcePrecision.SECOND,
                source_time_label="2022-05-05T20:00:00Z",
                basis=AvailabilityBasis.SOURCE_OBSERVED,
            ),
        ),
        "source_artifact": item,
    }
    return FactVersionV1.model_validate(
        {**values, "payload_hash": content_hash(values)}
    )


def partition_model(item: ArtifactReference) -> BaseModel:
    return PartitionDescriptorV1(
        partition_id=uuid7(),
        partition_key="part=1",
        artifact=item,
        byte_size=1,
        media_type="application/json",
        format_version="1",
        row_count=1,
        schema_hash=HASH_B,
        coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
    )


def validation_finding_model(item: ArtifactReference) -> BaseModel:
    return ValidationFindingV1(
        code="unsafe_reference",
        severity=FindingSeverity.ERROR,
        message="unsafe reference",
        artifact_references=(item,),
    )


def _bridge_manifest() -> DatasetManifestV1:
    partition_digest = HASH_B
    partition = PartitionDescriptorV1(
        partition_id=uuid7(),
        partition_key="part=1",
        artifact=reference(
            f"drift+sha256://{partition_digest}", digest=partition_digest
        ),
        byte_size=1,
        media_type="application/json",
        format_version="1",
        row_count=1,
        schema_hash=SYNTHETIC_FACT_SCHEMA_V1.schema_hash,
        coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
    )
    return DatasetManifestV1(
        manifest_schema_version="1",
        hash_profile="drift-canonical-json-sha256-v1",
        dataset_id=uuid7(),
        dataset_version="1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        created_at=NOW,
        source=SourceDescriptorV1(
            source_id="source",
            publisher="publisher",
            product="product",
            evidence_reference=reference("evidence:source"),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=NOW,
            collector_id="collector",
            collector_version="1",
            evidence_reference=reference("evidence:acquisition"),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="provider",
            license_reference="license",
            acquired_at=NOW,
            terms_evidence_reference=reference("evidence:license"),
        ),
        schema_definition=SYNTHETIC_FACT_SCHEMA_V1,
        partitions=(partition,),
        temporal_contract=synthetic_fact_temporal_contract_v1((PUBLIC,)),
    )


BRIDGE_MANIFEST = _bridge_manifest()
BRIDGE_DECISION = DatasetValidationDecisionV1(
    decision_id=uuid7(),
    manifest_hash=manifest_hash(BRIDGE_MANIFEST),
    validator_version="1",
    validator_implementation_hash=HASH_A,
    validation_profile_id="synthetic",
    validation_profile_hash=HASH_B,
    checked_at=NOW,
    validation_scope=ValidationScope.RECORDS,
    result=ValidationResult.PASS,
    validated_artifact_hashes=(HASH_B,),
    validated_record_hashes=(HASH_A,),
    checked_contracts=("dataset-manifest-v1", "record-temporal-v1"),
    findings=(),
)


def dataset_reference_bridge(item: ArtifactReference) -> BaseModel:
    manifest_reference = item.model_copy(
        update={
            "kind": ArtifactKind.DATASET,
            "content_hash": manifest_hash(BRIDGE_MANIFEST),
        }
    )
    return build_dataset_reference(BRIDGE_MANIFEST, manifest_reference, BRIDGE_DECISION)


REFERENCE_MODELS: tuple[tuple[str, Callable[[ArtifactReference], BaseModel]], ...] = (
    ("source", source_model),
    ("acquisition", acquisition_model),
    ("license", license_model),
    ("lineage transformation", lineage_transformation_model),
    ("lineage implementation", lineage_implementation_model),
    ("temporal evidence", temporal_evidence_model),
    ("temporal rule", rule_derivation_model),
    ("fact source", fact_model),
    ("partition", partition_model),
    ("validation finding", validation_finding_model),
    ("dataset reference bridge", dataset_reference_bridge),
)

UNSAFE_LOCATIONS = (
    "https://user:password@example.test/evidence.json",
    "https://example.test/evidence.json?api_key=secret",
    "https://example.test/evidence.json?X-Amz-Signature=secret",
    "https://example.test/evidence.json#access_token=secret",
)


@pytest.mark.parametrize(("model_name", "factory"), REFERENCE_MODELS)
@pytest.mark.parametrize("location", UNSAFE_LOCATIONS)
def test_every_m1a_reference_model_rejects_credential_bearing_locations(
    model_name: str,
    factory: Callable[[ArtifactReference], BaseModel],
    location: str,
) -> None:
    """Removing any model validator would persist a credential-bearing locator."""
    with pytest.raises((ValidationError, ValueError), match="credentials"):
        factory(reference(location))


@pytest.mark.parametrize(("model_name", "factory"), REFERENCE_MODELS)
def test_every_m1a_reference_seam_accepts_and_retains_a_safe_location(
    model_name: str,
    factory: Callable[[ArtifactReference], BaseModel],
) -> None:
    """Over-broad credential screening would reject a safe retained reference."""
    safe_location = (
        f"drift+sha256://{HASH_A}" if model_name == "partition" else "evidence:safe"
    )
    safe = reference(safe_location)

    result = factory(safe)

    assert safe_location.encode() in canonical_json(result)
