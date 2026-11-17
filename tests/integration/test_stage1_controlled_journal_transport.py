"""Bounded original journal storage; these blobs are not financial evidence."""

# ruff: noqa: E402
import base64
import hashlib
import json
import random
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid7

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from test_stage1_controlled_contracts import controlled_arguments
from test_stage1_synthetic_research_execution import BASE

from drift.domain.events import AuditEvent
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop import stage1_controlled_contracts as C
from drift.loop import stage1_controlled_transport as T
from drift.loop.stage1_controlled_campaign import execute_controlled_campaign
from drift.loop.stage1_controlled_journal import (
    CapturedControlledJournalV1,
    ControlledJournalWriterV1,
    append_controlled_cost_correction,
    reference,
)
from drift.loop.stage1_controlled_readback import read_controlled_campaign
from drift.serialization.canonical import canonical_json


class StorageBlob(BaseModel):
    value: str


@pytest.fixture(scope="module")
def large_blob() -> StorageBlob:
    # Deterministic low-compressibility bytes exercise the actual inline cap.
    return StorageBlob(value=random.Random(570).randbytes(1_100_000).hex())


def test_large_canonical_payload_roundtrip_preserves_inline_cap(
    large_blob: StorageBlob,
) -> None:
    assert len(canonical_json(large_blob)) < C.MAX_CONTEXT_BYTES
    with pytest.raises(ValueError, match="1048576"):
        C.RetainedCanonicalPayloadV1.retain(large_blob)
    retained = C.retain_canonical_payload(large_blob)
    assert retained.original_bytes() == canonical_json(large_blob)
    assert retained.parse(StorageBlob) == large_blob
    assert C.MAX_RECORD_BYTES == 1_048_576
    assert C.MAX_CONTEXT_BYTES == 33_554_432


def test_small_canonical_payload_keeps_original_v1_bytes() -> None:
    blob = StorageBlob(value="original small payload")
    original = C.RetainedCanonicalPayloadV1.retain(blob)
    retained = C.retain_canonical_payload(blob)
    assert type(retained) is C.RetainedCanonicalPayloadV1
    assert canonical_json(retained) == canonical_json(original)


@pytest.mark.parametrize("payload", [None, "malformed", 1, []])
def test_transport_rejects_nonmapping_original_payload(
    tmp_path: Path, payload: Any
) -> None:
    issuer = uuid7()
    event = SQLiteLedger(tmp_path / "malformed.sqlite3").append(
        AuditEventDraft(
            event_id=uuid7(),
            event_type=T.CHUNK_EVENT,
            timestamp=BASE,
            entity_type=C.ENTITY,
            entity_id=uuid7(),
            payload=payload,
            deduplication_key="malformed",
            schema_version="2",
        )
    )
    with pytest.raises(ValueError, match="MALFORMED_ORIGINAL_RECORD"):
        T.decode_original_events((event,), issuer)


def test_large_payload_factory_keeps_the_original_decoded_budget() -> None:
    with pytest.raises(ValueError, match="CONTROLLED_PAYLOAD_TOO_LARGE"):
        C.retain_canonical_payload(StorageBlob(value="x" * C.MAX_CONTEXT_BYTES))


@pytest.fixture(scope="module")
def original_journal(
    tmp_path_factory: pytest.TempPathFactory,
) -> CapturedControlledJournalV1:
    args = controlled_arguments(tmp_path_factory.mktemp("transport-original"))
    executed = execute_controlled_campaign(**args)
    assert executed.m0_status == "completed"
    return CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=executed.allocation_id,
        observed_at=args["clock"](),
    )


def storage_writer(
    tmp_path: Path, source: CapturedControlledJournalV1
) -> ControlledJournalWriterV1:
    # Retain the actual original account prefix, before any controlled append.
    origin = ConfiguredLocalSyntheticOriginV1(
        tmp_path / "original.sqlite3", source.origin.issuer_instance_id
    )
    ledger = SQLiteLedger(origin.ledger_path)
    for event in source.events[: source.manifest.sequence]:
        ledger.append(
            AuditEventDraft(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=event.payload,
                deduplication_key=event.deduplication_key,
                schema_version=event.schema_version,
            )
        )
    writer = ControlledJournalWriterV1(
        origin=origin, plan=source.plan, clock=lambda: source.observed_at
    )
    writer.append(source.manifest.record, key="manifest")
    return writer


def test_large_logical_record_roundtrips_in_bounded_original_events(
    tmp_path: Path,
    original_journal: CapturedControlledJournalV1,
    large_blob: StorageBlob,
) -> None:
    writer = storage_writer(tmp_path, original_journal)
    record = C.ContainmentRecordV1(
        observation=original_journal.manifest.ref, reason=large_blob.value
    )
    event = writer.append(record, key="large-storage-only")
    events = writer.origin.verified_events()
    assert all(
        len(canonical_json(item.payload)) <= C.MAX_RECORD_BYTES for item in events
    )
    captured = CapturedControlledJournalV1(
        origin=writer.origin,
        allocation_id=writer.plan.original_account.allocation_id,
        observed_at=original_journal.observed_at,
    )
    assert len(captured.rows) == 2
    assert captured.rows[-1].record == record
    assert captured.rows[-1].ref == reference(event)
    assert captured.rows[-1].sequence == len(events) - 1
    assert captured.events[-1] == event
    assert captured.physical_events == tuple(
        item for item in events if item.event_type.startswith(C.EVENT_PREFIX)
    )


def test_captured_prefix_does_not_reparse_bulk_payload_for_each_consumer(
    large_journal: CapturedControlledJournalV1, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = canonical_json(large_journal.events)
    parsed_bytes = 0
    parse = AuditEvent.model_validate_json

    def measured_parse(
        cls: type[AuditEvent], /, data: str | bytes | bytearray, **kwargs: Any
    ) -> AuditEvent:
        nonlocal parsed_bytes
        parsed_bytes += len(data)
        return parse(data, **kwargs)

    # Count actual parser input, rather than imposing a host-dependent timer.
    # Each consumer still receives and checks a real complete original prefix.
    monkeypatch.setattr(AuditEvent, "model_validate_json", classmethod(measured_parse))
    for _ in range(8):
        events = large_journal.origin.verified_events()
        assert canonical_json(events) == expected
        assert all(
            event is not original
            and event.event_id is not original.event_id
            and event.entity_id is not original.entity_id
            for event, original in zip(events, large_journal.events, strict=True)
        )
    assert parsed_bytes <= len(expected), "immutable bulk payload was repeatedly parsed"


def test_captured_payload_graph_is_immutable_and_prefix_stays_fixed(
    tmp_path: Path, original_journal: CapturedControlledJournalV1
) -> None:
    writer = storage_writer(tmp_path, original_journal)
    captured = CapturedControlledJournalV1(
        origin=writer.origin,
        allocation_id=writer.plan.original_account.allocation_id,
        observed_at=original_journal.observed_at,
    )
    expected = canonical_json(captured.events)

    def require_immutable(value: Any) -> None:
        if isinstance(value, Mapping):
            assert type(value) is MappingProxyType
            with pytest.raises(TypeError):
                cast(Any, value)["changed"] = None
            for item in value.values():
                require_immutable(item)
        elif isinstance(value, tuple):
            for item in value:
                require_immutable(item)
        else:
            assert type(value) in (type(None), bool, int, float, str)

    for event in captured.origin.verified_events():
        require_immutable(event.payload)
    writer.append(
        C.ContainmentRecordV1(
            observation=captured.manifest.ref, reason="Later original evidence"
        ),
        key="after-capture",
    )
    assert canonical_json(captured.origin.verified_events()) == expected
    assert len(writer.origin.verified_events()) == len(captured.events) + 1
    historical = CapturedControlledJournalV1(
        origin=writer.origin,
        allocation_id=writer.plan.original_account.allocation_id,
        observed_at=original_journal.observed_at,
        as_of_event_hash=captured.manifest.event.event_hash,
    )
    assert canonical_json(historical.events) == expected


def test_small_logical_record_keeps_original_v1_event(
    tmp_path: Path, original_journal: CapturedControlledJournalV1
) -> None:
    writer = storage_writer(tmp_path, original_journal)
    record = C.ContainmentRecordV1(
        observation=original_journal.manifest.ref, reason="storage-only"
    )
    before = len(writer.origin.verified_events())
    event = writer.append(record, key="small-storage-only")
    assert len(writer.origin.verified_events()) == before + 1
    assert event.schema_version == "1"
    assert canonical_json(event.payload) == canonical_json(
        C.ControlledEnvelopeV1.create(
            issuer=writer.origin.issuer_instance_id, plan=writer.plan, record=record
        )
    )


@pytest.mark.parametrize(
    "mutation", ["size", "hash", "reversed", "corrupt", "trailing", "oversized"]
)
def test_segmented_payload_refuses_corruption_and_resource_claims(
    large_blob: StorageBlob, mutation: str
) -> None:
    retained = C.retain_canonical_payload(large_blob)
    assert isinstance(retained, C.SegmentedCanonicalPayloadV2)
    data = retained.model_dump(mode="python")
    if mutation == "size":
        data["size"] -= 1
    elif mutation == "oversized":
        data["size"] = C.MAX_CONTEXT_BYTES + 1
    elif mutation == "hash":
        data["sha256"] = "0" * 64
    else:
        encoded = "".join(retained.data_parts)
        if mutation == "trailing":
            encoded = base64.b64encode(base64.b64decode(encoded) + b"trailing").decode(
                "ascii"
            )
        elif mutation == "corrupt":
            encoded = "AAAA" + encoded[4:]
        else:
            encoded = "".join(reversed(retained.data_parts))
        data["data_parts"] = tuple(
            encoded[i : i + C.MAX_RECORD_BYTES]
            for i in range(0, len(encoded), C.MAX_RECORD_BYTES)
        )
    with pytest.raises(ValueError):
        C.SegmentedCanonicalPayloadV2.model_validate(data).original_bytes()


def test_segment_count_and_direct_decode_cannot_bypass_original_budget(
    large_blob: StorageBlob,
) -> None:
    retained = C.retain_canonical_payload(large_blob)
    assert isinstance(retained, C.SegmentedCanonicalPayloadV2)
    with pytest.raises(ValueError):
        C.SegmentedCanonicalPayloadV2(
            size=1, sha256="0" * 64, data_parts=("AAAA",) * 65
        )
    forged = C.SegmentedCanonicalPayloadV2.model_construct(
        **(retained.model_dump() | {"size": C.MAX_CONTEXT_BYTES + 1})
    )
    with pytest.raises(ValueError, match="TOO_LARGE"):
        forged.original_bytes()


@pytest.fixture(scope="module")
def large_journal(
    tmp_path_factory: pytest.TempPathFactory,
    original_journal: CapturedControlledJournalV1,
    large_blob: StorageBlob,
) -> CapturedControlledJournalV1:
    writer = storage_writer(
        tmp_path_factory.mktemp("transport-large"), original_journal
    )
    writer.append(
        C.ContainmentRecordV1(
            observation=original_journal.manifest.ref, reason=large_blob.value
        ),
        key="large-storage-only",
    )
    return CapturedControlledJournalV1(
        origin=writer.origin,
        allocation_id=writer.plan.original_account.allocation_id,
        observed_at=original_journal.observed_at,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "corrupt",
        "reordered",
        "duplicate",
        "foreign_allocation",
        "foreign_record",
        "foreign_issuer",
        "late",
        "orphan",
        "oversized",
        "unknown_version",
    ],
)
def test_valid_chain_cannot_launder_broken_chunk_inventory(
    tmp_path: Path, large_journal: CapturedControlledJournalV1, mutation: str
) -> None:
    events = list(large_journal.events)
    indexes = [i for i, event in enumerate(events) if event.event_type == T.CHUNK_EVENT]
    if mutation == "reordered":
        a, b = indexes[:2]
        events[a], events[b] = events[b], events[a]
    elif mutation == "missing":
        events.pop(indexes[1])
    elif mutation == "orphan":
        events.append(
            events[indexes[0]].model_copy(
                update={"event_id": uuid7(), "deduplication_key": "orphan"}
            )
        )
    origin = ConfiguredLocalSyntheticOriginV1(
        tmp_path / "altered.sqlite3", large_journal.origin.issuer_instance_id
    )
    ledger = SQLiteLedger(origin.ledger_path)
    hashes: dict[Any, str] = {}
    first_chunk = events[indexes[0]].event_id if mutation != "reordered" else None
    for event in events:
        payload = json.loads(canonical_json(event.payload))
        timestamp, entity_id, schema = (
            event.timestamp,
            event.entity_id,
            event.schema_version,
        )
        if event.event_id == first_chunk:
            if mutation == "corrupt":
                payload["data"] = ("A" if payload["data"][0] != "A" else "B") + payload[
                    "data"
                ][1:]
            elif mutation == "foreign_allocation":
                entity_id = uuid7()
                payload["allocation_id"] = str(entity_id)
            elif mutation == "foreign_record":
                payload["record_id"] = str(uuid7())
            elif mutation == "foreign_issuer":
                payload["issuer_instance_id"] = str(uuid7())
            elif mutation == "late":
                timestamp += timedelta(seconds=1)
            elif mutation == "unknown_version":
                schema = "3"
        if payload.get("profile") == T.COMMIT_PROFILE:
            for ref in payload["parts"]:
                from uuid import UUID

                ident = UUID(ref["event_id"])
                ref["event_hash"] = hashes.get(ident, ref["event_hash"])
            if mutation == "duplicate":
                payload["parts"][1] = dict(payload["parts"][0])
            elif mutation == "oversized":
                payload["size"] = T.MAX_LOGICAL_RECORD_BYTES + 1
        appended = ledger.append(
            AuditEventDraft(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=timestamp,
                entity_type=event.entity_type,
                entity_id=entity_id,
                payload=payload,
                deduplication_key=event.deduplication_key,
                schema_version=schema,
            )
        )
        hashes[event.event_id] = appended.event_hash
    origin.verified_events()  # The altered original chain is structurally valid.
    with pytest.raises(ValueError, match="CONTROLLED"):
        CapturedControlledJournalV1(
            origin=origin,
            allocation_id=large_journal.plan.original_account.allocation_id,
            observed_at=large_journal.observed_at + timedelta(seconds=2),
        )


def test_snapshot_inside_chunk_group_is_incomplete(
    large_journal: CapturedControlledJournalV1,
) -> None:
    part = next(e for e in large_journal.events if e.event_type == T.CHUNK_EVENT)
    origin = ConfiguredLocalSyntheticOriginV1(
        large_journal.origin.ledger_path, large_journal.origin.issuer_instance_id
    )
    with pytest.raises(ValueError, match="ORPHAN_OR_INCOMPLETE"):
        CapturedControlledJournalV1(
            origin=origin,
            allocation_id=large_journal.plan.original_account.allocation_id,
            observed_at=large_journal.observed_at,
            as_of_event_hash=part.event_hash,
        )


@pytest.mark.parametrize("fault", ["before-first", "after-first", "after-commit"])
def test_interrupted_transport_never_retries_or_manufactures_completion(
    tmp_path: Path,
    original_journal: CapturedControlledJournalV1,
    large_blob: StorageBlob,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    writer = storage_writer(tmp_path, original_journal)
    append = writer._ledger.append
    injected = False

    def fail_once(draft: AuditEventDraft) -> Any:
        nonlocal injected
        target = (
            draft.event_type == T.CHUNK_EVENT
            if fault != "after-commit"
            else isinstance(draft.payload, Mapping)
            and draft.payload.get("profile") == T.COMMIT_PROFILE
        )
        if not injected and target:
            injected = True
            if fault != "before-first":
                append(draft)
            raise OSError("synthetic storage acknowledgment failure")
        return append(draft)

    monkeypatch.setattr(writer._ledger, "append", fail_once)
    record = C.ContainmentRecordV1(
        observation=original_journal.manifest.ref, reason=large_blob.value
    )
    with pytest.raises(OSError, match="acknowledgment"):
        writer.append(record, key="large")
    count = len(writer.origin.verified_events())
    with pytest.raises(ValueError, match="CLOSED_OR_UNCERTAIN"):
        writer.append(record, key="another-attempt")
    assert len(writer.origin.verified_events()) == count
    with pytest.raises(ValueError, match="ALREADY_RESERVED_NO_RETRY"):
        ControlledJournalWriterV1(
            origin=writer.origin,
            plan=writer.plan,
            clock=lambda: original_journal.observed_at,
        )
    if fault == "after-first":
        with pytest.raises(ValueError, match="ORPHAN_OR_INCOMPLETE"):
            CapturedControlledJournalV1(
                origin=writer.origin,
                allocation_id=writer.plan.original_account.allocation_id,
                observed_at=original_journal.observed_at,
            )
    else:
        recovered = CapturedControlledJournalV1(
            origin=writer.origin,
            allocation_id=writer.plan.original_account.allocation_id,
            observed_at=original_journal.observed_at,
        )
        assert len(recovered.rows) == (2 if fault == "after-commit" else 1)
        if fault == "after-commit":
            assert recovered.rows[-1].record == record


def test_large_original_transport_is_cold_readable_in_a_fresh_process(
    large_journal: CapturedControlledJournalV1,
) -> None:
    script = """
import hashlib, sys
from datetime import datetime
from uuid import UUID
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_controlled_journal import CapturedControlledJournalV1
from pathlib import Path
origin = ConfiguredLocalSyntheticOriginV1(Path(sys.argv[1]), UUID(sys.argv[2]))
captured = CapturedControlledJournalV1(
    origin=origin, allocation_id=UUID(sys.argv[3]),
    observed_at=datetime.fromisoformat(sys.argv[4]))
print(hashlib.sha256(captured.rows[-1].record.reason.encode()).hexdigest())
"""
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(large_journal.origin.ledger_path),
            str(large_journal.origin.issuer_instance_id),
            str(large_journal.plan.original_account.allocation_id),
            large_journal.observed_at.isoformat(),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert isinstance(large_journal.rows[-1].record, C.ContainmentRecordV1)
    assert (
        process.stdout.strip()
        == hashlib.sha256(large_journal.rows[-1].record.reason.encode()).hexdigest()
    )


READ_KEYS = (
    "origin",
    "campaign",
    "arms",
    "bindings",
    "expected_run_ids",
    "provenance",
    "clock",
)


@pytest.fixture(scope="module")
def large_manifest_campaign(
    tmp_path_factory: pytest.TempPathFactory,
    large_blob: StorageBlob,
) -> tuple[dict[str, Any], Any, CapturedControlledJournalV1]:
    from drift.intelligence.contracts import ArtifactReference

    args = controlled_arguments(tmp_path_factory.mktemp("large-manifest"))
    # Explicit large metadata exercises the composed writer/reader. This tiny
    # development fixture does not replace the full456 campaign proof.
    args["clock_policy"] = ArtifactReference(
        id="fixture:" + large_blob.value, version="1", sha256="1" * 64
    )
    checkpoint = args["checkpoints"][0]
    args["checkpoints"] = (
        checkpoint.model_copy(
            update={
                "fixture": checkpoint.fixture.model_copy(
                    update={"cost_amount": Decimal("8")}
                )
            }
        ),
    )
    executed = execute_controlled_campaign(**args)
    assert executed.m0_status == "completed"
    captured = CapturedControlledJournalV1(
        origin=args["origin"],
        allocation_id=executed.allocation_id,
        observed_at=args["clock"](),
    )
    return args, executed, captured


def test_large_manifest_commits_after_its_chunks_and_accounts_all_originals(
    large_manifest_campaign: tuple[dict[str, Any], Any, CapturedControlledJournalV1],
) -> None:
    args, executed, captured = large_manifest_campaign
    report = read_controlled_campaign(
        **{key: args[key] for key in READ_KEYS}, allocation_id=executed.allocation_id
    )
    assert report.status == "VERIFIED_COMPLETE", report.reasons
    assert captured.manifest.event.schema_version == "2"
    assert any(
        e.event_type == T.CHUNK_EVENT
        for e in captured.events[: captured.manifest.sequence]
    )
    assert report.accounted_event_hashes == tuple(
        e.event_hash for e in captured.physical_events
    )
    assert len(report.accounted_event_hashes) > len(captured.rows)
    assert report.authorizes_trading is False


def test_large_post_terminal_cost_correction_preserves_asof_and_idempotency(
    tmp_path: Path,
    large_blob: StorageBlob,
    large_manifest_campaign: tuple[dict[str, Any], Any, CapturedControlledJournalV1],
) -> None:
    from drift.intelligence.contracts import StoredArtifactRef
    from drift.intelligence.receipts import create_cost_receipt

    source, executed, captured = large_manifest_campaign
    target = tmp_path / "correction.sqlite3"
    shutil.copy2(source["origin"].ledger_path, target)
    origin = ConfiguredLocalSyntheticOriginV1(
        target, source["origin"].issuer_instance_id
    )
    args = {key: source[key] for key in READ_KEYS} | {
        "origin": origin,
        "clock": lambda: BASE + timedelta(hours=3),
    }
    original = next(
        row.record.original
        for row in captured.rows
        if isinstance(row.record, C.CostRecordV1)
    )
    correction = create_cost_receipt(
        receipt_id="large-actual-cost",
        scope=original.scope,
        category=original.category,
        billing_identity=original.billing_identity,
        amount_basis="actual",
        attempt_id=original.attempt_id,
        raw_evidence_ref=StoredArtifactRef(
            artifact_id="synthetic-bill",
            kind="other",
            content_hash="2" * 64,
            location="synthetic://" + large_blob.value,
        ),
        recorded_at=BASE + timedelta(hours=1),
        amount="9",
        currency="USD",
        supersedes_receipt_id=original.receipt_id,
    )
    assert captured.tip is not None
    kwargs = dict(
        origin=origin,
        allocation_id=executed.allocation_id,
        checkpoint_id=source["checkpoints"][0].checkpoint_id,
        correction=correction,
        clock=lambda: BASE + timedelta(hours=2),
    )
    first = append_controlled_cost_correction(**kwargs)
    size = len(origin.verified_events())
    assert append_controlled_cost_correction(**kwargs) == first
    assert len(origin.verified_events()) == size
    now = read_controlled_campaign(**args, allocation_id=executed.allocation_id)
    before = read_controlled_campaign(
        **args,
        allocation_id=executed.allocation_id,
        as_of_event_hash=captured.tip.event_hash,
    )
    assert now.status == before.status == "VERIFIED_COMPLETE"
    assert before.trials[0].operating_cost.amount == Decimal("8")
    assert now.trials[0].operating_cost.amount == Decimal("9")
    assert now.original_result == before.original_result


def test_transport_groups_interleaved_allocations_by_original_commit(
    tmp_path: Path,
    original_journal: CapturedControlledJournalV1,
    large_blob: StorageBlob,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This isolates the transport adapter. Domain manifest/account joins remain
    # the separate journal reader's responsibility; no execution is claimed.
    writer = storage_writer(tmp_path, original_journal)
    record = C.ContainmentRecordV1(
        observation=original_journal.manifest.ref, reason=large_blob.value
    )
    first = C.ControlledEnvelopeV1.create(
        issuer=writer.origin.issuer_instance_id, plan=writer.plan, record=record
    )
    second = first.model_copy(
        update={
            "allocation_id": uuid7(),
            "account_id": "transport-only-other-allocation",
        }
    )
    append = writer._ledger.append
    inserted: list[Any] = []

    def interleave(draft: AuditEventDraft) -> Any:
        event = append(draft)
        if draft.event_type == T.CHUNK_EVENT and not inserted:
            inserted.append(None)
            inserted[0] = T.append_envelope(
                writer._ledger,
                second,
                when=original_journal.observed_at,
                key="interleaved-second",
            )
        return event

    monkeypatch.setattr(writer._ledger, "append", interleave)
    final = T.append_envelope(
        writer._ledger,
        first,
        when=original_journal.observed_at,
        key="interleaved-first",
    )
    events = writer.origin.verified_events()
    decoded = T.decode_original_events(events, writer.origin.issuer_instance_id)
    by_id = {
        event.event_id: (position, envelope)
        for position, event, envelope in decoded.rows
    }
    assert by_id[final.event_id][1] == first
    assert by_id[inserted[0].event_id][1] == second
    assert by_id[inserted[0].event_id][0] < by_id[final.event_id][0]
    first_parts = [
        i
        for i, event in enumerate(events)
        if event.event_type == T.CHUNK_EVENT
        and isinstance(event.payload, Mapping)
        and event.payload["record_id"] == str(final.event_id)
    ]
    assert first_parts[0] < by_id[inserted[0].event_id][0] < first_parts[-1]


def test_logical_size_preflight_writes_no_partial_group(
    tmp_path: Path,
    original_journal: CapturedControlledJournalV1,
    large_blob: StorageBlob,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = storage_writer(tmp_path, original_journal)
    before = writer.origin.verified_events()
    assert T.MAX_LOGICAL_RECORD_BYTES == 67_108_864
    # Lower only this test's resource budget to exercise the same preflight
    # without allocating a 64MiB string merely to prove rejection.
    monkeypatch.setattr(T, "MAX_LOGICAL_RECORD_BYTES", C.MAX_RECORD_BYTES)
    with pytest.raises(ValueError, match="CONTROLLED_LOGICAL_RECORD_TOO_LARGE"):
        writer.append(
            C.ContainmentRecordV1(
                observation=original_journal.manifest.ref, reason=large_blob.value
            ),
            key="oversized",
        )
    assert writer.origin.verified_events() == before
    with pytest.raises(ValueError, match="CLOSED_OR_UNCERTAIN"):
        writer.append(
            C.ContainmentRecordV1(
                observation=original_journal.manifest.ref, reason="small"
            ),
            key="retry",
        )


@pytest.mark.parametrize("winner_large", [False, True])
def test_competing_cost_corrections_cannot_leave_orphan_chunks(
    tmp_path: Path,
    large_blob: StorageBlob,
    large_manifest_campaign: tuple[dict[str, Any], Any, CapturedControlledJournalV1],
    monkeypatch: pytest.MonkeyPatch,
    winner_large: bool,
) -> None:
    from drift.errors import DuplicateEventError
    from drift.intelligence.contracts import StoredArtifactRef
    from drift.intelligence.receipts import create_cost_receipt
    from drift.loop import stage1_controlled_journal as J

    source, executed, captured = large_manifest_campaign
    path = tmp_path / "competing.sqlite3"
    shutil.copy2(source["origin"].ledger_path, path)
    origin = ConfiguredLocalSyntheticOriginV1(path, source["origin"].issuer_instance_id)
    original = next(
        row.record.original
        for row in captured.rows
        if isinstance(row.record, C.CostRecordV1)
    )

    def correction(ident: str, large: bool, amount: str) -> Any:
        return create_cost_receipt(
            receipt_id=ident,
            scope=original.scope,
            category=original.category,
            billing_identity=original.billing_identity,
            amount_basis="actual",
            attempt_id=original.attempt_id,
            raw_evidence_ref=StoredArtifactRef(
                artifact_id=ident,
                kind="other",
                content_hash="3" * 64,
                location="synthetic://" + (large_blob.value if large else "small"),
            ),
            recorded_at=BASE + timedelta(hours=1),
            amount=amount,
            currency="USD",
            supersedes_receipt_id=original.receipt_id,
        )

    winner = correction("winner", winner_large, "9")
    loser = correction("loser", not winner_large, "10")
    kwargs = dict(
        origin=origin,
        allocation_id=executed.allocation_id,
        checkpoint_id=source["checkpoints"][0].checkpoint_id,
        clock=lambda: BASE + timedelta(hours=2),
    )
    append = T.append_envelope
    winning_events: list[Any] = []

    def race(*args: Any, **options: Any) -> Any:
        if not winning_events:
            # Outer correction has already validated the same old prefix.
            winning_events.append(None)
            append_controlled_cost_correction(**kwargs, correction=winner)
            winning_events[:] = list(origin.verified_events())
        return append(*args, **options)

    monkeypatch.setattr(J, "append_envelope", race)
    with pytest.raises(DuplicateEventError):
        append_controlled_cost_correction(**kwargs, correction=loser)
    assert origin.verified_events() == tuple(winning_events)
    read_args = {key: source[key] for key in READ_KEYS} | {
        "origin": origin,
        "clock": lambda: BASE + timedelta(hours=3),
    }
    report = read_controlled_campaign(**read_args, allocation_id=executed.allocation_id)
    assert report.status == "VERIFIED_COMPLETE", report.reasons
    assert report.trials[0].operating_cost.amount == Decimal("9")
