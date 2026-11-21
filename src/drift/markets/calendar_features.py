"""Compute point-in-time calendar features from schedule rows (issue 662).

``compute_calendar_features`` takes the ``ScheduledSessionVersionV1`` rows of
one source and venue, one ``CalendarFeatureRequestV1`` per session, the
availability channel and policy that say when a row became known, and an
optional registry of known-in-advance event records. It returns one
self-hashed ``CalendarFeatureSetV1``.

How knowledge is read:

* A schedule row is known for a session when M1b assertion selection on the
  requested channel selects it strictly before the session's ``as_of``. The
  selection is evaluated one microsecond before ``as_of``, the resolution of a
  Python datetime, so a row available exactly at ``as_of`` is not known.
  Revision chains, corrections and withdrawals follow M1b unchanged.
* M1b selects the latest version definitely available and passes over a
  later version whose availability it cannot settle. Here such a later
  version makes the date unknown instead: an INDETERMINATE window on the
  channel, no evidence on the channel, or a later version that is available
  but not causally selectable all mean the earlier version may already be
  superseded.
* A date's status is ``open`` when its known row is ``regular`` or
  ``early_close``, ``closed`` when it is ``closed``, and ``unknown`` otherwise:
  no row, a row not yet known, an unsettled later version, a withdrawn row,
  or a row whose own state is ``unknown``. An unknown date never counts as
  closed, so a weekend needs an explicit closed row like any other date.
* An event revision is known when its ``published_at`` is strictly before
  ``as_of``. The latest known revision of each event decides it.

What it does not do:

* It does not authenticate rows. A closed row materialized from closed-world
  coverage is indistinguishable here from one a provider printed; run
  ``verify_closed_world_session_coverage`` on the context the rows came from.
* It does not know when a session opens. ``as_of`` is the caller's cutoff,
  and nothing here checks it against the session's own boundaries.
* It opens no connection, reads no file and sources no data.
"""

from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from re import fullmatch
from types import MappingProxyType

from drift.datasets.assertions import select_assertion_version, validate_assertion_chain
from drift.domain.assertions import AssertionVersionProjectionV1
from drift.domain.calendar_features import (
    CALENDAR_EVENT_KIND_PATTERN,
    US_REGULAR_WAY_SETTLEMENT_TABLE_V1,
    CalendarCountV1,
    CalendarDateV1,
    CalendarEventFeaturesV1,
    CalendarEventRecordV1,
    CalendarFeatureInputError,
    CalendarFeatureRequestV1,
    CalendarFeatureSetV1,
    CalendarIndeterminateReason,
    CalendarSessionFeaturesV1,
    SessionKnowledgeStatus,
    calendar_feature_algorithm_hash,
    monthly_expiration_flag,
    seal_calendar_feature_set,
    seal_calendar_session_features,
    settlement_cycle_for,
    third_friday_of_month,
)
from drift.domain.common import FrozenModel
from drift.domain.sessions import ScheduledSessionVersionV1
from drift.domain.temporal import (
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    CutoffEligibility,
    evaluate_availability,
)
from drift.serialization.canonical import content_hash

_ONE_MICROSECOND = timedelta(microseconds=1)
_OPEN_STATES = frozenset({"regular", "early_close"})
#: The earliest cutoff accepted, so that one microsecond earlier still exists.
_EARLIEST_CUTOFF = datetime(1, 1, 2, tzinfo=UTC)


def _refuse(code: str, detail: str) -> CalendarFeatureInputError:
    return CalendarFeatureInputError(code, detail)


@dataclass(frozen=True)
class _ScheduleIndex:
    """The validated rows, one revision chain per session date."""

    source_id: str
    mic: str
    chains: Mapping[date, tuple[AssertionVersionProjectionV1, ...]]
    by_hash: Mapping[str, ScheduledSessionVersionV1]
    input_hash: str


def _require_plain_temporal(value: object) -> None:
    """Refuse a date or datetime subclass anywhere inside a model dump.

    A subclass can redefine comparison, so a value that claims to be
    available in 2030 could compare as available now.
    """
    if isinstance(value, date) and type(value) not in (date, datetime):
        raise ValueError("a date or datetime subclass is not a plain value")
    if isinstance(value, Mapping):
        for item in value.values():
            _require_plain_temporal(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _require_plain_temporal(item)


def _revalidated[M: FrozenModel](
    model: type[M], value: object, code: str, what: str
) -> M:
    """Validate ``value`` again through its own contract, or refuse it.

    Every nested date and datetime must be a plain value. The model is then
    rebuilt from its own JSON, so no other subclassed value survives either.
    """
    if not isinstance(value, model) or type(value) is not model:
        raise _refuse(code, f"every {what} must be a {model.__name__}")
    try:
        _require_plain_temporal(value.model_dump(mode="python", warnings=False))
        return model.model_validate_json(value.model_dump_json(warnings=False))
    except (AttributeError, TypeError, ValueError) as error:
        raise _refuse(
            code, f"a {what} does not validate through its own contract"
        ) from error


def _revalidated_row(row: object) -> ScheduledSessionVersionV1:
    return _revalidated(
        ScheduledSessionVersionV1, row, "calendar_schedule_row_invalid", "row"
    )


def _validated_schedule(schedule: Iterable[object]) -> _ScheduleIndex:
    rows = tuple(_revalidated_row(row) for row in schedule)
    if not rows:
        raise _refuse("calendar_schedule_empty", "no schedule row was supplied")
    sources = {row.source_id for row in rows}
    if len(sources) != 1:
        raise _refuse(
            "calendar_schedule_mixed_source",
            f"rows come from {len(sources)} sources; select one source first",
        )
    mics = {row.session_key.mic for row in rows}
    if len(mics) != 1:
        raise _refuse(
            "calendar_schedule_mixed_venue",
            f"rows describe {len(mics)} venues; one venue per computation",
        )
    hashes = tuple(content_hash(row) for row in rows)
    if len(set(hashes)) != len(hashes):
        raise _refuse("calendar_schedule_duplicate_row", "a row is supplied twice")
    versions = tuple(row.revision.record_version_id for row in rows)
    if len(set(versions)) != len(versions):
        raise _refuse(
            "calendar_schedule_duplicate_version",
            "two rows share one record version id",
        )
    by_logical: dict[object, list[tuple[ScheduledSessionVersionV1, str]]] = {}
    for row, digest in zip(rows, hashes, strict=True):
        by_logical.setdefault(row.revision.logical_record_id, []).append((row, digest))
    chains: dict[date, tuple[AssertionVersionProjectionV1, ...]] = {}
    for members in by_logical.values():
        days = {row.session_key.local_date for row, _digest in members}
        if len(days) != 1:
            raise _refuse(
                "calendar_schedule_chain_moves_date",
                "the versions of one logical row name different session dates",
            )
        (day,) = days
        if day in chains:
            raise _refuse(
                "calendar_schedule_conflicting_rows",
                f"two logical rows describe {day.isoformat()}; revise one chain "
                "instead",
            )
        projections = tuple(
            AssertionVersionProjectionV1(revision=row.revision, record_hash=digest)
            for row, digest in members
        )
        findings = validate_assertion_chain(projections)
        if findings:
            codes = ", ".join(item.code for item in findings)
            raise _refuse(
                "calendar_schedule_chain_invalid",
                f"the row chain for {day.isoformat()} fails M1b checks: {codes}",
            )
        chains[day] = tuple(
            sorted(projections, key=lambda item: item.revision.source_sequence)
        )
    (source_id,) = sources
    (mic,) = mics
    return _ScheduleIndex(
        source_id=source_id,
        mic=mic,
        chains=MappingProxyType(chains),
        by_hash=MappingProxyType(dict(zip(hashes, rows, strict=True))),
        input_hash=content_hash({"schedule_record_hashes": tuple(sorted(hashes))}),
    )


def _validated_requests(
    requests: Iterable[object], mic: str
) -> tuple[CalendarFeatureRequestV1, ...]:
    validated: list[CalendarFeatureRequestV1] = []
    for request in requests:
        again = _revalidated(
            CalendarFeatureRequestV1, request, "calendar_request_invalid", "request"
        )
        if again.as_of < _EARLIEST_CUTOFF:
            raise _refuse(
                "calendar_request_invalid",
                f"a cutoff before {_EARLIEST_CUTOFF.isoformat()} is out of range",
            )
        if again.session_key.mic != mic:
            raise _refuse(
                "calendar_request_venue_mismatch",
                f"a request names {again.session_key.mic}, the schedule {mic}",
            )
        validated.append(again)
    if not validated:
        raise _refuse("calendar_requests_empty", "no session was requested")
    for earlier, later in zip(validated, validated[1:], strict=False):
        if later.session_key.local_date <= earlier.session_key.local_date:
            raise _refuse(
                "calendar_request_order_invalid",
                "requests must be in strictly increasing session-date order",
            )
        if later.as_of < earlier.as_of:
            raise _refuse(
                "calendar_request_cutoff_not_monotone",
                f"the cutoff for {later.session_key.local_date.isoformat()} "
                "precedes the cutoff of an earlier session",
            )
    return tuple(validated)


def _validated_kinds(event_kinds: Iterable[object]) -> tuple[str, ...]:
    kinds = tuple(event_kinds)
    if any(
        type(kind) is not str or fullmatch(CALENDAR_EVENT_KIND_PATTERN, kind) is None
        for kind in kinds
    ):
        raise _refuse(
            "calendar_event_kinds_invalid",
            "an event kind must be a lowercase snake-case string",
        )
    if len(set(kinds)) != len(kinds):
        raise _refuse("calendar_event_kinds_invalid", "an event kind is repeated")
    return tuple(sorted(str(kind) for kind in kinds))


def _validated_events(
    events: Iterable[object], kinds: tuple[str, ...]
) -> tuple[tuple[CalendarEventRecordV1, ...], ...]:
    """Every event's revisions, ordered, after the chain checks."""
    by_event: dict[str, list[CalendarEventRecordV1]] = {}
    seen: set[tuple[str, int]] = set()
    for record in events:
        again = _revalidated(
            CalendarEventRecordV1, record, "calendar_event_invalid", "event record"
        )
        if again.event_kind not in kinds:
            raise _refuse(
                "calendar_event_kind_undeclared",
                f"event kind {again.event_kind} is not among the declared kinds",
            )
        identity = (again.event_id, again.revision)
        if identity in seen:
            raise _refuse(
                "calendar_event_duplicate",
                f"revision {again.revision} of event {again.event_id} repeats",
            )
        seen.add(identity)
        by_event.setdefault(again.event_id, []).append(again)
    chains: list[tuple[CalendarEventRecordV1, ...]] = []
    for event_id in sorted(by_event):
        chain = tuple(sorted(by_event[event_id], key=lambda item: item.revision))
        if tuple(item.revision for item in chain) != tuple(range(len(chain))):
            raise _refuse(
                "calendar_event_chain_invalid",
                f"the revisions of event {event_id} are not 0 to n without gaps",
            )
        if len({item.event_kind for item in chain}) != 1:
            raise _refuse(
                "calendar_event_chain_invalid",
                f"the revisions of event {event_id} change its kind",
            )
        for earlier, later in zip(chain, chain[1:], strict=False):
            if later.published_at <= earlier.published_at:
                raise _refuse(
                    "calendar_event_chain_invalid",
                    f"revision {later.revision} of event {event_id} is not "
                    "published strictly after the revision it replaces",
                )
        chains.append(chain)
    return tuple(chains)


def _validated_retained(
    retained_evidence: Mapping[str, AvailabilityEvidenceV1] | None,
) -> Mapping[str, AvailabilityEvidenceV1]:
    """Retained raw evidence, each entry keyed by its own content hash."""
    retained: dict[str, AvailabilityEvidenceV1] = {}
    for key, evidence in dict(retained_evidence or {}).items():
        again = _revalidated(
            AvailabilityEvidenceV1,
            evidence,
            "calendar_retained_evidence_invalid",
            "retained evidence",
        )
        if key != content_hash(again):
            raise _refuse(
                "calendar_retained_evidence_invalid",
                "retained evidence must be keyed by its own content hash",
            )
        retained[key] = again
    return MappingProxyType(retained)


@dataclass
class _KnownSchedule:
    """The status of each date as known strictly before one cutoff."""

    index: _ScheduleIndex
    channel: AvailabilityChannelV1
    policy: AvailabilityPolicyV1
    retained: Mapping[str, AvailabilityEvidenceV1]
    as_of: datetime
    consulted: set[str] = field(default_factory=set)
    _cache: dict[date, SessionKnowledgeStatus] = field(default_factory=dict)

    def status(self, day: date) -> SessionKnowledgeStatus:
        cached = self._cache.get(day)
        if cached is not None:
            return cached
        resolved = self._resolve(day)
        self._cache[day] = resolved
        return resolved

    def _decision(self, item: AssertionVersionProjectionV1) -> CutoffEligibility:
        """One version's availability strictly before the cutoff.

        Only a version definitely not available by the cutoff is INELIGIBLE.
        No evidence on the requested channel, or a rule-derived instant the
        policy does not permit, cannot be settled, so it is INDETERMINATE.
        """
        evidence = next(
            (
                claim
                for claim in item.revision.availability
                if claim.channel == self.channel
            ),
            None,
        )
        if evidence is None:
            return CutoffEligibility.INDETERMINATE
        result = evaluate_availability(
            evidence,
            self.channel,
            self.policy,
            self.as_of - _ONE_MICROSECOND,
            self.retained,
        )
        if (
            result.classification is CutoffEligibility.INELIGIBLE
            and result.reason != "not_available_by_cutoff"
        ):
            return CutoffEligibility.INDETERMINATE
        return result.classification

    def _resolve(self, day: date) -> SessionKnowledgeStatus:
        chain = self.index.chains.get(day)
        if chain is None:
            return "unknown"
        decisions = {item.record_hash: self._decision(item) for item in chain}
        self.consulted.update(
            digest
            for digest, decision in decisions.items()
            if decision is not CutoffEligibility.INELIGIBLE
        )
        selection = select_assertion_version(
            chain,
            self.channel,
            self.policy,
            self.as_of - _ONE_MICROSECOND,
            self.retained,
        )
        if (
            selection.classification is not CutoffEligibility.ELIGIBLE
            or selection.selected_record_hash is None
        ):
            return "unknown"
        row = self.index.by_hash[selection.selected_record_hash]
        if any(
            item.revision.source_sequence > row.revision.source_sequence
            and decisions[item.record_hash] is not CutoffEligibility.INELIGIBLE
            for item in chain
        ):
            return "unknown"
        if row.state in _OPEN_STATES:
            return "open"
        if row.state == "closed":
            return "closed"
        return "unknown"


@dataclass(frozen=True)
class _Tally:
    """Open dates counted over a range, or the first date that blocks it."""

    count: int | None
    blocking_date: date | None


def _tally_open(known: _KnownSchedule, first: int, last: int) -> _Tally:
    """Count open dates over ordinals ``first`` through ``last``, all known.

    Ordinals keep the range arithmetic clear of the ends of ``date``.
    """
    count = 0
    for ordinal in range(first, last + 1):
        day = date.fromordinal(ordinal)
        status = known.status(day)
        if status == "unknown":
            return _Tally(count=None, blocking_date=day)
        if status == "open":
            count += 1
    return _Tally(count=count, blocking_date=None)


def _count(tally: _Tally, offset: int) -> CalendarCountV1:
    if tally.count is None:
        return _indeterminate_count("schedule_status_unknown", tally.blocking_date)
    return CalendarCountV1(
        status="known", value=tally.count + offset, reason=None, blocking_date=None
    )


def _indeterminate_count(
    reason: CalendarIndeterminateReason, blocking_date: date | None = None
) -> CalendarCountV1:
    return CalendarCountV1(
        status="indeterminate", value=None, reason=reason, blocking_date=blocking_date
    )


def _indeterminate_date(
    reason: CalendarIndeterminateReason, blocking_date: date | None = None
) -> CalendarDateV1:
    return CalendarDateV1(
        status="indeterminate", value=None, reason=reason, blocking_date=blocking_date
    )


def _known_date(value: date) -> CalendarDateV1:
    return CalendarDateV1(status="known", value=value, reason=None, blocking_date=None)


def _expiration_session(known: _KnownSchedule, third_friday: date) -> CalendarDateV1:
    """The third Friday if open, else the latest earlier open date in its month.

    Every date walked over must be known closed; the first unknown one makes
    the answer INDETERMINATE. A month whose every date up to its third Friday
    is known closed has no expiration session under the rule; whatever the
    exchanges would do then is not a calendar fact, so it is INDETERMINATE.
    """
    for day_of_month in range(third_friday.day, 0, -1):
        day = third_friday.replace(day=day_of_month)
        status = known.status(day)
        if status == "open":
            return _known_date(day)
        if status == "unknown":
            return _indeterminate_date("schedule_status_unknown", day)
    return _indeterminate_date("expiration_outside_month")


def _visible_events(
    chains: tuple[tuple[CalendarEventRecordV1, ...], ...], as_of: datetime
) -> tuple[CalendarEventRecordV1, ...]:
    """The latest revision of each event published strictly before ``as_of``."""
    visible: list[CalendarEventRecordV1] = []
    for chain in chains:
        published = tuple(item for item in chain if item.published_at < as_of)
        if published:
            visible.append(published[-1])
    return tuple(visible)


def _event_features(
    kind: str,
    visible: tuple[CalendarEventRecordV1, ...],
    known: _KnownSchedule,
    day: date,
    session_open: bool,
) -> CalendarEventFeaturesV1:
    dates = sorted(
        {
            item.event_date
            for item in visible
            if item.event_kind == kind and item.status == "scheduled"
        }
    )
    earlier = [value for value in dates if value < day]
    later = [value for value in dates if value > day]
    previous = (
        _known_date(earlier[-1]) if earlier else _indeterminate_date("no_visible_event")
    )
    following = (
        _known_date(later[0]) if later else _indeterminate_date("no_visible_event")
    )
    if not session_open:
        until = _indeterminate_count("session_not_known_open")
    elif following.value is None:
        until = _indeterminate_count("no_visible_event")
    else:
        until = _count(
            _tally_open(known, day.toordinal() + 1, following.value.toordinal()), 0
        )
    return CalendarEventFeaturesV1(
        event_kind=kind,
        on_session=day in dates,
        previous_event_date=previous,
        next_event_date=following,
        sessions_until_next_event=until,
    )


def _session_features(
    request: CalendarFeatureRequestV1,
    index: _ScheduleIndex,
    channel: AvailabilityChannelV1,
    policy: AvailabilityPolicyV1,
    retained: Mapping[str, AvailabilityEvidenceV1],
    kinds: tuple[str, ...],
    event_chains: tuple[tuple[CalendarEventRecordV1, ...], ...],
) -> CalendarSessionFeaturesV1:
    day = request.session_key.local_date
    known = _KnownSchedule(
        index=index,
        channel=channel,
        policy=policy,
        retained=retained,
        as_of=request.as_of,
    )
    session_status = known.status(day)
    session_open = session_status == "open"
    ordinal = day.toordinal()
    first = ordinal - day.day + 1
    last = first + monthrange(day.year, day.month)[1] - 1
    if session_open:
        from_start = _count(_tally_open(known, first, ordinal - 1), 1)
        after = _tally_open(known, ordinal + 1, last)
        from_end = _count(after, 1)
        remaining = _count(after, 0)
    else:
        from_start = _indeterminate_count("session_not_known_open")
        from_end = _indeterminate_count("session_not_known_open")
        remaining = _indeterminate_count("session_not_known_open")
    third_friday = third_friday_of_month(day.year, day.month)
    expiration = _expiration_session(known, third_friday)
    visible = _visible_events(event_chains, request.as_of)
    events = tuple(
        _event_features(kind, visible, known, day, session_open) for kind in kinds
    )
    return seal_calendar_session_features(
        {
            "algorithm_hash": calendar_feature_algorithm_hash(),
            "settlement_table_hash": US_REGULAR_WAY_SETTLEMENT_TABLE_V1.table_hash,
            "source_id": index.source_id,
            "knowledge_channel": channel,
            "availability_policy_hash": content_hash(policy),
            "session_key": request.session_key,
            "as_of": request.as_of,
            "session_status": session_status,
            "month_ordinal_from_start": from_start,
            "month_ordinal_from_end": from_end,
            "sessions_remaining_in_month": remaining,
            "third_friday": third_friday,
            "is_third_friday": day == third_friday,
            "monthly_expiration_session": expiration,
            "is_monthly_expiration_session": monthly_expiration_flag(
                session_open, day, expiration
            ),
            "settlement_cycle": settlement_cycle_for(
                US_REGULAR_WAY_SETTLEMENT_TABLE_V1, index.mic, day, request.as_of
            ),
            "events": events,
            "schedule_record_hashes": tuple(sorted(known.consulted)),
            "event_record_hashes": tuple(sorted(item.record_hash for item in visible)),
        }
    )


def compute_calendar_features(
    schedule: Sequence[ScheduledSessionVersionV1],
    requests: Sequence[CalendarFeatureRequestV1],
    *,
    channel: AvailabilityChannelV1,
    availability_policy: AvailabilityPolicyV1,
    retained_evidence: Mapping[str, AvailabilityEvidenceV1] | None = None,
    events: Sequence[CalendarEventRecordV1] = (),
    event_kinds: Sequence[str] = (),
) -> CalendarFeatureSetV1:
    """Compute every requested session's calendar features as of its cutoff.

    ``schedule`` is the rows of one source and one venue, with every revision
    supplied. One logical row per session date; a correction or a late
    closure is a later version of that row. ``requests`` are in strictly
    increasing date order with non-decreasing cutoffs. ``channel`` and
    ``availability_policy`` decide when a row became known, as in M1b, and
    ``retained_evidence`` holds the raw evidence any rule-derived
    availability rests on. ``events`` are optional records of the declared
    ``event_kinds``.

    Any input the contracts refuse raises ``CalendarFeatureInputError`` with
    its code, whether or not it is known before a cutoff: nothing is
    computed from inconsistent input. Knowledge that is consistent but not
    established strictly before a session's cutoff makes the dependent
    features INDETERMINATE instead.
    """
    index = _validated_schedule(schedule)
    validated_requests = _validated_requests(requests, index.mic)
    kinds = _validated_kinds(event_kinds)
    event_chains = _validated_events(events, kinds)
    knowledge_channel = _revalidated(
        AvailabilityChannelV1,
        channel,
        "calendar_knowledge_policy_invalid",
        "knowledge channel",
    )
    policy = _revalidated(
        AvailabilityPolicyV1,
        availability_policy,
        "calendar_knowledge_policy_invalid",
        "availability policy",
    )
    retained = _validated_retained(retained_evidence)
    sessions = tuple(
        _session_features(
            request, index, knowledge_channel, policy, retained, kinds, event_chains
        )
        for request in validated_requests
    )
    event_hashes = tuple(
        sorted(record.record_hash for chain in event_chains for record in chain)
    )
    return seal_calendar_feature_set(
        {
            "algorithm_hash": calendar_feature_algorithm_hash(),
            "settlement_table_hash": US_REGULAR_WAY_SETTLEMENT_TABLE_V1.table_hash,
            "source_id": index.source_id,
            "mic": index.mic,
            "knowledge_channel": knowledge_channel,
            "availability_policy_hash": content_hash(policy),
            "schedule_input_hash": index.input_hash,
            "event_input_hash": content_hash({"event_record_hashes": event_hashes}),
            "event_kinds": kinds,
            "sessions": sessions,
        }
    )
