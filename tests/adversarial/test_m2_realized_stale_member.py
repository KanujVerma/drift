"""M2 adversarial acceptance: a stale security is never read as current (issue 141).

Finding FA1 F3 of the M2 final acceptance rerun, owner ruling A. The issue 87
ruling closed the stale-as-current hazard for the reconstructed lane only. In
the realized lane a security whose newest decision evidence was older than
the session being decided still reached the strategy as though it were
current, and a target for it filled at the next open: the reviewer probe, a
2026-01-07 decision where SEC_A's newest evidence is its 01-06 bar while
SEC_B is current, ended COMPLETE with SEC_A's history in content-hash order
(01-06 before 01-05) and a fill of 10 SEC_A at the 01-08 open.

Two rules now hold, each proven here against a control:

* A security with decision evidence at the cutoff but no view sourced from
  the decision session halts the decision INDETERMINATE, before the strategy
  is asked, naming the session and every such security in canonical order.
* Each security's history is held in source-session order, with a content
  hash tie-break between views of one session, whatever order the views
  arrive in.

Every ``pytest.raises`` and every cause assertion names text unique to the
guard under attack, so another guard firing first fails the test.
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
from drift.domain.observation_query import ObservationDecisionQueryV1
from drift.domain.securities import ListingVenue
from drift.domain.universes import StructuralEligibilityClassification
from drift.serialization.canonical import content_hash

SEC_A = eng.SEC_A
SEC_B = eng.SEC_B
DAY_0, DAY_1, DAY_2, DAY_3 = eng.DAYS

LISTING_OF: Mapping[UUID, UUID7] = {SEC_A: eng.LISTING_A, SEC_B: eng.LISTING_B}

#: Each decision's full history: every clock session through its own.
FULL_HISTORY: Mapping[date, tuple[date, ...]] = {
    day: eng.DAYS[: index + 1] for index, day in enumerate(eng.DAYS)
}

type Sources = Mapping[tuple[UUID, date], tuple[date, ...]]


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
    sources: Sources | None = None, *, admit_sec_b: bool = True
) -> EvaluationInputBundleV1:
    """Both securities priced on every day, each with full history.

    ``sources`` overrides one security's source sessions at one decision
    cutoff; every other decision carries that security's full history. SEC_A
    is always admitted, and SEC_B unless ``admit_sec_b`` is false.
    """
    overrides: Sources = {} if sources is None else sources
    decision = tuple(
        view
        for cutoff in eng.DAYS[1:]
        for security_id in (SEC_A, SEC_B)
        for view in _history(
            security_id,
            cutoff,
            overrides.get((security_id, cutoff), FULL_HISTORY[cutoff]),
        )
    )
    accounting = tuple(
        eng._accounting_view(security_id, day, listing_id=LISTING_OF[security_id])
        for security_id in (SEC_A, SEC_B)
        for day in eng.DAYS
    )
    return eng._bundle(
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
    targets: Mapping[date, tuple[tuple[UUID, int], ...]] | None = None,
    *,
    admit_sec_b: bool = True,
) -> tuple[EvaluationRunArtifactsV2, eng.FixedTargetStrategy]:
    strategy = eng.FixedTargetStrategy(
        {DAY_2: ((SEC_A, 10),)} if targets is None else targets
    )
    bundle = _bundle(sources, admit_sec_b=admit_sec_b)
    return eng._run(eng._engine(bundle=bundle), strategy), strategy


def _stale_cause(decided: date, *stale: tuple[UUID, date]) -> str:
    """The issue 141 cause: each stale security with its newest session."""
    clauses = "; ".join(
        f"security {security_id} has decision evidence through XNYS "
        f"{through.isoformat()} but no view sourced from XNYS {decided.isoformat()}"
        for security_id, through in stale
    )
    return (
        "incomplete decision context at the realized decision session "
        f"XNYS {decided.isoformat()}: {clauses}"
    )


def _assert_halted_before_asking(
    artifacts: EvaluationRunArtifactsV2,
    strategy: eng.FixedTargetStrategy,
    *,
    index: int,
    cause: str,
) -> None:
    """The decision at ``index`` halts INDETERMINATE with exactly ``cause``."""
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
    decided = [eng.DAYS[position] for position in range(1, index)]
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


# --- a stale security halts the decision --------------------------------------


def test_a_stale_security_is_never_traded_as_current() -> None:
    """The reviewer probe: SEC_A's newest evidence at the 01-07 cutoff is 01-06.

    Before issue 141 the 01-07 context showed SEC_A's history ending 01-06 as
    if it were current, the target filled 10 SEC_A at the 01-08 open, and the
    run was COMPLETE. The decision now halts INDETERMINATE at the 01-07
    close, before the strategy is asked, naming SEC_A and the session.
    SEC_B's history holds the 01-06 bar too, so a guard reading the previous
    session as current would pass both securities and complete.
    """
    artifacts, strategy = _run_over({(SEC_A, DAY_2): (DAY_0, DAY_1)})

    _assert_halted_before_asking(
        artifacts, strategy, index=2, cause=_stale_cause(DAY_2, (SEC_A, DAY_1))
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
        artifacts, strategy, index=2, cause=_stale_cause(DAY_2, (SEC_B, DAY_1))
    )


def test_every_stale_security_is_named_in_canonical_order() -> None:
    """Both securities stale: one cause names both, SEC_A first.

    SEC_A's evidence stops at 01-05 and SEC_B's at 01-06, so each clause
    names that security's own newest session. The bundle holds SEC_B's
    01-07-cutoff evidence before SEC_A's, so naming securities in bundle
    order would put SEC_B first.
    """
    sources = {(SEC_A, DAY_2): (DAY_0,), (SEC_B, DAY_2): (DAY_0, DAY_1)}
    cutoff = eng._close_of(DAY_2)
    at_cutoff = [
        view.security_id
        for view in _bundle(sources).authentic_decision_views
        if isinstance(view.query.observation, ObservationDecisionQueryV1)
        and view.query.observation.decision_time == cutoff
    ]
    assert at_cutoff[0] == SEC_B
    artifacts, strategy = _run_over(sources)

    _assert_halted_before_asking(
        artifacts,
        strategy,
        index=2,
        cause=_stale_cause(DAY_2, (SEC_A, DAY_0), (SEC_B, DAY_1)),
    )


def test_a_stale_security_halts_the_first_decision() -> None:
    """The first decision, at 01-06 under the two-session warmup, is guarded too."""
    artifacts, strategy = _run_over(
        {(SEC_A, DAY_1): (DAY_0,)}, targets={DAY_1: ((SEC_A, 10),)}
    )

    _assert_halted_before_asking(
        artifacts, strategy, index=1, cause=_stale_cause(DAY_1, (SEC_A, DAY_0))
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
        artifacts, strategy, index=2, cause=_stale_cause(DAY_2, (SEC_B, DAY_1))
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


def test_lookahead_evidence_still_fails_loudly_before_the_stale_halt() -> None:
    """A security whose evidence skips past its decision session is lookahead.

    At the 01-06 cutoff SEC_A holds 01-05 and 01-07 evidence and none from
    01-06. The context's causality guard refuses the 01-07 view loudly; the
    run never reaches the stale halt, which would have classified it.
    """
    with pytest.raises(
        ValidationError, match=r"decision evidence sourced after its decision session"
    ):
        _run_over({(SEC_A, DAY_1): (DAY_0, DAY_2)})


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
    """The decision session is a venue, a scope and a date, not a date alone."""
    from drift.evaluator.engine import _require_current_securities

    xnys = eng._decision_view(SEC_A, DAY_2)
    xnas = _on_venue(xnys, ListingVenue.XNAS)
    assert xnas.source_session.local_date == DAY_2
    assert xnas.source_session.mic == "XNAS"
    decided = eng._session(DAY_2)

    with pytest.raises(IndeterminateValuationError) as refused:
        _require_current_securities(
            decided, (StrategyDecisionViewV1(security_id=SEC_A, views=(xnas,)),)
        )

    assert str(refused.value) == (
        "incomplete decision context at the realized decision session XNYS "
        f"2026-01-07: security {SEC_A} has decision evidence through XNAS "
        "2026-01-07 but no view sourced from XNYS 2026-01-07"
    )
    # Control: with the decision session's own view present, it is current.
    _require_current_securities(
        decided, (StrategyDecisionViewV1(security_id=SEC_A, views=(xnas, xnys)),)
    )


# --- history is held in source-session order ----------------------------------


def _dates(view: StrategyDecisionViewV1) -> list[date]:
    return [item.source_session.local_date for item in view.views]


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
    at_cutoff = {
        (context.session_key.local_date, view.security_id): _dates(view)
        for context in strategy.seen
        for view in context.decision_views
    }
    assert at_cutoff[(DAY_2, SEC_A)] == [DAY_0, DAY_1, DAY_2]
    assert at_cutoff[(DAY_3, SEC_B)] == [DAY_0, DAY_1, DAY_2, DAY_3]


def _hash_disordered_history() -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A's full 01-08 history, in content-hash order that is not date order."""
    views = tuple(sorted(_history(SEC_A, DAY_3, FULL_HISTORY[DAY_3]), key=content_hash))
    assert [view.source_session.local_date for view in views] != list(eng.DAYS)
    return views


def test_a_decision_view_holds_its_history_in_source_session_order() -> None:
    """Model canonicalization orders by source session, whatever the input order."""
    views = _hash_disordered_history()

    for order in itertools.permutations(views):
        built = StrategyDecisionViewV1(security_id=SEC_A, views=order)
        assert _dates(built) == list(eng.DAYS)
    # A document listing the views in hash order validates into date order.
    document = StrategyDecisionViewV1.model_construct(
        security_id=SEC_A, views=views
    ).model_dump_json()
    parsed = StrategyDecisionViewV1.model_validate_json(document)
    assert _dates(parsed) == list(eng.DAYS)


def test_a_decision_context_rebuilt_from_json_keeps_source_session_order() -> None:
    """The copy handed to a strategy is rebuilt through JSON, and keeps the order."""
    session = eng._session(DAY_3)
    context = StrategyDecisionContextV1(
        session_key=session.session_key,
        decision_session=session,
        decision_cutoff=session.closed_at,
        admitted_universe=(SEC_A,),
        current_holdings=(),
        current_cash=Decimal("10000.00"),
        portfolio_nav=Decimal("10000.00"),
        decision_views=(
            StrategyDecisionViewV1(security_id=SEC_A, views=_hash_disordered_history()),
        ),
    )

    rebuilt = StrategyDecisionContextV1.model_validate_json(context.model_dump_json())

    assert _dates(rebuilt.decision_views[0]) == list(eng.DAYS)
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
    """The session key orders by date, then venue, before any content hash."""
    xnys = eng._decision_view(SEC_A, DAY_2)
    xnas = _on_venue(xnys, ListingVenue.XNAS)
    assert content_hash(xnys) < content_hash(xnas)

    for order in ((xnys, xnas), (xnas, xnys)):
        built = StrategyDecisionViewV1(security_id=SEC_A, views=order)
        assert [item.source_session.mic for item in built.views] == ["XNAS", "XNYS"]
