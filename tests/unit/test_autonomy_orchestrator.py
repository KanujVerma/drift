"""Unit tests for Bounded Autonomy Orchestrator (M18-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.autonomy.governor import AllocationExpansionGovernor
from drift.autonomy.ledger import PersistentEvidenceLedger
from drift.autonomy.orchestrator import BoundedAutonomyOrchestrator
from drift.domain.autonomy import AutonomyTier, GovernanceTransitionType
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


def test_orchestrator_successful_submission_and_fill(tmp_path: Path) -> None:
    """Valid order within tier caps executes and records clean session."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_0_CANARY,
    )

    transport = MockRobinhoodMcpTransport(
        initial_cash=Decimal("100.00"),
        price_map={"AAPL": Decimal("4.00")},
    )
    rh_config = RobinhoodAgenticConfigV1(account_id="rh-01", symbol_map=symbol_map)
    adapter = RobinhoodAgenticAdapter(config=rh_config, transport=transport)

    intent_journal = PersistentOrderIntentJournal(db_path=tmp_path / "intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

    orchestrator = BoundedAutonomyOrchestrator(
        governor=governor,
        router=router,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="auto-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = orchestrator.submit_autonomous_intent(intent)
    assert report.status == ExecutionStatus.FILLED
    assert governor.clean_sessions_at_current_tier == 1

    gov_ledger.close()


def test_orchestrator_tier_quantity_breach_rejected(tmp_path: Path) -> None:
    """Order exceeding active tier max quantity is rejected pre-route."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_0_CANARY,  # max quantity = 1
    )

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-02", symbol_map=symbol_map),
        transport=transport,
    )
    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=PersistentOrderIntentJournal(db_path=tmp_path / "intent.db"),
    )
    orchestrator = BoundedAutonomyOrchestrator(governor=governor, router=router)

    # Request 2 shares when Tier 0 limit is 1 share
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="auto-002",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("2.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = orchestrator.submit_autonomous_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert "tier_quantity_limit_exceeded" in str(report.rejection_reason)
    assert len(transport.call_history) == 0

    gov_ledger.close()


def test_orchestrator_tier_notional_breach_rejected(tmp_path: Path) -> None:
    """Order exceeding active tier notional cap is rejected pre-route."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_0_CANARY,  # max notional = $5.00
    )

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-03", symbol_map=symbol_map),
        transport=transport,
    )
    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=PersistentOrderIntentJournal(db_path=tmp_path / "intent.db"),
    )
    orchestrator = BoundedAutonomyOrchestrator(governor=governor, router=router)

    # Request $8.00 notional when Tier 0 limit is $5.00
    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="auto-003",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("8.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = orchestrator.submit_autonomous_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert "tier_notional_limit_exceeded" in str(report.rejection_reason)
    assert len(transport.call_history) == 0

    gov_ledger.close()


def test_orchestrator_evidence_review_and_tier_update(tmp_path: Path) -> None:
    """Periodic evidence review evaluates metrics and records transition."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_0_CANARY,
        min_sessions_per_tier=2,
    )
    # Complete 2 clean sessions
    governor.record_clean_session()
    governor.record_clean_session()

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-04", symbol_map=symbol_map),
        transport=transport,
    )
    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=PersistentOrderIntentJournal(db_path=tmp_path / "intent.db"),
    )
    orchestrator = BoundedAutonomyOrchestrator(governor=governor, router=router)

    scorecard = {"deflated_sharpe_ratio": "1.7", "pbo": "0.10"}
    transition = orchestrator.review_evidence_and_update_tier(scorecard)

    assert transition.transition_type == GovernanceTransitionType.PROMOTION
    assert transition.target_tier == AutonomyTier.TIER_1_MICRO
    assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO

    gov_ledger.close()


def test_orchestrator_kill_switch_tripped_rejects_and_freezes(
    tmp_path: Path,
) -> None:
    """When kill switch is active, order is rejected and tier collapses to canary."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_2_SMALL,
    )

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-05", symbol_map=symbol_map),
        transport=transport,
    )
    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=PersistentOrderIntentJournal(db_path=tmp_path / "intent.db"),
    )

    risk_journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    risk_journal.trip_kill_switch(
        reason="emergency halt",
        tripped_at=datetime.now(UTC),
    )
    risk_policy = build_risk_policy(
        policy_id="risk-pol",
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

    orchestrator = BoundedAutonomyOrchestrator(
        governor=governor,
        router=router,
        risk_gatekeeper=risk_gatekeeper,
    )

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="auto-005",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("4.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = orchestrator.submit_autonomous_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert "emergency_kill_switch_active" in str(report.rejection_reason)
    assert governor.get_current_tier() == AutonomyTier.TIER_0_CANARY

    gov_ledger.close()
