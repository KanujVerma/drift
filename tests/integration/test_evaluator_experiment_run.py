"""Integration tests binding the M2 evaluator to M0 experiment provenance.

The evaluator result and trace are content-addressed and carry no wall-clock
time. Operational metadata (run identifier, start and completion instants,
artifact identifiers) belongs to the M0 ``ExperimentRun`` and is supplied by
the caller, so replaying one evaluation under two different runs must produce
byte-identical result and trace hashes.
"""

import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid7

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_evaluator_engine import (  # noqa: E402
    CODE_VERSION_HASH,
    DAY_1,
    DAY_2,
    DAY_3,
    DAYS,
    ENVIRONMENT_HASH,
    SEC_A,
    STRATEGY_CODE_HASH,
    FixedTargetStrategy,
    _accounting_view,
    _bundle,
    _engine,
    _protocol,
    _run_identity,
)

from drift.domain.artifacts import ArtifactKind, ArtifactReference  # noqa: E402
from drift.domain.common import ImmutableJSONValue  # noqa: E402
from drift.domain.datasets import DatasetReference, TemporalCoverage  # noqa: E402
from drift.domain.evaluator_results import EvaluationClassification  # noqa: E402
from drift.domain.events import AuditEvent  # noqa: E402
from drift.domain.experiments import (  # noqa: E402
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpecification,
)
from drift.domain.strategies import StrategyReference  # noqa: E402
from drift.evaluator.engine import SessionEvaluatorEngine  # noqa: E402
from drift.evaluator.experiment_runner import (  # noqa: E402
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.ledger.sqlite import SQLiteLedger  # noqa: E402
from drift.serialization.canonical import content_hash  # noqa: E402

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 1, 12, 5, tzinfo=UTC)
MUCH_LATER = datetime(2027, 3, 4, 8, tzinfo=UTC)

DATASET_HASH = "d" * 64
SPEC_HASH = "b" * 64


def _artifact(kind: ArtifactKind, digest: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid7(),
        kind=kind,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _dataset() -> DatasetReference:
    return DatasetReference(
        dataset_id=uuid7(),
        dataset_version="2026.01.08",
        schema_version="1",
        content_hash=DATASET_HASH,
        created_at=NOW,
        source="synthetic M2 evaluation corpus",
        temporal_coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
        point_in_time_policy="Use values known at each observation time.",
        corporate_action_policy="Use unadjusted source-basis prices.",
        availability_timestamp_policy="Use source availability timestamps.",
        manifest_reference=_artifact(ArtifactKind.DATASET, SPEC_HASH),
    )


def _specification(*, code_hash: str = STRATEGY_CODE_HASH) -> ExperimentSpecification:
    return ExperimentSpecification(
        experiment_id=uuid7(),
        hypothesis_ids=(uuid7(),),
        strategy_reference=StrategyReference(
            strategy_id=uuid7(),
            strategy_version="1",
            code_hash=code_hash,
            artifact_reference=_artifact(ArtifactKind.STRATEGY, code_hash),
        ),
        dataset_reference=_dataset(),
        parameters={"target_quantity": 10},
        benchmark="Equal-weighted universe return",
        evaluation_protocol={"decision_clock": "post_close_next_open"},
        cost_assumptions={"bps": 0},
        preregistered_metrics=("net_profit_and_loss",),
        parent_experiment_ids=(),
        created_at=NOW,
    )


def _context(
    engine: SessionEvaluatorEngine,
    *,
    strategy: FixedTargetStrategy | None = None,
    run_id: UUID | None = None,
    started_at: datetime = NOW,
    completed_at: datetime = LATER,
    ledger: SQLiteLedger | None = None,
    audit_event_id: UUID | None = None,
) -> ExperimentRunnerContext:
    return ExperimentRunnerContext(
        run_id=uuid7() if run_id is None else run_id,
        started_at=started_at,
        completed_at=completed_at,
        engine=engine,
        strategy=_buy_ten() if strategy is None else strategy,
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
        ),
        result_artifact_id=uuid7(),
        trace_artifact_id=uuid7(),
        result_artifact_location="artifacts/m2/result.json",
        trace_artifact_location="artifacts/m2/trace.json",
        ledger=ledger,
        audit_event_id=uuid7() if audit_event_id is None else audit_event_id,
    )


def _payload_status(event: AuditEvent) -> ImmutableJSONValue:
    """Read the recorded status out of one audit event payload."""
    payload = event.payload
    assert isinstance(payload, Mapping)
    return payload["status"]


def _metric(run: ExperimentRun, name: str) -> ImmutableJSONValue:
    """Read one metric out of an experiment run's canonical metrics mapping."""
    metrics = run.metrics
    assert isinstance(metrics, Mapping)
    return metrics[name]


def _buy_ten() -> FixedTargetStrategy:
    return FixedTargetStrategy(
        {DAY_1: ((SEC_A, 10),), DAY_2: ((SEC_A, 10),), DAY_3: ((SEC_A, 10),)}
    )


# --- completed runs ------------------------------------------------------


def test_completed_run_binds_result_and_trace_artifacts() -> None:
    engine = _engine()
    context = _context(engine)

    run = execute_experiment_run(_specification(), context)

    assert run.status is ExperimentRunStatus.COMPLETED
    assert run.completed_at == LATER
    kinds = {reference.kind for reference in run.artifact_references}
    assert kinds == {ArtifactKind.RESULT, ArtifactKind.LOG}


def test_completed_run_artifact_hashes_are_the_content_addresses() -> None:
    engine = _engine()
    context = _context(engine)
    artifacts = engine.run(strategy=context.strategy, run_identity=context.run_identity)

    run = execute_experiment_run(_specification(), _context(engine))

    digests = {
        reference.kind: reference.content_hash for reference in run.artifact_references
    }
    assert digests[ArtifactKind.RESULT] == artifacts.result.result_hash
    assert digests[ArtifactKind.LOG] == artifacts.trace.trace_hash


def test_completed_run_carries_the_preregistered_summary_metrics() -> None:
    run = execute_experiment_run(_specification(), _context(_engine()))

    assert _metric(run, "classification") == "complete"
    # Money is carried in the canonical M1c spelling, so 200.00 renders "200".
    assert Decimal(str(_metric(run, "net_profit_and_loss"))) == Decimal("200.00")
    assert _metric(run, "committed_fill_count") == 1
    assert _metric(run, "evaluated_session_count") == len(DAYS)


def test_completed_run_binds_the_deterministic_run_identity_hashes() -> None:
    specification = _specification()

    run = execute_experiment_run(specification, _context(_engine()))

    assert run.code_hash == CODE_VERSION_HASH
    assert run.environment_hash == ENVIRONMENT_HASH
    assert run.dataset_hash == specification.dataset_reference.content_hash
    assert run.parameters_hash == content_hash(specification.parameters)
    assert run.experiment_id == specification.experiment_id


# --- replay determinism across experiment runs ---------------------------


def test_replay_under_two_experiment_runs_is_bitwise_identical() -> None:
    specification = _specification()
    first = execute_experiment_run(
        specification,
        _context(_engine(), run_id=uuid7(), started_at=NOW, completed_at=LATER),
    )
    second = execute_experiment_run(
        specification,
        _context(
            _engine(),
            run_id=uuid7(),
            started_at=MUCH_LATER,
            completed_at=MUCH_LATER,
        ),
    )

    assert first.run_id != second.run_id
    assert first.started_at != second.started_at

    def _digests(run: object) -> dict[ArtifactKind, str]:
        return {
            reference.kind: reference.content_hash
            for reference in run.artifact_references  # type: ignore[attr-defined]
        }

    assert _digests(first) == _digests(second)
    assert first.metrics == second.metrics


def test_a_different_specification_cannot_change_the_evaluation_hashes() -> None:
    engine = _engine()
    first = execute_experiment_run(_specification(), _context(engine))
    second = execute_experiment_run(_specification(), _context(engine))

    assert first.experiment_id != second.experiment_id
    assert {reference.content_hash for reference in first.artifact_references} == {
        reference.content_hash for reference in second.artifact_references
    }


# --- halted evaluations ---------------------------------------------------


def test_indeterminate_evaluation_still_completes_the_experiment_run() -> None:
    views = tuple(_accounting_view(SEC_A, day) for day in DAYS if day != DAY_2)
    engine = _engine(bundle=_bundle(accounting_views=views))

    run = execute_experiment_run(_specification(), _context(engine))

    assert run.status is ExperimentRunStatus.COMPLETED
    assert run.error_details is None
    assert (
        _metric(run, "classification") == EvaluationClassification.INDETERMINATE.value
    )
    assert _metric(run, "halted_session_index") == 2


def test_rejected_evaluation_still_completes_the_experiment_run() -> None:
    engine = _engine()
    strategy = FixedTargetStrategy({DAY_1: ((SEC_A, 1000),)})

    run = execute_experiment_run(_specification(), _context(engine, strategy=strategy))

    assert run.status is ExperimentRunStatus.COMPLETED
    assert _metric(run, "classification") == EvaluationClassification.REJECTED.value
    assert _metric(run, "committed_fill_count") == 0


# --- failure path ----------------------------------------------------------


class _ExplodingStrategy(FixedTargetStrategy):
    def decide(self, context: object) -> object:  # type: ignore[override]
        raise RuntimeError("strategy raised on session " + str(context))


def test_unhandled_exception_fails_the_experiment_run_with_error_details() -> None:
    engine = _engine()
    context = _context(engine, strategy=_ExplodingStrategy({}))

    run = execute_experiment_run(_specification(), context)

    assert run.status is ExperimentRunStatus.FAILED
    assert run.error_details is not None
    assert "strategy raised on session" in run.error_details
    assert run.artifact_references == ()
    assert run.completed_at == LATER


def test_runner_requires_the_specification_to_name_the_evaluated_strategy() -> None:
    engine = _engine()

    with pytest.raises(ValueError, match="specification strategy does not match"):
        execute_experiment_run(_specification(code_hash="f" * 64), _context(engine))


def test_runner_requires_a_completion_at_or_after_its_start() -> None:
    engine = _engine()

    with pytest.raises(ValueError, match="completion cannot precede"):
        execute_experiment_run(
            _specification(),
            _context(engine, started_at=LATER, completed_at=NOW),
        )


# --- audit ledger integration ----------------------------------------------


def test_runner_appends_one_audit_event_for_a_completed_run(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = _engine()
    context = _context(engine, ledger=ledger)

    run = execute_experiment_run(_specification(), context)

    events = ledger.verified_events()
    assert len(events) == 1
    assert events[0].entity_type == "experiment_run"
    assert events[0].entity_id == run.run_id
    assert _payload_status(events[0]) == "completed"


def test_runner_appends_an_audit_event_for_a_failed_run(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = _engine()
    context = _context(engine, strategy=_ExplodingStrategy({}), ledger=ledger)

    execute_experiment_run(_specification(), context)

    events = ledger.verified_events()
    assert len(events) == 1
    assert _payload_status(events[0]) == "failed"


def test_runner_writes_no_audit_event_without_a_ledger() -> None:
    run = execute_experiment_run(_specification(), _context(_engine()))

    assert run.status is ExperimentRunStatus.COMPLETED


# --- protocol coupling -----------------------------------------------------


def test_metrics_report_the_exact_terminal_book() -> None:
    run = execute_experiment_run(
        _specification(), _context(_engine(protocol=_protocol()))
    )

    assert Decimal(str(_metric(run, "ending_cash"))) == Decimal("9000.00")
    assert Decimal(str(_metric(run, "ending_net_asset_value"))) == Decimal("10200.00")
    assert Decimal(str(_metric(run, "gross_traded_notional"))) == Decimal("1000.00")
    assert _metric(run, "lane") == "exploratory"
    assert _metric(run, "is_promotion_grade_evidence") is False
