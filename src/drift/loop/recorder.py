"""Recursive R&D loop audit event recorder and M0 ledger persistence (M8-4, Issue 237).

Provides atomic, append-only sealing of single iteration audit records and
terminal loop summary outcomes into the Drift SQLite research ledger.
"""

from uuid import UUID

from drift.domain.common import _freeze_json
from drift.domain.events import AuditEvent
from drift.domain.research_loop import (
    ITERATION_EVENT_TYPE,
    LOOP_EVENT_TYPE,
    RESEARCH_LOOP_SCHEMA_VERSION,
    IterationCompletedAuditEventPayloadV1,
    LoopCompletedAuditEventPayloadV1,
    ResearchIterationRecordV1,
    ResearchLoopSummaryV1,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.memory.recorder import deterministic_memory_uuid7

ITERATION_ENTITY_TYPE = "research_iteration"
LOOP_ENTITY_TYPE = "research_loop"

__all__ = [
    "ITERATION_ENTITY_TYPE",
    "LOOP_ENTITY_TYPE",
    "ResearchLoopRecorder",
]


class ResearchLoopRecorder:
    """Manages transactional recording of loop iteration and summary events."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def record_iteration(
        self,
        iteration: ResearchIterationRecordV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a research iteration record into the M0 ledger."""
        payload = IterationCompletedAuditEventPayloadV1(iteration=iteration)
        draft = AuditEventDraft(
            schema_version=RESEARCH_LOOP_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(
                f"loop_iteration:{iteration.loop_id}:{iteration.iteration_index}"
            ),
            event_type=ITERATION_EVENT_TYPE,
            timestamp=iteration.completed_at,
            entity_type=ITERATION_ENTITY_TYPE,
            entity_id=iteration.iteration_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m8:iteration:{iteration.iteration_id}",
        )
        return self.ledger.append(draft)

    def record_loop_summary(
        self,
        summary: ResearchLoopSummaryV1,
        *,
        event_id: UUID | None = None,
    ) -> AuditEvent:
        """Atomically seal a research loop summary into the M0 ledger."""
        payload = LoopCompletedAuditEventPayloadV1(summary=summary)
        draft = AuditEventDraft(
            schema_version=RESEARCH_LOOP_SCHEMA_VERSION,
            event_id=event_id
            or deterministic_memory_uuid7(f"loop_summary:{summary.loop_id}"),
            event_type=LOOP_EVENT_TYPE,
            timestamp=summary.completed_at,
            entity_type=LOOP_ENTITY_TYPE,
            entity_id=summary.loop_id,
            payload=_freeze_json(payload.model_dump(mode="python")),
            deduplication_key=f"m8:loop:{summary.loop_id}",
        )
        return self.ledger.append(draft)
