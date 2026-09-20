"""Unit tests for M2 promotion evidence validation against M1e qualification."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from drift.domain.common import FrozenModel
from drift.domain.evaluator_lanes import (
    PromotionEvaluationAdmissionV1,
    promotion_evaluation_admission_hash,
)
from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    DimensionQualificationResultV1,
    ExecutionReachability,
    M1eCompletionKind,
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PilotStage,
    PurposeQualificationReportV1,
    PurposeStageStateV1,
    QualificationDimension,
    QualificationProfileV1,
    QualificationStatus,
    QualificationTargetV1,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import (
    QualifiedSourceHandoffV1,
    qualified_source_handoff_hash,
)
from drift.evaluator.admission import validate_m1e_promotion_evidence
from drift.serialization.canonical import content_hash

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
PILOT_ID = UUID("0191f618-b200-7bb0-85f0-b49e29a67a01")
REPORT_ID_1 = UUID("0191f618-b200-7bb0-85f0-b49e29a67a02")
REPORT_ID_2 = UUID("0191f618-b200-7bb0-85f0-b49e29a67a03")
HANDOFF_ID_1 = UUID("0191f618-b200-7bb0-85f0-b49e29a67a04")
HANDOFF_ID_2 = UUID("0191f618-b200-7bb0-85f0-b49e29a67a05")
COMPLETION_ID = UUID("0191f618-b200-7bb0-85f0-b49e29a67a06")


def make_dimension_result(
    dim: QualificationDimension,
    status: QualificationStatus = QualificationStatus.PASS,
    reachability: ExecutionReachability = ExecutionReachability.REACHED,
    admitted: bool = True,
    purpose: ConsumerPurpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT,
    limitations: tuple[str, ...] = (),
) -> DimensionQualificationResultV1:
    if status is not QualificationStatus.PASS and not limitations:
        limitations = ("acknowledged-limitation",)
    if status in {QualificationStatus.FAIL, QualificationStatus.UNKNOWN}:
        admitted = False
    return DimensionQualificationResultV1(
        dimension=dim,
        purpose=purpose,
        status=status,
        reachability=reachability,
        evidence_hashes=(H1,),
        tested_golden_case_ids=(),
        limitations=limitations,
        admitted_purpose=admitted,
        adjudication_policy_hash=H1,
    )


def make_test_fixture() -> dict[str, Any]:
    # 1. Profiles
    crit_dims = (
        QualificationDimension.LICENSING_RETENTION,
        QualificationDimension.REVISIONS_POINT_IN_TIME,
    )
    decision_profile = QualificationProfileV1.model_construct(
        schema_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        declared_provider="vendor_a",
        critical_dimensions=crit_dims,
    )
    audit_profile = QualificationProfileV1.model_construct(
        schema_version="1",
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        declared_provider="vendor_a",
        critical_dimensions=crit_dims,
    )
    dec_prof_hash = qualification_profile_hash(decision_profile)
    audit_prof_hash = qualification_profile_hash(audit_profile)

    # 2. Profile set
    profile_set = PilotProfileSetV1.model_construct(
        schema_version="1",
        pilot_id=PILOT_ID,
        pilot_version="1",
        profiles=(decision_profile, audit_profile),
    )
    profile_set_hash = content_hash(profile_set)

    # 3. Targets and Reports (sharing snapshot H5)
    dec_target = QualificationTargetV1(
        profile_hash=dec_prof_hash,
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H1,),
        snapshot_hash=H5,
        failure_evidence_hashes=(),
    )
    audit_target = QualificationTargetV1(
        profile_hash=audit_prof_hash,
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H1,),
        snapshot_hash=H5,
        failure_evidence_hashes=(),
    )

    dec_results = tuple(
        make_dimension_result(d, purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT)
        for d in QualificationDimension
    )
    audit_results = tuple(
        make_dimension_result(d, purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT)
        for d in QualificationDimension
    )

    dec_report = PurposeQualificationReportV1(
        report_id=REPORT_ID_1,
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=dec_target,
        results=dec_results,
        pre_replay_report_hash=H1,
    )
    audit_report = PurposeQualificationReportV1(
        report_id=REPORT_ID_2,
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        target=audit_target,
        results=audit_results,
        pre_replay_report_hash=H2,
    )

    # 4. Purpose States
    dec_state = PurposeStageStateV1.model_construct(
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=dec_prof_hash,
        stage=PilotStage.COMPLETED_POSITIVE,
        reached_stage_artifact_hashes=(H1,),
        terminal_blocker=None,
    )
    audit_state = PurposeStageStateV1.model_construct(
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        profile_hash=audit_prof_hash,
        stage=PilotStage.COMPLETED_POSITIVE,
        reached_stage_artifact_hashes=(H2,),
        terminal_blocker=None,
    )

    # 5. Completion Record
    completion = M1eCompletionRecordV1.model_construct(
        schema_version="1",
        completion_id=COMPLETION_ID,
        completion_version="1",
        completed_at=NOW,
        profile_set_hash=profile_set_hash,
        purpose_states=(dec_state, audit_state),
        shared_artifact_hashes=(H1,),
        blocking_dimensions=(),
        blocking_evidence_hashes=(),
        purpose_reports=(dec_report, audit_report),
        content_dispositions=(),
        external_dependencies=(),
        completion_kind=M1eCompletionKind.COMPLETED_POSITIVE,
    )
    completion_hash = content_hash(completion)

    # 6. QualifiedSourceHandoffV1
    dec_handoff_unhashed = QualifiedSourceHandoffV1.model_construct(
        schema_version="1",
        handoff_id=HANDOFF_ID_1,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=dec_prof_hash,
        report_hash=content_hash(dec_report),
        target_hash=content_hash(dec_target),
        snapshot_hash=H5,
        rights_assessment_hash=H3,
        universe_references=("drift+sha256://univ",),
        economic_outcome_references=(),
        observation_view_references=(),
        session_view_references=(),
        environment_closure_hash=H6,
        replay_authorization_hash=H7,
        limitations=(),
        handoff_hash=H0,
    )
    dec_handoff = dec_handoff_unhashed.model_copy(
        update={"handoff_hash": qualified_source_handoff_hash(dec_handoff_unhashed)}
    )

    audit_handoff_unhashed = QualifiedSourceHandoffV1.model_construct(
        schema_version="1",
        handoff_id=HANDOFF_ID_2,
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        profile_hash=audit_prof_hash,
        report_hash=content_hash(audit_report),
        target_hash=content_hash(audit_target),
        snapshot_hash=H5,
        rights_assessment_hash=H4,
        universe_references=("drift+sha256://univ",),
        economic_outcome_references=(),
        observation_view_references=(),
        session_view_references=(),
        environment_closure_hash=H6,
        replay_authorization_hash=H7,
        limitations=(),
        handoff_hash=H0,
    )
    audit_handoff = audit_handoff_unhashed.model_copy(
        update={"handoff_hash": qualified_source_handoff_hash(audit_handoff_unhashed)}
    )

    # 7. Admission
    admission_unhashed = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash=completion_hash,
        m1e_profile_set_hash=profile_set_hash,
        decision_handoff_hash=dec_handoff.handoff_hash,
        audit_handoff_hash=audit_handoff.handoff_hash,
        input_bundle_hash=H1,
        admission_hash=H0,
    )
    admission = admission_unhashed.model_copy(
        update={
            "admission_hash": promotion_evaluation_admission_hash(admission_unhashed)
        }
    )

    return {
        "admission": admission,
        "profile_set": profile_set,
        "completion": completion,
        "decision_profile": decision_profile,
        "audit_profile": audit_profile,
        "decision_report": dec_report,
        "audit_report": audit_report,
        "decision_handoff": dec_handoff,
        "audit_handoff": audit_handoff,
    }


def copy_constructed[T: FrozenModel](model: T, **updates: object) -> T:
    data = dict(model)
    data.update(updates)
    return type(model).model_construct(**data)


def rebind_admission(
    fixture: dict[str, Any], **updates: object
) -> PromotionEvaluationAdmissionV1:
    admission: PromotionEvaluationAdmissionV1 = fixture["admission"]
    rebound = copy_constructed(admission, **updates)
    return copy_constructed(
        rebound, admission_hash=promotion_evaluation_admission_hash(rebound)
    )


def test_validate_m1e_promotion_evidence_happy_path() -> None:
    f = make_test_fixture()
    # Should complete without error
    validate_m1e_promotion_evidence(**f)


def test_validate_m1e_promotion_evidence_rejects_negative_completion() -> None:
    f = make_test_fixture()
    bad_completion = copy_constructed(
        f["completion"], completion_kind=M1eCompletionKind.COMPLETED_NEGATIVE
    )
    bad_adm = copy_constructed(
        f["admission"], m1e_completion_record_hash=content_hash(bad_completion)
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="positive M1e completion"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_completion, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_completion_hash_mismatch() -> None:
    f = make_test_fixture()
    bad_adm = copy_constructed(f["admission"], m1e_completion_record_hash=H4)
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="completion record hash mismatch"):
        validate_m1e_promotion_evidence(**{**f, "admission": bad_adm})


def test_validate_m1e_promotion_evidence_rejects_profile_set_mismatch() -> None:
    f = make_test_fixture()
    bad_adm = copy_constructed(f["admission"], m1e_profile_set_hash=H4)
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="profile set hash mismatch"):
        validate_m1e_promotion_evidence(**{**f, "admission": bad_adm})


def test_validate_m1e_promotion_evidence_rejects_unlisted_profile() -> None:
    f = make_test_fixture()
    foreign_profile = QualificationProfileV1.model_construct(
        schema_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        declared_provider="vendor_foreign",
        critical_dimensions=(),
    )
    with pytest.raises(ValueError, match="not a member of bound profile set"):
        validate_m1e_promotion_evidence(**{**f, "decision_profile": foreign_profile})


def test_validate_m1e_promotion_evidence_rejects_purpose_mismatch() -> None:
    f = make_test_fixture()
    # Swap decision and audit profiles
    with pytest.raises(ValueError, match="historical_decision_input purpose"):
        validate_m1e_promotion_evidence(**{**f, "decision_profile": f["audit_profile"]})


def test_validate_m1e_promotion_evidence_rejects_missing_purpose_state() -> None:
    f = make_test_fixture()
    # completion with only decision state, missing audit state
    bad_comp = copy_constructed(
        f["completion"], purpose_states=(f["completion"].purpose_states[0],)
    )
    bad_adm = copy_constructed(
        f["admission"], m1e_completion_record_hash=content_hash(bad_comp)
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="missing retrospective_audit purpose state"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_purpose_state_terminal_blocker() -> (
    None
):
    f = make_test_fixture()
    blocked_state = copy_constructed(
        f["completion"].purpose_states[0],
        terminal_blocker=QualificationDimension.LICENSING_RETENTION,
    )
    bad_comp = copy_constructed(
        f["completion"],
        purpose_states=(blocked_state, f["completion"].purpose_states[1]),
    )
    bad_adm = copy_constructed(
        f["admission"], m1e_completion_record_hash=content_hash(bad_comp)
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="terminal blocker"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_critical_dimension_fail() -> None:
    f = make_test_fixture()
    # Mutate critical dimension LICENSING_RETENTION in decision report to FAIL
    bad_results = list(f["decision_report"].results)
    for i, r in enumerate(bad_results):
        if r.dimension == QualificationDimension.LICENSING_RETENTION:
            bad_results[i] = make_dimension_result(
                r.dimension,
                status=QualificationStatus.FAIL,
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            )
    bad_report = copy_constructed(f["decision_report"], results=tuple(bad_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = copy_constructed(
        f["admission"],
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="did not PASS"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_allows_non_critical_partial() -> None:
    f = make_test_fixture()
    # Mutate non-critical dimension (e.g. COVERAGE_OMISSION) to PARTIAL
    mod_results = list(f["decision_report"].results)
    for i, r in enumerate(mod_results):
        if r.dimension == QualificationDimension.COVERAGE_OMISSION:
            mod_results[i] = make_dimension_result(
                r.dimension,
                status=QualificationStatus.PARTIAL,
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            )
    mod_report = copy_constructed(f["decision_report"], results=tuple(mod_results))
    mod_comp = copy_constructed(
        f["completion"], purpose_reports=(mod_report, f["audit_report"])
    )
    mod_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(mod_report)
    )
    mod_handoff = copy_constructed(
        mod_handoff, handoff_hash=qualified_source_handoff_hash(mod_handoff)
    )
    mod_adm = copy_constructed(
        f["admission"],
        m1e_completion_record_hash=content_hash(mod_comp),
        decision_handoff_hash=mod_handoff.handoff_hash,
    )
    mod_adm = copy_constructed(
        mod_adm, admission_hash=promotion_evaluation_admission_hash(mod_adm)
    )
    # Non-critical PARTIAL does NOT fail admission
    validate_m1e_promotion_evidence(
        **{
            **f,
            "decision_report": mod_report,
            "completion": mod_comp,
            "decision_handoff": mod_handoff,
            "admission": mod_adm,
        }
    )


def test_validate_m1e_promotion_evidence_rejects_snapshot_mismatch() -> None:
    f = make_test_fixture()
    # Audit target points to different snapshot H4
    bad_target = copy_constructed(f["audit_report"].target, snapshot_hash=H4)
    bad_report = copy_constructed(f["audit_report"], target=bad_target)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(f["decision_report"], bad_report)
    )
    bad_handoff = copy_constructed(
        f["audit_handoff"],
        target_hash=content_hash(bad_target),
        report_hash=content_hash(bad_report),
        snapshot_hash=H4,
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = copy_constructed(
        f["admission"],
        m1e_completion_record_hash=content_hash(bad_comp),
        audit_handoff_hash=bad_handoff.handoff_hash,
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="identical snapshot hash"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "audit_report": bad_report,
                "completion": bad_comp,
                "audit_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_handoff_hash_mismatch() -> None:
    f = make_test_fixture()
    bad_adm = copy_constructed(f["admission"], decision_handoff_hash=H4)
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="decision handoff hash mismatch"):
        validate_m1e_promotion_evidence(**{**f, "admission": bad_adm})


def test_validate_m1e_promotion_evidence_rejects_missing_env_closure() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], environment_closure_hash=None)
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = copy_constructed(
        f["admission"], decision_handoff_hash=bad_handoff.handoff_hash
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="missing environment closure hash"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_missing_replay_auth() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(
        f["decision_handoff"], replay_authorization_hash=None
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = copy_constructed(
        f["admission"], decision_handoff_hash=bad_handoff.handoff_hash
    )
    bad_adm = copy_constructed(
        bad_adm, admission_hash=promotion_evaluation_admission_hash(bad_adm)
    )
    with pytest.raises(ValueError, match="missing replay authorization hash"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_audit_profile_wrong_purpose() -> None:
    f = make_test_fixture()
    with pytest.raises(ValueError, match="retrospective_audit purpose"):
        validate_m1e_promotion_evidence(**{**f, "audit_profile": f["decision_profile"]})


def test_validate_m1e_promotion_evidence_rejects_audit_profile_not_in_set() -> None:
    f = make_test_fixture()
    foreign_profile = QualificationProfileV1.model_construct(
        schema_version="1",
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        declared_provider="vendor_foreign",
        critical_dimensions=(),
    )
    with pytest.raises(ValueError, match="not a member of bound profile set"):
        validate_m1e_promotion_evidence(**{**f, "audit_profile": foreign_profile})


def test_validate_m1e_promotion_evidence_rejects_duplicate_purpose_states() -> None:
    f = make_test_fixture()
    dup_state = f["completion"].purpose_states[0]
    bad_comp = copy_constructed(f["completion"], purpose_states=(dup_state, dup_state))
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="duplicate purpose states"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_duplicate_purpose_reports() -> None:
    f = make_test_fixture()
    dup_report = f["completion"].purpose_reports[0]
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(dup_report, dup_report)
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="duplicate purpose reports"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_purpose_state_profile_mismatch() -> (
    None
):
    f = make_test_fixture()
    bad_state = copy_constructed(f["completion"].purpose_states[0], profile_hash=H4)
    bad_comp = copy_constructed(
        f["completion"],
        purpose_states=(bad_state, f["completion"].purpose_states[1]),
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="purpose state profile hash mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_noncompleted_purpose_state() -> None:
    f = make_test_fixture()
    bad_state = copy_constructed(
        f["completion"].purpose_states[1], stage=PilotStage.QUALIFIED
    )
    bad_comp = copy_constructed(
        f["completion"],
        purpose_states=(f["completion"].purpose_states[0], bad_state),
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="is not COMPLETED_POSITIVE"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_unbound_decision_report() -> None:
    f = make_test_fixture()
    distinct_report = copy_constructed(f["decision_report"], report_id=REPORT_ID_2)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(distinct_report, f["audit_report"])
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(
        ValueError, match="decision report does not match completion purpose report"
    ):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_unbound_audit_report() -> None:
    f = make_test_fixture()
    distinct_report = copy_constructed(f["audit_report"], report_id=REPORT_ID_1)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(f["decision_report"], distinct_report)
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(
        ValueError, match="audit report does not match completion purpose report"
    ):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_report_target_profile_mismatch() -> (
    None
):
    f = make_test_fixture()
    bad_target = copy_constructed(f["decision_report"].target, profile_hash=H4)
    bad_report = copy_constructed(f["decision_report"], target=bad_target)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"],
        report_hash=content_hash(bad_report),
        target_hash=content_hash(bad_target),
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="report target profile hash mismatch"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_unsnapshotted_target() -> None:
    f = make_test_fixture()
    bad_target = copy_constructed(
        f["decision_report"].target,
        acquisition_state=AcquisitionState.ACQUIRED_UNSNAPSHOTTED,
    )
    bad_report = copy_constructed(f["decision_report"], target=bad_target)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="not snapshot-bound"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_missing_snapshot() -> None:
    f = make_test_fixture()
    bad_target = copy_constructed(f["decision_report"].target, snapshot_hash=None)
    bad_report = copy_constructed(f["decision_report"], target=bad_target)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="has no snapshot hash"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_critical_unknown() -> None:
    f = make_test_fixture()
    bad_results = list(f["decision_report"].results)
    for i, r in enumerate(bad_results):
        if r.dimension == QualificationDimension.LICENSING_RETENTION:
            bad_results[i] = make_dimension_result(
                r.dimension,
                status=QualificationStatus.UNKNOWN,
                reachability=ExecutionReachability.REACHED,
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                limitations=("unresolved-evidence",),
            )
    bad_report = copy_constructed(f["decision_report"], results=tuple(bad_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="did not PASS"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_critical_not_reached() -> None:
    f = make_test_fixture()
    bad_results = list(f["decision_report"].results)
    for i, r in enumerate(bad_results):
        if r.dimension == QualificationDimension.LICENSING_RETENTION:
            bad_results[i] = copy_constructed(
                r, reachability=ExecutionReachability.NOT_REACHED
            )
    bad_report = copy_constructed(f["decision_report"], results=tuple(bad_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="is not REACHED"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_critical_admitted_false() -> None:
    f = make_test_fixture()
    bad_results = list(f["decision_report"].results)
    for i, r in enumerate(bad_results):
        if r.dimension == QualificationDimension.LICENSING_RETENTION:
            bad_results[i] = copy_constructed(r, admitted_purpose=False)
    bad_report = copy_constructed(f["decision_report"], results=tuple(bad_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="was not admitted"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_wrong_dimension_set() -> None:
    f = make_test_fixture()
    trimmed = tuple(
        r
        for r in f["decision_report"].results
        if r.dimension != QualificationDimension.LICENSING_RETENTION
    )
    bad_report = copy_constructed(f["decision_report"], results=trimmed)
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="exact 12 dimension set"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_fake_handoff_hash() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], handoff_hash=H4)
    bad_adm = rebind_admission(f, decision_handoff_hash=H4)
    with pytest.raises(ValueError, match="inconsistent decision handoff hash"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_decision_handoff_wrong_purpose() -> (
    None
):
    f = make_test_fixture()
    bad_handoff = copy_constructed(
        f["decision_handoff"], purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, decision_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff purpose mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_audit_handoff_wrong_purpose() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(
        f["audit_handoff"], purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, audit_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff purpose mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "audit_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_handoff_profile_mismatch() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], profile_hash=H4)
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, decision_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff profile hash mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_handoff_report_mismatch() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], report_hash=H4)
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, decision_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff report hash mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_handoff_target_mismatch() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], target_hash=H4)
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, decision_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff target hash mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_handoff_snapshot_mismatch() -> None:
    f = make_test_fixture()
    bad_handoff = copy_constructed(f["decision_handoff"], snapshot_hash=H4)
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(f, decision_handoff_hash=bad_handoff.handoff_hash)
    with pytest.raises(ValueError, match="handoff snapshot hash mismatch"):
        validate_m1e_promotion_evidence(
            **{**f, "decision_handoff": bad_handoff, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_noncritical_not_reached() -> None:
    f = make_test_fixture()
    mod_results = list(f["decision_report"].results)
    for i, r in enumerate(mod_results):
        if r.dimension == QualificationDimension.COVERAGE_OMISSION:
            mod_results[i] = copy_constructed(
                r, reachability=ExecutionReachability.NOT_REACHED
            )
    bad_report = copy_constructed(f["decision_report"], results=tuple(mod_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="is not REACHED"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_result_purpose_mismatch() -> None:
    f = make_test_fixture()
    bad_results = list(f["decision_report"].results)
    bad_results[0] = copy_constructed(
        bad_results[0], purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT
    )
    bad_report = copy_constructed(f["decision_report"], results=tuple(bad_results))
    bad_comp = copy_constructed(
        f["completion"], purpose_reports=(bad_report, f["audit_report"])
    )
    bad_handoff = copy_constructed(
        f["decision_handoff"], report_hash=content_hash(bad_report)
    )
    bad_handoff = copy_constructed(
        bad_handoff, handoff_hash=qualified_source_handoff_hash(bad_handoff)
    )
    bad_adm = rebind_admission(
        f,
        m1e_completion_record_hash=content_hash(bad_comp),
        decision_handoff_hash=bad_handoff.handoff_hash,
    )
    with pytest.raises(ValueError, match="has purpose mismatch"):
        validate_m1e_promotion_evidence(
            **{
                **f,
                "decision_report": bad_report,
                "completion": bad_comp,
                "decision_handoff": bad_handoff,
                "admission": bad_adm,
            }
        )


def test_validate_m1e_promotion_evidence_rejects_blocking_dimensions() -> None:
    f = make_test_fixture()
    bad_comp = copy_constructed(
        f["completion"],
        blocking_dimensions=(QualificationDimension.LICENSING_RETENTION,),
    )
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="blocking dimensions"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_rejects_blocking_evidence() -> None:
    f = make_test_fixture()
    bad_comp = copy_constructed(f["completion"], blocking_evidence_hashes=(H1,))
    bad_adm = rebind_admission(f, m1e_completion_record_hash=content_hash(bad_comp))
    with pytest.raises(ValueError, match="blocking evidence hashes"):
        validate_m1e_promotion_evidence(
            **{**f, "completion": bad_comp, "admission": bad_adm}
        )


def test_validate_m1e_promotion_evidence_binds_self_excluding_handoff_hash() -> None:
    f = make_test_fixture()
    whole_handoff_hash = content_hash(f["decision_handoff"])
    assert whole_handoff_hash != f["decision_handoff"].handoff_hash
    bad_adm = rebind_admission(f, decision_handoff_hash=whole_handoff_hash)
    with pytest.raises(ValueError, match="decision handoff hash mismatch"):
        validate_m1e_promotion_evidence(**{**f, "admission": bad_adm})
