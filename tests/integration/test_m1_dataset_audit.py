"""Integration tests for compact M1a dataset audit-event drafts."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from drift.datasets.events import (
    build_manifest_recorded_event,
    build_validation_completed_event,
)
from drift.datasets.hashing import manifest_hash, schema_hash
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationError,
    ValidationResult,
    ValidationScope,
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
from drift.domain.temporal import (
    AvailabilityChannelV1,
    ChannelKind,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import content_hash


def uid(suffix: int) -> UUID:
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
PUBLIC = AvailabilityChannelV1(
    kind=ChannelKind.PUBLIC, identifier="synthetic-public", version="1"
)


def artifact(
    suffix: int,
    digest: str,
    *,
    kind: ArtifactKind = ArtifactKind.OTHER,
    location: str = "evidence:synthetic",
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uid(suffix),
        kind=kind,
        content_hash=digest,
        location=location,
    )


FIELDS = (
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
PROVISIONAL_SCHEMA = SchemaDescriptorV1.model_construct(
    schema_version="1", fields=FIELDS, schema_hash="a" * 64
)
SCHEMA = SchemaDescriptorV1(
    schema_version="1",
    fields=FIELDS,
    schema_hash=schema_hash(PROVISIONAL_SCHEMA),
)
PARTITION = PartitionDescriptorV1(
    partition_id=uid(301),
    partition_key="synthetic=fixture",
    artifact=artifact(
        302,
        "d" * 64,
        kind=ArtifactKind.DATASET,
        location=f"drift+sha256://{'d' * 64}",
    ),
    byte_size=1024,
    media_type="application/json",
    format_version="1",
    row_count=1,
    schema_hash=SCHEMA.schema_hash,
    coverage=TemporalCoverage(
        started_at=datetime(2022, 1, 1, tzinfo=UTC),
        ended_at=datetime(2022, 12, 31, tzinfo=UTC),
    ),
)
MANIFEST = DatasetManifestV1(
    dataset_id=uid(300),
    dataset_version="synthetic-1",
    dataset_kind=DatasetKind.SOURCE_FACTS,
    created_at=NOW,
    source=SourceDescriptorV1(
        source_id="synthetic-source",
        publisher="Synthetic Publisher",
        product="Synthetic Facts",
        evidence_reference=artifact(303, "a" * 64),
    ),
    acquisition=AcquisitionDescriptorV1(
        acquired_at=NOW,
        collector_id="fixture-collector",
        collector_version="1",
        evidence_reference=artifact(304, "b" * 64),
    ),
    license=LicenseDescriptorV1(
        provider_legal_name="Synthetic Publisher",
        license_reference="private fixture terms that must stay out of SQLite",
        acquired_at=NOW,
        terms_evidence_reference=artifact(305, "c" * 64),
    ),
    schema_definition=SCHEMA,
    partitions=(PARTITION,),
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
        declared_channels=(PUBLIC,),
    ),
)
MANIFEST_REFERENCE = artifact(
    306,
    manifest_hash(MANIFEST),
    kind=ArtifactKind.DATASET,
    location="local/private/manifest.json",
)
DECISION = DatasetValidationDecisionV1(
    decision_id=uid(400),
    manifest_hash=manifest_hash(MANIFEST),
    validator_version="1",
    validator_implementation_hash="e" * 64,
    validation_profile_id="m1a-synthetic-facts-v1",
    validation_profile_hash="f" * 64,
    checked_at=datetime(2026, 9, 1, 12, 30, tzinfo=UTC),
    validation_scope=ValidationScope.RECORDS,
    result=ValidationResult.PASS,
    validated_artifact_hashes=("d" * 64,),
    validated_record_hashes=("1" * 64,),
    checked_contracts=("dataset-manifest-v1", "record-temporal-v1"),
    findings=(),
)


def test_dataset_factories_return_unhashed_drafts_and_ledger_assigns_hashes(
    tmp_path: Path,
) -> None:
    """Calling a factory must not precompute or inject ledger chain hashes."""
    manifest_draft = build_manifest_recorded_event(MANIFEST, MANIFEST_REFERENCE)
    validation_draft = build_validation_completed_event(MANIFEST, DECISION)
    assert isinstance(manifest_draft, AuditEventDraft)
    assert isinstance(validation_draft, AuditEventDraft)
    assert "previous_event_hash" not in type(manifest_draft).model_fields
    assert "event_hash" not in type(manifest_draft).model_fields

    ledger = SQLiteLedger(tmp_path / "ledger.sqlite3")
    manifest_event = ledger.append(manifest_draft)
    validation_event = ledger.append(validation_draft)
    assert validation_event.previous_event_hash == manifest_event.event_hash
    ledger.verify_chain()


def test_manifest_recorded_draft_is_content_bound_and_compact() -> None:
    """Dropping a manifest identity field or persisting a locator breaks this test."""
    draft = build_manifest_recorded_event(MANIFEST, MANIFEST_REFERENCE)
    assert draft.event_id == MANIFEST_REFERENCE.artifact_id
    assert draft.event_type == "dataset.manifest.recorded"
    assert draft.timestamp == MANIFEST.created_at
    assert draft.entity_type == "dataset_manifest"
    assert draft.entity_id == MANIFEST.dataset_id
    assert draft.payload == {
        "manifest_id": str(MANIFEST_REFERENCE.artifact_id),
        "manifest_hash": manifest_hash(MANIFEST),
        "hash_profile": "drift-canonical-json-sha256-v1",
        "schema_version": "1",
    }
    assert draft.schema_version == "1"


def test_manifest_recorded_draft_rejects_wrong_reference_kind_or_hash() -> None:
    """Recording an unbound manifest reference must fail before ledger append."""
    with pytest.raises(DatasetValidationError, match="manifest_artifact_kind"):
        build_manifest_recorded_event(
            MANIFEST,
            MANIFEST_REFERENCE.model_copy(update={"kind": ArtifactKind.OTHER}),
        )
    with pytest.raises(DatasetValidationError, match="manifest_hash_mismatch"):
        build_manifest_recorded_event(
            MANIFEST,
            MANIFEST_REFERENCE.model_copy(update={"content_hash": "0" * 64}),
        )


def test_validation_completed_draft_records_only_exact_decision_summary() -> None:
    """Adding a cutoff permission or omitting a decision binding breaks this test."""
    draft = build_validation_completed_event(MANIFEST, DECISION)
    assert draft.event_id == DECISION.decision_id
    assert draft.event_type == "dataset.validation.completed"
    assert draft.timestamp == DECISION.checked_at
    assert draft.entity_type == "dataset_manifest"
    assert draft.entity_id == MANIFEST.dataset_id
    assert draft.payload == {
        "manifest_hash": DECISION.manifest_hash,
        "decision_hash": content_hash(DECISION),
        "result": "pass",
        "validation_scope": "records",
    }
    assert draft.schema_version == "1"


def test_sqlite_payloads_exclude_bytes_paths_license_and_cutoff_permissions(
    tmp_path: Path,
) -> None:
    """Persisting bulky or query-specific data in either event breaks this test."""
    path = tmp_path / "ledger.sqlite3"
    ledger = SQLiteLedger(path)
    ledger.append(build_manifest_recorded_event(MANIFEST, MANIFEST_REFERENCE))
    ledger.append(build_validation_completed_event(MANIFEST, DECISION))
    with sqlite3.connect(path) as connection:
        payloads = tuple(
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM audit_events ORDER BY sequence"
            )
        )
    assert payloads == (
        {
            "hash_profile": "drift-canonical-json-sha256-v1",
            "manifest_hash": manifest_hash(MANIFEST),
            "manifest_id": str(MANIFEST_REFERENCE.artifact_id),
            "schema_version": "1",
        },
        {
            "decision_hash": content_hash(DECISION),
            "manifest_hash": DECISION.manifest_hash,
            "result": "pass",
            "validation_scope": "records",
        },
    )
    stored = json.dumps(payloads, sort_keys=True)
    for forbidden in (
        "local/private/manifest.json",
        "private fixture terms",
        "raw_bytes",
        "cutoff",
        "eligible",
        "permission",
    ):
        assert forbidden not in stored
