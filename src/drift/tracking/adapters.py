"""Reference baseline predictor adapters for Drift (M4-4, Issue 181).

Provides predictor adapters that generate ex-ante predictions grounded in
historical analytical return series:
- B4MomentumPredictor: Generates forward return predictions based on 12-1 momentum.
- B5LowVolatilityPredictor: Generates forward volatility predictions based on
  60-session variance.
- NullReferencePredictor: Generates zero forward return predictions to anchor
  residual variance.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from drift.domain.analytical_returns import (
    AnalyticalReturnSeriesV1,
    calculate_low_volatility_60,
    calculate_momentum_12_1,
    is_security_eligible_for_lookback,
)
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.predictions import (
    DirectionalPredictionV1,
    ExAntePredictionRecordV1,
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.tracking.recorder import PredictionRecorder


class PredictorAdapter(Protocol):
    """Protocol for ex-ante model predictor adapters."""

    @property
    def name(self) -> str: ...

    @property
    def target_type(self) -> PredictionTargetType: ...

    def predict(
        self,
        *,
        recorder: PredictionRecorder,
        securities: Sequence[UUID],
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        target_horizon: HorizonSpecificationV1,
        as_of_time: datetime | None = None,
    ) -> tuple[ExAntePredictionRecordV1, ...]: ...


class B4MomentumPredictor:
    """Predictor adapter generating 12-1 momentum forward forecasts."""

    def __init__(
        self,
        *,
        name: str = "b4_momentum",
        emit_directional: bool = False,
        min_required_sessions: int = 253,
    ) -> None:
        self._name = name
        self._emit_directional = emit_directional
        self._min_required_sessions = min_required_sessions

    @property
    def name(self) -> str:
        return self._name

    @property
    def target_type(self) -> PredictionTargetType:
        if self._emit_directional:
            return PredictionTargetType.DIRECTIONAL_RETURN
        return PredictionTargetType.FORWARD_RETURN

    def predict(
        self,
        *,
        recorder: PredictionRecorder,
        securities: Sequence[UUID],
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        target_horizon: HorizonSpecificationV1,
        as_of_time: datetime | None = None,
    ) -> tuple[ExAntePredictionRecordV1, ...]:
        """Generate momentum predictions for eligible securities."""
        records: list[ExAntePredictionRecordV1] = []

        for sec_id in securities:
            series = analytical_series.get(sec_id)
            if not is_security_eligible_for_lookback(
                series, self._min_required_sessions
            ):
                continue

            assert series is not None
            try:
                mom_val = calculate_momentum_12_1(series)
            except IndeterminateValuationError:
                continue

            pred_val: DirectionalPredictionV1 | ScalarPointPredictionV1
            if self._emit_directional:
                direction: Literal["up", "down", "flat"]
                if mom_val > Decimal("0"):
                    direction = "up"
                elif mom_val < Decimal("0"):
                    direction = "down"
                else:
                    direction = "flat"

                conf = min(abs(mom_val), Decimal("1.0"))
                pred_val = DirectionalPredictionV1(
                    direction=direction,
                    confidence=conf,
                )
            else:
                pred_val = ScalarPointPredictionV1(point_value=mom_val)

            rec = recorder.record_prediction(
                security_id=sec_id,
                target_type=self.target_type,
                target_horizon=target_horizon,
                prediction_value=pred_val,
                as_of_time=as_of_time,
            )
            records.append(rec)

        return tuple(records)


class B5LowVolatilityPredictor:
    """Predictor adapter generating 60-session historical volatility forecasts."""

    def __init__(
        self,
        *,
        name: str = "b5_low_volatility",
        min_required_sessions: int = 61,
    ) -> None:
        self._name = name
        self._min_required_sessions = min_required_sessions

    @property
    def name(self) -> str:
        return self._name

    @property
    def target_type(self) -> PredictionTargetType:
        return PredictionTargetType.REALIZED_VOLATILITY

    def predict(
        self,
        *,
        recorder: PredictionRecorder,
        securities: Sequence[UUID],
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        target_horizon: HorizonSpecificationV1,
        as_of_time: datetime | None = None,
    ) -> tuple[ExAntePredictionRecordV1, ...]:
        """Generate volatility predictions for eligible securities."""
        records: list[ExAntePredictionRecordV1] = []

        for sec_id in securities:
            series = analytical_series.get(sec_id)
            if not is_security_eligible_for_lookback(
                series, self._min_required_sessions
            ):
                continue

            assert series is not None
            try:
                variance = calculate_low_volatility_60(series)
                vol_val = variance.sqrt()
            except IndeterminateValuationError:
                continue

            pred_val = ScalarPointPredictionV1(point_value=vol_val)
            rec = recorder.record_prediction(
                security_id=sec_id,
                target_type=self.target_type,
                target_horizon=target_horizon,
                prediction_value=pred_val,
                as_of_time=as_of_time,
            )
            records.append(rec)

        return tuple(records)


class NullReferencePredictor:
    """Null reference predictor generating constant zero-return forecasts."""

    def __init__(
        self,
        *,
        name: str = "null_reference",
        constant_value: Decimal = Decimal("0.0"),
    ) -> None:
        self._name = name
        self._constant_value = constant_value

    @property
    def name(self) -> str:
        return self._name

    @property
    def target_type(self) -> PredictionTargetType:
        return PredictionTargetType.FORWARD_RETURN

    def predict(
        self,
        *,
        recorder: PredictionRecorder,
        securities: Sequence[UUID],
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        target_horizon: HorizonSpecificationV1,
        as_of_time: datetime | None = None,
    ) -> tuple[ExAntePredictionRecordV1, ...]:
        """Generate constant forecasts for all given securities."""
        records: list[ExAntePredictionRecordV1] = []

        for sec_id in securities:
            pred_val = ScalarPointPredictionV1(point_value=self._constant_value)
            rec = recorder.record_prediction(
                security_id=sec_id,
                target_type=self.target_type,
                target_horizon=target_horizon,
                prediction_value=pred_val,
                as_of_time=as_of_time,
            )
            records.append(rec)

        return tuple(records)
