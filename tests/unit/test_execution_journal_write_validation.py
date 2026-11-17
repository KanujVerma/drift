"""Validate the exact V1 bytes before irreversible journal retention."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest
from pydantic import ValidationError

from drift.domain.execution import (
    ExecutionReportV1,
    ExecutionStatus,
    OrderIntentV1,
    OrderType,
    build_execution_report,
    build_order_intent,
    compute_execution_report_hash,
    compute_order_intent_hash,
)
from drift.domain.sessions import SessionKeyV1
from drift.execution.journal import (
    DuplicateIntentRecordError,
    IntentAppendOnlyViolationError,
    PersistentOrderIntentJournal,
)
from drift.serialization.canonical import canonical_json


def _intent() -> OrderIntentV1:
    return build_order_intent(
        intent_id=uuid7(),
        client_order_id=str(uuid7()),
        session_key=SessionKeyV1(
            mic="XNYS", session_scope="regular", local_date=date(2026, 3, 2)
        ),
        security_id=uuid7(),
        side="buy",
        quantity=5,
        order_type="limit",
        limit_price=Decimal("100"),
        created_at=datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
    )


def _report(intent: OrderIntentV1) -> ExecutionReportV1:
    return build_execution_report(
        report_id=uuid7(),
        intent_id=intent.intent_id,
        broker_order_id="synthetic-order",
        status="acknowledged",
        leaves_quantity=5,
        reported_at=intent.created_at,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 17},
        {"quantity": 0},
        {"limit_price": Decimal("0")},
        {"order_type": OrderType.MARKET},
        {"schema_version": "2"},
        {"client_order_id": ""},
        {"intent_hash": "0" * 64},
    ],
)
def test_invalid_intent_refuses_before_sql_and_does_not_reserve_identity(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    path = tmp_path / "journal.sqlite"
    journal = PersistentOrderIntentJournal(path)
    earlier, valid = _intent(), _intent()
    journal.record_intent(earlier)
    forged = OrderIntentV1.model_construct(
        **{
            **{name: getattr(valid, name) for name in OrderIntentV1.model_fields},
            **change,
        }
    )
    connection = journal.connection
    original = tuple(connection.iterdump())
    changes = connection.total_changes
    trace: list[str] = []
    connection.set_trace_callback(trace.append)
    try:
        with pytest.raises(ValidationError):
            journal.record_intent(forged)
    finally:
        connection.set_trace_callback(None)
    try:
        assert trace == []
        assert connection.total_changes == changes
        assert tuple(connection.iterdump()) == original
        assert journal.get_intent(earlier.intent_id) == earlier
        assert journal.get_intent(valid.intent_id) is None
        journal.record_intent(valid)
        assert journal.get_intent(valid.intent_id) == valid
        assert journal.get_intent_by_client_id(valid.client_order_id) == valid
    finally:
        journal.close()
    reopened = PersistentOrderIntentJournal(path)
    try:
        assert reopened.get_intent(earlier.intent_id) == earlier
        assert reopened.get_intent(valid.intent_id) == valid
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "change",
    [
        {"cum_quantity": 17},
        {"cum_quantity": -1},
        {"leaves_quantity": -1},
        {"fee_amount": Decimal("-1")},
        {"status": ExecutionStatus.FILLED},
        {"status": ExecutionStatus.REJECTED},
        {"schema_version": "2"},
        {"report_hash": "0" * 64},
    ],
)
def test_invalid_report_refuses_before_sql_and_preserves_prior_evidence(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    path = tmp_path / "journal.sqlite"
    journal = PersistentOrderIntentJournal(path)
    intent = _intent()
    earlier, valid = _report(intent), _report(intent)
    journal.record_intent(intent)
    journal.record_execution_report(earlier)
    forged = ExecutionReportV1.model_construct(
        **{
            **{name: getattr(valid, name) for name in ExecutionReportV1.model_fields},
            **change,
        }
    )
    connection = journal.connection
    original = tuple(connection.iterdump())
    changes = connection.total_changes
    trace: list[str] = []
    connection.set_trace_callback(trace.append)
    try:
        with pytest.raises(ValidationError):
            journal.record_execution_report(forged)
    finally:
        connection.set_trace_callback(None)
    try:
        assert trace == []
        assert connection.total_changes == changes
        assert tuple(connection.iterdump()) == original
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (earlier,)
        assert journal.get_execution_report(valid.report_id) is None
        journal.record_execution_report(valid)
        assert journal.list_execution_reports_for_intent(intent.intent_id) == (
            earlier,
            valid,
        )
    finally:
        journal.close()
    reopened = PersistentOrderIntentJournal(path)
    try:
        assert reopened.list_execution_reports_for_intent(intent.intent_id) == (
            earlier,
            valid,
        )
    finally:
        reopened.close()


def test_valid_canonical_bytes_indexes_and_hashes_are_preserved(tmp_path: Path) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "journal.sqlite")
    intent = _intent()
    report = _report(intent)
    try:
        journal.record_intent(intent)
        journal.record_execution_report(report)
        intent_row = journal.connection.execute(
            "SELECT payload_json,quantity,intent_hash,session_key FROM order_intents"
        ).fetchone()
        report_row = journal.connection.execute(
            "SELECT payload_json,cum_quantity,leaves_quantity,report_hash "
            "FROM execution_reports"
        ).fetchone()
        assert intent_row["payload_json"].encode() == canonical_json(
            intent.model_dump(mode="python")
        )
        assert report_row["payload_json"].encode() == canonical_json(
            report.model_dump(mode="python")
        )
        assert intent_row["quantity"] == 5
        assert intent_row["intent_hash"] == intent.intent_hash
        assert intent_row["session_key"] == "XNYS:regular:2026-03-02"
        assert report_row["cum_quantity"] == 0
        assert report_row["leaves_quantity"] == 5
        assert report_row["report_hash"] == report.report_hash
        assert journal.get_intent(intent.intent_id) == intent
        assert journal.get_execution_report(report.report_id) == report
    finally:
        journal.close()


@pytest.mark.parametrize("kind", ["intent", "report"])
def test_matching_hash_does_not_admit_invalid_semantics(kind: str) -> None:
    intent = _intent()
    journal = PersistentOrderIntentJournal()
    trace: list[str] = []
    try:
        if kind == "intent":
            fields: dict[str, Any] = {
                name: getattr(intent, name)
                for name in OrderIntentV1.model_fields
                if name != "intent_hash"
            }
            fields["quantity"] = 0
            fields["intent_hash"] = compute_order_intent_hash(**fields)
            forged_intent = OrderIntentV1.model_construct(**fields)
            journal.connection.set_trace_callback(trace.append)
            with pytest.raises(ValidationError, match="greater than 0"):
                journal.record_intent(forged_intent)
        else:
            report = _report(intent)
            fields = {
                name: getattr(report, name)
                for name in ExecutionReportV1.model_fields
                if name != "report_hash"
            }
            fields["status"] = ExecutionStatus.FILLED
            fields["report_hash"] = compute_execution_report_hash(**fields)
            forged_report = ExecutionReportV1.model_construct(**fields)
            journal.connection.set_trace_callback(trace.append)
            with pytest.raises(ValidationError, match="cum_quantity > 0"):
                journal.record_execution_report(forged_report)
        assert trace == []
    finally:
        journal.connection.set_trace_callback(None)
        journal.close()


def test_validation_does_not_weaken_duplicates_or_append_only_triggers(
    tmp_path: Path,
) -> None:
    journal = PersistentOrderIntentJournal(tmp_path / "journal.sqlite")
    intent = _intent()
    report = _report(intent)
    try:
        journal.record_intent(intent)
        journal.record_execution_report(report)
        before = tuple(journal.connection.iterdump())
        with pytest.raises(DuplicateIntentRecordError):
            journal.record_intent(intent)
        with pytest.raises(DuplicateIntentRecordError):
            journal.record_execution_report(report)
        for table in ("order_intents", "execution_reports"):
            with pytest.raises(IntentAppendOnlyViolationError):
                with journal._transaction() as cursor:
                    cursor.execute(f"DELETE FROM {table}")
            with pytest.raises(IntentAppendOnlyViolationError):
                with journal._transaction() as cursor:
                    cursor.execute(f"UPDATE {table} SET payload_json = '{{}}'")
        assert tuple(journal.connection.iterdump()) == before
    finally:
        journal.close()
