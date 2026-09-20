"""Unit tests for M2 evaluation cost and slippage models."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)

H0 = "0" * 64
H1 = "1" * 64


def test_cost_model_valid_and_hash_verification() -> None:
    unhashed = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="zero_cost_v1",
        commission_per_share=Decimal("0.00"),
        fixed_fee_per_order=Decimal("0.00"),
        notional_fee_basis_points=Decimal("0.00"),
        adverse_slippage_basis_points=Decimal("0.00"),
        cost_model_hash=H0,
    )
    expected_hash = evaluation_cost_model_hash(unhashed)
    model = unhashed.model_copy(update={"cost_model_hash": expected_hash})

    assert model.schema_version == "1"
    assert model.model_id == "zero_cost_v1"
    assert model.commission_per_share == Decimal("0.00")
    assert model.fixed_fee_per_order == Decimal("0.00")
    assert model.notional_fee_basis_points == Decimal("0.00")
    assert model.adverse_slippage_basis_points == Decimal("0.00")
    assert model.cost_model_hash == expected_hash


def test_cost_model_positive_values_and_hash_sensitivity() -> None:
    unhashed_1 = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="linear_cost_v1",
        commission_per_share=Decimal("0.005"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("5.0"),
        adverse_slippage_basis_points=Decimal("10.0"),
        cost_model_hash=H0,
    )
    h1 = evaluation_cost_model_hash(unhashed_1)
    m1 = unhashed_1.model_copy(update={"cost_model_hash": h1})

    unhashed_2 = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="linear_cost_v1",
        commission_per_share=Decimal("0.005"),
        fixed_fee_per_order=Decimal("1.00"),
        notional_fee_basis_points=Decimal("5.0"),
        adverse_slippage_basis_points=Decimal("10.1"),
        cost_model_hash=H0,
    )
    h2 = evaluation_cost_model_hash(unhashed_2)
    assert h1 != h2
    assert m1.cost_model_hash == h1


def test_cost_model_negative_values_rejected() -> None:
    with pytest.raises(ValidationError, match="commission_per_share"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            commission_per_share=Decimal("-0.01"),
            cost_model_hash=H1,
        )

    with pytest.raises(ValidationError, match="fixed_fee_per_order"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            fixed_fee_per_order=Decimal("-1.00"),
            cost_model_hash=H1,
        )

    with pytest.raises(ValidationError, match="notional_fee_basis_points"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            notional_fee_basis_points=Decimal("-0.1"),
            cost_model_hash=H1,
        )

    with pytest.raises(ValidationError, match="adverse_slippage_basis_points"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            adverse_slippage_basis_points=Decimal("-1.0"),
            cost_model_hash=H1,
        )


def test_cost_model_slippage_upper_bound() -> None:
    # 9999 bps is accepted (< 10000)
    unhashed = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id="high_slippage",
        adverse_slippage_basis_points=Decimal("9999"),
        cost_model_hash=H0,
    )
    h = evaluation_cost_model_hash(unhashed)
    m = unhashed.model_copy(update={"cost_model_hash": h})
    assert m.adverse_slippage_basis_points == Decimal("9999")

    # 10000 bps is rejected
    with pytest.raises(ValidationError, match="adverse_slippage_basis_points"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_slippage",
            adverse_slippage_basis_points=Decimal("10000"),
            cost_model_hash=H1,
        )

    # > 10000 bps is rejected
    with pytest.raises(ValidationError, match="adverse_slippage_basis_points"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_slippage",
            adverse_slippage_basis_points=Decimal("15000"),
            cost_model_hash=H1,
        )


def test_cost_model_exact_decimal_required() -> None:
    # float is rejected
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            commission_per_share=0.01,  # type: ignore[arg-type]
            cost_model_hash=H1,
        )

    # NaN / Inf is rejected
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="bad_model",
            commission_per_share=Decimal("NaN"),
            cost_model_hash=H1,
        )


def test_cost_model_tampered_hash_rejected() -> None:
    with pytest.raises(ValidationError, match="cost model hash mismatch"):
        EvaluationCostModelV1(
            schema_version="1",
            model_id="linear_cost_v1",
            commission_per_share=Decimal("0.005"),
            cost_model_hash=H1,
        )


def test_cost_model_non_finite_rejected_for_each_field() -> None:
    fields = (
        "commission_per_share",
        "fixed_fee_per_order",
        "notional_fee_basis_points",
        "adverse_slippage_basis_points",
    )
    for field in fields:
        for bad in (Decimal("Infinity"), Decimal("-Infinity"), float("inf")):
            with pytest.raises(ValidationError, match="exact decimal"):
                EvaluationCostModelV1(
                    schema_version="1",
                    model_id="bad_model",
                    cost_model_hash=H1,
                    **{field: bad},  # type: ignore[arg-type]
                )


def test_cost_model_hash_changes_with_each_cost_input() -> None:
    base: dict[str, Any] = {
        "schema_version": "1",
        "model_id": "linear_cost_v1",
        "commission_per_share": Decimal("0.005"),
        "fixed_fee_per_order": Decimal("1.00"),
        "notional_fee_basis_points": Decimal("5.0"),
        "adverse_slippage_basis_points": Decimal("10.0"),
        "cost_model_hash": H0,
    }
    baseline = evaluation_cost_model_hash(EvaluationCostModelV1.model_construct(**base))
    for field, replacement in (
        ("commission_per_share", Decimal("0.006")),
        ("fixed_fee_per_order", Decimal("1.01")),
        ("notional_fee_basis_points", Decimal("5.01")),
        ("adverse_slippage_basis_points", Decimal("10.01")),
        ("model_id", "alt_cost_model_v1"),
    ):
        alt_hash = evaluation_cost_model_hash(
            EvaluationCostModelV1.model_construct(**{**base, field: replacement})
        )
        assert alt_hash != baseline
