"""Adversarial original-record controls for the synthetic candidate (#564)."""

# ruff: noqa: E402
import json
import sqlite3
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from test_stage1_synthetic_research_execution import (
    BASE,
    Tick,
    cold_read,
    make_harness,
    proposal,
    request,
)

from drift.errors import DuplicateEventError
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import ResearchContext, compute_record_hash
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    CLAIM,
    CONSUMED,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
)
from drift.loop import stage1_synthetic_research_execution as pipeline
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json


def _ref(harness: dict[str, Any]) -> LocalEventReferenceV1:
    event = next(
        event
        for event in harness["origin"].verified_events()
        if event.event_type == pipeline.OPPORTUNITY
    )
    return LocalEventReferenceV1(event.event_id, event.event_hash)


def test_duplicate_opportunity_cannot_repeat_research_or_execution(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    original = pipeline.execute_synthetic_research(**harness, request=request())
    before = harness["origin"].verified_events()
    with pytest.raises(DuplicateEventError):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert harness["origin"].verified_events() == before
    assert (
        cold_read(harness, original.opportunity_ref).state == "LOCAL_EXECUTION_COMPLETE"
    )


@pytest.mark.parametrize(
    "phase", [pipeline.RESEARCH, pipeline.RESERVATION, pipeline.OUTCOME]
)
def test_interrupted_writes_remain_unresolved_and_never_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    harness = make_harness(tmp_path)
    real_append = pipeline._append

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        if kwargs["phase"] == phase:
            raise OSError("injected unavailable durable store")
        return real_append(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", interrupted)
        with pytest.raises(OSError, match="injected"):
            pipeline.execute_synthetic_research(**harness, request=request())
    before = harness["origin"].verified_events()
    result = cold_read(harness, _ref(harness))
    assert result.state == "UNRESOLVED"
    assert not result.g2_accepted
    assert result.original_result is None
    assert harness["origin"].verified_events() == before
    with pytest.raises(DuplicateEventError):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert harness["origin"].verified_events() == before


@pytest.mark.parametrize("field", ["account_id", "arm_id", "experiment_id"])
def test_canonical_but_cross_scope_context_is_refused_before_research(
    tmp_path: Path, field: str
) -> None:
    harness = make_harness(tmp_path)
    raw = harness["context"].model_dump(mode="python")
    raw["scope"][field] = "OTHER"
    raw["record_hash"] = compute_record_hash(raw)
    harness["context"] = ResearchContext.model_validate(raw)
    before = harness["origin"].verified_events()
    with pytest.raises(ValueError, match="RESEARCH_ORIGINAL_SCOPE"):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert harness["origin"].verified_events() == before


def test_cold_reader_refuses_wrong_checkpoint_even_with_valid_e1(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    result = pipeline.execute_synthetic_research(**harness, request=request())
    harness["provenance"] = build_stage1_trial_provenance_snapshot(
        campaign=harness["campaign"],
        arms=harness["arms"],
        bindings=harness["bindings"],
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id="ARM-B",
        checkpoint_id="CKPT-OTHER",
        events=(),
    )
    with pytest.raises(ValueError, match="RESEARCH_ORIGINAL_SCOPE"):
        cold_read(harness, result.opportunity_ref)


def test_missing_ledger_is_not_created_by_cold_reader(tmp_path: Path) -> None:
    harness = make_harness(tmp_path / "source")
    result = pipeline.execute_synthetic_research(**harness, request=request())
    missing = tmp_path / "does-not-exist.sqlite3"
    harness["origin"] = ConfiguredLocalSyntheticOriginV1(
        missing, harness["origin"].issuer_instance_id
    )
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        cold_read(harness, result.opportunity_ref)
    assert not missing.exists()


def test_wrong_issuer_cannot_read_matching_local_originals(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    result = pipeline.execute_synthetic_research(**harness, request=request())
    harness["origin"] = replace(harness["origin"], issuer_instance_id=uuid7())
    with pytest.raises(ValueError, match="ORIGIN_MISMATCH"):
        cold_read(harness, result.opportunity_ref)


@pytest.mark.parametrize("mutation", ["context", "intent", "missing", "duplicate-key"])
def test_genuine_m0_result_does_not_certify_forged_first_decision_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    harness = make_harness(tmp_path)
    real_append = pipeline._append

    def forged(*args: Any, **kwargs: Any) -> Any:
        if kwargs["phase"] == pipeline.OUTCOME:
            body = kwargs["body"]
            changes: dict[str, str | None]
            if mutation == "missing":
                changes = {"first_context_utf8": None}
            elif mutation == "context":
                raw = json.loads(body.first_context_utf8)
                raw["current_cash"] = "9999"
                changes = {"first_context_utf8": canonical_json(raw).decode()}
            elif mutation == "intent":
                raw = json.loads(body.first_intent_utf8)
                raw["targets"][0]["target_quantity"] = 50
                changes = {"first_intent_utf8": canonical_json(raw).decode()}
            else:
                text = body.first_intent_utf8
                changes = {"first_intent_utf8": '{"schema_version":"1",' + text[1:]}
            kwargs["body"] = body.model_copy(update=changes)
        return real_append(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", forged)
        with pytest.raises(ValueError):
            pipeline.execute_synthetic_research(**harness, request=request())
    # Genuine completed M0 and original financial evidence are present. The
    # refusal is specifically about joining that result to a forged decision.
    assert any(
        event.event_type == "stage1.synthetic_result.original_retained"
        for event in harness["origin"].verified_events()
    )
    with pytest.raises(ValueError):
        cold_read(harness, _ref(harness))


@pytest.mark.parametrize("field", ["output_utf8", "receipt_journal_utf8"])
def test_research_replay_refuses_changed_original_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    harness = make_harness(tmp_path)
    real_append = pipeline._append

    def forged(*args: Any, **kwargs: Any) -> Any:
        if kwargs["phase"] == pipeline.RESEARCH:
            body = kwargs["body"]
            kwargs["body"] = body.model_copy(update={field: "{}"})
        return real_append(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", forged)
        with pytest.raises(ValueError, match="RESEARCH_ORIGINAL_REPLAY_MISMATCH"):
            pipeline.execute_synthetic_research(**harness, request=request())
    with pytest.raises(ValueError, match="RESEARCH_ORIGINAL_REPLAY_MISMATCH"):
        cold_read(harness, _ref(harness))


def test_expired_opportunity_stops_before_any_producer_call(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    harness["clock"] = Tick(BASE + timedelta(hours=1))
    before = harness["origin"].verified_events()
    with pytest.raises(ValueError, match="INVALID_OPPORTUNITY_CHRONOLOGY"):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert harness["origin"].verified_events() == before


def test_false_equal_reference_leaf_is_refused(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    result = pipeline.execute_synthetic_research(**harness, request=request())

    class EqualString(str):
        def __eq__(self, other: object) -> bool:
            return True

        __hash__ = str.__hash__

    forged = LocalEventReferenceV1(
        result.opportunity_ref.event_id, EqualString("f" * 64)
    )
    with pytest.raises(ValueError, match="INVALID_RESEARCH_ORIGIN_OR_REFERENCE"):
        cold_read(harness, forged)


def test_committed_outcome_with_lost_ack_can_be_read_but_not_reexecuted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = make_harness(tmp_path)
    real_append = pipeline._append

    def lost_ack(*args: Any, **kwargs: Any) -> Any:
        event = real_append(*args, **kwargs)
        if kwargs["phase"] == pipeline.OUTCOME:
            raise OSError("commit succeeded but acknowledgement lost")
        return event

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", lost_ack)
        with pytest.raises(OSError, match="acknowledgement lost"):
            pipeline.execute_synthetic_research(**harness, request=request())
    result = cold_read(harness, _ref(harness))
    assert result.state == "LOCAL_EXECUTION_COMPLETE"
    before = harness["origin"].verified_events()
    with pytest.raises(DuplicateEventError):
        pipeline.execute_synthetic_research(**harness, request=request())
    assert harness["origin"].verified_events() == before


def test_original_research_retained_after_deadline_does_not_dispatch(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    stamps = iter(
        [
            BASE + timedelta(seconds=4),
            BASE + timedelta(seconds=5),
            BASE + timedelta(minutes=6),
        ]
    )

    def delayed() -> Any:
        return next(stamps, BASE + timedelta(minutes=7))

    harness["clock"] = delayed
    result = pipeline.execute_synthetic_research(**harness, request=request())
    assert result.state == "NO_DISPATCH"
    assert result.reason == "RESEARCH_READY_AFTER_DEADLINE"
    assert result.candidate_hash is not None
    assert len(result.research_receipt_hashes) == 3
    assert not any(
        event.event_type == "m2.evaluation.run.recorded"
        for event in harness["origin"].verified_events()
    )


def _compressed_context(raw: bytes, **changes: Any) -> Any:
    import base64
    import hashlib
    import zlib

    return pipeline._CompressedDecisionContextV1.model_validate(
        {
            "uncompressed_size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "data": base64.b64encode(zlib.compress(raw)).decode("ascii"),
        }
        | changes
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated",
        "trailing",
        "concatenated",
        "short-size",
        "long-size",
        "wrong-digest",
        "bad-zlib",
        "bad-base64",
        "base64-whitespace",
    ],
)
def test_compressed_proof_refuses_corrupt_streams_and_claims(mutation: str) -> None:
    import base64
    import zlib

    raw = canonical_json({"original": "retained" * 1000})
    stream = zlib.compress(raw)
    changes: dict[str, Any] = {}
    if mutation == "truncated":
        stream = stream[:-1]
    elif mutation == "trailing":
        stream += b"not part of the original"
    elif mutation == "concatenated":
        stream += zlib.compress(b"{}")
    elif mutation == "short-size":
        changes["uncompressed_size"] = len(raw) - 1
    elif mutation == "long-size":
        changes["uncompressed_size"] = len(raw) + 1
    elif mutation == "wrong-digest":
        changes["sha256"] = "f" * 64
    elif mutation == "bad-zlib":
        stream = b"not a zlib stream"
    changes["data"] = base64.b64encode(stream).decode("ascii")
    if mutation == "bad-base64":
        changes["data"] = "not!base64"
    elif mutation == "base64-whitespace":
        changes["data"] += "\n"
    artifact = _compressed_context(raw, **changes)
    with pytest.raises(ValueError):
        pipeline._decode_context(artifact)


@pytest.mark.parametrize("size", [True, False, 0, -1, 1.5, "20", 33_554_433])
def test_compressed_proof_requires_bounded_exact_integer_size(size: Any) -> None:
    with pytest.raises(ValueError):
        _compressed_context(b"{}", uncompressed_size=size)


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x": 1}', b'{"x":NaN}', b"[]", b"\xff"]
)
def test_lossless_compression_never_relaxes_original_json_rules(raw: bytes) -> None:
    artifact = _compressed_context(raw)
    with pytest.raises(ValueError):
        pipeline._decode_context(artifact)


def test_decompression_stops_at_advertised_size_instead_of_expanding_a_bomb() -> None:
    artifact = _compressed_context(b"x" * 1_000_000, uncompressed_size=2)
    with pytest.raises(ValueError, match="STREAM_OR_LENGTH"):
        pipeline._decode_context(artifact)


@pytest.mark.parametrize("bound", ["decoded", "encoded"])
def test_unretainable_first_context_fails_before_any_order_is_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str
) -> None:
    from drift.evaluator import engine as engine_module

    harness = make_harness(tmp_path)
    stages: list[bool] = []

    def unexpected_stage(*args: Any, **kwargs: Any) -> Any:
        stages.append(True)
        raise AssertionError("An unretainable first proof must not reach staging")

    monkeypatch.setattr(engine_module, "stage_decision_targets", unexpected_stage)
    monkeypatch.setattr(
        engine_module, "stage_exploratory_decision_targets", unexpected_stage
    )
    if bound == "decoded":
        monkeypatch.setattr(pipeline, "MAX_DECISION_CONTEXT_BYTES", 8)
        expected = "DECISION_CONTEXT_DECODED_BOUND_EXCEEDED"
    else:
        monkeypatch.setattr(
            pipeline, "_PROOF_METADATA_RESERVE", pipeline.MAX_RECORD_BYTES
        )
        expected = "FIRST_DECISION_PROOF_TOO_LARGE"
    result = pipeline.execute_synthetic_research(**harness, request=request())
    assert result.state == "EXECUTION_FAILED"
    assert expected in result.reason
    assert stages == []
    assert result.original_result is None
    assert not any(
        event.event_type == "stage1.synthetic_result.original_retained"
        for event in harness["origin"].verified_events()
    )


@pytest.mark.parametrize("field", ["sha256", "uncompressed_size", "data"])
def test_cold_read_refuses_rehashed_but_corrupt_compressed_original_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    harness = make_harness(tmp_path)
    real_append = pipeline._append
    monkeypatch.setattr(pipeline, "_INLINE_CONTEXT_BYTES", 1)

    def forged(*args: Any, **kwargs: Any) -> Any:
        if kwargs["phase"] == pipeline.OUTCOME:
            body = kwargs["body"]
            artifact = body.first_context_artifact
            value = {"sha256": "f" * 64, "uncompressed_size": 1, "data": "AA=="}[field]
            changed = artifact.model_copy(update={field: value})
            kwargs["body"] = body.model_copy(update={"first_context_artifact": changed})
        return real_append(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "_append", forged)
        with pytest.raises(ValueError):
            pipeline.execute_synthetic_research(**harness, request=request())
    assert any(
        event.event_type == "stage1.synthetic_result.original_retained"
        for event in harness["origin"].verified_events()
    )
    with pytest.raises(ValueError):
        cold_read(harness, _ref(harness))


@pytest.mark.parametrize("schema", ["1", "3"])
def test_compressed_outcome_cannot_be_downgraded_or_read_as_an_unknown_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema: str
) -> None:
    harness = make_harness(tmp_path)
    monkeypatch.setattr(pipeline, "_INLINE_CONTEXT_BYTES", 1)
    result = pipeline.execute_synthetic_research(**harness, request=request())
    outcome = next(
        item
        for item in harness["origin"].verified_events()
        if item.event_type == pipeline.OUTCOME
    )
    forged = outcome.model_copy(update={"schema_version": schema})
    cls = pipeline._Outcome if schema == "1" else pipeline._OutcomeV2
    with pytest.raises(ValueError):
        pipeline._record(forged, cls, harness["origin"])
    assert (
        cold_read(harness, result.opportunity_ref).state == "LOCAL_EXECUTION_COMPLETE"
    )


@pytest.mark.parametrize(
    "mutation", ["both", "failed", "missing-kind", "missing-intent"]
)
def test_compressed_outcome_requires_one_complete_success_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    harness = make_harness(tmp_path)
    monkeypatch.setattr(pipeline, "_INLINE_CONTEXT_BYTES", 1)
    pipeline.execute_synthetic_research(**harness, request=request())
    outcome = next(
        item
        for item in harness["origin"].verified_events()
        if item.event_type == pipeline.OUTCOME
    )
    data = json.loads(outcome.payload["body_utf8"])
    change = {
        "both": {"first_context_utf8": "{}"},
        "failed": {"status": "M0_FAILED"},
        "missing-kind": {"first_context_kind": None},
        "missing-intent": {"first_intent_utf8": None},
    }[mutation]
    with pytest.raises(ValueError):
        pipeline._OutcomeV2.model_validate(data | change)


def test_noncanonical_base64_pad_bits_do_not_alias_original_compressed_bytes() -> None:
    import base64

    artifact = _compressed_context(b"{}")
    assert artifact.data.endswith("==")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    pos = alphabet.index(artifact.data[-3])
    assert pos % 16 == 0
    changed = artifact.data[:-3] + alphabet[pos + 1] + "=="
    assert base64.b64decode(changed) == base64.b64decode(artifact.data)
    with pytest.raises(ValueError, match="BASE64_NONCANONICAL"):
        pipeline._decode_context(artifact.model_copy(update={"data": changed}))


_FAILED_EVIDENCE_MUTATIONS = (
    "claim-schema",
    "claim-profile",
    "claim-issuer",
    "claim-entity",
    "claim-dedup",
    "claim-witness",
    "claim-identity",
    "claim-before-reservation",
    "claim-after-failure",
    "failure-before-claim",
    "shared-wrong-invocation",
    "binding-extra-key",
    "binding-not-uuid7",
    "consumption-schema",
    "consumption-profile",
    "consumption-issuer",
    "consumption-entity",
    "consumption-dedup",
    "consumption-claim-id",
    "consumption-claim-hash",
    "consumption-allocation",
    "consumption-identity",
    "consumption-book",
    "consumption-binding",
    "consumption-before-claim",
    "consumption-after-failure",
    "consumption-after-m0",
    "duplicate-consumption",
)


def _failed_evidence_copy(
    tmp_path: Path, mutation: str
) -> tuple[dict[str, Any], LocalEventReferenceV1]:
    """Use genuine failed M0, then an independently hash-valid negative ledger.

    Checksum failures would mask the missing semantic checks under test. Rebuild
    the copy through SQLiteLedger.append, preserving the original allocation,
    opportunity, research and reservation. This is fixture corruption only;
    the original writer's database and append protections are never modified.
    """
    harness = make_harness(tmp_path / "source")
    result = pipeline.execute_synthetic_research(
        **harness, request=request(proposal(weight="0.5", cash="0.5"))
    )
    assert result.state == "EXECUTION_FAILED"
    events = list(harness["origin"].verified_events())
    claim = next(e for e in events if e.event_type == CLAIM)
    consumed = next(e for e in events if e.event_type == CONSUMED)
    reservation = next(e for e in events if e.event_type == pipeline.RESERVATION)
    failed = next(e for e in events if e.event_type == "m2.evaluation.run.recorded")
    origin = replace(harness["origin"], ledger_path=tmp_path / "negative.sqlite3")
    ledger = SQLiteLedger(origin.ledger_path)
    if mutation == "consumption-after-m0":
        events.remove(consumed)
        events.insert(events.index(failed) + 1, consumed)
    replacement_invocation = str(uuid7())
    claim_hash = claim.event_hash
    for event in events:
        payload = json.loads(canonical_json(event.payload))
        schema, entity, stamp, dedup = (
            event.schema_version,
            event.entity_type,
            event.timestamp,
            event.deduplication_key,
        )
        if event.event_type == CLAIM:
            if mutation == "claim-schema":
                schema = "1"
            if mutation == "claim-profile":
                payload["profile"] = "unaccepted-profile"
            if mutation == "claim-issuer":
                payload["issuer_instance_id"] = str(uuid7())
            if mutation == "claim-entity":
                entity = "other_account"
            if mutation == "claim-dedup":
                dedup = "unscoped-claim"
            if mutation == "claim-witness":
                payload["witness_event_hash"] = "0" * 64
            if mutation == "claim-identity":
                payload["identity_hash"] = "not-a-digest"
            if mutation == "claim-before-reservation":
                stamp = reservation.timestamp - timedelta(seconds=1)
            if mutation == "claim-after-failure":
                stamp = failed.timestamp + timedelta(seconds=1)
        if mutation == "failure-before-claim" and event == failed:
            stamp = claim.timestamp - timedelta(seconds=1)
        if event.event_type in (CLAIM, CONSUMED, "m2.evaluation.run.recorded"):
            if mutation == "shared-wrong-invocation":
                payload["invocation_binding"]["invocation_id"] = replacement_invocation
            if mutation == "binding-extra-key":
                payload["invocation_binding"]["unexpected"] = "value"
            if mutation == "binding-not-uuid7":
                payload["invocation_binding"]["invocation_id"] = "not-a-uuid"
        if event.event_type == CONSUMED:
            # Keep lineage consistent after a claim mutation so each negative
            # cannot pass merely because an unrelated stale claim hash fails.
            payload["claim_event_hash"] = claim_hash
            if mutation == "consumption-schema":
                schema = "1"
            if mutation == "consumption-profile":
                payload["profile"] = "unaccepted-profile"
            if mutation == "consumption-issuer":
                payload["issuer_instance_id"] = str(uuid7())
            if mutation == "consumption-entity":
                entity = "other_account"
            if mutation == "consumption-dedup":
                dedup = "unscoped-consumption"
            fields = {
                "consumption-claim-id": "claim_event_id",
                "consumption-claim-hash": "claim_event_hash",
                "consumption-allocation": "allocation_event_hash",
                "consumption-identity": "identity_hash",
                "consumption-book": "original_book_sha256",
            }
            if mutation in fields:
                payload[fields[mutation]] = "0" * 64
            if mutation == "consumption-binding":
                payload["invocation_binding"]["m0_run_id"] = str(uuid7())
            if mutation == "consumption-before-claim":
                stamp = claim.timestamp - timedelta(seconds=1)
            if mutation == "consumption-after-failure":
                stamp = failed.timestamp + timedelta(seconds=1)
        draft = AuditEventDraft(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=stamp,
            entity_type=entity,
            entity_id=event.entity_id,
            payload=payload,
            schema_version=schema,
            deduplication_key=dedup,
        )
        written = ledger.append(draft)
        if event.event_type == CLAIM:
            claim_hash = written.event_hash
        if event.event_type == CONSUMED and mutation == "duplicate-consumption":
            ledger.append(
                draft.model_copy(
                    update={
                        "event_id": uuid7(),
                        "deduplication_key": "duplicate-consumption",
                    }
                )
            )
    verified = origin.verified_events()
    assert len(verified) == len(events) + (mutation == "duplicate-consumption")
    if mutation == "none":
        assert verified == tuple(events)
    harness["origin"] = origin
    return harness, result.opportunity_ref


@pytest.mark.parametrize("mutation", _FAILED_EVIDENCE_MUTATIONS)
def test_failed_run_requires_original_claim_and_consumption_semantics(
    tmp_path: Path, mutation: str
) -> None:
    harness, reference = _failed_evidence_copy(tmp_path, mutation)
    with pytest.raises(ValueError):
        cold_read(harness, reference)


def test_genuine_failed_run_survives_independent_evidence_copy(tmp_path: Path) -> None:
    harness, reference = _failed_evidence_copy(tmp_path, "none")
    result = cold_read(harness, reference)
    assert result.state == "EXECUTION_FAILED"
    assert result.original_result is None
    assert not result.g2_accepted


def test_failure_before_consumption_does_not_require_fabricated_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = make_harness(tmp_path)

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise OSError("consumption unavailable before original append")

    monkeypatch.setattr(
        Stage1SyntheticAccountLifecycleV1, "observe_bound_consumption", unavailable
    )
    result = pipeline.execute_synthetic_research(**harness, request=request())
    assert result.state == "EXECUTION_FAILED"
    assert result.original_result is None
    events = harness["origin"].verified_events()
    assert any(e.event_type == CLAIM for e in events)
    assert not any(e.event_type == CONSUMED for e in events)
    assert cold_read(harness, result.opportunity_ref).state == "EXECUTION_FAILED"
