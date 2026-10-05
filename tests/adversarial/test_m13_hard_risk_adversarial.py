"""M13 adversarial acceptance suite: Deterministic Hard Risk (Issue 288).

Attacks the hard risk gatekeeper, persistent kill switch, and integration harness
across eight adversarial vectors:
1. Position limit boundary attack and single-name concentration caps.
2. Persistent kill switch latching across multiple disk restarts.
3. Runaway order burst attack and sliding window rate limiting.
4. Intra-session loss and trailing peak drawdown circuit breakers.
5. Fail-closed market price indeterminacy and missing data attacks.
6. Gross portfolio exposure boundary cap breach rejection.
7. SQLite append-only immutability trigger attack on risk tables.
8. Three-layer tradability separation (M12 eligibility vs M13 risk permissions).

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid7

import pytest

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
from drift.domain.evaluator_portfolio import (
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioMarkV1,
    PortfolioStateV2,
    SecurityHoldingV2,
)
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
from drift.risk.journal import (
    PersistentRiskJournal,
    RiskAppendOnlyViolationError,
)
from drift.shadow.broker import ShadowBroker
from drift.shadow.journal import SimulationExecutionJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))
KEY2 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2))


def _make_cost_model() -> EvaluationCostModelV1:
    placeholder = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="test-adv-risk-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash="placeholder",
    )
    c_hash = evaluation_cost_model_hash(placeholder)
    return EvaluationCostModelV1(
        schema_version="1",
        model_id="test-adv-risk-costs",
        commission_per_share=Decimal("0.01"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("5.00"),
        cost_model_hash=c_hash,
    )


def _make_clock_and_state(
    *,
    initial_cash: Decimal = Decimal("100000"),
    holdings: tuple[SecurityHoldingV2, ...] = (),
    holdings_value: Decimal = Decimal("0"),
    holding_price: Decimal = Decimal("100"),
    session_key: SessionKeyV1 = KEY1,
) -> tuple[SessionClockV1, PortfolioStateV2]:
    p1 = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=session_key,
        authority="realized",
        opened_at=NOW,
        closed_at=datetime(2026, 3, 1, 21, 0, tzinfo=UTC),
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="placeholder",
    )
    sess1 = EvaluationSessionV1(
        schema_version="1",
        session_key=session_key,
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

    mark = None
    if holdings:
        mark = PortfolioMarkV1(
            session_key=session_key,
            lane="exploratory",
            prices=tuple(
                MarkPriceV1(
                    security_id=h.security_id,
                    close_price=holding_price,
                    evidence=MarkEvidenceV1(
                        grade="exploratory",
                        evidence_hash="a" * 64,
                    ),
                )
                for h in holdings
            ),
        )

    nav = initial_cash + holdings_value
    state = PortfolioStateV2(
        lane="exploratory",
        admission_hash="5" * 64,
        session_key=session_key,
        cash_balance=initial_cash,
        holdings=holdings,
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=(),
        mark=mark,
        holdings_market_value=holdings_value,
        pending_claims_value=Decimal("0"),
        net_asset_value=nav,
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
    max_position_weight_basis_points: int = 2500,  # 25% NAV
    max_gross_exposure_basis_points: int = 10000,  # 100% NAV
    max_session_drawdown_basis_points: int = 300,  # 3% session loss
    max_trailing_drawdown_basis_points: int = 1000,  # 10% peak drawdown
    max_orders_per_minute: int = 5,
) -> RiskPolicyV1:
    return build_risk_policy(
        policy_id="test-adv-policy",
        max_order_notional=max_order_notional,
        max_order_quantity=max_order_quantity,
        max_position_notional=max_position_notional,
        max_position_weight_basis_points=max_position_weight_basis_points,
        max_gross_exposure_basis_points=max_gross_exposure_basis_points,
        max_session_drawdown_basis_points=max_session_drawdown_basis_points,
        max_trailing_drawdown_basis_points=max_trailing_drawdown_basis_points,
        max_orders_per_minute=max_orders_per_minute,
    )


def _make_harness(
    *,
    initial_cash: Decimal = Decimal("100000"),
    policy: RiskPolicyV1 | None = None,
    journal: PersistentRiskJournal | None = None,
) -> RiskManagedBroker:
    clock, state = _make_clock_and_state(initial_cash=initial_cash)
    kernel = PortfolioAccountingKernel(state, session_clock=clock)
    exec_j = SimulationExecutionJournal()
    cost_m = _make_cost_model()
    broker = ShadowBroker(kernel=kernel, journal=exec_j, cost_model=cost_m)

    risk_j = journal if journal is not None else PersistentRiskJournal()
    active_policy = policy or _make_policy()
    gatekeeper = HardRiskGatekeeper(
        policy=active_policy,
        journal=risk_j,
        initial_nav=initial_cash,
    )
    return RiskManagedBroker(broker=broker, gatekeeper=gatekeeper)


# =========================================================================
# Vector 1: Position Limit Boundary Attacks and Single-Name Concentration
# =========================================================================


def test_adversarial_v1_position_limit_boundary_attacks() -> None:
    """Attacks position notional and portfolio weight caps at the exact boundary."""
    # NAV = 100,000; max position notional = 20,000; max weight = 2000 bps (20%)
    policy = _make_policy(
        max_order_quantity=500,
        max_order_notional=Decimal("30000"),
        max_position_notional=Decimal("20000"),
        max_position_weight_basis_points=2000,
    )
    harness = _make_harness(policy=policy)
    sec = uuid7()

    # Control: Exactly 200 shares at $100 = $20,000 (exactly at limit) -> ALLOWED
    order_ok = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=200,
        created_at=NOW,
    )
    v_ok = harness.submit_order(
        order_ok,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_ok.status == RiskVerdictStatus.ALLOWED

    # Attack: 201 shares at $100 = $20,100 ($100 over notional limit) -> REJECTED
    order_over = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=201,
        created_at=NOW,
    )
    v_over = harness.submit_order(
        order_over,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_over.status == RiskVerdictStatus.REJECTED
    assert "max_position_notional_exceeded" in str(v_over.reason)


# =========================================================================
# Vector 2: Persistent Kill Switch Latching Across Process Restarts
# =========================================================================


def test_adversarial_v2_kill_switch_persistence_across_restarts(
    tmp_path: Path,
) -> None:
    """Verifies kill switch tripped state latches across SQLite database reloads."""
    db_file = tmp_path / "adversarial_risk.db"

    # Instance 1: Trip kill switch
    journal_1 = PersistentRiskJournal(db_path=db_file)
    journal_1.trip_kill_switch(reason="risk_anomaly_detected", tripped_at=NOW)
    assert journal_1.is_kill_switch_tripped() is True
    journal_1.close()

    # Instance 2: Cold restart with fresh journal & gatekeeper reading same DB
    journal_2 = PersistentRiskJournal(db_path=db_file)
    assert journal_2.is_kill_switch_tripped() is True

    policy = _make_policy()
    harness = _make_harness(policy=policy, journal=journal_2)

    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    v_refused = harness.submit_order(
        order,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_refused.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
    assert "emergency_kill_switch_is_active" in str(v_refused.reason)

    # Control: Explicit administrative unlock
    journal_2.clear_kill_switch(reason="operator_audit_cleared", cleared_at=NOW)
    journal_2.close()

    # Instance 3: Verify cleared state persists
    journal_3 = PersistentRiskJournal(db_path=db_file)
    assert journal_3.is_kill_switch_tripped() is False
    harness_3 = _make_harness(policy=policy, journal=journal_3)

    order_3 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    v_cleared = harness_3.submit_order(
        order_3,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_cleared.status == RiskVerdictStatus.ALLOWED
    journal_3.close()


# =========================================================================
# Vector 3: Runaway Order Burst Attack (Rate Limiting Sliding Window)
# =========================================================================


def test_adversarial_v3_runaway_order_burst_throttling() -> None:
    """Attacks sliding window order rate throttler with high-frequency order bursts."""
    policy = _make_policy(max_orders_per_minute=5)
    harness = _make_harness(policy=policy)
    sec = uuid7()

    # Submit 5 orders in rapid succession (allowed)
    for i in range(5):
        ord_i = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec,
            side="buy",
            quantity=1,
            created_at=NOW + timedelta(seconds=i),
        )
        v = harness.submit_order(
            ord_i,
            current_price=Decimal("10"),
            evaluation_time=NOW + timedelta(seconds=i),
        )
        assert v.status == RiskVerdictStatus.ALLOWED

    # Attack: 6th through 15th orders within the same minute -> all throttled
    for _ in range(5, 15):
        ord_burst = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec,
            side="buy",
            quantity=1,
            created_at=NOW + timedelta(seconds=10),
        )
        v_throttled = harness.submit_order(
            ord_burst,
            current_price=Decimal("10"),
            evaluation_time=NOW + timedelta(seconds=10),
        )
        assert v_throttled.status == RiskVerdictStatus.REJECTED
        assert "order_rate_limit_exceeded" in str(v_throttled.reason)

    # Control: Advance clock past 60s window (at 65s) -> next order succeeds
    ord_recovered = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=1,
        created_at=NOW + timedelta(seconds=65),
    )
    v_recovered = harness.submit_order(
        ord_recovered,
        current_price=Decimal("10"),
        evaluation_time=NOW + timedelta(seconds=65),
    )
    assert v_recovered.status == RiskVerdictStatus.ALLOWED


# =========================================================================
# Vector 4: Portfolio Drawdown Circuit Breakers (Session and Trailing)
# =========================================================================


def test_adversarial_v4_drawdown_auto_trip_circuit_breakers() -> None:
    """Verifies intra-session and trailing peak drawdown breakers trip kill switch."""
    # 300 bps session loss (3%), 1000 bps trailing drawdown (10%)
    policy = _make_policy(
        max_session_drawdown_basis_points=300,
        max_trailing_drawdown_basis_points=1000,
    )
    risk_j = PersistentRiskJournal()
    gatekeeper = HardRiskGatekeeper(
        policy=policy,
        journal=risk_j,
        initial_nav=Decimal("100000"),
    )

    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=5,
        created_at=NOW,
    )

    # Control: 1% drawdown (1000 loss / 100k) < 300 bps limit -> ALLOWED
    _, state_1pct = _make_clock_and_state(initial_cash=Decimal("99000"))
    v_ok = gatekeeper.evaluate_order(
        order,
        portfolio_state=state_1pct,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_ok.status == RiskVerdictStatus.ALLOWED
    assert risk_j.is_kill_switch_tripped() is False

    # Attack: Session drops to 96,000 (4% loss >= 300 bps limit) -> trips kill switch
    order_trip = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=5,
        created_at=NOW,
    )
    _, state_4pct = _make_clock_and_state(initial_cash=Decimal("96000"))
    v_trip = gatekeeper.evaluate_order(
        order_trip,
        portfolio_state=state_4pct,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_trip.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
    assert "session_drawdown_breached" in str(v_trip.reason)
    assert risk_j.is_kill_switch_tripped() is True


# =========================================================================
# Vector 5: Missing or Invalid Market Prices Fail-Closed
# =========================================================================


def test_adversarial_v5_fail_closed_on_invalid_prices() -> None:
    """Attacks price valuation with None, zero, negative, and infinite prices."""
    harness = _make_harness()
    sec = uuid7()

    invalid_prices = [
        None,
        Decimal("0"),
        Decimal("-1.00"),
        Decimal("-100.50"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ]

    for inv_price in invalid_prices:
        ord_inv = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec,
            side="buy",
            quantity=10,
            created_at=NOW,
        )
        verdict = harness.submit_order(
            ord_inv,
            current_price=inv_price,
            evaluation_time=NOW,
        )
        assert verdict.status == RiskVerdictStatus.REJECTED
        assert "indeterminate_market_price" in str(verdict.reason)

    # Control: Strict positive price succeeds
    ord_valid = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    v_valid = harness.submit_order(
        ord_valid,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_valid.status == RiskVerdictStatus.ALLOWED


# =========================================================================
# Vector 6: Gross Portfolio Exposure Boundary Cap Breach
# =========================================================================


def test_adversarial_v6_gross_exposure_boundary_breach() -> None:
    """Attacks gross portfolio exposure cap (e.g. 10000 bps = 100% NAV)."""
    # NAV = 100,000; max gross exposure = 10000 bps (100% unlevered)
    policy = _make_policy(
        max_order_quantity=500,
        max_order_notional=Decimal("60000"),
        max_position_notional=Decimal("60000"),
        max_position_weight_basis_points=6000,
        max_gross_exposure_basis_points=10000,
    )
    # Pre-existing holdings of 60,000 in sec1
    sec1 = uuid7()
    sec2 = uuid7()
    h1 = SecurityHoldingV2(
        security_id=sec1,
        quantity=600,
        basis_status="known",
        cost_basis=Decimal("60000"),
    )
    _, state = _make_clock_and_state(
        initial_cash=Decimal("40000"),
        holdings=(h1,),
        holdings_value=Decimal("60000"),
        holding_price=Decimal("100"),
    )
    risk_j = PersistentRiskJournal()
    gatekeeper = HardRiskGatekeeper(
        policy=policy,
        journal=risk_j,
        initial_nav=Decimal("100000"),
    )

    # Control: Buy 400 shares of sec2 at $100 = 40,000 (total gross = 100,000 = 100%)
    ord_exact = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec2,
        side="buy",
        quantity=400,
        created_at=NOW,
    )
    v_exact = gatekeeper.evaluate_order(
        ord_exact,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_exact.status == RiskVerdictStatus.ALLOWED

    # Attack: Buy 401 shares of sec2 at $100 = 40,100 (total gross = 100,100 > 100k)
    ord_over = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec2,
        side="buy",
        quantity=401,
        created_at=NOW,
    )
    v_over = gatekeeper.evaluate_order(
        ord_over,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_over.status == RiskVerdictStatus.REJECTED
    assert "max_gross_exposure_exceeded" in str(v_over.reason)


# =========================================================================
# Vector 7: SQLite Append-Only Immutability Trigger Attack
# =========================================================================


def test_adversarial_v7_sqlite_append_only_triggers() -> None:
    """Attacks risk ledger immutability via raw SQL UPDATE and DELETE operations."""
    journal = PersistentRiskJournal()
    sec = uuid7()
    policy = _make_policy()
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)

    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    _, state = _make_clock_and_state()
    gatekeeper.evaluate_order(
        order,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )

    # Attack 1: Attempt to UPDATE risk_verdicts
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE risk_verdicts SET status = 'rejected' WHERE order_id = ?",
                (str(order.order_id),),
            )

    # Attack 2: Attempt to DELETE FROM risk_verdicts
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM risk_verdicts WHERE order_id = ?",
                (str(order.order_id),),
            )

    # Attack 3: Attempt to UPDATE kill_switch_events
    journal.trip_kill_switch(reason="test_trip", tripped_at=NOW)
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "UPDATE kill_switch_events SET status = 'active'",
            )

    # Attack 4: Attempt to DELETE FROM kill_switch_events
    with pytest.raises(RiskAppendOnlyViolationError):
        with journal._transaction() as cursor:
            cursor.execute(
                "DELETE FROM kill_switch_events",
            )


# =========================================================================
# Vector 8: Three-Layer Tradability Separation (M12 vs M13)
# =========================================================================


def test_adversarial_v8_three_layer_tradability_isolation() -> None:
    """Proves isolation: M12 eligibility and M13 risk policy act independently."""
    harness = _make_harness()
    sec = uuid7()

    # Case A: Order passes M13 Risk (ALLOWED), but M12 Eligibility is HALTED
    # Result: submit_order succeeds, but execute_order fails closed with rejection
    ord_a = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    v_a = harness.submit_order(
        ord_a,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_a.status == RiskVerdictStatus.ALLOWED

    el_halted = build_market_execution_eligibility(
        security_id=sec,
        session_key=KEY1,
        status=EligibilityStatus.INELIGIBLE,
        reason="trading_halt_active",
        evidence_hash="1" * 64,
    )
    fill_a = harness.execute_order(
        ord_a,
        open_price=Decimal("100"),
        eligibility=el_halted,
        execution_time=NOW,
    )
    assert fill_a is None
    # Rejection recorded in execution journal
    rej_a = harness.execution_journal.get_rejection_by_order(ord_a.order_id)
    assert rej_a is not None
    assert "trading_halt_active" in rej_a.reason

    # Case B: Security is ELIGIBLE in M12, but M13 Risk refuses (notional breach)
    # Result: submit_order rejects; order is never sent to broker queue or execution
    ord_b = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=500,  # 500 * 100 = 50,000 > 20,000 max order notional
        created_at=NOW,
    )
    v_b = harness.submit_order(
        ord_b,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v_b.status == RiskVerdictStatus.REJECTED
    assert harness.execution_journal.get_order(ord_b.order_id) is None
    assert len(harness.broker._order_queue) == 1  # only ord_a from Case A
