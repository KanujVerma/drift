"""Local v0.2 simulation settings.

These numbers reuse the prior comparison where that comparison still
fits a $10,000 book. They are not an approved product mandate.
See docs/V02.md.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from drift.manager.models import (
    PROSPECTIVE_READINESS,
    PROSPECTIVE_SEAL_REQUIRED,
    REQUIRED_MANDATE_ACKNOWLEDGEMENTS,
    Instrument,
    SimulationMandate,
    SimulationSession,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.window import NYSECalendar as NYSECalendar
from drift.prospective.window import active_window
from drift.prospective.window import build_window as build_window
from drift.research.universe import RESEARCH_UNIVERSE

NY = ZoneInfo("America/New_York")
OBSERVATION_COUNT = 20
# Sessions after the 20th exist so the last decision can fill. They are
# not extra observation decisions.
FILL_TAIL = 5
START = date(2026, 11, 27)
HOLIDAYS = frozenset({date(2026, 12, 25), date(2027, 1, 1)})
EARLY_CLOSE = frozenset({date(2026, 11, 27), date(2026, 12, 24)})

# Comparison book: 0.25 position fraction, $1 simulation fee, whole shares,
# 336-hour evidence age on the multi-session path. The comparison cash floor
# was $20,000 of $100,000. This book uses the same 20% floor, $2,000 of
# $10,000. The 72-hour controlled-case age is not used here.
CASH = "10000"
MAX_POSITION_FRACTION = "0.25"
MIN_CASH_AFTER = "2000"
EVIDENCE_AGE_HOURS = 336
FILL_FEE = "1"

UNIVERSE = (
    ("AAPL", "0000320193", "Apple Inc."),
    ("MSFT", "0000789019", "Microsoft Corporation"),
    ("JNJ", "0000200406", "Johnson & Johnson"),
    ("SPY", "0000884394", "SPDR S&P 500 ETF Trust"),
)
# Pilot trading authorization is explicit; a research-universe addition alone
# cannot authorize simulated trading. UNIVERSE remains the historical set.
TRADING_SYMBOLS = (
    "AAPL",
    "MSFT",
    "AMZN",
    "JPM",
    "JNJ",
    "XOM",
    "CAT",
    "PG",
    "NEE",
    "LIN",
    "SPY",
    "QQQ",
    "MDY",
)
MODELS = {
    "terra": "codex/gpt-6.1-terra@xhigh",
    "sol": "codex/gpt-6.2-sol@xhigh",
}


def trading_dates(count: int) -> tuple[date, ...]:
    """Weekdays from the first eligible session, skipping listed holidays."""
    found: list[date] = []
    day = START
    while len(found) < count:
        if day.weekday() < 5 and day not in HOLIDAYS:
            found.append(day)
        day += timedelta(days=1)
    return tuple(found)


def observation_dates() -> tuple[date, ...]:
    active = active_window()
    if active is not None:
        return active.observation_dates
    return trading_dates(OBSERVATION_COUNT)


def calendar_dates() -> tuple[date, ...]:
    active = active_window()
    if active is not None:
        return active.dates
    return trading_dates(OBSERVATION_COUNT + FILL_TAIL)


def is_session_day(day: date) -> bool:
    active = active_window()
    if active is None:
        return day.weekday() < 5 and day not in HOLIDAYS
    try:
        return active.calendar.is_session(day)
    except ValueError:
        return False


def session_open_utc(day: date) -> datetime:
    """09:30 America/New_York, converted to UTC for that date."""
    active = active_window()
    return (
        active.calendar.open(day)
        if active is not None
        else datetime.combine(day, time(9, 30), tzinfo=NY).astimezone(UTC)
    )


def session_close_utc(day: date) -> datetime:
    """16:00 America/New_York, or 13:00 on an early close, converted to UTC."""
    active = active_window()
    if active is not None:
        return active.calendar.close(day)
    hour = 13 if day in EARLY_CLOSE else 16
    return datetime.combine(day, time(hour, 0), tzinfo=NY).astimezone(UTC)


def next_session_open_after(moment: datetime) -> datetime | None:
    """The next 09:30 America/New_York open strictly after ``moment``."""
    current = moment.astimezone(UTC)
    for day in calendar_dates():
        opened = session_open_utc(day)
        if opened > current:
            return opened
    return None


def submission_is_late(issued: datetime, now: datetime) -> bool:
    """True once the wall clock has reached the next session open after the review."""
    opened = next_session_open_after(issued)
    return opened is not None and now >= opened


def bar_session_day(observed: datetime) -> date:
    """Trading date of a Yahoo daily bar, in America/New_York."""
    return observed.astimezone(NY).date()


def in_settlement_window(moment: datetime) -> bool:
    """True on a post-observation session that exists only to fill the last decision."""
    current = moment.astimezone(UTC)
    observed = set(observation_dates())
    for day in calendar_dates():
        if day in observed:
            continue
        window = session_for(day)
        if window.opened_at <= current <= window.closed_at:
            return True
    return False


def session_for(day: date) -> SimulationSession:
    """Review window for one New York trading date.

    The close is 23:59 UTC so an after-close review still lands on that
    date. It is not the exchange close. Early closes are disclosed beside
    the date rather than by shrinking the review window.
    """
    return SimulationSession(
        local_date=day,
        opened_at=session_open_utc(day)
        if active_window() is not None
        else datetime.combine(day, time(14, 30), tzinfo=UTC),
        closed_at=datetime.combine(day, time(23, 59), tzinfo=UTC),
    )


def instruments() -> tuple[Instrument, ...]:
    """The original v0.2 and historical-replay instrument set."""
    return tuple(
        Instrument(
            symbol=symbol,
            security_id=deterministic_memory_uuid7(f"prospective-v02:{symbol}"),
            name=name,
        )
        for symbol, _cik, name in UNIVERSE
    )


def pilot_instruments() -> tuple[Instrument, ...]:
    return tuple(
        Instrument(
            symbol=item.symbol,
            security_id=deterministic_memory_uuid7(f"prospective-v02:{item.symbol}"),
            name=item.name,
        )
        for item in RESEARCH_UNIVERSE
    )


def mandate() -> SimulationMandate:
    return SimulationMandate(
        mode="simulation_only",
        allowed_symbols=tuple(symbol for symbol, _cik, _name in UNIVERSE),
        max_position_notional_fraction=MAX_POSITION_FRACTION,
        min_cash_after=MIN_CASH_AFTER,
        max_evidence_age_hours=EVIDENCE_AGE_HOURS,
        fill_fee=FILL_FEE,
        fill_price_source="post_decision_execution",
        position_check="cost_basis_denominator",
        whole_shares_only=True,
        acknowledgements=REQUIRED_MANDATE_ACKNOWLEDGEMENTS
        + (
            "v0.2 limits are local test configuration, not an approved product mandate",
        ),
    )


def pilot_mandate() -> SimulationMandate:
    """The expanded pilot authority does not alter the v0.2 baseline."""
    base = mandate()
    return base.model_copy(
        update={
            "allowed_symbols": TRADING_SYMBOLS,
            "citation_policy": "research",
            "acknowledgements": base.acknowledgements + (PROSPECTIVE_SEAL_REQUIRED,),
        }
    )


def readiness_mandate() -> SimulationMandate:
    pilot = pilot_mandate()
    return pilot.model_copy(
        update={
            "acknowledgements": tuple(
                item
                for item in pilot.acknowledgements
                if item != PROSPECTIVE_SEAL_REQUIRED
            )
            + (PROSPECTIVE_READINESS,)
        }
    )


def observation_date(moment: datetime) -> date | None:
    """Trading date on which a new observation decision may be recorded."""
    local = moment.astimezone(NY)
    if local.date() not in set(observation_dates()):
        return None
    window = session_for(local.date())
    current = moment.astimezone(UTC)
    if not window.opened_at <= current <= window.closed_at:
        return None
    return local.date()


def next_session_open(moment: datetime) -> datetime | None:
    """Next 09:30 America/New_York open in the observation window."""
    local = moment.astimezone(NY)
    for day in observation_dates():
        opened = session_open_utc(day).astimezone(NY)
        if opened > local:
            return opened
    return None


def eligibility_message(moment: datetime) -> str | None:
    """Remaining launch requirement, or None when a decision is eligible."""
    if observation_date(moment) is not None:
        return None
    opened = next_session_open(moment)
    if opened is None:
        return "the 20-session observation window has no remaining open"
    early = ""
    active = active_window()
    early_closes = active.calendar.early_closes if active is not None else EARLY_CLOSE
    if opened.astimezone(NY).date() in early_closes:
        early = " NYSE lists an early close at 13:00 America/New_York."
    stamp = opened.astimezone(NY).strftime("%Y-%m-%d %H:%M %Z")
    return (
        "no observation decision is eligible now. "
        f"Next session open is {stamp}.{early} "
        "Run python -m drift.prospective daily --role observation after that "
        "open. Do not record a session before then."
    )
