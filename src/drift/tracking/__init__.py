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

__all__ = [
    "PREDICTION_SET_ENTITY_TYPE",
    "PREDICTION_SET_EVENT_SCHEMA_VERSION",
    "PREDICTION_SET_EVENT_TYPE",
    "CausalityViolationError",
    "DuplicatePredictionError",
    "EmptyEpochError",
    "PredictionRecorder",
    "TrackingError",
]
