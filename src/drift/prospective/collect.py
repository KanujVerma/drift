"""Free public inputs for the prospective books.

SEC EDGAR filings and companyfacts are the fundamentals, filings, earnings,
and official-announcement record. Yahoo chart bars are prices and, when
present, the ^SP500TR level. Yahoo headline RSS is optional financial news.
X is not collected. Failures stay gaps. Nothing here is invented.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import sleep
from typing import Literal

from drift.domain.evaluator_portfolio import canonical_money
from drift.manager.models import (
    REQUIRED_CONTEXT_LIMITATIONS,
    REQUIRED_PACKET_LIMITATIONS,
    BenchmarkPoint,
    EvidenceItem,
    PortfolioContext,
    ResearchPacket,
    SimulationSession,
)
from drift.prospective.config import (
    UNIVERSE,
    bar_session_day,
    calendar_dates,
    instruments,
    observation_dates,
    session_close_utc,
    session_for,
    session_open_utc,
)

# EDGAR rejects agents that do not look like "Name email".
# research@example.com is a non-routable contact for that header, not a credential.
USER_AGENT = "Drift prospective study research@example.com"
SEC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"})
SIGNIFICANT_FORMS = frozenset({"8-K", "8-K/A"})
X_GAP = "X posts are not collected; no authorized X API credential is configured"
IR_GAP = (
    "company investor-relations pages are not scraped; "
    "SEC filings are the official-announcement record"
)


@dataclass(frozen=True)
class Bar:
    symbol: str
    observed_at: datetime
    open_price: str | None
    close_price: str | None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class Filing:
    symbol: str
    form: str
    accession: str
    filed: datetime


@dataclass(frozen=True)
class Fact:
    symbol: str
    concept: str
    end: str
    filed: str
    form: str
    value: str
    unit: str


@dataclass(frozen=True)
class Headline:
    symbol: str
    title: str
    observed_at: datetime
    link: str


@dataclass(frozen=True)
class UserSuggestion:
    """A supervising user's note. It is not market evidence."""

    symbol: str
    summary: str
    observed_at: datetime


@dataclass(frozen=True)
class Collection:
    collected_at: datetime
    bars: tuple[Bar, ...]
    filings: tuple[Filing, ...]
    facts: tuple[Fact, ...]
    headlines: tuple[Headline, ...]
    benchmark_level: str | None
    benchmark_kind: str
    benchmark_limitation: str
    benchmark_fetched_at: datetime
    gaps: tuple[str, ...]
    sources: tuple[str, ...]
    suggestions: tuple[UserSuggestion, ...] = ()


def load_suggestions(path: Path) -> tuple[UserSuggestion, ...]:
    """Read a JSON list of user notes. Each note carries its own time."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        message = "suggestions must be a JSON list"
        raise ValueError(message)
    rows: list[UserSuggestion] = []
    for item in payload:
        if not isinstance(item, dict):
            message = "each suggestion must be an object"
            raise ValueError(message)
        symbol = item.get("symbol")
        summary = item.get("summary")
        observed = item.get("observed_at")
        if not isinstance(symbol, str) or not isinstance(summary, str):
            message = "a suggestion needs a symbol and a summary"
            raise ValueError(message)
        if not isinstance(observed, str):
            message = "a suggestion needs observed_at"
            raise ValueError(message)
        moment = datetime.fromisoformat(observed)
        if moment.tzinfo is None:
            message = "suggestion observed_at must be timezone-aware"
            raise ValueError(message)
        rows.append(
            UserSuggestion(
                symbol=symbol,
                summary=summary,
                observed_at=moment.astimezone(UTC),
            )
        )
    return tuple(rows)


def fetch_bytes(url: str, *, timeout: float = 30) -> bytes:
    """GET one URL with the study user agent. The caller records failures."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not isinstance(body, bytes):
        message = "response body was not bytes"
        raise TypeError(message)
    return body


def cents(value: object) -> str | None:
    """Half-up cents. Unusable values become a gap, not a guessed price."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except ArithmeticError, ValueError:
        return None
    if amount <= 0:
        return None
    return format(canonical_money(amount), "f")


def yahoo_bars(symbol: str, payload: object) -> tuple[Bar, ...]:
    """Daily open and close rows from a Yahoo chart payload."""
    if not isinstance(payload, dict):
        return ()
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return ()
    result = chart.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return ()
    first = result[0]
    stamps = first.get("timestamp")
    indicators = first.get("indicators")
    if not isinstance(stamps, list) or not isinstance(indicators, dict):
        return ()
    quote = indicators.get("quote")
    if not isinstance(quote, list) or not quote or not isinstance(quote[0], dict):
        return ()
    opens = quote[0].get("open")
    closes = quote[0].get("close")
    if not isinstance(opens, list) or not isinstance(closes, list):
        return ()
    rows: list[Bar] = []
    for index, stamp in enumerate(stamps):
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            continue
        observed = datetime.fromtimestamp(int(stamp), UTC)
        open_price = cents(opens[index]) if index < len(opens) else None
        close_price = cents(closes[index]) if index < len(closes) else None
        if open_price is None and close_price is None:
            continue
        rows.append(
            Bar(
                symbol=symbol,
                observed_at=observed,
                open_price=open_price,
                close_price=close_price,
            )
        )
    return tuple(rows)


def sec_filings(symbol: str, payload: object) -> tuple[Filing, ...]:
    if not isinstance(payload, dict):
        return ()
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return ()
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        return ()
    forms = recent.get("form")
    accessions = recent.get("accessionNumber")
    filed = recent.get("acceptanceDateTime")
    if not isinstance(forms, list) or not isinstance(accessions, list):
        return ()
    if not isinstance(filed, list):
        filed = []
    rows: list[Filing] = []
    for index, form in enumerate(forms):
        if not isinstance(form, str) or form not in SEC_FORMS:
            continue
        if index >= len(accessions) or not isinstance(accessions[index], str):
            continue
        observed = _filing_time(filed[index] if index < len(filed) else None)
        if observed is None:
            continue
        rows.append(
            Filing(
                symbol=symbol,
                form=form,
                accession=accessions[index],
                filed=observed,
            )
        )
    return tuple(rows[:12])


def sec_facts(symbol: str, payload: object) -> tuple[Fact, ...]:
    """Latest revenue and diluted EPS rows. Ambiguous rows are kept and labeled."""
    if not isinstance(payload, dict):
        return ()
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return ()
    gaap = facts.get("us-gaap")
    if not isinstance(gaap, dict):
        return ()
    chosen: list[Fact] = []
    for concept in (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "EarningsPerShareDiluted",
    ):
        block = gaap.get(concept)
        if not isinstance(block, dict):
            continue
        units = block.get("units")
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            if not isinstance(unit, str) or not isinstance(rows, list):
                continue
            parsed = [row for row in rows if isinstance(row, dict)]
            parsed.sort(
                key=lambda row: str(row.get("filed", "")),
            )
            for row in parsed[-2:]:
                end = row.get("end")
                filed = row.get("filed")
                form = row.get("form")
                value = row.get("val")
                if not isinstance(end, str) or not isinstance(filed, str):
                    continue
                if not isinstance(form, str) or isinstance(value, bool):
                    continue
                if not isinstance(value, (int, float, str)):
                    continue
                chosen.append(
                    Fact(
                        symbol=symbol,
                        concept=concept,
                        end=end,
                        filed=filed,
                        form=form,
                        value=str(value),
                        unit=unit,
                    )
                )
            if chosen and chosen[-1].concept == concept:
                break
    return tuple(chosen)


def rss_headlines(
    symbol: str, xml_text: str, *, limit: int = 5
) -> tuple[Headline, ...]:
    root = ET.fromstring(xml_text)
    rows: list[Headline] = []
    for item in root.iter("item"):
        title = item.findtext("title")
        link = item.findtext("link") or ""
        published = item.findtext("pubDate")
        if not title:
            continue
        observed = _rss_time(published)
        if observed is None:
            continue
        rows.append(
            Headline(
                symbol=symbol,
                title=title.strip(),
                observed_at=observed,
                link=link,
            )
        )
        if len(rows) >= limit:
            break
    return tuple(rows)


def collect_live(now: datetime | None = None) -> Collection:
    """Fetch the current public inputs. Network errors become gaps."""
    # Stamp after the fetches when the caller does not pin a clock, so a
    # close that finishes while the download is in flight is not dropped.
    bars: list[Bar] = []
    filings: list[Filing] = []
    facts: list[Fact] = []
    headlines: list[Headline] = []
    gaps = [X_GAP, IR_GAP]
    sources: list[str] = []
    for symbol, cik, _name in UNIVERSE:
        chart_url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(symbol)}?interval=1d&range=3mo"
        )
        payload, error, fetched_at = _read_json(chart_url, now)
        if error is not None:
            gaps.append(f"{symbol} prices: {error}")
        else:
            parsed = tuple(
                Bar(
                    symbol=bar.symbol,
                    observed_at=bar.observed_at,
                    open_price=bar.open_price,
                    close_price=bar.close_price,
                    fetched_at=fetched_at,
                )
                for bar in yahoo_bars(symbol, payload)
            )
            if not parsed:
                gaps.append(f"{symbol} prices: Yahoo chart returned no bars")
            else:
                bars.extend(parsed)
                sources.append(f"yahoo-chart-v8:{symbol}")
        submissions, error, _filing_received = _read_json(
            f"https://data.sec.gov/submissions/CIK{cik}.json", now
        )
        sleep(0.2)
        if error is not None:
            gaps.append(f"{symbol} filings: {error}")
        else:
            filings.extend(sec_filings(symbol, submissions))
            sources.append(f"sec-submissions:{symbol}")
        company, error, _facts_received = _read_json(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", now
        )
        sleep(0.2)
        if error is not None:
            gaps.append(f"{symbol} companyfacts: {error}")
        else:
            found = sec_facts(symbol, company)
            if not found:
                gaps.append(f"{symbol} companyfacts: no revenue or EPS rows")
            facts.extend(found)
            sources.append(f"sec-companyfacts:{symbol}")
        rss_url = (
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s="
            f"{urllib.parse.quote(symbol)}&region=US&lang=en-US"
        )
        raw, error, _rss_received = _read_bytes(rss_url, now)
        if error is not None:
            gaps.append(f"{symbol} headlines: {error}")
        else:
            try:
                headlines.extend(rss_headlines(symbol, raw.decode("utf-8", "replace")))
                sources.append(f"yahoo-rss:{symbol}")
            except ET.ParseError as exc:
                gaps.append(f"{symbol} headlines: {exc}")
    level, kind, limitation, bench_gap, benchmark_fetched_at = _benchmark(now)
    collected_at = benchmark_fetched_at
    if bench_gap is not None:
        gaps.append(bench_gap)
    else:
        sources.append(f"benchmark:{kind}")
    return Collection(
        collected_at=collected_at,
        bars=tuple(bars),
        filings=tuple(filings),
        facts=tuple(facts),
        headlines=tuple(headlines),
        benchmark_level=level,
        benchmark_kind=kind,
        benchmark_limitation=limitation,
        benchmark_fetched_at=benchmark_fetched_at,
        gaps=tuple(gaps),
        sources=tuple(sources),
    )


def build_packet(collection: Collection, *, readiness: bool) -> ResearchPacket:
    """Opening packet. Evidence observed after the collection time is omitted."""
    when = collection.collected_at.astimezone(UTC)
    sessions: tuple[SimulationSession, ...]
    if readiness:
        sessions = (_readiness_session(when),)
    else:
        sessions = tuple(session_for(day) for day in calendar_dates())
    evidence = _evidence_items(collection, when)
    if not evidence:
        message = "collection produced no usable evidence"
        raise ValueError(message)
    notes = [
        *REQUIRED_PACKET_LIMITATIONS,
        "source gaps are recorded beside the collection and are not invented",
        "Yahoo prices are not official exchange prints",
        "filing acceptance times are source timestamps, not exchange authority",
    ]
    if readiness:
        notes.append("readiness drill; this book is not an observation session")
        settlement: tuple[date, ...] = ()
    else:
        observed = set(observation_dates())
        settlement = tuple(day for day in calendar_dates() if day not in observed)
    limitations = tuple(notes)
    benchmark = _benchmark_points(collection, sessions[0].opened_at)
    return ResearchPacket(
        instruments=instruments(),
        sessions=sessions,
        evidence=tuple(evidence),
        portfolio_context=PortfolioContext(
            as_of=sessions[0].opened_at,
            cash="10000",
            positions=(),
            limitations=REQUIRED_CONTEXT_LIMITATIONS,
        ),
        limitations=limitations,
        benchmark=benchmark,
        settlement_only_dates=settlement,
    )


def new_items(
    existing_ids: set[str], collection: Collection
) -> tuple[EvidenceItem, ...]:
    """Evidence from this collection that the book has not recorded."""
    return tuple(
        item
        for item in _evidence_items(collection, collection.collected_at.astimezone(UTC))
        if item.evidence_id not in existing_ids
    )


def _evidence_items(collection: Collection, when: datetime) -> list[EvidenceItem]:
    rows: list[EvidenceItem] = []
    price_limit = (
        "Yahoo chart v8 rounded half-up to cents; not an official exchange print; "
        f"collected {when.isoformat()}",
    )
    for bar in collection.bars:
        if bar.observed_at > when:
            continue
        day = bar_session_day(bar.observed_at)
        opened = session_open_utc(day)
        closed = session_close_utc(day)
        # A missing fetch time must not inherit the batch clock. That clock
        # can sit after the close even when this bar was read before it.
        fetched = bar.fetched_at.astimezone(UTC) if bar.fetched_at is not None else None
        if fetched is not None and fetched < opened:
            continue
        if fetched is None and when < opened:
            continue
        if bar.close_price is not None and fetched is not None and fetched >= closed:
            rows.append(
                _item(
                    evidence_id=f"yahoo:{bar.symbol}:close:{day.isoformat()}",
                    kind="observation",
                    symbol=bar.symbol,
                    observed_at=closed,
                    available_at=when,
                    summary=f"Daily close {bar.close_price} for {bar.symbol}.",
                    source_label="yahoo-chart-v8",
                    limitations=price_limit
                    + (
                        "admitted only after the session close; "
                        "the first post-close value is kept",
                    ),
                    price=bar.close_price,
                    price_role="close",
                )
            )
        if bar.open_price is not None:
            rows.append(
                _item(
                    evidence_id=f"yahoo:{bar.symbol}:open:{day.isoformat()}",
                    kind="observation",
                    symbol=bar.symbol,
                    observed_at=opened,
                    available_at=when,
                    summary=f"Daily open {bar.open_price} for {bar.symbol}.",
                    source_label="yahoo-chart-v8",
                    limitations=price_limit
                    + (
                        "open is the execution observation only when it is "
                        "after the decision",
                    ),
                    price=bar.open_price,
                    price_role="trade",
                )
            )
    for filing in collection.filings:
        if filing.filed > when:
            continue
        rows.append(
            _item(
                evidence_id=f"sec:filing:{filing.accession}",
                kind="news",
                symbol=filing.symbol,
                observed_at=filing.filed,
                available_at=when,
                summary=f"{filing.form} accession {filing.accession}.",
                source_label="sec-submissions",
                limitations=(
                    "SEC submissions row; not a full filing text; "
                    "not origin authentication",
                ),
            )
        )
    for index, fact in enumerate(collection.facts):
        filed = _fact_time(fact.filed, when)
        if filed is None:
            continue
        rows.append(
            _item(
                evidence_id=(
                    f"sec:fact:{fact.symbol}:{fact.concept}:{fact.end}:"
                    f"{fact.filed}:{index}"
                ),
                kind="fundamental",
                symbol=fact.symbol,
                observed_at=filed,
                available_at=when,
                summary=(
                    f"{fact.concept} {fact.value} {fact.unit} "
                    f"period end {fact.end} form {fact.form}."
                ),
                source_label="sec-companyfacts",
                limitations=(
                    "SEC companyfacts value; the row may not say which period "
                    "it is; not origin authentication",
                ),
            )
        )
    for headline in collection.headlines:
        if headline.observed_at > when:
            continue
        digest = hashlib.sha256(headline.title.encode()).hexdigest()[:16]
        rows.append(
            _item(
                evidence_id=f"news:{headline.symbol}:{digest}",
                kind="news",
                symbol=headline.symbol,
                observed_at=headline.observed_at,
                available_at=when,
                summary=f"{headline.title} {headline.link}".strip(),
                source_label="yahoo-rss",
                limitations=(
                    "headline only; untrusted text; not authenticated origin",
                ),
            )
        )
    seen_suggestions: set[str] = set()
    for suggestion in collection.suggestions:
        if suggestion.observed_at > when:
            continue
        observed = suggestion.observed_at.astimezone(UTC)
        digest = hashlib.sha256(suggestion.summary.encode()).hexdigest()[:16]
        evidence_id = f"suggestion:{suggestion.symbol}:{observed.isoformat()}:{digest}"
        if evidence_id in seen_suggestions:
            continue
        seen_suggestions.add(evidence_id)
        rows.append(
            _item(
                evidence_id=evidence_id,
                kind="suggestion",
                symbol=suggestion.symbol,
                observed_at=observed,
                available_at=when,
                summary=suggestion.summary,
                source_label="user-suggestion",
                limitations=(
                    "user suggestion; not market evidence; "
                    "cannot by itself support a trade",
                ),
            )
        )
    return rows


def _item(
    *,
    evidence_id: str,
    kind: str,
    symbol: str,
    observed_at: datetime,
    available_at: datetime,
    summary: str,
    source_label: str,
    limitations: tuple[str, ...],
    price: str | None = None,
    price_role: str | None = None,
) -> EvidenceItem:
    return EvidenceItem.model_validate(
        {
            "evidence_id": evidence_id,
            "kind": kind,
            "symbol": symbol,
            "observed_at": observed_at,
            "available_at": available_at,
            "limitations": limitations,
            "summary": summary,
            "source_label": source_label,
            "price": price,
            "price_role": price_role,
        }
    )


def benchmark_point(collection: Collection) -> BenchmarkPoint | None:
    """A later benchmark level at the real fetch time."""
    if collection.benchmark_level is None:
        return None
    kind = _benchmark_kind(collection.benchmark_kind)
    return BenchmarkPoint(
        available_at=collection.benchmark_fetched_at.astimezone(UTC),
        level=collection.benchmark_level,
        limitations=(collection.benchmark_limitation,),
        series_kind=kind,
    )


def _benchmark_kind(
    kind: str,
) -> Literal["sp500_total_return", "price_only_substitute"]:
    if kind == "sp500_total_return":
        return "sp500_total_return"
    if kind == "price_only_substitute":
        return "price_only_substitute"
    message = f"unknown benchmark kind {kind}"
    raise ValueError(message)


def _readiness_session(when: datetime) -> SimulationSession:
    """A drill window that contains ``when`` and is not an observation session."""
    day = when.astimezone(UTC).date()
    opened = when.astimezone(UTC) - timedelta(minutes=5)
    if opened.date() != day:
        opened = datetime.combine(day, time(0, 0), tzinfo=UTC)
    closed = datetime.combine(day, time(23, 59), tzinfo=UTC)
    if closed <= when:
        message = "readiness time is outside the UTC drill window"
        raise ValueError(message)
    return SimulationSession(local_date=day, opened_at=opened, closed_at=closed)


def _benchmark_points(
    collection: Collection, opened_at: datetime
) -> tuple[BenchmarkPoint, ...]:
    if collection.benchmark_level is None:
        return ()
    kind = _benchmark_kind(collection.benchmark_kind)
    del opened_at
    fetched = collection.benchmark_fetched_at.astimezone(UTC)
    limitation = f"{collection.benchmark_limitation}; fetched {fetched.isoformat()}"
    return (
        BenchmarkPoint(
            available_at=fetched,
            level=collection.benchmark_level,
            limitations=(limitation,),
            series_kind=kind,
        ),
    )


def _fact_time(filed: str, when: datetime) -> datetime | None:
    """Companyfacts dates are dates. Use 21:00 UTC, never after collection."""
    try:
        if "T" in filed:
            parsed = datetime.fromisoformat(filed.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            parsed = parsed.astimezone(UTC)
        else:
            parsed = datetime.combine(
                date.fromisoformat(filed), time(21, 0), tzinfo=UTC
            )
    except ValueError:
        return None
    if parsed <= when:
        return parsed
    if parsed.date() > when.date():
        return None
    return when


def _benchmark(
    pinned: datetime | None,
) -> tuple[str | None, str, str, str | None, datetime]:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        "%5ESP500TR?interval=1d&range=1mo"
    )
    payload, error, received = _read_json(url, pinned)
    if error is None:
        bars = yahoo_bars("SP500TR", payload)
        usable = [bar for bar in bars if _close_is_final(bar, received)]
        if usable:
            level = usable[-1].close_price
            assert level is not None
            return (
                level,
                "sp500_total_return",
                (
                    "Yahoo chart ^SP500TR daily close rounded half-up to cents; "
                    f"collected {received.isoformat()}; not an official S&P calculation"
                ),
                None,
                received,
            )
    spy, spy_error, received = _read_json(
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=5d",
        pinned,
    )
    if spy_error is None:
        bars = yahoo_bars("SPY", spy)
        usable = [bar for bar in bars if _close_is_final(bar, received)]
        if usable:
            level = usable[-1].close_price
            assert level is not None
            return (
                level,
                "price_only_substitute",
                (
                    "SPY price close, not S&P 500 total return; "
                    f"collected {received.isoformat()}"
                ),
                "^SP500TR was unavailable; benchmark is a SPY price substitute",
                received,
            )
    detail = error or spy_error or "no benchmark bar"
    return (
        None,
        "price_only_substitute",
        "no benchmark level",
        f"benchmark: {detail}",
        received,
    )


def _close_is_final(bar: Bar, when: datetime) -> bool:
    if bar.close_price is None:
        return False
    day = bar_session_day(bar.observed_at)
    return when >= session_close_utc(day)


def _read_json(
    url: str, pinned: datetime | None = None
) -> tuple[object, str | None, datetime]:
    raw, error, received = _read_bytes(url, pinned)
    if error is not None:
        return None, error, received
    try:
        return json.loads(raw), None, received
    except json.JSONDecodeError as exc:
        return None, str(exc), received


def _read_bytes(
    url: str, pinned: datetime | None = None
) -> tuple[bytes, str | None, datetime]:
    """Return the body and the clock when the bytes arrived, before parsing."""
    try:
        body = fetch_bytes(url)
        error = None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        body = b""
        error = str(exc)
    if pinned is not None:
        received = pinned.astimezone(UTC)
    else:
        received = datetime.now(UTC)
    return body, error, received


def _filing_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _rss_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except TypeError, ValueError, IndexError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)
