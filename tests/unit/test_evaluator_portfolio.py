"""Unit tests for M2 Task 3 portfolio state and cash accounting kernel."""

from datetime import date
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from observation_test_support import uid
from pydantic import ValidationError

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    pending_cash_claim_id,
)
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.serialization.canonical import content_hash

SEC_A = uid(21)
SEC_B = uid(22)

FRI = date(2026, 1, 2)
SAT = date(2026, 1, 3)
MON = date(2026, 1, 5)
TUE = date(2026, 1, 6)


def _key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _state(cash: str = "10000.00", day: date = FRI) -> PortfolioStateV1:
    return initial_portfolio_state(session_key=_key(day), initial_cash=Decimal(cash))


def _claim(
    *,
    security_id: UUID = SEC_A,
    component_id: str = "cash-1",
    occurrence_id: str = "occ-1",
    quantity: int = 100,
    per_share: str = "0.50",
    entitlement: date = FRI,
    payable: date = MON,
    kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
) -> PendingCashClaimV1:
    per = Decimal(per_share)
    return PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            security_id=security_id,
            action_kind=kind,
            occurrence_id=occurrence_id,
            component_id=component_id,
            entitlement_session=entitlement,
            payable_session=payable,
        ),
        security_id=security_id,
        action_kind=kind,
        occurrence_id=occurrence_id,
        component_id=component_id,
        entitled_quantity=quantity,
        cash_per_share=per,
        total_cash_expected=per * quantity,
        entitlement_session=entitlement,
        payable_session=payable,
    )


# --- holdings ---


def test_holding_rejects_non_positive_quantity() -> None:
    for bad in (0, -1):
        with pytest.raises((ValidationError, ValueError)):
            SecurityHoldingV1(
                security_id=SEC_A, quantity=bad, cost_basis=Decimal("10.00")
            )


def test_holding_rejects_negative_cost_basis() -> None:
    with pytest.raises((ValidationError, ValueError)):
        SecurityHoldingV1(security_id=SEC_A, quantity=1, cost_basis=Decimal("-0.01"))


def test_average_cost_per_share_is_exact() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=8, cost_basis=Decimal("100.00")
    )
    assert holding.average_cost_per_share == Decimal("12.5")


# --- claim identity ---


def test_claim_id_is_deterministic() -> None:
    assert _claim().claim_id == _claim().claim_id


def test_claim_id_distinguishes_components_on_same_date() -> None:
    first = _claim(component_id="cash-1")
    second = _claim(component_id="cash-2")
    assert first.claim_id != second.claim_id


def test_claim_id_depends_on_every_derivation_input() -> None:
    base = _claim()
    variants = (
        _claim(security_id=SEC_B),
        _claim(kind=ActionKind.SPECIAL_CASH_DISTRIBUTION),
        _claim(occurrence_id="occ-2"),
        _claim(component_id="cash-9"),
        _claim(entitlement=MON, payable=MON),
        _claim(payable=TUE),
    )
    for variant in variants:
        assert variant.claim_id != base.claim_id


def test_claim_rejects_inconsistent_total() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PendingCashClaimV1(
            claim_id=pending_cash_claim_id(
                security_id=SEC_A,
                action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
                occurrence_id="occ-1",
                component_id="cash-1",
                entitlement_session=FRI,
                payable_session=MON,
            ),
            security_id=SEC_A,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-1",
            component_id="cash-1",
            entitled_quantity=100,
            cash_per_share=Decimal("0.50"),
            total_cash_expected=Decimal("49.00"),
            entitlement_session=FRI,
            payable_session=MON,
        )


def test_claim_rejects_payable_before_entitlement() -> None:
    with pytest.raises((ValidationError, ValueError)):
        _claim(entitlement=MON, payable=FRI)


# --- state invariants ---


def test_initial_state_nav_equals_cash() -> None:
    state = _state("10000.00")
    assert state.cash_balance == Decimal("10000.00")
    assert state.net_asset_value == Decimal("10000.00")
    assert state.holdings == ()


def test_state_rejects_negative_cash() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("-0.01"),
            holdings=(),
            pending_cash_claims=(),
            is_marked=False,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("-0.01"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_nav_that_does_not_reconcile() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("100.00"),
            holdings=(),
            pending_cash_claims=(),
            is_marked=False,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("999.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_duplicate_holdings_for_one_security() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=1, cost_basis=Decimal("10.00")
    )
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(holding, holding),
            pending_cash_claims=(),
            is_marked=False,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("0.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- fills ---


def _buy(qty: int, price: str, costs: str = "0.00") -> PortfolioFillV1:
    return PortfolioFillV1(
        security_id=SEC_A,
        side="buy",
        quantity=qty,
        fill_price=Decimal(price),
        transaction_costs=Decimal(costs),
    )


def _sell(qty: int, price: str, costs: str = "0.00") -> PortfolioFillV1:
    return PortfolioFillV1(
        security_id=SEC_A,
        side="sell",
        quantity=qty,
        fill_price=Decimal(price),
        transaction_costs=Decimal(costs),
    )


def test_buy_moves_cash_into_cost_basis_including_fees() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00", "1.50"))
    state = kernel.state
    assert state.cash_balance == Decimal("9798.50")
    assert state.holdings[0].quantity == 10
    assert state.holdings[0].cost_basis == Decimal("201.50")
    assert state.cumulative_transaction_costs == Decimal("1.50")


def test_buy_rejects_insufficient_cash() -> None:
    kernel = PortfolioAccountingKernel(_state("100.00"))
    with pytest.raises(ValueError, match="insufficient cash"):
        kernel.apply_fill(_buy(10, "20.00"))


def test_sell_relieves_cost_basis_proportionally() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(4, "25.00"))
    holding = kernel.state.holdings[0]
    assert holding.quantity == 6
    assert holding.cost_basis == Decimal("120.00")
    assert kernel.state.realized_gross_pnl == Decimal("20.00")


def test_sell_net_pnl_subtracts_costs() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(4, "25.00", "2.00"))
    assert kernel.state.realized_gross_pnl == Decimal("20.00")
    assert kernel.state.realized_net_pnl == Decimal("18.00")


def test_full_exit_removes_holding() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(10, "21.00"))
    assert kernel.state.holdings == ()
    assert kernel.state.realized_gross_pnl == Decimal("10.00")


def test_sell_rejects_more_than_held() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(5, "20.00"))
    with pytest.raises(ValueError, match="exceeds held quantity"):
        kernel.apply_fill(_sell(6, "20.00"))


def test_fill_rejects_non_positive_quantity() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioFillV1(
            security_id=SEC_A,
            side="buy",
            quantity=0,
            fill_price=Decimal("1.00"),
            transaction_costs=Decimal("0.00"),
        )


# --- claims and settlement ---


def test_recorded_claim_lifts_nav_without_touching_cash() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    kernel.record_claim(_claim(quantity=100, per_share="0.50"))
    state = kernel.state
    assert state.cash_balance == Decimal("1000.00")
    assert state.pending_claims_value == Decimal("50.00")
    assert state.net_asset_value == Decimal("1050.00")


def test_duplicate_claim_is_rejected() -> None:
    kernel = PortfolioAccountingKernel(_state())
    kernel.record_claim(_claim())
    with pytest.raises(ValueError, match="duplicate pending claim"):
        kernel.record_claim(_claim())


def test_settlement_converts_claim_into_cash() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    state = kernel.state
    assert state.cash_balance == Decimal("1050.00")
    assert state.pending_cash_claims == ()
    assert state.net_asset_value == Decimal("1050.00")


def test_settlement_ignores_claims_without_delivered_evidence() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    claim = _claim()
    kernel.record_claim(claim)
    kernel.settle_claims(())
    assert kernel.state.cash_balance == Decimal("1000.00")
    assert kernel.state.pending_cash_claims == (claim,)


def test_settlement_rejects_unknown_claim_id() -> None:
    kernel = PortfolioAccountingKernel(_state())
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims(("f" * 64,))


def test_weekend_payable_claim_settles_on_next_trading_session() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00", day=FRI))
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=SAT)
    kernel.record_claim(claim)

    # Saturday is not a trading session, so nothing settles while the book is
    # still on Friday.
    assert kernel.state.cash_balance == Decimal("1000.00")

    kernel.advance_session(_key(MON))
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.session_key.local_date == MON
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_claim_cannot_settle_before_its_payable_session() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00", day=FRI))
    claim = _claim(entitlement=FRI, payable=TUE)
    kernel.record_claim(claim)
    with pytest.raises(ValueError, match="not yet payable"):
        kernel.settle_claims((claim.claim_id,))


def test_advance_session_rejects_going_backwards() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00", day=MON))
    with pytest.raises(ValueError, match="must advance"):
        kernel.advance_session(_key(FRI))


# --- marking ---


def test_mark_close_uses_exact_unadjusted_prices() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close({SEC_A: Decimal("21.37")})
    state = kernel.state
    assert state.holdings_market_value == Decimal("213.70")
    assert state.net_asset_value == Decimal("9800.00") + Decimal("213.70")


def test_mark_close_without_price_for_held_position_is_indeterminate() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(IndeterminateValuationError):
        kernel.mark_close({})


def test_mark_close_rejects_non_positive_price() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(ValueError, match="close price"):
        kernel.mark_close({SEC_A: Decimal("0.00")})


def test_mark_close_with_no_holdings_is_valid() -> None:
    kernel = PortfolioAccountingKernel(_state("500.00"))
    kernel.mark_close({})
    assert kernel.state.holdings_market_value == Decimal("0.00")
    assert kernel.state.net_asset_value == Decimal("500.00")


def test_nav_reconciles_across_a_full_cycle() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    kernel.apply_fill(_buy(10, "20.00", "1.00"))
    claim = _claim(quantity=10, per_share="0.25", entitlement=FRI, payable=MON)
    kernel.record_claim(claim)
    kernel.advance_session(_key(MON))
    kernel.settle_claims((claim.claim_id,))
    kernel.mark_close({SEC_A: Decimal("22.00")})
    state = kernel.state
    assert (
        state.net_asset_value
        == state.cash_balance + state.holdings_market_value + state.pending_claims_value
    )
    assert state.cumulative_transaction_costs == Decimal("1.00")


# --- mark invalidation (value-creation guard) ---


def test_sell_after_mark_cannot_create_net_asset_value() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close({SEC_A: Decimal("20.00")})
    assert kernel.state.net_asset_value == Decimal("10000.00")
    kernel.apply_fill(_sell(10, "20.00"))
    state = kernel.state
    assert state.holdings == ()
    assert state.holdings_market_value == Decimal("0")
    assert state.is_marked is False
    assert state.net_asset_value == Decimal("10000.00")


def test_buy_after_mark_invalidates_the_mark() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close({SEC_A: Decimal("25.00")})
    assert kernel.state.is_marked is True
    kernel.apply_fill(_buy(5, "20.00"))
    assert kernel.state.is_marked is False
    assert kernel.state.holdings_market_value == Decimal("0")


def test_advance_session_clears_the_mark() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00", day=FRI))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close({SEC_A: Decimal("25.00")})
    kernel.advance_session(_key(MON))
    assert kernel.state.is_marked is False
    assert kernel.state.holdings_market_value == Decimal("0")
    assert kernel.state.holdings[0].quantity == 10


def test_state_rejects_market_value_without_holdings() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("100.00"),
            holdings=(),
            pending_cash_claims=(),
            is_marked=True,
            holdings_market_value=Decimal("50.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("150.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_unmarked_state_carrying_a_mark() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=1, cost_basis=Decimal("10.00")
    )
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(holding,),
            pending_cash_claims=(),
            is_marked=False,
            holdings_market_value=Decimal("11.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("11.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- atomicity ---


def test_rejected_sell_rolls_back_completely() -> None:
    kernel = PortfolioAccountingKernel(_state("100.00"))
    kernel.apply_fill(_buy(1, "100.00"))
    before = kernel.state
    with pytest.raises(ValueError, match="insufficient cash for sell costs"):
        kernel.apply_fill(_sell(1, "100.00", "500.00"))
    assert kernel.state == before
    # The rejected fill must not surface through a later successful operation.
    claim = _claim(quantity=1, per_share="1.00", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.holdings[0].quantity == 1
    assert kernel.state.cumulative_transaction_costs == Decimal("0.00")
    assert kernel.state.realized_net_pnl == Decimal("0")


def test_sell_side_costs_accumulate() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00", "1.00"))
    kernel.apply_fill(_sell(5, "20.00", "2.00"))
    assert kernel.state.cumulative_transaction_costs == Decimal("3.00")


# --- settlement container robustness ---


def test_settlement_enforces_unknown_guard_for_mapping_evidence() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    kernel.record_claim(_claim(entitlement=FRI, payable=FRI))
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims({"f" * 64: "delivered"})


def test_settlement_enforces_unknown_guard_for_keys_view() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    kernel.record_claim(_claim(entitlement=FRI, payable=FRI))
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims({"f" * 64: 1}.keys())


def test_settlement_settles_only_the_named_claim() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    first = _claim(
        component_id="cash-1", per_share="0.50", entitlement=FRI, payable=FRI
    )
    second = _claim(
        component_id="cash-2", per_share="0.25", entitlement=FRI, payable=FRI
    )
    kernel.record_claim(first)
    kernel.record_claim(second)
    kernel.settle_claims((first.claim_id,))
    state = kernel.state
    assert state.cash_balance == Decimal("1050.00")
    assert state.pending_cash_claims == (second,)
    assert state.pending_claims_value == Decimal("25.00")


# --- multi-security ---


def test_mark_close_values_every_holding() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=SEC_B,
            side="buy",
            quantity=4,
            fill_price=Decimal("50.00"),
            transaction_costs=Decimal("0.00"),
        )
    )
    kernel.mark_close({SEC_A: Decimal("21.00"), SEC_B: Decimal("55.00")})
    assert kernel.state.holdings_market_value == Decimal("430.00")


def test_mark_close_is_indeterminate_when_one_of_many_prices_is_absent() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=SEC_B,
            side="buy",
            quantity=4,
            fill_price=Decimal("50.00"),
            transaction_costs=Decimal("0.00"),
        )
    )
    with pytest.raises(IndeterminateValuationError):
        kernel.mark_close({SEC_A: Decimal("21.00")})


def test_cost_basis_is_isolated_per_security() -> None:
    kernel = PortfolioAccountingKernel(_state("10000.00"))
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=SEC_B,
            side="buy",
            quantity=4,
            fill_price=Decimal("50.00"),
            transaction_costs=Decimal("0.00"),
        )
    )
    by_id = {h.security_id: h for h in kernel.state.holdings}
    assert by_id[SEC_A].cost_basis == Decimal("200.00")
    assert by_id[SEC_B].cost_basis == Decimal("200.00")


# --- opening state and determinism ---


def test_initial_state_rejects_non_positive_cash() -> None:
    for bad in ("0.00", "-1.00"):
        with pytest.raises(ValueError, match="initial cash"):
            initial_portfolio_state(session_key=_key(FRI), initial_cash=Decimal(bad))


def test_non_terminating_basis_relief_is_deterministic() -> None:
    def run() -> Decimal:
        kernel = PortfolioAccountingKernel(_state("10000.00"))
        kernel.apply_fill(_buy(3, "33.33"))
        kernel.apply_fill(_sell(1, "40.00"))
        return kernel.state.holdings[0].cost_basis

    first = run()
    with localcontext() as ctx:
        # A dependency mangling the ambient context must not change the books.
        ctx.prec = 9
        second = run()
    assert first == second


# --- settled-claim replay (double payment) ---


def test_settled_claim_cannot_be_recorded_again() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.cash_balance == Decimal("1050.00")
    with pytest.raises(ValueError, match="already settled"):
        kernel.record_claim(claim)
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_repeated_record_settle_cycles_cannot_pay_twice() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    for _ in range(3):
        with pytest.raises(ValueError, match="already settled"):
            kernel.record_claim(claim)
    # Exactly one payment, no matter how many times the effect is re-yielded.
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_settled_claim_survives_session_advance() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00", day=FRI))
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    kernel.advance_session(_key(MON))
    with pytest.raises(ValueError, match="already settled"):
        kernel.record_claim(claim)
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_settled_ledger_is_carried_on_state_and_survives_reconstruction() -> None:
    kernel = PortfolioAccountingKernel(_state("1000.00"))
    claim = _claim(entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.settled_claim_ids == (claim.claim_id,)
    # A kernel rebuilt from persisted state must keep the guard.
    rebuilt = PortfolioAccountingKernel(kernel.state)
    with pytest.raises(ValueError, match="already settled"):
        rebuilt.record_claim(claim)


def test_state_rejects_settled_claim_reappearing_as_pending() -> None:
    claim = _claim(entitlement=FRI, payable=FRI)
    with pytest.raises((ValidationError, ValueError), match="already settled"):
        PortfolioStateV1(
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(),
            pending_cash_claims=(claim,),
            settled_claim_ids=(claim.claim_id,),
            is_marked=False,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=claim.total_cash_expected,
            net_asset_value=claim.total_cash_expected,
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- ambient decimal context independence ---


def _cycle_hashes() -> tuple[str, Decimal]:
    # Cash is deliberately large: NAV must exceed the significant digits a
    # low ambient precision would keep, otherwise the test cannot detect an
    # unpinned rebuild.
    kernel = PortfolioAccountingKernel(_state("12345678.91"))
    kernel.apply_fill(_buy(3, "33.33"))
    first = _claim(
        component_id="cash-1",
        quantity=3,
        per_share="0.33",
        entitlement=FRI,
        payable=FRI,
    )
    second = _claim(
        component_id="cash-2",
        quantity=7,
        per_share="1.11",
        entitlement=FRI,
        payable=FRI,
    )
    third = _claim(
        component_id="cash-3",
        quantity=9,
        per_share="2.22",
        entitlement=FRI,
        payable=FRI,
    )
    kernel.record_claim(first)
    kernel.record_claim(second)
    kernel.record_claim(third)
    kernel.settle_claims((first.claim_id,))
    kernel.mark_close({SEC_A: Decimal("34.00")})
    return content_hash(kernel.state), kernel.state.net_asset_value


def test_state_hash_is_independent_of_ambient_decimal_context() -> None:
    baseline, baseline_nav = _cycle_hashes()
    for precision in (34, 28, 12, 9, 7):
        with localcontext() as ctx:
            ctx.prec = precision
            digest, nav = _cycle_hashes()
        assert nav == baseline_nav, f"NAV drifted at ambient prec {precision}"
        assert digest == baseline, f"state hash drifted at ambient prec {precision}"


def test_opening_state_reconciles_under_low_ambient_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 9
        state = initial_portfolio_state(
            session_key=_key(FRI), initial_cash=Decimal("12345678.91")
        )
    assert state.net_asset_value == Decimal("12345678.91")


def test_claim_validation_holds_under_low_ambient_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 6
        claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    assert claim.total_cash_expected == Decimal("50.00")
