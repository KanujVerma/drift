"""Conservative identification of recorded split observations."""

from datetime import date

SPLIT_SOURCE = "alpaca-corporate-action"


def split_date(source: object, evidence_id: object, symbol: object) -> date | None:
    """Return the ex-date for a split row; refuse malformed split records."""
    if source != SPLIT_SOURCE:
        return None
    if not isinstance(evidence_id, str) or not isinstance(symbol, str):
        raise ValueError("split observation lacks identity")
    parts = evidence_id.split(":")
    if len(parts) != 4 or parts[:2] != ["alpaca", "split"] or parts[2] != symbol:
        raise ValueError("split observation identity does not match its symbol")
    try:
        return date.fromisoformat(parts[3])
    except ValueError as error:
        raise ValueError("split observation has an invalid ex-date") from error
