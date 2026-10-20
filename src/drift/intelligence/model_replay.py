"""Offline deterministic model replay runtime without network access.

Implements Slice K2 replay_model_output() under DP-R4 and research.md T06/T11.
Reconstructs execution from immutable stored request/response artifacts, verifying
exact content hashes, parsing raw choices, and constructing ModelReplayRecord.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ModelReplayRecord,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
    StoredArtifactRef,
    TrustedInvocationBinding,
    compute_record_hash,
)
from drift.intelligence.validation import (
    ResolvedDependencies,
    ValidationResult,
    validate_candidate,
)
from drift.serialization.canonical import content_hash


class ModelReplayResult(ImmutableModel):
    """Result of an offline deterministic model replay execution."""

    is_success: bool
    status: str
    candidate: ResearchCandidate | None = None
    validation: ValidationResult | None = None
    replay_record: ModelReplayRecord | None = None
    reason: str | None = None


def replay_model_output(
    *,
    recorded_request: StoredArtifactRef | Mapping[str, Any],
    recorded_response: StoredArtifactRef | Mapping[str, Any] | None,
    request_payload: str | bytes,
    response_payload: str | bytes | None,
    original_context: ResearchContext,
    original_bindings: ResolvedDependencies,
    adapter_revision: ArtifactReference,
    parser_schema_ref: ArtifactReference,
    validation_policy: ArtifactReference,
    attempt_id: str,
    replay_id: str | None = None,
    candidate_id: str | None = None,
    checked_at: datetime | None = None,
    valid_until: datetime | None = None,
    recorded_finish_reason: Literal["stop", "timeout", "unknown"] | None = None,
) -> ModelReplayResult:
    """Replay recorded model output offline with deterministic verification (T06).

    Guarantees:
    - Strictly ZERO network calls or external provider calls.
    - Fails closed with 'UNAVAILABLE' if payloads are missing or hashes mismatch.
    - Fails closed with 'MALFORMED_OUTPUT' if response payload is invalid JSON.
    - Re-validates candidate against original context and bindings.
    """
    # Offline replay is defined by retained evidence, not today's wall clock.
    actual_checked_at = checked_at or original_context.review_started_at
    if actual_checked_at.tzinfo is None or actual_checked_at.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: replay requires explicit cutoff")
    now = actual_checked_at.astimezone(UTC)
    identity_seed = content_hash(
        {
            "attempt": attempt_id,
            "context": original_context.record_hash,
            "adapter": adapter_revision.sha256,
            "parser": parser_schema_ref.sha256,
            "policy": validation_policy.sha256,
            "request": (
                recorded_request.content_hash
                if isinstance(recorded_request, StoredArtifactRef)
                else recorded_request.get("content_hash")
            ),
            "response": (
                recorded_response.content_hash
                if isinstance(recorded_response, StoredArtifactRef)
                else (
                    recorded_response.get("content_hash")
                    if recorded_response is not None
                    else None
                )
            ),
            "cutoff": now,
        }
    )
    actual_replay_id = replay_id or str(uuid5(NAMESPACE_URL, identity_seed))
    actual_candidate_id = candidate_id or str(
        uuid5(NAMESPACE_URL, identity_seed + ":candidate")
    )

    # Convert request ref
    if isinstance(recorded_request, StoredArtifactRef):
        req_ref = recorded_request
    else:
        req_ref = StoredArtifactRef.model_validate(recorded_request)

    # 1. Verify the exact retained request bytes, not merely parsed JSON.
    req_bytes = (
        request_payload.encode("utf-8")
        if isinstance(request_payload, str)
        else request_payload
    )
    req_raw_hash = hashlib.sha256(req_bytes).hexdigest()
    if req_ref.content_hash != req_raw_hash:
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="request digest mismatch",
        )

    # Absent response evidence must be consistent. A one-sided absence is not
    # proof of a historical timeout or a provider completion.
    if (recorded_response is None) != (response_payload is None):
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="inconsistent missing response evidence",
        )

    # Absence is not a historical timeout unless the retained call-status
    # evidence explicitly says so. Do not manufacture a provider failure.
    if recorded_response is None and response_payload is None:
        if recorded_finish_reason != "timeout":
            return ModelReplayResult(
                is_success=False,
                status="UNAVAILABLE",
                reason="missing retained response and no proven timeout status",
            )
        raw_replay_record: dict[str, Any] = {
            "profile": "drift-research/1-draft",
            "kind": "model_replay",
            "replay_id": actual_replay_id,
            "attempt_id": attempt_id,
            "scope": original_context.scope.model_dump(mode="python"),
            "context_ref": ArtifactReference(
                id=original_context.context_id,
                version="v1",
                sha256=original_context.record_hash,
            ).model_dump(mode="python"),
            "method_ref": original_context.method_ref.model_dump(mode="python"),
            "adapter_ref": adapter_revision.model_dump(mode="python"),
            "parser_schema_ref": parser_schema_ref.model_dump(mode="python"),
            "provider_identity": "offline_replay",
            "requested_model": "recorded_offline",
            "resolved_model_revision": None,
            "resolution_limitation": "Offline replay from recorded bytes",
            "training_horizon_limitation": "No live model access",
            "request_ref": req_ref.model_dump(mode="python"),
            "response_ref": None,
            "request_sent_at": original_context.review_started_at,
            "response_received_at": None,
            "parse_completed_at": None,
            "measured_latency_ms": None,
            "latency_unknown_reason": "Recorded call timed out without response",
            "usage_ref": None,
            "provider_call_id": None,
            "finish_reason": "timeout",
            "mode": "offline_deterministic",
            "original_replay_ref": None,
            "retention_limitation": "Timeout recorded in offline replay",
            "replay_started_at": now,
            "replay_completed_at": now,
        }
        rec_hash = compute_record_hash(raw_replay_record)
        raw_replay_record["record_hash"] = rec_hash
        replay_rec = ModelReplayRecord.model_validate(raw_replay_record)
        return ModelReplayResult(
            is_success=False,
            status="TIMEOUT",
            replay_record=replay_rec,
            reason="Recorded model call timed out without response",
        )

    if recorded_finish_reason == "timeout":
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="timeout claim conflicts with retained response",
        )

    # Convert response ref
    if isinstance(recorded_response, StoredArtifactRef):
        resp_ref = recorded_response
    else:
        resp_ref = StoredArtifactRef.model_validate(recorded_response)

    # 3. Verify response content hash
    resp_bytes = (
        response_payload.encode("utf-8")
        if isinstance(response_payload, str)
        else response_payload
    )
    # Missing retained response bytes cannot be authenticated or replayed.
    if resp_bytes is None:
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="inconsistent missing response evidence",
        )
    resp_raw_hash = hashlib.sha256(resp_bytes).hexdigest()
    if resp_ref.content_hash != resp_raw_hash:
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="response digest mismatch",
        )

    # 4. Parse the retained response without silent last-key-wins or
    # non-standard JSON constants such as NaN and Infinity.
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_MODEL_OUTPUT_JSON_KEY")
            result[key] = value
        return result

    def refuse_constant(value: str) -> None:
        raise ValueError(f"NONFINITE_MODEL_OUTPUT_CONSTANT: {value}")

    try:
        raw_choice_data = json.loads(
            resp_bytes.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=refuse_constant,
        )
        if not isinstance(raw_choice_data, dict):
            raise ValueError("model output is not a JSON object")
    except ValueError, UnicodeDecodeError:
        return ModelReplayResult(
            is_success=False,
            status="MALFORMED_OUTPUT",
            reason="malformed JSON in response payload",
        )

    # Two separate commitments are required: ModelReplayRecord.response_ref
    # binds exact retained bytes, while the candidate validator binds the
    # normalized typed RawChoice. Cosmetic JSON serialization changes affect
    # the raw byte proof but must not falsely invalidate a matched output.
    try:
        parsed_choice = RawChoice.model_validate(raw_choice_data)
        normalized_choice_hash = content_hash(parsed_choice.model_dump(mode="python"))
    except ValueError:
        # Invalid typed choices are rejected by validate_candidate below.
        normalized_choice_hash = content_hash(raw_choice_data)

    # 5. Build trusted invocation binding and validate candidate
    inv_binding = TrustedInvocationBinding(
        attempt_id=attempt_id,
        candidate_id=actual_candidate_id,
        validation_id=str(uuid5(NAMESPACE_URL, identity_seed + ":validation")),
        policy_ref=validation_policy,
        raw_output_ref=ArtifactReference(
            id=f"{resp_ref.artifact_id}:normalized-choice",
            version="raw-choice/1",
            sha256=normalized_choice_hash,
        ),
        producer="offline_replay",
        completed_at=now,
        checked_at=actual_checked_at,
        valid_until=valid_until,
        model_replay_ref=None,
        cost_receipt_ids=(),
    )

    val_result = validate_candidate(
        raw_choice=raw_choice_data,
        context=original_context,
        resolved_dependencies=original_bindings,
        trusted_invocation=inv_binding,
    )

    # 6. Build ModelReplayRecord
    raw_replay_record = {
        "profile": "drift-research/1-draft",
        "kind": "model_replay",
        "replay_id": actual_replay_id,
        "attempt_id": attempt_id,
        "scope": original_context.scope.model_dump(mode="python"),
        "context_ref": ArtifactReference(
            id=original_context.context_id,
            version="v1",
            sha256=original_context.record_hash,
        ).model_dump(mode="python"),
        "method_ref": original_context.method_ref.model_dump(mode="python"),
        "adapter_ref": adapter_revision.model_dump(mode="python"),
        "parser_schema_ref": parser_schema_ref.model_dump(mode="python"),
        "provider_identity": "offline_replay",
        "requested_model": "recorded_offline",
        "resolved_model_revision": None,
        "resolution_limitation": "Offline deterministic replay from recorded bytes",
        "training_horizon_limitation": "No live model access",
        "request_ref": req_ref.model_dump(mode="python"),
        "response_ref": resp_ref.model_dump(mode="python"),
        "request_sent_at": original_context.review_started_at,
        # Original provider timestamps are not recovered by replay.
        "response_received_at": None,
        "parse_completed_at": None,
        "measured_latency_ms": None,
        "latency_unknown_reason": "offline replay cannot measure provider latency",
        "usage_ref": None,
        "provider_call_id": None,
        # Retained response bytes alone do not prove a provider finish code.
        "finish_reason": recorded_finish_reason or "unknown",
        "mode": "offline_deterministic",
        "original_replay_ref": None,
        "retention_limitation": (
            "historical provider timestamps unavailable; provider finish unknown"
            if recorded_finish_reason != "stop"
            else "historical provider timestamps unavailable"
        ),
        "replay_started_at": now,
        "replay_completed_at": now,
    }
    rec_hash = compute_record_hash(raw_replay_record)
    raw_replay_record["record_hash"] = rec_hash
    replay_rec = ModelReplayRecord.model_validate(raw_replay_record)

    return ModelReplayResult(
        is_success=val_result.is_valid,
        status=val_result.status,
        candidate=val_result.candidate,
        validation=val_result,
        replay_record=replay_rec,
        reason=val_result.reason,
    )
