"""Original-journal corruption, complete membership and interrupted-write controls."""

# ruff: noqa: E402
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from test_stage1_controlled_contracts import controlled_arguments
from test_stage1_synthetic_research_execution import BASE

from drift.evaluator.session_observer import RebalancePreviewV1
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.loop import stage1_controlled_contracts as C
from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
from drift.loop.stage1_controlled_journal import (
    CapturedControlledJournalV1,
    ControlledJournalWriterV1,
)
from drift.loop.stage1_controlled_readback import (
    ControlledCampaignReadbackV1,
    read_controlled_campaign,
)
from drift.serialization.canonical import canonical_json

READ_KEYS = (
    "origin",
    "campaign",
    "arms",
    "bindings",
    "expected_run_ids",
    "provenance",
    "clock",
)


def read(
    args: dict[str, Any], allocation_id: Any, **kwargs: Any
) -> ControlledCampaignReadbackV1:
    return read_controlled_campaign(
        **{key: args[key] for key in READ_KEYS}, allocation_id=allocation_id, **kwargs
    )


def capture(args: dict[str, Any], allocation_id: Any) -> CapturedControlledJournalV1:
    return CapturedControlledJournalV1(
        origin=args["origin"], allocation_id=allocation_id, observed_at=args["clock"]()
    )


@pytest.fixture(scope="module")
def original_campaign(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], Any]:
    args = controlled_arguments(tmp_path_factory.mktemp("controlled-original"))
    executed = execute_controlled_campaign(**args)
    assert executed.m0_status == "completed"
    assert read(args, executed.allocation_id).status == "VERIFIED_COMPLETE"
    return args, executed


@pytest.fixture
def retained_copy(
    original_campaign: tuple[dict[str, Any], Any], tmp_path: Path
) -> tuple[dict[str, Any], Any]:
    source, executed = original_campaign
    args = dict(source)
    target = tmp_path / "original.sqlite3"
    shutil.copy2(source["origin"].ledger_path, target)
    args["origin"] = replace(source["origin"], ledger_path=target)
    args["clock"] = lambda: BASE + timedelta(days=2)
    return args, executed


def append_record(
    args: dict[str, Any],
    captured: CapturedControlledJournalV1,
    record: C.ControlledRecord,
    *,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    payload = json.loads(
        canonical_json(
            C.ControlledEnvelopeV1.create(
                issuer=args["origin"].issuer_instance_id,
                plan=captured.plan,
                record=record,
            )
        )
    )
    if mutate is not None:
        mutate(payload)
    SQLiteLedger(args["origin"].ledger_path).append(
        AuditEventDraft(
            event_id=uuid7(),
            event_type=C.EVENT_PREFIX + record.kind,
            timestamp=BASE + timedelta(days=1),
            entity_type=C.ENTITY,
            entity_id=captured.plan.original_account.allocation_id,
            payload=payload,
            deduplication_key="synthetic-corruption:" + str(uuid7()),
            schema_version="1",
        )
    )


@pytest.mark.parametrize("kind", ["grant", "input_witness", "no_attempt"])
def test_trailing_hash_valid_undeclared_phase_cannot_disappear(
    retained_copy: tuple[dict[str, Any], Any], kind: str
) -> None:
    args, executed = retained_copy
    captured = capture(args, executed.allocation_id)
    grant_row = next(row for row in captured.rows if row.record.kind == "grant")
    record: C.ControlledRecord
    if kind == "no_attempt":
        record = C.NoAttemptRecordV1(
            checkpoint_id="UNDECLARED", grant=grant_row.ref, reason="EXPIRED"
        )
    else:
        record = next(
            row.record for row in captured.rows if row.record.kind == kind
        ).model_copy(update={"checkpoint_id": "UNDECLARED"})
    append_record(args, captured, record)
    args["origin"].verified_events()  # The ordinary hash chain is genuinely valid.
    with pytest.raises(ValueError, match="CONTROLLED"):
        read(args, executed.allocation_id)


@pytest.mark.parametrize(
    "field", ["allocation_id", "arm_id", "run_id", "manifest_hash"]
)
def test_original_envelope_changes_cannot_filter_a_record_out(
    retained_copy: tuple[dict[str, Any], Any], field: str
) -> None:
    args, executed = retained_copy
    captured = capture(args, executed.allocation_id)
    record = next(row.record for row in captured.rows if row.record.kind == "grant")
    value = (
        str(uuid7())
        if field == "allocation_id"
        else ("f" * 64 if field == "manifest_hash" else "FOREIGN")
    )
    append_record(
        args, captured, record, mutate=lambda payload: payload.update({field: value})
    )
    args["origin"].verified_events()
    with pytest.raises(ValueError, match="CONTROLLED"):
        read(args, executed.allocation_id)


@pytest.mark.parametrize("kind", ["grant", "input_witness", "no_attempt"])
def test_undeclared_phase_before_completion_cannot_disappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    args = controlled_arguments(tmp_path)
    original_append = ControlledJournalWriterV1.append
    inserted = False

    def insert(
        self: ControlledJournalWriterV1, record: C.ControlledRecord, **kwargs: Any
    ) -> Any:
        nonlocal inserted
        event = original_append(self, record, **kwargs)
        if not inserted and record.kind == "research_output":
            inserted = True
            captured = CapturedControlledJournalV1(
                origin=self.origin,
                allocation_id=self.plan.original_account.allocation_id,
                observed_at=event.timestamp,
            )
            grant_row = next(row for row in captured.rows if row.record.kind == "grant")
            bad: C.ControlledRecord
            if kind == "no_attempt":
                bad = C.NoAttemptRecordV1(
                    checkpoint_id="UNDECLARED", grant=grant_row.ref, reason="EXPIRED"
                )
            else:
                bad = next(
                    row.record for row in captured.rows if row.record.kind == kind
                ).model_copy(update={"checkpoint_id": "UNDECLARED"})
            original_append(self, bad, key="undeclared:" + kind, at=event.timestamp)
        return event

    with monkeypatch.context() as patch:
        patch.setattr(ControlledJournalWriterV1, "append", insert)
        executed = execute_controlled_campaign(**args)
    assert executed.m0_status == "completed"
    args["origin"].verified_events()
    with pytest.raises(ValueError, match="UNDECLARED"):
        read(args, executed.allocation_id)


@pytest.mark.parametrize(
    "phase",
    [
        "input_witness",
        "grant",
        "attempt",
        "cost",
        "validation",
        "research_output",
        "decision",
        "execution",
    ],
)
@pytest.mark.parametrize("lost_ack", [False, True])
def test_interrupted_original_lifecycle_is_unresolved_and_cannot_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, lost_ack: bool
) -> None:
    args = controlled_arguments(tmp_path)
    original_append = ControlledJournalWriterV1.append
    injected = False

    def interrupted(
        self: ControlledJournalWriterV1, record: C.ControlledRecord, **kwargs: Any
    ) -> Any:
        nonlocal injected
        at_checkpoint = (
            not isinstance(record, C.DecisionRecordV1)
            or record.checkpoint_id is not None
        )
        if not injected and record.kind == phase and at_checkpoint:
            injected = True
            if lost_ack:
                original_append(self, record, **kwargs)
            raise OSError("injected original retention failure")
        return original_append(self, record, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ControlledJournalWriterV1, "append", interrupted)
        executed = execute_controlled_campaign(**args)
    assert injected and executed.m0_status == "failed"
    before = args["origin"].verified_events()
    report = read(args, executed.allocation_id)
    assert report.status == "UNRESOLVED"
    assert not any(trial.complete_interval for trial in report.trials)
    assert not report.authorizes_trading
    assert args["origin"].verified_events() == before
    with pytest.raises((ValueError, RuntimeError)):
        execute_controlled_campaign(**args)
    assert args["origin"].verified_events() == before


def test_original_prefix_does_not_see_future_corruption(
    retained_copy: tuple[dict[str, Any], Any],
) -> None:
    args, executed = retained_copy
    captured = capture(args, executed.allocation_id)
    assert captured.tip is not None
    before = read(
        args, executed.allocation_id, as_of_event_hash=captured.tip.event_hash
    )
    record = next(
        row.record for row in captured.rows if row.record.kind == "grant"
    ).model_copy(update={"checkpoint_id": "UNDECLARED"})
    append_record(args, captured, record)
    assert (
        read(args, executed.allocation_id, as_of_event_hash=captured.tip.event_hash)
        == before
    )
    with pytest.raises(ValueError):
        read(args, executed.allocation_id)


def test_repeated_reopen_preserves_account_and_never_dispatches(
    retained_copy: tuple[dict[str, Any], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    args, executed = retained_copy
    before = args["origin"].verified_events()
    first = read(args, executed.allocation_id)
    second = read(args, executed.allocation_id)
    assert first == second
    assert second.independent_account_count == 1
    assert args["origin"].verified_events() == before


def test_cold_replay_refuses_a_different_installed_source_inventory(
    retained_copy: tuple[dict[str, Any], Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import drift.loop.stage1_controlled_readback as reader

    args, executed = retained_copy
    assert read(args, executed.allocation_id).status == "VERIFIED_COMPLETE"
    monkeypatch.setattr(reader, "drift_source_inventory_hash", lambda: "0" * 64)
    with pytest.raises(ValueError, match="ORIGINAL_INSTALLED_SOURCE"):
        read(args, executed.allocation_id)


@pytest.mark.parametrize("checkpoint_execution", [False, True])
def test_missing_original_execution_record_is_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint_execution: bool
) -> None:
    """The real evaluator authorizes and fills; only journal retention is omitted."""
    from drift.evaluator.session_observer import RebalancePreviewV1

    args = controlled_arguments(tmp_path)
    index = (
        args["checkpoints"][0].session_index
        if checkpoint_execution
        else args["initial_decision_index"]
    ) + 1
    original_append = ControlledJournalWriterV1.append
    omitted = False

    def omit(
        self: ControlledJournalWriterV1, record: C.ControlledRecord, **kwargs: Any
    ) -> Any:
        nonlocal omitted
        if isinstance(record, C.ExecutionRecordV1):
            preview = record.preview.parse(RebalancePreviewV1)
            if preview.session_index == index:
                omitted = True
                # authorize_rebalance does not consume append's return value.
                # Keep a genuinely valid original ledger, not a filtered reader.
                return self.origin.verified_events()[-1]
        return original_append(self, record, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ControlledJournalWriterV1, "append", omit)
        executed = execute_controlled_campaign(**args)
    assert omitted and executed.m0_status == "completed"
    args["origin"].verified_events()
    report = read(args, executed.allocation_id)
    assert report.status == "UNRESOLVED"
    assert "MISSING_ORIGINAL_EXECUTION_RECORD" in report.reasons
    assert not report.economics.complete
    if checkpoint_execution:
        assert report.trials[0].outcome == "UNRESOLVED"
        assert not report.trials[0].complete_interval


def _write_reordered_journal(original: list[Any], target: Path) -> None:
    """Rebuild a fully valid audit hash chain after moving original events."""
    writer = SQLiteLedger(target)
    hashes: dict[str, str] = {}

    def remap(value: Any) -> Any:
        if isinstance(value, str):
            return hashes.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    for event in original:
        payload = remap(json.loads(canonical_json(event.payload)))
        appended = writer.append(
            AuditEventDraft(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=payload,
                deduplication_key=event.deduplication_key,
                schema_version=event.schema_version,
            )
        )
        hashes[event.event_hash] = appended.event_hash
    writer.verify_chain()


def test_equal_clock_execution_after_marked_book_is_not_certified(
    tmp_path: Path,
) -> None:
    """An append-valid authorization cannot follow its own committed close."""
    args = controlled_arguments(tmp_path / "source")
    args["clock"] = lambda: BASE + timedelta(hours=1)
    executed = execute_controlled_campaign(**args)
    assert read(args, executed.allocation_id).status == "VERIFIED_COMPLETE"
    captured = capture(args, executed.allocation_id)
    execution = next(row for row in captured.rows if row.record.kind == "execution")
    assert isinstance(execution.record, C.ExecutionRecordV1)
    preview = execution.record.preview.parse(RebalancePreviewV1)
    marked = next(
        row
        for row in captured.rows
        if isinstance(row.record, C.ObservationRecordV1)
        and row.record.observation.session_index == preview.session_index
    )
    original = list(args["origin"].verified_events())
    moved = next(
        event for event in original if event.event_id == execution.event.event_id
    )
    original.remove(moved)
    target_index = next(
        i for i, event in enumerate(original) if event.event_id == marked.event.event_id
    )
    original.insert(target_index + 1, moved)
    target = tmp_path / "late-authorization.sqlite3"
    _write_reordered_journal(original, target)
    args["origin"] = replace(args["origin"], ledger_path=target)
    with pytest.raises(ValueError, match="CONTROLLED_REFERENCE_NOT_CAUSAL"):
        read(args, executed.allocation_id)


def test_equal_clock_decision_before_research_is_not_certified(
    tmp_path: Path,
) -> None:
    """Rebuild a hash-valid original journal with a genuine causal inversion."""
    args = controlled_arguments(tmp_path / "source")
    args["clock"] = lambda: BASE + timedelta(hours=1)
    executed = execute_controlled_campaign(**args)
    assert read(args, executed.allocation_id).status == "VERIFIED_COMPLETE"
    original = list(args["origin"].verified_events())
    decision = next(
        event
        for event in original
        if event.event_type == C.EVENT_PREFIX + "decision"
        and event.payload["record"]["checkpoint_id"] == "CKPT-001"
    )
    observation_id = decision.payload["record"]["observation"]["event_id"]
    original.remove(decision)
    position = next(
        i for i, event in enumerate(original) if str(event.event_id) == observation_id
    )
    original.insert(position + 1, decision)
    target = tmp_path / "causally-reordered.sqlite3"
    _write_reordered_journal(original, target)
    args["origin"] = replace(args["origin"], ledger_path=target)
    with pytest.raises(ValueError, match="CONTROLLED_REFERENCE_NOT_CAUSAL"):
        read(args, executed.allocation_id)
