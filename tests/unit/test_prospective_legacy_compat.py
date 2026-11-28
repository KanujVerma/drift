"""Synthetic v0.2 observation records remain readable and cannot execute unsealed."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_prospective_pilot_safety import collection

from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import replay
from drift.manager.models import (
    CENT_BASIS_ALLOCATION,
    EvidenceItem,
    ExitCondition,
    IngestBatch,
    InvestmentProposal,
    ResearchPacket,
)
from drift.manager.service import PortfolioManager
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.config import MODELS, instruments, mandate
from drift.prospective.run import (
    apply_proposal,
    execute_books,
    export_contexts,
    ingest_new,
    perform_daily,
    status_report,
)
from drift.prospective.window import configure_window


def original_books(tmp_path: Path) -> datetime:
    """Match 1fb56cc6's four instruments, old calendar, mandate and basis policy."""
    when = datetime(2026, 11, 27, 18, 10, tzinfo=UTC)
    # Captured from synthetic input with original commit 1fb56cc6; no live records.
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures/prospective-v02/original-packet.json"
    )
    packet = ResearchPacket.model_validate_json(fixture.read_text())
    root = tmp_path / "observation"
    root.mkdir()
    # The old public manager path emitted decisions without reviews or seals.
    for name, identity in MODELS.items():
        staging = tmp_path / f"staging-{name}.sqlite"
        manager, _ = PortfolioManager.open(staging, packet, mandate())
        decision = when + timedelta(minutes=1)
        proposal = InvestmentProposal(
            proposal_id=deterministic_memory_uuid7(f"old-original-{name}"),
            as_of=decision,
            action="buy",
            symbol="AAPL",
            quantity=1,
            thesis="Synthetic legacy decision",
            evidence_ids=(packet.evidence[0].evidence_id,),
            uncertainty="Fixture",
            allocation_reasoning="One share",
            exit_conditions=(ExitCondition(kind="price_below", threshold="90"),),
            execution="simulation",
            inference="native_supervised",
            model_identity=identity,
        )
        accepted = manager.propose(proposal)
        assert isinstance(accepted, dict) and accepted["status"] == "accepted"
        trade_at = when + timedelta(minutes=2)
        trade = EvidenceItem(
            evidence_id="legacy-synthetic-trade",
            kind="observation",
            symbol="AAPL",
            observed_at=trade_at,
            available_at=trade_at,
            limitations=("synthetic",),
            summary="Synthetic trade",
            source_label="fixture",
            price="100",
            price_role="trade",
        )
        manager.ingest(IngestBatch(evidence=(trade,)))
        if name == "sol":
            filled = manager.execute_pending(when + timedelta(minutes=3))
            assert isinstance(filled, dict) and filled["status"] == "filled"
        staging.rename(root / f"{name}.sqlite")
    return when


def test_original_books_are_readable_and_do_not_advance_unsealed_decisions(
    tmp_path: Path,
) -> None:
    when = original_books(tmp_path)
    root = tmp_path / "observation"
    paths = [root / f"{name}.sqlite" for name in MODELS]
    before = [sha256(path.read_bytes()).hexdigest() for path in paths]
    ledger = SQLiteLedger.open_existing(root / "terra.sqlite")
    events = ledger.verified_events()
    packet, rules, *_ = replay(events)
    assert packet.instruments == instruments() and rules == mandate()
    assert (
        len(packet.sessions) == 25
        and str(packet.sessions[0].local_date) == "2026-11-27"
    )
    assert CENT_BASIS_ALLOCATION not in packet.limitations
    assert any(event.event_type == "manager.decision" for event in events)
    assert all(event.event_type != "manager.prospective_seal" for event in events)
    report: Any = status_report(tmp_path, "observation", when + timedelta(minutes=3))
    assert set(report["reports"]) == {"terra", "sol"}
    assert report["reports"]["sol"]["cash"] == "9899"
    assert report["decision_records"]["terra"] == 1
    assert report["trusted_decision_records"]["terra"] == 0
    assert report["legacy_read_only_books"] == ["terra", "sol"]
    manager = PortfolioManager.recover(root / "terra.sqlite")
    with pytest.raises(ValueError, match="legacy.*read.only"):
        manager.execute_pending(when + timedelta(minutes=3))
    with pytest.raises(ValueError, match="legacy.*read.only"):
        manager.ingest(IngestBatch(evidence=(packet.evidence[0],)))
    with pytest.raises(ValueError, match="legacy.*read.only"):
        manager.mark(when + timedelta(minutes=3))
    with pytest.raises(ValueError, match="legacy.*read.only"):
        export_contexts(tmp_path, "observation", when + timedelta(minutes=3))
    with pytest.raises(ValueError, match="legacy.*read.only"):
        ingest_new(tmp_path, "observation", collection(when + timedelta(minutes=3)))
    with pytest.raises(ValueError, match="legacy.*read.only"):
        apply_proposal(tmp_path, "observation", "terra", tmp_path / "missing.json")
    assert (
        execute_books(tmp_path, "observation", when + timedelta(minutes=3))["terra"]
        == "untrusted_decision_time"
    )
    with pytest.raises(ValueError, match="existing observation books"):
        configure_window(tmp_path)
    with pytest.raises(ValueError, match="legacy.*read.only"):
        perform_daily(
            tmp_path,
            "observation",
            when + timedelta(minutes=3),
            collection(when + timedelta(minutes=3)),
        )
    assert before == [sha256(path.read_bytes()).hexdigest() for path in paths]
