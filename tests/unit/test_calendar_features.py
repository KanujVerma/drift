"""Hand-computed vectors and contract checks for issue 662 calendar features.

The NYSE dates used below are real 2024 to 2025 closures (New Year's Day,
the 2025-01-09 National Day of Mourning, Martin Luther King Jr. Day, Good
Friday 2025-04-18, Christmas) and the 2024-12-24 early close. Every
availability instant is synthetic: it only orders knowledge against the
cutoffs the tests choose. The schedule rows are authored test rows, not a
provider's calendar.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.datasets.hashing import assertion_version_payload
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    BoundaryShape,
    HistoryCompleteness,
    RevisionEnvelopeV1,
    TemporalBoundaryClaimV1,
)
from drift.domain.calendar_features import (
    CALENDAR_FEATURE_INPUT_CODES,
    US_REGULAR_WAY_SETTLEMENT_TABLE_V1,
    CalendarCountV1,
    CalendarEventRecordV1,
    CalendarFeatureInputError,
    CalendarFeatureRequestV1,
    CalendarFeatureSetV1,
    CalendarSessionFeaturesV1,
    SettlementCycleRowV1,
    SettlementCycleTableV1,
    calendar_feature_algorithm_hash,
    seal_calendar_event_record,
    seal_settlement_cycle_table,
    settlement_row_known_from,
    third_friday_of_month,
)
from drift.domain.revisions import RevisionKind
from drift.domain.sessions import (
    HistoricalBoundaryOffsetV1,
    ScheduledSessionVersionV1,
    SessionKeyV1,
)
from drift.domain.temporal import (
    CONSERVATIVE_UPPER_BOUND_RULE_HASH,
    AvailabilityBasis,
    AvailabilityChannelV1,
    AvailabilityEvidenceV1,
    AvailabilityPolicyV1,
    AvailabilityShape,
    ChannelKind,
    SourcePrecision,
    derive_conservative_upper_bound,
)
from drift.markets.calendar_features import compute_calendar_features
from drift.serialization.canonical import content_hash

type RowState = Literal["regular", "early_close", "closed", "unknown"]

BOUNDARIES: tuple[Literal["open", "close"], ...] = ("open", "close")
SOURCE_ID = "calendar-test-source"
MIC = "XNYS"
CHANNEL = AvailabilityChannelV1(
    kind=ChannelKind.PUBLIC, identifier="calendar-test-public", version="1"
)
OTHER_CHANNEL = AvailabilityChannelV1(
    kind=ChannelKind.PUBLIC, identifier="calendar-test-other", version="1"
)
POLICY = AvailabilityPolicyV1(policy_id="calendar-test-policy")
METHODOLOGY_HASH = sha256(b"calendar-test-methodology").hexdigest()
ARTIFACT_HASH = sha256(b"calendar-test-artifact").hexdigest()
#: When the authored base schedule rows became available (synthetic).
SCHEDULE_PUBLISHED = datetime(2024, 6, 3, 12, tzinfo=UTC)
#: Synthetic availability of the 2025-01-09 closure correction. The NYSE
#: announced the closure on 2024-12-30; the instant here is illustrative.
MOURNING_ANNOUNCED = datetime(2024, 12, 30, 22, tzinfo=UTC)
MOURNING_DAY = date(2025, 1, 9)

#: NYSE full closures on weekdays in the months the tests author.
NYSE_HOLIDAYS = frozenset(
    {
        date(2024, 12, 25),
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 4, 18),
    }
)
NYSE_EARLY_CLOSES = frozenset({date(2024, 12, 24)})
FOMC_KIND = "fomc_scheduled_meeting"


def derived_uuid7(*parts: str) -> UUID:
    """A stable RFC 9562 version 7 identifier derived from exact parts."""
    digest = sha256("\u0000".join(("calendar-test", *parts)).encode()).digest()
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def reference(*parts: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=derived_uuid7("artifact", *parts),
        kind=ArtifactKind.OTHER,
        content_hash=ARTIFACT_HASH,
        location=f"drift+sha256://{ARTIFACT_HASH}",
    )


def exact_availability(
    instant: datetime, channel: AvailabilityChannelV1 = CHANNEL
) -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=channel,
        shape=AvailabilityShape.EXACT,
        lower_bound=instant,
        upper_bound=instant,
        precision=SourcePrecision.SECOND,
        source_time_label=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference("availability", instant.isoformat()),
        rule_derivation=None,
    )


def bounded_availability(lower: datetime, upper: datetime) -> AvailabilityEvidenceV1:
    return AvailabilityEvidenceV1(
        channel=CHANNEL,
        shape=AvailabilityShape.BOUNDED,
        lower_bound=lower,
        upper_bound=upper,
        precision=SourcePrecision.INTERVAL,
        source_time_label=f"{lower.isoformat()}/{upper.isoformat()}",
        source_timezone=None,
        basis=AvailabilityBasis.SOURCE_OBSERVED,
        evidence_reference=reference("bounded", lower.isoformat()),
        rule_derivation=None,
    )


def schedule_row(
    day: date,
    state: RowState,
    *,
    available_at: datetime = SCHEDULE_PUBLISHED,
    predecessor: ScheduledSessionVersionV1 | None = None,
    kind: RevisionKind | None = None,
    logical_salt: str = "",
    source_id: str = SOURCE_ID,
    mic: str = MIC,
    availability: tuple[AvailabilityEvidenceV1, ...] | None = None,
) -> ScheduledSessionVersionV1:
    """One authored schedule row, or a later version of ``predecessor``."""
    sequence = 0 if predecessor is None else predecessor.revision.source_sequence + 1
    logical = (
        predecessor.revision.logical_record_id
        if predecessor is not None
        else derived_uuid7("logical", source_id, mic, day.isoformat(), logical_salt)
    )
    seed = (str(logical), str(sequence), state, available_at.isoformat())
    is_open = state in {"regular", "early_close"}
    close = "13:00:00" if state == "early_close" else "16:00:00"
    revision = RevisionEnvelopeV1(
        schema_version="1",
        logical_record_id=logical,
        record_version_id=derived_uuid7("version", *seed),
        revision_kind=(
            kind
            if kind is not None
            else RevisionKind.INITIAL
            if predecessor is None
            else RevisionKind.CORRECTION
        ),
        supersedes_record_version_id=(
            None if predecessor is None else predecessor.revision.record_version_id
        ),
        source_sequence=sequence,
        availability=availability or (exact_availability(available_at),),
        history_completeness=HistoryCompleteness.UNKNOWN,
        source_native_revision_label=None,
        source_artifact=reference("source", *seed),
        payload_hash="0" * 64,
    )
    lower = datetime.combine(day, time(), UTC)
    values: dict[str, object] = {
        "schema_version": "1",
        "revision": revision,
        "source_id": source_id,
        "session_key": SessionKeyV1(mic=mic, session_scope="regular", local_date=day),
        "source_temporal_evidence": TemporalBoundaryClaimV1(
            schema_version="1",
            shape=BoundaryShape.BOUNDED,
            lower_bound=lower,
            upper_bound=lower + timedelta(days=1),
            source_precision=SourcePrecision.INTERVAL,
            source_time_label=day.isoformat(),
            source_timezone=None,
            evidence_reference=reference("temporal", *seed),
        ),
        "state": state,
        "local_open": f"{day.isoformat()}T09:30:00" if is_open else None,
        "local_close": f"{day.isoformat()}T{close}" if is_open else None,
        "timezone_identifier": "America/New_York",
        "open_fold": None,
        "close_fold": None,
        "historical_boundary_offsets": (
            tuple(
                HistoricalBoundaryOffsetV1(
                    boundary=boundary,
                    utc_offset_seconds=None,
                    methodology_encoding_hash=None,
                    authority_artifact_hash=None,
                    authority_availability_evidence_hash=None,
                )
                for boundary in BOUNDARIES
            )
            if is_open
            else ()
        ),
        "source_methodology_hash": METHODOLOGY_HASH,
    }
    provisional = ScheduledSessionVersionV1.model_construct(**cast(Any, values))
    values["revision"] = revision.model_copy(
        update={"payload_hash": content_hash(assertion_version_payload(provisional))}
    )
    return ScheduledSessionVersionV1.model_validate(values)


def nyse_state(day: date) -> RowState:
    if day.weekday() >= 5 or day in NYSE_HOLIDAYS:
        return "closed"
    if day in NYSE_EARLY_CLOSES:
        return "early_close"
    return "regular"


def dates_between(first: date, last: date) -> tuple[date, ...]:
    return tuple(
        date.fromordinal(ordinal)
        for ordinal in range(first.toordinal(), last.toordinal() + 1)
    )


def nyse_rows(
    first: date,
    last: date,
    *,
    available_at: datetime = SCHEDULE_PUBLISHED,
    skip: Iterable[date] = (),
) -> list[ScheduledSessionVersionV1]:
    """Authored rows for every calendar date from ``first`` through ``last``."""
    skipped = frozenset(skip)
    return [
        schedule_row(day, nyse_state(day), available_at=available_at)
        for day in dates_between(first, last)
        if day not in skipped
    ]


def with_mourning_closure(
    rows: Sequence[ScheduledSessionVersionV1],
    announced: datetime = MOURNING_ANNOUNCED,
) -> list[ScheduledSessionVersionV1]:
    """Add the late-announced 2025-01-09 closure as a correction."""
    (original,) = (row for row in rows if row.session_key.local_date == MOURNING_DAY)
    return [
        *rows,
        schedule_row(
            MOURNING_DAY, "closed", available_at=announced, predecessor=original
        ),
    ]


def request(day: date, as_of: datetime, mic: str = MIC) -> CalendarFeatureRequestV1:
    return CalendarFeatureRequestV1(
        session_key=SessionKeyV1(mic=mic, session_scope="regular", local_date=day),
        as_of=as_of,
    )


def evening_before(day: date) -> datetime:
    """A cutoff of 23:00 UTC on the calendar day before ``day``."""
    return datetime.combine(day - timedelta(days=1), time(23), UTC)


def compute(
    rows: Sequence[ScheduledSessionVersionV1],
    requests: Sequence[CalendarFeatureRequestV1],
    *,
    events: Sequence[CalendarEventRecordV1] = (),
    event_kinds: Sequence[str] = (),
) -> CalendarFeatureSetV1:
    return compute_calendar_features(
        rows,
        requests,
        channel=CHANNEL,
        availability_policy=POLICY,
        events=events,
        event_kinds=event_kinds,
    )


def features_at(
    rows: Sequence[ScheduledSessionVersionV1],
    day: date,
    as_of: datetime | None = None,
    **kwargs: Any,
) -> CalendarSessionFeaturesV1:
    result = compute(rows, (request(day, as_of or evening_before(day)),), **kwargs)
    (session,) = result.sessions
    return session


def event_record(
    event_id: str,
    event_date: date,
    published_at: datetime,
    *,
    revision: int = 0,
    status: Literal["scheduled", "cancelled"] = "scheduled",
    kind: str = FOMC_KIND,
) -> CalendarEventRecordV1:
    return seal_calendar_event_record(
        {
            "event_id": event_id,
            "revision": revision,
            "event_kind": kind,
            "status": status,
            "event_date": event_date,
            "published_at": published_at,
            "source_sha256": None,
        }
    )


def month_triple(features: CalendarSessionFeaturesV1) -> tuple[int | None, ...]:
    return (
        features.month_ordinal_from_start.value,
        features.month_ordinal_from_end.value,
        features.sessions_remaining_in_month.value,
    )


JANUARY = nyse_rows(date(2024, 12, 1), date(2025, 2, 28))
JANUARY_WITH_MOURNING = with_mourning_closure(JANUARY)
APRIL = nyse_rows(date(2025, 3, 1), date(2025, 5, 31))


# --- third Friday --------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2024, 12, date(2024, 12, 20)),
        (2025, 1, date(2025, 1, 17)),
        (2025, 4, date(2025, 4, 18)),
        (2024, 5, date(2024, 5, 17)),
        (2017, 9, date(2017, 9, 15)),
        (2026, 6, date(2026, 6, 19)),
    ],
)
def test_third_friday_vectors(year: int, month: int, expected: date) -> None:
    assert third_friday_of_month(year, month) == expected


def test_third_friday_is_always_the_third_friday() -> None:
    for year in range(1990, 2031):
        for month in range(1, 13):
            value = third_friday_of_month(year, month)
            fridays = [
                day for day in range(1, 29) if date(year, month, day).weekday() == 4
            ]
            assert value == date(year, month, fridays[2])


# --- month position across holidays --------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 1, 2), (1, 20, 19)),
        (date(2025, 1, 8), (5, 16, 15)),
        (date(2025, 1, 10), (6, 15, 14)),
        (date(2025, 1, 17), (11, 10, 9)),
        (date(2025, 1, 21), (12, 9, 8)),
        (date(2025, 1, 31), (20, 1, 0)),
    ],
)
def test_january_2025_month_position_with_the_mourning_closure(
    day: date, expected: tuple[int, int, int]
) -> None:
    features = features_at(JANUARY_WITH_MOURNING, day)
    assert features.session_status == "open"
    assert month_triple(features) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 1, 2), (1, 21, 20)),
        (date(2025, 1, 8), (5, 17, 16)),
        (date(2025, 1, 10), (7, 15, 14)),
        (date(2025, 1, 31), (21, 1, 0)),
    ],
)
def test_january_2025_month_position_without_the_closure(
    day: date, expected: tuple[int, int, int]
) -> None:
    assert month_triple(features_at(JANUARY, day)) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 12, 2), (1, 21, 20)),
        (date(2024, 12, 24), (17, 5, 4)),
        (date(2024, 12, 26), (18, 4, 3)),
        (date(2024, 12, 31), (21, 1, 0)),
    ],
)
def test_december_2024_counts_the_early_close_as_a_session(
    day: date, expected: tuple[int, int, int]
) -> None:
    assert month_triple(features_at(JANUARY, day)) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 4, 1), (1, 21, 20)),
        (date(2025, 4, 17), (13, 9, 8)),
        (date(2025, 4, 21), (14, 8, 7)),
        (date(2025, 4, 30), (21, 1, 0)),
    ],
)
def test_april_2025_month_position_across_good_friday(
    day: date, expected: tuple[int, int, int]
) -> None:
    assert month_triple(features_at(APRIL, day)) == expected


# --- monthly expiration ---------------------------------------------------


def test_good_friday_2025_moves_expiration_to_thursday() -> None:
    thursday = features_at(APRIL, date(2025, 4, 17))
    assert thursday.third_friday == date(2025, 4, 18)
    assert not thursday.is_third_friday
    assert thursday.monthly_expiration_session.value == date(2025, 4, 17)
    assert thursday.is_monthly_expiration_session.value is True

    friday = features_at(APRIL, date(2025, 4, 18))
    assert friday.session_status == "closed"
    assert friday.is_third_friday
    assert friday.monthly_expiration_session.value == date(2025, 4, 17)
    assert friday.is_monthly_expiration_session.reason == "session_not_known_open"
    assert friday.month_ordinal_from_start.reason == "session_not_known_open"


def test_an_open_third_friday_is_the_expiration_session() -> None:
    friday = features_at(JANUARY, date(2025, 1, 17))
    assert friday.is_third_friday
    assert friday.monthly_expiration_session.value == date(2025, 1, 17)
    assert friday.is_monthly_expiration_session.value is True
    other = features_at(JANUARY, date(2025, 1, 16))
    assert other.monthly_expiration_session.value == date(2025, 1, 17)
    assert other.is_monthly_expiration_session.value is False


def test_expiration_walks_back_over_consecutive_closures() -> None:
    """Synthetic: Thursday and Friday both closed moves it to Wednesday."""
    rows = [
        row
        if row.session_key.local_date != date(2025, 4, 17)
        else schedule_row(date(2025, 4, 17), "closed", logical_salt="synthetic")
        for row in APRIL
    ]
    features = features_at(rows, date(2025, 4, 16))
    assert features.monthly_expiration_session.value == date(2025, 4, 16)
    assert features.is_monthly_expiration_session.value is True


def test_expiration_is_indeterminate_when_the_walk_meets_an_unknown_date() -> None:
    rows = [row for row in APRIL if row.session_key.local_date != date(2025, 4, 17)]
    features = features_at(rows, date(2025, 4, 10))
    assert features.monthly_expiration_session.status == "indeterminate"
    assert features.monthly_expiration_session.reason == "schedule_status_unknown"
    assert features.monthly_expiration_session.blocking_date == date(2025, 4, 17)
    assert features.is_monthly_expiration_session.blocking_date == date(2025, 4, 17)


# --- INDETERMINATE, never a guessed default ------------------------------


def test_month_end_is_indeterminate_when_the_rest_of_the_month_is_not_known() -> None:
    rows = nyse_rows(date(2025, 1, 1), date(2025, 1, 20))
    features = features_at(rows, date(2025, 1, 10))
    assert features.month_ordinal_from_start.value == 7
    for item in (features.month_ordinal_from_end, features.sessions_remaining_in_month):
        assert item.status == "indeterminate"
        assert item.reason == "schedule_status_unknown"
        assert item.blocking_date == date(2025, 1, 21)


def test_a_missing_weekend_row_is_unknown_not_closed() -> None:
    rows = nyse_rows(date(2025, 1, 1), date(2025, 1, 31), skip=(date(2025, 1, 11),))
    features = features_at(rows, date(2025, 1, 10))
    assert features.month_ordinal_from_end.blocking_date == date(2025, 1, 11)
    later = features_at(rows, date(2025, 1, 13))
    assert later.month_ordinal_from_start.blocking_date == date(2025, 1, 11)
    assert later.month_ordinal_from_end.value == 14


def test_a_row_whose_own_state_is_unknown_blocks_its_month() -> None:
    rows = [
        row
        if row.session_key.local_date != date(2025, 1, 6)
        else schedule_row(date(2025, 1, 6), "unknown", logical_salt="unknown-state")
        for row in nyse_rows(date(2025, 1, 1), date(2025, 1, 31))
    ]
    features = features_at(rows, date(2025, 1, 10))
    assert features.month_ordinal_from_start.blocking_date == date(2025, 1, 6)
    assert features.month_ordinal_from_end.value == 15


def test_a_session_with_no_known_row_is_not_a_session() -> None:
    rows = nyse_rows(date(2025, 1, 1), date(2025, 1, 31), skip=(date(2025, 1, 10),))
    features = features_at(rows, date(2025, 1, 10))
    assert features.session_status == "unknown"
    assert features.schedule_record_hashes  # the expiration walk read rows
    for item in (
        features.month_ordinal_from_start,
        features.month_ordinal_from_end,
        features.sessions_remaining_in_month,
        features.is_monthly_expiration_session,
    ):
        assert item.reason == "session_not_known_open"
    assert features.settlement_cycle.business_days_after_trade_date == 1


def test_a_row_is_known_only_strictly_before_the_cutoff() -> None:
    day = date(2025, 1, 10)
    exactly = features_at(JANUARY, day, as_of=SCHEDULE_PUBLISHED)
    assert exactly.session_status == "unknown"
    assert exactly.schedule_record_hashes == ()
    later = features_at(JANUARY, day, as_of=SCHEDULE_PUBLISHED + timedelta(seconds=1))
    assert later.session_status == "open"


def test_bounded_availability_spanning_the_cutoff_is_unknown() -> None:
    lower = datetime(2024, 6, 1, tzinfo=UTC)
    upper = datetime(2024, 6, 10, tzinfo=UTC)
    rows = [
        row
        if row.session_key.local_date != date(2025, 1, 10)
        else schedule_row(
            date(2025, 1, 10),
            "regular",
            logical_salt="bounded",
            availability=(bounded_availability(lower, upper),),
        )
        for row in JANUARY
    ]
    inside = features_at(
        rows, date(2025, 1, 10), as_of=datetime(2024, 6, 5, tzinfo=UTC)
    )
    assert inside.session_status == "unknown"
    at_upper = features_at(rows, date(2025, 1, 10), as_of=upper)
    assert at_upper.session_status == "unknown"
    after = features_at(rows, date(2025, 1, 10), as_of=upper + timedelta(seconds=1))
    assert after.session_status == "open"


def test_a_row_known_only_on_another_channel_is_unknown() -> None:
    rows = [
        row
        if row.session_key.local_date != date(2025, 1, 10)
        else schedule_row(
            date(2025, 1, 10),
            "regular",
            logical_salt="other-channel",
            availability=(exact_availability(SCHEDULE_PUBLISHED, OTHER_CHANNEL),),
        )
        for row in JANUARY
    ]
    assert features_at(rows, date(2025, 1, 10)).session_status == "unknown"


def test_a_withdrawn_row_is_unknown_after_the_withdrawal() -> None:
    withdrawn_at = datetime(2024, 11, 1, tzinfo=UTC)
    (original,) = (
        row for row in JANUARY if row.session_key.local_date == date(2025, 1, 10)
    )
    rows = [
        *JANUARY,
        schedule_row(
            date(2025, 1, 10),
            "regular",
            available_at=withdrawn_at,
            predecessor=original,
            kind=RevisionKind.WITHDRAWAL,
        ),
    ]
    before = features_at(rows, date(2025, 1, 10), as_of=withdrawn_at)
    assert before.session_status == "open"
    after = features_at(rows, date(2025, 1, 10))
    assert after.session_status == "unknown"


def _rule_derived_case() -> tuple[
    list[ScheduledSessionVersionV1], AvailabilityEvidenceV1, CalendarFeatureRequestV1
]:
    raw = bounded_availability(
        datetime(2024, 6, 1, tzinfo=UTC), datetime(2024, 6, 2, tzinfo=UTC)
    )
    rule = ArtifactReference(
        artifact_id=derived_uuid7("rule"),
        kind=ArtifactKind.OTHER,
        content_hash=CONSERVATIVE_UPPER_BOUND_RULE_HASH,
        location=f"drift+sha256://{CONSERVATIVE_UPPER_BOUND_RULE_HASH}",
    )
    derived = derive_conservative_upper_bound(raw, rule)
    rows = [
        row
        if row.session_key.local_date != date(2025, 1, 10)
        else schedule_row(
            date(2025, 1, 10),
            "regular",
            logical_salt="rule-derived",
            availability=(derived,),
        )
        for row in JANUARY
    ]
    return rows, raw, request(date(2025, 1, 10), evening_before(date(2025, 1, 10)))


def test_rule_derived_availability_needs_its_evidence_and_policy() -> None:
    rows, raw, requested = _rule_derived_case()
    permitted = AvailabilityPolicyV1(
        policy_id="calendar-test-policy",
        permitted_rule_hashes=(CONSERVATIVE_UPPER_BOUND_RULE_HASH,),
    )

    def status(
        policy: AvailabilityPolicyV1, retained: dict[str, AvailabilityEvidenceV1]
    ) -> str:
        result = compute_calendar_features(
            rows,
            (requested,),
            channel=CHANNEL,
            availability_policy=policy,
            retained_evidence=retained,
        )
        return result.sessions[0].session_status

    retained = {content_hash(raw): raw}
    assert status(permitted, retained) == "open"
    assert status(permitted, {}) == "unknown"
    assert status(POLICY, retained) == "unknown"
    with pytest.raises(CalendarFeatureInputError) as error:
        status(permitted, {"0" * 64: raw})
    assert error.value.code == "calendar_retained_evidence_invalid"


def test_a_malformed_knowledge_channel_is_refused() -> None:
    with pytest.raises(CalendarFeatureInputError) as error:
        compute_calendar_features(
            JANUARY,
            (request(date(2025, 1, 10), evening_before(date(2025, 1, 10))),),
            channel=cast(Any, {"kind": "public", "identifier": "x"}),
            availability_policy=POLICY,
        )
    assert error.value.code == "calendar_knowledge_policy_invalid"


# --- settlement cycle -----------------------------------------------------


SETTLEMENT_ROWS = [schedule_row(date(2017, 9, 5), "regular")]
#: A cutoff after every settlement row's announcement.
LATE_CUTOFF = datetime(2026, 11, 21, tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "expected", "row_id"),
    [
        (date(1993, 10, 6), 5, "t5-sro-regular-way"),
        (date(1995, 5, 31), 5, "t5-sro-regular-way"),
        (date(1995, 6, 1), 5, "t5-before-conversion"),
        (date(1995, 6, 2), 5, "t5-before-conversion"),
        (date(1995, 6, 5), 4, "t4-conversion"),
        (date(1995, 6, 6), 4, "t4-conversion"),
        (date(1995, 6, 7), 3, "t3-rule-15c6-1"),
        (date(2017, 9, 1), 3, "t3-rule-15c6-1"),
        (date(2017, 9, 5), 2, "t2-rule-15c6-1"),
        (date(2024, 5, 24), 2, "t2-rule-15c6-1"),
        (date(2024, 5, 28), 1, "t1-rule-15c6-1"),
        (date(2026, 11, 20), 1, "t1-rule-15c6-1"),
    ],
)
def test_settlement_cycle_on_and_either_side_of_each_boundary(
    day: date, expected: int, row_id: str
) -> None:
    features = features_at(SETTLEMENT_ROWS, day, as_of=LATE_CUTOFF)
    assert features.settlement_cycle.status == "known"
    assert features.settlement_cycle.business_days_after_trade_date == expected
    assert features.settlement_cycle.row_id == row_id


@pytest.mark.parametrize(
    ("day", "reason"),
    [
        (date(1993, 10, 5), "settlement_before_table"),
        (date(2026, 11, 23), "settlement_after_verified_range"),
    ],
)
def test_settlement_outside_the_table_is_indeterminate(day: date, reason: str) -> None:
    cycle = features_at(SETTLEMENT_ROWS, day, as_of=LATE_CUTOFF).settlement_cycle
    assert cycle.status == "indeterminate"
    assert cycle.reason == reason
    assert cycle.business_days_after_trade_date is None


def test_settlement_outside_the_table_venues_is_indeterminate() -> None:
    rows = [schedule_row(date(2025, 1, 10), "regular", mic="XLON")]
    result = compute(rows, (request(date(2025, 1, 10), LATE_CUTOFF, mic="XLON"),))
    cycle = result.sessions[0].settlement_cycle
    assert cycle.reason == "settlement_venue_outside_table"


def test_the_first_settlement_row_counts_only_after_its_evidence_date() -> None:
    cycle = features_at(SETTLEMENT_ROWS, date(1993, 10, 6)).settlement_cycle
    assert cycle.reason == "settlement_row_not_known_at_cutoff"


def test_a_settlement_row_counts_only_after_its_announcement() -> None:
    (row,) = (
        item
        for item in US_REGULAR_WAY_SETTLEMENT_TABLE_V1.rows
        if item.row_id == "t1-rule-15c6-1"
    )
    known_from = settlement_row_known_from(row)
    assert known_from == datetime(2023, 2, 17, tzinfo=UTC)
    day = date(2024, 5, 28)
    for as_of, status in (
        (datetime(2023, 2, 15, 23, tzinfo=UTC), "indeterminate"),
        (known_from, "indeterminate"),
        (known_from + timedelta(seconds=1), "known"),
    ):
        cycle = features_at(SETTLEMENT_ROWS, day, as_of=as_of).settlement_cycle
        assert cycle.status == status
    early = features_at(SETTLEMENT_ROWS, day, as_of=known_from).settlement_cycle
    assert early.reason == "settlement_row_not_known_at_cutoff"


def test_the_settlement_table_is_closed_contiguous_and_pinned() -> None:
    table = US_REGULAR_WAY_SETTLEMENT_TABLE_V1
    assert table.venues == ("XASE", "XNAS", "XNYS")
    assert [row.business_days_after_trade_date for row in table.rows] == [
        5,
        5,
        4,
        3,
        2,
        1,
    ]
    assert table.table_hash == PINNED_TABLE_HASH
    assert SettlementCycleTableV1.model_validate(table.model_dump()) == table


def _table_values(**changes: object) -> dict[str, object]:
    values = US_REGULAR_WAY_SETTLEMENT_TABLE_V1.model_dump(mode="python")
    values.pop("table_hash")
    values["rows"] = tuple(
        SettlementCycleRowV1.model_validate(row) for row in values["rows"]
    )
    values["venues"] = tuple(values["venues"])
    values.update(changes)
    return values


def test_a_gap_in_the_settlement_table_is_refused() -> None:
    rows = list(US_REGULAR_WAY_SETTLEMENT_TABLE_V1.rows)
    rows[2] = rows[2].model_copy(update={"effective_from": date(1995, 6, 6)})
    with pytest.raises(ValidationError, match="sorted and contiguous"):
        seal_settlement_cycle_table(_table_values(rows=tuple(rows)))


def test_a_closed_last_settlement_row_is_refused() -> None:
    rows = list(US_REGULAR_WAY_SETTLEMENT_TABLE_V1.rows)
    rows[-1] = rows[-1].model_copy(update={"effective_until": date(2030, 1, 1)})
    with pytest.raises(ValidationError, match="only the last row is open"):
        seal_settlement_cycle_table(_table_values(rows=tuple(rows)))


def test_a_settlement_row_announced_after_it_applies_is_refused() -> None:
    with pytest.raises(ValidationError, match="announced after"):
        SettlementCycleRowV1(
            row_id="late",
            business_days_after_trade_date=1,
            effective_from=date(2024, 5, 28),
            effective_until=None,
            announced_on=date(2024, 5, 29),
            authority="synthetic",
        )


def test_a_forged_settlement_table_hash_is_refused() -> None:
    values = _table_values()
    values["table_hash"] = "1" * 64
    with pytest.raises(ValidationError, match="table hash"):
        SettlementCycleTableV1.model_validate(values)


# --- known-in-advance events ---------------------------------------------


FOMC_PUBLISHED = datetime(2024, 8, 1, 12, tzinfo=UTC)


def test_a_visible_event_marks_its_session_and_counts_down_to_it() -> None:
    events = (event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),)
    before = features_at(
        JANUARY_WITH_MOURNING,
        date(2025, 1, 24),
        events=events,
        event_kinds=(FOMC_KIND,),
    )
    (item,) = before.events
    assert not item.on_session
    assert item.next_event_date.value == date(2025, 1, 29)
    assert item.sessions_until_next_event.value == 3
    assert item.previous_event_date.reason == "no_visible_event"
    assert before.event_record_hashes == (events[0].record_hash,)

    on = features_at(
        JANUARY_WITH_MOURNING,
        date(2025, 1, 29),
        events=events,
        event_kinds=(FOMC_KIND,),
    )
    (item,) = on.events
    assert item.on_session
    assert item.next_event_date.reason == "no_visible_event"
    assert item.sessions_until_next_event.reason == "no_visible_event"


def test_an_event_published_at_or_after_the_cutoff_is_invisible() -> None:
    events = (event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),)
    for as_of, visible in (
        (FOMC_PUBLISHED, False),
        (FOMC_PUBLISHED + timedelta(seconds=1), True),
    ):
        features = features_at(
            JANUARY,
            date(2025, 1, 10),
            as_of=as_of,
            events=events,
            event_kinds=(FOMC_KIND,),
        )
        (item,) = features.events
        assert (item.next_event_date.value is not None) is visible
        assert bool(features.event_record_hashes) is visible


def test_a_rescheduled_event_moves_only_once_the_revision_is_published() -> None:
    moved_at = datetime(2024, 12, 2, tzinfo=UTC)
    events = (
        event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),
        event_record("fomc-2025-01", date(2025, 1, 30), moved_at, revision=1),
    )
    kwargs: dict[str, Any] = {"events": events, "event_kinds": (FOMC_KIND,)}
    before = features_at(JANUARY, date(2025, 1, 2), as_of=moved_at, **kwargs)
    after = features_at(
        JANUARY, date(2025, 1, 2), as_of=moved_at + timedelta(hours=1), **kwargs
    )
    assert before.events[0].next_event_date.value == date(2025, 1, 29)
    assert after.events[0].next_event_date.value == date(2025, 1, 30)
    assert before.event_record_hashes == (events[0].record_hash,)
    assert after.event_record_hashes == (events[1].record_hash,)


def test_a_cancelled_event_is_no_longer_visible() -> None:
    cancelled_at = datetime(2024, 12, 2, tzinfo=UTC)
    events = (
        event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),
        event_record(
            "fomc-2025-01",
            date(2025, 1, 29),
            cancelled_at,
            revision=1,
            status="cancelled",
        ),
    )
    features = features_at(
        JANUARY, date(2025, 1, 2), events=events, event_kinds=(FOMC_KIND,)
    )
    assert features.events[0].next_event_date.reason == "no_visible_event"
    assert features.event_record_hashes == (events[1].record_hash,)


def test_sessions_until_an_event_needs_every_date_up_to_it_known() -> None:
    rows = nyse_rows(date(2025, 1, 1), date(2025, 1, 25))
    events = (event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED),)
    features = features_at(
        rows, date(2025, 1, 24), events=events, event_kinds=(FOMC_KIND,)
    )
    countdown = features.events[0].sessions_until_next_event
    assert countdown.reason == "schedule_status_unknown"
    assert countdown.blocking_date == date(2025, 1, 26)


def test_every_declared_kind_is_reported_even_without_records() -> None:
    features = features_at(
        JANUARY, date(2025, 1, 10), event_kinds=("zeta_kind", FOMC_KIND)
    )
    assert [item.event_kind for item in features.events] == [FOMC_KIND, "zeta_kind"]


# --- refusals --------------------------------------------------------------


def _refused(code: str, *args: Any, **kwargs: Any) -> None:
    assert code in CALENDAR_FEATURE_INPUT_CODES
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(*args, **kwargs)
    assert error.value.code == code


def test_an_empty_schedule_is_refused() -> None:
    _refused(
        "calendar_schedule_empty", [], (request(date(2025, 1, 2), FOMC_PUBLISHED),)
    )


def test_rows_of_two_sources_are_refused() -> None:
    rows = [*JANUARY[:5], schedule_row(date(2025, 3, 3), "regular", source_id="other")]
    _refused(
        "calendar_schedule_mixed_source",
        rows,
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_rows_of_two_venues_are_refused() -> None:
    rows = [*JANUARY[:5], schedule_row(date(2025, 3, 3), "regular", mic="XNAS")]
    _refused(
        "calendar_schedule_mixed_venue",
        rows,
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_a_duplicate_row_is_refused() -> None:
    _refused(
        "calendar_schedule_duplicate_row",
        [*JANUARY, JANUARY[3]],
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_two_logical_rows_for_one_date_are_refused() -> None:
    rival = schedule_row(date(2025, 1, 10), "closed", logical_salt="rival")
    _refused(
        "calendar_schedule_conflicting_rows",
        [*JANUARY, rival],
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_an_identical_rival_row_for_one_date_is_still_refused() -> None:
    rival = schedule_row(date(2025, 1, 10), "regular", logical_salt="same-state")
    _refused(
        "calendar_schedule_conflicting_rows",
        [*JANUARY, rival],
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_a_branching_row_chain_is_refused() -> None:
    (original,) = (row for row in JANUARY if row.session_key.local_date == MOURNING_DAY)
    first = schedule_row(
        MOURNING_DAY, "closed", available_at=MOURNING_ANNOUNCED, predecessor=original
    )
    second = schedule_row(
        MOURNING_DAY,
        "early_close",
        available_at=MOURNING_ANNOUNCED + timedelta(hours=1),
        predecessor=original,
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute(
            [*JANUARY, first, second], (request(date(2024, 12, 2), FOMC_PUBLISHED),)
        )
    assert error.value.code == "calendar_schedule_chain_invalid"
    assert "branching_revision_chain" in str(error.value)


def test_a_correction_available_before_its_predecessor_is_refused() -> None:
    (original,) = (row for row in JANUARY if row.session_key.local_date == MOURNING_DAY)
    backwards = schedule_row(
        MOURNING_DAY,
        "closed",
        available_at=SCHEDULE_PUBLISHED - timedelta(days=1),
        predecessor=original,
    )
    with pytest.raises(CalendarFeatureInputError) as error:
        compute([*JANUARY, backwards], (request(date(2024, 12, 2), FOMC_PUBLISHED),))
    assert error.value.code == "calendar_schedule_chain_invalid"
    assert "backward_availability" in str(error.value)


def test_a_forged_row_is_refused() -> None:
    forged = JANUARY[5].model_construct(**(JANUARY[5].__dict__ | {"state": "closed"}))
    _refused(
        "calendar_schedule_row_invalid",
        [*JANUARY[:5], forged],
        (request(date(2024, 12, 2), FOMC_PUBLISHED),),
    )


def test_requests_must_be_ordered_and_their_cutoffs_monotone() -> None:
    first = request(date(2025, 1, 10), evening_before(date(2025, 1, 10)))
    second = request(date(2025, 1, 13), evening_before(date(2025, 1, 13)))
    _refused("calendar_request_order_invalid", JANUARY, (second, first))
    _refused("calendar_request_order_invalid", JANUARY, (first, first))
    rewound = request(date(2025, 1, 13), evening_before(date(2025, 1, 9)))
    _refused("calendar_request_cutoff_not_monotone", JANUARY, (first, rewound))
    _refused("calendar_requests_empty", JANUARY, ())
    _refused(
        "calendar_request_venue_mismatch",
        JANUARY,
        (request(date(2025, 1, 10), FOMC_PUBLISHED, mic="XNAS"),),
    )


def test_a_naive_cutoff_is_refused_at_construction() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        CalendarFeatureRequestV1(
            session_key=SessionKeyV1(
                mic=MIC, session_scope="regular", local_date=date(2025, 1, 10)
            ),
            as_of=datetime(2025, 1, 9, 23),
        )


def test_a_date_subclass_is_refused() -> None:
    class ShiftedDate(date):
        pass

    sneaky = CalendarFeatureRequestV1(
        session_key=SessionKeyV1(
            mic=MIC, session_scope="regular", local_date=ShiftedDate(2025, 1, 10)
        ),
        as_of=FOMC_PUBLISHED,
    )
    _refused("calendar_request_invalid", JANUARY, (sneaky,))


def test_event_inputs_are_refused_when_inconsistent() -> None:
    requests = (request(date(2025, 1, 10), evening_before(date(2025, 1, 10))),)
    base = event_record("fomc-2025-01", date(2025, 1, 29), FOMC_PUBLISHED)
    _refused(
        "calendar_event_kind_undeclared",
        JANUARY,
        requests,
        events=(base,),
        event_kinds=(),
    )
    kinds = (FOMC_KIND,)
    _refused(
        "calendar_event_duplicate",
        JANUARY,
        requests,
        events=(base, base),
        event_kinds=kinds,
    )
    gap = event_record(
        "fomc-2025-01",
        date(2025, 1, 30),
        FOMC_PUBLISHED + timedelta(days=1),
        revision=2,
    )
    _refused(
        "calendar_event_chain_invalid",
        JANUARY,
        requests,
        events=(base, gap),
        event_kinds=kinds,
    )
    stale = event_record("fomc-2025-01", date(2025, 1, 30), FOMC_PUBLISHED, revision=1)
    _refused(
        "calendar_event_chain_invalid",
        JANUARY,
        requests,
        events=(base, stale),
        event_kinds=kinds,
    )
    renamed = event_record(
        "fomc-2025-01",
        date(2025, 1, 30),
        FOMC_PUBLISHED + timedelta(days=1),
        revision=1,
        kind="other_kind",
    )
    _refused(
        "calendar_event_chain_invalid",
        JANUARY,
        requests,
        events=(base, renamed),
        event_kinds=(FOMC_KIND, "other_kind"),
    )
    _refused(
        "calendar_event_kinds_invalid", JANUARY, requests, event_kinds=("Bad Kind",)
    )
    _refused(
        "calendar_event_kinds_invalid",
        JANUARY,
        requests,
        event_kinds=(FOMC_KIND, FOMC_KIND),
    )


def test_an_event_record_refuses_naive_times_and_a_cancelled_first_revision() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        event_record("fomc", date(2025, 1, 29), datetime(2024, 8, 1))
    with pytest.raises(ValidationError, match="revision 0"):
        event_record("fomc", date(2025, 1, 29), FOMC_PUBLISHED, status="cancelled")
    record = event_record("fomc", date(2025, 1, 29), FOMC_PUBLISHED)
    with pytest.raises(ValidationError, match="record hash"):
        record.model_copy(update={"event_date": date(2025, 1, 30)})


# --- record contracts and hash stability ---------------------------------


def test_a_feature_record_cannot_be_edited_without_resealing() -> None:
    features = features_at(JANUARY, date(2025, 1, 10))
    with pytest.raises(ValidationError, match="features hash"):
        features.model_copy(update={"as_of": features.as_of + timedelta(seconds=1)})
    with pytest.raises(ValidationError, match="features hash"):
        features.model_copy(
            update={
                "month_ordinal_from_start": CalendarCountV1(
                    status="known", value=8, reason=None, blocking_date=None
                )
            }
        )
    with pytest.raises(ValidationError, match="session-relative"):
        features.model_copy(update={"session_status": "closed"})
    forged = CalendarSessionFeaturesV1.model_construct(
        **(features.__dict__ | {"is_third_friday": True})
    )
    with pytest.raises(ValidationError, match="is_third_friday"):
        CalendarSessionFeaturesV1.model_validate(forged.model_dump())


def test_a_known_count_cannot_carry_a_reason() -> None:
    with pytest.raises(ValidationError, match="shape"):
        CalendarCountV1(
            status="known",
            value=3,
            reason="schedule_status_unknown",
            blocking_date=None,
        )
    with pytest.raises(ValidationError, match="blocking date"):
        CalendarCountV1(
            status="indeterminate",
            value=None,
            reason="schedule_status_unknown",
            blocking_date=None,
        )


def test_results_are_independent_of_input_order() -> None:
    requests = tuple(
        request(day, evening_before(day))
        for day in (date(2024, 12, 24), date(2025, 1, 8), date(2025, 1, 31))
    )
    forward = compute(JANUARY_WITH_MOURNING, requests)
    backward = compute(list(reversed(JANUARY_WITH_MOURNING)), requests)
    assert forward == backward
    assert forward.set_hash == backward.set_hash


def test_hashes_are_pinned() -> None:
    assert calendar_feature_algorithm_hash() == PINNED_ALGORITHM_HASH
    features = features_at(JANUARY_WITH_MOURNING, date(2025, 1, 10))
    assert features.features_hash == PINNED_JANUARY_10_FEATURES_HASH


#: Pinned when the V1 contracts were first authored (issue 662). A change to
#: any of these is a contract change and needs a new version, not a re-pin.
PINNED_ALGORITHM_HASH = (
    "69afbc9261420e844745f85e96f4909db2a5daf02f4adc06d6c25da4d5065172"
)
PINNED_TABLE_HASH = "6338e6cdce38c9f9814fee57dae22a71730f391dcf97a5de6408b8985b8d6eac"
PINNED_JANUARY_10_FEATURES_HASH = (
    "b864ee471cd32777937d936f7100fd519bef53a1a63b8bde9b3d8b1bb83163a0"
)
