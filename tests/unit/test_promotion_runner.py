"""Unit tests for candidate promotion runner and orchestrator (M11-3, Issue 259)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

from drift.domain.promotion import (
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
    build_promotion_gate_config,
)
from drift.promotion.gatekeeper import PromotionGatekeeper
from drift.promotion.runner import (
    CandidatePromotionRequestV1,
    PromotionRecorderProtocol,
    PromotionRunner,
)


class MockPromotionRecorder:
    """In-memory mock recorder for promotion audit events."""

    def __init__(self) -> None:
        self.evaluations: list[PromotionEvaluationRecordV1] = []
        self.certifications: list[PromotionEvaluationRecordV1] = []
        self.rejections: list[PromotionEvaluationRecordV1] = []

    def record_evaluation(self, record: PromotionEvaluationRecordV1) -> Any:
        self.evaluations.append(record)

    def record_certification(self, record: PromotionEvaluationRecordV1) -> Any:
        self.certifications.append(record)

    def record_rejection(self, record: PromotionEvaluationRecordV1) -> Any:
        self.rejections.append(record)


def test_promotion_runner_single_candidate_without_recorder() -> None:
    """Runner evaluates candidate cleanly without recorder."""
    now = datetime.now(UTC)
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)
    runner = PromotionRunner(gk)

    req = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.20"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )
    record = runner.evaluate_candidate(req)
    assert record.verdict == PromotionGateVerdict.PROMOTION_QUALIFIED


def test_promotion_runner_batch_evaluation_and_mock_recorder() -> None:
    """Runner evaluates batch and invokes recorder protocol methods."""
    now = datetime.now(UTC)
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)
    mock_rec = MockPromotionRecorder()
    assert isinstance(mock_rec, PromotionRecorderProtocol)

    runner = PromotionRunner(gk, recorder=mock_rec)

    # 1. Qualified candidate
    req1 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="1" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )

    # 2. Exploratory passed candidate (not promotion grade evidence)
    req2 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="mean_reversion_v1",
        parameters_hash="2" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.10"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=False,
    )

    # 3. Rejected candidate (incomplete pnl basis)
    req3 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="breakout_v1",
        parameters_hash="3" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("3.00"),
        is_pnl_complete=False,
        is_promotion_grade_evidence=True,
    )

    # 4. Rejected candidate (deflated Sharpe under large K)
    req4 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="trend_v1",
        parameters_hash="4" * 64,
        trials_explored_k=100,
        observed_sharpe=Decimal("1.10"),
        trial_sharpes=[Decimal("1.10"), Decimal("0.90"), Decimal("-0.10")],
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )

    batch_res = runner.evaluate_batch([req1, req2, req3, req4])

    assert batch_res.total_candidates == 4
    assert len(batch_res.certified_candidates) == 2
    assert len(batch_res.rejected_candidates) == 2
    assert len(batch_res.records) == 4

    assert (
        batch_res.certified_candidates[0].verdict
        == PromotionGateVerdict.PROMOTION_QUALIFIED
    )
    assert (
        batch_res.certified_candidates[1].verdict
        == PromotionGateVerdict.EXPLORATORY_PASSED
    )
    assert (
        batch_res.rejected_candidates[0].verdict
        == PromotionGateVerdict.REJECTED_INCOMPLETE_EVIDENCE
    )
    assert (
        batch_res.rejected_candidates[1].verdict
        == PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    )

    # Recorder verification
    assert len(mock_rec.evaluations) == 4
    assert len(mock_rec.certifications) == 2
    assert len(mock_rec.rejections) == 2
