"""Unit tests for M2 evaluation session and clock contracts/builders."""

from datetime import UTC, date, datetime
from typing import Literal

import pytest
from observation_test_support import ObservationHarness
from pydantic import ValidationError

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
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
    ScheduleGenerationPolicyV1,
    SessionKeyV1,
)
from drift.evaluator.clock import (
    _build_clock,
    _ensure_ordered_unique,
    build_realized_session_clock,
    build_scheduled_reconstruction_clock,
)
from drift.markets.observation_validation import M1dResolutionContext
from drift.markets.session_generation import generate_schedule

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
