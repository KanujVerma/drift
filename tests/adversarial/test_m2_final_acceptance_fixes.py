"""M2 adversarial acceptance: the four final-acceptance fixes of issue 142.

The final M2 acceptance rerun (#8, at ``7213c67``) found four defects, all
already present on ``main``:

* D1 (FA3 F1). The realized lane never bound its accounting price currency to
  the book currency, so an ``ISO-4217 EUR`` book filled and marked the USD
  prices of the M1d regular-session trade-bar profile, accepted a EUR dividend
  on the same security, and ended COMPLETE with one NAV summing both.
* D2 (FA2 F1). The evaluator evidence hash identifies each evidence collection
  by its sorted member hashes, but the engine kept the caller's order, so one
  run identity gave two results depending on member order.
* D3 (FA2 F2). A result could carry an admission of bundle X under a run
  identity naming bundle Y.
* D4 (FA3 F2). ``canonical_money`` rounded an input with more than 34
  significant digits to the pinned context instead of refusing it.

Each reviewer probe is a test here, with a specific exception and a match
unique to its guard.
"""

# ruff: noqa: E402

import copy
import dataclasses
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

_SUPPORT = Path(__file__).resolve().parents[1]
for folder in (_SUPPORT / "unit", _SUPPORT / "integration"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import exploratory_decision_test_support as eds
import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    LISTING,
    SEC,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    exploratory_admission,
    reconstructed_engine,
    run_engine,
    scheduled_session_case,
)
from exploratory_decision_test_support import replay_of as exploratory_replay_of
from observation_test_support import ObservationHarness
from pydantic import ValidationError
from session_test_support import boundary_at, revision
from test_evaluator_reconstruction import make_policy

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.economic_common import ActionKind, CashComponentV1
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_corporate_actions import (
    SecurityEconomicOutcomeV1,
    exact_decimal,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioFillV1,
    PortfolioStateV1,
    canonical_money,
    fits_portfolio_context,
)
from drift.domain.evaluator_protocol import (
    EvaluationProtocolV1,
    evaluation_protocol_hash,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    ExploratoryEvaluationResultV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_trace import (
    FillTraceEventV1,
    IndeterminateCauseTraceEventV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.securities import (
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingTerminationReason,
    ListingTerminationVersionV1,
    OutcomeEvidenceStatus,
)
from drift.domain.temporal import SourcePrecision
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    _revalidated_evidence,
    accounting_view_currency,
)
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    build_exploratory_reconstructed_session_observation,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.markets.observation_validation import m1d_context_hash
from drift.serialization.canonical import content_hash

# --- D1: the realized lane binds its price currency to the book --------------


def _at(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _dividend(code: str) -> SecurityEconomicOutcomeV1:
    """The probe's dividend on SEC_A, ex and payable on DAY_3, in ``code``."""
    return _dividend_of(
        ca._cash(amount="0.5", component_id="d", predecessor=eng.SEC_A, code=code)
    )


def _dividend_of(cash: CashComponentV1) -> SecurityEconomicOutcomeV1:
    """A dividend on SEC_A paying ``cash``, ex and payable on DAY_3."""
    terms = ca._terms(
        suffix=5500,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(cash,),
        dates=(
            ca._date_fact("ex", _at(eng.DAY_3)),
            ca._date_fact("payable", _at(eng.DAY_3)),
        ),
        security_id=eng.SEC_A,
    )
    effect = ca._effect(
        suffix=5501,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(cash,),
        terms=terms,
        occurrence_id="p1-div",
        effective_at=_at(eng.DAY_3),
        security_id=eng.SEC_A,
    )
    return ca._outcome(
        security_id=eng.SEC_A,
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(
            ca._delivery(
                components=(cash,),
                security_id=eng.SEC_A,
                occurrence_id="p1-div",
                settled_at=_at(eng.DAY_3),
            ),
        ),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )


def _realized_engine(
    *,
    code: str,
    outcomes: tuple[SecurityEconomicOutcomeV1, ...] = (),
    accounting_views: tuple[DerivedObservationViewV1, ...] | None = None,
) -> SessionEvaluatorEngine:
    """A realized-lane engine over the genuine USD-profile views, in ``code``."""
    bundle = eng._bundle(
        accounting_views=accounting_views,
        economic_outcomes=tuple(item.resolution for item in outcomes),
    )
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS, economic_outcomes=outcomes
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=code,
    )


def _refusal(field_name: str, day: date, code: str) -> str:
    return (
        f"accounting {field_name} price for security {eng.SEC_A} on XNYS "
        f"{day.isoformat()} is in USD, not the book currency {code}"
    )


def test_the_accounting_views_are_in_the_currency_their_profile_pins() -> None:
    """Control: a genuine M1d view cites the regular-session trade-bar profile."""
    assert accounting_view_currency(eng._accounting_view(eng.SEC_A, eng.DAY_2)) == (
        "USD"
    )


def test_a_realized_book_in_another_currency_halts_indeterminate() -> None:
    """The realized-lane twin of the reconstructed lane's EUR book control.

    Before issue 142 this EUR book filled the USD open, marked USD closes and
    ended COMPLETE with a NAV of 10200.
    """
    artifacts = eng._run(_realized_engine(code="EUR"))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _refusal("open", eng.DAY_2, "EUR")
    assert artifacts.result.metrics.committed_fill_count == 0
    assert artifacts.final_state.holdings == ()
    assert artifacts.final_state.cash_balance == Decimal("10000")
    causes = [
        event
        for event in artifacts.trace.events
        if isinstance(event, IndeterminateCauseTraceEventV1)
    ]
    assert [(item.phase.value, item.cause_kind) for item in causes] == [
        ("open_execution", "indeterminate_valuation")
    ]


def test_the_same_run_in_the_views_own_currency_completes() -> None:
    """Control: only the currency differs, so the USD book still completes."""
    artifacts = eng._run(_realized_engine(code="USD"))

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.committed_fill_count == 1
    assert artifacts.final_state.net_asset_value == Decimal("10200")


@pytest.mark.parametrize("field_name", ["open", "close"])
def test_both_realized_price_reads_refuse_another_book_currency(
    field_name: str,
) -> None:
    """The open fill and the close mark each read through the currency guard.

    A EUR book holds no position a USD fill did not buy, so a run halts at the
    open before any close mark reads a held price. The close read is therefore
    driven directly, on the same engine.
    """
    engine = _realized_engine(code="EUR")
    session = eng._session(eng.DAY_1)
    read = engine._open_price if field_name == "open" else engine._mark_price

    with pytest.raises(IndeterminateValuationError) as refused:
        read(eng.SEC_A, session)

    assert str(refused.value) == _refusal(field_name, eng.DAY_1, "EUR")


def test_a_eur_dividend_on_a_usd_priced_security_never_completes() -> None:
    """Probe p1: no NAV sums EUR cash with USD marks.

    Before issue 142 this run settled the EUR dividend and ended COMPLETE with
    a NAV of 10205, EUR cash plus USD marks.
    """
    artifacts = eng._run(_realized_engine(code="EUR", outcomes=(_dividend("EUR"),)))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _refusal("open", eng.DAY_2, "EUR")
    assert artifacts.result.metrics.committed_fill_count == 0
    assert artifacts.final_state.settled_claim_ids == ()
    assert artifacts.final_state.pending_cash_claims == ()
    assert artifacts.final_state.net_asset_value == Decimal("10000")


def test_a_dividend_in_the_views_own_currency_still_settles() -> None:
    """Control: the same dividend and views in USD settle into a COMPLETE run."""
    artifacts = eng._run(_realized_engine(code="USD", outcomes=(_dividend("USD"),)))

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert len(artifacts.final_state.settled_claim_ids) == 1
    assert artifacts.final_state.cash_balance == Decimal("9005")
    assert artifacts.final_state.net_asset_value == Decimal("10205")


FOREIGN_PROFILE = "f" * 64


def _foreign_profile_view(day: date) -> DerivedObservationViewV1:
    """A source-basis view citing an observation profile M1d never pinned."""
    genuine = eng._accounting_view(eng.SEC_A, day)
    observation = genuine.query.observation.model_copy(
        update={"profile_hash": FOREIGN_PROFILE}
    )
    open_price, close_price = eng.PRICES[eng.SEC_A][day]
    return eng._restated_view(
        role="outcome",
        observation=observation,
        security_id=eng.SEC_A,
        listing_id=eng.LISTING_A,
        source_day=day,
        open_price=open_price,
        close_price=close_price,
    )


def _foreign_profile_refusal(day: date) -> str:
    return (
        f"accounting view for security {eng.SEC_A} on XNYS {day.isoformat()} "
        f"cites observation profile {FOREIGN_PROFILE}, which pins no price "
        "currency"
    )


def test_a_view_citing_an_unpinned_profile_names_no_currency() -> None:
    view = _foreign_profile_view(eng.DAY_2)

    with pytest.raises(IndeterminateValuationError) as refused:
        accounting_view_currency(view)

    assert str(refused.value) == _foreign_profile_refusal(eng.DAY_2)


def test_a_realized_run_over_an_unpinned_profile_halts_indeterminate() -> None:
    """A price whose currency no evidence states fails closed, even in USD."""
    views = tuple(_foreign_profile_view(day) for day in eng.DAYS)
    artifacts = eng._run(_realized_engine(code="USD", accounting_views=views))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _foreign_profile_refusal(eng.DAY_2)
    assert artifacts.result.metrics.committed_fill_count == 0


# --- D2: evidence order cannot change a result under one identity -----------


def _termination(
    boundary: TemporalBoundaryClaimV1, suffix: int
) -> ListingTerminationVersionV1:
    return ListingTerminationVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=eng.LISTING_A,
        reason=ListingTerminationReason.EXCHANGE_DELISTING,
        source_reason_code=None,
        source_reason_text=None,
        last_regular_trade_time=boundary,
        effective_time=boundary,
        successor_relationship_ids=(),
        outcome_evidence_status=OutcomeEvidenceStatus.UNKNOWN,
    )


def _probe_terminations() -> tuple[
    ListingTerminationVersionV1, ListingTerminationVersionV1
]:
    """Probe p1: one reached termination, and one of unknown time."""
    reached = _termination(
        boundary_at(datetime.combine(eng.DAY_0, time(12, 0), tzinfo=UTC), 901), 901
    )
    unknown = TemporalBoundaryClaimV1(
        schema_version="1",
        shape=BoundaryShape.UNKNOWN,
        lower_bound=None,
        upper_bound=None,
        source_precision=SourcePrecision.UNKNOWN,
        source_time_label=None,
        source_timezone=None,
        evidence_reference=reached.effective_time.evidence_reference,
    )
    return reached, _termination(unknown, 911)


def test_one_run_identity_gives_one_result_whatever_the_evidence_order() -> None:
    """Probe p1: both orders share one identity, so they share one result.

    Before issue 142 the AB order halted on the reached termination and the
    BA order on the ambiguous one: one run identity, two result hashes.
    """
    reached, ambiguous = _probe_terminations()
    runs = []
    for records in ((reached, ambiguous), (ambiguous, reached)):
        engine = eng._engine(
            evidence=SessionEvaluatorEvidence(
                listing_role_records=eng.ROLE_RECORDS,
                listing_termination_records=records,
            )
        )
        runs.append(eng._run(engine))
    first, second = runs

    assert first.result.run_identity == second.result.run_identity
    assert first.result.classification is EvaluationClassification.INDETERMINATE
    assert first.result.halt_reason == second.result.halt_reason
    assert first.trace.trace_hash == second.trace.trace_hash
    assert first.result.result_hash == second.result.result_hash


def _lifecycle(
    kind: ListingLifecycleEventKind, at: datetime, suffix: int
) -> ListingLifecycleVersionV1:
    return ListingLifecycleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        listing_id=eng.LISTING_A,
        event_kind=kind,
        effective_time=boundary_at(at, suffix),
        related_listing_id=None,
    )


def _two_of_every_collection() -> dict[str, tuple[Any, Any]]:
    """Two distinct genuine members of every evaluator evidence collection."""
    _, share_effect, _ = ca._split_case(
        numerator="1",
        denominator="2",
        treatment=ca._treatment("round_nearest", "nearest half_up"),
        suffix=140,
    )
    due_bill_terms, _, _ = ca._due_bill_terms()
    reconstructed = tuple(scheduled_session_case(day)[0] for day in (JAN5, JAN6))
    requests = exploratory_replay_of(reconstructed).requests
    assert len(requests) == 2
    return {
        "listing_role_records": eng.ROLE_RECORDS,
        "listing_termination_records": _probe_terminations(),
        "listing_lifecycle_records": (
            _lifecycle(
                ListingLifecycleEventKind.SUSPENDED,
                datetime(2025, 6, 2, 14, 30, tzinfo=UTC),
                941,
            ),
            _lifecycle(
                ListingLifecycleEventKind.RESUMED,
                datetime(2025, 6, 3, 14, 30, tzinfo=UTC),
                942,
            ),
        ),
        "economic_outcomes": (
            ca._dividend_case(suffix=800)[2],
            ca._dividend_case(suffix=820)[2],
        ),
        "tie_breaking_rules": (
            ca._tie_rule(effect=share_effect, tie_break="half_up"),
            ca._tie_rule(effect=share_effect, tie_break="half_even"),
        ),
        "due_bill_rules": (
            ca._due_bill_rule(due_bill_terms, entitlement=ca.ENTITLED_DAY),
            ca._due_bill_rule(
                due_bill_terms, entitlement=ca.ENTITLED_DAY, source_id="synthetic-b"
            ),
        ),
        "cash_in_lieu_rates": (
            ca._cash_in_lieu_rate(effect=share_effect, rate="4"),
            ca._cash_in_lieu_rate(effect=share_effect, rate="1"),
        ),
        "replay_requests": (requests[0], requests[1]),
    }


def _request_key(request: tuple[Any, Any]) -> str:
    """The key the evidence hash identifies a replay request by."""
    query, context = request
    return content_hash({"query": query, "context": m1d_context_hash(context)})


def _held_keys(evidence: SessionEvaluatorEvidence, name: str) -> list[str]:
    if name == "replay_requests":
        replay = evidence.exploratory_reconstruction_replay
        assert replay is not None
        return [_request_key(item) for item in replay.requests]
    return [content_hash(item) for item in getattr(evidence, name)]


def test_the_engine_holds_every_evidence_collection_in_content_hash_order() -> None:
    """Each collection the evidence hash sorts is held sorted the same way.

    The two orders of every collection rebuild into one evidence value, so no
    consumer can see the caller's order.
    """
    members = _two_of_every_collection()
    tuple_fields = {
        item.name
        for item in dataclasses.fields(SessionEvaluatorEvidence)
        if item.default == ()
    }
    assert set(members) == tuple_fields | {"replay_requests"}

    def evidence(order: int) -> SessionEvaluatorEvidence:
        chosen: dict[str, Any] = {name: pair[::order] for name, pair in members.items()}
        requests = chosen.pop("replay_requests")
        return SessionEvaluatorEvidence(
            **chosen,
            exploratory_reconstruction_replay=ExploratoryReconstructionReplay(
                policy=make_policy(), requests=requests
            ),
        )

    forward = _revalidated_evidence(evidence(1))
    backward = _revalidated_evidence(evidence(-1))
    for name in members:
        held = _held_keys(forward, name)
        assert len(set(held)) == 2, name
        assert held == sorted(held), name
        assert _held_keys(backward, name) == held, name


def _evidence_with(name: str, members: tuple[Any, ...]) -> SessionEvaluatorEvidence:
    """Evaluator evidence carrying ``members`` as the collection ``name``."""
    if name == "replay_requests":
        return SessionEvaluatorEvidence(
            exploratory_reconstruction_replay=ExploratoryReconstructionReplay(
                policy=make_policy(), requests=members
            )
        )
    return SessionEvaluatorEvidence(**cast(dict[str, Any], {name: members}))


def test_duplicate_evidence_members_are_kept_in_content_hash_order() -> None:
    """The evidence hash keeps a repeated member, so the held order keeps it too.

    Sorting by content hash must not also deduplicate: a collection handed a
    member twice is held with both copies, in the one canonical order.
    """
    for name, (first, second) in _two_of_every_collection().items():
        orders = ((first, second, first), (first, first, second))
        held = [
            _held_keys(_revalidated_evidence(_evidence_with(name, o)), name)
            for o in orders
        ]
        assert len(held[0]) == 3, name
        assert held[0] == sorted(held[0]), name
        assert held[1] == held[0], name
        assert len(set(held[0])) == 2, name


def test_replay_requests_are_ordered_by_query_and_context_together() -> None:
    """A request's key is its query and its M1d context hash, not either alone.

    Two requests sharing a query, or sharing a context, still get one order
    whatever order they are handed in. Keyed by the shared half alone, the
    sort would tie and keep the caller's order.
    """
    first, second = _two_of_every_collection()["replay_requests"]
    (query_a, context_a), (query_b, context_b) = first, second
    assert query_a != query_b
    assert m1d_context_hash(context_a) != m1d_context_hash(context_b)
    shared_query = ((query_a, context_a), (query_a, context_b))
    shared_context = ((query_a, context_a), (query_b, context_a))
    for pair in (shared_query, shared_context):
        held = [
            _held_keys(
                _revalidated_evidence(_evidence_with("replay_requests", order)),
                "replay_requests",
            )
            for order in (pair, pair[::-1])
        ]
        assert len(set(held[0])) == 2
        assert held[0] == sorted(held[0])
        assert held[1] == held[0]


# --- D3: a result binds its admission's bundle to its identity's bundle -----


def _forged_identity(genuine: Any) -> EvaluationRunIdentityV1:
    """Probe p2: the genuine identity renamed onto another bundle and resealed."""
    other_bundle = eng._bundle(days=eng.DAYS[:3])
    assert other_bundle.bundle_hash != genuine.result.admission.input_bundle_hash
    draft = EvaluationRunIdentityV1.model_construct(
        **(
            dict(genuine.result.run_identity)
            | {"bundle_hash": other_bundle.bundle_hash}
        )
    )
    return EvaluationRunIdentityV1.model_validate(
        dict(draft) | {"run_identity_hash": evaluation_run_identity_hash(draft)}
    )


def _resealed(
    genuine: Any, identity: EvaluationRunIdentityV1
) -> ExploratoryEvaluationResultV1:
    """The genuine result under ``identity``, resealed but never validated."""
    unsealed = ExploratoryEvaluationResultV1.model_construct(
        **(dict(genuine.result) | {"run_identity": identity})
    )
    return ExploratoryEvaluationResultV1.model_construct(
        **(dict(unsealed) | {"result_hash": evaluation_result_hash(unsealed)})
    )


RESULT_BUNDLE_REFUSAL = r"^1 validation error for ExploratoryEvaluationResultV1\n"


def _artifact_bundle_refusal(pair: type[Any]) -> str:
    """The artifact pair's refusal, for whichever artifacts version runs return."""
    return rf"^1 validation error for {pair.__name__}\nresult\.exploratory\n"


RESULT_BUNDLE_CAUSE = "result run identity must bind the bundle its admission admits"


def test_a_result_refuses_an_identity_naming_another_bundle() -> None:
    """Probe p2: before issue 142 this result validated."""
    genuine = eng._run(eng._engine())
    forged = _resealed(genuine, _forged_identity(genuine))

    with pytest.raises(ValidationError, match=RESULT_BUNDLE_REFUSAL) as refused:
        ExploratoryEvaluationResultV1.model_validate(dict(forged))

    assert RESULT_BUNDLE_CAUSE in str(refused.value)


@pytest.mark.parametrize("handed", ["unvalidated", "rewritten-after-validation"])
def test_run_artifacts_refuse_a_result_naming_another_bundle(handed: str) -> None:
    """Artifact validation revalidates the result it pairs, so it refuses too.

    Probe p2 validated these artifacts. The result is handed in either never
    validated, or validated genuinely and then rewritten in place.
    """
    genuine = eng._run(eng._engine())
    identity = _forged_identity(genuine)
    if handed == "unvalidated":
        result = _resealed(genuine, identity)
    else:
        result = ExploratoryEvaluationResultV1.model_validate(dict(genuine.result))
        resealed = _resealed(genuine, identity)
        object.__setattr__(result, "run_identity", identity)
        object.__setattr__(result, "result_hash", resealed.result_hash)

    # The pair of whichever artifacts version the engine returns.
    pair = type(genuine)
    with pytest.raises(
        ValidationError, match=_artifact_bundle_refusal(pair)
    ) as refused:
        pair.model_validate(
            {
                "result": result,
                "trace": genuine.trace,
                "final_state": genuine.final_state,
            }
        )

    assert RESULT_BUNDLE_CAUSE in str(refused.value)


class _StandIn:
    """Probe p2's stand-in engine: the genuine engine returning ``returned``."""

    def __init__(self, inner: SessionEvaluatorEngine, returned: object) -> None:
        self._inner = inner
        self._returned = returned

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def run(self, **_: object) -> Any:
        return self._returned


def test_the_runner_records_nothing_for_a_result_naming_another_bundle() -> None:
    """Probe p2: before issue 142 the runner recorded a COMPLETED row."""
    engine = eng._engine()
    genuine = eng._run(engine)
    identity = _forged_identity(genuine)
    returned = type(genuine).model_construct(
        schema_version=genuine.schema_version,
        result=_resealed(genuine, identity),
        trace=genuine.trace,
        final_state=genuine.final_state,
    )
    with TemporaryDirectory() as folder:
        ledger = SQLiteLedger(Path(folder) / "audit.sqlite3")
        context = dataclasses.replace(
            run_support._context(
                cast(SessionEvaluatorEngine, _StandIn(engine, returned)),
                ledger=ledger,
            ),
            run_identity=identity,
        )
        honest = run_support._specification()
        specification = honest.model_copy(
            update={
                "dataset_reference": honest.dataset_reference.model_copy(
                    update={"content_hash": identity.bundle_hash}
                )
            }
        )

        with pytest.raises(ValidationError) as refused:
            execute_experiment_run(specification, context)

        assert RESULT_BUNDLE_CAUSE in str(refused.value)
        assert ledger.verified_events() == ()


def test_the_runner_refuses_a_nested_rewrite_the_pair_does_not_see() -> None:
    """Review F2 of PR 145: the runner's canonical JSON rebuild is the defense.

    A result's admission rewritten in place under a resealed result hash
    passes the artifact pair, which re-runs only the result's own checks. The
    runner rebuilds what an engine returns through canonical JSON, so the
    admission's own hash check runs, and nothing is recorded.
    """
    engine = eng._engine()
    returned = copy.deepcopy(eng._run(engine))
    assert returned.result.admission is not engine.admission
    object.__setattr__(
        returned.result.admission, "acknowledged_limitations", ("forged",)
    )
    object.__setattr__(
        returned.result, "result_hash", evaluation_result_hash(returned.result)
    )
    type(returned).model_validate(dict(returned))

    with TemporaryDirectory() as folder:
        ledger = SQLiteLedger(Path(folder) / "audit.sqlite3")
        context = run_support._context(
            cast(SessionEvaluatorEngine, _StandIn(engine, returned)), ledger=ledger
        )

        with pytest.raises(
            ValidationError, match=r"result\.exploratory\.admission\n"
        ) as refused:
            execute_experiment_run(run_support._specification(), context)

        assert "admission hash mismatch" in str(refused.value)
        assert ledger.verified_events() == ()


# --- D4: canonical money refuses, never rounds, a wider input -----------------

#: 37 significant digits, from probe p3.
WIDE = Decimal("1.000000000000000000000000000000000049")
#: 39 significant digits, from probe p3.
WIDE_CASH = Decimal("123456789012345678901234567890.123456789")
#: Exactly the 34 digits the pinned portfolio context holds.
FULL = Decimal("1234567890123456789012345678901.234")
PRECISION_REFUSAL = "cannot be held exactly in the pinned 34-digit portfolio context"


@pytest.mark.parametrize(
    "value",
    # ``copy_negate`` is exact; unary minus would round under the ambient
    # 28-digit context before the value ever reached ``canonical_money``.
    [WIDE, WIDE.copy_negate(), WIDE_CASH, WIDE_CASH.copy_negate()],
    ids=["wide", "negative-wide", "wide-cash", "negative-wide-cash"],
)
def test_canonical_money_refuses_more_significant_digits_than_the_context(
    value: Decimal,
) -> None:
    """Probe p3: before issue 142 the 37-digit value came back as ``1``."""
    with pytest.raises(ValueError, match=PRECISION_REFUSAL):
        canonical_money(value)


def test_canonical_money_keeps_a_value_the_context_holds_exactly() -> None:
    """Controls: 34 significant digits, and zeros beyond them, are exact."""
    assert str(canonical_money(FULL)) == "1234567890123456789012345678901.234"
    assert str(canonical_money(FULL.copy_negate())) == (
        "-1234567890123456789012345678901.234"
    )
    assert str(canonical_money(Decimal("1." + "0" * 40))) == "1"
    assert str(canonical_money(Decimal("0E-50"))) == "0"


def _state(cash: Decimal) -> PortfolioStateV1:
    return PortfolioStateV1(
        lane="exploratory",
        admission_hash=ca.EXPLORATORY.admission_hash,
        session_key=ca._key(),
        cash_balance=cash,
        holdings=(),
        pending_cash_claims=(),
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=cash,
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )


def test_money_fields_refuse_a_wider_value_at_validation() -> None:
    """Probe p3: cash, a fill price and a close price were each rounded."""
    with pytest.raises(ValidationError, match=PRECISION_REFUSAL):
        _state(WIDE_CASH)
    with pytest.raises(ValidationError, match=PRECISION_REFUSAL):
        PortfolioFillV1(security_id=ca.SEC_A, side="buy", quantity=1, fill_price=WIDE)
    with pytest.raises(ValidationError, match=PRECISION_REFUSAL):
        MarkPriceV1(
            security_id=ca.SEC_A,
            close_price=WIDE,
            evidence=MarkEvidenceV1(grade="exploratory", evidence_hash="d" * 64),
        )
    genuine = PortfolioFillV1(
        security_id=ca.SEC_A, side="buy", quantity=1, fill_price=FULL
    )
    with pytest.raises(ValidationError, match=PRECISION_REFUSAL):
        PortfolioFillV1.model_validate_json(
            genuine.model_dump_json().replace(str(FULL), str(WIDE))
        )


def test_money_fields_keep_a_full_width_value_exactly() -> None:
    """Control: a 34-digit amount validates without changing."""
    assert _state(FULL).cash_balance == FULL
    fill = PortfolioFillV1(
        security_id=ca.SEC_A, side="buy", quantity=1, fill_price=FULL
    )
    assert fill.fill_price == FULL


# --- PR 145 review F1: a value the book cannot hold halts INDETERMINATE ------
#
# D4 refuses a wide value where it is first held as money. The review found
# three reads that reached that refusal only as an exception out of the run,
# so the M0 row recorded FAILED, or never reached it: an exact per-share cash
# amount wider than the context, a wide close price, and a wide open price,
# which fill arithmetic silently rounded. A value the book cannot hold is
# missing evidence for the book, as a price in another currency is (D1), so
# each now halts the run INDETERMINATE where it is read.

#: 35 significant digits, one more than the pinned portfolio context holds.
WIDE_PRICE = "100." + "0" * 31 + "1"
#: A 31-digit M1c amount per 1024 shares: an exact 38-digit cash per share.
WIDE_AMOUNT = "1234567890123456789012345678901"


def _wide_refusal(what: str, value: object) -> str:
    return (
        f"{what} cannot be held exactly in the pinned 34-digit portfolio "
        f"context: {value}"
    )


def _views_with(
    day: date, *, open_price: str | None = None, close_price: str | None = None
) -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A's genuine accounting views, with ``day``'s given prices replaced."""
    return tuple(
        eng._accounting_view(
            eng.SEC_A,
            item,
            open_price=open_price if item == day else None,
            close_price=close_price if item == day else None,
        )
        for item in eng.DAYS
    )


def _fill_sessions(artifacts: Any) -> list[date]:
    """The session of each traced fill; a halted session's fill is traced only."""
    return [
        event.session_key.local_date
        for event in artifacts.trace.events
        if isinstance(event, FillTraceEventV1)
    ]


def _halt_phases(artifacts: Any) -> list[tuple[str, str]]:
    return [
        (event.phase.value, event.cause_kind)
        for event in artifacts.trace.events
        if isinstance(event, IndeterminateCauseTraceEventV1)
    ]


def test_the_wide_values_are_one_digit_or_more_past_the_context() -> None:
    """The fixtures are non-vacuous: each needs more than 34 digits."""
    assert len(WIDE_PRICE.replace(".", "")) == 35
    assert len(WIDE_AMOUNT) == 31
    per_share = str(Fraction(int(WIDE_AMOUNT), 1024).numerator * 5**10)
    assert len(per_share) == 38
    assert len(WIDE_INITIAL_CASH.replace(".", "")) == 35


def test_exact_decimal_refuses_a_cash_amount_wider_than_the_context() -> None:
    amount = Fraction(int(WIDE_AMOUNT), 1024)

    with pytest.raises(IndeterminateValuationError) as refused:
        exact_decimal(amount)

    assert str(refused.value) == (
        f"cash amount {WIDE_AMOUNT}/1024 cannot be held exactly in the pinned "
        "34-digit portfolio context"
    )


def test_exact_decimal_keeps_an_amount_the_context_holds_exactly() -> None:
    """Controls: 34 significant digits, and zeros beyond them, convert exactly."""
    assert exact_decimal(Fraction(FULL)) == FULL
    assert str(exact_decimal(Fraction(FULL))) == str(FULL)
    assert exact_decimal(Fraction(10**40)) == Decimal(10**40)
    assert exact_decimal(Fraction(1, 1024)) == Decimal("0.0009765625")


def test_a_computed_cash_amount_wider_than_the_context_halts_indeterminate() -> None:
    """The review probe: a 38-digit cash per share recorded FAILED before."""
    wide = _dividend_of(
        ca._cash(
            amount=WIDE_AMOUNT,
            component_id="d",
            predecessor=eng.SEC_A,
            numerator="1024",
        )
    )

    artifacts = eng._run(_realized_engine(code="USD", outcomes=(wide,)))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == (
        f"cash amount {WIDE_AMOUNT}/1024 cannot be held exactly in the pinned "
        "34-digit portfolio context"
    )
    assert _halt_phases(artifacts) == [("pre_open_effects", "indeterminate_valuation")]
    assert artifacts.final_state.pending_cash_claims == ()


def test_a_wide_realized_open_halts_before_it_fills() -> None:
    """Before this fix fill arithmetic rounded the open, and the run completed."""
    views = _views_with(eng.DAY_2, open_price=WIDE_PRICE)

    artifacts = eng._run(_realized_engine(code="USD", accounting_views=views))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _wide_refusal(
        f"accounting open price for security {eng.SEC_A} on XNYS "
        f"{eng.DAY_2.isoformat()}",
        WIDE_PRICE,
    )
    assert artifacts.result.metrics.committed_fill_count == 0
    assert _halt_phases(artifacts) == [("open_execution", "indeterminate_valuation")]


def test_a_wide_realized_close_halts_at_the_mark() -> None:
    """Before this fix the mark raised out of the run and the M0 row FAILED."""
    views = _views_with(eng.DAY_2, close_price=WIDE_PRICE)

    artifacts = eng._run(_realized_engine(code="USD", accounting_views=views))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _wide_refusal(
        f"accounting close price for security {eng.SEC_A} on XNYS "
        f"{eng.DAY_2.isoformat()}",
        WIDE_PRICE,
    )
    assert _fill_sessions(artifacts) == [eng.DAY_2]
    assert _halt_phases(artifacts) == [("close_mark", "indeterminate_valuation")]


def test_a_wide_price_no_fill_or_mark_reads_changes_nothing() -> None:
    """Control: the refusal is at first use, so an unread wide price is inert.

    Nothing is held on 2026-01-06 and nothing fills then, so no read reaches
    that session's close, and the run completes exactly as the genuine one.
    """
    genuine = eng._run(_realized_engine(code="USD"))
    views = _views_with(eng.DAY_1, close_price=WIDE_PRICE)

    artifacts = eng._run(_realized_engine(code="USD", accounting_views=views))

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics == genuine.result.metrics
    held, expected = artifacts.final_state, genuine.final_state
    assert held.holdings == expected.holdings
    assert held.cash_balance == expected.cash_balance
    assert held.net_asset_value == expected.net_asset_value == Decimal("10200")


def test_a_wide_reconstructed_close_halts_at_the_mark() -> None:
    """The reconstructed lane's twin: a wide close also raised out of the run."""
    bundle = bundle_of(
        (scheduled_session_case(JAN5), scheduled_session_case(JAN6, close=WIDE_PRICE))
    )

    artifacts = run_engine(
        reconstructed_engine(bundle), ReconstructedTargetStrategy({JAN5: ((SEC, 1),)})
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _wide_refusal(
        f"exploratory reconstructed close price for security {SEC} on XNYS "
        f"{JAN6.isoformat()}",
        WIDE_PRICE,
    )
    assert _fill_sessions(artifacts) == [JAN6]
    assert _halt_phases(artifacts) == [("close_mark", "indeterminate_valuation")]


WIDE_INITIAL_CASH = "1234567890123456789012345678901234.5"
INITIAL_CASH_REFUSAL = (
    f"initial_cash {WIDE_INITIAL_CASH} cannot be held exactly in the pinned "
    "34-digit portfolio context"
)


def _unvalidated_protocol(cash: str) -> EvaluationProtocolV1:
    """The engine tests' protocol with ``cash``, sealed but never validated."""
    draft = EvaluationProtocolV1.model_construct(
        **(dict(eng._protocol()) | {"initial_cash": Decimal(cash)})
    )
    return EvaluationProtocolV1.model_construct(
        **(dict(draft) | {"protocol_hash": evaluation_protocol_hash(draft)})
    )


def test_a_protocol_refuses_initial_cash_wider_than_the_context() -> None:
    """Before this fix it validated, and the run failed at its first book."""
    wide = _unvalidated_protocol(WIDE_INITIAL_CASH)

    with pytest.raises(ValidationError, match=INITIAL_CASH_REFUSAL):
        eng._protocol(cash=WIDE_INITIAL_CASH)
    with pytest.raises(ValidationError, match=INITIAL_CASH_REFUSAL):
        EvaluationProtocolV1.model_validate(wide.model_dump())
    with pytest.raises(ValidationError, match=INITIAL_CASH_REFUSAL):
        EvaluationProtocolV1.model_validate_json(wide.model_dump_json())
    with pytest.raises(ValidationError, match=INITIAL_CASH_REFUSAL):
        eng._engine(protocol=wide)


def test_a_protocol_keeps_full_width_initial_cash() -> None:
    """Control: 34 significant digits are held exactly."""
    full = _unvalidated_protocol(str(FULL))
    assert EvaluationProtocolV1.model_validate(full.model_dump()).initial_cash == FULL
    assert eng._protocol(cash=str(FULL)).initial_cash == FULL


# --- Round-2 review of PR 145: the remaining reads and the pathological ends --


def _wide_open_reconstruction(
    session_date: date,
) -> tuple[ExploratoryReconstructedSessionObservationV1, EvaluationSessionV1]:
    """A genuinely reconstructed session whose source bar opens at WIDE_PRICE."""
    harness = ObservationHarness(
        session_date=session_date,
        security_id=SEC,
        listing_id=LISTING,
        close="100.000",
        available_at=f"{session_date.isoformat()}T22:30:00Z",
        claimed_close_utc=(20, 55),
    )
    harness.use_numeric_values(
        open_value=WIDE_PRICE, high="101", low="99", close="100.000", volume="1000"
    )
    harness.attach_sessions(schedule_state="regular", realized_outcome="missing")
    horizon = f"{(session_date + timedelta(days=1)).isoformat()}T00:00:00Z"
    query = harness.outcome(
        economic_horizon=horizon,
        evidence_vintage_cutoff=horizon,
        session_date=session_date.isoformat(),
    )
    observation = build_exploratory_reconstructed_session_observation(
        query, harness.context, cohort_of((SEC,)), make_policy()
    )
    # Registered as the support module's own genuine cases are, so the
    # engine's replay re-derives this reconstruction from its source.
    eds._SOURCE_REQUESTS[observation.reconstruction_hash] = (query, harness.context)
    clock = build_scheduled_reconstruction_clock((query,), harness.context)
    return observation, clock.sessions[0]


def _wide_open_reconstructed_engine(code: str) -> SessionEvaluatorEngine:
    """The reconstructed lane over a wide 2026-01-06 open, in the given book."""
    bundle = bundle_of((scheduled_session_case(JAN5), _wide_open_reconstruction(JAN6)))
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=exploratory_admission(bundle),
        protocol=eng._protocol(warmup=1),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            exploratory_cohort=cohort_of(),
            exploratory_reconstruction_replay=exploratory_replay_of(
                bundle.exploratory_reconstructed_observations
            ),
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=code,
    )


def test_a_wide_reconstructed_open_halts_before_it_fills() -> None:
    """Round-2 review: an open-only reconstructed check went untested."""
    artifacts = run_engine(
        _wide_open_reconstructed_engine("USD"),
        ReconstructedTargetStrategy({JAN5: ((SEC, 1),)}),
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason == _wide_refusal(
        f"exploratory reconstructed open price for security {SEC} on XNYS "
        f"{JAN6.isoformat()}",
        WIDE_PRICE,
    )
    assert _fill_sessions(artifacts) == []
    assert _halt_phases(artifacts) == [("open_execution", "indeterminate_valuation")]


def test_the_currency_is_checked_before_the_width_in_both_lanes() -> None:
    """A price in another currency is refused for its currency, whatever its width.

    Spec 11, the issue 142 D4 amendment: the width check runs after the
    currency check, so the halt names the more basic defect.
    """
    realized = eng._run(
        _realized_engine(
            code="EUR", accounting_views=_views_with(eng.DAY_2, open_price=WIDE_PRICE)
        )
    )
    reconstructed = run_engine(
        _wide_open_reconstructed_engine("EUR"),
        ReconstructedTargetStrategy({JAN5: ((SEC, 1),)}),
    )

    assert realized.result.halt_reason == _refusal("open", eng.DAY_2, "EUR")
    assert reconstructed.result.halt_reason == (
        f"exploratory reconstructed open price for security {SEC} on XNYS "
        f"{JAN6.isoformat()} is in USD, not the book currency EUR"
    )


COST_FIELDS = (
    "commission_per_share",
    "fixed_fee_per_order",
    "notional_fee_basis_points",
    "adverse_slippage_basis_points",
)
#: 35 significant digits, one more than the pinned portfolio context holds.
WIDE_COST = "1." + "0" * 33 + "1"


def _unvalidated_cost_model(field: str, value: str) -> EvaluationCostModelV1:
    """The engine tests' zero-cost model with one field, sealed, never validated."""
    draft = EvaluationCostModelV1.model_construct(
        **(dict(eng._cost_model()) | {field: Decimal(value)})
    )
    return EvaluationCostModelV1.model_construct(
        **(dict(draft) | {"cost_model_hash": evaluation_cost_model_hash(draft)})
    )


@pytest.mark.parametrize("field", COST_FIELDS)
def test_a_cost_model_refuses_a_parameter_wider_than_the_context(field: str) -> None:
    """Round-2 review: a wide cost was silently rounded by cost arithmetic."""
    assert len(WIDE_COST.replace(".", "")) == 35
    wide = _unvalidated_cost_model(field, WIDE_COST)
    refusal = (
        f"^1 validation error for EvaluationCostModelV1\n  Value error, {field} "
        f"{getattr(wide, field)} cannot be held exactly in the pinned 34-digit "
        "portfolio context"
    )

    with pytest.raises(ValidationError, match=refusal):
        EvaluationCostModelV1.model_validate(wide.model_dump())
    with pytest.raises(ValidationError, match=refusal):
        EvaluationCostModelV1.model_validate_json(wide.model_dump_json())
    with pytest.raises(ValidationError, match=refusal):
        eng._engine(cost_model=wide)


def test_a_cost_model_keeps_full_width_parameters() -> None:
    """Control: 34 significant digits, and zeros beyond them, are held exactly."""
    for field in COST_FIELDS:
        full = _unvalidated_cost_model(field, "0." + "0" * 40 + "1" * 34)
        rebuilt = EvaluationCostModelV1.model_validate(full.model_dump())
        assert getattr(rebuilt, field) == getattr(full, field)


def test_exact_decimal_refuses_by_counting_digits_before_it_renders() -> None:
    """Round-2 review: rendering 4300 digits raised ValueError out of the run.

    A cash amount per 2**6200 shares has 6200 decimal places. Its digits are
    counted arithmetically, so it is refused as a value the book cannot hold,
    never by CPython's integer-to-text conversion limit.
    """
    amount = Fraction(1, 2**6200)

    with pytest.raises(IndeterminateValuationError) as refused:
        exact_decimal(amount)

    assert str(refused.value).endswith(
        "cannot be held exactly in the pinned 34-digit portfolio context"
    )
    assert exact_decimal(Fraction(3 * 10**40, 2**10)) == Decimal(3 * 10**40) / 1024


#: A finite value whose rounding to the context overflows its exponent range.
OVERFLOWING = Decimal("1E+1000000")


def test_a_value_past_the_exponent_range_does_not_fit_and_never_raises() -> None:
    """Round-2 review: ``decimal.Overflow`` escaped instead of an answer."""
    assert fits_portfolio_context(OVERFLOWING) is False
    assert fits_portfolio_context(OVERFLOWING.copy_negate()) is False
    with pytest.raises(ValueError, match=PRECISION_REFUSAL):
        canonical_money(OVERFLOWING)
    with pytest.raises(ValidationError, match="initial_cash 1E[+]1000000 cannot"):
        EvaluationProtocolV1.model_validate(
            _unvalidated_protocol(str(OVERFLOWING)).model_dump()
        )


def test_a_realized_open_past_the_exponent_range_halts_indeterminate() -> None:
    """Before this it raised Overflow out of the run and the M0 row FAILED."""
    views = _views_with(eng.DAY_2, open_price=str(OVERFLOWING))

    artifacts = eng._run(_realized_engine(code="USD", accounting_views=views))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert _halt_phases(artifacts) == [("open_execution", "indeterminate_valuation")]


@pytest.mark.parametrize(
    ("denominator", "problem"),
    (
        (1, "cannot be held exactly in the pinned 34-digit portfolio context"),
        (3, "is not exactly representable as a decimal"),
    ),
    ids=("wide", "non-terminating"),
)
def test_a_refusal_names_a_ratio_past_the_integer_conversion_limit(
    denominator: int, problem: str
) -> None:
    """Follow-up review: the refusal wording itself must never hit the limit.

    A 5000-digit numerator is past CPython's 4300-digit integer conversion
    limit, so spelling it with ``str`` would raise ``ValueError`` out of the
    run instead of the refusal.
    """
    # Built arithmetically: parsing 5000 digits would itself hit the limit.
    numerator = 7 * (10**5000 - 1) // 9

    with pytest.raises(IndeterminateValuationError) as refused:
        exact_decimal(Fraction(numerator, denominator))

    assert str(refused.value) == f"cash amount {'7' * 5000}/{denominator} {problem}"


def test_a_cost_model_keeps_zeros_beyond_its_significant_digits() -> None:
    """Control: zeros past the significant digits are not significant."""
    for field in COST_FIELDS:
        value = "0.005" + "0" * 40
        model = _unvalidated_cost_model(field, value)
        rebuilt = EvaluationCostModelV1.model_validate(model.model_dump())
        assert getattr(rebuilt, field) == Decimal(value)
