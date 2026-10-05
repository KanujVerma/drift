"""Automated trial diagnosis and failure postmortem generator (M8-2, Issue 233).

Diagnoses evaluated trial metrics against formal hypothesis falsification criteria,
classifies outcomes, identifies primary root causes, and generates structured
postmortems with extracted forbidden parameter variations.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from drift.domain.common import UTCDateTime
from drift.domain.research_agent import (
    ExperimentSpecificationProposalV1,
    HypothesisProposalV1,
)
from drift.domain.research_memory import (
    FailureCategory,
    FailurePostmortemV1,
    TrialOutcome,
    build_failure_postmortem,
)
from drift.memory.recorder import deterministic_memory_uuid7


@dataclass(frozen=True)
class TrialDiagnosisResult:
    """Detailed diagnosis of an evaluated experiment against hypothesis criteria."""

    outcome: TrialOutcome
    failure_category: FailureCategory | None
    root_cause_summary: str
    lessons_learned: str
    breached_criteria: tuple[str, ...]
    forbidden_variations: tuple[str, ...]


def diagnose_trial_outcome(
    *,
    hypothesis: HypothesisProposalV1,
    experiment: ExperimentSpecificationProposalV1,
    metrics: Mapping[str, Any],
) -> TrialDiagnosisResult:
    """Evaluate actual metrics against hypothesis falsification criteria."""
    breaches: list[str] = []
    primary_category: FailureCategory | None = None

    # 1. Sharpe Ratio
    raw_sharpe = metrics.get("annualized_sharpe", Decimal("0"))
    sharpe = Decimal(str(raw_sharpe))
    if sharpe < hypothesis.min_annualized_sharpe:
        breaches.append(
            f"annualized_sharpe ({sharpe}) below required minimum "
            f"({hypothesis.min_annualized_sharpe})"
        )
        if sharpe < Decimal("0"):
            primary_category = FailureCategory.NEGATIVE_ALPHA
        else:
            primary_category = FailureCategory.CALIBRATION_FAILURE

    # 2. Maximum Drawdown
    raw_drawdown = metrics.get("max_drawdown", Decimal("0"))
    drawdown = Decimal(str(raw_drawdown))
    if drawdown > hypothesis.max_drawdown_limit:
        breaches.append(
            f"max_drawdown ({drawdown}) breached maximum limit "
            f"({hypothesis.max_drawdown_limit})"
        )
        if primary_category is None:
            primary_category = FailureCategory.DRAWDOWN_BREACH

    # 3. Annualized Turnover
    raw_turnover = metrics.get("annualized_turnover", Decimal("0"))
    turnover = Decimal(str(raw_turnover))
    if turnover > hypothesis.max_turnover_limit:
        breaches.append(
            f"annualized_turnover ({turnover}) exceeded maximum limit "
            f"({hypothesis.max_turnover_limit})"
        )
        if primary_category is None:
            primary_category = FailureCategory.TURNOVER_DRAG

    # 4. Information Coefficient (Optional)
    if hypothesis.min_information_coefficient is not None:
        raw_ic = metrics.get("information_coefficient")
        if raw_ic is not None:
            ic = Decimal(str(raw_ic))
            if ic < hypothesis.min_information_coefficient:
                breaches.append(
                    f"information_coefficient ({ic}) below required minimum "
                    f"({hypothesis.min_information_coefficient})"
                )
                if primary_category is None:
                    primary_category = FailureCategory.CALIBRATION_FAILURE

    # Determine Outcome
    forbidden: list[str] = []
    if breaches:
        outcome = TrialOutcome.FAILED
        assert primary_category is not None

        # Extract parameter variations to forbid
        if isinstance(experiment.proposed_parameters, Mapping):
            for k, v in experiment.proposed_parameters.items():
                forbidden.append(f"{k}={v}")

        root_cause = "; ".join(breaches)
        lessons = (
            f"Strategy '{experiment.strategy_type}' failed falsification criteria "
            f"due to {primary_category.value}. Avoid parameter configuration: "
            f"{', '.join(forbidden)}."
        )
    else:
        # Passed all criteria
        # Superior if Sharpe exceeds target by at least 50%
        if sharpe >= hypothesis.min_annualized_sharpe * Decimal("1.5"):
            outcome = TrialOutcome.SUPERIOR
        else:
            outcome = TrialOutcome.NEUTRAL
        root_cause = "All falsification criteria satisfied."
        lessons = (
            f"Hypothesis '{hypothesis.title}' validated with Sharpe {sharpe} "
            f"and drawdown {drawdown}."
        )

    return TrialDiagnosisResult(
        outcome=outcome,
        failure_category=primary_category,
        root_cause_summary=root_cause,
        lessons_learned=lessons,
        breached_criteria=tuple(breaches),
        forbidden_variations=tuple(forbidden),
    )


def build_automatic_failure_postmortem(
    *,
    diagnosis: TrialDiagnosisResult,
    experiment_id: UUID,
    run_id: UUID,
    created_at: UTCDateTime,
    postmortem_id: UUID | None = None,
    trial_id: UUID | None = None,
    falsified_hypothesis_id: UUID | None = None,
) -> FailurePostmortemV1:
    """Build a formal FailurePostmortemV1 from a diagnosed failure."""
    if diagnosis.failure_category is None:
        raise ValueError(
            "Cannot construct failure postmortem for non-failing trial diagnosis"
        )

    pm_id = postmortem_id or deterministic_memory_uuid7(
        f"postmortem:{experiment_id}:{diagnosis.failure_category.value}"
    )

    falsified_tuple = (
        (falsified_hypothesis_id,) if falsified_hypothesis_id is not None else ()
    )

    return build_failure_postmortem(
        postmortem_id=pm_id,
        experiment_id=experiment_id,
        run_id=run_id,
        trial_id=trial_id,
        failure_category=diagnosis.failure_category,
        root_cause_summary=diagnosis.root_cause_summary,
        lessons_learned=diagnosis.lessons_learned,
        created_at=created_at,
        falsified_hypotheses=falsified_tuple,
        forbidden_variations=diagnosis.forbidden_variations,
    )
