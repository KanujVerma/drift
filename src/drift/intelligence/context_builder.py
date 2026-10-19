"""Point-in-time causal context builder runtime.

Implements Slice K4 build_context() under DP-R5 and DP-R8, enforcing strict
pre-aggregation causal filtering, arm boundaries (T04), and sealed holdout
isolation (T05).
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

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
    actual_context_id = context_id or str(uuid4())
    cutoff_utc = (
        decision_cutoff.astimezone(UTC)
        if decision_cutoff.tzinfo
        else decision_cutoff.replace(tzinfo=UTC)
    )

    admitted_inputs: list[dict[str, Any]] = []
    seen_digests: set[str] = set()

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
        inp_avail_utc = (
            inp.available_at.astimezone(UTC)
            if inp.available_at.tzinfo
            else inp.available_at.replace(tzinfo=UTC)
        )
        if inp_avail_utc > cutoff_utc:
            cutoff_str = cutoff_utc.strftime("%H:%M")
            raise ValueError(
                f"refuse: input availability after {cutoff_str} cutoff; "
                "replace ref digests with fixture hashes first to isolate causality"
            )

        # 3. Arm boundary filtering (T04)
        if inp.arm_id is not None and inp.arm_id != scope.arm_id:
            continue

        # 4. Deduplication by content hash
        digest = inp.input_ref.sha256
        if digest in seen_digests:
            continue
        seen_digests.add(digest)

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
        )
    )

    built_at = cutoff_utc
    review_started_at = cutoff_utc + timedelta(seconds=1)

    raw_dict: dict[str, Any] = {
        "profile": "drift-research/1-draft",
        "kind": "context",
        "context_id": actual_context_id,
        "scope": scope.model_dump(mode="python"),
        "decision_cutoff": cutoff_utc,
        "built_at": built_at,
        "review_started_at": review_started_at,
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
