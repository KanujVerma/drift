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

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PERIOD_START = re.compile(r"period start (\d{4}-\d{2}-\d{2})")
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
    fact = _parse_fact(row)
    if fact is not None:
        return any(_later_fact(fact, row, other, as_of) for other in rows)
    return _amended_filing(row, as_of, rows)


def _amended_filing(
    row: CitationRow, as_of: datetime, rows: Sequence[CitationRow]
) -> bool:
    """A later amendment replaces the one earlier filing it can be tied to."""
    identity = _filing_identity(row)
    if identity is None:
        return False
    for other in rows:
        if not _later_amendment(other, identity, row, as_of):
            continue
        targets = [
            candidate
            for candidate in rows
            if candidate.evidence_id != other.evidence_id
            and _filing_identity(candidate) == identity
            and candidate.observed_at < other.observed_at
            and candidate.observed_at <= as_of
            and candidate.available_at <= as_of
        ]
        if len(targets) == 1 and targets[0].evidence_id == row.evidence_id:
            return True
    return False


def _later_amendment(
    other: CitationRow,
    identity: tuple[str, str, str],
    row: CitationRow,
    as_of: datetime,
) -> bool:
    parsed = _FILING.match(other.summary)
    if parsed is None or not parsed.group("form").endswith("/A"):
        return False
    if _filing_identity(other) != identity:
        return False
    if other.evidence_id == row.evidence_id or other.observed_at <= row.observed_at:
        return False
    return other.observed_at <= as_of and other.available_at <= as_of


def _filing_identity(row: CitationRow) -> tuple[str, str, str] | None:
    parsed = _FILING.match(row.summary)
    report = None if parsed is None else parsed.group("report")
    if parsed is None or report is None or not row.symbol:
        return None
    return row.symbol, _base_form(parsed.group("form")), report


def _later_fact(
    fact: dict[str, str], row: CitationRow, other: CitationRow, as_of: datetime
) -> bool:
    if other.evidence_id == row.evidence_id:
        return False
    if other.available_at > as_of or other.observed_at > as_of:
        return False
    parsed = _parse_fact(other)
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


def _parse_fact(row: CitationRow) -> dict[str, str] | None:
    """Read the current fact id and the older id that omitted period start."""
    if not row.evidence_id.startswith("sec:fact:"):
        return None
    parts = row.evidence_id.split(":")
    if len(parts) < 8 or not _DATE.fullmatch(parts[4]):
        return None
    symbol, concept, end = parts[2], parts[3], parts[4]
    if (
        len(parts) >= 9
        and (parts[5] == "none" or _DATE.fullmatch(parts[5]))
        and _DATE.fullmatch(parts[6])
    ):
        start, filed, unit = parts[5], parts[6], ":".join(parts[8:])
    elif _DATE.fullmatch(parts[5]):
        start, filed, unit = "none", parts[5], ":".join(parts[7:])
    else:
        return None
    if start == "none":
        found = _PERIOD_START.search(row.summary)
        if found is not None:
            start = found.group(1)
    return {
        "symbol": symbol,
        "concept": concept,
        "end": end,
        "start": start,
        "filed": filed,
        "unit": unit,
    }


def _base_form(form: str) -> str:
    if form.endswith("/A"):
        return form[:-2]
    return form
