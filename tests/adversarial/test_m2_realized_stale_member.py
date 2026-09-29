"""M2 adversarial acceptance: a realized history is contiguous and current (issue 141).

Finding FA1 F3 of the M2 final acceptance rerun, owner ruling A, extended to
contiguity under the owner's fail-closed operating rule recorded on #62,
exactly as the issue 87 rule was for the reconstructed lane. In the realized
lane a security whose newest decision evidence was older than the session
being decided still reached the strategy as though it were current, and a
target for it filled at the next open: the reviewer probe, a 2026-01-07
decision where SEC_A's newest evidence is its 01-06 bar while SEC_B is
current, ended COMPLETE with SEC_A's history in content-hash order (01-06
before 01-05) and a fill of 10 SEC_A at the 01-08 open.

Two rules now hold, each proven here against a control:

* A security with decision evidence at the cutoff must have a view sourced
  from every clock session from its first viewed session through the
  decision session. A stale or gapped security halts the decision
  INDETERMINATE, before the strategy is asked, naming the session and, in
  canonical order, every such security with its first viewed session and
  each session it lacks.
* Each security's history is held in source-session order, with a content
  hash tie-break between views of one session, whatever order the views
  arrive in.

Every ``pytest.raises`` and every cause assertion names text unique to the
guard under attack, so another guard firing first fails the test. Where a
precondition depends on content hashes, which move whenever the M1d evidence
identity moves, the case is chosen from a fixed family and one must exist.
"""

# ruff: noqa: E402

import itertools
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_engine as eng
from pydantic import ValidationError

from drift.domain.common import UUID7
from drift.domain.evaluator_bundles import EvaluationInputBundleV1
from drift.domain.evaluator_portfolio import IndeterminateValuationError
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionViewV1,
)
from drift.domain.evaluator_trace import EvaluationPhase
from drift.domain.normalization import (
    DerivedObservationViewV1,
    NormalizationQueryV1,
    derived_view_output_hash,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.domain.universes import StructuralEligibilityClassification
from drift.evaluator.engine import _require_contiguous_securities
from drift.serialization.canonical import content_hash

SEC_A = eng.SEC_A
SEC_B = eng.SEC_B
DAY_0, DAY_1, DAY_2, DAY_3 = eng.DAYS

LISTING_OF: Mapping[UUID, UUID7] = {SEC_A: eng.LISTING_A, SEC_B: eng.LISTING_B}

type Sources = Mapping[tuple[UUID, date], tuple[date, ...]]
type Targets = Mapping[date, tuple[tuple[UUID, int], ...]]
type Gap = tuple[UUID, date, tuple[date, ...]]


def _full(days: Sequence[date], cutoff: date) -> tuple[date, ...]:
    """A decision's full history: every clock session through its own."""
    return tuple(days[: list(days).index(cutoff) + 1])


def _history(
    security_id: UUID7, cutoff: date, sources: Sequence[date]
) -> tuple[DerivedObservationViewV1, ...]:
    """Decision views queried at ``cutoff``'s close, one per source session."""
    return tuple(
        eng._decision_view(
            security_id, cutoff, listing_id=LISTING_OF[security_id], source_day=day
        )
        for day in sources
    )


def _bundle(
    sources: Sources | None = None,
    *,
    admit_sec_b: bool = True,
    days: tuple[date, ...] = eng.DAYS,
) -> EvaluationInputBundleV1:
    """Both securities priced on every clock day, each with full history.

    ``sources`` overrides one security's source sessions at one decision
    cutoff; every other decision carries that security's full history. SEC_A
    is always admitted, and SEC_B unless ``admit_sec_b`` is false.
    """
    overrides: Sources = {} if sources is None else sources
    decision = tuple(
        view
        for cutoff in days[1:]
        for security_id in (SEC_A, SEC_B)
        for view in _history(
            security_id,
            cutoff,
            overrides.get((security_id, cutoff), _full(days, cutoff)),
        )
    )
    accounting = tuple(
        eng._accounting_view(security_id, day, listing_id=LISTING_OF[security_id])
        for security_id in (SEC_A, SEC_B)
        for day in days
    )
    return eng._bundle(
        days=days,
        decision_views=decision,
        accounting_views=accounting,
        eligibilities=(
            eng._eligibility(SEC_A, eng.LISTING_A),
            eng._eligibility(
                SEC_B,
                eng.LISTING_B,
                classification=(
                    StructuralEligibilityClassification.ELIGIBLE
                    if admit_sec_b
                    else StructuralEligibilityClassification.INELIGIBLE
                ),
            ),
        ),
    )


def _run_over(
    sources: Sources | None = None,
    targets: Targets | None = None,
    *,
    admit_sec_b: bool = True,
    days: tuple[date, ...] = eng.DAYS,
) -> tuple[EvaluationRunArtifactsV2, eng.FixedTargetStrategy]:
    strategy = eng.FixedTargetStrategy(
        {DAY_2: ((SEC_A, 10),)} if targets is None else targets
    )
    bundle = _bundle(sources, admit_sec_b=admit_sec_b, days=days)
    return eng._run(eng._engine(bundle=bundle), strategy), strategy


def _clause(security_id: UUID, first: date, missing: Sequence[date]) -> str:
    return (
        f"security {security_id} has decision evidence from XNYS "
        f"{first.isoformat()} but no view sourced from "
        + ", ".join(f"XNYS {day.isoformat()}" for day in missing)
    )


def _gap_cause(decided: date, *gapped: Gap) -> str:
    """The issue 141 cause: each security's first view and every missing one."""
    return (
        "incomplete decision context at the realized decision session "
        f"XNYS {decided.isoformat()}: "
        + "; ".join(_clause(*security) for security in gapped)
    )


def _assert_halted_before_asking(
    artifacts: EvaluationRunArtifactsV2,
    strategy: eng.FixedTargetStrategy,
    *,
    index: int,
    cause: str,
    days: tuple[date, ...] = eng.DAYS,
) -> None:
    """The decision at ``index`` halts INDETERMINATE with exactly ``cause``.

    Every earlier decision was asked and traced, this one was not, and
    nothing filled.
    """
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == index
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].session_index == index
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert causes[0].cause_kind == "indeterminate_valuation"
    assert causes[0].cause == cause
    assert artifacts.result.halt_reason == cause
    decided = list(days[1:index])
    assert [context.session_key.local_date for context in strategy.seen] == decided
    assert [
        event.session_key.local_date
        for event in artifacts.trace.events
        if event.kind == "strategy_decision"
    ] == decided
    assert not [event for event in artifacts.trace.events if event.kind == "fill"]
    assert artifacts.final_state.holdings == ()


def _fills(artifacts: EvaluationRunArtifactsV2) -> list[tuple[date, UUID, int]]:
    return [
        (event.session_key.local_date, event.fill.security_id, event.fill.quantity)
        for event in artifacts.trace.events
        if event.kind == "fill"
    ]


def _dates(view: StrategyDecisionViewV1) -> list[date]:
    return [item.source_session.local_date for item in view.views]


def _seen_histories(
    strategy: eng.FixedTargetStrategy,
) -> dict[tuple[date, UUID], list[date]]:
    """Per decision and security, the source dates the context shows."""
    return {
        (context.session_key.local_date, view.security_id): _dates(view)
        for context in strategy.seen
        for view in context.decision_views
    }


# --- a stale security halts the decision --------------------------------------


def test_a_stale_security_is_never_traded_as_current() -> None:
    """The reviewer probe: SEC_A's newest evidence at the 01-07 cutoff is 01-06.

    Before issue 141 the 01-07 context showed SEC_A's history ending 01-06 as
    if it were current, the target filled 10 SEC_A at the 01-08 open, and the
    run was COMPLETE. The decision now halts INDETERMINATE at the 01-07
    close, before the strategy is asked, naming SEC_A, its first viewed
    session and the missing decision session. SEC_B's history holds the
    01-06 bar too, so a guard stopping at the previous session would pass
    both securities and complete.
    """
    artifacts, strategy = _run_over({(SEC_A, DAY_2): (DAY_0, DAY_1)})

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=2,
        cause=_gap_cause(DAY_2, (SEC_A, DAY_0, (DAY_2,))),
    )

    control, seen = _run_over()

    assert control.result.classification is EvaluationClassification.COMPLETE
    assert _fills(control) == [(DAY_3, SEC_A, 10)]
    assert [context.session_key.local_date for context in seen.seen] == [
        DAY_1,
        DAY_2,
        DAY_3,
    ]


def test_a_stale_security_after_the_first_in_canonical_order_halts_too() -> None:
    """SEC_B, second in canonical order, is stale while SEC_A is current.

    The strategy trades only the current SEC_A. The decision still halts,
    because the context it would read is incomplete either way.
    """
    assert SEC_A.bytes < SEC_B.bytes
    artifacts, strategy = _run_over({(SEC_B, DAY_2): (DAY_0, DAY_1)})

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=2,
        cause=_gap_cause(DAY_2, (SEC_B, DAY_0, (DAY_2,))),
    )


def test_every_gapped_security_is_named_in_canonical_order() -> None:
    """Both securities stale: one cause names both, SEC_A first.

    SEC_A's evidence stops at 01-05, so it lacks 01-06 and 01-07, named in
    clock order; SEC_B's stops at 01-06, so it lacks 01-07 alone.
    """
    artifacts, strategy = _run_over(
        {(SEC_A, DAY_2): (DAY_0,), (SEC_B, DAY_2): (DAY_0, DAY_1)}
    )

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=2,
        cause=_gap_cause(
            DAY_2, (SEC_A, DAY_0, (DAY_1, DAY_2)), (SEC_B, DAY_0, (DAY_2,))
        ),
    )


def test_a_stale_security_halts_the_first_decision() -> None:
    """The first decision, at 01-06 under the two-session warmup, is guarded too."""
    artifacts, strategy = _run_over(
        {(SEC_A, DAY_1): (DAY_0,)}, targets={DAY_1: ((SEC_A, 10),)}
    )

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=1,
        cause=_gap_cause(DAY_1, (SEC_A, DAY_0, (DAY_1,))),
    )


def test_a_stale_unadmitted_security_halts_as_well() -> None:
    """A security outside the universe still reaches the strategy's context.

    SEC_B is ineligible, so it is not admitted, but its stale evidence would
    still be read at the 01-07 cutoff. Control: when it is current the same
    run completes and trades SEC_A.
    """
    artifacts, strategy = _run_over({(SEC_B, DAY_2): (DAY_0, DAY_1)}, admit_sec_b=False)

    assert all(context.admitted_universe == (SEC_A,) for context in strategy.seen)
    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=2,
        cause=_gap_cause(DAY_2, (SEC_B, DAY_0, (DAY_2,))),
    )

    control, seen = _run_over(admit_sec_b=False)

    assert control.result.classification is EvaluationClassification.COMPLETE
    assert _fills(control) == [(DAY_3, SEC_A, 10)]
    assert all(context.admitted_universe == (SEC_A,) for context in seen.seen)


def test_a_security_without_evidence_at_the_cutoff_keeps_the_existing_rules() -> None:
    """No evidence is not stale evidence: the security simply has no view.

    SEC_B has no decision evidence at the 01-07 cutoff, so that context holds
    SEC_A alone and the run completes as before.
    """
    artifacts, strategy = _run_over({(SEC_B, DAY_2): ()})

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(DAY_3, SEC_A, 10)]
    at_cutoff = {
        context.session_key.local_date: tuple(
            view.security_id for view in context.decision_views
        )
        for context in strategy.seen
    }
    assert at_cutoff == {DAY_1: (SEC_A, SEC_B), DAY_2: (SEC_A,), DAY_3: (SEC_A, SEC_B)}


# --- a gapped security halts the decision ------------------------------------


@pytest.mark.parametrize("gapped", [SEC_A, SEC_B], ids=["first", "second"])
def test_a_missing_middle_session_halts_the_decision(gapped: UUID) -> None:
    """A current history with a hole two sessions back is not contiguous.

    At the 01-08 cutoff the gapped security holds 01-05, 01-07 and 01-08 but
    not 01-06, so a lookback indexed by position would silently span it.
    The decision halts before the strategy is asked, naming the security,
    first or second in canonical order, and only the missing session. A
    check covering only the latest step between sessions would pass it.
    Control: with 01-06 present the strategy is asked and stages its target.
    """
    targets = {DAY_3: ((SEC_A, 10),)}
    artifacts, strategy = _run_over({(gapped, DAY_3): (DAY_0, DAY_2, DAY_3)}, targets)

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=3,
        cause=_gap_cause(DAY_3, (gapped, DAY_0, (DAY_1,))),
    )

    control, seen = _run_over(targets=targets)

    assert control.result.classification is EvaluationClassification.COMPLETE
    staged = [
        [(item.security_id, item.target_quantity) for item in event.staged_targets]
        for event in control.trace.events
        if event.kind == "strategy_decision" and event.session_index == 3
    ]
    assert staged == [[(SEC_A, 10)]]
    assert _seen_histories(seen)[(DAY_3, gapped)] == list(eng.DAYS)


def test_a_history_starting_after_the_clock_start_is_contiguous() -> None:
    """Contiguity runs from the security's first view, not from the clock start.

    SEC_B's history starts at 01-06 at every decision, and a target for it
    fills at the 01-08 open. Sessions before its first view are not gaps.
    Control: a late starter with a hole still halts, naming its own first
    view, 01-06, not the clock's first session.
    """
    late = {(SEC_B, cutoff): _full(eng.DAYS, cutoff)[1:] for cutoff in eng.DAYS[1:]}
    artifacts, strategy = _run_over(late, targets={DAY_2: ((SEC_B, 10),)})

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(DAY_3, SEC_B, 10)]
    histories = _seen_histories(strategy)
    assert histories[(DAY_1, SEC_B)] == [DAY_1]
    assert histories[(DAY_3, SEC_B)] == [DAY_1, DAY_2, DAY_3]

    holed = dict(late) | {(SEC_B, DAY_3): (DAY_1, DAY_3)}
    halted, asked = _run_over(holed, targets={})

    _assert_halted_before_asking(
        halted,
        asked,
        index=3,
        cause=_gap_cause(DAY_3, (SEC_B, DAY_1, (DAY_2,))),
    )


def test_a_date_the_clock_does_not_step_is_not_a_gap() -> None:
    """Contiguity is over clock sessions, never over calendar dates.

    The clock steps 01-05, 01-06 and 01-08, as it would across a holiday or
    a weekend, so 01-07 is not a session and a history without it is
    contiguous: the run completes and the 01-06 target fills at the 01-08
    open. Counting dates would read 01-07 as missing and halt. Control: a
    history lacking the 01-06 session halts, naming that session alone.
    """
    days = (DAY_0, DAY_1, DAY_3)
    artifacts, strategy = _run_over(targets={DAY_1: ((SEC_A, 10),)}, days=days)

    clock = _bundle(days=days).session_clock
    assert [session.session_key.local_date for session in clock.sessions] == list(days)
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(DAY_3, SEC_A, 10)]
    histories = _seen_histories(strategy)
    assert histories[(DAY_3, SEC_A)] == [DAY_0, DAY_1, DAY_3]
    assert histories[(DAY_3, SEC_B)] == [DAY_0, DAY_1, DAY_3]

    # Control: missing the 01-06 clock session is a gap, named alone.
    halted, asked = _run_over({(SEC_A, DAY_3): (DAY_0, DAY_3)}, targets={}, days=days)

    _assert_halted_before_asking(
        halted,
        asked,
        index=2,
        cause=_gap_cause(DAY_3, (SEC_A, DAY_0, (DAY_1,))),
        days=days,
    )


def test_lookahead_evidence_still_fails_loudly_before_the_stale_halt() -> None:
    """A security whose evidence skips past its decision session is lookahead.

    At the 01-06 cutoff SEC_A holds 01-05 and 01-07 evidence and none from
    01-06. The context's causality guard refuses the 01-07 view loudly; the
    run never reaches the contiguity halt, which would have classified it.
    """
    with pytest.raises(
        ValidationError, match=r"decision evidence sourced after its decision session"
    ):
        _run_over({(SEC_A, DAY_1): (DAY_0, DAY_2)})


# --- the guard itself --------------------------------------------------------


def _key(day: date, mic: str = "XNYS") -> SessionKeyV1:
    return SessionKeyV1(mic=mic, session_scope="regular", local_date=day)


def _group(
    security_id: UUID7, cutoff: date, sources: Sequence[date]
) -> StrategyDecisionViewV1:
    return StrategyDecisionViewV1(
        security_id=security_id, views=_history(security_id, cutoff, sources)
    )


def test_the_guard_names_securities_in_canonical_order_whatever_it_is_handed() -> None:
    """Handed SEC_B's history before SEC_A's, the cause still names SEC_A first."""
    history = (_key(DAY_0), _key(DAY_1), _key(DAY_2))
    handed = (_group(SEC_B, DAY_2, (DAY_0,)), _group(SEC_A, DAY_2, (DAY_0, DAY_2)))

    with pytest.raises(IndeterminateValuationError) as refused:
        _require_contiguous_securities(history, handed)

    assert str(refused.value) == _gap_cause(
        DAY_2, (SEC_A, DAY_0, (DAY_1,)), (SEC_B, DAY_0, (DAY_1, DAY_2))
    )


def test_evidence_from_a_session_outside_the_history_is_refused_loudly() -> None:
    """Defense in depth: a view from a session the clock has not closed.

    The context refuses a later-dated source and the engine refuses a
    same-date multi-venue clock (issue 97), so this cannot reach the guard
    from a run. Handed one anyway, the guard refuses it rather than judge
    the rest of the history, which here is contiguous and current.
    """
    history = (_key(DAY_0), _key(DAY_1), _key(DAY_2))
    handed = (_group(SEC_A, DAY_2, (DAY_1, DAY_2, DAY_3)),)

    with pytest.raises(ValueError) as refused:
        _require_contiguous_securities(history, handed)

    assert type(refused.value) is ValueError
    assert str(refused.value) == (
        f"decision evidence for security {SEC_A} is sourced from a session the "
        "clock has not closed by the decision session XNYS 2026-01-07: "
        "XNYS 2026-01-08"
    )
    # Control: without the 01-08 view the same history passes.
    _require_contiguous_securities(history, (_group(SEC_A, DAY_2, (DAY_1, DAY_2)),))


def _on_venue(
    view: DerivedObservationViewV1, venue: ListingVenue
) -> DerivedObservationViewV1:
    """The same view sourced from another venue's session on the same date."""
    observation = view.query.observation.model_copy(update={"venue": venue})
    query = NormalizationQueryV1.model_construct(
        **(dict(view.query) | {"observation": observation})
    )
    draft = DerivedObservationViewV1.model_construct(
        **(
            dict(view)
            | {
                "query": query,
                "query_hash": content_hash(query),
                "source_session": view.source_session.model_copy(
                    update={"mic": venue.value}
                ),
            }
        )
    )
    sealed = DerivedObservationViewV1.model_construct(
        **(dict(draft) | {"output_hash": derived_view_output_hash(draft)})
    )
    return DerivedObservationViewV1.model_validate(dict(sealed))


def test_a_same_date_view_from_another_venue_is_not_the_decision_session() -> None:
    """A session is a venue, a scope and a date, never a date alone.

    The history holds an XNAS 01-07 session closed before the XNYS 01-07
    decision session (a shape the engine refuses at construction, issue 97,
    so this is defense in depth). SEC_A's only view is from XNAS, so it
    lacks the decision session. Control: with its XNYS view as well, the
    history is contiguous and current.
    """
    xnys = eng._decision_view(SEC_A, DAY_2)
    xnas = _on_venue(xnys, ListingVenue.XNAS)
    assert xnas.source_session == _key(DAY_2, "XNAS")
    history = (_key(DAY_2, "XNAS"), _key(DAY_2))

    with pytest.raises(IndeterminateValuationError) as refused:
        _require_contiguous_securities(
            history, (StrategyDecisionViewV1(security_id=SEC_A, views=(xnas,)),)
        )

    assert str(refused.value) == (
        "incomplete decision context at the realized decision session XNYS "
        f"2026-01-07: security {SEC_A} has decision evidence from XNAS "
        "2026-01-07 but no view sourced from XNYS 2026-01-07"
    )
    _require_contiguous_securities(
        history, (StrategyDecisionViewV1(security_id=SEC_A, views=(xnas, xnys)),)
    )


# --- history is held in source-session order ----------------------------------


def test_the_engine_hands_each_history_in_source_session_order() -> None:
    """Every security's history reaches the strategy oldest first.

    The views arrive in the bundle's content-hash order. At least one
    history here has a hash order other than its date order, so a context
    built in hash order fails.
    """
    control, strategy = _run_over()

    assert control.result.classification is EvaluationClassification.COMPLETE
    groups = [view for context in strategy.seen for view in context.decision_views]
    assert len(groups) == 6
    for group in groups:
        assert _dates(group) == sorted(_dates(group))
        assert len(set(_dates(group))) == len(group.views)
    assert any(
        [
            item.source_session.local_date
            for item in sorted(group.views, key=content_hash)
        ]
        != _dates(group)
        for group in groups
    )
    at_cutoff = _seen_histories(strategy)
    assert at_cutoff[(DAY_2, SEC_A)] == [DAY_0, DAY_1, DAY_2]
    assert at_cutoff[(DAY_3, SEC_B)] == [DAY_0, DAY_1, DAY_2, DAY_3]


def _hash_disordered_history() -> tuple[
    UUID7, list[date], tuple[DerivedObservationViewV1, ...]
]:
    """A full history whose content-hash order is not its date order.

    The first such history in a fixed family: SEC_A then SEC_B, at the 01-08
    and then the 01-07 cutoff. Returns the security, its dates in session
    order, and its views in hash order.
    """
    for cutoff in (DAY_3, DAY_2):
        for security_id in (SEC_A, SEC_B):
            dates = list(_full(eng.DAYS, cutoff))
            views = tuple(
                sorted(_history(security_id, cutoff, dates), key=content_hash)
            )
            if [view.source_session.local_date for view in views] != dates:
                return security_id, dates, views
    raise AssertionError("every history in the family is already in hash order")


def test_a_decision_view_holds_its_history_in_source_session_order() -> None:
    """Model canonicalization orders by source session, whatever the input order."""
    security_id, dates, views = _hash_disordered_history()

    for order in itertools.permutations(views):
        built = StrategyDecisionViewV1(security_id=security_id, views=order)
        assert _dates(built) == dates
    # A document listing the views in hash order validates into date order.
    document = StrategyDecisionViewV1.model_construct(
        security_id=security_id, views=views
    ).model_dump_json()
    parsed = StrategyDecisionViewV1.model_validate_json(document)
    assert _dates(parsed) == dates


def test_a_decision_context_rebuilt_from_json_keeps_source_session_order() -> None:
    """The copy handed to a strategy is rebuilt through JSON, and keeps the order."""
    security_id, dates, views = _hash_disordered_history()
    session = eng._session(dates[-1])
    context = StrategyDecisionContextV1(
        session_key=session.session_key,
        decision_session=session,
        decision_cutoff=session.closed_at,
        admitted_universe=(security_id,),
        current_holdings=(),
        current_cash=Decimal("10000.00"),
        portfolio_nav=Decimal("10000.00"),
        decision_views=(StrategyDecisionViewV1(security_id=security_id, views=views),),
    )

    rebuilt = StrategyDecisionContextV1.model_validate_json(context.model_dump_json())

    assert _dates(rebuilt.decision_views[0]) == dates
    assert content_hash(rebuilt) == content_hash(context)


def test_views_of_one_session_are_ordered_by_content_hash() -> None:
    """Two views of the 01-07 bar tie on the session; the content hash breaks it."""
    earlier = eng._decision_view(SEC_A, DAY_2, source_day=DAY_1)
    tied = (
        eng._decision_view(SEC_A, DAY_2),
        eng._decision_view(SEC_A, DAY_2, listing_id=eng.LISTING_B),
    )
    assert tied[0].source_session == tied[1].source_session
    expected = (earlier, *sorted(tied, key=content_hash))

    for order in itertools.permutations((earlier, *tied)):
        built = StrategyDecisionViewV1(security_id=SEC_A, views=order)
        assert built.views == expected


def test_views_of_one_date_on_two_venues_are_ordered_by_venue() -> None:
    """The session key orders by date, then venue, before any content hash.

    The pair is the first in a fixed family whose XNYS view hashes below its
    XNAS twin, so ordering by hash would put XNYS first.
    """
    pairs = (
        (xnys, _on_venue(xnys, ListingVenue.XNAS))
        for xnys in (
            eng._decision_view(security_id, cutoff, listing_id=LISTING_OF[security_id])
            for cutoff in eng.DAYS
            for security_id in (SEC_A, SEC_B)
        )
    )
    pair = next(
        (pair for pair in pairs if content_hash(pair[0]) < content_hash(pair[1])),
        None,
    )
    assert pair is not None, "no pair in the family hashes XNYS first"
    xnys, xnas = pair

    for order in ((xnys, xnas), (xnas, xnys)):
        built = StrategyDecisionViewV1(security_id=xnys.security_id, views=order)
        assert [item.source_session.mic for item in built.views] == ["XNAS", "XNYS"]
