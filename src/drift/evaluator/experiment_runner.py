"""Bind one deterministic M2 evaluation to an M0 experiment run record.

The split of responsibility is the point of this module. The evaluator's
result and trace are content-addressed and reproducible: no random
identifier, no wall-clock instant. The operational facts of an execution -
which run it was, when it started, when it finished, and which artifact rows
hold its outputs - belong to M0 `ExperimentRun` and are supplied by the
caller through `ExperimentRunnerContext`.

That keeps replay honest. Running one evaluation twice under two different
`ExperimentRun` identifiers and two different clocks produces two experiment
rows whose bound artifact hashes are byte-identical.

The promotion lane is disabled (the issue 79 ruling). Behind the engine's own
refusal, the runner refuses a promotion admission before running, and refuses
a promotion result before recording, so no M0 experiment run and no audit
event ever records ``lane=promotion``. The runner trusts no object an engine
returns: it rebuilds the artifacts through canonical JSON, refuses the rebuilt
result if it is in the promotion lane or claims promotion-grade evidence, and
records only from the rebuilt objects (issue 120 review, F-A). A valid rebuild
is not proof the artifacts are this run's, so the rebuilt result must also
carry the context's run identity over the dataset the M0 row records (issue
124). The caller's own inputs are not trusted either: every one the runner
compares is rebuilt through canonical JSON first, and only those canonical
copies are compared and recorded (issue 123).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import TypeAdapter

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7, ImmutableJSONValue
from drift.domain.datasets import DatasetReference
from drift.domain.evaluator_bundles import EvaluationRunIdentityV1
from drift.domain.evaluator_results import (
    EvaluationResultV1,
    EvaluationRunArtifactsV1,
    EvaluationSummaryMetricsV1,
)
from drift.domain.evaluator_trace import EvaluationTraceLogV1
from drift.domain.experiments import (
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpecification,
)
from drift.domain.strategies import StrategyReference
from drift.errors import DriftError
from drift.evaluator.engine import (
    LaneDispatchStrategy,
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    refuse_promotion_lane,
)
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.serialization.canonical import content_hash

EXPERIMENT_RUN_EVENT_TYPE = "m2.evaluation.run.recorded"
EXPERIMENT_RUN_ENTITY_TYPE = "experiment_run"
EXPERIMENT_RUN_EVENT_SCHEMA_VERSION = "1"


class ForeignRunArtifactsError(DriftError, ValueError):
    """Raised when an engine returns artifacts that are not this run's (#124).

    A canonical rebuild proves the returned artifacts are valid, not that they
    came from the run the context names. A genuine run over another bundle,
    protocol, cost model, strategy or evaluator evidence would otherwise be
    recorded under this run's M0 row. Nothing is recorded when this is raised.
    """


@dataclass(frozen=True)
class ExperimentRunnerContext:
    """Everything an execution needs that the evaluation itself must not own.

    Every identifier and instant here is operational metadata. None of it
    reaches the evaluator, so none of it can perturb a result hash.
    """

    run_id: UUID7
    started_at: datetime
    completed_at: datetime
    engine: SessionEvaluatorEngine
    strategy: LaneDispatchStrategy
    run_identity: EvaluationRunIdentityV1
    result_artifact_id: UUID7
    trace_artifact_id: UUID7
    result_artifact_location: str
    trace_artifact_location: str
    ledger: Ledger | None = None
    audit_event_id: UUID7 | None = None


@dataclass(frozen=True)
class _CallerInputs:
    """Canonical copies of every caller input the runner compares (issue 123)."""

    run_identity: EvaluationRunIdentityV1
    dataset_hash: str
    specified_strategy_hash: str
    running_strategy_hash: str
    started_at: datetime
    completed_at: datetime


_RUN_IDENTITY: TypeAdapter[EvaluationRunIdentityV1] = TypeAdapter(
    EvaluationRunIdentityV1
)
_DATASET: TypeAdapter[DatasetReference] = TypeAdapter(DatasetReference)
_STRATEGY: TypeAdapter[StrategyReference] = TypeAdapter(StrategyReference)
_INSTANT: TypeAdapter[datetime] = TypeAdapter(datetime)


def _canonical[T](declared: TypeAdapter[T], value: T) -> T:
    """Rebuild one caller input through canonical JSON as its declared type.

    The declared type's serializer reads the value, not the value's own
    methods, and validating the JSON it writes yields only fresh, exact
    built-in leaves. A subclass with forged equality, or a leaf such as a
    ``str`` equal to every string, then compares as the text it spells
    (issue 123). An input that fails its rebuild raises before anything runs.
    """
    return declared.validate_json(declared.dump_json(value, warnings=False))


def _caller_inputs(
    specification: ExperimentSpecification, context: ExperimentRunnerContext
) -> _CallerInputs:
    """Canonical copies of the caller inputs, taken before any comparison.

    Comparing a rebuilt value with a caller's object is not enough: Python
    asks a right operand that subclasses the left one first, so a forged
    ``__eq__`` answers whichever side it is on.
    """
    return _CallerInputs(
        run_identity=_canonical(_RUN_IDENTITY, context.run_identity),
        dataset_hash=_canonical(_DATASET, specification.dataset_reference).content_hash,
        specified_strategy_hash=_canonical(
            _STRATEGY, specification.strategy_reference
        ).code_hash,
        running_strategy_hash=_canonical(
            _STRATEGY, context.strategy.strategy_reference
        ).code_hash,
        started_at=_canonical(_INSTANT, context.started_at),
        completed_at=_canonical(_INSTANT, context.completed_at),
    )


def summary_metrics_payload(
    result: EvaluationResultV1,
) -> dict[str, ImmutableJSONValue]:
    """Project one evaluation result into a canonical metrics mapping.

    Exact decimals are carried as their canonical text. Rendering them as
    floats would make a metrics row disagree with the book it summarizes.
    A promotion result is refused, never projected (issue 79 ruling).
    """
    refuse_promotion_lane(result, site="the summary metrics projection")
    metrics: EvaluationSummaryMetricsV1 = result.metrics
    payload: dict[str, ImmutableJSONValue] = {
        "lane": result.lane,
        "classification": result.classification.value,
        "is_promotion_grade_evidence": result.is_promotion_grade_evidence,
        "evaluated_session_count": metrics.evaluated_session_count,
        "committed_fill_count": metrics.committed_fill_count,
        "halted_session_index": result.halted_session_index,
        "result_hash": result.result_hash,
        "trace_hash": result.trace_hash,
        "run_identity_hash": result.run_identity.run_identity_hash,
    }
    exact: Mapping[str, Decimal] = {
        "initial_cash": metrics.initial_cash,
        "initial_net_asset_value": metrics.initial_net_asset_value,
        "ending_cash": metrics.ending_cash,
        "ending_net_asset_value": metrics.ending_net_asset_value,
        "net_profit_and_loss": metrics.net_profit_and_loss,
        "realized_gross_pnl": metrics.realized_gross_pnl,
        "realized_net_pnl": metrics.realized_net_pnl,
        "cumulative_transaction_costs": metrics.cumulative_transaction_costs,
        "gross_traded_notional": metrics.gross_traded_notional,
    }
    payload.update({name: str(value) for name, value in exact.items()})
    return payload


def _rebuilt_artifacts(artifacts: EvaluationRunArtifactsV1) -> EvaluationRunArtifactsV1:
    """Rebuild what an engine returned before any of it is recorded (#120 F-A).

    The returned object is refused first if it names the promotion lane or
    claims promotion-grade evidence. It is then rebuilt through canonical
    JSON, not a python-mode dump: a python-mode rebuild keeps subclassed leaf
    values and so any attacker-defined equality inside them (issue 123), while
    a JSON rebuild validates every member as its declared type over exact
    built-in leaves. The rebuilt result is refused in turn, and only the
    rebuilt objects are recorded.
    """
    refuse_promotion_lane(
        artifacts.result, site="the experiment runner on the returned result"
    )
    rebuilt = EvaluationRunArtifactsV1.model_validate_json(
        artifacts.model_dump_json(warnings=False)
    )
    refuse_promotion_lane(
        rebuilt.result, site="the experiment runner on the rebuilt result"
    )
    return rebuilt


def _refuse_foreign_run(
    inputs: _CallerInputs, recorded: EvaluationRunArtifactsV1
) -> None:
    """Refuse rebuilt artifacts that are not this run's (issue 124).

    The run identity binds everything that changes results (issue 86): the
    bundle, protocol, cost model, strategy, admission, evaluator evidence,
    code version and environment closure. The rebuilt result must carry
    exactly the identity the engine was asked to run. Its bundle must also be
    the dataset the M0 row records, checked against the result itself, so the
    row never names one dataset over a result evaluated on another. Both
    sides are canonical copies (issue 123).
    """
    identity = recorded.result.run_identity
    if identity != inputs.run_identity:
        raise ForeignRunArtifactsError(
            "the returned run is not this run: its run identity is "
            f"{identity.run_identity_hash}, this run is "
            f"{inputs.run_identity.run_identity_hash}"
        )
    if identity.bundle_hash != inputs.dataset_hash:
        raise ForeignRunArtifactsError(
            f"the returned result was evaluated over bundle {identity.bundle_hash}, "
            f"not the dataset this run records, {inputs.dataset_hash}"
        )


def _artifact_references(
    context: ExperimentRunnerContext, artifacts: EvaluationRunArtifactsV1
) -> tuple[ArtifactReference, ...]:
    result: EvaluationResultV1 = artifacts.result
    trace: EvaluationTraceLogV1 = artifacts.trace
    return (
        ArtifactReference(
            artifact_id=context.result_artifact_id,
            kind=ArtifactKind.RESULT,
            content_hash=result.result_hash,
            location=context.result_artifact_location,
        ),
        ArtifactReference(
            artifact_id=context.trace_artifact_id,
            kind=ArtifactKind.LOG,
            content_hash=trace.trace_hash,
            location=context.trace_artifact_location,
        ),
    )


def _validate_context(inputs: _CallerInputs) -> None:
    """Check the caller's inputs against each other, as canonical copies."""
    if inputs.completed_at < inputs.started_at:
        raise ValueError(
            "an experiment run completion cannot precede its start: "
            f"{inputs.completed_at.isoformat()} precedes "
            f"{inputs.started_at.isoformat()}"
        )
    identity = inputs.run_identity
    # The experiment row must name the strategy that was actually evaluated.
    # Without this an ExperimentRun could attribute one strategy's evidence to
    # a different strategy version.
    if identity.strategy_hash != inputs.specified_strategy_hash:
        raise ValueError(
            "the specification strategy does not match the evaluated run "
            f"identity: specification names "
            f"{inputs.specified_strategy_hash}, run identity binds "
            f"{identity.strategy_hash}"
        )
    # Issue 86: the row must also name the strategy that actually runs, and
    # the dataset must be the bundle the run identity binds.
    running = inputs.running_strategy_hash
    if running != identity.strategy_hash:
        raise ValueError(
            "the strategy that runs does not match the run identity: the "
            f"strategy is {running}, run identity binds "
            f"{identity.strategy_hash}"
        )
    dataset = inputs.dataset_hash
    if dataset != identity.bundle_hash:
        raise ValueError(
            "the specification dataset is not the evaluated bundle: "
            f"specification names {dataset}, run identity binds "
            f"{identity.bundle_hash}"
        )


def _record_audit_event(context: ExperimentRunnerContext, run: ExperimentRun) -> None:
    ledger = context.ledger
    if ledger is None:
        return
    if context.audit_event_id is None:
        raise ValueError("recording an experiment run requires an audit event id")
    ledger.append(
        AuditEventDraft(
            event_id=context.audit_event_id,
            event_type=EXPERIMENT_RUN_EVENT_TYPE,
            timestamp=context.completed_at,
            entity_type=EXPERIMENT_RUN_ENTITY_TYPE,
            entity_id=run.run_id,
            payload={
                "experiment_id": str(run.experiment_id),
                "status": run.status.value,
                "artifact_hashes": tuple(
                    reference.content_hash for reference in run.artifact_references
                ),
                "metrics": dict(run.metrics)
                if isinstance(run.metrics, Mapping)
                else {},
                "error_details": run.error_details,
            },
            schema_version=EXPERIMENT_RUN_EVENT_SCHEMA_VERSION,
        )
    )


def execute_experiment_run(
    specification: ExperimentSpecification, context: ExperimentRunnerContext
) -> ExperimentRun:
    """Execute one M2 evaluation and record it as an M0 experiment run.

    A halted evaluation is still a completed experiment: `INDETERMINATE` and
    `REJECTED` are scientific answers, and the run records them with its
    artifacts bound. Only an unhandled defect produces `FAILED`, and it binds
    no artifacts because the evaluation produced none that can be trusted.

    A promotion admission or result is not a defect but a refusal (issue 79
    ruling): it raises `PromotionLaneDisabledError` and records nothing, and
    so does that error raised from inside the engine run. Returned artifacts
    that fail their canonical rebuild are not recorded either; the validation
    error propagates. Nor are rebuilt artifacts of another run (issue 124):
    they raise `ForeignRunArtifactsError`.

    Every caller input the runner compares (the run identity, the dataset and
    strategy references, and the start and completion instants) is rebuilt
    through canonical JSON before any comparison, and only the canonical
    copies are compared, run and recorded (issue 123). An input that fails
    its rebuild raises its validation error and records nothing.
    """
    refuse_promotion_lane(context.engine.admission, site="the experiment runner")
    inputs = _caller_inputs(specification, context)
    _validate_context(inputs)
    common: dict[str, object] = {
        "run_id": context.run_id,
        "experiment_id": specification.experiment_id,
        "started_at": inputs.started_at,
        "completed_at": inputs.completed_at,
        "code_hash": inputs.run_identity.code_version_hash,
        "environment_hash": inputs.run_identity.environment_closure_hash,
        "dataset_hash": inputs.dataset_hash,
        "parameters_hash": content_hash(specification.parameters),
    }
    try:
        artifacts = context.engine.run(
            strategy=context.strategy, run_identity=inputs.run_identity
        )
    except PromotionLaneDisabledError:
        # A refusal from inside the run is still a refusal (issue 120 review,
        # F-B): it is never laundered into a recorded FAILED run.
        raise
    except Exception as error:
        detail = (
            f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
        )
        run = ExperimentRun.model_validate(
            common
            | {
                "status": ExperimentRunStatus.FAILED,
                "metrics": {},
                "artifact_references": (),
                "error_details": detail,
            }
        )
        _record_audit_event(context, run)
        return run
    recorded = _rebuilt_artifacts(artifacts)
    _refuse_foreign_run(inputs, recorded)
    run = ExperimentRun.model_validate(
        common
        | {
            "status": ExperimentRunStatus.COMPLETED,
            "metrics": summary_metrics_payload(recorded.result),
            "artifact_references": _artifact_references(context, recorded),
        }
    )
    _record_audit_event(context, run)
    return run
