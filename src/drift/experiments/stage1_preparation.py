"""Stage 1 session history preparation windows (warmup, observation, post-observation).

This module partitions an immutable, validated SessionClockV1 into standard
Stage 1 preparation windows per S07, S08, S09, and S38 of stage1-decisions.md.

It is a pure, deterministic, dependency-free partition engine. It does not
validate market source provenance, rights, or completeness, and produces
strictly chronological input partitions. The presence of complete count
windows does NOT imply data qualification, approved B3/B4/B5 strategy
eligibility, Gate G1/G2/G3 completion, or permission to score campaigns or trade.
"""

from dataclasses import dataclass

from drift.domain.common import SHA256Hash
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockMode,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)

STAGE1_WARMUP_SESSIONS: int = 253
STAGE1_OBSERVATION_SESSIONS: int = 126


@dataclass(frozen=True, slots=True)
class Stage1PreparationWindows:
    """Immutable, non-persisted preparation windows for Stage 1 evaluation.

    Contains the original clock metadata and slices of the validated sessions
    partitioned into warmup (first 253), observation (next 126), and
    post-observation candidate input sessions.

    The boolean flags `warmup_count_complete` and `observation_count_complete`
    strictly reflect whether the expected session count thresholds (253 and 126)
    have been satisfied. They do NOT imply:
    - Market data qualification or provenance verification.
    - Approved B3/B4/B5 strategy eligibility.
    - Gate G1/G2/G3 completion.
    - A scored experiment campaign.
    - Authorization to create, credit, or trade accounts.
    """

    clock_hash: SHA256Hash
    clock_mode: SessionClockMode
    warmup_sessions: tuple[EvaluationSessionV1, ...]
    observation_sessions: tuple[EvaluationSessionV1, ...]
    post_observation_sessions: tuple[EvaluationSessionV1, ...]
    warmup_count_complete: bool
    observation_count_complete: bool


def partition_stage1_preparation(clock: SessionClockV1) -> Stage1PreparationWindows:
    """Partition a validated SessionClockV1 into Stage 1 preparation windows.

    Validates that:
    1. The input is an instance of SessionClockV1.
    2. The caller's original clock_hash matches session_clock_hash(clock).
    3. Each caller session's claimed session_hash matches
       evaluation_session_hash(session).
    4. The clock cleanly revalidates through SessionClockV1.model_validate
       without any normalization discrepancy or contract violation.
    5. All sessions belong to a single venue MIC (multi-venue clocks are
       refused pending an accepted multi-venue calendar alignment contract).
    6. Sessions are strictly ordered chronologically with strictly increasing
       local dates and no time overlaps.
    7. No calendar sessions are fabricated or interpolated.

    Args:
        clock: Validated immutable session clock.

    Returns:
        Stage1PreparationWindows containing immutable tuples of existing
        EvaluationSessionV1 objects.

    Raises:
        TypeError: If clock is not a SessionClockV1 instance.
        ValueError: If clock is invalid, empty, forged, overlapping, out-of-order,
            contains mixed venue MICs, has non-monotone dates, or exhibits any
            normalization discrepancy.
    """
    if not isinstance(clock, SessionClockV1):
        raise TypeError(
            f"expected clock to be an instance of SessionClockV1, "
            f"got {type(clock).__name__}"
        )

    if not clock.sessions:
        raise ValueError("session clock requires at least one session")

    # 1. Verify original input hashes directly on caller's objects before normalization
    expected_original_clock_hash = session_clock_hash(clock)
    if clock.clock_hash != expected_original_clock_hash:
        raise ValueError(
            f"clock hash mismatch: expected {expected_original_clock_hash}, "
            f"got {clock.clock_hash}"
        )

    for session in clock.sessions:
        expected_original_session_hash = evaluation_session_hash(session)
        if session.session_hash != expected_original_session_hash:
            raise ValueError(
                f"session hash mismatch for {session.session_key}: "
                f"expected {expected_original_session_hash}, "
                f"got {session.session_hash}"
            )

    # 2. Revalidate from Python dictionary dump to enforce contract invariants
    dump = clock.model_dump(mode="python")
    try:
        validated_clock = SessionClockV1.model_validate(dump)
    except Exception as err:
        raise ValueError(f"clock failed model revalidation: {err}") from err

    # 3. Reject any normalization discrepancy between caller's data and validated data
    if clock.clock_hash != validated_clock.clock_hash:
        raise ValueError("clock hash differs from validated canonical representation")

    if clock.acknowledged_limitations != validated_clock.acknowledged_limitations:
        raise ValueError(
            "clock acknowledged_limitations differ from "
            "validated canonical representation"
        )

    if len(clock.sessions) != len(validated_clock.sessions):
        raise ValueError("clock session count differs from validated sessions")

    for original_session, validated_session in zip(
        clock.sessions, validated_clock.sessions, strict=True
    ):
        if (
            original_session.session_hash != validated_session.session_hash
            or original_session.authority_record_hashes
            != validated_session.authority_record_hashes
            or original_session.authority_proof_hashes
            != validated_session.authority_proof_hashes
            or original_session != validated_session
        ):
            raise ValueError(
                f"original session {original_session.session_key} differs from "
                "validated canonical representation"
            )

    # 4. Refuse mixed venue MICs (S38 / issue 97 alignment requirement)
    mics = {session.session_key.mic for session in clock.sessions}
    if len(mics) > 1:
        raise ValueError(
            "mixed venue MICs are rejected without multi-venue calendar alignment: "
            f"{sorted(mics)}"
        )

    # 5. Verify strict chronological order, monotonicity, and non-overlap
    sessions = clock.sessions
    for prev, curr in zip(sessions, sessions[1:], strict=False):
        if curr.session_key.local_date <= prev.session_key.local_date:
            raise ValueError(
                "session local dates must be strictly monotonically increasing: "
                f"{prev.session_key.local_date} followed by "
                f"{curr.session_key.local_date}"
            )
        if curr.opened_at < prev.closed_at:
            raise ValueError(
                f"overlapping sessions detected: session {prev.session_key} "
                f"closes at {prev.closed_at} after next session "
                f"{curr.session_key} opens at {curr.opened_at}"
            )
        if curr.opened_at <= prev.opened_at:
            raise ValueError(
                f"sessions must be strictly chronologically ordered: "
                f"{prev.opened_at} followed by {curr.opened_at}"
            )
        if curr.closed_at <= curr.opened_at:
            raise ValueError(
                f"session closed_at must follow opened_at for {curr.session_key}"
            )

    # 6. Slice into windows without manufacturing skipped sessions
    total_sessions = len(sessions)
    warmup_sessions = sessions[: min(total_sessions, STAGE1_WARMUP_SESSIONS)]
    observation_sessions = (
        sessions[
            STAGE1_WARMUP_SESSIONS : min(
                total_sessions,
                STAGE1_WARMUP_SESSIONS + STAGE1_OBSERVATION_SESSIONS,
            )
        ]
        if total_sessions > STAGE1_WARMUP_SESSIONS
        else ()
    )
    post_observation_sessions = (
        sessions[STAGE1_WARMUP_SESSIONS + STAGE1_OBSERVATION_SESSIONS :]
        if total_sessions > STAGE1_WARMUP_SESSIONS + STAGE1_OBSERVATION_SESSIONS
        else ()
    )

    warmup_count_complete = len(warmup_sessions) == STAGE1_WARMUP_SESSIONS
    observation_count_complete = (
        warmup_count_complete
        and len(observation_sessions) == STAGE1_OBSERVATION_SESSIONS
    )

    return Stage1PreparationWindows(
        clock_hash=clock.clock_hash,
        clock_mode=clock.mode,
        warmup_sessions=warmup_sessions,
        observation_sessions=observation_sessions,
        post_observation_sessions=post_observation_sessions,
        warmup_count_complete=warmup_count_complete,
        observation_count_complete=observation_count_complete,
    )
