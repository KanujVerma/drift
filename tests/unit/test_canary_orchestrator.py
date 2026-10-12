"""Unit tests for Canary Execution Orchestrator (M17-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.canary.orchestrator import CanaryExecutionOrchestrator
from drift.canary.settlement import CanarySettlementGrader
from drift.domain.canary import CanaryPolicyV1
from drift.domain.execution import (
    ExecutionStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.risk import build_risk_policy
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal


def _make_session_key() -> SessionKeyV1:
    return SessionKeyV1(
        mic="XNYS",
        session_scope="regular",
        local_date=date(2026, 3, 1),
    )


def test_orchestrator_successful_canary_execution(tmp_path: Path) -> None:
    """Authorized canary order is admitted, routed, executed, and settled."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("5.00"),
        whitelisted_symbols=frozenset({"AAPL"}),
        max_slippage_bps=50,
    )
    symbol_map = {sec_id: "AAPL"}

    gatekeeper = CanaryAllocationGatekeeper(policy=policy, symbol_map=symbol_map)
    grader = CanarySettlementGrader(policy=policy)

    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("100.00"),
        price_map={"AAPL": Decimal("4.00")},
    )
    rh_config = RobinhoodAgenticConfigV1(
        account_id="rh-canary-01",
        symbol_map=symbol_map,
    )
    adapter = RobinhoodAgenticAdapter(config=rh_config, transport=transport)

    db_path = tmp_path / "intent_audit.db"
    journal = PersistentOrderIntentJournal(db_path=db_path)
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    orchestrator = CanaryExecutionOrchestrator(
        router=router,
        gatekeeper=gatekeeper,
        settlement_grader=grader,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-orch-01",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    exec_report, settlement_report = orchestrator.submit_canary_intent(intent)
    assert exec_report.status == ExecutionStatus.FILLED
    assert exec_report.cum_quantity == 1
    assert settlement_report is not None
    assert settlement_report.is_settled is True
    assert settlement_report.reconciliation_difference == Decimal("0")


def test_orchestrator_gatekeeper_refusal(tmp_path: Path) -> None:
    """Unauthorized canary intent is rejected pre-trade without contacting router."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(canary_authorized=False)
    gatekeeper = CanaryAllocationGatekeeper(policy=policy, symbol_map={sec_id: "AAPL"})
    grader = CanarySettlementGrader(policy=policy)

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(
            account_id="rh-acc", symbol_map={sec_id: "AAPL"}
        ),
        transport=transport,
    )
    journal = PersistentOrderIntentJournal(db_path=tmp_path / "intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    orchestrator = CanaryExecutionOrchestrator(
        router=router,
        gatekeeper=gatekeeper,
        settlement_grader=grader,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-orch-02",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    exec_report, settlement_report = orchestrator.submit_canary_intent(intent)
    assert exec_report.status == ExecutionStatus.REJECTED
    assert exec_report.rejection_reason is not None
    assert "canary_refusal" in exec_report.rejection_reason
    assert settlement_report is None
    assert len(transport.call_history) == 0


def test_orchestrator_tripped_risk_gatekeeper(tmp_path: Path) -> None:
    """When hard risk kill switch is tripped, canary intent is rejected."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(canary_authorized=True, max_order_notional=Decimal("10.00"))
    gatekeeper = CanaryAllocationGatekeeper(policy=policy, symbol_map={sec_id: "AAPL"})
    grader = CanarySettlementGrader(policy=policy)

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(
            account_id="rh-acc", symbol_map={sec_id: "AAPL"}
        ),
        transport=transport,
    )
    journal = PersistentOrderIntentJournal(db_path=tmp_path / "intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    risk_journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    risk_journal.trip_kill_switch(
        reason="emergency halt tripped",
        tripped_at=datetime.now(UTC),
    )
    risk_policy = build_risk_policy(
        policy_id="test-risk-policy-1",
        max_order_notional=Decimal("100.00"),
        max_order_quantity=10,
        max_position_notional=Decimal("100.00"),
        max_position_weight_basis_points=1000,
        max_gross_exposure_basis_points=2000,
        max_session_drawdown_basis_points=500,
        max_trailing_drawdown_basis_points=500,
        max_orders_per_minute=10,
    )
    risk_gatekeeper = HardRiskGatekeeper(policy=risk_policy, journal=risk_journal)

    orchestrator = CanaryExecutionOrchestrator(
        router=router,
        gatekeeper=gatekeeper,
        settlement_grader=grader,
        risk_gatekeeper=risk_gatekeeper,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="canary-orch-03",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    exec_report, settlement_report = orchestrator.submit_canary_intent(intent)
    assert exec_report.status == ExecutionStatus.REJECTED
    assert exec_report.rejection_reason is not None
    assert "risk_halt" in exec_report.rejection_reason
    assert settlement_report is None
    assert len(transport.call_history) == 0
