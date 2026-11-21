"""Malformed risk verdicts cannot poison the append-only risk journal."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4, uuid7

import pytest
from pydantic import ValidationError

from drift.domain.risk import (
    RiskVerdictStatus,
    RiskVerdictV1,
    build_risk_verdict,
    compute_risk_verdict_hash,
)
from drift.risk.journal import DuplicateRiskRecordError, PersistentRiskJournal
from drift.serialization.canonical import canonical_json

NOW = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)


def _verdict(status: RiskVerdictStatus = RiskVerdictStatus.ALLOWED) -> RiskVerdictV1:
    return build_risk_verdict(
        order_id=uuid7(),
        status=status,
        reason=None if status == RiskVerdictStatus.ALLOWED else "fixture refusal",
        evaluated_at=NOW,
    )


@pytest.mark.parametrize(
    "change,rehash",
    [
        ({"verdict_hash": "0" * 64}, False),
        ({"order_id": uuid7()}, False),
        ({"evaluated_at": NOW + timedelta(seconds=1)}, False),
        ({"status": RiskVerdictStatus.REJECTED, "reason": "changed"}, False),
        ({"schema_version": "2"}, True),
        ({"status": "unknown"}, True),
        ({"status": RiskVerdictStatus.REJECTED, "reason": None}, True),
        ({"status": RiskVerdictStatus.KILL_SWITCH_ACTIVE, "reason": None}, True),
        ({"reason": "unexpected allowed reason"}, True),
        ({"status": RiskVerdictStatus.REJECTED, "reason": ""}, True),
        ({"order_id": uuid4()}, True),
    ],
)
def test_invalid_verdict_refuses_before_sql_and_preserves_valid_identity_retry(
    tmp_path: Path, change: dict[str, Any], rehash: bool
) -> None:
    path = tmp_path / "risk.sqlite"
    earlier, valid = _verdict(), _verdict()
    fields = {name: getattr(valid, name) for name in RiskVerdictV1.model_fields}
    fields.update(change)
    if rehash:
        fields["verdict_hash"] = compute_risk_verdict_hash(fields)
    forged = RiskVerdictV1.model_construct(**fields)
    with PersistentRiskJournal(path) as journal:
        journal.record_verdict(earlier)
        latch = journal.trip_kill_switch(reason="fixture stop", tripped_at=NOW)
        connection = journal.connection
        original_dump = tuple(connection.iterdump())
        original_changes = connection.total_changes
        trace: list[str] = []
        connection.set_trace_callback(trace.append)
        try:
            with pytest.raises(ValidationError):
                journal.record_verdict(forged)
        finally:
            connection.set_trace_callback(None)
        assert trace == []
        assert connection.total_changes == original_changes
        assert tuple(connection.iterdump()) == original_dump
        assert journal.list_verdicts() == (earlier,)
        assert journal.get_verdict_for_order(valid.order_id) is None
        assert journal.get_current_kill_switch_state() == latch
        journal.record_verdict(valid)
        assert journal.get_verdict_for_order(valid.order_id) == valid
    with PersistentRiskJournal(path) as reopened:
        assert reopened.list_verdicts() == (earlier, valid)
        assert reopened.get_current_kill_switch_state() == latch


@pytest.mark.parametrize("status", list(RiskVerdictStatus))
def test_valid_verdict_preserves_exact_bytes_indexes_and_cold_readback(
    tmp_path: Path, status: RiskVerdictStatus
) -> None:
    path = tmp_path / "risk.sqlite"
    valid = _verdict(status)
    expected = canonical_json(valid.model_dump(mode="python")).decode("utf-8")
    with PersistentRiskJournal(path) as journal:
        journal.record_verdict(valid)
        row = journal.connection.execute(
            "SELECT * FROM risk_verdicts WHERE order_id = ?", (str(valid.order_id),)
        ).fetchone()
        assert row is not None
        assert row["payload_json"] == expected
        assert row["order_id"] == str(valid.order_id)
        assert row["status"] == valid.status
        assert row["reason"] == valid.reason
        assert row["evaluated_at"] == valid.evaluated_at.isoformat()
        assert row["verdict_hash"] == valid.verdict_hash
        assert journal.get_verdict_for_order(valid.order_id) == valid
        with pytest.raises(DuplicateRiskRecordError):
            journal.record_verdict(valid)
        for query in (
            "UPDATE risk_verdicts SET status = 'rejected'",
            "DELETE FROM risk_verdicts",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                journal.connection.execute(query)
        assert journal.list_verdicts() == (valid,)
    with PersistentRiskJournal(path) as reopened:
        assert reopened.list_verdicts() == (valid,)
        assert (
            reopened.connection.execute(
                "SELECT payload_json FROM risk_verdicts"
            ).fetchone()[0]
            == expected
        )


def test_supported_model_copy_already_rejects_an_invalid_hash() -> None:
    with pytest.raises(ValidationError, match="risk verdict hash mismatch"):
        _verdict().model_copy(update={"verdict_hash": "0" * 64})
