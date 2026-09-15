"""Grading algorithms and result verification for Drift M1e Golden Cases."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.golden_cases import (
    GoldenCasePlanV1,
    GoldenCaseReachability,
    GoldenCaseResultV1,
    GoldenCaseStatus,
    IndependentTruthClaimV1,
    PredicateEvaluation,
    PredicateResultV1,
    TruthEvidenceEntryV1,
    TruthExtractionDecisionV1,
    TruthIntakeReceiptV1,
    evaluate_predicate,
    golden_case_result_hash,
)
from drift.qualification.adapters import ValidatedCandidateFactSet
from drift.serialization.canonical import content_hash


@dataclass(frozen=True, slots=True)
class GoldenCaseGradingContext:
    """Retained ground-truth bytes and provenance chain for grading golden cases."""

    truth_bytes: Mapping[str, VerifiedArtifactBytes]
    intake_receipts: tuple[TruthIntakeReceiptV1, ...]
    evidence_entries: tuple[TruthEvidenceEntryV1, ...]
    extraction_decisions: tuple[TruthExtractionDecisionV1, ...]
    truth_claims: tuple[IndependentTruthClaimV1, ...]


def _extract_field_value(record: Any, field_name: str) -> Any:
    """Extract named field from record or nested payload/dates/components/revision."""
    if hasattr(record, field_name):
        return getattr(record, field_name)
    if hasattr(record, "identity") and record.identity is not None:
        ident = record.identity
        if hasattr(ident, field_name):
            return getattr(ident, field_name)
    if hasattr(record, "payload") and record.payload is not None:
        payload = record.payload
        if hasattr(payload, field_name):
            return getattr(payload, field_name)
        if hasattr(payload, "components"):
            for comp in payload.components:
                if hasattr(comp, field_name):
                    return getattr(comp, field_name)
        if hasattr(payload, "dates"):
            for dt in payload.dates:
                if hasattr(dt, field_name):
                    return getattr(dt, field_name)
                if getattr(dt, "role", None) == field_name:
                    return dt.date_value
    if hasattr(record, "revision") and record.revision is not None:
        rev = record.revision
        if hasattr(rev, field_name):
            return getattr(rev, field_name)
    return None


def grade_golden_case(
    plan: GoldenCasePlanV1,
    candidate: ValidatedCandidateFactSet,
    context: GoldenCaseGradingContext,
) -> GoldenCaseResultV1:
    """Evaluate one golden case against candidate outputs and independent truth."""
    # 1. Verify truth claims match context
    truth_claims_by_id = {tc.claim_id: tc for tc in context.truth_claims}
    for tc in plan.truth_claims:
        if tc.claim_id not in truth_claims_by_id:
            raise ValueError(f"truth claim {tc.claim_id} missing from grading context")

    # 2. Check reachability: candidate must have bound claims or explicit absence
    if not plan.candidate_bindings:
        unhashed = GoldenCaseResultV1.model_construct(
            schema_version="1",
            case_id=plan.definition.case_id,
            reachability=GoldenCaseReachability.NOT_REACHED,
            status=GoldenCaseStatus.UNKNOWN,
            predicate_results=(),
            compared_claim_hashes=(),
            evidence_hashes=(),
            policy_hashes=(),
            limitations=("candidate_bindings_not_reached",),
            result_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"result_hash": golden_case_result_hash(unhashed)}
        )

    # 3. Resolve candidate records via candidate claim bindings
    matched_hashes = {
        h for b in plan.candidate_bindings for h in b.matched_record_hashes
    }
    matched_records: list[Any] = []
    if matched_hashes:
        for recs in candidate.records_by_role.values():
            for rec in recs:
                if content_hash(rec) in matched_hashes:
                    matched_records.append(rec)

    coverage_pass = candidate.mapping_report.coverage_reconciliation_pass

    # 4. Evaluate each predicate in definition
    results: list[PredicateResultV1] = []
    has_false = False
    has_unsupported = False
    has_unknown = False
    has_true = False

    for pred in plan.definition.predicates:
        candidate_val: Any = None
        truth_val: Any = None

        # Resolve truth value from selector if present
        if pred.truth_selector is not None:
            tc_id = pred.truth_selector.truth_claim_id
            if tc_id in truth_claims_by_id:
                truth_val = truth_claims_by_id[tc_id].canonical_value

        # Look up candidate value in bound candidate records
        for rec in matched_records:
            val = _extract_field_value(rec, pred.candidate_field)
            if val is not None:
                candidate_val = val
                break

        res = evaluate_predicate(
            pred, candidate_val, truth_val, coverage_pass=coverage_pass
        )
        results.append(res)

        if pred.is_required:
            if res.evaluation == PredicateEvaluation.FALSE:
                has_false = True
            elif res.evaluation == PredicateEvaluation.UNKNOWN:
                has_unknown = True
            elif res.evaluation == PredicateEvaluation.UNSUPPORTED:
                has_unsupported = True
            elif res.evaluation == PredicateEvaluation.TRUE:
                has_true = True

    # 5. Status determination per closed rule: FAIL > UNKNOWN > PARTIAL > PASS
    status: GoldenCaseStatus
    limitations: tuple[str, ...]
    if has_false:
        status = GoldenCaseStatus.FAIL
        limitations = (f"case_{plan.definition.case_id.value}_failed",)
    elif has_unknown:
        status = GoldenCaseStatus.UNKNOWN
        limitations = (f"case_{plan.definition.case_id.value}_unknown",)
    elif has_unsupported:
        status = GoldenCaseStatus.PARTIAL
        limitations = (f"case_{plan.definition.case_id.value}_partial",)
    elif has_true:
        status = GoldenCaseStatus.PASS
        limitations = ()
    else:
        status = GoldenCaseStatus.UNKNOWN
        limitations = (f"case_{plan.definition.case_id.value}_not_reached",)

    unhashed = GoldenCaseResultV1.model_construct(
        schema_version="1",
        case_id=plan.definition.case_id,
        reachability=GoldenCaseReachability.REACHED,
        status=status,
        predicate_results=tuple(results),
        compared_claim_hashes=tuple(tc.claim_hash for tc in plan.truth_claims),
        evidence_hashes=tuple(e.evidence_entry_hash for e in plan.evidence_entries),
        policy_hashes=(),
        limitations=limitations,
        result_hash="0" * 64,
    )
    return unhashed.model_copy(
        update={"result_hash": golden_case_result_hash(unhashed)}
    )


def verify_golden_case_result(
    result: GoldenCaseResultV1,
    plan: GoldenCasePlanV1,
    candidate: ValidatedCandidateFactSet,
    context: GoldenCaseGradingContext,
) -> None:
    """Verify golden case result matches independent grading from retained bytes."""
    expected = grade_golden_case(plan, candidate, context)
    if result.result_hash != expected.result_hash:
        raise ValueError(
            f"golden case {result.case_id} result hash mismatch: "
            f"expected {expected.result_hash}, got {result.result_hash}"
        )
