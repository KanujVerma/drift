"""M2 adversarial acceptance: the versioned portfolio state (issues 49, 103, 105).

``PortfolioStateV2`` carries two facts ``PortfolioStateV1`` cannot: which
share-mutating economic effects a book has already absorbed (#49), and whether
each holding's cost basis is known (#103, #105). The runs below are end to end,
through ``SessionEvaluatorEngine``, on the shared engine fixture: ten SEC_A
shares bought at the session-2 open for 1000.00, a hold staged for session 3,
and one corporate action effective at the session-3 pre-open.

The run pins are the hash-impact record of the slice (the #80 precedent:
construction-additive, but hash-changing). A run with no spin-off, mixed
acquisition, aggregate-sale residual or continuing liquidation instalment on
an exposed security keeps its exact trace and result hashes, because position
digests are quantity-only and a known position view dumps exactly as before.
A run that exposes an indeterminate basis at a decision moves its decision
context hash, and so its trace and result hashes, by design.
"""

# ruff: noqa: E402

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
from pydantic import ValidationError

from drift.domain.economic_common import (
    ActionKind,
    EconomicComponentV1,
    EconomicDateFactV1,
    FractionTreatmentV1,
)
from drift.domain.economic_events import EconomicEffectVersionV1
from drift.domain.evaluator_corporate_actions import (
    CashInLieuRateV1,
    SecurityEconomicOutcomeV1,
)
from drift.domain.evaluator_portfolio import (
    EffectAlreadyAppliedError,
    PortfolioStateV1,
    PortfolioStateV2,
    SecurityHoldingV2,
    applied_economic_effect_id,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.normalization import DerivedObservationViewV1
from drift.evaluator.corporate_actions import CorporateActionProcessor
from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence

#: The session-3 pre-open of the shared engine clock.
ACTION_AT = "2026-01-08T00:00:00Z"


# ==========================================================================
# Scenario builders
# ==========================================================================


def _action(
    kind: ActionKind,
    *,
    suffix: int,
    components: tuple[EconomicComponentV1, ...],
    dates: tuple[EconomicDateFactV1, ...] = (),
    claim_status: str = "continuing",
    security_id: UUID = eng.SEC_A,
) -> tuple[EconomicEffectVersionV1, SecurityEconomicOutcomeV1]:
    """One occurred SEC_A effect at the session-3 pre-open, and its outcome."""
    terms = ca._terms(
        suffix=suffix,
        action_kind=kind,
        components=components,
        dates=dates,
        security_id=security_id,
    )
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=components,
        terms=terms,
        occurrence_id=f"issue-49-{suffix}",
        effective_at=ACTION_AT,
        security_id=security_id,
        claim_status=claim_status,
    )
    outcome = ca._outcome(
        security_id=security_id,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(kind,),
    )
    return effect, outcome


def _shares(
    *,
    numerator: str,
    denominator: str,
    meaning: str,
    recipient: UUID = eng.SEC_A,
    treatment: FractionTreatmentV1 | None = None,
) -> EconomicComponentV1:
    return ca._shares(
        numerator=numerator,
        denominator=denominator,
        component_id="action-shares",
        recipient=recipient,
        predecessor=eng.SEC_A,
        meaning=meaning,
        treatment=treatment,
    )


def _cash(amount: str, component_id: str) -> EconomicComponentV1:
    return ca._cash(amount=amount, component_id=component_id, predecessor=eng.SEC_A)


def _payable() -> tuple[EconomicDateFactV1, ...]:
    return (ca._date_fact("payable", ACTION_AT),)


def _run(
    outcome: SecurityEconomicOutcomeV1,
    views: tuple[DerivedObservationViewV1, ...],
    *,
    rates: tuple[CashInLieuRateV1, ...] = (),
    strategy: eng.FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV2:
    bundle = eng._bundle(
        accounting_views=views, economic_outcomes=(outcome.resolution,)
    )
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            economic_outcomes=(outcome,),
            cash_in_lieu_rates=rates,
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )
    return eng._run(engine, strategy)


def _views(
    *,
    session_3: tuple[str, str] | None = None,
    child: bool = False,
) -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A over sessions 0 to 3, re-priced at session 3 if asked, and SEC_B."""
    views = tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3])
    if session_3 is None:
        views += (eng._accounting_view(eng.SEC_A, eng.DAY_3),)
    else:
        views += (
            eng._accounting_view(
                eng.SEC_A,
                eng.DAY_3,
                open_price=session_3[0],
                close_price=session_3[1],
            ),
        )
    if child:
        views += (eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),)
    return views


def _pre_action_views_and_child() -> tuple[DerivedObservationViewV1, ...]:
    """SEC_A up to session 2, and SEC_B at session 3, for a holding SEC_A leaves."""
    return tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3]) + (
        eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),
    )


# --- runs whose basis stays known ------------------------------------------


def forward_split_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.FORWARD_SPLIT,
        suffix=4900,
        components=(
            _shares(
                numerator="2", denominator="1", meaning="resulting_per_predecessor"
            ),
        ),
    )
    return _run(outcome, _views(session_3=("55.00", "60.00")))


def stock_dividend_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.STOCK_DIVIDEND,
        suffix=4910,
        components=(
            _shares(
                numerator="1", denominator="10", meaning="additional_per_predecessor"
            ),
        ),
    )
    return _run(outcome, _views(session_3=("100.00", "109.10")))


def stock_acquisition_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.STOCK_ACQUISITION,
        suffix=4920,
        components=(
            _shares(
                numerator="3",
                denominator="2",
                meaning="resulting_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
        claim_status="converted",
    )
    return _run(outcome, _pre_action_views_and_child())


def extinguishing_liquidation_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.LIQUIDATION,
        suffix=4930,
        components=(_cash("150", "liquidation-cash"),),
        dates=_payable(),
        claim_status="extinguished",
    )
    return _run(outcome, _views())


def cash_acquisition_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.CASH_ACQUISITION,
        suffix=4940,
        components=(_cash("150", "acquisition-cash"),),
        dates=_payable(),
        claim_status="extinguished",
    )
    return _run(outcome, _views())


def cash_dividend_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.REGULAR_CASH_DIVIDEND,
        suffix=4950,
        components=(_cash("0.5", "dividend-cash"),),
        dates=(ca._date_fact("ex", ACTION_AT), *_payable()),
    )
    return _run(outcome, _views())


# --- runs that expose an indeterminate or relieved basis --------------------


def spinoff_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.SPINOFF,
        suffix=4960,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="additional_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
    )
    return _run(outcome, _views(child=True))


def continuing_instalment_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.LIQUIDATION,
        suffix=4970,
        components=(_cash("3", "liquidation-cash"),),
        dates=(ca._date_fact("ex", ACTION_AT), *_payable()),
    )
    return _run(outcome, _views())


def mixed_acquisition_run() -> EvaluationRunArtifactsV2:
    _, outcome = _action(
        ActionKind.MIXED_ACQUISITION,
        suffix=4980,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="resulting_per_predecessor",
                recipient=eng.SEC_B,
            ),
            _cash("5", "acquisition-cash"),
        ),
        dates=_payable(),
        claim_status="converted",
    )
    return _run(outcome, _pre_action_views_and_child())


def aggregate_sale_residual_run() -> EvaluationRunArtifactsV2:
    effect, outcome = _action(
        ActionKind.REVERSE_SPLIT,
        suffix=4990,
        components=(
            _shares(
                numerator="1",
                denominator="3",
                meaning="resulting_per_predecessor",
                treatment=ca._treatment("aggregate_sale_cash"),
            ),
        ),
        dates=_payable(),
    )
    rate = ca._cash_in_lieu_rate(effect=effect, component_id="action-shares", rate="3")
    return _run(outcome, _views(session_3=("330.00", "360.00")), rates=(rate,))


# ==========================================================================
# Hash-impact pins
# ==========================================================================

#: ``(classification, trace_hash, result_hash)`` of each run, taken at main
#: 5dd05cd before any V2 model existed. The V2 switch and the replay record
#: moved none of them. Each later move is recorded at its pin, with the only
#: leaves a field-by-field diff of the run's trace and result shows moving.
#: Issue 71 moves every pin once: its closed-world session coverage changes
#: the ``m1d-evidence-v1`` attestation and every bundle, so each run's bundle,
#: admission and run identity hashes, its decision-context and mark hashes,
#: and its trace and result hashes move. That diff of all ten runs shows no
#: other leaf moving and no classification changing.
RUN_PINS: dict[str, tuple[EvaluationClassification, str, str]] = {
    "forward-split": (
        EvaluationClassification.COMPLETE,
        "ca92a0393a8bf3638801737d5f5966ac80507e9ac63d8d363f2ac7abb5b310d0",
        "66a3c502f58902837762ddb90b7a72443de6416880dbc3a238629f93a6386b40",
    ),
    "stock-dividend": (
        EvaluationClassification.COMPLETE,
        "c0620796061923bc0bbcd26ef9339af1ac2c743a5645aa05377fae4386223165",
        "94bf0d98a88509386231c38d3f4a2f278b33bb08194aadf084c85861469d1563",
    ),
    "stock-acquisition": (
        EvaluationClassification.COMPLETE,
        "dbb9321410fd827f65fa8ab2d8f58e7355488c334781b71a0f354160e495c022",
        "d719459b541dbd0f61112f530157cf36f2cdeca4950bca08f6e404959fd90c41",
    ),
    "extinguishing-liquidation": (
        EvaluationClassification.COMPLETE,
        "638ee4e7bee0f88e7c78d66f6728da7dc8bfbc3f18fb10411802fd8a9c8d0bf8",
        "90a3b4c65d48fcd63470f48632d9e7a081086087e7a2ab1082eea4c7d995c391",
    ),
    "cash-acquisition": (
        EvaluationClassification.COMPLETE,
        "102f6cf5b51cdccabf0063a925de4b294c2c8b3537097770d1cb24f4931a0a97",
        "581cc449e6c98a8c038ae8b86f23c982f6ffcff63c7d5766b6ad110b026282b7",
    ),
    "cash-dividend": (
        EvaluationClassification.COMPLETE,
        "5036427e25b2d5b7a372801f985c600205ff9371f43ceeed9ba5cf471027af00",
        "2f35960e790d6e1350e3177636c8431c0b410759e4cae03342dbe12d224ffe61",
    ),
    # Issue 103: the session-3 decision sees both sides of the spin-off with
    # an indeterminate basis, so its context hash moves (41ce3853 to
    # 3a99b693), and with it the trace and result hashes. Nothing else does.
    "spinoff": (
        EvaluationClassification.COMPLETE,
        "41e66aa89e78fadc93e9e21ad7cdba6553ee7215aaa7a99c2f1e8fae888c652c",
        "aa68c784574c0433319766e35da7f66407c666c03c0d5d33482b84486232dac6",
    ),
    # Issue 105: the instalment leaves the continuing basis indeterminate, so
    # the session-3 decision context hash moves (f8b8bbef to 98949b80).
    "continuing-instalment": (
        EvaluationClassification.COMPLETE,
        "88151cc53750d3d83974555f2f639592f2446f66a520e7a655f4a49de2d933b1",
        "4df43e6d40f02f03c56c61f6658ab7e304e5bfc2eadb14c0d52a26b91019ba67",
    ),
    # Issue 105: the cash leg leaves the acquirer basis indeterminate, so the
    # session-3 decision context hash moves (bf7c5181 to e8e7a543).
    "mixed-acquisition": (
        EvaluationClassification.COMPLETE,
        "df667937c3b76cfda8ea4a717e55df9274974cc30f2fb658a830c67d2d63981f",
        "46a4fbb86ffd04a238af943441af475cd1f487700e80ba18bb4912ab8af56fee",
    ),
    # Issue 105: the sold third relieves 100.00 of basis against 1.00 of
    # proceeds, so realized gross and net PnL move from 0 to -99 and the
    # session-3 decision sees a 900.00 basis (context hash af429511 to
    # 87213f0b).
    "aggregate-sale-residual": (
        EvaluationClassification.COMPLETE,
        "b82784349f41b81bb2c95b1346bee347aebfca6338bb5c147a3b451cdd3f0e06",
        "bf14d43264e39e255819f194a742882df7b91d05e69fefbd0ad3bc7ddb620494",
    ),
}

RUNS: dict[str, Callable[[], EvaluationRunArtifactsV2]] = {
    "forward-split": forward_split_run,
    "stock-dividend": stock_dividend_run,
    "stock-acquisition": stock_acquisition_run,
    "extinguishing-liquidation": extinguishing_liquidation_run,
    "cash-acquisition": cash_acquisition_run,
    "cash-dividend": cash_dividend_run,
    "spinoff": spinoff_run,
    "continuing-instalment": continuing_instalment_run,
    "mixed-acquisition": mixed_acquisition_run,
    "aggregate-sale-residual": aggregate_sale_residual_run,
}


@pytest.mark.parametrize("name", RUNS)
def test_a_corporate_action_run_keeps_its_recorded_hashes(name: str) -> None:
    artifacts = RUNS[name]()

    assert (
        artifacts.result.classification,
        artifacts.trace.trace_hash,
        artifacts.result.result_hash,
    ) == RUN_PINS[name]


# ==========================================================================
# One accounting truth
# ==========================================================================


def test_the_engine_books_every_run_into_a_v2_book() -> None:
    artifacts = forward_split_run()

    assert type(artifacts) is EvaluationRunArtifactsV2
    assert type(artifacts.final_state) is PortfolioStateV2
    (holding,) = artifacts.final_state.holdings
    assert type(holding) is SecurityHoldingV2
    assert (holding.quantity, holding.basis_status, holding.cost_basis) == (
        20,
        "known",
        Decimal("1000"),
    )


def test_run_artifacts_never_pair_a_result_with_a_v1_book() -> None:
    artifacts = forward_split_run()
    data = json.loads(artifacts.model_dump_json())
    # The same book spelled as V1: no basis status, and a V1 schema version.
    book = data["final_state"]
    book["schema_version"] = "1"
    del book["applied_effect_ids"]
    for holding in book["holdings"]:
        holding["schema_version"] = "1"
        del holding["basis_status"]
        del holding["basis_indeterminate_by"]
    assert PortfolioStateV1.model_validate_json(json.dumps(book))

    with pytest.raises(ValidationError):
        EvaluationRunArtifactsV2.model_validate_json(json.dumps(data))
    # Control: the V2 book the run produced rebuilds exactly.
    rebuilt = EvaluationRunArtifactsV2.model_validate_json(artifacts.model_dump_json())
    assert rebuilt == artifacts


# ==========================================================================
# A replayed pre-open fails closed (issue 49)
# ==========================================================================


def _engine_processor() -> CorporateActionProcessor:
    return CorporateActionProcessor(
        session_clock=eng._clock(),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def _forward_split() -> SecurityEconomicOutcomeV1:
    _, outcome = _action(
        ActionKind.FORWARD_SPLIT,
        suffix=4900,
        components=(
            _shares(
                numerator="2", denominator="1", meaning="resulting_per_predecessor"
            ),
        ),
    )
    return outcome


def test_a_book_replayed_through_its_own_pre_open_is_refused() -> None:
    # The final book of the forward-split run already absorbed the split at
    # the session-3 pre-open. Replaying that pre-open on it, as a rebuilt M12
    # checkpoint would (#20 Q3), must not split the twenty shares again.
    book = forward_split_run().final_state
    assert [holding.quantity for holding in book.holdings] == [20]
    effect_id = applied_economic_effect_id(
        source_id=ca.SOURCE_A, security_id=eng.SEC_A, occurrence_id="issue-49-4900"
    )
    assert book.applied_effect_ids == (effect_id,)
    hold = (SecurityTargetPositionV1(security_id=eng.SEC_A, target_quantity=20),)

    with pytest.raises(EffectAlreadyAppliedError, match=effect_id):
        _engine_processor().apply_pre_open_actions(
            book, hold, (_forward_split(),), eng._key(eng.DAY_3)
        )

    # Control: the same book without its record is split a second time, to
    # forty shares. That is the defect the record exists to refuse.
    unrecorded = book.model_copy(update={"applied_effect_ids": ()})
    doubled, _ = _engine_processor().apply_pre_open_actions(
        unrecorded, hold, (_forward_split(),), eng._key(eng.DAY_3)
    )
    assert [holding.quantity for holding in doubled.holdings] == [40]


def test_every_run_records_the_share_actions_it_absorbed() -> None:
    recorded = {name: RUNS[name]().final_state.applied_effect_ids for name in RUNS}
    # A cash dividend moves no share and leaves no basis indeterminate. Every
    # other run records its one effect: a share action, or (issue 105) the
    # continuing instalment its indeterminate basis names.
    assert recorded["cash-dividend"] == ()
    for name in RUNS:
        if name != "cash-dividend":
            assert len(recorded[name]) == 1, name


# ==========================================================================
# An indeterminate basis fails closed when realized (issue 103)
# ==========================================================================

DAY_4 = date(2026, 1, 9)
FIVE_DAYS = (*eng.DAYS, DAY_4)


def _run_five_sessions(
    outcome: SecurityEconomicOutcomeV1,
    strategy: eng.FixedTargetStrategy,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rates: tuple[CashInLieuRateV1, ...] = (),
) -> EvaluationRunArtifactsV2:
    """The engine fixture plus a session 4, with SEC_B admitted and priced."""
    monkeypatch.setitem(eng.PRICES[eng.SEC_A], DAY_4, ("120.00", "121.00"))
    monkeypatch.setitem(eng.PRICES[eng.SEC_B], DAY_4, ("50.00", "51.00"))
    views = tuple(eng._accounting_view(eng.SEC_A, day) for day in FIVE_DAYS) + tuple(
        eng._accounting_view(eng.SEC_B, day, listing_id=eng.LISTING_B)
        for day in (eng.DAY_3, DAY_4)
    )
    bundle = eng._bundle(
        days=FIVE_DAYS,
        accounting_views=views,
        eligibilities=(
            eng._eligibility(eng.SEC_A, eng.LISTING_A),
            eng._eligibility(eng.SEC_B, eng.LISTING_B),
        ),
        economic_outcomes=(outcome.resolution,),
    )
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS,
            economic_outcomes=(outcome,),
            cash_in_lieu_rates=rates,
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )
    return eng._run(engine, strategy)


def _spinoff() -> SecurityEconomicOutcomeV1:
    _, outcome = _action(
        ActionKind.SPINOFF,
        suffix=5000,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="additional_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
    )
    return outcome


def _then_at_session_3(
    targets: tuple[tuple[UUID, int], ...],
) -> eng.FixedTargetStrategy:
    return eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: ((eng.SEC_A, 10),),
            eng.DAY_3: targets,
        }
    )


def _halt(artifacts: EvaluationRunArtifactsV2) -> tuple[int | None, str]:
    (cause,) = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    return artifacts.result.halted_session_index, f"{cause.phase}: {cause.cause}"


@pytest.mark.parametrize(
    ("sold", "targets"),
    [
        ("child", ((eng.SEC_A, 10), (eng.SEC_B, 0))),
        ("parent", ((eng.SEC_A, 4), (eng.SEC_B, 5))),
    ],
)
def test_selling_either_side_of_a_spinoff_halts_instead_of_inventing_pnl(
    sold: str,
    targets: tuple[tuple[UUID, int], ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _run_five_sessions(_spinoff(), _then_at_session_3(targets), monkeypatch)

    # Before the fix the child's five shares sold for 250.00 of pure realized
    # gain on a zero basis, and the parent's sale relieved its whole basis.
    session, cause = _halt(artifacts)
    assert session == 4
    assert cause.startswith("open_execution: the rebalance sells")
    assert "whose cost basis is indeterminate" in cause
    security = eng.SEC_B if sold == "child" else eng.SEC_A
    assert str(security) in cause
    # The book as of its last mark: both sides held, neither sold.
    assert [(holding.quantity) for holding in artifacts.final_state.holdings] == [
        10,
        5,
    ]
    assert artifacts.result.metrics.realized_gross_pnl == Decimal("0")


def test_holding_both_sides_of_a_spinoff_marks_a_complete_nav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = _run_five_sessions(
        _spinoff(),
        _then_at_session_3(((eng.SEC_A, 10), (eng.SEC_B, 5))),
        monkeypatch,
    )

    # NAV never reads basis status: ten parents at 121.00 and five children
    # at 51.00, on the 9000.00 of cash left after the session-2 buy.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10465.00")
    statuses = {
        holding.security_id: holding.basis_status
        for holding in artifacts.final_state.holdings
    }
    assert statuses == {eng.SEC_A: "indeterminate", eng.SEC_B: "indeterminate"}


def test_a_decision_sees_an_indeterminate_basis_as_unknown() -> None:
    strategy = eng._buy_ten()
    _, outcome = _action(
        ActionKind.SPINOFF,
        suffix=4960,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="additional_per_predecessor",
                recipient=eng.SEC_B,
            ),
        ),
    )
    _run(outcome, _views(child=True), strategy=strategy)

    views = {view.security_id: view for view in strategy.seen[-1].current_holdings}
    for security in (eng.SEC_A, eng.SEC_B):
        assert views[security].cost_basis is None
        assert views[security].average_cost_per_share is None
    # Control: the decision before the spin-off saw the known basis.
    (before,) = strategy.seen[-2].current_holdings
    assert before.cost_basis == Decimal("1000.00")


# ==========================================================================
# Basis allocation from source evidence only (issue 105)
# ==========================================================================

_INITIAL_CASH = Decimal("10000.00")


def _identity_gap(artifacts: EvaluationRunArtifactsV2) -> Decimal:
    """Cash, claims and remaining basis, less initial cash and realized PnL."""
    state = artifacts.final_state
    basis = sum((ca._known_basis(holding) for holding in state.holdings), Decimal(0))
    return (
        state.cash_balance
        + state.pending_claims_value
        + basis
        - _INITIAL_CASH
        - state.realized_net_pnl
    )


def test_an_aggregate_sale_residual_closes_the_realized_pnl_identity() -> None:
    artifacts = aggregate_sale_residual_run()

    # Ten shares of basis 1000.00 became 3 1/3; the third sold for 1.00 and
    # carried 100.00 of the pool. Before the fix it relieved nothing and the
    # identity missed by 100.00.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    (holding,) = artifacts.final_state.holdings
    assert (holding.quantity, holding.cost_basis) == (3, Decimal("900"))
    assert artifacts.result.metrics.realized_net_pnl == Decimal("-99")
    assert _identity_gap(artifacts) == 0


@pytest.mark.parametrize(
    "name",
    [
        "forward-split",
        "stock-dividend",
        "stock-acquisition",
        "extinguishing-liquidation",
        "cash-acquisition",
        "aggregate-sale-residual",
    ],
)
def test_the_realized_pnl_identity_closes_over_every_determinate_run(
    name: str,
) -> None:
    assert _identity_gap(RUNS[name]()) == 0


def test_a_mixed_acquisition_cash_leg_halts_the_sale_of_its_acquirer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, outcome = _action(
        ActionKind.MIXED_ACQUISITION,
        suffix=5100,
        components=(
            _shares(
                numerator="1",
                denominator="2",
                meaning="resulting_per_predecessor",
                recipient=eng.SEC_B,
            ),
            _cash("5", "acquisition-cash"),
        ),
        dates=_payable(),
        claim_status="converted",
    )

    sold = _run_five_sessions(
        outcome, _then_at_session_3(((eng.SEC_B, 2),)), monkeypatch
    )

    # Before the fix the acquirer carried the whole 1000.00 basis, the cash
    # leg realized 0, and selling three acquirer shares relieved 600.00.
    session, cause = _halt(sold)
    assert session == 4
    assert cause.startswith("open_execution: the rebalance sells 3 of")

    # Control: holding the acquirer marks a complete NAV.
    held = _run_five_sessions(
        outcome, _then_at_session_3(((eng.SEC_B, 5),)), monkeypatch
    )
    assert held.result.classification is EvaluationClassification.COMPLETE
    (acquirer,) = held.final_state.holdings
    assert (acquirer.security_id, acquirer.basis_status) == (eng.SEC_B, "indeterminate")


def _instalment_then_final(*, amount: str) -> tuple[SecurityEconomicOutcomeV1, str]:
    """A continuing instalment at session 3, then the final disposal at 4."""
    cash = _cash(amount, "instalment-cash")
    terms = ca._terms(
        suffix=5200,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash,),
        dates=(ca._date_fact("ex", ACTION_AT), *_payable()),
        security_id=eng.SEC_A,
    )
    instalment = ca._effect(
        suffix=5201,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash,),
        terms=terms,
        occurrence_id="issue-105-instalment",
        effective_at=ACTION_AT,
        security_id=eng.SEC_A,
    )
    final_at = "2026-01-09T00:00:00Z"
    final_cash = _cash("150", "final-cash")
    final_terms = ca._terms(
        suffix=5210,
        action_kind=ActionKind.LIQUIDATION,
        components=(final_cash,),
        dates=(ca._date_fact("payable", final_at),),
        security_id=eng.SEC_A,
    )
    final = ca._effect(
        suffix=5211,
        action_kind=ActionKind.LIQUIDATION,
        components=(final_cash,),
        terms=final_terms,
        occurrence_id="issue-105-final",
        effective_at=final_at,
        security_id=eng.SEC_A,
        claim_status="extinguished",
    )
    outcome = ca._outcome(
        security_id=eng.SEC_A,
        terms=(terms, final_terms),
        effects=(instalment, final),
        action_kinds=(ActionKind.LIQUIDATION,),
        claim_status="extinguished",
    )
    cause = applied_economic_effect_id(
        source_id=ca.SOURCE_A,
        security_id=eng.SEC_A,
        occurrence_id="issue-105-instalment",
    )
    return outcome, cause


def test_the_disposal_after_a_liquidation_instalment_halts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, cause = _instalment_then_final(amount="3")

    artifacts = _run_five_sessions(
        outcome, _then_at_session_3(((eng.SEC_A, 10),)), monkeypatch
    )

    # Before the fix the 30.00 instalment was income and the final 1500.00
    # realized 500.00; as a return of capital it would realize 530.00. With
    # no source saying which, the disposal cannot book either.
    session, halt = _halt(artifacts)
    assert session == 4
    assert halt.startswith("pre_open_effects: the cost basis of")
    assert cause in halt
    assert artifacts.result.metrics.realized_gross_pnl == Decimal("0")


def test_an_instalment_above_its_basis_halts_at_its_own_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 120.00 a share on ten shares of basis 100.00 a share.
    outcome, _ = _instalment_then_final(amount="120")

    artifacts = _run_five_sessions(
        outcome, _then_at_session_3(((eng.SEC_A, 10),)), monkeypatch
    )

    session, halt = _halt(artifacts)
    assert session == 3
    assert "exceeds its basis" in halt
