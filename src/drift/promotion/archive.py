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
    CandidateCertifiedAuditEventPayloadV1,
    CandidateRejectedAuditEventPayloadV1,
    PromotionEvaluationRecordV1,
)
from drift.ledger.interface import Ledger
from drift.serialization.canonical import canonical_json

__all__ = ["PromotionArchive"]


class PromotionArchive:
    """Historical archive reconstructing promotion state from immutable ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._evaluations: dict[UUID, PromotionEvaluationRecordV1] = {}
        self._certifications: list[CandidateCertifiedAuditEventPayloadV1] = []
        self._rejections: list[CandidateRejectedAuditEventPayloadV1] = []
        self._certified_candidates: dict[
            UUID, CandidateCertifiedAuditEventPayloadV1
        ] = {}
        self.refresh()

    def refresh(self) -> None:
        """Scan ledger events and synchronize promotion state."""
        self._evaluations.clear()
        self._certifications.clear()
        self._rejections.clear()
        self._certified_candidates.clear()

        for event in self.ledger.events():
            if not isinstance(event.payload, Mapping):
                continue

            if event.event_type == GATE_EVALUATED_EVENT_TYPE:
                eval_raw = event.payload.get("evaluation")
                if isinstance(eval_raw, Mapping):
                    try:
                        record = PromotionEvaluationRecordV1.model_validate_json(
                            canonical_json(dict(eval_raw))
                        )
                        self._evaluations[record.evaluation_id] = record
                    except Exception:
                        continue

            elif event.event_type == CANDIDATE_CERTIFIED_EVENT_TYPE:
                try:
                    cert_payload = (
                        CandidateCertifiedAuditEventPayloadV1.model_validate_json(
                            canonical_json(dict(event.payload))
                        )
                    )
                    self._certifications.append(cert_payload)
                    self._certified_candidates[cert_payload.candidate_id] = cert_payload
                except Exception:
                    continue

            elif event.event_type == CANDIDATE_REJECTED_EVENT_TYPE:
                try:
                    rej_payload = (
                        CandidateRejectedAuditEventPayloadV1.model_validate_json(
                            canonical_json(dict(event.payload))
                        )
                    )
                    self._rejections.append(rej_payload)
                except Exception:
                    continue

    def get_evaluation(self, evaluation_id: UUID) -> PromotionEvaluationRecordV1 | None:
        """Retrieve evaluation record by ID."""
        return self._evaluations.get(evaluation_id)

    def list_evaluations(self) -> list[PromotionEvaluationRecordV1]:
        """List all promotion evaluation records in chronological order."""
        return list(self._evaluations.values())

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
        """Check if candidate is certified in the archive."""
        return candidate_id in self._certified_candidates
