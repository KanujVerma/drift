"""Task 3 rights topology and purpose-scoped assessment tests."""

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid7

import pytest

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.qualification import (
    ConsumerPurpose,
    ContentDispositionDuty,
    InfrastructureScopeV1,
    PilotProfileSetV1,
    ProviderProductScopeV1,
    QualificationDataScopeV1,
    QualificationDimension,
    QualificationProfileV1,
    SubscriberUseScopeV1,
    qualification_profile_hash,
)
from drift.domain.rights import (
    ApplicabilityStatus,
    AuthorizedUserV1,
    ConfidentialityClass,
    ContentRightsPolicyV1,
    ContractDocumentNodeV1,
    ContractPrecedenceEdgeV1,
    ContractTopologyV1,
    EntitlementState,
    LegalPartyV1,
    MissingContractNodeV1,
    PurposeRightsResultV1,
    RightsAnswerV1,
    RightsAssessmentV1,
    RightsDisposition,
    RightsEvidenceContext,
    RightsQuestion,
    ServiceProviderScopeV1,
    UseClassificationStatus,
    UseClassificationV1,
)
from drift.qualification.rights import (
    assess_acquisition_eligibility,
    bind_content_rights,
    content_rights_policy_hash,
    validate_contract_topology,
    validate_rights_assessment,
)
from drift.serialization.canonical import content_hash

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _verified(data: bytes) -> VerifiedArtifactBytes:
    return VerifiedArtifactBytes(
        data=data, byte_size=len(data), content_hash=_digest(data)
    )


CONTRACT = _verified(b"executed synthetic agreement")
ASSENT = _verified(b"synthetic assent")
CLASSIFICATION = _verified(b"provider classification definition")
ADJUDICATION = _verified(b"human legal adjudication")
NOTICE = _verified(b"current synthetic notice")
PRECEDENCE = _verified(b"synthetic precedence clause")


def _reference(evidence: VerifiedArtifactBytes, *, location: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.OTHER,
        content_hash=evidence.content_hash,
        location=location,
    )


def make_profile(purpose: ConsumerPurpose) -> QualificationProfileV1:
    return QualificationProfileV1(
        profile_id=uuid7(),
        profile_version="1",
        provider=ProviderProductScopeV1(
            provider_legal_name="Synthetic Data LLC",
            provider_legal_id="provider-1",
            product_id="daily-equities",
            dataset_ids=("daily",),
            publisher_ids=("publisher-1",),
            declared_fields=("close",),
            methodology_reference_hashes=("1" * 64,),
            schema_reference_hashes=("2" * 64,),
        ),
        subscriber=SubscriberUseScopeV1(
            subscriber_legal_entity="Synthetic Research LLC",
            authorized_user_id="user-1",
            model_development_requested=True,
            trading_support_requested=False,
            provider_classification_label="internal non-display research",
            classification_unresolved=False,
            classification_evidence_hashes=(CLASSIFICATION.content_hash,),
        ),
        infrastructure=InfrastructureScopeV1(
            machine_identity="mac-arm64-1",
            user_ids=("user-1",),
            contractor_ids=(),
            shared_account=False,
            real_data_ci=False,
            cloud_processing=False,
            service_provider_ids=(),
            private_store_policy_hash="3" * 64,
            backup_location_ids=(),
        ),
        data=QualificationDataScopeV1(
            security_ids=("security-1",),
            universe_ids=("universe-1",),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            requested_fields=("close",),
            revision_cutoff=NOW,
            event_window_ids=("G01",),
            sessions_before_event=2,
            sessions_after_event=2,
        ),
        purpose=purpose,
        critical_dimensions=(QualificationDimension.LICENSING_RETENTION,),
        required_golden_case_ids=("G01",),
        golden_case_instance_manifest_hash="4" * 64,
        adjudication_policy_hash="5" * 64,
    )


def make_topology(
    *,
    document_kind: str = "executed_agreement",
    applicability: ApplicabilityStatus = ApplicabilityStatus.APPLICABLE,
    confidentiality: ConfidentialityClass = ConfidentialityClass.CONFIDENTIAL,
    location: str = "evidence:restricted/agreement",
    missing_nodes: tuple[MissingContractNodeV1, ...] = (),
) -> ContractTopologyV1:
    party = LegalPartyV1(
        party_id="provider-1",
        exact_legal_name="Synthetic Data LLC",
        role="provider",
        jurisdiction="Delaware",
        jurisdiction_unknown=False,
        evidence_references=(
            _reference(CONTRACT, location="evidence:restricted/agreement"),
        ),
    )
    node = ContractDocumentNodeV1(
        node_id="agreement",
        document_kind=document_kind,
        title="Synthetic Agreement",
        document_version="2026-01",
        effective_at=NOW - timedelta(days=30),
        expires_at=LATER,
        artifact_reference=_reference(CONTRACT, location=location),
        product_ids=("daily-equities",),
        publisher_ids=("publisher-1",),
        party_ids=("provider-1",),
        assent_evidence_hashes=(ASSENT.content_hash,),
        signature_evidence_hashes=(),
        confidentiality_class=confidentiality,
        applicability_status=applicability,
    )
    return ContractTopologyV1(
        topology_version="1",
        parties=(party,),
        nodes=(node,),
        edges=(),
        root_agreement_ids=("agreement",),
        assessed_product_id="daily-equities",
        assessed_publisher_ids=("publisher-1",),
        missing_nodes=missing_nodes,
    )


def make_evidence(topology: ContractTopologyV1) -> RightsEvidenceContext:
    return RightsEvidenceContext(
        topology=topology,
        contract_evidence=(CONTRACT,),
        assent_evidence=(ASSENT,),
        amendment_evidence=(),
        schedule_evidence=(),
        policy_evidence=(),
        notice_evidence=(NOTICE,),
        classification_evidence=(CLASSIFICATION,),
        adjudication_evidence=(ADJUDICATION,),
    )


def make_policy(profile: QualificationProfileV1) -> ContentRightsPolicyV1:
    placeholder = ContentRightsPolicyV1(
        policy_id="raw-policy",
        provider_contractual_class="licensed source rows",
        object_scope="provider-native daily rows",
        controlling_provision_hashes=(CONTRACT.content_hash,),
        permitted_purposes=(profile.purpose,),
        permitted_user_ids=profile.infrastructure.user_ids,
        permitted_location_ids=(profile.infrastructure.machine_identity,),
        retention_until=LATER,
        post_termination_use=RightsDisposition.ALLOWED,
        disposition_duty=ContentDispositionDuty.RETAIN,
        backup_allowed=True,
        backup_rule="encrypted local backup permitted",
        policy_hash="0" * 64,
    )
    return placeholder.model_copy(
        update={"policy_hash": content_rights_policy_hash(placeholder)}
    )


def make_assessment(
    profile: QualificationProfileV1,
    topology: ContractTopologyV1,
    *,
    overrides: dict[RightsQuestion, RightsDisposition] | None = None,
    classification_status: UseClassificationStatus = UseClassificationStatus.RESOLVED,
    entitlement_state: EntitlementState = EntitlementState.ACTIVE,
    assessed_at: datetime = NOW,
    valid_until: datetime = LATER,
) -> RightsAssessmentV1:
    node_hash = content_hash(topology.nodes[0])
    overrides = overrides or {}
    answers = tuple(
        RightsAnswerV1(
            question=question,
            disposition=overrides.get(question, RightsDisposition.ALLOWED),
            controlling_node_hashes=(node_hash,),
            evidence_hashes=(CONTRACT.content_hash, ASSENT.content_hash),
            scope_hash=qualification_profile_hash(profile),
            valid_from=assessed_at,
            valid_until=valid_until,
            limitations=()
            if overrides.get(question, RightsDisposition.ALLOWED)
            is RightsDisposition.ALLOWED
            else ("synthetic limitation",),
            adjudicator_identity="reviewer-1",
        )
        for question in RightsQuestion
    )
    result = RightsDisposition.ALLOWED
    if RightsDisposition.DENIED in overrides.values():
        result = RightsDisposition.DENIED
    elif RightsDisposition.UNKNOWN in overrides.values():
        result = RightsDisposition.UNKNOWN
    classification = UseClassificationV1(
        classification_id="class-1",
        provider_party_id="provider-1",
        provider_defined_label="internal non-display research"
        if classification_status is UseClassificationStatus.RESOLVED
        else None,
        status=classification_status,
        definition_evidence_hashes=(CLASSIFICATION.content_hash,)
        if classification_status is UseClassificationStatus.RESOLVED
        else (),
        assessed_use="automated internal research",
    )
    return RightsAssessmentV1(
        assessment_id=uuid7(),
        profile_hash=qualification_profile_hash(profile),
        topology_hash=content_hash(topology),
        assessed_at=assessed_at,
        valid_from=assessed_at,
        valid_until=valid_until,
        entitlement_state=entitlement_state,
        classification=classification,
        authorized_users=(
            AuthorizedUserV1(
                user_id=profile.infrastructure.user_ids[0],
                access_purpose=profile.purpose,
                evidence_hashes=(ASSENT.content_hash,),
            ),
        ),
        service_providers=(),
        answers=answers,
        notice_evidence_hashes=(NOTICE.content_hash,),
        content_rights_policies=(make_policy(profile),),
        reassessment_triggers=("contract change", "termination notice"),
        policy_hash=profile.adjudication_policy_hash,
        assessor_identity="reviewer-1",
        purpose_results=(
            PurposeRightsResultV1(
                purpose=profile.purpose,
                disposition=result,
                evidence_hashes=(ADJUDICATION.content_hash,),
                limitations=()
                if result is RightsDisposition.ALLOWED
                else ("rights not fully allowed",),
            ),
        ),
    )


def test_rights_question_is_exactly_closed() -> None:
    assert {item.value for item in RightsQuestion} == {
        "internal_automated_research",
        "display_use",
        "non_display_use",
        "model_development",
        "future_trading_support",
        "local_storage",
        "private_git_storage",
        "real_data_ci",
        "cloud_processing",
        "third_party_service_access",
        "backup_storage",
        "raw_byte_retention",
        "post_subscription_raw_use",
        "normalized_row_retention",
        "derived_artifact_retention",
        "model_parameter_retention",
        "metric_report_retention",
        "private_fixture_use",
        "public_fixture_use",
        "publication",
        "redistribution",
        "deletion_and_certification",
        "upstream_publisher_restrictions",
    }


def test_complete_lawful_synthetic_topology_validates() -> None:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()

    assert validate_contract_topology(topology) == ()
    validated = validate_rights_assessment(
        profile, make_assessment(profile, topology), make_evidence(topology)
    )
    assert validated.topology == topology


def test_topology_reports_duplicate_edges_and_cycles() -> None:
    topology = make_topology()
    second = topology.nodes[0].model_copy(
        update={"node_id": "schedule", "document_kind": "schedule"}
    )
    edge = ContractPrecedenceEdgeV1(
        controlling_node_id="agreement",
        subordinate_node_id="schedule",
        relationship="incorporates",
        precedence_evidence_hashes=(PRECEDENCE.content_hash,),
    )
    invalid = topology.model_copy(
        update={
            "nodes": (*topology.nodes, second),
            "edges": (
                edge,
                edge,
                edge.model_copy(
                    update={
                        "controlling_node_id": "schedule",
                        "subordinate_node_id": "agreement",
                    }
                ),
            ),
        }
    )

    codes = {item.code for item in validate_contract_topology(invalid)}
    assert "duplicate_contract_precedence_edge" in codes
    assert "contract_precedence_cycle" in codes


@pytest.mark.parametrize(
    ("topology", "expected"),
    [
        (
            make_topology(
                missing_nodes=(
                    MissingContractNodeV1(
                        node_id="publisher-schedule",
                        reason="not supplied",
                        affected_questions=(RightsQuestion.RAW_BYTE_RETENTION,),
                        evidence_hashes=(),
                    ),
                )
            ),
            "missing_contract_node",
        ),
        (
            make_topology(applicability=ApplicabilityStatus.UNKNOWN),
            "unknown_contract_applicability",
        ),
        (
            make_topology().model_copy(update={"assessed_product_id": "other"}),
            "unmatched_contract_product",
        ),
        (
            make_topology().model_copy(update={"assessed_publisher_ids": ("other",)}),
            "unmatched_contract_publisher",
        ),
        (
            make_topology().model_copy(
                update={
                    "nodes": (
                        make_topology()
                        .nodes[0]
                        .model_copy(update={"assent_evidence_hashes": ()}),
                    )
                }
            ),
            "absent_contract_assent",
        ),
        (
            make_topology(location="git:contracts/agreement.pdf"),
            "confidential_evidence_public_reference",
        ),
    ],
)
def test_topology_fails_closed_for_incomplete_or_mismatched_authority(
    topology: ContractTopologyV1, expected: str
) -> None:
    assert expected in {item.code for item in validate_contract_topology(topology)}


def test_missing_applicable_node_forces_affected_answer_unknown() -> None:
    missing = MissingContractNodeV1(
        node_id="publisher-schedule",
        reason="not supplied",
        affected_questions=(RightsQuestion.RAW_BYTE_RETENTION,),
        evidence_hashes=(),
    )
    topology = make_topology(missing_nodes=(missing,))
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)

    with pytest.raises(ValueError, match="missing applicable contract node"):
        validate_rights_assessment(
            profile,
            make_assessment(profile, topology),
            make_evidence(topology),
        )

    assessment = make_assessment(
        profile,
        topology,
        overrides={RightsQuestion.RAW_BYTE_RETENTION: RightsDisposition.UNKNOWN},
    )
    validated = validate_rights_assessment(profile, assessment, make_evidence(topology))
    assert validated.assessment.answers[11].disposition is RightsDisposition.UNKNOWN


def test_unresolved_classification_and_marketing_copy_cannot_allow_use() -> None:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()
    unresolved = make_assessment(
        profile,
        topology,
        classification_status=UseClassificationStatus.UNRESOLVED,
    )
    with pytest.raises(ValueError, match="classification"):
        validate_rights_assessment(profile, unresolved, make_evidence(topology))

    marketing = make_topology(document_kind="marketing")
    with pytest.raises(ValueError, match="marketing"):
        validate_rights_assessment(
            profile, make_assessment(profile, marketing), make_evidence(marketing)
        )


def test_assessment_rejects_missing_user_and_unauthorized_service_provider() -> None:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()
    assessment = make_assessment(profile, topology)

    with pytest.raises(ValueError, match="authorized users"):
        validate_rights_assessment(
            profile,
            assessment.model_copy(update={"authorized_users": ()}),
            make_evidence(topology),
        )
    with pytest.raises(ValueError, match="service providers"):
        validate_rights_assessment(
            profile,
            assessment.model_copy(
                update={
                    "service_providers": (
                        ServiceProviderScopeV1(
                            service_provider_id="unrequested-service",
                            access_purpose=profile.purpose,
                            evidence_hashes=(ASSENT.content_hash,),
                        ),
                    )
                }
            ),
            make_evidence(topology),
        )


def test_nonexistent_or_mismatched_contract_evidence_hash_is_rejected() -> None:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()
    context = make_evidence(topology)
    forged = VerifiedArtifactBytes(
        data=CONTRACT.data,
        byte_size=CONTRACT.byte_size,
        content_hash="f" * 64,
    )

    with pytest.raises(ValueError, match="hash-verified"):
        validate_rights_assessment(
            profile,
            make_assessment(profile, topology),
            RightsEvidenceContext(
                topology=topology,
                contract_evidence=(forged,),
                assent_evidence=context.assent_evidence,
                amendment_evidence=(),
                schedule_evidence=(),
                policy_evidence=(),
                notice_evidence=context.notice_evidence,
                classification_evidence=context.classification_evidence,
                adjudication_evidence=context.adjudication_evidence,
            ),
        )


def test_assessment_then_per_object_binding_is_acyclic() -> None:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()
    validated = validate_rights_assessment(
        profile, make_assessment(profile, topology), make_evidence(topology)
    )
    policy = validated.assessment.content_rights_policies[0]

    binding = bind_content_rights(
        content_hash=_digest(b"later acquired row"),
        policy=policy,
        assessment=validated,
    )

    assert "content_hash" not in ContentRightsPolicyV1.model_fields
    assert "assessment_hash" not in ContentRightsPolicyV1.model_fields
    assert binding.content_hash == _digest(b"later acquired row")
    assert binding.policy_hash == policy.policy_hash
    assert binding.frozen_assessment_hash == content_hash(validated.assessment)
    assert binding.provider_contractual_class == policy.provider_contractual_class
    assert binding.backup_rule == policy.backup_rule


@pytest.mark.parametrize(
    "question",
    [
        RightsQuestion.RAW_BYTE_RETENTION,
        RightsQuestion.BACKUP_STORAGE,
        RightsQuestion.POST_SUBSCRIPTION_RAW_USE,
    ],
)
def test_eligibility_preserves_denied_rights_per_purpose(
    question: RightsQuestion,
) -> None:
    decision = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    audit = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profiles = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(decision, audit)
    )
    topology = make_topology()
    decision_assessment = validate_rights_assessment(
        decision,
        make_assessment(
            decision, topology, overrides={question: RightsDisposition.DENIED}
        ),
        make_evidence(topology),
    )
    audit_assessment = validate_rights_assessment(
        audit, make_assessment(audit, topology), make_evidence(topology)
    )

    eligibility = assess_acquisition_eligibility(
        profiles, (decision_assessment, audit_assessment)
    )

    assert qualification_profile_hash(decision) in eligibility.denied_profile_hashes
    assert qualification_profile_hash(audit) in eligibility.eligible_profile_hashes
    assert not eligibility.unresolved_profile_hashes


def test_dataset_kind_is_not_a_legal_classification_field() -> None:
    assert "dataset_kind" not in ContentRightsPolicyV1.model_fields
