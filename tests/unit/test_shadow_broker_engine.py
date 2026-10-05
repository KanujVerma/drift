"""Unit tests for Shadow Broker engine and execution simulator (M12-3)."""

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
from drift.domain.sessions import SessionKeyV1
from drift.domain.shadow_broker import (
    EligibilityStatus,
    build_market_execution_eligibility,
    build_simulated_order,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import SimulationExecutionJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY2 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2))


def _make_cost_model(
    *,
    commission_per_share: Decimal = Decimal("0.01"),
    fixed_fee_per_order: Decimal = Decimal("1.00"),
    notional_fee_basis_points: Decimal = Decimal("0.00"),
    adverse_slippage_basis_points: Decimal = Decimal("10.00"),
) -> EvaluationCostModelV1:
    placeholder = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="test-cost-model",
        commission_per_share=commission_per_share,
        fixed_fee_per_order=fixed_fee_per_order,
        notional_fee_basis_points=notional_fee_basis_points,
        adverse_slippage_basis_points=adverse_slippage_basis_points,
        cost_model_hash="placeholder",
    )
    c_hash = evaluation_cost_model_hash(placeholder)
    return EvaluationCostModelV1(
        schema_version="1",
        model_id="test-cost-model",
        commission_per_share=commission_per_share,
        fixed_fee_per_order=fixed_fee_per_order,
        notional_fee_basis_points=notional_fee_basis_points,
        adverse_slippage_basis_points=adverse_slippage_basis_points,
        cost_model_hash=c_hash,
    )


def _make_kernel(
    initial_cash: Decimal = Decimal("100000"),
) -> PortfolioAccountingKernel:
    p1 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="placeholder",
    )
    sess1 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY1,
        authority="realized",
        opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash=evaluation_session_hash(p1),
    )

    p2 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY2,
        authority="realized",
        opened_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 2, 21, 0, tzinfo=UTC),
        authority_record_hashes=("3" * 64,),
        authority_proof_hashes=("4" * 64,),
        session_hash="placeholder",
    )
    sess2 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY2,
        authority="realized",
        opened_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 2, 21, 0, tzinfo=UTC),
        authority_record_hashes=("3" * 64,),
        authority_proof_hashes=("4" * 64,),
        session_hash=evaluation_session_hash(p2),
    )

    pc = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2),
        acknowledged_limitations=(),
        clock_hash="placeholder",
    )
    clock = SessionClockV1(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2),
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
    return PortfolioAccountingKernel(state, session_clock=clock)


def test_shadow_broker_buy_and_sell_lifecycle() -> None:
    """Verifies simulated execution, slippage, costs, and kernel reconciliation."""
    kernel = _make_kernel()
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="e" * 64,
    )

    # 1. Buy Order: 100 shares at unadjusted open 150.00
    buy_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=100,
        created_at=NOW,
    )
    broker.submit_order(buy_order)

    buy_fill = broker.execute_order(
        buy_order,
        open_price=Decimal("150.00"),
        eligibility=el,
        execution_time=NOW,
    )
    assert buy_fill is not None
    assert buy_fill.order_id == buy_order.order_id
    assert buy_fill.quantity == 100
    # Slippage: 150 * (1 + 0.001) = 150.15
    assert buy_fill.fill_price == Decimal("150.15")
    # Costs: 100 * 0.01 + 1.00 = 2.00
    assert buy_fill.transaction_costs == Decimal("2")

    # Kernel cash: 100000 - (100 * 150.15 + 2) = 100000 - 15017 = 84983
    assert kernel.state.cash_balance == Decimal("84983")
    assert len(kernel.state.holdings) == 1
    assert kernel.state.holdings[0].security_id == sec
    assert kernel.state.holdings[0].quantity == 100

    # Journal verification
    assert journal.get_order(buy_order.order_id) == buy_order
    assert journal.get_fill_by_order(buy_order.order_id) == buy_fill

    # 2. Sell Order: 40 shares at unadjusted open 160.00
    sell_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=40,
        created_at=NOW,
    )
    broker.submit_order(sell_order)

    sell_fill = broker.execute_order(
        sell_order,
        open_price=Decimal("160.00"),
        eligibility=el,
        execution_time=NOW,
    )
    assert sell_fill is not None
    assert sell_fill.quantity == 40
    # Slippage: 160 * (1 - 0.001) = 159.84
    assert sell_fill.fill_price == Decimal("159.84")
    # Costs: 40 * 0.01 + 1.00 = 1.40
    assert sell_fill.transaction_costs == Decimal("1.4")

    # Kernel cash: 84983 + (40 * 159.84 - 1.40) = 84983 + (6393.60 - 1.40) = 91375.20
    assert kernel.state.cash_balance == Decimal("91375.2")
    assert kernel.state.holdings[0].quantity == 60


def test_shadow_broker_eligibility_gating() -> None:
    """Verifies orders are rejected when security is ineligible or indeterminate."""
    kernel = _make_kernel()
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    broker.submit_order(order)

    # 1. Ineligible
    inel = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.INELIGIBLE,
        reason="halted_by_exchange",
        evidence_hash="a" * 64,
    )
    fill = broker.execute_order(
        order,
        open_price=Decimal("100"),
        eligibility=inel,
        execution_time=NOW,
    )
    assert fill is None
    rej = journal.get_rejection_by_order(order.order_id)
    assert rej is not None
    assert "ineligible_security: halted_by_exchange" in rej.reason

    # 2. Indeterminate
    order2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    broker.submit_order(order2)

    indet = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.INDETERMINATE,
        reason="feed_discontinuity",
    )
    fill2 = broker.execute_order(
        order2,
        open_price=Decimal("100"),
        eligibility=indet,
        execution_time=NOW,
    )
    assert fill2 is None
    rej2 = journal.get_rejection_by_order(order2.order_id)
    assert rej2 is not None
    assert "indeterminate_eligibility: feed_discontinuity" in rej2.reason

    # 3. Missing eligibility record
    order3 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    broker.submit_order(order3)
    fill3 = broker.execute_order(
        order3,
        open_price=Decimal("100"),
        eligibility=None,
        execution_time=NOW,
    )
    assert fill3 is None
    rej3 = journal.get_rejection_by_order(order3.order_id)
    assert rej3 is not None
    assert "missing_eligibility" in rej3.reason


def test_shadow_broker_short_sale_rejection() -> None:
    """Verifies long-only constraint forbids selling shares not currently held."""
    kernel = _make_kernel()
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="b" * 64,
    )

    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=50,
        created_at=NOW,
    )
    broker.submit_order(order)

    fill = broker.execute_order(
        order,
        open_price=Decimal("150"),
        eligibility=el,
        execution_time=NOW,
    )
    assert fill is None
    rej = journal.get_rejection_by_order(order.order_id)
    assert rej is not None
    assert "short_sale_rejected" in rej.reason


def test_shadow_broker_insufficient_cash_rejection() -> None:
    """Verifies buy order is rejected when required cash exceeds balance."""
    kernel = _make_kernel(initial_cash=Decimal("5000"))
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="c" * 64,
    )

    # Required cash: ~150 * 50 = $7500 > $5000
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW,
    )
    broker.submit_order(order)

    fill = broker.execute_order(
        order,
        open_price=Decimal("150"),
        eligibility=el,
        execution_time=NOW,
    )
    assert fill is None
    rej = journal.get_rejection_by_order(order.order_id)
    assert rej is not None
    assert "insufficient_cash" in rej.reason


def test_shadow_broker_limit_order_feasibility() -> None:
    """Verifies limit orders reject when slipped open price breaches limit."""
    kernel = _make_kernel()
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model(adverse_slippage_basis_points=Decimal("50.00"))
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="d" * 64,
    )

    # 1. Buy limit order: limit 100.00, open 100.00, slippage 50 bps -> fill 100.50
    buy_lim = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
        order_type="limit",
        limit_price=Decimal("100.00"),
    )
    broker.submit_order(buy_lim)

    fill_buy = broker.execute_order(
        buy_lim,
        open_price=Decimal("100.00"),
        eligibility=el,
        execution_time=NOW,
    )
    assert fill_buy is None
    rej_buy = journal.get_rejection_by_order(buy_lim.order_id)
    assert rej_buy is not None
    assert "limit_price_exceeded" in rej_buy.reason

    # 2. Sell limit order: buy shares first
    buy_mkt = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=20,
        created_at=NOW,
    )
    broker.submit_order(buy_mkt)
    broker.execute_order(
        buy_mkt,
        open_price=Decimal("100.00"),
        eligibility=el,
        execution_time=NOW,
    )

    # Sell limit order: limit 110.00, open 110.00, slippage 50 bps -> fill 109.45
    sell_lim = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=10,
        created_at=NOW,
        order_type="limit",
        limit_price=Decimal("110.00"),
    )
    broker.submit_order(sell_lim)

    fill_sell = broker.execute_order(
        sell_lim,
        open_price=Decimal("110.00"),
        eligibility=el,
        execution_time=NOW,
    )
    assert fill_sell is None
    rej_sell = journal.get_rejection_by_order(sell_lim.order_id)
    assert rej_sell is not None
    assert "limit_price_not_met" in rej_sell.reason


def test_shadow_broker_batch_session_execution() -> None:
    """Verifies batch execution executes only matching session orders."""
    kernel = _make_kernel()
    journal = SimulationExecutionJournal()
    cost_model = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=cost_model)

    sec = uuid7()
    el1 = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    el2 = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY2,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="2" * 64,
    )

    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY2,
        security_id=sec,
        side="buy",
        quantity=20,
        created_at=NOW,
    )
    broker.submit_order(ord1)
    broker.submit_order(ord2)

    # Execute session 1
    fills1 = broker.execute_session(
        session_key=KEY1,
        open_prices={sec: Decimal("100")},
        eligibilities={sec: el1},
        execution_time=NOW,
    )
    assert len(fills1) == 1
    assert fills1[0].order_id == ord1.order_id
    assert len(broker._order_queue) == 1
    assert broker._order_queue[0].order_id == ord2.order_id

    # Execute session 2
    kernel.advance_session(KEY2)
    fills2 = broker.execute_session(
        session_key=KEY2,
        open_prices={sec: Decimal("105")},
        eligibilities={sec: el2},
        execution_time=NOW,
    )
    assert len(fills2) == 1
    assert fills2[0].order_id == ord2.order_id
    assert len(broker._order_queue) == 0
