"""Behavioral tests for exact M1d observation/session binding."""

from datetime import UTC, datetime
from typing import Literal

import pytest
from observation_test_support import ObservationHarness

from drift.domain.observation_query import ObservationQueryV1
from drift.domain.observations import RuleDisposition
from drift.serialization.canonical import content_hash


def bound_case(
    *,
    schedule_state: Literal["regular", "early_close", "closed", "unknown"] = (
        "regular"
    ),
    realized_outcome: Literal[
        "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
    ] = "opened",
    auction_event_inclusion: RuleDisposition = "included",
    used_population_rules: RuleDisposition = "included",
    corrected_schedule: bool = False,
) -> tuple[ObservationHarness, ObservationQueryV1]:
    h = ObservationHarness(
        auction_event_inclusion=auction_event_inclusion,
        used_population_rules=used_population_rules,
    )
    h.attach_sessions(
        schedule_state=schedule_state,
        realized_outcome=realized_outcome,
        corrected_schedule=corrected_schedule,
    )
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")
    return h, query


def test_binds_against_realized_interval_without_rewriting_first_trade() -> None:
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case()
    result = bind_observation_session(query, h.context)

    assert result.classification == "bound"
    assert result.actual_interval is not None
    assert result.actual_interval.opened_at == datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    assert result.actual_interval.closed_at == datetime(2026, 1, 5, 20, 55, tzinfo=UTC)
    assert result.claimed_interval is not None
    assert result.claimed_interval.start.lower_bound == result.actual_interval.opened_at
    assert result.source_label_mapping is not None
    assert result.source_label_mapping.source_local_label == "2026-01-05"
    assert result.selected_schedule_proof_hash is not None
    assert result.selected_realized_proof_hash is not None


def test_did_not_open_conflicts_with_a_present_completed_bar() -> None:
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case(realized_outcome="did_not_open")
    result = bind_observation_session(query, h.context)

    assert result.classification == "conflict"
    assert result.actual_interval is None
    assert result.reasons == ("realized_session_did_not_open",)


def test_future_emergency_is_not_diagnostic_until_its_finite_vintage() -> None:
    from drift.markets.observation_selection import select_observation_records
    from drift.markets.session_binding import bind_observation_session

    h = ObservationHarness()
    h.attach_sessions(
        realized_outcome="did_not_open",
        realized_available_at="2026-01-08T00:00:00Z",
    )
    before_query = h.outcome(
        "2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05"
    )
    after_query = h.outcome(
        "2026-01-09T00:00:00Z", "2026-01-09T00:00:00Z", "2026-01-05"
    )

    before_schedule = select_observation_records(
        before_query, "scheduled_session", h.context
    )
    before = bind_observation_session(before_query, h.context)
    after_schedule = select_observation_records(
        after_query, "scheduled_session", h.context
    )
    after = bind_observation_session(after_query, h.context)

    assert before_schedule.records == after_schedule.records
    assert before.classification == "indeterminate"
    assert "realized_session_did_not_open" not in before.reasons
    assert after.classification == "conflict"
    assert after.reasons == ("realized_session_did_not_open",)


@pytest.mark.parametrize("outcome", ("missing", "unknown", "opened_without_bounds"))
def test_unknown_or_unbounded_realization_never_authorizes_a_completed_bar(
    outcome: Literal[
        "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
    ],
) -> None:
    from drift.markets.observation_selection import select_observation_records
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case(realized_outcome=outcome)
    result = bind_observation_session(query, h.context)

    assert result.classification == "indeterminate"
    assert result.actual_interval is None
    if outcome == "opened_without_bounds":
        selected = select_observation_records(query, "realized_session", h.context)
        assert len(selected.records) == 1


@pytest.mark.parametrize("schedule_state", ("closed", "unknown"))
def test_realized_actual_interval_remains_authoritative_when_schedule_differs(
    schedule_state: Literal["regular", "early_close", "closed", "unknown"],
) -> None:
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case(schedule_state=schedule_state)
    result = bind_observation_session(query, h.context)

    assert result.classification == "bound"
    assert result.selected_schedule_proof_hash is not None
    assert "schedule_realized_difference" in result.reasons


def test_unknown_auction_endpoint_policy_is_not_completed_bar_authority() -> None:
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case(auction_event_inclusion="unknown")
    result = bind_observation_session(query, h.context)

    assert result.classification == "indeterminate"
    assert result.reasons == ("observation_endpoint_policy_unproven",)


def test_endpoint_policy_uses_field_population_not_explicit_decoy() -> None:
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case(used_population_rules="unknown")
    result = bind_observation_session(query, h.context)

    assert result.classification == "indeterminate"
    assert result.reasons == ("observation_endpoint_policy_unproven",)


@pytest.mark.parametrize("coverage_mode", ("absent", "partial"))
def test_present_exact_observation_binds_with_unproven_coverage_diagnostic(
    coverage_mode: Literal["absent", "partial"],
) -> None:
    from drift.markets.session_binding import bind_observation_session

    h = ObservationHarness()
    h.use_unproven_observation_coverage(mode=coverage_mode)
    h.attach_sessions()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    result = bind_observation_session(query, h.context)

    assert result.classification == "bound"
    assert result.actual_interval is not None
    assert "observation_coverage_unproven" in result.reasons


def test_absent_observation_does_not_infer_provider_gap_before_task4() -> None:
    from drift.markets.session_binding import bind_observation_session

    h = ObservationHarness()
    h.use_empty_source_inventory()
    h.attach_sessions()
    query = h.outcome("2026-01-07T00:00:00Z", "2026-01-07T00:00:00Z", "2026-01-05")

    result = bind_observation_session(query, h.context)

    assert result.classification == "indeterminate"
    assert all("provider" not in reason for reason in result.reasons)


def test_schedule_correction_needs_fresh_context_and_preserves_old_replay() -> None:
    from drift.markets.session_binding import (
        bind_observation_session,
        verify_session_binding,
    )

    old_h, old_query = bound_case()
    old_result = bind_observation_session(old_query, old_h.context)
    new_h, new_query = bound_case(corrected_schedule=True)
    new_result = bind_observation_session(new_query, new_h.context)

    assert old_result.classification == new_result.classification == "bound"
    assert old_result.actual_interval == new_result.actual_interval
    assert old_result.selected_schedule_proof_hash != (
        new_result.selected_schedule_proof_hash
    )
    verify_session_binding(old_result, old_h.context)
    with pytest.raises(ValueError, match="context hash mismatch"):
        verify_session_binding(old_result, new_h.context)


def test_binding_replay_rejects_substituted_observation_and_dependencies() -> None:
    from drift.markets.session_binding import (
        bind_observation_session,
        verify_session_binding,
    )

    h, query = bound_case()
    result = bind_observation_session(query, h.context)
    forged_observation = result.model_construct(
        **{
            **{name: getattr(result, name) for name in type(result).model_fields},
            "observation_hash": "f" * 64,
        }
    )
    forged_dependencies = result.model_construct(
        **{
            **{name: getattr(result, name) for name in type(result).model_fields},
            "dependency_hashes": ("e" * 64,),
        }
    )

    with pytest.raises(ValueError, match="replay mismatch"):
        verify_session_binding(forged_observation, h.context)
    with pytest.raises(ValueError, match="replay mismatch"):
        verify_session_binding(forged_dependencies, h.context)


def test_binding_dependency_hashes_include_exact_selected_values() -> None:
    from drift.markets.observation_selection import select_observation_records
    from drift.markets.session_binding import bind_observation_session

    h, query = bound_case()
    result = bind_observation_session(query, h.context)
    observation = select_observation_records(
        query,
        "observation",
        h.context,
    )
    realized = select_observation_records(
        query,
        "realized_session",
        h.context,
    )

    assert content_hash(observation.records[0]) in result.dependency_hashes
    assert content_hash(realized.records[0]) in result.dependency_hashes
