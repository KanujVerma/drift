"""Structured failure postmortem extraction and diagnostic engine (M6-3).

Provides automated extraction of root cause analyses, evidence citation hashes,
lessons learned, and forbidden variation constraints from failing M5 scorecards.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from drift.domain.common import SHA256Hash
from drift.domain.research_memory import (
    FailureCategory,
    FailurePostmortemV1,
    build_failure_postmortem,
)
from drift.domain.scorecards import ModelScorecardV1, StrategyScorecardV1
from drift.memory.recorder import ResearchMemoryRecorder, _detect_failure_category

FORBIDDEN_VARIATION_TEMPLATES: dict[FailureCategory, tuple[str, ...]] = {
    FailureCategory.DATA_DEFECT: (
        "Do not run evaluations without verified cost basis allocation",
        "Require RealizedPnLCompletenessV1 check before computing performance",
    ),
    FailureCategory.DRAWDOWN_BREACH: (
        "Do not execute unbounded long-only momentum during market regime shifts",
        "Require dynamic stop-loss or volatility-scaled position sizing",
    ),
    FailureCategory.TURNOVER_DRAG: (
        "Do not evaluate high-frequency rebalancing without cost penalties",
        "Require minimum holding period constraints or turnover threshold bands",
    ),
    FailureCategory.CALIBRATION_FAILURE: (
        "Do not use uncalibrated raw probability scores for portfolio weighting",
        "Require Platt scaling or isotonic calibration before position sizing",
    ),
    FailureCategory.OVERFITTING_REJECTION: (
        "Do not promote strategies without multiple-testing adjustments",
        "Penalize strategy Sharpe ratio by total historical exploratory trial count K",
    ),
    FailureCategory.NEGATIVE_ALPHA: (
        "Do not deploy signals with non-positive Spearman information coefficient",
        "Investigate feature inversion or economic rationale before re-evaluating",
    ),
    FailureCategory.EXECUTION_UNVIABLE: (
        "Do not trade illiquid or restricted securities without participation limits",
        "Constrain trade sizes to ADV liquidity bands",
    ),
}


class FailurePostmortemEngine:
    """Automated extraction and ledger recording of structured failure postmortems."""

    def __init__(self, recorder: ResearchMemoryRecorder | None = None) -> None:
        self.recorder = recorder

    def extract_postmortem(
        self,
        *,
        postmortem_id: UUID,
        experiment_id: UUID,
        run_id: UUID,
        scorecard: StrategyScorecardV1 | ModelScorecardV1,
        trial_id: UUID | None = None,
        falsified_hypotheses: tuple[UUID, ...] = (),
        custom_forbidden_variations: tuple[str, ...] = (),
        override_root_cause: str | None = None,
        override_lessons_learned: str | None = None,
        created_at: datetime | None = None,
    ) -> FailurePostmortemV1:
        """Extract a structured failure postmortem from scorecard metrics."""
        category = _detect_failure_category(scorecard)
        ts = created_at or datetime.now(UTC)

        strat = (
            scorecard.strategy_scorecard
            if isinstance(scorecard, ModelScorecardV1)
            else scorecard
        )

        root_cause = override_root_cause or self._synthesize_root_cause(
            category, scorecard, strat
        )
        lessons = override_lessons_learned or self._synthesize_lessons_learned(
            category, scorecard, strat
        )

        # Evidence hashes
        evidence_hashes: list[SHA256Hash] = [
            scorecard.scorecard_hash,
            scorecard.run_identity.run_identity_hash,
        ]
        if (
            isinstance(scorecard, ModelScorecardV1)
            and scorecard.prediction_scorecard is not None
        ):
            evidence_hashes.append(scorecard.prediction_scorecard.scorecard_hash)

        # Forbidden variations
        base_variations = FORBIDDEN_VARIATION_TEMPLATES.get(category, ())
        all_forbidden = tuple(
            dict.fromkeys((*base_variations, *custom_forbidden_variations))
        )

        postmortem = build_failure_postmortem(
            postmortem_id=postmortem_id,
            experiment_id=experiment_id,
            run_id=run_id,
            trial_id=trial_id,
            failure_category=category,
            root_cause_summary=root_cause,
            lessons_learned=lessons,
            created_at=ts,
            falsified_hypotheses=falsified_hypotheses,
            evidence_hashes=tuple(evidence_hashes),
            forbidden_variations=all_forbidden,
        )

        if self.recorder is not None:
            self.recorder.record_postmortem(postmortem)

        return postmortem

    def _synthesize_root_cause(
        self,
        category: FailureCategory,
        scorecard: StrategyScorecardV1 | ModelScorecardV1,
        strat: StrategyScorecardV1 | None,
    ) -> str:
        """Derive detailed diagnostic text for the primary failure cause."""
        match category:
            case FailureCategory.DATA_DEFECT:
                count = (
                    len(strat.pnl_completeness.excluded_disposals)
                    if strat is not None
                    else 0
                )
                return (
                    f"Data defect: Realized PnL incompleteness detected; "
                    f"{count} disposals excluded due to missing cost basis."
                )
            case FailureCategory.DRAWDOWN_BREACH:
                mdd = (
                    strat.drawdown_profile.maximum_drawdown
                    if strat is not None
                    else Decimal("0")
                )
                return (
                    f"Risk limit breach: Maximum drawdown reached {mdd * 100:.2f}%, "
                    f"exceeding the acceptable 20% limit."
                )
            case FailureCategory.TURNOVER_DRAG:
                ann_turn = (
                    strat.turnover_summary.annualized_turnover
                    if strat is not None
                    else Decimal("0")
                )
                cost_drag = (
                    strat.turnover_summary.estimated_cost_drag
                    if strat is not None
                    else Decimal("0")
                )
                return (
                    f"Economic unviability: Annualized turnover of {ann_turn:.2f}x "
                    f"incurred estimated cost drag of {cost_drag * 100:.2f}%."
                )
            case FailureCategory.CALIBRATION_FAILURE:
                ece = (
                    scorecard.prediction_scorecard.calibration_summary.expected_calibration_error
                    if isinstance(scorecard, ModelScorecardV1)
                    and scorecard.prediction_scorecard is not None
                    else None
                )
                return (
                    f"Calibration failure: Expected Calibration Error (ECE) is {ece}, "
                    f"indicating severe probability distortion."
                )
            case FailureCategory.OVERFITTING_REJECTION:
                dsr = (
                    scorecard.multiple_testing.deflated_sharpe_ratio
                    if isinstance(scorecard, ModelScorecardV1)
                    and scorecard.multiple_testing is not None
                    else None
                )
                return (
                    f"Selection bias rejection: Deflated Sharpe Ratio (DSR: {dsr}) "
                    f"failed to achieve 95% statistical significance."
                )
            case FailureCategory.NEGATIVE_ALPHA:
                return (
                    "Alpha failure: Signal information coefficient is non-positive; "
                    "predictions exhibit zero correlation with forward returns."
                )
            case _:
                return f"Experiment failed due to {category.value}."

    def _synthesize_lessons_learned(
        self,
        category: FailureCategory,
        scorecard: StrategyScorecardV1 | ModelScorecardV1,
        strat: StrategyScorecardV1 | None,
    ) -> str:
        """Derive actionable guidance for future trial iterations."""
        match category:
            case FailureCategory.DATA_DEFECT:
                return (
                    "Audit corporate actions data feeds and verify acquisition lot "
                    "reconciliation before committing compute to backtest runs."
                )
            case FailureCategory.DRAWDOWN_BREACH:
                return (
                    "Incorporate stop-loss rules, dynamic trend filtering, and "
                    "regime-conditional allocation to prevent tail losses during "
                    "broad market drawdowns."
                )
            case FailureCategory.TURNOVER_DRAG:
                return (
                    "Optimize execution schedules using turnover penalty terms "
                    "in alpha objective and evaluate longer holding periods."
                )
            case FailureCategory.CALIBRATION_FAILURE:
                return (
                    "Apply post-processing calibration (Platt or temperature scaling) "
                    "to align model confidences with empirical probabilities."
                )
            case FailureCategory.OVERFITTING_REJECTION:
                return (
                    "Adjust critical Sharpe thresholds according to Bailey & Lopez "
                    "de Prado DSR accounting for trial space cardinality K."
                )
            case FailureCategory.NEGATIVE_ALPHA:
                return (
                    "Re-evaluate underlying economic hypothesis and examine feature "
                    "predictive power on out-of-sample regimes before retraining."
                )
            case _:
                return "Analyze trial execution metrics and refine strategy parameters."
