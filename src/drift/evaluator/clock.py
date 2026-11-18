"""Session clock builders for the M2 evaluator (realized and scheduled modes)."""

from collections.abc import Callable, Mapping
from datetime import date, datetime
from inspect import iscoroutine
from typing import Literal

from drift.datasets.hashing import manifest_hash
from drift.domain.evaluator_clock import (
    CommonSessionClockV1,
    CommonVenueSessionV1,
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
from drift.domain.observation_query import (
    ObservationDecisionQueryV1,
    ObservationQueryV1,
    ObservationSourceSelectionPolicyV1,
)
from drift.domain.session_closed_world import ClosedWorldSessionCoverageV1
from drift.domain.sessions import (
    GeneratedSessionRowV1,
    RealizedSessionVersionV1,
    ScheduleArtifactV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionCoverageVersionV1,
    SessionKeyV1,
)
from drift.domain.temporal import CutoffEligibility
from drift.errors import DriftError
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.markets.session_closed_world import (
    closed_world_record_digest,
    evidenced_session_date_status,
    verify_closed_world_session_coverage,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import content_hash

_REALIZED = "realized"
_SCHEDULED = "scheduled_reconstruction"

_required_session_authority = {
    "realized_session_authority": _REALIZED,
    "scheduled_session_reconstruction": _SCHEDULED,
}


def require_common_replay_inventory(
    clock: CommonSessionClockV1,
    queries: tuple[ObservationQueryV1, ...],
) -> tuple[ObservationDecisionQueryV1, ...]:
    """Match the declared query for every member, without admitting a clock.

    This inventory check is only one prerequisite. Callers must independently
    replay every matched query against its authorized context and prove the
    entire venue interval before making any execution decision.
    """
    clock = CommonSessionClockV1.model_validate(clock.model_dump(mode="python"))
    by_hash: dict[str, ObservationDecisionQueryV1] = {}
    for supplied in queries:
        if not isinstance(supplied, ObservationDecisionQueryV1):
            raise ValueError("common replay inventory requires decision queries")
        query = ObservationDecisionQueryV1.model_validate(
            supplied.model_dump(mode="python")
        )
        digest = content_hash(query)
        if digest in by_hash:
            raise ValueError("common replay inventory has a duplicate query")
        by_hash[digest] = query
    matched: list[ObservationDecisionQueryV1] = []
    for group in clock.sessions:
        for member in group.members:
            matched_query = by_hash.get(member.selection_query_hash)
            if matched_query is None:
                raise ValueError("common replay inventory is missing a member query")
            del by_hash[member.selection_query_hash]
            if (
                matched_query.venue.value != member.session.session_key.mic
                or matched_query.session_date != group.local_date
                or matched_query.input_context_hash != member.resolution_context_hash
                or matched_query.source_selection_policy_hash
                != member.source_policy_hash
                or matched_query.decision_time != group.closed_at
                or matched_query.knowledge_cutoff > group.closed_at
                or matched_query.effective_cutoff > group.closed_at
            ):
                raise ValueError("common replay inventory has a mismatched member")
            matched.append(matched_query)
    if by_hash:
        raise ValueError("common replay inventory contains an extra query")
    return tuple(matched)


def replay_common_venue_session(
    member: CommonVenueSessionV1,
    query: ObservationDecisionQueryV1,
    context: M1dResolutionContext,
) -> EvaluationSessionV1:
    """Rederive one member; this alone does not authenticate or admit a clock."""
    member = CommonVenueSessionV1.model_validate(member.model_dump(mode="python"))
    query = ObservationDecisionQueryV1.model_validate(query.model_dump(mode="python"))
    session = member.session
    if (
        member.resolution_context_hash != m1d_context_hash(context)
        or query.input_context_hash != member.resolution_context_hash
        or member.selection_query_hash != content_hash(query)
        or member.source_policy_hash != query.source_selection_policy_hash
        or query.venue.value != session.session_key.mic
        or query.session_date != session.session_key.local_date
        or query.decision_time != session.closed_at
    ):
        raise ValueError("common venue replay identity mismatch")
    purpose = (
        "scheduled_session"
        if session.authority == "scheduled_reconstruction"
        else "realized_session"
    )
    selected = select_observation_records(query, purpose, context)
    if selected.proof.classification != "selected" or len(selected.records) != 1:
        raise ValueError("common venue replay requires one selected authority record")
    record = selected.records[0]
    if not isinstance(record, ScheduledSessionVersionV1 | RealizedSessionVersionV1):
        raise ValueError("common venue replay selected a non-session record")
    source_evidence = {content_hash(item) for item in record.revision.availability}
    witnessed = tuple(
        decision
        for decision in selected.proof.availability_decisions
        if decision.evidence_hash == member.availability_evidence_hash
        and decision.evidence_hash in source_evidence
        and decision.classification is CutoffEligibility.ELIGIBLE
        and decision.evidence.lower_bound == member.first_available_at
        and decision.evidence.upper_bound == member.first_available_at
        and decision.cutoff == query.knowledge_cutoff
        and decision.requested_channel == query.requested_channel
        and decision.policy_hash == query.availability_policy_hash
    )
    if len(witnessed) != 1 or member.first_available_at > query.knowledge_cutoff:
        raise ValueError("common venue replay availability is not witnessed")
    mode: SessionClockMode = (
        "scheduled_session_reconstruction"
        if purpose == "scheduled_session"
        else "realized_session_authority"
    )
    rederived = rebuild_session_clock(mode, (query,), context)
    if len(rederived.sessions) != 1 or rederived.sessions[0] != session:
        raise ValueError("common venue replay session does not match source authority")
    return rederived.sessions[0]


def replay_common_session_members(
    clock: CommonSessionClockV1,
    requests: tuple[tuple[ObservationDecisionQueryV1, M1dResolutionContext], ...],
) -> tuple[EvaluationSessionV1, ...]:
    """Replay members; coverage and source authorization remain separate."""
    matched = require_common_replay_inventory(
        clock, tuple(query for query, _ in requests)
    )
    contexts = {content_hash(query): context for query, context in requests}
    members = tuple(member for group in clock.sessions for member in group.members)
    return tuple(
        replay_common_venue_session(member, query, contexts[content_hash(query)])
        for member, query in zip(members, matched, strict=True)
    )


def require_common_interval_inventory(
    clock: CommonSessionClockV1,
    coverage: tuple[ClosedWorldSessionCoverageV1, ...],
) -> None:
    """Compare every venue/date to coverage; callers must verify its origin.

    These structural records are not authenticated here. In particular, a
    caller must obtain them from venue-scoped authorized replay contexts,
    rather than relabeling a consolidated calendar as two separate sources.
    """
    clock = CommonSessionClockV1.model_validate(clock.model_dump(mode="python"))
    if clock.mode != "scheduled_session_reconstruction":
        raise ValueError(
            "common interval scheduled coverage cannot prove realized dates"
        )
    records = tuple(
        ClosedWorldSessionCoverageV1.model_validate(record.model_dump(mode="python"))
        for record in coverage
    )
    if any(
        record.mic not in clock.expected_venues or not record.completeness.positive
        for record in records
    ):
        raise ValueError("common interval has foreign or incomplete coverage")
    by_venue = {
        venue: tuple(record for record in records if record.mic == venue)
        for venue in clock.expected_venues
    }
    if any(not rows for rows in by_venue.values()):
        raise ValueError("common interval is missing venue coverage")
    request_venues: dict[str, str] = {}
    observation_venues: dict[str, str] = {}
    for venue, rows in by_venue.items():
        for record in rows:
            previous_request = request_venues.setdefault(
                record.request_binding_hash, venue
            )
            previous_observation = observation_venues.setdefault(
                record.origin_observation_hash, venue
            )
            if previous_request != venue or previous_observation != venue:
                raise ValueError("common interval reuses an acquisition across venues")
    expected = set(clock.expected_session_dates)
    for ordinal in range(
        clock.window_start.toordinal(), clock.window_end.toordinal() + 1
    ):
        day = date.fromordinal(ordinal)
        wanted = "scheduled_open" if day in expected else "evidenced_non_trading"
        for venue, rows in by_venue.items():
            actual = evidenced_session_date_status(rows, venue, day)
            if actual != wanted:
                raise ValueError(
                    f"common interval {venue} {day.isoformat()} is {actual}, "
                    f"expected {wanted}"
                )


def _coverage_binds_selected_session(
    coverage: ClosedWorldSessionCoverageV1,
    selected_coverage_hash: str,
    selected_hash: str,
    context: M1dResolutionContext,
) -> bool:
    """Join the selected row to the dataset a verified coverage row covers."""
    coverage_digest = closed_world_record_digest(coverage)
    datasets = {manifest_hash(item.manifest): item for item in context.session_datasets}
    for dataset in context.session_datasets:
        for row in dataset.records:
            if (
                not isinstance(row, SessionCoverageVersionV1)
                or content_hash(row) != selected_coverage_hash
                or row.revision.source_artifact.content_hash != coverage_digest
            ):
                continue
            for digest in row.covered_dataset_hashes:
                target = datasets.get(digest)
                if target is not None and any(
                    isinstance(record, ScheduledSessionVersionV1)
                    and content_hash(record) == selected_hash
                    and record.revision.source_artifact.content_hash
                    == coverage.response_sha256
                    for record in target.records
                ):
                    return True
    return False


def verify_common_clock_replay(
    clock: CommonSessionClockV1,
    requests: tuple[tuple[ObservationDecisionQueryV1, M1dResolutionContext], ...],
    authorized_sources: Mapping[str, tuple[str, str]],
    coverage_verifiers: Mapping[
        str, Callable[[ClosedWorldSessionCoverageV1, M1dResolutionContext], None]
    ]
    | None = None,
) -> tuple[EvaluationSessionV1, ...]:
    """Rederive a scheduled clock against externally configured venue sources.

    The caller must authenticate the source configuration and its issuer.
    A self-selected policy, these hashes, or this function alone cannot confer
    source authenticity, promotion eligibility, or a realized session.
    """
    if clock.mode != "scheduled_session_reconstruction":
        raise ValueError("common clock replay currently requires scheduled authority")
    if set(authorized_sources) != set(clock.expected_venues):
        raise ValueError("common clock source configuration must cover its venues")
    if coverage_verifiers is None or set(coverage_verifiers) != set(
        clock.expected_venues
    ):
        raise ValueError(
            "common clock requires a source-specific verifier for each venue"
        )
    sessions = replay_common_session_members(clock, requests)
    by_query = {content_hash(query): (query, context) for query, context in requests}
    records: dict[str, ClosedWorldSessionCoverageV1] = {}
    earliest_cutoff = clock.sessions[0].closed_at
    for group in clock.sessions:
        for member in group.members:
            query, context = by_query[member.selection_query_hash]
            expected_policy, expected_source = authorized_sources[query.venue.value]
            if query.source_selection_policy_hash != expected_policy:
                raise ValueError("common clock source policy is not authorized")
            policy_artifact = context.supporting_artifacts.get(expected_policy)
            if policy_artifact is None:
                raise ValueError("common clock source policy is unavailable")
            policy = ObservationSourceSelectionPolicyV1.model_validate_json(
                policy_artifact.data
            )
            for role in ("scheduled_session", "session_coverage"):
                matches = tuple(
                    binding
                    for binding in policy.bindings
                    if binding.dataset_role == role
                    and binding.venue == query.venue
                    and binding.listing_id == query.listing_id
                    and binding.source_id == expected_source
                    and binding.start_date <= clock.window_start
                    and binding.end_date >= clock.window_end
                )
                if len(matches) != 1:
                    raise ValueError(
                        "common clock policy does not cover the full interval"
                    )
            selected = select_observation_records(query, "scheduled_session", context)
            if len(selected.records) != 1 or not isinstance(
                selected.records[0], ScheduledSessionVersionV1
            ):
                raise ValueError("common clock selected session is unavailable")
            selected_record = selected.records[0]
            if selected_record.source_id != expected_source:
                raise ValueError("common clock selected source is not authorized")
            selected_coverage = select_observation_records(
                query, "session_coverage", context
            )
            if (
                selected_coverage.proof.classification != "selected"
                or len(selected_coverage.records) != 1
                or not isinstance(
                    selected_coverage.records[0], SessionCoverageVersionV1
                )
            ):
                raise ValueError("common clock coverage was not selected at the cutoff")
            coverage_row = selected_coverage.records[0]
            if (
                coverage_row.status != "expected_complete"
                or coverage_row.revision_history_completeness != "complete"
                or coverage_row.expected_daily_cardinality != 1
                or coverage_row.exception_dates
                or coverage_row.missing_artifact_hashes
            ):
                raise ValueError("common clock coverage is incomplete")
            selected_coverage_hash = content_hash(coverage_row)
            candidates = verify_closed_world_session_coverage(context)
            joined = tuple(
                coverage
                for coverage in candidates
                if _coverage_binds_selected_session(
                    coverage,
                    selected_coverage_hash,
                    content_hash(selected_record),
                    context,
                )
            )
            if not joined:
                raise ValueError(
                    "common clock session lacks its exact coverage binding"
                )
            for coverage in joined:
                if (
                    coverage.mic != query.venue.value
                    or coverage.source_id != expected_source
                    or coverage.availability_channel != query.requested_channel
                    or coverage_row.snapshot_as_of != coverage.snapshot_as_of
                    or coverage_row.snapshot_as_of.upper_bound is None
                    or coverage_row.snapshot_as_of.upper_bound
                    > min(earliest_cutoff, query.knowledge_cutoff)
                    or coverage.snapshot_as_of.upper_bound is None
                    or coverage.snapshot_as_of.upper_bound
                    > min(earliest_cutoff, query.knowledge_cutoff)
                ):
                    raise ValueError("common clock has foreign or late coverage")
                result: object = coverage_verifiers[query.venue.value](
                    coverage, context
                )
                if result is not None:
                    if iscoroutine(result):
                        result.close()
                    raise ValueError(
                        "common clock source verifier must synchronously return None"
                    )
                records[coverage.record_hash] = coverage
    require_common_interval_inventory(clock, tuple(records.values()))
    return sessions


class RealizedSessionLocalDateError(DriftError, ValueError):
    """Raised when a realized session's UTC stamps are not on its local date.

    Issue 140. A realized record's ``actual_open`` and ``actual_close`` are
    UTC instants, and M1d binds neither to the record's own
    ``session_key.local_date``. A record stamped days after its date would
    re-derive, faithfully, into the issue 95 lagged clock, so the realized
    builder, and with it ``verify_session_clock`` and the bundle boundary,
    refuses such a record.
    """


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
    """Build a realized-authority clock from authentic selected realized sessions.

    Each admitted record's stamps must fall on its own local date in the
    venue's authorized local time (issue 140), so a record misdated at its
    source cannot re-derive into a lagged clock.
    """
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
        _require_stamps_on_local_date(
            record, record.actual_open, record.actual_close, query, context
        )
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


def _require_stamps_on_local_date(
    record: RealizedSessionVersionV1,
    actual_open: datetime,
    actual_close: datetime,
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> None:
    """Refuse a realized record whose UTC stamps are off its local date.

    Issue 140. The venue's local time comes from the authority M1d holds for
    it: the authorized generated schedule row of the same session key, from
    the ``generate_schedule`` pipeline the scheduled clock uses. That row
    converts its local open and close labels to UTC at row-bound historical
    offsets, each proven by its retained authority artifact, available by the
    query's cutoff, and agreeing with the exact TZif reconstruction. A label
    less its authorized UTC instant is therefore that boundary's authorized
    UTC offset on that date. Each stamp is read at its own boundary's offset,
    the open at the open's and the close at the close's, and must fall on the
    record's local date. A row that authorizes no open and close (closed,
    unknown, indeterminate, or absent) carries no UTC boundaries, since an
    output that is not authorized never does (``SessionOutputV1``), so it
    cannot place the stamps, and the record is refused rather than read
    against the UTC calendar.
    """
    key = record.session_key
    where = f"realized session {key.mic} {key.local_date.isoformat()}"
    refusal = realized_stamps_local_date_refusal(
        key, (("open", actual_open), ("close", actual_close)), query, context
    )
    if refusal is not None:
        raise RealizedSessionLocalDateError(f"{where} {refusal} (issue 140)")


def realized_stamps_local_date_refusal(
    session_key: SessionKeyV1,
    stamps: tuple[tuple[Literal["open", "close"], datetime], ...],
    query: ObservationQueryV1,
    context: M1dResolutionContext,
) -> str | None:
    """Say why realized stamps are not on their session's local date, if so.

    The one issue 140 reading, shared by the realized clock builder and the
    issue 147 anchor guard of the bundle boundaries, each of which refuses on
    a returned reason in its own words. Each stamp is named by its boundary
    and read at that boundary's authorized offset on the authorized generated
    schedule row of ``query``'s session (see ``_require_stamps_on_local_date``
    for where that offset comes from), and must land on
    ``session_key.local_date``. Stamps are read in the order given, and the
    first off its date is the one named. A session without an authorized
    generated open and close cannot place any stamp. Returns ``None`` when
    every stamp is on the date.
    """
    artifact = generate_schedule(query, context, _load_clock_policy(context))
    rows = _matching_generated_rows(artifact, query)
    output = rows[0].output if len(rows) == 1 else None
    if (
        output is None
        or output.local_open is None
        or output.local_close is None
        or output.utc_open is None
        or output.utc_close is None
    ):
        state = "absent" if output is None else output.state
        return (
            "cannot be placed in venue local time: its session key has "
            "no authorized generated open and close (schedule artifact "
            f"{artifact.classification}, state {state})"
        )
    authorized = {
        "open": (output.local_open, output.utc_open),
        "close": (output.local_close, output.utc_close),
    }
    for boundary, stamp in stamps:
        label, instant = authorized[boundary]
        offset = datetime.fromisoformat(label) - instant.replace(tzinfo=None)
        local_date = (stamp + offset).date()
        if local_date != session_key.local_date:
            return (
                f"actual {boundary} {stamp.isoformat()} falls on venue "
                f"local date {local_date.isoformat()}, not its session date"
            )
    return None


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

    Dates are read through the base ``date`` methods, never the value's own.
    The engine rebuilds its inputs through canonical JSON (issue 123), so no
    ``date`` subclass reaches this refusal from an engine; reading through the
    base type stays as defense in depth for any other caller, since a
    subclass's equality, hash and string form could otherwise hide a second
    session on one date.
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
