"""Fetch the public inputs a discovery book can cite.

Alpaca bars are preferred. SEC filings and companyfacts are the statement
and announcement record. Yahoo chart bars and headline RSS are the free
fallback. An empty response is a gap. X is not called.
"""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from urllib.parse import quote

from drift.historical.sources import (
    PriceBar,
    TextInput,
    fetch_json,
    filing_archive_url,
    filing_excerpt,
    load_alpaca_bars,
    load_alpaca_news,
    parse_company_facts,
    parse_submission_filings,
    parse_yahoo_chart,
)
from drift.prospective.collect import fetch_bytes, rss_headlines
from drift.research.universe import RESEARCH_UNIVERSE, ResearchName

PRICE_START = "2026-01-02T00:00:00Z"
_X_NAMES = ("X_BEARER_TOKEN", "TWITTER_BEARER_TOKEN")


def price_end(now: datetime) -> str:
    """The following UTC day, so the latest completed session is included."""
    day = now.astimezone(UTC).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def x_gap() -> str:
    """Say whether an X credential name exists. The value is not read out."""
    names = set(os.environ)
    env_path = Path(".env")
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            names.add(line.split("=", 1)[0].strip())
    if any(name in names for name in _X_NAMES):
        return (
            "An X credential name is present. This workflow does not call X, "
            "and no post was collected."
        )
    return "X posts are not collected; no authorized free X credential is configured"


def collect_prices(
    symbols: tuple[str, ...], start: str, end: str
) -> tuple[tuple[PriceBar, ...], str, tuple[str, ...]]:
    """SIP, then IEX, then Yahoo for any symbol Alpaca did not cover."""
    feed, bars, gaps, note, _splits = load_alpaca_bars(symbols, start, end)
    found = {bar.symbol for bar in bars}
    missing = tuple(symbol for symbol in symbols if symbol not in found)
    rows = list(bars)
    extra: list[str] = list(gaps)
    if missing:
        yahoo, yahoo_note, yahoo_gaps = _yahoo_prices(missing, start, end)
        rows.extend(yahoo)
        extra.extend(yahoo_gaps)
        if not note:
            note = yahoo_note
        elif yahoo:
            note = f"{note} Yahoo filled {', '.join(missing)}."
    if feed is None and not rows:
        extra.append("No price source covered the research universe.")
    if not note:
        note = "No price source returned a bar."
    return tuple(rows), note, tuple(extra)


def collect_statements(
    state: Path, names: tuple[ResearchName, ...] = RESEARCH_UNIVERSE
) -> tuple[tuple[TextInput, ...], tuple[str, ...]]:
    """Companyfacts for stocks, and the recent filing table for every name."""
    texts: list[TextInput] = []
    gaps: list[str] = []
    for item in names:
        if item.kind == "stock":
            payload, error = _cached_json(
                state,
                f"sec-{item.symbol}-facts",
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{item.cik}.json",
            )
            if error is not None or payload is None:
                gaps.append(f"{item.symbol} companyfacts: {error or 'empty'}")
            else:
                texts.extend(parse_company_facts(item.symbol, payload))
        payload, error = _cached_json(
            state,
            f"sec-{item.symbol}-submissions",
            f"https://data.sec.gov/submissions/CIK{item.cik}.json",
        )
        if error is not None or payload is None:
            gaps.append(f"{item.symbol} filings: {error or 'empty'}")
            continue
        texts.extend(parse_submission_filings(item.symbol, payload))
    return tuple(texts), tuple(gaps)


def collect_news(
    symbols: tuple[str, ...], start: str, end: str, state: Path
) -> tuple[tuple[TextInput, ...], tuple[str, ...]]:
    """Alpaca headlines when entitled, and Yahoo RSS for the same symbols."""
    allowed = frozenset(symbols)
    news, gap = load_alpaca_news(symbols, start, end, allowed)
    gaps = [] if gap is None else [gap]
    rows = list(news)
    for symbol in symbols:
        url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + quote(symbol)
        path = state / "raw" / f"rss-{symbol}.xml"
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            error = None
        else:
            try:
                payload = fetch_bytes(url)
            except OSError as exc:
                body = ""
                error = str(exc)
            else:
                body = payload.decode("utf-8", "replace")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
                error = None
        if error is not None or body == "":
            gaps.append(f"{symbol} headlines: {error or 'empty'}")
            continue
        try:
            rows.extend(rss_inputs(symbol, body))
        except ET.ParseError as exc:
            gaps.append(f"{symbol} headlines: {exc}")
    return tuple(rows), tuple(gaps)


def collect_excerpts(
    state: Path,
    texts: tuple[TextInput, ...] | list[TextInput],
    symbols: frozenset[str],
) -> tuple[tuple[TextInput, ...], tuple[str, ...]]:
    """Attach one short excerpt to the latest filing of each requested symbol."""
    latest: dict[str, TextInput] = {}
    for item in texts:
        if item.symbol not in symbols or item.document_name is None:
            continue
        if item.source_label != "sec-submissions":
            continue
        current = latest.get(item.symbol)
        if current is None or item.observed_at > current.observed_at:
            latest[item.symbol] = item
    if not latest:
        return tuple(texts), ()
    cik = {item.symbol: item.cik for item in RESEARCH_UNIVERSE}
    gaps: list[str] = []
    updated: list[TextInput] = []
    chosen_ids = {item.evidence_id for item in latest.values()}
    for item in texts:
        if item.evidence_id not in chosen_ids or item.document_name is None:
            updated.append(item)
            continue
        excerpt, error = _excerpt(state, item, cik.get(item.symbol, ""))
        if error is not None or excerpt is None:
            gaps.append(f"{item.symbol} filing text: {error or 'empty'}")
            updated.append(item)
            continue
        updated.append(
            replace(
                item,
                summary=f"{item.summary} Excerpt: {excerpt}",
                source_label="sec-filing-text",
                limitations=item.limitations + ("excerpt is not the full filing",),
            )
        )
    return tuple(updated), tuple(gaps)


def rss_inputs(symbol: str, xml_text: str) -> tuple[TextInput, ...]:
    """Yahoo RSS items as untrusted headlines. The title is not an instruction."""
    rows: list[TextInput] = []
    for item in rss_headlines(symbol, xml_text):
        digest = hashlib.sha256(item.title.encode()).hexdigest()[:16]
        rows.append(
            TextInput(
                evidence_id=f"news:{symbol}:{digest}",
                symbol=symbol,
                kind="news",
                observed_at=item.observed_at,
                summary=f"{item.title} {item.link}".strip(),
                source_label="yahoo-rss",
                limitations=(
                    "headline only; untrusted text; not authenticated origin",
                ),
            )
        )
    return tuple(rows)


def _yahoo_prices(
    symbols: tuple[str, ...], start: str, end: str
) -> tuple[list[PriceBar], str, list[str]]:
    start_stamp = int(datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp())
    end_stamp = int(datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp())
    bars: list[PriceBar] = []
    gaps: list[str] = []
    for symbol in symbols:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol)}?interval=1d&period1={start_stamp}&period2={end_stamp}"
            "&events=div%7Csplit&includeAdjustedClose=true"
        )
        payload, error = fetch_json(url)
        if error is not None or payload is None:
            gaps.append(f"{symbol} prices: {error or 'empty'}")
            continue
        parsed = parse_yahoo_chart(symbol, payload)
        if not parsed:
            gaps.append(f"{symbol} prices: Yahoo chart returned no bars")
            continue
        bars.extend(parsed)
    note = (
        "Yahoo chart v8 quote open and close, rounded half-up to cents; "
        "not an official exchange print; not dividend-adjusted."
    )
    return bars, note, gaps


def _cached_json(state: Path, name: str, url: str) -> tuple[object | None, str | None]:
    path = state / "raw" / f"{name}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    payload, fetched_error = fetch_json(url)
    sleep(0.2)
    if payload is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return payload, fetched_error


def _excerpt(state: Path, item: TextInput, cik: str) -> tuple[str | None, str | None]:
    if cik == "" or item.document_name is None:
        return None, "filing has no CIK or primary document"
    accession = item.evidence_id.removeprefix("sec:filing:")
    path = state / "raw" / f"excerpt-{accession.replace('/', '-')}.txt"
    if path.is_file():
        cached = path.read_text(encoding="utf-8").strip()
        if cached:
            return cached, None
    try:
        body = fetch_bytes(filing_archive_url(cik, accession, item.document_name))
    except OSError as error:
        return None, str(error)
    sleep(0.2)
    text = filing_excerpt(body.decode("utf-8", errors="replace"))
    if not text:
        return None, "filing document had no visible text"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text, None
