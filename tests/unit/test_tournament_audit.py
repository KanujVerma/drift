"""Unit tests for tournament audit events, recorder, and archive (M10-4)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.domain.tournament import (
    TournamentDecision,
    build_tournament_config,
    build_tournament_match_record,
    build_tournament_participant,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.evaluator_adapter import DeterministicMockTrialEvaluator
from drift.tournament.archive import TournamentArchive
from drift.tournament.recorder import TournamentRecorder
from drift.tournament.runner import TournamentRunner

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
TOURNAMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
MATCH_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
MATCH_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
CHAMP_ID_0 = UUID("018f3a5b-6c7d-7890-8123-456789abcd10")
CHALL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd11")
CHALL_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd12")


def test_record_match_and_query_archive(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "tournament_audit.sqlite3")
    recorder = TournamentRecorder(ledger)
    archive = TournamentArchive(ledger)

    assert archive.total_matches_count == 0

    c0 = build_tournament_participant(
        participant_id=CHAMP_ID_0,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        is_incumbent_champion=True,
    )
    c1 = build_tournament_participant(
        participant_id=CHALL_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 40},
        is_incumbent_champion=False,
    )

    match = build_tournament_match_record(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        champion=c0,
        challenger=c1,
        champion_sharpe=Decimal("1.10"),
        challenger_sharpe=Decimal("1.45"),
        delta_sharpe=Decimal("0.35"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.07"),
        turnover_ratio=Decimal("1.10"),
        paired_t_stat=Decimal("3.20"),
        p_value=Decimal("0.001"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    recorder.record_match(match)
    recorder.record_promotion(match)

    archive.refresh()
    assert archive.total_matches_count == 1
    assert archive.promotions_count == 1

    stored_match = archive.get_match(MATCH_ID_1)
    assert stored_match == match

    all_matches = archive.list_matches(TOURNAMENT_ID_1)
    assert len(all_matches) == 1
    assert all_matches[0] == match


def test_track_champion_succession_lineage(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "tournament_succession.sqlite3")
    recorder = TournamentRecorder(ledger)
    archive = TournamentArchive(ledger)

    # 1. C0 is initial champion, C1 defeats C0
    c0 = build_tournament_participant(
        participant_id=CHAMP_ID_0,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        is_incumbent_champion=True,
    )
    c1 = build_tournament_participant(
        participant_id=CHALL_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 40},
        is_incumbent_champion=False,
    )

    m1 = build_tournament_match_record(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        champion=c0,
        challenger=c1,
        champion_sharpe=Decimal("1.00"),
        challenger_sharpe=Decimal("1.40"),
        delta_sharpe=Decimal("0.40"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.08"),
        turnover_ratio=Decimal("1.10"),
        paired_t_stat=Decimal("3.50"),
        p_value=Decimal("0.0005"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )
    recorder.record_match(m1)
    recorder.record_promotion(m1)

    # 2. C1 is now champion, C2 defeats C1
    c1_incumbent = build_tournament_participant(
        participant_id=CHALL_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 40},
        is_incumbent_champion=True,
    )
    c2 = build_tournament_participant(
        participant_id=CHALL_ID_2,
        strategy_type="b4_momentum",
        parameters={"lookback": 60},
        is_incumbent_champion=False,
    )

    m2 = build_tournament_match_record(
        match_id=MATCH_ID_2,
        tournament_id=TOURNAMENT_ID_1,
        champion=c1_incumbent,
        challenger=c2,
        champion_sharpe=Decimal("1.40"),
        challenger_sharpe=Decimal("1.80"),
        delta_sharpe=Decimal("0.40"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.06"),
        turnover_ratio=Decimal("1.05"),
        paired_t_stat=Decimal("4.00"),
        p_value=Decimal("0.0001"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )
    recorder.record_match(m2)
    recorder.record_promotion(m2)

    archive.refresh()
    assert archive.total_matches_count == 2
    assert archive.promotions_count == 2

    # Check reigning champion is C2
    current_champ = archive.get_current_champion("b4_momentum")
    assert current_champ is not None
    assert current_champ.participant_id == CHALL_ID_2

    # Check ordered succession lineage: C0 -> C1 -> C2
    lineage = archive.get_champion_lineage("b4_momentum")
    assert lineage == (CHAMP_ID_0, CHALL_ID_1, CHALL_ID_2)


def test_runner_with_recorder_end_to_end(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "tournament_runner_audit.sqlite3")
    recorder = TournamentRecorder(ledger)
    archive = TournamentArchive(ledger)

    champ = build_tournament_participant(
        participant_id=CHAMP_ID_0,
        strategy_type="b4_momentum",
        parameters={"lookback": 20},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=CHALL_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback": 50},
        is_incumbent_champion=False,
    )

    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP,
        min_delta_sharpe=Decimal("0.20"),
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.50"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.2"),
            },
        }
    )

    runner = TournamentRunner(
        config=config,
        evaluator=evaluator,
        recorder=recorder,
    )

    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP,
        end_time=TIMESTAMP,
    )

    archive.refresh()
    assert archive.total_matches_count == 1
    assert archive.promotions_count == 1

    stored = archive.get_match(record.match_id)
    assert stored == record

    reigning = archive.get_current_champion("b4_momentum")
    assert reigning is not None
    assert reigning.participant_id == CHALL_ID_1
