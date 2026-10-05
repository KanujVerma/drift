"""Unit tests for RiskManagedBroker harness (M13-4)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.risk import (
    RiskPolicyV1,
    RiskVerdictStatus,
    build_risk_policy,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    EligibilityStatus,
    build_market_execution_eligibility,
    build_simulated_order,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.harness import RiskManagedBroker
from drift.risk.journal import PersistentRiskJournal
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import SimulationExecutionJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


def _make_cost_model() -> EvaluationCostModelV1:
    placeholder = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="test-harness-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash="placeholder",
    )
    c_hash = evaluation_cost_model_hash(placeholder)
    return EvaluationCostModelV1(
        schema_version="1",
        model_id="test-harness-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash=c_hash,
    )


def _make_clock_and_state(
    initial_cash: Decimal = Decimal("100000"),
) -> tuple[SessionClockV1, PortfolioStateV2]:
    p1 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=NOW,
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="placeholder",
    )
    sess1 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=NOW,
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash=evaluation_session_hash(p1),
    )

    pc = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1,),
        acknowledged_limitations=(),
        clock_hash="placeholder",
    )
    clock = SessionClockV1(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1,),
        acknowledged_limitations=(),
        clock_hash=session_clock_hash(pc),
    )

    state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="5" * 64,
        session_key=KEY1,
        cash_balance=initial_cash,
        holdings=(),
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=None,
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=initial_cash,
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )
    return clock, state


def _make_policy(
    *,
    max_order_notional: Decimal = Decimal("20000"),
    max_order_quantity: int = 200,
    max_position_notional: Decimal = Decimal("50000"),
    max_position_weight_basis_points: int = 2500,
    max_gross_exposure_basis_points: int = 10000,
    max_session_drawdown_basis_points: int = 300,
    max_trailing_drawdown_basis_points: int = 1000,
    max_orders_per_minute: int = 10,
) -> RiskPolicyV1:
    return build_risk_policy(
        policy_id="test-harness-policy",
        max_order_notional=max_order_notional,
        max_order_quantity=max_order_quantity,
        max_position_notional=max_position_notional,
        max_position_weight_basis_points=max_position_weight_basis_points,
        max_gross_exposure_basis_points=max_gross_exposure_basis_points,
        max_session_drawdown_basis_points=max_session_drawdown_basis_points,
        max_trailing_drawdown_basis_points=max_trailing_drawdown_basis_points,
        max_orders_per_minute=max_orders_per_minute,
    )


def _build_harness(
    *,
    initial_cash: Decimal = Decimal("100000"),
    policy: RiskPolicyV1 | None = None,
) -> RiskManagedBroker:
    clock, initial_state = _make_clock_and_state(initial_cash=initial_cash)
    kernel = PortfolioAccountingKernel(initial_state, session_clock=clock)
    exec_journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=exec_journal, cost_model=cost_model)

    risk_journal = PersistentRiskJournal()
    active_policy = policy or _make_policy()
    gatekeeper = HardRiskGatekeeper(
        policy=active_policy,
        journal=risk_journal,
        initial_nav=initial_cash,
    )
    return RiskManagedBroker(broker=broker, gatekeeper=gatekeeper)


def test_harness_allowed_order_submits_and_executes() -> None:
    """Verifies that allowed orders pass risk gate and execute cleanly."""
    harness = _build_harness()
    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW,
    )

    verdict = harness.submit_order(
        order,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.ALLOWED

    # Verify journal logging
    risk_logged = harness.risk_journal.get_verdict_for_order(order.order_id)
    assert risk_logged == verdict
    broker_order = harness.execution_journal.get_order(order.order_id)
    assert broker_order == order
    broker_orders = harness.execution_journal.list_orders_for_session(KEY1)
    assert len(broker_orders) == 1
    assert broker_orders[0].order_id == order.order_id

    # Execute order
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    fill = harness.execute_order(
        order,
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW,
    )
    assert fill is not None
    assert fill.quantity == 50
    assert len(harness.kernel.state.holdings) == 1
    assert harness.kernel.state.holdings[0].quantity == 50


def test_harness_rejected_order_not_queued_to_broker() -> None:
    """Verifies risk-rejected orders are dropped fail-closed without broker queueing."""
    harness = _build_harness()
    sec = uuid7()
    # Quantity 300 exceeds max_order_quantity 200
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=300,
        created_at=NOW,
    )

    verdict = harness.submit_order(
        order,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.REJECTED
    assert "max_order_quantity_exceeded" in str(verdict.reason)

    # Broker journal and queue must be completely untouched
    assert harness.execution_journal.get_order(order.order_id) is None
    assert len(harness.execution_journal.list_orders_for_session(KEY1)) == 0
    assert len(harness.broker._order_queue) == 0

    # Risk journal recorded the rejection
    risk_logged = harness.risk_journal.get_verdict_for_order(order.order_id)
    assert risk_logged == verdict


def test_harness_missing_price_fails_closed() -> None:
    """Verifies missing market price causes fail-closed risk rejection."""
    harness = _build_harness()
    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )

    verdict = harness.submit_order(
        order,
        current_price=None,
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.REJECTED
    assert "indeterminate_market_price" in str(verdict.reason)
    assert len(harness.broker._order_queue) == 0


def test_harness_kill_switch_tripped_refuses_order() -> None:
    """Verifies active kill switch blocks order routing to shadow broker."""
    harness = _build_harness()
    harness.risk_journal.trip_kill_switch(
        reason="operator_emergency_halt",
        tripped_at=NOW,
    )

    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )

    verdict = harness.submit_order(
        order,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
    assert len(harness.broker._order_queue) == 0


def test_harness_submit_and_execute_helper() -> None:
    """Verifies single-step submit_and_execute convenience method."""
    harness = _build_harness()
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )

    # 1. Valid order -> (ALLOWED, fill)
    valid_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=20,
        created_at=NOW,
    )
    v_ok, fill_ok = harness.submit_and_execute(
        valid_order,
        current_price=Decimal("100"),
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW,
    )
    assert v_ok.status == RiskVerdictStatus.ALLOWED
    assert fill_ok is not None
    assert fill_ok.quantity == 20

    # 2. Invalid order (oversized) -> (REJECTED, None)
    bad_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=500,
        created_at=NOW,
    )
    v_bad, fill_bad = harness.submit_and_execute(
        bad_order,
        current_price=Decimal("100"),
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW,
    )
    assert v_bad.status == RiskVerdictStatus.REJECTED
    assert fill_bad is None


def test_harness_execute_session_batch() -> None:
    """Verifies batch execution of queued orders across a session."""
    harness = _build_harness()
    sec1 = uuid7()
    sec2 = uuid7()

    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec1,
        side="buy",
        quantity=15,
        created_at=NOW,
    )
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec2,
        side="buy",
        quantity=25,
        created_at=NOW,
    )

    assert (
        harness.submit_order(
            ord1,
            current_price=Decimal("100"),
            evaluation_time=NOW,
        ).status
        == RiskVerdictStatus.ALLOWED
    )
    assert (
        harness.submit_order(
            ord2,
            current_price=Decimal("50"),
            evaluation_time=NOW,
        ).status
        == RiskVerdictStatus.ALLOWED
    )

    el1 = build_market_execution_eligibility(
        security_id=sec1,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    el2 = build_market_execution_eligibility(
        security_id=sec2,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="2" * 64,
    )

    fills = harness.execute_session(
        session_key=KEY1,
        open_prices={sec1: Decimal("100"), sec2: Decimal("50")},
        eligibilities={sec1: el1, sec2: el2},
        execution_time=NOW,
    )
    assert len(fills) == 2
    assert len(harness.kernel.state.holdings) == 2
    assert len(harness.broker._order_queue) == 0
