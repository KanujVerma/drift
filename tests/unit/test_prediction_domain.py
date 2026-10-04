"""Unit tests for ex-ante prediction domain contracts (M4-1, Issue 175)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.predictions import (
    DirectionalPredictionV1,
    ExAntePredictionRecordV1,
    HorizonSpecificationV1,
    PredictionTargetType,
    QuantileDistributionPredictionV1,
    ScalarPointPredictionV1,
    build_ex_ante_prediction_record,
    build_ex_ante_prediction_set,
    compute_prediction_record_hash,
    compute_prediction_set_hash,
)
from drift.serialization.canonical import canonical_json

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdef")
PRED_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcde1")
PRED_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcde2")
SET_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcde0")
SEC_A = UUID("00000000-0000-7000-8000-000000000001")
SEC_B = UUID("00000000-0000-7000-8000-000000000002")
HASH_ZERO = "0" * 64
HASH_ONE = "1" * 64
AS_OF = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)


def test_horizon_specification_valid() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    assert horizon.horizon_sessions == 5
    assert horizon.anchor_session_date == date(2026, 1, 15)
    assert horizon.start_session_date == date(2026, 1, 16)
    assert horizon.end_session_date == date(2026, 1, 23)


def test_horizon_specification_rejects_non_positive_sessions() -> None:
    with pytest.raises(ValidationError, match="horizon sessions must be at least 1"):
        HorizonSpecificationV1(
            horizon_sessions=0,
            anchor_session_date=date(2026, 1, 15),
            start_session_date=date(2026, 1, 16),
            end_session_date=date(2026, 1, 23),
        )


def test_horizon_specification_rejects_start_not_after_anchor() -> None:
    with pytest.raises(
        ValidationError, match="start session date must be strictly after anchor"
    ):
        HorizonSpecificationV1(
            horizon_sessions=1,
            anchor_session_date=date(2026, 1, 15),
            start_session_date=date(2026, 1, 15),
            end_session_date=date(2026, 1, 16),
        )


def test_horizon_specification_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError, match="end session date cannot precede start"):
        HorizonSpecificationV1(
            horizon_sessions=1,
            anchor_session_date=date(2026, 1, 15),
            start_session_date=date(2026, 1, 16),
            end_session_date=date(2026, 1, 14),
        )


def test_scalar_point_prediction_valid() -> None:
    pred = ScalarPointPredictionV1(point_value=Decimal("0.025"))
    assert pred.kind == "scalar_point"
    assert pred.point_value == Decimal("0.025")


def test_directional_prediction_valid_and_bounds() -> None:
    pred = DirectionalPredictionV1(direction="up", confidence=Decimal("0.85"))
    assert pred.direction == "up"
    assert pred.confidence == Decimal("0.85")

    with pytest.raises(ValidationError, match="confidence must be between 0 and 1"):
        DirectionalPredictionV1(direction="down", confidence=Decimal("1.05"))

    with pytest.raises(ValidationError, match="confidence must be between 0 and 1"):
        DirectionalPredictionV1(direction="down", confidence=Decimal("-0.01"))


def test_quantile_distribution_prediction_valid() -> None:
    quantiles = (
        (Decimal("0.1"), Decimal("-0.05")),
        (Decimal("0.5"), Decimal("0.01")),
        (Decimal("0.9"), Decimal("0.08")),
    )
    pred = QuantileDistributionPredictionV1(quantiles=quantiles)
    assert len(pred.quantiles) == 3


def test_quantile_distribution_rejects_empty_or_unordered() -> None:
    with pytest.raises(ValidationError, match="quantiles must not be empty"):
        QuantileDistributionPredictionV1(quantiles=())

    with pytest.raises(ValidationError, match="quantiles must be strictly ascending"):
        QuantileDistributionPredictionV1(
            quantiles=(
                (Decimal("0.5"), Decimal("0.01")),
                (Decimal("0.2"), Decimal("-0.05")),
            )
        )

    with pytest.raises(ValidationError, match="quantile values must be non-decreasing"):
        QuantileDistributionPredictionV1(
            quantiles=(
                (Decimal("0.1"), Decimal("0.05")),
                (Decimal("0.9"), Decimal("0.01")),
            )
        )


def test_ex_ante_prediction_record_builder_and_hash() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    payload = ScalarPointPredictionV1(point_value=Decimal("0.035"))
    record = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_1,
        run_id=RUN_ID,
        security_id=SEC_A,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon,
        prediction_value=payload,
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )
    assert record.prediction_id == PRED_ID_1
    assert record.prediction_hash == compute_prediction_record_hash(record)

    # Tampering with prediction_hash raises ValidationError
    with pytest.raises(ValidationError, match="prediction hash mismatch"):
        ExAntePredictionRecordV1(
            prediction_id=PRED_ID_1,
            run_id=RUN_ID,
            security_id=SEC_A,
            as_of_time=AS_OF,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            prediction_value=payload,
            input_context_hash=HASH_ZERO,
            model_provenance_hash=HASH_ONE,
            prediction_hash=HASH_ZERO,
        )


def test_ex_ante_prediction_set_builder_and_invariants() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    rec1 = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_1,
        run_id=RUN_ID,
        security_id=SEC_A,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )
    rec2 = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_2,
        run_id=RUN_ID,
        security_id=SEC_B,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("-0.02")),
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )

    pred_set = build_ex_ante_prediction_set(
        prediction_set_id=SET_ID,
        run_id=RUN_ID,
        session_date=date(2026, 1, 15),
        as_of_time=AS_OF,
        lane="exploratory",
        predictions=(rec2, rec1),  # Out of order to verify canonical sorting
    )
    assert pred_set.prediction_set_id == SET_ID
    assert pred_set.lane == "exploratory"
    assert len(pred_set.predictions) == 2
    # Verify deterministic sorting: SEC_A precedes SEC_B
    assert pred_set.predictions[0].security_id == SEC_A
    assert pred_set.predictions[1].security_id == SEC_B
    assert pred_set.set_hash == compute_prediction_set_hash(pred_set)


def test_ex_ante_prediction_set_rejects_mismatched_run_id() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    other_run_id = UUID("018f3a5b-6c7d-7890-8123-999999999999")
    rec = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_1,
        run_id=other_run_id,
        security_id=SEC_A,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )
    with pytest.raises(
        ValidationError, match="all predictions must match prediction set run_id"
    ):
        build_ex_ante_prediction_set(
            prediction_set_id=SET_ID,
            run_id=RUN_ID,
            session_date=date(2026, 1, 15),
            as_of_time=AS_OF,
            lane="exploratory",
            predictions=(rec,),
        )


def test_ex_ante_prediction_set_rejects_anchor_session_mismatch() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 14),  # mismatched with set session_date 15
        start_session_date=date(2026, 1, 15),
        end_session_date=date(2026, 1, 15),
    )
    rec = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_1,
        run_id=RUN_ID,
        security_id=SEC_A,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=horizon,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )
    with pytest.raises(
        ValidationError,
        match="all prediction horizons must anchor on the set session date",
    ):
        build_ex_ante_prediction_set(
            prediction_set_id=SET_ID,
            run_id=RUN_ID,
            session_date=date(2026, 1, 15),
            as_of_time=AS_OF,
            lane="exploratory",
            predictions=(rec,),
        )


def test_canonical_json_roundtrip() -> None:
    horizon = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    rec = build_ex_ante_prediction_record(
        prediction_id=PRED_ID_1,
        run_id=RUN_ID,
        security_id=SEC_A,
        as_of_time=AS_OF,
        target_type=PredictionTargetType.DIRECTIONAL_RETURN,
        target_horizon=horizon,
        prediction_value=DirectionalPredictionV1(
            direction="up", confidence=Decimal("0.9")
        ),
        input_context_hash=HASH_ZERO,
        model_provenance_hash=HASH_ONE,
    )
    bytes1 = canonical_json(rec)
    bytes2 = canonical_json(rec)
    assert bytes1 == bytes2
    assert len(bytes1) > 0
