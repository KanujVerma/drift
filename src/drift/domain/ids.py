from uuid import UUID, uuid7


def new_entity_id() -> UUID:
    """Create a time-ordered identifier for a domain entity."""
    return uuid7()


def new_event_id() -> UUID:
    """Create a time-ordered identifier for a ledger event."""
    return uuid7()
