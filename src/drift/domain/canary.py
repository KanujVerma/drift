"""Canary domain models, policy configurations, and settlement reports (M17-1).

Provides immutable domain models for the Tiny-Money Canary layer enforcing
micro-capital boundaries, single-share constraints, and settlement reconciliation
per ADR 0011, ADR 0013, and ADR 0014.
"""

from datetime import datetime
from decimal import Decimal
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
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    canonical_money,
)
from drift.serialization.canonical import content_hash

CANARY_SCHEMA_VERSION: Literal["1"] = "1"
CANARY_SETTLEMENT_REPORT_PROFILE = "drift-canary-settlement-report-v1"

__all__ = [
    "CANARY_SCHEMA_VERSION",
    "CANARY_SETTLEMENT_REPORT_PROFILE",
    "CanaryEvaluationResultV1",
    "CanaryPolicyV1",
    "CanarySettlementReportV1",
    "build_canary_settlement_report",
    "compute_canary_settlement_report_hash",
]


def compute_canary_settlement_report_hash(
    *,
    schema_version: str,
    report_id: UUID,
    intent_id: UUID,
    broker_order_id: str | None,
    is_settled: bool,
    expected_notional: Decimal,
    actual_fill_notional: Decimal,
    fee_amount: Decimal,
    cash_balance_delta: Decimal,
    reconciliation_difference: Decimal,
    slippage_bps: Decimal,
    evaluated_at: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for a canary settlement report."""
    payload: dict[str, Any] = {
        "profile": CANARY_SETTLEMENT_REPORT_PROFILE,
        "schema_version": schema_version,
        "report_id": str(report_id),
        "intent_id": str(intent_id),
        "broker_order_id": broker_order_id,
        "is_settled": is_settled,
        "expected_notional": str(expected_notional),
        "actual_fill_notional": str(actual_fill_notional),
        "fee_amount": str(fee_amount),
        "cash_balance_delta": str(cash_balance_delta),
        "reconciliation_difference": str(reconciliation_difference),
        "slippage_bps": str(slippage_bps),
        "evaluated_at": evaluated_at.isoformat(),
    }
    return content_hash(payload)


class CanaryPolicyV1(FrozenModel):
    """Immutable policy governing tiny-money canary order limits and authorization."""

    schema_version: Literal["1"] = CANARY_SCHEMA_VERSION
    canary_authorized: bool = False
    max_order_notional: CanonicalMoney = Decimal("5.00")
    max_cumulative_notional: CanonicalMoney = Decimal("25.00")
    max_order_quantity: int = Field(default=1, gt=0)
    whitelisted_symbols: frozenset[str] = frozenset()
    max_slippage_bps: int = Field(default=50, ge=0)

    @model_validator(mode="after")
    def validate_policy_bounds(self) -> Self:
        if self.max_order_notional <= Decimal("0"):
            raise ValueError("max_order_notional must be positive")
        if self.max_cumulative_notional < self.max_order_notional:
            raise ValueError(
                "max_cumulative_notional cannot be less than max_order_notional"
            )
        return self


class CanaryEvaluationResultV1(FrozenModel):
    """Result of evaluating an order intent against the active CanaryPolicyV1."""

    schema_version: Literal["1"] = CANARY_SCHEMA_VERSION
    decision: Literal["admitted", "refused"]
    refusal_reasons: tuple[str, ...] = ()
    order_notional: CanonicalMoney
    cumulative_allocated_notional: CanonicalMoney


class CanarySettlementReportV1(FrozenModel):
    """Settlement and fill reconciliation report for a canary execution event."""

    schema_version: Literal["1"] = CANARY_SCHEMA_VERSION
    report_id: UUID7
    intent_id: UUID7
    broker_order_id: NonBlankStr | None = None
    is_settled: bool
    expected_notional: CanonicalMoney
    actual_fill_notional: CanonicalMoney
    fee_amount: CanonicalMoney = Decimal("0")
    cash_balance_delta: CanonicalMoney
    reconciliation_difference: CanonicalMoney
    slippage_bps: Decimal
    evaluated_at: UTCDateTime
    report_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        expected_hash = compute_canary_settlement_report_hash(
            schema_version=self.schema_version,
            report_id=self.report_id,
            intent_id=self.intent_id,
            broker_order_id=self.broker_order_id,
            is_settled=self.is_settled,
            expected_notional=self.expected_notional,
            actual_fill_notional=self.actual_fill_notional,
            fee_amount=self.fee_amount,
            cash_balance_delta=self.cash_balance_delta,
            reconciliation_difference=self.reconciliation_difference,
            slippage_bps=self.slippage_bps,
            evaluated_at=self.evaluated_at,
        )
        if self.report_hash != expected_hash:
            raise ValueError(
                f"report_hash mismatch: expected {expected_hash}, "
                f"got {self.report_hash}"
            )
        return self


def build_canary_settlement_report(
    *,
    report_id: UUID,
    intent_id: UUID,
    broker_order_id: str | None = None,
    is_settled: bool,
    expected_notional: Decimal,
    actual_fill_notional: Decimal,
    fee_amount: Decimal = Decimal("0"),
    cash_balance_delta: Decimal,
    reconciliation_difference: Decimal,
    slippage_bps: Decimal,
    evaluated_at: datetime,
) -> CanarySettlementReportV1:
    """Build an immutable CanarySettlementReportV1 with automatic hash computation."""
    c_exp = canonical_money(expected_notional)
    c_act = canonical_money(actual_fill_notional)
    c_fee = canonical_money(fee_amount)
    c_cash_delta = canonical_money(cash_balance_delta)
    c_diff = canonical_money(reconciliation_difference)

    h = compute_canary_settlement_report_hash(
        schema_version=CANARY_SCHEMA_VERSION,
        report_id=report_id,
        intent_id=intent_id,
        broker_order_id=broker_order_id,
        is_settled=is_settled,
        expected_notional=c_exp,
        actual_fill_notional=c_act,
        fee_amount=c_fee,
        cash_balance_delta=c_cash_delta,
        reconciliation_difference=c_diff,
        slippage_bps=slippage_bps,
        evaluated_at=evaluated_at,
    )

    return CanarySettlementReportV1(
        schema_version=CANARY_SCHEMA_VERSION,
        report_id=report_id,
        intent_id=intent_id,
        broker_order_id=broker_order_id,
        is_settled=is_settled,
        expected_notional=c_exp,
        actual_fill_notional=c_act,
        fee_amount=c_fee,
        cash_balance_delta=c_cash_delta,
        reconciliation_difference=c_diff,
        slippage_bps=slippage_bps,
        evaluated_at=evaluated_at,
        report_hash=h,
    )
