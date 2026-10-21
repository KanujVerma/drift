"""Synthetic, read-only UNKNOWN execution event preflight for #533/#411.

Proposed A1 transitions are NOT implemented in the broker, router or journal.
Neither record strings nor hashes authorize side-effecting operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_MONEY = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{1,12})?\Z")
_ROOT_FIELDS = frozenset({
    "profile", "account_key", "environment_ref", "journal_ref",
    "context_ref", "intent_hash", "client_token", "events",
})
_EVENT_FIELDS = frozenset({
    "event_id", "sequence", "previous_event_id", "kind",
    "account_key", "environment_ref", "journal_ref",
    "intent_hash", "client_token", "observed_utc",
    "evidence_ref", "reason_code", "broker_status",
    "cumulative_qty", "cumulative_fee_usd", "effect_id",
    "effect_quantity", "authority_ref", "quiescence_ref",
    "resolution_ref", "resume_mandate_ref", "expires_utc",
})
_KIND = frozenset({
    "PREPARED", "SEND_STARTED", "OBSERVED_UNKNOWN",
    "OBSERVED_CONFIRMED", "NOT_SENT", "PAUSED",
    "CANCEL_REQUESTED", "FILL_EFFECT", "RESOLVED", "RESUMED",
})
_BROKER_STATUS = frozenset({
    "new", "acknowledged", "partially_filled", "filled",
    "canceled", "rejected", "expired",
})
_UNKNOWN_REASONS = frozenset({
    "submission_unconfirmed", "cancellation_unconfirmed",
    "response_unrecognized", "evidence_conflict",
    "recovery_required", "journal_unavailable",
    "legacy_uncertainty",
})


@dataclass(frozen=True, slots=True)
class UnknownReplayPreflight:
    """Claims only; a reviewable fixture never establishes trusted state."""

    structurally_reviewable: bool
    claimed_phase: str
    account_hold_required: bool
    latest_broker_knowledge: str
    last_confirmed_broker_status: str | None
    last_confirmed_cumulative_qty: int | None
    last_confirmed_cumulative_fee_usd: Decimal | None
    distinct_reported_fill_effect_qty: int | None
    reasons: tuple[str, ...]

    @property
    def authorizes_dispatch_or_resumption(self) -> bool:
        return False

    @property
    def authenticates_journal_broker_or_ledger(self) -> bool:
        return False


def _plain_json(value: object, depth: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value) <= 4096
    if type(value) is list:
        return len(value) <= 512 and all(
            _plain_json(v, depth + 1, budget) for v in value
        )
    if type(value) is dict:
        return len(value) <= 128 and all(
            type(k) is str and len(k) <= 128
            and _plain_json(v, depth + 1, budget)
            for k, v in value.items()
        )
    return False


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _time(value: object) -> datetime | None:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timedelta(0) else None


def _money(value: object) -> Decimal | None:
    if type(value) is not str or len(value) > 40:
        return None
    if _MONEY.fullmatch(value) is None:
        return None
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


def _result(
    phase: str,
    known: str,
    status: str | None,
    qty: int | None,
    fee: Decimal | None,
    effect_qty: int,
    problems: list[str],
) -> UnknownReplayPreflight:
    """A self-declared RESUMED phase still requires a verified account hold."""
    valid = not problems
    return UnknownReplayPreflight(
        valid,
        phase if valid else "INVALID",
        True,
        known if valid else "UNAVAILABLE",
        status if valid else None,
        qty if valid else None,
        fee if valid else None,
        effect_qty if valid else None,
        tuple(problems),
    )


def preflight_unknown_execution_replay(payload: object) -> UnknownReplayPreflight:
    """Classify A1-style mock event order; never perform or permit operations."""
    if not _plain_json(payload, 0, [4096]):
        return _result("INVALID", "UNAVAILABLE", None, None, None, 0,
                       ["payload.not_plain_json"])
    if type(payload) is not dict:
        return _result("INVALID", "UNAVAILABLE", None, None, None, 0,
                       ["payload.not_plain_object"])
    root = cast(dict[str, object], payload)
    problems: list[str] = []
    if set(root) != _ROOT_FIELDS:
        problems.append("payload.fields.not_exact")
    if root.get("profile") != "synthetic-unknown-replay-review-v1":
        problems.append("profile.invalid")
    for field in ("account_key", "environment_ref", "journal_ref", "context_ref",
                  "client_token"):
        if not _text(root.get(field)):
            problems.append(f"{field}.missing")
    intent_hash = root.get("intent_hash")
    if type(intent_hash) is not str or _SHA.fullmatch(intent_hash) is None:
        problems.append("intent_hash.invalid")
    events = root.get("events")
    if type(events) is not list:
        problems.append("events.not_plain_list")
        events = []

    prior: dict[str, dict[str, object]] = {}
    effect_ids: dict[str, tuple[object, ...]] = {}
    last_id: str | None = None
    last_observed: datetime | None = None
    phase = "NONE"
    knowledge = "NONE"
    last_status: str | None = None
    last_qty: int | None = None
    last_fee: Decimal | None = None
    effects_total = 0
    send_started = False
    unknown_seen = False
    resolution_claimed = False
    for i, event_raw in enumerate(events):
        tag = f"events.{i}"
        if type(event_raw) is not dict:
            problems.append(f"{tag}.not_plain_object")
            continue
        event = cast(dict[str, object], event_raw)
        if set(event) != _EVENT_FIELDS:
            problems.append(f"{tag}.fields.not_exact")
        event_id = event.get("event_id")
        if not _text(event_id):
            problems.append(f"{tag}.event_id.missing")
            continue
        assert isinstance(event_id, str)
        original = prior.get(event_id)
        if original is not None:
            if original != event:
                problems.append(f"{tag}.event_id.conflicting_redelivery")
            continue
        seq = event.get("sequence")
        if type(seq) is not int or seq != len(prior) + 1:
            problems.append(f"{tag}.sequence.gap_or_out_of_order")
        if event.get("previous_event_id") != last_id:
            problems.append(f"{tag}.predecessor_mismatch")
        for field in (
            "account_key", "environment_ref", "journal_ref",
            "intent_hash", "client_token",
        ):
            if event.get(field) != root.get(field):
                problems.append(f"{tag}.{field}.binding_mismatch")
        observed = _time(event.get("observed_utc"))
        if observed is None:
            problems.append(f"{tag}.observed_utc.invalid")
        if (
            observed is not None and last_observed is not None
            and observed <= last_observed
        ):
            problems.append(f"{tag}.observation_order.not_strict")
        if observed is not None:
            last_observed = observed
        if not _text(event.get("evidence_ref")):
            problems.append(f"{tag}.evidence_ref.missing")

        kind = event.get("kind")
        if type(kind) is not str or kind not in _KIND:
            problems.append(f"{tag}.kind.invalid")
            prior[event_id] = event
            last_id = event_id
            continue
        prior[event_id] = event
        last_id = event_id

        for field in ("broker_status", "cumulative_qty", "cumulative_fee_usd"):
            if kind != "OBSERVED_CONFIRMED" and event.get(field) is not None:
                problems.append(f"{tag}.{field}.not_allowed_for_{kind}")
        for field in ("effect_id", "effect_quantity"):
            if kind != "FILL_EFFECT" and event.get(field) is not None:
                problems.append(f"{tag}.{field}.not_allowed_for_{kind}")
        if kind != "OBSERVED_UNKNOWN" and event.get("reason_code") is not None:
            problems.append(f"{tag}.reason_code.not_allowed")
        if kind != "RESOLVED" and (
            event.get("quiescence_ref") is not None
            or event.get("resolution_ref") is not None
        ):
            problems.append(f"{tag}.resolution_fields.unexpected")
        if kind != "RESUMED" and (
            event.get("resume_mandate_ref") is not None
            or event.get("expires_utc") is not None
        ):
            problems.append(f"{tag}.resume_fields.unexpected")
        if kind not in ("RESOLVED", "RESUMED", "NOT_SENT") and (
            event.get("authority_ref") is not None
        ):
            problems.append(f"{tag}.authority_ref.unexpected")

        if kind == "PREPARED":
            if phase != "NONE":
                problems.append("account.new_operation_while_existing_or_held")
            else:
                phase = "PREPARED"
        elif kind == "NOT_SENT":
            if phase != "PREPARED" or send_started:
                problems.append(f"{tag}.not_sent_without_proven_unsent")
            if not _text(event.get("authority_ref")):
                problems.append(f"{tag}.local_refusal_authority.missing")
            if not _text(event.get("evidence_ref")):
                problems.append(f"{tag}.journal_proof_no_send.missing")
            phase = "NOT_SENT_CLAIMED"
            knowledge = "NOT_SENT"
        elif kind == "SEND_STARTED":
            if phase != "PREPARED" or send_started:
                problems.append(f"{tag}.send_started_without_unique_prepare")
            send_started = True
            phase = "SEND_STARTED"
            knowledge = "UNKNOWN"
        elif kind == "OBSERVED_UNKNOWN":
            if not send_started or phase in (
                "NOT_SENT_CLAIMED", "RESUMED_CLAIMED",
            ):
                problems.append(f"{tag}.unknown_without_possible_send")
            if event.get("reason_code") not in _UNKNOWN_REASONS:
                problems.append(f"{tag}.unknown_reason.invalid")
            phase = "UNKNOWN"
            knowledge = "UNKNOWN"
            unknown_seen = True
        elif kind == "OBSERVED_CONFIRMED":
            if not send_started or phase in (
                "NOT_SENT_CLAIMED", "RESUMED_CLAIMED",
            ):
                problems.append(f"{tag}.confirmed_without_possible_send")
            status = event.get("broker_status")
            if type(status) is not str or status not in _BROKER_STATUS:
                problems.append(f"{tag}.broker_status.unrecognized")
            count = event.get("cumulative_qty")
            if count is not None and (
                type(count) is not int or count < 0
            ):
                problems.append(f"{tag}.cumulative_qty.invalid")
                count = None
            fee = event.get("cumulative_fee_usd")
            parsed_fee = _money(fee) if fee is not None else None
            if fee is not None and parsed_fee is None:
                problems.append(f"{tag}.cumulative_fee_usd.invalid")
            if last_qty is not None and count is not None and count < last_qty:
                problems.append(f"{tag}.cumulative_qty.regressed")
            if last_fee is not None and parsed_fee is not None:
                if parsed_fee < last_fee:
                    problems.append(f"{tag}.cumulative_fee_usd.regressed")
            if type(status) is str and status in _BROKER_STATUS:
                last_status = status
            if count is not None:
                last_qty = count
            if parsed_fee is not None:
                last_fee = parsed_fee
            elif fee is None:
                # An absent current fee must not be replaced by a historical zero.
                last_fee = None
            phase = "CONFIRMED_OBSERVATION"
            knowledge = "CONFIRMED"
        elif kind == "CANCEL_REQUESTED":
            if not send_started:
                problems.append(f"{tag}.cancel_without_original_submission")
            # Cancellation request is not a confirmed canceled broker outcome.
            phase = "CANCEL_PENDING"
            knowledge = "UNKNOWN"
            unknown_seen = True
        elif kind == "PAUSED":
            if phase == "NONE":
                problems.append(f"{tag}.pause_before_operation")
            # Pause never clears pending fills or previously known quantity.
            phase = "PAUSED_WITH_OBLIGATIONS"
        elif kind == "FILL_EFFECT":
            if not send_started:
                problems.append(f"{tag}.fill_without_send")
            effect_id = event.get("effect_id")
            effect_qty = event.get("effect_quantity")
            if not _text(effect_id):
                problems.append(f"{tag}.effect_id.missing")
            if type(effect_qty) is not int or effect_qty <= 0:
                problems.append(f"{tag}.effect_quantity.invalid")
            if _text(effect_id) and type(effect_qty) is int and effect_qty > 0:
                assert isinstance(effect_id, str)
                signature = (
                    effect_qty, event.get("intent_hash"),
                    event.get("account_key"), event.get("client_token"),
                )
                original_effect = effect_ids.get(effect_id)
                if original_effect is not None:
                    if original_effect != signature:
                        problems.append(f"{tag}.effect_id.conflicting_redelivery")
                else:
                    effect_ids[effect_id] = signature
                    effects_total += effect_qty
                if last_qty is None or effects_total > last_qty:
                    problems.append(f"{tag}.effect_not_backed_by_known_fill")
        elif kind == "RESOLVED":
            if not unknown_seen:
                problems.append(f"{tag}.resolution_without_uncertainty")
            if phase in ("RESOLVED_CLAIMED", "RESUMED_CLAIMED"):
                problems.append(f"{tag}.duplicate_resolution")
            for field in ("authority_ref", "quiescence_ref", "resolution_ref"):
                if not _text(event.get(field)):
                    problems.append(f"{tag}.{field}.missing")
            # A string asserting quiescence is not effective egress fencing.
            phase = "RESOLVED_CLAIMED"
            resolution_claimed = True
        elif kind == "RESUMED":
            if phase != "RESOLVED_CLAIMED" or not resolution_claimed:
                problems.append(f"{tag}.resumption_without_resolution")
            for field in ("authority_ref", "resume_mandate_ref"):
                if not _text(event.get(field)):
                    problems.append(f"{tag}.{field}.missing")
            expiry = _time(event.get("expires_utc"))
            if expiry is None:
                problems.append(f"{tag}.expires_utc.invalid")
            elif observed is not None and expiry <= observed:
                problems.append(f"{tag}.authorization_expired")
            phase = "RESUMED_CLAIMED"
            # Remains unsafe to authorize any operation without trusted verifier.
            knowledge = "UNVERIFIED_RESUMPTION"

    return _result(
        phase, knowledge, last_status, last_qty,
        last_fee, effects_total, problems,
    )
