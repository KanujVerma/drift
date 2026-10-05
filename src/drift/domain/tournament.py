"""Tournament domain models and audit event payloads (M10-1, Issue 243).

Provides immutable domain models for head-to-head out-of-sample competitions
between incumbent Champion strategies and newly evolved Challenger strategies.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.serialization.canonical import content_hash

TOURNAMENT_SCHEMA_VERSION: Literal["1"] = "1"
MATCH_COMPLETED_EVENT_TYPE: NonBlankStr = "m10.match.completed"
CHAMPION_PROMOTED_EVENT_TYPE: NonBlankStr = "m10.champion.promoted"
CHALLENGER_REJECTED_EVENT_TYPE: NonBlankStr = "m10.challenger.rejected"

__all__ = [
    "CHALLENGER_REJECTED_EVENT_TYPE",
    "CHAMPION_PROMOTED_EVENT_TYPE",
    "MATCH_COMPLETED_EVENT_TYPE",
    "TOURNAMENT_SCHEMA_VERSION",
    "ChallengerRejectedAuditEventPayloadV1",
    "ChampionPromotedAuditEventPayloadV1",
    "MatchCompletedAuditEventPayloadV1",
    "TournamentConfigV1",
    "TournamentDecision",
    "TournamentMatchRecordV1",
    "TournamentParticipantV1",
    "build_tournament_config",
    "build_tournament_match_record",
    "build_tournament_participant",
    "compute_tournament_config_hash",
    "compute_tournament_match_record_hash",
    "compute_tournament_participant_hash",
]


class TournamentDecision(StrEnum):
    """Terminal decision for a head-to-head tournament match."""

    PROMOTED = "promoted"
    REJECTED_INSUFFICIENT_OUTPERFORMANCE = "rejected_insufficient_outperformance"
    REJECTED_STATISTICALLY_INSIGNIFICANT = "rejected_statistically_insignificant"
    REJECTED_EXCESSIVE_DRAWDOWN = "rejected_excessive_drawdown"
    REJECTED_EXCESSIVE_TURNOVER = "rejected_excessive_turnover"
    REJECTED_INCOMPLETE_EVIDENCE = "rejected_incomplete_evidence"


# =========================================================================
# Hash Computation Functions
# =========================================================================


def compute_tournament_participant_hash(
    parameters: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash of participant parameters."""
    return content_hash(dict(parameters))


def compute_tournament_config_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for TournamentConfigV1."""
    d = dict(unsigned)
    d.pop("config_hash", None)
    return content_hash(d)


def compute_tournament_match_record_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash for TournamentMatchRecordV1."""
    d = dict(unsigned)
    d.pop("record_hash", None)
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class TournamentParticipantV1(FrozenModel):
    """Strategy participant in a tournament match."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    participant_id: UUID7
    strategy_type: NonBlankStr
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    parameters_hash: SHA256Hash
    trial_id: UUID7 | None = None
    is_incumbent_champion: bool = False

    @model_validator(mode="after")
    def validate_participant_integrity(self) -> Self:
        expected = compute_tournament_participant_hash(self.parameters)
        if self.parameters_hash != expected:
            raise ValueError("tournament participant parameters hash mismatch")
        return self


class TournamentConfigV1(FrozenModel):
    """Configuration governing head-to-head tournament evaluation."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    tournament_id: UUID7
    min_delta_sharpe: Decimal = Field(default=Decimal("0.20"), ge=Decimal("0.0"))
    significance_alpha: Decimal = Field(
        default=Decimal("0.05"), gt=Decimal("0.0"), le=Decimal("0.50")
    )
    max_drawdown_slack: Decimal = Field(default=Decimal("0.10"), ge=Decimal("0.0"))
    max_turnover_ratio: Decimal = Field(default=Decimal("2.50"), ge=Decimal("1.0"))
    min_evaluation_sessions: int = Field(default=60, ge=10)
    created_at: UTCDateTime
    config_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_config_integrity(self) -> Self:
        expected = compute_tournament_config_hash(self.model_dump(mode="python"))
        if self.config_hash != expected:
            raise ValueError("tournament config hash mismatch")
        return self


class TournamentMatchRecordV1(FrozenModel):
    """Immutable record of a completed head-to-head tournament match."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    match_id: UUID7
    tournament_id: UUID7
    champion: TournamentParticipantV1
    challenger: TournamentParticipantV1
    champion_sharpe: Decimal
    challenger_sharpe: Decimal
    delta_sharpe: Decimal
    champion_max_drawdown: Decimal
    challenger_max_drawdown: Decimal
    turnover_ratio: Decimal
    paired_t_stat: Decimal
    p_value: Decimal = Field(ge=Decimal("0.0"), le=Decimal("1.0"))
    decision: TournamentDecision
    rejection_reasons: tuple[str, ...] = ()
    evaluated_sessions_count: int = Field(ge=0)
    started_at: UTCDateTime
    completed_at: UTCDateTime
    record_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_record_integrity(self) -> Self:
        expected = compute_tournament_match_record_hash(self.model_dump(mode="python"))
        if self.record_hash != expected:
            raise ValueError("tournament match record hash mismatch")
        return self


# =========================================================================
# Ledger Audit Event Payloads
# =========================================================================


class MatchCompletedAuditEventPayloadV1(FrozenModel):
    """Payload for m10.match.completed audit events sealed into ledger."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    match: TournamentMatchRecordV1


class ChampionPromotedAuditEventPayloadV1(FrozenModel):
    """Payload for m10.champion.promoted audit events sealed into ledger."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    match_id: UUID7
    tournament_id: UUID7
    promoted_champion_id: UUID7
    dethroned_champion_id: UUID7
    promoted_at: UTCDateTime


class ChallengerRejectedAuditEventPayloadV1(FrozenModel):
    """Payload for m10.challenger.rejected audit events sealed into ledger."""

    schema_version: Literal["1"] = TOURNAMENT_SCHEMA_VERSION
    match_id: UUID7
    tournament_id: UUID7
    challenger_id: UUID7
    decision: TournamentDecision
    rejection_reasons: tuple[str, ...]
    rejected_at: UTCDateTime


# =========================================================================
# Builder Helpers
# =========================================================================


def build_tournament_participant(
    *,
    participant_id: UUID,
    strategy_type: NonBlankStr,
    parameters: Mapping[str, Any] | None = None,
    trial_id: UUID | None = None,
    is_incumbent_champion: bool = False,
) -> TournamentParticipantV1:
    """Construct an immutable TournamentParticipantV1 with computed hash."""
    params = dict(parameters) if parameters else {}
    p_hash = compute_tournament_participant_hash(params)
    return TournamentParticipantV1.model_validate(
        {
            "schema_version": TOURNAMENT_SCHEMA_VERSION,
            "participant_id": participant_id,
            "strategy_type": strategy_type,
            "parameters": params,
            "parameters_hash": p_hash,
            "trial_id": trial_id,
            "is_incumbent_champion": is_incumbent_champion,
        }
    )


def build_tournament_config(
    *,
    tournament_id: UUID,
    created_at: UTCDateTime,
    min_delta_sharpe: Decimal = Decimal("0.20"),
    significance_alpha: Decimal = Decimal("0.05"),
    max_drawdown_slack: Decimal = Decimal("0.10"),
    max_turnover_ratio: Decimal = Decimal("2.50"),
    min_evaluation_sessions: int = 60,
) -> TournamentConfigV1:
    """Construct an immutable TournamentConfigV1 with computed hash."""
    unsigned = {
        "schema_version": TOURNAMENT_SCHEMA_VERSION,
        "tournament_id": tournament_id,
        "min_delta_sharpe": min_delta_sharpe,
        "significance_alpha": significance_alpha,
        "max_drawdown_slack": max_drawdown_slack,
        "max_turnover_ratio": max_turnover_ratio,
        "min_evaluation_sessions": min_evaluation_sessions,
        "created_at": created_at,
    }
    c_hash = compute_tournament_config_hash(unsigned)
    return TournamentConfigV1.model_validate(
        {
            **unsigned,
            "config_hash": c_hash,
        }
    )


def build_tournament_match_record(
    *,
    match_id: UUID,
    tournament_id: UUID,
    champion: TournamentParticipantV1,
    challenger: TournamentParticipantV1,
    champion_sharpe: Decimal,
    challenger_sharpe: Decimal,
    delta_sharpe: Decimal,
    champion_max_drawdown: Decimal,
    challenger_max_drawdown: Decimal,
    turnover_ratio: Decimal,
    paired_t_stat: Decimal,
    p_value: Decimal,
    decision: TournamentDecision,
    evaluated_sessions_count: int,
    started_at: UTCDateTime,
    completed_at: UTCDateTime,
    rejection_reasons: tuple[str, ...] = (),
) -> TournamentMatchRecordV1:
    """Construct an immutable TournamentMatchRecordV1 with computed hash."""
    unsigned = {
        "schema_version": TOURNAMENT_SCHEMA_VERSION,
        "match_id": match_id,
        "tournament_id": tournament_id,
        "champion": champion.model_dump(mode="python"),
        "challenger": challenger.model_dump(mode="python"),
        "champion_sharpe": champion_sharpe,
        "challenger_sharpe": challenger_sharpe,
        "delta_sharpe": delta_sharpe,
        "champion_max_drawdown": champion_max_drawdown,
        "challenger_max_drawdown": challenger_max_drawdown,
        "turnover_ratio": turnover_ratio,
        "paired_t_stat": paired_t_stat,
        "p_value": p_value,
        "decision": decision,
        "rejection_reasons": rejection_reasons,
        "evaluated_sessions_count": evaluated_sessions_count,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    r_hash = compute_tournament_match_record_hash(unsigned)
    return TournamentMatchRecordV1.model_validate(
        {
            **unsigned,
            "champion": champion,
            "challenger": challenger,
            "record_hash": r_hash,
        }
    )
