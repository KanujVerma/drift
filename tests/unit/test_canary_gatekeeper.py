"""Unit tests for Canary Allocation Gatekeeper (M17-2)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.domain.canary import CanaryPolicyV1
from drift.domain.execution import (
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_gatekeeper_unauthorized_refused() -> None:
    """Unauthorized canary policy fails closed and refuses orders."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(canary_authorized=False)
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.50"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    result = gatekeeper.evaluate_intent(intent)
    assert result.decision == "refused"
    assert "canary_unauthorized" in result.refusal_reasons
    assert gatekeeper.cumulative_allocated_notional == Decimal("0")


def test_gatekeeper_valid_order_admitted() -> None:
    """Authorized order within notional and quantity caps is admitted."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("5.00"),
        whitelisted_symbols=frozenset({"AAPL"}),
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-002",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.50"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    result = gatekeeper.evaluate_intent(intent)
    assert result.decision == "admitted"
    assert result.refusal_reasons == ()
    assert result.order_notional == Decimal("4.50")
    assert gatekeeper.cumulative_allocated_notional == Decimal("4.50")


def test_gatekeeper_quantity_breach_refused() -> None:
    """Order with quantity > max_order_quantity is refused."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_quantity=1,
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-003",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("2.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    result = gatekeeper.evaluate_intent(intent)
    assert result.decision == "refused"
    assert any("exceeds max_order_quantity" in r for r in result.refusal_reasons)


def test_gatekeeper_whitelist_refused() -> None:
    """Order for symbol not in whitelist is refused."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        whitelisted_symbols=frozenset({"AAPL"}),
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "TSLA"},
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-004",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("3.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    result = gatekeeper.evaluate_intent(intent)
    assert result.decision == "refused"
    assert any("not in whitelisted_symbols" in r for r in result.refusal_reasons)


def test_gatekeeper_notional_and_cumulative_breach() -> None:
    """Notional per order and cumulative allocations are enforced."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("5.00"),
        max_cumulative_notional=Decimal("10.00"),
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    # 1. Single order exceeds order cap ($6.00 > $5.00)
    intent_big = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-big",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("6.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_big = gatekeeper.evaluate_intent(intent_big)
    assert res_big.decision == "refused"
    assert any("exceeds max_order_notional" in r for r in res_big.refusal_reasons)

    # 2. Admit two $4.00 orders ($8.00 total)
    intent_ok = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-ok1",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res1 = gatekeeper.evaluate_intent(intent_ok)
    assert res1.decision == "admitted"

    intent_ok2 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-ok2",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res2 = gatekeeper.evaluate_intent(intent_ok2)
    assert res2.decision == "admitted"
    assert gatekeeper.cumulative_allocated_notional == Decimal("8.00")

    # 3. Third $4.00 order would push total to $12.00 > $10.00 cap -> refused
    intent_ok3 = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-ok3",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res3 = gatekeeper.evaluate_intent(intent_ok3)
    assert res3.decision == "refused"
    assert any("exceeds max_cumulative_notional" in r for r in res3.refusal_reasons)

    # 4. Reset allocation allows new orders
    gatekeeper.reset_allocation()
    assert gatekeeper.cumulative_allocated_notional == Decimal("0")
    res4 = gatekeeper.evaluate_intent(intent_ok3)
    assert res4.decision == "admitted"
