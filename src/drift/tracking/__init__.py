"""Ex-ante prediction and outcome tracking package for Drift (M4)."""

from drift.tracking.recorder import (
    PREDICTION_SET_ENTITY_TYPE,
    PREDICTION_SET_EVENT_SCHEMA_VERSION,
    PREDICTION_SET_EVENT_TYPE,
    CausalityViolationError,
    DuplicatePredictionError,
    EmptyEpochError,
    PredictionRecorder,
    TrackingError,
)
from drift.tracking.resolver import (
    OUTCOME_BATCH_ENTITY_TYPE,
    OUTCOME_BATCH_EVENT_SCHEMA_VERSION,
    OUTCOME_BATCH_EVENT_TYPE,
    DelistingOutcomeInfoV1,
    IncompleteHorizonError,
    MissingAnalyticalSeriesError,
    OutcomeResolutionError,
    OutcomeResolver,
)

__all__ = [
    "OUTCOME_BATCH_ENTITY_TYPE",
    "OUTCOME_BATCH_EVENT_SCHEMA_VERSION",
    "OUTCOME_BATCH_EVENT_TYPE",
    "PREDICTION_SET_ENTITY_TYPE",
    "PREDICTION_SET_EVENT_SCHEMA_VERSION",
    "PREDICTION_SET_EVENT_TYPE",
    "CausalityViolationError",
    "DelistingOutcomeInfoV1",
    "DuplicatePredictionError",
    "EmptyEpochError",
    "IncompleteHorizonError",
    "MissingAnalyticalSeriesError",
    "OutcomeResolutionError",
    "OutcomeResolver",
    "PredictionRecorder",
    "TrackingError",
]
