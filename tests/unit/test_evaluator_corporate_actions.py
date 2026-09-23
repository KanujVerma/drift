"""Unit tests for M2 Task 4 corporate-action and economic outcome accounting."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

import pytest
from economic_test_support import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    bounded_boundary,
    economic_evidence,
    exact_boundary,
    parse_utc,
    public_channel,
    rebind_record_evidence,
    revision,
)
from observation_test_support import uid

from drift.domain.artifacts import ArtifactReference
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicComponentV1,
    EconomicDateFactV1,
    EconomicOccurrenceV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    EconomicSourceKeyV1,
    EconomicUnitBasisV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    OccurredEffectV1,
    ResidualClaimV1,
    TermsPayloadV1,
)
from drift.domain.economic_queries import MarketOutcomeQueryV1
from drift.domain.economic_results import (
    EconomicDeliveryGroupV1,
    EconomicEffectProjectionV1,
    EconomicOutcomeResolutionV1,
)
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_corporate_actions import (
    CashInLieuRateV1,
    DueBillRuleV1,
    SecurityEconomicOutcomeV1,
    TieBreakingRuleV1,
    cash_in_lieu_component_id,
    exact_decimal,
    exact_entitled_shares,
    ratio_fraction,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    MarkEvidenceV1,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioStateV1,
    SecurityHoldingV1,
    pending_cash_claim_id,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.corporate_actions import CorporateActionProcessor
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.serialization.canonical import content_hash

BOOK_NAMESPACE = "ISO-4217"
BOOK_CODE = "USD"

SEC_A = uid(21)
SEC_CHILD = uid(31)
SEC_ACQ = uid(41)
SEC_OTHER = uid(51)

EFFECT_DAY = date(2020, 6, 1)
PAYABLE_DAY = date(2020, 6, 15)
LATER_DAY = date(2020, 6, 8)
ENTITLED_DAY = date(2020, 6, 9)

EFFECT_AT = "2020-06-01T00:00:00Z"
PAYABLE_AT = "2020-06-15T00:00:00Z"
LATER_AT = "2020-06-08T00:00:00Z"
ENTITLED_AT = "2020-06-09T00:00:00Z"
# Dates the clock below does not contain: one between its first two sessions,
# and one before its first session.
BETWEEN_DAY = date(2020, 6, 5)
BETWEEN_AT = "2020-06-05T00:00:00Z"
BEFORE_CLOCK_AT = "2020-05-29T00:00:00Z"

ZERO = Decimal("0")
ZERO_HASH = "0" * 64

SOURCE_A = "synthetic-a"
SOURCE_B = "synthetic-b"


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------


def _key(day: date = EFFECT_DAY) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


# --- session clock and lane admission scaffolding ---


def _evaluation_session(day: date) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_key(day),
        opened_at=datetime.combine(day, time(14), tzinfo=UTC),
        closed_at=datetime.combine(day, time(21), tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(HASH_A,),
        authority_proof_hashes=(HASH_B,),
        session_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _clock(*days: date) -> SessionClockV1:
    """Realized-authority clock authorizing exactly the sessions under test."""
    sessions = tuple(
        sorted((_evaluation_session(day) for day in days), key=session_order_key)
    )
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=sessions,
        acknowledged_limitations=(),
        clock_hash=ZERO_HASH,
    )
    candidate = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(candidate.model_dump())


# Every session any test positions a book at. A book session the clock does
# not authorize is refused by the accounting kernel, so this list is the
# authority the whole file is evaluated against.
CLOCK = _clock(EFFECT_DAY, LATER_DAY, ENTITLED_DAY, PAYABLE_DAY)


def _exploratory_admission() -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=HASH_C,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )


EXPLORATORY = _exploratory_admission()


def _ref(label: str) -> ArtifactReference:
    reference, _ = economic_evidence(label)
    return reference


def _treatment(
    kind: str, source_rule: str = "source fraction rule"
) -> FractionTreatmentV1:
    if kind == "unknown":
        return FractionTreatmentV1(kind="unknown")
    return FractionTreatmentV1(
        kind=kind,  # type: ignore[arg-type]
        source_rule=source_rule,
        evidence_reference=_ref(f"fraction treatment {kind} {source_rule}"),
    )


def _shares(
    *,
    numerator: str,
    denominator: str,
    component_id: str = "shares-1",
    recipient: UUID = SEC_A,
    predecessor: UUID = SEC_A,
    meaning: str = "resulting_per_predecessor",
    treatment: FractionTreatmentV1 | None = None,
    share_basis: str = "predecessor_pre_action",
) -> ShareComponentV1:
    return ShareComponentV1(
        kind="shares",
        component_id=component_id,
        recipient=EconomicRecipientV1(kind="security", security_id=recipient),
        ratio=PositiveRatioV1(numerator=numerator, denominator=denominator),
        ratio_meaning=meaning,  # type: ignore[arg-type]
        unit_basis=EconomicShareBasisV1(
            security_id=predecessor,
            share_basis=share_basis,  # type: ignore[arg-type]
        ),
        fraction_treatment=(
            _treatment("round_down") if treatment is None else treatment
        ),
        applicability="ordinary_passive_holder",
        conditions=(),
    )


def _cash(
    *,
    amount: str,
    component_id: str = "cash-1",
    predecessor: UUID = SEC_A,
    numerator: str = "1",
    denominator: str = "1",
    namespace: str = BOOK_NAMESPACE,
    code: str = BOOK_CODE,
    amount_basis: str = "gross",
) -> CashComponentV1:
    return CashComponentV1(
        kind="cash",
        component_id=component_id,
        amount=amount,
        currency_namespace=namespace,
        currency_code=code,
        unit_basis=EconomicUnitBasisV1(
            security_id=predecessor,
            denominator=PositiveRatioV1(numerator=numerator, denominator=denominator),
            share_basis="predecessor_pre_action",
        ),
        amount_basis=amount_basis,  # type: ignore[arg-type]
        applicability="ordinary_passive_holder",
        conditions=(),
    )


def _date_fact(role: str, label: str, *, with_rule: bool = False) -> EconomicDateFactV1:
    return EconomicDateFactV1(
        role=role,  # type: ignore[arg-type]
        boundary=exact_boundary(label, _ref(f"{role} boundary {label}")),
        rule_reference=_ref(f"{role} rule {label}") if with_rule else None,
    )


def _terms(
    *,
    suffix: int,
    action_kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    dates: tuple[EconomicDateFactV1, ...] = (),
    source_id: str = "synthetic-a",
    security_id: UUID = SEC_A,
) -> CorporateActionTermsVersionV1:
    return rebind_record_evidence(
        CorporateActionTermsVersionV1,
        {
            "schema_version": "1",
            "revision": revision(
                suffix, "2020-05-01T00:00:00Z", _ref(f"terms seed {suffix}")
            ),
            "source_key": EconomicSourceKeyV1(
                source_id=source_id,
                family="terms",
                native_record_id=f"terms-{suffix}",
            ),
            "security_id": security_id,
            "listing_id": None,
            "occurrence": EconomicOccurrenceV1(
                kind="unknown", reason="terms do not claim an occurrence"
            ),
            "source_action_code": action_kind.value,
            "scheduled_effect_time": exact_boundary(
                EFFECT_AT, _ref(f"terms schedule {suffix}")
            ),
            "payload": TermsPayloadV1(
                kind="fixed",
                action_kind=action_kind,
                components=components,
                dates=dates,
                conditions=(),
                reason=None,
            ),
        },
    )


def _effect(
    *,
    suffix: int,
    action_kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    terms: CorporateActionTermsVersionV1 | None,
    occurrence_id: str | None = "occ-1",
    effective_at: str = EFFECT_AT,
    claim_status: str = "continuing",
    consideration_status: str = "components",
    source_id: str = "synthetic-a",
    security_id: UUID = SEC_A,
    asserted_hash: str | None = None,
) -> EconomicEffectVersionV1:
    association: EconomicAssociationV1
    if terms is None:
        association = EconomicAssociationV1(
            kind="unknown", reason="source did not name its terms"
        )
    else:
        association = EconomicAssociationV1(
            kind="identified",
            target=terms.source_key,
            asserted_target_version_hash=(
                content_hash(terms) if asserted_hash is None else asserted_hash
            ),
        )
    occurrence = (
        EconomicOccurrenceV1(
            kind="identified",
            native_occurrence_id=occurrence_id,
            evidence_reference=_ref(f"occurrence {occurrence_id} {suffix}"),
        )
        if occurrence_id is not None
        else EconomicOccurrenceV1(
            kind="unknown", reason="source did not name occurrence"
        )
    )
    return rebind_record_evidence(
        EconomicEffectVersionV1,
        {
            "schema_version": "1",
            "revision": revision(suffix, effective_at, _ref(f"effect seed {suffix}")),
            "source_key": EconomicSourceKeyV1(
                source_id=source_id,
                family="effect",
                native_record_id=f"effect-{suffix}",
            ),
            "security_id": security_id,
            "listing_id": None,
            "occurrence": occurrence,
            "source_action_code": action_kind.value,
            "effective_time": exact_boundary(
                effective_at, _ref(f"effect instant {suffix}")
            ),
            "terms_association": association,
            "payload": OccurredEffectV1(
                kind="occurred",
                action_kind=action_kind,
                claim_status=claim_status,  # type: ignore[arg-type]
                consideration_status=consideration_status,  # type: ignore[arg-type]
                owed_components=components,
                residual=ResidualClaimV1(
                    kind="unknown", reason="source did not address residual"
                ),
                evidence_reference=_ref(f"effect payload {suffix}"),
            ),
        },
    )


def _projection(
    effect: EconomicEffectVersionV1, status: str = "effective"
) -> EconomicEffectProjectionV1:
    payload = effect.payload
    assert isinstance(payload, OccurredEffectV1)
    return EconomicEffectProjectionV1(
        source_record_hash=content_hash(effect),
        effective_status=status,  # type: ignore[arg-type]
        claim_status=payload.claim_status,
        consideration_status=payload.consideration_status,
        owed_components=payload.owed_components,
        component_gaps=(),
        safe_fact_projection_hash=HASH_A,
    )


def _delivery(
    *,
    components: tuple[EconomicComponentV1, ...],
    security_id: UUID = SEC_A,
    occurrence_id: str = "occ-1",
    settled_at: str = PAYABLE_AT,
    source_id: str = "synthetic-a",
    residual_status: str = "closed_for_occurrence",
) -> EconomicDeliveryGroupV1:
    return EconomicDeliveryGroupV1(
        source_id=source_id,
        security_id=security_id,
        native_occurrence_id=occurrence_id,
        settled_time=exact_boundary(
            settled_at, _ref(f"delivery {occurrence_id} {settled_at}")
        ),
        delivered_components=components,
        component_gaps=(),
        residual_status=residual_status,  # type: ignore[arg-type]
        contributing_record_hashes=(HASH_A,),
        projection_hashes=(HASH_B,),
        association_result_hashes=(HASH_C,),
    )


def _query(
    security_id: UUID, action_kinds: tuple[ActionKind, ...]
) -> MarketOutcomeQueryV1:
    return MarketOutcomeQueryV1(
        schema_version="1",
        security_id=security_id,
        action_kinds=tuple(sorted(set(action_kinds), key=lambda item: item.value)),
        history_start=parse_utc("2020-01-01T00:00:00Z"),
        requested_channel=public_channel(),
        availability_policy_id="synthetic-availability",
        availability_policy_hash=HASH_A,
        source_selection_policy_hash=HASH_B,
        input_context_hash=HASH_C,
        kind="outcome",
        purpose="economic_outcome",
        economic_horizon=parse_utc("2021-01-01T00:00:00Z"),
        evidence_vintage_cutoff=parse_utc("2021-01-01T00:00:00Z"),
    )


def _outcome(
    *,
    security_id: UUID = SEC_A,
    terms: tuple[CorporateActionTermsVersionV1, ...] = (),
    effects: tuple[EconomicEffectVersionV1, ...] = (),
    statuses: tuple[str, ...] | None = None,
    delivery_groups: tuple[EconomicDeliveryGroupV1, ...] = (),
    support_status: str = "supported",
    action_kinds: tuple[ActionKind, ...] = (ActionKind.REGULAR_CASH_DIVIDEND,),
) -> SecurityEconomicOutcomeV1:
    effect_statuses = ("effective",) * len(effects) if statuses is None else statuses
    query = _query(security_id, action_kinds)
    resolution = EconomicOutcomeResolutionV1(
        schema_version="1",
        query=query,
        query_hash=content_hash(query),
        selection_proof_hash=HASH_D,
        source_selection_policy_hash=query.source_selection_policy_hash,
        input_context_hash=query.input_context_hash,
        composition_algorithm="drift-m1c-economic-composition-v1",
        composition_algorithm_spec_hash=HASH_E,
        composition_implementation_hash=HASH_A,
        selected_terms_hashes=tuple(content_hash(item) for item in terms),
        upcoming_terms_hashes=(),
        effect_projections=tuple(
            _projection(effect, status)
            for effect, status in zip(effects, effect_statuses, strict=True)
        ),
        cancelled_action_hashes=(),
        unknown_effect_hashes=(),
        delivery_groups=delivery_groups,
        uncomposed_settlement_hashes=(),
        associations=(),
        coverage_results=(),
        residual_resolutions=(),
        safe_projection_hashes=(),
        claim_status="continuing",
        evidence_completeness="known",
        support_status=support_status,  # type: ignore[arg-type]
        reasons=() if support_status == "supported" else ("synthetic gap",),
    )
    return SecurityEconomicOutcomeV1(
        security_id=security_id,
        resolution=resolution,
        terms_records=terms,
        effect_records=effects,
    )


def _mark_price(security_id: UUID, price: str) -> MarkPriceV1:
    """One exploratory-grade close price bound to the evidence it came from."""
    return MarkPriceV1(
        security_id=security_id,
        close_price=Decimal(price),
        evidence=MarkEvidenceV1(grade="exploratory", evidence_hash=HASH_D),
    )


def _holding(
    security_id: UUID = SEC_A, quantity: int = 100, basis: str = "1000"
) -> SecurityHoldingV1:
    return SecurityHoldingV1(
        security_id=security_id, quantity=quantity, cost_basis=Decimal(basis)
    )


def _state(
    *,
    holdings: tuple[SecurityHoldingV1, ...] = (),
    cash: str = "10000",
    claims: tuple[PendingCashClaimV1, ...] = (),
    settled: tuple[str, ...] = (),
    day: date = EFFECT_DAY,
) -> PortfolioStateV1:
    claims_value = sum((claim.total_cash_expected for claim in claims), ZERO)
    cash_value = Decimal(cash)
    return PortfolioStateV1(
        lane="exploratory",
        admission_hash=EXPLORATORY.admission_hash,
        session_key=_key(day),
        cash_balance=cash_value,
        holdings=holdings,
        pending_cash_claims=claims,
        settled_claim_ids=tuple(sorted(settled)),
        mark=None,
        holdings_market_value=ZERO,
        pending_claims_value=claims_value,
        net_asset_value=cash_value + claims_value,
        realized_gross_pnl=ZERO,
        realized_net_pnl=ZERO,
        cumulative_transaction_costs=ZERO,
    )


def _processor(
    *,
    tie_breaking_rules: tuple[TieBreakingRuleV1, ...] = (),
    due_bill_rules: tuple[DueBillRuleV1, ...] = (),
    cash_in_lieu_rates: tuple[CashInLieuRateV1, ...] = (),
) -> CorporateActionProcessor:
    return CorporateActionProcessor(
        session_clock=CLOCK,
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
        tie_breaking_rules=tie_breaking_rules,
        due_bill_rules=due_bill_rules,
        cash_in_lieu_rates=cash_in_lieu_rates,
    )


type _SplitCase = tuple[
    CorporateActionTermsVersionV1, EconomicEffectVersionV1, SecurityEconomicOutcomeV1
]


def _split_case_components(
    *,
    suffix: int,
    components: tuple[EconomicComponentV1, ...],
    action_kind: ActionKind = ActionKind.REVERSE_SPLIT,
    dates: tuple[EconomicDateFactV1, ...] = (),
) -> _SplitCase:
    terms = _terms(
        suffix=suffix,
        action_kind=action_kind,
        components=components,
        dates=dates,
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=action_kind,
        components=components,
        terms=terms,
    )
    outcome = _outcome(terms=(terms,), effects=(effect,), action_kinds=(action_kind,))
    return terms, effect, outcome


def _split_case_component(
    *,
    suffix: int,
    component: EconomicComponentV1,
    action_kind: ActionKind = ActionKind.REVERSE_SPLIT,
    dates: tuple[EconomicDateFactV1, ...] = (),
) -> _SplitCase:
    return _split_case_components(
        suffix=suffix,
        components=(component,),
        action_kind=action_kind,
        dates=dates,
    )


def _split_case(
    *,
    numerator: str,
    denominator: str,
    treatment: FractionTreatmentV1,
    action_kind: ActionKind = ActionKind.REVERSE_SPLIT,
    suffix: int = 700,
    dates: tuple[EconomicDateFactV1, ...] = (),
) -> _SplitCase:
    return _split_case_component(
        suffix=suffix,
        component=_shares(
            numerator=numerator, denominator=denominator, treatment=treatment
        ),
        action_kind=action_kind,
        dates=dates,
    )


def _cash_in_lieu_rate(
    *,
    effect: EconomicEffectVersionV1,
    component_id: str = "shares-1",
    rate: str = "4",
    namespace: str = BOOK_NAMESPACE,
    code: str = BOOK_CODE,
    evidence: ArtifactReference | None = None,
) -> CashInLieuRateV1:
    payload = effect.payload
    assert isinstance(payload, OccurredEffectV1)
    share = next(
        item
        for item in payload.owed_components
        if isinstance(item, ShareComponentV1) and item.component_id == component_id
    )
    bound = share.fraction_treatment.evidence_reference
    assert bound is not None
    occurrence_id = effect.occurrence.native_occurrence_id
    assert occurrence_id is not None
    return CashInLieuRateV1(
        source_id=effect.source_key.source_id,
        security_id=effect.security_id,
        occurrence_id=occurrence_id,
        component_id=component_id,
        evidence_reference=bound if evidence is None else evidence,
        cash_per_whole_share=rate,
        currency_namespace=namespace,
        currency_code=code,
    )


def _tie_rule(
    *,
    effect: EconomicEffectVersionV1,
    tie_break: str,
    component_id: str = "shares-1",
) -> TieBreakingRuleV1:
    payload = effect.payload
    assert isinstance(payload, OccurredEffectV1)
    share = next(
        item
        for item in payload.owed_components
        if isinstance(item, ShareComponentV1) and item.component_id == component_id
    )
    treatment = share.fraction_treatment
    assert treatment.source_rule is not None
    assert treatment.evidence_reference is not None
    return TieBreakingRuleV1(
        source_rule=treatment.source_rule,
        evidence_reference=treatment.evidence_reference,
        tie_break=tie_break,  # type: ignore[arg-type]
    )


def _dividend_case(
    *,
    action_kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
    amount: str = "0.5",
    dates: tuple[EconomicDateFactV1, ...] | None = None,
    suffix: int = 800,
    namespace: str = BOOK_NAMESPACE,
    code: str = BOOK_CODE,
    amount_basis: str = "gross",
) -> tuple[
    CorporateActionTermsVersionV1, EconomicEffectVersionV1, SecurityEconomicOutcomeV1
]:
    component = _cash(
        amount=amount, namespace=namespace, code=code, amount_basis=amount_basis
    )
    date_facts = (
        (
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
        )
        if dates is None
        else dates
    )
    terms = _terms(
        suffix=suffix,
        action_kind=action_kind,
        components=(component,),
        dates=date_facts,
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=action_kind,
        components=(component,),
        terms=terms,
    )
    outcome = _outcome(terms=(terms,), effects=(effect,), action_kinds=(action_kind,))
    return terms, effect, outcome


# --------------------------------------------------------------------------
# exact rational arithmetic
# --------------------------------------------------------------------------


def test_ratio_fraction_is_exact_rational() -> None:
    value = ratio_fraction(PositiveRatioV1(numerator="1", denominator="3"))
    assert value == Fraction(1, 3)
    assert isinstance(value, Fraction)


def test_exact_entitled_shares_resulting_per_predecessor() -> None:
    component = _shares(numerator="2", denominator="1")
    assert exact_entitled_shares(100, component) == Fraction(200)


def test_exact_entitled_shares_additional_same_recipient_adds() -> None:
    component = _shares(
        numerator="1", denominator="10", meaning="additional_per_predecessor"
    )
    assert exact_entitled_shares(100, component) == Fraction(110)


def test_exact_entitled_shares_additional_child_recipient_is_child_only() -> None:
    component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_CHILD,
        meaning="additional_per_predecessor",
    )
    assert exact_entitled_shares(100, component) == Fraction(50)


def test_exact_entitled_shares_rejects_unknown_share_basis() -> None:
    component = _shares(
        numerator="2", denominator="1", share_basis="as_reported_unknown"
    )
    with pytest.raises(IndeterminateValuationError, match="known source share basis"):
        exact_entitled_shares(100, component)


def test_exact_decimal_rejects_non_terminating_quotient() -> None:
    with pytest.raises(
        IndeterminateValuationError, match="exactly representable as a decimal"
    ):
        exact_decimal(Fraction(1, 3))


def test_exact_decimal_is_exact_for_terminating_quotient() -> None:
    assert exact_decimal(Fraction(1, 8)) == Decimal("0.125")
    assert exact_decimal(Fraction(0)) == Decimal("0")


def test_split_entitlement_uses_integer_arithmetic_not_floats() -> None:
    # A float implementation loses the low digits of this quotient entirely.
    quantity = 333_333_333_333_333_333
    _, _, outcome = _split_case(
        numerator="1",
        denominator="3",
        treatment=_treatment("round_down"),
        suffix=100,
    )
    state = _state(holdings=(_holding(quantity=quantity),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert updated.holdings[0].quantity == 111_111_111_111_111_111


# --------------------------------------------------------------------------
# GREEN criteria: fraction treatment
# --------------------------------------------------------------------------


def test_reverse_split_aggregate_sale_cash_creates_share_and_in_lieu_claim() -> None:
    treatment = _treatment("aggregate_sale_cash")
    terms, effect, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=treatment,
        suffix=110,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    del terms
    processor = _processor(
        cash_in_lieu_rates=(_cash_in_lieu_rate(effect=effect, rate="4"),)
    )
    state = _state(holdings=(_holding(quantity=10, basis="800"),))
    updated, _ = processor.apply_pre_open_actions(state, (), (outcome,), _key())

    assert len(updated.holdings) == 1
    assert updated.holdings[0].quantity == 1
    assert updated.holdings[0].cost_basis == Decimal("800")
    assert len(updated.pending_cash_claims) == 1
    claim = updated.pending_cash_claims[0]
    assert claim.component_id == cash_in_lieu_component_id("shares-1", Fraction(1, 4))
    assert "1/4" in claim.component_id
    assert claim.entitled_quantity == 1
    assert claim.total_cash_expected == Decimal("1")
    assert claim.entitlement_session == EFFECT_DAY
    assert claim.payable_session == PAYABLE_DAY


def test_reverse_split_unknown_fraction_treatment_is_indeterminate() -> None:
    _, _, outcome = _split_case(
        numerator="1", denominator="8", treatment=_treatment("unknown"), suffix=120
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError, match="no resolvable fraction treatment"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_reverse_split_fraction_issued_is_indeterminate_not_truncated() -> None:
    _, _, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("fraction_issued"),
        suffix=130,
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError, match="no resolvable fraction treatment"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_round_nearest_with_tie_rule_executes_deterministically() -> None:
    for tie_break, expected in (("half_up", 3), ("half_even", 2), ("half_down", 2)):
        _, effect, outcome = _split_case(
            numerator="1",
            denominator="2",
            treatment=_treatment("round_nearest", f"nearest {tie_break}"),
            suffix=140,
        )
        processor = _processor(
            tie_breaking_rules=(_tie_rule(effect=effect, tie_break=tie_break),)
        )
        state = _state(holdings=(_holding(quantity=5),))
        updated, _ = processor.apply_pre_open_actions(state, (), (outcome,), _key())
        assert updated.holdings[0].quantity == expected


def test_round_nearest_without_tie_rule_is_indeterminate() -> None:
    _, _, outcome = _split_case(
        numerator="1",
        denominator="2",
        treatment=_treatment("round_nearest"),
        suffix=150,
    )
    state = _state(holdings=(_holding(quantity=5),))
    with pytest.raises(
        IndeterminateValuationError,
        match="interpreted source tie-breaking rule",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_round_nearest_rule_bound_to_other_evidence_is_indeterminate() -> None:
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="2",
        treatment=_treatment("round_nearest"),
        suffix=160,
    )
    foreign = TieBreakingRuleV1(
        source_rule="source fraction rule",
        evidence_reference=_ref("unrelated tie-breaking statement"),
        tie_break="half_up",
    )
    del effect
    state = _state(holdings=(_holding(quantity=5),))
    with pytest.raises(
        IndeterminateValuationError,
        match="interpreted source tie-breaking rule",
    ):
        _processor(tie_breaking_rules=(foreign,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_round_down_truncates_and_round_up_rounds_up() -> None:
    for kind, expected in (("round_down", 1), ("round_up", 2)):
        _, _, outcome = _split_case(
            numerator="1", denominator="8", treatment=_treatment(kind), suffix=170
        )
        state = _state(holdings=(_holding(quantity=10),))
        updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
        assert updated.holdings[0].quantity == expected


def test_split_that_extinguishes_a_position_is_indeterminate() -> None:
    _, _, outcome = _split_case(
        numerator="1", denominator="8", treatment=_treatment("round_down"), suffix=180
    )
    state = _state(holdings=(_holding(quantity=1),))
    with pytest.raises(
        IndeterminateValuationError,
        match="would extinguish a held position",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_cash_in_lieu_without_proven_rate_is_indeterminate() -> None:
    _, _, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=190,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="proven source aggregate-sale cash rate",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_cash_in_lieu_rate_in_foreign_currency_is_indeterminate() -> None:
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=200,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    rate = _cash_in_lieu_rate(effect=effect, rate="4", code="EUR")
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError, match="does not match the book currency"
    ):
        _processor(cash_in_lieu_rates=(rate,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_cash_in_lieu_amount_that_is_not_exact_is_indeterminate() -> None:
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="3",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=210,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    rate = _cash_in_lieu_rate(effect=effect, rate="1")
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError, match="exactly representable as a decimal"
    ):
        _processor(cash_in_lieu_rates=(rate,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


# --------------------------------------------------------------------------
# GREEN criteria: staged target scaling
# --------------------------------------------------------------------------


def test_forward_split_doubles_holdings_and_staged_targets() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=220,
    )
    state = _state(holdings=(_holding(quantity=100, basis="1000"),))
    targets = (
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=50),
        SecurityTargetPositionV1(security_id=SEC_OTHER, target_quantity=7),
    )
    updated, scaled = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )
    assert updated.holdings[0].quantity == 200
    assert updated.holdings[0].cost_basis == Decimal("1000")
    by_security = {item.security_id: item.target_quantity for item in scaled}
    assert by_security[SEC_A] == 100
    assert by_security[SEC_OTHER] == 7


def test_split_scales_staged_target_without_any_holding() -> None:
    _, _, outcome = _split_case(
        numerator="3",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=230,
    )
    targets = (SecurityTargetPositionV1(security_id=SEC_A, target_quantity=5),)
    updated, scaled = _processor().apply_pre_open_actions(
        _state(), targets, (outcome,), _key()
    )
    assert updated.holdings == ()
    assert scaled[0].target_quantity == 15


def test_non_integral_unresolved_staged_target_is_indeterminate() -> None:
    _, _, outcome = _split_case(
        numerator="1",
        denominator="2",
        treatment=_treatment("round_nearest"),
        suffix=240,
    )
    targets = (SecurityTargetPositionV1(security_id=SEC_A, target_quantity=5),)
    with pytest.raises(
        IndeterminateValuationError,
        match="interpreted source tie-breaking rule",
    ):
        _processor().apply_pre_open_actions(_state(), targets, (outcome,), _key())


def test_staged_targets_must_be_unique_by_security() -> None:
    targets = (
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=1),
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=2),
    )
    with pytest.raises(ValueError, match="staged targets must be unique by security"):
        _processor().apply_pre_open_actions(_state(), targets, (), _key())


# --------------------------------------------------------------------------
# GREEN criteria: stock dividend and spin-off
# --------------------------------------------------------------------------


def test_stock_dividend_adds_shares_to_the_same_security() -> None:
    component = _shares(
        numerator="1",
        denominator="10",
        meaning="additional_per_predecessor",
        treatment=_treatment("round_down"),
    )
    terms = _terms(
        suffix=250, action_kind=ActionKind.STOCK_DIVIDEND, components=(component,)
    )
    effect = _effect(
        suffix=251,
        action_kind=ActionKind.STOCK_DIVIDEND,
        components=(component,),
        terms=terms,
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.STOCK_DIVIDEND,)
    )
    state = _state(holdings=(_holding(quantity=100, basis="1000"),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert updated.holdings[0].quantity == 110
    assert updated.holdings[0].cost_basis == Decimal("1000")


def test_spinoff_creates_child_holding_and_marks_nav_cleanly() -> None:
    component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_CHILD,
        meaning="additional_per_predecessor",
        treatment=_treatment("round_down"),
    )
    terms = _terms(suffix=260, action_kind=ActionKind.SPINOFF, components=(component,))
    effect = _effect(
        suffix=261,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        terms=terms,
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.SPINOFF,)
    )
    state = _state(holdings=(_holding(quantity=100, basis="1000"),), cash="500")
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    by_security = {item.security_id: item for item in updated.holdings}
    assert by_security[SEC_A].quantity == 100
    assert by_security[SEC_A].cost_basis == Decimal("1000")
    assert by_security[SEC_CHILD].quantity == 50
    assert by_security[SEC_CHILD].cost_basis == ZERO

    kernel = PortfolioAccountingKernel(updated, session_clock=CLOCK)
    kernel.mark_close((_mark_price(SEC_A, "10"), _mark_price(SEC_CHILD, "4")))
    assert kernel.state.holdings_market_value == Decimal("1200")
    assert kernel.state.net_asset_value == Decimal("1700")


# --------------------------------------------------------------------------
# GREEN criteria: due bills
# --------------------------------------------------------------------------


def _due_bill_terms() -> tuple[
    CorporateActionTermsVersionV1, EconomicEffectVersionV1, SecurityEconomicOutcomeV1
]:
    return _dividend_case(
        action_kind=ActionKind.SPECIAL_CASH_DISTRIBUTION,
        amount="2",
        suffix=300,
        dates=(
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
            _date_fact("due_bill_redemption", LATER_AT, with_rule=True),
        ),
    )


def _due_bill_rule(
    terms: CorporateActionTermsVersionV1,
    *,
    entitlement: date,
    redemption: date = LATER_DAY,
    executability: str = "executable",
    reference: ArtifactReference | None = None,
    source_id: str = "synthetic-a",
) -> DueBillRuleV1:
    payload = terms.payload
    assert payload is not None
    fact = next(item for item in payload.dates if item.role == "due_bill_redemption")
    bound = fact.rule_reference
    assert bound is not None
    ambiguous = executability == "ambiguous"
    return DueBillRuleV1(
        source_id=source_id,
        security_id=terms.security_id,
        occurrence_id="occ-1",
        rule_reference=bound if reference is None else reference,
        source_rule="due bills redeem on the proven redemption session",
        executability=executability,  # type: ignore[arg-type]
        entitlement_session=None if ambiguous else entitlement,
        redemption_session=None if ambiguous else redemption,
        reason="source rule is not executable" if ambiguous else None,
    )


def test_due_bill_dividend_defers_entitlement_to_the_proven_rule_session() -> None:
    terms, _, outcome = _due_bill_terms()
    # The proven rule names a session that is not the redemption session, so a
    # generic redemption-equals-entitlement shortcut cannot reproduce it.
    rule = _due_bill_rule(terms, entitlement=ENTITLED_DAY, redemption=LATER_DAY)
    processor = _processor(due_bill_rules=(rule,))
    state = _state(holdings=(_holding(quantity=100),))

    same_day, _ = processor.apply_pre_open_actions(state, (), (outcome,), _key())
    assert same_day.pending_cash_claims == ()
    assert same_day is state

    redemption_state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)
    on_redemption, _ = processor.apply_pre_open_actions(
        redemption_state, (), (outcome,), _key(LATER_DAY)
    )
    assert on_redemption.pending_cash_claims == ()

    entitled_state = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    entitled, _ = processor.apply_pre_open_actions(
        entitled_state, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert len(entitled.pending_cash_claims) == 1
    claim = entitled.pending_cash_claims[0]
    assert claim.entitlement_session == ENTITLED_DAY
    assert claim.payable_session == PAYABLE_DAY
    assert claim.total_cash_expected == Decimal("200")


def test_due_bill_without_a_proven_rule_is_indeterminate() -> None:
    _, _, outcome = _due_bill_terms()
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="proven executable due-bill rule",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_due_bill_with_an_ambiguous_rule_is_indeterminate() -> None:
    terms, _, outcome = _due_bill_terms()
    rule = _due_bill_rule(terms, entitlement=LATER_DAY, executability="ambiguous")
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="due-bill rule is not executable",
    ):
        _processor(due_bill_rules=(rule,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_due_bill_rule_not_bound_to_source_evidence_is_indeterminate() -> None:
    terms, _, outcome = _due_bill_terms()
    rule = _due_bill_rule(
        terms,
        entitlement=LATER_DAY,
        reference=_ref("an unrelated due-bill statement"),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="not bound to the source due-bill evidence",
    ):
        _processor(due_bill_rules=(rule,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


# --------------------------------------------------------------------------
# cash dividends and delivered settlement
# --------------------------------------------------------------------------


def test_cash_dividend_creates_claim_and_settles_on_delivered_evidence() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=310)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert len(staged.pending_cash_claims) == 1
    claim = staged.pending_cash_claims[0]
    assert claim.cash_per_share == Decimal("0.5")
    assert claim.total_cash_expected == Decimal("50.0")
    assert staged.cash_balance == Decimal("1000")

    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    payable_state = _payable_state(staged)
    settled = _processor().apply_intrasession_settlements(
        payable_state, (delivered,), _key(PAYABLE_DAY)
    )
    assert settled.pending_cash_claims == ()
    assert settled.cash_balance == Decimal("1050.0")
    assert settled.settled_claim_ids == (claim.claim_id,)


def _payable_state(state: PortfolioStateV1) -> PortfolioStateV1:
    kernel = PortfolioAccountingKernel(state, session_clock=CLOCK)
    kernel.advance_session(_key(PAYABLE_DAY))
    return kernel.state


def test_delivered_cash_without_a_proven_entitlement_is_indeterminate() -> None:
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    # Cash was delivered on a security the book holds, and no occurred effect
    # says what it was owed for, so the book cannot show it was not owed.
    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (delivered,), _key(PAYABLE_DAY)
        )


def test_delivered_cash_on_an_unexposed_security_commits_nothing() -> None:
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    state = _state(cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (delivered,), _key(PAYABLE_DAY)
    )

    # Delivered cash that no proven entitlement claims commits nothing.
    # Crediting it would create money from an unmatched report.
    assert settled is state
    assert settled.cash_balance == Decimal("1000")


def _delivered_dividend(
    *,
    suffix: int,
    ex_at: str = EFFECT_AT,
    settled_at: str = PAYABLE_AT,
    delivered_component: str = "cash-1",
    delivered_occurrence: str = "occ-1",
) -> SecurityEconomicOutcomeV1:
    """A 0.50 dividend whose full evidence rides with its delivered report."""
    terms, effect, _ = _dividend_case(
        amount="0.5",
        suffix=suffix,
        dates=(
            _date_fact("ex", ex_at),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    delivery = _delivery(
        components=(_cash(amount="0.5", component_id=delivered_component),),
        settled_at=settled_at,
        occurrence_id=delivered_occurrence,
    )
    return _outcome(terms=(terms,), effects=(effect,), delivery_groups=(delivery,))


def test_delivered_cash_the_ex_date_rule_proves_unowed_commits_nothing() -> None:
    outcome = _delivered_dividend(suffix=1600)
    # Held on the payable session but not at the ex date's prior close, as a
    # buy on or after the ex date is. The entitlement vested on the ex date
    # with nothing to pay, so the delivery owes this book nothing.
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state
    assert settled.cash_balance == Decimal("1000")


def test_delivered_cash_on_the_day_its_entitlement_vests_can_be_unowed() -> None:
    outcome = _delivered_dividend(suffix=1605, ex_at=LATER_AT, settled_at=LATER_AT)
    # Bought at the ex-date open, and paid on the same session: the ex date
    # vested this morning against a prior close that held nothing.
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=LATER_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(LATER_DAY)
    )

    assert settled is state


def test_delivered_cash_for_another_occurrence_is_indeterminate() -> None:
    # The effect proves occ-1, but the delivered report names occ-2, so no
    # proven entitlement explains it.
    outcome = _delivered_dividend(suffix=1615, delivered_occurrence="occ-2")
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (outcome,), _key(PAYABLE_DAY)
        )


def test_delivered_cash_two_effects_could_explain_is_indeterminate() -> None:
    terms, regular, _ = _dividend_case(
        amount="0.5",
        suffix=1625,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    special_terms, special, _ = _dividend_case(
        action_kind=ActionKind.SPECIAL_CASH_DISTRIBUTION,
        amount="0.5",
        suffix=1627,
        dates=(_date_fact("ex", LATER_AT), _date_fact("payable", PAYABLE_AT)),
    )
    # Two effective reports of one occurrence, of different kinds, both owe
    # cash-1. The delivered report cannot say which one it pays.
    outcome = _outcome(
        terms=(terms, special_terms),
        effects=(regular, special),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
        action_kinds=(
            ActionKind.REGULAR_CASH_DIVIDEND,
            ActionKind.SPECIAL_CASH_DISTRIBUTION,
        ),
    )
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (outcome,), _key(PAYABLE_DAY)
        )


def test_delivered_cash_before_its_entitlement_vests_is_indeterminate() -> None:
    outcome = _delivered_dividend(suffix=1610, ex_at=PAYABLE_AT, settled_at=LATER_AT)
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=LATER_DAY)

    # The ex date is still ahead, so no entitlement could have been recorded
    # yet, and the delivery cannot be shown to be owed to someone else.
    with pytest.raises(
        IndeterminateValuationError,
        match="before the entitlement it pays vests",
    ):
        _processor().apply_intrasession_settlements(state, (outcome,), _key(LATER_DAY))


def test_delivered_cash_for_a_component_never_owed_is_indeterminate() -> None:
    outcome = _delivered_dividend(suffix=1620, delivered_component="cash-9")
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (outcome,), _key(PAYABLE_DAY)
        )


def test_delivered_cash_seen_again_after_settlement_commits_nothing() -> None:
    outcome = _delivered_dividend(suffix=1630)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    settled = _processor().apply_intrasession_settlements(
        _payable_state(staged), (outcome,), _key(PAYABLE_DAY)
    )
    assert settled.cash_balance == Decimal("1050.0")

    # The same delivered report is read again once its claim is settled.
    again = _processor().apply_intrasession_settlements(
        settled, (outcome,), _key(PAYABLE_DAY)
    )

    assert again is settled


def test_unmatched_delivery_with_only_a_pending_claim_is_indeterminate() -> None:
    # The book sold after an entitlement, so it holds nothing but a claim on
    # the security. A delivery for an occurrence no evidence explains is still
    # exposure: it may be the cash that claim was owed, reported differently.
    state = _state(claims=(_manual_claim(payable=PAYABLE_DAY),), day=PAYABLE_DAY)
    delivered = _outcome(
        effects=(),
        delivery_groups=(
            _delivery(components=(_cash(amount="0.5"),), occurrence_id="occ-2"),
        ),
    )

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (delivered,), _key(PAYABLE_DAY)
        )


def test_delivered_amount_that_contradicts_the_claim_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=320)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.6"),)),),
    )
    with pytest.raises(
        IndeterminateValuationError,
        match="delivered cash contradicts the proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            _payable_state(staged), (delivered,), _key(PAYABLE_DAY)
        )


def test_delivery_before_the_payable_session_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=330)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    delivered = _outcome(
        effects=(),
        delivery_groups=(
            _delivery(components=(_cash(amount="0.5"),), settled_at=LATER_AT),
        ),
    )
    kernel = PortfolioAccountingKernel(staged, session_clock=CLOCK)
    kernel.advance_session(_key(LATER_DAY))
    with pytest.raises(
        IndeterminateValuationError,
        match="delivered before its proven payable session",
    ):
        _processor().apply_intrasession_settlements(
            kernel.state, (delivered,), _key(LATER_DAY)
        )


def test_future_delivery_commits_nothing_yet() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=340)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    unchanged = _processor().apply_intrasession_settlements(
        staged, (delivered,), _key()
    )
    assert unchanged is staged


def test_foreign_currency_dividend_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(amount="2", suffix=350, code="EUR")
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError, match="does not match the book currency"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_unknown_amount_basis_dividend_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(amount="2", suffix=360, amount_basis="unknown")
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError, match="source amount basis is unknown"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_dividend_without_a_source_ex_date_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="2",
        suffix=370,
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    state = _state(holdings=(_holding(quantity=100),))
    # The record date is present, but entitlement follows the ex-date rule,
    # and no record date may stand in for a missing ex date.
    with pytest.raises(IndeterminateValuationError, match="requires a source ex date"):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_dividend_needs_no_source_record_date() -> None:
    _, _, outcome = _dividend_case(
        amount="2",
        suffix=375,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    state = _state(holdings=(_holding(quantity=100),))

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("200")
    assert updated.pending_cash_claims[0].entitlement_session == EFFECT_DAY


def _t2_dividend(*, suffix: int) -> SecurityEconomicOutcomeV1:
    """A T+2-era dividend: ex on LATER_DAY, record one session later."""
    _, _, outcome = _dividend_case(
        amount="0.5",
        suffix=suffix,
        dates=(
            _date_fact("ex", LATER_AT),
            _date_fact("record", ENTITLED_AT),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    return outcome


def test_dividend_vests_on_its_ex_date_against_the_prior_close() -> None:
    outcome = _t2_dividend(suffix=1640)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    entitled, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    assert len(entitled.pending_cash_claims) == 1
    claim = entitled.pending_cash_claims[0]
    assert claim.entitlement_session == LATER_DAY
    assert claim.total_cash_expected == Decimal("50.0")


def test_dividend_is_not_owed_on_shares_bought_at_the_ex_date_open() -> None:
    outcome = _t2_dividend(suffix=1650)
    processor = _processor()

    # At the ex-date pre-open the prior close held nothing; only a buy is
    # staged for the open.
    at_ex, _ = processor.apply_pre_open_actions(
        _state(day=LATER_DAY), (_target(SEC_A, 100),), (outcome,), _key(LATER_DAY)
    )
    assert at_ex.pending_cash_claims == ()

    # On the record date the book holds the shares it bought at the ex-date
    # open. Under the record-date shortcut they would be credited.
    bought = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    at_record, _ = processor.apply_pre_open_actions(
        bought, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert at_record is bought
    assert at_record.pending_cash_claims == ()


def test_dividend_with_a_holiday_record_date_vests_on_its_ex_date() -> None:
    _, _, outcome = _dividend_case(
        amount="0.5",
        suffix=1660,
        dates=(
            _date_fact("ex", LATER_AT),
            _date_fact("record", "2020-06-13T00:00:00Z"),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    entitled, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    assert entitled.pending_cash_claims[0].total_cash_expected == Decimal("50.0")


def test_dividend_with_an_ex_date_off_the_clock_vests_at_the_next_pre_open() -> None:
    _, _, outcome = _dividend_case(
        amount="0.5",
        suffix=1670,
        dates=(_date_fact("ex", BETWEEN_AT), _date_fact("payable", PAYABLE_AT)),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    entitled, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    # Nothing trades between the prior session's close and this pre-open, so
    # the prior close's holdings are the ones the ex date pays.
    claim = entitled.pending_cash_claims[0]
    assert claim.entitlement_session == BETWEEN_DAY
    assert claim.total_cash_expected == Decimal("50.0")

    # Control: the next session does not vest it a second time.
    later = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    again, _ = _processor().apply_pre_open_actions(
        later, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert again is later


def test_due_bill_entitlement_off_the_clock_is_indeterminate() -> None:
    terms, _, outcome = _due_bill_terms()
    rule = _due_bill_rule(terms, entitlement=BETWEEN_DAY, redemption=BETWEEN_DAY)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    # The executable rule names a session the clock does not contain, and no
    # rule says which session such an entitlement moves to.
    with pytest.raises(
        IndeterminateValuationError,
        match="due-bill entitlement session 2020-06-05 is not a session",
    ):
        _processor(due_bill_rules=(rule,)).apply_pre_open_actions(
            state, (), (outcome,), _key(LATER_DAY)
        )


def test_dividend_without_a_source_payable_date_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="2",
        suffix=380,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("record", EFFECT_AT)),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError, match="requires a source payable date"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_dividend_without_a_holding_creates_no_claim() -> None:
    _, _, outcome = _dividend_case(amount="2", suffix=390)
    state = _state()
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert updated is state


def test_already_settled_dividend_claim_is_not_recreated() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=400)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    claim = staged.pending_cash_claims[0]
    replay = _state(
        holdings=(_holding(quantity=100),),
        cash="1050.0",
        settled=(claim.claim_id,),
    )
    again, _ = _processor().apply_pre_open_actions(replay, (), (outcome,), _key())
    assert again is replay
    assert again.pending_cash_claims == ()


def test_pending_dividend_claim_is_not_duplicated() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=410)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    again, _ = _processor().apply_pre_open_actions(staged, (), (outcome,), _key())
    assert len(again.pending_cash_claims) == 1
    assert again.cash_balance == Decimal("1000")


# --------------------------------------------------------------------------
# acquisitions and liquidation
# --------------------------------------------------------------------------


def test_cash_acquisition_removes_position_and_credits_entitlement() -> None:
    component = _cash(amount="12")
    terms = _terms(
        suffix=420,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(component,),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=421,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(component,),
        terms=terms,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.CASH_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="500")
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert updated.holdings == ()
    assert len(updated.pending_cash_claims) == 1
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("1200")
    assert updated.cash_balance == Decimal("500")
    assert updated.net_asset_value == Decimal("1700")


def test_cash_acquisition_with_continuing_claim_status_is_indeterminate() -> None:
    component = _cash(amount="12")
    terms = _terms(
        suffix=430,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(component,),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=431,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(component,),
        terms=terms,
        claim_status="continuing",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.CASH_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="acquisition must prove the predecessor claim ended",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_stock_acquisition_converts_holding_into_the_acquirer() -> None:
    component = _shares(
        numerator="3",
        denominator="2",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(
        suffix=440,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(component,),
    )
    effect = _effect(
        suffix=441,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(component,),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.STOCK_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert len(updated.holdings) == 1
    assert updated.holdings[0].security_id == SEC_ACQ
    assert updated.holdings[0].quantity == 150
    assert updated.holdings[0].cost_basis == Decimal("900")


def test_mixed_acquisition_credits_cash_and_acquirer_shares() -> None:
    share = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    cash = _cash(amount="3", component_id="cash-1")
    terms = _terms(
        suffix=450,
        action_kind=ActionKind.MIXED_ACQUISITION,
        components=(share, cash),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=451,
        action_kind=ActionKind.MIXED_ACQUISITION,
        components=(share, cash),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.MIXED_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert len(updated.holdings) == 1
    assert updated.holdings[0].security_id == SEC_ACQ
    assert updated.holdings[0].quantity == 50
    assert len(updated.pending_cash_claims) == 1
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("300")


def test_mixed_acquisition_without_cash_terms_is_indeterminate() -> None:
    share = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(
        suffix=460,
        action_kind=ActionKind.MIXED_ACQUISITION,
        components=(share,),
    )
    effect = _effect(
        suffix=461,
        action_kind=ActionKind.MIXED_ACQUISITION,
        components=(share,),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.MIXED_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="mixed acquisition requires proven cash terms",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_liquidation_credits_known_proceeds() -> None:
    component = _cash(amount="7")
    terms = _terms(
        suffix=470,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=471,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        terms=terms,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.LIQUIDATION,)
    )
    state = _state(holdings=(_holding(quantity=10, basis="100"),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert updated.holdings == ()
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("70")


def test_liquidation_with_missing_terms_is_indeterminate() -> None:
    terms = _terms(
        suffix=480,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=481,
        action_kind=ActionKind.LIQUIDATION,
        components=(),
        terms=terms,
        claim_status="extinguished",
        consideration_status="unknown",
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.LIQUIDATION,)
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="occurred effect does not prove its consideration",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


# --------------------------------------------------------------------------
# liquidation claim status and disposal PnL
# --------------------------------------------------------------------------


def _liquidation_case(
    *,
    suffix: int,
    claim_status: str,
    amount: str = "7",
    ex_at: str = EFFECT_AT,
    effective_at: str = EFFECT_AT,
    dates: tuple[EconomicDateFactV1, ...] | None = None,
) -> SecurityEconomicOutcomeV1:
    return _share_action_case(
        suffix=suffix,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount=amount),),
        claim_status=claim_status,
        dates=(
            (_date_fact("ex", ex_at), _date_fact("payable", PAYABLE_AT))
            if dates is None
            else dates
        ),
        effective_at=effective_at,
    )


def test_a_liquidation_that_extinguishes_the_claim_relieves_its_basis() -> None:
    outcome = _liquidation_case(suffix=1900, claim_status="extinguished")
    state = _state(holdings=(_holding(quantity=10, basis="100"),), cash="500")

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # Ten shares of basis 100 leave for 70 owed, so 30 is realized as a loss
    # at the disposal, exactly as a sale at 7.00 would realize it.
    assert updated.holdings == ()
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("70")
    assert updated.realized_gross_pnl == Decimal("-30")
    assert updated.realized_net_pnl == Decimal("-30")
    # The book's value moved from basis to the claim, not out of existence.
    assert updated.cash_balance + updated.pending_claims_value == Decimal("570")
    assert updated.net_asset_value == Decimal("570")


def test_a_liquidation_that_extinguishes_the_claim_zeroes_its_target() -> None:
    outcome = _liquidation_case(suffix=1910, claim_status="extinguished")
    state = _state(holdings=(_holding(quantity=10, basis="100"),))

    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 10),), (outcome,), _key()
    )

    # A kept target would re-buy the extinguished security at the open.
    assert _quantities(translated) == {SEC_A: 0}


def test_a_liquidation_zeroes_a_staged_buy_without_any_holding() -> None:
    outcome = _liquidation_case(suffix=1920, claim_status="extinguished")

    updated, translated = _processor().apply_pre_open_actions(
        _state(), (_target(SEC_A, 10),), (outcome,), _key()
    )

    assert updated.pending_cash_claims == ()
    assert updated.realized_gross_pnl == ZERO
    assert _quantities(translated) == {SEC_A: 0}


def test_a_liquidation_on_a_continuing_claim_is_a_cash_distribution() -> None:
    outcome = _liquidation_case(suffix=1930, claim_status="continuing")
    state = _state(holdings=(_holding(quantity=10, basis="100"),), cash="500")
    targets = (_target(SEC_A, 10),)

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    # A partial liquidating distribution pays cash on shares that continue:
    # every share, its basis, and the staged hold all survive.
    assert _quantities(updated.holdings) == {SEC_A: 10}
    assert updated.holdings[0].cost_basis == Decimal("100")
    assert _quantities(translated) == {SEC_A: 10}
    claim = updated.pending_cash_claims[0]
    assert claim.action_kind is ActionKind.LIQUIDATION
    assert claim.total_cash_expected == Decimal("70")
    assert updated.realized_gross_pnl == ZERO


def test_a_continuing_liquidation_vests_on_its_ex_date_like_a_dividend() -> None:
    outcome = _liquidation_case(
        suffix=1940, claim_status="continuing", ex_at=ENTITLED_AT
    )
    # Bought at the ex-date open: held at the entitlement session's pre-open
    # only through a staged buy, so the prior close held nothing.
    at_ex, _ = _processor().apply_pre_open_actions(
        _state(day=ENTITLED_DAY),
        (_target(SEC_A, 10),),
        (outcome,),
        _key(ENTITLED_DAY),
    )
    assert at_ex.pending_cash_claims == ()

    # Control: held at the prior close, the same distribution is owed.
    held = _state(holdings=(_holding(quantity=10),), day=ENTITLED_DAY)
    entitled, _ = _processor().apply_pre_open_actions(
        held, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert entitled.pending_cash_claims[0].entitlement_session == ENTITLED_DAY


def test_a_continuing_liquidation_without_an_ex_date_is_indeterminate() -> None:
    outcome = _liquidation_case(
        suffix=1950,
        claim_status="continuing",
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    state = _state(holdings=(_holding(quantity=10),))

    with pytest.raises(IndeterminateValuationError, match="requires a source ex date"):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


@pytest.mark.parametrize("claim_status", ["unknown", "converted"])
def test_a_liquidation_without_a_known_claim_outcome_is_indeterminate(
    claim_status: str,
) -> None:
    outcome = _liquidation_case(suffix=1960, claim_status=claim_status)
    state = _state(holdings=(_holding(quantity=10, basis="100"),))

    # Neither an ended claim nor a continuing one is proven, so whether any
    # share survives is unknown, and zero is never assumed (spec 12.6).
    with pytest.raises(
        IndeterminateValuationError,
        match=f"liquidation must prove the claim extinguished or continuing, "
        f"got claim status {claim_status}",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # Control: a staged buy alone is exposure too.
    with pytest.raises(IndeterminateValuationError, match="liquidation must prove"):
        _processor().apply_pre_open_actions(
            _state(), (_target(SEC_A, 1),), (outcome,), _key()
        )


def test_an_unproven_liquidation_behind_only_a_zero_target_commits_nothing() -> None:
    outcome = _liquidation_case(suffix=1970, claim_status="unknown")
    state = _state()

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key()
    )

    assert updated is state
    assert _quantities(translated) == {SEC_A: 0}


def test_a_cash_acquisition_relieves_its_basis_into_realized_pnl() -> None:
    component = _cash(amount="12")
    outcome = _share_action_case(
        suffix=1980,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(component,),
        claim_status="extinguished",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="500")

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # 100 shares of basis 900 leave for 1200 owed: 300 is realized.
    assert updated.realized_gross_pnl == Decimal("300")
    assert updated.realized_net_pnl == Decimal("300")
    # Realized-PnL identity: cash, claims and remaining basis equal the
    # opening cash and basis plus everything realized.
    remaining = sum((item.cost_basis for item in updated.holdings), ZERO)
    assert updated.cash_balance + updated.pending_claims_value + remaining == (
        Decimal("500") + Decimal("900") + updated.realized_net_pnl
    )


def test_a_continuing_liquidation_delivered_before_its_ex_date_is_indeterminate() -> (
    None
):
    terms = _terms(
        suffix=1995,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        dates=(_date_fact("ex", PAYABLE_AT), _date_fact("payable", PAYABLE_AT)),
    )
    effect = _effect(
        suffix=1996,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        terms=terms,
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(
            _delivery(components=(_cash(amount="7"),), settled_at=LATER_AT),
        ),
        action_kinds=(ActionKind.LIQUIDATION,),
    )
    state = _state(holdings=(_holding(quantity=10),), day=LATER_DAY)

    # A continuing liquidation vests on its ex date, like any distribution,
    # not on the date its effect was reported, so this cash came early.
    with pytest.raises(
        IndeterminateValuationError,
        match="before the entitlement it pays vests",
    ):
        _processor().apply_intrasession_settlements(state, (outcome,), _key(LATER_DAY))


def test_a_continuing_liquidation_is_counted_after_same_session_splits() -> None:
    split_component = _shares(
        numerator="2", denominator="1", component_id="split-shares"
    )
    for basis, expected in (
        ("predecessor_pre_action", Decimal("70")),
        ("predecessor_post_action", Decimal("140")),
    ):
        cash = CashComponentV1(
            kind="cash",
            component_id="cash-1",
            amount="7",
            currency_namespace=BOOK_NAMESPACE,
            currency_code=BOOK_CODE,
            unit_basis=EconomicUnitBasisV1(
                security_id=SEC_A,
                denominator=PositiveRatioV1(numerator="1", denominator="1"),
                share_basis=basis,  # type: ignore[arg-type]
            ),
            amount_basis="gross",
            applicability="ordinary_passive_holder",
            conditions=(),
        )
        split_terms = _terms(
            suffix=2002,
            action_kind=ActionKind.FORWARD_SPLIT,
            components=(split_component,),
        )
        split_effect = _effect(
            suffix=2003,
            action_kind=ActionKind.FORWARD_SPLIT,
            components=(split_component,),
            terms=split_terms,
            occurrence_id="occ-split",
        )
        liquidation_terms = _terms(
            suffix=2102,
            action_kind=ActionKind.LIQUIDATION,
            components=(cash,),
            dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
        )
        liquidation_effect = _effect(
            suffix=2103,
            action_kind=ActionKind.LIQUIDATION,
            components=(cash,),
            terms=liquidation_terms,
            occurrence_id="occ-liquidation",
        )
        outcome = _outcome(
            terms=(split_terms, liquidation_terms),
            effects=(split_effect, liquidation_effect),
            action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.LIQUIDATION),
        )
        # The premise that makes the ordering load-bearing.
        assert content_hash(liquidation_effect) < content_hash(split_effect)
        state = _state(holdings=(_holding(quantity=10),))

        updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

        # The liquidation record sorts before the split by hash, so only the
        # distribution ordering counts it after the split on the same
        # session, and a per-post-split-share amount is owed on all twenty.
        assert _quantities(updated.holdings) == {SEC_A: 20}
        assert updated.pending_cash_claims[0].total_cash_expected == expected


def test_a_disposal_realizes_the_proceeds_of_every_cash_component() -> None:
    outcome = _share_action_case(
        suffix=2010,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(
            _cash(amount="10", component_id="cash-1"),
            _cash(amount="2", component_id="cash-2"),
        ),
        claim_status="extinguished",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),))

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # 100 shares owed 10.00 and 2.00 each: 1200.00 of proceeds on 900 basis.
    assert updated.pending_claims_value == Decimal("1200")
    assert updated.realized_gross_pnl == Decimal("300")


def test_realized_disposal_pnl_accumulates_on_the_prior_realized_pnl() -> None:
    outcome = _liquidation_case(suffix=1990, claim_status="extinguished")
    prior = _state(holdings=(_holding(quantity=10, basis="100"),))
    state = PortfolioStateV1.model_validate(
        dict(prior)
        | {"realized_gross_pnl": Decimal("12"), "realized_net_pnl": Decimal("10")}
    )

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert updated.realized_gross_pnl == Decimal("-18")
    assert updated.realized_net_pnl == Decimal("-20")


def test_unsupported_action_kind_on_a_held_position_is_indeterminate() -> None:
    share = _shares(
        numerator="1",
        denominator="1",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(suffix=490, action_kind=ActionKind.CONVERSION, components=(share,))
    effect = _effect(
        suffix=491,
        action_kind=ActionKind.CONVERSION,
        components=(share,),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.CONVERSION,)
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="has no proven M2 accounting rule",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_unsupported_action_kind_without_exposure_commits_nothing() -> None:
    share = _shares(
        numerator="1",
        denominator="1",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(suffix=500, action_kind=ActionKind.CONVERSION, components=(share,))
    effect = _effect(
        suffix=501,
        action_kind=ActionKind.CONVERSION,
        components=(share,),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.CONVERSION,)
    )
    state = _state()
    updated, targets = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key()
    )
    assert updated is state
    assert targets == ()


# --------------------------------------------------------------------------
# staged target translation through every share action
# --------------------------------------------------------------------------


def _share_action_case(
    *,
    suffix: int,
    action_kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    claim_status: str = "continuing",
    dates: tuple[EconomicDateFactV1, ...] = (),
    effective_at: str = EFFECT_AT,
) -> SecurityEconomicOutcomeV1:
    terms = _terms(
        suffix=suffix, action_kind=action_kind, components=components, dates=dates
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=action_kind,
        components=components,
        terms=terms,
        claim_status=claim_status,
        effective_at=effective_at,
    )
    return _outcome(terms=(terms,), effects=(effect,), action_kinds=(action_kind,))


def _stock_dividend_case(
    *,
    suffix: int,
    numerator: str = "1",
    denominator: str = "10",
    treatment: FractionTreatmentV1 | None = None,
) -> SecurityEconomicOutcomeV1:
    component = _shares(
        numerator=numerator,
        denominator=denominator,
        meaning="additional_per_predecessor",
        treatment=_treatment("round_down") if treatment is None else treatment,
    )
    return _share_action_case(
        suffix=suffix, action_kind=ActionKind.STOCK_DIVIDEND, components=(component,)
    )


def _spinoff_case(*, suffix: int) -> SecurityEconomicOutcomeV1:
    component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_CHILD,
        meaning="additional_per_predecessor",
        treatment=_treatment("round_down"),
    )
    return _share_action_case(
        suffix=suffix, action_kind=ActionKind.SPINOFF, components=(component,)
    )


def _share_acquisition_case(
    *,
    suffix: int,
    numerator: str = "3",
    denominator: str = "2",
    treatment: FractionTreatmentV1 | None = None,
    action_kind: ActionKind = ActionKind.STOCK_ACQUISITION,
) -> SecurityEconomicOutcomeV1:
    share = _shares(
        numerator=numerator,
        denominator=denominator,
        recipient=SEC_ACQ,
        treatment=_treatment("round_down") if treatment is None else treatment,
    )
    mixed = action_kind == ActionKind.MIXED_ACQUISITION
    return _share_action_case(
        suffix=suffix,
        action_kind=action_kind,
        components=(share, _cash(amount="3")) if mixed else (share,),
        claim_status="converted",
        dates=(_date_fact("payable", PAYABLE_AT),) if mixed else (),
    )


def _cash_acquisition_case(
    *, suffix: int, claim_status: str = "extinguished"
) -> SecurityEconomicOutcomeV1:
    return _share_action_case(
        suffix=suffix,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12"),),
        claim_status=claim_status,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )


def _target(security_id: UUID, quantity: int) -> SecurityTargetPositionV1:
    return SecurityTargetPositionV1(security_id=security_id, target_quantity=quantity)


def _quantities(
    items: tuple[SecurityTargetPositionV1, ...] | tuple[SecurityHoldingV1, ...],
) -> dict[UUID, int]:
    return {
        item.security_id: (
            item.target_quantity
            if isinstance(item, SecurityTargetPositionV1)
            else item.quantity
        )
        for item in items
    }


def test_stock_dividend_scales_a_staged_hold_target_with_its_holding() -> None:
    outcome = _stock_dividend_case(suffix=1100)
    state = _state(holdings=(_holding(quantity=100, basis="1000"),))
    targets = (_target(SEC_A, 100), _target(SEC_OTHER, 7))

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    # A hold staged before the dividend is still a hold after it, so the
    # open trades nothing instead of selling the ten new shares.
    assert _quantities(updated.holdings) == {SEC_A: 110}
    assert _quantities(translated) == {SEC_A: 110, SEC_OTHER: 7}


def test_stock_dividend_scales_a_trading_target_by_one_plus_its_ratio() -> None:
    outcome = _stock_dividend_case(suffix=1110)
    state = _state(holdings=(_holding(quantity=100),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 50),), (outcome,), _key()
    )

    # Selling 50 pre-dividend shares is selling 55 post-dividend shares.
    assert _quantities(updated.holdings) == {SEC_A: 110}
    assert _quantities(translated) == {SEC_A: 55}


def test_stock_dividend_translates_exactly_like_the_equivalent_split() -> None:
    dividend = _stock_dividend_case(suffix=1120, numerator="3", denominator="1")
    _, _, split = _split_case(
        numerator="4",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=1130,
    )
    state = _state(holdings=(_holding(quantity=10, basis="1000"),))
    targets = (_target(SEC_A, 10),)

    as_dividend = _processor().apply_pre_open_actions(
        state, targets, (dividend,), _key()
    )
    as_split = _processor().apply_pre_open_actions(state, targets, (split,), _key())

    # Three additional shares per share and four resulting shares per share
    # are one economic event, so they must leave one book and one target.
    assert as_dividend == as_split
    assert _quantities(as_dividend[1]) == {SEC_A: 40}


def test_stock_dividend_scales_a_staged_target_without_any_holding() -> None:
    outcome = _stock_dividend_case(suffix=1140)

    updated, translated = _processor().apply_pre_open_actions(
        _state(), (_target(SEC_A, 20),), (outcome,), _key()
    )

    assert updated.holdings == ()
    assert _quantities(translated) == {SEC_A: 22}


def test_stock_dividend_resolves_a_fractional_hold_like_its_holding() -> None:
    outcome = _stock_dividend_case(suffix=1150)
    state = _state(holdings=(_holding(quantity=15),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 15),), (outcome,), _key()
    )

    # 16.5 resolves to 16 under the source round-down treatment, for the
    # holding and the target alike, so the hold survives the fraction.
    assert _quantities(updated.holdings) == {SEC_A: 16}
    assert _quantities(translated) == {SEC_A: 16}


def test_stock_dividend_unresolvable_fractional_target_is_indeterminate() -> None:
    outcome = _stock_dividend_case(suffix=1160, treatment=_treatment("round_nearest"))
    state = _state(holdings=(_holding(quantity=10),))

    # Control: an integral translation needs no tie-breaking rule.
    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 10),), (outcome,), _key()
    )
    assert _quantities(translated) == {SEC_A: 11}

    # The holding translates to exactly 11, but the target to 16.5.
    with pytest.raises(
        IndeterminateValuationError,
        match="interpreted source tie-breaking rule",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 15),), (outcome,), _key()
        )


def test_spinoff_credits_the_child_target_with_the_child_shares_received() -> None:
    outcome = _spinoff_case(suffix=1200)
    state = _state(holdings=(_holding(quantity=100),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_A: 100, SEC_CHILD: 50}
    assert _quantities(translated) == {SEC_A: 100, SEC_CHILD: 50}


def test_spinoff_leaves_the_parent_trade_and_holds_the_child() -> None:
    outcome = _spinoff_case(suffix=1210)
    state = _state(holdings=(_holding(quantity=100),))

    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key()
    )

    # Parent shares are unchanged, so the staged parent sale is unchanged,
    # and the child the book was handed is held rather than traded.
    assert _quantities(translated) == {SEC_A: 0, SEC_CHILD: 50}


def test_spinoff_adds_received_shares_to_an_existing_child_target() -> None:
    outcome = _spinoff_case(suffix=1220)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_CHILD, quantity=10, basis="40"))
    )
    targets = (_target(SEC_A, 100), _target(SEC_CHILD, 4))

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    # The staged child sale of six survives the 50 shares received.
    assert _quantities(updated.holdings) == {SEC_A: 100, SEC_CHILD: 60}
    assert _quantities(translated) == {SEC_A: 100, SEC_CHILD: 54}


def test_spinoff_without_a_staged_parent_target_stages_no_child_target() -> None:
    outcome = _spinoff_case(suffix=1230)
    state = _state(holdings=(_holding(quantity=100),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key()
    )

    # No decision is staged, so no target may be invented for the child.
    assert _quantities(updated.holdings) == {SEC_A: 100, SEC_CHILD: 50}
    assert translated == ()


def test_spinoff_child_held_without_a_staged_target_is_indeterminate() -> None:
    outcome = _spinoff_case(suffix=1240)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_CHILD, quantity=10, basis="40"))
    )

    with pytest.raises(
        IndeterminateValuationError,
        match="held without a staged target of its own",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 100),), (outcome,), _key()
        )


def test_cash_acquisition_extinguishes_the_staged_target() -> None:
    outcome = _cash_acquisition_case(suffix=1300)
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="500")

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )

    # A kept target would re-buy the extinguished security at the open.
    assert updated.holdings == ()
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("1200")
    assert _quantities(translated) == {SEC_A: 0}


def test_cash_acquisition_extinguishes_a_target_without_any_holding() -> None:
    outcome = _cash_acquisition_case(suffix=1310)

    updated, translated = _processor().apply_pre_open_actions(
        _state(), (_target(SEC_A, 10),), (outcome,), _key()
    )

    assert updated.pending_cash_claims == ()
    assert _quantities(translated) == {SEC_A: 0}


def test_cash_acquisition_target_without_an_ended_claim_is_indeterminate() -> None:
    outcome = _cash_acquisition_case(suffix=1320, claim_status="continuing")

    with pytest.raises(
        IndeterminateValuationError,
        match="acquisition must prove the predecessor claim ended",
    ):
        _processor().apply_pre_open_actions(
            _state(), (_target(SEC_A, 10),), (outcome,), _key()
        )


def test_stock_acquisition_maps_the_staged_target_to_the_acquirer() -> None:
    outcome = _share_acquisition_case(suffix=1400)
    state = _state(holdings=(_holding(quantity=100),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_ACQ: 150}
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 150}


def test_stock_acquisition_maps_a_trading_target_at_the_exact_ratio() -> None:
    outcome = _share_acquisition_case(suffix=1410)
    state = _state(holdings=(_holding(quantity=100),))

    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 40),), (outcome,), _key()
    )

    # Selling 60 of 100 predecessor shares is selling 90 of 150 acquirer
    # shares, never holding the whole conversion.
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 60}


def test_stock_acquisition_maps_a_zero_target_onto_the_acquirer() -> None:
    outcome = _share_acquisition_case(suffix=1420)
    state = _state(holdings=(_holding(quantity=100),))

    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key()
    )

    # The staged exit survives the conversion, and the acquirer the book now
    # holds is covered by a target rather than silently left uncovered.
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 0}


def test_stock_acquisition_adds_the_mapped_target_to_the_acquirers_own() -> None:
    outcome = _share_acquisition_case(suffix=1430)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_ACQ, quantity=10, basis="80"))
    )
    targets = (_target(SEC_A, 100), _target(SEC_ACQ, 10))

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_ACQ: 160}
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 160}


def test_stock_acquisition_staged_entry_without_a_holding_is_indeterminate() -> None:
    outcome = _share_acquisition_case(suffix=1440)

    # The staged entry of ten predecessor shares maps to 15 acquirer shares
    # while the book receives none, so honouring it would buy an acquirer no
    # admitted decision named.
    with pytest.raises(
        IndeterminateValuationError,
        match="would buy the acquirer",
    ):
        _processor().apply_pre_open_actions(
            _state(), (_target(SEC_A, 10),), (outcome,), _key()
        )


def test_stock_acquisition_staged_increase_is_indeterminate() -> None:
    outcome = _share_acquisition_case(suffix=1480)
    state = _state(holdings=(_holding(quantity=100),))

    # Control: a hold maps to exactly the 150 shares received.
    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 150}

    # 120 predecessor shares map to 180, more than the 150 received.
    with pytest.raises(
        IndeterminateValuationError,
        match="would buy the acquirer",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 120),), (outcome,), _key()
        )


def test_mixed_acquisition_staged_increase_is_indeterminate() -> None:
    outcome = _share_acquisition_case(
        suffix=1490,
        numerator="1",
        denominator="2",
        action_kind=ActionKind.MIXED_ACQUISITION,
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),))

    # 102 predecessor shares map to 51, more than the 50 received.
    with pytest.raises(
        IndeterminateValuationError,
        match="would buy the acquirer",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 102),), (outcome,), _key()
        )


def test_share_acquisition_increase_into_a_held_acquirer_is_indeterminate() -> None:
    outcome = _share_acquisition_case(suffix=1495)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_ACQ, quantity=10, basis="80"))
    )
    targets = (_target(SEC_A, 102), _target(SEC_ACQ, 10))

    # 102 predecessor shares map to 153, more than the 150 received. The ten
    # acquirer shares already held do not license the extra three: the bound
    # is the conversion, not whatever the book happens to hold.
    with pytest.raises(
        IndeterminateValuationError,
        match="would buy the acquirer",
    ):
        _processor().apply_pre_open_actions(state, targets, (outcome,), _key())


def test_share_acquisition_target_without_an_ended_claim_is_indeterminate() -> None:
    share = _shares(
        numerator="3",
        denominator="2",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    outcome = _share_action_case(
        suffix=1500,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(share,),
        claim_status="continuing",
    )

    # A staged target alone is exposure, so the claim must be proven ended
    # before the target is mapped anywhere.
    with pytest.raises(
        IndeterminateValuationError,
        match="acquisition must prove the predecessor claim ended",
    ):
        _processor().apply_pre_open_actions(
            _state(), (_target(SEC_A, 10),), (outcome,), _key()
        )


def test_share_acquisition_zero_target_without_a_holding_has_no_exposure() -> None:
    share = _shares(
        numerator="3",
        denominator="2",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    outcome = _share_action_case(
        suffix=1510,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(share,),
        claim_status="continuing",
    )
    state = _state()
    targets = (_target(SEC_A, 0),)

    # Nothing held and nothing to buy: an unproven claim status on a security
    # the book never touches must not halt the run.
    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    assert updated is state
    assert translated == targets


def test_cash_acquisition_zero_target_without_a_holding_has_no_exposure() -> None:
    outcome = _cash_acquisition_case(suffix=1520, claim_status="continuing")
    state = _state()
    targets = (_target(SEC_A, 0),)

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    assert updated is state
    assert translated == targets


def test_share_acquisition_zero_target_into_an_untargeted_holding_fails() -> None:
    outcome = _share_acquisition_case(suffix=1530)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_ACQ, quantity=10, basis="80"))
    )

    # A staged exit maps to zero acquirer shares, but reading the untargeted
    # acquirer holding as a zero target would also sell those ten shares.
    with pytest.raises(
        IndeterminateValuationError,
        match="held without a staged target of its own",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 0),), (outcome,), _key()
        )


@pytest.mark.parametrize(("tie_break", "expected"), [("half_up", 8), ("half_down", 7)])
def test_stock_dividend_target_follows_the_source_tie_breaking_rule(
    tie_break: str, expected: int
) -> None:
    outcome = _stock_dividend_case(
        suffix=1540,
        numerator="1",
        denominator="2",
        treatment=_treatment("round_nearest"),
    )
    rule = _tie_rule(effect=outcome.effect_records[0], tie_break=tie_break)
    state = _state(holdings=(_holding(quantity=10),))

    # The holding translates to exactly 15, the target of 5 to a tie at 7.5.
    processor = _processor(tie_breaking_rules=(rule,))
    updated, translated = processor.apply_pre_open_actions(
        state, (_target(SEC_A, 5),), (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_A: 15}
    assert _quantities(translated) == {SEC_A: expected}


@pytest.mark.parametrize(("tie_break", "expected"), [("half_up", 8), ("half_down", 7)])
def test_share_acquisition_target_follows_the_source_tie_breaking_rule(
    tie_break: str, expected: int
) -> None:
    outcome = _share_acquisition_case(
        suffix=1550, treatment=_treatment("round_nearest")
    )
    rule = _tie_rule(effect=outcome.effect_records[0], tie_break=tie_break)
    state = _state(holdings=(_holding(quantity=10),))

    # The holding converts to exactly 15, the target of 5 to a tie at 7.5.
    processor = _processor(tie_breaking_rules=(rule,))
    updated, translated = processor.apply_pre_open_actions(
        state, (_target(SEC_A, 5),), (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_ACQ: 15}
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: expected}


def test_spinoff_parent_held_without_a_staged_target_stages_no_child() -> None:
    outcome = _spinoff_case(suffix=1560)
    state = _state(holdings=(_holding(quantity=100),))
    targets = (_target(SEC_OTHER, 7),)

    # Another security's target does not stage a decision for the parent, so
    # it cannot license a child target either.
    _, translated = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )

    assert _quantities(translated) == {SEC_OTHER: 7}


def test_stock_acquisition_unresolvable_fractional_target_is_indeterminate() -> None:
    outcome = _share_acquisition_case(
        suffix=1450, treatment=_treatment("round_nearest")
    )
    state = _state(holdings=(_holding(quantity=100),))

    # Control: an integral translation needs no tie-breaking rule.
    _, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 150}

    # The holding converts to exactly 150, but the target to 7.5.
    with pytest.raises(
        IndeterminateValuationError,
        match="interpreted source tie-breaking rule",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 5),), (outcome,), _key()
        )


def test_share_acquisition_into_an_untargeted_holding_is_indeterminate() -> None:
    outcome = _share_acquisition_case(suffix=1460)
    state = _state(
        holdings=(_holding(quantity=100), _holding(SEC_ACQ, quantity=10, basis="80"))
    )

    with pytest.raises(
        IndeterminateValuationError,
        match="held without a staged target of its own",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 100),), (outcome,), _key()
        )


def test_mixed_acquisition_maps_the_staged_target_to_the_acquirer() -> None:
    outcome = _share_acquisition_case(
        suffix=1470,
        numerator="1",
        denominator="2",
        action_kind=ActionKind.MIXED_ACQUISITION,
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),))

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key()
    )

    assert _quantities(updated.holdings) == {SEC_ACQ: 50}
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("300")
    assert _quantities(translated) == {SEC_A: 0, SEC_ACQ: 50}


# --------------------------------------------------------------------------
# occurrence gating and zero-mutation rules
# --------------------------------------------------------------------------


def test_terms_without_an_occurred_effect_commit_no_mutation() -> None:
    component = _shares(
        numerator="2", denominator="1", treatment=_treatment("round_down")
    )
    terms = _terms(
        suffix=510, action_kind=ActionKind.FORWARD_SPLIT, components=(component,)
    )
    outcome = _outcome(
        terms=(terms,), effects=(), action_kinds=(ActionKind.FORWARD_SPLIT,)
    )
    state = _state(holdings=(_holding(quantity=100),))
    targets = (SecurityTargetPositionV1(security_id=SEC_A, target_quantity=50),)
    updated, scaled = _processor().apply_pre_open_actions(
        state, targets, (outcome,), _key()
    )
    assert updated is state
    assert scaled == targets


def test_upcoming_effect_commits_no_mutation() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=520,
    )
    upcoming = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        statuses=("upcoming",),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (upcoming,), _key())
    assert updated is state


def test_indeterminate_effect_projection_fails_closed() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=530,
    )
    unclear = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        statuses=("indeterminate",),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="effect projection effectiveness is indeterminate",
    ):
        _processor().apply_pre_open_actions(state, (), (unclear,), _key())


def test_unsupported_outcome_resolution_fails_closed_when_exposed() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=540,
    )
    unsupported = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        support_status="indeterminate",
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="economic outcome resolution is not supported evidence",
    ):
        _processor().apply_pre_open_actions(state, (), (unsupported,), _key())


def test_split_effective_on_another_session_commits_no_mutation() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=550,
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)
    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )
    assert updated is state
    assert updated.holdings[0].quantity == 100


# --------------------------------------------------------------------------
# effects dated off the clock
# --------------------------------------------------------------------------


def _off_clock_action(kind: ActionKind, suffix: int) -> SecurityEconomicOutcomeV1:
    """One share action on SEC_A, effective on a date the clock skips."""
    payable = (_date_fact("payable", PAYABLE_AT),)
    cases: dict[
        ActionKind,
        tuple[tuple[EconomicComponentV1, ...], str, tuple[EconomicDateFactV1, ...]],
    ] = {
        ActionKind.FORWARD_SPLIT: (
            (_shares(numerator="2", denominator="1"),),
            "continuing",
            (),
        ),
        ActionKind.STOCK_DIVIDEND: (
            (
                _shares(
                    numerator="1",
                    denominator="10",
                    meaning="additional_per_predecessor",
                ),
            ),
            "continuing",
            (),
        ),
        ActionKind.SPINOFF: (
            (
                _shares(
                    numerator="1",
                    denominator="2",
                    recipient=SEC_CHILD,
                    meaning="additional_per_predecessor",
                ),
            ),
            "continuing",
            (),
        ),
        ActionKind.CASH_ACQUISITION: ((_cash(amount="12"),), "extinguished", payable),
        ActionKind.STOCK_ACQUISITION: (
            (_shares(numerator="3", denominator="2", recipient=SEC_ACQ),),
            "converted",
            (),
        ),
        ActionKind.LIQUIDATION: ((_cash(amount="7"),), "extinguished", payable),
    }
    components, claim_status, dates = cases[kind]
    return _share_action_case(
        suffix=suffix,
        action_kind=kind,
        components=components,
        claim_status=claim_status,
        dates=dates,
        effective_at=BETWEEN_AT,
    )


@pytest.mark.parametrize(
    ("kind", "suffix", "held_after", "owed"),
    [
        (ActionKind.FORWARD_SPLIT, 1700, {SEC_A: 200}, None),
        (ActionKind.STOCK_DIVIDEND, 1710, {SEC_A: 110}, None),
        (ActionKind.SPINOFF, 1720, {SEC_A: 100, SEC_CHILD: 50}, None),
        (ActionKind.CASH_ACQUISITION, 1730, {}, Decimal("1200")),
        (ActionKind.STOCK_ACQUISITION, 1740, {SEC_ACQ: 150}, None),
        (ActionKind.LIQUIDATION, 1750, {}, Decimal("700")),
    ],
)
def test_a_share_action_dated_off_the_clock_applies_at_the_next_pre_open(
    kind: ActionKind,
    suffix: int,
    held_after: dict[UUID, int],
    owed: Decimal | None,
) -> None:
    outcome = _off_clock_action(kind, suffix)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    # BETWEEN_DAY falls after EFFECT_DAY and before LATER_DAY, so LATER_DAY is
    # the first pre-open that can see the action.
    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )
    assert _quantities(updated.holdings) == held_after
    # A disposal off the clock still owes its proceeds, vested on the date the
    # claim actually ended rather than on the session that recognized it.
    if owed is None:
        assert updated.pending_cash_claims == ()
    else:
        (claim,) = updated.pending_cash_claims
        assert claim.total_cash_expected == owed
        assert claim.entitlement_session == BETWEEN_DAY

    # Control: the following session owns only the dates after LATER_DAY, so
    # the same action is never applied a second time.
    later = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    again, _ = _processor().apply_pre_open_actions(
        later, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert again is later


def test_a_split_off_the_clock_translates_the_staged_target_too() -> None:
    outcome = _off_clock_action(ActionKind.FORWARD_SPLIT, 1760)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 100),), (outcome,), _key(LATER_DAY)
    )

    assert _quantities(updated.holdings) == {SEC_A: 200}
    assert _quantities(translated) == {SEC_A: 200}


def test_an_effect_dated_after_the_session_waits_for_its_own_pre_open() -> None:
    future = _share_action_case(
        suffix=1770,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(_shares(numerator="2", denominator="1"),),
        effective_at=ENTITLED_AT,
    )
    early = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    unchanged, _ = _processor().apply_pre_open_actions(
        early, (), (future,), _key(LATER_DAY)
    )
    assert unchanged is early

    # Control: its own session applies it.
    due = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    applied, _ = _processor().apply_pre_open_actions(
        due, (), (future,), _key(ENTITLED_DAY)
    )
    assert _quantities(applied.holdings) == {SEC_A: 200}


def test_an_effect_dated_before_the_clock_is_the_opening_books_history() -> None:
    component = _shares(numerator="2", denominator="1")
    outcome = _share_action_case(
        suffix=1780,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        effective_at=BEFORE_CLOCK_AT,
    )
    state = _state(holdings=(_holding(quantity=100),))

    # The first session has no prior session inside the evaluation, so it
    # owns only its own date. The opening book already reflects anything
    # earlier, and re-applying history would split it again.
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert updated is state


def test_a_pre_open_pass_for_a_session_off_the_clock_is_refused() -> None:
    state = _state(day=BETWEEN_DAY)

    with pytest.raises(ValueError, match="is not a session of the processor's clock"):
        _processor().apply_pre_open_actions(state, (), (), _key(BETWEEN_DAY))


def test_unsupported_evidence_behind_only_a_zero_target_commits_nothing() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=1790,
    )
    unsupported = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        support_status="indeterminate",
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state()

    # An explicit zero target on an unheld security trades nothing, so the
    # book is not exposed to evidence it cannot trust.
    updated, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (unsupported,), _key()
    )
    assert updated is state
    assert _quantities(translated) == {SEC_A: 0}

    # Control: a staged buy is exposure.
    with pytest.raises(
        IndeterminateValuationError,
        match="economic outcome resolution is not supported evidence",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 1),), (unsupported,), _key()
        )


def test_an_unmodelled_action_behind_only_a_zero_target_commits_nothing() -> None:
    share = _shares(numerator="1", denominator="1", recipient=SEC_ACQ)
    outcome = _share_action_case(
        suffix=1800,
        action_kind=ActionKind.CONVERSION,
        components=(share,),
        claim_status="converted",
    )
    state = _state()

    updated, _ = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key()
    )
    assert updated is state

    # Control: a staged buy is exposure.
    with pytest.raises(IndeterminateValuationError, match="no proven M2 accounting"):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 1),), (outcome,), _key()
        )


# --------------------------------------------------------------------------
# windows spanning several dates
# --------------------------------------------------------------------------


def _split_effect(
    security_id: UUID,
    kind: ActionKind,
    numerator: str,
    denominator: str,
    effective_at: str,
    suffix: int,
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    component = _shares(
        numerator=numerator,
        denominator=denominator,
        recipient=security_id,
        predecessor=security_id,
        component_id=f"shares-{suffix}",
    )
    terms = _terms(
        suffix=suffix,
        action_kind=kind,
        components=(component,),
        security_id=security_id,
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=(component,),
        terms=terms,
        occurrence_id=f"occ-{suffix}",
        effective_at=effective_at,
        security_id=security_id,
    )
    return terms, effect


@pytest.mark.parametrize(("reverse", "forward"), [(2100, 2150), (2150, 2100)])
def test_two_share_actions_on_two_dates_in_one_window_are_indeterminate(
    reverse: int, forward: int
) -> None:
    # A 1:10 reverse split on Friday and a 3:1 split on Monday both land in
    # Monday's window. In date order 105 shares become 10 and then 30; in the
    # other order they become 315 and then 31. Nothing orders them by date.
    first = _split_effect(
        SEC_A, ActionKind.REVERSE_SPLIT, "1", "10", BETWEEN_AT, reverse
    )
    second = _split_effect(SEC_A, ActionKind.FORWARD_SPLIT, "3", "1", LATER_AT, forward)
    outcome = _outcome(
        terms=(first[0], second[0]),
        effects=(first[1], second[1]),
        action_kinds=(ActionKind.REVERSE_SPLIT, ActionKind.FORWARD_SPLIT),
    )
    state = _state(holdings=(_holding(quantity=105),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match=r"share actions on 2020-06-05, 2020-06-08 touching",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(LATER_DAY))

    # Control: a book exposed to neither date's action is not halted.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),), day=LATER_DAY)
    unchanged, _ = _processor().apply_pre_open_actions(
        elsewhere, (), (outcome,), _key(LATER_DAY)
    )
    assert unchanged is elsewhere


def test_an_acquirer_split_and_an_acquisition_on_two_dates_are_indeterminate() -> None:
    # The acquirer splits 2:1 on Friday, and SEC_A converts 1:1 into it on
    # Monday. The two actions touch one security, the acquirer, on two dates
    # of one window, and the processor would apply them by security order.
    split_terms, split_effect = _split_effect(
        SEC_ACQ, ActionKind.FORWARD_SPLIT, "2", "1", BETWEEN_AT, 2200
    )
    split = _outcome(
        security_id=SEC_ACQ,
        terms=(split_terms,),
        effects=(split_effect,),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    acquisition = _share_action_case(
        suffix=2210,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(_shares(numerator="1", denominator="1", recipient=SEC_ACQ),),
        claim_status="converted",
        effective_at=LATER_AT,
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError, match=r"share actions on 2020-06-05, 2020-06-08"
    ):
        _processor().apply_pre_open_actions(
            state, (), (acquisition, split), _key(LATER_DAY)
        )

    # Control: on a single date there is no date order to lose, so the guard
    # stays silent; how same-date actions are ordered is a separate question.
    same_day = _share_action_case(
        suffix=2220,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(_shares(numerator="1", denominator="1", recipient=SEC_ACQ),),
        claim_status="converted",
        effective_at=BETWEEN_AT,
    )
    applied, _ = _processor().apply_pre_open_actions(
        state, (), (same_day, split), _key(LATER_DAY)
    )
    assert _quantities(applied.holdings)[SEC_ACQ] in {100, 200}


def test_share_actions_on_dates_in_different_windows_apply_one_by_one() -> None:
    # A split on EFFECT_DAY and another on LATER_DAY: two dates, but each in
    # its own session's window, so each window holds a single date.
    first = _split_effect(SEC_A, ActionKind.FORWARD_SPLIT, "2", "1", EFFECT_AT, 2230)
    second = _split_effect(SEC_A, ActionKind.FORWARD_SPLIT, "3", "1", LATER_AT, 2240)
    outcome = _outcome(
        terms=(first[0], second[0]),
        effects=(first[1], second[1]),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=200),), day=LATER_DAY)

    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    assert _quantities(updated.holdings) == {SEC_A: 600}


def test_a_distribution_beside_a_share_action_on_another_date_applies() -> None:
    # Friday's dividend pays on no share change, so it and Monday's split
    # share one window without an order to lose: the dividend is owed on the
    # prior close, the split doubles the holding.
    split_terms, split_effect = _split_effect(
        SEC_A, ActionKind.FORWARD_SPLIT, "2", "1", LATER_AT, 2250
    )
    dividend_terms, dividend_effect, _ = _dividend_case(
        amount="0.5",
        suffix=2260,
        dates=(_date_fact("ex", BETWEEN_AT), _date_fact("payable", PAYABLE_AT)),
    )
    dividend_effect = _effect(
        suffix=2261,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5"),),
        terms=dividend_terms,
        occurrence_id="occ-dividend",
        effective_at=BETWEEN_AT,
    )
    outcome = _outcome(
        terms=(split_terms, dividend_terms),
        effects=(split_effect, dividend_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REGULAR_CASH_DIVIDEND),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    assert _quantities(updated.holdings) == {SEC_A: 200}
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("50.0")


def test_a_before_window_effect_is_never_applied() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=2270,
    )
    before = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        statuses=("before_window",),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=100),))

    # Dated on this session, but M1c places it before its evidence window.
    # It can explain delivered cash; it never moves shares.
    updated, _ = _processor().apply_pre_open_actions(state, (), (before,), _key())

    assert updated is state


def test_unsupported_evidence_is_judged_against_the_book_the_pass_leaves() -> None:
    # The parent spins off into SEC_A, which sorts first. The child's own
    # outcome is unsupported, and the staged target of 0 alone is no
    # exposure, but the spin-off credits the child during the same pass.
    component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_A,
        predecessor=SEC_ACQ,
        meaning="additional_per_predecessor",
    )
    terms = _terms(
        suffix=2300,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        security_id=SEC_ACQ,
    )
    effect = _effect(
        suffix=2301,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        terms=terms,
        occurrence_id="spin-1",
        security_id=SEC_ACQ,
    )
    spin = _outcome(
        security_id=SEC_ACQ,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )
    child = _outcome(
        security_id=SEC_A,
        support_status="indeterminate",
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(SEC_ACQ, quantity=100),))
    targets = (_target(SEC_ACQ, 100), _target(SEC_A, 0))

    with pytest.raises(
        IndeterminateValuationError,
        match="economic outcome resolution is not supported evidence",
    ):
        _processor().apply_pre_open_actions(state, targets, (spin, child), _key())


def test_an_unmodelled_action_is_judged_against_the_book_the_pass_leaves() -> None:
    component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_A,
        predecessor=SEC_ACQ,
        meaning="additional_per_predecessor",
    )
    terms = _terms(
        suffix=2310,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        security_id=SEC_ACQ,
    )
    effect = _effect(
        suffix=2311,
        action_kind=ActionKind.SPINOFF,
        components=(component,),
        terms=terms,
        occurrence_id="spin-2",
        security_id=SEC_ACQ,
    )
    spin = _outcome(
        security_id=SEC_ACQ,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )
    conversion = _share_action_case(
        suffix=2320,
        action_kind=ActionKind.CONVERSION,
        components=(_shares(numerator="1", denominator="1", recipient=SEC_OTHER),),
        claim_status="converted",
    )
    state = _state(holdings=(_holding(SEC_ACQ, quantity=100),))
    targets = (_target(SEC_ACQ, 100), _target(SEC_A, 0))

    # The conversion of SEC_A is read before the spin-off credits SEC_A.
    with pytest.raises(IndeterminateValuationError, match="no proven M2 accounting"):
        _processor().apply_pre_open_actions(state, targets, (conversion, spin), _key())


def test_a_future_dividend_without_an_ex_date_waits_until_it_is_effective() -> None:
    _, _, outcome = _dividend_case(
        amount="0.5",
        suffix=2400,
        dates=(_date_fact("record", ENTITLED_AT), _date_fact("payable", PAYABLE_AT)),
    )
    effect = _effect(
        suffix=2401,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5"),),
        terms=outcome.terms_records[0],
        effective_at=ENTITLED_AT,
    )
    future = _outcome(terms=outcome.terms_records, effects=(effect,))
    early = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    # The effect is not yet effective, so its missing ex date cannot yet say
    # anything about this book.
    unchanged, _ = _processor().apply_pre_open_actions(
        early, (), (future,), _key(LATER_DAY)
    )
    assert unchanged is early

    # Control: once effective, the missing ex date halts the run.
    due = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    with pytest.raises(IndeterminateValuationError, match="requires a source ex date"):
        _processor().apply_pre_open_actions(due, (), (future,), _key(ENTITLED_DAY))


def test_a_dividend_effective_after_its_ex_date_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="0.5",
        suffix=2410,
        dates=(_date_fact("ex", BETWEEN_AT), _date_fact("payable", PAYABLE_AT)),
    )
    effect = _effect(
        suffix=2411,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5"),),
        terms=outcome.terms_records[0],
        effective_at=ENTITLED_AT,
    )
    late = _outcome(terms=outcome.terms_records, effects=(effect,))
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    # The ex date falls in this window, but the occurrence proving the
    # entitlement is effective only later. An entitlement never vests before
    # the evidence that proves it (spec 12.3, issue 82).
    with pytest.raises(
        IndeterminateValuationError,
        match="cannot vest before the occurrence that proves it",
    ):
        _processor().apply_pre_open_actions(state, (), (late,), _key(LATER_DAY))


def test_delivered_cash_from_another_source_is_indeterminate() -> None:
    # The effect proves synthetic-a's occ-1. A delivery from synthetic-b that
    # reuses the occurrence id is another source's report, which no proven
    # entitlement of this book explains.
    terms, effect, _ = _dividend_case(
        amount="0.5",
        suffix=2500,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    delivery = _delivery(components=(_cash(amount="0.5"),), source_id=SOURCE_B)
    outcome = _outcome(terms=(terms,), effects=(effect,), delivery_groups=(delivery,))
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (outcome,), _key(PAYABLE_DAY)
        )


def test_cash_in_lieu_delivered_to_a_whole_share_holder_commits_nothing() -> None:
    # A 1:8 reverse split pays aggregate-sale cash for fractions, reported
    # under the share component id. Sixteen shares become exactly two, so
    # this book is owed no fraction: the delivery pays other holders.
    terms, effect, _ = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=2510,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    delivery = _delivery(components=(_cash(amount="4", component_id="shares-1"),))
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(delivery,),
        action_kinds=(ActionKind.REVERSE_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=2),), cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state


def test_a_delivery_is_reconciled_against_one_proof_per_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import drift.evaluator.corporate_actions as module

    terms, effects, deliveries = [], [], []
    for index in range(6):
        dividend_terms, _, _ = _dividend_case(
            amount="0.5",
            suffix=2600 + 10 * index,
            dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
        )
        terms.append(dividend_terms)
        effects.append(
            _effect(
                suffix=2601 + 10 * index,
                action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
                components=(_cash(amount="0.5"),),
                terms=dividend_terms,
                occurrence_id=f"occ-{index}",
            )
        )
        deliveries.append(
            _delivery(components=(_cash(amount="0.5"),), occurrence_id=f"occ-{index}")
        )
    outcome = _outcome(
        terms=tuple(terms), effects=tuple(effects), delivery_groups=tuple(deliveries)
    )
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)
    proofs: list[object] = []
    real = module._effect_contexts

    def counted(*args: object, **kwargs: object) -> object:
        proofs.append(args)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module, "_effect_contexts", counted)

    # Six unmatched deliveries, all unowed, re-read every session: proving
    # the outcome once per delivery made each pass quadratic.
    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state
    assert len(proofs) == 1


def test_a_before_window_effect_explains_only_a_pre_clock_entitlement() -> None:
    # M1c reports the effect as occurring before its evidence window, and the
    # delivered cash lands inside the clock. It is proof only of an
    # entitlement that vested before the clock's first session, which the
    # opening book already carries.
    delivery = _delivery(components=(_cash(amount="0.5"),))
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)
    for ex_at, vests_before_the_clock in ((BEFORE_CLOCK_AT, True), (EFFECT_AT, False)):
        terms, effect, _ = _dividend_case(
            amount="0.5",
            suffix=2700 if vests_before_the_clock else 2710,
            dates=(_date_fact("ex", ex_at), _date_fact("payable", PAYABLE_AT)),
        )
        effect = _effect(
            suffix=2701 if vests_before_the_clock else 2711,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(_cash(amount="0.5"),),
            terms=terms,
            effective_at=ex_at,
        )
        outcome = _outcome(
            terms=(terms,),
            effects=(effect,),
            statuses=("before_window",),
            delivery_groups=(delivery,),
        )
        if vests_before_the_clock:
            settled = _processor().apply_intrasession_settlements(
                state, (outcome,), _key(PAYABLE_DAY)
            )
            assert settled is state
        else:
            # Vested on the clock's first session, which the pre-open pass
            # never saw, so the book may well have been owed it.
            with pytest.raises(
                IndeterminateValuationError, match="before the evidence window"
            ):
                _processor().apply_intrasession_settlements(
                    state, (outcome,), _key(PAYABLE_DAY)
                )


def test_effect_without_an_identified_occurrence_is_indeterminate() -> None:
    component = _shares(
        numerator="2", denominator="1", treatment=_treatment("round_down")
    )
    terms = _terms(
        suffix=560, action_kind=ActionKind.FORWARD_SPLIT, components=(component,)
    )
    effect = _effect(
        suffix=561,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        terms=terms,
        occurrence_id=None,
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.FORWARD_SPLIT,)
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="requires an identified source occurrence",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_duplicate_effective_reports_for_one_occurrence_fail_closed() -> None:
    component = _shares(
        numerator="2", denominator="1", treatment=_treatment("round_down")
    )
    terms = _terms(
        suffix=570, action_kind=ActionKind.FORWARD_SPLIT, components=(component,)
    )
    first = _effect(
        suffix=571,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        terms=terms,
    )
    second = _effect(
        suffix=572,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        terms=terms,
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(first, second),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="more than one effective report for one occurrence",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_effect_without_identified_terms_is_indeterminate() -> None:
    component = _cash(amount="2")
    effect = _effect(
        suffix=580,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=None,
    )
    outcome = _outcome(effects=(effect,))
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="identified source terms to prove its dates",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_effect_asserting_another_terms_version_is_indeterminate() -> None:
    component = _cash(amount="2")
    terms = _terms(
        suffix=720,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        dates=(
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    effect = _effect(
        suffix=721,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=terms,
        asserted_hash=HASH_E,
    )
    outcome = _outcome(terms=(terms,), effects=(effect,))
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="not the version the occurred effect asserts",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_unsupported_property_component_fails_closed() -> None:
    component = _shares(
        numerator="2", denominator="1", treatment=_treatment("round_down")
    )
    property_leg = UnsupportedPropertyComponentV1(
        kind="unsupported_property",
        component_id="property-1",
        recipient=EconomicRecipientV1(kind="security", security_id=SEC_CHILD),
        source_description="an unvalued property receipt",
        reason="M1c does not value this receipt",
        evidence_reference=_ref("unsupported property receipt"),
    )
    terms = _terms(
        suffix=590,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component, property_leg),
    )
    effect = _effect(
        suffix=591,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component, property_leg),
        terms=terms,
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.FORWARD_SPLIT,)
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="carries an unvalued property component",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


# --------------------------------------------------------------------------
# claim identity and binding invariants
# --------------------------------------------------------------------------


def test_two_sources_reporting_one_occurrence_fail_closed_on_identity() -> None:
    first_terms, _, first_outcome = _dividend_case(amount="0.5", suffix=600)
    del first_terms
    component = _cash(amount="0.5")
    terms_b = _terms(
        suffix=610,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        dates=(
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
        ),
        source_id="synthetic-b",
    )
    effect_b = _effect(
        suffix=611,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=terms_b,
        source_id="synthetic-b",
    )
    combined = _outcome(
        terms=first_outcome.terms_records + (terms_b,),
        effects=first_outcome.effect_records + (effect_b,),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="more than one effective report for one occurrence",
    ):
        _processor().apply_pre_open_actions(state, (), (combined,), _key())


def test_outcome_bundle_rejects_a_foreign_security_record() -> None:
    component = _cash(amount="2")
    terms = _terms(
        suffix=620,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        security_id=SEC_OTHER,
    )
    with pytest.raises(ValueError, match="terms record must describe"):
        _outcome(terms=(terms,))


def test_outcome_bundle_requires_records_for_every_projection() -> None:
    _, effect, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=630,
    )
    del effect
    with pytest.raises(ValueError, match="must correspond exactly"):
        SecurityEconomicOutcomeV1(
            security_id=SEC_A,
            resolution=outcome.resolution,
            terms_records=outcome.terms_records,
            effect_records=(),
        )


def test_outcomes_must_be_unique_by_security() -> None:
    _, _, outcome = _dividend_case(amount="2", suffix=640)
    with pytest.raises(ValueError, match="economic outcomes must be unique"):
        _processor().apply_pre_open_actions(_state(), (), (outcome, outcome), _key())


def test_portfolio_state_must_be_positioned_at_the_current_session() -> None:
    _, _, outcome = _dividend_case(amount="2", suffix=650)
    state = _state(day=LATER_DAY)
    with pytest.raises(ValueError, match="portfolio state must already be positioned"):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_conflicting_tie_breaking_rules_are_rejected_at_construction() -> None:
    reference = _ref("one tie-breaking statement")
    first = TieBreakingRuleV1(
        source_rule="nearest", evidence_reference=reference, tie_break="half_up"
    )
    second = TieBreakingRuleV1(
        source_rule="nearest", evidence_reference=reference, tie_break="half_even"
    )
    with pytest.raises(ValueError, match="conflicting interpreted tie-breaking"):
        _processor(tie_breaking_rules=(first, second))


def test_cash_in_lieu_rate_from_another_source_is_not_used() -> None:
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=660,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    foreign = _cash_in_lieu_rate(effect=effect, rate="4").model_copy(
        update={"source_id": "synthetic-b"}
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="proven source aggregate-sale cash rate",
    ):
        _processor(cash_in_lieu_rates=(foreign,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_due_bill_rule_from_another_source_is_not_used() -> None:
    terms, _, outcome = _due_bill_terms()
    foreign = _due_bill_rule(terms, entitlement=LATER_DAY, source_id="synthetic-b")
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="proven executable due-bill rule",
    ):
        _processor(due_bill_rules=(foreign,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_dividend_share_basis_selects_pre_or_post_split_quantity() -> None:
    # A split and a distribution declared for the same session. The share
    # count a dividend is owed on must follow the source's stated basis, not
    # the order the two source records happen to hash in.
    split_component = _shares(
        numerator="2",
        denominator="1",
        component_id="split-shares",
        treatment=_treatment("round_down"),
    )
    split_terms = _terms(
        suffix=670,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(split_component,),
    )
    split_effect = _effect(
        suffix=671,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(split_component,),
        terms=split_terms,
        occurrence_id="occ-split",
    )
    for basis, expected in (
        ("predecessor_pre_action", Decimal("50.0")),
        ("predecessor_post_action", Decimal("100.0")),
    ):
        cash_component = CashComponentV1(
            kind="cash",
            component_id="cash-1",
            amount="0.5",
            currency_namespace=BOOK_NAMESPACE,
            currency_code=BOOK_CODE,
            unit_basis=EconomicUnitBasisV1(
                security_id=SEC_A,
                denominator=PositiveRatioV1(numerator="1", denominator="1"),
                share_basis=basis,  # type: ignore[arg-type]
            ),
            amount_basis="gross",
            applicability="ordinary_passive_holder",
            conditions=(),
        )
        dividend_terms = _terms(
            suffix=680,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(cash_component,),
            dates=(
                _date_fact("ex", EFFECT_AT),
                _date_fact("record", EFFECT_AT),
                _date_fact("payable", PAYABLE_AT),
            ),
        )
        dividend_effect = _effect(
            suffix=681,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            components=(cash_component,),
            terms=dividend_terms,
            occurrence_id="occ-dividend",
        )
        outcome = _outcome(
            terms=(split_terms, dividend_terms),
            effects=(split_effect, dividend_effect),
            action_kinds=(
                ActionKind.FORWARD_SPLIT,
                ActionKind.REGULAR_CASH_DIVIDEND,
            ),
        )
        state = _state(holdings=(_holding(quantity=100),))
        updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
        assert updated.holdings[0].quantity == 200
        assert len(updated.pending_cash_claims) == 1
        assert updated.pending_cash_claims[0].total_cash_expected == expected


def test_cash_in_lieu_claim_settles_against_the_original_component_id() -> None:
    treatment = _treatment("aggregate_sale_cash")
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=treatment,
        suffix=690,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    processor = _processor(
        cash_in_lieu_rates=(_cash_in_lieu_rate(effect=effect, rate="4"),)
    )
    state = _state(holdings=(_holding(quantity=10, basis="800"),), cash="100")
    staged, _ = processor.apply_pre_open_actions(state, (), (outcome,), _key())
    assert len(staged.pending_cash_claims) == 1

    # The source reports the aggregate sale against the share component it
    # sold out of, not against the derived cash-in-lieu leg id.
    delivered = _outcome(
        effects=(),
        delivery_groups=(
            _delivery(components=(_cash(amount="1", component_id="shares-1"),)),
        ),
    )
    settled = processor.apply_intrasession_settlements(
        _payable_state(staged), (delivered,), _key(PAYABLE_DAY)
    )
    assert settled.pending_cash_claims == ()
    assert settled.cash_balance == Decimal("101")


def test_corporate_action_discards_a_stale_mark() -> None:
    _, _, outcome = _split_case(
        numerator="2",
        denominator="1",
        treatment=_treatment("round_down"),
        action_kind=ActionKind.FORWARD_SPLIT,
        suffix=700,
    )
    kernel = PortfolioAccountingKernel(
        _state(holdings=(_holding(quantity=100, basis="1000"),), cash="500"),
        session_clock=CLOCK,
    )
    kernel.mark_close((_mark_price(SEC_A, "10"),))
    marked = kernel.state
    assert marked.is_marked is True
    assert marked.mark is not None
    updated, _ = _processor().apply_pre_open_actions(marked, (), (outcome,), _key())
    assert updated.holdings[0].quantity == 200
    assert updated.is_marked is False
    assert updated.mark is None
    assert updated.holdings_market_value == ZERO
    assert updated.net_asset_value == Decimal("500")


def test_source_date_that_pins_no_session_is_indeterminate() -> None:
    interval = EconomicDateFactV1(
        role="payable",
        boundary=bounded_boundary(
            "2020-06-15T00:00:00Z",
            "2020-06-18T00:00:00Z",
            _ref("an interval payable window"),
        ),
        rule_reference=None,
    )
    _, _, outcome = _dividend_case(
        amount="2",
        suffix=710,
        dates=(
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            interval,
        ),
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="payable date does not pin an exact session date",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_due_bill_entitlement_vests_on_the_proven_redemption_session() -> None:
    terms, _, outcome = _due_bill_terms()
    rule = _due_bill_rule(terms, entitlement=LATER_DAY, redemption=LATER_DAY)
    processor = _processor(due_bill_rules=(rule,))
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)
    entitled, _ = processor.apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )
    assert len(entitled.pending_cash_claims) == 1
    assert entitled.pending_cash_claims[0].entitlement_session == LATER_DAY


def test_cash_amount_is_divided_by_its_source_unit_denominator() -> None:
    component = _cash(amount="100", numerator="1000", denominator="1")
    terms = _terms(
        suffix=730,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        dates=(
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    effect = _effect(
        suffix=731,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=terms,
    )
    outcome = _outcome(terms=(terms,), effects=(effect,))
    state = _state(holdings=(_holding(quantity=100),))
    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    claim = updated.pending_cash_claims[0]
    assert claim.cash_per_share == Decimal("0.1")
    assert claim.total_cash_expected == Decimal("10.0")


def test_aggregate_sale_rate_not_bound_to_source_evidence_is_indeterminate() -> None:
    _, effect, outcome = _split_case(
        numerator="1",
        denominator="8",
        treatment=_treatment("aggregate_sale_cash"),
        suffix=740,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    unbound = _cash_in_lieu_rate(
        effect=effect,
        rate="4",
        evidence=_ref("an unrelated aggregate-sale statement"),
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="not bound to the source fraction-treatment evidence",
    ):
        _processor(cash_in_lieu_rates=(unbound,)).apply_pre_open_actions(
            state, (), (outcome,), _key()
        )


def test_payable_date_before_the_entitlement_session_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="2",
        suffix=750,
        dates=(
            _date_fact("ex", PAYABLE_AT),
            _date_fact("record", PAYABLE_AT),
            _date_fact("payable", EFFECT_AT),
        ),
    )
    state = _state(holdings=(_holding(quantity=100),), day=PAYABLE_DAY)
    with pytest.raises(
        IndeterminateValuationError,
        match="payable date cannot precede the proven entitlement",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(PAYABLE_DAY))


def test_cash_distribution_is_recognized_only_on_its_entitlement_session() -> None:
    _, _, outcome = _dividend_case(amount="0.5", suffix=760)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)
    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )
    assert updated is state
    assert updated.pending_cash_claims == ()


def test_entitlement_before_the_proven_occurrence_is_indeterminate() -> None:
    component = _cash(amount="2")
    terms = _terms(
        suffix=770,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        dates=(
            _date_fact("ex", EFFECT_AT),
            _date_fact("record", EFFECT_AT),
            _date_fact("payable", PAYABLE_AT),
        ),
    )
    effect = _effect(
        suffix=771,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(component,),
        terms=terms,
        effective_at=LATER_AT,
    )
    outcome = _outcome(terms=(terms,), effects=(effect,))
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError,
        match="cannot vest before the occurrence that proves it",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_liquidation_carrying_a_share_component_is_indeterminate() -> None:
    cash = _cash(amount="7")
    share = _shares(
        numerator="1",
        denominator="1",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(
        suffix=780,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash, share),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=781,
        action_kind=ActionKind.LIQUIDATION,
        components=(cash, share),
        terms=terms,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(ActionKind.LIQUIDATION,)
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="a liquidation requires proven source cash components",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_split_paying_a_different_security_is_indeterminate() -> None:
    _, _, outcome = _split_case_component(
        suffix=790,
        component=_shares(
            numerator="1",
            denominator="2",
            recipient=SEC_CHILD,
            treatment=_treatment("round_down"),
        ),
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError, match="split has an unexpected share recipient"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_split_with_additional_ratio_meaning_is_indeterminate() -> None:
    _, _, outcome = _split_case_component(
        suffix=800,
        component=_shares(
            numerator="1",
            denominator="2",
            meaning="additional_per_predecessor",
            treatment=_treatment("round_down"),
        ),
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="split requires resulting_per_predecessor share terms",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_split_with_two_share_components_is_indeterminate() -> None:
    first = _shares(
        numerator="1",
        denominator="2",
        component_id="shares-1",
        treatment=_treatment("round_down"),
    )
    second = _shares(
        numerator="1",
        denominator="4",
        component_id="shares-2",
        treatment=_treatment("round_down"),
    )
    _, _, outcome = _split_case_components(suffix=810, components=(first, second))
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="split requires exactly one source share component",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_split_carrying_source_cash_is_indeterminate() -> None:
    share = _shares(numerator="1", denominator="2", treatment=_treatment("round_down"))
    _, _, outcome = _split_case_components(
        suffix=820, components=(share, _cash(amount="3"))
    )
    state = _state(holdings=(_holding(quantity=10),))
    with pytest.raises(
        IndeterminateValuationError,
        match="split carries no source cash component in M1c terms",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_share_acquisition_that_extinguishes_a_position_is_indeterminate() -> None:
    component = _shares(
        numerator="1",
        denominator="8",
        recipient=SEC_ACQ,
        treatment=_treatment("round_down"),
    )
    terms = _terms(
        suffix=830,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(component,),
    )
    effect = _effect(
        suffix=831,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(component,),
        terms=terms,
        claim_status="converted",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.STOCK_ACQUISITION,),
    )
    state = _state(holdings=(_holding(quantity=1),))
    with pytest.raises(
        IndeterminateValuationError,
        match="a share acquisition would extinguish a held position",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_a_payable_date_revision_carries_one_claim_identity() -> None:
    # The hazard the ruled claim identity removes. Dates are revisable
    # attributes, so one entitlement whose payable date was revised keeps a
    # single id and resolves by supersession. Were it to mint a second id,
    # both settled-claim guards are keyed on claim id, so neither would fire
    # and the entitlement would pay twice.
    first = _manual_claim(payable=PAYABLE_DAY)
    second = _manual_claim(payable=LATER_DAY)
    assert first.payable_session != second.payable_session
    assert first.claim_id == second.claim_id


def test_two_claims_on_one_component_make_delivery_ambiguous() -> None:
    # Genuine ambiguity survives source scoping. The index key names the
    # source, security, occurrence and component, but claim identity also
    # carries the action kind, which the key does not. One source reusing one
    # native occurrence id across two action kinds therefore holds two
    # entitlements under one key, and a delivered report, which carries no
    # action kind, names both. Settling either one would be a guess.
    first = _manual_claim(
        payable=PAYABLE_DAY, action_kind=ActionKind.REGULAR_CASH_DIVIDEND
    )
    second = _manual_claim(
        payable=PAYABLE_DAY, action_kind=ActionKind.SPECIAL_CASH_DISTRIBUTION
    )
    assert first.source_id == SOURCE_A
    assert second.source_id == SOURCE_A
    assert first.claim_id != second.claim_id
    state = _state(claims=(first, second), cash="100", day=PAYABLE_DAY)
    delivered = _outcome(
        effects=(),
        delivery_groups=(
            _delivery(components=(_cash(amount="0.5"),), source_id=SOURCE_A),
        ),
    )
    with pytest.raises(
        IndeterminateValuationError,
        match=(
            r"^one delivered cash component matches more than one pending "
            r"claim: synthetic-a/occ-1/cash-1$"
        ),
    ):
        _processor().apply_intrasession_settlements(
            state, (delivered,), _key(PAYABLE_DAY)
        )


def test_delivery_settles_the_claim_from_its_own_source() -> None:
    # Two sources reusing one native occurrence id are two entitlements. The
    # delivered report carries its own source, so it names exactly one of
    # them and the other stays pending.
    mine = _manual_claim(payable=PAYABLE_DAY, source_id=SOURCE_A)
    theirs = _manual_claim(payable=PAYABLE_DAY, source_id=SOURCE_B)
    assert mine.claim_id != theirs.claim_id
    state = _state(claims=(mine, theirs), cash="100", day=PAYABLE_DAY)
    delivered = _outcome(
        effects=(),
        delivery_groups=(
            _delivery(components=(_cash(amount="0.5"),), source_id=SOURCE_B),
        ),
    )
    settled = _processor().apply_intrasession_settlements(
        state, (delivered,), _key(PAYABLE_DAY)
    )
    assert settled.settled_claim_ids == (theirs.claim_id,)
    assert tuple(item.claim_id for item in settled.pending_cash_claims) == (
        mine.claim_id,
    )
    assert settled.cash_balance == Decimal("150.0")


def _manual_claim(
    *,
    payable: date,
    source_id: str = SOURCE_A,
    action_kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
) -> PendingCashClaimV1:
    per_share = Decimal("0.5")
    return PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            source_id=source_id,
            security_id=SEC_A,
            action_kind=action_kind,
            occurrence_id="occ-1",
            component_id="cash-1",
        ),
        source_id=source_id,
        security_id=SEC_A,
        action_kind=action_kind,
        occurrence_id="occ-1",
        component_id="cash-1",
        entitled_quantity=100,
        cash_per_share=per_share,
        total_cash_expected=per_share * 100,
        entitlement_session=EFFECT_DAY,
        payable_session=payable,
    )


def test_due_bill_rule_shape_is_enforced() -> None:
    with pytest.raises(ValueError, match="executable due-bill rule requires"):
        DueBillRuleV1(
            source_id="synthetic-a",
            security_id=SEC_A,
            occurrence_id="occ-1",
            rule_reference=_ref("due bill rule statement"),
            source_rule="a rule",
            executability="executable",
            entitlement_session=None,
            redemption_session=None,
            reason=None,
        )


def test_ambiguous_due_bill_rule_shape_is_enforced() -> None:
    with pytest.raises(ValueError, match="ambiguous due-bill rule requires"):
        DueBillRuleV1(
            source_id="synthetic-a",
            security_id=SEC_A,
            occurrence_id="occ-1",
            rule_reference=_ref("due bill rule statement"),
            source_rule="a rule",
            executability="ambiguous",
            entitlement_session=LATER_DAY,
            redemption_session=LATER_DAY,
            reason=None,
        )
