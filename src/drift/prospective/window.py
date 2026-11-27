"""An immutable prospective window derived from NYSE's published calendar."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
NYSE_URL = "https://www.nyse.com/trade/hours-calendars"
PILOT_VERSION = "0.6"
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}
_DATE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday),\s+([A-Za-z]+)\s+(\d{1,2})(?:,\s*(20\d{2}))?"
)
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_HOLIDAYS = frozenset(
    {
        "New Year’s Day",
        "Martin Luther King, Jr. Day",
        "Washington's Birthday",
        "Good Friday",
        "Memorial Day",
        "Juneteenth National Independence Day",
        "Independence Day",
        "Labor Day",
        "Thanksgiving Day",
        "Christmas Day",
    }
)


class _CalendarHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.paragraph: list[str] | None = None
        self.rows: list[list[str]] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"th", "td"}:
            self.cell = []
        if tag == "p":
            self.paragraph = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)
        if self.paragraph is not None:
            self.paragraph.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            self.rows.append([])
        if tag == "p" and self.paragraph is not None:
            self.paragraphs.append(" ".join("".join(self.paragraph).split()))
            self.paragraph = None


def _published_date(match: re.Match[str], year: int) -> date:
    weekday, month, day, explicit_year = match.groups()
    if explicit_year is not None and int(explicit_year) != year:
        raise ValueError("NYSE calendar year does not match its column")
    if month not in _MONTHS:
        raise ValueError("NYSE calendar has an unknown month")
    value = date(year, _MONTHS[month], int(day))
    if _WEEKDAYS[value.weekday()] != weekday:
        raise ValueError("NYSE calendar weekday does not match the date")
    return value


def parse_nyse_calendar(body: bytes) -> NYSECalendar:
    """Parse the official holiday table; refuse incomplete or unfamiliar layouts."""
    parser = _CalendarHTML()
    parser.feed(body.decode("utf-8", errors="strict"))
    headers = [i for i, row in enumerate(parser.rows) if row and row[0] == "Holiday"]
    if len(headers) != 1:
        raise ValueError("NYSE holiday table is missing or ambiguous")
    header = parser.rows[headers[0]]
    try:
        years = tuple(int(value) for value in header[1:])
    except ValueError as error:
        raise ValueError("NYSE calendar years are invalid") from error
    if len(years) < 2 or tuple(range(years[0], years[0] + len(years))) != years:
        raise ValueError("NYSE calendar years are incomplete")
    rows: dict[str, list[str]] = {}
    for row in parser.rows[headers[0] + 1 :]:
        if not row:
            break
        if row[0] not in _HOLIDAYS:
            raise ValueError("NYSE holiday table contains an unrecognized row")
        if row[0] in rows or len(row) != len(years) + 1:
            raise ValueError("NYSE holiday rows are ambiguous")
        rows[row[0]] = row[1:]
    if set(rows) != _HOLIDAYS:
        raise ValueError("NYSE holiday table is incomplete")
    holidays: set[date] = set()
    thanksgiving: dict[int, date] = {}
    expected_early: set[date] = set()
    for name, values in rows.items():
        for year, cell in zip(years, values, strict=True):
            match = _DATE.match(cell)
            if match is None:
                if (
                    name == "New Year’s Day"
                    and date(year, 1, 1).weekday() == 5
                    and cell.startswith("—")
                ):
                    continue
                raise ValueError("NYSE holiday date is missing")
            value = _published_date(match, year)
            if value in holidays:
                raise ValueError("NYSE holiday dates are duplicated")
            holidays.add(value)
            if name == "Thanksgiving Day":
                thanksgiving[year] = value
            if name == "Christmas Day" and "****" in cell:
                expected_early.add(value - timedelta(days=1))
            if name == "Independence Day" and "**" in cell:
                expected_early.add(value - timedelta(days=1))
    early: set[date] = set()
    for paragraph in parser.paragraphs:
        if (
            "closed" in paragraph.casefold() or "closure" in paragraph.casefold()
        ) and _DATE.search(paragraph):
            raise ValueError("unrecognized NYSE closure notice")
        if "Each market will close early at 1:00 p.m." not in paragraph:
            if "close early" in paragraph.casefold():
                raise ValueError("unrecognized NYSE early-close notice")
            continue
        matches = list(_DATE.finditer(paragraph))
        if not matches or any(match.group(4) is None for match in matches):
            raise ValueError("NYSE early-close dates are incomplete")
        for match in matches:
            year = int(match.group(4))
            if year not in years:
                raise ValueError("NYSE early-close year is outside the table")
            early.add(_published_date(match, year))
    expected_early.update(value + timedelta(days=1) for value in thanksgiving.values())
    if not expected_early.issubset(early):
        raise ValueError("NYSE early-close dates are incomplete")
    if early & holidays or any(day.weekday() >= 5 for day in early):
        raise ValueError("NYSE early-close dates conflict with holidays")
    return NYSECalendar(
        years=years, holidays=tuple(sorted(holidays)), early_closes=tuple(sorted(early))
    )


@dataclass(frozen=True)
class NYSECalendar:
    years: tuple[int, ...]
    holidays: tuple[date, ...]
    early_closes: tuple[date, ...]

    def is_session(self, day: date) -> bool:
        if day.year not in self.years:
            raise ValueError("NYSE calendar does not cover the requested date")
        return day.weekday() < 5 and day not in self.holidays

    def open(self, day: date) -> datetime:
        if not self.is_session(day):
            raise ValueError("date is not an NYSE session")
        return datetime.combine(day, time(9, 30), tzinfo=NY).astimezone(UTC)

    def close(self, day: date) -> datetime:
        if not self.is_session(day):
            raise ValueError("date is not an NYSE session")
        hour = 13 if day in self.early_closes else 16
        return datetime.combine(day, time(hour), tzinfo=NY).astimezone(UTC)


@dataclass(frozen=True)
class ProspectiveWindow:
    calendar: NYSECalendar
    dates: tuple[date, ...]
    source_sha256: str = ""
    source_received_at: datetime | None = None
    requested_start: date | None = None

    @property
    def observation_dates(self) -> tuple[date, ...]:
        return self.dates[:20]

    @property
    def settlement_dates(self) -> tuple[date, ...]:
        return self.dates[20:]

    @property
    def binding(self) -> str:
        if (
            not self.source_sha256
            or self.source_received_at is None
            or self.requested_start is None
        ):
            raise ValueError("window is not bound to a retained NYSE source")
        body = {
            "pilot_version": PILOT_VERSION,
            "source_sha256": self.source_sha256,
            "source_received_at": self.source_received_at.astimezone(UTC).isoformat(),
            "requested_start": self.requested_start.isoformat(),
            "dates": [day.isoformat() for day in self.dates],
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


_ACTIVE_WINDOW: ContextVar[ProspectiveWindow | None] = ContextVar(
    "prospective_window", default=None
)


def active_window() -> ProspectiveWindow | None:
    return _ACTIVE_WINDOW.get()


@contextmanager
def window_scope(state: Path) -> Iterator[None]:
    token = _ACTIVE_WINDOW.set(load_window(state))
    try:
        yield
    finally:
        _ACTIVE_WINDOW.reset(token)


def build_window(
    *, requested_start: date, now: datetime, calendar: NYSECalendar
) -> ProspectiveWindow:
    if now.tzinfo is None:
        raise ValueError("window clock must be timezone-aware")
    day = max(requested_start, now.astimezone(NY).date())
    dates: list[date] = []
    while len(dates) < 25:
        if calendar.is_session(day) and calendar.open(day) > now.astimezone(UTC):
            dates.append(day)
        day += timedelta(days=1)
    return ProspectiveWindow(calendar=calendar, dates=tuple(dates))


def _clock() -> datetime:
    return datetime.now(UTC)


def _fetch_nyse() -> tuple[bytes, datetime]:
    request = urllib.request.Request(
        NYSE_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = urllib.parse.urlsplit(response.geturl())
        if final_url.scheme != "https" or final_url.hostname != "www.nyse.com":
            raise ValueError("NYSE calendar redirected outside its authorized origin")
        body = response.read(5_000_001)
    received_at = _clock()
    if len(body) > 5_000_000:
        raise ValueError("NYSE calendar response is too large")
    return body, received_at


def _immutable_write(path: Path, body: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ValueError(
                    "prospective window evidence conflicts with the existing file"
                ) from None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_window(state: Path) -> ProspectiveWindow | None:
    path = state / "window.json"
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "1"
            or document.get("pilot_version") != PILOT_VERSION
            or document.get("source_url") != NYSE_URL
        ):
            raise ValueError("invalid prospective window record")
        digest = document.get("source_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid NYSE source hash")
        source = (state / f"nyse-calendar-{digest}.html").read_bytes()
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError("NYSE calendar source hash mismatch")
        received = datetime.fromisoformat(document["source_received_at"])
        requested = date.fromisoformat(document["requested_start"])
        if received.tzinfo is None or received > _clock():
            raise ValueError("NYSE calendar receipt is invalid")
        derived = build_window(
            requested_start=requested,
            now=received,
            calendar=parse_nyse_calendar(source),
        )
        if document.get("dates") != [day.isoformat() for day in derived.dates]:
            raise ValueError("prospective window dates do not match the source")
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise ValueError("prospective window record cannot be recovered") from error
    return ProspectiveWindow(
        derived.calendar, derived.dates, digest, received, requested
    )


def configure_window(
    state: Path, *, requested_start: date | None = None
) -> ProspectiveWindow:
    """Capture NYSE data and establish one immutable, future-only window."""
    from drift.prospective.locking import pilot_lock

    state = state.resolve()
    source_tree = Path(__file__).resolve().parents[3]
    if state.is_relative_to(source_tree):
        raise ValueError("prospective state must be outside the source tree")
    with pilot_lock(state):
        existing = load_window(state)
        if existing is not None:
            if (
                requested_start is not None
                and existing.requested_start != requested_start
            ):
                raise ValueError(
                    "prospective window is immutable; use a new state directory"
                )
            if (
                not any(
                    (state / "observation" / f"{name}.sqlite").exists()
                    for name in ("terra", "sol")
                )
                and existing.calendar.open(existing.dates[0]) <= _clock()
            ):
                raise ValueError(
                    "unstarted window has expired; use a new state directory"
                )
            return existing
        if any(
            (state / "observation" / f"{name}.sqlite").exists()
            for name in ("terra", "sol")
        ):
            raise ValueError(
                "existing observation books require a versioned transition"
            )
        source, received = _fetch_nyse()
        if received.tzinfo is None or received > _clock():
            raise ValueError("NYSE calendar receipt is invalid")
        requested = requested_start or received.astimezone(NY).date()
        selected = build_window(
            requested_start=requested,
            now=received,
            calendar=parse_nyse_calendar(source),
        )
        digest = hashlib.sha256(source).hexdigest()
        document = {
            "schema_version": "1",
            "pilot_version": PILOT_VERSION,
            "source_url": NYSE_URL,
            "source_received_at": received.astimezone(UTC).isoformat(),
            "source_sha256": digest,
            "requested_start": requested.isoformat(),
            "dates": [day.isoformat() for day in selected.dates],
        }
        _immutable_write(state / f"nyse-calendar-{digest}.html", source)
        _immutable_write(
            state / "window.json",
            (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(),
        )
        recovered = load_window(state)
        if recovered is None:
            raise ValueError("prospective window was not retained")
        return recovered


def verify_current_window(state: Path) -> None:
    """Recheck remaining sessions and retain the source response before use."""
    configured = active_window() or load_window(state)
    if configured is None:
        raise ValueError("prospective window is not configured")
    try:
        source, received = _fetch_nyse()
    except (OSError, ValueError) as error:
        observed = _clock().astimezone(UTC)
        checks = state / "calendar-checks"
        checks.mkdir(parents=True, exist_ok=True)
        stamp = observed.strftime("%Y%m%dT%H%M%S.%fZ")
        failure_record = {
            "pilot_version": PILOT_VERSION,
            "source_url": NYSE_URL,
            "failure_observed_at": observed.isoformat(),
            "window_binding": configured.binding,
            "status": "unavailable",
            "reason": type(error).__name__,
        }
        _immutable_write(
            checks / f"{stamp}-unavailable.json",
            (json.dumps(failure_record, indent=2, sort_keys=True) + "\n").encode(),
        )
        raise ValueError("NYSE calendar unavailable; no run was started") from error
    if received.tzinfo is None or received > _clock():
        raise ValueError("NYSE calendar receipt is invalid")
    digest = hashlib.sha256(source).hexdigest()
    _immutable_write(state / f"nyse-calendar-{digest}.html", source)
    reason: str | None = None
    try:
        current = parse_nyse_calendar(source)
        today = received.astimezone(NY).date()
        day = configured.dates[0]
        while day <= configured.dates[-1]:
            if day.year not in current.years and day < today:
                day += timedelta(days=1)
                continue
            old_session = configured.calendar.is_session(day)
            new_session = current.is_session(day)
            if old_session != new_session or (
                old_session
                and (
                    configured.calendar.open(day) != current.open(day)
                    or configured.calendar.close(day) != current.close(day)
                )
            ):
                reason = f"NYSE calendar changed for {day.isoformat()}"
                break
            day += timedelta(days=1)
    except (UnicodeError, ValueError) as error:
        reason = f"NYSE calendar could not be verified: {error}"
    checks = state / "calendar-checks"
    checks.mkdir(parents=True, exist_ok=True)
    stamp = received.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    record = {
        "pilot_version": PILOT_VERSION,
        "source_url": NYSE_URL,
        "source_received_at": received.astimezone(UTC).isoformat(),
        "source_sha256": digest,
        "window_binding": configured.binding,
        "status": "compatible" if reason is None else "refused",
        "reason": reason,
    }
    _immutable_write(
        checks / f"{stamp}-{digest}.json",
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
    )
    if reason is not None:
        raise ValueError(reason)
