"""Unit tests for ex-ante prediction recorder (M4-2, Issue 177)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from drift.domain.predictions import (
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.tracking.recorder import (
    PREDICTION_SET_ENTITY_TYPE,
    PREDICTION_SET_EVENT_TYPE,
    CausalityViolationError,
    DuplicatePredictionError,
    EmptyEpochError,
    PredictionRecorder,
)

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdef")
SEC_1 = UUID("00000000-0000-7000-8000-000000000001")
SEC_2 = UUID("00000000-0000-7000-8000-000000000002")


def test_record_and_seal_epoch_in_memory() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID, lane="exploratory")
    assert recorder.buffered_count == 0

    h = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    rec1 = recorder.record_prediction(
        security_id=SEC_2,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )
    rec2 = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("-0.01")),
    )
    assert recorder.buffered_count == 2
    assert rec1.security_id == SEC_2
    assert rec2.security_id == SEC_1

    as_of = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
    pred_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=as_of,
    )
    assert recorder.buffered_count == 0
    assert len(pred_set.predictions) == 2
    # Canonically sorted: SEC_1 precedes SEC_2
    assert pred_set.predictions[0].security_id == SEC_1
    assert pred_set.predictions[1].security_id == SEC_2
    assert pred_set.session_date == date(2026, 1, 15)
    assert pred_set.as_of_time == as_of
    assert len(recorder.sealed_sets) == 1


def test_seal_epoch_persists_to_sqlite_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "research_ledger.db"
    ledger = SQLiteLedger(ledger_path)
    recorder = PredictionRecorder(run_id=RUN_ID, lane="exploratory", ledger=ledger)

    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.05")),
    )

    as_of = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
    pred_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=as_of,
    )

    events = ledger.events()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == PREDICTION_SET_EVENT_TYPE
    assert event.entity_type == PREDICTION_SET_ENTITY_TYPE
    assert event.entity_id == pred_set.prediction_set_id
    assert event.timestamp == as_of

    ledger.verify_chain()


def test_duplicate_prediction_in_epoch_rejected() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
    )

    with pytest.raises(DuplicatePredictionError, match="duplicate prediction"):
        recorder.record_prediction(
            security_id=SEC_1,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=h,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
        )


def test_empty_epoch_seal_rejected() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    as_of = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
    with pytest.raises(EmptyEpochError, match="no buffered predictions"):
        recorder.seal_epoch(
            session_date=date(2026, 1, 15),
            as_of_time=as_of,
        )


def test_causality_violation_rejected() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
    )

    # as_of_time on 2026-01-16 is on start_session_date -> causality violation!
    late_as_of = datetime(2026, 1, 16, 9, 30, 0, tzinfo=UTC)
    with pytest.raises(CausalityViolationError, match="causality violation"):
        recorder.seal_epoch(
            session_date=date(2026, 1, 15),
            as_of_time=late_as_of,
        )


def test_multi_epoch_sequence_persists_clean_chain(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    recorder = PredictionRecorder(run_id=RUN_ID, ledger=ledger)

    h1 = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h1,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
    )
    recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC),
    )

    h2 = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 16),
        start_session_date=date(2026, 1, 17),
        end_session_date=date(2026, 1, 17),
    )
    recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h2,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )
    recorder.seal_epoch(
        session_date=date(2026, 1, 16),
        as_of_time=datetime(2026, 1, 16, 21, 0, 0, tzinfo=UTC),
    )

    events = ledger.events()
    assert len(events) == 2
    ledger.verify_chain()
