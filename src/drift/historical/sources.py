"""Public inputs for one historical replay.

Alpaca is requested first with the stored paper credentials. A refusal is a
gap, not a guessed price. SEC companyfacts and submissions supply fundamentals
and filings. Yahoo chart bars are the labeled fallback for prices.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from drift.prospective.collect import USER_AGENT, cents, fetch_bytes

ALPACA_DATA_HOST = "https://data.alpaca.markets"
ALPACA_BARS_ROUTE = "/v2/stocks/bars"
Feed = Literal["sip", "iex"]


@dataclass(frozen=True)
class PriceBar:
    """One daily open and close. Volume is text, not a fill price."""

    symbol: str
    day: date
    open_price: str
    close_price: str
    volume: str | None
    source_label: str


@dataclass(frozen=True)
class TextInput:
    """A filing or fundamental whose clock is the source time."""

    evidence_id: str
    symbol: str
    kind: Literal["fundamental", "news"]
    observed_at: datetime
    summary: str
    source_label: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PriceBook:
    """Prices, the benchmark, and the gaps observed while collecting them."""

    bars: tuple[PriceBar, ...]
    benchmark: tuple[tuple[date, str], ...]
    benchmark_kind: Literal["sp500_total_return", "price_only_substitute"]
    benchmark_limitation: str
    price_limitation: str
    splits: frozenset[date]
    gaps: tuple[str, ...]


def alpaca_access_gap(status: int | None, feed: str) -> str | None:
    """Describe an Alpaca refusal. ``None`` means that response can be parsed."""
    if status == 200:
        return None
    if status == 401:
        return (
            "Alpaca Market Data API returned HTTP 401 for the stored paper "
            f"credentials on feed {feed}. SIP entitlement, coverage, timestamps, "
            "and adjustment were not observable. No new credential was created."
        )
    if status == 403:
        return (
            "Alpaca Market Data API returned HTTP 403 for "
            f"feed {feed}. That feed is not entitled on the current account."
        )
    if status is None:
        return f"Alpaca Market Data API did not answer for feed {feed}."
    return f"Alpaca Market Data API returned HTTP {status} for feed {feed}."


def credential_names() -> tuple[str, str] | None:
    """Return which existing variable names are set, never their values."""
    pairs = (
        ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"),
    )
    env = dict(os.environ)
    env.update(_dotenv(Path(".env")))
    for key_name, secret_name in pairs:
        if env.get(key_name) and env.get(secret_name):
            return key_name, secret_name
    return None


def probe_alpaca() -> tuple[Feed | None, tuple[str, ...]]:
    """Try SIP, then IEX. The body is discarded; only the status is kept."""
    names = credential_names()
    if names is None:
        return None, (
            "Alpaca credentials are not in the environment or .env. "
            "No new credential was created.",
        )
    gaps: list[str] = []
    for feed in ("sip", "iex"):
        status = _alpaca_status(feed)
        gap = alpaca_access_gap(status, feed)
        if gap is None:
            return feed, tuple(gaps)
        gaps.append(gap)
    return None, tuple(gaps)


def parse_alpaca_bars(symbol: str, payload: object, feed: Feed) -> tuple[PriceBar, ...]:
    """Daily bars from ``GET /v2/stocks/bars``. Timestamps become New York dates."""
    if not isinstance(payload, dict):
        return ()
    bars = payload.get("bars")
    if not isinstance(bars, dict):
        return ()
    rows = bars.get(symbol)
    if not isinstance(rows, list):
        return ()
    parsed: list[PriceBar] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        stamp = item.get("t")
        if not isinstance(stamp, str):
            continue
        opened = cents(item.get("o"))
        closed = cents(item.get("c"))
        if opened is None or closed is None:
            continue
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            continue
        volume = item.get("v")
        volume_text = str(volume) if isinstance(volume, int | float) else None
        parsed.append(
            PriceBar(
                symbol=symbol,
                day=observed.astimezone(NY).date(),
                open_price=opened,
                close_price=closed,
                volume=volume_text,
                source_label=f"alpaca-bars-v2-{feed}-raw",
            )
        )
    return tuple(parsed)


def parse_yahoo_chart(symbol: str, payload: object) -> tuple[PriceBar, ...]:
    """Quote open and close from a Yahoo chart payload. Adjusted close is not used."""
    frame = _yahoo_frame(payload)
    if frame is None:
        return ()
    stamps, opens, closes, _adj, volumes = frame
    rows: list[PriceBar] = []
    for index, stamp in enumerate(stamps):
        if isinstance(stamp, bool) or not isinstance(stamp, int | float):
            continue
        opened = cents(opens[index]) if index < len(opens) else None
        closed = cents(closes[index]) if index < len(closes) else None
        if opened is None or closed is None:
            continue
        volume = volumes[index] if index < len(volumes) else None
        volume_text = str(volume) if isinstance(volume, int | float) else None
        observed = datetime.fromtimestamp(int(stamp), UTC)
        rows.append(
            PriceBar(
                symbol=symbol,
                day=observed.astimezone(NY).date(),
                open_price=opened,
                close_price=closed,
                volume=volume_text,
                source_label="yahoo-chart-v8",
            )
        )
    return tuple(rows)


def yahoo_adjustment_note(payload: object) -> str | None:
    """Return a note when quote close and adjusted close differ."""
    frame = _yahoo_frame(payload)
    if frame is None:
        return None
    _stamps, _opens, closes, adjusted, _volumes = frame
    for index, close in enumerate(closes):
        if index >= len(adjusted):
            continue
        left = cents(close)
        right = cents(adjusted[index])
        if left is not None and right is not None and left != right:
            return (
                "Yahoo quote close differs from adjusted close. "
                "The replay uses quote open and close, so dividends "
                "are not in the price."
            )
    return None


def yahoo_split_dates(payload: object) -> frozenset[date]:
    """Split dates declared by the chart payload."""
    if not isinstance(payload, dict):
        return frozenset()
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return frozenset()
    result = chart.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return frozenset()
    events = result[0].get("events")
    if not isinstance(events, dict):
        return frozenset()
    splits = events.get("splits")
    if not isinstance(splits, dict):
        return frozenset()
    found: set[date] = set()
    for value in splits.values():
        if not isinstance(value, dict):
            continue
        raw = value.get("date")
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            found.add(datetime.fromtimestamp(int(raw), UTC).astimezone(NY).date())
            continue
        text = value.get("splitDate") or value.get("date")
        if isinstance(text, str):
            found.add(date.fromisoformat(text[:10]))
    return frozenset(found)


def parse_company_facts(symbol: str, payload: object) -> tuple[TextInput, ...]:
    """Revenue and diluted EPS rows with their filed dates. Ambiguous rows are kept."""
    if not isinstance(payload, dict):
        return ()
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return ()
    gaap = facts.get("us-gaap")
    if not isinstance(gaap, dict):
        return ()
    chosen: list[TextInput] = []
    concepts = (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "EarningsPerShareDiluted",
    )
    for concept in concepts:
        block = gaap.get(concept)
        if not isinstance(block, dict):
            continue
        units = block.get("units")
        if not isinstance(units, dict):
            continue
        for unit, rows in units.items():
            if not isinstance(unit, str) or not isinstance(rows, list):
                continue
            for row in rows:
                item = _fact_row(symbol, concept, unit, row)
                if item is not None:
                    chosen.append(item)
    return tuple(chosen)


def parse_submission_filings(symbol: str, payload: object) -> tuple[TextInput, ...]:
    """10-K, 10-Q, and 8-K rows from one SEC submissions document."""
    recent = _recent_table(payload)
    if recent is None:
        return ()
    forms = recent.get("form")
    accessions = recent.get("accessionNumber")
    filed = recent.get("acceptanceDateTime")
    if not isinstance(forms, list) or not isinstance(accessions, list):
        return ()
    if not isinstance(filed, list):
        filed = []
    rows: list[TextInput] = []
    allowed = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"}
    for index, form in enumerate(forms):
        if not isinstance(form, str) or form not in allowed:
            continue
        if index >= len(accessions) or not isinstance(accessions[index], str):
            continue
        raw_time = filed[index] if index < len(filed) else None
        observed = _filing_time(raw_time)
        if observed is None:
            continue
        accession = accessions[index]
        rows.append(
            TextInput(
                evidence_id=f"sec:filing:{accession}",
                symbol=symbol,
                kind="news",
                observed_at=observed,
                summary=f"{form} accession {accession}.",
                source_label="sec-submissions",
                limitations=(
                    "SEC submissions row; not the full filing text; "
                    "not origin authentication",
                ),
            )
        )
    return tuple(rows)


def submission_file_names(payload: object) -> tuple[str, ...]:
    """Older submission file names declared beside the recent table."""
    if not isinstance(payload, dict):
        return ()
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return ()
    files = filings.get("files")
    if not isinstance(files, list):
        return ()
    names: list[str] = []
    for item in files:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return tuple(names)


def benchmark_level(text: str) -> Decimal | None:
    """Parse one positive level. Unusable text is absence, not zero."""
    parsed = cents(text)
    if parsed is None:
        return None
    return Decimal(parsed)


def _fact_row(symbol: str, concept: str, unit: str, row: object) -> TextInput | None:
    if not isinstance(row, dict):
        return None
    end = row.get("end")
    filed = row.get("filed")
    form = row.get("form")
    value = row.get("val")
    if (
        not isinstance(end, str)
        or not isinstance(filed, str)
        or not isinstance(form, str)
    ):
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    observed = datetime.fromisoformat(f"{filed}T21:00:00+00:00")
    return TextInput(
        evidence_id=f"sec:fact:{symbol}:{concept}:{end}:{filed}:{form}:{unit}",
        symbol=symbol,
        kind="fundamental",
        observed_at=observed,
        summary=(
            f"{concept} {value} {unit} period end {end} form {form} filed {filed}."
        ),
        source_label="sec-companyfacts",
        limitations=(
            "SEC companyfacts value placed at 21:00 UTC on the filed date; "
            "the row may not say which period it is; not origin authentication",
        ),
    )


def _recent_table(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    filings = payload.get("filings")
    if isinstance(filings, dict):
        recent = filings.get("recent")
        if isinstance(recent, dict):
            return recent
    if isinstance(payload.get("form"), list):
        return payload
    return None


def _filing_time(value: object) -> datetime | None:
    if not isinstance(value, str) or value == "":
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _yahoo_frame(
    payload: object,
) -> tuple[list[object], list[object], list[object], list[object], list[object]] | None:
    if not isinstance(payload, dict):
        return None
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return None
    result = chart.get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        return None
    first = result[0]
    stamps = first.get("timestamp")
    indicators = first.get("indicators")
    if not isinstance(stamps, list) or not isinstance(indicators, dict):
        return None
    quote = indicators.get("quote")
    if not isinstance(quote, list) or not quote or not isinstance(quote[0], dict):
        return None
    opens = quote[0].get("open")
    closes = quote[0].get("close")
    volumes = quote[0].get("volume")
    if not isinstance(opens, list) or not isinstance(closes, list):
        return None
    adjusted_rows = indicators.get("adjclose")
    adjusted: list[object] = []
    if (
        isinstance(adjusted_rows, list)
        and adjusted_rows
        and isinstance(adjusted_rows[0], dict)
    ):
        raw = adjusted_rows[0].get("adjclose")
        if isinstance(raw, list):
            adjusted = raw
    volume_rows = volumes if isinstance(volumes, list) else []
    return stamps, opens, closes, adjusted, volume_rows


def _alpaca_status(feed: Feed) -> int | None:
    names = credential_names()
    if names is None:
        return None
    env = dict(os.environ)
    env.update(_dotenv(Path(".env")))
    key = env[names[0]]
    secret = env[names[1]]
    query = urllib.parse.urlencode(
        {
            "symbols": "AAPL",
            "timeframe": "1Day",
            "start": "2024-11-01T00:00:00Z",
            "end": "2024-11-05T00:00:00Z",
            "adjustment": "raw",
            "feed": feed,
            "limit": "2",
        }
    )
    request = urllib.request.Request(
        f"{ALPACA_DATA_HOST}{ALPACA_BARS_ROUTE}?{query}",
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
            status = response.status
            return status if isinstance(status, int) else None
    except urllib.error.HTTPError as error:
        return error.code
    except OSError, urllib.error.URLError:
        return None


def _dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        found[name] = value.strip().strip('"').strip("'")
    return found


NY = ZoneInfo("America/New_York")


def load_cached_json(path: Path) -> object:
    """Read one cached response. The caller treats a missing file as a gap."""
    return json.loads(path.read_text(encoding="utf-8"))


def cache_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def fetch_json(url: str) -> tuple[object | None, str | None]:
    """GET JSON. A network or parse failure is a gap string."""
    try:
        body = fetch_bytes(url)
    except (OSError, urllib.error.URLError) as error:
        return None, str(error)
    try:
        return json.loads(body), None
    except json.JSONDecodeError as error:
        return None, str(error)
