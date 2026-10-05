"""Hypothesis lifecycle management and falsification engine (M6-3).

Provides deterministic hypothesis lifecycle state tracking, pre-registered
falsification criterion evaluation, validation checking, and transactional
M0 ledger synchronization.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from drift.domain.common import FrozenModel
from drift.domain.hypotheses import Hypothesis
from drift.domain.research_memory import (
    HypothesisLifecycleV1,
    HypothesisStatus,
    ResearchTrialRecordV1,
    TrialOutcome,
    build_hypothesis_lifecycle,
)
from drift.domain.scorecards import ModelScorecardV1, StrategyScorecardV1
from drift.errors import DriftError
from drift.memory.recorder import ResearchMemoryRecorder


class ResearchMemoryError(DriftError):
    """Base error for structured research memory operations."""


class InvalidStateTransitionError(ResearchMemoryError):
    """Raised when an invalid hypothesis state machine transition is attempted."""


class HypothesisNotFoundError(ResearchMemoryError):
    """Raised when a requested hypothesis is not registered with the manager."""


class HypothesisFalsificationCriteria(FrozenModel):
    """Pre-registered quantitative thresholds for hypothesis falsification."""

    min_sharpe_ratio: Decimal | None = None
    max_drawdown_limit: Decimal | None = None  # e.g. Decimal("-0.20")
    min_mean_ic: Decimal | None = None  # e.g. Decimal("0.0")
    max_consecutive_failures: int | None = Field(default=None, ge=1)
    min_validation_sharpe: Decimal | None = None  # e.g. Decimal("1.50")
    require_dsr_significant: bool = False


VALID_TRANSITIONS: Mapping[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.PROPOSED: frozenset(
        {HypothesisStatus.ACTIVE, HypothesisStatus.ABANDONED}
    ),
    HypothesisStatus.ACTIVE: frozenset(
        {
            HypothesisStatus.VALIDATED,
            HypothesisStatus.FALSIFIED,
            HypothesisStatus.ABANDONED,
        }
    ),
    HypothesisStatus.VALIDATED: frozenset({HypothesisStatus.FALSIFIED}),
    HypothesisStatus.FALSIFIED: frozenset(),
    HypothesisStatus.ABANDONED: frozenset(),
}


class HypothesisManager:
    """Manages hypothesis lifecycle state machines and falsification checks."""

    def __init__(self, recorder: ResearchMemoryRecorder) -> None:
        self.recorder = recorder
        self._lifecycles: dict[UUID, HypothesisLifecycleV1] = {}
        self._criteria: dict[UUID, HypothesisFalsificationCriteria] = {}
        self._consecutive_failures: dict[UUID, int] = {}

    def register_hypothesis(
        self,
        hypothesis: Hypothesis,
        *,
        criteria: HypothesisFalsificationCriteria | None = None,
        notes: str | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Register a newly formulated hypothesis in the PROPOSED state."""
        ts = as_of_time or datetime.now(UTC)
        lifecycle = build_hypothesis_lifecycle(
            hypothesis_id=hypothesis.hypothesis_id,
            status=HypothesisStatus.PROPOSED,
            updated_at=ts,
            notes=notes or f"Registered hypothesis: {hypothesis.title}",
        )
        self.recorder.record_hypothesis_state(lifecycle)
        self._lifecycles[hypothesis.hypothesis_id] = lifecycle
        if criteria is not None:
            self._criteria[hypothesis.hypothesis_id] = criteria
        self._consecutive_failures[hypothesis.hypothesis_id] = 0
        return lifecycle

    def get_state(self, hypothesis_id: UUID) -> HypothesisLifecycleV1:
        """Return the current lifecycle state of a registered hypothesis."""
        if hypothesis_id not in self._lifecycles:
            msg = f"Hypothesis {hypothesis_id} not registered"
            raise HypothesisNotFoundError(msg)
        return self._lifecycles[hypothesis_id]

    def activate_hypothesis(
        self,
        hypothesis_id: UUID,
        *,
        notes: str | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Transition a hypothesis from PROPOSED to ACTIVE."""
        current = self.get_state(hypothesis_id)
        self._validate_transition(
            hypothesis_id, current.status, HypothesisStatus.ACTIVE
        )
        ts = as_of_time or datetime.now(UTC)
        updated = build_hypothesis_lifecycle(
            hypothesis_id=hypothesis_id,
            status=HypothesisStatus.ACTIVE,
            updated_at=ts,
            notes=notes or "Hypothesis activated for empirical trials",
        )
        self.recorder.record_hypothesis_state(updated)
        self._lifecycles[hypothesis_id] = updated
        return updated

    def evaluate_trial(
        self,
        *,
        hypothesis_id: UUID,
        trial: ResearchTrialRecordV1,
        scorecard: StrategyScorecardV1 | ModelScorecardV1 | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Evaluate a trial result against pre-registered falsification criteria."""
        current = self.get_state(hypothesis_id)
        if current.status != HypothesisStatus.ACTIVE:
            msg = (
                f"Cannot evaluate trial for hypothesis {hypothesis_id} "
                f"in state {current.status}; must be ACTIVE"
            )
            raise InvalidStateTransitionError(msg)

        criteria = self._criteria.get(hypothesis_id)
        ts = as_of_time or datetime.now(UTC)
        falsification_triggered = False
        falsification_reasons: list[str] = []

        # 1. Trial failure outcome check
        if trial.trial_outcome in (
            TrialOutcome.FAILED,
            TrialOutcome.INVALIDATED,
        ):
            self._consecutive_failures[hypothesis_id] = (
                self._consecutive_failures.get(hypothesis_id, 0) + 1
            )
        else:
            self._consecutive_failures[hypothesis_id] = 0

        # 2. Check max consecutive failures threshold
        if criteria is not None and criteria.max_consecutive_failures is not None:
            if (
                self._consecutive_failures[hypothesis_id]
                >= criteria.max_consecutive_failures
            ):
                falsification_triggered = True
                falsification_reasons.append(
                    f"Exceeded max consecutive failures ("
                    f"{self._consecutive_failures[hypothesis_id]} >= "
                    f"{criteria.max_consecutive_failures})"
                )

        # 3. Check drawdown limit
        if (
            criteria is not None
            and criteria.max_drawdown_limit is not None
            and scorecard is not None
        ):
            strat = (
                scorecard.strategy_scorecard
                if isinstance(scorecard, ModelScorecardV1)
                else scorecard
            )
            if (
                strat is not None
                and strat.drawdown_profile.maximum_drawdown
                < criteria.max_drawdown_limit
            ):
                mdd = strat.drawdown_profile.maximum_drawdown
                falsification_triggered = True
                falsification_reasons.append(
                    f"Maximum drawdown ({mdd}) breached limit "
                    f"({criteria.max_drawdown_limit})"
                )

        # 4. Check min Sharpe ratio
        if criteria is not None and criteria.min_sharpe_ratio is not None:
            sharpe_val: Decimal | None = None
            if (
                isinstance(trial.headline_metrics, Mapping)
                and "sharpe_ratio" in trial.headline_metrics
            ):
                try:
                    sharpe_val = Decimal(str(trial.headline_metrics["sharpe_ratio"]))
                except Exception:
                    sharpe_val = None
            if sharpe_val is not None and sharpe_val < criteria.min_sharpe_ratio:
                falsification_triggered = True
                falsification_reasons.append(
                    f"Sharpe ratio ({sharpe_val}) fell below minimum "
                    f"({criteria.min_sharpe_ratio})"
                )

        # 5. Check min mean IC
        if (
            criteria is not None
            and criteria.min_mean_ic is not None
            and isinstance(scorecard, ModelScorecardV1)
            and scorecard.prediction_scorecard is not None
        ):
            mean_ic = scorecard.prediction_scorecard.ic_summary.mean_spearman_ic
            if mean_ic < criteria.min_mean_ic:
                falsification_triggered = True
                falsification_reasons.append(
                    f"Mean Spearman IC ({mean_ic}) fell below minimum "
                    f"({criteria.min_mean_ic})"
                )

        # If falsification triggered, transition to FALSIFIED
        if falsification_triggered:
            evidence_hashes = [trial.trial_hash]
            if scorecard is not None:
                evidence_hashes.append(scorecard.scorecard_hash)
            reason_str = "; ".join(falsification_reasons)
            return self.falsify_hypothesis(
                hypothesis_id,
                evidence_hashes=tuple(evidence_hashes),
                notes=f"Falsification criterion triggered: {reason_str}",
                as_of_time=ts,
            )

        # Check validation criteria
        if criteria is not None and criteria.min_validation_sharpe is not None:
            sharpe_val = None
            if (
                isinstance(trial.headline_metrics, Mapping)
                and "sharpe_ratio" in trial.headline_metrics
            ):
                try:
                    sharpe_val = Decimal(str(trial.headline_metrics["sharpe_ratio"]))
                except Exception:
                    sharpe_val = None

            if (
                sharpe_val is not None
                and sharpe_val >= criteria.min_validation_sharpe
                and trial.trial_outcome == TrialOutcome.SUPERIOR
            ):
                dsr_ok = True
                if criteria.require_dsr_significant:
                    if (
                        isinstance(scorecard, ModelScorecardV1)
                        and scorecard.multiple_testing is not None
                    ):
                        dsr_ok = scorecard.multiple_testing.is_dsr_significant_at_95
                    else:
                        dsr_ok = False

                if dsr_ok:
                    evidence_hashes = [trial.trial_hash]
                    if scorecard is not None:
                        evidence_hashes.append(scorecard.scorecard_hash)
                    return self.validate_hypothesis(
                        hypothesis_id,
                        evidence_hashes=tuple(evidence_hashes),
                        notes=f"Validation criteria satisfied with Sharpe {sharpe_val}",
                        as_of_time=ts,
                    )

        return current

    def falsify_hypothesis(
        self,
        hypothesis_id: UUID,
        *,
        evidence_hashes: tuple[str, ...],
        notes: str | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Mark a hypothesis as definitively FALSIFIED with evidence citations."""
        current = self.get_state(hypothesis_id)
        self._validate_transition(
            hypothesis_id, current.status, HypothesisStatus.FALSIFIED
        )
        if not evidence_hashes:
            msg = "Falsification requires at least one evidence citation hash"
            raise ValueError(msg)

        ts = as_of_time or datetime.now(UTC)
        updated = build_hypothesis_lifecycle(
            hypothesis_id=hypothesis_id,
            status=HypothesisStatus.FALSIFIED,
            falsification_evidence=evidence_hashes,
            falsified_at=ts,
            updated_at=ts,
            notes=notes or "Hypothesis falsified by empirical evidence",
        )
        self.recorder.record_hypothesis_state(updated)
        self._lifecycles[hypothesis_id] = updated
        return updated

    def validate_hypothesis(
        self,
        hypothesis_id: UUID,
        *,
        evidence_hashes: tuple[str, ...],
        notes: str | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Mark a hypothesis as empirically VALIDATED with evidence citations."""
        current = self.get_state(hypothesis_id)
        self._validate_transition(
            hypothesis_id, current.status, HypothesisStatus.VALIDATED
        )
        if not evidence_hashes:
            msg = "Validation requires at least one evidence citation hash"
            raise ValueError(msg)

        ts = as_of_time or datetime.now(UTC)
        updated = build_hypothesis_lifecycle(
            hypothesis_id=hypothesis_id,
            status=HypothesisStatus.VALIDATED,
            validation_evidence=evidence_hashes,
            validated_at=ts,
            updated_at=ts,
            notes=notes or "Hypothesis empirically validated",
        )
        self.recorder.record_hypothesis_state(updated)
        self._lifecycles[hypothesis_id] = updated
        return updated

    def abandon_hypothesis(
        self,
        hypothesis_id: UUID,
        *,
        notes: str | None = None,
        as_of_time: datetime | None = None,
    ) -> HypothesisLifecycleV1:
        """Retire or abandon a hypothesis before or during exploration."""
        current = self.get_state(hypothesis_id)
        self._validate_transition(
            hypothesis_id, current.status, HypothesisStatus.ABANDONED
        )
        ts = as_of_time or datetime.now(UTC)
        updated = build_hypothesis_lifecycle(
            hypothesis_id=hypothesis_id,
            status=HypothesisStatus.ABANDONED,
            updated_at=ts,
            notes=notes or "Hypothesis retired/abandoned",
        )
        self.recorder.record_hypothesis_state(updated)
        self._lifecycles[hypothesis_id] = updated
        return updated

    def _validate_transition(
        self,
        hypothesis_id: UUID,
        from_status: HypothesisStatus,
        to_status: HypothesisStatus,
    ) -> None:
        """Verify that state transition is admitted by canonical lifecycle DAG."""
        admitted = VALID_TRANSITIONS.get(from_status, frozenset())
        if to_status not in admitted:
            msg = (
                f"Invalid lifecycle transition for hypothesis {hypothesis_id}: "
                f"cannot transition from {from_status} to {to_status}"
            )
            raise InvalidStateTransitionError(msg)
