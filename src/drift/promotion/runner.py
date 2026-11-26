"""Candidate promotion runner and pipeline orchestrator (M11-3, Issue 259).

Orchestrates multi-candidate promotion evaluations across the four statistical
gatekeeper pillars, manages optional M0 ledger audit event recording, and
provides batch results for downstream Shadow Broker pipelines.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid7

from drift.domain.common import FrozenModel
from drift.domain.events import AuditEvent
from drift.domain.promotion import (
    IncompletePromotionRejectionV2,
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
)
from drift.promotion.gatekeeper import PromotionGatekeeper, _snapshot_evidence
from drift.promotion.recorder import PromotionRecorder

__all__ = [
    "CandidatePromotionRequestV1",
    "PromotionBatchResultV1",
    "PromotionBatchResultV2",
    "PromotionBatchInterrupted",
    "PromotionRecorderProtocol",
    "PromotionRunner",
]


@runtime_checkable
class PromotionRecorderProtocol(Protocol):
    """Protocol for recording promotion gate audit events into M0 ledger."""

    def record_evaluation(self, record: PromotionEvaluationRecordV1) -> Any: ...

    def record_certification(self, record: PromotionEvaluationRecordV1) -> Any: ...

    def record_rejection(self, record: PromotionEvaluationRecordV1) -> Any: ...


@dataclass(frozen=True)
class CandidatePromotionRequestV1:
    """Submission payload for evaluating a strategy candidate against promotion gate."""

    candidate_id: UUID
    strategy_type: str
    parameters_hash: str
    trials_explored_k: int
    observed_sharpe: Decimal | float
    trial_sharpes: Sequence[Decimal | float] | None = None
    trial_block_matrix: Sequence[Sequence[Decimal | float]] | None = None
    walk_forward_fold_returns: Sequence[Sequence[Decimal | float]] | None = None
    session_returns: Sequence[Decimal | float] | None = None
    is_pnl_complete: bool = False
    is_promotion_grade_evidence: bool = False
    skewness: Decimal | float | None = None
    kurtosis: Decimal | float | None = None
    sample_size_n: int | None = None
    evaluation_id: UUID = field(default_factory=uuid7)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name in (
            "trial_sharpes",
            "trial_block_matrix",
            "walk_forward_fold_returns",
            "session_returns",
        ):
            object.__setattr__(self, name, _snapshot_evidence(getattr(self, name)))


class PromotionBatchResultV1(FrozenModel):
    """Immutable batch evaluation result across strategy candidates."""

    total_candidates: int
    certified_candidates: tuple[PromotionEvaluationRecordV1, ...]
    rejected_candidates: tuple[PromotionEvaluationRecordV1, ...]
    records: tuple[PromotionEvaluationRecordV1, ...]


type PromotionOutcome = PromotionEvaluationRecordV1 | IncompletePromotionRejectionV2


@dataclass(frozen=True)
class PromotionBatchResultV2:
    """Ordered results without misrepresenting exploratory passes as certifications."""

    records: tuple[PromotionOutcome, ...]
    exploratory_candidates: tuple[PromotionEvaluationRecordV1, ...]
    rejected_candidates: tuple[PromotionOutcome, ...]


class PromotionBatchInterrupted(RuntimeError):
    """A batch is not transactional; expose completed and interrupted work."""

    def __init__(
        self,
        committed_prefix: tuple[PromotionOutcome, ...],
        failed_attempt: CandidatePromotionRequestV1,
        unprocessed_suffix: tuple[CandidatePromotionRequestV1, ...],
        failed_events: tuple[AuditEvent, ...] | None,
    ) -> None:
        super().__init__(
            "batch interrupted; inspect failed attempt and committed prefix"
        )
        self.committed_prefix = committed_prefix
        self.failed_attempt = failed_attempt
        self.unprocessed_suffix = unprocessed_suffix
        self.failed_events = failed_events


class PromotionRunner:
    """Pipeline orchestrator for candidate promotion gate evaluation."""

    def __init__(
        self,
        gatekeeper: PromotionGatekeeper,
        recorder: PromotionRecorderProtocol | None = None,
    ) -> None:
        self.gatekeeper = gatekeeper
        self.recorder = recorder

    def evaluate_candidate(
        self,
        request: CandidatePromotionRequestV1,
    ) -> PromotionEvaluationRecordV1 | IncompletePromotionRejectionV2:
        """Evaluate a single candidate request through the promotion gate."""
        record = self.gatekeeper.evaluate_candidate(
            candidate_id=request.candidate_id,
            strategy_type=request.strategy_type,
            parameters_hash=request.parameters_hash,
            trials_explored_k=request.trials_explored_k,
            observed_sharpe=request.observed_sharpe,
            trial_sharpes=request.trial_sharpes,
            trial_block_matrix=request.trial_block_matrix,
            walk_forward_fold_returns=request.walk_forward_fold_returns,
            session_returns=request.session_returns,
            is_pnl_complete=request.is_pnl_complete,
            is_promotion_grade_evidence=request.is_promotion_grade_evidence,
            skewness=request.skewness,
            kurtosis=request.kurtosis,
            sample_size_n=request.sample_size_n,
            evaluation_id=request.evaluation_id,
            evaluated_at=request.evaluated_at,
            recorder=self.recorder
            if isinstance(self.recorder, PromotionRecorder)
            else None,
        )

        return record

    def evaluate_batch(
        self,
        requests: Sequence[CandidatePromotionRequestV1],
    ) -> PromotionBatchResultV1:
        """Refuse the legacy batch view, which calls exploratory passes certified."""
        raise RuntimeError(
            "legacy batch cannot represent outcomes; use evaluate_batch_v2"
        )

    def evaluate_batch_v2(
        self,
        requests: Sequence[CandidatePromotionRequestV1],
    ) -> PromotionBatchResultV2:
        requests = tuple(requests)
        records: list[PromotionOutcome] = []
        for index, req in enumerate(requests):
            try:
                records.append(self.evaluate_candidate(req))
            except Exception as error:
                failed_events: tuple[AuditEvent, ...] | None = None
                if isinstance(self.recorder, PromotionRecorder):
                    try:
                        keys = {
                            f"m11:eval:{req.evaluation_id}",
                            f"m11:rej:{req.evaluation_id}",
                        }
                        failed_events = tuple(
                            e
                            for e in self.recorder.ledger.verified_events()
                            if e.deduplication_key in keys
                        )
                    except Exception:
                        pass
                raise PromotionBatchInterrupted(
                    tuple(records),
                    req,
                    tuple(requests[index + 1 :]),
                    failed_events,
                ) from error
        return PromotionBatchResultV2(
            records=tuple(records),
            exploratory_candidates=tuple(
                record
                for record in records
                if isinstance(record, PromotionEvaluationRecordV1)
                and record.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
            ),
            rejected_candidates=tuple(
                record
                for record in records
                if record.verdict != PromotionGateVerdict.EXPLORATORY_PASSED
            ),
        )
