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
    _json_object,
    _ready_at,
    acknowledge,
    assert_isolated,
    close_time,
    constrained_passive,
    decision_time,
    historical_mandate,
    normalize_proposal_json,
    open_time,
    prepare_review,
    price_value,
    require_settlement,
    research_brief,
    shown_context,
    texts_for_window,
)
from drift.historical.select import Close, Window, select_windows
from drift.historical.sources import (
    PriceBar,
    TextInput,
    alpaca_access_gap,
    entitled_feeds,
    filing_excerpt,
    parse_alpaca_bars,
    parse_alpaca_corporate_actions,
    parse_alpaca_news,
    parse_yahoo_chart,
    restamp_companyfact,
)
from drift.manager.decide import citation_time
from drift.manager.evidence_validity import CitationRow, citation_refusal
from drift.manager.models import (
    REQUIRED_CONTEXT_LIMITATIONS,
    REQUIRED_PACKET_LIMITATIONS,
    EvidenceItem,
    ExitCondition,
    InvestmentProposal,
    PortfolioContext,
    ResearchPacket,
    SimulationSession,
)
from drift.manager.service import (
    ManagerError,
    PortfolioManager,
    _next_trade_observation,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.config import (
    EVIDENCE_AGE_HOURS,
    START,
    UNIVERSE,
    instruments,
    mandate,
)

WARMUP = date(2024, 6, 3)
FIRST = date(2024, 6, 4)
SECOND = date(2024, 6, 5)
SETTLE = date(2024, 6, 6)


def test_prospective_calendar_is_unchanged() -> None:
    assert START == date(2026, 11, 27)
    assert mandate().citation_policy == "uniform_age"
    assert mandate().max_evidence_age_hours == EVIDENCE_AGE_HOURS
    assert historical_mandate().citation_policy == "research"
    assert historical_mandate().max_evidence_age_hours == EVIDENCE_AGE_HOURS


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


@pytest.mark.parametrize("name", ["prospective-single-sol", "prospective-pilot"])
def test_historical_state_rejects_named_pilot_directories_and_descendants(
    tmp_path: Path, name: str
) -> None:
    pilot = tmp_path / name
    pilot.mkdir()
    alias = tmp_path / "pilot-alias"
    alias.symlink_to(pilot, target_is_directory=True)
    for state in (pilot, pilot / "historical", alias / "historical"):
        with pytest.raises(ValueError, match="prospective"):
            assert_isolated(state)


def test_historical_state_rejects_custom_pilot_root(tmp_path: Path) -> None:
    pilot = tmp_path / "my-trading-book"
    (pilot / "observation").mkdir(parents=True)
    (pilot / "window.json").write_text("{}")
    with pytest.raises(ValueError, match="prospective"):
        assert_isolated(pilot / "nested")


def test_historical_state_rejects_custom_pilot_without_window_marker(
    tmp_path: Path,
) -> None:
    pilot = tmp_path / "custom-book"
    (pilot / "observation").mkdir(parents=True)
    with pytest.raises(ValueError, match="prospective"):
        assert_isolated(pilot / "observation" / "nested")


def test_constrained_passive_respects_the_position_cap() -> None:
    control = constrained_passive("100", "110")
    assert control["shares"] == "24"
    assert Decimal(control["spent"]) <= Decimal("2500")
    no_room = constrained_passive("0.01", "0.02", cash="100", floor="100")
    assert no_room["shares"] == "0"
    assert Decimal(no_room["ending_nav"]) == Decimal("100")


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
    assert "citable until superseded" in text
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
                            "EarningsPerShareDiluted 2 USD period end 2021-12-31 "
                            "period start 2021-01-01 form 10-K filed 2024-01-01."
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
                        "available_at": "2024-02-15T04:59:00+00:00",
                        "evidence_id": "sec:fact:AAPL:quarter",
                        "kind": "fundamental",
                        "summary": (
                            "Revenues 2 USD period end 2020-03-31 "
                            "period start 2020-01-01 form 10-Q filed 2024-02-15."
                        ),
                        "symbol": "AAPL",
                    },
                    {
                        "available_at": "2024-02-01T04:59:00+00:00",
                        "evidence_id": "sec:fact:AAPL:eps:2024",
                        "kind": "fundamental",
                        "summary": (
                            "EarningsPerShareDiluted 4 USD period end 2022-12-31 "
                            "period start 2022-01-01 form 10-K filed 2024-02-01."
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
    assert "period end 2022-12-31" in text.split("latest statement", 1)[1]
    assert "growth not computed" in text
    assert "citable until superseded" in text


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


def test_a_later_availability_time_does_not_refresh_old_evidence() -> None:
    as_of = datetime(2024, 6, 4, 22, 0, tzinfo=UTC)
    observed = as_of - timedelta(hours=400)
    available = as_of - timedelta(hours=2)
    assert citation_time(observed, available) == observed
    text = research_brief(
        {
            "evidence": [
                {
                    "available_at": available.isoformat(),
                    "observed_at": observed.isoformat(),
                    "evidence_id": "sec:filing:old",
                    "kind": "news",
                    "summary": "8-K accession old.",
                    "symbol": "AAPL",
                }
            ]
        },
        as_of,
    )
    assert "stale, not citable" in text


def test_duplicate_proposal_keys_are_refused() -> None:
    with pytest.raises(ValueError, match="repeats action"):
        _json_object('{"action": "sell", "action": "buy"}')


def test_cached_companyfact_stamp_moves_off_21_00_utc() -> None:
    cached = datetime(2021, 4, 1, 21, 0, tzinfo=UTC)
    moved = restamp_companyfact(cached, "sec-companyfacts")
    assert moved.astimezone(ZoneInfo("America/New_York")).hour == 23
    assert restamp_companyfact(cached, "sec-submissions") == cached


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
    assert (
        "hist:fixture:AAPL:close:fresh is 336 hours old, fresh price, citable." in text
    )
    assert "hist:fixture:JNJ:close:fresh is 1 hour old, fresh price, citable." in text
    assert "MSFT latest filing is 336 hours old, stale, not citable" in text


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
    close_id = next(
        item for item in _ids(first) if item.endswith(f"AAPL:close:{FIRST.isoformat()}")
    )
    manager = PortfolioManager.recover(root / "book.sqlite")
    recorded = manager.propose(_buy(receipt, close_id))
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


def test_alpaca_bar_uses_the_new_york_date_and_raw_cents() -> None:
    payload = {
        "bars": {
            "AAPL": [
                {
                    "t": "2024-11-01T04:00:00Z",
                    "o": 220.965,
                    "c": 222.91,
                    "v": 10,
                }
            ]
        }
    }
    rows = parse_alpaca_bars("AAPL", payload, "sip")
    assert rows[0].day == date(2024, 11, 1)
    assert rows[0].open_price == "220.97"
    assert rows[0].close_price == "222.91"
    assert rows[0].source_label == "alpaca-bars-v2-sip-raw"


def test_alpaca_actions_and_news_keep_their_labels() -> None:
    splits, dividends = parse_alpaca_corporate_actions(
        {
            "corporate_actions": {
                "forward_splits": [{"ex_date": "2020-08-31", "symbol": "AAPL"}],
                "cash_dividends": [{"ex_date": "2020-08-07", "symbol": "AAPL"}],
            }
        }
    )
    assert splits == frozenset({date(2020, 8, 31)})
    assert dividends == 1
    rows = parse_alpaca_news(
        {
            "news": [
                {
                    "id": 7,
                    "headline": "Apple event",
                    "summary": "A product note.",
                    "created_at": "2026-11-26T11:32:14Z",
                    "symbols": ["AAPL", "UNKNOWN"],
                }
            ]
        },
        frozenset({"AAPL", "MSFT"}),
    )
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL"
    assert rows[0].source_label == "alpaca-news"
    assert rows[0].evidence_id == "alpaca:news:7:AAPL"
    revised = parse_alpaca_news(
        {
            "news": [
                {
                    "id": 8,
                    "headline": "Revised",
                    "created_at": "2026-11-26T11:00:00Z",
                    "updated_at": "2026-11-26T15:00:00Z",
                    "symbols": ["AAPL"],
                }
            ]
        },
        frozenset({"AAPL"}),
    )
    assert revised[0].observed_at == datetime(2026, 11, 26, 11, tzinfo=UTC)
    assert revised[0].available_at == datetime(2026, 11, 26, 15, tzinfo=UTC)


def test_filing_excerpt_prefers_the_event_item() -> None:
    body = (
        "<html><body><p>Cover page</p>"
        "<p>Item 2.02 Results of Operations</p></body></html>"
    )
    assert filing_excerpt(body, limit=40).startswith("Item 2.02 Results")


def test_research_policy_distinguishes_evidence_class() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    old = datetime(2024, 1, 2, tzinfo=UTC)
    close = _row("hist:old-close", "observation", "close", old)
    news = _row("alpaca:news:1:AAPL", "news", "alpaca-news", old)
    original = _row(
        "sec:fact:AAPL:Revenues:2023-09-30:2022-10-01:2023-11-03:10-K:USD",
        "fundamental",
        "sec-companyfacts",
        datetime(2023, 11, 3, tzinfo=UTC),
    )
    amended = _row(
        "sec:fact:AAPL:Revenues:2023-09-30:2022-10-01:2024-02-02:10-K/A:USD",
        "fundamental",
        "sec-companyfacts",
        datetime(2024, 2, 2, tzinfo=UTC),
    )
    withdrawn = CitationRow(
        evidence_id="sec:fact:AAPL:Assets:2023-09-30:2023-11-03:10-K:USD",
        kind="fundamental",
        source_label="sec-companyfacts",
        summary="Assets 5 USD period end 2023-09-30.",
        limitations=("withdrawn filing",),
        observed_at=old,
        available_at=old,
        symbol="AAPL",
    )
    filing = CitationRow(
        evidence_id="sec:filing:0001",
        kind="news",
        source_label="sec-submissions",
        summary="10-K accession 0001 report 2023-09-30.",
        limitations=("SEC submissions row",),
        observed_at=datetime(2023, 11, 3, tzinfo=UTC),
        available_at=datetime(2023, 11, 3, tzinfo=UTC),
        symbol="AAPL",
    )
    amendment = CitationRow(
        evidence_id="sec:filing:0002",
        kind="news",
        source_label="sec-filing-text",
        summary="10-K/A accession 0002 report 2023-09-30.",
        limitations=("excerpt is not the full filing",),
        observed_at=datetime(2024, 2, 2, tzinfo=UTC),
        available_at=datetime(2024, 2, 2, tzinfo=UTC),
        symbol="AAPL",
    )
    rows = (close, news, original, amended, withdrawn, filing, amendment)
    assert citation_refusal(close, as_of, rows, policy="uniform_age", max_age_hours=336)
    assert (
        citation_refusal(close, as_of, rows, policy="research", max_age_hours=336)
        is None
    )
    assert citation_refusal(news, as_of, rows, policy="research", max_age_hours=336)
    assert (
        citation_refusal(amended, as_of, rows, policy="research", max_age_hours=336)
        is None
    )
    superseded = citation_refusal(
        original, as_of, rows, policy="research", max_age_hours=336
    )
    assert superseded is not None
    assert superseded.startswith("superseded_evidence")
    withdrawn_reason = citation_refusal(
        withdrawn, as_of, rows, policy="research", max_age_hours=336
    )
    assert withdrawn_reason is not None
    assert withdrawn_reason.startswith("withdrawn_evidence")
    filing_reason = citation_refusal(
        filing, as_of, rows, policy="research", max_age_hours=336
    )
    assert filing_reason is not None
    assert filing_reason.startswith("superseded_evidence")
    assert (
        citation_refusal(amendment, as_of, rows, policy="research", max_age_hours=336)
        is None
    )


def test_another_issuers_amendment_does_not_supersede() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    original = CitationRow(
        evidence_id="sec:filing:aapl",
        kind="news",
        source_label="sec-submissions",
        summary="10-Q accession aapl report 2024-03-30.",
        limitations=("SEC submissions row",),
        observed_at=datetime(2024, 5, 1, tzinfo=UTC),
        available_at=datetime(2024, 5, 1, tzinfo=UTC),
        symbol="AAPL",
    )
    other = CitationRow(
        evidence_id="sec:filing:msft",
        kind="news",
        source_label="sec-filing-text",
        summary="10-Q/A accession msft report 2024-03-30.",
        limitations=("excerpt is not the full filing",),
        observed_at=datetime(2024, 5, 20, tzinfo=UTC),
        available_at=datetime(2024, 5, 20, tzinfo=UTC),
        symbol="MSFT",
    )
    refusal = citation_refusal(
        original, as_of, (original, other), policy="research", max_age_hours=336
    )
    assert refusal is None


def test_two_original_filings_from_one_issuer_both_stay_citable() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    first = CitationRow(
        evidence_id="sec:filing:one",
        kind="news",
        source_label="sec-submissions",
        summary="8-K accession one report 2024-04-17.",
        limitations=("SEC submissions row",),
        observed_at=datetime(2024, 4, 17, 20, tzinfo=UTC),
        available_at=datetime(2024, 4, 17, 20, tzinfo=UTC),
        symbol="MSFT",
    )
    second = CitationRow(
        evidence_id="sec:filing:two",
        kind="news",
        source_label="sec-submissions",
        summary="8-K accession two report 2024-04-17.",
        limitations=("SEC submissions row",),
        observed_at=datetime(2024, 5, 1, 20, tzinfo=UTC),
        available_at=datetime(2024, 5, 1, 20, tzinfo=UTC),
        symbol="MSFT",
    )
    refusal = citation_refusal(
        first, as_of, (first, second), policy="research", max_age_hours=336
    )
    assert refusal is None


def test_a_different_period_start_does_not_replace_the_fact() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    quarter = _row(
        "sec:fact:AAPL:Revenues:2024-03-30:2024-01-01:2024-05-02:10-Q:USD",
        "fundamental",
        "sec-companyfacts",
        datetime(2024, 5, 2, tzinfo=UTC),
    )
    year = _row(
        "sec:fact:AAPL:Revenues:2024-03-30:2023-04-01:2024-05-03:10-Q:USD",
        "fundamental",
        "sec-companyfacts",
        datetime(2024, 5, 3, tzinfo=UTC),
    )
    refusal = citation_refusal(
        quarter, as_of, (quarter, year), policy="research", max_age_hours=336
    )
    assert refusal is None


def test_headlines_do_not_crowd_out_a_current_filing() -> None:
    window = Window(
        regime="between",
        warmup_day=date(2024, 6, 3),
        decision_days=(date(2024, 6, 4),),
        settlement_day=date(2024, 6, 5),
        threshold_index=0,
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        max_runup=Decimal("0"),
    )
    filing = TextInput(
        evidence_id="sec:filing:current",
        symbol="AAPL",
        kind="news",
        observed_at=datetime(2024, 5, 1, tzinfo=UTC),
        summary="10-Q accession current report 2024-03-30.",
        source_label="sec-submissions",
        limitations=("SEC submissions row",),
    )
    headlines = tuple(
        TextInput(
            evidence_id=f"alpaca:news:{index}:AAPL",
            symbol="AAPL",
            kind="news",
            observed_at=datetime(2024, 5, 20 + index, tzinfo=UTC),
            summary=f"headline {index}",
            source_label="alpaca-news",
            limitations=("headline",),
        )
        for index in range(3)
    )
    kept = texts_for_window((filing, *headlines), window)
    assert any(item.evidence_id == "sec:filing:current" for item in kept)


def test_a_failed_sip_download_still_leaves_iex_entitled() -> None:
    assert entitled_feeds({"sip": 200, "iex": 200}) == ("sip", "iex")
    assert entitled_feeds({"sip": 401, "iex": 200}) == ("iex",)


def test_uniform_age_still_rejects_a_fresh_withdrawn_filing() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    row = CitationRow(
        evidence_id="sec:filing:withdrawn",
        kind="news",
        source_label="sec-submissions",
        summary="Withdrawn filing accession x report 2024-06-04.",
        limitations=("withdrawn filing",),
        observed_at=datetime(2024, 6, 4, 21, tzinfo=UTC),
        available_at=datetime(2024, 6, 4, 21, tzinfo=UTC),
        symbol="AAPL",
    )
    refusal = citation_refusal(
        row, as_of, (row,), policy="uniform_age", max_age_hours=336
    )
    assert refusal is not None
    assert refusal.startswith("withdrawn_evidence")


def test_one_amendment_does_not_retire_two_originals() -> None:
    as_of = datetime(2024, 6, 4, 22, tzinfo=UTC)
    first = _filing("one", datetime(2024, 4, 17, 20, tzinfo=UTC), "8-K")
    second = _filing("two", datetime(2024, 4, 18, 20, tzinfo=UTC), "8-K")
    amendment = _filing("amend", datetime(2024, 5, 1, 20, tzinfo=UTC), "8-K/A")
    rows = (first, second, amendment)
    assert (
        citation_refusal(first, as_of, rows, policy="research", max_age_hours=336)
        is None
    )
    assert (
        citation_refusal(second, as_of, rows, policy="research", max_age_hours=336)
        is None
    )


def test_a_legacy_fact_id_still_matches_its_period() -> None:
    as_of = datetime(2019, 11, 1, 22, tzinfo=UTC)
    legacy = CitationRow(
        evidence_id=("sec:fact:AAPL:Revenues:2017-12-30:2019-01-30:10-Q:USD"),
        kind="fundamental",
        source_label="sec-companyfacts",
        summary=(
            "Revenues 1 USD period end 2017-12-30 period start 2017-10-01 "
            "form 10-Q filed 2019-01-30."
        ),
        limitations=("fixture",),
        observed_at=datetime(2019, 1, 30, 23, 59, tzinfo=UTC),
        available_at=datetime(2019, 1, 30, 23, 59, tzinfo=UTC),
        symbol="AAPL",
    )
    same = CitationRow(
        evidence_id=(
            "sec:fact:AAPL:Revenues:2017-12-30:2017-10-01:2019-10-31:10-K:USD"
        ),
        kind="fundamental",
        source_label="sec-companyfacts",
        summary=(
            "Revenues 2 USD period end 2017-12-30 period start 2017-10-01 "
            "form 10-K filed 2019-10-31."
        ),
        limitations=("fixture",),
        observed_at=datetime(2019, 10, 31, 23, 59, tzinfo=UTC),
        available_at=datetime(2019, 10, 31, 23, 59, tzinfo=UTC),
        symbol="AAPL",
    )
    other_period = CitationRow(
        evidence_id=(
            "sec:fact:AAPL:Revenues:2017-12-30:2017-07-01:2019-10-31:10-K:USD"
        ),
        kind="fundamental",
        source_label="sec-companyfacts",
        summary=(
            "Revenues 9 USD period end 2017-12-30 period start 2017-07-01 "
            "form 10-K filed 2019-10-31."
        ),
        limitations=("fixture",),
        observed_at=datetime(2019, 10, 31, 23, 59, tzinfo=UTC),
        available_at=datetime(2019, 10, 31, 23, 59, tzinfo=UTC),
        symbol="AAPL",
    )
    replaced = citation_refusal(
        legacy, as_of, (legacy, same), policy="research", max_age_hours=336
    )
    assert replaced is not None
    assert replaced.startswith("superseded_evidence")
    kept = citation_refusal(
        legacy,
        as_of,
        (legacy, other_period),
        policy="research",
        max_age_hours=336,
    )
    assert kept is None


def test_a_weekend_revision_is_ready_at_the_next_open() -> None:
    window = Window(
        regime="bullish",
        warmup_day=date(2024, 6, 6),
        decision_days=(date(2024, 6, 7), date(2024, 6, 10)),
        settlement_day=date(2024, 6, 11),
        threshold_index=0,
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        max_runup=Decimal("0"),
    )
    item = TextInput(
        evidence_id="alpaca:news:weekend:AAPL",
        symbol="AAPL",
        kind="news",
        observed_at=datetime(2024, 6, 7, 15, tzinfo=UTC),
        available_at=datetime(2024, 6, 9, 16, tzinfo=UTC),
        summary="Revised headline.",
        source_label="alpaca-news",
        limitations=("headline",),
    )
    assert _ready_at(item, window) == open_time(date(2024, 6, 10))


def _filing(name: str, stamp: datetime, form: str) -> CitationRow:
    return CitationRow(
        evidence_id=f"sec:filing:{name}",
        kind="news",
        source_label="sec-submissions",
        summary=f"{form} accession {name} report 2024-04-17.",
        limitations=("SEC submissions row",),
        observed_at=stamp,
        available_at=stamp,
        symbol="MSFT",
    )


def test_research_policy_does_not_freshen_an_old_fill() -> None:
    decision_at = datetime(2024, 1, 2, 22, tzinfo=UTC)
    trade_at = datetime(2024, 1, 3, 14, 30, tzinfo=UTC)
    as_of = datetime(2024, 6, 5, 14, 30, tzinfo=UTC)
    item = EvidenceItem.model_validate(
        {
            "evidence_id": "hist:fixture:AAPL:open:2024-01-03",
            "kind": "observation",
            "symbol": "AAPL",
            "observed_at": trade_at,
            "available_at": trade_at,
            "limitations": ("fixture price",),
            "summary": "Daily open 100 for AAPL.",
            "source_label": "fixture",
            "price": "100",
            "price_role": "trade",
        }
    )
    opened = datetime(2024, 6, 4, 13, 30, tzinfo=UTC)
    packet = ResearchPacket(
        instruments=instruments(),
        sessions=(
            _session(date(2024, 6, 4), opened),
            _session(date(2024, 6, 5), datetime(2024, 6, 5, 13, 30, tzinfo=UTC)),
        ),
        evidence=(item,),
        portfolio_context=PortfolioContext(
            as_of=opened,
            cash="10000",
            positions=(),
            limitations=REQUIRED_CONTEXT_LIMITATIONS,
        ),
        limitations=REQUIRED_PACKET_LIMITATIONS,
    )
    found = _next_trade_observation(
        packet,
        historical_mandate(),
        symbol="AAPL",
        decision_at=decision_at,
        as_of=as_of,
        used=set(),
    )
    assert found is not None
    _chosen, refusal = found
    assert refusal is not None
    assert refusal.startswith("stale_evidence")


def test_historical_book_rejects_superseded_and_accepts_history(
    tmp_path: Path,
) -> None:
    state = tmp_path / "historical"
    base, window = _study()
    old_close = date(2024, 4, 1)
    bars = list(base.bars)
    bars.append(
        PriceBar(
            symbol="AAPL",
            day=old_close,
            open_price="90",
            close_price="91",
            volume="12",
            source_label="fixture",
        )
    )
    original = "sec:fact:AAPL:Revenues:2023-09-30:2022-10-01:2023-11-03:10-K:USD"
    amended = "sec:fact:AAPL:Revenues:2023-09-30:2022-10-01:2024-02-02:10-K/A:USD"
    study = Study(
        bars=tuple(bars),
        texts=(
            _fact(
                original,
                datetime(2023, 11, 3, 23, 59, tzinfo=ZoneInfo("America/New_York")),
            ),
            _fact(
                amended,
                datetime(2024, 2, 2, 23, 59, tzinfo=ZoneInfo("America/New_York")),
            ),
        ),
        benchmark_levels=base.benchmark_levels,
        benchmark_kind=base.benchmark_kind,
        benchmark_limitation=base.benchmark_limitation,
        price_limitation=base.price_limitation,
    )
    prepare_review(state, study, window, book="nomemory", model="terra")
    root = state / "bullish" / "nomemory" / "terra"
    context = json.loads((root / "context.json").read_text())
    ids = _ids(context)
    assert any(item.endswith("AAPL:close:2024-04-01") for item in ids)
    assert original in ids
    assert amended in ids
    manager = PortfolioManager.recover(root / "book.sqlite")
    receipt = json.loads((root / "receipt.json").read_text())
    rejected = manager.propose(_cited(receipt, original, "superseded"))
    assert isinstance(rejected, dict)
    assert rejected["status"] == "rejected"
    reasons = rejected["reasons"]
    assert isinstance(reasons, list)
    assert any(str(reason).startswith("superseded_evidence") for reason in reasons)
    accepted = manager.propose(_cited(receipt, amended, "current-fact"))
    assert isinstance(accepted, dict)
    assert accepted["status"] == "accepted"
    close_id = next(item for item in ids if item.endswith("AAPL:close:2024-04-01"))
    historical = manager.propose(_cited(receipt, close_id, "old-close"))
    assert isinstance(historical, dict)
    assert historical["status"] == "accepted"


def _row(evidence_id: str, kind: str, source: str, stamp: datetime) -> CitationRow:
    summary = "Daily close 10." if kind == "observation" else "note"
    return CitationRow(
        evidence_id=evidence_id,
        kind=kind,
        source_label=source,
        summary=summary,
        limitations=("fixture",),
        observed_at=stamp,
        available_at=stamp,
        symbol="AAPL",
    )


def _fact(evidence_id: str, observed: datetime) -> TextInput:
    return TextInput(
        evidence_id=evidence_id,
        symbol="AAPL",
        kind="fundamental",
        observed_at=observed,
        summary=(
            "Revenues 10 USD period end 2023-09-30 period start 2022-10-01 "
            "form 10-K filed 2023-11-03."
        ),
        source_label="sec-companyfacts",
        limitations=("fixture fact",),
    )


def _cited(
    receipt: dict[str, object], evidence_id: str, name: str
) -> InvestmentProposal:
    as_of = receipt["as_of"]
    assert isinstance(as_of, str)
    return InvestmentProposal(
        proposal_id=deterministic_memory_uuid7(f"historical-test:{name}"),
        as_of=datetime.fromisoformat(as_of),
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="The cited row is the current evidence for AAPL.",
        evidence_ids=(evidence_id,),
        uncertainty="This does not establish an edge.",
        allocation_reasoning="One share stays inside the local cash floor.",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="scripted",
    )


def _session(day: date, opened: datetime) -> SimulationSession:
    return SimulationSession(
        local_date=day,
        opened_at=opened,
        closed_at=datetime(day.year, day.month, day.day, 23, 59, tzinfo=UTC),
    )


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


def test_passive_and_price_value_ignore_caller_decimal_context() -> None:
    from decimal import Context, localcontext

    study, window = _study()
    context: Json = {
        "book": {"cash": "8330", "holdings": [{"symbol": "AAPL", "quantity": "4"}]}
    }
    expected_passive = constrained_passive("100", "110")
    expected_value = price_value(study, window, context, SECOND)
    with localcontext(Context(prec=1)):
        assert price_value(study, window, context, SECOND) == expected_value
        assert constrained_passive("100", "110") == expected_passive
