"""Integration tests binding the M2 evaluator to M0 experiment provenance.

The evaluator result and trace are content-addressed and carry no wall-clock
time. Operational metadata (run identifier, start and completion instants,
artifact identifiers) belongs to the M0 ``ExperimentRun`` and is supplied by
the caller, so replaying one evaluation under two different runs must produce
byte-identical result and trace hashes.
"""

import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any, Self, cast
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_evaluator_engine import (  # noqa: E402
    BOOK_NAMESPACE,
    CODE_VERSION_HASH,
    DAY_1,
    DAY_2,
    DAY_3,
    DAYS,
    ENVIRONMENT_HASH,
    ROLE_RECORDS,
    SEC_A,
    STRATEGY_CODE_HASH,
    FixedTargetStrategy,
    _accounting_view,
    _bundle,
    _bypassed_promotion_engine,
    _cost_model,
    _engine,
    _promotion_admission,
    _protocol,
    _run_identity,
)

from drift.domain.artifacts import ArtifactKind, ArtifactReference  # noqa: E402
from drift.domain.common import ImmutableJSONValue  # noqa: E402
from drift.domain.datasets import DatasetReference, TemporalCoverage  # noqa: E402
from drift.domain.evaluator_bundles import EvaluationRunIdentityV1  # noqa: E402
from drift.domain.evaluator_portfolio import PortfolioStateV2  # noqa: E402
from drift.domain.evaluator_results import (  # noqa: E402
    EvaluationClassification,
    EvaluationRunArtifactsV2,
    ExploratoryEvaluationResultV1,
    PromotionEvaluationResultV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_strategy import (  # noqa: E402
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.evaluator_trace import (  # noqa: E402
    EvaluationTraceLogV1,
    evaluation_trace_log_hash,
)
from drift.domain.events import AuditEvent  # noqa: E402
from drift.domain.experiments import (  # noqa: E402
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpecification,
)
from drift.domain.strategies import StrategyReference  # noqa: E402
from drift.evaluator.bundles import build_evaluation_run_identity  # noqa: E402
from drift.evaluator.engine import (  # noqa: E402
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)
from drift.evaluator.experiment_runner import (  # noqa: E402
    ExperimentRunnerContext,
    ForeignRunArtifactsError,
    execute_experiment_run,
    summary_metrics_payload,
)
from drift.ledger.sqlite import SQLiteLedger  # noqa: E402
from drift.serialization.canonical import content_hash  # noqa: E402

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 1, 12, 5, tzinfo=UTC)
MUCH_LATER = datetime(2027, 3, 4, 8, tzinfo=UTC)

# The dataset an M2 run records is the bundle its run identity binds (#86).
DATASET_HASH = _bundle().bundle_hash
SPEC_HASH = "b" * 64


def _artifact(kind: ArtifactKind, digest: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=uuid7(),
        kind=kind,
        content_hash=digest,
        location=f"drift+sha256://{digest}",
    )


def _dataset(content_hash: str = DATASET_HASH) -> DatasetReference:
    return DatasetReference(
        dataset_id=uuid7(),
        dataset_version="2026.01.08",
        schema_version="1",
        content_hash=content_hash,
        created_at=NOW,
        source="synthetic M2 evaluation corpus",
        temporal_coverage=TemporalCoverage(started_at=NOW, ended_at=NOW),
        point_in_time_policy="Use values known at each observation time.",
        corporate_action_policy="Use unadjusted source-basis prices.",
        availability_timestamp_policy="Use source availability timestamps.",
        manifest_reference=_artifact(ArtifactKind.DATASET, SPEC_HASH),
    )


def _specification(
    *, code_hash: str = STRATEGY_CODE_HASH, dataset_hash: str = DATASET_HASH
) -> ExperimentSpecification:
    return ExperimentSpecification(
        experiment_id=uuid7(),
        hypothesis_ids=(uuid7(),),
        strategy_reference=StrategyReference(
            strategy_id=uuid7(),
            strategy_version="1",
            code_hash=code_hash,
            artifact_reference=_artifact(ArtifactKind.STRATEGY, code_hash),
        ),
        dataset_reference=_dataset(dataset_hash),
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
            evidence_hash=engine.evaluator_evidence_hash,
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

    run = execute_experiment_run(
        _specification(dataset_hash=engine.bundle.bundle_hash), _context(engine)
    )

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


# --- the promotion lane is disabled (issue 79 ruling) ----------------------

PROMOTION_LANE_DISABLED = r"^the promotion lane is disabled \(issue 79 ruling\): "


def test_runner_refuses_a_promotion_admission_and_records_nothing(
    tmp_path: Path,
) -> None:
    """Defense in depth behind the engine: refused before the engine runs.

    The engine is in the state 19c15f8 built for a promotion admission, which
    construction now refuses. The runner refuses it before running, so no
    session is stepped, no experiment run is returned, and the audit ledger
    stays empty.
    """
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    strategy = _buy_ten()
    context = _context(_bypassed_promotion_engine(), strategy=strategy, ledger=ledger)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "the experiment runner refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert strategy.seen == []
    assert ledger.verified_events() == ()


def _promotion_artifacts(engine: SessionEvaluatorEngine) -> EvaluationRunArtifactsV2:
    """A valid promotion pair over a genuine exploratory run's own trace.

    The artifact types accept this (finding F9, tracked as P9 on issue 115):
    the result binds its trace by hash only, and the realized trace carries no
    reconstructed-evidence event for the pairing to refuse.
    """
    genuine = engine.run(
        strategy=FixedTargetStrategy({}),
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
    )
    promotion = _promotion_admission(engine.bundle)
    draft = PromotionEvaluationResultV1.model_construct(
        run_identity=_run_identity(
            admission=promotion,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        classification=genuine.result.classification,
        metrics=genuine.result.metrics,
        trace_hash=genuine.result.trace_hash,
        admission=promotion,
        result_hash="0" * 64,
    )
    result = PromotionEvaluationResultV1.model_validate(
        dict(draft) | {"result_hash": evaluation_result_hash(draft)}
    )
    state = genuine.final_state
    assert state.mark is not None and state.mark.prices == ()
    final_state = PortfolioStateV2.model_validate(
        dict(state)
        | {
            "lane": "promotion",
            "admission_hash": promotion.admission_hash,
            "mark": state.mark.model_copy(update={"lane": "promotion"}),
        }
    )
    return EvaluationRunArtifactsV2.model_validate(
        {"result": result, "trace": genuine.trace, "final_state": final_state}
    )


class _StandInEngine:
    """An engine stand-in admitting exploratory, whose run returns ``artifacts``.

    No production engine returns anything but its own sealed artifacts. The
    runner does not rely on that: it refuses and rebuilds whatever comes back,
    and never records a promotion result or a promotion-grade claim.
    """

    def __init__(self, engine: SessionEvaluatorEngine, artifacts: object) -> None:
        self._engine = engine
        self._artifacts = artifacts

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)

    def run(self, **_: object) -> Any:
        return self._artifacts


class _Proxy:
    """Delegates to ``inner``, except for the attributes it lies about."""

    def __init__(self, inner: object, **lies: object) -> None:
        self.__dict__.update(lies)
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _Liar(str):
    """A lane equal to nothing, so ``lane == "promotion"`` is always False."""

    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        return False

    def __ne__(self, other: object) -> bool:
        return True


class _EqualToEveryDate(date):
    """A date equal to every date: python-mode revalidation keeps it (#123)."""

    __hash__ = date.__hash__

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


def _stand_in_context(
    tmp_path: Path, artifacts: object
) -> tuple[SQLiteLedger, ExperimentRunnerContext]:
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    engine = cast(SessionEvaluatorEngine, _StandInEngine(_engine(), artifacts))
    assert engine.admission.lane == "exploratory"
    return ledger, _context(engine, ledger=ledger)


def _genuine_artifacts() -> EvaluationRunArtifactsV2:
    engine = _engine()
    return engine.run(
        strategy=_buy_ten(),
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
    )


def _with_result(
    artifacts: EvaluationRunArtifactsV2, **changes: object
) -> EvaluationRunArtifactsV2:
    """The pair with a hand-built result; nothing here is revalidated."""
    result = ExploratoryEvaluationResultV1.model_construct(
        **(dict(artifacts.result) | changes)
    )
    return EvaluationRunArtifactsV2.model_construct(
        **(dict(artifacts) | {"result": result})
    )


def test_runner_never_records_a_promotion_result(tmp_path: Path) -> None:
    ledger, context = _stand_in_context(tmp_path, _promotion_artifacts(_engine()))

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the returned result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_an_exploratory_result_claiming_promotion_grade(
    tmp_path: Path,
) -> None:
    """Issue 120 review, S1: the flag is refused whatever lane is named."""
    forged = _with_result(_genuine_artifacts(), is_promotion_grade_evidence=True)
    assert forged.result.lane == "exploratory"
    ledger, context = _stand_in_context(tmp_path, forged)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the returned result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_a_truthy_non_bool_promotion_grade_claim(
    tmp_path: Path,
) -> None:
    """Issue 124 (#120 review N2): anything but exactly ``False`` is refused.

    ``1`` is not ``True``, so a flag check weakened to ``is True`` lets it
    through to the rebuild, which fails it only as a literal mismatch. The
    named refusal must come first.
    """
    forged = _with_result(_genuine_artifacts(), is_promotion_grade_evidence=1)
    assert forged.result.lane == "exploratory"
    assert forged.result.is_promotion_grade_evidence is not True
    ledger, context = _stand_in_context(tmp_path, forged)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the returned result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_a_result_whose_lane_equals_nothing(tmp_path: Path) -> None:
    """Issue 120 review, S2: a lying lane cannot hide a promotion-grade claim."""
    forged = _with_result(
        _genuine_artifacts(),
        lane=_Liar("promotion"),
        is_promotion_grade_evidence=True,
    )
    assert forged.result.lane != "promotion"
    ledger, context = _stand_in_context(tmp_path, forged)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the returned result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_a_promotion_result_behind_a_lane_lying_proxy(
    tmp_path: Path,
) -> None:
    """Issue 120 review, S3: the proxy says exploratory; the claim still shows."""
    promotion = _promotion_artifacts(_engine())
    proxy = _Proxy(promotion, result=_Proxy(promotion.result, lane="exploratory"))
    ledger, context = _stand_in_context(tmp_path, proxy)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the returned result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_the_promotion_result_its_rebuild_reveals(
    tmp_path: Path,
) -> None:
    """Every attribute the runner reads lies; only the rebuild sees promotion."""
    promotion = _promotion_artifacts(_engine())
    disguise = _Proxy(
        promotion.result, lane="exploratory", is_promotion_grade_evidence=False
    )
    ledger, context = _stand_in_context(tmp_path, _Proxy(promotion, result=disguise))

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED
        + "the experiment runner on the rebuilt result refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_records_only_from_the_rebuilt_artifacts(tmp_path: Path) -> None:
    """What the returned object claims is never what the runner records."""
    genuine = _genuine_artifacts()
    claimed = "f" * 64
    proxy = _Proxy(genuine, result=_Proxy(genuine.result, result_hash=claimed))
    ledger, context = _stand_in_context(tmp_path, proxy)

    run = execute_experiment_run(_specification(), context)

    assert run.status is ExperimentRunStatus.COMPLETED
    assert _metric(run, "result_hash") == genuine.result.result_hash
    assert [ref.content_hash for ref in run.artifact_references] == [
        genuine.result.result_hash,
        genuine.trace.trace_hash,
    ]
    (event,) = ledger.verified_events()
    payload = event.payload
    assert isinstance(payload, Mapping)
    assert payload["artifact_hashes"] == (
        genuine.result.result_hash,
        genuine.trace.trace_hash,
    )


def test_runner_records_nothing_that_validates_only_through_forged_equality(
    tmp_path: Path,
) -> None:
    """The rebuild is canonical JSON, not python mode (issue 123).

    One trace event is moved to the next day under a date equal to every
    date, and the trace and result are resealed over it. Its validators pass
    under that equality, so a python-mode rebuild admits the pair and would
    record it. The JSON rebuild compares real dates and refuses it.
    """
    genuine = _genuine_artifacts()
    events = list(genuine.trace.events)
    event = events[-1]
    assert event.kind != "session_start"
    key = event.session_key
    later = key.local_date + timedelta(days=1)
    moved = key.model_construct(
        **(
            dict(key)
            | {"local_date": _EqualToEveryDate(later.year, later.month, later.day)}
        )
    )
    events[-1] = event.model_construct(**(dict(event) | {"session_key": moved}))
    draft = EvaluationTraceLogV1.model_construct(
        schema_version="1", events=tuple(events), trace_hash="0" * 64
    )
    trace = draft.model_construct(
        **(dict(draft) | {"trace_hash": evaluation_trace_log_hash(draft)})
    )
    unsealed = ExploratoryEvaluationResultV1.model_construct(
        **(dict(genuine.result) | {"trace_hash": trace.trace_hash})
    )
    result = unsealed.model_construct(
        **(dict(unsealed) | {"result_hash": evaluation_result_hash(unsealed)})
    )
    forged = EvaluationRunArtifactsV2.model_construct(
        **(dict(genuine) | {"result": result, "trace": trace})
    )
    admitted = EvaluationRunArtifactsV2.model_validate(
        forged.model_dump(mode="python", warnings=False)
    )
    assert admitted.trace.trace_hash == trace.trace_hash
    ledger, context = _stand_in_context(tmp_path, forged)

    with pytest.raises(
        ValidationError, match="a trace event session key must match its open"
    ):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_a_refusal_raised_inside_the_run_is_never_recorded(tmp_path: Path) -> None:
    """Issue 120 review, F-B: a mid-run refusal is not a recorded FAILED run.

    The strategy swaps the engine's admission for a promotion admission while
    the run is under way, past the runner's own refusal, so the engine's
    sealing site refuses from inside the run.
    """
    engine = _engine()
    promotion = _promotion_admission(engine.bundle)

    class _Swapping(FixedTargetStrategy):
        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            engine._admission = promotion
            return super().decide(context)

    strategy = _Swapping({DAY_1: ((SEC_A, 10),)})
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    context = _context(engine, strategy=strategy, ledger=ledger)

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "result sealing refuses",
    ):
        execute_experiment_run(_specification(), context)

    assert strategy.seen
    assert ledger.verified_events() == ()


def test_the_summary_projection_refuses_a_promotion_result() -> None:
    """Issue 120 review, F-E: nothing projects a promotion result into metrics."""
    promotion = _promotion_artifacts(_engine())

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "the summary metrics projection refuses",
    ):
        summary_metrics_payload(promotion.result)

    # Control: an exploratory result projects.
    assert summary_metrics_payload(_genuine_artifacts().result)["lane"] == (
        "exploratory"
    )


# --- the returned run must be this run (issue 124) -------------------------

FOREIGN_RUN = r"^the returned run is not this run: "
OTHER_STRATEGY_HASH = "d" * 64
OTHER_CODE_VERSION_HASH = "9" * 64


class _EqualToEveryText(str):
    """A hash equal to every string, as a context identity could carry one."""

    __hash__ = str.__hash__

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


class _OtherStrategy(FixedTargetStrategy):
    """The same targets under another strategy version."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return StrategyReference(
            strategy_id=uuid7(),
            strategy_version="2",
            code_hash=OTHER_STRATEGY_HASH,
            artifact_reference=_artifact(ArtifactKind.STRATEGY, OTHER_STRATEGY_HASH),
        )


def _run_of(
    engine: SessionEvaluatorEngine,
    strategy: FixedTargetStrategy | None = None,
    *,
    strategy_hash: str = STRATEGY_CODE_HASH,
    code_version_hash: str = CODE_VERSION_HASH,
) -> EvaluationRunArtifactsV2:
    """A genuine run of ``engine``, sealed under the identity it names."""
    return engine.run(
        strategy=_buy_ten() if strategy is None else strategy,
        run_identity=build_evaluation_run_identity(
            strategy_hash=strategy_hash,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=code_version_hash,
            environment_closure_hash=ENVIRONMENT_HASH,
        ),
    )


def _euro_book_engine() -> SessionEvaluatorEngine:
    base = _engine()
    return SessionEvaluatorEngine(
        bundle=base.bundle,
        admission=base.admission,
        protocol=base.protocol,
        cost_model=base.cost_model,
        evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code="EUR",
    )


def test_runner_refuses_a_genuine_run_over_another_bundle(tmp_path: Path) -> None:
    """Issue 124 (#120 review R3): the misattribution probe.

    A stand-in engine returns a genuine exploratory run over a three-session
    bundle. It rebuilds cleanly, and was recorded COMPLETED under an M0 row
    naming the four-session dataset.
    """
    foreign = _run_of(_engine(bundle=_bundle(days=DAYS[:3])), FixedTargetStrategy({}))
    ledger, context = _stand_in_context(tmp_path, foreign)
    assert foreign.result.run_identity.bundle_hash != DATASET_HASH
    assert foreign.result.run_identity != context.run_identity

    with pytest.raises(ForeignRunArtifactsError, match=FOREIGN_RUN):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


FOREIGN_RUNS_OVER_THIS_BUNDLE: dict[str, Callable[[], EvaluationRunArtifactsV2]] = {
    "protocol": lambda: _run_of(_engine(protocol=_protocol(cash="20000.00"))),
    "cost model": lambda: _run_of(_engine(cost_model=_cost_model(commission="0.01"))),
    "strategy": lambda: _run_of(
        _engine(),
        _OtherStrategy(_buy_ten().targets),
        strategy_hash=OTHER_STRATEGY_HASH,
    ),
    "evaluator evidence": lambda: _run_of(_euro_book_engine()),
    "code version": lambda: _run_of(
        _engine(), code_version_hash=OTHER_CODE_VERSION_HASH
    ),
}


@pytest.mark.parametrize(
    "variant", sorted(FOREIGN_RUNS_OVER_THIS_BUNDLE), ids=lambda name: name
)
def test_runner_refuses_a_genuine_run_of_this_bundle_under_another_identity(
    tmp_path: Path, variant: str
) -> None:
    """The run identity binds more than the bundle, and all of it must match."""
    foreign = FOREIGN_RUNS_OVER_THIS_BUNDLE[variant]()
    ledger, context = _stand_in_context(tmp_path, foreign)
    identity = foreign.result.run_identity
    assert identity.bundle_hash == context.run_identity.bundle_hash == DATASET_HASH
    assert identity.admission_hash == context.run_identity.admission_hash
    assert identity != context.run_identity

    with pytest.raises(ForeignRunArtifactsError, match=FOREIGN_RUN):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


def test_runner_refuses_a_result_over_another_bundle_whatever_the_context_claims(
    tmp_path: Path,
) -> None:
    """No claim in the context can pair the row with a result over another bundle.

    The context names the foreign run's identity, except that its bundle hash
    equals every string, so it matches the specification's dataset and the
    foreign result's bundle alike. Before issue 123 the runner compared that
    object as given, and only the dataset check on the result itself refused
    it (``FOREIGN_BUNDLE``). The runner now compares only a canonical copy of
    the context's identity, whose bundle hash is the text it spells, so the
    copy fails its own identity hash and is refused before the engine runs.
    """
    foreign = _run_of(_engine(bundle=_bundle(days=DAYS[:3])), FixedTargetStrategy({}))
    identity = foreign.result.run_identity
    claimed = identity.model_construct(
        **(dict(identity) | {"bundle_hash": _EqualToEveryText(DATASET_HASH)})
    )
    ledger, genuine_context = _stand_in_context(tmp_path, foreign)
    context = replace(genuine_context, run_identity=claimed)
    assert identity == claimed
    assert identity.bundle_hash != DATASET_HASH

    with pytest.raises(ValidationError, match=r"run identity hash mismatch"):
        execute_experiment_run(_specification(), context)

    assert ledger.verified_events() == ()


# --- the runner compares only canonical caller inputs (issue 123) -------------


class _IdentityEqualToEveryIdentity(EvaluationRunIdentityV1):
    """A genuine run identity whose equality is forged."""

    __hash__ = EvaluationRunIdentityV1.__hash__

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


def _identity_equal_to_every_identity(
    context: ExperimentRunnerContext,
) -> EvaluationRunIdentityV1:
    return _IdentityEqualToEveryIdentity.model_validate(
        context.run_identity.model_dump()
    )


def _identity_of_text_equal_to_every_text(
    context: ExperimentRunnerContext,
) -> EvaluationRunIdentityV1:
    forged: dict[str, Any] = {
        name: _EqualToEveryText(value)
        for name, value in dict(context.run_identity).items()
    }
    return EvaluationRunIdentityV1.model_construct(**forged)


def _specification_of_a_dataset_equal_to_every_dataset() -> ExperimentSpecification:
    honest = _specification()
    dataset = honest.dataset_reference.model_construct(
        **(
            dict(honest.dataset_reference)
            | {"content_hash": _EqualToEveryText(DATASET_HASH)}
        )
    )
    return honest.model_construct(**(dict(honest) | {"dataset_reference": dataset}))


type _CallerForgery = Callable[
    [ExperimentRunnerContext], tuple[ExperimentRunnerContext, ExperimentSpecification]
]

#: The residual probe of the PR 126 review, cases A0 to A1b. A stand-in engine
#: returns a genuine run over another bundle. One lying caller input was caught
#: by the other comparison, but a lying identity together with a lying dataset
#: reference recorded a misattributed row.
CALLER_FORGERIES: dict[str, _CallerForgery] = {
    "A0 identity equal to every identity": lambda context: (
        replace(context, run_identity=_identity_equal_to_every_identity(context)),
        _specification(),
    ),
    "A0b identity of text equal to every text": lambda context: (
        replace(context, run_identity=_identity_of_text_equal_to_every_text(context)),
        _specification(),
    ),
    "A0c dataset equal to every dataset": lambda context: (
        context,
        _specification_of_a_dataset_equal_to_every_dataset(),
    ),
    "A1 identity and dataset equal to every one": lambda context: (
        replace(context, run_identity=_identity_equal_to_every_identity(context)),
        _specification_of_a_dataset_equal_to_every_dataset(),
    ),
    "A1b identity text and dataset equal to every one": lambda context: (
        replace(context, run_identity=_identity_of_text_equal_to_every_text(context)),
        _specification_of_a_dataset_equal_to_every_dataset(),
    ),
}


@pytest.mark.parametrize("forgery", sorted(CALLER_FORGERIES), ids=lambda name: name)
def test_runner_compares_only_canonical_copies_of_its_caller_inputs(
    tmp_path: Path, forgery: str
) -> None:
    """Forged equality in a caller input compares as the text it spells."""
    foreign = _run_of(_engine(bundle=_bundle(days=DAYS[:3])), FixedTargetStrategy({}))
    ledger, genuine_context = _stand_in_context(tmp_path, foreign)
    context, specification = CALLER_FORGERIES[forgery](genuine_context)

    with pytest.raises(ForeignRunArtifactsError, match=FOREIGN_RUN):
        execute_experiment_run(specification, context)

    assert ledger.verified_events() == ()


class _PrecedingNothing(datetime):
    """An instant that precedes no instant, whenever it is."""

    def __lt__(self, other: date, /) -> bool:
        return False


class _FollowingNothing(datetime):
    """An instant that follows no instant, whenever it is."""

    def __gt__(self, other: date, /) -> bool:
        return False


def _instant(kind: type[datetime], moment: datetime) -> datetime:
    return kind(
        moment.year, moment.month, moment.day, moment.hour, moment.minute, tzinfo=UTC
    )


def _forged_strategy_reference() -> StrategyReference:
    """Another strategy version, whose declared code hash equals every text."""
    return StrategyReference.model_construct(
        strategy_id=uuid7(),
        strategy_version="2",
        code_hash=_EqualToEveryText(OTHER_STRATEGY_HASH),
        artifact_reference=_artifact(ArtifactKind.STRATEGY, OTHER_STRATEGY_HASH),
    )


class _StrategyOfForgedReference(FixedTargetStrategy):
    """The same targets, declared under a forged strategy reference."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return _forged_strategy_reference()


def _specification_with(**changes: object) -> ExperimentSpecification:
    honest = _specification()
    return honest.model_construct(**(dict(honest) | changes))


def _dataset_of_another_bundle() -> DatasetReference:
    honest = _dataset()
    return honest.model_construct(
        **(dict(honest) | {"content_hash": _EqualToEveryText("f" * 64)})
    )


type _InputForgery = Callable[
    [ExperimentRunnerContext], tuple[ExperimentRunnerContext, ExperimentSpecification]
]

#: Each caller input ``_validate_context`` compares, forged to pass its check,
#: over the real engine, and the refusal its canonical copy meets instead.
#: Before issue 123 each was recorded as a COMPLETED run.
COMPARED_INPUT_FORGERIES: dict[str, tuple[_InputForgery, str]] = {
    "a completion before its start that precedes nothing": (
        lambda context: (
            replace(
                context,
                completed_at=_instant(_PrecedingNothing, NOW - timedelta(minutes=5)),
            ),
            _specification(),
        ),
        r"^an experiment run completion cannot precede its start",
    ),
    "a start after its completion that follows nothing": (
        lambda context: (
            replace(
                context,
                started_at=_instant(_FollowingNothing, LATER + timedelta(minutes=5)),
            ),
            _specification(),
        ),
        r"^an experiment run completion cannot precede its start",
    ),
    "a running strategy of another code hash equal to every text": (
        lambda context: (
            replace(
                context,
                strategy=_StrategyOfForgedReference(_buy_ten().targets),
            ),
            _specification(),
        ),
        r"^the strategy that runs does not match the run identity",
    ),
    "a specified strategy of another code hash equal to every text": (
        lambda context: (
            context,
            _specification_with(strategy_reference=_forged_strategy_reference()),
        ),
        r"^the specification strategy does not match the evaluated run identity",
    ),
    "a dataset of another bundle hash equal to every text": (
        lambda context: (
            context,
            _specification_with(dataset_reference=_dataset_of_another_bundle()),
        ),
        r"^the specification dataset is not the evaluated bundle",
    ),
}


@pytest.mark.parametrize(
    "forgery", sorted(COMPARED_INPUT_FORGERIES), ids=lambda name: name
)
def test_runner_refuses_a_compared_input_whatever_its_comparisons_say(
    tmp_path: Path, forgery: str
) -> None:
    """Each check reads the canonical copy, so nothing runs and nothing records."""
    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    forge, refusal = COMPARED_INPUT_FORGERIES[forgery]
    context, specification = forge(_context(_engine(), ledger=ledger))
    strategy = cast(FixedTargetStrategy, context.strategy)

    with pytest.raises(ValueError, match=refusal):
        execute_experiment_run(specification, context)

    assert strategy.seen == []
    assert ledger.verified_events() == ()


# --- the runner records only canonical caller values (#123 review) -----------

#: What every misspelled caller value below spells, whatever it holds.
MISSPELLED_INSTANT = datetime(2000, 1, 1, tzinfo=UTC)
MISSPELLED_ID = UUID("01990000-0000-7000-8000-00000000dead")


class _MisspelledInstant(datetime):
    """Holds its own instant, but spells and converts as ``MISSPELLED_INSTANT``."""

    def isoformat(self, sep: str = "T", timespec: str = "auto") -> str:
        return MISSPELLED_INSTANT.isoformat(sep, timespec)

    def strftime(self, format: str) -> str:
        return MISSPELLED_INSTANT.strftime(format)

    def astimezone(self, tz: tzinfo | None = None) -> Self:
        return self

    def __str__(self) -> str:
        return str(MISSPELLED_INSTANT)


class _MisspelledIdentifier(UUID):
    """Holds its own identifier, but spells ``MISSPELLED_ID``."""

    def __str__(self) -> str:
        return str(MISSPELLED_ID)


def _misspelled_instant(value: datetime) -> datetime:
    return _MisspelledInstant.fromtimestamp(value.timestamp(), UTC)


def _misspelled_id(value: UUID | None) -> UUID:
    assert value is not None
    return _MisspelledIdentifier(int=value.int)


type _Misspelling = Callable[
    [ExperimentRunnerContext, ExperimentSpecification],
    tuple[ExperimentRunnerContext, ExperimentSpecification],
]

#: Each caller value the runner records, misspelled. The row and the audit
#: event validate in python mode, which keeps a `datetime` or `UUID` subclass,
#: so a raw value would be recorded under the form it spells.
MISSPELLINGS: dict[str, _Misspelling] = {
    "start": lambda context, specification: (
        replace(context, started_at=_misspelled_instant(context.started_at)),
        specification,
    ),
    "completion": lambda context, specification: (
        replace(context, completed_at=_misspelled_instant(context.completed_at)),
        specification,
    ),
    "run id": lambda context, specification: (
        replace(context, run_id=_misspelled_id(context.run_id)),
        specification,
    ),
    "experiment id": lambda context, specification: (
        context,
        specification.model_construct(
            **(
                dict(specification)
                | {"experiment_id": _misspelled_id(specification.experiment_id)}
            )
        ),
    ),
    "audit event id": lambda context, specification: (
        replace(context, audit_event_id=_misspelled_id(context.audit_event_id)),
        specification,
    ),
    "result artifact id": lambda context, specification: (
        replace(context, result_artifact_id=_misspelled_id(context.result_artifact_id)),
        specification,
    ),
    "trace artifact id": lambda context, specification: (
        replace(context, trace_artifact_id=_misspelled_id(context.trace_artifact_id)),
        specification,
    ),
}


@pytest.mark.parametrize("misspelled", sorted(MISSPELLINGS), ids=lambda name: name)
def test_runner_records_a_misspelled_caller_value_as_the_value_it_holds(
    tmp_path: Path, misspelled: str
) -> None:
    """The M0 row and its audit event are those of the honest caller.

    Before the #123 review the audit event was stamped with the raw completion
    instant and the raw audit event, run and experiment identifiers, and the
    row kept the raw identifiers, so each was recorded as the form it spells
    (an audit event of 2000-01-01, before the run's checked start, or a run
    named ``...dead``).
    """
    honest_ledger = SQLiteLedger(tmp_path / "honest.sqlite3")
    forged_ledger = SQLiteLedger(tmp_path / "forged.sqlite3")
    honest = _context(_engine(), ledger=honest_ledger)
    specification = _specification()
    context, forged_specification = MISSPELLINGS[misspelled](
        replace(honest, strategy=_buy_ten(), ledger=forged_ledger), specification
    )

    recorded = execute_experiment_run(forged_specification, context)
    expected = execute_experiment_run(specification, honest)

    assert content_hash(recorded) == content_hash(expected)
    forged_events = forged_ledger.verified_events()
    honest_events = honest_ledger.verified_events()
    assert len(forged_events) == len(honest_events) == 1
    assert content_hash(forged_events[0]) == content_hash(honest_events[0])
    assert forged_events[0].timestamp == LATER


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
