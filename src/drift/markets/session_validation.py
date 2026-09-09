"""Exact-byte structural validation for immutable M1d session datasets."""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Protocol

from pydantic import BaseModel, ValidationError

from drift.datasets.assertions import (
    validate_assertion_chain,
    validate_manifest_v2_structure,
)
from drift.datasets.hashing import assertion_version_payload, manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import AssertionVersionProjectionV1
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
    EvidenceGranularity,
    FieldDescriptorV1,
    LogicalType,
    SchemaDescriptorV1,
)
from drift.domain.observation_query import m1d_implementation_hash
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SessionCoverageVersionV1,
    SessionInputRecordV1,
)
from drift.domain.temporal import AvailabilityChannelV1
from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import canonical_json, content_hash

SESSION_VALIDATION_PROFILE_ID = "m1d-session-v1"
_SESSION_VALIDATION_PROFILE_SPEC = {
    "schema_version": "1",
    "profile_id": SESSION_VALIDATION_PROFILE_ID,
    "roles": ("realized_session", "scheduled_session", "session_coverage"),
    "checks": (
        "exact_partition_bytes",
        "exact_role_schema",
        "exact_temporal_contract",
        "exact_typed_document",
        "complete_revision_chains",
        "source_ownership",
        "supporting_artifact_closure",
    ),
}

_BOUND_REVISION_FIELDS = (
    "revision.logical_record_id",
    "revision.record_version_id",
    "revision.revision_kind",
    "revision.supersedes_record_version_id",
    "revision.source_sequence",
    "revision.availability",
    "revision.source_artifact",
    "revision.payload_hash",
)

_SHARED_REVISION_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "schema_version": (LogicalType.STRING, False),
    "revision.schema_version": (LogicalType.STRING, False),
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

_ROLE_FIELDS: Mapping[str, Mapping[str, tuple[LogicalType, bool]]] = MappingProxyType(
    {
        "scheduled_session": {
            **_SHARED_REVISION_FIELDS,
            "source_id": (LogicalType.STRING, False),
            "session_key": (LogicalType.JSON, False),
            "source_temporal_evidence": (LogicalType.JSON, False),
            "state": (LogicalType.STRING, False),
            "local_open": (LogicalType.STRING, True),
            "local_close": (LogicalType.STRING, True),
            "timezone_identifier": (LogicalType.STRING, False),
            "open_fold": (LogicalType.INTEGER, True),
            "close_fold": (LogicalType.INTEGER, True),
            "historical_boundary_offsets": (LogicalType.JSON, False),
            "source_methodology_hash": (LogicalType.STRING, False),
        },
        "realized_session": {
            **_SHARED_REVISION_FIELDS,
            "source_id": (LogicalType.STRING, False),
            "session_key": (LogicalType.JSON, False),
            "outcome": (LogicalType.STRING, False),
            "actual_open": (LogicalType.DATETIME, True),
            "actual_close": (LogicalType.DATETIME, True),
            "reported_as_scheduled": (LogicalType.STRING, False),
            "late_open": (LogicalType.STRING, False),
            "early_close": (LogicalType.STRING, False),
            "interruption_intervals": (LogicalType.JSON, False),
            "interruption_coverage": (LogicalType.STRING, False),
            "source_evidence_hashes": (LogicalType.JSON, False),
            "methodology_hashes": (LogicalType.JSON, False),
            "compared_schedule_hash": (LogicalType.STRING, True),
        },
        "session_coverage": {
            **_SHARED_REVISION_FIELDS,
            "source_id": (LogicalType.STRING, False),
            "native_record_id": (LogicalType.STRING, False),
            "mic": (LogicalType.STRING, False),
            "session_scope": (LogicalType.STRING, False),
            "start_date": (LogicalType.DATE, False),
            "end_date": (LogicalType.DATE, False),
            "snapshot_identifier": (LogicalType.STRING, False),
            "snapshot_as_of": (LogicalType.JSON, False),
            "covered_dataset_hashes": (LogicalType.JSON, False),
            "covered_partition_hashes": (LogicalType.JSON, False),
            "record_inventory": (LogicalType.JSON, False),
            "expected_daily_cardinality": (LogicalType.INTEGER, False),
            "exception_dates": (LogicalType.JSON, False),
            "methodology_hash": (LogicalType.STRING, False),
            "status": (LogicalType.STRING, False),
            "missing_artifact_hashes": (LogicalType.JSON, False),
            "revision_history_completeness": (LogicalType.STRING, False),
        },
    }
)

_EFFECTIVE_FIELDS = MappingProxyType(
    {
        "scheduled_session": "source_temporal_evidence",
        "realized_session": "actual_close",
        "session_coverage": "snapshot_as_of",
    }
)


class _SessionDatasetInput(Protocol):
    @property
    def manifest(self) -> DatasetManifestV2: ...

    @property
    def artifacts(self) -> Mapping[str, VerifiedArtifactBytes]: ...

    @property
    def records(self) -> tuple[SessionInputRecordV1, ...]: ...


def session_validation_profile_hash() -> str:
    """Return the immutable session-validation profile identity."""
    return content_hash(_SESSION_VALIDATION_PROFILE_SPEC)


def session_validator_implementation_hash() -> str:
    """Return the installed package inventory identity."""
    return m1d_implementation_hash()


def session_role_schema(role: str) -> SchemaDescriptorV1:
    """Return the closed schema for one of the three session roles."""
    try:
        expected = _ROLE_FIELDS[role]
    except KeyError as error:
        raise ValueError(f"unsupported session role: {role}") from error
    fields = tuple(
        sorted(
            (
                FieldDescriptorV1(
                    field_id=name,
                    name=name,
                    logical_type=logical_type,
                    nullable=nullable,
                )
                for name, (logical_type, nullable) in expected.items()
            ),
            key=lambda item: item.field_id,
        )
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=fields, schema_hash="0" * 64
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=fields, schema_hash=schema_hash(provisional)
    )


def session_role_contract(
    role: str, channels: tuple[AvailabilityChannelV1, ...]
) -> AssertionTemporalContractV1:
    """Bind one session role to its exact assertion temporal contract."""
    try:
        fields = _ROLE_FIELDS[role]
        effective_field = _EFFECTIVE_FIELDS[role]
    except KeyError as error:
        raise ValueError(f"unsupported session role: {role}") from error
    semantic = tuple(
        sorted(
            name
            for name in fields
            if name not in _BOUND_REVISION_FIELDS and name != effective_field
        )
    )
    return AssertionTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_record_id_field_id="revision.logical_record_id",
        record_version_id_field_id="revision.record_version_id",
        revision_kind_field_id="revision.revision_kind",
        supersedes_field_id="revision.supersedes_record_version_id",
        source_sequence_field_id="revision.source_sequence",
        availability_field_id="revision.availability",
        source_artifact_field_id="revision.source_artifact",
        payload_hash_field_id="revision.payload_hash",
        effective_time_field_id=effective_field,
        effective_shape=AssertionEffectiveShape.BOUNDARY,
        semantic_state_field_ids=semantic,
        declared_channels=channels,
    )


def validate_session_dataset(
    manifest: DatasetManifestV2,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    run: ValidationRunContextV1,
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes],
) -> tuple[DatasetValidationDecisionV2, tuple[SessionInputRecordV1, ...]]:
    """Validate exact session partitions while retaining source claims as stated."""
    artifact_snapshot = MappingProxyType(dict(artifacts))
    support_snapshot = MappingProxyType(dict(supporting_artifacts))
    findings = [
        *_artifact_mapping_findings(artifact_snapshot, "session_artifact"),
        *_artifact_mapping_findings(support_snapshot, "session_supporting_artifact"),
    ]
    verified = tuple(artifact_snapshot[key] for key in sorted(artifact_snapshot))
    structure = validate_manifest_v2_structure(manifest, verified, run)
    if structure.result is ValidationResult.FAIL:
        return structure, ()
    role = manifest.dataset_role.name
    try:
        expected_schema = session_role_schema(role)
        expected_contract = session_role_contract(
            role, manifest.temporal_contract.contract.declared_channels
        )
    except AttributeError, ValueError:
        findings.append(_finding("unsupported_session_dataset_role"))
        return _final_decision(structure, findings, (), role)
    if (
        run.validator_version,
        run.validator_implementation_hash,
        run.validation_profile_id,
        run.validation_profile_hash,
    ) != (
        "1",
        session_validator_implementation_hash(),
        SESSION_VALIDATION_PROFILE_ID,
        session_validation_profile_hash(),
    ):
        findings.append(_finding("session_validation_run_mismatch"))
    if (
        manifest.dataset_role.namespace != "drift"
        or manifest.dataset_role.version != "1"
    ):
        findings.append(_finding("session_dataset_role_mismatch"))
    if manifest.schema_definition != expected_schema:
        findings.append(_finding("session_role_schema_mismatch"))
    if manifest.temporal_contract.contract != expected_contract:
        findings.append(_finding("session_role_contract_mismatch"))
    if _has_unsupported_consumed_raw_precision(verified):
        findings.append(_finding("session_unsupported_raw_temporal_precision"))
        return _final_decision(structure, findings, (), role)
    records: list[SessionInputRecordV1] = []
    for partition in manifest.partitions:
        artifact = artifact_snapshot.get(partition.artifact.content_hash)
        if artifact is None:
            continue
        try:
            records.extend(parse_session_document(artifact.data, role))
        except DatasetValidationError as error:
            findings.extend(error.findings)
    parsed = tuple(records)
    if len(parsed) != sum(item.row_count for item in manifest.partitions):
        findings.append(_finding("session_row_count_mismatch"))
    if len({content_hash(item) for item in parsed}) != len(parsed):
        findings.append(_finding("duplicate_session_record_hash"))
    declared_channels = set(manifest.temporal_contract.contract.declared_channels)
    for record in parsed:
        if record.source_id != manifest.source.source_id:
            findings.append(_finding("session_source_id_mismatch"))
        if any(
            evidence.channel not in declared_channels
            for evidence in record.revision.availability
        ):
            findings.append(_finding("session_undeclared_availability_channel"))
    findings.extend(_record_ownership_findings(parsed, role))
    findings.extend(_supporting_closure_findings(manifest, parsed, support_snapshot))
    return _final_decision(structure, findings, parsed, role)


def parse_session_document(data: bytes, role: str) -> tuple[SessionInputRecordV1, ...]:
    """Parse canonical bytes through only the manifest role's closed model."""
    if role not in {"scheduled_session", "realized_session", "session_coverage"}:
        raise DatasetValidationError.single("unsupported_session_dataset_role")
    try:
        document = _strict_json_loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKeyError) as error:
        raise DatasetValidationError.single("session_dataset_invalid_json") from error
    if canonical_json(document) != data:
        raise DatasetValidationError.single("session_dataset_noncanonical_json")
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "records"}
        or document.get("schema_version") != "1"
        or not isinstance(document.get("records"), list)
    ):
        raise DatasetValidationError.single("session_dataset_invalid_envelope")
    parsed: list[SessionInputRecordV1] = []
    for raw in document["records"]:
        try:
            encoded = canonical_json(raw)
            if role == "scheduled_session":
                record: SessionInputRecordV1 = (
                    ScheduledSessionVersionV1.model_validate_json(encoded)
                )
            elif role == "realized_session":
                record = RealizedSessionVersionV1.model_validate_json(encoded)
            else:
                record = SessionCoverageVersionV1.model_validate_json(encoded)
        except (CanonicalSerializationError, TypeError, ValidationError) as error:
            raise DatasetValidationError.single("session_record_invalid") from error
        if record.revision.payload_hash != content_hash(
            assertion_version_payload(record)
        ):
            raise DatasetValidationError.single("session_payload_hash_mismatch")
        parsed.append(record)
    return tuple(parsed)


def validate_session_coverage_inventories(
    datasets: Sequence[_SessionDatasetInput],
) -> None:
    """Verify dense coverage claims against exact retained schedule bytes."""
    candidates = tuple(datasets)
    by_manifest_hash = {manifest_hash(item.manifest): item for item in candidates}
    for coverage_dataset in candidates:
        for record in coverage_dataset.records:
            if not isinstance(record, SessionCoverageVersionV1):
                continue
            targets = []
            for digest in record.covered_dataset_hashes:
                target = by_manifest_hash.get(digest)
                if (
                    target is None
                    or target.manifest.dataset_role.name != "scheduled_session"
                ):
                    raise DatasetValidationError.single(
                        "session_coverage_target_manifest_missing"
                    )
                targets.append(target)
            expected_partitions = tuple(
                sorted(digest for target in targets for digest in target.artifacts)
            )
            rows = tuple(
                item
                for target in targets
                for item in target.records
                if isinstance(item, ScheduledSessionVersionV1)
            )
            expected_inventory = tuple(
                sorted(
                    (
                        item.revision.logical_record_id,
                        item.revision.record_version_id,
                        content_hash(item),
                    )
                    for item in rows
                )
            )
            actual_inventory = tuple(
                (item.assertion_id, item.version_id, item.record_hash)
                for item in record.record_inventory
            )
            if (
                record.covered_partition_hashes != expected_partitions
                or actual_inventory != expected_inventory
            ):
                raise DatasetValidationError.single(
                    "session_coverage_inventory_mismatch"
                )
            for row in rows:
                if (
                    row.source_id != record.source_id
                    or row.session_key.mic != record.mic
                    or row.session_key.session_scope != record.session_scope
                    or not (
                        record.start_date
                        <= row.session_key.local_date
                        <= record.end_date
                    )
                    or row.source_methodology_hash != record.methodology_hash
                ):
                    raise DatasetValidationError.single(
                        "session_coverage_scope_mismatch"
                    )
            if record.status == "expected_complete":
                current = record.start_date
                while current <= record.end_date:
                    logical_ids = {
                        row.revision.logical_record_id
                        for row in rows
                        if row.session_key.local_date == current
                    }
                    if len(logical_ids) != record.expected_daily_cardinality:
                        raise DatasetValidationError.single(
                            "session_coverage_daily_cardinality_mismatch"
                        )
                    current += timedelta(days=1)


def _record_ownership_findings(
    records: Sequence[SessionInputRecordV1], role: str
) -> tuple[ValidationFindingV1, ...]:
    by_logical: dict[object, list[SessionInputRecordV1]] = defaultdict(list)
    keys_by_logical: dict[object, set[tuple[object, ...]]] = defaultdict(set)
    logical_by_key: dict[tuple[object, ...], set[object]] = defaultdict(set)
    version_hashes: dict[object, set[str]] = defaultdict(set)
    for record in records:
        logical = record.revision.logical_record_id
        by_logical[logical].append(record)
        if isinstance(record, SessionCoverageVersionV1):
            key: tuple[object, ...] = (
                role,
                record.source_id,
                record.native_record_id,
            )
        else:
            key = (
                role,
                record.source_id,
                record.session_key.mic,
                record.session_key.session_scope,
                record.session_key.local_date,
            )
        keys_by_logical[logical].add(key)
        logical_by_key[key].add(logical)
        version_hashes[record.revision.record_version_id].add(content_hash(record))
    findings: list[ValidationFindingV1] = []
    if any(len(items) > 1 for items in keys_by_logical.values()):
        findings.append(_finding("session_logical_record_multiple_source_keys"))
    if any(len(items) > 1 for items in logical_by_key.values()):
        findings.append(_finding("session_source_key_multiple_logical_records"))
    if any(len(items) > 1 for items in version_hashes.values()):
        findings.append(_finding("session_conflicting_record_version"))
    for versions in by_logical.values():
        findings.extend(
            validate_assertion_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=item.revision, record_hash=content_hash(item)
                    )
                    for item in versions
                )
            )
        )
    return _canonical_findings(findings)


def _supporting_closure_findings(
    manifest: DatasetManifestV2,
    records: Sequence[SessionInputRecordV1],
    supporting: Mapping[str, VerifiedArtifactBytes],
) -> tuple[ValidationFindingV1, ...]:
    required = {
        manifest.source.evidence_reference.content_hash,
        manifest.acquisition.evidence_reference.content_hash,
        manifest.license.terms_evidence_reference.content_hash,
    }
    for record in records:
        required.update(
            reference.content_hash for reference in _artifact_references(record)
        )
        required.add(record.revision.source_artifact.content_hash)
        if isinstance(record, ScheduledSessionVersionV1):
            required.add(record.source_methodology_hash)
            for offset in record.historical_boundary_offsets:
                if offset.methodology_encoding_hash is not None:
                    required.add(offset.methodology_encoding_hash)
                if offset.authority_artifact_hash is not None:
                    required.add(offset.authority_artifact_hash)
        elif isinstance(record, RealizedSessionVersionV1):
            required.update(record.source_evidence_hashes)
            required.update(record.methodology_hashes)
        else:
            required.add(record.methodology_hash)
    partitions = {item.artifact.content_hash for item in manifest.partitions}
    if required & partitions:
        return (_finding("session_partition_self_reference"),)
    if required - set(supporting):
        return (_finding("session_missing_supporting_artifact"),)
    return ()


def _artifact_references(value: object) -> tuple[ArtifactReference, ...]:
    references: list[ArtifactReference] = []

    def visit(item: object) -> None:
        if isinstance(item, ArtifactReference):
            references.append(item)
        elif isinstance(item, BaseModel):
            for name in type(item).model_fields:
                visit(getattr(item, name))
        elif isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, tuple | list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(references)


def _has_unsupported_consumed_raw_precision(
    partitions: Iterable[VerifiedArtifactBytes],
) -> bool:
    for artifact in partitions:
        try:
            document = _strict_json_loads(artifact.data)
        except UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKeyError:
            continue
        if not isinstance(document, dict) or not isinstance(
            document.get("records"), list
        ):
            continue
        for record in document["records"]:
            if not isinstance(record, dict):
                continue
            revision = record.get("revision")
            if isinstance(revision, dict) and _raw_availability_has_bad_precision(
                revision.get("availability")
            ):
                return True
            for field in ("source_temporal_evidence", "snapshot_as_of"):
                if _raw_boundary_has_bad_precision(record.get(field)):
                    return True
            for field in ("interruption_intervals",):
                value = record.get(field)
                if isinstance(value, list) and any(
                    _raw_interval_has_bad_precision(item) for item in value
                ):
                    return True
    return False


def _raw_availability_has_bad_precision(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, dict) and item.get("precision") in {"date", "minute"}
        for item in value
    )


def _raw_boundary_has_bad_precision(value: object) -> bool:
    return isinstance(value, dict) and value.get("source_precision") in {
        "date",
        "minute",
    }


def _raw_interval_has_bad_precision(value: object) -> bool:
    return isinstance(value, dict) and any(
        _raw_boundary_has_bad_precision(value.get(name)) for name in ("start", "end")
    )


class _DuplicateJSONKeyError(ValueError):
    pass


def _strict_json_loads(data: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJSONKeyError(key)
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=reject_duplicates)


def _artifact_mapping_findings(
    artifacts: Mapping[str, VerifiedArtifactBytes], prefix: str
) -> tuple[ValidationFindingV1, ...]:
    findings: list[ValidationFindingV1] = []
    for key, artifact in artifacts.items():
        if key != artifact.content_hash:
            findings.append(_finding(f"{prefix}_mapping_key_mismatch"))
        if artifact.byte_size != len(artifact.data):
            findings.append(_finding(f"{prefix}_size_mismatch"))
        if sha256(artifact.data).hexdigest() != artifact.content_hash:
            findings.append(_finding(f"{prefix}_hash_mismatch"))
    return _canonical_findings(findings)


def _final_decision(
    structure: DatasetValidationDecisionV2,
    findings: Sequence[ValidationFindingV1],
    records: Sequence[SessionInputRecordV1],
    role: str,
) -> tuple[DatasetValidationDecisionV2, tuple[SessionInputRecordV1, ...]]:
    canonical = _canonical_findings(findings)
    passed = not canonical
    record_hashes = tuple(sorted({content_hash(item) for item in records}))
    checked = list(structure.checked_contracts)
    if passed:
        marker = role.replace("_", "-") + "-v1"
        checked.append(marker)
        if not records:
            checked.append(marker + "-exact-empty")
    decision = structure.model_copy(
        update={
            "validation_scope": (
                ValidationScope.RECORDS
                if passed and record_hashes
                else ValidationScope.MANIFEST_ONLY
            ),
            "result": ValidationResult.PASS if passed else ValidationResult.FAIL,
            "validated_record_hashes": record_hashes if passed else (),
            "checked_contracts": tuple(sorted(set(checked))),
            "findings": canonical,
        }
    )
    return decision, tuple(records) if passed else ()


def _finding(code: str) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code, severity=FindingSeverity.ERROR, message=code.replace("_", " ")
    )


def _canonical_findings(
    findings: Iterable[ValidationFindingV1],
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        sorted(
            set(findings),
            key=lambda item: (
                item.code,
                item.severity.value,
                item.message,
                tuple(ref.content_hash for ref in item.artifact_references),
            ),
        )
    )
