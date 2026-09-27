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

import dataclasses
import sys
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

_SUPPORT = Path(__file__).resolve().parents[1]
for folder in (_SUPPORT / "unit", _SUPPORT / "integration"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support
from exploratory_decision_test_support import JAN5, JAN6, scheduled_session_case
from exploratory_decision_test_support import replay_of as exploratory_replay_of
from pydantic import ValidationError
from session_test_support import boundary_at, revision
from test_evaluator_reconstruction import make_policy

from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV1,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_corporate_actions import SecurityEconomicOutcomeV1
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioFillV1,
    PortfolioStateV1,
    canonical_money,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
    ExploratoryEvaluationResultV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_trace import IndeterminateCauseTraceEventV1
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.securities import (
    ListingLifecycleEventKind,
    ListingLifecycleVersionV1,
    ListingTerminationReason,
    ListingTerminationVersionV1,
    OutcomeEvidenceStatus,
)
from drift.domain.temporal import SourcePrecision
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    _revalidated_evidence,
    accounting_view_currency,
)
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay
from drift.ledger.sqlite import SQLiteLedger
from drift.markets.observation_validation import m1d_context_hash
from drift.serialization.canonical import content_hash

# --- D1: the realized lane binds its price currency to the book --------------


def _at(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _dividend(code: str) -> SecurityEconomicOutcomeV1:
    """The probe's dividend on SEC_A, ex and payable on DAY_3, in ``code``."""
    cash = ca._cash(amount="0.5", component_id="d", predecessor=eng.SEC_A, code=code)
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


# --- D3: a result binds its admission's bundle to its identity's bundle -----


def _forged_identity(genuine: EvaluationRunArtifactsV1) -> EvaluationRunIdentityV1:
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
    genuine: EvaluationRunArtifactsV1, identity: EvaluationRunIdentityV1
) -> ExploratoryEvaluationResultV1:
    """The genuine result under ``identity``, resealed but never validated."""
    unsealed = ExploratoryEvaluationResultV1.model_construct(
        **(dict(genuine.result) | {"run_identity": identity})
    )
    return ExploratoryEvaluationResultV1.model_construct(
        **(dict(unsealed) | {"result_hash": evaluation_result_hash(unsealed)})
    )


RESULT_BUNDLE_REFUSAL = r"^1 validation error for ExploratoryEvaluationResultV1\n"
ARTIFACT_BUNDLE_REFUSAL = (
    r"^1 validation error for EvaluationRunArtifactsV1\nresult\.exploratory\n"
)
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

    with pytest.raises(ValidationError, match=ARTIFACT_BUNDLE_REFUSAL) as refused:
        EvaluationRunArtifactsV1.model_validate(
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
    returned = EvaluationRunArtifactsV1.model_construct(
        schema_version="1",
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
