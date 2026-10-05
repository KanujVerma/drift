"""Unit tests for tournament domain models, schemas, and payloads (M10-1, Issue 243)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.tournament import (
    CHALLENGER_REJECTED_EVENT_TYPE,
    CHAMPION_PROMOTED_EVENT_TYPE,
    MATCH_COMPLETED_EVENT_TYPE,
    ChallengerRejectedAuditEventPayloadV1,
    ChampionPromotedAuditEventPayloadV1,
    MatchCompletedAuditEventPayloadV1,
    TournamentConfigV1,
    TournamentDecision,
    TournamentMatchRecordV1,
    TournamentParticipantV1,
    build_tournament_config,
    build_tournament_match_record,
    build_tournament_participant,
)

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
PARTICIPANT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
PARTICIPANT_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
TOURNAMENT_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
MATCH_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")


def test_tournament_participant_construction_and_tamper() -> None:
    part = build_tournament_participant(
        participant_id=PARTICIPANT_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 20, "rebalance_freq": "weekly"},
        is_incumbent_champion=True,
    )

    assert part.participant_id == PARTICIPANT_ID_1
    assert part.strategy_type == "b4_momentum"
    assert part.is_incumbent_champion is True
    assert len(part.parameters_hash) == 64

    # Tamper with parameters without updating hash
    tampered = part.model_dump()
    tampered["parameters"] = {"lookback_days": 30}
    with pytest.raises(ValidationError, match="hash mismatch"):
        TournamentParticipantV1.model_validate(tampered)


def test_tournament_config_construction_and_bounds() -> None:
    config = build_tournament_config(
        tournament_id=TOURNAMENT_ID_1,
        created_at=TIMESTAMP,
        min_delta_sharpe=Decimal("0.25"),
        significance_alpha=Decimal("0.01"),
        max_drawdown_slack=Decimal("0.05"),
        max_turnover_ratio=Decimal("2.0"),
        min_evaluation_sessions=90,
    )

    assert config.tournament_id == TOURNAMENT_ID_1
    assert config.min_delta_sharpe == Decimal("0.25")
    assert config.significance_alpha == Decimal("0.01")
    assert config.min_evaluation_sessions == 90
    assert len(config.config_hash) == 64

    # Negative min_delta_sharpe rejected
    with pytest.raises(ValidationError):
        build_tournament_config(
            tournament_id=TOURNAMENT_ID_1,
            created_at=TIMESTAMP,
            min_delta_sharpe=Decimal("-0.10"),
        )

    # Insufficient evaluation sessions (< 10) rejected
    with pytest.raises(ValidationError):
        build_tournament_config(
            tournament_id=TOURNAMENT_ID_1,
            created_at=TIMESTAMP,
            min_evaluation_sessions=5,
        )

    # Tamper with config
    tampered = config.model_dump()
    tampered["min_delta_sharpe"] = Decimal("0.50")
    with pytest.raises(ValidationError, match="hash mismatch"):
        TournamentConfigV1.model_validate(tampered)


def test_tournament_match_record_construction_and_tamper() -> None:
    champ = build_tournament_participant(
        participant_id=PARTICIPANT_ID_1,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 20},
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=PARTICIPANT_ID_2,
        strategy_type="b4_momentum",
        parameters={"lookback_days": 40},
        is_incumbent_champion=False,
    )

    record = build_tournament_match_record(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        champion=champ,
        challenger=chall,
        champion_sharpe=Decimal("1.10"),
        challenger_sharpe=Decimal("1.45"),
        delta_sharpe=Decimal("0.35"),
        champion_max_drawdown=Decimal("0.08"),
        challenger_max_drawdown=Decimal("0.07"),
        turnover_ratio=Decimal("1.20"),
        paired_t_stat=Decimal("3.12"),
        p_value=Decimal("0.0018"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=120,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    assert record.match_id == MATCH_ID_1
    assert record.decision == TournamentDecision.PROMOTED
    assert record.delta_sharpe == Decimal("0.35")
    assert len(record.record_hash) == 64

    # Tamper with record
    tampered = record.model_dump()
    tampered["decision"] = TournamentDecision.REJECTED_EXCESSIVE_DRAWDOWN
    with pytest.raises(ValidationError, match="hash mismatch"):
        TournamentMatchRecordV1.model_validate(tampered)


def test_audit_event_payloads() -> None:
    champ = build_tournament_participant(
        participant_id=PARTICIPANT_ID_1,
        strategy_type="b4_momentum",
        is_incumbent_champion=True,
    )
    chall = build_tournament_participant(
        participant_id=PARTICIPANT_ID_2,
        strategy_type="b4_momentum",
        is_incumbent_champion=False,
    )

    record = build_tournament_match_record(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        champion=champ,
        challenger=chall,
        champion_sharpe=Decimal("1.0"),
        challenger_sharpe=Decimal("1.3"),
        delta_sharpe=Decimal("0.3"),
        champion_max_drawdown=Decimal("0.10"),
        challenger_max_drawdown=Decimal("0.09"),
        turnover_ratio=Decimal("1.10"),
        paired_t_stat=Decimal("2.80"),
        p_value=Decimal("0.005"),
        decision=TournamentDecision.PROMOTED,
        evaluated_sessions_count=60,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
    )

    # 1. MatchCompleted
    p1 = MatchCompletedAuditEventPayloadV1(match=record)
    assert p1.match == record
    assert MATCH_COMPLETED_EVENT_TYPE == "m10.match.completed"

    # 2. ChampionPromoted
    p2 = ChampionPromotedAuditEventPayloadV1(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        promoted_champion_id=PARTICIPANT_ID_2,
        dethroned_champion_id=PARTICIPANT_ID_1,
        promoted_at=TIMESTAMP,
    )
    assert p2.promoted_champion_id == PARTICIPANT_ID_2
    assert CHAMPION_PROMOTED_EVENT_TYPE == "m10.champion.promoted"

    # 3. ChallengerRejected
    p3 = ChallengerRejectedAuditEventPayloadV1(
        match_id=MATCH_ID_1,
        tournament_id=TOURNAMENT_ID_1,
        challenger_id=PARTICIPANT_ID_2,
        decision=TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT,
        rejection_reasons=("p-value 0.12 exceeded alpha 0.05",),
        rejected_at=TIMESTAMP,
    )
    assert p3.decision == TournamentDecision.REJECTED_STATISTICALLY_INSIGNIFICANT
    assert CHALLENGER_REJECTED_EVENT_TYPE == "m10.challenger.rejected"
