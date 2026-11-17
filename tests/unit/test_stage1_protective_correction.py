"""Cost-aware protective plans use original M2 fills without changing the book."""

from datetime import timedelta
from decimal import Decimal, localcontext
from typing import Any

import pytest
from test_evaluator_execution import (
    EXEC_CLOCK,
    EXEC_OPEN,
    LISTING_OTHER,
    SEC_A,
    SEC_B,
    SEC_C,
    ZERO_COST,
    _cost_model,
    _holding,
    _listings_for,
    _price,
    _session,
    _state,
)

from drift.loop.stage1_controlled_contracts import (
    ClassMandateV1,
    SecurityMandateV1,
    SyntheticMandateV1,
)
from drift.loop.stage1_protective_correction import (
    ProtectiveCorrectionPolicyV1,
    plan_protective_correction,
)
from drift.serialization.canonical import canonical_json


def correction_arguments() -> dict[str, Any]:
    return {
        "policy": ProtectiveCorrectionPolicyV1(
            enabled=True,
            allow_while_paused=False,
            maximum_preview_evaluations=256,
        ),
        "mandate": SyntheticMandateV1(
            policy_id="synthetic-explicit-correction",
            revision="1",
            securities=(
                SecurityMandateV1(
                    security_id=SEC_A,
                    asset_class="equity",
                    maximum_fraction=Decimal("0.2"),
                ),
                SecurityMandateV1(
                    security_id=SEC_B,
                    asset_class="equity",
                    maximum_fraction=Decimal("0.5"),
                ),
                SecurityMandateV1(
                    security_id=SEC_C,
                    asset_class="bond",
                    maximum_fraction=Decimal("0.5"),
                ),
            ),
            classes=(
                ClassMandateV1(asset_class="bond", maximum_fraction=Decimal("1")),
                ClassMandateV1(asset_class="equity", maximum_fraction=Decimal("1")),
            ),
            maximum_gross_fraction=Decimal("1"),
            maximum_turnover_fraction=Decimal("2"),
            maximum_price_age_sessions=0,
            paused=False,
            execution_knowledge="RESOLVED",
        ),
        "state": _state(cash="8000", holdings=(_holding(SEC_A, 30, "3000"),)),
        "execution_session": _session(),
        "open_prices": {SEC_A: _price("100")},
        "execution_listings": _listings_for(SEC_A),
        "cost_model": ZERO_COST,
        "session_clock": EXEC_CLOCK,
    }


@pytest.mark.parametrize("fee, remaining", [("0", 22), ("1", 21)])
def test_exact_post_cost_cap_requires_minimum_whole_share_reduction(
    fee: str,
    remaining: int,
) -> None:
    args = correction_arguments()
    args["cost_model"] = _cost_model(
        commission="0", fixed_fee=fee, notional_bps="0", slippage_bps="0"
    )
    before = canonical_json(args["state"])
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert result.before_open_nav == Decimal("11000")
    assert result.projected_open_nav == Decimal("11000") - Decimal(fee)
    assert [(t.security_id, t.target_quantity) for t in result.targets] == [
        (SEC_A, remaining)
    ]
    assert result.outcome is not None
    assert len(result.outcome.committed_fills) == 1
    fill = result.outcome.committed_fills[0]
    assert (fill.side, fill.quantity, fill.transaction_costs) == (
        "sell",
        30 - remaining,
        Decimal(fee),
    )
    assert result.outcome.state.cash_balance == (
        Decimal("8000") + Decimal(30 - remaining) * 100 - Decimal(fee)
    )
    assert not result.final_breaches
    assert canonical_json(args["state"]) == before


def test_class_trim_preserves_other_class_and_uses_stable_notional_order() -> None:
    args = correction_arguments()
    args["state"] = _state(
        cash="5000",
        holdings=(
            _holding(SEC_A, 20, "2000"),
            _holding(SEC_B, 20, "2000"),
            _holding(SEC_C, 10, "1000"),
        ),
    )
    mandate = args["mandate"]
    args["mandate"] = mandate.model_copy(
        update={
            "securities": tuple(
                s.model_copy(update={"maximum_fraction": Decimal("0.5")})
                for s in mandate.securities
            ),
            "classes": (
                ClassMandateV1(asset_class="bond", maximum_fraction=Decimal("1")),
                ClassMandateV1(asset_class="equity", maximum_fraction=Decimal("0.3")),
            ),
        }
    )
    args["open_prices"] = {s: _price("100") for s in (SEC_A, SEC_B, SEC_C)}
    args["execution_listings"] = _listings_for(SEC_A, SEC_B, SEC_C)
    args["cost_model"] = _cost_model(
        commission="0", fixed_fee="1", notional_bps="0", slippage_bps="0"
    )
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert {t.security_id: t.target_quantity for t in result.targets} == {
        SEC_A: 9,
        SEC_B: 20,
        SEC_C: 10,
    }
    assert result.projected_open_nav == Decimal("9999")
    assert result.outcome is not None
    assert len(result.outcome.committed_fills) == 1


def test_all_original_cost_components_reduce_corrective_open_nav() -> None:
    args = correction_arguments()
    args["cost_model"] = _cost_model(
        commission="1", fixed_fee="1", notional_bps="100", slippage_bps="1000"
    )
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert result.targets[0].target_quantity == 21
    assert result.projected_open_nav == Decimal("10891")
    assert result.outcome is not None
    fill = result.outcome.committed_fills[0]
    assert fill.quantity == 9
    assert fill.fill_price == Decimal("90")
    assert fill.transaction_costs == Decimal("19")
    assert result.outcome.state.cash_balance == Decimal("8791")


def test_fees_cannot_hide_new_breach_in_formerly_compliant_holding() -> None:
    args = correction_arguments()
    args["state"] = _state(
        cash="5800",
        holdings=(_holding(SEC_A, 30, "3000"), _holding(SEC_B, 22, "2200")),
    )
    args["mandate"] = args["mandate"].model_copy(
        update={
            "securities": tuple(
                s.model_copy(update={"maximum_fraction": Decimal("0.2")})
                for s in args["mandate"].securities
            )
        }
    )
    args["open_prices"] = {SEC_A: _price("100"), SEC_B: _price("100")}
    args["execution_listings"] = _listings_for(SEC_A, SEC_B)
    args["cost_model"] = _cost_model(
        commission="0", fixed_fee="1", notional_bps="0", slippage_bps="0"
    )
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert {t.security_id: t.target_quantity for t in result.targets} == {
        SEC_A: 21,
        SEC_B: 21,
    }
    assert result.projected_open_nav == Decimal("10998")
    assert result.outcome is not None
    assert sum(f.transaction_costs for f in result.outcome.committed_fills) == 2


@pytest.mark.parametrize("knowledge", ["UNKNOWN", "PARTIAL"])
def test_unreconciled_execution_never_authorizes_protective_sells(
    knowledge: str,
) -> None:
    args = correction_arguments()
    args["mandate"] = args["mandate"].model_copy(
        update={"execution_knowledge": knowledge}
    )
    result = plan_protective_correction(**args)
    assert result.status == "UNRESOLVED"
    assert result.reason == "CORRECTION_EXECUTION_UNRESOLVED"
    assert result.outcome is None and not result.targets


@pytest.mark.parametrize("allowed", [False, True])
def test_pause_requires_separate_explicit_protective_permission(allowed: bool) -> None:
    args = correction_arguments()
    args["mandate"] = args["mandate"].model_copy(update={"paused": True})
    args["policy"] = args["policy"].model_copy(update={"allow_while_paused": allowed})
    result = plan_protective_correction(**args)
    assert result.status == ("READY" if allowed else "UNRESOLVED")
    if allowed:
        assert result.outcome is not None
        assert all(fill.side == "sell" for fill in result.outcome.committed_fills)
    else:
        assert result.reason == "CORRECTION_PAUSED"


@pytest.mark.parametrize("missing", ["open_prices", "execution_listings"])
def test_missing_current_original_evidence_stays_unresolved(missing: str) -> None:
    args = correction_arguments()
    args[missing] = {}
    result = plan_protective_correction(**args)
    assert result.status == "UNRESOLVED"
    assert result.outcome is None and not result.targets


def test_nonbinding_book_does_not_generate_orders_or_fees() -> None:
    args = correction_arguments()
    args["state"] = _state(cash="9000", holdings=(_holding(SEC_A, 10, "1000"),))
    result = plan_protective_correction(**args)
    assert result.status == "NOT_REQUIRED"
    assert result.preview_evaluations == 0
    assert result.outcome is None and not result.targets


@pytest.mark.parametrize("knowledge", ["RESOLVED", "UNKNOWN", "PARTIAL"])
def test_safe_paused_book_needs_no_correction_but_must_have_resolved_execution(
    knowledge: str,
) -> None:
    args = correction_arguments()
    args["state"] = _state(cash="9000", holdings=(_holding(SEC_A, 10, "1000"),))
    args["mandate"] = args["mandate"].model_copy(
        update={"paused": True, "execution_knowledge": knowledge}
    )
    assert not args["policy"].allow_while_paused
    before = canonical_json(args["state"])
    result = plan_protective_correction(**args)
    if knowledge == "RESOLVED":
        assert result.status == "NOT_REQUIRED"
        assert result.reason == "CORRECTION_NOT_REQUIRED"
        assert result.before_open_nav == Decimal("10000")
        assert result.final_breaches == ()
    else:
        assert result.status == "UNRESOLVED"
        assert result.reason == "CORRECTION_EXECUTION_UNRESOLVED"
        assert result.before_open_nav is None
    assert result.preview_evaluations == 0
    assert result.outcome is None and not result.targets
    assert canonical_json(args["state"]) == before


def test_resource_bound_or_turnover_limit_is_not_a_permission_bypass() -> None:
    for field in ("budget", "turnover"):
        args = correction_arguments()
        if field == "budget":
            args["policy"] = args["policy"].model_copy(
                update={"maximum_preview_evaluations": 1}
            )
        else:
            args["mandate"] = args["mandate"].model_copy(
                update={"maximum_turnover_fraction": Decimal("0.01")}
            )
        before = canonical_json(args["state"])
        result = plan_protective_correction(**args)
        assert result.status == "UNRESOLVED"
        assert result.reason == (
            "CORRECTION_PREVIEW_BUDGET_EXHAUSTED"
            if field == "budget"
            else "CORRECTION_TURNOVER_CAP"
        )
        assert result.preview_evaluations == 1
        assert result.outcome is None and not result.targets
        assert canonical_json(args["state"]) == before


@pytest.mark.parametrize("precision", [3, 9, 28, 60])
def test_protective_policy_is_independent_of_ambient_decimal_precision(
    precision: int,
) -> None:
    args = correction_arguments()
    expected = plan_protective_correction(**args)
    with localcontext() as context:
        context.prec = precision
        actual = plan_protective_correction(**args)
    assert actual == expected


def test_wrong_session_and_invalid_cost_hash_refuse_before_planning() -> None:
    args = correction_arguments()
    values = dict(_session())
    values["session_hash"] = "f" * 64
    args["execution_session"] = type(_session()).model_construct(**values)
    with pytest.raises(ValueError):
        plan_protective_correction(**args)
    args = correction_arguments()
    values = ZERO_COST.model_dump(mode="python")
    values["cost_model_hash"] = "f" * 64
    args["cost_model"] = type(ZERO_COST).model_construct(**values)
    with pytest.raises(ValueError):
        plan_protective_correction(**args)


def test_gross_correction_rechecks_fee_reduced_nav() -> None:
    args = correction_arguments()
    args["state"] = _state(cash="100", holdings=(_holding(SEC_A, 90, "900"),))
    mandate = args["mandate"]
    args["mandate"] = mandate.model_copy(
        update={
            "maximum_gross_fraction": Decimal("0.7"),
            "securities": tuple(
                rule.model_copy(update={"maximum_fraction": Decimal("1")})
                for rule in mandate.securities
            ),
        }
    )
    args["open_prices"] = {SEC_A: _price("10")}
    args["cost_model"] = _cost_model(
        commission="0", fixed_fee="1", notional_bps="0", slippage_bps="0"
    )
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert result.initial_breaches == ("GROSS_CAP",)
    assert result.targets[0].target_quantity == 69
    assert result.projected_open_nav == Decimal("999")


def test_initial_unfunded_one_share_sale_can_be_funded_by_complete_plan() -> None:
    args = correction_arguments()
    args["state"] = _state(cash="0", holdings=(_holding(SEC_A, 100, "1000"),))
    mandate = args["mandate"]
    args["mandate"] = mandate.model_copy(
        update={
            "securities": tuple(
                rule.model_copy(update={"maximum_fraction": Decimal("0.9")})
                for rule in mandate.securities
            )
        }
    )
    args["open_prices"] = {SEC_A: _price("10")}
    args["cost_model"] = _cost_model(
        commission="0", fixed_fee="25", notional_bps="0", slippage_bps="0"
    )
    result = plan_protective_correction(**args)
    assert result.status == "READY"
    assert result.targets[0].target_quantity == 87
    assert result.projected_open_nav == Decimal("975")
    assert result.outcome is not None
    assert result.outcome.state.cash_balance == Decimal("105")
    assert result.outcome.committed_fills[0].transaction_costs == Decimal("25")


@pytest.mark.parametrize("mismatch", ["session", "listing", "extra_quote"])
def test_valid_but_wrong_original_bindings_do_not_authorize_sales(
    mismatch: str,
) -> None:
    args = correction_arguments()
    if mismatch == "session":
        args["execution_session"] = _session(opened=EXEC_OPEN + timedelta(minutes=1))
    elif mismatch == "listing":
        args["open_prices"] = {
            SEC_A: _price("100").model_copy(update={"listing_id": LISTING_OTHER})
        }
    else:
        args["open_prices"] = {SEC_A: _price("100"), SEC_B: _price("100")}
    result = plan_protective_correction(**args)
    assert result.status == "UNRESOLVED"
    assert result.preview_evaluations == 0
    assert result.outcome is None and not result.targets


def test_indeterminate_basis_does_not_become_a_protective_permission_bypass() -> None:
    args = correction_arguments()
    cause = "a" * 64
    holding = (
        args["state"]
        .holdings[0]
        .model_copy(
            update={
                "basis_status": "indeterminate",
                "cost_basis": None,
                "basis_indeterminate_by": (cause,),
            }
        )
    )
    args["state"] = args["state"].model_copy(
        update={"holdings": (holding,), "applied_effect_ids": (cause,)}
    )
    result = plan_protective_correction(**args)
    assert result.status == "UNRESOLVED"
    assert result.reason == "CORRECTION_ACCOUNTING_UNRESOLVED"
    assert result.outcome is None and not result.targets


def test_disabled_policy_and_invalid_computational_bound_cannot_enable_correction() -> (
    None
):
    args = correction_arguments()
    args["policy"] = args["policy"].model_copy(update={"enabled": False})
    result = plan_protective_correction(**args)
    assert result.status == "UNRESOLVED"
    assert result.reason == "CORRECTION_DISABLED"
    for bound in (0, 4097, True):
        with pytest.raises(ValueError):
            ProtectiveCorrectionPolicyV1(
                enabled=True,
                allow_while_paused=False,
                maximum_preview_evaluations=bound,
            )
