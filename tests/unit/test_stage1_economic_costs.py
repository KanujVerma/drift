"""Unit tests for Stage 1 economic cost policy and accounting integration.

Workstream C, Issue 575.
"""

import subprocess
import sys
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_economic_costs import (
    EconomicComparisonBreakdownV1,
    Stage1EconomicCostPolicyV1,
    create_stage1_cost_model,
    create_stage1_economic_cost_policy,
    reconcile_economic_advantage,
)


def test_create_stage1_cost_model_and_policy() -> None:
    model = create_stage1_cost_model(
        commission_per_share=Decimal("0.00"),
        fixed_fee_per_order=Decimal("0.00"),
        notional_fee_basis_points=Decimal("0.50"),
        adverse_slippage_basis_points=Decimal("1.00"),
    )
    assert model.notional_fee_basis_points == Decimal("0.50")
    assert model.adverse_slippage_basis_points == Decimal("1.00")
    assert len(model.cost_model_hash) == 64

    policy = create_stage1_economic_cost_policy(cost_model=model)
    assert policy.operating_cost_accounting == "ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO"
    assert policy.investment_nav_accounting == "TRADING_IN_NAV_OPERATING_OUTSIDE_NAV"
    assert policy.identical_cost_basis_enforced is True
    assert len(policy.policy_hash) == 64

    # Tampered hash rejected
    raw = policy.model_dump(mode="python")
    raw["policy_hash"] = "e" * 64
    with pytest.raises(ValidationError, match="COST_POLICY_HASH_MISMATCH"):
        Stage1EconomicCostPolicyV1.model_validate(raw)


def test_reconcile_economic_advantage_positive_control() -> None:
    econ = reconcile_economic_advantage(
        initial_capital=Decimal("10000"),
        b_terminal_nav=Decimal("11000"),
        r_terminal_nav=Decimal("10500"),
        incremental_operating_costs=Decimal("50"),
        b_trading_costs=Decimal("5"),
        r_trading_costs=Decimal("4"),
    )
    assert econ.b_investment_gain == Decimal("1000")
    assert econ.r_investment_gain == Decimal("500")
    assert econ.delta_nav == Decimal("500")
    assert econ.primary_economic_advantage == Decimal("450")  # 500 - 50 operating costs
    assert econ.b_net_return.as_fraction() == Fraction(1, 10)
    assert econ.r_net_return.as_fraction() == Fraction(1, 20)
    assert econ.pea_fraction.as_fraction() == Fraction(9, 200)


@pytest.mark.parametrize("precision", [6, 28, 50])
@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_HALF_EVEN])
def test_economic_reconciliation_is_exact_across_decimal_contexts(
    precision: int, rounding: str
) -> None:
    initial = Decimal("10000")
    b_nav = Decimal("10001.123456789012345678901234567891")
    r_nav = Decimal("10000.234567890123456789012345678912")
    operating_cost = Decimal("0.000000000000000000000000000123")

    with localcontext() as ctx:
        ctx.prec = precision
        ctx.rounding = rounding
        actual = reconcile_economic_advantage(
            initial_capital=initial,
            b_terminal_nav=b_nav,
            r_terminal_nav=r_nav,
            incremental_operating_costs=operating_cost,
            b_trading_costs=Decimal("5"),
            r_trading_costs=Decimal("4"),
        )

    expected_b = Fraction(b_nav) - Fraction(initial)
    expected_r = Fraction(r_nav) - Fraction(initial)
    expected_delta = Fraction(b_nav) - Fraction(r_nav)
    expected_economic = expected_delta - Fraction(operating_cost)
    assert Fraction(actual.b_investment_gain) == expected_b
    assert Fraction(actual.r_investment_gain) == expected_r
    assert Fraction(actual.delta_nav) == expected_delta
    assert Fraction(actual.primary_economic_advantage) == expected_economic
    assert actual.b_net_return.as_fraction() == expected_b / Fraction(initial)
    assert actual.r_net_return.as_fraction() == expected_r / Fraction(initial)
    assert actual.pea_fraction.as_fraction() == expected_economic / Fraction(initial)


def test_economic_reconciliation_preserves_nonterminating_ratio() -> None:
    with localcontext() as ctx:
        ctx.prec = 6
        actual = reconcile_economic_advantage(
            initial_capital=Decimal("3"),
            b_terminal_nav=Decimal("4"),
            r_terminal_nav=Decimal("3"),
            incremental_operating_costs=Decimal("0"),
        )
    assert actual.b_net_return.as_fraction() == Fraction(1, 3)


@pytest.mark.parametrize(
    "field",
    [
        "initial_capital",
        "b_terminal_nav",
        "r_terminal_nav",
        "incremental_operating_costs",
    ],
)
@pytest.mark.parametrize("value", ["1e100000000", "1e-100000000"])
def test_economic_reconciliation_refuses_unbounded_decimal_expansion(
    field: str, value: str
) -> None:
    script = """
from decimal import Decimal
import sys
from drift.experiments.stage1_economic_costs import reconcile_economic_advantage
try:
    values = {
        'initial_capital': Decimal('10000'),
        'b_terminal_nav': Decimal('10120'),
        'r_terminal_nav': Decimal('10000'),
        'incremental_operating_costs': Decimal('0'),
    }
    values[sys.argv[1]] = Decimal(sys.argv[2])
    reconcile_economic_advantage(**values)
except ValueError as error:
    print(error)
else:
    raise AssertionError('extreme input was accepted')
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, field, value],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert "ECONOMIC_PRECISION_BUDGET_EXCEEDED" in proc.stdout


def test_economic_reconciliation_refuses_oversized_coefficient() -> None:
    with pytest.raises(ValueError, match="ECONOMIC_PRECISION_BUDGET_EXCEEDED"):
        reconcile_economic_advantage(
            initial_capital=Decimal("10000"),
            b_terminal_nav=Decimal("9" * 1025),
            r_terminal_nav=Decimal("10000"),
            incremental_operating_costs=Decimal("0"),
        )


def test_economic_precision_budget_boundary_and_extreme_zero() -> None:
    initial = Decimal("10000")
    allowed = Decimal("1e-1023")
    result = reconcile_economic_advantage(
        initial_capital=initial,
        b_terminal_nav=allowed,
        r_terminal_nav=Decimal("0e-100000000"),
        incremental_operating_costs=Decimal("0"),
    )
    assert Fraction(result.b_investment_gain) == Fraction(allowed) - Fraction(initial)
    with pytest.raises(ValueError, match="ECONOMIC_PRECISION_BUDGET_EXCEEDED"):
        reconcile_economic_advantage(
            initial_capital=initial,
            b_terminal_nav=Decimal("1e-1024"),
            r_terminal_nav=Decimal("0"),
            incremental_operating_costs=Decimal("0"),
        )


def test_economic_cross_scale_result_roundtrips_exactly() -> None:
    initial = Decimal("1e-1023")
    end = Decimal("1e1023")
    result = reconcile_economic_advantage(
        initial_capital=initial,
        b_terminal_nav=end,
        r_terminal_nav=Decimal("0"),
        incremental_operating_costs=Decimal("0"),
    )
    restored = EconomicComparisonBreakdownV1.model_validate_json(
        result.model_dump_json()
    )
    expected = (Fraction(end) - Fraction(initial)) / Fraction(initial)
    assert restored.b_net_return.as_fraction() == expected
    assert restored == result


def test_reconcile_economic_advantage_negative_controls() -> None:
    # Non-positive initial capital rejected
    with pytest.raises(ValueError, match="NON_POSITIVE_INITIAL_CAPITAL"):
        reconcile_economic_advantage(
            initial_capital=Decimal("0"),
            b_terminal_nav=Decimal("10000"),
            r_terminal_nav=Decimal("10000"),
            incremental_operating_costs=Decimal("0"),
        )

    # Negative operating costs rejected
    with pytest.raises(ValueError, match="NEGATIVE_OPERATING_COSTS"):
        reconcile_economic_advantage(
            initial_capital=Decimal("10000"),
            b_terminal_nav=Decimal("10500"),
            r_terminal_nav=Decimal("10200"),
            incremental_operating_costs=Decimal("-10"),
        )
