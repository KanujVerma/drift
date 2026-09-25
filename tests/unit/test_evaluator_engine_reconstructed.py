"""Unit tests for the engine's EXPLORATORY reconstructed decision lane (issue 46).

A ``scheduled_session_reconstruction`` bundle carries no authentic decision or
accounting view, so before issue 46 every exploratory run over one halted
INDETERMINATE before its strategy was invoked once. These tests pin the lane
that replaces that halt: an exploratory admission over a scheduled clock
hands the strategy a dedicated ``ExploratoryStrategyDecisionContextV1`` built
from reconstructed observations, and nothing else changes.

Every ``pytest.raises`` names text unique to the guard under test, so an
earlier guard firing first fails the test instead of satisfying it.
"""

from datetime import date
from uuid import UUID

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    JAN7,
    LISTING,
    LISTING_OTHER,
    SEC,
    SEC_OTHER,
    DualLaneStrategy,
    RealizedOnlyStrategy,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    exploratory_admission,
    reconstructed_engine,
    run_engine,
    scheduled_bundle,
    scheduled_session_case,
    three_regular_sessions,
    utc_close,
)
from observation_test_support import market_uid
from test_evaluator_engine import FixedTargetStrategy, _buy_ten, _engine, _run

from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_clock import EvaluationSessionV1, evaluation_session_hash
from drift.domain.evaluator_exploratory_strategy import (
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION,
    ExploratoryEvaluationAdmissionV1,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
    ExploratoryEvaluationResultV1,
)
from drift.domain.evaluator_trace import (
    EvaluationPhase,
    ExploratoryStrategyDecisionTraceEventV1,
)
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence
from drift.serialization.canonical import content_hash


def _exploratory_events(
    artifacts: EvaluationRunArtifactsV1,
) -> list[ExploratoryStrategyDecisionTraceEventV1]:
    return [
        event
        for event in artifacts.trace.events
        if isinstance(event, ExploratoryStrategyDecisionTraceEventV1)
    ]


def _hold_cash() -> ReconstructedTargetStrategy:
    return ReconstructedTargetStrategy({})


# --- the lane runs, and the strategy is actually invoked ----------------


def test_a_scheduled_reconstruction_run_invokes_its_strategy() -> None:
    """The issue 42 symptom, inverted: the strategy is reached every session."""
    strategy = _hold_cash()

    artifacts = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert len(strategy.seen) == 3
    assert all(
        isinstance(context, ExploratoryStrategyDecisionContextV1)
        for context in strategy.seen
    )
    assert [context.session_key.local_date for context in strategy.seen] == [
        JAN5,
        JAN6,
        JAN7,
    ]


def test_each_context_reads_exactly_the_history_its_cutoff_has_closed() -> None:
    """No lookahead: session D sees sessions up to D and never D+1."""
    strategy = _hold_cash()

    run_engine(reconstructed_engine(bundle_of(three_regular_sessions())), strategy)

    assert strategy.seen, "the strategy was never invoked"
    visible = [
        [
            observation.session_key.local_date
            for view in context.reconstructed_decision_views
            for observation in view.observations
        ]
        for context in strategy.seen
    ]
    assert visible == [[JAN5], [JAN5, JAN6], [JAN5, JAN6, JAN7]]


def test_each_decision_is_traced_as_an_exploratory_reconstructed_decision() -> None:
    strategy = _hold_cash()
    cases = three_regular_sessions()

    artifacts = run_engine(reconstructed_engine(bundle_of(cases)), strategy)

    events = _exploratory_events(artifacts)
    assert len(events) == 3
    # The strong event kind never records a decision taken on this grade.
    assert not [
        event for event in artifacts.trace.events if event.kind == "strategy_decision"
    ]
    hashes = [observation.reconstruction_hash for observation, _ in cases]
    for position, (event, context) in enumerate(
        zip(events, strategy.seen, strict=True)
    ):
        assert event.context_hash == content_hash(context)
        assert event.decision_cutoff == context.decision_cutoff
        assert event.reconstruction_hashes == tuple(sorted(hashes[: position + 1]))
        assert event.evidence_grade == "exploratory_reconstructed"
        assert event.is_promotion_grade_evidence is False
        assert event.outcome == "staged"


def test_limitations_propagate_from_the_admission_into_every_artifact() -> None:
    strategy = _hold_cash()
    bundle = bundle_of(three_regular_sessions())
    engine = reconstructed_engine(bundle)

    artifacts = run_engine(engine, strategy)

    admission = engine.admission
    assert isinstance(admission, ExploratoryEvaluationAdmissionV1)
    acknowledged = admission.acknowledged_limitations
    assert set(RECONSTRUCTED_DECISION_LIMITATIONS) <= set(acknowledged)
    assert set(bundle.required_limitations) <= set(acknowledged)
    result = artifacts.result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    assert result.admission.acknowledged_limitations == acknowledged
    events = _exploratory_events(artifacts)
    assert events, "no exploratory decision was traced"
    for event, context in zip(events, strategy.seen, strict=True):
        assert event.acknowledged_limitations == acknowledged
        assert context.acknowledged_limitations == acknowledged


def test_the_warmup_defers_the_first_exploratory_decision() -> None:
    from test_evaluator_engine import _protocol

    strategy = _hold_cash()

    run_engine(
        reconstructed_engine(
            bundle_of(three_regular_sessions()), protocol=_protocol(warmup=2)
        ),
        strategy,
    )

    assert [context.session_key.local_date for context in strategy.seen] == [
        JAN6,
        JAN7,
    ]


def test_each_decision_is_taken_at_its_own_scheduled_close() -> None:
    strategy = _hold_cash()

    run_engine(reconstructed_engine(bundle_of(three_regular_sessions())), strategy)

    assert strategy.seen, "the strategy was never invoked"
    for context in strategy.seen:
        day = context.session_key.local_date
        assert context.decision_cutoff == utc_close(day, "regular")
        assert context.decision_cutoff == context.decision_session.closed_at
        assert context.decision_session.authority == "scheduled_reconstruction"


# --- fail closed ----------------------------------------------------------


def test_a_decision_session_without_reconstructed_evidence_fails_closed() -> None:
    """A scheduled session with no bar is unknown, never a halt, never a skip."""
    (jan5, jan5_session), (_, jan6_session) = (
        scheduled_session_case(JAN5),
        scheduled_session_case(JAN6),
    )
    bundle = scheduled_bundle((jan5,), (jan5_session, jan6_session))
    strategy = _hold_cash()

    artifacts = run_engine(reconstructed_engine(bundle), strategy)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert causes[0].cause == (
        "no reconstructed decision evidence for the scheduled decision session "
        "XNYS 2026-01-06"
    )
    assert [context.session_key.local_date for context in strategy.seen] == [JAN5]


def test_two_reconstructions_of_one_session_fail_closed() -> None:
    first, session = scheduled_session_case(JAN5)
    second, same_session = scheduled_session_case(JAN5, close="101.000")
    assert first.reconstruction_hash != second.reconstruction_hash
    # Both bars were reconstructed on one and the same calendar row.
    assert session.authority_record_hashes == same_session.authority_record_hashes
    (jan6, jan6_session) = scheduled_session_case(JAN6)
    bundle = scheduled_bundle((first, second, jan6), (session, jan6_session))

    artifacts = run_engine(reconstructed_engine(bundle), _hold_cash())

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 0
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].cause.startswith(
        "more than one reconstructed observation for security"
    )


def test_a_rejected_exploratory_intent_is_traced_and_classified_rejected() -> None:
    strategy = ReconstructedTargetStrategy({JAN5: ((SEC_OTHER, 1),)})

    artifacts = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halted_session_index == 0
    events = _exploratory_events(artifacts)
    assert len(events) == 1
    assert events[0].outcome == "rejected"
    assert events[0].staged_targets == ()
    assert events[0].rejection_reason is not None
    assert events[0].rejection_reason.startswith(
        "a positive target requires an admitted security"
    )


# --- construction guards ----------------------------------------------------


def test_a_strong_input_strategy_cannot_run_the_scheduled_lane() -> None:
    """Reconstructed evidence is never passed to ``decide``, not even once."""
    strategy = RealizedOnlyStrategy()
    engine = reconstructed_engine(bundle_of(three_regular_sessions()))

    with pytest.raises(TypeError, match=r"its strategy must answer decide_exploratory"):
        run_engine(engine, strategy)

    assert strategy.seen == []


def test_the_scheduled_lane_requires_its_declared_cohort() -> None:
    bundle = bundle_of(three_regular_sessions())

    with pytest.raises(
        ValueError,
        match=r"requires its predeclared exploratory cohort",
    ):
        reconstructed_engine(bundle, with_cohort=False)


def test_a_reconstruction_bound_to_another_cohort_is_refused() -> None:
    bundle = bundle_of(three_regular_sessions())
    foreign = cohort_of((SEC, SEC_OTHER))
    assert foreign.cohort_hash != cohort_of().cohort_hash

    with pytest.raises(ValueError, match=r"does not bind the declared cohort"):
        reconstructed_engine(bundle, cohort=foreign)


def test_an_admission_omitting_a_reconstruction_limitation_is_refused() -> None:
    bundle = bundle_of(three_regular_sessions())
    everything = exploratory_admission(bundle).acknowledged_limitations
    dropped = tuple(
        item
        for item in everything
        if item != ALPACA_LIMITATION_RETROSPECTIVE_RECONSTRUCTION
    )
    assert len(dropped) == len(everything) - 1

    with pytest.raises(
        ValueError, match=r"^exploratory admission omits required bundle limitations"
    ):
        reconstructed_engine(
            bundle, admission=exploratory_admission(bundle, limitations=dropped)
        )


def test_an_admission_omitting_the_bounded_cohort_is_refused() -> None:
    bundle = bundle_of(three_regular_sessions())
    assert ALPACA_LIMITATION_BOUNDED_COHORT not in bundle.required_limitations

    with pytest.raises(
        ValueError, match=r"^exploratory admission omits the bounded cohort limitation"
    ):
        reconstructed_engine(
            bundle,
            admission=exploratory_admission(
                bundle, limitations=bundle.required_limitations
            ),
        )


PAIR = (SEC, SEC_OTHER)


def _resealed(session: EvaluationSessionV1, **update: object) -> EvaluationSessionV1:
    """One session edited and re-hashed, so only a semantic guard can refuse it."""
    draft = EvaluationSessionV1.model_construct(**(dict(session) | update))
    return EvaluationSessionV1.model_validate(
        dict(draft) | {"session_hash": evaluation_session_hash(draft)}
    )


@pytest.mark.parametrize("built_by", ["SEC", "SEC_OTHER"])
def test_one_clock_session_serves_every_cohort_member_on_its_calendar_row(
    built_by: str,
) -> None:
    """The lane gate binds a clock session to its builder, not to one query.

    A clock session re-derives exactly only from the request whose query
    selected it, because its selection proofs name that query (issue 84).
    Another cohort member's request on the same session names the same
    calendar row, so it re-derives the same boundaries under its own proofs,
    and the run proceeds whichever member's query built the clock session.

    SEC_OTHER carries its JAN6 bar too. Without it the JAN6 context would be
    incomplete and halt (issue 87), which is not the binding under test.
    """
    ours, session = scheduled_session_case(JAN5, cohort_securities=PAIR)
    other, other_session = scheduled_session_case(
        JAN5, security_id=SEC_OTHER, listing_id=LISTING_OTHER, cohort_securities=PAIR
    )
    later, later_session = scheduled_session_case(JAN6, cohort_securities=PAIR)
    other_later, _ = scheduled_session_case(
        JAN6, security_id=SEC_OTHER, listing_id=LISTING_OTHER, cohort_securities=PAIR
    )
    assert other_session.authority_record_hashes == session.authority_record_hashes
    assert other_session.authority_proof_hashes != session.authority_proof_hashes
    clock_session = session if built_by == "SEC" else other_session
    bundle = scheduled_bundle(
        (ours, other, later, other_later), (clock_session, later_session)
    )
    assert bundle.session_clock.sessions[0] == clock_session

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), _hold_cash()
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE


def test_a_scheduled_clock_must_be_built_from_its_replays_own_queries() -> None:
    """A genuine session selected by a query outside the replay is refused.

    SEC_OTHER's query built the JAN5 clock session on the very row SEC's
    reconstruction names, so boundaries and records agree. Only its selection
    proofs differ, and no replay request carries the query they name.
    """
    ours, _ = scheduled_session_case(JAN5, cohort_securities=PAIR)
    _, outside = scheduled_session_case(
        JAN5, security_id=SEC_OTHER, listing_id=LISTING_OTHER, cohort_securities=PAIR
    )
    later, later_session = scheduled_session_case(JAN6, cohort_securities=PAIR)
    bundle = scheduled_bundle((ours, later), (outside, later_session))

    with pytest.raises(
        ValueError,
        match=(
            r"^scheduled clock session on XNYS 2026-01-05 carries selection proofs "
            r"no replay request on it derives$"
        ),
    ):
        reconstructed_engine(bundle, cohort=cohort_of(PAIR))


def test_a_union_authority_session_cannot_vouch_for_two_calendar_rows() -> None:
    """One session naming a regular and an early-close row is refused.

    Each member's reconstruction finds its own row among the session's
    records, so the calendar-row binding passes. The session keeps the
    regular row's boundaries, so the refusal names the records, not them.
    """
    jan5, jan5_session = scheduled_session_case(JAN5, cohort_securities=PAIR)
    regular, regular_session = scheduled_session_case(JAN6, cohort_securities=PAIR)
    early, early_session = scheduled_session_case(
        JAN6,
        "early_close",
        security_id=SEC_OTHER,
        listing_id=LISTING_OTHER,
        cohort_securities=PAIR,
    )
    union = _resealed(
        regular_session,
        authority_record_hashes=tuple(
            sorted(
                {
                    *regular_session.authority_record_hashes,
                    *early_session.authority_record_hashes,
                }
            )
        ),
    )
    bundle = scheduled_bundle((jan5, regular, early), (jan5_session, union))

    with pytest.raises(
        ValueError,
        match=(
            r"^scheduled clock session on XNYS 2026-01-06 names calendar records "
            r"no replay request on it derives$"
        ),
    ):
        reconstructed_engine(bundle, cohort=cohort_of(PAIR))


def test_an_exploratory_cohort_is_refused_outside_the_scheduled_lane() -> None:
    from test_evaluator_engine import (
        BOOK_CODE,
        BOOK_NAMESPACE,
        ROLE_RECORDS,
        _admission,
        _bundle,
        _cost_model,
        _protocol,
    )

    bundle = _bundle()
    assert bundle.session_clock.mode == "realized_session_authority"

    with pytest.raises(
        ValueError, match=r"an exploratory cohort scopes only a scheduled"
    ):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=_admission(bundle),
            protocol=_protocol(),
            cost_model=_cost_model(),
            evidence=SessionEvaluatorEvidence(
                listing_role_records=ROLE_RECORDS, exploratory_cohort=cohort_of()
            ),
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )


# --- every member with history is current at its decision (issue 87) --------

SEC_THIRD = market_uid(400)
LISTING_THIRD = market_uid(401)
TRIO = (SEC, SEC_OTHER, SEC_THIRD)
_LISTING_OF = {SEC: LISTING, SEC_OTHER: LISTING_OTHER, SEC_THIRD: LISTING_THIRD}
_ALL_DAYS = (JAN5, JAN6, JAN7)


def _cohort_bundle(
    bars: dict[UUID, tuple[date, ...]], cohort: tuple[UUID, ...] = PAIR
) -> EvaluationInputBundleV1:
    """Genuine reconstructions of each member on exactly the days it names.

    Each clock session is the one the first member carrying that day built, so
    every clock session re-derives from a replay request actually in the run.
    """
    cases = {
        (security_id, day): scheduled_session_case(
            day,
            security_id=security_id,
            listing_id=_LISTING_OF[security_id],
            cohort_securities=cohort,
        )
        for security_id, days in bars.items()
        for day in days
    }
    clock: dict[date, EvaluationSessionV1] = {}
    for (_, day), (_, session) in cases.items():
        clock.setdefault(day, session)
    return scheduled_bundle(
        tuple(observation for observation, _ in cases.values()), tuple(clock.values())
    )


def _visible(
    strategy: ReconstructedTargetStrategy,
) -> list[dict[UUID, list[date]]]:
    """Per decision, each member's reconstructed history as the context shows it."""
    return [
        {
            view.security_id: [
                observation.session_key.local_date for observation in view.observations
            ]
            for view in context.reconstructed_decision_views
        }
        for context in strategy.seen
    ]


def _incomplete(*members: tuple[UUID, date]) -> str:
    """The issue 87 halt cause at the JAN6 decision, member by member."""
    return (
        "incomplete reconstructed decision context at the scheduled decision "
        "session XNYS 2026-01-06: "
        + "; ".join(
            f"cohort security {security_id} has reconstructed history through "
            f"XNYS {through.isoformat()} but no reconstruction for that session"
            for security_id, through in members
        )
    )


@pytest.mark.parametrize("lacking", [SEC, SEC_OTHER], ids=["first", "second"])
def test_a_member_lacking_its_decision_session_halts_even_if_never_traded(
    lacking: UUID,
) -> None:
    """The context is incomplete whether or not the strategy would trade it.

    The strategy holds cash throughout, so no execution or mark could catch
    the gap later. Either member, first or second in canonical order, halts
    the JAN6 decision before the strategy is asked, naming itself and the
    session, and its history ending JAN5.
    """
    present = SEC_OTHER if lacking == SEC else SEC
    strategy = _hold_cash()
    bundle = _cohort_bundle({present: _ALL_DAYS, lacking: (JAN5, JAN7)})

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert causes[0].cause_kind == "indeterminate_valuation"
    assert causes[0].cause == _incomplete((lacking, JAN5))
    assert artifacts.result.halt_reason == causes[0].cause
    assert [context.session_key.local_date for context in strategy.seen] == [JAN5]
    assert [
        event.session_key.local_date for event in _exploratory_events(artifacts)
    ] == [JAN5]


def test_every_lacking_member_is_named_in_canonical_order() -> None:
    strategy = _hold_cash()
    bundle = _cohort_bundle(
        {SEC_THIRD: (JAN5, JAN7), SEC: _ALL_DAYS, SEC_OTHER: (JAN5, JAN7)},
        cohort=TRIO,
    )

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(TRIO)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    assert artifacts.result.halt_reason == _incomplete(
        (SEC_OTHER, JAN5), (SEC_THIRD, JAN5)
    )


def test_a_member_with_no_reconstructed_history_is_absent_and_never_halts() -> None:
    """The existing rule: no history is no view, and the cohort still admits it."""
    strategy = _hold_cash()
    bundle = _cohort_bundle({SEC: _ALL_DAYS})

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _visible(strategy) == [
        {SEC: [JAN5]},
        {SEC: [JAN5, JAN6]},
        {SEC: [JAN5, JAN6, JAN7]},
    ]
    assert all(set(context.admitted_cohort) == set(PAIR) for context in strategy.seen)


def test_a_member_whose_history_starts_later_joins_the_context_when_it_starts() -> None:
    """Before its first reconstruction a member has no history, so no halt."""
    strategy = _hold_cash()
    bundle = _cohort_bundle({SEC: _ALL_DAYS, SEC_OTHER: (JAN6, JAN7)})

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _visible(strategy) == [
        {SEC: [JAN5]},
        {SEC: [JAN5, JAN6], SEC_OTHER: [JAN6]},
        {SEC: [JAN5, JAN6, JAN7], SEC_OTHER: [JAN6, JAN7]},
    ]


def test_trading_a_member_without_history_still_fails_closed_at_the_open() -> None:
    """The existing rule is unchanged: no reconstructed open, no fill."""
    strategy = ReconstructedTargetStrategy({JAN5: ((SEC_OTHER, 1),)})
    bundle = _cohort_bundle({SEC: _ALL_DAYS})

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.OPEN_EXECUTION
    assert causes[0].cause == (
        "no exploratory reconstructed accounting price for security "
        f"{SEC_OTHER} on XNYS 2026-01-06"
    )
    assert not [event for event in artifacts.trace.events if event.kind == "fill"]


def test_a_complete_cohort_context_carries_every_members_full_history() -> None:
    """Control: with every bar present the run completes and trades as before."""
    strategy = ReconstructedTargetStrategy({JAN6: ((SEC_OTHER, 1),)})
    bundle = _cohort_bundle({SEC: _ALL_DAYS, SEC_OTHER: _ALL_DAYS})

    artifacts = run_engine(
        reconstructed_engine(bundle, cohort=cohort_of(PAIR)), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _visible(strategy) == [
        {SEC: [JAN5], SEC_OTHER: [JAN5]},
        {SEC: [JAN5, JAN6], SEC_OTHER: [JAN5, JAN6]},
        {SEC: [JAN5, JAN6, JAN7], SEC_OTHER: [JAN5, JAN6, JAN7]},
    ]
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [
        (event.session_key.local_date, event.fill.security_id) for event in fills
    ] == [(JAN7, SEC_OTHER)]


# --- the realized lane is untouched -----------------------------------------


def test_the_realized_lane_never_calls_decide_exploratory() -> None:
    """A strategy answering both lanes is handed only strong evidence here."""
    dual = DualLaneStrategy(_buy_ten().targets)

    artifacts = run_engine(_engine(), dual)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert dual.seen_realized, "the realized lane never invoked decide"
    assert dual.seen == []
    assert _exploratory_events(artifacts) == []


def test_a_realized_result_is_identical_whichever_protocol_it_also_answers() -> None:
    """The realized lane's output does not depend on the exploratory method."""
    realized_only: FixedTargetStrategy = _buy_ten()
    dual = DualLaneStrategy(realized_only.targets)

    baseline = _run(_engine(), realized_only)
    answered = run_engine(_engine(), dual)

    assert answered.result.result_hash == baseline.result.result_hash
    assert answered.trace.trace_hash == baseline.trace.trace_hash
