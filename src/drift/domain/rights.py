"""Immutable M1e contractual-rights and authorization records."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.domain.qualification import (
    ConsumerPurpose,
    ContentDispositionDuty,
    InfrastructureScopeV1,
    QualificationProfileV1,
)


class RightsDisposition(StrEnum):
    """Externally adjudicated answer to one exact rights question."""

    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class AuthorizationStatus(StrEnum):
    """Explicit acquisition or replay authorization status."""

    AUTHORIZED = "authorized"
    DENIED = "denied"
    UNKNOWN = "unknown"


class EntitlementState(StrEnum):
    """Current state of the entitlement controlling use."""

    ACTIVE = "active"
    TERMINATED = "terminated"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class RightsQuestion(StrEnum):
    """Closed set of contractual questions required by M1e."""

    INTERNAL_AUTOMATED_RESEARCH = "internal_automated_research"
    DISPLAY_USE = "display_use"
    NON_DISPLAY_USE = "non_display_use"
    MODEL_DEVELOPMENT = "model_development"
    FUTURE_TRADING_SUPPORT = "future_trading_support"
    LOCAL_STORAGE = "local_storage"
    PRIVATE_GIT_STORAGE = "private_git_storage"
    REAL_DATA_CI = "real_data_ci"
    CLOUD_PROCESSING = "cloud_processing"
    THIRD_PARTY_SERVICE_ACCESS = "third_party_service_access"
    BACKUP_STORAGE = "backup_storage"
    RAW_BYTE_RETENTION = "raw_byte_retention"
    POST_SUBSCRIPTION_RAW_USE = "post_subscription_raw_use"
    NORMALIZED_ROW_RETENTION = "normalized_row_retention"
    DERIVED_ARTIFACT_RETENTION = "derived_artifact_retention"
    MODEL_PARAMETER_RETENTION = "model_parameter_retention"
    METRIC_REPORT_RETENTION = "metric_report_retention"
    PRIVATE_FIXTURE_USE = "private_fixture_use"
    PUBLIC_FIXTURE_USE = "public_fixture_use"
    PUBLICATION = "publication"
    REDISTRIBUTION = "redistribution"
    DELETION_AND_CERTIFICATION = "deletion_and_certification"
    UPSTREAM_PUBLISHER_RESTRICTIONS = "upstream_publisher_restrictions"


class ApplicabilityStatus(StrEnum):
    """Whether a contract node applies to the assessed product scope."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ConfidentialityClass(StrEnum):
    """Permitted disclosure class for retained legal evidence."""

    PUBLIC = "public"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class UseClassificationStatus(StrEnum):
    """Resolution state of a provider-defined use classification."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


def _sorted_unique(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


class LegalPartyV1(FrozenModel):
    """One exact legal party without personal contact information."""

    schema_version: Literal["1"] = "1"
    party_id: NonBlankStr
    exact_legal_name: NonBlankStr
    role: NonBlankStr
    jurisdiction: NonBlankStr | None
    jurisdiction_unknown: bool
    evidence_references: tuple[ArtifactReference, ...]

    @field_validator("evidence_references")
    @classmethod
    def validate_references(
        cls, values: tuple[ArtifactReference, ...]
    ) -> tuple[ArtifactReference, ...]:
        if not values:
            raise ValueError("legal party requires evidence")
        checked = tuple(validate_safe_provenance_reference(item) for item in values)
        if len({item.content_hash for item in checked}) != len(checked):
            raise ValueError("legal party evidence must be unique")
        return tuple(sorted(checked, key=lambda item: item.content_hash))

    @model_validator(mode="after")
    def validate_jurisdiction(self) -> Self:
        if self.jurisdiction_unknown == (self.jurisdiction is not None):
            raise ValueError("jurisdiction requires an exact value or explicit unknown")
        return self


class UseClassificationV1(FrozenModel):
    """Provider-defined classification of the exact assessed use."""

    schema_version: Literal["1"] = "1"
    classification_id: NonBlankStr
    provider_party_id: NonBlankStr
    provider_defined_label: NonBlankStr | None
    status: UseClassificationStatus
    definition_evidence_hashes: tuple[SHA256Hash, ...]
    assessed_use: NonBlankStr

    @field_validator("definition_evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="classification evidence hashes")

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.status is UseClassificationStatus.RESOLVED:
            if (
                self.provider_defined_label is None
                or not self.definition_evidence_hashes
            ):
                raise ValueError("resolved classification requires provider evidence")
        elif self.provider_defined_label is not None:
            raise ValueError("unresolved classification cannot claim a provider label")
        return self


class AuthorizedUserV1(FrozenModel):
    """Stable nonsensitive identifier for one contract-authorized user."""

    schema_version: Literal["1"] = "1"
    user_id: NonBlankStr
    access_purpose: ConsumerPurpose
    evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("authorized user requires evidence")
        return _sorted_unique(values, label="authorized-user evidence hashes")


class ServiceProviderScopeV1(FrozenModel):
    """One permitted external service and its exact access purpose."""

    schema_version: Literal["1"] = "1"
    service_provider_id: NonBlankStr
    access_purpose: ConsumerPurpose
    evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("service provider requires evidence")
        return _sorted_unique(values, label="service-provider evidence hashes")


class ContractDocumentNodeV1(FrozenModel):
    """One exact retained document in the controlling contract topology."""

    schema_version: Literal["1"] = "1"
    node_id: NonBlankStr
    document_kind: NonBlankStr
    title: NonBlankStr
    document_version: NonBlankStr
    effective_at: UTCDateTime
    expires_at: UTCDateTime | None
    artifact_reference: ArtifactReference
    product_ids: tuple[NonBlankStr, ...]
    publisher_ids: tuple[NonBlankStr, ...]
    party_ids: tuple[NonBlankStr, ...]
    assent_evidence_hashes: tuple[SHA256Hash, ...]
    signature_evidence_hashes: tuple[SHA256Hash, ...]
    confidentiality_class: ConfidentialityClass
    applicability_status: ApplicabilityStatus

    @field_validator("artifact_reference")
    @classmethod
    def validate_reference(cls, value: ArtifactReference) -> ArtifactReference:
        return validate_safe_provenance_reference(value)

    @field_validator(
        "product_ids",
        "publisher_ids",
        "party_ids",
        "assent_evidence_hashes",
        "signature_evidence_hashes",
    )
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="contract-node collections")

    @model_validator(mode="after")
    def validate_time_bounds(self) -> Self:
        if self.expires_at is not None and self.expires_at < self.effective_at:
            raise ValueError("contract expiry cannot precede its effective time")
        return self


class ContractPrecedenceEdgeV1(FrozenModel):
    """An evidence-backed precedence or incorporation relationship."""

    schema_version: Literal["1"] = "1"
    controlling_node_id: NonBlankStr
    subordinate_node_id: NonBlankStr
    relationship: NonBlankStr
    precedence_evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("precedence_evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("contract precedence requires exact evidence")
        return _sorted_unique(values, label="precedence evidence hashes")


class MissingContractNodeV1(FrozenModel):
    """A declared absent agreement component and affected questions."""

    schema_version: Literal["1"] = "1"
    node_id: NonBlankStr
    reason: NonBlankStr
    affected_questions: tuple[RightsQuestion, ...]
    evidence_hashes: tuple[SHA256Hash, ...]

    @field_validator("affected_questions")
    @classmethod
    def canonicalize_questions(
        cls, values: tuple[RightsQuestion, ...]
    ) -> tuple[RightsQuestion, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("missing-node questions must be nonempty and unique")
        order = tuple(RightsQuestion)
        return tuple(sorted(values, key=order.index))

    @field_validator("evidence_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="missing-node evidence hashes")


class ContractTopologyV1(FrozenModel):
    """Complete assessed contract graph, including explicitly missing nodes."""

    schema_version: Literal["1"] = "1"
    topology_version: NonBlankStr
    parties: tuple[LegalPartyV1, ...]
    nodes: tuple[ContractDocumentNodeV1, ...]
    edges: tuple[ContractPrecedenceEdgeV1, ...]
    root_agreement_ids: tuple[NonBlankStr, ...]
    assessed_product_id: NonBlankStr
    assessed_publisher_ids: tuple[NonBlankStr, ...]
    missing_nodes: tuple[MissingContractNodeV1, ...]

    @field_validator("root_agreement_ids", "assessed_publisher_ids")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="contract-topology identifiers")

    @field_validator("parties")
    @classmethod
    def canonicalize_parties(
        cls, values: tuple[LegalPartyV1, ...]
    ) -> tuple[LegalPartyV1, ...]:
        return tuple(sorted(values, key=lambda item: item.party_id))

    @field_validator("nodes")
    @classmethod
    def canonicalize_nodes(
        cls, values: tuple[ContractDocumentNodeV1, ...]
    ) -> tuple[ContractDocumentNodeV1, ...]:
        return tuple(sorted(values, key=lambda item: item.node_id))

    @field_validator("edges")
    @classmethod
    def canonicalize_edges(
        cls, values: tuple[ContractPrecedenceEdgeV1, ...]
    ) -> tuple[ContractPrecedenceEdgeV1, ...]:
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.controlling_node_id,
                    item.subordinate_node_id,
                    item.relationship,
                    item.precedence_evidence_hashes,
                ),
            )
        )

    @field_validator("missing_nodes")
    @classmethod
    def canonicalize_missing_nodes(
        cls, values: tuple[MissingContractNodeV1, ...]
    ) -> tuple[MissingContractNodeV1, ...]:
        return tuple(sorted(values, key=lambda item: item.node_id))


class RightsAnswerV1(FrozenModel):
    """One explicit human/legal answer bound to exact controlling evidence."""

    schema_version: Literal["1"] = "1"
    question: RightsQuestion
    disposition: RightsDisposition
    controlling_node_hashes: tuple[SHA256Hash, ...]
    evidence_hashes: tuple[SHA256Hash, ...]
    scope_hash: SHA256Hash
    valid_from: UTCDateTime
    valid_until: UTCDateTime
    limitations: tuple[NonBlankStr, ...]
    adjudicator_identity: NonBlankStr

    @field_validator("controlling_node_hashes", "evidence_hashes", "limitations")
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="rights-answer collections")

    @model_validator(mode="after")
    def validate_answer(self) -> Self:
        if self.valid_until < self.valid_from:
            raise ValueError("rights-answer validity cannot be reversed")
        if self.disposition is RightsDisposition.ALLOWED:
            if not self.controlling_node_hashes or not self.evidence_hashes:
                raise ValueError("allowed answer requires controlling evidence")
        elif self.disposition is RightsDisposition.DENIED and (
            not self.controlling_node_hashes or not self.evidence_hashes
        ):
            raise ValueError("denied answer requires controlling evidence")
        if self.disposition is not RightsDisposition.ALLOWED and not self.limitations:
            raise ValueError("denied or unknown answer requires limitations")
        return self


class ContentRightsPolicyV1(FrozenModel):
    """Prospective contractual policy created before any content bytes exist."""

    schema_version: Literal["1"] = "1"
    policy_id: NonBlankStr
    provider_contractual_class: NonBlankStr
    object_scope: NonBlankStr
    controlling_provision_hashes: tuple[SHA256Hash, ...]
    permitted_purposes: tuple[ConsumerPurpose, ...]
    permitted_user_ids: tuple[NonBlankStr, ...]
    permitted_contractor_ids: tuple[NonBlankStr, ...]
    permitted_service_provider_ids: tuple[NonBlankStr, ...]
    permitted_location_ids: tuple[NonBlankStr, ...]
    permitted_backup_location_ids: tuple[NonBlankStr, ...]
    machine_identity: NonBlankStr
    shared_account: bool
    real_data_ci: bool
    cloud_processing: bool
    private_store_policy_hash: SHA256Hash
    retention_until: UTCDateTime | None
    post_termination_use: RightsDisposition
    disposition_duty: ContentDispositionDuty
    backup_allowed: bool
    backup_rule: NonBlankStr
    policy_hash: SHA256Hash

    @field_validator(
        "controlling_provision_hashes", "permitted_user_ids", "permitted_location_ids"
    )
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("content-rights policy collections must be nonempty")
        return _sorted_unique(values, label="content-rights policy collections")

    @field_validator(
        "permitted_contractor_ids",
        "permitted_service_provider_ids",
        "permitted_backup_location_ids",
    )
    @classmethod
    def canonicalize_optional_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="content-rights optional scopes")

    @field_validator("permitted_purposes")
    @classmethod
    def canonicalize_purposes(
        cls, values: tuple[ConsumerPurpose, ...]
    ) -> tuple[ConsumerPurpose, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("content policy purposes must be nonempty and unique")
        order = tuple(ConsumerPurpose)
        return tuple(sorted(values, key=order.index))


class ContentRightsBindingV1(FrozenModel):
    """A later content object bound to a frozen prospective rights policy."""

    schema_version: Literal["1"] = "1"
    content_hash: SHA256Hash
    policy_hash: SHA256Hash
    provider_contractual_class: NonBlankStr
    controlling_provision_hashes: tuple[SHA256Hash, ...]
    permitted_purposes: tuple[ConsumerPurpose, ...]
    permitted_user_ids: tuple[NonBlankStr, ...]
    permitted_contractor_ids: tuple[NonBlankStr, ...]
    permitted_service_provider_ids: tuple[NonBlankStr, ...]
    permitted_location_ids: tuple[NonBlankStr, ...]
    permitted_backup_location_ids: tuple[NonBlankStr, ...]
    machine_identity: NonBlankStr
    shared_account: bool
    real_data_ci: bool
    cloud_processing: bool
    private_store_policy_hash: SHA256Hash
    retention_until: UTCDateTime | None
    post_termination_use: RightsDisposition
    disposition_duty: ContentDispositionDuty
    backup_allowed: bool
    backup_rule: NonBlankStr
    frozen_assessment_hash: SHA256Hash

    @field_validator(
        "controlling_provision_hashes", "permitted_user_ids", "permitted_location_ids"
    )
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("content-rights binding collections must be nonempty")
        return _sorted_unique(values, label="content-rights binding collections")

    @field_validator(
        "permitted_contractor_ids",
        "permitted_service_provider_ids",
        "permitted_backup_location_ids",
    )
    @classmethod
    def canonicalize_optional_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="content-rights binding optional scopes")

    @field_validator("permitted_purposes")
    @classmethod
    def canonicalize_purposes(
        cls, values: tuple[ConsumerPurpose, ...]
    ) -> tuple[ConsumerPurpose, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("content binding purposes must be nonempty and unique")
        order = tuple(ConsumerPurpose)
        return tuple(sorted(values, key=order.index))


class PurposeRightsResultV1(FrozenModel):
    """Explicit aggregate adjudication for one consumer purpose."""

    schema_version: Literal["1"] = "1"
    purpose: ConsumerPurpose
    disposition: RightsDisposition
    evidence_hashes: tuple[SHA256Hash, ...]
    limitations: tuple[NonBlankStr, ...]

    @field_validator("evidence_hashes", "limitations")
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="purpose-rights collections")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if not self.evidence_hashes:
            raise ValueError("purpose rights result requires evidence")
        if self.disposition is not RightsDisposition.ALLOWED and not self.limitations:
            raise ValueError("non-allowed purpose result requires limitations")
        return self


class RightsAssessmentV1(FrozenModel):
    """Immutable external rights adjudication for one purpose profile."""

    schema_version: Literal["1"] = "1"
    assessment_id: UUID7
    profile_hash: SHA256Hash
    topology_hash: SHA256Hash
    assessed_at: UTCDateTime
    valid_from: UTCDateTime
    valid_until: UTCDateTime
    entitlement_state: EntitlementState
    classification: UseClassificationV1
    authorized_users: tuple[AuthorizedUserV1, ...]
    service_providers: tuple[ServiceProviderScopeV1, ...]
    answers: tuple[RightsAnswerV1, ...]
    notice_evidence_hashes: tuple[SHA256Hash, ...]
    content_rights_policies: tuple[ContentRightsPolicyV1, ...]
    reassessment_triggers: tuple[NonBlankStr, ...]
    policy_hash: SHA256Hash
    assessor_identity: NonBlankStr
    purpose_results: tuple[PurposeRightsResultV1, ...]

    @field_validator("notice_evidence_hashes", "reassessment_triggers")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("rights-assessment collections must be nonempty")
        return _sorted_unique(values, label="rights-assessment collections")

    @field_validator("answers")
    @classmethod
    def canonicalize_answers(
        cls, values: tuple[RightsAnswerV1, ...]
    ) -> tuple[RightsAnswerV1, ...]:
        questions = tuple(item.question for item in values)
        if len(questions) != len(set(questions)) or set(questions) != set(
            RightsQuestion
        ):
            raise ValueError("rights assessment requires every rights question once")
        order = tuple(RightsQuestion)
        return tuple(sorted(values, key=lambda item: order.index(item.question)))

    @field_validator("authorized_users")
    @classmethod
    def canonicalize_users(
        cls, values: tuple[AuthorizedUserV1, ...]
    ) -> tuple[AuthorizedUserV1, ...]:
        keys = tuple((item.access_purpose, item.user_id) for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("authorized users must be unique")
        return tuple(
            sorted(values, key=lambda item: (item.access_purpose, item.user_id))
        )

    @field_validator("service_providers")
    @classmethod
    def canonicalize_services(
        cls, values: tuple[ServiceProviderScopeV1, ...]
    ) -> tuple[ServiceProviderScopeV1, ...]:
        keys = tuple((item.access_purpose, item.service_provider_id) for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("service-provider scopes must be unique")
        return tuple(
            sorted(
                values,
                key=lambda item: (item.access_purpose, item.service_provider_id),
            )
        )

    @field_validator("content_rights_policies")
    @classmethod
    def canonicalize_policies(
        cls, values: tuple[ContentRightsPolicyV1, ...]
    ) -> tuple[ContentRightsPolicyV1, ...]:
        keys = tuple((item.policy_id, item.policy_hash) for item in values)
        if len(keys) != len(set(keys)) or len(
            {item.policy_id for item in values}
        ) != len(values):
            raise ValueError("content-rights policies must be unique")
        return tuple(
            sorted(values, key=lambda item: (item.policy_id, item.policy_hash))
        )

    @field_validator("purpose_results")
    @classmethod
    def canonicalize_results(
        cls, values: tuple[PurposeRightsResultV1, ...]
    ) -> tuple[PurposeRightsResultV1, ...]:
        purposes = tuple(item.purpose for item in values)
        if not values or len(purposes) != len(set(purposes)):
            raise ValueError("purpose rights results must be nonempty and unique")
        order = tuple(ConsumerPurpose)
        return tuple(sorted(values, key=lambda item: order.index(item.purpose)))

    @model_validator(mode="after")
    def validate_time_bounds(self) -> Self:
        if self.valid_until < self.valid_from or not (
            self.valid_from <= self.assessed_at <= self.valid_until
        ):
            raise ValueError("rights assessment has invalid validity bounds")
        if not self.content_rights_policies:
            raise ValueError("rights assessment requires prospective content policies")
        return self


@dataclass(frozen=True, slots=True)
class RightsEvidenceContext:
    """Exact category-resolved legal evidence bytes for one assessment."""

    topology: ContractTopologyV1
    contract_evidence: tuple[VerifiedArtifactBytes, ...]
    assent_evidence: tuple[VerifiedArtifactBytes, ...]
    amendment_evidence: tuple[VerifiedArtifactBytes, ...]
    schedule_evidence: tuple[VerifiedArtifactBytes, ...]
    policy_evidence: tuple[VerifiedArtifactBytes, ...]
    notice_evidence: tuple[VerifiedArtifactBytes, ...]
    classification_evidence: tuple[VerifiedArtifactBytes, ...]
    adjudication_evidence: tuple[VerifiedArtifactBytes, ...]


@dataclass(frozen=True, slots=True)
class ValidatedRightsAssessment:
    """Runtime-only exact assessment, profile, topology, and evidence snapshot."""

    assessment: RightsAssessmentV1
    profile: QualificationProfileV1
    topology: ContractTopologyV1
    evidence: RightsEvidenceContext


class AcquisitionEligibilityV1(FrozenModel):
    """Purpose-separated rights eligibility, never an acquisition approval."""

    schema_version: Literal["1"] = "1"
    profile_set_hash: SHA256Hash
    assessment_hashes: tuple[SHA256Hash, ...]
    eligible_profile_hashes: tuple[SHA256Hash, ...]
    denied_profile_hashes: tuple[SHA256Hash, ...]
    unresolved_profile_hashes: tuple[SHA256Hash, ...]
    product_id: NonBlankStr
    scope_hash: SHA256Hash
    valid_from: UTCDateTime
    valid_until: UTCDateTime
    private_store_policy_hash: SHA256Hash
    reasons: tuple[NonBlankStr, ...]
    policy_identity: SHA256Hash

    @field_validator(
        "assessment_hashes",
        "eligible_profile_hashes",
        "denied_profile_hashes",
        "unresolved_profile_hashes",
        "reasons",
    )
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="acquisition eligibility collections")

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        sets = (
            set(self.eligible_profile_hashes),
            set(self.denied_profile_hashes),
            set(self.unresolved_profile_hashes),
        )
        if any(
            left & right
            for index, left in enumerate(sets)
            for right in sets[index + 1 :]
        ):
            raise ValueError("eligibility profile sets must be disjoint")
        if self.valid_until < self.valid_from:
            raise ValueError("eligibility validity cannot be reversed")
        return self


class AcquisitionApprovalV1(FrozenModel):
    """External user approval, separate from a legal rights result."""

    schema_version: Literal["1"] = "1"
    approval_id: UUID7
    eligibility_hash: SHA256Hash
    approved_profile_hashes: tuple[SHA256Hash, ...]
    approved_product_id: NonBlankStr
    approved_scope_hash: SHA256Hash
    approval_evidence_hashes: tuple[SHA256Hash, ...]
    authorizer_scope_evidence_hashes: tuple[SHA256Hash, ...]
    decision_evidence_hashes: tuple[SHA256Hash, ...]
    expiry_evidence_hashes: tuple[SHA256Hash, ...]
    authorizer_identity: NonBlankStr
    decision_time: UTCDateTime
    expires_at: UTCDateTime
    purchase_authority: Literal[False] = False
    terms_acceptance_authority: Literal[False] = False

    @field_validator(
        "approved_profile_hashes",
        "approval_evidence_hashes",
        "authorizer_scope_evidence_hashes",
        "decision_evidence_hashes",
        "expiry_evidence_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="acquisition approval hashes")

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        if not self.approved_profile_hashes:
            raise ValueError("acquisition approval requires at least one profile")
        if not all(
            (
                self.approval_evidence_hashes,
                self.authorizer_scope_evidence_hashes,
                self.decision_evidence_hashes,
                self.expiry_evidence_hashes,
            )
        ):
            raise ValueError("acquisition approval requires complete external evidence")
        if self.expires_at < self.decision_time:
            raise ValueError("approval expiry cannot precede its decision")
        return self


@dataclass(frozen=True, slots=True)
class ApprovalEvidenceContext:
    """Hash-resolved evidence for an external acquisition approval."""

    approval_evidence: tuple[VerifiedArtifactBytes, ...]
    authorizer_scope_evidence: tuple[VerifiedArtifactBytes, ...]
    decision_evidence: tuple[VerifiedArtifactBytes, ...]
    expiry_evidence: tuple[VerifiedArtifactBytes, ...]


class AcquisitionAuthorizationV1(FrozenModel):
    """Verified intersection of rights eligibility and external approval."""

    schema_version: Literal["1"] = "1"
    authorization_id: UUID7
    eligibility_hash: SHA256Hash
    approval_hash: SHA256Hash
    authorized_profile_hashes: tuple[SHA256Hash, ...]
    product_id: NonBlankStr
    scope_hash: SHA256Hash
    authorized_from: UTCDateTime
    authorized_until: UTCDateTime
    private_store_policy_hash: SHA256Hash
    status: AuthorizationStatus
    reasons: tuple[NonBlankStr, ...]
    authorization_identity: NonBlankStr

    @field_validator("authorized_profile_hashes", "reasons")
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="acquisition authorization collections")

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.authorized_until < self.authorized_from:
            raise ValueError("authorization validity cannot be reversed")
        if self.status is AuthorizationStatus.AUTHORIZED:
            if not self.authorized_profile_hashes or not self.reasons:
                raise ValueError("authorized acquisition requires profiles and reasons")
        elif self.authorized_profile_hashes:
            raise ValueError(
                "non-authorized acquisition cannot name authorized profiles"
            )
        return self


class ReplayAuthorizationRequestV1(FrozenModel):
    """Purpose-specific request for one current offline replay decision."""

    schema_version: Literal["1"] = "1"
    request_id: UUID7
    profile_hash: SHA256Hash
    snapshot_hash: SHA256Hash
    environment_closure_hash: SHA256Hash
    requested_user_ids: tuple[NonBlankStr, ...]
    requested_infrastructure: InfrastructureScopeV1
    current_time: UTCDateTime
    entitlement_evidence_hashes: tuple[SHA256Hash, ...]
    termination_evidence_hashes: tuple[SHA256Hash, ...]
    notice_evidence_hashes: tuple[SHA256Hash, ...]
    purpose: ConsumerPurpose

    @field_validator(
        "requested_user_ids",
        "entitlement_evidence_hashes",
        "termination_evidence_hashes",
        "notice_evidence_hashes",
    )
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="replay request collections")

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.requested_user_ids != self.requested_infrastructure.user_ids:
            raise ValueError("replay users must match requested infrastructure")
        if not self.entitlement_evidence_hashes:
            raise ValueError("replay request requires current entitlement evidence")
        return self


class ReplayAuthorizationDecisionV1(FrozenModel):
    """Explicit current replay adjudication, independent of acquisition."""

    schema_version: Literal["1"] = "1"
    request_hash: SHA256Hash
    new_assessment_hash: SHA256Hash
    status: AuthorizationStatus
    evidence_hashes: tuple[SHA256Hash, ...]
    reasons: tuple[NonBlankStr, ...]
    policy_hash: SHA256Hash
    decision_id: UUID7
    decision_time: UTCDateTime

    @field_validator("evidence_hashes", "reasons")
    @classmethod
    def canonicalize_collections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="replay decision collections")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if not self.evidence_hashes or not self.reasons:
            raise ValueError("replay decision requires evidence and reasons")
        return self


@dataclass(frozen=True, slots=True)
class ReplayAuthorizationEvidenceContext:
    """Fresh purpose-specific evidence snapshot for one replay decision."""

    current_contract_evidence: tuple[VerifiedArtifactBytes, ...]
    entitlement_evidence: tuple[VerifiedArtifactBytes, ...]
    termination_evidence: tuple[VerifiedArtifactBytes, ...]
    notice_evidence: tuple[VerifiedArtifactBytes, ...]
    user_infrastructure_evidence: tuple[VerifiedArtifactBytes, ...]
    request_evidence: tuple[VerifiedArtifactBytes, ...]
    decision_evidence: tuple[VerifiedArtifactBytes, ...]
