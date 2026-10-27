"""#508 PR C adversaries: forged M0 roots, account scopes and duplicate RESULT.

These tests are entirely offline; a local hash chain does not appoint an
accepted issuer or scientific experiment authority.
"""

# ruff: noqa: E402
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

import pytest

for _source in ("unit", "integration"):
    _path = Path(__file__).resolve().parents[1] / _source
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_evaluator_engine import FixedTargetStrategy, _buy_ten, _engine, _run
from test_evaluator_experiment_run import _context, _specification
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)
from test_stage1_original_result_association import (
    BASE,
    M0_COMPLETE,
    M0_START,
    RESULT_OBSERVED,
    _execute,
    _setup,
    _Tick,
)

from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_results import EvaluationRunArtifactsV2
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.events import AuditEvent
from drift.domain.experiments import ExperimentRun, ExperimentRunStatus
from drift.errors import LedgerIntegrityError
from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    CLAIM,
    CONSUMED,
    WITNESS,
    ConfiguredLocalSyntheticOriginV1,
    LocalAccountReceiptError,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    OriginalLocalAccountReadbackV1,
)
from drift.loop.stage1_original_result_association import (
    M0_USE_EVENT,
    RESULT_EVENT,
    LocalOriginalResultReadbackV1,
    OriginalResultAssociationError,
    Stage1OriginalResultAssociationV1,
    read_original_result,
)


def _context_with_origin(
    engine: SessionEvaluatorEngine, path: Path
) -> ExperimentRunnerContext:
    return _context(
        engine,
        ledger=SQLiteLedger(path),
        started_at=M0_START,
        completed_at=M0_COMPLETE,
    )


def test_foreign_m0_ledger_does_not_authenticate_original_result(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    ctx = replace(
        _context_with_origin(engine, tmp_path / "forged-m0.sqlite3"),
        original_result_observer=observer,
    )
    with pytest.raises(
        OriginalResultAssociationError, match="M0_RUN_MISSING_OR_DUPLICATE"
    ):
        execute_experiment_run(_specification(), ctx)
    assert all(e.event_type != RESULT_EVENT for e in store.origin.verified_events())
    foreign = SQLiteLedger(tmp_path / "forged-m0.sqlite3")
    assert any(
        e.event_type == "m2.evaluation.run.recorded" for e in foreign.verified_events()
    )


def test_result_observation_clock_cannot_precede_actual_original_m0(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(
        tmp_path, clock=lambda: M0_COMPLETE - timedelta(microseconds=1)
    )
    with pytest.raises(
        OriginalResultAssociationError, match="RESULT_RECORD_PRECEDES_ORIGINAL"
    ):
        _execute(engine, observer, store)
    types = [e.event_type for e in store.origin.verified_events()]
    assert RESULT_EVENT not in types
    assert types[-1] == "m2.evaluation.run.recorded"


def test_mismatched_arm_and_account_provenance_fails_before_result(
    tmp_path: Path,
) -> None:
    engine, original, store = _setup(tmp_path, arm="ARM-B")
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    wrong_provenance = build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id="ARM-R",
        checkpoint_id="CKPT-001",
        events=(),
    )
    with pytest.raises(
        OriginalResultAssociationError, match="E1_TO_ACCOUNT_ORIGINAL_MISMATCH"
    ):
        Stage1OriginalResultAssociationV1(
            origin=store.origin,
            account=original._account,
            provenance=wrong_provenance,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=("RUN-001",),
            clock=lambda: datetime(2026, 10, 21, 19, 1, tzinfo=UTC),
        )
    assert len(store.origin.verified_events()) == 2


def test_fake_m0_event_id_is_refused_even_with_valid_result_hashes(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    context = replace(
        _context_with_origin(engine, store.origin.ledger_path),
        original_result_observer=_SourceResultCapture(),
    )
    run = execute_experiment_run(_specification(), context)
    same_content = _run(_engine())
    with pytest.raises(
        OriginalResultAssociationError, match="ACCOUNT_M0_INVOCATION_MISMATCH"
    ):
        observer.observe_canonical_result(
            run=run, artifacts=same_content, m0_audit_event_id=uuid7()
        )
    assert all(e.event_type != RESULT_EVENT for e in store.origin.verified_events())


def test_identical_result_cannot_be_counted_twice_by_second_m0_identity(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    run = _execute(engine, observer, store)
    before = tuple(store.origin.verified_events())
    retained = observer.readback()
    with pytest.raises(
        OriginalResultAssociationError, match="ORIGINAL_RESULT_ALREADY_ATTEMPTED"
    ):
        observer.observe_canonical_result(
            run=run,
            artifacts=retained.original_artifacts,
            m0_audit_event_id=uuid7(),
        )
    assert tuple(store.origin.verified_events()) == before


def test_fake_original_trial_record_cannot_mint_an_accepted_issuer(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    proof = observer.readback()
    assert proof.original_issuer_authenticated_for_e6b is False
    assert proof.scientifically_qualified is False
    assert proof.classification == "complete"
    assert (
        len(
            [
                event
                for event in store.origin.verified_events()
                if event.event_type == RESULT_EVENT
            ]
        )
        == 1
    )


class _SourceResultCapture:
    """Hold the actual canonical M0 callback without writing PR C's RESULT."""

    def __init__(self) -> None:
        self.run: ExperimentRun | None = None
        self.artifacts: EvaluationRunArtifactsV2 | None = None
        self.m0_event_id: UUID | None = None

    def observe_canonical_result(
        self,
        *,
        run: ExperimentRun,
        artifacts: EvaluationRunArtifactsV2,
        m0_audit_event_id: UUID,
    ) -> None:
        self.run = run
        self.artifacts = artifacts
        self.m0_event_id = m0_audit_event_id


def test_altered_final_book_cannot_borrow_original_result_trace_hashes(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    original = _SourceResultCapture()
    ctx = replace(
        _context_with_origin(engine, store.origin.ledger_path),
        original_result_observer=original,
    )
    run = execute_experiment_run(_specification(), ctx)
    assert run.status is ExperimentRunStatus.COMPLETED
    assert original.artifacts is not None
    assert original.m0_event_id is not None

    # This is a valid V2 book with the same admission and ending NAV but a
    # counterfeit settled claim. The original M0 V3 audit did not contain it.
    fake_book = original.artifacts.final_state.model_copy(
        update={"settled_claim_ids": ("a" * 64,)}
    )
    altered = original.artifacts.model_copy(update={"final_state": fake_book})
    assert altered.result.result_hash == original.artifacts.result.result_hash
    assert altered.trace.trace_hash == original.artifacts.trace.trace_hash
    assert altered.final_state != original.artifacts.final_state

    with pytest.raises(
        OriginalResultAssociationError, match="NOT_THE_ORIGINAL_COMPLETED_M0"
    ):
        observer.observe_canonical_result(
            run=run,
            artifacts=altered,
            m0_audit_event_id=original.m0_event_id,
        )
    assert all(e.event_type != RESULT_EVENT for e in store.origin.verified_events())


def test_result_append_success_is_not_undone_by_later_readback_clock(
    tmp_path: Path,
) -> None:
    times = iter((RESULT_OBSERVED, M0_COMPLETE - timedelta(seconds=1)))
    engine, observer, store = _setup(tmp_path, clock=lambda: next(times))
    # Only the first clock sample is used during the M0 observer's append.
    run = _execute(engine, observer, store)
    assert run.status is ExperimentRunStatus.COMPLETED
    originals = [
        e for e in store.origin.verified_events() if e.event_type == RESULT_EVENT
    ]
    assert len(originals) == 1
    # Independent readback can refuse its own impossible observation clock.
    # It must not erase or recategorize the already-committed M0/RESULT.
    with pytest.raises(
        OriginalResultAssociationError, match="RESULT_READBACK_CLOCK_ROLLBACK"
    ):
        observer.readback()
    assert (
        len([e for e in store.origin.verified_events() if e.event_type == RESULT_EVENT])
        == 1
    )


def test_same_original_m0_event_cannot_be_used_for_two_distinct_accounts(
    tmp_path: Path,
) -> None:
    """Two genuine bound accounts cannot share one operational M0 result."""
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "same-m0.sqlite3",
        issuer_instance_id=uuid7(),
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=origin,
        clock=_Tick(),
    )
    b_engine, b_observer, _ = _setup(tmp_path, arm="ARM-B", store=store)
    r_engine, r_observer, _ = _setup(tmp_path, arm="ARM-R", store=store)
    # R has its own genuine bound M0 invocation, retained only by a capture
    # observer. Byte-identical deterministic artifacts cannot let it adopt
    # the separately completed B invocation's original M0 event.
    r_context = replace(
        _context_with_origin(r_engine, origin.ledger_path),
        original_result_observer=_SourceResultCapture(),
        completed_at=BASE + timedelta(seconds=15),
    )
    r_run = execute_experiment_run(_specification(), r_context)
    assert r_run.status is ExperimentRunStatus.COMPLETED
    b = _execute(
        b_engine,
        b_observer,
        store,
        completed_at=BASE + timedelta(seconds=25),
    )
    retained_b = b_observer.readback()
    m0_events = [
        event
        for event in origin.verified_events()
        if event.event_type == "m2.evaluation.run.recorded"
    ]
    assert len(m0_events) == 2
    b_m0 = next(event for event in m0_events if event.entity_id == b.run_id)
    with pytest.raises(
        OriginalResultAssociationError,
        match="ACCOUNT_M0_INVOCATION_MISMATCH",
    ):
        r_observer.observe_canonical_result(
            run=b,
            artifacts=retained_b.original_artifacts,
            m0_audit_event_id=b_m0.event_id,
        )
    history = origin.verified_events()
    assert len([e for e in history if e.event_type == M0_USE_EVENT]) == 1
    assert len([e for e in history if e.event_type == RESULT_EVENT]) == 1
    assert b_observer.readback().account_id == "SYNTH-ACC-B-001"


def test_separate_consumption_cannot_authorize_a_fresh_m0_engine(
    tmp_path: Path,
) -> None:
    """Matching deterministic artifacts cannot prove the account's invocation."""
    prepared, observer, store = _setup(tmp_path)
    _run(prepared)
    assert observer._account.local_phase == "consumed"

    run = _execute(_engine(), observer, store)

    assert run.status is ExperimentRunStatus.FAILED
    history = store.origin.verified_events()
    assert all(event.event_type != RESULT_EVENT for event in history)
    assert all(event.event_type != M0_USE_EVENT for event in history)


def test_consumption_during_another_m0_cannot_claim_its_result(
    tmp_path: Path,
) -> None:
    """A phase transition during M0 is weaker than binding its actual engine."""
    b_engine, b_observer, store = _setup(tmp_path, arm="ARM-B")
    r_engine, _, _ = _setup(tmp_path, arm="ARM-R", store=store)
    assert b_observer._account.local_phase == "ready"

    class ConsumeOtherAccount(FixedTargetStrategy):
        fired = False

        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            if not self.fired:
                self.fired = True
                _run(b_engine)
            return super().decide(context)

    strategy = ConsumeOtherAccount(_buy_ten().targets)
    with pytest.raises(OriginalResultAssociationError):
        _execute(
            r_engine,
            b_observer,
            store,
            strategy=strategy,
            completed_at=BASE + timedelta(seconds=25),
        )
    assert b_observer._account.local_phase == "consumed"
    assert all(
        event.event_type not in (RESULT_EVENT, M0_USE_EVENT)
        for event in store.origin.verified_events()
    )


def _cold_read(
    observer: Stage1OriginalResultAssociationV1,
    origin: ConfiguredLocalSyntheticOriginV1,
    account: OriginalLocalAccountReadbackV1,
    reference: LocalEventReferenceV1,
) -> LocalOriginalResultReadbackV1:
    return read_original_result(
        origin=origin,
        original_account=account,
        association_ref=reference,
        provenance=observer._provenance,
        campaign=observer._campaign,
        arms=observer._arms,
        bindings=observer._bindings,
        expected_run_ids=observer._runs,
        clock=lambda: RESULT_OBSERVED + timedelta(seconds=30),
    )


def test_cold_read_does_not_create_a_missing_configured_ledger(tmp_path: Path) -> None:
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    account = observer._account.verified_original()
    receipt = observer.readback().association_ref
    missing = replace(store.origin, ledger_path=tmp_path / "absent.sqlite3")
    with pytest.raises(sqlite3.OperationalError, match="unable to open database"):
        _cold_read(observer, missing, account, receipt)
    assert not missing.ledger_path.exists()


def test_cold_read_refuses_missing_append_protection_without_repair(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    account = observer._account.verified_original()
    receipt = observer.readback().association_ref
    with sqlite3.connect(store.origin.ledger_path) as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
    with pytest.raises(LedgerIntegrityError, match="audit_events_no_update"):
        _cold_read(observer, store.origin, account, receipt)
    with sqlite3.connect(store.origin.ledger_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE name='audit_events_no_update'"
        ).fetchone() == (0,)


def _rewire_hashes(
    value: ImmutableJSONValue, hashes: Mapping[str, str]
) -> ImmutableJSONValue:
    if isinstance(value, Mapping):
        return {key: _rewire_hashes(item, hashes) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_rewire_hashes(item, hashes) for item in value)
    if type(value) is str:
        return hashes.get(value, value)
    return value


@pytest.mark.parametrize(
    "event_type",
    (CLAIM, CONSUMED, "m2.evaluation.run.recorded", M0_USE_EVENT, RESULT_EVENT),
)
@pytest.mark.parametrize("field", ("invocation_id", "m0_run_id", "m0_audit_event_id"))
def test_cold_reader_refuses_each_crossed_binding_in_a_valid_hash_chain(
    tmp_path: Path, event_type: str, field: str
) -> None:
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    account = observer._account.verified_original()
    genuine = observer.readback()
    assert _cold_read(
        observer, store.origin, account, genuine.association_ref
    ).result_hash

    # Rebuild a physically valid ledger and every dependent event-hash link.
    # Only one operational binding field contradicts the original invocation.
    # A hash-chain-only check would accept this internally consistent file.
    altered_origin = replace(store.origin, ledger_path=tmp_path / "crossed.sqlite3")
    writer = SQLiteLedger(altered_origin.ledger_path)
    hashes: dict[str, str] = {}
    references: dict[str, LocalEventReferenceV1] = {}
    for event in store.origin.verified_events():
        payload = _rewire_hashes(event.payload, hashes)
        assert isinstance(payload, Mapping)
        if event.event_type == event_type:
            existing = payload["invocation_binding"]
            assert isinstance(existing, Mapping)
            payload = dict(payload) | {
                "invocation_binding": dict(existing) | {field: str(uuid7())}
            }
        replacement = writer.append(
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
        hashes[event.event_hash] = replacement.event_hash
        references[event.event_type] = LocalEventReferenceV1(
            replacement.event_id, replacement.event_hash
        )
    writer.verify_chain()
    altered_account = replace(
        account, allocation_ref=references[ALLOCATION], witness_ref=references[WITNESS]
    )
    with pytest.raises((OriginalResultAssociationError, LocalAccountReceiptError)):
        _cold_read(observer, altered_origin, altered_account, references[RESULT_EVENT])


def test_original_m0_reservation_stays_terminal_when_result_append_is_missing(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    capture = _SourceResultCapture()
    context = replace(
        _context_with_origin(engine, store.origin.ledger_path),
        original_result_observer=capture,
    )
    run = execute_experiment_run(_specification(), context)
    assert capture.artifacts is not None
    assert capture.m0_event_id is not None
    # A previous uncertain writer reserved this exact original M0 event.
    # There is no RESULT to claim, and retry may not silently reuse it.
    SQLiteLedger(store.origin.ledger_path).append(
        AuditEventDraft(
            event_id=uuid7(),
            event_type=M0_USE_EVENT,
            timestamp=RESULT_OBSERVED,
            entity_type="stage1_synthetic_result",
            entity_id=observer._account.verified_original().allocation_id,
            payload={"uncertain_prior_reservation": True},
            deduplication_key=f"stage1:original-m0-use:{capture.m0_event_id}",
            schema_version="2",
        )
    )
    with pytest.raises(
        OriginalResultAssociationError, match="ORIGINAL_M0_EVENT_ALREADY_ASSOCIATED"
    ):
        observer.observe_canonical_result(
            run=run, artifacts=capture.artifacts, m0_audit_event_id=capture.m0_event_id
        )
    assert all(
        event.event_type != RESULT_EVENT for event in store.origin.verified_events()
    )
    with pytest.raises(OriginalResultAssociationError, match="ALREADY_ATTEMPTED"):
        observer.observe_canonical_result(
            run=run, artifacts=capture.artifacts, m0_audit_event_id=capture.m0_event_id
        )


def test_legacy_consumption_and_m0_cannot_be_upgraded_after_execution(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    context = _context_with_origin(engine, store.origin.ledger_path)
    run = execute_experiment_run(_specification(), context)
    assert run.status is ExperimentRunStatus.COMPLETED
    before = store.origin.verified_events()
    assert all(event.schema_version == "1" for event in before)
    m0 = next(
        event for event in before if event.event_type == "m2.evaluation.run.recorded"
    )
    with pytest.raises(
        OriginalResultAssociationError, match="NOT_ORIGINAL_ACCOUNT_EVENT"
    ):
        observer.observe_canonical_result(
            run=run, artifacts=_run(_engine()), m0_audit_event_id=m0.event_id
        )
    assert store.origin.verified_events() == before


class _AnyReferenceUUID(UUID):
    def __ne__(self, other: object) -> bool:
        return False


class _AnyReferenceHash(str):
    def __ne__(self, other: object) -> bool:
        return False


@pytest.mark.parametrize("forged_leaf", ("event_id", "event_hash", "both"))
def test_cold_reader_refuses_noncanonical_reference_equality(
    tmp_path: Path, forged_leaf: str
) -> None:
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    account = observer._account.verified_original()
    genuine = observer.readback()
    reference = LocalEventReferenceV1(
        _AnyReferenceUUID(int=uuid7().int)
        if forged_leaf in {"event_id", "both"}
        else genuine.association_ref.event_id,
        _AnyReferenceHash("0" * 64)
        if forged_leaf in {"event_hash", "both"}
        else genuine.association_ref.event_hash,
    )
    before = store.origin.verified_events()
    with pytest.raises(OriginalResultAssociationError):
        _cold_read(observer, store.origin, account, reference)
    assert store.origin.verified_events() == before


@pytest.mark.parametrize("foreign_envelope", [False, True])
def test_original_artifact_chunk_orphan_refuses_even_with_valid_ledger_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, foreign_envelope: bool
) -> None:
    """A post-RESULT orphan cannot disappear from a complete chunk inventory."""
    import base64

    from drift.loop import stage1_original_result_association as storage

    monkeypatch.setattr(storage, "MAX_ARTIFACT_BYTES", 1_024)
    monkeypatch.setattr(storage, "ARTIFACT_CHUNK_BYTES", 512)
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    original = observer.readback()
    events = store.origin.verified_events()
    chunk = next(event for event in events if event.event_type == storage.CHUNK_EVENT)
    assert isinstance(chunk.payload, Mapping)
    fields = dict(chunk.payload)
    fields["data_base64"] = base64.b64encode(b"forged").decode("ascii")
    SQLiteLedger(store.origin.ledger_path).append(
        AuditEventDraft(
            event_id=uuid7(),
            event_type=storage.CHUNK_EVENT,
            timestamp=RESULT_OBSERVED,
            entity_type=chunk.entity_type,
            entity_id=uuid7() if foreign_envelope else chunk.entity_id,
            payload=fields,
            deduplication_key="synthetic:orphan:" + str(uuid7()),
            schema_version="1",
        )
    )
    store.origin.verified_events()
    with pytest.raises(
        OriginalResultAssociationError, match="RESULT_CHUNK_INVENTORY_INCOMPLETE"
    ):
        observer.readback()
    assert not original.scientifically_qualified


def test_interrupted_artifact_chunk_retention_never_recredits_original_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial v3 artifact write remains unresolved and cannot retry M0."""
    from drift.loop import stage1_original_result_association as storage

    monkeypatch.setattr(storage, "MAX_ARTIFACT_BYTES", 1_024)
    monkeypatch.setattr(storage, "ARTIFACT_CHUNK_BYTES", 512)
    engine, observer, store = _setup(tmp_path)
    actual_append = SQLiteLedger.append
    chunks = 0

    def fail_second_chunk(ledger: SQLiteLedger, draft: AuditEventDraft) -> AuditEvent:
        nonlocal chunks
        if draft.event_type == storage.CHUNK_EVENT:
            chunks += 1
            if chunks == 2:
                raise OSError("injected v3 chunk retention uncertainty")
        return actual_append(ledger, draft)

    monkeypatch.setattr(SQLiteLedger, "append", fail_second_chunk)
    with pytest.raises(OSError, match="chunk retention uncertainty"):
        _execute(engine, observer, store)
    assert chunks == 2
    with pytest.raises(
        OriginalResultAssociationError, match="ORIGINAL_RESULT_NOT_RETAINED"
    ):
        observer.readback()
    events = store.origin.verified_events()
    assert any(e.event_type == storage.CHUNK_EVENT for e in events)
    assert all(
        e.event_type not in {storage.RESULT_EVENT, storage.M0_USE_EVENT} for e in events
    )
    assert any(e.event_type == CONSUMED for e in events)
    second = _execute(engine, observer, store)
    assert second.status is ExperimentRunStatus.FAILED
    remaining = store.origin.verified_events()
    assert sum(event.event_type == ALLOCATION for event in remaining) == 1
    assert sum(event.event_type == CONSUMED for event in remaining) == 1
    assert all(event.event_type != storage.RESULT_EVENT for event in remaining)


def test_original_chunk_reader_enforces_uncompressed_resource_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verified chunk hashes never authorize an unbounded decoded payload."""
    from drift.loop import stage1_original_result_association as storage

    monkeypatch.setattr(storage, "MAX_ARTIFACT_BYTES", 1_024)
    monkeypatch.setattr(storage, "ARTIFACT_CHUNK_BYTES", 512)
    engine, observer, store = _setup(tmp_path)
    _execute(engine, observer, store)
    assert observer.readback().original_artifacts_bytes
    before = store.origin.verified_events()
    monkeypatch.setattr(storage, "MAX_ORIGINAL_ARTIFACT_BYTES", 2_048)
    with pytest.raises(
        OriginalResultAssociationError, match="RESULT_CHUNK_MANIFEST_INVALID"
    ):
        observer.readback()
    assert store.origin.verified_events() == before
