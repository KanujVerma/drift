"""M2 session clock contracts over realized or scheduled-reconstruction authority."""

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
        ordered = sorted(
            sessions,
            key=lambda session: (
                session.session_key.mic,
                session.session_key.local_date,
            ),
        )
        if tuple(sessions) != tuple(ordered):
            raise ValueError(
                "session clock requires strict chronological session order"
            )
        for previous, current in zip(sessions, sessions[1:], strict=False):
            if current.opened_at < previous.closed_at:
                raise ValueError("session clock sessions must not overlap")
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
