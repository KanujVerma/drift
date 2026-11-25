"""Unit tests for candidate promotion runner and orchestrator (M11-3, Issue 259)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

from drift.domain.promotion import (
    PromotionEvaluationRecordV1,
    PromotionGateVerdict,
    build_promotion_gate_config,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.promotion.gatekeeper import PromotionGatekeeper
from drift.promotion.recorder import PromotionRecorder
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
    """Runner refuses an unsealed result without a recorder."""
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
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )
    with pytest.raises(RuntimeError, match="audit recorder"):
        runner.evaluate_candidate(req)


def test_promotion_runner_batch_evaluation_and_mock_recorder(tmp_path: Path) -> None:
    """Untrusted mock refuses; the real recorder seals mixed batch outcomes."""
    now = datetime.now(UTC)
    config = build_promotion_gate_config(
        config_id=uuid7(),
        created_at=now,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)
    mock_rec = MockPromotionRecorder()
    assert isinstance(mock_rec, PromotionRecorderProtocol)

    ledger = SQLiteLedger(tmp_path / "batch.sqlite3")
    runner = PromotionRunner(gk, recorder=PromotionRecorder(ledger))

    # 1. Caller assertions cannot make exploratory evidence promotion-qualified.
    req1 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="momentum_v1",
        parameters_hash="1" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.50"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )

    # 2. Exploratory passed candidate (not promotion grade evidence)
    req2 = CandidatePromotionRequestV1(
        candidate_id=uuid7(),
        strategy_type="mean_reversion_v1",
        parameters_hash="2" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.10"),
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
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
        trial_block_matrix=[[1.0, 1.0], [0.0, 0.0]],
        walk_forward_fold_returns=[[0.01]],
        session_returns=[0.01],
        is_pnl_complete=True,
        skewness=0.0,
        kurtosis=3.0,
        sample_size_n=252,
        is_promotion_grade_evidence=True,
    )

    with pytest.raises(RuntimeError, match="audit recorder"):
        PromotionRunner(gk, recorder=mock_rec).evaluate_candidate(req1)
    with pytest.raises(RuntimeError, match="legacy batch"):
        runner.evaluate_batch([req1, req2, req3, req4])
    assert ledger.verified_events() == ()
    batch_res = runner.evaluate_batch_v2([req1, req2, req3, req4])

    assert len(batch_res.exploratory_candidates) == 2
    assert len(batch_res.rejected_candidates) == 2
    assert len(batch_res.records) == 4

    assert (
        batch_res.exploratory_candidates[0].verdict
        == PromotionGateVerdict.EXPLORATORY_PASSED
    )
    assert (
        batch_res.exploratory_candidates[1].verdict
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

    assert len(ledger.verified_events()) == 5
    assert not mock_rec.evaluations
    assert not mock_rec.certifications
    assert not mock_rec.rejections
