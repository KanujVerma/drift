"""Conventional candidate selector and optimizer R seam runtime.

Implements Slice K3 conventional selector over preregistered finite pools under DP-R6.
Provides deterministic scoring, alphanumeric tie-breaking, and isolated state (T13).
"""

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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
    validate_candidate,
)
from drift.serialization.canonical import content_hash


class ConventionalSelectorResult(ImmutableModel):
    """Result of conventional optimizer candidate selection."""

    is_success: bool
    status: str
    selected_candidate: ResearchCandidate | None = None
    candidate_scores: dict[str, str] = {}
    attempt_id: str
    attempt_event_id: str
    reason: str | None = None


def _choice_identity(choice: Mapping[str, Any] | RawChoice) -> str:
    """Bind a candidate pool entry to its typed semantic choice, not key order."""
    raw_choice = (
        choice.model_dump(mode="python")
        if isinstance(choice, RawChoice)
        else dict(choice)
    )
    try:
        typed = RawChoice.model_validate(raw_choice)
        return content_hash(typed.model_dump(mode="python"))
    except ValueError:
        # Invalid entries are rejected by validate_candidate; keep a stable
        # diagnostic identity for the failed attempt.
        return content_hash(raw_choice)


def select_conventional_candidate(
    *,
    context: ResearchContext,
    resolved_inputs: ResolvedDependencies,
    candidate_pool: Sequence[Mapping[str, Any] | RawChoice],
    objective_fn: Callable[[ResearchCandidate], Decimal],
    method_ref: ArtifactReference,
    validation_policy: ArtifactReference,
    recorder: ResearchReceiptStore,
    attempt_id: str | None = None,
    logical_request_id: str | None = None,
    checked_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> ConventionalSelectorResult:
    """Select optimal candidate from preregistered finite pool under DP-R6.

    Guarantees:
    - Pure offline computation with ZERO model/provider imports or LLM calls.
    - Exhaustive discrete candidate evaluation against objective function.
    - Deterministic tie-breaking on (score, family_id, params_hash, candidate_id).
    - Full attempt lifecycle recording in recorder store.
    """
    # Offline selection must not depend on the host wall clock.
    now = checked_at or context.review_started_at
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("INDETERMINATE_TIMEZONE: comparator cutoff missing offset")
    if valid_until is not None and (
        valid_until.tzinfo is None or valid_until.utcoffset() is None
    ):
        raise ValueError("INDETERMINATE_TIMEZONE: comparator TTL requires offset")
    now = now.astimezone(UTC)
    if valid_until is not None:
        valid_until = valid_until.astimezone(UTC)
    # Snapshot the complete pool before any objective callback is invoked.
    # No callback may rewrite later candidates while a frozen experiment is
    # evaluated under a previously computed pool identity.
    invalid_pool = False
    frozen_pool: list[tuple[str, dict[str, Any]]] = []
    try:
        for choice in candidate_pool:
            source = (
                choice.model_dump(mode="python")
                if isinstance(choice, RawChoice)
                else dict(choice)
            )
            raw_snapshot = deepcopy(source)
            frozen_pool.append(
                (_choice_identity(raw_snapshot), raw_snapshot)
            )
        pool_hash = content_hash(sorted(identity for identity, _ in frozen_pool))
    except (CanonicalSerializationError, TypeError, ValueError):
        if attempt_id is None:
            raise ValueError(
                "NONCANONICAL_POOL_REQUIRES_EXPLICIT_ATTEMPT_ID"
            ) from None
        invalid_pool = True
        frozen_pool.clear()
        pool_hash = content_hash(
            {
                "invalid_pool": True,
                "explicit_attempt_id": attempt_id,
            }
        )
    seed = content_hash(
        {
            "context": context.record_hash,
            "method": method_ref.model_dump(mode="python"),
            "candidate_pool": pool_hash,
            "policy": validation_policy.model_dump(mode="python"),
            "logical_request_id": logical_request_id,
            "valid_until": valid_until,
            "checked_at": now,
        }
    )
    actual_attempt_id = attempt_id or str(uuid5(NAMESPACE_URL, seed))
    actual_request_id = logical_request_id or str(
        uuid5(NAMESPACE_URL, seed + ":request")
    )
    start_event_id = str(uuid5(NAMESPACE_URL, actual_attempt_id + ":start"))
    actual_checked_at = now

    # 1. Record started attempt event
    started_record = create_started_attempt(
        attempt_id=actual_attempt_id,
        logical_request_id=actual_request_id,
        attempt_event_id=start_event_id,
        scope=context.scope,
        context_ref=ArtifactReference(
            id=context.context_id,
            version=context.profile,
            sha256=context.record_hash,
        ),
        method_ref=method_ref,
        budget_ref=context.budget_ref,
        producer="conventional_selector",
        started_at=now,
    )
    recorder.record_attempt(started_record)

    # Retain the deterministic synthetic compute cost before committing a
    # terminal event that references it. No external provider call is made.
    cost = create_cost_receipt(
        receipt_id=f"cost-{actual_attempt_id}",
        scope=context.scope,
        category="selector_compute",
        billing_identity="conventional_billing",
        amount_basis="verified_zero",
        raw_evidence_ref=StoredArtifactRef(
            artifact_id=f"synthetic:offline-compute:{actual_attempt_id}",
            kind="other",
            content_hash=content_hash(
                {
                    "attempt": actual_attempt_id,
                    "method": method_ref.model_dump(mode="python"),
                    "kind": "synthetic_no_external_provider_call",
                }
            ),
            location="synthetic:offline-compute-only",
        ),
        attempt_id=actual_attempt_id,
        recorded_at=now,
    )
    recorder.record_cost_receipt(cost)

    # 2. Validate every pool member before objective scoring begins.
    # Rejected or unavailable members cannot silently shrink the experiment.
    evaluated_candidates: list[tuple[Decimal, str, str, str, ResearchCandidate]] = []
    scores_dict: dict[str, str] = {}
    score_error: str | None = (
        "INVALID_CANDIDATE_POOL_SERIALIZATION" if invalid_pool else None
    )
    seen_choice_hashes: set[str] = set()
    validated_candidates: list[ResearchCandidate] = []

    for choice_hash, raw_dict in frozen_pool:
        if choice_hash in seen_choice_hashes:
            score_error = "DUPLICATE_CANDIDATE_POOL_MEMBER"
            break
        seen_choice_hashes.add(choice_hash)
        candidate_identity = content_hash(
            {
                "choice_hash": choice_hash,
                "context_hash": context.record_hash,
                "method_hash": method_ref.sha256,
                "attempt_id": actual_attempt_id,
            }
        )
        cand_id = f"cand-r-{candidate_identity[:32]}"
        inv_binding = TrustedInvocationBinding(
            attempt_id=actual_attempt_id,
            candidate_id=cand_id,
            validation_id=str(uuid5(NAMESPACE_URL, cand_id + ":validation")),
            policy_ref=validation_policy,
            raw_output_ref=ArtifactReference(
                id=f"synthetic:pool-choice-{choice_hash[:16]}",
                version="v1",
                sha256=choice_hash,
            ),
            producer="conventional_selector",
            completed_at=now,
            checked_at=actual_checked_at,
            valid_until=valid_until,
            model_replay_ref=None,
            cost_receipt_ids=(f"cost-{actual_attempt_id}",),
        )
        verdict = validate_candidate(
            raw_choice=raw_dict,
            context=context,
            resolved_dependencies=resolved_inputs,
            trusted_invocation=inv_binding,
        )
        if not verdict.is_valid or verdict.candidate is None:
            score_error = "INVALID_CANDIDATE_POOL_MEMBER"
            break
        validated_candidates.append(verdict.candidate)

    if score_error is None:
        for candidate in validated_candidates:
            # Pydantic frozen models may still hold mutable nested Mapping
            # values. Give the untrusted scorer a clone, never our receipt.
            try:
                scoring_view = ResearchCandidate.model_validate(
                    candidate.model_dump(mode="python")
                )
                score_num = objective_fn(scoring_view)
            except Exception:  # noqa: BLE001 - callback cannot pick a winner
                score_error = "OBJECTIVE_EVALUATION_FAILED"
                break
            if not isinstance(score_num, Decimal) or not score_num.is_finite():
                score_error = "INVALID_OBJECTIVE_SCORE"
                break
            scores_dict[candidate.candidate_id] = str(score_num)
            family = (
                candidate.strategy.family_id
                if candidate.strategy
                else "no_strategy"
            )
            params_hash = (
                candidate.strategy.parameters_hash
                if candidate.strategy
                else "0" * 64
            )
            evaluated_candidates.append(
                (score_num, family, params_hash, candidate.candidate_id, candidate)
            )

    # 3. Handle case where no candidate in pool was valid
    terminal_event_id = str(uuid5(NAMESPACE_URL, actual_attempt_id + ":terminal"))
    if score_error is not None:
        evaluated_candidates.clear()
    if not evaluated_candidates:
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status="rejected",
            reason_codes=(score_error or "NO_ELIGIBLE_CANDIDATE",),
            cost_receipt_ids=(f"cost-{actual_attempt_id}",),
        )
        recorder.record_attempt(terminal_attempt)

        return ConventionalSelectorResult(
            is_success=False,
            status="REJECTED",
            attempt_id=actual_attempt_id,
            attempt_event_id=terminal_event_id,
            reason=(
                "Objective scoring was unavailable or invalid"
                if score_error is not None
                else "No candidate in pool satisfied validation constraints"
            ),
        )

    # DP-R6: scores within the frozen 1e-9 equivalence band tie, even when
    # their raw Decimal values differ. Resolve ties without pool-order bias.
    max_score = max(entry[0] for entry in evaluated_candidates)
    tolerance = Decimal("0.000000001")
    near_maximum = [
        entry for entry in evaluated_candidates if max_score - entry[0] <= tolerance
    ]
    winner = min(near_maximum, key=lambda entry: (entry[1], entry[2], entry[3]))[4]

    cand_ref = ArtifactReference(
        id=winner.candidate_id,
        version=winner.profile,
        sha256=winner.record_hash,
    )

    terminal_attempt = create_terminal_attempt(
        prior_attempt=started_record,
        attempt_event_id=terminal_event_id,
        completed_at=now,
        status="completed",
        candidate_ref=cand_ref,
        cost_receipt_ids=(f"cost-{actual_attempt_id}",),
    )
    recorder.record_attempt(terminal_attempt)

    # The verified-zero synthetic compute receipt was stored before completion.
    return ConventionalSelectorResult(
        is_success=True,
        status="VALID",
        selected_candidate=winner,
        candidate_scores=scores_dict,
        attempt_id=actual_attempt_id,
        attempt_event_id=terminal_event_id,
    )
