"""Task 3 acquisition and replay authorization tests."""

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import uuid7

import pytest
from test_rights_assessment import (
    LATER,
    NOW,
    make_assessment,
    make_evidence,
    make_profile,
    make_topology,
)

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.qualification import (
    ConsumerPurpose,
    InfrastructureScopeV1,
    PilotProfileSetV1,
    qualification_profile_hash,
)
from drift.domain.rights import (
    AcquisitionApprovalV1,
    AcquisitionEligibilityV1,
    ApprovalEvidenceContext,
    AuthorizationStatus,
    ReplayAuthorizationDecisionV1,
    ReplayAuthorizationEvidenceContext,
    ReplayAuthorizationRequestV1,
    RightsDisposition,
    RightsQuestion,
    ValidatedRightsAssessment,
)
from drift.qualification.rights import (
    AcquisitionAuthorizationVerificationBundle,
    ReplayAuthorizationVerificationBundle,
    assess_acquisition_eligibility,
    authorize_acquisition,
    validate_rights_assessment,
    verify_acquisition_authorization,
    verify_replay_authorization,
)
from drift.serialization.canonical import content_hash


def _verified(data: bytes) -> VerifiedArtifactBytes:
    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=sha256(data).hexdigest(),
    )


APPROVAL = _verified(b"external acquisition approval")
AUTHOR_SCOPE = _verified(b"authorizer scope")
APPROVAL_DECISION = _verified(b"approval decision time")
APPROVAL_EXPIRY = _verified(b"approval expiry")
ENTITLEMENT = _verified(b"current entitlement")
CURRENT_NOTICE = _verified(b"current notice")
REQUEST_EVIDENCE = _verified(b"replay request")
DECISION_EVIDENCE = _verified(b"replay decision")
TERMINATION = _verified(b"termination notice")
USER_INFRA = _verified(b"current user and infrastructure")
UNREFERENCED = _verified(b"unreferenced approval material")


def _profiles_and_assessments() -> tuple[
    PilotProfileSetV1, tuple[ValidatedRightsAssessment, ...]
]:
    decision = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    audit = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profiles = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(decision, audit)
    )
    topology = make_topology()
    assessments = tuple(
        validate_rights_assessment(
            profile,
            make_assessment(profile, topology),
            make_evidence(topology),
        )
        for profile in profiles.profiles
    )
    return profiles, assessments


def _approval(eligibility: AcquisitionEligibilityV1) -> AcquisitionApprovalV1:
    return AcquisitionApprovalV1(
        approval_id=uuid7(),
        eligibility_hash=content_hash(eligibility),
        approved_profile_hashes=eligibility.eligible_profile_hashes,
        approved_product_id=eligibility.product_id,
        approved_scope_hash=eligibility.scope_hash,
        approval_evidence_hashes=(APPROVAL.content_hash,),
        authorizer_scope_evidence_hashes=(AUTHOR_SCOPE.content_hash,),
        decision_evidence_hashes=(APPROVAL_DECISION.content_hash,),
        expiry_evidence_hashes=(APPROVAL_EXPIRY.content_hash,),
        authorizer_identity="authorizer-1",
        decision_time=NOW,
        expires_at=LATER,
        purchase_authority=False,
        terms_acceptance_authority=False,
    )


def _approval_context() -> ApprovalEvidenceContext:
    return ApprovalEvidenceContext(
        approval_evidence=(APPROVAL,),
        authorizer_scope_evidence=(AUTHOR_SCOPE,),
        decision_evidence=(APPROVAL_DECISION,),
        expiry_evidence=(APPROVAL_EXPIRY,),
    )


def test_external_approval_is_required_for_acquisition_authority() -> None:
    profiles, assessments = _profiles_and_assessments()
    eligibility = assess_acquisition_eligibility(profiles, assessments)
    approval = _approval(eligibility)

    authorization = authorize_acquisition(eligibility, approval, _approval_context())
    bundle = AcquisitionAuthorizationVerificationBundle(
        profiles=profiles,
        assessments=assessments,
        eligibility=eligibility,
        approval=approval,
        approval_evidence=_approval_context(),
        authorization=authorization,
    )

    assert authorization.status is AuthorizationStatus.AUTHORIZED
    verify_acquisition_authorization(bundle)


def test_acquisition_rejects_wrong_purpose_and_approval_evidence() -> None:
    profiles, assessments = _profiles_and_assessments()
    denied_profile = make_assessment(
        assessments[0].profile,
        assessments[0].topology,
        overrides={
            next(iter(RightsQuestion)): RightsDisposition.DENIED,
        },
    )
    denied = validate_rights_assessment(
        assessments[0].profile,
        denied_profile,
        assessments[0].evidence,
    )
    eligibility = assess_acquisition_eligibility(profiles, (denied, assessments[1]))
    approval = _approval(eligibility).model_copy(
        update={
            "approved_profile_hashes": (
                qualification_profile_hash(assessments[0].profile),
            )
        }
    )
    with pytest.raises(ValueError, match="eligible profile"):
        authorize_acquisition(eligibility, approval, _approval_context())

    valid = _approval(eligibility)
    invalid_context = ApprovalEvidenceContext(
        approval_evidence=(
            VerifiedArtifactBytes(
                data=APPROVAL.data,
                byte_size=APPROVAL.byte_size,
                content_hash="f" * 64,
            ),
        ),
        authorizer_scope_evidence=(AUTHOR_SCOPE,),
        decision_evidence=(APPROVAL_DECISION,),
        expiry_evidence=(APPROVAL_EXPIRY,),
    )
    with pytest.raises(ValueError, match="hash-verified"):
        authorize_acquisition(eligibility, valid, invalid_context)

    extra_context = ApprovalEvidenceContext(
        approval_evidence=(APPROVAL, UNREFERENCED),
        authorizer_scope_evidence=(AUTHOR_SCOPE,),
        decision_evidence=(APPROVAL_DECISION,),
        expiry_evidence=(APPROVAL_EXPIRY,),
    )
    with pytest.raises(ValueError, match="exact"):
        authorize_acquisition(eligibility, valid, extra_context)


def _current_replay_bundle(
    *, current_time: datetime = NOW + timedelta(days=1)
) -> ReplayAuthorizationVerificationBundle:
    profile = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    topology = make_topology()
    current_assessment = validate_rights_assessment(
        profile,
        make_assessment(
            profile,
            topology,
            assessed_at=current_time,
            valid_until=LATER,
        ),
        make_evidence(topology),
    )
    request = ReplayAuthorizationRequestV1(
        request_id=uuid7(),
        profile_hash=qualification_profile_hash(profile),
        snapshot_hash="a" * 64,
        environment_closure_hash="b" * 64,
        requested_user_ids=profile.infrastructure.user_ids,
        requested_infrastructure=profile.infrastructure,
        current_time=current_time,
        entitlement_evidence_hashes=(ENTITLEMENT.content_hash,),
        termination_evidence_hashes=(),
        notice_evidence_hashes=current_assessment.assessment.notice_evidence_hashes,
        purpose=profile.purpose,
    )
    decision = ReplayAuthorizationDecisionV1(
        request_hash=content_hash(request),
        new_assessment_hash=content_hash(current_assessment.assessment),
        status=AuthorizationStatus.AUTHORIZED,
        evidence_hashes=(
            REQUEST_EVIDENCE.content_hash,
            DECISION_EVIDENCE.content_hash,
            USER_INFRA.content_hash,
        ),
        reasons=("current synthetic authorization",),
        policy_hash=profile.adjudication_policy_hash,
        decision_id=uuid7(),
        decision_time=current_time,
    )
    evidence = ReplayAuthorizationEvidenceContext(
        current_contract_evidence=current_assessment.evidence.contract_evidence,
        entitlement_evidence=(ENTITLEMENT,),
        termination_evidence=(),
        notice_evidence=current_assessment.evidence.notice_evidence,
        user_infrastructure_evidence=(USER_INFRA,),
        request_evidence=(REQUEST_EVIDENCE,),
        decision_evidence=(DECISION_EVIDENCE,),
    )
    return ReplayAuthorizationVerificationBundle(
        request=request,
        decision=decision,
        current_assessment=current_assessment,
        profile=profile,
        evidence=evidence,
    )


def test_replay_requires_a_new_current_purpose_specific_decision() -> None:
    bundle = _current_replay_bundle()
    verify_replay_authorization(bundle)

    old_assessment = validate_rights_assessment(
        bundle.profile,
        make_assessment(bundle.profile, bundle.current_assessment.topology),
        bundle.current_assessment.evidence,
    )
    old = ReplayAuthorizationVerificationBundle(
        request=bundle.request,
        decision=bundle.decision.model_copy(
            update={"new_assessment_hash": content_hash(old_assessment.assessment)}
        ),
        current_assessment=old_assessment,
        profile=bundle.profile,
        evidence=bundle.evidence,
    )
    with pytest.raises(ValueError, match="fresh current assessment"):
        verify_replay_authorization(old)


@pytest.mark.parametrize("mutation", ["purpose", "users", "infrastructure"])
def test_replay_rejects_changed_purpose_users_or_infrastructure(mutation: str) -> None:
    bundle = _current_replay_bundle()
    update: dict[str, object] = {}
    if mutation == "purpose":
        update["purpose"] = ConsumerPurpose.RETROSPECTIVE_AUDIT
    elif mutation == "users":
        update["requested_user_ids"] = ("other-user",)
        with pytest.raises(ValueError, match="users"):
            bundle.request.model_copy(update=update)
        return
    else:
        update["requested_infrastructure"] = InfrastructureScopeV1(
            **{
                **bundle.profile.infrastructure.model_dump(mode="python"),
                "machine_identity": "other-machine",
            }
        )
    request = bundle.request.model_copy(update=update)
    mutated = ReplayAuthorizationVerificationBundle(
        request=request,
        decision=bundle.decision.model_copy(
            update={"request_hash": content_hash(request)}
        ),
        current_assessment=bundle.current_assessment,
        profile=bundle.profile,
        evidence=bundle.evidence,
    )
    with pytest.raises(ValueError, match="purpose|users|infrastructure"):
        verify_replay_authorization(mutated)


def test_replay_rejects_expired_rights_or_new_termination_notice() -> None:
    bundle = _current_replay_bundle()
    expired_request = bundle.request.model_copy(
        update={"current_time": LATER + timedelta(days=1)}
    )
    expired = ReplayAuthorizationVerificationBundle(
        request=expired_request,
        decision=bundle.decision.model_copy(
            update={
                "request_hash": content_hash(expired_request),
                "decision_time": expired_request.current_time,
            }
        ),
        current_assessment=bundle.current_assessment,
        profile=bundle.profile,
        evidence=bundle.evidence,
    )
    with pytest.raises(ValueError, match="validity"):
        verify_replay_authorization(expired)

    bundle = _current_replay_bundle()
    request = bundle.request.model_copy(
        update={"termination_evidence_hashes": (TERMINATION.content_hash,)}
    )
    terminated = ReplayAuthorizationVerificationBundle(
        request=request,
        decision=bundle.decision.model_copy(
            update={"request_hash": content_hash(request)}
        ),
        current_assessment=bundle.current_assessment,
        profile=bundle.profile,
        evidence=ReplayAuthorizationEvidenceContext(
            current_contract_evidence=bundle.evidence.current_contract_evidence,
            entitlement_evidence=bundle.evidence.entitlement_evidence,
            termination_evidence=(TERMINATION,),
            notice_evidence=bundle.evidence.notice_evidence,
            user_infrastructure_evidence=(USER_INFRA,),
            request_evidence=bundle.evidence.request_evidence,
            decision_evidence=bundle.evidence.decision_evidence,
        ),
    )
    with pytest.raises(ValueError, match="termination"):
        verify_replay_authorization(terminated)


def test_replay_authorized_status_is_never_inferred_from_hashes() -> None:
    bundle = _current_replay_bundle()
    denied = ReplayAuthorizationVerificationBundle(
        request=bundle.request,
        decision=bundle.decision.model_copy(
            update={"status": AuthorizationStatus.DENIED}
        ),
        current_assessment=bundle.current_assessment,
        profile=bundle.profile,
        evidence=bundle.evidence,
    )
    with pytest.raises(ValueError, match="not authorized"):
        verify_replay_authorization(denied)
