"""Unit tests for M2 Task 4 corporate-action and economic outcome accounting."""

from datetime import date
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
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
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

EFFECT_AT = "2020-06-01T00:00:00Z"
PAYABLE_AT = "2020-06-15T00:00:00Z"
LATER_AT = "2020-06-08T00:00:00Z"

ZERO = Decimal("0")


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------


def _key(day: date = EFFECT_DAY) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


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
        session_key=_key(day),
        cash_balance=cash_value,
        holdings=holdings,
        pending_cash_claims=claims,
        settled_claim_ids=tuple(sorted(settled)),
        is_marked=False,
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
        (_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT))
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

    kernel = PortfolioAccountingKernel(updated)
    kernel.mark_close({SEC_A: Decimal("10"), SEC_CHILD: Decimal("4")})
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
    rule = _due_bill_rule(terms, entitlement=date(2020, 6, 9), redemption=LATER_DAY)
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

    entitled_state = _state(holdings=(_holding(quantity=100),), day=date(2020, 6, 9))
    entitled, _ = processor.apply_pre_open_actions(
        entitled_state, (), (outcome,), _key(date(2020, 6, 9))
    )
    assert len(entitled.pending_cash_claims) == 1
    claim = entitled.pending_cash_claims[0]
    assert claim.entitlement_session == date(2020, 6, 9)
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
    kernel = PortfolioAccountingKernel(state)
    kernel.advance_session(_key(PAYABLE_DAY))
    return kernel.state


def test_delivered_cash_without_a_pending_claim_commits_zero_cash() -> None:
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    state = _state(holdings=(_holding(quantity=100),), cash="1000", day=PAYABLE_DAY)
    settled = _processor().apply_intrasession_settlements(
        state, (delivered,), _key(PAYABLE_DAY)
    )
    assert settled is state
    assert settled.cash_balance == Decimal("1000")


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
    kernel = PortfolioAccountingKernel(staged)
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


def test_dividend_without_a_source_record_date_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="2", suffix=370, dates=(_date_fact("payable", PAYABLE_AT),)
    )
    state = _state(holdings=(_holding(quantity=100),))
    with pytest.raises(
        IndeterminateValuationError, match="requires a source record date"
    ):
        _processor().apply_pre_open_actions(state, (), (outcome,), _key())


def test_dividend_without_a_source_payable_date_is_indeterminate() -> None:
    _, _, outcome = _dividend_case(
        amount="2", suffix=380, dates=(_date_fact("record", EFFECT_AT),)
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
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
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
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
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
        _state(holdings=(_holding(quantity=100, basis="1000"),), cash="500")
    )
    kernel.mark_close({SEC_A: Decimal("10")})
    marked = kernel.state
    assert marked.is_marked is True
    updated, _ = _processor().apply_pre_open_actions(marked, (), (outcome,), _key())
    assert updated.holdings[0].quantity == 200
    assert updated.is_marked is False
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
        dates=(_date_fact("record", EFFECT_AT), interval),
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
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
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
        dates=(_date_fact("record", EFFECT_AT), _date_fact("payable", PAYABLE_AT)),
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


def test_two_claims_on_one_component_make_delivery_ambiguous() -> None:
    # Exactly the hazard the in-flight claim-identity change removes: one
    # entitlement whose payable date was revised currently mints two ids.
    # Settling either one on a single delivered report would be a guess.
    first = _manual_claim(payable=PAYABLE_DAY)
    second = _manual_claim(payable=LATER_DAY)
    state = _state(claims=(first, second), cash="100", day=PAYABLE_DAY)
    delivered = _outcome(
        effects=(),
        delivery_groups=(_delivery(components=(_cash(amount="0.5"),)),),
    )
    with pytest.raises(
        IndeterminateValuationError,
        match="matches more than one pending claim",
    ):
        _processor().apply_intrasession_settlements(
            state, (delivered,), _key(PAYABLE_DAY)
        )


def _manual_claim(*, payable: date) -> PendingCashClaimV1:
    per_share = Decimal("0.5")
    return PendingCashClaimV1(
        claim_id=pending_cash_claim_id(
            security_id=SEC_A,
            action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
            occurrence_id="occ-1",
            component_id="cash-1",
            entitlement_session=EFFECT_DAY,
            payable_session=payable,
        ),
        security_id=SEC_A,
        action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
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
