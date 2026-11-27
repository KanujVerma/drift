"""Prospective calendar, source assembly, isolation, and the launch gate."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from drift.manager.models import InvestmentProposal
from drift.manager.service import PortfolioManager
from drift.prospective.collect import (
    Bar,
    Collection,
    Filing,
    UserSuggestion,
    _read_json,
    build_packet,
    load_suggestions,
    new_items,
    sec_filings,
    yahoo_bars,
)
from drift.prospective.config import (
    MODELS,
    eligibility_message,
    in_settlement_window,
    observation_date,
    observation_dates,
)
from drift.prospective.run import apply_proposal, perform_daily, unseen_significant

NY = ZoneInfo("America/New_York")
WHEN = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)


def _collection() -> Collection:
    return Collection(
        collected_at=WHEN,
        bars=(
            Bar(
                symbol="AAPL",
                observed_at=WHEN - timedelta(days=1),
                open_price="270.1",
                close_price="271.15",
                fetched_at=WHEN,
            ),
        ),
        filings=(),
        facts=(),
        headlines=(),
        benchmark_level="12880.12",
        benchmark_kind="sp500_total_return",
        benchmark_limitation="fixture total-return level, not an official calculation",
        benchmark_fetched_at=WHEN,
        corporate_actions_received_at=WHEN,
        gaps=(
            "X posts are not collected; no authorized X API credential is configured",
        ),
        sources=("fixture",),
    )


def test_observation_window_skips_the_holiday_and_waits_for_the_open() -> None:
    dates = observation_dates()
    assert len(dates) == 20
    assert dates[0] == date(2026, 11, 27)
    assert date(2026, 11, 26) not in dates
    assert date(2026, 12, 25) not in dates
    assert date(2026, 12, 24) in dates
    closed = datetime(2026, 11, 26, 19, 0, tzinfo=NY)
    assert observation_date(closed) is None
    message = eligibility_message(closed)
    assert message is not None
    assert "2026-11-27 09:30" in message
    assert "early close" in message
    assert observation_date(datetime(2026, 11, 27, 10, 0, tzinfo=NY)) == date(
        2026, 11, 27
    )
    after_window = datetime(2026, 11, 27, 20, 0, tzinfo=NY)
    assert observation_date(after_window) is None


def test_yahoo_and_sec_parsers_drop_missing_rows() -> None:
    bars = yahoo_bars(
        "AAPL",
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [1_763_000_000, 1_763_086_400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.126, None],
                                    "close": [101.2, None],
                                }
                            ]
                        },
                    }
                ]
            }
        },
    )
    assert len(bars) == 1
    assert bars[0].close_price == "101.2"
    assert bars[0].open_price == "100.13"
    assert yahoo_bars("AAPL", {"chart": {"result": None}}) == ()
    filings = sec_filings(
        "AAPL",
        {
            "filings": {
                "recent": {
                    "form": ["8-K", "4"],
                    "accessionNumber": ["0001-1", "0002-2"],
                    "acceptanceDateTime": [
                        "2026-11-25T21:00:00.000Z",
                        "2026-11-25T21:00:00.000Z",
                    ],
                }
            }
        },
    )
    assert len(filings) == 1
    assert filings[0].form == "8-K"


def test_packet_labels_total_return_and_records_the_x_gap() -> None:
    packet = build_packet(_collection(), readiness=True)
    assert packet.benchmark[0].series_kind == "sp500_total_return"
    assert packet.evidence[0].price_role == "close"
    assert any("not an observation session" in item for item in packet.limitations)
    assert not any(item.price_role == "trade" for item in packet.evidence)


def test_significant_filings_are_reported_once(tmp_path: Path) -> None:
    filing = Filing(
        symbol="AAPL",
        form="8-K",
        accession="0001-26-000001",
        filed=WHEN,
    )
    once = replace(_collection(), filings=(filing,))
    first = unseen_significant(tmp_path, once)
    assert first == [{"accession": "0001-26-000001", "form": "8-K", "symbol": "AAPL"}]
    assert unseen_significant(tmp_path, once) == []


def test_closed_market_does_not_open_observation_books(tmp_path: Path) -> None:
    moment = datetime(2026, 11, 26, 19, 0, tzinfo=NY)
    result = perform_daily(tmp_path, "observation", moment, _collection())
    assert result["status"] == "not_eligible"
    assert list(tmp_path.rglob("*.sqlite")) == []


def test_models_do_not_see_each_others_decisions(tmp_path: Path) -> None:
    result = perform_daily(tmp_path, "readiness", WHEN, _collection())
    assert result["status"] == "ready"
    assert result["counts_toward_observation"] is False
    receipt = json.loads(
        (tmp_path / "readiness" / "terra" / "receipt.json").read_text(encoding="utf-8")
    )
    proposal_path = tmp_path / "terra.json"
    proposal_path.write_text(
        InvestmentProposal(
            proposal_id=UUID(str(receipt["proposal_id"])),
            as_of=WHEN,
            action="hold",
            symbol="AAPL",
            quantity=0,
            thesis="The drill does not support a trade.",
            evidence_ids=(),
            uncertainty="No citation is invented.",
            allocation_reasoning="No simulated shares.",
            exit_conditions=(),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS["terra"],
        ).model_dump_json(),
        encoding="utf-8",
    )
    recorded = apply_proposal(tmp_path, "readiness", "terra", proposal_path)
    assert isinstance(recorded, dict)
    assert recorded["status"] == "accepted"
    sol = PortfolioManager.recover(tmp_path / "readiness" / "sol.sqlite")
    sol_context = sol.context(WHEN)
    assert isinstance(sol_context, dict)
    assert sol_context["decisions"] == []
    terra = PortfolioManager.recover(tmp_path / "readiness" / "terra.sqlite")
    again = terra.context(WHEN)
    assert isinstance(again, dict)
    decisions = again["decisions"]
    assert isinstance(decisions, list)
    assert len(decisions) == 1
    report = terra.report(WHEN)
    assert isinstance(report, dict)
    costs = report["system_costs"]
    assert isinstance(costs, dict)
    assert costs["status"] == "unknown"


def test_intraday_collection_does_not_admit_a_close() -> None:
    collected = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    bar_time = datetime(2026, 11, 27, 14, 30, tzinfo=UTC)
    collection = replace(
        _collection(),
        collected_at=collected,
        benchmark_fetched_at=collected,
        bars=(Bar("AAPL", bar_time, "100", "101"),),
    )
    assert not any(item.price is not None for item in new_items(set(), collection))


def test_settlement_tail_blocks_unverified_fills_and_new_decisions(
    tmp_path: Path,
) -> None:
    moment = datetime(2026, 12, 28, 16, 0, tzinfo=UTC)
    assert in_settlement_window(moment) is True
    assert observation_date(moment) is None
    collection = replace(_collection(), collected_at=moment)
    with pytest.raises(ValueError, match="before collecting"):
        perform_daily(tmp_path, "observation", moment, collection, {"terra": tmp_path})


def test_second_daily_records_receipt_and_rejects_late_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    bar = Bar("AAPL", datetime(2026, 11, 27, 14, 30, tzinfo=UTC), "100", "101", first)
    initial = replace(_collection(), collected_at=first, bars=(bar,))
    assert (
        perform_daily(tmp_path, "observation", first, initial)["status"] == "processed"
    )
    receipt_path = tmp_path / "observation" / "terra" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    proposal = tmp_path / "terra.json"
    proposal.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "action": "hold",
                "symbol": "AAPL",
                "quantity": 0,
                "thesis": "No trade.",
                "evidence_ids": [],
                "uncertainty": "Not enough.",
                "allocation_reasoning": "Stay in cash.",
                "exit_conditions": [],
                "execution": "simulation",
                "inference": "native_supervised",
                "model_identity": receipt["model_identity"],
                "proposal_id": receipt["proposal_id"],
                "as_of": receipt["as_of"],
            }
        ),
        encoding="utf-8",
    )
    second = first + timedelta(minutes=5)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return second

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    applied = apply_proposal(tmp_path, "observation", "terra", proposal)
    assert isinstance(applied, dict) and applied["status"] == "accepted"
    perform_daily(
        tmp_path, "observation", second, replace(initial, collected_at=second)
    )
    renewed = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert renewed == receipt

    late_root = tmp_path / "late"
    assert (
        perform_daily(late_root, "observation", first, initial)["status"] == "processed"
    )
    late_receipt = json.loads(
        (late_root / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    late_proposal = late_root / "terra.json"
    late_proposal.write_text(
        proposal.read_text(encoding="utf-8").replace(
            receipt["proposal_id"], late_receipt["proposal_id"]
        ),
        encoding="utf-8",
    )
    monday = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)

    class LateClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return monday

    monkeypatch.setattr("drift.prospective.run.datetime", LateClock)
    with pytest.raises(ValueError, match="outside the review session"):
        apply_proposal(late_root, "observation", "terra", late_proposal)


def test_default_collect_does_not_pin_the_command_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, datetime | None] = {}

    def fake_collect(pinned: datetime | None = None) -> Collection:
        seen["pinned"] = pinned
        return _collection()

    monkeypatch.setattr("drift.prospective.__main__.collect_live", fake_collect)
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    _run(Namespace(command="collect", now=None, state=tmp_path))
    assert seen["pinned"] is None


def test_response_clock_is_taken_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = datetime(2026, 11, 27, 17, 59, 59, tzinfo=UTC)
    after = datetime(2026, 11, 27, 18, 0, 1, tzinfo=UTC)
    current = {"value": before}

    class Clock:
        @staticmethod
        def now(tz: object = None) -> datetime:
            del tz
            return current["value"]

    def fake_fetch(_url: str, *, timeout: float = 30) -> bytes:
        del timeout
        return b'{"ok": true}'

    original_loads = json.loads

    def slow_loads(payload: str | bytes) -> Any:
        current["value"] = after
        return original_loads(payload)

    monkeypatch.setattr("drift.prospective.collect.datetime", Clock)
    monkeypatch.setattr("drift.prospective.collect.fetch_bytes", fake_fetch)
    monkeypatch.setattr("drift.prospective.collect.json.loads", slow_loads)
    _payload, error, received = _read_json("https://example.test/chart")
    assert error is None
    assert received == before


def test_user_suggestion_is_recorded_and_cannot_be_a_price(
    tmp_path: Path,
) -> None:
    note = UserSuggestion("AAPL", "Watch the filing.", WHEN - timedelta(hours=1))
    packet = build_packet(
        replace(_collection(), suggestions=(note,)),
        readiness=True,
    )
    suggestions = [item for item in packet.evidence if item.kind == "suggestion"]
    assert len(suggestions) == 1
    assert suggestions[0].price is None
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps(
            [
                {
                    "symbol": "MSFT",
                    "summary": "Consider the cash position.",
                    "observed_at": "2026-11-26T20:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_suggestions(path)
    assert loaded[0].symbol == "MSFT"
    assert loaded[0].observed_at == datetime(2026, 11, 26, 20, 0, tzinfo=UTC)
    earlier = UserSuggestion("AAPL", "Watch the filing.", WHEN - timedelta(hours=2))
    later = UserSuggestion("AAPL", "Watch the filing.", WHEN - timedelta(hours=1))
    repeat = later
    stamped = replace(_collection(), suggestions=(earlier, later, repeat))
    both = build_packet(stamped, readiness=True)
    notes = [item for item in both.evidence if item.kind == "suggestion"]
    assert len(notes) == 2
    assert notes[0].evidence_id != notes[1].evidence_id
    again = new_items({notes[0].evidence_id}, stamped)
    kept = [item.evidence_id for item in again if item.kind == "suggestion"]
    assert kept == [notes[1].evidence_id]


def test_unstamped_bar_does_not_claim_the_close() -> None:
    published = datetime(2026, 11, 27, 18, 0, 5, tzinfo=UTC)
    bar = Bar("AAPL", datetime(2026, 11, 27, 14, 30, tzinfo=UTC), "100", "101")
    collection = replace(
        _collection(),
        collected_at=published,
        benchmark_fetched_at=published,
        bars=(bar,),
    )
    ingested = new_items(set(), collection)
    assert all(item.price_role != "close" for item in ingested)
    assert all(item.evidence_id != "yahoo:AAPL:close:2026-11-27" for item in ingested)


def test_pre_close_fetch_does_not_claim_the_closing_price() -> None:
    fetched = datetime(2026, 11, 27, 17, 59, 55, tzinfo=UTC)
    published = datetime(2026, 11, 27, 18, 0, 5, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
        "100",
        "101",
        fetched_at=fetched,
    )
    collected = replace(
        _collection(),
        collected_at=published,
        benchmark_fetched_at=published,
        bars=(bar,),
    )
    assert all(item.price_role != "close" for item in new_items(set(), collected))
