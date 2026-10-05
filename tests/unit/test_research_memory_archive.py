"""Unit tests for ResearchMemoryArchive query and retrieval engine (M6-4)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

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
POSTMORTEM_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd05")
POSTMORTEM_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd06")


def test_archive_empty_ledger(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "archive.sqlite3")
    archive = ResearchMemoryArchive(ledger)

    assert archive.get_trial_count() == 0
    assert archive.get_trial_count(HYPOTHESIS_ID_1) == 0
    assert archive.get_trial_sharpe_distribution() == []
    assert archive.find_falsified_hypotheses() == []
    assert archive.get_postmortems_by_category(FailureCategory.DRAWDOWN_BREACH) == []
    assert not archive.is_parameter_region_evaluated("b4_momentum", "0" * 64)
    assert archive.get_trials() == []
    assert archive.get_postmortems() == []


def test_archive_trial_metrics_and_parameter_lookup(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "archive.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    trial_1 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd11"),
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        headline_metrics={"sharpe_ratio": "1.50"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )
    trial_2 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd12"),
        hypothesis_id=HYPOTHESIS_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 40},
        headline_metrics={"sharpe_ratio": "-0.20"},
        trial_outcome=TrialOutcome.INFERIOR,
        created_at=TIMESTAMP,
    )
    trial_3 = build_research_trial_record(
        trial_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd13"),
        hypothesis_id=HYPOTHESIS_ID_2,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        strategy_type="b5_mean_reversion",
        parameters={"window": 10},
        headline_metrics={"sharpe_ratio": "2.10"},
        trial_outcome=TrialOutcome.SUPERIOR,
        created_at=TIMESTAMP,
    )

    recorder.record_trial(trial_1)
    recorder.record_trial(trial_2)
    recorder.record_trial(trial_3)

    archive = ResearchMemoryArchive(ledger)

    # Global trial count K
    assert archive.get_trial_count() == 3
    # Scoped trial count
    assert archive.get_trial_count(HYPOTHESIS_ID_1) == 2
    assert archive.get_trial_count(HYPOTHESIS_ID_2) == 1

    # Sharpe distributions
    assert archive.get_trial_sharpe_distribution() == [
        Decimal("1.50"),
        Decimal("-0.20"),
        Decimal("2.10"),
    ]
    assert archive.get_trial_sharpe_distribution(HYPOTHESIS_ID_1) == [
        Decimal("1.50"),
        Decimal("-0.20"),
    ]

    # Parameter evaluation lookup
    assert archive.is_parameter_region_evaluated("b4_momentum", trial_1.parameters_hash)
    assert archive.is_parameter_region_evaluated(
        "b5_mean_reversion", trial_3.parameters_hash
    )
    assert not archive.is_parameter_region_evaluated("b4_momentum", "unknown_hash")
    assert not archive.is_parameter_region_evaluated(
        "b0_passive", trial_1.parameters_hash
    )


def test_archive_falsified_hypotheses_and_postmortems(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "archive.sqlite3")
    recorder = ResearchMemoryRecorder(ledger)

    # Hypotheses
    lc_1 = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_1,
        status=HypothesisStatus.FALSIFIED,
        falsification_evidence=("a" * 64,),
        falsified_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    lc_2 = build_hypothesis_lifecycle(
        hypothesis_id=HYPOTHESIS_ID_2,
        status=HypothesisStatus.ACTIVE,
        updated_at=TIMESTAMP,
    )
    recorder.record_hypothesis_state(lc_1)
    recorder.record_hypothesis_state(lc_2)

    # Postmortems
    pm_1 = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_1,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.DRAWDOWN_BREACH,
        root_cause_summary="Drawdown breach",
        lessons_learned="Add stop loss",
        created_at=TIMESTAMP,
    )
    pm_2 = build_failure_postmortem(
        postmortem_id=POSTMORTEM_ID_2,
        experiment_id=EXPERIMENT_ID_1,
        run_id=RUN_ID_1,
        failure_category=FailureCategory.TURNOVER_DRAG,
        root_cause_summary="Turnover drag",
        lessons_learned="Reduce rebalance freq",
        created_at=TIMESTAMP,
    )
    recorder.record_postmortem(pm_1)
    recorder.record_postmortem(pm_2)

    archive = ResearchMemoryArchive(ledger)

    # Falsified hypotheses
    falsified = archive.find_falsified_hypotheses()
    assert len(falsified) == 1
    assert falsified[0].hypothesis_id == HYPOTHESIS_ID_1

    # Postmortems by category
    dd_pms = archive.get_postmortems_by_category(FailureCategory.DRAWDOWN_BREACH)
    assert len(dd_pms) == 1
    assert dd_pms[0].postmortem_id == POSTMORTEM_ID_1

    turnover_pms = archive.get_postmortems_by_category(FailureCategory.TURNOVER_DRAG)
    assert len(turnover_pms) == 1
    assert turnover_pms[0].postmortem_id == POSTMORTEM_ID_2

    assert archive.get_postmortems_by_category(FailureCategory.NEGATIVE_ALPHA) == []
    assert len(archive.get_postmortems()) == 2
