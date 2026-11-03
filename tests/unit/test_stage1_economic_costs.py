"""Unit tests for Stage 1 economic cost policy and accounting integration.

Workstream C, Issue 575.
"""

from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_economic_costs import (
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
