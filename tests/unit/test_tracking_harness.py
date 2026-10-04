"""Unit tests for prediction tracking evaluation harness (M4-4, Issue 181)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from drift.domain.analytical_returns import (
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
    analytical_return_series_hash,
)
from drift.domain.outcomes import OutcomeResolutionStatus
from drift.domain.predictions import HorizonSpecificationV1
from drift.domain.sessions import SessionKeyV1
from drift.ledger.sqlite import SQLiteLedger
from drift.tracking.adapters import (
    B4MomentumPredictor,
    NullReferencePredictor,
)
from drift.tracking.harness import PredictionTrackingHarness
from drift.tracking.resolver import (
    OUTCOME_BATCH_EVENT_TYPE,
    DelistingOutcomeInfoV1,
)

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


def test_harness_end_to_end_lifecycle_with_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "research_ledger.db"
    ledger = SQLiteLedger(ledger_path)

    harness = PredictionTrackingHarness(
        run_id=RUN_ID,
        lane="exploratory",
        ledger=ledger,
    )

    # Historical series with 260 sessions
    series_1 = _build_synthetic_series(SEC_1, count=265)

    # Epoch decision at session 260 (anchor)
    anchor_date = series_1.sessions[260].session_key.local_date
    start_date = series_1.sessions[261].session_key.local_date
    end_date = series_1.sessions[264].session_key.local_date

    h = HorizonSpecificationV1(
        horizon_sessions=4,
        anchor_session_date=anchor_date,
        start_session_date=start_date,
        end_session_date=end_date,
    )

    predictor = B4MomentumPredictor()
    as_of = datetime(
        anchor_date.year, anchor_date.month, anchor_date.day, 21, 0, 0, tzinfo=UTC
    )

    # 1. Record and seal epoch
    pred_set = harness.record_and_seal_epoch(
        session_date=anchor_date,
        as_of_time=as_of,
        target_horizon=h,
        predictor=predictor,
        securities=[SEC_1],
        analytical_series={SEC_1: series_1},
    )

    assert len(pred_set.predictions) == 1
    assert len(harness.sealed_prediction_sets) == 1
    assert len(ledger.events()) == 1

    # 2. Resolve outcomes forward at horizon end
    resolved_at = datetime(
        end_date.year, end_date.month, end_date.day, 22, 0, 0, tzinfo=UTC
    )
    batch = harness.resolve_batch(
        prediction_set=pred_set,
        analytical_series={SEC_1: series_1},
        resolved_at=resolved_at,
    )

    assert len(batch.outcomes) == 1
    assert batch.outcomes[0].status == OutcomeResolutionStatus.RESOLVED
    assert len(harness.resolved_outcome_batches) == 1

    # Ledger now holds both prediction_set and outcome_batch events
    events = ledger.events()
    assert len(events) == 2
    assert events[1].event_type == OUTCOME_BATCH_EVENT_TYPE

    # 3. Compute summary
    summary = harness.compute_summary()
    assert summary.total_predictions_sealed == 1
    assert summary.total_outcomes_resolved == 1
    assert summary.resolved_count == 1
    assert summary.indeterminate_count == 0
    assert summary.directional_accuracy is not None
    assert summary.mean_error is not None
    assert summary.root_mean_squared_error is not None


def test_harness_summary_with_mixed_outcomes() -> None:
    harness = PredictionTrackingHarness(run_id=RUN_ID)

    # Synthetic series
    series_1 = _build_synthetic_series(SEC_1, count=10)
    anchor_date = series_1.sessions[4].session_key.local_date
    start_date = series_1.sessions[5].session_key.local_date
    end_date = series_1.sessions[9].session_key.local_date

    h = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=anchor_date,
        start_session_date=start_date,
        end_session_date=end_date,
    )

    predictor = NullReferencePredictor()
    as_of = datetime(
        anchor_date.year, anchor_date.month, anchor_date.day, 21, 0, 0, tzinfo=UTC
    )

    pred_set = harness.record_and_seal_epoch(
        session_date=anchor_date,
        as_of_time=as_of,
        target_horizon=h,
        predictor=predictor,
        securities=[SEC_1, SEC_2],
        analytical_series={},
    )
    assert len(pred_set.predictions) == 2

    # Resolve with SEC_1 determinate and SEC_2 delisted without proceeds
    delisting_2 = DelistingOutcomeInfoV1(
        security_id=SEC_2,
        delisting_date=start_date,
        has_authenticated_proceeds=False,
        reason="SEC_2 ceased trading unexpectedly",
    )

    resolved_at = datetime(
        end_date.year, end_date.month, end_date.day, 22, 0, 0, tzinfo=UTC
    )
    batch = harness.resolve_batch(
        prediction_set=pred_set,
        analytical_series={SEC_1: series_1},
        resolved_at=resolved_at,
        delistings={SEC_2: delisting_2},
    )

    assert len(batch.outcomes) == 2
    summary = harness.compute_summary()
    assert summary.total_predictions_sealed == 2
    assert summary.total_outcomes_resolved == 2
    assert summary.resolved_count == 1
    assert summary.delisted_without_outcome_count == 1
