"""Unit tests for execution safety risk gatekeeper enforcement (Issue #361, S1-S2).

Verifies that HardRiskGatekeeper evaluates OrderIntentV1 correctly across
execution boundaries (router, canary orchestrator, autonomy orchestrator),
and rejects non-compliant intents pre-trade without bypassing quantitative limits.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid7

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.autonomy.governor import AllocationExpansionGovernor
from drift.autonomy.ledger import PersistentEvidenceLedger
from drift.autonomy.orchestrator import BoundedAutonomyOrchestrator
from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.canary.orchestrator import CanaryExecutionOrchestrator
from drift.canary.settlement import CanarySettlementGrader
from drift.domain.autonomy import AutonomyTier
from drift.domain.canary import CanaryPolicyV1
from drift.domain.evaluator_portfolio import (
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioMarkV1,
    PortfolioStateV2,
    SecurityHoldingV2,
)
from drift.domain.execution import (
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.risk import (
    RiskVerdictStatus,
    build_risk_policy,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import PersistentOrderIntentJournal
from drift.execution.router import BrokerNeutralExecutionRouter
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_intent(
    *,
    sec_id: UUID,
    side: OrderSide = OrderSide.BUY,
    quantity: int = 10,
    price: Decimal = Decimal("50.00"),
    order_type: OrderType = OrderType.LIMIT,
    client_order_id: str = "safety-intent-01",
) -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=client_order_id,
        session_key=KEY1,
        security_id=sec_id,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=price if order_type == OrderType.LIMIT else None,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
    )


def test_gatekeeper_evaluates_order_intent_v1_without_portfolio_state(
    tmp_path: Path,
) -> None:
    """HardRiskGatekeeper evaluates OrderIntentV1 when portfolio_state is None."""
    journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    policy = build_risk_policy(
        policy_id="safety-pol-1",
        max_order_notional=Decimal("1000.00"),
        max_order_quantity=20,
        max_position_notional=Decimal("5000.00"),
        max_position_weight_basis_points=2500,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=500,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=5,
    )
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)
    sec_id = uuid7()

    # 1. Valid intent allowed
    intent_ok = _make_intent(sec_id=sec_id, quantity=10, price=Decimal("50.00"))
    v_ok = gatekeeper.evaluate_order(
        intent_ok, current_price=Decimal("50.00"), evaluation_time=NOW
    )
    assert v_ok.status == RiskVerdictStatus.ALLOWED
    assert v_ok.order_id == intent_ok.intent_id

    # 2. evaluate_intent alias returns same verdict idempotently
    v_alias = gatekeeper.evaluate_intent(
        intent_ok, current_price=Decimal("50.00"), evaluation_time=NOW
    )
    assert v_alias.status == RiskVerdictStatus.ALLOWED
    assert v_alias.verdict_hash == v_ok.verdict_hash

    # 3. Exceeds max order quantity -> REJECTED
    intent_qty = _make_intent(
        sec_id=sec_id, quantity=50, client_order_id="safety-qty-01"
    )
    v_qty = gatekeeper.evaluate_order(
        intent_qty, current_price=Decimal("10.00"), evaluation_time=NOW
    )
    assert v_qty.status == RiskVerdictStatus.REJECTED
    assert "max_order_quantity_exceeded" in str(v_qty.reason)

    # 4. Exceeds max order notional -> REJECTED
    intent_notional = _make_intent(
        sec_id=sec_id,
        quantity=15,
        price=Decimal("100.00"),
        client_order_id="safety-notional-01",
    )
    v_notional = gatekeeper.evaluate_order(
        intent_notional, current_price=Decimal("100.00"), evaluation_time=NOW
    )
    assert v_notional.status == RiskVerdictStatus.REJECTED
    assert "max_order_notional_exceeded" in str(v_notional.reason)

    # 5. Invalid price -> fail closed
    intent_bad_price = _make_intent(
        sec_id=sec_id, quantity=5, client_order_id="safety-bad-price-01"
    )
    v_price = gatekeeper.evaluate_order(
        intent_bad_price, current_price=None, evaluation_time=NOW
    )
    assert v_price.status == RiskVerdictStatus.REJECTED
    assert "indeterminate_market_price" in str(v_price.reason)


def test_gatekeeper_evaluates_order_intent_v1_with_portfolio_state(
    tmp_path: Path,
) -> None:
    """HardRiskGatekeeper evaluates OrderIntentV1 concentration limits."""
    journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    policy = build_risk_policy(
        policy_id="safety-pol-2",
        max_order_notional=Decimal("1000.00"),
        max_order_quantity=20,
        max_position_notional=Decimal("600.00"),  # $600 max per position
        max_position_weight_basis_points=5000,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=500,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=5,
    )
    gatekeeper = HardRiskGatekeeper(
        policy=policy, journal=journal, initial_nav=Decimal("750.00")
    )
    sec_id = uuid7()

    mark = PortfolioMarkV1(
        session_key=KEY1,
        lane="exploratory",
        prices=(
            MarkPriceV1(
                security_id=sec_id,
                close_price=Decimal("50.00"),
                evidence=MarkEvidenceV1(
                    grade="exploratory",
                    evidence_hash="a" * 64,
                ),
            ),
        ),
    )
    state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="a" * 64,
        session_key=KEY1,
        cash_balance=Decimal("500.00"),
        holdings=(
            SecurityHoldingV2(
                security_id=sec_id,
                quantity=5,
                basis_status="known",
                cost_basis=Decimal("250.00"),
            ),
        ),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=mark,
        holdings_market_value=Decimal("250.00"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal("750.00"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )

    # 10 more shares at $50 -> projected position = 15 * $50 = $750 > $600 limit
    intent = _make_intent(
        sec_id=sec_id,
        quantity=10,
        price=Decimal("50.00"),
        client_order_id="safety-conc-01",
    )
    v = gatekeeper.evaluate_order(
        intent,
        portfolio_state=state,
        current_price=Decimal("50.00"),
        evaluation_time=NOW,
    )
    assert v.status == RiskVerdictStatus.REJECTED
    assert "max_position_notional_exceeded" in str(v.reason)


def test_router_with_risk_gatekeeper_rejects_pre_trade(tmp_path: Path) -> None:
    """BrokerNeutralExecutionRouter with risk gatekeeper rejects bad intent."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("1000.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-safe-01", symbol_map=symbol_map),
        transport=transport,
    )
    intent_journal = PersistentOrderIntentJournal(db_path=tmp_path / "intent.db")
    risk_journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    risk_policy = build_risk_policy(
        policy_id="safety-pol-router",
        max_order_notional=Decimal("200.00"),  # max $200
        max_order_quantity=10,
        max_position_notional=Decimal("1000.00"),
        max_position_weight_basis_points=5000,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=500,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=5,
    )
    risk_gatekeeper = HardRiskGatekeeper(policy=risk_policy, journal=risk_journal)

    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=intent_journal,
        risk_gatekeeper=risk_gatekeeper,
    )

    # Submit intent with $500 notional (exceeds $200 policy limit)
    intent = _make_intent(
        sec_id=sec_id,
        quantity=5,
        price=Decimal("100.00"),
        client_order_id="safety-router-reject-01",
    )

    exec_report = router.route_intent(intent)
    assert exec_report.status == ExecutionStatus.REJECTED
    assert "risk_gatekeeper_rejection" in str(exec_report.rejection_reason)
    assert "max_order_notional_exceeded" in str(exec_report.rejection_reason)
    # Broker adapter was NEVER called
    assert len(transport.call_history) == 0

    # Idempotent resubmission returns recorded rejected report
    replay_report = router.route_intent(intent)
    assert replay_report.status == ExecutionStatus.REJECTED
    assert replay_report.report_id == exec_report.report_id
    assert len(transport.call_history) == 0


def test_canary_orchestrator_enforces_quantitative_risk_limits(
    tmp_path: Path,
) -> None:
    """CanaryExecutionOrchestrator rejects intent exceeding risk policy quantity."""
    sec_id = uuid7()
    policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_notional=Decimal("100.00"),
        max_cumulative_notional=Decimal("200.00"),
        max_order_quantity=10,
    )
    gatekeeper = CanaryAllocationGatekeeper(policy=policy, symbol_map={sec_id: "AAPL"})
    grader = CanarySettlementGrader(policy=policy)

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("100.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(
            account_id="rh-canary", symbol_map={sec_id: "AAPL"}
        ),
        transport=transport,
    )
    journal = PersistentOrderIntentJournal(db_path=tmp_path / "intent.db")
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    # Risk gatekeeper with tighter quantity limit: 2 shares
    risk_journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    risk_policy = build_risk_policy(
        policy_id="test-canary-risk-policy",
        max_order_notional=Decimal("50.00"),
        max_order_quantity=2,  # tighter than canary limit of 10
        max_position_notional=Decimal("50.00"),
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

    # 5 shares: passes canary (5 <= 10, $20 <= $100), but breaches risk (5 > 2)
    intent = _make_intent(
        sec_id=sec_id,
        quantity=5,
        price=Decimal("4.00"),
        client_order_id="canary-risk-qty-breach",
    )

    exec_report, settlement_report = orchestrator.submit_canary_intent(intent)
    assert exec_report.status == ExecutionStatus.REJECTED
    assert exec_report.rejection_reason is not None
    assert "risk_halt" in exec_report.rejection_reason
    assert "max_order_quantity_exceeded" in exec_report.rejection_reason
    assert settlement_report is None
    assert len(transport.call_history) == 0


def test_autonomy_orchestrator_demotes_on_risk_gatekeeper_rejection(
    tmp_path: Path,
) -> None:
    """BoundedAutonomyOrchestrator demotes tier on risk limit breach."""
    sec_id = uuid7()
    symbol_map = {sec_id: "AAPL"}

    gov_ledger = PersistentEvidenceLedger(db_path=tmp_path / "gov.db")
    governor = AllocationExpansionGovernor(
        ledger=gov_ledger,
        initial_tier=AutonomyTier.TIER_2_SMALL,  # Tier 2 allows up to $50 notional
    )

    transport = MockRobinhoodMcpTransport(initial_cash=Decimal("500.00"))
    adapter = RobinhoodAgenticAdapter(
        config=RobinhoodAgenticConfigV1(account_id="rh-auto-01", symbol_map=symbol_map),
        transport=transport,
    )
    router = BrokerNeutralExecutionRouter(
        adapter=adapter,
        journal=PersistentOrderIntentJournal(db_path=tmp_path / "intent.db"),
    )

    # Risk policy restricts order notional to $20, tighter than Tier 2's $50
    risk_journal = PersistentRiskJournal(db_path=tmp_path / "risk.db")
    risk_policy = build_risk_policy(
        policy_id="test-auto-risk-pol",
        max_order_notional=Decimal("20.00"),
        max_order_quantity=10,
        max_position_notional=Decimal("200.00"),
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

    # $30 notional (3 * $10) passes Tier 2 ($50 max) but breaches risk ($20 max)
    intent = _make_intent(
        sec_id=sec_id,
        quantity=3,
        price=Decimal("10.00"),
        client_order_id="auto-risk-notional-breach",
    )

    report = orchestrator.submit_autonomous_intent(intent)
    assert report.status == ExecutionStatus.REJECTED
    assert "risk_gatekeeper_rejection" in str(report.rejection_reason)
    assert "max_order_notional_exceeded" in str(report.rejection_reason)

    # Tier must be demoted from TIER_2_SMALL to TIER_1_MICRO
    assert governor.get_current_tier() == AutonomyTier.TIER_1_MICRO
    assert len(transport.call_history) == 0

    gov_ledger.close()
