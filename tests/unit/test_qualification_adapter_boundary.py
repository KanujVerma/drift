from datetime import UTC, datetime
from uuid import uuid7

import pytest

from drift.domain.common import SHA256Hash
from drift.domain.qualification import (
    ConsumerPurpose,
    PilotProfileSetV1,
    QualificationDimension,
)
from drift.domain.qualification_adapters import (
    AdapterIdentityV1,
    CandidateContextBlueprintV1,
    DatasetBlueprintV1,
    EmittedRecordMappingV1,
    FieldMappingDecisionV1,
    MappingDisposition,
    NativeRecordReferenceV1,
    OperationKind,
    ProviderMappingReportV1,
    QualifiedSourceHandoffV1,
    candidate_context_blueprint_hash,
    provider_mapping_report_hash,
    qualified_source_handoff_hash,
)
from drift.qualification.adapters import (
    CandidateFactSet,
    CandidateValidationContext,
    ValidatedCandidateFactSet,
    validate_candidate_facts,
    verify_mapping_report_integrity,
)
from drift.qualification.snapshots import ExistingContractContexts
from drift.serialization.canonical import content_hash

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _make_test_adapter_identity(
    profile_set_hash: SHA256Hash = H[0],
    profile_hashes: tuple[SHA256Hash, ...] = (H[1], H[2]),
) -> AdapterIdentityV1:
    return AdapterIdentityV1(
        adapter_id="test_adapter",
        adapter_version="1.0.0",
        supported_profile_set_hash=profile_set_hash,
        supported_profile_hashes=profile_hashes,
        provider_schema_hash=H[3],
        provider_methodology_hash=H[4],
        semantic_policy_hash=H[5],
        installed_source_hash=H[6],
    )


def test_adapter_identity_profile_subset_enforcement() -> None:
    # A profile not in supported_profile_hashes is rejected
    identity = _make_test_adapter_identity(profile_hashes=(H[1],))
    assert H[1] in identity.supported_profile_hashes
    assert H[2] not in identity.supported_profile_hashes


def test_field_mapping_decision_forbidden_inferences() -> None:
    # Attempting to map unsupported native fields as clean mapped without evidence
    # fails or records lossy
    decision = FieldMappingDecisionV1(
        target_role="identity_assignment",
        target_field="security_id",
        source_native_field="current_ticker",
        disposition=MappingDisposition.MAPPED,
        rule_evidence_hashes=(H[7],),
        availability_rule="source_observed",
        is_lossy=True,
        limitations=("current_ticker_cannot_mint_permanent_identity",),
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert decision.is_lossy is True
    assert "current_ticker_cannot_mint_permanent_identity" in decision.limitations


def test_provider_mapping_report_coverage_reconciliation() -> None:
    # Emitted records and consumed native records must reconcile
    identity = _make_test_adapter_identity()
    native_ref = NativeRecordReferenceV1(
        native_byte_hash=H[8],
        decoded_record_hash=H[9],
        native_key="rec-1",
        byte_layer_rule_hash=H[10],
        availability_evidence_hash=H[11],
    )
    mapping = EmittedRecordMappingV1(
        emitted_record_hash=H[12],
        native_record_references=(native_ref,),
        field_mapping_decision_hashes=(H[13],),
        operation_kind=OperationKind.ONE_TO_ONE,
        transformation_evidence_hashes=(H[14],),
    )
    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=identity,
        profile_set_hash=H[0],
        profile_hashes=(H[1], H[2]),
        receipt_hashes=(H[3],),
        native_field_inventory=("ticker", "close_price"),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(mapping,),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=1,
        emitted_records_count=1,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=H[0],
    )
    report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )
    assert report.coverage_reconciliation_pass is True


def test_mapping_report_rejects_tampered_emitted_record_hash() -> None:
    identity = _make_test_adapter_identity()
    native_ref = NativeRecordReferenceV1(
        native_byte_hash=H[8],
        decoded_record_hash=H[9],
        native_key="rec-1",
        byte_layer_rule_hash=H[10],
        availability_evidence_hash=H[11],
    )
    mapping = EmittedRecordMappingV1(
        emitted_record_hash=H[12],
        native_record_references=(native_ref,),
        field_mapping_decision_hashes=(),
        operation_kind=OperationKind.ONE_TO_ONE,
        transformation_evidence_hashes=(),
    )
    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=identity,
        profile_set_hash=H[0],
        profile_hashes=(H[1], H[2]),
        receipt_hashes=(H[3],),
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(mapping,),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=1,
        emitted_records_count=1,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=H[0],
    )
    report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )

    # 1. Mutating through model_copy validates hash mismatch
    tampered_mapping = mapping.model_copy(update={"emitted_record_hash": H[13]})
    with pytest.raises(Exception, match="report hash mismatch"):
        report.model_copy(update={"emitted_record_mappings": (tampered_mapping,)})

    # 2. Tampered report verified through verifier fails
    tampered_report = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=identity,
        profile_set_hash=H[0],
        profile_hashes=(H[1], H[2]),
        receipt_hashes=(H[3],),
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(tampered_mapping,),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=1,
        emitted_records_count=1,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=report.report_hash,  # stale hash
    )
    with pytest.raises(ValueError, match="report hash mismatch"):
        verify_mapping_report_integrity(tampered_report)


def test_candidate_context_blueprint_and_dataset_binding() -> None:
    ds_bp = DatasetBlueprintV1(
        dataset_role="identity_assignment",
        record_model_id="IdentityAssignmentVersionV1",
        partition_object_hashes=(H[1],),
        supporting_artifact_hashes=(H[2],),
        validation_run_hash=H[3],
        bundle_group="identity_group",
    )
    bp_unhashed = CandidateContextBlueprintV1.model_construct(
        schema_version="1",
        dataset_blueprints=(ds_bp,),
        cross_context_links=("link-1",),
        blueprint_hash=H[0],
    )
    bp = bp_unhashed.model_copy(
        update={"blueprint_hash": candidate_context_blueprint_hash(bp_unhashed)}
    )
    assert bp.dataset_blueprints[0].dataset_role == "identity_assignment"


def test_forbidden_inference_terms_cannot_mint_occurrence() -> None:
    decision = FieldMappingDecisionV1(
        target_role="economic_occurrence",
        target_field="occurrence_id",
        source_native_field="action_announcement",
        disposition=MappingDisposition.UNSUPPORTED,
        rule_evidence_hashes=(),
        availability_rule="none",
        is_lossy=True,
        limitations=("terms_cannot_mint_occurrence",),
        affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
    )
    assert decision.disposition == MappingDisposition.UNSUPPORTED
    assert "terms_cannot_mint_occurrence" in decision.limitations


def test_forbidden_inference_pay_date_cannot_mint_settlement() -> None:
    decision = FieldMappingDecisionV1(
        target_role="economic_settlement",
        target_field="settlement_status",
        source_native_field="pay_date",
        disposition=MappingDisposition.UNSUPPORTED,
        rule_evidence_hashes=(),
        availability_rule="none",
        is_lossy=True,
        limitations=("pay_date_cannot_mint_settlement",),
        affected_dimension=QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
    )
    assert "pay_date_cannot_mint_settlement" in decision.limitations


def test_forbidden_inference_daily_cannot_mint_regular_session() -> None:
    decision = FieldMappingDecisionV1(
        target_role="scheduled_session",
        target_field="session_id",
        source_native_field="daily_bar",
        disposition=MappingDisposition.UNSUPPORTED,
        rule_evidence_hashes=(),
        availability_rule="none",
        is_lossy=True,
        limitations=("daily_cannot_mint_regular_session_meaning",),
        affected_dimension=QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
    )
    assert "daily_cannot_mint_regular_session_meaning" in decision.limitations


def test_forbidden_inference_missing_row_cannot_mint_no_trade() -> None:
    decision = FieldMappingDecisionV1(
        target_role="source_observation",
        target_field="trade_volume",
        source_native_field="missing_row",
        disposition=MappingDisposition.UNKNOWN,
        rule_evidence_hashes=(),
        availability_rule="none",
        is_lossy=True,
        limitations=("missing_row_or_zero_cannot_mint_no_trade",),
        affected_dimension=QualificationDimension.COVERAGE_OMISSION,
    )
    assert "missing_row_or_zero_cannot_mint_no_trade" in decision.limitations


def test_forbidden_inference_successful_response_cannot_mint_completeness() -> None:
    decision = FieldMappingDecisionV1(
        target_role="observation_coverage",
        target_field="completeness",
        source_native_field="http_200_ok",
        disposition=MappingDisposition.UNKNOWN,
        rule_evidence_hashes=(),
        availability_rule="none",
        is_lossy=True,
        limitations=("successful_response_cannot_mint_completeness",),
        affected_dimension=QualificationDimension.COVERAGE_OMISSION,
    )
    assert "successful_response_cannot_mint_completeness" in decision.limitations


def test_adapter_coverage_reconciliation_fails_on_omitted_native_records() -> None:
    identity = _make_test_adapter_identity()
    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=identity,
        profile_set_hash=H[0],
        profile_hashes=(H[1], H[2]),
        receipt_hashes=(H[3],),
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=2,
        emitted_records_count=1,
        coverage_reconciliation_pass=False,  # fails reconciliation
        limitations=("unreconciled_native_records",),
        report_hash=H[0],
    )
    report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )
    with pytest.raises(
        ValueError, match="mapping report did not pass coverage reconciliation"
    ):
        verify_mapping_report_integrity(report)


def test_validate_candidate_facts_blueprint_and_profile_set_verification() -> None:
    from test_qualification_contracts import profile as make_profile

    p1 = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    p2 = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(p1, p2)
    )

    identity = _make_test_adapter_identity(
        profile_set_hash=content_hash(profile_set),
        profile_hashes=(H[1], H[2]),
    )
    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=identity,
        profile_set_hash=content_hash(profile_set),
        profile_hashes=(H[1], H[2]),
        receipt_hashes=(),
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(),
        emitted_candidate_dataset_hashes=(),
        native_records_count=0,
        emitted_records_count=0,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=H[0],
    )
    mapping_report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )

    bp_unhashed = CandidateContextBlueprintV1.model_construct(
        schema_version="1",
        dataset_blueprints=(),
        cross_context_links=(),
        blueprint_hash=H[0],
    )
    blueprint = bp_unhashed.model_copy(
        update={"blueprint_hash": candidate_context_blueprint_hash(bp_unhashed)}
    )

    candidate = CandidateFactSet(
        blueprint=blueprint,
        m1b_datasets=(),
        m1c_datasets=(),
        m1d_datasets=(),
        mapping_report=mapping_report,
    )

    val_context = CandidateValidationContext(
        profiles=profile_set,
        receipts=(),
        acquisition_authority=object(),  # type: ignore[arg-type]
        native_artifacts={},
        adjudication_policy_artifacts={},
        existing_contexts=ExistingContractContexts(
            m1b_contexts=(),
            m1c_context=None,  # type: ignore[arg-type]
            m1d_context=None,  # type: ignore[arg-type]
        ),
    )

    # 1. Validation succeeds
    validated = validate_candidate_facts(candidate, val_context)
    assert isinstance(validated, ValidatedCandidateFactSet)
    assert validated.mapping_report == mapping_report

    # 2. Profile set mismatch fails closed
    other_profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="2", profiles=(p1, p2)
    )
    other_context = CandidateValidationContext(
        profiles=other_profile_set,
        receipts=(),
        acquisition_authority=object(),  # type: ignore[arg-type]
        native_artifacts={},
        adjudication_policy_artifacts={},
    )
    with pytest.raises(
        ValueError, match="mapping report profile set hash .* does not match"
    ):
        validate_candidate_facts(candidate, other_context)


def test_qualified_source_handoff_hash_integrity() -> None:
    handoff_unhashed = QualifiedSourceHandoffV1.model_construct(
        schema_version="1",
        handoff_id=uuid7(),
        purpose=ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        profile_hash=H[0],
        report_hash=H[1],
        target_hash=H[2],
        snapshot_hash=H[3],
        rights_assessment_hash=H[4],
        universe_references=("univ-1",),
        economic_outcome_references=("outcome-1",),
        observation_view_references=("obs-1",),
        session_view_references=("sess-1",),
        environment_closure_hash=None,
        replay_authorization_hash=None,
        limitations=(),
        handoff_hash=H[0],
    )
    handoff = handoff_unhashed.model_copy(
        update={"handoff_hash": qualified_source_handoff_hash(handoff_unhashed)}
    )
    assert handoff.purpose == ConsumerPurpose.HISTORICAL_DECISION_INPUT
    assert handoff.universe_references == ("univ-1",)

    # Tampering report hash causes validation error
    with pytest.raises(ValueError, match="handoff hash mismatch"):
        handoff.model_copy(update={"report_hash": H[9]})
