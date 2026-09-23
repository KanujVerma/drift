"""Integration: M3-shaped baselines consume the EXPLORATORY reconstructed path.

Issue 46 invariant 9 requires that M3 can drive deterministic exploratory
baselines through this path. These tests run baseline-shaped strategies over a
genuine scheduled-reconstruction corpus through the public M0 experiment
runner, the entry point M3 will use, and pin two facts: the path is
deterministic across experiment runs, and a baseline that trades executes and
marks on EXPLORATORY reconstructed prices. Issue 46 authorized reconstructed
evidence for decisions only, so a trading baseline used to halt at its first
execution open; the issue 54 ruling (Q2 in #62) admits reconstructed opens as
exploratory execution prices and closes as exploratory marks.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from exploratory_decision_test_support import (  # noqa: E402
    JAN5,
    JAN6,
    JAN7,
    SEC,
    DualLaneStrategy,
    ReconstructedTargetStrategy,
    bundle_of,
    reconstructed_engine,
    run_engine,
    three_regular_sessions,
)
from test_evaluator_engine import (  # noqa: E402
    CODE_VERSION_HASH,
    ENVIRONMENT_HASH,
    STRATEGY_CODE_HASH,
    _buy_ten,
    _engine,
)
from test_evaluator_experiment_run import _metric, _specification  # noqa: E402

from drift.domain.evaluator_results import EvaluationClassification  # noqa: E402
from drift.domain.evaluator_trace import EvaluationPhase  # noqa: E402
from drift.domain.experiments import ExperimentRunStatus  # noqa: E402
from drift.evaluator.bundles import build_evaluation_run_identity  # noqa: E402
from drift.evaluator.engine import SessionEvaluatorEngine  # noqa: E402
from drift.evaluator.experiment_runner import (  # noqa: E402
    ExperimentRunnerContext,
    execute_experiment_run,
)

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 22, 12, 5, tzinfo=UTC)
MUCH_LATER = datetime(2027, 3, 4, 8, tzinfo=UTC)


def _context(
    engine: SessionEvaluatorEngine,
    strategy: ReconstructedTargetStrategy,
    *,
    started_at: datetime = NOW,
    completed_at: datetime = LATER,
) -> ExperimentRunnerContext:
    return ExperimentRunnerContext(
        run_id=uuid7(),
        started_at=started_at,
        completed_at=completed_at,
        engine=engine,
        strategy=strategy,
        run_identity=build_evaluation_run_identity(
            strategy_hash=STRATEGY_CODE_HASH,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=CODE_VERSION_HASH,
            environment_closure_hash=ENVIRONMENT_HASH,
        ),
        result_artifact_id=uuid7(),
        trace_artifact_id=uuid7(),
        result_artifact_location="artifacts/m2/result.json",
        trace_artifact_location="artifacts/m2/trace.json",
    )


def test_a_baseline_consumes_the_reconstructed_path_deterministically() -> None:
    """Two experiment runs, two run ids, two clocks, one content address."""
    engine = reconstructed_engine(bundle_of(three_regular_sessions()))
    first_strategy = ReconstructedTargetStrategy({})
    second_strategy = ReconstructedTargetStrategy({})

    first = execute_experiment_run(
        _specification(dataset_hash=engine.bundle.bundle_hash),
        _context(engine, first_strategy),
    )
    second = execute_experiment_run(
        _specification(dataset_hash=engine.bundle.bundle_hash),
        _context(
            engine, second_strategy, started_at=MUCH_LATER, completed_at=MUCH_LATER
        ),
    )

    for run in (first, second):
        assert run.status is ExperimentRunStatus.COMPLETED
        assert _metric(run, "classification") == "complete"
        assert _metric(run, "lane") == "exploratory"
        assert _metric(run, "is_promotion_grade_evidence") is False
    assert first.run_id != second.run_id
    assert {ref.content_hash for ref in first.artifact_references} == {
        ref.content_hash for ref in second.artifact_references
    }
    assert len(first_strategy.seen) == len(second_strategy.seen) == 3
    assert [context.model_dump(mode="json") for context in first_strategy.seen] == [
        context.model_dump(mode="json") for context in second_strategy.seen
    ]


def test_a_trading_baseline_executes_and_marks_on_reconstructed_prices() -> None:
    """The deliberate change the issue 46 version of this test anticipated.

    The decision at the JAN5 scheduled close stages a buy. The JAN6 open fills
    it at the reconstructed JAN6 open, and every close marks the position at
    that session's reconstructed close. Each price the fill and the marks read
    is named in the trace under its own exploratory event kind.
    """
    strategy = ReconstructedTargetStrategy({JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)})

    artifacts = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())), strategy
    )

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.lane == "exploratory"
    assert artifacts.result.metrics.committed_fill_count == 1
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [(event.session_index, event.fill.side) for event in fills] == [(1, "buy")]
    priced = [
        (event.session_index, event.phase)
        for event in artifacts.trace.events
        if event.kind == "exploratory_accounting_price"
    ]
    assert priced == [
        (1, EvaluationPhase.OPEN_EXECUTION),
        (1, EvaluationPhase.CLOSE_MARK),
        (2, EvaluationPhase.CLOSE_MARK),
    ]
    assert not any(
        event.kind == "indeterminate_cause" for event in artifacts.trace.events
    )
    decisions = [
        event
        for event in artifacts.trace.events
        if event.kind == "exploratory_strategy_decision"
    ]
    assert [event.session_index for event in decisions] == [0, 1, 2]


def test_one_baseline_class_serves_both_lanes_through_their_own_contexts() -> None:
    """The M3 shape: one class, two methods, and the engine picks the lane."""
    dual = DualLaneStrategy({}, realized_targets=_buy_ten().targets)

    realized = run_engine(_engine(), dual)
    exploratory = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())), dual
    )

    assert realized.result.classification is EvaluationClassification.COMPLETE
    assert exploratory.result.classification is EvaluationClassification.COMPLETE
    assert realized.result.metrics.committed_fill_count == 1
    assert [context.session_key.local_date for context in dual.seen] == [
        JAN5,
        JAN6,
        JAN7,
    ]
    assert dual.seen_realized, "the realized lane never invoked decide"
    assert all(
        type(context).__name__ == "StrategyDecisionContextV1"
        for context in dual.seen_realized
    )
