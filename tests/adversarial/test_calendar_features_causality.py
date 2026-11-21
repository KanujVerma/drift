"""Issue 662 adversarial causality: knowledge after a cutoff never moves it.

The features of a session depend only on schedule rows and event records
known strictly before the session's cutoff. These tests attack that rule from
outside: they truncate everything a cutoff cannot see, revise every row and
event after it, add rows for dates that had none, announce a closure late,
and forge records and inputs. Every availability instant here is synthetic.
"""

# ruff: noqa: E402

import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from random import Random

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from pydantic import ValidationError
from test_calendar_features import (
    CHANNEL,
    FOMC_KIND,
    JANUARY,
    JANUARY_WITH_MOURNING,
    MOURNING_ANNOUNCED,
    MOURNING_DAY,
    NYSE_HOLIDAYS,
    SCHEDULE_PUBLISHED,
    RowState,
    bounded_availability,
    compute,
    date_availability,
    dates_between,
    evening_before,
    event_record,
    exact_availability,
    request,
    schedule_row,
)

from drift.domain.calendar_features import (
    CalendarEventRecordV1,
    CalendarFeatureInputError,
    CalendarFeatureSetV1,
    CalendarSessionFeaturesV1,
)
from drift.domain.sessions import ScheduledSessionVersionV1
from drift.domain.temporal import AvailabilityEvidenceV1
from drift.serialization.canonical import content_hash

type Window = tuple[date, datetime, datetime]

STATES: tuple[RowState, ...] = ("regular", "early_close", "closed", "unknown")
#: Cutoffs start just after the base rows, so a truncated schedule is never
#: empty (an empty schedule is refused, not answered).
WINDOW_START = SCHEDULE_PUBLISHED + timedelta(seconds=1)
WINDOW_END = datetime(2025, 3, 31, tzinfo=UTC)
FOMC_PUBLISHED = datetime(2024, 8, 1, 12, tzinfo=UTC)


def _instant(rng: Random, lower: datetime, upper: datetime) -> datetime:
    """A whole-second instant in ``[lower, upper)``."""
    span = int((upper - lower).total_seconds())
    return lower + timedelta(seconds=rng.randrange(span))


def _bounds(row: ScheduledSessionVersionV1) -> tuple[datetime, datetime]:
    """The row's availability window on the one channel these tests use."""
    (evidence,) = row.revision.availability
    assert evidence.lower_bound is not None and evidence.upper_bound is not None
    return evidence.lower_bound, evidence.upper_bound


def _correction_evidence(
    rng: Random, after: datetime, kind: str
) -> AvailabilityEvidenceV1:
    """Exact, bounded or DATE-precision evidence starting at or after ``after``."""
    start = _instant(rng, after, max(WINDOW_END, after + timedelta(days=1)))
    if kind == "exact":
        return exact_availability(start)
    if kind == "bounded":
        width = timedelta(seconds=rng.randrange(3600, 20 * 86_400))
        return bounded_availability(start, start + width)
    return date_availability((start + timedelta(days=2)).date())


def _tails(
    rows: list[ScheduledSessionVersionV1],
) -> dict[date, ScheduledSessionVersionV1]:
    tails: dict[date, ScheduledSessionVersionV1] = {}
    for row in rows:
        day = row.session_key.local_date
        if (
            day not in tails
            or row.revision.source_sequence > tails[day].revision.source_sequence
        ):
            tails[day] = row
    return tails


def _revised_history(
    rng: Random,
) -> tuple[list[ScheduledSessionVersionV1], list[Window]]:
    """Base rows, the late closure, and random corrections.

    Corrections carry exact, bounded or DATE-precision availability, each
    window starting no earlier than its predecessor's ends. Returns the rows
    and the (date, lower, upper) window of every non-exact correction.
    """
    rows = list(JANUARY_WITH_MOURNING)
    windows: list[Window] = []
    kinds = ["bounded", "date"]
    kinds += [rng.choice(("exact", "bounded", "date")) for _ in range(16)]
    for kind in kinds:
        tails = _tails(rows)
        day = rng.choice(sorted(tails))
        tail = tails[day]
        evidence = _correction_evidence(rng, _bounds(tail)[1], kind)
        assert evidence.lower_bound is not None and evidence.upper_bound is not None
        rows.append(
            schedule_row(
                day,
                rng.choice(STATES),
                available_at=evidence.upper_bound,
                predecessor=tail,
                availability=(evidence,),
            )
        )
        if kind != "exact":
            windows.append((day, evidence.lower_bound, evidence.upper_bound))
    return rows, windows


def _events() -> list[CalendarEventRecordV1]:
    return [
        event_record("fomc-2024-12", date(2024, 12, 18), FOMC_PUBLISHED),
        event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),
        event_record(
            "fomc-2025-01",
            date(2025, 1, 30),
            datetime(2025, 1, 15, tzinfo=UTC),
            revision=1,
        ),
        event_record("fomc-2025-03", date(2025, 3, 19), FOMC_PUBLISHED),
        event_record(
            "fomc-2025-03",
            date(2025, 3, 19),
            datetime(2025, 2, 3, tzinfo=UTC),
            revision=1,
            status="cancelled",
        ),
    ]


def _known_rows(
    rows: list[ScheduledSessionVersionV1], as_of: datetime
) -> list[ScheduledSessionVersionV1]:
    """Drop every version definitely not available strictly before ``as_of``.

    A version whose window spans the cutoff stays: it may already be known,
    and that possibility is knowledge the features must respect.
    """
    return [row for row in rows if _bounds(row)[0] < as_of]


def _known_events(
    events: list[CalendarEventRecordV1], as_of: datetime
) -> list[CalendarEventRecordV1]:
    return [record for record in events if record.published_at < as_of]


def _revised_after(
    rng: Random,
    rows: list[ScheduledSessionVersionV1],
    events: list[CalendarEventRecordV1],
    as_of: datetime,
) -> tuple[list[ScheduledSessionVersionV1], list[CalendarEventRecordV1]]:
    """Revise every chain and event at or after ``as_of`` and add new ones."""
    later_rows = list(rows)
    for day, tail in sorted(_tails(rows).items()):
        when = max(as_of, _bounds(tail)[1]) + timedelta(seconds=rng.randrange(3600))
        later_rows.append(
            schedule_row(day, rng.choice(STATES), available_at=when, predecessor=tail)
        )
    for day in dates_between(date(2025, 3, 1), date(2025, 3, 31)):
        later_rows.append(schedule_row(day, rng.choice(STATES), available_at=as_of))
    later_events = list(events)
    latest: dict[str, CalendarEventRecordV1] = {}
    for record in events:
        if (
            record.event_id not in latest
            or record.revision > latest[record.event_id].revision
        ):
            latest[record.event_id] = record
    for event_id, record in sorted(latest.items()):
        later_events.append(
            event_record(
                event_id,
                record.event_date + timedelta(days=rng.randrange(1, 9)),
                max(as_of, record.published_at + timedelta(seconds=1)),
                revision=record.revision + 1,
            )
        )
    later_events.append(
        event_record(f"surprise-{as_of.isoformat()}", as_of.date(), as_of)
    )
    return later_rows, later_events


def _session(
    rows: list[ScheduledSessionVersionV1],
    events: list[CalendarEventRecordV1],
    day: date,
    as_of: datetime,
) -> CalendarSessionFeaturesV1:
    result = compute(
        rows, (request(day, as_of),), events=events, event_kinds=(FOMC_KIND,)
    )
    (session,) = result.sessions
    return session


def _pending_dates_are_unknown(
    rows: list[ScheduledSessionVersionV1],
    features: CalendarSessionFeaturesV1,
    as_of: datetime,
) -> int:
    """A version pending at the cutoff leaves its date, and what reads it, unknown.

    Returns how many pending dates in the session's month were checked.
    """
    day = features.session_key.local_date
    pending = {
        row.session_key.local_date
        for row in rows
        if _bounds(row)[0] < as_of <= _bounds(row)[1]
    }
    checked = 0
    for pending_day in sorted(pending):
        if (pending_day.year, pending_day.month) != (day.year, day.month):
            continue
        checked += 1
        if pending_day == day:
            assert features.session_status == "unknown", (day, as_of)
        elif pending_day < day:
            assert features.month_ordinal_from_start.status == "indeterminate"
        else:
            assert features.month_ordinal_from_end.status == "indeterminate"
    return checked


@pytest.mark.parametrize("seed", range(5))
def test_truncating_or_revising_after_the_cutoff_never_changes_a_session(
    seed: int,
) -> None:
    """30 random (session, cutoff) pairs over a randomly revised history.

    Half of the cutoffs fall inside the window of a bounded or DATE-precision
    correction, in the month of the session, so pending knowledge is exercised
    on every seed.
    """
    rng = Random(662_000 + seed)
    rows, windows = _revised_history(rng)
    events = _events()
    sessions = dates_between(date(2024, 12, 2), date(2025, 2, 27))
    hidden = pending = 0
    for case in range(6):
        if case % 2:
            pending_day, lower, upper = rng.choice(windows)
            as_of = _instant(rng, lower + timedelta(seconds=1), upper)
            day = rng.choice(
                [
                    item
                    for item in sessions
                    if (item.year, item.month) == (pending_day.year, pending_day.month)
                ]
            )
        else:
            day = rng.choice(sessions)
            as_of = _instant(rng, WINDOW_START, WINDOW_END)
        known = _known_rows(rows, as_of)
        hidden += len(rows) - len(known)
        full = _session(rows, events, day, as_of)
        pending += _pending_dates_are_unknown(rows, full, as_of)
        truncated = _session(known, _known_events(events, as_of), day, as_of)
        later_rows, later_events = _revised_after(rng, rows, events, as_of)
        revised = _session(later_rows, later_events, day, as_of)
        assert truncated == full, (day, as_of)
        assert revised == full, (day, as_of)
        assert revised.features_hash == full.features_hash
    assert hidden > 0, "no case truncated any knowledge"
    assert pending > 0, "no case met a correction pending at its cutoff"


def test_truncating_to_an_empty_history_leaves_only_indeterminate_answers() -> None:
    day = date(2025, 1, 10)
    as_of = SCHEDULE_PUBLISHED
    full = _session(list(JANUARY), _events(), day, as_of)
    assert full.session_status == "unknown"
    assert full.schedule_record_hashes == ()
    assert full.event_record_hashes == ()
    assert full.monthly_expiration_session.status == "indeterminate"


def test_a_batch_answers_each_session_exactly_as_alone() -> None:
    rows, _windows = _revised_history(Random(662))
    events = _events()
    days = (date(2024, 12, 20), date(2024, 12, 31), date(2025, 1, 8), date(2025, 2, 3))
    requests = tuple(request(day, evening_before(day)) for day in days)
    batch = compute(rows, requests, events=events, event_kinds=(FOMC_KIND,))
    alone = tuple(_session(rows, events, day, evening_before(day)) for day in days)
    assert batch.sessions == alone


# --- the late-announced unscheduled closure ------------------------------


def _weekdays(first: date, last: date) -> tuple[date, ...]:
    return tuple(day for day in dates_between(first, last) if day.weekday() < 5)


def test_a_late_closure_changes_later_computations_but_not_earlier_ones() -> None:
    days = _weekdays(date(2024, 12, 2), date(2025, 1, 31))
    requests = tuple(request(day, evening_before(day)) for day in days)
    without = compute(JANUARY, requests)
    with_closure = compute(JANUARY_WITH_MOURNING, requests)
    changed = []
    for plain, closed in zip(without.sessions, with_closure.sessions, strict=True):
        day = plain.session_key.local_date
        if plain.as_of <= MOURNING_ANNOUNCED or day.month == 12:
            # Before the announcement nothing can see it, and no December
            # feature reads 2025-01-09 even after it.
            assert closed == plain, day
        elif day in NYSE_HOLIDAYS:
            # A holiday is no session either way, and its date-level
            # features do not read 2025-01-09.
            assert closed == plain, day
            assert plain.session_status == "closed"
        else:
            assert closed.features_hash != plain.features_hash, day
            changed.append(day)
    # Not vacuous: the 2024-12-31 cutoff already sees the announcement.
    assert without.sessions[days.index(date(2024, 12, 31))].as_of > MOURNING_ANNOUNCED
    assert changed == [
        day for day in days if day.year == 2025 and day not in NYSE_HOLIDAYS
    ]
    assert len(changed) == 21
    first = with_closure.sessions[days.index(date(2025, 1, 2))]
    assert (
        first.month_ordinal_from_end.value,
        first.sessions_remaining_in_month.value,
    ) == (20, 19)
    plain_first = without.sessions[days.index(date(2025, 1, 2))]
    assert plain_first.month_ordinal_from_end.value == 21
    closed_day = with_closure.sessions[days.index(MOURNING_DAY)]
    assert closed_day.session_status == "closed"
    assert without.sessions[days.index(MOURNING_DAY)].session_status == "open"


def test_a_late_closure_announced_at_the_cutoff_is_not_yet_known() -> None:
    day = date(2025, 1, 2)
    at = _session(list(JANUARY_WITH_MOURNING), [], day, MOURNING_ANNOUNCED)
    plain = _session(list(JANUARY), [], day, MOURNING_ANNOUNCED)
    assert at == plain
    after = _session(
        list(JANUARY_WITH_MOURNING), [], day, MOURNING_ANNOUNCED + timedelta(seconds=1)
    )
    assert after.month_ordinal_from_end.value == 20


def test_the_closure_correction_is_read_only_after_it_is_known() -> None:
    (correction,) = (
        row for row in JANUARY_WITH_MOURNING if row.revision.source_sequence == 1
    )
    digest = content_hash(correction)
    before = _session(
        list(JANUARY_WITH_MOURNING), [], date(2025, 1, 2), MOURNING_ANNOUNCED
    )
    after = _session(
        list(JANUARY_WITH_MOURNING),
        [],
        date(2025, 1, 3),
        evening_before(date(2025, 1, 3)),
    )
    assert digest not in before.schedule_record_hashes
    assert digest in after.schedule_record_hashes


# --- events -----------------------------------------------------------------


def test_an_event_published_after_the_cutoff_is_invisible() -> None:
    day = date(2025, 1, 24)
    as_of = evening_before(day)
    late = event_record("fomc-2025-01", date(2025, 1, 29), as_of + timedelta(days=1))
    at = event_record("fomc-2025-01", date(2025, 1, 29), as_of)
    for record in (late, at):
        session = _session(list(JANUARY_WITH_MOURNING), [record], day, as_of)
        (item,) = session.events
        assert item.next_event_date.reason == "no_visible_event"
        assert not item.on_session
        assert session.event_record_hashes == ()
    none = _session(list(JANUARY_WITH_MOURNING), [], day, as_of)
    assert none.events == session.events
    assert none.features_hash == session.features_hash


def test_a_revision_published_after_the_cutoff_does_not_move_an_event() -> None:
    day = date(2025, 1, 24)
    as_of = evening_before(day)
    original = event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED)
    moved = event_record(
        "fomc-2025-01", date(2025, 1, 31), as_of + timedelta(hours=1), revision=1
    )
    alone = _session(list(JANUARY_WITH_MOURNING), [original], day, as_of)
    revised = _session(list(JANUARY_WITH_MOURNING), [original, moved], day, as_of)
    assert revised == alone
    assert revised.events[0].next_event_date.value == date(2025, 1, 29)


# --- refusals hold whatever the cutoff -------------------------------------


def test_a_conflicting_row_published_long_after_every_cutoff_is_still_refused() -> None:
    rival = schedule_row(
        date(2025, 1, 10),
        "closed",
        available_at=datetime(2030, 1, 1, tzinfo=UTC),
        logical_salt="far-future-rival",
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(
            [*JANUARY, rival],
            (request(date(2025, 1, 2), evening_before(date(2025, 1, 2))),),
        )
    assert error.value.code == "calendar_schedule_conflicting_rows"


def test_a_duplicate_row_after_the_cutoff_is_still_refused() -> None:
    (original,) = (row for row in JANUARY if row.session_key.local_date == MOURNING_DAY)
    late = schedule_row(
        MOURNING_DAY,
        "closed",
        available_at=datetime(2030, 1, 1, tzinfo=UTC),
        predecessor=original,
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(
            [*JANUARY, late, late],
            (request(date(2025, 1, 2), evening_before(date(2025, 1, 2))),),
        )
    assert error.value.code == "calendar_schedule_duplicate_row"


def test_an_event_revision_published_before_its_predecessor_is_refused() -> None:
    first = event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED)
    earlier = event_record(
        "fomc-2025-01",
        date(2025, 1, 30),
        FOMC_PUBLISHED - timedelta(days=1),
        revision=1,
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(
            JANUARY,
            (request(date(2025, 1, 2), evening_before(date(2025, 1, 2))),),
            events=(first, earlier),
            event_kinds=(FOMC_KIND,),
        )
    assert error.value.code == "calendar_event_chain_invalid"


def test_a_rewound_cutoff_inside_a_batch_is_refused() -> None:
    requests = (
        request(date(2025, 1, 2), evening_before(date(2025, 1, 3))),
        request(date(2025, 1, 3), evening_before(date(2025, 1, 2))),
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(JANUARY, requests)
    assert error.value.code == "calendar_request_cutoff_not_monotone"


def test_naive_datetimes_are_refused_everywhere() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        request(date(2025, 1, 2), datetime(2025, 1, 1, 23))
    with pytest.raises(ValidationError, match="timezone-aware"):
        event_record("fomc", date(2025, 1, 29), datetime(2024, 8, 1, 12))


def test_a_forged_feature_set_is_refused() -> None:
    days = (date(2025, 1, 2), date(2025, 1, 3))
    result = compute(JANUARY, tuple(request(day, evening_before(day)) for day in days))
    swapped = CalendarFeatureSetV1.model_construct(
        **(result.__dict__ | {"sessions": tuple(reversed(result.sessions))})
    )
    with pytest.raises(ValidationError, match="increasing date order"):
        CalendarFeatureSetV1.model_validate(swapped.model_dump())
    stripped = CalendarFeatureSetV1.model_construct(
        **(result.__dict__ | {"sessions": result.sessions[:1]})
    )
    with pytest.raises(ValidationError, match="set hash"):
        CalendarFeatureSetV1.model_validate(stripped.model_dump())


# --- hash stability -------------------------------------------------------


def test_features_are_stable_across_runs_offsets_and_serialization() -> None:
    day = date(2025, 1, 10)
    as_of = evening_before(day)
    first = _session(list(JANUARY_WITH_MOURNING), _events(), day, as_of)
    again = _session(list(reversed(JANUARY_WITH_MOURNING)), _events()[::-1], day, as_of)
    eastern = as_of.astimezone(timezone(timedelta(hours=-5)))
    shifted = _session(list(JANUARY_WITH_MOURNING), _events(), day, eastern)
    assert first == again == shifted
    assert first.features_hash == again.features_hash == shifted.features_hash
    assert (
        CalendarSessionFeaturesV1.model_validate_json(first.model_dump_json()) == first
    )
    moved = _session(
        list(JANUARY_WITH_MOURNING), _events(), day, as_of + timedelta(seconds=1)
    )
    assert moved.features_hash != first.features_hash


def test_the_knowledge_channel_is_bound_into_every_session() -> None:
    result = compute(
        JANUARY, (request(date(2025, 1, 2), evening_before(date(2025, 1, 2))),)
    )
    assert result.knowledge_channel == CHANNEL
    assert result.sessions[0].knowledge_channel == CHANNEL
    assert result.evidence_lane == "exploratory"
    assert result.sessions[0].evidence_lane == "exploratory"
