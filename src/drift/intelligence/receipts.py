"""Research receipt persistence, attempt lifecycle, and spend accounting.

Implements Slice K2 persistence store, immutable attempt events, and cost receipts
under Decision Packets DP-R3 (Spend/Unknowns) and DP-R4 (Persistence/Recovery).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CostReceipt,
    Scope,
    StoredArtifactRef,
    UsageEntry,
    compute_record_hash,
)


def create_started_attempt(
    *,
    attempt_id: str,
    logical_request_id: str,
    attempt_event_id: str,
    scope: Scope,
    context_ref: ArtifactReference,
    method_ref: ArtifactReference,
    budget_ref: ArtifactReference,
    producer: str,
    started_at: datetime,
    retry_of: str | None = None,
    duplicate_of: str | None = None,
    budget_authorization_ref: ArtifactReference | None = None,
) -> AttemptRecord:
    """Create the initial started event for an attempt (event_index=0)."""
    raw_dict: dict[str, Any] = {
        "profile": "drift-research/1-draft",
        "kind": "attempt",
        "attempt_id": attempt_id,
        "logical_request_id": logical_request_id,
        "attempt_event_id": attempt_event_id,
        "event_index": 0,
        "previous_event_ref": None,
        "retry_of": retry_of,
        "duplicate_of": duplicate_of,
        "scope": scope.model_dump(mode="python"),
        "context_ref": context_ref.model_dump(mode="python"),
        "method_ref": method_ref.model_dump(mode="python"),
        "budget_ref": budget_ref.model_dump(mode="python"),
        "producer": producer,
        "started_at": started_at,
        "completed_at": None,
        "status": "started",
        "validation_ref": None,
        "candidate_ref": None,
        "model_replay_ref": None,
        "cost_receipt_ids": (),
        "reason_codes": (),
        "failure_artifact_ref": None,
        "budget_authorization_ref": (
            budget_authorization_ref.model_dump(mode="python")
            if budget_authorization_ref
            else None
        ),
    }
    rec_hash = compute_record_hash(raw_dict)
    raw_dict["record_hash"] = rec_hash
    return AttemptRecord.model_validate(raw_dict)


def create_terminal_attempt(
    *,
    prior_attempt: AttemptRecord,
    attempt_event_id: str,
    completed_at: datetime,
    status: Literal["completed", "failed", "rejected"],
    validation_ref: ArtifactReference | None = None,
    candidate_ref: ArtifactReference | None = None,
    model_replay_ref: ArtifactReference | None = None,
    cost_receipt_ids: Sequence[str] = (),
    reason_codes: Sequence[str] = (),
    failure_artifact_ref: ArtifactReference | None = None,
) -> AttemptRecord:
    """Create an immutable terminal event linking to the prior lifecycle event."""
    prev_ref = ArtifactReference(
        id=prior_attempt.attempt_event_id,
        version="v1",
        sha256=prior_attempt.record_hash,
    )
    raw_dict: dict[str, Any] = {
        "profile": "drift-research/1-draft",
        "kind": "attempt",
        "attempt_id": prior_attempt.attempt_id,
        "logical_request_id": prior_attempt.logical_request_id,
        "attempt_event_id": attempt_event_id,
        "event_index": prior_attempt.event_index + 1,
        "previous_event_ref": prev_ref.model_dump(mode="python"),
        "retry_of": prior_attempt.retry_of,
        "duplicate_of": prior_attempt.duplicate_of,
        "scope": prior_attempt.scope.model_dump(mode="python"),
        "context_ref": prior_attempt.context_ref.model_dump(mode="python"),
        "method_ref": prior_attempt.method_ref.model_dump(mode="python"),
        "budget_ref": prior_attempt.budget_ref.model_dump(mode="python"),
        "producer": prior_attempt.producer,
        "started_at": prior_attempt.started_at,
        "completed_at": completed_at,
        "status": status,
        "validation_ref": (
            validation_ref.model_dump(mode="python") if validation_ref else None
        ),
        "candidate_ref": (
            candidate_ref.model_dump(mode="python") if candidate_ref else None
        ),
        "model_replay_ref": (
            model_replay_ref.model_dump(mode="python") if model_replay_ref else None
        ),
        "cost_receipt_ids": tuple(cost_receipt_ids),
        "reason_codes": tuple(reason_codes),
        "failure_artifact_ref": (
            failure_artifact_ref.model_dump(mode="python")
            if failure_artifact_ref
            else None
        ),
        "budget_authorization_ref": (
            prior_attempt.budget_authorization_ref.model_dump(mode="python")
            if prior_attempt.budget_authorization_ref
            else None
        ),
    }
    rec_hash = compute_record_hash(raw_dict)
    raw_dict["record_hash"] = rec_hash
    return AttemptRecord.model_validate(raw_dict)


def create_cost_receipt(
    *,
    receipt_id: str,
    scope: Scope,
    category: str,
    billing_identity: str,
    amount_basis: Literal["actual", "estimate", "unknown", "verified_zero"],
    attempt_id: str | None = None,
    raw_evidence_ref: StoredArtifactRef | None = None,
    incurred_start: datetime | None = None,
    incurred_end: datetime | None = None,
    recorded_at: datetime | None = None,
    amount: str | None = None,
    currency: str | None = None,
    unknown_reason: str | None = None,
    pricing_ref: ArtifactReference | None = None,
    usage: Sequence[UsageEntry] = (),
    shared_work_ref: ArtifactReference | None = None,
    supersedes_receipt_id: str | None = None,
) -> CostReceipt:
    """Create a validated CostReceipt adhering strictly to DP-R3."""
    if amount_basis == "verified_zero":
        if raw_evidence_ref is None:
            raise ValueError(
                "verified_zero requires non-null raw_evidence_ref for audit"
            )
        amount_val = "0"
        currency_val = currency or "USD"
        unknown_reason_val = None
    elif amount_basis == "unknown":
        if not unknown_reason:
            raise ValueError("unknown amount_basis requires non-empty unknown_reason")
        amount_val = None
        currency_val = None
        unknown_reason_val = unknown_reason
    else:  # actual or estimate
        if amount is None or not str(amount).strip():
            raise ValueError(f"{amount_basis} amount_basis requires non-null amount")
        try:
            Decimal(amount)
        except InvalidOperation as err:
            raise ValueError(f"invalid Decimal string: {amount}") from err
        if not currency or not currency.strip():
            raise ValueError(f"{amount_basis} amount_basis requires non-null currency")
        amount_val = str(amount)
        currency_val = str(currency)
        unknown_reason_val = None

    raw_dict: dict[str, Any] = {
        "profile": "drift-research/1-draft",
        "kind": "raw_cost",
        "receipt_id": receipt_id,
        "scope": scope.model_dump(mode="python"),
        "attempt_id": attempt_id,
        "category": category,
        "billing_identity": billing_identity,
        "raw_evidence_ref": (
            raw_evidence_ref.model_dump(mode="python") if raw_evidence_ref else None
        ),
        "incurred_start": incurred_start,
        "incurred_end": incurred_end,
        "recorded_at": recorded_at,
        "amount": amount_val,
        "currency": currency_val,
        "amount_basis": amount_basis,
        "unknown_reason": unknown_reason_val,
        "pricing_ref": (pricing_ref.model_dump(mode="python") if pricing_ref else None),
        "usage": tuple(u.model_dump(mode="python") for u in usage),
        "shared_work_ref": (
            shared_work_ref.model_dump(mode="python") if shared_work_ref else None
        ),
        "supersedes_receipt_id": supersedes_receipt_id,
    }
    rec_hash = compute_record_hash(raw_dict)
    raw_dict["record_hash"] = rec_hash
    return CostReceipt.model_validate(raw_dict)


class ResearchReceiptStore:
    """In-memory append-only ledger store for research attempts and cost receipts.

    Implements DP-R4 idempotency, duplicate protection, and crash-recovery readback.
    """

    def __init__(self) -> None:
        self._attempts_by_event_id: dict[str, AttemptRecord] = {}
        self._attempts_by_attempt_id: dict[str, list[AttemptRecord]] = defaultdict(list)
        self._costs_by_receipt_id: dict[str, CostReceipt] = {}

    def record_attempt(self, attempt: AttemptRecord) -> None:
        """Record an attempt lifecycle event idempotently or fail on conflict."""
        event_id = attempt.attempt_event_id
        if event_id in self._attempts_by_event_id:
            existing = self._attempts_by_event_id[event_id]
            if existing.record_hash == attempt.record_hash:
                return
            raise ValueError(
                f"Integrity conflict: attempt event {event_id} already exists "
                f"with differing content"
            )

        self._attempts_by_event_id[event_id] = attempt
        self._attempts_by_attempt_id[attempt.attempt_id].append(attempt)
        # Sort events by event_index
        self._attempts_by_attempt_id[attempt.attempt_id].sort(
            key=lambda e: e.event_index
        )

    def get_attempt_event(self, attempt_event_id: str) -> AttemptRecord | None:
        """Retrieve a specific attempt lifecycle event by event ID."""
        return self._attempts_by_event_id.get(attempt_event_id)

    def get_attempt_events(self, attempt_id: str) -> tuple[AttemptRecord, ...]:
        """Retrieve all lifecycle events for an attempt sorted by event_index."""
        return tuple(self._attempts_by_attempt_id.get(attempt_id, []))

    def get_latest_attempt(self, attempt_id: str) -> AttemptRecord | None:
        """Retrieve the latest lifecycle event for an attempt."""
        events = self._attempts_by_attempt_id.get(attempt_id)
        if not events:
            return None
        return events[-1]

    def record_cost_receipt(self, cost: CostReceipt) -> None:
        """Record a cost receipt idempotently or fail on conflict."""
        receipt_id = cost.receipt_id
        if receipt_id in self._costs_by_receipt_id:
            existing = self._costs_by_receipt_id[receipt_id]
            if existing.record_hash == cost.record_hash:
                return
            raise ValueError(
                f"Integrity conflict: cost receipt {receipt_id} already exists "
                f"with differing content"
            )
        self._costs_by_receipt_id[receipt_id] = cost

    def get_cost_receipt(self, receipt_id: str) -> CostReceipt | None:
        """Retrieve a cost receipt by receipt ID."""
        return self._costs_by_receipt_id.get(receipt_id)

    def get_cost_receipts_for_attempt(self, attempt_id: str) -> tuple[CostReceipt, ...]:
        """Retrieve all cost receipts linked to a given attempt ID."""
        return tuple(
            c for c in self._costs_by_receipt_id.values() if c.attempt_id == attempt_id
        )

    def get_unresolved_attempts(self) -> tuple[AttemptRecord, ...]:
        """Return all attempts whose latest event remains in 'started' status."""
        unresolved: list[AttemptRecord] = []
        for events in self._attempts_by_attempt_id.values():
            if events and events[-1].status == "started":
                unresolved.append(events[-1])
        return tuple(unresolved)

    def export_events(self) -> list[dict[str, Any]]:
        """Export all recorded attempt events and cost receipts for persistence."""
        exported: list[dict[str, Any]] = []
        for att in self._attempts_by_event_id.values():
            exported.append(att.model_dump(mode="python"))
        for cost in self._costs_by_receipt_id.values():
            exported.append(cost.model_dump(mode="python"))
        return exported

    def load_events(self, events: Sequence[Mapping[str, Any]]) -> None:
        """Restore store from serialized JSON records, enforcing hash integrity."""
        for ev in events:
            kind = ev.get("kind")
            if kind == "attempt":
                att = AttemptRecord.model_validate(ev)
                self.record_attempt(att)
            elif kind == "raw_cost":
                cost = CostReceipt.model_validate(ev)
                self.record_cost_receipt(cost)
            else:
                raise ValueError(f"Unknown receipt event kind: {kind}")
