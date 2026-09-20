"""Domain models for M2 evaluation cost and slippage models."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import ValidationInfo, field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.serialization.canonical import content_hash


def evaluation_cost_model_hash(model: EvaluationCostModelV1) -> SHA256Hash:
    """Compute canonical content hash for EvaluationCostModelV1."""
    dump = model.model_dump(mode="python")
    dump.pop("cost_model_hash", None)
    return content_hash(dump)


class EvaluationCostModelV1(FrozenModel):
    """Model parameterizing transaction costs, fees, and adverse execution slippage."""

    schema_version: Literal["1"] = "1"
    model_id: NonBlankStr
    commission_per_share: Decimal = Decimal("0.00")
    fixed_fee_per_order: Decimal = Decimal("0.00")
    notional_fee_basis_points: Decimal = Decimal("0.00")
    adverse_slippage_basis_points: Decimal = Decimal("0.00")
    cost_model_hash: SHA256Hash

    @field_validator(
        "commission_per_share",
        "fixed_fee_per_order",
        "notional_fee_basis_points",
        "adverse_slippage_basis_points",
        mode="before",
    )
    @classmethod
    def require_exact_cost_decimal(cls, value: object, info: ValidationInfo) -> Decimal:
        field_name = info.field_name or "cost field"
        if info.mode == "json" and isinstance(value, str):
            try:
                parsed = Decimal(value)
            except (ArithmeticError, ValueError) as error:
                raise ValueError(
                    f"{field_name} requires an exact decimal string"
                ) from error
            if parsed.is_finite():
                return parsed
        elif info.mode == "python" and isinstance(value, Decimal):
            if value.is_finite():
                return value
        raise ValueError(f"{field_name} requires an exact decimal value")

    @model_validator(mode="after")
    def validate_costs(self) -> Self:
        if self.commission_per_share < Decimal("0.00"):
            raise ValueError("commission_per_share must be non-negative")
        if self.fixed_fee_per_order < Decimal("0.00"):
            raise ValueError("fixed_fee_per_order must be non-negative")
        if self.notional_fee_basis_points < Decimal("0.00"):
            raise ValueError("notional_fee_basis_points must be non-negative")
        if self.adverse_slippage_basis_points < Decimal("0.00"):
            raise ValueError("adverse_slippage_basis_points must be non-negative")
        if self.adverse_slippage_basis_points >= Decimal("10000.00"):
            raise ValueError(
                "adverse_slippage_basis_points must be strictly less than "
                "10000 basis points"
            )
        expected = evaluation_cost_model_hash(self)
        if self.cost_model_hash != expected:
            raise ValueError(
                f"cost model hash mismatch: expected {expected}, "
                f"got {self.cost_model_hash}"
            )
        return self
