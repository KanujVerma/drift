from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    DimensionQualificationResultV1,
    ExecutionReachability,
    ExternalDependencyResolutionV1,
    ExternalDependencyStatus,
    InfrastructureScopeV1,
    M1eCompletionKind,
    M1eCompletionRecordV1,
    PilotProfileSetV1,
    PilotStage,
    PreProfileAttemptRecordV1,
    PreProfileAttemptStatus,
    PreReplayQualificationReportV1,
    ProviderProductScopeV1,
    PurposeQualificationReportV1,
    PurposeStageStateV1,
    QualificationDataScopeV1,
    QualificationDimension,
    QualificationProfileV1,
    QualificationStatus,
    QualificationTargetV1,
    SubscriberUseScopeV1,
    qualification_profile_hash,
)
from drift.serialization.canonical import content_hash

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def provider_scope() -> ProviderProductScopeV1:
    return ProviderProductScopeV1(
        provider_legal_name="Example Data LLC",
        provider_legal_id="provider-1",
        product_id="daily-equities",
        dataset_ids=("prices", "actions"),
        publisher_ids=("publisher-b", "publisher-a"),
        declared_fields=("volume", "close"),
        methodology_reference_hashes=(H2, H1),
        schema_reference_hashes=(H4, H3),
    )


def subscriber_scope() -> SubscriberUseScopeV1:
    return SubscriberUseScopeV1(
        subscriber_legal_entity="Example Research LLC",
        authorized_user_id="user-1",
        model_development_requested=True,
        trading_support_requested=True,
        provider_classification_label=None,
        classification_unresolved=True,
        classification_evidence_hashes=(H2, H1),
    )


def infrastructure_scope() -> InfrastructureScopeV1:
    return InfrastructureScopeV1(
        machine_identity="mac-arm64-1",
        user_ids=("user-1",),
        contractor_ids=(),
        shared_account=False,
        real_data_ci=False,
        cloud_processing=False,
        service_provider_ids=(),
        private_store_policy_hash=H1,
        backup_location_ids=("encrypted-backup",),
    )


def data_scope(**updates: object) -> QualificationDataScopeV1:
    values: dict[str, object] = {
        "market": "US",
        "frequency": "daily_equity",
        "security_ids": ("security-b", "security-a"),
        "universe_ids": ("universe-1",),
        "start_date": date(2024, 1, 1),
        "end_date": date(2025, 12, 31),
        "requested_fields": ("volume", "close"),
        "revision_cutoff": NOW,
        "event_window_ids": ("G02", "G01"),
        "sessions_before_event": 20,
        "sessions_after_event": 20,
    }
    values.update(updates)
    return QualificationDataScopeV1.model_validate(values)


def profile(
    purpose: ConsumerPurpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT,
    **updates: object,
) -> QualificationProfileV1:
    values: dict[str, object] = {
        "profile_id": uuid7(),
        "profile_version": "1.0.0",
        "provider": provider_scope(),
        "subscriber": subscriber_scope(),
        "infrastructure": infrastructure_scope(),
        "data": data_scope(),
        "purpose": purpose,
        "critical_dimensions": tuple(QualificationDimension),
        "required_golden_case_ids": ("G02", "G01"),
        "golden_case_instance_manifest_hash": H5,
        "adjudication_policy_hash": H6,
    }
    values.update(updates)
    return QualificationProfileV1.model_validate(values)


def target(
    profile_hash: str,
    state: AcquisitionState = AcquisitionState.SNAPSHOT_BOUND,
) -> QualificationTargetV1:
    if state is AcquisitionState.NOT_ACQUIRED:
        return QualificationTargetV1(
            profile_hash=profile_hash,
            acquisition_state=state,
            receipt_hashes=(),
            snapshot_hash=None,
            failure_evidence_hashes=(H2,),
        )
    if state is AcquisitionState.ACQUIRED_UNSNAPSHOTTED:
        return QualificationTargetV1(
            profile_hash=profile_hash,
            acquisition_state=state,
            receipt_hashes=(H1,),
            snapshot_hash=None,
            failure_evidence_hashes=(H2,),
        )
    return QualificationTargetV1(
        profile_hash=profile_hash,
        acquisition_state=state,
        receipt_hashes=(H1,),
        snapshot_hash=H2,
        failure_evidence_hashes=(),
    )


def dimension_result(
    dimension: QualificationDimension,
    purpose: ConsumerPurpose = ConsumerPurpose.HISTORICAL_DECISION_INPUT,
    *,
    status: QualificationStatus = QualificationStatus.PASS,
    reachability: ExecutionReachability = ExecutionReachability.REACHED,
) -> DimensionQualificationResultV1:
    reached = reachability is ExecutionReachability.REACHED
    return DimensionQualificationResultV1(
        dimension=dimension,
        purpose=purpose,
        status=status if reached else QualificationStatus.UNKNOWN,
        reachability=reachability,
        evidence_hashes=(H1,) if reached else (),
        tested_golden_case_ids=("G01",) if reached else (),
        admitted_purpose=reached and status is QualificationStatus.PASS,
        limitations=()
        if reached and status is QualificationStatus.PASS
        else ("blocked",),
        adjudication_policy_hash=H6,
    )


def test_exact_public_enum_values_and_dimension_count() -> None:
    assert [item.value for item in ConsumerPurpose] == [
        "historical_decision_input",
        "retrospective_audit",
    ]
    assert [item.value for item in QualificationStatus] == [
        "pass",
        "partial",
        "fail",
        "unknown",
    ]
    assert [item.value for item in QualificationDimension] == [
        "security_listing_identity",
        "universe_lifecycle",
        "corporate_action_terms",
        "occurred_effects",
        "settlements_terminal_outcomes",
        "observations_methodologies",
        "scheduled_realized_sessions",
        "revisions_point_in_time",
        "coverage_omission",
        "licensing_retention",
        "acquisition_snapshot",
        "offline_replay",
    ]
    assert len(QualificationDimension) == 12


def test_scope_dump_load_is_stable_and_unordered_inputs_are_canonicalized() -> None:
    value = provider_scope()
    restored = ProviderProductScopeV1.model_validate_json(value.model_dump_json())

    assert restored == value
    assert value.publisher_ids == ("publisher-a", "publisher-b")
    assert value.declared_fields == ("close", "volume")
    assert value.methodology_reference_hashes == (H1, H2)


def test_subscriber_scope_requires_at_least_one_requested_use() -> None:
    value = subscriber_scope()

    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "model_development_requested": False,
                "trading_support_requested": False,
            }
        )


def test_data_scope_enforces_all_pilot_bounds() -> None:
    assert data_scope().security_ids == ("security-a", "security-b")

    invalid_updates = (
        {"security_ids": tuple(f"security-{index}" for index in range(101))},
        {"start_date": date(2024, 1, 1), "end_date": date(2026, 1, 1)},
        {"event_window_ids": tuple(f"G{index:02}" for index in range(21))},
        {"sessions_before_event": 21},
        {"sessions_after_event": 21},
    )
    for update in invalid_updates:
        with pytest.raises(ValidationError):
            data_scope(**update)


def test_profile_is_snapshot_free_and_hashes_exact_canonical_profile() -> None:
    value = profile()

    assert qualification_profile_hash(value) == content_hash(value)
    assert "snapshot" not in QualificationProfileV1.model_fields
    with pytest.raises(ValidationError):
        QualificationProfileV1.model_validate(
            {**value.model_dump(mode="python"), "snapshot_hash": H1}
        )


def test_profile_mutation_cannot_substitute_infrastructure_user() -> None:
    value = profile()
    altered = value.infrastructure.model_copy(update={"user_ids": ("other-user",)})

    with pytest.raises(ValidationError):
        value.model_copy(update={"infrastructure": altered})


def test_pilot_profile_set_requires_exactly_two_matching_purposes_and_scopes() -> None:
    decision = profile()
    audit = profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    value = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(audit, decision)
    )

    assert tuple(item.purpose for item in value.profiles) == tuple(ConsumerPurpose)
    with pytest.raises(ValidationError):
        value.model_copy(update={"profiles": (decision,)})
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "profiles": (
                    decision,
                    audit.model_copy(update={"profile_id": decision.profile_id}),
                )
            }
        )
    with pytest.raises(ValidationError):
        value.model_copy(
            update={
                "profiles": (
                    decision,
                    profile(
                        ConsumerPurpose.RETROSPECTIVE_AUDIT,
                        data=data_scope(requested_fields=("open",)),
                    ),
                )
            }
        )


@pytest.mark.parametrize(
    ("state", "receipts", "snapshot", "failures", "valid"),
    [
        (AcquisitionState.NOT_ACQUIRED, (), None, (H3,), True),
        (AcquisitionState.NOT_ACQUIRED, (H1,), None, (H3,), False),
        (AcquisitionState.ACQUIRED_UNSNAPSHOTTED, (H1,), None, (H3,), True),
        (AcquisitionState.ACQUIRED_UNSNAPSHOTTED, (H1,), H2, (H3,), False),
        (AcquisitionState.ACQUIRED_UNSNAPSHOTTED, (H1,), None, (), False),
        (AcquisitionState.SNAPSHOT_BOUND, (H1,), H2, (), True),
        (AcquisitionState.SNAPSHOT_BOUND, (), H2, (), False),
    ],
)
def test_qualification_target_encodes_only_real_acquisition_state(
    state: AcquisitionState,
    receipts: tuple[str, ...],
    snapshot: str | None,
    failures: tuple[str, ...],
    valid: bool,
) -> None:
    values = {
        "profile_hash": H6,
        "acquisition_state": state,
        "receipt_hashes": receipts,
        "snapshot_hash": snapshot,
        "failure_evidence_hashes": failures,
    }
    if valid:
        assert QualificationTargetV1.model_validate(values).acquisition_state is state
    else:
        with pytest.raises(ValidationError):
            QualificationTargetV1.model_validate(values)


def test_not_reached_dimension_cannot_claim_status_evidence_or_admission() -> None:
    result = dimension_result(
        QualificationDimension.OFFLINE_REPLAY,
        status=QualificationStatus.FAIL,
        reachability=ExecutionReachability.NOT_REACHED,
    )
    assert result.status is QualificationStatus.UNKNOWN

    for update in (
        {"status": QualificationStatus.PASS},
        {"evidence_hashes": (H1,)},
        {"admitted_purpose": True},
    ):
        with pytest.raises(ValidationError):
            result.model_copy(update=update)


def test_reached_partial_dimension_may_admit_only_its_explicit_limited_purpose() -> (
    None
):
    result = DimensionQualificationResultV1(
        dimension=QualificationDimension.COVERAGE_OMISSION,
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        status=QualificationStatus.PARTIAL,
        reachability=ExecutionReachability.REACHED,
        evidence_hashes=(H1,),
        tested_golden_case_ids=("G04",),
        admitted_purpose=True,
        limitations=("retrospective use only",),
        adjudication_policy_hash=H6,
    )

    assert result.admitted_purpose


def test_pre_replay_report_has_exactly_11_non_replay_dimensions() -> None:
    value = profile()
    results = tuple(
        dimension_result(item) for item in reversed(tuple(QualificationDimension)[:-1])
    )
    report = PreReplayQualificationReportV1(
        purpose=value.purpose,
        target=target(qualification_profile_hash(value)),
        results=results,
    )

    assert (
        tuple(item.dimension for item in report.results)
        == tuple(QualificationDimension)[:-1]
    )
    with pytest.raises(ValidationError):
        report.model_copy(
            update={
                "results": (*report.results[:-1], report.results[-2]),
            }
        )
    with pytest.raises(ValidationError):
        report.model_copy(
            update={
                "results": (
                    *report.results[:-1],
                    dimension_result(
                        report.results[-1].dimension,
                        status=QualificationStatus.UNKNOWN,
                        reachability=ExecutionReachability.NOT_REACHED,
                    ),
                )
            }
        )


def test_final_report_has_all_12_dimensions_and_replay_binding() -> None:
    value = profile()
    results = tuple(dimension_result(item) for item in QualificationDimension)
    report = PurposeQualificationReportV1(
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=value.purpose,
        target=target(qualification_profile_hash(value)),
        results=tuple(reversed(results)),
        pre_replay_report_hash=H3,
    )

    assert tuple(item.dimension for item in report.results) == tuple(
        QualificationDimension
    )
    assert (
        PurposeQualificationReportV1.model_validate_json(report.model_dump_json())
        == report
    )
    with pytest.raises(ValidationError):
        report.model_copy(update={"pre_replay_report_hash": None})


def test_reached_offline_replay_requires_all_prior_dimensions_reached() -> None:
    value = profile()
    results = tuple(dimension_result(item) for item in QualificationDimension)
    not_reached = dimension_result(
        QualificationDimension.SECURITY_LISTING_IDENTITY,
        status=QualificationStatus.UNKNOWN,
        reachability=ExecutionReachability.NOT_REACHED,
    )

    with pytest.raises(ValidationError):
        PurposeQualificationReportV1(
            report_id=uuid7(),
            report_version="1",
            reported_at=NOW,
            purpose=value.purpose,
            target=target(qualification_profile_hash(value)),
            results=(not_reached, *results[1:]),
            pre_replay_report_hash=H3,
        )


def test_one_purpose_result_cannot_be_used_in_the_other_purpose_report() -> None:
    value = profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    results = tuple(
        dimension_result(item, ConsumerPurpose.HISTORICAL_DECISION_INPUT)
        for item in tuple(QualificationDimension)[:-1]
    )

    with pytest.raises(ValidationError):
        PreReplayQualificationReportV1(
            purpose=value.purpose,
            target=target(qualification_profile_hash(value)),
            results=results,
        )


def test_external_dependency_terminal_evidence_and_pre_profile_abandonment() -> None:
    pending = ExternalDependencyResolutionV1(
        dependency_kind="provider-contract",
        responsible_party="provider",
        status=ExternalDependencyStatus.PENDING,
        evidence_hashes=(H1,),
        decision_time=None,
        limitations=("awaiting response",),
    )
    terminal = pending.model_copy(
        update={
            "status": ExternalDependencyStatus.INQUIRY_EXHAUSTED,
            "decision_time": NOW,
        }
    )

    with pytest.raises(ValidationError):
        pending.model_copy(update={"status": ExternalDependencyStatus.UNAVAILABLE})
    with pytest.raises(ValidationError):
        PreProfileAttemptRecordV1(
            attempt_id=uuid7(),
            attempt_version="1",
            attempted_candidate_ids=("candidate-1",),
            external_dependencies=(pending,),
            reasons=("provider did not resolve the contract",),
        )
    attempt = PreProfileAttemptRecordV1(
        attempt_id=uuid7(),
        attempt_version="1",
        attempted_candidate_ids=("candidate-1",),
        external_dependencies=(terminal,),
        reasons=("provider did not resolve the contract",),
    )
    assert attempt.outcome is PreProfileAttemptStatus.ABANDONED_PRE_PROFILE


def test_task2_rejects_direct_terminal_purpose_state_construction() -> None:
    value = profile()

    for stage in (
        PilotStage.COMPLETED_POSITIVE,
        PilotStage.COMPLETED_NEGATIVE,
    ):
        with pytest.raises(ValidationError):
            PurposeStageStateV1(
                purpose=value.purpose,
                profile_hash=qualification_profile_hash(value),
                stage=stage,
                reached_stage_artifact_hashes=(H1,),
                terminal_blocker=(
                    QualificationDimension.LICENSING_RETENTION
                    if stage is PilotStage.COMPLETED_NEGATIVE
                    else None
                ),
            )


def test_task2_rejects_direct_positive_completion_record_construction() -> None:
    decision = profile()
    audit = profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profiles = (decision, audit)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=profiles
    )
    reports = cast(
        tuple[PurposeQualificationReportV1, PurposeQualificationReportV1],
        tuple(
            PurposeQualificationReportV1(
                report_id=uuid7(),
                report_version="1",
                reported_at=NOW,
                purpose=item.purpose,
                target=target(qualification_profile_hash(item)),
                results=tuple(
                    dimension_result(
                        dimension,
                        item.purpose,
                    )
                    for dimension in QualificationDimension
                ),
                pre_replay_report_hash=H3,
            )
            for item in profiles
        ),
    )
    states = cast(
        tuple[PurposeStageStateV1, PurposeStageStateV1],
        tuple(
            PurposeStageStateV1.model_construct(
                purpose=item.purpose,
                profile_hash=qualification_profile_hash(item),
                stage=PilotStage.COMPLETED_POSITIVE,
                reached_stage_artifact_hashes=(H1,),
                terminal_blocker=None,
            )
            for item in profiles
        ),
    )
    common = {
        "completion_id": uuid7(),
        "completion_version": "1",
        "completed_at": NOW,
        "profile_set_hash": content_hash(profile_set),
        "purpose_states": states,
        "shared_artifact_hashes": (H1,),
        "blocking_dimensions": (),
        "blocking_evidence_hashes": (),
        "purpose_reports": reports,
        "completion_kind": M1eCompletionKind.COMPLETED_POSITIVE,
    }

    with pytest.raises(ValidationError):
        M1eCompletionRecordV1.model_validate(
            {
                **common,
                "content_dispositions": (),
                "external_dependencies": (),
            }
        )
