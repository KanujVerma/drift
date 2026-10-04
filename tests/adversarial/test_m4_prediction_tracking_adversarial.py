"""M4 adversarial acceptance suite: prediction and outcome tracking (Issue 183).

Attacks the prediction and outcome tracking kernel across all five criteria:
1. Lookahead Immunity: Future observations after as_of_time cannot alter
   sealed predictions.
2. Causality Ordering: Predictions post-dating horizon open or premature
   resolutions fail closed.
3. Anti-Cherry-Picking: All cohort members must explicitly resolve to terminal
   states.
4. Corporate Action Invariance: Forward returns across stock splits reflect
   true economic reality.
5. Replay Determinism: Bitwise invariant replay of prediction sets and outcome
   batches.

Every test follows the adversarial principle: assertion of an attack paired with a
control proving that the test cannot pass vacuously.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.analytical_returns import (
    ADJUSTMENT_METHOD_TOTAL_RETURN,
    AnalyticalReturnSeriesV1,
    AnalyticalReturnSessionV1,
    analytical_return_series_hash,
)
from drift.domain.outcomes import OutcomeResolutionStatus
from drift.domain.predictions import (
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import canonical_json
from drift.tracking.adapters import B4MomentumPredictor
from drift.tracking.harness import PredictionTrackingHarness
from drift.tracking.recorder import (
    CausalityViolationError,
    DuplicatePredictionError,
    EmptyEpochError,
    PredictionRecorder,
)
from drift.tracking.resolver import (
    DelistingOutcomeInfoV1,
    OutcomeResolver,
)

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdef")
SEC_1 = UUID("00000000-0000-7000-8000-000000000001")
SEC_2 = UUID("00000000-0000-7000-8000-000000000002")
SEC_3 = UUID("00000000-0000-7000-8000-000000000003")
SEC_4 = UUID("00000000-0000-7000-8000-000000000004")
SEC_5 = UUID("00000000-0000-7000-8000-000000000005")
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


def _make_series_from_tuples(
    sec_id: UUID,
    records: list[tuple[date, Decimal | None, Decimal, Decimal]],
) -> AnalyticalReturnSeriesV1:
    # records: (date, return_from_prior, analytical_close, cumulative_split_factor)
    sessions: list[AnalyticalReturnSessionV1] = []
    for d, ret, close, split_factor in records:
        unadjusted = close / split_factor
        sessions.append(
            AnalyticalReturnSessionV1(
                session_key=_session_key(d),
                unadjusted_close=unadjusted,
                analytical_close=close,
                return_from_prior=ret,
                cumulative_split_factor=split_factor,
            )
        )
    return _build_series(security_id=sec_id, sessions=tuple(sessions))


def test_adversarial_lookahead_immunity() -> None:
    """Attack: inject future market fluctuations into environment after as_of_time.

    Control: verify already-sealed ex-ante prediction sets and content hashes
    remain bitwise invariant and immune to post-decision tampering.
    """
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
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.035")),
    )
    as_of = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
    pred_set_control = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=as_of,
    )

    control_hash = pred_set_control.set_hash
    control_pred_hash = pred.prediction_hash

    # Attack 1: Attempt in-place mutation of sealed prediction set
    with pytest.raises(ValidationError):
        pred_set_control.session_date = date(2026, 1, 20)

    # Attack 2: Attempt in-place mutation of prediction record
    with pytest.raises(ValidationError):
        pred.prediction_value = ScalarPointPredictionV1(point_value=Decimal("0.99"))

    # Control verification: hashes remain identical
    assert pred_set_control.set_hash == control_hash
    assert pred.prediction_hash == control_pred_hash


def test_adversarial_causality_ordering() -> None:
    """Attack: attempt to register/seal predictions post-dating horizon open,

    register duplicate predictions, seal empty epochs, or resolve prematurely.
    Control: verify all illegal temporal and logical operations fail closed.
    """
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=2,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 17),
    )

    # Attack 1: Duplicate prediction registration in same epoch
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

    # Attack 2: Sealing epoch with as_of_time on or after horizon start date
    illegal_as_of = datetime(2026, 1, 16, 9, 30, 0, tzinfo=UTC)
    with pytest.raises(CausalityViolationError, match="causality violation"):
        recorder.seal_epoch(
            session_date=date(2026, 1, 15),
            as_of_time=illegal_as_of,
        )

    # Control 2: Valid as_of_time strictly before horizon start succeeds
    valid_as_of = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
    sealed_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=valid_as_of,
    )
    assert len(sealed_set.predictions) == 1

    # Attack 3: Empty epoch sealing
    with pytest.raises(EmptyEpochError, match="no buffered predictions"):
        recorder.seal_epoch(
            session_date=date(2026, 1, 15),
            as_of_time=valid_as_of,
        )

    # Attack 4: Premature resolution before horizon has concluded
    resolver = OutcomeResolver()
    premature_resolved_at = datetime(2026, 1, 16, 21, 0, 0, tzinfo=UTC)
    premature_outcome = resolver.resolve_single_prediction(
        sealed_set.predictions[0],
        analytical_series=None,
        resolved_at=premature_resolved_at,
    )
    assert premature_outcome.status == OutcomeResolutionStatus.INDETERMINATE
    assert "PrematureResolutionError" in str(premature_outcome.indeterminate_reason)


def test_adversarial_anti_cherry_picking_and_completeness() -> None:
    """Attack: an evaluation run has diverse cohort members (determinate, missing

    data, incomplete horizon, delisted with proceeds, delisted without proceeds).
    Attacker expects unresolvable cohort members to silently drop out of the batch.
    Control: every single prediction in the cohort must resolve to an explicit
    terminal state in the batch with 100% accounting completeness.
    """
    recorder = PredictionRecorder(run_id=RUN_ID)
    h = HorizonSpecificationV1(
        horizon_sessions=3,
        anchor_session_date=date(2026, 1, 15),
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 20),
    )

    for sec in [SEC_1, SEC_2, SEC_3, SEC_4, SEC_5]:
        recorder.record_prediction(
            security_id=sec,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=h,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
        )

    pred_set = recorder.seal_epoch(
        session_date=date(2026, 1, 15),
        as_of_time=datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC),
    )
    assert len(pred_set.predictions) == 5

    # SEC_1: Fully determinate series (3 forward sessions)
    s1 = _make_series_from_tuples(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100"), Decimal("1")),
            (date(2026, 1, 16), Decimal("0.01"), Decimal("101"), Decimal("1")),
            (date(2026, 1, 19), Decimal("0.02"), Decimal("103.02"), Decimal("1")),
            (date(2026, 1, 20), Decimal("-0.01"), Decimal("101.9898"), Decimal("1")),
        ],
    )
    # SEC_2: Missing series entirely (no entry in map)
    # SEC_3: Incomplete horizon (only 1 session instead of 3)
    s3 = _make_series_from_tuples(
        SEC_3,
        [
            (date(2026, 1, 15), None, Decimal("100"), Decimal("1")),
            (date(2026, 1, 16), Decimal("0.01"), Decimal("101"), Decimal("1")),
        ],
    )
    # SEC_4: Delisted with authenticated liquidation proceeds
    delisting_4 = DelistingOutcomeInfoV1(
        security_id=SEC_4,
        delisting_date=date(2026, 1, 18),
        has_authenticated_proceeds=True,
        terminal_realized_return=Decimal("0.08"),
        evidence_hashes=("4" * 64,),
    )
    # SEC_5: Delisted without authenticated proceeds
    delisting_5 = DelistingOutcomeInfoV1(
        security_id=SEC_5,
        delisting_date=date(2026, 1, 18),
        has_authenticated_proceeds=False,
        reason="Merger proceeds unverified cash distribution",
        evidence_hashes=("5" * 64,),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 20, 22, 0, 0, tzinfo=UTC)
    batch = resolver.resolve_prediction_set(
        pred_set,
        analytical_series={SEC_1: s1, SEC_3: s3},
        resolved_at=resolved_at,
        delistings={SEC_4: delisting_4, SEC_5: delisting_5},
    )

    # Completeness check: all 5 predictions MUST be accounted for in outcomes
    assert len(batch.outcomes) == 5

    outcomes_by_sec = {}
    for p in pred_set.predictions:
        matched = [o for o in batch.outcomes if o.prediction_id == p.prediction_id]
        assert len(matched) == 1
        outcomes_by_sec[p.security_id] = matched[0]

    # Verify each terminal classification
    assert outcomes_by_sec[SEC_1].status == OutcomeResolutionStatus.RESOLVED
    assert outcomes_by_sec[SEC_1].realized_value is not None

    assert outcomes_by_sec[SEC_2].status == OutcomeResolutionStatus.EXCLUDED_UNAVAILABLE
    assert outcomes_by_sec[SEC_2].indeterminate_reason is not None

    assert outcomes_by_sec[SEC_3].status == OutcomeResolutionStatus.INDETERMINATE
    assert outcomes_by_sec[SEC_3].indeterminate_reason is not None

    assert (
        outcomes_by_sec[SEC_4].status == OutcomeResolutionStatus.DELISTED_WITH_OUTCOME
    )
    assert outcomes_by_sec[SEC_4].realized_value == Decimal("0.08")

    assert (
        outcomes_by_sec[SEC_5].status
        == OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME
    )
    assert outcomes_by_sec[SEC_5].indeterminate_reason is not None


def test_adversarial_corporate_action_invariance() -> None:
    """Attack: a 2-for-1 forward stock split causes unadjusted prices to drop 50%.

    A naive unadjusted return engine would evaluate a false -50% loss.
    Control: corporate-action-consistent analytical return series correctly
    preserves economic ground truth, compound returns, and residual attribution.
    """
    # Stock trades at $100 pre-split. Splits 2:1 on Jan 16, closes at $50 unadjusted
    # (equivalent to $100 analytical, 0.00 return).
    # Then rises to $52 unadjusted on Jan 17 ($104 analytical, +4.0% return from prior).
    split_series = _make_series_from_tuples(
        SEC_1,
        [
            (date(2026, 1, 15), None, Decimal("100"), Decimal("1")),
            (date(2026, 1, 16), Decimal("0.00"), Decimal("100"), Decimal("2")),
            (date(2026, 1, 17), Decimal("0.04"), Decimal("104"), Decimal("2")),
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
        target_type=PredictionTargetType.FORWARD_RETURN,
        target_horizon=h,
        # Model predicted a +3.0% forward gain (+0.03)
        prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.03")),
    )

    resolver = OutcomeResolver()
    resolved_at = datetime(2026, 1, 17, 22, 0, 0, tzinfo=UTC)
    outcome = resolver.resolve_single_prediction(
        pred,
        analytical_series=split_series,
        resolved_at=resolved_at,
    )

    assert outcome.status == OutcomeResolutionStatus.RESOLVED
    # True economic return: (1 + 0.00) * (1 + 0.04) - 1 = +0.04 (+4.0%)
    # Naive unadjusted return would have been 52 / 100 - 1 = -48% (-0.48)!
    assert outcome.realized_value == Decimal("0.04")
    assert outcome.directional_match is True
    assert outcome.error == Decimal("0.04") - Decimal("0.03")


def test_adversarial_replay_determinism(tmp_path: Path) -> None:
    """Attack: execute identical prediction tracking lifecycles across separate runs.

    Control: verify that prediction set hashes, outcome batch hashes, and ledger
    event payloads are bitwise identical across replays.
    """

    def _run_lifecycle(ledger_path: Path) -> tuple[str, str, bytes, bytes]:
        ledger = SQLiteLedger(ledger_path)
        harness = PredictionTrackingHarness(
            run_id=RUN_ID,
            lane="exploratory",
            ledger=ledger,
            deterministic=True,
        )

        # Build 265-session series
        series_1 = _make_series_from_tuples(
            SEC_1,
            [
                (
                    date(2025, 1, 1) + date.resolution * i,
                    None if i == 0 else Decimal("0.001"),
                    Decimal("100") * (Decimal("1.001") ** i),
                    Decimal("1"),
                )
                for i in range(265)
            ],
        )

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

        pred_set = harness.record_and_seal_epoch(
            session_date=anchor_date,
            as_of_time=as_of,
            target_horizon=h,
            predictor=predictor,
            securities=[SEC_1],
            analytical_series={SEC_1: series_1},
        )

        resolved_at = datetime(
            end_date.year, end_date.month, end_date.day, 22, 0, 0, tzinfo=UTC
        )
        batch = harness.resolve_batch(
            prediction_set=pred_set,
            analytical_series={SEC_1: series_1},
            resolved_at=resolved_at,
        )

        events = ledger.events()
        assert len(events) == 2

        pred_event_json = canonical_json(events[0].payload)
        outcome_event_json = canonical_json(events[1].payload)

        return (
            pred_set.set_hash,
            batch.batch_hash,
            pred_event_json,
            outcome_event_json,
        )

    run1_pred_hash, run1_batch_hash, run1_p_json, run1_o_json = _run_lifecycle(
        tmp_path / "run1.db"
    )
    run2_pred_hash, run2_batch_hash, run2_p_json, run2_o_json = _run_lifecycle(
        tmp_path / "run2.db"
    )

    # Replay determinism verification
    assert run1_pred_hash == run2_pred_hash
    assert run1_batch_hash == run2_batch_hash
    assert run1_p_json == run2_p_json
    assert run1_o_json == run2_o_json
