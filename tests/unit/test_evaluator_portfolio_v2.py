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

import pytest
from observation_test_support import uid
from pydantic import BaseModel, create_model

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_execution import RebalanceOutcomeV1, positions_digest
from drift.domain.evaluator_portfolio import (
    MarkEvidenceV1,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioMarkV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    pending_cash_claim_id,
)
from drift.domain.evaluator_strategy import PositionViewV1
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

SEC_A = uid(21)
SEC_B = uid(22)
DAY = date(2026, 1, 2)
ADMISSION_HASH = "a" * 64
EVIDENCE_HASH = "b" * 64


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
    holdings = (
        SecurityHoldingV1(security_id=SEC_A, quantity=8, cost_basis=Decimal("1")),
        SecurityHoldingV1(security_id=SEC_B, quantity=3, cost_basis=Decimal("0")),
    )
    assert positions_digest(holdings) == (
        "8a2d1319a0a7eaca6b22ccecaee4216abe042942eacdaa21f39abe4a435fc149"
    )
