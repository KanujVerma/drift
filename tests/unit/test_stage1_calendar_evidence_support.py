"""Source-backed, explicitly exploratory closed-world XNYS G2 fixture controls."""

from dataclasses import replace
from datetime import date

import pytest
from exploratory_decision_test_support import merged_scheduled_clock
from observation_test_support import ObservationHarness
from stage1_calendar_evidence_support import (
    FIXTURE_PATH,
    attach_pinned_calendar,
    pinned_source_calendar,
)
from test_evaluator_reconstruction import make_policy

from drift.domain.dataset_validation import DatasetValidationError
from drift.domain.evaluator_execution import IndeterminateExecutionError
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.evaluator.bundles import require_evidenced_clock_density
from drift.evaluator.clock import build_scheduled_reconstruction_clock
from drift.evaluator.reconstruction import ExploratoryReconstructionReplay
from drift.markets.observation_validation import validate_m1d_resolution_context
from drift.markets.session_closed_world import (
    closed_world_record_digest,
    evidenced_session_date_status,
    verify_closed_world_session_coverage,
)


def _harness(day: date) -> ObservationHarness:
    instance = ObservationHarness(session_date=day)
    instance.use_unproven_observation_coverage(mode="absent")
    instance.attach_sessions(realized_outcome="missing")
    return instance


def _query(harness: ObservationHarness, day: date) -> ObservationOutcomeQueryV1:
    return harness.outcome(
        economic_horizon="2026-10-29T00:00:00Z",
        evidence_vintage_cutoff="2026-10-29T00:00:00Z",
        session_date=day.isoformat(),
    )


def test_original_normalized_calendar_is_complete_and_crosschecked() -> None:
    dates, early, raw = pinned_source_calendar()
    assert raw == FIXTURE_PATH.read_bytes()
    assert len(dates) == 461
    assert dates[0] == date(2024, 1, 2)
    assert dates[-1] == date(2025, 10, 31)
    assert dates[455] == date(2025, 10, 24)
    assert date(2024, 1, 15) not in dates
    assert date(2025, 1, 9) not in dates
    assert early[date(2024, 7, 3)] == "13:00"
    assert early[date(2025, 7, 3)] == "13:00"


def test_retained_calendar_replays_weekend_and_holiday_without_guessing() -> None:
    dates, _, _ = pinned_source_calendar()
    harness = _harness(dates[0])
    context = attach_pinned_calendar(harness)
    (coverage,) = verify_closed_world_session_coverage(context)
    for closed in (
        date(2024, 1, 6),
        date(2024, 1, 7),
        date(2024, 1, 15),
        date(2025, 1, 9),
    ):
        assert evidenced_session_date_status((coverage,), "XNYS", closed) == (
            "evidenced_non_trading"
        )
    assert (
        evidenced_session_date_status((coverage,), "XNYS", date(2024, 1, 16))
        == "scheduled_open"
    )
    assert (
        evidenced_session_date_status((coverage,), "XNYS", date(2025, 11, 1))
        == "indeterminate"
    )


def test_actual_clock_density_requires_retained_calendar_response() -> None:
    friday = _harness(date(2024, 1, 5))
    monday = _harness(date(2024, 1, 8))
    q_friday = _query(friday, date(2024, 1, 5))
    q_monday = _query(monday, date(2024, 1, 8))
    friday_clock = build_scheduled_reconstruction_clock((q_friday,), friday.context)
    monday_clock = build_scheduled_reconstruction_clock((q_monday,), monday.context)
    full_clock = merged_scheduled_clock(
        (friday_clock.sessions[0], monday_clock.sessions[0])
    )
    absent = ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=((q_friday, friday.context), (q_monday, monday.context)),
    )
    with pytest.raises(IndeterminateExecutionError, match="2024-01-06"):
        require_evidenced_clock_density(full_clock, absent)
    # A separate upstream reconstructed date source is insufficient; the same
    # actually replayed M1d context must retain the complete source inventory.
    anchor = _harness(date(2024, 1, 2))
    attach_pinned_calendar(anchor)
    q_anchor = _query(anchor, date(2024, 1, 2))
    proven = ExploratoryReconstructionReplay(
        policy=make_policy(),
        requests=((q_anchor, anchor.context), *absent.requests),
    )
    require_evidenced_clock_density(full_clock, proven)


def test_corrupted_retained_calendar_record_is_rejected() -> None:
    harness = _harness(date(2024, 1, 2))
    context = attach_pinned_calendar(harness)
    (coverage,) = verify_closed_world_session_coverage(context)
    digest = closed_world_record_digest(coverage)
    support = dict(context.supporting_artifacts)
    support.pop(digest)
    missing = replace(context, supporting_artifacts=support)
    assert verify_closed_world_session_coverage(missing) == ()
    with pytest.raises(
        DatasetValidationError, match="session_validation_decision_mismatch"
    ):
        validate_m1d_resolution_context(missing)
