"""Unit tests for M2 evaluation session and clock contracts/builders."""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from functools import cache
from hashlib import sha256
from struct import pack
from typing import Literal

import action_session_test_support
import pytest
import session_test_support
from observation_test_support import NormalizationHarness, ObservationHarness
from pydantic import ValidationError
from session_test_support import availability, boundary_authority_payload

from drift.datasets.hashing import assertion_version_payload
from drift.datasets.resolver import VerifiedArtifactBytes
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
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.sessions import (
    RealizedSessionVersionV1,
    ScheduleArtifactV1,
    ScheduledSessionVersionV1,
    ScheduleGenerationPolicyV1,
    SessionKeyV1,
)
from drift.evaluator.clock import (
    RealizedSessionLocalDateError,
    SameDateMultiVenueClockError,
    _build_clock,
    _ensure_ordered_unique,
    _session_from_authority,
    build_realized_session_clock,
    build_scheduled_reconstruction_clock,
    refuse_same_date_multi_venue_clock,
    verify_session_clock,
)
from drift.markets.observation_selection import select_observation_records
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
)
from drift.markets.session_generation import generate_schedule
from drift.serialization.canonical import canonical_json, content_hash

H0 = "0" * 64
H1 = "1" * 64
H2 = "2" * 64

JAN5 = date(2026, 1, 5)
JAN6 = date(2026, 1, 6)
OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
CLOSE = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
EARLY_CLOSE = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)


ScheduleStateT = Literal["regular", "early_close", "closed", "unknown"]
RealizedOutcomeT = Literal[
    "opened", "opened_without_bounds", "did_not_open", "unknown", "missing"
]


def _ready_harness(
    *,
    schedule_state: ScheduleStateT = "regular",
    realized_outcome: RealizedOutcomeT = "missing",
) -> ObservationHarness:
    harness = ObservationHarness()
    harness.attach_sessions(
        schedule_state=schedule_state, realized_outcome=realized_outcome
    )
    return harness


def _queries(
    harness: ObservationHarness,
) -> tuple[ObservationOutcomeQueryV1, ...]:
    return (
        harness.outcome(
            economic_horizon="2026-01-06T00:00:00Z",
            evidence_vintage_cutoff="2026-01-06T00:00:00Z",
            session_date="2026-01-05",
        ),
    )


# --- Realized-authority clock ---


def test_realized_clock_uses_exact_actual_bounds() -> None:
    harness = _ready_harness(realized_outcome="opened")
    clock = build_realized_session_clock(_queries(harness), harness.context)
    assert clock.mode == "realized_session_authority"
    assert len(clock.sessions) == 1
    session = clock.sessions[0]
    assert session.authority == "realized"
    assert session.opened_at == datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    assert session.closed_at == datetime(2026, 1, 5, 20, 55, tzinfo=UTC)
    assert session.session_hash == evaluation_session_hash(session)
    assert clock.clock_hash == session_clock_hash(clock)
    assert session.authority_record_hashes
    assert session.authority_proof_hashes


def test_realized_clock_preserves_early_realized_close() -> None:
    harness = _ready_harness(realized_outcome="opened")
    clock = build_realized_session_clock(_queries(harness), harness.context)
    assert clock.sessions[0].closed_at != datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
    assert clock.sessions[0].closed_at == datetime(2026, 1, 5, 20, 55, tzinfo=UTC)


def test_realized_clock_did_not_open_cannot_create_session() -> None:
    harness = _ready_harness(realized_outcome="did_not_open")
    with pytest.raises(ValueError):
        build_realized_session_clock(_queries(harness), harness.context)


def test_realized_clock_unknown_outcome_cannot_create_session() -> None:
    harness = _ready_harness(realized_outcome="unknown")
    with pytest.raises(ValueError):
        build_realized_session_clock(_queries(harness), harness.context)


def test_realized_clock_requires_opened_state_and_bounds() -> None:
    harness = _ready_harness(realized_outcome="opened_without_bounds")
    with pytest.raises(ValueError):
        build_realized_session_clock(_queries(harness), harness.context)


# --- Scheduled reconstruction clock ---


def test_scheduled_clock_uses_generated_boundaries() -> None:
    harness = _ready_harness()
    clock = build_scheduled_reconstruction_clock(_queries(harness), harness.context)
    assert clock.mode == "scheduled_session_reconstruction"
    assert len(clock.sessions) == 1
    session = clock.sessions[0]
    assert session.authority == "scheduled_reconstruction"
    assert session.opened_at == OPEN
    assert session.closed_at == CLOSE
    assert (
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION
        in clock.acknowledged_limitations
    )
    assert ALPACA_LIMITATION_ABSENT_HALTS in clock.acknowledged_limitations
    assert session.session_hash == evaluation_session_hash(session)
    assert clock.clock_hash == session_clock_hash(clock)


def test_scheduled_clock_preserves_early_close() -> None:
    harness = _ready_harness(schedule_state="early_close")
    clock = build_scheduled_reconstruction_clock(_queries(harness), harness.context)
    assert clock.sessions[0].closed_at == EARLY_CLOSE
    assert clock.sessions[0].closed_at != CLOSE


def test_scheduled_clock_closed_day_produces_no_session() -> None:
    harness = _ready_harness(schedule_state="closed")
    with pytest.raises(ValueError):
        build_scheduled_reconstruction_clock(_queries(harness), harness.context)


def test_scheduled_clock_unknown_schedule_fails_closed() -> None:
    harness = _ready_harness(schedule_state="unknown")
    with pytest.raises(ValueError):
        build_scheduled_reconstruction_clock(_queries(harness), harness.context)


def test_scheduled_clock_fabricates_no_realized_sessions() -> None:
    harness = _ready_harness()
    clock = build_scheduled_reconstruction_clock(_queries(harness), harness.context)
    records = clock.sessions[0].authority_record_hashes
    assert isinstance(records, tuple)
    for digest in records:
        for dataset in harness.context.session_datasets:
            for record in dataset.records:
                if isinstance(record, RealizedSessionVersionV1):
                    assert content_hash_local(record) != digest


def content_hash_local(record: object) -> str:
    from drift.serialization.canonical import content_hash

    return content_hash(record)


def test_clock_round_trip_determinism() -> None:
    first = build_scheduled_reconstruction_clock(
        _queries(_ready_harness()), _ready_harness().context
    )
    second = build_scheduled_reconstruction_clock(
        _queries(_ready_harness()), _ready_harness().context
    )
    assert first.clock_hash == second.clock_hash


def test_clock_boundary_change_changes_hash() -> None:
    regular = build_scheduled_reconstruction_clock(
        _queries(_ready_harness()), _ready_harness().context
    )
    early = build_scheduled_reconstruction_clock(
        _queries(_ready_harness(schedule_state="early_close")),
        _ready_harness(schedule_state="early_close").context,
    )
    assert regular.clock_hash != early.clock_hash


# --- Session and clock contract shape ---


def make_session(
    local_date: date = JAN5,
    opened: datetime = OPEN,
    closed: datetime = CLOSE,
    authority: str = "scheduled_reconstruction",
    mic: str = "XNYS",
) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=SessionKeyV1(
            mic=mic, session_scope="regular", local_date=local_date
        ),
        opened_at=opened,
        closed_at=closed,
        authority=authority,
        authority_record_hashes=(H1,),
        authority_proof_hashes=(H2,),
        session_hash=H0,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def test_session_requires_close_after_open() -> None:
    payload = make_session().model_dump(mode="python")
    payload["closed_at"] = payload["opened_at"]
    payload["session_hash"] = H0
    with pytest.raises(ValidationError, match="close must follow open"):
        EvaluationSessionV1.model_validate(payload)


def test_session_tampered_hash_rejected() -> None:
    payload = make_session().model_dump(mode="python")
    payload["session_hash"] = H1
    with pytest.raises(ValidationError, match="session hash mismatch"):
        EvaluationSessionV1.model_validate(payload)


def test_clock_rejects_duplicate_or_unordered_sessions() -> None:
    first = make_session()
    second = make_session(
        local_date=JAN6,
        opened=datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
        closed=datetime(2026, 1, 6, 21, 0, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="unique session keys"):
        SessionClockV1.model_validate(
            {
                "schema_version": "1",
                "mode": "scheduled_session_reconstruction",
                "sessions": (first, first),
                "acknowledged_limitations": (
                    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                    ALPACA_LIMITATION_ABSENT_HALTS,
                ),
                "clock_hash": H0,
            }
        )
    with pytest.raises(ValidationError, match="chronological"):
        SessionClockV1.model_validate(
            {
                "schema_version": "1",
                "mode": "scheduled_session_reconstruction",
                "sessions": (second, first),
                "acknowledged_limitations": (
                    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                    ALPACA_LIMITATION_ABSENT_HALTS,
                ),
                "clock_hash": H0,
            }
        )


def test_clock_is_frozen_and_state_hash_verified() -> None:
    harness = _ready_harness()
    clock = build_scheduled_reconstruction_clock(_queries(harness), harness.context)
    with pytest.raises(ValidationError):
        clock.mode = "realized_session_authority"
    payload = clock.model_dump(mode="python")
    payload["clock_hash"] = H1
    with pytest.raises(ValidationError, match="clock hash mismatch"):
        SessionClockV1.model_validate(payload)


def _validated_scheduled_clock(
    sessions: tuple[EvaluationSessionV1, ...],
) -> SessionClockV1:
    limitations = (
        ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
        ALPACA_LIMITATION_ABSENT_HALTS,
    )
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="scheduled_session_reconstruction",
        sessions=sessions,
        acknowledged_limitations=limitations,
        clock_hash=H0,
    )
    hashed = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(hashed.model_dump(mode="python"))


def test_clock_accepts_utc_order_when_mic_order_disagrees() -> None:
    earlier = make_session(mic="ZZZZ", local_date=JAN5, opened=OPEN, closed=CLOSE)
    later = make_session(
        mic="AAAA",
        local_date=JAN6,
        opened=datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
        closed=datetime(2026, 1, 6, 21, 0, tzinfo=UTC),
    )
    clock = _validated_scheduled_clock((earlier, later))
    assert tuple(session.session_key.mic for session in clock.sessions) == (
        "ZZZZ",
        "AAAA",
    )
    with pytest.raises(ValidationError, match="chronological"):
        _validated_scheduled_clock((later, earlier))


# --- Non-overlap and local-date coherence (issue 84) ---


SCHEDULED_LIMITATIONS = (
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ALPACA_LIMITATION_ABSENT_HALTS,
)


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


#: Clock-ordered session pairs whose second member opens before the first
#: closes. The second is the #66 case: XNAS opens first and closes after the
#: XNYS early close on the same local date.
OVERLAPPING_PAIRS = {
    "next-date-opens-inside-the-prior-session": (
        make_session(),
        make_session(local_date=JAN6, opened=_utc(JAN5, 20), closed=_utc(JAN6, 21)),
    ),
    "same-date-venue-closes-after-the-next-opens": (
        make_session(
            mic="XNAS",
            local_date=JAN6,
            opened=_utc(JAN6, 13, 30),
            closed=_utc(JAN6, 21),
        ),
        make_session(local_date=JAN6, opened=_utc(JAN6, 14, 30), closed=_utc(JAN6, 18)),
    ),
}

#: Clock-ordered session pairs whose local dates run backwards. Each is in
#: UTC boundary order and does not overlap, so only the date guard refuses it.
DATE_INVERTED_PAIRS = {
    "same-venue": (
        make_session(local_date=JAN6),
        make_session(local_date=JAN5, opened=_utc(JAN6, 14, 30), closed=_utc(JAN6, 21)),
    ),
    "across-venues": (
        make_session(mic="XNAS", local_date=JAN6),
        make_session(local_date=JAN5, opened=_utc(JAN6, 14, 30), closed=_utc(JAN6, 21)),
    ),
}


@pytest.mark.parametrize("pair", OVERLAPPING_PAIRS.values(), ids=OVERLAPPING_PAIRS)
def test_clock_refuses_a_session_opening_before_the_prior_one_closes(
    pair: tuple[EvaluationSessionV1, EvaluationSessionV1],
) -> None:
    """The non-overlap guard is what makes clock order a causal order.

    With it, every stepped session has closed by the time the next one opens,
    so the stepped prefix is exactly the closed history (#66) and the next
    clock session opens after the decision it executes.
    """
    with pytest.raises(
        ValidationError, match="session clock sessions must not overlap"
    ):
        _validated_scheduled_clock(pair)


def test_clock_accepts_a_session_opening_exactly_at_the_prior_close() -> None:
    touching = make_session(local_date=JAN6, opened=CLOSE, closed=_utc(JAN6, 21))

    clock = _validated_scheduled_clock((make_session(), touching))

    assert clock.sessions[1].opened_at == clock.sessions[0].closed_at


@pytest.mark.parametrize("pair", DATE_INVERTED_PAIRS.values(), ids=DATE_INVERTED_PAIRS)
def test_clock_refuses_local_dates_running_backwards_in_clock_order(
    pair: tuple[EvaluationSessionV1, EvaluationSessionV1],
) -> None:
    """A session keyed on an earlier date cannot be stamped after a later one."""
    with pytest.raises(
        ValidationError,
        match="session clock local dates must not decrease in clock order",
    ):
        _validated_scheduled_clock(pair)


def test_clock_accepts_one_local_date_on_two_venues_in_turn() -> None:
    """Across venues, local dates need only be non-decreasing."""
    first = make_session(
        local_date=JAN6, opened=_utc(JAN6, 14, 30), closed=_utc(JAN6, 18)
    )
    second = make_session(
        mic="XNAS", local_date=JAN6, opened=_utc(JAN6, 18, 30), closed=_utc(JAN6, 21)
    )

    clock = _validated_scheduled_clock((first, second))

    assert [session.session_key.mic for session in clock.sessions] == ["XNYS", "XNAS"]


def test_clock_refuses_one_local_date_twice_on_one_venue() -> None:
    """Per venue, local dates strictly increase, because keys are unique."""
    first = make_session(
        local_date=JAN6, opened=_utc(JAN6, 14, 30), closed=_utc(JAN6, 18)
    )
    second = make_session(
        local_date=JAN6, opened=_utc(JAN6, 18, 30), closed=_utc(JAN6, 21)
    )

    with pytest.raises(ValidationError, match="unique session keys"):
        _validated_scheduled_clock((first, second))


# --- Same-date multi-venue clocks are not evaluated (issue 97) ---


#: Each clock mode with the session authority and limitations it requires.
CLOCK_MODES: dict[str, tuple[SessionClockMode, str, tuple[str, ...]]] = {
    "realized": ("realized_session_authority", "realized", ()),
    "scheduled": (
        "scheduled_session_reconstruction",
        "scheduled_reconstruction",
        SCHEDULED_LIMITATIONS,
    ),
}


def _clock_in(
    mode_case: tuple[SessionClockMode, str, tuple[str, ...]],
    sessions: tuple[tuple[str, date, datetime, datetime], ...],
) -> SessionClockV1:
    """A validated clock of one mode over (MIC, local date, open, close) rows."""
    mode, authority, limitations = mode_case
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode=mode,
        sessions=tuple(
            make_session(
                mic=mic,
                local_date=day,
                opened=opened,
                closed=closed,
                authority=authority,
            )
            for mic, day, opened, closed in sessions
        ),
        acknowledged_limitations=tuple(sorted(limitations)),
        clock_hash=H0,
    )
    hashed = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(hashed.model_dump(mode="python"))


#: Clocks `SessionClockV1` admits (above) with two or more venues trading on
#: one local date, which the issue 97 ruling refuses to run. Each names the
#: pair the refusal reports: the first session on the date, then the second.
#: The venue order varies, so no MIC ordering can stand in for the date.
SAME_DATE_MULTI_VENUE_ROWS: dict[
    str, tuple[tuple[tuple[str, date, datetime, datetime], ...], tuple[str, str]]
] = {
    "xnys-then-xnas": (
        (
            ("XNYS", JAN5, OPEN, CLOSE),
            ("XNYS", JAN6, _utc(JAN6, 14, 30), _utc(JAN6, 18)),
            ("XNAS", JAN6, _utc(JAN6, 18, 30), _utc(JAN6, 21)),
        ),
        ("XNYS", "XNAS"),
    ),
    "xnas-then-xnys": (
        (
            ("XNYS", JAN5, OPEN, CLOSE),
            ("XNAS", JAN6, _utc(JAN6, 14, 30), _utc(JAN6, 18)),
            ("XNYS", JAN6, _utc(JAN6, 18, 30), _utc(JAN6, 21)),
        ),
        ("XNAS", "XNYS"),
    ),
    "three-venues-on-one-date": (
        (
            ("XNAS", JAN6, _utc(JAN6, 13), _utc(JAN6, 14)),
            ("XNYS", JAN6, _utc(JAN6, 14, 30), _utc(JAN6, 18)),
            ("ARCX", JAN6, _utc(JAN6, 18, 30), _utc(JAN6, 21)),
        ),
        ("XNAS", "XNYS"),
    ),
}

#: Clocks with one session per local date, which the ruling leaves unchanged.
ONE_SESSION_PER_DATE_ROWS = {
    "one-session": (("XNYS", JAN5, OPEN, CLOSE),),
    "one-venue": (
        ("XNYS", JAN5, OPEN, CLOSE),
        ("XNYS", JAN6, _utc(JAN6, 14, 30), _utc(JAN6, 21)),
    ),
    "two-venues-on-distinct-dates": (
        ("XNYS", JAN5, OPEN, CLOSE),
        ("XNAS", JAN6, _utc(JAN6, 14, 30), _utc(JAN6, 21)),
    ),
}


@pytest.mark.parametrize(
    "case", SAME_DATE_MULTI_VENUE_ROWS.values(), ids=SAME_DATE_MULTI_VENUE_ROWS
)
@pytest.mark.parametrize("mode_case", CLOCK_MODES.values(), ids=CLOCK_MODES)
def test_a_same_date_multi_venue_clock_is_refused_for_evaluation(
    mode_case: tuple[SessionClockMode, str, tuple[str, ...]],
    case: tuple[tuple[tuple[str, date, datetime, datetime], ...], tuple[str, str]],
) -> None:
    """Issue 97 ruling, option A: refused by name, in either clock mode.

    The clock model admits the shape; only the evaluation guard refuses it.
    Dates are compared across venues: on one venue they already differ.
    """
    rows, (first_mic, second_mic) = case
    clock = _clock_in(mode_case, rows)
    assert [session.session_key.mic for session in clock.sessions] == [
        mic for mic, *_ in rows
    ]

    with pytest.raises(
        SameDateMultiVenueClockError,
        match=(
            "^"
            + re.escape(
                "the session clock steps two sessions on local date 2026-01-06, "
                f"{first_mic} then {second_mic}: next-open execution requires a "
                "later local date, so a same-date multi-venue clock is refused "
                "at engine construction (issue 97 ruling)"
            )
            + "$"
        ),
    ):
        refuse_same_date_multi_venue_clock(clock)
    assert issubclass(SameDateMultiVenueClockError, ValueError)


@pytest.mark.parametrize(
    "rows", ONE_SESSION_PER_DATE_ROWS.values(), ids=ONE_SESSION_PER_DATE_ROWS
)
@pytest.mark.parametrize("mode_case", CLOCK_MODES.values(), ids=CLOCK_MODES)
def test_a_clock_with_one_session_per_local_date_is_evaluated(
    mode_case: tuple[SessionClockMode, str, tuple[str, ...]],
    rows: tuple[tuple[str, date, datetime, datetime], ...],
) -> None:
    """Control: single-venue clocks, and a venue change across dates, pass."""
    refuse_same_date_multi_venue_clock(_clock_in(mode_case, rows))


@pytest.mark.parametrize("pair", OVERLAPPING_PAIRS.values(), ids=OVERLAPPING_PAIRS)
def test_the_clock_builders_refuse_overlapping_sessions(
    pair: tuple[EvaluationSessionV1, EvaluationSessionV1],
) -> None:
    """Both builder layers refuse overlap: their own guard and the model gate."""
    with pytest.raises(ValueError, match=r"^session clock sessions must not overlap$"):
        _ensure_ordered_unique(pair)
    with pytest.raises(
        ValidationError, match="session clock sessions must not overlap"
    ):
        _build_clock(
            mode="scheduled_session_reconstruction",
            sessions=pair,
            limitations=SCHEDULED_LIMITATIONS,
        )


@pytest.mark.parametrize("pair", DATE_INVERTED_PAIRS.values(), ids=DATE_INVERTED_PAIRS)
def test_the_clock_builders_refuse_local_dates_running_backwards(
    pair: tuple[EvaluationSessionV1, EvaluationSessionV1],
) -> None:
    with pytest.raises(
        ValidationError,
        match="session clock local dates must not decrease in clock order",
    ):
        _build_clock(
            mode="scheduled_session_reconstruction",
            sessions=pair,
            limitations=SCHEDULED_LIMITATIONS,
        )


def test_scheduled_clock_rejects_selected_source_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mismatched(
        query: ObservationOutcomeQueryV1,
        context: M1dResolutionContext,
        policy: ScheduleGenerationPolicyV1,
    ) -> ScheduleArtifactV1:
        artifact = generate_schedule(query, context, policy)
        row = artifact.rows[0]
        bad_row = row.model_copy(update={"source_version_hash": "ab" * 32})
        return artifact.model_copy(update={"rows": (bad_row, *artifact.rows[1:])})

    monkeypatch.setattr("drift.evaluator.clock.generate_schedule", mismatched)
    harness = _ready_harness()
    with pytest.raises(ValueError, match="independently selected scheduled session"):
        build_scheduled_reconstruction_clock(_queries(harness), harness.context)


def test_scheduled_clock_mode_requires_scheduled_limitations() -> None:
    payload = make_session().model_dump(mode="python")
    clock_payload = {
        "schema_version": "1",
        "mode": "scheduled_session_reconstruction",
        "sessions": (payload,),
        "acknowledged_limitations": (),
        "clock_hash": H0,
    }
    with pytest.raises(ValidationError, match="clock lacks limitations"):
        SessionClockV1.model_validate(clock_payload)


# --- Realized stamps belong to their local date (issue 140) ---

#: Moved realized stamps: (local date, actual open, actual close) per record.
RealizedStamps = tuple[tuple[date, datetime, datetime], ...]

NOV25 = date(2026, 11, 25)
NOV26 = date(2026, 11, 26)
NOV27 = date(2026, 11, 27)
NOV30 = date(2026, 11, 30)
DEC1 = date(2026, 12, 1)

#: The open dates of the prior-open action corpus, each with a realized record:
#: a regular session, the 2026-11-27 early close, and another regular session.
CORPUS_DATES = (NOV25, NOV27, NOV30)

#: The issue 140 probe: the issue 95 lag moved into the M1d source records.
#: 2026-11-27 carries 2026-11-30's regular hours and 2026-11-30 carries
#: 2026-12-01's, while 2026-11-25 keeps its own.
LAGGED_RECORD_STAMPS: RealizedStamps = (
    (NOV27, _utc(NOV30, 14, 30), _utc(NOV30, 21)),
    (NOV30, _utc(DEC1, 14, 30), _utc(DEC1, 21)),
)

#: One stamp moved per open date. The corpus venue is on UTC-5 in late
#: November, so 2026-11-25 closes at 20:00 local, past UTC midnight yet on its
#: own date; 2026-11-27 opens at 23:00 local the evening before, on its own
#: UTC date; and 2026-11-30 closes at 00:30 local the next day.
ONE_STAMP_RECORD_STAMPS: RealizedStamps = (
    (NOV25, _utc(NOV25, 14, 30), _utc(NOV26, 1)),
    (NOV27, _utc(NOV27, 4), _utc(NOV27, 18)),
    (NOV30, _utc(NOV30, 14, 30), _utc(DEC1, 5, 30)),
)


def _restamping(stamps: RealizedStamps) -> Callable[..., RealizedSessionVersionV1]:
    """Wrap the action corpus's realized-record builder to move chosen stamps.

    Each named open date gets the given actual open and close, and its
    availability moves to five minutes after that close, as the genuine
    records' does, so only the stamps differ from the genuine corpus.
    """
    moved: Mapping[date, tuple[datetime, datetime]] = {
        day: (opened, closed) for day, opened, closed in stamps
    }
    original = action_session_test_support._realized_session

    def restamped(
        local_date: date, *, opened: bool, suffix: int
    ) -> RealizedSessionVersionV1:
        record = original(local_date, opened=opened, suffix=suffix)
        if local_date not in moved or not opened:
            return record
        actual_open, actual_close = moved[local_date]
        available_at = actual_close + timedelta(minutes=5)
        evidence = record.revision.availability[0].model_copy(
            update={
                "lower_bound": available_at,
                "upper_bound": available_at,
                "source_time_label": available_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        revision = record.revision.model_copy(
            update={"availability": (evidence,), "payload_hash": "0" * 64}
        )
        values = dict(record) | {
            "revision": revision,
            "actual_open": actual_open,
            "actual_close": actual_close,
        }
        provisional = RealizedSessionVersionV1.model_construct(**values)
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        return RealizedSessionVersionV1.model_validate(values)

    return restamped


@cache
def restamped_realized_corpus(stamps: RealizedStamps) -> NormalizationHarness:
    """The genuine prior-open action corpus with the given realized stamps moved.

    Every other byte comes from the builders of the genuine corpus, so the
    selection policy, coverage and validation decisions are genuine, and M1d
    accepts the moved records. With no stamps moved it is the genuine corpus.
    Cached because each corpus is only read.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            action_session_test_support, "_realized_session", _restamping(stamps)
        )
        return NormalizationHarness(include_prior_open=True)


def restamped_corpus_queries(
    harness: NormalizationHarness, *dates: date
) -> tuple[ObservationOutcomeQueryV1, ...]:
    """One session query per requested date over a restamped corpus."""
    return tuple(
        harness.source.outcome(
            economic_horizon="2026-12-02T00:00:00Z",
            evidence_vintage_cutoff="2026-12-02T00:00:00Z",
            session_date=day.isoformat(),
        ).model_copy(
            update={
                "source_selection_policy_hash": harness._source_policy_hash,
                "input_context_hash": m1d_context_hash(harness.context),
            }
        )
        for day in dates
    )


def pre_issue_140_realized_clock(
    queries: tuple[ObservationOutcomeQueryV1, ...], context: M1dResolutionContext
) -> SessionClockV1:
    """The realized clock the builder derived before issue 140.

    It is the canonical derivation without the local-date guard: each selected
    record's exact bounds, record hash and selection proof. It is the clock a
    misdated record used to mint, and what a genuine build must still equal.
    """
    sessions: list[EvaluationSessionV1] = []
    for query in queries:
        selected = select_observation_records(query, "realized_session", context)
        (record,) = selected.records
        assert isinstance(record, RealizedSessionVersionV1)
        assert record.actual_open is not None and record.actual_close is not None
        sessions.append(
            _session_from_authority(
                session_key=record.session_key,
                opened_at=record.actual_open,
                closed_at=record.actual_close,
                authority="realized",
                record_hashes=(content_hash(record),),
                proof_hashes=(content_hash(selected.proof),),
            )
        )
    return _build_clock(
        mode="realized_session_authority", sessions=tuple(sessions), limitations=()
    )


def off_date_refusal(session_date: str, boundary: str, stamp: str, local: str) -> str:
    """The issue 140 refusal of one stamp, as an anchored pattern."""
    return (
        "^"
        + re.escape(
            f"realized session XNYS {session_date} actual {boundary} {stamp} "
            f"falls on venue local date {local}, not its session date (issue 140)"
        )
        + "$"
    )


#: Records M1d accepts whose stamp falls off their local date: the stamps
#: moved, the dates queried, and the refusal (session date, boundary, UTC
#: stamp, and the venue local date that stamp falls on). The probe refuses at
#: its first misdated record; the others move one record, or one stamp alone.
OFF_DATE_CASES: dict[
    str, tuple[RealizedStamps, tuple[date, ...], tuple[str, str, str, str]]
] = {
    "days-late-the-issue-140-probe": (
        LAGGED_RECORD_STAMPS,
        CORPUS_DATES,
        ("2026-11-27", "open", "2026-11-30T14:30:00+00:00", "2026-11-30"),
    ),
    "one-day-late": (
        LAGGED_RECORD_STAMPS,
        (NOV30,),
        ("2026-11-30", "open", "2026-12-01T14:30:00+00:00", "2026-12-01"),
    ),
    "only-the-open-on-the-evening-before": (
        ONE_STAMP_RECORD_STAMPS,
        (NOV27,),
        ("2026-11-27", "open", "2026-11-27T04:00:00+00:00", "2026-11-26"),
    ),
    "only-the-close-after-local-midnight": (
        ONE_STAMP_RECORD_STAMPS,
        (NOV30,),
        ("2026-11-30", "close", "2026-12-01T05:30:00+00:00", "2026-12-01"),
    ),
}


@pytest.mark.parametrize("case", OFF_DATE_CASES.values(), ids=OFF_DATE_CASES)
def test_a_realized_record_stamped_off_its_local_date_is_refused(
    case: tuple[RealizedStamps, tuple[date, ...], tuple[str, str, str, str]],
) -> None:
    """Issue 140: each stamp must fall on its record's venue local date.

    The records pass M1d, and the clock derived from them before issue 140 is
    valid on its own and carries the moved stamp. The builder now refuses the
    record, and verification, which rebuilds, refuses that clock for the same
    reason.
    """
    stamps, dates, (session_date, boundary, stamp, local) = case
    corpus = restamped_realized_corpus(stamps)
    queries = restamped_corpus_queries(corpus, *dates)
    misdated = pre_issue_140_realized_clock(queries, corpus.context)
    (session,) = (
        item
        for item in misdated.sessions
        if item.session_key.local_date.isoformat() == session_date
    )
    moved = session.opened_at if boundary == "open" else session.closed_at
    assert moved.isoformat() == stamp

    refusal = off_date_refusal(session_date, boundary, stamp, local)
    with pytest.raises(RealizedSessionLocalDateError, match=refusal):
        build_realized_session_clock(queries, corpus.context)
    with pytest.raises(RealizedSessionLocalDateError, match=refusal):
        verify_session_clock(misdated, queries, corpus.context)
    assert issubclass(RealizedSessionLocalDateError, ValueError)


def test_a_realized_close_past_utc_midnight_on_its_local_date_is_admitted() -> None:
    """Control: the venue's local date governs, never the UTC date.

    2026-11-25 closes at 01:00Z on 2026-11-26, which is 20:00 on 2026-11-25 at
    the venue, so the record builds exactly as it did before issue 140.
    """
    corpus = restamped_realized_corpus(ONE_STAMP_RECORD_STAMPS)
    queries = restamped_corpus_queries(corpus, NOV25)

    clock = build_realized_session_clock(queries, corpus.context)

    assert clock == pre_issue_140_realized_clock(queries, corpus.context)
    (session,) = clock.sessions
    assert session.closed_at == _utc(NOV26, 1)
    verify_session_clock(clock, queries, corpus.context)


def test_genuine_realized_clocks_are_unchanged_by_the_local_date_guard() -> None:
    """Control: the guard only refuses, so a genuine clock is byte-identical."""
    corpus = restamped_realized_corpus(())
    queries = restamped_corpus_queries(corpus, *CORPUS_DATES)
    clock = build_realized_session_clock(queries, corpus.context)
    assert clock == pre_issue_140_realized_clock(queries, corpus.context)
    assert tuple(item.session_key.local_date for item in clock.sessions) == (
        CORPUS_DATES
    )
    verify_session_clock(clock, queries, corpus.context)

    harness = _ready_harness(realized_outcome="opened")
    single = build_realized_session_clock(_queries(harness), harness.context)
    assert single == pre_issue_140_realized_clock(_queries(harness), harness.context)


@pytest.mark.parametrize(
    ("schedule_state", "detail"),
    [
        ("closed", "schedule artifact generated, state closed"),
        ("unknown", "schedule artifact indeterminate, state unknown"),
    ],
)
def test_a_realized_record_without_authorized_venue_time_is_refused(
    schedule_state: ScheduleStateT, detail: str
) -> None:
    """Issue 140 fails closed without the venue's authorized local time.

    The authorized generated schedule row of the session key is the venue
    local time M1d holds. A realized opening on a date whose calendar row is
    closed, or unknown, has no authorized boundary offset, so its stamps cannot
    be placed on its date, however ordinary they look.
    """
    harness = _ready_harness(schedule_state=schedule_state, realized_outcome="opened")
    queries = _queries(harness)
    (session,) = pre_issue_140_realized_clock(queries, harness.context).sessions
    assert session.opened_at == datetime(2026, 1, 5, 14, 35, tzinfo=UTC)

    with pytest.raises(
        RealizedSessionLocalDateError,
        match=(
            "^"
            + re.escape(
                "realized session XNYS 2026-01-05 cannot be placed in venue local "
                "time: its session key has no authorized generated open and close "
                f"({detail}) (issue 140)"
            )
            + "$"
        ),
    ):
        build_realized_session_clock(queries, harness.context)


# --- An in-session DST transition (issue 140, PR 144 review F1) ---

EST_OFFSET = -18_000
EDT_OFFSET = -14_400

#: The in-session corpus springs forward at 2026-11-30 17:00Z, which is 12:00
#: EST, inside that date's 09:30 to 16:00 session, so the session opens at
#: UTC-5 and closes at UTC-4. Every earlier corpus instant keeps UTC-5, and the
#: corpus falls back only long after the last instant it holds.
IN_SESSION_SPRING_FORWARD = _utc(NOV30, 17)
IN_SESSION_FALL_BACK = _utc(date(2026, 12, 15), 6)


def in_session_dst_timezone_bytes(*, summer_offset_seconds: int = EDT_OFFSET) -> bytes:
    """The corpus TZif v1 with both transitions moved to the 2026 year end.

    It has the layout of ``session_test_support.timezone_bytes``, so it
    replaces that function while the in-session corpus is built.
    """
    transitions = (
        int(IN_SESSION_SPRING_FORWARD.timestamp()),
        int(IN_SESSION_FALL_BACK.timestamp()),
    )
    abbreviations = b"EST\0EDT\0"
    header = (
        b"TZif\0"
        + (b"\0" * 15)
        + pack(">6l", 0, 0, 0, len(transitions), 2, len(abbreviations))
    )
    transition_table = b"".join(pack(">l", value) for value in transitions)
    local_time_types = pack(">lbb", EST_OFFSET, 0, 0) + pack(
        ">lbb", summer_offset_seconds, 1, 4
    )
    return header + transition_table + bytes((1, 0)) + local_time_types + abbreviations


def _in_session_dst_schedules(
    original: Callable[..., ScheduledSessionVersionV1],
) -> Callable[..., ScheduledSessionVersionV1]:
    """Wrap the corpus schedule builder to authorize the 2026-11-30 UTC-4 close.

    The builder asserts one offset for both boundaries of a row. Across the
    in-session transition the close is at UTC-4, so the 2026-11-30 close gets
    its own authority artifact stating that offset, available when the open's
    is, and the row is resealed. Every other row is the genuine one.
    """

    def schedule(
        local_date: date,
        state: ScheduleStateT,
        methodology_hash: str,
        support: dict[str, VerifiedArtifactBytes],
        retained: dict[str, object],
        **options: object,
    ) -> ScheduledSessionVersionV1:
        record = original(
            local_date, state, methodology_hash, support, retained, **options
        )
        if local_date != NOV30:
            return record
        opening, closing = record.historical_boundary_offsets
        assert (opening.boundary, closing.boundary) == ("open", "close")
        assert record.local_close is not None
        payload = canonical_json(
            boundary_authority_payload(
                local_date, "close", record.local_close, EDT_OFFSET
            )
        )
        payload_hash = sha256(payload).hexdigest()
        evidence = availability(evidence_digest=payload_hash)
        evidence_hash = content_hash(evidence)
        support[payload_hash] = VerifiedArtifactBytes(
            data=payload, byte_size=len(payload), content_hash=payload_hash
        )
        retained[evidence_hash] = evidence
        close = closing.model_copy(
            update={
                "utc_offset_seconds": EDT_OFFSET,
                "authority_artifact_hash": payload_hash,
                "authority_availability_evidence_hash": evidence_hash,
            }
        )
        revision = record.revision.model_copy(update={"payload_hash": "0" * 64})
        values = dict(record) | {
            "revision": revision,
            "historical_boundary_offsets": (opening, close),
        }
        provisional = ScheduledSessionVersionV1.model_construct(**values)
        values["revision"] = revision.model_copy(
            update={
                "payload_hash": content_hash(assertion_version_payload(provisional))
            }
        )
        return ScheduledSessionVersionV1.model_validate(values)

    return schedule


@cache
def in_session_dst_realized_corpus(stamps: RealizedStamps) -> NormalizationHarness:
    """The restamped corpus over a venue that springs forward mid-session.

    Only the TZif and the 2026-11-30 schedule row differ from the genuine
    corpus, so the schedule generation that authorizes each boundary's offset
    is the genuine pipeline. Cached because each corpus is only read.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            session_test_support, "timezone_bytes", in_session_dst_timezone_bytes
        )
        patch.setattr(
            action_session_test_support,
            "schedule_record",
            # The action corpus imports it from here, so this is the same builder.
            _in_session_dst_schedules(session_test_support.schedule_record),
        )
        patch.setattr(
            action_session_test_support, "_realized_session", _restamping(stamps)
        )
        return NormalizationHarness(include_prior_open=True)


#: Stamps where the 2026-11-30 open's UTC-5 and close's UTC-4 disagree on the
#: local date: the stamps moved, and the refusal (boundary, UTC stamp, and
#: the venue local date at that boundary's own offset). 04:30Z on 2026-12-01
#: is 00:30 the next day at the close's UTC-4, but 23:30 on the session date
#: at the open's UTC-5; 04:30Z on 2026-11-30 is 23:30 the day before at the
#: open's UTC-5, but 00:30 on the session date at the close's UTC-4.
IN_SESSION_DST_CASES: dict[str, tuple[RealizedStamps, tuple[str, str, str]]] = {
    "the-close-read-at-its-own-utc-4": (
        ((NOV30, _utc(NOV30, 14, 30), _utc(DEC1, 4, 30)),),
        ("close", "2026-12-01T04:30:00+00:00", "2026-12-01"),
    ),
    "the-open-read-at-its-own-utc-5": (
        ((NOV30, _utc(NOV30, 4, 30), _utc(NOV30, 21)),),
        ("open", "2026-11-30T04:30:00+00:00", "2026-11-29"),
    ),
}


def test_the_in_session_dst_corpus_authorizes_two_offsets_for_one_session() -> None:
    """The corpus is non-vacuous: one session, two authorized offsets.

    The scheduled clock over the genuine pipeline opens 2026-11-30 at 14:30Z,
    09:30 at UTC-5, and closes it at 20:00Z, 16:00 at UTC-4, so a check that
    read both stamps at one boundary's offset would misplace the other.
    """
    corpus = in_session_dst_realized_corpus(())
    (session,) = build_scheduled_reconstruction_clock(
        restamped_corpus_queries(corpus, NOV30), corpus.context
    ).sessions
    assert session.opened_at == _utc(NOV30, 14, 30)
    assert session.closed_at == _utc(NOV30, 20)


@pytest.mark.parametrize(
    "case", IN_SESSION_DST_CASES.values(), ids=IN_SESSION_DST_CASES
)
def test_each_stamp_is_read_at_its_own_offset_across_an_in_session_transition(
    case: tuple[RealizedStamps, tuple[str, str, str]],
) -> None:
    """Issue 140: the open is placed at the open's offset, the close at the close's.

    On 2026-11-30 the venue springs forward mid-session. Each stamp below is
    on the session date at the other boundary's offset and off it at its own,
    so reading the close at the open's offset, or the open at the close's,
    admits it. Both the build and verification refuse it.
    """
    stamps, (boundary, stamp, local) = case
    corpus = in_session_dst_realized_corpus(stamps)
    queries = restamped_corpus_queries(corpus, NOV30)
    misdated = pre_issue_140_realized_clock(queries, corpus.context)
    (session,) = misdated.sessions
    moved = session.opened_at if boundary == "open" else session.closed_at
    assert moved.isoformat() == stamp

    refusal = off_date_refusal("2026-11-30", boundary, stamp, local)
    with pytest.raises(RealizedSessionLocalDateError, match=refusal):
        build_realized_session_clock(queries, corpus.context)
    with pytest.raises(RealizedSessionLocalDateError, match=refusal):
        verify_session_clock(misdated, queries, corpus.context)


@pytest.mark.parametrize(
    "stamps",
    [(), ((NOV30, _utc(NOV30, 5, 30), _utc(DEC1, 3, 30)),)],
    ids=["genuine", "both-stamps-within-an-hour-of-local-midnight"],
)
def test_an_in_session_transition_admits_stamps_on_their_local_date(
    stamps: RealizedStamps,
) -> None:
    """Control: across the transition, on-date stamps build unchanged.

    05:30Z on 2026-11-30 is 00:30 at the open's UTC-5, and 03:30Z on
    2026-12-01 is 23:30 at the close's UTC-4, both on the session date though
    the close is on the next UTC date.
    """
    corpus = in_session_dst_realized_corpus(stamps)
    queries = restamped_corpus_queries(corpus, *CORPUS_DATES)

    clock = build_realized_session_clock(queries, corpus.context)

    assert clock == pre_issue_140_realized_clock(queries, corpus.context)
    assert tuple(item.session_key.local_date for item in clock.sessions) == (
        CORPUS_DATES
    )
    verify_session_clock(clock, queries, corpus.context)
