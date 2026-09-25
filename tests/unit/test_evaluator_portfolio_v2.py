"""Unit tests for the versioned M2 portfolio state (issues 49, 103 and 105).

``PortfolioStateV2`` and ``SecurityHoldingV2`` are successors, not edits. The
V1 accounting surface is frozen (#50): its models keep their exact schema and
their exact bytes, and the pins below fail on any change to either. The M2
stack moves to V2 wholesale, so there is one accounting truth, and nothing
lifts a V1 book into V2: a lift would launder the zero basis a V1 spin-off
child carries (#103) as a known one.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
import test_evaluator_corporate_actions as ca
from observation_test_support import uid
from pydantic import BaseModel, ValidationError, create_model

import drift.errors
from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_corporate_actions import SecurityEconomicOutcomeV1
from drift.domain.evaluator_execution import (
    RebalanceOutcomeV1,
    RebalanceOutcomeV2,
    RebalancePlanV1,
    positions_digest,
)
from drift.domain.evaluator_portfolio import (
    APPLIED_EFFECT_ID_PROFILE,
    EffectAlreadyAppliedError,
    IndeterminateBasisError,
    IndeterminateValuationError,
    MarkEvidenceV1,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioMarkV1,
    PortfolioStateV1,
    PortfolioStateV2,
    SecurityHoldingV1,
    SecurityHoldingV2,
    applied_economic_effect_id,
    pending_cash_claim_id,
)
from drift.domain.evaluator_strategy import PositionViewV1, SecurityTargetPositionV1
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.serialization.canonical import content_hash

SEC_A = uid(21)
SEC_B = uid(22)
DAY = date(2026, 1, 2)
ADMISSION_HASH = "a" * 64
EVIDENCE_HASH = "b" * 64

SPINOFF_ID = applied_economic_effect_id(
    source_id="source-a", security_id=SEC_A, occurrence_id="spin-1"
)
SPLIT_ID = applied_economic_effect_id(
    source_id="source-a", security_id=SEC_A, occurrence_id="split-1"
)


def _key(day: date = DAY) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


# ==========================================================================
# The V1 accounting surface stays byte-identical (#50 freeze)
# ==========================================================================

#: sha256 over each frozen V1 model's canonical ``model_json_schema()``, taken
#: at main 5dd05cd before any V2 model existed. A new field, a changed type, a
#: changed default or a renamed field each move the fingerprint.
V1_SCHEMA_FINGERPRINTS: dict[type[BaseModel], str] = {
    SecurityHoldingV1: (
        "b3dd9df9a0faace64cbd85040371cb936a59563b4bad19530cc5276a48f205af"
    ),
    PendingCashClaimV1: (
        "d049aed2750ea4392e75c0412eb67753c9780824fa816c94764db1027e7b08be"
    ),
    PortfolioFillV1: (
        "a0a7b65c8f7b95d4311c1ace0dd099e01d78270d1c4d693b8c93ce80585808e2"
    ),
    MarkEvidenceV1: (
        "546b396f2013664fbdb890e2383475b7bece08a12ead7db4e9dfb8763c42740c"
    ),
    MarkPriceV1: ("19244d89a77f736858910971909e1f8bb22fba212c93b12f3a54f68c99abd78c"),
    PortfolioMarkV1: (
        "99f259c8ee5784280afa7fb3d9cb8f13e4e719ee974bf61b7d259be1c5d54135"
    ),
    PortfolioStateV1: (
        "dc71c12b7dcea3870d3464ae0aa8d2712ece807e8be5d9ee803ca2624860658e"
    ),
    RebalanceOutcomeV1: (
        "88bac385fd075cccdbb5490d6532241b400b8c57d40857c2f288d2d9c28bec92"
    ),
}


@pytest.mark.parametrize(
    "model", list(V1_SCHEMA_FINGERPRINTS), ids=lambda model: model.__name__
)
def test_a_frozen_v1_model_keeps_its_exact_schema(model: type[BaseModel]) -> None:
    assert content_hash(model.model_json_schema()) == V1_SCHEMA_FINGERPRINTS[model]


def test_the_schema_fingerprint_sees_one_added_defaulted_field() -> None:
    # Non-vacuity: the smallest additive change, a defaulted field, moves it.
    extended = create_model(
        "SecurityHoldingV1",
        __base__=SecurityHoldingV1,
        basis_status=(str, "known"),
    )
    assert (
        content_hash(extended.model_json_schema())
        != V1_SCHEMA_FINGERPRINTS[SecurityHoldingV1]
    )


def _v1_book() -> PortfolioStateV1:
    claim = PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            source_id="source-a",
            security_id=SEC_A,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-1",
            component_id="cash-1",
        ),
        source_id="source-a",
        security_id=SEC_A,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        occurrence_id="occ-1",
        component_id="cash-1",
        entitled_quantity=10,
        cash_per_share=Decimal("0.5"),
        total_cash_expected=Decimal("5"),
        entitlement_session=DAY,
        payable_session=DAY,
    )
    mark = PortfolioMarkV1(
        session_key=_key(),
        lane="exploratory",
        prices=(
            MarkPriceV1(
                security_id=SEC_A,
                close_price=Decimal("12"),
                evidence=MarkEvidenceV1(
                    grade="exploratory", evidence_hash=EVIDENCE_HASH
                ),
            ),
        ),
    )
    return PortfolioStateV1(
        lane="exploratory",
        admission_hash=ADMISSION_HASH,
        session_key=_key(),
        cash_balance=Decimal("880"),
        holdings=(
            SecurityHoldingV1(
                security_id=SEC_A, quantity=10, cost_basis=Decimal("120")
            ),
        ),
        pending_cash_claims=(claim,),
        settled_claim_ids=(),
        mark=mark,
        holdings_market_value=Decimal("120"),
        pending_claims_value=Decimal("5"),
        net_asset_value=Decimal("1005"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )


def test_a_v1_book_keeps_its_exact_bytes() -> None:
    # A frozen model with an unchanged schema could still dump differently.
    assert content_hash(_v1_book()) == (
        "0f12f17c58888bc12dc32ffa861c580d71a5f2f4ca23cf88becb23ba3abcb615"
    )


# ==========================================================================
# Characterization pins the V2 switch must not move
# ==========================================================================


def test_a_known_position_view_dumps_exactly_as_before() -> None:
    # The decision context hash covers every position view, so a known view
    # must dump identically after its basis fields become nullable.
    view = PositionViewV1(
        security_id=SEC_A,
        quantity=8,
        cost_basis=Decimal("100.00"),
        average_cost_per_share=Decimal("12.5"),
    )
    assert content_hash(view.model_dump(mode="python")) == (
        "51612f12616595b87e16fbac0dcc25e396573f7b09b4dee6edb659be6173d00b"
    )
    assert view.model_dump_json() == (
        '{"schema_version":"1","security_id":"01990000-0000-7000-8000-000000000021",'
        '"quantity":8,"cost_basis":"100.00","average_cost_per_share":"12.5"}'
    )


def test_the_positions_digest_stays_quantity_only() -> None:
    # Pinned over V1 holdings before the switch; the V2 digest is identical,
    # whatever the basis status.
    holdings = (
        SecurityHoldingV2(
            security_id=SEC_A,
            quantity=8,
            basis_status="known",
            cost_basis=Decimal("1"),
        ),
        SecurityHoldingV2(
            security_id=SEC_B,
            quantity=3,
            basis_status="indeterminate",
            cost_basis=None,
            basis_indeterminate_by=(SPINOFF_ID,),
        ),
    )
    assert positions_digest(holdings) == (
        "8a2d1319a0a7eaca6b22ccecaee4216abe042942eacdaa21f39abe4a435fc149"
    )


# ==========================================================================
# Applied-effect identity (issue 49)
# ==========================================================================


def test_applied_effect_identity_is_a_versioned_content_hash() -> None:
    assert APPLIED_EFFECT_ID_PROFILE == "drift-applied-economic-effect-v1"
    assert SPINOFF_ID == content_hash(
        {
            "profile": "drift-applied-economic-effect-v1",
            "source_id": "source-a",
            "security_id": str(SEC_A),
            "occurrence_id": "spin-1",
        }
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"source_id": "source-b"},
        {"security_id": SEC_B},
        {"occurrence_id": "spin-2"},
    ],
)
def test_applied_effect_identity_depends_on_every_identity_input(
    changed: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "source_id": "source-a",
        "security_id": SEC_A,
        "occurrence_id": "spin-1",
    }
    assert applied_economic_effect_id(**(values | changed)) != SPINOFF_ID


def test_applied_effect_identity_never_collides_with_a_claim_identity() -> None:
    # Same source, security and occurrence: the profiles keep the spaces apart.
    claim = pending_cash_claim_id(
        source_id="source-a",
        security_id=SEC_A,
        action_kind=ActionKind.SPINOFF,
        occurrence_id="spin-1",
        component_id="shares-1",
    )
    assert claim != SPINOFF_ID


def test_the_v2_errors_fail_closed_as_indeterminate_valuations() -> None:
    # The engine classifies an IndeterminateValuationError as INDETERMINATE,
    # and neither error lives in drift.errors, which both M1d closures hold.
    for error in (EffectAlreadyAppliedError, IndeterminateBasisError):
        assert issubclass(error, IndeterminateValuationError)
        assert not hasattr(drift.errors, error.__name__)


# ==========================================================================
# SecurityHoldingV2: basis status (issues 103 and 105)
# ==========================================================================


def _known(quantity: int = 10, basis: str = "100") -> SecurityHoldingV2:
    return SecurityHoldingV2(
        security_id=SEC_A,
        quantity=quantity,
        basis_status="known",
        cost_basis=Decimal(basis),
    )


def _indeterminate(
    *causes: str, security_id: Any = SEC_A, quantity: int = 10
) -> SecurityHoldingV2:
    return SecurityHoldingV2(
        security_id=security_id,
        quantity=quantity,
        basis_status="indeterminate",
        cost_basis=None,
        basis_indeterminate_by=tuple(sorted(causes)) or (SPINOFF_ID,),
    )


def test_a_known_holding_carries_its_exact_basis() -> None:
    holding = _known(quantity=8, basis="100")
    assert holding.schema_version == "2"
    assert holding.basis_indeterminate_by == ()
    assert holding.average_cost_per_share == Decimal("12.5")


def test_an_indeterminate_holding_carries_no_basis_at_all() -> None:
    holding = _indeterminate(SPINOFF_ID)
    assert holding.cost_basis is None
    assert holding.average_cost_per_share is None
    assert holding.basis_indeterminate_by == (SPINOFF_ID,)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"basis_status": "known", "cost_basis": None},
            "a known basis requires an exact cost basis",
        ),
        (
            {"basis_status": "known", "cost_basis": Decimal("-1")},
            "cost basis must be non-negative",
        ),
        (
            {
                "basis_status": "known",
                "cost_basis": Decimal("1"),
                "basis_indeterminate_by": (SPINOFF_ID,),
            },
            "a known basis cannot name an indeterminacy cause",
        ),
        (
            {
                "basis_status": "indeterminate",
                "cost_basis": Decimal("0"),
                "basis_indeterminate_by": (SPINOFF_ID,),
            },
            "an indeterminate basis cannot carry a cost basis",
        ),
        (
            {"basis_status": "indeterminate", "cost_basis": None},
            "an indeterminate basis must name the effects that made it so",
        ),
        (
            {
                "basis_status": "indeterminate",
                "cost_basis": None,
                "basis_indeterminate_by": (SPINOFF_ID, SPINOFF_ID),
            },
            "indeterminacy causes must be unique",
        ),
        (
            {
                "basis_status": "indeterminate",
                "cost_basis": None,
                "basis_indeterminate_by": tuple(
                    sorted((SPINOFF_ID, SPLIT_ID), reverse=True)
                ),
            },
            "indeterminacy causes must be canonically sorted",
        ),
        (
            {"basis_status": "unknown", "cost_basis": Decimal("1")},
            "basis_status",
        ),
    ],
)
def test_a_holding_refuses_every_inconsistent_basis_status(
    values: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SecurityHoldingV2(security_id=SEC_A, quantity=10, **values)


def test_a_holding_states_its_basis_status_explicitly() -> None:
    # No default: a holding never becomes known by omission.
    with pytest.raises(ValidationError, match="basis_status"):
        SecurityHoldingV2(security_id=SEC_A, quantity=10, cost_basis=Decimal("1"))  # type: ignore[call-arg]


def test_a_holding_refuses_a_non_positive_quantity() -> None:
    with pytest.raises(ValidationError):
        _known(quantity=0)


def test_a_v1_holding_is_not_a_v2_holding() -> None:
    # No lift: a V1 holding cannot say whether its basis is known.
    v1 = SecurityHoldingV1(security_id=SEC_A, quantity=10, cost_basis=Decimal("0"))
    with pytest.raises(ValidationError):
        SecurityHoldingV2.model_validate(v1.model_dump())


# ==========================================================================
# PortfolioStateV2
# ==========================================================================


def _v2_book(
    *,
    holdings: tuple[SecurityHoldingV2, ...] = (),
    applied: tuple[str, ...] = (),
    cash: str = "880",
) -> PortfolioStateV2:
    return PortfolioStateV2(
        lane="exploratory",
        admission_hash=ADMISSION_HASH,
        session_key=_key(),
        cash_balance=Decimal(cash),
        holdings=holdings,
        pending_cash_claims=(),
        settled_claim_ids=(),
        applied_effect_ids=applied,
        mark=None,
        holdings_market_value=Decimal("0"),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal(cash),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
    )


def test_a_v2_book_records_the_effects_it_absorbed() -> None:
    book = _v2_book(
        holdings=(_indeterminate(SPINOFF_ID),),
        applied=tuple(sorted((SPINOFF_ID, SPLIT_ID))),
    )
    assert book.schema_version == "2"
    assert set(book.applied_effect_ids) == {SPINOFF_ID, SPLIT_ID}


def test_an_empty_v2_book_has_applied_nothing() -> None:
    assert _v2_book().applied_effect_ids == ()


@pytest.mark.parametrize(
    ("applied", "message"),
    [
        ((SPLIT_ID, SPLIT_ID), "applied effect ids must be unique"),
        (
            tuple(sorted((SPINOFF_ID, SPLIT_ID), reverse=True)),
            "applied effect ids must be canonically sorted",
        ),
    ],
)
def test_a_v2_book_keeps_its_applied_effects_canonical(
    applied: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _v2_book(applied=applied)


def test_an_indeterminate_holding_names_only_effects_the_book_applied() -> None:
    with pytest.raises(
        ValidationError, match="names an indeterminacy cause the book never applied"
    ):
        _v2_book(holdings=(_indeterminate(SPINOFF_ID),), applied=(SPLIT_ID,))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cash_balance": Decimal("-1")}, "cash balance must be non-negative"),
        ({"net_asset_value": Decimal("1")}, "net asset value must reconcile"),
        (
            {"holdings_market_value": Decimal("5"), "net_asset_value": Decimal("885")},
            "state without holdings cannot carry a market value",
        ),
        ({"settled_claim_ids": ("b" * 64, "a" * 64)}, "canonically sorted"),
    ],
)
def test_a_v2_book_holds_every_invariant_a_v1_book_holds(
    changes: dict[str, Any], message: str
) -> None:
    values = _v2_book().model_dump(mode="python") | changes
    with pytest.raises(ValidationError, match=message):
        PortfolioStateV2.model_validate(values)


def test_a_v2_book_refuses_two_holdings_of_one_security() -> None:
    with pytest.raises(ValidationError, match="at most one entry per security"):
        _v2_book(holdings=(_known(), _known(quantity=2)))


def test_a_mark_never_reads_the_basis_status() -> None:
    # NAV is priced from quantities and closes alone, known or not.
    prices = (
        MarkPriceV1(
            security_id=SEC_A,
            close_price=Decimal("12"),
            evidence=MarkEvidenceV1(grade="exploratory", evidence_hash=EVIDENCE_HASH),
        ),
    )
    mark = PortfolioMarkV1(session_key=_key(), lane="exploratory", prices=prices)
    for holding in (_known(), _indeterminate(SPINOFF_ID)):
        values = _v2_book(holdings=(holding,), applied=(SPINOFF_ID,)).model_dump(
            mode="python"
        ) | {
            "mark": mark,
            "holdings_market_value": Decimal("120"),
            "net_asset_value": Decimal("1000"),
        }
        assert PortfolioStateV2.model_validate(values).net_asset_value == Decimal(
            "1000"
        )


def test_a_v1_book_is_never_lifted_into_v2() -> None:
    with pytest.raises(ValidationError):
        PortfolioStateV2.model_validate(_v1_book().model_dump(mode="python"))


def test_a_v2_book_round_trips_through_json() -> None:
    book = _v2_book(holdings=(_indeterminate(SPINOFF_ID),), applied=(SPINOFF_ID,))
    assert PortfolioStateV2.model_validate_json(book.model_dump_json()) == book


# ==========================================================================
# Nullable position view basis (issue 103)
# ==========================================================================


def test_a_position_view_of_an_indeterminate_basis_shows_no_number() -> None:
    view = PositionViewV1(
        security_id=SEC_A, quantity=5, cost_basis=None, average_cost_per_share=None
    )
    assert view.cost_basis is None
    assert view.average_cost_per_share is None


@pytest.mark.parametrize(
    ("basis", "average"),
    [(Decimal("100"), None), (None, Decimal("20"))],
)
def test_a_position_view_refuses_a_half_indeterminate_basis(
    basis: Decimal | None, average: Decimal | None
) -> None:
    with pytest.raises(ValidationError, match="leaves both the cost basis and"):
        PositionViewV1(
            security_id=SEC_A,
            quantity=5,
            cost_basis=basis,
            average_cost_per_share=average,
        )


# ==========================================================================
# RebalanceOutcomeV2
# ==========================================================================


def _empty_plan() -> RebalancePlanV1:
    return RebalancePlanV1(
        session_key=_key(),
        planned_fills=(),
        opening_positions_hash=positions_digest(()),
        current_cash=Decimal("880"),
        gross_sell_proceeds=Decimal("0"),
        sell_transaction_costs=Decimal("0"),
        required_cash=Decimal("0"),
        projected_cash=Decimal("880"),
    )


def test_a_v2_outcome_carries_a_v2_book() -> None:
    outcome = RebalanceOutcomeV2(
        classification="executed",
        plan=_empty_plan(),
        committed_fills=(),
        rejection=None,
        state=_v2_book(),
        halt_stepping=False,
    )
    assert outcome.schema_version == "2"
    assert outcome.state == _v2_book()


def test_a_v2_outcome_refuses_a_v1_book() -> None:
    with pytest.raises(ValidationError):
        RebalanceOutcomeV2(
            classification="executed",
            plan=_empty_plan(),
            committed_fills=(),
            rejection=None,
            state=_v1_book(),  # type: ignore[arg-type]
            halt_stepping=False,
        )


def test_a_v2_outcome_keeps_the_all_or_nothing_shape() -> None:
    with pytest.raises(ValidationError, match="must not halt session stepping"):
        RebalanceOutcomeV2(
            classification="executed",
            plan=_empty_plan(),
            committed_fills=(),
            rejection=None,
            state=_v2_book(),
            halt_stepping=True,
        )
    with pytest.raises(ValidationError, match="requires its rejection"):
        RebalanceOutcomeV2(
            classification="rejected",
            plan=_empty_plan(),
            committed_fills=(),
            rejection=None,
            state=_v2_book(),
            halt_stepping=True,
        )


# ==========================================================================
# The replay gate (issue 49)
# ==========================================================================
#
# A pass records the applied-effect identity of every share-mutating effect
# it owns, exposed or not, and refuses one the book already absorbed when the
# book is exposed to a security it touches. Staged targets are not state, so
# a replay cannot be proven a no-op for a staged buy: it fails closed.


def _share_outcome(
    suffix: int,
    *,
    security_id: UUID = ca.SEC_A,
    occurrence: str = "occ-1",
    kind: ActionKind = ActionKind.FORWARD_SPLIT,
    effective_at: str = ca.EFFECT_AT,
    numerator: str = "2",
    denominator: str = "1",
    meaning: str = "resulting_per_predecessor",
    source_id: str = ca.SOURCE_A,
) -> SecurityEconomicOutcomeV1:
    component = ca._shares(
        numerator=numerator,
        denominator=denominator,
        recipient=security_id,
        predecessor=security_id,
        meaning=meaning,
    )
    terms = ca._terms(
        suffix=suffix,
        action_kind=kind,
        components=(component,),
        security_id=security_id,
        source_id=source_id,
    )
    effect = ca._effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=(component,),
        terms=terms,
        occurrence_id=occurrence,
        effective_at=effective_at,
        security_id=security_id,
        source_id=source_id,
    )
    return ca._outcome(
        security_id=security_id, terms=(terms,), effects=(effect,), action_kinds=(kind,)
    )


def _effect_id(
    security_id: UUID = ca.SEC_A,
    occurrence: str = "occ-1",
    source_id: str = ca.SOURCE_A,
) -> str:
    return applied_economic_effect_id(
        source_id=source_id, security_id=security_id, occurrence_id=occurrence
    )


def _pass(
    state: PortfolioStateV2,
    outcomes: tuple[SecurityEconomicOutcomeV1, ...],
    *,
    day: date = ca.EFFECT_DAY,
    targets: tuple[SecurityTargetPositionV1, ...] = (),
) -> tuple[PortfolioStateV2, tuple[SecurityTargetPositionV1, ...]]:
    return ca._processor().apply_pre_open_actions(
        state, targets, outcomes, ca._key(day)
    )


def test_a_pass_records_every_share_mutation_it_owns_exposed_or_not() -> None:
    held = _share_outcome(4000)
    elsewhere = _share_outcome(4010, security_id=ca.SEC_OTHER, occurrence="occ-2")
    state = ca._state(holdings=(ca._holding(quantity=100),))

    updated, _ = _pass(state, (held, elsewhere))

    assert updated.holdings[0].quantity == 200
    assert updated.applied_effect_ids == tuple(
        sorted((_effect_id(), _effect_id(ca.SEC_OTHER, "occ-2")))
    )


def test_a_pass_records_nothing_it_does_not_own() -> None:
    # Not yet effective, and a cash distribution: neither is recorded.
    later = _share_outcome(4020, security_id=ca.SEC_OTHER, effective_at=ca.LATER_AT)
    _, _, dividend = ca._dividend_case(suffix=4030)
    state = ca._state(holdings=(ca._holding(quantity=100),))

    updated, _ = _pass(state, (later, dividend))

    assert updated.holdings[0].quantity == 100
    assert updated.applied_effect_ids == ()
    assert len(updated.pending_cash_claims) == 1


def test_recording_an_unexposed_effect_keeps_the_mark_and_the_book() -> None:
    state = ca._state(holdings=(ca._holding(quantity=100),))
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)
    kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))
    marked = kernel.state

    updated, _ = _pass(marked, (_share_outcome(4040, security_id=ca.SEC_OTHER),))

    assert updated.applied_effect_ids == (_effect_id(ca.SEC_OTHER),)
    assert updated.model_dump(exclude={"applied_effect_ids"}) == marked.model_dump(
        exclude={"applied_effect_ids"}
    )


def test_a_replayed_pass_is_refused_rather_than_splitting_twice() -> None:
    outcome = _share_outcome(4050)
    state = ca._state(holdings=(ca._holding(quantity=100),))
    once, _ = _pass(state, (outcome,))
    assert once.holdings[0].quantity == 200

    # A checkpoint taken after the pre-open, then replayed (#20 Q3). Before
    # the fix this split the split position again, to 400 shares.
    with pytest.raises(
        EffectAlreadyAppliedError,
        match=(
            r"^the forward_split occ-1 of synthetic-a on .* was already applied "
            r"to this book"
        ),
    ):
        _pass(once, (outcome,))


def test_a_replay_exposed_only_by_a_staged_buy_is_refused() -> None:
    # Staged targets are not state, so no replay of them can be proven a no-op.
    outcome = _share_outcome(4060)
    book = ca._state()
    once, _ = _pass(book, (outcome,))
    assert once.applied_effect_ids == (_effect_id(),)
    buy = (SecurityTargetPositionV1(security_id=ca.SEC_A, target_quantity=5),)

    with pytest.raises(EffectAlreadyAppliedError):
        _pass(once, (outcome,), targets=buy)

    # Control: a zero target trades nothing, so the replay is not exposed.
    zero = (SecurityTargetPositionV1(security_id=ca.SEC_A, target_quantity=0),)
    again, targets = _pass(once, (outcome,), targets=zero)
    assert again == once
    assert targets == zero


def test_a_replay_on_an_unexposed_book_changes_nothing() -> None:
    outcome = _share_outcome(4070, security_id=ca.SEC_OTHER)
    state = ca._state(holdings=(ca._holding(quantity=100),))
    once, _ = _pass(state, (outcome,))

    again, _ = _pass(once, (outcome,))

    assert again == once


def test_a_reclassifying_revision_cannot_mutate_one_occurrence_twice() -> None:
    # The occurrence first reads as a split, then as a stock dividend a week
    # later. Action kind and dates are revisable, so identity ignores both.
    state = ca._state(holdings=(ca._holding(quantity=100),))
    split, _ = _pass(state, (_share_outcome(4080, occurrence="occ-9"),))
    advanced = PortfolioAccountingKernel(split, session_clock=ca.CLOCK)
    advanced.advance_session(ca._key(ca.LATER_DAY))
    revised = _share_outcome(
        4090,
        occurrence="occ-9",
        kind=ActionKind.STOCK_DIVIDEND,
        effective_at=ca.LATER_AT,
        numerator="1",
        denominator="10",
        meaning="additional_per_predecessor",
    )

    with pytest.raises(EffectAlreadyAppliedError, match="stock_dividend occ-9"):
        _pass(advanced.state, (revised,), day=ca.LATER_DAY)

    # Control: a distinct occurrence applies on top of the split.
    other = _share_outcome(
        4100,
        occurrence="occ-10",
        kind=ActionKind.STOCK_DIVIDEND,
        effective_at=ca.LATER_AT,
        numerator="1",
        denominator="10",
        meaning="additional_per_predecessor",
    )
    applied, _ = _pass(advanced.state, (other,), day=ca.LATER_DAY)
    assert applied.holdings[0].quantity == 220


def test_one_occurrence_reported_by_two_sources_is_two_effects() -> None:
    # Identity is source-scoped, as M1c occurrence identity is.
    state = ca._state(holdings=(ca._holding(quantity=100),))
    first, _ = _pass(state, (_share_outcome(4110, security_id=ca.SEC_OTHER),))
    second, _ = _pass(
        first,
        (_share_outcome(4120, security_id=ca.SEC_OTHER, source_id=ca.SOURCE_B),),
    )
    assert second.applied_effect_ids == tuple(
        sorted(
            (
                _effect_id(ca.SEC_OTHER),
                _effect_id(ca.SEC_OTHER, source_id=ca.SOURCE_B),
            )
        )
    )


def test_a_replayed_dividend_stays_idempotent_by_claim_identity() -> None:
    _, _, dividend = ca._dividend_case(suffix=4130)
    state = ca._state(holdings=(ca._holding(quantity=100),))
    once, _ = _pass(state, (dividend,))

    again, _ = _pass(once, (dividend,))

    assert again == once
    assert len(again.pending_cash_claims) == 1
