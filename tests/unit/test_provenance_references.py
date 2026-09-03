"""Credential-safety tests for every M1a provenance reference boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from pydantic import BaseModel, ValidationError

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
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
from drift.serialization.canonical import content_hash

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
    with pytest.raises(ValidationError, match="credentials"):
        factory(reference(location))
