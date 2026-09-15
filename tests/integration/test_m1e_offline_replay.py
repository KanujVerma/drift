"""Integration tests for M1e offline replay, attestations, and pilot finalization."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.common import FrozenModel
from drift.domain.qualification import (
    AcquisitionState,
    ConsumerPurpose,
    DimensionQualificationResultV1,
    ExecutionReachability,
    InfrastructureScopeV1,
    M1eCompletionKind,
    M1eCompletionRecordV1,
    M1ePilotStateV1,
    PilotStage,
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
from drift.domain.qualification_replay import (
    AcquisitionNegativeEvidence,
    ExpectedOutputV1,
    FreshRestoreAttestationV1,
    NegativePurposeTerminalBundle,
    OfflineControlStatus,
    OfflineProbeResultV1,
    PositivePurposeTerminalBundle,
    ProfileExternalNegativeEvidence,
    QualificationNegativeEvidence,
    ReplayAttemptEnvelopeV1,
    ReplayAuthorizationNegativeEvidence,
    ReplayComparisonPolicyV1,
    ReplayExecutionRecordV1,
    ReplayExecutionStatus,
    ReplayNegativeEvidence,
    ReplayOutcome,
    ReplayResultV1,
    RightsNegativeEvidence,
    SnapshotNegativeEvidence,
    SystemOfflineAttestationV1,
    build_qualified_source_handoff,
    compare_replay_outputs,
    derive_qualified_reference_inventory,
    finalize_pilot,
    finalize_qualification_report,
    finalize_replay_result,
    require_qualified_purpose,
)
from drift.qualification.replay import (
    execute_replay,
    verify_fresh_restore_attestation,
    verify_system_offline_attestation,
)

H = tuple(f"{index:064x}" for index in range(1, 35))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


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
            classification_evidence_hashes=("0" * 64,),
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


def test_replay_outcome_and_offline_control_status_enums() -> None:
    # Closed set of 7 ReplayOutcome members
    assert len(ReplayOutcome) == 7
    expected_outcomes = {
        "MATCH",
        "SOURCE_BYTES_UNAVAILABLE",
        "USE_DENIED_BY_RIGHTS",
        "ENVIRONMENT_ARTIFACT_UNAVAILABLE",
        "PLATFORM_INCOMPATIBLE",
        "SEMANTIC_IDENTITY_MISMATCH",
        "OUTPUT_HASH_MISMATCH",
    }
    assert {o.value for o in ReplayOutcome} == expected_outcomes

    # Closed set of 3 OfflineControlStatus members
    assert len(OfflineControlStatus) == 3
    assert {s.value for s in OfflineControlStatus} == {
        "enforced",
        "not_enforced",
        "unknown",
    }


def test_compare_replay_outputs_exactness() -> None:
    policy = ReplayComparisonPolicyV1(
        schema_version="1",
        compared_artifact_roles=("identity_assignment", "universe_membership"),
        replay_envelope_exclusions=("temporary_paths", "diagnostics"),
        policy_hash=H[0],
    )

    expected = (
        ExpectedOutputV1(role="identity_assignment", content_hash=H[1], byte_size=100),
        ExpectedOutputV1(role="universe_membership", content_hash=H[2], byte_size=200),
    )
    actual_match = (
        ExpectedOutputV1(role="identity_assignment", content_hash=H[1], byte_size=100),
        ExpectedOutputV1(role="universe_membership", content_hash=H[2], byte_size=200),
    )
    assert compare_replay_outputs(expected, actual_match, policy) == ReplayOutcome.MATCH

    actual_mismatch = (
        ExpectedOutputV1(role="identity_assignment", content_hash=H[3], byte_size=100),
        ExpectedOutputV1(role="universe_membership", content_hash=H[2], byte_size=200),
    )
    assert (
        compare_replay_outputs(expected, actual_mismatch, policy)
        == ReplayOutcome.OUTPUT_HASH_MISMATCH
    )


def test_finalize_replay_result_rule_hierarchy() -> None:
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=NOW,
        end_time=NOW + timedelta(seconds=10),
        process_ids=(12345,),
        temporary_paths=("/tmp/drift_test",),
        cache_layout="isolated",
        diagnostics=("clean exit",),
        host_observations=("darwin_arm64",),
    )

    policy = ReplayComparisonPolicyV1(
        schema_version="1",
        compared_artifact_roles=("identity_assignment",),
        replay_envelope_exclusions=(),
        policy_hash=H[0],
    )

    expected = (
        ExpectedOutputV1(role="identity_assignment", content_hash=H[1], byte_size=100),
    )
    actual = (
        ExpectedOutputV1(role="identity_assignment", content_hash=H[1], byte_size=100),
    )

    # 1. Preflight denial returns USE_DENIED_BY_RIGHTS without post-run attestations
    exec_denied = ReplayExecutionRecordV1(
        schema_version="1",
        request_hash=H[2],
        authorization_hash=H[3],
        attempt_envelope=attempt,
        verified_inputs=(),
        status=ReplayExecutionStatus.NOT_STARTED,
        preflight_outcome=ReplayOutcome.USE_DENIED_BY_RIGHTS,
        actual_outputs=(),
        process_tree_identity="none",
        target_identity="none",
        start_time=NOW,
        end_time=NOW,
        raw_outcome_evidence_hash=H[4],
        execution_record_hash=H[5],
    )
    res_denied = finalize_replay_result(
        execution=exec_denied,
        offline=None,
        fresh=None,
        expected=expected,
        actual=(),
        policy=policy,
        replay_implementation_hash=H[6],
    )
    assert res_denied.outcome == ReplayOutcome.USE_DENIED_BY_RIGHTS

    # 2. Executed run with missing offline attestation returns UNAVAILABLE
    exec_ok = ReplayExecutionRecordV1(
        schema_version="1",
        request_hash=H[2],
        authorization_hash=H[3],
        attempt_envelope=attempt,
        verified_inputs=(H[7],),
        status=ReplayExecutionStatus.EXECUTED,
        preflight_outcome=None,
        actual_outputs=(H[1],),
        process_tree_identity="proc-12345",
        target_identity="target-1",
        start_time=NOW,
        end_time=NOW + timedelta(seconds=10),
        raw_outcome_evidence_hash=H[4],
        execution_record_hash=H[5],
    )
    res_no_offline = finalize_replay_result(
        execution=exec_ok,
        offline=None,
        fresh=None,
        expected=expected,
        actual=actual,
        policy=policy,
        replay_implementation_hash=H[6],
    )
    assert res_no_offline.outcome == ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE

    # 3. Offline control NOT_ENFORCED returns ENVIRONMENT_ARTIFACT_UNAVAILABLE
    offline_unenforced = SystemOfflineAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[2],
        attempt_id=attempt.attempt_id,
        vm_identity="vm-1",
        process_tree_identity="proc-12345",
        enforced_mechanism="pf",
        control_interval_start=NOW,
        control_interval_end=NOW + timedelta(seconds=10),
        configuration_evidence_hash=H[8],
        probe_results=(),
        status=OfflineControlStatus.NOT_ENFORCED,
        attestor_id="system_attestor",
        policy_hash=H[9],
        attestation_hash=H[10],
    )
    fresh_attestation = FreshRestoreAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[2],
        attempt_id=attempt.attempt_id,
        target_identity="target-1",
        base_state_evidence_hash=H[11],
        absence_of_inherited_state=True,
        creation_evidence_hash=H[12],
        process_use_evidence_hash=H[13],
        disposal_evidence_hash=H[14],
        attestor_id="system_attestor",
        policy_hash=H[9],
        attestation_hash=H[15],
    )
    res_unenforced = finalize_replay_result(
        execution=exec_ok,
        offline=offline_unenforced,
        fresh=fresh_attestation,
        expected=expected,
        actual=actual,
        policy=policy,
        replay_implementation_hash=H[6],
    )
    assert res_unenforced.outcome == ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE

    # 4. Fully enforced offline, fresh target, matching outputs -> MATCH
    probe = OfflineProbeResultV1(
        probe_name="dns_lookup",
        destination_class="public_dns",
        attempted_at=NOW,
        status="blocked",
        exit_code=1,
        log_evidence_hash=H[8],
    )
    offline_enforced = offline_unenforced.model_copy(
        update={
            "status": OfflineControlStatus.ENFORCED,
            "probe_results": (probe,),
        }
    )
    res_match = finalize_replay_result(
        execution=exec_ok,
        offline=offline_enforced,
        fresh=fresh_attestation,
        expected=expected,
        actual=actual,
        policy=policy,
        replay_implementation_hash=H[6],
    )
    assert res_match.outcome == ReplayOutcome.MATCH


def test_finalize_qualification_report_derives_offline_replay_dimension() -> None:
    # Build pre-replay report with 11 dimensions
    from drift.domain.qualification import (
        _PRE_REPLAY_DIMENSIONS,
        AcquisitionState,
        QualificationTargetV1,
    )

    target = QualificationTargetV1(
        profile_hash=H[0],
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H[1],),
        snapshot_hash=H[4],
        failure_evidence_hashes=(),
    )

    results_11 = tuple(
        DimensionQualificationResultV1(
            schema_version="1",
            dimension=dim,
            purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
            status=QualificationStatus.PASS,
            reachability=ExecutionReachability.REACHED,
            evidence_hashes=(H[0],),
            tested_golden_case_ids=("G01",),
            admitted_purpose=True,
            limitations=(),
            adjudication_policy_hash=H[5],
        )
        for dim in _PRE_REPLAY_DIMENSIONS
    )
    pre_replay = PreReplayQualificationReportV1(
        schema_version="1",
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=target,
        results=results_11,
    )

    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=NOW,
        end_time=NOW + timedelta(seconds=10),
        process_ids=(1,),
        temporary_paths=(),
        cache_layout="isolated",
        diagnostics=(),
        host_observations=(),
    )
    replay_result = ReplayResultV1(
        schema_version="1",
        result_id=uuid7(),
        evaluated_at=NOW,
        request_hash=H[6],
        authorization_hash=H[7],
        outcome=ReplayOutcome.MATCH,
        verified_input_hashes=(H[8],),
        actual_output_hashes=(H[9],),
        offline_attestation_hash=H[10],
        fresh_attestation_hash=H[11],
        mismatch_classifications=(),
        limitations=(),
        attempt_envelope=attempt,
        replay_implementation_hash=H[12],
        policy_hash=H[13],
        result_hash=H[14],
    )

    # finalize_qualification_report derives the 12th dimension
    final_report = finalize_qualification_report(pre_replay, replay_result)
    assert len(final_report.results) == 12
    assert final_report.results[-1].dimension == QualificationDimension.OFFLINE_REPLAY
    assert final_report.results[-1].status == QualificationStatus.PASS
    assert final_report.pre_replay_report_hash is not None


def test_system_offline_attestation_rejects_package_manager_flags() -> None:
    probe = OfflineProbeResultV1(
        probe_name="dns_lookup",
        destination_class="public_dns",
        attempted_at=NOW,
        status="blocked",
        exit_code=1,
        log_evidence_hash=H[8],
    )
    with pytest.raises(ValueError, match="package-manager flags"):
        SystemOfflineAttestationV1(
            schema_version="1",
            request_hash=H[0],
            attempt_id=uuid7(),
            vm_identity="vm-1",
            process_tree_identity="proc-1",
            enforced_mechanism="uv --offline",
            control_interval_start=NOW,
            control_interval_end=NOW + timedelta(seconds=10),
            configuration_evidence_hash=H[1],
            probe_results=(probe,),
            status=OfflineControlStatus.ENFORCED,
            attestor_id="attestor",
            policy_hash=H[2],
            attestation_hash=H[3],
        )


def test_fresh_restore_attestation_rejects_inherited_state() -> None:
    with pytest.raises(ValueError, match="absence of inherited state"):
        FreshRestoreAttestationV1(
            schema_version="1",
            request_hash=H[0],
            attempt_id=uuid7(),
            target_identity="target-1",
            base_state_evidence_hash=H[1],
            absence_of_inherited_state=False,
            creation_evidence_hash=H[2],
            process_use_evidence_hash=H[3],
            disposal_evidence_hash=H[4],
            attestor_id="attestor",
            policy_hash=H[5],
            attestation_hash=H[6],
        )


def test_finalize_replay_result_rejects_mismatched_or_predated_attestations() -> None:
    attempt_id = uuid7()
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=attempt_id,
        start_time=NOW,
        end_time=NOW + timedelta(seconds=10),
        process_ids=(1,),
        temporary_paths=(),
        cache_layout="isolated",
        diagnostics=(),
        host_observations=(),
    )
    exec_ok = ReplayExecutionRecordV1(
        schema_version="1",
        request_hash=H[0],
        authorization_hash=H[1],
        attempt_envelope=attempt,
        verified_inputs=(H[2],),
        status=ReplayExecutionStatus.EXECUTED,
        preflight_outcome=None,
        actual_outputs=(H[3],),
        process_tree_identity="proc-1",
        target_identity="target-1",
        start_time=NOW,
        end_time=NOW + timedelta(seconds=10),
        raw_outcome_evidence_hash=H[4],
        execution_record_hash=H[5],
    )
    policy = ReplayComparisonPolicyV1(
        schema_version="1",
        compared_artifact_roles=(),
        policy_hash=H[6],
    )
    probe = OfflineProbeResultV1(
        probe_name="dns",
        destination_class="public_dns",
        attempted_at=NOW,
        status="blocked",
        exit_code=1,
        log_evidence_hash=H[7],
    )
    offline_diff_attempt = SystemOfflineAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[0],
        attempt_id=uuid7(),
        vm_identity="vm-1",
        process_tree_identity="proc-1",
        enforced_mechanism="pf",
        control_interval_start=NOW,
        control_interval_end=NOW + timedelta(seconds=10),
        configuration_evidence_hash=H[8],
        probe_results=(probe,),
        status=OfflineControlStatus.ENFORCED,
        attestor_id="attestor",
        policy_hash=H[9],
        attestation_hash=H[10],
    )
    fresh = FreshRestoreAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[0],
        attempt_id=attempt_id,
        target_identity="target-1",
        base_state_evidence_hash=H[11],
        absence_of_inherited_state=True,
        creation_evidence_hash=H[12],
        process_use_evidence_hash=H[13],
        disposal_evidence_hash=H[14],
        attestor_id="attestor",
        policy_hash=H[9],
        attestation_hash=H[15],
    )
    with pytest.raises(ValueError, match="does not match execution attempt_id"):
        finalize_replay_result(
            execution=exec_ok,
            offline=offline_diff_attempt,
            fresh=fresh,
            expected=(),
            actual=(),
            policy=policy,
            replay_implementation_hash=H[16],
        )

    offline_predated = offline_diff_attempt.model_copy(
        update={
            "attempt_id": attempt_id,
            "control_interval_start": NOW - timedelta(seconds=20),
            "control_interval_end": NOW - timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="cannot predate execution attempt"):
        finalize_replay_result(
            execution=exec_ok,
            offline=offline_predated,
            fresh=fresh,
            expected=(),
            actual=(),
            policy=policy,
            replay_implementation_hash=H[16],
        )


def test_finalize_pilot_rejects_non_match_in_positive_bundle() -> None:
    p_dec = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)

    target = QualificationTargetV1(
        profile_hash=H[0],
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H[1],),
        snapshot_hash=H[2],
        failure_evidence_hashes=(),
    )
    rep = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=target,
        results=(),
        pre_replay_report_hash=H[3],
    )
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=NOW,
        end_time=NOW,
        process_ids=(1,),
        temporary_paths=(),
        cache_layout="isolated",
        diagnostics=(),
        host_observations=(),
    )
    replay_mismatch = ReplayResultV1(
        schema_version="1",
        result_id=uuid7(),
        evaluated_at=NOW,
        request_hash=H[4],
        authorization_hash=H[5],
        outcome=ReplayOutcome.OUTPUT_HASH_MISMATCH,
        verified_input_hashes=(),
        actual_output_hashes=(),
        attempt_envelope=attempt,
        replay_implementation_hash=H[6],
        policy_hash=H[7],
        result_hash=H[8],
    )
    # A positive bundle containing non-MATCH replay must be rejected by finalize_pilot
    bundle_fake_pos = PositivePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        pre_replay_report=None,  # type: ignore
        final_report=rep,
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=None,  # type: ignore
        execution=None,  # type: ignore
        offline=None,  # type: ignore
        fresh=None,  # type: ignore
        replay=replay_mismatch,
        qualification_context=None,  # type: ignore
        artifacts={},
        dispositions=(),
    )
    pilot_state = M1ePilotStateV1(
        profile_set_hash=H[9],
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=H[0],
                stage=PilotStage.SNAPSHOT_FROZEN,
                reached_stage_artifact_hashes=(H[4],),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=H[1],
                stage=PilotStage.SNAPSHOT_FROZEN,
                reached_stage_artifact_hashes=(H[4],),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )
    p_aud = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    bundle_fake_pos_aud = PositivePurposeTerminalBundle(
        profile=p_aud,
        target=target,
        pre_replay_report=None,  # type: ignore
        final_report=rep,
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=None,  # type: ignore
        execution=None,  # type: ignore
        offline=None,  # type: ignore
        fresh=None,  # type: ignore
        replay=replay_mismatch,
        qualification_context=None,  # type: ignore
        artifacts={},
        dispositions=(),
    )
    with pytest.raises(
        ValueError, match="positive terminal bundle requires ReplayOutcome.MATCH"
    ):
        finalize_pilot(pilot_state, (bundle_fake_pos, bundle_fake_pos_aud))


def test_negative_stage_evidence_table_verification() -> None:
    p_dec = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    p_aud = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)

    target = QualificationTargetV1(
        profile_hash=H[0],
        acquisition_state=AcquisitionState.NOT_ACQUIRED,
        receipt_hashes=(),
        snapshot_hash=None,
        failure_evidence_hashes=(),
    )
    rep_dec = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=target,
        results=(),
        pre_replay_report_hash=H[1],
    )
    rep_aud = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        target=target,
        results=(),
        pre_replay_report_hash=H[2],
    )
    pilot_state = M1ePilotStateV1(
        profile_set_hash=H[3],
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=H[0],
                stage=PilotStage.PROFILE_FROZEN,
                reached_stage_artifact_hashes=(H[4],),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=H[1],
                stage=PilotStage.PROFILE_FROZEN,
                reached_stage_artifact_hashes=(H[4],),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )

    # 1. RightsNegativeEvidence
    rights_ev = RightsNegativeEvidence(
        assessment=None,  # type: ignore
        evidence=None,  # type: ignore
    )
    neg_rights = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=rights_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    neg_rights_aud = NegativePurposeTerminalBundle(
        profile=p_aud,
        target=target,
        final_report=rep_aud,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=rights_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    neg_rights_invalid = NegativePurposeTerminalBundle(
        profile=p_aud,
        target=target,
        final_report=rep_aud,
        blocker_dimension=QualificationDimension.OFFLINE_REPLAY,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=rights_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="RightsNegativeEvidence requires LICENSING_RETENTION"
    ):
        finalize_pilot(pilot_state, (neg_rights, neg_rights_invalid))

    # 2. ProfileExternalNegativeEvidence
    neg_profile_ext_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=ProfileExternalNegativeEvidence(
            profile=p_dec,
            external_dependency=None,  # type: ignore
            evidence={},
        ),
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="ProfileExternalNegativeEvidence requires external_dependency"
    ):
        finalize_pilot(pilot_state, (neg_profile_ext_invalid, neg_rights_aud))

    # 3. AcquisitionNegativeEvidence
    acq_ev = AcquisitionNegativeEvidence(
        acquisition_authority=None,  # type: ignore
        plan=None,  # type: ignore
        receipts=(),
        reconciliations=(),
        artifacts={},
    )
    neg_acq_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=acq_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="AcquisitionNegativeEvidence requires ACQUISITION_SNAPSHOT"
    ):
        finalize_pilot(pilot_state, (neg_acq_invalid, neg_rights_aud))

    # 4. SnapshotNegativeEvidence
    snap_ev = SnapshotNegativeEvidence(
        acquisition_authority=None,  # type: ignore
        receipts=(),
        validation_context=None,  # type: ignore
        validated_candidate=None,
        consistency=None,
        artifacts={},
    )
    neg_snap_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=snap_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="SnapshotNegativeEvidence requires ACQUISITION_SNAPSHOT"
    ):
        finalize_pilot(pilot_state, (neg_snap_invalid, neg_rights_aud))

    # 5. QualificationNegativeEvidence
    qual_ev = QualificationNegativeEvidence(
        context=None,  # type: ignore
        pre_replay_report=None,
        golden_case_results=(),
    )
    neg_qual_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.OFFLINE_REPLAY,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=qual_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError,
        match="QualificationNegativeEvidence requires a pre-replay blocker dimension",
    ):
        finalize_pilot(pilot_state, (neg_qual_invalid, neg_rights_aud))

    # 6. ReplayAuthorizationNegativeEvidence
    replay_auth_ev = ReplayAuthorizationNegativeEvidence(
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        pre_replay_report=None,  # type: ignore
        qualification_context=None,  # type: ignore
        replay_authority=None,  # type: ignore
        artifacts={},
    )
    neg_replay_auth_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=replay_auth_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="ReplayAuthorizationNegativeEvidence requires OFFLINE_REPLAY"
    ):
        finalize_pilot(pilot_state, (neg_replay_auth_invalid, neg_rights_aud))

    # 7. ReplayNegativeEvidence
    replay_ev = ReplayNegativeEvidence(
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=None,  # type: ignore
        execution=None,  # type: ignore
        qualification_context=None,  # type: ignore
        pre_replay_report=None,  # type: ignore
        offline=None,
        fresh=None,
        replay=None,  # type: ignore
        artifacts={},
    )
    neg_replay_invalid = NegativePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        final_report=rep_dec,
        blocker_dimension=QualificationDimension.ACQUISITION_SNAPSHOT,
        blocker_evidence={
            H[2]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[2])
        },
        stage_evidence=replay_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    with pytest.raises(
        ValueError, match="ReplayNegativeEvidence requires OFFLINE_REPLAY"
    ):
        finalize_pilot(pilot_state, (neg_replay_invalid, neg_rights_aud))


def test_finalize_pilot_successful_positive_and_negative_completions() -> None:
    p_dec = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    p_aud = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)

    target_dec = QualificationTargetV1(
        profile_hash=qualification_profile_hash(p_dec),
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H[0],),
        snapshot_hash=H[1],
        failure_evidence_hashes=(),
    )
    target_aud = QualificationTargetV1(
        profile_hash=qualification_profile_hash(p_aud),
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H[0],),
        snapshot_hash=H[1],
        failure_evidence_hashes=(),
    )

    rep_dec = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=target_dec,
        results=(),
        pre_replay_report_hash=H[2],
    )
    rep_aud = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        target=target_aud,
        results=(),
        pre_replay_report_hash=H[2],
    )

    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=NOW,
        end_time=NOW,
        process_ids=(1,),
        temporary_paths=(),
        cache_layout="isolated",
        diagnostics=(),
        host_observations=(),
    )
    replay_match = ReplayResultV1(
        schema_version="1",
        result_id=uuid7(),
        evaluated_at=NOW,
        request_hash=H[3],
        authorization_hash=H[4],
        outcome=ReplayOutcome.MATCH,
        verified_input_hashes=(),
        actual_output_hashes=(),
        attempt_envelope=attempt,
        replay_implementation_hash=H[5],
        policy_hash=H[6],
        result_hash=H[7],
    )

    pos_bundle_dec = PositivePurposeTerminalBundle(
        profile=p_dec,
        target=target_dec,
        pre_replay_report=None,  # type: ignore
        final_report=rep_dec,
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=None,  # type: ignore
        execution=None,  # type: ignore
        offline=None,  # type: ignore
        fresh=None,  # type: ignore
        replay=replay_match,
        qualification_context=None,  # type: ignore
        artifacts={},
        dispositions=(),
    )
    pos_bundle_aud = PositivePurposeTerminalBundle(
        profile=p_aud,
        target=target_aud,
        pre_replay_report=None,  # type: ignore
        final_report=rep_aud,
        snapshot=None,  # type: ignore
        closure=None,  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=None,  # type: ignore
        execution=None,  # type: ignore
        offline=None,  # type: ignore
        fresh=None,  # type: ignore
        replay=replay_match,
        qualification_context=None,  # type: ignore
        artifacts={},
        dispositions=(),
    )

    pilot_state = M1ePilotStateV1(
        profile_set_hash=H[8],
        purpose_states=(
            PurposeStageStateV1(
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                profile_hash=qualification_profile_hash(p_dec),
                stage=PilotStage.SNAPSHOT_FROZEN,
                reached_stage_artifact_hashes=(H[9],),
                terminal_blocker=None,
            ),
            PurposeStageStateV1(
                purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
                profile_hash=qualification_profile_hash(p_aud),
                stage=PilotStage.SNAPSHOT_FROZEN,
                reached_stage_artifact_hashes=(H[9],),
                terminal_blocker=None,
            ),
        ),
        shared_artifact_hashes=(),
    )

    # Both positive -> COMPLETED_POSITIVE
    comp_pos = finalize_pilot(pilot_state, (pos_bundle_dec, pos_bundle_aud))
    assert comp_pos.completion_kind == M1eCompletionKind.COMPLETED_POSITIVE
    assert comp_pos.blocking_dimensions == ()
    assert comp_pos.purpose_states[0].stage == PilotStage.COMPLETED_POSITIVE
    assert comp_pos.purpose_states[1].stage == PilotStage.COMPLETED_POSITIVE
    assert comp_pos.purpose_states[0].terminal_blocker is None
    assert comp_pos.purpose_states[1].terminal_blocker is None

    # One positive, one negative -> COMPLETED_NEGATIVE
    rights_ev = RightsNegativeEvidence(assessment=None, evidence=None)  # type: ignore
    neg_bundle_aud = NegativePurposeTerminalBundle(
        profile=p_aud,
        target=target_aud,
        final_report=rep_aud,
        blocker_dimension=QualificationDimension.LICENSING_RETENTION,
        blocker_evidence={
            H[10]: VerifiedArtifactBytes(data=b"ev", byte_size=2, content_hash=H[10])
        },
        stage_evidence=rights_ev,
        dispositions=(),
        disposition_evidence={},
        external_dependency=None,
    )
    comp_mixed = finalize_pilot(pilot_state, (pos_bundle_dec, neg_bundle_aud))
    assert comp_mixed.completion_kind == M1eCompletionKind.COMPLETED_NEGATIVE
    assert comp_mixed.blocking_dimensions == (
        QualificationDimension.LICENSING_RETENTION,
    )
    assert comp_mixed.purpose_states[0].stage == PilotStage.COMPLETED_POSITIVE
    assert comp_mixed.purpose_states[1].stage == PilotStage.COMPLETED_NEGATIVE
    assert (
        comp_mixed.purpose_states[1].terminal_blocker
        == QualificationDimension.LICENSING_RETENTION
    )


def test_derive_qualified_reference_inventory_and_handoff() -> None:
    p_dec = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)

    target = QualificationTargetV1(
        profile_hash=H[0],
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=(H[1],),
        snapshot_hash=H[2],
        failure_evidence_hashes=(),
    )
    rep = PurposeQualificationReportV1.model_construct(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=NOW,
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        target=target,
        results=(
            DimensionQualificationResultV1(
                schema_version="1",
                dimension=QualificationDimension.OFFLINE_REPLAY,
                purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
                status=QualificationStatus.PASS,
                reachability=ExecutionReachability.REACHED,
                evidence_hashes=(H[3],),
                tested_golden_case_ids=(),
                admitted_purpose=True,
                limitations=(),
                adjudication_policy_hash=H[4],
            ),
        ),
        pre_replay_report_hash=H[5],
    )
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=NOW,
        end_time=NOW,
        process_ids=(1,),
        temporary_paths=(),
        cache_layout="isolated",
        diagnostics=(),
        host_observations=(),
    )
    replay_match = ReplayResultV1(
        schema_version="1",
        result_id=uuid7(),
        evaluated_at=NOW,
        request_hash=H[6],
        authorization_hash=H[7],
        outcome=ReplayOutcome.MATCH,
        verified_input_hashes=(H[8],),
        actual_output_hashes=(H[9],),
        attempt_envelope=attempt,
        replay_implementation_hash=H[10],
        policy_hash=H[11],
        result_hash=H[12],
    )

    class DummyAssessment(FrozenModel):
        assessment: str = H[13]

    class DummyDecision(FrozenModel):
        decision: str = H[14]

    class DummyReplayAuth:
        current_assessment = DummyAssessment()
        decision = DummyDecision()

    class DummySnapshot:
        snapshot_hash = H[2]
        replay_inputs = ()
        expected_outputs = ()

    class DummyClosure:
        closure_hash = H[15]

    bundle = PositivePurposeTerminalBundle(
        profile=p_dec,
        target=target,
        pre_replay_report=None,  # type: ignore
        final_report=rep,
        snapshot=DummySnapshot(),  # type: ignore
        closure=DummyClosure(),  # type: ignore
        request=None,  # type: ignore
        acquisition_authority=None,  # type: ignore
        replay_authority=DummyReplayAuth(),  # type: ignore
        execution=None,  # type: ignore
        offline=None,  # type: ignore
        fresh=None,  # type: ignore
        replay=replay_match,
        qualification_context=None,  # type: ignore
        artifacts={},
        dispositions=(),
    )

    refs = derive_qualified_reference_inventory(bundle)
    assert len(refs) == 6
    assert all(r.location.startswith("drift+sha256://") for r in refs)

    completion = M1eCompletionRecordV1.model_construct(
        schema_version="1",
        completion_id=uuid7(),
        completion_version="1",
        completed_at=NOW,
        profile_set_hash=H[16],
        purpose_states=(),
        shared_artifact_hashes=(),
        blocking_dimensions=(),
        blocking_evidence_hashes=(),
        purpose_reports=(),
        content_dispositions=(),
        external_dependencies=(),
        completion_kind=M1eCompletionKind.COMPLETED_POSITIVE,
    )
    handoff = build_qualified_source_handoff(
        completion, ConsumerPurpose.HISTORICAL_DECISION_INPUT, bundle
    )
    assert handoff.purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT
    assert handoff.snapshot_hash == H[2]
    assert handoff.environment_closure_hash == H[15]
    assert handoff.handoff_hash is not None

    purpose_report = require_qualified_purpose(
        completion, ConsumerPurpose.HISTORICAL_DECISION_INPUT, bundle
    )
    assert purpose_report == rep


def test_verify_system_offline_attestation_success_and_failures() -> None:
    probe = OfflineProbeResultV1(
        probe_name="dns_lookup",
        destination_class="public_dns",
        attempted_at=NOW,
        status="blocked",
        exit_code=1,
        log_evidence_hash=H[1],
    )
    attestation = SystemOfflineAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[0],
        attempt_id=uuid7(),
        vm_identity="vm-1",
        process_tree_identity="proc-1",
        enforced_mechanism="host_packet_filter",
        control_interval_start=NOW,
        control_interval_end=NOW + timedelta(seconds=10),
        configuration_evidence_hash=H[2],
        probe_results=(probe,),
        status=OfflineControlStatus.ENFORCED,
        attestor_id="attestor",
        policy_hash=H[3],
        attestation_hash=H[4],
    )
    # 1. Missing configuration evidence
    artifacts: dict[str, VerifiedArtifactBytes] = {
        H[1]: VerifiedArtifactBytes(data=b"probe_log", byte_size=9, content_hash=H[1]),
    }
    with pytest.raises(ValueError, match="configuration evidence"):
        verify_system_offline_attestation(attestation, artifacts)

    # 2. Missing probe log evidence
    artifacts_no_probe: dict[str, VerifiedArtifactBytes] = {
        H[2]: VerifiedArtifactBytes(data=b"config", byte_size=6, content_hash=H[2]),
    }
    with pytest.raises(ValueError, match="probe log evidence"):
        verify_system_offline_attestation(attestation, artifacts_no_probe)

    # 3. Success when all evidence present
    artifacts_full: dict[str, VerifiedArtifactBytes] = {
        H[1]: VerifiedArtifactBytes(data=b"probe_log", byte_size=9, content_hash=H[1]),
        H[2]: VerifiedArtifactBytes(data=b"config", byte_size=6, content_hash=H[2]),
    }
    verify_system_offline_attestation(attestation, artifacts_full)


def test_verify_fresh_restore_attestation_success_and_failures() -> None:
    attestation = FreshRestoreAttestationV1.model_construct(
        schema_version="1",
        request_hash=H[0],
        attempt_id=uuid7(),
        target_identity="target-1",
        base_state_evidence_hash=H[1],
        absence_of_inherited_state=True,
        creation_evidence_hash=H[2],
        process_use_evidence_hash=H[3],
        disposal_evidence_hash=H[4],
        attestor_id="attestor",
        policy_hash=H[5],
        attestation_hash=H[6],
    )
    artifacts: dict[str, VerifiedArtifactBytes] = {
        H[1]: VerifiedArtifactBytes(data=b"base", byte_size=4, content_hash=H[1]),
        H[2]: VerifiedArtifactBytes(data=b"creation", byte_size=8, content_hash=H[2]),
        H[3]: VerifiedArtifactBytes(data=b"use", byte_size=3, content_hash=H[3]),
        H[4]: VerifiedArtifactBytes(data=b"disposal", byte_size=8, content_hash=H[4]),
    }
    # Success
    verify_fresh_restore_attestation(attestation, artifacts)

    # Missing evidence hash raises ValueError
    for key in (H[1], H[2], H[3], H[4]):
        missing = dict(artifacts)
        del missing[key]
        with pytest.raises(ValueError, match="fresh restore evidence"):
            verify_fresh_restore_attestation(attestation, missing)


def test_execute_replay_preflight_branches() -> None:
    from drift.domain.rights import AuthorizationStatus, ReplayAuthorizationDecisionV1

    # Baseline mock objects
    dummy_decision = ReplayAuthorizationDecisionV1(
        schema_version="1",
        request_hash=H[0],
        new_assessment_hash=H[1],
        status=AuthorizationStatus.AUTHORIZED,
        evidence_hashes=(H[2],),
        reasons=("Authorized",),
        policy_hash=H[3],
        decision_id=uuid7(),
        decision_time=NOW,
    )
    denied_decision = ReplayAuthorizationDecisionV1(
        schema_version="1",
        request_hash=H[0],
        new_assessment_hash=H[1],
        status=AuthorizationStatus.DENIED,
        evidence_hashes=(H[2],),
        reasons=("Denied",),
        policy_hash=H[3],
        decision_id=uuid7(),
        decision_time=NOW,
    )

    class DummyReplayAuth:
        decision = dummy_decision

    class DummyPlatform:
        os_name = "macos"
        architecture = "arm64"

    class DummyClosure:
        closure_hash = H[10]
        platform = DummyPlatform()

    class DummySnapshot:
        snapshot_hash = H[11]

    class DummyRequest:
        request_hash = H[12]
        snapshot_hash = H[11]
        closure_hash = H[10]

    class DummyCandidate:
        records_by_role = {"prices": [{"id": 1}, {"id": 2}]}

    class DummyTarget:
        snapshot_hash = H[11]

    class DummyContext:
        targets = (DummyTarget(),)
        validated_candidate = DummyCandidate()

    # 1. Denied authorization
    class DeniedReplayAuth:
        decision = denied_decision

    rec_denied = execute_replay(
        request=DummyRequest(),  # type: ignore
        authorization=DeniedReplayAuth(),  # type: ignore
        snapshot=DummySnapshot(),  # type: ignore
        closure=DummyClosure(),  # type: ignore
        context=DummyContext(),  # type: ignore
    )
    assert rec_denied.status == ReplayExecutionStatus.NOT_STARTED
    assert rec_denied.preflight_outcome == ReplayOutcome.USE_DENIED_BY_RIGHTS

    # 2. Platform incompatible
    class IncompatiblePlatform:
        os_name = "linux"
        architecture = "arm64"

    class IncompatibleClosure:
        closure_hash = H[10]
        platform = IncompatiblePlatform()

    rec_platform = execute_replay(
        request=DummyRequest(),  # type: ignore
        authorization=DummyReplayAuth(),  # type: ignore
        snapshot=DummySnapshot(),  # type: ignore
        closure=IncompatibleClosure(),  # type: ignore
        context=DummyContext(),  # type: ignore
    )
    assert rec_platform.status == ReplayExecutionStatus.NOT_STARTED
    assert rec_platform.preflight_outcome == ReplayOutcome.PLATFORM_INCOMPATIBLE

    # 3. Semantic identity mismatch
    class MismatchedRequest:
        request_hash = H[12]
        snapshot_hash = H[30]  # Mismatch
        closure_hash = H[10]

    rec_mismatch = execute_replay(
        request=MismatchedRequest(),  # type: ignore
        authorization=DummyReplayAuth(),  # type: ignore
        snapshot=DummySnapshot(),  # type: ignore
        closure=DummyClosure(),  # type: ignore
        context=DummyContext(),  # type: ignore
    )
    assert rec_mismatch.status == ReplayExecutionStatus.NOT_STARTED
    assert rec_mismatch.preflight_outcome == ReplayOutcome.SEMANTIC_IDENTITY_MISMATCH

    # 4. Source bytes unavailable
    class EmptyContext:
        targets = ()
        validated_candidate = DummyCandidate()

    rec_no_src = execute_replay(
        request=DummyRequest(),  # type: ignore
        authorization=DummyReplayAuth(),  # type: ignore
        snapshot=DummySnapshot(),  # type: ignore
        closure=DummyClosure(),  # type: ignore
        context=EmptyContext(),  # type: ignore
    )
    assert rec_no_src.status == ReplayExecutionStatus.NOT_STARTED
    assert rec_no_src.preflight_outcome == ReplayOutcome.SOURCE_BYTES_UNAVAILABLE

    # 5. Executed successfully
    rec_ok = execute_replay(
        request=DummyRequest(),  # type: ignore
        authorization=DummyReplayAuth(),  # type: ignore
        snapshot=DummySnapshot(),  # type: ignore
        closure=DummyClosure(),  # type: ignore
        context=DummyContext(),  # type: ignore
    )
    assert rec_ok.status == ReplayExecutionStatus.EXECUTED
    assert rec_ok.preflight_outcome is None
    assert len(rec_ok.actual_outputs) == 2


def test_sanitize_child_environment() -> None:
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from scripts.replay_m1e_offline import sanitize_child_environment

    base = {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": "/tmp/custom",
        "SECRET_KEY": "supersecret",
        "AWS_KEY": "forbidden",
        "PROXY": "http://127.0.0.1:8080",
    }
    sanitized = sanitize_child_environment(base)
    assert "SECRET_KEY" not in sanitized
    assert "AWS_KEY" not in sanitized
    assert "PROXY" not in sanitized
    assert sanitized["PATH"] == "/usr/bin:/bin"
    assert sanitized["TMPDIR"] == "/tmp/custom"
    assert sanitized["PYTHONNOUSERSITE"] == "1"
    assert sanitized["PYTHONDONTWRITEBYTECODE"] == "1"
    assert sanitized["PYTHONHASHSEED"] == "0"
    assert sanitized["UV_OFFLINE"] == "1"
    assert sanitized["UV_NO_CONFIG"] == "1"
    assert sanitized["UV_PYTHON_DOWNLOADS"] == "never"


def test_capture_and_replay_cli_help() -> None:
    import subprocess
    import sys

    # Test capture_m1e_environment CLI help
    cp = subprocess.run(
        [sys.executable, "scripts/capture_m1e_environment.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "M1e macOS/arm64 Environment Closure Capture Boundary" in cp.stdout

    # Test replay_m1e_offline CLI help
    rp = subprocess.run(
        [sys.executable, "scripts/replay_m1e_offline.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "M1e macOS/arm64 Offline Replay Execution Boundary" in rp.stdout


def test_synthetic_clean_prefix_restore_integration(tmp_path: Path) -> None:
    from drift.domain.environment_closure import (
        EnvironmentArtifactKind,
        EnvironmentArtifactV1,
        EnvironmentClosureV1,
        PlatformIdentityV1,
        PythonRuntimeIdentityV1,
        SystemLibraryIdentityV1,
        environment_closure_hash,
    )
    from drift.qualification.environment import verify_environment_closure

    clean_root = tmp_path / "clean_restore_root"
    clean_root.mkdir()

    artifacts: dict[str, VerifiedArtifactBytes] = {}

    def _add_art(
        name: str, kind: EnvironmentArtifactKind, data: bytes
    ) -> tuple[EnvironmentArtifactV1, str]:
        import hashlib

        h = hashlib.sha256(data).hexdigest()
        vb = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=h)
        artifacts[h] = vb
        art = EnvironmentArtifactV1(
            artifact_kind=kind,
            artifact_reference=f"drift+sha256://{h}",
            content_hash=h,
            byte_size=len(data),
            media_type="application/octet-stream",
            platform_applicability="macos-arm64",
            origin=f"file:///{name}",
            rights_binding_hash=None,
        )
        return art, h

    art_git, h_git = _add_art(
        "git.tar", EnvironmentArtifactKind.GIT_ARCHIVE, b"git_tree"
    )
    art_sdist, h_sdist = _add_art(
        "drift.tar.gz", EnvironmentArtifactKind.DRIFT_SDIST, b"drift_sdist"
    )
    art_wheel, h_wheel = _add_art(
        "drift.whl", EnvironmentArtifactKind.DRIFT_WHEEL, b"drift_wheel"
    )
    art_meta, h_meta = _add_art(
        "pyproject.toml", EnvironmentArtifactKind.PROJECT_METADATA, b"project_metadata"
    )
    art_uvlock, h_uvlock = _add_art(
        "uv.lock", EnvironmentArtifactKind.UV_LOCK, b"uv_lock"
    )
    art_pylock, h_pylock = _add_art(
        "pylock.toml", EnvironmentArtifactKind.PYLOCK, b"pylock"
    )
    art_uv, h_uv = _add_art("uv", EnvironmentArtifactKind.UV_EXECUTABLE, b"uv_bin")
    art_py, h_py = _add_art(
        "python.tar.gz", EnvironmentArtifactKind.PYTHON_DISTRIBUTION, b"python_dist"
    )
    art_std, h_std = _add_art(
        "stdlib", EnvironmentArtifactKind.STANDARD_LIBRARY, b"stdlib"
    )
    art_sys, h_sys = _add_art(
        "syslib", EnvironmentArtifactKind.SYSTEM_LIBRARY, b"syslib"
    )
    art_tz, h_tz = _add_art("tzif", EnvironmentArtifactKind.TZIF, b"tzif")
    art_snap, h_snap = _add_art(
        "snapshot", EnvironmentArtifactKind.SOURCE_SNAPSHOT, b"snapshot"
    )
    art_rec, h_rec = _add_art(
        "recipe", EnvironmentArtifactKind.RESTORE_RECIPE, b"restore_recipe"
    )
    art_vuln, h_vuln = _add_art(
        "vuln", EnvironmentArtifactKind.VULNERABILITY_EVIDENCE, b"vuln"
    )

    python_runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=h_std,
        distribution_artifact_hash=h_py,
        native_library_links=("libSystem.B.dylib",),
    )
    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A335",
        kernel_compatibility="24.0.0",
        hardware_class="Apple M-series",
        declared_host_assumptions=("local_arm64",),
    )
    sys_lib = SystemLibraryIdentityV1(
        schema_version="1",
        library_name="libSystem.B.dylib",
        version_or_build="1.0.0",
        architecture="arm64",
        digest=h_sys,
        relevance="core system runtime",
    )

    env_artifacts = (
        art_git,
        art_sdist,
        art_wheel,
        art_meta,
        art_uvlock,
        art_pylock,
        art_uv,
        art_py,
        art_std,
        art_sys,
        art_tz,
        art_snap,
        art_rec,
        art_vuln,
    )
    closure_unhashed = EnvironmentClosureV1.model_construct(
        schema_version="1",
        closure_id=uuid7(),
        closure_version="1",
        created_at=NOW,
        semantic_policy_hashes=(H[1],),
        git_commit="e072665",
        git_tree_hash=h_git,
        git_archive_hash=h_git,
        drift_wheel_hash=h_wheel,
        drift_sdist_hash=h_sdist,
        pyproject_toml_hash=h_meta,
        uv_lock_hash=h_uvlock,
        pylock_toml_hash=h_pylock,
        uv_executable_hash=h_uv,
        python_runtime=python_runtime,
        package_artifacts=(),
        system_libraries=(sys_lib,),
        tzif_hash=h_tz,
        source_snapshot_hash=h_snap,
        restore_recipe_hash=h_rec,
        platform=platform,
        vulnerability_evidence_hash=h_vuln,
        security_lane="safe_offline",
        environment_artifacts=env_artifacts,
        closure_hash="0" * 64,
    )
    closure = closure_unhashed.model_copy(
        update={"closure_hash": environment_closure_hash(closure_unhashed)}
    )

    # Verification of clean environment closure succeeds without network
    verify_environment_closure(closure, artifacts)
    assert closure.platform.os_name == "macos"
    assert closure.platform.architecture == "arm64"
