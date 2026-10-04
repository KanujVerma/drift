"""Unit tests for statistical scorecard domain models (M5-1, Issue 189)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    evaluation_run_identity_v2_hash,
)
from drift.domain.evaluator_results import (
    ExcludedDisposalV1,
    RealizedPnLCompletenessV1,
)
from drift.domain.predictions import PredictionTargetType
from drift.domain.scorecards import (
    CalibrationBinV1,
    CalibrationSummaryV1,
    DrawdownProfileV1,
    InformationCoefficientSummaryV1,
    MetricSummaryV1,
    MultipleTestingSummaryV1,
    PredictionScorecardV1,
    TurnoverSummaryV1,
    build_model_scorecard,
    build_prediction_scorecard,
    build_strategy_scorecard,
    compute_model_scorecard_hash,
    compute_prediction_scorecard_hash,
    compute_strategy_scorecard_hash,
)
from drift.domain.sessions import SessionKeyV1

SCORECARD_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcd01")
SCORECARD_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcd02")
COMPOSITE_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd03")
CREATED_AT = datetime(2026, 1, 15, 21, 0, 0, tzinfo=UTC)


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


def make_sample_ic_summary() -> InformationCoefficientSummaryV1:
    return InformationCoefficientSummaryV1(
        mean_spearman_ic=Decimal("0.0520"),
        std_spearman_ic=Decimal("0.1200"),
        information_ratio_ic=Decimal("0.4333"),
        t_statistic_ic=Decimal("2.4500"),
        positive_ic_ratio=Decimal("0.6200"),
        mean_pearson_ic=Decimal("0.0480"),
        evaluated_sessions=32,
        quantile_spread_return=Decimal("0.0150"),
        is_rank_monotonic=True,
    )


def make_sample_calibration_summary() -> CalibrationSummaryV1:
    bins = (
        CalibrationBinV1(
            bin_index=0,
            bin_lower=Decimal("0.0"),
            bin_upper=Decimal("0.5"),
            predicted_confidence=Decimal("0.35"),
            empirical_accuracy=Decimal("0.38"),
            sample_count=50,
        ),
        CalibrationBinV1(
            bin_index=1,
            bin_lower=Decimal("0.5"),
            bin_upper=Decimal("1.0"),
            predicted_confidence=Decimal("0.75"),
            empirical_accuracy=Decimal("0.72"),
            sample_count=50,
        ),
    )
    return CalibrationSummaryV1(
        brier_score=Decimal("0.1820"),
        expected_calibration_error=Decimal("0.0350"),
        maximum_calibration_error=Decimal("0.0420"),
        calibration_slope=Decimal("0.9500"),
        calibration_intercept=Decimal("0.0200"),
        mean_absolute_error=Decimal("0.0210"),
        root_mean_squared_error=Decimal("0.0315"),
        bins=bins,
    )


def make_sample_drawdown_profile() -> DrawdownProfileV1:
    return DrawdownProfileV1(
        maximum_drawdown=Decimal("-0.0850"),
        max_drawdown_duration_sessions=14,
        peak_to_trough_sessions=6,
        recovery_sessions=8,
        current_drawdown=Decimal("0.0000"),
        is_recovered=True,
    )


def make_sample_turnover_summary() -> TurnoverSummaryV1:
    return TurnoverSummaryV1(
        mean_session_turnover=Decimal("0.0450"),
        annualized_turnover=Decimal("11.3400"),
        estimated_cost_drag=Decimal("0.0025"),
    )


def make_sample_multiple_testing_summary() -> MultipleTestingSummaryV1:
    return MultipleTestingSummaryV1(
        trial_count=20,
        sharpe_trial_variance=Decimal("0.2500"),
        expected_max_null_sharpe=Decimal("1.2500"),
        deflated_sharpe_ratio=Decimal("0.9650"),
        is_dsr_significant_at_95=True,
        bonferroni_adjusted_p_value=Decimal("0.0320"),
        holm_adjusted_p_value=Decimal("0.0280"),
        benjamini_hochberg_fdr_q=Decimal("0.0150"),
    )


# =========================================================================
# Unit tests: MetricSummaryV1
# =========================================================================


def test_metric_summary_valid() -> None:
    metric = MetricSummaryV1(
        metric_name="annualized_sharpe",
        value=Decimal("1.85"),
        standard_error=Decimal("0.35"),
        t_statistic=Decimal("5.28"),
        p_value=Decimal("0.001"),
        sample_size=100,
    )
    assert metric.metric_name == "annualized_sharpe"
    assert metric.value == Decimal("1.85")
    assert metric.sample_size == 100


def test_metric_summary_rejects_negative_sample_size() -> None:
    with pytest.raises(
        ValidationError, match="Input should be greater than or equal to 0"
    ):
        MetricSummaryV1(
            metric_name="test_metric",
            value=Decimal("1.0"),
            sample_size=-1,
        )


def test_metric_summary_rejects_invalid_p_value() -> None:
    with pytest.raises(ValidationError, match="p_value must be within \\[0, 1\\]"):
        MetricSummaryV1(
            metric_name="test_metric",
            value=Decimal("1.0"),
            p_value=Decimal("1.5"),
            sample_size=10,
        )


# =========================================================================
# Unit tests: InformationCoefficientSummaryV1
# =========================================================================


def test_ic_summary_valid() -> None:
    ic = make_sample_ic_summary()
    assert ic.mean_spearman_ic == Decimal("0.0520")
    assert ic.is_rank_monotonic is True


def test_ic_summary_rejects_negative_std() -> None:
    with pytest.raises(
        ValidationError, match="Input should be greater than or equal to 0"
    ):
        InformationCoefficientSummaryV1(
            mean_spearman_ic=Decimal("0.05"),
            std_spearman_ic=Decimal("-0.01"),
            information_ratio_ic=Decimal("0.5"),
            t_statistic_ic=Decimal("2.0"),
            positive_ic_ratio=Decimal("0.6"),
            mean_pearson_ic=Decimal("0.04"),
            evaluated_sessions=10,
        )


def test_ic_summary_rejects_invalid_positive_ratio() -> None:
    with pytest.raises(
        ValidationError, match="positive_ic_ratio must be within \\[0, 1\\]"
    ):
        InformationCoefficientSummaryV1(
            mean_spearman_ic=Decimal("0.05"),
            std_spearman_ic=Decimal("0.1"),
            information_ratio_ic=Decimal("0.5"),
            t_statistic_ic=Decimal("2.0"),
            positive_ic_ratio=Decimal("1.2"),
            mean_pearson_ic=Decimal("0.04"),
            evaluated_sessions=10,
        )


# =========================================================================
# Unit tests: CalibrationBinV1 & CalibrationSummaryV1
# =========================================================================


def test_calibration_bin_valid() -> None:
    b = CalibrationBinV1(
        bin_index=0,
        bin_lower=Decimal("0.1"),
        bin_upper=Decimal("0.2"),
        predicted_confidence=Decimal("0.15"),
        empirical_accuracy=Decimal("0.14"),
        sample_count=20,
    )
    assert b.sample_count == 20


def test_calibration_bin_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError, match="bin_lower cannot exceed bin_upper"):
        CalibrationBinV1(
            bin_index=0,
            bin_lower=Decimal("0.8"),
            bin_upper=Decimal("0.2"),
            predicted_confidence=Decimal("0.5"),
            empirical_accuracy=Decimal("0.5"),
            sample_count=10,
        )


def test_calibration_summary_rejects_negative_brier() -> None:
    with pytest.raises(
        ValidationError, match="calibration metric value must be non-negative"
    ):
        CalibrationSummaryV1(
            brier_score=Decimal("-0.05"),
        )


# =========================================================================
# Unit tests: DrawdownProfileV1 & TurnoverSummaryV1
# =========================================================================


def test_drawdown_profile_valid() -> None:
    dd = make_sample_drawdown_profile()
    assert dd.maximum_drawdown == Decimal("-0.0850")
    assert dd.is_recovered is True


def test_drawdown_profile_rejects_positive_drawdown() -> None:
    with pytest.raises(ValidationError, match="drawdown values cannot be positive"):
        DrawdownProfileV1(
            maximum_drawdown=Decimal("0.05"),
            max_drawdown_duration_sessions=10,
            peak_to_trough_sessions=5,
            recovery_sessions=5,
            current_drawdown=Decimal("0.0"),
            is_recovered=True,
        )


def test_turnover_summary_rejects_negative_turnover() -> None:
    with pytest.raises(
        ValidationError, match="Input should be greater than or equal to 0"
    ):
        TurnoverSummaryV1(
            mean_session_turnover=Decimal("-0.01"),
            annualized_turnover=Decimal("2.5"),
            estimated_cost_drag=Decimal("0.001"),
        )


# =========================================================================
# Unit tests: MultipleTestingSummaryV1
# =========================================================================


def test_multiple_testing_summary_valid() -> None:
    mt = make_sample_multiple_testing_summary()
    assert mt.trial_count == 20
    assert mt.is_dsr_significant_at_95 is True


def test_multiple_testing_summary_rejects_zero_trials() -> None:
    with pytest.raises(
        ValidationError, match="Input should be greater than or equal to 1"
    ):
        MultipleTestingSummaryV1(
            trial_count=0,
            sharpe_trial_variance=Decimal("0.1"),
            expected_max_null_sharpe=Decimal("1.0"),
            deflated_sharpe_ratio=Decimal("0.9"),
            is_dsr_significant_at_95=False,
            bonferroni_adjusted_p_value=Decimal("0.1"),
            holm_adjusted_p_value=Decimal("0.1"),
            benjamini_hochberg_fdr_q=Decimal("0.1"),
        )


# =========================================================================
# Unit tests: PredictionScorecardV1
# =========================================================================


def test_prediction_scorecard_build_and_validate() -> None:
    identity = make_run_identity_v2()
    card = build_prediction_scorecard(
        scorecard_id=SCORECARD_ID_1,
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        ic_summary=make_sample_ic_summary(),
        calibration_summary=make_sample_calibration_summary(),
        total_predictions=100,
        resolved_predictions=90,
        indeterminate_predictions=5,
        delisted_predictions=5,
        created_at=CREATED_AT,
    )
    assert card.scorecard_id == SCORECARD_ID_1
    assert card.lane == "exploratory"
    assert card.total_predictions == 100
    assert card.scorecard_hash == compute_prediction_scorecard_hash(card)


def test_prediction_scorecard_rejects_exceeded_prediction_counts() -> None:
    identity = make_run_identity_v2()
    with pytest.raises(
        ValidationError,
        match="sum of resolved, indeterminate, and delisted predictions exceeds total",
    ):
        build_prediction_scorecard(
            scorecard_id=SCORECARD_ID_1,
            run_identity=identity,
            lane="exploratory",
            prediction_target=PredictionTargetType.FORWARD_RETURN,
            ic_summary=make_sample_ic_summary(),
            calibration_summary=make_sample_calibration_summary(),
            total_predictions=100,
            resolved_predictions=95,
            indeterminate_predictions=10,
            delisted_predictions=0,
            created_at=CREATED_AT,
        )


def test_prediction_scorecard_rejects_tampered_hash() -> None:
    identity = make_run_identity_v2()
    card = build_prediction_scorecard(
        scorecard_id=SCORECARD_ID_1,
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        ic_summary=make_sample_ic_summary(),
        calibration_summary=make_sample_calibration_summary(),
        total_predictions=100,
        resolved_predictions=90,
        indeterminate_predictions=5,
        delisted_predictions=5,
        created_at=CREATED_AT,
    )
    tampered_data = card.model_dump()
    tampered_data["scorecard_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="prediction scorecard hash mismatch"):
        PredictionScorecardV1.model_validate(tampered_data)


# =========================================================================
# Unit tests: StrategyScorecardV1
# =========================================================================


def test_strategy_scorecard_build_and_validate() -> None:
    identity = make_run_identity_v2()
    pnl_comp = RealizedPnLCompletenessV1(
        is_complete=True,
        excluded_disposals=(),
    )
    card = build_strategy_scorecard(
        scorecard_id=SCORECARD_ID_2,
        run_identity=identity,
        lane="exploratory",
        cumulative_return=Decimal("0.1450"),
        annualized_return=Decimal("0.1820"),
        annualized_volatility=Decimal("0.1150"),
        downside_deviation=Decimal("0.0780"),
        sharpe_ratio=Decimal("1.5826"),
        sortino_ratio=Decimal("2.3333"),
        calmar_ratio=Decimal("2.1412"),
        drawdown_profile=make_sample_drawdown_profile(),
        turnover_summary=make_sample_turnover_summary(),
        pnl_completeness=pnl_comp,
        created_at=CREATED_AT,
    )
    assert card.scorecard_id == SCORECARD_ID_2
    assert card.sharpe_ratio == Decimal("1.5826")
    assert card.pnl_completeness.is_complete is True
    assert card.scorecard_hash == compute_strategy_scorecard_hash(card)


def test_strategy_scorecard_with_incomplete_pnl() -> None:
    identity = make_run_identity_v2()
    disposal = ExcludedDisposalV1(
        security_id=UUID("00000000-0000-7000-8000-000000000001"),
        source_id="src-1",
        action_kind=ActionKind.SPINOFF,
        occurrence_id="occ-1",
        component_id="cmp-1",
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
        ),
        cash_proceeds=Decimal("10.50"),
        reason="unallocated parent cost basis for spin-off child residual disposal",
        applied_effect_id="1" * 64,
    )
    pnl_comp = RealizedPnLCompletenessV1(
        is_complete=False,
        excluded_disposals=(disposal,),
    )
    card = build_strategy_scorecard(
        scorecard_id=SCORECARD_ID_2,
        run_identity=identity,
        lane="exploratory",
        cumulative_return=Decimal("0.1200"),
        annualized_return=Decimal("0.1500"),
        annualized_volatility=Decimal("0.1200"),
        downside_deviation=Decimal("0.0800"),
        sharpe_ratio=Decimal("1.2500"),
        sortino_ratio=Decimal("1.8750"),
        calmar_ratio=Decimal("1.7647"),
        drawdown_profile=make_sample_drawdown_profile(),
        turnover_summary=make_sample_turnover_summary(),
        pnl_completeness=pnl_comp,
        created_at=CREATED_AT,
    )
    assert card.pnl_completeness.is_complete is False
    assert len(card.pnl_completeness.excluded_disposals) == 1


# =========================================================================
# Unit tests: ModelScorecardV1
# =========================================================================


def test_model_scorecard_composite() -> None:
    identity = make_run_identity_v2()
    pred_card = build_prediction_scorecard(
        scorecard_id=SCORECARD_ID_1,
        run_identity=identity,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        ic_summary=make_sample_ic_summary(),
        calibration_summary=make_sample_calibration_summary(),
        total_predictions=100,
        resolved_predictions=90,
        indeterminate_predictions=5,
        delisted_predictions=5,
        created_at=CREATED_AT,
    )
    strat_card = build_strategy_scorecard(
        scorecard_id=SCORECARD_ID_2,
        run_identity=identity,
        lane="exploratory",
        cumulative_return=Decimal("0.1450"),
        annualized_return=Decimal("0.1820"),
        annualized_volatility=Decimal("0.1150"),
        downside_deviation=Decimal("0.0780"),
        sharpe_ratio=Decimal("1.5826"),
        sortino_ratio=Decimal("2.3333"),
        calmar_ratio=Decimal("2.1412"),
        drawdown_profile=make_sample_drawdown_profile(),
        turnover_summary=make_sample_turnover_summary(),
        pnl_completeness=RealizedPnLCompletenessV1(
            is_complete=True, excluded_disposals=()
        ),
        created_at=CREATED_AT,
    )
    mt_summary = make_sample_multiple_testing_summary()

    composite = build_model_scorecard(
        scorecard_id=COMPOSITE_ID,
        run_identity=identity,
        lane="exploratory",
        prediction_scorecard=pred_card,
        strategy_scorecard=strat_card,
        multiple_testing=mt_summary,
        created_at=CREATED_AT,
    )
    assert composite.scorecard_id == COMPOSITE_ID
    assert composite.prediction_scorecard is not None
    assert composite.strategy_scorecard is not None
    assert composite.multiple_testing is not None
    assert composite.scorecard_hash == compute_model_scorecard_hash(composite)


def test_model_scorecard_rejects_empty_sub_scorecards() -> None:
    identity = make_run_identity_v2()
    with pytest.raises(
        ValidationError,
        match="at least one sub-scorecard must be provided in ModelScorecardV1",
    ):
        build_model_scorecard(
            scorecard_id=COMPOSITE_ID,
            run_identity=identity,
            lane="exploratory",
            prediction_scorecard=None,
            strategy_scorecard=None,
            multiple_testing=None,
            created_at=CREATED_AT,
        )


def test_model_scorecard_rejects_mismatched_run_identity() -> None:
    identity_1 = make_run_identity_v2(strategy_hash="1" * 64)
    identity_2 = make_run_identity_v2(strategy_hash="2" * 64)
    pred_card = build_prediction_scorecard(
        scorecard_id=SCORECARD_ID_1,
        run_identity=identity_1,
        lane="exploratory",
        prediction_target=PredictionTargetType.FORWARD_RETURN,
        ic_summary=make_sample_ic_summary(),
        calibration_summary=make_sample_calibration_summary(),
        total_predictions=100,
        resolved_predictions=90,
        indeterminate_predictions=5,
        delisted_predictions=5,
        created_at=CREATED_AT,
    )
    with pytest.raises(
        ValidationError, match="prediction scorecard run_identity mismatch"
    ):
        build_model_scorecard(
            scorecard_id=COMPOSITE_ID,
            run_identity=identity_2,
            lane="exploratory",
            prediction_scorecard=pred_card,
            created_at=CREATED_AT,
        )


def test_model_scorecard_immutability() -> None:
    identity = make_run_identity_v2()
    strat_card = build_strategy_scorecard(
        scorecard_id=SCORECARD_ID_2,
        run_identity=identity,
        lane="exploratory",
        cumulative_return=Decimal("0.1450"),
        annualized_return=Decimal("0.1820"),
        annualized_volatility=Decimal("0.1150"),
        downside_deviation=Decimal("0.0780"),
        sharpe_ratio=Decimal("1.5826"),
        sortino_ratio=Decimal("2.3333"),
        calmar_ratio=Decimal("2.1412"),
        drawdown_profile=make_sample_drawdown_profile(),
        turnover_summary=make_sample_turnover_summary(),
        pnl_completeness=RealizedPnLCompletenessV1(
            is_complete=True, excluded_disposals=()
        ),
        created_at=CREATED_AT,
    )
    with pytest.raises(ValidationError):
        strat_card.cumulative_return = Decimal("0.9999")
