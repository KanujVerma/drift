"""Exact cost supersession and trial arithmetic, without financial authority."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any
from uuid import uuid7

import pytest

from drift.experiments.stage1_trial_projection import (
    ControlledTrialProjectionV1,
    ExactRatioV1,
    OperatingCostProjectionV1,
    make_trial_projection,
    project_operating_costs,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    CostReceipt,
    Scope,
    StoredArtifactRef,
)
from drift.intelligence.receipts import create_cost_receipt
from drift.loop.stage1_controlled_contracts import OriginalReferenceV1
from drift.serialization.canonical import content_hash

BASE = datetime(2026, 10, 25, tzinfo=UTC)


def receipt(
    ident: str = "cost",
    *,
    amount: str | None = "8",
    basis: Any = "estimate",
    supersedes: str | None = None,
) -> CostReceipt:
    return create_cost_receipt(
        receipt_id=ident,
        scope=Scope(
            experiment_id="campaign",
            arm_id="B",
            account_id="account-B",
            campaign_ref=ArtifactReference(id="campaign", version="1", sha256="a" * 64),
        ),
        category="model_inference",
        billing_identity="synthetic-fixture",
        amount_basis=basis,
        attempt_id="attempt",
        amount=amount,
        currency=None if basis == "unknown" else "USD",
        unknown_reason="Missing original bill" if basis == "unknown" else None,
        raw_evidence_ref=StoredArtifactRef(
            artifact_id="synthetic-bill:" + ident,
            kind="other",
            content_hash=content_hash({"id": ident, "amount": amount}),
            location="synthetic://bill",
        ),
        recorded_at=BASE + timedelta(seconds=1 if supersedes else 0),
        supersedes_receipt_id=supersedes,
    )


def projection(**overrides: Any) -> ControlledTrialProjectionV1:
    ref = OriginalReferenceV1(event_id=uuid7(), event_hash="b" * 64)
    args: dict[str, Any] = dict(
        campaign_id="campaign",
        run_id="run",
        arm_id="B",
        account_id="account-B",
        checkpoint_id="checkpoint",
        trial_id="trial",
        manifest_hash="a" * 64,
        original_allocation=ref,
        original_result=ref,
        snapshot_tip=ref,
        original_event_hashes=("c" * 64,),
        start_session_index=1,
        end_session_index=2,
        outcome="COMPLETED",
        complete_interval=True,
        selected_family="B3",
        start_nav=Decimal("3"),
        end_nav=Decimal("4"),
        trading_costs=Decimal("0.2"),
        costs=(receipt(amount="0", basis="verified_zero"),),
        reason="Synthetic originals",
    )
    return make_trial_projection(**(args | overrides))


def test_late_actual_cost_replaces_estimate_without_erasing_originals() -> None:
    estimated, actual = (
        receipt(),
        receipt("actual", amount="9", basis="actual", supersedes="cost"),
    )
    old = project_operating_costs((estimated,))
    new = project_operating_costs((estimated, actual))
    assert old.status == "ESTIMATED" and old.amount == Decimal("8")
    assert new.status == "ACTUAL" and new.amount == Decimal("9")
    assert new.original_receipt_hashes == (estimated.record_hash, actual.record_hash)
    assert new.effective_receipt_hashes == (actual.record_hash,)


def test_cost_absence_and_unknown_are_not_zero() -> None:
    for costs in ((), (receipt(amount=None, basis="unknown"),)):
        result = projection(costs=costs)
        assert result.operating_cost.status == "UNAVAILABLE"
        assert result.economic_gain is None and result.economic_return is None
        assert result.net_investment_gain == Decimal("1")


def test_trading_cost_already_in_nav_is_not_subtracted_again() -> None:
    result = projection(costs=(receipt(amount="0.3"),))
    assert result.net_investment_gain == Decimal("1")
    assert result.economic_gain == Decimal("0.7")
    assert result.net_investment_return is not None
    assert result.net_investment_return.as_fraction() == Fraction(1, 3)


def test_retained_incumbent_preserves_real_loss_and_cost_without_new_selection() -> (
    None
):
    result = projection(
        outcome="RETAINED",
        selected_family=None,
        reason="RESEARCH_ABSTAIN",
        start_nav=Decimal("10000"),
        end_nav=Decimal("9980"),
        costs=(receipt(amount="25", basis="actual"),),
    )
    assert result.net_investment_gain == Decimal("-20")
    assert result.economic_gain == Decimal("-45")
    assert result.selected_family is None
    assert result.reason == "RESEARCH_ABSTAIN"
    assert (
        ControlledTrialProjectionV1.model_validate_json(result.model_dump_json())
        == result
    )
    assert not result.scientifically_qualified and not result.authorizes_trading


@pytest.mark.parametrize("precision", [1, 2, 7, 28, 100])
def test_nonterminating_return_and_cost_sum_are_exact_at_every_decimal_precision(
    precision: int,
) -> None:
    with localcontext() as context:
        context.prec = precision
        result = projection(costs=(receipt(amount="0.12345678901234567890123456789"),))
        assert result.net_investment_return == ExactRatioV1(numerator=1, denominator=3)
        assert result.economic_gain == Decimal("0.87654321098765432109876543211")


@pytest.mark.parametrize(
    "changes",
    [
        {"net_investment_gain": Decimal("2")},
        {"economic_gain": Decimal("2")},
        {"net_investment_return": ExactRatioV1(numerator=2, denominator=3)},
        {"end_nav": Decimal("5")},
        {"start_nav": Decimal("0")},
        {"end_session_index": 1},
        {"trading_costs": Decimal("-1")},
        {"original_result": None},
        {"outcome": "UNRESOLVED"},
        {"original_event_hashes": ("c" * 64, "c" * 64)},
    ],
)
def test_self_rehashed_false_trial_arithmetic_or_completeness_refuses(
    changes: dict[str, Any],
) -> None:
    value = projection().model_dump(mode="python") | changes
    value.pop("projection_hash")
    value["projection_hash"] = content_hash(value)
    with pytest.raises(ValueError):
        ControlledTrialProjectionV1.model_validate(value)


@pytest.mark.parametrize(
    "basis,amount",
    [
        ("UNAVAILABLE", Decimal("0")),
        ("VERIFIED_ZERO", Decimal("1")),
        ("ACTUAL", Decimal("-1")),
        ("ACTUAL", None),
        ("ESTIMATED", Decimal("NaN")),
    ],
)
def test_contradictory_cost_shape_refuses(basis: Any, amount: Decimal | None) -> None:
    with pytest.raises(ValueError):
        OperatingCostProjectionV1(
            status=basis,
            amount=amount,
            original_receipt_hashes=("a" * 64,),
            effective_receipt_hashes=("a" * 64,),
        )


def test_duplicate_or_competing_cost_corrections_refuse() -> None:
    initial = receipt()
    actual = receipt("actual", amount="9", basis="actual", supersedes="cost")
    competing = receipt("other", amount="10", basis="actual", supersedes="cost")
    for costs in ((initial, initial), (initial, actual, competing), (actual,)):
        with pytest.raises(ValueError):
            project_operating_costs(costs)
