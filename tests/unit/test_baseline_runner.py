"""Unit tests for canonical baseline runner and code-version provenance (Issue 109).

Verifies that canonical baseline executions bind drift_source_inventory_hash
as EvaluationRunIdentityV2.code_version_hash and ExperimentRun.code_hash,
ensuring whole-tree provenance is tracked without disturbing semantic
bundle hashes.
"""

# ruff: noqa: E402

import sys
from collections.abc import Mapping
from pathlib import Path

_SUPPORT = Path(__file__).resolve().parent
if str(_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_SUPPORT))

import test_evaluator_engine as eng

from drift.baselines import (
    B0CashStrategy,
    B1SingleBuyAndHoldStrategy,
    BaselineSuiteResult,
    build_canonical_run_identity,
    build_canonical_specification,
    make_bundle_dataset_reference,
    run_baseline_suite,
    run_canonical_baseline,
)
from drift.domain.evaluator_bundles import strategy_parameters_hash
from drift.domain.experiments import ExperimentRunStatus
from drift.domain.observation_query import drift_source_inventory_hash
from drift.evaluator.bundles import (
    build_evaluation_run_identity,
    build_evaluation_run_identity_v2,
)


def test_build_canonical_run_identity_defaults_to_inventory_hash() -> None:
    bundle = eng._bundle()
    admission = eng._admission(bundle)
    engine = eng._engine(bundle=bundle)
    params_hash = strategy_parameters_hash({"baseline": "B0", "mode": "cash"})

    identity = build_canonical_run_identity(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        strategy_parameters_hash=params_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
    )

    assert identity.schema_version == "2"
    assert identity.code_version_hash == drift_source_inventory_hash()


def test_build_canonical_run_identity_preserves_explicit_code_version_hash() -> None:
    bundle = eng._bundle()
    admission = eng._admission(bundle)
    engine = eng._engine(bundle=bundle)
    params_hash = strategy_parameters_hash({"baseline": "B0", "mode": "cash"})
    explicit_hash = "7" * 64

    identity = build_canonical_run_identity(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        strategy_parameters_hash=params_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=explicit_hash,
    )

    assert identity.code_version_hash == explicit_hash


def test_evaluator_bundle_builders_default_code_version_hash() -> None:
    bundle = eng._bundle()
    admission = eng._admission(bundle)
    engine = eng._engine(bundle=bundle)
    params_hash = strategy_parameters_hash({"baseline": "B0", "mode": "cash"})

    v1_identity = build_evaluation_run_identity(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        environment_closure_hash=eng.ENVIRONMENT_HASH,
    )
    assert v1_identity.code_version_hash == drift_source_inventory_hash()

    v2_identity = build_evaluation_run_identity_v2(
        strategy_hash=eng.STRATEGY_CODE_HASH,
        strategy_parameters_hash=params_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        environment_closure_hash=eng.ENVIRONMENT_HASH,
    )
    assert v2_identity.code_version_hash == drift_source_inventory_hash()


def test_make_bundle_dataset_reference() -> None:
    bundle = eng._bundle()
    dataset_ref = make_bundle_dataset_reference(bundle)

    assert dataset_ref.schema_version == "1"
    assert dataset_ref.content_hash == bundle.bundle_hash
    assert dataset_ref.manifest_reference.content_hash == bundle.bundle_hash


def test_build_canonical_specification() -> None:
    bundle = eng._bundle()
    strategy = B0CashStrategy()
    spec = build_canonical_specification(strategy=strategy, bundle=bundle)

    assert spec.strategy_reference == strategy.strategy_reference
    assert spec.parameters == strategy.strategy_parameters
    assert spec.dataset_reference.content_hash == bundle.bundle_hash


def test_run_canonical_baseline_cash() -> None:
    engine = eng._engine()
    strategy = B0CashStrategy()

    run = run_canonical_baseline(engine=engine, strategy=strategy)

    assert run.status == ExperimentRunStatus.COMPLETED
    assert run.code_hash == drift_source_inventory_hash()
    assert run.dataset_hash == engine.bundle.bundle_hash
    assert isinstance(run.metrics, Mapping)
    assert run.metrics["evaluated_session_count"] == len(
        engine.bundle.session_clock.sessions
    )
    assert run.metrics["committed_fill_count"] == 0


def test_run_canonical_baseline_single_buy_and_hold() -> None:
    engine = eng._engine()
    strategy = B1SingleBuyAndHoldStrategy(target_security_id=eng.SEC_A)

    run = run_canonical_baseline(engine=engine, strategy=strategy)

    assert run.status == ExperimentRunStatus.COMPLETED
    assert run.code_hash == drift_source_inventory_hash()
    assert run.dataset_hash == engine.bundle.bundle_hash


def test_run_canonical_baseline_explicit_code_version_hash() -> None:
    engine = eng._engine()
    strategy = B0CashStrategy()
    explicit_hash = "4" * 64

    run = run_canonical_baseline(
        engine=engine,
        strategy=strategy,
        code_version_hash=explicit_hash,
    )

    assert run.status == ExperimentRunStatus.COMPLETED
    assert run.code_hash == explicit_hash


def test_run_baseline_suite() -> None:
    engine = eng._engine()
    suite = run_baseline_suite(engine=engine, securities=(eng.SEC_A,))

    assert isinstance(suite, BaselineSuiteResult)
    expected_keys = {
        "b0_cash",
        f"b1_buy_and_hold_{eng.SEC_A}",
        "b2_equal_weight_buy_and_hold",
        "b3_monthly_equal_weight_rebalance",
        "b4_momentum",
        "b5_low_volatility",
    }
    assert set(suite.runs.keys()) == expected_keys

    for key, run in suite.runs.items():
        assert run.status == ExperimentRunStatus.COMPLETED, f"{key} failed"
        assert run.code_hash == drift_source_inventory_hash(), f"{key} code_hash"
        assert run.dataset_hash == engine.bundle.bundle_hash, f"{key} dataset_hash"
