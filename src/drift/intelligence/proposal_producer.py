"""Scripted AI and structured proposal producer runtime.

Implements Slice K3 produce() interface with fake transport injection,
attempt lifecycle recording (T09), and output failure handling (T07).
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
    StoredArtifactRef,
    TrustedInvocationBinding,
)
from drift.intelligence.receipts import (
    ResearchReceiptStore,
    create_cost_receipt,
    create_started_attempt,
    create_terminal_attempt,
)
from drift.intelligence.validation import (
    ResolvedDependencies,
    ValidationResult,
    validate_candidate,
)


class ProducerResult(ImmutableModel):
    """Result of a proposal generation attempt."""

    is_success: bool
    status: str
    candidate: ResearchCandidate | None = None
    validation: ValidationResult | None = None
    attempt_id: str
    attempt_event_id: str
    reason: str | None = None


class FakeTransport:
    """Configurable fake model transport for offline structured proposal injection."""

    def __init__(
        self,
        *,
        raw_choice: Mapping[str, Any] | RawChoice | None = None,
        should_timeout: bool = False,
        malformed_json: str | None = None,
        cost_amount: str = "0",
        cost_currency: str = "USD",
    ) -> None:
        self.raw_choice = raw_choice
        self.should_timeout = should_timeout
        self.malformed_json = malformed_json
        self.cost_amount = cost_amount
        self.cost_currency = cost_currency


def produce_proposal(
    *,
    context: ResearchContext,
    resolved_inputs: ResolvedDependencies,
    frozen_method: ArtifactReference,
    validation_policy: ArtifactReference,
    recorder: ResearchReceiptStore,
    transport: FakeTransport | None = None,
    attempt_id: str | None = None,
    logical_request_id: str | None = None,
    candidate_id: str | None = None,
    checked_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> ProducerResult:
    """Execute proposal generation workflow with strict attempt accounting.

    Enforces T07 (fail-closed failure handling) and T09 (all attempts retained).
    """
    now = datetime.now(UTC)
    actual_attempt_id = attempt_id or str(uuid4())
    actual_request_id = logical_request_id or str(uuid4())
    start_event_id = str(uuid4())
    actual_candidate_id = candidate_id or str(uuid4())
    actual_checked_at = checked_at or now

    # 1. Record started attempt event
    started_record = create_started_attempt(
        attempt_id=actual_attempt_id,
        logical_request_id=actual_request_id,
        attempt_event_id=start_event_id,
        scope=context.scope,
        context_ref=ArtifactReference(
            id=context.context_id,
            version="v1",
            sha256=context.record_hash,
        ),
        method_ref=frozen_method,
        budget_ref=ArtifactReference(
            id="fixture:budget",
            version="v1",
            sha256="0" * 64,
        ),
        producer="scripted_producer",
        started_at=now,
    )
    recorder.record_attempt(started_record)

    # 2. Check for transport timeout or failure
    if transport is None or transport.should_timeout:
        terminal_event_id = str(uuid4())
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status="failed",
            reason_codes=("TIMEOUT", "NO_TRANSPORT_RESPONSE"),
        )
        recorder.record_attempt(terminal_attempt)

        # Record unknown cost receipt for timeout
        cost = create_cost_receipt(
            receipt_id=f"cost-{actual_attempt_id}",
            scope=context.scope,
            category="model_inference",
            billing_identity="scripted_billing",
            amount_basis="unknown",
            attempt_id=actual_attempt_id,
            unknown_reason="Transport call timed out without response",
            recorded_at=now,
        )
        recorder.record_cost_receipt(cost)

        return ProducerResult(
            is_success=False,
            status="TIMEOUT",
            attempt_id=actual_attempt_id,
            attempt_event_id=terminal_event_id,
            reason="Transport call timed out without response",
        )

    # 3. Check for malformed JSON output
    if transport.malformed_json is not None:
        terminal_event_id = str(uuid4())
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status="failed",
            reason_codes=("MALFORMED_OUTPUT",),
        )
        recorder.record_attempt(terminal_attempt)
        return ProducerResult(
            is_success=False,
            status="MALFORMED_OUTPUT",
            attempt_id=actual_attempt_id,
            attempt_event_id=terminal_event_id,
            reason="Transport emitted malformed non-JSON payload",
        )

    # 4. Extract raw choice and validate
    raw_choice_obj = transport.raw_choice
    if raw_choice_obj is None:
        terminal_event_id = str(uuid4())
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status="failed",
            reason_codes=("EMPTY_PAYLOAD",),
        )
        recorder.record_attempt(terminal_attempt)
        return ProducerResult(
            is_success=False,
            status="FAILED",
            attempt_id=actual_attempt_id,
            attempt_event_id=terminal_event_id,
            reason="No choice emitted by transport",
        )

    raw_dict = (
        raw_choice_obj.model_dump(mode="python")
        if isinstance(raw_choice_obj, RawChoice)
        else dict(raw_choice_obj)
    )

    inv_binding = TrustedInvocationBinding(
        attempt_id=actual_attempt_id,
        candidate_id=actual_candidate_id,
        validation_id=str(uuid4()),
        policy_ref=validation_policy,
        raw_output_ref=ArtifactReference(
            id="fixture:raw-output",
            version="v1",
            sha256="a" * 64,
        ),
        producer="scripted_producer",
        completed_at=now,
        checked_at=actual_checked_at,
        valid_until=valid_until,
        model_replay_ref=None,
        cost_receipt_ids=(f"cost-{actual_attempt_id}",),
    )

    val_res = validate_candidate(
        raw_choice=raw_dict,
        context=context,
        resolved_dependencies=resolved_inputs,
        trusted_invocation=inv_binding,
    )

    terminal_event_id = str(uuid4())
    if not val_res.is_valid:
        # Rejection handling (T07)
        status_terminal: Literal["rejected", "failed"] = (
            "rejected" if val_res.status == "REJECTED" else "failed"
        )
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status=status_terminal,
            reason_codes=(val_res.reason or val_res.status,),
            cost_receipt_ids=(f"cost-{actual_attempt_id}",),
        )
        recorder.record_attempt(terminal_attempt)

        # Record incurred cost even on rejection (T10)
        cost = create_cost_receipt(
            receipt_id=f"cost-{actual_attempt_id}",
            scope=context.scope,
            category="model_inference",
            billing_identity="scripted_billing",
            amount_basis="verified_zero",
            raw_evidence_ref=StoredArtifactRef(
                artifact_id="art-evidence",
                kind="other",
                content_hash="b" * 64,
                location="fixture:evidence",
            ),
            attempt_id=actual_attempt_id,
            recorded_at=now,
        )
        recorder.record_cost_receipt(cost)

        return ProducerResult(
            is_success=False,
            status=val_res.status,
            attempt_id=actual_attempt_id,
            attempt_event_id=terminal_event_id,
            validation=val_res,
            reason=val_res.reason,
        )

    # Valid candidate produced
    candidate = val_res.candidate
    assert candidate is not None

    cand_ref = ArtifactReference(
        id=candidate.candidate_id,
        version="v1",
        sha256=candidate.record_hash,
    )
    val_ref = ArtifactReference(
        id=inv_binding.validation_id,
        version="v1",
        sha256="c" * 64,
    )

    terminal_attempt = create_terminal_attempt(
        prior_attempt=started_record,
        attempt_event_id=terminal_event_id,
        completed_at=now,
        status="completed",
        candidate_ref=cand_ref,
        validation_ref=val_ref,
        cost_receipt_ids=(f"cost-{actual_attempt_id}",),
    )
    recorder.record_attempt(terminal_attempt)

    # Record verified zero cost for fake transport
    cost = create_cost_receipt(
        receipt_id=f"cost-{actual_attempt_id}",
        scope=context.scope,
        category="model_inference",
        billing_identity="scripted_billing",
        amount_basis="verified_zero",
        raw_evidence_ref=StoredArtifactRef(
            artifact_id="art-evidence",
            kind="other",
            content_hash="b" * 64,
            location="fixture:evidence",
        ),
        attempt_id=actual_attempt_id,
        recorded_at=now,
    )
    recorder.record_cost_receipt(cost)

    return ProducerResult(
        is_success=True,
        status="VALID",
        candidate=candidate,
        validation=val_res,
        attempt_id=actual_attempt_id,
        attempt_event_id=terminal_event_id,
    )
