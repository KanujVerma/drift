"""#508 PR C: actual M0/M2 RESULT retained with the original synthetic account.

These are offline structural tests, not historical G3/scientific eligibility.
"""

# ruff: noqa: E402
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import pytest

_UNIT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT) not in sys.path:
    sys.path.insert(0, str(_UNIT))

from test_evaluator_engine import DAY_1, SEC_A, FixedTargetStrategy, _engine, _run
from test_evaluator_experiment_run import (
    _context,
    _ExplodingStrategy,
    _specification,
)
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.experiments import ExperimentRun, ExperimentRunStatus
from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import (
    M0_USE_EVENT,
    RESULT_EVENT,
    OriginalResultAssociationError,
    Stage1OriginalResultAssociationV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json

BASE = datetime(2026, 10, 21, 19, 0, tzinfo=UTC)
M0_START = BASE + timedelta(seconds=2)
M0_COMPLETE = BASE + timedelta(seconds=6)
RESULT_OBSERVED = BASE + timedelta(minutes=1)


@dataclass
class _Tick:
    now: datetime = BASE
    ticks: int = 0

    def __call__(self) -> datetime:
        value = self.now + timedelta(seconds=self.ticks)
        self.ticks += 1
        return value


def _setup(
    tmp_path: Path,
    *,
    arm: str = "ARM-B",
    store: LocalSyntheticAccountReceiptStoreV1 | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[
    SessionEvaluatorEngine,
    Stage1OriginalResultAssociationV1,
    LocalSyntheticAccountReceiptStoreV1,
]:
    actual_store = store
    if actual_store is None:
        origin = ConfiguredLocalSyntheticOriginV1(
            ledger_path=tmp_path / "owner-original.sqlite3",
            issuer_instance_id=uuid7(),
        )
        actual_store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=_Tick())
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    provenance = build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        run_id="RUN-001",
        arm_id=arm,
        checkpoint_id="CKPT-001",
        events=(),
    )
    lifecycle = Stage1SyntheticAccountLifecycleV1(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        provenance=provenance,
        store=actual_store,
    )
    engine = _engine()
    engine.prepare_opening_book(lifecycle=lifecycle)
    association = Stage1OriginalResultAssociationV1(
        origin=actual_store.origin,
        account=lifecycle,
        provenance=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        clock=(lambda: RESULT_OBSERVED) if clock is None else clock,
    )
    return engine, association, actual_store


def _execute(
    engine: SessionEvaluatorEngine,
    observer: Stage1OriginalResultAssociationV1,
    store: LocalSyntheticAccountReceiptStoreV1,
    *,
    strategy: FixedTargetStrategy | None = None,
    completed_at: datetime = M0_COMPLETE,
) -> ExperimentRun:
    context = replace(
        _context(
            engine,
            ledger=SQLiteLedger(store.origin.ledger_path),
            started_at=M0_START,
            completed_at=completed_at,
            strategy=strategy,
        ),
        original_result_observer=observer,
    )
    return execute_experiment_run(_specification(), context)


def test_actual_m0_result_trace_book_and_e1_account_are_retained(
    tmp_path: Path,
) -> None:
    original_engine = _engine()
    baseline = _run(original_engine)
    engine, association, store = _setup(tmp_path)
    run = _execute(engine, association, store)
    assert run.status is ExperimentRunStatus.COMPLETED
    retained = association.readback()
    assert retained.account_id == "SYNTH-ACC-B-001"
    assert retained.run_id == "RUN-001"
    assert retained.arm_id == "ARM-B"
    assert retained.checkpoint_id == "CKPT-001"
    assert retained.classification == "complete"
    assert not retained.original_issuer_authenticated_for_e6b
    assert not retained.scientifically_qualified
    assert retained.original_artifacts.result.result_hash == baseline.result.result_hash
    assert retained.original_artifacts.trace.trace_hash == baseline.trace.trace_hash
    assert retained.original_artifacts.final_state == baseline.final_state
    assert retained.original_artifacts_bytes == canonical_json(
        retained.original_artifacts
    )
    from drift.domain.artifacts import ArtifactKind

    by_kind = {ref.kind: ref.content_hash for ref in run.artifact_references}
    assert by_kind[ArtifactKind.RESULT] == retained.result_hash
    assert by_kind[ArtifactKind.LOG] == retained.trace_hash
    original_events = store.origin.verified_events()
    m0_audit = [
        event
        for event in original_events
        if event.event_type == "m2.evaluation.run.recorded"
    ]
    assert len(m0_audit) == 1
    assert m0_audit[0].schema_version == "3"
    m0_data = m0_audit[0].payload
    assert isinstance(m0_data, Mapping)
    assert m0_data["original_final_book_hash"] == retained.final_book_hash
    types = [event.event_type for event in original_events]
    assert types == [
        "stage1.synthetic_account.allocation",
        "stage1.synthetic_account.allocation_observed",
        "stage1.synthetic_account.invocation_claim",
        "stage1.synthetic_account.book_consumed",
        "m2.evaluation.run.recorded",
        M0_USE_EVENT,
        RESULT_EVENT,
    ]


def test_independent_b_r_accounts_keep_separate_original_results(
    tmp_path: Path,
) -> None:
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "paired.sqlite3", issuer_instance_id=uuid7()
    )
    store = LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=_Tick())
    b_engine, b_observer, _ = _setup(tmp_path, arm="ARM-B", store=store)
    r_engine, r_observer, _ = _setup(tmp_path, arm="ARM-R", store=store)
    b = _execute(b_engine, b_observer, store)
    # Both original allocations precede B's run. R's later invocation
    # consumes more ledger time, so its original M0 completion must follow
    # the R consumption event. Never backdate it to the B completion time.
    r = _execute(
        r_engine,
        r_observer,
        store,
        completed_at=BASE + timedelta(seconds=12),
    )
    assert b.status is ExperimentRunStatus.COMPLETED
    assert r.status is ExperimentRunStatus.COMPLETED
    pb, pr = b_observer.readback(), r_observer.readback()
    assert pb.account_id == "SYNTH-ACC-B-001"
    assert pr.account_id == "SYNTH-ACC-R-001"
    assert pb.association_ref != pr.association_ref
    assert pb.operational_m0_run_id != pr.operational_m0_run_id
    assert pb.result_hash == pr.result_hash
    assert pb.trace_hash == pr.trace_hash
    original_results = [
        event for event in origin.verified_events() if event.event_type == RESULT_EVENT
    ]
    original_m0_uses = [
        event for event in origin.verified_events() if event.event_type == M0_USE_EVENT
    ]
    assert len(original_results) == 2
    assert len(original_m0_uses) == 2
    assert len({event.deduplication_key for event in original_m0_uses}) == 2


def test_no_order_original_result_does_not_invent_fills(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    run = _execute(engine, observer, store, strategy=FixedTargetStrategy({}))
    assert run.status is ExperimentRunStatus.COMPLETED
    record = observer.readback()
    assert record.classification == EvaluationClassification.COMPLETE.value
    assert record.original_artifacts.result.metrics.committed_fill_count == 0
    assert record.original_artifacts.trace.trace_hash == record.trace_hash
    assert not record.scientifically_qualified


def test_evaluator_rejection_is_not_scientific_completion(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    oversized = FixedTargetStrategy({DAY_1: ((SEC_A, 999999),)})
    run = _execute(engine, observer, store, strategy=oversized)
    assert run.status is ExperimentRunStatus.COMPLETED
    retained = observer.readback()
    assert retained.classification == EvaluationClassification.REJECTED.value
    assert retained.original_artifacts.result.metrics.committed_fill_count == 0
    assert retained.scientifically_qualified is False


def test_failed_m0_attempt_has_no_original_result_association(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    failed_run = _execute(engine, observer, store, strategy=_ExplodingStrategy({}))
    assert failed_run.status is ExperimentRunStatus.FAILED
    with pytest.raises(
        OriginalResultAssociationError, match="ORIGINAL_RESULT_NOT_RETAINED"
    ):
        observer.readback()
    assert all(e.event_type != RESULT_EVENT for e in store.origin.verified_events())


def test_observer_requires_a_real_original_m0_audit_before_stepping(
    tmp_path: Path,
) -> None:
    engine, observer, store = _setup(tmp_path)
    context = replace(
        _context(engine, started_at=M0_START, completed_at=M0_COMPLETE),
        original_result_observer=observer,
        ledger=None,
    )
    with pytest.raises(ValueError, match="requires an M0 audit ledger"):
        execute_experiment_run(_specification(), context)
    assert [e.event_type for e in store.origin.verified_events()] == [
        "stage1.synthetic_account.allocation",
        "stage1.synthetic_account.allocation_observed",
    ]


def test_strategy_cannot_suppress_original_result_observer_during_decide(
    tmp_path: Path,
) -> None:
    """Caller context changes cannot redirect the original M0 collaborators."""
    engine, original, store = _setup(tmp_path)

    class ObserverErasingStrategy(FixedTargetStrategy):
        run_context: ExperimentRunnerContext | None = None

        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            assert self.run_context is not None
            object.__setattr__(self.run_context, "original_result_observer", None)
            object.__setattr__(self.run_context, "ledger", None)
            object.__setattr__(self.run_context, "engine", _engine())
            return super().decide(context)

    strategy = ObserverErasingStrategy({})
    ctx = replace(
        _context(
            engine,
            ledger=SQLiteLedger(store.origin.ledger_path),
            started_at=M0_START,
            completed_at=M0_COMPLETE,
            strategy=strategy,
        ),
        original_result_observer=original,
    )
    strategy.run_context = ctx
    run = execute_experiment_run(_specification(), ctx)
    assert run.status is ExperimentRunStatus.COMPLETED
    assert ctx.original_result_observer is None
    assert ctx.ledger is None
    assert ctx.engine is not engine
    recorded_m0 = [
        e
        for e in store.origin.verified_events()
        if e.event_type == "m2.evaluation.run.recorded"
    ]
    assert len(recorded_m0) == 1
    assert recorded_m0[0].schema_version == "3"
    retained = original.readback()
    assert retained.result_hash in {r.content_hash for r in run.artifact_references}
    assert not retained.scientifically_qualified


def test_bounded_chunked_original_result_can_be_cold_verified_without_v1_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the additive v3 path with real evaluator artifacts and tiny chunks."""
    from drift.loop import stage1_original_result_association as storage
    from drift.loop.stage1_original_result_association import (
        CHUNK_EVENT,
        read_original_result,
    )

    monkeypatch.setattr(storage, "MAX_ARTIFACT_BYTES", 1_024)
    monkeypatch.setattr(storage, "ARTIFACT_CHUNK_BYTES", 512)
    engine, observer, store = _setup(tmp_path)
    run = _execute(engine, observer, store)
    assert run.status is ExperimentRunStatus.COMPLETED
    events = store.origin.verified_events()
    chunks = [e for e in events if e.event_type == CHUNK_EVENT]
    receipts = [e for e in events if e.event_type == RESULT_EVENT]
    assert len(receipts) == 1 and receipts[0].schema_version == "3"
    assert len(chunks) >= 2
    assert all(e.schema_version == "1" for e in chunks)
    assert isinstance(receipts[0].payload, Mapping)
    assert receipts[0].payload["artifact_chunk_count"] == len(chunks)
    original = observer.readback()
    cold = read_original_result(
        origin=store.origin,
        original_account=observer._account.verified_original(),
        association_ref=original.association_ref,
        provenance=observer._provenance,
        campaign=make_golden_campaign(),
        arms=(make_golden_arm_b(), make_golden_arm_r()),
        bindings=tuple(make_golden_bindings()),
        expected_run_ids=("RUN-001",),
        clock=lambda: RESULT_OBSERVED + timedelta(minutes=1),
    )
    assert original.original_artifacts_bytes == cold.original_artifacts_bytes
    assert cold.original_artifacts_bytes == canonical_json(cold.original_artifacts)
    assert cold.result_hash == original.result_hash
    assert not cold.original_issuer_authenticated_for_e6b
    assert not cold.scientifically_qualified
