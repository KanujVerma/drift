"""Unit tests for predictive power and calibration metrics engine (M5-2, Issue 191)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    evaluation_run_identity_v2_hash,
)
from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    build_realized_outcome_batch,
    build_realized_outcome_record,
)
from drift.domain.predictions import (
    HorizonSpecificationV1,
    PredictionTargetType,
    ScalarPointPredictionV1,
    build_ex_ante_prediction_record,
    build_ex_ante_prediction_set,
)
from drift.scorecards.predictive import (
    aggregate_information_coefficients,
    compute_calibration_summary,
    compute_pearson_correlation,
    compute_spearman_rank_correlation,
    fractional_ranks,
    generate_prediction_scorecard,
)

RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcde0")
SET_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcde1")
BATCH_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcde2")
SEC_1 = UUID("00000000-0000-7000-8000-000000000001")
SEC_2 = UUID("00000000-0000-7000-8000-000000000002")
SEC_3 = UUID("00000000-0000-7000-8000-000000000003")
SEC_4 = UUID("00000000-0000-7000-8000-000000000004")
SEC_5 = UUID("00000000-0000-7000-8000-000000000005")
AS_OF = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)
SESSION_DATE = date(2026, 1, 15)


def make_run_identity_v2(**overrides: Any) -> EvaluationRunIdentityV2:
    fields = {
        "strategy_hash": "a" * 64,
        "strategy_parameters_hash": "b" * 64,
        "protocol_hash": "c" * 64,
        "cost_model_hash": "d" * 64,
        "admission_hash": "e" * 64,
        "bundle_hash": "f" * 64,
        "evaluator_evidence_hash": "1" * 64,
        "code_version_hash": "2" * 64,
        "environment_closure_hash": "3" * 64,
        "run_identity_hash": "0" * 64,
        **overrides,
    }
    draft = EvaluationRunIdentityV2.model_construct(schema_version="2", **fields)
    expected = evaluation_run_identity_v2_hash(draft)
    return EvaluationRunIdentityV2.model_validate(
        {**fields, "run_identity_hash": expected}
    )


# =========================================================================
# Unit tests: fractional_ranks
# =========================================================================


def test_fractional_ranks_empty_and_single() -> None:
    assert fractional_ranks([]) == []
    assert fractional_ranks([Decimal("42")]) == [Decimal("1")]


def test_fractional_ranks_distinct() -> None:
    ranks = fractional_ranks([Decimal("10"), Decimal("20"), Decimal("30")])
    assert ranks == [Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]


def test_fractional_ranks_with_ties() -> None:
    # 10 is rank 1; 20 and 20 are ranks 2 and 3 -> avg 2.5; 30 is rank 4
    vals = [Decimal("10"), Decimal("20"), Decimal("20"), Decimal("30")]
    assert fractional_ranks(vals) == [
        Decimal("1.0"),
        Decimal("2.5"),
        Decimal("2.5"),
        Decimal("4.0"),
    ]


def test_fractional_ranks_all_identical() -> None:
    vals = [Decimal("5"), Decimal("5"), Decimal("5")]
    assert fractional_ranks(vals) == [
        Decimal("2.0"),
        Decimal("2.0"),
        Decimal("2.0"),
    ]


def test_fractional_ranks_reverse_sorted() -> None:
    vals = [Decimal("30"), Decimal("20"), Decimal("10")]
    assert fractional_ranks(vals) == [
        Decimal("3.0"),
        Decimal("2.0"),
        Decimal("1.0"),
    ]


# =========================================================================
# Unit tests: compute_pearson_correlation
# =========================================================================


def test_pearson_correlation_perfect_positive() -> None:
    x = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    y = [Decimal("2"), Decimal("4"), Decimal("6"), Decimal("8")]
    r = compute_pearson_correlation(x, y)
    assert r == Decimal("1.0000")


def test_pearson_correlation_perfect_negative() -> None:
    x = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    y = [Decimal("8"), Decimal("6"), Decimal("4"), Decimal("2")]
    r = compute_pearson_correlation(x, y)
    assert r == Decimal("-1.0000")


def test_pearson_correlation_zero_variance() -> None:
    x = [Decimal("5"), Decimal("5"), Decimal("5")]
    y = [Decimal("1"), Decimal("2"), Decimal("3")]
    assert compute_pearson_correlation(x, y) == Decimal("0")


def test_pearson_correlation_insufficient_samples() -> None:
    assert compute_pearson_correlation([Decimal("1")], [Decimal("2")]) is None


# =========================================================================
# Unit tests: compute_spearman_rank_correlation
# =========================================================================


def test_spearman_rank_correlation_nonlinear_monotonic() -> None:
    # Cubic relationship is nonlinearly monotonic
    x = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    y = [Decimal("1"), Decimal("8"), Decimal("27"), Decimal("64")]
    # Spearman should be exactly 1.0 even if Pearson is slightly less
    r = compute_spearman_rank_correlation(x, y)
    assert r == Decimal("1.0000")


def test_spearman_rank_correlation_inverted() -> None:
    x = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    y = [Decimal("64"), Decimal("27"), Decimal("8"), Decimal("1")]
    r = compute_spearman_rank_correlation(x, y)
    assert r == Decimal("-1.0000")


def test_spearman_rank_correlation_with_ties() -> None:
    x = [Decimal("1"), Decimal("2"), Decimal("2"), Decimal("4")]
    y = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]
    r = compute_spearman_rank_correlation(x, y)
    assert r is not None
    assert r > Decimal("0.9")


# =========================================================================
# Unit tests: aggregate_information_coefficients
# =========================================================================


def test_aggregate_ic_empty() -> None:
    summary = aggregate_information_coefficients([])
    assert summary.evaluated_sessions == 0
    assert summary.mean_spearman_ic == Decimal("0")


def test_aggregate_ic_series() -> None:
    ics = [
        Decimal("0.08"),
        Decimal("0.12"),
        Decimal("0.04"),
        Decimal("0.16"),
    ]
    summary = aggregate_information_coefficients(ics)
    assert summary.evaluated_sessions == 4
    assert summary.mean_spearman_ic == Decimal("0.1000")
    assert summary.positive_ic_ratio == Decimal("1.0000")
    assert summary.std_spearman_ic > Decimal("0")
    assert summary.information_ratio_ic > Decimal("0")
    assert summary.t_statistic_ic > Decimal("0")


def test_aggregate_ic_with_quantile_monotonicity() -> None:
    ics = [Decimal("0.05"), Decimal("0.06")]
    # 5 quantiles monotonically increasing in returns
    quantile_rets = [
        [
            Decimal("-0.02"),
            Decimal("-0.01"),
            Decimal("0.00"),
            Decimal("0.01"),
            Decimal("0.03"),
        ],
        [
            Decimal("-0.01"),
            Decimal("-0.005"),
            Decimal("0.005"),
            Decimal("0.015"),
            Decimal("0.025"),
        ],
    ]
    summary = aggregate_information_coefficients(ics, quantile_returns=quantile_rets)
    assert summary.is_rank_monotonic is True
    assert summary.quantile_spread_return is not None
    assert summary.quantile_spread_return > Decimal("0")


def test_aggregate_ic_non_monotonic() -> None:
    ics = [Decimal("0.02")]
    quantile_rets = [
        [
            Decimal("0.05"),
            Decimal("0.01"),
            Decimal("0.04"),
            Decimal("0.02"),
            Decimal("0.03"),
        ]
    ]
    summary = aggregate_information_coefficients(ics, quantile_returns=quantile_rets)
    assert summary.is_rank_monotonic is False


# =========================================================================
# Unit tests: compute_calibration_summary
# =========================================================================


def test_compute_calibration_summary_continuous() -> None:
    preds = [Decimal("0.02"), Decimal("0.05"), Decimal("-0.01")]
    truth = [Decimal("0.01"), Decimal("0.04"), Decimal("-0.02")]
    summary = compute_calibration_summary(preds, truth, is_binary=False)
    assert summary.mean_absolute_error == Decimal("0.0100")
    assert summary.root_mean_squared_error == Decimal("0.0100")
    assert summary.brier_score is None


def test_compute_calibration_summary_binary() -> None:
    preds = [Decimal("0.85"), Decimal("0.15"), Decimal("0.70"), Decimal("0.30")]
    truth = [Decimal("1.00"), Decimal("0.00"), Decimal("1.00"), Decimal("0.00")]
    summary = compute_calibration_summary(preds, truth, num_bins=5, is_binary=True)
    assert summary.brier_score is not None
    assert summary.brier_score < Decimal("0.1")
    assert summary.expected_calibration_error is not None
    assert summary.maximum_calibration_error is not None
    assert len(summary.bins) == 5


# =========================================================================
# Unit tests: generate_prediction_scorecard end-to-end
# =========================================================================


def test_generate_prediction_scorecard_end_to_end() -> None:
    identity = make_run_identity_v2()

    horizon = HorizonSpecificationV1(
        horizon_sessions=1,
        anchor_session_date=SESSION_DATE,
        start_session_date=date(2026, 1, 16),
        end_session_date=date(2026, 1, 16),
    )

    # 5 predictions in cross-section
    pred_records = [
        build_ex_ante_prediction_record(
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd11"),
            run_id=RUN_ID,
            security_id=SEC_1,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            as_of_time=AS_OF,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.01")),
            input_context_hash="0" * 64,
            model_provenance_hash="0" * 64,
        ),
        build_ex_ante_prediction_record(
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd12"),
            run_id=RUN_ID,
            security_id=SEC_2,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            as_of_time=AS_OF,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.02")),
            input_context_hash="0" * 64,
            model_provenance_hash="0" * 64,
        ),
        build_ex_ante_prediction_record(
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd13"),
            run_id=RUN_ID,
            security_id=SEC_3,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            as_of_time=AS_OF,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.03")),
            input_context_hash="0" * 64,
            model_provenance_hash="0" * 64,
        ),
        build_ex_ante_prediction_record(
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd14"),
            run_id=RUN_ID,
            security_id=SEC_4,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            as_of_time=AS_OF,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.04")),
            input_context_hash="0" * 64,
            model_provenance_hash="0" * 64,
        ),
        build_ex_ante_prediction_record(
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd15"),
            run_id=RUN_ID,
            security_id=SEC_5,
            target_type=PredictionTargetType.FORWARD_RETURN,
            target_horizon=horizon,
            as_of_time=AS_OF,
            prediction_value=ScalarPointPredictionV1(point_value=Decimal("0.05")),
            input_context_hash="0" * 64,
            model_provenance_hash="0" * 64,
        ),
    ]

    pred_set = build_ex_ante_prediction_set(
        prediction_set_id=SET_ID,
        run_id=RUN_ID,
        session_date=SESSION_DATE,
        as_of_time=AS_OF,
        lane="exploratory",
        predictions=pred_records,
    )

    # 4 resolved outcomes and 1 delisted
    outcome_records = [
        build_realized_outcome_record(
            outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd21"),
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd11"),
            status=OutcomeResolutionStatus.RESOLVED,
            resolved_at=AS_OF,
            realized_value=Decimal("0.015"),
            error=Decimal("0.005"),
            directional_match=True,
            evidence_hashes=("1" * 64,),
        ),
        build_realized_outcome_record(
            outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd22"),
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd12"),
            status=OutcomeResolutionStatus.RESOLVED,
            resolved_at=AS_OF,
            realized_value=Decimal("0.022"),
            error=Decimal("0.002"),
            directional_match=True,
            evidence_hashes=("1" * 64,),
        ),
        build_realized_outcome_record(
            outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd23"),
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd13"),
            status=OutcomeResolutionStatus.RESOLVED,
            resolved_at=AS_OF,
            realized_value=Decimal("0.028"),
            error=Decimal("-0.002"),
            directional_match=True,
            evidence_hashes=("1" * 64,),
        ),
        build_realized_outcome_record(
            outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd24"),
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd14"),
            status=OutcomeResolutionStatus.RESOLVED,
            resolved_at=AS_OF,
            realized_value=Decimal("0.042"),
            error=Decimal("0.002"),
            directional_match=True,
            evidence_hashes=("1" * 64,),
        ),
        build_realized_outcome_record(
            outcome_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd25"),
            prediction_id=UUID("018f3a5b-6c7d-7890-8123-456789abcd15"),
            status=OutcomeResolutionStatus.DELISTED_WITH_OUTCOME,
            resolved_at=AS_OF,
            realized_value=Decimal("0.000"),
            evidence_hashes=("1" * 64,),
        ),
    ]

    outcome_batch = build_realized_outcome_batch(
        outcome_batch_id=BATCH_ID,
        run_id=RUN_ID,
        resolved_at=AS_OF,
        lane="exploratory",
        outcomes=outcome_records,
    )

    card = generate_prediction_scorecard(
        prediction_sets=[pred_set],
        outcome_batches=[outcome_batch],
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        as_of_time=AS_OF,
    )

    assert card.total_predictions == 5
    assert card.resolved_predictions == 4
    assert card.delisted_predictions == 1
    assert card.indeterminate_predictions == 0
    assert card.ic_summary.evaluated_sessions == 1
    # Ranked predictions [0.01, 0.02, 0.03, 0.04] against [0.015, 0.022, 0.028, 0.042]
    # are monotonically concordant, so Spearman IC is 1.0!
    assert card.ic_summary.mean_spearman_ic == Decimal("1.0000")
    assert card.calibration_summary.mean_absolute_error is not None
