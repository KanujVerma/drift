"""Pinned M0 serialization compatibility across the provenance-only M1 bridge."""

from datetime import UTC, datetime
from uuid import UUID

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.datasets import DatasetReference, TemporalCoverage
from drift.domain.events import UnsignedAuditEvent
from drift.ledger.hashing import GENESIS_HASH, compute_event_hash
from drift.serialization.canonical import canonical_json

M0_REFERENCE_BYTES = (
    b'{"availability_timestamp_policy":"source timestamp",'
    b'"content_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    b'aaaaaaaaaaaaaaaa","corporate_action_policy":"not applicable",'
    b'"created_at":"2026-09-01T12:00:00.000000Z",'
    b'"dataset_id":"019b8240-0000-7000-8000-000000000101",'
    b'"dataset_version":"m0-fixture-1","manifest_reference":{'
    b'"artifact_id":"019b8240-0000-7000-8000-000000000102",'
    b'"content_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    b'aaaaaaaaaaaaaaaa","kind":"dataset",'
    b'"location":"artifacts/m0-dataset.json"},'
    b'"point_in_time_policy":"explicit snapshot","schema_version":"1",'
    b'"source":"synthetic-m0","temporal_coverage":{'
    b'"ended_at":"2020-12-31T00:00:00.000000Z",'
    b'"started_at":"2020-01-01T00:00:00.000000Z"}}'
)
M0_EVENT_HASH = "0106cd8ed30151ffe1f55ca4923df83d4fb86a6ccd45d45641c6fbb171eaea53"


def existing_m0_dataset_reference() -> DatasetReference:
    return DatasetReference(
        dataset_id=UUID("019b8240-0000-7000-8000-000000000101"),
        dataset_version="m0-fixture-1",
        schema_version="1",
        content_hash="a" * 64,
        created_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        source="synthetic-m0",
        temporal_coverage=TemporalCoverage(
            started_at=datetime(2020, 1, 1, tzinfo=UTC),
            ended_at=datetime(2020, 12, 31, tzinfo=UTC),
        ),
        point_in_time_policy="explicit snapshot",
        corporate_action_policy="not applicable",
        availability_timestamp_policy="source timestamp",
        manifest_reference=ArtifactReference(
            artifact_id=UUID("019b8240-0000-7000-8000-000000000102"),
            kind=ArtifactKind.DATASET,
            content_hash="a" * 64,
            location="artifacts/m0-dataset.json",
        ),
    )


def existing_m0_unsigned_event() -> UnsignedAuditEvent:
    reference = existing_m0_dataset_reference()
    return UnsignedAuditEvent(
        event_id=UUID("019b8240-0000-7000-8000-000000000103"),
        event_type="dataset.recorded",
        timestamp=datetime(2026, 9, 1, 12, tzinfo=UTC),
        entity_type="dataset",
        entity_id=reference.dataset_id,
        payload={"dataset_hash": reference.content_hash, "status": "recorded"},
        previous_event_hash=GENESIS_HASH,
        deduplication_key="m0-fixture",
        schema_version="1",
    )


def test_m0_fixture_serialization_and_event_hashes_are_unchanged() -> None:
    assert canonical_json(existing_m0_dataset_reference()) == M0_REFERENCE_BYTES
    assert compute_event_hash(existing_m0_unsigned_event()) == M0_EVENT_HASH
