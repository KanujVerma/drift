"""Single-book observation contract, exercised with synthetic inputs only."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from test_prospective_pilot_safety import collection
from test_prospective_window import _nyse_html

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.models import (
    EvidenceItem,
    ExitCondition,
    IngestBatch,
    InvestmentProposal,
)
from drift.manager.service import PortfolioManager
from drift.prospective import window
from drift.prospective.collect import Bar, TradeInvalidation
from drift.prospective.config import MODELS
from drift.prospective.locking import pilot_lock
from drift.prospective.run import (
    _record_corporate_action_status,
    apply_proposal,
    execute_books,
    pending_benchmark_after,
    perform_daily,
    restore_pending_observation_reviews,
    status_report,
)


def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> datetime:
    received = datetime(2026, 11, 27, 20, tzinfo=UTC)
    monkeypatch.setattr(window, "_clock", lambda: received)
    monkeypatch.setattr(window, "_fetch_nyse", lambda: (_nyse_html(), received))
    configured_window = window.configure_window(tmp_path)
    assert configured_window.mode == "single-sol"
    assert len(configured_window.observation_dates) == 20
    assert len(configured_window.settlement_dates) == 5
    return datetime(2026, 11, 30, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    "quantity, expected_status, expected_cash",
    [(1, "filled", "9899"), (30, "rejected", "10000")],
)
def test_single_sol_review_seal_causal_fill_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quantity: int,
    expected_status: str,
    expected_cash: str,
) -> None:
    issued = configured(tmp_path, monkeypatch)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    result: Any = perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    assert set(result["opened"]) == {"sol"}
    assert not (tmp_path / "observation" / "terra.sqlite").exists()
    assert restore_pending_observation_reviews(tmp_path) == ["sol"]
    folder = tmp_path / "observation" / "sol"
    receipt = json.loads((folder / "receipt.json").read_text())
    context = json.loads((folder / "context.json").read_text())
    assert context["book"]["cash"] == "10000"
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=quantity,
        thesis="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["sol"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json())
    submitted = issued + timedelta(minutes=5)
    sealed = submitted + timedelta(seconds=2)
    clocks = iter((submitted - timedelta(seconds=1), submitted, sealed))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return next(clocks)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    accepted = apply_proposal(tmp_path, "observation", "sol", path)
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    assert pending_benchmark_after(tmp_path) == sealed
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "sol.sqlite")
    types = [event.event_type for event in ledger.verified_events()]
    assert types.index("manager.decision") < types.index("manager.prospective_seal")
    manager = PortfolioManager.recover(tmp_path / "observation" / "sol.sqlite")

    def trade(observed: datetime, available: datetime, trade_id: int) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:{trade_id}",
            kind="observation",
            symbol="AAPL",
            observed_at=observed,
            available_at=available,
            limitations=("fixture",),
            summary="Fixture",
            source_label="alpaca-trades-v2-iex",
            price="100",
            price_role="trade",
        )

    baseline_observed = sealed + timedelta(seconds=15)
    baseline_available = sealed + timedelta(seconds=30)
    baseline = EvidenceItem(
        evidence_id=(
            f"alpaca:benchmark:alpaca-trades-v2-iex:SPY:"
            f"{baseline_observed.isoformat()}:V:3"
        ),
        kind="observation",
        symbol="SPY",
        observed_at=baseline_observed,
        available_at=baseline_available,
        limitations=("fixture",),
        summary="Synthetic benchmark",
        source_label="alpaca-trades-v2-iex",
        price="500",
        price_role="trade",
    )
    manager.ingest(IngestBatch(evidence=(baseline,)))
    first = sealed + timedelta(minutes=1)
    manager.ingest(IngestBatch(evidence=(trade(submitted, first, 1),)))
    with pilot_lock(tmp_path):
        _record_corporate_action_status(
            tmp_path / "observation", first, "complete", coverage_at=first
        )
    first_fill: Any = execute_books(tmp_path, "observation", first)["sol"]
    assert first_fill["status"] == "pending"
    second = first + timedelta(minutes=1)
    manager.ingest(IngestBatch(evidence=(trade(first, second, 2),)))
    with pilot_lock(tmp_path):
        _record_corporate_action_status(
            tmp_path / "observation", second, "complete", coverage_at=second
        )
    second_fill: Any = execute_books(tmp_path, "observation", second)["sol"]
    assert second_fill["status"] == expected_status
    report: Any = status_report(tmp_path, "observation", second)
    assert report["trusted_decision_records"] == {"sol": 1}
    assert report["recorded_session_count"] == 1
    assert report["model_identity_verification"] == "not_verified"
    assert report["reports"]["sol"]["cash"] == expected_cash
    if quantity == 1:
        close_at = datetime(2026, 11, 30, 21, 10, tzinfo=UTC)
        bars = tuple(
            Bar(
                symbol,
                issued,
                price,
                price,
                close_at,
                "alpaca-bars-v2-iex-raw",
                covered_until=close_at,
            )
            for symbol, price in (("AAPL", "101"), ("SPY", "500"))
        )
        perform_daily(
            tmp_path,
            "observation",
            close_at,
            replace(collection(close_at), bars=bars),
            suppress_reviews=True,
        )
        closing: Any = manager.report(close_at)
        assert closing["benchmark_relative"]["status"] == "available"
        assert closing["benchmark_relative"]["start_portfolio_value"] == "10000"
        price_benchmark = closing["price_return_benchmark"]
        assert price_benchmark["status"] == "available"
        assert price_benchmark["start_evidence_id"] == baseline.evidence_id
        assert price_benchmark["limitation"] == (
            "SPY price return; dividends are not credited to either side"
            "; benchmark begins after the first decision while the book was in cash"
        )
        noticed_at = close_at + timedelta(minutes=1)
        trade_id = f"alpaca-trades-v2-iex:AAPL:{first.isoformat()}:V:2"
        notice = TradeInvalidation("AAPL", trade_id, noticed_at, "canceled")
        perform_daily(
            tmp_path,
            "observation",
            noticed_at,
            replace(collection(noticed_at), bars=(), trade_invalidations=(notice,)),
            suppress_reviews=True,
        )
        invalidated: Any = manager.report(noticed_at)
        assert invalidated["valuation"] == "unavailable"
        assert invalidated["benchmark_relative"]["status"] == "unavailable"


def test_single_window_binding_cannot_be_downgraded_to_paired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = configured(tmp_path, monkeypatch)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    document_path = tmp_path / "window.json"
    document = json.loads(document_path.read_text())
    del document["mode"]
    document_path.write_text(json.dumps(document))
    manager = PortfolioManager.recover(tmp_path / "observation" / "sol.sqlite")
    with pytest.raises(ValueError, match="window do not match"):
        manager.context(issued)


def test_legacy_window_without_mode_remains_paired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = configured(tmp_path, monkeypatch)
    path = tmp_path / "window.json"
    document = json.loads(path.read_text())
    del document["mode"]
    path.write_text(json.dumps(document))
    legacy_window = window.load_window(tmp_path)
    assert legacy_window is not None and legacy_window.mode == "paired"
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    result: Any = perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    assert set(result["opened"]) == {"terra", "sol"}


def test_inactive_model_is_rejected_before_any_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    configured(tmp_path, monkeypatch)
    args = Namespace(
        command="submit",
        role="readiness",
        state=tmp_path,
        proposal=["sol=missing.json", "terra=missing.json"],
    )
    with pytest.raises(ValueError, match="inactive model"):
        _run(args)
    assert not (tmp_path / "readiness").exists()


def test_visible_wrong_symbol_citation_is_recorded_and_sealed_as_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = configured(tmp_path, monkeypatch)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    folder = tmp_path / "observation" / "sol"
    receipt = json.loads((folder / "receipt.json").read_text())
    context = json.loads((folder / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="MSFT",
        quantity=1,
        thesis="Synthetic mismatch",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["sol"],
    )
    path = tmp_path / "mismatched.json"
    path.write_text(proposal.model_dump_json())

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return issued + timedelta(minutes=5)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = apply_proposal(tmp_path, "observation", "sol", path)
    assert isinstance(result, dict) and result["status"] == "rejected"
    reasons = result["reasons"]
    assert isinstance(reasons, list)
    assert any("evidence" in str(reason) for reason in reasons)
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "sol.sqlite"
    ).verified_events()
    assert (
        sum(event.event_type == "manager.prospective_intent" for event in events) == 1
    )
    assert sum(event.event_type == "manager.decision" for event in events) == 1
    assert sum(event.event_type == "manager.prospective_seal" for event in events) == 1


def test_single_intent_clock_race_allows_only_identical_same_session_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = configured(tmp_path, monkeypatch)
    bar = Bar(
        "AAPL",
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )
    receipt = json.loads(
        (tmp_path / "observation" / "sol" / "receipt.json").read_text()
    )
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Synthetic hold",
        evidence_ids=(),
        uncertainty="Fixture",
        allocation_reasoning="Cash",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["sol"],
    )
    path = tmp_path / "retry.json"
    path.write_text(proposal.model_dump_json())
    ledger_path = tmp_path / "observation" / "sol.sqlite"
    manager = PortfolioManager.recover(ledger_path)
    calls = 0

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                available = issued + timedelta(minutes=4)
                item = EvidenceItem(
                    evidence_id="single-race-news",
                    kind="news",
                    symbol="AAPL",
                    observed_at=issued,
                    available_at=available,
                    limitations=("fixture",),
                    summary="Synthetic event",
                    source_label="fixture",
                )
                manager.ingest(IngestBatch(evidence=(item,)))
                return issued + timedelta(minutes=3)
            return issued + timedelta(minutes=2 if calls == 1 else 5)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = apply_proposal(tmp_path, "observation", "sol", path)
    assert isinstance(result, dict) and result["status"] == "rejected"
    events = SQLiteLedger.open_existing(ledger_path).verified_events()
    assert sum(e.event_type == "manager.prospective_intent" for e in events) == 1
    assert not any(e.event_type == "manager.decision" for e in events)
    path.write_text(proposal.model_copy(update={"thesis": "Changed"}).model_dump_json())
    with pytest.raises(ValueError, match="conflicts with saved submission intent"):
        apply_proposal(tmp_path, "observation", "sol", path)
    path.write_text(proposal.model_dump_json())
    retried = apply_proposal(tmp_path, "observation", "sol", path)
    assert isinstance(retried, dict) and retried["status"] == "accepted"
    events = SQLiteLedger.open_existing(ledger_path).verified_events()
    assert sum(e.event_type == "manager.prospective_intent" for e in events) == 1
    assert sum(e.event_type == "manager.decision" for e in events) == 1
    assert sum(e.event_type == "manager.prospective_seal" for e in events) == 1
