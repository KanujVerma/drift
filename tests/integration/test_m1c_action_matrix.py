"""Fixed-action and adversarial M1c integration acceptance matrix."""

# ruff: noqa: E402, I001

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

_UNIT_FIXTURES = Path(__file__).parents[1] / "unit"
if str(_UNIT_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_UNIT_FIXTURES))

_INTEGRATION_FIXTURES = Path(__file__).parent
if str(_INTEGRATION_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_FIXTURES))

from economic_test_support import (
    bounded_boundary,
    cash_component,
    closed_liquidation_case,
    duplicate_report,
    economic_evidence,
    effect_record,
    exact_boundary,
    identity_assignment,
    rebind_record_evidence,
    revise_record,
    second_installment,
    settlement_record,
    terms_record,
    uid,
    validated_case,
    EconomicHarness,
)
from test_m1b_identity_history import canonical_query, canonical_task3_context

from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicDateFactV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    DeliveredSettlementV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
    OccurredEffectV1,
    ResidualClaimV1,
    TermsPayloadV1,
    UnknownEffectV1,
    classify_economic_shape,
)
from drift.domain.economic_results import EconomicOutcomeResolutionV1
from drift.domain.assertions import M1bSelectionPurpose
from drift.domain.securities import ListingTerminationStatus
from drift.markets.economic_outcomes import (
    resolve_economic_facts,
    verify_economic_outcome,
)
from drift.markets.economic_selection import (
    decision_reference,
    outcome_reference,
    project_market_facts,
    resolve_decision_records,
    resolve_decision_projections,
    resolve_outcome_records,
    select_market_records,
)
from drift.markets.identity import (
    resolve_listing_history_coverage,
    resolve_listing_termination,
)
from drift.serialization.canonical import content_hash


def _replace[T: EconomicRecordV1](record: T, **updates: object) -> T:
    """Re-seal a fixture record after changing source-reported semantics."""
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values.update(updates)
    return rebind_record_evidence(type(record), values)


def _share(
    recipient: int,
    numerator: str,
    denominator: str,
    meaning: Literal["resulting_per_predecessor", "additional_per_predecessor"],
    *,
    component_id: str = "shares",
    fraction: Literal["fraction_issued", "round_up", "unknown"] = "round_up",
) -> ShareComponentV1:
    """State one sourced exact share entitlement without numerical conversion."""
    evidence, _ = economic_evidence(
        f"matrix {component_id} {numerator}/{denominator} {meaning} {fraction}"
    )
    treatment = (
        FractionTreatmentV1(kind="unknown")
        if fraction == "unknown"
        else FractionTreatmentV1(
            kind=fraction,
            source_rule=f"source states {fraction}",
            evidence_reference=evidence,
        )
    )
    return ShareComponentV1(
        kind="shares",
        component_id=component_id,
        recipient=EconomicRecipientV1(kind="security", security_id=uid(recipient)),
        ratio=PositiveRatioV1(numerator=numerator, denominator=denominator),
        ratio_meaning=meaning,
        unit_basis=EconomicShareBasisV1(
            security_id=uid(21), share_basis="predecessor_pre_action"
        ),
        fraction_treatment=treatment,
        applicability="ordinary_passive_holder",
        conditions=(),
    )


def _terms(
    suffix: int,
    kind: ActionKind,
    components: tuple[
        CashComponentV1 | ShareComponentV1 | UnsupportedPropertyComponentV1, ...
    ],
    *,
    dates: tuple[EconomicDateFactV1, ...] = (),
    payload_kind: Literal["fixed", "incomplete", "unsupported"] = "fixed",
    reason: str | None = None,
    known_at: str = "2020-05-01T00:00:00Z",
    scheduled_at: str = "2020-06-01T00:00:00Z",
) -> CorporateActionTermsVersionV1:
    base = terms_record(
        suffix, action_kind=kind, known_at=known_at, scheduled_at=scheduled_at
    )
    return _replace(
        base,
        payload=TermsPayloadV1(
            kind=payload_kind,
            action_kind=kind,
            components=components,
            dates=dates,
            conditions=(),
            reason=reason,
        ),
    )


def _effect(
    suffix: int,
    kind: ActionKind,
    components: tuple[CashComponentV1 | ShareComponentV1, ...],
    claim_status: Literal["continuing", "converted", "extinguished", "unknown"],
    *,
    consideration_status: Literal[
        "components", "explicit_none", "unknown"
    ] = "components",
    effective_at: str = "2020-06-01T00:00:00Z",
    terms_association: EconomicAssociationV1 | None = None,
) -> EconomicEffectVersionV1:
    base = effect_record(suffix, effective_at=effective_at, claim_status=claim_status)
    return _replace(
        base,
        terms_association=(
            EconomicAssociationV1(kind="unknown", reason="source did not name parent")
            if terms_association is None
            else terms_association
        ),
        payload=OccurredEffectV1(
            kind="occurred",
            action_kind=kind,
            claim_status=claim_status,
            consideration_status=consideration_status,
            owed_components=components,
            residual=ResidualClaimV1(
                kind="unknown", reason="source does not close residual"
            ),
            evidence_reference=base.revision.source_artifact,
        ),
    )


def _settlement(
    suffix: int,
    kind: ActionKind,
    components: tuple[CashComponentV1 | ShareComponentV1, ...],
    occurrence_id: str,
    *,
    settled_at: str = "2020-06-15T00:00:00Z",
    terms_association: EconomicAssociationV1 | None = None,
) -> EconomicSettlementVersionV1:
    base = settlement_record(suffix, occurrence_id=occurrence_id, settled_at=settled_at)
    return _replace(
        base,
        terms_association=(
            EconomicAssociationV1(kind="unknown", reason="source did not name parent")
            if terms_association is None
            else terms_association
        ),
        payload=DeliveredSettlementV1(
            kind="delivered",
            action_kind=kind,
            delivered_components=components,
            residual=ResidualClaimV1(
                kind="unknown", reason="source does not close residual"
            ),
            evidence_reference=base.revision.source_artifact,
        ),
    )


def _outcome(case: EconomicHarness) -> EconomicOutcomeResolutionV1:
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    verify_economic_outcome(result, case.context, case.source_policy)
    return result


def test_m1c_may_announcement_june_split() -> None:
    terms = _terms(
        7001,
        ActionKind.FORWARD_SPLIT,
        (_share(21, "2", "1", "resulting_per_predecessor"),),
    )
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.upcoming_terms_hashes == (content_hash(terms),)
    assert result.effect_projections == () and result.delivery_groups == ()


def test_m1c_announced_then_cancelled() -> None:
    terms = terms_record(7002)
    cancelled = _replace(
        effect_record(7003, kind="cancelled_action"),
        terms_association=EconomicAssociationV1(
            kind="identified", target=terms.source_key
        ),
    )
    result = _outcome(validated_case((terms, cancelled)))
    assert result.cancelled_action_hashes == (content_hash(cancelled),)
    association = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(cancelled)
        and item.association_field == "terms"
    )
    assert association.status == "resolved"
    assert association.selected_target_hash == content_hash(terms)
    assert result.claim_status == "unknown"
    assert result.effect_projections == () and result.delivery_groups == ()


def test_m1c_forward_reverse_and_fractions() -> None:
    forward = _terms(
        7004,
        ActionKind.FORWARD_SPLIT,
        (_share(21, "2", "1", "resulting_per_predecessor"),),
    )
    reverse = _terms(
        7005,
        ActionKind.REVERSE_SPLIT,
        (_share(21, "1", "10", "resulting_per_predecessor", fraction="round_up"),),
    )
    forward_case = validated_case((forward,))
    reverse_case = validated_case((reverse,))
    forward_query = forward_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    reverse_query = reverse_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    forward_result = resolve_economic_facts(
        forward_query, forward_case.context, forward_case.source_policy
    )
    reverse_result = resolve_economic_facts(
        reverse_query, reverse_case.context, reverse_case.source_policy
    )
    forward_projection = next(
        item
        for item in project_market_facts(
            forward_query, forward_case.context, forward_case.source_policy
        )
        if item.source_record_hash == content_hash(forward)
    )
    reverse_projection = next(
        item
        for item in project_market_facts(
            reverse_query, reverse_case.context, reverse_case.source_policy
        )
        if item.source_record_hash == content_hash(reverse)
    )
    first = forward_projection.known_components[0]
    second = reverse_projection.known_components[0]
    assert forward_result.selected_terms_hashes == (content_hash(forward),)
    assert reverse_result.selected_terms_hashes == (content_hash(reverse),)
    assert forward_result.support_status == reverse_result.support_status == "supported"
    assert isinstance(first, ShareComponentV1) and isinstance(second, ShareComponentV1)
    assert (
        first.ratio.numerator,
        first.ratio.denominator,
        first.ratio_meaning,
    ) == ("2", "1", "resulting_per_predecessor")
    assert (
        second.ratio.numerator,
        second.ratio.denominator,
        second.ratio_meaning,
        second.fraction_treatment.kind,
        second.fraction_treatment.source_rule,
    ) == (
        "1",
        "10",
        "resulting_per_predecessor",
        "round_up",
        "source states round_up",
    )


def test_m1c_regular_and_special_due_bill() -> None:
    evidence, _ = economic_evidence("independent ex record payable due-bill dates")
    dates = (
        EconomicDateFactV1(
            role="ex", boundary=exact_boundary("2020-06-20T00:00:00Z", evidence)
        ),
        EconomicDateFactV1(
            role="record", boundary=exact_boundary("2020-06-10T00:00:00Z", evidence)
        ),
        EconomicDateFactV1(
            role="payable", boundary=exact_boundary("2020-06-05T00:00:00Z", evidence)
        ),
        EconomicDateFactV1(
            role="due_bill_start",
            boundary=exact_boundary("2020-06-01T00:00:00Z", evidence),
        ),
    )
    regular = _terms(
        7006, ActionKind.REGULAR_CASH_DIVIDEND, (cash_component("3"),), dates=dates
    )
    special = _terms(7007, ActionKind.SPECIAL_CASH_DISTRIBUTION, (cash_component("7"),))
    regular_case = validated_case((regular,))
    special_case = validated_case((special,))
    regular_query = regular_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    special_query = special_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    regular_result = resolve_economic_facts(
        regular_query, regular_case.context, regular_case.source_policy
    )
    special_result = resolve_economic_facts(
        special_query, special_case.context, special_case.source_policy
    )
    regular_reference = outcome_reference(
        regular_query, regular_case.context, regular_case.source_policy
    )
    selected = resolve_outcome_records(
        regular_reference,
        regular_query,
        {content_hash(regular): regular},
        regular_case.context,
        regular_case.source_policy,
    )
    selected_regular = selected[content_hash(regular)]
    assert isinstance(selected_regular, CorporateActionTermsVersionV1)
    assert selected_regular.payload is not None
    selected_dates = {
        item.role: item.boundary.lower_bound for item in selected_regular.payload.dates
    }
    assert selected_dates == {
        "ex": datetime(2020, 6, 20, tzinfo=UTC),
        "record": datetime(2020, 6, 10, tzinfo=UTC),
        "payable": datetime(2020, 6, 5, tzinfo=UTC),
        "due_bill_start": datetime(2020, 6, 1, tzinfo=UTC),
    }
    payable = selected_dates["payable"]
    ex_date = selected_dates["ex"]
    assert payable is not None and ex_date is not None
    assert payable < ex_date
    assert regular_result.selected_terms_hashes == (content_hash(regular),)
    assert special_result.selected_terms_hashes == (content_hash(special),)
    special_projection = next(
        item
        for item in project_market_facts(
            special_query, special_case.context, special_case.source_policy
        )
        if item.source_record_hash == content_hash(special)
    )
    special_cash = special_projection.known_components[0]
    assert isinstance(special_cash, CashComponentV1) and special_cash.amount == "7"
    assert regular_result.delivery_groups == special_result.delivery_groups == ()
    assert regular_result.effect_projections == special_result.effect_projections == ()


def test_m1c_late_bounded_dates() -> None:
    base = effect_record(
        7008,
        effective_at="2020-05-31T00:00:00Z",
        known_at="2020-06-02T00:00:00Z",
    )
    effect = _replace(
        base,
        effective_time=bounded_boundary(
            "2020-05-31T00:00:00Z",
            "2020-06-02T00:00:00Z",
            base.revision.source_artifact,
        ),
    )
    case = validated_case((effect,), through="2020-06-01T00:00:00Z")
    query = case.decision_query(
        "2020-07-01T00:00:00Z", "2020-07-01T00:00:00Z", "2020-06-01T00:00:00Z"
    )
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert len(result.effect_projections) == 1
    projection = result.effect_projections[0]
    assert projection.source_record_hash == content_hash(effect)
    assert projection.effective_status == "indeterminate"
    assert projection.claim_status == "continuing"
    assert result.claim_status == "unknown"
    assert "economic_time_indeterminate" in result.reasons
    assert "source_revision_selection_unresolved" not in result.reasons


def test_m1c_same_security_stock_dividend() -> None:
    dividend = _terms(
        7009,
        ActionKind.STOCK_DIVIDEND,
        (_share(21, "1", "10", "additional_per_predecessor"),),
    )
    _outcome(validated_case((dividend,)))
    assert classify_economic_shape(dividend) == "supported"


def test_m1c_cash_agreement_without_completion() -> None:
    agreement = _terms(7010, ActionKind.CASH_ACQUISITION, (cash_component("11"),))
    result = _outcome(validated_case((agreement,)))
    assert result.selected_terms_hashes == (content_hash(agreement),)
    assert result.delivery_groups == () and result.effect_projections == ()


def test_m1c_completed_cash_stock_mixed() -> None:
    cash_effect = _effect(
        7011, ActionKind.CASH_ACQUISITION, (cash_component("9"),), "extinguished"
    )
    cash_link = EconomicAssociationV1(kind="identified", target=cash_effect.source_key)
    cash_delivery = _replace(
        _settlement(
            7012,
            ActionKind.CASH_ACQUISITION,
            (cash_component("9"),),
            "cash-payment",
        ),
        effect_association=cash_link,
    )
    cash_result = _outcome(validated_case((cash_effect, cash_delivery)))
    assert cash_result.claim_status == "extinguished"
    assert cash_result.effect_projections[0].source_record_hash == content_hash(
        cash_effect
    )
    cash_owed = cash_result.effect_projections[0].owed_components[0]
    cash_paid = cash_result.delivery_groups[0].delivered_components[0]
    assert isinstance(cash_owed, CashComponentV1) and cash_owed.amount == "9"
    assert isinstance(cash_paid, CashComponentV1) and cash_paid.amount == "9"
    assert cash_result.delivery_groups[0].contributing_record_hashes == (
        content_hash(cash_delivery),
    )

    stock_effect = _effect(
        7012,
        ActionKind.STOCK_ACQUISITION,
        (_share(22, "3", "2", "resulting_per_predecessor"),),
        "converted",
    )
    stock_link = EconomicAssociationV1(
        kind="identified", target=stock_effect.source_key
    )
    stock_delivery = _replace(
        _settlement(
            7013,
            ActionKind.STOCK_ACQUISITION,
            (_share(22, "3", "2", "resulting_per_predecessor"),),
            "stock-payment",
        ),
        effect_association=stock_link,
    )
    stock_result = _outcome(validated_case((stock_effect, stock_delivery)))
    assert stock_result.claim_status == "converted"
    stock_owed = stock_result.effect_projections[0].owed_components[0]
    stock_paid = stock_result.delivery_groups[0].delivered_components[0]
    for component in (stock_owed, stock_paid):
        assert isinstance(component, ShareComponentV1)
        assert component.recipient.security_id == uid(22)
        assert (component.ratio.numerator, component.ratio.denominator) == ("3", "2")
        assert component.ratio_meaning == "resulting_per_predecessor"
    assert stock_result.effect_projections[0].source_record_hash == content_hash(
        stock_effect
    )
    assert stock_result.delivery_groups[0].contributing_record_hashes == (
        content_hash(stock_delivery),
    )

    mixed_effect = _effect(
        7013,
        ActionKind.MIXED_ACQUISITION,
        (cash_component("4"), _share(22, "1", "2", "resulting_per_predecessor")),
        "converted",
    )
    mixed_link = EconomicAssociationV1(
        kind="identified", target=mixed_effect.source_key
    )
    mixed_delivery = _replace(
        _settlement(
            7014,
            ActionKind.MIXED_ACQUISITION,
            (
                cash_component("4"),
                _share(22, "1", "2", "resulting_per_predecessor"),
            ),
            "mixed-payment",
        ),
        effect_association=mixed_link,
    )
    mixed_result = _outcome(validated_case((mixed_effect, mixed_delivery)))
    assert mixed_result.claim_status == "converted"
    for components in (
        mixed_result.effect_projections[0].owed_components,
        mixed_result.delivery_groups[0].delivered_components,
    ):
        assert len(components) == 2
        cash = next(item for item in components if isinstance(item, CashComponentV1))
        shares = next(item for item in components if isinstance(item, ShareComponentV1))
        assert cash.amount == "4"
        assert shares.recipient.security_id == uid(22)
        assert (shares.ratio.numerator, shares.ratio.denominator) == ("1", "2")
        assert shares.ratio_meaning == "resulting_per_predecessor"
    assert mixed_result.effect_projections[0].source_record_hash == content_hash(
        mixed_effect
    )
    assert mixed_result.delivery_groups[0].contributing_record_hashes == (
        content_hash(mixed_delivery),
    )


def test_m1c_elective_prorated_formula() -> None:
    base = terms_record(7015)
    conditional = cash_component("5").model_copy(
        update={
            "applicability": "conditional",
            "conditions": (
                "formula-priced consideration",
                "holder election",
                "proration may apply",
            ),
        }
    )
    with pytest.raises(
        ValidationError, match="fixed terms require ordinary passive holder components"
    ):
        TermsPayloadV1(
            kind="fixed",
            action_kind=ActionKind.CASH_ACQUISITION,
            components=(conditional,),
            dates=(),
            conditions=(),
        )
    elective = _replace(
        base,
        payload=TermsPayloadV1(
            kind="unsupported",
            action_kind=ActionKind.CASH_ACQUISITION,
            components=(conditional,),
            dates=(),
            conditions=(),
            reason="election, proration, and formula vary consideration",
        ),
    )
    case = validated_case((elective,))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    projection = next(
        item
        for item in project_market_facts(query, case.context, case.source_policy)
        if item.source_record_hash == content_hash(elective)
    )
    retained = projection.known_components[0]
    assert classify_economic_shape(elective) == "unsupported"
    assert result.selected_terms_hashes == (content_hash(elective),)
    assert result.support_status == "unsupported"
    assert projection.component_role == "terms"
    assert projection.fact_status == "terms"
    assert projection.claim_status == "unknown"
    assert isinstance(retained, CashComponentV1)
    assert retained.amount == "5" and retained.applicability == "conditional"
    assert retained.conditions == (
        "formula-priced consideration",
        "holder election",
        "proration may apply",
    )
    assert result.effect_projections == () and result.delivery_groups == ()


def test_m1c_spinoff_and_excluded_property() -> None:
    spinoff = _effect(
        7015,
        ActionKind.SPINOFF,
        (_share(22, "1", "4", "additional_per_predecessor"),),
        "continuing",
    )
    evidence, _ = economic_evidence("REIT right receipt remains excluded property")
    right = UnsupportedPropertyComponentV1(
        kind="unsupported_property",
        component_id="reit-right",
        recipient=EconomicRecipientV1(
            kind="unresolved_property",
            source_property_key="REIT-right",
            reason="not a security identity",
        ),
        source_description="one REIT right",
        reason="M1c does not value right",
        evidence_reference=evidence,
    )
    spinoff_result = _outcome(validated_case((spinoff,)))
    spinoff_projection = spinoff_result.effect_projections[0]
    spinoff_share = spinoff_projection.owed_components[0]
    assert spinoff_result.claim_status == "continuing"
    assert spinoff_projection.source_record_hash == content_hash(spinoff)
    assert isinstance(spinoff_share, ShareComponentV1)
    assert spinoff_share.recipient.security_id == uid(22)
    assert (spinoff_share.ratio.numerator, spinoff_share.ratio.denominator) == (
        "1",
        "4",
    )
    assert spinoff_share.ratio_meaning == "additional_per_predecessor"

    excluded = _terms(
        7017,
        ActionKind.RIGHTS_WARRANTS_CVR,
        (right,),
        payload_kind="unsupported",
        reason="right has no supported security recipient",
    )
    excluded_case = validated_case((excluded,))
    excluded_query = excluded_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    excluded_result = resolve_economic_facts(
        excluded_query, excluded_case.context, excluded_case.source_policy
    )
    excluded_projection = next(
        item
        for item in project_market_facts(
            excluded_query, excluded_case.context, excluded_case.source_policy
        )
        if item.source_record_hash == content_hash(excluded)
    )
    retained_property = excluded_projection.known_components[0]
    assert excluded_result.selected_terms_hashes == (content_hash(excluded),)
    assert excluded_result.support_status == "unsupported"
    assert excluded_projection.component_role == "terms"
    assert excluded_projection.fact_status == "terms"
    assert excluded_projection.claim_status == "unknown"
    assert isinstance(retained_property, UnsupportedPropertyComponentV1)
    assert retained_property.source_description == "one REIT right"
    assert retained_property.recipient.source_property_key == "REIT-right"
    assert excluded_result.claim_status == "unknown"
    assert excluded_result.effect_projections == ()
    assert excluded_result.delivery_groups == ()


def test_m1c_fixed_conversion() -> None:
    conversion = _effect(
        7017,
        ActionKind.CONVERSION,
        (_share(22, "3", "2", "resulting_per_predecessor"),),
        "converted",
    )
    result = _outcome(validated_case((conversion,)))
    component = result.effect_projections[0].owed_components[0]
    assert result.claim_status == "converted"
    assert result.effect_projections[0].source_record_hash == content_hash(conversion)
    assert isinstance(component, ShareComponentV1)
    assert component.recipient.kind == "security"
    assert component.recipient.security_id == uid(22)
    assert (component.ratio.numerator, component.ratio.denominator) == ("3", "2")
    assert component.ratio_meaning == "resulting_per_predecessor"


def test_m1c_delisted_claim_continues() -> None:
    m1b = canonical_task3_context()
    listing_id = uid(5)
    evaluation_time = datetime(2022, 1, 4, tzinfo=UTC)
    coverage_query = canonical_query(
        m1b,
        "listing_history_coverage",
        M1bSelectionPurpose.LISTING_LIFECYCLE,
        {"listing_id": listing_id},
        evaluation_time,
    )
    coverage = resolve_listing_history_coverage(
        listing_id,
        m1b.coverage,
        coverage_query,
        m1b.bundle,
        m1b.manifests["listing_history_coverage"],
        m1b.decisions["listing_history_coverage"],
        m1b.policy,
        {},
    )
    termination_query = canonical_query(
        m1b,
        "listing_termination",
        M1bSelectionPurpose.LISTING_TERMINATION,
        {"listing_id": listing_id},
        evaluation_time,
    )
    termination = resolve_listing_termination(
        listing_id,
        m1b.terminations,
        coverage,
        termination_query,
        m1b.bundle,
        m1b.manifests["listing_termination"],
        m1b.decisions["listing_termination"],
        m1b.policy,
        {},
        coverage_versions=m1b.coverage,
        coverage_manifest=m1b.manifests["listing_history_coverage"],
        coverage_decision=m1b.decisions["listing_history_coverage"],
    )
    assert termination.status is ListingTerminationStatus.TERMINATED
    assert termination.selected_termination_record_hash is not None
    selected_termination = next(
        record
        for record in m1b.terminations
        if content_hash(record) == termination.selected_termination_record_hash
    )
    terminated_at = selected_termination.effective_time.upper_bound
    assert terminated_at == datetime(2021, 12, 31, tzinfo=UTC)
    assert terminated_at < evaluation_time

    continuing = _replace(
        _effect(
            7018,
            ActionKind.LIQUIDATION,
            (cash_component("2"),),
            "continuing",
            effective_at="2022-01-03T00:00:00Z",
        ),
        listing_id=listing_id,
    )
    listing_assignment = identity_assignment(
        70181,
        5,
        identity_kind="listing",
        ended_at="2021-12-31T00:00:00Z",
    )
    case = validated_case(
        (continuing,),
        through="2022-01-04T00:00:00Z",
        coverage_snapshot_at="2022-01-05T00:00:00Z",
        identity_assignments=(
            identity_assignment(70180, 21),
            listing_assignment,
        ),
    )
    query = case.outcome_query("2022-01-04T00:00:00Z", "2022-01-05T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    verify_economic_outcome(result, case.context, case.source_policy)
    listing_ended_at = (
        None
        if listing_assignment.effective_interval.end is None
        else listing_assignment.effective_interval.end.upper_bound
    )
    claim_effective_at = continuing.effective_time.lower_bound
    assert listing_ended_at == terminated_at
    assert claim_effective_at == datetime(2022, 1, 3, tzinfo=UTC)
    assert terminated_at is not None and claim_effective_at is not None
    assert terminated_at < claim_effective_at <= query.economic_horizon
    assert query.economic_horizon == evaluation_time
    assert all(item.status == "complete" for item in result.coverage_results)
    assert continuing.listing_id == termination.listing_id
    assert result.claim_status == "continuing"
    assert len(result.effect_projections) == 1
    projection = result.effect_projections[0]
    assert projection.source_record_hash == content_hash(continuing)
    assert projection.effective_status == "effective"
    assert projection.claim_status == "continuing"
    assert projection.consideration_status == "components"


def test_m1c_zero_vs_unknown_cancellation() -> None:
    base = effect_record(7019, claim_status="extinguished")
    explicit_none = _replace(
        base,
        payload=OccurredEffectV1(
            kind="occurred",
            action_kind=ActionKind.BANKRUPTCY_REORGANIZATION,
            claim_status="extinguished",
            consideration_status="explicit_none",
            owed_components=(),
            residual=ResidualClaimV1(kind="unknown", reason="no cash source claim"),
            evidence_reference=base.revision.source_artifact,
        ),
    )
    unknown = _replace(
        effect_record(7020, kind="unknown"),
        payload=UnknownEffectV1(
            kind="unknown",
            action_kind=ActionKind.BANKRUPTCY_REORGANIZATION,
            reason="bankruptcy outcome unknown",
        ),
    )
    explicit_result = _outcome(validated_case((explicit_none,)))
    unknown_result = _outcome(validated_case((unknown,)))
    assert classify_economic_shape(explicit_none) == "supported"
    assert explicit_result.claim_status == "extinguished"
    assert explicit_result.support_status == "supported"
    assert explicit_result.effect_projections[0].source_record_hash == content_hash(
        explicit_none
    )
    assert explicit_result.effect_projections[0].consideration_status == "explicit_none"
    assert explicit_result.effect_projections[0].owed_components == ()
    assert explicit_result.delivery_groups == ()
    assert classify_economic_shape(unknown) == "indeterminate"
    assert unknown_result.unknown_effect_hashes == (content_hash(unknown),)
    assert unknown_result.claim_status == "unknown"
    assert unknown_result.support_status == "indeterminate"
    assert unknown_result.effect_projections == ()
    assert unknown_result.delivery_groups == ()


def test_m1c_liquidation_installments_and_residual() -> None:
    first = _settlement(
        7021, ActionKind.LIQUIDATION, (cash_component("2"),), "liquidation-a"
    )
    second = _settlement(
        7022,
        ActionKind.LIQUIDATION,
        (cash_component("3"),),
        "liquidation-b",
        settled_at="2020-07-15T00:00:00Z",
    )
    result = _outcome(validated_case((first, second)))
    by_occurrence = {
        group.native_occurrence_id: group for group in result.delivery_groups
    }
    assert set(by_occurrence) == {"liquidation-a", "liquidation-b"}
    first_group = by_occurrence["liquidation-a"]
    second_group = by_occurrence["liquidation-b"]
    first_cash = first_group.delivered_components[0]
    second_cash = second_group.delivered_components[0]
    assert isinstance(first_cash, CashComponentV1) and first_cash.amount == "2"
    assert isinstance(second_cash, CashComponentV1) and second_cash.amount == "3"
    assert first_group.contributing_record_hashes == (content_hash(first),)
    assert second_group.contributing_record_hashes == (content_hash(second),)
    assert first_group.residual_status == second_group.residual_status == "unknown"
    assert result.evidence_completeness == "partial"
    assert "settlement_residual_unresolved" in result.reasons


def test_m1c_corrected_installment() -> None:
    original = settlement_record(7023, amount="5", occurrence_id="corrected-payment")
    corrected = revise_record(
        original,
        7024,
        "2020-07-01T00:00:00Z",
        {
            "payload": DeliveredSettlementV1(
                kind="delivered",
                action_kind=ActionKind.REGULAR_CASH_DIVIDEND,
                delivered_components=(cash_component("4"),),
                residual=ResidualClaimV1(
                    kind="unknown", reason="source does not close residual"
                ),
                evidence_reference=original.revision.source_artifact,
            )
        },
    )
    result = _outcome(validated_case((original, corrected)))
    assert len(result.delivery_groups) == 1
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1) and component.amount == "4"


def test_m1c_duplicate_report() -> None:
    original = settlement_record(7025, occurrence_id="corroborated")
    duplicate = duplicate_report(original, 7026)
    result = _outcome(validated_case((original, duplicate)))
    assert len(result.delivery_groups) == 1 and set(
        result.delivery_groups[0].contributing_record_hashes
    ) == {content_hash(original), content_hash(duplicate)}


def test_m1c_equal_date_equal_amount_distinct() -> None:
    original = settlement_record(7027, occurrence_id="first-equal")
    distinct = second_installment(original, 7028, "second-equal")
    result = _outcome(validated_case((original, distinct)))
    assert {group.native_occurrence_id for group in result.delivery_groups} == {
        "first-equal",
        "second-equal",
    }


def test_m1c_missing_terms_known_payment() -> None:
    payment = settlement_record(7029, amount="4", occurrence_id="orphan-payment")
    result = _outcome(validated_case((payment,)))
    assert len(result.delivery_groups) == 1
    group = result.delivery_groups[0]
    component = group.delivered_components[0]
    assert group.native_occurrence_id == "orphan-payment"
    assert group.contributing_record_hashes == (content_hash(payment),)
    assert isinstance(component, CashComponentV1) and component.amount == "4"
    assert result.evidence_completeness == "partial"


def test_m1c_conflicting_association() -> None:
    foreign = _replace(terms_record(7030), security_id=uid(22))
    payment = _replace(
        settlement_record(7031, occurrence_id="conflicted"),
        terms_association=EconomicAssociationV1(
            kind="identified", target=foreign.source_key
        ),
    )
    result = _outcome(validated_case((foreign, payment)))
    terms_link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "terms"
    )
    assert terms_link.status == "conflicting"
    assert terms_link.selected_target_hash is None
    assert terms_link.reasons == ("association_target_security_mismatch",)
    assert payment.terms_association.target == foreign.source_key
    assert len(result.delivery_groups) == 1
    assert result.delivery_groups[0].contributing_record_hashes == (
        content_hash(payment),
    )
    assert result.evidence_completeness == "partial"


def test_m1c_security_attribution_corrected() -> None:
    initial = settlement_record(7032, occurrence_id="attribution")
    corrected = revise_record(
        initial, 7033, "2020-07-01T00:00:00Z", {"security_id": uid(22)}
    )
    history_a = validated_case(
        (initial, corrected),
        security_id=uid(21),
        through="2020-06-20T00:00:00Z",
        coverage_snapshot_at="2020-07-02T00:00:00Z",
    )
    history_b = validated_case(
        (initial, corrected),
        security_id=uid(22),
        through="2020-06-20T00:00:00Z",
        coverage_snapshot_at="2020-07-02T00:00:00Z",
    )
    old_query = history_a.decision_query(
        "2020-06-20T00:00:00Z",
        "2020-06-20T00:00:00Z",
        "2020-06-20T00:00:00Z",
    )
    later_a_query = history_a.outcome_query(
        "2020-06-20T00:00:00Z", "2020-07-02T00:00:00Z"
    )
    later_b_query = history_b.outcome_query(
        "2020-06-20T00:00:00Z", "2020-07-02T00:00:00Z"
    )
    old_proof = select_market_records(
        old_query, history_a.context, history_a.source_policy
    )
    old = resolve_economic_facts(old_query, history_a.context, history_a.source_policy)
    corrected_a = resolve_economic_facts(
        later_a_query, history_a.context, history_a.source_policy
    )
    corrected_b = resolve_economic_facts(
        later_b_query, history_b.context, history_b.source_policy
    )
    assert content_hash(initial) in old_proof.revision_selected_record_hashes
    assert content_hash(corrected) not in old_proof.revision_selected_record_hashes
    assert old.delivery_groups == ()
    assert old.uncomposed_settlement_hashes == (content_hash(initial),)
    assert "source_coverage_incomplete" in old.reasons
    assert corrected_a.delivery_groups == ()
    assert len(corrected_b.delivery_groups) == 1
    assert corrected_b.delivery_groups[0].security_id == uid(22)
    assert corrected_b.delivery_groups[0].contributing_record_hashes == (
        content_hash(corrected),
    )
    assert (
        content_hash(initial)
        not in corrected_b.delivery_groups[0].contributing_record_hashes
    )


def test_m1c_coverage_missing_or_wrong_class() -> None:
    case = validated_case(())
    source_policy = case.source_policy.model_copy(
        update={"action_kinds": (ActionKind.REGULAR_CASH_DIVIDEND,)}
    )
    query = case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    ).model_copy(
        update={
            "action_kinds": (ActionKind.REGULAR_CASH_DIVIDEND,),
            "source_selection_policy_hash": content_hash(source_policy),
        }
    )
    result = resolve_economic_facts(query, case.context, source_policy)
    assert {
        item.family: (item.status, item.occurrence_identity_supported, item.reasons)
        for item in result.coverage_results
    } == {
        "terms": ("partial", False, ("coverage_action_classes_mismatch",)),
        "effect": ("partial", False, ("coverage_action_classes_mismatch",)),
        "settlement": ("partial", False, ("coverage_action_classes_mismatch",)),
    }
    assert result.selected_terms_hashes == ()
    assert result.effect_projections == ()
    assert result.cancelled_action_hashes == ()
    assert result.unknown_effect_hashes == ()
    assert result.delivery_groups == ()
    assert result.uncomposed_settlement_hashes == ()
    assert result.claim_status == "unknown"
    assert result.evidence_completeness == "unknown"
    assert result.support_status == "indeterminate"
    assert result.reasons == ("source_coverage_incomplete",)


def test_m1c_selected_value_substitution() -> None:
    terms = terms_record(7035)
    substituted = terms_record(70350)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    reference = decision_reference(query, case.context, case.source_policy)
    with pytest.raises(ValueError, match="record hash"):
        resolve_decision_records(
            reference,
            query,
            {content_hash(terms): substituted},
            case.context,
            case.source_policy,
        )


def test_m1c_forged_dependent_outcome() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.effect_projections
    genuine_projection = result.effect_projections[0]
    assert genuine_projection.claim_status == "continuing"
    forged_projection = genuine_projection.model_copy(
        update={"claim_status": "extinguished"}
    )
    forged = result.model_copy(
        update={
            "effect_projections": (
                forged_projection,
                *result.effect_projections[1:],
            )
        }
    )
    assert forged.safe_projection_hashes == result.safe_projection_hashes
    assert forged.effect_projections[0].source_record_hash == (
        genuine_projection.source_record_hash
    )
    assert forged.effect_projections[0].claim_status != genuine_projection.claim_status
    with pytest.raises(ValueError, match="exact replay"):
        verify_economic_outcome(forged, case.context, case.source_policy)


def test_m1c_outcome_into_decision() -> None:
    terms = terms_record(7036)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    decision = case.decision_query(
        "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    outcome = case.outcome_query("2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z")
    reference = outcome_reference(outcome, case.context, case.source_policy)
    with pytest.raises(TypeError, match="decision reference"):
        resolve_decision_projections(
            reference,  # type: ignore[arg-type]
            decision,
            {},
            case.context,
            case.source_policy,
        )


def test_m1c_later_decision_uses_known_realization() -> None:
    payment = settlement_record(7037, occurrence_id="past-payment")
    case = validated_case((payment,), through="2020-07-01T00:00:00Z")
    query = case.decision_query(
        "2020-07-01T00:00:00Z", "2020-07-01T00:00:00Z", "2020-07-01T00:00:00Z"
    )
    proof = select_market_records(query, case.context, case.source_policy)
    assert content_hash(payment) in proof.raw_materializable_record_hashes


def test_m1c_earlier_effective_cutoff() -> None:
    effect = effect_record(7038, effective_at="2020-06-01T00:00:00Z")
    case = validated_case((effect,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-07-01T00:00:00Z", "2020-07-01T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.claim_status == "unknown"
    assert result.effect_projections[0].effective_status == "upcoming"


def test_m1c_prior_payment_then_no_further_consideration() -> None:
    terms = _terms(7039, ActionKind.LIQUIDATION, (cash_component("5"),))
    link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    paid = _settlement(
        7040,
        ActionKind.LIQUIDATION,
        (cash_component("5"),),
        "prior-payment",
        terms_association=link,
    )
    none = _effect(
        7041,
        ActionKind.LIQUIDATION,
        (),
        "extinguished",
        consideration_status="explicit_none",
        terms_association=link,
        effective_at="2020-07-01T00:00:00Z",
    )
    result = _outcome(validated_case((terms, paid, none)))
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1) and component.amount == "5"
    assert result.claim_status == "extinguished" and all(
        not isinstance(value, CashComponentV1) or value.amount != "0"
        for effect in result.effect_projections
        for value in effect.owed_components
    )
