"""Exact-byte validation for immutable M1d source-observation datasets."""

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from drift.datasets.assertions import (
    build_validated_dataset_bundle,
    validate_assertion_chain,
    validate_manifest_v2_structure,
)
from drift.datasets.hashing import assertion_version_payload, manifest_hash, schema_hash
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import AssertionVersionProjectionV1
from drift.domain.common import UUID7, SHA256Hash
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    DatasetValidationError,
    FindingSeverity,
    ValidatedDatasetBundleV1,
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
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationContractV1,
    ObservationCoverageVersionV1,
    ObservationInputRecordV1,
    ObservationMethodologyV1,
    observation_methodology_for_contract,
)
from drift.domain.sessions import SessionInputRecordV1
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
)
from drift.domain.universes import ResearchUniverseDefinitionV1
from drift.errors import CanonicalSerializationError, DriftError
from drift.markets.universes import StructuralResolutionContext
from drift.serialization.canonical import canonical_json, content_hash

OBSERVATION_VALIDATION_PROFILE_ID = "m1d-source-observation-v1"
_OBSERVATION_VALIDATION_PROFILE_SPEC = {
    "schema_version": "1",
    "profile_id": OBSERVATION_VALIDATION_PROFILE_ID,
    "roles": ("observation_coverage", "source_observation"),
    "checks": (
        "exact_partition_bytes",
        "exact_role_schema",
        "exact_temporal_contract",
        "exact_typed_document",
        "complete_revision_chains",
        "source_and_contract_ownership",
        "exact_supporting_methodology",
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
        "source_observation": {
            **_SHARED_REVISION_FIELDS,
            "source_key": (LogicalType.JSON, False),
            "source_record_locator": (LogicalType.STRING, False),
            "source_record_hash": (LogicalType.STRING, False),
            "contract_hash": (LogicalType.STRING, False),
            "security_id": (LogicalType.STRING, False),
            "listing_id": (LogicalType.STRING, False),
            "venue": (LogicalType.STRING, False),
            "session_date": (LogicalType.DATE, False),
            "source_local_label": (LogicalType.STRING, False),
            "source_timezone": (LogicalType.STRING, False),
            "claimed_interval": (LogicalType.JSON, False),
            "completion_time": (LogicalType.JSON, False),
            "fields": (LogicalType.JSON, False),
            "source_flags": (LogicalType.JSON, False),
            "first_eligible_trade_time": (LogicalType.JSON, True),
            "last_eligible_trade_time": (LogicalType.JSON, True),
            "activity_claim": (LogicalType.STRING, False),
            "any_trade_claim": (LogicalType.STRING, False),
        },
        "observation_coverage": {
            **_SHARED_REVISION_FIELDS,
            "source_id": (LogicalType.STRING, False),
            "native_record_id": (LogicalType.STRING, False),
            "contract_hash": (LogicalType.STRING, False),
            "venue": (LogicalType.STRING, False),
            "listing_id": (LogicalType.STRING, False),
            "security_id": (LogicalType.STRING, False),
            "start_date": (LogicalType.DATE, False),
            "end_date": (LogicalType.DATE, False),
            "snapshot_identifier": (LogicalType.STRING, False),
            "snapshot_as_of": (LogicalType.JSON, False),
            "covered_dataset_hashes": (LogicalType.JSON, False),
            "covered_partition_hashes": (LogicalType.JSON, False),
            "record_inventory": (LogicalType.JSON, False),
            "methodology_artifact_hash": (LogicalType.STRING, False),
            "omission_rule_hash": (LogicalType.STRING, False),
            "status": (LogicalType.STRING, False),
            "exception_keys": (LogicalType.JSON, False),
            "missing_artifact_hashes": (LogicalType.JSON, False),
            "revision_history_completeness": (LogicalType.STRING, False),
        },
    }
)

_EFFECTIVE_FIELDS = MappingProxyType(
    {
        "source_observation": "completion_time",
        "observation_coverage": "snapshot_as_of",
    }
)


class ObservationArtifactUnavailableError(DriftError):
    """Raised when required exact M1d supporting bytes are unavailable."""


def observation_validation_profile_hash() -> str:
    """Return the immutable generic source-validation profile hash."""
    return content_hash(_OBSERVATION_VALIDATION_PROFILE_SPEC)


def observation_validator_implementation_hash() -> str:
    """Return the installed Drift Python source-inventory hash."""
    return m1d_implementation_hash()


def observation_role_schema(role: str) -> SchemaDescriptorV1:
    """Return the closed, hash-bound schema for one M1d observation role."""
    try:
        expected = _ROLE_FIELDS[role]
    except KeyError as error:
        raise ValueError(f"unsupported observation role: {role}") from error
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


SOURCE_OBSERVATION_SCHEMA_V1 = observation_role_schema("source_observation")
OBSERVATION_COVERAGE_SCHEMA_V1 = observation_role_schema("observation_coverage")


def observation_role_contract(
    role: str, channels: tuple[AvailabilityChannelV1, ...]
) -> AssertionTemporalContractV1:
    """Bind one M1d observation role to its exact assertion contract."""
    try:
        fields = _ROLE_FIELDS[role]
        effective_field = _EFFECTIVE_FIELDS[role]
    except KeyError as error:
        raise ValueError(f"unsupported observation role: {role}") from error
    semantic_fields = tuple(
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
        semantic_state_field_ids=semantic_fields,
        declared_channels=channels,
    )


def validate_observation_dataset(
    manifest: DatasetManifestV2,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    run: ValidationRunContextV1,
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes],
) -> tuple[DatasetValidationDecisionV2, tuple[ObservationInputRecordV1, ...]]:
    """Validate exact partition, contract, methodology, and source record bytes."""
    artifact_snapshot = MappingProxyType(dict(artifacts))
    support_snapshot = MappingProxyType(dict(supporting_artifacts))
    findings = [
        *_artifact_mapping_findings(artifact_snapshot, "observation_artifact"),
        *_artifact_mapping_findings(
            support_snapshot, "observation_supporting_artifact"
        ),
    ]
    verified = tuple(artifact_snapshot[key] for key in sorted(artifact_snapshot))
    structure = validate_manifest_v2_structure(manifest, verified, run)
    if structure.result is ValidationResult.FAIL:
        return structure, ()

    expected_run = (
        "1",
        observation_validator_implementation_hash(),
        OBSERVATION_VALIDATION_PROFILE_ID,
        observation_validation_profile_hash(),
    )
    actual_run = (
        run.validator_version,
        run.validator_implementation_hash,
        run.validation_profile_id,
        run.validation_profile_hash,
    )
    if actual_run != expected_run:
        findings.append(_finding("observation_validation_run_mismatch"))

    role = manifest.dataset_role.name
    try:
        expected_schema = observation_role_schema(role)
        expected_contract = observation_role_contract(
            role, manifest.temporal_contract.contract.declared_channels
        )
    except AttributeError, ValueError:
        findings.append(_finding("unsupported_observation_dataset_role"))
        return _final_decision(structure, findings, (), role)
    if (
        manifest.dataset_role.namespace != "drift"
        or manifest.dataset_role.version != "1"
    ):
        findings.append(_finding("observation_dataset_role_mismatch"))
    if manifest.schema_definition != expected_schema:
        findings.append(_finding("observation_role_schema_mismatch"))
    if manifest.temporal_contract.contract != expected_contract:
        findings.append(_finding("observation_role_contract_mismatch"))

    if _has_unsupported_consumed_raw_precision(verified, support_snapshot):
        findings.append(_finding("observation_unsupported_raw_temporal_precision"))
        return _final_decision(structure, findings, (), role)

    records: list[ObservationInputRecordV1] = []
    for partition in manifest.partitions:
        artifact = artifact_snapshot.get(partition.artifact.content_hash)
        if artifact is None:
            continue
        try:
            records.extend(parse_observation_document(artifact.data, role))
        except DatasetValidationError as error:
            findings.extend(error.findings)
    parsed = tuple(records)
    record_hashes = tuple(content_hash(record) for record in parsed)
    if len(set(record_hashes)) != len(record_hashes):
        findings.append(_finding("duplicate_observation_record_hash"))
    if len(parsed) != sum(item.row_count for item in manifest.partitions):
        findings.append(_finding("observation_row_count_mismatch"))

    declared_channels = set(manifest.temporal_contract.contract.declared_channels)
    contracts: dict[str, ObservationContractV1] = {}
    for record in parsed:
        if any(
            evidence.channel not in declared_channels
            for evidence in record.revision.availability
        ):
            findings.append(_finding("observation_undeclared_availability_channel"))
        source_id = (
            record.source_key.source_id
            if isinstance(record, DailySourceObservationVersionV1)
            else record.source_id
        )
        if source_id != manifest.source.source_id:
            findings.append(_finding("observation_source_id_mismatch"))
        contract = contracts.get(record.contract_hash)
        if contract is None:
            contract = _load_contract(record.contract_hash, support_snapshot, findings)
            if contract is not None:
                contracts[record.contract_hash] = contract
        if contract is None:
            continue
        if contract.source_id != source_id:
            findings.append(_finding("observation_contract_source_mismatch"))
        _validate_methodology(contract, support_snapshot, findings)
        if isinstance(record, DailySourceObservationVersionV1):
            _validate_row_contract(record, contract, findings)
        elif record.methodology_artifact_hash != contract.methodology_artifact_hash:
            findings.append(_finding("observation_coverage_methodology_mismatch"))

    findings.extend(_record_ownership_findings(parsed))
    findings.extend(
        _supporting_closure_findings(manifest, parsed, contracts, support_snapshot)
    )
    return _final_decision(structure, findings, parsed, role)


def parse_observation_document(
    data: bytes, role: str
) -> tuple[ObservationInputRecordV1, ...]:
    """Parse a canonical envelope through only the role's closed source model."""
    model: type[DailySourceObservationVersionV1 | ObservationCoverageVersionV1]
    if role == "source_observation":
        model = DailySourceObservationVersionV1
    elif role == "observation_coverage":
        model = ObservationCoverageVersionV1
    else:
        raise DatasetValidationError.single("unsupported_observation_dataset_role")
    try:
        document = _strict_json_loads(data)
    except _DuplicateJSONKeyError as error:
        raise DatasetValidationError.single(
            "observation_dataset_duplicate_json_key"
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DatasetValidationError.single(
            "observation_dataset_invalid_json"
        ) from error
    if canonical_json(document) != data:
        raise DatasetValidationError.single("observation_dataset_noncanonical_json")
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "records"}
        or document.get("schema_version") != "1"
        or not isinstance(document.get("records"), list)
    ):
        raise DatasetValidationError.single("observation_dataset_invalid_envelope")
    parsed: list[ObservationInputRecordV1] = []
    for raw_record in document["records"]:
        try:
            record = model.model_validate_json(canonical_json(raw_record))
        except (CanonicalSerializationError, TypeError, ValidationError) as error:
            raise DatasetValidationError.single("observation_record_invalid") from error
        if record.revision.payload_hash != content_hash(
            assertion_version_payload(record)
        ):
            raise DatasetValidationError.single("observation_payload_hash_mismatch")
        parsed.append(record)
    return tuple(parsed)


M1dRecordT = TypeVar(
    "M1dRecordT",
    bound=ObservationInputRecordV1 | SessionInputRecordV1,
    default=ObservationInputRecordV1,
)


@dataclass(frozen=True, slots=True)
class M1dDatasetInput(Generic[M1dRecordT]):
    """One immutable claimed M1d input, replayed before every public use."""

    manifest: DatasetManifestV2
    validation_run: ValidationRunContextV1
    artifacts: Mapping[str, VerifiedArtifactBytes]
    records: tuple[M1dRecordT, ...]
    decision: DatasetValidationDecisionV2
    bundle: ValidatedDatasetBundleV1

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", MappingProxyType(dict(self.artifacts)))
        object.__setattr__(self, "records", tuple(self.records))
        if self.decision.result is not ValidationResult.PASS:
            raise ValueError("M1d dataset input requires a passing decision")


@dataclass(frozen=True, slots=True)
class M1dResolutionContext:
    """Task-1 inputs retained for later additive M1d resolution stages."""

    observation_datasets: tuple[M1dDatasetInput[ObservationInputRecordV1], ...]
    availability_policies: Mapping[str, AvailabilityPolicyV1]
    retained_evidence: Mapping[str, AvailabilityEvidenceV1]
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes]
    session_datasets: tuple[M1dDatasetInput[SessionInputRecordV1], ...] = ()
    structural_context: StructuralResolutionContext | None = None
    research_definition: ResearchUniverseDefinitionV1 | None = None
    issuer_id: UUID7 | None = None
    structural_methodology_id: str | None = None
    m1b_requested_channel: AvailabilityChannelV1 | None = None
    schedule_generation_policy_hash: SHA256Hash | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_datasets", tuple(self.observation_datasets)
        )
        object.__setattr__(self, "session_datasets", tuple(self.session_datasets))
        object.__setattr__(
            self,
            "availability_policies",
            MappingProxyType(dict(self.availability_policies)),
        )
        object.__setattr__(
            self, "retained_evidence", MappingProxyType(dict(self.retained_evidence))
        )
        object.__setattr__(
            self,
            "supporting_artifacts",
            MappingProxyType(dict(self.supporting_artifacts)),
        )
        m1b_values = (
            self.structural_context,
            self.research_definition,
            self.issuer_id,
            self.structural_methodology_id,
        )
        if any(value is None for value in m1b_values) and any(
            value is not None for value in m1b_values
        ):
            raise ValueError("M1b observation context fields must be supplied together")
        if self.m1b_requested_channel is not None and self.structural_context is None:
            raise ValueError("M1b channel mapping requires a structural context")


def m1d_context_descriptor(context: M1dResolutionContext) -> dict[str, object]:
    """Return the storage-neutral exact Task-1 context hash preimage."""
    datasets = tuple(
        sorted(
            (
                {
                    "role": item.manifest.dataset_role.name,
                    "source_id": item.manifest.source.source_id,
                    "manifest_hash": manifest_hash(item.manifest),
                    "decision_hash": content_hash(item.decision),
                    "bundle_hash": content_hash(item.bundle),
                    "artifact_hashes": tuple(sorted(item.artifacts)),
                    "record_hashes": tuple(
                        sorted(content_hash(record) for record in item.records)
                    ),
                }
                for item in context.observation_datasets
            ),
            key=lambda item: (
                item["role"],
                item["source_id"],
                item["manifest_hash"],
            ),
        )
    )
    session_datasets = tuple(
        sorted(
            (
                {
                    "role": item.manifest.dataset_role.name,
                    "source_id": item.manifest.source.source_id,
                    "manifest_hash": manifest_hash(item.manifest),
                    "decision_hash": content_hash(item.decision),
                    "bundle_hash": content_hash(item.bundle),
                    "artifact_hashes": tuple(sorted(item.artifacts)),
                    "record_hashes": tuple(
                        sorted(content_hash(record) for record in item.records)
                    ),
                }
                for item in context.session_datasets
            ),
            key=lambda item: (
                item["role"],
                item["source_id"],
                item["manifest_hash"],
            ),
        )
    )
    descriptor: dict[str, object] = {
        "context_schema_version": "1",
        "observation_datasets": datasets,
        "session_datasets": session_datasets,
        "availability_policies": tuple(
            sorted(
                (key, content_hash(value))
                for key, value in context.availability_policies.items()
            )
        ),
        "retained_evidence": tuple(
            sorted(
                (key, content_hash(value))
                for key, value in context.retained_evidence.items()
            )
        ),
        "supporting_artifact_hashes": tuple(sorted(context.supporting_artifacts)),
    }
    m1b = _m1b_context_descriptor(context)
    if m1b is not None:
        descriptor["m1b"] = m1b
    if context.schedule_generation_policy_hash is not None:
        descriptor["schedule_generation_policy_hash"] = (
            context.schedule_generation_policy_hash
        )
    return descriptor


def _validated_records_descriptor(records: Any) -> dict[str, object]:
    return {
        "manifest_hash": manifest_hash(records.manifest),
        "decision_hash": content_hash(records.decision),
        "record_hashes": tuple(sorted(content_hash(item) for item in records.records)),
    }


def _m1b_context_descriptor(context: M1dResolutionContext) -> object:
    structural = context.structural_context
    if structural is None:
        return None
    universe = structural.universe
    return {
        "research_definition_hash": content_hash(context.research_definition),
        "issuer_id": context.issuer_id,
        "methodology_id": context.structural_methodology_id,
        "requested_channel": context.m1b_requested_channel,
        "identity_bundle_hash": content_hash(universe.identity_bundle),
        "universe_bundle_hash": content_hash(universe.universe_bundle),
        "policy_hash": content_hash(universe.policy),
        "retained_evidence": tuple(
            sorted(
                (key, content_hash(value))
                for key, value in universe.retained_evidence.items()
            )
        ),
        "assignments": _validated_records_descriptor(universe.assignments),
        "memberships": _validated_records_descriptor(universe.memberships),
        "source_definitions": _validated_records_descriptor(
            universe.source_definitions
        ),
        "relationships": _validated_records_descriptor(structural.relationships),
        "classifications": _validated_records_descriptor(structural.classifications),
        "roles": _validated_records_descriptor(structural.roles),
        "lifecycle": _validated_records_descriptor(structural.lifecycle),
        "terminations": _validated_records_descriptor(structural.terminations),
        "coverage": _validated_records_descriptor(structural.coverage),
    }


def m1d_context_hash(context: M1dResolutionContext) -> str:
    """Hash the exact Task-1 context descriptor without local paths."""
    return content_hash(m1d_context_descriptor(context))


def validate_m1d_resolution_context(context: M1dResolutionContext) -> None:
    """Validate the exact Task-1 context closure."""
    if any(
        item.manifest.dataset_role.name
        not in {"source_observation", "observation_coverage"}
        for item in context.observation_datasets
    ):
        raise DatasetValidationError.single("session_dataset_in_observation_slot")
    if any(
        item.manifest.dataset_role.name
        not in {"scheduled_session", "realized_session", "session_coverage"}
        for item in context.session_datasets
    ):
        raise DatasetValidationError.single("observation_dataset_in_session_slot")
    identities = tuple(
        (item.manifest.source.source_id, item.manifest.dataset_role.name)
        for item in context.observation_datasets
    )
    if len(set(identities)) != len(identities):
        raise DatasetValidationError.single("duplicate_observation_source_role")
    session_identities = tuple(
        (item.manifest.source.source_id, item.manifest.dataset_role.name)
        for item in context.session_datasets
    )
    if len(set(session_identities)) != len(session_identities):
        raise DatasetValidationError.single("duplicate_session_source_role")
    support_findings = _artifact_mapping_findings(
        context.supporting_artifacts, "observation_supporting_artifact"
    )
    if support_findings:
        raise DatasetValidationError(support_findings)
    for key, policy in context.availability_policies.items():
        if key != content_hash(policy):
            raise DatasetValidationError.single("availability_policy_mapping_mismatch")
    for key, evidence in context.retained_evidence.items():
        if key != content_hash(evidence):
            raise DatasetValidationError.single(
                "availability_evidence_mapping_mismatch"
            )
    for observation_dataset in context.observation_datasets:
        validate_m1d_dataset_input(observation_dataset, context.supporting_artifacts)
    for session_dataset in context.session_datasets:
        validate_m1d_dataset_input(session_dataset, context.supporting_artifacts)
    _validate_coverage_inventories(context.observation_datasets)
    from drift.markets.session_validation import (
        validate_session_coverage_inventories,
    )

    validate_session_coverage_inventories(context.session_datasets)


def validate_m1d_dataset_input(
    dataset: M1dDatasetInput[ObservationInputRecordV1]
    | M1dDatasetInput[SessionInputRecordV1],
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None:
    """Reconstruct a source dataset PASS from exact retained bytes."""
    role = dataset.manifest.dataset_role.name
    records: tuple[ObservationInputRecordV1, ...] | tuple[SessionInputRecordV1, ...]
    if role in {"source_observation", "observation_coverage"}:
        decision, observation_records = validate_observation_dataset(
            dataset.manifest,
            dataset.artifacts,
            dataset.validation_run,
            supporting_artifacts,
        )
        records = observation_records
        prefix = "observation"
    elif role in {"scheduled_session", "realized_session", "session_coverage"}:
        from drift.markets.session_validation import validate_session_dataset

        decision, session_records = validate_session_dataset(
            dataset.manifest,
            dataset.artifacts,
            dataset.validation_run,
            supporting_artifacts,
        )
        records = session_records
        prefix = "session"
    else:
        raise DatasetValidationError.single("unsupported_m1d_dataset_role")
    if decision != dataset.decision:
        raise DatasetValidationError.single(f"{prefix}_validation_decision_mismatch")
    if records != dataset.records:
        raise DatasetValidationError.single(f"{prefix}_parsed_records_mismatch")
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single(f"{prefix}_validation_decision_not_pass")
    if tuple(sorted(dataset.artifacts)) != decision.validated_artifact_hashes:
        raise DatasetValidationError.single(f"{prefix}_validated_artifact_set_mismatch")
    try:
        validated_bundle = ValidatedDatasetBundleV1.model_validate(
            dataset.bundle.model_dump(mode="python")
        )
        rebuilt_bundle = build_validated_dataset_bundle(
            bundle_id=validated_bundle.bundle_id,
            bundle_version=validated_bundle.bundle_version,
            created_at=validated_bundle.created_at,
            validated_datasets=((dataset.manifest, decision),),
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise DatasetValidationError.single(f"{prefix}_bundle_invalid") from error
    if rebuilt_bundle != validated_bundle:
        raise DatasetValidationError.single(f"{prefix}_bundle_membership_mismatch")


class _DuplicateJSONKeyError(ValueError):
    pass


def _strict_json_loads(data: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise _DuplicateJSONKeyError(key)
            value[key] = item
        return value

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


def _has_unsupported_consumed_raw_precision(
    partitions: Iterable[VerifiedArtifactBytes],
    supporting: Mapping[str, VerifiedArtifactBytes],
) -> bool:
    contract_hashes: set[str] = set()
    for artifact in partitions:
        try:
            document = _strict_json_loads(artifact.data)
        except UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKeyError:
            continue
        if not isinstance(document, dict):
            continue
        records = document.get("records")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            contract_hash = record.get("contract_hash")
            if isinstance(contract_hash, str):
                contract_hashes.add(contract_hash)
            revision = record.get("revision")
            if isinstance(
                revision, dict
            ) and _raw_availability_has_unsupported_precision(
                revision.get("availability")
            ):
                return True
            if _raw_interval_has_unsupported_precision(record.get("claimed_interval")):
                return True
            for field_name in (
                "completion_time",
                "first_eligible_trade_time",
                "last_eligible_trade_time",
                "snapshot_as_of",
            ):
                if _raw_boundary_has_unsupported_precision(record.get(field_name)):
                    return True
    for contract_hash in contract_hashes:
        contract_artifact = supporting.get(contract_hash)
        if contract_artifact is None:
            continue
        try:
            contract = _strict_json_loads(contract_artifact.data)
        except UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKeyError:
            continue
        if isinstance(contract, dict) and _raw_availability_has_unsupported_precision(
            contract.get("availability")
        ):
            return True
    return False


def _raw_availability_has_unsupported_precision(value: object) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, dict) and item.get("precision") in {"date", "minute"}
        for item in value
    )


def _raw_boundary_has_unsupported_precision(value: object) -> bool:
    return isinstance(value, dict) and value.get("source_precision") in {
        "date",
        "minute",
    }


def _raw_interval_has_unsupported_precision(value: object) -> bool:
    return isinstance(value, dict) and any(
        _raw_boundary_has_unsupported_precision(value.get(name))
        for name in ("start", "end")
    )


def _load_contract(
    expected_hash: str,
    supporting: Mapping[str, VerifiedArtifactBytes],
    findings: list[ValidationFindingV1],
) -> ObservationContractV1 | None:
    artifact = supporting.get(expected_hash)
    if artifact is None:
        findings.append(_finding("observation_contract_artifact_missing"))
        return None
    try:
        document = _strict_json_loads(artifact.data)
        if canonical_json(document) != artifact.data:
            raise ValueError("noncanonical contract")
        contract = ObservationContractV1.model_validate_json(artifact.data)
    except (
        CanonicalSerializationError,
        TypeError,
        ValueError,
        ValidationError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateJSONKeyError,
    ):
        findings.append(_finding("observation_contract_invalid"))
        return None
    if content_hash(contract) != expected_hash:
        findings.append(_finding("observation_contract_hash_mismatch"))
        return None
    return contract


def _validate_methodology(
    contract: ObservationContractV1,
    supporting: Mapping[str, VerifiedArtifactBytes],
    findings: list[ValidationFindingV1],
) -> None:
    artifact = supporting.get(contract.methodology_artifact_hash)
    if artifact is None:
        findings.append(_finding("observation_methodology_artifact_missing"))
        return
    expected = observation_methodology_for_contract(contract)
    if artifact.data != canonical_json(expected):
        findings.append(_finding("observation_methodology_contract_mismatch"))
        return
    try:
        parsed = ObservationMethodologyV1.model_validate_json(artifact.data)
    except ValidationError:
        findings.append(_finding("observation_methodology_invalid"))
        return
    if parsed != expected:
        findings.append(_finding("observation_methodology_contract_mismatch"))


def _validate_row_contract(
    record: DailySourceObservationVersionV1,
    contract: ObservationContractV1,
    findings: list[ValidationFindingV1],
) -> None:
    methods = {
        (item.field_name, item.method_id): item for item in contract.field_methods
    }
    flags = {item.key: item.value for item in record.source_flags}
    for field in record.fields:
        if (field.field_name, field.method_id) not in methods:
            findings.append(_finding("observation_method_foreign_to_contract"))
            continue
        branches = tuple(
            branch
            for branch in contract.method_branches
            if branch.method_id == field.method_id
        )
        active = tuple(
            branch
            for branch in branches
            if branch.trigger_kind == "always"
            or flags.get(branch.marker_name or "") == branch.marker_value
        )
        if len(active) != 1:
            findings.append(_finding("observation_method_branch_not_exactly_active"))


def _record_ownership_findings(
    records: Sequence[ObservationInputRecordV1],
) -> tuple[ValidationFindingV1, ...]:
    by_logical: dict[object, list[ObservationInputRecordV1]] = defaultdict(list)
    keys_by_logical: dict[object, set[tuple[str, str, str]]] = defaultdict(set)
    logical_by_key: dict[tuple[str, str, str], set[object]] = defaultdict(set)
    version_hashes: dict[object, set[str]] = defaultdict(set)
    for record in records:
        logical_id = record.revision.logical_record_id
        by_logical[logical_id].append(record)
        key = (
            (
                "source_observation",
                record.source_key.source_id,
                record.source_key.native_record_id,
            )
            if isinstance(record, DailySourceObservationVersionV1)
            else (
                "observation_coverage",
                record.source_id,
                record.native_record_id,
            )
        )
        keys_by_logical[logical_id].add(key)
        logical_by_key[key].add(logical_id)
        version_hashes[record.revision.record_version_id].add(content_hash(record))
    findings: list[ValidationFindingV1] = []
    if any(len(values) > 1 for values in keys_by_logical.values()):
        findings.append(_finding("observation_logical_record_multiple_source_keys"))
    if any(len(values) > 1 for values in logical_by_key.values()):
        findings.append(_finding("observation_source_key_multiple_logical_records"))
    if any(len(values) > 1 for values in version_hashes.values()):
        findings.append(_finding("observation_conflicting_record_version"))
    for versions in by_logical.values():
        findings.extend(
            validate_assertion_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=record.revision,
                        record_hash=content_hash(record),
                    )
                    for record in versions
                )
            )
        )
    return _canonical_findings(findings)


def _supporting_closure_findings(
    manifest: DatasetManifestV2,
    records: Sequence[ObservationInputRecordV1],
    contracts: Mapping[str, ObservationContractV1],
    supporting: Mapping[str, VerifiedArtifactBytes],
) -> tuple[ValidationFindingV1, ...]:
    required = {
        manifest.source.evidence_reference.content_hash,
        manifest.acquisition.evidence_reference.content_hash,
        manifest.license.terms_evidence_reference.content_hash,
    }
    partition_hashes = {item.artifact.content_hash for item in manifest.partitions}
    for record in records:
        required.update(item.content_hash for item in _artifact_references(record))
        if isinstance(record, DailySourceObservationVersionV1):
            required.add(record.source_record_hash)
        else:
            required.update(
                (record.methodology_artifact_hash, record.omission_rule_hash)
            )
    for digest, contract in contracts.items():
        required.add(digest)
        required.update(_contract_artifact_hashes(contract))
        required.update(item.content_hash for item in _artifact_references(contract))
    if required & partition_hashes:
        return (_finding("observation_partition_self_reference"),)
    if required - set(supporting):
        return (_finding("observation_missing_supporting_artifact"),)
    return ()


def _validate_coverage_inventories(
    datasets: Sequence[M1dDatasetInput],
) -> None:
    by_manifest_hash = {
        manifest_hash(dataset.manifest): dataset for dataset in datasets
    }
    for coverage_dataset in datasets:
        for record in coverage_dataset.records:
            if not isinstance(record, ObservationCoverageVersionV1):
                continue
            targets: list[M1dDatasetInput] = []
            for digest in record.covered_dataset_hashes:
                target = by_manifest_hash.get(digest)
                if (
                    target is None
                    or target.manifest.dataset_role.name != "source_observation"
                ):
                    raise DatasetValidationError.single(
                        "observation_coverage_target_manifest_missing"
                    )
                targets.append(target)
            expected_partitions = tuple(
                sorted(digest for target in targets for digest in target.artifacts)
            )
            expected_inventory = tuple(
                sorted(
                    (
                        (
                            item.revision.logical_record_id,
                            item.revision.record_version_id,
                            content_hash(item),
                        )
                        for target in targets
                        for item in target.records
                        if isinstance(item, DailySourceObservationVersionV1)
                    ),
                    key=lambda item: (str(item[0]), str(item[1]), item[2]),
                )
            )
            actual_inventory = tuple(
                (
                    item.assertion_id,
                    item.version_id,
                    item.record_hash,
                )
                for item in record.record_inventory
            )
            if (
                record.covered_partition_hashes != expected_partitions
                or actual_inventory != expected_inventory
            ):
                raise DatasetValidationError.single(
                    "observation_coverage_inventory_mismatch"
                )
            for target in targets:
                if target.manifest.source.source_id != record.source_id:
                    raise DatasetValidationError.single(
                        "observation_coverage_source_mismatch"
                    )
                for item in target.records:
                    if not isinstance(item, DailySourceObservationVersionV1):
                        continue
                    if (
                        item.contract_hash != record.contract_hash
                        or item.security_id != record.security_id
                        or item.listing_id != record.listing_id
                        or item.venue is not record.venue
                        or not (
                            record.start_date <= item.session_date <= record.end_date
                        )
                    ):
                        raise DatasetValidationError.single(
                            "observation_coverage_scope_mismatch"
                        )


def _contract_artifact_hashes(contract: ObservationContractV1) -> set[str]:
    hashes = {contract.methodology_artifact_hash}
    for population in contract.populations:
        hashes.update(
            (
                population.sale_condition_policy_hash,
                population.correction_cancellation_policy_hash,
                population.evidence_hash,
            )
        )
    for method in contract.field_methods:
        hashes.update((method.ordering_policy_hash, method.basis_methodology_hash))
        if method.equivalence_evidence_hash is not None:
            hashes.add(method.equivalence_evidence_hash)
    hashes.update(
        item.methodology_artifact_hash for item in contract.method_equivalences
    )
    hashes.update(item.evidence_hash for item in contract.volume_relationships)
    hashes.update(
        (
            contract.interval_policy.event_policy_hash,
            contract.revision_policy.policy_hash,
            contract.row_emission.omission_marker_policy_hash,
        )
    )
    return hashes


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


def _final_decision(
    structure: DatasetValidationDecisionV2,
    findings: Sequence[ValidationFindingV1],
    records: Sequence[ObservationInputRecordV1],
    role: str,
) -> tuple[DatasetValidationDecisionV2, tuple[ObservationInputRecordV1, ...]]:
    canonical_findings = _canonical_findings(findings)
    passed = not canonical_findings
    record_hashes = tuple(sorted({content_hash(item) for item in records}))
    checked_contracts = list(structure.checked_contracts)
    if passed:
        marker = role.replace("_", "-") + "-v1"
        checked_contracts.append(marker)
        if not records:
            checked_contracts.append(marker + "-exact-empty")
    decision = structure.model_copy(
        update={
            "validation_scope": (
                ValidationScope.RECORDS
                if passed and record_hashes
                else ValidationScope.MANIFEST_ONLY
            ),
            "result": ValidationResult.PASS if passed else ValidationResult.FAIL,
            "validated_record_hashes": record_hashes if passed else (),
            "checked_contracts": tuple(sorted(set(checked_contracts))),
            "findings": canonical_findings,
        }
    )
    return decision, tuple(records) if passed else ()


def _finding(code: str) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
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
                tuple(reference.content_hash for reference in item.artifact_references),
            ),
        )
    )
