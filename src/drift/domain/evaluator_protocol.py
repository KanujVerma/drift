"""Domain model for M2 evaluation protocol."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import ValidationInfo, field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.serialization.canonical import content_hash


def evaluation_protocol_hash(protocol: EvaluationProtocolV1) -> SHA256Hash:
    """Compute canonical content hash for EvaluationProtocolV1."""
    dump = protocol.model_dump(mode="python")
    dump.pop("protocol_hash", None)
    return content_hash(dump)


class EvaluationProtocolV1(FrozenModel):
    """Protocol governing session evaluation cadence, scope, and parameters."""

    schema_version: Literal["1"] = "1"
    protocol_id: NonBlankStr
    decision_clock: Literal["post_close_decision_next_open_execution"] = (
        "post_close_decision_next_open_execution"
    )
    session_scope: Literal["regular"] = "regular"
    warmup_session_count: int
    initial_cash: Decimal
    protocol_hash: SHA256Hash

    @field_validator("initial_cash", mode="before")
    @classmethod
    def require_exact_initial_cash(cls, value: object, info: ValidationInfo) -> Decimal:
        if info.mode == "json" and isinstance(value, str):
            try:
                parsed = Decimal(value)
            except (ArithmeticError, ValueError) as error:
                raise ValueError(
                    "initial_cash requires an exact decimal string"
                ) from error
            if parsed.is_finite():
                return parsed
        elif info.mode == "python" and isinstance(value, Decimal):
            if value.is_finite():
                return value
        raise ValueError("initial_cash requires an exact decimal value")

    @model_validator(mode="after")
    def validate_protocol(self) -> Self:
        if self.warmup_session_count < 1:
            raise ValueError("warmup_session_count must be at least 1")
        if self.initial_cash <= Decimal("0.00"):
            raise ValueError("initial_cash must be strictly positive")
        expected = evaluation_protocol_hash(self)
        if self.protocol_hash != expected:
            raise ValueError(
                f"protocol hash mismatch: expected {expected}, got {self.protocol_hash}"
            )
        return self
