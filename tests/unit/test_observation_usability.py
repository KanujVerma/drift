"""Behavioral tests for orthogonal observation missingness and usability."""

from dataclasses import replace
from decimal import Decimal
from typing import Literal

import pytest
from observation_test_support import ObservationHarness
from pydantic import ValidationError

from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.observation_usability import (
    ListingSessionEligibilityResultV1,
    ObservationAssessmentV1,
)
from drift.errors import ArtifactIntegrityError
from drift.markets.observation_usability import (
    listing_session_eligibility_algorithm_hash,
    resolve_listing_session_eligibility,
)
from drift.markets.observation_validation import m1d_context_hash


def completed_query(h: ObservationHarness) -> ObservationOutcomeQueryV1:
    return h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")


def test_valid_source_bar_is_usable_without_action_inputs() -> None:
    h = ObservationHarness(assessment_ready=True)

    result = h.assess(completed_query(h))

    assert result.kind == "assessment"
    assert result.usability == "usable"
    assert result.provider_gap == "not_proven"
    assert result.record_presence == "present"
    assert result.required_fields == "complete"
    assert result.numeric_view is not None
    assert result.numeric_view.close == Decimal("100.000")


def test_daily_profile_rejects_shortened_claimed_aggregation_interval() -> None:
    h = ObservationHarness(
        assessment_ready=True,
        claimed_open_utc=(15, 0),
        claimed_close_utc=(20, 0),
    )

    result = h.assess(completed_query(h))

    assert result.kind == "assessment"
    assert result.usability == "unusable"
    assert result.numeric_view is None
    assert "claimed_interval_not_exact_realized_session" in result.reasons


@pytest.mark.parametrize(
    ("coverage", "policy"),
    (("unknown", "matching"), ("complete", "missing")),
)
def test_realized_venue_interruption_requires_complete_exact_aggregation_authority(
    coverage: Literal["complete", "partial", "unknown"], policy: str
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h._configure_aggregation_policy(policy)
    h._rebuild()
    h.attach_sessions(with_interruption=True, interruption_coverage=coverage)
    h.attach_m1b()

    result = h.assess(completed_query(h))

    assert result.kind == "assessment"
    assert result.usability == "indeterminate"
    assert result.numeric_view is None
    assert "realized_interruption_aggregation_unknown" in result.reasons


@pytest.mark.parametrize(
    ("coverage", "policy", "classification"),
    (
        ("complete", "matching", "eligible"),
        ("unknown", "matching", "indeterminate"),
        ("complete", "missing", "indeterminate"),
    ),
)
def test_realized_interruption_eligibility_binds_current_semantics_and_replays(
    coverage: Literal["complete", "partial", "unknown"],
    policy: str,
    classification: Literal["eligible", "indeterminate"],
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h._configure_aggregation_policy(policy)
    h._rebuild()
    h.attach_sessions(with_interruption=True, interruption_coverage=coverage)
    h.attach_m1b()
    query = completed_query(h)

    result = resolve_listing_session_eligibility(query, h.context)
    loaded = ListingSessionEligibilityResultV1.model_validate_json(
        result.model_dump_json()
    )

    assert result.classification == classification
    assert (
        result.semantic_algorithm_hash == listing_session_eligibility_algorithm_hash()
    )
    assert loaded == result
    assert resolve_listing_session_eligibility(query, h.context) == loaded


def test_positive_price_bar_conflicts_with_explicit_no_any_trade_claim() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case("contradictory_no_any_trade")

    result = h.assess(completed_query(h))

    assert result.kind == "assessment"
    assert result.qualifying_price_activity == "reported"
    assert result.any_reported_activity == "explicit_none"
    assert result.usability == "unusable"
    assert result.numeric_view is None
    assert (
        "activity_claim_conflict:any_trade_explicit_none_with_qualifying_price_trade"
        in result.reasons
    )


def test_same_day_close_is_not_available_at_open() -> None:
    h = ObservationHarness(assessment_ready=True, available_at="2026-01-05T14:00:00Z")
    query = h.decision(
        "2026-01-05T14:30:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05T14:30:00Z",
        "2026-01-05",
    )

    result = h.assess(query)

    assert result.usability != "usable"
    assert result.cutoff_availability != "eligible"
    assert result.provider_gap == "not_proven"
    assert result.numeric_view is None


def test_exact_absent_row_proves_provider_gap_without_zero_price() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_absent_query_row()

    result = h.assess(completed_query(h))

    assert result.record_presence == "absent"
    assert result.coverage == "expected_complete"
    assert result.provider_gap == "proven"
    assert result.qualifying_price_activity == "unknown"
    assert result.any_reported_activity == "unknown"
    assert result.numeric_view is None


@pytest.mark.parametrize("coverage", ("partial", "current_only", "unknown"))
def test_absent_row_without_complete_historical_coverage_is_not_a_provider_gap(
    coverage: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_absent_query_row(coverage=coverage)

    result = h.assess(completed_query(h))

    assert result.record_presence == "absent"
    assert result.provider_gap == "not_proven"
    assert result.numeric_view is None


def test_explicit_no_price_trade_keeps_any_activity_independent() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case("explicit_no_price_trade")

    result = h.assess(completed_query(h))

    assert result.qualifying_price_activity == "explicit_none"
    assert result.any_reported_activity == "reported"
    assert result.record_presence == "present"
    assert result.provider_gap == "not_proven"
    assert result.numeric_view is None


@pytest.mark.parametrize(
    "case", ("conditional_absent", "zero_volume", "volume_sentinel", "null_close")
)
def test_omission_zero_and_null_do_not_infer_no_trade(case: str) -> None:
    h = ObservationHarness(assessment_ready=True)
    if case == "conditional_absent":
        h.use_absent_query_row(row_emission="conditional_on_qualifying_activity")
    else:
        h.use_field_case(case)

    result = h.assess(completed_query(h))

    assert result.qualifying_price_activity == "unknown"
    assert result.provider_gap == "not_proven"
    assert result.numeric_view is None


@pytest.mark.parametrize("failure", ("corrupt", "unavailable"))
def test_typed_read_failures_do_not_become_absence_or_lifecycle(
    failure: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_read_failure(failure)

    result = h.assess(completed_query(h))

    assert result.kind == "read_failure"
    assert result.integrity == failure
    assert result.record_presence == "unknown"
    assert result.lifecycle == "indeterminate"
    assert result.provider_gap == "not_proven"
    assert result.numeric_view is None


def test_malformed_or_forged_assessment_is_not_swallowed_as_missingness() -> None:
    h = ObservationHarness(assessment_ready=True)
    query = completed_query(h)
    valid = h.assess(query)
    assert isinstance(valid, ObservationAssessmentV1)
    forged_payload = valid.model_dump(mode="python")
    forged_payload["query_hash"] = "f" * 64

    with pytest.raises(ValidationError, match="query hash"):
        ObservationAssessmentV1.model_validate(forged_payload)
    forged = ObservationAssessmentV1.model_construct(
        **{
            **{
                name: getattr(valid, name)
                for name in ObservationAssessmentV1.model_fields
            },
            "usability": "indeterminate",
            "numeric_view": None,
        }
    )
    with pytest.raises(ValueError, match="replay mismatch"):
        h.verify(forged)


@pytest.mark.parametrize(
    ("lifecycle", "expected_axis"),
    (
        ("not_yet_listed", "not_yet_listed"),
        ("fully_suspended", "suspended"),
        ("terminated_before", "terminated"),
    ),
)
def test_known_ineligible_lifecycle_intervals_are_unusable(
    lifecycle: str, expected_axis: str
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case(lifecycle)

    result = h.assess(completed_query(h))

    assert result.lifecycle == expected_axis
    assert result.usability == "unusable"
    assert result.numeric_view is None


def test_delisted_listing_keeps_pretermination_bar_usable() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("terminated_after")

    result = h.assess(completed_query(h))

    assert result.lifecycle == "active"
    assert result.usability == "usable"


def test_partial_suspension_requires_complete_explicit_aggregation() -> None:
    complete = ObservationHarness(assessment_ready=True)
    complete.use_lifecycle_case("partial_suspension", interruption_coverage="complete")
    unknown = ObservationHarness(assessment_ready=True)
    unknown.use_lifecycle_case("partial_suspension", interruption_coverage="unknown")

    complete_result = complete.assess(completed_query(complete))
    unknown_result = unknown.assess(completed_query(unknown))
    assert isinstance(complete_result, ObservationAssessmentV1)
    assert isinstance(unknown_result, ObservationAssessmentV1)

    assert {segment.lifecycle for segment in complete_result.eligibility.segments} == {
        "active",
        "suspended",
    }
    assert complete_result.usability == "usable"
    assert unknown_result.usability == "indeterminate"
    assert unknown_result.numeric_view is None


def test_disjoint_uncertain_lifecycle_evidence_does_not_poison_interval() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("disjoint_bounded_unknown")

    result = h.assess(completed_query(h))

    assert result.lifecycle == "active"
    assert result.usability == "usable"


def test_multiple_unknown_axes_are_preserved_without_a_dominant_reason() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_unproven_observation_coverage(mode="partial")
    h.use_lifecycle_case("overlapping_bounded_unknown")
    h.attach_sessions(schedule_state="unknown", realized_outcome="unknown")

    result = h.assess(completed_query(h))

    assert result.scheduled_day == "unknown"
    assert result.realized_outcome == "unknown"
    assert result.coverage == "partial"
    assert result.lifecycle == "indeterminate"
    assert result.usability == "indeterminate"
    assert len(result.reasons) >= 4


def test_present_complete_row_does_not_require_global_coverage() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_unproven_observation_coverage(mode="partial")

    result = h.assess(completed_query(h))

    assert result.record_presence == "present"
    assert result.coverage == "partial"
    assert result.usability == "usable"
    assert result.numeric_view is not None


@pytest.mark.parametrize(
    "case",
    (
        "mixed_population",
        "official_close_unproven",
        "unknown_method_meaning",
        "unknown_ordering",
        "zero_volume",
        "volume_sentinel",
        "partial_fields",
        "negative_price",
        "range_failure",
        "split_adjusted",
        "dividend_adjusted",
        "unknown_basis",
    ),
)
def test_nonconforming_source_claims_are_retained_without_numeric_view(
    case: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case(case)

    result = h.assess(completed_query(h))

    assert result.record_presence == "present"
    assert result.usability != "usable"
    assert result.numeric_view is None


def test_proven_official_close_equivalence_can_satisfy_profile() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case("official_close_equivalent")

    result = h.assess(completed_query(h))

    assert result.profile_compatibility == "compatible"
    assert result.usability == "usable"
    assert result.numeric_view is not None


def test_complete_values_with_unknown_price_activity_are_indeterminate() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case("unknown_activity")

    result = h.assess(completed_query(h))

    assert result.qualifying_price_activity == "unknown"
    assert result.usability == "indeterminate"
    assert result.numeric_view is None


def test_outcome_vintage_controls_inner_as_known_lifecycle() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("late_known_termination")
    early = h.outcome("2026-01-09T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")
    late = h.outcome("2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05")

    early_result = h.assess(early)
    late_result = h.assess(late)
    assert isinstance(early_result, ObservationAssessmentV1)
    assert isinstance(late_result, ObservationAssessmentV1)

    assert (
        early_result.eligibility.inner_knowledge_cutoff == early.evidence_vintage_cutoff
    )
    assert early_result.usability == "usable"
    assert late_result.lifecycle == "terminated"
    assert late_result.usability == "unusable"


def test_research_eligibility_never_claims_tradability() -> None:
    h = ObservationHarness(assessment_ready=True)
    result = h.assess(completed_query(h))
    assert isinstance(result, ObservationAssessmentV1)

    dumped = result.model_dump(mode="python")
    assert "tradable" not in dumped
    assert "no_trade" not in dumped
    assert result.eligibility.classification == "eligible"


def test_only_typed_read_errors_are_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    from drift.markets import observation_usability as module

    h = ObservationHarness(assessment_ready=True)
    query = completed_query(h)

    def forged_failure(*_args: object) -> None:
        raise ValueError("forged proof")

    monkeypatch.setattr(module, "_verify_requested_observation_bytes", forged_failure)
    with pytest.raises(ValueError, match="forged proof"):
        h.assess(query)

    def integrity_failure(*_args: object) -> None:
        raise ArtifactIntegrityError("bad bytes")

    monkeypatch.setattr(
        module, "_verify_requested_observation_bytes", integrity_failure
    )
    result = h.assess(query)
    assert result.kind == "read_failure"
    assert result.integrity == "corrupt"


def test_assessment_replay_binds_complete_result_and_context() -> None:
    h = ObservationHarness(assessment_ready=True)
    result = h.assess(completed_query(h))

    h.verify(result)
    changed = replace(h.context, supporting_artifacts={})
    assert m1d_context_hash(changed) != m1d_context_hash(h.context)
    with pytest.raises(ValueError, match="context hash"):
        h.verify(result, context=changed)


@pytest.mark.parametrize("change", ("membership_removal", "classification_change"))
def test_non_lifecycle_structural_boundaries_split_the_source_interval(
    change: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_structural_change(change)

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert len(result.eligibility.segments) >= 2
    assert {item.structural_classification for item in result.eligibility.segments} == {
        "eligible",
        "ineligible",
    }
    assert result.usability == "unusable"


def test_selected_unknown_lifecycle_boundary_makes_whole_interval_indeterminate() -> (
    None
):
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("unknown_boundary")

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert result.lifecycle == "indeterminate"
    assert result.eligibility.classification == "indeterminate"
    assert all(
        segment.lifecycle == "indeterminate" for segment in result.eligibility.segments
    )


def test_valid_venue_transfer_replays_complete_m1b_dependency_closure() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("venue_transfer")

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert result.usability == "unusable"
    assert {segment.lifecycle for segment in result.eligibility.segments} == {
        "active",
        "terminated",
    }
    assert result.eligibility.lifecycle_resolution_hashes


@pytest.mark.parametrize("policy", ("missing", "unknown", "mismatched"))
def test_partial_suspension_without_exact_aggregation_policy_is_indeterminate(
    policy: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case(
        "partial_suspension",
        interruption_coverage="complete",
        aggregation_policy=policy,
    )

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert result.usability == "indeterminate"
    assert result.numeric_view is None


@pytest.mark.parametrize("snapshot_case", ("unknown", "bounded", "future", "backdated"))
def test_provider_gap_requires_causal_completed_coverage_snapshot(
    snapshot_case: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_absent_query_row(snapshot_case=snapshot_case)

    result = h.assess(completed_query(h))

    assert result.provider_gap == "not_proven"


def test_explicit_m1b_channel_mapping_is_required_for_distinct_outer_channel() -> None:
    h = ObservationHarness(assessment_ready=True)
    query = completed_query(h)
    h.remove_m1b_channel_mapping()
    mismatched = query.model_copy(
        update={"input_context_hash": m1d_context_hash(h.context)}
    )

    with pytest.raises(ValueError, match="channel"):
        h.assess(mismatched)


def test_explicit_m1b_channel_mapping_authorizes_declared_distinct_channel() -> None:
    h = ObservationHarness(assessment_ready=True)

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert h.context.m1b_requested_channel is not None
    assert result.eligibility.classification == "eligible"


def test_future_correction_does_not_poison_selected_old_row_cutoff_axis() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.replace_source_revision(close="99.500", available_at="2026-01-08T00:00:00Z")
    early = h.outcome("2026-01-09T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")
    late = h.outcome("2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05")

    early_result = h.assess(early)
    late_result = h.assess(late)

    assert isinstance(early_result, ObservationAssessmentV1)
    assert isinstance(late_result, ObservationAssessmentV1)
    assert early_result.cutoff_availability == "eligible"
    assert early_result.usability == "usable"
    assert early_result.numeric_view is not None
    assert early_result.numeric_view.close == Decimal("100.000")
    assert late_result.numeric_view is not None
    assert late_result.numeric_view.close == Decimal("99.500")


def test_forged_context_precedes_corrupt_artifact_read_failure() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_read_failure("corrupt")
    query = completed_query(h)
    forged = query.model_copy(update={"input_context_hash": "f" * 64})

    with pytest.raises(ValueError, match="context hash"):
        h.assess(forged)
    genuine = h.assess(query)
    assert genuine.kind == "read_failure"
    assert genuine.integrity == "corrupt"


def test_forged_policy_precedes_corrupt_artifact_read_failure() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_read_failure("corrupt")
    query = completed_query(h).model_copy(
        update={"source_selection_policy_hash": "f" * 64}
    )

    with pytest.raises(ValueError, match="policy"):
        h.assess(query)


def test_scheduled_research_eligibility_does_not_require_realized_outcome() -> None:
    from drift.markets.observation_usability import (
        resolve_listing_session_eligibility,
    )

    h = ObservationHarness(assessment_ready=True)
    h.attach_sessions(realized_outcome="missing")
    query = completed_query(h)

    eligibility = resolve_listing_session_eligibility(query, h.context)
    assessment = h.assess(query)

    assert eligibility.classification == "eligible"
    assert eligibility.generated_schedule_hash is not None
    assert assessment.usability == "indeterminate"
    assert assessment.numeric_view is None


def test_unknown_schedule_remains_research_indeterminate_without_realization() -> None:
    from drift.markets.observation_usability import (
        resolve_listing_session_eligibility,
    )

    h = ObservationHarness(assessment_ready=True)
    h.attach_sessions(schedule_state="unknown", realized_outcome="missing")
    query = completed_query(h)

    result = resolve_listing_session_eligibility(query, h.context)

    assert result.classification == "indeterminate"
    assert result.generated_schedule_hash is not None


@pytest.mark.parametrize("case", ("split_adjusted", "negative_price"))
def test_intrinsic_profile_incompatibility_survives_unknown_session_binding(
    case: str,
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_field_case(case)
    h.attach_sessions(realized_outcome="missing")

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    assert result.profile_compatibility == "incompatible"
    assert result.usability == "unusable"
    assert result.numeric_view is None


def test_bounded_uncertainty_ending_at_segment_start_is_half_open_disjoint() -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_lifecycle_case("bounded_endpoint_touch")

    result = h.assess(completed_query(h))

    assert isinstance(result, ObservationAssessmentV1)
    later = next(
        segment
        for segment in result.eligibility.segments
        if segment.opened_at.isoformat() == "2026-01-05T17:00:00+00:00"
    )
    assert later.lifecycle == "active"
    assert later.structural_classification == "eligible"


@pytest.mark.parametrize("corrupt", (False, True))
@pytest.mark.parametrize(
    ("policy_case", "message"),
    (
        ("false_implementation", "implementation identity"),
        ("missing_producer_source", "lineage artifact unavailable"),
        ("missing_producer_package", "lineage artifact unavailable"),
        ("missing_lockfile", "lineage artifact unavailable"),
    ),
)
def test_generation_policy_forgery_precedes_observation_read(
    policy_case: str, message: str, corrupt: bool
) -> None:
    h = ObservationHarness(assessment_ready=True)
    h.use_generation_policy_case(policy_case)
    if corrupt:
        h.use_read_failure("corrupt")

    with pytest.raises(ValueError, match=message):
        h.assess(completed_query(h))
