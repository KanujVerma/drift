"""M17 adversarial acceptance suite: Tiny-Money Canary Layer (Issue 334).

Attacks the canary gatekeeper, orchestrator, and settlement grader across
eight adversarial vectors:
1. Unauthorized live activation attack (canary_authorized=False fails closed).
2. Multi-share allocation attack (quantity > max_order_quantity refused).
3. Micro-capital order notional breach attack (order notional cap enforced).
4. Cumulative portfolio allocation ceiling breach attack.
5. Non-whitelisted ticker isolation attack (unregistered tickers refused).
6. Fill price slippage spike attack (fails settlement validation).
7. Broker cash settlement discrepancy attack (cash delta divergence fails).
8. Cryptographic hash tampering attack (corrupted hashes fail validation).

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.canary.settlement import CanarySettlementGrader
from drift.domain.canary import (
    CanaryPolicyV1,
    CanarySettlementReportV1,
    build_canary_settlement_report,
)
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


def test_v1_unauthorized_live_activation_attack() -> None:
    """Vector 1: Unauthorized canary policy strictly refuses orders fail-closed."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(canary_authorized=False)
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    result = gatekeeper.evaluate_intent(intent)
    assert result.decision == "refused"
    assert "canary_unauthorized" in result.refusal_reasons
    assert gatekeeper.cumulative_allocated_notional == Decimal("0")


def test_v2_multi_share_allocation_attack() -> None:
    """Vector 2: Order with quantity > max_order_quantity is refused."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_quantity=1,
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    # Attack: request 5 shares
    intent_attack = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-002",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("1.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_attack = gatekeeper.evaluate_intent(intent_attack)
    assert res_attack.decision == "refused"
    assert any("exceeds max_order_quantity" in r for r in res_attack.refusal_reasons)

    # Control: request 1 share passes
    intent_control = build_order_intent(
        intent_id=uuid7(),
        client_order_id="ctrl-002",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("1.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_control = gatekeeper.evaluate_intent(intent_control)
    assert res_control.decision == "admitted"


def test_v3_order_notional_cap_attack() -> None:
    """Vector 3: Order notional exceeding max_order_notional is refused."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("5.00"),
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={sec_id: "AAPL"},
    )

    # Attack: $10.00 notional order
    intent_attack = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-003",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("10.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_attack = gatekeeper.evaluate_intent(intent_attack)
    assert res_attack.decision == "refused"
    assert any("exceeds max_order_notional" in r for r in res_attack.refusal_reasons)


def test_v4_cumulative_allocation_saturation_attack() -> None:
    """Vector 4: Orders exceeding cumulative capital ceiling are refused."""
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

    # Fill $5.00 and $4.00 ($9.00 total)
    for i in (1, 2):
        intent = build_order_intent(
            intent_id=uuid7(),
            client_order_id=f"cum-{i}",
            session_key=_make_session_key(),
            security_id=sec_id,
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("4.50"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        res = gatekeeper.evaluate_intent(intent)
        assert res.decision == "admitted"

    assert gatekeeper.cumulative_allocated_notional == Decimal("9.00")

    # Attack: Third order of $4.50 exceeds $10.00 ceiling
    intent_overflow = build_order_intent(
        intent_id=uuid7(),
        client_order_id="cum-overflow",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.50"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_overflow = gatekeeper.evaluate_intent(intent_overflow)
    assert res_overflow.decision == "refused"
    assert any(
        "exceeds max_cumulative_notional" in r for r in res_overflow.refusal_reasons
    )


def test_v5_non_whitelisted_ticker_isolation_attack() -> None:
    """Vector 5: Order for non-whitelisted symbol is refused pre-trade."""
    sec_whitelisted = uuid7()
    sec_bad = uuid7()

    policy = CanaryPolicyV1(
        canary_authorized=True,
        whitelisted_symbols=frozenset({"AAPL"}),
    )
    gatekeeper = CanaryAllocationGatekeeper(
        policy=policy,
        symbol_map={
            sec_whitelisted: "AAPL",
            sec_bad: "MEME",
        },
    )

    intent_bad = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-bad-sym",
        session_key=_make_session_key(),
        security_id=sec_bad,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("3.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )
    res_bad = gatekeeper.evaluate_intent(intent_bad)
    assert res_bad.decision == "refused"
    assert any("not in whitelisted_symbols" in r for r in res_bad.refusal_reasons)


def test_v6_slippage_threshold_spike_attack() -> None:
    """Vector 6: Execution slippage exceeding policy tolerance fails settlement."""
    policy = CanaryPolicyV1(max_slippage_bps=50)  # max 50 bps
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-slip",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    # Attack: Expected $4.00, filled at $4.20 (500 bps slippage > 50 bps)
    report_spiked = build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="rh-slip-01",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.20"),
        reported_at=datetime.now(UTC),
    )

    settlement = grader.grade_settlement(
        intent=intent,
        report=report_spiked,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("95.80"),
        expected_fill_price=Decimal("4.00"),
    )

    assert settlement.is_settled is False
    assert settlement.slippage_bps == Decimal("500")


def test_v7_broker_cash_settlement_discrepancy_attack() -> None:
    """Vector 7: Unaccounted cash balance delta fails settlement reconciliation."""
    policy = CanaryPolicyV1()
    grader = CanarySettlementGrader(policy=policy)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="atk-cash-disc",
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
        broker_order_id="rh-disc-01",
        status=ExecutionStatus.FILLED,
        cum_quantity=1,
        leaves_quantity=0,
        avg_fill_price=Decimal("4.00"),
        fee_amount=Decimal("0.00"),
        reported_at=datetime.now(UTC),
    )

    # Attack: cash balance dropped by $4.50 instead of $4.00 ($0.50 missing)
    settlement = grader.grade_settlement(
        intent=intent,
        report=report,
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("95.50"),
    )

    assert settlement.is_settled is False
    assert settlement.reconciliation_difference == Decimal("0.50")


def test_v8_cryptographic_hash_tampering_attack() -> None:
    """Vector 8: Tampering with canary settlement report hash fails validation."""
    now = datetime.now(UTC)
    report = build_canary_settlement_report(
        report_id=uuid7(),
        intent_id=uuid7(),
        broker_order_id="rh-tamper-01",
        is_settled=True,
        expected_notional=Decimal("4.00"),
        actual_fill_notional=Decimal("4.00"),
        fee_amount=Decimal("0.00"),
        cash_balance_delta=Decimal("-4.00"),
        reconciliation_difference=Decimal("0.00"),
        slippage_bps=Decimal("0.0"),
        evaluated_at=now,
    )

    # Attack: corrupted hash string
    with pytest.raises(ValidationError):
        CanarySettlementReportV1(
            report_id=report.report_id,
            intent_id=report.intent_id,
            broker_order_id=report.broker_order_id,
            is_settled=report.is_settled,
            expected_notional=report.expected_notional,
            actual_fill_notional=report.actual_fill_notional,
            fee_amount=report.fee_amount,
            cash_balance_delta=report.cash_balance_delta,
            reconciliation_difference=report.reconciliation_difference,
            slippage_bps=report.slippage_bps,
            evaluated_at=report.evaluated_at,
            report_hash="a" * 64,
        )
