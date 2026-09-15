"""Domain models and definitions for Drift M1e Golden Cases (G01-G18)."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import model_validator

from drift.domain.common import FrozenModel, SHA256Hash
from drift.domain.qualification import QualificationDimension
from drift.serialization.canonical import content_hash


class GoldenCaseId(StrEnum):
    """The 18 closed Drift M1e golden case identifiers."""

    G01 = "G01"
    G02 = "G02"
    G03 = "G03"
    G04 = "G04"
    G05 = "G05"
    G06 = "G06"
    G07 = "G07"
    G08 = "G08"
    G09 = "G09"
    G10 = "G10"
    G11 = "G11"
    G12 = "G12"
    G13 = "G13"
    G14 = "G14"
    G15 = "G15"
    G16 = "G16"
    G17 = "G17"
    G18 = "G18"


class PredicateOperator(StrEnum):
    """Closed set of golden case evaluation operators."""

    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    SAME_IDENTITY = "same_identity"
    DISTINCT_IDENTITY = "distinct_identity"
    ORDERED_BEFORE = "ordered_before"
    EXACT_RATIO = "exact_ratio"
    REQUIRED_PRESENT = "required_present"
    REQUIRED_ABSENT = "required_absent"
    PROHIBITED_INFERENCE = "prohibited_inference"


class PredicateEvaluation(StrEnum):
    """Four-valued logic outcome for a predicate."""

    TRUE = "true"
    FALSE = "false"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class GoldenCaseReachability(StrEnum):
    REACHED = "reached"
    NOT_REACHED = "not_reached"


class GoldenCaseStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class TruthExtractionMethod(StrEnum):
    STRUCTURED_PRIMARY = "structured_primary"
    HUMAN_ADJUDICATED = "human_adjudicated"


def truth_intake_receipt_hash(receipt: TruthIntakeReceiptV1) -> SHA256Hash:
    dump = receipt.model_dump(mode="python")
    dump.pop("receipt_hash", None)
    return content_hash(dump)


class TruthIntakeReceiptV1(FrozenModel):
    """Intake receipt for externally acquired primary truth evidence."""

    schema_version: str = "1"
    receipt_id: UUID
    source_id: str
    description: str
    byte_graph_hash: SHA256Hash
    origin_evidence_hash: SHA256Hash
    rights_binding_hash: SHA256Hash
    availability_evidence_hash: SHA256Hash
    expected_inventory_hash: SHA256Hash | None = None
    completeness_pass: bool
    collector_id: str
    received_at: datetime
    receipt_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        expected = truth_intake_receipt_hash(self)
        if self.receipt_hash != expected:
            raise ValueError(
                f"receipt hash mismatch: expected {expected}, got {self.receipt_hash}"
            )
        return self


class TruthEvidenceEntryV1(FrozenModel):
    """Entry binding a verified truth artifact with rights and availability."""

    schema_version: str = "1"
    publisher_id: str
    artifact_hash: SHA256Hash
    intake_receipt_hash: SHA256Hash
    origin_evidence_hash: SHA256Hash
    availability_evidence_hash: SHA256Hash
    rights_binding_hash: SHA256Hash
    is_retained: bool
    independence_declaration: str
    evidence_entry_hash: SHA256Hash


def truth_extraction_decision_hash(decision: TruthExtractionDecisionV1) -> SHA256Hash:
    dump = decision.model_dump(mode="python")
    dump.pop("decision_hash", None)
    return content_hash(dump)


class TruthExtractionDecisionV1(FrozenModel):
    """Adjudicated or primary-extracted value from truth bytes."""

    schema_version: str = "1"
    decision_id: UUID
    input_byte_hash: SHA256Hash
    locator: str
    method: TruthExtractionMethod
    canonical_extracted_value: Any
    temporal_precision: str
    adjudicator_id: str
    policy_hash: SHA256Hash
    decided_at: datetime
    decision_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        expected = truth_extraction_decision_hash(self)
        if self.decision_hash != expected:
            raise ValueError(
                f"decision hash mismatch: expected {expected}, got {self.decision_hash}"
            )
        return self


def independent_truth_claim_hash(claim: IndependentTruthClaimV1) -> SHA256Hash:
    dump = claim.model_dump(mode="python")
    dump.pop("claim_hash", None)
    return content_hash(dump)


class IndependentTruthClaimV1(FrozenModel):
    """Typed ground truth claim bound to its extraction decision."""

    schema_version: str = "1"
    claim_id: str
    subject_id: str
    claim_kind: str
    canonical_value: Any
    temporal_lower_bound: datetime
    temporal_upper_bound: datetime
    evidence_hashes: tuple[SHA256Hash, ...]
    extraction_decision_hash: SHA256Hash
    limitations: tuple[str, ...] = ()
    claim_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        expected = independent_truth_claim_hash(self)
        if self.claim_hash != expected:
            raise ValueError(
                f"claim hash mismatch: expected {expected}, got {self.claim_hash}"
            )
        return self

    @classmethod
    def create_and_validate(
        cls,
        claim_id: str,
        subject_id: str,
        claim_kind: str,
        canonical_value: Any,
        temporal_lower_bound: datetime,
        temporal_upper_bound: datetime,
        evidence_hashes: tuple[SHA256Hash, ...],
        extraction_decision: TruthExtractionDecisionV1,
        limitations: tuple[str, ...] = (),
    ) -> Self:
        """Construct truth claim and verify exact value agreement with decision."""
        if canonical_value != extraction_decision.canonical_extracted_value:
            expected_val = extraction_decision.canonical_extracted_value
            raise ValueError(
                f"claim value must match extraction decision: "
                f"expected {expected_val}, got {canonical_value}"
            )
        unhashed = cls.model_construct(
            schema_version="1",
            claim_id=claim_id,
            subject_id=subject_id,
            claim_kind=claim_kind,
            canonical_value=canonical_value,
            temporal_lower_bound=temporal_lower_bound,
            temporal_upper_bound=temporal_upper_bound,
            evidence_hashes=evidence_hashes,
            extraction_decision_hash=extraction_decision.decision_hash,
            limitations=limitations,
            claim_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"claim_hash": independent_truth_claim_hash(unhashed)}
        )


class TruthClaimSelectorV1(FrozenModel):
    truth_claim_id: str
    value_kind: str


class GoldenCasePredicateV1(FrozenModel):
    """One verifiable invariant predicate in a golden case."""

    predicate_id: str
    operator: PredicateOperator
    candidate_field: str
    expected_constant: Any | None = None
    truth_selector: TruthClaimSelectorV1 | None = None
    is_required: bool = True
    affected_dimension: QualificationDimension
    predicate_semantic_hash: SHA256Hash | None = None


def golden_case_definition_hash(definition: GoldenCaseDefinitionV1) -> SHA256Hash:
    dump = definition.model_dump(mode="python")
    dump.pop("definition_hash", None)
    return content_hash(dump)


class GoldenCaseDefinitionV1(FrozenModel):
    """Specification of an invariant test case and its required evidence."""

    case_id: GoldenCaseId
    case_version: str = "1"
    invariant_description: str
    required_evidence_kinds: tuple[str, ...]
    predicates: tuple[GoldenCasePredicateV1, ...]
    dimensions: tuple[QualificationDimension, ...]
    definition_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        expected = golden_case_definition_hash(self)
        if self.definition_hash != expected:
            raise ValueError(
                f"definition hash mismatch: expected {expected}, "
                f"got {self.definition_hash}"
            )
        return self


class GoldenCaseInstanceV1(FrozenModel):
    """Specific real-world entity or event instance bound to a case definition."""

    instance_id: UUID
    case_id: GoldenCaseId
    subject_id: str
    event_id: str
    target_fields: tuple[str, ...]
    truth_claim_ids: tuple[str, ...]
    definition_hash: SHA256Hash
    substitute_for_id: str | None = None


def golden_case_instance_manifest_hash(
    manifest: GoldenCaseInstanceManifestV1,
) -> SHA256Hash:
    dump = manifest.model_dump(mode="python")
    dump.pop("manifest_hash", None)
    return content_hash(dump)


class GoldenCaseInstanceManifestV1(FrozenModel):
    """Pre-acquisition frozen manifest containing all 18 instances."""

    schema_version: str = "1"
    instances: tuple[GoldenCaseInstanceV1, ...]
    selection_evidence_hash: SHA256Hash
    frozen_at: datetime
    manifest_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        expected = golden_case_instance_manifest_hash(self)
        if self.manifest_hash != expected:
            raise ValueError(
                f"manifest hash mismatch: expected {expected}, got {self.manifest_hash}"
            )
        if len(self.instances) != 18:
            raise ValueError(
                f"manifest requires exactly 18 instances, got {len(self.instances)}"
            )
        return self


class CandidateClaimSelectorSpecV1(FrozenModel):
    schema_version: str = "1"
    dataset_role: str
    subject_criteria: str
    target_field_id: str
    required_cardinality: int
    selection_policy_hash: SHA256Hash
    selector_hash: SHA256Hash


class CandidateClaimBindingV1(FrozenModel):
    schema_version: str = "1"
    selector_spec_hash: SHA256Hash
    matched_record_hashes: tuple[SHA256Hash, ...]
    emitted_mapping_hashes: tuple[SHA256Hash, ...]
    coverage_evidence_hash: SHA256Hash
    binding_policy_hash: SHA256Hash
    binding_hash: SHA256Hash


class GoldenCasePlanV1(FrozenModel):
    """Post-mapping execution plan for grading a golden case."""

    definition: GoldenCaseDefinitionV1
    instance: GoldenCaseInstanceV1
    profile_hash: SHA256Hash
    target_hash: SHA256Hash
    candidate_bindings: tuple[CandidateClaimBindingV1, ...]
    truth_claims: tuple[IndependentTruthClaimV1, ...]
    evidence_entries: tuple[TruthEvidenceEntryV1, ...]


class PredicateResultV1(FrozenModel):
    predicate_id: str
    evaluation: PredicateEvaluation
    compared_candidate_value: str | None = None
    compared_truth_value: str | None = None
    explanation: str | None = None


def golden_case_result_hash(result: GoldenCaseResultV1) -> SHA256Hash:
    dump = result.model_dump(mode="python")
    dump.pop("result_hash", None)
    return content_hash(dump)


class GoldenCaseResultV1(FrozenModel):
    schema_version: str = "1"
    case_id: GoldenCaseId
    reachability: GoldenCaseReachability
    status: GoldenCaseStatus
    predicate_results: tuple[PredicateResultV1, ...]
    compared_claim_hashes: tuple[SHA256Hash, ...]
    evidence_hashes: tuple[SHA256Hash, ...]
    policy_hashes: tuple[SHA256Hash, ...]
    limitations: tuple[str, ...] = ()
    result_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        expected = golden_case_result_hash(self)
        if self.result_hash != expected:
            raise ValueError(
                f"result hash mismatch: expected {expected}, got {self.result_hash}"
            )
        return self


def _to_comparable_instant(val: Any) -> datetime | None:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=UTC)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            try:
                d = date.fromisoformat(val)
                return datetime(d.year, d.month, d.day, tzinfo=UTC)
            except ValueError:
                return None
    return None


def _to_ratio_tuple(val: Any) -> tuple[int, int] | None:
    from math import gcd

    if isinstance(val, (tuple, list)) and len(val) == 2:
        try:
            n, d = int(val[0]), int(val[1])
            if n > 0 and d > 0:
                g = gcd(n, d)
                return (n // g, d // g)
        except ValueError, TypeError:
            return None
    elif hasattr(val, "numerator") and hasattr(val, "denominator"):
        try:
            n, d = int(val.numerator), int(val.denominator)
            if n > 0 and d > 0:
                g = gcd(n, d)
                return (n // g, d // g)
        except ValueError, TypeError:
            return None
    return None


def _to_identity_key(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, UUID):
        return str(val)
    if hasattr(val, "identity_id"):
        return str(val.identity_id)
    if hasattr(val, "security_id"):
        return str(val.security_id)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def evaluate_predicate(
    predicate: GoldenCasePredicateV1,
    candidate_value: Any,
    truth_value: Any = None,
    *,
    coverage_pass: bool = False,
) -> PredicateResultV1:
    """Evaluate one golden case predicate using closed predicate semantics."""
    target_comparison = (
        predicate.expected_constant
        if predicate.expected_constant is not None
        else truth_value
    )

    op = predicate.operator

    if candidate_value is None:
        if op == PredicateOperator.REQUIRED_ABSENT:
            if coverage_pass:
                return PredicateResultV1(
                    predicate_id=predicate.predicate_id,
                    evaluation=PredicateEvaluation.TRUE,
                    compared_candidate_value=str(candidate_value),
                    compared_truth_value=str(target_comparison),
                    explanation="Candidate value is absent under passing coverage",
                )
            return PredicateResultV1(
                predicate_id=predicate.predicate_id,
                evaluation=PredicateEvaluation.UNKNOWN,
                compared_candidate_value=str(candidate_value),
                compared_truth_value=str(target_comparison),
                explanation="Candidate absence requires passing coverage evidence",
            )
        elif op == PredicateOperator.REQUIRED_PRESENT:
            if coverage_pass:
                return PredicateResultV1(
                    predicate_id=predicate.predicate_id,
                    evaluation=PredicateEvaluation.FALSE,
                    compared_candidate_value=str(candidate_value),
                    compared_truth_value=str(target_comparison),
                    explanation="Required value absent under complete coverage",
                )
            return PredicateResultV1(
                predicate_id=predicate.predicate_id,
                evaluation=PredicateEvaluation.UNKNOWN,
                compared_candidate_value=str(candidate_value),
                compared_truth_value=str(target_comparison),
                explanation="Candidate value is unavailable",
            )
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.UNKNOWN,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
            explanation="Candidate value is unavailable",
        )

    # If target_comparison is required by the operator but is None:
    if target_comparison is None and op not in {
        PredicateOperator.REQUIRED_PRESENT,
        PredicateOperator.REQUIRED_ABSENT,
    }:
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.UNKNOWN,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
            explanation="Target comparison operand is unavailable",
        )

    if op == PredicateOperator.EQUAL:
        matched = candidate_value == target_comparison
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE
            if matched
            else PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )
    elif op == PredicateOperator.NOT_EQUAL:
        matched = candidate_value != target_comparison
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE
            if matched
            else PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )
    elif op in {PredicateOperator.SAME_IDENTITY, PredicateOperator.DISTINCT_IDENTITY}:
        id1 = _to_identity_key(candidate_value)
        id2 = _to_identity_key(target_comparison)
        if id1 is None or id2 is None:
            return PredicateResultV1(
                predicate_id=predicate.predicate_id,
                evaluation=PredicateEvaluation.UNKNOWN,
                compared_candidate_value=str(candidate_value),
                compared_truth_value=str(target_comparison),
                explanation="Identity operand is unavailable or invalid",
            )
        is_same = id1 == id2
        eval_res = is_same if op == PredicateOperator.SAME_IDENTITY else not is_same
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE
            if eval_res
            else PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )
    elif op == PredicateOperator.EXACT_RATIO:
        r1 = _to_ratio_tuple(candidate_value)
        r2 = _to_ratio_tuple(target_comparison)
        if r1 is None or r2 is None:
            return PredicateResultV1(
                predicate_id=predicate.predicate_id,
                evaluation=PredicateEvaluation.UNKNOWN,
                compared_candidate_value=str(candidate_value),
                compared_truth_value=str(target_comparison),
                explanation="Non-ratio or invalid ratio value",
            )
        matched = r1 == r2
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE
            if matched
            else PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )
    elif op == PredicateOperator.ORDERED_BEFORE:
        t1 = _to_comparable_instant(candidate_value)
        t2 = _to_comparable_instant(target_comparison)
        if t1 is not None and t2 is not None:
            matched = t1 < t2
            return PredicateResultV1(
                predicate_id=predicate.predicate_id,
                evaluation=PredicateEvaluation.TRUE
                if matched
                else PredicateEvaluation.FALSE,
                compared_candidate_value=str(candidate_value),
                compared_truth_value=str(target_comparison),
            )
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.UNKNOWN,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
            explanation="Uncomparable types or invalid dates for ordering",
        )
    elif op == PredicateOperator.REQUIRED_PRESENT:
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )
    elif op == PredicateOperator.REQUIRED_ABSENT:
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
            explanation="Candidate value is present when required absent",
        )
    elif op == PredicateOperator.PROHIBITED_INFERENCE:
        matched = candidate_value != target_comparison
        return PredicateResultV1(
            predicate_id=predicate.predicate_id,
            evaluation=PredicateEvaluation.TRUE
            if matched
            else PredicateEvaluation.FALSE,
            compared_candidate_value=str(candidate_value),
            compared_truth_value=str(target_comparison),
        )

    return PredicateResultV1(
        predicate_id=predicate.predicate_id,
        evaluation=PredicateEvaluation.UNKNOWN,
        compared_candidate_value=str(candidate_value),
        compared_truth_value=str(target_comparison),
    )


def _build_definitions() -> Mapping[GoldenCaseId, GoldenCaseDefinitionV1]:
    """Instantiate the 18 closed Drift M1e golden case definitions."""
    definitions: dict[GoldenCaseId, GoldenCaseDefinitionV1] = {}
    cases_meta = [
        (
            GoldenCaseId.G01,
            "FB to META name and ticker continuity with unchanged CUSIP",
            ("sec_filing", "exchange_notice"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.UNIVERSE_LIFECYCLE,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G01-P1",
                    operator=PredicateOperator.SAME_IDENTITY,
                    candidate_field="security_id",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G01-IDENTITY",
                        value_kind="security_id",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
        (
            GoldenCaseId.G02,
            "Roundhill META/METV ticker collision does not join securities",
            ("issuer_record", "sec_filing", "exchange_notice"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.UNIVERSE_LIFECYCLE,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G02-P1",
                    operator=PredicateOperator.DISTINCT_IDENTITY,
                    candidate_field="security_id",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G02-ROUNDHILL-IDENTITY",
                        value_kind="security_id",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
        (
            GoldenCaseId.G03,
            "Linde primary listing changes NYSE to Nasdaq without new security",
            ("form_8k", "exchange_transfer_record"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G03-P1",
                    operator=PredicateOperator.SAME_IDENTITY,
                    candidate_field="security_id",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G03-IDENTITY",
                        value_kind="security_id",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
        (
            GoldenCaseId.G04,
            "Listing termination is distinct from claim extinction",
            ("sec_form_25", "finra_daily_list"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.UNIVERSE_LIFECYCLE,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G04-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="reason",
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
        (
            GoldenCaseId.G05,
            "NVIDIA 10-for-1 forward split exact terms and ratio",
            ("form_8k", "exchange_action_record"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.OCCURRED_EFFECTS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G05-P1",
                    operator=PredicateOperator.EXACT_RATIO,
                    candidate_field="ratio",
                    expected_constant=(10, 1),
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G06,
            "GE 1-for-8 reverse split exact ratio and session mapping",
            ("sec_filing", "exchange_notice"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.OCCURRED_EFFECTS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G06-P1",
                    operator=PredicateOperator.EXACT_RATIO,
                    candidate_field="ratio",
                    expected_constant=(1, 8),
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G07,
            "Ordinary dividend ex, record, and payable dates remain distinct",
            ("issuer_ir_release", "exchange_ex_date_record"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G07-P1",
                    operator=PredicateOperator.ORDERED_BEFORE,
                    candidate_field="ex_date",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G07-PAYABLE-DATE",
                        value_kind="payable_date",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G08,
            "Special distribution due-bill period is preserved without fallback",
            ("finra_upc_notice", "nasdaq_daily_list"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G08-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="due_bill_indicator",
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G09,
            "Twitter/X cash merger terms and delisting remain separate facts",
            ("merger_agreement", "closing_8k", "nyse_notice"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G09-P1",
                    operator=PredicateOperator.EQUAL,
                    candidate_field="action_kind",
                    expected_constant="cash_acquisition",
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G10,
            "Mixed merger consideration components and successor continuity",
            ("form_s4", "closing_filing"),
            (
                QualificationDimension.CORPORATE_ACTION_TERMS,
                QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G10-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="components",
                    is_required=True,
                    affected_dimension=QualificationDimension.CORPORATE_ACTION_TERMS,
                ),
            ),
        ),
        (
            GoldenCaseId.G11,
            "GE Vernova spinoff parent continuity and new security claim",
            ("information_statement", "exchange_notice"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.CORPORATE_ACTION_TERMS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G11-P1",
                    operator=PredicateOperator.DISTINCT_IDENTITY,
                    candidate_field="spinoff_security_id",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G11-PARENT-IDENTITY",
                        value_kind="security_id",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
        (
            GoldenCaseId.G12,
            "BBBY bankruptcy, delisting, cancellation, and unknown recovery",
            ("court_filing", "form_25", "finra_notice"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.CORPORATE_ACTION_TERMS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G12-P1",
                    operator=PredicateOperator.EQUAL,
                    candidate_field="reason",
                    expected_constant="bankruptcy_cancellation",
                    is_required=True,
                    affected_dimension=QualificationDimension.SETTLEMENTS_TERMINAL_OUTCOMES,
                ),
            ),
        ),
        (
            GoldenCaseId.G13,
            "Old and corrected corporate action versions point-in-time selection",
            ("provider_correction_notice", "issuer_exchange_truth"),
            (
                QualificationDimension.REVISIONS_POINT_IN_TIME,
                QualificationDimension.CORPORATE_ACTION_TERMS,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G13-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="revision",
                    is_required=True,
                    affected_dimension=QualificationDimension.REVISIONS_POINT_IN_TIME,
                ),
            ),
        ),
        (
            GoldenCaseId.G14,
            "Daily aggregate correction versions point-in-time selection",
            ("corrected_receipts", "eligible_trade_reconstruction"),
            (
                QualificationDimension.REVISIONS_POINT_IN_TIME,
                QualificationDimension.OBSERVATIONS_METHODOLOGIES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G14-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="revision",
                    is_required=True,
                    affected_dimension=QualificationDimension.REVISIONS_POINT_IN_TIME,
                ),
            ),
        ),
        (
            GoldenCaseId.G15,
            "Early close session schedule and realization agreement",
            ("exchange_calendar", "first_party_trade_evidence"),
            (
                QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                QualificationDimension.OBSERVATIONS_METHODOLOGIES,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G15-P1",
                    operator=PredicateOperator.EQUAL,
                    candidate_field="is_early_close",
                    expected_constant=True,
                    is_required=True,
                    affected_dimension=QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                ),
            ),
        ),
        (
            GoldenCaseId.G16,
            "2018-12-05 national day of mourning explicit closure",
            ("exchange_closure_notice", "sec_exchange_records"),
            (
                QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                QualificationDimension.COVERAGE_OMISSION,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G16-P1",
                    operator=PredicateOperator.EQUAL,
                    candidate_field="is_open",
                    expected_constant=False,
                    is_required=True,
                    affected_dimension=QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                ),
            ),
        ),
        (
            GoldenCaseId.G17,
            "Trading halt/suspension versus omission and no-trade",
            ("exchange_halt_status", "raw_eligible_trades"),
            (
                QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                QualificationDimension.COVERAGE_OMISSION,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G17-P1",
                    operator=PredicateOperator.REQUIRED_PRESENT,
                    candidate_field="reason",
                    is_required=True,
                    affected_dimension=QualificationDimension.SCHEDULED_REALIZED_SESSIONS,
                ),
            ),
        ),
        (
            GoldenCaseId.G18,
            "Berkshire Class A and Class B share distinction under normalization",
            ("issuer_filing", "exchange_security_master"),
            (
                QualificationDimension.SECURITY_LISTING_IDENTITY,
                QualificationDimension.UNIVERSE_LIFECYCLE,
            ),
            (
                GoldenCasePredicateV1(
                    predicate_id="G18-P1",
                    operator=PredicateOperator.DISTINCT_IDENTITY,
                    candidate_field="security_id",
                    truth_selector=TruthClaimSelectorV1(
                        truth_claim_id="TRUTH-G18-BRK-B-IDENTITY",
                        value_kind="security_id",
                    ),
                    is_required=True,
                    affected_dimension=QualificationDimension.SECURITY_LISTING_IDENTITY,
                ),
            ),
        ),
    ]

    for gid, desc, req_ev, dims, preds in cases_meta:
        unhashed = GoldenCaseDefinitionV1.model_construct(
            case_id=gid,
            case_version="1",
            invariant_description=desc,
            required_evidence_kinds=req_ev,
            predicates=preds,
            dimensions=dims,
            definition_hash="0" * 64,
        )
        definitions[gid] = unhashed.model_copy(
            update={"definition_hash": golden_case_definition_hash(unhashed)}
        )
    return definitions


ALL_GOLDEN_CASE_DEFINITIONS: Mapping[GoldenCaseId, GoldenCaseDefinitionV1] = (
    _build_definitions()
)
