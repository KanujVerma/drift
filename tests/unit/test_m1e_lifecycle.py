from datetime import UTC, date, datetime
from hashlib import sha256
from typing import cast
from uuid import uuid7

import pytest
from pydantic import ValidationError

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
    StageArtifactKind,
    StageArtifactReferenceV1,
    SubscriberUseScopeV1,
    build_negative_report,
    qualification_profile_hash,
)
from drift.qualification.lifecycle import transition_pilot
from drift.serialization.canonical import content_hash

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


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
        critical_dimensions=tuple(QualificationDimension),
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


REQUIRED_KINDS = {
    PilotStage.PROFILE_FROZEN: (
        StageArtifactKind.PILOT_PROFILE_SET,
        StageArtifactKind.QUALIFICATION_PROFILE,
        StageArtifactKind.GOLDEN_CASE_INSTANCE_MANIFEST,
    ),
    PilotStage.RIGHTS_ASSESSED: (
        StageArtifactKind.VALIDATED_RIGHTS_ASSESSMENT,
        StageArtifactKind.CONTRACT_TOPOLOGY_EVIDENCE,
    ),
    PilotStage.ACQUISITION_AUTHORIZED: (
        StageArtifactKind.ACQUISITION_ELIGIBILITY,
        StageArtifactKind.ACQUISITION_APPROVAL,
        StageArtifactKind.ACQUISITION_AUTHORIZATION,
    ),
    PilotStage.ACQUIRED: (
        StageArtifactKind.ACQUISITION_PLAN,
        StageArtifactKind.ACQUISITION_RECEIPT,
        StageArtifactKind.NATIVE_BYTE_GRAPH,
        StageArtifactKind.ACQUISITION_RECONCILIATION,
    ),
    PilotStage.SNAPSHOT_FROZEN: (
        StageArtifactKind.QUALIFICATION_TARGET,
        StageArtifactKind.ACQUISITION_RECEIPT,
        StageArtifactKind.CANDIDATE_VALIDATION_CONTEXT,
        StageArtifactKind.CROSS_COMPONENT_CONSISTENCY,
        StageArtifactKind.REPLAY_INPUT_INVENTORY,
        StageArtifactKind.EXPECTED_M1B_M1D_OUTPUTS,
        StageArtifactKind.REAL_SOURCE_SNAPSHOT,
    ),
    PilotStage.QUALIFIED: (
        StageArtifactKind.GOLDEN_CASE_RESULTS,
        StageArtifactKind.PRE_REPLAY_QUALIFICATION_REPORT,
    ),
    PilotStage.REPLAY_AUTHORIZED: (StageArtifactKind.REPLAY_AUTHORIZATION_DECISION,),
    PilotStage.REPLAYED: (
        StageArtifactKind.REPLAY_EXECUTION_RECORD,
        StageArtifactKind.SYSTEM_OFFLINE_ATTESTATION,
        StageArtifactKind.FRESH_RESTORE_ATTESTATION,
        StageArtifactKind.REPLAY_RESULT,
    ),
}


def make_transition(
    purpose: ConsumerPurpose,
    profile_hash: str,
    from_stage: PilotStage | None,
    to_stage: PilotStage,
    *,
    authorized_profile_hashes: tuple[str, ...] = (),
) -> M1eTransitionV1:
    kinds = REQUIRED_KINDS[to_stage]
    artifacts = tuple(
        StageArtifactReferenceV1(
            kind=kind, artifact_hash=sha256(kind.value.encode()).hexdigest()
        )
        for kind in kinds
    )
    return M1eTransitionV1(
        transition_id=uuid7(),
        purpose=purpose,
        profile_hash=profile_hash,
        from_stage=from_stage,
        to_stage=to_stage,
        artifacts=artifacts,
        authorized_profile_hashes=authorized_profile_hashes,
        shared_artifact_hashes=(),
    )


def advance_to(
    state: M1ePilotStateV1,
    purpose: ConsumerPurpose,
    profile_hash: str,
    destination: PilotStage,
) -> M1ePilotStateV1:
    current: PilotStage | None = None
    for next_stage in tuple(REQUIRED_KINDS):
        transition = make_transition(
            purpose,
            profile_hash,
            current,
            next_stage,
            authorized_profile_hashes=(profile_hash,)
            if next_stage in {PilotStage.ACQUISITION_AUTHORIZED, PilotStage.ACQUIRED}
            else (),
        )
        state = transition_pilot(state, transition)
        current = next_stage
        if next_stage is destination:
            return state
    raise AssertionError("unreachable destination")


def test_every_nonterminal_transition_advances_one_purpose_only() -> None:
    _, decision, audit, state = pilot()
    decision_hash = qualification_profile_hash(decision)
    state = advance_to(state, decision.purpose, decision_hash, PilotStage.REPLAYED)

    by_purpose = {item.purpose: item for item in state.purpose_states}
    assert by_purpose[decision.purpose].stage is PilotStage.REPLAYED
    assert by_purpose[audit.purpose].stage is None
    reached_hashes = by_purpose[decision.purpose].reached_stage_artifact_hashes
    receipt_hash = sha256(
        StageArtifactKind.ACQUISITION_RECEIPT.value.encode()
    ).hexdigest()
    assert len(reached_hashes) == 26
    assert reached_hashes.count(receipt_hash) == 2
    assert by_purpose[audit.purpose].reached_stage_artifact_hashes == ()


@pytest.mark.parametrize(
    ("from_stage", "to_stage"),
    [
        (None, PilotStage.RIGHTS_ASSESSED),
        (PilotStage.PROFILE_FROZEN, PilotStage.ACQUISITION_AUTHORIZED),
        (PilotStage.RIGHTS_ASSESSED, PilotStage.PROFILE_FROZEN),
        (PilotStage.QUALIFIED, PilotStage.SNAPSHOT_FROZEN),
        (PilotStage.REPLAYED, PilotStage.REPLAYED),
    ],
)
def test_skip_backtrack_and_repeat_are_rejected(
    from_stage: PilotStage | None, to_stage: PilotStage
) -> None:
    _, decision, _, state = pilot()
    profile_hash = qualification_profile_hash(decision)
    if from_stage is not None:
        state = advance_to(state, decision.purpose, profile_hash, from_stage)

    with pytest.raises(ValueError):
        transition_pilot(
            state,
            make_transition(decision.purpose, profile_hash, from_stage, to_stage),
        )


def test_transition_rejects_purpose_and_profile_hash_substitution() -> None:
    _, decision, audit, state = pilot()
    decision_hash = qualification_profile_hash(decision)
    audit_hash = qualification_profile_hash(audit)

    with pytest.raises(ValueError):
        transition_pilot(
            state,
            make_transition(
                decision.purpose, audit_hash, None, PilotStage.PROFILE_FROZEN
            ),
        )
    with pytest.raises(ValueError):
        transition_pilot(
            state,
            make_transition(
                ConsumerPurpose.RETROSPECTIVE_AUDIT,
                decision_hash,
                None,
                PilotStage.PROFILE_FROZEN,
            ),
        )


def test_transition_rejects_missing_named_guard_artifact() -> None:
    _, decision, _, state = pilot()
    profile_hash = qualification_profile_hash(decision)
    transition = make_transition(
        decision.purpose, profile_hash, None, PilotStage.PROFILE_FROZEN
    )

    with pytest.raises(ValidationError):
        transition.model_copy(update={"artifacts": transition.artifacts[:-1]})


def test_shared_receipt_cannot_advance_unauthorized_sibling_profile() -> None:
    _, decision, audit, state = pilot()
    decision_hash = qualification_profile_hash(decision)
    audit_hash = qualification_profile_hash(audit)
    state = advance_to(state, audit.purpose, audit_hash, PilotStage.RIGHTS_ASSESSED)
    with pytest.raises(ValueError):
        transition_pilot(
            state,
            make_transition(
                audit.purpose,
                audit_hash,
                PilotStage.RIGHTS_ASSESSED,
                PilotStage.ACQUISITION_AUTHORIZED,
                authorized_profile_hashes=(decision_hash,),
            ),
        )


@pytest.mark.parametrize(
    "terminal",
    [PilotStage.COMPLETED_POSITIVE, PilotStage.COMPLETED_NEGATIVE],
)
def test_lifecycle_exposes_no_terminal_transition_finalizer(
    terminal: PilotStage,
) -> None:
    _, decision, _, state = pilot()
    profile_hash = qualification_profile_hash(decision)
    state = advance_to(state, decision.purpose, profile_hash, PilotStage.REPLAYED)

    with pytest.raises(ValidationError):
        M1eTransitionV1(
            transition_id=uuid7(),
            purpose=decision.purpose,
            profile_hash=profile_hash,
            from_stage=PilotStage.REPLAYED,
            to_stage=terminal,
            artifacts=(),
            authorized_profile_hashes=(),
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
def test_negative_report_preserves_reached_results_and_never_invents_outputs(
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

    report = build_negative_report(qualification_target, (passed, blocked), blocker)

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
        )
