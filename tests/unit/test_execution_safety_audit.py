"""Empirical safety audit test suite for execution and risk boundaries (Phase 5).

Demonstrates and verifies architectural safety concerns S1 through S5
against the active repository implementation.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid7

import pytest

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
from drift.domain.risk import RiskVerdictStatus, build_risk_policy
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


# =============================================================================
# DEFECT REPRODUCTION AND REGRESSION TESTS (S1 through S5)
# =============================================================================


def test_s1_reproduce_router_bypasses_hard_risk_gatekeeper(tmp_path: Any) -> None:
    """Defect Reproduction S1: Router routes intents without gatekeeper.

    Reproduces the known defect where OrderIntentV1 is dispatched directly
    without evaluating active risk limits.
    """
    db_path = str(tmp_path / "order_intents.db")
    journal = PersistentOrderIntentJournal(db_path)
    adapter = MockBrokerAdapter(initial_cash=Decimal("50000.00"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    # Intent exceeds typical risk notional
    intent = _make_intent(quantity=100, limit_price=Decimal("200.00"))

    # Confirms S1 defect: routes and fills without risk evaluation
    report = router.route_intent(intent)
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 100


def test_s1_configured_orchestrator_rejects_order_violating_hard_risk_policy(
    tmp_path: Any,
) -> None:
    """Positive regression S1: Configured orchestrator rejects risk violation.

    Verifies that CanaryExecutionOrchestrator with configured HardRiskGatekeeper
    enforces quantitative order limits and rejects non-compliant intents.
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

    # Order quantity=10 exceeds HardRiskGatekeeper limit of 5 shares
    intent = _make_intent(quantity=10, limit_price=Decimal("100.00"))
    report, _ = orchestrator.submit_canary_intent(
        intent, reference_price=Decimal("100.00")
    )

    # Confirms hard-risk rejection: order rejected before routing
    assert report.status == ExecutionStatus.REJECTED
    assert "risk_halt" in str(report.rejection_reason)


def test_s1_orchestrator_permits_none_gatekeeper_bypassing_risk(
    tmp_path: Any,
) -> None:
    """Negative coverage S1: Orchestrators permit risk_gatekeeper=None, bypassing risk.

    Demonstrates that when CanaryExecutionOrchestrator is instantiated without
    a HardRiskGatekeeper (risk_gatekeeper=None), quantitative risk checks are
    bypassed and orders are filled directly by the router.
    """
    db_intents = str(tmp_path / "intents.db")
    intent_journal = PersistentOrderIntentJournal(db_intents)
    adapter = MockBrokerAdapter(initial_cash=Decimal("50000.00"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=intent_journal)

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
        risk_gatekeeper=None,
    )

    intent = _make_intent(quantity=10, limit_price=Decimal("100.00"))
    report, _ = orchestrator.submit_canary_intent(
        intent, reference_price=Decimal("100.00")
    )

    # Confirms risk_gatekeeper=None permits execution without hard-risk checks
    assert report.status == ExecutionStatus.FILLED
    assert report.cum_quantity == 10


def test_s2_gatekeeper_evaluates_order_intent_v1_and_enforces_limits() -> None:
    """Regression S2: HardRiskGatekeeper evaluates OrderIntentV1 and enforces policy.

    Verifies that OrderIntentV1 is supported without AttributeError, producing
    valid RiskVerdict reports for both compliant and non-compliant orders.
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

    # 1. Valid OrderIntentV1 evaluated and produces valid ALLOWED verdict
    intent_ok = _make_intent(quantity=10, limit_price=Decimal("100.00"))
    verdict_ok = gatekeeper.evaluate_order(
        intent_ok,
        portfolio_state=_make_state(),
        current_price=Decimal("100.00"),
        evaluation_time=datetime.now(UTC),
    )
    assert verdict_ok is not None
    assert verdict_ok.status == RiskVerdictStatus.ALLOWED

    # 2. Intent exceeding configured risk policy receives appropriate refusal
    intent_exceeding = _make_intent(quantity=150, limit_price=Decimal("100.00"))
    verdict_exceeding = gatekeeper.evaluate_order(
        intent_exceeding,
        portfolio_state=_make_state(),
        current_price=Decimal("100.00"),
        evaluation_time=datetime.now(UTC),
    )
    assert verdict_exceeding is not None
    assert verdict_exceeding.status == RiskVerdictStatus.REJECTED
    assert "max_order_quantity_exceeded" in str(verdict_exceeding.reason)


def test_s3_cancellation_error_not_swallowed_and_preserves_failure_reason() -> None:
    """Regression S3: Robinhood cancellation error is not swallowed as CANCELED.

    Verifies that transport cancellation errors are not swallowed, the adapter
    does not report confirmed CANCELED, and the failure reason is preserved.
    """
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={sec_id: "AAPL"})
    failing_transport = _FailingMcpTransport(
        fail_tool="robinhood_cancel_order",
        error_message="503 Service Unavailable: broker cancel failed",
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=failing_transport)

    intent = _make_intent()
    adapter._intent_to_broker_order[intent.intent_id] = "rh-ord-9999"

    cancel_report = adapter.cancel_intent(intent.intent_id)

    # Cancellation error is not swallowed: does NOT report CANCELED
    assert cancel_report.status != ExecutionStatus.CANCELED
    # Failure reason is preserved
    assert cancel_report.rejection_reason is not None
    assert "cancellation_failed" in cancel_report.rejection_reason
    assert "503 Service Unavailable" in cancel_report.rejection_reason


def test_s4_reproduce_ambiguous_submission_error_marked_as_definitive_rejection() -> (
    None
):
    """Defect Reproduction S4: Submission network timeout marked as REJECTED.

    Reproduces the known defect where ambiguous timeout is marked as terminal REJECTED.
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

    # Confirms S4 defect: ambiguous timeout is authoritatively marked REJECTED
    assert report.status == ExecutionStatus.REJECTED
    assert report.broker_order_id is None
    assert "Connection timed out" in str(report.rejection_reason)


def test_s5_unmapped_positions_quarantined_without_crash_or_fabricated_uuid() -> None:
    """Regression S5: Unmapped positions quarantined, valid mapped positions preserved.

    Verifies that unmapped symbols do not crash validation, do not fabricate
    synthetic UUIDs, and are quarantined while mapped positions are preserved.
    """
    mapped_sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(
        account_id="acc-01",
        symbol_map={mapped_sec_id: "AAPL"},
    )
    transport = MockRobinhoodMcpTransport()
    transport._positions["AAPL"] = {
        "quantity": 10,
        "cost_basis": Decimal("1500.00"),
    }
    transport._positions["UNMAPPED_TICKER"] = {
        "quantity": 25,
        "cost_basis": Decimal("2500.00"),
    }
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    # 1. No validation crash occurs
    positions = adapter.get_positions()

    # 2. Valid mapped positions are preserved
    assert len(positions) == 1
    assert positions[0].security_id == mapped_sec_id
    assert positions[0].quantity == 10

    # 3. Unmapped positions are quarantined
    assert "UNMAPPED_TICKER" in adapter.quarantined_symbols

    # 4. No fabricated security identifier is produced
    retrieved_ids = {p.security_id for p in positions}
    assert retrieved_ids == {mapped_sec_id}


# =============================================================================
# SAFE-BEHAVIOR REGRESSION TESTS
# =============================================================================


@pytest.mark.xfail(
    strict=True,
    reason="Defect S1: Router routes intents without HardRiskGatekeeper (UNFIXED)",
)
def test_s1_safe_behavior_router_must_enforce_hard_risk_limits(tmp_path: Any) -> None:
    """Safe behavior invariant: router must reject intents that exceed risk limits."""
    db_path = str(tmp_path / "order_intents.db")
    journal = PersistentOrderIntentJournal(db_path)
    adapter = MockBrokerAdapter(initial_cash=Decimal("50000.00"))
    router = BrokerNeutralExecutionRouter(adapter=adapter, journal=journal)

    intent = _make_intent(quantity=100, limit_price=Decimal("200.00"))
    report = router.route_intent(intent)
    # Safe behavior: unvetted order without risk approval must NOT be FILLED
    assert report.status != ExecutionStatus.FILLED


def test_s1_safe_behavior_orchestrator_must_reject_order_exceeding_risk_policy(
    tmp_path: Any,
) -> None:
    """Safe behavior regression: orchestrator rejects orders exceeding limits."""
    db_risk = str(tmp_path / "risk.db")
    risk_journal = PersistentRiskJournal(db_risk)
    policy = build_risk_policy(
        policy_id="audit-risk-policy-1",
        max_order_quantity=5,
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

    intent = _make_intent(quantity=10, limit_price=Decimal("100.00"))
    report, _ = orchestrator.submit_canary_intent(
        intent, reference_price=Decimal("100.00")
    )
    # Safe behavior: must reject order that exceeds gatekeeper limit of 5 shares
    assert report.status != ExecutionStatus.FILLED
    assert report.status == ExecutionStatus.REJECTED


def test_s2_safe_behavior_gatekeeper_evaluates_order_intent() -> None:
    """Safe behavior regression: Gatekeeper evaluates OrderIntentV1 cleanly."""
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

    # Safe behavior: should evaluate OrderIntentV1 without raising AttributeError
    verdict = gatekeeper.evaluate_order(
        intent,
        portfolio_state=_make_state(),
        current_price=Decimal("100.00"),
        evaluation_time=datetime.now(UTC),
    )
    assert verdict is not None
    assert verdict.status == RiskVerdictStatus.ALLOWED


def test_s3_safe_behavior_cancellation_error_fails_closed() -> None:
    """Safe behavior regression: cancellation error must NOT report CANCELED."""
    sec_id = uuid7()
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={sec_id: "AAPL"})
    failing_transport = _FailingMcpTransport(
        fail_tool="robinhood_cancel_order",
        error_message="503 Service Unavailable: broker cancel failed",
    )
    adapter = RobinhoodAgenticAdapter(config=config, transport=failing_transport)

    intent = _make_intent()
    adapter._intent_to_broker_order[intent.intent_id] = "rh-ord-9999"

    cancel_report = adapter.cancel_intent(intent.intent_id)
    # Safe behavior: must not report CANCELED when cancellation call failed
    assert cancel_report.status != ExecutionStatus.CANCELED


@pytest.mark.xfail(
    strict=True,
    reason="Defect S4: Ambiguous timeout marked as authoritative REJECTED (UNFIXED)",
)
def test_s4_safe_behavior_submission_timeout_not_marked_rejected() -> None:
    """Safe behavior invariant: timeout must NOT be marked as REJECTED."""
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
    # Safe behavior: timeout must be ambiguous/pending reconciliation, not REJECTED
    assert report.status != ExecutionStatus.REJECTED


def test_s5_safe_behavior_unmapped_symbol_quarantined_without_crash() -> None:
    """Safe behavior regression: unmapped positions quarantined without crash."""
    config = RobinhoodAgenticConfigV1(account_id="acc-01", symbol_map={})
    transport = MockRobinhoodMcpTransport()
    transport._positions["UNMAPPED_TICKER"] = {
        "quantity": 25,
        "cost_basis": Decimal("2500.00"),
    }
    adapter = RobinhoodAgenticAdapter(config=config, transport=transport)

    # Safe behavior: get_positions must succeed (quarantining) without ValidationError
    positions = adapter.get_positions()
    assert len(positions) == 0
    assert "UNMAPPED_TICKER" in adapter.quarantined_symbols
