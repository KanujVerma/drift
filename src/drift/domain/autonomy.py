"""Autonomy domain models, tier definitions, and governance records (M18-1).

Provides immutable domain models for the Bounded Autonomy layer defining
progressive capital allocation tiers, limits, and cryptographically chained
governance transition events per ADR 0011, ADR 0013, and ADR 0014.
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
from drift.domain.evaluator_portfolio import CanonicalMoney
from drift.serialization.canonical import content_hash

AUTONOMY_SCHEMA_VERSION: Literal["1"] = "1"
GOVERNANCE_TRANSITION_PROFILE = "drift-governance-transition-v1"

__all__ = [
    "AUTONOMY_SCHEMA_VERSION",
    "GOVERNANCE_TRANSITION_PROFILE",
    "TIER_LIMITS",
    "AutonomyTier",
    "GovernanceTransitionType",
    "GovernanceTransitionV1",
    "TierAllocationLimitsV1",
    "build_governance_transition",
    "compute_governance_transition_hash",
]


class AutonomyTier(StrEnum):
    """Operational capital allocation tiers."""

    TIER_0_CANARY = "tier_0_canary"
    TIER_1_MICRO = "tier_1_micro"
    TIER_2_SMALL = "tier_2_small"
    TIER_3_BOUNDED = "tier_3_bounded"


class GovernanceTransitionType(StrEnum):
    """Type of tier governance transition."""

    PROMOTION = "promotion"
    DEMOTION = "demotion"
    HOLD = "hold"
    EMERGENCY_HALT = "emergency_halt"


class TierAllocationLimitsV1(FrozenModel):
    """Allocation constraints associated with an AutonomyTier."""

    tier: AutonomyTier
    max_order_notional: CanonicalMoney
    max_cumulative_notional: CanonicalMoney
    max_order_quantity: int = Field(gt=0)


TIER_LIMITS: dict[AutonomyTier, TierAllocationLimitsV1] = {
    AutonomyTier.TIER_0_CANARY: TierAllocationLimitsV1(
        tier=AutonomyTier.TIER_0_CANARY,
        max_order_notional=Decimal("5.00"),
        max_cumulative_notional=Decimal("25.00"),
        max_order_quantity=1,
    ),
    AutonomyTier.TIER_1_MICRO: TierAllocationLimitsV1(
        tier=AutonomyTier.TIER_1_MICRO,
        max_order_notional=Decimal("25.00"),
        max_cumulative_notional=Decimal("100.00"),
        max_order_quantity=5,
    ),
    AutonomyTier.TIER_2_SMALL: TierAllocationLimitsV1(
        tier=AutonomyTier.TIER_2_SMALL,
        max_order_notional=Decimal("100.00"),
        max_cumulative_notional=Decimal("500.00"),
        max_order_quantity=20,
    ),
    AutonomyTier.TIER_3_BOUNDED: TierAllocationLimitsV1(
        tier=AutonomyTier.TIER_3_BOUNDED,
        max_order_notional=Decimal("500.00"),
        max_cumulative_notional=Decimal("2500.00"),
        max_order_quantity=50,
    ),
}


def compute_governance_transition_hash(
    *,
    schema_version: str,
    event_id: UUID,
    previous_tier: str,
    target_tier: str,
    transition_type: str,
    trigger_reason: str,
    scorecard_summary: Mapping[str, Any],
    previous_chain_hash: str | None,
    evaluated_at: datetime,
) -> SHA256Hash:
    """Compute deterministic SHA-256 hash for a governance transition record."""
    payload: dict[str, Any] = {
        "profile": GOVERNANCE_TRANSITION_PROFILE,
        "schema_version": schema_version,
        "event_id": str(event_id),
        "previous_tier": previous_tier,
        "target_tier": target_tier,
        "transition_type": transition_type,
        "trigger_reason": trigger_reason,
        "scorecard_summary": dict(scorecard_summary),
        "previous_chain_hash": previous_chain_hash,
        "evaluated_at": evaluated_at.isoformat(),
    }
    return content_hash(payload)


class GovernanceTransitionV1(FrozenModel):
    """Immutable, cryptographically chained governance event record."""

    schema_version: Literal["1"] = AUTONOMY_SCHEMA_VERSION
    event_id: UUID7
    previous_tier: AutonomyTier
    target_tier: AutonomyTier
    transition_type: GovernanceTransitionType
    trigger_reason: NonBlankStr
    scorecard_summary: Mapping[str, Any] = Field(default_factory=dict)
    previous_chain_hash: SHA256Hash | None = None
    chain_hash: SHA256Hash
    evaluated_at: UTCDateTime

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        expected_hash = compute_governance_transition_hash(
            schema_version=self.schema_version,
            event_id=self.event_id,
            previous_tier=self.previous_tier.value,
            target_tier=self.target_tier.value,
            transition_type=self.transition_type.value,
            trigger_reason=self.trigger_reason,
            scorecard_summary=self.scorecard_summary,
            previous_chain_hash=self.previous_chain_hash,
            evaluated_at=self.evaluated_at,
        )
        if self.chain_hash != expected_hash:
            raise ValueError(
                f"chain_hash mismatch: expected {expected_hash}, got {self.chain_hash}"
            )
        return self


def build_governance_transition(
    *,
    event_id: UUID,
    previous_tier: AutonomyTier | str,
    target_tier: AutonomyTier | str,
    transition_type: GovernanceTransitionType | str,
    trigger_reason: str,
    scorecard_summary: Mapping[str, Any] | None = None,
    previous_chain_hash: str | None = None,
    evaluated_at: datetime,
) -> GovernanceTransitionV1:
    """Build an immutable GovernanceTransitionV1 with automatic hash chaining."""
    prev_tier = (
        AutonomyTier(previous_tier) if isinstance(previous_tier, str) else previous_tier
    )
    targ_tier = (
        AutonomyTier(target_tier) if isinstance(target_tier, str) else target_tier
    )
    t_type = (
        GovernanceTransitionType(transition_type)
        if isinstance(transition_type, str)
        else transition_type
    )
    summary = dict(scorecard_summary) if scorecard_summary is not None else {}

    c_hash = compute_governance_transition_hash(
        schema_version=AUTONOMY_SCHEMA_VERSION,
        event_id=event_id,
        previous_tier=prev_tier.value,
        target_tier=targ_tier.value,
        transition_type=t_type.value,
        trigger_reason=trigger_reason,
        scorecard_summary=summary,
        previous_chain_hash=previous_chain_hash,
        evaluated_at=evaluated_at,
    )

    return GovernanceTransitionV1(
        schema_version=AUTONOMY_SCHEMA_VERSION,
        event_id=event_id,
        previous_tier=prev_tier,
        target_tier=targ_tier,
        transition_type=t_type,
        trigger_reason=trigger_reason,
        scorecard_summary=summary,
        previous_chain_hash=previous_chain_hash,
        chain_hash=c_hash,
        evaluated_at=evaluated_at,
    )
