"""Unit tests for M2 Task 5 strategy boundary contracts and staging rules."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import cache

import pytest
from observation_test_support import (
    NormalizationHarness,
    market_uid,
    reference,
    uid,
)
from pydantic import ValidationError

from drift.domain.common import UUID7
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    evaluation_session_hash,
)
from drift.domain.evaluator_portfolio import SecurityHoldingV1
from drift.domain.evaluator_strategy import (
    DECISION_TIME_MISMATCH,
    PositionViewV1,
    RuntimeStrategy,
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
    StrategyDecisionViewV1,
    StrategyIntentRejectedError,
    position_view,
    stage_decision_targets,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    NormalizationQueryV1,
    derived_view_output_hash,
)
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationOutcomeQueryV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)
from drift.serialization.canonical import content_hash

SEC_A = uid(21)
SEC_B = uid(22)
SEC_C = uid(23)
VIEW_SECURITY = market_uid(21)

SESSION_DATE = date(2026, 11, 30)
SOURCE_DATE = date(2026, 11, 27)
CUTOFF = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)

CODE_HASH = "a" * 64

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64


def _key(day: date = SESSION_DATE) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(
    day: date = SESSION_DATE, *, close: datetime | None = None
) -> EvaluationSessionV1:
    default_close = datetime.combine(day, time(21, 0), tzinfo=UTC)
    closed_at = default_close if close is None else close
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_key(day),
        opened_at=closed_at - timedelta(hours=6, minutes=30),
        closed_at=closed_at,
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


@cache
def _split_normalized_decision_view(anchor: date) -> DerivedObservationViewV1:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query("split_normalized", anchor_date=anchor)
    result = harness.normalize(query)
    return materialize_observation_decision(result.reference, query, harness.context)


@cache
def _source_basis_decision_view() -> DerivedObservationViewV1:
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query("source_basis")
    result = harness.normalize(query)
    return materialize_observation_decision(result.reference, query, harness.context)


@cache
def _causal_source_basis_view() -> DerivedObservationViewV1:
    """A source-basis decision view genuinely answerable at the cutoff.

    The default harness query carries a knowledge clock 27 hours past the
    decision cutoff. This one is materialized under clocks that land exactly
    on the cutoff, so it is evidence a decision taken there could have read.
    """
    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "source_basis",
        # The harness derives its vintage as outer_horizon plus one day, and
        # the vintage is both the decision time and the knowledge cutoff.
        outer_horizon="2026-11-29T21:00:00Z",
        effective_cutoff="2026-11-30T21:00:00Z",
    )
    result = harness.normalize(query)
    return materialize_observation_decision(result.reference, query, harness.context)


def _reseal(
    view: DerivedObservationViewV1, observation: object, *, validated: bool = True
) -> DerivedObservationViewV1:
    """Rebind one derived view to a restated observation query.

    `validated` is only lowered where the restatement is deliberately
    forged past a contract the derived view itself already enforces.
    """
    query = NormalizationQueryV1.model_construct(
        **(dict(view.query) | {"observation": observation})
    )
    draft = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"query": query, "query_hash": content_hash(query)})
    )
    sealed = DerivedObservationViewV1.model_construct(
        **(dict(draft) | {"output_hash": derived_view_output_hash(draft)})
    )
    if not validated:
        return sealed
    return DerivedObservationViewV1.model_validate(dict(sealed))


def _reclocked(
    view: DerivedObservationViewV1, *, decision_time: datetime
) -> DerivedObservationViewV1:
    """Restate one decision view's clocks, keeping the query well formed.

    The M1d pipeline can only materialize the split-normalized case with a
    knowledge clock past the decision session close, because proving the
    anchor session opened depends on evidence published after that close.
    Restating the same derived payload under clocks a decision at the cutoff
    could have read is the only way to exercise the anchor rule and the
    clock rule independently rather than having one mask the other.
    """
    observation = view.query.observation.model_copy(
        update={
            "decision_time": decision_time,
            "knowledge_cutoff": decision_time,
            "effective_cutoff": decision_time,
        }
    )
    return _reseal(view, observation)


def _forged_clocks(
    view: DerivedObservationViewV1, **clocks: datetime
) -> DerivedObservationViewV1:
    """Restate clocks past the observation query's own internal constraint.

    The query itself already forbids a knowledge or effective clock after its
    decision time, so each context guard can only be exercised on its own by
    bypassing that constructor.
    """
    observation = ObservationDecisionQueryV1.model_construct(
        **(dict(view.query.observation) | clocks)
    )
    return _reseal(view, observation)


@cache
def _causal_split_normalized_view() -> DerivedObservationViewV1:
    return _reclocked(
        _split_normalized_decision_view(SESSION_DATE), decision_time=CUTOFF
    )


@cache
def _outcome_view() -> DerivedObservationViewV1:
    harness = NormalizationHarness()
    query = harness.normalization_query("source_basis")
    result = harness.normalize(query)
    return materialize_observation_outcome(result.reference, query, harness.context)


def _holding(security_id: UUID7, quantity: int, basis: str) -> SecurityHoldingV1:
    return SecurityHoldingV1(
        security_id=security_id, quantity=quantity, cost_basis=Decimal(basis)
    )


def _context(
    *,
    admitted: tuple[UUID7, ...] = (SEC_A, SEC_B),
    holdings: tuple[PositionViewV1, ...] = (),
    cash: str = "10000.00",
    nav: str | None = None,
    views: tuple[StrategyDecisionViewV1, ...] = (),
    day: date = SESSION_DATE,
    cutoff: datetime | None = None,
    session: EvaluationSessionV1 | None = None,
) -> StrategyDecisionContextV1:
    decision_session = _evaluation_session(day) if session is None else session
    return StrategyDecisionContextV1(
        session_key=_key(day),
        decision_session=decision_session,
        decision_cutoff=decision_session.closed_at if cutoff is None else cutoff,
        admitted_universe=admitted,
        current_holdings=holdings,
        current_cash=Decimal(cash),
        portfolio_nav=Decimal(cash if nav is None else nav),
        decision_views=views,
    )


def _intent(
    *,
    targets: tuple[SecurityTargetPositionV1, ...],
    day: date = SESSION_DATE,
    decision_time: datetime = CUTOFF,
) -> StrategyDecisionIntentV1:
    return StrategyDecisionIntentV1(
        session_key=_key(day), decision_time=decision_time, targets=targets
    )


def _target(security_id: UUID7, quantity: int) -> SecurityTargetPositionV1:
    return SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)


# --- position views ---


def test_position_view_projects_a_holding_exactly() -> None:
    view = position_view(_holding(SEC_A, 8, "100.00"))
    assert view.security_id == SEC_A
    assert view.quantity == 8
    assert view.cost_basis == Decimal("100.00")
    assert view.average_cost_per_share == Decimal("12.5")


def test_position_view_rejects_inconsistent_average_cost() -> None:
    with pytest.raises(ValidationError, match="average cost"):
        PositionViewV1(
            security_id=SEC_A,
            quantity=8,
            cost_basis=Decimal("100.00"),
            average_cost_per_share=Decimal("13.00"),
        )


def test_position_view_rejects_non_positive_quantity() -> None:
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            PositionViewV1(
                security_id=SEC_A,
                quantity=bad,
                cost_basis=Decimal("0.00"),
                average_cost_per_share=Decimal("0.00"),
            )


def test_position_view_rejects_negative_cost_basis() -> None:
    with pytest.raises(ValidationError, match="cost basis"):
        PositionViewV1(
            security_id=SEC_A,
            quantity=2,
            cost_basis=Decimal("-10.00"),
            average_cost_per_share=Decimal("-5.00"),
        )


# --- decision views ---


def test_decision_view_requires_matching_security() -> None:
    with pytest.raises(ValidationError, match="share the security"):
        StrategyDecisionViewV1(
            security_id=SEC_A, views=(_source_basis_decision_view(),)
        )


def test_decision_view_rejects_outcome_role_evidence() -> None:
    with pytest.raises(ValidationError, match="decision-role"):
        StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(_outcome_view(),))


def test_decision_view_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=())


def test_decision_view_rejects_duplicate_evidence() -> None:
    view = _source_basis_decision_view()
    with pytest.raises(ValidationError, match="unique"):
        StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(view, view))


def test_decision_view_canonicalizes_member_order() -> None:
    first = _source_basis_decision_view()
    second = _split_normalized_decision_view(SESSION_DATE)
    forward = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(first, second))
    reverse = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(second, first))
    assert forward.views == reverse.views


# --- decision context ---


def test_context_canonicalizes_admitted_universe() -> None:
    context = _context(admitted=(SEC_C, SEC_A, SEC_B))
    assert context.admitted_universe == (SEC_A, SEC_B, SEC_C)


def test_context_rejects_duplicate_admitted_security() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _context(admitted=(SEC_A, SEC_A))


def test_context_canonicalizes_holdings_by_security() -> None:
    holdings = (
        position_view(_holding(SEC_C, 1, "10.00")),
        position_view(_holding(SEC_A, 1, "10.00")),
    )
    context = _context(holdings=holdings)
    assert tuple(item.security_id for item in context.current_holdings) == (
        SEC_A,
        SEC_C,
    )


def test_context_rejects_duplicate_holding_security() -> None:
    holding = position_view(_holding(SEC_A, 1, "10.00"))
    with pytest.raises(ValidationError, match="unique"):
        _context(holdings=(holding, holding))


def test_context_rejects_negative_cash() -> None:
    with pytest.raises(ValidationError, match="cash"):
        _context(cash="-0.01")


def test_context_rejects_negative_nav() -> None:
    with pytest.raises(ValidationError, match="net asset value"):
        _context(cash="0.00", nav="-0.01")


def test_context_accepts_split_normalized_view_anchored_to_its_session() -> None:
    view = StrategyDecisionViewV1(
        security_id=VIEW_SECURITY,
        views=(_causal_split_normalized_view(),),
    )
    context = _context(views=(view,))
    assert context.decision_views == (view,)


def test_context_rejects_split_normalized_view_anchored_to_a_future_session() -> None:
    view = StrategyDecisionViewV1(
        security_id=VIEW_SECURITY,
        views=(_causal_split_normalized_view(),),
    )
    with pytest.raises(ValidationError, match="anchored"):
        _context(views=(view,), day=SOURCE_DATE)


def test_context_accepts_evidence_clocked_exactly_at_the_cutoff() -> None:
    view = StrategyDecisionViewV1(
        security_id=VIEW_SECURITY, views=(_causal_source_basis_view(),)
    )
    observation = _causal_source_basis_view().query.observation
    assert isinstance(observation, ObservationDecisionQueryV1)
    assert observation.decision_time == CUTOFF
    assert observation.knowledge_cutoff == CUTOFF
    assert observation.effective_cutoff == CUTOFF
    assert _context(views=(view,)).decision_views == (view,)


def test_context_rejects_evidence_whose_knowledge_clock_follows_the_cutoff() -> None:
    # The reviewer's demonstration: a view whose source session passes the
    # session guard, carrying a knowledge cutoff 27 hours past the cutoff.
    shipped = _source_basis_decision_view()
    observation = shipped.query.observation
    assert isinstance(observation, ObservationDecisionQueryV1)
    assert shipped.source_session.local_date == SOURCE_DATE
    assert observation.knowledge_cutoff == datetime(2026, 12, 2, tzinfo=UTC)
    assert observation.knowledge_cutoff - CUTOFF == timedelta(hours=27)
    view = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(shipped,))
    with pytest.raises(ValidationError, match="knowledge cutoff follows"):
        _context(views=(view,))


def test_context_rejects_evidence_whose_effective_clock_follows_the_cutoff() -> None:
    late = _forged_clocks(
        _causal_source_basis_view(),
        effective_cutoff=CUTOFF + timedelta(seconds=1),
    )
    view = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(late,))
    with pytest.raises(ValidationError, match="effective cutoff follows"):
        _context(views=(view,))


def test_context_rejects_a_forged_knowledge_clock_past_the_cutoff() -> None:
    late = _forged_clocks(
        _causal_source_basis_view(),
        knowledge_cutoff=CUTOFF + timedelta(seconds=1),
    )
    view = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(late,))
    with pytest.raises(ValidationError, match="knowledge cutoff follows"):
        _context(views=(view,))


def test_context_rejects_evidence_queried_at_another_decision_time() -> None:
    early = _reclocked(
        _causal_source_basis_view(), decision_time=CUTOFF - timedelta(days=1)
    )
    view = StrategyDecisionViewV1(security_id=VIEW_SECURITY, views=(early,))
    with pytest.raises(ValidationError, match="queried at the decision cutoff"):
        _context(views=(view,))


def _forged_outcome_group(
    *, horizon: datetime, vintage: datetime
) -> StrategyDecisionViewV1:
    """A decision-role view forged onto an ex-post outcome query."""
    decision = _causal_source_basis_view()
    fields = dict(decision.query.observation)
    for clock in ("decision_time", "knowledge_cutoff", "effective_cutoff"):
        fields.pop(clock)
    outcome_query = ObservationOutcomeQueryV1.model_construct(
        **(
            fields
            | {
                "kind": "outcome",
                "economic_horizon": horizon,
                "evidence_vintage_cutoff": vintage,
            }
        )
    )
    forged = _reseal(decision, outcome_query, validated=False)
    return StrategyDecisionViewV1.model_construct(
        schema_version="1", security_id=VIEW_SECURITY, views=(forged,)
    )


def test_context_rejects_a_forged_outcome_query_reaching_past_the_cutoff() -> None:
    beyond = CUTOFF + timedelta(days=1)
    group = _forged_outcome_group(horizon=beyond, vintage=beyond)
    with pytest.raises(ValidationError, match="economic horizon follows"):
        _context(views=(group,))


def test_context_rejects_a_forged_outcome_vintage_past_the_cutoff() -> None:
    # The horizon alone is causal here, so only the vintage guard can fire.
    group = _forged_outcome_group(horizon=CUTOFF, vintage=CUTOFF + timedelta(days=1))
    with pytest.raises(ValidationError, match="evidence vintage cutoff follows"):
        _context(views=(group,))


def test_context_requires_the_cutoff_to_be_the_decision_session_close() -> None:
    with pytest.raises(ValidationError, match="decision session close"):
        _context(cutoff=CUTOFF - timedelta(seconds=1))


def test_context_rejects_a_cutoff_after_the_decision_session_close() -> None:
    with pytest.raises(ValidationError, match="decision session close"):
        _context(cutoff=CUTOFF + timedelta(hours=3))


def test_context_requires_the_decision_session_to_be_the_context_session() -> None:
    with pytest.raises(ValidationError, match="decision session must be"):
        _context(session=_evaluation_session(SOURCE_DATE), cutoff=CUTOFF)


def test_context_rejects_view_sourced_after_its_decision_session() -> None:
    view = StrategyDecisionViewV1(
        security_id=VIEW_SECURITY, views=(_source_basis_decision_view(),)
    )
    with pytest.raises(ValidationError, match="after"):
        _context(views=(view,), day=date(2026, 11, 26))


def test_context_rejects_duplicate_decision_view_security() -> None:
    view = StrategyDecisionViewV1(
        security_id=VIEW_SECURITY, views=(_source_basis_decision_view(),)
    )
    with pytest.raises(ValidationError, match="unique"):
        _context(views=(view, view))


# --- target positions ---


def test_target_position_does_not_carry_an_execution_listing() -> None:
    assert "execution_listing_id" not in SecurityTargetPositionV1.model_fields
    assert "listing_id" not in SecurityTargetPositionV1.model_fields
    with pytest.raises(ValidationError, match="execution_listing_id"):
        SecurityTargetPositionV1.model_validate(
            {
                "security_id": SEC_A,
                "target_quantity": 1,
                "execution_listing_id": uid(99),
            }
        )


def test_target_position_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=-1)


def test_target_position_accepts_zero_quantity() -> None:
    assert _target(SEC_A, 0).target_quantity == 0


# --- decision intent ---


def test_intent_canonicalizes_target_order() -> None:
    intent = _intent(targets=(_target(SEC_C, 1), _target(SEC_A, 2)))
    assert tuple(item.security_id for item in intent.targets) == (SEC_A, SEC_C)


def test_intent_rejects_duplicate_target_security() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _intent(targets=(_target(SEC_A, 1), _target(SEC_A, 2)))


# --- staging ---


def test_staging_rejects_decision_time_that_is_not_the_cutoff() -> None:
    intent = _intent(
        targets=(_target(SEC_A, 1),),
        decision_time=datetime(2026, 11, 30, 21, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match=DECISION_TIME_MISMATCH):
        stage_decision_targets(intent, _context())


def test_staging_rejects_wall_clock_decision_time() -> None:
    intent = _intent(targets=(_target(SEC_A, 1),), decision_time=datetime.now(UTC))
    with pytest.raises(StrategyIntentRejectedError):
        stage_decision_targets(intent, _context())


def test_decision_time_mismatch_is_a_value_error() -> None:
    assert issubclass(StrategyIntentRejectedError, ValueError)


def test_staging_rejects_session_key_mismatch() -> None:
    intent = _intent(targets=(_target(SEC_A, 1),), day=date(2026, 11, 27))
    with pytest.raises(StrategyIntentRejectedError, match="session"):
        stage_decision_targets(intent, _context())


def test_staging_liquidates_an_omitted_holding() -> None:
    holdings = (position_view(_holding(SEC_B, 40, "400.00")),)
    context = _context(holdings=holdings)
    staged = stage_decision_targets(_intent(targets=(_target(SEC_A, 5),)), context)
    assert staged == (_target(SEC_A, 5), _target(SEC_B, 0))


def test_staging_preserves_an_explicitly_maintained_holding() -> None:
    holdings = (position_view(_holding(SEC_B, 40, "400.00")),)
    context = _context(holdings=holdings)
    staged = stage_decision_targets(_intent(targets=(_target(SEC_B, 40),)), context)
    assert staged == (_target(SEC_B, 40),)


def test_staging_returns_canonically_sorted_targets() -> None:
    holdings = (position_view(_holding(SEC_C, 1, "10.00")),)
    context = _context(admitted=(SEC_A, SEC_B, SEC_C), holdings=holdings)
    staged = stage_decision_targets(
        _intent(targets=(_target(SEC_B, 2), _target(SEC_A, 1))), context
    )
    assert tuple(item.security_id for item in staged) == (SEC_A, SEC_B, SEC_C)


def test_staging_rejects_entry_into_a_non_admitted_security() -> None:
    context = _context(admitted=(SEC_A,))
    with pytest.raises(StrategyIntentRejectedError, match="admitted"):
        stage_decision_targets(_intent(targets=(_target(SEC_B, 1),)), context)


def test_staging_allows_liquidation_of_a_non_admitted_security() -> None:
    holdings = (position_view(_holding(SEC_B, 3, "30.00")),)
    context = _context(admitted=(SEC_A,), holdings=holdings)
    staged = stage_decision_targets(_intent(targets=(_target(SEC_B, 0),)), context)
    assert staged == (_target(SEC_B, 0),)


def test_staging_rejects_a_forged_negative_target() -> None:
    forged = SecurityTargetPositionV1.model_construct(
        schema_version="1", security_id=SEC_A, target_quantity=-5
    )
    intent = StrategyDecisionIntentV1.model_construct(
        schema_version="1",
        session_key=_key(),
        decision_time=CUTOFF,
        targets=(forged,),
    )
    with pytest.raises(StrategyIntentRejectedError, match="non-negative"):
        stage_decision_targets(intent, _context())


def test_staging_rejects_forged_duplicate_targets() -> None:
    intent = StrategyDecisionIntentV1.model_construct(
        schema_version="1",
        session_key=_key(),
        decision_time=CUTOFF,
        targets=(_target(SEC_A, 1), _target(SEC_A, 2)),
    )
    with pytest.raises(StrategyIntentRejectedError, match="unique"):
        stage_decision_targets(intent, _context())


def test_staging_of_an_empty_intent_liquidates_every_holding() -> None:
    holdings = (
        position_view(_holding(SEC_A, 1, "10.00")),
        position_view(_holding(SEC_B, 2, "20.00")),
    )
    staged = stage_decision_targets(_intent(targets=()), _context(holdings=holdings))
    assert staged == (_target(SEC_A, 0), _target(SEC_B, 0))


# --- runtime protocol ---


class _FlatStrategy:
    """Minimal conforming strategy used to exercise the runtime protocol."""

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity

    @property
    def strategy_reference(self) -> StrategyReference:
        return StrategyReference(
            strategy_id=uid(7),
            strategy_version="1",
            code_hash=CODE_HASH,
            artifact_reference=reference(8),
        )

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return StrategyDecisionIntentV1(
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=tuple(
                SecurityTargetPositionV1(
                    security_id=security_id, target_quantity=self._quantity
                )
                for security_id in context.admitted_universe
            ),
        )


def test_runtime_strategy_protocol_accepts_a_conforming_strategy() -> None:
    strategy: RuntimeStrategy = _FlatStrategy(3)
    context = _context()
    staged = stage_decision_targets(strategy.decide(context), context)
    assert staged == (_target(SEC_A, 3), _target(SEC_B, 3))
