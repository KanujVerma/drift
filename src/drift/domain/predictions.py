"""Ex-ante prediction domain contracts and ledger validation (M4-1, Issue 175).

Provides immutable domain models for ex-ante quantitative predictions,
target horizon specifications, payload models (point, directional, quantile),
content hashing, and atomic prediction sets sealed into the M0 ledger.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    SHA256Hash,
    UTCDateTime,
)
from drift.serialization.canonical import content_hash

PREDICTIONS_SCHEMA_VERSION: Literal["1"] = "1"


class PredictionTargetType(StrEnum):
    """Admitted quantitative prediction target types."""

    FORWARD_RETURN = "forward_return"
    DIRECTIONAL_RETURN = "directional_return"
    REALIZED_VOLATILITY = "realized_volatility"
    CROSS_SECTIONAL_RANK = "cross_sectional_rank"
    EXCESS_RETURN = "excess_return"


class HorizonSpecificationV1(FrozenModel):
    """Immutable specification of the forward evaluation horizon."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    horizon_sessions: int
    anchor_session_date: date
    start_session_date: date
    end_session_date: date

    @model_validator(mode="after")
    def validate_horizon(self) -> Self:
        if self.horizon_sessions < 1:
            raise ValueError("horizon sessions must be at least 1")
        if self.start_session_date <= self.anchor_session_date:
            raise ValueError("start session date must be strictly after anchor")
        if self.end_session_date < self.start_session_date:
            raise ValueError("end session date cannot precede start")
        return self


class ScalarPointPredictionV1(FrozenModel):
    """Single scalar expected value (e.g. predicted return +0.0245)."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    kind: Literal["scalar_point"] = "scalar_point"
    point_value: Decimal

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if not self.point_value.is_finite():
            raise ValueError("point value must be finite")
        return self


class DirectionalPredictionV1(FrozenModel):
    """Categorical directional prediction with confidence."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    kind: Literal["directional"] = "directional"
    direction: Literal["up", "down", "flat"]
    confidence: Decimal

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if not (Decimal("0") <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be between 0 and 1")
        return self


class QuantileDistributionPredictionV1(FrozenModel):
    """Quantile distribution predictions (e.g. p10, p50, p90)."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    kind: Literal["quantile_distribution"] = "quantile_distribution"
    quantiles: tuple[tuple[Decimal, Decimal], ...]

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if not self.quantiles:
            raise ValueError("quantiles must not be empty")
        prior_q: Decimal | None = None
        prior_v: Decimal | None = None
        for q, v in self.quantiles:
            if not (Decimal("0") <= q <= Decimal("1")):
                raise ValueError("quantile probabilities must be between 0 and 1")
            if not v.is_finite():
                raise ValueError("quantile values must be finite")
            if prior_q is not None and q <= prior_q:
                raise ValueError("quantiles must be strictly ascending")
            if prior_v is not None and v < prior_v:
                raise ValueError("quantile values must be non-decreasing")
            prior_q = q
            prior_v = v
        return self


type PredictionValueV1 = (
    ScalarPointPredictionV1 | DirectionalPredictionV1 | QuantileDistributionPredictionV1
)


class ExAntePredictionRecordV1(FrozenModel):
    """An individual ex-ante prediction for a specific asset and horizon."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    prediction_id: UUID7
    run_id: UUID7
    security_id: UUID7
    as_of_time: UTCDateTime
    target_type: PredictionTargetType
    target_horizon: HorizonSpecificationV1
    prediction_value: PredictionValueV1
    input_context_hash: SHA256Hash
    model_provenance_hash: SHA256Hash
    prediction_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        expected = compute_prediction_record_hash(self)
        if self.prediction_hash != expected:
            raise ValueError("prediction hash mismatch")
        return self


def compute_prediction_record_hash(
    record: ExAntePredictionRecordV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for an ex-ante prediction record."""
    if isinstance(record, Mapping):
        data = {k: v for k, v in record.items() if k != "prediction_hash"}
    else:
        data = {
            k: v
            for k, v in record.model_dump(mode="python").items()
            if k != "prediction_hash"
        }
    return content_hash(data)


def build_ex_ante_prediction_record(
    *,
    prediction_id: UUID,
    run_id: UUID,
    security_id: UUID,
    as_of_time: Any,
    target_type: PredictionTargetType,
    target_horizon: HorizonSpecificationV1,
    prediction_value: PredictionValueV1,
    input_context_hash: str,
    model_provenance_hash: str,
) -> ExAntePredictionRecordV1:
    """Construct an ExAntePredictionRecordV1 with calculated content hash."""
    unsigned = {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "prediction_id": prediction_id,
        "run_id": run_id,
        "security_id": security_id,
        "as_of_time": as_of_time,
        "target_type": target_type,
        "target_horizon": target_horizon,
        "prediction_value": prediction_value,
        "input_context_hash": input_context_hash,
        "model_provenance_hash": model_provenance_hash,
    }
    p_hash = compute_prediction_record_hash(unsigned)
    return ExAntePredictionRecordV1.model_validate(
        {
            **unsigned,
            "prediction_hash": p_hash,
        }
    )


def _prediction_record_order(
    record: ExAntePredictionRecordV1,
) -> tuple[bytes, str, bytes]:
    return (
        record.security_id.bytes,
        record.target_type.value,
        record.prediction_id.bytes,
    )


class ExAntePredictionSetV1(FrozenModel):
    """Atomic batch of ex-ante predictions emitted at a decision epoch."""

    schema_version: Literal["1"] = PREDICTIONS_SCHEMA_VERSION
    prediction_set_id: UUID7
    run_id: UUID7
    session_date: date
    as_of_time: UTCDateTime
    lane: Literal["exploratory", "promotion"]
    predictions: tuple[ExAntePredictionRecordV1, ...]
    set_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        for p in self.predictions:
            if p.run_id != self.run_id:
                raise ValueError("all predictions must match prediction set run_id")
            if p.as_of_time != self.as_of_time:
                raise ValueError("all predictions must match prediction set as_of_time")
            if p.target_horizon.anchor_session_date != self.session_date:
                raise ValueError(
                    "all prediction horizons must anchor on the set session date"
                )

        pred_ids = [p.prediction_id for p in self.predictions]
        if len(set(pred_ids)) != len(pred_ids):
            raise ValueError("all predictions in a set must have unique prediction_ids")

        ordered = tuple(sorted(self.predictions, key=_prediction_record_order))
        if self.predictions != ordered:
            raise ValueError("predictions must be canonically sorted")

        expected = compute_prediction_set_hash(self)
        if self.set_hash != expected:
            raise ValueError("prediction set hash mismatch")
        return self


def compute_prediction_set_hash(
    pred_set: ExAntePredictionSetV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for an ex-ante prediction set."""
    if isinstance(pred_set, Mapping):
        data = {k: v for k, v in pred_set.items() if k != "set_hash"}
    else:
        data = {
            k: v
            for k, v in pred_set.model_dump(mode="python").items()
            if k != "set_hash"
        }
    return content_hash(data)


def build_ex_ante_prediction_set(
    *,
    prediction_set_id: UUID,
    run_id: UUID,
    session_date: date,
    as_of_time: Any,
    lane: Literal["exploratory", "promotion"],
    predictions: tuple[ExAntePredictionRecordV1, ...] | list[ExAntePredictionRecordV1],
) -> ExAntePredictionSetV1:
    """Construct an ExAntePredictionSetV1 with sorted predictions and hash."""
    ordered = tuple(sorted(predictions, key=_prediction_record_order))
    unsigned = {
        "schema_version": PREDICTIONS_SCHEMA_VERSION,
        "prediction_set_id": prediction_set_id,
        "run_id": run_id,
        "session_date": session_date,
        "as_of_time": as_of_time,
        "lane": lane,
        "predictions": ordered,
    }
    s_hash = compute_prediction_set_hash(unsigned)
    return ExAntePredictionSetV1.model_validate(
        {
            **unsigned,
            "set_hash": s_hash,
        }
    )
