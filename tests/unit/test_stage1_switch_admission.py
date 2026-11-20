"""Synthetic consumer checks for #423; no orders, accounts or sources are live."""

from datetime import timedelta
from decimal import Decimal
from functools import cache
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
import test_stage1_switch_preflight as k0

from drift.domain.evaluator_portfolio import SecurityHoldingV2
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionIntentV1,
    position_view,
)
from drift.loop.stage1_switch_admission import (
    AdmissionStatus,
    admit_stage1_switch,
)
from drift.loop.stage1_switch_preflight import (
    Stage1SwitchPreflightResult,
    compute_preflight_hash,
    evaluate_stage1_switch_preflight,
)


@cache
def fixture_inputs(
    lane: str = "strong", count: int = 1, proposed: str = "B3"
) -> dict[str, Any]:
    fixture = k0.TestStage1SwitchPreflight()
    fixture.setUp()
    holding = SecurityHoldingV2(
        security_id=fixture.etf_uuids["VOO"],
        quantity=2,
        basis_status="known",
        cost_basis=Decimal("1000.00"),
    )
    portfolio = fixture._make_valid_portfolio_state(
        cash_balance=Decimal("99000.00"),
        holdings=(holding,),
        mark_prices={holding.security_id: Decimal("500.00")},
    )
    builder = (
        fixture._build_strong_lane_context
        if lane == "strong"
        else fixture._build_context
    )
    context = builder(session_count=count, holdings=(position_view(holding),))
    return dict(
        proposed_strategy=proposed,
        current_strategy="B3",
        decision_context=context,
        current_portfolio_state=portfolio,
        required_universe=fixture.admitted_uuids,
        expected_universe_hash=fixture.cohort_hash,
        universe_manifest=dict(fixture.universe_manifest),
        account_id="account-alpha",
        mandate="balanced_stage1",
        open_orders=(),
        mandate_verified=True,
        risk_verified=True,
        completed_sessions=tuple(fixture.completed_sessions),
        adjustments_by_security=dict(fixture.valid_adjustments),
    )


def intent_for(inputs: dict[str, Any]) -> StrategyDecisionIntentV1:
    context = inputs["decision_context"]
    # An admitted positive IJH allocation intentionally exits the held VOO.
    return StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=(
            SecurityTargetPositionV1(
                security_id=inputs["required_universe"][1], target_quantity=3
            ),
        ),
    )


def call(
    inputs: dict[str, Any],
    *,
    changes: dict[str, Any] | None = None,
    intent: StrategyDecisionIntentV1 | None = None,
) -> Any:
    original = dict(inputs)
    preflight = evaluate_stage1_switch_preflight(**original)
    return admit_stage1_switch(
        preflight=preflight,
        intent=intent if intent is not None else intent_for(inputs),
        **{**original, **(changes or {})},
    )


def corrupt(model: Any, **updates: Any) -> Any:
    """Forge only negative inputs; normal FrozenModel.model_copy validates."""
    fields = {name: getattr(model, name) for name in type(model).model_fields}
    return type(model).model_construct(**{**fields, **updates})


@pytest.mark.parametrize("lane", ["strong", "exploratory"])
@pytest.mark.parametrize(
    ("proposed", "count", "admitted"),
    [("B4", 252, False), ("B4", 253, True), ("B5", 60, False), ("B5", 61, True)],
)
def test_real_producer_history_boundaries(
    lane: str, proposed: str, count: int, admitted: bool
) -> None:
    inputs = fixture_inputs(lane, count, proposed)
    before = inputs["current_portfolio_state"].model_dump_json()
    result = call(inputs)
    assert (result.status == AdmissionStatus.ADMITTED) is admitted
    assert result.hold_incumbent is (not admitted)
    assert not result.requires_containment
    if admitted:
        assert [(t.security_id, t.target_quantity) for t in result.staged_targets] == [
            (inputs["required_universe"][0], 0),
            (inputs["required_universe"][1], 3),
        ]
    else:
        assert result.staged_targets == ()
    assert inputs["current_portfolio_state"].model_dump_json() == before


@pytest.mark.parametrize("proposed", ["ABSTAIN", "B0", "unknown"])
def test_noneligible_results_never_call_either_stager(proposed: str) -> None:
    inputs = fixture_inputs("strong", 1, proposed)
    with (
        patch("drift.loop.stage1_switch_admission.stage_decision_targets") as strong,
        patch(
            "drift.loop.stage1_switch_admission.stage_exploratory_decision_targets"
        ) as exploratory,
    ):
        result = call(inputs)
    assert result.status == AdmissionStatus.REFUSED
    assert result.hold_incumbent
    assert result.staged_targets == ()
    strong.assert_not_called()
    exploratory.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other-account"},
        {"mandate": "other-mandate"},
        {"risk_verified": False},
        {"mandate_verified": None},
        {"open_orders": None},
        {"open_orders": ("UNKNOWN",)},
        {"open_orders": ("PARTIALLY_FILLED",)},
        {"open_orders": ("UNFILLED",)},
        {"current_strategy": None},
        {"current_strategy": "B5"},
        {"current_portfolio_state": None},
        {"decision_context": None},
        {"expected_universe_hash": "0" * 64},
        {"universe_manifest": None},
        {"completed_sessions": None},
        {"proposed_strategy": "B4"},
    ],
)
def test_stale_or_incomplete_evidence_never_stages(changes: dict[str, Any]) -> None:
    inputs = fixture_inputs()
    with patch("drift.loop.stage1_switch_admission.stage_decision_targets") as staging:
        result = call(inputs, changes=changes)
    assert result.status == AdmissionStatus.CONTAINMENT
    assert not result.hold_incumbent
    assert result.requires_containment
    assert result.staged_targets == ()
    staging.assert_not_called()


def test_changed_cash_and_cutoff_are_not_a_replay() -> None:
    inputs = fixture_inputs()
    for changes in (
        {
            "current_portfolio_state": corrupt(
                inputs["current_portfolio_state"], cash_balance=Decimal("98999.00")
            )
        },
        {
            "decision_context": corrupt(
                inputs["decision_context"],
                decision_cutoff=inputs["decision_context"].decision_cutoff
                + timedelta(seconds=1),
            )
        },
        {"required_universe": inputs["required_universe"][:-1]},
        {
            "required_universe": (
                inputs["required_universe"][0],
                *inputs["required_universe"][:-1],
            )
        },
    ):
        result = call(inputs, changes=changes)
        assert result.status == AdmissionStatus.CONTAINMENT
        assert not result.hold_incumbent
        assert not result.staged_targets


@pytest.mark.parametrize("targets", [(), (0,), (True,), (1.5,), (-1,)])
def test_empty_cash_only_or_forged_quantities_are_refused(
    targets: tuple[object, ...],
) -> None:
    inputs = fixture_inputs()
    intent = corrupt(
        intent_for(inputs),
        targets=tuple(
            SecurityTargetPositionV1.model_construct(
                security_id=inputs["required_universe"][1],
                target_quantity=quantity,
            )
            for quantity in targets
        ),
    )
    result = call(inputs, intent=intent)
    assert result.status == AdmissionStatus.REFUSED
    assert not result.staged_targets


def test_duplicate_and_stale_targets_are_refused() -> None:
    inputs = fixture_inputs()
    intent = intent_for(inputs)
    for bad_intent in (
        corrupt(intent, targets=intent.targets * 2),
        corrupt(intent, decision_time=intent.decision_time - timedelta(seconds=1)),
    ):
        result = call(inputs, intent=bad_intent)
        assert result.status == AdmissionStatus.REFUSED
        assert not result.staged_targets


def test_tampered_verdict_flags_cannot_authorize_staging() -> None:
    inputs = fixture_inputs("strong", 1, "ABSTAIN")
    verdict = evaluate_stage1_switch_preflight(**inputs)
    result = admit_stage1_switch(
        preflight=corrupt(verdict, is_tradeable=True),
        intent=intent_for(inputs),
        **inputs,
    )
    assert result.status == AdmissionStatus.CONTAINMENT
    assert not result.hold_incumbent
    assert not result.staged_targets


def test_missing_intent_is_explicit_refusal_and_repeat_is_pure() -> None:
    inputs = fixture_inputs()
    verdict = evaluate_stage1_switch_preflight(**inputs)
    result = admit_stage1_switch(preflight=verdict, intent=None, **inputs)
    assert result.status == AdmissionStatus.REFUSED
    assert not result.staged_targets
    assert call(inputs) == call(inputs)


def test_missing_required_fund_is_refused_without_staging_or_mutation() -> None:
    inputs = dict(fixture_inputs())
    original_context = inputs["decision_context"]
    inputs["decision_context"] = original_context.model_copy(
        update={"decision_views": original_context.decision_views[:-1]}
    )
    before = inputs["current_portfolio_state"].model_dump_json()
    with patch("drift.loop.stage1_switch_admission.stage_decision_targets") as staging:
        result = call(inputs)
    assert result.status == AdmissionStatus.REFUSED
    assert result.hold_incumbent
    assert not result.staged_targets
    assert inputs["current_portfolio_state"].model_dump_json() == before
    staging.assert_not_called()
    stale = call(
        fixture_inputs(), changes={"decision_context": inputs["decision_context"]}
    )
    assert stale.status == AdmissionStatus.CONTAINMENT
    assert not stale.hold_incumbent


def test_rehashed_claim_cannot_replace_the_current_producer_outcome() -> None:
    inputs = fixture_inputs()
    verdict = evaluate_stage1_switch_preflight(**inputs)
    fields = {name: getattr(verdict, name) for name in type(verdict).model_fields}
    fields.pop("schema_version")
    fields.pop("preflight_hash")
    fields.update(proposed_strategy="B5", effective_strategy="B5")
    forged = Stage1SwitchPreflightResult(
        **fields, preflight_hash=compute_preflight_hash(**fields)
    )
    result = admit_stage1_switch(preflight=forged, intent=intent_for(inputs), **inputs)
    assert result.status == AdmissionStatus.CONTAINMENT
    assert not result.staged_targets


def test_unadmitted_positive_target_refused_by_existing_stager() -> None:
    inputs = fixture_inputs()
    intent = intent_for(inputs).model_copy(
        update={
            "targets": (
                SecurityTargetPositionV1(
                    security_id=UUID("018e0000-0000-7000-8000-000000009999"),
                    target_quantity=1,
                ),
            )
        }
    )
    result = call(inputs, intent=intent)
    assert result.status == AdmissionStatus.REFUSED
    assert not result.staged_targets


def test_stateful_collection_cannot_hide_unknown_open_order() -> None:
    class EmptyLookingOrders(list[str]):
        def __len__(self) -> int:
            return 0

    result = call(
        fixture_inputs(), changes={"open_orders": EmptyLookingOrders(["UNKNOWN"])}
    )
    assert result.status == AdmissionStatus.CONTAINMENT
    assert not result.hold_incumbent
    assert not result.staged_targets


@pytest.mark.parametrize("kind", ["conflicting", "duplicate", "shared_symbol"])
def test_ambiguous_manifest_identity_cannot_be_overwritten(kind: str) -> None:
    inputs = fixture_inputs()
    manifest = dict(inputs["universe_manifest"])
    voo = inputs["required_universe"][0]
    if kind == "conflicting":
        manifest[voo] = "NOT_A_STAGE1_ETF"
        manifest["VOO"] = voo
    elif kind == "duplicate":
        manifest["VOO"] = voo
    else:
        manifest[UUID("018e0000-0000-7000-8000-000000009999")] = "vOo"
    with patch("drift.loop.stage1_switch_admission.stage_decision_targets") as staging:
        result = call(inputs, changes={"universe_manifest": manifest})
    assert result.status == AdmissionStatus.CONTAINMENT
    assert not result.hold_incumbent
    assert not result.staged_targets
    staging.assert_not_called()


@pytest.mark.parametrize("lane", ["strong", "exploratory"])
def test_manifest_direction_and_universe_order_preserve_valid_selection(
    lane: str,
) -> None:
    inputs = dict(fixture_inputs(lane))
    expected = call(inputs)
    intent = intent_for(inputs)
    inputs["universe_manifest"] = {
        symbol.lower(): security
        for security, symbol in inputs["universe_manifest"].items()
    }
    inputs["required_universe"] = tuple(reversed(inputs["required_universe"]))
    result = call(inputs, intent=intent)
    assert result.status == AdmissionStatus.ADMITTED
    assert result.staged_targets == expected.staged_targets
