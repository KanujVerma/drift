from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid7

import pytest
from pydantic import ValidationError
from test_replay_authorization import _approval, _approval_context
from test_rights_assessment import (
    make_assessment,
    make_evidence,
    make_topology,
)
from test_rights_assessment import (
    make_profile as make_rights_profile,
)

import drift.domain.qualification as qualification_contracts
from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    DimensionQualificationResultV1,
    ExecutionReachability,
    InfrastructureScopeV1,
    M1ePilotStateV1,
    M1eTransitionV1,
    PilotProfileSetV1,
    PilotStage,
    ProviderProductScopeV1,
    PurposeStageStateV1,
    QualificationDataScopeV1,
    QualificationDimension,
    QualificationProfileV1,
    QualificationStatus,
    QualificationTargetV1,
    SubscriberUseScopeV1,
    build_negative_report,
    qualification_profile_hash,
)
from drift.qualification.lifecycle import (
    transition_acquisition_authorized,
    transition_pilot,
    transition_rights_assessed,
)
from drift.qualification.rights import (
    AcquisitionAuthorizationVerificationBundle,
    assess_acquisition_eligibility,
    authorize_acquisition,
    validate_rights_assessment,
)
from drift.serialization.canonical import content_hash

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
REPORT_ID = uuid7()
LATER_NONTERMINAL_STAGES = (
    PilotStage.ACQUIRED,
    PilotStage.SNAPSHOT_FROZEN,
    PilotStage.QUALIFIED,
    PilotStage.REPLAY_AUTHORIZED,
    PilotStage.REPLAYED,
)


def test_task3_advances_rights_and_acquisition_only_from_typed_verification() -> None:
    decision = make_rights_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    audit = make_rights_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(decision, audit)
    )
    state = M1ePilotStateV1(
        profile_set_hash=content_hash(profile_set),
        purpose_states=cast(
            tuple[PurposeStageStateV1, PurposeStageStateV1],
            tuple(
                PurposeStageStateV1(
                    purpose=profile.purpose,
                    profile_hash=qualification_profile_hash(profile),
                    stage=None,
                    reached_stage_artifact_hashes=(),
                    terminal_blocker=None,
                )
                for profile in profile_set.profiles
            ),
        ),
        shared_artifact_hashes=(),
    )
    for profile in profile_set.profiles:
        state = transition_pilot(state, freeze_transition(profile_set, profile))

    topology = make_topology()
    assessments = tuple(
        validate_rights_assessment(
            profile,
            make_assessment(profile, topology),
            make_evidence(topology),
        )
        for profile in profile_set.profiles
    )
    for assessment in assessments:
        state = transition_rights_assessed(state, assessment)
    assert all(
        item.stage is PilotStage.RIGHTS_ASSESSED for item in state.purpose_states
    )

    eligibility = assess_acquisition_eligibility(profile_set, assessments)
    approval = _approval(eligibility)
    authorization = authorize_acquisition(eligibility, approval, _approval_context())
    state = transition_acquisition_authorized(
        state,
        AcquisitionAuthorizationVerificationBundle(
            profiles=profile_set,
            assessments=assessments,
            eligibility=eligibility,
            approval=approval,
            approval_evidence=_approval_context(),
            authorization=authorization,
        ),
    )
    assert all(
        item.stage is PilotStage.ACQUISITION_AUTHORIZED for item in state.purpose_states
    )


def test_task3_rights_transition_rejects_profile_substitution() -> None:
    profile_set, decision, _, state = pilot()
    state = transition_pilot(state, freeze_transition(profile_set, decision))
    substitute = make_rights_profile(decision.purpose)
    topology = make_topology()
    validated = validate_rights_assessment(
        substitute,
        make_assessment(substitute, topology),
        make_evidence(topology),
    )

    with pytest.raises(ValueError, match="profile"):
        transition_rights_assessed(state, validated)


def test_acquisition_transition_rejects_assessment_substitution() -> None:
    decision = make_rights_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    audit = make_rights_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(decision, audit)
    )
    state = M1ePilotStateV1(
        profile_set_hash=content_hash(profile_set),
        purpose_states=cast(
            tuple[PurposeStageStateV1, PurposeStageStateV1],
            tuple(
                PurposeStageStateV1(
                    purpose=profile.purpose,
                    profile_hash=qualification_profile_hash(profile),
                    stage=None,
                    reached_stage_artifact_hashes=(),
                    terminal_blocker=None,
                )
                for profile in profile_set.profiles
            ),
        ),
        shared_artifact_hashes=(),
    )
    for profile in profile_set.profiles:
        state = transition_pilot(state, freeze_transition(profile_set, profile))
    topology = make_topology()
    assessed = tuple(
        validate_rights_assessment(
            profile,
            make_assessment(profile, topology),
            make_evidence(topology),
        )
        for profile in profile_set.profiles
    )
    for assessment in assessed:
        state = transition_rights_assessed(state, assessment)

    substituted = (
        validate_rights_assessment(
            decision,
            make_assessment(decision, topology),
            make_evidence(topology),
        ),
        assessed[1],
    )
    eligibility = assess_acquisition_eligibility(profile_set, substituted)
    approval = _approval(eligibility)
    authorization = authorize_acquisition(eligibility, approval, _approval_context())
    bundle = AcquisitionAuthorizationVerificationBundle(
        profiles=profile_set,
        assessments=substituted,
        eligibility=eligibility,
        approval=approval,
        approval_evidence=_approval_context(),
        authorization=authorization,
    )

    with pytest.raises(ValueError, match="recorded rights assessment"):
        transition_acquisition_authorized(state, bundle)


def make_profile(purpose: ConsumerPurpose) -> QualificationProfileV1:
    return QualificationProfileV1(
        profile_id=uuid7(),
        profile_version="1",
        provider=ProviderProductScopeV1(
            provider_legal_name="Example Data LLC",
            provider_legal_id="provider-1",
            product_id="daily-equities",
            dataset_ids=("daily",),
            publisher_ids=("publisher",),
            declared_fields=("close", "volume"),
            methodology_reference_hashes=(H[0],),
            schema_reference_hashes=(H[1],),
        ),
        subscriber=SubscriberUseScopeV1(
            subscriber_legal_entity="Example Research LLC",
            authorized_user_id="user-1",
            model_development_requested=True,
            trading_support_requested=True,
            provider_classification_label=None,
            classification_unresolved=True,
            classification_evidence_hashes=(H[2],),
        ),
        infrastructure=InfrastructureScopeV1(
            machine_identity="mac-arm64-1",
            user_ids=("user-1",),
            contractor_ids=(),
            shared_account=False,
            real_data_ci=False,
            cloud_processing=False,
            service_provider_ids=(),
            private_store_policy_hash=H[3],
            backup_location_ids=(),
        ),
        data=QualificationDataScopeV1(
            market="US",
            frequency="daily_equity",
            security_ids=("security-1",),
            universe_ids=("universe-1",),
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            requested_fields=("close", "volume"),
            revision_cutoff=NOW,
            event_window_ids=("G01",),
            sessions_before_event=20,
            sessions_after_event=20,
        ),
        purpose=purpose,
        critical_dimensions=(QualificationDimension.LICENSING_RETENTION,),
        required_golden_case_ids=("G01",),
        golden_case_instance_manifest_hash=H[4],
        adjudication_policy_hash=H[5],
    )


def pilot() -> tuple[
    PilotProfileSetV1,
    QualificationProfileV1,
    QualificationProfileV1,
    M1ePilotStateV1,
]:
    decision = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    audit = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(decision, audit)
    )
    state = M1ePilotStateV1(
        profile_set_hash=content_hash(profile_set),
        purpose_states=cast(
            tuple[PurposeStageStateV1, PurposeStageStateV1],
            tuple(
                PurposeStageStateV1(
                    purpose=item.purpose,
                    profile_hash=qualification_profile_hash(item),
                    stage=None,
                    reached_stage_artifact_hashes=(),
                    terminal_blocker=None,
                )
                for item in profile_set.profiles
            ),
        ),
        shared_artifact_hashes=(),
    )
    return profile_set, decision, audit, state


def freeze_transition(
    profile_set: PilotProfileSetV1,
    profile: QualificationProfileV1,
) -> M1eTransitionV1:
    return M1eTransitionV1(
        transition_id=uuid7(),
        profile_set=profile_set,
        profile=profile,
    )


def test_profile_freeze_uses_actual_profile_set_and_profile_data() -> None:
    profile_set, decision, audit, state = pilot()

    advanced = transition_pilot(state, freeze_transition(profile_set, decision))

    by_purpose = {item.purpose: item for item in advanced.purpose_states}
    decision_state = by_purpose[decision.purpose]
    assert decision_state.stage is PilotStage.PROFILE_FROZEN
    assert decision_state.reached_stage_artifact_hashes == (
        content_hash(profile_set),
        qualification_profile_hash(decision),
        decision.golden_case_instance_manifest_hash,
    )
    assert by_purpose[audit.purpose].stage is None
    assert advanced.shared_artifact_hashes == tuple(
        sorted(
            (
                content_hash(profile_set),
                decision.golden_case_instance_manifest_hash,
            )
        )
    )


def test_profile_freeze_can_start_each_exact_purpose_once() -> None:
    profile_set, decision, audit, state = pilot()
    state = transition_pilot(state, freeze_transition(profile_set, decision))
    state = transition_pilot(state, freeze_transition(profile_set, audit))

    assert all(item.stage is PilotStage.PROFILE_FROZEN for item in state.purpose_states)
    with pytest.raises(ValueError):
        transition_pilot(state, freeze_transition(profile_set, decision))


def test_profile_freeze_rejects_profile_or_profile_set_substitution() -> None:
    profile_set, decision, audit, state = pilot()
    substitute = make_profile(decision.purpose)
    other_set = PilotProfileSetV1(
        pilot_id=uuid7(),
        pilot_version="1",
        profiles=(substitute, audit.model_copy(update={"profile_id": uuid7()})),
    )

    with pytest.raises(ValueError):
        transition_pilot(state, freeze_transition(profile_set, substitute))
    with pytest.raises(ValueError):
        transition_pilot(state, freeze_transition(other_set, substitute))


def test_generic_future_stage_evidence_and_advancement_are_not_exposed() -> None:
    assert not hasattr(qualification_contracts, "StageArtifactKind")
    assert not hasattr(qualification_contracts, "StageArtifactReferenceV1")
    profile_set, decision, _, _ = pilot()
    transition = freeze_transition(profile_set, decision)

    with pytest.raises(ValidationError):
        transition.model_copy(update={"to_stage": PilotStage.RIGHTS_ASSESSED})
    with pytest.raises(ValueError):
        transition.model_copy(update={"artifacts": (H[0],)})


@pytest.mark.parametrize("stage", LATER_NONTERMINAL_STAGES)
def test_task2_rejects_direct_later_purpose_stage_construction(
    stage: PilotStage,
) -> None:
    with pytest.raises(ValidationError):
        PurposeStageStateV1(
            purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            profile_hash=H[12],
            stage=stage,
            reached_stage_artifact_hashes=(H[0],),
            terminal_blocker=None,
        )


@pytest.mark.parametrize("stage", LATER_NONTERMINAL_STAGES)
def test_task2_rejects_later_stage_hidden_in_pilot_state(
    stage: PilotStage,
) -> None:
    later = PurposeStageStateV1.model_construct(
        schema_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=H[12],
        stage=stage,
        reached_stage_artifact_hashes=(H[0],),
        terminal_blocker=None,
    )
    initial = PurposeStageStateV1(
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        profile_hash=H[13],
        stage=None,
        reached_stage_artifact_hashes=(),
        terminal_blocker=None,
    )

    with pytest.raises(ValidationError):
        M1ePilotStateV1(
            profile_set_hash=H[14],
            purpose_states=(later, initial),
            shared_artifact_hashes=(),
        )


@pytest.mark.parametrize(
    ("acquisition_state", "blocker"),
    [
        (AcquisitionState.NOT_ACQUIRED, QualificationDimension.LICENSING_RETENTION),
        (
            AcquisitionState.ACQUIRED_UNSNAPSHOTTED,
            QualificationDimension.ACQUISITION_SNAPSHOT,
        ),
        (
            AcquisitionState.SNAPSHOT_BOUND,
            QualificationDimension.OBSERVATIONS_METHODOLOGIES,
        ),
    ],
)
def test_negative_report_is_deterministic_and_never_invents_outputs(
    acquisition_state: AcquisitionState, blocker: QualificationDimension
) -> None:
    value = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    profile_hash = qualification_profile_hash(value)
    if acquisition_state is AcquisitionState.NOT_ACQUIRED:
        qualification_target = QualificationTargetV1(
            profile_hash=profile_hash,
            acquisition_state=acquisition_state,
            receipt_hashes=(),
            snapshot_hash=None,
            failure_evidence_hashes=(H[0],),
        )
    elif acquisition_state is AcquisitionState.ACQUIRED_UNSNAPSHOTTED:
        qualification_target = QualificationTargetV1(
            profile_hash=profile_hash,
            acquisition_state=acquisition_state,
            receipt_hashes=(H[0],),
            snapshot_hash=None,
            failure_evidence_hashes=(H[1],),
        )
    else:
        qualification_target = QualificationTargetV1(
            profile_hash=profile_hash,
            acquisition_state=acquisition_state,
            receipt_hashes=(H[0],),
            snapshot_hash=H[1],
            failure_evidence_hashes=(),
        )
    passed = DimensionQualificationResultV1(
        dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
        purpose=value.purpose,
        status=QualificationStatus.PASS,
        reachability=ExecutionReachability.REACHED,
        evidence_hashes=(H[2],),
        tested_golden_case_ids=("G01",),
        admitted_purpose=True,
        limitations=(),
        adjudication_policy_hash=value.adjudication_policy_hash,
    )
    blocked = passed.model_copy(
        update={
            "dimension": blocker,
            "status": QualificationStatus.FAIL,
            "admitted_purpose": False,
            "limitations": ("blocked",),
        }
    )

    report = build_negative_report(
        qualification_target,
        (passed, blocked),
        blocker,
        report_id=REPORT_ID,
        reported_at=NOW,
    )
    repeated = build_negative_report(
        qualification_target,
        (passed, blocked),
        blocker,
        report_id=REPORT_ID,
        reported_at=NOW,
    )

    assert repeated == report
    assert report.report_id == REPORT_ID
    assert report.reported_at == NOW
    by_dimension = {item.dimension: item for item in report.results}
    assert by_dimension[passed.dimension] == passed
    assert by_dimension[blocker] == blocked
    assert all(
        item.status is QualificationStatus.UNKNOWN
        and item.reachability is ExecutionReachability.NOT_REACHED
        and not item.evidence_hashes
        and not item.tested_golden_case_ids
        and not item.admitted_purpose
        for item in report.results
        if item.dimension not in {passed.dimension, blocker}
    )
    assert report.target == qualification_target
    assert report.pre_replay_report_hash is None


def test_negative_report_rejects_pass_blocker_or_cross_purpose_results() -> None:
    decision = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    qualification_target = QualificationTargetV1(
        profile_hash=qualification_profile_hash(decision),
        acquisition_state=AcquisitionState.NOT_ACQUIRED,
        receipt_hashes=(),
        snapshot_hash=None,
        failure_evidence_hashes=(H[0],),
    )
    passed = DimensionQualificationResultV1(
        dimension=QualificationDimension.LICENSING_RETENTION,
        purpose=decision.purpose,
        status=QualificationStatus.PASS,
        reachability=ExecutionReachability.REACHED,
        evidence_hashes=(H[1],),
        tested_golden_case_ids=(),
        admitted_purpose=True,
        limitations=(),
        adjudication_policy_hash=decision.adjudication_policy_hash,
    )
    audit = passed.model_copy(update={"purpose": ConsumerPurpose.RETROSPECTIVE_AUDIT})

    with pytest.raises(ValueError):
        build_negative_report(
            qualification_target,
            (passed,),
            QualificationDimension.LICENSING_RETENTION,
            report_id=REPORT_ID,
            reported_at=NOW,
        )
    with pytest.raises(ValueError):
        build_negative_report(
            qualification_target,
            (
                passed.model_copy(
                    update={
                        "status": QualificationStatus.FAIL,
                        "admitted_purpose": False,
                        "limitations": ("blocked",),
                    }
                ),
                audit,
            ),
            QualificationDimension.LICENSING_RETENTION,
            report_id=REPORT_ID,
            reported_at=NOW,
        )
