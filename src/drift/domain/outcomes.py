"""Realized outcome domain contracts and ledger validation (M4-1, Issue 175).

Provides immutable domain models for ground-truth outcome resolution,
attribution residuals, delisting/indeterminate handling, content hashing,
and atomic outcome batches sealed into the M0 ledger.
"""

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import field_validator, model_validator

from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.serialization.canonical import content_hash

OUTCOMES_SCHEMA_VERSION: Literal["1"] = "1"


class OutcomeResolutionStatus(StrEnum):
    """Terminal resolution classification for an ex-ante prediction."""

    RESOLVED = "resolved"
    INDETERMINATE = "indeterminate"
    DELISTED_WITH_OUTCOME = "delisted_with_outcome"
    DELISTED_WITHOUT_OUTCOME = "delisted_without_outcome"
    EXCLUDED_UNAVAILABLE = "excluded_unavailable"


class RealizedOutcomeRecordV1(FrozenModel):
    """Immutable ground-truth realization and attribution for a prediction."""

    schema_version: Literal["1"] = OUTCOMES_SCHEMA_VERSION
    outcome_id: UUID7
    prediction_id: UUID7
    status: OutcomeResolutionStatus
    realized_value: Decimal | None = None
    error: Decimal | None = None
    directional_match: bool | None = None
    resolved_at: UTCDateTime
    evidence_hashes: tuple[SHA256Hash, ...]
    indeterminate_reason: NonBlankStr | None = None
    outcome_hash: SHA256Hash

    @field_validator("evidence_hashes")
    @classmethod
    def canonicalize_evidence_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("evidence hashes must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status == OutcomeResolutionStatus.RESOLVED:
            if self.realized_value is None:
                raise ValueError("resolved outcomes require a realized value")
            if self.indeterminate_reason is not None:
                raise ValueError(
                    "resolved outcomes cannot have an indeterminate reason"
                )

        if self.status == OutcomeResolutionStatus.DELISTED_WITH_OUTCOME:
            if self.realized_value is None:
                raise ValueError("delisted with outcome requires a realized value")

        if self.status in {
            OutcomeResolutionStatus.INDETERMINATE,
            OutcomeResolutionStatus.DELISTED_WITHOUT_OUTCOME,
            OutcomeResolutionStatus.EXCLUDED_UNAVAILABLE,
        }:
            if self.indeterminate_reason is None:
                raise ValueError(
                    "unresolved outcomes require an explicit indeterminate reason"
                )
            if self.realized_value is not None:
                raise ValueError("unresolved outcomes cannot have a realized value")
            if self.error is not None:
                raise ValueError("unresolved outcomes cannot have an error value")

        expected = compute_outcome_record_hash(self)
        if self.outcome_hash != expected:
            raise ValueError("outcome hash mismatch")
        return self


def compute_outcome_record_hash(
    record: RealizedOutcomeRecordV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for a realized outcome record."""
    if isinstance(record, Mapping):
        data = {k: v for k, v in record.items() if k != "outcome_hash"}
    else:
        data = {
            k: v
            for k, v in record.model_dump(mode="python").items()
            if k != "outcome_hash"
        }
    return content_hash(data)


def build_realized_outcome_record(
    *,
    outcome_id: UUID,
    prediction_id: UUID,
    status: OutcomeResolutionStatus,
    resolved_at: Any,
    evidence_hashes: tuple[str, ...] | list[str],
    realized_value: Decimal | None = None,
    error: Decimal | None = None,
    directional_match: bool | None = None,
    indeterminate_reason: str | None = None,
) -> RealizedOutcomeRecordV1:
    """Construct a RealizedOutcomeRecordV1 with calculated content hash."""
    unsigned = {
        "schema_version": OUTCOMES_SCHEMA_VERSION,
        "outcome_id": outcome_id,
        "prediction_id": prediction_id,
        "status": status,
        "realized_value": realized_value,
        "error": error,
        "directional_match": directional_match,
        "resolved_at": resolved_at,
        "evidence_hashes": tuple(sorted(evidence_hashes)),
        "indeterminate_reason": indeterminate_reason,
    }
    o_hash = compute_outcome_record_hash(unsigned)
    return RealizedOutcomeRecordV1.model_validate(
        {
            **unsigned,
            "outcome_hash": o_hash,
        }
    )


def _outcome_record_order(
    record: RealizedOutcomeRecordV1,
) -> bytes:
    return record.outcome_id.bytes


class RealizedOutcomeBatchV1(FrozenModel):
    """Atomic batch of realized outcomes resolved at an evaluation horizon."""

    schema_version: Literal["1"] = OUTCOMES_SCHEMA_VERSION
    outcome_batch_id: UUID7
    run_id: UUID7
    resolved_at: UTCDateTime
    lane: Literal["exploratory", "promotion"]
    outcomes: tuple[RealizedOutcomeRecordV1, ...]
    batch_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        outcome_ids = [o.outcome_id for o in self.outcomes]
        if len(set(outcome_ids)) != len(outcome_ids):
            raise ValueError("all outcomes in a batch must have unique outcome_ids")

        pred_ids = [o.prediction_id for o in self.outcomes]
        if len(set(pred_ids)) != len(pred_ids):
            raise ValueError("all outcomes in a batch must have unique prediction_ids")

        ordered = tuple(sorted(self.outcomes, key=_outcome_record_order))
        if self.outcomes != ordered:
            raise ValueError("outcomes must be canonically sorted")

        expected = compute_outcome_batch_hash(self)
        if self.batch_hash != expected:
            raise ValueError("outcome batch hash mismatch")
        return self


def compute_outcome_batch_hash(
    batch: RealizedOutcomeBatchV1 | Mapping[str, Any],
) -> str:
    """Compute content hash for a realized outcome batch."""
    if isinstance(batch, Mapping):
        data = {k: v for k, v in batch.items() if k != "batch_hash"}
    else:
        data = {
            k: v
            for k, v in batch.model_dump(mode="python").items()
            if k != "batch_hash"
        }
    return content_hash(data)


def build_realized_outcome_batch(
    *,
    outcome_batch_id: UUID,
    run_id: UUID,
    resolved_at: Any,
    lane: Literal["exploratory", "promotion"],
    outcomes: tuple[RealizedOutcomeRecordV1, ...] | list[RealizedOutcomeRecordV1],
) -> RealizedOutcomeBatchV1:
    """Construct a RealizedOutcomeBatchV1 with sorted outcomes and hash."""
    ordered = tuple(sorted(outcomes, key=_outcome_record_order))
    unsigned = {
        "schema_version": OUTCOMES_SCHEMA_VERSION,
        "outcome_batch_id": outcome_batch_id,
        "run_id": run_id,
        "resolved_at": resolved_at,
        "lane": lane,
        "outcomes": ordered,
    }
    b_hash = compute_outcome_batch_hash(unsigned)
    return RealizedOutcomeBatchV1.model_validate(
        {
            **unsigned,
            "batch_hash": b_hash,
        }
    )
