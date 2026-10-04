"""Deterministic outcome resolver and attribution engine (M4-3, Issue 179).

Resolves ex-ante prediction sets against realized market facts using
corporate-action-consistent analytical returns, calculates error residuals and
directional matches, handles indeterminate and delisting outcomes, and emits
atomic RealizedOutcomeBatchV1 ledger events.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID, uuid7

from pydantic import field_validator, model_validator

from drift.domain.analytical_returns import (
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
)
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    _freeze_json,
)
from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    RealizedOutcomeBatchV1,
    RealizedOutcomeRecordV1,
    build_realized_outcome_batch,
    build_realized_outcome_record,
)
from drift.domain.predictions import (
    DirectionalPredictionV1,
    ExAntePredictionRecordV1,
    ExAntePredictionSetV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.tracking.recorder import (
    TrackingError,
    deterministic_tracking_uuid7,
)

OUTCOME_BATCH_EVENT_TYPE: NonBlankStr = "m4.outcome_batch.resolved"
OUTCOME_BATCH_ENTITY_TYPE: NonBlankStr = "outcome_batch"
OUTCOME_BATCH_EVENT_SCHEMA_VERSION: NonBlankStr = "1"

type RankItem = tuple[ExAntePredictionRecordV1, Decimal, str]
type TiedRankList = list[tuple[int, RankItem]]


class OutcomeResolutionError(TrackingError):
    """Base error for outcome resolution."""


class MissingAnalyticalSeriesError(OutcomeResolutionError, ValueError):
    """Raised when required analytical series is missing."""


class IncompleteHorizonError(OutcomeResolutionError, ValueError):
    """Raised when return series does not cover the complete target horizon."""


class DelistingOutcomeInfoV1(FrozenModel):
    """Information regarding a security's delisting during an evaluation horizon."""

    security_id: UUID7
    delisting_date: date
    has_authenticated_proceeds: bool
    terminal_realized_return: Decimal | None = None
    evidence_hashes: tuple[SHA256Hash, ...] = ()
    reason: NonBlankStr | None = None

    @field_validator("evidence_hashes")
    @classmethod
    def canonicalize_evidence_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("evidence hashes must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_delisting(self) -> Self:
        if self.has_authenticated_proceeds:
            if self.terminal_realized_return is None:
                raise ValueError(
                    "delisting with authenticated proceeds requires "
                    "terminal_realized_return"
                )
        else:
            if self.reason is None:
                raise ValueError(
                    "delisting without authenticated proceeds requires an "
                    "explicit reason"
                )
        return self


def _compute_forward_return(
    matching_sessions: Sequence[AnalyticalReturnSessionV1],
) -> Decimal:
    """Compute cumulative compound return across horizon sessions."""
    compound = Decimal("1")
    for s in matching_sessions:
        if s.return_from_prior is None:
            raise ValueError("session return_from_prior is None")
        compound *= Decimal("1") + s.return_from_prior
    return compound - Decimal("1")


def _compute_realized_volatility(
    matching_sessions: Sequence[AnalyticalReturnSessionV1],
) -> Decimal:
    """Compute sample standard deviation of daily returns across horizon."""
    returns = [
        s.return_from_prior
        for s in matching_sessions
        if s.return_from_prior is not None
    ]
    if len(returns) < 2:
        raise ValueError("sample volatility requires at least 2 sessions")
    k = Decimal(str(len(returns)))
    mean_r = sum(returns, Decimal("0")) / k
    var = sum(((r - mean_r) ** 2 for r in returns), Decimal("0")) / (k - Decimal("1"))
    return var.sqrt()


def _check_directional_match(realized: Decimal, predicted: Decimal) -> bool:
    """Check whether realized and predicted scalar returns have matching signs."""
    if realized > Decimal("0") and predicted > Decimal("0"):
        return True
    if realized < Decimal("0") and predicted < Decimal("0"):
        return True
    if realized == Decimal("0") and predicted == Decimal("0"):
        return True
    return False


def _check_direction_literal_match(realized: Decimal, direction: str) -> bool:
    """Check whether realized scalar return matches categorical direction."""
    if direction == "up":
        return realized > Decimal("0")
    if direction == "down":
        return realized < Decimal("0")
    if direction == "flat":
        return realized == Decimal("0")
    return False


class OutcomeResolver:
    """Deterministic outcome resolver and attribution engine for M4."""

    def __init__(
        self,
        *,
        ledger: Ledger | None = None,
        deterministic: bool = False,
    ) -> None:
        self._ledger = ledger
        self._deterministic = deterministic

    @property
    def deterministic(self) -> bool:
        return self._deterministic

    def resolve_single_prediction(
        self,
        prediction: ExAntePredictionRecordV1,
        *,
        analytical_series: AnalyticalReturnSeriesV1 | None,
        resolved_at: datetime,
        delisting_info: DelistingOutcomeInfoV1 | None = None,
        benchmark_series: AnalyticalReturnSeriesV1 | None = None,
        outcome_id: UUID | None = None,
    ) -> RealizedOutcomeRecordV1:
        """Resolve a single ex-ante prediction against market evidence."""
        if outcome_id is None:
            if self._deterministic:
                seed = f"{prediction.run_id}:outcome:{prediction.prediction_id}"
                outcome_id = deterministic_tracking_uuid7(seed)
            else:
                outcome_id = uuid7()

        resolved_utc = (
            resolved_at.astimezone(UTC)
            if resolved_at.tzinfo is not None
            else resolved_at.replace(tzinfo=UTC)
        )

        # Check for premature resolution
        if resolved_utc.date() < prediction.target_horizon.end_session_date:
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.INDETERMINATE,
                resolved_at=resolved_utc,
                evidence_hashes=(),
                indeterminate_reason=(
                    f"PrematureResolutionError: resolved_at ({resolved_utc.date()}) "
                    f"precedes horizon end session date "
                    f"({prediction.target_horizon.end_session_date})"
                ),
            )

        # Check for delisting
        if delisting_info is not None:
            end_date = prediction.target_horizon.end_session_date
            if delisting_info.delisting_date <= end_date:
                evid_set: set[str] = set(delisting_info.evidence_hashes)
                if analytical_series is not None:
                    evid_set.add(analytical_series.series_hash)

                if delisting_info.has_authenticated_proceeds:
                    assert delisting_info.terminal_realized_return is not None
                    term_ret = delisting_info.terminal_realized_return
                    err: Decimal | None = None
                    match: bool | None = None
                    pred_val = prediction.prediction_value
                    if isinstance(pred_val, ScalarPointPredictionV1):
                        err = term_ret - pred_val.point_value
                        match = _check_directional_match(term_ret, pred_val.point_value)
                    elif isinstance(pred_val, DirectionalPredictionV1):
                        match = _check_direction_literal_match(
                            term_ret, pred_val.direction
                        )

                    return build_realized_outcome_record(
                        outcome_id=outcome_id,
                        prediction_id=prediction.prediction_id,
                        status=OutcomeResolutionStatus.DELISTED_WITH_OUTCOME,
                        realized_value=term_ret,
                        error=err,
                        directional_match=match,
                        resolved_at=resolved_utc,
                        evidence_hashes=sorted(evid_set),
                    )
                else:
                    reason = (
                        delisting_info.reason
                        or f"Security {prediction.security_id} delisted during "
                        f"horizon without liquidating proceeds"
                    )
                    return build_realized_outcome_record(
                        outcome_id=outcome_id,
                        prediction_id=prediction.prediction_id,
                        status=OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME,
                        resolved_at=resolved_utc,
                        evidence_hashes=sorted(evid_set),
                        indeterminate_reason=reason,
                    )

        # Check for missing analytical return series
        if analytical_series is None:
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.EXCLUDED_UNAVAILABLE,
                resolved_at=resolved_utc,
                evidence_hashes=(),
                indeterminate_reason=(
                    "No analytical return series available for security "
                    f"{prediction.security_id}"
                ),
            )

        # Extract horizon sessions
        h_start = prediction.target_horizon.start_session_date
        h_end = prediction.target_horizon.end_session_date
        matching = [
            s
            for s in analytical_series.sessions
            if h_start <= s.session_key.local_date <= h_end
        ]

        # Completeness checks
        if len(matching) < prediction.target_horizon.horizon_sessions:
            expected_n = prediction.target_horizon.horizon_sessions
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.INDETERMINATE,
                resolved_at=resolved_utc,
                evidence_hashes=(analytical_series.series_hash,),
                indeterminate_reason=(
                    f"MissingSessionReturnError: expected {expected_n} sessions, "
                    f"found {len(matching)}"
                ),
            )

        for s in matching:
            if s.return_from_prior is None:
                return build_realized_outcome_record(
                    outcome_id=outcome_id,
                    prediction_id=prediction.prediction_id,
                    status=OutcomeResolutionStatus.INDETERMINATE,
                    resolved_at=resolved_utc,
                    evidence_hashes=(analytical_series.series_hash,),
                    indeterminate_reason=(
                        f"MissingSessionReturnError: session "
                        f"{s.session_key.local_date} has return_from_prior=None"
                    ),
                )

        target_type = prediction.target_type

        if target_type == PredictionTargetType.FORWARD_RETURN:
            realized_val = _compute_forward_return(matching)
            err = None
            dir_match = None
            if isinstance(prediction.prediction_value, ScalarPointPredictionV1):
                err = realized_val - prediction.prediction_value.point_value
                dir_match = _check_directional_match(
                    realized_val, prediction.prediction_value.point_value
                )
            elif isinstance(prediction.prediction_value, DirectionalPredictionV1):
                dir_match = _check_direction_literal_match(
                    realized_val, prediction.prediction_value.direction
                )
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.RESOLVED,
                realized_value=realized_val,
                error=err,
                directional_match=dir_match,
                resolved_at=resolved_utc,
                evidence_hashes=(analytical_series.series_hash,),
            )

        if target_type == PredictionTargetType.DIRECTIONAL_RETURN:
            realized_val = _compute_forward_return(matching)
            err = None
            dir_match = None
            if isinstance(prediction.prediction_value, DirectionalPredictionV1):
                dir_match = _check_direction_literal_match(
                    realized_val, prediction.prediction_value.direction
                )
            elif isinstance(prediction.prediction_value, ScalarPointPredictionV1):
                err = realized_val - prediction.prediction_value.point_value
                dir_match = _check_directional_match(
                    realized_val, prediction.prediction_value.point_value
                )
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.RESOLVED,
                realized_value=realized_val,
                error=err,
                directional_match=dir_match,
                resolved_at=resolved_utc,
                evidence_hashes=(analytical_series.series_hash,),
            )

        if target_type == PredictionTargetType.REALIZED_VOLATILITY:
            if len(matching) < 2:
                return build_realized_outcome_record(
                    outcome_id=outcome_id,
                    prediction_id=prediction.prediction_id,
                    status=OutcomeResolutionStatus.INDETERMINATE,
                    resolved_at=resolved_utc,
                    evidence_hashes=(analytical_series.series_hash,),
                    indeterminate_reason=(
                        "IndeterminateValuationError: realized volatility "
                        "requires at least 2 sessions"
                    ),
                )
            realized_val = _compute_realized_volatility(matching)
            err = None
            if isinstance(prediction.prediction_value, ScalarPointPredictionV1):
                err = realized_val - prediction.prediction_value.point_value
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.RESOLVED,
                realized_value=realized_val,
                error=err,
                directional_match=None,
                resolved_at=resolved_utc,
                evidence_hashes=(analytical_series.series_hash,),
            )

        if target_type == PredictionTargetType.EXCESS_RETURN:
            if benchmark_series is None:
                return build_realized_outcome_record(
                    outcome_id=outcome_id,
                    prediction_id=prediction.prediction_id,
                    status=OutcomeResolutionStatus.INDETERMINATE,
                    resolved_at=resolved_utc,
                    evidence_hashes=(analytical_series.series_hash,),
                    indeterminate_reason=(
                        "MissingBenchmarkSeriesError: benchmark series unavailable"
                    ),
                )
            bench_matching = [
                s
                for s in benchmark_series.sessions
                if h_start <= s.session_key.local_date <= h_end
            ]
            if len(bench_matching) < prediction.target_horizon.horizon_sessions or any(
                s.return_from_prior is None for s in bench_matching
            ):
                return build_realized_outcome_record(
                    outcome_id=outcome_id,
                    prediction_id=prediction.prediction_id,
                    status=OutcomeResolutionStatus.INDETERMINATE,
                    resolved_at=resolved_utc,
                    evidence_hashes=sorted(
                        {analytical_series.series_hash, benchmark_series.series_hash}
                    ),
                    indeterminate_reason=(
                        "MissingBenchmarkSeriesError: benchmark series "
                        "incomplete across horizon"
                    ),
                )
            stock_ret = _compute_forward_return(matching)
            bench_ret = _compute_forward_return(bench_matching)
            realized_val = stock_ret - bench_ret
            err = None
            dir_match = None
            if isinstance(prediction.prediction_value, ScalarPointPredictionV1):
                err = realized_val - prediction.prediction_value.point_value
                dir_match = _check_directional_match(
                    realized_val, prediction.prediction_value.point_value
                )
            evid_hashes = sorted(
                {analytical_series.series_hash, benchmark_series.series_hash}
            )
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.RESOLVED,
                realized_value=realized_val,
                error=err,
                directional_match=dir_match,
                resolved_at=resolved_utc,
                evidence_hashes=evid_hashes,
            )

        if target_type == PredictionTargetType.CROSS_SECTIONAL_RANK:
            # Fallback for single prediction: rank is 1.0
            realized_val = Decimal("1.0")
            err = None
            if isinstance(prediction.prediction_value, ScalarPointPredictionV1):
                err = realized_val - prediction.prediction_value.point_value
            return build_realized_outcome_record(
                outcome_id=outcome_id,
                prediction_id=prediction.prediction_id,
                status=OutcomeResolutionStatus.RESOLVED,
                realized_value=realized_val,
                error=err,
                directional_match=None,
                resolved_at=resolved_utc,
                evidence_hashes=(analytical_series.series_hash,),
            )

        raise OutcomeResolutionError(f"unsupported target type {target_type}")

    def resolve_prediction_records(
        self,
        predictions: tuple[ExAntePredictionRecordV1, ...]
        | list[ExAntePredictionRecordV1],
        *,
        run_id: UUID,
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        resolved_at: datetime,
        lane: Literal["exploratory", "promotion"] = "exploratory",
        delistings: Mapping[UUID, DelistingOutcomeInfoV1] | None = None,
        benchmark_series: AnalyticalReturnSeriesV1 | None = None,
        outcome_batch_id: UUID | None = None,
        audit_event_id: UUID | None = None,
    ) -> RealizedOutcomeBatchV1:
        """Resolve a batch of ex-ante prediction records."""
        resolved_utc = (
            resolved_at.astimezone(UTC)
            if resolved_at.tzinfo is not None
            else resolved_at.replace(tzinfo=UTC)
        )

        outcomes: list[RealizedOutcomeRecordV1] = []

        # Separate cross-sectional rank predictions from others
        rank_preds_by_horizon: dict[
            tuple[date, date, date], list[ExAntePredictionRecordV1]
        ] = defaultdict(list)
        other_preds: list[ExAntePredictionRecordV1] = []

        for p in predictions:
            if p.target_type == PredictionTargetType.CROSS_SECTIONAL_RANK:
                key = (
                    p.target_horizon.anchor_session_date,
                    p.target_horizon.start_session_date,
                    p.target_horizon.end_session_date,
                )
                rank_preds_by_horizon[key].append(p)
            else:
                other_preds.append(p)

        # Resolve other predictions directly
        for p in other_preds:
            s = analytical_series.get(p.security_id)
            d = delistings.get(p.security_id) if delistings is not None else None
            record = self.resolve_single_prediction(
                p,
                analytical_series=s,
                resolved_at=resolved_utc,
                delisting_info=d,
                benchmark_series=benchmark_series,
            )
            outcomes.append(record)

        # Resolve cross-sectional rank groups
        for _horizon_key, group in rank_preds_by_horizon.items():
            determinate_items: list[RankItem] = []
            for p in group:
                s = analytical_series.get(p.security_id)
                d = delistings.get(p.security_id) if delistings is not None else None
                # If delisted or missing series, resolve individually
                if s is None or d is not None:
                    outcomes.append(
                        self.resolve_single_prediction(
                            p,
                            analytical_series=s,
                            resolved_at=resolved_utc,
                            delisting_info=d,
                        )
                    )
                    continue

                h_start = p.target_horizon.start_session_date
                h_end = p.target_horizon.end_session_date
                matching = [
                    sess
                    for sess in s.sessions
                    if h_start <= sess.session_key.local_date <= h_end
                ]
                if len(matching) < p.target_horizon.horizon_sessions or any(
                    sess.return_from_prior is None for sess in matching
                ):
                    outcomes.append(
                        self.resolve_single_prediction(
                            p,
                            analytical_series=s,
                            resolved_at=resolved_utc,
                        )
                    )
                    continue

                ret = _compute_forward_return(matching)
                determinate_items.append((p, ret, s.series_hash))

            if not determinate_items:
                continue

            n = len(determinate_items)
            if n == 1:
                p, ret, s_hash = determinate_items[0]
                rank_val = Decimal("1.0")
                err = None
                if isinstance(p.prediction_value, ScalarPointPredictionV1):
                    err = rank_val - p.prediction_value.point_value
                single_out_id = (
                    deterministic_tracking_uuid7(
                        f"{p.run_id}:outcome:{p.prediction_id}"
                    )
                    if self._deterministic
                    else uuid7()
                )
                outcomes.append(
                    build_realized_outcome_record(
                        outcome_id=single_out_id,
                        prediction_id=p.prediction_id,
                        status=OutcomeResolutionStatus.RESOLVED,
                        realized_value=rank_val,
                        error=err,
                        directional_match=None,
                        resolved_at=resolved_utc,
                        evidence_hashes=(s_hash,),
                    )
                )
            else:
                # Sort by return ascending
                determinate_items.sort(key=lambda item: item[1])
                denom = Decimal(str(n - 1))

                # Handle ties with average fractional rank
                return_groups: dict[Decimal, TiedRankList] = defaultdict(list)
                for idx, item in enumerate(determinate_items):
                    return_groups[item[1]].append((idx, item))

                for _ret_val, tied_list in return_groups.items():
                    avg_rank = sum(
                        Decimal(str(idx)) / denom for idx, _ in tied_list
                    ) / Decimal(str(len(tied_list)))
                    for _, (p, _, s_hash) in tied_list:
                        err = None
                        if isinstance(p.prediction_value, ScalarPointPredictionV1):
                            err = avg_rank - p.prediction_value.point_value
                        tied_out_id = (
                            deterministic_tracking_uuid7(
                                f"{p.run_id}:outcome:{p.prediction_id}"
                            )
                            if self._deterministic
                            else uuid7()
                        )
                        outcomes.append(
                            build_realized_outcome_record(
                                outcome_id=tied_out_id,
                                prediction_id=p.prediction_id,
                                status=OutcomeResolutionStatus.RESOLVED,
                                realized_value=avg_rank,
                                error=err,
                                directional_match=None,
                                resolved_at=resolved_utc,
                                evidence_hashes=(s_hash,),
                            )
                        )

        if outcome_batch_id is None:
            if self._deterministic:
                seed = f"{run_id}:batch:{resolved_utc.isoformat()}:{len(outcomes)}"
                outcome_batch_id = deterministic_tracking_uuid7(seed)
            else:
                outcome_batch_id = uuid7()

        batch = build_realized_outcome_batch(
            outcome_batch_id=outcome_batch_id,
            run_id=run_id,
            resolved_at=resolved_utc,
            lane=lane,
            outcomes=outcomes,
        )

        if self._ledger is not None:
            if audit_event_id is None:
                if self._deterministic:
                    seed = f"{run_id}:outcome_event:{batch.outcome_batch_id}"
                    audit_event_id = deterministic_tracking_uuid7(seed)
                else:
                    audit_event_id = uuid7()
            draft = AuditEventDraft(
                event_id=audit_event_id,
                event_type=OUTCOME_BATCH_EVENT_TYPE,
                timestamp=resolved_utc,
                entity_type=OUTCOME_BATCH_ENTITY_TYPE,
                entity_id=batch.outcome_batch_id,
                payload=_freeze_json(batch.model_dump(mode="python")),
                deduplication_key=f"m4.outcome_batch:{batch.outcome_batch_id}",
                schema_version=OUTCOME_BATCH_EVENT_SCHEMA_VERSION,
            )
            self._ledger.append(draft)

        return batch

    def resolve_prediction_set(
        self,
        prediction_set: ExAntePredictionSetV1,
        *,
        analytical_series: Mapping[UUID, AnalyticalReturnSeriesV1],
        resolved_at: datetime,
        delistings: Mapping[UUID, DelistingOutcomeInfoV1] | None = None,
        benchmark_series: AnalyticalReturnSeriesV1 | None = None,
        outcome_batch_id: UUID | None = None,
        audit_event_id: UUID | None = None,
    ) -> RealizedOutcomeBatchV1:
        """Resolve an entire sealed ExAntePredictionSetV1 against market evidence."""
        return self.resolve_prediction_records(
            prediction_set.predictions,
            run_id=prediction_set.run_id,
            analytical_series=analytical_series,
            resolved_at=resolved_at,
            lane=prediction_set.lane,
            delistings=delistings,
            benchmark_series=benchmark_series,
            outcome_batch_id=outcome_batch_id,
            audit_event_id=audit_event_id,
        )
