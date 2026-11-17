"""Bounded lossless transport for original controlled journal envelopes.

Physical events keep the existing 1MiB cap. A larger logical record becomes
ordered chunks followed by one original commit event. Nothing is authenticated
by these hashes outside the configured, trusted local ledger boundary.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid7

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, ImmutableJSONValue, SHA256Hash
from drift.domain.events import AuditEvent
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.loop import stage1_controlled_contracts as C
from drift.serialization.canonical import canonical_json

CHUNK_PROFILE: Literal["drift-local-synthetic-g2-chunk/2"] = (
    "drift-local-synthetic-g2-chunk/2"
)
COMMIT_PROFILE: Literal["drift-local-synthetic-g2-record/2"] = (
    "drift-local-synthetic-g2-record/2"
)
CHUNK_EVENT = C.EVENT_PREFIX + "record_chunk"
CHUNK_BYTES = 262_144
MAX_LOGICAL_RECORD_BYTES = C.MAX_CONTEXT_BYTES * 2
MAX_CHUNKS = MAX_LOGICAL_RECORD_BYTES // CHUNK_BYTES
MAX_CHUNK_ENCODING = 4 * ((CHUNK_BYTES + 2) // 3)


class _BindingV2(FrozenModel):
    issuer_instance_id: UUID7
    allocation_id: UUID7
    record_id: UUID7
    record_kind: str = Field(strict=True, min_length=1, max_length=32)
    size: int = Field(strict=True, gt=C.MAX_RECORD_BYTES, le=MAX_LOGICAL_RECORD_BYTES)
    sha256: SHA256Hash
    count: int = Field(strict=True, gt=0, le=MAX_CHUNKS)

    @model_validator(mode="after")
    def require_count(self) -> Self:
        if self.count != (self.size + CHUNK_BYTES - 1) // CHUNK_BYTES:
            raise ValueError("CONTROLLED_TRANSPORT_COUNT_SIZE_MISMATCH")
        return self


class ControlledChunkV2(_BindingV2):
    profile: Literal["drift-local-synthetic-g2-chunk/2"] = CHUNK_PROFILE
    index: int = Field(strict=True, ge=0, lt=MAX_CHUNKS)
    data: str = Field(strict=True, min_length=1, max_length=MAX_CHUNK_ENCODING)


class ControlledCommitV2(_BindingV2):
    profile: Literal["drift-local-synthetic-g2-record/2"] = COMMIT_PROFILE
    parts: tuple[C.OriginalReferenceV1, ...] = Field(
        min_length=1, max_length=MAX_CHUNKS
    )

    @model_validator(mode="after")
    def require_parts(self) -> Self:
        if (
            len(self.parts) != self.count
            or len({p.event_id for p in self.parts}) != self.count
        ):
            raise ValueError("CONTROLLED_TRANSPORT_PART_INVENTORY")
        return self


def _physical_payload(value: FrozenModel) -> dict[str, ImmutableJSONValue]:
    encoded = canonical_json(value)
    if len(encoded) > C.MAX_RECORD_BYTES:
        raise ValueError("CONTROLLED_ORIGINAL_RECORD_TOO_LARGE")
    result: dict[str, ImmutableJSONValue] = json.loads(encoded)
    return result


def append_envelope(
    ledger: SQLiteLedger,
    envelope: C.ControlledEnvelopeV1,
    *,
    when: datetime,
    key: str,
) -> AuditEvent:
    """Append once; the owning writer must latch any failure as uncertain."""
    original = canonical_json(envelope)
    if len(original) > MAX_LOGICAL_RECORD_BYTES:
        raise ValueError("CONTROLLED_LOGICAL_RECORD_TOO_LARGE")
    envelope = C.ControlledEnvelopeV1.model_validate_json(original)
    event_id = uuid7()
    if len(original) <= C.MAX_RECORD_BYTES:
        return ledger.append(
            AuditEventDraft(
                event_id=event_id,
                event_type=C.EVENT_PREFIX + envelope.record.kind,
                timestamp=when,
                entity_type=C.ENTITY,
                entity_id=envelope.allocation_id,
                payload=json.loads(original),
                deduplication_key=key,
                schema_version="1",
            )
        )
    binding = _BindingV2(
        issuer_instance_id=envelope.issuer_instance_id,
        allocation_id=envelope.allocation_id,
        record_id=event_id,
        record_kind=envelope.record.kind,
        size=len(original),
        sha256=hashlib.sha256(original).hexdigest(),
        count=(len(original) + CHUNK_BYTES - 1) // CHUNK_BYTES,
    )
    common = binding.model_dump(mode="python")
    # Prepare and size-check the entire append before writing its first part.
    chunks = [
        (
            uuid7(),
            _physical_payload(
                ControlledChunkV2(
                    **common,
                    index=index,
                    data=base64.b64encode(original[start : start + CHUNK_BYTES]).decode(
                        "ascii"
                    ),
                )
            ),
        )
        for index, start in enumerate(range(0, len(original), CHUNK_BYTES))
    ]
    # Hashes have fixed width: this capacity-only template is never retained.
    _physical_payload(
        ControlledCommitV2(
            **common,
            parts=tuple(
                C.OriginalReferenceV1(event_id=ident, event_hash="0" * 64)
                for ident, _ in chunks
            ),
        )
    )
    parts: list[C.OriginalReferenceV1] = []
    # Reserve the shared logical key before any part survives. A competing
    # inline or chunked write must lose without leaving orphan chunks. Other
    # transport keys use the preallocated commit ID outside the caller namespace.
    transport_key = f"stage1:controlled:transport:{event_id}"
    for index, (ident, payload) in enumerate(chunks):
        event = ledger.append(
            AuditEventDraft(
                event_id=ident,
                event_type=CHUNK_EVENT,
                timestamp=when,
                entity_type=C.ENTITY,
                entity_id=envelope.allocation_id,
                payload=payload,
                deduplication_key=(
                    key if index == 0 else f"{transport_key}:chunk:{index}"
                ),
                schema_version="2",
            )
        )
        parts.append(
            C.OriginalReferenceV1(event_id=event.event_id, event_hash=event.event_hash)
        )
    commit = ControlledCommitV2(**common, parts=tuple(parts))
    return ledger.append(
        AuditEventDraft(
            event_id=event_id,
            event_type=C.EVENT_PREFIX + envelope.record.kind,
            timestamp=when,
            entity_type=C.ENTITY,
            entity_id=envelope.allocation_id,
            payload=_physical_payload(commit),
            deduplication_key=f"{transport_key}:commit",
            schema_version="2",
        )
    )


@dataclass(frozen=True, slots=True)
class DecodedControlledEvents:
    rows: tuple[tuple[int, AuditEvent, C.ControlledEnvelopeV1], ...]
    members: dict[UUID, tuple[UUID, ...]]


def _touches_namespace(event: AuditEvent) -> bool:
    profile = (
        event.payload.get("profile") if isinstance(event.payload, Mapping) else None
    )
    return (
        event.event_type.startswith(C.EVENT_PREFIX)
        or event.entity_type == C.ENTITY
        or (isinstance(profile, str) and profile.startswith("drift-local-synthetic-g2"))
    )


def _check_event(event: AuditEvent, binding: _BindingV2, issuer: UUID) -> None:
    if (
        event.schema_version != "2"
        or event.entity_type != C.ENTITY
        or event.entity_id != binding.allocation_id
        or binding.issuer_instance_id != issuer
    ):
        raise ValueError("CONTROLLED_TRANSPORT_SCOPE_MISMATCH")


def decode_original_events(
    events: Sequence[AuditEvent], issuer: UUID
) -> DecodedControlledEvents:
    """Inventory all allocations before filtering, including orphan tail parts."""
    rows: list[tuple[int, AuditEvent, C.ControlledEnvelopeV1]] = []
    chunks: dict[UUID, tuple[int, AuditEvent, ControlledChunkV2]] = {}
    commits: list[tuple[int, AuditEvent, ControlledCommitV2]] = []
    members: dict[UUID, tuple[UUID, ...]] = {}
    for index, event in enumerate(events):
        if not _touches_namespace(event):
            continue
        encoded = canonical_json(event.payload)
        if len(encoded) > C.MAX_RECORD_BYTES:
            raise ValueError("CONTROLLED_UNKNOWN_OR_MALFORMED_ORIGINAL_RECORD")
        try:
            if event.schema_version == "1":
                envelope = C.ControlledEnvelopeV1.model_validate_json(encoded)
                if (
                    event.entity_type != C.ENTITY
                    or event.entity_id != envelope.allocation_id
                    or event.event_type != C.EVENT_PREFIX + envelope.record.kind
                    or envelope.issuer_instance_id != issuer
                    or canonical_json(envelope) != encoded
                ):
                    raise ValueError("CONTROLLED_ENVELOPE_BODY_OR_ISSUER_MISMATCH")
                rows.append((index, event, envelope))
                members[event.event_id] = (event.event_id,)
            elif (
                isinstance(event.payload, Mapping)
                and event.payload.get("profile") == CHUNK_PROFILE
            ):
                part = ControlledChunkV2.model_validate_json(encoded)
                _check_event(event, part, issuer)
                if event.event_type != CHUNK_EVENT or canonical_json(part) != encoded:
                    raise ValueError("CONTROLLED_TRANSPORT_CHUNK_ENVELOPE")
                chunks[event.event_id] = (index, event, part)
            else:
                commit = ControlledCommitV2.model_validate_json(encoded)
                _check_event(event, commit, issuer)
                if (
                    event.event_id != commit.record_id
                    or event.event_type != C.EVENT_PREFIX + commit.record_kind
                    or canonical_json(commit) != encoded
                ):
                    raise ValueError("CONTROLLED_TRANSPORT_COMMIT_ENVELOPE")
                commits.append((index, event, commit))
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CONTROLLED_UNKNOWN_OR_MALFORMED_ORIGINAL_RECORD"
            ) from error
    consumed: set[UUID] = set()
    for position, event, commit in commits:
        previous = -1
        restored: list[bytes] = []
        common = _BindingV2.model_validate(
            commit.model_dump(include=set(_BindingV2.model_fields))
        )
        for index, ref in enumerate(commit.parts):
            found = chunks.get(ref.event_id)
            if found is None:
                raise ValueError("CONTROLLED_TRANSPORT_MISSING_CHUNK")
            sequence, source, part = found
            if (
                source.event_hash != ref.event_hash
                or source.event_id in consumed
                or not previous < sequence < position
                or source.timestamp != event.timestamp
                or part.index != index
                or _BindingV2.model_validate(
                    part.model_dump(include=set(_BindingV2.model_fields))
                )
                != common
            ):
                raise ValueError("CONTROLLED_TRANSPORT_CHUNK_BINDING_OR_ORDER")
            previous = sequence
            try:
                raw = base64.b64decode(part.data, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("CONTROLLED_TRANSPORT_CHUNK_ENCODING") from error
            expected_size = min(CHUNK_BYTES, commit.size - index * CHUNK_BYTES)
            if (
                len(raw) != expected_size
                or base64.b64encode(raw).decode("ascii") != part.data
            ):
                raise ValueError("CONTROLLED_TRANSPORT_CHUNK_SIZE_OR_ENCODING")
            restored.append(raw)
            consumed.add(source.event_id)
        # Count and each part's length were bounded before concatenation/parsing.
        original = b"".join(restored)
        if (
            len(original) != commit.size
            or hashlib.sha256(original).hexdigest() != commit.sha256
        ):
            raise ValueError("CONTROLLED_TRANSPORT_ORIGINAL_SIZE_OR_HASH")
        envelope = C.ControlledEnvelopeV1.model_validate_json(original)
        if (
            canonical_json(envelope) != original
            or envelope.issuer_instance_id != commit.issuer_instance_id
            or envelope.allocation_id != commit.allocation_id
            or envelope.record.kind != commit.record_kind
        ):
            raise ValueError("CONTROLLED_TRANSPORT_ORIGINAL_ENVELOPE")
        rows.append((position, event, envelope))
        members[event.event_id] = tuple(p.event_id for p in commit.parts) + (
            event.event_id,
        )
    if set(chunks) != consumed:
        raise ValueError("CONTROLLED_TRANSPORT_ORPHAN_OR_INCOMPLETE_CHUNKS")
    return DecodedControlledEvents(tuple(sorted(rows, key=lambda row: row[0])), members)
