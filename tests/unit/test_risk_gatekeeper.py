"""Unit tests for HardRiskGatekeeper engine (M13-3)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid7

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
from drift.domain.shadow_broker import build_simulated_order
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)
KEY1 = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 3, 1))


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
        policy_id="test-gatekeeper-policy",
        max_order_notional=max_order_notional,
        max_order_quantity=max_order_quantity,
        max_position_notional=max_position_notional,
        max_position_weight_basis_points=max_position_weight_basis_points,
        max_gross_exposure_basis_points=max_gross_exposure_basis_points,
        max_session_drawdown_basis_points=max_session_drawdown_basis_points,
        max_trailing_drawdown_basis_points=max_trailing_drawdown_basis_points,
        max_orders_per_minute=max_orders_per_minute,
    )


def _make_state(
    *,
    cash: Decimal = Decimal("100000"),
    holdings: tuple[SecurityHoldingV2, ...] = (),
    holdings_value: Decimal = Decimal("0"),
    holding_price: Decimal = Decimal("100"),
) -> PortfolioStateV2:
    nav = cash + holdings_value
    mark = None
    if holdings:
        mark = PortfolioMarkV1(
            session_key=KEY1,
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
    return PortfolioStateV2(
        lane="exploratory",
        admission_hash="a" * 64,
        session_key=KEY1,
        cash_balance=cash,
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


def test_gatekeeper_allowed_order() -> None:
    """Verifies that an order conforming to all limits receives ALLOWED verdict."""
    journal = PersistentRiskJournal()
    policy = _make_policy()
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)

    sec = uuid7()
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=50,
        created_at=NOW,
    )
    state = _make_state()

    verdict = gatekeeper.evaluate_order(
        order,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.ALLOWED
    assert verdict.reason is None

    # Check journal logged verdict
    logged = journal.get_verdict_for_order(order.order_id)
    assert logged == verdict


def test_gatekeeper_kill_switch_active() -> None:
    """Verifies orders are refused when kill switch is tripped."""
    journal = PersistentRiskJournal()
    journal.trip_kill_switch(reason="manual_operator_halt", tripped_at=NOW)
    policy = _make_policy()
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)

    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    state = _make_state()

    verdict = gatekeeper.evaluate_order(
        order,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert verdict.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
    assert "emergency_kill_switch_is_active" in str(verdict.reason)


def test_gatekeeper_fail_closed_on_invalid_price() -> None:
    """Verifies fail-closed rejection when price is None, negative, or zero."""
    journal = PersistentRiskJournal()
    policy = _make_policy()
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)

    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    state = _make_state()

    # None price
    v1 = gatekeeper.evaluate_order(
        order,
        portfolio_state=state,
        current_price=None,
        evaluation_time=NOW,
    )
    assert v1.status == RiskVerdictStatus.REJECTED
    assert "indeterminate_market_price" in str(v1.reason)

    # Zero price
    order2 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=10,
        created_at=NOW,
    )
    v2 = gatekeeper.evaluate_order(
        order2,
        portfolio_state=state,
        current_price=Decimal("0.00"),
        evaluation_time=NOW,
    )
    assert v2.status == RiskVerdictStatus.REJECTED


def test_gatekeeper_order_quantity_and_notional_limits() -> None:
    """Verifies rejection when order quantity or notional exceeds limits."""
    journal = PersistentRiskJournal()
    # Max order qty = 200, max order notional = 20000
    policy = _make_policy(
        max_order_quantity=200,
        max_order_notional=Decimal("20000"),
    )
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)
    state = _make_state()

    # 1. Exceed order quantity: 201 shares
    ord_qty = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=201,
        created_at=NOW,
    )
    v_qty = gatekeeper.evaluate_order(
        ord_qty,
        portfolio_state=state,
        current_price=Decimal("10"),
        evaluation_time=NOW,
    )
    assert v_qty.status == RiskVerdictStatus.REJECTED
    assert "max_order_quantity_exceeded" in str(v_qty.reason)

    # 2. Exceed order notional: 150 shares * 200 = 30000 > 20000
    ord_notional = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=uuid7(),
        side="buy",
        quantity=150,
        created_at=NOW,
    )
    v_notional = gatekeeper.evaluate_order(
        ord_notional,
        portfolio_state=state,
        current_price=Decimal("200"),
        evaluation_time=NOW,
    )
    assert v_notional.status == RiskVerdictStatus.REJECTED
    assert "max_order_notional_exceeded" in str(v_notional.reason)


def test_gatekeeper_position_notional_and_weight_caps() -> None:
    """Verifies single-name position concentration and portfolio weight caps."""
    journal = PersistentRiskJournal()
    sec = uuid7()
    # Max position notional = 25000, max weight = 20% (2000 bps) of 100k NAV
    policy = _make_policy(
        max_order_notional=Decimal("50000"),
        max_position_notional=Decimal("25000"),
        max_position_weight_basis_points=2000,
    )
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)

    # Pre-existing holding: 100 shares at 100 = 10000
    holding = SecurityHoldingV2(
        security_id=sec,
        quantity=100,
        basis_status="known",
        cost_basis=Decimal("10000"),
    )
    state = _make_state(
        cash=Decimal("90000"),
        holdings=(holding,),
        holdings_value=Decimal("10000"),
    )

    # Attempt to buy 160 more shares at 100:
    # projected notional = 260 * 100 = 26000 > 25000 limit
    order = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=160,
        created_at=NOW,
    )
    v = gatekeeper.evaluate_order(
        order,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v.status == RiskVerdictStatus.REJECTED
    assert "max_position_notional_exceeded" in str(v.reason)


def test_gatekeeper_session_and_trailing_drawdown_auto_trip() -> None:
    """Verifies drawdown breaches automatically trip persistent kill switch."""
    journal = PersistentRiskJournal()
    # 300 bps session loss limit (3%), 1000 bps trailing drawdown limit (10%)
    policy = _make_policy(
        max_session_drawdown_basis_points=300,
        max_trailing_drawdown_basis_points=1000,
    )
    gatekeeper = HardRiskGatekeeper(
        policy=policy,
        journal=journal,
        initial_nav=Decimal("100000"),
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

    # 1. Session drawdown: NAV drops from 100,000 to 96,500 (3.5% loss >= 3% limit)
    down_state = _make_state(cash=Decimal("96500"))
    v = gatekeeper.evaluate_order(
        order,
        portfolio_state=down_state,
        current_price=Decimal("100"),
        evaluation_time=NOW,
    )
    assert v.status == RiskVerdictStatus.KILL_SWITCH_ACTIVE
    assert "session_drawdown_breached" in str(v.reason)

    # Check journal has flipped to TRIPPED
    assert journal.is_kill_switch_tripped() is True


def test_gatekeeper_rate_limiting() -> None:
    """Verifies that exceeding max_orders_per_minute within 60s is throttled."""
    journal = PersistentRiskJournal()
    policy = _make_policy(max_orders_per_minute=3)
    gatekeeper = HardRiskGatekeeper(policy=policy, journal=journal)
    state = _make_state()
    sec = uuid7()

    # Submit 3 orders at NOW
    for i in range(3):
        ord_i = build_simulated_order(
            order_id=uuid7(),
            session_key=KEY1,
            security_id=sec,
            side="buy",
            quantity=5,
            created_at=NOW + timedelta(seconds=i),
        )
        v = gatekeeper.evaluate_order(
            ord_i,
            portfolio_state=state,
            current_price=Decimal("100"),
            evaluation_time=NOW + timedelta(seconds=i),
        )
        assert v.status == RiskVerdictStatus.ALLOWED

    # 4th order within 60s -> rate limit exceeded
    ord_4 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=5,
        created_at=NOW + timedelta(seconds=10),
    )
    v_4 = gatekeeper.evaluate_order(
        ord_4,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW + timedelta(seconds=10),
    )
    assert v_4.status == RiskVerdictStatus.REJECTED
    assert "order_rate_limit_exceeded" in str(v_4.reason)

    # 5th order after 65 seconds -> allowed again
    ord_5 = build_simulated_order(
        order_id=uuid7(),
        session_key=KEY1,
        security_id=sec,
        side="buy",
        quantity=5,
        created_at=NOW + timedelta(seconds=65),
    )
    v_5 = gatekeeper.evaluate_order(
        ord_5,
        portfolio_state=state,
        current_price=Decimal("100"),
        evaluation_time=NOW + timedelta(seconds=65),
    )
    assert v_5.status == RiskVerdictStatus.ALLOWED
