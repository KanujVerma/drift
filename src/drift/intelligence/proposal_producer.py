"""Purely scripted, offline research proposal producer and attempt recorder.

No provider network call is possible through FakeTransport. A proposal is never
an order or a portfolio mandate authorization. Any later real transport needs
its own separately approved adapter and authenticated billing provenance.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from drift.errors import CanonicalSerializationError
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
from drift.serialization.canonical import canonical_json, content_hash

type ValidationObservationCallback = Callable[
    [str, TrustedInvocationBinding, ValidationResult], None
]


def observe_original_validation(
    observer: ValidationObservationCallback | None,
    raw_choice: Mapping[str, Any],
    binding: TrustedInvocationBinding,
    result: ValidationResult,
) -> None:
    """Observe detached original validation immediately, never reconstructed later.

    A retention exception propagates before terminal completion. The installed
    caller must preserve its already-recorded start/cost and refuse retry.
    Omitting the observer preserves the existing offline producer behavior.
    """
    if observer is not None:
        observer(
            canonical_json(raw_choice).decode("utf-8"),
            TrustedInvocationBinding.model_validate(binding.model_dump(mode="python")),
            ValidationResult.model_validate(result.model_dump(mode="python")),
        )


class ProducerResult(ImmutableModel):
    """Non-operational outcome of a single scripted proposal attempt."""

    is_success: bool
    status: str
    candidate: ResearchCandidate | None = None
    validation: ValidationResult | None = None
    attempt_id: str
    attempt_event_id: str
    reason: str | None = None


class FakeTransport:
    """Offline test transport, never a general provider connector."""

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


def _record_scripted_cost(
    *,
    recorder: ResearchReceiptStore,
    context: ResearchContext,
    attempt_id: str,
    method_ref: ArtifactReference,
    completed_at: datetime,
    transport: FakeTransport | None,
) -> str:
    """Retain every attempt's *synthetic* cost, including unsuccessful calls.

    A user-specified nonzero cost is an ESTIMATE, not evidence of an actual
    provider bill. A timeout with uncertain usage stays UNKNOWN.
    """
    receipt_id = f"cost-{attempt_id}"
    if transport is None or transport.should_timeout:
        cost = create_cost_receipt(
            receipt_id=receipt_id,
            scope=context.scope,
            category="model_inference",
            billing_identity="scripted_offline",
            amount_basis="unknown",
            attempt_id=attempt_id,
            unknown_reason="Scripted call timed out; historical usage is not verified",
            recorded_at=completed_at,
        )
    else:
        # Offline transport metadata is not a provider invoice. Reject even
        # syntactically valid scientific notation rather than allowing the
        # downstream plain-Decimal cost constructor to strand the attempt.
        try:
            if (
                not isinstance(transport.cost_amount, str)
                or "e" in transport.cost_amount.lower()
                or transport.cost_amount.strip() != transport.cost_amount
            ):
                raise ValueError("Synthetic cost is not plain DecimalText")
            amount = Decimal(transport.cost_amount)
        except InvalidOperation, TypeError, ValueError:
            amount = Decimal("NaN")
        if not amount.is_finite() or amount < 0:
            cost = create_cost_receipt(
                receipt_id=receipt_id,
                scope=context.scope,
                category="model_inference",
                billing_identity="scripted_offline",
                amount_basis="unknown",
                attempt_id=attempt_id,
                unknown_reason="Synthetic cost amount is invalid or missing",
                recorded_at=completed_at,
            )
        elif amount > 0 and (
            not isinstance(transport.cost_currency, str)
            or not transport.cost_currency.strip()
        ):
            cost = create_cost_receipt(
                receipt_id=receipt_id,
                scope=context.scope,
                category="model_inference",
                billing_identity="scripted_offline",
                amount_basis="unknown",
                attempt_id=attempt_id,
                unknown_reason="Synthetic nonzero cost has no valid currency",
                recorded_at=completed_at,
            )
        elif amount == 0:
            # This only describes the offline FakeTransport; no external bill
            # or provider usage is represented by the synthetic evidence ref.
            cost = create_cost_receipt(
                receipt_id=receipt_id,
                scope=context.scope,
                category="model_inference",
                billing_identity="scripted_offline",
                amount_basis="verified_zero",
                attempt_id=attempt_id,
                raw_evidence_ref=StoredArtifactRef(
                    artifact_id=f"synthetic:fake-transport:{attempt_id}",
                    kind="other",
                    content_hash=content_hash(
                        {
                            "transport": "FakeTransport",
                            "mode": "offline_no_external_calls",
                            "attempt_id": attempt_id,
                            "method": method_ref.model_dump(mode="python"),
                        }
                    ),
                    location="synthetic:fake-transport-no-external-provider",
                ),
                recorded_at=completed_at,
            )
        else:
            cost = create_cost_receipt(
                receipt_id=receipt_id,
                scope=context.scope,
                category="model_inference",
                billing_identity="scripted_offline",
                amount_basis="estimate",
                attempt_id=attempt_id,
                amount=str(amount),
                currency=transport.cost_currency,
                recorded_at=completed_at,
            )
    recorder.record_cost_receipt(cost)
    return receipt_id


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
    validation_observer: ValidationObservationCallback | None = None,
) -> ProducerResult:
    """Record a full scripted attempt, validate or fail closed, without I/O."""
    logical_clock = checked_at or context.review_started_at
    if logical_clock.tzinfo is None or logical_clock.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: producer requires explicit time")
    if valid_until is not None and (
        valid_until.tzinfo is None or valid_until.utcoffset() is None
    ):
        raise ValueError("INDETERMINATE_TIMEZONE: candidate TTL requires offset")
    now = logical_clock.astimezone(UTC)
    seed = content_hash(
        {
            "context": context.record_hash,
            "method": frozen_method.model_dump(mode="python"),
            "policy": validation_policy.model_dump(mode="python"),
            "at": now,
            "logical_request_id": logical_request_id,
            "valid_until": valid_until,
        }
    )
    selected_attempt_id = attempt_id or str(uuid5(NAMESPACE_URL, seed))
    selected_request_id = logical_request_id or str(
        uuid5(NAMESPACE_URL, seed + ":request")
    )
    started_id = str(uuid5(NAMESPACE_URL, selected_attempt_id + ":started"))
    completed_id = str(uuid5(NAMESPACE_URL, selected_attempt_id + ":terminal"))
    selected_candidate_id = candidate_id or str(
        uuid5(NAMESPACE_URL, selected_attempt_id + ":candidate")
    )

    started = create_started_attempt(
        attempt_id=selected_attempt_id,
        logical_request_id=selected_request_id,
        attempt_event_id=started_id,
        scope=context.scope,
        context_ref=ArtifactReference(
            id=context.context_id,
            version=context.profile,
            sha256=context.record_hash,
        ),
        method_ref=frozen_method,
        budget_ref=context.budget_ref,
        producer="scripted_producer",
        started_at=now,
    )
    recorder.record_attempt(started)
    cost_id = _record_scripted_cost(
        recorder=recorder,
        context=context,
        attempt_id=selected_attempt_id,
        method_ref=frozen_method,
        completed_at=now,
        transport=transport,
    )

    result: ValidationResult | None = None
    terminal_status: Literal["completed", "failed", "rejected"] = "failed"
    reason: str | None = None
    status = "FAILED"

    if transport is None or transport.should_timeout:
        status, reason = "TIMEOUT", "Scripted transport timed out without a response"
    elif transport.malformed_json is not None:
        status = "MALFORMED_OUTPUT"
        reason = "Scripted transport supplied malformed JSON"
    elif transport.raw_choice is None:
        status, reason = "FAILED", "No choice emitted by scripted transport"
    else:
        raw_choice = (
            transport.raw_choice.model_dump(mode="python")
            if isinstance(transport.raw_choice, RawChoice)
            else dict(transport.raw_choice)
        )
        # Parse the untrusted structured choice before hashing. A permitted
        # Mapping[str, Any] may contain non-finite or opaque values that the
        # canonical encoder must refuse. This still records an invalid
        # terminal attempt and its incurred cost instead of crashing.
        try:
            parsed_choice = RawChoice.model_validate(raw_choice)
            raw_digest = content_hash(parsed_choice.model_dump(mode="python"))
        except ValueError, TypeError, CanonicalSerializationError:
            try:
                raw_digest = content_hash(raw_choice)
            except CanonicalSerializationError, TypeError, ValueError:
                result = ValidationResult(
                    is_valid=False,
                    status="INVALID",
                    reason="INVALID_RAW_CHOICE_SERIALIZATION",
                )
        if result is None:
            binding = TrustedInvocationBinding(
                attempt_id=selected_attempt_id,
                candidate_id=selected_candidate_id,
                validation_id=str(
                    uuid5(NAMESPACE_URL, selected_attempt_id + ":validation")
                ),
                policy_ref=validation_policy,
                raw_output_ref=ArtifactReference(
                    id=f"synthetic:scripted-output:{selected_attempt_id}",
                    version="v1",
                    sha256=raw_digest,
                ),
                producer="scripted_producer",
                completed_at=now,
                checked_at=now,
                valid_until=valid_until,
                model_replay_ref=None,
                cost_receipt_ids=(cost_id,),
            )
            result = validate_candidate(
                raw_choice=raw_choice,
                context=context,
                resolved_dependencies=resolved_inputs,
                trusted_invocation=binding,
            )
            observe_original_validation(
                validation_observer, raw_choice, binding, result
            )
        status = result.status
        reason = result.reason
        if result.is_valid and result.candidate is not None:
            terminal_status = "completed"
        elif result.status == "REJECTED":
            terminal_status = "rejected"

    candidate = result.candidate if result is not None and result.is_valid else None
    terminal = create_terminal_attempt(
        prior_attempt=started,
        attempt_event_id=completed_id,
        completed_at=now,
        status=terminal_status,
        candidate_ref=(
            ArtifactReference(
                id=candidate.candidate_id,
                version=candidate.profile,
                sha256=candidate.record_hash,
            )
            if candidate is not None
            else None
        ),
        validation_ref=(
            ArtifactReference(
                id=f"{selected_attempt_id}:validation",
                version="v1",
                sha256=content_hash(result.model_dump(mode="python")),
            )
            if result is not None
            else None
        ),
        cost_receipt_ids=(cost_id,),
        reason_codes=(status,),
    )
    recorder.record_attempt(terminal)
    return ProducerResult(
        is_success=candidate is not None,
        status=status,
        candidate=candidate,
        validation=result,
        attempt_id=selected_attempt_id,
        attempt_event_id=completed_id,
        reason=reason,
    )
