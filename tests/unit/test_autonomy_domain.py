"""Unit tests for Autonomy domain models, tiers, and governance records (M18-1)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    TIER_LIMITS,
    AutonomyTier,
    GovernanceTransitionType,
    GovernanceTransitionV1,
    build_governance_transition,
)


def test_autonomy_tiers_and_limits() -> None:
    """All autonomy tiers exist and have monotonically increasing limits."""
    assert len(AutonomyTier) == 4
    for tier in AutonomyTier:
        limits = TIER_LIMITS[tier]
        assert limits.tier == tier
        assert limits.max_order_notional > Decimal("0")
        assert limits.max_cumulative_notional >= limits.max_order_notional
        assert limits.max_order_quantity >= 1

    # Verify monotonic progression
    t0 = TIER_LIMITS[AutonomyTier.TIER_0_CANARY]
    t1 = TIER_LIMITS[AutonomyTier.TIER_1_MICRO]
    t2 = TIER_LIMITS[AutonomyTier.TIER_2_SMALL]
    t3 = TIER_LIMITS[AutonomyTier.TIER_3_BOUNDED]

    assert (
        t0.max_order_notional
        < t1.max_order_notional
        < t2.max_order_notional
        < t3.max_order_notional
    )
    assert (
        t0.max_cumulative_notional
        < t1.max_cumulative_notional
        < t2.max_cumulative_notional
        < t3.max_cumulative_notional
    )
    assert (
        t0.max_order_quantity
        < t1.max_order_quantity
        < t2.max_order_quantity
        < t3.max_order_quantity
    )


def test_governance_transition_builder_and_hash_chaining() -> None:
    """Transitions build with deterministic hashes and support chaining."""
    now1 = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    now2 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    # Initial transition: Tier 0 Canary hold
    e1_id = uuid7()
    t1 = build_governance_transition(
        event_id=e1_id,
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_0_CANARY,
        transition_type=GovernanceTransitionType.HOLD,
        trigger_reason="initial_canary_baseline",
        scorecard_summary={"sharpe": "1.5"},
        previous_chain_hash=None,
        evaluated_at=now1,
    )

    assert t1.schema_version == AUTONOMY_SCHEMA_VERSION
    assert t1.previous_chain_hash is None
    assert len(t1.chain_hash) == 64

    # Second transition: Promotion to Tier 1 Micro chaining to t1
    e2_id = uuid7()
    t2 = build_governance_transition(
        event_id=e2_id,
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_1_MICRO,
        transition_type=GovernanceTransitionType.PROMOTION,
        trigger_reason="m5_scorecard_and_m17_settlement_satisfied",
        scorecard_summary={"sharpe": "1.8", "pbo": "0.05"},
        previous_chain_hash=t1.chain_hash,
        evaluated_at=now2,
    )

    assert t2.previous_chain_hash == t1.chain_hash
    assert len(t2.chain_hash) == 64
    assert t2.chain_hash != t1.chain_hash


def test_governance_transition_tampered_hash_fails() -> None:
    """Tampering with chain_hash fails model validation."""
    now = datetime.now(UTC)
    e_id = uuid7()
    t = build_governance_transition(
        event_id=e_id,
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_0_CANARY,
        transition_type=GovernanceTransitionType.HOLD,
        trigger_reason="baseline",
        evaluated_at=now,
    )

    with pytest.raises(ValidationError):
        GovernanceTransitionV1(
            event_id=e_id,
            previous_tier=t.previous_tier,
            target_tier=t.target_tier,
            transition_type=t.transition_type,
            trigger_reason=t.trigger_reason,
            previous_chain_hash=t.previous_chain_hash,
            chain_hash="0" * 64,
            evaluated_at=now,
        )


def test_governance_transition_immutability() -> None:
    """Governance transition record is frozen and immutable."""
    now = datetime.now(UTC)
    t = build_governance_transition(
        event_id=uuid7(),
        previous_tier=AutonomyTier.TIER_0_CANARY,
        target_tier=AutonomyTier.TIER_0_CANARY,
        transition_type=GovernanceTransitionType.HOLD,
        trigger_reason="baseline",
        evaluated_at=now,
    )

    with pytest.raises(ValidationError):
        t.trigger_reason = "tampered"
