"""Final M1c regressions for validation, replay, and temporal composition."""

from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Literal

import pytest
from economic_test_support import (
    EconomicHarness,
    _fixture_artifact_references,
    bounded_availability,
    bounded_boundary,
    bounded_effect_record,
    closed_liquidation_case,
    coverage_record,
    economic_dataset,
    effect_record,
    parse_utc,
    public_availability,
    rebind_record_evidence,
    settlement_record,
    source_policy,
    support_bytes,
    terms_record,
    validated_case,
)

from drift.datasets.hashing import manifest_hash
from drift.domain.assertions import BoundaryShape, TemporalBoundaryClaimV1
from drift.domain.dataset_validation import (
    DatasetValidationError,
    ValidationResult,
    ValidationScope,
)
from drift.domain.economic_common import ActionKind, EconomicAssociationV1
from drift.domain.economic_coverage import (
    DatasetBindingV1,
    EconomicSourceOwnerV1,
    EconomicSourceSelectionPolicyV1,
)
from drift.domain.economic_events import (
    CorporateActionTermsVersionV1,
    EconomicEffectVersionV1,
    EconomicRecordV1,
    EconomicSettlementVersionV1,
)
from drift.domain.economic_queries import MarketSelectionQueryV1
from drift.domain.temporal import SourcePrecision
from drift.markets.economic_outcomes import resolve_economic_facts
from drift.markets.economic_selection import (
    decision_reference,
    outcome_reference,
    project_market_facts,
    resolve_decision_projections,
    resolve_decision_records,
    resolve_outcome_projections,
    resolve_outcome_records,
    select_market_records,
)
from drift.markets.economic_validation import (
    EconomicResolutionContext,
    validate_economic_context,
    validate_economic_dataset,
)
from drift.markets.validation import validate_identity_dataset
from drift.serialization.canonical import content_hash


def _query(
    case: EconomicHarness,
    kind: Literal["decision", "outcome"],
    *,
    horizon: str,
    cutoff: str,
    history_start: str | None = None,
) -> tuple[EconomicSourceSelectionPolicyV1, MarketSelectionQueryV1]:
    policy = case.source_policy
    if history_start is not None:
        policy = type(policy).model_validate(
            {
                **policy.model_dump(mode="python"),
                "history_start": parse_utc(history_start),
            }
        )
    query: MarketSelectionQueryV1 = (
        case.decision_query(horizon, cutoff, horizon)
        if kind == "decision"
        else case.outcome_query(horizon, cutoff)
    )
    if history_start is not None:
        query = type(query).model_validate(
            {
                **query.model_dump(mode="python"),
                "history_start": parse_utc(history_start),
                "source_selection_policy_hash": content_hash(policy),
            }
        )
    return policy, query


def _economic_records(case: EconomicHarness) -> tuple[EconomicRecordV1, ...]:
    return tuple(
        record
        for dataset in case.context.datasets
        for record in dataset.records
        if isinstance(
            record,
            CorporateActionTermsVersionV1
            | EconomicEffectVersionV1
            | EconomicSettlementVersionV1,
        )
    )


def _failed_economic_case() -> EconomicHarness:
    base = validated_case(())
    old = next(
        item
        for item in base.context.datasets
        if item.manifest.dataset_role.name == "economic_settlement"
    )
    manifest_values = old.manifest.model_dump(mode="python")
    manifest_values["partitions"][0]["row_count"] = 1
    manifest = type(old.manifest).model_validate(manifest_values)
    decision, parsed = validate_economic_dataset(
        manifest, old.verified_artifacts, old.validation_run
    )
    assert decision.result is ValidationResult.FAIL
    assert {item.code for item in decision.findings} == {"economic_row_count_mismatch"}
    bundle_values = old.bundle.model_dump(mode="python")
    bundle_values["members"][0]["manifest_hash"] = manifest_hash(manifest)
    bundle_values["members"][0]["validation_decision_hash"] = content_hash(decision)
    failed = replace(
        old,
        manifest=manifest,
        decision=decision,
        records=parsed,
        bundle=type(old.bundle).model_validate(bundle_values),
    )
    facts = tuple(
        failed if item is old else item
        for item in base.context.datasets
        if item.manifest.dataset_role.name != "economic_coverage"
    )
    families: tuple[Literal["terms", "effect", "settlement"], ...] = (
        "terms",
        "effect",
        "settlement",
    )
    coverages = tuple(
        coverage_record(
            9500 + index,
            family=family,
            target_manifest_hash=manifest_hash(dataset.manifest),
            inventory_artifact_hashes=dataset.decision.validated_artifact_hashes,
            inventory_record_hashes=dataset.decision.validated_record_hashes,
            snapshot_at="2021-01-02T00:00:00Z",
        )
        for index, (family, dataset) in enumerate(zip(families, facts, strict=True))
    )
    coverage = economic_dataset("economic_coverage", coverages)
    datasets = (*facts, coverage)
    references = {}
    for dataset in datasets:
        for reference in _fixture_artifact_references(
            (
                dataset.records,
                dataset.manifest.source,
                dataset.manifest.acquisition,
                dataset.manifest.license,
            )
        ):
            references[reference.content_hash] = reference
    context = EconomicResolutionContext(
        datasets=datasets,
        identity=base.context.identity,
        availability_policy=base.context.availability_policy,
        retained_evidence={},
        supporting_artifacts=tuple(
            support_bytes(reference) for reference in references.values()
        ),
    )
    bindings = tuple(
        DatasetBindingV1(
            manifest_hash=manifest_hash(item.manifest),
            decision_hash=content_hash(item.decision),
            bundle_hash=content_hash(item.bundle),
            role=item.manifest.dataset_role.name,
            source_id=item.manifest.source.source_id,
        )
        for item in datasets
    )
    owners = tuple(
        EconomicSourceOwnerV1(
            family=family,
            source_id="synthetic-a",
            fact_manifest_hash=manifest_hash(dataset.manifest),
            coverage_manifest_hash=manifest_hash(coverage.manifest),
        )
        for family, dataset in zip(families, facts, strict=True)
    )
    policy = source_policy(
        base.source_policy.security_id,
        bindings,
        owners,
        parse_utc("2020-01-01T00:00:00Z"),
        parse_utc("2021-01-01T00:00:00Z"),
    )
    return EconomicHarness(context=context, source_policy=policy)


def _failed_identity_case() -> EconomicHarness:
    base = validated_case((settlement_record(9600),))
    identity = base.context.identity
    manifest_values = identity.manifest.model_dump(mode="python")
    manifest_values["partitions"][0]["row_count"] += 1
    manifest = type(identity.manifest).model_validate(manifest_values)
    decision = validate_identity_dataset(
        manifest, identity.verified_artifacts, identity.validation_run
    )
    assert decision.result is ValidationResult.FAIL
    assert {item.code for item in decision.findings} == {
        "identity_record_count_mismatch"
    }
    bundle_values = identity.bundle.model_dump(mode="python")
    bundle_values["members"][0]["manifest_hash"] = manifest_hash(manifest)
    bundle_values["members"][0]["validation_decision_hash"] = content_hash(decision)
    failed_identity = replace(
        identity,
        manifest=manifest,
        decision=decision,
        bundle=type(identity.bundle).model_validate(bundle_values),
    )
    return EconomicHarness(
        context=replace(base.context, identity=failed_identity),
        source_policy=base.source_policy,
    )


@pytest.mark.parametrize("kind", ["decision", "outcome"])
def test_failed_economic_dataset_never_authorizes_a_consumer_role(
    kind: Literal["decision", "outcome"],
) -> None:
    case = _failed_economic_case()
    _, query = _query(
        case,
        kind,
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z" if kind == "outcome" else "2021-01-01T00:00:00Z",
    )

    with pytest.raises(
        DatasetValidationError, match="economic_validation_decision_not_pass"
    ):
        select_market_records(query, case.context, case.source_policy)


@pytest.mark.parametrize("kind", ["decision", "outcome"])
def test_failed_identity_dataset_never_authorizes_a_consumer_role(
    kind: Literal["decision", "outcome"],
) -> None:
    case = _failed_identity_case()
    _, query = _query(
        case,
        kind,
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z" if kind == "outcome" else "2021-01-01T00:00:00Z",
    )

    with pytest.raises(
        DatasetValidationError, match="identity_validation_decision_not_pass"
    ):
        select_market_records(query, case.context, case.source_policy)


@pytest.mark.parametrize("kind", ["decision", "outcome"])
def test_exact_empty_pass_remains_valid_for_both_consumer_roles(
    kind: Literal["decision", "outcome"],
) -> None:
    case = validated_case(())
    settlement = next(
        item
        for item in case.context.datasets
        if item.manifest.dataset_role.name == "economic_settlement"
    )
    query = (
        case.decision_query(
            "2021-01-02T00:00:00Z",
            "2021-01-02T00:00:00Z",
            "2021-01-01T00:00:00Z",
        )
        if kind == "decision"
        else case.outcome_query("2021-01-01T00:00:00Z", "2021-01-02T00:00:00Z")
    )

    validate_economic_context(case.context)
    proof = select_market_records(query, case.context, case.source_policy)
    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert settlement.decision.result is ValidationResult.PASS
    assert settlement.decision.validation_scope is ValidationScope.MANIFEST_ONLY
    assert proof.raw_materializable_record_hashes == ()
    assert {item.status for item in result.coverage_results} == {"complete"}
    assert result.evidence_completeness == "known"


class _ChangingMapping[T](Mapping[str, T]):
    def __init__(self, key: str, first: T, later: T) -> None:
        self.key = key
        self.first = first
        self.later = later
        self.reads = 0

    def __iter__(self) -> Iterator[str]:
        return iter((self.key,))

    def __len__(self) -> int:
        return 1

    def __getitem__(self, key: str) -> T:
        if key != self.key:
            raise KeyError(key)
        self.reads += 1
        return self.first if self.reads == 1 else self.later


def test_decision_record_resolver_returns_its_one_verified_snapshot() -> None:
    authentic = terms_record(9700)
    substitute = terms_record(9701)
    case = validated_case((authentic,), through="2020-07-01T00:00:00Z")
    query = case.decision_query(
        "2020-07-01T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-07-01T00:00:00Z",
    )
    reference = decision_reference(query, case.context, case.source_policy)
    key = content_hash(authentic)
    supplied = _ChangingMapping(key, authentic, substitute)

    assert resolve_decision_records(
        reference, query, {key: authentic}, case.context, case.source_policy
    ) == {key: authentic}
    resolved = resolve_decision_records(
        reference, query, supplied, case.context, case.source_policy
    )
    assert supplied.reads == 1
    assert resolved[key] == authentic
    assert content_hash(resolved[key]) == key
    with pytest.raises(ValueError, match="record hash"):
        resolve_decision_records(
            reference, query, {key: substitute}, case.context, case.source_policy
        )


def test_outcome_record_resolver_returns_its_one_verified_snapshot() -> None:
    authentic = terms_record(9710)
    substitute = terms_record(9711)
    case = validated_case((authentic,), through="2020-07-01T00:00:00Z")
    query = case.outcome_query("2020-07-01T00:00:00Z", "2020-07-02T00:00:00Z")
    reference = outcome_reference(query, case.context, case.source_policy)
    key = content_hash(authentic)
    supplied = _ChangingMapping(key, authentic, substitute)

    assert resolve_outcome_records(
        reference, query, {key: authentic}, case.context, case.source_policy
    ) == {key: authentic}
    resolved = resolve_outcome_records(
        reference, query, supplied, case.context, case.source_policy
    )
    assert supplied.reads == 1
    assert resolved[key] == authentic
    assert content_hash(resolved[key]) == key
    with pytest.raises(ValueError, match="record hash"):
        resolve_outcome_records(
            reference, query, {key: substitute}, case.context, case.source_policy
        )


def test_decision_projection_resolver_returns_its_one_verified_snapshot() -> None:
    case = validated_case((terms_record(9720),), through="2020-07-01T00:00:00Z")
    query = case.decision_query(
        "2020-07-01T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-07-01T00:00:00Z",
    )
    reference = decision_reference(query, case.context, case.source_policy)
    authentic = project_market_facts(query, case.context, case.source_policy)[0]
    substitute = authentic.model_copy(
        update={"optional_context_reasons": ("substituted",)}
    )
    key = content_hash(authentic)
    supplied = _ChangingMapping(key, authentic, substitute)

    assert resolve_decision_projections(
        reference, query, {key: authentic}, case.context, case.source_policy
    ) == {key: authentic}
    resolved = resolve_decision_projections(
        reference, query, supplied, case.context, case.source_policy
    )
    assert supplied.reads == 1
    assert resolved[key] == authentic
    assert content_hash(resolved[key]) == key
    with pytest.raises(ValueError, match="projection hash"):
        resolve_decision_projections(
            reference, query, {key: substitute}, case.context, case.source_policy
        )


def test_outcome_projection_resolver_returns_its_one_verified_snapshot() -> None:
    case = validated_case((terms_record(9730),), through="2020-07-01T00:00:00Z")
    query = case.outcome_query("2020-07-01T00:00:00Z", "2020-07-02T00:00:00Z")
    reference = outcome_reference(query, case.context, case.source_policy)
    authentic = project_market_facts(query, case.context, case.source_policy)[0]
    substitute = authentic.model_copy(
        update={"optional_context_reasons": ("substituted",)}
    )
    key = content_hash(authentic)
    supplied = _ChangingMapping(key, authentic, substitute)

    assert resolve_outcome_projections(
        reference, query, {key: authentic}, case.context, case.source_policy
    ) == {key: authentic}
    resolved = resolve_outcome_projections(
        reference, query, supplied, case.context, case.source_policy
    )
    assert supplied.reads == 1
    assert resolved[key] == authentic
    assert content_hash(resolved[key]) == key
    with pytest.raises(ValueError, match="projection hash"):
        resolve_outcome_projections(
            reference, query, {key: substitute}, case.context, case.source_policy
        )


def _bounded_settlement(
    suffix: int,
    lower: str,
    upper: str,
    availability_lower: str,
    availability_upper: str,
    *,
    occurrence_id: str,
) -> EconomicSettlementVersionV1:
    base = settlement_record(
        suffix,
        occurrence_id=occurrence_id,
        settled_at=lower,
        known_at=availability_upper,
    )
    evidence = base.revision.source_artifact
    values = {name: getattr(base, name) for name in type(base).model_fields}
    availability = (
        public_availability(availability_lower, evidence)
        if availability_lower == availability_upper
        else bounded_availability(availability_lower, availability_upper, evidence)
    )
    values["revision"] = base.revision.model_copy(
        update={"availability": (availability,)}
    )
    values["settled_time"] = bounded_boundary(lower, upper, evidence)
    return rebind_record_evidence(type(base), values)


def _bounded_actual(
    family: Literal["effect", "settlement"], suffix: int, upper: str
) -> EconomicEffectVersionV1 | EconomicSettlementVersionV1:
    if family == "effect":
        return bounded_effect_record(
            suffix,
            "2020-06-01T00:00:00Z",
            upper,
            "2020-06-01T00:00:00Z",
            "2020-06-05T00:00:00Z",
        )
    return _bounded_settlement(
        suffix,
        "2020-06-01T00:00:00Z",
        upper,
        "2020-06-01T00:00:00Z",
        "2020-06-05T00:00:00Z",
        occurrence_id=f"bounded-{suffix}",
    )


@pytest.mark.parametrize("kind", ["decision", "outcome"])
@pytest.mark.parametrize("family", ["effect", "settlement"])
def test_before_window_actual_after_finite_cutoff_is_indeterminate(
    kind: Literal["decision", "outcome"],
    family: Literal["effect", "settlement"],
) -> None:
    record = _bounded_actual(family, 9800, "2020-06-10T00:00:00Z")
    case = validated_case((record,), through="2020-07-01T00:00:00Z")
    policy, query = _query(
        case,
        kind,
        horizon="2020-07-01T00:00:00Z",
        cutoff="2020-06-05T00:00:00Z",
        history_start="2020-06-20T00:00:00Z",
    )

    proof = select_market_records(query, case.context, policy)
    applicability = next(
        item
        for item in proof.applicability
        if item.source_record_hash == content_hash(record)
    )

    assert applicability.status == "indeterminate"
    assert content_hash(record) not in proof.raw_materializable_record_hashes
    if family == "effect":
        assert resolve_economic_facts(query, case.context, policy).claim_status == (
            "unknown"
        )


@pytest.mark.parametrize("kind", ["decision", "outcome"])
@pytest.mark.parametrize("family", ["effect", "settlement"])
@pytest.mark.parametrize("upper", ["2020-06-04T00:00:00Z", "2020-06-05T00:00:00Z"])
def test_before_window_actual_at_or_before_finite_cutoff_remains_authoritative(
    kind: Literal["decision", "outcome"],
    family: Literal["effect", "settlement"],
    upper: str,
) -> None:
    record = _bounded_actual(family, 9810, upper)
    case = validated_case((record,), through="2020-07-01T00:00:00Z")
    policy, query = _query(
        case,
        kind,
        horizon="2020-07-01T00:00:00Z",
        cutoff="2020-06-05T00:00:00Z",
        history_start="2020-06-20T00:00:00Z",
    )

    proof = select_market_records(query, case.context, policy)
    applicability = next(
        item
        for item in proof.applicability
        if item.source_record_hash == content_hash(record)
    )

    assert applicability.status == "before_window"
    assert content_hash(record) in proof.raw_materializable_record_hashes


def test_only_settlements_at_or_after_history_start_emit_delivery_groups() -> None:
    before = settlement_record(
        9820,
        occurrence_id="before",
        settled_at="2020-01-15T00:00:00Z",
    )
    at = settlement_record(
        9821,
        occurrence_id="at",
        settled_at="2020-02-01T00:00:00Z",
    )
    after = settlement_record(
        9822,
        occurrence_id="after",
        settled_at="2020-03-01T00:00:00Z",
    )
    case = validated_case((before, at, after), through="2020-12-31T00:00:00Z")
    policy, query = _query(
        case,
        "outcome",
        horizon="2020-12-31T00:00:00Z",
        cutoff="2021-01-01T00:00:00Z",
        history_start="2020-02-01T00:00:00Z",
    )

    result = resolve_economic_facts(query, case.context, policy)

    assert {group.native_occurrence_id for group in result.delivery_groups} == {
        "at",
        "after",
    }
    assert content_hash(before) not in {
        item_hash
        for group in result.delivery_groups
        for item_hash in group.contributing_record_hashes
    }


def test_before_window_payment_still_supports_later_action_closure() -> None:
    case = closed_liquidation_case()
    payment = next(
        item
        for item in _economic_records(case)
        if isinstance(item, EconomicSettlementVersionV1)
    )
    policy, query = _query(
        case,
        "outcome",
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z",
        history_start="2020-06-20T00:00:00Z",
    )

    result = resolve_economic_facts(query, case.context, policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert result.delivery_groups == ()
    assert action.status == "closed"
    assert content_hash(payment) in action.covered_settlement_hashes


def _assert_same_occurrence_conflict(
    case: EconomicHarness,
    query: MarketSelectionQueryV1,
    expected_hashes: set[str],
) -> None:
    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert result.delivery_groups == ()
    assert set(result.uncomposed_settlement_hashes) == expected_hashes
    assert "same_occurrence_economics_conflicting" in result.reasons


def test_before_window_same_occurrence_report_still_constrains_comparison() -> None:
    before = settlement_record(
        9823,
        occurrence_id="same-payment-lower",
        settled_at="2020-01-15T00:00:00Z",
        known_at="2020-01-16T00:00:00Z",
    )
    inside = settlement_record(
        9824,
        occurrence_id="same-payment-lower",
        settled_at="2020-02-15T00:00:00Z",
        known_at="2020-02-16T00:00:00Z",
    )
    case = validated_case((before, inside))
    policy, query = _query(
        case,
        "outcome",
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z",
        history_start="2020-02-01T00:00:00Z",
    )
    rebound = EconomicHarness(context=case.context, source_policy=policy)

    _assert_same_occurrence_conflict(
        rebound, query, {content_hash(before), content_hash(inside)}
    )


def test_after_horizon_same_occurrence_report_still_constrains_comparison() -> None:
    inside = settlement_record(
        9825,
        occurrence_id="same-payment-upper",
        settled_at="2020-01-15T00:00:00Z",
        known_at="2020-01-16T00:00:00Z",
    )
    after = settlement_record(
        9826,
        occurrence_id="same-payment-upper",
        settled_at="2020-02-15T00:00:00Z",
        known_at="2020-02-16T00:00:00Z",
    )
    case = validated_case((inside, after), through="2020-01-31T00:00:00Z")
    query = case.outcome_query("2020-01-31T00:00:00Z", "2020-02-17T00:00:00Z")

    _assert_same_occurrence_conflict(
        case, query, {content_hash(inside), content_hash(after)}
    )


def test_future_unavailable_same_occurrence_report_does_not_conflict() -> None:
    inside = settlement_record(
        9827,
        occurrence_id="same-payment-future",
        settled_at="2020-01-15T00:00:00Z",
        known_at="2020-01-16T00:00:00Z",
    )
    future = settlement_record(
        9828,
        occurrence_id="same-payment-future",
        settled_at="2020-02-15T00:00:00Z",
        known_at="2020-03-01T00:00:00Z",
    )
    case = validated_case((inside, future), through="2020-01-31T00:00:00Z")
    query = case.outcome_query("2020-01-31T00:00:00Z", "2020-02-17T00:00:00Z")

    proof = select_market_records(query, case.context, case.source_policy)
    projections = project_market_facts(query, case.context, case.source_policy)
    result = resolve_economic_facts(query, case.context, case.source_policy)

    assert content_hash(inside) in proof.revision_selected_record_hashes
    assert content_hash(future) not in proof.revision_selected_record_hashes
    assert {item.source_record_hash for item in projections} == {content_hash(inside)}
    assert content_hash(future) not in result.uncomposed_settlement_hashes
    assert "same_occurrence_economics_conflicting" not in result.reasons
    settlement_coverage = next(
        item for item in result.coverage_results if item.family == "settlement"
    )
    assert settlement_coverage.status == "unknown"
    assert "source_coverage_incomplete" in result.reasons


def _indeterminate_later_settlement(
    suffix: int,
    *,
    terms: CorporateActionTermsVersionV1 | None = None,
) -> EconomicSettlementVersionV1:
    later = _bounded_settlement(
        suffix,
        "2020-06-30T00:00:00Z",
        "2020-08-01T00:00:00Z",
        "2020-08-02T00:00:00Z",
        "2020-08-02T00:00:00Z",
        occurrence_id=f"possible-later-{suffix}",
    )
    assert later.payload is not None
    values = {name: getattr(later, name) for name in type(later).model_fields}
    values["payload"] = later.payload.model_copy(
        update={"action_kind": ActionKind.LIQUIDATION}
    )
    if terms is not None:
        values["terms_association"] = EconomicAssociationV1(
            kind="identified", target=terms.source_key
        )
    return rebind_record_evidence(type(later), values)


def test_indeterminate_possible_later_payment_withholds_closure_not_old_payment() -> (
    None
):
    base = closed_liquidation_case()
    records = _economic_records(base)
    later = _indeterminate_later_settlement(9830)
    case = validated_case(
        (*records, later),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-02T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert action.status == "unknown"
    assert "unresolved_later_installment_prevents_closure" in action.reasons
    assert content_hash(later) in result.uncomposed_settlement_hashes
    assert all(
        content_hash(later) not in group.contributing_record_hashes
        for group in result.delivery_groups
    )
    assert any(
        group.native_occurrence_id == "liquidation-payment"
        for group in result.delivery_groups
    )


def _opposing_indeterminate_effect(
    suffix: int,
    terms: CorporateActionTermsVersionV1,
    *,
    unknown_time: bool = False,
) -> EconomicEffectVersionV1:
    effect = bounded_effect_record(
        suffix,
        "2020-06-30T00:00:00Z",
        "2020-08-01T00:00:00Z",
        "2020-08-02T00:00:00Z",
        "2020-08-03T00:00:00Z",
    )
    assert effect.payload is not None
    values = {name: getattr(effect, name) for name in type(effect).model_fields}
    values["terms_association"] = EconomicAssociationV1(
        kind="identified", target=terms.source_key
    )
    values["payload"] = effect.payload.model_copy(
        update={
            "action_kind": ActionKind.LIQUIDATION,
            "claim_status": "continuing",
        }
    )
    if unknown_time:
        values["effective_time"] = TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.UNKNOWN,
            lower_bound=None,
            upper_bound=None,
            source_precision=SourcePrecision.UNKNOWN,
            source_time_label=None,
            source_timezone=None,
            evidence_reference=None,
        )
    return rebind_record_evidence(type(effect), values)


@pytest.mark.parametrize("unknown_time", [False, True])
def test_indeterminate_opposing_effect_withholds_claim_across_distinct_action(
    unknown_time: bool,
) -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    other_terms = terms_record(9840, action_kind=ActionKind.LIQUIDATION)
    opposing = _opposing_indeterminate_effect(
        9841, other_terms, unknown_time=unknown_time
    )
    case = validated_case(
        (*records, other_terms, opposing),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-03T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-03T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)
    original = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert result.claim_status == "unknown"
    assert "claim_effect_chronology_indeterminate" in result.reasons
    assert original.status == "closed"
    assert any(
        item.source_record_hash == content_hash(opposing)
        and item.effective_status == "indeterminate"
        for item in result.effect_projections
    )


def test_indeterminate_same_action_effect_withholds_closure_without_authority() -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    terms = next(
        item for item in records if isinstance(item, CorporateActionTermsVersionV1)
    )
    opposing = _opposing_indeterminate_effect(9845, terms)
    case = validated_case(
        (*records, opposing),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-03T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-03T00:00:00Z")

    proof = select_market_records(query, case.context, case.source_policy)
    result = resolve_economic_facts(query, case.context, case.source_policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert action.status == "unknown"
    assert action.reasons == ("indeterminate_action_fact_prevents_closure",)
    assert content_hash(opposing) not in proof.raw_materializable_record_hashes
    assert any(
        item.source_record_hash == content_hash(opposing)
        and item.effective_status == "indeterminate"
        for item in result.effect_projections
    )


@pytest.mark.parametrize("kind", ["cancelled_action", "unknown"])
def test_indeterminate_nonoccurred_effect_retains_fact_without_claim_change(
    kind: Literal["cancelled_action", "unknown"],
) -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    record = effect_record(
        9844,
        kind=kind,
        effective_at="2020-06-30T00:00:00Z",
        known_at="2020-08-03T00:00:00Z",
    )
    values = {name: getattr(record, name) for name in type(record).model_fields}
    values["effective_time"] = bounded_boundary(
        "2020-06-30T00:00:00Z",
        "2020-08-01T00:00:00Z",
        record.revision.source_artifact,
    )
    record = rebind_record_evidence(type(record), values)
    case = validated_case((*records, record), through="2020-07-15T00:00:00Z")
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-03T00:00:00Z")

    proof = select_market_records(query, case.context, case.source_policy)
    result = resolve_economic_facts(query, case.context, case.source_policy)
    record_hash = content_hash(record)

    applicability = next(
        item for item in proof.applicability if item.source_record_hash == record_hash
    )
    assert applicability.status == "indeterminate"
    assert record_hash not in proof.raw_materializable_record_hashes
    assert result.claim_status == "extinguished"
    assert (record_hash in result.cancelled_action_hashes) is (
        kind == "cancelled_action"
    )
    assert (record_hash in result.unknown_effect_hashes) is (kind == "unknown")
    assert any(
        group.native_occurrence_id == "liquidation-payment"
        for group in result.delivery_groups
    )


def test_earlier_indeterminate_continuing_does_not_erase_terminal() -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    terms = next(
        item for item in records if isinstance(item, CorporateActionTermsVersionV1)
    )
    earlier = bounded_effect_record(
        9846,
        "2020-05-01T00:00:00Z",
        "2020-05-10T00:00:00Z",
        "2020-05-11T00:00:00Z",
        "2020-05-12T00:00:00Z",
    )
    assert earlier.payload is not None
    values = {name: getattr(earlier, name) for name in type(earlier).model_fields}
    values["terms_association"] = EconomicAssociationV1(
        kind="identified", target=terms.source_key
    )
    values["payload"] = earlier.payload.model_copy(
        update={
            "action_kind": ActionKind.LIQUIDATION,
            "claim_status": "continuing",
        }
    )
    earlier = rebind_record_evidence(type(earlier), values)
    case = validated_case((*records, earlier))
    policy, query = _query(
        case,
        "outcome",
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z",
        history_start="2020-05-05T00:00:00Z",
    )

    proof = select_market_records(query, case.context, policy)
    result = resolve_economic_facts(query, case.context, policy)
    action = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    applicability = next(
        item
        for item in proof.applicability
        if item.source_record_hash == content_hash(earlier)
    )
    assert applicability.status == "indeterminate"
    assert content_hash(earlier) not in proof.raw_materializable_record_hashes
    assert result.claim_status == "extinguished"
    assert "claim_effect_chronology_indeterminate" not in result.reasons
    assert action.status == "closed"


def test_definitely_earlier_indeterminate_terminal_preserves_resurrection_veto() -> (
    None
):
    terms = terms_record(9847, action_kind=ActionKind.LIQUIDATION)
    link = EconomicAssociationV1(kind="identified", target=terms.source_key)
    prior_terminal = bounded_effect_record(
        9848,
        "2020-05-01T00:00:00Z",
        "2020-05-10T00:00:00Z",
        "2020-05-11T00:00:00Z",
        "2020-05-12T00:00:00Z",
    )
    assert prior_terminal.payload is not None
    prior_values = {
        name: getattr(prior_terminal, name)
        for name in type(prior_terminal).model_fields
    }
    prior_values["terms_association"] = link
    prior_values["payload"] = prior_terminal.payload.model_copy(
        update={
            "action_kind": ActionKind.LIQUIDATION,
            "claim_status": "extinguished",
        }
    )
    prior_terminal = rebind_record_evidence(type(prior_terminal), prior_values)
    later_continuing = effect_record(
        9849,
        claim_status="continuing",
        effective_at="2020-06-01T00:00:00Z",
    )
    assert later_continuing.payload is not None
    later_values = {
        name: getattr(later_continuing, name)
        for name in type(later_continuing).model_fields
    }
    later_values["terms_association"] = link
    later_values["payload"] = later_continuing.payload.model_copy(
        update={"action_kind": ActionKind.LIQUIDATION}
    )
    later_continuing = rebind_record_evidence(type(later_continuing), later_values)
    case = validated_case((terms, prior_terminal, later_continuing))
    policy, query = _query(
        case,
        "outcome",
        horizon="2021-01-01T00:00:00Z",
        cutoff="2021-01-02T00:00:00Z",
        history_start="2020-05-05T00:00:00Z",
    )

    result = resolve_economic_facts(query, case.context, policy)

    assert result.claim_status == "unknown"
    assert "claim_terminal_state_resurrected" in result.reasons


def test_after_horizon_indeterminate_effect_does_not_taint_claim_or_closure() -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    terms = next(
        item for item in records if isinstance(item, CorporateActionTermsVersionV1)
    )
    future = bounded_effect_record(
        9850,
        "2020-08-01T00:00:00Z",
        "2020-08-10T00:00:00Z",
        "2020-08-01T00:00:00Z",
        "2020-08-05T00:00:00Z",
    )
    assert future.payload is not None
    values = {name: getattr(future, name) for name in type(future).model_fields}
    values["terms_association"] = EconomicAssociationV1(
        kind="identified", target=terms.source_key
    )
    values["payload"] = future.payload.model_copy(
        update={
            "action_kind": ActionKind.LIQUIDATION,
            "claim_status": "continuing",
        }
    )
    future = rebind_record_evidence(type(future), values)
    case = validated_case(
        (*records, future),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-05T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-05T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)
    original = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert result.claim_status == "extinguished"
    assert original.status == "closed"
    assert any(
        item.source_record_hash == content_hash(future)
        and item.effective_status == "indeterminate"
        for item in result.effect_projections
    )


def test_causally_unavailable_opposing_effect_does_not_taint_claim_or_closure() -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    terms = next(
        item for item in records if isinstance(item, CorporateActionTermsVersionV1)
    )
    future_known = bounded_effect_record(
        9860,
        "2020-06-30T00:00:00Z",
        "2020-07-01T00:00:00Z",
        "2020-08-03T00:00:00Z",
        "2020-08-04T00:00:00Z",
    )
    assert future_known.payload is not None
    values = {
        name: getattr(future_known, name) for name in type(future_known).model_fields
    }
    values["terms_association"] = EconomicAssociationV1(
        kind="identified", target=terms.source_key
    )
    values["payload"] = future_known.payload.model_copy(
        update={
            "action_kind": ActionKind.LIQUIDATION,
            "claim_status": "continuing",
        }
    )
    future_known = rebind_record_evidence(type(future_known), values)
    case = validated_case(
        (*records, future_known),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-04T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)
    original = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert result.claim_status == "extinguished"
    assert original.status == "closed"
    assert all(
        item.source_record_hash != content_hash(future_known)
        for item in result.effect_projections
    )


def test_indeterminate_settlement_for_distinct_action_does_not_taint_closure() -> None:
    base = closed_liquidation_case()
    records = _economic_records(base)
    other_terms = terms_record(9870, action_kind=ActionKind.LIQUIDATION)
    later = _indeterminate_later_settlement(9871, terms=other_terms)
    case = validated_case(
        (*records, other_terms, later),
        through="2020-07-15T00:00:00Z",
        coverage_snapshot_at="2020-08-02T00:00:00Z",
    )
    query = case.outcome_query("2020-07-15T00:00:00Z", "2020-08-02T00:00:00Z")

    result = resolve_economic_facts(query, case.context, case.source_policy)
    original = next(
        item
        for item in result.residual_resolutions
        if item.action_scope.native_record_id == "report-600"
    )

    assert original.status == "closed"
    assert content_hash(later) in result.uncomposed_settlement_hashes
