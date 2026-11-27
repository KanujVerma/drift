"""Deterministic screen. A passing row is not an order.

The floor, warmup, and shortlist size are local research configuration.
They are not an approved product mandate and they do not change the
simulation risk limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

WARMUP_SESSIONS = 63
LIQUIDITY_SESSIONS = 21
SHORTLIST_LIMIT = 4
MIN_MEDIAN_DOLLAR_VOLUME = Decimal("20000000")
_REQUIRED_CLOSES = WARMUP_SESSIONS + 1
_FACT = re.compile(
    r"^(?P<concept>[A-Za-z0-9]+)\s+(?P<value>-?[0-9]+(?:\.[0-9]+)?)\s+"
    r"\S+\s+period end\s+(?P<end>\d{4}-\d{2}-\d{2})"
    r"(?:\s+period start\s+(?P<start>\d{4}-\d{2}-\d{2}))?"
)


@dataclass(frozen=True)
class ClosePoint:
    """One close used by the screen. The id is the citable evidence id."""

    symbol: str
    day: date
    close: Decimal
    volume: Decimal | None
    evidence_id: str


@dataclass(frozen=True)
class FactPoint:
    """One fundamental summary already parsed from a source row."""

    symbol: str
    day: date
    summary: str


@dataclass(frozen=True)
class ScreenRow:
    """One symbol's screen result. ``shortlisted`` does not authorize a trade."""

    symbol: str
    research_eligible: bool
    screen_pass: bool
    shortlisted: bool
    trading_authorized: bool
    inclusion: str
    sessions: int
    median_dollar_volume: str | None
    return_21: str | None
    return_63: str | None
    trend_vs_mean: str | None
    price_over_eps: str | None
    latest_close: str | None
    latest_evidence_id: str | None
    anchor_21_evidence_id: str | None
    anchor_63_evidence_id: str | None
    notes: tuple[str, ...]


def screen(
    closes: tuple[ClosePoint, ...] | list[ClosePoint],
    *,
    as_of: date,
    universe: frozenset[str],
    authorized: frozenset[str],
    holdings: frozenset[str] = frozenset(),
    suggestions: frozenset[str] = frozenset(),
    facts: tuple[FactPoint, ...] | list[FactPoint] = (),
    min_dollar_volume: Decimal = MIN_MEDIAN_DOLLAR_VOLUME,
    shortlist_limit: int = SHORTLIST_LIMIT,
) -> tuple[ScreenRow, ...]:
    """Rank liquid names and always keep holdings and suggestions.

    Research eligibility is the configured universe plus user suggestions.
    Trading authorization is a separate set. A suggestion is researched
    even when it is outside the configured universe.
    """
    grouped: dict[str, list[ClosePoint]] = {}
    for item in closes:
        if item.day <= as_of and item.close > 0:
            grouped.setdefault(item.symbol, []).append(item)
    for series_rows in grouped.values():
        series_rows.sort(key=lambda point: (point.day, point.evidence_id))
    fact_rows: dict[str, list[FactPoint]] = {}
    for fact in facts:
        if fact.day <= as_of:
            fact_rows.setdefault(fact.symbol, []).append(fact)
    symbols = set(grouped) | set(universe) | set(holdings) | set(suggestions)
    built: dict[str, tuple[ScreenRow, Decimal | None]] = {}
    for symbol in symbols:
        series = grouped.get(symbol, [])
        built[symbol] = _row(
            symbol,
            series,
            facts=fact_rows.get(symbol, []),
            universe=universe,
            authorized=authorized,
            holdings=holdings,
            suggestions=suggestions,
            floor=min_dollar_volume,
        )
    ranked = [
        symbol
        for symbol, (row, _score) in built.items()
        if row.screen_pass and row.return_63 is not None
    ]
    ranked.sort(key=lambda symbol: (-_score_of(built[symbol][1]), symbol))
    chosen = set(ranked[:shortlist_limit])
    screened: list[ScreenRow] = []
    for symbol in sorted(built):
        row, _score = built[symbol]
        inclusion = row.inclusion
        shortlisted = row.shortlisted
        notes = list(row.notes)
        if symbol in chosen:
            shortlisted = True
            inclusion = "ranked"
            notes.append(f"ranked in the top {shortlist_limit} by 63-session return")
        if symbol in holdings:
            shortlisted = True
            inclusion = "holding"
            notes.append("included because it is an existing holding")
        elif symbol in suggestions:
            shortlisted = True
            inclusion = "suggestion"
            notes.append("included because a user suggested it")
        if not shortlisted and row.research_eligible:
            notes.append("screened and not shortlisted")
        screened.append(
            ScreenRow(
                symbol=row.symbol,
                research_eligible=row.research_eligible,
                screen_pass=row.screen_pass,
                shortlisted=shortlisted,
                trading_authorized=row.trading_authorized,
                inclusion=inclusion if shortlisted else "not_shortlisted",
                sessions=row.sessions,
                median_dollar_volume=row.median_dollar_volume,
                return_21=row.return_21,
                return_63=row.return_63,
                trend_vs_mean=row.trend_vs_mean,
                price_over_eps=row.price_over_eps,
                latest_close=row.latest_close,
                latest_evidence_id=row.latest_evidence_id,
                anchor_21_evidence_id=row.anchor_21_evidence_id,
                anchor_63_evidence_id=row.anchor_63_evidence_id,
                notes=tuple(notes),
            )
        )
    return tuple(screened)


def _score_of(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("-1000000")
    return value


def _row(
    symbol: str,
    series: list[ClosePoint],
    *,
    facts: list[FactPoint],
    universe: frozenset[str],
    authorized: frozenset[str],
    holdings: frozenset[str],
    suggestions: frozenset[str],
    floor: Decimal,
) -> tuple[ScreenRow, Decimal | None]:
    eligible = symbol in universe or symbol in suggestions or symbol in holdings
    notes: list[str] = []
    if symbol not in universe and symbol in suggestions:
        notes.append("suggestion is outside the configured research universe")
    if not eligible:
        notes.append("not in the research universe")
    sessions = len(series)
    latest = series[-1] if series else None
    anchor_21 = _anchor(series, LIQUIDITY_SESSIONS)
    anchor_63 = _anchor(series, WARMUP_SESSIONS)
    change_21, score_21 = _change(series, LIQUIDITY_SESSIONS)
    change_63, score_63 = _change(series, WARMUP_SESSIONS)
    trend = _trend(series)
    dollar, dollar_text = _dollar_volume(series)
    valuation = _valuation(latest.close if latest is not None else None, facts)
    passed = True
    if not eligible:
        passed = False
    elif sessions < _REQUIRED_CLOSES:
        passed = False
        notes.append(f"fewer than {_REQUIRED_CLOSES} closes")
    elif dollar is None:
        passed = False
        notes.append("missing volume on the liquidity window")
    elif dollar < floor:
        passed = False
        notes.append("median dollar volume is below the screen floor")
    if symbol in authorized:
        notes.append("trading-authorized on this isolated book")
    else:
        notes.append("researched, not trading-authorized")
    row = ScreenRow(
        symbol=symbol,
        research_eligible=eligible,
        screen_pass=passed,
        shortlisted=False,
        trading_authorized=symbol in authorized,
        inclusion="not_shortlisted",
        sessions=sessions,
        median_dollar_volume=dollar_text,
        return_21=change_21,
        return_63=change_63,
        trend_vs_mean=trend,
        price_over_eps=valuation,
        latest_close=None if latest is None else format(latest.close, "f"),
        latest_evidence_id=None if latest is None else latest.evidence_id,
        anchor_21_evidence_id=None if anchor_21 is None else anchor_21.evidence_id,
        anchor_63_evidence_id=None if anchor_63 is None else anchor_63.evidence_id,
        notes=tuple(notes),
    )
    return row, score_63


def _anchor(series: list[ClosePoint], sessions: int) -> ClosePoint | None:
    if len(series) < sessions + 1:
        return None
    return series[-(sessions + 1)]


def _change(
    series: list[ClosePoint], sessions: int
) -> tuple[str | None, Decimal | None]:
    if len(series) < sessions + 1:
        return None, None
    start = series[-(sessions + 1)].close
    last = series[-1].close
    if start == 0:
        return "not computed", None
    points = ((last - start) / start * Decimal("100")).quantize(Decimal("0.01"))
    return f"{points} percent", points


def _trend(series: list[ClosePoint]) -> str | None:
    if len(series) < WARMUP_SESSIONS:
        return None
    window = series[-WARMUP_SESSIONS:]
    mean = sum((item.close for item in window), Decimal("0")) / Decimal(WARMUP_SESSIONS)
    if mean == 0:
        return "not computed"
    points = ((window[-1].close - mean) / mean * Decimal("100")).quantize(
        Decimal("0.01")
    )
    return f"{points} percent"


def _dollar_volume(
    series: list[ClosePoint],
) -> tuple[Decimal | None, str | None]:
    window = series[-LIQUIDITY_SESSIONS:]
    if len(window) < LIQUIDITY_SESSIONS:
        return None, None
    values: list[Decimal] = []
    for item in window:
        if item.volume is None:
            return None, None
        values.append(item.close * item.volume)
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / 2
    shown = median.quantize(Decimal("0.01"))
    return shown, format(shown, "f")


def _valuation(price: Decimal | None, facts: list[FactPoint]) -> str | None:
    if price is None:
        return None
    parsed: list[tuple[date, date, Decimal, int | None]] = []
    for item in facts:
        match = _FACT.match(item.summary)
        if match is None or "EarningsPerShare" not in match.group("concept"):
            continue
        period = date.fromisoformat(match.group("end"))
        span = _span_days(match.group("start"), period)
        parsed.append((period, item.day, Decimal(match.group("value")), span))
    if not parsed:
        return None
    latest = max((row[0], row[1]) for row in parsed)
    tied = [row for row in parsed if (row[0], row[1]) == latest]
    values = {row[2] for row in tied}
    if len(values) == 1:
        eps = next(iter(values))
    else:
        ranked: list[tuple[int, Decimal]] = []
        for row in tied:
            span = row[3]
            if span is not None:
                ranked.append((span, row[2]))
        if not ranked:
            return None
        distance = min(abs(span - 365) for span, _value in ranked)
        winners = [value for span, value in ranked if abs(span - 365) == distance]
        if len(set(winners)) != 1:
            return None
        eps = winners[0]
    if eps <= 0:
        return "not computed"
    return str((price / eps).quantize(Decimal("0.01")))


def _span_days(start: str | None, end: date) -> int | None:
    if start is None:
        return None
    try:
        return (end - date.fromisoformat(start)).days
    except ValueError:
        return None
