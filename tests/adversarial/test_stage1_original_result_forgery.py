"""#508 PR C adversaries: forged M0 roots, account scopes and duplicate RESULT.

These tests are entirely offline; a local hash chain does not appoint an
accepted issuer or scientific experiment authority.
"""

# ruff: noqa: E402
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

import pytest

for _source in ("unit", "integration"):
    _path = Path(__file__).resolve().parents[1] / _source
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_evaluator_engine import _engine, _run
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
    _Tick,
    _execute,
    _setup,
)

from drift.domain.evaluator_results import EvaluationRunArtifactsV2
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
        e.event_type == "m2.evaluation.run.recorded"
        for e in foreign.verified_events()
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
    context = _context_with_origin(engine, store.origin.ledger_path)
    run = execute_experiment_run(_specification(), context)
    same_content = _run(_engine())
    with pytest.raises(
        OriginalResultAssociationError, match="NOT_THE_ORIGINAL_COMPLETED_M0"
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
    assert len([
        event for event in store.origin.verified_events()
        if event.event_type == RESULT_EVENT
    ]) == 1


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
    # counterfeit settled claim. The original M0 V2 audit did not contain it.
    fake_book = original.artifacts.final_state.model_copy(
        update={"settled_claim_ids": ("a" * 64,)}
    )
    altered = original.artifacts.model_copy(
        update={"final_state": fake_book}
    )
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
    assert len([
        e for e in store.origin.verified_events() if e.event_type == RESULT_EVENT
    ]) == 1


def test_same_original_m0_event_cannot_be_used_for_two_distinct_accounts(
    tmp_path: Path,
) -> None:
    """Ledger-unique M0 reservation prevents reusing B's execution for R."""
    origin = ConfiguredLocalSyntheticOriginV1(
        ledger_path=tmp_path / "same-m0.sqlite3",
        issuer_instance_id=uuid7(),
    )
    store = LocalSyntheticAccountReceiptStoreV1(
        origin=origin,
        clock=_Tick(),
    )
    b_engine, b_observer, _ = _setup(
        tmp_path, arm="ARM-B", store=store
    )
    r_engine, r_observer, _ = _setup(
        tmp_path, arm="ARM-R", store=store
    )
    # Both accounts have independently claimed/consumed their opening books
    # before this sole operational M0 event. Identical genuine result hashes
    # are permitted, but cannot authenticate two independent M0 executions.
    _run(r_engine)
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
    assert len(m0_events) == 1
    with pytest.raises(
        OriginalResultAssociationError,
        match="ORIGINAL_M0_EVENT_ALREADY_ASSOCIATED",
    ):
        r_observer.observe_canonical_result(
            run=b,
            artifacts=retained_b.original_artifacts,
            m0_audit_event_id=m0_events[0].event_id,
        )
    history = origin.verified_events()
    assert len([e for e in history if e.event_type == M0_USE_EVENT]) == 1
    assert len([e for e in history if e.event_type == RESULT_EVENT]) == 1
    assert b_observer.readback().account_id == "SYNTH-ACC-B-001"
