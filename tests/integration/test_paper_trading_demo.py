"""Integration test demonstrating end-to-end simulated paper trading workflow.

Verifies:
- Initial capital: $10,000.00
- Multi-asset order intent generation
- Tier-based allocation governance and limit enforcement
- Execution routing through official Robinhood adapter (mock transport)
- Real-time fill tracking, portfolio reconciliation, and NAV reporting
- Fail-closed risk rejection demonstration
- Persistent SQLite intent journal and evidence ledger verification
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
from drift.domain.autonomy import AutonomyTier
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


def test_end_to_end_paper_trading_simulation(tmp_path: Path) -> None:
    """Execute end-to-end simulated paper trading workflow and verify all states."""
    aapl_id = uuid7()
    msft_id = uuid7()
    nvda_id = uuid7()

    symbol_map: dict[UUID, str] = {
        aapl_id: "AAPL",
        msft_id: "MSFT",
        nvda_id: "NVDA",
    }
    price_map: dict[str, Decimal] = {
        "AAPL": Decimal("40.00"),
        "MSFT": Decimal("80.00"),
        "NVDA": Decimal("25.00"),
    }

    intent_db = tmp_path / "order_intents.db"
    risk_db = tmp_path / "risk_journal.db"
    gov_db = tmp_path / "autonomy_ledger.db"

    intent_journal = PersistentOrderIntentJournal(intent_db)
    risk_journal = PersistentRiskJournal(risk_db)
    gov_ledger = PersistentEvidenceLedger(gov_db)

    try:
        risk_policy = build_risk_policy(
            policy_id="paper-trading-risk-01",
            max_order_quantity=100,
            max_order_notional=Decimal("1000.00"),
            max_position_notional=Decimal("5000.00"),
            max_position_weight_basis_points=4000,
            max_gross_exposure_basis_points=10000,
            max_session_drawdown_basis_points=500,
            max_trailing_drawdown_basis_points=1000,
            max_orders_per_minute=20,
        )
        risk_gatekeeper = HardRiskGatekeeper(
            policy=risk_policy,
            journal=risk_journal,
            initial_nav=Decimal("10000.00"),
        )

        governor = AllocationExpansionGovernor(
            ledger=gov_ledger,
            initial_tier=AutonomyTier.TIER_3_BOUNDED,
        )

        initial_cash = Decimal("10000.00")
        transport = MockRobinhoodMcpTransport(
            initial_cash=initial_cash,
            price_map=price_map,
        )
        rh_config = RobinhoodAgenticConfigV1(
            account_id="paper-rh-account-01",
            symbol_map=symbol_map,
        )
        adapter = RobinhoodAgenticAdapter(config=rh_config, transport=transport)
        router = BrokerNeutralExecutionRouter(
            adapter=adapter,
            journal=intent_journal,
        )

        orchestrator = BoundedAutonomyOrchestrator(
            governor=governor,
            router=router,
            risk_gatekeeper=risk_gatekeeper,
        )

        session_key = SessionKeyV1(
            mic="XNYS",
            session_scope="regular",
            local_date=date.today(),
        )

        # 1. Buy 10 AAPL @ $40 (Notional $400 <= $500 cap) -> FILLED
        intent_1 = build_order_intent(
            intent_id=uuid7(),
            client_order_id="ORD-001",
            session_key=session_key,
            security_id=aapl_id,
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("40.00"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        rep_1 = orchestrator.submit_autonomous_intent(intent_1, Decimal("40.00"))
        assert rep_1.status == ExecutionStatus.FILLED
        assert rep_1.cum_quantity == 10

        # 2. Buy 5 MSFT @ $80 (Notional $400 <= $500 cap) -> FILLED
        intent_2 = build_order_intent(
            intent_id=uuid7(),
            client_order_id="ORD-002",
            session_key=session_key,
            security_id=msft_id,
            side=OrderSide.BUY,
            quantity=5,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("80.00"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        rep_2 = orchestrator.submit_autonomous_intent(intent_2, Decimal("80.00"))
        assert rep_2.status == ExecutionStatus.FILLED
        assert rep_2.cum_quantity == 5

        # 3. Buy 16 NVDA @ $25 (Notional $400 <= $500 cap) -> FILLED
        intent_3 = build_order_intent(
            intent_id=uuid7(),
            client_order_id="ORD-003",
            session_key=session_key,
            security_id=nvda_id,
            side=OrderSide.BUY,
            quantity=16,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("25.00"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        rep_3 = orchestrator.submit_autonomous_intent(intent_3, Decimal("25.00"))
        assert rep_3.status == ExecutionStatus.FILLED
        assert rep_3.cum_quantity == 16

        # 4. Oversized Order: Buy 20 MSFT @ $80 (Notional $1600 > $500 cap) -> REJECTED
        intent_4 = build_order_intent(
            intent_id=uuid7(),
            client_order_id="ORD-004",
            session_key=session_key,
            security_id=msft_id,
            side=OrderSide.BUY,
            quantity=20,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("80.00"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        rep_4 = orchestrator.submit_autonomous_intent(intent_4, Decimal("80.00"))
        assert rep_4.status == ExecutionStatus.REJECTED
        assert "tier_notional_limit_exceeded" in str(rep_4.rejection_reason)

        # 5. Sell 5 AAPL @ $44 (Profit-taking) -> FILLED
        transport.set_market_price("AAPL", Decimal("44.00"))
        intent_5 = build_order_intent(
            intent_id=uuid7(),
            client_order_id="ORD-005",
            session_key=session_key,
            security_id=aapl_id,
            side=OrderSide.SELL,
            quantity=5,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("44.00"),
            time_in_force=TimeInForce.DAY,
            created_at=datetime.now(UTC),
        )
        rep_5 = orchestrator.submit_autonomous_intent(intent_5, Decimal("44.00"))
        assert rep_5.status == ExecutionStatus.FILLED
        assert rep_5.cum_quantity == 5

        # 6. Reconcile Holdings and Cash
        positions = adapter.get_positions()
        pos_by_sec = {p.security_id: p for p in positions}

        assert pos_by_sec[aapl_id].quantity == 5  # Bought 10, sold 5
        assert pos_by_sec[msft_id].quantity == 5
        assert pos_by_sec[nvda_id].quantity == 16

        # Cash: 10,000 - 400 - 400 - 400 + 220 = 9,020.00
        ending_cash = adapter.get_account_snapshot().cash_balance
        assert ending_cash == Decimal("9020.00")

        # Total NAV: Cash ($9,020) + AAPL (5*44 = 220) + MSFT (5*80 = 400)
        # + NVDA (16*25 = 400) = $10,040.00
        invested = sum(
            (p.market_value for p in positions if p.market_value is not None),
            Decimal("0.00"),
        )
        assert invested == Decimal("1020.00")
        assert ending_cash + invested == Decimal("10040.00")

        # 7. Audit Verification
        logged_intents = intent_journal.list_intents_for_session(session_key)
        assert len(logged_intents) == 4  # The 4 routed intents
        assert not risk_journal.is_kill_switch_tripped()
    finally:
        intent_journal.close()
        risk_journal.close()
        gov_ledger.close()
