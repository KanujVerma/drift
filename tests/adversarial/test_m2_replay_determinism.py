"""M2 adversarial acceptance: closed-world replay determinism.

A deterministic evaluator is only as good as the things it refuses to depend
on. The attacks here try to make one evaluation disagree with its own replay
by changing something that is not evidence: the experiment identity, the wall
clock, the ambient decimal context, the order members were handed to the
bundle assembler, or the identity of the engine object itself.

Every equality assertion is paired with a control that changes one genuine
input and requires the hashes to move. Without that pairing an equality test
proves only that two constants are equal.
"""

# ruff: noqa: E402

import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_UP, Context, Decimal, localcontext
from pathlib import Path
from typing import Any
from uuid import uuid7

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))
_INTEGRATION_SUPPORT = Path(__file__).resolve().parents[1] / "integration"
if str(_INTEGRATION_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_SUPPORT))

import pytest
import test_evaluator_engine as eng
import test_evaluator_experiment_run as run_support
from pydantic import ValidationError

from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV1,
)
from drift.domain.evaluator_strategy import (
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.evaluator_trace import (
    EvaluationTraceLogV1,
    evaluation_trace_log_hash,
    seal_evaluation_trace_log,
)
from drift.domain.experiments import ExperimentRunStatus
from drift.domain.strategies import StrategyReference
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_run_identity,
)
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.serialization.canonical import canonical_json, content_hash

LATE_START = datetime(2031, 12, 31, 23, 59, tzinfo=UTC)
LATE_END = datetime(2032, 1, 1, 0, 30, tzinfo=UTC)


def _artifacts() -> EvaluationRunArtifactsV1:
    return eng._run(eng._engine())


def _identity_of(engine: Any) -> Any:
    return eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )


# ==========================================================================
# Replay across experiment runs
# ==========================================================================


def test_two_experiment_runs_over_one_evaluation_are_bitwise_identical() -> None:
    """Operational metadata must not reach the evaluation in any form."""
    engine = eng._engine()
    first = execute_experiment_run(
        run_support._specification(), run_support._context(engine)
    )
    second = execute_experiment_run(
        run_support._specification(),
        run_support._context(
            engine,
            run_id=uuid7(),
            started_at=LATE_START,
            completed_at=LATE_END,
        ),
    )

    assert first.run_id != second.run_id
    assert first.started_at != second.started_at
    assert first.experiment_id != second.experiment_id
    first_digests = {
        reference.kind: reference.content_hash
        for reference in first.artifact_references
    }
    second_digests = {
        reference.kind: reference.content_hash
        for reference in second.artifact_references
    }
    assert first_digests == second_digests
    assert first.metrics == second.metrics


def test_the_result_and_trace_serialize_to_identical_bytes_on_replay() -> None:
    first = _artifacts()
    second = _artifacts()

    assert canonical_json(first.result) == canonical_json(second.result)
    assert canonical_json(first.trace) == canonical_json(second.trace)
    assert first.result.result_hash == second.result.result_hash
    assert first.trace.trace_hash == second.trace.trace_hash


def test_a_changed_price_changes_both_content_addresses() -> None:
    """Control: the determinism assertions above are not comparing constants."""
    baseline = _artifacts()
    shifted_views = tuple(
        eng._accounting_view(eng.SEC_A, day, close_price="130.00")
        if day == eng.DAY_3
        else eng._accounting_view(eng.SEC_A, day)
        for day in eng.DAYS
    )
    shifted = eng._run(eng._engine(bundle=eng._bundle(accounting_views=shifted_views)))

    assert shifted.result.result_hash != baseline.result.result_hash
    assert shifted.trace.trace_hash != baseline.trace.trace_hash


def test_the_same_engine_object_replays_itself_identically() -> None:
    """The engine must hold no state that survives one run into the next."""
    engine = eng._engine()
    identity = _identity_of(engine)

    first = engine.run(strategy=eng._buy_ten(), run_identity=identity)
    second = engine.run(strategy=eng._buy_ten(), run_identity=identity)

    assert first.result.result_hash == second.result.result_hash
    assert first.trace.trace_hash == second.trace.trace_hash
    assert content_hash(first.final_state) == content_hash(second.final_state)


def test_two_independently_built_engines_agree_exactly() -> None:
    first = _artifacts()
    second = _artifacts()

    assert content_hash(first.final_state) == content_hash(second.final_state)
    assert first.result.run_identity == second.result.run_identity


# ==========================================================================
# Determinism against the ambient process
# ==========================================================================


def test_a_perturbed_ambient_decimal_context_cannot_move_a_result() -> None:
    """Arithmetic is pinned, so an unrelated dependency cannot rewrite a book."""
    baseline = _artifacts()

    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        perturbed = _artifacts()

    assert perturbed.result.result_hash == baseline.result.result_hash
    assert perturbed.trace.trace_hash == baseline.trace.trace_hash
    assert perturbed.final_state.net_asset_value == baseline.final_state.net_asset_value


def test_a_perturbed_ambient_context_cannot_move_a_split_adjusted_book() -> None:
    """A split folds rationals into share counts, so it is the harder case."""
    engine, _ = eng._split_engine()
    baseline = eng._run(engine)

    with localcontext(Context(prec=2, rounding=ROUND_UP)):
        split_engine, _ = eng._split_engine()
        perturbed = eng._run(split_engine)

    assert perturbed.result.result_hash == baseline.result.result_hash
    assert perturbed.final_state.holdings[0].quantity == 20


def test_bundle_member_order_cannot_change_the_evaluation() -> None:
    """Canonical member ordering must absorb the order a caller supplies."""
    forward = assemble_evaluation_input_bundle(
        evaluation_interval=eng._interval(),
        session_clock=eng._clock(),
        security_identities=eng.SECURITIES,
        listing_identities=eng.LISTINGS,
        structural_eligibilities=(eng._eligibility(eng.SEC_A, eng.LISTING_A),),
        authentic_decision_views=tuple(
            eng._decision_view(eng.SEC_A, day) for day in eng.DAYS[1:]
        ),
        authentic_accounting_views=tuple(
            eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS
        ),
    )
    reversed_bundle = assemble_evaluation_input_bundle(
        evaluation_interval=eng._interval(),
        session_clock=eng._clock(),
        security_identities=tuple(reversed(eng.SECURITIES)),
        listing_identities=tuple(reversed(eng.LISTINGS)),
        structural_eligibilities=(eng._eligibility(eng.SEC_A, eng.LISTING_A),),
        authentic_decision_views=tuple(
            eng._decision_view(eng.SEC_A, day) for day in reversed(eng.DAYS[1:])
        ),
        authentic_accounting_views=tuple(
            eng._accounting_view(eng.SEC_A, day) for day in reversed(eng.DAYS)
        ),
    )

    assert forward.bundle_hash == reversed_bundle.bundle_hash
    assert (
        eng._run(eng._engine(bundle=forward)).result.result_hash
        == eng._run(eng._engine(bundle=reversed_bundle)).result.result_hash
    )


def test_the_result_artifact_carries_no_operational_metadata() -> None:
    """No run identifier and no completion instant may enter the preimage."""
    result = _artifacts().result
    annotations = {
        name: str(field.annotation) for name, field in type(result).model_fields.items()
    }
    for name, annotation in annotations.items():
        assert "UUID" not in annotation, name
        assert "datetime" not in annotation, name
    assert "run_id" not in annotations
    assert "completed_at" not in annotations


# ==========================================================================
# Run identity depends on every genuine input and on nothing else
# ==========================================================================


def test_a_trading_reconstructed_run_is_bitwise_identical_across_runs() -> None:
    """The reconstructed lane (#46, #54) replays bitwise too, while it trades.

    Two ExperimentRuns with different ids and clocks over one reconstructed
    evaluation that buys and marks on exploratory reconstructed prices must
    bind the same result and trace content addresses.
    """
    import test_exploratory_reconstructed_experiment_run as reconstructed_runs
    from exploratory_decision_test_support import (
        JAN5,
        JAN6,
        SEC,
        ReconstructedTargetStrategy,
        bundle_of,
        reconstructed_engine,
        three_regular_sessions,
    )

    engine = reconstructed_engine(bundle_of(three_regular_sessions()))
    targets = {JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)}
    specification = run_support._specification(dataset_hash=engine.bundle.bundle_hash)

    first = execute_experiment_run(
        specification,
        reconstructed_runs._context(engine, ReconstructedTargetStrategy(targets)),
    )
    second = execute_experiment_run(
        specification,
        reconstructed_runs._context(
            engine,
            ReconstructedTargetStrategy(targets),
            started_at=LATE_START,
            completed_at=LATE_END,
        ),
    )

    for run in (first, second):
        assert run.status is ExperimentRunStatus.COMPLETED
        assert run_support._metric(run, "committed_fill_count") == 1
        assert run_support._metric(run, "lane") == "exploratory"
    assert first.run_id != second.run_id
    assert {ref.kind: ref.content_hash for ref in first.artifact_references} == {
        ref.kind: ref.content_hash for ref in second.artifact_references
    }


def test_every_run_identity_input_moves_the_identity_hash() -> None:
    engine = eng._engine()
    base = _identity_of(engine)
    variants = {
        "strategy": eng._run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
            strategy_hash="f" * 64,
        ),
        "protocol": eng._run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=eng._protocol(warmup=1),
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        "cost_model": eng._run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=eng._cost_model(model_id="other-cost-v1"),
            evidence_hash=engine.evaluator_evidence_hash,
        ),
        "code_version": build_evaluation_run_identity(
            strategy_hash=eng.STRATEGY_CODE_HASH,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash="9" * 64,
            environment_closure_hash=eng.ENVIRONMENT_HASH,
        ),
        "environment": build_evaluation_run_identity(
            strategy_hash=eng.STRATEGY_CODE_HASH,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=eng.CODE_VERSION_HASH,
            environment_closure_hash="8" * 64,
        ),
    }
    other_bundle = eng._bundle(days=eng.DAYS[:3])
    variants["bundle"] = eng._run_identity(
        admission=eng._admission(other_bundle),
        bundle=other_bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )
    variants["evaluator_evidence"] = eng._run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash="7" * 64,
    )

    assert len(variants) == 7
    digests = {base.run_identity_hash}
    for label, identity in variants.items():
        assert identity.run_identity_hash != base.run_identity_hash, label
        digests.add(identity.run_identity_hash)
    assert len(digests) == 8


def test_a_run_identity_cannot_bind_a_bundle_its_admission_never_admitted() -> None:
    engine = eng._engine()
    other = eng._bundle(days=eng.DAYS[:3])

    with pytest.raises(
        ValueError, match=r"^run identity requires the admission to admit this exact"
    ):
        build_evaluation_run_identity(
            strategy_hash=eng.STRATEGY_CODE_HASH,
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=other,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=eng.CODE_VERSION_HASH,
            environment_closure_hash=eng.ENVIRONMENT_HASH,
        )


# ==========================================================================
# Overnight split target scaling
# ==========================================================================


def test_an_overnight_split_preserves_the_intended_staged_delta() -> None:
    engine, _ = eng._split_engine()

    artifacts = eng._run(engine)

    applied = [
        event
        for event in artifacts.trace.events
        if event.kind == "corporate_action_applied"
    ]
    assert len(applied) == 1
    event = applied[0]
    assert event.session_index == 3
    assert [
        (target.security_id, target.target_quantity)
        for target in event.staged_targets_before
    ] == [(eng.SEC_A, 10)]
    assert [
        (target.security_id, target.target_quantity)
        for target in event.staged_targets_after
    ] == [(eng.SEC_A, 20)]
    # The scaled target exactly matches the scaled holding, so the intended
    # delta of zero survives the split and no second fill is committed.
    fills = [item for item in artifacts.trace.events if item.kind == "fill"]
    assert [item.session_index for item in fills] == [2]
    assert artifacts.final_state.holdings[0].quantity == 20


def test_a_split_scaled_run_replays_to_the_same_content_address() -> None:
    first, _ = eng._split_engine()
    second, _ = eng._split_engine()

    assert eng._run(first).result.result_hash == eng._run(second).result.result_hash


# ==========================================================================
# Trace integrity under replay
# ==========================================================================


def test_the_trace_sequence_is_contiguous_and_session_ordered() -> None:
    trace = _artifacts().trace

    assert [event.sequence for event in trace.events] == list(range(len(trace.events)))
    opened = [
        event.session_index for event in trace.events if event.kind == "session_start"
    ]
    assert opened == sorted(opened)
    assert opened == list(range(len(opened)))


def test_a_reordered_trace_cannot_be_resealed() -> None:
    trace = _artifacts().trace
    swapped = (trace.events[1], trace.events[0], *trace.events[2:])

    with pytest.raises(
        ValidationError, match=r"trace event sequence must be contiguous from zero"
    ):
        seal_evaluation_trace_log(swapped)


def test_a_trace_cannot_be_rehashed_around_a_dropped_event() -> None:
    trace = _artifacts().trace
    trimmed = trace.events[:-1]
    draft = EvaluationTraceLogV1.model_construct(
        schema_version="1", events=trimmed, trace_hash="0" * 64
    )
    resealed = EvaluationTraceLogV1.model_validate(
        dict(draft) | {"trace_hash": evaluation_trace_log_hash(draft)}
    )

    assert resealed.trace_hash != trace.trace_hash
    result = _artifacts().result
    with pytest.raises(
        ValidationError, match=r"result must bind the trace it is paired with"
    ):
        EvaluationRunArtifactsV1(
            result=result, trace=resealed, final_state=_artifacts().final_state
        )


# ==========================================================================
# A broken run is never laundered into a classification
# ==========================================================================


class _ExplodingStrategy:
    """A strategy whose defect must never become a scientific answer."""

    @property
    def strategy_reference(self) -> StrategyReference:
        return eng.STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        raise RuntimeError("strategy defect")


def test_a_strategy_defect_fails_the_experiment_run_and_binds_no_artifacts() -> None:
    engine = eng._engine()
    context = run_support._context(engine)
    broken = ExperimentRunnerContext(
        **(dict(vars(context)) | {"strategy": _ExplodingStrategy()})
    )

    run = execute_experiment_run(run_support._specification(), broken)

    assert run.status is ExperimentRunStatus.FAILED
    assert run.artifact_references == ()
    assert run.error_details is not None
    assert "strategy defect" in run.error_details


def test_a_halted_evaluation_is_still_a_completed_experiment_with_artifacts() -> None:
    bundle = eng._bundle(
        accounting_views=tuple(
            eng._accounting_view(eng.SEC_A, day) for day in eng.DAYS[:2]
        )
    )
    engine = eng._engine(bundle=bundle)

    run = execute_experiment_run(
        run_support._specification(dataset_hash=engine.bundle.bundle_hash),
        run_support._context(engine),
    )

    assert run.status is ExperimentRunStatus.COMPLETED
    assert len(run.artifact_references) == 2
    metrics = run.metrics
    assert isinstance(metrics, Mapping)
    assert metrics["classification"] == EvaluationClassification.INDETERMINATE.value
    assert metrics["is_promotion_grade_evidence"] is False


def test_a_specification_naming_another_strategy_is_refused() -> None:
    engine = eng._engine()

    with pytest.raises(
        ValueError, match=r"^the specification strategy does not match the evaluated"
    ):
        execute_experiment_run(
            run_support._specification(code_hash="7" * 64),
            run_support._context(engine),
        )


def test_the_exact_terminal_book_is_reproduced_across_replays() -> None:
    first = _artifacts()
    second = _artifacts()

    assert first.result.metrics == second.result.metrics
    assert first.result.metrics.ending_net_asset_value == Decimal("10200.00")
    assert first.final_state.cash_balance == second.final_state.cash_balance
