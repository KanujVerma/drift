"""Unit tests for promotion domain models, schemas, and payloads (M11-1)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.promotion import (
    CANDIDATE_CERTIFIED_EVENT_TYPE,
    CANDIDATE_REJECTED_EVENT_TYPE,
    GATE_EVALUATED_EVENT_TYPE,
    CandidateCertifiedAuditEventPayloadV1,
    CandidateRejectedAuditEventPayloadV1,
    GateEvaluatedAuditEventPayloadV1,
    PromotionEvaluationRecordV1,
    PromotionGateConfigV1,
    PromotionGateVerdict,
    build_promotion_evaluation_record,
    build_promotion_gate_config,
)

TIMESTAMP = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
CONFIG_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
EVAL_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
CANDIDATE_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
DUMMY_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def test_promotion_gate_config_bounds_and_tamper() -> None:
    config = build_promotion_gate_config(
        config_id=CONFIG_ID_1,
        created_at=TIMESTAMP,
        min_dsr=Decimal("0.95"),
        max_pbo=Decimal("0.25"),
        min_positive_folds_fraction=Decimal("0.80"),
        max_regime_drawdown=Decimal("0.20"),
        is_promotion_grade_authorized=True,
    )

    assert config.config_id == CONFIG_ID_1
    assert config.min_dsr == Decimal("0.95")
    assert config.max_pbo == Decimal("0.25")
    assert config.is_promotion_grade_authorized is True
    assert len(config.config_hash) == 64

    # Out of bounds min_dsr (< 0.50) rejected
    with pytest.raises(ValidationError):
        build_promotion_gate_config(
            config_id=CONFIG_ID_1,
            created_at=TIMESTAMP,
            min_dsr=Decimal("0.40"),
        )

    # Out of bounds max_pbo (> 0.50) rejected
    with pytest.raises(ValidationError):
        build_promotion_gate_config(
            config_id=CONFIG_ID_1,
            created_at=TIMESTAMP,
            max_pbo=Decimal("0.60"),
        )

    # Tamper with config
    tampered = config.model_dump()
    tampered["min_dsr"] = Decimal("0.99")
    with pytest.raises(ValidationError, match="hash mismatch"):
        PromotionGateConfigV1.model_validate(tampered)


def test_promotion_evaluation_record_construction_and_tamper() -> None:
    rec = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CANDIDATE_ID_1,
        strategy_type="b4_momentum",
        parameters_hash=DUMMY_HASH,
        deflated_sharpe_ratio=Decimal("0.98"),
        pbo_estimate=Decimal("0.15"),
        positive_folds_fraction=Decimal("0.85"),
        max_regime_drawdown=Decimal("0.18"),
        trials_explored_k=25,
        verdict=PromotionGateVerdict.PROMOTION_QUALIFIED,
        evaluated_at=TIMESTAMP,
    )

    assert rec.evaluation_id == EVAL_ID_1
    assert rec.verdict == PromotionGateVerdict.PROMOTION_QUALIFIED
    assert rec.trials_explored_k == 25
    assert len(rec.record_hash) == 64

    # Negative/zero K rejected
    with pytest.raises(ValidationError):
        build_promotion_evaluation_record(
            evaluation_id=EVAL_ID_1,
            candidate_id=CANDIDATE_ID_1,
            strategy_type="b4_momentum",
            parameters_hash=DUMMY_HASH,
            deflated_sharpe_ratio=Decimal("0.98"),
            pbo_estimate=Decimal("0.15"),
            positive_folds_fraction=Decimal("0.85"),
            max_regime_drawdown=Decimal("0.18"),
            trials_explored_k=0,
            verdict=PromotionGateVerdict.PROMOTION_QUALIFIED,
            evaluated_at=TIMESTAMP,
        )

    # Tamper with record
    tampered = rec.model_dump()
    tampered["verdict"] = PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    with pytest.raises(ValidationError, match="hash mismatch"):
        PromotionEvaluationRecordV1.model_validate(tampered)


def test_promotion_audit_event_payloads() -> None:
    rec = build_promotion_evaluation_record(
        evaluation_id=EVAL_ID_1,
        candidate_id=CANDIDATE_ID_1,
        strategy_type="b4_momentum",
        parameters_hash=DUMMY_HASH,
        deflated_sharpe_ratio=Decimal("0.96"),
        pbo_estimate=Decimal("0.20"),
        positive_folds_fraction=Decimal("0.80"),
        max_regime_drawdown=Decimal("0.22"),
        trials_explored_k=10,
        verdict=PromotionGateVerdict.EXPLORATORY_PASSED,
        evaluated_at=TIMESTAMP,
    )

    # 1. GateEvaluated
    p1 = GateEvaluatedAuditEventPayloadV1(evaluation=rec)
    assert p1.evaluation == rec
    assert GATE_EVALUATED_EVENT_TYPE == "m11.gate.evaluated"

    # 2. CandidateCertified
    p2 = CandidateCertifiedAuditEventPayloadV1(
        evaluation_id=EVAL_ID_1,
        candidate_id=CANDIDATE_ID_1,
        strategy_type="b4_momentum",
        verdict=PromotionGateVerdict.EXPLORATORY_PASSED,
        certified_at=TIMESTAMP,
    )
    assert p2.verdict == PromotionGateVerdict.EXPLORATORY_PASSED
    assert CANDIDATE_CERTIFIED_EVENT_TYPE == "m11.candidate.certified"

    # 3. CandidateRejected
    p3 = CandidateRejectedAuditEventPayloadV1(
        evaluation_id=EVAL_ID_1,
        candidate_id=CANDIDATE_ID_1,
        strategy_type="b4_momentum",
        verdict=PromotionGateVerdict.REJECTED_DEFLATED_SHARPE,
        rejection_reasons=("DSR 0.88 < required 0.95",),
        rejected_at=TIMESTAMP,
    )
    assert p3.verdict == PromotionGateVerdict.REJECTED_DEFLATED_SHARPE
    assert CANDIDATE_REJECTED_EVENT_TYPE == "m11.candidate.rejected"
