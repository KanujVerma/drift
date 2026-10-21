"""#508 PR C adversaries: forged M0 roots, account scopes and duplicate RESULT.

These tests are entirely offline; a local hash chain does not appoint an
accepted issuer or scientific experiment authority.
"""

# ruff: noqa: E402
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

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
    M0_COMPLETE,
    M0_START,
    _execute,
    _setup,
)

from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.experiments.stage1_trial_provenance import (
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.loop.stage1_original_result_association import (
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
