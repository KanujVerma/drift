"""Candidate E6B research/E1 association over accepted public source records.

This module deliberately DOES NOT issue scheduler grants, authenticate Matthew's
opening book, or return a scientific trial admission. The #507 local producer
receipt and all checks remain gated on original independent issuer evidence.
No existing K1/E1 record or hash preimage is changed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from uuid import UUID

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
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.serialization.canonical import canonical_json, content_hash

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
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field}: UTC instant required")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field}: UTC instant required")


def _model_copy[T: BaseModel](cls: type[T], value: object, field: str) -> T:
    """Reparse exact accepted K1 model through its original validation rules."""
    if type(value) is not cls:
        raise ValueError(f"{field}: wrong accepted original class")
    original = value
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
        None
        if raw_output_ref is None
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
        if candidate is not None
        else None
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
    original_scheduler_grant_ref: ArtifactReference | None = None,
    original_account_provisioning_ref: ArtifactReference | None = None,
    local_validation_readback: LocalValidationReadback | None = None,
) -> ResearchE1BindingReview:
    """Check the accepted original source records, never issue a trusted grant.

    The full E1 snapshot is verified against one captured collection view.
    Account allocation, scheduler grant and validator-original issuer proof
    still require separately accepted, original producer verifiers.
    """
    reasons: list[str] = []
    blocked: tuple[str, ...] = (
        "MISSING_MATTHEW_ORIGINAL_ACCOUNT_ISSUER_508",
        "MISSING_KANUJ_ORIGINAL_SCHEDULER_ISSUER_512",
        "MISSING_KRISH_ORIGINAL_VALIDATION_RETENTION_507",
        "MISSING_KRISH_ORIGINAL_INPUT_AVAILABILITY_VERIFIER_507",
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
            False,
            None,
            None,
            (),
            (),
            (f"E1_MANIFEST_OR_PROVENANCE_INVALID:{type(error).__name__}",),
            blocked,
        )
    try:
        ctx = _model_copy(ResearchContext, context, "context")
        initial = _model_copy(AttemptRecord, started, "started")
        final = _model_copy(AttemptRecord, terminal, "terminal")
        decision = (
            None
            if validation is None
            else _model_copy(ValidationResult, validation, "validation")
        )
        choice = (
            None
            if candidate is None
            else _model_copy(ResearchCandidate, candidate, "candidate")
        )
        model = (
            None if replay is None else _model_copy(ModelReplayRecord, replay, "replay")
        )
        cost_records = tuple(
            _model_copy(CostReceipt, c, f"cost[{i}]") for i, c in enumerate(costs)
        )
        grant = (
            None
            if original_scheduler_grant_ref is None
            else _model_copy(
                ArtifactReference,
                original_scheduler_grant_ref,
                "original_scheduler_grant_ref",
            )
        )
        allocation = (
            None
            if original_account_provisioning_ref is None
            else _model_copy(
                ArtifactReference,
                original_account_provisioning_ref,
                "original_account_provisioning_ref",
            )
        )
        _utc(decision_deadline, "decision_deadline")
        _utc(association_first_available_at, "association_first_available_at")
    except (ValueError, TypeError, AttributeError) as error:
        return ResearchE1BindingReview(
            False,
            None,
            None,
            (),
            (),
            (f"K1_SOURCE_OR_TIMESTAMP_INVALID:{type(error).__name__}",),
            blocked,
        )

    e1 = provenance.scope
    binding = e1.run_account_binding
    _problem(
        reasons,
        "E1_SCOPE_WRONG_ACCOUNT",
        ctx.scope.account_id == binding.portfolio_account_id,
    )
    _problem(reasons, "E1_SCOPE_WRONG_ARM", ctx.scope.arm_id == e1.arm_id)
    _problem(
        reasons,
        "E1_CAMPAIGN_REF_MISMATCH",
        ctx.scope.campaign_ref.id == e1.campaign_id
        and ctx.scope.campaign_ref.sha256 == e1.campaign_spec_fingerprint,
    )
    _problem(
        reasons,
        "BAD_CONTEXT_ORIGINAL_AVAILABILITY",
        ctx.decision_cutoff <= ctx.built_at <= ctx.review_started_at,
    )
    _problem(
        reasons,
        "BAD_REVIEW_ATTEMPT_ORDER",
        ctx.review_started_at <= cast(datetime, initial.started_at),
    )
    _problem(
        reasons, "INVALID_DECISION_DEADLINE", ctx.decision_cutoff <= decision_deadline
    )
    _problem(
        reasons,
        "TERMINAL_AFTER_DECISION_DEADLINE",
        final.completed_at is not None and final.completed_at <= decision_deadline,
    )
    _problem(
        reasons,
        "ASSOCIATION_PRECEDES_TERMINAL",
        final.completed_at is not None
        and association_first_available_at >= final.completed_at,
    )

    _problem(
        reasons,
        "MISSING_REQUEST_ID",
        type(logical_request_id) is str and bool(logical_request_id),
    )
    _problem(
        reasons,
        "WRONG_LOGICAL_REQUEST",
        initial.logical_request_id == logical_request_id
        and final.logical_request_id == logical_request_id,
    )
    _problem(
        reasons,
        "ATTEMPT_IDENTITY_OR_ORDER",
        initial.status == "started"
        and initial.event_index == 0
        and final.status in ("completed", "failed", "rejected")
        and final.event_index == 1
        and initial.attempt_id == final.attempt_id
        and initial.started_at == final.started_at
        and initial.completed_at is None,
    )
    _problem(
        reasons,
        "ATTEMPT_ORIGINAL_BACKLINK_INVALID",
        _ref(
            final.previous_event_ref,
            initial.attempt_event_id,
            initial.record_hash,
            version="v1",
        ),
    )
    _problem(
        reasons,
        "ATTEMPT_CONTEXT_OR_SCOPE_MISMATCH",
        initial.scope == ctx.scope
        and final.scope == ctx.scope
        and _ref(initial.context_ref, ctx.context_id, ctx.record_hash)
        and _ref(final.context_ref, ctx.context_id, ctx.record_hash),
    )
    _problem(
        reasons,
        "ATTEMPT_METHOD_OR_BUDGET_MISMATCH",
        initial.method_ref == ctx.method_ref
        and final.method_ref == ctx.method_ref
        and initial.budget_ref == ctx.budget_ref
        and final.budget_ref == ctx.budget_ref,
    )
    _problem(
        reasons,
        "ATTEMPT_END_BEFORE_START",
        initial.started_at is not None
        and final.completed_at is not None
        and initial.started_at <= final.completed_at,
    )

    if choice is not None:
        _problem(
            reasons,
            "ORPHAN_OR_CROSS_SCOPE_CANDIDATE",
            choice.attempt_id == initial.attempt_id
            and choice.scope == ctx.scope
            and _ref(choice.context_ref, ctx.context_id, ctx.record_hash)
            and choice.method_ref == ctx.method_ref
            and choice.portfolio_ref == ctx.portfolio_ref
            and choice.mandate_ref == ctx.mandate_ref
            and choice.universe_ref == ctx.universe_ref
            and choice.registry_ref == ctx.registry_ref
            and _ref(final.candidate_ref, choice.candidate_id, choice.record_hash),
        )
        _problem(
            reasons,
            "CANDIDATE_OUTSIDE_TERMINAL",
            initial.started_at is not None
            and final.completed_at is not None
            and initial.started_at <= choice.completed_at <= final.completed_at,
        )
        if choice.valid_until is not None:
            _problem(
                reasons,
                "CANDIDATE_EXPIRED_BEFORE_TERMINAL",
                final.completed_at is not None
                and choice.valid_until >= final.completed_at,
            )
        _problem(
            reasons,
            "CANDIDATE_COST_RECEIPT_SET_MISMATCH",
            set(choice.cost_receipt_ids) == set(final.cost_receipt_ids),
        )
        if choice.disposition == "hold":
            _problem(
                reasons,
                "HOLD_NO_RECORDED_INCUMBENT",
                ctx.current_selection_ref is not None,
            )
    else:
        _problem(
            reasons,
            "FAILED_ATTEMPT_MUST_NOT_MINT_CANDIDATE",
            final.status in ("failed", "rejected")
            and final.candidate_ref is None
            and bool(final.reason_codes),
        )

    if final.status == "completed":
        _problem(reasons, "COMPLETED_ATTEMPT_WITHOUT_CANDIDATE", choice is not None)
    if choice is not None and choice.disposition == "hold":
        blocked = (*blocked, "MISSING_VERIFIED_MATCHING_INCUMBENT_FOR_HOLD")
    if choice is not None and final.status in ("failed", "rejected"):
        reasons.append("FAILED_ATTEMPT_MUST_NOT_CARRY_CANDIDATE")

    if decision is None or retained_validation is None:
        if final.status == "completed" or choice is not None:
            reasons.append("ORIGINAL_VALIDATION_MISSING")
        elif not (final.failure_artifact_ref is not None and final.reason_codes):
            reasons.append("FAILED_ATTEMPT_NO_ORIGINAL_FAILURE_EVIDENCE")
    else:
        try:
            if type(retained_validation) is not RetainedValidationCandidateV1:
                raise ValueError("validation receipt class mismatch")
            _utc(
                retained_validation.first_available_at,
                "retained_validation.first_available_at",
            )
            expected_hash = content_hash(_retained_preimage(retained_validation))
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
        except ValueError, TypeError, AttributeError:
            reasons.append("INVALID_RETAINED_VALIDATION")
        else:
            _problem(
                reasons,
                "TERMINAL_VALIDATION_REF_MISMATCH",
                _ref(
                    final.validation_ref,
                    retained_validation.validation_id,
                    retained_validation.record_hash,
                    version=VALIDATION_CANDIDATE_PROFILE,
                ),
            )
            _problem(
                reasons,
                "VALIDATION_ATTEMPT_MISMATCH",
                retained_validation.attempt_id == initial.attempt_id,
            )
            _problem(
                reasons,
                "VALIDATION_STATUS_CANDIDATE_MISMATCH",
                (decision.status == "VALID") == (choice is not None)
                and (
                    (choice is None and decision.candidate is None)
                    or (
                        choice is not None
                        and decision.candidate is not None
                        and decision.candidate.record_hash == choice.record_hash
                    )
                ),
            )
            _problem(
                reasons,
                "VALIDATION_LATE_OR_EARLY",
                initial.started_at is not None
                and final.completed_at is not None
                and initial.started_at
                <= retained_validation.first_available_at
                <= final.completed_at,
            )

    if local_validation_readback is not None:
        if (
            type(local_validation_readback) is not LocalValidationReadback
            or retained_validation is None
            or local_validation_readback.candidate != retained_validation
            or local_validation_readback.trusted_research_issuer_authenticated
        ):
            reasons.append("ORIGINAL_VALIDATION_LOCAL_READBACK_MISMATCH")
    if model is None:
        _problem(
            reasons,
            "UNEXPECTED_MODEL_REPLAY_REFERENCE",
            final.model_replay_ref is None
            and (choice is None or choice.model_replay_ref is None),
        )
    else:
        _problem(
            reasons,
            "MODEL_REPLAY_WRONG_ATTEMPT_OR_SCOPE",
            model.attempt_id == initial.attempt_id
            and model.scope == ctx.scope
            and _ref(model.context_ref, ctx.context_id, ctx.record_hash)
            and model.method_ref == ctx.method_ref
            and _ref(final.model_replay_ref, model.replay_id, model.record_hash),
        )
        _problem(
            reasons,
            "MODEL_REPLAY_CANDIDATE_MISMATCH",
            choice is None
            or _ref(choice.model_replay_ref, model.replay_id, model.record_hash),
        )
        if model.response_received_at is not None:
            _problem(
                reasons,
                "MODEL_RESPONSE_BEFORE_SEND",
                model.request_sent_at <= model.response_received_at,
            )
        if model.parse_completed_at is not None:
            _problem(
                reasons,
                "MODEL_PARSE_BEFORE_RESPONSE",
                model.response_received_at is not None
                and model.response_received_at <= model.parse_completed_at,
            )
        _problem(
            reasons,
            "MODEL_CALL_OUTSIDE_ATTEMPT",
            initial.started_at is not None
            and final.completed_at is not None
            and initial.started_at <= model.request_sent_at
            and (
                model.parse_completed_at
                or model.response_received_at
                or model.request_sent_at
            )
            <= final.completed_at,
        )
        if retained_validation is not None:
            last_model_at = (
                model.parse_completed_at
                or model.response_received_at
                or model.request_sent_at
            )
            _problem(
                reasons,
                "MODEL_AFTER_VALIDATION",
                last_model_at <= retained_validation.first_available_at,
            )

    ids = [c.receipt_id for c in cost_records]
    _problem(
        reasons,
        "COST_RECEIPT_SET_MISMATCH",
        len(set(ids)) == len(ids) and set(ids) == set(final.cost_receipt_ids),
    )
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
        _problem(
            reasons,
            "CROSS_ARM_OR_ATTEMPT_COST",
            cost.scope == ctx.scope and cost.attempt_id in (None, initial.attempt_id),
        )
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
            False,
            None,
            None if choice is None else choice.disposition,
            (),
            tuple(sorted(late_costs)),
            tuple(sorted(set(reasons))),
            blocked,
        )
    fingerprint = content_hash(
        {
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
                None if retained_validation is None else retained_validation.record_hash
            ),
            "validation_local_audit_event_hash": (
                None
                if local_validation_readback is None
                else local_validation_readback.audit_event_hash
            ),
            "candidate_hash": None if choice is None else choice.record_hash,
            "model_replay_hash": None if model is None else model.record_hash,
            "cost_hashes_as_of": tuple(sorted(included_cost_hashes)),
            "cost_receipt_ids_late": tuple(sorted(late_costs)),
            "logical_request_id": logical_request_id,
            "original_scheduler_grant_claim": (
                None if grant is None else grant.model_dump(mode="python")
            ),
            "original_account_provisioning_claim": (
                None if allocation is None else allocation.model_dump(mode="python")
            ),
            "decision_deadline": decision_deadline,
            "association_first_available_at": association_first_available_at,
        }
    )
    return ResearchE1BindingReview(
        True,
        fingerprint,
        None if choice is None else choice.disposition,
        tuple(sorted(included_cost_hashes)),
        tuple(sorted(late_costs)),
        (),
        blocked,
    )


# K1 original-byte recorder, with no scheduler or broker capability.
_LOCAL_RETENTION_PROFILE = "drift-k1-validation-retention/1-candidate"
_LOCAL_RETENTION_EVENT = "k1.validation.original_candidate_recorded"
_LOCAL_RETENTION_PAYLOAD_KEYS = frozenset(
    {
        "profile",
        "validation_id",
        "attempt_id",
        "validation_utf8",
        "raw_output_base64",
        "retained_candidate_hash",
        "issuer_claim",
    }
)
_MAX_LOCAL_RAW_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class LocalValidationReadback:
    """Durable event-integrity evidence, not independent issuer authentication."""

    candidate: RetainedValidationCandidateV1
    audit_event_id: UUID
    audit_event_hash: str
    validation_bytes_sha256: str
    raw_output_bytes_sha256: str | None

    @property
    def trusted_research_issuer_authenticated(self) -> bool:
        return False

    @property
    def can_admit_e6b(self) -> bool:
        return False


def _retained_original_ref(event_id: UUID, original: bytes) -> StoredArtifactRef:
    return StoredArtifactRef(
        artifact_id=str(event_id),
        kind="k1_validation_canonical_candidate",
        content_hash=hashlib.sha256(original).hexdigest(),
        location=f"ledger-event://{event_id}/validation",
    )


def _retained_raw_ref(event_id: UUID, raw: bytes) -> StoredArtifactRef:
    return StoredArtifactRef(
        artifact_id=str(event_id),
        kind="k1_raw_output_candidate",
        content_hash=hashlib.sha256(raw).hexdigest(),
        location=f"ledger-event://{event_id}/raw",
    )


def _parse_exact_validation(original: bytes) -> ValidationResult:
    """Reject duplicate JSON keys and noncanonical bytes before reconstruction."""

    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_ORIGINAL_VALIDATION_JSON_KEY")
            result[key] = value
        return result

    decoded = json.loads(
        original,
        object_pairs_hook=reject_duplicate,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"INVALID_VALIDATION_CONSTANT:{value}")
        ),
    )
    if type(decoded) is not dict or canonical_json(decoded) != original:
        raise ValueError("NONCANONICAL_ORIGINAL_VALIDATION_BYTES")
    return ValidationResult.model_validate(decoded)


def readback_local_validation_original(
    *,
    ledger: Ledger,
    event_id: UUID,
    expected_event_hash: str,
) -> LocalValidationReadback:
    """Verify retained original bytes against a supplied ledger snapshot.

    IMPORTANT: Passing an arbitrary caller-chosen Ledger grants no issuer
    provenance. Actual trust in the registered instance/root requires a
    separate #507 owner and independent verifier acceptance.
    """
    if type(event_id) is not UUID or event_id.version != 7:
        raise ValueError("INVALID_ORIGINAL_VALIDATION_EVENT_ID")
    if (
        type(expected_event_hash) is not str
        or len(expected_event_hash) != 64
        or any(c not in "0123456789abcdef" for c in expected_event_hash)
    ):
        raise ValueError("INVALID_ORIGINAL_VALIDATION_EVENT_HASH")

    events = ledger.verified_events()
    matches = [e for e in events if e.event_id == event_id]
    if len(matches) != 1:
        raise ValueError("ORIGINAL_VALIDATION_EVENT_NOT_UNIQUE_OR_MISSING")
    event = matches[0]
    if (
        event.event_hash != expected_event_hash
        or event.event_type != _LOCAL_RETENTION_EVENT
        or event.entity_type != "k1_validation"
        or event.schema_version != "1"
        or event.deduplication_key is None
    ):
        raise ValueError("ORIGINAL_VALIDATION_EVENT_BINDING_MISMATCH")
    payload = event.payload
    if (
        not isinstance(payload, Mapping)
        or set(payload) != _LOCAL_RETENTION_PAYLOAD_KEYS
    ):
        raise ValueError("ORIGINAL_VALIDATION_PAYLOAD_NOT_EXACT")
    if payload["profile"] != _LOCAL_RETENTION_PROFILE:
        raise ValueError("ORIGINAL_VALIDATION_PROFILE_MISMATCH")
    validation_id = payload["validation_id"]
    attempt_id = payload["attempt_id"]
    if not isinstance(validation_id, str) or not validation_id:
        raise ValueError("ORIGINAL_VALIDATION_ID_INVALID")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("ORIGINAL_VALIDATION_ATTEMPT_ID_INVALID")
    if event.deduplication_key != f"k1:validation:{validation_id}":
        raise ValueError("ORIGINAL_VALIDATION_DEDUP_MISMATCH")
    original_text = payload["validation_utf8"]
    if not isinstance(original_text, str):
        raise ValueError("ORIGINAL_VALIDATION_NOT_UTF8")
    original = original_text.encode("utf-8")
    if len(original) > _MAX_LOCAL_RAW_BYTES:
        raise ValueError("ORIGINAL_VALIDATION_TOO_LARGE")
    decision = _parse_exact_validation(original)
    raw_b64 = payload["raw_output_base64"]
    if raw_b64 is None:
        raw = None
    else:
        if not isinstance(raw_b64, str) or len(raw_b64) > 1_400_000:
            raise ValueError("ORIGINAL_RAW_NOT_BOUNDED_BASE64")
        try:
            raw = base64.b64decode(raw_b64, validate=True)
        except binascii.Error as error:
            raise ValueError("ORIGINAL_RAW_BAD_BASE64") from error
        if len(raw) > _MAX_LOCAL_RAW_BYTES:
            raise ValueError("ORIGINAL_RAW_TOO_LARGE")
    issuer_claim = ArtifactReference.model_validate(payload["issuer_claim"])
    candidate = build_retained_validation_candidate(
        validation_id=validation_id,
        attempt_id=attempt_id,
        original_validation=decision,
        raw_output_ref=(None if raw is None else _retained_raw_ref(event_id, raw)),
        original_validation_ref=_retained_original_ref(event_id, original),
        validator_issuer_ref=issuer_claim,
        first_available_at=event.timestamp,
    )
    if payload["retained_candidate_hash"] != candidate.record_hash:
        raise ValueError("ORIGINAL_VALIDATION_CANDIDATE_HASH_MISMATCH")
    return LocalValidationReadback(
        candidate=candidate,
        audit_event_id=event_id,
        audit_event_hash=event.event_hash,
        validation_bytes_sha256=hashlib.sha256(original).hexdigest(),
        raw_output_bytes_sha256=(
            None if raw is None else hashlib.sha256(raw).hexdigest()
        ),
    )


def append_local_validation_original(
    *,
    ledger: Ledger,
    event_id: UUID,
    entity_id: UUID,
    observed_at: datetime,
    validation_id: str,
    attempt_id: str,
    original_validation: ValidationResult,
    raw_output_bytes: bytes | None,
    issuer_claim: ArtifactReference,
) -> LocalValidationReadback:
    """Durably append/re-read a canonical validation decision plus raw bytes.

    Writes one event to the *supplied* append-only Ledger. The supplied
    ledger, event identity, timestamp and issuer claim are not independently
    authenticated. The caller must retain and verify the readback against a
    separately accepted configured issuer and original clock before E6B use.
    """
    _utc(observed_at, "observed_at")
    for field, identifier in (("event_id", event_id), ("entity_id", entity_id)):
        if type(identifier) is not UUID or identifier.version != 7:
            raise ValueError(f"{field}: original UUID7 required")
    if raw_output_bytes is not None and (
        type(raw_output_bytes) is not bytes
        or len(raw_output_bytes) > _MAX_LOCAL_RAW_BYTES
    ):
        raise ValueError("ORIGINAL_RAW_NOT_BOUNDED_BYTES")
    decision = _model_copy(ValidationResult, original_validation, "original_validation")
    issuer = _model_copy(ArtifactReference, issuer_claim, "issuer_claim")
    original = canonical_json(decision.model_dump(mode="python"))
    if len(original) > _MAX_LOCAL_RAW_BYTES:
        raise ValueError("ORIGINAL_VALIDATION_TOO_LARGE")
    candidate = build_retained_validation_candidate(
        validation_id=validation_id,
        attempt_id=attempt_id,
        original_validation=decision,
        raw_output_ref=(
            None
            if raw_output_bytes is None
            else _retained_raw_ref(event_id, raw_output_bytes)
        ),
        original_validation_ref=_retained_original_ref(event_id, original),
        validator_issuer_ref=issuer,
        first_available_at=observed_at,
    )
    draft = AuditEventDraft(
        event_id=event_id,
        event_type=_LOCAL_RETENTION_EVENT,
        timestamp=observed_at,
        entity_type="k1_validation",
        entity_id=entity_id,
        payload={
            "profile": _LOCAL_RETENTION_PROFILE,
            "validation_id": validation_id,
            "attempt_id": attempt_id,
            "validation_utf8": original.decode("utf-8"),
            "raw_output_base64": (
                None
                if raw_output_bytes is None
                else base64.b64encode(raw_output_bytes).decode("ascii")
            ),
            "retained_candidate_hash": candidate.record_hash,
            "issuer_claim": issuer.model_dump(mode="python"),
        },
        deduplication_key=f"k1:validation:{validation_id}",
        schema_version="1",
    )
    result = ledger.append(draft)
    # No use of caller asserted success without a same-ledger chain readback.
    checked = readback_local_validation_original(
        ledger=ledger,
        event_id=result.event_id,
        expected_event_hash=result.event_hash,
    )
    if checked.candidate != candidate:
        raise ValueError("ORIGINAL_VALIDATION_READBACK_CONFLICT")
    return checked
