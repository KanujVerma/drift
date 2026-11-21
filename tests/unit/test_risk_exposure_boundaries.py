"""Hard exposure caps include fractional basis points at their boundaries."""

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, localcontext
from fractions import Fraction
from uuid import uuid7

import pytest
from test_execution_safety_risk import _make_intent
from test_risk_gatekeeper import _make_policy, _make_state

from drift.domain.evaluator_portfolio import SecurityHoldingV2, decimal_context
from drift.domain.risk import RiskVerdictStatus
from drift.risk.gatekeeper import HardRiskGatekeeper
from drift.risk.journal import PersistentRiskJournal


@pytest.mark.parametrize("kind", ["position", "gross"])
@pytest.mark.parametrize("cap", [0, 1, 1234, 2500, 5000, 9999])
@pytest.mark.parametrize("offset", ["-0.50", "0", "0.01", "0.50", "0.99"])
def test_exposure_boundary_matches_independent_fraction_oracle(
    kind: str, cap: int, offset: str
) -> None:
    price = Decimal(cap) + Decimal(offset)
    if price <= 0:
        # A positive price is required independently of exposure caps.
        price = Decimal("0.01")
    state = _make_state(cash=Decimal("10000"))
    policy = _make_policy(
        max_position_weight_basis_points=cap if kind == "position" else 10000,
        max_gross_exposure_basis_points=cap if kind == "gross" else 10000,
    )
    exceeds = Fraction(price) * 10000 > Fraction(state.net_asset_value) * cap
    with PersistentRiskJournal() as journal:
        gate = HardRiskGatekeeper(policy=policy, journal=journal)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=price)
        verdict = gate.evaluate_intent(
            intent, portfolio_state=state, current_price=price
        )
        expected = RiskVerdictStatus.REJECTED if exceeds else RiskVerdictStatus.ALLOWED
        assert verdict.status == expected
        if exceeds:
            prefix = (
                "max_position_weight_exceeded"
                if kind == "position"
                else "max_gross_exposure_exceeded"
            )
            assert prefix in str(verdict.reason)
            assert "bps of NAV" in str(verdict.reason)
        assert journal.list_verdicts() == (verdict,)


@pytest.mark.parametrize("kind", ["position", "gross"])
def test_division_rounding_cannot_hide_a_represented_excess(kind: str) -> None:
    nav = Decimal("9999.999999999999999999999999999999")
    price = Decimal("3333")
    cap = 3333
    with decimal_context():
        state = _make_state(cash=nav)
        # Even removing int() would leave this rounded ratio on the boundary.
        assert price / nav * Decimal("10000") == cap
    assert Fraction(price) * 10000 > Fraction(nav) * cap
    policy = _make_policy(
        max_position_weight_basis_points=cap if kind == "position" else 10000,
        max_gross_exposure_basis_points=cap if kind == "gross" else 10000,
    )
    with PersistentRiskJournal() as journal:
        gate = HardRiskGatekeeper(policy=policy, journal=journal)
        intent = _make_intent(sec_id=uuid7(), quantity=1, price=price)
        verdict = gate.evaluate_intent(
            intent, portfolio_state=state, current_price=price
        )
        assert verdict.status == RiskVerdictStatus.REJECTED
        assert journal.list_verdicts() == (verdict,)


@pytest.mark.parametrize("kind", ["position", "gross"])
@pytest.mark.parametrize("delta", ["-0.50", "0", "0.50"])
def test_existing_holdings_are_included_in_exact_cap_comparison(
    kind: str, delta: str
) -> None:
    security = uuid7()
    cap = 2500 if kind == "position" else 5000
    with decimal_context():
        if kind == "position":
            price = (Decimal(cap) + Decimal(delta)) / 10
            held_quantity = 9
            held_value = price * held_quantity
            held_security = security
        else:
            price = Decimal("1")
            held_quantity = 1
            held_value = Decimal(cap) + Decimal(delta) - price
            held_security = uuid7()
        holding = SecurityHoldingV2(
            security_id=held_security,
            quantity=held_quantity,
            basis_status="known",
            cost_basis=held_value,
        )
        state = _make_state(
            cash=Decimal("10000") - held_value,
            holdings=(holding,),
            holdings_value=held_value,
            holding_price=held_value / held_quantity,
        )
    policy = _make_policy(
        max_position_weight_basis_points=cap if kind == "position" else 10000,
        max_gross_exposure_basis_points=cap if kind == "gross" else 10000,
    )
    with PersistentRiskJournal() as journal:
        gate = HardRiskGatekeeper(policy=policy, journal=journal)
        intent = _make_intent(sec_id=security, quantity=1, price=price)
        verdict = gate.evaluate_order(
            intent, portfolio_state=state, current_price=price
        )
        expected = (
            RiskVerdictStatus.REJECTED
            if Decimal(delta) > 0
            else RiskVerdictStatus.ALLOWED
        )
        assert verdict.status == expected
        assert journal.list_verdicts() == (verdict,)


@pytest.mark.parametrize("kind", ["position", "gross"])
@pytest.mark.parametrize(
    "precision,rounding", [(2, ROUND_UP), (7, ROUND_DOWN), (50, ROUND_HALF_EVEN)]
)
def test_cap_comparison_is_independent_of_the_callers_decimal_context(
    kind: str, precision: int, rounding: str
) -> None:
    state = _make_state(cash=Decimal("10000"))
    price = Decimal("2500.50")
    policy = _make_policy(
        max_position_weight_basis_points=2500 if kind == "position" else 10000,
        max_gross_exposure_basis_points=2500 if kind == "gross" else 10000,
    )
    intent = _make_intent(sec_id=uuid7(), quantity=1, price=price)
    with PersistentRiskJournal() as journal, localcontext() as ambient:
        ambient.prec = precision
        ambient.rounding = rounding
        gate = HardRiskGatekeeper(policy=policy, journal=journal)
        verdict = gate.evaluate_intent(
            intent, portfolio_state=state, current_price=price
        )
        assert verdict.status == RiskVerdictStatus.REJECTED
        assert ambient.prec == precision and ambient.rounding == rounding
