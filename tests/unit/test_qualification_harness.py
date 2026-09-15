"""Unit tests for M1e qualification harness and report verification."""

from datetime import UTC, datetime
from uuid import uuid7

import pytest

from drift.domain.common import SHA256Hash
from drift.domain.golden_cases import (
    ALL_GOLDEN_CASE_DEFINITIONS,
    CandidateClaimBindingV1,
    GoldenCaseId,
    GoldenCaseInstanceV1,
    GoldenCasePlanV1,
)
from drift.domain.qualification import (
    _PRE_REPLAY_DIMENSIONS,
    AcquisitionState,
    ConsumerPurpose,
    DimensionQualificationResultV1,
    PilotProfileSetV1,
    PreReplayQualificationReportV1,
    QualificationDimension,
    QualificationTargetV1,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import (
    AdapterIdentityV1,
    ProviderMappingReportV1,
    provider_mapping_report_hash,
)
from drift.qualification.adapters import (
    CandidateFactSet,
    CandidateValidationContext,
    QualificationAdapterInput,
    ValidatedCandidateFactSet,
)
from drift.qualification.golden_cases import GoldenCaseGradingContext
from drift.qualification.harness import (
    QualificationExecutionContext,
    qualify_source,
    verify_qualification_report,
)
from drift.serialization.canonical import content_hash

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class _MockAdapter:
    def __init__(self, supported_profile_hash: SHA256Hash) -> None:
        self.identity = AdapterIdentityV1(
            adapter_id="mock_adapter",
            adapter_version="1.0.0",
            supported_profile_set_hash=H[0],
            supported_profile_hashes=(supported_profile_hash,),
            provider_schema_hash=H[1],
            provider_methodology_hash=H[2],
            semantic_policy_hash=H[3],
            installed_source_hash=H[4],
        )

    def map(self, value: QualificationAdapterInput) -> CandidateFactSet:
        raise NotImplementedError


def _make_plan(
    case_id: GoldenCaseId, target_hash: SHA256Hash, profile_hash: SHA256Hash
) -> GoldenCasePlanV1:
    definition = ALL_GOLDEN_CASE_DEFINITIONS[case_id]
    instance = GoldenCaseInstanceV1(
        instance_id=uuid7(),
        case_id=case_id,
        subject_id=f"sub-{case_id.value}",
        event_id=f"evt-{case_id.value}",
        target_fields=("security_id",),
        truth_claim_ids=(),
        definition_hash=definition.definition_hash,
    )
    binding = CandidateClaimBindingV1(
        schema_version="1",
        selector_spec_hash=H[0],
        matched_record_hashes=(),
        emitted_mapping_hashes=(),
        coverage_evidence_hash=H[1],
        binding_policy_hash=H[2],
        binding_hash=H[3],
    )
    return GoldenCasePlanV1(
        definition=definition,
        instance=instance,
        profile_hash=profile_hash,
        target_hash=target_hash,
        candidate_bindings=(binding,),
        truth_claims=(),
        evidence_entries=(),
    )


def test_qualify_source_and_verify_report() -> None:
    from test_qualification_contracts import profile as make_profile
    from test_source_snapshots import _make_sample_snapshot_and_state

    p1 = make_profile(ConsumerPurpose.HISTORICAL_DECISION_INPUT)
    p2 = make_profile(ConsumerPurpose.RETROSPECTIVE_AUDIT)

    p1_hash = qualification_profile_hash(p1)
    profile_set = PilotProfileSetV1(
        pilot_id=uuid7(), pilot_version="1", profiles=(p1, p2)
    )

    adapter = _MockAdapter(p1_hash)
    snapshot, artifacts, contexts, _, _ = _make_sample_snapshot_and_state()

    target = QualificationTargetV1(
        profile_hash=p1_hash,
        acquisition_state=AcquisitionState.SNAPSHOT_BOUND,
        receipt_hashes=snapshot.receipt_hashes,
        snapshot_hash=snapshot.snapshot_hash,
        failure_evidence_hashes=(),
    )

    report_unhashed = ProviderMappingReportV1.model_construct(
        schema_version="1",
        adapter_identity=adapter.identity,
        profile_set_hash=content_hash(profile_set),
        profile_hashes=(p1_hash,),
        receipt_hashes=snapshot.receipt_hashes,
        native_field_inventory=(),
        field_decisions=(),
        unsupported_native_values=(),
        emitted_record_mappings=(),
        emitted_candidate_dataset_hashes=(H[4],),
        native_records_count=0,
        emitted_records_count=0,
        coverage_reconciliation_pass=True,
        limitations=(),
        report_hash=H[0],
    )

    mapping_report = report_unhashed.model_copy(
        update={"report_hash": provider_mapping_report_hash(report_unhashed)}
    )

    validated_candidate = ValidatedCandidateFactSet(
        mapping_report=mapping_report,
        validation_decisions=(),
        bundles=(),
        records_by_role={},
        contexts=contexts,
    )

    grading_context = GoldenCaseGradingContext(
        truth_bytes={},
        intake_receipts=(),
        evidence_entries=(),
        extraction_decisions=(),
        truth_claims=(),
    )

    validation_context = CandidateValidationContext(
        profiles=profile_set,
        receipts=(),
        acquisition_authority=object(),  # type: ignore[arg-type]
        native_artifacts={},
        adjudication_policy_artifacts={},
    )

    target_h = content_hash(target)
    plans = tuple(
        _make_plan(GoldenCaseId(gc_id), target_h, p1_hash)
        for gc_id in p1.required_golden_case_ids
    )

    exec_context = QualificationExecutionContext(
        validation=validation_context,
        validated_candidate=validated_candidate,
        snapshot=snapshot,
        targets=(target,),
        golden_case_plans=plans,
        golden_case_results=(),
        grading_context=grading_context,
    )

    # 1. Qualify source generates canonical report covering all 11 pre-replay dimensions
    report = qualify_source(target, adapter, exec_context)
    assert isinstance(report, PreReplayQualificationReportV1)
    assert len(report.results) == 11
    assert tuple(r.dimension for r in report.results) == _PRE_REPLAY_DIMENSIONS
    assert QualificationDimension.OFFLINE_REPLAY not in [
        r.dimension for r in report.results
    ]
    assert all(isinstance(r, DimensionQualificationResultV1) for r in report.results)

    # 2. verify_qualification_report validates matching report
    verify_qualification_report(report, adapter, exec_context)

    # 3. Missing required golden cases fails closed
    exec_context_no_plans = QualificationExecutionContext(
        validation=validation_context,
        validated_candidate=validated_candidate,
        snapshot=snapshot,
        targets=(target,),
        golden_case_plans=(),
        golden_case_results=(),
        grading_context=grading_context,
    )
    with pytest.raises(
        ValueError, match="missing golden case plans for required golden case IDs"
    ):
        qualify_source(target, adapter, exec_context_no_plans)

    # 4. Target profile mismatch is rejected
    mismatched_target = target.model_copy(update={"profile_hash": H[9]})
    with pytest.raises(ValueError, match="not supported by adapter"):
        qualify_source(mismatched_target, adapter, exec_context)

    # 5. Non snapshot-bound target is rejected
    not_bound = target.model_copy(
        update={
            "acquisition_state": AcquisitionState.NOT_ACQUIRED,
            "receipt_hashes": (),
            "snapshot_hash": None,
            "failure_evidence_hashes": (H[0],),
        }
    )
    with pytest.raises(ValueError, match="target must be snapshot-bound"):
        qualify_source(not_bound, adapter, exec_context)

    # 6. Snapshot hash mismatch is rejected
    tampered_snapshot_target = target.model_copy(update={"snapshot_hash": H[10]})
    with pytest.raises(ValueError, match="target snapshot hash .* does not match"):
        qualify_source(tampered_snapshot_target, adapter, exec_context)
