"""The expanded replay uses historical state and the current review."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from test_historical_replay import FIRST, SECOND, _study

from drift.historical.replay import prepare_review
from drift.historical.sources import PriceBar, TextInput
from drift.prospective.config import TRADING_SYMBOLS


def test_current_review_exposes_thirteen_symbols_without_future_prices(tmp_path):
    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    additional = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    future = TextInput(
        "future-amzn",
        "AMZN",
        "news",
        datetime(2024, 6, 5, 19, tzinfo=UTC),
        "A future filing.",
        "fixture",
        ("fixture",),
    )
    study = replace(
        study,
        bars=(*study.bars, *additional),
        texts=(*study.texts, future),
        workflow="current13",
    )
    prepared = prepare_review(tmp_path, study, window, book="memory", model="sol")
    assert prepared["status"] == "proposal_due"
    root = tmp_path / "bullish" / "memory" / "sol"
    context = json.loads((root / "context.json").read_text())
    assert {row["symbol"] for row in context["screen"]} == set(TRADING_SYMBOLS)
    assert not any(
        SECOND.isoformat() in row["evidence_id"] for row in context["evidence"]
    )
    assert "future-amzn" not in {row["evidence_id"] for row in context["evidence"]}
    assert (
        "Compare the screen, research, holdings, prior outcomes, and cash."
        in (root / "prompt.txt").read_text()
    )
    assert any(FIRST.isoformat() in row["evidence_id"] for row in context["evidence"])
    daily_close = next(
        row for row in context["evidence"] if row.get("price_role") == "close"
    )
    assert any(
        "conservative" in note and "actual" in note
        for note in daily_close["limitations"]
    )


def test_expanded_purchase_fills_at_next_open_and_remembers_own_outcome(tmp_path):
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge, decision_time
    from drift.manager.service import PortfolioManager

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(
            symbol,
            day,
            "111" if symbol == "AMZN" and day == SECOND else "100",
            "101",
            "100000",
            "fixture",
        )
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    context = json.loads((root / "context.json").read_text())
    receipt = json.loads((root / "receipt.json").read_text())
    citation = next(
        row["evidence_id"]
        for row in context["evidence"]
        if row.get("symbol") == "AMZN"
        and row.get("price_role") == "close"
        and FIRST.isoformat() in row["evidence_id"]
    )
    manager = PortfolioManager.recover(root / "book.sqlite")
    invalid = _buy(receipt, "invented-future-citation").model_copy(
        update={"symbol": "AMZN"}
    )
    assert manager.propose(invalid)["status"] == "rejected"
    # The rejected proposal is final for its id; use the real citation in a fresh book.
    other = tmp_path / "fresh"
    prepare_review(other, study, window, book="memory", model="sol")
    root = other / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    manager = PortfolioManager.recover(root / "book.sqlite")
    assert (
        manager.propose(_buy(receipt, citation).model_copy(update={"symbol": "AMZN"}))[
            "status"
        ]
        == "accepted"
    )
    acknowledge(other, study, window, book="memory", model="sol")
    book = manager.context(decision_time(SECOND))["book"]
    assert book["cash"] == "9888"
    assert any(
        row["symbol"] == "AMZN" and row["quantity"] == 1 for row in book["holdings"]
    )
    next_context = json.loads((root / "context.json").read_text())
    assert any(row["symbol"] == "AMZN" for row in next_context["decisions"])


@pytest.mark.parametrize(
    ("symbol", "expected"), [("AAPL", "accepted"), ("AMZN", "rejected")]
)
def test_native_trade_cites_only_eligible_displayed_outcomes(
    tmp_path, symbol, expected
):
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge, apply_native
    from drift.manager.service import PortfolioManager

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    context = json.loads((root / "context.json").read_text())
    price = next(
        row["evidence_id"]
        for row in context["evidence"]
        if row.get("symbol") == "AAPL" and row.get("price_role") == "close"
    )
    assert (
        PortfolioManager.recover(root / "book.sqlite").propose(_buy(receipt, price))[
            "status"
        ]
        == "accepted"
    )
    acknowledge(tmp_path, study, window, book="memory", model="sol")
    context = json.loads((root / "context.json").read_text())
    receipt = json.loads((root / "receipt.json").read_text())
    outcome_id = context["decisions"][0]["outcome_id"]
    own_price = next(
        row["evidence_id"]
        for row in context["evidence"]
        if row.get("symbol") == symbol and row.get("price_role") == "close"
    )
    proposal = _buy(receipt, outcome_id).model_copy(
        update={
            "symbol": symbol,
            "evidence_ids": (own_price, outcome_id),
            "inference": "native_supervised",
            "model_identity": receipt["model_identity"],
        }
    )
    path = tmp_path / "proposal.json"
    path.write_text(
        proposal.model_copy(update={"evidence_ids": ("not-shown",)}).model_dump_json()
    )
    with pytest.raises(ValueError, match="not shown"):
        apply_native(
            tmp_path, study, window, book="memory", model="sol", proposal_path=path
        )
    path.write_text(proposal.model_dump_json())
    result = apply_native(
        tmp_path, study, window, book="memory", model="sol", proposal_path=path
    )
    assert result["recorded_status"] == expected
    with sqlite3.connect(root / "book.sqlite") as connection:
        rows = connection.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE event_type = 'manager.decision' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    assert rows is not None
    reasons = json.loads(rows[0])["reasons"]
    if symbol == "AMZN":
        assert any("records AAPL, not AMZN" in reason for reason in reasons)
    else:
        assert all(not reason.startswith("unsupported_evidence") for reason in reasons)


def test_new_historical_books_use_cent_basis_while_old_books_reopen(tmp_path):
    from drift.historical.replay import (
        CLOSE_TIME_LIMITATION,
        _manager,
        _opening_packet,
        historical_mandate,
    )
    from drift.manager.book import replay
    from drift.manager.models import CENT_BASIS_ALLOCATION
    from drift.manager.service import PortfolioManager

    study, window = _study()
    old_root = tmp_path / "old" / "bullish" / "memory" / "sol"
    old_root.mkdir(parents=True)
    packet = _opening_packet(study, window)
    old_packet = packet.model_copy(
        update={
            "limitations": tuple(
                item for item in packet.limitations if item != CENT_BASIS_ALLOCATION
            ),
            "evidence": tuple(
                item.model_copy(
                    update={
                        "limitations": tuple(
                            note
                            for note in item.limitations
                            if note != CLOSE_TIME_LIMITATION
                        )
                    }
                )
                for item in packet.evidence
            ),
            "benchmark": tuple(
                point.model_copy(
                    update={
                        "limitations": tuple(
                            note
                            for note in point.limitations
                            if note != CLOSE_TIME_LIMITATION
                        )
                    }
                )
                for point in packet.benchmark
            ),
        }
    )
    PortfolioManager.open(old_root / "book.sqlite", old_packet, historical_mandate())
    old_manager = _manager(tmp_path / "old", study, window, "memory", "sol")
    old_replayed = replay(old_manager._ledger.verified_events())[0]
    assert CENT_BASIS_ALLOCATION not in old_replayed.limitations

    new_root = tmp_path / "new" / "bullish" / "memory" / "sol"
    new_root.mkdir(parents=True)
    new_manager = _manager(tmp_path / "new", study, window, "memory", "sol")
    new_replayed = replay(new_manager._ledger.verified_events())[0]
    assert CENT_BASIS_ALLOCATION in new_replayed.limitations
    _manager(tmp_path / "new", study, window, "memory", "sol")


def test_daily_close_source_discloses_assumed_timestamp():
    from drift.historical.replay import _benchmark_point, _optional_price

    study, window = _study()
    price = _optional_price(study, "AAPL", window.warmup_day, "close")
    assert price is not None
    assert any("actual exchange close" in note for note in price.limitations)
    benchmark = _benchmark_point(study, window.warmup_day, "100")
    assert any("actual exchange close" in note for note in benchmark.limitations)


def test_workflow_binding_prevents_using_the_same_book_for_legacy_and_current(tmp_path):
    import pytest

    study, window = _study()
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    with pytest.raises(ValueError, match="workflow mismatch"):
        prepare_review(
            tmp_path,
            replace(study, workflow="current13"),
            window,
            book="memory",
            model="sol",
        )


def test_workflow_mismatch_does_not_advance_an_existing_cursor(tmp_path):
    import pytest
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge
    from drift.manager.service import PortfolioManager

    study, window = _study()
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    context = json.loads((root / "context.json").read_text())
    citation = next(
        row["evidence_id"]
        for row in context["evidence"]
        if row.get("symbol") == "AAPL"
        and row.get("price_role") == "close"
        and FIRST.isoformat() in row["evidence_id"]
    )
    assert (
        PortfolioManager.recover(root / "book.sqlite").propose(_buy(receipt, citation))[
            "status"
        ]
        == "accepted"
    )
    before = (root / "cursor.json").read_bytes()
    with pytest.raises(ValueError, match="workflow mismatch"):
        acknowledge(
            tmp_path,
            replace(study, workflow="current13"),
            window,
            book="memory",
            model="sol",
        )
    assert (root / "cursor.json").read_bytes() == before


def test_expanded_window_retains_preexisting_research_for_new_symbols():
    from drift.historical.replay import texts_for_window

    _, window = _study()
    item = TextInput(
        "amzn-fact",
        "AMZN",
        "fundamental",
        datetime(2024, 5, 30, 21, tzinfo=UTC),
        "Revenue 100 USD.",
        "fixture",
        ("fixture",),
    )
    assert item in texts_for_window((item,), window, symbols=TRADING_SYMBOLS)
    assert item not in texts_for_window((item,), window)


def test_current_apply_rejects_citations_not_shown_before_mutating_book(tmp_path):
    import pytest
    from test_historical_replay import _buy

    from drift.historical.replay import apply_native

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    proposal = _buy(receipt, "not-shown").model_copy(
        update={
            "inference": "native_supervised",
            "model_identity": receipt["model_identity"],
        }
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json())
    cursor = (root / "cursor.json").read_bytes()
    with pytest.raises(ValueError, match="not shown"):
        apply_native(
            tmp_path, study, window, book="memory", model="sol", proposal_path=path
        )
    assert (root / "cursor.json").read_bytes() == cursor


def test_current_apply_accepts_shown_citation_and_fills_next_open(tmp_path):
    from test_historical_replay import _buy

    from drift.historical.replay import apply_native

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(
            symbol,
            day,
            "111" if symbol == "AMZN" and day == SECOND else "100",
            "101",
            "100000",
            "fixture",
        )
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    context = json.loads((root / "context.json").read_text())
    receipt = json.loads((root / "receipt.json").read_text())
    citation = next(
        row["evidence_id"]
        for row in context["evidence"]
        if row.get("symbol") == "AMZN"
        and row.get("price_role") == "close"
        and FIRST.isoformat() in row["evidence_id"]
    )
    proposal = _buy(receipt, citation).model_copy(
        update={
            "symbol": "AMZN",
            "inference": "native_supervised",
            "model_identity": receipt["model_identity"],
        }
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json())
    outcome = apply_native(
        tmp_path, study, window, book="memory", model="sol", proposal_path=path
    )
    assert outcome["recorded_status"] == "accepted"
    next_context = json.loads((root / "context.json").read_text())
    assert next_context["book"]["cash"] == "9888"
    assert any(row["symbol"] == "AMZN" for row in next_context["decisions"])


def test_rejected_buy_cash_only_review_values_cash_on_review_day(tmp_path):
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge
    from drift.manager.service import PortfolioManager

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    manager = PortfolioManager.recover(root / "book.sqlite")
    assert manager.propose(_buy(receipt, "not-in-ledger"))["status"] == "rejected"
    acknowledge(tmp_path, study, window, book="memory", model="sol")
    context = json.loads((root / "context.json").read_text())
    book = context["book"]
    assert book["cash"] == "10000"
    assert book["holdings"] == []
    assert book["net_asset_value"] == "10000"
    assert book["holdings_market_value"] == "0"
    assert book["session"] == FIRST.isoformat()
    assert book["historical_review_session"] == SECOND.isoformat()
    assert "last advanced ledger session" in book["valuation_reason"]
    assert context["decisions"][0]["status"] == "rejected"


def test_historical_cash_view_does_not_value_an_unmarked_position():
    from drift.historical.replay import historical_cash_view

    book = {
        "valuation": "unavailable",
        "cash": "9000",
        "holdings": [{"symbol": "AAPL", "quantity": 1}],
        "net_asset_value": None,
    }
    context = {"book": book}
    assert historical_cash_view(context, SECOND) == context
    assert book["net_asset_value"] is None


def test_historical_cash_view_is_nonmutating():
    from drift.historical.replay import historical_cash_view

    context = {
        "book": {
            "valuation": "unavailable",
            "cash": "10000",
            "holdings": [],
            "session": FIRST.isoformat(),
        }
    }
    result = historical_cash_view(context, SECOND)
    assert result["book"]["net_asset_value"] == "10000"
    assert "net_asset_value" not in context["book"]
    assert result["book"]["session"] == FIRST.isoformat()


def test_accepted_all_cash_hold_keeps_cash_value_in_next_review(tmp_path):
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge
    from drift.manager.service import PortfolioManager

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    hold = _buy(receipt, "unused").model_copy(
        update={
            "action": "hold",
            "quantity": 0,
            "evidence_ids": (),
            "exit_conditions": (),
        }
    )
    assert (
        PortfolioManager.recover(root / "book.sqlite").propose(hold)["status"]
        == "accepted"
    )
    acknowledge(tmp_path, study, window, book="memory", model="sol")
    result = json.loads((root / "context.json").read_text())
    assert result["book"]["net_asset_value"] == "10000"
    assert result["book"]["historical_review_session"] == SECOND.isoformat()


def test_opt_in_exit_memory_shows_prior_filled_trade_conditions_without_trading(
    tmp_path,
):
    from test_historical_replay import _buy

    from drift.historical.replay import acknowledge, decision_time
    from drift.manager.models import ExitCondition
    from drift.manager.service import PortfolioManager

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(
        study,
        bars=(*study.bars, *extra),
        workflow="current13",
        review_exit_conditions=True,
    )
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    root = tmp_path / "bullish" / "memory" / "sol"
    context = json.loads((root / "context.json").read_text())
    receipt = json.loads((root / "receipt.json").read_text())
    citation = next(
        x["evidence_id"]
        for x in context["evidence"]
        if x.get("symbol") == "AAPL"
        and x.get("price_role") == "close"
        and FIRST.isoformat() in x["evidence_id"]
    )
    manager = PortfolioManager.recover(root / "book.sqlite")
    proposal = _buy(receipt, citation).model_copy(
        update={
            "exit_conditions": (ExitCondition(kind="price_below", threshold="110"),)
        }
    )
    assert manager.propose(proposal)["status"] == "accepted"
    from datetime import timedelta

    before = manager.context(
        decision_time(FIRST) - timedelta(seconds=1), include_exit_conditions=True
    )
    assert before["decisions"] == []
    pending = manager.context(decision_time(FIRST), include_exit_conditions=True)
    assert pending["decisions"][0]["exit_conditions_status"] == "unfilled"
    acknowledge(tmp_path, study, window, book="memory", model="sol")
    revised = json.loads((root / "context.json").read_text())
    assert revised["decisions"][0]["exit_conditions"][0]["threshold"] == "110"
    assert (
        revised["decisions"][0]["exit_conditions_status"] == "review_current_position"
    )
    assert revised["decisions"][0]["fill"] is not None
    assert len(revised["book"]["holdings"]) == 1
    assert "review signals, not automatic orders" in (root / "prompt.txt").read_text()
    default = manager.context(decision_time(SECOND))
    assert "exit_conditions" not in default["decisions"][0]


def test_exit_review_cannot_reuse_ordinary_current_workflow_book(tmp_path):
    import pytest

    study, window = _study()
    existing = {bar.symbol for bar in study.bars}
    days = {bar.day for bar in study.bars}
    extra = tuple(
        PriceBar(symbol, day, "100", "101", "100000", "fixture")
        for symbol in TRADING_SYMBOLS
        if symbol not in existing
        for day in days
    )
    study = replace(study, bars=(*study.bars, *extra), workflow="current13")
    prepare_review(tmp_path, study, window, book="memory", model="sol")
    with pytest.raises(ValueError, match="workflow mismatch"):
        prepare_review(
            tmp_path,
            replace(study, review_exit_conditions=True),
            window,
            book="memory",
            model="sol",
        )
