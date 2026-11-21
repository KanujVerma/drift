"""M2 session clock contracts over realized or scheduled-reconstruction authority."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.common import (
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
)
from drift.domain.securities import ListingVenue
from drift.domain.sessions import SessionKeyV1
from drift.serialization.canonical import content_hash

type SessionClockMode = Literal[
    "realized_session_authority",
    "scheduled_session_reconstruction",
]


def evaluation_session_hash(session: EvaluationSessionV1) -> SHA256Hash:
    """Compute the canonical content hash for EvaluationSessionV1."""
    dump = session.model_dump(mode="python")
    dump.pop("session_hash", None)
    return content_hash(dump)


def session_clock_hash(clock: SessionClockV1) -> SHA256Hash:
    """Compute the canonical content hash for SessionClockV1."""
    dump = clock.model_dump(mode="python")
    dump.pop("clock_hash", None)
    return content_hash(dump)


def session_order_key(session: EvaluationSessionV1) -> tuple[object, ...]:
    """Canonical chronological ordering key for evaluation sessions.

    Ordering follows actual UTC session boundaries first. Local date, venue
    MIC, and session scope break only boundary ties, in that order. MIC never
    precedes time, so a venue change across dates stays chronological.
    """
    return (
        session.opened_at,
        session.closed_at,
        session.session_key.local_date,
        session.session_key.mic,
        session.session_key.session_scope,
    )


class EvaluationSessionV1(FrozenModel):
    """One evaluation session with exact boundary and bound authority evidence."""

    schema_version: Literal["1"] = "1"
    session_key: SessionKeyV1
    opened_at: UTCDateTime
    closed_at: UTCDateTime
    authority: Literal["realized", "scheduled_reconstruction"]
    authority_record_hashes: tuple[SHA256Hash, ...]
    authority_proof_hashes: tuple[SHA256Hash, ...]
    session_hash: SHA256Hash

    @field_validator("authority_record_hashes", "authority_proof_hashes")
    @classmethod
    def canonicalize_authority_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("session authority evidence must not be empty")
        if len(set(values)) != len(values):
            raise ValueError("session authority evidence hashes must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if self.closed_at <= self.opened_at:
            raise ValueError("session close must follow open")
        expected = evaluation_session_hash(self)
        if self.session_hash != expected:
            raise ValueError(
                f"session hash mismatch: expected {expected}, got {self.session_hash}"
            )
        return self


class CommonVenueSessionV1(FrozenModel):
    """A venue-specific source session and its declared replay identities.

    This model is structural. Its hashes and timestamps are not source or
    issuer authentication; the common-clock verifier must rederive them from
    the configured evidence before an evaluator may consume the association.
    """

    schema_version: Literal["1"] = "1"
    session: EvaluationSessionV1
    resolution_context_hash: SHA256Hash
    selection_query_hash: SHA256Hash
    source_policy_hash: SHA256Hash
    availability_evidence_hash: SHA256Hash
    first_available_at: UTCDateTime


def common_session_association_hash(
    association: CommonSessionAssociationV1,
) -> SHA256Hash:
    """Hash the versioned logical step without inventing a venue MIC."""
    return content_hash(
        association.model_dump(mode="python", exclude={"association_hash"})
    )


class CommonSessionAssociationV1(FrozenModel):
    """One logical step whose venue members share exact session boundaries.

    Members retain their original session keys. This structure by itself is
    not an authorization to evaluate or a verified common market session.
    """

    schema_version: Literal["1"] = "1"
    local_date: date
    opened_at: UTCDateTime
    closed_at: UTCDateTime
    authority: Literal["realized", "scheduled_reconstruction"]
    expected_venues: tuple[NonBlankStr, ...]
    members: tuple[CommonVenueSessionV1, ...]
    association_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_association(self) -> Self:
        if self.closed_at <= self.opened_at:
            raise ValueError("common session close must follow open")
        if len(self.expected_venues) < 2:
            raise ValueError("common session requires at least two venues")
        if tuple(sorted(set(self.expected_venues))) != self.expected_venues:
            raise ValueError("expected venues must be unique and ordered")
        for mic in self.expected_venues:
            try:
                ListingVenue(mic)
            except ValueError as error:
                raise ValueError(f"unsupported listing venue {mic}") from error
        actual = tuple(member.session.session_key.mic for member in self.members)
        if actual != self.expected_venues:
            raise ValueError("common session members must match the expected venues")
        for member in self.members:
            session = member.session
            if session.session_key.local_date != self.local_date:
                raise ValueError("member local date must match the common session")
            if (session.opened_at, session.closed_at) != (
                self.opened_at,
                self.closed_at,
            ):
                raise ValueError("member boundaries must match the common session")
            if session.authority != self.authority:
                raise ValueError("member authority must match the common session")
            if member.first_available_at > self.closed_at:
                raise ValueError("member authority must be available by the close")
        expected = common_session_association_hash(self)
        if self.association_hash != expected:
            raise ValueError(
                f"common session association hash mismatch: expected {expected}"
            )
        return self


def common_session_clock_hash(clock: CommonSessionClockV1) -> SHA256Hash:
    """Hash the declared logical clock; rederivation is a separate gate."""
    return content_hash(clock.model_dump(mode="python", exclude={"clock_hash"}))


class CommonSessionClockV1(FrozenModel):
    """One ordered logical step per declared date across the same venues.

    The expected inventory is a declaration, not proof of coverage. A
    consumer must independently verify the interval and every venue member
    before admitting this clock.
    """

    schema_version: Literal["1"] = "1"
    mode: SessionClockMode
    window_start: date
    window_end: date
    expected_venues: tuple[NonBlankStr, ...]
    expected_session_dates: tuple[date, ...]
    sessions: tuple[CommonSessionAssociationV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    clock_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_common_clock(self) -> Self:
        if self.window_start > self.window_end:
            raise ValueError("common clock window cannot be reversed")
        if not self.sessions:
            raise ValueError("common clock requires at least one session")
        if tuple(sorted(set(self.expected_venues))) != self.expected_venues:
            raise ValueError("expected venues must be unique and ordered")
        if len(self.expected_venues) < 2:
            raise ValueError("common clock requires at least two venues")
        dates = tuple(session.local_date for session in self.sessions)
        if dates != self.expected_session_dates:
            raise ValueError("common clock sessions must match the expected dates")
        if tuple(sorted(set(dates))) != dates:
            raise ValueError("common clock dates must be unique and ordered")
        if dates[0] < self.window_start or dates[-1] > self.window_end:
            raise ValueError("common clock sessions must lie within its window")
        expected_authority = {
            "realized_session_authority": "realized",
            "scheduled_session_reconstruction": "scheduled_reconstruction",
        }[self.mode]
        for session in self.sessions:
            if session.expected_venues != self.expected_venues:
                raise ValueError("common session venues must match the clock")
            if session.authority != expected_authority:
                raise ValueError("common session authority must match the clock mode")
        for previous, current in zip(self.sessions, self.sessions[1:], strict=False):
            if current.opened_at < previous.closed_at:
                raise ValueError("common clock sessions must not overlap")
        if (
            tuple(sorted(set(self.acknowledged_limitations)))
            != self.acknowledged_limitations
        ):
            raise ValueError("common clock limitations must be unique and ordered")
        if self.mode == "scheduled_session_reconstruction":
            required = {
                ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                ALPACA_LIMITATION_ABSENT_HALTS,
            }
            if not required.issubset(self.acknowledged_limitations):
                raise ValueError("scheduled common clock lacks required limitations")
        expected = common_session_clock_hash(self)
        if self.clock_hash != expected:
            raise ValueError(f"common clock hash mismatch: expected {expected}")
        return self


class SessionClockV1(FrozenModel):
    """Immutable content-addressed authority-bound session sequence."""

    schema_version: Literal["1"] = "1"
    mode: SessionClockMode
    sessions: tuple[EvaluationSessionV1, ...]
    acknowledged_limitations: tuple[NonBlankStr, ...]
    clock_hash: SHA256Hash

    @field_validator("sessions")
    @classmethod
    def canonicalize_sessions(
        cls, sessions: tuple[EvaluationSessionV1, ...]
    ) -> tuple[EvaluationSessionV1, ...]:
        if not sessions:
            raise ValueError("session clock requires at least one session")
        keys = tuple(
            (
                session.session_key.mic,
                session.session_key.local_date.isoformat(),
            )
            for session in sessions
        )
        if len(set(keys)) != len(keys):
            raise ValueError("session clock requires unique session keys")
        ordered = sorted(sessions, key=session_order_key)
        if tuple(sessions) != tuple(ordered):
            raise ValueError(
                "session clock requires strict chronological session order"
            )
        # Clock order is UTC boundary order. Without overlap every stepped
        # session has closed before the next one opens, so the next session
        # opens after the decision it executes. The local date is the key
        # every piece of evidence binds to, so it must follow the same order
        # (issue 84): a session stamped after a later date would otherwise
        # fill that later decision at a price printed before it. Unique keys
        # then make each venue's dates strictly increasing.
        for previous, current in zip(sessions, sessions[1:], strict=False):
            if current.opened_at < previous.closed_at:
                raise ValueError("session clock sessions must not overlap")
            if current.session_key.local_date < previous.session_key.local_date:
                raise ValueError(
                    "session clock local dates must not decrease in clock order"
                )
        return tuple(sessions)

    @field_validator("acknowledged_limitations")
    @classmethod
    def canonicalize_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("session clock limitations must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_clock(self) -> Self:
        expected_authority = {
            "realized_session_authority": "realized",
            "scheduled_session_reconstruction": "scheduled_reconstruction",
        }[self.mode]
        for session in self.sessions:
            if session.authority != expected_authority:
                raise ValueError(
                    "session authority must match the clock authority mode"
                )
        if self.mode == "scheduled_session_reconstruction":
            required = (
                ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
                ALPACA_LIMITATION_ABSENT_HALTS,
            )
            missing = tuple(
                item for item in required if item not in self.acknowledged_limitations
            )
            if missing:
                raise ValueError(
                    f"scheduled reconstruction clock lacks limitations: {missing}"
                )
        expected = session_clock_hash(self)
        if self.clock_hash != expected:
            raise ValueError(
                f"clock hash mismatch: expected {expected}, got {self.clock_hash}"
            )
        return self
