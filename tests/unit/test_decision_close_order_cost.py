"""Numeric-only decision-close cost fixtures and independent rational oracle."""

from dataclasses import FrozenInstanceError
from decimal import Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from itertools import product
from typing import Any

import pytest

from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.evaluator.execution import estimate_decision_close_order_cost


def _model(
    commission: str = "0.01", fixed: str = "1", notional: str = "10", slip: str = "5"
) -> EvaluationCostModelV1:
    draft = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="explicit-synthetic-fee-fixture",
        commission_per_share=Decimal(commission),
        fixed_fee_per_order=Decimal(fixed),
        notional_fee_basis_points=Decimal(notional),
        adverse_slippage_basis_points=Decimal(slip),
        cost_model_hash="0" * 64,
    )
    return draft.model_copy(
        update={"cost_model_hash": evaluation_cost_model_hash(draft)}
    )


@pytest.mark.parametrize(
    ("delta", "fees", "shortfall", "cost", "cash"),
    [
        (5, "1.55", "0.25", "1.8", "-501.8"),
        (-5, "1.55", "0.25", "1.8", "498.2"),
        (0, "0", "0", "0", "0"),
    ],
)
def test_hand_computable_buy_sell_and_zero(
    delta: int, fees: str, shortfall: str, cost: str, cash: str
) -> None:
    result = estimate_decision_close_order_cost(
        delta=delta, decision_close=Decimal("100"), cost_model=_model()
    )
    assert result.delta == delta
    assert result.reference_notional == Decimal(abs(delta) * 100)
    assert result.fees == Decimal(fees)
    assert result.adverse_shortfall == Decimal(shortfall)
    assert result.estimated_cost == Decimal(cost)
    assert result.cash_delta == Decimal(cash)


def test_paired_orders_keep_both_fixed_fees_and_shortfalls() -> None:
    buy = estimate_decision_close_order_cost(
        delta=5, decision_close=Decimal("100"), cost_model=_model()
    )
    sell = estimate_decision_close_order_cost(
        delta=-5, decision_close=Decimal("100"), cost_model=_model()
    )
    assert buy.fees + sell.fees == Decimal("3.10")
    assert buy.estimated_cost + sell.estimated_cost == Decimal("3.60")
    assert buy.cash_delta + sell.cash_delta == Decimal("-3.60")


def test_later_price_computation_cannot_mutate_earlier_result() -> None:
    model = _model()
    before = model.model_dump_json()
    earlier = estimate_decision_close_order_cost(
        delta=5, decision_close=Decimal("100"), cost_model=model
    )
    later = estimate_decision_close_order_cost(
        delta=5, decision_close=Decimal("103"), cost_model=model
    )
    assert earlier.estimated_cost == Decimal("1.8")
    assert later.estimated_cost == Decimal("1.8225")
    assert model.model_dump_json() == before
    mutable_attempt: Any = earlier
    with pytest.raises(FrozenInstanceError):
        mutable_attempt.estimated_cost = Decimal("0")


def test_order_cost_grid_matches_independent_exact_rational_arithmetic() -> None:
    for delta, price, commission, fixed, notional, slip in product(
        (-17, -1, 0, 1, 17),
        ("0.01", "99.125", "10000"),
        ("0", "0.013"),
        ("0", "1.25"),
        ("0", "13.7"),
        ("0", "7.3"),
    ):
        model = _model(commission, fixed, notional, slip)
        result = estimate_decision_close_order_cost(
            delta=delta, decision_close=Decimal(price), cost_model=model
        )
        gross = abs(delta) * Fraction(price)
        fees = (
            abs(delta) * Fraction(commission)
            + Fraction(fixed)
            + gross * Fraction(notional) / 10000
            if delta
            else Fraction(0)
        )
        shortfall = gross * Fraction(slip) / 10000
        expected_cash = (
            -(gross + fees + shortfall) if delta > 0 else gross - fees - shortfall
        )
        assert Fraction(result.reference_notional) == gross
        assert Fraction(result.fees) == fees
        assert Fraction(result.adverse_shortfall) == shortfall
        assert Fraction(result.estimated_cost) == fees + shortfall
        assert Fraction(result.cash_delta) == expected_cash


@pytest.mark.parametrize("precision", [2, 9, 28, 60])
def test_hostile_ambient_decimal_context_cannot_change_result(precision: int) -> None:
    model = _model("0.013", "1.25", "13.7", "7.3")
    baseline = estimate_decision_close_order_cost(
        delta=-17, decision_close=Decimal("99.125"), cost_model=model
    )
    with localcontext() as context:
        context.prec = precision
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.flags[Inexact] = True
        context.flags[Rounded] = True
        before = context.copy()
        actual = estimate_decision_close_order_cost(
            delta=-17, decision_close=Decimal("99.125"), cost_model=model
        )
        assert actual == baseline
        assert context.prec == before.prec and context.Emax == before.Emax
        assert context.traps == before.traps and context.flags == before.flags


@pytest.mark.parametrize("delta", [True, False, 5.0, Decimal("5"), "5", None])
def test_whole_share_delta_requires_an_exact_integer(delta: Any) -> None:
    with pytest.raises(ValueError, match="delta"):
        estimate_decision_close_order_cost(
            delta=delta, decision_close=Decimal("100"), cost_model=_model()
        )


@pytest.mark.parametrize(
    "price",
    [
        None,
        True,
        100,
        100.0,
        "100",
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("1.12345678901234567890123456789012345"),
    ],
)
@pytest.mark.parametrize("delta", [0, 5])
def test_missing_invalid_or_unrepresentable_price_is_not_a_zero_cost(
    price: Any, delta: int
) -> None:
    with pytest.raises(ValueError, match="decision.close"):
        estimate_decision_close_order_cost(
            delta=delta, decision_close=price, cost_model=_model()
        )


def test_delta_that_cannot_fit_portfolio_context_is_refused() -> None:
    with pytest.raises(ValueError, match="delta"):
        estimate_decision_close_order_cost(
            delta=10**35 + 1, decision_close=Decimal("1"), cost_model=_model()
        )


@pytest.mark.parametrize("delta", [0, 5])
def test_forged_cost_model_is_refused_even_for_zero_delta(delta: int) -> None:
    model = _model()
    forged = EvaluationCostModelV1.model_construct(
        **{**model.model_dump(mode="python"), "commission_per_share": Decimal("2")}
    )
    with pytest.raises(ValueError):
        estimate_decision_close_order_cost(
            delta=delta, decision_close=Decimal("100"), cost_model=forged
        )


@pytest.mark.parametrize("model", [None, {}, "policy"])
def test_missing_model_is_not_a_zero_fee_policy(model: Any) -> None:
    with pytest.raises(ValueError, match="cost model"):
        estimate_decision_close_order_cost(
            delta=0, decision_close=Decimal("100"), cost_model=model
        )


def test_overflow_is_an_unavailable_numeric_result() -> None:
    with pytest.raises(ValueError, match="represent"):
        estimate_decision_close_order_cost(
            delta=10, decision_close=Decimal("1e999999"), cost_model=_model()
        )
