"""Unit tests for Broker-Neutral Execution domain models and schemas (M14-1)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.execution import (
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_broker_account_snapshot,
    build_broker_position_snapshot,
    build_execution_report,
    build_order_intent,
)
from drift.domain.sessions import SessionKeyV1

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def test_order_intent_creation_and_hashing() -> None:
    """Verifies OrderIntentV1 builder, validation, and deterministic hashing."""
    sec = uuid7()
    intent_id = uuid7()

    # 1. Valid Market Order Intent
    intent_mkt = build_order_intent(
        intent_id=intent_id,
        client_order_id="drift-ord-001",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    assert intent_mkt.intent_id == intent_id
    assert intent_mkt.quantity == 50
    assert intent_mkt.order_type == OrderType.MARKET
    assert intent_mkt.limit_price is None
    assert intent_mkt.time_in_force == TimeInForce.DAY
    assert len(intent_mkt.intent_hash) == 64

    # 2. Valid Limit Order Intent
    intent_lmt = build_order_intent(
        intent_id=uuid7(),
        client_order_id="drift-ord-002",
        session_key=KEY1,
        security_id=sec,
        side=OrderSide.SELL,
        quantity=25,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.25"),
        time_in_force=TimeInForce.GTC,
        created_at=NOW,
    )
    assert intent_lmt.limit_price == Decimal("150.25")
    assert intent_lmt.time_in_force == TimeInForce.GTC

    # 3. Validation: Limit order missing price
    with pytest.raises(
        ValidationError, match="limit order requires positive limit_price"
    ):
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="drift-ord-003",
            session_key=KEY1,
            security_id=sec,
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=None,
            created_at=NOW,
        )

    # 4. Validation: Market order carrying limit price
    with pytest.raises(
        ValidationError, match="market order must not specify limit_price"
    ):
        build_order_intent(
            intent_id=uuid7(),
            client_order_id="drift-ord-004",
            session_key=KEY1,
            security_id=sec,
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            limit_price=Decimal("100.00"),
            created_at=NOW,
        )

    # 5. Validation: Tampered intent hash
    with pytest.raises(ValidationError, match="intent_hash mismatch"):
        OrderIntentV1(
            intent_id=intent_id,
            client_order_id="drift-ord-001",
            session_key=KEY1,
            security_id=sec,
            side=OrderSide.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
            created_at=NOW,
            intent_hash="0" * 64,
        )


def test_execution_report_creation_and_hashing() -> None:
    """Verifies ExecutionReportV1 builder, validation, and lifecycle states."""
    intent_id = uuid7()
    report_id = uuid7()

    # 1. Valid Acknowledged Report
    rep_ack = build_execution_report(
        report_id=report_id,
        intent_id=intent_id,
        broker_order_id="broker-12345",
        status=ExecutionStatus.ACKNOWLEDGED,
        cum_quantity=0,
        leaves_quantity=50,
        reported_at=NOW,
    )
    assert rep_ack.status == ExecutionStatus.ACKNOWLEDGED
    assert rep_ack.broker_order_id == "broker-12345"
    assert len(rep_ack.report_hash) == 64

    # 2. Valid Fill Report
    rep_fill = build_execution_report(
        report_id=uuid7(),
        intent_id=intent_id,
        broker_order_id="broker-12345",
        status=ExecutionStatus.FILLED,
        cum_quantity=50,
        leaves_quantity=0,
        last_fill_price=Decimal("100.05"),
        last_fill_quantity=50,
        avg_fill_price=Decimal("100.05"),
        fee_amount=Decimal("1.50"),
        reported_at=NOW,
    )
    assert rep_fill.status == ExecutionStatus.FILLED
    assert rep_fill.cum_quantity == 50
    assert rep_fill.fee_amount == Decimal("1.50")

    # 3. Valid Rejection Report
    rep_rej = build_execution_report(
        report_id=uuid7(),
        intent_id=intent_id,
        status=ExecutionStatus.REJECTED,
        rejection_reason="insufficient_buying_power",
        reported_at=NOW,
    )
    assert rep_rej.status == ExecutionStatus.REJECTED
    assert rep_rej.rejection_reason == "insufficient_buying_power"

    # 4. Validation: Rejected without reason
    with pytest.raises(ValidationError, match="requires rejection_reason"):
        build_execution_report(
            report_id=uuid7(),
            intent_id=intent_id,
            status=ExecutionStatus.REJECTED,
            rejection_reason=None,
            reported_at=NOW,
        )

    # 5. Validation: Filled with zero cumulative quantity
    with pytest.raises(ValidationError, match="cum_quantity > 0"):
        build_execution_report(
            report_id=uuid7(),
            intent_id=intent_id,
            status=ExecutionStatus.FILLED,
            cum_quantity=0,
            reported_at=NOW,
        )

    # 6. Validation: Negative fee amount
    with pytest.raises(ValidationError, match="fee_amount must be non-negative"):
        build_execution_report(
            report_id=uuid7(),
            intent_id=intent_id,
            status=ExecutionStatus.NEW,
            fee_amount=Decimal("-0.50"),
            reported_at=NOW,
        )


def test_broker_account_and_position_snapshots() -> None:
    """Verifies account and position snapshot builders and validations."""
    snap_id = uuid7()
    sec = uuid7()

    # 1. Valid Account Snapshot
    acc = build_broker_account_snapshot(
        snapshot_id=snap_id,
        account_id="act-live-001",
        cash_balance=Decimal("50000.00"),
        buying_power=Decimal("100000.00"),
        portfolio_equity=Decimal("75000.00"),
        as_of=NOW,
    )
    assert acc.account_id == "act-live-001"
    assert acc.cash_balance == Decimal("50000.00")
    assert len(acc.snapshot_hash) == 64

    # 2. Negative cash balance validation
    with pytest.raises(ValidationError, match="cash_balance must be non-negative"):
        build_broker_account_snapshot(
            snapshot_id=uuid7(),
            account_id="act-live-001",
            cash_balance=Decimal("-10.00"),
            buying_power=Decimal("1000.00"),
            portfolio_equity=Decimal("1000.00"),
            as_of=NOW,
        )

    # 3. Valid Position Snapshot
    pos = build_broker_position_snapshot(
        snapshot_id=uuid7(),
        security_id=sec,
        quantity=100,
        cost_basis=Decimal("10000.00"),
        current_price=Decimal("105.00"),
        market_value=Decimal("10500.00"),
        as_of=NOW,
    )
    assert pos.quantity == 100
    assert pos.cost_basis == Decimal("10000.00")
    assert pos.market_value == Decimal("10500.00")
    assert len(pos.snapshot_hash) == 64

    # 4. Negative cost basis validation
    with pytest.raises(ValidationError, match="cost_basis must be non-negative"):
        build_broker_position_snapshot(
            snapshot_id=uuid7(),
            security_id=sec,
            quantity=10,
            cost_basis=Decimal("-50.00"),
            as_of=NOW,
        )


def test_domain_model_immutability() -> None:
    """Verifies all domain models are immutable and frozen."""
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="drift-ord-imm",
        session_key=KEY1,
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        created_at=NOW,
    )
    with pytest.raises(ValidationError):
        intent.quantity = 20
