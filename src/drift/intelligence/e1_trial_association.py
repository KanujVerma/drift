"""Candidate E6B research/E1 association over accepted public source records.

This module deliberately DOES NOT issue scheduler grants, authenticate Matthew's
opening book, or return a scientific trial admission. The #507 local producer
receipt and all checks remain gated on original independent issuer evidence.
No existing K1/E1 record or hash preimage is changed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Sequence, cast

from pydantic import BaseModel

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CostReceipt,
    ModelReplayRecord,
    ResearchCandidate,
    ResearchContext,
    StoredArtifactRef,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import ValidationResult
from drift.serialization.canonical import content_hash

VALIDATION_CANDIDATE_PROFILE = "drift-research-validation-e1/1-candidate"
ASSOCIATION_CANDIDATE_PROFILE = "drift-research-e1-association/1-candidate"
VALIDATION_STATUSES = frozenset({"VALID", "INVALID", "REJECTED", "REFUSED"})


@dataclass(frozen=True, slots=True)
class RetainedValidationCandidateV1:
    """A proposed original validation index, not a trusted issuer capability.

    The original raw output, validator's decision and exact retained canonical
    bytes must be verified from their *real* issuers before scientific use.
    """

    profile: str
    validation_id: str
    attempt_id: str
    status: str
    reason: str
    candidate_ref: ArtifactReference | None
    raw_output_ref: StoredArtifactRef | None
    original_validation_ref: StoredArtifactRef
    validator_issuer_ref: ArtifactReference
    first_available_at: datetime
    record_hash: str


@dataclass(frozen=True, slots=True)
class ResearchE1BindingReview:
    """One local source-consistency assessment; never E6B authorization."""

    structural_consistency: bool
    candidate_association_hash: str | None
    observed_disposition: str | None
    included_cost_receipt_hashes: tuple[str, ...]
    late_cost_receipt_ids: tuple[str, ...]
    source_refusal_reasons: tuple[str, ...]
    missing_trusted_producers: tuple[str, ...]

    @property
    def original_issuer_verified(self) -> bool:
        return False

    @property
    def admitted_for_e6b_or_trading(self) -> bool:
        return False


def _utc(value: datetime, field: str) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field}: UTC instant required")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field}: non-UTC timestamp")


def _model_copy[T: BaseModel](cls: type[T], value: object, field: str) -> T:
    """Reparse exact accepted K1 model through its original validation rules."""
    if type(value) is not cls:
        raise ValueError(f"{field}: wrong accepted original class")
    original = cast(T, value)
    return cls.model_validate(original.model_dump(mode="python"))


def _retained_preimage(record: RetainedValidationCandidateV1) -> dict[str, object]:
    return {
        "profile": record.profile,
        "validation_id": record.validation_id,
        "attempt_id": record.attempt_id,
        "status": record.status,
        "reason": record.reason,
        "candidate_ref": record.candidate_ref,
        "raw_output_ref": record.raw_output_ref,
        "original_validation_ref": record.original_validation_ref,
        "validator_issuer_ref": record.validator_issuer_ref,
        "first_available_at": record.first_available_at,
    }


def build_retained_validation_candidate(
    *,
    validation_id: str,
    attempt_id: str,
    original_validation: ValidationResult,
    raw_output_ref: StoredArtifactRef | None,
    original_validation_ref: StoredArtifactRef,
    validator_issuer_ref: ArtifactReference,
    first_available_at: datetime,
) -> RetainedValidationCandidateV1:
    """Bind the actual K1 ValidationResult to an externally stored-byte claim.

    This function does not write raw bytes or authenticate an issuer. It checks
    that the claimed retained canonical decision hash matches the original
    revalidated validation result. Caller claims alone cannot satisfy #507.
    """
    validation = _model_copy(ValidationResult, original_validation, "validation")
    raw = (
        None if raw_output_ref is None
        else _model_copy(StoredArtifactRef, raw_output_ref, "raw_output_ref")
    )
    original = _model_copy(
        StoredArtifactRef, original_validation_ref, "original_validation_ref"
    )
    issuer = _model_copy(
        ArtifactReference, validator_issuer_ref, "validator_issuer_ref"
    )
    _utc(first_available_at, "first_available_at")
    if not validation_id or type(validation_id) is not str:
        raise ValueError("validation_id: missing")
    if not attempt_id or type(attempt_id) is not str:
        raise ValueError("attempt_id: missing")
    if validation.status not in VALIDATION_STATUSES:
        raise ValueError("validation_status: unsupported")
    if not validation.reason:
        raise ValueError("validation_reason: missing")
    if validation.status == "VALID":
        if validation.is_valid is not True or validation.candidate is None:
            raise ValueError("VALID_REQUIRES_ORIGINAL_CANDIDATE")
        if raw is None:
            raise ValueError("VALIDATION_RAW_OUTPUT_NOT_RETAINED")
    elif validation.is_valid is not False or validation.candidate is not None:
        raise ValueError("FAILURE_CANNOT_CARRY_CANDIDATE")
    candidate = validation.candidate
    if candidate is not None and candidate.attempt_id != attempt_id:
        raise ValueError("VALIDATION_ATTEMPT_MISMATCH")
    expected_decision_digest = content_hash(validation.model_dump(mode="python"))
    if original.content_hash != expected_decision_digest:
        raise ValueError("ORIGINAL_VALIDATION_BYTES_HASH_MISMATCH")
    candidate_ref = (
        ArtifactReference(
            id=candidate.candidate_id,
            version="drift-research/1-draft",
            sha256=candidate.record_hash,
        )
        if candidate is not None else None
    )
    preliminary = RetainedValidationCandidateV1(
        profile=VALIDATION_CANDIDATE_PROFILE,
        validation_id=validation_id,
        attempt_id=attempt_id,
        status=validation.status,
        reason=validation.reason,
        candidate_ref=candidate_ref,
        raw_output_ref=raw,
        original_validation_ref=original,
        validator_issuer_ref=issuer,
        first_available_at=first_available_at,
        record_hash="",
    )
    return replace(
        preliminary,
        record_hash=content_hash(_retained_preimage(preliminary)),
    )


def _ref(
    ref: ArtifactReference | None,
    key: str,
    digest: str,
    *,
    version: str | None = None,
) -> bool:
    return (
        type(ref) is ArtifactReference
        and ref.id == key
        and ref.sha256 == digest
        and (version is None or ref.version == version)
    )


def _problem(reasons: list[str], name: str, condition: bool) -> None:
    if not condition:
        reasons.append(name)


def review_research_e1_binding(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    provenance: Stage1TrialProvenanceSnapshotV1,
    context: ResearchContext,
    started: AttemptRecord,
    terminal: AttemptRecord,
    validation: ValidationResult | None,
    retained_validation: RetainedValidationCandidateV1 | None,
    candidate: ResearchCandidate | None,
    replay: ModelReplayRecord | None,
    costs: Sequence[CostReceipt],
    logical_request_id: str,
    decision_deadline: datetime,
    association_first_available_at: datetime,
) -> ResearchE1BindingReview:
    """Check the accepted original source records, never issue a trusted grant.

    The full E1 snapshot is verified against one captured collection view.
    Account allocation, scheduler grant and validator-original issuer proof
    still require separately accepted, original producer verifiers.
    """
    reasons: list[str] = []
    blocked = (
        "MISSING_MATTHEW_ORIGINAL_ACCOUNT_ISSUER_508",
        "MISSING_KANUJ_ORIGINAL_SCHEDULER_ISSUER_512",
        "MISSING_KRISH_ORIGINAL_VALIDATION_RETENTION_507",
        "INDEPENDENT_E1_PROVENANCE_511_ACCEPTANCE_REQUIRED",
    )
    try:
        captured_arms = tuple(arms)
        captured_bindings = tuple(bindings)
        captured_runs = tuple(expected_run_ids)
        if (
            type(provenance) is not Stage1TrialProvenanceSnapshotV1
            or type(campaign) is not CampaignSpecV1
        ):
            raise ValueError("INVALID_ORIGINAL_E1_TYPES")
        verify_stage1_trial_provenance_snapshot(
            snapshot=provenance,
            campaign=campaign,
            arms=captured_arms,
            bindings=captured_bindings,
            expected_run_ids=captured_runs,
        )
    except (ValueError, TypeError, AttributeError) as error:
        return ResearchE1BindingReview(
            False, None, None, (), (),
            (f"E1_MANIFEST_OR_PROVENANCE_INVALID:{type(error).__name__}",),
            blocked,
        )
    try:
        ctx = _model_copy(ResearchContext, context, "context")
        initial = _model_copy(AttemptRecord, started, "started")
        final = _model_copy(AttemptRecord, terminal, "terminal")
        decision = (
            None if validation is None
            else _model_copy(ValidationResult, validation, "validation")
        )
        choice = (
            None if candidate is None
            else _model_copy(ResearchCandidate, candidate, "candidate")
        )
        model = (
            None if replay is None
            else _model_copy(ModelReplayRecord, replay, "replay")
        )
        cost_records = tuple(
            _model_copy(CostReceipt, c, f"cost[{i}]")
            for i, c in enumerate(costs)
        )
        _utc(decision_deadline, "decision_deadline")
        _utc(association_first_available_at, "association_first_available_at")
    except (ValueError, TypeError, AttributeError) as error:
        return ResearchE1BindingReview(
            False, None, None, (), (),
            (f"K1_SOURCE_OR_TIMESTAMP_INVALID:{type(error).__name__}",),
            blocked,
        )

    e1 = provenance.scope
    binding = e1.run_account_binding
    _problem(reasons, "E1_SCOPE_WRONG_ACCOUNT",
             ctx.scope.account_id == binding.portfolio_account_id)
    _problem(reasons, "E1_SCOPE_WRONG_ARM", ctx.scope.arm_id == e1.arm_id)
    _problem(reasons, "E1_CAMPAIGN_REF_MISMATCH",
             ctx.scope.campaign_ref.sha256 == e1.campaign_spec_fingerprint)
    _problem(reasons, "BAD_CONTEXT_ORIGINAL_AVAILABILITY",
             ctx.decision_cutoff <= ctx.built_at <= ctx.review_started_at)
    _problem(reasons, "BAD_REVIEW_ATTEMPT_ORDER",
             ctx.review_started_at <= cast(datetime, initial.started_at))
    _problem(reasons, "INVALID_DECISION_DEADLINE",
             ctx.decision_cutoff <= decision_deadline)
    _problem(reasons, "TERMINAL_AFTER_DECISION_DEADLINE",
             final.completed_at is not None
             and final.completed_at <= decision_deadline)
    _problem(reasons, "ASSOCIATION_PRECEDES_TERMINAL",
             final.completed_at is not None
             and association_first_available_at >= final.completed_at)

    _problem(reasons, "MISSING_REQUEST_ID",
             type(logical_request_id) is str and bool(logical_request_id))
    _problem(reasons, "WRONG_LOGICAL_REQUEST",
             initial.logical_request_id == logical_request_id
             and final.logical_request_id == logical_request_id)
    _problem(reasons, "ATTEMPT_IDENTITY_OR_ORDER",
             initial.status == "started" and initial.event_index == 0
             and final.status in ("completed", "failed", "rejected")
             and final.event_index == 1
             and initial.attempt_id == final.attempt_id
             and initial.started_at == final.started_at
             and initial.completed_at is None)
    _problem(reasons, "ATTEMPT_ORIGINAL_BACKLINK_INVALID",
             _ref(final.previous_event_ref, initial.attempt_event_id,
                  initial.record_hash, version="v1"))
    _problem(reasons, "ATTEMPT_CONTEXT_OR_SCOPE_MISMATCH",
             initial.scope == ctx.scope and final.scope == ctx.scope
             and _ref(initial.context_ref, ctx.context_id, ctx.record_hash)
             and _ref(final.context_ref, ctx.context_id, ctx.record_hash))
    _problem(reasons, "ATTEMPT_METHOD_OR_BUDGET_MISMATCH",
             initial.method_ref == ctx.method_ref
             and final.method_ref == ctx.method_ref
             and initial.budget_ref == ctx.budget_ref
             and final.budget_ref == ctx.budget_ref)
    _problem(reasons, "ATTEMPT_END_BEFORE_START",
             initial.started_at is not None and final.completed_at is not None
             and initial.started_at <= final.completed_at)

    if choice is not None:
        _problem(reasons, "ORPHAN_OR_CROSS_SCOPE_CANDIDATE",
                 choice.attempt_id == initial.attempt_id
                 and choice.scope == ctx.scope
                 and _ref(choice.context_ref, ctx.context_id, ctx.record_hash)
                 and choice.method_ref == ctx.method_ref
                 and choice.portfolio_ref == ctx.portfolio_ref
                 and choice.mandate_ref == ctx.mandate_ref
                 and choice.universe_ref == ctx.universe_ref
                 and choice.registry_ref == ctx.registry_ref
                 and _ref(final.candidate_ref, choice.candidate_id,
                          choice.record_hash))
        _problem(reasons, "CANDIDATE_OUTSIDE_TERMINAL",
                 initial.started_at is not None
                 and final.completed_at is not None
                 and initial.started_at <= choice.completed_at <= final.completed_at)
        if choice.valid_until is not None:
            _problem(reasons, "CANDIDATE_EXPIRED_BEFORE_TERMINAL",
                     final.completed_at is not None
                     and choice.valid_until >= final.completed_at)
        _problem(reasons, "CANDIDATE_COST_RECEIPT_SET_MISMATCH",
                 set(choice.cost_receipt_ids) == set(final.cost_receipt_ids))
        if choice.disposition == "hold":
            _problem(reasons, "HOLD_NO_RECORDED_INCUMBENT",
                     ctx.current_selection_ref is not None)
    else:
        _problem(reasons, "FAILED_ATTEMPT_MUST_NOT_MINT_CANDIDATE",
                 final.status in ("failed", "rejected")
                 and final.candidate_ref is None and bool(final.reason_codes))

    if final.status == "completed":
        _problem(reasons, "COMPLETED_ATTEMPT_WITHOUT_CANDIDATE",
                 choice is not None)
    if choice is not None and choice.disposition == "hold":
        blocked = (*blocked, "MISSING_VERIFIED_MATCHING_INCUMBENT_FOR_HOLD")
    elif choice is not None:
        reasons.append("FAILED_ATTEMPT_MUST_NOT_CARRY_CANDIDATE")

    if decision is None or retained_validation is None:
        if final.status == "completed" or choice is not None:
            reasons.append("ORIGINAL_VALIDATION_MISSING")
        elif not (
            final.failure_artifact_ref is not None
            and final.reason_codes
        ):
            reasons.append("FAILED_ATTEMPT_NO_ORIGINAL_FAILURE_EVIDENCE")
    else:
        try:
            if type(retained_validation) is not RetainedValidationCandidateV1:
                raise ValueError("validation receipt class mismatch")
            _utc(retained_validation.first_available_at,
                 "retained_validation.first_available_at")
            expected_hash = content_hash(
                _retained_preimage(retained_validation)
            )
            if expected_hash != retained_validation.record_hash:
                raise ValueError("retained validation candidate hash invalid")
            reconstructed = build_retained_validation_candidate(
                validation_id=retained_validation.validation_id,
                attempt_id=retained_validation.attempt_id,
                original_validation=decision,
                raw_output_ref=retained_validation.raw_output_ref,
                original_validation_ref=retained_validation.original_validation_ref,
                validator_issuer_ref=retained_validation.validator_issuer_ref,
                first_available_at=retained_validation.first_available_at,
            )
            if reconstructed != retained_validation:
                raise ValueError("retained validation original mismatch")
        except (ValueError, TypeError, AttributeError):
            reasons.append("INVALID_RETAINED_VALIDATION")
        else:
            _problem(reasons, "TERMINAL_VALIDATION_REF_MISMATCH",
                     _ref(final.validation_ref, retained_validation.validation_id,
                          retained_validation.record_hash))
            _problem(reasons, "VALIDATION_ATTEMPT_MISMATCH",
                     retained_validation.attempt_id == initial.attempt_id)
            _problem(reasons, "VALIDATION_STATUS_CANDIDATE_MISMATCH",
                     (decision.status == "VALID") == (choice is not None)
                     and ((choice is None and decision.candidate is None)
                          or (choice is not None
                              and decision.candidate is not None
                              and decision.candidate.record_hash
                              == choice.record_hash)))
            _problem(reasons, "VALIDATION_LATE_OR_EARLY",
                     initial.started_at is not None
                     and final.completed_at is not None
                     and initial.started_at
                     <= retained_validation.first_available_at
                     <= final.completed_at)

    if model is None:
        _problem(reasons, "UNEXPECTED_MODEL_REPLAY_REFERENCE",
                 final.model_replay_ref is None
                 and (choice is None or choice.model_replay_ref is None))
    else:
        _problem(reasons, "MODEL_REPLAY_WRONG_ATTEMPT_OR_SCOPE",
                 model.attempt_id == initial.attempt_id
                 and model.scope == ctx.scope
                 and _ref(model.context_ref, ctx.context_id, ctx.record_hash)
                 and model.method_ref == ctx.method_ref
                 and _ref(final.model_replay_ref, model.replay_id,
                          model.record_hash))
        _problem(reasons, "MODEL_REPLAY_CANDIDATE_MISMATCH",
                 choice is None or _ref(choice.model_replay_ref, model.replay_id,
                                        model.record_hash))
        if model.response_received_at is not None:
            _problem(reasons, "MODEL_RESPONSE_BEFORE_SEND",
                     model.request_sent_at <= model.response_received_at)
        if model.parse_completed_at is not None:
            _problem(reasons, "MODEL_PARSE_BEFORE_RESPONSE",
                     model.response_received_at is not None
                     and model.response_received_at <= model.parse_completed_at)
        _problem(reasons, "MODEL_CALL_OUTSIDE_ATTEMPT",
                 initial.started_at is not None
                 and final.completed_at is not None
                 and initial.started_at <= model.request_sent_at
                 and (model.parse_completed_at or model.response_received_at
                      or model.request_sent_at) <= final.completed_at)
        if retained_validation is not None:
            last_model_at = (
                model.parse_completed_at
                or model.response_received_at
                or model.request_sent_at
            )
            _problem(reasons, "MODEL_AFTER_VALIDATION",
                     last_model_at <= retained_validation.first_available_at)

    ids = [c.receipt_id for c in cost_records]
    _problem(reasons, "COST_RECEIPT_SET_MISMATCH",
             len(set(ids)) == len(ids)
             and set(ids) == set(final.cost_receipt_ids))
    store = ResearchReceiptStore()
    try:
        store.record_attempt(initial)
        store.record_attempt(final)
        for cost in cost_records:
            store.record_cost_receipt(cost)
    except ValueError:
        reasons.append("ORIGINAL_RECEIPT_STORE_REFUSAL")
    late_costs: list[str] = []
    included_cost_hashes: list[str] = []
    for cost in cost_records:
        _problem(reasons, "CROSS_ARM_OR_ATTEMPT_COST",
                 cost.scope == ctx.scope
                 and cost.attempt_id in (None, initial.attempt_id))
        if cost.recorded_at is None:
            reasons.append("COST_FIRST_AVAILABILITY_UNKNOWN")
        elif cost.recorded_at > association_first_available_at:
            late_costs.append(cost.receipt_id)
        else:
            included_cost_hashes.append(cost.record_hash)
    # An original cost correction can be retained, but a later correction
    # cannot be represented as already available in an earlier association.
    if reasons:
        return ResearchE1BindingReview(
            False, None,
            None if choice is None else choice.disposition,
            (), tuple(sorted(late_costs)), tuple(sorted(set(reasons))), blocked,
        )
    fingerprint = content_hash({
        "profile": ASSOCIATION_CANDIDATE_PROFILE,
        "campaign_id": e1.campaign_id,
        "run_id": e1.run_id,
        "arm_id": e1.arm_id,
        "checkpoint_id": e1.checkpoint_id,
        "trial_id": e1.trial_id,
        "snapshot_fingerprint": provenance.snapshot_fingerprint,
        "complete_manifest_fingerprint": e1.complete_manifest_fingerprint,
        "binding_id": binding.binding_id,
        "portfolio_account_id": binding.portfolio_account_id,
        "context_hash": ctx.record_hash,
        "started_attempt_hash": initial.record_hash,
        "terminal_attempt_hash": final.record_hash,
        "validation_candidate_hash": (
            None if retained_validation is None
            else retained_validation.record_hash
        ),
        "candidate_hash": None if choice is None else choice.record_hash,
        "model_replay_hash": None if model is None else model.record_hash,
        "cost_hashes_as_of": tuple(sorted(included_cost_hashes)),
        "cost_receipt_ids_late": tuple(sorted(late_costs)),
        "logical_request_id": logical_request_id,
        "decision_deadline": decision_deadline,
        "association_first_available_at": association_first_available_at,
    })
    return ResearchE1BindingReview(
        True, fingerprint,
        None if choice is None else choice.disposition,
        tuple(sorted(included_cost_hashes)),
        tuple(sorted(late_costs)), (), blocked,
    )
