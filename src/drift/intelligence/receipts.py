"""Research receipt persistence, attempt lifecycle, and spend accounting.

Implements Slice K2 persistence store, immutable attempt events, and cost receipts
under Decision Packets DP-R3 (Spend/Unknowns) and DP-R4 (Persistence/Recovery).
"""

import json
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
from drift.serialization.canonical import canonical_json


def _validate_cost_chronology(
    *,
    incurred_start: datetime | None,
    incurred_end: datetime | None,
    recorded_at: datetime | None,
) -> None:
    """Reject impossible or ambiguous known spend clocks before hashing.

    An unknown timestamp remains None. A supplied timestamp is never silently
    assumed to be UTC, because semantic refusal must precede canonical JSON
    serialization, which cannot encode naive datetimes.
    """
    for label, stamp in (
        ("incurred_start", incurred_start),
        ("incurred_end", incurred_end),
        ("recorded_at", recorded_at),
    ):
        if stamp is not None and (
            not isinstance(stamp, datetime)
            or stamp.tzinfo is None
            or stamp.utcoffset() is None
        ):
            raise ValueError(f"INVALID_COST_TIMESTAMP: {label} lacks timezone")
    if (
        incurred_start is not None
        and incurred_end is not None
        and incurred_end < incurred_start
    ):
        raise ValueError("INVALID_COST_CHRONOLOGY: end precedes start")
    if recorded_at is not None and (
        (incurred_start is not None and recorded_at < incurred_start)
        or (incurred_end is not None and recorded_at < incurred_end)
    ):
        raise ValueError("INVALID_COST_CHRONOLOGY: recorded before incurred")


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
    if prior_attempt.status != "started" or prior_attempt.event_index != 0:
        raise ValueError("INVALID_ATTEMPT_TRANSITION: terminal requires a start")
    if (
        prior_attempt.started_at is None
        or prior_attempt.started_at.tzinfo is None
        or completed_at.tzinfo is None
        or completed_at < prior_attempt.started_at
    ):
        raise ValueError(
            "INVALID_ATTEMPT_TIME: terminal precedes start or lacks timezone"
        )
    if attempt_event_id == prior_attempt.attempt_event_id:
        raise ValueError("DUPLICATE_ATTEMPT_EVENT_ID")
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
        if amount is not None and amount != "0":
            raise ValueError("CONFLICTING_VERIFIED_ZERO_AMOUNT")
        if unknown_reason is not None:
            raise ValueError("CONFLICTING_VERIFIED_ZERO_UNKNOWN_REASON")
        if currency is not None and not currency.strip():
            raise ValueError("INVALID_VERIFIED_ZERO_CURRENCY")
        if raw_evidence_ref is None:
            raise ValueError(
                "verified_zero requires non-null raw_evidence_ref for audit"
            )
        amount_val = "0"
        currency_val = currency or "USD"
        unknown_reason_val = None
    elif amount_basis == "unknown":
        if amount is not None or currency is not None:
            raise ValueError("CONFLICTING_UNKNOWN_COST_FIELDS")
        if not unknown_reason or not unknown_reason.strip():
            raise ValueError("unknown amount_basis requires non-empty unknown_reason")
        amount_val = None
        currency_val = None
        unknown_reason_val = unknown_reason
    else:  # actual or estimate
        if not isinstance(amount, str) or not amount.strip():
            raise ValueError(f"{amount_basis} amount_basis requires non-null amount")
        try:
            value = Decimal(amount)
        except InvalidOperation as err:
            raise ValueError(f"invalid Decimal string: {amount}") from err
        if not value.is_finite() or value < 0:
            raise ValueError("INVALID_COST: amount must be finite and non-negative")
        if "e" in amount.lower() or amount.strip() != amount:
            raise ValueError("INVALID_COST: amount must be plain DecimalText")
        if not currency or not currency.strip():
            raise ValueError(f"{amount_basis} amount_basis requires non-null currency")
        amount_val = str(amount)
        currency_val = str(currency)
        unknown_reason_val = None

    # Named chronology errors must precede hashing or model construction.
    _validate_cost_chronology(
        incurred_start=incurred_start,
        incurred_end=incurred_end,
        recorded_at=recorded_at,
    )
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
    receipt = CostReceipt.model_validate(raw_dict)
    return receipt


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
        # model_copy(update=...) bypasses Pydantic validation. Re-deserialize
        # at the trust boundary before accepting a supposedly immutable value.
        attempt = AttemptRecord.model_validate(attempt.model_dump(mode="python"))
        event_id = attempt.attempt_event_id
        if event_id in self._attempts_by_event_id:
            existing = self._attempts_by_event_id[event_id]
            if existing.record_hash == attempt.record_hash:
                return
            raise ValueError(
                f"Integrity conflict: attempt event {event_id} already exists "
                f"with differing content"
            )

        prior_events = self._attempts_by_attempt_id.get(attempt.attempt_id, [])
        if not prior_events:
            if (
                attempt.event_index != 0
                or attempt.status != "started"
                or attempt.previous_event_ref is not None
                or attempt.started_at is None
                or attempt.completed_at is not None
            ):
                raise ValueError(
                    "INVALID_ATTEMPT_CHAIN: missing initial started event"
                )
        else:
            prev = prior_events[-1]
            backlink = attempt.previous_event_ref
            if (
                prev.status != "started"
                or attempt.status == "started"
                or attempt.event_index != prev.event_index + 1
                or backlink is None
                or backlink.id != prev.attempt_event_id
                or backlink.sha256 != prev.record_hash
                or attempt.attempt_event_id == prev.attempt_event_id
            ):
                raise ValueError(
                    "INVALID_ATTEMPT_CHAIN: broken or repeated transition"
                )
            prior_payload = prev.model_dump(mode="python")
            next_payload = attempt.model_dump(mode="python")
            for key in (
                "logical_request_id",
                "scope",
                "context_ref",
                "method_ref",
                "budget_ref",
                "producer",
                "started_at",
                "budget_authorization_ref",
                "retry_of",
                "duplicate_of",
            ):
                if next_payload[key] != prior_payload[key]:
                    raise ValueError(f"INVALID_ATTEMPT_CHAIN: changed {key}")
            if attempt.completed_at is None or attempt.completed_at < prev.started_at:
                raise ValueError("INVALID_ATTEMPT_CHAIN: completion time is invalid")
        self._attempts_by_event_id[event_id] = attempt
        self._attempts_by_attempt_id[attempt.attempt_id].append(attempt)

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
        # Check the supplied object before record-hash serialization too.
        # model_copy(update=...) may contain a naive datetime or a bad type.
        _validate_cost_chronology(
            incurred_start=cost.incurred_start,
            incurred_end=cost.incurred_end,
            recorded_at=cost.recorded_at,
        )
        cost = CostReceipt.model_validate(cost.model_dump(mode="python"))
        receipt_id = cost.receipt_id
        if receipt_id in self._costs_by_receipt_id:
            existing = self._costs_by_receipt_id[receipt_id]
            if existing.record_hash == cost.record_hash:
                return
            raise ValueError(
                f"Integrity conflict: cost receipt {receipt_id} already exists "
                f"with differing content"
            )
        if cost.supersedes_receipt_id is not None:
            prior = self._costs_by_receipt_id.get(cost.supersedes_receipt_id)
            if prior is None:
                raise ValueError("UNKNOWN_COST_SUPERSESSION: original receipt missing")
            if any(
                existing.supersedes_receipt_id == cost.supersedes_receipt_id
                for existing in self._costs_by_receipt_id.values()
            ):
                raise ValueError(
                    "DUPLICATE_COST_SUPERSESSION: competing correction receipts"
                )
            if (
                prior.attempt_id != cost.attempt_id
                or prior.scope != cost.scope
                or prior.category != cost.category
                or prior.billing_identity != cost.billing_identity
            ):
                raise ValueError("CROSS_SCOPE_COST_SUPERSESSION")
            if prior.amount_basis not in ("estimate", "unknown"):
                raise ValueError(
                    "INVALID_COST_SUPERSESSION: only estimates or unknowns"
                )
        self._costs_by_receipt_id[receipt_id] = cost

    def get_cost_receipt(self, receipt_id: str) -> CostReceipt | None:
        """Retrieve a cost receipt by receipt ID."""
        return self._costs_by_receipt_id.get(receipt_id)

    def get_cost_receipts_for_attempt(self, attempt_id: str) -> tuple[CostReceipt, ...]:
        """Retrieve all cost receipts linked to a given attempt ID."""
        return tuple(
            sorted(
                (
                    c
                    for c in self._costs_by_receipt_id.values()
                    if c.attempt_id == attempt_id
                ),
                key=lambda cost: cost.receipt_id,
            )
        )

    def get_unresolved_attempts(self) -> tuple[AttemptRecord, ...]:
        """Return all attempts whose latest event remains in 'started' status."""
        unresolved: list[AttemptRecord] = []
        for events in self._attempts_by_attempt_id.values():
            if events and events[-1].status == "started":
                unresolved.append(events[-1])
        return tuple(sorted(unresolved, key=lambda event: event.attempt_id))

    def export_events(self) -> list[dict[str, Any]]:
        """Export all recorded attempt events and cost receipts for persistence."""
        exported: list[dict[str, Any]] = []
        for att in sorted(
            self._attempts_by_event_id.values(),
            key=lambda event: (
                event.attempt_id, event.event_index, event.attempt_event_id
            ),
        ):
            exported.append(att.model_dump(mode="python"))
        # Deterministic topological order: the original estimate/unknown
        # receipt must precede its superseding correction, even when the
        # correction ID sorts first lexicographically. Otherwise export and
        # reload of valid lineage can fail closed on its own snapshots.
        pending = dict(self._costs_by_receipt_id)
        while pending:
            ready = sorted(
                (
                    cost for cost in pending.values()
                    if cost.supersedes_receipt_id not in pending
                ),
                key=lambda cost: cost.receipt_id,
            )
            if not ready:
                raise ValueError(
                    "INVALID_COST_LINEAGE: correction graph contains a cycle"
                )
            for cost in ready:
                exported.append(cost.model_dump(mode="python"))
                del pending[cost.receipt_id]
        return exported

    def load_events(self, events: Sequence[Mapping[str, Any]]) -> None:
        """Restore store from serialized JSON records, enforcing hash integrity."""
        # Commit only after the *entire* untrusted batch validates, so a
        # damaged recovery artifact cannot leave a half-loaded ledger.
        staged = ResearchReceiptStore()
        for existing in self._attempts_by_event_id.values():
            staged.record_attempt(existing)
        for existing in self._costs_by_receipt_id.values():
            staged.record_cost_receipt(existing)
        for ev in events:
            kind = ev.get("kind")
            if kind == "attempt":
                staged.record_attempt(AttemptRecord.model_validate(ev))
            elif kind == "raw_cost":
                staged.record_cost_receipt(CostReceipt.model_validate(ev))
            else:
                raise ValueError(f"Unknown receipt event kind: {kind}")
        self._attempts_by_event_id = staged._attempts_by_event_id
        self._attempts_by_attempt_id = staged._attempts_by_attempt_id
        self._costs_by_receipt_id = staged._costs_by_receipt_id


    def export_canonical_jsonl(self) -> bytes:
        """Expose exact canonical bytes for a separate durable M0 ledger adapter.

        This in-memory projection DOES NOT itself provide fsync or a committed
        M0 event. The platform persistence owner must durably append the bytes.
        """
        return b"".join(
            canonical_json(record) + b"\n" for record in self.export_events()
        )

    def load_canonical_jsonl(self, payload: bytes) -> None:
        """Atomically verify a complete retained JSONL snapshot on replay."""
        if payload and not payload.endswith(b"\n"):
            raise ValueError("TRUNCATED_RECEIPT_JOURNAL: final newline is missing")

        def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("DUPLICATE_RECEIPT_JSON_KEY")
                result[key] = value
            return result

        records: list[Mapping[str, Any]] = []
        for line in payload.splitlines():
            if not line:
                raise ValueError("INVALID_RECEIPT_JOURNAL: empty row")
            decoded = json.loads(
                line,
                object_pairs_hook=no_duplicate_keys,
                parse_constant=lambda _c: (_ for _ in ()).throw(
                    ValueError("INVALID_RECEIPT_JOURNAL: non-finite JSON")
                ),
            )
            if not isinstance(decoded, dict):
                raise ValueError("INVALID_RECEIPT_JOURNAL: object required")
            records.append(decoded)
        self.load_events(records)
