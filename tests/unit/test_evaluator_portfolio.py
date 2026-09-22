"""Unit tests for M2 Task 3 portfolio state and cash accounting kernel."""

from datetime import UTC, date, datetime, time
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from observation_test_support import uid
from pydantic import ValidationError

from drift.domain.economic_common import ActionKind
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
    promotion_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    EvaluationLane,
    IndeterminateValuationError,
    LaneAdmissibilityError,
    MarkEvidenceGrade,
    MarkEvidenceV1,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioMarkV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    canonical_money,
    pending_cash_claim_id,
)
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.serialization.canonical import content_hash

SEC_A = uid(21)
SEC_B = uid(22)

FRI = date(2026, 1, 2)
SAT = date(2026, 1, 3)
MON = date(2026, 1, 5)
TUE = date(2026, 1, 6)
FAR = date(2027, 6, 30)

XNYS = "XNYS"
XTKS = "XTKS"

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
ZERO_HASH = "0" * 64

ACCOUNTING_EVIDENCE = "a" * 64
RECONSTRUCTION_EVIDENCE = "b" * 64

SOURCE_A = "source-a"
SOURCE_B = "source-b"

# Only the kernel's settled-claim guard renders the bare claim id right after
# the phrase. The state-level replay guard says "cannot be pending again"
# instead, so this pattern cannot be satisfied by that message, by any other
# guard, or by incidental text such as a temporary directory name.
KERNEL_SETTLED_GUARD = r"claim already settled [0-9a-f]{64}$"


# --- session clock scaffolding ---


def _key(day: date, mic: str = XNYS) -> SessionKeyV1:
    return SessionKeyV1(mic=mic, session_scope="regular", local_date=day)


def _evaluation_session(
    key: SessionKeyV1, *, open_hour: int = 14, close_hour: int = 21
) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=key,
        opened_at=datetime.combine(key.local_date, time(open_hour), tzinfo=UTC),
        closed_at=datetime.combine(key.local_date, time(close_hour), tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _clock(*sessions: EvaluationSessionV1) -> SessionClockV1:
    ordered = tuple(sorted(sessions, key=session_order_key))
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=ordered,
        acknowledged_limitations=(),
        clock_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"clock_hash": session_clock_hash(draft)})


# Saturday is deliberately absent: it is not a trading session.
CLOCK = _clock(
    _evaluation_session(_key(FRI)),
    _evaluation_session(_key(MON)),
    _evaluation_session(_key(TUE)),
)

# A legal multi-venue clock holding two sessions on one local date.
MULTI_VENUE_CLOCK = _clock(
    _evaluation_session(_key(FRI)),
    _evaluation_session(_key(MON)),
    _evaluation_session(_key(TUE, XTKS), open_hour=0, close_hour=6),
    _evaluation_session(_key(TUE)),
)


# --- lane admission scaffolding ---


def _exploratory_admission() -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=H3,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )


def _promotion_admission() -> PromotionEvaluationAdmissionV1:
    draft = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash=H1,
        m1e_profile_set_hash=H2,
        decision_handoff_hash=H3,
        audit_handoff_hash=H4,
        input_bundle_hash=H5,
        provenance_proof_hash=H6,
        admission_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"admission_hash": promotion_evaluation_admission_hash(draft)}
    )


EXPLORATORY = _exploratory_admission()
PROMOTION = _promotion_admission()


def _state(
    cash: str = "10000.00",
    day: date = FRI,
    admission: EvaluationAdmissionV1 = EXPLORATORY,
) -> PortfolioStateV1:
    return initial_portfolio_state(
        session_key=_key(day), initial_cash=Decimal(cash), admission=admission
    )


def _kernel(
    cash: str = "10000.00",
    day: date = FRI,
    admission: EvaluationAdmissionV1 = EXPLORATORY,
    clock: SessionClockV1 = CLOCK,
) -> PortfolioAccountingKernel:
    return PortfolioAccountingKernel(_state(cash, day, admission), session_clock=clock)


# --- mark scaffolding ---


def _mark(
    price: str,
    *,
    security_id: UUID = SEC_A,
    grade: MarkEvidenceGrade = "exploratory",
) -> MarkPriceV1:
    if grade == "indeterminate":
        evidence = MarkEvidenceV1(grade=grade, reason="price lifted without provenance")
    elif grade == "promotion_grade":
        evidence = MarkEvidenceV1(grade=grade, evidence_hash=ACCOUNTING_EVIDENCE)
    else:
        evidence = MarkEvidenceV1(grade=grade, evidence_hash=RECONSTRUCTION_EVIDENCE)
    return MarkPriceV1(
        security_id=security_id, close_price=Decimal(price), evidence=evidence
    )


def _portfolio_mark(
    prices: tuple[MarkPriceV1, ...],
    *,
    day: date = FRI,
    mic: str = XNYS,
    lane: EvaluationLane = "exploratory",
) -> PortfolioMarkV1:
    return PortfolioMarkV1(session_key=_key(day, mic), lane=lane, prices=prices)


def _claim(
    *,
    source_id: str = SOURCE_A,
    security_id: UUID = SEC_A,
    component_id: str = "cash-1",
    occurrence_id: str = "occ-1",
    quantity: int = 100,
    per_share: str = "0.50",
    entitlement: date = FRI,
    payable: date = MON,
    kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
) -> PendingCashClaimV1:
    per = Decimal(per_share)
    return PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            source_id=source_id,
            security_id=security_id,
            action_kind=kind,
            occurrence_id=occurrence_id,
            component_id=component_id,
        ),
        source_id=source_id,
        security_id=security_id,
        action_kind=kind,
        occurrence_id=occurrence_id,
        component_id=component_id,
        entitled_quantity=quantity,
        cash_per_share=per,
        total_cash_expected=per * quantity,
        entitlement_session=entitlement,
        payable_session=payable,
    )


# --- holdings ---


def test_holding_rejects_non_positive_quantity() -> None:
    for bad in (0, -1):
        with pytest.raises((ValidationError, ValueError)):
            SecurityHoldingV1(
                security_id=SEC_A, quantity=bad, cost_basis=Decimal("10.00")
            )


def test_holding_rejects_negative_cost_basis() -> None:
    with pytest.raises((ValidationError, ValueError)):
        SecurityHoldingV1(security_id=SEC_A, quantity=1, cost_basis=Decimal("-0.01"))


def test_average_cost_per_share_is_exact() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=8, cost_basis=Decimal("100.00")
    )
    assert holding.average_cost_per_share == Decimal("12.5")


# --- claim identity ---


def test_claim_id_is_deterministic() -> None:
    assert _claim().claim_id == _claim().claim_id


def test_claim_id_distinguishes_components_on_same_date() -> None:
    first = _claim(component_id="cash-1")
    second = _claim(component_id="cash-2")
    assert first.claim_id != second.claim_id


def test_claim_id_depends_on_every_identity_input() -> None:
    base = _claim()
    variants = (
        _claim(source_id=SOURCE_B),
        _claim(security_id=SEC_B),
        _claim(kind=ActionKind.SPECIAL_CASH_DISTRIBUTION),
        _claim(occurrence_id="occ-2"),
        _claim(component_id="cash-9"),
    )
    for variant in variants:
        assert variant.claim_id != base.claim_id


def test_claim_identity_is_source_scoped() -> None:
    # M1c occurrence identity is scoped by EconomicDeliveryGroupV1.source_id
    # plus native_occurrence_id, so two sources reusing one native occurrence
    # id are two occurrences and must not collide onto a single claim.
    first = _claim(source_id=SOURCE_A, occurrence_id="shared-occurrence")
    second = _claim(source_id=SOURCE_B, occurrence_id="shared-occurrence")
    assert first.claim_id != second.claim_id


def test_claim_identity_ignores_revisable_dates() -> None:
    # Payable dates are revisable source claims, so they are attributes of the
    # claim rather than part of its identity.
    base = _claim(entitlement=FRI, payable=MON)
    revised_payable = _claim(entitlement=FRI, payable=TUE)
    revised_entitlement = _claim(entitlement=MON, payable=TUE)
    assert revised_payable.claim_id == base.claim_id
    assert revised_entitlement.claim_id == base.claim_id


def test_claim_rejects_inconsistent_total() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PendingCashClaimV1(
            claim_id=pending_cash_claim_id(
                source_id=SOURCE_A,
                security_id=SEC_A,
                action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
                occurrence_id="occ-1",
                component_id="cash-1",
            ),
            source_id=SOURCE_A,
            security_id=SEC_A,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-1",
            component_id="cash-1",
            entitled_quantity=100,
            cash_per_share=Decimal("0.50"),
            total_cash_expected=Decimal("49.00"),
            entitlement_session=FRI,
            payable_session=MON,
        )


def test_claim_rejects_tampered_claim_id() -> None:
    with pytest.raises((ValidationError, ValueError), match="claim id mismatch"):
        PendingCashClaimV1(
            claim_id=ZERO_HASH,
            source_id=SOURCE_A,
            security_id=SEC_A,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-1",
            component_id="cash-1",
            entitled_quantity=100,
            cash_per_share=Decimal("0.50"),
            total_cash_expected=Decimal("50.00"),
            entitlement_session=FRI,
            payable_session=MON,
        )


def test_claim_rejects_payable_before_entitlement() -> None:
    with pytest.raises((ValidationError, ValueError)):
        _claim(entitlement=MON, payable=FRI)


# --- state invariants ---


def test_initial_state_nav_equals_cash() -> None:
    state = _state("10000.00")
    assert state.cash_balance == Decimal("10000.00")
    assert state.net_asset_value == Decimal("10000.00")
    assert state.holdings == ()


def test_initial_state_binds_lane_and_admission() -> None:
    exploratory = _state(admission=EXPLORATORY)
    promotion = _state(admission=PROMOTION)
    assert exploratory.lane == "exploratory"
    assert exploratory.admission_hash == EXPLORATORY.admission_hash
    assert promotion.lane == "promotion"
    assert promotion.admission_hash == PROMOTION.admission_hash


def test_state_rejects_negative_cash() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("-0.01"),
            holdings=(),
            pending_cash_claims=(),
            mark=None,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("-0.01"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_nav_that_does_not_reconcile() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("100.00"),
            holdings=(),
            pending_cash_claims=(),
            mark=None,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("999.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_duplicate_holdings_for_one_security() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=1, cost_basis=Decimal("10.00")
    )
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(holding, holding),
            pending_cash_claims=(),
            mark=None,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("0.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_is_marked_as_a_settable_field() -> None:
    # is_marked is derived from the bound mark. Accepting it as input again
    # would reopen the uncoupled-mark defect.
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("100.00"),
            holdings=(),
            pending_cash_claims=(),
            mark=None,
            is_marked=True,  # type: ignore[call-arg]
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("100.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_two_claims_sharing_one_identity() -> None:
    first = _claim(entitlement=FRI, payable=MON)
    second = _claim(entitlement=FRI, payable=TUE)
    assert first.claim_id == second.claim_id
    with pytest.raises(
        (ValidationError, ValueError), match="pending claims must be unique by claim id"
    ):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(),
            pending_cash_claims=(first, second),
            mark=None,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=Decimal("100.00"),
            net_asset_value=Decimal("100.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- fills ---


def _buy(qty: int, price: str, costs: str = "0.00") -> PortfolioFillV1:
    return PortfolioFillV1(
        security_id=SEC_A,
        side="buy",
        quantity=qty,
        fill_price=Decimal(price),
        transaction_costs=Decimal(costs),
    )


def _sell(qty: int, price: str, costs: str = "0.00") -> PortfolioFillV1:
    return PortfolioFillV1(
        security_id=SEC_A,
        side="sell",
        quantity=qty,
        fill_price=Decimal(price),
        transaction_costs=Decimal(costs),
    )


def _buy_b(qty: int, price: str) -> PortfolioFillV1:
    return PortfolioFillV1(
        security_id=SEC_B,
        side="buy",
        quantity=qty,
        fill_price=Decimal(price),
        transaction_costs=Decimal("0.00"),
    )


def test_buy_moves_cash_into_cost_basis_including_fees() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00", "1.50"))
    state = kernel.state
    assert state.cash_balance == Decimal("9798.50")
    assert state.holdings[0].quantity == 10
    assert state.holdings[0].cost_basis == Decimal("201.50")
    assert state.cumulative_transaction_costs == Decimal("1.50")


def test_buy_rejects_insufficient_cash() -> None:
    kernel = _kernel("100.00")
    with pytest.raises(ValueError, match="insufficient cash"):
        kernel.apply_fill(_buy(10, "20.00"))


def test_sell_relieves_cost_basis_proportionally() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(4, "25.00"))
    holding = kernel.state.holdings[0]
    assert holding.quantity == 6
    assert holding.cost_basis == Decimal("120.00")
    assert kernel.state.realized_gross_pnl == Decimal("20.00")


def test_sell_net_pnl_subtracts_costs() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(4, "25.00", "2.00"))
    assert kernel.state.realized_gross_pnl == Decimal("20.00")
    assert kernel.state.realized_net_pnl == Decimal("18.00")


def test_full_exit_removes_holding() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(10, "21.00"))
    assert kernel.state.holdings == ()
    assert kernel.state.realized_gross_pnl == Decimal("10.00")


def test_sell_rejects_more_than_held() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(5, "20.00"))
    with pytest.raises(ValueError, match="exceeds held quantity"):
        kernel.apply_fill(_sell(6, "20.00"))


def test_fill_rejects_non_positive_quantity() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioFillV1(
            security_id=SEC_A,
            side="buy",
            quantity=0,
            fill_price=Decimal("1.00"),
            transaction_costs=Decimal("0.00"),
        )


# --- claims and settlement ---


def test_recorded_claim_lifts_nav_without_touching_cash() -> None:
    kernel = _kernel("1000.00")
    kernel.record_claim(_claim(quantity=100, per_share="0.50"))
    state = kernel.state
    assert state.cash_balance == Decimal("1000.00")
    assert state.pending_claims_value == Decimal("50.00")
    assert state.net_asset_value == Decimal("1050.00")


def test_duplicate_claim_is_rejected() -> None:
    kernel = _kernel()
    kernel.record_claim(_claim())
    with pytest.raises(ValueError, match="duplicate pending claim"):
        kernel.record_claim(_claim())


def test_settlement_converts_claim_into_cash() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    state = kernel.state
    assert state.cash_balance == Decimal("1050.00")
    assert state.pending_cash_claims == ()
    assert state.net_asset_value == Decimal("1050.00")


def test_settlement_ignores_claims_without_delivered_evidence() -> None:
    kernel = _kernel("1000.00")
    claim = _claim()
    kernel.record_claim(claim)
    kernel.settle_claims(())
    assert kernel.state.cash_balance == Decimal("1000.00")
    assert kernel.state.pending_cash_claims == (claim,)


def test_settlement_rejects_unknown_claim_id() -> None:
    kernel = _kernel()
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims(("f" * 64,))


def test_weekend_payable_claim_settles_on_next_trading_session() -> None:
    kernel = _kernel("1000.00", day=FRI)
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=SAT)
    kernel.record_claim(claim)

    # Saturday is not a trading session, so nothing settles while the book is
    # still on Friday.
    assert kernel.state.cash_balance == Decimal("1000.00")

    kernel.advance_session(_key(MON))
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.session_key.local_date == MON
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_claim_cannot_settle_before_its_payable_session() -> None:
    kernel = _kernel("1000.00", day=FRI)
    claim = _claim(entitlement=FRI, payable=TUE)
    kernel.record_claim(claim)
    with pytest.raises(ValueError, match="not yet payable"):
        kernel.settle_claims((claim.claim_id,))


# --- F1: claim supersession over revisable dates ---


def test_payable_date_revision_cannot_pay_one_dividend_twice() -> None:
    # The reviewer's exact attack: one 0.50 x 100 dividend, settled, then
    # re-delivered under a revised payable date.
    kernel = _kernel("100000.00", day=FRI)
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=MON)
    kernel.record_claim(claim)
    kernel.advance_session(_key(MON))
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.cash_balance == Decimal("100050.00")

    revised = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=TUE)
    assert revised.claim_id == claim.claim_id
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.record_claim(revised)
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.supersede_claim(revised)
    kernel.advance_session(_key(TUE))
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.record_claim(revised)
    assert kernel.state.cash_balance == Decimal("100050.00")


def test_payable_date_revision_supersedes_the_same_claim() -> None:
    kernel = _kernel("1000.00", day=FRI)
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=MON)
    kernel.record_claim(claim)
    revised = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=TUE)
    kernel.supersede_claim(revised)
    state = kernel.state
    assert len(state.pending_cash_claims) == 1
    assert state.pending_cash_claims[0].payable_session == TUE
    assert state.pending_claims_value == Decimal("50.00")
    assert state.net_asset_value == Decimal("1050.00")


def test_superseded_claim_settles_exactly_once() -> None:
    kernel = _kernel("1000.00", day=FRI)
    kernel.record_claim(_claim(quantity=100, per_share="0.50", payable=MON))
    revised = _claim(quantity=100, per_share="0.50", payable=TUE)
    kernel.supersede_claim(revised)
    kernel.advance_session(_key(MON))
    with pytest.raises(ValueError, match="not yet payable"):
        kernel.settle_claims((revised.claim_id,))
    kernel.advance_session(_key(TUE))
    kernel.settle_claims((revised.claim_id,))
    assert kernel.state.cash_balance == Decimal("1050.00")
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.record_claim(revised)
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_supersede_refuses_a_claim_that_was_never_recorded() -> None:
    kernel = _kernel("1000.00")
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.supersede_claim(_claim())
    assert kernel.state.pending_cash_claims == ()


def test_supersede_refuses_a_settled_claim() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.supersede_claim(_claim(entitlement=FRI, payable=TUE))
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_supersede_survives_rehydration_from_persisted_state() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    rebuilt = PortfolioAccountingKernel(kernel.state, session_clock=CLOCK)
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        rebuilt.supersede_claim(_claim(entitlement=FRI, payable=TUE))


# --- F7: session advancement follows the session clock ---


def test_advance_session_rejects_going_backwards() -> None:
    kernel = _kernel("1000.00", day=MON)
    with pytest.raises(ValueError, match="session must advance beyond"):
        kernel.advance_session(_key(FRI))


def test_advance_session_rejects_standing_still() -> None:
    kernel = _kernel("1000.00", day=MON)
    with pytest.raises(ValueError, match="session must advance beyond"):
        kernel.advance_session(_key(MON))


def test_advance_refuses_a_session_the_clock_does_not_authorize() -> None:
    kernel = _kernel("1000.00", day=FRI)
    with pytest.raises(
        ValueError, match="session clock does not authorize session XNYS"
    ):
        kernel.advance_session(_key(SAT))


def test_advance_refuses_a_foreign_venue_absent_from_the_clock() -> None:
    kernel = _kernel("1000.00", day=FRI)
    with pytest.raises(
        ValueError, match="session clock does not authorize session XTKS"
    ):
        kernel.advance_session(_key(TUE, XTKS))


def test_claim_cannot_settle_on_a_foreign_venue_session() -> None:
    # The reviewer settled a claim payable 2026-01-06 on an XTKS session inside
    # an XNYS book. The book must refuse the venue the clock never authorized,
    # so the claim stays unpayable.
    kernel = _kernel("1000.00", day=FRI)
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=TUE)
    kernel.record_claim(claim)
    with pytest.raises(
        ValueError, match="session clock does not authorize session XTKS"
    ):
        kernel.advance_session(_key(TUE, XTKS))
    with pytest.raises(ValueError, match="not yet payable"):
        kernel.settle_claims((claim.claim_id,))
    assert kernel.state.cash_balance == Decimal("1000.00")
    assert kernel.state.session_key == _key(FRI)


def test_advance_accepts_a_second_venue_the_clock_authorizes() -> None:
    # A legal multi-venue clock holds two sessions on one local date. Bare
    # local-date comparison wrongly refused the second one.
    kernel = _kernel("1000.00", day=MON, clock=MULTI_VENUE_CLOCK)
    kernel.advance_session(_key(TUE, XTKS))
    assert kernel.state.session_key == _key(TUE, XTKS)
    kernel.advance_session(_key(TUE))
    assert kernel.state.session_key == _key(TUE)


def test_advance_refuses_going_backwards_within_one_local_date() -> None:
    kernel = _kernel("1000.00", day=MON, clock=MULTI_VENUE_CLOCK)
    kernel.advance_session(_key(TUE))
    with pytest.raises(ValueError, match="session must advance beyond"):
        kernel.advance_session(_key(TUE, XTKS))


def test_kernel_refuses_a_book_session_absent_from_the_clock() -> None:
    state = _state("1000.00", day=SAT)
    with pytest.raises(
        ValueError, match="session clock does not authorize book session XNYS"
    ):
        PortfolioAccountingKernel(state, session_clock=CLOCK)


# --- marking ---


def test_mark_close_uses_exact_unadjusted_prices() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("21.37"),))
    state = kernel.state
    assert state.holdings_market_value == Decimal("213.70")
    assert state.net_asset_value == Decimal("9800.00") + Decimal("213.70")


def test_mark_close_without_price_for_held_position_is_indeterminate() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(IndeterminateValuationError, match="no authorized close price"):
        kernel.mark_close(())


def test_mark_close_rejects_non_positive_price() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="close price must be strictly positive"
    ):
        _mark("0.00")


def test_mark_close_rejects_price_for_an_unheld_security() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(ValueError, match="close price for unheld security"):
        kernel.mark_close((_mark("21.00"), _mark("55.00", security_id=SEC_B)))
    assert kernel.state.is_marked is False


def test_mark_close_rejects_a_repeated_price_for_one_security() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(ValueError, match="repeated close price for security"):
        kernel.mark_close((_mark("21.00"), _mark("22.00")))
    assert kernel.state.is_marked is False


def test_mark_close_with_no_holdings_is_valid() -> None:
    kernel = _kernel("500.00")
    kernel.mark_close(())
    assert kernel.state.holdings_market_value == Decimal("0.00")
    assert kernel.state.net_asset_value == Decimal("500.00")
    assert kernel.state.is_marked is True


def test_nav_reconciles_across_a_full_cycle() -> None:
    kernel = _kernel("1000.00")
    kernel.apply_fill(_buy(10, "20.00", "1.00"))
    claim = _claim(quantity=10, per_share="0.25", entitlement=FRI, payable=MON)
    kernel.record_claim(claim)
    kernel.advance_session(_key(MON))
    kernel.settle_claims((claim.claim_id,))
    kernel.mark_close((_mark("22.00"),))
    state = kernel.state
    assert (
        state.net_asset_value
        == state.cash_balance + state.holdings_market_value + state.pending_claims_value
    )
    assert state.cumulative_transaction_costs == Decimal("1.00")


# --- F3: lane-aware, provenance-bound marks ---


def test_exploratory_lane_accepts_exploratory_evidence() -> None:
    kernel = _kernel("10000.00", admission=EXPLORATORY)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00", grade="exploratory"),))
    assert kernel.state.holdings_market_value == Decimal("250.00")
    assert kernel.state.mark is not None
    assert kernel.state.mark.lane == "exploratory"
    assert kernel.state.mark.prices[0].evidence.grade == "exploratory"


def test_exploratory_lane_accepts_promotion_grade_evidence() -> None:
    kernel = _kernel("10000.00", admission=EXPLORATORY)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00", grade="promotion_grade"),))
    assert kernel.state.holdings_market_value == Decimal("250.00")


def test_promotion_lane_accepts_promotion_grade_evidence() -> None:
    kernel = _kernel("10000.00", admission=PROMOTION)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00", grade="promotion_grade"),))
    assert kernel.state.lane == "promotion"
    assert kernel.state.holdings_market_value == Decimal("250.00")


def test_promotion_lane_refuses_an_exploratory_derived_mark() -> None:
    kernel = _kernel("10000.00", admission=PROMOTION)
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(
        LaneAdmissibilityError, match="promotion lane refuses exploratory mark evidence"
    ):
        kernel.mark_close((_mark("25.00", grade="exploratory"),))
    assert kernel.state.is_marked is False
    assert kernel.state.holdings_market_value == Decimal("0")
    assert kernel.state.net_asset_value == Decimal("9800.00")


def test_promotion_lane_refuses_a_mixed_mark_set() -> None:
    kernel = _kernel("10000.00", admission=PROMOTION)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_buy_b(4, "50.00"))
    with pytest.raises(
        LaneAdmissibilityError, match="promotion lane refuses exploratory mark evidence"
    ):
        kernel.mark_close(
            (
                _mark("21.00", grade="promotion_grade"),
                _mark("55.00", security_id=SEC_B, grade="exploratory"),
            )
        )
    assert kernel.state.is_marked is False


def test_indeterminate_provenance_is_refused_in_the_promotion_lane() -> None:
    kernel = _kernel("10000.00", admission=PROMOTION)
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(
        IndeterminateValuationError, match="has indeterminate provenance"
    ):
        kernel.mark_close((_mark("25.00", grade="indeterminate"),))
    assert kernel.state.is_marked is False


def test_indeterminate_provenance_is_refused_in_the_exploratory_lane() -> None:
    # Fail closed: unbound provenance is never defaulted to acceptable, even in
    # the lane that admits weaker evidence.
    kernel = _kernel("10000.00", admission=EXPLORATORY)
    kernel.apply_fill(_buy(10, "20.00"))
    with pytest.raises(
        IndeterminateValuationError, match="has indeterminate provenance"
    ):
        kernel.mark_close((_mark("25.00", grade="indeterminate"),))
    assert kernel.state.is_marked is False
    assert kernel.state.net_asset_value == Decimal("9800.00")


def test_bound_mark_evidence_requires_an_evidence_hash() -> None:
    for grade in ("promotion_grade", "exploratory"):
        with pytest.raises(
            (ValidationError, ValueError), match="requires a bound evidence hash"
        ):
            MarkEvidenceV1(grade=grade)


def test_indeterminate_mark_evidence_cannot_name_an_evidence_hash() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="cannot name an evidence hash"
    ):
        MarkEvidenceV1(
            grade="indeterminate", evidence_hash=ACCOUNTING_EVIDENCE, reason="nope"
        )


def test_indeterminate_mark_evidence_requires_a_reason() -> None:
    with pytest.raises(
        (ValidationError, ValueError),
        match="indeterminate mark evidence requires a reason",
    ):
        MarkEvidenceV1(grade="indeterminate")


def test_bound_mark_evidence_cannot_carry_an_indeterminacy_reason() -> None:
    with pytest.raises(
        (ValidationError, ValueError),
        match="cannot carry an indeterminacy reason",
    ):
        MarkEvidenceV1(
            grade="exploratory", evidence_hash=ACCOUNTING_EVIDENCE, reason="hedge"
        )


def test_portfolio_mark_refuses_evidence_its_lane_does_not_admit() -> None:
    with pytest.raises(
        (ValidationError, ValueError),
        match="promotion lane refuses exploratory mark evidence",
    ):
        _portfolio_mark((_mark("21.00", grade="exploratory"),), lane="promotion")


def test_portfolio_mark_refuses_indeterminate_evidence_in_every_lane() -> None:
    # Fail closed at the model layer too: no lane admits a price that cannot
    # name the evidence it came from.
    for lane in ("exploratory", "promotion"):
        with pytest.raises(
            (ValidationError, ValueError),
            match=f"{lane} lane refuses indeterminate mark evidence",
        ):
            _portfolio_mark((_mark("21.00", grade="indeterminate"),), lane=lane)


def test_portfolio_mark_refuses_a_repeated_security() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="at most one price per security"
    ):
        _portfolio_mark((_mark("21.00"), _mark("22.00")))


def _marked_state(
    *,
    lane: EvaluationLane = "exploratory",
    admission_hash: str = EXPLORATORY.admission_hash,
    state_day: date = FRI,
    mark_day: date = FRI,
    mark_lane: EvaluationLane = "exploratory",
    grade: MarkEvidenceGrade = "exploratory",
    market_value: str = "210.00",
    prices: tuple[MarkPriceV1, ...] | None = None,
) -> PortfolioStateV1:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=10, cost_basis=Decimal("200.00")
    )
    if prices is None:
        prices = (_mark("21.00", grade=grade),)
    return PortfolioStateV1(
        lane=lane,
        admission_hash=admission_hash,
        session_key=_key(state_day),
        cash_balance=Decimal("0.00"),
        holdings=(holding,),
        pending_cash_claims=(),
        mark=_portfolio_mark(prices, day=mark_day, lane=mark_lane),
        holdings_market_value=Decimal(market_value),
        pending_claims_value=Decimal("0.00"),
        net_asset_value=Decimal(market_value),
        realized_gross_pnl=Decimal("0.00"),
        realized_net_pnl=Decimal("0.00"),
        cumulative_transaction_costs=Decimal("0.00"),
    )


def test_marked_state_is_valid_when_every_binding_agrees() -> None:
    state = _marked_state()
    assert state.is_marked is True
    assert state.holdings_market_value == Decimal("210.00")


def test_state_refuses_a_promotion_lane_mark_built_on_exploratory_evidence() -> None:
    with pytest.raises(
        (ValidationError, ValueError),
        match="promotion lane refuses exploratory mark evidence",
    ):
        _marked_state(
            lane="promotion",
            admission_hash=PROMOTION.admission_hash,
            mark_lane="promotion",
            grade="exploratory",
        )


def test_state_refuses_a_mark_admitted_under_another_lane() -> None:
    with pytest.raises(
        (ValidationError, ValueError),
        match="mark was admitted under the exploratory lane",
    ):
        _marked_state(
            lane="promotion",
            admission_hash=PROMOTION.admission_hash,
            mark_lane="exploratory",
            grade="promotion_grade",
        )


def test_state_refuses_a_mark_taken_in_another_session() -> None:
    with pytest.raises((ValidationError, ValueError), match="mark belongs to session"):
        _marked_state(state_day=MON, mark_day=FRI)


def test_state_refuses_a_mark_that_does_not_price_every_holding() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="mark must price exactly the held"
    ):
        _marked_state(
            prices=(_mark("21.00", security_id=SEC_B),), market_value="210.00"
        )


def test_state_refuses_a_market_value_the_mark_does_not_support() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="holdings market value must equal"
    ):
        _marked_state(market_value="999.00")


# --- F6: the mark cannot survive rehydration into another session ---


def test_mark_cannot_survive_rehydration_into_another_session() -> None:
    kernel = _kernel("10000.00", day=FRI)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00"),))
    marked = kernel.state
    assert marked.is_marked is True
    with pytest.raises((ValidationError, ValueError), match="mark belongs to session"):
        marked.model_copy(update={"session_key": _key(FAR)})


def test_mark_cannot_be_reused_under_a_later_persisted_session() -> None:
    kernel = _kernel("10000.00", day=FRI)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00"),))
    persisted = kernel.state.model_dump(mode="python")
    persisted["session_key"] = _key(MON).model_dump(mode="python")
    with pytest.raises((ValidationError, ValueError), match="mark belongs to session"):
        PortfolioStateV1.model_validate(persisted)


# --- mark invalidation (value-creation guard) ---


def test_sell_after_mark_cannot_create_net_asset_value() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("20.00"),))
    assert kernel.state.net_asset_value == Decimal("10000.00")
    kernel.apply_fill(_sell(10, "20.00"))
    state = kernel.state
    assert state.holdings == ()
    assert state.holdings_market_value == Decimal("0")
    assert state.is_marked is False
    assert state.net_asset_value == Decimal("10000.00")


def test_buy_after_mark_invalidates_the_mark() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00"),))
    assert kernel.state.is_marked is True
    kernel.apply_fill(_buy(5, "20.00"))
    assert kernel.state.is_marked is False
    assert kernel.state.holdings_market_value == Decimal("0")


def test_advance_session_clears_the_mark() -> None:
    kernel = _kernel("10000.00", day=FRI)
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("25.00"),))
    kernel.advance_session(_key(MON))
    assert kernel.state.is_marked is False
    assert kernel.state.mark is None
    assert kernel.state.holdings_market_value == Decimal("0")
    assert kernel.state.holdings[0].quantity == 10


def test_state_rejects_market_value_without_holdings() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("100.00"),
            holdings=(),
            pending_cash_claims=(),
            mark=_portfolio_mark(()),
            holdings_market_value=Decimal("50.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("150.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


def test_state_rejects_unmarked_state_carrying_a_mark() -> None:
    holding = SecurityHoldingV1(
        security_id=SEC_A, quantity=1, cost_basis=Decimal("10.00")
    )
    with pytest.raises(
        (ValidationError, ValueError),
        match="unmarked state cannot carry a holdings market value",
    ):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(holding,),
            pending_cash_claims=(),
            mark=None,
            holdings_market_value=Decimal("11.00"),
            pending_claims_value=Decimal("0.00"),
            net_asset_value=Decimal("11.00"),
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- atomicity ---


def test_rejected_sell_rolls_back_completely() -> None:
    kernel = _kernel("100.00")
    kernel.apply_fill(_buy(1, "100.00"))
    before = kernel.state
    with pytest.raises(ValueError, match="insufficient cash for sell costs"):
        kernel.apply_fill(_sell(1, "100.00", "500.00"))
    assert kernel.state == before
    # The rejected fill must not surface through a later successful operation.
    claim = _claim(quantity=1, per_share="1.00", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.holdings[0].quantity == 1
    assert kernel.state.cumulative_transaction_costs == Decimal("0.00")
    assert kernel.state.realized_net_pnl == Decimal("0")


def test_transaction_rolls_back_a_partially_applied_mutation() -> None:
    # No public operation can currently fail during rebuild, so the atomicity
    # guard is exercised through the kernel's own transaction contract.
    # Without it a partially applied mutation would stay in the kernel's
    # internal fields and be silently committed by the next success.
    kernel = _kernel("1000.00")
    before = kernel.state
    with (
        pytest.raises(RuntimeError, match="rebuild refused this mutation"),
        kernel._transaction(),
    ):
        kernel._cash = Decimal("999999.00")
        kernel._settled.add("f" * 64)
        kernel._mark = _portfolio_mark(())
        raise RuntimeError("rebuild refused this mutation")
    assert kernel._cash == Decimal("1000.00")
    assert kernel._settled == set()
    assert kernel._mark is None
    assert kernel.state == before
    claim = _claim(entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.cash_balance == Decimal("1050.00")
    assert kernel.state.settled_claim_ids == (claim.claim_id,)


def test_refused_mark_rolls_back_completely() -> None:
    kernel = _kernel("10000.00", admission=PROMOTION)
    kernel.apply_fill(_buy(10, "20.00"))
    before = kernel.state
    with pytest.raises(LaneAdmissibilityError):
        kernel.mark_close((_mark("25.00", grade="exploratory"),))
    assert kernel.state == before
    kernel.mark_close((_mark("25.00", grade="promotion_grade"),))
    assert kernel.state.holdings_market_value == Decimal("250.00")


def test_sell_side_costs_accumulate() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00", "1.00"))
    kernel.apply_fill(_sell(5, "20.00", "2.00"))
    assert kernel.state.cumulative_transaction_costs == Decimal("3.00")


# --- settlement container robustness ---


def test_settlement_enforces_unknown_guard_for_mapping_evidence() -> None:
    kernel = _kernel("1000.00")
    kernel.record_claim(_claim(entitlement=FRI, payable=FRI))
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims({"f" * 64: "delivered"})


def test_settlement_enforces_unknown_guard_for_keys_view() -> None:
    kernel = _kernel("1000.00")
    kernel.record_claim(_claim(entitlement=FRI, payable=FRI))
    with pytest.raises(ValueError, match="unknown claim"):
        kernel.settle_claims({"f" * 64: 1}.keys())


def test_settlement_settles_only_the_named_claim() -> None:
    kernel = _kernel("1000.00")
    first = _claim(
        component_id="cash-1", per_share="0.50", entitlement=FRI, payable=FRI
    )
    second = _claim(
        component_id="cash-2", per_share="0.25", entitlement=FRI, payable=FRI
    )
    kernel.record_claim(first)
    kernel.record_claim(second)
    kernel.settle_claims((first.claim_id,))
    state = kernel.state
    assert state.cash_balance == Decimal("1050.00")
    assert state.pending_cash_claims == (second,)
    assert state.pending_claims_value == Decimal("25.00")


# --- multi-security ---


def test_mark_close_values_every_holding() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_buy_b(4, "50.00"))
    kernel.mark_close((_mark("21.00"), _mark("55.00", security_id=SEC_B)))
    assert kernel.state.holdings_market_value == Decimal("430.00")


def test_mark_close_is_indeterminate_when_one_of_many_prices_is_absent() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_buy_b(4, "50.00"))
    with pytest.raises(IndeterminateValuationError, match="no authorized close price"):
        kernel.mark_close((_mark("21.00"),))


def test_cost_basis_is_isolated_per_security() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_buy_b(4, "50.00"))
    by_id = {h.security_id: h for h in kernel.state.holdings}
    assert by_id[SEC_A].cost_basis == Decimal("200.00")
    assert by_id[SEC_B].cost_basis == Decimal("200.00")


# --- opening state and determinism ---


def test_initial_state_rejects_non_positive_cash() -> None:
    for bad in ("0.00", "-1.00"):
        with pytest.raises(ValueError, match="initial cash"):
            initial_portfolio_state(
                session_key=_key(FRI),
                initial_cash=Decimal(bad),
                admission=EXPLORATORY,
            )


def test_non_terminating_basis_relief_is_deterministic() -> None:
    def run() -> Decimal:
        kernel = _kernel("10000.00")
        kernel.apply_fill(_buy(3, "33.33"))
        kernel.apply_fill(_sell(1, "40.00"))
        return kernel.state.holdings[0].cost_basis

    first = run()
    with localcontext() as ctx:
        # A dependency mangling the ambient context must not change the books.
        ctx.prec = 9
        second = run()
    assert first == second


# --- settled-claim replay (double payment) ---


def test_settled_claim_cannot_be_recorded_again() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.cash_balance == Decimal("1050.00")
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.record_claim(claim)
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_repeated_record_settle_cycles_cannot_pay_twice() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    for _ in range(3):
        with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
            kernel.record_claim(claim)
    # Exactly one payment, no matter how many times the effect is re-yielded.
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_settled_claim_survives_session_advance() -> None:
    kernel = _kernel("1000.00", day=FRI)
    claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    kernel.advance_session(_key(MON))
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        kernel.record_claim(claim)
    assert kernel.state.cash_balance == Decimal("1050.00")


def test_settled_ledger_is_carried_on_state_and_survives_reconstruction() -> None:
    kernel = _kernel("1000.00")
    claim = _claim(entitlement=FRI, payable=FRI)
    kernel.record_claim(claim)
    kernel.settle_claims((claim.claim_id,))
    assert kernel.state.settled_claim_ids == (claim.claim_id,)
    # A kernel rebuilt from persisted state must keep the guard.
    rebuilt = PortfolioAccountingKernel(kernel.state, session_clock=CLOCK)
    with pytest.raises(ValueError, match=KERNEL_SETTLED_GUARD):
        rebuilt.record_claim(claim)


def test_state_rejects_settled_claim_reappearing_as_pending() -> None:
    claim = _claim(entitlement=FRI, payable=FRI)
    with pytest.raises(
        (ValidationError, ValueError),
        match="claim already settled cannot be pending again",
    ):
        PortfolioStateV1(
            lane="exploratory",
            admission_hash=EXPLORATORY.admission_hash,
            session_key=_key(FRI),
            cash_balance=Decimal("0.00"),
            holdings=(),
            pending_cash_claims=(claim,),
            settled_claim_ids=(claim.claim_id,),
            mark=None,
            holdings_market_value=Decimal("0.00"),
            pending_claims_value=claim.total_cash_expected,
            net_asset_value=claim.total_cash_expected,
            realized_gross_pnl=Decimal("0.00"),
            realized_net_pnl=Decimal("0.00"),
            cumulative_transaction_costs=Decimal("0.00"),
        )


# --- ambient decimal context independence ---


def _cycle_hashes() -> tuple[str, Decimal]:
    # Cash is deliberately large: NAV must exceed the significant digits a
    # low ambient precision would keep, otherwise the test cannot detect an
    # unpinned rebuild.
    kernel = _kernel("12345678.91")
    kernel.apply_fill(_buy(3, "33.33"))
    first = _claim(
        component_id="cash-1",
        quantity=3,
        per_share="0.33",
        entitlement=FRI,
        payable=FRI,
    )
    second = _claim(
        component_id="cash-2",
        quantity=7,
        per_share="1.11",
        entitlement=FRI,
        payable=FRI,
    )
    third = _claim(
        component_id="cash-3",
        quantity=9,
        per_share="2.22",
        entitlement=FRI,
        payable=FRI,
    )
    kernel.record_claim(first)
    kernel.record_claim(second)
    kernel.record_claim(third)
    kernel.settle_claims((first.claim_id,))
    kernel.mark_close((_mark("34.00"),))
    return content_hash(kernel.state), kernel.state.net_asset_value


def test_state_hash_is_independent_of_ambient_decimal_context() -> None:
    baseline, baseline_nav = _cycle_hashes()
    for precision in (34, 28, 12, 9, 7):
        with localcontext() as ctx:
            ctx.prec = precision
            digest, nav = _cycle_hashes()
        assert nav == baseline_nav, f"NAV drifted at ambient prec {precision}"
        assert digest == baseline, f"state hash drifted at ambient prec {precision}"


def test_opening_state_reconciles_under_low_ambient_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 9
        state = initial_portfolio_state(
            session_key=_key(FRI),
            initial_cash=Decimal("12345678.91"),
            admission=EXPLORATORY,
        )
    assert state.net_asset_value == Decimal("12345678.91")


def test_claim_validation_holds_under_low_ambient_precision() -> None:
    with localcontext() as ctx:
        ctx.prec = 6
        claim = _claim(quantity=100, per_share="0.50", entitlement=FRI, payable=FRI)
    assert claim.total_cash_expected == Decimal("50.00")


# --- F8: monetary spelling is canonical, so equal money hashes equally ---


def test_state_hash_is_independent_of_decimal_spelling() -> None:
    terse = initial_portfolio_state(
        session_key=_key(FRI), initial_cash=Decimal("100000"), admission=EXPLORATORY
    )
    padded = initial_portfolio_state(
        session_key=_key(FRI), initial_cash=Decimal("100000.00"), admission=EXPLORATORY
    )
    assert terse == padded
    assert content_hash(terse) == content_hash(padded)


def test_claim_hash_is_independent_of_decimal_spelling() -> None:
    terse = _claim(quantity=100, per_share="0.5")
    padded = _claim(quantity=100, per_share="0.5000")
    assert terse == padded
    assert content_hash(terse) == content_hash(padded)


def test_holding_hash_is_independent_of_decimal_spelling() -> None:
    terse = SecurityHoldingV1(security_id=SEC_A, quantity=8, cost_basis=Decimal("100"))
    padded = SecurityHoldingV1(
        security_id=SEC_A, quantity=8, cost_basis=Decimal("100.000")
    )
    assert content_hash(terse) == content_hash(padded)


def test_mark_hash_is_independent_of_decimal_spelling() -> None:
    terse = _mark("21.5")
    padded = _mark("21.500")
    assert content_hash(terse) == content_hash(padded)


def test_realized_loss_keeps_its_sign_under_canonical_spelling() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.apply_fill(_sell(10, "19.00"))
    assert kernel.state.realized_gross_pnl == Decimal("-10")
    assert str(kernel.state.realized_gross_pnl) == "-10"


def test_canonical_money_preserves_value_and_collapses_spelling() -> None:
    cases = (
        ("100000.00", "100000"),
        ("0.50", "0.5"),
        ("0.00", "0"),
        ("-0.00", "0"),
        ("-12.3400", "-12.34"),
        ("1E+3", "1000"),
    )
    for raw, expected in cases:
        result = canonical_money(Decimal(raw))
        assert str(result) == expected
        assert result == Decimal(raw)


def test_canonical_money_gives_equal_amounts_exactly_one_spelling() -> None:
    # content_hash renders Decimals with str(), so the canonical form is only
    # useful if numerically equal amounts always reach the same str().
    pairs = (
        ("100000", "100000.00"),
        ("0.5", "0.50000"),
        ("1E+3", "1000.000"),
        ("1E-10", "0.0000000001"),
        ("-12.34", "-12.3400"),
        ("0", "-0.00"),
    )
    for left, right in pairs:
        assert Decimal(left) == Decimal(right)
        assert str(canonical_money(Decimal(left))) == str(
            canonical_money(Decimal(right))
        )


def test_canonical_money_refuses_a_spelling_the_m1c_rule_rejects() -> None:
    # The reused CanonicalCash rule is load-bearing, not decorative: it is what
    # refuses a rendering that is not a canonical nonnegative decimal.
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(
            ValueError, match="cash requires canonical nonnegative decimal text"
        ):
            canonical_money(Decimal(bad))


def test_monetary_fields_reject_float_input() -> None:
    with pytest.raises(
        (ValidationError, ValueError), match="requires an exact decimal value"
    ):
        SecurityHoldingV1(
            security_id=SEC_A,
            quantity=1,
            cost_basis=10.5,  # type: ignore[arg-type]
        )


def test_monetary_fields_reject_non_finite_decimals() -> None:
    for bad in ("NaN", "Infinity"):
        with pytest.raises(
            (ValidationError, ValueError), match="requires a finite decimal value"
        ):
            SecurityHoldingV1(security_id=SEC_A, quantity=1, cost_basis=Decimal(bad))


def test_monetary_fields_round_trip_through_json() -> None:
    kernel = _kernel("10000.00")
    kernel.apply_fill(_buy(10, "20.00"))
    kernel.mark_close((_mark("21.37"),))
    payload = kernel.state.model_dump_json()
    restored = PortfolioStateV1.model_validate_json(payload)
    assert restored == kernel.state
    assert content_hash(restored) == content_hash(kernel.state)
