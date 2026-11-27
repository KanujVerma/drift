"""Select the evidence a decision prompt needs.

The full series stays available for a later lookup. The prompt keeps
anchor closes, the current statement, a superseded predecessor when one
exists, the latest filing, and a few fresh headlines.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from drift.manager.evidence_validity import CitationRow, citation_refusal

MAX_HEADLINES = 3
MAX_FOLLOW_UPS = 3
NEWS_AGE_HOURS = 336
_LATEST = re.compile(r"Latest (\S+) is ")
_LABELED = re.compile(r"^(\S+) is (?:superseded|withdrawn),", re.MULTILINE)
_FILING = re.compile(
    r"^(?P<form>10-K/A|10-Q/A|8-K/A|10-K|10-Q|8-K) accession \S+"
    r"(?: report (?P<report>\d{4}-\d{2}-\d{2}))?"
)


def compact_evidence(
    evidence: Sequence[Mapping[str, object]],
    *,
    symbols: frozenset[str],
    deep: frozenset[str],
    as_of: datetime,
) -> list[dict[str, object]]:
    """Return the citable slice, preserving ids the full series already uses."""
    visible = [dict(item) for item in evidence if _visible(item, as_of)]
    kept: dict[str, dict[str, object]] = {}
    for symbol in sorted(symbols):
        closes = _closes(visible, symbol)
        for item in _anchors(closes):
            _keep(kept, item)
        if symbol not in deep:
            continue
        for item in visible:
            if item.get("symbol") == symbol and item.get("kind") == "suggestion":
                _keep(kept, item)
        for item in _facts(visible, symbol):
            _keep(kept, item)
        filing = _latest_filing(visible, symbol)
        if filing is not None:
            _keep(kept, filing)
        for item in _headlines(visible, symbol, as_of):
            _keep(kept, item)
        contradicted = _contradictions(visible, symbol, as_of)
        for item in contradicted:
            _keep(kept, item)
        for item in _replacements(visible, symbol, contradicted):
            _keep(kept, item)
    return [kept[key] for key in sorted(kept)]


def cited_ids_missing(
    brief: str, evidence: Sequence[Mapping[str, object]]
) -> tuple[str, ...]:
    """Ids the research block names that the compact slice dropped."""
    present = {
        item.get("evidence_id")
        for item in evidence
        if isinstance(item.get("evidence_id"), str)
    }
    named = set(_LATEST.findall(brief)) | set(_LABELED.findall(brief))
    return tuple(sorted(item for item in named if item not in present))


def follow_ups(
    evidence: Sequence[Mapping[str, object]],
    *,
    deep: frozenset[str],
    kinds: Mapping[str, str],
    as_of: datetime,
) -> tuple[str, ...]:
    """At most three missing-evidence requests. A gap does not block a hold."""
    visible = [item for item in evidence if _visible(item, as_of)]
    requests: list[str] = []
    for symbol in sorted(deep):
        if len(_closes(visible, symbol)) < 64:
            requests.append(
                f"{symbol}: fewer than 64 closes, so the 63-session change is missing"
            )
        elif kinds.get(symbol) == "stock" and not _facts(visible, symbol):
            requests.append(f"{symbol}: no financial statement was available")
        elif not _headlines(visible, symbol, as_of):
            requests.append(
                f"{symbol}: no headline inside {NEWS_AGE_HOURS} hours was available"
            )
        if len(requests) >= MAX_FOLLOW_UPS:
            break
    return tuple(requests[:MAX_FOLLOW_UPS])


def size_report(full_text: str, compact_text: str) -> dict[str, int | str]:
    """Character counts, plus a rough token estimate that is not a provider count."""
    full = len(full_text)
    compact = len(compact_text)
    return {
        "compact_characters": compact,
        "compact_estimated_tokens_div4": compact // 4,
        "full_characters": full,
        "full_estimated_tokens_div4": full // 4,
        "note": "div4 is a character estimate, not a provider token count",
        "reduction_characters": full - compact,
    }


def lookup_matches(
    evidence: Sequence[Mapping[str, object]],
    *,
    symbol: str | None = None,
    kind: str | None = None,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Newest matching cache rows. The limit keeps a follow-up small."""
    matched = [
        dict(item)
        for item in evidence
        if (symbol is None or item.get("symbol") == symbol)
        and (kind is None or item.get("kind") == kind)
    ]
    matched.sort(key=lambda item: str(item.get("observed_at")))
    if limit < 1:
        return []
    return matched[-limit:]


def lookup_evidence(
    evidence: Sequence[Mapping[str, object]], evidence_id: str
) -> dict[str, object] | None:
    """Return one cached row. Absence is None, not a guessed row."""
    for item in evidence:
        if item.get("evidence_id") == evidence_id:
            return dict(item)
    return None


def _visible(item: Mapping[str, object], as_of: datetime) -> bool:
    observed = _time(item.get("observed_at"))
    available = _time(item.get("available_at"))
    if available is None or available > as_of:
        return False
    return observed is None or observed <= as_of


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _closes(
    evidence: Sequence[Mapping[str, object]], symbol: str
) -> list[dict[str, object]]:
    rows = [
        dict(item)
        for item in evidence
        if item.get("symbol") == symbol
        and item.get("kind") == "observation"
        and item.get("price_role") == "close"
    ]
    rows.sort(
        key=lambda item: (
            str(item.get("observed_at")),
            str(item.get("evidence_id")),
        )
    )
    return rows


def _anchors(closes: list[dict[str, object]]) -> list[dict[str, object]]:
    if not closes:
        return []
    indexes = {len(closes) - 1}
    if len(closes) >= 22:
        indexes.add(len(closes) - 22)
    if len(closes) >= 64:
        indexes.add(len(closes) - 64)
    return [closes[index] for index in sorted(indexes)]


def _facts(
    evidence: Sequence[Mapping[str, object]], symbol: str
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in evidence:
        if item.get("symbol") != symbol or item.get("kind") != "fundamental":
            continue
        evidence_id = item.get("evidence_id")
        key = evidence_id if isinstance(evidence_id, str) else ""
        grouped.setdefault(_fact_group(key), []).append(dict(item))
    chosen: list[dict[str, object]] = []
    for rows in grouped.values():
        rows.sort(key=lambda item: str(item.get("observed_at")))
        chosen.append(rows[-1])
        if len(rows) > 1:
            chosen.append(rows[-2])
    return chosen


def _fact_group(evidence_id: str) -> str:
    """Group a companyfacts id without its filed date, so a restatement collides."""
    parts = evidence_id.split(":")
    if len(parts) >= 9 and parts[0] == "sec" and parts[1] == "fact":
        return ":".join((*parts[:5], parts[5], *parts[7:]))
    return evidence_id


def _latest_filing(
    evidence: Sequence[Mapping[str, object]], symbol: str
) -> dict[str, object] | None:
    rows = [
        dict(item)
        for item in evidence
        if _filing(item) and item.get("symbol") == symbol
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: str(item.get("observed_at")))
    return rows[-1]


def _headlines(
    evidence: Sequence[Mapping[str, object]], symbol: str, as_of: datetime
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evidence:
        if item.get("symbol") != symbol or item.get("kind") != "news" or _filing(item):
            continue
        available = _time(item.get("available_at"))
        observed = _time(item.get("observed_at"))
        stamp = observed if observed is not None else available
        if stamp is None or as_of - stamp > timedelta(hours=NEWS_AGE_HOURS):
            continue
        rows.append(dict(item))
    rows.sort(key=lambda item: str(item.get("observed_at")))
    return rows[-MAX_HEADLINES:]


def _filing(item: Mapping[str, object]) -> bool:
    source = item.get("source_label")
    summary = item.get("summary")
    if isinstance(source, str) and source.startswith("sec-"):
        return item.get("kind") == "news"
    return isinstance(summary, str) and summary.startswith(("10-K", "10-Q", "8-K"))


def _replacements(
    evidence: Sequence[Mapping[str, object]],
    symbol: str,
    superseded: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep the later row that makes a retained filing or fact superseded."""
    extra: list[dict[str, object]] = []
    for item in superseded:
        observed = _time(item.get("observed_at"))
        filing = _filing_identity(item)
        fact = _fact_identity(str(item.get("evidence_id")))
        if observed is None or (filing is None and fact is None):
            continue
        for other in evidence:
            if other.get("symbol") != symbol:
                continue
            if other.get("evidence_id") == item.get("evidence_id"):
                continue
            other_time = _time(other.get("observed_at"))
            if other_time is None or other_time <= observed:
                continue
            same_fact = (
                fact is not None
                and _fact_identity(str(other.get("evidence_id"))) == fact
            )
            same_filing = filing is not None and _filing_identity(other) == filing
            summary = other.get("summary")
            amended = isinstance(summary, str) and summary.startswith(
                ("10-K/A", "10-Q/A", "8-K/A")
            )
            if same_fact or (same_filing and amended):
                extra.append(dict(other))
    return extra


def _filing_identity(item: Mapping[str, object]) -> tuple[str, str, str] | None:
    summary = item.get("summary")
    symbol = item.get("symbol")
    if not isinstance(summary, str) or not isinstance(symbol, str):
        return None
    parsed = _FILING.match(summary)
    report = None if parsed is None else parsed.group("report")
    if parsed is None or report is None:
        return None
    return symbol, parsed.group("form").removesuffix("/A"), report


def _fact_identity(evidence_id: str) -> tuple[str, ...] | None:
    parts = evidence_id.split(":")
    if len(parts) < 9 or parts[0] != "sec" or parts[1] != "fact":
        return None
    return (parts[2], parts[3], parts[4], parts[5], ":".join(parts[8:]))


def _contradictions(
    evidence: Sequence[Mapping[str, object]], symbol: str, as_of: datetime
) -> list[dict[str, object]]:
    """Keep a row the citation rule marks superseded or withdrawn."""
    rows = [
        item
        for item in evidence
        if item.get("symbol") == symbol and item.get("kind") in {"fundamental", "news"}
    ]
    citations = tuple(_citation(item) for item in rows)
    usable = [item for item in citations if item is not None]
    kept: list[dict[str, object]] = []
    for item, citation in zip(rows, citations, strict=True):
        if citation is None:
            continue
        refusal = citation_refusal(
            citation,
            as_of,
            usable,
            policy="research",
            max_age_hours=NEWS_AGE_HOURS,
        )
        if refusal is not None and refusal.startswith(("superseded_", "withdrawn_")):
            kept.append(dict(item))
    return kept


def _citation(item: Mapping[str, object]) -> CitationRow | None:
    evidence_id = item.get("evidence_id")
    kind = item.get("kind")
    observed = _time(item.get("observed_at"))
    available = _time(item.get("available_at"))
    if not isinstance(evidence_id, str) or not isinstance(kind, str):
        return None
    if observed is None or available is None:
        return None
    source = item.get("source_label")
    summary = item.get("summary")
    symbol = item.get("symbol")
    raw_limits = item.get("limitations")
    limits: tuple[str, ...] = ()
    if isinstance(raw_limits, list):
        limits = tuple(limit for limit in raw_limits if isinstance(limit, str))
    return CitationRow(
        evidence_id=evidence_id,
        kind=kind,
        source_label=source if isinstance(source, str) else "",
        summary=summary if isinstance(summary, str) else evidence_id,
        limitations=limits,
        observed_at=observed,
        available_at=available,
        symbol=symbol if isinstance(symbol, str) else "",
    )


def _keep(kept: dict[str, dict[str, object]], item: Mapping[str, object]) -> None:
    evidence_id = item.get("evidence_id")
    if isinstance(evidence_id, str):
        kept[evidence_id] = dict(item)
