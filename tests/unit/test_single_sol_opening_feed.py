"""Opening feed must support later valuation without rewriting old books."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_prospective_pilot_safety import collection
from test_prospective_window import _nyse_html

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import packet_through
from drift.manager.models import EvidenceItem
from drift.manager.service import (
    PortfolioManager,
    _valid_pilot_close,
    _valid_pilot_trade,
)
from drift.prospective import window
from drift.prospective.collect import Bar, Collection, Filing, build_packet
from drift.prospective.config import pilot_mandate
from drift.prospective.locking import pilot_lock
from drift.prospective.run import ingest_new, open_books, perform_daily


def non_price_collection(now: datetime) -> Collection:
    return replace(
        collection(now),
        bars=(),
        filings=(Filing("AAPL", "10-Q", "fixture", now - timedelta(days=1)),),
    )


def test_missing_opening_feed_refuses_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    window.configure_window(tmp_path)
    now = datetime(2026, 11, 30, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 15, tzinfo=UTC),
        "100",
        "101",
        now,
        "alpaca-bars-v2-iex-raw",
        covered_until=now,
    )
    with pilot_lock(tmp_path):
        missing = build_packet(non_price_collection(now), readiness=False)
        with pytest.raises(ValueError, match="opening.*feed"):
            open_books(tmp_path, "observation", missing)
        assert not (tmp_path / "observation" / "sol.sqlite").exists()
        with pytest.raises(ValueError, match="opening.*feed"):
            perform_daily(
                tmp_path,
                "observation",
                now,
                non_price_collection(now),
            )
        assert not (tmp_path / "observation").exists()
        valid = build_packet(replace(collection(now), bars=(bar,)), readiness=False)
        assert open_books(tmp_path, "observation", valid)["sol"] == "opened"


def test_mixed_feed_refused_and_existing_bad_book_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    window.configure_window(tmp_path)
    now = datetime(2026, 11, 30, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 15, tzinfo=UTC),
        "100",
        "101",
        now,
        "alpaca-bars-v2-iex-raw",
        covered_until=now,
    )
    with pilot_lock(tmp_path):
        mixed = build_packet(
            replace(
                collection(now),
                bars=(
                    bar,
                    replace(bar, symbol="MSFT", source_label="alpaca-bars-v2-sip-raw"),
                ),
            ),
            readiness=False,
        )
        with pytest.raises(ValueError, match="opening.*feed"):
            open_books(tmp_path, "observation", mixed)
        assert not (tmp_path / "observation" / "sol.sqlite").exists()

        missing = build_packet(non_price_collection(now), readiness=False)
        root = tmp_path / "observation"
        root.mkdir()
        path = root / "sol.sqlite"
        PortfolioManager.open(path, missing, pilot_mandate())
        before = SQLiteLedger.open_existing(path).verified_events()
        with pytest.raises(ValueError, match="opening.*feed"):
            perform_daily(
                tmp_path, "observation", now, replace(collection(now), bars=(bar,))
            )
        assert SQLiteLedger.open_existing(path).verified_events() == before
        assert not (root / "packet.json").exists()


def test_later_close_can_enable_trade_but_not_repair_mark_feed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    monkeypatch.setattr(window, "_clock", lambda: received)
    window.configure_window(tmp_path)
    now = datetime(2026, 11, 30, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 15, tzinfo=UTC),
        "100",
        "101",
        now,
        "yahoo-chart-v8",
        covered_until=now,
    )
    with pilot_lock(tmp_path):
        opening = build_packet(non_price_collection(now), readiness=False)
        close_time = datetime(2026, 11, 30, 21, tzinfo=UTC)
        later_bar = replace(
            bar,
            observed_at=now,
            fetched_at=close_time + timedelta(seconds=1),
            covered_until=close_time,
            source_label="alpaca-bars-v2-iex-raw",
        )
        later = build_packet(
            replace(collection(close_time + timedelta(seconds=1)), bars=(later_bar,)),
            readiness=False,
        )
        close = next(item for item in later.evidence if item.price_role == "close")
        trade_time = now + timedelta(minutes=1)
        trade = EvidenceItem(
            evidence_id=f"alpaca-trades-v2-iex:AAPL:{trade_time.isoformat()}:V:1",
            kind="observation",
            symbol="AAPL",
            observed_at=trade_time,
            available_at=trade_time,
            source_label="alpaca-trades-v2-iex",
            price="100",
            price_role="trade",
            summary="synthetic trade",
            limitations=("fixture",),
        )
        combined = opening.model_copy(
            update={"evidence": (*opening.evidence, close, trade)}
        )
        assert not _valid_pilot_close(close, "AAPL", opening)
        assert _valid_pilot_trade(trade, combined, pilot_mandate(), "AAPL")
        root = tmp_path / "observation"
        root.mkdir()
        PortfolioManager.open(root / "sol.sqlite", opening, pilot_mandate())
        result = ingest_new(
            tmp_path,
            "observation",
            replace(collection(close_time + timedelta(seconds=1)), bars=(later_bar,)),
        )
        assert result["ingested"] == {"sol": "ingested"}
        packet = packet_through(
            SQLiteLedger.open_existing(root / "sol.sqlite").verified_events()
        )
        assert close in packet.evidence
