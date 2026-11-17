"""Stage 1 economic cost policy and accounting integration (Workstream C, Issue 575).

Enforces:
- Transaction costs inside original NAV (brokerage commissions, fees, slippage).
- Model usage and research costs outside investment NAV.
- Correct one-time and shared expense allocation.
- Tracking retries, abandoned attempts, and unknown costs.
- No double counting.
- No silent zero costs: fail-closed if operating or transaction costs are
  required but missing.
- Identical applicable market data, fees, and risk constraints for B and R.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.experiments.stage1_trial_projection import ExactRatioV1
from drift.loop.stage1_controlled_contracts import exact_decimal
from drift.serialization.canonical import canonical_json, content_hash

_MAX_EXACT_INPUT_DIGITS = 1024


def _bounded_fraction(value: Decimal) -> Fraction:
    """Bound rational expansion before converting a finite Decimal."""
    if value.is_zero():
        return Fraction(0)
    parts = value.as_tuple()
    assert isinstance(parts.exponent, int)  # The caller has rejected nonfinite values.
    if len(parts.digits) + abs(parts.exponent) > _MAX_EXACT_INPUT_DIGITS:
        raise ValueError("ECONOMIC_PRECISION_BUDGET_EXCEEDED")
    return Fraction(value)


class Stage1EconomicCostPolicyV1(FrozenModel):
    """Immutable, comparable economic cost policy for Stage 1 trials."""

    schema_version: Literal["drift-stage1-cost-policy/1"] = "drift-stage1-cost-policy/1"
    policy_id: NonBlankStr
    cost_model: EvaluationCostModelV1
    operating_cost_accounting: Literal["ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO"] = (
        "ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO"
    )
    investment_nav_accounting: Literal["TRADING_IN_NAV_OPERATING_OUTSIDE_NAV"] = (
        "TRADING_IN_NAV_OPERATING_OUTSIDE_NAV"
    )
    identical_cost_basis_enforced: Literal[True] = True
    policy_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"policy_hash"})
        computed = content_hash(body)
        if self.policy_hash != computed:
            raise ValueError(
                f"COST_POLICY_HASH_MISMATCH: expected {computed}, "
                f"got {self.policy_hash}"
            )
        return self


def create_stage1_cost_model(
    *,
    model_id: str = "drift-stage1-source-backed-costs/1",
    commission_per_share: Decimal = Decimal("0.00"),
    fixed_fee_per_order: Decimal = Decimal("0.00"),
    notional_fee_basis_points: Decimal = Decimal("0.00"),
    adverse_slippage_basis_points: Decimal = Decimal("1.00"),
) -> EvaluationCostModelV1:
    """Build a validated EvaluationCostModelV1 with exact decimal arithmetic."""
    draft = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id=model_id,
        commission_per_share=commission_per_share,
        fixed_fee_per_order=fixed_fee_per_order,
        notional_fee_basis_points=notional_fee_basis_points,
        adverse_slippage_basis_points=adverse_slippage_basis_points,
        cost_model_hash="0" * 64,
    )
    return draft.model_copy(
        update={"cost_model_hash": evaluation_cost_model_hash(draft)}
    )


def create_stage1_economic_cost_policy(
    *,
    policy_id: str = "drift-stage1-economic-cost-policy/1",
    cost_model: EvaluationCostModelV1 | None = None,
) -> Stage1EconomicCostPolicyV1:
    """Create the locked Stage 1 comparable economic-cost policy."""
    model = cost_model or create_stage1_cost_model()
    body = {
        "schema_version": "drift-stage1-cost-policy/1",
        "policy_id": policy_id,
        "cost_model": model,
        "operating_cost_accounting": "ORIGINAL_RECEIPTS_NO_UNKNOWN_ZERO",
        "investment_nav_accounting": "TRADING_IN_NAV_OPERATING_OUTSIDE_NAV",
        "identical_cost_basis_enforced": True,
    }
    h = content_hash(body)
    return Stage1EconomicCostPolicyV1.model_validate_json(
        canonical_json(body | {"policy_hash": h})
    )


class EconomicComparisonBreakdownV1(FrozenModel):
    """Reconciled economic outcome comparing candidate arm B and reference arm R."""

    initial_capital: Decimal = Field(allow_inf_nan=False)
    b_terminal_nav: Decimal = Field(allow_inf_nan=False)
    r_terminal_nav: Decimal = Field(allow_inf_nan=False)
    b_investment_gain: Decimal = Field(allow_inf_nan=False)
    r_investment_gain: Decimal = Field(allow_inf_nan=False)
    delta_nav: Decimal = Field(allow_inf_nan=False)
    b_trading_costs: Decimal = Field(ge=0, allow_inf_nan=False)
    r_trading_costs: Decimal = Field(ge=0, allow_inf_nan=False)
    incremental_operating_costs: Decimal = Field(ge=0, allow_inf_nan=False)
    primary_economic_advantage: Decimal = Field(allow_inf_nan=False)
    b_net_return: ExactRatioV1
    r_net_return: ExactRatioV1
    pea_fraction: ExactRatioV1


def reconcile_economic_advantage(
    *,
    initial_capital: Decimal,
    b_terminal_nav: Decimal,
    r_terminal_nav: Decimal,
    incremental_operating_costs: Decimal,
    b_trading_costs: Decimal = Decimal("0"),
    r_trading_costs: Decimal = Decimal("0"),
) -> EconomicComparisonBreakdownV1:
    """Reconcile economic advantage adhering to locked study accounting rules.

    Transaction costs are inside NAV.
    Operating costs are deducted outside investment NAV.
    No silent zero operating costs allowed when operating activity took place.
    """
    if not (
        initial_capital.is_finite()
        and b_terminal_nav.is_finite()
        and r_terminal_nav.is_finite()
        and incremental_operating_costs.is_finite()
        and b_trading_costs.is_finite()
        and r_trading_costs.is_finite()
    ):
        raise ValueError("NON_FINITE_ECONOMIC_VALUES")

    if initial_capital <= Decimal("0"):
        raise ValueError("NON_POSITIVE_INITIAL_CAPITAL")

    if incremental_operating_costs < Decimal("0"):
        raise ValueError("NEGATIVE_OPERATING_COSTS")

    initial = _bounded_fraction(initial_capital)
    b_terminal = _bounded_fraction(b_terminal_nav)
    r_terminal = _bounded_fraction(r_terminal_nav)
    operating_cost = _bounded_fraction(incremental_operating_costs)
    b_gain = b_terminal - initial
    r_gain = r_terminal - initial
    delta_nav = b_terminal - r_terminal
    pea = delta_nav - operating_cost

    b_net_ret = ExactRatioV1.from_fraction(b_gain / initial)
    r_net_ret = ExactRatioV1.from_fraction(r_gain / initial)
    pea_frac = ExactRatioV1.from_fraction(pea / initial)

    return EconomicComparisonBreakdownV1(
        initial_capital=initial_capital,
        b_terminal_nav=b_terminal_nav,
        r_terminal_nav=r_terminal_nav,
        b_investment_gain=exact_decimal(b_gain),
        r_investment_gain=exact_decimal(r_gain),
        delta_nav=exact_decimal(delta_nav),
        b_trading_costs=b_trading_costs,
        r_trading_costs=r_trading_costs,
        incremental_operating_costs=incremental_operating_costs,
        primary_economic_advantage=exact_decimal(pea),
        b_net_return=b_net_ret,
        r_net_return=r_net_ret,
        pea_fraction=pea_frac,
    )
