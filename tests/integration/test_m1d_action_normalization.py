"""Scenario-owned M1c action mapping and M1d normalization acceptance."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from m1d_fixture_generator import JoinedScenario
from m1d_fixture_generator import joined_scenario as _joined_scenario
from m1d_fixture_support import assert_roundtrip_replays, field, materialize_result

from drift.domain.action_sessions import EconomicDateRole
from drift.domain.economic_common import ActionKind
from drift.domain.economic_coverage import EconomicCoverageVersionV1
from drift.domain.economic_events import CorporateActionTermsVersionV1
from drift.domain.normalization import (
    ExactRatioV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.domain.observation_query import ObservationDecisionQueryV1
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)


def joined_scenario(**kwargs: Any) -> JoinedScenario:
    kwargs.setdefault("decision_time", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("knowledge_cutoff", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("effective_cutoff", datetime(2026, 12, 1, tzinfo=UTC))
    return _joined_scenario(**kwargs)


def _materialize_with_role(
    reference: ObservationDecisionReferenceV1 | ObservationOutcomeReferenceV1,
    scenario: JoinedScenario,
) -> object:
    if isinstance(reference, ObservationDecisionReferenceV1):
        return materialize_observation_decision(
            reference, scenario.query, scenario.context
        )
    return materialize_observation_outcome(reference, scenario.query, scenario.context)


def _forged_reference(
    result: NormalizationResultV1,
) -> ObservationDecisionReferenceV1 | ObservationOutcomeReferenceV1:
    model = (
        ObservationDecisionReferenceV1
        if result.query.observation.kind == "decision"
        else ObservationOutcomeReferenceV1
    )
    return model(
        query_hash=result.query_hash,
        view_hash="0" * 64,
        derivation_hash="1" * 64,
        context_hash=result.context_hash,
    )


def assert_materialized_join(scenario: JoinedScenario) -> NormalizationResultV1:
    result = scenario.normalize()
    assert_roundtrip_replays(result, scenario.context)
    assert result.classification == "materialized"
    assert result.reference is not None
    assert materialize_result(result, scenario.context) == result.view
    return result


def assert_nonmaterialized_join(
    scenario: JoinedScenario,
    *,
    classification: str,
    reason: str,
) -> NormalizationResultV1:
    result = scenario.normalize()
    assert_roundtrip_replays(result, scenario.context)
    assert result.classification == classification
    assert reason in result.reasons
    assert result.view is None
    assert result.derivation is None
    assert result.reference is None
    with pytest.raises(ValueError, match="no longer materializes"):
        _materialize_with_role(_forged_reference(result), scenario)
    return result


def test_a01_joined_explicit_first_basis_date_maps_on_proven_open() -> None:
    scenario = joined_scenario(
        action_basis="2026-11-27", mapping_mode="explicit_first_basis_date"
    )
    result = assert_materialized_join(scenario)
    assert result.view is not None
    assert result.view.anchor_session is not None
    assert field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )


def test_a02_joined_after_early_close_uses_next_proven_open() -> None:
    scenario = joined_scenario(action_basis="2026-11-27T18:05:00Z")
    result = assert_materialized_join(scenario)
    assert field(result, "close").quantized_value == Decimal("50.00")
    assert result.selected_action_hashes
    assert len(result.action_mapping_hashes) == 1


def test_a03_joined_before_open_maps_but_undesignated_endpoint_blocks() -> None:
    before = assert_materialized_join(
        joined_scenario(action_basis="2026-11-27T14:00:00Z")
    )
    assert field(before, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert_nonmaterialized_join(
        joined_scenario(action_basis="2026-11-27T14:30:00Z"),
        classification="indeterminate",
        reason="split_mapping_indeterminate",
    )


@pytest.mark.parametrize("role", ("announcement", "record", "payable", "legal_effect"))
def test_a04_joined_legal_dates_never_gain_trading_basis_meaning(
    role: EconomicDateRole,
) -> None:
    assert_nonmaterialized_join(
        joined_scenario(
            action_basis="2026-11-27",
            mapping_mode="explicit_first_basis_date",
            date_role=role,
        ),
        classification="indeterminate",
        reason="split_mapping_indeterminate",
    )


def test_a05_joined_emergency_did_not_open_blocks_mapping() -> None:
    assert_nonmaterialized_join(
        joined_scenario(
            action_basis="2026-11-30",
            mapping_mode="explicit_first_basis_date",
            emergency_date=date(2026, 11, 30),
        ),
        classification="indeterminate",
        reason="anchor_basis_unproved",
    )


def test_a06_joined_subject_mismatch_blocks_action_mapping() -> None:
    assert_nonmaterialized_join(
        joined_scenario(
            action_basis="2026-11-27",
            mapping_mode="explicit_first_basis_date",
            method_mic="XNAS",
        ),
        classification="indeterminate",
        reason="split_mapping_indeterminate",
    )


def test_a07_joined_correction_changes_only_later_mapping() -> None:
    old_scenario = joined_scenario(
        outer_kind="decision",
        action_basis="2026-11-27T14:00:00Z",
        source_session_date=date(2026, 11, 25),
    )
    corrected_scenario = joined_scenario(
        outer_kind="decision",
        action_basis="2026-11-27T14:00:00Z",
        correction_basis="2026-11-27T18:05:00Z",
        source_session_date=date(2026, 11, 25),
    )
    old = assert_materialized_join(old_scenario)
    corrected = assert_materialized_join(corrected_scenario)

    assert field(old, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert field(corrected, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert (
        field(old, "close").quantized_value == field(corrected, "close").quantized_value
    )
    assert old.action_mapping_hashes != corrected.action_mapping_hashes
    assert old.derivation_hash != corrected.derivation_hash
    assert old.reference != corrected.reference
    assert_roundtrip_replays(old, old_scenario.context)
    assert_roundtrip_replays(corrected, corrected_scenario.context)


def test_a08_joined_duplicate_occurrence_applies_one_factor() -> None:
    result = assert_materialized_join(joined_scenario(duplicate="equal"))
    assert len(result.selected_action_hashes) == 2
    assert len(result.action_mapping_hashes) == 1
    assert field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )


def test_a08_joined_crossing_window_conflict_blocks_factor() -> None:
    assert_nonmaterialized_join(
        joined_scenario(
            duplicate="conflict_outside_window",
            decision_time=datetime(2026, 12, 4, tzinfo=UTC),
            knowledge_cutoff=datetime(2026, 12, 4, tzinfo=UTC),
            effective_cutoff=datetime(2026, 12, 3, tzinfo=UTC),
        ),
        classification="indeterminate",
        reason="same_occurrence_economic_disagreement",
    )


def test_n01_joined_same_context_before_and_after_split() -> None:
    retained = joined_scenario(outer_kind="decision")
    before_scenario = retained.with_query(
        mode="source_basis",
        decision_time=datetime(2026, 11, 28, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
        effective_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
    )
    after_scenario = retained.with_query(
        mode="split_normalized",
        anchor_date=date(2026, 11, 30),
        decision_time=datetime(2026, 12, 2, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 12, 2, tzinfo=UTC),
        effective_cutoff=datetime(2026, 12, 1, tzinfo=UTC),
    )
    before = assert_materialized_join(before_scenario)
    after = assert_materialized_join(after_scenario)

    assert isinstance(before.query.observation, ObservationDecisionQueryV1)
    assert before.query.observation.decision_time == datetime(2026, 11, 28, tzinfo=UTC)
    assert before.query.observation.knowledge_cutoff == datetime(
        2026, 11, 28, tzinfo=UTC
    )
    assert before.query.observation.effective_cutoff == datetime(
        2026, 11, 28, tzinfo=UTC
    )
    assert isinstance(after.query.observation, ObservationDecisionQueryV1)
    assert after.query.observation.decision_time == datetime(2026, 12, 2, tzinfo=UTC)
    assert after.query.observation.knowledge_cutoff == datetime(2026, 12, 2, tzinfo=UTC)
    assert after.query.observation.effective_cutoff == datetime(2026, 12, 1, tzinfo=UTC)
    assert before_scenario.context is after_scenario.context
    assert before.query.observation.security_id == after.query.observation.security_id
    assert field(before, "close").source_value == Decimal("100.000")
    assert field(before, "close").quantized_value is None
    assert field(before, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert before.selected_action_hashes == ()
    assert before.action_mapping_hashes == ()
    assert field(after, "close").quantized_value == Decimal("50.00")
    assert field(after, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert field(after, "volume").exact_factor == ExactRatioV1(
        numerator="2", denominator="1"
    )
    assert len(after.action_mapping_hashes) == 1


def test_n02_joined_retained_future_action_does_not_leak_then_applies_later() -> None:
    early_scenario = joined_scenario(
        outer_kind="decision",
        action_basis="2026-11-30T14:00:00Z",
        omit_effect=True,
        anchor_date=date(2026, 11, 27),
        decision_time=datetime(2026, 11, 29, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 11, 29, tzinfo=UTC),
        effective_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
    )
    later_scenario = joined_scenario(
        outer_kind="decision",
        action_basis="2026-11-30T14:00:00Z",
        anchor_date=date(2026, 11, 30),
        decision_time=datetime(2026, 12, 2, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 12, 2, tzinfo=UTC),
        effective_cutoff=datetime(2026, 12, 1, tzinfo=UTC),
    )
    empty_control_scenario = joined_scenario(
        outer_kind="decision",
        action_basis="2026-11-30T14:00:00Z",
        omit_effect=True,
        omit_terms=True,
        anchor_date=date(2026, 11, 27),
        decision_time=datetime(2026, 11, 29, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 11, 29, tzinfo=UTC),
        effective_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
    )
    early = assert_materialized_join(early_scenario)
    later = assert_materialized_join(later_scenario)
    empty_control = assert_materialized_join(empty_control_scenario)

    assert early_scenario.context is not later_scenario.context
    assert early_scenario.context is not empty_control_scenario.context
    assert early.query.observation.security_id == later.query.observation.security_id
    assert early.query.observation.model_dump(
        exclude={"input_context_hash"}
    ) == empty_control.query.observation.model_dump(exclude={"input_context_hash"})
    assert early.query.anchor_session == empty_control.query.anchor_session
    assert early_scenario.context.observation_datasets == (
        empty_control_scenario.context.observation_datasets
    )
    assert early_scenario.context.session_datasets == (
        empty_control_scenario.context.session_datasets
    )
    assert early_scenario.context.structural_context == (
        empty_control_scenario.context.structural_context
    )
    assert early_scenario.context.economic_context is not None
    assert later_scenario.context.economic_context is not None
    assert empty_control_scenario.context.economic_context is not None
    early_effect_hashes = {
        hash_
        for dataset in early_scenario.context.economic_context.datasets
        if dataset.manifest.dataset_role.name == "economic_effect"
        for hash_ in dataset.decision.validated_record_hashes
    }
    early_terms = tuple(
        record
        for dataset in early_scenario.context.economic_context.datasets
        for record in dataset.records
        if isinstance(record, CorporateActionTermsVersionV1)
    )
    assert len(early_terms) == 1
    assert early_terms[0].revision.availability[0].upper_bound == datetime(
        2026, 11, 20, tzinfo=UTC
    )
    assert early_terms[0].scheduled_effect_time.lower_bound == datetime(
        2026, 11, 30, 14, tzinfo=UTC
    )
    control_terms = tuple(
        record
        for dataset in empty_control_scenario.context.economic_context.datasets
        for record in dataset.records
        if isinstance(record, CorporateActionTermsVersionV1)
    )
    control_effect_hashes = {
        hash_
        for dataset in empty_control_scenario.context.economic_context.datasets
        if dataset.manifest.dataset_role.name == "economic_effect"
        for hash_ in dataset.decision.validated_record_hashes
    }
    control_coverage = tuple(
        record
        for dataset in empty_control_scenario.context.economic_context.datasets
        for record in dataset.records
        if isinstance(record, EconomicCoverageVersionV1)
    )
    assert control_terms == ()
    assert control_effect_hashes == set()
    assert len(control_coverage) == 3
    assert all(record.completeness == "complete" for record in control_coverage)
    later_effect_hashes = {
        hash_
        for dataset in later_scenario.context.economic_context.datasets
        if dataset.manifest.dataset_role.name == "economic_effect"
        for hash_ in dataset.decision.validated_record_hashes
    }
    assert early_effect_hashes == set()
    assert later_effect_hashes
    assert early.selected_action_hashes == ()
    assert early.action_mapping_hashes == ()
    assert empty_control.selected_action_hashes == ()
    assert empty_control.action_mapping_hashes == ()
    assert early.reasons == empty_control.reasons
    assert all("future" not in reason for reason in early.reasons)
    assert all(
        marker not in "|".join(early.reasons)
        for marker in (
            "2026-11-30",
            "trading_basis",
            "forward_split",
            "split-occurrence-1",
        )
    )
    early_fields = (
        tuple(
            (
                item.field_name,
                item.source_value,
                item.exact_factor,
                item.exact_transformed_value,
                item.quantized_value,
                item.output_scale,
                item.rounded_to_zero,
                item.meaning,
            )
            for item in early.view.fields
        )
        if early.view is not None
        else ()
    )
    control_fields = (
        tuple(
            (
                item.field_name,
                item.source_value,
                item.exact_factor,
                item.exact_transformed_value,
                item.quantized_value,
                item.output_scale,
                item.rounded_to_zero,
                item.meaning,
            )
            for item in empty_control.view.fields
        )
        if empty_control.view is not None
        else ()
    )
    assert early_fields == control_fields
    assert field(early, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert field(later, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="2"
    )
    assert later_effect_hashes & set(later.selected_action_hashes)


def test_n03_joined_future_anchor_is_denied() -> None:
    scenario = joined_scenario(
        outer_kind="decision",
        decision_time=datetime(2026, 11, 28, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
        effective_cutoff=datetime(2026, 11, 28, tzinfo=UTC),
        anchor_date=date(2026, 11, 30),
    )
    assert_nonmaterialized_join(
        scenario,
        classification="indeterminate",
        reason="anchor_basis_beyond_effective_cutoff",
    )


def test_n04_joined_forward_and_reverse_factors_are_exact_reciprocals() -> None:
    cases = (
        (("2", "1"), ActionKind.FORWARD_SPLIT, ("1", "2"), ("2", "1")),
        (("1", "10"), ActionKind.REVERSE_SPLIT, ("10", "1"), ("1", "10")),
    )
    for ratio, action_kind, price_factor, volume_factor in cases:
        result = assert_materialized_join(
            joined_scenario(ratio=ratio, action_kind=action_kind)
        )
        price = field(result, "close").exact_factor
        volume = field(result, "volume").exact_factor
        assert (price.numerator, price.denominator) == price_factor
        assert (volume.numerator, volume.denominator) == volume_factor
