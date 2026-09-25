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
records only from the rebuilt objects (issue 120 review, F-A).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7, ImmutableJSONValue
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


def _validate_context(
    specification: ExperimentSpecification, context: ExperimentRunnerContext
) -> None:
    if context.completed_at < context.started_at:
        raise ValueError(
            "an experiment run completion cannot precede its start: "
            f"{context.completed_at.isoformat()} precedes "
            f"{context.started_at.isoformat()}"
        )
    # The experiment row must name the strategy that was actually evaluated.
    # Without this an ExperimentRun could attribute one strategy's evidence to
    # a different strategy version.
    if context.run_identity.strategy_hash != (
        specification.strategy_reference.code_hash
    ):
        raise ValueError(
            "the specification strategy does not match the evaluated run "
            f"identity: specification names "
            f"{specification.strategy_reference.code_hash}, run identity binds "
            f"{context.run_identity.strategy_hash}"
        )
    # Issue 86: the row must also name the strategy that actually runs, and
    # the dataset must be the bundle the run identity binds.
    running = context.strategy.strategy_reference.code_hash
    if running != context.run_identity.strategy_hash:
        raise ValueError(
            "the strategy that runs does not match the run identity: the "
            f"strategy is {running}, run identity binds "
            f"{context.run_identity.strategy_hash}"
        )
    dataset = specification.dataset_reference.content_hash
    if dataset != context.run_identity.bundle_hash:
        raise ValueError(
            "the specification dataset is not the evaluated bundle: "
            f"specification names {dataset}, run identity binds "
            f"{context.run_identity.bundle_hash}"
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
    error propagates.
    """
    refuse_promotion_lane(context.engine.admission, site="the experiment runner")
    _validate_context(specification, context)
    common: dict[str, object] = {
        "run_id": context.run_id,
        "experiment_id": specification.experiment_id,
        "started_at": context.started_at,
        "completed_at": context.completed_at,
        "code_hash": context.run_identity.code_version_hash,
        "environment_hash": context.run_identity.environment_closure_hash,
        "dataset_hash": specification.dataset_reference.content_hash,
        "parameters_hash": content_hash(specification.parameters),
    }
    try:
        artifacts = context.engine.run(
            strategy=context.strategy, run_identity=context.run_identity
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
