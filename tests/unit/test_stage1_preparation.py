"""Unit tests for pure Stage 1 preparation window partition engine.

These tests verify deterministic boundary slicing (warmup 253, observation 126,
and post-observation candidate inputs) under S07, S08, S09, and S38.

Synthetic test fixtures demonstrate partition window mechanics and boundary
invariants; they never certify actual market-source provenance, corporate action
adjustment, or live trading availability.
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockMode,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
from drift.domain.sessions import SessionKeyV1
from drift.experiments.stage1_preparation import (
    STAGE1_OBSERVATION_SESSIONS,
    STAGE1_WARMUP_SESSIONS,
    Stage1PreparationWindows,
    partition_stage1_preparation,
)

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64

_SCHEDULED_LIMITATIONS: tuple[str, ...] = tuple(
    sorted(
        (
            ALPACA_LIMITATION_ABSENT_HALTS,
            ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
        )
    )
)


def _build_synthetic_clock(
    count: int,
    *,
    mode: SessionClockMode = "scheduled_session_reconstruction",
    mic: str = "XNYS",
    start_date: date = date(2024, 1, 2),
) -> SessionClockV1:
    """Construct a validated synthetic SessionClockV1 with `count` sessions."""
    sessions: list[EvaluationSessionV1] = []
    authority = (
        "scheduled_reconstruction"
        if mode == "scheduled_session_reconstruction"
        else "realized"
    )
    limitations = (
        _SCHEDULED_LIMITATIONS if mode == "scheduled_session_reconstruction" else ()
    )

    for i in range(count):
        d = start_date + timedelta(days=i)
        opened = datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)
        closed = datetime(d.year, d.month, d.day, 21, 0, tzinfo=UTC)
        draft_session = EvaluationSessionV1.model_construct(
            schema_version="1",
            session_key=SessionKeyV1(mic=mic, session_scope="regular", local_date=d),
            opened_at=opened,
            closed_at=closed,
            authority=authority,
            authority_record_hashes=(H1,),
            authority_proof_hashes=(H2,),
            session_hash=H0,
        )
        session = draft_session.model_copy(
            update={"session_hash": evaluation_session_hash(draft_session)}
        )
        sessions.append(session)

    draft_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode=mode,
        sessions=tuple(sessions),
        acknowledged_limitations=limitations,
        clock_hash=H0,
    )
    hashed_clock = draft_clock.model_copy(
        update={"clock_hash": session_clock_hash(draft_clock)}
    )
    return SessionClockV1.model_validate(hashed_clock.model_dump(mode="python"))


@pytest.mark.parametrize(
    (
        "total_count",
        "expected_warmup",
        "expected_obs",
        "expected_post",
        "expected_w_complete",
        "expected_o_complete",
    ),
    [
        (1, 1, 0, 0, False, False),
        (252, 252, 0, 0, False, False),
        (253, 253, 0, 0, True, False),
        (254, 253, 1, 0, True, False),
        (378, 253, 125, 0, True, False),
        (379, 253, 126, 0, True, True),
        (380, 253, 126, 1, True, True),
        (400, 253, 126, 21, True, True),
    ],
)
def test_exact_boundary_partitioning(
    total_count: int,
    expected_warmup: int,
    expected_obs: int,
    expected_post: int,
    expected_w_complete: bool,
    expected_o_complete: bool,
) -> None:
    """Verify exact boundary counts for warmup (253) and observation (126)."""
    clock = _build_synthetic_clock(total_count)
    windows = partition_stage1_preparation(clock)

    assert len(windows.warmup_sessions) == expected_warmup
    assert len(windows.observation_sessions) == expected_obs
    assert len(windows.post_observation_sessions) == expected_post
    assert windows.warmup_count_complete is expected_w_complete
    assert windows.observation_count_complete is expected_o_complete

    # Verify concatenated order matches input sessions exactly
    reconstructed = (
        windows.warmup_sessions
        + windows.observation_sessions
        + windows.post_observation_sessions
    )
    assert reconstructed == clock.sessions
    assert all(a is b for a, b in zip(reconstructed, clock.sessions, strict=True))


def test_clock_metadata_and_immutability() -> None:
    """Verify clock metadata preservation and immutability of result dataclass."""
    clock = _build_synthetic_clock(255)
    windows = partition_stage1_preparation(clock)

    assert windows.clock_hash == clock.clock_hash
    assert windows.clock_mode == clock.mode
    assert isinstance(windows.warmup_sessions, tuple)
    assert isinstance(windows.observation_sessions, tuple)
    assert isinstance(windows.post_observation_sessions, tuple)

    with pytest.raises(FrozenInstanceError):
        windows.warmup_count_complete = False  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        windows.clock_hash = "hacked"  # type: ignore[misc]


def test_both_scheduled_and_realized_clock_modes() -> None:
    """Verify partitioner functions with both recognized clock modes."""
    scheduled_clock = _build_synthetic_clock(
        380, mode="scheduled_session_reconstruction"
    )
    sched_windows = partition_stage1_preparation(scheduled_clock)
    assert sched_windows.clock_mode == "scheduled_session_reconstruction"
    assert sched_windows.warmup_count_complete is True
    assert sched_windows.observation_count_complete is True
    assert len(sched_windows.post_observation_sessions) == 1

    realized_clock = _build_synthetic_clock(380, mode="realized_session_authority")
    realized_windows = partition_stage1_preparation(realized_clock)
    assert realized_windows.clock_mode == "realized_session_authority"
    assert realized_windows.warmup_count_complete is True
    assert realized_windows.observation_count_complete is True
    assert len(realized_windows.post_observation_sessions) == 1


def test_post_observation_sessions_are_candidate_inputs_not_authorization() -> None:
    """Post-observation sessions provide candidate chronological timestamps only.

    The completion booleans must never imply data qualification, approved
    B3/B4/B5 strategy eligibility, G1/G2/G3 gate completion, or permission to score.
    """
    clock = _build_synthetic_clock(400)
    windows = partition_stage1_preparation(clock)

    assert windows.warmup_count_complete is True
    assert windows.observation_count_complete is True
    assert len(windows.post_observation_sessions) == 21

    # Verify no authorization attributes exist on Stage1PreparationWindows
    assert not hasattr(windows, "ready_to_score")
    assert not hasattr(windows, "approved")
    assert not hasattr(windows, "qualified")
    assert not hasattr(windows, "authorized_accounts")
    assert not hasattr(windows, "create_account")


def test_fail_closed_on_incorrect_input_type() -> None:
    """Verify partitioner rejects non-SessionClockV1 types."""
    invalid_inputs: list[object] = [None, "clock", 123, {}, [], True]
    for invalid in invalid_inputs:
        with pytest.raises(
            TypeError, match="expected clock to be an instance of SessionClockV1"
        ):
            partition_stage1_preparation(invalid)  # type: ignore[arg-type]


def test_fail_closed_on_forged_clock_hash() -> None:
    """Verify partitioner rejects a clock with forged clock_hash."""
    valid_clock = _build_synthetic_clock(10)
    forged_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=valid_clock.sessions,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=H1,  # wrong hash
    )
    with pytest.raises(ValueError, match="clock hash mismatch"):
        partition_stage1_preparation(forged_clock)


def test_fail_closed_on_forged_session_hash() -> None:
    """Verify partitioner rejects a clock with forged session_hash in a session."""
    valid_clock = _build_synthetic_clock(5)
    tampered_session = valid_clock.sessions[0].model_construct(
        schema_version="1",
        session_key=valid_clock.sessions[0].session_key,
        opened_at=valid_clock.sessions[0].opened_at,
        closed_at=valid_clock.sessions[0].closed_at,
        authority=valid_clock.sessions[0].authority,
        authority_record_hashes=valid_clock.sessions[0].authority_record_hashes,
        authority_proof_hashes=valid_clock.sessions[0].authority_proof_hashes,
        session_hash=H2,  # wrong session hash
    )
    tampered_sessions = (tampered_session, *valid_clock.sessions[1:])
    tampered_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=tampered_sessions,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=session_clock_hash(
            SessionClockV1.model_construct(
                schema_version="1",
                mode=valid_clock.mode,
                sessions=tampered_sessions,
                acknowledged_limitations=valid_clock.acknowledged_limitations,
                clock_hash=H0,
            )
        ),
    )
    with pytest.raises(ValueError, match="session hash mismatch"):
        partition_stage1_preparation(tampered_clock)


def test_fail_closed_on_out_of_order_sessions() -> None:
    """Verify partitioner rejects chronologically unordered sessions."""
    valid_clock = _build_synthetic_clock(5)
    swapped = (
        valid_clock.sessions[1],
        valid_clock.sessions[0],
        *valid_clock.sessions[2:],
    )
    out_of_order_draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=swapped,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=H0,
    )
    out_of_order_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=swapped,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=session_clock_hash(out_of_order_draft),
    )
    with pytest.raises(ValueError):
        partition_stage1_preparation(out_of_order_clock)


def test_fail_closed_on_duplicate_session_keys() -> None:
    """Verify partitioner rejects duplicate session keys."""
    valid_clock = _build_synthetic_clock(5)
    duplicate_sessions = (
        valid_clock.sessions[0],
        valid_clock.sessions[0],
        *valid_clock.sessions[2:],
    )
    dup_draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=duplicate_sessions,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=H0,
    )
    dup_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode=valid_clock.mode,
        sessions=duplicate_sessions,
        acknowledged_limitations=valid_clock.acknowledged_limitations,
        clock_hash=session_clock_hash(dup_draft),
    )
    with pytest.raises(ValueError):
        partition_stage1_preparation(dup_clock)


def test_fail_closed_on_overlapping_sessions() -> None:
    """Verify partitioner rejects overlapping session timestamps."""
    d1 = date(2024, 1, 2)
    d2 = date(2024, 1, 3)
    s1_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d1),
        opened_at=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s1 = s1_draft.model_copy(update={"session_hash": evaluation_session_hash(s1_draft)})

    # Overlaps with s1: opens before s1 closes
    s2_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d2),
        opened_at=datetime(2024, 1, 2, 20, 0, tzinfo=UTC),  # overlaps with s1
        closed_at=datetime(2024, 1, 3, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s2 = s2_draft.model_copy(update={"session_hash": evaluation_session_hash(s2_draft)})

    clock_draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s1, s2),
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    clock = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s1, s2),
        acknowledged_limitations=(),
        clock_hash=session_clock_hash(clock_draft),
    )
    with pytest.raises(ValueError, match="overlapping sessions detected|overlap"):
        partition_stage1_preparation(clock)


def test_fail_closed_on_mixed_venue_mics() -> None:
    """Verify partitioner rejects mixed venue MICs (no multi-venue alignment)."""
    d1 = date(2024, 1, 2)
    d2 = date(2024, 1, 3)
    s1_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d1),
        opened_at=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s1 = s1_draft.model_copy(update={"session_hash": evaluation_session_hash(s1_draft)})

    s2_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNAS", session_scope="regular", local_date=d2),
        opened_at=datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 3, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s2 = s2_draft.model_copy(update={"session_hash": evaluation_session_hash(s2_draft)})

    draft_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s1, s2),
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    hashed_clock = draft_clock.model_copy(
        update={"clock_hash": session_clock_hash(draft_clock)}
    )
    clock = SessionClockV1.model_validate(hashed_clock.model_dump(mode="python"))

    with pytest.raises(ValueError, match="mixed venue MICs are rejected"):
        partition_stage1_preparation(clock)


def test_fail_closed_on_nonmonotone_local_dates() -> None:
    """Verify partitioner rejects non-increasing or decreasing local dates."""
    d1 = date(2024, 1, 3)
    d2 = date(2024, 1, 2)  # Decreasing date
    s1_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d1),
        opened_at=datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s1 = s1_draft.model_copy(update={"session_hash": evaluation_session_hash(s1_draft)})

    s2_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(mic="XNYS", session_scope="regular", local_date=d2),
        opened_at=datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 3, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s2 = s2_draft.model_copy(update={"session_hash": evaluation_session_hash(s2_draft)})

    clock_draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s1, s2),
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    clock = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s1, s2),
        acknowledged_limitations=(),
        clock_hash=session_clock_hash(clock_draft),
    )
    with pytest.raises(ValueError):
        partition_stage1_preparation(clock)


def test_fail_closed_on_empty_clock() -> None:
    """Verify partitioner rejects empty clock with zero sessions."""
    empty_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(),
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    with pytest.raises(ValueError, match="session clock requires at least one session"):
        partition_stage1_preparation(empty_clock)


def test_no_date_interpolation_over_calendar_gaps() -> None:
    """Verify partitioner does not interpolate or fabricate missing calendar days.

    Skipped days (such as weekends or holidays) must not cause synthetic
    session generation.
    """
    friday = date(2024, 1, 5)
    monday = date(2024, 1, 8)  # Saturday (Jan 6) and Sunday (Jan 7) skipped
    s_fri_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=friday
        ),
        opened_at=datetime(2024, 1, 5, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 5, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s_fri = s_fri_draft.model_copy(
        update={"session_hash": evaluation_session_hash(s_fri_draft)}
    )

    s_mon_draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=monday
        ),
        opened_at=datetime(2024, 1, 8, 14, 30, tzinfo=UTC),
        closed_at=datetime(2024, 1, 8, 21, 0, tzinfo=UTC),
        authority="realized",
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    s_mon = s_mon_draft.model_copy(
        update={"session_hash": evaluation_session_hash(s_mon_draft)}
    )

    draft_clock = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=(s_fri, s_mon),
        acknowledged_limitations=(),
        clock_hash=H0,
    )
    hashed_clock = draft_clock.model_copy(
        update={"clock_hash": session_clock_hash(draft_clock)}
    )
    clock = SessionClockV1.model_validate(hashed_clock.model_dump(mode="python"))

    windows = partition_stage1_preparation(clock)
    # Exactly 2 sessions; no Saturday or Sunday sessions fabricated
    assert len(windows.warmup_sessions) == 2
    assert len(windows.observation_sessions) == 0
    assert len(windows.post_observation_sessions) == 0
    assert windows.warmup_sessions[0].session_key.local_date == friday
    assert windows.warmup_sessions[1].session_key.local_date == monday


def test_no_mutation_of_caller_state() -> None:
    """Verify partitioner does not mutate input clock or its sessions."""
    clock = _build_synthetic_clock(10)
    original_sessions = clock.sessions
    original_hash = clock.clock_hash

    windows = partition_stage1_preparation(clock)

    assert clock.sessions is original_sessions
    assert clock.clock_hash == original_hash
    assert windows.warmup_sessions == original_sessions


def test_constants_and_types() -> None:
    """Verify exported Stage 1 preparation constants and dataclass typing."""
    assert STAGE1_WARMUP_SESSIONS == 253
    assert STAGE1_OBSERVATION_SESSIONS == 126

    clock = _build_synthetic_clock(1)
    windows = partition_stage1_preparation(clock)
    assert isinstance(windows, Stage1PreparationWindows)


def _shallow(model: object) -> dict[str, Any]:
    """Return a shallow dictionary of model field names to values."""
    fields = getattr(type(model), "model_fields", {})
    return {name: getattr(model, name) for name in fields}


def test_fail_closed_on_reversed_authority_record_hashes_preserved_hashes() -> None:
    """Exact regression: reversed authority_record_hashes with preserved claimed hashes.

    Must reject because the original session hash and clock hash differ from
    their claimed values, even though validating a normalized copy would sort
    the hashes.
    """
    base = _build_synthetic_clock(1)
    session_values = _shallow(base.sessions[0])
    session_values["authority_record_hashes"] = ("1" * 64, "2" * 64)
    session_draft = EvaluationSessionV1.model_construct(**session_values)
    session_values["session_hash"] = evaluation_session_hash(session_draft)
    session = EvaluationSessionV1.model_validate(session_values)

    clock_values = _shallow(base)
    clock_values["sessions"] = (session,)
    clock_draft = SessionClockV1.model_construct(**clock_values)
    clock_values["clock_hash"] = session_clock_hash(clock_draft)
    clock = SessionClockV1.model_validate(clock_values)

    # Control: verified valid input passes and preserves object identity
    control = partition_stage1_preparation(clock)
    assert control.warmup_sessions[0] is session
    assert control.clock_hash == clock.clock_hash

    # Tampered: reverse authority_record_hashes, preserving claimed hashes
    forged_values = _shallow(session)
    forged_values["authority_record_hashes"] = tuple(
        reversed(session.authority_record_hashes)
    )
    forged_session = EvaluationSessionV1.model_construct(**forged_values)
    forged_clock_values = _shallow(clock)
    forged_clock_values["sessions"] = (forged_session,)
    forged_clock = SessionClockV1.model_construct(**forged_clock_values)

    assert evaluation_session_hash(forged_session) != forged_session.session_hash
    assert session_clock_hash(forged_clock) != forged_clock.clock_hash

    with pytest.raises(ValueError, match="hash mismatch"):
        partition_stage1_preparation(forged_clock)


def test_fail_closed_on_reversed_authority_proof_hashes_preserved_hashes() -> None:
    """Analogous regression: reversed proof hashes with preserved claimed hashes."""
    base = _build_synthetic_clock(1)
    session_values = _shallow(base.sessions[0])
    session_values["authority_proof_hashes"] = ("1" * 64, "2" * 64)
    session_draft = EvaluationSessionV1.model_construct(**session_values)
    session_values["session_hash"] = evaluation_session_hash(session_draft)
    session = EvaluationSessionV1.model_validate(session_values)

    clock_values = _shallow(base)
    clock_values["sessions"] = (session,)
    clock_draft = SessionClockV1.model_construct(**clock_values)
    clock_values["clock_hash"] = session_clock_hash(clock_draft)
    clock = SessionClockV1.model_validate(clock_values)

    control = partition_stage1_preparation(clock)
    assert control.warmup_sessions[0] is session

    forged_values = _shallow(session)
    forged_values["authority_proof_hashes"] = tuple(
        reversed(session.authority_proof_hashes)
    )
    forged_session = EvaluationSessionV1.model_construct(**forged_values)
    forged_clock_values = _shallow(clock)
    forged_clock_values["sessions"] = (forged_session,)
    forged_clock = SessionClockV1.model_construct(**forged_clock_values)

    assert evaluation_session_hash(forged_session) != forged_session.session_hash
    with pytest.raises(ValueError, match="hash mismatch"):
        partition_stage1_preparation(forged_clock)


def test_fail_closed_on_unsorted_acknowledged_limitations_preserved_hashes() -> None:
    """Analogous regression: unsorted limitations with preserved claimed hash."""
    base = _build_synthetic_clock(1, mode="scheduled_session_reconstruction")

    # Unsorted limitations: ABSENT_HALTS ('t') before SCHEDULED_RECONSTRUCTION ('s')
    unsorted_limits = (
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    )
    forged_clock_values = _shallow(base)
    forged_clock_values["acknowledged_limitations"] = unsorted_limits
    # Keep claimed clock_hash matching the sorted base clock
    forged_clock_values["clock_hash"] = base.clock_hash
    forged_clock = SessionClockV1.model_construct(**forged_clock_values)

    assert session_clock_hash(forged_clock) != forged_clock.clock_hash
    with pytest.raises(ValueError, match="hash mismatch"):
        partition_stage1_preparation(forged_clock)


def test_fail_closed_on_unnormalized_data_with_recomputed_hashes() -> None:
    """Reject unnormalized data even when hashes are recomputed for unnormalized bytes.

    If contract revalidation would canonicalize or sort fields, the original
    unnormalized data must not be returned.
    """
    base = _build_synthetic_clock(1)
    session = base.sessions[0]

    # 1. Unnormalized authority_record_hashes with recomputed session hash
    unnorm_rec_values = _shallow(session)
    unnorm_rec_values["authority_record_hashes"] = ("2" * 64, "1" * 64)
    unnorm_rec_draft = EvaluationSessionV1.model_construct(**unnorm_rec_values)
    unnorm_rec_values["session_hash"] = evaluation_session_hash(unnorm_rec_draft)
    unnorm_rec_session = EvaluationSessionV1.model_construct(**unnorm_rec_values)

    clock_values1 = _shallow(base)
    clock_values1["sessions"] = (unnorm_rec_session,)
    clock_draft1 = SessionClockV1.model_construct(**clock_values1)
    clock_values1["clock_hash"] = session_clock_hash(clock_draft1)
    clock1 = SessionClockV1.model_construct(**clock_values1)

    with pytest.raises(ValueError):
        partition_stage1_preparation(clock1)

    # 2. Unnormalized authority_proof_hashes with recomputed session hash
    unnorm_proof_values = _shallow(session)
    unnorm_proof_values["authority_proof_hashes"] = ("2" * 64, "1" * 64)
    unnorm_proof_draft = EvaluationSessionV1.model_construct(**unnorm_proof_values)
    unnorm_proof_values["session_hash"] = evaluation_session_hash(unnorm_proof_draft)
    unnorm_proof_session = EvaluationSessionV1.model_construct(**unnorm_proof_values)

    clock_values2 = _shallow(base)
    clock_values2["sessions"] = (unnorm_proof_session,)
    clock_draft2 = SessionClockV1.model_construct(**clock_values2)
    clock_values2["clock_hash"] = session_clock_hash(clock_draft2)
    clock2 = SessionClockV1.model_construct(**clock_values2)

    with pytest.raises(ValueError):
        partition_stage1_preparation(clock2)

    # 3. Unnormalized acknowledged_limitations with recomputed clock hash
    sched_base = _build_synthetic_clock(1, mode="scheduled_session_reconstruction")
    unsorted_limits = (
        ALPACA_LIMITATION_ABSENT_HALTS,
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    )
    clock_values3 = _shallow(sched_base)
    clock_values3["acknowledged_limitations"] = unsorted_limits
    clock_draft3 = SessionClockV1.model_construct(**clock_values3)
    clock_values3["clock_hash"] = session_clock_hash(clock_draft3)
    clock3 = SessionClockV1.model_construct(**clock_values3)

    with pytest.raises(ValueError):
        partition_stage1_preparation(clock3)


def test_no_mutation_of_caller_state_on_rejection() -> None:
    """Verify partitioner does not mutate input clock or sessions when rejecting."""
    base = _build_synthetic_clock(1)
    forged_values = _shallow(base.sessions[0])
    forged_values["authority_record_hashes"] = ("2" * 64, "1" * 64)
    forged_session = EvaluationSessionV1.model_construct(**forged_values)
    forged_clock_values = _shallow(base)
    forged_clock_values["sessions"] = (forged_session,)
    forged_clock = SessionClockV1.model_construct(**forged_clock_values)

    orig_clock_hash = forged_clock.clock_hash
    orig_session_hash = forged_session.session_hash
    orig_rec_hashes = forged_session.authority_record_hashes

    with pytest.raises(ValueError):
        partition_stage1_preparation(forged_clock)

    assert forged_clock.clock_hash == orig_clock_hash
    assert forged_session.session_hash == orig_session_hash
    assert forged_session.authority_record_hashes == orig_rec_hashes
