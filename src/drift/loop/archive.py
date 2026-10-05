"""Recursive R&D loop audit archive and historical query engine (M8-4, Issue 237).

Reconstructs execution runs, iteration lifecycles, and trial performance
directly from immutable M0 SQLite ledger events.
"""

from collections.abc import Mapping
from uuid import UUID

from drift.domain.research_loop import (
    ITERATION_EVENT_TYPE,
    LOOP_EVENT_TYPE,
    ResearchIterationRecordV1,
    ResearchLoopSummaryV1,
)
from drift.ledger.interface import Ledger
from drift.serialization.canonical import canonical_json

__all__ = ["ResearchLoopArchive"]


class ResearchLoopArchive:
    """Historical archive reconstructing loop executions from immutable M0 ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._summaries: dict[UUID, ResearchLoopSummaryV1] = {}
        self._iterations: dict[UUID, list[ResearchIterationRecordV1]] = {}
        self.refresh()

    def refresh(self) -> None:
        """Scan ledger events and synchronize loop execution records."""
        self._summaries.clear()
        self._iterations.clear()

        for event in self.ledger.events():
            if not isinstance(event.payload, Mapping):
                continue

            if event.event_type == ITERATION_EVENT_TYPE:
                iter_raw = event.payload.get("iteration")
                if isinstance(iter_raw, Mapping):
                    try:
                        it = ResearchIterationRecordV1.model_validate_json(
                            canonical_json(dict(iter_raw))
                        )
                        if it.loop_id not in self._iterations:
                            self._iterations[it.loop_id] = []
                        self._iterations[it.loop_id].append(it)
                    except Exception:
                        continue

            elif event.event_type == LOOP_EVENT_TYPE:
                sum_raw = event.payload.get("summary")
                if isinstance(sum_raw, Mapping):
                    try:
                        summary = ResearchLoopSummaryV1.model_validate_json(
                            canonical_json(dict(sum_raw))
                        )
                        self._summaries[summary.loop_id] = summary
                    except Exception:
                        continue

        # Ensure iterations are ordered by iteration_index
        for iters in self._iterations.values():
            iters.sort(key=lambda x: x.iteration_index)

    @property
    def total_completed_loops(self) -> int:
        """Total number of completed loop runs sealed in the ledger."""
        return len(self._summaries)

    @property
    def total_completed_iterations(self) -> int:
        """Total number of completed iterations sealed across all loops."""
        return sum(len(iters) for iters in self._iterations.values())

    def get_loop_summary(self, loop_id: UUID) -> ResearchLoopSummaryV1 | None:
        """Retrieve loop summary by loop_id."""
        return self._summaries.get(loop_id)

    def list_iterations(self, loop_id: UUID) -> tuple[ResearchIterationRecordV1, ...]:
        """Retrieve ordered iterations for a specific loop execution."""
        return tuple(self._iterations.get(loop_id, []))

    def list_loop_summaries(self) -> tuple[ResearchLoopSummaryV1, ...]:
        """List all loop summaries recorded in the ledger."""
        return tuple(self._summaries.values())

    def get_best_trials_across_loops(self) -> list[UUID]:
        """Return all best_trial_id values across all completed loop runs."""
        return [
            s.best_trial_id
            for s in self._summaries.values()
            if s.best_trial_id is not None
        ]
