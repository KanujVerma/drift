"""Immutable audit event envelopes for the Drift research ledger."""

from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)


class UnsignedAuditEvent(FrozenModel):
    """A complete audit event before its content hash is attached."""

    event_id: UUID7
    event_type: NonBlankStr
    timestamp: UTCDateTime
    entity_type: NonBlankStr
    entity_id: UUID7
    payload: ImmutableJSON
    previous_event_hash: SHA256Hash
    deduplication_key: NonBlankStr | None = None
    schema_version: NonBlankStr


class AuditEvent(UnsignedAuditEvent):
    """A complete, hash-signed audit event."""

    event_hash: SHA256Hash
