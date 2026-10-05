"""Shadow broker domain models, order lifecycles, and eligibility schemas (M12-1).

Provides immutable domain models for simulated order submission, execution fills,
and market execution eligibility gating consuming M2 canonical accounting.
"""

from collections.abc import Mapping
from datetime import datetime
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
from drift.domain.evaluator_portfolio import (
    CanonicalMoney,
    PortfolioFillV1,
    canonical_money,
)
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

SHADOW_BROKER_SCHEMA_VERSION: Literal["1"] = "1"

__all__ = [
    "SHADOW_BROKER_SCHEMA_VERSION",
    "EligibilityStatus",
    "MarketExecutionEligibilityV1",
    "SimulatedFillV1",
    "SimulatedOrderStatus",
    "SimulatedOrderV1",
    "build_market_execution_eligibility",
    "build_simulated_fill",
    "build_simulated_order",
    "compute_market_execution_eligibility_hash",
    "compute_simulated_fill_hash",
    "compute_simulated_order_hash",
]


class EligibilityStatus(StrEnum):
    """Three-valued market execution eligibility status."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class SimulatedOrderStatus(StrEnum):
    """Simulated order lifecycle status."""

    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# =========================================================================
# Content Hash Functions
# =========================================================================


def compute_market_execution_eligibility_hash(
    unsigned: Mapping[str, Any],
) -> SHA256Hash:
    """Compute canonical content hash for MarketExecutionEligibilityV1."""
    d = dict(unsigned)
    d.pop("eligibility_hash", None)
    return content_hash(d)


def compute_simulated_order_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for SimulatedOrderV1."""
    d = dict(unsigned)
    d.pop("order_hash", None)
    if d.get("limit_price") is not None and isinstance(d["limit_price"], Decimal):
        d["limit_price"] = canonical_money(d["limit_price"])
    return content_hash(d)


def compute_simulated_fill_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for SimulatedFillV1."""
    d = dict(unsigned)
    d.pop("fill_hash", None)
    if d.get("fill_price") is not None and isinstance(d["fill_price"], Decimal):
        d["fill_price"] = canonical_money(d["fill_price"])
    if d.get("transaction_costs") is not None and isinstance(
        d["transaction_costs"], Decimal
    ):
        d["transaction_costs"] = canonical_money(d["transaction_costs"])
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class MarketExecutionEligibilityV1(FrozenModel):
    """Upstream market execution eligibility for one security in one session."""

    schema_version: Literal["1"] = SHADOW_BROKER_SCHEMA_VERSION
    security_id: UUID7
    session_key: SessionKeyV1
    status: EligibilityStatus
    reason: NonBlankStr | None = None
    evidence_hash: SHA256Hash | None = None
    eligibility_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_eligibility_integrity(self) -> Self:
        if self.status == EligibilityStatus.INDETERMINATE:
            if self.evidence_hash is not None:
                raise ValueError("indeterminate eligibility cannot name evidence hash")
            if self.reason is None:
                raise ValueError("indeterminate eligibility requires a reason")
        else:
            if self.evidence_hash is None:
                raise ValueError(
                    f"{self.status} eligibility requires a bound evidence hash"
                )

        expected = compute_market_execution_eligibility_hash(
            self.model_dump(mode="python")
        )
        if self.eligibility_hash != expected:
            raise ValueError("market execution eligibility hash mismatch")
        return self


class SimulatedOrderV1(FrozenModel):
    """One simulated whole-share order submitted to the shadow broker."""

    schema_version: Literal["1"] = SHADOW_BROKER_SCHEMA_VERSION
    order_id: UUID7
    session_key: SessionKeyV1
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    order_type: Literal["market", "limit"] = "market"
    limit_price: CanonicalMoney | None = None
    created_at: UTCDateTime
    order_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_order_integrity(self) -> Self:
        if self.order_type == "limit":
            if self.limit_price is None or self.limit_price <= Decimal("0"):
                raise ValueError("limit order requires positive limit price")
        elif self.limit_price is not None:
            raise ValueError("market order cannot carry limit price")

        expected = compute_simulated_order_hash(self.model_dump(mode="python"))
        if self.order_hash != expected:
            raise ValueError("simulated order hash mismatch")
        return self


class SimulatedFillV1(FrozenModel):
    """One simulated execution fill produced by shadow broker at source basis."""

    schema_version: Literal["1"] = SHADOW_BROKER_SCHEMA_VERSION
    fill_id: UUID7
    order_id: UUID7
    security_id: UUID7
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    fill_price: CanonicalMoney
    transaction_costs: CanonicalMoney = Decimal("0")
    filled_at: UTCDateTime
    fill_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_fill_integrity(self) -> Self:
        if self.fill_price <= Decimal("0"):
            raise ValueError("fill price must be strictly positive")
        if self.transaction_costs < Decimal("0"):
            raise ValueError("transaction costs must be non-negative")

        expected = compute_simulated_fill_hash(self.model_dump(mode="python"))
        if self.fill_hash != expected:
            raise ValueError("simulated fill hash mismatch")
        return self

    def to_portfolio_fill(self) -> PortfolioFillV1:
        """Project simulated fill into M2 canonical accounting PortfolioFillV1."""
        return PortfolioFillV1(
            security_id=self.security_id,
            side=self.side,
            quantity=self.quantity,
            fill_price=self.fill_price,
            transaction_costs=self.transaction_costs,
        )


# =========================================================================
# Builders
# =========================================================================


def build_market_execution_eligibility(
    *,
    security_id: UUID,
    session_key: SessionKeyV1,
    status: EligibilityStatus,
    reason: str | None = None,
    evidence_hash: str | None = None,
) -> MarketExecutionEligibilityV1:
    """Construct immutable MarketExecutionEligibilityV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": SHADOW_BROKER_SCHEMA_VERSION,
        "security_id": security_id,
        "session_key": session_key,
        "status": status,
        "reason": reason,
        "evidence_hash": evidence_hash,
    }
    e_hash = compute_market_execution_eligibility_hash(unsigned)
    return MarketExecutionEligibilityV1.model_validate(
        {
            **unsigned,
            "eligibility_hash": e_hash,
        }
    )


def build_simulated_order(
    *,
    order_id: UUID,
    session_key: SessionKeyV1,
    security_id: UUID,
    side: Literal["buy", "sell"],
    quantity: int,
    created_at: datetime,
    order_type: Literal["market", "limit"] = "market",
    limit_price: Decimal | None = None,
) -> SimulatedOrderV1:
    """Construct immutable SimulatedOrderV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": SHADOW_BROKER_SCHEMA_VERSION,
        "order_id": order_id,
        "session_key": session_key,
        "security_id": security_id,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "limit_price": (
            canonical_money(limit_price) if limit_price is not None else None
        ),
        "created_at": created_at,
    }
    o_hash = compute_simulated_order_hash(unsigned)
    return SimulatedOrderV1.model_validate(
        {
            **unsigned,
            "order_hash": o_hash,
        }
    )


def build_simulated_fill(
    *,
    fill_id: UUID,
    order_id: UUID,
    security_id: UUID,
    side: Literal["buy", "sell"],
    quantity: int,
    fill_price: Decimal,
    filled_at: datetime,
    transaction_costs: Decimal = Decimal("0"),
) -> SimulatedFillV1:
    """Construct immutable SimulatedFillV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": SHADOW_BROKER_SCHEMA_VERSION,
        "fill_id": fill_id,
        "order_id": order_id,
        "security_id": security_id,
        "side": side,
        "quantity": quantity,
        "fill_price": canonical_money(fill_price),
        "transaction_costs": canonical_money(transaction_costs),
        "filled_at": filled_at,
    }
    f_hash = compute_simulated_fill_hash(unsigned)
    return SimulatedFillV1.model_validate(
        {
            **unsigned,
            "fill_hash": f_hash,
        }
    )
