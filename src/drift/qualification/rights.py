"""Fail-closed verification of M1e rights, acquisition, and replay authority."""

from dataclasses import dataclass
from hashlib import sha256

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactReference
from drift.domain.dataset_validation import (
    FindingSeverity,
    ValidationFindingV1,
)
from drift.domain.qualification import (
    ContentDispositionDuty,
    PilotProfileSetV1,
    QualificationProfileV1,
    qualification_profile_hash,
)
from drift.domain.rights import (
    AcquisitionApprovalV1,
    AcquisitionAuthorizationV1,
    AcquisitionEligibilityV1,
    ApplicabilityStatus,
    ApprovalEvidenceContext,
    AuthorizationStatus,
    ConfidentialityClass,
    ContentRightsBindingV1,
    ContentRightsPolicyV1,
    ContractDocumentNodeV1,
    ContractTopologyV1,
    EntitlementState,
    ReplayAuthorizationDecisionV1,
    ReplayAuthorizationEvidenceContext,
    ReplayAuthorizationRequestV1,
    RightsAssessmentV1,
    RightsDisposition,
    RightsEvidenceContext,
    RightsQuestion,
    UseClassificationStatus,
    ValidatedRightsAssessment,
)
from drift.serialization.canonical import content_hash


@dataclass(frozen=True, slots=True)
class AcquisitionAuthorizationVerificationBundle:
    """Every object needed to reverify acquisition authority."""

    profiles: PilotProfileSetV1
    assessments: tuple[ValidatedRightsAssessment, ...]
    eligibility: AcquisitionEligibilityV1
    approval: AcquisitionApprovalV1
    approval_evidence: ApprovalEvidenceContext
    authorization: AcquisitionAuthorizationV1


@dataclass(frozen=True, slots=True)
class ReplayAuthorizationVerificationBundle:
    """Every current object needed to reverify one replay decision."""

    request: ReplayAuthorizationRequestV1
    decision: ReplayAuthorizationDecisionV1
    current_assessment: ValidatedRightsAssessment
    profile: QualificationProfileV1
    evidence: ReplayAuthorizationEvidenceContext


_MARKETING_KINDS = frozenset(
    {"marketing", "marketing_copy", "sales_email", "website", "brochure"}
)


def _finding(
    code: str,
    *,
    node: ContractDocumentNodeV1 | None = None,
    reference: ArtifactReference | None = None,
) -> ValidationFindingV1:
    references: tuple[ArtifactReference, ...]
    if node is not None:
        references = (node.artifact_reference,)
    elif reference is not None:
        references = (reference,)
    else:
        references = ()
    return ValidationFindingV1(
        code=code,
        severity=FindingSeverity.ERROR,
        message=code.replace("_", " "),
        artifact_references=references,
    )


def validate_contract_topology(
    topology: ContractTopologyV1,
) -> tuple[ValidationFindingV1, ...]:
    """Return deterministic fail-closed findings for one exact contract graph."""
    findings: list[ValidationFindingV1] = []
    node_ids = tuple(node.node_id for node in topology.nodes)
    party_ids = tuple(party.party_id for party in topology.parties)
    if not node_ids or not topology.root_agreement_ids:
        findings.append(_finding("absent_root_agreement"))
    if not party_ids:
        findings.append(_finding("absent_legal_party"))
    if len(node_ids) != len(set(node_ids)):
        findings.append(_finding("duplicate_contract_node"))
    if len(party_ids) != len(set(party_ids)):
        findings.append(_finding("duplicate_legal_party"))
    known_nodes = set(node_ids)
    known_parties = set(party_ids)
    for root in topology.root_agreement_ids:
        if root not in known_nodes:
            findings.append(_finding("missing_root_agreement"))

    edge_keys = tuple(
        (
            edge.controlling_node_id,
            edge.subordinate_node_id,
            edge.relationship,
            edge.precedence_evidence_hashes,
        )
        for edge in topology.edges
    )
    if len(edge_keys) != len(set(edge_keys)):
        findings.append(_finding("duplicate_contract_precedence_edge"))
    if any(
        edge.controlling_node_id not in known_nodes
        or edge.subordinate_node_id not in known_nodes
        for edge in topology.edges
    ):
        findings.append(_finding("missing_incorporated_agreement"))
    if _has_cycle(topology):
        findings.append(_finding("contract_precedence_cycle"))
    if known_nodes - _reachable_nodes(topology):
        findings.append(_finding("orphan_contract_node"))

    assessed_publishers = set(topology.assessed_publisher_ids)
    for node in topology.nodes:
        if any(party_id not in known_parties for party_id in node.party_ids):
            findings.append(_finding("unknown_contract_party", node=node))
        if node.applicability_status is ApplicabilityStatus.UNKNOWN:
            findings.append(_finding("unknown_contract_applicability", node=node))
        if node.applicability_status is not ApplicabilityStatus.APPLICABLE:
            continue
        if topology.assessed_product_id not in node.product_ids:
            findings.append(_finding("unmatched_contract_product", node=node))
        if not assessed_publishers.issubset(node.publisher_ids):
            findings.append(_finding("unmatched_contract_publisher", node=node))
        if not (node.assent_evidence_hashes or node.signature_evidence_hashes):
            findings.append(_finding("absent_contract_assent", node=node))
        if node.confidentiality_class is not ConfidentialityClass.PUBLIC and not (
            _is_private_content_addressed(node.artifact_reference)
        ):
            findings.append(
                _finding("confidential_evidence_public_reference", node=node)
            )
    confidential_hashes = {
        node.artifact_reference.content_hash
        for node in topology.nodes
        if node.confidentiality_class is not ConfidentialityClass.PUBLIC
    }
    for party in topology.parties:
        for reference in party.evidence_references:
            if reference.content_hash in confidential_hashes and not (
                _is_private_content_addressed(reference)
            ):
                findings.append(
                    _finding(
                        "confidential_evidence_public_reference",
                        reference=reference,
                    )
                )
    if topology.missing_nodes:
        findings.append(_finding("missing_contract_node"))
    missing_ids = tuple(item.node_id for item in topology.missing_nodes)
    if len(missing_ids) != len(set(missing_ids)):
        findings.append(_finding("duplicate_missing_contract_node"))
    if known_nodes & set(missing_ids):
        findings.append(_finding("contradictory_missing_contract_node"))
    return tuple(sorted(findings, key=lambda item: item.code))


def _is_private_content_addressed(reference: ArtifactReference) -> bool:
    return reference.location == f"drift+sha256://{reference.content_hash}"


def _has_cycle(topology: ContractTopologyV1) -> bool:
    graph: dict[str, set[str]] = {}
    for edge in topology.edges:
        graph.setdefault(edge.controlling_node_id, set()).add(edge.subordinate_node_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(child) for child in graph.get(node_id, ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in graph)


def _reachable_nodes(topology: ContractTopologyV1) -> set[str]:
    graph: dict[str, set[str]] = {}
    for edge in topology.edges:
        graph.setdefault(edge.controlling_node_id, set()).add(edge.subordinate_node_id)
    reached: set[str] = set()
    pending = list(topology.root_agreement_ids)
    while pending:
        node_id = pending.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        pending.extend(graph.get(node_id, ()))
    return reached


def _verify_bytes(values: tuple[VerifiedArtifactBytes, ...]) -> tuple[str, ...]:
    hashes: list[str] = []
    for item in values:
        if (
            item.byte_size != len(item.data)
            or item.content_hash != sha256(item.data).hexdigest()
        ):
            raise ValueError("evidence bytes are not hash-verified")
        hashes.append(item.content_hash)
    if len(hashes) != len(set(hashes)):
        raise ValueError("evidence snapshot contains duplicate hashes")
    return tuple(sorted(hashes))


def _require_exact(
    label: str,
    expected: tuple[str, ...] | set[str],
    evidence: tuple[VerifiedArtifactBytes, ...],
) -> None:
    actual = set(_verify_bytes(evidence))
    if set(expected) != actual:
        raise ValueError(f"{label} evidence is not the exact referenced set")


def _all_rights_evidence(
    context: RightsEvidenceContext,
) -> tuple[VerifiedArtifactBytes, ...]:
    return (
        *context.contract_evidence,
        *context.assent_evidence,
        *context.amendment_evidence,
        *context.schedule_evidence,
        *context.policy_evidence,
        *context.notice_evidence,
        *context.classification_evidence,
        *context.adjudication_evidence,
    )


def content_rights_policy_hash(policy: ContentRightsPolicyV1) -> str:
    """Hash a prospective policy without its declared self-hash field."""
    return content_hash(policy.model_dump(mode="python", exclude={"policy_hash"}))


def bind_content_rights(
    *,
    content: VerifiedArtifactBytes,
    policy: ContentRightsPolicyV1,
    assessment: ValidatedRightsAssessment,
) -> ContentRightsBindingV1:
    """Bind bytes only after both the policy and assessment identities exist."""
    revalidated = validate_rights_assessment(
        assessment.profile,
        assessment.assessment,
        assessment.evidence,
    )
    if revalidated != assessment:
        raise ValueError("rights assessment does not reverify")
    if (
        content.byte_size != len(content.data)
        or content.content_hash != sha256(content.data).hexdigest()
    ):
        raise ValueError("content bytes are not hash-verified")
    result = next(
        item
        for item in assessment.assessment.purpose_results
        if item.purpose is assessment.profile.purpose
    )
    if result.disposition is not RightsDisposition.ALLOWED:
        raise ValueError("purpose rights result must be ALLOWED before binding")
    if policy.policy_hash != content_rights_policy_hash(policy):
        raise ValueError("content-rights policy hash mismatch")
    if policy not in assessment.assessment.content_rights_policies:
        raise ValueError("content-rights policy is not in the frozen assessment")
    return ContentRightsBindingV1(
        content_hash=content.content_hash,
        policy_hash=policy.policy_hash,
        provider_contractual_class=policy.provider_contractual_class,
        controlling_provision_hashes=policy.controlling_provision_hashes,
        permitted_purposes=policy.permitted_purposes,
        permitted_user_ids=policy.permitted_user_ids,
        permitted_contractor_ids=policy.permitted_contractor_ids,
        permitted_service_provider_ids=policy.permitted_service_provider_ids,
        permitted_location_ids=policy.permitted_location_ids,
        permitted_backup_location_ids=policy.permitted_backup_location_ids,
        machine_identity=policy.machine_identity,
        shared_account=policy.shared_account,
        real_data_ci=policy.real_data_ci,
        cloud_processing=policy.cloud_processing,
        private_store_policy_hash=policy.private_store_policy_hash,
        retention_until=policy.retention_until,
        post_termination_use=policy.post_termination_use,
        disposition_duty=policy.disposition_duty,
        backup_allowed=policy.backup_allowed,
        backup_rule=policy.backup_rule,
        frozen_assessment_hash=content_hash(assessment.assessment),
    )


def validate_rights_assessment(
    profile: QualificationProfileV1,
    assessment: RightsAssessmentV1,
    evidence: RightsEvidenceContext,
) -> ValidatedRightsAssessment:
    """Verify an external adjudication without creating a legal conclusion."""
    profile_hash = qualification_profile_hash(profile)
    if assessment.profile_hash != profile_hash:
        raise ValueError("rights assessment profile hash mismatch")
    if assessment.topology_hash != content_hash(evidence.topology):
        raise ValueError("rights assessment topology hash mismatch")
    if evidence.topology.assessed_product_id != profile.provider.product_id:
        raise ValueError("contract product does not match qualification profile")
    if set(evidence.topology.assessed_publisher_ids) != set(
        profile.provider.publisher_ids
    ):
        raise ValueError("contract publishers do not match qualification profile")
    providers = tuple(
        party for party in evidence.topology.parties if party.role == "provider"
    )
    if len(providers) != 1 or (
        providers[0].party_id != profile.provider.provider_legal_id
        or providers[0].exact_legal_name != profile.provider.provider_legal_name
    ):
        raise ValueError("provider legal party does not match frozen profile")
    subscribers = tuple(
        party for party in evidence.topology.parties if party.role == "subscriber"
    )
    if len(subscribers) != 1 or (
        subscribers[0].exact_legal_name != profile.subscriber.subscriber_legal_entity
    ):
        raise ValueError("subscriber legal party does not match frozen profile")
    expected_party_ids = {providers[0].party_id, subscribers[0].party_id}
    if len(evidence.topology.parties) != 2 or any(
        node.applicability_status is ApplicabilityStatus.APPLICABLE
        and set(node.party_ids) != expected_party_ids
        for node in evidence.topology.nodes
    ):
        raise ValueError("contract topology parties do not match frozen profile")

    topology_findings = validate_contract_topology(evidence.topology)
    blocking = {
        item.code for item in topology_findings if item.code != "missing_contract_node"
    }
    if blocking:
        raise ValueError(
            "contract topology is not complete: " + ", ".join(sorted(blocking))
        )

    contract_hashes = {
        *(node.artifact_reference.content_hash for node in evidence.topology.nodes),
        *(
            reference.content_hash
            for party in evidence.topology.parties
            for reference in party.evidence_references
        ),
        *(
            hash_value
            for edge in evidence.topology.edges
            for hash_value in edge.precedence_evidence_hashes
        ),
        *(
            hash_value
            for missing in evidence.topology.missing_nodes
            for hash_value in missing.evidence_hashes
        ),
    }
    _require_exact(
        "contract",
        contract_hashes,
        (
            *evidence.contract_evidence,
            *evidence.amendment_evidence,
            *evidence.schedule_evidence,
            *evidence.policy_evidence,
        ),
    )
    assent_hashes = {
        hash_value
        for node in evidence.topology.nodes
        for hash_value in (
            *node.assent_evidence_hashes,
            *node.signature_evidence_hashes,
        )
    }
    _require_exact("assent", assent_hashes, evidence.assent_evidence)
    _require_exact(
        "notice", assessment.notice_evidence_hashes, evidence.notice_evidence
    )
    _require_exact(
        "classification",
        assessment.classification.definition_evidence_hashes,
        evidence.classification_evidence,
    )
    adjudication_hashes = {
        hash_value
        for result in assessment.purpose_results
        for hash_value in result.evidence_hashes
    }
    _require_exact("adjudication", adjudication_hashes, evidence.adjudication_evidence)
    all_hashes = set(_verify_bytes(_all_rights_evidence(evidence)))

    node_by_hash = {content_hash(node): node for node in evidence.topology.nodes}
    answer_by_question = {answer.question: answer for answer in assessment.answers}
    missing_questions = {
        question
        for missing in evidence.topology.missing_nodes
        for question in missing.affected_questions
    }
    for question in missing_questions:
        if answer_by_question[question].disposition is not RightsDisposition.UNKNOWN:
            raise ValueError("missing applicable contract node requires UNKNOWN answer")
    for answer in assessment.answers:
        if answer.adjudicator_identity != assessment.assessor_identity:
            raise ValueError("rights answer adjudicator does not match assessment")
        if answer.scope_hash != profile_hash:
            raise ValueError("rights answer scope does not match profile")
        if not (
            assessment.valid_from
            <= answer.valid_from
            <= answer.valid_until
            <= assessment.valid_until
        ):
            raise ValueError("rights answer validity exceeds assessment")
        if not set(answer.evidence_hashes).issubset(all_hashes):
            raise ValueError("rights answer evidence is not hash-resolved")
        nodes = tuple(
            node_by_hash.get(value) for value in answer.controlling_node_hashes
        )
        if any(node is None for node in nodes):
            raise ValueError("rights answer has nonexistent controlling contract")
        applicable = tuple(node for node in nodes if node is not None)
        if answer.disposition is RightsDisposition.ALLOWED:
            if any(
                node.document_kind.casefold() in _MARKETING_KINDS for node in applicable
            ):
                raise ValueError("marketing evidence cannot produce ALLOWED")
            if any(
                node.applicability_status is not ApplicabilityStatus.APPLICABLE
                for node in applicable
            ):
                raise ValueError("allowed answer requires applicable contract evidence")
            if any(
                node.effective_at > answer.valid_from
                or (
                    node.expires_at is not None and node.expires_at < answer.valid_until
                )
                for node in applicable
            ):
                raise ValueError("allowed answer exceeds controlling contract validity")

    if (
        assessment.classification.provider_party_id
        != profile.provider.provider_legal_id
    ):
        raise ValueError("classification provider does not match profile")
    if (
        assessment.classification.provider_defined_label
        != profile.subscriber.provider_classification_label
        or set(assessment.classification.definition_evidence_hashes)
        != set(profile.subscriber.classification_evidence_hashes)
    ):
        raise ValueError("classification does not match frozen provider definition")
    if profile.subscriber.classification_unresolved != (
        assessment.classification.status is UseClassificationStatus.UNRESOLVED
    ):
        raise ValueError("classification status does not match frozen profile")
    if assessment.policy_hash != profile.adjudication_policy_hash:
        raise ValueError("rights assessment policy does not match profile")
    matching_results = tuple(
        result
        for result in assessment.purpose_results
        if result.purpose is profile.purpose
    )
    if len(matching_results) != 1 or len(assessment.purpose_results) != 1:
        raise ValueError("rights assessment requires the exact profile purpose result")
    actual_result = matching_results[0]
    if (
        assessment.classification.status is UseClassificationStatus.UNRESOLVED
        and actual_result.disposition is RightsDisposition.ALLOWED
    ):
        raise ValueError("unresolved provider classification cannot allow use")
    expected_result = _purpose_disposition(profile, assessment)
    if actual_result.disposition is not expected_result:
        raise ValueError("purpose rights result does not match explicit answers")
    if (
        assessment.entitlement_state is not EntitlementState.ACTIVE
        and actual_result.disposition is RightsDisposition.ALLOWED
    ):
        raise ValueError("inactive entitlement cannot allow use")

    if any(
        item.access_purpose is not profile.purpose
        for item in assessment.authorized_users
    ):
        raise ValueError("authorized users cannot cross consumer purposes")
    user_ids = {item.user_id for item in assessment.authorized_users}
    if user_ids != set(profile.infrastructure.user_ids):
        raise ValueError("authorized users do not match profile")
    user_evidence = {
        hash_value
        for item in assessment.authorized_users
        for hash_value in item.evidence_hashes
    }
    if not user_evidence or not user_evidence.issubset(all_hashes):
        raise ValueError("authorized-user evidence is not hash-resolved")
    if any(
        item.access_purpose is not profile.purpose
        for item in assessment.service_providers
    ):
        raise ValueError("service providers cannot cross consumer purposes")
    service_ids = {
        item.service_provider_id
        for item in assessment.service_providers
        if item.access_purpose is profile.purpose
    }
    if service_ids != set(profile.infrastructure.service_provider_ids):
        raise ValueError("authorized service providers do not match profile")
    service_evidence = {
        hash_value
        for item in assessment.service_providers
        for hash_value in item.evidence_hashes
    }
    if service_evidence and not service_evidence.issubset(all_hashes):
        raise ValueError("service-provider evidence is not hash-resolved")
    answer_by_question = {item.question: item for item in assessment.answers}
    for policy in assessment.content_rights_policies:
        if policy.policy_hash != content_rights_policy_hash(policy):
            raise ValueError("content-rights policy hash mismatch")
        if policy.permitted_purposes != (profile.purpose,):
            raise ValueError("content-rights policy requires exact assessed purpose")
        exact_infrastructure = (
            policy.permitted_user_ids == profile.infrastructure.user_ids
            and policy.permitted_contractor_ids == profile.infrastructure.contractor_ids
            and policy.permitted_service_provider_ids
            == profile.infrastructure.service_provider_ids
            and policy.permitted_location_ids
            == (profile.infrastructure.machine_identity,)
            and policy.permitted_backup_location_ids
            == profile.infrastructure.backup_location_ids
            and policy.machine_identity == profile.infrastructure.machine_identity
            and policy.shared_account == profile.infrastructure.shared_account
            and policy.real_data_ci == profile.infrastructure.real_data_ci
            and policy.cloud_processing == profile.infrastructure.cloud_processing
            and policy.private_store_policy_hash
            == profile.infrastructure.private_store_policy_hash
        )
        if not exact_infrastructure:
            raise ValueError(
                "content-rights policy requires exact authorized infrastructure"
            )
        if not set(policy.controlling_provision_hashes).issubset(all_hashes):
            raise ValueError("content-rights policy evidence is not hash-resolved")
        backup_disposition = answer_by_question[
            RightsQuestion.BACKUP_STORAGE
        ].disposition
        if policy.backup_allowed != (backup_disposition is RightsDisposition.ALLOWED):
            raise ValueError("content policy and backup answer are inconsistent")
        post_term_disposition = answer_by_question[
            RightsQuestion.POST_SUBSCRIPTION_RAW_USE
        ].disposition
        if policy.post_termination_use is not post_term_disposition:
            raise ValueError(
                "content policy and post-termination answer are inconsistent"
            )
        deletion_duties = {
            ContentDispositionDuty.DELETE,
            ContentDispositionDuty.CERTIFY_DELETE,
        }
        if (
            post_term_disposition is RightsDisposition.ALLOWED
            and policy.disposition_duty in deletion_duties
        ) or (
            post_term_disposition is RightsDisposition.DENIED
            and policy.disposition_duty not in deletion_duties
        ):
            raise ValueError("post-termination rights and disposition duty conflict")
        if (
            policy.retention_until is not None
            and policy.retention_until < assessment.valid_until
            and answer_by_question[RightsQuestion.RAW_BYTE_RETENTION].disposition
            is RightsDisposition.ALLOWED
        ):
            raise ValueError("content policy retention horizon is too short")
    return ValidatedRightsAssessment(
        assessment=assessment,
        profile=profile,
        topology=evidence.topology,
        evidence=evidence,
    )


def _purpose_disposition(
    profile: QualificationProfileV1, assessment: RightsAssessmentV1
) -> RightsDisposition:
    required = {
        RightsQuestion.INTERNAL_AUTOMATED_RESEARCH,
        RightsQuestion.NON_DISPLAY_USE,
        RightsQuestion.LOCAL_STORAGE,
        RightsQuestion.BACKUP_STORAGE,
        RightsQuestion.RAW_BYTE_RETENTION,
        RightsQuestion.POST_SUBSCRIPTION_RAW_USE,
        RightsQuestion.NORMALIZED_ROW_RETENTION,
        RightsQuestion.DERIVED_ARTIFACT_RETENTION,
        RightsQuestion.MODEL_PARAMETER_RETENTION,
        RightsQuestion.METRIC_REPORT_RETENTION,
        RightsQuestion.PRIVATE_FIXTURE_USE,
        RightsQuestion.DELETION_AND_CERTIFICATION,
        RightsQuestion.UPSTREAM_PUBLISHER_RESTRICTIONS,
    }
    if profile.subscriber.model_development_requested:
        required.add(RightsQuestion.MODEL_DEVELOPMENT)
    if profile.subscriber.trading_support_requested:
        required.add(RightsQuestion.FUTURE_TRADING_SUPPORT)
    if profile.infrastructure.real_data_ci:
        required.add(RightsQuestion.REAL_DATA_CI)
    if profile.infrastructure.cloud_processing:
        required.add(RightsQuestion.CLOUD_PROCESSING)
    if profile.infrastructure.service_provider_ids:
        required.add(RightsQuestion.THIRD_PARTY_SERVICE_ACCESS)
    values = {
        answer.disposition
        for answer in assessment.answers
        if answer.question in required
    }
    if RightsDisposition.DENIED in values:
        return RightsDisposition.DENIED
    if (
        RightsDisposition.UNKNOWN in values
        or assessment.classification.status is UseClassificationStatus.UNRESOLVED
        or assessment.entitlement_state is EntitlementState.UNKNOWN
    ):
        return RightsDisposition.UNKNOWN
    if assessment.entitlement_state is not EntitlementState.ACTIVE:
        return RightsDisposition.DENIED
    return RightsDisposition.ALLOWED


def _profile_scope_hash(profile: QualificationProfileV1) -> str:
    return content_hash(
        {
            "provider": profile.provider,
            "subscriber": profile.subscriber,
            "infrastructure": profile.infrastructure,
            "data": profile.data,
        }
    )


def assess_acquisition_eligibility(
    profiles: PilotProfileSetV1,
    assessments: tuple[ValidatedRightsAssessment, ...],
) -> AcquisitionEligibilityV1:
    """Partition the two exact purpose profiles by explicit rights result."""
    expected = {
        qualification_profile_hash(profile): profile for profile in profiles.profiles
    }
    supplied = {item.assessment.profile_hash: item for item in assessments}
    if len(supplied) != len(assessments) or set(supplied) != set(expected):
        raise ValueError("eligibility requires one validated assessment per profile")
    revalidated: list[ValidatedRightsAssessment] = []
    for profile_hash, profile in expected.items():
        item = supplied[profile_hash]
        revalidated.append(
            validate_rights_assessment(profile, item.assessment, item.evidence)
        )
    scopes = {_profile_scope_hash(item.profile) for item in revalidated}
    store_policies = {
        item.profile.infrastructure.private_store_policy_hash for item in revalidated
    }
    policies = {item.assessment.policy_hash for item in revalidated}
    if len(scopes) != 1 or len(store_policies) != 1 or len(policies) != 1:
        raise ValueError("purpose profiles do not share acquisition scope and policy")

    eligible: list[str] = []
    denied: list[str] = []
    unresolved: list[str] = []
    reasons: list[str] = []
    for item in revalidated:
        result = next(
            value
            for value in item.assessment.purpose_results
            if value.purpose is item.profile.purpose
        )
        profile_hash = item.assessment.profile_hash
        if result.disposition is RightsDisposition.ALLOWED:
            eligible.append(profile_hash)
        elif result.disposition is RightsDisposition.DENIED:
            denied.append(profile_hash)
        else:
            unresolved.append(profile_hash)
        reasons.append(f"{profile_hash}:{result.disposition.value}")
    return AcquisitionEligibilityV1(
        profile_set_hash=content_hash(profiles),
        assessment_hashes=tuple(content_hash(item.assessment) for item in revalidated),
        eligible_profile_hashes=tuple(eligible),
        denied_profile_hashes=tuple(denied),
        unresolved_profile_hashes=tuple(unresolved),
        product_id=profiles.profiles[0].provider.product_id,
        scope_hash=next(iter(scopes)),
        valid_from=max(item.assessment.valid_from for item in revalidated),
        valid_until=min(item.assessment.valid_until for item in revalidated),
        private_store_policy_hash=next(iter(store_policies)),
        reasons=tuple(reasons),
        policy_identity=next(iter(policies)),
    )


def _verify_approval_evidence(
    approval: AcquisitionApprovalV1, evidence: ApprovalEvidenceContext
) -> None:
    _require_exact(
        "approval", approval.approval_evidence_hashes, evidence.approval_evidence
    )
    _require_exact(
        "authorizer scope",
        approval.authorizer_scope_evidence_hashes,
        evidence.authorizer_scope_evidence,
    )
    _require_exact(
        "approval decision",
        approval.decision_evidence_hashes,
        evidence.decision_evidence,
    )
    _require_exact(
        "approval expiry", approval.expiry_evidence_hashes, evidence.expiry_evidence
    )


def authorize_acquisition(
    eligibility: AcquisitionEligibilityV1,
    approval: AcquisitionApprovalV1,
    evidence: ApprovalEvidenceContext,
) -> AcquisitionAuthorizationV1:
    """Intersect verified legal eligibility with separate external approval."""
    _verify_approval_evidence(approval, evidence)
    if approval.eligibility_hash != content_hash(eligibility):
        raise ValueError("approval eligibility hash mismatch")
    if approval.approved_product_id != eligibility.product_id:
        raise ValueError("approval product mismatch")
    if approval.approved_scope_hash != eligibility.scope_hash:
        raise ValueError("approval scope mismatch")
    if not set(approval.approved_profile_hashes).issubset(
        eligibility.eligible_profile_hashes
    ):
        raise ValueError("approval names a profile that is not an eligible profile")
    if not (
        eligibility.valid_from <= approval.decision_time <= eligibility.valid_until
    ):
        raise ValueError("approval decision is outside rights validity")
    authorized_until = min(approval.expires_at, eligibility.valid_until)
    return AcquisitionAuthorizationV1(
        authorization_id=approval.approval_id,
        eligibility_hash=content_hash(eligibility),
        approval_hash=content_hash(approval),
        authorized_profile_hashes=approval.approved_profile_hashes,
        product_id=eligibility.product_id,
        scope_hash=eligibility.scope_hash,
        authorized_from=approval.decision_time,
        authorized_until=authorized_until,
        private_store_policy_hash=eligibility.private_store_policy_hash,
        status=AuthorizationStatus.AUTHORIZED,
        reasons=("external approval and rights eligibility verified",),
        authorization_identity=approval.authorizer_identity,
    )


def verify_acquisition_authorization(
    bundle: AcquisitionAuthorizationVerificationBundle,
) -> None:
    """Recompute every acquisition-authority layer from retained referents."""
    eligibility = assess_acquisition_eligibility(bundle.profiles, bundle.assessments)
    if eligibility != bundle.eligibility:
        raise ValueError("acquisition eligibility does not reverify")
    authorization = authorize_acquisition(
        bundle.eligibility, bundle.approval, bundle.approval_evidence
    )
    if authorization != bundle.authorization:
        raise ValueError("acquisition authorization does not reverify")


def verify_replay_authorization(
    bundle: ReplayAuthorizationVerificationBundle,
) -> None:
    """Verify a fresh purpose-specific replay decision using current evidence."""
    request = bundle.request
    decision = bundle.decision
    current = validate_rights_assessment(
        bundle.profile,
        bundle.current_assessment.assessment,
        bundle.current_assessment.evidence,
    )
    if current != bundle.current_assessment:
        raise ValueError("current rights assessment does not reverify")
    if request.profile_hash != qualification_profile_hash(bundle.profile):
        raise ValueError("replay profile hash mismatch")
    if request.purpose is not bundle.profile.purpose:
        raise ValueError("replay purpose mismatch")
    if request.requested_user_ids != bundle.profile.infrastructure.user_ids:
        raise ValueError("replay users do not match profile")
    if request.requested_infrastructure != bundle.profile.infrastructure:
        raise ValueError("replay infrastructure does not match profile")
    if decision.request_hash != content_hash(request):
        raise ValueError("replay decision request hash mismatch")
    if decision.new_assessment_hash != content_hash(current.assessment):
        raise ValueError("replay decision assessment hash mismatch")
    if not (
        current.assessment.valid_from
        <= request.current_time
        <= current.assessment.valid_until
    ):
        raise ValueError("replay time is outside rights validity")
    if current.assessment.assessed_at != request.current_time:
        raise ValueError("replay requires a fresh current assessment")
    if decision.decision_time != request.current_time:
        raise ValueError("replay decision is not current")
    if current.assessment.entitlement_state is not EntitlementState.ACTIVE:
        raise ValueError("replay entitlement is not active")
    result = next(
        value
        for value in current.assessment.purpose_results
        if value.purpose is bundle.profile.purpose
    )
    if result.disposition is not RightsDisposition.ALLOWED:
        raise ValueError("current rights do not allow replay purpose")
    if decision.status is not AuthorizationStatus.AUTHORIZED:
        raise ValueError("replay decision is not authorized")
    if decision.policy_hash != current.assessment.policy_hash:
        raise ValueError("replay decision policy mismatch")
    _require_exact(
        "current entitlement",
        request.entitlement_evidence_hashes,
        bundle.evidence.entitlement_evidence,
    )
    if request.termination_evidence_hashes or bundle.evidence.termination_evidence:
        _require_exact(
            "termination",
            request.termination_evidence_hashes,
            bundle.evidence.termination_evidence,
        )
        raise ValueError("current termination evidence blocks replay")
    _require_exact(
        "current notice",
        request.notice_evidence_hashes,
        bundle.evidence.notice_evidence,
    )
    if set(request.notice_evidence_hashes) != set(
        current.assessment.notice_evidence_hashes
    ):
        raise ValueError("replay notice set differs from current assessment")
    current_contract_hashes = {
        item.content_hash for item in current.evidence.contract_evidence
    }
    _require_exact(
        "current contract",
        current_contract_hashes,
        bundle.evidence.current_contract_evidence,
    )
    decision_evidence = (
        *bundle.evidence.user_infrastructure_evidence,
        *bundle.evidence.request_evidence,
        *bundle.evidence.decision_evidence,
    )
    _require_exact("replay decision", decision.evidence_hashes, decision_evidence)
