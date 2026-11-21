"""Typed point-in-time calendar features per session (issue 662).

These models fix what a calendar feature request, a known-in-advance event
record, a settlement-cycle table and a per-session feature record are, and
keep each one self-consistent. The computation lives in
``drift.markets.calendar_features``.

The point-in-time rule: the features for one session are computed as of an
explicit caller-supplied cutoff ``as_of``, and depend only on schedule rows
and event records known strictly before that cutoff. A feature that needs
knowledge the inputs do not establish strictly before the cutoff is
INDETERMINATE with a reason code. It is never a guessed default.

Limitations, stated plainly:

* Exploratory lane only (ADR 0012). Every record carries
  ``evidence_lane="exploratory"`` and nothing here is promotion-grade
  evidence, a source qualification or a permission.
* The hashes are plain content hashes, not signatures. They show that a
  record is internally consistent and unchanged since it was sealed, not who
  sealed it or that its inputs were authentic.
* Event records are caller-supplied. ``published_at`` is whatever the caller
  states, and must be a conservative upper bound of first publication. This
  module cannot check it.
* The settlement table describes the US regular-way standard for most
  broker-dealer trades. It is a closed, versioned table with its sources in
  ``docs/architecture/calendar-features.md``, and it says nothing about
  settlement holidays or about any security a rule exempts.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.sessions import SessionKeyV1
from drift.domain.temporal import AvailabilityChannelV1
from drift.errors import CanonicalSerializationError, DriftError
from drift.serialization.canonical import content_hash

_PLACEHOLDER_HASH = "0" * 64

_CALENDAR_FEATURE_ALGORITHM_V1 = {
    "schema_version": "1",
    "algorithm": "point_in_time_calendar_features_v1",
    "knowledge": "m1b_assertion_selection_available_strictly_before_cutoff",
    "date_status": "selected_row_open_or_closed_otherwise_unknown",
    "unresolved_later_version": "unknown_never_the_earlier_version",
    "missing_row": "unknown_never_closed",
    "schedule_record_hashes": "every_version_not_definitely_unavailable_before",
    "month_ordinal_from_start": "one_plus_open_dates_from_month_start_all_known",
    "month_ordinal_from_end": "one_plus_open_dates_to_month_end_all_known",
    "sessions_remaining_in_month": "open_dates_strictly_after_in_month",
    "third_friday": "third_friday_of_the_calendar_month",
    "monthly_expiration_session": "third_friday_or_latest_earlier_open_in_month",
    "settlement_cycle": "containing_known_row_or_latest_known_row_end_not_public",
    "events": "latest_revision_published_strictly_before_cutoff",
    "session_relative_features": "indeterminate_unless_session_known_open",
}

CALENDAR_FEATURE_INPUT_CODES: tuple[str, ...] = (
    "calendar_event_chain_invalid",
    "calendar_event_duplicate",
    "calendar_event_invalid",
    "calendar_event_kind_undeclared",
    "calendar_event_kinds_invalid",
    "calendar_knowledge_policy_invalid",
    "calendar_request_cutoff_not_monotone",
    "calendar_request_invalid",
    "calendar_request_order_invalid",
    "calendar_request_venue_mismatch",
    "calendar_requests_empty",
    "calendar_retained_evidence_invalid",
    "calendar_schedule_chain_invalid",
    "calendar_schedule_chain_moves_date",
    "calendar_schedule_conflicting_rows",
    "calendar_schedule_duplicate_row",
    "calendar_schedule_duplicate_version",
    "calendar_schedule_empty",
    "calendar_schedule_mixed_source",
    "calendar_schedule_mixed_venue",
    "calendar_schedule_row_invalid",
)
"""Every refusal code the computation can raise, sorted."""

type CalendarFeatureStatus = Literal["known", "indeterminate"]
type SessionKnowledgeStatus = Literal["open", "closed", "unknown"]
type CalendarIndeterminateReason = Literal[
    "expiration_outside_month",
    "no_visible_event",
    "schedule_status_unknown",
    "session_not_known_open",
    "settlement_after_verified_range",
    "settlement_before_table",
    "settlement_row_not_known_at_cutoff",
    "settlement_venue_outside_table",
]
type SettlementBusinessDays = Literal[1, 2, 3, 4, 5]

_SETTLEMENT_REASONS = frozenset(
    {
        "settlement_after_verified_range",
        "settlement_before_table",
        "settlement_row_not_known_at_cutoff",
        "settlement_venue_outside_table",
    }
)

CALENDAR_EVENT_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
"""A lowercase snake-case event kind, such as ``fomc_scheduled_meeting``."""

type CalendarEventKind = Annotated[
    str, StringConstraints(pattern=CALENDAR_EVENT_KIND_PATTERN)
]


class CalendarFeatureInputError(DriftError, ValueError):
    """An input the computation refuses outright, named by its code.

    A refusal means nothing was computed. It is distinct from an
    INDETERMINATE feature, which is a computed answer that the inputs do not
    establish strictly before the cutoff.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def calendar_feature_algorithm_hash() -> SHA256Hash:
    """Return the static semantic identity of the V1 feature algorithm."""
    return content_hash(_CALENDAR_FEATURE_ALGORITHM_V1)


def third_friday_of_month(year: int, month: int) -> date:
    """Return the third Friday of one calendar month."""
    first = date(year, month, 1)
    first_friday = 1 + (4 - first.weekday()) % 7
    return date(year, month, first_friday + 14)


def _require_plain_date(value: date | None) -> date | None:
    """Refuse a date subclass, whose ordering a caller could redefine."""
    if value is not None and type(value) is not date:
        raise ValueError("calendar dates must be plain datetime.date values")
    return value


def _require_feature_shape(
    status: CalendarFeatureStatus,
    has_value: bool,
    reason: CalendarIndeterminateReason | None,
    blocking_date: date | None,
) -> None:
    if status == "known":
        if not has_value or reason is not None or blocking_date is not None:
            raise ValueError(
                "calendar_feature_shape_invalid: a known feature carries a "
                "value and no reason"
            )
        return
    if has_value or reason is None:
        raise ValueError(
            "calendar_feature_shape_invalid: an indeterminate feature carries "
            "a reason and no value"
        )
    if reason in _SETTLEMENT_REASONS:
        raise ValueError(
            "calendar_feature_shape_invalid: a settlement reason belongs to "
            "the settlement feature only"
        )
    if (reason == "schedule_status_unknown") != (blocking_date is not None):
        raise ValueError(
            "calendar_feature_shape_invalid: a blocking date is given exactly "
            "when a schedule status is unknown"
        )


class CalendarCountV1(FrozenModel):
    """A count feature, or INDETERMINATE with the reason it cannot be known.

    ``blocking_date`` is the first date whose open or closed status was not
    known strictly before the cutoff, when that is the reason.
    """

    status: CalendarFeatureStatus
    value: Annotated[int, Field(ge=0)] | None
    reason: CalendarIndeterminateReason | None
    blocking_date: date | None

    _plain_dates = field_validator("blocking_date")(_require_plain_date)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        _require_feature_shape(
            self.status, self.value is not None, self.reason, self.blocking_date
        )
        return self


class CalendarDateV1(FrozenModel):
    """A date feature, or INDETERMINATE with the reason it cannot be known."""

    status: CalendarFeatureStatus
    value: date | None
    reason: CalendarIndeterminateReason | None
    blocking_date: date | None

    _plain_dates = field_validator("value", "blocking_date")(_require_plain_date)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        _require_feature_shape(
            self.status, self.value is not None, self.reason, self.blocking_date
        )
        return self


class CalendarFlagV1(FrozenModel):
    """A yes-or-no feature, or INDETERMINATE with the reason."""

    status: CalendarFeatureStatus
    value: bool | None
    reason: CalendarIndeterminateReason | None
    blocking_date: date | None

    _plain_dates = field_validator("blocking_date")(_require_plain_date)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        _require_feature_shape(
            self.status, self.value is not None, self.reason, self.blocking_date
        )
        return self


class SettlementCycleFeatureV1(FrozenModel):
    """The regular-way settlement cycle for the session's trade date.

    ``business_days_after_trade_date`` is the ``n`` of ``T+n``. ``row_id``
    names the table row it came from. The settlement date itself is not
    computed: settlement business days follow a calendar this module does not
    hold.
    """

    status: CalendarFeatureStatus
    business_days_after_trade_date: SettlementBusinessDays | None
    row_id: NonBlankStr | None
    reason: CalendarIndeterminateReason | None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        known = self.status == "known"
        carried = (
            self.business_days_after_trade_date is not None,
            self.row_id is not None,
        )
        if known != all(carried) or known == (self.reason is not None):
            raise ValueError(
                "calendar_feature_shape_invalid: a known settlement cycle "
                "carries its days and row and no reason"
            )
        if any(carried) and not known:
            raise ValueError(
                "calendar_feature_shape_invalid: an indeterminate settlement "
                "cycle carries no days and no row"
            )
        if self.reason is not None and self.reason not in _SETTLEMENT_REASONS:
            raise ValueError(
                "calendar_feature_shape_invalid: an indeterminate settlement "
                "cycle carries a settlement reason"
            )
        return self


class CalendarEventFeaturesV1(FrozenModel):
    """What the visible events of one declared kind say about one session.

    An event is visible when the latest revision of its record published
    strictly before the cutoff is ``scheduled``. ``on_session`` is ``False``
    when no visible event falls on the session date, which does not mean no
    event will happen there. ``sessions_until_next_event`` counts open dates
    after the session up to and including the next visible event date.
    """

    event_kind: CalendarEventKind
    on_session: bool
    previous_event_date: CalendarDateV1
    next_event_date: CalendarDateV1
    sessions_until_next_event: CalendarCountV1


class CalendarEventRecordV1(FrozenModel):
    """One caller-supplied revision of a known-in-advance event date.

    ``event_id`` is the logical event; ``revision`` numbers its versions from
    0. A later revision replaces an earlier one once it is visible, and
    ``status="cancelled"`` withdraws the event. ``published_at`` is the
    conservative instant by which this revision was public. ``event_date`` is
    the venue-local calendar date the event is assigned to, for example the
    date of a scheduled FOMC statement.
    """

    schema_version: Literal["1"] = "1"
    event_id: NonBlankStr
    revision: Annotated[int, Field(ge=0)]
    event_kind: CalendarEventKind
    status: Literal["scheduled", "cancelled"]
    event_date: date
    published_at: UTCDateTime
    source_sha256: SHA256Hash | None
    record_hash: SHA256Hash

    _plain_dates = field_validator("event_date")(_require_plain_date)

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.revision == 0 and self.status != "scheduled":
            raise ValueError(
                "calendar_event_invalid: revision 0 of an event must schedule it"
            )
        if self.record_hash != calendar_event_record_hash(self):
            raise ValueError(
                "calendar_event_invalid: the record hash does not cover the "
                "record's own fields"
            )
        return self


class CalendarFeatureRequestV1(FrozenModel):
    """One session to compute features for, and the cutoff to compute them at.

    ``as_of`` is the caller's knowledge cutoff for this session, normally the
    instant the decision that uses the features is made. The features depend
    only on what is known strictly before it.
    """

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    as_of: UTCDateTime


class SettlementCycleRowV1(FrozenModel):
    """One row of the settlement-cycle table, keyed by trade date.

    ``effective_from`` is the first trade date the row governs and
    ``effective_until`` the first it does not, or ``None`` for the open last
    row, which the table's ``verified_through`` bounds.

    ``announced_on`` is a conservative date by which the row's start and
    cycle were public. ``end_announced_on`` is a conservative date by which
    its ``effective_until`` was public; it is ``None`` exactly for the open
    last row. Each date counts as known only from 00:00 UTC two days later.
    """

    schema_version: Literal["1"] = "1"
    row_id: NonBlankStr
    business_days_after_trade_date: SettlementBusinessDays
    effective_from: date
    effective_until: date | None
    announced_on: date
    end_announced_on: date | None
    authority: NonBlankStr

    _plain_dates = field_validator(
        "effective_from", "effective_until", "announced_on", "end_announced_on"
    )(_require_plain_date)

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        if (
            self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("settlement_table_invalid: a row must be nonempty")
        if self.announced_on > self.effective_from:
            raise ValueError(
                "settlement_table_invalid: a row cannot be announced after it "
                "takes effect"
            )
        if (self.end_announced_on is None) != (self.effective_until is None):
            raise ValueError(
                "settlement_table_invalid: a row's end is announced exactly when "
                "it has an end"
            )
        if (
            self.end_announced_on is not None
            and self.effective_until is not None
            and self.end_announced_on > self.effective_until
        ):
            raise ValueError(
                "settlement_table_invalid: a row's end cannot be announced after "
                "it takes effect"
            )
        return self


def _known_from(announced_on: date) -> datetime:
    """00:00 UTC two calendar days after ``announced_on``.

    That instant is later than the end of ``announced_on`` in every US time
    zone, so nothing is treated as known before its announcement date ended.
    """
    return datetime.combine(announced_on + timedelta(days=2), time(), UTC)


def settlement_row_known_from(row: SettlementCycleRowV1) -> datetime:
    """The instant from which a row's start and cycle count as known."""
    return _known_from(row.announced_on)


def settlement_row_end_known_from(row: SettlementCycleRowV1) -> datetime | None:
    """The instant from which a row's end counts as known, if it has one."""
    if row.end_announced_on is None:
        return None
    return _known_from(row.end_announced_on)


def settlement_row_end_possibly_public_from(
    row: SettlementCycleRowV1,
) -> datetime | None:
    """The earliest instant a row's end could have been public, if it has one.

    00:00 UTC on the day before ``end_announced_on`` precedes the start of
    that date in every time zone, so no announcement made on that date can be
    earlier.
    """
    if row.end_announced_on is None:
        return None
    return datetime.combine(row.end_announced_on - timedelta(days=1), time(), UTC)


class SettlementCycleTableV1(FrozenModel):
    """A closed, versioned, contiguous table of settlement cycles.

    Rows are sorted and contiguous. Trade dates before the first row, after
    ``verified_through`` or at a venue outside ``venues`` have no answer.
    """

    schema_version: Literal["1"] = "1"
    table_id: NonBlankStr
    table_version: NonBlankStr
    venues: tuple[NonBlankStr, ...]
    verified_through: date
    rows: tuple[SettlementCycleRowV1, ...]
    table_hash: SHA256Hash

    _plain_dates = field_validator("verified_through")(_require_plain_date)

    @model_validator(mode="after")
    def validate_table(self) -> Self:
        if not self.venues or self.venues != tuple(sorted(set(self.venues))):
            raise ValueError(
                "settlement_table_invalid: venues must be nonempty, unique and sorted"
            )
        if not self.rows:
            raise ValueError("settlement_table_invalid: a table needs rows")
        if len({row.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("settlement_table_invalid: row ids must be unique")
        for earlier, later in pairwise(self.rows):
            if earlier.effective_until != later.effective_from:
                raise ValueError(
                    "settlement_table_invalid: rows must be sorted and contiguous"
                )
            if (
                earlier.end_announced_on is not None
                and earlier.end_announced_on > later.announced_on
            ):
                raise ValueError(
                    "settlement_table_invalid: a row's end is public no later "
                    "than the row that follows it"
                )
        if self.rows[-1].effective_until is not None:
            raise ValueError(
                "settlement_table_invalid: only the last row is open, and it must be"
            )
        if self.verified_through < self.rows[-1].effective_from:
            raise ValueError(
                "settlement_table_invalid: verified_through cannot precede the last row"
            )
        if self.table_hash != settlement_cycle_table_hash(self):
            raise ValueError(
                "settlement_table_invalid: the table hash does not cover the "
                "table's own fields"
            )
        return self


class CalendarSessionFeaturesV1(FrozenModel):
    """Every calendar feature of one session as of one cutoff, self-hashed.

    ``session_status`` is what the schedule known strictly before ``as_of``
    says about the session date itself. The session-relative features (the
    month ordinals, the sessions remaining, the expiration flag and each
    ``sessions_until_next_event``) are INDETERMINATE with
    ``session_not_known_open`` unless it is ``open``. The date-level features
    (third Friday, expiration session date, event dates, settlement) do not
    depend on the session being open.

    ``schedule_record_hashes`` names every version of every schedule row the
    computation examined that was not definitely unavailable before
    ``as_of``: versions known strictly before it, and versions whose
    availability on the channel cannot be settled at it (an INDETERMINATE
    window or no evidence on the channel), which make their date unknown.
    ``event_record_hashes`` names the latest revision of each event published
    strictly before ``as_of``.

    ``settlement_table_hash`` must be the one table the V1 algorithm reads,
    and ``settlement_cycle`` must be what that table answers for the session
    date as of ``as_of``.
    """

    schema_version: Literal["1"] = "1"
    evidence_lane: Literal["exploratory"] = "exploratory"
    algorithm_hash: SHA256Hash
    settlement_table_hash: SHA256Hash
    source_id: NonBlankStr
    knowledge_channel: AvailabilityChannelV1
    availability_policy_hash: SHA256Hash
    session_key: SessionKeyV1
    as_of: UTCDateTime
    session_status: SessionKnowledgeStatus
    month_ordinal_from_start: CalendarCountV1
    month_ordinal_from_end: CalendarCountV1
    sessions_remaining_in_month: CalendarCountV1
    third_friday: date
    is_third_friday: bool
    monthly_expiration_session: CalendarDateV1
    is_monthly_expiration_session: CalendarFlagV1
    settlement_cycle: SettlementCycleFeatureV1
    events: tuple[CalendarEventFeaturesV1, ...]
    schedule_record_hashes: tuple[SHA256Hash, ...]
    event_record_hashes: tuple[SHA256Hash, ...]
    features_hash: SHA256Hash

    _plain_dates = field_validator("third_friday")(_require_plain_date)

    @model_validator(mode="after")
    def validate_features(self) -> Self:
        if self.algorithm_hash != calendar_feature_algorithm_hash():
            raise ValueError(
                "calendar_features_invalid: the record names an algorithm other "
                "than point_in_time_calendar_features_v1"
            )
        day = self.session_key.local_date
        if self.third_friday != third_friday_of_month(day.year, day.month):
            raise ValueError(
                "calendar_features_invalid: third_friday is not the third "
                "Friday of the session month"
            )
        if self.is_third_friday != (day == self.third_friday):
            raise ValueError(
                "calendar_features_invalid: is_third_friday disagrees with the "
                "session date"
            )
        self._validate_session_relative()
        self._validate_month()
        self._validate_events()
        self._validate_settlement()
        for label, hashes in (
            ("schedule_record_hashes", self.schedule_record_hashes),
            ("event_record_hashes", self.event_record_hashes),
        ):
            if hashes != tuple(sorted(set(hashes))):
                raise ValueError(
                    f"calendar_features_invalid: {label} must be unique and sorted"
                )
        if self.features_hash != calendar_session_features_hash(self):
            raise ValueError(
                "calendar_features_invalid: the features hash does not cover "
                "the record's own fields"
            )
        return self

    def _session_relative(
        self,
    ) -> tuple[CalendarCountV1 | CalendarFlagV1, ...]:
        return (
            self.month_ordinal_from_start,
            self.month_ordinal_from_end,
            self.sessions_remaining_in_month,
            self.is_monthly_expiration_session,
            *(item.sessions_until_next_event for item in self.events),
        )

    def _validate_session_relative(self) -> None:
        not_open = tuple(
            item.reason == "session_not_known_open" for item in self._session_relative()
        )
        if self.session_status == "open" and any(not_open):
            raise ValueError(
                "calendar_features_invalid: an open session cannot report "
                "session_not_known_open"
            )
        if self.session_status != "open" and not all(not_open):
            raise ValueError(
                "calendar_features_invalid: a session not known open has no "
                "session-relative feature"
            )

    def _validate_month(self) -> None:
        start = self.month_ordinal_from_start
        end = self.month_ordinal_from_end
        remaining = self.sessions_remaining_in_month
        for item in (start, end):
            if item.value is not None and item.value < 1:
                raise ValueError(
                    "calendar_features_invalid: a month ordinal starts at 1"
                )
            if item.reason not in _MONTH_REASONS:
                raise ValueError(
                    "calendar_features_invalid: a month ordinal is INDETERMINATE "
                    "only for an unknown date or a session not known open"
                )
        if (end.value is None) != (remaining.value is None) or (
            end.value is not None and remaining.value != end.value - 1
        ):
            raise ValueError(
                "calendar_features_invalid: sessions_remaining_in_month is "
                "month_ordinal_from_end minus 1"
            )
        if end.status == "indeterminate" and (
            (end.reason, end.blocking_date)
            != (remaining.reason, remaining.blocking_date)
        ):
            raise ValueError(
                "calendar_features_invalid: sessions_remaining_in_month shares "
                "the reason of month_ordinal_from_end"
            )
        expiration = self.monthly_expiration_session
        if expiration.value is not None and not (
            (expiration.value.year, expiration.value.month)
            == (self.third_friday.year, self.third_friday.month)
            and expiration.value <= self.third_friday
        ):
            raise ValueError(
                "calendar_features_invalid: the expiration session lies in the "
                "third Friday's month, on or before it"
            )
        if expiration.reason not in _EXPIRATION_REASONS:
            raise ValueError(
                "calendar_features_invalid: the expiration session is "
                "INDETERMINATE only for an unknown date or a walk out of the month"
            )
        expected = monthly_expiration_flag(
            self.session_status == "open", self.session_key.local_date, expiration
        )
        if self.is_monthly_expiration_session != expected:
            raise ValueError(
                "calendar_features_invalid: is_monthly_expiration_session "
                "disagrees with monthly_expiration_session"
            )

    def _validate_events(self) -> None:
        kinds = tuple(item.event_kind for item in self.events)
        if kinds != tuple(sorted(set(kinds))):
            raise ValueError(
                "calendar_features_invalid: event features must be unique and "
                "sorted by kind"
            )
        day = self.session_key.local_date
        for item in self.events:
            previous = item.previous_event_date.value
            following = item.next_event_date.value
            if (previous is not None and previous >= day) or (
                following is not None and following <= day
            ):
                raise ValueError(
                    "calendar_features_invalid: previous and next event dates "
                    "lie strictly before and after the session"
                )
            for edge in (item.previous_event_date, item.next_event_date):
                if edge.reason not in (None, "no_visible_event"):
                    raise ValueError(
                        "calendar_features_invalid: an event date is INDETERMINATE "
                        "only when no event is visible"
                    )
            if self.session_status != "open":
                continue
            allowed = (
                {"no_visible_event"}
                if following is None
                else {None, "schedule_status_unknown"}
            )
            if item.sessions_until_next_event.reason not in allowed:
                raise ValueError(
                    "calendar_features_invalid: sessions_until_next_event "
                    "disagrees with next_event_date"
                )

    def _validate_settlement(self) -> None:
        table = US_REGULAR_WAY_SETTLEMENT_TABLE_V1
        if self.settlement_table_hash != table.table_hash:
            raise ValueError(
                "calendar_features_invalid: the record names a settlement table "
                "other than the one the V1 algorithm reads"
            )
        expected = settlement_cycle_for(
            table, self.session_key.mic, self.session_key.local_date, self.as_of
        )
        if self.settlement_cycle != expected:
            raise ValueError(
                "calendar_features_invalid: settlement_cycle is not what the "
                "settlement table answers for the session date and cutoff"
            )


class CalendarFeatureSetV1(FrozenModel):
    """The features of every requested session, bound to the whole input.

    ``schedule_input_hash`` and ``event_input_hash`` identify every row and
    every event record supplied, including those published after a session's
    cutoff, so they change when later knowledge is added. Each session's own
    ``features_hash`` covers only what that session's features were read from.
    """

    schema_version: Literal["1"] = "1"
    evidence_lane: Literal["exploratory"] = "exploratory"
    algorithm_hash: SHA256Hash
    settlement_table_hash: SHA256Hash
    source_id: NonBlankStr
    mic: NonBlankStr
    knowledge_channel: AvailabilityChannelV1
    availability_policy_hash: SHA256Hash
    schedule_input_hash: SHA256Hash
    event_input_hash: SHA256Hash
    event_kinds: tuple[CalendarEventKind, ...]
    sessions: tuple[CalendarSessionFeaturesV1, ...]
    set_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        if self.event_kinds != tuple(sorted(set(self.event_kinds))):
            raise ValueError(
                "calendar_feature_set_invalid: event kinds must be unique and sorted"
            )
        if not self.sessions:
            raise ValueError("calendar_feature_set_invalid: a set needs sessions")
        for earlier, later in pairwise(self.sessions):
            if later.session_key.local_date <= earlier.session_key.local_date:
                raise ValueError(
                    "calendar_feature_set_invalid: sessions must be in strictly "
                    "increasing date order"
                )
            if later.as_of < earlier.as_of:
                raise ValueError(
                    "calendar_feature_set_invalid: cutoffs must not decrease"
                )
        shared = (
            self.algorithm_hash,
            self.settlement_table_hash,
            self.source_id,
            self.mic,
            self.knowledge_channel,
            self.availability_policy_hash,
            self.event_kinds,
        )
        for item in self.sessions:
            own = (
                item.algorithm_hash,
                item.settlement_table_hash,
                item.source_id,
                item.session_key.mic,
                item.knowledge_channel,
                item.availability_policy_hash,
                tuple(event.event_kind for event in item.events),
            )
            if own != shared:
                raise ValueError(
                    "calendar_feature_set_invalid: every session must share the "
                    "set's algorithm, table, source, venue, knowledge and kinds"
                )
        if self.set_hash != calendar_feature_set_hash(self):
            raise ValueError(
                "calendar_feature_set_invalid: the set hash does not cover the "
                "set's own fields"
            )
        return self


_MONTH_REASONS = frozenset({None, "schedule_status_unknown", "session_not_known_open"})
_EXPIRATION_REASONS = frozenset(
    {None, "expiration_outside_month", "schedule_status_unknown"}
)


def monthly_expiration_flag(
    session_open: bool, day: date, expiration: CalendarDateV1
) -> CalendarFlagV1:
    """Whether ``day`` is the expiration session, or why that is unknown."""
    if not session_open:
        return CalendarFlagV1(
            status="indeterminate",
            value=None,
            reason="session_not_known_open",
            blocking_date=None,
        )
    if expiration.value is None:
        return CalendarFlagV1(
            status="indeterminate",
            value=None,
            reason=expiration.reason,
            blocking_date=expiration.blocking_date,
        )
    return CalendarFlagV1(
        status="known", value=day == expiration.value, reason=None, blocking_date=None
    )


def settlement_cycle_for(
    table: SettlementCycleTableV1, mic: str, trade_date: date, as_of: datetime
) -> SettlementCycleFeatureV1:
    """The cycle for one trade date, from the table rows known before ``as_of``.

    A row's start and cycle count as known from ``settlement_row_known_from``.
    The row containing the trade date answers once it is known. Before that,
    the latest known row starting on or before the trade date answers only
    while its end cannot yet be public (a cutoff at or before
    ``settlement_row_end_possibly_public_from``): as known then, it has no
    end. From that instant on, the end may already be public or is known, so
    the trade date may lie past the rule and nothing answers. A venue outside
    the table, a date before its first row or after ``verified_through`` has
    no answer at any cutoff.
    """
    reason: CalendarIndeterminateReason | None = None
    if mic not in table.venues:
        reason = "settlement_venue_outside_table"
    elif trade_date < table.rows[0].effective_from:
        reason = "settlement_before_table"
    elif trade_date > table.verified_through:
        reason = "settlement_after_verified_range"
    if reason is None:
        started = tuple(row for row in table.rows if row.effective_from <= trade_date)
        containing = started[-1]
        known = tuple(row for row in started if settlement_row_known_from(row) < as_of)
        answer: SettlementCycleRowV1 | None = None
        if containing in known:
            answer = containing
        elif known:
            end_public = settlement_row_end_possibly_public_from(known[-1])
            if end_public is None or as_of <= end_public:
                answer = known[-1]
        if answer is not None:
            return SettlementCycleFeatureV1(
                status="known",
                business_days_after_trade_date=answer.business_days_after_trade_date,
                row_id=answer.row_id,
                reason=None,
            )
        reason = "settlement_row_not_known_at_cutoff"
    return SettlementCycleFeatureV1(
        status="indeterminate",
        business_days_after_trade_date=None,
        row_id=None,
        reason=reason,
    )


def _self_excluding_hash(model: FrozenModel, field: str) -> SHA256Hash:
    dump = model.model_dump(mode="python", warnings=False)
    dump.pop(field, None)
    return content_hash(dump)


def calendar_event_record_hash(record: CalendarEventRecordV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one event record."""
    return _self_excluding_hash(record, "record_hash")


def settlement_cycle_table_hash(table: SettlementCycleTableV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one settlement table."""
    return _self_excluding_hash(table, "table_hash")


def calendar_session_features_hash(
    features: CalendarSessionFeaturesV1,
) -> SHA256Hash:
    """Return the self-excluding canonical hash of one session's features."""
    return _self_excluding_hash(features, "features_hash")


def calendar_feature_set_hash(feature_set: CalendarFeatureSetV1) -> SHA256Hash:
    """Return the self-excluding canonical hash of one feature set."""
    return _self_excluding_hash(feature_set, "set_hash")


def _seal[M: FrozenModel](
    model: type[M], values: Mapping[str, object], field: str
) -> M:
    """Seal ``field`` over ``values`` and validate; a seal never repairs.

    Values that cannot even be hashed, such as a naive datetime, are sealed
    with the placeholder so that validation reports the real fault.
    """
    body: dict[str, Any] = {key: item for key, item in values.items() if key != field}
    draft = model.model_construct(**(body | {field: _PLACEHOLDER_HASH}))
    try:
        digest = _self_excluding_hash(draft, field)
    except CanonicalSerializationError:
        digest = _PLACEHOLDER_HASH
    return model.model_validate(body | {field: digest})


def seal_calendar_event_record(values: Mapping[str, object]) -> CalendarEventRecordV1:
    """Seal an event record's own hash over ``values`` and validate it."""
    return _seal(CalendarEventRecordV1, values, "record_hash")


def seal_settlement_cycle_table(
    values: Mapping[str, object],
) -> SettlementCycleTableV1:
    """Seal a settlement table's own hash over ``values`` and validate it."""
    return _seal(SettlementCycleTableV1, values, "table_hash")


def seal_calendar_session_features(
    values: Mapping[str, object],
) -> CalendarSessionFeaturesV1:
    """Seal one session's features hash over ``values`` and validate them."""
    return _seal(CalendarSessionFeaturesV1, values, "features_hash")


def seal_calendar_feature_set(values: Mapping[str, object]) -> CalendarFeatureSetV1:
    """Seal a feature set's own hash over ``values`` and validate it."""
    return _seal(CalendarFeatureSetV1, values, "set_hash")


US_REGULAR_WAY_SETTLEMENT_TABLE_V1 = seal_settlement_cycle_table(
    {
        "table_id": "drift-us-regular-way-settlement-cycle",
        "table_version": "1",
        "venues": ("XASE", "XNAS", "XNYS"),
        "verified_through": date(2026, 11, 20),
        "rows": (
            SettlementCycleRowV1(
                row_id="t5-sro-regular-way",
                business_days_after_trade_date=5,
                effective_from=date(1993, 10, 6),
                effective_until=date(1995, 6, 1),
                announced_on=date(1993, 10, 6),
                end_announced_on=date(1993, 10, 6),
                authority=(
                    "SEC Release No. 34-33023 (1993-10-06) adopting Rule 15c6-1 "
                    "describes T+5 as the standard it replaces from 1995-06-01"
                ),
            ),
            SettlementCycleRowV1(
                row_id="t5-before-conversion",
                business_days_after_trade_date=5,
                effective_from=date(1995, 6, 1),
                effective_until=date(1995, 6, 5),
                announced_on=date(1995, 4, 1),
                end_announced_on=date(1995, 4, 1),
                authority=(
                    "SEC Release No. 34-34952 (1994-11-09) moved the Rule 15c6-1 "
                    "effective date to 1995-06-07; NASD Notice to Members 95-26 "
                    "(1995-04-01) settles 1995-06-02 trades on 1995-06-09"
                ),
            ),
            SettlementCycleRowV1(
                row_id="t4-conversion",
                business_days_after_trade_date=4,
                effective_from=date(1995, 6, 5),
                effective_until=date(1995, 6, 7),
                announced_on=date(1995, 4, 1),
                end_announced_on=date(1995, 4, 1),
                authority=(
                    "NASD Notice to Members 95-26 (1995-04-01): trades of "
                    "1995-06-05 and 1995-06-06 settle in four business days"
                ),
            ),
            SettlementCycleRowV1(
                row_id="t3-rule-15c6-1",
                business_days_after_trade_date=3,
                effective_from=date(1995, 6, 7),
                effective_until=date(2017, 9, 5),
                announced_on=date(1995, 4, 1),
                end_announced_on=date(2017, 3, 22),
                authority=(
                    "Rule 15c6-1 effective 1995-06-07 (SEC Release No. 34-34952; "
                    "NASD Notice to Members 95-26)"
                ),
            ),
            SettlementCycleRowV1(
                row_id="t2-rule-15c6-1",
                business_days_after_trade_date=2,
                effective_from=date(2017, 9, 5),
                effective_until=date(2024, 5, 28),
                announced_on=date(2017, 3, 22),
                end_announced_on=date(2023, 2, 15),
                authority=(
                    "SEC Release No. 34-80295 (2017-03-22), compliance date 2017-09-05"
                ),
            ),
            SettlementCycleRowV1(
                row_id="t1-rule-15c6-1",
                business_days_after_trade_date=1,
                effective_from=date(2024, 5, 28),
                effective_until=None,
                announced_on=date(2023, 2, 15),
                end_announced_on=None,
                authority=(
                    "SEC Release No. 34-96930 (2023-02-15), compliance date 2024-05-28"
                ),
            ),
        ),
    }
)
"""The one settlement table the V1 algorithm reads. Sources in the doc."""
