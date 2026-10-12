"""Deterministic hard risk domain models, policies, and verdict schemas (M13-1).

Provides immutable domain models for non-negotiable risk policies, persistent
kill switch states, and pre-execution order evaluation verdicts.
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
    canonical_money,
)
from drift.serialization.canonical import content_hash

RISK_SCHEMA_VERSION: Literal["1"] = "1"

__all__ = [
    "RISK_SCHEMA_VERSION",
    "KillSwitchStateV1",
    "KillSwitchStatus",
    "RiskPolicyV1",
    "RiskVerdictStatus",
    "RiskVerdictV1",
    "build_kill_switch_state",
    "build_risk_policy",
    "build_risk_verdict",
    "compute_kill_switch_state_hash",
    "compute_risk_policy_hash",
    "compute_risk_verdict_hash",
]


class KillSwitchStatus(StrEnum):
    """Status of the persistent emergency kill switch."""

    ACTIVE = "active"
    TRIPPED = "tripped"


class RiskVerdictStatus(StrEnum):
    """Three-valued risk evaluation verdict."""

    ALLOWED = "allowed"
    REJECTED = "rejected"
    KILL_SWITCH_ACTIVE = "kill_switch_active"


# =========================================================================
# Content Hash Functions
# =========================================================================


def compute_risk_policy_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for RiskPolicyV1."""
    d = dict(unsigned)
    d.pop("policy_hash", None)
    for field in ("max_order_notional", "max_position_notional"):
        if d.get(field) is not None and isinstance(d[field], Decimal):
            d[field] = canonical_money(d[field])
    return content_hash(d)


def compute_kill_switch_state_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for KillSwitchStateV1."""
    d = dict(unsigned)
    d.pop("state_hash", None)
    return content_hash(d)


def compute_risk_verdict_hash(unsigned: Mapping[str, Any]) -> SHA256Hash:
    """Compute canonical content hash for RiskVerdictV1."""
    d = dict(unsigned)
    d.pop("verdict_hash", None)
    return content_hash(d)


# =========================================================================
# Domain Models
# =========================================================================


class RiskPolicyV1(FrozenModel):
    """Immutable parameterization of deterministic hard risk limits."""

    schema_version: Literal["1"] = RISK_SCHEMA_VERSION
    policy_id: NonBlankStr
    max_order_notional: CanonicalMoney
    max_order_quantity: int = Field(gt=0)
    max_position_notional: CanonicalMoney
    max_position_weight_basis_points: int = Field(ge=0, le=10000)
    max_gross_exposure_basis_points: int = Field(ge=0, le=10000)
    max_session_drawdown_basis_points: int = Field(ge=0, le=10000)
    max_trailing_drawdown_basis_points: int = Field(ge=0, le=10000)
    max_orders_per_minute: int = Field(gt=0)
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_policy_integrity(self) -> Self:
        if self.max_order_notional <= Decimal("0"):
            raise ValueError("max_order_notional must be strictly positive")
        if self.max_position_notional <= Decimal("0"):
            raise ValueError("max_position_notional must be strictly positive")

        expected = compute_risk_policy_hash(self.model_dump(mode="python"))
        if self.policy_hash != expected:
            raise ValueError("risk policy hash mismatch")
        return self


class KillSwitchStateV1(FrozenModel):
    """Immutable representation of persistent kill switch state."""

    schema_version: Literal["1"] = RISK_SCHEMA_VERSION
    status: KillSwitchStatus
    tripped_at: UTCDateTime | None = None
    trip_reason: NonBlankStr | None = None
    cleared_at: UTCDateTime | None = None
    clear_reason: NonBlankStr | None = None
    state_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_state_integrity(self) -> Self:
        if self.status == KillSwitchStatus.TRIPPED:
            if self.tripped_at is None:
                raise ValueError("tripped kill switch requires tripped_at")
            if self.trip_reason is None:
                raise ValueError("tripped kill switch requires trip_reason")
        else:
            if self.cleared_at is not None and self.clear_reason is None:
                raise ValueError("cleared kill switch requires clear_reason")

        expected = compute_kill_switch_state_hash(self.model_dump(mode="python"))
        if self.state_hash != expected:
            raise ValueError("kill switch state hash mismatch")
        return self


class RiskVerdictV1(FrozenModel):
    """Pre-execution risk evaluation verdict on a simulated order."""

    schema_version: Literal["1"] = RISK_SCHEMA_VERSION
    order_id: UUID7
    status: RiskVerdictStatus
    reason: NonBlankStr | None = None
    evaluated_at: UTCDateTime
    verdict_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_verdict_integrity(self) -> Self:
        if self.status in (
            RiskVerdictStatus.REJECTED,
            RiskVerdictStatus.KILL_SWITCH_ACTIVE,
        ):
            if self.reason is None:
                raise ValueError(
                    f"{self.status} verdict requires a non-blank diagnostic reason"
                )
        elif self.reason is not None:
            raise ValueError("allowed verdict cannot carry a rejection reason")

        expected = compute_risk_verdict_hash(self.model_dump(mode="python"))
        if self.verdict_hash != expected:
            raise ValueError("risk verdict hash mismatch")
        return self


# =========================================================================
# Builders
# =========================================================================


def build_risk_policy(
    *,
    policy_id: str,
    max_order_notional: Decimal,
    max_order_quantity: int,
    max_position_notional: Decimal,
    max_position_weight_basis_points: int,
    max_gross_exposure_basis_points: int,
    max_session_drawdown_basis_points: int,
    max_trailing_drawdown_basis_points: int,
    max_orders_per_minute: int,
) -> RiskPolicyV1:
    """Construct immutable RiskPolicyV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": RISK_SCHEMA_VERSION,
        "policy_id": policy_id,
        "max_order_notional": canonical_money(max_order_notional),
        "max_order_quantity": max_order_quantity,
        "max_position_notional": canonical_money(max_position_notional),
        "max_position_weight_basis_points": max_position_weight_basis_points,
        "max_gross_exposure_basis_points": max_gross_exposure_basis_points,
        "max_session_drawdown_basis_points": max_session_drawdown_basis_points,
        "max_trailing_drawdown_basis_points": max_trailing_drawdown_basis_points,
        "max_orders_per_minute": max_orders_per_minute,
    }
    p_hash = compute_risk_policy_hash(unsigned)
    return RiskPolicyV1.model_validate(
        {
            **unsigned,
            "policy_hash": p_hash,
        }
    )


def build_kill_switch_state(
    *,
    status: KillSwitchStatus,
    tripped_at: datetime | None = None,
    trip_reason: str | None = None,
    cleared_at: datetime | None = None,
    clear_reason: str | None = None,
) -> KillSwitchStateV1:
    """Construct immutable KillSwitchStateV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": RISK_SCHEMA_VERSION,
        "status": status,
        "tripped_at": tripped_at,
        "trip_reason": trip_reason,
        "cleared_at": cleared_at,
        "clear_reason": clear_reason,
    }
    s_hash = compute_kill_switch_state_hash(unsigned)
    return KillSwitchStateV1.model_validate(
        {
            **unsigned,
            "state_hash": s_hash,
        }
    )


def build_risk_verdict(
    *,
    order_id: UUID,
    status: RiskVerdictStatus,
    evaluated_at: datetime,
    reason: str | None = None,
) -> RiskVerdictV1:
    """Construct immutable RiskVerdictV1 with computed hash."""
    unsigned: dict[str, Any] = {
        "schema_version": RISK_SCHEMA_VERSION,
        "order_id": order_id,
        "status": status,
        "reason": reason,
        "evaluated_at": evaluated_at,
    }
    v_hash = compute_risk_verdict_hash(unsigned)
    return RiskVerdictV1.model_validate(
        {
            **unsigned,
            "verdict_hash": v_hash,
        }
    )
