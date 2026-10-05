"""Structured research memory archive and query engine (M6-4).

Provides deterministic query operations over historical research trials,
falsified hypotheses, failure postmortems, parameter spaces, and Sharpe distributions.
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from drift.domain.research_memory import (
    HYPOTHESIS_STATE_EVENT_TYPE,
    POSTMORTEM_EVENT_TYPE,
    TRIAL_EVENT_TYPE,
    FailureCategory,
    FailurePostmortemV1,
    HypothesisLifecycleV1,
    HypothesisStatus,
    ParameterSearchSpaceV1,
    ResearchTrialRecordV1,
)
from drift.ledger.interface import Ledger
from drift.serialization.canonical import canonical_json


class ResearchMemoryArchive:
    """Query and retrieval engine over M0 ledger research memory events."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._trials: list[ResearchTrialRecordV1] = []
        self._postmortems: list[FailurePostmortemV1] = []
        self._hypotheses: dict[UUID, HypothesisLifecycleV1] = {}
        self._parameter_spaces: list[ParameterSearchSpaceV1] = []
        self._evaluated_parameters: set[tuple[str, str]] = set()
        self.refresh()

    def refresh(self) -> None:
        """Scan ledger events and synchronize in-memory indexes."""
        self._trials.clear()
        self._postmortems.clear()
        self._hypotheses.clear()
        self._parameter_spaces.clear()
        self._evaluated_parameters.clear()

        for event in self.ledger.events():
            if not isinstance(event.payload, Mapping):
                continue

            if event.event_type == TRIAL_EVENT_TYPE:
                trial_raw = event.payload.get("trial")
                if isinstance(trial_raw, Mapping):
                    trial = ResearchTrialRecordV1.model_validate_json(
                        canonical_json(dict(trial_raw))
                    )
                    self._trials.append(trial)
                    self._evaluated_parameters.add(
                        (trial.strategy_type, trial.parameters_hash)
                    )

            elif event.event_type == POSTMORTEM_EVENT_TYPE:
                pm_raw = event.payload.get("postmortem")
                if isinstance(pm_raw, Mapping):
                    pm = FailurePostmortemV1.model_validate_json(
                        canonical_json(dict(pm_raw))
                    )
                    self._postmortems.append(pm)

            elif event.event_type == HYPOTHESIS_STATE_EVENT_TYPE:
                lc_raw = event.payload.get("lifecycle")
                if isinstance(lc_raw, Mapping):
                    lc = HypothesisLifecycleV1.model_validate_json(
                        canonical_json(dict(lc_raw))
                    )
                    self._hypotheses[lc.hypothesis_id] = lc

    def get_trial_count(self, hypothesis_id: UUID | None = None) -> int:
        """Return total trial count K, globally or scoped to a hypothesis."""
        if hypothesis_id is None:
            return len(self._trials)
        return sum(1 for t in self._trials if t.hypothesis_id == hypothesis_id)

    def get_trial_sharpe_distribution(
        self, hypothesis_id: UUID | None = None
    ) -> list[Decimal]:
        """Return the empirical distribution of trial Sharpe ratios."""
        trials = (
            self._trials
            if hypothesis_id is None
            else [t for t in self._trials if t.hypothesis_id == hypothesis_id]
        )
        sharpes: list[Decimal] = []
        for t in trials:
            if (
                isinstance(t.headline_metrics, Mapping)
                and "sharpe_ratio" in t.headline_metrics
            ):
                try:
                    val = Decimal(str(t.headline_metrics["sharpe_ratio"]))
                    sharpes.append(val)
                except Exception:
                    continue
        return sharpes

    def find_falsified_hypotheses(
        self, tags: tuple[str, ...] = ()
    ) -> list[HypothesisLifecycleV1]:
        """Return all hypotheses whose current lifecycle state is FALSIFIED."""
        return [
            lc
            for lc in self._hypotheses.values()
            if lc.status == HypothesisStatus.FALSIFIED
        ]

    def get_postmortems_by_category(
        self, category: FailureCategory
    ) -> list[FailurePostmortemV1]:
        """Return all failure postmortems classified under the given category."""
        return [pm for pm in self._postmortems if pm.failure_category == category]

    def is_parameter_region_evaluated(
        self, strategy_type: str, parameters_hash: str
    ) -> bool:
        """Check if an exact parameter configuration has already been executed."""
        return (strategy_type, parameters_hash) in self._evaluated_parameters

    def get_parameter_search_frontier(
        self, strategy_type: str
    ) -> list[ParameterSearchSpaceV1]:
        """Return explored parameter search dimensions and coverage metrics."""
        return [
            ps for ps in self._parameter_spaces if ps.strategy_type == strategy_type
        ]

    def get_trials(
        self,
        *,
        hypothesis_id: UUID | None = None,
        strategy_type: str | None = None,
    ) -> list[ResearchTrialRecordV1]:
        """Return matching research trial records in chronological order."""
        trials = self._trials
        if hypothesis_id is not None:
            trials = [t for t in trials if t.hypothesis_id == hypothesis_id]
        if strategy_type is not None:
            trials = [t for t in trials if t.strategy_type == strategy_type]
        return list(trials)

    def get_postmortems(self) -> list[FailurePostmortemV1]:
        """Return all failure postmortems in chronological order."""
        return list(self._postmortems)
