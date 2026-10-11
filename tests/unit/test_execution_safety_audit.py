"""Empirical safety audit test suite for execution and risk boundaries (Phase 5).

Demonstrates and verifies architectural safety concerns S1 through S5
against the active repository implementation.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.adapters.robinhood import (
    MockRobinhoodMcpTransport,
    RobinhoodAgenticAdapter,
    RobinhoodAgenticConfigV1,
)
from drift.adapters.robinhood.transport import RobinhoodMcpError
from drift.canary.gatekeeper import CanaryAllocationGatekeeper
from drift.canary.orchestrator import CanaryExecutionOrchestrator
from drift.canary.settlement import CanarySettlementGrader
from drift.domain.canary import CanaryPolicyV1
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.execution import (
    ExecutionStatus,
    OrderIntentV1,
    OrderSide,
    OrderType,
    TimeInForce,
    build_order_intent,
)
from drift.domain.risk import build_risk_policy
from drift.domain.sessions import SessionKeyV1
from drift.execution.adapter import MockBrokerAdapter
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


def _make_intent(
    *, quantity: int = 10, limit_price: Decimal = Decimal("100.00")
) -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=f"audit-intent-{uuid7()}",
        session_key=_make_session_key(),
        security_id=uuid7(),
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )


class _FailingMcpTransport(MockRobinhoodMcpTransport):
    """Transport simulator injecting configurable network/API errors."""

    def __init__(self, *, fail_tool: str, error_message: str) -> None:
        super().__init__()
        self._fail_tool = fail_tool
        self._error_message = error_message

    def call_tool(self, tool_name: str, arguments: Any) -> dict[str, Any]:
        if tool_name == self._fail_tool:
            raise RobinhoodMcpError(self._error_message)
        return super().call_tool(tool_name, arguments)


def _make_state(cash: Decimal = Decimal("100000.00")) -> PortfolioStateV2:
    return PortfolioStateV2(
        lane="exploratory",
        admission_hash="a" * 64,
        session_key=_make_session_key(),
        cash_balance=cash,
        holdings=(),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=None,
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=cash,
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )


def test_s1_router_bypasses_hard_risk_gatekeeper(tmp_path: Any) -> None:
    """Audit S1: Router routes intents without consulting HardRiskGatekeeper.

    The router accepts OrderIntentV1 and dispatches directly to the adapter.
    Even if an active HardRiskGatekeeper with restrictive limits is present
    in the process, the router does not require or evaluate risk verdicts.
    """
    db_path = str(tmp_path / "order_intents.db")
    journal = PersistentOrderIntentJournal(db_path)
    adapter = MockBrokerAdapter(initial_cash=Decimal("50000.00"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    # Intent exceeds typical risk notional
    intent = _make_intent(quantity=100, limit_price=Decimal("200.00"))

    # Intent routes and fills without any risk gatekeeper evaluation
    report = router.route_intent(intent)
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 100


def test_s1_orchestrators_only_check_kill_switch_not_full_policy(tmp_path: Any) -> None:
    """Audit S1: Orchestrators only check is_kill_switch_tripped, bypassing full policy.

    ShadowValidationEngine, CanaryExecutionOrchestrator, and BoundedAutonomyOrchestrator
    accept an optional HardRiskGatekeeper, but only inspect its kill switch latch,
    bypassing rate limits, order notional limits, and exposure limits.
    """
    db_risk = str(tmp_path / "risk.db")
    risk_journal = PersistentRiskJournal(db_risk)
    policy = build_risk_policy(
        policy_id="audit-risk-policy-1",
        max_order_quantity=5,  # Strict order quantity limit of 5 shares
        max_order_notional=Decimal("500.00"),
        max_position_notional=Decimal("2000.00"),
        max_position_weight_basis_points=2500,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=300,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=10,
    )
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=risk_journal)

    db_intents = str(tmp_path / "intents.db")
    intent_journal = PersistentOrderIntentJournal(db_intents)
    adapter = MockBrokerAdapter(initial_cash=Decimal("50000.00"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

    # Configure canary orchestrator with canary limit higher than risk limit
    canary_policy = CanaryPolicyV1(
        canary_authorized=True,
        max_order_quantity=50,
        max_order_notional=Decimal("2000.00"),
        max_cumulative_notional=Decimal("5000.00"),
    )
    canary_gatekeeper = CanaryAllocationGatekeeper(policy=canary_policy)
    canary_grader = CanarySettlementGrader(policy=canary_policy)
    orchestrator = CanaryExecutionOrchestrator(
        router=router,
        gatekeeper=canary_gatekeeper,
        settlement_grader=canary_grader,
        risk_gatekeeper=gatekeeper,
    )

    # Order has quantity=10 (exceeds HardRiskGatekeeper limit of 5 shares)
    intent = _make_intent(quantity=10, limit_price=Decimal("100.00"))
    report, _ = orchestrator.submit_canary_intent(
        intent, reference_price=Decimal("100.00")
    )

    # Confirms S1: Order is approved and routed despite violating gatekeeper policy
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 10


def test_s2_domain_type_mismatch_between_risk_and_execution() -> None:
    """Audit S2: Gatekeeper accepts SimulatedOrderV1 while router accepts OrderIntentV1.

    HardRiskGatekeeper.evaluate_order expects SimulatedOrderV1. An OrderIntentV1
    cannot be directly evaluated without type adaptation.
    """
    policy = build_risk_policy(
        policy_id="audit-risk-policy-2",
        max_order_notional=Decimal("10000.00"),
        max_order_quantity=100,
        max_position_notional=Decimal("50000.00"),
        max_position_weight_basis_points=2500,
        max_gross_exposure_basis_points=10000,
        max_session_drawdown_basis_points=300,
        max_trailing_drawdown_basis_points=1000,
        max_orders_per_minute=10,
    )
    risk_journal = PersistentRiskJournal(":memory:")
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=risk_journal)
    intent = _make_intent()

    # Demonstrates S2 type mismatch: OrderIntentV1 lacks SimulatedOrderV1 fields
    with pytest.raises(AttributeError):
        # SimulatedOrderV1 has order_id, side (str), etc.
        # OrderIntentV1 has intent_id, side (OrderSide enum), etc.
        gatekeeper.evaluate_order(
            intent,  # type: ignore[arg-type]
            portfolio_state=_make_state(),
            current_price=Decimal("100.00"),
            evaluation_time=datetime.now(UTC),
        )


def test_s3_robinhood_cancellation_error_swallowed_as_canceled() -> None:
    """Audit S3: Robinhood cancellation transport error returns CANCELED status.

    RobinhoodAgenticAdapter.cancel_intent catches RobinhoodMcpError and swallows it,
    unconditionally returning ExecutionStatus.CANCELED.
    """
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={sec_id: "AAPL"})
    failing_transport = _FailingMcpTransport(
        fail_tool="robinhood_cancel_order",
        error_message="503 Service Unavailable: broker cancel failed",
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=failing_transport)

    intent = _make_intent()
    # Mock transport does not fill if auto_fill=False
    adapter._intent_to_broker_order[intent.intent_id] = "rh-ord-9999"

    # Cancel intent encounters RobinhoodMcpError on cancel_order tool
    cancel_report = adapter.cancel_intent(intent.intent_id)

    # Confirms S3: Adapter returns CANCELED despite failed cancellation
    assert cancel_report.status == ExecutionStatus.CANCELED
    assert cancel_report.leaves_quantity == 0


def test_s4_ambiguous_submission_error_marked_as_definitive_rejection() -> None:
    """Audit S4: Ambiguous MCP network timeout on submission is marked as REJECTED.

    When robinhood_place_order encounters a timeout or network error, the adapter
    returns ExecutionStatus.REJECTED with broker_order_id=None, even though the order
    may have been received and filled on the broker side.
    """
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={sec_id: "AAPL"})
    failing_transport = _FailingMcpTransport(
        fail_tool="robinhood_place_order",
        error_message="Connection timed out after 30 seconds",
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=failing_transport)

    intent = build_order_intent(
        intent_id=uuid7(),
        client_order_id="ambiguous-cli-001",
        session_key=_make_session_key(),
        security_id=sec_id,
        side=OrderSide.BUY,
        quantity=50,
        order_type=OrderType.LIMIT,
        limit_price=Decimal("150.00"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime.now(UTC),
    )

    report = adapter.submit_intent(intent)

    # Confirms S4: Ambiguous network error is marked as authoritative REJECTED
    assert report.status == ExecutionStatus.REJECTED
    assert report.broker_order_id is None
    assert "Connection timed out" in str(report.rejection_reason)


def test_s5_unknown_symbol_maps_to_fabricated_uuid() -> None:
    """Audit S5: Unmapped Robinhood positions map to fabricated DNS UUIDs and crash.

    RobinhoodAgenticAdapter.get_positions uses uuid5 DNS hashing for unmapped symbols.
    Because BrokerPositionSnapshotV1 requires strict UUIDv7, the fabricated UUIDv5
    fails schema validation and causes get_positions to crash.
    """
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={})
    transport = MockRobinhoodMcpTransport()
    # Populate an unmapped position in the mock transport
    transport._positions["UNMAPPED_TICKER"] = {
        "quantity": 25,
        "cost_basis": Decimal("2500.00"),
    }
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    # Confirms S5: Constructing BrokerPositionSnapshotV1 with UUIDv5 fails validation
    with pytest.raises(ValidationError) as excinfo:
        adapter.get_positions()

    assert "identifiers must be UUIDv7 values" in str(excinfo.value)
