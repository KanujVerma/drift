"""Candidate promotion runner and pipeline orchestrator (M11-3, Issue 259).

Orchestrates multi-candidate promotion evaluations across the four statistical
gatekeeper pillars, manages optional M0 ledger audit event recording, and
provides batch results for downstream Shadow Broker pipelines.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from drift.domain.common import FrozenModel
from drift.domain.promotion import (
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
)
from drift.promotion.gatekeeper import PromotionGatekeeper

__all__ = [
    "CandidatePromotionRequestV1",
    "PromotionBatchResultV1",
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
    is_pnl_complete: bool = True
    is_promotion_grade_evidence: bool = False
    skewness: Decimal | float = 0.0
    kurtosis: Decimal | float = 3.0
    sample_size_n: int = 252


class PromotionBatchResultV1(FrozenModel):
    """Immutable batch evaluation result across strategy candidates."""

    total_candidates: int
    certified_candidates: tuple[PromotionEvaluationRecordV1, ...]
    rejected_candidates: tuple[PromotionEvaluationRecordV1, ...]
    records: tuple[PromotionEvaluationRecordV1, ...]


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
    ) -> PromotionEvaluationRecordV1:
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
        )

        if self.recorder is not None:
            self.recorder.record_evaluation(record)
            if record.verdict in (
                PromotionGateVerdict.PROMOTION_QUALIFIED,
                PromotionGateVerdict.EXPLORATORY_PASSED,
            ):
                self.recorder.record_certification(record)
            else:
                self.recorder.record_rejection(record)

        return record

    def evaluate_batch(
        self,
        requests: Sequence[CandidatePromotionRequestV1],
    ) -> PromotionBatchResultV1:
        """Evaluate a sequence of candidate requests in deterministic order."""
        records: list[PromotionEvaluationRecordV1] = []
        certified: list[PromotionEvaluationRecordV1] = []
        rejected: list[PromotionEvaluationRecordV1] = []

        for req in requests:
            rec = self.evaluate_candidate(req)
            records.append(rec)
            if rec.verdict in (
                PromotionGateVerdict.PROMOTION_QUALIFIED,
                PromotionGateVerdict.EXPLORATORY_PASSED,
            ):
                certified.append(rec)
            else:
                rejected.append(rec)

        return PromotionBatchResultV1(
            total_candidates=len(requests),
            certified_candidates=tuple(certified),
            rejected_candidates=tuple(rejected),
            records=tuple(records),
        )
