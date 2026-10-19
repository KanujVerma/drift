"""Conventional candidate selector and optimizer R seam runtime.

Implements Slice K3 conventional selector over preregistered finite pools under DP-R6.
Provides deterministic scoring, alphanumeric tie-breaking, and isolated state (T13).
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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
    pool_hash = content_hash(sorted(
        content_hash(
            choice.model_dump(mode="python") if isinstance(choice, RawChoice) else dict(choice)
        ) for choice in candidate_pool
    ))
    seed = content_hash({
        "context": context.record_hash,
        "method": method_ref.sha256,
        "candidate_pool": pool_hash,
        "checked_at": now,
    })
    actual_attempt_id = attempt_id or str(uuid5(NAMESPACE_URL, seed))
    actual_request_id = logical_request_id or str(uuid5(NAMESPACE_URL, seed + ":request"))
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
            version="v1",
            sha256=context.record_hash,
        ),
        method_ref=method_ref,
        budget_ref=ArtifactReference(
            id="fixture:budget",
            version="v1",
            sha256="0" * 64,
        ),
        producer="conventional_selector",
        started_at=now,
    )
    recorder.record_attempt(started_record)

    # 2. Exhaustively evaluate valid candidates
    evaluated_candidates: list[tuple[Decimal, str, str, str, ResearchCandidate]] = []
    scores_dict: dict[str, str] = {}
    score_error: str | None = None
    seen_choice_hashes: set[str] = set()

    for choice_item in candidate_pool:
        # The candidate's identity is stable under a pool permutation.
        raw_source = (
            choice_item.model_dump(mode="python")
            if isinstance(choice_item, RawChoice)
            else dict(choice_item)
        )
        choice_hash = content_hash(raw_source)
        if choice_hash in seen_choice_hashes:
            score_error = "DUPLICATE_CANDIDATE_POOL_MEMBER"
            break
        seen_choice_hashes.add(choice_hash)
        candidate_identity = content_hash({
            "choice_hash": choice_hash,
            "context_hash": context.record_hash,
            "method_hash": method_ref.sha256,
        })
        cand_id = f"cand-r-{candidate_identity[:32]}"
        raw_dict = (
            choice_item.model_dump(mode="python")
            if isinstance(choice_item, RawChoice)
            else dict(choice_item)
        )

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

        val_res = validate_candidate(
            raw_choice=raw_dict,
            context=context,
            resolved_dependencies=resolved_inputs,
            trusted_invocation=inv_binding,
        )

        if val_res.is_valid and val_res.candidate is not None:
            cand = val_res.candidate
            try:
                score_num = objective_fn(cand)
            except Exception:  # noqa: BLE001 - untrusted callback cannot pick a winner
                score_error = "OBJECTIVE_EVALUATION_FAILED"
                break
            if not isinstance(score_num, Decimal) or not score_num.is_finite():
                score_error = "INVALID_OBJECTIVE_SCORE"
                break
            score_dec = score_num
            scores_dict[cand.candidate_id] = str(score_dec)

            family = cand.strategy.family_id if cand.strategy else "no_strategy"
            params_hash = (
                cand.strategy.strategy_ref.sha256 if cand.strategy else "0" * 64
            )
            evaluated_candidates.append(
                (score_dec, family, params_hash, cand.candidate_id, cand)
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

        cost = create_cost_receipt(
            receipt_id=f"cost-{actual_attempt_id}",
            scope=context.scope,
            category="selector_compute",
            billing_identity="conventional_billing",
            amount_basis="verified_zero",
            raw_evidence_ref=StoredArtifactRef(
                artifact_id=f"synthetic:offline-compute:{actual_attempt_id}",
                kind="other",
                content_hash=content_hash({
                    "attempt": actual_attempt_id,
                    "method": method_ref.model_dump(mode="python"),
                    "kind": "synthetic_no_external_provider_call",
                }),
                location="synthetic:offline-compute-only",
            ),
            attempt_id=actual_attempt_id,
            recorded_at=now,
        )
        recorder.record_cost_receipt(cost)

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
        entry for entry in evaluated_candidates
        if max_score - entry[0] <= tolerance
    ]
    winner = min(near_maximum, key=lambda entry: (entry[1], entry[2], entry[3]))[4]

    cand_ref = ArtifactReference(
        id=winner.candidate_id,
        version="v1",
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

    # Record verified zero cost receipt for deterministic local compute
    cost = create_cost_receipt(
        receipt_id=f"cost-{actual_attempt_id}",
        scope=context.scope,
        category="selector_compute",
        billing_identity="conventional_billing",
        amount_basis="verified_zero",
        raw_evidence_ref=StoredArtifactRef(
            artifact_id=f"synthetic:offline-compute:{actual_attempt_id}",
            kind="other",
            content_hash=content_hash({
                    "attempt": actual_attempt_id,
                    "method": method_ref.model_dump(mode="python"),
                    "kind": "synthetic_no_external_provider_call",
                }),
            location="synthetic:offline-compute-only",
        ),
        attempt_id=actual_attempt_id,
        recorded_at=now,
    )
    recorder.record_cost_receipt(cost)

    return ConventionalSelectorResult(
        is_success=True,
        status="VALID",
        selected_candidate=winner,
        candidate_scores=scores_dict,
        attempt_id=actual_attempt_id,
        attempt_event_id=terminal_event_id,
    )
