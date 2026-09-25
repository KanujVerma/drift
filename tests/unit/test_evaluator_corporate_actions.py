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
    share_basis: str = "predecessor_pre_action",
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
            share_basis=share_basis,  # type: ignore[arg-type]
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
    claim_status: str = "continuing",
) -> SecurityEconomicOutcomeV1:
    effect_statuses = ("effective",) * len(effects) if statuses is None else statuses
    # A composed claim status M1c cannot resolve marks the evidence partial.
    composed_unknown = claim_status == "unknown"
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
        claim_status=claim_status,  # type: ignore[arg-type]
        evidence_completeness="partial" if composed_unknown else "known",
        support_status=support_status,  # type: ignore[arg-type]
        reasons=(
            ("claim_effect_chronology_conflicting",)
            if composed_unknown
            else (() if support_status == "supported" else ("synthetic gap",))
        ),
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
    # Held at the ex date's prior close: the distribution is owed at the ex
    # date's pre-open.
    held = _state(holdings=(_holding(quantity=10),), day=ENTITLED_DAY)
    entitled, _ = _processor().apply_pre_open_actions(
        held, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert entitled.pending_cash_claims[0].entitlement_session == ENTITLED_DAY

    # Bought at the ex-date open instead: the shares are first held at the
    # next session's pre-open, which owns no date on or before the ex date,
    # so nothing is owed on them.
    bought = _state(holdings=(_holding(quantity=10),), day=PAYABLE_DAY)
    after, _ = _processor().apply_pre_open_actions(
        bought, (), (outcome,), _key(PAYABLE_DAY)
    )
    assert after is bought


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


def _conflicting_liquidations(
    suffix: int,
    *,
    composed: str,
    continuing_at: str = EFFECT_AT,
    final_at: str = EFFECT_AT,
) -> SecurityEconomicOutcomeV1:
    """An extinguishing and a continuing liquidation of SEC_A.

    ``composed`` is the claim status M1c composes across the two effects:
    for effects at one instant with conflicting statuses, or a continuing
    effect after an extinguishing one, M1c composes ``unknown``.
    """
    final = _cash(amount="15", component_id="liquidation-final")
    instalment = _cash(amount="3", component_id="liquidation-instalment")
    final_terms = _terms(
        suffix=suffix,
        action_kind=ActionKind.LIQUIDATION,
        components=(final,),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    final_effect = _effect(
        suffix=suffix + 1,
        action_kind=ActionKind.LIQUIDATION,
        components=(final,),
        terms=final_terms,
        occurrence_id="occ-final",
        claim_status="extinguished",
        effective_at=final_at,
    )
    instalment_terms = _terms(
        suffix=suffix + 10,
        action_kind=ActionKind.LIQUIDATION,
        components=(instalment,),
        dates=(_date_fact("ex", continuing_at), _date_fact("payable", PAYABLE_AT)),
    )
    instalment_effect = _effect(
        suffix=suffix + 11,
        action_kind=ActionKind.LIQUIDATION,
        components=(instalment,),
        terms=instalment_terms,
        occurrence_id="occ-instalment",
        effective_at=continuing_at,
    )
    return _outcome(
        terms=(final_terms, instalment_terms),
        effects=(final_effect, instalment_effect),
        action_kinds=(ActionKind.LIQUIDATION,),
        claim_status=composed,
    )


def test_a_liquidation_m1c_composes_as_unknown_is_indeterminate() -> None:
    # S11: an extinguishing and a continuing liquidation at one instant. Each
    # effect reads cleanly on its own, but M1c composes the claim as unknown:
    # whether any share survives is not proven.
    outcome = _conflicting_liquidations(2900, composed="unknown")
    state = _state(holdings=(_holding(quantity=10, basis="100"),), cash="0")

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # Control: a book exposed to nothing in SEC_A is not halted.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),))
    unchanged, _ = _processor().apply_pre_open_actions(
        elsewhere, (), (outcome,), _key()
    )
    assert unchanged is elsewhere


def test_an_extinguishing_liquidation_m1c_composes_as_unknown_halts_alone() -> None:
    # The continuing instalment is dated a window later than the
    # extinguishing liquidation, so M1c composes the claim as resurrected,
    # unknown. Only the extinguishing effect is in this window, and the
    # disposal itself must refuse to erase the shares. The pass would leave
    # no SEC_A, so only the prior close's book shows the exposure.
    outcome = _conflicting_liquidations(
        2930, composed="unknown", continuing_at=LATER_AT
    )
    state = _state(holdings=(_holding(quantity=10, basis="100"),))

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_a_resurrected_liquidation_claim_is_indeterminate() -> None:
    # A continuing instalment after the extinguishing one: M1c composes the
    # terminal state as resurrected, so unknown. At the continuing effect's
    # own session it is the distribution path that must refuse it.
    outcome = _conflicting_liquidations(
        2920, composed="unknown", continuing_at=LATER_AT
    )
    state = _state(holdings=(_holding(quantity=10, basis="100"),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(LATER_DAY))


def test_a_liquidation_m1c_composes_as_ended_or_continuing_applies() -> None:
    # Control for the composed-status rule: the same two effects, with the
    # instalment at 10:00 and the final liquidation at 15:00 of one date, are
    # ones M1c can order, and it composes them as extinguished. Each then
    # applies by its own rule: 30 for the instalment, 150 for the final.
    outcome = _conflicting_liquidations(
        2940,
        composed="extinguished",
        continuing_at="2020-06-01T10:00:00Z",
        final_at="2020-06-01T15:00:00Z",
    )
    state = _state(holdings=(_holding(quantity=10, basis="100"),), cash="0")

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert updated.holdings == ()
    assert updated.pending_claims_value == Decimal("180")


@pytest.mark.parametrize("kind", ["cash", "stock"])
def test_an_acquisition_m1c_composes_as_unknown_is_indeterminate(kind: str) -> None:
    # The same gap for acquisitions: the effect says the claim ended, but a
    # continuing dividend dated a window later resurrects the claim, so M1c
    # composes it as unknown and the conversion is unproven.
    if kind == "cash":
        components: tuple[EconomicComponentV1, ...] = (_cash(amount="12"),)
        action_kind = ActionKind.CASH_ACQUISITION
        dates: tuple[EconomicDateFactV1, ...] = (_date_fact("payable", PAYABLE_AT),)
    else:
        components = (_shares(numerator="3", denominator="2", recipient=SEC_ACQ),)
        action_kind = ActionKind.STOCK_ACQUISITION
        dates = ()
    ended = "converted" if kind == "stock" else "extinguished"
    terms = _terms(
        suffix=2960, action_kind=action_kind, components=components, dates=dates
    )
    effect = _effect(
        suffix=2961,
        action_kind=action_kind,
        components=components,
        terms=terms,
        claim_status=ended,
    )
    later_terms, later_effect = _continuing("dividend", LATER_AT)
    resurrected = _outcome(
        terms=(terms, later_terms),
        effects=(effect, later_effect),
        action_kinds=(action_kind, ActionKind.REGULAR_CASH_DIVIDEND),
        claim_status="unknown",
    )
    state = _state(holdings=(_holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (resurrected,), _key())

    # Control: the acquisition alone, which M1c composes as its own status.
    alone = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(action_kind,),
        claim_status=ended,
    )
    updated, _ = _processor().apply_pre_open_actions(state, (), (alone,), _key())
    assert SEC_A not in _quantities(updated.holdings)


def _resurrected_after(
    terminal_at: str,
    later: tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1],
    *,
    terminal_before_window: bool = False,
) -> SecurityEconomicOutcomeV1:
    """An extinguishing cash acquisition of SEC_A, then a continuing effect.

    M1c composes that chronology as ``claim_terminal_state_resurrected``,
    so ``unknown``. The continuing effect is a kind with no gate of its own.
    """
    cash_terms, cash_effect = _same_date_effect(
        3400,
        ActionKind.CASH_ACQUISITION,
        (_cash(amount="12", component_id="terminal"),),
        at=terminal_at,
        claim_status="extinguished",
        occurrence="occ-terminal",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    later_terms, later_effect = later
    payload = later_effect.payload
    assert isinstance(payload, OccurredEffectV1)
    return _outcome(
        terms=(cash_terms, later_terms),
        effects=(cash_effect, later_effect),
        statuses=(
            ("before_window" if terminal_before_window else "effective"),
            "effective",
        ),
        action_kinds=(ActionKind.CASH_ACQUISITION, payload.action_kind),
        claim_status="unknown",
    )


def _continuing(
    kind: str, at: str
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    if kind == "split":
        return _same_date_effect(
            3410,
            ActionKind.FORWARD_SPLIT,
            (_shares(numerator="2", denominator="1", component_id="split"),),
            at=at,
            claim_status="continuing",
            occurrence="occ-later",
        )
    if kind == "dividend":
        return _same_date_effect(
            3410,
            ActionKind.REGULAR_CASH_DIVIDEND,
            (_cash(amount="1", component_id="dividend"),),
            at=at,
            claim_status="continuing",
            occurrence="occ-later",
            dates=(_date_fact("ex", at), _date_fact("payable", PAYABLE_AT)),
        )
    if kind == "spinoff":
        return _same_date_effect(
            3410,
            ActionKind.SPINOFF,
            (
                _shares(
                    numerator="1",
                    denominator="2",
                    component_id="spin",
                    recipient=SEC_CHILD,
                    meaning="additional_per_predecessor",
                ),
            ),
            at=at,
            claim_status="continuing",
            occurrence="occ-later",
        )
    return _same_date_effect(
        3410,
        ActionKind.STOCK_DIVIDEND,
        (
            _shares(
                numerator="1",
                denominator="10",
                component_id="stock-dividend",
                meaning="additional_per_predecessor",
            ),
        ),
        at=at,
        claim_status="continuing",
        occurrence="occ-later",
    )


@pytest.mark.parametrize("at", [LATER_AT, BETWEEN_AT], ids=["on-clock", "off-clock"])
@pytest.mark.parametrize("kind", ["split", "dividend"])
def test_a_resurrected_claim_halts_an_ungated_kind_once_exposed(
    kind: str, at: str
) -> None:
    # C1: the extinguishing acquisition on EFFECT_DAY finds the book not
    # exposed; the continuing split or dividend in LATER_DAY's window finds
    # it holding SEC_A. Before the fix the split doubled the holding, or the
    # dividend recorded a claim of 100, on a claim M1c could not compose.
    # Dated on Friday, off the clock, the continuing effect commits in the
    # same window, on a date before the session's own.
    outcome = _resurrected_after(EFFECT_AT, _continuing(kind, at))
    processor = _processor()
    flat = _state(cash="10000")
    first, _ = processor.apply_pre_open_actions(flat, (), (outcome,), _key())
    assert first is flat

    held = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)
    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        processor.apply_pre_open_actions(held, (), (outcome,), _key(LATER_DAY))


@pytest.mark.parametrize("kind", ["split", "dividend", "spinoff", "stock_dividend"])
def test_a_resurrected_claim_halts_when_the_terminal_predates_the_window(
    kind: str,
) -> None:
    # C2: M1c places the extinguishing acquisition before its evidence
    # window, so the pre-open pass never reads it; the in-window continuing
    # effect still sits on a claim M1c composes as unknown.
    outcome = _resurrected_after(
        BEFORE_CLOCK_AT, _continuing(kind, EFFECT_AT), terminal_before_window=True
    )
    state = _state(holdings=(_holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    # Control: a book exposed to nothing the outcome touches is not halted.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),))
    unchanged, _ = _processor().apply_pre_open_actions(
        elsewhere, (), (outcome,), _key()
    )
    assert unchanged is elsewhere


def test_a_split_with_its_own_unknown_claim_status_halts() -> None:
    # C3: M1c composes one split whose own claim status is unknown as
    # unknown. The pass-level rule halts it too.
    terms, effect = _same_date_effect(
        3420,
        ActionKind.FORWARD_SPLIT,
        (_shares(numerator="2", denominator="1", component_id="split"),),
        at=EFFECT_AT,
        claim_status="unknown",
        occurrence="occ-split",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
        claim_status="unknown",
    )
    state = _state(holdings=(_holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_an_unknown_claim_halts_a_dividend_that_vests_in_the_window() -> None:
    # The dividend's effect is dated before this window, but its ex date is
    # in it, so this pass is the one that records the claim. The rule reads
    # the entitlement date too, not only the effective date. The effect's
    # own claim status is unknown, so M1c composes the claim as unknown.
    terms, effect = _same_date_effect(
        3430,
        ActionKind.REGULAR_CASH_DIVIDEND,
        (_cash(amount="1", component_id="dividend"),),
        at=EFFECT_AT,
        claim_status="unknown",
        occurrence="occ-dividend",
        dates=(_date_fact("ex", LATER_AT), _date_fact("payable", PAYABLE_AT)),
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        claim_status="unknown",
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(LATER_DAY))

    # Control: once the window holds neither its effect nor its ex date, the
    # composed unknown has nothing to act on and the pass completes.
    later = _state(holdings=(_holding(quantity=100),), day=ENTITLED_DAY)
    unchanged, _ = _processor().apply_pre_open_actions(
        later, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert unchanged is later


def test_an_unknown_claim_with_an_undatable_dividend_counts_as_live() -> None:
    # The dividend is effective and has no ex date, so when it vests cannot
    # be said: it could vest in this window. The book stages a buy of SEC_A
    # and holds none, which the dividend path ignores, so only the
    # pass-level rule sees that the claim it builds on is unknown. The
    # effect's own claim status is unknown, so M1c composes it as unknown.
    def undatable(at: str) -> SecurityEconomicOutcomeV1:
        terms, effect = _same_date_effect(
            3470,
            ActionKind.REGULAR_CASH_DIVIDEND,
            (_cash(amount="1", component_id="dividend"),),
            at=at,
            claim_status="unknown",
            occurrence="occ-dividend",
            dates=(_date_fact("payable", PAYABLE_AT),),
        )
        return _outcome(terms=(terms,), effects=(effect,), claim_status="unknown")

    buy = (_target(SEC_A, 10),)
    state = _state(day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(
            state, buy, (undatable(EFFECT_AT),), _key(LATER_DAY)
        )

    # Control: it is live only once it is effective. Effective on
    # ENTITLED_DAY, it is not yet evidence at LATER_DAY's pre-open, and it
    # halts ENTITLED_DAY's own.
    future = undatable(ENTITLED_AT)
    unchanged, _ = _processor().apply_pre_open_actions(
        state, buy, (future,), _key(LATER_DAY)
    )
    assert unchanged is state
    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(
            _state(day=ENTITLED_DAY), buy, (future,), _key(ENTITLED_DAY)
        )


def test_an_unknown_claim_counts_exposure_to_the_securities_it_delivers() -> None:
    # SEC_A converts into SEC_ACQ on EFFECT_DAY, and a continuing dividend
    # on SEC_A follows on LATER_DAY, so M1c composes the claim as
    # resurrected, unknown. The book holds only SEC_ACQ, the security the
    # outcome delivers into, which is exposure to that outcome too.
    terms, effect = _same_date_effect(
        3460,
        ActionKind.STOCK_ACQUISITION,
        (_shares(numerator="1", denominator="1", recipient=SEC_ACQ),),
        at=EFFECT_AT,
        claim_status="converted",
        occurrence="occ-conversion",
    )
    later_terms, later_effect = _continuing("dividend", LATER_AT)
    outcome = _outcome(
        terms=(terms, later_terms),
        effects=(effect, later_effect),
        action_kinds=(ActionKind.STOCK_ACQUISITION, ActionKind.REGULAR_CASH_DIVIDEND),
        claim_status="unknown",
    )

    for day in (EFFECT_DAY, LATER_DAY):
        # On LATER_DAY only the dividend commits, and the conversion that
        # delivers SEC_ACQ is a window old: exposure still counts every
        # security any effect of the outcome touches.
        state = _state(holdings=(_holding(SEC_ACQ, quantity=10, basis="80"),), day=day)
        with pytest.raises(
            IndeterminateValuationError,
            match="M1c composes the claim of .* as unknown",
        ):
            _processor().apply_pre_open_actions(state, (), (outcome,), _key(day))

    # Control: a book exposed to nothing the outcome touches is not halted.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),), day=LATER_DAY)
    unchanged, _ = _processor().apply_pre_open_actions(
        elsewhere, (), (outcome,), _key(LATER_DAY)
    )
    assert unchanged is elsewhere


def test_an_unknown_claim_is_judged_against_the_book_the_pass_leaves() -> None:
    # The parent SEC_ACQ spins off into SEC_A, which sorts first. SEC_A's own
    # outcome composes unknown (its dividend's own claim status is unknown)
    # with the dividend vesting now; at the prior close the book held no
    # SEC_A, but the pass leaves it holding 50.
    spin_component = _shares(
        numerator="1",
        denominator="2",
        recipient=SEC_A,
        predecessor=SEC_ACQ,
        meaning="additional_per_predecessor",
    )
    spin_terms = _terms(
        suffix=3440,
        action_kind=ActionKind.SPINOFF,
        components=(spin_component,),
        security_id=SEC_ACQ,
    )
    spin_effect = _effect(
        suffix=3441,
        action_kind=ActionKind.SPINOFF,
        components=(spin_component,),
        terms=spin_terms,
        occurrence_id="occ-spin",
        security_id=SEC_ACQ,
    )
    spin = _outcome(
        security_id=SEC_ACQ,
        terms=(spin_terms,),
        effects=(spin_effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )
    dividend_terms, dividend_effect = _same_date_effect(
        3450,
        ActionKind.REGULAR_CASH_DIVIDEND,
        (_cash(amount="1", component_id="dividend"),),
        at=EFFECT_AT,
        claim_status="unknown",
        occurrence="occ-child-dividend",
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    child = _outcome(
        terms=(dividend_terms,),
        effects=(dividend_effect,),
        claim_status="unknown",
    )
    state = _state(holdings=(_holding(SEC_ACQ, quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match="M1c composes the claim of .* as unknown",
    ):
        _processor().apply_pre_open_actions(state, (), (child, spin), _key())


def test_two_disposals_in_one_pass_both_realize() -> None:
    # S8: a cash acquisition of SEC_A and a liquidation of SEC_OTHER on one
    # session. Each relieves its own basis: 1200 - 900 and 30 - 50.
    acquisition = _share_action_case(
        suffix=2980,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12"),),
        claim_status="extinguished",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    other_cash = _cash(amount="3", predecessor=SEC_OTHER)
    other_terms = _terms(
        suffix=2990,
        action_kind=ActionKind.LIQUIDATION,
        components=(other_cash,),
        dates=(_date_fact("payable", PAYABLE_AT),),
        security_id=SEC_OTHER,
    )
    other_effect = _effect(
        suffix=2991,
        action_kind=ActionKind.LIQUIDATION,
        components=(other_cash,),
        terms=other_terms,
        occurrence_id="occ-other",
        claim_status="extinguished",
        security_id=SEC_OTHER,
    )
    liquidation = _outcome(
        security_id=SEC_OTHER,
        terms=(other_terms,),
        effects=(other_effect,),
        action_kinds=(ActionKind.LIQUIDATION,),
    )
    state = _state(
        holdings=(
            _holding(quantity=100, basis="900"),
            _holding(SEC_OTHER, quantity=10, basis="50"),
        ),
        cash="0",
    )

    updated, _ = _processor().apply_pre_open_actions(
        state, (), (acquisition, liquidation), _key()
    )

    assert updated.holdings == ()
    assert updated.pending_claims_value == Decimal("1230")
    assert updated.realized_gross_pnl == Decimal("280")
    assert updated.realized_net_pnl == Decimal("280")


def test_an_extinguishing_liquidation_beside_a_split_on_another_date_halts() -> None:
    # S12: an extinguishing liquidation on Friday and a split on Monday, one
    # window. Unlike a continuing one, it changes the share count, so it is a
    # share action for the multi-date window rule.
    split_terms, split_effect = _split_effect(
        SEC_A, ActionKind.FORWARD_SPLIT, "2", "1", LATER_AT, 3000
    )
    liquidation_terms = _terms(
        suffix=3010,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    liquidation_effect = _effect(
        suffix=3011,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        terms=liquidation_terms,
        occurrence_id="occ-liquidation",
        effective_at=BETWEEN_AT,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(split_terms, liquidation_terms),
        effects=(split_effect, liquidation_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.LIQUIDATION),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError, match=r"share actions on 2020-06-05, 2020-06-08"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(LATER_DAY))


def test_a_continuing_liquidation_owes_nothing_before_its_ex_date() -> None:
    # The effect is effective on EFFECT_DAY, but its ex date is ENTITLED_DAY.
    outcome = _liquidation_case(
        suffix=3020, claim_status="continuing", ex_at=ENTITLED_AT
    )

    # Held on the effect's own session: the ex date is still ahead, so no
    # claim is recorded yet.
    held = _state(holdings=(_holding(quantity=10),))
    at_effect, _ = _processor().apply_pre_open_actions(held, (), (outcome,), _key())
    assert at_effect is held

    # Sold before the ex date: the ex date's pre-open holds nothing, so
    # nothing is ever owed.
    sold = _state(day=ENTITLED_DAY)
    at_ex, _ = _processor().apply_pre_open_actions(
        sold, (), (outcome,), _key(ENTITLED_DAY)
    )
    assert at_ex is sold


@pytest.mark.parametrize("missing", ["terms", "payable"])
def test_a_disposal_without_its_terms_or_payable_date_is_indeterminate(
    missing: str,
) -> None:
    component = _cash(amount="7")
    terms = _terms(
        suffix=3030,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        dates=() if missing == "payable" else (_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=3031,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        terms=None if missing == "terms" else terms,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=() if missing == "terms" else (terms,),
        effects=(effect,),
        action_kinds=(ActionKind.LIQUIDATION,),
    )
    state = _state(holdings=(_holding(quantity=10),))

    # The proceeds are owed from the terms' payable date. Without it the
    # claim cannot be dated, so the disposal cannot be booked.
    with pytest.raises(
        IndeterminateValuationError,
        match=(
            "requires identified source terms"
            if missing == "terms"
            else "requires a source payable date"
        ),
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_an_extinguishing_liquidation_delivery_vests_on_its_effect_date() -> None:
    # Its cash is owed from the effective date, not under a distribution's ex
    # rule; its terms carry no ex date at all. A book exposed on the payable
    # session that holds no claim for it was not owed it.
    component = _cash(amount="7")
    terms = _terms(
        suffix=3040,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    effect = _effect(
        suffix=3041,
        action_kind=ActionKind.LIQUIDATION,
        components=(component,),
        terms=terms,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        delivery_groups=(_delivery(components=(component,)),),
        action_kinds=(ActionKind.LIQUIDATION,),
    )
    state = _state(holdings=(_holding(quantity=10),), cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state


def test_a_continuing_liquidation_with_a_share_component_names_itself() -> None:
    outcome = _share_action_case(
        suffix=3050,
        action_kind=ActionKind.LIQUIDATION,
        components=(
            _cash(amount="3"),
            _shares(numerator="1", denominator="1", recipient=SEC_ACQ),
        ),
        claim_status="continuing",
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    state = _state(holdings=(_holding(quantity=10),))

    with pytest.raises(
        IndeterminateValuationError,
        match="a liquidating distribution requires proven source cash components",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


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
# continuing share actions on an ended claim (issue 117)
# --------------------------------------------------------------------------

CONTINUING_SHARE_ACTIONS = (
    ActionKind.FORWARD_SPLIT,
    ActionKind.REVERSE_SPLIT,
    ActionKind.STOCK_DIVIDEND,
    ActionKind.SPINOFF,
)


def _continuing_share_action(
    kind: ActionKind, status: str, *, at: str = EFFECT_AT, suffix: int = 3800
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    """One continuing-claim share action on SEC_A with its own claim status.

    A 2:1 split, a 1:20 reverse split, a 1-for-10 stock dividend, or a
    spin-off of one SEC_CHILD per two shares, every fraction rounded down.
    """
    if kind == ActionKind.FORWARD_SPLIT:
        component = _shares(numerator="2", denominator="1", component_id="action")
    elif kind == ActionKind.REVERSE_SPLIT:
        component = _shares(numerator="1", denominator="20", component_id="action")
    elif kind == ActionKind.STOCK_DIVIDEND:
        component = _shares(
            numerator="1",
            denominator="10",
            component_id="action",
            meaning="additional_per_predecessor",
        )
    else:
        component = _shares(
            numerator="1",
            denominator="2",
            component_id="action",
            recipient=SEC_CHILD,
            meaning="additional_per_predecessor",
        )
    return _same_date_effect(
        suffix,
        kind,
        (component,),
        at=at,
        claim_status=status,
        occurrence="occ-share-action",
    )


def _ended_claim_share_action(
    kind: ActionKind, *, own: str, composed: str
) -> SecurityEconomicOutcomeV1:
    terms, effect = _continuing_share_action(kind, own)
    return _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(kind,), claim_status=composed
    )


def _ended_claim_message(kind: ActionKind, status: str) -> str:
    return (
        rf"the {kind.value} occ-share-action on {SEC_A} needs a continuing "
        rf"claim, but .*{status}"
    )


@pytest.mark.parametrize("kind", CONTINUING_SHARE_ACTIONS, ids=lambda kind: kind.value)
@pytest.mark.parametrize("status", ["extinguished", "converted"])
@pytest.mark.parametrize(
    ("own_ended", "composed_ended"),
    [(True, True), (True, False), (False, True)],
    ids=["own-and-composed", "own-only", "composed-only"],
)
def test_a_continuing_share_action_on_an_ended_claim_halts_an_exposed_book(
    kind: ActionKind, status: str, own_ended: bool, composed_ended: bool
) -> None:
    # N4 (issue 117): a split, reverse split, stock dividend or spin-off acts
    # on a continuing claim, yet its own claim status, or the status M1c
    # composes with no later effect ending the claim, says the claim ended
    # or was converted. The evidence contradicts itself. Before the fix the
    # action applied: 100 shares became 200 on a claim that had ended.
    # Only own-and-composed is a state M1c composes: M1c composes a lone
    # effect's own status. Own-only and composed-only are states it cannot
    # produce, pinned as defense in depth against evidence it did not compose.
    outcome = _ended_claim_share_action(
        kind,
        own=status if own_ended else "continuing",
        composed=status if composed_ended else "continuing",
    )
    state = _state(holdings=(_holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError, match=_ended_claim_message(kind, status)
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 100),), (outcome,), _key()
        )

    # Control: unrelated evidence does not poison a book exposed to nothing
    # in SEC_A.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),))
    unchanged, targets = _processor().apply_pre_open_actions(
        elsewhere, (_target(SEC_OTHER, 5),), (outcome,), _key()
    )
    assert unchanged is elsewhere
    assert _quantities(targets) == {SEC_OTHER: 5}


@pytest.mark.parametrize("kind", CONTINUING_SHARE_ACTIONS, ids=lambda kind: kind.value)
def test_a_continuing_share_action_on_an_ended_claim_halts_a_staged_buy(
    kind: ActionKind,
) -> None:
    # A positive staged target on an unheld SEC_A is exposure too. The 1:20
    # reverse split restates the target of 10 as 0, so only the prior
    # close's book shows the exposure; the book the pass leaves has none.
    outcome = _ended_claim_share_action(
        kind, own="extinguished", composed="extinguished"
    )
    state = _state()

    with pytest.raises(
        IndeterminateValuationError, match=_ended_claim_message(kind, "extinguished")
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 10),), (outcome,), _key()
        )

    # Control: an explicit zero target on an unheld SEC_A trades nothing.
    unchanged, targets = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key()
    )
    assert unchanged is state
    assert _quantities(targets) == {SEC_A: 0}


def test_a_share_action_on_an_ended_claim_commits_nothing_outside_its_window() -> None:
    # The rule judges an action in the window its effective date falls in,
    # the one pass that would apply it. A book first exposed a window later
    # is not acted on by it.
    outcome = _ended_claim_share_action(
        ActionKind.FORWARD_SPLIT, own="extinguished", composed="extinguished"
    )
    later = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    unchanged, _ = _processor().apply_pre_open_actions(
        later, (), (outcome,), _key(LATER_DAY)
    )

    assert unchanged is later


_CONTINUING_RESULT = {
    ActionKind.FORWARD_SPLIT: {SEC_A: 200},
    ActionKind.REVERSE_SPLIT: {SEC_A: 5},
    ActionKind.STOCK_DIVIDEND: {SEC_A: 110},
    ActionKind.SPINOFF: {SEC_A: 100, SEC_CHILD: 50},
}


@pytest.mark.parametrize("kind", CONTINUING_SHARE_ACTIONS, ids=lambda kind: kind.value)
def test_a_continuing_share_action_on_a_continuing_claim_applies(
    kind: ActionKind,
) -> None:
    # Control: with its own and its composed claim status continuing, each
    # action applies as before.
    outcome = _ended_claim_share_action(kind, own="continuing", composed="continuing")
    state = _state(holdings=(_holding(quantity=100),))

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert _quantities(updated.holdings) == _CONTINUING_RESULT[kind]


@pytest.mark.parametrize("kind", CONTINUING_SHARE_ACTIONS, ids=lambda kind: kind.value)
def test_a_share_action_before_a_later_acquisition_still_applies(
    kind: ActionKind,
) -> None:
    # Control: the action on EFFECT_DAY, then a cash acquisition on
    # LATER_DAY. M1c composes the claim as extinguished, the status of its
    # latest effect, and the acquisition that ends it definitely follows the
    # action. The action acted on a live claim, so it applies in its own
    # window, and the acquisition disposes of the holding in the next.
    action_terms, action_effect = _continuing_share_action(kind, "continuing")
    acquisition_terms, acquisition_effect = _same_date_effect(
        3810,
        ActionKind.CASH_ACQUISITION,
        (_cash(amount="12", component_id="acquisition"),),
        at=LATER_AT,
        claim_status="extinguished",
        occurrence="occ-acquisition",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    outcome = _outcome(
        terms=(action_terms, acquisition_terms),
        effects=(action_effect, acquisition_effect),
        action_kinds=(kind, ActionKind.CASH_ACQUISITION),
        claim_status="extinguished",
    )
    state = _state(holdings=(_holding(quantity=100),))

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    assert _quantities(updated.holdings) == _CONTINUING_RESULT[kind]

    later = _state(
        holdings=(_holding(quantity=_CONTINUING_RESULT[kind][SEC_A]),), day=LATER_DAY
    )
    disposed, _ = _processor().apply_pre_open_actions(
        later, (), (outcome,), _key(LATER_DAY)
    )
    assert SEC_A not in _quantities(disposed.holdings)


@pytest.mark.parametrize("ending", ["none", "earlier"])
def test_a_composed_end_no_later_effect_explains_halts_the_share_action(
    ending: str,
) -> None:
    # M1c's composed status is the status of the claim's latest effect, so a
    # composed end with a continuing split is explained only by an ending
    # effect that definitely follows the split. A later effect that ends
    # nothing, or an ending effect before the split, explains nothing: the
    # claim had ended by the split. M1c cannot compose either state: it
    # composes the first as continuing and the second as resurrected, so
    # unknown. Both are pinned as defense in depth against evidence M1c did
    # not compose.
    split_at, other_at = EFFECT_AT, LATER_AT
    if ending == "earlier":
        split_at, other_at = other_at, split_at
    split_terms, split_effect = _continuing_share_action(
        ActionKind.FORWARD_SPLIT, "continuing", at=split_at
    )
    if ending == "none":
        other_terms, other_effect = _same_date_effect(
            3820,
            ActionKind.REGULAR_CASH_DIVIDEND,
            (_cash(amount="1", component_id="dividend"),),
            at=other_at,
            claim_status="continuing",
            occurrence="occ-dividend",
            dates=(_date_fact("ex", other_at), _date_fact("payable", PAYABLE_AT)),
        )
    else:
        other_terms, other_effect = _same_date_effect(
            3820,
            ActionKind.CASH_ACQUISITION,
            (_cash(amount="12", component_id="acquisition"),),
            at=other_at,
            claim_status="extinguished",
            occurrence="occ-acquisition",
            dates=(_date_fact("payable", PAYABLE_AT),),
        )
    other_payload = other_effect.payload
    assert isinstance(other_payload, OccurredEffectV1)
    outcome = _outcome(
        terms=(split_terms, other_terms),
        effects=(split_effect, other_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, other_payload.action_kind),
        claim_status="extinguished",
    )
    day = EFFECT_DAY if ending == "none" else LATER_DAY
    state = _state(holdings=(_holding(quantity=100),), day=day)

    with pytest.raises(
        IndeterminateValuationError,
        match=_ended_claim_message(ActionKind.FORWARD_SPLIT, "extinguished"),
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(day))


def _ended_distribution(
    kind: ActionKind, status: str, *, at: str = EFFECT_AT, suffix: int = 3830
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    """One cash distribution on SEC_A, ex on ``at``, with its own claim status."""
    return _same_date_effect(
        suffix,
        kind,
        (_cash(amount="1", component_id="distribution"),),
        at=at,
        claim_status=status,
        occurrence="occ-ended-distribution",
        dates=(_date_fact("ex", at), _date_fact("payable", PAYABLE_AT)),
    )


def _ended_distribution_message(kind: ActionKind, status: str) -> str:
    return (
        rf"the {kind.value} occ-ended-distribution on {SEC_A} needs a continuing "
        rf"claim, but its own claim status is {status}"
    )


@pytest.mark.parametrize(
    "kind",
    [ActionKind.REGULAR_CASH_DIVIDEND, ActionKind.SPECIAL_CASH_DISTRIBUTION],
    ids=lambda kind: kind.value,
)
@pytest.mark.parametrize("status", ["extinguished", "converted"])
def test_a_cash_distribution_on_an_ended_claim_halts_an_exposed_book(
    kind: ActionKind, status: str
) -> None:
    # F1 of the PR #125 review: a dividend or special distribution pays on
    # shares that continue, yet its own claim status says the claim ended or
    # was converted. M1c classifies it supported and composes that status.
    # Before the fix it was paid as an ordinary distribution, 100 on the 100
    # shares, and the shares were kept on an ended claim.
    terms, effect = _ended_distribution(kind, status)
    outcome = _outcome(
        terms=(terms,), effects=(effect,), action_kinds=(kind,), claim_status=status
    )
    message = _ended_distribution_message(kind, status)

    held = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(IndeterminateValuationError, match=message):
        _processor().apply_pre_open_actions(held, (), (outcome,), _key())
    # A staged buy of the unheld security is exposure too.
    with pytest.raises(IndeterminateValuationError, match=message):
        _processor().apply_pre_open_actions(
            _state(), (_target(SEC_A, 10),), (outcome,), _key()
        )

    # Control: unrelated evidence does not poison a book exposed to nothing
    # in SEC_A.
    elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),))
    unchanged, _ = _processor().apply_pre_open_actions(
        elsewhere, (), (outcome,), _key()
    )
    assert unchanged is elsewhere

    # Control: the same distribution on a continuing claim is owed on 100.
    terms, effect = _ended_distribution(kind, "continuing")
    continuing = _outcome(terms=(terms,), effects=(effect,), action_kinds=(kind,))
    paid, _ = _processor().apply_pre_open_actions(held, (), (continuing,), _key())
    (claim,) = paid.pending_cash_claims
    assert (claim.entitled_quantity, claim.total_cash_expected) == (100, Decimal("100"))


@pytest.mark.parametrize(
    ("split_suffix", "distribution_suffix", "split_first"),
    [(3800, 3830, True), (3840, 3870, False)],
    ids=["split-record-first", "distribution-record-first"],
)
@pytest.mark.parametrize("exposed", [True, False], ids=["exposed", "unexposed"])
def test_a_split_then_an_ended_claim_dividend_halts_at_the_dividend(
    split_suffix: int, distribution_suffix: int, split_first: bool, exposed: bool
) -> None:
    # F1 chain: a split on EFFECT_DAY, then a dividend whose own claim status
    # is extinguished on LATER_DAY. M1c composes the claim as extinguished,
    # and the dividend is the ending effect that follows the split, so the
    # split applies in its own window. Before the fix the dividend was then
    # paid on the 200 shares and nothing ever removed them; now it halts in
    # its own window. Both record orders are covered.
    split_terms, split_effect = _continuing_share_action(
        ActionKind.FORWARD_SPLIT, "continuing", suffix=split_suffix
    )
    dividend_terms, dividend_effect = _ended_distribution(
        ActionKind.REGULAR_CASH_DIVIDEND,
        "extinguished",
        at=LATER_AT,
        suffix=distribution_suffix,
    )
    assert (content_hash(split_effect) < content_hash(dividend_effect)) is split_first
    outcome = _outcome(
        terms=(split_terms, dividend_terms),
        effects=(split_effect, dividend_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.REGULAR_CASH_DIVIDEND),
        claim_status="extinguished",
    )

    if not exposed:
        for day in (EFFECT_DAY, LATER_DAY):
            elsewhere = _state(holdings=(_holding(SEC_OTHER, quantity=5),), day=day)
            unchanged, _ = _processor().apply_pre_open_actions(
                elsewhere, (), (outcome,), _key(day)
            )
            assert unchanged is elsewhere
        return

    first = _state(holdings=(_holding(quantity=100),))
    split, _ = _processor().apply_pre_open_actions(first, (), (outcome,), _key())
    assert _quantities(split.holdings) == {SEC_A: 200}
    assert split.pending_cash_claims == ()

    later = _state(holdings=(_holding(quantity=200),), day=LATER_DAY)
    with pytest.raises(
        IndeterminateValuationError,
        match=_ended_distribution_message(
            ActionKind.REGULAR_CASH_DIVIDEND, "extinguished"
        ),
    ):
        _processor().apply_pre_open_actions(later, (), (outcome,), _key(LATER_DAY))


@pytest.mark.parametrize(
    "parent", [uid(11), SEC_OTHER], ids=["parent-first", "child-first"]
)
def test_an_ended_claim_dividend_on_a_delivered_security_halts(parent: UUID) -> None:
    # The book holds no SEC_A at the prior close, but the parent's spin-off
    # delivers 50 in this pass, and SEC_A's dividend, quoted per pre-action
    # share, says its own claim ended. Only the book the pass leaves shows
    # the exposure: a distribution is no share action, so no conflict halts
    # it first. Both dispatch orders halt.
    spin_terms, spin_effect = _same_date_effect(
        3750,
        ActionKind.SPINOFF,
        (
            _shares(
                numerator="1",
                denominator="2",
                component_id="spin",
                recipient=SEC_A,
                predecessor=parent,
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-spin",
        security_id=parent,
    )
    spin = _outcome(
        security_id=parent,
        terms=(spin_terms,),
        effects=(spin_effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )

    def dividend(status: str) -> SecurityEconomicOutcomeV1:
        terms, effect = _ended_distribution(ActionKind.REGULAR_CASH_DIVIDEND, status)
        return _outcome(terms=(terms,), effects=(effect,), claim_status=status)

    state = _state(holdings=(_holding(parent, quantity=100, basis="900"),))
    targets = (_target(parent, 100),)

    with pytest.raises(
        IndeterminateValuationError,
        match=_ended_distribution_message(
            ActionKind.REGULAR_CASH_DIVIDEND, "extinguished"
        ),
    ):
        _processor().apply_pre_open_actions(
            state, targets, (spin, dividend("extinguished")), _key()
        )

    # Control: on a continuing claim the pre-action dividend is owed on the
    # prior close's SEC_A, which is none.
    updated, _ = _processor().apply_pre_open_actions(
        state, targets, (spin, dividend("continuing")), _key()
    )
    assert _quantities(updated.holdings) == {parent: 100, SEC_A: 50}
    assert updated.pending_cash_claims == ()


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

    # On a single date the two actions still touch the acquirer twice, and
    # nothing orders them either: the pass would apply them by security id.
    # Issue 83 (round 3) refuses that too; it is no longer a control.
    same_day = _share_action_case(
        suffix=2220,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(_shares(numerator="1", denominator="1", recipient=SEC_ACQ),),
        claim_status="converted",
        effective_at=BETWEEN_AT,
    )
    with pytest.raises(
        IndeterminateValuationError, match=r"share actions on 2020-06-05 touching"
    ):
        _processor().apply_pre_open_actions(
            state, (), (same_day, split), _key(LATER_DAY)
        )


def _conversion(
    source: UUID, acquirer: UUID, effective_at: str, suffix: int
) -> SecurityEconomicOutcomeV1:
    """``source`` converts one for one into ``acquirer``."""
    share = _shares(
        numerator="1",
        denominator="1",
        recipient=acquirer,
        predecessor=source,
        component_id=f"acq-{suffix}",
    )
    terms = _terms(
        suffix=suffix,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(share,),
        security_id=source,
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=ActionKind.STOCK_ACQUISITION,
        components=(share,),
        terms=terms,
        occurrence_id=f"acq-{suffix}",
        effective_at=effective_at,
        security_id=source,
        claim_status="converted",
    )
    return _outcome(
        security_id=source,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.STOCK_ACQUISITION,),
    )


@pytest.mark.parametrize("with_split", [True, False], ids=["split", "no-split"])
def test_a_two_hop_conversion_halts_at_the_security_both_hops_touch(
    with_split: bool,
) -> None:
    # The book holds only SEC_A. On Monday SEC_A converts into SEC_ACQ and
    # SEC_ACQ into SEC_OTHER; SEC_OTHER may also split 2:1 on Friday. In date
    # order 105 SEC_A shares end as 105 SEC_OTHER; applied by security order
    # they end as 210. The chain is refused at its middle hop: SEC_ACQ is
    # touched by both Monday conversions, two share actions on one security
    # in one window, and the book holds SEC_A, which one of them acts on.
    # The split and the second conversion also touch SEC_OTHER twice, but
    # that conflict touches only SEC_ACQ and SEC_OTHER, which the prior close
    # does not hold, so the middle hop is the one refusal, split or not.
    outcomes = [
        _conversion(SEC_A, SEC_ACQ, LATER_AT, 2330),
        _conversion(SEC_ACQ, SEC_OTHER, LATER_AT, 2340),
    ]
    if with_split:
        split_terms, split_effect = _split_effect(
            SEC_OTHER, ActionKind.FORWARD_SPLIT, "2", "1", BETWEEN_AT, 2320
        )
        outcomes.append(
            _outcome(
                security_id=SEC_OTHER,
                terms=(split_terms,),
                effects=(split_effect,),
                action_kinds=(ActionKind.FORWARD_SPLIT,),
            )
        )
    state = _state(holdings=(_holding(quantity=105),), day=LATER_DAY)

    with pytest.raises(IndeterminateValuationError) as raised:
        _processor().apply_pre_open_actions(state, (), tuple(outcomes), _key(LATER_DAY))
    assert str(raised.value) == (
        f"one pre-open window holds share actions on 2020-06-08 touching "
        f"{SEC_ACQ} (stock_acquisition, stock_acquisition), and M2 V1 proves "
        "no order between share actions on one security in one window"
    )

    # Control: one hop alone touches SEC_ACQ once and simply converts.
    updated, _ = _processor().apply_pre_open_actions(
        state, (), (_conversion(SEC_A, SEC_ACQ, LATER_AT, 2330),), _key(LATER_DAY)
    )
    assert _quantities(updated.holdings) == {SEC_ACQ: 105}


def test_a_conversion_into_a_security_then_disposed_is_still_caught() -> None:
    # SEC_A converts into SEC_ACQ on Monday; SEC_ACQ split on Friday and is
    # cash-acquired on Monday. The pass leaves no SEC_ACQ, and the prior
    # close held no SEC_ACQ, yet the book is exposed through SEC_A, which one
    # of the conflicting actions delivers from.
    split_terms, split_effect = _split_effect(
        SEC_ACQ, ActionKind.FORWARD_SPLIT, "2", "1", BETWEEN_AT, 2370
    )
    cash_terms = _terms(
        suffix=2380,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12", predecessor=SEC_ACQ),),
        dates=(_date_fact("payable", PAYABLE_AT),),
        security_id=SEC_ACQ,
    )
    cash_effect = _effect(
        suffix=2381,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12", predecessor=SEC_ACQ),),
        terms=cash_terms,
        occurrence_id="occ-cash",
        effective_at=LATER_AT,
        claim_status="extinguished",
        security_id=SEC_ACQ,
    )
    acquirer = _outcome(
        security_id=SEC_ACQ,
        terms=(split_terms, cash_terms),
        effects=(split_effect, cash_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.CASH_ACQUISITION),
    )
    outcomes = (_conversion(SEC_A, SEC_ACQ, LATER_AT, 2390), acquirer)
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError, match=r"share actions on 2020-06-05, 2020-06-08"
    ):
        _processor().apply_pre_open_actions(state, (), outcomes, _key(LATER_DAY))


def test_a_disposal_beside_a_split_on_another_date_is_indeterminate() -> None:
    # SEC_A splits on Friday and is cash-acquired on Monday. The pass leaves
    # no SEC_A at all, so only the book at the prior close shows exposure.
    split_terms, split_effect = _split_effect(
        SEC_A, ActionKind.FORWARD_SPLIT, "2", "1", BETWEEN_AT, 2350
    )
    acquisition_terms = _terms(
        suffix=2360,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12"),),
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    acquisition_effect = _effect(
        suffix=2361,
        action_kind=ActionKind.CASH_ACQUISITION,
        components=(_cash(amount="12"),),
        terms=acquisition_terms,
        occurrence_id="occ-acquisition",
        effective_at=LATER_AT,
        claim_status="extinguished",
    )
    outcome = _outcome(
        terms=(split_terms, acquisition_terms),
        effects=(split_effect, acquisition_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.CASH_ACQUISITION),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError, match=r"share actions on 2020-06-05, 2020-06-08"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key(LATER_DAY))


def _same_date_effect(
    suffix: int,
    kind: ActionKind,
    components: tuple[EconomicComponentV1, ...],
    *,
    at: str,
    claim_status: str,
    occurrence: str,
    security_id: UUID = SEC_A,
    dates: tuple[EconomicDateFactV1, ...] = (),
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    terms = _terms(
        suffix=suffix,
        action_kind=kind,
        components=components,
        dates=dates,
        security_id=security_id,
    )
    effect = _effect(
        suffix=suffix + 1,
        action_kind=kind,
        components=components,
        terms=terms,
        occurrence_id=occurrence,
        effective_at=at,
        claim_status=claim_status,
        security_id=security_id,
    )
    return terms, effect


@pytest.mark.parametrize(
    ("split", "acquisition", "split_first"),
    [(3100, 3150, True), (3120, 3170, False)],
    ids=["split-dispatched-first", "acquisition-dispatched-first"],
)
def test_a_split_then_a_cash_acquisition_on_one_date_is_indeterminate(
    split: int, acquisition: int, split_first: bool
) -> None:
    # D1: a 2:1 split at 10:00 and a cash acquisition at 15:00 of one date.
    # Split first owes 2400 and realizes 1500; acquisition first owes 1200
    # and realizes 300. The pass applies them in record-hash order, and M2
    # V1 does not yet prove a same-date order from intraday effect times.
    # The two parametrizations dispatch them in opposite orders.
    split_terms, split_effect = _same_date_effect(
        split,
        ActionKind.FORWARD_SPLIT,
        (_shares(numerator="2", denominator="1", component_id="split"),),
        at="2020-06-01T10:00:00Z",
        claim_status="continuing",
        occurrence="occ-split",
    )
    cash_terms, cash_effect = _same_date_effect(
        acquisition,
        ActionKind.CASH_ACQUISITION,
        (_cash(amount="12", component_id="acquisition"),),
        at="2020-06-01T15:00:00Z",
        claim_status="extinguished",
        occurrence="occ-acquisition",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    outcome = _outcome(
        terms=(split_terms, cash_terms),
        effects=(split_effect, cash_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.CASH_ACQUISITION),
        claim_status="extinguished",
    )
    # The premise: one outcome's effects dispatch in record-hash order.
    assert (content_hash(split_effect) < content_hash(cash_effect)) is split_first
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="0")

    with pytest.raises(
        IndeterminateValuationError,
        match=r"share actions on 2020-06-01 touching .*forward_split.*cash_acquisition",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


@pytest.mark.parametrize(
    ("acquisition", "liquidation", "acquisition_first"),
    [(3200, 3210, True), (3190, 3240, False)],
    ids=["acquisition-dispatched-first", "liquidation-dispatched-first"],
)
def test_two_claim_ending_actions_on_one_date_are_indeterminate(
    acquisition: int, liquidation: int, acquisition_first: bool
) -> None:
    # D3: a cash acquisition (converted) at 10:00 and a liquidation
    # (extinguished) at 15:00 of one date. Each order owes a different claim,
    # 1200 or 1500, and nothing orders them. The two parametrizations
    # dispatch them in opposite orders.
    cash_terms, cash_effect = _same_date_effect(
        acquisition,
        ActionKind.CASH_ACQUISITION,
        (_cash(amount="12", component_id="acquisition"),),
        at="2020-06-01T10:00:00Z",
        claim_status="converted",
        occurrence="occ-acquisition",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    liquidation_terms, liquidation_effect = _same_date_effect(
        liquidation,
        ActionKind.LIQUIDATION,
        (_cash(amount="15", component_id="liquidation"),),
        at="2020-06-01T15:00:00Z",
        claim_status="extinguished",
        occurrence="occ-liquidation",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    outcome = _outcome(
        terms=(cash_terms, liquidation_terms),
        effects=(cash_effect, liquidation_effect),
        action_kinds=(ActionKind.CASH_ACQUISITION, ActionKind.LIQUIDATION),
        claim_status="extinguished",
    )
    # The premise: one outcome's effects dispatch in record-hash order.
    assert (
        content_hash(cash_effect) < content_hash(liquidation_effect)
    ) is acquisition_first
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="0")

    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"share actions on 2020-06-01 touching {SEC_A} "
            r"\(cash_acquisition, liquidation\)"
        ),
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


@pytest.mark.parametrize("predecessor", [SEC_A, SEC_OTHER])
def test_a_conversion_and_the_acquirers_disposal_on_one_date_are_indeterminate(
    predecessor: UUID,
) -> None:
    # D2: the predecessor converts 1:1 into SEC_ACQ at 10:00, and SEC_ACQ is
    # cash-acquired at 15:00, in two outcomes applied by security id. SEC_A
    # sorts before SEC_ACQ, SEC_OTHER after it. With SEC_ACQ first, the book
    # kept 100 SEC_ACQ after SEC_ACQ was cashed out and lost the 2000 owed.
    share = _shares(
        numerator="1",
        denominator="1",
        component_id="to-acquirer",
        recipient=SEC_ACQ,
        predecessor=predecessor,
    )
    conversion_terms, conversion_effect = _same_date_effect(
        3300,
        ActionKind.STOCK_ACQUISITION,
        (share,),
        at="2020-06-01T10:00:00Z",
        claim_status="converted",
        occurrence="occ-conversion",
        security_id=predecessor,
    )
    conversion = _outcome(
        security_id=predecessor,
        terms=(conversion_terms,),
        effects=(conversion_effect,),
        action_kinds=(ActionKind.STOCK_ACQUISITION,),
        claim_status="converted",
    )
    cash = _cash(amount="20", component_id="acquirer-cash", predecessor=SEC_ACQ)
    cash_terms, cash_effect = _same_date_effect(
        3310,
        ActionKind.CASH_ACQUISITION,
        (cash,),
        at="2020-06-01T15:00:00Z",
        claim_status="extinguished",
        occurrence="occ-acquirer-cash",
        security_id=SEC_ACQ,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    disposal = _outcome(
        security_id=SEC_ACQ,
        terms=(cash_terms,),
        effects=(cash_effect,),
        action_kinds=(ActionKind.CASH_ACQUISITION,),
        claim_status="extinguished",
    )
    state = _state(
        holdings=(_holding(predecessor, quantity=100, basis="900"),), cash="0"
    )

    with pytest.raises(
        IndeterminateValuationError,
        match=r"share actions on 2020-06-01 touching .*stock_acquisition",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(predecessor, 100),), (conversion, disposal), _key()
        )


def test_a_spin_off_beside_a_split_of_its_parent_is_indeterminate() -> None:
    # SEC_A splits 2:1 and spins off one SEC_CHILD per two shares on one
    # date. Spin-off first delivers 50 children, split first 100: a spin-off
    # is a share action on its parent, not only on its child.
    spin_terms, spin_effect = _same_date_effect(
        3540,
        ActionKind.SPINOFF,
        (
            _shares(
                numerator="1",
                denominator="2",
                component_id="spin",
                recipient=SEC_CHILD,
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-spin",
    )
    split_terms, split_effect = _same_date_effect(
        3550,
        ActionKind.FORWARD_SPLIT,
        (_shares(numerator="2", denominator="1", component_id="split"),),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-split",
    )
    outcome = _outcome(
        terms=(spin_terms, split_terms),
        effects=(spin_effect, split_effect),
        action_kinds=(ActionKind.SPINOFF, ActionKind.FORWARD_SPLIT),
    )
    state = _state(holdings=(_holding(quantity=100),))

    with pytest.raises(
        IndeterminateValuationError,
        match=rf"touching {SEC_A} \(forward_split, spinoff\)",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


@pytest.mark.parametrize(
    "parent", [SEC_A, SEC_OTHER], ids=["parent-first", "child-first"]
)
def test_a_spin_off_child_cashed_out_in_the_same_window_is_indeterminate(
    parent: UUID,
) -> None:
    # The parent spins off one SEC_CHILD per two shares, and SEC_CHILD is
    # cash-acquired at 12 on the same date, in another outcome. SEC_CHILD
    # sorts between SEC_A and SEC_OTHER, so the two parents dispatch the
    # outcomes in opposite orders. Child first, the book would keep 50
    # cashed-out children owed nothing; parent first, it would be owed 600.
    assert (parent.bytes < SEC_CHILD.bytes) is (parent == SEC_A)
    spin_terms, spin_effect = _same_date_effect(
        3560,
        ActionKind.SPINOFF,
        (
            _shares(
                numerator="1",
                denominator="2",
                component_id="spin",
                recipient=SEC_CHILD,
                predecessor=parent,
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-spin",
        security_id=parent,
    )
    spin = _outcome(
        security_id=parent,
        terms=(spin_terms,),
        effects=(spin_effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )
    cash_terms, cash_effect = _same_date_effect(
        3570,
        ActionKind.CASH_ACQUISITION,
        (_cash(amount="12", component_id="child-cash", predecessor=SEC_CHILD),),
        at=EFFECT_AT,
        claim_status="extinguished",
        occurrence="occ-child-cash",
        security_id=SEC_CHILD,
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    cash_out = _outcome(
        security_id=SEC_CHILD,
        terms=(cash_terms,),
        effects=(cash_effect,),
        action_kinds=(ActionKind.CASH_ACQUISITION,),
        claim_status="extinguished",
    )
    state = _state(holdings=(_holding(parent, quantity=100, basis="900"),), cash="0")

    with pytest.raises(
        IndeterminateValuationError,
        match=rf"touching {SEC_CHILD} \(cash_acquisition, spinoff\)",
    ):
        _processor().apply_pre_open_actions(state, (), (spin, cash_out), _key())


def test_a_stock_dividend_beside_a_reverse_split_is_indeterminate() -> None:
    # A one-for-four stock dividend and a 1:10 reverse split of SEC_A on one
    # date, both rounding down. 105 shares become 131 and then 13 with the
    # dividend first, 10 and then 12 with the split first: a stock dividend
    # is a share action too.
    dividend_terms, dividend_effect = _same_date_effect(
        3580,
        ActionKind.STOCK_DIVIDEND,
        (
            _shares(
                numerator="1",
                denominator="4",
                component_id="stock-dividend",
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-stock-dividend",
    )
    split_terms, split_effect = _same_date_effect(
        3590,
        ActionKind.REVERSE_SPLIT,
        (_shares(numerator="1", denominator="10", component_id="reverse-split"),),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-reverse-split",
    )
    outcome = _outcome(
        terms=(dividend_terms, split_terms),
        effects=(dividend_effect, split_effect),
        action_kinds=(ActionKind.STOCK_DIVIDEND, ActionKind.REVERSE_SPLIT),
    )
    state = _state(holdings=(_holding(quantity=105),))

    with pytest.raises(
        IndeterminateValuationError,
        match=rf"touching {SEC_A} \(reverse_split, stock_dividend\)",
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_share_actions_on_an_unheld_security_halt_a_staged_buy_of_it() -> None:
    # A 1:10 reverse split on Friday and a 3:1 split on Monday of SEC_A,
    # which the book does not hold, while it stages a buy of 105. The pass
    # would restate that target to 30 or 31 by the order it happens to pick,
    # so a staged buy is exposure to the conflict too.
    first = _split_effect(SEC_A, ActionKind.REVERSE_SPLIT, "1", "10", BETWEEN_AT, 3600)
    second = _split_effect(SEC_A, ActionKind.FORWARD_SPLIT, "3", "1", LATER_AT, 3610)
    outcome = _outcome(
        terms=(first[0], second[0]),
        effects=(first[1], second[1]),
        action_kinds=(ActionKind.REVERSE_SPLIT, ActionKind.FORWARD_SPLIT),
    )
    state = _state(day=LATER_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match=r"share actions on 2020-06-05, 2020-06-08 touching",
    ):
        _processor().apply_pre_open_actions(
            state, (_target(SEC_A, 105),), (outcome,), _key(LATER_DAY)
        )

    # Control: an explicit zero target on the unheld security trades nothing.
    unchanged, translated = _processor().apply_pre_open_actions(
        state, (_target(SEC_A, 0),), (outcome,), _key(LATER_DAY)
    )
    assert unchanged is state
    assert _quantities(translated) == {SEC_A: 0}


# --------------------------------------------------------------------------
# one dispatch order across every outcome of a pass
# --------------------------------------------------------------------------


def _distribution_effect(
    security_id: UUID,
    suffix: int,
    *,
    kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
    amount: str = "1",
    share_basis: str = "predecessor_post_action",
    with_ex_date: bool = True,
    at: str = EFFECT_AT,
) -> tuple[CorporateActionTermsVersionV1, EconomicEffectVersionV1]:
    """One cash distribution on ``security_id``, effective at ``at``.

    Its claim continues, so a liquidation here is a partial liquidating
    distribution. With an ex date, it is ex on EFFECT_DAY.
    """
    dates: tuple[EconomicDateFactV1, ...] = (_date_fact("payable", PAYABLE_AT),)
    if with_ex_date:
        dates = (_date_fact("ex", EFFECT_AT), *dates)
    return _same_date_effect(
        suffix,
        kind,
        (
            _cash(
                amount=amount,
                component_id="distribution",
                predecessor=security_id,
                share_basis=share_basis,
            ),
        ),
        at=at,
        claim_status="continuing",
        occurrence="occ-distribution",
        security_id=security_id,
        dates=dates,
    )


def _distribution(
    security_id: UUID,
    suffix: int,
    *,
    kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
    amount: str = "1",
    share_basis: str = "predecessor_post_action",
    with_ex_date: bool = True,
) -> SecurityEconomicOutcomeV1:
    """One cash distribution on EFFECT_DAY, alone in its own outcome.

    M1c composes its continuing claim as continuing.
    """
    terms, effect = _distribution_effect(
        security_id,
        suffix,
        kind=kind,
        amount=amount,
        share_basis=share_basis,
        with_ex_date=with_ex_date,
    )
    return _outcome(
        security_id=security_id,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(kind,),
    )


def _delivery_case(
    predecessor: UUID,
    acquirer_held: int,
    *,
    kind: ActionKind = ActionKind.REGULAR_CASH_DIVIDEND,
    amount: str = "1",
    share_basis: str,
) -> tuple[
    PortfolioStateV1,
    tuple[SecurityTargetPositionV1, ...],
    tuple[SecurityEconomicOutcomeV1, ...],
]:
    """The predecessor converts 1:1 into SEC_ACQ, which pays a distribution.

    Both are on EFFECT_DAY, in two outcomes. The book holds 100 of the
    predecessor and ``acquirer_held`` SEC_ACQ at the prior close, each with a
    staged hold.
    """
    conversion_terms, conversion_effect = _same_date_effect(
        3620,
        ActionKind.STOCK_ACQUISITION,
        (
            _shares(
                numerator="1",
                denominator="1",
                component_id="to-acquirer",
                recipient=SEC_ACQ,
                predecessor=predecessor,
            ),
        ),
        at=EFFECT_AT,
        claim_status="converted",
        occurrence="occ-conversion",
        security_id=predecessor,
    )
    conversion = _outcome(
        security_id=predecessor,
        terms=(conversion_terms,),
        effects=(conversion_effect,),
        action_kinds=(ActionKind.STOCK_ACQUISITION,),
        claim_status="converted",
    )
    distribution = _distribution(
        SEC_ACQ, 3630, kind=kind, amount=amount, share_basis=share_basis
    )
    holdings: tuple[SecurityHoldingV1, ...] = (
        _holding(predecessor, quantity=100, basis="900"),
    )
    targets: tuple[SecurityTargetPositionV1, ...] = (_target(predecessor, 100),)
    if acquirer_held:
        holdings += (_holding(SEC_ACQ, quantity=acquirer_held, basis="80"),)
        targets += (_target(SEC_ACQ, acquirer_held),)
    return _state(holdings=holdings, cash="0"), targets, (conversion, distribution)


@pytest.mark.parametrize(
    "predecessor", [SEC_A, SEC_OTHER], ids=["predecessor-first", "acquirer-first"]
)
@pytest.mark.parametrize("acquirer_held", [10, 0], ids=["acquirer-held", "unheld"])
@pytest.mark.parametrize(
    ("kind", "amount"),
    [(ActionKind.REGULAR_CASH_DIVIDEND, "1"), (ActionKind.LIQUIDATION, "3")],
    ids=["dividend", "liquidating"],
)
def test_a_post_action_distribution_on_delivered_shares_halts(
    predecessor: UUID, acquirer_held: int, kind: ActionKind, amount: str
) -> None:
    # N1 and N2c, ruled fail-closed in round 4: the predecessor converts
    # 100 shares 1:1 into SEC_ACQ, and SEC_ACQ quotes a distribution per
    # post-action share, ex on the same date, in another outcome. The ex-date
    # rule entitles the prior close's holdings, and M1c's share basis says
    # only what the source divides its cash by, so whether the 100 delivered
    # shares are entitled is not proven, held SEC_ACQ or not. SEC_A sorts
    # before SEC_ACQ and SEC_OTHER after it, so the two predecessors dispatch
    # the outcomes in opposite orders; both halt. The distribution used to be
    # owed on 110 (or 100) predecessor first, and on 10 (or none) acquirer
    # first, then on the 110 in both orders.
    assert (predecessor.bytes < SEC_ACQ.bytes) is (predecessor == SEC_A)
    state, targets, outcomes = _delivery_case(
        predecessor,
        acquirer_held,
        kind=kind,
        amount=amount,
        share_basis="predecessor_post_action",
    )

    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"the {kind.value} occ-distribution on {SEC_ACQ} quotes cash per "
            rf"post-action share, and the stock_acquisition occ-conversion of "
            rf"{predecessor} delivered shares into it"
        ),
    ):
        _processor().apply_pre_open_actions(state, targets, outcomes, _key())


@pytest.mark.parametrize(
    "predecessor", [SEC_A, SEC_OTHER], ids=["predecessor-first", "acquirer-first"]
)
@pytest.mark.parametrize("acquirer_held", [10, 0], ids=["acquirer-held", "unheld"])
def test_a_pre_action_distribution_is_owed_on_the_prior_close_alone(
    predecessor: UUID, acquirer_held: int
) -> None:
    # Control: quoted per pre-action share, the same distribution is owed on
    # the prior close's SEC_ACQ alone, and never on the delivered shares, in
    # both orders.
    assert (predecessor.bytes < SEC_ACQ.bytes) is (predecessor == SEC_A)
    state, targets, outcomes = _delivery_case(
        predecessor, acquirer_held, share_basis="predecessor_pre_action"
    )

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, outcomes, _key()
    )

    basis = "980" if acquirer_held else "900"
    received = 100 + acquirer_held
    assert updated.holdings == (_holding(SEC_ACQ, quantity=received, basis=basis),)
    assert [
        (claim.security_id, claim.entitled_quantity, claim.total_cash_expected)
        for claim in updated.pending_cash_claims
    ] == ([(SEC_ACQ, 10, Decimal("10"))] if acquirer_held else [])
    assert _quantities(translated) == {predecessor: 0, SEC_ACQ: received}


@pytest.mark.parametrize(
    ("kind", "amount", "owed"),
    [
        (ActionKind.REGULAR_CASH_DIVIDEND, "1", "20"),
        (ActionKind.LIQUIDATION, "3", "60"),
    ],
    ids=["dividend", "liquidating"],
)
def test_a_post_action_distribution_counts_its_own_split(
    kind: ActionKind, amount: str, owed: str
) -> None:
    # Control: a split re-denominates the prior close's own holding, so the
    # count after the security's single continuing share action is proven.
    # SEC_ACQ splits 2:1 and quotes a distribution per post-action share on
    # the same date: it is owed on the 20 shares the 10 became.
    split_terms, split_effect = _same_date_effect(
        3660,
        ActionKind.FORWARD_SPLIT,
        (
            _shares(
                numerator="2",
                denominator="1",
                component_id="split",
                recipient=SEC_ACQ,
                predecessor=SEC_ACQ,
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-split",
        security_id=SEC_ACQ,
    )
    distribution_terms, distribution_effect = _distribution_effect(
        SEC_ACQ, 3670, kind=kind, amount=amount
    )
    outcome = _outcome(
        security_id=SEC_ACQ,
        terms=(split_terms, distribution_terms),
        effects=(split_effect, distribution_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, kind),
    )
    state = _state(holdings=(_holding(SEC_ACQ, quantity=10, basis="80"),), cash="0")

    updated, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())

    assert _quantities(updated.holdings) == {SEC_ACQ: 20}
    (claim,) = updated.pending_cash_claims
    assert (claim.entitled_quantity, claim.total_cash_expected) == (20, Decimal(owed))


def _spin_off_to_child(parent: UUID) -> SecurityEconomicOutcomeV1:
    """``parent`` spins off one SEC_CHILD per two shares on EFFECT_DAY."""
    spin_terms, spin_effect = _same_date_effect(
        3640,
        ActionKind.SPINOFF,
        (
            _shares(
                numerator="1",
                denominator="2",
                component_id="spin",
                recipient=SEC_CHILD,
                predecessor=parent,
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="continuing",
        occurrence="occ-spin",
        security_id=parent,
    )
    return _outcome(
        security_id=parent,
        terms=(spin_terms,),
        effects=(spin_effect,),
        action_kinds=(ActionKind.SPINOFF,),
    )


@pytest.mark.parametrize(
    "parent", [SEC_A, SEC_OTHER], ids=["parent-first", "child-first"]
)
@pytest.mark.parametrize("child_held", [0, 4], ids=["child-unheld", "child-held"])
def test_a_post_action_distribution_on_a_spin_off_child_halts(
    parent: UUID, child_held: int
) -> None:
    # N2, ruled fail-closed in round 4: the parent spins off 50 SEC_CHILD,
    # and SEC_CHILD pays 1 per post-action share on the same date, in another
    # outcome. The book holds no child at the prior close, or 4. SEC_CHILD
    # sorts between SEC_A and SEC_OTHER, so the two parents dispatch the
    # outcomes in opposite orders. The post-action count includes the 50
    # shares the spin-off delivered, which the prior close did not hold, so
    # both orders halt. It used to be owed on 50 or 54 parent first, and on
    # nothing or 4 child first.
    assert (parent.bytes < SEC_CHILD.bytes) is (parent == SEC_A)
    holdings: tuple[SecurityHoldingV1, ...] = (
        _holding(parent, quantity=100, basis="900"),
    )
    if child_held:
        holdings += (_holding(SEC_CHILD, quantity=child_held, basis="40"),)
    state = _state(holdings=holdings, cash="0")
    spin = _spin_off_to_child(parent)

    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"the regular_cash_dividend occ-distribution on {SEC_CHILD} quotes "
            rf"cash per post-action share, and the spinoff occ-spin of {parent} "
            "delivered shares into it"
        ),
    ):
        _processor().apply_pre_open_actions(
            state, (), (spin, _distribution(SEC_CHILD, 3650)), _key()
        )

    # Control: quoted per pre-action share, it is owed on the prior close's
    # children alone, in both orders.
    pre_action = _distribution(SEC_CHILD, 3650, share_basis="predecessor_pre_action")
    updated, _ = _processor().apply_pre_open_actions(
        state, (), (spin, pre_action), _key()
    )
    assert _quantities(updated.holdings) == {parent: 100, SEC_CHILD: 50 + child_held}
    assert [
        (claim.security_id, claim.total_cash_expected)
        for claim in updated.pending_cash_claims
    ] == ([(SEC_CHILD, Decimal(child_held))] if child_held else [])


@pytest.mark.parametrize(
    "removal", ["cash_acquisition", "conversion", "final_liquidation"]
)
def test_a_post_action_distribution_on_a_removed_holding_halts(removal: str) -> None:
    # Ruled fail-closed in round 4: the book holds 100 SEC_A at the prior
    # close. SEC_A quotes a distribution per post-action share at 09:00, ex
    # that date, and its own outcome removes the holding at 15:00: a cash
    # acquisition or a conversion after a dividend, or the final
    # extinguishing liquidation after a continuing instalment. M1c composes
    # each as the removal's status. The post-action count is not defined, and
    # the distribution used to be dropped without a word.
    kind = ActionKind.REGULAR_CASH_DIVIDEND
    amount = "1"
    dates: tuple[EconomicDateFactV1, ...] = (_date_fact("payable", PAYABLE_AT),)
    status = "extinguished"
    components: tuple[EconomicComponentV1, ...]
    if removal == "cash_acquisition":
        removing_kind = ActionKind.CASH_ACQUISITION
        components = (_cash(amount="12", component_id="acquisition"),)
    elif removal == "conversion":
        removing_kind = ActionKind.STOCK_ACQUISITION
        components = (
            _shares(
                numerator="1",
                denominator="1",
                component_id="to-acquirer",
                recipient=SEC_ACQ,
            ),
        )
        dates = ()
        status = "converted"
    else:
        kind = removing_kind = ActionKind.LIQUIDATION
        amount = "3"
        components = (_cash(amount="15", component_id="final"),)
    removing_terms, removing_effect = _same_date_effect(
        3680,
        removing_kind,
        components,
        at="2020-06-01T15:00:00Z",
        claim_status=status,
        occurrence="occ-removal",
        dates=dates,
    )

    def outcome(share_basis: str) -> SecurityEconomicOutcomeV1:
        terms, effect = _distribution_effect(
            SEC_A,
            3690,
            kind=kind,
            amount=amount,
            share_basis=share_basis,
            at="2020-06-01T09:00:00Z",
        )
        return _outcome(
            terms=(terms, removing_terms),
            effects=(effect, removing_effect),
            action_kinds=(kind, removing_kind),
            claim_status=status,
        )

    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="0")
    targets = (_target(SEC_A, 100),)

    with pytest.raises(
        IndeterminateValuationError,
        match=(
            rf"the {kind.value} occ-distribution on {SEC_A} quotes cash per "
            rf"post-action share, and the {removing_kind.value} occ-removal "
            "removed the holding"
        ),
    ):
        _processor().apply_pre_open_actions(
            state, targets, (outcome("predecessor_post_action"),), _key()
        )

    # Control: quoted per pre-action share, it is owed on the prior close's
    # 100 shares beside whatever the removal owes.
    updated, _ = _processor().apply_pre_open_actions(
        state, targets, (outcome("predecessor_pre_action"),), _key()
    )
    (owed,) = (
        claim
        for claim in updated.pending_cash_claims
        if claim.component_id == "distribution"
    )
    assert (owed.security_id, owed.action_kind) == (SEC_A, kind)
    assert owed.entitled_quantity == 100
    assert owed.total_cash_expected == Decimal(amount) * 100
    assert SEC_A not in _quantities(updated.holdings)


@pytest.mark.parametrize(
    "parent", [SEC_A, SEC_OTHER], ids=["parent-first", "child-first"]
)
def test_an_undated_distribution_on_a_spin_off_child_halts_in_either_order(
    parent: UUID,
) -> None:
    # N5: as above, but the child's distribution has no ex date. The book
    # holds the child once the spin-off has run, so in both orders the
    # distribution is evidence about it and halts; child first, it used to
    # find no child held and complete.
    assert (parent.bytes < SEC_CHILD.bytes) is (parent == SEC_A)
    state = _state(holdings=(_holding(parent, quantity=100, basis="900"),), cash="0")
    outcomes = (
        _spin_off_to_child(parent),
        _distribution(SEC_CHILD, 3650, with_ex_date=False),
    )

    with pytest.raises(IndeterminateValuationError, match="requires a source ex date"):
        _processor().apply_pre_open_actions(state, (), outcomes, _key())


@pytest.mark.parametrize("shape", ["delivered", "removed"])
def test_an_unknown_basis_distribution_halt_names_the_basis_it_quotes(
    shape: str,
) -> None:
    # N1 (issue 117): a distribution quoted on the as_reported_unknown share
    # basis beside a delivery into its holding, or a removal of it, halts,
    # and the halt names the basis actually quoted. It used to say the
    # source quotes cash per post-action share, which it does not.
    if shape == "delivered":
        state, targets, outcomes = _delivery_case(
            SEC_A, 10, share_basis="as_reported_unknown"
        )
        security, action = SEC_ACQ, "stock_acquisition occ-conversion"
    else:
        removing_terms, removing_effect = _same_date_effect(
            3700,
            ActionKind.CASH_ACQUISITION,
            (_cash(amount="12", component_id="acquisition"),),
            at="2020-06-01T15:00:00Z",
            claim_status="extinguished",
            occurrence="occ-removal",
            dates=(_date_fact("payable", PAYABLE_AT),),
        )
        terms, effect = _distribution_effect(
            SEC_A,
            3710,
            share_basis="as_reported_unknown",
            at="2020-06-01T09:00:00Z",
        )
        outcomes = (
            _outcome(
                terms=(terms, removing_terms),
                effects=(effect, removing_effect),
                action_kinds=(
                    ActionKind.REGULAR_CASH_DIVIDEND,
                    ActionKind.CASH_ACQUISITION,
                ),
                claim_status="extinguished",
            ),
        )
        state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="0")
        targets = (_target(SEC_A, 100),)
        security, action = SEC_A, "cash_acquisition occ-removal"

    with pytest.raises(IndeterminateValuationError) as raised:
        _processor().apply_pre_open_actions(state, targets, outcomes, _key())

    message = str(raised.value)
    assert message.startswith(
        f"the regular_cash_dividend occ-distribution on {security} quotes cash "
        "per share on the as_reported_unknown share basis, and the "
        f"{action} "
    )
    assert "per post-action share" not in message


@pytest.mark.parametrize(
    "parent", [SEC_A, SEC_OTHER], ids=["parent-first", "child-first"]
)
def test_a_spin_off_delivering_no_whole_child_share_leaves_its_count_proven(
    parent: UUID,
) -> None:
    # N2 (issue 117): one parent share, one child per two, rounded down, so
    # the spin-off delivers no child share. The child's post-action count is
    # then the prior close's 4, and its post-action dividend is owed on
    # them. Recording a delivery that never happened would halt it.
    state = _state(
        holdings=(
            _holding(parent, quantity=1, basis="9"),
            _holding(SEC_CHILD, quantity=4, basis="40"),
        ),
        cash="0",
    )
    targets = (_target(parent, 1), _target(SEC_CHILD, 4))
    outcomes = (_spin_off_to_child(parent), _distribution(SEC_CHILD, 3720))

    updated, translated = _processor().apply_pre_open_actions(
        state, targets, outcomes, _key()
    )

    assert _quantities(updated.holdings) == {parent: 1, SEC_CHILD: 4}
    assert _quantities(translated) == {parent: 1, SEC_CHILD: 4}
    (claim,) = updated.pending_cash_claims
    assert (claim.security_id, claim.entitled_quantity, claim.total_cash_expected) == (
        SEC_CHILD,
        4,
        Decimal("4"),
    )


@pytest.mark.parametrize(
    "parent", [SEC_A, SEC_OTHER], ids=["parent-first", "child-first"]
)
def test_an_ended_claim_spin_off_leaves_a_child_only_book_alone(
    parent: UUID,
) -> None:
    # F3 of the PR #125 review: the ended-claim rule judges exposure to the
    # acted security, not to every security the action touches. The parent's
    # spin-off says its own claim ended, but the book holds only 4 SEC_CHILD
    # and no parent, so the spin-off delivers it nothing. The child's
    # post-action dividend is owed on those 4, and the pass completes.
    spin_terms, spin_effect = _same_date_effect(
        3730,
        ActionKind.SPINOFF,
        (
            _shares(
                numerator="1",
                denominator="2",
                component_id="spin",
                recipient=SEC_CHILD,
                predecessor=parent,
                meaning="additional_per_predecessor",
            ),
        ),
        at=EFFECT_AT,
        claim_status="extinguished",
        occurrence="occ-spin",
        security_id=parent,
    )
    spin = _outcome(
        security_id=parent,
        terms=(spin_terms,),
        effects=(spin_effect,),
        action_kinds=(ActionKind.SPINOFF,),
        claim_status="extinguished",
    )
    state = _state(holdings=(_holding(SEC_CHILD, quantity=4, basis="40"),), cash="0")
    targets = (_target(SEC_CHILD, 4),)

    updated, _ = _processor().apply_pre_open_actions(
        state, targets, (spin, _distribution(SEC_CHILD, 3740)), _key()
    )

    assert _quantities(updated.holdings) == {SEC_CHILD: 4}
    (claim,) = updated.pending_cash_claims
    assert (claim.security_id, claim.entitled_quantity, claim.total_cash_expected) == (
        SEC_CHILD,
        4,
        Decimal("4"),
    )


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


def test_a_continuing_liquidation_beside_a_share_action_on_another_date() -> None:
    # A liquidating distribution on a continuing claim erases no share, so it
    # shares a window with Monday's split exactly as a dividend does.
    split_terms, split_effect = _split_effect(
        SEC_A, ActionKind.FORWARD_SPLIT, "2", "1", LATER_AT, 2280
    )
    liquidation_terms = _terms(
        suffix=2290,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        dates=(_date_fact("ex", BETWEEN_AT), _date_fact("payable", PAYABLE_AT)),
    )
    liquidation_effect = _effect(
        suffix=2291,
        action_kind=ActionKind.LIQUIDATION,
        components=(_cash(amount="7"),),
        terms=liquidation_terms,
        occurrence_id="occ-liquidation",
        effective_at=BETWEEN_AT,
    )
    outcome = _outcome(
        terms=(split_terms, liquidation_terms),
        effects=(split_effect, liquidation_effect),
        action_kinds=(ActionKind.FORWARD_SPLIT, ActionKind.LIQUIDATION),
    )
    state = _state(holdings=(_holding(quantity=100),), day=LATER_DAY)

    updated, _ = _processor().apply_pre_open_actions(
        state, (), (outcome,), _key(LATER_DAY)
    )

    assert _quantities(updated.holdings) == {SEC_A: 200}
    assert updated.pending_cash_claims[0].total_cash_expected == Decimal("700")


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


@pytest.mark.parametrize(
    ("unmodelled_at", "disposal_at", "day"),
    [
        ("2020-06-01T10:00:00Z", "2020-06-01T15:00:00Z", EFFECT_DAY),
        (BETWEEN_AT, LATER_AT, LATER_DAY),
    ],
    ids=["one-date", "two-dates"],
)
@pytest.mark.parametrize(
    ("disposal", "owed", "realized"),
    [("liquidation", "1500", "600"), ("cash_acquisition", "1200", "300")],
)
@pytest.mark.parametrize(
    "kind", [ActionKind.CONVERSION, ActionKind.BANKRUPTCY_REORGANIZATION]
)
def test_an_unmodelled_action_beside_a_disposal_of_its_security_halts(
    kind: ActionKind,
    disposal: str,
    owed: str,
    realized: str,
    unmodelled_at: str,
    disposal_at: str,
    day: date,
) -> None:
    # N3: the book holds 100 SEC_A at a basis of 900. A share action with no
    # M2 accounting rule converts SEC_A into SEC_OTHER, and a disposal of
    # SEC_A follows in the same window, which M1c composes as extinguished.
    # The disposal leaves no SEC_A in the book the pass leaves, so the
    # unmodelled action is judged against the prior close's book too. It
    # used to complete, owing the disposal's cash and realizing PnL on shares
    # whose fate the unmodelled action leaves unproven.
    share = _shares(
        numerator="1", denominator="1", component_id="unmodelled", recipient=SEC_OTHER
    )
    unmodelled_terms, unmodelled_effect = _same_date_effect(
        3660,
        kind,
        (share,),
        at=unmodelled_at,
        claim_status="converted",
        occurrence="occ-unmodelled",
    )
    if disposal == "liquidation":
        disposal_kind = ActionKind.LIQUIDATION
        cash = _cash(amount="15", component_id="liquidation")
    else:
        disposal_kind = ActionKind.CASH_ACQUISITION
        cash = _cash(amount="12", component_id="acquisition")
    disposal_terms, disposal_effect = _same_date_effect(
        3670,
        disposal_kind,
        (cash,),
        at=disposal_at,
        claim_status="extinguished",
        occurrence="occ-disposal",
        dates=(_date_fact("payable", PAYABLE_AT),),
    )
    state = _state(holdings=(_holding(quantity=100, basis="900"),), cash="0", day=day)
    targets = (_target(SEC_A, 100),)
    message = f"corporate action kind {kind.value} has no proven M2 accounting rule"

    both = _outcome(
        terms=(unmodelled_terms, disposal_terms),
        effects=(unmodelled_effect, disposal_effect),
        action_kinds=(kind, disposal_kind),
        claim_status="extinguished",
    )
    with pytest.raises(IndeterminateValuationError, match=message):
        _processor().apply_pre_open_actions(state, targets, (both,), _key(day))
    # A holding is exposure at the prior close whatever is staged for it: a
    # sale to 0, or no target at all.
    for staged in ((_target(SEC_A, 0),), ()):
        with pytest.raises(IndeterminateValuationError, match=message):
            _processor().apply_pre_open_actions(state, staged, (both,), _key(day))
    # A staged buy with no holding is exposure at the prior close too, and
    # the disposal zeroes it.
    unheld = _state(cash="0", day=day)
    with pytest.raises(IndeterminateValuationError, match=message):
        _processor().apply_pre_open_actions(unheld, targets, (both,), _key(day))

    # Without the disposal the book the pass leaves still holds SEC_A, and
    # the unmodelled action halts it as it always did.
    alone = _outcome(
        terms=(unmodelled_terms,),
        effects=(unmodelled_effect,),
        action_kinds=(kind,),
        claim_status="converted",
    )
    with pytest.raises(IndeterminateValuationError, match=message):
        _processor().apply_pre_open_actions(state, targets, (alone,), _key(day))

    # Control: the disposal alone applies, and realizes its gain.
    disposed = _outcome(
        terms=(disposal_terms,),
        effects=(disposal_effect,),
        action_kinds=(disposal_kind,),
        claim_status="extinguished",
    )
    updated, translated = _processor().apply_pre_open_actions(
        state, targets, (disposed,), _key(day)
    )
    assert updated.holdings == ()
    assert updated.pending_claims_value == Decimal(owed)
    assert updated.realized_net_pnl == Decimal(realized)
    assert _quantities(translated) == {SEC_A: 0}
    unchanged, translated = _processor().apply_pre_open_actions(
        unheld, targets, (disposed,), _key(day)
    )
    assert unchanged is unheld
    assert _quantities(translated) == {SEC_A: 0}


def test_an_unmodelled_action_halts_a_staged_buy_in_a_later_window() -> None:
    # SEC_A converts into SEC_OTHER on EFFECT_DAY under an action kind with
    # no M2 accounting rule, while the book holds no SEC_A. At LATER_DAY's
    # pre-open the book stages a buy of 10 SEC_A. An unmodelled action is
    # judged in every pass, whatever its effective date, so buying the
    # converted security halts.
    terms, effect = _same_date_effect(
        3700,
        ActionKind.CONVERSION,
        (
            _shares(
                numerator="1",
                denominator="1",
                component_id="unmodelled",
                recipient=SEC_OTHER,
            ),
        ),
        at=EFFECT_AT,
        claim_status="converted",
        occurrence="occ-unmodelled",
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.CONVERSION,),
        claim_status="converted",
    )
    processor = _processor()
    flat = _state(cash="1000")
    first, _ = processor.apply_pre_open_actions(flat, (), (outcome,), _key())
    assert first is flat

    later = _state(cash="1000", day=LATER_DAY)
    with pytest.raises(
        IndeterminateValuationError,
        match="corporate action kind conversion has no proven M2 accounting rule",
    ):
        processor.apply_pre_open_actions(
            later, (_target(SEC_A, 10),), (outcome,), _key(LATER_DAY)
        )

    # Control: without a staged buy the book is not exposed to SEC_A.
    unchanged, _ = processor.apply_pre_open_actions(
        later, (_target(SEC_A, 0),), (outcome,), _key(LATER_DAY)
    )
    assert unchanged is later


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


def _with_an_incomplete_pre_window_record(
    suffix: int,
) -> SecurityEconomicOutcomeV1:
    """A dividend on EFFECT_DAY, beside an old record M1c places before the window.

    The old record is a split with no proven consideration: fine to ignore,
    since it is never applied, and it must not halt a run by being read.
    """
    terms, effect, _ = _dividend_case(
        amount="0.5",
        suffix=suffix,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    old_terms = _terms(
        suffix=suffix + 10,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(_shares(numerator="2", denominator="1", component_id="old"),),
    )
    old = _effect(
        suffix=suffix + 11,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(),
        terms=old_terms,
        occurrence_id="old-1",
        effective_at="2019-06-03T00:00:00Z",
        consideration_status="unknown",
    )
    return _outcome(
        terms=(terms, old_terms),
        effects=(effect, old),
        statuses=("effective", "before_window"),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND, ActionKind.FORWARD_SPLIT),
    )


def test_an_incomplete_pre_window_record_never_halts_a_paid_dividend() -> None:
    # The dividend is owed, recorded, delivered and settled. Every later
    # session reads that delivery again, finds no pending claim, and checks
    # the evidence explains it. Reading the old incomplete record must not
    # halt the run the session after the dividend is paid.
    outcome = _with_an_incomplete_pre_window_record(2720)
    state = _state(holdings=(_holding(quantity=100),), cash="1000")
    staged, _ = _processor().apply_pre_open_actions(state, (), (outcome,), _key())
    settled = _processor().apply_intrasession_settlements(
        _payable_state(staged), (outcome,), _key(PAYABLE_DAY)
    )
    assert settled.cash_balance == Decimal("1050.0")

    again = _processor().apply_intrasession_settlements(
        settled, (outcome,), _key(PAYABLE_DAY)
    )

    assert again is settled


def test_an_incomplete_pre_window_record_never_halts_an_unowed_delivery() -> None:
    outcome = _with_an_incomplete_pre_window_record(2740)
    # Bought after the ex date, so owed nothing.
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state


def test_an_incomplete_pre_window_record_explains_nothing() -> None:
    # Control: a delivery that only the incomplete record could explain is
    # still unexplained, so the run halts rather than taking it as unowed.
    outcome = _with_an_incomplete_pre_window_record(2760)
    unexplained = _outcome(
        terms=outcome.terms_records,
        effects=outcome.effect_records,
        statuses=("effective", "before_window"),
        delivery_groups=(
            _delivery(
                components=(_cash(amount="1", component_id="old"),),
                occurrence_id="old-1",
            ),
        ),
        action_kinds=(ActionKind.REGULAR_CASH_DIVIDEND, ActionKind.FORWARD_SPLIT),
    )
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (unexplained,), _key(PAYABLE_DAY)
        )


def test_a_duplicated_pre_window_record_explains_nothing() -> None:
    # Two reports M1c places before the window, of one occurrence and kind,
    # that disagree on what is owed: cash-1 against cash-2. Neither can be
    # taken as proof, so a delivery of cash-1 is not explained by either.
    terms, first, _ = _dividend_case(
        amount="0.5",
        suffix=2780,
        dates=(_date_fact("ex", BEFORE_CLOCK_AT), _date_fact("payable", PAYABLE_AT)),
    )
    first = _effect(
        suffix=2781,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5"),),
        terms=terms,
        effective_at=BEFORE_CLOCK_AT,
    )
    second = _effect(
        suffix=2782,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5", component_id="cash-2"),),
        terms=terms,
        effective_at=BEFORE_CLOCK_AT,
    )
    delivery = _delivery(components=(_cash(amount="0.5"),))
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    # Control: one such report explains the delivery.
    single = _outcome(
        terms=(terms,),
        effects=(first,),
        statuses=("before_window",),
        delivery_groups=(delivery,),
    )
    assert (
        _processor().apply_intrasession_settlements(state, (single,), _key(PAYABLE_DAY))
        is state
    )

    duplicated = _outcome(
        terms=(terms,),
        effects=(first, second),
        statuses=("before_window", "before_window"),
        delivery_groups=(delivery,),
    )
    with pytest.raises(
        IndeterminateValuationError,
        match="matches no pending claim and no proven entitlement",
    ):
        _processor().apply_intrasession_settlements(
            state, (duplicated,), _key(PAYABLE_DAY)
        )


def test_a_pre_window_copy_of_an_effective_report_adds_no_explanation() -> None:
    # One occurrence reported twice: once effective, once before the window.
    # The effective report alone explains the delivery; the old copy must not
    # become a second explanation that makes the delivery ambiguous.
    terms, effective, _ = _dividend_case(
        amount="0.5",
        suffix=2800,
        dates=(_date_fact("ex", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
    )
    copy = _effect(
        suffix=2802,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
        components=(_cash(amount="0.5"),),
        terms=terms,
        effective_at=BEFORE_CLOCK_AT,
    )
    outcome = _outcome(
        terms=(terms,),
        effects=(effective, copy),
        statuses=("effective", "before_window"),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    # Bought after the ex date, so owed nothing.
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)

    settled = _processor().apply_intrasession_settlements(
        state, (outcome,), _key(PAYABLE_DAY)
    )

    assert settled is state


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
