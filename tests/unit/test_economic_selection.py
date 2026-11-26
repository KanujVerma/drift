"""Causal M1c economic selection, projection, and replay tests."""

from types import MappingProxyType
from typing import Literal

import pytest
from economic_test_support import (
    bounded_availability,
    bounded_boundary,
    bounded_effect_record,
    effect_record,
    evidence_bearing_partial_projection_case,
    identity_assignment,
    mixed_settlement_case,
    multichannel_actual_case,
    multichannel_untrusted_evidence_case,
    parse_utc,
    public_channel,
    rebind_record_evidence,
    revise_identity_assignment,
    revise_record,
    seal_record,
    terms_record,
    uid,
    validated_case,
    vendor_channel,
    with_identity_assignments,
)

from drift.domain.dataset_validation import DatasetValidationError
from drift.domain.economic_common import (
    CashComponentV1,
    ShareComponentV1,
    UnsupportedPropertyComponentV1,
)
from drift.domain.economic_coverage import DatasetBindingV1, EconomicSourceOwnerV1
from drift.domain.economic_events import EconomicSettlementVersionV1
from drift.domain.securities import (
    IdentityAssignmentEffect,
    IdentityAssignmentVersionV1,
)
from drift.markets.economic_selection import (
    decision_reference,
    outcome_reference,
    project_market_facts,
    resolve_decision_projections,
    resolve_decision_records,
    resolve_outcome_projections,
    resolve_outcome_records,
    select_market_records,
    select_retained_economic_identity,
    verify_market_selection,
)
from drift.markets.economic_validation import EconomicResolutionContext
from drift.serialization.canonical import content_hash


def test_may_announcement_is_selected_without_proving_june_occurrence() -> None:
    terms = terms_record(100)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)
    reference = decision_reference(query, case.context, case.source_policy)

    assert reference.selected_record_hashes == proof.raw_materializable_record_hashes
    assert content_hash(terms) in reference.selected_record_hashes
    assert not hasattr(reference, "considered_record_hashes")


def test_mixed_row_preserves_known_cash_without_future_recipient() -> None:
    case = mixed_settlement_case("2021-02-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    projections = project_market_facts(query, case.context, case.source_policy)

    paid = next(item for item in projections if item.family == "settlement")
    cash = paid.known_components[0]
    assert isinstance(cash, CashComponentV1)
    assert cash.amount == "4"
    assert len(paid.withheld_components) == 1
    assert paid.withheld_components[0].reason == "recipient_identity_unavailable"
    assert "019b8240-0000-7000-8000-000000000022" not in paid.model_dump_json()


def test_mixed_row_exposes_both_components_after_recipient_is_known() -> None:
    case = mixed_settlement_case("2021-02-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-02-02T00:00:00Z")

    paid = next(
        item
        for item in project_market_facts(query, case.context, case.source_policy)
        if item.family == "settlement"
    )

    assert tuple(component.component_id for component in paid.known_components) == (
        "cash",
        "shares",
    )
    assert paid.withheld_components == ()


def test_decision_reference_replays_exact_raw_values_and_rejects_forgery() -> None:
    terms = terms_record(120)
    forged = terms_record(121)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    reference = decision_reference(query, case.context, case.source_policy)
    record_hash = content_hash(terms)

    resolved = resolve_decision_records(
        reference,
        query,
        {record_hash: terms},
        case.context,
        case.source_policy,
    )

    assert isinstance(resolved, MappingProxyType)
    assert resolved == {record_hash: terms}
    with pytest.raises(ValueError, match="record hash"):
        resolve_decision_records(
            reference,
            query,
            {record_hash: forged},
            case.context,
            case.source_policy,
        )


def test_reference_and_proof_replay_reject_role_and_selected_value_forgery() -> None:
    terms = terms_record(122)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    decision_query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    outcome_query = case.outcome_query("2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z")
    proof = select_market_records(decision_query, case.context, case.source_policy)
    forged = proof.model_copy(update={"projection_hashes": ("f" * 64,)})

    with pytest.raises(ValueError, match="selection proof"):
        verify_market_selection(forged, case.context, case.source_policy)
    with pytest.raises(TypeError, match="decision query"):
        decision_reference(outcome_query, case.context, case.source_policy)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="outcome query"):
        outcome_reference(decision_query, case.context, case.source_policy)  # type: ignore[arg-type]


def test_retained_identity_is_finite_and_independent_of_ended_interval() -> None:
    terms = terms_record(130)
    base = validated_case((terms,), through="2020-05-15T00:00:00Z")
    future = with_identity_assignments(
        base,
        (identity_assignment(5100, 21, known_at="2020-06-01T00:00:00Z"),),
    )
    ended = with_identity_assignments(
        base,
        (identity_assignment(5101, 21, ended_at="2020-02-01T00:00:00Z"),),
    )
    future_query = future.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    ended_query = ended.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    future_proof = select_market_records(
        future_query, future.context, future.source_policy
    )
    ended_proof = select_market_records(ended_query, ended.context, ended.source_policy)

    assert future_proof.identity_proofs[0].status == "unknown"
    assert future_proof.raw_materializable_record_hashes == ()
    assert ended_proof.identity_proofs[0].status == "known"
    assert content_hash(terms) in ended_proof.raw_materializable_record_hashes


def test_unassigned_identity_requires_and_retains_positive_prefix() -> None:
    base_assignment = identity_assignment(5200, 21)
    unassigned = revise_identity_assignment(
        base_assignment,
        5201,
        "2020-02-01T00:00:00Z",
        effect=IdentityAssignmentEffect.UNASSIGNED,
    )
    lone_unassigned = identity_assignment(
        5202, 21, effect=IdentityAssignmentEffect.UNASSIGNED
    )
    base = validated_case((terms_record(131),), through="2020-05-15T00:00:00Z")
    with_prefix = with_identity_assignments(base, (base_assignment, unassigned))
    without_prefix = with_identity_assignments(base, (lone_unassigned,))
    query_with = with_prefix.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    query_without = without_prefix.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    retained = select_retained_economic_identity(
        "security", uid(21), query_with, with_prefix.context
    )
    unsupported = select_retained_economic_identity(
        "security", uid(21), query_without, without_prefix.context
    )

    assert retained.status == "known"
    assert len(retained.selected_assignment_hashes) == 2
    assert unsupported.status == "unknown"


def test_identity_correction_switches_a_to_b_only_at_finite_cutoff() -> None:
    initial_a = identity_assignment(5300, 21)
    corrected_b = revise_identity_assignment(
        initial_a, 5301, "2020-03-01T00:00:00Z", identity_id=22
    )
    base = validated_case((terms_record(132),), through="2020-05-15T00:00:00Z")
    case = with_identity_assignments(base, (initial_a, corrected_b))
    old_query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-02-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    new_query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-04-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    assert (
        select_retained_economic_identity(
            "security", uid(21), old_query, case.context
        ).status
        == "known"
    )
    assert (
        select_retained_economic_identity(
            "security", uid(22), old_query, case.context
        ).status
        == "unknown"
    )
    assert (
        select_retained_economic_identity(
            "security", uid(21), new_query, case.context
        ).status
        == "unknown"
    )
    assert (
        select_retained_economic_identity(
            "security", uid(22), new_query, case.context
        ).status
        == "known"
    )


def test_predating_actual_claim_stays_withheld_until_correction() -> None:
    impossible = effect_record(
        140,
        effective_at="2020-06-01T00:00:00Z",
        known_at="2020-05-01T00:00:00Z",
    )
    corrected = revise_record(impossible, 141, "2020-07-01T00:00:00Z", changes={})
    stale_case = validated_case((impossible,), through="2020-07-02T00:00:00Z")
    early_case = validated_case((impossible,), through="2020-05-15T00:00:00Z")
    corrected_case = validated_case(
        (impossible, corrected), through="2020-07-02T00:00:00Z"
    )
    stale_query = stale_case.outcome_query(
        "2020-07-02T00:00:00Z", "2020-07-02T00:00:00Z"
    )
    early_query = early_case.outcome_query(
        "2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z"
    )
    corrected_query = corrected_case.outcome_query(
        "2020-07-02T00:00:00Z", "2020-07-02T00:00:00Z"
    )

    stale = select_market_records(
        stale_query, stale_case.context, stale_case.source_policy
    )
    early = select_market_records(
        early_query, early_case.context, early_case.source_policy
    )
    repaired = select_market_records(
        corrected_query, corrected_case.context, corrected_case.source_policy
    )

    for impossible_proof in (early, stale):
        assert impossible_proof.applicability[0].status == "indeterminate"
        assert impossible_proof.applicability[0].reasons == (
            "actual_claim_predates_occurrence",
        )
        assert impossible_proof.raw_materializable_record_hashes == ()
    assert stale.raw_materializable_record_hashes == ()
    assert content_hash(corrected) in repaired.raw_materializable_record_hashes


def test_bounded_actual_overlap_is_indeterminate_and_same_day_is_valid() -> None:
    spans_horizon = bounded_effect_record(
        142,
        "2020-06-01T00:00:00Z",
        "2020-06-02T00:00:00Z",
        "2020-06-03T00:00:00Z",
        "2020-06-03T12:00:00Z",
    )
    spanning_case = validated_case((spans_horizon,), through="2020-06-01T12:00:00Z")
    spanning_query = spanning_case.decision_query(
        "2020-06-04T00:00:00Z",
        "2020-06-04T00:00:00Z",
        "2020-06-01T12:00:00Z",
    )
    same_day = bounded_effect_record(
        143,
        "2020-06-01T00:00:00Z",
        "2020-06-02T00:00:00Z",
        "2020-06-01T12:00:00Z",
        "2020-06-02T00:00:00Z",
    )
    same_day_case = validated_case((same_day,), through="2020-06-03T00:00:00Z")
    same_day_query = same_day_case.outcome_query(
        "2020-06-03T00:00:00Z", "2020-06-03T00:00:00Z"
    )

    spanning = select_market_records(
        spanning_query, spanning_case.context, spanning_case.source_policy
    )
    spanning_projection = next(
        item
        for item in project_market_facts(
            spanning_query, spanning_case.context, spanning_case.source_policy
        )
        if item.source_record_hash == content_hash(spans_horizon)
    )
    valid = select_market_records(
        same_day_query, same_day_case.context, same_day_case.source_policy
    )

    assert spanning.applicability[0].status == "indeterminate"
    assert spanning_projection.applicability == spanning.applicability[0]
    assert spanning.raw_materializable_record_hashes == ()
    assert content_hash(same_day) in valid.raw_materializable_record_hashes


def test_optional_listing_is_omitted_without_erasing_safe_components() -> None:
    listing_id = uid(88)
    case = mixed_settlement_case("2020-02-01T00:00:00Z", listing_id=listing_id)
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")

    paid = next(
        item
        for item in project_market_facts(query, case.context, case.source_policy)
        if item.family == "settlement"
    )
    proof = select_market_records(query, case.context, case.source_policy)

    assert tuple(item.component_id for item in paid.known_components) == (
        "cash",
        "shares",
    )
    assert paid.optional_context_reasons == ("source_listing_context_omitted",)
    assert str(listing_id) not in paid.model_dump_json()
    assert proof.raw_materializable_record_hashes == ()


def test_complete_audit_keeps_other_security_and_coverage_audit_only() -> None:
    target = terms_record(150)
    other_base = terms_record(151)
    values = {name: getattr(other_base, name) for name in type(other_base).model_fields}
    values["security_id"] = uid(99)
    other = rebind_record_evidence(type(other_base), values)
    case = validated_case((target, other), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)
    projection_sources = {
        item.source_record_hash
        for item in project_market_facts(query, case.context, case.source_policy)
    }
    coverage_hashes = {
        content_hash(record) for record in case.context.datasets[-1].records
    }

    assert content_hash(other) in proof.revision_selected_record_hashes
    coverage_proof = next(
        item for item in proof.dataset_proofs if item.role == "economic_coverage"
    )
    assert coverage_hashes <= set(coverage_proof.considered_record_hashes)
    assert set(proof.raw_materializable_record_hashes) == {content_hash(target)}
    assert projection_sources == {content_hash(target)}
    assert not coverage_hashes & set(proof.raw_materializable_record_hashes)


def test_projection_and_outcome_resolvers_verify_exact_authorized_values() -> None:
    case = mixed_settlement_case("2021-02-01T00:00:00Z")
    query = case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    reference = outcome_reference(query, case.context, case.source_policy)
    projection = project_market_facts(query, case.context, case.source_policy)[0]
    projection_hash = content_hash(projection)
    authentic_raw = next(
        record
        for dataset in case.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )

    resolved = resolve_outcome_projections(
        reference,
        query,
        {projection_hash: projection},
        case.context,
        case.source_policy,
    )

    assert isinstance(resolved, MappingProxyType)
    assert resolved == {projection_hash: projection}
    with pytest.raises(ValueError, match="projection hash"):
        resolve_outcome_projections(
            reference,
            query,
            {
                projection_hash: projection.model_copy(
                    update={"optional_context_reasons": ("forged",)}
                )
            },
            case.context,
            case.source_policy,
        )
    with pytest.raises(ValueError, match="record hash keys"):
        resolve_outcome_records(
            reference,
            query,
            {content_hash(authentic_raw): authentic_raw},
            case.context,
            case.source_policy,
        )


def test_outcome_reference_cannot_be_used_by_decision_projection_api() -> None:
    terms = terms_record(156)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    outcome_query = case.outcome_query("2020-05-15T00:00:00Z", "2020-05-15T00:00:00Z")
    decision_query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    reference = outcome_reference(outcome_query, case.context, case.source_policy)
    reference = type(reference).model_validate_json(reference.model_dump_json())

    with pytest.raises(TypeError, match="decision reference"):
        resolve_decision_projections(
            reference,  # type: ignore[arg-type]
            decision_query,
            {},
            case.context,
            case.source_policy,
        )


def test_uncertain_revision_preserves_prior_and_binds_unresolved_chain() -> None:
    initial = terms_record(160, known_at="2020-05-01T00:00:00Z")
    uncertain = revise_record(initial, 161, "2020-06-01T00:00:00Z", changes={})
    evidence = uncertain.revision.source_artifact
    uncertain_values = {
        name: getattr(uncertain, name) for name in type(uncertain).model_fields
    }
    uncertain_values["revision"] = uncertain.revision.model_copy(
        update={
            "availability": (
                bounded_availability(
                    "2020-05-10T00:00:00Z",
                    "2020-05-20T00:00:00Z",
                    evidence,
                ),
            )
        }
    )
    uncertain = rebind_record_evidence(type(uncertain), uncertain_values)
    case = validated_case((initial, uncertain), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)

    assert content_hash(initial) in proof.raw_materializable_record_hashes
    assert content_hash(uncertain) not in proof.raw_materializable_record_hashes
    assert proof.unresolved_chain_hashes


def test_source_security_correction_switches_a_to_b_at_cutoff() -> None:
    initial_a = terms_record(162, known_at="2020-01-01T00:00:00Z")
    corrected_b = revise_record(
        initial_a,
        163,
        "2020-03-01T00:00:00Z",
        {"security_id": uid(22)},
    )
    case_a = validated_case(
        (initial_a, corrected_b),
        through="2020-05-15T00:00:00Z",
        security_id=uid(21),
    )
    case_b = validated_case(
        (initial_a, corrected_b),
        through="2020-05-15T00:00:00Z",
        security_id=uid(22),
    )
    old_a = case_a.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-02-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    old_b = case_b.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-02-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    new_a = case_a.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-04-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    new_b = case_b.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-04-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    assert select_market_records(
        old_a, case_a.context, case_a.source_policy
    ).raw_materializable_record_hashes == (content_hash(initial_a),)
    assert (
        select_market_records(
            old_b, case_b.context, case_b.source_policy
        ).raw_materializable_record_hashes
        == ()
    )
    assert (
        select_market_records(
            new_a, case_a.context, case_a.source_policy
        ).raw_materializable_record_hashes
        == ()
    )
    assert select_market_records(
        new_b, case_b.context, case_b.source_policy
    ).raw_materializable_record_hashes == (content_hash(corrected_b),)


def test_future_current_only_record_does_not_invent_old_knowledge() -> None:
    future = terms_record(164, known_at="2020-03-01T00:00:00Z")
    case = validated_case(
        (future,),
        through="2020-05-15T00:00:00Z",
        coverage_revision_support="current_only",
    )
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-02-01T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)

    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()


def test_december_settlement_is_not_selected_at_june_knowledge_cutoff() -> None:
    future = mixed_settlement_case("2020-01-01T00:00:00Z")
    source = next(
        record
        for dataset in future.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )
    december = revise_record(
        source,
        165,
        "2020-12-15T00:00:00Z",
        {
            "settled_time": source.settled_time.model_copy(
                update={
                    "lower_bound": parse_utc("2020-12-15T00:00:00Z"),
                    "upper_bound": parse_utc("2020-12-15T00:00:00Z"),
                    "source_time_label": "2020-12-15T00:00:00Z",
                }
            )
        },
    )
    case = validated_case((source, december), through="2020-12-31T00:00:00Z")
    query = case.decision_query(
        "2020-12-31T00:00:00Z",
        "2020-06-01T00:00:00Z",
        "2020-12-31T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)

    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()


def test_withdrawal_does_not_retain_identity_but_ended_listing_does() -> None:
    assigned = identity_assignment(5400, 21)
    withdrawn = revise_identity_assignment(
        assigned, 5401, "2020-02-01T00:00:00Z", withdrawal=True
    )
    base = validated_case((terms_record(170),), through="2020-05-15T00:00:00Z")
    withdrawn_case = with_identity_assignments(base, (assigned, withdrawn))
    withdrawn_query = withdrawn_case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    assert (
        select_retained_economic_identity(
            "security", uid(21), withdrawn_query, withdrawn_case.context
        ).status
        == "unknown"
    )

    listing_id = uid(88)
    listing_case = mixed_settlement_case("2020-02-01T00:00:00Z", listing_id=listing_id)
    listing_case = with_identity_assignments(
        listing_case,
        (
            identity_assignment(5402, 21),
            identity_assignment(5403, 22),
            identity_assignment(
                5404,
                88,
                identity_kind="listing",
                ended_at="2020-03-01T00:00:00Z",
            ),
        ),
    )
    listing_query = listing_case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    )
    listing_proof = select_market_records(
        listing_query, listing_case.context, listing_case.source_policy
    )
    retained_listing = next(
        item
        for item in listing_proof.identity_proofs
        if item.identity_kind == "listing"
    )
    assert retained_listing.status == "known"
    assert listing_proof.projection_hashes
    assert listing_proof.raw_materializable_record_hashes == ()


def test_horizon_or_effective_cutoff_beyond_evidence_does_not_anticipate() -> None:
    actual = effect_record(171, effective_at="2020-06-01T00:00:00Z")
    outcome_case = validated_case((actual,), through="2020-06-02T00:00:00Z")
    decision_case = validated_case((actual,), through="2020-06-02T00:00:00Z")
    outcome_query = outcome_case.outcome_query(
        "2020-06-02T00:00:00Z", "2020-05-01T00:00:00Z"
    )
    decision_query = decision_case.decision_query(
        "2020-06-02T00:00:00Z",
        "2020-05-01T00:00:00Z",
        "2020-06-02T00:00:00Z",
    )

    for proof in (
        select_market_records(
            outcome_query, outcome_case.context, outcome_case.source_policy
        ),
        select_market_records(
            decision_query, decision_case.context, decision_case.source_policy
        ),
    ):
        assert proof.raw_materializable_record_hashes == ()
        assert proof.projection_hashes == ()


def test_selection_rejects_policy_context_and_dataset_binding_mutations() -> None:
    terms = terms_record(172)
    case = validated_case((terms,), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    evidence = terms.revision.availability[0]
    changed_context = EconomicResolutionContext(
        datasets=case.context.datasets,
        identity=case.context.identity,
        availability_policy=case.context.availability_policy,
        retained_evidence={content_hash(evidence): evidence},
        supporting_artifacts=case.context.supporting_artifacts,
    )
    wrong_window = case.source_policy.model_copy(
        update={"through": parse_utc("2020-05-16T00:00:00Z")}
    )
    wrong_security = case.source_policy.model_copy(update={"security_id": uid(22)})
    first_binding = case.source_policy.input_dataset_bindings[0].model_copy(
        update={"decision_hash": "e" * 64}
    )
    wrong_bindings = case.source_policy.model_copy(
        update={
            "input_dataset_bindings": (
                first_binding,
                *case.source_policy.input_dataset_bindings[1:],
            )
        }
    )
    wrong_policy_hash_query = query.model_copy(
        update={"source_selection_policy_hash": "f" * 64}
    )
    terms_owner = next(
        owner for owner in case.source_policy.owners if owner.family == "terms"
    )
    forged_owner = EconomicSourceOwnerV1(
        family="terms",
        source_id="synthetic-b",
        fact_manifest_hash=terms_owner.fact_manifest_hash,
        coverage_manifest_hash=terms_owner.coverage_manifest_hash,
    )
    forged_bindings = tuple(
        DatasetBindingV1(
            manifest_hash=binding.manifest_hash,
            decision_hash=binding.decision_hash,
            bundle_hash=binding.bundle_hash,
            role=binding.role,
            source_id=(
                "synthetic-b"
                if binding.manifest_hash == terms_owner.fact_manifest_hash
                else binding.source_id
            ),
        )
        for binding in case.source_policy.input_dataset_bindings
    ) + (
        DatasetBindingV1(
            manifest_hash=terms_owner.coverage_manifest_hash,
            decision_hash=next(
                binding.decision_hash
                for binding in case.source_policy.input_dataset_bindings
                if binding.manifest_hash == terms_owner.coverage_manifest_hash
            ),
            bundle_hash=next(
                binding.bundle_hash
                for binding in case.source_policy.input_dataset_bindings
                if binding.manifest_hash == terms_owner.coverage_manifest_hash
            ),
            role="economic_coverage",
            source_id="synthetic-b",
        ),
    )
    wrong_source = case.source_policy.model_copy(
        update={
            "owners": tuple(
                forged_owner if owner.family == "terms" else owner
                for owner in case.source_policy.owners
            ),
            "input_dataset_bindings": forged_bindings,
        }
    )

    attacks = (
        (query, changed_context, case.source_policy),
        (query, case.context, wrong_window),
        (query, case.context, wrong_security),
        (query, case.context, wrong_bindings),
        (query, case.context, wrong_source),
        (wrong_policy_hash_query, case.context, case.source_policy),
    )
    for attacked_query, attacked_context, attacked_policy in attacks:
        with pytest.raises(DatasetValidationError):
            select_market_records(attacked_query, attacked_context, attacked_policy)


def test_full_replay_rejects_omitted_chain_and_borrowed_clock() -> None:
    target = terms_record(173)
    other_base = terms_record(174)
    other_values = {
        name: getattr(other_base, name) for name in type(other_base).model_fields
    }
    other_values["security_id"] = uid(99)
    other = rebind_record_evidence(type(other_base), other_values)
    case = validated_case((target, other), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )
    proof = select_market_records(query, case.context, case.source_policy)
    reparsed = type(proof).model_validate_json(proof.model_dump_json())
    verify_market_selection(reparsed, case.context, case.source_policy)

    terms_dataset = proof.dataset_proofs[0]
    keep = tuple(
        selection
        for selection in terms_dataset.chain_selections
        if content_hash(other) not in selection.considered_record_hashes
    )
    omitted_dataset = terms_dataset.model_copy(
        update={
            "chain_selections": keep,
            "considered_record_hashes": tuple(
                item
                for item in terms_dataset.considered_record_hashes
                if item != content_hash(other)
            ),
            "selected_record_hashes": tuple(
                item
                for item in terms_dataset.selected_record_hashes
                if item != content_hash(other)
            ),
        }
    )
    omitted = proof.model_copy(
        update={
            "dataset_proofs": (omitted_dataset, *proof.dataset_proofs[1:]),
            "revision_selected_record_hashes": tuple(
                item
                for item in proof.revision_selected_record_hashes
                if item != content_hash(other)
            ),
        }
    )
    earlier_query = query.model_copy(
        update={"knowledge_cutoff": parse_utc("2020-04-01T00:00:00Z")}
    )
    borrowed = proof.model_copy(
        update={"query": earlier_query, "query_hash": content_hash(earlier_query)}
    )

    with pytest.raises(ValueError, match="selection proof"):
        verify_market_selection(omitted, case.context, case.source_policy)
    with pytest.raises(ValueError, match="selection proof"):
        verify_market_selection(borrowed, case.context, case.source_policy)


def test_empty_validated_inputs_authorize_nothing_not_a_no_events_claim() -> None:
    case = validated_case((), through="2020-05-15T00:00:00Z")
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)
    reference = decision_reference(query, case.context, case.source_policy)

    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()
    assert reference.selected_record_hashes == ()
    assert not hasattr(proof, "no_events")


def test_dataset_input_order_does_not_change_selection_identity() -> None:
    case = validated_case((terms_record(180),), through="2020-05-15T00:00:00Z")
    reordered_context = EconomicResolutionContext(
        datasets=tuple(reversed(case.context.datasets)),
        identity=case.context.identity,
        availability_policy=case.context.availability_policy,
        retained_evidence=case.context.retained_evidence,
        supporting_artifacts=case.context.supporting_artifacts,
    )
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    original = select_market_records(query, case.context, case.source_policy)
    reordered = select_market_records(query, reordered_context, case.source_policy)

    assert reordered == original
    assert content_hash(reordered) == content_hash(original)


def test_retained_identity_replay_rejects_query_from_another_context() -> None:
    base = validated_case((terms_record(181),), through="2020-05-15T00:00:00Z")
    changed = with_identity_assignments(
        base,
        (identity_assignment(5800, 21, known_at="2020-06-01T00:00:00Z"),),
    )
    borrowed_query = base.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    with pytest.raises(DatasetValidationError, match="identity_context_mismatch"):
        select_retained_economic_identity(
            "security", uid(21), borrowed_query, changed.context
        )


@pytest.mark.parametrize("query_kind", ["decision", "outcome"])
def test_partial_projection_uses_opaque_nested_evidence_locators(
    query_kind: str,
) -> None:
    case = evidence_bearing_partial_projection_case()
    query = (
        case.decision_query(
            "2021-01-02T00:00:00Z",
            "2021-01-02T00:00:00Z",
            "2021-01-01T00:00:00Z",
        )
        if query_kind == "decision"
        else case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    )
    raw = next(
        record
        for dataset in case.context.datasets
        for record in dataset.records
        if isinstance(record, EconomicSettlementVersionV1)
    )
    raw_json = raw.model_dump_json()
    assert raw.payload is not None
    raw_share = next(
        item
        for item in raw.payload.delivered_components
        if item.component_id == "known-shares"
    )
    raw_property = next(
        item
        for item in raw.payload.delivered_components
        if item.component_id == "source-property"
    )
    assert isinstance(raw_share, ShareComponentV1)
    assert isinstance(raw_property, UnsupportedPropertyComponentV1)

    projection = project_market_facts(query, case.context, case.source_policy)[0]

    projected_share = next(
        item
        for item in projection.known_components
        if item.component_id == "known-shares"
    )
    projected_property = next(
        item
        for item in projection.known_components
        if item.component_id == "source-property"
    )
    assert isinstance(projected_share, ShareComponentV1)
    assert isinstance(projected_property, UnsupportedPropertyComponentV1)
    assert projection.withheld_components[0].component_id == "shares"
    assert str(uid(22)) not in projection.model_dump_json()
    share_reference = projected_share.fraction_treatment.evidence_reference
    raw_share_reference = raw_share.fraction_treatment.evidence_reference
    assert share_reference is not None and raw_share_reference is not None
    assert share_reference.location == f"drift+sha256://{share_reference.content_hash}"
    assert projected_property.evidence_reference.location == (
        f"drift+sha256://{projected_property.evidence_reference.content_hash}"
    )
    assert (
        share_reference.model_copy(update={"location": raw_share_reference.location})
        == raw_share_reference
    )
    assert (
        projected_property.evidence_reference.model_copy(
            update={"location": raw_property.evidence_reference.location}
        )
        == raw_property.evidence_reference
    )
    assert (
        projected_share.model_copy(
            update={
                "fraction_treatment": projected_share.fraction_treatment.model_copy(
                    update={"evidence_reference": raw_share_reference}
                )
            }
        )
        == raw_share
    )
    assert (
        projected_property.model_copy(
            update={"evidence_reference": raw_property.evidence_reference}
        )
        == raw_property
    )
    assert raw.model_dump_json() == raw_json
    assert content_hash(raw) == projection.source_record_hash


def _reuse_assignment_subject(
    record: IdentityAssignmentVersionV1,
    source: IdentityAssignmentVersionV1,
) -> IdentityAssignmentVersionV1:
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values["source_namespace"] = source.source_namespace
    values["source_key"] = source.source_key
    return seal_record(type(record), values)


def test_competing_overlapping_identity_claims_fail_closed() -> None:
    assignment_a = identity_assignment(7000, 21)
    assignment_b = _reuse_assignment_subject(
        identity_assignment(7001, 22), assignment_a
    )
    terms = terms_record(190)
    base = validated_case((terms,), through="2020-05-15T00:00:00Z")
    case = with_identity_assignments(base, (assignment_a, assignment_b))
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)
    identity = next(
        item
        for item in proof.identity_proofs
        if item.identity_kind == "security" and item.identity_id == uid(21)
    )

    assert identity.status == "conflicting"
    assert set(identity.selected_assignment_hashes) == {
        content_hash(assignment_a),
        content_hash(assignment_b),
    }
    assert len(identity.selection_evidence_hashes) == 2
    assert content_hash(terms) in proof.revision_selected_record_hashes
    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()


def test_disjoint_or_future_competing_identity_claim_does_not_contaminate() -> None:
    ended_a = identity_assignment(7010, 21, ended_at="2020-02-01T00:00:00Z")
    later_b = _reuse_assignment_subject(
        identity_assignment(7011, 22, started_at="2020-03-01T00:00:00Z"),
        ended_a,
    )
    future_b = _reuse_assignment_subject(
        identity_assignment(7012, 22, known_at="2020-06-01T00:00:00Z"),
        ended_a,
    )
    base = validated_case((terms_record(191),), through="2020-05-15T00:00:00Z")
    for assignments, selected_count in (
        ((ended_a, later_b), 2),
        ((ended_a, future_b), 1),
    ):
        case = with_identity_assignments(base, assignments)
        query = case.decision_query(
            "2020-05-15T00:00:00Z",
            "2020-05-15T00:00:00Z",
            "2020-05-15T00:00:00Z",
        )
        proof = select_market_records(query, case.context, case.source_policy)
        identity = next(
            item
            for item in proof.identity_proofs
            if item.identity_kind == "security" and item.identity_id == uid(21)
        )
        assert identity.status == "known"
        assert len(identity.selected_assignment_hashes) == selected_count
        assert len(identity.selection_evidence_hashes) == 2
        assert proof.raw_materializable_record_hashes
        assert proof.projection_hashes


def test_ambiguous_assignment_interval_overlap_fails_closed() -> None:
    assignment_a = identity_assignment(7020, 21)
    evidence_a = assignment_a.revision.source_artifact
    values_a = {
        name: getattr(assignment_a, name) for name in type(assignment_a).model_fields
    }
    values_a["effective_interval"] = assignment_a.effective_interval.model_copy(
        update={
            "end": bounded_boundary(
                "2020-03-01T00:00:00Z",
                "2020-04-01T00:00:00Z",
                evidence_a,
            )
        }
    )
    assignment_a = seal_record(type(assignment_a), values_a)
    assignment_b = identity_assignment(7021, 22)
    evidence_b = assignment_b.revision.source_artifact
    values_b = {
        name: getattr(assignment_b, name) for name in type(assignment_b).model_fields
    }
    values_b["effective_interval"] = assignment_b.effective_interval.model_copy(
        update={
            "start": bounded_boundary(
                "2020-03-15T00:00:00Z",
                "2020-04-15T00:00:00Z",
                evidence_b,
            )
        }
    )
    assignment_b = _reuse_assignment_subject(
        seal_record(type(assignment_b), values_b), assignment_a
    )
    base = validated_case((terms_record(192),), through="2020-05-15T00:00:00Z")
    case = with_identity_assignments(base, (assignment_a, assignment_b))
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)

    assert proof.identity_proofs[0].status == "conflicting"
    assert proof.identity_proofs[0].reasons == (
        "competing_identity_assignment_overlap_indeterminate",
    )
    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()


def test_unassigned_prefix_stops_at_different_selected_identity() -> None:
    initial_a = identity_assignment(7030, 21)
    corrected_b = revise_identity_assignment(
        initial_a, 7031, "2020-02-01T00:00:00Z", identity_id=22
    )
    unassigned_a = revise_identity_assignment(
        corrected_b,
        7032,
        "2020-03-01T00:00:00Z",
        identity_id=21,
        effect=IdentityAssignmentEffect.UNASSIGNED,
    )
    terms = terms_record(193)
    base = validated_case((terms,), through="2020-05-15T00:00:00Z")
    case = with_identity_assignments(base, (initial_a, corrected_b, unassigned_a))
    query = case.decision_query(
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
        "2020-05-15T00:00:00Z",
    )

    proof = select_market_records(query, case.context, case.source_policy)
    identity = proof.identity_proofs[0]

    assert identity.status == "unknown"
    assert set(identity.selected_assignment_hashes) == {
        content_hash(corrected_b),
        content_hash(unassigned_a),
    }
    assert len(identity.selection_evidence_hashes) == 2
    assert content_hash(terms) in proof.revision_selected_record_hashes
    assert proof.raw_materializable_record_hashes == ()
    assert proof.projection_hashes == ()


@pytest.mark.parametrize("family", ["effect", "settlement"])
def test_actual_contradiction_is_intrinsic_across_requested_channels(
    family: Literal["effect", "settlement"],
) -> None:
    case, record, _ = multichannel_actual_case(family)
    for query_kind in ("decision", "outcome"):
        for channel in (public_channel(), vendor_channel()):
            query = (
                case.decision_query(
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    requested_channel=channel,
                )
                if query_kind == "decision"
                else case.outcome_query(
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    requested_channel=channel,
                )
            )
            proof = select_market_records(query, case.context, case.source_policy)
            projection = next(
                item
                for item in project_market_facts(
                    query, case.context, case.source_policy
                )
                if item.source_record_hash == content_hash(record)
            )
            applicability = next(
                item
                for item in proof.applicability
                if item.source_record_hash == content_hash(record)
            )
            assert applicability.status == "indeterminate"
            assert applicability.reasons == ("actual_claim_predates_occurrence",)
            assert projection.applicability == applicability
            assert content_hash(record) not in proof.raw_materializable_record_hashes


def test_genuine_multichannel_correction_recovers_actual_authority() -> None:
    case, initial, correction = multichannel_actual_case("effect", corrected=True)
    assert correction is not None
    for query_kind in ("decision", "outcome"):
        for channel in (public_channel(), vendor_channel()):
            query = (
                case.decision_query(
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    requested_channel=channel,
                )
                if query_kind == "decision"
                else case.outcome_query(
                    "2020-07-02T00:00:00Z",
                    "2020-07-02T00:00:00Z",
                    requested_channel=channel,
                )
            )
            proof = select_market_records(query, case.context, case.source_policy)
            assert content_hash(initial) not in proof.raw_materializable_record_hashes
            assert content_hash(correction) in proof.raw_materializable_record_hashes


@pytest.mark.parametrize("evidence_kind", ["unknown", "indeterminate", "unapproved"])
def test_untrusted_other_channel_evidence_does_not_create_contradiction(
    evidence_kind: Literal["unknown", "indeterminate", "unapproved"],
) -> None:
    case = multichannel_untrusted_evidence_case(evidence_kind)
    query = case.outcome_query("2020-07-02T00:00:00Z", "2020-07-02T00:00:00Z")

    proof = select_market_records(query, case.context, case.source_policy)
    effect_hash = next(
        content_hash(record)
        for dataset in case.context.datasets
        for record in dataset.records
        if record.source_key.family == "effect"
    )
    applicability = next(
        item for item in proof.applicability if item.source_record_hash == effect_hash
    )

    assert applicability.status == "in_window"
    assert effect_hash in proof.raw_materializable_record_hashes


@pytest.mark.parametrize(
    "entrypoint",
    ["selection", "projection", "decision_reference", "outcome_reference"],
)
@pytest.mark.parametrize(
    "policy_defect",
    ["duplicate_owner", "missing_owner", "duplicate_binding"],
)
def test_public_selection_pipeline_rejects_constructor_bypassed_policy_shape(
    entrypoint: Literal[
        "selection", "projection", "decision_reference", "outcome_reference"
    ],
    policy_defect: Literal["duplicate_owner", "missing_owner", "duplicate_binding"],
) -> None:
    case = validated_case((terms_record(9100),))
    owners = case.source_policy.owners
    bindings = case.source_policy.input_dataset_bindings
    if policy_defect == "duplicate_owner":
        owners = (*owners, owners[-1])
    elif policy_defect == "missing_owner":
        owners = owners[:-1]
    else:
        bindings = (*bindings, bindings[-1])
    forged_policy = type(case.source_policy).model_construct(
        schema_version=case.source_policy.schema_version,
        policy_id=case.source_policy.policy_id,
        policy_version=case.source_policy.policy_version,
        security_id=case.source_policy.security_id,
        action_kinds=case.source_policy.action_kinds,
        scope=case.source_policy.scope,
        history_start=case.source_policy.history_start,
        through=case.source_policy.through,
        owners=owners,
        input_dataset_bindings=bindings,
    )
    if entrypoint == "decision_reference":
        decision_query = case.decision_query(
            "2021-01-02T00:00:00Z",
            "2021-01-02T00:00:00Z",
            "2021-01-01T00:00:00Z",
        ).model_copy(
            update={"source_selection_policy_hash": content_hash(forged_policy)}
        )
        with pytest.raises(ValueError, match="owner|binding"):
            decision_reference(decision_query, case.context, forged_policy)
        return
    outcome_query = case.outcome_query(
        "2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z"
    ).model_copy(update={"source_selection_policy_hash": content_hash(forged_policy)})

    with pytest.raises(ValueError, match="owner|binding"):
        if entrypoint == "selection":
            select_market_records(outcome_query, case.context, forged_policy)
        elif entrypoint == "projection":
            project_market_facts(outcome_query, case.context, forged_policy)
        else:
            outcome_reference(outcome_query, case.context, forged_policy)
