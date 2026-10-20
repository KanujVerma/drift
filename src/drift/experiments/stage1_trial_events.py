"""Stage 1 auditable trial-event chain.

Provides deterministic, immutable Stage 1 trial events and chain verification
for local synthetic/offline experiment integrity under schema version
drift-experiment/1-draft.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from drift.serialization.canonical import content_hash

SCHEMA_VERSION: str = "drift-experiment/1-draft"

ALLOWED_EVENT_KINDS: frozenset[str] = frozenset(
    {
        "OPPORTUNITY_CREATED",
        "INPUTS_BOUND",
        "PROPOSAL_RECORDED",
        "ELIGIBILITY_RECORDED",
        "MANDATE_VERDICT_RECORDED",
        "ORDERS_STAGED",
        "FILLS_RECORDED",
        "RESULT_BOUND",
        "COSTS_BOUND",
        "TRIAL_FINALIZED",
    }
)

_SHA256_PATTERN: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_PATTERN: re.Pattern[str] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)


@dataclass(frozen=True, slots=True)
class Stage1TrialEvent:
    schema_version: str
    event_id: str
    trial_id: str
    event_index: int
    previous_event_reference: str
    event_kind: str
    recorded_at: str
    producer_evidence_references: tuple[str, ...]
    payload_reference: str
    payload_hash: str
    event_hash: str


def _canonical_recorded_at(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise ValueError("recorded_at must be datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")

    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_persisted_recorded_at(value: object) -> None:
    if not isinstance(value, str) or type(value) is not str:
        raise ValueError("recorded_at must be an exact str")
    if not _TIMESTAMP_PATTERN.fullmatch(value):
        msg = (
            f"recorded_at string {value!r} does not match canonical format "
            "YYYY-MM-DDTHH:MM:SS.ffffffZ"
        )
        raise ValueError(msg)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(
            f"recorded_at string {value!r} contains invalid calendar date or time"
        ) from exc
    roundtrip = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if roundtrip != value:
        raise ValueError(
            f"recorded_at string {value!r} failed roundtrip: {roundtrip!r}"
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and type(value) is str
        and bool(_SHA256_PATTERN.fullmatch(value))
    )


def _event_preimage(event: Stage1TrialEvent) -> dict[str, object]:
    return {
        "schema_version": event.schema_version,
        "event_id": event.event_id,
        "trial_id": event.trial_id,
        "event_index": event.event_index,
        "previous_event_reference": event.previous_event_reference,
        "event_kind": event.event_kind,
        "recorded_at": event.recorded_at,
        "producer_evidence_references": list(event.producer_evidence_references),
        "payload_reference": event.payload_reference,
        "payload_hash": event.payload_hash,
    }


def _validate_stage1_trial_event(
    event: object,
    expected_trial_id: str | None = None,
) -> None:
    if not isinstance(event, Stage1TrialEvent):
        raise ValueError("event must be a Stage1TrialEvent instance")

    if type(event.schema_version) is not str or event.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {SCHEMA_VERSION!r}, got {event.schema_version!r}"
        )

    if (
        not isinstance(event.trial_id, str)
        or type(event.trial_id) is not str
        or not event.trial_id.strip()
        or event.trial_id != event.trial_id.strip()
    ):
        raise ValueError("trial_id must be a non-empty string without whitespace")

    if expected_trial_id is not None and event.trial_id != expected_trial_id:
        msg = (
            f"event trial_id {event.trial_id!r} does not match "
            f"expected {expected_trial_id!r}"
        )
        raise ValueError(msg)

    if (
        isinstance(event.event_index, bool)
        or type(event.event_index) is not int
        or event.event_index < 0
    ):
        raise ValueError("event_index must be a non-negative non-Boolean integer")

    expected_event_id = f"{event.trial_id}:EVT-{event.event_index}"
    if type(event.event_id) is not str or event.event_id != expected_event_id:
        raise ValueError(
            f"event_id must be {expected_event_id!r}, got {event.event_id!r}"
        )

    if type(event.previous_event_reference) is not str:
        raise ValueError("previous_event_reference must be a str")

    if event.event_index == 0:
        if event.previous_event_reference != "ROOT":
            msg = (
                "Root event index 0 must have previous_event_reference 'ROOT', "
                f"got {event.previous_event_reference!r}"
            )
            raise ValueError(msg)
    else:
        if not _is_sha256(event.previous_event_reference):
            msg = (
                "Non-root previous_event_reference must be lowercase 64-hex "
                f"SHA-256 digest, got {event.previous_event_reference!r}"
            )
            raise ValueError(msg)

    if type(event.event_kind) is not str or event.event_kind not in ALLOWED_EVENT_KINDS:
        msg = f"event_kind {event.event_kind!r} not in ALLOWED_EVENT_KINDS"
        raise ValueError(msg)

    _validate_persisted_recorded_at(event.recorded_at)

    if type(event.producer_evidence_references) is not tuple:
        raise ValueError("producer_evidence_references must be an immutable tuple")

    for ref in event.producer_evidence_references:
        if not _is_sha256(ref):
            msg = (
                f"producer_evidence_references item {ref!r} is not a "
                "lowercase 64-hex SHA-256"
            )
            raise ValueError(msg)

    if list(event.producer_evidence_references) != sorted(
        event.producer_evidence_references
    ):
        raise ValueError(
            "producer_evidence_references must be sorted lexicographically"
        )

    if (
        not isinstance(event.payload_reference, str)
        or type(event.payload_reference) is not str
        or not event.payload_reference.strip()
    ):
        raise ValueError("payload_reference must be a non-empty string")

    if not _is_sha256(event.payload_hash):
        msg = f"payload_hash {event.payload_hash!r} is not a valid SHA-256 digest"
        raise ValueError(msg)

    if not _is_sha256(event.event_hash):
        msg = f"event_hash {event.event_hash!r} is not a valid SHA-256 digest"
        raise ValueError(msg)

    preimage = _event_preimage(event)
    expected_event_hash = content_hash(preimage)
    if event.event_hash != expected_event_hash:
        msg = (
            f"event_hash mismatch: expected {expected_event_hash}, "
            f"got {event.event_hash}"
        )
        raise ValueError(msg)


def build_stage1_trial_event(
    *,
    trial_id: str,
    event_index: int,
    previous_event_reference: str,
    event_kind: str,
    recorded_at: datetime,
    producer_evidence_references: Sequence[str],
    payload_reference: str,
    payload_hash: str,
) -> Stage1TrialEvent:
    if (
        not isinstance(trial_id, str)
        or type(trial_id) is not str
        or not trial_id.strip()
        or trial_id != trial_id.strip()
    ):
        raise ValueError("trial_id must be a non-empty string without whitespace")

    if isinstance(event_index, bool) or type(event_index) is not int or event_index < 0:
        raise ValueError("event_index must be a non-negative non-Boolean integer")

    if type(previous_event_reference) is not str:
        raise ValueError("previous_event_reference must be a str")

    if event_index == 0:
        if previous_event_reference != "ROOT":
            msg = (
                "Root event index 0 must have previous_event_reference 'ROOT', "
                f"got {previous_event_reference!r}"
            )
            raise ValueError(msg)
    else:
        if not _is_sha256(previous_event_reference):
            msg = (
                "Non-root previous_event_reference must be lowercase 64-hex "
                f"SHA-256 digest, got {previous_event_reference!r}"
            )
            raise ValueError(msg)

    if type(event_kind) is not str or event_kind not in ALLOWED_EVENT_KINDS:
        raise ValueError(f"event_kind {event_kind!r} is not an allowed event kind")

    canonical_recorded_at_str = _canonical_recorded_at(recorded_at)

    if isinstance(producer_evidence_references, (str, bytes)) or not isinstance(
        producer_evidence_references, Sequence
    ):
        raise ValueError("producer_evidence_references must be a sequence of strings")

    for ref in producer_evidence_references:
        if not _is_sha256(ref):
            msg = (
                f"producer_evidence_references item {ref!r} is not a "
                "lowercase 64-hex SHA-256"
            )
            raise ValueError(msg)

    sorted_evidence = tuple(sorted(producer_evidence_references))

    if (
        not isinstance(payload_reference, str)
        or type(payload_reference) is not str
        or not payload_reference.strip()
    ):
        raise ValueError("payload_reference must be a non-empty string")

    if not _is_sha256(payload_hash):
        raise ValueError(
            f"payload_hash {payload_hash!r} is not a lowercase 64-hex SHA-256 digest"
        )

    event_id = f"{trial_id}:EVT-{event_index}"

    preimage = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "trial_id": trial_id,
        "event_index": event_index,
        "previous_event_reference": previous_event_reference,
        "event_kind": event_kind,
        "recorded_at": canonical_recorded_at_str,
        "producer_evidence_references": list(sorted_evidence),
        "payload_reference": payload_reference,
        "payload_hash": payload_hash,
    }
    event_hash = content_hash(preimage)

    return Stage1TrialEvent(
        schema_version=SCHEMA_VERSION,
        event_id=event_id,
        trial_id=trial_id,
        event_index=event_index,
        previous_event_reference=previous_event_reference,
        event_kind=event_kind,
        recorded_at=canonical_recorded_at_str,
        producer_evidence_references=sorted_evidence,
        payload_reference=payload_reference,
        payload_hash=payload_hash,
        event_hash=event_hash,
    )


def verify_stage1_trial_chain(
    *,
    trial_id: str,
    events: Sequence[Stage1TrialEvent],
) -> bool:
    if (
        not isinstance(trial_id, str)
        or type(trial_id) is not str
        or not trial_id.strip()
        or trial_id != trial_id.strip()
    ):
        raise ValueError("trial_id must be a non-empty string without whitespace")

    if (
        isinstance(events, (str, bytes))
        or not isinstance(events, Sequence)
        or len(events) == 0
    ):
        raise ValueError("events sequence must be a non-empty sequence")

    seen_ids: set[str] = set()
    for idx, event in enumerate(events):
        _validate_stage1_trial_event(event, expected_trial_id=trial_id)
        if event.event_index != idx:
            msg = (
                f"event at index {idx} has non-sequential "
                f"event_index {event.event_index}"
            )
            raise ValueError(msg)
        if event.event_id in seen_ids:
            raise ValueError(f"duplicate event_id {event.event_id}")
        seen_ids.add(event.event_id)

        if idx == 0:
            if event.previous_event_reference != "ROOT":
                msg = (
                    "root event must have previous_event_reference 'ROOT', "
                    f"got {event.previous_event_reference!r}"
                )
                raise ValueError(msg)
        else:
            expected_prev_hash = events[idx - 1].event_hash
            if event.previous_event_reference != expected_prev_hash:
                msg = (
                    f"event {event.event_id} has previous_event_reference "
                    f"{event.previous_event_reference!r}, "
                    f"expected {expected_prev_hash!r}"
                )
                raise ValueError(msg)

    return True


def append_stage1_trial_event(
    *,
    events: tuple[Stage1TrialEvent, ...],
    event: Stage1TrialEvent,
) -> tuple[Stage1TrialEvent, ...]:
    if type(events) is not tuple:
        raise ValueError("events must be a tuple")
    if not isinstance(event, Stage1TrialEvent):
        raise ValueError("event must be a Stage1TrialEvent")

    _validate_stage1_trial_event(event)

    if len(events) == 0:
        if event.event_index != 0 or event.previous_event_reference != "ROOT":
            msg = (
                "Initial event in stream must have event_index 0 and "
                "previous_event_reference 'ROOT'"
            )
            raise ValueError(msg)
        res = (event,)
        verify_stage1_trial_chain(trial_id=event.trial_id, events=res)
        return res

    _validate_stage1_trial_event(events[0])
    verify_stage1_trial_chain(trial_id=events[0].trial_id, events=events)

    if event.trial_id != events[0].trial_id:
        msg = (
            f"Cannot append event with trial_id {event.trial_id!r} to chain "
            f"with trial_id {events[0].trial_id!r}"
        )
        raise ValueError(msg)

    for existing_event in events:
        if existing_event.event_id == event.event_id:
            if existing_event == event:
                return events
            raise ValueError(
                f"conflicting event with existing event_id {event.event_id}"
            )

    if event.event_index != len(events):
        msg = (
            f"event_index {event.event_index} does not equal expected next "
            f"index {len(events)}"
        )
        raise ValueError(msg)
    if event.previous_event_reference != events[-1].event_hash:
        msg = (
            f"previous_event_reference {event.previous_event_reference!r} "
            f"does not match preceding event_hash {events[-1].event_hash!r}"
        )
        raise ValueError(msg)

    new_events = events + (event,)
    verify_stage1_trial_chain(trial_id=events[0].trial_id, events=new_events)
    return new_events
