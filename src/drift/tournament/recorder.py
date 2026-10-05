"""Tournament match recorder and M0 ledger persistence (M10-4, Issue 249).

Provides atomic sealing of match records, champion promotions, and challenger
rejections into the SQLite ledger with schema versioning and dedup keys.
"""

from uuid import UUID

from drift.domain.common import _freeze_json
from drift.domain.events import AuditEvent
from drift.domain.tournament import (
    CHALLENGER_REJECTED_EVENT_TYPE,
    CHAMPION_PROMOTED_EVENT_TYPE,
    MATCH_COMPLETED_EVENT_TYPE,
    TOURNAMENT_SCHEMA_VERSION,
    ChallengerRejectedAuditEventPayloadV1,
    ChampionPromotedAuditEventPayloadV1,
    MatchCompletedAuditEventPayloadV1,
    TournamentMatchRecordV1,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.memory.recorder import deterministic_memory_uuid7

MATCH_ENTITY_TYPE = "tournament_match"
PROMOTION_ENTITY_TYPE = "tournament_promotion"
REJECTION_ENTITY_TYPE = "tournament_rejection"

__all__ = [
    "MATCH_ENTITY_TYPE",
    "PROMOTION_ENTITY_TYPE",
    "REJECTION_ENTITY_TYPE",
    "TournamentRecorder",
]


class TournamentRecorder:
    """Manages transactional recording of tournament events into M0 ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def record_match(
        self,
        match: TournamentMatchRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a completed tournament match record into ledger."""
        payload = MatchCompletedAuditEventPayloadV1(match=match)
        draft = AuditEventDraft(
            schema_version=TOURNAMENT_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(f"tournament_match:{match.match_id}"),
            event_type=MATCH_COMPLETED_EVENT_TYPE,
            timestamp=match.completed_at,
            entity_type=MATCH_ENTITY_TYPE,
            entity_id=match.match_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m10:match:{match.match_id}",
        )
        return self.ledger.append(draft)

    def record_promotion(
        self,
        match: TournamentMatchRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a champion promotion event into ledger."""
        payload = ChampionPromotedAuditEventPayloadV1(
            match_id=match.match_id,
            tournament_id=match.tournament_id,
            promoted_champion_id=match.challenger.participant_id,
            dethroned_champion_id=match.champion.participant_id,
            promoted_at=match.completed_at,
        )
        draft = AuditEventDraft(
            schema_version=TOURNAMENT_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(
                f"tournament_promo:{match.match_id}:{match.challenger.participant_id}"
            ),
            event_type=CHAMPION_PROMOTED_EVENT_TYPE,
            timestamp=match.completed_at,
            entity_type=PROMOTION_ENTITY_TYPE,
            entity_id=match.challenger.participant_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m10:promo:{match.match_id}",
        )
        return self.ledger.append(draft)

    def record_rejection(
        self,
        match: TournamentMatchRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a challenger rejection event into ledger."""
        payload = ChallengerRejectedAuditEventPayloadV1(
            match_id=match.match_id,
            tournament_id=match.tournament_id,
            challenger_id=match.challenger.participant_id,
            decision=match.decision,
            rejection_reasons=match.rejection_reasons,
            rejected_at=match.completed_at,
        )
        draft = AuditEventDraft(
            schema_version=TOURNAMENT_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(
                f"tournament_reject:{match.match_id}:{match.challenger.participant_id}"
            ),
            event_type=CHALLENGER_REJECTED_EVENT_TYPE,
            timestamp=match.completed_at,
            entity_type=REJECTION_ENTITY_TYPE,
            entity_id=match.challenger.participant_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m10:reject:{match.match_id}",
        )
        return self.ledger.append(draft)
