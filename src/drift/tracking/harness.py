"""Prediction tracking evaluation harness (M4-4, Issue 181).

Integrates baseline predictors, ex-ante prediction recording, atomic epoch sealing,
deterministic outcome resolution, and M0 SQLite research ledger persistence.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from drift.domain.analytical_returns import AnalyticalReturnSeriesV1
from drift.domain.common import (
    UUID7,
    FrozenModel,
)
from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    RealizedOutcomeBatchV1,
)
from drift.domain.predictions import (
    ExAntePredictionSetV1,
    HorizonSpecificationV1,
)
from drift.ledger.interface import Ledger
from drift.tracking.adapters import PredictorAdapter
from drift.tracking.recorder import PredictionRecorder
from drift.tracking.resolver import (
    DelistingOutcomeInfoV1,
    OutcomeResolver,
)


class PredictionTrackingSummaryV1(FrozenModel):
    """Immutable summary metrics for an evaluation run's prediction tracking."""

    schema_version: Literal["1"] = "1"
    run_id: UUID7
    lane: Literal["exploratory", "promotion"]
    total_predictions_sealed: int
    total_outcomes_resolved: int
    resolved_count: int
    indeterminate_count: int
    delisted_with_outcome_count: int
    delisted_without_outcome_count: int
    excluded_unavailable_count: int
    directional_accuracy: Decimal | None = None
    mean_error: Decimal | None = None
    root_mean_squared_error: Decimal | None = None
    prediction_set_ids: tuple[UUID7, ...] = ()
    outcome_batch_ids: tuple[UUID7, ...] = ()


class PredictionTrackingHarness:
    """Manages prediction recording and outcome resolution across evaluation runs."""

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
        self._lane = lane
        self._ledger = ledger
        self._recorder = PredictionRecorder(
            run_id=run_id,
            lane=lane,
            ledger=ledger,
            input_context_hash=input_context_hash,
            model_provenance_hash=model_provenance_hash,
        )
        self._resolver = OutcomeResolver(ledger=ledger)
        self._sealed_sets: list[ExAntePredictionSetV1] = []
        self._resolved_batches: list[RealizedOutcomeBatchV1] = []

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @property
    def lane(self) -> Literal["exploratory", "promotion"]:
        return self._lane

    @property
    def recorder(self) -> PredictionRecorder:
        return self._recorder

    @property
    def resolver(self) -> OutcomeResolver:
        return self._resolver

    @property
    def sealed_prediction_sets(self) -> tuple[ExAntePredictionSetV1, ...]:
        return tuple(self._sealed_sets)

    @property
    def resolved_outcome_batches(self) -> tuple[RealizedOutcomeBatchV1, ...]:
        return tuple(self._resolved_batches)

    def record_and_seal_epoch(
        self,
        *,
        session_date: date,
        as_of_time: datetime,
        target_horizon: HorizonSpecificationV1,
        predictor: PredictorAdapter,
        securities: Sequence[UUID],
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
    ) -> ExAntePredictionSetV1:
        """Run predictor and seal ex-ante predictions into an immutable set."""
        predictor.predict(
            recorder=self._recorder,
            securities=securities,
            analytical_series=analytical_series,
            target_horizon=target_horizon,
            as_of_time=as_of_time,
        )

        pred_set = self._recorder.seal_epoch(
            session_date=session_date,
            as_of_time=as_of_time,
        )
        self._sealed_sets.append(pred_set)
        return pred_set

    def resolve_batch(
        self,
        *,
        prediction_set: ExAntePredictionSetV1,
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        resolved_at: datetime,
        delistings: Mapping[UUID, DelistingOutcomeInfoV1] | None = None,
        benchmark_series: AnalyticalReturnSeriesV1 | None = None,
    ) -> RealizedOutcomeBatchV1:
        """Resolve forward outcomes for a sealed prediction set."""
        batch = self._resolver.resolve_prediction_set(
            prediction_set,
            analytical_series=analytical_series,
            resolved_at=resolved_at,
            delistings=delistings,
            benchmark_series=benchmark_series,
        )
        self._resolved_batches.append(batch)
        return batch

    def compute_summary(self) -> PredictionTrackingSummaryV1:
        """Compute summary attribution metrics across all resolved batches."""
        all_preds = [p for ps in self._sealed_sets for p in ps.predictions]
        all_outcomes = [o for b in self._resolved_batches for o in b.outcomes]

        resolved_n = sum(
            1 for o in all_outcomes if o.status == OutcomeResolutionStatus.RESOLVED
        )
        indet_n = sum(
            1 for o in all_outcomes if o.status == OutcomeResolutionStatus.INDETERMINATE
        )
        delisted_with_n = sum(
            1
            for o in all_outcomes
            if o.status == OutcomeResolutionStatus.DELISTED_WITH_OUTCOME
        )
        delisted_without_n = sum(
            1
            for o in all_outcomes
            if o.status == OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME
        )
        excluded_n = sum(
            1
            for o in all_outcomes
            if o.status == OutcomeResolutionStatus.EXCLUDED_UNAVAILABLE
        )

        dir_matches = [
            o.directional_match for o in all_outcomes if o.directional_match is not None
        ]
        dir_acc: Decimal | None = None
        if dir_matches:
            correct = sum(1 for m in dir_matches if m is True)
            dir_acc = Decimal(str(correct)) / Decimal(str(len(dir_matches)))

        errors = [o.error for o in all_outcomes if o.error is not None]
        mean_err: Decimal | None = None
        rmse: Decimal | None = None
        if errors:
            err_count = Decimal(str(len(errors)))
            mean_err = sum(errors, Decimal("0")) / err_count
            mse = sum((e**2 for e in errors), Decimal("0")) / err_count
            rmse = mse.sqrt()

        return PredictionTrackingSummaryV1(
            run_id=self._run_id,
            lane=self._lane,
            total_predictions_sealed=len(all_preds),
            total_outcomes_resolved=len(all_outcomes),
            resolved_count=resolved_n,
            indeterminate_count=indet_n,
            delisted_with_outcome_count=delisted_with_n,
            delisted_without_outcome_count=delisted_without_n,
            excluded_unavailable_count=excluded_n,
            directional_accuracy=dir_acc,
            mean_error=mean_err,
            root_mean_squared_error=rmse,
            prediction_set_ids=tuple(ps.prediction_set_id for ps in self._sealed_sets),
            outcome_batch_ids=tuple(b.outcome_batch_id for b in self._resolved_batches),
        )
