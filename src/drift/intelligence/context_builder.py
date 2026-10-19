"""Point-in-time causal context builder runtime.

Implements Slice K4 build_context() under DP-R5 and DP-R8, enforcing strict
pre-aggregation causal filtering, arm boundaries (T04), and sealed holdout
isolation (T05).
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from drift.intelligence.contracts import (
    ArtifactReference,
    ImmutableModel,
    ResearchContext,
    Scope,
    compute_record_hash,
)


class CandidateInput(ImmutableModel):
    """Specification of an informational or market input into context."""

    input_ref: ArtifactReference
    role: str
    available_at: datetime
    availability_basis_ref: ArtifactReference
    transformation_ref: ArtifactReference | None = None
    is_holdout: bool = False
    arm_id: str | None = None


def build_context(
    *,
    scope: Scope,
    decision_cutoff: datetime,
    portfolio_ref: ArtifactReference,
    mandate_ref: ArtifactReference,
    universe_ref: ArtifactReference,
    registry_ref: ArtifactReference,
    method_ref: ArtifactReference,
    clock_policy_ref: ArtifactReference,
    budget_ref: ArtifactReference,
    memory_snapshot_ref: ArtifactReference,
    excluded_inputs_ref: ArtifactReference | None = None,
    feed_state_ref: ArtifactReference | None = None,
    feedback_refs: Sequence[ArtifactReference] = (),
    source_grade: str = "synthetic_fixture",
    limitations: Sequence[str] = (),
    inputs: Sequence[CandidateInput] = (),
    context_id: str | None = None,
    review_started_at: datetime | None = None,
    built_at: datetime | None = None,
    review_reason: str = "routine",
    trigger_ref: ArtifactReference | None = None,
    current_selection_ref: ArtifactReference | None = None,
) -> ResearchContext:
    """Build an immutable ResearchContext enforcing causal and isolation invariants.

    Enforces:
    - Point-in-time causality: inputs available after cutoff are rejected (T01, T02).
    - Sealed holdout isolation: holdout data triggers security refusal (T05).
    - Arm isolation: inputs restricted to different arms are excluded (T04).
    - Pre-aggregation deterministic deduplication and sorting.
    """
    if decision_cutoff.tzinfo is None or decision_cutoff.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: decision cutoff missing offset")
    cutoff_utc = decision_cutoff.astimezone(UTC)
    if source_grade != "synthetic_fixture" and (
        review_started_at is None or built_at is None
    ):
        raise ValueError(
            "CLOCK_AUTHORITY_REQUIRED: real review and build times must be supplied"
        )
    actual_review_started = review_started_at or cutoff_utc + timedelta(seconds=1)
    actual_built_at = built_at or cutoff_utc
    if (
        actual_review_started.tzinfo is None
        or actual_review_started.utcoffset() is None
        or actual_built_at.tzinfo is None
        or actual_built_at.utcoffset() is None
    ):
        raise ValueError("INDETERMINATE_TIMEZONE: build and review times need offsets")
    actual_review_started = actual_review_started.astimezone(UTC)
    actual_built_at = actual_built_at.astimezone(UTC)
    if actual_review_started < actual_built_at or actual_built_at < cutoff_utc:
        raise ValueError("NON_CAUSAL_REVIEW_CLOCK")

    admitted_inputs: list[dict[str, Any]] = []
    seen_records: set[tuple[str, str, str, str, str]] = set()
    seen_versions: dict[tuple[str, str], str] = {}

    # Pre-aggregation validation and filtering
    for inp in inputs:
        # 1. Sealed holdout isolation (T05)
        if (
            inp.is_holdout
            or inp.role in ("sealed_holdout", "holdout")
            or inp.input_ref.id.startswith("holdout:")
        ):
            raise ValueError(
                "HOLDOUT_ACCESS_VIOLATION: sealed holdout artifact cannot be "
                "consumed in context"
            )

        # 2. Causality verification (T01, T02, N04)
        if inp.available_at.tzinfo is None or inp.available_at.utcoffset() is None:
            raise ValueError(
                "INDETERMINATE_TIMEZONE: input availability missing offset"
            )
        inp_avail_utc = inp.available_at.astimezone(UTC)
        if inp_avail_utc > cutoff_utc:
            cutoff_str = cutoff_utc.strftime("%H:%M")
            raise ValueError(
                f"refuse: input availability after {cutoff_str} cutoff; "
                "replace ref digests with fixture hashes first to isolate causality"
            )

        # 3. Arm boundary filtering (T04)
        if inp.arm_id is not None and inp.arm_id != scope.arm_id:
            continue

        # 4. Different securities/roles may legitimately have identical bytes.
        # Never collapse solely by content hash. Reused source revision identity
        # with different bytes, however, is a provenance conflict.
        rev_key = (inp.input_ref.id, inp.input_ref.version)
        old_digest = seen_versions.get(rev_key)
        if old_digest is not None and old_digest != inp.input_ref.sha256:
            raise ValueError(
                "INPUT_REVISION_CONFLICT: same source version changed bytes"
            )
        seen_versions[rev_key] = inp.input_ref.sha256
        identity = (
            inp.input_ref.id, inp.input_ref.version, inp.input_ref.sha256,
            inp.role, inp.availability_basis_ref.sha256,
        )
        if identity in seen_records:
            continue
        seen_records.add(identity)

        admitted_inputs.append(
            {
                "input_ref": inp.input_ref.model_dump(mode="python"),
                "role": inp.role,
                "available_at": inp_avail_utc,
                "availability_basis_ref": (
                    inp.availability_basis_ref.model_dump(mode="python")
                ),
                "transformation_ref": (
                    inp.transformation_ref.model_dump(mode="python")
                    if inp.transformation_ref
                    else None
                ),
            }
        )

    # Sort admitted inputs deterministically by (available_at, role, id)
    admitted_inputs.sort(
        key=lambda item: (
            item["available_at"],
            item["role"],
            item["input_ref"]["id"],
            item["input_ref"]["version"],
            item["input_ref"]["sha256"],
            item["availability_basis_ref"]["sha256"],
            (
                item["transformation_ref"]["sha256"]
                if item["transformation_ref"] is not None
                else ""
            ),
        )
    )

    derived_id = content_hash({
        "scope": scope.model_dump(mode="python"),
        "cutoff": cutoff_utc,
        "review_started_at": actual_review_started,
        "built_at": actual_built_at,
        "inputs": admitted_inputs,
        "method": method_ref.sha256,
        "portfolio": portfolio_ref.sha256,
        "mandate": mandate_ref.sha256,
        "universe": universe_ref.sha256,
        "memory": memory_snapshot_ref.sha256,
    })
    actual_context_id = context_id or str(uuid5(NAMESPACE_URL, derived_id))

    raw_dict: dict[str, Any] = {
        "profile": "drift-research/1-draft",
        "kind": "context",
        "context_id": actual_context_id,
        "scope": scope.model_dump(mode="python"),
        "decision_cutoff": cutoff_utc,
        "built_at": actual_built_at,
        "review_started_at": actual_review_started,
        "review_reason": review_reason,
        "trigger_ref": (trigger_ref.model_dump(mode="python") if trigger_ref else None),
        "clock_policy_ref": clock_policy_ref.model_dump(mode="python"),
        "method_ref": method_ref.model_dump(mode="python"),
        "budget_ref": budget_ref.model_dump(mode="python"),
        "portfolio_ref": portfolio_ref.model_dump(mode="python"),
        "mandate_ref": mandate_ref.model_dump(mode="python"),
        "universe_ref": universe_ref.model_dump(mode="python"),
        "registry_ref": registry_ref.model_dump(mode="python"),
        "memory_snapshot_ref": memory_snapshot_ref.model_dump(mode="python"),
        "memory_cutoff": cutoff_utc,
        "inputs": admitted_inputs,
        "excluded_inputs_ref": (
            excluded_inputs_ref.model_dump(mode="python")
            if excluded_inputs_ref
            else None
        ),
        "feed_state_ref": (
            feed_state_ref.model_dump(mode="python") if feed_state_ref else None
        ),
        "feedback_refs": [ref.model_dump(mode="python") for ref in feedback_refs],
        "source_grade": source_grade,
        "limitations": list(limitations),
        "current_selection_ref": (
            current_selection_ref.model_dump(mode="python")
            if current_selection_ref
            else None
        ),
    }

    rec_hash = compute_record_hash(raw_dict)
    raw_dict["record_hash"] = rec_hash
    return ResearchContext.model_validate(raw_dict)
