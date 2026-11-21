"""Whole-portfolio numeric costs without account mutation or execution."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from itertools import permutations
from typing import Any

import pytest
from test_decision_close_order_cost import _model
from test_evaluator_execution import SEC_A, SEC_B, SEC_C, _holding, _state, _target

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_portfolio import (
    PendingCashClaimV1,
    PortfolioStateV2,
    pending_cash_claim_id,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.evaluator.execution import estimate_decision_close_rebalance_cost


def test_paired_sell_buy_includes_all_costs_and_only_spendable_cash() -> None:
    state = _state(cash="4", holdings=(_holding(SEC_B, 5, "500"),))
    targets = (_target(SEC_A, 5), _target(SEC_B, 0))
    prices = {SEC_A: Decimal("100"), SEC_B: Decimal("100")}
    before = (
        state.model_dump_json(),
        tuple(t.model_dump_json() for t in targets),
        prices.copy(),
    )
    result = estimate_decision_close_rebalance_cost(
        state=state, staged_targets=targets, decision_closes=prices, cost_model=_model()
    )
    assert [security for security, _ in result.orders] == [SEC_A, SEC_B]
    assert [cost.delta for _, cost in result.orders] == [5, -5]
    assert result.total_fees == Decimal("3.10")
    assert result.total_shortfall == Decimal("0.50")
    assert result.estimated_cost == Decimal("3.60")
    assert result.required_cash == Decimal("501.80")
    assert result.net_sale_proceeds == Decimal("498.20")
    assert result.projected_cash == Decimal("0.40")
    assert result.is_funded
    assert before == (
        state.model_dump_json(),
        tuple(t.model_dump_json() for t in targets),
        prices,
    )
    mutable: Any = result
    with pytest.raises(FrozenInstanceError):
        mutable.projected_cash = Decimal("1000")


def test_unpaid_claim_does_not_fund_a_buy() -> None:
    fields: dict[str, Any] = dict(
        source_id="synthetic-claim",
        security_id=SEC_A,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="fixture-dividend",
        component_id="cash",
    )
    claim = PendingCashClaimV1(
        claim_id=pending_cash_claim_id(**fields),
        **fields,
        entitled_quantity=1,
        cash_per_share=Decimal("100"),
        total_cash_expected=Decimal("100"),
        entitlement_session=date(2026, 11, 30),
        payable_session=date(2026, 12, 1),
    )
    state = _state(cash="480").model_copy(
        update={
            "pending_cash_claims": (claim,),
            "pending_claims_value": Decimal("100"),
            "net_asset_value": Decimal("580"),
        }
    )
    result = estimate_decision_close_rebalance_cost(
        state=state,
        staged_targets=(_target(SEC_A, 5),),
        decision_closes={SEC_A: Decimal("100")},
        cost_model=_model(),
    )
    assert result.required_cash == Decimal("501.80")
    assert result.projected_cash == Decimal("-21.80")
    assert not result.is_funded
    assert result.orders[0][1].delta == 5  # No trimming to force affordability.
    assert state.pending_cash_claims == (claim,)


def test_same_family_internal_rebalance_is_not_free() -> None:
    result = estimate_decision_close_rebalance_cost(
        state=_state(holdings=(_holding(SEC_A, 5, "500"),)),
        staged_targets=(_target(SEC_A, 10),),
        decision_closes={SEC_A: Decimal("100")},
        cost_model=_model(),
    )
    assert result.estimated_cost == Decimal("1.8")
    assert result.orders[0][1].delta == 5


def test_explicit_liquidation_and_unchanged_holding_are_distinct() -> None:
    state = _state(holdings=(_holding(SEC_A, 5, "500"),))
    same = estimate_decision_close_rebalance_cost(
        state=state,
        staged_targets=(_target(SEC_A, 5),),
        decision_closes={SEC_A: Decimal("100")},
        cost_model=_model(),
    )
    assert same.orders == ()
    assert same.estimated_cost == 0
    assert same.projected_cash == state.cash_balance
    liquidate = estimate_decision_close_rebalance_cost(
        state=state,
        staged_targets=(_target(SEC_A, 0),),
        decision_closes={SEC_A: Decimal("100")},
        cost_model=_model(),
    )
    assert liquidate.orders[0][1].delta == -5
    assert liquidate.net_sale_proceeds == Decimal("498.2")


@pytest.mark.parametrize("target_quantity", [0, 5, 10])
@pytest.mark.parametrize("prices", [{}, {SEC_A: Decimal("NaN")}, {SEC_A: Decimal("0")}])
def test_missing_or_invalid_held_close_refuses_even_without_trade(
    target_quantity: int, prices: dict[Any, Decimal]
) -> None:
    with pytest.raises(ValueError, match="close"):
        estimate_decision_close_rebalance_cost(
            state=_state(holdings=(_holding(SEC_A, 5, "500"),)),
            staged_targets=(_target(SEC_A, target_quantity),),
            decision_closes=prices,
            cost_model=_model(),
        )


def test_missing_buy_price_refuses_but_unheld_zero_target_needs_none() -> None:
    state = _state()
    with pytest.raises(ValueError, match="close"):
        estimate_decision_close_rebalance_cost(
            state=state,
            staged_targets=(_target(SEC_A, 1),),
            decision_closes={},
            cost_model=_model(),
        )
    result = estimate_decision_close_rebalance_cost(
        state=state,
        staged_targets=(_target(SEC_A, 0),),
        decision_closes={},
        cost_model=_model(),
    )
    assert result.orders == () and result.estimated_cost == 0


@pytest.mark.parametrize("targets", [(), (_target(SEC_B, 1),)])
def test_omitted_holding_is_not_silent_liquidation(
    targets: tuple[SecurityTargetPositionV1, ...],
) -> None:
    with pytest.raises(ValueError, match="cover every held security"):
        estimate_decision_close_rebalance_cost(
            state=_state(holdings=(_holding(SEC_A, 5, "500"),)),
            staged_targets=targets,
            decision_closes={SEC_A: Decimal("100"), SEC_B: Decimal("100")},
            cost_model=_model(),
        )


def test_duplicate_targets_are_not_merged() -> None:
    with pytest.raises(ValueError, match="unique"):
        estimate_decision_close_rebalance_cost(
            state=_state(),
            staged_targets=(_target(SEC_A, 1), _target(SEC_A, 2)),
            decision_closes={SEC_A: Decimal("100")},
            cost_model=_model(),
        )


@pytest.mark.parametrize("quantity", [-1, True, 0.5, Decimal("1"), "1"])
def test_forged_noninteger_or_negative_target_refuses(quantity: Any) -> None:
    forged = SecurityTargetPositionV1.model_construct(
        security_id=SEC_A, target_quantity=quantity
    )
    with pytest.raises(ValueError):
        estimate_decision_close_rebalance_cost(
            state=_state(),
            staged_targets=(forged,),
            decision_closes={SEC_A: Decimal("100")},
            cost_model=_model(),
        )


@pytest.mark.parametrize("empty", [True, False])
def test_invalid_state_and_cost_model_refuse_even_for_no_trades(empty: bool) -> None:
    state = _state()
    targets = () if empty else (_target(SEC_A, 0),)
    forged = PortfolioStateV2.model_construct(
        **{
            **{name: getattr(state, name) for name in PortfolioStateV2.model_fields},
            "net_asset_value": Decimal("7"),
        }
    )
    with pytest.raises(ValueError):
        estimate_decision_close_rebalance_cost(
            state=forged,
            staged_targets=targets,
            decision_closes={},
            cost_model=_model(),
        )
    model = _model()
    forged_model = EvaluationCostModelV1.model_construct(
        **{**model.model_dump(mode="python"), "cost_model_hash": "0" * 64}
    )
    with pytest.raises(ValueError):
        estimate_decision_close_rebalance_cost(
            state=state,
            staged_targets=targets,
            decision_closes={},
            cost_model=forged_model,
        )


def test_order_and_hostile_decimal_context_do_not_change_result() -> None:
    state = _state(cash="10", holdings=(_holding(SEC_B, 5, "500"),))
    targets = (_target(SEC_A, 2), _target(SEC_B, 0), _target(SEC_C, 1))
    prices = {SEC_A: Decimal("100"), SEC_B: Decimal("100"), SEC_C: Decimal("50")}
    model = _model()
    expected = estimate_decision_close_rebalance_cost(
        state=state, staged_targets=targets, decision_closes=prices, cost_model=model
    )
    for order in permutations(targets):
        with localcontext() as ambient:
            ambient.prec = 2
            ambient.Emax = 2
            ambient.Emin = -2
            ambient.traps[Inexact] = ambient.traps[Rounded] = True
            ambient.flags[Inexact] = ambient.flags[Rounded] = True
            result = estimate_decision_close_rebalance_cost(
                state=state,
                staged_targets=order,
                decision_closes=dict(reversed(tuple(prices.items()))),
                cost_model=model,
            )
            assert result == expected
            assert ambient.prec == 2
            assert ambient.traps[Inexact] and ambient.flags[Inexact]
            assert ambient.traps[Rounded] and ambient.flags[Rounded]


def test_complete_portfolio_matches_independent_fraction_oracle() -> None:
    for buy_quantity in (0, 1, 5, 17):
        for sell_target in (0, 2, 5):
            result = estimate_decision_close_rebalance_cost(
                state=_state(cash="20", holdings=(_holding(SEC_B, 5, "500"),)),
                staged_targets=(
                    _target(SEC_A, buy_quantity),
                    _target(SEC_B, sell_target),
                ),
                decision_closes={SEC_A: Decimal("13.25"), SEC_B: Decimal("100")},
                cost_model=_model(),
            )
            cost = Fraction(0)
            cash = Fraction(20)
            for delta, price in (
                (buy_quantity, Fraction("13.25")),
                (sell_target - 5, Fraction(100)),
            ):
                if not delta:
                    continue
                notional = abs(delta) * price
                fee = Fraction(abs(delta), 100) + 1 + notional / 1000
                shortfall = notional / 2000
                cost += fee + shortfall
                cash += (
                    -notional - fee - shortfall
                    if delta > 0
                    else notional - fee - shortfall
                )
            assert Fraction(result.estimated_cost) == cost
            assert Fraction(result.projected_cash) == cash
            assert result.is_funded == (cash >= 0)
