"""Historical promotion archive and query engine (M11-4, Issue 261).

Reconstructs promotion evaluation records, certifications, and rejections
directly from immutable M0 SQLite ledger events.
"""

from collections.abc import Mapping
from uuid import UUID

from drift.domain.promotion import (
    CANDIDATE_CERTIFIED_EVENT_TYPE,
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    INCOMPLETE_REJECTED_EVENT_TYPE,
    CandidateCertifiedAuditEventPayloadV1,
    CandidateRejectedAuditEventPayloadV1,
    GateEvaluatedAuditEventPayloadV1,
    IncompletePromotionRejectionV2,
    PromotionEvaluationRecordV1,
)
from drift.ledger.interface import Ledger
from drift.memory.recorder import deterministic_memory_uuid7
from drift.serialization.canonical import canonical_json

__all__ = ["PromotionArchive"]


class PromotionArchive:
    """Historical archive reconstructing promotion state from immutable ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._evaluations: dict[UUID, PromotionEvaluationRecordV1] = {}
        self._incomplete: dict[UUID, IncompletePromotionRejectionV2] = {}
        self._certifications: list[CandidateCertifiedAuditEventPayloadV1] = []
        self._rejections: list[CandidateRejectedAuditEventPayloadV1] = []
        self._certified_candidates: dict[
            UUID, CandidateCertifiedAuditEventPayloadV1
        ] = {}
        self.refresh()

    def refresh(self) -> None:
        """Scan ledger events and synchronize promotion state."""
        self._evaluations.clear()
        self._incomplete.clear()
        self._certifications.clear()
        self._rejections.clear()
        self._certified_candidates.clear()

        for event in self.ledger.verified_events():
            expected_versions = {
                INCOMPLETE_REJECTED_EVENT_TYPE: "2",
                GATE_EVALUATED_EVENT_TYPE: "1",
                CANDIDATE_CERTIFIED_EVENT_TYPE: "1",
                CANDIDATE_REJECTED_EVENT_TYPE: "1",
            }
            if not isinstance(event.payload, Mapping):
                if event.event_type in expected_versions:
                    raise ValueError("malformed promotion event payload")
                continue
            version = expected_versions.get(event.event_type)
            if version is not None and (
                event.schema_version != version
                or event.payload.get("schema_version", "1" if version == "1" else None)
                != version
            ):
                raise ValueError("malformed promotion event version")

            if event.event_type == INCOMPLETE_REJECTED_EVENT_TYPE:
                record_v2 = IncompletePromotionRejectionV2.model_validate_json(
                    canonical_json(dict(event.payload))
                )
                if (
                    event.schema_version != "2"
                    or event.entity_type != "promotion_evaluation"
                    or event.entity_id != record_v2.evaluation_id
                    or event.event_id
                    != deterministic_memory_uuid7(
                        f"promotion_eval:{record_v2.evaluation_id}"
                    )
                    or event.deduplication_key != f"m11:eval:{record_v2.evaluation_id}"
                    or event.timestamp != record_v2.evaluated_at
                ):
                    raise ValueError("invalid incomplete rejection event envelope")
                self._incomplete[record_v2.evaluation_id] = record_v2

            elif event.event_type == GATE_EVALUATED_EVENT_TYPE:
                payload = GateEvaluatedAuditEventPayloadV1.model_validate_json(
                    canonical_json(dict(event.payload))
                )
                record = payload.evaluation
                self._evaluations[record.evaluation_id] = record

            elif event.event_type == CANDIDATE_CERTIFIED_EVENT_TYPE:
                try:
                    cert_payload = (
                        CandidateCertifiedAuditEventPayloadV1.model_validate_json(
                            canonical_json(dict(event.payload))
                        )
                    )
                    self._certifications.append(cert_payload)
                    self._certified_candidates[cert_payload.candidate_id] = cert_payload
                except Exception as error:
                    raise ValueError("malformed certification event") from error

            elif event.event_type == CANDIDATE_REJECTED_EVENT_TYPE:
                try:
                    rej_payload = (
                        CandidateRejectedAuditEventPayloadV1.model_validate_json(
                            canonical_json(dict(event.payload))
                        )
                    )
                    self._rejections.append(rej_payload)
                except Exception as error:
                    raise ValueError("malformed rejection event") from error

    def get_evaluation(self, evaluation_id: UUID) -> PromotionEvaluationRecordV1 | None:
        """Retrieve evaluation record by ID."""
        return self._evaluations.get(evaluation_id)

    def list_evaluations(self) -> list[PromotionEvaluationRecordV1]:
        """List V1 evaluations only; incomplete V2 attempts are not included."""
        return list(self._evaluations.values())

    def list_incomplete_rejections(self) -> list[IncompletePromotionRejectionV2]:
        """List truthful incomplete attempts omitted from legacy V1 views."""
        return list(self._incomplete.values())

    def get_attempt(
        self,
        evaluation_id: UUID,
    ) -> PromotionEvaluationRecordV1 | IncompletePromotionRejectionV2 | None:
        """Read either event version without fabricating V1 metrics."""
        return self._incomplete.get(evaluation_id) or self._evaluations.get(
            evaluation_id
        )

    def list_certifications(
        self, strategy_type: str | None = None
    ) -> list[CandidateCertifiedAuditEventPayloadV1]:
        """List certified candidates, optionally filtered by strategy type."""
        if strategy_type is None:
            return list(self._certifications)
        return [c for c in self._certifications if c.strategy_type == strategy_type]

    def list_rejections(
        self, strategy_type: str | None = None
    ) -> list[CandidateRejectedAuditEventPayloadV1]:
        """List rejected candidates, optionally filtered by strategy type."""
        if strategy_type is None:
            return list(self._rejections)
        return [r for r in self._rejections if r.strategy_type == strategy_type]

    def is_candidate_certified(self, candidate_id: UUID) -> bool:
        """Check historical certification presence, not present-day authority."""
        return candidate_id in self._certified_candidates
