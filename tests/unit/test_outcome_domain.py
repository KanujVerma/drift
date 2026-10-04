"""Unit tests for realized outcome domain contracts (M4-1, Issue 175)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from drift.domain.outcomes import (
    OutcomeResolutionStatus,
    RealizedOutcomeRecordV1,
    build_realized_outcome_batch,
    build_realized_outcome_record,
    compute_outcome_batch_hash,
    compute_outcome_record_hash,
)
from drift.serialization.canonical import canonical_json

OUTCOME_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcde1")
OUTCOME_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcde2")
PRED_ID_1 = UUID("018f3a5b-6c7d-7890-8123-456789abcda1")
PRED_ID_2 = UUID("018f3a5b-6c7d-7890-8123-456789abcda2")
BATCH_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcdb0")
RUN_ID = UUID("018f3a5b-6c7d-7890-8123-456789abcd00")
RESOLVED_AT = datetime(2026, 1, 23, 21, 30, 0, tzinfo=UTC)
EVID_HASH_1 = "1" * 64
EVID_HASH_2 = "2" * 64


def test_resolved_outcome_record_valid() -> None:
    record = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_1,
        prediction_id=PRED_ID_1,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.042"),
        error=Decimal("0.007"),
        directional_match=True,
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1, EVID_HASH_2),
    )
    assert record.outcome_id == OUTCOME_ID_1
    assert record.prediction_id == PRED_ID_1
    assert record.status == OutcomeResolutionStatus.RESOLVED
    assert record.realized_value == Decimal("0.042")
    assert record.error == Decimal("0.007")
    assert record.directional_match is True
    assert record.indeterminate_reason is None
    assert record.outcome_hash == compute_outcome_record_hash(record)


def test_resolved_outcome_rejects_missing_realized_value() -> None:
    with pytest.raises(
        ValidationError, match="resolved outcomes require a realized value"
    ):
        RealizedOutcomeRecordV1(
            outcome_id=OUTCOME_ID_1,
            prediction_id=PRED_ID_1,
            status=OutcomeResolutionStatus.RESOLVED,
            realized_value=None,
            resolved_at=RESOLVED_AT,
            evidence_hashes=(EVID_HASH_1,),
            outcome_hash="0" * 64,
        )


def test_resolved_outcome_rejects_indeterminate_reason() -> None:
    with pytest.raises(
        ValidationError, match="resolved outcomes cannot have an indeterminate reason"
    ):
        RealizedOutcomeRecordV1(
            outcome_id=OUTCOME_ID_1,
            prediction_id=PRED_ID_1,
            status=OutcomeResolutionStatus.RESOLVED,
            realized_value=Decimal("0.01"),
            resolved_at=RESOLVED_AT,
            evidence_hashes=(EVID_HASH_1,),
            indeterminate_reason="Some error",
            outcome_hash="0" * 64,
        )


def test_indeterminate_outcome_valid_and_bounds() -> None:
    record = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_1,
        prediction_id=PRED_ID_1,
        status=OutcomeResolutionStatus.INDETERMINATE,
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1,),
        indeterminate_reason="MissingSessionReturnError: session unavailable",
    )
    assert record.status == OutcomeResolutionStatus.INDETERMINATE
    assert record.realized_value is None
    assert record.error is None
    assert record.indeterminate_reason is not None

    with pytest.raises(
        ValidationError,
        match="unresolved outcomes require an explicit indeterminate reason",
    ):
        RealizedOutcomeRecordV1(
            outcome_id=OUTCOME_ID_1,
            prediction_id=PRED_ID_1,
            status=OutcomeResolutionStatus.INDETERMINATE,
            resolved_at=RESOLVED_AT,
            evidence_hashes=(EVID_HASH_1,),
            indeterminate_reason=None,
            outcome_hash="0" * 64,
        )


def test_outcome_record_hash_mismatch_fails() -> None:
    with pytest.raises(ValidationError, match="outcome hash mismatch"):
        RealizedOutcomeRecordV1(
            outcome_id=OUTCOME_ID_1,
            prediction_id=PRED_ID_1,
            status=OutcomeResolutionStatus.RESOLVED,
            realized_value=Decimal("0.05"),
            resolved_at=RESOLVED_AT,
            evidence_hashes=(EVID_HASH_1,),
            outcome_hash="0" * 64,  # bad hash
        )


def test_realized_outcome_batch_builder_and_invariants() -> None:
    rec1 = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_1,
        prediction_id=PRED_ID_1,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.02"),
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1,),
    )
    rec2 = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_2,
        prediction_id=PRED_ID_2,
        status=OutcomeResolutionStatus.INDETERMINATE,
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1,),
        indeterminate_reason="DelistedWithoutOutcomeError",
    )

    batch = build_realized_outcome_batch(
        outcome_batch_id=BATCH_ID,
        run_id=RUN_ID,
        resolved_at=RESOLVED_AT,
        lane="exploratory",
        outcomes=(rec2, rec1),  # Out of order to verify canonical sorting
    )
    assert batch.outcome_batch_id == BATCH_ID
    assert batch.run_id == RUN_ID
    assert batch.lane == "exploratory"
    assert len(batch.outcomes) == 2
    assert batch.outcomes[0].outcome_id == OUTCOME_ID_1
    assert batch.outcomes[1].outcome_id == OUTCOME_ID_2
    assert batch.batch_hash == compute_outcome_batch_hash(batch)


def test_realized_outcome_batch_rejects_duplicate_outcome_or_prediction() -> None:
    rec1 = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_1,
        prediction_id=PRED_ID_1,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.02"),
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1,),
    )
    rec_dup_pred = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_2,
        prediction_id=PRED_ID_1,  # Duplicate prediction_id
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.03"),
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1,),
    )

    with pytest.raises(
        ValidationError, match="all outcomes in a batch must have unique prediction_ids"
    ):
        build_realized_outcome_batch(
            outcome_batch_id=BATCH_ID,
            run_id=RUN_ID,
            resolved_at=RESOLVED_AT,
            lane="exploratory",
            outcomes=(rec1, rec_dup_pred),
        )


def test_canonical_json_roundtrip_outcome() -> None:
    rec = build_realized_outcome_record(
        outcome_id=OUTCOME_ID_1,
        prediction_id=PRED_ID_1,
        status=OutcomeResolutionStatus.RESOLVED,
        realized_value=Decimal("0.042"),
        error=Decimal("0.007"),
        directional_match=True,
        resolved_at=RESOLVED_AT,
        evidence_hashes=(EVID_HASH_1, EVID_HASH_2),
    )
    bytes1 = canonical_json(rec)
    bytes2 = canonical_json(rec)
    assert bytes1 == bytes2
    assert len(bytes1) > 0
