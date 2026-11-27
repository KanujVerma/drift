"""Historical windows and the isolated ledger path."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from drift.historical.replay import (
    Study,
    acknowledge,
    assert_isolated,
    constrained_passive,
    decision_time,
    prepare_review,
)
from drift.historical.select import Close, Window, select_windows
from drift.historical.sources import PriceBar, alpaca_access_gap, parse_yahoo_chart
from drift.manager.models import ExitCondition, InvestmentProposal
from drift.manager.service import PortfolioManager
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
