"""Promotion gate recorder and M0 ledger persistence (M11-4, Issue 261).

Provides atomic sealing of promotion evaluation records, certifications, and
rejections into the SQLite ledger with schema versioning and dedup keys.
"""

from uuid import UUID

from drift.domain.common import _freeze_json
from drift.domain.events import AuditEvent
from drift.domain.promotion import (
    CANDIDATE_CERTIFIED_EVENT_TYPE,
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    PROMOTION_SCHEMA_VERSION,
    CandidateCertifiedAuditEventPayloadV1,
    CandidateRejectedAuditEventPayloadV1,
    GateEvaluatedAuditEventPayloadV1,
    PromotionEvaluationRecordV1,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.memory.recorder import deterministic_memory_uuid7

PROMOTION_EVALUATION_ENTITY_TYPE = "promotion_evaluation"
PROMOTION_CERTIFICATION_ENTITY_TYPE = "promotion_certification"
PROMOTION_REJECTION_ENTITY_TYPE = "promotion_rejection"

__all__ = [
    "PROMOTION_CERTIFICATION_ENTITY_TYPE",
    "PROMOTION_EVALUATION_ENTITY_TYPE",
    "PROMOTION_REJECTION_ENTITY_TYPE",
    "PromotionRecorder",
]


class PromotionRecorder:
    """Manages transactional recording of promotion gate events into M0 ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def record_evaluation(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a promotion evaluation record into ledger."""
        payload = GateEvaluatedAuditEventPayloadV1(evaluation=record)
        draft = AuditEventDraft(
            schema_version=PROMOTION_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(f"promotion_eval:{record.evaluation_id}"),
            event_type=GATE_EVALUATED_EVENT_TYPE,
            timestamp=record.evaluated_at,
            entity_type=PROMOTION_EVALUATION_ENTITY_TYPE,
            entity_id=record.evaluation_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m11:eval:{record.evaluation_id}",
        )
        return self.ledger.append(draft)

    def record_certification(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a candidate certification event into ledger."""
        payload = CandidateCertifiedAuditEventPayloadV1(
            evaluation_id=record.evaluation_id,
            candidate_id=record.candidate_id,
            strategy_type=record.strategy_type,
            verdict=record.verdict,
            certified_at=record.evaluated_at,
        )
        draft = AuditEventDraft(
            schema_version=PROMOTION_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(
                f"promotion_cert:{record.evaluation_id}:{record.candidate_id}"
            ),
            event_type=CANDIDATE_CERTIFIED_EVENT_TYPE,
            timestamp=record.evaluated_at,
            entity_type=PROMOTION_CERTIFICATION_ENTITY_TYPE,
            entity_id=record.candidate_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m11:cert:{record.evaluation_id}",
        )
        return self.ledger.append(draft)

    def record_rejection(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a candidate rejection event into ledger."""
        payload = CandidateRejectedAuditEventPayloadV1(
            evaluation_id=record.evaluation_id,
            candidate_id=record.candidate_id,
            strategy_type=record.strategy_type,
            verdict=record.verdict,
            rejection_reasons=record.rejection_reasons,
            rejected_at=record.evaluated_at,
        )
        draft = AuditEventDraft(
            schema_version=PROMOTION_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(
                f"promotion_rej:{record.evaluation_id}:{record.candidate_id}"
            ),
            event_type=CANDIDATE_REJECTED_EVENT_TYPE,
            timestamp=record.evaluated_at,
            entity_type=PROMOTION_REJECTION_ENTITY_TYPE,
            entity_id=record.candidate_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m11:rej:{record.evaluation_id}",
        )
        return self.ledger.append(draft)
