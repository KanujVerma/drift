"""Qualification harness assessing real-source candidates against Drift contracts."""

from dataclasses import dataclass

from drift.domain.dataset_validation import ValidationResult
from drift.domain.golden_cases import (
    GoldenCasePlanV1,
    GoldenCaseResultV1,
    GoldenCaseStatus,
)
from drift.domain.qualification import (
    _PRE_REPLAY_DIMENSIONS,
    AcquisitionState,
    DimensionQualificationResultV1,
    ExecutionReachability,
    PreReplayQualificationReportV1,
    QualificationStatus,
    QualificationTargetV1,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import MappingDisposition
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.qualification.adapters import (
    CandidateValidationContext,
    QualificationAdapter,
    ValidatedCandidateFactSet,
    verify_mapping_report_integrity,
)
from drift.qualification.golden_cases import (
    GoldenCaseGradingContext,
    grade_golden_case,
)
from drift.serialization.canonical import content_hash


@dataclass(frozen=True, slots=True)
class QualificationExecutionContext:
    """Context containing validated candidates, snapshot, and golden cases."""

    validation: CandidateValidationContext
    validated_candidate: ValidatedCandidateFactSet
    snapshot: RealSourceSnapshotV1
    targets: tuple[QualificationTargetV1, ...]
    golden_case_plans: tuple[GoldenCasePlanV1, ...]
    golden_case_results: tuple[GoldenCaseResultV1, ...]
    grading_context: GoldenCaseGradingContext


def qualify_source(
    target: QualificationTargetV1,
    adapter: QualificationAdapter,
    context: QualificationExecutionContext,
) -> PreReplayQualificationReportV1:
    """Evaluate candidate through 11 pre-replay dimensions and golden cases."""
    # 1. Enforce snapshot-bound state and matching snapshot hash
    if target.acquisition_state is not AcquisitionState.SNAPSHOT_BOUND:
        raise ValueError("qualification target must be snapshot-bound")
    if target.snapshot_hash != context.snapshot.snapshot_hash:
        raise ValueError(
            f"target snapshot hash {target.snapshot_hash} does not match "
            f"execution context snapshot hash {context.snapshot.snapshot_hash}"
        )

    # 2. Check profile support
    if target.profile_hash not in adapter.identity.supported_profile_hashes:
        raise ValueError(
            f"target profile {target.profile_hash} not supported by adapter "
            f"{adapter.identity.adapter_id}"
        )

    profile_match = next(
        (
            p
            for p in context.validation.profiles.profiles
            if qualification_profile_hash(p) == target.profile_hash
        ),
        None,
    )
    if profile_match is None:
        raise ValueError(
            f"target profile {target.profile_hash} not found in pilot profile set"
        )

    # 3. Verify mapping report integrity
    verify_mapping_report_integrity(context.validated_candidate.mapping_report)

    # 4. Check dataset validation decisions: must all be PASS
    for dec in context.validated_candidate.validation_decisions:
        if dec.result != ValidationResult.PASS:
            raise ValueError(
                f"candidate dataset manifest {dec.manifest_hash} "
                f"failed validation: {dec.findings}"
            )

    # 5. Check golden case coverage against required_golden_case_ids
    required_gc_ids = set(profile_match.required_golden_case_ids)
    plan_gc_ids = {plan.definition.case_id.value for plan in context.golden_case_plans}
    missing_gc_ids = required_gc_ids - plan_gc_ids
    if missing_gc_ids:
        missing_sorted = sorted(missing_gc_ids)
        raise ValueError(
            f"missing golden case plans for required golden case IDs: {missing_sorted}"
        )

    # 6. Grade golden cases
    gc_results: list[GoldenCaseResultV1] = []
    for plan in context.golden_case_plans:
        res = grade_golden_case(
            plan, context.validated_candidate, context.grading_context
        )
        gc_results.append(res)

    # 7. Evaluate each of the 11 pre-replay dimensions
    results: list[DimensionQualificationResultV1] = []
    mapping_report = context.validated_candidate.mapping_report

    for dim in _PRE_REPLAY_DIMENSIONS:
        dim_plans = [
            plan
            for plan in context.golden_case_plans
            if dim in plan.definition.dimensions
        ]
        dim_gc_results = [
            res
            for plan, res in zip(context.golden_case_plans, gc_results, strict=True)
            if dim in plan.definition.dimensions
        ]
        tested_gc_ids = tuple(
            sorted({plan.definition.case_id.value for plan in dim_plans})
        )

        dim_decisions = [
            d for d in mapping_report.field_decisions if d.affected_dimension == dim
        ]

        has_gc_fail = any(r.status == GoldenCaseStatus.FAIL for r in dim_gc_results)
        has_gc_unknown = any(
            r.status == GoldenCaseStatus.UNKNOWN for r in dim_gc_results
        )
        has_gc_partial = any(
            r.status == GoldenCaseStatus.PARTIAL for r in dim_gc_results
        )

        has_conflicting_decision = any(
            d.disposition == MappingDisposition.CONFLICTING for d in dim_decisions
        )
        has_unsupported_decision = any(
            d.disposition == MappingDisposition.UNSUPPORTED for d in dim_decisions
        )
        has_lossy_decision = any(d.is_lossy for d in dim_decisions)

        status: QualificationStatus
        if has_gc_fail or has_conflicting_decision:
            status = QualificationStatus.FAIL
        elif has_gc_unknown:
            status = QualificationStatus.UNKNOWN
        elif has_gc_partial or has_unsupported_decision or has_lossy_decision:
            status = QualificationStatus.PARTIAL
        else:
            status = QualificationStatus.PASS

        # Collect evidence hashes (must be non-empty for reached dimension)
        ev_hashes = {mapping_report.report_hash, context.snapshot.snapshot_hash}
        ev_hashes.update(r.result_hash for r in dim_gc_results)
        evidence_hashes = tuple(sorted(ev_hashes))

        limitations: tuple[str, ...]
        if status is not QualificationStatus.PASS:
            lims = list(mapping_report.limitations)
            lims.append(f"{dim.value}_status_{status.value}")
            for r in dim_gc_results:
                lims.extend(r.limitations)
            limitations = tuple(sorted(set(lims)))
        else:
            limitations = ()

        admitted_purpose = status is QualificationStatus.PASS

        dim_res = DimensionQualificationResultV1(
            schema_version="1",
            dimension=dim,
            purpose=profile_match.purpose,
            status=status,
            reachability=ExecutionReachability.REACHED,
            evidence_hashes=evidence_hashes,
            tested_golden_case_ids=tested_gc_ids,
            admitted_purpose=admitted_purpose,
            limitations=limitations,
            adjudication_policy_hash=profile_match.adjudication_policy_hash,
        )
        results.append(dim_res)

    return PreReplayQualificationReportV1(
        schema_version="1",
        purpose=profile_match.purpose,
        target=target,
        results=tuple(results),
    )


def verify_qualification_report(
    report: PreReplayQualificationReportV1,
    adapter: QualificationAdapter,
    context: QualificationExecutionContext,
) -> None:
    """Verify report was authentically computed from retained evidence."""
    target_match = next(
        (t for t in context.targets if content_hash(t) == content_hash(report.target)),
        None,
    )
    if target_match is None:
        raise ValueError("target in report does not match any execution context target")

    expected = qualify_source(target_match, adapter, context)
    if content_hash(report) != content_hash(expected):
        raise ValueError(
            f"qualification report content hash mismatch: "
            f"expected {content_hash(expected)}, got {content_hash(report)}"
        )
