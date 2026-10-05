"""Unit tests for research context synthesis engine (M7-2, Issue 219)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.agent.context import ResearchContextSynthesizer
from drift.domain.research_agent import ResearchAgentRole
from drift.domain.research_memory import (
    FailureCategory,
    HypothesisStatus,
    TrialOutcome,
    build_failure_postmortem,
    build_hypothesis_lifecycle,
    build_research_trial_record,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.memory.archive import ResearchMemoryArchive
from drift.memory.recorder import ResearchMemoryRecorder

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
HYPOTHESIS_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
HYPOTHESIS_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EXPERIMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
RUN_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")


def test_empty_archive_context_synthesis(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)

    packet = synthesizer.synthesize_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        as_of_time=TIMESTAMP,
    )

    assert packet.total_trial_count == 0
    assert packet.median_sharpe_ratio is None
    assert packet.max_sharpe_ratio is None
    assert packet.active_hypotheses_count == 0
    assert packet.falsified_hypotheses_count == 0
    assert len(packet.falsified_hypothesis_summaries) == 0
    assert len(packet.forbidden_variations) == 0
    assert len(packet.context_hash) == 64


def test_odd_and_even_sharpe_distribution_median(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    # Record 3 trials (odd)
    sharpes = [Decimal("0.50"), Decimal("1.20"), Decimal("0.80")]
    for i, s in enumerate(sharpes):
        t = build_research_trial_record(
            trial_id=UUID(f"018f3a5b-6c7d-7890-8123-456789abcd{i:02x}"),
            hypothesis_id=HYPOTHESIS_ID_1,
            experiment_id=EXPERIMENT_ID_1,
            run_id=RUN_ID_1,
            strategy_type="b4_momentum",
            parameters={"lookback": 10 + i},
            headline_metrics={"sharpe_ratio": str(s)},
            trial_outcome=TrialOutcome.SUPERIOR,
            created_at=TIMESTAMP,
        )
        recorder.record_trial(t)

    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)

    packet_odd = synthesizer.synthesize_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        as_of_time=TIMESTAMP,
    )

    # Sorted: 0.50, 0.80, 1.20 -> median = 0.80, max = 1.20
    assert packet_odd.total_trial_count == 3
    assert packet_odd.median_sharpe_ratio == Decimal("0.80")
    assert packet_odd.max_sharpe_ratio == Decimal("1.20")

    # Add 4th trial (even)
    t4 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd03"),
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 40},
        headline_metrics={"sharpe_ratio": "1.00"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    recorder.record_trial(t4)
    archive.refresh()

    packet_even = synthesizer.synthesize_packet(
        agent_role=ResearchAgentRole.ALPHA_RESEARCHER,
        as_of_time=TIMESTAMP,
    )

    # Sorted: 0.50, 0.80, 1.00, 1.20 -> median = (0.80 + 1.00) / 2 = 0.90
    assert packet_even.total_trial_count == 4
    assert packet_even.median_sharpe_ratio == Decimal("0.90")
    assert packet_even.max_sharpe_ratio == Decimal("1.20")


def test_falsified_hypotheses_and_forbidden_variations_context(
    tmp_path: Path,
) -> None:
    ledger = SQLiteLedger(tmp_path / "research.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    # Record active hypothesis
    h_active = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.ACTIVE,
        updated_at=TIMESTAMP,
        notes="Active momentum hypothesis",
    )
    recorder.record_hypothesis_state(h_active)

    # Record falsified hypothesis
    h_falsified = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_2,
        status=HypothesisStatus.FALSIFIED,
        falsified_at=TIMESTAMP,
        falsification_evidence=("f" * 64,),
        updated_at=TIMESTAMP,
        notes="Falsified high turnover hypothesis",
    )
    recorder.record_hypothesis_state(h_falsified)

    # Record postmortem with forbidden variation
    pm = build_failure_postmortem(
        postmortem_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd05"),
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Turnover drag exceeded alpha",
        lessons_learned="Reduce rebalance frequency",
        created_at=TIMESTAMP,
        forbidden_variations=("unhedged daily rebalance",),
    )
    recorder.record_postmortem(pm)

    archive = ResearchMemoryArchive(ledger)
    synthesizer = ResearchContextSynthesizer(archive)

    packet = synthesizer.synthesize_packet(
        agent_role=ResearchAgentRole.RISK_CRITIC,
        as_of_time=TIMESTAMP,
    )

    assert packet.agent_role == ResearchAgentRole.RISK_CRITIC
    assert packet.active_hypotheses_count == 1
    assert packet.falsified_hypotheses_count == 1
    assert len(packet.falsified_hypothesis_summaries) == 1
    assert (
        "Falsified high turnover hypothesis" in packet.falsified_hypothesis_summaries[0]
    )
    assert "unhedged daily rebalance" in packet.forbidden_variations
