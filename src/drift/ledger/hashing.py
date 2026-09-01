"""Canonical hash construction for immutable audit events."""

from drift.domain.events import AuditEvent, UnsignedAuditEvent
from drift.serialization.canonical import content_hash

GENESIS_HASH = "0" * 64
"""Previous-event hash for the first event in an audit chain."""


def compute_event_hash(event: UnsignedAuditEvent) -> str:
    """Hash every unsigned audit-event field in canonical JSON form."""
    return content_hash(event.model_dump(mode="python", exclude={"event_hash"}))


def build_audit_event(unsigned_event: UnsignedAuditEvent) -> AuditEvent:
    """Attach the canonical hash to a complete unsigned event envelope."""
    return AuditEvent.model_validate(
        {
            **unsigned_event.model_dump(mode="python"),
            "event_hash": compute_event_hash(unsigned_event),
        }
    )
