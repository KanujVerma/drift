"""Domain models for provider-neutral qualification adapters and mappings."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from drift.domain.common import FrozenModel, SHA256Hash
from drift.domain.economic_coverage import EconomicCoverageVersionV1
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicSettlementVersionV1,
)
from drift.domain.observations import (
    DailySourceObservationVersionV1,
    ObservationCoverageVersionV1,
)
from drift.domain.qualification import ConsumerPurpose, QualificationDimension
from drift.domain.securities import (
    ExternalIdentifierMappingVersionV1,
    IdentityAssignmentVersionV1,
    IdentityRelationshipVersionV1,
    ListingHistoryCoverageVersionV1,
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
    SecurityClassificationVersionV1,
)
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduledSessionVersionV1,
    SessionCoverageVersionV1,
)
from drift.domain.universes import (
    SourceUniverseDefinitionVersionV1,
    UniverseMembershipVersionV1,
)
from drift.serialization.canonical import content_hash

CandidateRecordModel = (
    IdentityAssignmentVersionV1
    | IdentityRelationshipVersionV1
    | ExternalIdentifierMappingVersionV1
    | SecurityClassificationVersionV1
    | ListingRoleVersionV1
    | ListingLifecycleVersionV1
    | ListingTerminationVersionV1
    | ListingHistoryCoverageVersionV1
    | SourceUniverseDefinitionVersionV1
    | UniverseMembershipVersionV1
    | CorporateActionTermsVersionV1
    | EconomicEffectVersionV1
    | EconomicSettlementVersionV1
    | EconomicCoverageVersionV1
    | DailySourceObservationVersionV1
    | ObservationCoverageVersionV1
    | ScheduledSessionVersionV1
    | RealizedSessionVersionV1
    | SessionCoverageVersionV1
)


class MappingDisposition(StrEnum):
    MAPPED = "mapped"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class OperationKind(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"


class AdapterIdentityV1(FrozenModel):
    """Immutable identity and build metadata for a qualification adapter."""

    adapter_id: str
    adapter_version: str
    supported_profile_set_hash: SHA256Hash
    supported_profile_hashes: tuple[SHA256Hash, ...]
    provider_schema_hash: SHA256Hash
    provider_methodology_hash: SHA256Hash
    semantic_policy_hash: SHA256Hash
    installed_source_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_adapter_identity(self) -> Self:
        if not self.adapter_id:
            raise ValueError("adapter_id must not be empty")
        if not self.adapter_version:
            raise ValueError("adapter_version must not be empty")
        if not self.supported_profile_hashes:
            raise ValueError("supported_profile_hashes must not be empty")
        return self


class NativeRecordReferenceV1(FrozenModel):
    """Lineage pointer from emitted records back to provider native objects."""

    native_byte_hash: SHA256Hash
    decoded_record_hash: SHA256Hash
    native_key: str
    byte_layer_rule_hash: SHA256Hash
    availability_evidence_hash: SHA256Hash


class FieldMappingDecisionV1(FrozenModel):
    """Explicit mapping decision for a single target field."""

    target_role: str
    target_field: str
    source_native_field: str
    disposition: MappingDisposition
    rule_evidence_hashes: tuple[SHA256Hash, ...]
    availability_rule: str
    is_lossy: bool
    limitations: tuple[str, ...]
    affected_dimension: QualificationDimension


class EmittedRecordMappingV1(FrozenModel):
    """Mapping record connecting an emitted canonical record to native inputs."""

    emitted_record_hash: SHA256Hash
    native_record_references: tuple[NativeRecordReferenceV1, ...]
    field_mapping_decision_hashes: tuple[SHA256Hash, ...]
    operation_kind: OperationKind
    transformation_evidence_hashes: tuple[SHA256Hash, ...]


def provider_mapping_report_hash(report: ProviderMappingReportV1) -> SHA256Hash:
    """Compute canonical hash for ProviderMappingReportV1 excluding report_hash."""
    dump = report.model_dump(mode="python")
    dump.pop("report_hash", None)
    return content_hash(dump)


class ProviderMappingReportV1(FrozenModel):
    """Auditable mapping report describing how native records were transformed."""

    schema_version: str = "1"
    adapter_identity: AdapterIdentityV1
    profile_set_hash: SHA256Hash
    profile_hashes: tuple[SHA256Hash, ...]
    receipt_hashes: tuple[SHA256Hash, ...]
    native_field_inventory: tuple[str, ...]
    field_decisions: tuple[FieldMappingDecisionV1, ...]
    unsupported_native_values: tuple[str, ...]
    emitted_record_mappings: tuple[EmittedRecordMappingV1, ...]
    emitted_candidate_dataset_hashes: tuple[SHA256Hash, ...]
    native_records_count: int
    emitted_records_count: int
    coverage_reconciliation_pass: bool
    limitations: tuple[str, ...]
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected = provider_mapping_report_hash(self)
        if self.report_hash != expected:
            raise ValueError(
                f"report hash mismatch: expected {expected}, got {self.report_hash}"
            )
        return self


class DatasetBlueprintV1(FrozenModel):
    """Structural blueprint for one emitted candidate dataset."""

    dataset_role: str
    record_model_id: str
    partition_object_hashes: tuple[SHA256Hash, ...]
    supporting_artifact_hashes: tuple[SHA256Hash, ...]
    validation_run_hash: SHA256Hash
    bundle_group: str


def candidate_context_blueprint_hash(
    blueprint: CandidateContextBlueprintV1,
) -> SHA256Hash:
    """Compute hash for CandidateContextBlueprintV1 excluding blueprint_hash."""
    dump = blueprint.model_dump(mode="python")
    dump.pop("blueprint_hash", None)
    return content_hash(dump)


class CandidateContextBlueprintV1(FrozenModel):
    """Blueprint linking candidate datasets into authentic resolution contexts."""

    schema_version: str = "1"
    dataset_blueprints: tuple[DatasetBlueprintV1, ...]
    cross_context_links: tuple[str, ...]
    blueprint_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_blueprint(self) -> Self:
        expected = candidate_context_blueprint_hash(self)
        if self.blueprint_hash != expected:
            raise ValueError(
                f"blueprint hash mismatch: expected {expected}, "
                f"got {self.blueprint_hash}"
            )
        return self


def qualified_source_handoff_hash(handoff: QualifiedSourceHandoffV1) -> SHA256Hash:
    """Compute canonical hash for QualifiedSourceHandoffV1 excluding handoff_hash."""
    dump = handoff.model_dump(mode="python")
    dump.pop("handoff_hash", None)
    return content_hash(dump)


class QualifiedSourceHandoffV1(FrozenModel):
    """Immutable handoff object representing a qualified real-source candidate."""

    schema_version: str = "1"
    handoff_id: UUID
    purpose: ConsumerPurpose
    profile_hash: SHA256Hash
    report_hash: SHA256Hash
    target_hash: SHA256Hash
    snapshot_hash: SHA256Hash
    rights_assessment_hash: SHA256Hash
    universe_references: tuple[str, ...]
    economic_outcome_references: tuple[str, ...]
    observation_view_references: tuple[str, ...]
    session_view_references: tuple[str, ...]
    environment_closure_hash: SHA256Hash | None = None
    replay_authorization_hash: SHA256Hash | None = None
    limitations: tuple[str, ...] = ()
    handoff_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_handoff(self) -> Self:
        expected = qualified_source_handoff_hash(self)
        if self.handoff_hash != expected:
            raise ValueError(
                f"handoff hash mismatch: expected {expected}, got {self.handoff_hash}"
            )
        return self
