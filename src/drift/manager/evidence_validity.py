"""Citation rules for one decision.

The prospective books keep a single maximum age. The historical research
policy does not. A fill still uses that maximum age on the trade print.
This module does not choose a fill.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

_FACT_ID = re.compile(
    r"^sec:fact:(?P<symbol>[A-Z0-9]+):(?P<concept>[A-Za-z0-9]+):"
    r"(?P<end>\d{4}-\d{2}-\d{2}):(?P<start>none|\d{4}-\d{2}-\d{2}):"
    r"(?P<filed>\d{4}-\d{2}-\d{2}):(?P<form>[^:]+):(?P<unit>.+)$"
)
_FILING = re.compile(
    r"^(?P<form>10-K/A|10-Q/A|8-K/A|10-K|10-Q|8-K) accession \S+"
    r"(?: report (?P<report>\d{4}-\d{2}-\d{2}))?"
)

Policy = Literal["uniform_age", "research"]


@dataclass(frozen=True)
class CitationRow:
    """The clocks and labels a citation check needs. Text stays untrusted."""

    evidence_id: str
    kind: str
    source_label: str
    summary: str
    limitations: tuple[str, ...]
    observed_at: datetime
    available_at: datetime
    symbol: str


def citation_clock(observed: datetime, available: datetime) -> datetime:
    """Age from the earlier clock. Later availability cannot refresh it."""
    if observed <= available:
        return observed
    return available


def citation_refusal(
    row: CitationRow,
    as_of: datetime,
    rows: Sequence[CitationRow],
    *,
    policy: Policy,
    max_age_hours: int,
) -> str | None:
    """Return a rejection reason, or None when the row may be cited."""
    if _withdrawn(row):
        return f"withdrawn_evidence: {row.evidence_id} was withdrawn"
    if _durable(row) and _superseded(row, as_of, rows):
        return f"superseded_evidence: {row.evidence_id} has a later replacement"
    if policy == "research" and (_durable(row) or row.kind == "observation"):
        return None
    return _aged(row, as_of, max_age_hours)


def citation_label(
    row: CitationRow,
    as_of: datetime,
    rows: Sequence[CitationRow],
    *,
    max_age_hours: int,
) -> str:
    """Short research-policy label. It uses the same refusal as the validator."""
    refusal = citation_refusal(
        row,
        as_of,
        rows,
        policy="research",
        max_age_hours=max_age_hours,
    )
    if refusal is None and row.kind == "observation":
        age = as_of - citation_clock(row.observed_at, row.available_at)
        if age <= timedelta(hours=max_age_hours):
            return "fresh price, citable"
        return "historical price, citable"
    if refusal is None and _durable(row):
        return "citable until superseded"
    if refusal is None:
        return "time-sensitive, citable"
    if refusal.startswith("withdrawn_evidence:"):
        return "withdrawn, not citable"
    if refusal.startswith("superseded_evidence:"):
        return "superseded, not citable"
    if refusal.startswith("stale_evidence:"):
        return "stale, not citable"
    return "not citable"


def _aged(row: CitationRow, as_of: datetime, max_age_hours: int) -> str | None:
    aged = citation_clock(row.observed_at, row.available_at)
    if as_of - aged > timedelta(hours=max_age_hours):
        return f"stale_evidence: {row.evidence_id} is older than the configured age"
    return None


def _withdrawn(row: CitationRow) -> bool:
    if row.summary.casefold().startswith("withdrawn "):
        return True
    return any("withdrawn" in item.casefold() for item in row.limitations)


def _durable(row: CitationRow) -> bool:
    if row.kind == "fundamental":
        return True
    return row.kind == "news" and row.source_label.startswith("sec-")


def _superseded(row: CitationRow, as_of: datetime, rows: Sequence[CitationRow]) -> bool:
    fact = _FACT_ID.match(row.evidence_id)
    if fact is not None:
        return any(_later_fact(fact, row, other, as_of) for other in rows)
    filing = _FILING.match(row.summary)
    if filing is None:
        return False
    report = filing.group("report")
    if report is None:
        return False
    base = _base_form(filing.group("form"))
    for other in rows:
        if other.evidence_id == row.evidence_id:
            continue
        if other.available_at > as_of or other.observed_at > as_of:
            continue
        if other.observed_at <= row.observed_at:
            continue
        parsed = _FILING.match(other.summary)
        if parsed is None or parsed.group("report") != report:
            continue
        if not row.symbol or other.symbol != row.symbol:
            continue
        later_form = parsed.group("form")
        if later_form.endswith("/A") and _base_form(later_form) == base:
            return True
    return False


def _later_fact(
    fact: re.Match[str], row: CitationRow, other: CitationRow, as_of: datetime
) -> bool:
    if other.evidence_id == row.evidence_id:
        return False
    if other.available_at > as_of or other.observed_at > as_of:
        return False
    parsed = _FACT_ID.match(other.evidence_id)
    if parsed is None:
        return False
    return (
        parsed["symbol"] == fact["symbol"]
        and parsed["concept"] == fact["concept"]
        and parsed["end"] == fact["end"]
        and parsed["start"] == fact["start"]
        and parsed["unit"] == fact["unit"]
        and parsed["filed"] > fact["filed"]
    )


def _base_form(form: str) -> str:
    if form.endswith("/A"):
        return form[:-2]
    return form
