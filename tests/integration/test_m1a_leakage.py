"""Adversarial exact-byte tests for M1a temporal leakage defenses."""

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from drift.datasets.hashing import schema_hash
from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
)
from drift.datasets.validation import (
    parse_synthetic_fact_bytes,
    validate_synthetic_fact_dataset,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationError,
    ValidationResult,
    ValidationRunContextV1,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    AcquisitionDescriptorV1,
    DatasetKind,
    DatasetManifestV1,
    FieldDescriptorV1,
    LicenseDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    RecordTemporalContractV1,
    SchemaDescriptorV1,
    SourceDescriptorV1,
)
from drift.domain.revisions import select_fact_version
from drift.domain.temporal import (
    CONSERVATIVE_UPPER_BOUND_RULE_HASH,
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    ChannelKind,
    SourcePrecision,
    derive_conservative_upper_bound,
)
from drift.errors import ArtifactIntegrityError, ArtifactResolutionError
from drift.serialization.canonical import canonical_json, content_hash

FIXTURES = Path(__file__).parents[1] / "fixtures" / "datasets" / "m1a"
EXPECTED_HASHES = {
    "late-fundamental.json": (
        "69318299cc17b4c919de8d16c0d008822b1846546567f1616a7d0196be04b708"
    ),
    "restated-fundamental.json": (
        "3af884fea5a3b7037c9aad818a308d022d499d5ca99d080e72b32eb3dbc4d47f"
    ),
    "macro-vintage.json": (
        "527205a6e60b1d2b36eb9e722f9992e988b72196c1aaa8a2045f39498343fbaf"
    ),
    "vendor-delay.json": (
        "8aa9721a790e881a62ecadf6be5458a77832a9cd000181c1de1101bc6056c6f0"
    ),
    "date-only-release.json": (
        "da7940e8d8f5dcc361a450bf6bbf2d5ffa03a370db288c608c514a968944d877"
    ),
    "derived-upper-bound.json": (
        "34eb40fcb2a641f25302e7ae693abeba804169b969397ce3c59ca09d530ab099"
    ),
    "bounded-release.json": (
        "37b9ef343b63e69ffa21fefddfed8873b40b47e293f35b844d5e1e488e509d04"
    ),
    "unknown-release.json": (
        "689fda33fd981c868b5644d51be4ed23c3f9dee72ce60eab2a3d6b0915f67b5b"
    ),
    "late-ingest.json": (
        "7f409a6b15050a283a8d4435642870c32ca902bf20ef7750e7431c2d5ded8746"
    ),
    "withdrawal.json": (
        "6d39f56bf38dd1ce9e10103c191958695ac3498545f740b4b7e5b6451e71670e"
    ),
}

CHANNELS = {
    "public": AvailabilityChannelV1(
        kind=ChannelKind.PUBLIC, identifier="synthetic-public", version="1"
    ),
    "vendor": AvailabilityChannelV1(
        kind=ChannelKind.VENDOR, identifier="synthetic-vendor", version="1"
    ),
    "system": AvailabilityChannelV1(
        kind=ChannelKind.SYSTEM, identifier="synthetic-system", version="1"
    ),
}
POLICIES = {
    "strict": AvailabilityPolicyV1(policy_id="strict"),
    "rule_allowed": AvailabilityPolicyV1(
        policy_id="rule_allowed",
        permitted_rule_hashes=(CONSERVATIVE_UPPER_BOUND_RULE_HASH,),
    ),
}

CASES = (
    (
        "late-fundamental.json",
        "public",
        "strict",
        "2022-04-30T23:59:59Z",
        "ineligible",
        None,
    ),
    (
        "late-fundamental.json",
        "public",
        "strict",
        "2022-05-05T20:00:00Z",
        "eligible",
        "1.20",
    ),
    (
        "restated-fundamental.json",
        "public",
        "strict",
        "2022-06-01T00:00:00Z",
        "eligible",
        "1.20",
    ),
    (
        "restated-fundamental.json",
        "public",
        "strict",
        "2022-08-10T00:00:00Z",
        "eligible",
        "0.90",
    ),
    (
        "macro-vintage.json",
        "public",
        "strict",
        "2022-02-01T00:00:00Z",
        "eligible",
        "initial",
    ),
    (
        "macro-vintage.json",
        "public",
        "strict",
        "2022-03-01T00:00:00Z",
        "eligible",
        "revised",
    ),
    (
        "vendor-delay.json",
        "public",
        "strict",
        "2022-05-05T20:00:00Z",
        "eligible",
        "released",
    ),
    (
        "vendor-delay.json",
        "vendor",
        "strict",
        "2022-05-05T20:00:00Z",
        "ineligible",
        None,
    ),
    (
        "date-only-release.json",
        "public",
        "strict",
        "2022-05-05T12:00:00Z",
        "indeterminate",
        None,
    ),
    (
        "date-only-release.json",
        "public",
        "strict",
        "2022-05-06T04:00:00Z",
        "eligible",
        "released",
    ),
    (
        "derived-upper-bound.json",
        "public",
        "rule_allowed",
        "2022-05-06T04:00:00Z",
        "eligible",
        "released",
    ),
    (
        "unknown-release.json",
        "public",
        "strict",
        "2030-01-01T00:00:00Z",
        "indeterminate",
        None,
    ),
    (
        "late-ingest.json",
        "system",
        "strict",
        "2022-05-06T00:00:00Z",
        "ineligible",
        None,
    ),
    (
        "withdrawal.json",
        "public",
        "strict",
        "2022-09-01T00:00:00Z",
        "ineligible",
        None,
    ),
)


def parse_utc(value: str) -> datetime:
    """Parse a test cutoff without relying on fixture code."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def retained_evidence_by_hash(
    verified: VerifiedArtifactBytes,
) -> dict[str, AvailabilityEvidenceV1]:
    """Recover retained raw evidence independently from verified document bytes."""
    evidence = (
        item
        for version in parse_synthetic_fact_bytes(verified)
        for item in version.availability
        if item.basis is not AvailabilityBasis.RULE_DERIVED
    )
    return {content_hash(item): item for item in evidence}


def verified_fixture(filename: str) -> VerifiedArtifactBytes:
    """Read one pinned fixture through the confined resolver."""
    return read_verified_local_artifact(
        FIXTURES,
        filename,
        EXPECTED_HASHES[filename],
        ResolverLimits(max_bytes=64_000),
    )


@pytest.mark.parametrize(
    (
        "filename",
        "channel_id",
        "policy_id",
        "cutoff",
        "expected_class",
        "expected_value",
    ),
    CASES,
)
def test_adversarial_cutoff_table(
    filename: str,
    channel_id: str,
    policy_id: str,
    cutoff: str,
    expected_class: str,
    expected_value: str | None,
) -> None:
    """Future data or the wrong channel must never satisfy a cutoff query."""
    verified = verified_fixture(filename)
    versions = parse_synthetic_fact_bytes(verified)
    result = select_fact_version(
        versions,
        CHANNELS[channel_id],
        POLICIES[policy_id],
        parse_utc(cutoff),
        retained_evidence_by_hash(verified),
    )
    assert result.classification.value == expected_class
    actual = None if result.selected_version is None else result.selected_version.value
    assert actual == expected_value


def test_fixture_bytes_are_asset_neutral_and_retain_explicit_evidence() -> None:
    """Adding a forbidden domain field or dropping record evidence breaks this test."""
    forbidden = (
        "security_id",
        "listing_id",
        "ticker",
        "universe",
        "corporate_action",
        "session",
        '"bar"',
    )
    for filename in EXPECTED_HASHES:
        verified = verified_fixture(filename)
        text = verified.data.decode("utf-8").lower()
        assert not any(term in text for term in forbidden)
        for version in parse_synthetic_fact_bytes(verified):
            assert version.availability
            for evidence in version.availability:
                assert evidence.source_time_label is not None
                if evidence.precision is SourcePrecision.UNKNOWN:
                    assert evidence.lower_bound is None
                    assert evidence.upper_bound is None
                else:
                    assert evidence.lower_bound is not None
                    assert evidence.upper_bound is not None


def test_channel_and_date_fixtures_preserve_source_semantics() -> None:
    """Collapsing channels or fabricating a date-only instant breaks this test."""
    vendor = parse_synthetic_fact_bytes(verified_fixture("vendor-delay.json"))[0]
    assert tuple(item.channel for item in vendor.availability) == (
        CHANNELS["public"],
        CHANNELS["vendor"],
    )
    ingest = parse_synthetic_fact_bytes(verified_fixture("late-ingest.json"))[0]
    assert tuple(item.channel for item in ingest.availability) == (
        CHANNELS["public"],
        CHANNELS["system"],
    )
    date_only = parse_synthetic_fact_bytes(verified_fixture("date-only-release.json"))[
        0
    ].availability[0]
    assert date_only.source_time_label == "2022-05-05"
    assert date_only.source_timezone == "America/New_York"
    assert date_only.precision is SourcePrecision.DATE
    assert date_only.lower_bound == parse_utc("2022-05-05T04:00:00Z")
    assert date_only.upper_bound == parse_utc("2022-05-06T04:00:00Z")


def test_derived_upper_bound_recomputes_from_retained_raw_evidence() -> None:
    """A caller-authored derived instant cannot replace replayed rule output."""
    verified = verified_fixture("derived-upper-bound.json")
    raw_version, derived_version = parse_synthetic_fact_bytes(verified)
    raw = raw_version.availability[0]
    derived = derived_version.availability[0]
    assert derived.rule_derivation is not None
    assert derived.rule_derivation.input_evidence_hash == content_hash(raw)
    assert derived == derive_conservative_upper_bound(
        raw, derived.rule_derivation.rule_reference
    )


def _mutated_verified(
    filename: str, mutation: Callable[[dict[str, Any]], None]
) -> VerifiedArtifactBytes:
    document = cast(dict[str, Any], json.loads(verified_fixture(filename).data))
    mutation(document)
    data = canonical_json(document)
    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=sha256(data).hexdigest(),
    )


def _rehash(raw_version: dict[str, Any]) -> None:
    raw_version["payload_hash"] = content_hash(_normalized_payload(raw_version))


def _normalized_payload(raw_version: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(
        {key: value for key, value in raw_version.items() if key != "payload_hash"}
    )

    def normalize(container: object) -> None:
        if isinstance(container, dict):
            for key, item in container.items():
                if (
                    isinstance(item, str)
                    and key in {"lower_bound", "upper_bound", "started_at", "ended_at"}
                    and item.endswith("Z")
                    and "." not in item
                ):
                    container[key] = item.removesuffix("Z") + ".000000Z"
                else:
                    normalize(item)
        elif isinstance(container, list):
            for item in container:
                normalize(item)

    normalize(payload)
    return payload


def _chain_mutation(document: dict[str, Any], mutation: str) -> None:
    versions = cast(list[dict[str, Any]], document["fact_versions"])
    if mutation == "broken_predecessor":
        versions[1]["supersedes_fact_version_id"] = str(_uid(999))
        _rehash(versions[1])
    elif mutation == "cycle":
        versions[0]["revision_kind"] = "revision"
        versions[0]["supersedes_fact_version_id"] = versions[1]["fact_version_id"]
        _rehash(versions[0])
    elif mutation == "duplicate_version_id":
        versions[1]["fact_version_id"] = versions[0]["fact_version_id"]
        versions[1]["supersedes_fact_version_id"] = versions[0]["fact_version_id"]
        _rehash(versions[1])
    else:
        versions[1]["source_sequence"] = 0
        _rehash(versions[1])


@pytest.mark.parametrize(
    "mutation",
    ("broken_predecessor", "cycle", "duplicate_version_id", "reversed_chronology"),
)
def test_malformed_fixture_chains_are_rejected(mutation: str) -> None:
    """Removing a revision-chain guard makes one malformed chain selectable."""
    verified = _mutated_verified(
        "restated-fundamental.json",
        lambda document: _chain_mutation(document, mutation),
    )
    versions = parse_synthetic_fact_bytes(verified)
    with pytest.raises(DatasetValidationError):
        select_fact_version(
            versions,
            CHANNELS["public"],
            POLICIES["strict"],
            parse_utc("2022-09-01T00:00:00Z"),
            retained_evidence_by_hash(verified),
        )


def test_changed_bytes_schema_drift_and_traversal_are_rejected(
    tmp_path: Path,
) -> None:
    """Trusting unpinned, unsupported, or unconfined bytes breaks this test."""
    original = verified_fixture("late-fundamental.json")
    changed = original.data.replace(b'"1.20"', b'"1.21"', 1)
    changed_path = tmp_path / "changed-bytes.json"
    changed_path.write_bytes(changed)
    with pytest.raises(ArtifactIntegrityError):
        read_verified_local_artifact(
            tmp_path,
            changed_path.name,
            EXPECTED_HASHES["late-fundamental.json"],
            ResolverLimits(max_bytes=64_000),
        )

    def drift_schema(document: dict[str, Any]) -> None:
        document["schema_version"] = "2"

    with pytest.raises(DatasetValidationError, match="unsupported_fact_schema_version"):
        parse_synthetic_fact_bytes(
            _mutated_verified("late-fundamental.json", drift_schema)
        )
    with pytest.raises(ArtifactResolutionError):
        read_verified_local_artifact(
            FIXTURES,
            "../m1a/late-fundamental.json",
            EXPECTED_HASHES["late-fundamental.json"],
            ResolverLimits(max_bytes=64_000),
        )


@pytest.mark.parametrize(
    "mutation",
    ("raw_upper_bound", "rule_hash", "input_hash", "derived_instant"),
)
def test_derived_fixture_mutations_fail_closed(mutation: str) -> None:
    """Every independently forged derivation input or output is rejected."""

    def mutate(document: dict[str, Any]) -> None:
        raw, derived = cast(list[dict[str, Any]], document["fact_versions"])
        raw_evidence = cast(list[dict[str, Any]], raw["availability"])[0]
        derived_evidence = cast(list[dict[str, Any]], derived["availability"])[0]
        derivation = cast(dict[str, Any], derived_evidence["rule_derivation"])
        if mutation == "raw_upper_bound":
            raw_evidence["upper_bound"] = "2022-05-06T03:59:59Z"
            _rehash(raw)
        elif mutation == "rule_hash":
            reference = cast(dict[str, Any], derivation["rule_reference"])
            reference["content_hash"] = "f" * 64
            _rehash(derived)
        elif mutation == "input_hash":
            derivation["input_evidence_hash"] = "e" * 64
            _rehash(derived)
        else:
            derived_evidence["lower_bound"] = "2022-05-06T04:00:01Z"
            derived_evidence["upper_bound"] = "2022-05-06T04:00:01Z"
            _rehash(derived)

    verified = _mutated_verified("derived-upper-bound.json", mutate)
    try:
        versions = parse_synthetic_fact_bytes(verified)
    except DatasetValidationError:
        assert mutation == "rule_hash"
        return
    decision = validate_synthetic_fact_dataset(
        _manifest_for(verified, row_count=len(versions)),
        (verified,),
        _validation_context(),
    )
    assert decision.result is ValidationResult.FAIL
    assert {
        "rule_input_evidence_unavailable",
        "rule_derivation_not_reproducible",
    } & {finding.code for finding in decision.findings}


def test_lineage_mismatch_is_rejected() -> None:
    """Claiming derived bytes without complete lineage fails exact validation."""
    verified = verified_fixture("late-fundamental.json")
    manifest = _manifest_for(verified)
    forged = DatasetManifestV1.model_construct(
        **{
            **{
                name: getattr(manifest, name) for name in DatasetManifestV1.model_fields
            },
            "dataset_kind": DatasetKind.DERIVED_FACTS,
            "lineage": None,
        }
    )
    decision = validate_synthetic_fact_dataset(
        forged, (verified,), _validation_context()
    )
    assert decision.result is ValidationResult.FAIL
    assert "missing_derived_lineage" in {finding.code for finding in decision.findings}


def _uid(suffix: int) -> UUID:
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def _artifact(suffix: int, digest: str, location: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=_uid(suffix),
        kind=ArtifactKind.DATASET,
        content_hash=digest,
        location=location,
    )


def _manifest_for(
    verified: VerifiedArtifactBytes, *, row_count: int = 1
) -> DatasetManifestV1:
    fields = (
        FieldDescriptorV1(
            field_id="availability",
            name="availability",
            logical_type=LogicalType.JSON,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="fact_id",
            name="fact_id",
            logical_type=LogicalType.STRING,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="null_reason",
            name="null_reason",
            logical_type=LogicalType.STRING,
            nullable=True,
        ),
        FieldDescriptorV1(
            field_id="revision_id",
            name="revision_id",
            logical_type=LogicalType.STRING,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="source_sequence",
            name="source_sequence",
            logical_type=LogicalType.INTEGER,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="supersedes",
            name="supersedes",
            logical_type=LogicalType.STRING,
            nullable=True,
        ),
        FieldDescriptorV1(
            field_id="valid_end",
            name="valid_end",
            logical_type=LogicalType.DATETIME,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="valid_start",
            name="valid_start",
            logical_type=LogicalType.DATETIME,
            nullable=False,
        ),
        FieldDescriptorV1(
            field_id="value",
            name="value",
            logical_type=LogicalType.JSON,
            nullable=True,
        ),
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=fields, schema_hash="a" * 64
    )
    definition = SchemaDescriptorV1(
        schema_version="1",
        fields=fields,
        schema_hash=schema_hash(provisional),
    )
    partition = PartitionDescriptorV1(
        partition_id=_uid(910),
        partition_key="synthetic=fixture",
        artifact=_artifact(
            911,
            verified.content_hash,
            f"drift+sha256://{verified.content_hash}",
        ),
        byte_size=verified.byte_size,
        media_type="application/json",
        format_version="1",
        row_count=row_count,
        schema_hash=definition.schema_hash,
        coverage=TemporalCoverage(
            started_at=parse_utc("2022-01-01T00:00:00Z"),
            ended_at=parse_utc("2022-12-31T23:59:59Z"),
        ),
    )
    return DatasetManifestV1(
        dataset_id=_uid(900),
        dataset_version="fixture-1",
        dataset_kind=DatasetKind.SOURCE_FACTS,
        created_at=parse_utc("2026-09-01T12:00:00Z"),
        source=SourceDescriptorV1(
            source_id="synthetic-source",
            publisher="Synthetic Publisher",
            product="Synthetic Facts",
            evidence_reference=_artifact(912, "a" * 64, "evidence:source"),
        ),
        acquisition=AcquisitionDescriptorV1(
            acquired_at=parse_utc("2026-09-01T12:00:00Z"),
            collector_id="fixture-collector",
            collector_version="1",
            evidence_reference=_artifact(913, "b" * 64, "evidence:acquisition"),
        ),
        license=LicenseDescriptorV1(
            provider_legal_name="Synthetic Publisher",
            license_reference="synthetic-reference",
            acquired_at=parse_utc("2026-09-01T12:00:00Z"),
            terms_evidence_reference=_artifact(914, "c" * 64, "evidence:terms"),
        ),
        schema_definition=definition,
        partitions=(partition,),
        temporal_contract=RecordTemporalContractV1(
            logical_key_field_ids=("fact_id",),
            valid_start_field_id="valid_start",
            valid_end_field_id="valid_end",
            availability_field_id="availability",
            revision_id_field_id="revision_id",
            supersedes_field_id="supersedes",
            source_sequence_field_id="source_sequence",
            value_field_id="value",
            null_reason_field_id="null_reason",
            declared_channels=tuple(
                sorted(
                    {
                        evidence.channel
                        for version in parse_synthetic_fact_bytes(verified)
                        for evidence in version.availability
                    },
                    key=lambda channel: (
                        channel.kind.value,
                        channel.identifier,
                        channel.version or "",
                    ),
                )
            ),
        ),
    )


def _validation_context() -> ValidationRunContextV1:
    return ValidationRunContextV1(
        decision_id=_uid(920),
        validator_version="1",
        validator_implementation_hash="d" * 64,
        validation_profile_id="m1a-adversarial-v1",
        validation_profile_hash="e" * 64,
        checked_at=parse_utc("2026-09-01T12:30:00Z"),
    )
