"""NYSE-backed prospective windows and their immutable state binding."""

from datetime import UTC, date, datetime

from drift.prospective import config


def test_window_starts_at_next_future_exchange_open() -> None:
    assert hasattr(config, "build_window")
    # The early close on November 27 has passed; Friday is not backdated.
    window = config.build_window(
        requested_start=date(2026, 11, 27),
        now=datetime(2026, 11, 27, 20, tzinfo=UTC),
        calendar=config.NYSECalendar(
            years=(2026, 2027),
            holidays=(date(2026, 12, 25), date(2027, 1, 1)),
            early_closes=(date(2026, 11, 27), date(2026, 12, 24)),
        ),
    )
    assert window.observation_dates[0] == date(2026, 11, 30)
    assert len(window.observation_dates) == 20
    assert len(window.settlement_dates) == 5
    assert date(2026, 12, 25) not in window.dates
    assert date(2027, 1, 1) not in window.dates


def test_window_configuration_is_immutable_and_recoverable(
    tmp_path: object, monkeypatch: object
) -> None:
    from pathlib import Path

    import pytest

    from drift.prospective import window

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(
        window, "_fetch_nyse", lambda: (_nyse_html(), received), raising=False
    )
    monkeypatch.setattr(window, "_clock", lambda: received, raising=False)
    configure = getattr(window, "configure_window", lambda *_args, **_kwargs: None)
    created = configure(tmp_path, requested_start=date(2026, 11, 27))
    assert created is not None
    assert created.observation_dates[0] == date(2026, 11, 30)
    assert window.load_window(tmp_path) == created
    assert configure(tmp_path, requested_start=date(2026, 11, 27)) == created
    with pytest.raises(ValueError, match="immutable"):
        configure(tmp_path, requested_start=date(2026, 12, 1))


def _nyse_html() -> bytes:
    rows = [
        ("New Year’s Day", "Thursday, January 1", "Friday, January 1", "—*"),
        (
            "Martin Luther King, Jr. Day",
            "Monday, January 19",
            "Monday, January 18",
            "Monday, January 17",
        ),
        (
            "Washington's Birthday",
            "Monday, February 16",
            "Monday, February 15",
            "Monday, February 21",
        ),
        ("Good Friday", "Friday, April 3", "Friday, March 26", "Friday, April 14"),
        ("Memorial Day", "Monday, May 25", "Monday, May 31", "Monday, May 29"),
        (
            "Juneteenth National Independence Day",
            "Friday, June 19",
            "Friday, June 18",
            "Monday, June 19",
        ),
        ("Independence Day", "Friday, July 3", "Monday, July 5", "Tuesday, July 4"),
        (
            "Labor Day",
            "Monday, September 7",
            "Monday, September 6",
            "Monday, September 4",
        ),
        (
            "Thanksgiving Day",
            "Thursday, November 26",
            "Thursday, November 25",
            "Thursday, November 23",
        ),
        (
            "Christmas Day",
            "Friday, December 25",
            "Friday, December 24",
            "Monday, December 25",
        ),
    ]
    table = "<table><tr><th>Holiday</th><th>2026</th><th>2027</th><th>2028</th></tr>"
    table += "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows
    )
    table += "</table>"
    table += (
        "<p>Each market will close early at 1:00 p.m. on Friday, November 27, 2026, "
        "Friday, November 26, 2027, and Friday, November 24, 2028.</p>"
    )
    table += (
        "<p>Each market will close early at 1:00 p.m. "
        "on Thursday, December 24, 2026.</p>"
    )
    table += "<p>Each market will close early at 1:00 p.m. on Monday, July 3, 2028.</p>"
    return table.encode()


def test_nyse_calendar_extracts_holidays_and_early_closes() -> None:
    from drift.prospective import window

    parser = getattr(window, "parse_nyse_calendar", lambda _: None)
    calendar = parser(_nyse_html())
    assert calendar is not None
    assert not calendar.is_session(date(2026, 12, 25))
    assert calendar.close(date(2026, 12, 24)) == datetime(2026, 12, 24, 18, tzinfo=UTC)
    assert calendar.open(date(2027, 3, 15)) == datetime(2027, 3, 15, 13, 30, tzinfo=UTC)
    assert calendar.is_session(date(2028, 1, 3))


def test_nyse_calendar_refuses_incomplete_or_conflicting_source() -> None:
    import pytest

    from drift.prospective.window import parse_nyse_calendar

    source = _nyse_html()
    with pytest.raises(ValueError, match="incomplete|unrecognized"):
        parse_nyse_calendar(source.replace(b"Thanksgiving Day", b"Unknown holiday"))
    with pytest.raises(ValueError, match="weekday"):
        parse_nyse_calendar(
            source.replace(b"Friday, December 25", b"Monday, December 25")
        )
    with pytest.raises(ValueError, match="early-close"):
        parse_nyse_calendar(
            source.replace(b"Each market will close early", b"No early close")
        )


def test_window_rejects_a_calendar_that_does_not_cover_all_sessions() -> None:
    import pytest

    from drift.prospective.window import NYSECalendar, build_window

    calendar = NYSECalendar(years=(2026,), holidays=(), early_closes=())
    with pytest.raises(ValueError, match="does not cover"):
        build_window(
            requested_start=date(2026, 12, 28),
            now=datetime(2026, 12, 27, tzinfo=UTC),
            calendar=calendar,
        )


def test_state_lock_activates_window_and_restores_legacy_context(
    tmp_path: object, monkeypatch: object
) -> None:
    from pathlib import Path

    import pytest

    from drift.prospective import window
    from drift.prospective.locking import pilot_lock

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    saved = window.configure_window(tmp_path)
    legacy = config.observation_dates()
    with pilot_lock(tmp_path):
        assert config.observation_dates() == saved.observation_dates
        assert config.calendar_dates() == saved.dates
        assert config.session_close_utc(date(2026, 12, 24)) == datetime(
            2026, 12, 24, 18, tzinfo=UTC
        )
    assert config.observation_dates() == legacy


def test_cli_refuses_unconfigured_observation_before_data_collection(
    tmp_path: object, monkeypatch: object
) -> None:
    from argparse import Namespace
    from pathlib import Path

    import pytest

    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(
        "drift.prospective.__main__.collect_live",
        lambda *_args, **_kwargs: pytest.fail("unexpected collection"),
    )
    result = _run(
        Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
    )
    assert result["status"] == "window_not_configured"
    assert not (tmp_path / "observation" / "terra.sqlite").exists()


def test_book_rejects_a_different_configured_window_on_restart(
    tmp_path: object, monkeypatch: object
) -> None:
    from dataclasses import replace
    from pathlib import Path

    import pytest
    from test_prospective_pilot_safety import collection

    from drift.manager.service import PortfolioManager
    from drift.prospective import window
    from drift.prospective.collect import Bar, build_packet
    from drift.prospective.locking import pilot_lock
    from drift.prospective.run import open_books

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    first, second = tmp_path / "first", tmp_path / "second"
    window.configure_window(first, requested_start=date(2026, 11, 27))
    window.configure_window(second, requested_start=date(2026, 12, 1))
    as_of = datetime(2026, 11, 30, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        as_of,
        "alpaca-bars-v2-iex-raw",
        covered_until=as_of,
    )
    with pilot_lock(first):
        packet = build_packet(replace(collection(as_of), bars=(bar,)), readiness=False)
        open_books(first, "observation", packet)
    manager = PortfolioManager.recover(first / "observation" / "terra.sqlite")
    assert isinstance(manager.context(as_of), dict)
    saved = first / "window-saved.json"
    (first / "window.json").rename(saved)
    with pytest.raises(ValueError, match="window do not match"):
        manager.context(as_of)
    saved.rename(first / "window.json")
    (first / "window.json").write_bytes((second / "window.json").read_bytes())
    with pytest.raises(ValueError, match="window do not match"):
        manager.context(as_of)


def test_window_recovery_refuses_modified_source_and_does_not_overwrite(
    tmp_path: object, monkeypatch: object
) -> None:
    import json
    from pathlib import Path

    import pytest

    from drift.prospective import window

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    window.configure_window(tmp_path)
    record_path = tmp_path / "window.json"
    record_before = record_path.read_bytes()
    document = json.loads(record_before)
    source_path = tmp_path / f"nyse-calendar-{document['source_sha256']}.html"
    assert document["pilot_version"] == "0.6"
    source_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        window.load_window(tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        window.configure_window(tmp_path)
    assert record_path.read_bytes() == record_before


def test_unstarted_window_cannot_be_reused_after_its_first_open(
    tmp_path: object, monkeypatch: object
) -> None:
    from pathlib import Path

    import pytest

    from drift.prospective import window

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    window.configure_window(tmp_path)
    monkeypatch.setattr(
        window, "_clock", lambda: datetime(2026, 11, 30, 15, tzinfo=UTC)
    )
    with pytest.raises(ValueError, match="expired"):
        window.configure_window(tmp_path)


def test_status_does_not_report_legacy_dates_as_a_configured_window(
    tmp_path: object,
) -> None:
    from argparse import Namespace
    from pathlib import Path

    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    result = _run(
        Namespace(command="status", role="observation", state=tmp_path, now=None)
    )
    status = result["status"]
    assert isinstance(status, dict)
    assert status["window_configuration"] == "not_configured"
    assert status["observation_dates"] == []


def test_configured_future_window_does_not_collect_before_open(
    tmp_path: object, monkeypatch: object
) -> None:
    from argparse import Namespace
    from pathlib import Path
    from typing import Any

    import pytest

    from drift.prospective import window
    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    now = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: now)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), now))
    window.configure_window(tmp_path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return now

    monkeypatch.setattr("drift.prospective.__main__.datetime", Clock)
    monkeypatch.setattr(
        "drift.prospective.__main__.collect_live",
        lambda *_args, **_kwargs: pytest.fail("unexpected collection"),
    )
    result = _run(
        Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
    )
    assert result["status"] == "not_eligible"
    assert not (tmp_path / "observation" / "terra.sqlite").exists()


def test_missed_first_session_refuses_stale_window_before_collecting(
    tmp_path: object, monkeypatch: object
) -> None:
    from argparse import Namespace
    from pathlib import Path
    from typing import Any

    import pytest

    from drift.prospective import window
    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    window.configure_window(tmp_path)
    now = datetime(2026, 12, 1, 16, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: now)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return now

    monkeypatch.setattr("drift.prospective.__main__.datetime", Clock)
    monkeypatch.setattr(
        "drift.prospective.__main__.collect_live",
        lambda *_args, **_kwargs: pytest.fail("unexpected collection"),
    )
    result = _run(
        Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
    )
    assert result["status"] == "fresh_window_required"


def test_changed_exchange_calendar_is_refused_before_daily_collection(
    tmp_path: object, monkeypatch: object
) -> None:
    from argparse import Namespace
    from pathlib import Path
    from typing import Any

    import pytest

    from drift.prospective import window
    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    window.configure_window(tmp_path)
    now = datetime(2026, 11, 30, 16, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: now)
    changed = _nyse_html().replace(
        b"Thursday, December 24, 2026", b"Wednesday, December 23, 2026"
    )
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (changed, now))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return now

    monkeypatch.setattr("drift.prospective.__main__.datetime", Clock)
    monkeypatch.setattr(
        "drift.prospective.__main__.collect_live",
        lambda *_args, **_kwargs: pytest.fail("unexpected collection"),
    )
    with pytest.raises(ValueError, match="calendar changed"):
        _run(
            Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
        )
    assert not (tmp_path / "observation" / "terra.sqlite").exists()


def test_missing_christmas_early_close_is_not_silently_accepted() -> None:
    import pytest

    from drift.prospective.window import parse_nyse_calendar

    source = _nyse_html().replace(
        b"Friday, December 25</td>", b"Friday, December 25****</td>"
    )
    source = source.replace(
        b"Each market will close early at 1:00 p.m. on Thursday, December 24, 2026.",
        b"Unrecognized notice.",
    )
    with pytest.raises(ValueError, match="early-close"):
        parse_nyse_calendar(source)


def test_calendar_source_outage_is_recorded_without_changing_window(
    tmp_path: object, monkeypatch: object
) -> None:
    import json
    from pathlib import Path

    import pytest

    from drift.prospective import window
    from drift.prospective.locking import pilot_lock

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    window.configure_window(tmp_path)
    before = (tmp_path / "window.json").read_bytes()

    def fail() -> tuple[bytes, datetime]:
        raise OSError("source unavailable")

    monkeypatch.setattr(window, "_fetch_nyse", fail)
    with pilot_lock(tmp_path), pytest.raises(ValueError, match="calendar unavailable"):
        window.verify_current_window(tmp_path)
    records = list((tmp_path / "calendar-checks").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["status"] == "unavailable"
    assert (tmp_path / "window.json").read_bytes() == before


def test_recheck_detects_changed_past_session_when_source_still_covers_it(
    tmp_path: object, monkeypatch: object
) -> None:
    from pathlib import Path

    import pytest

    from drift.prospective import window
    from drift.prospective.locking import pilot_lock

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    window.configure_window(tmp_path)
    later = datetime(2026, 12, 28, 16, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: later)
    changed = _nyse_html().replace(
        b"Thursday, December 24, 2026", b"Wednesday, December 23, 2026"
    )
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (changed, later))
    with pilot_lock(tmp_path), pytest.raises(ValueError, match="calendar changed"):
        window.verify_current_window(tmp_path)


def test_direct_status_recovers_configured_dates_without_caller_scope(
    tmp_path: object, monkeypatch: object
) -> None:
    from pathlib import Path

    import pytest

    from drift.prospective import window
    from drift.prospective.run import status_report

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    configured = window.configure_window(tmp_path)
    result = status_report(tmp_path, "observation", received)
    assert result["observation_dates"] == [
        day.isoformat() for day in configured.observation_dates
    ]


def test_calendar_rejects_unrecognized_holiday_rows_in_source_table() -> None:
    import pytest

    from drift.prospective.window import parse_nyse_calendar

    source = _nyse_html().replace(
        b"</table>",
        b"<tr><td>New closure</td><td>Friday, December 18</td>"
        b"<td>Friday, December 17</td><td>Friday, December 15</td></tr></table>",
    )
    with pytest.raises(ValueError, match="unrecognized"):
        parse_nyse_calendar(source)


def test_unrecognized_emergency_closure_notice_refuses_calendar() -> None:
    import pytest

    from drift.prospective.window import parse_nyse_calendar

    source = _nyse_html() + b"<p>NYSE will be closed Tuesday, December 1, 2026.</p>"
    with pytest.raises(ValueError, match="closure notice"):
        parse_nyse_calendar(source)


def test_submission_refuses_changed_calendar_before_reading_proposals(
    tmp_path: object, monkeypatch: object
) -> None:
    from argparse import Namespace
    from pathlib import Path

    import pytest

    from drift.prospective import window
    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    initial = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: initial)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), initial))
    window.configure_window(tmp_path)
    later = datetime(2026, 11, 30, 16, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: later)
    changed = _nyse_html().replace(
        b"Thursday, December 24, 2026", b"Wednesday, December 23, 2026"
    )
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (changed, later))
    with pytest.raises(ValueError, match="calendar changed"):
        _run(
            Namespace(command="submit", role="observation", state=tmp_path, proposal=[])
        )
