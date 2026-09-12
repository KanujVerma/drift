"""Scenario-owned finite-history acceptance for M1d normalization."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest
from m1d_fixture_generator import JoinedScenario
from m1d_fixture_generator import joined_scenario as _joined_scenario
from m1d_fixture_support import assert_roundtrip_replays, field, materialize_result

from drift.domain.normalization import (
    ExactRatioV1,
    NormalizationResultV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)


def joined_scenario(**kwargs: Any) -> JoinedScenario:
    kwargs.setdefault("decision_time", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("knowledge_cutoff", datetime(2026, 12, 2, tzinfo=UTC))
    kwargs.setdefault("effective_cutoff", datetime(2026, 12, 1, tzinfo=UTC))
    return _joined_scenario(**kwargs)


def _instant(day: int) -> datetime:
    return datetime(2026, 11, day, tzinfo=UTC)


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


def test_o01_joined_source_values_materialize_without_action_inputs() -> None:
    scenario = joined_scenario(outer_kind="decision", mode="source_basis")
    result = assert_materialized_join(scenario)

    assert scenario.context.economic_context is not None
    assert result.view is not None
    assert result.view.basis_mode == "source_basis"
    assert result.view.anchor_session is None
    assert field(result, "close").source_value == Decimal("100.000")
    assert field(result, "close").exact_factor == ExactRatioV1(
        numerator="1", denominator="1"
    )
    assert all(item.exact_transformed_value is None for item in result.view.fields)
    assert all(item.quantized_value is None for item in result.view.fields)
    assert result.selected_action_hashes == ()
    assert result.action_mapping_hashes == ()


def test_t02_joined_finite_correction_selects_original_then_revision() -> None:
    retained = joined_scenario(
        outer_kind="decision", mode="source_basis", source_mutation="correction"
    )
    before_scenario = retained.with_query(
        decision_time=_instant(28),
        knowledge_cutoff=_instant(28),
        effective_cutoff=_instant(28),
    )
    after_scenario = retained.with_query(
        decision_time=_instant(30),
        knowledge_cutoff=_instant(30),
        effective_cutoff=_instant(30),
    )

    before = assert_materialized_join(before_scenario)
    after = assert_materialized_join(after_scenario)

    assert before.context_hash == after.context_hash
    assert before.query.observation.security_id == after.query.observation.security_id
    assert field(before, "close").source_value == Decimal("100.000")
    assert field(after, "close").source_value == Decimal("99.500")
    assert before.query_hash != after.query_hash
    assert before.derivation_hash != after.derivation_hash
    assert before.reference != after.reference
    assert before.view is not None and after.view is not None
    assert before.view.usability_hash != after.view.usability_hash
    assert_roundtrip_replays(before, retained.context)


def test_s03_joined_future_emergency_changes_only_later_binding() -> None:
    retained = joined_scenario(
        outer_kind="decision",
        mode="source_basis",
        emergency_date=date(2026, 11, 27),
    )
    before_scenario = retained.with_query(
        decision_time=datetime(2026, 11, 27, 20, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 11, 27, 20, tzinfo=UTC),
        effective_cutoff=datetime(2026, 11, 27, 20, tzinfo=UTC),
    )
    after_scenario = retained.with_query(
        decision_time=_instant(30),
        knowledge_cutoff=_instant(30),
        effective_cutoff=_instant(30),
    )
    before = assert_materialized_join(before_scenario)
    assert "realized_session_did_not_open" not in before.reasons
    after = assert_nonmaterialized_join(
        after_scenario,
        classification="unusable",
        reason="realized_session_did_not_open",
    )
    assert before.context_hash == after.context_hash
    assert_roundtrip_replays(before, retained.context)


def test_s07_joined_schedule_correction_preserves_old_replay() -> None:
    retained = joined_scenario(
        outer_kind="decision",
        mode="source_basis",
        corrected_schedule_state="unknown",
    )
    before_scenario = retained.with_query(
        decision_time=_instant(28),
        knowledge_cutoff=_instant(28),
        effective_cutoff=_instant(28),
    )
    after_scenario = retained.with_query(
        decision_time=datetime(2026, 12, 2, tzinfo=UTC),
        knowledge_cutoff=datetime(2026, 12, 2, tzinfo=UTC),
        effective_cutoff=datetime(2026, 12, 1, tzinfo=UTC),
    )
    before = assert_materialized_join(before_scenario)
    after = assert_nonmaterialized_join(
        after_scenario,
        classification="indeterminate",
        reason="scheduled_day_unknown",
    )
    assert before.context_hash == after.context_hash
    assert_roundtrip_replays(before, retained.context)


@pytest.mark.parametrize(
    "case", ("split_adjusted", "dividend_adjusted", "unknown_basis")
)
def test_o07_joined_adjusted_or_unknown_source_basis_is_refused(
    case: Literal["split_adjusted", "dividend_adjusted", "unknown_basis"],
) -> None:
    retained = joined_scenario(
        outer_kind="outcome", mode="source_basis", source_mutation=case
    )
    source = assert_nonmaterialized_join(
        retained,
        classification="unusable",
        reason="source_basis_incompatible",
    )
    split_scenario = retained.with_query(
        mode="split_normalized", anchor_date=date(2026, 11, 30)
    )
    split = assert_nonmaterialized_join(
        split_scenario,
        classification="unusable",
        reason="source_basis_incompatible",
    )
    assert source.query.observation.security_id == split.query.observation.security_id


def test_o09_joined_mixed_adjustment_basis_is_retained_and_refused() -> None:
    scenario = joined_scenario(
        mode="source_basis", source_mutation="mixed_adjustment_basis"
    )
    result = assert_nonmaterialized_join(
        scenario,
        classification="unusable",
        reason="source_basis_incompatible",
    )
    assert "source_basis:mixed" in result.reasons


def test_o10_joined_official_close_requires_exact_active_equivalence() -> None:
    admitted = assert_materialized_join(
        joined_scenario(
            mode="source_basis", source_mutation="official_close_equivalent"
        )
    )
    assert field(admitted, "close").source_value == Decimal("100.000")
    refused = assert_nonmaterialized_join(
        joined_scenario(mode="source_basis", source_mutation="official_close_unproven"),
        classification="unusable",
        reason="profile_compatibility:incompatible",
    )
    assert "source_selector_or_population_incompatible" in refused.reasons


def test_o11_joined_unrelated_population_containment_is_refused() -> None:
    result = assert_nonmaterialized_join(
        joined_scenario(mode="source_basis", source_mutation="mixed_population"),
        classification="unusable",
        reason="profile_compatibility:incompatible",
    )
    assert "source_selector_or_population_incompatible" in result.reasons
