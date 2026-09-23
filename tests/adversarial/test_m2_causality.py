"""M2 adversarial acceptance: causality, universe, clock authority, provider boundary.

Every test here is an attack. The question each one asks is not "does the
happy path work" but "can the invariant be violated by evidence that is
individually well formed". Fixtures are reused from the Task 6 engine unit
tests so that the attacks run against the same corpus the implementation was
built on, rather than against a weaker corpus invented here.

Two habits are deliberate. First, several tests assert a control alongside the
attack: the same setup with the offending property removed must behave
differently, so the assertion cannot pass vacuously. Second, every
``pytest.raises`` pattern names text unique to the guard under attack, so a
different guard firing first fails the test instead of satisfying it.
"""

# ruff: noqa: E402

import ast
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    SEC,
    ReconstructedTargetStrategy,
    early_close_sessions,
    reconstructed_engine,
    run_engine,
    scheduled_bundle,
    three_regular_sessions,
    utc_close,
)
from observation_test_support import NormalizationHarness
from pydantic import ValidationError
from session_test_support import boundary_at, revision
from test_evaluator_bundles import _harness, _queries, _scheduled_bundle
from test_evaluator_engine import (
    BOOK_CODE,
    BOOK_NAMESPACE,
    DAY_0,
    DAY_1,
    DAY_2,
    DAY_3,
    DAYS,
    LISTING_A,
    LISTING_B,
    LISTINGS,
    ROLE_RECORDS,
    SEC_A,
    SEC_B,
    SECURITIES,
    FixedTargetStrategy,
    _accounting_view,
    _buy_ten,
    _close_of,
    _cost_model,
    _decision_view,
    _eligibility,
    _engine,
    _interval,
    _protocol,
    _restated_view,
    _role_record,
    _run,
    _template_view,
)

from drift.domain.assertions import ResolutionMode, TemporalIntervalClaimV1
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    evaluation_input_bundle_hash,
)
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_execution import IndeterminateExecutionError
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyIntentRejectedError,
    stage_decision_targets,
)
from drift.domain.evaluator_trace import EvaluationPhase
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationDecisionQueryV1
from drift.domain.securities import (
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingRole,
    ListingRoleVersionV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.universes import (
    StructuralEligibilityClassification,
    StructuralEligibilityResultV1,
)
from drift.evaluator.bundles import assemble_evaluation_input_bundle
from drift.evaluator.clock import build_realized_session_clock
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    reconstructed_history_sessions,
    require_next_open_execution,
)
from drift.evaluator.execution import resolve_execution_listing
from drift.serialization.canonical import content_hash

REGULAR_OPEN = time(14, 30)
REGULAR_CLOSE = time(21, 0)
EARLY_CLOSE = time(18, 0)

HASH_ONE = "1" * 64
HASH_TWO = "2" * 64
HASH_ZERO = "0" * 64

#: Every module whose imports define the evaluator's provider boundary.
CORE_PACKAGE_PREFIXES = (
    "drift.domain.",
    "drift.evaluator.",
    "drift.markets.",
    "drift.serialization.",
    "drift.ledger.",
    "drift.errors",
)


# --- local clock and bundle builders ------------------------------------


def _session_at(
    day: date,
    *,
    closes_at: time = REGULAR_CLOSE,
    authority: Literal["realized", "scheduled_reconstruction"] = "realized",
) -> EvaluationSessionV1:
    """One evaluation session with an exact boundary and a named authority."""
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day),
        opened_at=datetime.combine(day, REGULAR_OPEN, tzinfo=UTC),
        closed_at=datetime.combine(day, closes_at, tzinfo=UTC),
        authority=authority,
        authority_record_hashes=(HASH_ONE,),
        authority_proof_hashes=(HASH_TWO,),
        session_hash=HASH_ZERO,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _resealed(session: EvaluationSessionV1, **update: object) -> EvaluationSessionV1:
    """One session edited and re-hashed, so only a semantic guard can refuse it."""
    draft = EvaluationSessionV1.model_construct(**(dict(session) | update))
    return EvaluationSessionV1.model_validate(
        dict(draft) | {"session_hash": evaluation_session_hash(draft)}
    )


def _xnas_session(day: date, opens_at: time, closes_at: time) -> EvaluationSessionV1:
    """A second venue's realized session on one local date."""
    return _resealed(
        _session_at(day),
        session_key=SessionKeyV1(mic="XNAS", session_scope="regular", local_date=day),
        opened_at=datetime.combine(day, opens_at, tzinfo=UTC),
        closed_at=datetime.combine(day, closes_at, tzinfo=UTC),
    )


def _clock_of(
    sessions: Sequence[EvaluationSessionV1],
    *,
    mode: str = "realized_session_authority",
    limitations: Sequence[str] = (),
) -> SessionClockV1:
    """Assemble a clock without letting a draft self-validate before its hash."""
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=mode,
        sessions=tuple(sessions),
        acknowledged_limitations=tuple(sorted(limitations)),
        clock_hash=HASH_ZERO,
    )
    candidate = SessionClockV1.model_construct(
        **(dict(draft) | {"clock_hash": session_clock_hash(draft)})
    )
    return SessionClockV1.model_validate(candidate.model_dump())


def _bundle_over(
    *,
    clock: SessionClockV1,
    decision_views: tuple[DerivedObservationViewV1, ...],
    accounting_views: tuple[DerivedObservationViewV1, ...],
    eligibilities: tuple[StructuralEligibilityResultV1, ...] | None = None,
) -> Any:
    """A bundle bound to an explicitly supplied clock."""
    universe = (
        (_eligibility(SEC_A, LISTING_A),) if eligibilities is None else eligibilities
    )
    return assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=clock,
        security_identities=SECURITIES,
        listing_identities=LISTINGS,
        structural_eligibilities=universe,
        economic_outcomes=(),
        authentic_decision_views=decision_views,
        authentic_accounting_views=accounting_views,
    )


def _leaky_observation(
    day: date,
    *,
    knowledge_cutoff: datetime | None = None,
    effective_cutoff: datetime | None = None,
) -> ObservationDecisionQueryV1:
    """A decision query answered at the cutoff whose own clocks outrun it.

    Built through ``model_construct`` on purpose. The M1d query contract
    already refuses this shape, so the only way to reach the M2 context guard
    with it is to forge a query that never passed M1d validation. That is
    exactly the adversary worth modelling: the second line of defence has to
    hold on its own.
    """
    cutoff = _close_of(day)
    base = dict(_template_view().query.observation)
    return ObservationDecisionQueryV1.model_construct(
        **(
            base
            | {
                "security_id": SEC_A,
                "listing_id": LISTING_A,
                "session_date": day,
                "decision_time": cutoff,
                "knowledge_cutoff": (
                    cutoff if knowledge_cutoff is None else knowledge_cutoff
                ),
                "effective_cutoff": (
                    cutoff if effective_cutoff is None else effective_cutoff
                ),
            }
        )
    )


def _leaky_decision_view(
    day: date,
    *,
    knowledge_cutoff: datetime | None = None,
    effective_cutoff: datetime | None = None,
) -> DerivedObservationViewV1:
    """A decision view carrying a forged, acausal decision query."""
    return _restated_view(
        role="decision",
        observation=_leaky_observation(
            day,
            knowledge_cutoff=knowledge_cutoff,
            effective_cutoff=effective_cutoff,
        ),
        security_id=SEC_A,
        listing_id=LISTING_A,
        source_day=day,
        open_price="100.00",
        close_price="100.00",
    )


def _poisoned_decision_bundle(leaked: DerivedObservationViewV1) -> Any:
    """A bundle carrying a forged decision view, assembled past validation."""
    base = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=(_decision_view(SEC_A, DAY_2), _decision_view(SEC_A, DAY_3)),
        accounting_views=_default_accounting_views(),
    )
    views = tuple(
        view
        for _, view in sorted(
            (
                (content_hash(item), item)
                for item in (leaked, *base.authentic_decision_views)
            ),
            key=lambda pair: pair[0],
        )
    )
    draft = EvaluationInputBundleV1.model_construct(
        **(dict(base) | {"authentic_decision_views": views})
    )
    return EvaluationInputBundleV1.model_construct(
        **(dict(draft) | {"bundle_hash": evaluation_input_bundle_hash(draft)})
    )


def _default_decision_views() -> tuple[DerivedObservationViewV1, ...]:
    return tuple(_decision_view(SEC_A, day) for day in DAYS[1:])


def _default_accounting_views() -> tuple[DerivedObservationViewV1, ...]:
    return tuple(_accounting_view(SEC_A, day) for day in DAYS)


# ==========================================================================
# Causality
# ==========================================================================


def test_a_staged_decision_never_executes_inside_its_own_session() -> None:
    """Same-bar close lookahead: phase order must forbid same-session execution."""
    artifacts = _run(_engine())

    staged = [
        event
        for event in artifacts.trace.events
        if event.kind == "strategy_decision" and event.outcome == "staged"
    ]
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert staged, "the fixture must stage at least one decision"
    assert fills, "the fixture must commit at least one fill"
    first_staged = min(event.session_index for event in staged)
    for fill in fills:
        assert fill.session_index > first_staged


def test_a_next_open_fill_uses_neither_close_available_at_the_decision() -> None:
    """The fill price must be the execution open, not any close it could see."""
    views = (
        _accounting_view(SEC_A, DAY_0),
        _accounting_view(SEC_A, DAY_1, open_price="100.00", close_price="100.00"),
        _accounting_view(SEC_A, DAY_2, open_price="200.00", close_price="111.00"),
        _accounting_view(SEC_A, DAY_3, open_price="111.00", close_price="120.00"),
    )
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=_default_decision_views(),
        accounting_views=views,
    )

    artifacts = _run(_engine(bundle=bundle))

    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].session_index == 2
    fill = fills[0].fill
    assert fill.unadjusted_open_price == Decimal("200.00")
    # The decision session close and the execution session close are both
    # visible numbers that a lookahead would have used. Neither may appear.
    assert fill.unadjusted_open_price != Decimal("100.00")
    assert fill.unadjusted_open_price != Decimal("111.00")


def test_a_final_session_decision_is_never_executed() -> None:
    """There is no session after the last one, so its intent cannot fill."""
    strategy = FixedTargetStrategy(
        {DAY_1: ((SEC_A, 10),), DAY_2: ((SEC_A, 10),), DAY_3: ((SEC_A, 40),)}
    )

    artifacts = _run(_engine(), strategy)

    staged = [
        event
        for event in artifacts.trace.events
        if event.kind == "strategy_decision" and event.outcome == "staged"
    ]
    assert max(event.session_index for event in staged) == 3
    assert artifacts.result.metrics.committed_fill_count == 1
    assert [
        (holding.security_id, holding.quantity)
        for holding in artifacts.final_state.holdings
    ] == [(SEC_A, 10)]


def test_the_m1d_query_contract_refuses_a_post_cutoff_knowledge_clock() -> None:
    """First line of defence: an acausal decision query is not constructible."""
    forged = _leaky_observation(DAY_1, knowledge_cutoff=_close_of(DAY_2))

    with pytest.raises(
        ValidationError, match=r"knowledge cutoff cannot follow decision time"
    ):
        ObservationDecisionQueryV1.model_validate(dict(forged))


def test_the_m1d_query_contract_refuses_a_post_cutoff_effective_clock() -> None:
    forged = _leaky_observation(DAY_1, effective_cutoff=_close_of(DAY_2))

    with pytest.raises(
        ValidationError, match=r"effective cutoff cannot follow decision time"
    ):
        ObservationDecisionQueryV1.model_validate(dict(forged))


def test_a_bundle_refuses_a_forged_acausal_decision_view() -> None:
    """Second line of defence: bundle assembly revalidates every nested query."""
    leaked = _leaky_decision_view(DAY_1, knowledge_cutoff=_close_of(DAY_2))

    with pytest.raises(
        ValidationError, match=r"knowledge cutoff cannot follow decision time"
    ):
        _bundle_over(
            clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
            decision_views=(
                leaked,
                _decision_view(SEC_A, DAY_2),
                _decision_view(SEC_A, DAY_3),
            ),
            accounting_views=_default_accounting_views(),
        )


def test_a_post_cutoff_knowledge_clock_on_decision_evidence_fails_loudly() -> None:
    """Third line of defence: the strategy boundary rechecks the clocks itself.

    Reaching this guard requires a bundle that never passed validation, so the
    bundle is built with ``model_construct``. Post-cutoff leakage must fail
    loudly here rather than being silently filtered into a COMPLETE run.
    """
    bundle = _poisoned_decision_bundle(
        _leaky_decision_view(DAY_1, knowledge_cutoff=_close_of(DAY_2))
    )

    with pytest.raises(
        ValidationError,
        match=r"decision evidence knowledge cutoff follows its decision cutoff",
    ):
        _run(_engine(bundle=bundle))


def test_a_post_cutoff_effective_clock_on_decision_evidence_fails_loudly() -> None:
    bundle = _poisoned_decision_bundle(
        _leaky_decision_view(DAY_1, effective_cutoff=_close_of(DAY_2))
    )

    with pytest.raises(
        ValidationError,
        match=r"decision evidence effective cutoff follows its decision cutoff",
    ):
        _run(_engine(bundle=bundle))


def test_a_decision_view_sourced_after_its_decision_session_fails_loudly() -> None:
    """A later source session reaching an earlier decision is plain lookahead."""
    ahead = _decision_view(SEC_A, DAY_1, source_day=DAY_2)
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=(
            ahead,
            _decision_view(SEC_A, DAY_2),
            _decision_view(SEC_A, DAY_3),
        ),
        accounting_views=_default_accounting_views(),
    )

    with pytest.raises(
        ValidationError,
        match=r"decision evidence sourced after its decision session",
    ):
        _run(_engine(bundle=bundle))


def test_an_early_close_session_decides_at_its_own_close() -> None:
    """A 13:00 local close decides at 13:00, never at the regular 16:00."""
    clock = _clock_of(
        (
            _session_at(DAY_0),
            _session_at(DAY_1),
            _session_at(DAY_2, closes_at=EARLY_CLOSE),
            _session_at(DAY_3),
        )
    )
    early_cutoff = datetime.combine(DAY_2, EARLY_CLOSE, tzinfo=UTC)
    bundle = _bundle_over(
        clock=clock,
        decision_views=(
            _decision_view(SEC_A, DAY_1),
            _decision_view(SEC_A, DAY_2, decision_cutoff=early_cutoff),
            _decision_view(SEC_A, DAY_3),
        ),
        accounting_views=_default_accounting_views(),
    )
    strategy = _buy_ten()

    _run(_engine(bundle=bundle), strategy)

    seen = {context.session_key.local_date: context for context in strategy.seen}
    assert seen[DAY_2].decision_cutoff == early_cutoff
    assert seen[DAY_2].decision_cutoff != _close_of(DAY_2)
    assert seen[DAY_1].decision_cutoff == _close_of(DAY_1)


def test_an_early_close_session_refuses_regular_close_evidence() -> None:
    """Evidence answered at 16:00 cannot serve a decision taken at 13:00."""
    clock = _clock_of(
        (
            _session_at(DAY_0),
            _session_at(DAY_1),
            _session_at(DAY_2, closes_at=EARLY_CLOSE),
            _session_at(DAY_3),
        )
    )
    bundle = _bundle_over(
        clock=clock,
        decision_views=(
            _decision_view(SEC_A, DAY_1),
            _decision_view(SEC_A, DAY_2),
            _decision_view(SEC_A, DAY_3),
        ),
        accounting_views=_default_accounting_views(),
    )

    artifacts = _run(_engine(bundle=bundle))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert "no authorized decision evidence for the decision cutoff" in causes[0].cause


def test_a_future_corporate_action_cannot_perturb_earlier_sessions() -> None:
    """Knowledge of a later action must leave every earlier session bit-identical."""
    from test_evaluator_engine import _admission, _bundle, _forward_split_outcome

    outcome = _forward_split_outcome("2026-01-08T00:00:00Z")
    views = (
        _accounting_view(SEC_A, DAY_0),
        _accounting_view(SEC_A, DAY_1),
        _accounting_view(SEC_A, DAY_2),
        _accounting_view(SEC_A, DAY_3, open_price="55.00", close_price="60.00"),
    )
    with_action_bundle = _bundle(
        accounting_views=views, economic_outcomes=(outcome.resolution,)
    )
    with_action = SessionEvaluatorEngine(
        bundle=with_action_bundle,
        admission=_admission(with_action_bundle),
        protocol=_protocol(),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=ROLE_RECORDS, economic_outcomes=(outcome,)
        ),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )
    without_action = _engine(bundle=_bundle(accounting_views=views))

    known = _run(with_action)
    unknown = _run(without_action)

    def prefix(artifacts: Any) -> list[Any]:
        return [
            event.model_dump(mode="python")
            for event in artifacts.trace.events
            if event.session_index < 3
        ]

    assert prefix(known) == prefix(unknown)
    # Control: the action is real and does change the final session.
    assert known.trace.trace_hash != unknown.trace.trace_hash
    applied = [
        event
        for event in known.trace.events
        if event.kind == "corporate_action_applied"
    ]
    assert [event.session_index for event in applied] == [3]


# ==========================================================================
# Universe
# ==========================================================================


def test_a_current_interpretation_universe_cannot_authorize_a_position() -> None:
    """An ex-post universe reading must reject the trade, not merely be filtered."""
    ex_post = _eligibility(
        SEC_B, LISTING_B, resolution_mode=ResolutionMode.CURRENT_INTERPRETATION
    )
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=_default_decision_views(),
        accounting_views=_default_accounting_views(),
        eligibilities=(_eligibility(SEC_A, LISTING_A), ex_post),
    )
    assert ex_post.classification is StructuralEligibilityClassification.ELIGIBLE, (
        "the attack requires an otherwise eligible result"
    )
    strategy = FixedTargetStrategy({DAY_1: ((SEC_B, 1),)})

    artifacts = _run(_engine(bundle=bundle), strategy)

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halt_reason is not None
    assert "a positive target requires an admitted security" in (
        artifacts.result.halt_reason
    )


def test_a_survivorship_universe_admits_nothing_at_earlier_decisions() -> None:
    """Today's active list cannot define what a past decision was allowed to hold."""
    survivorship = _eligibility(SEC_A, LISTING_A, knowledge_cutoff=_close_of(DAY_3))
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=_default_decision_views(),
        accounting_views=_default_accounting_views(),
        eligibilities=(survivorship,),
    )
    engine = _engine(bundle=bundle)
    sessions = bundle.session_clock.sessions

    assert engine.admitted_universe_at(sessions[0]) == ()
    assert engine.admitted_universe_at(sessions[1]) == ()
    assert engine.admitted_universe_at(sessions[2]) == ()
    # Control: the result is a genuine admission once its own cutoff is reached.
    assert engine.admitted_universe_at(sessions[3]) == (SEC_A,)


def test_an_indeterminate_membership_is_not_an_admission() -> None:
    undecided = _eligibility(
        SEC_B,
        LISTING_B,
        classification=StructuralEligibilityClassification.INDETERMINATE,
    )
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=_default_decision_views(),
        accounting_views=_default_accounting_views(),
        eligibilities=(_eligibility(SEC_A, LISTING_A), undecided),
    )
    engine = _engine(bundle=bundle)
    strategy = FixedTargetStrategy({DAY_1: ((SEC_B, 1),)})

    artifacts = _run(engine, strategy)

    assert SEC_B not in engine.admitted_universe_at(bundle.session_clock.sessions[1])
    assert artifacts.result.classification is EvaluationClassification.REJECTED


def test_liquidating_an_unadmitted_holding_stays_permitted() -> None:
    """A security dropped from the universe may be exited, never re-entered."""
    strategy = _buy_ten()
    _run(_engine(), strategy)
    held_context = next(
        context for context in strategy.seen if context.current_holdings
    )
    dropped = StrategyDecisionContextV1.model_validate(
        dict(held_context) | {"admitted_universe": ()}
    )
    assert dropped.current_holdings, "the attack requires a held position"
    security_id = dropped.current_holdings[0].security_id

    staged = stage_decision_targets(_intent(dropped, ((security_id, 0),)), dropped)

    assert staged == (
        SecurityTargetPositionV1(security_id=security_id, target_quantity=0),
    )


def test_holding_an_unadmitted_security_is_rejected() -> None:
    strategy = _buy_ten()
    _run(_engine(), strategy)
    held_context = next(
        context for context in strategy.seen if context.current_holdings
    )
    dropped = StrategyDecisionContextV1.model_validate(
        dict(held_context) | {"admitted_universe": ()}
    )
    security_id = dropped.current_holdings[0].security_id

    with pytest.raises(
        StrategyIntentRejectedError,
        match=r"^a positive target requires an admitted security",
    ):
        stage_decision_targets(_intent(dropped, ((security_id, 1),)), dropped)


def _intent(context: StrategyDecisionContextV1, targets: Any) -> Any:
    from drift.domain.evaluator_strategy import StrategyDecisionIntentV1

    return StrategyDecisionIntentV1(
        session_key=context.session_key,
        decision_time=context.decision_cutoff,
        targets=tuple(
            SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)
            for security_id, quantity in targets
        ),
    )


def _migration_roles() -> tuple[ListingRoleVersionV1, ...]:
    """SEC_A migrates from listing A to listing B exactly at the DAY_2 open."""
    migration = datetime.combine(DAY_2, REGULAR_OPEN, tzinfo=UTC)
    return (
        ListingRoleVersionV1(
            schema_version="1",
            revision=revision(5100),
            security_id=SEC_A,
            listing_id=LISTING_A,
            role=ListingRole.PRIMARY,
            methodology_id="synthetic-primary-v1",
            methodology_version="1",
            effective_interval=TemporalIntervalClaimV1(
                schema_version="1",
                start=boundary_at(datetime(2020, 1, 2, 14, 30, tzinfo=UTC), 5101),
                end=boundary_at(migration, 5102),
            ),
        ),
        ListingRoleVersionV1(
            schema_version="1",
            revision=revision(5200),
            security_id=SEC_A,
            listing_id=LISTING_B,
            role=ListingRole.PRIMARY,
            methodology_id="synthetic-primary-v1",
            methodology_version="1",
            effective_interval=TemporalIntervalClaimV1(
                schema_version="1",
                start=boundary_at(migration, 5201),
                end=None,
            ),
        ),
    )


def test_execution_resolves_the_listing_primary_at_execution_time() -> None:
    """Phase 2 resolves the new listing, not the one primary at the decision."""
    roles = _migration_roles()
    clock = _clock_of(tuple(_session_at(day) for day in DAYS))
    views = (
        _accounting_view(SEC_A, DAY_0),
        _accounting_view(SEC_A, DAY_1),
        _accounting_view(SEC_A, DAY_2, listing_id=LISTING_B),
        _accounting_view(SEC_A, DAY_3, listing_id=LISTING_B),
    )
    bundle = _bundle_over(
        clock=clock,
        decision_views=_default_decision_views(),
        accounting_views=views,
    )
    engine = _engine(
        bundle=bundle,
        evidence=SessionEvaluatorEvidence(listing_role_records=roles),
    )

    # Control: at the decision session the primary listing is still the old one.
    assert (
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=clock.sessions[1],
            role_records=roles,
            listings=LISTINGS,
            termination_records=(),
            lifecycle_records=(),
        ).listing_id
        == LISTING_A
    )

    artifacts = _run(engine)

    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [event.fill.listing_id for event in fills] == [LISTING_B]


def test_a_stale_listing_price_fails_closed_after_a_migration() -> None:
    """A price printed on the abandoned listing cannot fill on the new one."""
    roles = _migration_roles()
    clock = _clock_of(tuple(_session_at(day) for day in DAYS))
    bundle = _bundle_over(
        clock=clock,
        decision_views=_default_decision_views(),
        accounting_views=_default_accounting_views(),
    )
    engine = _engine(
        bundle=bundle,
        evidence=SessionEvaluatorEvidence(listing_role_records=roles),
    )

    artifacts = _run(engine)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason is not None
    assert "but execution resolved listing" in artifacts.result.halt_reason


# ==========================================================================
# Clock authority
# ==========================================================================


def test_a_scheduled_session_cannot_be_relabelled_as_realized_authority() -> None:
    """A generated calendar row must never mint a realized-authority clock."""
    scheduled = tuple(
        _session_at(day, authority="scheduled_reconstruction") for day in DAYS
    )

    with pytest.raises(
        ValidationError, match=r"session authority must match the clock authority mode"
    ):
        _clock_of(scheduled, mode="realized_session_authority")


def test_a_realized_clock_cannot_be_minted_from_scheduled_only_evidence() -> None:
    harness = _harness()

    with pytest.raises(
        ValueError, match=r"^realized clock requires exactly one selected realized"
    ):
        build_realized_session_clock(_queries(harness), harness.context)


def test_a_scheduled_clock_must_acknowledge_absent_halt_telemetry() -> None:
    """Missing halt data is unknown, never an affirmative 'not halted'."""
    scheduled = tuple(
        _session_at(day, authority="scheduled_reconstruction") for day in DAYS
    )

    with pytest.raises(
        ValidationError,
        match=(
            r"scheduled reconstruction clock lacks limitations: .*"
            + re.escape(ALPACA_LIMITATION_ABSENT_HALTS)
        ),
    ):
        _clock_of(
            scheduled,
            mode="scheduled_session_reconstruction",
            limitations=(ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,),
        )


def test_a_scheduled_clock_must_acknowledge_its_reconstruction() -> None:
    scheduled = tuple(
        _session_at(day, authority="scheduled_reconstruction") for day in DAYS
    )

    with pytest.raises(
        ValidationError,
        match=(
            r"scheduled reconstruction clock lacks limitations: .*"
            + re.escape(ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION)
        ),
    ):
        _clock_of(
            scheduled,
            mode="scheduled_session_reconstruction",
            limitations=(ALPACA_LIMITATION_ABSENT_HALTS,),
        )


# --- clock integrity (issue 84) ----------------------------------------------

#: Forged boundaries for the genuine 13:00 New York early close on JAN6. Each
#: is re-hashed under that session's genuine calendar row hashes (P1).
FORGED_EARLY_CLOSE_BOUNDARIES: dict[str, dict[str, datetime]] = {
    "regular-16-00-close-on-a-13-00-row": {"closed_at": utc_close(JAN6, "regular")},
    "10-00-new-york-cutoff-inside-the-session": {
        "closed_at": datetime(2026, 1, 6, 15, 0, tzinfo=UTC)
    },
    "jan6-boundaries-on-the-jan7-wall-clock": {
        "opened_at": datetime(2026, 1, 7, 14, 30, tzinfo=UTC),
        "closed_at": datetime(2026, 1, 7, 21, 0, tzinfo=UTC),
    },
}


def test_a_genuine_early_close_row_decides_at_its_13_00_close() -> None:
    """Control for the forgeries below: the genuine session runs at 13:00."""
    (jan5, jan5_session), (jan6, jan6_session) = early_close_sessions()
    strategy = ReconstructedTargetStrategy({JAN6: ((SEC, 10),)})

    artifacts = run_engine(
        reconstructed_engine(
            scheduled_bundle((jan5, jan6), (jan5_session, jan6_session))
        ),
        strategy,
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert [context.decision_cutoff for context in strategy.seen] == [
        utc_close(JAN5, "regular"),
        utc_close(JAN6, "early_close"),
    ]


@pytest.mark.parametrize(
    "update",
    FORGED_EARLY_CLOSE_BOUNDARIES.values(),
    ids=FORGED_EARLY_CLOSE_BOUNDARIES,
)
def test_a_scheduled_session_cannot_leave_its_calendar_row(
    update: dict[str, datetime],
) -> None:
    """P1: genuine row hashes do not carry forged boundaries into the lane.

    The reconstructions are genuine and name the genuine row, so only the
    re-derivation of the clock session itself can refuse the forgery.
    """
    (jan5, jan5_session), (jan6, jan6_session) = early_close_sessions()
    forged = _resealed(jan6_session, **update)
    assert forged.authority_record_hashes == jan6_session.authority_record_hashes
    bundle = scheduled_bundle((jan5, jan6), (jan5_session, forged))

    with pytest.raises(
        ValueError,
        match=(
            r"^scheduled clock session on XNYS 2026-01-06 is not the session its "
            r"calendar row re-derives: the clock states "
            + re.escape(
                f"{forged.opened_at.isoformat()} to {forged.closed_at.isoformat()}, "
                f"its replay derives {jan6_session.opened_at.isoformat()} to "
                f"{jan6_session.closed_at.isoformat()}"
            )
            + "$"
        ),
    ):
        reconstructed_engine(bundle)


def test_a_scheduled_session_cannot_carry_proofs_its_replay_never_derives() -> None:
    """Genuine boundaries and records still bind the builder's selection proofs.

    Only the proofs differ, so the refusal names the proofs rather than
    reporting identical boundaries as a mismatch.
    """
    (jan5, jan5_session), (jan6, jan6_session) = early_close_sessions()
    forged = _resealed(jan6_session, authority_proof_hashes=(HASH_ONE, HASH_TWO))
    bundle = scheduled_bundle((jan5, jan6), (jan5_session, forged))

    with pytest.raises(
        ValueError,
        match=(
            r"^scheduled clock session on XNYS 2026-01-06 carries selection proofs "
            r"no replay request on it derives$"
        ),
    ):
        reconstructed_engine(bundle)


def test_a_realized_clock_refuses_a_session_stamped_after_a_later_date() -> None:
    """P3: DAY_1 on DAY_3 times would fill a DAY_2 decision at DAY_1's open."""
    forged = _resealed(
        _session_at(DAY_1),
        opened_at=datetime.combine(DAY_3, REGULAR_OPEN, tzinfo=UTC),
        closed_at=datetime.combine(DAY_3, REGULAR_CLOSE, tzinfo=UTC),
    )
    # Control: the same three dates on their own times form a clock.
    _clock_of(tuple(_session_at(day) for day in DAYS[:3]))

    with pytest.raises(
        ValidationError,
        match=r"session clock local dates must not decrease in clock order",
    ):
        _clock_of((_session_at(DAY_0), _session_at(DAY_2), forged))


def test_a_scheduled_clock_refuses_a_session_stamped_after_a_later_date() -> None:
    """P3b: the same inversion on the scheduled lane is refused, not FAILED."""
    (jan5, jan5_session), (jan6, jan6_session), (jan7, jan7_session) = (
        three_regular_sessions()
    )
    forged = _resealed(
        jan6_session,
        opened_at=datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
        closed_at=datetime(2026, 1, 8, 21, 0, tzinfo=UTC),
    )

    with pytest.raises(
        ValidationError,
        match=r"session clock local dates must not decrease in clock order",
    ):
        scheduled_bundle((jan5, jan6, jan7), (jan5_session, jan7_session, forged))


def test_a_staged_decision_executes_only_at_a_later_dates_open() -> None:
    """The engine's own next-open guard, checked on the session pair itself.

    On one venue the clock's guards already make every next session qualify,
    so the refused pairs here are ones only a clock that escaped them could
    present. The guard does not rely on them.
    """
    decision = _session_at(DAY_1)
    # Control: the next date's open qualifies, even exactly at the cutoff.
    require_next_open_execution(decision, _session_at(DAY_2))
    require_next_open_execution(
        decision, _resealed(_session_at(DAY_2), opened_at=decision.closed_at)
    )
    prefix = "a decision staged at the XNYS 2026-01-06 close cannot execute at the "

    with pytest.raises(
        IndeterminateExecutionError,
        match=(
            "^"
            + re.escape(
                f"{prefix}XNYS 2026-01-07 open: that session opens at "
                "2026-01-06T20:00:00+00:00, before the decision cutoff "
                "2026-01-06T21:00:00+00:00"
            )
            + "$"
        ),
    ):
        require_next_open_execution(
            decision,
            _resealed(
                _session_at(DAY_2), opened_at=datetime(2026, 1, 6, 20, 0, tzinfo=UTC)
            ),
        )
    for execution in (
        _xnas_session(DAY_1, time(21, 30), time(23, 0)),
        _resealed(
            _session_at(DAY_0),
            opened_at=datetime.combine(DAY_2, REGULAR_OPEN, tzinfo=UTC),
            closed_at=datetime.combine(DAY_2, REGULAR_CLOSE, tzinfo=UTC),
        ),
    ):
        key = execution.session_key
        with pytest.raises(
            IndeterminateExecutionError,
            match=(
                "^"
                + re.escape(
                    f"{prefix}{key.mic} {key.local_date.isoformat()} open: "
                    "next-open execution requires a later local date"
                )
                + "$"
            ),
        ):
            require_next_open_execution(decision, execution)


#: Decisions staged at the XNYS close ahead of a same-date XNAS open: one that
#: trades there, and one that holds cash and would read no price at all.
SAME_DATE_TARGETS: dict[str, dict[date, tuple[tuple[UUID, int], ...]]] = {
    "buys": {DAY_1: ((SEC_A, 10),)},
    "holds-cash": {},
}


@pytest.mark.parametrize("targets", SAME_DATE_TARGETS.values(), ids=SAME_DATE_TARGETS)
def test_a_decision_never_fills_at_another_venues_open_on_its_own_date(
    targets: dict[date, tuple[tuple[UUID, int], ...]],
) -> None:
    """A legal two-venue clock whose next open shares the decision's date.

    XNAS opens after the XNYS decision cutoff and without overlap, so the
    clock admits it. Its open is still on the date the decision was taken,
    which is not the next-open execution the protocol states. The refusal
    holds whether or not the staged decision trades, so a same-date
    multi-venue clock halts at its second session pending an owner ruling.
    """
    clock = _clock_of(
        (_session_at(DAY_1), _xnas_session(DAY_1, time(21, 30), time(23, 0)))
    )
    bundle = _bundle_over(
        clock=clock,
        decision_views=(_decision_view(SEC_A, DAY_1),),
        accounting_views=(_accounting_view(SEC_A, DAY_1),),
    )
    strategy = FixedTargetStrategy(targets)

    artifacts = _run(_engine(bundle=bundle, protocol=_protocol(warmup=1)), strategy)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 1
    assert [event for event in artifacts.trace.events if event.kind == "fill"] == []
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.OPEN_EXECUTION
    assert causes[0].cause == (
        "a decision staged at the XNYS 2026-01-06 close cannot execute at the "
        "XNAS 2026-01-06 open: next-open execution requires a later local date"
    )


def test_the_non_overlap_guard_is_what_keeps_decision_history_closed() -> None:
    """F7: the #66 history filter sits behind the overlap guard; prove both.

    On any clock the model admits, every stepped session has closed by the
    next open, so the stepped prefix is the closed history and the filter
    never drops a session. The #66 inversion itself, XNAS opening first and
    closing after the XNYS early close, is refused by the clock. Behind that
    refusal the filter still keeps the later-closing session out of history.
    """
    xnas = _xnas_session(DAY_1, time(13, 30), REGULAR_CLOSE)
    xnys = _session_at(DAY_1, closes_at=EARLY_CLOSE)
    inverted = tuple(sorted((xnys, xnas), key=session_order_key))
    assert inverted == (xnas, xnys)

    with pytest.raises(
        ValidationError, match=r"session clock sessions must not overlap"
    ):
        _clock_of(inverted)
    assert reconstructed_history_sessions(inverted, 1) == {xnys.session_key}

    # Control: on an admitted clock the history is the whole stepped prefix.
    sessions = _clock_of(tuple(_session_at(day) for day in DAYS)).sessions
    for index in range(len(sessions)):
        assert reconstructed_history_sessions(sessions, index) == {
            item.session_key for item in sessions[: index + 1]
        }


def test_a_missing_bar_on_the_execution_open_fails_closed_to_indeterminate() -> None:
    """No close, no prior open, and no schedule may substitute for a missing bar."""
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=_default_decision_views(),
        accounting_views=tuple(
            _accounting_view(SEC_A, day) for day in (DAY_0, DAY_1, DAY_3)
        ),
    )

    artifacts = _run(_engine(bundle=bundle))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.OPEN_EXECUTION
    assert "no authorized accounting view for security" in causes[0].cause


def test_a_scheduled_only_corpus_cannot_materialize_any_authentic_view() -> None:
    """The mechanism behind issue 42, proven against the landed M1d path.

    ``bind_observation_session`` classifies a source session ``bound`` only on
    a selected realized session that opened with exact bounds. A
    scheduled-only corpus therefore never materializes a derived view, so no
    scheduled-reconstruction bundle can carry authentic decision or accounting
    evidence. That still holds after issue 46: the Table 22 row requiring an
    executing ``scheduled_session_reconstruction`` run is satisfied by the
    EXPLORATORY-only reconstructed decision lane in
    ``test_m2_reconstructed_decisions.py``, never by a hybrid bundle.
    """
    control_harness = NormalizationHarness(source_only=True)
    control = control_harness.normalize(
        control_harness.normalization_query("source_basis")
    )
    assert control.classification == "materialized"
    assert control.view is not None

    scheduled = NormalizationHarness(source_only=True)
    scheduled.source.attach_sessions(
        schedule_state="regular", realized_outcome="missing"
    )
    scheduled.source.attach_m1b()
    scheduled.context = scheduled.source.context

    result = scheduled.normalize(scheduled.normalization_query("source_basis"))

    assert result.classification == "indeterminate"
    assert result.view is None
    assert "realized_session_not_selected" in result.reasons
    assert "exact_realized_binding_unavailable" in result.reasons


def test_a_scheduled_reconstruction_bundle_carries_no_authentic_views() -> None:
    """A bundle built through the sanctioned path has both buckets empty."""
    bundle = _scheduled_bundle()

    assert bundle.session_clock.mode == "scheduled_session_reconstruction"
    assert bundle.authentic_decision_views == ()
    assert bundle.authentic_accounting_views == ()
    assert bundle.has_exploratory_reconstructions is True


def test_an_empty_decision_bucket_never_reaches_the_strategy() -> None:
    """The state every scheduled-reconstruction bundle is in, run end to end."""
    bundle = _bundle_over(
        clock=_clock_of(tuple(_session_at(day) for day in DAYS)),
        decision_views=(),
        accounting_views=_default_accounting_views(),
    )
    strategy = _buy_ten()

    artifacts = _run(_engine(bundle=bundle, protocol=_protocol(warmup=1)), strategy)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 0
    assert strategy.seen == []
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert "no authorized decision evidence for the decision cutoff" in causes[0].cause


def test_an_unresumed_suspension_is_not_read_as_not_halted() -> None:
    """Absence of a resumption is unknown, so the listing is not executable."""
    session = _session_at(DAY_2)
    roles = (_role_record(SEC_A, LISTING_A, suffix=5300),)
    suspension = ListingLifecycleVersionV1(
        schema_version="1",
        revision=revision(5400),
        listing_id=LISTING_A,
        event_kind=ListingLifecycleEventKind.SUSPENDED,
        effective_time=boundary_at(datetime(2026, 1, 6, 14, 30, tzinfo=UTC), 5401),
        related_listing_id=None,
    )

    # Control: without the suspension the listing resolves cleanly.
    assert (
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=session,
            role_records=roles,
            listings=LISTINGS,
            termination_records=(),
            lifecycle_records=(),
        ).listing_id
        == LISTING_A
    )

    with pytest.raises(
        IndeterminateExecutionError,
        match=r"^suspended listing is not executable: listing",
    ):
        resolve_execution_listing(
            security_id=SEC_A,
            execution_session=session,
            role_records=roles,
            listings=LISTINGS,
            termination_records=(),
            lifecycle_records=(suspension,),
        )


# ==========================================================================
# Provider boundary
# ==========================================================================


def _core_modules() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2] / "src" / "drift"
    return tuple(
        sorted(
            (
                *(root / "evaluator").glob("*.py"),
                *(root / "domain").glob("evaluator_*.py"),
                root / "domain" / "replay_provenance.py",
            )
        )
    )


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                names.add(node.module)
    return tuple(sorted(names))


def test_the_evaluator_core_imports_no_provider_adapter() -> None:
    """The single evaluator core never reaches a vendor-specific module."""
    modules = _core_modules()
    assert len(modules) >= 20, "the provider-boundary scan found no core modules"

    offending: list[tuple[str, str]] = []
    for path in modules:
        for imported in _imported_modules(path):
            if not imported.startswith("drift"):
                continue
            if not imported.startswith(CORE_PACKAGE_PREFIXES):
                offending.append((path.name, imported))

    assert offending == []


def test_the_evaluator_core_names_no_vendor_module_path() -> None:
    offending: list[tuple[str, str]] = []
    for path in _core_modules():
        for imported in _imported_modules(path):
            lowered = imported.lower()
            if "alpaca" in lowered or "adapters" in lowered.split("."):
                offending.append((path.name, imported))

    assert offending == []


def test_the_decision_context_refuses_a_raw_vendor_payload() -> None:
    strategy = _buy_ten()
    _run(_engine(), strategy)
    context = strategy.seen[0]

    with pytest.raises(ValidationError) as error:
        StrategyDecisionContextV1.model_validate(
            dict(context) | {"vendor_payload": {"bars": []}}
        )

    reported = [
        (item["type"], item["loc"]) for item in error.value.errors(include_url=False)
    ]
    assert reported == [("extra_forbidden", ("vendor_payload",))]


def test_the_decision_context_surface_is_pinned() -> None:
    """Widening the strategy boundary must be a deliberate, reviewed change."""
    assert set(StrategyDecisionContextV1.model_fields) == {
        "schema_version",
        "session_key",
        "decision_session",
        "decision_cutoff",
        "admitted_universe",
        "current_holdings",
        "current_cash",
        "portfolio_nav",
        "decision_views",
    }


def test_the_admitted_universe_is_a_plain_identifier_tuple() -> None:
    """A strategy sees security identities, never vendor symbols or payloads."""
    strategy = _buy_ten()
    _run(_engine(), strategy)
    context = strategy.seen[0]

    assert context.admitted_universe
    for member in context.admitted_universe:
        assert isinstance(member, UUID)
        assert member.version == 7
