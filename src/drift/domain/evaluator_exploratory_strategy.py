"""EXPLORATORY-only reconstructed decision evidence and its strategy context.

ADR 0012 created an exploratory lane so evaluator and baseline work could
proceed before promotion-grade data is bought. A
``scheduled_session_reconstruction`` bundle carries no
``DerivedObservationViewV1`` at all, because ``bind_observation_session``
classifies a source session ``bound`` only through realized open/close
evidence, and design spec 7.1 forbids forcing scheduled-only history through
the M1d materializers. The lane therefore had evidence
(``ExploratoryReconstructedSessionObservationV1``) and no consumer. The issue
42 adjudication (issue 46) rules that this weaker evidence may drive strategy
decisions in the EXPLORATORY lane only, through a dedicated type.

This module is that type, and only that type. It is deliberately a separate
module from :mod:`drift.domain.evaluator_strategy` so the canonical strong
decision input is never widened into a union containing reconstructed
evidence: importing the strong strategy boundary cannot surface the weaker
grade, and every consumer of the weaker grade is found by grepping this
module name.

Four separations keep the Absolute Non-Upgrade Rule structural rather than
procedural:

* ``ExploratoryReconstructedDecisionViewV1`` is not a
  ``StrategyDecisionViewV1`` and cannot be placed in one. Its members are
  ``ExploratoryReconstructedSessionObservationV1``, which carries none of the
  fields a derived view requires, so the strong bucket rejects it on shape.
* ``ExploratoryStrategyDecisionContextV1`` shares no base class and no
  evidence field with ``StrategyDecisionContextV1``, and declares ``lane``,
  ``evidence_grade``, and ``is_promotion_grade_evidence`` as literals on a
  frozen model, so no assignment, copy, or revalidation can raise its
  standing.
* The context refuses any decision session that does not carry scheduled
  reconstruction authority, so realized standing can never be claimed for it.
* The runtime entry point is a distinct method name, ``decide_exploratory``.
  The realized and promotion dispatch path calls ``decide`` and therefore
  cannot hand the weaker context to a strategy even by accident.

What this contract deliberately does NOT check is publication vintage. Design
spec 7.2 relaxes provider publication and revision availability timestamps in
the exploratory lane, and only those: business-time ordering is still
enforced, so session D may never read a bar printed for session D+1.
"""

from decimal import Decimal
from typing import Literal, Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_UNVERSIONED_BARS,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_strategy import (
    PositionViewV1,
    SecurityTargetPositionV1,
    StrategyDecisionIntentV1,
    _stage_targets,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference

type ExploratoryReconstructedEvidenceGrade = Literal["exploratory_reconstructed"]
"""The single evidence grade this module admits. Never promotion-grade."""

EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE: ExploratoryReconstructedEvidenceGrade = (
    "exploratory_reconstructed"
)

#: Limitations a scheduled-reconstruction clock always states about itself.
SCHEDULED_CLOCK_LIMITATIONS: tuple[str, ...] = (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)

#: Every limitation a decision taken on reconstructed evidence carries, however
#: it was assembled: the scheduled clock's own, the bounded cohort standing in
#: for a historical universe, and the retrospective, unversioned grade of the
#: reconstructed bars themselves. Nothing that consumes this grade may state
#: fewer.
RECONSTRUCTED_DECISION_LIMITATIONS: tuple[str, ...] = tuple(
    sorted(
        (
            *SCHEDULED_CLOCK_LIMITATIONS,
            ALPACA_LIMITATION_BOUNDED_COHORT,
            ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
            ALPACA_LIMITATION_UNVERSIONED_BARS,
        )
    )
)


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def _session_order(session_key: SessionKeyV1) -> tuple[object, ...]:
    """Chronological order for one security's reconstructed history."""
    return (session_key.local_date, session_key.mic, session_key.session_scope)


def _describe(session_key: SessionKeyV1) -> str:
    return f"{session_key.mic} {session_key.local_date.isoformat()}"


class ExploratoryReconstructedDecisionViewV1(FrozenModel):
    """EXPLORATORY-only reconstructed decision evidence for one security.

    The weaker counterpart of ``StrategyDecisionViewV1``, and never a
    substitute for it. Its members prove no realized session, no historical
    publication availability, and no structural eligibility. They are
    admissible for exploratory screening over a declared cohort and for
    nothing else. Members are held in chronological session order, one per
    session, so a strategy reads its history in business time.
    """

    schema_version: Literal["1"] = "1"
    evidence_grade: ExploratoryReconstructedEvidenceGrade = (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    )
    security_id: UUID7
    observations: tuple[ExploratoryReconstructedSessionObservationV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]

    @field_validator("observations")
    @classmethod
    def canonicalize_observations(
        cls, values: tuple[ExploratoryReconstructedSessionObservationV1, ...]
    ) -> tuple[ExploratoryReconstructedSessionObservationV1, ...]:
        if not values:
            raise ValueError(
                "reconstructed decision view requires at least one observation"
            )
        digests = tuple(item.reconstruction_hash for item in values)
        if len(set(digests)) != len(digests):
            raise ValueError("reconstructed decision view members must be unique")
        return tuple(sorted(values, key=lambda item: _session_order(item.session_key)))

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        for observation in self.observations:
            if observation.security_id != self.security_id:
                raise ValueError(
                    "reconstructed decision view members must share the security"
                )
        # Two reconstructions of one security's session are two answers to one
        # question. Choosing either would make the decision depend on order.
        sessions = tuple(item.session_key for item in self.observations)
        if len(set(sessions)) != len(sessions):
            raise ValueError(
                "reconstructed decision view members must be unique by session"
            )
        # Exactly the union, not a superset and not a subset. A subset drops an
        # acknowledged weakness of the evidence; a superset invents one, which
        # would let a reader believe a limitation was audited when it was not.
        expected = tuple(
            sorted(
                {
                    limitation
                    for observation in self.observations
                    for limitation in observation.acknowledged_limitations
                }
            )
        )
        if tuple(self.acknowledged_limitations) != expected:
            raise ValueError(
                "reconstructed decision view must acknowledge exactly the "
                f"limitations its evidence carries: expected {expected}, got "
                f"{tuple(self.acknowledged_limitations)}"
            )
        return self


class ExploratoryStrategyDecisionContextV1(FrozenModel):
    """EXPLORATORY-only causal information set built from reconstructed evidence.

    Structurally the counterpart of ``StrategyDecisionContextV1``, and never
    interchangeable with it. The two share no base class and no evidence
    field type, so a strategy written against one cannot silently receive the
    other, and neither validates as the other.
    """

    schema_version: Literal["1"] = "1"
    lane: Literal["exploratory"] = "exploratory"
    evidence_grade: ExploratoryReconstructedEvidenceGrade = (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    )
    is_promotion_grade_evidence: Literal[False] = False
    session_key: SessionKeyV1
    decision_session: EvaluationSessionV1
    decision_cutoff: UTCDateTime
    cohort_hash: SHA256Hash
    admitted_cohort: tuple[UUID7, ...]
    current_holdings: tuple[PositionViewV1, ...]
    current_cash: Decimal
    portfolio_nav: Decimal
    reconstructed_decision_views: tuple[ExploratoryReconstructedDecisionViewV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]

    @field_validator("admitted_cohort")
    @classmethod
    def canonicalize_cohort(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if not values:
            raise ValueError("exploratory decision context requires a bounded cohort")
        if len(set(values)) != len(values):
            raise ValueError("admitted cohort members must be unique")
        return tuple(sorted(values, key=_security_order))

    @field_validator("current_holdings")
    @classmethod
    def canonicalize_holdings(
        cls, values: tuple[PositionViewV1, ...]
    ) -> tuple[PositionViewV1, ...]:
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("holdings must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))

    @field_validator("reconstructed_decision_views")
    @classmethod
    def canonicalize_views(
        cls, values: tuple[ExploratoryReconstructedDecisionViewV1, ...]
    ) -> tuple[ExploratoryReconstructedDecisionViewV1, ...]:
        securities = tuple(item.security_id for item in values)
        if len(set(securities)) != len(securities):
            raise ValueError("reconstructed decision views must be unique by security")
        return tuple(sorted(values, key=lambda item: _security_order(item.security_id)))

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("acknowledged limitations must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if self.decision_session.session_key != self.session_key:
            raise ValueError(
                "decision session must be the context session: "
                f"{self.decision_session.session_key.local_date} is not "
                f"{self.session_key.local_date}"
            )
        # The whole point of this type is that scheduled evidence stays
        # scheduled. A realized-authority session reaching here would mean a
        # reconstruction had been given realized standing, which is exactly
        # the upgrade ADR 0012 forbids.
        if self.decision_session.authority != "scheduled_reconstruction":
            raise ValueError(
                "exploratory reconstructed decisions require scheduled "
                "reconstruction session authority, got "
                f"{self.decision_session.authority!r}"
            )
        # The decision is taken at the scheduled close the generated calendar
        # states, early or regular. Nothing here hardcodes a clock time. A
        # cutoff before that close would be a decision taken during the
        # session it claims to have observed; a cutoff after it would wait for
        # a close the schedule never stated.
        if self.decision_cutoff != self.decision_session.closed_at:
            raise ValueError(
                "exploratory decision cutoff must be the scheduled session "
                f"close {self.decision_session.closed_at.isoformat()}, got "
                f"{self.decision_cutoff.isoformat()}"
            )
        if self.current_cash < Decimal("0"):
            raise ValueError("current cash must be non-negative")
        if self.portfolio_nav < Decimal("0"):
            raise ValueError("portfolio net asset value must be non-negative")
        if not self.reconstructed_decision_views:
            raise ValueError(
                "exploratory decision context requires at least one "
                "reconstructed decision view"
            )
        self._validate_evidence()
        self._validate_decision_session_evidence()
        self._validate_limitations()
        return self

    def _validate_evidence(self) -> None:
        admitted = frozenset(self.admitted_cohort)
        for group in self.reconstructed_decision_views:
            for observation in group.observations:
                # Business-time ordering is not relaxed by the exploratory
                # lane. A later session's bar is plain lookahead whatever its
                # publication vintage.
                if observation.session_key.local_date > self.session_key.local_date:
                    raise ValueError(
                        "reconstructed decision evidence sourced after its "
                        f"decision session: {observation.session_key.local_date} "
                        f"follows {self.session_key.local_date}"
                    )
                if observation.cohort_hash != self.cohort_hash:
                    raise ValueError(
                        "reconstructed decision evidence must bind the declared "
                        f"cohort {self.cohort_hash}, got {observation.cohort_hash}"
                    )
                if observation.security_id not in admitted:
                    raise ValueError(
                        "reconstructed decision evidence must describe an "
                        "admitted cohort security, got "
                        f"{observation.security_id}"
                    )

    def _validate_decision_session_evidence(self) -> None:
        """Bind the decision to the scheduled session it claims to have observed.

        A decision at the close of session D must read a bar for D, and that
        bar must have been reconstructed against the very calendar row the
        clock generated D from. Without the second check a reconstruction
        built against a regular 16:00 schedule could serve a decision the clock
        takes at a 13:00 early close, or the reverse, and the scheduled clock
        would no longer be what timed the decision.
        """
        authority = frozenset(self.decision_session.authority_record_hashes)
        current = tuple(
            observation
            for group in self.reconstructed_decision_views
            for observation in group.observations
            if observation.session_key == self.session_key
        )
        if not current:
            raise ValueError(
                "exploratory decision context requires reconstructed evidence "
                f"for its own scheduled decision session {_describe(self.session_key)}"
            )
        for observation in current:
            if (
                observation.scheduled_session_hash not in authority
                or observation.generated_session_row_hash not in authority
            ):
                raise ValueError(
                    "reconstructed decision evidence must bind the scheduled "
                    "calendar row its decision session was generated from: "
                    f"{observation.reconstruction_hash} on "
                    f"{_describe(observation.session_key)}"
                )

    def _validate_limitations(self) -> None:
        required = {
            *SCHEDULED_CLOCK_LIMITATIONS,
            ALPACA_LIMITATION_BOUNDED_COHORT,
        }
        for group in self.reconstructed_decision_views:
            required.update(group.acknowledged_limitations)
        missing = tuple(sorted(required - set(self.acknowledged_limitations)))
        if missing:
            raise ValueError(
                f"exploratory decision context omits required limitations: {missing}"
            )


@runtime_checkable
class ExploratoryReconstructedRuntimeStrategy(Protocol):
    """Strategy interface for the EXPLORATORY reconstructed decision path.

    Deliberately a different method name from ``RuntimeStrategy.decide``. A
    strategy that only implements ``decide`` can never be handed reconstructed
    evidence, and the realized and promotion path can never call this method,
    because that path does not know it exists. A strategy may implement both
    methods; the evaluator calls exactly the one its lane dictates.
    """

    @property
    def strategy_reference(self) -> StrategyReference:
        """Provenance reference for the executing strategy version."""
        ...

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        """Answer an exploratory reconstructed context with a target intent."""
        ...


def stage_exploratory_decision_targets(
    intent: StrategyDecisionIntentV1,
    context: ExploratoryStrategyDecisionContextV1,
) -> tuple[SecurityTargetPositionV1, ...]:
    """Validate one exploratory intent and stage the complete target set.

    The staging contract is identical to the realized path's, because it is a
    property of the intent rather than of the evidence grade: whole shares,
    non-negative, no unadmitted entries, and an explicit zero for any held
    security the intent omits. The admitted set is the context's
    ``admitted_cohort``, never a historical universe: the engine builds it as
    the declared cohort restricted to the members with reconstructed history
    at the decision cutoff (issue 130).
    """
    return _stage_targets(
        intent=intent,
        session_key=context.session_key,
        decision_cutoff=context.decision_cutoff,
        admitted_universe=context.admitted_cohort,
        current_holdings=context.current_holdings,
    )
