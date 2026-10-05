"""Unit tests for Deterministic Hard Risk domain models and schemas (M13-1)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.risk import (
    KillSwitchStateV1,
    KillSwitchStatus,
    RiskPolicyV1,
    RiskVerdictStatus,
    RiskVerdictV1,
    build_kill_switch_state,
    build_risk_policy,
    build_risk_verdict,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)


def test_risk_policy_validation_and_hashing() -> None:
    """Verifies RiskPolicyV1 invariants, bounds, and tamper detection."""
    policy = build_risk_policy(
        policy_id="standard-limits",
        max_order_notional=Decimal("50000.00"),
        max_order_quantity=500,
        max_position_notional=Decimal("100000.00"),
        max_position_weight_basis_points=2000,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=300,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=60,
    )
    assert policy.policy_id == "standard-limits"
    assert policy.max_order_notional == Decimal("50000")
    assert policy.max_order_quantity == 500
    assert policy.max_position_notional == Decimal("100000")
    assert policy.max_position_weight_basis_points == 2000

    # Non-positive notional refused
    with pytest.raises(ValidationError, match="max_order_notional must be"):
        build_risk_policy(
            policy_id="invalid",
            max_order_notional=Decimal("0.00"),
            max_order_quantity=100,
            max_position_notional=Decimal("50000"),
            max_position_weight_basis_points=1000,
            max_gross_exposure_basis_points=10000,
            max_session_drawdown_basis_points=300,
            max_trailing_drawdown_basis_points=1000,
            max_orders_per_minute=60,
        )

    # Basis points > 10000 refused
    with pytest.raises(ValidationError):
        build_risk_policy(
            policy_id="invalid",
            max_order_notional=Decimal("10000"),
            max_order_quantity=100,
            max_position_notional=Decimal("50000"),
            max_position_weight_basis_points=15000,  # invalid > 10000
            max_gross_exposure_basis_points=10000,
            max_session_drawdown_basis_points=300,
            max_trailing_drawdown_basis_points=1000,
            max_orders_per_minute=60,
        )

    # Hash tamper detection
    tampered = policy.model_dump(mode="python")
    tampered["max_order_quantity"] = 999
    with pytest.raises(ValidationError, match="risk policy hash mismatch"):
        RiskPolicyV1.model_validate(tampered)


def test_kill_switch_state_validation_and_hashing() -> None:
    """Verifies KillSwitchStateV1 requirements, states, and tamper detection."""
    # Active (untripped)
    active = build_kill_switch_state(status=KillSwitchStatus.ACTIVE)
    assert active.status == KillSwitchStatus.ACTIVE
    assert active.tripped_at is None
    assert active.trip_reason is None

    # Tripped
    tripped = build_kill_switch_state(
        status=KillSwitchStatus.TRIPPED,
        tripped_at=NOW,
        trip_reason="session_loss_limit_exceeded: -3.5%",
    )
    assert tripped.status == KillSwitchStatus.TRIPPED
    assert tripped.tripped_at == NOW
    assert tripped.trip_reason == "session_loss_limit_exceeded: -3.5%"

    # Tripped missing reason or timestamp raises
    with pytest.raises(ValidationError, match="tripped kill switch requires"):
        build_kill_switch_state(
            status=KillSwitchStatus.TRIPPED,
            tripped_at=None,
            trip_reason=None,
        )

    # Cleared with reason
    cleared = build_kill_switch_state(
        status=KillSwitchStatus.ACTIVE,
        cleared_at=NOW,
        clear_reason="operator_reset_confirmed",
    )
    assert cleared.status == KillSwitchStatus.ACTIVE
    assert cleared.clear_reason == "operator_reset_confirmed"

    # Hash tamper detection
    tampered = tripped.model_dump(mode="python")
    tampered["trip_reason"] = "tampered_reason"
    with pytest.raises(ValidationError, match="kill switch state hash mismatch"):
        KillSwitchStateV1.model_validate(tampered)


def test_risk_verdict_validation_and_hashing() -> None:
    """Verifies RiskVerdictV1 verdicts, reasons, and tamper detection."""
    order_id = uuid7()

    # Allowed
    allowed = build_risk_verdict(
        order_id=order_id,
        status=RiskVerdictStatus.ALLOWED,
        evaluated_at=NOW,
    )
    assert allowed.status == RiskVerdictStatus.ALLOWED
    assert allowed.reason is None

    # Allowed cannot carry reason
    with pytest.raises(ValidationError, match="allowed verdict cannot carry"):
        build_risk_verdict(
            order_id=order_id,
            status=RiskVerdictStatus.ALLOWED,
            evaluated_at=NOW,
            reason="spurious_reason",
        )

    # Rejected requires reason
    rejected = build_risk_verdict(
        order_id=order_id,
        status=RiskVerdictStatus.REJECTED,
        evaluated_at=NOW,
        reason="max_position_notional_exceeded: requested 60000 > limit 50000",
    )
    assert rejected.status == RiskVerdictStatus.REJECTED
    assert "max_position_notional_exceeded" in str(rejected.reason)

    with pytest.raises(ValidationError, match="requires a non-blank diagnostic"):
        build_risk_verdict(
            order_id=order_id,
            status=RiskVerdictStatus.REJECTED,
            evaluated_at=NOW,
            reason=None,
        )

    # Kill switch active requires reason
    halted = build_risk_verdict(
        order_id=order_id,
        status=RiskVerdictStatus.KILL_SWITCH_ACTIVE,
        evaluated_at=NOW,
        reason="kill_switch_latch_tripped: trading halted",
    )
    assert halted.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE

    # Tampering
    tampered = rejected.model_dump(mode="python")
    tampered["reason"] = "tampered_diagnostic_reason"
    with pytest.raises(ValidationError, match="risk verdict hash mismatch"):
        RiskVerdictV1.model_validate(tampered)
