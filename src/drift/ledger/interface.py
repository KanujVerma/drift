"""Public append and query contracts for Drift ledgers."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    UTCDateTime,
)
from drift.domain.events import AuditEvent


class AuditEventDraft(FrozenModel):
    """An audit event request whose chain hashes are assigned by the ledger."""

    event_id: UUID7
    event_type: NonBlankStr
    timestamp: UTCDateTime
    entity_type: NonBlankStr
    entity_id: UUID7
    payload: ImmutableJSON
    deduplication_key: NonBlankStr | None = None
    schema_version: NonBlankStr


class Ledger(Protocol):
    """Storage-independent append-only audit ledger contract."""

    def append(self, draft: AuditEventDraft) -> AuditEvent:
        """Append a draft after assigning its predecessor and event hashes."""
        ...

    def get(self, event_id: UUID) -> AuditEvent | None:
        """Return one event by identifier, or ``None`` when it is absent."""
        ...

    def events(self) -> tuple[AuditEvent, ...]:
        """Return every event in ledger sequence order."""
        ...

    def events_for_entity(
        self, entity_type: str, entity_id: UUID
    ) -> tuple[AuditEvent, ...]:
        """Return one entity's events in ledger sequence order."""
        ...

    def events_after(self, cursor: UUID | datetime) -> tuple[AuditEvent, ...]:
        """Return events strictly after an event or timestamp cursor."""
        ...

    def verify_chain(self) -> None:
        """Raise when stored event or checkpoint history is inconsistent."""
        ...

    def verified_events(self) -> tuple[AuditEvent, ...]:
        """Verify and return one immutable event-history snapshot."""
        ...
