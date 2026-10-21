"""#508 PR C: actual M0/M2 RESULT retained with the original synthetic account.

These are offline structural tests, not historical G3/scientific eligibility.
"""

# ruff: noqa: E402
import sys
from collections.abc import Callable
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
    _ExplodingStrategy,
    _context,
    _specification,
)
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.domain.evaluator_results import EvaluationClassification
from drift.domain.experiments import ExperimentRunStatus
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import (
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
    object,
    Stage1OriginalResultAssociationV1,
    LocalSyntheticAccountReceiptStoreV1,
]:
    actual_store = store
    if actual_store is None:
        origin = ConfiguredLocalSyntheticOriginV1(
            ledger_path=tmp_path / "owner-original.sqlite3",
            issuer_instance_id=uuid7(),
        )
        actual_store = LocalSyntheticAccountReceiptStoreV1(
            origin=origin, clock=_Tick()
        )
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
    engine: object,
    observer: Stage1OriginalResultAssociationV1,
    store: LocalSyntheticAccountReceiptStoreV1,
    *,
    strategy: FixedTargetStrategy | None = None,
) -> object:
    from drift.evaluator.engine import SessionEvaluatorEngine

    assert isinstance(engine, SessionEvaluatorEngine)
    context = replace(
        _context(
            engine,
            ledger=SQLiteLedger(store.origin.ledger_path),
            started_at=M0_START,
            completed_at=M0_COMPLETE,
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
    types = [event.event_type for event in store.origin.verified_events()]
    assert types == [
        "stage1.synthetic_account.allocation",
        "stage1.synthetic_account.allocation_observed",
        "stage1.synthetic_account.invocation_claim",
        "stage1.synthetic_account.book_consumed",
        "m2.evaluation.run.recorded",
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
    r = _execute(r_engine, r_observer, store)
    assert b.status is ExperimentRunStatus.COMPLETED
    assert r.status is ExperimentRunStatus.COMPLETED
    pb, pr = b_observer.readback(), r_observer.readback()
    assert pb.account_id == "SYNTH-ACC-B-001"
    assert pr.account_id == "SYNTH-ACC-R-001"
    assert pb.association_ref != pr.association_ref
    assert pb.operational_m0_run_id != pr.operational_m0_run_id
    assert pb.result_hash == pr.result_hash
    assert pb.trace_hash == pr.trace_hash
    assert len([e for e in origin.verified_events() if e.event_type == RESULT_EVENT]) == 2


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
    from drift.evaluator.engine import SessionEvaluatorEngine

    assert isinstance(engine, SessionEvaluatorEngine)
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
