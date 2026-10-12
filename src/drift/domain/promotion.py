"""Promotion gate domain models, schemas, and payloads (M11-1, Issue 255).

Provides immutable domain models for statistical promotion gatekeeping,
including Deflated Sharpe Ratio (DSR), Probability of Backtest Overfitting (PBO),
walk-forward out-of-sample consistency, and regime shift verification.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.serialization.canonical import content_hash

PROMOTION_SCHEMA_VERSION: Literal["1"] = "1"
GATE_EVALUATED_EVENT_TYPE: NonBlankStr = "m11.gate.evaluated"
CANDIDATE_CERTIFIED_EVENT_TYPE: NonBlankStr = "m11.candidate.certified"
CANDIDATE_REJECTED_EVENT_TYPE: NonBlankStr = "m11.candidate.rejected"

__all__ = [
    "CANDIDATE_CERTIFIED_EVENT_TYPE",
    "CANDIDATE_REJECTED_EVENT_TYPE",
    "GATE_EVALUATED_EVENT_TYPE",
    "PROMOTION_SCHEMA_VERSION",
    "CandidateCertifiedAuditEventPayloadV1",
    "CandidateRejectedAuditEventPayloadV1",
    "GateEvaluatedAuditEventPayloadV1",
    "PromotionEvaluationRecordV1",
    "PromotionGateConfigV1",
    "PromotionGateVerdict",
    "build_promotion_evaluation_record",
    "build_promotion_gate_config",
    "compute_promotion_evaluation_record_hash",
    "compute_promotion_gate_config_hash",
]


class PromotionGateVerdict(StrEnum):
    """Terminal decision for candidate statistical promotion gatekeeping."""

    PROMOTION_QUALIFIED = "promotion_qualified"
    EXPLORATORY_PASSED = "exploratory_passed"
    REJECTED_DEFLATED_SHARPE = "rejected_deflated_sharpe"
    REJECTED_PBO_OVERFITTING = "rejected_pbo_overfitting"
    REJECTED_WALK_FORWARD_DEGRADATION = "rejected_walk_forward_degradation"
    REJECTED_REGIME_INSTABILITY = "rejected_regime_instability"
    REJECTED_INCOMPLETE_EVIDENCE = "rejected_incomplete_evidence"


# =========================================================================
# Hash Computation Functions
# =========================================================================


def compute_promotion_gate_config_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for PromotionGateConfigV1."""
    d = dict(unsigned)
    d.pop("config_hash", None)
    return content_hash(d)


def compute_promotion_evaluation_record_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash for PromotionEvaluationRecordV1."""
    d = dict(unsigned)
    d.pop("record_hash", None)
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class PromotionGateConfigV1(FrozenModel):
    """Configuration governing statistical promotion gatekeeping thresholds."""

    schema_version: Literal["1"] = PROMOTION_SCHEMA_VERSION
    config_id: UUID7
    min_dsr: Decimal = Field(
        default=Decimal("0.95"), ge=Decimal("0.50"), le=Decimal("1.0")
    )
    max_pbo: Decimal = Field(
        default=Decimal("0.30"), ge=Decimal("0.0"), le=Decimal("0.50")
    )
    min_positive_folds_fraction: Decimal = Field(
        default=Decimal("0.80"), ge=Decimal("0.50"), le=Decimal("1.0")
    )
    max_regime_drawdown: Decimal = Field(
        default=Decimal("0.25"), ge=Decimal("0.05"), le=Decimal("0.50")
    )
    is_promotion_grade_authorized: bool = False
    created_at: UTCDateTime
    config_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_config_integrity(self) -> Self:
        expected = compute_promotion_gate_config_hash(self.model_dump(mode="python"))
        if self.config_hash != expected:
            raise ValueError("promotion gate config hash mismatch")
        return self


class PromotionEvaluationRecordV1(FrozenModel):
    """Immutable evaluation record of candidate statistical gatekeeping."""

    schema_version: Literal["1"] = PROMOTION_SCHEMA_VERSION
    evaluation_id: UUID7
    candidate_id: UUID7
    strategy_type: NonBlankStr
    parameters_hash: SHA256Hash
    deflated_sharpe_ratio: Decimal
    pbo_estimate: Decimal
    positive_folds_fraction: Decimal
    max_regime_drawdown: Decimal
    trials_explored_k: int = Field(ge=1)
    verdict: PromotionGateVerdict
    rejection_reasons: tuple[str, ...] = ()
    evaluated_at: UTCDateTime
    record_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_record_integrity(self) -> Self:
        expected = compute_promotion_evaluation_record_hash(
            self.model_dump(mode="python")
        )
        if self.record_hash != expected:
            raise ValueError("promotion evaluation record hash mismatch")
        return self


# =========================================================================
# Ledger Audit Event Payloads
# =========================================================================


class GateEvaluatedAuditEventPayloadV1(FrozenModel):
    """Payload for m11.gate.evaluated audit events sealed into ledger."""

    schema_version: Literal["1"] = PROMOTION_SCHEMA_VERSION
    evaluation: PromotionEvaluationRecordV1


class CandidateCertifiedAuditEventPayloadV1(FrozenModel):
    """Payload for m11.candidate.certified audit events sealed into ledger."""

    schema_version: Literal["1"] = PROMOTION_SCHEMA_VERSION
    evaluation_id: UUID7
    candidate_id: UUID7
    strategy_type: NonBlankStr
    verdict: PromotionGateVerdict
    certified_at: UTCDateTime


class CandidateRejectedAuditEventPayloadV1(FrozenModel):
    """Payload for m11.candidate.rejected audit events sealed into ledger."""

    schema_version: Literal["1"] = PROMOTION_SCHEMA_VERSION
    evaluation_id: UUID7
    candidate_id: UUID7
    strategy_type: NonBlankStr
    verdict: PromotionGateVerdict
    rejection_reasons: tuple[str, ...]
    rejected_at: UTCDateTime


# =========================================================================
# Builder Helpers
# =========================================================================


def build_promotion_gate_config(
    *,
    config_id: UUID,
    created_at: UTCDateTime,
    min_dsr: Decimal = Decimal("0.95"),
    max_pbo: Decimal = Decimal("0.30"),
    min_positive_folds_fraction: Decimal = Decimal("0.80"),
    max_regime_drawdown: Decimal = Decimal("0.25"),
    is_promotion_grade_authorized: bool = False,
) -> PromotionGateConfigV1:
    """Construct an immutable PromotionGateConfigV1 with computed hash."""
    unsigned = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "config_id": config_id,
        "min_dsr": min_dsr,
        "max_pbo": max_pbo,
        "min_positive_folds_fraction": min_positive_folds_fraction,
        "max_regime_drawdown": max_regime_drawdown,
        "is_promotion_grade_authorized": is_promotion_grade_authorized,
        "created_at": created_at,
    }
    c_hash = compute_promotion_gate_config_hash(unsigned)
    return PromotionGateConfigV1.model_validate(
        {
            **unsigned,
            "config_hash": c_hash,
        }
    )


def build_promotion_evaluation_record(
    *,
    evaluation_id: UUID,
    candidate_id: UUID,
    strategy_type: NonBlankStr,
    parameters_hash: SHA256Hash,
    deflated_sharpe_ratio: Decimal,
    pbo_estimate: Decimal,
    positive_folds_fraction: Decimal,
    max_regime_drawdown: Decimal,
    trials_explored_k: int,
    verdict: PromotionGateVerdict,
    evaluated_at: UTCDateTime,
    rejection_reasons: tuple[str, ...] = (),
) -> PromotionEvaluationRecordV1:
    """Construct an immutable PromotionEvaluationRecordV1 with computed hash."""
    unsigned = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "candidate_id": candidate_id,
        "strategy_type": strategy_type,
        "parameters_hash": parameters_hash,
        "deflated_sharpe_ratio": deflated_sharpe_ratio,
        "pbo_estimate": pbo_estimate,
        "positive_folds_fraction": positive_folds_fraction,
        "max_regime_drawdown": max_regime_drawdown,
        "trials_explored_k": trials_explored_k,
        "verdict": verdict,
        "rejection_reasons": rejection_reasons,
        "evaluated_at": evaluated_at,
    }
    r_hash = compute_promotion_evaluation_record_hash(unsigned)
    return PromotionEvaluationRecordV1.model_validate(
        {
            **unsigned,
            "record_hash": r_hash,
        }
    )
