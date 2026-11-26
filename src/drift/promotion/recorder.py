"""Promotion gate recorder and M0 ledger persistence (M11-4, Issue 261).

Provides atomic sealing of promotion evaluation records, certifications, and
rejections into the SQLite ledger with schema versioning and dedup keys.
"""

from datetime import datetime
from uuid import UUID

from drift.domain.common import _freeze_json
from drift.domain.events import AuditEvent
from drift.domain.promotion import (
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    INCOMPLETE_REJECTED_EVENT_TYPE,
    PROMOTION_SCHEMA_VERSION,
    CandidateRejectedAuditEventPayloadV1,
    GateEvaluatedAuditEventPayloadV1,
    IncompletePromotionRejectionV2,
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
)
from drift.errors import DuplicateEventError
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.memory.recorder import deterministic_memory_uuid7
from drift.serialization.canonical import canonical_json

PROMOTION_EVALUATION_ENTITY_TYPE = "promotion_evaluation"
PROMOTION_CERTIFICATION_ENTITY_TYPE = "promotion_certification"
PROMOTION_REJECTION_ENTITY_TYPE = "promotion_rejection"

__all__ = [
    "PROMOTION_CERTIFICATION_ENTITY_TYPE",
    "PROMOTION_EVALUATION_ENTITY_TYPE",
    "PROMOTION_REJECTION_ENTITY_TYPE",
    "PromotionAuditUncertain",
    "PromotionRecorder",
]


class PromotionAuditUncertain(OSError):
    """A write or readback failed; retain identity for an exact retry."""

    def __init__(self, evaluation_id: UUID, evaluated_at: datetime) -> None:
        super().__init__("audit append or readback uncertain")
        self.evaluation_id = evaluation_id
        self.evaluated_at = evaluated_at


class PromotionRecorder:
    """Manages transactional recording of promotion gate events into M0 ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def _append_exact(
        self, draft: AuditEventDraft, *, evaluation_id: UUID
    ) -> AuditEvent:
        try:
            self.ledger.append(draft)
        except DuplicateEventError:
            pass
        except Exception as error:
            raise PromotionAuditUncertain(evaluation_id, draft.timestamp) from error
        try:
            matches = [
                e for e in self.ledger.verified_events() if e.event_id == draft.event_id
            ]
        except Exception as error:
            raise PromotionAuditUncertain(evaluation_id, draft.timestamp) from error
        if len(matches) != 1 or canonical_json(
            matches[0].model_dump(exclude={"event_hash", "previous_event_hash"})
        ) != canonical_json(draft.model_dump()):
            raise ValueError("attempt identity or payload conflict")
        return matches[0]

    def record_incomplete(self, record: IncompletePromotionRejectionV2) -> AuditEvent:
        """Seal or exactly retry one incomplete attempt; never replace it."""
        record = IncompletePromotionRejectionV2.model_validate(
            record.model_dump(mode="python")
        )
        draft = AuditEventDraft(
            schema_version="2",
            event_id=deterministic_memory_uuid7(
                f"promotion_eval:{record.evaluation_id}"
            ),
            event_type=INCOMPLETE_REJECTED_EVENT_TYPE,
            timestamp=record.evaluated_at,
            entity_type=PROMOTION_EVALUATION_ENTITY_TYPE,
            entity_id=record.evaluation_id,
            payload=_freeze_json(record.model_dump(mode="python")),
            deduplication_key=f"m11:eval:{record.evaluation_id}",
        )
        return self._append_exact(draft, evaluation_id=record.evaluation_id)

    def record_evaluation(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Refuse caller-created metrics; use the gatekeeper to compute them."""
        raise ValueError("caller-created evaluation record refused")

    def record_certification(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Refuse new certification until authenticated provenance exists."""
        raise RuntimeError("certification requires authenticated provenance")

    def record_rejection(
        self,
        record: PromotionEvaluationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a candidate rejection event into ledger."""
        record = PromotionEvaluationRecordV1.model_validate(
            record.model_dump(mode="python")
        )
        if record.verdict in (
            PromotionGateVerdict.PROMOTION_QUALIFIED,
            PromotionGateVerdict.EXPLORATORY_PASSED,
            PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE,
        ):
            raise ValueError("record is not a supported statistical rejection")
        try:
            evaluations = [
                event
                for event in self.ledger.verified_events()
                if event.deduplication_key == f"m11:eval:{record.evaluation_id}"
                and event.event_type == GATE_EVALUATED_EVENT_TYPE
            ]
        except Exception as error:
            raise PromotionAuditUncertain(
                record.evaluation_id, record.evaluated_at
            ) from error
        expected = GateEvaluatedAuditEventPayloadV1(evaluation=record)
        if len(evaluations) != 1 or canonical_json(
            evaluations[0].payload
        ) != canonical_json(expected.model_dump(mode="python")):
            raise ValueError("rejection requires a matching evaluated record")
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
            event_id=(
                deterministic_memory_uuid7(
                    f"promotion_rej:{record.evaluation_id}:{record.candidate_id}"
                )
                if event_id is None
                else event_id
            ),
            event_type=CANDIDATE_REJECTED_EVENT_TYPE,
            timestamp=record.evaluated_at,
            entity_type=PROMOTION_REJECTION_ENTITY_TYPE,
            entity_id=record.candidate_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m11:rej:{record.evaluation_id}",
        )
        return self._append_exact(draft, evaluation_id=record.evaluation_id)
