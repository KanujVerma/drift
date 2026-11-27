"""Historical windows and the isolated ledger path."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from drift.historical.__main__ import refuse_frozen_relabel
from drift.historical.replay import (
    Json,
    Study,
    acknowledge,
    assert_isolated,
    close_time,
    constrained_passive,
    decision_time,
    normalize_proposal_json,
    open_time,
    prepare_review,
    price_value,
    require_settlement,
    research_brief,
    shown_context,
)
from drift.historical.select import Close, Window, select_windows
from drift.historical.sources import (
    PriceBar,
    TextInput,
    alpaca_access_gap,
    parse_yahoo_chart,
)
from drift.manager.models import ExitCondition, InvestmentProposal
from drift.manager.service import ManagerError, PortfolioManager
from drift.prospective.config import START, UNIVERSE

WARMUP = date(2024, 6, 3)
FIRST = date(2024, 6, 4)
SECOND = date(2024, 6, 5)
SETTLE = date(2024, 6, 6)


def test_prospective_calendar_is_unchanged() -> None:
    assert START == date(2026, 11, 27)


def test_alpaca_401_is_a_gap_not_a_price() -> None:
    gap = alpaca_access_gap(401, "sip")
    assert gap is not None
    assert "401" in gap
    assert "SIP" in gap
    assert alpaca_access_gap(200, "iex") is None


def test_earliest_block_wins_over_a_larger_later_move() -> None:
    closes = _series(["100"] * 23 + ["105"] + ["100"] * 11 + ["140"])
    chosen = select_windows(closes)
    assert set(chosen) == {"bullish"}
    window = chosen["bullish"]
    assert window.threshold_index == 0
    assert window.decision_days[0] == closes[12].day
    assert window.total_return < Decimal("0.1")


def test_sideways_and_bearish_rules_are_the_precommitted_ones() -> None:
    flat = select_windows(_series(["100"] * 25))
    assert "sideways" in flat
    assert flat["sideways"].threshold_index == 0
    down = select_windows(_series(["100"] * 23 + ["90", "90"]))
    assert "bearish" in down
    assert down["bearish"].total_return == Decimal("-0.1")


def test_split_date_removes_the_block() -> None:
    closes = _series(["100"] * 23 + ["105"] + ["100"] * 11 + ["110", "110"])
    blocked = closes[12].day
    chosen = select_windows(closes, forbidden=frozenset({blocked}))
    assert "bullish" in chosen
    assert blocked not in chosen["bullish"].decision_days


def test_replay_hides_the_next_close_and_fills_the_next_open(tmp_path: Path) -> None:
    state = tmp_path / "historical"
    study, window = _study()
    prepared = prepare_review(state, study, window, book="memory", model="terra")
    assert prepared["status"] == "proposal_due"
    prompt = (state / "bullish" / "memory" / "terra" / "prompt.txt").read_text()
    assert "allocation_reasoning" in prompt
    assert "symbol is one of AAPL, MSFT, JNJ, SPY, including on a hold." in prompt
    context = json.loads(
        (state / "bullish" / "memory" / "terra" / "context.json").read_text()
    )
    ids = [item["evidence_id"] for item in context["evidence"]]
    assert not any(item.endswith(f":close:{SECOND.isoformat()}") for item in ids)
    assert any(item.endswith(f":close:{FIRST.isoformat()}") for item in ids)
    root = state / "bullish" / "memory" / "terra"
    receipt = json.loads((root / "receipt.json").read_text())
    manager = PortfolioManager.recover(root / "book.sqlite")
    recorded = manager.propose(_buy(receipt, _close_id(ids, "AAPL", FIRST)))
    assert isinstance(recorded, dict)
    assert recorded["status"] == "accepted"
    follow = acknowledge(state, study, window, book="memory", model="terra")
    assert follow["status"] == "proposal_due"
    filled = manager.context(decision_time(SECOND))
    assert isinstance(filled, dict)
    decisions = filled["decisions"]
    assert isinstance(decisions, list)
    first = decisions[0]
    assert isinstance(first, dict)
    fill = first["fill"]
    assert isinstance(fill, dict)
    assert fill["fill_price"] == "101"
    quiet = prepare_review(state, study, window, book="nomemory", model="terra")
    assert quiet["status"] == "proposal_due"
    quiet_root = state / "bullish" / "nomemory" / "terra"
    quiet_receipt = json.loads((quiet_root / "receipt.json").read_text())
    quiet_context = json.loads((quiet_root / "context.json").read_text())
    quiet_ids = [item["evidence_id"] for item in quiet_context["evidence"]]
    quiet_manager = PortfolioManager.recover(quiet_root / "book.sqlite")
    assert quiet_manager.propose(
        _buy(quiet_receipt, _close_id(quiet_ids, "AAPL", FIRST))
    )
    acknowledge(state, study, window, book="nomemory", model="terra")
    omitted = json.loads((quiet_root / "context.json").read_text())
    assert omitted["decisions"] == []
    book = omitted["book"]
    assert isinstance(book, dict)
    holdings = book["holdings"]
    assert isinstance(holdings, list)
    assert holdings


def test_historical_state_cannot_use_the_prospective_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prospective"):
        assert_isolated(tmp_path / "prospective")


def test_constrained_passive_respects_the_position_cap() -> None:
    control = constrained_passive("100", "110")
    assert control["shares"] == "24"
    assert Decimal(control["spent"]) <= Decimal("2500")


def test_research_brief_keeps_stale_statements_out_of_citations() -> None:
    as_of = datetime(2024, 6, 4, 22, 0, tzinfo=UTC)
    text = research_brief(
        {
            "book": {"cash": "10000"},
            "evidence": [
                {
                    "available_at": "2024-06-03T20:00:00+00:00",
                    "evidence_id": "hist:fixture:AAPL:close:2024-06-03",
                    "kind": "observation",
                    "price": "100",
                    "price_role": "close",
                    "summary": "Daily close 100 for AAPL.",
                    "symbol": "AAPL",
                },
                {
                    "available_at": "2024-06-04T20:00:00+00:00",
                    "evidence_id": "hist:fixture:AAPL:close:2024-06-04",
                    "kind": "observation",
                    "price": "101",
                    "price_role": "close",
                    "summary": "Daily close 101 for AAPL.",
                    "symbol": "AAPL",
                },
                {
                    "available_at": "2024-05-01T03:59:00+00:00",
                    "evidence_id": "sec:fact:AAPL:revenue",
                    "kind": "fundamental",
                    "summary": "revenue 1 USD",
                    "symbol": "AAPL",
                },
            ],
        },
        as_of,
    )
    assert "change 1.00 percent" in text
    assert "hist:fixture:AAPL:close:2024-06-04" in text
    assert "background, not citable" in text
    assert "Cash 10000." in text


def test_research_brief_reports_trend_and_earnings() -> None:
    as_of = datetime(2024, 6, 6, 22, 0, tzinfo=UTC)
    closes: list[dict[str, str]] = []
    for index, price in enumerate(("100", "110", "90", "100")):
        day = date(2024, 6, 3 + index)
        closes.append(
            {
                "available_at": datetime(
                    day.year, day.month, day.day, 20, tzinfo=UTC
                ).isoformat(),
                "evidence_id": f"hist:fixture:AAPL:close:{day.isoformat()}",
                "kind": "observation",
                "price": price,
                "price_role": "close",
                "summary": f"Daily close {price} for AAPL. Volume {index + 1}.",
                "symbol": "AAPL",
            }
        )
    text = research_brief(
        cast(
            Json,
            {
                "evidence": [
                    *closes,
                    {
                        "available_at": "2024-01-01T04:59:00+00:00",
                        "evidence_id": "sec:fact:AAPL:eps:2023",
                        "kind": "fundamental",
                        "summary": (
                            "EarningsPerShareDiluted 2 USD period end 2023-09-30 "
                            "form 10-K filed 2024-01-01."
                        ),
                        "symbol": "AAPL",
                    },
                    {
                        "available_at": "2024-03-01T04:59:00+00:00",
                        "evidence_id": "sec:fact:AAPL:old",
                        "kind": "fundamental",
                        "summary": (
                            "Revenues 1 USD period end 2019-09-30 "
                            "form 10-K filed 2024-03-01."
                        ),
                        "symbol": "AAPL",
                    },
                    {
                        "available_at": "2024-02-01T04:59:00+00:00",
                        "evidence_id": "sec:fact:AAPL:eps:2024",
                        "kind": "fundamental",
                        "summary": (
                            "EarningsPerShareDiluted 4 USD period end 2024-09-30 "
                            "form 10-K filed 2024-02-01."
                        ),
                        "symbol": "AAPL",
                    },
                ]
            },
        ),
        as_of,
    )
    assert "last session 11.11 percent" in text
    assert "volatility" in text
    assert "volume 4" in text
    assert "growth 100.00 percent" in text
    assert "price over EPS 25.00" in text
    assert "period end 2024-09-30" in text.split("latest statement", 1)[1]
    assert "background, not citable" in text


def test_price_value_marks_shares_without_calling_them_total_return() -> None:
    study, window = _study()
    value = price_value(
        study,
        window,
        {
            "book": {
                "cash": "8330",
                "holdings": [{"symbol": "AAPL", "quantity": "4"}],
            }
        },
        SECOND,
    )
    assert value["status"] == "priced"
    assert value["net_asset_value"] == "8730"
    assert value["dividends"] == "not_credited"
    assert value["benchmark_interval"] == [FIRST.isoformat(), SECOND.isoformat()]
    assert value["benchmark_change"] == "0.00000000"
    assert str(value["label"]).startswith("price return")


def test_lessons_drop_raw_decisions_and_keep_the_outcome() -> None:
    shown = shown_context(
        {
            "decisions": [
                {
                    "action": "hold",
                    "status": "accepted",
                    "symbol": "SPY",
                    "thesis": "x" * 400,
                    "fill": None,
                }
            ],
            "limitations": ["recorded"],
        },
        "lessons",
    )
    assert isinstance(shown, dict)
    assert shown["decisions"] == []
    lessons = shown["lessons"]
    assert isinstance(lessons, list)
    first = lessons[0]
    assert isinstance(first, dict)
    assert first["outcome"] == "abstained"
    assert len(str(first["thesis"])) == 180


def test_schema_bind_does_not_change_the_trade() -> None:
    bound = json.loads(
        normalize_proposal_json(
            json.dumps(
                {
                    "action": "buy",
                    "evidence_ids": ["hist:a"],
                    "exit_conditions": "sell if it breaks",
                    "quantity": 4,
                    "schema_version": "1.0",
                    "symbol": "AAPL",
                }
            )
        )
    )
    assert bound["schema_version"] == "1"
    assert bound["action"] == "buy"
    assert bound["quantity"] == 4
    assert bound["evidence_ids"] == ["hist:a"]
    assert bound["exit_conditions"] == [
        {"kind": "narrative", "text": "sell if it breaks"}
    ]


def test_citation_label_uses_the_full_336_hour_cutoff() -> None:
    as_of = datetime(2024, 6, 4, 22, 0, tzinfo=UTC)
    exactly = as_of - timedelta(hours=336)
    over = exactly - timedelta(seconds=1)
    text = research_brief(
        {
            "evidence": [
                {
                    "available_at": exactly.isoformat(),
                    "evidence_id": "hist:fixture:AAPL:close:fresh",
                    "kind": "observation",
                    "price": "10",
                    "price_role": "close",
                    "summary": "Daily close 10 for AAPL.",
                    "symbol": "AAPL",
                },
                {
                    "available_at": (as_of - timedelta(hours=1)).isoformat(),
                    "evidence_id": "hist:fixture:JNJ:close:fresh",
                    "kind": "observation",
                    "price": "10",
                    "price_role": "close",
                    "summary": "Daily close 10 for JNJ.",
                    "symbol": "JNJ",
                },
                {
                    "available_at": over.isoformat(),
                    "evidence_id": "sec:filing:late",
                    "kind": "news",
                    "summary": "8-K accession late.",
                    "symbol": "MSFT",
                },
            ]
        },
        as_of,
    )
    assert "hist:fixture:AAPL:close:fresh is 336 hours old, citable." in text
    assert "hist:fixture:JNJ:close:fresh is 1 hour old, citable." in text
    assert "MSFT latest filing is 336 hours old, background, not citable" in text


def test_a_post_decision_fact_waits_for_the_next_open(tmp_path: Path) -> None:
    state = tmp_path / "historical"
    base, window = _study()
    late = datetime(2024, 6, 4, 23, 59, tzinfo=ZoneInfo("America/New_York"))
    study = Study(
        bars=base.bars,
        texts=(
            TextInput(
                evidence_id="sec:fact:AAPL:late",
                symbol="AAPL",
                kind="fundamental",
                observed_at=late,
                summary="EarningsPerShareDiluted 1 USD period end 2024-03-30.",
                source_label="sec-companyfacts",
                limitations=("fixture fact",),
            ),
        ),
        benchmark_levels=base.benchmark_levels,
        benchmark_kind=base.benchmark_kind,
        benchmark_limitation=base.benchmark_limitation,
        price_limitation=base.price_limitation,
    )
    prepare_review(state, study, window, book="nomemory", model="terra")
    root = state / "bullish" / "nomemory" / "terra"
    first = json.loads((root / "context.json").read_text())
    assert "sec:fact:AAPL:late" not in _ids(first)
    receipt = json.loads((root / "receipt.json").read_text())
    manager = PortfolioManager.recover(root / "book.sqlite")
    recorded = manager.propose(_hold(receipt))
    assert isinstance(recorded, dict)
    assert recorded["status"] == "accepted"
    follow = acknowledge(state, study, window, book="nomemory", model="terra")
    assert follow["status"] == "proposal_due"
    second = json.loads((root / "context.json").read_text())
    assert "sec:fact:AAPL:late" in _ids(second)


def _ids(context: object) -> list[str]:
    assert isinstance(context, dict)
    evidence = context["evidence"]
    assert isinstance(evidence, list)
    found: list[str] = []
    for item in evidence:
        assert isinstance(item, dict)
        evidence_id = item["evidence_id"]
        assert isinstance(evidence_id, str)
        found.append(evidence_id)
    return found


def _hold(receipt: dict[str, object]) -> InvestmentProposal:
    proposal_id = receipt["proposal_id"]
    as_of = receipt["as_of"]
    assert isinstance(proposal_id, str)
    assert isinstance(as_of, str)
    return InvestmentProposal(
        proposal_id=UUID(proposal_id),
        as_of=datetime.fromisoformat(as_of),
        action="hold",
        symbol="SPY",
        quantity=0,
        thesis="The cited evidence is not enough for a trade.",
        evidence_ids=(),
        uncertainty="One session does not establish an edge.",
        allocation_reasoning="Cash stays inside the local limits.",
        exit_conditions=(),
        execution="simulation",
        inference="scripted",
    )


def test_session_clock_follows_new_york() -> None:
    winter = date(2022, 1, 4)
    summer = date(2021, 4, 14)
    assert open_time(winter) == datetime(2022, 1, 4, 14, 30, tzinfo=UTC)
    assert close_time(winter) == datetime(2022, 1, 4, 21, 0, tzinfo=UTC)
    assert open_time(summer) == datetime(2021, 4, 14, 13, 30, tzinfo=UTC)
    assert close_time(summer) == datetime(2021, 4, 14, 20, 0, tzinfo=UTC)
    assert decision_time(summer) > close_time(summer)


def test_settlement_refuses_a_trade_that_is_still_pending() -> None:
    require_settlement({"results": [], "status": "idle"})
    with pytest.raises(ManagerError, match="unfinished"):
        require_settlement({"results": [{"status": "pending"}], "status": "pending"})


def test_prepare_refuses_to_relabel_an_existing_book(tmp_path: Path) -> None:
    ledger = tmp_path / "bullish" / "memory" / "terra"
    ledger.mkdir(parents=True)
    (ledger / "book.sqlite").write_bytes(b"")
    with pytest.raises(ValueError, match="cannot be rewritten"):
        refuse_frozen_relabel(tmp_path)


def test_yahoo_parser_uses_the_quote_close() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_718_000_000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.004],
                                "close": [10.006],
                                "volume": [5],
                            }
                        ],
                        "adjclose": [{"adjclose": [9.5]}],
                    },
                }
            ]
        }
    }
    rows = parse_yahoo_chart("AAPL", payload)
    assert rows[0].open_price == "10"
    assert rows[0].close_price == "10.01"
    assert rows[0].source_label == "yahoo-chart-v8"


def _close_id(ids: list[str], symbol: str, day: date) -> str:
    suffix = f"{symbol}:close:{day.isoformat()}"
    return next(item for item in ids if item.endswith(suffix))


def _buy(receipt: dict[str, object], close_id: str) -> InvestmentProposal:
    proposal_id = receipt["proposal_id"]
    as_of = receipt["as_of"]
    assert isinstance(proposal_id, str)
    assert isinstance(as_of, str)
    return InvestmentProposal(
        proposal_id=UUID(proposal_id),
        as_of=datetime.fromisoformat(as_of),
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="The cited close is the only fresh price.",
        evidence_ids=(close_id,),
        uncertainty="One close does not establish an edge.",
        allocation_reasoning="One share stays inside the local cash floor.",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="scripted",
    )


def _series(levels: list[str]) -> tuple[Close, ...]:
    start = date(2021, 1, 4)
    return tuple(
        Close(start + timedelta(days=index), Decimal(level))
        for index, level in enumerate(levels)
    )


def _study() -> tuple[Study, Window]:
    from drift.historical.select import Window

    days = (WARMUP, FIRST, SECOND, SETTLE)
    bars: list[PriceBar] = []
    for day in days:
        for symbol, _cik, _name in UNIVERSE:
            opened = "101" if symbol == "AAPL" and day == SECOND else "100"
            bars.append(
                PriceBar(
                    symbol=symbol,
                    day=day,
                    open_price=opened,
                    close_price="100",
                    volume="10",
                    source_label="yahoo-chart-v8",
                )
            )
    window = Window(
        regime="bullish",
        warmup_day=WARMUP,
        decision_days=(FIRST, SECOND),
        settlement_day=SETTLE,
        threshold_index=0,
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        max_runup=Decimal("0"),
    )
    study = Study(
        bars=tuple(bars),
        texts=(),
        benchmark_levels=tuple((day, "100") for day in days),
        benchmark_kind="price_only_substitute",
        benchmark_limitation="fixture level, not an index",
        price_limitation="fixture price, not an exchange print",
    )
    return study, window
