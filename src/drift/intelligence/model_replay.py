"""Offline deterministic model replay runtime without network access.

Implements Slice K2 replay_model_output() under DP-R4 and research.md T06/T11.
Reconstructs execution from immutable stored request/response artifacts, verifying
exact content hashes, parsing raw choices, and constructing ModelReplayRecord.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ModelReplayRecord,
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
) -> ModelReplayResult:
    """Replay recorded model output offline with deterministic verification (T06).

    Guarantees:
    - Strictly ZERO network calls or external provider calls.
    - Fails closed with 'UNAVAILABLE' if payloads are missing or hashes mismatch.
    - Fails closed with 'MALFORMED_OUTPUT' if response payload is invalid JSON.
    - Re-validates candidate against original context and bindings.
    """
    now = datetime.now(UTC)
    actual_replay_id = replay_id or str(uuid4())
    actual_candidate_id = candidate_id or str(uuid4())
    actual_checked_at = checked_at or now

    # Convert request ref
    if isinstance(recorded_request, StoredArtifactRef):
        req_ref = recorded_request
    else:
        req_ref = StoredArtifactRef.model_validate(recorded_request)

    import hashlib

    # 1. Verify request content hash
    req_bytes = (
        request_payload.encode("utf-8")
        if isinstance(request_payload, str)
        else request_payload
    )
    req_raw_hash = hashlib.sha256(req_bytes).hexdigest()
    try:
        req_canon_hash = content_hash(json.loads(req_bytes.decode("utf-8")))
    except Exception:
        req_canon_hash = None

    if req_ref.content_hash not in (req_raw_hash, req_canon_hash):
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="request digest mismatch",
        )

    # 2. Check for recorded timeout / missing response
    if recorded_response is None or response_payload is None:
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
    resp_raw_hash = hashlib.sha256(resp_bytes).hexdigest()
    try:
        resp_canon_hash = content_hash(json.loads(resp_bytes.decode("utf-8")))
    except Exception:
        resp_canon_hash = None

    if resp_ref.content_hash not in (resp_raw_hash, resp_canon_hash):
        return ModelReplayResult(
            is_success=False,
            status="UNAVAILABLE",
            reason="response digest mismatch",
        )

    # 4. Parse response JSON
    try:
        raw_choice_data = json.loads(resp_bytes.decode("utf-8"))
    except Exception:
        return ModelReplayResult(
            is_success=False,
            status="MALFORMED_OUTPUT",
            reason="malformed JSON in response payload",
        )

    # 5. Build trusted invocation binding and validate candidate
    inv_binding = TrustedInvocationBinding(
        attempt_id=attempt_id,
        candidate_id=actual_candidate_id,
        validation_id=str(uuid4()),
        policy_ref=validation_policy,
        raw_output_ref=ArtifactReference(
            id=resp_ref.artifact_id,
            version="v1",
            sha256=resp_ref.content_hash,
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
        "response_received_at": now,
        "parse_completed_at": now,
        "measured_latency_ms": 0,
        "latency_unknown_reason": None,
        "usage_ref": None,
        "provider_call_id": None,
        "finish_reason": "stop",
        "mode": "offline_deterministic",
        "original_replay_ref": None,
        "retention_limitation": None,
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
