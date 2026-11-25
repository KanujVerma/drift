"""Synthetic uncertainty observations, not verified evidence or send authority.

This is an offline-only candidate contract. CONFIRMED describes only a
supplied fake fact; NOT_SENT is a fixture claim, not proof that a real send
did not occur. Neither is verified by this model. It does not establish
account identity, evidence origin, broker outcome, settlement, or resumption.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import UUID7, FrozenModel, SHA256Hash, UTCDateTime
from drift.serialization.canonical import content_hash


class SyntheticBrokerFactV2(FrozenModel):
    """A caller-supplied fake fact, not evidence from an actual broker."""

    status: Literal[
        "new",
        "acknowledged",
        "partially_filled",
        "filled",
        "canceled",
        "rejected",
        "expired",
    ]
    cumulative_quantity: int | None = Field(default=None, ge=0)
    leaves_quantity: int | None = Field(default=None, ge=0)
    cumulative_fee: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class SyntheticExecutionObservationV2(FrozenModel):
    """An unverified synthetic observation, never a broker assertion."""

    profile: Literal["drift-synthetic-execution-observation-v2"] = (
        "drift-synthetic-execution-observation-v2"
    )
    schema_version: Literal["2"] = "2"
    observation_id: UUID7
    attempt_id: UUID7
    intent_id: UUID7
    intent_hash: SHA256Hash
    account_key: str
    observed_at: UTCDateTime
    knowledge: Literal["CONFIRMED", "UNKNOWN", "NOT_SENT"]
    reason_code: (
        Literal[
            "submission_unconfirmed",
            "cancellation_unconfirmed",
            "response_unrecognized",
            "evidence_conflict",
            "recovery_required",
            "journal_unavailable",
            "legacy_uncertainty",
            "authorization_refused",
        ]
        | None
    )
    broker_fact: SyntheticBrokerFactV2 | None = None
    last_confirmed_report_hash: SHA256Hash | None = None
    observation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if (
            not self.account_key.startswith("synthetic-")
            or self.account_key != self.account_key.strip()
            or len(self.account_key) <= len("synthetic-")
        ):
            raise ValueError("only labelled synthetic account keys are supported")
        if self.knowledge == "CONFIRMED":
            if self.broker_fact is None or self.reason_code is not None:
                raise ValueError("synthetic confirmed candidate requires a fact")
        elif self.broker_fact is not None or self.reason_code is None:
            raise ValueError("unknown and not-sent candidates cannot carry facts")
        if self.knowledge == "NOT_SENT" and self.reason_code != "authorization_refused":
            raise ValueError("synthetic not-sent candidate requires refusal reason")
        if self.knowledge == "UNKNOWN" and self.reason_code == "authorization_refused":
            raise ValueError("refusal is not an uncertainty reason")
        payload = self.model_dump(mode="python", exclude={"observation_hash"})
        if self.observation_hash != content_hash(payload):
            raise ValueError("observation hash mismatch")
        return self


def build_synthetic_observation(
    *,
    observation_id: UUID,
    attempt_id: UUID,
    intent_id: UUID,
    intent_hash: str,
    account_key: str,
    observed_at: datetime,
    knowledge: Literal["CONFIRMED", "UNKNOWN", "NOT_SENT"],
    reason_code: Literal[
        "submission_unconfirmed",
        "cancellation_unconfirmed",
        "response_unrecognized",
        "evidence_conflict",
        "recovery_required",
        "journal_unavailable",
        "legacy_uncertainty",
        "authorization_refused",
    ]
    | None,
    broker_fact: SyntheticBrokerFactV2 | None = None,
    last_confirmed_report_hash: str | None = None,
) -> SyntheticExecutionObservationV2:
    """Build an unverified candidate; hashing does not authenticate origin."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    payload = {
        "profile": "drift-synthetic-execution-observation-v2",
        "schema_version": "2",
        "observation_id": observation_id,
        "attempt_id": attempt_id,
        "intent_id": intent_id,
        "intent_hash": intent_hash,
        "account_key": account_key,
        "observed_at": observed_at.astimezone(UTC),
        "knowledge": knowledge,
        "reason_code": reason_code,
        "broker_fact": broker_fact.model_dump(mode="python") if broker_fact else None,
        "last_confirmed_report_hash": last_confirmed_report_hash,
    }
    return SyntheticExecutionObservationV2.model_validate(
        {**payload, "observation_hash": content_hash(payload)}
    )
