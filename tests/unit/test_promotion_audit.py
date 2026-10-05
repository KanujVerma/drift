"""Unit tests for promotion audit events, recorder, and archive (M11-4, Issue 261)."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.domain.promotion import (
    CANDIDATE_CERTIFIED_EVENT_TYPE,
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
    build_promotion_gate_config,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.promotion.archive import PromotionArchive
from drift.promotion.gatekeeper import PromotionGatekeeper
from drift.promotion.recorder import (
    PROMOTION_CERTIFICATION_ENTITY_TYPE,
    PROMOTION_EVALUATION_ENTITY_TYPE,
    PROMOTION_REJECTION_ENTITY_TYPE,
    PromotionRecorder,
)
from drift.promotion.runner import (
    CandidatePromotionRequestV1,
    PromotionRunner,
)

EVAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
CAND_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
EVAL_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
CAND_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd04")
TIMESTAMP = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


def test_promotion_recorder_and_archive(tmp_path: Path) -> None:
    """PromotionRecorder seals events into SQLite ledger; archive reconstructs."""
    ledger = SQLiteLedger(tmp_path / "promotion_audit.sqlite3")
    recorder = PromotionRecorder(ledger)
    archive = PromotionArchive(ledger)

    assert len(archive.list_evaluations()) == 0
    assert len(archive.list_certifications()) == 0
    assert len(archive.list_rejections()) == 0

    # Build qualified evaluation record
    rec1 = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CAND_ID_1,
        strategy_type="momentum_v1",
        parameters_hash="a" * 64,
        deflated_sharpe_ratio=Decimal("0.98"),
        pbo_estimate=Decimal("0.10"),
        positive_folds_fraction=Decimal("1.0"),
        max_regime_drawdown=Decimal("0.15"),
        trials_explored_k=5,
        verdict=PromotionGateVerdict.PROMOTION_QUALIFIED,
        evaluated_at=TIMESTAMP,
    )

    ev_eval = recorder.record_evaluation(rec1)
    assert ev_eval.event_type == GATE_EVALUATED_EVENT_TYPE
    assert ev_eval.entity_type == PROMOTION_EVALUATION_ENTITY_TYPE
    assert ev_eval.entity_id == EVAL_ID_1

    ev_cert = recorder.record_certification(rec1)
    assert ev_cert.event_type == CANDIDATE_CERTIFIED_EVENT_TYPE
    assert ev_cert.entity_type == PROMOTION_CERTIFICATION_ENTITY_TYPE
    assert ev_cert.entity_id == CAND_ID_1

    # Build rejected evaluation record
    rec2 = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_2,
        candidate_id=CAND_ID_2,
        strategy_type="reversal_v1",
        parameters_hash="b" * 64,
        deflated_sharpe_ratio=Decimal("0.40"),
        pbo_estimate=Decimal("0.50"),
        positive_folds_fraction=Decimal("0.40"),
        max_regime_drawdown=Decimal("0.35"),
        trials_explored_k=50,
        verdict=PromotionGateVerdict.REJECTED_DEFLATED_SHARPE,
        rejection_reasons=("deflated_sharpe_ratio_below_threshold",),
        evaluated_at=TIMESTAMP,
    )

    recorder.record_evaluation(rec2)
    ev_rej = recorder.record_rejection(rec2)
    assert ev_rej.event_type == CANDIDATE_REJECTED_EVENT_TYPE
    assert ev_rej.entity_type == PROMOTION_REJECTION_ENTITY_TYPE
    assert ev_rej.entity_id == CAND_ID_2

    # Refresh archive and query reconstructed state
    archive.refresh()
    assert len(archive.list_evaluations()) == 2
    assert len(archive.list_certifications()) == 1
    assert len(archive.list_rejections()) == 1

    assert archive.is_candidate_certified(CAND_ID_1)
    assert not archive.is_candidate_certified(CAND_ID_2)

    eval_found = archive.get_evaluation(EVAL_ID_1)
    assert eval_found is not None
    assert eval_found.candidate_id == CAND_ID_1
    assert eval_found.verdict == PromotionGateVerdict.PROMOTION_QUALIFIED


def test_promotion_runner_with_sqlite_ledger(tmp_path: Path) -> None:
    """PromotionRunner seals batches into SQLite ledger, verified via Archive."""
    ledger = SQLiteLedger(tmp_path / "runner_audit.sqlite3")
    recorder = PromotionRecorder(ledger)
    archive = PromotionArchive(ledger)

    config = build_promotion_gate_config(
        config_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd99"),
        created_at=TIMESTAMP,
        is_promotion_grade_authorized=True,
    )
    gk = PromotionGatekeeper(config)
    runner = PromotionRunner(gk, recorder=recorder)

    req1 = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_1,
        strategy_type="momentum_v1",
        parameters_hash="1" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.40"),
        is_pnl_complete=True,
        is_promotion_grade_evidence=True,
    )

    req2 = CandidatePromotionRequestV1(
        candidate_id=CAND_ID_2,
        strategy_type="mean_rev_v1",
        parameters_hash="2" * 64,
        trials_explored_k=1,
        observed_sharpe=Decimal("2.40"),
        is_pnl_complete=False,
        is_promotion_grade_evidence=True,
    )

    batch_res = runner.evaluate_batch([req1, req2])
    assert batch_res.total_candidates == 2

    archive.refresh()
    assert len(archive.list_evaluations()) == 2
    assert len(archive.list_certifications()) == 1
    assert len(archive.list_rejections()) == 1
    assert archive.is_candidate_certified(CAND_ID_1)
    assert not archive.is_candidate_certified(CAND_ID_2)
