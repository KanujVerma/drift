"""Session clock builders for the M2 evaluator (realized and scheduled modes)."""

from datetime import date, datetime

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockMode,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
from drift.domain.observation_query import ObservationQueryV1
from drift.domain.sessions import (
    GeneratedSessionRowV1,
    RealizedSessionVersionV1,
    ScheduleArtifactV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionKeyV1,
)
from drift.errors import DriftError
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import (
    M1dResolutionContext,
    validate_m1d_resolution_context,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import content_hash

_REALIZED = "realized"
_SCHEDULED = "scheduled_reconstruction"

_required_session_authority = {
    "realized_session_authority": _REALIZED,
    "scheduled_session_reconstruction": _SCHEDULED,
}


def _session_from_authority(
    *,
    session_key: SessionKeyV1,
    opened_at: datetime,
    closed_at: datetime,
    authority: str,
    record_hashes: tuple[str, ...],
    proof_hashes: tuple[str, ...],
) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=session_key,
        opened_at=opened_at,
        closed_at=closed_at,
        authority=authority,
        authority_record_hashes=tuple(sorted(record_hashes)),
        authority_proof_hashes=tuple(sorted(proof_hashes)),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _build_clock(
    *,
    mode: str,
    sessions: tuple[EvaluationSessionV1, ...],
    limitations: tuple[str, ...],
) -> SessionClockV1:
    sessions = tuple(sorted(sessions, key=session_order_key))
    for session in sessions:
        EvaluationSessionV1.model_validate(session.model_dump())
    if not sessions:
        raise ValueError("session clock requires at least one admitted session")
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=mode,
        sessions=sessions,
        acknowledged_limitations=tuple(sorted(limitations)),
        clock_hash="0" * 64,
    )
    candidate = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(candidate.model_dump())


def _ensure_ordered_unique(sessions: tuple[EvaluationSessionV1, ...]) -> None:
    for previous, current in zip(sessions, sessions[1:], strict=False):
        if session_order_key(previous) >= session_order_key(current):
            raise ValueError("session keys must be unique and chronologically ordered")
        if current.opened_at < previous.closed_at:
            raise ValueError("session clock sessions must not overlap")


def build_realized_session_clock(
    queries: tuple[ObservationQueryV1, ...],
    context: M1dResolutionContext,
) -> SessionClockV1:
    """Build a realized-authority clock from authentic selected realized sessions."""
    validate_m1d_resolution_context(context)
    if not queries:
        raise ValueError("realized clock requires at least one session query")
    sessions: list[EvaluationSessionV1] = []
    for query in queries:
        selected = select_observation_records(query, "realized_session", context)
        if selected.proof.classification != "selected" or len(selected.records) != 1:
            raise ValueError(
                "realized clock requires exactly one selected realized session "
                f"for {query.session_date}"
            )
        record = selected.records[0]
        if not isinstance(record, RealizedSessionVersionV1):
            raise ValueError("realized clock selection returned an unexpected record")
        if record.outcome == "did_not_open":
            continue
        if record.outcome != "opened":
            raise ValueError(
                f"realized outcome {record.outcome} cannot authorize a session"
            )
        if record.actual_open is None or record.actual_close is None:
            raise ValueError(
                "realized session cannot authorize without exact actual bounds"
            )
        if record.actual_close <= record.actual_open:
            raise ValueError("realized session close must follow open")
        sessions.append(
            _session_from_authority(
                session_key=record.session_key,
                opened_at=record.actual_open,
                closed_at=record.actual_close,
                authority=_REALIZED,
                record_hashes=(content_hash(record),),
                proof_hashes=(content_hash(selected.proof),),
            )
        )
    sessions_tuple = tuple(sessions)
    _ensure_ordered_unique(sessions_tuple)
    return _build_clock(
        mode="realized_session_authority",
        sessions=sessions_tuple,
        limitations=(),
    )


def build_scheduled_reconstruction_clock(
    queries: tuple[ObservationQueryV1, ...],
    context: M1dResolutionContext,
) -> SessionClockV1:
    """Build a scheduled-reconstruction clock from generated schedule evidence."""
    validate_m1d_resolution_context(context)
    if not queries:
        raise ValueError("scheduled clock requires at least one session query")
    policy = _load_clock_policy(context)
    sessions: list[EvaluationSessionV1] = []
    for query in queries:
        selected = select_observation_records(query, "scheduled_session", context)
        if selected.proof.classification != "selected" or len(selected.records) != 1:
            raise ValueError(
                "scheduled reconstruction requires exactly one selected "
                "scheduled session"
            )
        selected_record = selected.records[0]
        if not isinstance(selected_record, ScheduledSessionVersionV1):
            raise ValueError(
                "scheduled reconstruction selection returned an unexpected record"
            )
        artifact = generate_schedule(query, context, policy)
        if artifact.classification != "generated":
            raise ValueError(
                "scheduled reconstruction cannot use a non-generated artifact "
                f"(got {artifact.classification})"
            )
        rows = _matching_generated_rows(artifact, query)
        if len(rows) != 1:
            raise ValueError(
                "scheduled reconstruction requires exactly one generated session row"
            )
        row = rows[0]
        if row.source_version_hash != content_hash(selected_record):
            raise ValueError(
                "generated schedule source does not match the independently "
                "selected scheduled session"
            )
        output = row.output
        if output.interpretation_status != "authorized":
            raise ValueError(
                "scheduled reconstruction requires an authorized generated output"
            )
        if output.state == "closed":
            continue
        if output.state not in {"regular", "early_close"}:
            raise ValueError(
                f"scheduled reconstruction cannot use a {output.state!r} session"
            )
        if output.utc_open is None or output.utc_close is None:
            raise ValueError(
                "scheduled reconstruction requires exact generated UTC boundaries"
            )
        if output.utc_close <= output.utc_open:
            raise ValueError("scheduled session close must follow open")
        record_hashes = (row.source_version_hash, content_hash(row))
        sessions.append(
            _session_from_authority(
                session_key=output.session_key,
                opened_at=output.utc_open,
                closed_at=output.utc_close,
                authority=_SCHEDULED,
                record_hashes=record_hashes,
                proof_hashes=(
                    content_hash(
                        artifact.model_dump(mode="python", exclude={"generated_at"})
                    ),
                    content_hash(selected.proof),
                ),
            )
        )
    sessions_tuple = tuple(sessions)
    _ensure_ordered_unique(sessions_tuple)
    return _build_clock(
        mode="scheduled_session_reconstruction",
        sessions=sessions_tuple,
        limitations=(
            ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
            ALPACA_LIMITATION_ABSENT_HALTS,
        ),
    )


class SameDateMultiVenueClockError(DriftError, ValueError):
    """Raised when an evaluation clock steps two sessions on one local date.

    Issue 97 ruling, option A. ``SessionClockV1`` admits a non-overlapping
    multi-venue clock whose second venue trades on the same local date, for
    example XNYS on day D then XNAS on day D. Next-open execution needs a
    later local date (section 13.1), so no decision staged before such a
    session could execute there, and the engine refuses the clock at
    construction instead of halting ``INDETERMINATE`` at runtime.
    """


def refuse_same_date_multi_venue_clock(clock: SessionClockV1) -> None:
    """Refuse to evaluate a clock with two sessions on one local date (issue 97).

    Dates are compared across the whole clock, whatever the venue and in
    either mode. Session keys are unique per venue, so on one venue the dates
    already strictly increase and every single-venue clock passes unchanged,
    as does a venue change across dates. The next-open guard in the engine
    stays behind this refusal as defense in depth.

    Dates are read through the base ``date`` methods, never the value's own:
    revalidation keeps a ``date`` subclass (issue 123), whose equality, hash
    and string form could otherwise hide a second session on one date.
    """
    first_on: dict[int, SessionKeyV1] = {}
    for session in clock.sessions:
        key = session.session_key
        ordinal = date.toordinal(key.local_date)
        first = first_on.get(ordinal)
        if first is not None:
            raise SameDateMultiVenueClockError(
                "the session clock steps two sessions on local date "
                f"{date.isoformat(key.local_date)}, {first.mic} then {key.mic}: "
                "next-open execution requires a later local date, so a "
                "same-date multi-venue clock is refused at engine construction "
                "(issue 97 ruling)"
            )
        first_on[ordinal] = key


def rebuild_session_clock(
    mode: SessionClockMode,
    queries: tuple[ObservationQueryV1, ...],
    context: M1dResolutionContext,
) -> SessionClockV1:
    """Re-derive a clock of one mode through that mode's canonical builder."""
    if mode == "realized_session_authority":
        return build_realized_session_clock(queries, context)
    if mode == "scheduled_session_reconstruction":
        return build_scheduled_reconstruction_clock(queries, context)
    raise ValueError(f"unknown session clock mode {mode!r}")


def verify_session_clock(
    clock: SessionClockV1,
    queries: tuple[ObservationQueryV1, ...],
    context: M1dResolutionContext,
) -> None:
    """Require a clock to equal a fresh canonical build over its session queries.

    A clock's own hashes prove only that it is self-consistent, never that a
    builder produced it, so a clock with invented authority hashes, moved
    boundaries, or a scheduled calendar row relabelled as realized is fully
    valid on its own. Rebuilding under the clock's declared mode and requiring
    exact canonical equality proves every session, boundary, authority record,
    proof, and limitation at once (issue 80). The mode is re-derived too: the
    realized builder never emits a scheduled row.
    """
    rebuilt = rebuild_session_clock(clock.mode, queries, context)
    if content_hash(rebuilt) != content_hash(clock):
        raise ValueError(
            "session clock does not match its canonical re-derivation: bundle "
            f"clock {clock.clock_hash}, re-derived {rebuilt.clock_hash}"
        )


def _load_clock_policy(context: M1dResolutionContext) -> ScheduleGenerationPolicyV1:
    digest = context.schedule_generation_policy_hash
    if digest is None:
        raise ValueError("schedule generation policy is unavailable")
    artifact = context.supporting_artifacts.get(digest)
    if artifact is None:
        raise ValueError("schedule generation policy bytes unavailable")
    return ScheduleGenerationPolicyV1.model_validate_json(artifact.data)


def _matching_generated_rows(
    artifact: ScheduleArtifactV1, query: ObservationQueryV1
) -> tuple[GeneratedSessionRowV1, ...]:
    return tuple(
        row
        for row in artifact.rows
        if row.output.session_key.mic == query.venue.value
        and row.output.session_key.local_date == query.session_date
    )
