"""Unit tests for reference baseline predictor adapters (M4-4, Issue 181)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.analytical_returns import (
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
    analytical_return_series_hash,
)
from drift.domain.predictions import (
    DirectionalPredictionV1,
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.tracking.adapters import (
    B4MomentumPredictor,
    B5LowVolatilityPredictor,
    NullReferencePredictor,
)
from drift.tracking.recorder import PredictionRecorder

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdef")
SEC_1 = UUID("00000000-0000-7000-8000-000000000001")
SEC_2 = UUID("00000000-0000-7000-8000-000000000002")
VENUE = "XNAS"


def _session_key(day_num: int) -> SessionKeyV1:
    day = date(2025, 1, 1) + date.resolution * day_num
    return SessionKeyV1(local_date=day, mic=VENUE, session_scope="regular")


def _build_synthetic_series(
    sec_id: UUID,
    count: int,
    base_price: Decimal = Decimal("100"),
    daily_growth: Decimal = Decimal("0.001"),
) -> AnalyticalReturnSeriesV1:
    sessions: list[AnalyticalReturnSessionV1] = []
    current_price = base_price
    for i in range(count):
        if i == 0:
            ret = None
        else:
            ret = daily_growth
            current_price = current_price * (Decimal("1") + daily_growth)

        sessions.append(
            AnalyticalReturnSessionV1(
                session_key=_session_key(i),
                unadjusted_close=current_price,
                analytical_close=current_price,
                return_from_prior=ret,
                cumulative_split_factor=Decimal("1"),
            )
        )

    interval = (sessions[0].session_key, sessions[-1].session_key)
    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=sec_id,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        sessions=tuple(sessions),
        lookback_interval=interval,
        source_observation_hashes=(),
        applied_effect_hashes=(),
        acknowledged_limitations=(),
        series_hash="0" * 64,
    )
    return draft.model_copy(
        update={"series_hash": analytical_return_series_hash(draft)}
    )


def test_b4_momentum_predictor_point() -> None:
    # Build series with 260 sessions
    series_1 = _build_synthetic_series(SEC_1, count=260)
    # Series 2 with insufficient history (100 sessions)
    series_2 = _build_synthetic_series(SEC_2, count=100)

    predictor = B4MomentumPredictor()
    assert predictor.name == "b4_momentum"
    assert predictor.target_type == PredictionTargetType.FORWARD_RETURN

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=21,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 2, 16),
    )

    preds = predictor.predict(
        recorder=recorder,
        securities=[SEC_1, SEC_2],
        analytical_series={SEC_1: series_1, SEC_2: series_2},
        target_horizon=h,
    )

    # Only SEC_1 is eligible (has >= 253 sessions)
    assert len(preds) == 1
    assert preds[0].security_id == SEC_1
    assert preds[0].target_type == PredictionTargetType.FORWARD_RETURN
    assert isinstance(preds[0].prediction_value, ScalarPointPredictionV1)

    # Momentum should be positive with daily_growth = 0.001
    assert preds[0].prediction_value.point_value > Decimal("0")


def test_b4_momentum_predictor_directional() -> None:
    series_1 = _build_synthetic_series(SEC_1, count=260)
    predictor = B4MomentumPredictor(emit_directional=True)
    assert predictor.target_type == PredictionTargetType.DIRECTIONAL_RETURN

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=21,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 2, 16),
    )

    preds = predictor.predict(
        recorder=recorder,
        securities=[SEC_1],
        analytical_series={SEC_1: series_1},
        target_horizon=h,
    )

    assert len(preds) == 1
    assert preds[0].target_type == PredictionTargetType.DIRECTIONAL_RETURN
    assert isinstance(preds[0].prediction_value, DirectionalPredictionV1)
    assert preds[0].prediction_value.direction == "up"
    assert preds[0].prediction_value.confidence > Decimal("0")


def test_b5_low_volatility_predictor() -> None:
    # 70 sessions: eligible for 60-session low vol
    series_1 = _build_synthetic_series(SEC_1, count=70)
    # 40 sessions: ineligible
    series_2 = _build_synthetic_series(SEC_2, count=40)

    predictor = B5LowVolatilityPredictor()
    assert predictor.name == "b5_low_volatility"
    assert predictor.target_type == PredictionTargetType.REALIZED_VOLATILITY

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=21,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 2, 16),
    )

    preds = predictor.predict(
        recorder=recorder,
        securities=[SEC_1, SEC_2],
        analytical_series={SEC_1: series_1, SEC_2: series_2},
        target_horizon=h,
    )

    assert len(preds) == 1
    assert preds[0].security_id == SEC_1
    assert preds[0].target_type == PredictionTargetType.REALIZED_VOLATILITY
    assert isinstance(preds[0].prediction_value, ScalarPointPredictionV1)
    # Since all returns were identical (daily_growth=0.001), volatility is 0
    assert preds[0].prediction_value.point_value == Decimal("0")


def test_null_reference_predictor() -> None:
    predictor = NullReferencePredictor()
    assert predictor.name == "null_reference"
    assert predictor.target_type == PredictionTargetType.FORWARD_RETURN

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )

    preds = predictor.predict(
        recorder=recorder,
        securities=[SEC_1, SEC_2],
        analytical_series={},
        target_horizon=h,
        as_of_time=datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC),
    )

    assert len(preds) == 2
    assert preds[0].prediction_value == ScalarPointPredictionV1(
        point_value=Decimal("0.0")
    )
    assert preds[1].prediction_value == ScalarPointPredictionV1(
        point_value=Decimal("0.0")
    )
