import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest

from drift.errors import LedgerIntegrityError
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger


def _populated_ledger(path: Path) -> SQLiteLedger:
    ledger = SQLiteLedger(path)
    for index in range(3):
        ledger.append(
            AuditEventDraft.model_validate(
                {
                    "event_id": uuid7(),
                    "event_type": "evidence.recorded",
                    "timestamp": datetime(2026, 9, 1, 12, tzinfo=UTC)
                    + timedelta(seconds=index),
                    "entity_type": "evidence",
                    "entity_id": uuid7(),
                    "payload": {"result": index},
                    "deduplication_key": f"source-{index}",
                    "schema_version": "1",
                }
            )
        )
    return ledger


def _tamper(path: Path, mutation: str) -> None:
    with sqlite3.connect(path) as connection:
        trigger = (
            "audit_events_no_delete"
            if mutation.startswith("delete_")
            else "audit_events_no_update"
        )
        connection.execute(f"DROP TRIGGER {trigger}")

        if mutation == "payload":
            connection.execute(
                "UPDATE audit_events SET payload_json = ? WHERE sequence = 2",
                ('{"result":"altered"}',),
            )
        elif mutation == "delete_middle":
            connection.execute("DELETE FROM audit_events WHERE sequence = 2")
        elif mutation == "delete_tail":
            connection.execute("DELETE FROM audit_events WHERE sequence = 3")
        elif mutation == "event_hash":
            connection.execute(
                "UPDATE audit_events SET event_hash = ? WHERE sequence = 2",
                ("f" * 64,),
            )
        elif mutation == "previous_hash":
            connection.execute(
                "UPDATE audit_events SET previous_event_hash = ? WHERE sequence = 2",
                ("f" * 64,),
            )
        elif mutation == "sequence_gap":
            connection.execute(
                "UPDATE audit_events SET sequence = 4 WHERE sequence = 2"
            )
        elif mutation == "reordered":
            connection.execute(
                "UPDATE audit_events SET sequence = 99 WHERE sequence = 1"
            )
            connection.execute(
                "UPDATE audit_events SET sequence = 1 WHERE sequence = 2"
            )
            connection.execute(
                "UPDATE audit_events SET sequence = 2 WHERE sequence = 99"
            )
        else:
            raise AssertionError(f"unsupported test mutation: {mutation}")


@pytest.mark.parametrize(
    "mutation",
    [
        "payload",
        "delete_middle",
        "delete_tail",
        "event_hash",
        "previous_hash",
        "sequence_gap",
        "reordered",
    ],
)
def test_verify_chain_detects_direct_database_tampering(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "ledger.db"
    ledger = _populated_ledger(path)
    _tamper(path, mutation)

    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()
