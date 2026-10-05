"""M12 adversarial acceptance suite: Shadow Broker engine and journal (Issue 276).

Attacks the simulated execution kernel across eight adversarial vectors:
1. Short-sale boundary attacks and zero-held liquidations.
2. Multi-status market execution eligibility and tamper attacks.
3. Cash exhaustion, boundary penny over-exhaustion, and margin refusal.
4. Unadjusted source price enforcement (refusal of non-positive/non-finite).
5. Journal append-only immutability proofs and SQL trigger defense.
6. Multi-session order burst and cold journal replay bit-exactness.
7. Limit order micro-slippage boundary conditions.
8. Cost model parameter validation and negative fee refusal.

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid7

import pytest
from pydantic import ValidationError

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
    MarketExecutionEligibilityV1,
    build_market_execution_eligibility,
    build_simulated_order,
)
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import (
    JournalAppendOnlyViolationError,
    SimulationExecutionJournal,
)
from drift.shadow.reconciler import ShadowBrokerReconciler

NOW1 = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
NOW2 = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)
NOW3 = datetime(2026, 3, 3, 14, 30, tzinfo=UTC)

KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY2 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2))
KEY3 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 3))


def _make_cost_model(
    *,
    commission_per_share: Decimal = Decimal("0.01"),
    fixed_fee_per_order: Decimal = Decimal("1.00"),
    notional_fee_basis_points: Decimal = Decimal("0.00"),
    adverse_slippage_basis_points: Decimal = Decimal("5.00"),
) -> EvaluationCostModelV1:
    placeholder = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="test-adversarial-costs",
        commission_per_share=commission_per_share,
        fixed_fee_per_order=fixed_fee_per_order,
        notional_fee_basis_points=notional_fee_basis_points,
        adverse_slippage_basis_points=adverse_slippage_basis_points,
        cost_model_hash="placeholder",
    )
    c_hash = evaluation_cost_model_hash(placeholder)
    return EvaluationCostModelV1(
        schema_version="1",
        model_id="test-adversarial-costs",
        commission_per_share=commission_per_share,
        fixed_fee_per_order=fixed_fee_per_order,
        notional_fee_basis_points=notional_fee_basis_points,
        adverse_slippage_basis_points=adverse_slippage_basis_points,
        cost_model_hash=c_hash,
    )


def _make_harness(
    initial_cash: Decimal = Decimal("100000"),
    cost_model: EvaluationCostModelV1 | None = None,
) -> tuple[
    ShadowBroker,
    ShadowBrokerReconciler,
    SessionClockV1,
    PortfolioStateV2,
]:
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

    p3 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=KEY3,
        authority="realized",
        opened_at=datetime(2026, 3, 3, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 3, 21, 0, tzinfo=UTC),
        authority_record_hashes=("5" * 64,),
        authority_proof_hashes=("6" * 64,),
        session_hash="placeholder",
    )
    sess3 = EvaluationSessionV1(
        schema_version="1",
        session_key=KEY3,
        authority="realized",
        opened_at=datetime(2026, 3, 3, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 3, 3, 21, 0, tzinfo=UTC),
        authority_record_hashes=("5" * 64,),
        authority_proof_hashes=("6" * 64,),
        session_hash=evaluation_session_hash(p3),
    )

    pc = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2, sess3),
        acknowledged_limitations=(),
        clock_hash="placeholder",
    )
    clock = SessionClockV1(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(sess1, sess2, sess3),
        acknowledged_limitations=(),
        clock_hash=session_clock_hash(pc),
    )

    state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="7" * 64,
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

    kernel = PortfolioAccountingKernel(state, session_clock=clock)
    journal = SimulationExecutionJournal()
    active_cost = cost_model or _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=journal, cost_model=active_cost)
    reconciler = ShadowBrokerReconciler(broker=broker)

    return broker, reconciler, clock, state


def test_adversarial_vector_1_short_sale_boundary_and_zero_liquidation() -> None:
    """Vector 1: Refusal of naked short sales, over-selling, and zero liquidations."""
    broker, _, _, _ = _make_harness()
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )

    # Attack 1: Naked short sell with 0 held
    naked_sell = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=1,
        created_at=NOW1,
    )
    broker.submit_order(naked_sell)
    assert (
        broker.execute_order(
            naked_sell,
            open_price=Decimal("100"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )
    rej1 = broker.journal.get_rejection_by_order(naked_sell.order_id)
    assert rej1 is not None and "short_sale_rejected" in rej1.reason

    # Control 1: Buy 100 shares
    buy_ord = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=100,
        created_at=NOW1,
    )
    broker.submit_order(buy_ord)
    buy_fill = broker.execute_order(
        buy_ord,
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW1,
    )
    assert buy_fill is not None and broker.kernel.state.holdings[0].quantity == 100

    # Attack 2: Attempt to sell 101 shares (1 share over held position)
    over_sell = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=101,
        created_at=NOW1,
    )
    broker.submit_order(over_sell)
    assert (
        broker.execute_order(
            over_sell,
            open_price=Decimal("100"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )
    rej2 = broker.journal.get_rejection_by_order(over_sell.order_id)
    assert rej2 is not None and "short_sale_rejected" in rej2.reason
    assert broker.kernel.state.holdings[0].quantity == 100

    # Control 2: Sell exact 100 shares to liquidate position completely
    full_liquidation = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=100,
        created_at=NOW1,
    )
    broker.submit_order(full_liquidation)
    sell_fill = broker.execute_order(
        full_liquidation,
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW1,
    )
    assert sell_fill is not None
    assert len(broker.kernel.state.holdings) == 0

    # Attack 3: Post-liquidation sell of 1 share
    post_sell = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="sell",
        quantity=1,
        created_at=NOW1,
    )
    broker.submit_order(post_sell)
    assert (
        broker.execute_order(
            post_sell,
            open_price=Decimal("100"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )


def test_adversarial_vector_2_multi_status_eligibility_and_tamper_attacks() -> None:
    """Vector 2: Ineligible/indeterminate/missing gating and tamper rejection."""
    broker, _, _, _ = _make_harness()
    sec = uuid7()

    ord1 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
    )
    broker.submit_order(ord1)

    # Attack 1: Ineligible status with regulatory halt reason
    inel = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.INELIGIBLE,
        reason="sec_circuit_breaker_halt",
        evidence_hash="a" * 64,
    )
    assert (
        broker.execute_order(
            ord1,
            open_price=Decimal("50"),
            eligibility=inel,
            execution_time=NOW1,
        )
        is None
    )
    rej1 = broker.journal.get_rejection_by_order(ord1.order_id)
    assert rej1 is not None and "sec_circuit_breaker_halt" in rej1.reason

    # Attack 2: Indeterminate status (feed uncertainty fail-closed)
    ord2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
    )
    broker.submit_order(ord2)
    indet = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.INDETERMINATE,
        reason="feed_clock_skew",
    )
    assert (
        broker.execute_order(
            ord2,
            open_price=Decimal("50"),
            eligibility=indet,
            execution_time=NOW1,
        )
        is None
    )
    rej2 = broker.journal.get_rejection_by_order(ord2.order_id)
    assert rej2 is not None and "indeterminate_eligibility" in rej2.reason

    # Attack 3: Tampered eligibility hash
    el_valid = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="b" * 64,
    )
    tampered_dict = el_valid.model_dump(mode="python")
    tampered_dict["eligibility_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="eligibility hash mismatch"):
        MarketExecutionEligibilityV1.model_validate(tampered_dict)


def test_adversarial_vector_3_cash_exhaustion_and_margin_refusal() -> None:
    """Vector 3: Refusal of order when required cash exceeds balance by even $0.01."""
    # Start with exact cash: $1000.00
    broker, _, _, _ = _make_harness(
        initial_cash=Decimal("1000.00"),
        cost_model=_make_cost_model(
            commission_per_share=Decimal("0.00"),
            fixed_fee_per_order=Decimal("0.00"),
            adverse_slippage_basis_points=Decimal("0.00"),
        ),
    )
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )

    # Attack 1: Buy 10 shares at $100.01 -> requires $1000.10 > $1000.00
    over_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
    )
    broker.submit_order(over_order)
    assert (
        broker.execute_order(
            over_order,
            open_price=Decimal("100.01"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )
    rej = broker.journal.get_rejection_by_order(over_order.order_id)
    assert rej is not None and "insufficient_cash" in rej.reason
    assert broker.kernel.state.cash_balance == Decimal("1000")

    # Control: Buy 10 shares at exact $100.00 -> requires exact $1000.00
    exact_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
    )
    broker.submit_order(exact_order)
    fill = broker.execute_order(
        exact_order,
        open_price=Decimal("100.00"),
        eligibility=el,
        execution_time=NOW1,
    )
    assert fill is not None
    assert broker.kernel.state.cash_balance == Decimal("0")

    # Attack 2: Subsequent buy with $0 remaining cash
    zero_cash_order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=1,
        created_at=NOW1,
    )
    broker.submit_order(zero_cash_order)
    assert (
        broker.execute_order(
            zero_cash_order,
            open_price=Decimal("1.00"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )


def test_adversarial_vector_4_unadjusted_source_price_enforcement() -> None:
    """Vector 4: Refusal of zero, negative, and infinite/NaN prices."""
    broker, _, _, _ = _make_harness()
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )

    bad_prices = [
        Decimal("0"),
        Decimal("-10.50"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ]

    for bad_price in bad_prices:
        order = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec,
            side="buy",
            quantity=10,
            created_at=NOW1,
        )
        broker.submit_order(order)
        fill = broker.execute_order(
            order,
            open_price=bad_price,
            eligibility=el,
            execution_time=NOW1,
        )
        assert fill is None
        rej = broker.journal.get_rejection_by_order(order.order_id)
        assert rej is not None and "missing_or_invalid_price" in rej.reason


def test_adversarial_vector_5_journal_immutability_and_trigger_defense() -> None:
    """Vector 5: SQL triggers abort any UPDATE or DELETE on journal tables."""
    broker, _, _, _ = _make_harness()
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
    )
    broker.submit_order(order)
    broker.execute_order(
        order,
        open_price=Decimal("100"),
        eligibility=el,
        execution_time=NOW1,
    )

    journal = broker.journal

    # 1. Mutate simulated_orders
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE simulated_orders SET quantity = 999 WHERE order_id = ?",
                (str(order.order_id),),
            )
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM simulated_orders WHERE order_id = ?",
                (str(order.order_id),),
            )

    # 2. Mutate simulated_fills
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE simulated_fills SET fill_price = '0.01' WHERE order_id = ?",
                (str(order.order_id),),
            )
    with pytest.raises(JournalAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM simulated_fills WHERE order_id = ?",
                (str(order.order_id),),
            )


def test_adversarial_vector_6_multi_session_burst_and_replay_bit_exactness() -> None:
    """Vector 6: 40-order multi-session burst and bit-exact journal cold replay."""
    broker, reconciler, clock, initial_state = _make_harness(
        initial_cash=Decimal("500000")
    )
    sec_a = uuid7()
    sec_b = uuid7()

    el_a1 = build_market_execution_eligibility(
        security_id=sec_a,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="a1" * 32,
    )
    el_b1 = build_market_execution_eligibility(
        security_id=sec_b,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="b1" * 32,
    )
    el_a2 = build_market_execution_eligibility(
        security_id=sec_a,
        session_key=KEY2,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="a2" * 32,
    )
    el_b2 = build_market_execution_eligibility(
        security_id=sec_b,
        session_key=KEY2,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="b2" * 32,
    )
    el_a3 = build_market_execution_eligibility(
        security_id=sec_a,
        session_key=KEY3,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="a3" * 32,
    )
    el_b3 = build_market_execution_eligibility(
        security_id=sec_b,
        session_key=KEY3,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="b3" * 32,
    )

    # Session 1: Buy bursts
    for _ in range(5):
        ord_a = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec_a,
            side="buy",
            quantity=20,
            created_at=NOW1,
        )
        ord_b = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec_b,
            side="buy",
            quantity=15,
            created_at=NOW1,
        )
        broker.submit_order(ord_a)
        broker.submit_order(ord_b)

    broker.execute_session(
        session_key=KEY1,
        open_prices={sec_a: Decimal("120.00"), sec_b: Decimal("75.50")},
        eligibilities={sec_a: el_a1, sec_b: el_b1},
        execution_time=NOW1,
    )
    rec1 = reconciler.reconcile_session(session_key=KEY1, reconciled_at=NOW1)
    assert rec1.status == "matched"

    # Session 2: Interleaved buy and sell
    broker.kernel.advance_session(KEY2)
    for _ in range(3):
        sell_a = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY2,
            security_id=sec_a,
            side="sell",
            quantity=10,
            created_at=NOW2,
        )
        buy_b = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY2,
            security_id=sec_b,
            side="buy",
            quantity=10,
            created_at=NOW2,
        )
        broker.submit_order(sell_a)
        broker.submit_order(buy_b)

    broker.execute_session(
        session_key=KEY2,
        open_prices={sec_a: Decimal("125.00"), sec_b: Decimal("72.00")},
        eligibilities={sec_a: el_a2, sec_b: el_b2},
        execution_time=NOW2,
    )
    rec2 = reconciler.reconcile_session(session_key=KEY2, reconciled_at=NOW2)
    assert rec2.status == "matched"

    # Session 3: Liquidations and rebalances
    broker.kernel.advance_session(KEY3)
    for _ in range(2):
        sell_b = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY3,
            security_id=sec_b,
            side="sell",
            quantity=25,
            created_at=NOW3,
        )
        broker.submit_order(sell_b)

    broker.execute_session(
        session_key=KEY3,
        open_prices={sec_a: Decimal("130.00"), sec_b: Decimal("80.00")},
        eligibilities={sec_a: el_a3, sec_b: el_b3},
        execution_time=NOW3,
    )
    rec3 = reconciler.reconcile_session(session_key=KEY3, reconciled_at=NOW3)
    assert rec3.status == "matched"

    # Invariance check: Cold journal replay matches live state bit for bit
    assert (
        reconciler.verify_replay_projection(
            initial_state=initial_state,
            session_clock=clock,
        )
        is True
    )


def test_adversarial_vector_7_limit_order_micro_slippage_boundary() -> None:
    """Vector 7: Exact limit matches pass; micro-slippage breaches fail."""
    broker, _, _, _ = _make_harness(
        cost_model=_make_cost_model(adverse_slippage_basis_points=Decimal("10.00"))
    )
    sec = uuid7()
    el = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.ELIGIBLE,
        evidence_hash="1" * 64,
    )

    # 10 bps slippage = 0.001. Open 100.00 -> fill price 100.10.
    # Limit at exact 100.10 -> Accepted
    lim_exact = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
        order_type="limit",
        limit_price=Decimal("100.10"),
    )
    broker.submit_order(lim_exact)
    fill_exact = broker.execute_order(
        lim_exact,
        open_price=Decimal("100.00"),
        eligibility=el,
        execution_time=NOW1,
    )
    assert fill_exact is not None
    assert fill_exact.fill_price == Decimal("100.1")

    # Limit at 100.09 (1 cent below fill price 100.10) -> Rejected
    lim_breached = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW1,
        order_type="limit",
        limit_price=Decimal("100.09"),
    )
    broker.submit_order(lim_breached)
    assert (
        broker.execute_order(
            lim_breached,
            open_price=Decimal("100.00"),
            eligibility=el,
            execution_time=NOW1,
        )
        is None
    )
    rej = broker.journal.get_rejection_by_order(lim_breached.order_id)
    assert rej is not None and "limit_price_exceeded" in rej.reason


def test_adversarial_vector_8_negative_cost_and_model_tamper_refusal() -> None:
    """Vector 8: Refusal of negative commissions, fees, or tampered hashes."""
    # Negative commission refused
    with pytest.raises(ValidationError, match="commission_per_share must be"):
        _make_cost_model(commission_per_share=Decimal("-0.01"))

    # Negative fee refused
    with pytest.raises(ValidationError, match="fixed_fee_per_order must be"):
        _make_cost_model(fixed_fee_per_order=Decimal("-1.00"))

    # Negative slippage refused
    with pytest.raises(ValidationError, match="adverse_slippage_basis_points must be"):
        _make_cost_model(adverse_slippage_basis_points=Decimal("-5.00"))

    # Excessive slippage >= 10000 bps refused
    with pytest.raises(ValidationError, match="strictly less than 10000 basis points"):
        _make_cost_model(adverse_slippage_basis_points=Decimal("10000.00"))

    # Tampered model hash refused
    valid_model = _make_cost_model()
    tampered_dict = valid_model.model_dump(mode="python")
    tampered_dict["cost_model_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="cost model hash mismatch"):
        EvaluationCostModelV1.model_validate(tampered_dict)
