"""Prospective market data must retain the downloaded feed and fetch time."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from drift.historical.sources import PriceBar, TimedPriceBar
from drift.prospective.collect import (
    Bar,
    TradeInvalidation,
    build_packet,
    collect_live,
    new_items,
)
from drift.prospective.run import ingest_new, perform_daily
from drift.research.universe import RESEARCH_UNIVERSE


def test_suggestion_receipt_is_the_actual_file_read_time(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.prospective.collect import load_suggestions

    before = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    received = before + timedelta(minutes=2)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return received

    path = Path(str(tmp_path)) / "suggestions.json"
    path.write_text(
        '[{"symbol":"AAPL","summary":"note","observed_at":"2026-11-27T15:00:00+00:00"}]'
    )
    monkeypatch.setattr("drift.prospective.collect.datetime", Clock)
    suggestions = load_suggestions(path)
    earlier = replace(collection(before), suggestions=suggestions)
    assert not any(item.kind == "suggestion" for item in new_items(set(), earlier))
    later = replace(
        collection(received + timedelta(minutes=2)), suggestions=suggestions
    )
    item = next(item for item in new_items(set(), later) if item.kind == "suggestion")
    assert item.available_at == received


def test_pilot_bars_refuse_malformed_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import _paged_bars

    now = datetime(2026, 11, 27, 18, 1, tzinfo=UTC)
    payload = {
        "bars": {"AAPL": [{"t": "2026-11-25T05:00:00Z", "o": 100, "c": 101, "v": 10}]},
        "next_page_token": 42,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    rows, error = _paged_bars(
        ("AAPL",), "2026-11-01", "2026-11-27", "iex", capture_receipt=True
    )
    assert error is not None
    assert not rows


def test_bar_query_must_cover_close_even_when_response_arrives_afterward() -> None:
    from dataclasses import replace

    from test_prospective_pilot_safety import collection

    close = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        close.replace(hour=14, minute=30),
        "100",
        "101",
        close + timedelta(seconds=1),
        "alpaca-bars-v2-iex-raw",
        covered_until=close - timedelta(seconds=1),
    )
    result = replace(collection(close + timedelta(seconds=2)), bars=(bar,))
    assert not any(item.price_role == "close" for item in new_items(set(), result))
    result = replace(result, bars=(replace(bar, covered_until=close),))
    assert any(item.price_role == "close" for item in new_items(set(), result))


def test_daily_bar_open_is_not_a_timestamped_execution_trade() -> None:
    from dataclasses import replace

    from test_prospective_pilot_safety import collection

    now = datetime(2026, 11, 27, 18, 1, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        now.replace(hour=14, minute=30),
        "100",
        "101",
        now,
        "alpaca-bars-v2-iex-raw",
        covered_until=now,
    )
    rows = new_items(set(), replace(collection(now), bars=(bar,)))
    assert not any(item.price_role == "trade" for item in rows)


def test_trade_download_retains_actual_print_and_receipt_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.prospective.collect import collect_trades

    boundary = datetime(2026, 11, 27, 14, 30, tzinfo=UTC)
    requested = boundary + timedelta(minutes=1)
    received = requested + timedelta(seconds=2)
    payload = {
        "trades": {
            "AAPL": [
                {
                    "t": "2026-11-27T14:30:00.096124938Z",
                    "p": 100.5,
                    "s": 100,
                    "i": 42,
                    "x": "V",
                    "c": ["@"],
                }
            ]
        },
        "next_page_token": None,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed",
        lambda *_: (payload, 200, received),
    )
    trades, gaps = collect_trades("iex", (("AAPL", boundary),), requested)
    assert not gaps and len(trades) == 1
    assert trades[0].observed_at > boundary
    assert trades[0].received_at == received
    assert "14:30:00.096124938Z" in trades[0].source_id
    assert trades[0].source_label == "alpaca-trades-v2-iex"


def test_historical_price_bar_contract_is_unchanged() -> None:
    from dataclasses import fields

    assert [field.name for field in fields(PriceBar)] == [
        "symbol",
        "day",
        "open_price",
        "close_price",
        "volume",
        "source_label",
    ]


def test_prospective_collection_uses_and_labels_downloaded_alpaca_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    symbols = tuple(item.symbol for item in RESEARCH_UNIVERSE)
    bars = tuple(
        TimedPriceBar(
            symbol,
            date(2026, 11, 25),
            "100",
            "101",
            "1000000",
            "alpaca-bars-v2-iex-raw",
            when,
        )
        for symbol in symbols
    )

    def alpaca(
        requested: tuple[str, ...], start: str, end: str, **_: object
    ) -> tuple[object, ...]:
        assert requested == symbols
        assert start < end
        return (
            "iex",
            bars,
            ("Alpaca bars returned HTTP 403 for feed sip.",),
            "IEX raw",
            frozenset(),
        )

    def no_json(url: str, pinned: datetime | None) -> tuple[object, str, datetime]:
        assert "/chart/" not in url
        return None, "fixture gap", when

    monkeypatch.setattr("drift.historical.sources.load_alpaca_bars", alpaca)
    monkeypatch.setattr("drift.prospective.collect._read_json", no_json)
    monkeypatch.setattr(
        "drift.prospective.collect._benchmark",
        lambda _: (None, "price_only_substitute", "fixture", "fixture gap", when),
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_bytes", lambda *_: (b"", "fixture gap", when)
    )
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    result = collect_live(when)
    assert {bar.symbol for bar in result.bars} == set(symbols)
    packet = build_packet(result, readiness=True)
    prices = [item for item in packet.evidence if item.price is not None]
    assert prices and all(
        item.source_label == "alpaca-bars-v2-iex-raw" for item in prices
    )
    assert all(item.available_at == when for item in prices)
    assert any("403" in gap for gap in result.gaps)


def test_bar_availability_is_its_download_time_not_later_batch_end() -> None:
    from dataclasses import replace

    from test_prospective_pilot_safety import collection

    finished = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    received = finished - timedelta(minutes=5)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        received,
        "alpaca-bars-v2-iex-raw",
        covered_until=received,
    )
    items = new_items(set(), replace(collection(finished), bars=(bar,)))
    prices = [item for item in items if item.price is not None]
    assert prices and all(item.available_at == received for item in prices)
    future = replace(bar, fetched_at=finished + timedelta(minutes=1))
    items = new_items(set(), replace(collection(finished), bars=(future,)))
    assert not any(item.price is not None for item in items)


def test_preclose_alpaca_response_does_not_become_a_final_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import _paged_bars

    received = datetime(2026, 11, 27, 17, 59, 59, tzinfo=UTC)
    finished = datetime(2026, 11, 27, 18, 0, 1, tzinfo=UTC)
    payload = {
        "bars": {
            "AAPL": [{"t": "2026-11-27T05:00:00Z", "o": 100, "c": 101, "v": 1000}]
        },
        "next_page_token": None,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed",
        lambda *_: (payload, 200, received),
        raising=False,
    )
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json",
        lambda *_: pytest.fail("bar download must preserve response time"),
    )
    bars, error = _paged_bars(
        ("AAPL",), "2026-11-27", "2026-11-28", "iex", capture_receipt=True
    )
    assert error is None and len(bars) == 1
    assert isinstance(bars[0], TimedPriceBar)
    assert bars[0].received_at == received

    monkeypatch.setattr(
        "drift.historical.sources.load_alpaca_bars",
        lambda *_, **__: ("iex", bars, (), "", frozenset()),
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_json",
        lambda *_: (None, "fixture gap", finished),
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_bytes",
        lambda *_: (b"", "fixture gap", finished),
    )
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    monkeypatch.setattr(
        "drift.prospective.collect._benchmark",
        lambda _: (None, "price_only_substitute", "fixture", None, finished),
    )
    result = collect_live(finished)
    prices = [
        item
        for item in new_items(set(), result)
        if item.symbol == "AAPL" and item.price
    ]
    assert not prices
    assert all(item.available_at == received for item in prices)


def test_split_records_are_kept_as_timestamped_symbol_specific_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import import_module

    sources = import_module("drift.historical.sources")
    assert hasattr(sources, "CorporateSplit")
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    split = sources.CorporateSplit(
        "AAPL", date(2026, 11, 25), "split-1", "forward_split", when
    )
    bar = TimedPriceBar(
        "AAPL",
        date(2026, 11, 25),
        "50",
        "51",
        "1000",
        "alpaca-bars-v2-iex-raw",
        when,
        (split,),
    )
    monkeypatch.setattr(
        "drift.historical.sources.load_alpaca_bars",
        lambda *_, **__: ("iex", (bar,), (), "", frozenset({split.ex_date})),
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_json", lambda *_: (None, "fixture gap", when)
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_bytes", lambda *_: (b"", "fixture gap", when)
    )
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    monkeypatch.setattr(
        "drift.prospective.collect._benchmark",
        lambda _: (None, "price_only_substitute", "fixture", None, when),
    )
    data = collect_live(when)
    items = new_items(set(), data)
    rows = [item for item in items if item.source_label == "alpaca-corporate-action"]
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL" and rows[0].available_at == when
    assert rows[0].evidence_id == "alpaca:split:AAPL:2026-11-25"


def test_alpaca_split_pages_preserve_symbol_and_response_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import load_alpaca_bars

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    calls: list[str | None] = []

    def actions(_path: str, query: dict[str, str]) -> tuple[object, int, datetime]:
        token = query.get("page_token")
        calls.append(token)
        symbol, next_token = ("AAPL", "next") if token is None else ("MSFT", None)
        return (
            {
                "corporate_actions": {
                    "forward_splits": [
                        {
                            "id": f"split-{symbol}",
                            "symbol": symbol,
                            "ex_date": "2026-11-25",
                        }
                    ]
                },
                "next_page_token": next_token,
            },
            200,
            when,
        )

    monkeypatch.setattr(
        "drift.historical.sources.credential_names", lambda: ("key", "secret")
    )
    monkeypatch.setattr("drift.historical.sources._alpaca_status", lambda _: 200)
    monkeypatch.setattr(
        "drift.historical.sources._paged_bars",
        lambda symbols, *_, **__: (
            tuple(
                TimedPriceBar(
                    s,
                    date(2026, 11, 25),
                    "50",
                    "51",
                    "1000",
                    "alpaca-bars-v2-iex-raw",
                    when,
                )
                for s in symbols
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "drift.historical.sources._adjustment_changes", lambda *_: False
    )
    monkeypatch.setattr("drift.historical.sources._alpaca_json_timed", actions)
    feed, bars, gaps, _note, dates = load_alpaca_bars(
        ("AAPL", "MSFT"),
        "2026-11-01",
        "2026-11-27",
        preferred_feed="iex",
        capture_receipt=True,
    )
    assert feed == "iex" and not gaps and dates == frozenset({date(2026, 11, 25)})
    assert calls == [None, "next"]
    assert all(isinstance(bar, TimedPriceBar) for bar in bars)
    assert {
        bar.symbol: bar.splits[0].received_at
        for bar in bars
        if isinstance(bar, TimedPriceBar)
    } == {
        "AAPL": when,
        "MSFT": when,
    }


def test_incomplete_corporate_actions_record_gap_without_decisions(
    tmp_path: object,
) -> None:
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    perform_daily(tmp_path, "observation", when, collection(when))
    paths = [tmp_path / "observation" / f"{name}.sqlite" for name in ("terra", "sol")]
    later = when + timedelta(minutes=1)
    incomplete = replace(collection(later), corporate_actions_complete=False)
    result = perform_daily(tmp_path, "observation", later, incomplete)
    assert result["status"] == "corporate_actions_unavailable"
    from drift.ledger.sqlite import SQLiteLedger
    from drift.manager.book import thaw

    for path in paths:
        events = SQLiteLedger.open_existing(path).verified_events()
        assert events[-1].event_type == "manager.prospective_corporate_action_status"
        assert thaw(events[-1].payload)["status"] == "unavailable"
        assert not any(event.event_type == "manager.decision" for event in events)


def test_existing_iex_book_requests_only_iex_even_if_sip_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import load_alpaca_bars

    seen: list[str] = []
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "drift.historical.sources.credential_names", lambda: ("key", "secret")
    )
    monkeypatch.setattr("drift.historical.sources._alpaca_status", lambda _: 200)

    def pages(
        symbols: tuple[str, ...], start: str, end: str, feed: str
    ) -> tuple[tuple[PriceBar, ...], None]:
        del start, end
        seen.append(feed)
        return tuple(
            TimedPriceBar(
                symbol,
                when.date(),
                "100",
                "101",
                "1000",
                f"alpaca-bars-v2-{feed}-raw",
                when,
            )
            for symbol in symbols
        ), None

    monkeypatch.setattr("drift.historical.sources._paged_bars", pages)
    monkeypatch.setattr(
        "drift.historical.sources._adjustment_changes", lambda *_: False
    )
    monkeypatch.setattr(
        "drift.historical.sources._corporate_actions",
        lambda *_: (frozenset(), 0, None),
    )
    feed, bars, _gaps, _note, _splits = load_alpaca_bars(
        ("AAPL",), "2026-11-01", "2026-11-27", preferred_feed="iex"
    )
    assert feed == "iex" and bars and seen == ["iex"]
    seen.clear()

    def unavailable(
        _symbols: tuple[str, ...], _start: str, _end: str, feed: str
    ) -> tuple[tuple[PriceBar, ...], str]:
        seen.append(feed)
        return (), "IEX download refused"

    monkeypatch.setattr("drift.historical.sources._paged_bars", unavailable)
    feed, bars, gaps, _note, _splits = load_alpaca_bars(
        ("AAPL",), "2026-11-01", "2026-11-27", preferred_feed="iex"
    )
    assert feed is None and not bars and seen == ["iex"]
    assert "IEX download refused" in gaps


def test_pilot_does_not_run_retroactive_adjustment_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import load_alpaca_bars

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "drift.historical.sources.credential_names", lambda: ("key", "secret")
    )
    monkeypatch.setattr("drift.historical.sources._alpaca_status", lambda _: 200)
    monkeypatch.setattr(
        "drift.historical.sources._paged_bars",
        lambda symbols, *_: (
            tuple(
                TimedPriceBar(
                    s, when.date(), "100", "101", "1000", "alpaca-bars-v2-iex-raw", when
                )
                for s in symbols
            ),
            None,
        ),
    )
    monkeypatch.setattr(
        "drift.historical.sources._corporate_actions", lambda *_: (frozenset(), 0, None)
    )
    monkeypatch.setattr(
        "drift.historical.sources._adjustment_changes",
        lambda *_: pytest.fail("unexpected retrospective probe"),
    )
    feed, bars, *_ = load_alpaca_bars(
        ("AAPL",),
        "2026-11-01",
        "2026-11-27",
        preferred_feed="iex",
        check_adjustments=False,
    )
    assert feed == "iex" and bars


@pytest.mark.parametrize("role", ["observation", "readiness"])
@pytest.mark.parametrize("explicit_clock", [False, True])
def test_daily_uses_feed_persisted_in_existing_books(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, role: str, explicit_clock: bool
) -> None:
    from argparse import Namespace
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.prospective.__main__ import _run
    from drift.prospective.run import open_books

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        when - timedelta(days=2),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    data = replace(collection(when), bars=(bar,))
    open_books(tmp_path, role, build_packet(data, readiness=role == "readiness"))
    calls: list[str | None] = []

    def collect(_: object, *, preferred_feed: str | None = None) -> object:
        calls.append(preferred_feed)
        return data

    monkeypatch.setattr("drift.prospective.__main__.collect_live", collect)
    _run(
        Namespace(
            command="daily",
            role=role,
            state=tmp_path,
            proposal=[],
            suggestions=None,
            now=when.isoformat() if explicit_clock else None,
        )
    )
    assert calls == ["iex"]


def test_changed_price_feed_is_refused_before_either_book_is_updated(
    tmp_path: object,
) -> None:
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        when - timedelta(days=2),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    first = replace(collection(when), bars=(bar,))
    perform_daily(tmp_path, "observation", when, first)
    next_time = when + timedelta(minutes=1)
    changed = replace(
        first,
        collected_at=next_time,
        benchmark_fetched_at=next_time,
        bars=(
            replace(bar, fetched_at=next_time, source_label="alpaca-bars-v2-sip-raw"),
        ),
    )
    with pytest.raises(ValueError, match="price feed"):
        ingest_new(tmp_path, "observation", changed)


def test_date_only_fact_is_not_assigned_a_fabricated_intraday_time() -> None:
    from drift.prospective.collect import _fact_time

    afternoon = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    assert _fact_time("2026-11-27", afternoon) is None
    next_day = datetime(2026, 11, 28, 6, 0, tzinfo=UTC)
    observed = _fact_time("2026-11-27", next_day)
    assert observed is not None and observed > afternoon


def test_submitting_a_saved_decision_does_not_collect_later_market_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from argparse import Namespace
    from pathlib import Path

    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)

    def must_not_collect(_: object) -> None:
        raise AssertionError("submission fetched future observations")

    monkeypatch.setattr("drift.prospective.__main__.collect_live", must_not_collect)
    monkeypatch.setattr(
        "drift.prospective.__main__.apply_proposal",
        lambda _state, _role, name, _path: {"status": "accepted", "name": name},
        raising=False,
    )
    outcome = _run(
        Namespace(
            command="submit",
            role="observation",
            state=tmp_path,
            proposal=["terra=one.json", "sol=two.json"],
        )
    )
    proposals = outcome["proposals"]
    assert isinstance(proposals, dict)
    assert set(proposals) == {"terra", "sol"}
    with pytest.raises(ValueError, match="before collecting"):
        _run(
            Namespace(
                command="daily",
                role="observation",
                state=tmp_path,
                proposal=["terra=one.json"],
            )
        )
    from test_prospective_pilot_safety import collection

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="before collecting"):
        perform_daily(
            tmp_path,
            "observation",
            when,
            collection(when),
            {"terra": tmp_path / "one.json"},
        )


def test_filing_excerpt_keeps_source_metadata_and_collection_time() -> None:
    from dataclasses import replace

    from test_prospective_pilot_safety import collection

    from drift.prospective.collect import sec_filings

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q"],
                "accessionNumber": ["0000320193-26-000001"],
                "acceptanceDateTime": ["2026-11-25T21:00:00Z"],
                "primaryDocument": ["report.htm"],
                "reportDate": ["2026-09-30"],
            }
        }
    }
    filing = sec_filings("AAPL", payload)[0]
    assert filing.document_name == "report.htm"
    assert filing.report_date == "2026-09-30"
    filing = replace(filing, excerpt="Revenue grew in the quarter.", fetched_at=when)
    rows = new_items(set(), replace(collection(when), filings=(filing,), bars=()))
    assert len(rows) == 1
    assert rows[0].source_label == "sec-filing-text"
    assert "Revenue grew" in rows[0].summary
    assert "report 2026-09-30" in rows[0].summary
    assert rows[0].available_at == when


def test_companyfacts_keep_distinct_accessions_and_deduplicate_exact_rows() -> None:
    from dataclasses import replace

    from test_prospective_pilot_safety import collection

    from drift.prospective.collect import sec_facts

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    common = {
        "start": "2026-01-01",
        "end": "2026-09-30",
        "filed": "2026-11-01",
        "form": "10-Q",
        "val": 100,
    }
    first = {**common, "accn": "0001-26-000001"}
    second = {**common, "accn": "0001-26-000002"}
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [first, second]}}}}}
    facts = sec_facts("AAPL", payload)
    rows = [
        item
        for item in new_items(set(), replace(collection(when), facts=facts))
        if item.kind == "fundamental"
    ]
    assert len(rows) == 2 and len({item.evidence_id for item in rows}) == 2
    duplicates = replace(collection(when), facts=(facts[0], facts[0]))
    assert (
        len(
            [
                item
                for item in new_items(set(), duplicates)
                if item.kind == "fundamental"
            ]
        )
        == 1
    )


def test_conflicting_companyfacts_are_omitted_and_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    row = {
        "start": "2026-01-01",
        "end": "2026-09-30",
        "filed": "2026-11-01",
        "form": "10-Q",
        "val": 100,
        "accn": "0001-26-000001",
    }
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [row, {**row, "val": 101, "accn": "0001-26-000002"}]
                    }
                }
            }
        }
    }
    monkeypatch.setattr(
        "drift.historical.sources.load_alpaca_bars",
        lambda *_, **__: (None, (), (), "", frozenset()),
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_json", lambda *_: (payload, None, when)
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_bytes", lambda *_: (b"", "gap", when)
    )
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    monkeypatch.setattr(
        "drift.prospective.collect._benchmark",
        lambda _: (None, "price_only_substitute", "fixture", None, when),
    )
    data = collect_live(when)
    assert any("companyfacts conflicting rows omitted" in gap for gap in data.gaps)
    assert not any(item.kind == "fundamental" for item in new_items(set(), data))


def test_pilot_fact_guard_does_not_change_historical_citation_policy() -> None:
    from drift.manager.evidence_validity import CitationRow, citation_refusal

    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    row = CitationRow(
        evidence_id="sec:fact:AAPL:Revenues:2026-09-30:none:2026-11-01:10-Q:USD",
        kind="fundamental",
        source_label="sec-companyfacts",
        summary="Revenues 100 USD period end 2026-09-30",
        limitations=("historical fixture",),
        observed_at=when,
        available_at=when,
        symbol="AAPL",
    )
    assert (
        citation_refusal(row, when, (row,), policy="research", max_age_hours=336)
        is None
    )


def test_observation_state_inside_checkout_is_refused_before_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from argparse import Namespace
    from pathlib import Path

    from drift.prospective.__main__ import _run

    def must_not_collect(_: object) -> None:
        raise AssertionError("collection started before state validation")

    monkeypatch.setattr("drift.prospective.__main__.collect_live", must_not_collect)
    root = Path(__file__).resolve().parents[2]
    args = Namespace(
        command="daily", role="observation", state=root / "pilot-state", proposal=[]
    )
    with pytest.raises(ValueError, match="outside the source tree"):
        _run(args)


def test_relative_state_uses_stable_absolute_context_paths(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace
    from dataclasses import replace
    from pathlib import Path

    from test_prospective_pilot_safety import collection
    from test_prospective_window import _nyse_html

    from drift.prospective import window
    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    received = datetime(2026, 11, 27, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    window.configure_window(tmp_path / "state")
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    monkeypatch.setattr(
        "drift.prospective.__main__.collect_live",
        lambda *_: replace(collection(when), bars=(bar,)),
    )
    _run(
        Namespace(
            command="daily",
            role="observation",
            state=Path("../state"),
            proposal=[],
            suggestions=None,
        )
    )
    context = (tmp_path / "state" / "observation" / "terra" / "context.json").resolve()
    prompt = (context.parent / "prompt.txt").read_text()
    assert f"Context file: {context}" in prompt


def test_daily_does_not_collect_while_a_review_is_unanswered(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace
    from pathlib import Path

    from test_prospective_pilot_safety import collection

    from drift.prospective.__main__ import _run

    assert isinstance(tmp_path, Path)
    when = datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    perform_daily(tmp_path, "observation", when, collection(when))

    def must_not_collect(_: object) -> None:
        raise AssertionError("pending review caused a new data collection")

    monkeypatch.setattr("drift.prospective.__main__.collect_live", must_not_collect)
    result = _run(
        Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
    )
    assert result["status"] == "pending_reviews"
    assert result["models"] == ["terra", "sol"]


def test_pilot_rejects_empty_or_missing_pagination_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import _paged_bars, _pilot_corporate_actions
    from drift.prospective.collect import collect_trades

    now = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    payload: dict[str, object] = {
        "bars": {"AAPL": [{"t": "2026-11-25T05:00:00Z", "o": 100, "c": 101}]},
        "next_page_token": "",
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    assert (
        _paged_bars(("AAPL",), "2026-11-01", "2026-11-27", "iex", capture_receipt=True)[
            1
        ]
        is not None
    )
    payload.clear()
    payload["corporate_actions"] = {}
    assert (
        _pilot_corporate_actions(("AAPL",), "2026-11-01", "2026-11-27")[2] is not None
    )
    payload.clear()
    payload.update(
        {
            "trades": {
                "AAPL": [
                    {
                        "t": "2026-11-27T14:31:00Z",
                        "p": 100,
                        "s": 100,
                        "i": 1,
                        "x": "V",
                        "c": ["@"],
                    }
                ]
            },
            "next_page_token": "",
        }
    )
    trades, gaps = collect_trades(
        "iex", (("AAPL", now.replace(hour=14, minute=30)),), now
    )
    assert not trades and gaps


def test_trade_collection_starts_at_session_and_skips_consumed_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.prospective.collect import collect_trades

    now = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    boundary = now.replace(hour=12)
    calls: list[dict[str, str]] = []

    def fetch(_path: str, query: dict[str, str]) -> tuple[object, int, datetime]:
        calls.append(query)
        return (
            {
                "trades": {
                    "AAPL": [
                        {
                            "t": "2026-11-27T14:30:00.100000Z",
                            "p": 100,
                            "s": 100,
                            "i": 1,
                            "x": "V",
                            "c": ["@"],
                        },
                        {
                            "t": "2026-11-27T14:30:01.100000Z",
                            "p": 101,
                            "s": 100,
                            "i": 2,
                            "x": "V",
                            "c": ["@"],
                        },
                    ]
                },
                "next_page_token": None,
            },
            200,
            now,
        )

    monkeypatch.setattr("drift.historical.sources._alpaca_json_timed", fetch)
    consumed = frozenset({"alpaca-trades-v2-iex:AAPL:2026-11-27T14:30:00.100000Z:V:1"})
    rows, gaps = collect_trades("iex", (("AAPL", boundary),), now, excluded=consumed)
    assert not gaps and len(rows) == 1 and rows[0].price == "101"
    assert datetime.fromisoformat(calls[0]["start"]) >= datetime(
        2026, 11, 27, 14, 29, 59, 999999, tzinfo=UTC
    )


def test_unit_split_uses_its_own_documented_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import _pilot_corporate_actions

    now = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    payload = {
        "corporate_actions": {
            "unit_splits": [
                {
                    "id": "unit-1",
                    "old_symbol": "AAPL",
                    "new_symbol": "AAPL",
                    "effective_date": "2026-11-27",
                }
            ]
        },
        "next_page_token": None,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    dates, _, gap, details = _pilot_corporate_actions(
        ("AAPL",), "2026-11-01", "2026-11-27"
    )
    assert gap is None and date(2026, 11, 27) in dates
    assert len(details) == 1 and details[0].symbol == "AAPL"


def test_trade_identity_preserves_exchange_and_nanoseconds() -> None:
    from drift.prospective.trade_identity import normalize_trade_id

    a = "alpaca-trades-v2-iex:AAPL:2026-11-30T16:01:58.123456789Z:V:7"
    b = "alpaca-trades-v2-iex:AAPL:2026-11-30T16:01:58.123456789+00:00:V:7"
    c = "alpaca-trades-v2-iex:AAPL:2026-11-30T16:01:58.123456788Z:V:7"
    d = "alpaca-trades-v2-iex:AAPL:2026-11-30T16:01:58.123456789Z:Q:7"
    assert normalize_trade_id(a) == normalize_trade_id(b)
    assert normalize_trade_id(a) != normalize_trade_id(c)
    assert normalize_trade_id(a) != normalize_trade_id(d)


def test_trade_collector_skips_canceled_and_incorrect_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.prospective.collect import collect_trades

    start = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    received = start + timedelta(minutes=1)
    rows = [
        {
            "t": (start + timedelta(seconds=i)).isoformat(),
            "p": price,
            "s": 100,
            "i": i,
            "c": ["@"],
            "x": "V",
            "u": update,
        }
        for i, price, update in (
            (1, 140, "canceled"),
            (2, 120, "incorrect"),
            (3, 101, "corrected"),
        )
    ]
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed",
        lambda *_: ({"trades": {"AAPL": rows}, "next_page_token": None}, 200, received),
    )
    notices: list[TradeInvalidation] = []
    trades, gaps = collect_trades(
        "iex", (("AAPL", start),), received, invalidations=notices
    )
    assert not gaps and len(trades) == 1 and trades[0].price == "101"
    assert {notice.status for notice in notices} == {"canceled", "incorrect"}


def test_ticker_changing_reverse_split_suspends_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import _pilot_corporate_actions

    now = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    payload = {
        "corporate_actions": {
            "reverse_splits": [
                {
                    "id": "split-1",
                    "symbol": "AAPL",
                    "new_symbol": "MSFT",
                    "ex_date": "2026-11-27",
                }
            ]
        },
        "next_page_token": None,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    assert (
        _pilot_corporate_actions(("AAPL", "MSFT"), "2026-11-01", "2026-11-27")[2]
        is not None
    )


def test_ambiguous_corporate_action_cannot_report_complete_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import load_alpaca_bars

    now = datetime(2026, 11, 27, 16, tzinfo=UTC)
    monkeypatch.setattr(
        "drift.historical.sources.credential_names", lambda: ("key", "secret")
    )
    monkeypatch.setattr("drift.historical.sources._alpaca_status", lambda _: 200)
    monkeypatch.setattr(
        "drift.historical.sources._paged_bars",
        lambda *_, **__: (
            (
                TimedPriceBar(
                    "AAPL",
                    date(2026, 11, 25),
                    "100",
                    "101",
                    "10",
                    "alpaca-bars-v2-iex-raw",
                    now,
                ),
            ),
            None,
        ),
    )
    payload = {
        "corporate_actions": {
            "reverse_splits": [
                {
                    "id": "split",
                    "symbol": "AAPL",
                    "new_symbol": "MSFT",
                    "ex_date": "2026-11-27",
                }
            ]
        },
        "next_page_token": None,
    }
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    receipts: list[datetime] = []
    _, _, gaps, _, _ = load_alpaca_bars(
        ("AAPL",),
        "2026-11-01",
        "2026-11-27",
        preferred_feed="iex",
        capture_receipt=True,
        corporate_action_receipts=receipts,
    )
    assert gaps and not receipts


@pytest.mark.parametrize(
    "kind, entry, complete",
    [
        (
            "unit_splits",
            {
                "id": "unit",
                "old_symbol": "AAPL",
                "new_symbol": "MSFT",
                "effective_date": "2026-11-27",
            },
            False,
        ),
        (
            "unit_splits",
            {
                "id": "unit",
                "old_symbol": "AAPL",
                "new_symbol": "AAPL",
                "alternate_symbol": "MSFT",
                "effective_date": "2026-11-27",
            },
            False,
        ),
        (
            "reverse_splits",
            {
                "id": "reverse",
                "symbol": "AAPL",
                "new_symbol": "",
                "ex_date": "2026-11-27",
            },
            True,
        ),
    ],
)
def test_split_identity_ambiguity_is_not_complete(
    monkeypatch: pytest.MonkeyPatch, kind: str, entry: dict[str, str], complete: bool
) -> None:
    from drift.historical.sources import _pilot_corporate_actions

    now = datetime(2026, 11, 27, 16, tzinfo=UTC)
    payload = {"corporate_actions": {kind: [entry]}, "next_page_token": None}
    monkeypatch.setattr(
        "drift.historical.sources._alpaca_json_timed", lambda *_: (payload, 200, now)
    )
    result = _pilot_corporate_actions(("AAPL", "MSFT"), "2026-11-01", "2026-11-27")
    assert (result[2] is None) == complete


def test_refresh_cannot_erase_initial_corporate_action_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.historical.sources import CorporateSplit
    from drift.prospective.collect import Trade

    now = datetime(2026, 11, 27, 16, tzinfo=UTC)
    bar = TimedPriceBar(
        "AAPL", date(2026, 11, 25), "100", "101", "10", "alpaca-bars-v2-iex-raw", now
    )
    monkeypatch.setattr(
        "drift.historical.sources.load_alpaca_bars",
        lambda *_, **__: (
            "iex",
            (bar,),
            ("initial ticker-change failure",),
            "",
            frozenset(),
        ),
    )
    trade = Trade(
        "AAPL",
        now - timedelta(seconds=1),
        now,
        "100",
        "alpaca-trades-v2-iex",
        "fixture",
    )
    monkeypatch.setattr(
        "drift.prospective.collect.collect_trades", lambda *_, **__: ((trade,), ())
    )

    def refreshed(
        *_: object, receipts: list[datetime], **__: object
    ) -> tuple[object, ...]:
        receipts.append(now)
        return (
            frozenset({now.date()}),
            0,
            None,
            (CorporateSplit("MSFT", now.date(), "other", "forward_split", now),),
        )

    monkeypatch.setattr("drift.historical.sources._pilot_corporate_actions", refreshed)
    monkeypatch.setattr(
        "drift.prospective.collect._read_json", lambda *_: (None, "fixture", now)
    )
    monkeypatch.setattr(
        "drift.prospective.collect._read_bytes", lambda *_: (b"", "fixture", now)
    )
    monkeypatch.setattr(
        "drift.prospective.collect._benchmark",
        lambda _: (None, "price_only_substitute", "fixture", None, now),
    )
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    result = collect_live(
        now,
        preferred_feed="iex",
        trade_requests=(("AAPL", now - timedelta(minutes=1)),),
    )
    assert result.corporate_actions_complete is False
    assert result.corporate_actions_received_at is None


def test_cent_conversion_ignores_caller_decimal_context() -> None:
    from decimal import Context, localcontext

    from drift.prospective.collect import cents

    with localcontext(Context(prec=1)):
        assert cents("102.225") == "102.23"
