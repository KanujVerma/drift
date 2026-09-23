"""Reconstructed decision history is what had closed by the cutoff (#66).

The EXPLORATORY reconstructed lane decides at a scheduled close on the
reconstructions the clock has already stepped. The clock orders sessions by
open time first, so on a multi-venue clock a same-date session can open
earlier than an early-closing session and still close after it. Such a
session has not closed at the earlier cutoff and must not be history there.
"""

from datetime import UTC, date, datetime

from drift.domain.evaluator_clock import EvaluationSessionV1, session_order_key
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.engine import reconstructed_history_sessions


def _session(mic: str, day: date, opened: str, closed: str) -> EvaluationSessionV1:
    """An ordering stand-in: only the key and the UTC boundaries are read."""

    def at(clock: str) -> datetime:
        hour, minute = (int(part) for part in clock.split(":"))
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)

    return EvaluationSessionV1.model_construct(
        session_key=SessionKeyV1.model_construct(
            mic=mic, session_scope="regular", local_date=day
        ),
        opened_at=at(opened),
        closed_at=at(closed),
    )


JAN5 = date(2026, 1, 5)
JAN6 = date(2026, 1, 6)


def _clock(*sessions: EvaluationSessionV1) -> tuple[EvaluationSessionV1, ...]:
    return tuple(sorted(sessions, key=session_order_key))


def test_a_later_closing_same_day_session_is_not_history_at_an_early_close() -> None:
    """The reviewer's case: XNAS 13:30-21:00Z sorts before XNYS 14:30-18:00Z."""
    xnas = _session("XNAS", JAN6, "13:30", "21:00")
    xnys = _session("XNYS", JAN6, "14:30", "18:00")
    clock = _clock(xnas, xnys)
    assert clock.index(xnas) < clock.index(xnys)

    history = reconstructed_history_sessions(clock, clock.index(xnys))

    assert xnys.session_key in history
    assert xnas.session_key not in history


def test_every_earlier_session_that_had_closed_is_history() -> None:
    """Earlier days, and a same-day session that closed first, are history."""
    prior = _session("XNYS", JAN5, "14:30", "21:00")
    early = _session("XNYS", JAN6, "14:30", "18:00")
    late = _session("XNAS", JAN6, "14:30", "21:00")
    clock = _clock(prior, early, late)

    at_late = reconstructed_history_sessions(clock, clock.index(late))
    at_early = reconstructed_history_sessions(clock, clock.index(early))

    assert at_late == {prior.session_key, early.session_key, late.session_key}
    assert at_early == {prior.session_key, early.session_key}


def test_a_single_venue_clock_keeps_the_whole_stepped_prefix() -> None:
    """Control: where closes follow opens, nothing changes from the prefix."""
    days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
    clock = _clock(*(_session("XNYS", day, "14:30", "21:00") for day in days))
    for index in range(len(clock)):
        assert reconstructed_history_sessions(clock, index) == {
            item.session_key for item in clock[: index + 1]
        }


def test_a_session_not_yet_stepped_is_never_history() -> None:
    """A later session that closes before the cutoff is still not stepped."""
    long = _session("XNYS", JAN6, "14:30", "21:00")
    short = _session("XNAS", JAN6, "15:00", "18:00")
    clock = _clock(long, short)
    assert clock.index(long) < clock.index(short)

    assert reconstructed_history_sessions(clock, clock.index(long)) == {
        long.session_key
    }
