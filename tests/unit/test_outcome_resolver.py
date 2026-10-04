"""Unit tests for deterministic outcome resolver and attribution engine (Issue 179)."""

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
from drift.domain.predictions import (
    DirectionalPredictionV1,
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.ledger.sqlite import SQLiteLedger
from drift.tracking.recorder import PredictionRecorder
from drift.tracking.resolver import (
    OUTCOME_BATCH_ENTITY_TYPE,
    OUTCOME_BATCH_EVENT_TYPE,
    DelistingOutcomeInfoV1,
    OutcomeResolver,
)

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdef")
SEC_1 = UUID("00000000-0000-7000-8000-000000000001")
SEC_2 = UUID("00000000-0000-7000-8000-000000000002")
SEC_3 = UUID("00000000-0000-7000-8000-000000000003")
BENCH_SEC = UUID("00000000-0000-7000-8000-000000000099")
VENUE = "XNAS"


def _session_key(d: date) -> SessionKeyV1:
    return SessionKeyV1(local_date=d, mic=VENUE, session_scope="regular")


def _build_series(
    *,
    security_id: UUID,
    sessions: tuple[AnalyticalReturnSessionV1, ...],
) -> AnalyticalReturnSeriesV1:
    interval = (sessions[0].session_key, sessions[-1].session_key)
    draft = AnalyticalReturnSeriesV1.model_construct(
        schema_version="1",
        security_id=security_id,
        grade="exploratory",
        adjustment_method=ADJUSTMENT_METHOD_TOTAL_RETURN,
        sessions=sessions,
        lookback_interval=interval,
        source_observation_hashes=(),
        applied_effect_hashes=(),
        acknowledged_limitations=(),
        series_hash="0" * 64,
    )
    return draft.model_copy(
        update={"series_hash": analytical_return_series_hash(draft)}
    )


def _make_sample_series(
    sec_id: UUID,
    returns: list[tuple[date, Decimal | None, Decimal]],
) -> AnalyticalReturnSeriesV1:
    sess_list: list[AnalyticalReturnSessionV1] = []
    for d, ret, close in returns:
        sess_list.append(
            AnalyticalReturnSessionV1(
                session_key=_session_key(d),
                unadjusted_close=close,
                analytical_close=close,
                return_from_prior=ret,
                cumulative_split_factor=Decimal("1"),
            )
        )
    return _build_series(security_id=sec_id, sessions=tuple(sess_list))


def test_resolve_forward_return_scalar_point() -> None:
    # 1 anchor session (day 15) and 3 forward sessions (days 16, 17, 18)
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100.00")),
            (date(2026, 1, 16), Decimal("0.01"), Decimal("101.00")),
            (date(2026, 1, 17), Decimal("0.02"), Decimal("103.02")),
            (date(2026, 1, 18), Decimal("-0.01"), Decimal("101.9898")),
        ],
    )

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=3,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 18),
    )
    pred_rec = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.015")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 18, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred_rec,
        analytical_series=series,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.RESOLVED
    assert outcome.prediction_id == pred_rec.prediction_id
    # Compound return: (1 + 0.01) * (1 + 0.02) * (1 - 0.01) - 1 = 0.019898
    expected_ret = Decimal("0.019898")
    assert outcome.realized_value == expected_ret
    assert outcome.error == expected_ret - Decimal("0.015")
    assert outcome.directional_match is True
    assert outcome.indeterminate_reason is None
    assert outcome.evidence_hashes == (series.series_hash,)


def test_resolve_forward_return_directional() -> None:
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100.00")),
            (date(2026, 1, 16), Decimal("0.03"), Decimal("103.00")),
        ],
    )

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    pred_up = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=DirectionalPredictionV1(
            direction="up", confidence=Decimal("0.8")
        ),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    outcome_up = resolver.resolve_single_prediction(
        pred_up,
        analytical_series=series,
        resolved_at=resolved_at,
    )
    assert outcome_up.status == OutcomeResolutionStatus.RESOLVED
    assert outcome_up.realized_value == Decimal("0.03")
    assert outcome_up.error is None
    assert outcome_up.directional_match is True

    # Same with down prediction expecting mismatch
    pred_down = recorder.record_prediction(
        security_id=SEC_2,
        target_type=PredictionTargetType.DIRECTIONAL_RETURN,
        target_horizon=h,
        prediction_value=DirectionalPredictionV1(
            direction="down", confidence=Decimal("0.7")
        ),
    )
    outcome_down = resolver.resolve_single_prediction(
        pred_down,
        analytical_series=series,
        resolved_at=resolved_at,
    )
    assert outcome_down.status == OutcomeResolutionStatus.RESOLVED
    assert outcome_down.directional_match is False


def test_resolve_realized_volatility() -> None:
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100.00")),
            (date(2026, 1, 16), Decimal("0.02"), Decimal("102.00")),
            (date(2026, 1, 17), Decimal("-0.02"), Decimal("99.96")),
        ],
    )

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=2,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 17),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.REALIZED_VOLATILITY,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 17, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=series,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.RESOLVED
    assert outcome.realized_value is not None
    # returns: 0.02, -0.02. mean = 0.
    # diffs^2 = 0.0004 + 0.0004 = 0.0008. var = 0.0008 / (2 - 1) = 0.0008
    # vol = sqrt(0.0008)
    expected_vol = Decimal("0.0008").sqrt()
    assert outcome.realized_value == expected_vol
    assert outcome.error == expected_vol - Decimal("0.02")
    assert outcome.directional_match is None


def test_resolve_realized_volatility_under_2_sessions_indeterminate() -> None:
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100.00")),
            (date(2026, 1, 16), Decimal("0.02"), Decimal("102.00")),
        ],
    )
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.REALIZED_VOLATILITY,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=series,
        resolved_at=resolved_at,
    )
    assert outcome.status == OutcomeResolutionStatus.INDETERMINATE
    assert "realized volatility requires at least 2 sessions" in str(
        outcome.indeterminate_reason
    )


def test_resolve_excess_return() -> None:
    sec_series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100.00")),
            (date(2026, 1, 16), Decimal("0.05"), Decimal("105.00")),
        ],
    )
    bench_series = _make_sample_series(
        BENCH_SEC,
        [
            (date(2026, 1, 15), None, Decimal("200.00")),
            (date(2026, 1, 16), Decimal("0.02"), Decimal("204.00")),
        ],
    )

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.EXCESS_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.025")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=sec_series,
        benchmark_series=bench_series,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.RESOLVED
    assert outcome.realized_value == Decimal("0.05") - Decimal("0.02")
    assert outcome.error == Decimal("0.03") - Decimal("0.025")
    assert outcome.directional_match is True
    assert outcome.evidence_hashes == tuple(
        sorted([sec_series.series_hash, bench_series.series_hash])
    )


def test_resolve_cross_sectional_rank_cohort() -> None:
    # 3 securities with returns: SEC_1: -0.01, SEC_2: +0.02, SEC_3: +0.05
    s1 = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("-0.01"), Decimal("99")),
        ],
    )
    s2 = _make_sample_series(
        SEC_2,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("0.02"), Decimal("102")),
        ],
    )
    s3 = _make_sample_series(
        SEC_3,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("0.05"), Decimal("105")),
        ],
    )

    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    p1 = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.CROSS_SECTIONAL_RANK,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.1")),
    )
    p2 = recorder.record_prediction(
        security_id=SEC_2,
        target_type=PredictionTargetType.CROSS_SECTIONAL_RANK,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.5")),
    )
    p3 = recorder.record_prediction(
        security_id=SEC_3,
        target_type=PredictionTargetType.CROSS_SECTIONAL_RANK,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.9")),
    )

    pred_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    batch = resolver.resolve_prediction_set(
        pred_set,
        analytical_series={SEC_1: s1, SEC_2: s2, SEC_3: s3},
        resolved_at=resolved_at,
    )

    assert len(batch.outcomes) == 3
    outcomes_by_pred = {o.prediction_id: o for o in batch.outcomes}

    # SEC_1 has lowest return -> rank 0.0
    assert outcomes_by_pred[p1.prediction_id].realized_value == Decimal("0")
    # SEC_2 has middle return -> rank 0.5 (1 / 2)
    assert outcomes_by_pred[p2.prediction_id].realized_value == Decimal("0.5")
    # SEC_3 has highest return -> rank 1.0 (2 / 2)
    assert outcomes_by_pred[p3.prediction_id].realized_value == Decimal("1.0")


def test_resolve_missing_analytical_series_excluded_unavailable() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=None,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.EXCLUDED_UNAVAILABLE
    assert outcome.realized_value is None
    assert outcome.error is None
    assert "No analytical return series available" in str(outcome.indeterminate_reason)


def test_resolve_incomplete_horizon_indeterminate() -> None:
    # Requires 3 sessions, but only 1 forward session provided
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("0.01"), Decimal("101")),
        ],
    )
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=3,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 18),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 18, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=series,
        resolved_at=resolved_at,
    )
    assert outcome.status == OutcomeResolutionStatus.INDETERMINATE
    assert "MissingSessionReturnError: expected 3 sessions, found 1" in str(
        outcome.indeterminate_reason
    )


def test_resolve_premature_resolution_indeterminate() -> None:
    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("0.01"), Decimal("101")),
        ],
    )
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )

    resolver = OutcomeResolver()
    # Attempting to resolve on Jan 15 when horizon ends on Jan 16
    premature_at = datetime(2026, 1, 15, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=series,
        resolved_at=premature_at,
    )
    assert outcome.status == OutcomeResolutionStatus.INDETERMINATE
    assert "PrematureResolutionError" in str(outcome.indeterminate_reason)


def test_resolve_delisting_with_outcome() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.05")),
    )

    delisting = DelistingOutcomeInfoV1(
        security_id=SEC_1,
        delisting_date=date(2026, 1, 19),
        has_authenticated_proceeds=True,
        terminal_realized_return=Decimal("0.12"),
        evidence_hashes=("d" * 64,),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 23, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=None,
        delisting_info=delisting,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.DELISTED_WITH_OUTCOME
    assert outcome.realized_value == Decimal("0.12")
    assert outcome.error == Decimal("0.12") - Decimal("0.05")
    assert outcome.directional_match is True
    assert outcome.evidence_hashes == ("d" * 64,)


def test_resolve_delisting_without_outcome() -> None:
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=5,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 23),
    )
    pred = recorder.record_prediction(
        security_id=SEC_1,
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.05")),
    )

    delisting = DelistingOutcomeInfoV1(
        security_id=SEC_1,
        delisting_date=date(2026, 1, 19),
        has_authenticated_proceeds=False,
        reason="Acquired with unverified cash merger proceeds",
        evidence_hashes=("d" * 64,),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 23, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=None,
        delisting_info=delisting,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME
    assert outcome.realized_value is None
    assert outcome.error is None
    assert "Acquired with unverified cash merger proceeds" in str(
        outcome.indeterminate_reason
    )


def test_resolve_prediction_set_and_persist_to_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "research_ledger.db"
    ledger = SQLiteLedger(ledger_path)

    recorder = PredictionRecorder(run_id=RUN_ID, ledger=ledger)
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
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
    )
    pred_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC),
    )

    # 1 event for prediction set recorded
    assert len(ledger.events()) == 1

    series = _make_sample_series(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100")),
            (date(2026, 1, 16), Decimal("0.02"), Decimal("102")),
        ],
    )

    resolver = OutcomeResolver(ledger=ledger)
    resolved_at = datetime(2026, 1, 16, 22, 0, 0, tzinfo=UTC)
    batch = resolver.resolve_prediction_set(
        pred_set,
        analytical_series={SEC_1: series},
        resolved_at=resolved_at,
    )

    assert len(batch.outcomes) == 1
    assert batch.outcomes[0].status == OutcomeResolutionStatus.RESOLVED

    # Now ledger should have 2 events: prediction set + outcome batch
    events = ledger.events()
    assert len(events) == 2
    outcome_event = events[1]
    assert outcome_event.event_type == OUTCOME_BATCH_EVENT_TYPE
    assert outcome_event.entity_type == OUTCOME_BATCH_ENTITY_TYPE
    assert outcome_event.entity_id == batch.outcome_batch_id
