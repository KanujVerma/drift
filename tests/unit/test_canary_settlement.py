"""Unit tests for Canary Settlement and Fill Reconciliation Grader (M17-3)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

from drift.canary.settlement import CanarySettlementGrader
from drift.domain.canary import CanaryPolicyV1
from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_grade_settlement_perfect_buy() -> None:
    """Buy order with exact cash delta and zero slippage settles successfully."""
    policy = CanaryPolicyV1(max_slippage_bps=50)
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-settle-01",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-001",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.00"),
        fee_amount=Decimal("0.00"),
        reported_at=datetime.now(UTC),
    )

    settlement = grader.grade_settlement(
        intent=intent,
        report=report,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("96.00"),
    )

    assert settlement.is_settled is True
    assert settlement.reconciliation_difference == Decimal("0")
    assert settlement.slippage_bps == Decimal("0")
    assert settlement.actual_fill_notional == Decimal("4.00")
    assert settlement.cash_balance_delta == Decimal("-4.00")


def test_grade_settlement_perfect_sell_with_fee() -> None:
    """Sell order with fee and matching net proceeds settles successfully."""
    policy = CanaryPolicyV1(max_slippage_bps=50)
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-settle-02",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("5.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-002",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("5.00"),
        fee_amount=Decimal("0.50"),
        reported_at=datetime.now(UTC),
    )

    # Net proceeds: $5.00 - $0.50 = $4.50
    settlement = grader.grade_settlement(
        intent=intent,
        report=report,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("104.50"),
    )

    assert settlement.is_settled is True
    assert settlement.reconciliation_difference == Decimal("0")
    assert settlement.actual_fill_notional == Decimal("5.00")
    assert settlement.cash_balance_delta == Decimal("4.50")


def test_grade_settlement_cash_discrepancy() -> None:
    """Unexpected cash balance delta fails settlement reconciliation."""
    policy = CanaryPolicyV1()
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-settle-03",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-003",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.00"),
        fee_amount=Decimal("0.00"),
        reported_at=datetime.now(UTC),
    )

    # Final cash $95.00 instead of expected $96.00 ($1.00 missing)
    settlement = grader.grade_settlement(
        intent=intent,
        report=report,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("95.00"),
    )

    assert settlement.is_settled is False
    assert settlement.reconciliation_difference == Decimal("1.00")


def test_grade_settlement_slippage_tolerance() -> None:
    """Slippage exceeding policy tolerance fails settlement validation."""
    policy = CanaryPolicyV1(max_slippage_bps=50)  # max 0.50%
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-settle-04",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    # Expected $4.00, filled at $4.50 (12.5% slippage = 1250 bps)
    report_bad = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-004",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.50"),
        reported_at=datetime.now(UTC),
    )

    res_bad = grader.grade_settlement(
        intent=intent,
        report=report_bad,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("95.50"),
        expected_fill_price=Decimal("4.00"),
    )
    assert res_bad.is_settled is False
    assert res_bad.slippage_bps == Decimal("1250")

    # Expected $4.00, filled at $4.01 (0.25% slippage = 25 bps <= 50 bps)
    report_good = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-005",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.01"),
        reported_at=datetime.now(UTC),
    )

    res_good = grader.grade_settlement(
        intent=intent,
        report=report_good,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("95.99"),
        expected_fill_price=Decimal("4.00"),
    )
    assert res_good.is_settled is True
    assert res_good.slippage_bps == Decimal("25")
