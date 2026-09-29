"""M2 adversarial acceptance: accounting and execution invariants.

The attacks here are chosen against this milestone's own failure history. Two
value-creation defects shipped on a fully green suite: a dividend that could
pay twice because claim identity carried a revisable payable date, and a stale
mark that survived a fill so that market value outlived the holdings backing
it. Both classes are re-attacked directly below, end to end rather than at the
unit boundary where they originally hid.

Where a case restates an invariant the Task 3 to Task 5 unit tests already
cover, it is included because the canonical plan's adversarial matrix names it,
and it is strengthened with an explicit control: the same setup with the
offending property removed must behave differently. A fail-closed assertion
with no control is indistinguishable from an assertion that could never fail.
"""

# ruff: noqa: E402

import sys
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal
from uuid import UUID

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
import test_evaluator_corporate_actions as ca
import test_evaluator_engine as eng
import test_evaluator_execution as ex
from observation_test_support import NormalizationHarness
from pydantic import ValidationError

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_corporate_actions import (
    SecurityEconomicOutcomeV1,
    cash_in_lieu_component_id,
)
from drift.domain.evaluator_execution import (
    IndeterminateExecutionError,
    RebalanceOutcomeV1,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PortfolioFillV1,
    pending_cash_claim_id,
)
from drift.domain.evaluator_protocol import (
    EvaluationProtocolV1,
    evaluation_protocol_hash,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.evaluator_trace import EvaluationPhase
from drift.domain.normalization import DerivedObservationViewV1
from drift.evaluator.engine import (
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    source_basis_price,
)
from drift.evaluator.execution import AtomicRebalanceEngine
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.markets.normalization import materialize_observation_outcome

ZERO = Decimal("0")


# ==========================================================================
# Double-counting adjustment
# ==========================================================================


def _outcome_view(
    mode: Literal["source_basis", "split_normalized"], *, anchor: date | None = None
) -> DerivedObservationViewV1:
    harness = NormalizationHarness()
    query = harness.normalization_query(mode, anchor_date=anchor)
    result = harness.normalize(query)
    view: DerivedObservationViewV1 = materialize_observation_outcome(
        result.reference, query, harness.context
    )
    return view


def test_an_adjusted_view_cannot_enter_the_accounting_bucket() -> None:
    """Split-adjusted prices plus M1c splits would apply one split twice."""
    adjusted = _outcome_view("split_normalized", anchor=date(2026, 11, 30))
    assert adjusted.basis_mode == "split_normalized"

    with pytest.raises(
        (ValidationError, ValueError),
        match=r"authentic accounting views require unadjusted source basis",
    ):
        eng._bundle(accounting_views=(adjusted,))


def test_the_price_bridge_refuses_adjusted_evidence_that_bypassed_the_bundle() -> None:
    adjusted = _outcome_view("split_normalized", anchor=date(2026, 11, 30))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^execution and accounting require source basis evidence",
    ):
        source_basis_price(adjusted, "close")


def test_the_double_count_the_basis_rule_prevents_is_material() -> None:
    """Control: the two bases really disagree, so admitting one would matter."""
    source = _outcome_view("source_basis")
    adjusted = _outcome_view("split_normalized", anchor=date(2026, 11, 30))

    source_close = next(item for item in source.fields if item.field_name == "close")
    adjusted_close = next(
        item for item in adjusted.fields if item.field_name == "close"
    )
    assert source_close.exact_factor.numerator == "1"
    assert source_close.exact_factor.denominator == "1"
    assert (
        adjusted_close.exact_factor.numerator,
        adjusted_close.exact_factor.denominator,
    ) != ("1", "1")
    assert adjusted_close.quantized_value != adjusted_close.source_value


def test_a_source_basis_view_carrying_a_scaling_factor_fails_closed() -> None:
    """An adjusted number wearing an unadjusted label must not be read."""
    view = eng._template_view()
    scaled = tuple(
        item.model_copy(
            update={
                "exact_factor": item.exact_factor.model_copy(
                    update={"denominator": "2"}
                )
            }
        )
        if item.field_name == "open"
        else item
        for item in view.fields
    )
    forged = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"fields": scaled})
    )

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^source basis evidence requires an identity transform factor",
    ):
        source_basis_price(forged, "open")


# ==========================================================================
# Premature settlement and the double-payment hazard
# ==========================================================================


def test_a_claim_cannot_settle_before_its_payable_session() -> None:
    _, _, outcome = ca._dividend_case(amount="0.5", suffix=9100)
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    staged, _ = ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    claim = staged.pending_cash_claims[0]
    kernel = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)

    with pytest.raises(ValueError, match=r"is not yet payable"):
        kernel.settle_claims((claim.claim_id,))

    # Control: the same claim settles once its proven payable session arrives.
    payable = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)
    payable.advance_session(ca._key(ca.PAYABLE_DAY))
    payable.settle_claims((claim.claim_id,))
    assert payable.state.cash_balance == Decimal("1050.0")


def test_delivered_cash_before_the_payable_session_is_indeterminate() -> None:
    _, _, outcome = ca._dividend_case(amount="0.5", suffix=9110)
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    staged, _ = ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    early = ca._outcome(
        effects=(),
        delivery_groups=(
            ca._delivery(components=(ca._cash(amount="0.5"),), settled_at=ca.LATER_AT),
        ),
    )
    advanced = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)
    advanced.advance_session(ca._key(ca.LATER_DAY))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^a claim cannot be delivered before its proven payable session",
    ):
        ca._processor().apply_intrasession_settlements(
            advanced.state, (early,), ca._key(ca.LATER_DAY)
        )


def test_a_payable_date_revision_cannot_pay_one_entitlement_twice() -> None:
    """The shipped defect: a revisable date must never mint a second claim.

    Both settled-claim guards key on ``claim_id``. If a payable-date revision
    produced a second id, neither guard would fire and one entitlement would
    pay twice. This walks the whole path: stage, settle, then re-apply the
    revised terms and require that no second claim and no second payment
    appear.
    """
    _, _, original = ca._dividend_case(amount="0.5", suffix=9200)
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    staged, _ = ca._processor().apply_pre_open_actions(
        state, (), (original,), ca._key()
    )
    claim = staged.pending_cash_claims[0]
    assert claim.payable_session == ca.PAYABLE_DAY

    kernel = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)
    kernel.advance_session(ca._key(ca.PAYABLE_DAY))
    kernel.settle_claims((claim.claim_id,))
    settled = kernel.state
    assert settled.cash_balance == Decimal("1050.0")

    # The source revises the payable date. Nothing else about the entitlement
    # changes, so the revision must resolve onto the same claim identity.
    _, _, revised = ca._dividend_case(
        amount="0.5",
        suffix=9210,
        dates=(
            ca._date_fact("ex", ca.EFFECT_AT),
            ca._date_fact("record", ca.EFFECT_AT),
            ca._date_fact("payable", ca.LATER_AT),
        ),
    )
    fresh_book = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    would_stage, _ = ca._processor().apply_pre_open_actions(
        fresh_book, (), (revised,), ca._key()
    )
    # Control: the revised terms are live evidence that does stage a claim.
    assert len(would_stage.pending_cash_claims) == 1
    assert would_stage.pending_cash_claims[0].payable_session == ca.LATER_DAY
    assert would_stage.pending_cash_claims[0].claim_id == claim.claim_id

    replay = ca._state(
        holdings=(ca._holding(quantity=100),),
        cash="1050.0",
        settled=(claim.claim_id,),
    )
    again, _ = ca._processor().apply_pre_open_actions(replay, (), (revised,), ca._key())

    assert again.pending_cash_claims == ()
    assert again.cash_balance == Decimal("1050.0")
    assert again.net_asset_value == Decimal("1050.0")


def test_a_settled_claim_can_never_be_recorded_again() -> None:
    _, _, outcome = ca._dividend_case(amount="0.5", suffix=9220)
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    staged, _ = ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    claim = staged.pending_cash_claims[0]
    kernel = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)
    kernel.advance_session(ca._key(ca.PAYABLE_DAY))
    kernel.settle_claims((claim.claim_id,))

    with pytest.raises(ValueError, match=r"^claim already settled"):
        kernel.record_claim(claim)
    with pytest.raises(ValueError, match=r"^claim already settled"):
        kernel.supersede_claim(claim)


def test_settlement_moves_claim_value_into_cash_without_creating_any() -> None:
    _, _, outcome = ca._dividend_case(amount="0.5", suffix=9230)
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")
    staged, _ = ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())
    before = staged.cash_balance + staged.pending_claims_value
    assert staged.pending_claims_value == Decimal("50.0")

    kernel = PortfolioAccountingKernel(staged, session_clock=ca.CLOCK)
    kernel.advance_session(ca._key(ca.PAYABLE_DAY))
    kernel.settle_claims(tuple(claim.claim_id for claim in staged.pending_cash_claims))

    after = kernel.state
    assert after.cash_balance + after.pending_claims_value == before
    assert after.pending_claims_value == ZERO


def test_two_cash_components_on_one_date_are_two_distinct_claims() -> None:
    """Same-date cash legs separate on M1c component identity, not on date."""
    first = ca._cash(amount="0.5", component_id="cash-1")
    second = ca._cash(amount="0.25", component_id="cash-2")
    dates = (
        ca._date_fact("ex", ca.EFFECT_AT),
        ca._date_fact("record", ca.EFFECT_AT),
        ca._date_fact("payable", ca.PAYABLE_AT),
    )
    terms = ca._terms(
        suffix=9300,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(first, second),
        dates=dates,
    )
    effect = ca._effect(
        suffix=9301,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(first, second),
        terms=terms,
    )
    outcome = ca._outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )
    state = ca._state(holdings=(ca._holding(quantity=100),), cash="1000")

    staged, _ = ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())

    claims = staged.pending_cash_claims
    assert len(claims) == 2
    assert len({claim.claim_id for claim in claims}) == 2
    assert {claim.component_id for claim in claims} == {"cash-1", "cash-2"}
    assert staged.pending_claims_value == Decimal("75.00")
    for claim in claims:
        assert claim.claim_id == pending_cash_claim_id(
            source_id=claim.source_id,
            security_id=claim.security_id,
            action_kind=claim.action_kind,
            occurrence_id=claim.occurrence_id,
            component_id=claim.component_id,
        )


def test_another_sources_delivery_never_settles_this_sources_claim() -> None:
    """Settlement matching stays source-scoped when only one claim is pending.

    Source A's 0.50 claim on 100 shares is pending and payable. Source B then
    reports a delivery reusing A's occurrence and component ids. That is
    another source's evidence, which no entitlement of this book explains, so
    it halts. Falling back to any claim sharing the security, occurrence and
    component would pay A's entitlement on B's word.
    """
    claim = ca._manual_claim(payable=ca.PAYABLE_DAY, source_id=ca.SOURCE_A)
    state = ca._state(claims=(claim,), cash="100", day=ca.PAYABLE_DAY)

    def delivered_by(source_id: str) -> SecurityEconomicOutcomeV1:
        return ca._outcome(
            effects=(),
            delivery_groups=(
                ca._delivery(components=(ca._cash(amount="0.5"),), source_id=source_id),
            ),
        )

    with pytest.raises(
        IndeterminateValuationError,
        match=(
            r"matches no pending claim and no proven entitlement: "
            r"synthetic-b/occ-1/cash-1$"
        ),
    ):
        ca._processor().apply_intrasession_settlements(
            state, (delivered_by(ca.SOURCE_B),), ca._key(ca.PAYABLE_DAY)
        )

    # Control: the identical report from source A settles A's claim.
    settled = ca._processor().apply_intrasession_settlements(
        state, (delivered_by(ca.SOURCE_A),), ca._key(ca.PAYABLE_DAY)
    )
    assert settled.settled_claim_ids == (claim.claim_id,)
    assert settled.pending_cash_claims == ()
    assert settled.cash_balance == Decimal("150.0")


# ==========================================================================
# Due bills, tie-breaking, and unprovable fractions
# ==========================================================================


def test_a_due_bill_distribution_never_falls_back_to_the_record_date() -> None:
    """No generic redemption-equals-entitlement shortcut, and no silent default."""
    _, _, due_bill = ca._due_bill_terms()
    state = ca._state(holdings=(ca._holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^a due-bill distribution requires a proven executable due-bill rule",
    ):
        ca._processor().apply_pre_open_actions(state, (), (due_bill,), ca._key())

    # Control: the ex date in that very same kind of terms record is perfectly
    # usable, and is used, once the due-bill fact is absent. The failure above
    # is therefore a refusal to derive, not a missing date.
    _, _, plain = ca._dividend_case(
        action_kind=ActionKind.SPECIAL_CASH_DISTRIBUTION,
        amount="2",
        suffix=9400,
        dates=(
            ca._date_fact("ex", ca.EFFECT_AT),
            ca._date_fact("record", ca.EFFECT_AT),
            ca._date_fact("payable", ca.PAYABLE_AT),
        ),
    )
    staged, _ = ca._processor().apply_pre_open_actions(state, (), (plain,), ca._key())
    assert len(staged.pending_cash_claims) == 1
    assert staged.pending_cash_claims[0].entitlement_session == ca.EFFECT_DAY


def test_round_nearest_without_a_source_rule_fails_closed() -> None:
    _, effect, outcome = ca._split_case(
        numerator="1",
        denominator="2",
        treatment=ca._treatment("round_nearest"),
        suffix=9500,
    )
    state = ca._state(holdings=(ca._holding(quantity=5),))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^round_nearest requires an interpreted source tie-breaking rule",
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())

    # Control: the very same split resolves once the source reading is bound.
    resolved, _ = ca._processor(
        tie_breaking_rules=(ca._tie_rule(effect=effect, tie_break="half_up"),)
    ).apply_pre_open_actions(state, (), (outcome,), ca._key())
    assert resolved.holdings[0].quantity == 3


def test_a_reverse_split_with_an_unknown_fraction_treatment_fails_closed() -> None:
    for kind in ("unknown", "fraction_issued"):
        _, _, outcome = ca._split_case(
            numerator="1",
            denominator="8",
            treatment=ca._treatment(kind),
            suffix=9510,
        )
        state = ca._state(holdings=(ca._holding(quantity=10),))
        with pytest.raises(
            IndeterminateValuationError,
            match=(
                r"^fractional share entitlement has no resolvable fraction treatment"
            ),
        ):
            ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())

    # Control: a resolvable treatment on the identical ratio does commit.
    _, _, resolvable = ca._split_case(
        numerator="1",
        denominator="8",
        treatment=ca._treatment("round_down"),
        suffix=9511,
    )
    state = ca._state(holdings=(ca._holding(quantity=10),))
    updated, _ = ca._processor().apply_pre_open_actions(
        state, (), (resolvable,), ca._key()
    )
    assert updated.holdings[0].quantity == 1


def test_an_aggregate_sale_residual_without_a_proven_rate_fails_closed() -> None:
    _, effect, outcome = ca._split_case(
        numerator="1",
        denominator="8",
        treatment=ca._treatment("aggregate_sale_cash"),
        suffix=9520,
        dates=(ca._date_fact("payable", ca.PAYABLE_AT),),
    )
    state = ca._state(holdings=(ca._holding(quantity=10, basis="800"),))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"^an aggregate-sale fractional entitlement requires a proven",
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())

    # Control: with the source rate bound, the residual becomes a cash claim
    # carrying the exact fractional quantum in its own component identity.
    priced, _ = ca._processor(
        cash_in_lieu_rates=(ca._cash_in_lieu_rate(effect=effect, rate="4"),)
    ).apply_pre_open_actions(state, (), (outcome,), ca._key())
    assert priced.pending_cash_claims[0].component_id == cash_in_lieu_component_id(
        "shares-1", Fraction(1, 4)
    )


def test_cash_with_no_exact_decimal_spelling_fails_closed() -> None:
    """Rounding a non-terminating quotient would invent or destroy money."""
    component = ca._cash(amount="1", numerator="3", denominator="1")
    dates = (
        ca._date_fact("ex", ca.EFFECT_AT),
        ca._date_fact("record", ca.EFFECT_AT),
        ca._date_fact("payable", ca.PAYABLE_AT),
    )
    terms = ca._terms(
        suffix=9600,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        dates=dates,
    )
    effect = ca._effect(
        suffix=9601,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=terms,
    )
    outcome = ca._outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )
    state = ca._state(holdings=(ca._holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"is not exactly representable as a decimal",
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())


def test_a_foreign_currency_distribution_fails_closed() -> None:
    _, _, outcome = ca._dividend_case(amount="0.5", suffix=9610, code="EUR")
    state = ca._state(holdings=(ca._holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match=r"does not match the book currency",
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())


# ==========================================================================
# Terms are a schedule, never a mutation
# ==========================================================================


def test_terms_without_an_occurred_effect_commit_no_mutation() -> None:
    component = ca._shares(numerator="2", denominator="1")
    terms = ca._terms(
        suffix=9700,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
    )
    outcome = ca._outcome(
        terms=(terms,), effects=(), action_kinds=(ActionKind.FORWARD_SPLIT,)
    )
    state = ca._state(holdings=(ca._holding(quantity=10),), cash="1000")

    updated, targets = ca._processor().apply_pre_open_actions(
        state, (), (outcome,), ca._key()
    )

    assert updated is state
    assert targets == ()
    assert updated.holdings[0].quantity == 10
    assert updated.cash_balance == Decimal("1000")
    assert updated.pending_cash_claims == ()


def test_an_upcoming_effect_record_commits_no_mutation() -> None:
    """An effect record the source still projects as upcoming is a schedule.

    The case above carries no effect record at all, so it cannot tell an
    upcoming effect from an occurred one. Here the record is present.
    """
    _, _, occurred = ca._split_case(
        numerator="2",
        denominator="1",
        treatment=ca._treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=9710,
    )
    upcoming = ca._outcome(
        terms=occurred.terms_records,
        effects=occurred.effect_records,
        statuses=("upcoming",),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    assert len(upcoming.effect_records) == 1
    state = ca._state(holdings=(ca._holding(quantity=10),), cash="1000")

    updated, targets = ca._processor().apply_pre_open_actions(
        state, (), (upcoming,), ca._key()
    )

    assert updated is state
    assert targets == ()

    # Control: the identical record projected as effective splits the book.
    split, _ = ca._processor().apply_pre_open_actions(state, (), (occurred,), ca._key())
    assert [holding.quantity for holding in split.holdings] == [20]


@pytest.mark.parametrize("claim_status", ["extinguished", "continuing"])
def test_a_liquidation_without_source_terms_fails_closed(claim_status: str) -> None:
    """A delisting whose settlement is unprovable is never invented.

    Both liquidation paths need the terms: an extinguishing one to date its
    terminal claims, a continuing one to find the ex date it vests on.
    """
    component = ca._cash(amount="3")
    effect = ca._effect(
        suffix=9710,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        terms=None,
        claim_status=claim_status,
    )
    outcome = ca._outcome(
        terms=(), effects=(effect,), action_kinds=(ActionKind.LIQUIDATION,)
    )
    state = ca._state(holdings=(ca._holding(quantity=10),), cash="1000")

    with pytest.raises(
        IndeterminateValuationError,
        match=r"requires identified source terms to prove its dates",
    ):
        ca._processor().apply_pre_open_actions(state, (), (outcome,), ca._key())


# ==========================================================================
# Marks: no forward fill, no stale value
# ==========================================================================


def test_a_missing_close_for_a_held_position_is_never_forward_filled() -> None:
    bundle = eng._bundle(
        accounting_views=tuple(
            eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3]
        )
    )

    artifacts = eng._run(eng._engine(bundle=bundle))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.CLOSE_MARK
    # The prior session did mark, and its close was available to forward fill.
    marks = [event for event in artifacts.trace.events if event.kind == "session_mark"]
    assert [event.session_index for event in marks] == [0, 1, 2]
    assert marks[-1].holdings_market_value == Decimal("1100.00")
    assert artifacts.result.metrics.evaluated_session_count == 3

    # Control: with the missing close supplied the same run completes.
    complete = eng._run(eng._engine())
    assert complete.result.classification is EvaluationClassification.COMPLETE
    assert complete.result.metrics.evaluated_session_count == 4


def test_a_stale_mark_cannot_survive_a_liquidation() -> None:
    """The shipped defect: market value outliving the holdings that back it."""
    strategy = eng.FixedTargetStrategy(
        {eng.DAY_1: ((eng.SEC_A, 10),), eng.DAY_2: (), eng.DAY_3: ()}
    )

    artifacts = eng._run(eng._engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    series = artifacts.result.metrics.equity_series
    # Control: the position was genuinely marked before it was liquidated.
    assert series[2].holdings_market_value > ZERO
    assert artifacts.final_state.holdings == ()
    assert artifacts.final_state.holdings_market_value == ZERO
    assert artifacts.final_state.mark is not None
    assert artifacts.final_state.mark.prices == ()
    assert artifacts.final_state.net_asset_value == artifacts.final_state.cash_balance


def test_a_fill_invalidates_the_mark_it_was_taken_against() -> None:
    state = ca._state(holdings=(ca._holding(quantity=10, basis="100"),), cash="1000")
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)
    kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))
    assert kernel.state.holdings_market_value == Decimal("100")

    kernel.apply_fill(
        PortfolioFillV1(
            security_id=ca.SEC_A,
            side="sell",
            quantity=10,
            fill_price=Decimal("10"),
            transaction_costs=ZERO,
        )
    )

    assert kernel.state.mark is None
    assert kernel.state.holdings == ()
    assert kernel.state.holdings_market_value == ZERO
    assert kernel.state.net_asset_value == kernel.state.cash_balance


def test_a_mark_does_not_survive_into_the_next_session() -> None:
    state = ca._state(holdings=(ca._holding(quantity=10, basis="100"),), cash="1000")
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)
    kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))
    assert kernel.state.holdings_market_value == Decimal("100")

    kernel.advance_session(ca._key(ca.LATER_DAY))

    assert kernel.state.mark is None
    assert kernel.state.holdings_market_value == ZERO
    assert kernel.state.holdings[0].quantity == 10


def test_a_corporate_action_discards_the_mark_it_invalidates() -> None:
    _, _, outcome = ca._split_case(
        numerator="2",
        denominator="1",
        treatment=ca._treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=9800,
    )
    state = ca._state(holdings=(ca._holding(quantity=10, basis="100"),), cash="1000")
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)
    kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))
    marked = kernel.state
    assert marked.holdings_market_value == Decimal("100")

    updated, _ = ca._processor().apply_pre_open_actions(
        marked, (), (outcome,), ca._key()
    )

    assert updated.holdings[0].quantity == 20
    assert updated.mark is None
    assert updated.holdings_market_value == ZERO


def test_a_forward_split_creates_no_net_asset_value() -> None:
    engine, _ = eng._split_engine()

    artifacts = eng._run(engine)

    series = artifacts.result.metrics.equity_series
    # Twenty shares at the halved close against ten at the unsplit close.
    assert series[2].holdings_market_value == Decimal("1100.00")
    assert series[3].holdings_market_value == Decimal("1200.00")
    assert artifacts.final_state.holdings[0].quantity == 20
    assert artifacts.final_state.holdings[0].cost_basis == Decimal("1000.00")


# ==========================================================================
# Staged target translation through every share action
# ==========================================================================
#
# The overnight-split invariant (a staged target is restated through the
# action so the intended delta survives) holds for every action that moves
# shares, not only for splits. Each run below holds ten shares of SEC_A from
# the session-2 open, with a hold of ten staged for session 3, and the action
# becomes effective at the session-3 pre-open. A correct translation trades
# nothing at that open.

_ACTION_AT = "2026-01-08T00:00:00Z"


def _share_action_outcome(
    kind: ActionKind,
    *,
    numerator: str,
    denominator: str,
    meaning: str,
    suffix: int,
    recipient: UUID = eng.SEC_A,
    claim_status: str = "continuing",
    effective_at: str = _ACTION_AT,
) -> SecurityEconomicOutcomeV1:
    component = ca._shares(
        numerator=numerator,
        denominator=denominator,
        component_id="action-shares",
        recipient=recipient,
        predecessor=eng.SEC_A,
        meaning=meaning,
    )
    terms = ca._terms(
        suffix=suffix, action_kind=kind, components=(component,), security_id=eng.SEC_A
    )
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=(component,),
        terms=terms,
        occurrence_id=f"issue-81-{suffix}",
        effective_at=effective_at,
        security_id=eng.SEC_A,
        claim_status=claim_status,
    )
    return ca._outcome(
        security_id=eng.SEC_A, terms=(terms,), effects=(effect,), action_kinds=(kind,)
    )


def _cash_acquisition_outcome(*, suffix: int) -> SecurityEconomicOutcomeV1:
    """SEC_A acquired for 150.00 a share, paid and delivered on session 3."""
    cash = ca._cash(
        amount="150", component_id="acquisition-cash", predecessor=eng.SEC_A
    )
    terms = ca._terms(
        suffix=suffix,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(cash,),
        dates=(ca._date_fact("payable", _ACTION_AT),),
        security_id=eng.SEC_A,
    )
    occurrence = f"issue-81-{suffix}"
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(cash,),
        terms=terms,
        occurrence_id=occurrence,
        effective_at=_ACTION_AT,
        security_id=eng.SEC_A,
        claim_status="extinguished",
    )
    delivery = ca._delivery(
        components=(cash,),
        security_id=eng.SEC_A,
        occurrence_id=occurrence,
        settled_at=_ACTION_AT,
    )
    return ca._outcome(
        security_id=eng.SEC_A,
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(delivery,),
        action_kinds=(ActionKind.CASH_ACQUISITION,),
    )


def _run_action(
    outcome: SecurityEconomicOutcomeV1,
    views: tuple[DerivedObservationViewV1, ...],
    strategy: eng.FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV1:
    bundle = eng._bundle(
        accounting_views=views, economic_outcomes=(outcome.resolution,)
    )
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS, economic_outcomes=(outcome,)
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )
    return eng._run(engine, strategy)


def _pre_action_views() -> tuple[DerivedObservationViewV1, ...]:
    return tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:3])


def _fills(artifacts: EvaluationRunArtifactsV1) -> list[tuple[int, str, int]]:
    return [
        (event.session_index, event.fill.side, event.fill.quantity)
        for event in artifacts.trace.events
        if event.kind == "fill"
    ]


def _translated_targets(artifacts: EvaluationRunArtifactsV1) -> dict[UUID, int]:
    (applied,) = [
        event
        for event in artifacts.trace.events
        if event.kind == "corporate_action_applied"
    ]
    assert applied.session_index == 3
    return {
        target.security_id: target.target_quantity
        for target in applied.staged_targets_after
    }


def _held(artifacts: EvaluationRunArtifactsV1) -> dict[UUID, int]:
    return {
        holding.security_id: holding.quantity
        for holding in artifacts.final_state.holdings
    }


def test_an_overnight_stock_dividend_keeps_a_staged_hold_a_hold() -> None:
    outcome = _share_action_outcome(
        ActionKind.STOCK_DIVIDEND,
        numerator="1",
        denominator="10",
        meaning="additional_per_predecessor",
        suffix=8100,
    )
    views = _pre_action_views() + (
        eng._accounting_view(
            eng.SEC_A, eng.DAY_3, open_price="100.00", close_price="109.10"
        ),
    )

    artifacts = _run_action(outcome, views)

    # Before the fix the target stayed at ten and one new share was sold.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 11}
    assert _held(artifacts) == {eng.SEC_A: 11}
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10200.10")


def test_an_overnight_stock_dividend_restates_a_staged_buy() -> None:
    outcome = _share_action_outcome(
        ActionKind.STOCK_DIVIDEND,
        numerator="1",
        denominator="10",
        meaning="additional_per_predecessor",
        suffix=8105,
    )
    views = _pre_action_views() + (
        eng._accounting_view(
            eng.SEC_A, eng.DAY_3, open_price="90.00", close_price="91.00"
        ),
    )
    buy_ten_more = eng.FixedTargetStrategy(
        {eng.DAY_1: ((eng.SEC_A, 10),), eng.DAY_2: ((eng.SEC_A, 20),)}
    )

    artifacts = _run_action(outcome, views, buy_ten_more)

    # A staged buy of ten pre-dividend shares is a buy of eleven afterwards,
    # on top of the eleven the dividend already delivered.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10), (3, "buy", 11)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 22}
    assert _held(artifacts) == {eng.SEC_A: 22}
    # 10000.00 less 10 at 100.00 and 11 at 90.00, plus 22 marked at 91.00.
    assert artifacts.final_state.cash_balance == Decimal("8010.00")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10012.00")


def test_a_split_booked_as_a_stock_dividend_trades_exactly_like_the_split() -> None:
    views = _pre_action_views() + (
        eng._accounting_view(
            eng.SEC_A, eng.DAY_3, open_price="27.50", close_price="30.00"
        ),
    )
    as_dividend = _run_action(
        _share_action_outcome(
            ActionKind.STOCK_DIVIDEND,
            numerator="3",
            denominator="1",
            meaning="additional_per_predecessor",
            suffix=8110,
        ),
        views,
    )
    # Control: the same four-for-one booked as a split.
    as_split = _run_action(
        _share_action_outcome(
            ActionKind.FORWARD_SPLIT,
            numerator="4",
            denominator="1",
            meaning="resulting_per_predecessor",
            suffix=8120,
        ),
        views,
    )

    for artifacts in (as_dividend, as_split):
        assert artifacts.result.classification is EvaluationClassification.COMPLETE
        assert _fills(artifacts) == [(2, "buy", 10)]
        assert _translated_targets(artifacts) == {eng.SEC_A: 40}
        assert _held(artifacts) == {eng.SEC_A: 40}
    # Before the fix the dividend sold 30 of the 40 shares at the open. The
    # two books differ only in the admission that binds their own bundle.
    economic = ("holdings", "cash_balance", "holdings_market_value")
    assert [getattr(as_dividend.final_state, name) for name in economic] == [
        getattr(as_split.final_state, name) for name in economic
    ]
    assert (
        as_dividend.result.metrics.ending_net_asset_value
        == as_split.result.metrics.ending_net_asset_value
        == Decimal("10200.00")
    )


def test_an_overnight_spinoff_with_a_staged_hold_completes_without_trading() -> None:
    outcome = _share_action_outcome(
        ActionKind.SPINOFF,
        numerator="1",
        denominator="2",
        meaning="additional_per_predecessor",
        suffix=8130,
        recipient=eng.SEC_B,
    )
    views = tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS) + (
        eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),
    )

    artifacts = _run_action(outcome, views)

    # Before the fix every staged spin-off halted: the child was held with no
    # target, so the rebalance could not tell a hold from a liquidation.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 10, eng.SEC_B: 5}
    assert _held(artifacts) == {eng.SEC_A: 10, eng.SEC_B: 5}
    # Ten parent shares at 120.00 and five child shares at 50.00.
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10450.00")


def test_an_overnight_cash_acquisition_never_rebuys_the_ended_security() -> None:
    artifacts = _run_action(
        _cash_acquisition_outcome(suffix=8140),
        tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS),
    )

    # Before the fix the kept target re-bought ten extinguished shares at
    # the session-3 open and reported 10600.00.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 0}
    assert _held(artifacts) == {}
    assert artifacts.final_state.cash_balance == Decimal("10500.00")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10500.00")


def test_a_cash_acquisition_needs_no_price_for_the_security_it_ended() -> None:
    artifacts = _run_action(_cash_acquisition_outcome(suffix=8150), _pre_action_views())

    # Before the fix the re-buy demanded a session-3 open for a security that
    # no longer trades, and the run halted.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10500.00")


def test_an_overnight_stock_acquisition_maps_a_staged_hold_to_the_acquirer() -> None:
    outcome = _share_action_outcome(
        ActionKind.STOCK_ACQUISITION,
        numerator="3",
        denominator="2",
        meaning="resulting_per_predecessor",
        suffix=8160,
        recipient=eng.SEC_B,
        claim_status="converted",
    )
    views = _pre_action_views() + (
        eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),
    )

    artifacts = _run_action(outcome, views)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 0, eng.SEC_B: 15}
    assert _held(artifacts) == {eng.SEC_B: 15}
    # Fifteen acquirer shares at 50.00 on 9000.00 of cash.
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("9750.00")


def _acquisition_into_unadmitted_acquirer(
    suffix: int, strategy: eng.FixedTargetStrategy
) -> EvaluationRunArtifactsV1:
    """SEC_A is acquired 3:2 into SEC_B, which no decision universe admits."""
    outcome = _share_action_outcome(
        ActionKind.STOCK_ACQUISITION,
        numerator="3",
        denominator="2",
        meaning="resulting_per_predecessor",
        suffix=suffix,
        recipient=eng.SEC_B,
        claim_status="converted",
    )
    views = _pre_action_views() + (
        eng._accounting_view(eng.SEC_B, eng.DAY_3, listing_id=eng.LISTING_B),
    )
    artifacts = _run_action(outcome, views, strategy)
    assert all(eng.SEC_B not in seen.admitted_universe for seen in strategy.seen)
    return artifacts


def test_a_stock_acquisition_never_turns_a_staged_increase_into_a_buy() -> None:
    # Control: the staged hold of the test above maps and completes.
    hold = _acquisition_into_unadmitted_acquirer(
        8170,
        eng.FixedTargetStrategy(
            {eng.DAY_1: ((eng.SEC_A, 10),), eng.DAY_2: ((eng.SEC_A, 10),)}
        ),
    )
    assert hold.result.classification is EvaluationClassification.COMPLETE

    artifacts = _acquisition_into_unadmitted_acquirer(
        8180,
        eng.FixedTargetStrategy(
            {eng.DAY_1: ((eng.SEC_A, 10),), eng.DAY_2: ((eng.SEC_A, 20),)}
        ),
    )

    # Before the fix twenty predecessor shares mapped to thirty acquirer
    # shares, and the open bought fifteen of a security no universe admitted.
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    assert artifacts.result.halt_reason is not None
    assert "would buy the acquirer" in artifacts.result.halt_reason
    assert _fills(artifacts) == [(2, "buy", 10)]


def test_a_stock_acquisition_never_turns_a_staged_entry_into_a_buy() -> None:
    artifacts = _acquisition_into_unadmitted_acquirer(
        8190, eng.FixedTargetStrategy({eng.DAY_2: ((eng.SEC_A, 10),)})
    )

    # Before the fix an entry staged into the predecessor bought fifteen
    # acquirer shares from an empty book.
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    assert artifacts.result.halt_reason is not None
    assert "would buy the acquirer" in artifacts.result.halt_reason
    assert _fills(artifacts) == []


# ==========================================================================
# Evidence dated off the clock, and the ex-date entitlement rule
# ==========================================================================
#
# An effect is owned by the first session on or after its date. A weekend or
# a did-not-open day is simply not a session, so the effect lands at the next
# pre-open, where nothing has traded since the prior close. A cash dividend
# vests on its ex date against that prior close, whatever the record date.

# Monday 2026-01-05 through Friday 2026-01-09, then Monday 2026-01-12.
_FRIDAY = date(2026, 1, 9)
_MONDAY = date(2026, 1, 12)
_OVER_A_WEEKEND = (*eng.DAYS, _FRIDAY, _MONDAY)


def _price_the_weekend(monkeypatch: pytest.MonkeyPatch, monday: str) -> None:
    """Give the shared engine price table the two extra sessions."""
    monkeypatch.setitem(eng.PRICES[eng.SEC_A], _FRIDAY, ("120.00", "120.00"))
    monkeypatch.setitem(eng.PRICES[eng.SEC_A], _MONDAY, (monday, monday))


def _run_over(
    outcome: SecurityEconomicOutcomeV1,
    *,
    days: tuple[date, ...],
    strategy: eng.FixedTargetStrategy,
    views: tuple[DerivedObservationViewV1, ...] | None = None,
    warmup: int = 2,
) -> EvaluationRunArtifactsV1:
    bundle = eng._bundle(
        days=days,
        decision_views=tuple(eng._decision_view(eng.SEC_A, day) for day in days),
        accounting_views=(
            tuple(eng._accounting_view(eng.SEC_A, day) for day in days)
            if views is None
            else views
        ),
        economic_outcomes=(outcome.resolution,),
    )
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=eng._admission(bundle),
        protocol=eng._protocol(warmup=warmup),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=eng.ROLE_RECORDS, economic_outcomes=(outcome,)
        ),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )
    return eng._run(engine, strategy)


def _hold_ten(days: tuple[date, ...]) -> eng.FixedTargetStrategy:
    return eng.FixedTargetStrategy({day: ((eng.SEC_A, 10),) for day in days})


def _dividend_outcome(
    *,
    suffix: int,
    ex_at: str | None,
    payable_at: str,
    record_at: str | None = None,
    settled_at: str | None = None,
    effective_at: str | None = None,
) -> SecurityEconomicOutcomeV1:
    """A 0.50 SEC_A dividend, delivered when ``settled_at`` is given."""
    cash = ca._cash(amount="0.5", component_id="dividend-cash", predecessor=eng.SEC_A)
    dates = tuple(
        ca._date_fact(role, label)
        for role, label in (
            ("ex", ex_at),
            ("record", record_at),
            ("payable", payable_at),
        )
        if label is not None
    )
    terms = ca._terms(
        suffix=suffix,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(cash,),
        dates=dates,
        security_id=eng.SEC_A,
    )
    occurrence = f"issue-82-{suffix}"
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(cash,),
        terms=terms,
        occurrence_id=occurrence,
        effective_at=(ex_at or payable_at) if effective_at is None else effective_at,
        security_id=eng.SEC_A,
    )
    deliveries = (
        ()
        if settled_at is None
        else (
            ca._delivery(
                components=(cash,),
                security_id=eng.SEC_A,
                occurrence_id=occurrence,
                settled_at=settled_at,
            ),
        )
    )
    return ca._outcome(
        security_id=eng.SEC_A,
        terms=(terms,),
        effects=(effect,),
        delivery_groups=deliveries,
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )


def _applied_sessions(artifacts: EvaluationRunArtifactsV1) -> list[int]:
    return [
        event.session_index
        for event in artifacts.trace.events
        if event.kind == "corporate_action_applied"
    ]


def _settled(artifacts: EvaluationRunArtifactsV1) -> list[tuple[int, Decimal]]:
    return [
        (event.session_index, event.settled_cash)
        for event in artifacts.trace.events
        if event.kind == "claim_settled"
    ]


def test_a_weekend_split_is_applied_at_the_next_pre_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _price_the_weekend(monkeypatch, monday="60.00")
    weekend = _share_action_outcome(
        ActionKind.FORWARD_SPLIT,
        numerator="2",
        denominator="1",
        meaning="resulting_per_predecessor",
        suffix=8200,
        effective_at="2026-01-10T00:00:00Z",
    )

    artifacts = _run_over(
        weekend, days=_OVER_A_WEEKEND, strategy=_hold_ten(_OVER_A_WEEKEND[1:5])
    )

    # Before the fix the Saturday split was never applied: ten shares were
    # marked at the halved Monday close and NAV fell to 9600.00.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [5]
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _held(artifacts) == {eng.SEC_A: 20}
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10200.00")


def test_a_split_on_a_did_not_open_day_is_applied_at_the_next_pre_open() -> None:
    days = (eng.DAY_0, eng.DAY_1, eng.DAY_3)
    outcome = eng._forward_split_outcome("2026-01-07T00:00:00Z")
    views = (
        eng._accounting_view(eng.SEC_A, eng.DAY_0),
        eng._accounting_view(eng.SEC_A, eng.DAY_1),
        eng._accounting_view(
            eng.SEC_A, eng.DAY_3, open_price="55.00", close_price="60.00"
        ),
    )
    strategy = eng.FixedTargetStrategy(
        {day: ((eng.SEC_A, 10),) for day in (eng.DAY_0, eng.DAY_1)}
    )

    artifacts = _run_over(outcome, days=days, strategy=strategy, views=views, warmup=1)

    # DAY_2 is absent from the clock, as a did-not-open day is. Before the fix
    # the split it carried was dropped and NAV fell to 9600.00.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [2]
    assert _held(artifacts) == {eng.SEC_A: 20}
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10200.00")


def test_a_holiday_record_date_still_pays_the_ex_date_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _price_the_weekend(monkeypatch, monday="120.00")
    outcome = _dividend_outcome(
        suffix=8210,
        ex_at="2026-01-09T00:00:00Z",
        record_at="2026-01-10T00:00:00Z",
        payable_at="2026-01-12T00:00:00Z",
        settled_at="2026-01-12T00:00:00Z",
    )

    artifacts = _run_over(
        outcome, days=_OVER_A_WEEKEND, strategy=_hold_ten(_OVER_A_WEEKEND[1:5])
    )

    # Before the fix the Saturday record date pinned no session and the
    # dividend was never recorded.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [4]
    assert _settled(artifacts) == [(5, Decimal("5.0"))]
    assert artifacts.final_state.cash_balance == Decimal("9005.0")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10205.00")


def test_an_ex_date_off_the_clock_vests_at_the_next_pre_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _price_the_weekend(monkeypatch, monday="120.00")
    outcome = _dividend_outcome(
        suffix=8220,
        ex_at="2026-01-10T00:00:00Z",
        payable_at="2026-01-12T00:00:00Z",
        settled_at="2026-01-12T00:00:00Z",
    )

    artifacts = _run_over(
        outcome, days=_OVER_A_WEEKEND, strategy=_hold_ten(_OVER_A_WEEKEND[1:5])
    )

    # Friday's close held ten shares and nothing traded before Monday's
    # pre-open, so the Saturday ex date pays those ten.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [5]
    assert _settled(artifacts) == [(5, Decimal("5.0"))]
    assert artifacts.final_state.cash_balance == Decimal("9005.0")


def test_a_t2_buy_at_the_ex_date_open_is_not_paid_the_dividend() -> None:
    # T+2 era: ex on DAY_2, record on DAY_3. The default strategy buys ten
    # shares at the DAY_2 open, which is the ex-date open.
    outcome = _dividend_outcome(
        suffix=8230,
        ex_at="2026-01-07T00:00:00Z",
        record_at="2026-01-08T00:00:00Z",
        payable_at="2026-01-08T00:00:00Z",
        settled_at="2026-01-08T00:00:00Z",
    )

    artifacts = _run_over(outcome, days=eng.DAYS, strategy=_hold_ten(eng.DAYS[1:]))

    # Before the fix the record-date shortcut credited 5.00. The delivered
    # report is real, but it pays the holders at the ex date's prior close,
    # and this book held nothing then.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == []
    assert _settled(artifacts) == []
    assert artifacts.final_state.cash_balance == Decimal("9000.00")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10200.00")

    # Control: with the ex date one session later, the book held ten shares
    # at the prior close and is paid.
    paid = _run_over(
        _dividend_outcome(
            suffix=8240,
            ex_at="2026-01-08T00:00:00Z",
            payable_at="2026-01-08T00:00:00Z",
            settled_at="2026-01-08T00:00:00Z",
        ),
        days=eng.DAYS,
        strategy=_hold_ten(eng.DAYS[1:]),
    )
    assert paid.result.classification is EvaluationClassification.COMPLETE
    assert _settled(paid) == [(3, Decimal("5.0"))]
    assert paid.final_state.cash_balance == Decimal("9005.0")


def test_a_held_dividend_without_an_ex_date_halts_the_run() -> None:
    outcome = _dividend_outcome(
        suffix=8250,
        ex_at=None,
        record_at="2026-01-08T00:00:00Z",
        payable_at="2026-01-08T00:00:00Z",
    )

    artifacts = _run_over(outcome, days=eng.DAYS, strategy=_hold_ten(eng.DAYS[1:]))

    # The book first holds SEC_A at the DAY_3 pre-open, and from then on its
    # dividend entitlement cannot be placed.
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    assert artifacts.result.halt_reason is not None
    assert "requires a source ex date" in artifacts.result.halt_reason


def test_delivered_cash_no_evidence_explains_halts_a_held_position() -> None:
    cash = ca._cash(amount="0.5", component_id="dividend-cash", predecessor=eng.SEC_A)
    unexplained = ca._outcome(
        security_id=eng.SEC_A,
        delivery_groups=(
            ca._delivery(
                components=(cash,),
                security_id=eng.SEC_A,
                occurrence_id="issue-82-unexplained",
                settled_at="2026-01-08T00:00:00Z",
            ),
        ),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )

    artifacts = _run_over(unexplained, days=eng.DAYS, strategy=_hold_ten(eng.DAYS[1:]))

    # Before the fix the delivered cash was dropped and the run read COMPLETE.
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    assert artifacts.result.halt_reason is not None
    assert "no proven entitlement" in artifacts.result.halt_reason

    # Control: a book that never holds SEC_A is not exposed to the report.
    flat = _run_over(unexplained, days=eng.DAYS, strategy=eng.FixedTargetStrategy({}))
    assert flat.result.classification is EvaluationClassification.COMPLETE


# --- issue 8 final acceptance: phase order and exactly-once share actions ---
#
# Spec 16 orders each session as pre-open effects, open execution,
# intrasession effects and settlement (Phase 3), then the close mark
# (Phase 4). Swapping Phases 3 and 4 leaves NAV unchanged, so only the
# cash-and-claims split of the settlement-day mark, and the session count of
# a Phase 3 halt, can tell the two orders apart.


def _session_marks(
    artifacts: EvaluationRunArtifactsV1,
) -> dict[int, tuple[Decimal, Decimal, Decimal, Decimal]]:
    return {
        point.session_index: (
            point.cash_balance,
            point.holdings_market_value,
            point.pending_claims_value,
            point.net_asset_value,
        )
        for point in artifacts.result.metrics.equity_series
    }


def test_the_settlement_day_mark_books_the_settled_claim_as_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim settled in Phase 3 is cash, not a pending claim, at that close.

    Ten shares are bought at the DAY_2 open for 1000.00. A 0.50 dividend with
    ex date DAY_3 vests on them at the DAY_3 pre-open and is paid and
    delivered on Friday, session 4. Both closes print 120.00.
    """
    _price_the_weekend(monkeypatch, monday="120.00")
    outcome = _dividend_outcome(
        suffix=8260,
        ex_at="2026-01-08T00:00:00Z",
        payable_at="2026-01-09T00:00:00Z",
        settled_at="2026-01-09T00:00:00Z",
    )

    artifacts = _run_over(
        outcome, days=_OVER_A_WEEKEND, strategy=_hold_ten(_OVER_A_WEEKEND[1:5])
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [3]
    assert _settled(artifacts) == [(4, Decimal("5.0"))]
    marks = _session_marks(artifacts)
    # DAY_3 close: the vested 5.00 is still a claim.
    assert marks[3] == (
        Decimal("9000.00"),
        Decimal("1200.00"),
        Decimal("5.0"),
        Decimal("10205.00"),
    )
    # Friday close, the settlement day: the same 5.00 is now cash.
    assert marks[4] == (Decimal("9005.0"), Decimal("1200.00"), ZERO, Decimal("10205.0"))
    (friday_mark,) = [
        event
        for event in artifacts.trace.events
        if event.kind == "session_mark" and event.session_index == 4
    ]
    assert friday_mark.cash_balance == Decimal("9005.0")
    assert friday_mark.pending_claims_value == ZERO


def test_a_settlement_halt_never_marks_the_session_it_halted() -> None:
    """A Phase 3 halt stops its session before the Phase 4 close mark.

    The metrics quote only sessions that closed, so the equity series ends at
    the last session before the halt and never quotes the halted one.
    """
    cash = ca._cash(amount="0.5", component_id="dividend-cash", predecessor=eng.SEC_A)
    unexplained = ca._outcome(
        security_id=eng.SEC_A,
        delivery_groups=(
            ca._delivery(
                components=(cash,),
                security_id=eng.SEC_A,
                occurrence_id="issue-8-unexplained",
                settled_at="2026-01-08T00:00:00Z",
            ),
        ),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND,),
    )

    artifacts = _run_over(unexplained, days=eng.DAYS, strategy=_hold_ten(eng.DAYS[1:]))

    result = artifacts.result
    assert result.classification is EvaluationClassification.INDETERMINATE
    assert result.halted_session_index == 3
    (cause,) = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert cause.session_index == 3
    assert cause.phase is EvaluationPhase.INTRASESSION_ECONOMIC_EFFECTS
    assert "no proven entitlement" in cause.cause
    assert result.metrics.evaluated_session_count == result.halted_session_index
    assert list(_session_marks(artifacts)) == [0, 1, 2]
    assert [
        event.session_index
        for event in artifacts.trace.events
        if event.kind == "session_mark"
    ] == [0, 1, 2]
    # The last marked close is DAY_2: 9000.00 cash and ten shares at 110.00.
    assert result.metrics.ending_net_asset_value == Decimal("10100.00")


def test_a_split_before_the_last_session_is_applied_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A split effective mid-run lands once, never again at a later pre-open.

    Two sessions follow the DAY_3 split here, so a window that re-applied an
    already effective split would double the book again on Friday.
    """
    monkeypatch.setitem(eng.PRICES[eng.SEC_A], _FRIDAY, ("60.00", "60.00"))
    monkeypatch.setitem(eng.PRICES[eng.SEC_A], _MONDAY, ("60.00", "60.00"))
    views = tuple(
        eng._accounting_view(eng.SEC_A, day, open_price="55.00", close_price="60.00")
        if day == eng.DAY_3
        else eng._accounting_view(eng.SEC_A, day)
        for day in _OVER_A_WEEKEND
    )
    # Ten shares are bought at the DAY_2 open. The staged hold of ten is
    # restated to twenty through the split, and every later decision asks for
    # the post-split twenty, so a correct run trades exactly once.
    strategy = eng.FixedTargetStrategy(
        {
            eng.DAY_1: ((eng.SEC_A, 10),),
            eng.DAY_2: ((eng.SEC_A, 10),),
            eng.DAY_3: ((eng.SEC_A, 20),),
            _FRIDAY: ((eng.SEC_A, 20),),
        }
    )

    artifacts = _run_over(
        eng._forward_split_outcome("2026-01-08T00:00:00Z"),
        days=_OVER_A_WEEKEND,
        strategy=strategy,
        views=views,
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _applied_sessions(artifacts) == [3]
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _held(artifacts) == {eng.SEC_A: 20}
    # 9000.00 cash plus twenty shares at the 60.00 Monday close.
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10200.00")


# ==========================================================================
# Liquidation claim status and corporate-action disposal PnL
# ==========================================================================
#
# A corporate action that extinguishes a holding for cash is a disposal. Its
# basis is relieved into realized PnL exactly as a sale at the owed price
# would relieve it, so the realized-PnL identity below closes for every book:
#
#     cash + pending claims + remaining basis
#         == initial cash + realized net PnL + distribution income
#
# Buy costs are capitalized into basis and sell costs are charged to realized
# net PnL, so the identity holds under any cost model. A distribution on
# shares that continue is income, not a disposal.

_INITIAL_CASH = Decimal("10000.00")


def _assert_realized_identity(
    artifacts: EvaluationRunArtifactsV1, *, income: Decimal = ZERO
) -> None:
    state = artifacts.final_state
    basis = sum((holding.cost_basis for holding in state.holdings), ZERO)
    assert state.cash_balance + state.pending_claims_value + basis == (
        _INITIAL_CASH + state.realized_net_pnl + income
    )


def _liquidation_outcome(
    *, suffix: int, claim_status: str, amount: str
) -> SecurityEconomicOutcomeV1:
    """A SEC_A liquidation, paid and delivered on session 3."""
    cash = ca._cash(
        amount=amount, component_id="liquidation-cash", predecessor=eng.SEC_A
    )
    payable = ca._date_fact("payable", _ACTION_AT)
    dates = (
        (ca._date_fact("ex", _ACTION_AT), payable)
        if claim_status == "continuing"
        else (payable,)
    )
    terms = ca._terms(
        suffix=suffix,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash,),
        dates=dates,
        security_id=eng.SEC_A,
    )
    occurrence = f"issue-83-{suffix}"
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash,),
        terms=terms,
        occurrence_id=occurrence,
        effective_at=_ACTION_AT,
        security_id=eng.SEC_A,
        claim_status=claim_status,
    )
    delivery = ca._delivery(
        components=(cash,),
        security_id=eng.SEC_A,
        occurrence_id=occurrence,
        settled_at=_ACTION_AT,
    )
    return ca._outcome(
        security_id=eng.SEC_A,
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(delivery,),
        action_kinds=(ActionKind.LIQUIDATION,),
    )


def _all_views() -> tuple[DerivedObservationViewV1, ...]:
    return tuple(eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS)


def test_an_extinguishing_liquidation_never_rebuys_and_books_its_gain() -> None:
    outcome = _liquidation_outcome(
        suffix=8300, claim_status="extinguished", amount="150"
    )

    artifacts = _run_action(outcome, _all_views())

    # Before the fix the kept target re-bought ten extinguished shares at
    # 110.00, NAV read 10600.00, and the disposal realized nothing.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _translated_targets(artifacts) == {eng.SEC_A: 0}
    assert _held(artifacts) == {}
    assert artifacts.final_state.cash_balance == Decimal("10500.00")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10500.00")
    # Ten shares of basis 1000.00 liquidated for 1500.00.
    assert artifacts.final_state.realized_gross_pnl == Decimal("500.00")
    assert artifacts.final_state.realized_net_pnl == Decimal("500.00")
    _assert_realized_identity(artifacts)


def test_a_cash_acquisition_books_the_gain_it_realizes() -> None:
    artifacts = _run_action(_cash_acquisition_outcome(suffix=8310), _all_views())

    # Before the fix the acquisition removed 1000.00 of basis for 1500.00 of
    # proceeds and reported realized 0, so the identity missed by 500.00.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.final_state.realized_gross_pnl == Decimal("500.00")
    assert artifacts.final_state.realized_net_pnl == Decimal("500.00")
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10500.00")
    _assert_realized_identity(artifacts)


def test_a_partial_liquidating_distribution_keeps_the_shares_that_continue() -> None:
    outcome = _liquidation_outcome(suffix=8320, claim_status="continuing", amount="3")

    artifacts = _run_action(outcome, _all_views())

    # Before the fix a continuing claim was erased like an extinguished one,
    # and the staged hold re-bought the ten shares that in fact continued.
    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert _fills(artifacts) == [(2, "buy", 10)]
    assert _held(artifacts) == {eng.SEC_A: 10}
    assert artifacts.final_state.cash_balance == Decimal("9030.00")
    # Ten shares at the 120.00 close on 9030.00 of cash.
    assert artifacts.result.metrics.ending_net_asset_value == Decimal("10230.00")
    assert artifacts.final_state.realized_gross_pnl == ZERO
    _assert_realized_identity(artifacts, income=Decimal("30.00"))


def test_a_liquidation_without_a_proven_claim_outcome_halts() -> None:
    outcome = _liquidation_outcome(suffix=8330, claim_status="unknown", amount="150")

    artifacts = _run_action(outcome, _all_views())

    # Before the fix the unknown claim was erased as if extinguished and the
    # run read COMPLETE. The control is the extinguishing case above.
    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3
    assert artifacts.result.halt_reason is not None
    assert "liquidation must prove the claim" in artifacts.result.halt_reason


@pytest.mark.parametrize("claim_status", ["extinguished", "converted"])
def test_an_overnight_split_on_an_ended_claim_halts_the_run(claim_status: str) -> None:
    views = _pre_action_views() + (
        eng._accounting_view(
            eng.SEC_A, eng.DAY_3, open_price="55.00", close_price="60.00"
        ),
    )

    def split(status: str, suffix: int) -> EvaluationRunArtifactsV1:
        return _run_action(
            _share_action_outcome(
                ActionKind.FORWARD_SPLIT,
                numerator="2",
                denominator="1",
                meaning="resulting_per_predecessor",
                suffix=suffix,
                claim_status=status,
            ),
            views,
        )

    ended = split(claim_status, 8400)

    # Issue 117: the split's own claim status says the claim ended or was
    # converted, which contradicts a split. Before the fix the ten shares
    # became twenty and the run read COMPLETE.
    assert ended.result.classification is EvaluationClassification.INDETERMINATE
    assert ended.result.halted_session_index == 3
    assert ended.result.halt_reason is not None
    assert "needs a continuing claim" in ended.result.halt_reason
    assert claim_status in ended.result.halt_reason

    # Control: the same split on a continuing claim holds twenty at 60.00.
    continuing = split("continuing", 8410)
    assert continuing.result.classification is EvaluationClassification.COMPLETE
    assert _fills(continuing) == [(2, "buy", 10)]
    assert _held(continuing) == {eng.SEC_A: 20}
    assert continuing.result.metrics.ending_net_asset_value == Decimal("10200.00")


# ==========================================================================
# Execution contract
# ==========================================================================


def test_a_missing_open_price_is_never_replaced_by_a_close() -> None:
    engine = AtomicRebalanceEngine(cost_model=ex.ZERO_COST, session_clock=ex.EXEC_CLOCK)
    state = ex._state(cash="10000.00")

    with pytest.raises(
        IndeterminateExecutionError,
        match=r"^no unadjusted open price for security",
    ):
        engine.plan(
            state=state,
            staged_targets=(ex._target(ex.SEC_A, 10),),
            open_prices={},
            execution_listings=ex._listings_for(ex.SEC_A),
        )

    # Control: the identical rebalance plans cleanly once the open is supplied.
    plan = engine.plan(
        state=state,
        staged_targets=(ex._target(ex.SEC_A, 10),),
        open_prices={ex.SEC_A: ex._price("100.00")},
        execution_listings=ex._listings_for(ex.SEC_A),
    )
    assert plan.is_funded


def test_a_negative_target_quantity_is_not_constructible() -> None:
    with pytest.raises(ValidationError) as error:
        SecurityTargetPositionV1(security_id=ex.SEC_A, target_quantity=-1)

    assert [item["type"] for item in error.value.errors(include_url=False)] == [
        "greater_than_equal"
    ]


def test_a_costed_run_matches_an_independent_exact_computation() -> None:
    """Nonzero costs through the whole engine, checked by exact Fractions.

    Commission 0.005 per share, a 1.00 fixed fee, 2.5 bps of the unadjusted
    open notional, and 7 bps adverse slippage on the fill price (spec 11.4 and
    14). Every expected number is derived here from the engine's own
    accounting-view prices, never read back from the engine.
    """
    engine = eng._engine(
        cost_model=eng._cost_model(
            model_id="costed-v1",
            commission="0.005",
            fixed_fee="1.00",
            notional_bps="2.5",
            slippage_bps="7",
        )
    )

    artifacts = eng._run(engine, eng._buy_ten())

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    (fill,) = [event.fill for event in artifacts.trace.events if event.kind == "fill"]
    fill_session = next(
        event.session_key for event in artifacts.trace.events if event.kind == "fill"
    )
    open_price = Fraction(
        source_basis_price(
            next(
                view
                for view in engine.bundle.authentic_accounting_views
                if view.source_session == fill_session
            ),
            "open",
        )
    )
    quantity = Fraction(fill.quantity)
    fill_price = open_price * (1 + Fraction(7, 10_000))
    costs = (
        quantity * Fraction("0.005")
        + Fraction("1.00")
        + open_price * quantity * Fraction(25, 100_000)
    )
    assert Fraction(fill.fill_price) == fill_price
    assert Fraction(fill.transaction_costs) == costs

    final = artifacts.final_state
    initial_cash = Fraction(engine.protocol.initial_cash)
    assert Fraction(final.cash_balance) == initial_cash - fill_price * quantity - costs
    (holding,) = final.holdings
    assert Fraction(holding.cost_basis) == fill_price * quantity + costs
    assert final.mark is not None
    (mark,) = final.mark.prices
    market_value = Fraction(mark.close_price) * quantity
    assert (
        Fraction(final.net_asset_value) == Fraction(final.cash_balance) + market_value
    )
    # NAV identity: the change in NAV is realized net PnL plus unrealized PnL.
    metrics = artifacts.result.metrics
    assert Fraction(final.net_asset_value) - initial_cash == (
        Fraction(metrics.realized_net_pnl) + market_value - Fraction(holding.cost_basis)
    )


def test_a_costed_partial_sell_matches_an_independent_exact_computation() -> None:
    """A costed sell: adverse slippage, net proceeds, proportional basis relief.

    Commission 0.01 per share, a 1.00 fixed fee, 10 bps of the unadjusted
    open notional, and 5 bps adverse slippage. Every number is computed by
    hand from the fixture prices.

    Buy 10 at the DAY_2 open of 100.00: fill 100.05, gross 1000.50, costs
    0.10 + 1.00 + 1.00 = 2.10. Cash 8997.40, basis 1002.60.

    Sell 6 at the DAY_3 open of 110.00: fill 110 x 0.9995 = 109.945, gross
    659.67, costs 0.06 + 1.00 + 0.66 = 1.72, net proceeds 657.95. Cash
    9655.35. Relieved basis 1002.60 x 6/10 = 601.56, leaving 401.04.
    Realized gross 659.67 - 601.56 = 58.11, net 58.11 - 1.72 = 56.39.

    Four shares marked at the DAY_3 close of 120.00: NAV 9655.35 + 480.00.
    """
    engine = eng._engine(
        cost_model=eng._cost_model(
            model_id="costed-sell-v1",
            commission="0.01",
            fixed_fee="1.00",
            notional_bps="10",
            slippage_bps="5",
        )
    )
    strategy = eng.FixedTargetStrategy(
        {eng.DAY_1: ((eng.SEC_A, 10),), eng.DAY_2: ((eng.SEC_A, 4),)}
    )

    artifacts = eng._run(engine, strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    fills = [
        (event.session_index, event.fill)
        for event in artifacts.trace.events
        if event.kind == "fill"
    ]
    assert [(index, fill.side, fill.quantity) for index, fill in fills] == [
        (2, "buy", 10),
        (3, "sell", 6),
    ]
    _, sell = fills[1]
    assert sell.fill_price == Decimal("109.945")
    assert sell.gross_notional == Decimal("659.67")
    assert sell.transaction_costs == Decimal("1.72")
    assert sell.cash_delta == Decimal("657.95")

    final = artifacts.final_state
    assert final.cash_balance == Decimal("9655.35")
    assert [(item.quantity, item.cost_basis) for item in final.holdings] == [
        (4, Decimal("401.04"))
    ]
    assert final.realized_gross_pnl == Decimal("58.11")
    assert final.realized_net_pnl == Decimal("56.39")
    assert final.cumulative_transaction_costs == Decimal("3.82")
    assert final.net_asset_value == Decimal("10135.35")
    metrics = artifacts.result.metrics
    assert metrics.realized_net_pnl == Decimal("56.39")
    assert metrics.gross_traded_notional == Decimal("1660.17")
    # Realized-PnL identity: cash plus remaining basis is initial cash plus
    # realized net PnL, 9655.35 + 401.04 == 10000.00 + 56.39.
    _assert_realized_identity(artifacts)


def test_a_split_adjusted_field_method_cannot_become_a_reconstructed_price() -> None:
    """Double adjustment, reconstructed lane (#54): the per-field basis guard.

    The contract is unadjusted but its close method is split adjusted. The
    contract-level check passes, so only the per-field guard in the canonical
    builder stands between that close and an exploratory accounting price.
    """
    from observation_test_support import ObservationHarness
    from test_evaluator_reconstruction import build_from_harness

    observed = ObservationHarness(close="100.000")
    methods = tuple(
        method.model_copy(update={"adjustment_basis": "split_adjusted"})
        if method.field_name == "close"
        else method
        for method in observed._contract.field_methods
    )
    observed._replace_contract(field_methods=methods)
    observed._records = (observed._reseal_record(observed._records[0]),)
    observed._rebuild()
    observed.attach_sessions(schedule_state="regular", realized_outcome="missing")
    assert observed._contract.adjustment_basis == "unadjusted"

    with pytest.raises(ValueError, match=r"^field close method must be unadjusted$"):
        build_from_harness(observed)


def test_a_fractional_target_quantity_is_not_constructible() -> None:
    for quantity in (1.5, Decimal("1.5"), "1"):
        with pytest.raises(ValidationError) as error:
            SecurityTargetPositionV1(
                security_id=ex.SEC_A,
                target_quantity=quantity,  # type: ignore[arg-type]
            )
        assert [item["loc"] for item in error.value.errors(include_url=False)] == [
            ("target_quantity",)
        ]


class _ForgedFractionalStrategy(eng.FixedTargetStrategy):
    """Returns a target that skipped its own contract: 10.5 shares."""

    def decide(self, context):  # type: ignore[no-untyped-def]
        intent = super().decide(context)
        forged = SecurityTargetPositionV1.model_construct(
            schema_version="1", security_id=eng.SEC_A, target_quantity=Decimal("10.5")
        )
        return intent.model_construct(**(dict(intent) | {"targets": (forged,)}))


def test_a_forged_fractional_target_rejects_the_run() -> None:
    """Issue 88: whole shares only, and a forged fraction is REJECTED, not FAILED."""
    strategy = _ForgedFractionalStrategy({eng.DAY_1: ((eng.SEC_A, 10),)})

    artifacts = eng._run(eng._engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.metrics.committed_fill_count == 0


def test_a_negative_staged_target_is_refused_by_the_rebalance_engine() -> None:
    """A forged target that skipped its own contract still fails closed."""
    forged = SecurityTargetPositionV1.model_construct(
        schema_version="1", security_id=ex.SEC_A, target_quantity=-1
    )
    engine = AtomicRebalanceEngine(cost_model=ex.ZERO_COST, session_clock=ex.EXEC_CLOCK)

    with pytest.raises(
        ValueError, match=r"^staged target quantity must be non-negative"
    ):
        engine.plan(
            state=ex._state(cash="10000.00"),
            staged_targets=(forged,),
            open_prices={ex.SEC_A: ex._price("100.00")},
            execution_listings=ex._listings_for(ex.SEC_A),
        )


def test_an_unfunded_rebalance_leaves_the_book_completely_untouched() -> None:
    engine = AtomicRebalanceEngine(cost_model=ex.ZERO_COST, session_clock=ex.EXEC_CLOCK)
    state = ex._state(cash="100.00")

    outcome = engine.rebalance(
        state=state,
        staged_targets=(ex._target(ex.SEC_A, 10),),
        open_prices={ex.SEC_A: ex._price("100.00")},
        execution_listings=ex._listings_for(ex.SEC_A),
    )

    assert outcome.classification == "rejected"
    assert outcome.committed_fills == ()
    assert outcome.halt_stepping is True
    assert outcome.state is state
    assert outcome.state.holdings == ()
    assert outcome.state.cash_balance == Decimal("100.00")
    assert outcome.rejection is not None
    assert outcome.rejection.cash_shortfall == Decimal("900.00")


def test_a_plan_unfunded_only_by_its_sell_costs_is_rejected_whole() -> None:
    """Funding counts sell costs (spec 13.2 step 3), not only buy costs.

    Selling one SEC_A at 100.00 raises 100.00 gross but 99.00 after its 1.00
    fee. Buying one SEC_B at 98.50 needs 99.50 with its own fee. Gross
    proceeds would cover the buy with 0.50 to spare; net proceeds leave it
    0.50 short. A funding check that ignored sell costs would call the plan
    funded, book the sell, run out of cash on the buy, and abort the whole
    rebalance instead of rejecting the intent cleanly.
    """
    engine = AtomicRebalanceEngine(cost_model=ex.FEE_ONLY, session_clock=ex.EXEC_CLOCK)
    state = ex._state(cash="0.00", holdings=(ex._holding(ex.SEC_A, 1, "100.00"),))
    targets = (ex._target(ex.SEC_A, 0), ex._target(ex.SEC_B, 1))
    listings = ex._listings_for(ex.SEC_A, ex.SEC_B)
    prices = {ex.SEC_A: ex._price("100.00"), ex.SEC_B: ex._price("98.50")}

    plan = engine.plan(
        state=state,
        staged_targets=targets,
        open_prices=prices,
        execution_listings=listings,
    )

    assert plan.gross_sell_proceeds == Decimal("100.00")
    assert plan.sell_transaction_costs == Decimal("1.00")
    assert plan.required_cash == Decimal("99.50")
    assert plan.projected_cash == Decimal("-0.50")
    assert plan.is_funded is False

    outcome = engine.execute(state=state, plan=plan)

    assert outcome.classification == "rejected"
    assert outcome.committed_fills == ()
    assert outcome.halt_stepping is True
    assert outcome.state is state
    assert outcome.rejection is not None
    assert outcome.rejection.cash_shortfall == Decimal("0.50")

    # Control: 0.50 cheaper, the same rotation is funded to the cent and
    # commits both legs, ending with exactly zero cash.
    funded = engine.rebalance(
        state=state,
        staged_targets=targets,
        open_prices=prices | {ex.SEC_B: ex._price("98.00")},
        execution_listings=listings,
    )
    assert funded.plan.projected_cash == ZERO
    assert funded.classification == "executed"
    assert [fill.side for fill in funded.committed_fills] == ["sell", "buy"]
    assert funded.state.cash_balance == ZERO


def test_a_rejected_rebalance_cannot_be_relabelled_with_committed_fills() -> None:
    engine = AtomicRebalanceEngine(cost_model=ex.ZERO_COST, session_clock=ex.EXEC_CLOCK)
    outcome = engine.rebalance(
        state=ex._state(cash="100.00"),
        staged_targets=(ex._target(ex.SEC_A, 10),),
        open_prices={ex.SEC_A: ex._price("100.00")},
        execution_listings=ex._listings_for(ex.SEC_A),
    )
    assert outcome.plan.planned_fills

    with pytest.raises(
        ValidationError, match=r"a rejected rebalance must commit zero fills"
    ):
        RebalanceOutcomeV1.model_validate(
            dict(outcome) | {"committed_fills": outcome.plan.planned_fills}
        )


def test_a_sell_fee_exceeding_its_proceeds_cannot_abort_a_funded_rebalance() -> None:
    """Canonical commit order is load-bearing, not an implementation detail."""
    engine = AtomicRebalanceEngine(cost_model=ex.FEE_ONLY, session_clock=ex.EXEC_CLOCK)
    state = ex._state(
        cash="0.00",
        holdings=(
            ex._holding(ex.SEC_A, 1, "100.00"),
            ex._holding(ex.SEC_B, 1, "1.00"),
        ),
    )
    prices = {ex.SEC_A: ex._price("100.00"), ex.SEC_B: ex._price("0.50")}

    outcome = engine.rebalance(
        state=state,
        staged_targets=(ex._target(ex.SEC_A, 0), ex._target(ex.SEC_B, 0)),
        open_prices=prices,
        execution_listings=ex._listings_for(ex.SEC_A, ex.SEC_B),
    )

    assert outcome.classification == "executed"
    assert [fill.security_id for fill in outcome.committed_fills] == [
        ex.SEC_A,
        ex.SEC_B,
    ]
    # Control: the reverse order genuinely cannot be booked, so the canonical
    # order is what keeps a funded plan committable.
    reversed_kernel = PortfolioAccountingKernel(state, session_clock=ex.EXEC_CLOCK)
    with pytest.raises(ValueError, match=r"^insufficient cash for sell costs"):
        for fill in reversed(outcome.committed_fills):
            reversed_kernel.apply_fill(fill.to_portfolio_fill())


def test_a_zero_warmup_protocol_is_rejected() -> None:
    draft = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="zero-warmup",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=0,
        initial_cash=Decimal("10000.00"),
        protocol_hash="0" * 64,
    )
    payload = dict(draft) | {"protocol_hash": evaluation_protocol_hash(draft)}

    with pytest.raises(
        ValidationError, match=r"warmup_session_count must be at least 1"
    ):
        EvaluationProtocolV1.model_validate(payload)

    # Control: the identical protocol validates at the minimum legal warmup.
    minimal = EvaluationProtocolV1.model_construct(
        **(dict(draft) | {"warmup_session_count": 1})
    )
    EvaluationProtocolV1.model_validate(
        dict(minimal) | {"protocol_hash": evaluation_protocol_hash(minimal)}
    )
