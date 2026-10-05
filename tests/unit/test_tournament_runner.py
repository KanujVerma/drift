"""Unit tests for head-to-head tournament runner and match controller (M10-3)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from drift.domain.tournament import (
    TournamentDecision,
    TournamentMatchRecordV1,
    TournamentParticipantV1,
    build_tournament_config,
    build_tournament_participant,
)
from drift.loop.evaluator_adapter import DeterministicMockTrialEvaluator
from drift.tournament.runner import TournamentRunner

TIMESTAMP_START = datetime(2026, 1, 15, 9, 30, 0, tzinfo=UTC)
TIMESTAMP_END = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
TOURNAMENT_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd10")
CHAMPION_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd11")
CHALLENGER_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd12")


def _sample_participants() -> tuple[TournamentParticipantV1, TournamentParticipantV1]:
    champ = build_tournament_participant(
        participant_id=CHAMPION_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 30},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=CHALLENGER_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 60},
        is_incumbent_champion=False,
    )
    return champ, chall


def test_runner_match_champion_defends_title() -> None:
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
        min_delta_sharpe=Decimal("0.25"),
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.20"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                # Challenger only marginally better (+0.05 < required +0.25)
                "annualized_sharpe": Decimal("1.25"),
                "max_drawdown": Decimal("0.08"),
                "annualized_turnover": Decimal("2.1"),
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.REJECTED_INSUFFICIENT_OUTPERFORMANCE
    assert record.delta_sharpe == Decimal("0.05")
    assert len(record.rejection_reasons) > 0


def test_runner_match_challenger_promoted() -> None:
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
        min_delta_sharpe=Decimal("0.30"),
    )

    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.00"),
                "max_drawdown": Decimal("0.10"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                # Significantly outperforms: +0.60 Sharpe, lower DD
                "annualized_sharpe": Decimal("1.60"),
                "max_drawdown": Decimal("0.07"),
                "annualized_turnover": Decimal("2.2"),
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    record = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert record.decision == TournamentDecision.PROMOTED
    assert record.delta_sharpe == Decimal("0.60")
    assert len(record.rejection_reasons) == 0


def test_runner_rejects_non_incumbent_as_champion() -> None:
    fake_champ = build_tournament_participant(
        participant_id=CHAMPION_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 30},
        is_incumbent_champion=False,  # NOT an incumbent
    )
    chall = build_tournament_participant(
        participant_id=CHALLENGER_ID,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 60},
        is_incumbent_champion=False,
    )
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
    )
    evaluator = DeterministicMockTrialEvaluator()

    runner = TournamentRunner(config=config, evaluator=evaluator)
    with pytest.raises(ValueError, match="not declared as incumbent champion"):
        runner.run_match(
            champion=fake_champ,
            challenger=chall,
            start_time=TIMESTAMP_START,
            end_time=TIMESTAMP_END,
        )


def test_runner_with_mock_recorder() -> None:
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
    )

    class MockRecorder:
        def __init__(self) -> None:
            self.matches: list[TournamentMatchRecordV1] = []
            self.promotions: list[TournamentMatchRecordV1] = []
            self.rejections: list[TournamentMatchRecordV1] = []

        def record_match(self, match: TournamentMatchRecordV1) -> Any:
            self.matches.append(match)

        def record_promotion(self, match: TournamentMatchRecordV1) -> Any:
            self.promotions.append(match)

        def record_rejection(self, match: TournamentMatchRecordV1) -> Any:
            self.rejections.append(match)

    recorder = MockRecorder()
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
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert len(recorder.matches) == 1
    assert len(recorder.promotions) == 1
    assert len(recorder.rejections) == 0
    assert recorder.matches[0] == record


def test_runner_reproducibility() -> None:
    champ, chall = _sample_participants()
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID,
        created_at=TIMESTAMP_START,
    )
    evaluator = DeterministicMockTrialEvaluator(
        metric_overrides={
            champ.parameters_hash: {
                "annualized_sharpe": Decimal("1.10"),
                "max_drawdown": Decimal("0.09"),
                "annualized_turnover": Decimal("2.0"),
            },
            chall.parameters_hash: {
                "annualized_sharpe": Decimal("1.45"),
                "max_drawdown": Decimal("0.07"),
                "annualized_turnover": Decimal("2.1"),
            },
        }
    )

    runner = TournamentRunner(config=config, evaluator=evaluator)
    rec1 = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )
    rec2 = runner.run_match(
        champion=champ,
        challenger=chall,
        start_time=TIMESTAMP_START,
        end_time=TIMESTAMP_END,
    )

    assert rec1 == rec2
    assert rec1.record_hash == rec2.record_hash
