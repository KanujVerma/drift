"""Unit tests for the EXPLORATORY-only reconstructed decision contracts.

These contracts exist so the scheduled-reconstruction lane can invoke a
strategy without ever pretending its evidence is realized-session authority.
Every test here asks whether the weaker grade stays weaker: the type is
distinct from `StrategyDecisionViewV1`, it refuses realized authority, it
refuses evidence from after its own session, and it refuses to lose the
limitations its evidence carries.
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from observation_test_support import ObservationHarness, market_uid
from pydantic import ValidationError
from test_evaluator_reconstruction import make_cohort, make_policy

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
)
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
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
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
    StrategyDecisionViewV1,
    StrategyIntentRejectedError,
)
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.reconstruction import (
    build_exploratory_reconstructed_session_observation,
)

CLOCK_LIMITATIONS = (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
JAN5 = date(2026, 1, 5)
JAN6 = date(2026, 1, 6)


# --- genuine scheduled reconstruction fixtures --------------------------


def scheduled_case(
    *,
    session_date: date = JAN5,
    schedule_state: str = "regular",
    security_id: UUID | None = None,
    close: str = "100.000",
) -> tuple[ExploratoryReconstructedSessionObservationV1, SessionClockV1]:
    """One genuinely built reconstruction and the clock over its own session."""
    harness = ObservationHarness(
        session_date=session_date, security_id=security_id, close=close
    )
    harness.attach_sessions(
        schedule_state=schedule_state,  # type: ignore[arg-type]
        realized_outcome="missing",
    )
    horizon = f"{(session_date + timedelta(days=1)).isoformat()}T00:00:00Z"
    query = harness.outcome(
        economic_horizon=horizon,
        evidence_vintage_cutoff=horizon,
        session_date=session_date.isoformat(),
    )
    observation = build_exploratory_reconstructed_session_observation(
        query, harness.context, make_cohort(harness.security_id), make_policy()
    )
    clock = build_scheduled_reconstruction_clock((query,), harness.context)
    return observation, clock


def decision_view(
    observation: ExploratoryReconstructedSessionObservationV1,
    *,
    limitations: tuple[str, ...] | None = None,
) -> ExploratoryReconstructedDecisionViewV1:
    return ExploratoryReconstructedDecisionViewV1(
        security_id=observation.security_id,
        observations=(observation,),
        acknowledged_limitations=(
            tuple(sorted(observation.acknowledged_limitations))
            if limitations is None
            else limitations
        ),
    )


def context_for(
    observation: ExploratoryReconstructedSessionObservationV1,
    clock: SessionClockV1,
    **overrides: object,
) -> ExploratoryStrategyDecisionContextV1:
    session = clock.sessions[-1]
    view = decision_view(observation)
    values: dict[str, object] = {
        "session_key": session.session_key,
        "decision_session": session,
        "decision_cutoff": session.closed_at,
        "cohort_hash": observation.cohort_hash,
        "admitted_cohort": (observation.security_id,),
        "current_holdings": (),
        "current_cash": Decimal("10000.00"),
        "portfolio_nav": Decimal("10000.00"),
        "reconstructed_decision_views": (view,),
        "acknowledged_limitations": tuple(
            sorted(
                {
                    *view.acknowledged_limitations,
                    *CLOCK_LIMITATIONS,
                    ALPACA_LIMITATION_BOUNDED_COHORT,
                }
            )
        ),
    }
    values.update(overrides)
    return ExploratoryStrategyDecisionContextV1(**values)  # type: ignore[arg-type]


def relabelled_as_realized(session: EvaluationSessionV1) -> EvaluationSessionV1:
    """The laundering attack: one scheduled session wearing realized authority."""
    draft = EvaluationSessionV1.model_construct(
        **(dict(session) | {"authority": "realized"})
    )
    return EvaluationSessionV1.model_validate(
        dict(draft) | {"session_hash": evaluation_session_hash(draft)}
    )


# --- the reconstructed decision view ------------------------------------


def test_a_reconstructed_decision_view_carries_its_observations() -> None:
    observation, _ = scheduled_case()
    view = decision_view(observation)

    assert view.evidence_grade == EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
    assert view.security_id == observation.security_id
    assert view.observations == (observation,)
    assert view.acknowledged_limitations == tuple(
        sorted(observation.acknowledged_limitations)
    )


def test_a_reconstructed_decision_view_is_not_a_strategy_decision_view() -> None:
    observation, _ = scheduled_case()
    view = decision_view(observation)

    assert not isinstance(view, StrategyDecisionViewV1)
    assert not isinstance(observation, StrategyDecisionViewV1)


def test_the_strong_decision_view_refuses_a_reconstructed_observation() -> None:
    observation, _ = scheduled_case()

    with pytest.raises(ValidationError) as error:
        StrategyDecisionViewV1(
            security_id=observation.security_id,
            views=(observation,),  # type: ignore[arg-type]
        )

    errors = error.value.errors(include_url=False)
    assert errors, "the strong view must reject the weaker type on shape"
    assert [
        (item["type"], item["loc"], item["ctx"]["class_name"]) for item in errors
    ] == [("model_type", ("views", 0), "DerivedObservationViewV1")]


def test_the_strong_decision_context_refuses_a_reconstructed_decision_view() -> None:
    observation, clock = scheduled_case()
    session = clock.sessions[-1]

    with pytest.raises(ValidationError) as error:
        StrategyDecisionContextV1(
            session_key=session.session_key,
            decision_session=session,
            decision_cutoff=session.closed_at,
            admitted_universe=(observation.security_id,),
            current_holdings=(),
            current_cash=Decimal("1"),
            portfolio_nav=Decimal("1"),
            decision_views=(decision_view(observation),),  # type: ignore[arg-type]
        )

    errors = error.value.errors(include_url=False)
    assert errors, "the strong context must reject the weaker view on shape"
    assert [
        (item["type"], item["loc"], item["ctx"]["class_name"]) for item in errors
    ] == [("model_type", ("decision_views", 0), "StrategyDecisionViewV1")]


def test_a_reconstructed_decision_view_requires_at_least_one_observation() -> None:
    observation, _ = scheduled_case()

    with pytest.raises(
        ValidationError,
        match="reconstructed decision view requires at least one observation",
    ):
        ExploratoryReconstructedDecisionViewV1(
            security_id=observation.security_id,
            observations=(),
            acknowledged_limitations=tuple(
                sorted(observation.acknowledged_limitations)
            ),
        )


def test_a_reconstructed_decision_view_binds_one_security() -> None:
    first, _ = scheduled_case()
    foreign, _ = scheduled_case(security_id=market_uid(260))
    assert foreign.security_id != first.security_id

    with pytest.raises(
        ValidationError,
        match="reconstructed decision view members must share the security",
    ):
        ExploratoryReconstructedDecisionViewV1(
            security_id=first.security_id,
            observations=(first, foreign),
            acknowledged_limitations=tuple(sorted(first.acknowledged_limitations)),
        )


def test_a_reconstructed_decision_view_states_exactly_its_own_limitations() -> None:
    observation, _ = scheduled_case()
    assert ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION in (
        observation.acknowledged_limitations
    )
    dropped = tuple(
        item
        for item in sorted(observation.acknowledged_limitations)
        if item != ALPACA_LIMITATION_UNVERSIONED_BARS
    )
    assert len(dropped) < len(observation.acknowledged_limitations)

    with pytest.raises(
        ValidationError,
        match="reconstructed decision view must acknowledge exactly",
    ):
        decision_view(observation, limitations=dropped)


def test_a_reconstructed_decision_view_refuses_invented_limitations() -> None:
    observation, _ = scheduled_case()
    padded = tuple(sorted({*observation.acknowledged_limitations, "invented"}))

    with pytest.raises(
        ValidationError,
        match="reconstructed decision view must acknowledge exactly",
    ):
        decision_view(observation, limitations=padded)


# --- the exploratory decision context -----------------------------------


def test_an_exploratory_context_is_permanently_non_promotable() -> None:
    observation, clock = scheduled_case()
    context = context_for(observation, clock)

    assert context.lane == "exploratory"
    assert context.is_promotion_grade_evidence is False
    assert context.evidence_grade == EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE

    # Three literals on a frozen model, so no assignment, copy, or
    # revalidation can raise this context's standing.
    for field, value in (
        ("is_promotion_grade_evidence", True),
        ("lane", "promotion"),
        ("evidence_grade", "authentic_decision_views"),
    ):
        with pytest.raises(ValidationError) as error:
            ExploratoryStrategyDecisionContextV1.model_validate(
                dict(context) | {field: value}
            )
        assert {item["loc"] for item in error.value.errors(include_url=False)} == {
            (field,)
        }


def test_an_exploratory_context_refuses_realized_session_authority() -> None:
    """The Absolute Non-Upgrade Rule, at the decision boundary."""
    observation, clock = scheduled_case()
    laundered = relabelled_as_realized(clock.sessions[-1])
    assert laundered.authority == "realized"

    with pytest.raises(
        ValidationError,
        match=(
            "exploratory reconstructed decisions require scheduled "
            "reconstruction session authority"
        ),
    ):
        context_for(observation, clock, decision_session=laundered)


def test_an_exploratory_context_decides_exactly_at_the_scheduled_close() -> None:
    observation, clock = scheduled_case()
    session = clock.sessions[-1]

    context = context_for(observation, clock)
    assert context.decision_cutoff == session.closed_at

    with pytest.raises(
        ValidationError,
        match="exploratory decision cutoff must be the scheduled session close",
    ):
        context_for(observation, clock, decision_cutoff=session.opened_at)


def test_an_exploratory_context_refuses_evidence_from_a_later_session() -> None:
    """No lookahead: session D may not read the bar printed on session D+1."""
    today, clock = scheduled_case(session_date=JAN5)
    tomorrow, _ = scheduled_case(session_date=JAN6)
    assert tomorrow.session_key.local_date > today.session_key.local_date

    with pytest.raises(
        ValidationError,
        match="reconstructed decision evidence sourced after its decision session",
    ):
        context_for(
            today,
            clock,
            reconstructed_decision_views=(decision_view(tomorrow),),
            admitted_cohort=(tomorrow.security_id,),
        )


def test_an_exploratory_context_requires_evidence_at_all() -> None:
    observation, clock = scheduled_case()

    with pytest.raises(
        ValidationError,
        match=(
            "exploratory decision context requires at least one reconstructed "
            "decision view"
        ),
    ):
        context_for(observation, clock, reconstructed_decision_views=())


def test_an_exploratory_context_binds_its_declared_cohort() -> None:
    observation, clock = scheduled_case()

    with pytest.raises(
        ValidationError,
        match="reconstructed decision evidence must bind the declared cohort",
    ):
        context_for(observation, clock, cohort_hash="f" * 64)


def test_an_exploratory_context_refuses_evidence_outside_its_cohort() -> None:
    observation, clock = scheduled_case()
    other = observation.security_id
    stranger = type(other)(int=other.int ^ 1)

    with pytest.raises(
        ValidationError,
        match="reconstructed decision evidence must describe an admitted cohort",
    ):
        context_for(observation, clock, admitted_cohort=(stranger,))


def test_an_exploratory_context_propagates_every_evidence_limitation() -> None:
    observation, clock = scheduled_case()
    context = context_for(observation, clock)

    assert context.acknowledged_limitations
    for limitation in observation.acknowledged_limitations:
        assert limitation in context.acknowledged_limitations
    for limitation in CLOCK_LIMITATIONS:
        assert limitation in context.acknowledged_limitations


def _without(
    observation: ExploratoryReconstructedSessionObservationV1, limitation: str
) -> tuple[str, ...]:
    """Every limitation the context must carry, except exactly one."""
    full = tuple(
        sorted(
            {
                *observation.acknowledged_limitations,
                *CLOCK_LIMITATIONS,
                ALPACA_LIMITATION_BOUNDED_COHORT,
            }
        )
    )
    dropped = tuple(item for item in full if item != limitation)
    assert len(dropped) == len(full) - 1
    return dropped


def _omits(limitation: str) -> str:
    """The guard's message naming exactly one omitted limitation."""
    return "exploratory decision context omits required limitations: " + re.escape(
        repr((limitation,))
    )


def test_an_exploratory_context_cannot_drop_an_evidence_limitation() -> None:
    observation, clock = scheduled_case()
    limitation = ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION

    with pytest.raises(ValidationError, match=_omits(limitation)):
        context_for(
            observation,
            clock,
            acknowledged_limitations=_without(observation, limitation),
        )


def test_an_exploratory_context_cannot_drop_the_scheduled_clock_limitations() -> None:
    observation, clock = scheduled_case()
    for limitation in CLOCK_LIMITATIONS:
        with pytest.raises(ValidationError, match=_omits(limitation)):
            context_for(
                observation,
                clock,
                acknowledged_limitations=_without(observation, limitation),
            )


# --- issue 46 hardening: history order, calendar binding, cohort ---------


def test_a_reconstructed_decision_view_reads_its_history_in_business_time() -> None:
    days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
    observations = tuple(scheduled_case(session_date=day)[0] for day in days)
    by_hash = tuple(sorted(observations, key=lambda item: item.reconstruction_hash))
    # Precondition: content-hash order is not business-time order, so the
    # assertion below can tell the two canonical orders apart.
    assert by_hash != observations

    view = ExploratoryReconstructedDecisionViewV1(
        security_id=observations[0].security_id,
        observations=tuple(reversed(observations)),
        acknowledged_limitations=tuple(
            sorted(observations[0].acknowledged_limitations)
        ),
    )

    assert [item.session_key.local_date for item in view.observations] == list(days)


def test_a_reconstructed_decision_view_refuses_two_answers_for_one_session() -> None:
    first, _ = scheduled_case()
    second, _ = scheduled_case(close="101.000")
    assert first.session_key == second.session_key
    assert first.reconstruction_hash != second.reconstruction_hash

    with pytest.raises(
        ValidationError,
        match="reconstructed decision view members must be unique by session",
    ):
        ExploratoryReconstructedDecisionViewV1(
            security_id=first.security_id,
            observations=(first, second),
            acknowledged_limitations=tuple(sorted(first.acknowledged_limitations)),
        )


def test_an_exploratory_context_requires_evidence_for_its_own_session() -> None:
    """A decision at the close of D that never read D decided on stale data."""
    yesterday, _ = scheduled_case(session_date=JAN5)
    _, clock = scheduled_case(session_date=JAN6)

    with pytest.raises(
        ValidationError,
        match=(
            "exploratory decision context requires reconstructed evidence for "
            "its own scheduled decision session XNYS 2026-01-06"
        ),
    ):
        context_for(yesterday, clock)

    # Control: yesterday's bar is admissible history beside today's.
    today, _ = scheduled_case(session_date=JAN6)
    context = context_for(
        today,
        clock,
        reconstructed_decision_views=(
            ExploratoryReconstructedDecisionViewV1(
                security_id=today.security_id,
                observations=(yesterday, today),
                acknowledged_limitations=tuple(sorted(today.acknowledged_limitations)),
            ),
        ),
    )
    assert len(context.reconstructed_decision_views[0].observations) == 2


def test_an_exploratory_context_refuses_a_bar_built_on_another_calendar_row() -> None:
    """A 16:00 calendar row's bar cannot be read at a 13:00 scheduled close."""
    regular, _ = scheduled_case(session_date=JAN6)
    _, early_clock = scheduled_case(session_date=JAN6, schedule_state="early_close")
    assert regular.session_key == early_clock.sessions[-1].session_key
    assert regular.generated_session_row_hash not in (
        early_clock.sessions[-1].authority_record_hashes
    )

    with pytest.raises(
        ValidationError,
        match=(
            "reconstructed decision evidence must bind the scheduled calendar "
            "row its decision session was generated from"
        ),
    ):
        context_for(regular, early_clock)

    # Control: the bar built on the early close's own row is admitted.
    early, _ = scheduled_case(session_date=JAN6, schedule_state="early_close")
    assert context_for(early, early_clock).decision_cutoff == (
        early_clock.sessions[-1].closed_at
    )


def test_an_exploratory_context_cannot_drop_the_bounded_cohort_limitation() -> None:
    observation, clock = scheduled_case()
    full = tuple(
        sorted(
            {
                *observation.acknowledged_limitations,
                *CLOCK_LIMITATIONS,
                ALPACA_LIMITATION_BOUNDED_COHORT,
            }
        )
    )
    dropped = tuple(item for item in full if item != ALPACA_LIMITATION_BOUNDED_COHORT)
    assert len(dropped) == len(full) - 1

    with pytest.raises(
        ValidationError,
        match="exploratory decision context omits required limitations",
    ):
        context_for(observation, clock, acknowledged_limitations=dropped)


def test_an_early_close_context_decides_at_the_scheduled_13_00_close() -> None:
    observation, clock = scheduled_case(session_date=JAN6, schedule_state="early_close")
    session = clock.sessions[-1]

    context = context_for(observation, clock)

    assert context.decision_cutoff == session.closed_at
    assert context.decision_cutoff.hour == 18  # 13:00 New York, EST
    for too_early in (session.opened_at, session.closed_at - timedelta(minutes=1)):
        with pytest.raises(
            ValidationError,
            match="exploratory decision cutoff must be the scheduled session close",
        ):
            context_for(observation, clock, decision_cutoff=too_early)


# --- staging targets from an exploratory decision -----------------------


def test_staging_accepts_an_intent_bound_to_the_scheduled_cutoff() -> None:
    observation, clock = scheduled_case()
    context = context_for(observation, clock)
    intent = StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=(
            SecurityTargetPositionV1(
                security_id=observation.security_id, target_quantity=3
            ),
        ),
    )

    staged = stage_exploratory_decision_targets(intent, context)

    assert staged == intent.targets


def test_staging_refuses_a_target_outside_the_admitted_cohort() -> None:
    observation, clock = scheduled_case()
    context = context_for(observation, clock)
    stranger = type(observation.security_id)(int=observation.security_id.int ^ 1)
    intent = StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=stranger, target_quantity=1),),
    )

    with pytest.raises(
        StrategyIntentRejectedError,
        match="a positive target requires an admitted security",
    ):
        stage_exploratory_decision_targets(intent, context)


def test_staging_liquidates_a_holding_the_intent_omits() -> None:
    observation, clock = scheduled_case()
    holding = PositionViewV1(
        security_id=observation.security_id,
        quantity=4,
        cost_basis=Decimal("400.00"),
        average_cost_per_share=Decimal("100.00"),
    )
    context = context_for(observation, clock, current_holdings=(holding,))
    intent = StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=(),
    )

    staged = stage_exploratory_decision_targets(intent, context)

    assert staged == (
        SecurityTargetPositionV1(
            security_id=observation.security_id, target_quantity=0
        ),
    )


def test_staging_refuses_an_intent_answering_a_different_cutoff() -> None:
    observation, clock = scheduled_case()
    context = context_for(observation, clock)
    intent = StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_session.opened_at,
        targets=(),
    )

    with pytest.raises(
        StrategyIntentRejectedError,
        match="decision intent decision_time must strictly match",
    ):
        stage_exploratory_decision_targets(intent, context)
