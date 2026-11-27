"""Regression tests for prospective review recovery and reporting."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import append_manager_event, thaw
from drift.manager.evidence_validity import CitationRow, citation_refusal
from drift.manager.models import (
    EvidenceItem,
    ExitCondition,
    IngestBatch,
    InvestmentProposal,
)
from drift.manager.service import PortfolioManager
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.collect import (
    Bar,
    Collection,
    Trade,
    build_packet,
    collect_live,
    new_items,
    sec_facts,
)
from drift.prospective.config import MODELS
from drift.prospective.config import pilot_instruments as instruments
from drift.prospective.config import pilot_mandate as mandate
from drift.prospective.run import (
    apply_proposal,
    execute_books,
    export_contexts,
    open_books,
    perform_daily,
    status_report,
)
from drift.research.universe import ORIGINAL_TRADING_SYMBOLS, RESEARCH_UNIVERSE


def collection(when: datetime) -> Collection:
    return Collection(
        collected_at=when,
        bars=(Bar("AAPL", when - timedelta(days=1), "100", "101", when),),
        filings=(),
        facts=(),
        headlines=(),
        benchmark_level=None,
        benchmark_kind="price_only_substitute",
        benchmark_limitation="fixture",
        benchmark_fetched_at=when,
        corporate_actions_received_at=when,
        gaps=(),
        sources=("fixture",),
    )


def test_pilot_research_instruments_cover_existing_discovery_universe() -> None:
    assert {item.symbol for item in instruments()} == {
        item.symbol for item in RESEARCH_UNIVERSE
    }
    assert set(ORIGINAL_TRADING_SYMBOLS) <= set(mandate().allowed_symbols)


def test_authorized_pilot_mandate_covers_13_with_original_limits() -> None:
    rules = mandate()
    assert set(rules.allowed_symbols) == {item.symbol for item in RESEARCH_UNIVERSE}
    assert len(rules.allowed_symbols) == 13
    assert rules.max_position_notional_fraction == "0.25"
    assert rules.min_cash_after == "2000"
    assert rules.fill_fee == "1"
    assert rules.fill_price_source == "post_decision_execution"


def test_prospective_companyfact_amendment_supersedes_same_period() -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    facts = sec_facts(
        "AAPL",
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                    "filed": "2026-11-01",
                                    "form": "10-Q",
                                    "val": 100,
                                    "accn": "0001-26-000001",
                                },
                                {
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                    "filed": "2026-11-02",
                                    "form": "10-Q/A",
                                    "val": 110,
                                    "accn": "0001-26-000002",
                                },
                            ]
                        }
                    }
                }
            }
        },
    )
    rows = [
        item
        for item in new_items(set(), replace(collection(when), facts=facts))
        if item.kind == "fundamental"
    ]
    assert len(rows) == 2
    assert all("period start 2026-07-01" in row.summary for row in rows)
    citations = [
        CitationRow(
            evidence_id=item.evidence_id,
            kind=item.kind,
            source_label=item.source_label,
            summary=item.summary,
            limitations=item.limitations,
            observed_at=item.observed_at,
            available_at=item.available_at,
            symbol=item.symbol,
        )
        for item in rows
    ]
    refusal = citation_refusal(
        citations[0], when, citations, policy="uniform_age", max_age_hours=1000
    )
    assert refusal is not None and refusal.startswith("superseded_evidence:")


def test_duplicate_companyfacts_do_not_hide_a_conflicting_value() -> None:
    row = {
        "start": "2025-01-01",
        "end": "2025-12-31",
        "filed": "2026-02-01",
        "form": "10-K",
        "val": 100,
        "accn": "one",
    }
    other = {**row, "val": 101, "accn": "two"}
    facts = sec_facts(
        "AAPL",
        {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [other, row, row]}}}}},
    )
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    rows = new_items(set(), replace(collection(when), facts=facts))
    assert not any(item.kind == "fundamental" for item in rows)
    assert any(item.source_label == "sec-companyfacts-dispute" for item in rows)


def test_later_companyfact_conflict_refuses_earlier_citation_only_after_receipt() -> (
    None
):
    from drift.prospective.collect import Fact, fact_disputes

    first = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    later = first + timedelta(hours=1)
    fact = Fact(
        "AAPL",
        "Revenues",
        "2025-12-31",
        "2026-02-01",
        "10-K",
        "100",
        "USD",
        "2025-01-01",
        "one",
    )
    old = next(
        item
        for item in new_items(set(), replace(collection(first), facts=(fact,)))
        if item.kind == "fundamental"
    )
    disputes = fact_disputes(
        (old,), replace(collection(later), facts=(replace(fact, value="101"),))
    )
    assert len(disputes) == 1

    def citation(item: EvidenceItem) -> CitationRow:
        return CitationRow(
            item.evidence_id,
            item.kind,
            item.source_label,
            item.summary,
            item.limitations,
            item.observed_at,
            item.available_at,
            item.symbol,
        )

    rows = tuple(citation(item) for item in (old, *disputes))
    assert (
        citation_refusal(rows[0], first, rows, policy="research", max_age_hours=1000)
        is None
    )
    refusal = citation_refusal(
        rows[0], later, rows, policy="research", max_age_hours=1000
    )
    assert refusal is not None and refusal.startswith("disputed_evidence:")


def test_legacy_prospective_fact_without_period_and_unit_is_not_citable() -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    old = CitationRow(
        evidence_id="sec:fact:AAPL:Revenues:2026-09-30:2026-11-01:0",
        kind="fundamental",
        source_label="sec-companyfacts-pilot",
        summary="Revenues 100 USD period end 2026-09-30 form 10-Q.",
        limitations=("period unavailable",),
        observed_at=when - timedelta(days=1),
        available_at=when - timedelta(days=1),
        symbol="AAPL",
    )
    reason = citation_refusal(
        old, when, (old,), policy="uniform_age", max_age_hours=336
    )
    assert reason is not None and reason.startswith("unsupported_evidence:")


def test_prospective_duration_fact_without_start_is_not_citable() -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    facts = sec_facts(
        "AAPL",
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "end": "2026-09-30",
                                    "filed": "2026-11-26",
                                    "form": "10-Q",
                                    "val": 100,
                                }
                            ]
                        }
                    }
                }
            }
        },
    )
    row = next(
        item
        for item in new_items(set(), replace(collection(when), facts=facts))
        if item.kind == "fundamental"
    )
    citation = CitationRow(
        evidence_id=row.evidence_id,
        kind=row.kind,
        source_label=row.source_label,
        summary=row.summary,
        limitations=row.limitations,
        observed_at=row.observed_at,
        available_at=row.available_at,
        symbol=row.symbol,
    )
    reason = citation_refusal(
        citation, when, (citation,), policy="uniform_age", max_age_hours=336
    )
    assert reason is not None and reason.startswith("unsupported_evidence:")


def test_live_collection_requests_each_research_symbol_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)

    def read_json(url: str, pinned: datetime | None) -> tuple[object, str, datetime]:
        del pinned
        seen.append(url)
        return None, "fixture gap", when

    def read_bytes(url: str, pinned: datetime | None) -> tuple[bytes, str, datetime]:
        del url, pinned
        return b"", "fixture gap", when

    monkeypatch.setattr("drift.prospective.collect._read_json", read_json)
    monkeypatch.setattr("drift.prospective.collect._read_bytes", read_bytes)
    monkeypatch.setattr("drift.prospective.collect.sleep", lambda _: None)
    monkeypatch.setattr(
        "drift.historical.sources.load_alpaca_bars",
        lambda *_, **__: (None, (), ("fixture gap",), "", frozenset()),
    )
    collect_live(when)
    for item in RESEARCH_UNIVERSE:
        assert any(f"CIK{item.cik}.json" in url for url in seen)


def test_daily_preserves_unanswered_review_receipts(tmp_path: Path) -> None:
    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    outcome = perform_daily(tmp_path, "observation", first, collection(first))
    assert outcome["counts_toward_observation"] is False
    assert outcome["status"] == "processed"
    assert (
        status_report(tmp_path, "observation", first)["counts_toward_observation"]
        is False
    )
    path = tmp_path / "observation" / "terra" / "receipt.json"
    receipt = path.read_text(encoding="utf-8")
    later = first + timedelta(minutes=5)
    perform_daily(tmp_path, "observation", later, collection(later))
    assert path.read_text(encoding="utf-8") == receipt


def test_review_context_is_bound_to_the_book_ledger(tmp_path: Path) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", when, collection(when))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "terra.sqlite"
    ).verified_events()
    reviews = [
        event for event in events if event.event_type == "manager.prospective_review"
    ]
    assert len(reviews) == 1
    payload = thaw(reviews[0].payload)
    assert payload["proposal_id"] == receipt["proposal_id"]
    assert payload["context"] == context


def test_review_refuses_a_clock_before_latest_ledger_event(tmp_path: Path) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    open_books(tmp_path, "observation", build_packet(collection(when), readiness=False))
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    item = EvidenceItem(
        evidence_id="later-news",
        kind="news",
        symbol="AAPL",
        observed_at=when,
        available_at=when + timedelta(minutes=10),
        limitations=("fixture",),
        summary="Fixture",
        source_label="fixture",
    )
    manager.ingest(IngestBatch(evidence=(item,)))
    with pytest.raises(ValueError, match="review clock"):
        export_contexts(tmp_path, "observation", when + timedelta(minutes=5))


def test_review_cannot_be_issued_outside_an_observation_session(tmp_path: Path) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    open_books(tmp_path, "observation", build_packet(collection(when), readiness=False))
    weekend = datetime(2026, 11, 28, 18, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="outside.*observation session"):
        export_contexts(tmp_path, "observation", weekend)


def test_review_recovers_after_crash_before_receipt_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    import drift.prospective.run as run

    original = run._atomic_write

    def interrupted(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "receipt.json" and path.parent.name == "terra":
            raise OSError("simulated receipt write interruption")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "_atomic_write", interrupted)
        with pytest.raises(OSError, match="interruption"):
            perform_daily(tmp_path, "observation", when, collection(when))
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    first = [
        e
        for e in ledger.verified_events()
        if e.event_type == "manager.prospective_review"
    ]
    assert len(first) == 1
    later = when + timedelta(minutes=5)
    perform_daily(tmp_path, "observation", later, collection(later))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["proposal_id"] == thaw(first[0].payload)["proposal_id"]
    assert receipt["as_of"] == when.isoformat()
    assert (
        len(
            [
                e
                for e in ledger.verified_events()
                if e.event_type == "manager.prospective_review"
            ]
        )
        == 1
    )


def test_cli_restores_committed_review_after_receipt_write_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    import drift.prospective.run as run

    original = run._atomic_write

    def interrupted(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "receipt.json" and path.parent.name == "terra":
            raise OSError("receipt interruption")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "_atomic_write", interrupted)
        with pytest.raises(OSError, match="interruption"):
            perform_daily(tmp_path, "observation", when, collection(when))
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    review = next(
        e
        for e in ledger.verified_events()
        if e.event_type == "manager.prospective_review"
    )
    from drift.prospective.run import _restore_review_files

    terra_folder = tmp_path / "observation" / "terra"
    _restore_review_files(terra_folder, "terra", review)
    terra_receipt = json.loads((terra_folder / "receipt.json").read_text())
    early_proposal = InvestmentProposal(
        proposal_id=UUID(terra_receipt["proposal_id"]),
        as_of=when,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture",
        evidence_ids=(),
        uncertainty="Fixture",
        allocation_reasoning="Cash",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    early_path = tmp_path / "early.json"
    early_path.write_text(early_proposal.model_dump_json())

    class EarlyClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return when + timedelta(seconds=30)

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", EarlyClock)
        with pytest.raises(ValueError, match="paired review"):
            apply_proposal(tmp_path, "observation", "terra", early_path)
    recovered_at = when + timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return recovered_at

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", Clock)
        patcher.setattr("drift.prospective.__main__.datetime", Clock)
        patcher.setattr(
            "drift.prospective.__main__.collect_live",
            lambda *_: pytest.fail("must not collect"),
        )
        result = _run(
            Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
        )
    assert result["status"] == "pending_reviews"
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text()
    )
    assert receipt["proposal_id"] == thaw(review.payload)["proposal_id"]
    assert receipt["as_of"] == review.timestamp.isoformat()
    assert (tmp_path / "observation" / "terra" / "prompt.txt").is_file()
    sol_receipt = json.loads(
        (tmp_path / "observation" / "sol" / "receipt.json").read_text()
    )
    assert sol_receipt["as_of"] == review.timestamp.isoformat()
    sol_events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "sol.sqlite"
    ).verified_events()
    sol_review = next(
        event
        for event in sol_events
        if event.event_type == "manager.prospective_review"
    )
    assert sol_review.timestamp == recovered_at
    assert thaw(sol_review.payload)["context_as_of"] == review.timestamp.isoformat()
    proposal = InvestmentProposal(
        proposal_id=UUID(sol_receipt["proposal_id"]),
        as_of=when,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture",
        evidence_ids=(),
        uncertainty="Fixture",
        allocation_reasoning="Cash",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["sol"],
    )
    proposal_path = tmp_path / "sol-recovered.json"
    proposal_path.write_text(proposal.model_dump_json())

    class SubmitClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return recovered_at + timedelta(seconds=1)

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", SubmitClock)
        accepted = apply_proposal(tmp_path, "observation", "sol", proposal_path)
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "sol.sqlite"
    ).verified_events()
    decision = next(event for event in events if event.event_type == "manager.decision")
    assert decision.timestamp == recovered_at + timedelta(seconds=1)


def test_next_readiness_review_preserves_original_model_input(tmp_path: Path) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "readiness", when, collection(when))
    folder = tmp_path / "readiness" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text())
    original_context = (folder / "context.json").read_bytes()
    original_prompt = (folder / "prompt.txt").read_bytes()
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=when,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture",
        evidence_ids=(),
        uncertainty="Fixture",
        allocation_reasoning="Cash",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json())
    apply_proposal(tmp_path, "readiness", "terra", path)
    export_contexts(tmp_path, "readiness", when + timedelta(minutes=1))
    archived = folder / "reviews" / receipt["proposal_id"]
    assert (archived / "context.json").read_bytes() == original_context
    assert (archived / "prompt.txt").read_bytes() == original_prompt


def test_day_two_recovers_review_before_refreshing_old_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    import drift.prospective.run as run
    from drift.prospective.__main__ import _run

    first = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    second = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))

    class FirstClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return first + timedelta(minutes=1)

    for name in MODELS:
        folder = tmp_path / "observation" / name
        receipt = json.loads((folder / "receipt.json").read_text())
        proposal = InvestmentProposal(
            proposal_id=UUID(receipt["proposal_id"]),
            as_of=first,
            action="hold",
            symbol="AAPL",
            quantity=0,
            thesis="Fixture",
            evidence_ids=(),
            uncertainty="Fixture",
            allocation_reasoning="Cash",
            exit_conditions=(),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS[name],
        )
        path = tmp_path / f"{name}.json"
        path.write_text(proposal.model_dump_json())
        with monkeypatch.context() as patcher:
            patcher.setattr(run, "datetime", FirstClock)
            apply_proposal(tmp_path, "observation", name, path)

    folder = tmp_path / "observation" / "terra"
    old_receipt = json.loads((folder / "receipt.json").read_text())
    old_archive = folder / "reviews" / old_receipt["proposal_id"] / "context.json"
    old_body = old_archive.read_bytes()
    receipt_path = folder / "receipt.json"
    original_receipt = receipt_path.read_bytes()
    context_path = folder / "context.json"
    original_context = context_path.read_bytes()
    sol_path = tmp_path / "observation" / "sol" / "receipt.json"
    sol_original = sol_path.read_bytes()
    sol_receipt = json.loads(sol_original)
    sol_path.write_text(json.dumps({**sol_receipt, "model_identity": "changed"}))
    with pytest.raises(ValueError, match="conflicts"):
        export_contexts(tmp_path, "observation", second)
    for name in MODELS:
        events = SQLiteLedger.open_existing(
            tmp_path / "observation" / f"{name}.sqlite"
        ).verified_events()
        assert sum(e.event_type == "manager.prospective_review" for e in events) == 1
    sol_path.write_bytes(sol_original)
    receipt_path.write_text(json.dumps({**old_receipt, "model_identity": "changed"}))
    with pytest.raises(ValueError, match="conflicts"):
        export_contexts(tmp_path, "observation", second)
    receipt_path.write_bytes(original_receipt)
    context_path.write_text(json.dumps({"changed": True}))
    with pytest.raises(ValueError, match="conflicts"):
        export_contexts(tmp_path, "observation", second)
    context_path.write_bytes(original_context)
    original_archive = run._archive_review

    def interrupted_archive(folder: Path, identifier: str, *args: Any) -> None:
        if folder.name == "terra" and identifier != old_receipt["proposal_id"]:
            raise OSError("interrupted")
        original_archive(folder, identifier, *args)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "_archive_review", interrupted_archive)
        with pytest.raises(OSError, match="interrupted"):
            perform_daily(tmp_path, "observation", second, collection(second))

    class SecondClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return second + timedelta(minutes=1)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "datetime", SecondClock)
        patcher.setattr("drift.prospective.__main__.datetime", SecondClock)
        patcher.setattr(
            "drift.prospective.__main__.collect_live",
            lambda *_: pytest.fail("must not collect"),
        )
        result = _run(
            Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
        )
    assert result["status"] == "pending_reviews"
    assert (
        json.loads((folder / "receipt.json").read_text())["proposal_id"]
        != old_receipt["proposal_id"]
    )
    assert old_archive.read_bytes() == old_body


def test_concurrent_daily_rejects_overlap_without_splitting_books(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import drift.prospective.run as run

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    entered, release = Event(), Event()
    original = run.open_books

    def pause(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(run, "open_books", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(
            perform_daily, tmp_path, "observation", when, collection(when)
        )
        assert entered.wait(5)
        try:
            with pytest.raises(ValueError, match="pilot.*busy"):
                perform_daily(tmp_path, "observation", when, collection(when))
        finally:
            release.set()
        assert future.result()["status"] == "processed"
    for name in MODELS:
        assert (tmp_path / "observation" / f"{name}.sqlite").is_file()


def test_expired_review_does_not_block_other_books_pending_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    friday = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(
        tmp_path,
        "observation",
        friday,
        replace(
            collection(friday),
            bars=(
                Bar(
                    "AAPL",
                    friday - timedelta(days=1),
                    "100",
                    "101",
                    friday,
                    "alpaca-bars-v2-iex-raw",
                    covered_until=friday,
                ),
            ),
        ),
    )
    root = tmp_path / "observation"
    terra_receipt = json.loads((root / "terra" / "receipt.json").read_text())
    sol_receipt = (root / "sol" / "receipt.json").read_bytes()
    context = json.loads((root / "terra" / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(terra_receipt["proposal_id"]),
        as_of=friday,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture",
        uncertainty="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "terra.json"
    path.write_text(proposal.model_dump_json())
    submitted = friday + timedelta(minutes=1)

    class SubmitClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return submitted

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", SubmitClock)
        assert isinstance(apply_proposal(tmp_path, "observation", "terra", path), dict)
    monday = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    market = replace(
        collection(monday),
        bars=(),
        trades=(
            Trade(
                "AAPL",
                monday,
                monday,
                "102",
                "alpaca-trades-v2-iex",
                f"alpaca-trades-v2-iex:AAPL:{monday.isoformat()}:V:1",
            ),
        ),
    )

    class MondayClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return monday

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.__main__.datetime", MondayClock)
        patcher.setattr(
            "drift.prospective.__main__.collect_live", lambda *_, **__: market
        )
        result = _run(
            Namespace(
                command="daily",
                role="observation",
                state=tmp_path,
                proposal=[],
                suggestions=None,
            )
        )
    assert result["status"] == "pending_reviews"
    assert (root / "sol" / "receipt.json").read_bytes() == sol_receipt
    terra = PortfolioManager.recover(root / "terra.sqlite").context(monday)
    assert isinstance(terra, dict) and isinstance(terra["book"], dict)
    assert terra["book"]["cash"] == "9897"
    from drift.prospective.run import resolve_expired_review

    sol_id = json.loads(sol_receipt)["proposal_id"]
    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", MondayClock)
        assert (
            resolve_expired_review(tmp_path, "sol", sol_id, "unanswered after cutoff")[
                "status"
            ]
            == "expired"
        )
    next_review = monday + timedelta(minutes=1)
    resumed = perform_daily(
        tmp_path,
        "observation",
        next_review,
        replace(market, collected_at=next_review, benchmark_fetched_at=next_review),
    )
    assert resumed["status"] == "processed"
    receipts = [
        json.loads((root / name / "receipt.json").read_text()) for name in MODELS
    ]
    assert all(item["as_of"] == next_review.isoformat() for item in receipts)
    assert (
        root / "sol" / "reviews" / sol_id / "receipt.json"
    ).read_bytes() == sol_receipt


@pytest.mark.parametrize("trade_before_baseline", [False, True])
@pytest.mark.parametrize("corrupt_baseline", [False, True])
def test_next_daily_requests_and_executes_timestamped_alpaca_trade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trade_before_baseline: bool,
    corrupt_baseline: bool,
) -> None:
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    issued = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    old = datetime(2026, 11, 25, 14, 30, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        old,
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )

    class SubmitClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return issued + timedelta(minutes=1)

    for name in MODELS:
        folder = tmp_path / "observation" / name
        receipt = json.loads((folder / "receipt.json").read_text())
        context = json.loads((folder / "context.json").read_text())
        buy = name == "terra"
        proposal = InvestmentProposal(
            proposal_id=UUID(receipt["proposal_id"]),
            as_of=issued,
            action="buy" if buy else "hold",
            symbol="AAPL",
            quantity=1 if buy else 0,
            thesis="Fixture",
            evidence_ids=(context["evidence"][0]["evidence_id"],) if buy else (),
            uncertainty="Fixture",
            allocation_reasoning="Fixture",
            exit_conditions=(ExitCondition(kind="price_below", threshold="90"),)
            if buy
            else (),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS[name],
        )
        path = tmp_path / f"{name}.json"
        path.write_text(proposal.model_dump_json())
        with monkeypatch.context() as patcher:
            patcher.setattr("drift.prospective.run.datetime", SubmitClock)
            result = apply_proposal(tmp_path, "observation", name, path)
            assert isinstance(result, dict) and result["status"] == "accepted"
    monday = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    observed = monday - timedelta(seconds=4 if trade_before_baseline else 2)
    baseline_stamp = (monday - timedelta(seconds=3)).isoformat()
    valid_baseline = f"alpaca:benchmark:alpaca-trades-v2-iex:SPY:{baseline_stamp}:V:3"
    market = replace(
        collection(monday),
        bars=(),
        trades=(
            Trade(
                "AAPL",
                observed,
                monday,
                "102",
                "alpaca-trades-v2-iex",
                f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:1",
            ),
            Trade(
                "SPY",
                monday - timedelta(seconds=3),
                monday - timedelta(seconds=1),
                "500",
                "alpaca-trades-v2-iex",
                (
                    f"alpaca:benchmark:alpaca-trades-v2-sip:AAPL:{baseline_stamp}:V:3"
                    if corrupt_baseline
                    else valid_baseline
                ),
            ),
        ),
    )
    calls: list[object] = []

    def collect(_: object, **kwargs: object) -> Collection:
        calls.append(kwargs)
        return market

    class MondayClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return monday

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.__main__.datetime", MondayClock)
        patcher.setattr("drift.prospective.__main__.collect_live", collect)
        daily_result = _run(
            Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
        )
    assert daily_result["status"] == "processed"
    assert calls == [
        {
            "preferred_feed": "iex",
            "trade_requests": (("AAPL", issued + timedelta(minutes=1)),),
            "benchmark_after": issued + timedelta(minutes=1),
        }
    ]
    context = PortfolioManager.recover(
        tmp_path / "observation" / "terra.sqlite"
    ).context(monday)
    assert isinstance(context, dict) and isinstance(context["book"], dict)
    assert context["book"]["cash"] == "9897"
    after_close = datetime(2026, 11, 30, 21, 10, tzinfo=UTC)
    closing_bars = tuple(
        Bar(
            symbol,
            monday,
            price,
            price,
            after_close,
            "alpaca-bars-v2-iex-raw",
            covered_until=after_close,
        )
        for symbol, price in (("AAPL", "103"), ("SPY", "510"))
    )
    perform_daily(
        tmp_path,
        "observation",
        after_close,
        replace(collection(after_close), bars=closing_bars),
        suppress_reviews=True,
    )
    report = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite").report(
        after_close
    )
    assert isinstance(report, dict)
    benchmark = report["price_return_benchmark"]
    assert isinstance(benchmark, dict)
    if trade_before_baseline or corrupt_baseline:
        assert benchmark["status"] == "unavailable"
    else:
        assert benchmark["status"] == "available"
        assert benchmark["series_change"] == "0.02"

        class LaterSubmitClock(datetime):
            @classmethod
            def now(cls, tz: object = None) -> Any:
                return after_close + timedelta(minutes=1)

        for name in MODELS:
            folder = tmp_path / "observation" / name
            receipt = json.loads((folder / "receipt.json").read_text())
            saved = json.loads((folder / "context.json").read_text())
            buy = name == "terra"
            proposal = InvestmentProposal(
                proposal_id=UUID(receipt["proposal_id"]),
                as_of=datetime.fromisoformat(receipt["as_of"]),
                action="buy" if buy else "hold",
                symbol="AAPL",
                quantity=1 if buy else 0,
                thesis="Fixture",
                evidence_ids=(saved["evidence"][0]["evidence_id"],) if buy else (),
                uncertainty="Fixture",
                allocation_reasoning="Fixture",
                exit_conditions=(ExitCondition(kind="price_below", threshold="90"),)
                if buy
                else (),
                execution="simulation",
                inference="native_supervised",
                model_identity=MODELS[name],
            )
            path = tmp_path / f"later-{name}.json"
            path.write_text(proposal.model_dump_json())
            with monkeypatch.context() as patcher:
                patcher.setattr("drift.prospective.run.datetime", LaterSubmitClock)
                accepted = apply_proposal(tmp_path, "observation", name, path)
            assert isinstance(accepted, dict) and accepted["status"] == "accepted"
        tuesday = datetime(2026, 12, 1, 16, tzinfo=UTC)
        later_observed = tuesday - timedelta(seconds=1)
        later_trade = Trade(
            "AAPL",
            later_observed,
            tuesday,
            "104",
            "alpaca-trades-v2-iex",
            f"alpaca-trades-v2-iex:AAPL:{later_observed.isoformat()}:V:2",
        )
        perform_daily(
            tmp_path,
            "observation",
            tuesday,
            replace(collection(tuesday), bars=(), trades=(later_trade,)),
            suppress_reviews=True,
        )
        after = PortfolioManager.recover(
            tmp_path / "observation" / "terra.sqlite"
        ).report(after_close)
        assert isinstance(after, dict) and after["price_return_benchmark"] == benchmark


def test_expired_unanswered_review_has_explicit_ledger_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.prospective.run import (
        pending_observation_reviews,
        resolve_expired_review,
    )

    friday = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", friday, collection(friday))
    root = tmp_path / "observation" / "sol"
    receipt = json.loads((root / "receipt.json").read_text())
    original = (root / "receipt.json").read_bytes()
    monday = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return monday

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = resolve_expired_review(
        tmp_path, "sol", receipt["proposal_id"], "unanswered after cutoff"
    )
    assert result == {"status": "expired", "proposal_id": receipt["proposal_id"]}
    assert "sol" not in pending_observation_reviews(tmp_path)
    assert (root / "receipt.json").read_bytes() == original
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "sol.sqlite")
    assert (
        sum(
            event.event_type == "manager.prospective_expired"
            for event in ledger.verified_events()
        )
        == 1
    )
    assert (
        resolve_expired_review(
            tmp_path, "sol", receipt["proposal_id"], "unanswered after cutoff"
        )["status"]
        == "already_expired"
    )


def test_review_resolution_refuses_before_cutoff_or_wrong_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hashlib import sha256

    from drift.prospective.run import resolve_expired_review

    friday = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", friday, collection(friday))
    receipt = json.loads(
        (tmp_path / "observation" / "sol" / "receipt.json").read_text()
    )
    ledger_path = tmp_path / "observation" / "sol.sqlite"
    before = sha256(ledger_path.read_bytes()).hexdigest()

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return friday + timedelta(minutes=5)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    with pytest.raises(ValueError, match="not passed"):
        resolve_expired_review(tmp_path, "sol", receipt["proposal_id"], "unanswered")
    with pytest.raises(ValueError, match="one saved review"):
        resolve_expired_review(
            tmp_path, "sol", str(deterministic_memory_uuid7("wrong")), "unanswered"
        )
    assert sha256(ledger_path.read_bytes()).hexdigest() == before


def test_review_recovers_partial_receipt_from_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    import drift.prospective.run as run

    original = run._atomic_write

    def interrupted(path: Path, data: str, **kwargs: Any) -> None:
        if path.name == "receipt.json" and path.parent.name == "terra":
            path.write_text("{", encoding="utf-8")
            raise OSError("partial receipt")
        return original(path, data, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "_atomic_write", interrupted)
        with pytest.raises(OSError, match="partial receipt"):
            perform_daily(tmp_path, "observation", when, collection(when))
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    review = next(
        e
        for e in ledger.verified_events()
        if e.event_type == "manager.prospective_review"
    )
    later = when + timedelta(minutes=5)
    perform_daily(tmp_path, "observation", later, collection(later))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["proposal_id"] == thaw(review.payload)["proposal_id"]


def test_submission_records_after_review_and_seals_after_durable_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    submitted = issued + timedelta(minutes=5)
    sealed = submitted + timedelta(seconds=1)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="No trade.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    clocks = iter((submitted - timedelta(seconds=1), submitted, sealed))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(clocks)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(result, dict) and result["status"] == "accepted"
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "terra.sqlite"
    ).verified_events()
    decision = next(event for event in events if event.event_type == "manager.decision")
    seal = next(
        event for event in events if event.event_type == "manager.prospective_seal"
    )
    assert decision.timestamp == submitted
    assert seal.timestamp == sealed
    assert events.index(decision) < events.index(seal)
    assert thaw(seal.payload)["proposal_id"] == receipt["proposal_id"]
    sol = PortfolioManager.recover(tmp_path / "observation" / "sol.sqlite").context(
        sealed
    )
    assert isinstance(sol, dict) and sol["decisions"] == []
    export_contexts(tmp_path, "observation", sealed + timedelta(seconds=1))
    new_receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert new_receipt["proposal_id"] == receipt["proposal_id"]
    duplicate = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(duplicate, dict) and duplicate["status"] == "duplicate"
    next_proposal = proposal.model_copy(
        update={
            "proposal_id": UUID(new_receipt["proposal_id"]),
            "as_of": datetime.fromisoformat(new_receipt["as_of"]),
        }
    )
    next_path = tmp_path / "next-proposal.json"
    next_path.write_text(next_proposal.model_dump_json(), encoding="utf-8")

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return sealed + timedelta(minutes=1)

    monkeypatch.setattr("drift.prospective.run.datetime", LaterClock)
    second_result = apply_proposal(tmp_path, "observation", "terra", next_path)
    assert isinstance(second_result, dict) and second_result["status"] == "duplicate"
    report = status_report(tmp_path, "observation", sealed + timedelta(minutes=2))
    assert report["trusted_decision_records"] == {"terra": 1, "sol": 0}
    assert report["observation_session_counts"] == {"terra": 1, "sol": 0}


def test_submission_refuses_changed_or_unseen_review_context(tmp_path: Path) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    context_path = folder / "context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture.",
        evidence_ids=("not-visible",),
        uncertainty="Fixture.",
        allocation_reasoning="One share.",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="outside the saved review"):
        apply_proposal(tmp_path, "observation", "terra", path)
    context["book"]["cash"] = "999999"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(ValueError, match="context does not match"):
        apply_proposal(tmp_path, "observation", "terra", path)


def test_daily_submits_using_wall_clock_and_keeps_books_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    times = iter(issued + timedelta(minutes=5, seconds=i) for i in range(3))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(times)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    now = issued + timedelta(minutes=5)
    accepted = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(accepted, dict) and accepted["status"] == "accepted"
    after = now + timedelta(seconds=3)
    result = perform_daily(tmp_path, "observation", after, collection(after))
    assert json.loads((folder / "receipt.json").read_text()) == receipt
    assert result["counts_toward_observation"] is False
    report = status_report(tmp_path, "observation", now + timedelta(seconds=5))
    assert report["counts_toward_observation"] is False
    assert report["completed_session_count"] == 0
    assert report["trusted_decision_records"] == {"terra": 1, "sol": 0}
    other = PortfolioManager.recover(tmp_path / "observation" / "sol.sqlite").context(
        now
    )
    assert isinstance(other, dict) and other["decisions"] == []


def test_submission_refuses_clock_behind_newly_ingested_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    calls = 0

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            nonlocal calls
            del tz
            calls += 1
            if calls == 2:
                later = issued + timedelta(minutes=4)
                item = EvidenceItem(
                    evidence_id="later-news",
                    kind="news",
                    symbol="AAPL",
                    observed_at=issued,
                    available_at=later,
                    limitations=("fixture",),
                    summary="Fixture",
                    source_label="fixture",
                )
                manager.ingest(IngestBatch(evidence=(item,)))
                return issued + timedelta(minutes=3)
            if calls > 2:
                return issued + timedelta(minutes=5)
            return issued + timedelta(minutes=2)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(result, dict) and result["status"] == "rejected"
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "terra.sqlite"
    ).verified_events()
    assert all(event.event_type != "manager.decision" for event in events)


def test_decision_without_same_session_commit_seal_remains_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 23, 58, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    clocks = iter(
        (
            issued + timedelta(seconds=10),
            issued + timedelta(seconds=20),
            issued + timedelta(minutes=2),
        )
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(clocks)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    with pytest.raises(ValueError, match="seal.*session"):
        apply_proposal(tmp_path, "observation", "terra", path)
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "terra.sqlite"
    ).verified_events()
    assert any(event.event_type == "manager.decision" for event in events)
    assert all(event.event_type != "manager.prospective_seal" for event in events)


def test_execution_ignores_print_before_seal_and_uses_later_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    submitted = issued + timedelta(minutes=5)
    sealed = submitted + timedelta(seconds=2)
    perform_daily(
        tmp_path,
        "observation",
        issued,
        replace(
            collection(issued),
            bars=(
                Bar(
                    "AAPL",
                    issued - timedelta(days=1),
                    "100",
                    "101",
                    issued,
                    "alpaca-bars-v2-iex-raw",
                    covered_until=issued,
                ),
            ),
        ),
    )
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture buy.",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture.",
        allocation_reasoning="One share.",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    proposal_path = tmp_path / "buy.json"
    proposal_path.write_text(proposal.model_dump_json(), encoding="utf-8")
    clocks = iter((submitted - timedelta(seconds=1), submitted, sealed))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(clocks)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    result = apply_proposal(tmp_path, "observation", "terra", proposal_path)
    assert isinstance(result, dict) and result["status"] == "accepted"
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")

    def trade(identifier: str, observed: datetime, available: datetime) -> EvidenceItem:
        trade_id = 1 if identifier == "before-seal" else 2
        return EvidenceItem(
            evidence_id=f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:{trade_id}",
            kind="observation",
            symbol="AAPL",
            observed_at=observed,
            available_at=available,
            limitations=("fixture",),
            summary="Fixture trade",
            source_label="alpaca-trades-v2-iex",
            price="100",
            price_role="trade",
        )

    first_time = sealed + timedelta(minutes=1)
    manager.ingest(
        IngestBatch(
            evidence=(
                trade("before-seal", submitted + timedelta(seconds=1), first_time),
            )
        )
    )
    from drift.prospective.run import _record_corporate_action_status

    _record_corporate_action_status(
        tmp_path / "observation", first_time, "complete", coverage_at=first_time
    )
    first = execute_books(tmp_path, "observation", first_time)["terra"]
    assert isinstance(first, dict) and first["status"] == "pending"
    second_time = first_time + timedelta(minutes=1)
    manager.ingest(
        IngestBatch(
            evidence=(
                trade("after-seal", first_time + timedelta(seconds=1), second_time),
            )
        )
    )
    _record_corporate_action_status(
        tmp_path / "observation", second_time, "complete", coverage_at=second_time
    )
    second = execute_books(tmp_path, "observation", second_time)["terra"]
    assert isinstance(second, dict) and second["status"] == "filled"
    results = second["results"]
    assert isinstance(results, list) and isinstance(results[0], dict)
    fill = results[0]["fill"]
    expected_time = (first_time + timedelta(seconds=1)).isoformat()
    assert isinstance(fill, dict) and fill["price_evidence_id"] == (
        f"alpaca-trades-v2-iex:AAPL:{expected_time}:V:2"
    )


def test_two_books_trade_new_authorized_symbol_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    pg = Bar(
        "PG",
        issued - timedelta(days=1),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(pg,))
    )
    times = iter(issued + timedelta(minutes=5, seconds=i) for i in range(6))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(times)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    for name, quantity in (("terra", 1), ("sol", 2)):
        folder = tmp_path / "observation" / name
        receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        context = json.loads((folder / "context.json").read_text(encoding="utf-8"))
        proposal = InvestmentProposal(
            proposal_id=UUID(receipt["proposal_id"]),
            as_of=issued,
            action="buy",
            symbol="PG",
            quantity=quantity,
            thesis="Fixture.",
            evidence_ids=(context["evidence"][0]["evidence_id"],),
            uncertainty="Fixture.",
            allocation_reasoning="Within limits.",
            exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS[name],
        )
        path = tmp_path / f"{name}.json"
        path.write_text(proposal.model_dump_json(), encoding="utf-8")
        result = apply_proposal(tmp_path, "observation", name, path)
        assert isinstance(result, dict) and result["status"] == "accepted"
    observed = issued + timedelta(minutes=6)
    paired = status_report(tmp_path, "observation", observed)
    assert paired["paired_recorded_session_count"] == 1
    assert paired["completed_session_count"] is None
    assert paired["model_identity_verification"] == "not_verified"
    available = observed + timedelta(minutes=1)
    trade = EvidenceItem(
        evidence_id=f"alpaca-trades-v2-iex:PG:{observed.isoformat()}:V:1",
        kind="observation",
        symbol="PG",
        observed_at=observed,
        available_at=available,
        limitations=("fixture",),
        summary="Fixture trade",
        source_label="alpaca-trades-v2-iex",
        price="100",
        price_role="trade",
    )
    for name in MODELS:
        manager = PortfolioManager.recover(tmp_path / "observation" / f"{name}.sqlite")
        assert isinstance(manager.ingest(IngestBatch(evidence=(trade,))), dict)
    from drift.prospective.run import _record_corporate_action_status

    _record_corporate_action_status(
        tmp_path / "observation", available, "complete", coverage_at=available
    )
    results = execute_books(tmp_path, "observation", available)
    for name, cash in (("terra", "9899"), ("sol", "9799")):
        result = results[name]
        assert isinstance(result, dict) and result["status"] == "filled"
        book = PortfolioManager.recover(
            tmp_path / "observation" / f"{name}.sqlite"
        ).context(available)
        assert isinstance(book, dict) and isinstance(book["book"], dict)
        assert book["book"]["cash"] == cash
    terra = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    legacy = proposal.model_copy(
        update={
            "proposal_id": deterministic_memory_uuid7("legacy-after-seal"),
            "as_of": available + timedelta(minutes=1),
            "action": "hold",
            "quantity": 0,
            "evidence_ids": (),
            "exit_conditions": (),
            "model_identity": MODELS["terra"],
        }
    )
    legacy_result = terra.propose(legacy)
    assert isinstance(legacy_result, dict) and legacy_result["status"] == "accepted"
    mixed = execute_books(tmp_path, "observation", available + timedelta(minutes=2))
    assert mixed["terra"] == "untrusted_decision_time"


def test_duplicate_recovers_decision_after_interrupted_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.prospective import run

    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    clocks = iter(issued + timedelta(minutes=5, seconds=second) for second in range(4))

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return next(clocks)

    monkeypatch.setattr(run, "datetime", Clock)
    original = append_manager_event

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("event_type") == "manager.prospective_seal":
            raise OSError("seal interruption")
        return original(*args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "append_manager_event", interrupted)
        with pytest.raises(OSError, match="seal interruption"):
            apply_proposal(tmp_path, "observation", "terra", path)
    export_contexts(tmp_path, "observation", issued + timedelta(minutes=6))
    assert json.loads((folder / "receipt.json").read_text(encoding="utf-8")) == receipt
    recovered = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(recovered, dict) and recovered["status"] == "duplicate"
    repeated = apply_proposal(tmp_path, "observation", "terra", path)
    assert isinstance(repeated, dict) and repeated["status"] == "duplicate"
    events = SQLiteLedger.open_existing(
        tmp_path / "observation" / "terra.sqlite"
    ).verified_events()
    assert sum(event.event_type == "manager.decision" for event in events) == 1
    assert sum(event.event_type == "manager.prospective_seal" for event in events) == 1


def test_expired_interrupted_submission_has_terminal_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.prospective import run

    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture",
        evidence_ids=(),
        uncertainty="Fixture",
        allocation_reasoning="Cash",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json())

    class BeforeCutoff(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return issued + timedelta(minutes=5)

    original = append_manager_event

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("event_type") == "manager.prospective_seal":
            raise OSError("interrupted")
        return original(*args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "datetime", BeforeCutoff)
        patcher.setattr(run, "append_manager_event", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            apply_proposal(tmp_path, "observation", "terra", path)

    class AfterCutoff(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return datetime(2026, 11, 30, 15, 0, tzinfo=UTC)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "datetime", AfterCutoff)
        result = run.resolve_expired_review(
            tmp_path, "terra", receipt["proposal_id"], "seal interrupted"
        )
    assert result["status"] == "expired"
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    events = ledger.verified_events()
    assert sum(e.event_type == "manager.decision" for e in events) == 1
    assert not any(e.event_type == "manager.prospective_seal" for e in events)
    assert receipt["proposal_id"] in run._expired_review_ids(events)
    assert not run._has_untrusted_decisions(
        events, run._execution_barriers(ledger, AfterCutoff.now())
    )
    context = PortfolioManager.recover(ledger.path).context(AfterCutoff.now())
    assert isinstance(context, dict) and isinstance(context["decisions"], list)
    first_decision = context["decisions"][0]
    assert isinstance(first_decision, dict) and first_decision["status"] == "expired"
    from drift.manager.service import _outcomes

    outcome_id = f"outcome:{receipt['proposal_id']}"
    assert outcome_id in _outcomes(events, issued + timedelta(minutes=6))
    assert outcome_id not in _outcomes(events, AfterCutoff.now())


def test_recovers_after_interruption_between_opening_books(tmp_path: Path) -> None:
    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    root = tmp_path / "observation"
    root.mkdir()
    packet = build_packet(collection(first), readiness=False)
    PortfolioManager.open(root / "terra.sqlite", packet, mandate())
    later = first + timedelta(minutes=5)
    result = perform_daily(tmp_path, "observation", later, collection(later))
    assert result["opened"] == {"terra": "already_open", "sol": "opened"}
    assert PortfolioManager.recover(root / "sol.sqlite").context(later) is not None


def test_collection_ingests_each_actual_availability_time(tmp_path: Path) -> None:
    from drift.manager.book import packet_through
    from drift.prospective.collect import Filing
    from drift.prospective.run import ingest_new

    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))
    price_at = first + timedelta(minutes=1)
    filing_at = first + timedelta(minutes=2)
    batch_at = first + timedelta(minutes=3)
    bar = Bar("AAPL", first - timedelta(days=2), "100", "101", price_at)
    filing = Filing(
        "AAPL",
        "8-K",
        "0000320193-26-999999",
        first - timedelta(days=1),
        fetched_at=filing_at,
    )
    batch = replace(
        collection(batch_at), bars=(bar,), filings=(filing,), benchmark_level="100"
    )
    result = ingest_new(tmp_path, "observation", batch)
    assert result["ingested"] == {"terra": "ingested", "sol": "ingested"}
    packets = []
    for name in MODELS:
        ledger = SQLiteLedger.open_existing(tmp_path / "observation" / f"{name}.sqlite")
        packet = packet_through(ledger.verified_events())
        packets.append(packet)
        ids = {item.evidence_id: item.available_at for item in packet.evidence}
        assert ids["yahoo:AAPL:close:2026-11-25"] == price_at
        assert ids["sec:filing:0000320193-26-999999"] == filing_at
        assert packet.benchmark[-1].available_at == batch_at
    assert packets[0] == packets[1]


def test_daily_recovers_interrupted_shared_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.manager.book import packet_through
    from drift.prospective.run import ingest_new

    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))
    later = first + timedelta(minutes=1)
    bar = Bar("AAPL", first - timedelta(days=2), "100", "101", later)
    update = replace(collection(later), bars=(bar,))
    original = PortfolioManager.ingest
    calls = 0

    def interrupted(manager: PortfolioManager, batch: IngestBatch) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interruption between books")
        return original(manager, batch)

    with monkeypatch.context() as patcher:
        patcher.setattr(PortfolioManager, "ingest", interrupted)
        with pytest.raises(OSError, match="interruption"):
            ingest_new(tmp_path, "observation", update)
    from argparse import Namespace

    from drift.prospective.__main__ import _run

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "drift.prospective.__main__.collect_live",
            lambda *_: pytest.fail("must not collect"),
        )
        pending = _run(
            Namespace(command="daily", role="observation", state=tmp_path, proposal=[])
        )
    assert pending["status"] == "pending_reviews"
    for name in MODELS:
        ledger = SQLiteLedger.open_existing(tmp_path / "observation" / f"{name}.sqlite")
        assert any(
            event.event_type == "manager.ingest" for event in ledger.verified_events()
        )
    recovered = perform_daily(tmp_path, "observation", later, update)
    assert recovered["status"] == "processed"
    packets = []
    for name in MODELS:
        ledger = SQLiteLedger.open_existing(tmp_path / "observation" / f"{name}.sqlite")
        packets.append(packet_through(ledger.verified_events()))
    assert packets[0] == packets[1]


def test_conflicting_ingest_histories_are_not_reconciled(tmp_path: Path) -> None:
    from hashlib import sha256

    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))
    later = first + timedelta(minutes=1)
    for name in MODELS:
        item = EvidenceItem(
            evidence_id=f"different-{name}",
            kind="news",
            symbol="AAPL",
            observed_at=later,
            available_at=later,
            limitations=("fixture",),
            summary=f"{name} input",
            source_label="fixture",
        )
        manager = PortfolioManager.recover(tmp_path / "observation" / f"{name}.sqlite")
        assert isinstance(manager.ingest(IngestBatch(evidence=(item,))), dict)
    paths = [tmp_path / "observation" / f"{name}.sqlite" for name in MODELS]
    before = [sha256(path.read_bytes()).hexdigest() for path in paths]
    with pytest.raises(ValueError, match="incompatible source evidence"):
        perform_daily(tmp_path, "observation", later, collection(later))
    assert before == [sha256(path.read_bytes()).hexdigest() for path in paths]


def test_refuses_existing_books_with_legacy_mandate_before_mutation(
    tmp_path: Path,
) -> None:
    from hashlib import sha256

    from drift.prospective.config import mandate as legacy_mandate

    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    packet = build_packet(collection(when), readiness=False)
    root = tmp_path / "observation"
    root.mkdir()
    for name in MODELS:
        PortfolioManager.open(root / f"{name}.sqlite", packet, legacy_mandate())
    before = {
        name: sha256((root / f"{name}.sqlite").read_bytes()).hexdigest()
        for name in MODELS
    }
    with pytest.raises(ValueError, match="incompatible"):
        perform_daily(tmp_path, "observation", when, collection(when))
    assert before == {
        name: sha256((root / f"{name}.sqlite").read_bytes()).hexdigest()
        for name in MODELS
    }


def test_unverified_legacy_pending_observation_trades_are_not_executed(
    tmp_path: Path,
) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", when, collection(when))
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    context = manager.context(when)
    assert isinstance(context, dict)
    evidence = context["evidence"]
    assert isinstance(evidence, list)
    row = evidence[0]
    assert isinstance(row, dict)
    evidence_id = row["evidence_id"]
    assert isinstance(evidence_id, str)
    decision_time = when + timedelta(minutes=1)
    proposal = InvestmentProposal(
        proposal_id=deterministic_memory_uuid7("legacy-pending-test"),
        as_of=decision_time,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Test a pending simulated trade.",
        evidence_ids=(evidence_id,),
        uncertainty="Fixture only.",
        allocation_reasoning="One share.",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    recorded = manager.propose(proposal)
    assert isinstance(recorded, dict) and recorded["status"] == "accepted"
    later = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    trade = Trade(
        "AAPL",
        datetime(2026, 11, 30, 14, 30, tzinfo=UTC),
        later,
        "100",
        "fixture",
        "fixture-trade",
    )
    later_collection = collection(later)
    items = new_items(
        {str(item["evidence_id"]) for item in evidence if isinstance(item, dict)},
        replace(later_collection, bars=(), trades=(trade,)),
    )
    ingested = manager.ingest(IngestBatch(evidence=items))
    assert isinstance(ingested, dict) and ingested["status"] == "ingested"
    direct = manager.execute_pending(later)
    assert isinstance(direct, dict) and direct["status"] == "untrusted_decision_time"
    assert execute_books(tmp_path, "observation", later) == {
        "terra": "untrusted_decision_time",
        "sol": "untrusted_decision_time",
    }
    book = manager.context(later)
    assert isinstance(book, dict) and isinstance(book["book"], dict)
    assert book["book"]["cash"] == "10000"


@pytest.mark.parametrize("late_booking", [False, True])
def test_split_after_fill_blocks_valuation_until_adjusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_booking: bool
) -> None:
    issued = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    perform_daily(
        tmp_path,
        "observation",
        issued,
        replace(
            collection(issued),
            bars=(
                Bar(
                    "AAPL",
                    issued - timedelta(days=1),
                    "100",
                    "101",
                    issued,
                    "alpaca-bars-v2-iex-raw",
                    covered_until=issued,
                ),
            ),
        ),
    )
    root = tmp_path / "observation" / "terra"
    receipt = json.loads((root / "receipt.json").read_text())
    context = json.loads((root / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="80"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "buy.json"
    path.write_text(proposal.model_dump_json())
    submitted = issued + timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return submitted

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", Clock)
        apply_proposal(tmp_path, "observation", "terra", path)
    observed_time = issued + timedelta(minutes=2)
    fill_time = (
        datetime(2026, 11, 30, 16, 0, tzinfo=UTC) if late_booking else observed_time
    )
    initial_trade = EvidenceItem(
        evidence_id=f"alpaca-trades-v2-iex:AAPL:{observed_time.isoformat()}:V:1",
        kind="observation",
        symbol="AAPL",
        observed_at=observed_time,
        available_at=fill_time,
        limitations=("fixture",),
        summary="Trade 100",
        source_label="alpaca-trades-v2-iex",
        price="100",
        price_role="trade",
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    manager.ingest(IngestBatch(evidence=(initial_trade,)))
    from drift.prospective.run import _record_corporate_action_status

    _record_corporate_action_status(
        tmp_path / "observation", fill_time, "complete", coverage_at=fill_time
    )
    filled = execute_books(tmp_path, "observation", fill_time)["terra"]
    assert isinstance(filled, dict) and filled["status"] == "filled"
    monday = datetime(2026, 11, 30, 20, 0, tzinfo=UTC)
    split = EvidenceItem(
        evidence_id="alpaca:split:AAPL:2026-11-30",
        kind="news",
        symbol="AAPL",
        observed_at=monday,
        available_at=monday,
        limitations=("fixture",),
        summary="forward_split AAPL ex_date 2026-11-30",
        source_label="alpaca-corporate-action",
    )
    close = EvidenceItem(
        evidence_id="post-split-close",
        kind="observation",
        symbol="AAPL",
        observed_at=monday,
        available_at=monday,
        limitations=("fixture",),
        summary="Close 50",
        source_label="alpaca-trades-v2-iex",
        price="50",
        price_role="close",
    )
    manager.ingest(IngestBatch(evidence=(split, close)))
    _record_corporate_action_status(
        tmp_path / "observation", monday, "complete", coverage_at=monday
    )
    marked = manager.mark(monday)
    assert isinstance(marked, dict) and marked["status"] == "rejected"
    report = manager.report(monday)
    assert isinstance(report, dict) and report["net_asset_value"] is None
    assert isinstance(report["observed_drawdown"], dict)
    assert report["observed_drawdown"]["maximum"] is None


def test_pending_buy_is_not_filled_after_a_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text())
    context = json.loads((folder / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="80"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "buy.json"
    path.write_text(proposal.model_dump_json())
    submitted = issued + timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return submitted

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", Clock)
        apply_proposal(tmp_path, "observation", "terra", path)
    monday = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    split = EvidenceItem(
        evidence_id="alpaca:split:AAPL:2026-11-30",
        kind="news",
        symbol="AAPL",
        observed_at=monday,
        available_at=monday,
        limitations=("fixture",),
        summary="forward_split AAPL ex_date 2026-11-30",
        source_label="alpaca-corporate-action",
    )
    trade = EvidenceItem(
        evidence_id="post-split-trade",
        kind="observation",
        symbol="AAPL",
        observed_at=monday,
        available_at=monday,
        limitations=("fixture",),
        summary="Trade 50",
        source_label="fixture",
        price="50",
        price_role="trade",
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    manager.ingest(IngestBatch(evidence=(split, trade)))
    from drift.prospective.run import _record_corporate_action_status

    _record_corporate_action_status(
        tmp_path / "observation", monday, "complete", coverage_at=monday
    )
    result = manager.execute_pending(monday)
    assert isinstance(result, dict) and result["status"] == "pending"
    book = manager.context(monday)
    assert isinstance(book, dict) and isinstance(book["book"], dict)
    assert book["book"]["cash"] == "10000"


def test_corporate_action_outage_blocks_direct_manager_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    folder = tmp_path / "observation" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text())
    context = json.loads((folder / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="80"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "buy.json"
    path.write_text(proposal.model_dump_json())
    submitted = issued + timedelta(minutes=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return submitted

    with monkeypatch.context() as patcher:
        patcher.setattr("drift.prospective.run.datetime", Clock)
        apply_proposal(tmp_path, "observation", "terra", path)
    observed = issued + timedelta(minutes=2)
    trade = EvidenceItem(
        evidence_id="eligible-trade",
        kind="observation",
        symbol="AAPL",
        observed_at=observed,
        available_at=observed,
        limitations=("fixture",),
        summary="Trade 100",
        source_label="fixture",
        price="100",
        price_role="trade",
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    manager.ingest(IngestBatch(evidence=(trade,)))
    outage = observed + timedelta(minutes=1)
    outcome = perform_daily(
        tmp_path,
        "observation",
        outage,
        replace(collection(outage), corporate_actions_complete=False),
    )
    assert outcome["status"] == "corporate_actions_unavailable"
    direct = manager.execute_pending(outage)
    assert (
        isinstance(direct, dict) and direct["status"] == "corporate_actions_unavailable"
    )
    book = manager.context(outage)
    assert isinstance(book, dict) and isinstance(book["book"], dict)
    assert book["book"]["cash"] == "10000"


def test_interrupted_corporate_action_gap_blocks_both_books_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.manager.book import append_manager_event as original
    from drift.prospective import run

    first = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))
    outage = first + timedelta(minutes=1)
    calls = 0

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        if kwargs.get("event_type") == "manager.prospective_corporate_action_status":
            calls += 1
            if calls == 2:
                raise OSError("coverage interruption")
        return original(*args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "append_manager_event", interrupted)
        with pytest.raises(OSError, match="coverage interruption"):
            perform_daily(
                tmp_path,
                "observation",
                outage,
                replace(collection(outage), corporate_actions_complete=False),
            )
    for name in MODELS:
        manager = PortfolioManager.recover(tmp_path / "observation" / f"{name}.sqlite")
        result = manager.execute_pending(outage)
        assert (
            isinstance(result, dict)
            and result["status"] == "corporate_actions_unavailable"
        )
    run.recover_shared_inputs(tmp_path, "observation")
    for name in MODELS:
        ledger = SQLiteLedger.open_existing(tmp_path / "observation" / f"{name}.sqlite")
        last = [
            event
            for event in ledger.verified_events()
            if event.event_type == "manager.prospective_corporate_action_status"
        ][-1]
        assert thaw(last.payload)["status"] == "unavailable"
        assert thaw(last.payload)["coverage_at"] is None
    run.recover_shared_inputs(tmp_path, "observation")


def test_new_submission_refuses_a_book_with_unreconciled_legacy_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text(
            encoding="utf-8"
        )
    )
    proposed = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="Fixture.",
        evidence_ids=(),
        uncertainty="Fixture.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    legacy = proposed.model_copy(
        update={
            "proposal_id": deterministic_memory_uuid7("unreconciled-legacy"),
            "as_of": issued + timedelta(minutes=1),
        }
    )
    result = manager.propose(legacy)
    assert isinstance(result, dict) and result["status"] == "accepted"
    path = tmp_path / "proposal.json"
    path.write_text(proposed.model_dump_json(), encoding="utf-8")

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return issued + timedelta(minutes=5)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    with pytest.raises(ValueError, match="unreconciled legacy"):
        apply_proposal(tmp_path, "observation", "terra", path)


def test_status_reports_each_books_decisions_not_maximum(tmp_path: Path) -> None:
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "readiness", when, collection(when))
    receipt = json.loads(
        (tmp_path / "readiness" / "terra" / "receipt.json").read_text(encoding="utf-8")
    )
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=when,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="No trade.",
        evidence_ids=(),
        uncertainty="No evidence.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    apply_proposal(tmp_path, "readiness", "terra", path)
    report = status_report(tmp_path, "readiness", when)
    assert report["decision_records"] == {"terra": 1, "sol": 0}


def test_observation_submission_refuses_wall_clock_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    perform_daily(tmp_path, "observation", issued, collection(issued))
    receipt = json.loads(
        (tmp_path / "observation" / "terra" / "receipt.json").read_text()
    )
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="hold",
        symbol="AAPL",
        quantity=0,
        thesis="No trade.",
        evidence_ids=(),
        uncertainty="No evidence.",
        allocation_reasoning="Cash.",
        exit_conditions=(),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "proposal.json"
    path.write_text(proposal.model_dump_json(), encoding="utf-8")
    submitted = issued + timedelta(minutes=5)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            del tz
            return issued - timedelta(minutes=1)

    monkeypatch.setattr("drift.prospective.run.datetime", Clock)
    with pytest.raises(ValueError, match="before the saved review"):
        apply_proposal(tmp_path, "observation", "terra", path)
    with pytest.raises(ValueError, match="before collecting"):
        perform_daily(
            tmp_path, "observation", submitted, collection(submitted), {"terra": path}
        )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    context = manager.context(submitted)
    assert isinstance(context, dict)
    assert context["decisions"] == []


def test_full_companyfacts_detect_conflict_with_an_older_stored_group() -> None:
    from drift.prospective.collect import Fact, fact_disputes

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    old = Fact(
        "AAPL",
        "Revenues",
        "2023-12-31",
        "2024-02-01",
        "10-K",
        "100",
        "USD",
        "2023-01-01",
        "old",
    )
    prior = tuple(
        i
        for i in new_items(set(), replace(collection(when), facts=(old,)))
        if i.kind == "fundamental"
    )
    rows = [
        {
            "start": f"{year}-01-01",
            "end": f"{year}-12-31",
            "filed": f"{year + 1}-02-01",
            "form": "10-K",
            "val": value,
            "accn": str(year),
        }
        for year, value in ((2023, 200), (2024, 300), (2025, 400))
    ]
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    current = replace(
        collection(when + timedelta(minutes=1)),
        facts=sec_facts("AAPL", payload),
        dispute_facts=sec_facts("AAPL", payload, full=True),
    )
    assert len(current.facts) == 2
    assert fact_disputes(prior, current)


def test_settlement_requires_regular_timestamped_trade_on_pinned_feed() -> None:
    from drift.manager.service import _next_trade_observation

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        when - timedelta(days=2),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    bad = Trade("AAPL", when, when, "100", "alpaca-bars-v2-iex-raw", "fake-bar-trade")
    packet = build_packet(
        replace(collection(when), bars=(bar,), trades=(bad,)), readiness=False
    )
    assert (
        _next_trade_observation(
            packet,
            mandate(),
            symbol="AAPL",
            decision_at=when - timedelta(minutes=1),
            as_of=when,
            used=set(),
        )
        is None
    )
    valid = Trade(
        "AAPL",
        when,
        when,
        "100",
        "alpaca-trades-v2-iex",
        f"alpaca-trades-v2-iex:AAPL:{when.isoformat()}:V:123",
    )
    packet = build_packet(
        replace(collection(when), bars=(bar,), trades=(valid,)), readiness=False
    )
    assert (
        _next_trade_observation(
            packet,
            mandate(),
            symbol="AAPL",
            decision_at=when - timedelta(minutes=1),
            as_of=when,
            used=set(),
        )
        is not None
    )
    alias = valid.source_id.replace("+00:00", "Z")
    assert (
        _next_trade_observation(
            packet,
            mandate(),
            symbol="AAPL",
            decision_at=when - timedelta(minutes=1),
            as_of=when,
            used={alias},
        )
        is None
    )


@pytest.mark.parametrize(
    "issued",
    [datetime(2026, 11, 27, 16, tzinfo=UTC), datetime(2026, 11, 24, 16, tzinfo=UTC)],
)
def test_readiness_exercises_trade_settlement_without_observation_seal(
    tmp_path: Path,
    issued: datetime,
) -> None:
    initial = replace(
        collection(issued),
        bars=(
            Bar(
                "AAPL",
                issued - timedelta(days=2),
                "100",
                "101",
                issued,
                "alpaca-bars-v2-iex-raw",
                covered_until=issued,
            ),
        ),
    )
    perform_daily(tmp_path, "readiness", issued, initial)
    folder = tmp_path / "readiness" / "terra"
    receipt = json.loads((folder / "receipt.json").read_text())
    context = json.loads((folder / "context.json").read_text())
    proposal = InvestmentProposal(
        proposal_id=UUID(receipt["proposal_id"]),
        as_of=issued,
        action="buy",
        symbol="AAPL",
        quantity=1,
        thesis="Fixture",
        evidence_ids=(context["evidence"][0]["evidence_id"],),
        uncertainty="Fixture",
        allocation_reasoning="Fixture",
        exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
        execution="simulation",
        inference="native_supervised",
        model_identity=MODELS["terra"],
    )
    path = tmp_path / "readiness-proposal.json"
    path.write_text(proposal.model_dump_json())
    assert isinstance(apply_proposal(tmp_path, "readiness", "terra", path), dict)
    observed = issued + timedelta(minutes=1)
    available = observed + timedelta(seconds=1)
    trade = Trade(
        "AAPL",
        observed,
        available,
        "102",
        "alpaca-trades-v2-iex",
        f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:1",
    )
    result = perform_daily(
        tmp_path,
        "readiness",
        available,
        replace(collection(available), bars=(), trades=(trade,)),
    )
    assert result["counts_toward_observation"] is False
    fills = result["fills"]
    assert isinstance(fills, dict)
    filled = fills["terra"]
    assert isinstance(filled, dict) and filled["status"] == "filled"
    from drift.prospective.config import session_close_utc

    after_close = session_close_utc(issued.date()) + timedelta(minutes=10)
    close = Bar(
        "AAPL",
        issued,
        "102",
        "103",
        after_close,
        "alpaca-bars-v2-iex-raw",
        covered_until=after_close,
    )
    result = perform_daily(
        tmp_path,
        "readiness",
        after_close,
        replace(collection(after_close), bars=(close,)),
    )
    marks = result["marks"]
    assert isinstance(marks, dict)
    marked = marks["terra"]
    assert isinstance(marked, dict) and marked["status"] == "marked"


def test_direct_pilot_open_honors_state_lock(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from drift.prospective.locking import pilot_lock

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    packet = build_packet(collection(when), readiness=False)
    with pilot_lock(tmp_path), ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            PortfolioManager.open,
            tmp_path / "observation" / "terra.sqlite",
            packet,
            mandate(),
        )
        with pytest.raises(ValueError, match="busy"):
            result.result()
    assert not (tmp_path / "observation" / "terra.sqlite").exists()


def test_coverage_uses_provider_receipt_not_batch_timestamp(tmp_path: Path) -> None:
    from drift.manager.service import _pilot_coverage_available
    from drift.prospective.run import _record_corporate_action_status

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    perform_daily(tmp_path, "observation", when, collection(when))
    receipt = when + timedelta(seconds=1)
    trade_receipt = when + timedelta(seconds=2)
    batch = when + timedelta(seconds=3)
    _record_corporate_action_status(
        tmp_path / "observation", batch, "complete", coverage_at=receipt
    )
    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    assert not _pilot_coverage_available(ledger, batch, required_at=trade_receipt)


@pytest.mark.parametrize("source, final", [("iex", False), ("sip", True)])
def test_pilot_mark_rejects_preclose_and_other_feed(source: str, final: bool) -> None:
    from drift.manager.service import _close_observation

    when = datetime(2026, 11, 27, 16, 0, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        when - timedelta(days=2),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    opening = build_packet(replace(collection(when), bars=(bar,)), readiness=False)
    observed = when.replace(hour=18) if final else when
    partial = EvidenceItem(
        evidence_id=f"alpaca-bars-v2-{source}-raw:AAPL:close:2026-11-27",
        kind="observation",
        symbol="AAPL",
        observed_at=observed,
        available_at=observed,
        source_label=f"alpaca-bars-v2-{source}-raw",
        price="150",
        price_role="close",
        summary="partial close",
        limitations=("fixture",),
    )
    packet = opening.model_copy(update={"evidence": (*opening.evidence, partial)})
    result = _close_observation(
        packet,
        mandate(),
        "AAPL",
        as_of=when.replace(hour=18, minute=1),
        session_open=when.replace(hour=14, minute=30),
        session_close=when.replace(hour=23, minute=59),
        opening_packet=opening,
    )
    assert isinstance(result, str) and "no close" in result


def test_trade_invalidation_prevents_stale_execution_from_its_receipt() -> None:
    from drift.manager.service import _next_trade_observation
    from drift.prospective.collect import TradeInvalidation

    when = datetime(2026, 11, 27, 16, tzinfo=UTC)
    observed = when + timedelta(seconds=1)
    receipt = observed + timedelta(seconds=1)
    canceled = receipt + timedelta(seconds=1)
    ident = f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:1"
    bar = Bar(
        "AAPL",
        when - timedelta(days=2),
        "100",
        "101",
        when,
        "alpaca-bars-v2-iex-raw",
        covered_until=when,
    )
    trade = Trade("AAPL", observed, receipt, "140", "alpaca-trades-v2-iex", ident)
    notice = TradeInvalidation("AAPL", ident, canceled, "canceled")
    packet = build_packet(
        replace(
            collection(canceled),
            bars=(bar,),
            trades=(trade,),
            trade_invalidations=(notice,),
        ),
        readiness=False,
    )
    citations = tuple(
        CitationRow(
            item.evidence_id,
            item.kind,
            item.source_label,
            item.summary,
            item.limitations,
            item.observed_at,
            item.available_at,
            item.symbol,
        )
        for item in packet.evidence
    )
    trade_row = next(item for item in citations if item.evidence_id == ident)
    assert (
        citation_refusal(
            trade_row, receipt, citations, policy="research", max_age_hours=336
        )
        is None
    )
    reason = citation_refusal(
        trade_row, canceled, citations, policy="research", max_age_hours=336
    )
    assert reason is not None and reason.startswith("withdrawn_evidence:")
    notice_row = next(
        item for item in citations if item.source_label == "alpaca-trade-invalidation"
    )
    notice_reason = citation_refusal(
        notice_row, canceled, citations, policy="research", max_age_hours=336
    )
    assert notice_reason is not None and notice_reason.startswith(
        "unsupported_evidence:"
    )
    assert (
        _next_trade_observation(
            packet,
            mandate(),
            symbol="AAPL",
            decision_at=when,
            as_of=receipt,
            used=set(),
        )
        is not None
    )
    assert (
        _next_trade_observation(
            packet,
            mandate(),
            symbol="AAPL",
            decision_at=when,
            as_of=canceled,
            used=set(),
        )
        is None
    )


def test_pilot_benchmark_rejects_intraday_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = datetime(2026, 11, 27, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        issued - timedelta(days=2),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return issued + timedelta(minutes=1)

    for name in MODELS:
        receipt = json.loads(
            (tmp_path / "observation" / name / "receipt.json").read_text()
        )
        proposal = InvestmentProposal(
            proposal_id=UUID(receipt["proposal_id"]),
            as_of=issued,
            action="hold",
            symbol="SPY",
            quantity=0,
            thesis="Fixture",
            evidence_ids=(),
            uncertainty="Fixture",
            allocation_reasoning="Cash",
            exit_conditions=(),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS[name],
        )
        path = tmp_path / f"{name}.json"
        path.write_text(proposal.model_dump_json())
        with monkeypatch.context() as patcher:
            patcher.setattr("drift.prospective.run.datetime", Clock)
            apply_proposal(tmp_path, "observation", name, path)
    observed = issued + timedelta(minutes=2)
    available = issued + timedelta(minutes=3)
    baseline_id = (
        f"alpaca:benchmark:alpaca-trades-v2-iex:SPY:{observed.isoformat()}:V:1"
    )
    baseline = EvidenceItem(
        evidence_id=baseline_id,
        kind="observation",
        symbol="SPY",
        observed_at=observed,
        available_at=available,
        source_label="alpaca-trades-v2-iex",
        price="500",
        price_role="trade",
        summary="baseline",
        limitations=("fixture",),
    )
    fake = EvidenceItem(
        evidence_id="alpaca-bars-v2-iex-raw:SPY:close:2026-11-27",
        kind="observation",
        symbol="SPY",
        observed_at=available,
        available_at=available,
        source_label="alpaca-bars-v2-iex-raw",
        price="510",
        price_role="close",
        summary="intraday",
        limitations=("fixture",),
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    manager.ingest(IngestBatch(evidence=(baseline, fake)))
    report = manager.report(available)
    assert isinstance(report, dict) and isinstance(
        report["price_return_benchmark"], dict
    )
    assert report["price_return_benchmark"]["status"] == "unavailable"


def test_canceled_trade_after_interrupted_ingest_cannot_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.prospective.collect import TradeInvalidation
    from drift.prospective.run import ingest_new

    issued = datetime(2026, 11, 27, 16, tzinfo=UTC)
    bar = Bar(
        "AAPL",
        issued - timedelta(days=2),
        "100",
        "101",
        issued,
        "alpaca-bars-v2-iex-raw",
        covered_until=issued,
    )
    perform_daily(
        tmp_path, "observation", issued, replace(collection(issued), bars=(bar,))
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> Any:
            return issued + timedelta(minutes=1)

    for name in MODELS:
        folder = tmp_path / "observation" / name
        receipt = json.loads((folder / "receipt.json").read_text())
        context = json.loads((folder / "context.json").read_text())
        buy = name == "terra"
        proposal = InvestmentProposal(
            proposal_id=UUID(receipt["proposal_id"]),
            as_of=issued,
            action="buy" if buy else "hold",
            symbol="AAPL",
            quantity=1 if buy else 0,
            thesis="Fixture",
            evidence_ids=(context["evidence"][0]["evidence_id"],) if buy else (),
            uncertainty="Fixture",
            allocation_reasoning="Fixture",
            exit_conditions=(ExitCondition(kind="price_below", threshold="90"),)
            if buy
            else (),
            execution="simulation",
            inference="native_supervised",
            model_identity=MODELS[name],
        )
        path = tmp_path / f"{name}.json"
        path.write_text(proposal.model_dump_json())
        with monkeypatch.context() as patcher:
            patcher.setattr("drift.prospective.run.datetime", Clock)
            apply_proposal(tmp_path, "observation", name, path)
    first_at = issued + timedelta(minutes=2)
    observed = first_at - timedelta(seconds=1)
    old_id = f"alpaca-trades-v2-iex:AAPL:{observed.isoformat()}:V:1"
    old = Trade("AAPL", observed, first_at, "140", "alpaca-trades-v2-iex", old_id)
    ingest_new(
        tmp_path, "observation", replace(collection(first_at), bars=(), trades=(old,))
    )
    later = first_at + timedelta(minutes=1)
    corrected_at = observed + timedelta(seconds=1)
    corrected = Trade(
        "AAPL",
        corrected_at,
        later,
        "101",
        "alpaca-trades-v2-iex",
        f"alpaca-trades-v2-iex:AAPL:{corrected_at.isoformat()}:V:2",
        "corrected",
    )
    notice = TradeInvalidation("AAPL", old_id, later, "canceled")
    outage_result = perform_daily(
        tmp_path,
        "observation",
        later,
        replace(
            collection(later),
            bars=(),
            trades=(corrected,),
            trade_invalidations=(notice,),
            corporate_actions_complete=False,
        ),
        suppress_reviews=True,
    )
    assert outage_result["status"] == "corporate_actions_unavailable"
    healthy = later + timedelta(minutes=1)
    corrected = replace(corrected, received_at=healthy)
    result = perform_daily(
        tmp_path,
        "observation",
        healthy,
        replace(collection(healthy), bars=(), trades=(corrected,)),
        suppress_reviews=True,
    )
    fills = result["fills"]
    assert isinstance(fills, dict)
    terra = fills["terra"]
    assert isinstance(terra, dict) and terra["status"] == "filled"
    assert terra["results"][0]["fill"]["fill_price"] == "101"
    canceled_at = healthy + timedelta(minutes=1)
    second_notice = TradeInvalidation(
        "AAPL", corrected.source_id, canceled_at, "canceled"
    )
    from drift.prospective import run

    original_ingest = PortfolioManager.ingest
    calls = 0

    def interrupt_second(manager: PortfolioManager, batch: IngestBatch) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("notice interruption")
        return original_ingest(manager, batch)

    notice_batch = replace(
        collection(canceled_at), bars=(), trade_invalidations=(second_notice,)
    )
    with monkeypatch.context() as patcher:
        patcher.setattr(PortfolioManager, "ingest", interrupt_second)
        with pytest.raises(OSError, match="notice interruption"):
            ingest_new(tmp_path, "observation", notice_batch)
    for name in MODELS:
        manager = PortfolioManager.recover(tmp_path / "observation" / f"{name}.sqlite")
        interim = manager.report(canceled_at)
        assert isinstance(interim, dict) and interim["net_asset_value"] is None
        assert interim["valuation_reason"] == "books disagree on trade invalidations"
        earlier = manager.report(healthy)
        assert isinstance(earlier, dict)
        assert earlier["valuation_reason"] != "books disagree on trade invalidations"
    run.recover_shared_inputs(tmp_path, "observation")
    perform_daily(
        tmp_path,
        "observation",
        canceled_at,
        notice_batch,
        suppress_reviews=True,
    )
    manager = PortfolioManager.recover(tmp_path / "observation" / "terra.sqlite")
    report = manager.report(canceled_at)
    assert isinstance(report, dict) and report["net_asset_value"] is None
    assert report["valuation_reason"] == "an executed trade was later invalidated"
    context = manager.context(canceled_at)
    assert isinstance(context, dict) and isinstance(context["book"], dict)
    assert context["book"]["net_asset_value"] is None
    assert isinstance(context["decisions"], list)
    assert context["decisions"][0]["status"] == "invalidated"
    assert context["decisions"][0]["fill"] is None
    from drift.manager.models import ReflectionRequest
    from drift.manager.service import _outcomes

    proposal_id = UUID(context["decisions"][0]["outcome_id"].removeprefix("outcome:"))
    reflected = manager.reflect(
        ReflectionRequest(
            reflection_id=deterministic_memory_uuid7("invalidated-reflection"),
            proposal_id=proposal_id,
            as_of=canceled_at,
            observation_evidence_id=corrected.source_id,
            note="Fixture",
        )
    )
    assert isinstance(reflected, dict) and reflected["status"] == "rejected"
    reasons = reflected["reasons"]
    assert isinstance(reasons, list) and "invalidated_evidence" in reasons

    ledger = SQLiteLedger.open_existing(tmp_path / "observation" / "terra.sqlite")
    assert not _outcomes(ledger.verified_events(), canceled_at)


def test_interrupted_complete_coverage_recovers_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drift.prospective import run

    first = datetime(2026, 11, 27, 16, tzinfo=UTC)
    perform_daily(tmp_path, "observation", first, collection(first))
    batch = first + timedelta(minutes=2)
    coverage = batch - timedelta(seconds=3)
    original = append_manager_event
    calls = 0

    def interrupt(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        if kwargs.get("event_type") == "manager.prospective_corporate_action_status":
            calls += 1
            if calls == 2:
                raise OSError("coverage interruption")
        return original(*args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(run, "append_manager_event", interrupt)
        with pytest.raises(OSError, match="interruption"):
            perform_daily(
                tmp_path,
                "observation",
                batch,
                replace(collection(batch), corporate_actions_received_at=coverage),
                suppress_reviews=True,
            )
    run.recover_shared_inputs(tmp_path, "observation")
    for name in MODELS:
        events = SQLiteLedger.open_existing(
            tmp_path / "observation" / f"{name}.sqlite"
        ).verified_events()
        latest = [
            e
            for e in events
            if e.event_type == "manager.prospective_corporate_action_status"
        ][-1]
        assert thaw(latest.payload) == {
            "status": "complete",
            "coverage_at": coverage.isoformat(),
        }
    run.recover_shared_inputs(tmp_path, "observation")


def test_unavailable_coverage_refuses_a_claimed_receipt(tmp_path: Path) -> None:
    from drift.prospective.run import _record_corporate_action_status

    when = datetime(2026, 11, 27, 16, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot carry a receipt"):
        _record_corporate_action_status(tmp_path, when, "unavailable", coverage_at=when)
