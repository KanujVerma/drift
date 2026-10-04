"""Ex-ante prediction recorder and M0 ledger persistence (M4-2, Issue 177).

Manages buffering, causal validation, atomic epoch sealing, and M0 ledger
persistence of ex-ante prediction sets.
"""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid7

from drift.domain.common import (
    NonBlankStr,
    _freeze_json,
)
from drift.domain.predictions import (
    ExAntePredictionRecordV1,
    ExAntePredictionSetV1,
    HorizonSpecificationV1,
    PredictionTargetType,
    PredictionValueV1,
    build_ex_ante_prediction_record,
    build_ex_ante_prediction_set,
)
from drift.errors import DriftError
from drift.ledger.interface import AuditEventDraft, Ledger

PREDICTION_SET_EVENT_TYPE: NonBlankStr = "m4.prediction_set.recorded"
PREDICTION_SET_ENTITY_TYPE: NonBlankStr = "prediction_set"
PREDICTION_SET_EVENT_SCHEMA_VERSION: NonBlankStr = "1"


class TrackingError(DriftError):
    """Base error for prediction and outcome tracking."""


class CausalityViolationError(TrackingError, ValueError):
    """Raised when an ex-ante prediction timestamp violates temporal causality."""


class DuplicatePredictionError(TrackingError, ValueError):
    """Raised when duplicate predictions are registered in a single epoch."""


class EmptyEpochError(TrackingError, ValueError):
    """Raised when attempting to seal an epoch without predictions."""


class PredictionRecorder:
    """Manages buffering, causal validation, and ledger persistence."""

    def __init__(
        self,
        *,
        run_id: UUID,
        lane: Literal["exploratory", "promotion"] = "exploratory",
        ledger: Ledger | None = None,
        input_context_hash: str = "0" * 64,
        model_provenance_hash: str = "0" * 64,
    ) -> None:
        self._run_id = run_id
        self._lane: Literal["exploratory", "promotion"] = lane
        self._ledger = ledger
        self._input_context_hash = input_context_hash
        self._model_provenance_hash = model_provenance_hash
        self._buffer: list[ExAntePredictionRecordV1] = []
        self._registered_keys: set[tuple[UUID, str, date, date]] = set()
        self._sealed_sets: list[ExAntePredictionSetV1] = []

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @property
    def lane(self) -> Literal["exploratory", "promotion"]:
        return self._lane

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    @property
    def sealed_sets(self) -> tuple[ExAntePredictionSetV1, ...]:
        return tuple(self._sealed_sets)

    def record_prediction(
        self,
        *,
        security_id: UUID,
        target_type: PredictionTargetType,
        target_horizon: HorizonSpecificationV1,
        prediction_value: PredictionValueV1,
        prediction_id: UUID | None = None,
        as_of_time: datetime | None = None,
    ) -> ExAntePredictionRecordV1:
        """Buffer an ex-ante prediction for the current decision epoch."""
        key = (
            security_id,
            target_type.value,
            target_horizon.start_session_date,
            target_horizon.end_session_date,
        )
        if key in self._registered_keys:
            raise DuplicatePredictionError(
                f"duplicate prediction registered for security {security_id} "
                f"and target {target_type.value} over horizon "
                f"[{target_horizon.start_session_date}, "
                f"{target_horizon.end_session_date}]"
            )

        if prediction_id is None:
            prediction_id = uuid7()

        if as_of_time is None:
            as_of_time = datetime(
                target_horizon.anchor_session_date.year,
                target_horizon.anchor_session_date.month,
                target_horizon.anchor_session_date.day,
                21,
                0,
                0,
                tzinfo=UTC,
            )

        record = build_ex_ante_prediction_record(
            prediction_id=prediction_id,
            run_id=self._run_id,
            security_id=security_id,
            as_of_time=as_of_time,
            target_type=target_type,
            target_horizon=target_horizon,
            prediction_value=prediction_value,
            input_context_hash=self._input_context_hash,
            model_provenance_hash=self._model_provenance_hash,
        )
        self._buffer.append(record)
        self._registered_keys.add(key)
        return record

    def seal_epoch(
        self,
        *,
        session_date: date,
        as_of_time: datetime,
        prediction_set_id: UUID | None = None,
        audit_event_id: UUID | None = None,
    ) -> ExAntePredictionSetV1:
        """Atomically seal all buffered predictions into an ExAntePredictionSetV1."""
        if not self._buffer:
            raise EmptyEpochError("no buffered predictions to seal for epoch")

        as_of_utc = as_of_time.astimezone(UTC)
        for p in self._buffer:
            if as_of_utc.date() >= p.target_horizon.start_session_date:
                raise CausalityViolationError(
                    f"causality violation: as_of_time {as_of_utc} is on or after "
                    f"target horizon start date {p.target_horizon.start_session_date}"
                )

        if prediction_set_id is None:
            prediction_set_id = uuid7()

        reanchored: list[ExAntePredictionRecordV1] = []
        for p in self._buffer:
            if (
                p.as_of_time != as_of_utc
                or p.target_horizon.anchor_session_date != session_date
            ):
                reanchored.append(
                    build_ex_ante_prediction_record(
                        prediction_id=p.prediction_id,
                        run_id=self._run_id,
                        security_id=p.security_id,
                        as_of_time=as_of_utc,
                        target_type=p.target_type,
                        target_horizon=HorizonSpecificationV1(
                            horizon_sessions=p.target_horizon.horizon_sessions,
                            anchor_session_date=session_date,
                            start_session_date=p.target_horizon.start_session_date,
                            end_session_date=p.target_horizon.end_session_date,
                        ),
                        prediction_value=p.prediction_value,
                        input_context_hash=p.input_context_hash,
                        model_provenance_hash=p.model_provenance_hash,
                    )
                )
            else:
                reanchored.append(p)

        pred_set = build_ex_ante_prediction_set(
            prediction_set_id=prediction_set_id,
            run_id=self._run_id,
            session_date=session_date,
            as_of_time=as_of_utc,
            lane=self._lane,
            predictions=reanchored,
        )

        if self._ledger is not None:
            if audit_event_id is None:
                audit_event_id = uuid7()
            draft = AuditEventDraft(
                event_id=audit_event_id,
                event_type=PREDICTION_SET_EVENT_TYPE,
                timestamp=as_of_utc,
                entity_type=PREDICTION_SET_ENTITY_TYPE,
                entity_id=pred_set.prediction_set_id,
                payload=_freeze_json(pred_set.model_dump(mode="python")),
                deduplication_key=f"m4.prediction_set:{pred_set.prediction_set_id}",
                schema_version=PREDICTION_SET_EVENT_SCHEMA_VERSION,
            )
            self._ledger.append(draft)

        self._buffer.clear()
        self._registered_keys.clear()
        self._sealed_sets.append(pred_set)
        return pred_set
