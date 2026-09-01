"""Deterministic replay for verified audit ledgers."""

from drift.domain.events import AuditEvent
from drift.ledger.interface import Ledger


def replay_events(ledger: Ledger) -> tuple[AuditEvent, ...]:
    """Return the ordered immutable event history after integrity verification."""
    ledger.verify_chain()
    return ledger.events()
