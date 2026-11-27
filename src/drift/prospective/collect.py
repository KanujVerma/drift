"""Free public inputs for the prospective books.

SEC EDGAR filings and companyfacts are the fundamentals, filings, earnings,
and official-announcement record. Alpaca supplies raw price bars. Yahoo
supplies the optional ^SP500TR level and headline RSS.
X is not collected. Failures stay gaps. Nothing here is invented.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import sleep
from typing import Literal

from drift.domain.evaluator_portfolio import canonical_money, decimal_context
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
    NY,
    bar_session_day,
    calendar_dates,
    is_session_day,
    observation_dates,
    pilot_instruments,
    session_close_utc,
    session_for,
    session_open_utc,
)
from drift.prospective.window import active_window
from drift.research.universe import RESEARCH_UNIVERSE

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
    source_label: str = "yahoo-chart-v8"
    volume: str | None = None
    covered_until: datetime | None = None


@dataclass(frozen=True)
class Trade:
    symbol: str
    observed_at: datetime
    received_at: datetime
    price: str
    source_label: str
    source_id: str
    update: str | None = None


@dataclass(frozen=True)
class TradeInvalidation:
    symbol: str
    trade_id: str
    received_at: datetime
    status: str


@dataclass(frozen=True)
class Filing:
    symbol: str
    form: str
    accession: str
    filed: datetime
    document_name: str | None = None
    report_date: str | None = None
    excerpt: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class Fact:
    symbol: str
    concept: str
    end: str
    filed: str
    form: str
    value: str
    unit: str
    start: str | None = None
    accession: str | None = None


@dataclass(frozen=True)
class Headline:
    symbol: str
    title: str
    observed_at: datetime
    link: str


@dataclass(frozen=True)
class SplitObservation:
    symbol: str
    ex_date: date
    source_id: str
    kind: str
    received_at: datetime


@dataclass(frozen=True)
class UserSuggestion:
    """A supervising user's note. It is not market evidence."""

    symbol: str
    summary: str
    observed_at: datetime
    received_at: datetime | None = None


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
    splits: tuple[SplitObservation, ...] = ()
    corporate_actions_complete: bool = True
    corporate_actions_received_at: datetime | None = None
    trades: tuple[Trade, ...] = ()
    trade_invalidations: tuple[TradeInvalidation, ...] = ()
    dispute_facts: tuple[Fact, ...] = ()


def load_suggestions(path: Path) -> tuple[UserSuggestion, ...]:
    """Read a JSON list of user notes. Each note carries its own time."""
    body = path.read_text(encoding="utf-8")
    received_at = datetime.now(UTC)
    payload = json.loads(body)
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
                received_at=received_at,
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


@decimal_context()
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
    documents = recent.get("primaryDocument")
    reports = recent.get("reportDate")
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
                document_name=(
                    documents[index]
                    if isinstance(documents, list)
                    and index < len(documents)
                    and isinstance(documents[index], str)
                    else None
                ),
                report_date=(
                    reports[index]
                    if isinstance(reports, list)
                    and index < len(reports)
                    and isinstance(reports[index], str)
                    and reports[index]
                    else None
                ),
            )
        )
    return tuple(rows[:12])


def sec_facts(symbol: str, payload: object, *, full: bool = False) -> tuple[Fact, ...]:
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
            candidates: list[Fact] = []
            for row in parsed:
                end = row.get("end")
                filed = row.get("filed")
                form = row.get("form")
                value = row.get("val")
                start = row.get("start")
                accession = row.get("accn")
                if not isinstance(end, str) or not isinstance(filed, str):
                    continue
                if not isinstance(form, str) or isinstance(value, bool):
                    continue
                if not isinstance(value, (int, float, str)):
                    continue
                candidates.append(
                    Fact(
                        symbol=symbol,
                        concept=concept,
                        end=end,
                        filed=filed,
                        form=form,
                        value=str(value),
                        unit=unit,
                        start=start if isinstance(start, str) else None,
                        accession=accession
                        if isinstance(accession, str) and accession
                        else None,
                    )
                )
            # Keep complete latest period groups so duplicates cannot crowd a
            # conflicting value out of the screen before it is checked.
            keys = list(dict.fromkeys((f.end, f.start, f.filed) for f in candidates))
            latest = set(keys[-2:])
            chosen.extend(
                dict.fromkeys(
                    f for f in candidates if full or (f.end, f.start, f.filed) in latest
                )
            )
            if candidates and not full:
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


def collect_trades(
    feed: Literal["sip", "iex"],
    requests: tuple[tuple[str, datetime], ...],
    end: datetime,
    *,
    excluded: frozenset[str] = frozenset(),
    invalidations: list[TradeInvalidation] | None = None,
) -> tuple[tuple[Trade, ...], tuple[str, ...]]:
    """Search regular sessions in order and retain distinct eligible prints."""
    found: dict[str, Trade] = {}
    gaps: list[str] = []
    for symbol, boundary in sorted(requests):
        boundary_day = boundary.astimezone(NY).date()
        extra = (boundary_day,) if is_session_day(boundary_day) else ()
        for day in sorted(set(calendar_dates()) | set(extra)):
            opened, closed = session_open_utc(day), session_close_utc(day)
            if closed <= boundary or opened > end:
                continue
            start = max(boundary, opened - timedelta(microseconds=1))
            rows, errors = _collect_trade_window(
                feed,
                ((symbol, start),),
                min(end, closed),
                excluded=excluded | frozenset(found),
                invalidations=invalidations,
            )
            if rows:
                found.update({row.source_id: row for row in rows})
                break
            if any("no eligible" not in error for error in errors):
                gaps.extend(errors)
                break
        else:
            gaps.append(f"{symbol} trades: no eligible post-decision print")
    return tuple(found.values()), tuple(gaps)


def _collect_trade_window(
    feed: Literal["sip", "iex"],
    requests: tuple[tuple[str, datetime], ...],
    end: datetime,
    *,
    excluded: frozenset[str],
    invalidations: list[TradeInvalidation] | None,
) -> tuple[tuple[Trade, ...], tuple[str, ...]]:
    """Read actual trades after each sealed boundary; never infer a print from a bar."""
    from drift.historical.sources import _alpaca_json_timed
    from drift.prospective.trade_identity import canonical_trade_id, normalize_trade_id

    excluded_keys = {normalize_trade_id(item) for item in excluded}

    found: dict[str, Trade] = {}
    gaps: list[str] = []
    for symbol, boundary in sorted(set(requests)):
        if boundary >= end:
            continue
        token: str | None = None
        seen: set[str] = set()
        previous: datetime | None = None
        for _ in range(5):
            query = {
                "symbols": symbol,
                "feed": feed,
                "sort": "asc",
                "limit": "1000",
                "start": boundary.astimezone(UTC).isoformat(),
                "end": end.astimezone(UTC).isoformat(),
            }
            if token is not None:
                query["page_token"] = token
            payload, status, received = _alpaca_json_timed("/v2/stocks/trades", query)
            if status != 200 or not isinstance(payload, dict) or received is None:
                gaps.append(f"{symbol} trades: HTTP {status} or missing receipt")
                break
            groups = payload.get("trades")
            next_token = payload.get("next_page_token")
            if (
                not isinstance(groups, dict)
                or "next_page_token" not in payload
                or any(key != symbol for key in groups)
                or not isinstance(groups.get(symbol, []), list)
                or (
                    next_token is not None
                    and (not isinstance(next_token, str) or not next_token)
                )
                or (isinstance(next_token, str) and next_token in seen)
            ):
                gaps.append(f"{symbol} trades: malformed page or pagination")
                break
            candidates: list[Trade] = []
            invalidated: set[str] = set()
            page_invalidations: list[TradeInvalidation] = []
            malformed = False
            for row in groups.get(symbol, []):
                if not isinstance(row, dict) or not isinstance(row.get("t"), str):
                    malformed = True
                    break
                try:
                    observed = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
                    price = Decimal(str(row.get("p")))
                except ValueError, ArithmeticError:
                    malformed = True
                    break
                size, identifier, conditions = row.get("s"), row.get("i"), row.get("c")
                exchange = row.get("x")
                update = row.get("u")
                if "u" in row and update not in ("canceled", "incorrect", "corrected"):
                    malformed = True
                    break
                if (
                    observed.tzinfo is None
                    or observed > end
                    or observed > received
                    or (previous is not None and observed < previous)
                    or not price.is_finite()
                    or price <= 0
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size <= 0
                    or not isinstance(identifier, int)
                    or isinstance(identifier, bool)
                    or not isinstance(exchange, str)
                    or not exchange
                    or not exchange.isalnum()
                    or not isinstance(conditions, list)
                    or any(not isinstance(c, str) for c in conditions)
                ):
                    malformed = True
                    break
                previous = observed
                # Conservative eligibility: only ordinary regular-way prints.
                trade_day = observed.astimezone(NY).date()
                regular_session = is_session_day(trade_day) and session_open_utc(
                    trade_day
                ) <= observed <= session_close_utc(trade_day)
                try:
                    source_id = canonical_trade_id(
                        feed, symbol, row["t"], exchange, identifier
                    )
                except ValueError:
                    malformed = True
                    break
                if update in ("canceled", "incorrect"):
                    invalidated.add(source_id)
                    page_invalidations.append(
                        TradeInvalidation(symbol, source_id, received, update)
                    )
                    continue
                if (
                    observed > boundary
                    and conditions in ([], ["@"])
                    and regular_session
                    and source_id not in excluded_keys
                ):
                    rounded = cents(str(price))
                    if rounded is None:
                        malformed = True
                        break
                    candidates.append(
                        Trade(
                            symbol,
                            observed.astimezone(UTC),
                            received.astimezone(UTC),
                            rounded,
                            f"alpaca-trades-v2-{feed}",
                            source_id,
                            update,
                        )
                    )
            if malformed:
                gaps.append(f"{symbol} trades: malformed or unordered print")
                break
            if invalidations is not None:
                invalidations.extend(page_invalidations)
            candidate = next(
                (row for row in candidates if row.source_id not in invalidated), None
            )
            if candidate is not None:
                found[candidate.source_id] = candidate
                break
            if not next_token:
                gaps.append(f"{symbol} trades: no eligible post-decision print")
                break
            seen.add(next_token)
            token = next_token
        else:
            gaps.append(f"{symbol} trades: pagination limit reached")
    return tuple(found.values()), tuple(gaps)


def collect_live(
    now: datetime | None = None,
    *,
    preferred_feed: Literal["sip", "iex"] | None = None,
    trade_requests: tuple[tuple[str, datetime], ...] = (),
    benchmark_after: datetime | None = None,
    excluded_trades: frozenset[str] = frozenset(),
) -> Collection:
    """Fetch the current public inputs. Network errors become gaps."""
    from drift.historical.sources import (
        TimedPriceBar,
        _pilot_corporate_actions,
        filing_archive_url,
        filing_excerpt,
        load_alpaca_bars,
    )

    # Stamp after the fetches when the caller does not pin a clock, so a
    # close that finishes while the download is in flight is not dropped.
    bars: list[Bar] = []
    filings: list[Filing] = []
    facts: list[Fact] = []
    dispute_facts: list[Fact] = []
    headlines: list[Headline] = []
    gaps = [X_GAP, IR_GAP]
    sources: list[str] = []
    split_rows: dict[tuple[str, date], SplitObservation] = {}
    request_at = datetime.now(UTC) if now is None else now.astimezone(UTC)
    symbols = tuple(item.symbol for item in RESEARCH_UNIVERSE)
    start = (request_at - timedelta(days=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = request_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    coverage_receipts: list[datetime] = []
    feed, downloaded, price_gaps, _note, splits = load_alpaca_bars(
        symbols,
        start,
        end,
        preferred_feed=preferred_feed,
        check_adjustments=False,
        capture_receipt=True,
        corporate_action_receipts=coverage_receipts,
    )
    gaps.extend(price_gaps)
    coverage_valid = bool(coverage_receipts)
    if splits:
        gaps.append("Alpaca reports splits in the requested window; prices are raw")
    if feed is not None:
        sources.append(f"alpaca-bars-v2-{feed}-raw")
    trades: tuple[Trade, ...] = ()
    invalidations: list[TradeInvalidation] = []
    if feed in ("sip", "iex") and (trade_requests or benchmark_after is not None):
        selected_feed: Literal["sip", "iex"] = "sip" if feed == "sip" else "iex"
        trades, trade_gaps = collect_trades(
            selected_feed,
            trade_requests,
            request_at,
            excluded=excluded_trades,
            invalidations=invalidations,
        )
        gaps.extend(trade_gaps)
        if benchmark_after is not None:
            baseline, baseline_gaps = collect_trades(
                selected_feed,
                (("SPY", benchmark_after),),
                request_at,
                invalidations=invalidations,
            )
            gaps.extend(baseline_gaps)
            trades += tuple(
                replace(item, source_id=f"alpaca:benchmark:{item.source_id}")
                for item in baseline
            )
        if trades or invalidations:
            sources.append(f"alpaca-trades-v2-{feed}")
            coverage_receipts = []
            new_splits, _, action_gap, details = _pilot_corporate_actions(
                symbols, start, end, receipts=coverage_receipts
            )
            splits |= new_splits
            if action_gap is not None:
                gaps.append(action_gap)
                coverage_receipts.clear()
            coverage_valid = (
                coverage_valid and bool(coverage_receipts) and action_gap is None
            )
            for action in details:
                key = (action.symbol, action.ex_date)
                split_rows[key] = SplitObservation(
                    action.symbol,
                    action.ex_date,
                    action.source_id,
                    action.kind,
                    action.received_at,
                )
    calendar_skips: dict[tuple[str, int], list[date]] = {}
    for bar in downloaded:
        if not isinstance(bar, TimedPriceBar) or bar.received_at is None:
            gaps.append(f"{bar.symbol} prices: response receipt time unavailable")
            continue
        for split in bar.splits:
            row = SplitObservation(
                split.symbol,
                split.ex_date,
                split.source_id,
                split.kind,
                split.received_at,
            )
            key = (row.symbol, row.ex_date)
            if key in split_rows and (
                split_rows[key].source_id != row.source_id
                or split_rows[key].kind != row.kind
            ):
                gaps.append(
                    f"conflicting corporate action records for {row.symbol} "
                    f"{row.ex_date}"
                )
            elif key not in split_rows:
                split_rows[key] = row
        if active_window() is not None and not is_session_day(bar.day):
            calendar_skips.setdefault((bar.symbol, bar.day.year), []).append(bar.day)
            continue
        bars.append(
            Bar(
                symbol=bar.symbol,
                observed_at=session_open_utc(bar.day),
                open_price=bar.open_price,
                close_price=bar.close_price,
                fetched_at=bar.received_at,
                source_label=bar.source_label,
                volume=bar.volume,
                covered_until=datetime.fromisoformat(end.replace("Z", "+00:00")),
            )
        )
    for (symbol, year), days in sorted(calendar_skips.items()):
        gaps.append(
            f"{symbol} prices: {len(days)} dates in {year} were not verified "
            f"as NYSE sessions ({min(days)} through {max(days)})"
        )
    if splits - {row.ex_date for row in split_rows.values()}:
        gaps.append("corporate action split attribution is incomplete")
    for item in RESEARCH_UNIVERSE:
        symbol, cik = item.symbol, item.cik
        submissions, error, _filing_received = _read_json(
            f"https://data.sec.gov/submissions/CIK{cik}.json", now
        )
        sleep(0.2)
        if error is not None:
            gaps.append(f"{symbol} filings: {error}")
        else:
            found = list(sec_filings(symbol, submissions))
            if found and found[0].document_name:
                filing = found[0]
                document = filing.document_name
                assert document is not None
                url = filing_archive_url(cik, filing.accession, document)
                body, excerpt_error, received = _read_bytes(url, now)
                if excerpt_error is None:
                    excerpt = filing_excerpt(body.decode("utf-8", errors="replace"))
                    if excerpt:
                        found[0] = replace(filing, excerpt=excerpt, fetched_at=received)
                    else:
                        gaps.append(f"{symbol} filing text: empty")
                else:
                    gaps.append(f"{symbol} filing text: {excerpt_error}")
                sleep(0.2)
            filings.extend(found)
            sources.append(f"sec-submissions:{symbol}")
        company, error, _facts_received = _read_json(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", now
        )
        sleep(0.2)
        if error is not None:
            gaps.append(f"{symbol} companyfacts: {error}")
        else:
            found_facts = sec_facts(symbol, company)
            if not found_facts:
                gaps.append(f"{symbol} companyfacts: no revenue or EPS rows")
            facts.extend(found_facts)
            dispute_facts.extend(sec_facts(symbol, company, full=True))
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
    for identity in _conflicting_fact_ids(facts):
        gaps.append(f"companyfacts conflicting rows omitted: {identity}")
    level, kind, limitation, bench_gap, benchmark_fetched_at = _benchmark(now)
    collected_at = benchmark_fetched_at
    if bench_gap is not None:
        gaps.append(bench_gap)
    else:
        sources.append(f"benchmark:{kind}")
    coverage_complete = (
        feed is not None
        and coverage_valid
        and not any("corporate action" in gap.lower() for gap in gaps)
    )
    return Collection(
        collected_at=collected_at,
        bars=tuple(bars),
        filings=tuple(filings),
        facts=tuple(facts),
        dispute_facts=tuple(dispute_facts),
        headlines=tuple(headlines),
        benchmark_level=level,
        benchmark_kind=kind,
        benchmark_limitation=limitation,
        benchmark_fetched_at=benchmark_fetched_at,
        gaps=tuple(gaps),
        sources=tuple(sources),
        splits=tuple(split_rows.values()),
        corporate_actions_complete=coverage_complete,
        corporate_actions_received_at=min(coverage_receipts)
        if coverage_complete
        else None,
        trades=trades,
        trade_invalidations=tuple(invalidations),
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
    from drift.manager.models import CENT_BASIS_ALLOCATION

    notes = [
        *REQUIRED_PACKET_LIMITATIONS,
        CENT_BASIS_ALLOCATION,
        "source gaps are recorded beside the collection and are not invented",
        "raw market bars are not dividend-adjusted",
        "filing acceptance times are source timestamps, not exchange authority",
    ]
    if readiness:
        notes.append("readiness drill; this book is not an observation session")
        settlement: tuple[date, ...] = ()
    else:
        configured = active_window()
        if configured is not None:
            notes.append(f"prospective-window-sha256:{configured.binding}")
        observed = set(observation_dates())
        settlement = tuple(day for day in calendar_dates() if day not in observed)
    limitations = tuple(notes)
    benchmark = _benchmark_points(collection, sessions[0].opened_at)
    return ResearchPacket(
        instruments=pilot_instruments(),
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
    for split in collection.splits:
        if split.received_at > when:
            continue
        rows.append(
            _item(
                evidence_id=f"alpaca:split:{split.symbol}:{split.ex_date.isoformat()}",
                kind="news",
                symbol=split.symbol,
                observed_at=split.received_at,
                available_at=split.received_at,
                summary=(
                    f"{split.kind} {split.symbol} ex_date {split.ex_date.isoformat()} "
                    f"source_id {split.source_id}"
                ),
                source_label="alpaca-corporate-action",
                limitations=("Alpaca corporate action; not origin authentication",),
            )
        )
    for bar in collection.bars:
        if bar.observed_at > when:
            continue
        day = bar_session_day(bar.observed_at)
        if active_window() is not None and not is_session_day(day):
            continue
        opened = session_open_utc(day)
        closed = session_close_utc(day)
        # A missing fetch time must not inherit the batch clock. That clock
        # can sit after the close even when this bar was read before it.
        fetched = bar.fetched_at.astimezone(UTC) if bar.fetched_at is not None else None
        if fetched is not None and fetched > when:
            continue
        price_limit = (
            f"{bar.source_label} rounded half-up to cents; raw prices; "
            f"collected {(fetched or when).isoformat()}",
        )
        source_id = (
            "yahoo" if bar.source_label == "yahoo-chart-v8" else bar.source_label
        )
        if fetched is not None and fetched < opened:
            continue
        if fetched is None and when < opened:
            continue
        covered = bar.covered_until
        if (
            bar.close_price is not None
            and fetched is not None
            and fetched >= closed
            and (
                not bar.source_label.startswith("alpaca-bars-v2-")
                or (covered is not None and closed <= covered <= fetched)
            )
        ):
            rows.append(
                _item(
                    evidence_id=f"{source_id}:{bar.symbol}:close:{day.isoformat()}",
                    kind="observation",
                    symbol=bar.symbol,
                    observed_at=closed,
                    available_at=fetched,
                    summary=(
                        f"Daily close {bar.close_price} for {bar.symbol}."
                        + (f" Volume {bar.volume}." if bar.volume is not None else "")
                    ),
                    source_label=bar.source_label,
                    limitations=price_limit
                    + (
                        "admitted only after the session close; "
                        "the first post-close value is kept",
                    ),
                    price=bar.close_price,
                    price_role="close",
                )
            )
    invalidation_by_id: dict[str, TradeInvalidation] = {}
    for notice in collection.trade_invalidations:
        key = f"alpaca:trade-invalid:{notice.trade_id}:{notice.status}"
        if notice.received_at > when or notice.status not in ("canceled", "incorrect"):
            continue
        prior = invalidation_by_id.get(key)
        if prior is None or notice.received_at < prior.received_at:
            invalidation_by_id[key] = notice
    for key, notice in invalidation_by_id.items():
        rows.append(
            _item(
                evidence_id=key,
                kind="news",
                symbol=notice.symbol,
                observed_at=notice.received_at,
                available_at=notice.received_at,
                summary=f"Alpaca reported a previously observed trade {notice.status}.",
                source_label="alpaca-trade-invalidation",
                limitations=(
                    "provider update observed at receipt; not origin authentication",
                ),
            )
        )
    for trade in collection.trades:
        if (
            trade.observed_at > trade.received_at
            or trade.received_at > when
            or trade.update not in (None, "corrected")
        ):
            continue
        rows.append(
            _item(
                evidence_id=trade.source_id,
                kind="observation",
                symbol=trade.symbol,
                observed_at=trade.observed_at,
                available_at=trade.received_at,
                summary=f"Timestamped trade {trade.price} for {trade.symbol}."
                + (
                    " Provider marked it corrected."
                    if trade.update == "corrected"
                    else ""
                ),
                source_label=trade.source_label,
                limitations=(
                    "trade print rounded half-up to cents; not an actual fill",
                ),
                price=trade.price,
                price_role="trade",
            )
        )
    for filing in collection.filings:
        if filing.filed > when:
            continue
        available = filing.fetched_at or when
        if available > when or available < filing.filed:
            continue
        report = f" report {filing.report_date}" if filing.report_date else ""
        excerpt = f" Excerpt: {filing.excerpt}" if filing.excerpt else ""
        rows.append(
            _item(
                evidence_id=f"sec:filing:{filing.accession}",
                kind="news",
                symbol=filing.symbol,
                observed_at=filing.filed,
                available_at=available,
                summary=f"{filing.form} accession {filing.accession}{report}.{excerpt}",
                source_label="sec-filing-text" if filing.excerpt else "sec-submissions",
                limitations=(
                    "SEC filing metadata or short excerpt; not a full filing; "
                    "not origin authentication",
                ),
            )
        )
    conflicting = _conflicting_fact_ids(collection.facts)
    rows.extend(fact_disputes((), collection))
    seen_facts: set[str] = set()
    for fact in collection.facts:
        identity = _fact_id(fact)
        if identity in conflicting or identity in seen_facts:
            continue
        seen_facts.add(identity)
        filed = _fact_time(fact.filed, when)
        if filed is None:
            continue
        rows.append(
            _item(
                evidence_id=identity,
                kind="fundamental",
                symbol=fact.symbol,
                observed_at=filed,
                available_at=when,
                summary=(
                    f"{fact.concept} {fact.value} {fact.unit} "
                    f"period end {fact.end}"
                    + (f" period start {fact.start}" if fact.start else "")
                    + f" form {fact.form} filed {fact.filed}."
                ),
                source_label="sec-companyfacts-pilot",
                limitations=(
                    "SEC companyfacts value; the row may not say which period "
                    "it is; not origin authentication",
                    "date-only filing time is conservatively bounded at the end "
                    "of the New York filing date, not a measured acceptance time",
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
        if suggestion.symbol not in {item.symbol for item in RESEARCH_UNIVERSE}:
            continue
        available = suggestion.received_at or when
        if suggestion.observed_at > available or available > when:
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
                available_at=available,
                summary=suggestion.summary,
                source_label="user-suggestion",
                limitations=(
                    "user suggestion; not market evidence; "
                    "cannot by itself support a trade",
                ),
            )
        )
    return rows


def _fact_id(fact: Fact) -> str:
    return (
        f"sec:fact:{fact.symbol}:{fact.concept}:{fact.end}:"
        f"{fact.start or 'none'}:{fact.filed}:{fact.form}:{fact.unit}:"
        f"accn={fact.accession or 'missing'}"
    )


def _fact_group_id(
    symbol: str, concept: str, end: str, start: str, filed: str, unit: str
) -> str:
    return hashlib.sha256(
        json.dumps([symbol, concept, end, start, filed, unit]).encode()
    ).hexdigest()


def _fact_value(value: str) -> str:
    try:
        number = Decimal(value)
        return str(number.normalize()) if number.is_finite() else value
    except ArithmeticError, ValueError:
        return value


def fact_disputes(
    existing: tuple[EvidenceItem, ...], collection: Collection
) -> tuple[EvidenceItem, ...]:
    """Record conflicts at the time they are discovered, including older facts."""
    values: dict[str, set[str]] = {}
    symbols: dict[str, str] = {}
    for item in existing:
        parts = item.evidence_id.split(":")
        if item.source_label != "sec-companyfacts-pilot" or len(parts) < 10:
            continue
        group = _fact_group_id(
            parts[2], parts[3], parts[4], parts[5], parts[6], ":".join(parts[8:-1])
        )
        words = item.summary.split()
        if len(words) < 2:
            continue
        values.setdefault(group, set()).add(_fact_value(words[1]))
        symbols[group] = item.symbol
    for fact in collection.dispute_facts or collection.facts:
        group = _fact_group_id(
            fact.symbol,
            fact.concept,
            fact.end,
            fact.start or "none",
            fact.filed,
            fact.unit,
        )
        values.setdefault(group, set()).add(_fact_value(fact.value))
        symbols[group] = fact.symbol
    result: list[EvidenceItem] = []
    for group, amounts in values.items():
        if len(amounts) < 2:
            continue
        digest = hashlib.sha256(json.dumps(sorted(amounts)).encode()).hexdigest()
        result.append(
            _item(
                evidence_id=f"sec:fact-dispute:{group}:{digest}",
                kind="news",
                symbol=symbols[group],
                observed_at=collection.collected_at,
                available_at=collection.collected_at,
                summary="Conflicting SEC companyfacts values were observed: "
                + ", ".join(sorted(amounts)),
                source_label="sec-companyfacts-dispute",
                limitations=(
                    "dispute recorded at collection time; source is not authenticated",
                ),
            )
        )
    return tuple(result)


def _conflicting_fact_ids(facts: tuple[Fact, ...] | list[Fact]) -> set[str]:
    values: dict[tuple[str, str, str, str | None, str, str], set[str]] = {}
    for fact in facts:
        key = (fact.symbol, fact.concept, fact.end, fact.start, fact.filed, fact.unit)
        values.setdefault(key, set()).add(_fact_value(fact.value))
    return {
        _fact_id(fact)
        for fact in facts
        if len(
            values[
                (fact.symbol, fact.concept, fact.end, fact.start, fact.filed, fact.unit)
            ]
        )
        > 1
    }


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
    """Defer a date-only fact until the end of its New York filing date."""
    try:
        if "T" in filed:
            parsed = datetime.fromisoformat(filed.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            parsed = parsed.astimezone(UTC)
        else:
            parsed = datetime.combine(
                date.fromisoformat(filed), time.max, tzinfo=NY
            ).astimezone(UTC)
    except ValueError:
        return None
    return parsed if parsed <= when else None


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
    if active_window() is not None and not is_session_day(day):
        return False
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
