"""Discovery screen, compact evidence, and one isolated simulated decision."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest

from drift.historical.replay import Json, decision_time, research_brief
from drift.historical.sources import PriceBar
from drift.manager.models import ExitCondition, InvestmentProposal
from drift.manager.service import PortfolioManager
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.collect import UserSuggestion
from drift.prospective.config import MODELS, START, UNIVERSE
from drift.research.book import assemble_book, choose_sessions
from drift.research.collect import rss_inputs
from drift.research.compact import cited_ids_missing, compact_evidence
from drift.research.screen import (
    ClosePoint,
    FactPoint,
    screen,
)
from drift.research.universe import ORIGINAL_TRADING_SYMBOLS, RESEARCH_UNIVERSE

FLOOR = Decimal("1000")


def test_prospective_universe_stays_the_original_four() -> None:
    assert tuple(symbol for symbol, _cik, _name in UNIVERSE) == ORIGINAL_TRADING_SYMBOLS
    assert START == date(2026, 11, 27)
    assert "CAT" in {item.symbol for item in RESEARCH_UNIVERSE}
    assert "CAT" not in ORIGINAL_TRADING_SYMBOLS


def test_screen_keeps_holdings_and_suggestions_and_does_not_authorize_them() -> None:
    days = _days(70)
    closes = [
        *_series("CAT", days, start=100, step=1, volume=1_000_000),
        *_series("AAPL", days, start=100, step=0, volume=1_000_000),
        *_series("JNJ", days, start=100, step=0, volume=1),
        *_series("LIN", days, start=50, step=0, volume=1),
    ]
    rows = {
        row.symbol: row
        for row in screen(
            closes,
            as_of=days[-2],
            universe=frozenset(item.symbol for item in RESEARCH_UNIVERSE),
            authorized=frozenset(ORIGINAL_TRADING_SYMBOLS),
            holdings=frozenset({"JNJ"}),
            suggestions=frozenset({"IDEA"}),
            facts=(
                FactPoint(
                    symbol="CAT",
                    day=days[10],
                    summary=(
                        "EarningsPerShareDiluted 5 USD period end 2025-12-31 "
                        "period start 2025-01-01 form 10-K filed 2026-02-01."
                    ),
                ),
            ),
            min_dollar_volume=FLOOR,
            shortlist_limit=1,
        )
    }
    assert rows["CAT"].shortlisted
    assert rows["CAT"].screen_pass
    assert not rows["CAT"].trading_authorized
    assert rows["CAT"].price_over_eps is not None
    assert rows["AAPL"].trading_authorized
    assert rows["AAPL"].screen_pass
    assert not rows["AAPL"].shortlisted
    assert rows["JNJ"].shortlisted
    assert not rows["JNJ"].screen_pass
    assert rows["JNJ"].inclusion == "holding"
    assert not rows["LIN"].shortlisted
    assert not rows["LIN"].screen_pass
    assert rows["IDEA"].shortlisted
    assert rows["IDEA"].inclusion == "suggestion"
    assert not rows["IDEA"].trading_authorized
    assert "outside the configured research universe" in " ".join(rows["IDEA"].notes)
    assert rows["CAT"].return_63 == "60.00 percent"


def test_compact_slice_keeps_anchors_and_a_superseded_fact() -> None:
    days = _days(70)
    evidence = [_close_row("CAT", day, 100 + index) for index, day in enumerate(days)]
    older = _fact("2026-02-01", "4")
    newer = _fact("2026-08-01", "5")
    evidence.extend((older, newer))
    as_of = decision_time(days[-2])
    visible = [
        item
        for item in evidence
        if datetime.fromisoformat(str(item["observed_at"])) <= as_of
    ]
    compact = compact_evidence(
        visible,
        symbols=frozenset({"CAT"}),
        deep=frozenset({"CAT"}),
        as_of=as_of,
    )
    ids = {item["evidence_id"] for item in compact}
    assert len([item for item in compact if item["price_role"] == "close"]) == 3
    assert len(visible) > len(compact)
    brief = research_brief(
        cast(Json, {"book": {"cash": "10000"}, "evidence": visible}),
        as_of,
        policy="research",
    )
    assert "63-session change 60.00 percent" in brief
    assert cited_ids_missing(brief, compact) == ()
    assert older["evidence_id"] in ids
    assert newer["evidence_id"] in ids
    assert "superseded, not citable" in brief


def test_isolated_book_escalates_a_new_name_and_can_fill_an_authorized_buy(
    tmp_path: Path,
) -> None:
    days = _days(70)
    decision_day, settlement_day = days[-2], days[-1]
    bars = [
        *_bars("CAT", days, start=100, step=1, volume="1000000"),
        *_bars("AAPL", days, start=100, step=0, volume="1000000"),
    ]
    suggestion = UserSuggestion(
        symbol="IDEA",
        summary="Look at IDEA. This note is not a trade signal.",
        observed_at=decision_time(days[0]),
    )
    book = assemble_book(
        bars,
        (),
        suggestions=(suggestion,),
        holdings=frozenset({"AAPL"}),
        price_limitation="fixture prices, not an exchange print",
        decision_day=decision_day,
        settlement_day=settlement_day,
        min_dollar_volume=FLOOR,
        shortlist_limit=1,
    )
    by_symbol = {row.symbol: row for row in book.rows}
    assert by_symbol["CAT"].shortlisted
    assert not by_symbol["CAT"].trading_authorized
    assert "CAT" in book.prompts["terra"]
    assert "screening does not authorize a trade" in book.prompts["terra"].lower() or (
        "A pass does not authorize a trade." in book.prompts["terra"]
    )
    assert int(str(book.measurement["reduction_characters"])) > 0
    assert "IDEA" in book.packet.model_dump_json()
    manager, _opened = PortfolioManager.open(
        tmp_path / "book.sqlite", book.packet, book.mandate
    )
    held = _object(
        manager.propose(
            _proposal(
                "hold",
                symbol="AAPL",
                action="hold",
                quantity=0,
                evidence=(),
                as_of=book.as_of,
            )
        )
    )
    assert held["status"] == "accepted"
    assert any(str(reason).startswith("abstained:") for reason in _reasons(held))
    escalated = _object(
        manager.propose(
            _proposal(
                "escalate",
                symbol="CAT",
                action="buy",
                quantity=1,
                evidence=(str(by_symbol["CAT"].latest_evidence_id),),
                as_of=book.as_of,
            )
        )
    )
    assert escalated["status"] == "escalated"
    assert any(
        str(reason).startswith("escalated_symbol_outside_mandate")
        for reason in _reasons(escalated)
    )
    bought = _object(
        manager.propose(
            _proposal(
                "buy",
                symbol="AAPL",
                action="buy",
                quantity=10,
                evidence=(str(by_symbol["AAPL"].latest_evidence_id),),
                as_of=book.as_of,
            )
        )
    )
    assert bought["status"] == "accepted"
    assert bought["fill"] is None
    filled = _object(manager.execute_pending(book.packet.sessions[-1].closed_at))
    assert filled["status"] == "filled"


def test_choose_sessions_uses_the_last_two_shared_days() -> None:
    days = _days(5)
    bars = _bars("AAPL", days, start=10, step=0, volume="10")
    assert choose_sessions(bars, ("AAPL",)) == (days[-2], days[-1])


def test_rss_headline_is_untrusted_text() -> None:
    rows = rss_inputs(
        "CAT",
        """<?xml version="1.0"?>
        <rss><channel><item>
        <title>Caterpillar updates its outlook</title>
        <link>https://example.test/cat</link>
        <pubDate>Wed, 25 Nov 2026 15:00:00 GMT</pubDate>
        </item></channel></rss>""",
    )
    assert len(rows) == 1
    assert rows[0].source_label == "yahoo-rss"
    assert rows[0].kind == "news"
    assert "not authenticated origin" in rows[0].limitations[0]


def test_discovery_state_cannot_sit_inside_prospective() -> None:
    from drift.research.__main__ import _assert_state

    with pytest.raises(ValueError, match="prospective"):
        _assert_state(Path("/tmp/prospective/discovery"))


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        message = "manager result was not an object"
        raise AssertionError(message)
    return {str(key): item for key, item in value.items()}


def _reasons(result: dict[str, object]) -> list[object]:
    reasons = result["reasons"]
    if not isinstance(reasons, list):
        message = "manager result has no reason list"
        raise AssertionError(message)
    return reasons


def _proposal(
    name: str,
    *,
    symbol: str,
    action: Literal["buy", "sell", "hold"],
    quantity: int,
    evidence: tuple[str, ...],
    as_of: datetime,
) -> InvestmentProposal:
    exits: tuple[ExitCondition, ...] = ()
    if action != "hold" or evidence:
        exits = (ExitCondition(kind="narrative", text="Revisit if the thesis breaks."),)
    return InvestmentProposal(
        proposal_id=deterministic_memory_uuid7(f"discovery-test:{name}"),
        as_of=as_of,
        action=action,
        symbol=symbol,
        quantity=quantity,
        thesis="Fixture thesis with a catalyst and a downside."
        if action != "hold"
        else "The citable evidence is not enough, so this book abstains.",
        uncertainty="Fixture uncertainty. This is not an investing edge.",
        allocation_reasoning="Cash remains a holding. The screen is not an order.",
        evidence_ids=evidence,
        exit_conditions=exits,
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )


def _days(count: int) -> tuple[date, ...]:
    found: list[date] = []
    day = date(2026, 10, 16)
    while len(found) < count:
        if day.weekday() < 5:
            found.append(day)
        day -= timedelta(days=1)
    return tuple(reversed(found))


def _series(
    symbol: str, days: tuple[date, ...], *, start: int, step: int, volume: int
) -> list[ClosePoint]:
    return [
        ClosePoint(
            symbol=symbol,
            day=day,
            close=Decimal(start + step * index),
            volume=Decimal(volume),
            evidence_id=f"discovery:fixture:{symbol}:close:{day.isoformat()}",
        )
        for index, day in enumerate(days)
    ]


def _bars(
    symbol: str, days: tuple[date, ...], *, start: int, step: int, volume: str
) -> list[PriceBar]:
    return [
        PriceBar(
            symbol=symbol,
            day=day,
            open_price=str(start + step * index),
            close_price=str(start + step * index),
            volume=volume,
            source_label="fixture",
        )
        for index, day in enumerate(days)
    ]


def _close_row(symbol: str, day: date, price: int) -> dict[str, object]:
    stamp = datetime(day.year, day.month, day.day, 21, tzinfo=UTC).isoformat()
    return {
        "available_at": stamp,
        "evidence_id": f"discovery:fixture:{symbol}:close:{day.isoformat()}",
        "kind": "observation",
        "limitations": ["fixture"],
        "observed_at": stamp,
        "price": str(price),
        "price_role": "close",
        "source_label": "fixture",
        "summary": f"Daily close {price} for {symbol}. Volume 1000000.",
        "symbol": symbol,
    }


def _fact(filed: str, value: str) -> dict[str, object]:
    return {
        "available_at": f"{filed}T21:00:00+00:00",
        "evidence_id": (
            "sec:fact:CAT:EarningsPerShareDiluted:2025-12-31:"
            f"2025-01-01:{filed}:10-K:USD"
        ),
        "kind": "fundamental",
        "limitations": ["fixture"],
        "observed_at": f"{filed}T21:00:00+00:00",
        "price": None,
        "price_role": None,
        "source_label": "sec-companyfacts",
        "summary": (
            f"EarningsPerShareDiluted {value} USD period end 2025-12-31 "
            f"period start 2025-01-01 form 10-K filed {filed}."
        ),
        "symbol": "CAT",
    }
