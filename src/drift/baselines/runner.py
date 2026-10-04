"""Canonical M3 reference baseline execution runner and provenance binding (Issue 109).

Binds whole-tree code-version provenance (drift_source_inventory_hash) to
every canonical baseline run as EvaluationRunIdentityV2.code_version_hash,
ensuring run identity reflects repository state while bundle identity remains
purely semantic and stable across unrelated source edits.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid7

from drift.baselines.b0_cash import B0CashStrategy
from drift.baselines.b1_single_buy_and_hold import B1SingleBuyAndHoldStrategy
from drift.baselines.b2_equal_weight_buy_and_hold import (
    B2EqualWeightBuyAndHoldStrategy,
)
from drift.baselines.b3_monthly_equal_weight_rebalance import (
    B3MonthlyEqualWeightRebalanceStrategy,
)
from drift.baselines.b4_momentum import B4MomentumStrategy
from drift.baselines.b5_low_volatility import B5LowVolatilityStrategy
from drift.baselines.common import deterministic_baseline_uuid7
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7, SHA256Hash
from drift.domain.datasets import DatasetReference, TemporalCoverage
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV2,
    strategy_parameters_hash,
)
from drift.domain.evaluator_lanes import EvaluationAdmissionV1
from drift.domain.experiments import ExperimentRun, ExperimentSpecification
from drift.domain.observation_query import drift_source_inventory_hash
from drift.domain.strategies import StrategyReference
from drift.evaluator.bundles import build_evaluation_run_identity_v2
from drift.evaluator.engine import LaneDispatchStrategy, SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.ledger.interface import Ledger

type BaselineReferenceStrategy = (
    B0CashStrategy
    | B1SingleBuyAndHoldStrategy
    | B2EqualWeightBuyAndHoldStrategy
    | B3MonthlyEqualWeightRebalanceStrategy
    | B4MomentumStrategy
    | B5LowVolatilityStrategy
)


def build_canonical_run_identity(
    *,
    strategy_hash: SHA256Hash,
    strategy_parameters_hash: SHA256Hash,
    protocol_hash: SHA256Hash,
    cost_model_hash: SHA256Hash,
    admission: EvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    evaluator_evidence_hash: SHA256Hash,
    environment_closure_hash: SHA256Hash = "0" * 64,
    code_version_hash: SHA256Hash | None = None,
) -> EvaluationRunIdentityV2:
    """Build canonical EvaluationRunIdentityV2 binding whole-tree provenance.

    Canonical M3 runs bind drift_source_inventory_hash() as code_version_hash
    (issue 109, issue 63 Q6). This ensures that while bundle_hash and admission
    remain stable across unrelated source changes, run identity moves with
    the codebase.
    """
    if code_version_hash is None:
        code_version_hash = drift_source_inventory_hash()
    return build_evaluation_run_identity_v2(
        strategy_hash=strategy_hash,
        strategy_parameters_hash=strategy_parameters_hash,
        protocol_hash=protocol_hash,
        cost_model_hash=cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=evaluator_evidence_hash,
        code_version_hash=code_version_hash,
        environment_closure_hash=environment_closure_hash,
    )


def make_bundle_dataset_reference(
    bundle: EvaluationInputBundleV1,
    *,
    dataset_id: UUID | None = None,
    dataset_version: str = "1",
    created_at: datetime | None = None,
    source: str = "Drift canonical evaluation corpus",
) -> DatasetReference:
    """Derive an immutable DatasetReference bound to the given input bundle."""
    if not bundle.session_clock.sessions:
        raise ValueError("bundle requires a nonempty session clock")
    clock_start = bundle.session_clock.sessions[0].opened_at
    clock_end = bundle.session_clock.sessions[-1].closed_at
    created = created_at or clock_start
    ident = dataset_id or deterministic_baseline_uuid7(
        f"drift.dataset.{bundle.bundle_hash}"
    )
    manifest_artifact_id = deterministic_baseline_uuid7(
        f"drift.manifest.{bundle.bundle_hash}"
    )
    return DatasetReference(
        dataset_id=ident,
        dataset_version=dataset_version,
        schema_version="1",
        content_hash=bundle.bundle_hash,
        created_at=created,
        source=source,
        temporal_coverage=TemporalCoverage(
            started_at=clock_start,
            ended_at=clock_end,
        ),
        point_in_time_policy="Use values known at each observation time.",
        corporate_action_policy=(
            "Use unadjusted source-basis prices or analytical returns."
        ),
        availability_timestamp_policy="Use source availability timestamps.",
        manifest_reference=ArtifactReference(
            artifact_id=manifest_artifact_id,
            kind=ArtifactKind.DATASET,
            content_hash=bundle.bundle_hash,
            location=f"drift+sha256://{bundle.bundle_hash}",
        ),
    )


def build_canonical_specification(
    *,
    strategy: BaselineReferenceStrategy | LaneDispatchStrategy,
    bundle: EvaluationInputBundleV1,
    dataset_reference: DatasetReference | None = None,
    experiment_id: UUID | None = None,
    benchmark: str = "Equal-weighted universe return",
    preregistered_metrics: tuple[str, ...] = ("net_profit_and_loss",),
    created_at: datetime | None = None,
) -> ExperimentSpecification:
    """Build canonical ExperimentSpecification for a baseline execution."""
    ref = getattr(strategy, "strategy_reference", None)
    if not isinstance(ref, StrategyReference):
        raise ValueError("strategy must provide an authentic StrategyReference")
    params = getattr(strategy, "strategy_parameters", {})
    ds_ref = dataset_reference or make_bundle_dataset_reference(bundle)
    now = created_at or bundle.session_clock.sessions[0].opened_at
    exp_id = experiment_id or deterministic_baseline_uuid7(
        f"drift.baseline.experiment.{ref.strategy_id}:{bundle.bundle_hash}"
    )
    return ExperimentSpecification(
        experiment_id=exp_id,
        hypothesis_ids=(
            deterministic_baseline_uuid7(f"drift.hypothesis.{ref.strategy_id}"),
        ),
        strategy_reference=ref,
        dataset_reference=ds_ref,
        parameters=params,
        benchmark=benchmark,
        evaluation_protocol={"decision_clock": "post_close_next_open"},
        cost_assumptions={"bps": 0},
        preregistered_metrics=preregistered_metrics,
        parent_experiment_ids=(),
        created_at=now,
    )


def run_canonical_baseline(
    *,
    engine: SessionEvaluatorEngine,
    strategy: BaselineReferenceStrategy | LaneDispatchStrategy,
    specification: ExperimentSpecification | None = None,
    dataset_reference: DatasetReference | None = None,
    environment_closure_hash: SHA256Hash = "0" * 64,
    code_version_hash: SHA256Hash | None = None,
    run_id: UUID | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    ledger: Ledger | None = None,
    audit_event_id: UUID | None = None,
    result_artifact_location: str | None = None,
    trace_artifact_location: str | None = None,
) -> ExperimentRun:
    """Execute one baseline strategy canonically and record an M0 ExperimentRun.

    Binds drift_source_inventory_hash() as code_version_hash (issue 109)
    unless explicitly overridden.
    """
    ref = getattr(strategy, "strategy_reference", None)
    if not isinstance(ref, StrategyReference):
        raise ValueError("strategy must provide an authentic StrategyReference")
    params = getattr(strategy, "strategy_parameters", {})
    param_hash = strategy_parameters_hash(
        params, label="the canonical baseline strategy parameters"
    )

    if code_version_hash is None:
        code_version_hash = drift_source_inventory_hash()

    run_identity = build_canonical_run_identity(
        strategy_hash=ref.code_hash,
        strategy_parameters_hash=param_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
    )

    actual_spec = specification or build_canonical_specification(
        strategy=strategy,
        bundle=engine.bundle,
        dataset_reference=dataset_reference,
    )

    sessions = engine.bundle.session_clock.sessions
    start_time = started_at or sessions[0].opened_at
    end_time = completed_at or sessions[-1].closed_at
    if end_time < start_time:
        end_time = start_time

    res_loc = (
        result_artifact_location or f"artifacts/baselines/{ref.strategy_id}/result.json"
    )
    trc_loc = (
        trace_artifact_location or f"artifacts/baselines/{ref.strategy_id}/trace.json"
    )

    context = ExperimentRunnerContext(
        run_id=run_id or uuid7(),
        started_at=start_time,
        completed_at=end_time,
        engine=engine,
        strategy=strategy,
        run_identity=run_identity,
        result_artifact_id=uuid7(),
        trace_artifact_id=uuid7(),
        result_artifact_location=res_loc,
        trace_artifact_location=trc_loc,
        ledger=ledger,
        audit_event_id=audit_event_id,
    )

    return execute_experiment_run(actual_spec, context)


@dataclass(frozen=True)
class BaselineSuiteResult:
    """Outcome collection of executing the standard reference baseline suite."""

    runs: Mapping[str, ExperimentRun]


def run_baseline_suite(
    *,
    engine: SessionEvaluatorEngine,
    securities: Sequence[UUID7] | None = None,
    environment_closure_hash: SHA256Hash = "0" * 64,
    code_version_hash: SHA256Hash | None = None,
    ledger: Ledger | None = None,
) -> BaselineSuiteResult:
    """Run standard reference baselines B0 through B5 over one engine."""
    runs: dict[str, ExperimentRun] = {}

    # B0: Cash
    runs["b0_cash"] = run_canonical_baseline(
        engine=engine,
        strategy=B0CashStrategy(),
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
        ledger=ledger,
    )

    # Determine admitted securities for B1 single buy and hold
    if securities is None:
        if engine.bundle.security_identities:
            securities = tuple(s.security_id for s in engine.bundle.security_identities)
        elif engine.bundle.exploratory_reconstructed_observations:
            securities = tuple(
                sorted(
                    {
                        obs.security_id
                        for obs in engine.bundle.exploratory_reconstructed_observations
                    },
                    key=lambda s: s.bytes,
                )
            )
        else:
            securities = ()

    # B1: Single buy and hold per admitted security
    for sec_id in securities:
        runs[f"b1_buy_and_hold_{sec_id}"] = run_canonical_baseline(
            engine=engine,
            strategy=B1SingleBuyAndHoldStrategy(target_security_id=sec_id),
            environment_closure_hash=environment_closure_hash,
            code_version_hash=code_version_hash,
            ledger=ledger,
        )

    # B2: Equal weight cohort buy and hold
    runs["b2_equal_weight_buy_and_hold"] = run_canonical_baseline(
        engine=engine,
        strategy=B2EqualWeightBuyAndHoldStrategy(),
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
        ledger=ledger,
    )

    # B3: Monthly equal weight rebalance
    runs["b3_monthly_equal_weight_rebalance"] = run_canonical_baseline(
        engine=engine,
        strategy=B3MonthlyEqualWeightRebalanceStrategy(),
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
        ledger=ledger,
    )

    # B4: 12-1 Momentum
    runs["b4_momentum"] = run_canonical_baseline(
        engine=engine,
        strategy=B4MomentumStrategy(),
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
        ledger=ledger,
    )

    # B5: 60-Session Low Volatility
    runs["b5_low_volatility"] = run_canonical_baseline(
        engine=engine,
        strategy=B5LowVolatilityStrategy(),
        environment_closure_hash=environment_closure_hash,
        code_version_hash=code_version_hash,
        ledger=ledger,
    )

    return BaselineSuiteResult(runs=runs)
