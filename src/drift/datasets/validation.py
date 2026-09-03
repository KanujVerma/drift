"""Fail-closed exact-object validation for synthetic M1a fact datasets."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from hashlib import sha256
from typing import Literal

from pydantic import ValidationError

from drift.datasets.hashing import manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes, verify_partition_bytes
from drift.domain.common import FrozenModel
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV1,
    DatasetValidationError,
    FindingSeverity,
    ValidationFindingV1,
    ValidationResult,
    ValidationRunContextV1,
    ValidationScope,
)
from drift.domain.manifests import (
    DatasetKind,
    DatasetManifestV1,
    EvidenceGranularity,
    FieldDescriptorV1,
    LogicalType,
    PartitionDescriptorV1,
    RecordTemporalContractV1,
    SchemaDescriptorV1,
)
from drift.domain.revisions import FactVersionV1, validate_revision_chain
from drift.domain.temporal import (
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    derive_conservative_upper_bound,
)
from drift.errors import ArtifactIntegrityError
from drift.serialization.canonical import content_hash

_MANIFEST_CONTRACT = "dataset-manifest-v1"
_RECORD_CONTRACT = "record-temporal-v1"
_SUPPORTED_VALIDATOR_VERSION = "1"
_SYNTHETIC_FACT_SCHEMA_HASH_V1 = (
    "aa0b033243bd749e2312353bf6434a79b34825e2a06af8a709890e2fb2dbfe7c"
)

_SYNTHETIC_FACT_FIELDS_V1 = (
    FieldDescriptorV1(
        field_id="availability",
        name="availability",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="fact_version_id",
        name="fact_version_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.concept",
        name="logical_key.concept",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.dimensions",
        name="logical_key.dimensions",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.entity_key",
        name="logical_key.entity_key",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.source_id",
        name="logical_key.source_id",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.unit",
        name="logical_key.unit",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.valid_period.ended_at",
        name="logical_key.valid_period.ended_at",
        logical_type=LogicalType.DATETIME,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="logical_key.valid_period.started_at",
        name="logical_key.valid_period.started_at",
        logical_type=LogicalType.DATETIME,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="null_reason",
        name="null_reason",
        logical_type=LogicalType.STRING,
        nullable=True,
    ),
    FieldDescriptorV1(
        field_id="payload_hash",
        name="payload_hash",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="revision_kind",
        name="revision_kind",
        logical_type=LogicalType.STRING,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="source_artifact",
        name="source_artifact",
        logical_type=LogicalType.JSON,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="source_sequence",
        name="source_sequence",
        logical_type=LogicalType.INTEGER,
        nullable=False,
    ),
    FieldDescriptorV1(
        field_id="supersedes_fact_version_id",
        name="supersedes_fact_version_id",
        logical_type=LogicalType.STRING,
        nullable=True,
    ),
    FieldDescriptorV1(
        field_id="value",
        name="value",
        logical_type=LogicalType.JSON,
        nullable=True,
    ),
)

SYNTHETIC_FACT_SCHEMA_V1 = SchemaDescriptorV1(
    schema_version="1",
    fields=_SYNTHETIC_FACT_FIELDS_V1,
    schema_hash=_SYNTHETIC_FACT_SCHEMA_HASH_V1,
)


def synthetic_fact_temporal_contract_v1(
    declared_channels: tuple[AvailabilityChannelV1, ...],
) -> RecordTemporalContractV1:
    """Return the sole temporal binding for serialized ``FactVersionV1`` data."""
    return RecordTemporalContractV1(
        contract_version="1",
        evidence_granularity=EvidenceGranularity.RECORD,
        logical_key_field_ids=(
            "logical_key.source_id",
            "logical_key.entity_key",
            "logical_key.concept",
            "logical_key.valid_period.started_at",
            "logical_key.valid_period.ended_at",
            "logical_key.unit",
            "logical_key.dimensions",
        ),
        valid_start_field_id="logical_key.valid_period.started_at",
        valid_end_field_id="logical_key.valid_period.ended_at",
        availability_field_id="availability",
        revision_id_field_id="fact_version_id",
        supersedes_field_id="supersedes_fact_version_id",
        source_sequence_field_id="source_sequence",
        value_field_id="value",
        null_reason_field_id="null_reason",
        declared_channels=declared_channels,
    )


class _SyntheticFactDocumentV1(FrozenModel):
    """Strict versioned envelope for retained synthetic fact bytes."""

    schema_version: Literal["1"]
    fact_versions: tuple[FactVersionV1, ...]


def validate_fact_versions(
    versions: Sequence[FactVersionV1],
) -> tuple[ValidationFindingV1, ...]:
    """Validate an immutable fact-revision chain without selecting a cutoff."""
    return validate_revision_chain(versions)


def parse_synthetic_fact_bytes(
    verified: VerifiedArtifactBytes,
) -> tuple[FactVersionV1, ...]:
    """Parse the already-verified bytes without resolving or reopening a path."""
    try:
        document = _SyntheticFactDocumentV1.model_validate_json(verified.data)
    except ValidationError as error:
        version_errors = {
            item["type"]
            for item in error.errors()
            if tuple(item["loc"]) == ("schema_version",)
        }
        code = (
            "unsupported_fact_schema_version"
            if "literal_error" in version_errors
            else "invalid_fact_document"
        )
        raise DatasetValidationError.single(code) from error
    return document.fact_versions


def validate_manifest_structure(
    manifest: DatasetManifestV1,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV1:
    """Validate the exact manifest and supplied verified artifact objects."""
    findings = _manifest_findings(manifest, verified_artifacts, context)
    return _decision(
        manifest,
        verified_artifacts,
        context,
        ValidationScope.MANIFEST_ONLY,
        (),
        (_MANIFEST_CONTRACT,),
        findings,
    )


def validate_synthetic_fact_dataset(
    manifest: DatasetManifestV1,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> DatasetValidationDecisionV1:
    """Validate every bound byte partition and record without a cutoff query."""
    findings = list(_manifest_findings(manifest, verified_artifacts, context))
    _validate_synthetic_bindings(manifest, findings)
    records_by_partition: list[
        tuple[PartitionDescriptorV1, tuple[FactVersionV1, ...]]
    ] = []
    records: list[FactVersionV1] = []

    verified_by_hash: dict[str, list[VerifiedArtifactBytes]] = defaultdict(list)
    for verified in verified_artifacts:
        verified_by_hash[verified.content_hash].append(verified)

    for partition in manifest.partitions:
        matches = verified_by_hash.get(partition.artifact.content_hash, [])
        if len(matches) != 1 or not _verified_matches(partition, matches[0]):
            continue
        try:
            parsed = parse_synthetic_fact_bytes(matches[0])
        except DatasetValidationError as error:
            findings.extend(_with_artifact(error.findings, partition))
            continue
        if len(parsed) != partition.row_count:
            findings.append(_finding("partition_row_count_mismatch", partition))
        records_by_partition.append((partition, parsed))
        records.extend(parsed)

    for partition, partition_records in records_by_partition:
        for record in partition_records:
            _validate_record(manifest, partition, record, findings)

    _validate_record_set(manifest, records, findings)
    record_hashes = tuple(sorted({record.payload_hash for record in records}))
    if len(record_hashes) != len(records):
        findings.append(_finding("duplicate_record_hash"))
    scope = ValidationScope.RECORDS if record_hashes else ValidationScope.MANIFEST_ONLY
    return _decision(
        manifest,
        verified_artifacts,
        context,
        scope,
        record_hashes,
        (_MANIFEST_CONTRACT, _RECORD_CONTRACT),
        findings,
    )


def _manifest_findings(
    manifest: DatasetManifestV1,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
) -> tuple[ValidationFindingV1, ...]:
    findings: list[ValidationFindingV1] = []
    if context.validator_version != _SUPPORTED_VALIDATOR_VERSION:
        findings.append(_finding("unsupported_validator_version"))
    if manifest.manifest_schema_version != "1":
        findings.append(_finding("unsupported_manifest_schema_version"))
    if manifest.hash_profile != "drift-canonical-json-sha256-v1":
        findings.append(_finding("unsupported_manifest_hash_profile"))
    if manifest.schema_definition.schema_version != "1":
        findings.append(_finding("unsupported_schema_version"))
    if manifest.temporal_contract.contract_version != "1":
        findings.append(_finding("unsupported_temporal_contract_version"))
    if any(partition.format_version != "1" for partition in manifest.partitions):
        findings.append(_finding("unsupported_partition_format_version"))
    if any(
        partition.media_type != "application/json" for partition in manifest.partitions
    ):
        findings.append(_finding("unsupported_partition_media_type"))

    try:
        DatasetManifestV1.model_validate(manifest.model_dump(mode="python"))
    except ValidationError:
        findings.append(_finding("invalid_manifest_structure"))
    try:
        if manifest.schema_definition.schema_hash != schema_hash(
            manifest.schema_definition
        ):
            findings.append(_finding("schema_hash_mismatch"))
    except AssertionError, KeyError, TypeError, ValueError:
        findings.append(_finding("schema_hash_mismatch"))
    _validate_schema_bindings(manifest, findings)
    _validate_lineage(manifest, findings)

    partition_hashes = tuple(
        partition.artifact.content_hash for partition in manifest.partitions
    )
    verified_hashes = tuple(item.content_hash for item in verified_artifacts)
    if len(set(partition_hashes)) != len(partition_hashes) or len(
        set(verified_hashes)
    ) != len(verified_hashes):
        findings.append(_finding("duplicate_artifact_hash"))

    partition_hash_set = set(partition_hashes)
    verified_hash_set = set(verified_hashes)
    for partition in manifest.partitions:
        matches = [
            item
            for item in verified_artifacts
            if item.content_hash == partition.artifact.content_hash
        ]
        if not matches:
            findings.append(_finding("missing_partition_artifact", partition))
            continue
        if len(matches) == 1:
            _append_verified_findings(partition, matches[0], findings)
    if verified_hash_set - partition_hash_set:
        findings.append(_finding("undeclared_partition_artifact"))
    return _canonical_findings(findings)


def _validate_schema_bindings(
    manifest: DatasetManifestV1, findings: list[ValidationFindingV1]
) -> None:
    field_ids = {field.field_id for field in manifest.schema_definition.fields}
    contract = manifest.temporal_contract
    if set(contract.field_ids()) - field_ids:
        findings.append(_finding("manifest_schema_binding_missing"))
    if any(
        partition.schema_hash != manifest.schema_definition.schema_hash
        for partition in manifest.partitions
    ):
        findings.append(_finding("partition_schema_hash_mismatch"))


def _validate_synthetic_bindings(
    manifest: DatasetManifestV1, findings: list[ValidationFindingV1]
) -> None:
    """Require the one concrete schema and role map supported by this parser."""
    if manifest.schema_definition != SYNTHETIC_FACT_SCHEMA_V1:
        findings.append(_finding("synthetic_schema_mismatch"))
    try:
        expected_contract = synthetic_fact_temporal_contract_v1(
            manifest.temporal_contract.declared_channels
        )
    except ValidationError:
        findings.append(_finding("synthetic_temporal_contract_mismatch"))
        return
    if manifest.temporal_contract != expected_contract:
        findings.append(_finding("synthetic_temporal_contract_mismatch"))


def _validate_lineage(
    manifest: DatasetManifestV1, findings: list[ValidationFindingV1]
) -> None:
    if manifest.dataset_kind is DatasetKind.SOURCE_FACTS:
        if manifest.lineage is not None:
            findings.append(_finding("unexpected_source_lineage"))
        return
    if manifest.lineage is None:
        findings.append(_finding("missing_derived_lineage"))
    elif manifest.lineage.output_schema_hash != manifest.schema_definition.schema_hash:
        findings.append(_finding("derived_lineage_schema_mismatch"))


def _append_verified_findings(
    partition: PartitionDescriptorV1,
    verified: VerifiedArtifactBytes,
    findings: list[ValidationFindingV1],
) -> None:
    if verified.byte_size != len(verified.data):
        findings.append(_finding("verified_byte_size_mismatch", partition))
    if sha256(verified.data).hexdigest() != verified.content_hash:
        findings.append(_finding("verified_content_hash_mismatch", partition))
    try:
        verify_partition_bytes(partition, verified)
    except ArtifactIntegrityError as error:
        code = (
            "partition_byte_size_mismatch"
            if "byte size" in str(error)
            else "partition_content_hash_mismatch"
        )
        findings.append(_finding(code, partition))


def _verified_matches(
    partition: PartitionDescriptorV1, verified: VerifiedArtifactBytes
) -> bool:
    if verified.byte_size != len(verified.data):
        return False
    if sha256(verified.data).hexdigest() != verified.content_hash:
        return False
    try:
        verify_partition_bytes(partition, verified)
    except ArtifactIntegrityError:
        return False
    return True


def _validate_record(
    manifest: DatasetManifestV1,
    partition: PartitionDescriptorV1,
    record: FactVersionV1,
    findings: list[ValidationFindingV1],
) -> None:
    period = record.logical_key.valid_period
    if (
        period.started_at < partition.coverage.started_at
        or period.ended_at > partition.coverage.ended_at
    ):
        findings.append(_finding("record_outside_partition_coverage", partition))
    if record.logical_key.source_id != manifest.source.source_id:
        findings.append(_finding("record_source_mismatch", partition))
    declared = set(manifest.temporal_contract.declared_channels)
    actual = {item.channel for item in record.availability}
    if declared - actual:
        findings.append(_finding("missing_declared_channel_evidence", partition))
    if actual - declared:
        findings.append(_finding("undeclared_channel_evidence", partition))


def _validate_record_set(
    manifest: DatasetManifestV1,
    records: Sequence[FactVersionV1],
    findings: list[ValidationFindingV1],
) -> None:
    chains: dict[str, list[FactVersionV1]] = defaultdict(list)
    evidence: list[AvailabilityEvidenceV1] = []
    fact_version_ids = tuple(record.fact_version_id for record in records)
    duplicate_fact_version_id = len(set(fact_version_ids)) != len(fact_version_ids)
    if duplicate_fact_version_id:
        findings.append(_finding("duplicate_fact_version_id"))
    for record in records:
        chains[content_hash(record.logical_key)].append(record)
        evidence.extend(record.availability)
        if record.payload_hash != content_hash(
            record.model_dump(mode="python", exclude={"payload_hash"})
        ):
            findings.append(_finding("record_payload_hash_mismatch"))
    for versions in chains.values():
        findings.extend(
            finding
            for finding in validate_revision_chain(versions)
            if not (
                duplicate_fact_version_id
                and finding.code == "duplicate_fact_version_id"
            )
        )

    raw_evidence = {
        content_hash(item): item
        for item in evidence
        if item.basis is not AvailabilityBasis.RULE_DERIVED
    }
    for item in evidence:
        if item.basis is not AvailabilityBasis.RULE_DERIVED:
            continue
        derivation = item.rule_derivation
        raw = (
            None
            if derivation is None
            else raw_evidence.get(derivation.input_evidence_hash)
        )
        if raw is None or derivation is None:
            findings.append(_finding("rule_input_evidence_unavailable"))
            continue
        try:
            recomputed = derive_conservative_upper_bound(raw, derivation.rule_reference)
        except ValidationError, ValueError:
            findings.append(_finding("rule_derivation_not_reproducible"))
            continue
        if recomputed != item:
            findings.append(_finding("rule_derivation_not_reproducible"))


def _decision(
    manifest: DatasetManifestV1,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    context: ValidationRunContextV1,
    scope: ValidationScope,
    record_hashes: tuple[str, ...],
    checked_contracts: tuple[str, ...],
    findings: Iterable[ValidationFindingV1],
) -> DatasetValidationDecisionV1:
    canonical_findings = _canonical_findings(findings)
    return DatasetValidationDecisionV1(
        **context.model_dump(mode="python"),
        manifest_hash=manifest_hash(manifest),
        validation_scope=scope,
        result=(
            ValidationResult.FAIL
            if any(
                finding.severity is FindingSeverity.ERROR
                for finding in canonical_findings
            )
            else ValidationResult.PASS
        ),
        validated_artifact_hashes=tuple(
            sorted({item.content_hash for item in verified_artifacts})
        ),
        validated_record_hashes=record_hashes,
        checked_contracts=tuple(sorted(checked_contracts)),
        findings=canonical_findings,
    )


def _with_artifact(
    findings: Sequence[ValidationFindingV1], partition: PartitionDescriptorV1
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        finding.model_copy(update={"artifact_references": (partition.artifact,)})
        for finding in findings
    )


def _finding(
    code: str, partition: PartitionDescriptorV1 | None = None
) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
        artifact_references=() if partition is None else (partition.artifact,),
    )


def _canonical_findings(
    findings: Iterable[ValidationFindingV1],
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.code,
                item.severity.value,
                item.message,
                tuple(ref.content_hash for ref in item.artifact_references),
            ),
        )
    )
