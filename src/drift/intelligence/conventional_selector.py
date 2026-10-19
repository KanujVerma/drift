"""Conventional candidate selector and optimizer R seam runtime.

Implements Slice K3 conventional selector over preregistered finite pools under DP-R6.
Provides deterministic scoring, alphanumeric tie-breaking, and isolated state (T13).
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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
    objective_fn: Callable[[ResearchCandidate], Decimal | float],
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
    now = datetime.now(UTC)
    actual_attempt_id = attempt_id or str(uuid4())
    actual_request_id = logical_request_id or str(uuid4())
    start_event_id = str(uuid4())
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

    for idx, choice_item in enumerate(candidate_pool):
        cand_id = f"cand-r-{actual_attempt_id[:8]}-{idx}"
        raw_dict = (
            choice_item.model_dump(mode="python")
            if isinstance(choice_item, RawChoice)
            else dict(choice_item)
        )

        inv_binding = TrustedInvocationBinding(
            attempt_id=actual_attempt_id,
            candidate_id=cand_id,
            validation_id=str(uuid4()),
            policy_ref=validation_policy,
            raw_output_ref=ArtifactReference(
                id=f"fixture:pool-choice-{idx}",
                version="v1",
                sha256=content_hash(raw_dict),
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
            score_num = objective_fn(cand)
            score_dec = Decimal(str(score_num))
            scores_dict[cand.candidate_id] = str(score_dec)

            family = cand.strategy.family_id if cand.strategy else "no_strategy"
            params_hash = (
                cand.strategy.strategy_ref.sha256 if cand.strategy else "0" * 64
            )
            evaluated_candidates.append(
                (score_dec, family, params_hash, cand.candidate_id, cand)
            )

    # 3. Handle case where no candidate in pool was valid
    terminal_event_id = str(uuid4())
    if not evaluated_candidates:
        terminal_attempt = create_terminal_attempt(
            prior_attempt=started_record,
            attempt_event_id=terminal_event_id,
            completed_at=now,
            status="rejected",
            reason_codes=("NO_ELIGIBLE_CANDIDATE",),
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
                artifact_id="art-zero",
                kind="other",
                content_hash="0" * 64,
                location="fixture:zero",
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
            reason="No candidate in pool satisfied validation constraints",
        )

    # 4. Deterministic sort and tie-breaking:
    # Sort key: (-score, family, params_hash, candidate_id)
    evaluated_candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    winner = evaluated_candidates[0][4]

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
            artifact_id="art-zero",
            kind="other",
            content_hash="0" * 64,
            location="fixture:zero",
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
