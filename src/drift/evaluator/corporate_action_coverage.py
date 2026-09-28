"""Closed-world corporate-action coverage for the M2 pre-open pass (issue 76).

Owner ruling on #76, option A: a held or traded security needs closed-world,
evidence-bearing corporate-action coverage over every session window it is
exposed in, or the evaluation halts INDETERMINATE, in both lanes. Silent "no
corporate action" is not a default any more.

``CorporateActionCoverageIndex`` is the mandatory constructor argument of the
corporate-action processor (decision D7-b), so the rule runs inside
``apply_pre_open_actions``, over exactly the exposure and the session windows
the processor already owns. Coverage for one security over one window comes
from one of two kinds of evidence, never both (V11):

* an exploratory ``ClosedWorldCorporateActionCoverageV1`` record, admitted only
  under an exploratory admission (V12), which covers the window when
  ``corporate_action_window_status`` reads it ``evidenced_no_action``; or
* the security's own M1c outcome, when it is M1c-native coverage over the
  window (section 3.4), the promotion-grade form.

A window with returned actions halts, naming them: the Alpaca bridge mints no
occurred effect, so a returned action in a held window is unaccounted
evidence. A window with no coverage halts, naming the security and the dates.
Both halts are ``IndeterminateValuationError`` in ``PRE_OPEN_EFFECTS``. An
integrity failure of the evidence itself is refused by its code instead.
"""

from collections.abc import Iterable
from datetime import date
from typing import Literal
from uuid import UUID

from drift.domain.economic_closed_world import (
    ClosedWorldCorporateActionCoverageV1,
    exact_date,
)
from drift.domain.evaluator_corporate_actions import SecurityEconomicOutcomeV1
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.markets.economic_closed_world import (
    CorporateActionCoverageError,
    corporate_action_window_status,
    native_outcome_covers_window,
    native_outcome_is_empty,
    verify_corporate_action_coverage,
    window_returned_actions,
)

type CoverageLane = Literal["exploratory", "promotion"]


def _window_text(security_id: UUID, start: date, end: date) -> str:
    return f"{security_id} over [{date.isoformat(start)}, {date.isoformat(end)}]"


class CorporateActionCoverageIndex:
    """The exploratory coverage records one evaluation may read, by lane.

    Every record is re-verified at construction: it revalidates through its
    own contract and was derived under the running coverage identity (V10).
    Under a promotion admission any exploratory record is refused (V12): the
    grade follows the source, and a promotion evaluation may be covered only
    by M1c-native coverage.
    """

    def __init__(
        self,
        *,
        records: Iterable[ClosedWorldCorporateActionCoverageV1],
        lane: CoverageLane,
    ) -> None:
        if lane not in ("exploratory", "promotion"):
            raise ValueError(f"unknown evaluation lane for coverage: {lane!r}")
        verified = tuple(verify_corporate_action_coverage(item) for item in records)
        if lane == "promotion" and verified:
            raise CorporateActionCoverageError(
                "ca_coverage_grade_refused_by_lane",
                "a promotion admission cannot be covered by exploratory-grade "
                "corporate-action coverage records",
            )
        self._records = verified
        self._lane: CoverageLane = lane
        self._securities = frozenset(item.security_id for item in verified)

    @property
    def records(self) -> tuple[ClosedWorldCorporateActionCoverageV1, ...]:
        """The verified exploratory records this index reads."""
        return self._records

    @property
    def lane(self) -> CoverageLane:
        """The lane of the admission this index serves."""
        return self._lane

    def _refuse_mixed(self, security_id: UUID) -> None:
        if security_id in self._securities:
            raise CorporateActionCoverageError(
                "ca_coverage_mixed_sources",
                f"security {security_id} carries both an M1c economic outcome and "
                "an exploratory corporate-action coverage record",
            )

    def native_no_action(
        self, outcome: SecurityEconomicOutcomeV1, start: date, end: date
    ) -> bool:
        """C4: whether an outcome is M1c-native coverage with no records at all.

        Such an outcome is evidenced no action over the window, not unsupported
        evidence, whatever its ``support_status`` says about its empty record
        set.
        """
        self._refuse_mixed(outcome.security_id)
        start, end = exact_date(start), exact_date(end)
        return native_outcome_covers_window(
            outcome.resolution, start, end
        ) and native_outcome_is_empty(outcome.resolution)

    def require_covered(
        self,
        security_id: UUID,
        outcome: SecurityEconomicOutcomeV1 | None,
        start: date,
        end: date,
    ) -> None:
        """C3: halt INDETERMINATE unless the window is closed-world covered.

        ``start`` and ``end`` are the inclusive local dates of the session
        window. ``outcome`` is the security's own M1c outcome, if one was
        supplied. Raises ``IndeterminateValuationError`` naming what is
        missing or present, and ``CorporateActionCoverageError`` for evidence
        that contradicts itself.

        A window that owns no date, such as the window of a second clock
        session on the date of the one before it, holds nothing to cover.
        """
        start, end = exact_date(start), exact_date(end)
        if start > end:
            return
        if outcome is not None:
            if outcome.security_id != security_id:
                raise ValueError("an outcome must describe the security it covers")
            self._refuse_mixed(security_id)
            if native_outcome_covers_window(outcome.resolution, start, end):
                return
            raise IndeterminateValuationError(
                "no closed-world corporate-action coverage for "
                f"{_window_text(security_id, start, end)}: its M1c economic "
                "outcome is not complete coverage of every action kind over the "
                "window"
            )
        status = corporate_action_window_status(self._records, security_id, start, end)
        if status == "evidenced_no_action":
            return
        present = window_returned_actions(self._records, security_id, start, end)
        if present:
            named = ", ".join(
                f"{action.native_kind} {action.native_id}" for action in present
            )
            raise IndeterminateValuationError(
                "corporate-action coverage returned actions for "
                f"{_window_text(security_id, start, end)} that no M2 accounting "
                f"evidence accounts for: {named}"
            )
        raise IndeterminateValuationError(
            "no closed-world corporate-action coverage for "
            f"{_window_text(security_id, start, end)} ({status})"
        )
