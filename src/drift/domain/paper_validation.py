"""Domain models, market ticks, and execution drift schemas (M15-1).

Specifies immutable domain structures for real-world paper and shadow validation:
- MarketTickV1: point-in-time quote and trade updates with bid/ask spreads.
- ExecutionDriftReportV1: measures intended vs simulated execution price slippage.
- ShadowValidationSummaryV1: aggregate session validation and drift metrics.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    canonical_money,
    decimal_context,
)
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

PAPER_VALIDATION_SCHEMA_VERSION: Literal["1"] = "1"

__all__ = [
    "PAPER_VALIDATION_SCHEMA_VERSION",
    "ExecutionDriftReportV1",
    "MarketTickV1",
    "ShadowValidationSummaryV1",
    "build_execution_drift_report",
    "build_market_tick",
    "build_shadow_validation_summary",
    "compute_execution_drift_hash",
    "compute_market_tick_hash",
    "compute_shadow_validation_summary_hash",
]


# =========================================================================
# Canonical Hashing Functions
# =========================================================================


def compute_market_tick_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute deterministic SHA-256 content hash for MarketTickV1."""
    d = dict(unsigned)
    d.pop("tick_hash", None)
    with decimal_context():
        if d.get("bid_price") is not None and isinstance(d["bid_price"], Decimal):
            d["bid_price"] = canonical_money(d["bid_price"])
        if d.get("ask_price") is not None and isinstance(d["ask_price"], Decimal):
            d["ask_price"] = canonical_money(d["ask_price"])
        if d.get("last_price") is not None and isinstance(d["last_price"], Decimal):
            d["last_price"] = canonical_money(d["last_price"])
    return content_hash(d)


def compute_execution_drift_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute deterministic SHA-256 content hash for ExecutionDriftReportV1."""
    d = dict(unsigned)
    d.pop("drift_hash", None)
    with decimal_context():
        if d.get("intended_price") is not None and isinstance(
            d["intended_price"], Decimal
        ):
            d["intended_price"] = canonical_money(d["intended_price"])
        if d.get("fill_price") is not None and isinstance(d["fill_price"], Decimal):
            d["fill_price"] = canonical_money(d["fill_price"])
        if d.get("slippage_bps") is not None and isinstance(d["slippage_bps"], Decimal):
            d["slippage_bps"] = canonical_money(d["slippage_bps"])
    return content_hash(d)


def compute_shadow_validation_summary_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute deterministic SHA-256 content hash for ShadowValidationSummaryV1."""
    d = dict(unsigned)
    d.pop("summary_hash", None)
    with decimal_context():
        for field in (
            "total_slippage_bps",
            "mean_slippage_bps",
            "max_slippage_bps",
            "final_equity",
        ):
            if d.get(field) is not None and isinstance(d[field], Decimal):
                d[field] = canonical_money(d[field])
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class MarketTickV1(FrozenModel):
    """Point-in-time market quote and trade tick."""

    schema_version: Literal["1"] = PAPER_VALIDATION_SCHEMA_VERSION
    tick_id: UUID7
    security_id: UUID7
    timestamp: UTCDateTime
    bid_price: CanonicalMoney | None = None
    bid_size: int | None = Field(default=None, ge=0)
    ask_price: CanonicalMoney | None = None
    ask_size: int | None = Field(default=None, ge=0)
    last_price: CanonicalMoney
    last_size: int = Field(ge=0)
    tick_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_tick(self) -> Self:
        if self.last_price <= Decimal("0"):
            raise ValueError("last_price must be strictly positive")
        if self.bid_price is not None and self.ask_price is not None:
            if self.bid_price > self.ask_price:
                raise ValueError(
                    "crossed market condition: bid_price exceeds ask_price"
                )
        if self.bid_price is not None and self.bid_price <= Decimal("0"):
            raise ValueError("bid_price must be strictly positive")
        if self.ask_price is not None and self.ask_price <= Decimal("0"):
            raise ValueError("ask_price must be strictly positive")

        expected = compute_market_tick_hash(self.model_dump(mode="python"))
        if self.tick_hash != expected:
            raise ValueError(
                f"tick_hash mismatch: expected {expected}, got {self.tick_hash}"
            )
        return self


class ExecutionDriftReportV1(FrozenModel):
    """Point-in-time measurement of price slippage and execution drift."""

    schema_version: Literal["1"] = PAPER_VALIDATION_SCHEMA_VERSION
    drift_id: UUID7
    intent_id: UUID7
    security_id: UUID7
    intended_price: CanonicalMoney
    fill_price: CanonicalMoney
    slippage_bps: CanonicalMoney
    recorded_at: UTCDateTime
    drift_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_drift(self) -> Self:
        if self.intended_price <= Decimal("0"):
            raise ValueError("intended_price must be strictly positive")
        if self.fill_price <= Decimal("0"):
            raise ValueError("fill_price must be strictly positive")

        expected = compute_execution_drift_hash(self.model_dump(mode="python"))
        if self.drift_hash != expected:
            raise ValueError(
                f"drift_hash mismatch: expected {expected}, got {self.drift_hash}"
            )
        return self


class ShadowValidationSummaryV1(FrozenModel):
    """Aggregate summary of a paper or shadow validation session."""

    schema_version: Literal["1"] = PAPER_VALIDATION_SCHEMA_VERSION
    validation_id: UUID7
    session_key: SessionKeyV1
    total_ticks_processed: int = Field(ge=0)
    orders_generated: int = Field(ge=0)
    orders_approved: int = Field(ge=0)
    orders_rejected_risk: int = Field(ge=0)
    orders_filled: int = Field(ge=0)
    total_slippage_bps: CanonicalMoney
    mean_slippage_bps: CanonicalMoney
    max_slippage_bps: CanonicalMoney
    final_equity: CanonicalMoney
    summary_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.orders_approved + self.orders_rejected_risk > self.orders_generated:
            raise ValueError(
                "sum of approved and rejected orders cannot exceed generated orders"
            )
        if self.orders_filled > self.orders_approved:
            raise ValueError("filled orders cannot exceed approved orders")

        expected = compute_shadow_validation_summary_hash(
            self.model_dump(mode="python")
        )
        if self.summary_hash != expected:
            raise ValueError(
                f"summary_hash mismatch: expected {expected}, got {self.summary_hash}"
            )
        return self


# =========================================================================
# Builders
# =========================================================================


def build_market_tick(
    *,
    tick_id: UUID,
    security_id: UUID,
    timestamp: datetime,
    last_price: Decimal,
    last_size: int,
    bid_price: Decimal | None = None,
    bid_size: int | None = None,
    ask_price: Decimal | None = None,
    ask_size: int | None = None,
) -> MarketTickV1:
    """Construct immutable MarketTickV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": PAPER_VALIDATION_SCHEMA_VERSION,
        "tick_id": tick_id,
        "security_id": security_id,
        "timestamp": timestamp,
        "last_price": canonical_money(last_price),
        "last_size": last_size,
        "bid_price": canonical_money(bid_price) if bid_price is not None else None,
        "bid_size": bid_size,
        "ask_price": canonical_money(ask_price) if ask_price is not None else None,
        "ask_size": ask_size,
    }
    t_hash = compute_market_tick_hash(unsigned)
    return MarketTickV1.model_validate({**unsigned, "tick_hash": t_hash})


def build_execution_drift_report(
    *,
    drift_id: UUID,
    intent_id: UUID,
    security_id: UUID,
    intended_price: Decimal,
    fill_price: Decimal,
    recorded_at: datetime,
) -> ExecutionDriftReportV1:
    """Construct immutable ExecutionDriftReportV1 with derived slippage and hash."""
    with decimal_context():
        # Slippage in basis points: ((fill - intended) / intended) * 10000
        slippage_bps = canonical_money(
            ((fill_price - intended_price) / intended_price) * Decimal("10000")
        )

    unsigned: dict[str, Any] = {
        "schema_version": PAPER_VALIDATION_SCHEMA_VERSION,
        "drift_id": drift_id,
        "intent_id": intent_id,
        "security_id": security_id,
        "intended_price": canonical_money(intended_price),
        "fill_price": canonical_money(fill_price),
        "slippage_bps": slippage_bps,
        "recorded_at": recorded_at,
    }
    d_hash = compute_execution_drift_hash(unsigned)
    return ExecutionDriftReportV1.model_validate({**unsigned, "drift_hash": d_hash})


def build_shadow_validation_summary(
    *,
    validation_id: UUID,
    session_key: SessionKeyV1,
    total_ticks_processed: int,
    orders_generated: int,
    orders_approved: int,
    orders_rejected_risk: int,
    orders_filled: int,
    total_slippage_bps: Decimal,
    mean_slippage_bps: Decimal,
    max_slippage_bps: Decimal,
    final_equity: Decimal,
) -> ShadowValidationSummaryV1:
    """Construct immutable ShadowValidationSummaryV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": PAPER_VALIDATION_SCHEMA_VERSION,
        "validation_id": validation_id,
        "session_key": session_key,
        "total_ticks_processed": total_ticks_processed,
        "orders_generated": orders_generated,
        "orders_approved": orders_approved,
        "orders_rejected_risk": orders_rejected_risk,
        "orders_filled": orders_filled,
        "total_slippage_bps": canonical_money(total_slippage_bps),
        "mean_slippage_bps": canonical_money(mean_slippage_bps),
        "max_slippage_bps": canonical_money(max_slippage_bps),
        "final_equity": canonical_money(final_equity),
    }
    s_hash = compute_shadow_validation_summary_hash(unsigned)
    return ShadowValidationSummaryV1.model_validate(
        {**unsigned, "summary_hash": s_hash}
    )
