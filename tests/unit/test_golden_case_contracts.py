"""Unit tests for Golden Cases G01-G18 contracts and predicates."""

from datetime import UTC, datetime
from uuid import uuid7

import pytest

from drift.domain.golden_cases import (
    ALL_GOLDEN_CASE_DEFINITIONS,
    GoldenCaseId,
    GoldenCaseInstanceManifestV1,
    GoldenCaseInstanceV1,
    GoldenCasePlanV1,
    GoldenCasePredicateV1,
    GoldenCaseReachability,
    GoldenCaseResultV1,
    GoldenCaseStatus,
    IndependentTruthClaimV1,
    PredicateEvaluation,
    PredicateOperator,
    evaluate_predicate,
    golden_case_instance_manifest_hash,
    golden_case_result_hash,
    independent_truth_claim_hash,
)
from drift.domain.qualification import QualificationDimension

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def test_golden_case_inventory_exactness() -> None:
    # Exactly 18 cases G01 through G18
    assert len(GoldenCaseId) == 18
    assert len(ALL_GOLDEN_CASE_DEFINITIONS) == 18
    for gid in GoldenCaseId:
        assert gid in ALL_GOLDEN_CASE_DEFINITIONS
        definition = ALL_GOLDEN_CASE_DEFINITIONS[gid]
        assert definition.case_id == gid
        assert len(definition.predicates) > 0


def test_predicate_operators_and_closed_evaluations() -> None:
    assert len(PredicateOperator) == 9
    expected_operators = {
        "EQUAL",
        "NOT_EQUAL",
        "SAME_IDENTITY",
        "DISTINCT_IDENTITY",
        "ORDERED_BEFORE",
        "EXACT_RATIO",
        "REQUIRED_PRESENT",
        "REQUIRED_ABSENT",
        "PROHIBITED_INFERENCE",
    }
    assert {op.name for op in PredicateOperator} == expected_operators


def test_evaluate_predicate_equal_operator() -> None:
    pred = GoldenCasePredicateV1(
        predicate_id="pred-1",
        operator=PredicateOperator.EQUAL,
        candidate_field="name",
        expected_constant="Meta Platforms, Inc.",
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    # Exact equal evaluates TRUE
    res_true = evaluate_predicate(pred, candidate_value="Meta Platforms, Inc.")
    assert res_true.evaluation == PredicateEvaluation.TRUE

    # Unequal evaluates FALSE
    res_false = evaluate_predicate(pred, candidate_value="Facebook, Inc.")
    assert res_false.evaluation == PredicateEvaluation.FALSE

    # None / unknown evaluates UNKNOWN
    res_unknown = evaluate_predicate(pred, candidate_value=None)
    assert res_unknown.evaluation == PredicateEvaluation.UNKNOWN


def test_evaluate_predicate_not_equal_operator() -> None:
    pred = GoldenCasePredicateV1(
        predicate_id="pred-ne",
        operator=PredicateOperator.NOT_EQUAL,
        candidate_field="name",
        expected_constant="Facebook, Inc.",
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert evaluate_predicate(
        pred, candidate_value="Meta Platforms, Inc."
    ).evaluation == (PredicateEvaluation.TRUE)
    assert evaluate_predicate(pred, candidate_value="Facebook, Inc.").evaluation == (
        PredicateEvaluation.FALSE
    )


def test_evaluate_predicate_same_and_distinct_identity() -> None:
    u1 = uuid7()
    u2 = uuid7()

    pred_same = GoldenCasePredicateV1(
        predicate_id="pred-same",
        operator=PredicateOperator.SAME_IDENTITY,
        candidate_field="security_id",
        expected_constant=u1,
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert evaluate_predicate(pred_same, candidate_value=u1).evaluation == (
        PredicateEvaluation.TRUE
    )
    assert evaluate_predicate(pred_same, candidate_value=u2).evaluation == (
        PredicateEvaluation.FALSE
    )
    assert evaluate_predicate(pred_same, candidate_value=None).evaluation == (
        PredicateEvaluation.UNKNOWN
    )

    pred_distinct = GoldenCasePredicateV1(
        predicate_id="pred-distinct",
        operator=PredicateOperator.DISTINCT_IDENTITY,
        candidate_field="security_id",
        expected_constant=u1,
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert evaluate_predicate(pred_distinct, candidate_value=u2).evaluation == (
        PredicateEvaluation.TRUE
    )
    assert evaluate_predicate(pred_distinct, candidate_value=u1).evaluation == (
        PredicateEvaluation.FALSE
    )
    # Missing operand evaluates UNKNOWN, never vacuously TRUE
    pred_no_target = GoldenCasePredicateV1(
        predicate_id="pred-distinct-notarget",
        operator=PredicateOperator.DISTINCT_IDENTITY,
        candidate_field="security_id",
        expected_constant=None,
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert evaluate_predicate(pred_no_target, candidate_value=u2).evaluation == (
        PredicateEvaluation.UNKNOWN
    )


def test_evaluate_predicate_ordered_before() -> None:
    from datetime import date

    pred = GoldenCasePredicateV1(
        predicate_id="pred-order",
        operator=PredicateOperator.ORDERED_BEFORE,
        candidate_field="ex_date",
        expected_constant="2026-06-15",
        is_required=True,
        affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
    )
    # Date before string evaluates TRUE
    assert evaluate_predicate(pred, candidate_value=date(2026, 6, 1)).evaluation == (
        PredicateEvaluation.TRUE
    )
    # Datetime before string evaluates TRUE
    assert (
        evaluate_predicate(
            pred, candidate_value=datetime(2026, 6, 1, 10, tzinfo=UTC)
        ).evaluation
        == PredicateEvaluation.TRUE
    )
    # Date after string evaluates FALSE
    assert evaluate_predicate(pred, candidate_value=date(2026, 7, 1)).evaluation == (
        PredicateEvaluation.FALSE
    )
    # Uncomparable evaluates UNKNOWN without raising TypeError
    assert evaluate_predicate(pred, candidate_value=12345).evaluation == (
        PredicateEvaluation.UNKNOWN
    )


def test_evaluate_predicate_exact_ratio_operator() -> None:
    from drift.domain.economic_common import PositiveRatioV1

    pred = GoldenCasePredicateV1(
        predicate_id="pred-ratio",
        operator=PredicateOperator.EXACT_RATIO,
        candidate_field="ratio",
        expected_constant=(10, 1),
        is_required=True,
        affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
    )
    # Exact ratio evaluates TRUE
    assert evaluate_predicate(pred, candidate_value=(10, 1)).evaluation == (
        PredicateEvaluation.TRUE
    )
    # Reduced PositiveRatioV1 evaluates TRUE
    ratio_model = PositiveRatioV1(numerator="10", denominator="1")
    assert evaluate_predicate(pred, candidate_value=ratio_model).evaluation == (
        PredicateEvaluation.TRUE
    )
    # Different ratio evaluates FALSE
    assert evaluate_predicate(pred, candidate_value=(5, 1)).evaluation == (
        PredicateEvaluation.FALSE
    )
    # Non-ratio evaluates UNKNOWN
    assert evaluate_predicate(pred, candidate_value="not_a_ratio").evaluation == (
        PredicateEvaluation.UNKNOWN
    )


def test_evaluate_predicate_required_present() -> None:
    pred = GoldenCasePredicateV1(
        predicate_id="pred-present",
        operator=PredicateOperator.REQUIRED_PRESENT,
        candidate_field="reason",
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    assert evaluate_predicate(pred, candidate_value="delisted").evaluation == (
        PredicateEvaluation.TRUE
    )
    # Absent under passing coverage is FALSE
    assert (
        evaluate_predicate(pred, candidate_value=None, coverage_pass=True).evaluation
        == PredicateEvaluation.FALSE
    )
    # Absent without passing coverage is UNKNOWN
    assert (
        evaluate_predicate(pred, candidate_value=None, coverage_pass=False).evaluation
        == PredicateEvaluation.UNKNOWN
    )


def test_evaluate_predicate_required_absent() -> None:
    pred = GoldenCasePredicateV1(
        predicate_id="pred-absent",
        operator=PredicateOperator.REQUIRED_ABSENT,
        candidate_field="unexpected_field",
        is_required=True,
        affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
    )
    # Absent under passing coverage evaluates TRUE
    assert (
        evaluate_predicate(pred, candidate_value=None, coverage_pass=True).evaluation
        == PredicateEvaluation.TRUE
    )
    # Absent WITHOUT passing coverage evaluates UNKNOWN
    assert (
        evaluate_predicate(pred, candidate_value=None, coverage_pass=False).evaluation
        == PredicateEvaluation.UNKNOWN
    )
    # Present evaluates FALSE
    assert (
        evaluate_predicate(
            pred, candidate_value="present_value", coverage_pass=True
        ).evaluation
        == PredicateEvaluation.FALSE
    )


def test_evaluate_predicate_prohibited_inference() -> None:
    pred = GoldenCasePredicateV1(
        predicate_id="pred-prohibited",
        operator=PredicateOperator.PROHIBITED_INFERENCE,
        candidate_field="inferred_status",
        expected_constant="forbidden_value",
        is_required=True,
        affected_dimension=QualificationDimension.COVERAGE_OMISSION,
    )
    # Emitted forbidden value evaluates FALSE
    assert (
        evaluate_predicate(pred, candidate_value="forbidden_value").evaluation
        == PredicateEvaluation.FALSE
    )
    # Did not emit forbidden value evaluates TRUE
    assert (
        evaluate_predicate(pred, candidate_value="safe_value").evaluation
        == PredicateEvaluation.TRUE
    )


def test_grade_golden_case_and_verify_result() -> None:
    from drift.domain.assertions import RevisionEnvelopeV1
    from drift.domain.golden_cases import CandidateClaimBindingV1
    from drift.domain.qualification_adapters import (
        AdapterIdentityV1,
        ProviderMappingReportV1,
        provider_mapping_report_hash,
    )
    from drift.domain.securities import (
        IdentityAssignmentEffect,
        IdentityAssignmentVersionV1,
        SecurityV1,
    )
    from drift.qualification.adapters import ValidatedCandidateFactSet
    from drift.qualification.golden_cases import (
        GoldenCaseGradingContext,
        grade_golden_case,
        verify_golden_case_result,
    )
    from drift.qualification.snapshots import ExistingContractContexts
    from drift.serialization.canonical import content_hash

    sec_uuid = uuid7()
    definition = ALL_GOLDEN_CASE_DEFINITIONS[GoldenCaseId.G01]

    truth_claim_unhashed = IndependentTruthClaimV1.model_construct(
        schema_version="1",
        claim_id="TRUTH-G01-IDENTITY",
        subject_id="META",
        claim_kind="security_id",
        canonical_value=str(sec_uuid),
        temporal_lower_bound=NOW,
        temporal_upper_bound=NOW,
        evidence_hashes=(H[0],),
        extraction_decision_hash=H[1],
        limitations=(),
        claim_hash=H[2],
    )
    truth_claim = truth_claim_unhashed.model_copy(
        update={"claim_hash": independent_truth_claim_hash(truth_claim_unhashed)}
    )

    rec = IdentityAssignmentVersionV1.model_construct(
        schema_version="1",
        revision=RevisionEnvelopeV1.model_construct(
            payload_hash=H[3],
        ),
        identity=SecurityV1(schema_version="1", security_id=sec_uuid),
        assignment_effect=IdentityAssignmentEffect.ASSIGNED,
    )

    rec_hash = content_hash(rec)
    binding = CandidateClaimBindingV1(
        schema_version="1",
        selector_spec_hash=H[4],
        matched_record_hashes=(rec_hash,),
        emitted_mapping_hashes=(),
        coverage_evidence_hash=H[5],
        binding_policy_hash=H[6],
        binding_hash=H[7],
    )

    instance = GoldenCaseInstanceV1(
        instance_id=uuid7(),
        case_id=GoldenCaseId.G01,
        subject_id="META",
        event_id="EVT-G01",
        target_fields=("security_id",),
        truth_claim_ids=("TRUTH-G01-IDENTITY",),
        definition_hash=definition.definition_hash,
    )

    plan = GoldenCasePlanV1(
        definition=definition,
        instance=instance,
        profile_hash=H[8],
        target_hash=H[9],
        candidate_bindings=(binding,),
        truth_claims=(truth_claim,),
        evidence_entries=(),
    )

    adapter_identity = AdapterIdentityV1(
        adapter_id="test",
        adapter_version="1",
        supported_profile_set_hash=H[0],
        supported_profile_hashes=(H[8],),
        provider_schema_hash=H[1],
        provider_methodology_hash=H[2],
        semantic_policy_hash=H[3],
        installed_source_hash=H[4],
    )
    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=adapter_identity,
        profile_set_hash=H[0],
        profile_hashes=(H[8],),
        receipt_hashes=(),
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=1,
        emitted_records_count=1,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=H[0],
    )
    mapping_report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )

    contexts = ExistingContractContexts(
        m1b_contexts=(),
        m1c_context=None,  # type: ignore[arg-type]
        m1d_context=None,  # type: ignore[arg-type]
    )
    candidate = ValidatedCandidateFactSet(
        mapping_report=mapping_report,
        validation_decisions=(),
        bundles=(),
        records_by_role={"identity_assignment": (rec,)},
        contexts=contexts,
    )

    grading_ctx = GoldenCaseGradingContext(
        truth_bytes={},
        intake_receipts=(),
        evidence_entries=(),
        extraction_decisions=(),
        truth_claims=(truth_claim,),
    )

    # 1. Grade golden case evaluates PASS
    result = grade_golden_case(plan, candidate, grading_ctx)
    assert result.status == GoldenCaseStatus.PASS
    assert result.reachability == GoldenCaseReachability.REACHED

    # 2. verify_golden_case_result validates matching result
    verify_golden_case_result(result, plan, candidate, grading_ctx)

    # 3. Tampered result fails verification
    tampered_unhashed = GoldenCaseResultV1.model_construct(
        schema_version=result.schema_version,
        case_id=result.case_id,
        reachability=result.reachability,
        status=GoldenCaseStatus.FAIL,
        predicate_results=result.predicate_results,
        compared_claim_hashes=result.compared_claim_hashes,
        evidence_hashes=result.evidence_hashes,
        policy_hashes=result.policy_hashes,
        limitations=result.limitations,
        result_hash="0" * 64,
    )
    tampered_result = tampered_unhashed.model_copy(
        update={"result_hash": golden_case_result_hash(tampered_unhashed)}
    )
    with pytest.raises(ValueError, match="result hash mismatch"):
        verify_golden_case_result(tampered_result, plan, candidate, grading_ctx)


def test_golden_case_instance_manifest_hash_integrity() -> None:
    instances = tuple(
        GoldenCaseInstanceV1(
            instance_id=uuid7(),
            case_id=gid,
            subject_id=f"sub-{gid.value}",
            event_id=f"evt-{gid.value}",
            target_fields=("f1",),
            truth_claim_ids=("tc-1",),
            definition_hash=ALL_GOLDEN_CASE_DEFINITIONS[gid].definition_hash,
        )
        for gid in GoldenCaseId
    )
    manifest_unhashed = GoldenCaseInstanceManifestV1.model_construct(
        schema_version="1",
        instances=instances,
        selection_evidence_hash=H[0],
        frozen_at=NOW,
        manifest_hash=H[0],
    )
    manifest = manifest_unhashed.model_copy(
        update={"manifest_hash": golden_case_instance_manifest_hash(manifest_unhashed)}
    )
    assert len(manifest.instances) == 18
