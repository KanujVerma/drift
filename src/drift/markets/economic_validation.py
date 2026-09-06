"""Exact-byte validation for immutable M1c economic source datasets."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from pydantic import BaseModel, ValidationError

from drift.datasets.assertions import (
    validate_assertion_chain,
    validate_manifest_v2_structure,
)
from drift.datasets.hashing import (
    assertion_version_payload,
    manifest_hash,
    schema_hash,
)
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.assertions import AssertionVersionProjectionV1
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
from drift.domain.economic_common import (
    EconomicSourceKeyV1,
    economic_implementation_hash,
)
from drift.domain.economic_coverage import (
    EconomicCoverageVersionV1,
    EconomicInputRecordV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicSettlementVersionV1,
    validate_economic_record_ownership,
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
from drift.domain.securities import IdentityAssignmentVersionV1
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
)
from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import canonical_json, content_hash

ECONOMIC_VALIDATION_PROFILE_ID = "m1c-economic-source-v1"
_ECONOMIC_VALIDATION_PROFILE_SPEC = {
    "schema_version": "1",
    "profile_id": ECONOMIC_VALIDATION_PROFILE_ID,
    "roles": tuple(
        sorted(
            (
                "economic_terms",
                "economic_effect",
                "economic_settlement",
                "economic_coverage",
            )
        )
    ),
    "checks": (
        "exact_partition_bytes",
        "exact_role_schema",
        "exact_temporal_contract",
        "exact_typed_document",
        "complete_revision_chains",
        "source_ownership",
    ),
}


def economic_validation_profile_hash() -> str:
    """Return the hash of the immutable M1c validation profile."""
    return content_hash(_ECONOMIC_VALIDATION_PROFILE_SPEC)


def economic_validator_implementation_hash() -> str:
    """Return the exact installed Drift Python source-inventory hash."""
    return economic_implementation_hash()


def economic_coverage_methodology_supported(
    record: EconomicCoverageVersionV1,
    supporting_artifacts: Sequence[VerifiedArtifactBytes],
) -> bool:
    """Recognize one exact synthetic methodology profile without granting authority."""
    matches = tuple(
        artifact
        for artifact in supporting_artifacts
        if artifact.content_hash == record.methodology_reference.content_hash
    )
    if len(matches) != 1:
        return False
    artifact = matches[0]
    if (
        artifact.byte_size != len(artifact.data)
        or sha256(artifact.data).hexdigest() != artifact.content_hash
    ):
        return False
    expected_profile = {
        "schema_version": "1",
        "kind": "drift_economic_coverage_methodology",
        "methodology_version": record.methodology_version,
        "omission_detection": "closed_artifact_and_record_inventory",
        "revision_tracking": "source_sequence_and_supersession",
        "occurrence_identification": "stable_economic_occurrence_id",
    }
    if artifact.data != canonical_json(expected_profile):
        return False
    try:
        document = json.loads(artifact.data)
    except UnicodeDecodeError, json.JSONDecodeError:
        return False
    return bool(document == expected_profile)


_ROLE_MODELS: Mapping[str, type[EconomicInputRecordV1]] = MappingProxyType(
    {
        "economic_terms": CorporateActionTermsVersionV1,
        "economic_effect": EconomicEffectVersionV1,
        "economic_settlement": EconomicSettlementVersionV1,
        "economic_coverage": EconomicCoverageVersionV1,
    }
)

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

_SHARED_FIELDS: dict[str, tuple[LogicalType, bool]] = {
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
    "source_key": (LogicalType.JSON, False),
    "security_id": (LogicalType.STRING, False),
    "listing_id": (LogicalType.STRING, True),
}

_FACT_FIELDS: dict[str, tuple[LogicalType, bool]] = {
    "occurrence": (LogicalType.JSON, False),
    "source_action_code": (LogicalType.STRING, True),
    "payload": (LogicalType.JSON, True),
}

_ROLE_FIELDS: Mapping[str, Mapping[str, tuple[LogicalType, bool]]] = MappingProxyType(
    {
        "economic_terms": {
            **_SHARED_FIELDS,
            **_FACT_FIELDS,
            "scheduled_effect_time": (LogicalType.JSON, False),
        },
        "economic_effect": {
            **_SHARED_FIELDS,
            **_FACT_FIELDS,
            "effective_time": (LogicalType.JSON, False),
            "terms_association": (LogicalType.JSON, False),
        },
        "economic_settlement": {
            **_SHARED_FIELDS,
            **_FACT_FIELDS,
            "settled_time": (LogicalType.JSON, False),
            "terms_association": (LogicalType.JSON, False),
            "effect_association": (LogicalType.JSON, False),
        },
        "economic_coverage": {
            **_SHARED_FIELDS,
            "coverage_interval": (LogicalType.JSON, False),
            "fact_family": (LogicalType.STRING, False),
            "action_kinds": (LogicalType.JSON, False),
            "target_manifest_hash": (LogicalType.STRING, False),
            "inventory_artifact_hashes": (LogicalType.JSON, False),
            "inventory_record_hashes": (LogicalType.JSON, False),
            "methodology_reference": (LogicalType.JSON, False),
            "methodology_version": (LogicalType.STRING, False),
            "snapshot_at": (LogicalType.DATETIME, False),
            "completeness": (LogicalType.STRING, False),
            "revision_support": (LogicalType.STRING, False),
            "occurrence_key_semantics": (LogicalType.STRING, False),
            "gaps": (LogicalType.JSON, False),
            "exceptions": (LogicalType.JSON, False),
        },
    }
)

_EFFECTIVE_FIELDS = MappingProxyType(
    {
        "economic_terms": ("scheduled_effect_time", AssertionEffectiveShape.BOUNDARY),
        "economic_effect": ("effective_time", AssertionEffectiveShape.BOUNDARY),
        "economic_settlement": ("settled_time", AssertionEffectiveShape.BOUNDARY),
        "economic_coverage": ("coverage_interval", AssertionEffectiveShape.INTERVAL),
    }
)


def _require_role[T](role: str, values: Mapping[str, T]) -> T:
    try:
        return values[role]
    except KeyError as error:
        raise ValueError(f"unsupported economic role: {role}") from error


def economic_role_schema(role: str) -> SchemaDescriptorV1:
    """Return the closed, hash-bound schema for one M1c dataset role."""
    expected = _require_role(role, _ROLE_FIELDS)
    ordered = tuple(
        sorted(
            (
                FieldDescriptorV1(
                    field_id=field_id,
                    name=field_id,
                    logical_type=logical_type,
                    nullable=nullable,
                )
                for field_id, (logical_type, nullable) in expected.items()
            ),
            key=lambda item: item.field_id,
        )
    )
    provisional = SchemaDescriptorV1.model_construct(
        schema_version="1", fields=ordered, schema_hash="0" * 64
    )
    return SchemaDescriptorV1(
        schema_version="1", fields=ordered, schema_hash=schema_hash(provisional)
    )


ECONOMIC_TERMS_SCHEMA_V1 = economic_role_schema("economic_terms")
ECONOMIC_EFFECT_SCHEMA_V1 = economic_role_schema("economic_effect")
ECONOMIC_SETTLEMENT_SCHEMA_V1 = economic_role_schema("economic_settlement")
ECONOMIC_COVERAGE_SCHEMA_V1 = economic_role_schema("economic_coverage")


def economic_role_contract(
    role: str, channels: tuple[AvailabilityChannelV1, ...]
) -> AssertionTemporalContractV1:
    """Bind one economic role to its exact assertion temporal contract."""
    expected = _require_role(role, _ROLE_FIELDS)
    effective_field, effective_shape = _require_role(role, _EFFECTIVE_FIELDS)
    semantic_fields = tuple(
        sorted(
            field_id
            for field_id in expected
            if field_id not in _BOUND_REVISION_FIELDS and field_id != effective_field
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
        effective_shape=effective_shape,
        semantic_state_field_ids=semantic_fields,
        declared_channels=channels,
    )


def parse_economic_document(
    data: bytes, role: str
) -> tuple[EconomicInputRecordV1, ...]:
    """Parse one canonical envelope only through the role's exact Pydantic model."""
    model = _require_role(role, _ROLE_MODELS)
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DatasetValidationError.single("economic_dataset_invalid_json") from error
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "records"}
        or document.get("schema_version") != "1"
        or not isinstance(document.get("records"), list)
    ):
        raise DatasetValidationError.single("economic_dataset_invalid_envelope")
    parsed: list[EconomicInputRecordV1] = []
    for raw_record in document["records"]:
        try:
            record = model.model_validate_json(canonical_json(raw_record))
        except (CanonicalSerializationError, TypeError, ValidationError) as error:
            raise DatasetValidationError.single("economic_record_invalid") from error
        if record.revision.payload_hash != content_hash(
            assertion_version_payload(record)
        ):
            raise DatasetValidationError.single("economic_payload_hash_mismatch")
        parsed.append(record)
    return tuple(parsed)


def validate_economic_dataset(
    manifest: DatasetManifestV2,
    verified_artifacts: Sequence[VerifiedArtifactBytes],
    run: ValidationRunContextV1,
) -> tuple[DatasetValidationDecisionV2, tuple[EconomicInputRecordV1, ...]]:
    """Validate exact partition bytes, role schema, records, and revision ownership."""
    structure = validate_manifest_v2_structure(manifest, verified_artifacts, run)
    if structure.result is ValidationResult.FAIL:
        return structure, ()

    role = manifest.dataset_role.name
    findings: list[ValidationFindingV1] = []
    records: tuple[EconomicInputRecordV1, ...] = ()
    try:
        expected_schema = economic_role_schema(role)
        expected_contract = economic_role_contract(
            role, manifest.temporal_contract.contract.declared_channels
        )
    except ValueError:
        findings.append(_finding("unsupported_economic_dataset_role"))
    else:
        if (
            manifest.dataset_role.namespace != "drift"
            or manifest.dataset_role.version != "1"
        ):
            findings.append(_finding("economic_dataset_role_mismatch"))
        if manifest.schema_definition != expected_schema:
            findings.append(_finding("economic_role_schema_mismatch"))
        if manifest.temporal_contract.contract != expected_contract:
            findings.append(_finding("economic_role_contract_mismatch"))
        parsed: list[EconomicInputRecordV1] = []
        for artifact in verified_artifacts:
            try:
                parsed.extend(parse_economic_document(artifact.data, role))
            except DatasetValidationError as error:
                findings.extend(error.findings)
        records = tuple(parsed)

    record_hashes = tuple(sorted(content_hash(record) for record in records))
    if len(set(record_hashes)) != len(record_hashes):
        findings.append(_finding("duplicate_economic_record_hash"))
    if len(records) != sum(partition.row_count for partition in manifest.partitions):
        findings.append(_finding("economic_row_count_mismatch"))

    declared_channels = set(manifest.temporal_contract.contract.declared_channels)
    for record in records:
        if record.source_key.source_id != manifest.source.source_id:
            findings.append(_finding("economic_source_id_mismatch"))
        if any(
            evidence.channel not in declared_channels
            for evidence in record.revision.availability
        ):
            findings.append(_finding("economic_undeclared_availability_channel"))

    facts = tuple(
        record
        for record in records
        if not isinstance(record, EconomicCoverageVersionV1)
    )
    findings.extend(validate_economic_record_ownership(facts))
    findings.extend(
        _coverage_ownership_findings(
            tuple(
                record
                for record in records
                if isinstance(record, EconomicCoverageVersionV1)
            )
        )
    )
    canonical_findings = _canonical_findings(findings)
    passed = not canonical_findings
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
            "validated_record_hashes": (
                tuple(sorted(set(record_hashes))) if passed else ()
            ),
            "checked_contracts": tuple(sorted(set(checked_contracts))),
            "findings": canonical_findings,
        }
    )
    return decision, records if passed else ()


@dataclass(frozen=True, slots=True)
class EconomicDatasetInput:
    """One immutable, exact-byte economic dataset input."""

    records: tuple[EconomicInputRecordV1, ...]
    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2
    verified_artifacts: tuple[VerifiedArtifactBytes, ...]
    validation_run: ValidationRunContextV1
    bundle: ValidatedDatasetBundleV1

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "verified_artifacts", tuple(self.verified_artifacts))


@dataclass(frozen=True, slots=True)
class EconomicIdentityInput:
    """One immutable, exact-byte identity assignment input."""

    records: tuple[IdentityAssignmentVersionV1, ...]
    manifest: DatasetManifestV2
    decision: DatasetValidationDecisionV2
    verified_artifacts: tuple[VerifiedArtifactBytes, ...]
    validation_run: ValidationRunContextV1
    bundle: ValidatedDatasetBundleV1

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "verified_artifacts", tuple(self.verified_artifacts))


@dataclass(frozen=True, slots=True)
class EconomicResolutionContext:
    """Closed immutable inputs available to later M1c resolution."""

    datasets: tuple[EconomicDatasetInput, ...]
    identity: EconomicIdentityInput
    availability_policy: AvailabilityPolicyV1
    retained_evidence: Mapping[str, AvailabilityEvidenceV1]
    supporting_artifacts: tuple[VerifiedArtifactBytes, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "datasets", tuple(self.datasets))
        object.__setattr__(
            self,
            "retained_evidence",
            MappingProxyType(dict(self.retained_evidence)),
        )
        object.__setattr__(
            self, "supporting_artifacts", tuple(self.supporting_artifacts)
        )


def validate_economic_context(context: EconomicResolutionContext) -> None:
    """Validate one closed M1c resolution context."""
    identities = tuple(
        (dataset.manifest.source.source_id, dataset.manifest.dataset_role.name)
        for dataset in context.datasets
    )
    if len(set(identities)) != len(identities):
        raise DatasetValidationError.single("duplicate_economic_source_role")

    for dataset in context.datasets:
        expected_run = (
            "1",
            economic_validator_implementation_hash(),
            ECONOMIC_VALIDATION_PROFILE_ID,
            economic_validation_profile_hash(),
        )
        actual_run = (
            dataset.validation_run.validator_version,
            dataset.validation_run.validator_implementation_hash,
            dataset.validation_run.validation_profile_id,
            dataset.validation_run.validation_profile_hash,
        )
        if actual_run != expected_run:
            raise DatasetValidationError.single("economic_validation_run_mismatch")
        decision, parsed = validate_economic_dataset(
            dataset.manifest,
            dataset.verified_artifacts,
            dataset.validation_run,
        )
        if decision != dataset.decision:
            raise DatasetValidationError.single("economic_validation_decision_mismatch")
        if parsed != dataset.records:
            raise DatasetValidationError.single("economic_parsed_records_mismatch")
        if tuple(sorted(item.content_hash for item in dataset.verified_artifacts)) != (
            dataset.decision.validated_artifact_hashes
        ):
            raise DatasetValidationError.single(
                "economic_validated_artifact_set_mismatch"
            )
        if decision.result is not ValidationResult.PASS:
            raise DatasetValidationError.single("economic_validation_decision_not_pass")

    _require_exact_bundle_membership(context.datasets)
    _validate_identity_input(context.identity)
    _validate_coverage_inventories(context.datasets)
    require_m1c_evidence_closure(context)


def economic_context_hash(context: EconomicResolutionContext) -> str:
    """Hash the exact immutable inputs to later M1c resolution."""
    datasets = tuple(
        sorted(
            (
                {
                    "role": dataset.manifest.dataset_role.name,
                    "source_id": dataset.manifest.source.source_id,
                    "manifest_hash": manifest_hash(dataset.manifest),
                    "decision_hash": content_hash(dataset.decision),
                    "bundle_hash": content_hash(dataset.bundle),
                    "artifact_hashes": tuple(
                        sorted(
                            artifact.content_hash
                            for artifact in dataset.verified_artifacts
                        )
                    ),
                    "record_hashes": tuple(
                        sorted(content_hash(record) for record in dataset.records)
                    ),
                }
                for dataset in context.datasets
            ),
            key=lambda item: (
                item["role"],
                item["source_id"],
                item["manifest_hash"],
            ),
        )
    )
    identity = context.identity
    payload = {
        "context_schema_version": "1",
        "datasets": datasets,
        "identity": {
            "role": identity.manifest.dataset_role.name,
            "source_id": identity.manifest.source.source_id,
            "manifest_hash": manifest_hash(identity.manifest),
            "decision_hash": content_hash(identity.decision),
            "bundle_hash": content_hash(identity.bundle),
            "artifact_hashes": tuple(
                sorted(
                    artifact.content_hash for artifact in identity.verified_artifacts
                )
            ),
            "record_hashes": tuple(
                sorted(content_hash(record) for record in identity.records)
            ),
        },
        "availability_policy_hash": content_hash(context.availability_policy),
        "retained_evidence_hashes": tuple(
            sorted(
                (key, content_hash(evidence))
                for key, evidence in context.retained_evidence.items()
            )
        ),
        "supporting_artifact_hashes": tuple(
            sorted(artifact.content_hash for artifact in context.supporting_artifacts)
        ),
    }
    return content_hash(payload)


def require_m1c_evidence_closure(context: EconomicResolutionContext) -> None:
    """Require exact supporting bytes for every retained M1c evidence reference."""
    references: list[ArtifactReference] = []
    partition_hashes: set[str] = set()
    for dataset in context.datasets:
        own_partition_hashes = {
            artifact.content_hash for artifact in dataset.verified_artifacts
        }
        partition_hashes.update(own_partition_hashes)
        for record in dataset.records:
            record_references = _artifact_references(record)
            if any(
                reference.content_hash in own_partition_hashes
                for reference in record_references
            ):
                raise DatasetValidationError.single("economic_partition_self_reference")
            references.extend(record_references)
        references.extend(
            (
                dataset.manifest.source.evidence_reference,
                dataset.manifest.acquisition.evidence_reference,
                dataset.manifest.license.terms_evidence_reference,
            )
        )
    for evidence in context.retained_evidence.values():
        references.extend(_artifact_references(evidence))

    supplied_hashes = tuple(
        artifact.content_hash for artifact in context.supporting_artifacts
    )
    if len(set(supplied_hashes)) != len(supplied_hashes):
        raise DatasetValidationError.single("duplicate_supporting_artifact")
    for artifact in context.supporting_artifacts:
        if artifact.byte_size != len(artifact.data):
            raise DatasetValidationError.single("supporting_artifact_size_mismatch")
        if sha256(artifact.data).hexdigest() != artifact.content_hash:
            raise DatasetValidationError.single("supporting_artifact_hash_mismatch")

    required_hashes = {
        reference.content_hash for reference in references
    } - partition_hashes
    supplied_set = set(supplied_hashes)
    if required_hashes - supplied_set:
        raise DatasetValidationError.single("missing_supporting_artifact")
    if supplied_set - required_hashes:
        raise DatasetValidationError.single("extra_supporting_artifact")


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


def _require_exact_bundle_membership(
    datasets: Sequence[EconomicDatasetInput],
) -> None:
    bundles: dict[str, ValidatedDatasetBundleV1] = {}
    for dataset in datasets:
        bundle_hash = content_hash(dataset.bundle)
        existing = bundles.setdefault(bundle_hash, dataset.bundle)
        if existing != dataset.bundle:
            raise DatasetValidationError.single("economic_bundle_hash_collision")
    for bundle_hash, bundle in bundles.items():
        actual = {
            (
                member.dataset_role,
                member.manifest_hash,
                member.validation_decision_hash,
            )
            for member in bundle.members
        }
        represented = {
            (
                dataset.manifest.dataset_role,
                manifest_hash(dataset.manifest),
                content_hash(dataset.decision),
            )
            for dataset in datasets
            if content_hash(dataset.bundle) == bundle_hash
        }
        if actual != represented:
            raise DatasetValidationError.single("economic_bundle_membership_mismatch")


def _validate_identity_input(identity: EconomicIdentityInput) -> None:
    decision = __import__(
        "drift.markets.validation", fromlist=["validate_identity_dataset"]
    ).validate_identity_dataset(
        identity.manifest,
        identity.verified_artifacts,
        identity.validation_run,
    )
    if decision != identity.decision:
        raise DatasetValidationError.single("identity_validation_decision_mismatch")
    parsed: list[IdentityAssignmentVersionV1] = []
    for artifact in identity.verified_artifacts:
        try:
            document = json.loads(artifact.data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DatasetValidationError.single(
                "identity_dataset_invalid_json"
            ) from error
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "records"}
            or document.get("schema_version") != "1"
            or not isinstance(document.get("records"), list)
        ):
            raise DatasetValidationError.single("identity_dataset_invalid_envelope")
        for raw_record in document["records"]:
            try:
                parsed.append(
                    IdentityAssignmentVersionV1.model_validate_json(
                        canonical_json(raw_record)
                    )
                )
            except (CanonicalSerializationError, TypeError, ValidationError) as error:
                raise DatasetValidationError.single(
                    "identity_record_invalid"
                ) from error
    if tuple(parsed) != identity.records:
        raise DatasetValidationError.single("identity_parsed_records_mismatch")
    expected_member = (
        identity.manifest.dataset_role,
        manifest_hash(identity.manifest),
        content_hash(identity.decision),
    )
    actual_members = tuple(
        (
            member.dataset_role,
            member.manifest_hash,
            member.validation_decision_hash,
        )
        for member in identity.bundle.members
    )
    if actual_members != (expected_member,):
        raise DatasetValidationError.single("identity_bundle_membership_mismatch")
    if decision.result is not ValidationResult.PASS:
        raise DatasetValidationError.single("identity_validation_decision_not_pass")


def _validate_coverage_inventories(
    datasets: Sequence[EconomicDatasetInput],
) -> None:
    by_manifest_hash = {
        manifest_hash(dataset.manifest): dataset for dataset in datasets
    }
    for coverage_dataset in datasets:
        for record in coverage_dataset.records:
            if not isinstance(record, EconomicCoverageVersionV1):
                continue
            target = by_manifest_hash.get(record.target_manifest_hash)
            if target is None:
                raise DatasetValidationError.single("coverage_target_manifest_missing")
            if (
                target.manifest.dataset_role.name != f"economic_{record.fact_family}"
                or target.manifest.source.source_id != record.source_key.source_id
            ):
                raise DatasetValidationError.single("coverage_target_binding_mismatch")
            if (
                record.inventory_artifact_hashes
                != target.decision.validated_artifact_hashes
                or record.inventory_record_hashes
                != target.decision.validated_record_hashes
            ):
                raise DatasetValidationError.single("coverage_inventory_mismatch")
            availability = tuple(
                evidence
                for item in target.records
                for evidence in item.revision.availability
            )
            if record.completeness == "complete" and any(
                evidence.upper_bound is None for evidence in availability
            ):
                raise DatasetValidationError.single(
                    "coverage_unknown_availability_cannot_be_complete"
                )
            if any(
                evidence.upper_bound is not None
                and evidence.upper_bound > record.snapshot_at
                for evidence in availability
            ):
                raise DatasetValidationError.single(
                    "coverage_snapshot_precedes_inventory"
                )


def _coverage_ownership_findings(
    records: Sequence[EconomicCoverageVersionV1],
) -> tuple[ValidationFindingV1, ...]:
    by_logical: dict[object, list[EconomicCoverageVersionV1]] = defaultdict(list)
    source_keys: dict[object, set[EconomicSourceKeyV1]] = defaultdict(set)
    logical_ids: dict[EconomicSourceKeyV1, set[object]] = defaultdict(set)
    for record in records:
        logical_id = record.revision.logical_record_id
        by_logical[logical_id].append(record)
        source_keys[logical_id].add(record.source_key)
        logical_ids[record.source_key].add(logical_id)
    findings: list[ValidationFindingV1] = []
    if any(len(values) > 1 for values in source_keys.values()):
        findings.append(_finding("economic_logical_record_multiple_source_keys"))
    if any(len(values) > 1 for values in logical_ids.values()):
        findings.append(_finding("economic_source_key_multiple_logical_records"))
    for versions in by_logical.values():
        findings.extend(
            validate_assertion_chain(
                tuple(
                    AssertionVersionProjectionV1(
                        revision=record.revision, record_hash=content_hash(record)
                    )
                    for record in versions
                )
            )
        )
    return _canonical_findings(findings)


def _finding(code: str) -> ValidationFindingV1:
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
    )


def _canonical_findings(
    findings: Sequence[ValidationFindingV1],
) -> tuple[ValidationFindingV1, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.code,
                item.severity.value,
                item.message,
                tuple(reference.content_hash for reference in item.artifact_references),
            ),
        )
    )
