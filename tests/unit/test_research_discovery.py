"""Discovery screen, compact evidence, and one isolated simulated decision."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest

from drift.historical.replay import (
    Json,
    decision_time,
    historical_session,
    research_brief,
)
from drift.historical.sources import PriceBar, TextInput
from drift.manager.models import ExitCondition, InvestmentProposal
from drift.manager.service import PortfolioManager
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.collect import UserSuggestion
from drift.prospective.config import MODELS, START, UNIVERSE
from drift.research.book import (
    DiscoveryBook,
    assemble_book,
    choose_sessions,
    later_weekday,
    review_prompts,
)
from drift.research.collect import rss_inputs
from drift.research.compact import (
    cited_ids_missing,
    compact_evidence,
    lookup_matches,
    visible_through,
)
from drift.research.screen import (
    ClosePoint,
    FactPoint,
    ScreenRow,
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
    filled = _object(
        manager.execute_pending(historical_session(book.settlement_day).closed_at)
    )
    assert filled["status"] == "filled"


def test_choose_sessions_uses_the_last_two_shared_days() -> None:
    days = _days(5)
    bars = _bars("AAPL", days, start=10, step=0, volume="10")
    assert choose_sessions(bars, ("AAPL",)) == (days[-2], days[-1])


def test_a_missing_research_bar_does_not_skip_a_market_session() -> None:
    days = _days(5)
    bars = _bars("AAPL", days, start=10, step=0, volume="10")
    bars.extend(
        bar
        for bar in _bars("CAT", days, start=10, step=0, volume="10")
        if bar.day != days[-2]
    )
    assert choose_sessions(bars, ("AAPL", "CAT")) == (days[-2], days[-1])


def test_a_later_review_can_sell_shares_the_ledger_holds(tmp_path: Path) -> None:
    days = _days(70)
    book = assemble_book(
        _bars("AAPL", days, start=100, step=0, volume="1000000"),
        (),
        price_limitation="fixture prices, not an exchange print",
        decision_day=days[-2],
        settlement_day=days[-1],
        min_dollar_volume=FLOOR,
        shortlist_limit=1,
    )
    manager, _opened = PortfolioManager.open(
        tmp_path / "book.sqlite", book.packet, book.mandate
    )
    bought = _object(
        manager.propose(
            _proposal(
                "open-buy",
                symbol="AAPL",
                action="buy",
                quantity=4,
                evidence=(str(_row(book, "AAPL").latest_evidence_id),),
                as_of=book.as_of,
            )
        )
    )
    assert bought["status"] == "accepted"
    filled = _object(
        manager.execute_pending(historical_session(book.settlement_day).closed_at)
    )
    assert filled["status"] == "filled"
    _prompts, _ids, rows = review_prompts(
        list(book.cache),
        ledger=list(book.cache),
        cash="8331.00",
        quantities={"AAPL": 4},
        review_day=book.review_day,
        min_dollar_volume=FLOOR,
    )
    assert _row_from(rows, "AAPL").inclusion == "holding"
    sold = _object(
        manager.propose(
            _proposal(
                "later-sell",
                symbol="AAPL",
                action="sell",
                quantity=1,
                evidence=(str(_row(book, "AAPL").latest_evidence_id),),
                as_of=decision_time(book.review_day),
            )
        )
    )
    assert sold["status"] == "accepted"
    assert not any(
        str(reason).startswith("unsafe_oversell") for reason in _reasons(sold)
    )
    settled = _object(
        manager.execute_pending(
            historical_session(later_weekday(book.review_day)).closed_at
        )
    )
    assert "decision_before_recorded_state" not in str(settled)


def test_compact_keeps_the_amendment_that_replaces_a_filing() -> None:
    as_of = datetime(2026, 10, 16, 22, tzinfo=UTC)
    original = _filing_row("10-Q", "2026-08-01T20:00:00+00:00", "2026-06-30")
    amendment = _filing_row("10-Q/A", "2026-09-01T20:00:00+00:00", "2026-06-30")
    later = _filing_row("8-K", "2026-10-01T20:00:00+00:00", "2026-10-01")
    compact = compact_evidence(
        [original, amendment, later],
        symbols=frozenset({"CAT"}),
        deep=frozenset({"CAT"}),
        as_of=as_of,
    )
    ids = {item["evidence_id"] for item in compact}
    assert original["evidence_id"] in ids
    assert amendment["evidence_id"] in ids
    assert later["evidence_id"] in ids


def test_post_cutoff_facts_do_not_displace_the_visible_statement() -> None:
    days = _days(70)
    bars = _bars("CAT", days, start=100, step=1, volume="1000000")
    visible = _eps("2026-02-01", "5", "2025-01-01", "2025-12-31")
    later = _eps("2026-12-01", "9", "2026-01-01", "2026-12-31")
    book = assemble_book(
        bars,
        (visible, later),
        suggestions=(
            UserSuggestion(
                symbol="LATE",
                summary="This note is after the decision.",
                observed_at=datetime(2026, 12, 1, 22, tzinfo=UTC),
            ),
        ),
        price_limitation="fixture prices, not an exchange print",
        decision_day=days[-2],
        settlement_day=days[-1],
        min_dollar_volume=FLOOR,
    )
    assert _row(book, "CAT").price_over_eps == "33.60"
    assert "LATE" not in {row.symbol for row in book.rows if row.shortlisted}


def test_eps_multiple_does_not_depend_on_row_order() -> None:
    facts = (
        FactPoint(
            symbol="JNJ",
            day=date(2026, 10, 1),
            summary=(
                "EarningsPerShareDiluted 0.09 USD/shares period end 2026-09-27 "
                "period start 2026-06-29 form 10-Q filed 2026-10-01."
            ),
        ),
        FactPoint(
            symbol="JNJ",
            day=date(2026, 10, 1),
            summary=(
                "EarningsPerShareDiluted 4.49 USD/shares period end 2026-09-27 "
                "period start 2025-12-29 form 10-Q filed 2026-10-01."
            ),
        ),
    )
    closes = _series("JNJ", _days(70), start=100, step=0, volume=1_000_000)
    forward = screen(
        closes,
        as_of=date(2026, 10, 16),
        universe=frozenset({"JNJ"}),
        authorized=frozenset(),
        facts=facts,
        min_dollar_volume=FLOOR,
    )
    backward = screen(
        closes,
        as_of=date(2026, 10, 16),
        universe=frozenset({"JNJ"}),
        authorized=frozenset(),
        facts=tuple(reversed(facts)),
        min_dollar_volume=FLOOR,
    )
    assert forward[0].price_over_eps == backward[0].price_over_eps
    assert forward[0].price_over_eps == "22.27"


def test_lookup_can_find_a_symbol_without_an_evidence_id() -> None:
    rows = lookup_matches(
        [_close_row("PG", date(2026, 11, 24), 172), _fact("2026-10-22", "2")],
        symbol="CAT",
        kind="fundamental",
    )
    assert len(rows) == 1
    assert rows[0]["kind"] == "fundamental"


def test_same_day_eps_rows_keep_the_annual_multiple_in_either_order() -> None:
    days = _days(70)
    stamp = datetime(2026, 2, 1, 21, tzinfo=UTC)
    rows = (
        _eps_at(stamp, "3", "2025-10-01", "2025-12-31", "q"),
        _eps_at(stamp, "5", "2025-01-01", "2025-12-31", "y"),
        _eps_at(stamp, "2", "2025-12-01", "2025-12-31", "m"),
    )
    forward = _eps_multiple(days, rows)
    backward = _eps_multiple(days, tuple(reversed(rows)))
    assert forward == backward == "33.60"


def test_review_screens_the_full_series_and_cites_only_the_ledger() -> None:
    days = _days(70)
    series = [_close_row("CAT", day, 100 + index) for index, day in enumerate(days)]
    ledger = [series[0], series[68]]
    prompts, _ids, rows = review_prompts(
        series,
        ledger=ledger,
        cash="10000",
        quantities={},
        review_day=days[-2],
        min_dollar_volume=FLOOR,
    )
    cat = _row_from(rows, "CAT")
    assert cat.sessions == 69
    assert cat.shortlisted
    assert cat.latest_evidence_id == series[68]["evidence_id"]
    assert cat.anchor_21_evidence_id is None
    assert cat.anchor_63_evidence_id is None
    assert str(series[5]["evidence_id"]) not in prompts["terra"]
    anchored = review_prompts(
        series,
        ledger=[series[5], series[47], series[68]],
        cash="10000",
        quantities={},
        review_day=days[-2],
        min_dollar_volume=FLOOR,
    )
    named = _row_from(anchored[2], "CAT")
    context = anchored[0]["terra"].split("Context JSON:", 1)[1]
    assert named.anchor_63_evidence_id == series[5]["evidence_id"]
    assert named.anchor_21_evidence_id == series[47]["evidence_id"]
    assert str(series[5]["evidence_id"]) in context
    assert str(series[47]["evidence_id"]) in context
    eps = _fact("2026-02-01", "5")
    withheld = review_prompts(
        [*series, eps],
        ledger=[series[0]],
        cash="10000",
        quantities={},
        review_day=days[-2],
        min_dollar_volume=FLOOR,
    )
    withheld_row = _row_from(withheld[2], "CAT")
    brief = withheld[0]["terra"].split("Context JSON:", 1)[0]
    latest_id = str(series[68]["evidence_id"])
    eps_id = str(eps["evidence_id"])
    assert withheld_row.sessions == 69
    assert withheld_row.latest_evidence_id is None
    assert "closes 69" in brief
    assert "63-session change 60.00 percent" in brief
    assert "diluted EPS 5" in brief
    assert "price over EPS 33.60" in brief
    assert latest_id not in brief
    assert eps_id not in withheld[0]["terra"]
    assert "fresh price, citable" not in brief
    assert "citable until superseded" not in brief
    registered = review_prompts(
        [*series, eps],
        ledger=[series[68], eps],
        cash="10000",
        quantities={},
        review_day=days[-2],
        min_dollar_volume=FLOOR,
    )
    registered_brief = registered[0]["terra"].split("Context JSON:", 1)[0]
    assert "citable until superseded" in registered_brief
    assert eps_id in registered[0]["terra"].split("Context JSON:", 1)[1]


def test_review_cites_only_registered_evidence_and_keeps_suggestions() -> None:
    stamp = datetime(2026, 11, 24, 21, tzinfo=UTC).isoformat()
    close = {
        "available_at": stamp,
        "evidence_id": "vendor-close-001",
        "kind": "observation",
        "limitations": ["fixture"],
        "observed_at": stamp,
        "price": "100",
        "price_role": "close",
        "source_label": "vendor",
        "summary": "Daily close 100 for AAPL. Volume 1000000.",
        "symbol": "AAPL",
    }
    suggestion = {
        "available_at": stamp,
        "evidence_id": "suggestion:IDEA:2026-11-24",
        "kind": "suggestion",
        "limitations": ["user suggestion"],
        "observed_at": stamp,
        "price": None,
        "price_role": None,
        "source_label": "user-suggestion",
        "summary": "Look at IDEA.",
        "symbol": "IDEA",
    }
    prompts, _ids, rows = review_prompts(
        [close, suggestion],
        ledger=[close, suggestion],
        cash="10000",
        quantities={},
        review_day=date(2026, 11, 25),
        min_dollar_volume=FLOOR,
    )
    assert _row_from(rows, "AAPL").latest_evidence_id == "vendor-close-001"
    assert "vendor-close-001" in prompts["terra"]
    assert _row_from(rows, "IDEA").shortlisted


def test_detail_lookup_hides_rows_after_the_decision_cutoff() -> None:
    as_of = datetime(2026, 11, 24, 22, tzinfo=UTC)
    early = _close_row("AAPL", date(2026, 11, 24), 100)
    later = _close_row("AAPL", date(2026, 11, 25), 101)
    visible = visible_through([early, later], as_of)
    assert [item["evidence_id"] for item in visible] == [early["evidence_id"]]


def test_rejected_ingest_does_not_change_the_cache() -> None:
    from drift.research.__main__ import remember_ingested

    cache = [_close_row("AAPL", date(2026, 11, 24), 100)]
    extra = {"evidence_id": "vendor-close-001", "kind": "observation"}
    assert remember_ingested(cache, [extra], accepted=False) == cache
    stored = remember_ingested(cache, [extra, extra], accepted=True)
    assert [item["evidence_id"] for item in stored].count("vendor-close-001") == 1
    revised = remember_ingested(
        stored,
        [{"evidence_id": "vendor-close-001", "price": "123.45"}],
        accepted=True,
    )
    assert revised[-1]["price"] == "123.45"
    assert [item["evidence_id"] for item in revised].count("vendor-close-001") == 1


def test_discovery_state_rejects_a_prospective_role_directory(tmp_path: Path) -> None:
    from drift.research.__main__ import _assert_state

    role = tmp_path / "observation"
    role.mkdir()
    (role / "terra.sqlite").write_bytes(b"")
    with pytest.raises(ValueError, match="prospective"):
        _assert_state(role)


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


def _row(book: DiscoveryBook, symbol: str) -> ScreenRow:
    return _row_from(book.rows, symbol)


def _row_from(rows: tuple[ScreenRow, ...], symbol: str) -> ScreenRow:
    return next(item for item in rows if item.symbol == symbol)


def _filing_row(form: str, stamp: str, report: str) -> dict[str, object]:
    accession = f"0000000000-26-{form.replace('/', '')}{report[-2:]}"
    return {
        "available_at": stamp,
        "evidence_id": f"sec:filing:{accession}",
        "kind": "news",
        "limitations": ["fixture"],
        "observed_at": stamp,
        "price": None,
        "price_role": None,
        "source_label": "sec-submissions",
        "summary": f"{form} accession {accession} report {report}.",
        "symbol": "CAT",
    }


def _eps_multiple(days: tuple[date, ...], rows: tuple[TextInput, ...]) -> str | None:
    book = assemble_book(
        _bars("CAT", days, start=100, step=1, volume="1000000"),
        rows,
        price_limitation="fixture prices, not an exchange print",
        decision_day=days[-2],
        settlement_day=days[-1],
        min_dollar_volume=FLOOR,
    )
    return _row(book, "CAT").price_over_eps


def _eps_at(stamp: datetime, value: str, start: str, end: str, label: str) -> TextInput:
    return TextInput(
        evidence_id=(
            f"sec:fact:CAT:EarningsPerShareDiluted:{end}:{start}:{label}:10-K:USD"
        ),
        symbol="CAT",
        kind="fundamental",
        observed_at=stamp,
        summary=(
            f"EarningsPerShareDiluted {value} USD period end {end} "
            f"period start {start} form 10-K filed {stamp.date().isoformat()}."
        ),
        source_label="sec-companyfacts",
        limitations=("fixture",),
    )


def _eps(filed: str, value: str, start: str, end: str) -> TextInput:
    observed = datetime.fromisoformat(f"{filed}T21:00:00+00:00")
    return TextInput(
        evidence_id=(
            f"sec:fact:CAT:EarningsPerShareDiluted:{end}:{start}:{filed}:10-K:USD"
        ),
        symbol="CAT",
        kind="fundamental",
        observed_at=observed,
        summary=(
            f"EarningsPerShareDiluted {value} USD period end {end} "
            f"period start {start} form 10-K filed {filed}."
        ),
        source_label="sec-companyfacts",
        limitations=("fixture",),
    )


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
