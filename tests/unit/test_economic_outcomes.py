"""Association, coverage and replay tests for composed M1c economic outcomes."""

import pytest
from economic_test_support import (
    bounded_boundary,
    bounded_effect_record,
    cash_component,
    closed_liquidation_case,
    duplicate_report,
    economic_evidence,
    effect_record,
    exact_boundary,
    identity_assignment,
    known_unsupported_case,
    mixed_settlement_case,
    rebind_record_evidence,
    revise_record,
    second_installment,
    settlement_record,
    terms_record,
    uid,
    validated_case,
)

from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.economic_common import (
    ActionKind,
    CashComponentV1,
    EconomicAssociationV1,
    EconomicOccurrenceV1,
    EconomicRecipientV1,
    EconomicShareBasisV1,
    EconomicSourceKeyV1,
    FractionTreatmentV1,
    PositiveRatioV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_coverage import DatasetBindingV1
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
    OccurredEffectV1,
    ResidualClaimV1,
)
from drift.domain.economic_results import (
    CashEconomicValueV1,
    EconomicAssociationValueV1,
    EconomicBoundaryValueV1,
    EconomicRecipientValueV1,
    EconomicResidualValueV1,
    FractionEconomicValueV1,
    PropertyEconomicValueV1,
    ShareEconomicValueV1,
)
from drift.domain.temporal import SourcePrecision
from drift.markets.economic_outcomes import (
    _COMPOSITION_SPEC,
    boundary_economic_value_v1,
    component_economic_value_v1,
    residual_economic_value_v1,
    resolve_economic_facts,
    settlement_occurrence_payload_v1,
    verify_economic_outcome,
)
from drift.markets.economic_selection import (
    outcome_reference,
    project_market_facts,
    resolve_outcome_projections,
)
from drift.markets.economic_validation import (
    EconomicResolutionContext,
    economic_context_hash,
)
from drift.serialization.canonical import content_hash


def test_duplicate_report_is_one_delivery_but_two_installments_are_two() -> None:
    first = settlement_record(300)
    duplicate = duplicate_report(first, 301)
    second = second_installment(first, 302, "payment-2")
    case = validated_case((first, duplicate, second))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.delivery_groups) == 2
    assert sorted(
        len(group.contributing_record_hashes) for group in result.delivery_groups
    ) == [1, 2]
    amounts = []
    for group in result.delivery_groups:
        component = group.delivered_components[0]
        assert isinstance(component, CashComponentV1)
        amounts.append(component.amount)
    assert amounts == ["5", "5"]
    assert result.evidence_completeness == "partial"


def test_later_action_closure_preserves_prior_payment_and_completes_evidence() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.claim_status == "extinguished"
    assert result.evidence_completeness == "known"
    assert len(result.delivery_groups) == 1
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"
    assert result.residual_resolutions
    assert all(item.status == "closed" for item in result.residual_resolutions)


def test_wrong_action_scope_does_not_close_known_payment_residual() -> None:
    case = closed_liquidation_case(wrong_scope=True)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"
    assert any(item.status != "closed" for item in result.residual_resolutions)
    assert result.evidence_completeness == "partial"


def test_known_unsupported_property_is_not_missing_evidence() -> None:
    case = known_unsupported_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert (result.evidence_completeness, result.support_status) == (
        "known",
        "unsupported",
    )


def _with_associations[T: EconomicRecordV1](record: T, **updates: object) -> T:
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values.update(updates)
    return rebind_record_evidence(type(record), values)


def test_exact_parent_links_resolve_without_installment_id_equality() -> None:
    terms = terms_record(400)
    effect = effect_record(401)
    effect = _with_associations(
        effect,
        terms_association=EconomicAssociationV1(
            kind="identified", target=terms.source_key
        ),
    )
    payment = settlement_record(402, occurrence_id="installment-a")
    payment = _with_associations(
        payment,
        terms_association=EconomicAssociationV1(
            kind="identified", target=terms.source_key
        ),
        effect_association=EconomicAssociationV1(
            kind="identified", target=effect.source_key
        ),
    )
    case = validated_case((terms, effect, payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.associations) == 3
    assert all(item.status == "resolved" for item in result.associations)
    assert {item.selected_target_hash for item in result.associations} == {
        content_hash(terms),
        content_hash(effect),
    }
    assert result.delivery_groups[0].native_occurrence_id == "installment-a"


def test_definite_parent_security_mismatch_conflicts_but_keeps_payment() -> None:
    foreign_terms = terms_record(410)
    foreign_terms = _with_associations(foreign_terms, security_id=uid(22))
    payment = settlement_record(411, amount="4")
    payment = _with_associations(
        payment,
        terms_association=EconomicAssociationV1(
            kind="identified", target=foreign_terms.source_key
        ),
    )
    case = validated_case((foreign_terms, payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    terms_link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "terms"
    )
    assert terms_link.status == "conflicting"
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "4"
    assert result.evidence_completeness == "partial"


def test_settlement_after_horizon_is_not_composed_as_a_delivery() -> None:
    paid = settlement_record(430, amount="5", occurrence_id="paid")
    future = settlement_record(
        431,
        amount="9",
        occurrence_id="future",
        settled_at="2021-02-01T00:00:00Z",
        known_at="2021-02-01T00:00:00Z",
    )
    case = validated_case((paid, future), through="2021-01-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-02-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert [
        component.amount
        for group in result.delivery_groups
        for component in group.delivered_components
        if isinstance(component, CashComponentV1)
    ] == ["5"]


def test_same_time_outstanding_assertion_prevents_action_closure() -> None:
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    terms = next(
        record
        for record in records
        if isinstance(record, CorporateActionTermsVersionV1)
    )
    association = EconomicAssociationV1(kind="identified", target=terms.source_key)
    tied = effect_record(
        605,
        claim_status="extinguished",
        effective_at="2020-07-01T00:00:00Z",
    )
    assert isinstance(tied.payload, OccurredEffectV1)
    tied = _with_associations(
        tied,
        terms_association=association,
        payload=tied.payload.model_copy(
            update={
                "action_kind": ActionKind.LIQUIDATION,
                "residual": ResidualClaimV1(
                    kind="outstanding",
                    scope_action=association,
                    reason="same-time report says consideration is outstanding",
                ),
            }
        ),
    )
    case = validated_case((*records, tied))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert any(item.status != "closed" for item in result.residual_resolutions)
    assert result.evidence_completeness == "partial"


def test_cash_comparison_ignores_report_metadata_and_preserves_multiplicity() -> None:
    first = settlement_record(440)
    assert first.payload is not None
    source_cash = first.payload.delivered_components[0]
    assert isinstance(source_cash, CashComponentV1)
    first = _with_associations(
        first,
        payload=first.payload.model_copy(
            update={
                "delivered_components": (
                    source_cash.model_copy(
                        update={
                            "component_id": "cash-a",
                            "conditions": ("taxable", "ordinary", "taxable"),
                            "source_amount_text": "5.00",
                            "source_precision": 2,
                        }
                    ),
                )
            }
        ),
    )
    duplicate = duplicate_report(first, 441)
    assert duplicate.payload is not None
    duplicate_cash = duplicate.payload.delivered_components[0]
    assert isinstance(duplicate_cash, CashComponentV1)
    duplicate = _with_associations(
        duplicate,
        payload=duplicate.payload.model_copy(
            update={
                "delivered_components": (
                    duplicate_cash.model_copy(
                        update={
                            "component_id": "payment",
                            "source_amount_text": "5",
                            "source_precision": 0,
                        }
                    ),
                )
            }
        ),
    )
    assert first.payload is not None
    doubled = _with_associations(
        first,
        payload=first.payload.model_copy(
            update={
                "delivered_components": (
                    source_cash.model_copy(update={"component_id": "cash-a"}),
                    source_cash.model_copy(update={"component_id": "cash-b"}),
                )
            }
        ),
    )

    assert settlement_occurrence_payload_v1(first) == (
        settlement_occurrence_payload_v1(duplicate)
    )
    doubled_payload = settlement_occurrence_payload_v1(doubled)
    assert len(doubled_payload.components) == 2
    assert doubled_payload != settlement_occurrence_payload_v1(first)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_basis": "net"},
        {"currency_code": "CAD"},
        {"applicability": "conditional"},
        {"conditions": ("holder-election",)},
    ],
)
def test_cash_comparison_rejects_changes_to_economic_fields(
    change: dict[str, object],
) -> None:
    first = settlement_record(450)
    assert first.payload is not None
    cash = first.payload.delivered_components[0]
    assert isinstance(cash, CashComponentV1)
    changed = _with_associations(
        first,
        payload=first.payload.model_copy(
            update={"delivered_components": (cash.model_copy(update=change),)}
        ),
    )

    assert settlement_occurrence_payload_v1(changed) != (
        settlement_occurrence_payload_v1(first)
    )


def test_same_occurrence_conflict_is_uncomposed_and_never_summed() -> None:
    first = settlement_record(460, amount="5")
    conflict = duplicate_report(first, 461)
    assert conflict.payload is not None
    component = conflict.payload.delivered_components[0]
    assert isinstance(component, CashComponentV1)
    conflict = _with_associations(
        conflict,
        payload=conflict.payload.model_copy(
            update={
                "delivered_components": (
                    component.model_copy(update={"amount_basis": "net"}),
                )
            }
        ),
    )
    case = validated_case((first, conflict))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.delivery_groups == ()
    assert result.uncomposed_settlement_hashes == tuple(
        sorted((content_hash(first), content_hash(conflict)))
    )
    assert "same_occurrence_economics_conflicting" in result.reasons


def test_unknown_occurrence_methodology_keeps_report_uncomposed() -> None:
    payment = settlement_record(470, amount="4")
    case = validated_case((payment,), complete_coverage=False)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.delivery_groups == ()
    assert result.uncomposed_settlement_hashes == (content_hash(payment),)
    assert result.evidence_completeness == "partial"


def test_mixed_row_keeps_known_cash_and_component_gap() -> None:
    case = mixed_settlement_case("2021-02-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.delivery_groups) == 1
    group = result.delivery_groups[0]
    assert len(group.delivered_components) == 1
    component = group.delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "4"
    assert len(group.component_gaps) == 1
    assert result.evidence_completeness == "partial"


def test_occurrence_correction_respects_old_new_and_full_chain_snapshots() -> None:
    old_report = settlement_record(480, occurrence_id="payment-1")
    corroboration = duplicate_report(old_report, 481)
    correction = revise_record(
        old_report,
        482,
        "2021-02-01T00:00:00Z",
        {
            "occurrence": EconomicOccurrenceV1(
                kind="identified",
                native_occurrence_id="payment-2",
                evidence_reference=old_report.revision.source_artifact,
            )
        },
    )
    old_case = validated_case((old_report, corroboration))
    full_case = validated_case(
        (old_report, correction, corroboration),
        coverage_snapshot_at="2021-02-02T00:00:00Z",
    )
    old_query = old_case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    new_query = full_case.outcome_query("2021-01-01T00:00:00Z", "2021-02-02T00:00:00Z")
    full_old_query = full_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )

    old_result = resolve_economic_facts(
        old_query, old_case.context, old_case.source_policy
    )
    new_result = resolve_economic_facts(
        new_query, full_case.context, full_case.source_policy
    )
    full_old_result = resolve_economic_facts(
        full_old_query, full_case.context, full_case.source_policy
    )

    assert len(old_result.delivery_groups) == 1
    assert len(new_result.delivery_groups) == 2
    assert full_old_result.delivery_groups == ()
    assert set(full_old_result.uncomposed_settlement_hashes) == {
        content_hash(old_report),
        content_hash(corroboration),
    }
    assert full_old_result.evidence_completeness == "partial"


def test_complete_outcome_replay_rejects_forged_inventory() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)

    verify_economic_outcome(result, case.context, case.source_policy)
    forged = result.model_copy(
        update={"safe_projection_hashes": (*result.safe_projection_hashes, "f" * 64)}
    )
    with pytest.raises(ValueError, match="exact replay"):
        verify_economic_outcome(forged, case.context, case.source_policy)


def test_direct_terms_scope_wins_when_linked_effect_has_no_terms_parent() -> None:
    terms = terms_record(490)
    effect = effect_record(491)
    payment = settlement_record(492)
    assert payment.payload is not None
    terms_link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    payment = _with_associations(
        payment,
        terms_association=terms_link,
        effect_association=EconomicAssociationV1(
            kind="identified", target=effect.source_key
        ),
        payload=payment.payload.model_copy(
            update={
                "residual": ResidualClaimV1(
                    kind="outstanding",
                    scope_action=terms_link,
                    reason="more consideration may follow",
                )
            }
        ),
    )
    case = validated_case((terms, effect, payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    direct = next(
        item
        for item in result.residual_resolutions
        if item.action_scope == terms.source_key
    )
    assert direct.status == "outstanding"
    assert direct.covered_settlement_hashes == (content_hash(payment),)


def test_indeterminate_effect_boundary_is_projected_without_claim_authority() -> None:
    effect = bounded_effect_record(
        500,
        "2020-06-01T00:00:00Z",
        "2020-06-02T00:00:00Z",
        "2020-06-03T00:00:00Z",
        "2020-06-03T12:00:00Z",
    )
    case = validated_case((effect,), through="2020-06-01T12:00:00Z")
    query = case.decision_query(
        "2020-06-04T00:00:00Z",
        "2020-06-04T00:00:00Z",
        "2020-06-01T12:00:00Z",
    )

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.effect_projections) == 1
    assert result.effect_projections[0].effective_status == "indeterminate"
    assert result.claim_status == "unknown"
    assert result.evidence_completeness == "partial"


def test_outstanding_effect_without_settlement_keeps_evidence_partial() -> None:
    terms = terms_record(510)
    terms_link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    effect = effect_record(511)
    assert isinstance(effect.payload, OccurredEffectV1)
    effect = _with_associations(
        effect,
        terms_association=terms_link,
        payload=effect.payload.model_copy(
            update={
                "residual": ResidualClaimV1(
                    kind="outstanding",
                    scope_action=terms_link,
                    reason="delivery remains outstanding",
                )
            }
        ),
    )
    case = validated_case((terms, effect))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.residual_resolutions) == 1
    assert result.residual_resolutions[0].covered_settlement_hashes == ()
    assert result.residual_resolutions[0].status == "outstanding"
    assert result.evidence_completeness == "partial"


def test_cancellation_does_not_erase_prior_payment_or_invent_claim_state() -> None:
    payment = settlement_record(520, amount="5")
    cancelled = effect_record(521, kind="cancelled_action")
    case = validated_case((payment, cancelled))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.cancelled_action_hashes == (content_hash(cancelled),)
    assert result.claim_status == "unknown"
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "5"


def test_explicit_no_consideration_without_payment_never_fabricates_zero() -> None:
    terms = terms_record(530, action_kind=ActionKind.LIQUIDATION)
    terms_link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    effect = effect_record(531, claim_status="extinguished")
    assert isinstance(effect.payload, OccurredEffectV1)
    effect = _with_associations(
        effect,
        terms_association=terms_link,
        payload=effect.payload.model_copy(
            update={
                "action_kind": ActionKind.LIQUIDATION,
                "consideration_status": "explicit_none",
                "owed_components": (),
                "residual": ResidualClaimV1(
                    kind="closed_for_action",
                    scope_action=terms_link,
                    evidence_reference=effect.revision.source_artifact,
                ),
            }
        ),
    )
    case = validated_case((terms, effect))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.claim_status == "extinguished"
    assert result.delivery_groups == ()
    assert all(item.owed_components == () for item in result.effect_projections)
    assert "0" not in {
        component.amount
        for item in result.effect_projections
        for component in item.owed_components
        if isinstance(component, CashComponentV1)
    }


def test_continuing_effect_cannot_resurrect_terminal_claim() -> None:
    terminal = effect_record(
        540,
        claim_status="extinguished",
        effective_at="2020-06-01T00:00:00Z",
    )
    later = effect_record(
        541,
        claim_status="continuing",
        effective_at="2020-07-01T00:00:00Z",
    )
    case = validated_case((terminal, later))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.claim_status == "unknown"
    assert "claim_terminal_state_resurrected" in result.reasons
    assert result.support_status == "supported"


def test_settlement_correction_replaces_amount_instead_of_adding_receipt() -> None:
    initial = settlement_record(550, amount="5")
    assert initial.payload is not None
    old_cash = initial.payload.delivered_components[0]
    assert isinstance(old_cash, CashComponentV1)
    correction = revise_record(
        initial,
        551,
        "2020-07-01T00:00:00Z",
        {
            "payload": initial.payload.model_copy(
                update={
                    "delivered_components": (
                        old_cash.model_copy(update={"amount": "4"}),
                    )
                }
            )
        },
    )
    case = validated_case((initial, correction))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert len(result.delivery_groups) == 1
    assert result.delivery_groups[0].contributing_record_hashes == (
        content_hash(correction),
    )
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "4"


def test_replay_under_different_context_or_policy_is_rejected() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    different = validated_case((settlement_record(560),))

    with pytest.raises(Exception, match="mismatch"):
        verify_economic_outcome(result, different.context, different.source_policy)


def test_report_id_only_coverage_cannot_authorize_occurrence_grouping() -> None:
    payment = settlement_record(570)
    case = validated_case(
        (payment,), coverage_occurrence_key_semantics="report_ids_only"
    )
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    settlement_coverage = next(
        item for item in result.coverage_results if item.family == "settlement"
    )
    assert settlement_coverage.status == "partial"
    assert not settlement_coverage.occurrence_identity_supported
    assert result.delivery_groups == ()
    assert result.uncomposed_settlement_hashes == (content_hash(payment),)


def test_share_and_property_comparison_excludes_only_source_metadata() -> None:
    mixed_case = mixed_settlement_case("2020-02-01T00:00:00Z")
    mixed = next(
        record
        for dataset in mixed_case.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )
    assert mixed.payload is not None
    cash, share = mixed.payload.delivered_components
    assert isinstance(cash, CashComponentV1)
    assert isinstance(share, ShareComponentV1)
    share = share.model_copy(
        update={
            "fraction_treatment": FractionTreatmentV1(
                kind="round_up",
                source_rule="round fractional shares upward",
                evidence_reference=mixed.revision.source_artifact,
            )
        }
    )
    share_only = _with_associations(
        mixed,
        payload=mixed.payload.model_copy(update={"delivered_components": (share,)}),
    )
    share_duplicate = duplicate_report(share_only, 571)
    assert settlement_occurrence_payload_v1(share_only) == (
        settlement_occurrence_payload_v1(share_duplicate)
    )
    assert share_only.payload is not None
    changed_share = _with_associations(
        share_only,
        payload=share_only.payload.model_copy(
            update={
                "delivered_components": (
                    share.model_copy(
                        update={"ratio_meaning": "resulting_per_predecessor"}
                    ),
                )
            }
        ),
    )
    assert settlement_occurrence_payload_v1(share_only) != (
        settlement_occurrence_payload_v1(changed_share)
    )

    property_case = known_unsupported_case()
    property_record = next(
        record
        for dataset in property_case.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )
    assert property_record.payload is not None
    property_component = property_record.payload.delivered_components[0]
    assert isinstance(property_component, UnsupportedPropertyComponentV1)
    metadata_change = _with_associations(
        property_record,
        payload=property_record.payload.model_copy(
            update={
                "delivered_components": (
                    property_component.model_copy(
                        update={
                            "component_id": "renamed-cvr",
                            "reason": "different explanatory report reason",
                        }
                    ),
                )
            }
        ),
    )
    economic_change = _with_associations(
        property_record,
        payload=property_record.payload.model_copy(
            update={
                "delivered_components": (
                    property_component.model_copy(
                        update={"source_description": "two contractual CVRs"}
                    ),
                )
            }
        ),
    )
    assert settlement_occurrence_payload_v1(property_record) == (
        settlement_occurrence_payload_v1(metadata_change)
    )
    assert settlement_occurrence_payload_v1(property_record) != (
        settlement_occurrence_payload_v1(economic_change)
    )


def test_effect_projection_dependency_forgery_fails_complete_replay() -> None:
    case = closed_liquidation_case()
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    first = result.effect_projections[0]
    forged_effect = first.model_copy(update={"safe_fact_projection_hash": "e" * 64})
    forged = result.model_copy(
        update={"effect_projections": (forged_effect, *result.effect_projections[1:])}
    )

    with pytest.raises(ValueError, match="exact replay"):
        verify_economic_outcome(forged, case.context, case.source_policy)


def test_explicitly_incomplete_terms_prevent_known_evidence() -> None:
    terms = terms_record(580)
    assert terms.payload is not None
    incomplete = _with_associations(
        terms,
        payload=terms.payload.model_copy(
            update={
                "kind": "incomplete",
                "reason": "source omitted holder eligibility conditions",
            }
        ),
    )
    case = validated_case((incomplete,))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.selected_terms_hashes == (content_hash(incomplete),)
    assert result.evidence_completeness == "partial"
    assert result.support_status == "indeterminate"


def test_asserted_parent_version_mismatch_is_conflicting() -> None:
    terms = terms_record(590)
    effect = effect_record(591)
    effect = _with_associations(
        effect,
        terms_association=EconomicAssociationV1(
            kind="identified",
            target=terms.source_key,
            asserted_target_version_hash="f" * 64,
        ),
    )
    case = validated_case((terms, effect))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    association = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(effect)
    )
    assert association.status == "conflicting"
    assert "association_asserted_version_mismatch" in association.reasons
    assert len(result.effect_projections) == 1


def test_source_unknown_occurrence_stays_uncomposed_under_complete_coverage() -> None:
    payment = settlement_record(592, occurrence_id=None)
    case = validated_case((payment,))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.delivery_groups == ()
    assert result.uncomposed_settlement_hashes == (content_hash(payment),)
    assert result.evidence_completeness == "partial"


def test_after_horizon_effect_parent_is_unresolved_but_payment_survives() -> None:
    effect = effect_record(
        800,
        effective_at="2022-01-01T00:00:00Z",
        known_at="2022-01-01T00:00:00Z",
    )
    payment = settlement_record(801, amount="4")
    payment = _with_associations(
        payment,
        effect_association=EconomicAssociationV1(
            kind="identified", target=effect.source_key
        ),
    )
    case = validated_case(
        (effect, payment),
        through="2021-01-01T00:00:00Z",
        coverage_snapshot_at="2022-01-02T00:00:00Z",
    )
    query = case.outcome_query("2021-01-01T00:00:00Z", "2022-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "effect"
    )
    assert link.status == "unresolved"
    assert result.effect_projections[0].effective_status == "upcoming"
    component = result.delivery_groups[0].delivered_components[0]
    assert isinstance(component, CashComponentV1)
    assert component.amount == "4"


def test_indeterminate_effect_parent_is_unresolved_but_payment_survives() -> None:
    effect = bounded_effect_record(
        802,
        "2020-06-01T00:00:00Z",
        "2020-06-02T00:00:00Z",
        "2020-06-03T00:00:00Z",
        "2020-06-03T12:00:00Z",
    )
    payment = settlement_record(
        803,
        amount="4",
        settled_at="2020-05-15T00:00:00Z",
        known_at="2020-05-15T00:00:00Z",
    )
    payment = _with_associations(
        payment,
        effect_association=EconomicAssociationV1(
            kind="identified", target=effect.source_key
        ),
    )
    case = validated_case((effect, payment), through="2020-06-01T12:00:00Z")
    query = case.decision_query(
        "2020-06-04T00:00:00Z",
        "2020-06-04T00:00:00Z",
        "2020-06-01T12:00:00Z",
    )

    result = resolve_economic_facts(query, case.context, case.source_policy)

    link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "effect"
    )
    assert link.status == "unresolved"
    assert result.effect_projections[0].effective_status == "indeterminate"
    assert result.delivery_groups


def test_non_admitted_action_class_parent_is_unresolved() -> None:
    parent = terms_record(804, action_kind=ActionKind.CASH_ACQUISITION)
    payment = settlement_record(805)
    payment = _with_associations(
        payment,
        terms_association=EconomicAssociationV1(
            kind="identified", target=parent.source_key
        ),
    )
    case = validated_case((parent, payment))
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

    link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "terms"
    )
    assert link.status == "unresolved"
    assert content_hash(payment) in result.uncomposed_settlement_hashes
    assert result.safe_projection_hashes


def test_known_future_scheduled_terms_can_scope_prepaid_action_closure() -> None:
    terms = terms_record(806, scheduled_at="2022-01-01T00:00:00Z")
    terms_link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    payment = settlement_record(807, amount="5")
    assert payment.payload is not None
    payment = _with_associations(
        payment,
        terms_association=terms_link,
        payload=payment.payload.model_copy(
            update={
                "residual": ResidualClaimV1(
                    kind="closed_for_action",
                    scope_action=terms_link,
                    evidence_reference=payment.revision.source_artifact,
                )
            }
        ),
    )
    case = validated_case((terms, payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert any(
        item.status == "resolved"
        and item.source_record_hash == content_hash(payment)
        and item.association_field == "terms"
        for item in result.associations
    )
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope == terms.source_key
    )
    assert action.status == "closed"
    assert result.delivery_groups


def test_known_unknown_scheduled_terms_can_still_resolve_reported_parent() -> None:
    terms = terms_record(838)
    terms = _with_associations(
        terms,
        scheduled_effect_time=TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            source_precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            evidence_reference=None,
        ),
    )
    payment = settlement_record(839)
    payment = _with_associations(
        payment,
        terms_association=EconomicAssociationV1(
            kind="identified", target=terms.source_key
        ),
    )
    case = validated_case((terms, payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(payment)
        and item.association_field == "terms"
    )
    assert link.status == "resolved"
    assert result.delivery_groups


def test_opposing_exact_effect_tie_has_unknown_claim_state() -> None:
    continuing = effect_record(
        808,
        claim_status="continuing",
        effective_at="2020-06-01T00:00:00Z",
    )
    extinguished = effect_record(
        809,
        claim_status="extinguished",
        effective_at="2020-06-01T00:00:00Z",
    )
    case = validated_case((continuing, extinguished))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.claim_status == "unknown"
    assert "claim_effect_chronology_conflicting" in result.reasons


def test_nonadjacent_nested_opposing_effects_have_unknown_claim_state() -> None:
    outer = bounded_effect_record(
        810,
        "2020-06-01T00:00:00Z",
        "2020-06-30T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-07-02T00:00:00Z",
    )
    nested = bounded_effect_record(
        811,
        "2020-06-02T00:00:00Z",
        "2020-06-03T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-07-02T00:00:00Z",
    )
    opposing = bounded_effect_record(
        812,
        "2020-06-04T00:00:00Z",
        "2020-06-05T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-07-02T00:00:00Z",
    )
    assert isinstance(opposing.payload, OccurredEffectV1)
    opposing = _with_associations(
        opposing,
        payload=opposing.payload.model_copy(update={"claim_status": "extinguished"}),
    )
    case = validated_case(
        (outer, nested, opposing),
        through="2020-07-01T00:00:00Z",
        coverage_snapshot_at="2020-07-02T00:00:00Z",
    )
    query = case.outcome_query("2020-07-01T00:00:00Z", "2020-07-03T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.claim_status == "unknown"
    assert "claim_effect_chronology_conflicting" in result.reasons


def test_conflicting_terms_parent_cannot_be_replaced_by_effect_scope_anchor() -> None:
    foreign_terms = _with_associations(terms_record(813), security_id=uid(22))
    effect = effect_record(814, claim_status="extinguished")
    assert isinstance(effect.payload, OccurredEffectV1)
    effect_scope = EconomicAssociationV1(kind="identified", target=effect.source_key)
    effect = _with_associations(
        effect,
        terms_association=EconomicAssociationV1(
            kind="identified", target=foreign_terms.source_key
        ),
        payload=effect.payload.model_copy(
            update={
                "consideration_status": "explicit_none",
                "owed_components": (),
                "residual": ResidualClaimV1(
                    kind="closed_for_action",
                    scope_action=effect_scope,
                    evidence_reference=effect.revision.source_artifact,
                ),
            }
        ),
    )
    case = validated_case((foreign_terms, effect))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    link = next(
        item
        for item in result.associations
        if item.source_record_hash == content_hash(effect)
    )
    assert link.status == "conflicting"
    assert all(item.status != "closed" for item in result.residual_resolutions)


def test_unresolved_later_installment_blocks_prior_action_closure() -> None:
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    later = settlement_record(
        815,
        amount="7",
        occurrence_id="unresolved-later",
        settled_at="2020-08-01T00:00:00Z",
    )
    case = validated_case((*records, later))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)

    later_hash = content_hash(later)
    assert any(
        later_hash in group.contributing_record_hashes
        for group in result.delivery_groups
    )
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert action.status != "closed"
    assert later_hash not in action.covered_settlement_hashes


def test_literal_comparison_spec_hash_is_pinned_in_outcome() -> None:
    assert content_hash(_COMPOSITION_SPEC) == (
        "fb79e2326838f095927dab4636671476df55971f25dec78a804253d82d7c91d1"
    )
    assert _COMPOSITION_SPEC["components"] == {
        "collection": "multiset",
        "ordering": "canonical_json_bytes",
        "multiplicity": "preserved",
        "matching_prohibition": "never match across occurrence IDs",
    }
    case = validated_case((settlement_record(820),))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.composition_algorithm_spec_hash == content_hash(_COMPOSITION_SPEC)


def test_comparison_model_fields_match_the_literal_contract() -> None:
    assert tuple(CashEconomicValueV1.model_fields) == (
        "kind",
        "amount",
        "currency_namespace",
        "currency_code",
        "unit_basis",
        "amount_basis",
        "applicability",
        "conditions",
    )
    assert tuple(ShareEconomicValueV1.model_fields) == (
        "kind",
        "recipient",
        "ratio",
        "ratio_meaning",
        "unit_basis",
        "fraction",
        "applicability",
        "conditions",
    )
    assert tuple(PropertyEconomicValueV1.model_fields) == (
        "kind",
        "recipient",
        "source_description",
    )
    assert tuple(EconomicRecipientValueV1.model_fields) == (
        "kind",
        "security_id",
        "source_property_key",
    )
    assert tuple(FractionEconomicValueV1.model_fields) == ("kind", "source_rule")
    assert tuple(EconomicBoundaryValueV1.model_fields) == (
        "shape",
        "lower_bound",
        "upper_bound",
    )
    assert tuple(EconomicResidualValueV1.model_fields) == (
        "kind",
        "scope_occurrence_id",
        "scope_action",
    )
    assert tuple(EconomicAssociationValueV1.model_fields) == (
        "kind",
        "target",
        "asserted_target_version_hash",
        "native_hint",
    )


def test_cash_comparison_complete_included_and_excluded_field_matrix() -> None:
    base = cash_component()
    included = (
        base.model_copy(update={"amount": "6"}),
        base.model_copy(update={"currency_namespace": "SYNTHETIC"}),
        base.model_copy(update={"currency_code": "CAD"}),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={"security_id": uid(22)}
                )
            }
        ),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={
                        "denominator": PositiveRatioV1(numerator="1", denominator="2")
                    }
                )
            }
        ),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={
                        "denominator": PositiveRatioV1(numerator="2", denominator="1")
                    }
                )
            }
        ),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={"share_basis": "predecessor_post_action"}
                )
            }
        ),
        base.model_copy(update={"amount_basis": "net"}),
        base.model_copy(update={"applicability": "conditional"}),
        base.model_copy(update={"conditions": ("holder election",)}),
    )
    excluded = (
        base.model_copy(update={"component_id": "renamed"}),
        base.model_copy(update={"source_amount_text": "5.00"}),
        base.model_copy(update={"source_precision": 2}),
    )
    projected = component_economic_value_v1(base)
    assert all(component_economic_value_v1(item) != projected for item in included)
    assert all(component_economic_value_v1(item) == projected for item in excluded)


def test_share_comparison_complete_included_and_excluded_field_matrix() -> None:
    reference, _ = economic_evidence("share comparison evidence")
    alternate_reference, _ = economic_evidence("alternate share comparison evidence")
    base = ShareComponentV1(
        kind="shares",
        component_id="shares",
        recipient=EconomicRecipientV1(kind="security", security_id=uid(22)),
        ratio=PositiveRatioV1(numerator="1", denominator="2"),
        ratio_meaning="additional_per_predecessor",
        unit_basis=EconomicShareBasisV1(
            security_id=uid(21), share_basis="predecessor_pre_action"
        ),
        fraction_treatment=FractionTreatmentV1(
            kind="round_up",
            source_rule="round upward",
            evidence_reference=reference,
        ),
        applicability="ordinary_passive_holder",
        conditions=(),
    )
    included = (
        base.model_copy(
            update={
                "recipient": EconomicRecipientV1(
                    kind="unresolved_property",
                    source_property_key="rights-contract",
                    reason="source names property only",
                )
            }
        ),
        base.model_copy(
            update={"ratio": PositiveRatioV1(numerator="2", denominator="3")}
        ),
        base.model_copy(
            update={"ratio": PositiveRatioV1(numerator="2", denominator="1")}
        ),
        base.model_copy(
            update={"ratio": PositiveRatioV1(numerator="1", denominator="3")}
        ),
        base.model_copy(update={"ratio_meaning": "resulting_per_predecessor"}),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={"security_id": uid(22)}
                )
            }
        ),
        base.model_copy(
            update={
                "unit_basis": base.unit_basis.model_copy(
                    update={"share_basis": "predecessor_post_action"}
                )
            }
        ),
        base.model_copy(
            update={
                "fraction_treatment": FractionTreatmentV1(
                    kind="round_down",
                    source_rule="round downward",
                    evidence_reference=reference,
                )
            }
        ),
        base.model_copy(
            update={
                "fraction_treatment": base.fraction_treatment.model_copy(
                    update={"source_rule": "different fraction rule"}
                )
            }
        ),
        base.model_copy(update={"applicability": "conditional"}),
        base.model_copy(update={"conditions": ("holder election",)}),
    )
    excluded = (
        base.model_copy(update={"component_id": "renamed"}),
        base.model_copy(
            update={
                "fraction_treatment": base.fraction_treatment.model_copy(
                    update={"evidence_reference": alternate_reference}
                )
            }
        ),
    )
    projected = component_economic_value_v1(base)
    assert all(component_economic_value_v1(item) != projected for item in included)
    assert all(component_economic_value_v1(item) == projected for item in excluded)


def test_property_boundary_and_residual_complete_comparison_matrix() -> None:
    reference, _ = economic_evidence("comparison evidence one")
    alternate_reference, _ = economic_evidence("comparison evidence two")
    property_base = UnsupportedPropertyComponentV1(
        kind="unsupported_property",
        component_id="property",
        recipient=EconomicRecipientV1(kind="security", security_id=uid(22)),
        source_description="one contingent right",
        reason="unsupported valuation",
        evidence_reference=reference,
    )
    property_included = (
        property_base.model_copy(
            update={
                "recipient": EconomicRecipientV1(
                    kind="unresolved_property",
                    source_property_key="cvr-contract",
                    reason="source-native property",
                )
            }
        ),
        property_base.model_copy(
            update={
                "recipient": property_base.recipient.model_copy(
                    update={"security_id": uid(21)}
                )
            }
        ),
        property_base.model_copy(update={"source_description": "two rights"}),
    )
    property_excluded = (
        property_base.model_copy(update={"component_id": "renamed"}),
        property_base.model_copy(update={"reason": "different explanation"}),
        property_base.model_copy(update={"evidence_reference": alternate_reference}),
    )
    property_value = component_economic_value_v1(property_base)
    assert all(
        component_economic_value_v1(item) != property_value
        for item in property_included
    )
    assert all(
        component_economic_value_v1(item) == property_value
        for item in property_excluded
    )
    assert component_economic_value_v1(cash_component()) != property_value

    boundary = bounded_boundary(
        "2020-06-01T00:00:00Z", "2020-06-02T00:00:00Z", reference
    )
    assert boundary.lower_bound is not None
    assert boundary.upper_bound is not None
    boundary_value = boundary_economic_value_v1(boundary)
    assert (
        boundary_economic_value_v1(
            boundary.model_copy(
                update={"lower_bound": boundary.lower_bound.replace(hour=1)}
            )
        )
        != boundary_value
    )
    assert (
        boundary_economic_value_v1(
            boundary.model_copy(
                update={"upper_bound": boundary.upper_bound.replace(hour=1)}
            )
        )
        != boundary_value
    )
    assert (
        boundary_economic_value_v1(
            boundary.model_copy(
                update={
                    "source_precision": SourcePrecision.SECOND,
                    "source_time_label": "different source label",
                    "source_timezone": "UTC",
                    "evidence_reference": alternate_reference,
                }
            )
        )
        == boundary_value
    )

    action_a = EconomicAssociationV1(
        kind="identified",
        target=EconomicSourceKeyV1(
            source_id="synthetic-a", family="terms", native_record_id="action-a"
        ),
    )
    assert action_a.target is not None
    action_b = action_a.model_copy(
        update={
            "target": action_a.target.model_copy(
                update={"native_record_id": "action-b"}
            )
        }
    )
    residual = ResidualClaimV1(
        kind="outstanding", scope_action=action_a, reason="more may follow"
    )
    residual_value = residual_economic_value_v1(residual)
    assert (
        residual_economic_value_v1(residual.model_copy(update={"kind": "unknown"}))
        != residual_value
    )
    assert (
        residual_economic_value_v1(
            residual.model_copy(update={"scope_action": action_b})
        )
        != residual_value
    )
    assert (
        residual_economic_value_v1(
            residual.model_copy(
                update={
                    "scope_action": action_a.model_copy(
                        update={"asserted_target_version_hash": "f" * 64}
                    )
                }
            )
        )
        != residual_value
    )
    assert (
        residual_economic_value_v1(
            residual.model_copy(
                update={
                    "scope_action": EconomicAssociationV1(
                        kind="native_hint", native_hint="issuer-action-42"
                    )
                }
            )
        )
        != residual_value
    )
    occurrence_residual = ResidualClaimV1(
        kind="closed_for_occurrence",
        scope_occurrence_id="payment-1",
        evidence_reference=reference,
    )
    assert residual_economic_value_v1(
        occurrence_residual.model_copy(update={"scope_occurrence_id": "payment-2"})
    ) != residual_economic_value_v1(occurrence_residual)
    assert (
        residual_economic_value_v1(
            residual.model_copy(
                update={
                    "reason": "different explanation",
                    "evidence_reference": alternate_reference,
                }
            )
        )
        == residual_value
    )


def test_unknown_and_after_horizon_closures_do_not_close_action() -> None:
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    terminal = next(
        record
        for record in records
        if isinstance(record, EconomicEffectVersionV1)
        and isinstance(record.payload, OccurredEffectV1)
        and record.payload.residual.kind == "closed_for_action"
    )
    unknown_terminal = _with_associations(
        terminal,
        effective_time=TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            source_precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            evidence_reference=None,
        ),
    )
    unknown_case = validated_case(
        tuple(unknown_terminal if item == terminal else item for item in records)
    )
    unknown_query = unknown_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    unknown_result = resolve_economic_facts(
        unknown_query, unknown_case.context, unknown_case.source_policy
    )
    unknown_action = next(
        item
        for item in unknown_result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert unknown_action.status != "closed"
    assert unknown_result.delivery_groups

    after_horizon = revise_record(
        terminal,
        821,
        "2022-01-01T00:00:00Z",
        {
            "effective_time": exact_boundary(
                "2022-01-01T00:00:00Z", terminal.revision.source_artifact
            )
        },
    )
    after_case = validated_case(
        (*records, after_horizon),
        coverage_snapshot_at="2022-01-02T00:00:00Z",
    )
    after_query = after_case.outcome_query(
        "2021-01-01T00:00:00Z", "2022-01-02T00:00:00Z"
    )
    after_result = resolve_economic_facts(
        after_query, after_case.context, after_case.source_policy
    )
    after_action = next(
        item
        for item in after_result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert after_action.status != "closed"
    assert any(
        item.effective_status == "upcoming" for item in after_result.effect_projections
    )
    assert after_result.delivery_groups


def test_strictly_later_outstanding_prevents_closure() -> None:
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    terms = next(
        item for item in records if isinstance(item, CorporateActionTermsVersionV1)
    )
    terms_link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    later = effect_record(
        822,
        claim_status="extinguished",
        effective_at="2020-08-01T00:00:00Z",
    )
    assert isinstance(later.payload, OccurredEffectV1)
    later = _with_associations(
        later,
        terms_association=terms_link,
        payload=later.payload.model_copy(
            update={
                "action_kind": ActionKind.LIQUIDATION,
                "residual": ResidualClaimV1(
                    kind="outstanding",
                    scope_action=terms_link,
                    reason="later report says consideration remains",
                ),
            }
        ),
    )
    case = validated_case((*records, later))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert action.status == "outstanding"
    assert result.delivery_groups


def test_resolved_distinct_action_does_not_poison_closed_action() -> None:
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    other_terms = terms_record(823, action_kind=ActionKind.LIQUIDATION)
    other_link = EconomicAssociationV1(kind="identified", target=other_terms.source_key)
    other_payment = settlement_record(
        824,
        amount="7",
        occurrence_id="distinct-action-payment",
        settled_at="2020-08-01T00:00:00Z",
    )
    assert other_payment.payload is not None
    other_payment = _with_associations(
        other_payment,
        terms_association=other_link,
        payload=other_payment.payload.model_copy(
            update={
                "action_kind": ActionKind.LIQUIDATION,
                "residual": ResidualClaimV1(
                    kind="closed_for_action",
                    scope_action=other_link,
                    evidence_reference=other_payment.revision.source_artifact,
                ),
            }
        ),
    )
    case = validated_case((*records, other_terms, other_payment))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    original = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert original.status == "closed"


def test_definitely_after_horizon_unresolved_installment_does_not_block_closure() -> (
    None
):
    base = closed_liquidation_case()
    records = tuple(
        record
        for dataset in base.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )
    future = settlement_record(
        825,
        amount="7",
        occurrence_id="after-horizon",
        settled_at="2022-01-01T00:00:00Z",
        known_at="2022-01-01T00:00:00Z",
    )
    case = validated_case(
        (*records, future), coverage_snapshot_at="2022-01-02T00:00:00Z"
    )
    query = case.outcome_query("2021-01-01T00:00:00Z", "2022-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )
    assert action.status == "closed"
    assert all(
        content_hash(future) not in group.contributing_record_hashes
        for group in result.delivery_groups
    )


def test_security_attribution_correction_never_counts_both_versions() -> None:
    initial = settlement_record(826, amount="5")
    correction = revise_record(
        initial,
        827,
        "2020-07-01T00:00:00Z",
        {"security_id": uid(22)},
    )
    old_case = validated_case((initial,), security_id=uid(21))
    new_a = validated_case((initial, correction), security_id=uid(21))
    new_b = validated_case((initial, correction), security_id=uid(22))
    old_query = old_case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    new_a_query = new_a.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    new_b_query = new_b.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    old_result = resolve_economic_facts(
        old_query, old_case.context, old_case.source_policy
    )
    new_a_result = resolve_economic_facts(
        new_a_query, new_a.context, new_a.source_policy
    )
    new_b_result = resolve_economic_facts(
        new_b_query, new_b.context, new_b.source_policy
    )
    assert old_result.delivery_groups[0].contributing_record_hashes == (
        content_hash(initial),
    )
    assert new_a_result.delivery_groups == ()
    assert new_b_result.delivery_groups[0].contributing_record_hashes == (
        content_hash(correction),
    )


def test_forged_duplicate_owner_partition_is_rejected_at_composition_boundary() -> None:
    case = validated_case((settlement_record(828),))
    forged_policy = type(case.source_policy).model_construct(
        schema_version=case.source_policy.schema_version,
        policy_id=case.source_policy.policy_id,
        policy_version=case.source_policy.policy_version,
        security_id=case.source_policy.security_id,
        action_kinds=case.source_policy.action_kinds,
        scope=case.source_policy.scope,
        history_start=case.source_policy.history_start,
        through=case.source_policy.through,
        owners=(*case.source_policy.owners, case.source_policy.owners[-1]),
        input_dataset_bindings=case.source_policy.input_dataset_bindings,
    )
    query = case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    ).model_copy(update={"source_selection_policy_hash": content_hash(forged_policy)})
    with pytest.raises(ValueError, match="owner"):
        resolve_economic_facts(query, case.context, forged_policy)


def test_split_complete_coverage_cannot_be_combined_into_authority() -> None:
    case = validated_case((), split_settlement_coverage=True)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    settlement_coverage = next(
        item for item in result.coverage_results if item.family == "settlement"
    )
    assert len(settlement_coverage.selected_coverage_hashes) == 2
    assert settlement_coverage.status != "complete"
    assert not settlement_coverage.occurrence_identity_supported
    assert result.evidence_completeness == "unknown"


def test_ended_listing_context_does_not_override_continuing_claim() -> None:
    listing_id = uid(88)
    effect = effect_record(829, claim_status="continuing")
    effect = _with_associations(effect, listing_id=listing_id)
    case = validated_case(
        (effect,),
        identity_assignments=(
            identity_assignment(830, 21),
            identity_assignment(
                831,
                88,
                identity_kind="listing",
                ended_at="2020-02-01T00:00:00Z",
            ),
        ),
    )
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.claim_status == "continuing"
    assert result.effect_projections


def test_unknown_bankruptcy_remains_unknown_and_indeterminate() -> None:
    effect = effect_record(832)
    assert isinstance(effect.payload, OccurredEffectV1)
    effect = _with_associations(
        effect,
        payload=effect.payload.model_copy(
            update={
                "action_kind": ActionKind.BANKRUPTCY_REORGANIZATION,
                "claim_status": "unknown",
                "consideration_status": "unknown",
                "owed_components": (),
                "residual": ResidualClaimV1(
                    kind="unknown", reason="bankruptcy outcome is unresolved"
                ),
            }
        ),
    )
    case = validated_case((effect,))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    assert result.claim_status == "unknown"
    assert result.evidence_completeness == "partial"
    assert result.support_status == "indeterminate"


def test_future_correction_cannot_be_injected_through_dependent_result() -> None:
    initial = effect_record(833, claim_status="continuing")
    assert isinstance(initial.payload, OccurredEffectV1)
    correction = revise_record(
        initial,
        834,
        "2021-02-01T00:00:00Z",
        {
            "payload": initial.payload.model_copy(
                update={"claim_status": "extinguished"}
            )
        },
    )
    case = validated_case(
        (initial, correction), coverage_snapshot_at="2021-02-02T00:00:00Z"
    )
    old_query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    new_query = case.outcome_query("2021-01-01T00:00:00Z", "2021-02-02T00:00:00Z")
    old_result = resolve_economic_facts(old_query, case.context, case.source_policy)
    new_result = resolve_economic_facts(new_query, case.context, case.source_policy)
    forged = old_result.model_copy(
        update={"effect_projections": new_result.effect_projections}
    )
    with pytest.raises(ValueError, match="exact replay"):
        verify_economic_outcome(forged, case.context, case.source_policy)


def test_audit_outcome_hash_cannot_leak_into_consumer_reference() -> None:
    case = validated_case((settlement_record(835),))
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    result = resolve_economic_facts(query, case.context, case.source_policy)
    reference = outcome_reference(query, case.context, case.source_policy)
    projections = project_market_facts(query, case.context, case.source_policy)
    mapping = {content_hash(item): item for item in projections}
    leaked = reference.model_copy(
        update={
            "projection_hashes": (*reference.projection_hashes, content_hash(result))
        }
    )
    with pytest.raises(ValueError, match="reference"):
        resolve_outcome_projections(
            leaked,
            query,
            mapping,
            case.context,
            case.source_policy,
        )


def test_alternate_provider_cannot_become_owner_receipt() -> None:
    owner_payment = settlement_record(836, amount="5")
    alternate_payment = settlement_record(837, amount="9")
    owner = validated_case((owner_payment,), owner_source="synthetic-a")
    alternate = validated_case((alternate_payment,), owner_source="synthetic-b")
    alternate_owned = next(
        record
        for dataset in alternate.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )
    datasets = (*owner.context.datasets, *alternate.context.datasets)
    supporting_by_hash = {
        item.content_hash: item
        for item in (
            *owner.context.supporting_artifacts,
            *alternate.context.supporting_artifacts,
        )
    }
    context = EconomicResolutionContext(
        datasets=datasets,
        identity=owner.context.identity,
        availability_policy=owner.context.availability_policy,
        retained_evidence=owner.context.retained_evidence,
        supporting_artifacts=tuple(
            supporting_by_hash[item] for item in sorted(supporting_by_hash)
        ),
    )
    bindings = tuple(
        DatasetBindingV1(
            manifest_hash=manifest_hash(dataset.manifest),
            decision_hash=content_hash(dataset.decision),
            bundle_hash=content_hash(dataset.bundle),
            role=dataset.manifest.dataset_role.name,
            source_id=dataset.manifest.source.source_id,
        )
        for dataset in datasets
    )
    source_policy = owner.source_policy.model_copy(
        update={"input_dataset_bindings": bindings}
    )
    query = owner.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    ).model_copy(
        update={
            "input_context_hash": economic_context_hash(context),
            "source_selection_policy_hash": content_hash(source_policy),
        }
    )
    result = resolve_economic_facts(query, context, source_policy)
    assert len(result.delivery_groups) == 1
    assert result.delivery_groups[0].contributing_record_hashes == (
        content_hash(owner_payment),
    )
    selected_projections = project_market_facts(query, context, source_policy)
    assert {item.source_record_hash for item in selected_projections} == {
        content_hash(owner_payment)
    }
    assert content_hash(alternate_owned) not in {
        item.source_record_hash for item in selected_projections
    }
