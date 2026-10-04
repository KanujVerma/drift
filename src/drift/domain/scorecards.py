"""Statistical and model scorecard domain models (M5-1, Issue 189).

Provides immutable domain models for quantitative forecast evaluation,
information coefficients, probabilistic calibration, risk attribution,
drawdown profiles, portfolio turnover, multiple-testing adjustments,
content hashing, and M0 research ledger persistence.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_bundles import EvaluationRunIdentityV2
from drift.domain.evaluator_portfolio import EvaluationLane
from drift.domain.evaluator_results import RealizedPnLCompletenessV1
from drift.domain.predictions import PredictionTargetType
from drift.serialization.canonical import content_hash

SCORECARD_SCHEMA_VERSION: Literal["1"] = "1"
SCORECARD_EVENT_TYPE: NonBlankStr = "m5.scorecard.recorded"


class ScorecardType(StrEnum):
    """Classification of statistical scorecard artifact."""

    PREDICTION = "prediction"
    STRATEGY = "strategy"
    COMPOSITE = "composite"


class MetricSummaryV1(FrozenModel):
    """Scalar metric summary with sample size and statistical bounds."""

    metric_name: NonBlankStr
    value: Decimal
    standard_error: Decimal | None = None
    t_statistic: Decimal | None = None
    p_value: Decimal | None = None
    sample_size: int = Field(ge=0)

    @field_validator("p_value")
    @classmethod
    def validate_p_value(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError("p_value must be within [0, 1]")
        return v


class InformationCoefficientSummaryV1(FrozenModel):
    """Rank and linear correlation summary across decision epochs."""

    mean_spearman_ic: Decimal
    std_spearman_ic: Decimal = Field(ge=Decimal("0"))
    information_ratio_ic: Decimal
    t_statistic_ic: Decimal
    positive_ic_ratio: Decimal
    mean_pearson_ic: Decimal
    evaluated_sessions: int = Field(ge=0)
    quantile_spread_return: Decimal | None = None
    is_rank_monotonic: bool | None = None

    @field_validator("positive_ic_ratio")
    @classmethod
    def validate_positive_ic_ratio(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError("positive_ic_ratio must be within [0, 1]")
        return v


class CalibrationBinV1(FrozenModel):
    """Empirical calibration bin for reliability diagrams."""

    bin_index: int = Field(ge=0)
    bin_lower: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    bin_upper: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    predicted_confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    empirical_accuracy: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    sample_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_bin_bounds(self) -> Self:
        if self.bin_lower > self.bin_upper:
            raise ValueError("bin_lower cannot exceed bin_upper")
        return self


class CalibrationSummaryV1(FrozenModel):
    """Probabilistic and directional calibration summary."""

    brier_score: Decimal | None = None
    expected_calibration_error: Decimal | None = None
    maximum_calibration_error: Decimal | None = None
    calibration_slope: Decimal | None = None
    calibration_intercept: Decimal | None = None
    mean_absolute_error: Decimal | None = None
    root_mean_squared_error: Decimal | None = None
    bins: tuple[CalibrationBinV1, ...] = ()

    @field_validator(
        "brier_score", "expected_calibration_error", "maximum_calibration_error"
    )
    @classmethod
    def validate_non_negative_probabilities(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < Decimal("0"):
            raise ValueError("calibration metric value must be non-negative")
        return v

    @field_validator("mean_absolute_error", "root_mean_squared_error")
    @classmethod
    def validate_non_negative_errors(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < Decimal("0"):
            raise ValueError("error metric must be non-negative")
        return v


class DrawdownProfileV1(FrozenModel):
    """Drawdown and underwater trajectory profile."""

    maximum_drawdown: Decimal
    max_drawdown_duration_sessions: int = Field(ge=0)
    peak_to_trough_sessions: int = Field(ge=0)
    recovery_sessions: int = Field(ge=0)
    current_drawdown: Decimal
    is_recovered: bool

    @field_validator("maximum_drawdown", "current_drawdown")
    @classmethod
    def validate_drawdown_non_positive(cls, v: Decimal) -> Decimal:
        if v > Decimal("0"):
            raise ValueError("drawdown values cannot be positive")
        return v


class TurnoverSummaryV1(FrozenModel):
    """Portfolio turnover and transaction cost drag metrics."""

    mean_session_turnover: Decimal = Field(ge=Decimal("0"))
    annualized_turnover: Decimal = Field(ge=Decimal("0"))
    estimated_cost_drag: Decimal = Field(ge=Decimal("0"))


class MultipleTestingSummaryV1(FrozenModel):
    """Multiple-testing and selection-bias adjustments."""

    trial_count: int = Field(ge=1)
    sharpe_trial_variance: Decimal = Field(ge=Decimal("0"))
    expected_max_null_sharpe: Decimal
    deflated_sharpe_ratio: Decimal
    is_dsr_significant_at_95: bool
    bonferroni_adjusted_p_value: Decimal
    holm_adjusted_p_value: Decimal
    benjamini_hochberg_fdr_q: Decimal

    @field_validator(
        "deflated_sharpe_ratio",
        "bonferroni_adjusted_p_value",
        "holm_adjusted_p_value",
        "benjamini_hochberg_fdr_q",
    )
    @classmethod
    def validate_unit_interval(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError("probability/ratio must be within [0, 1]")
        return v


class PredictionScorecardV1(FrozenModel):
    """Ex-ante prediction quality and calibration scorecard."""

    schema_version: Literal["1"] = SCORECARD_SCHEMA_VERSION
    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    prediction_target: PredictionTargetType
    ic_summary: InformationCoefficientSummaryV1
    calibration_summary: CalibrationSummaryV1
    total_predictions: int = Field(ge=0)
    resolved_predictions: int = Field(ge=0)
    indeterminate_predictions: int = Field(ge=0)
    delisted_predictions: int = Field(ge=0)
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_prediction_scorecard(self) -> Self:
        if (
            self.resolved_predictions
            + self.indeterminate_predictions
            + self.delisted_predictions
            > self.total_predictions
        ):
            raise ValueError(
                "sum of resolved, indeterminate, and delisted predictions exceeds total"
            )
        expected_hash = compute_prediction_scorecard_hash(self)
        if self.scorecard_hash != expected_hash:
            raise ValueError("prediction scorecard hash mismatch")
        return self


class StrategyScorecardV1(FrozenModel):
    """Session portfolio accounting, risk, and drawdown scorecard."""

    schema_version: Literal["1"] = SCORECARD_SCHEMA_VERSION
    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    cumulative_return: Decimal
    annualized_return: Decimal
    annualized_volatility: Decimal = Field(ge=Decimal("0"))
    downside_deviation: Decimal = Field(ge=Decimal("0"))
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    calmar_ratio: Decimal
    drawdown_profile: DrawdownProfileV1
    turnover_summary: TurnoverSummaryV1
    pnl_completeness: RealizedPnLCompletenessV1
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_strategy_scorecard(self) -> Self:
        expected_hash = compute_strategy_scorecard_hash(self)
        if self.scorecard_hash != expected_hash:
            raise ValueError("strategy scorecard hash mismatch")
        return self


class ModelScorecardV1(FrozenModel):
    """Composite quantitative scorecard combining prediction, strategy, and testing."""

    schema_version: Literal["1"] = SCORECARD_SCHEMA_VERSION
    scorecard_id: UUID7
    run_identity: EvaluationRunIdentityV2
    lane: EvaluationLane
    prediction_scorecard: PredictionScorecardV1 | None = None
    strategy_scorecard: StrategyScorecardV1 | None = None
    multiple_testing: MultipleTestingSummaryV1 | None = None
    created_at: UTCDateTime
    scorecard_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_model_scorecard(self) -> Self:
        if self.prediction_scorecard is None and self.strategy_scorecard is None:
            raise ValueError(
                "at least one sub-scorecard must be provided in ModelScorecardV1"
            )
        if self.prediction_scorecard is not None:
            if self.prediction_scorecard.run_identity != self.run_identity:
                raise ValueError("prediction scorecard run_identity mismatch")
            if self.prediction_scorecard.lane != self.lane:
                raise ValueError("prediction scorecard lane mismatch")
        if self.strategy_scorecard is not None:
            if self.strategy_scorecard.run_identity != self.run_identity:
                raise ValueError("strategy scorecard run_identity mismatch")
            if self.strategy_scorecard.lane != self.lane:
                raise ValueError("strategy scorecard lane mismatch")
        expected_hash = compute_model_scorecard_hash(self)
        if self.scorecard_hash != expected_hash:
            raise ValueError("model scorecard hash mismatch")
        return self


def compute_prediction_scorecard_hash(
    scorecard: PredictionScorecardV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for an ex-ante prediction scorecard."""
    if isinstance(scorecard, Mapping):
        data = {k: v for k, v in scorecard.items() if k != "scorecard_hash"}
    else:
        data = {
            k: v
            for k, v in scorecard.model_dump(mode="python").items()
            if k != "scorecard_hash"
        }
    return content_hash(data)


def compute_strategy_scorecard_hash(
    scorecard: StrategyScorecardV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for a strategy accounting scorecard."""
    if isinstance(scorecard, Mapping):
        data = {k: v for k, v in scorecard.items() if k != "scorecard_hash"}
    else:
        data = {
            k: v
            for k, v in scorecard.model_dump(mode="python").items()
            if k != "scorecard_hash"
        }
    return content_hash(data)


def compute_model_scorecard_hash(
    scorecard: ModelScorecardV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for a composite model scorecard."""
    if isinstance(scorecard, Mapping):
        data = {k: v for k, v in scorecard.items() if k != "scorecard_hash"}
    else:
        data = {
            k: v
            for k, v in scorecard.model_dump(mode="python").items()
            if k != "scorecard_hash"
        }
    return content_hash(data)


def build_prediction_scorecard(
    *,
    scorecard_id: UUID,
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    prediction_target: PredictionTargetType,
    ic_summary: InformationCoefficientSummaryV1,
    calibration_summary: CalibrationSummaryV1,
    total_predictions: int,
    resolved_predictions: int,
    indeterminate_predictions: int,
    delisted_predictions: int,
    created_at: Any,
) -> PredictionScorecardV1:
    """Construct a PredictionScorecardV1 with deterministic hash derivation."""
    unsigned = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "scorecard_id": scorecard_id,
        "run_identity": run_identity,
        "lane": lane,
        "prediction_target": prediction_target,
        "ic_summary": ic_summary,
        "calibration_summary": calibration_summary,
        "total_predictions": total_predictions,
        "resolved_predictions": resolved_predictions,
        "indeterminate_predictions": indeterminate_predictions,
        "delisted_predictions": delisted_predictions,
        "created_at": created_at,
    }
    s_hash = compute_prediction_scorecard_hash(unsigned)
    return PredictionScorecardV1.model_validate(
        {
            **unsigned,
            "scorecard_hash": s_hash,
        }
    )


def build_strategy_scorecard(
    *,
    scorecard_id: UUID,
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    cumulative_return: Decimal,
    annualized_return: Decimal,
    annualized_volatility: Decimal,
    downside_deviation: Decimal,
    sharpe_ratio: Decimal,
    sortino_ratio: Decimal,
    calmar_ratio: Decimal,
    drawdown_profile: DrawdownProfileV1,
    turnover_summary: TurnoverSummaryV1,
    pnl_completeness: RealizedPnLCompletenessV1,
    created_at: Any,
) -> StrategyScorecardV1:
    """Construct a StrategyScorecardV1 with deterministic hash derivation."""
    unsigned = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "scorecard_id": scorecard_id,
        "run_identity": run_identity,
        "lane": lane,
        "cumulative_return": cumulative_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "downside_deviation": downside_deviation,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "drawdown_profile": drawdown_profile,
        "turnover_summary": turnover_summary,
        "pnl_completeness": pnl_completeness,
        "created_at": created_at,
    }
    s_hash = compute_strategy_scorecard_hash(unsigned)
    return StrategyScorecardV1.model_validate(
        {
            **unsigned,
            "scorecard_hash": s_hash,
        }
    )


def build_model_scorecard(
    *,
    scorecard_id: UUID,
    run_identity: EvaluationRunIdentityV2,
    lane: EvaluationLane,
    prediction_scorecard: PredictionScorecardV1 | None = None,
    strategy_scorecard: StrategyScorecardV1 | None = None,
    multiple_testing: MultipleTestingSummaryV1 | None = None,
    created_at: Any,
) -> ModelScorecardV1:
    """Construct a composite ModelScorecardV1 with deterministic hash derivation."""
    unsigned = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "scorecard_id": scorecard_id,
        "run_identity": run_identity,
        "lane": lane,
        "prediction_scorecard": prediction_scorecard,
        "strategy_scorecard": strategy_scorecard,
        "multiple_testing": multiple_testing,
        "created_at": created_at,
    }
    s_hash = compute_model_scorecard_hash(unsigned)
    return ModelScorecardV1.model_validate(
        {
            **unsigned,
            "scorecard_hash": s_hash,
        }
    )
