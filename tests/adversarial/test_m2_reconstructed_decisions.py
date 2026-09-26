"""M2 adversarial acceptance: EXPLORATORY-only reconstructed decision evidence.

Issue 46 implements the issue 42 adjudication (ADR 0012 Option B): a
``scheduled_session_reconstruction`` bundle may drive strategy decisions in
the EXPLORATORY lane only, through ``ExploratoryStrategyDecisionContextV1``,
and never through the strong realized-session input. Every test here is an
attack on that boundary: an attempt to upgrade, relabel, or launder the weaker
grade into realized authority or promotion standing, or to let it leak time.

Habits carried over from the other M2 adversarial suites: each attack is paired
with a control that differs only in the property under attack, and every
``pytest.raises`` pattern names text unique to the guard under attack, so a
different guard firing first fails the test instead of satisfying it.
"""

# ruff: noqa: E402

import ast
import sys
import typing
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))

import pytest
from exploratory_decision_test_support import (
    JAN5,
    JAN6,
    SEC,
    DualLaneStrategy,
    ReconstructedTargetStrategy,
    bundle_of,
    cohort_of,
    early_close_sessions,
    merged_scheduled_clock,
    promotion_admission,
    reconstructed_engine,
    replay_of,
    run_engine,
    scheduled_bundle,
    scheduled_session_case,
    three_regular_sessions,
    utc_close,
)
from pydantic import TypeAdapter, ValidationError

from drift.domain.evaluator_clock import EvaluationSessionV1, evaluation_session_hash
from drift.domain.evaluator_exploratory_strategy import (
    RECONSTRUCTED_DECISION_LIMITATIONS,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    ExploratoryEvaluationResultV1,
)
from drift.domain.evaluator_strategy import (
    RuntimeStrategy,
    StrategyDecisionContextV1,
    StrategyDecisionViewV1,
)
from drift.domain.evaluator_trace import (
    EvaluationPhase,
    EvaluatorTraceEventV1,
    ExploratoryStrategyDecisionTraceEventV1,
    StrategyDecisionTraceEventV1,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    _resolve_reconstructed_lane,
)

NEW_YORK = ZoneInfo("America/New_York")
SRC = Path(__file__).resolve().parents[2] / "src" / "drift"
RIDING_REFUSED = (
    r"a bundle on a realized_session_authority clock cannot carry exploratory "
    r"reconstructions \(issue 72\)"
)


def _exploratory_events(
    artifacts: Any,
) -> list[ExploratoryStrategyDecisionTraceEventV1]:
    return [
        event
        for event in artifacts.trace.events
        if isinstance(event, ExploratoryStrategyDecisionTraceEventV1)
    ]


def _relabelled(session: EvaluationSessionV1) -> EvaluationSessionV1:
    """One scheduled session wearing realized authority, resealed consistently."""
    draft = EvaluationSessionV1.model_construct(
        **(dict(session) | {"authority": "realized"})
    )
    return EvaluationSessionV1.model_validate(
        dict(draft) | {"session_hash": evaluation_session_hash(draft)}
    )


# ==========================================================================
# Clock Authority: Scheduled Exploratory Early Close (design spec Table 22)
# ==========================================================================


def test_scheduled_exploratory_early_close_decides_only_after_the_13_00_close() -> None:
    """The matrix row, executed rather than recorded as uncovered.

    A 13:00 New York scheduled close under ``scheduled_session_reconstruction``
    decides at exactly that close, on EXPLORATORY-only reconstructed evidence,
    and the run completes. It is not INDETERMINATE.
    """
    cases = early_close_sessions()
    bundle = bundle_of(cases)
    strategy = ReconstructedTargetStrategy({JAN6: ((SEC, 10),)})

    artifacts = run_engine(reconstructed_engine(bundle), strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert bundle.session_clock.mode == "scheduled_session_reconstruction"
    _, early_session = cases[1]
    assert early_session.closed_at == utc_close(JAN6, "early_close")
    assert early_session.closed_at.astimezone(NEW_YORK).time() == time(13, 0)

    assert [context.session_key.local_date for context in strategy.seen] == [
        JAN5,
        JAN6,
    ]
    early = strategy.seen[-1]
    assert early.decision_cutoff == early_session.closed_at
    # Not the regular 16:00 close, and not any instant inside the session.
    assert early.decision_cutoff != utc_close(JAN6, "regular")
    assert early.decision_cutoff > early_session.opened_at
    assert early.decision_session.authority == "scheduled_reconstruction"

    events = _exploratory_events(artifacts)
    assert [event.decision_cutoff for event in events] == [
        utc_close(JAN5, "regular"),
        utc_close(JAN6, "early_close"),
    ]
    staged = events[-1]
    assert staged.outcome == "staged"
    assert [target.target_quantity for target in staged.staged_targets] == [10]
    early_observation, _ = cases[1]
    assert early_observation.reconstruction_hash in staged.reconstruction_hashes
    assert set(RECONSTRUCTED_DECISION_LIMITATIONS) <= set(
        staged.acknowledged_limitations
    )

    result = artifacts.result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    assert result.lane == "exploratory"
    assert result.is_promotion_grade_evidence is False


def test_an_early_close_decision_is_not_delayed_to_the_regular_close() -> None:
    """An intent answering 16:00 on a 13:00 day answers a close that never was."""

    class _RegularCloseAnswer(ReconstructedTargetStrategy):
        def decide_exploratory(
            self, context: ExploratoryStrategyDecisionContextV1
        ) -> Any:
            intent = super().decide_exploratory(context)
            return intent.model_copy(
                update={
                    "decision_time": utc_close(
                        context.session_key.local_date, "regular"
                    )
                }
            )

    strategy = _RegularCloseAnswer({})

    artifacts = run_engine(
        reconstructed_engine(bundle_of(early_close_sessions())), strategy
    )

    # The regular day answers its own close and stages; the early day refuses.
    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halted_session_index == 1
    events = _exploratory_events(artifacts)
    assert [event.outcome for event in events] == ["staged", "rejected"]
    assert events[-1].rejection_reason == (
        "decision intent decision_time must strictly match context.decision_cutoff"
    )


def test_evidence_generated_against_another_close_cannot_time_a_decision() -> None:
    """A bar reconstructed on a 16:00 calendar row cannot serve a 13:00 clock."""
    regular_jan6, _ = scheduled_session_case(JAN6)
    _, early_session = scheduled_session_case(JAN6, "early_close")
    jan5, jan5_session = scheduled_session_case(JAN5)
    assert regular_jan6.session_key == early_session.session_key
    bundle = scheduled_bundle((jan5, regular_jan6), (jan5_session, early_session))

    with pytest.raises(
        ValueError,
        match=r"does not bind the scheduled calendar row its clock session was",
    ):
        reconstructed_engine(bundle)

    # Control: the same dates with consistent calendar rows are admitted.
    reconstructed_engine(bundle_of(early_close_sessions()))


def test_an_exploratory_run_fabricates_no_realized_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No realized authority is minted, bound, or materialized on this path."""
    import drift.evaluator.bundles as bundles
    import drift.markets.normalization as normalization
    import drift.markets.session_binding as session_binding

    def _forbidden(*_: object, **__: object) -> Any:
        raise AssertionError("the exploratory decision path reached realized M1d")

    for module, name in (
        (normalization, "materialize_observation_decision"),
        (normalization, "materialize_observation_outcome"),
        (normalization, "bind_observation_session"),
        (session_binding, "bind_observation_session"),
        (bundles, "materialize_observation_decision"),
        (bundles, "materialize_observation_outcome"),
    ):
        monkeypatch.setattr(module, name, _forbidden)

    cases = early_close_sessions()
    bundle = bundle_of(cases)
    strategy = ReconstructedTargetStrategy({})

    artifacts = run_engine(reconstructed_engine(bundle), strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    clock_hashes = {session.session_hash for session in bundle.session_clock.sessions}
    starts = [
        event for event in artifacts.trace.events if event.kind == "session_start"
    ]
    assert len(starts) == len(cases)
    assert {event.session_hash for event in starts} == clock_hashes
    assert {session.authority for session in bundle.session_clock.sessions} == {
        "scheduled_reconstruction"
    }
    for context in strategy.seen:
        assert context.decision_session.authority == "scheduled_reconstruction"


def test_the_reconstructed_path_names_no_realized_authority() -> None:
    """Static proof for the dynamic one above: the path cannot reach realized M1d."""
    forbidden = {
        "RealizedSessionVersionV1",
        "bind_observation_session",
        "materialize_observation_decision",
        "materialize_observation_outcome",
    }
    path = SRC / "domain" / "evaluator_exploratory_strategy.py"
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name | ast.Attribute)
    }
    imported = {
        alias.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert imported, "the scan read no imports"
    assert not (names | imported) & forbidden


# ==========================================================================
# Epistemic Lanes: relabelling and upgrading attacks
# ==========================================================================


def test_an_exploratory_context_refuses_a_session_relabelled_as_realized() -> None:
    strategy = ReconstructedTargetStrategy({})
    run_engine(reconstructed_engine(bundle_of(early_close_sessions())), strategy)
    context = strategy.seen[-1]
    laundered = _relabelled(context.decision_session)
    assert laundered.authority == "realized"
    assert laundered.authority_record_hashes == (
        context.decision_session.authority_record_hashes
    )

    with pytest.raises(
        ValidationError,
        match=(
            "exploratory reconstructed decisions require scheduled "
            "reconstruction session authority"
        ),
    ):
        ExploratoryStrategyDecisionContextV1.model_validate(
            dict(context) | {"decision_session": laundered}
        )


def test_relabelling_the_clock_realized_turns_no_reconstruction_into_evidence() -> None:
    """The laundering attack on the clock gains nothing.

    Resealing every scheduled session as realized makes a self-consistent
    realized clock. A realized clock carries no reconstruction (issue 72), so
    the reconstructions cannot ride along at all. The relabelled clock alone
    buys nothing either: the strong lane reads only authentic views, so the
    run halts exactly as the realized lane always halts without them, and the
    exploratory method is never called.
    """
    cases = three_regular_sessions()
    relabelled = merged_scheduled_clock(
        tuple(_relabelled(session) for _, session in cases),
        limitations=(),
        mode="realized_session_authority",
    )
    with pytest.raises(ValueError, match=RIDING_REFUSED):
        scheduled_bundle(
            tuple(observation for observation, _ in cases),
            tuple(session for _, session in cases),
            clock=relabelled,
        )
    bundle = scheduled_bundle((), (), clock=relabelled)
    dual = DualLaneStrategy({})

    artifacts = run_engine(reconstructed_engine(bundle, with_cohort=False), dual)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 0
    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase is EvaluationPhase.POST_CLOSE_DECISION
    assert causes[0].cause.startswith(
        "no authorized decision evidence for the decision cutoff"
    )
    assert dual.seen == []
    assert dual.seen_realized == []
    assert _exploratory_events(artifacts) == []

    # Bringing the cohort along does not open the reconstructed lane either:
    # a realized clock can never be scoped by an exploratory cohort.
    with pytest.raises(
        ValueError,
        match=r"^an exploratory cohort scopes only a scheduled session reconstruction",
    ):
        reconstructed_engine(bundle)

    # Control: the honest scheduled clock over the same reconstructions runs.
    control = DualLaneStrategy({})
    honest = run_engine(reconstructed_engine(bundle_of(cases)), control)
    assert honest.result.classification is EvaluationClassification.COMPLETE
    assert len(control.seen) == 3
    assert control.seen_realized == []


def test_an_exploratory_context_never_validates_as_the_strong_context() -> None:
    strategy = ReconstructedTargetStrategy({})
    run_engine(reconstructed_engine(bundle_of(early_close_sessions())), strategy)
    context = strategy.seen[-1]

    with pytest.raises(ValidationError) as error:
        StrategyDecisionContextV1.model_validate(dict(context))

    reported = {
        (item["type"], item["loc"]) for item in error.value.errors(include_url=False)
    }
    assert ("missing", ("decision_views",)) in reported
    assert ("missing", ("admitted_universe",)) in reported
    for field in (
        "lane",
        "evidence_grade",
        "is_promotion_grade_evidence",
        "reconstructed_decision_views",
        "acknowledged_limitations",
    ):
        assert ("extra_forbidden", (field,)) in reported


def test_a_reconstructed_view_cannot_be_renamed_into_the_strong_view() -> None:
    strategy = ReconstructedTargetStrategy({})
    run_engine(reconstructed_engine(bundle_of(early_close_sessions())), strategy)
    view = strategy.seen[-1].reconstructed_decision_views[0]
    assert isinstance(view, ExploratoryReconstructedDecisionViewV1)

    with pytest.raises(ValidationError) as error:
        StrategyDecisionViewV1.model_validate(
            {"security_id": view.security_id, "views": view.observations}
        )

    errors = error.value.errors(include_url=False)
    assert errors, "the strong view must reject reconstructed members on shape"
    assert {(item["type"], item["loc"][:2]) for item in errors} == {
        ("model_type", ("views", index)) for index in range(len(view.observations))
    }


def test_an_exploratory_decision_event_cannot_be_relabelled_as_a_strong_one() -> None:
    artifacts = run_engine(
        reconstructed_engine(bundle_of(early_close_sessions())),
        ReconstructedTargetStrategy({}),
    )
    event = _exploratory_events(artifacts)[-1]
    adapter: TypeAdapter[EvaluatorTraceEventV1] = TypeAdapter(EvaluatorTraceEventV1)

    with pytest.raises(ValidationError) as error:
        adapter.validate_python(dict(event) | {"kind": "strategy_decision"})

    reported = {
        (item["type"], item["loc"][-1])
        for item in error.value.errors(include_url=False)
    }
    for field in (
        "evidence_grade",
        "is_promotion_grade_evidence",
        "reconstruction_hashes",
        "acknowledged_limitations",
    ):
        assert ("extra_forbidden", field) in reported
    assert not isinstance(event, StrategyDecisionTraceEventV1)


def test_the_strong_decision_input_is_not_a_union() -> None:
    """The canonical strong input keeps exactly its authentic member types."""
    assert (
        StrategyDecisionViewV1.model_fields["views"].annotation
        == tuple[DerivedObservationViewV1, ...]
    )
    assert (
        StrategyDecisionContextV1.model_fields["decision_views"].annotation
        == (tuple[StrategyDecisionViewV1, ...])
    )
    hints = typing.get_type_hints(RuntimeStrategy.decide)
    assert hints["context"] is StrategyDecisionContextV1

    strong = SRC / "domain" / "evaluator_strategy.py"
    imported = {
        node.module
        for node in ast.walk(ast.parse(strong.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "drift.domain.normalization" in imported, "the import scan read nothing"
    assert "drift.domain.evaluator_reconstruction" not in imported
    assert "drift.domain.evaluator_exploratory_strategy" not in imported


def test_the_exploratory_context_surface_is_pinned() -> None:
    """Widening the weaker boundary must be a deliberate, reviewed change too."""
    assert set(ExploratoryStrategyDecisionContextV1.model_fields) == {
        "schema_version",
        "lane",
        "evidence_grade",
        "is_promotion_grade_evidence",
        "session_key",
        "decision_session",
        "decision_cutoff",
        "cohort_hash",
        "admitted_cohort",
        "current_holdings",
        "current_cash",
        "portfolio_nav",
        "reconstructed_decision_views",
        "acknowledged_limitations",
    }


_WEAK_TYPES = (
    "ExploratoryStrategyDecisionContextV1",
    "ExploratoryReconstructedDecisionViewV1",
    "ExploratoryReconstructedSessionObservationV1",
    "ExploratoryStrategyDecisionTraceEventV1",
)
_STRONG_TYPES = (
    "StrategyDecisionContextV1",
    "StrategyDecisionViewV1",
    "DerivedObservationViewV1",
    "StrategyDecisionTraceEventV1",
    "RealizedSessionVersionV1",
    "Promotion",
)


def test_no_seam_converts_reconstructed_evidence_into_strong_or_promotion_types() -> (
    None
):
    """No function in Drift takes the weaker grade and returns a stronger one."""
    inspected = 0
    offending: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            inspected += 1
            arguments = ast.unparse(node.args)
            if not any(name in arguments for name in _WEAK_TYPES):
                continue
            returns = "" if node.returns is None else ast.unparse(node.returns)
            if any(name in returns for name in _STRONG_TYPES):
                offending.append(f"{path.relative_to(SRC)}:{node.name}")

    assert inspected >= 500, "the conversion-seam scan inspected nothing"
    assert offending == []


# ==========================================================================
# Promotion: the weaker type and path are refused structurally
# ==========================================================================

# Issue 79 ruling: the engine refuses every promotion admission first, before
# the reconstruction, cohort, and replay guards behind it. Those guards stay
# for the day issue 115 re-enables the lane; until then these attacks meet the
# lane refusal.
PROMOTION_LANE_DISABLED = (
    r"^the promotion lane is disabled \(issue 79 ruling\): engine construction "
    r"refuses"
)


def test_a_promotion_admission_cannot_evaluate_a_scheduled_reconstruction() -> None:
    bundle = bundle_of(early_close_sessions())
    admission = promotion_admission(bundle)
    assert admission.input_bundle_hash == bundle.bundle_hash

    with pytest.raises(PromotionLaneDisabledError, match=PROMOTION_LANE_DISABLED):
        reconstructed_engine(bundle, admission=admission, with_cohort=False)

    # Control: the exploratory admission of the same bundle is admitted.
    reconstructed_engine(bundle)


def test_a_promotion_admission_refuses_reconstructions_on_a_realized_clock() -> None:
    """Reconstructions riding a realized bundle are refused, not ignored.

    Issue 72 refuses the riding bundle itself, before an admission of either
    lane can bind it.
    """
    from test_evaluator_engine import _bundle

    realized = _bundle()
    observation, _ = scheduled_session_case(JAN5)
    assert observation.session_key in {
        session.session_key for session in realized.session_clock.sessions
    }
    from drift.evaluator.bundles import assemble_evaluation_input_bundle

    with pytest.raises(ValueError, match=RIDING_REFUSED):
        assemble_evaluation_input_bundle(
            evaluation_interval=realized.evaluation_interval,
            session_clock=realized.session_clock,
            security_identities=realized.security_identities,
            listing_identities=realized.listing_identities,
            structural_eligibilities=realized.structural_eligibilities,
            economic_outcomes=realized.economic_outcomes,
            authentic_decision_views=realized.authentic_decision_views,
            authentic_accounting_views=realized.authentic_accounting_views,
            exploratory_reconstructed_observations=(observation,),
        )

    # The same realized bundle without the reconstruction, admitted at
    # 19c15f8, is refused too: the lane is disabled, not only its weaker path.
    with pytest.raises(PromotionLaneDisabledError, match=PROMOTION_LANE_DISABLED):
        reconstructed_engine(
            realized, admission=promotion_admission(realized), with_cohort=False
        )

    # Control: the exploratory admission of that realized bundle is admitted.
    reconstructed_engine(realized, with_cohort=False)


def test_a_promotion_admission_cannot_carry_an_exploratory_cohort() -> None:
    from test_evaluator_engine import _bundle

    realized = _bundle()

    with pytest.raises(PromotionLaneDisabledError, match=PROMOTION_LANE_DISABLED):
        reconstructed_engine(realized, admission=promotion_admission(realized))


# The guards the lane refusal stands in front of, exercised directly (issue 120
# review, F-C). Construction never reaches them while the lane is disabled, so
# each is called as the engine will call it once issue 115 re-enables the lane.


def test_the_retained_guard_refuses_reconstructions_under_promotion() -> None:
    bundle = bundle_of(early_close_sessions())
    assert bundle.has_exploratory_reconstructions is True

    with pytest.raises(
        ValueError,
        match=(
            r"^a promotion admission cannot evaluate exploratory reconstructed "
            r"evidence$"
        ),
    ):
        _resolve_reconstructed_lane(
            bundle=bundle,
            admission=promotion_admission(bundle),
            cohort=None,
            replay=None,
        )


def test_the_retained_guard_refuses_a_cohort_under_promotion() -> None:
    from test_evaluator_engine import _bundle

    realized = _bundle()

    with pytest.raises(
        ValueError,
        match=r"^a promotion admission cannot evaluate an exploratory cohort$",
    ):
        _resolve_reconstructed_lane(
            bundle=realized,
            admission=promotion_admission(realized),
            cohort=cohort_of(),
            replay=None,
        )


def test_the_retained_guard_refuses_replay_evidence_under_promotion() -> None:
    from test_evaluator_engine import _bundle

    realized = _bundle()

    with pytest.raises(
        ValueError,
        match=(
            r"^a promotion admission cannot evaluate exploratory reconstruction "
            r"replay evidence$"
        ),
    ):
        _resolve_reconstructed_lane(
            bundle=realized,
            admission=promotion_admission(realized),
            cohort=None,
            replay=replay_of(()),
        )


def test_the_retained_guards_admit_a_clean_realized_promotion_bundle() -> None:
    """Control: with nothing weaker present, no reconstructed lane is resolved."""
    from test_evaluator_engine import _bundle

    realized = _bundle()

    assert (
        _resolve_reconstructed_lane(
            bundle=realized,
            admission=promotion_admission(realized),
            cohort=None,
            replay=None,
        )
        is None
    )


def test_the_promotion_gate_refuses_the_bundle_an_exploratory_run_completed() -> None:
    """The exact bundle the exploratory lane executes is inadmissible for promotion."""
    from test_m2_anti_laundering import _admitted_case, _rebind

    from drift.domain.replay_provenance import _build_bundle_provenance_proof
    from drift.evaluator.bundles import validate_promotion_admission

    cases = early_close_sessions()
    completed = run_engine(
        reconstructed_engine(bundle_of(cases)), ReconstructedTargetStrategy({})
    )
    assert completed.result.classification is EvaluationClassification.COMPLETE

    case = _admitted_case()
    snapshot_hash = case["bundle"].source_snapshot_hash
    poisoned = bundle_of(cases, source_snapshot_hash=snapshot_hash)
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=case["proof"].qualified_context_hash,
        source_snapshot_hash=snapshot_hash,
        bundle=poisoned,
    )
    attacked = _rebind(
        {**case, "bundle": poisoned, "proof": proof},
        input_bundle_hash=poisoned.bundle_hash,
        provenance_proof_hash=proof.proof_hash,
    )

    with pytest.raises(
        ValueError,
        match=r"^promotion evaluation cannot consume exploratory reconstructed inputs",
    ):
        validate_promotion_admission(**attacked)


def _paired_artifacts(lane: str) -> dict[str, Any]:
    """A genuine exploratory run's trace, paired with a result in ``lane``.

    Every binding the artifact checks is kept consistent, so the only
    difference between the two lanes is the lane itself.
    """
    bundle = bundle_of(three_regular_sessions())
    engine = reconstructed_engine(bundle)
    artifacts = run_engine(engine, ReconstructedTargetStrategy({}))
    assert _exploratory_events(artifacts)
    if lane == "exploratory":
        return {
            "result": artifacts.result,
            "trace": artifacts.trace,
            "final_state": artifacts.final_state,
        }
    return _as_promotion(engine, artifacts)


def _as_promotion(engine: Any, artifacts: Any) -> dict[str, Any]:
    """Relabel one exploratory run's result and final state into the promotion lane.

    The engine no longer builds a promotion result (issue 79 ruling), so any
    promotion pairing is assembled by hand, keeping every binding consistent.
    """
    from test_evaluator_engine import (
        CODE_VERSION_HASH,
        ENVIRONMENT_HASH,
        STRATEGY_REFERENCE,
    )

    from drift.domain.evaluator_portfolio import PortfolioStateV2
    from drift.domain.evaluator_results import (
        PromotionEvaluationResultV1,
        evaluation_result_hash,
    )
    from drift.evaluator.bundles import build_evaluation_run_identity

    bundle = engine.bundle
    promotion = promotion_admission(bundle)
    identity = build_evaluation_run_identity(
        strategy_hash=STRATEGY_REFERENCE.code_hash,
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=promotion,
        bundle=bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=CODE_VERSION_HASH,
        environment_closure_hash=ENVIRONMENT_HASH,
    )
    source = artifacts.result
    draft = PromotionEvaluationResultV1.model_construct(
        run_identity=identity,
        classification=source.classification,
        halted_session_index=source.halted_session_index,
        halt_reason=source.halt_reason,
        metrics=source.metrics,
        trace_hash=source.trace_hash,
        admission=promotion,
        result_hash="0" * 64,
    )
    result = PromotionEvaluationResultV1.model_validate(
        dict(draft) | {"result_hash": evaluation_result_hash(draft)}
    )
    state = artifacts.final_state
    mark = (
        None
        if state.mark is None
        else state.mark.model_copy(update={"lane": "promotion"})
    )
    final_state = PortfolioStateV2.model_validate(
        dict(state)
        | {
            "lane": "promotion",
            "admission_hash": promotion.admission_hash,
            "mark": mark,
        }
    )
    return {"result": result, "trace": artifacts.trace, "final_state": final_state}


def test_a_promotion_result_cannot_bind_a_trace_of_reconstructed_decisions() -> None:
    """The artifact types refuse the weaker grade under a promotion result.

    The shared trace union can name ``exploratory_strategy_decision``, so
    without this guard a hand-assembled promotion artifact would validate
    while its trace records decisions taken on reconstructed bars. The control
    is the identical trace under its own exploratory result.
    """
    from drift.domain.evaluator_results import EvaluationRunArtifactsV2

    control = EvaluationRunArtifactsV2.model_validate(_paired_artifacts("exploratory"))
    assert control.result.lane == "exploratory"
    assert _exploratory_events(control)

    with pytest.raises(
        ValidationError,
        match=(
            r"a promotion result cannot bind a trace of decisions taken on "
            r"EXPLORATORY reconstructed evidence: 3 exploratory_strategy_decision"
        ),
    ):
        EvaluationRunArtifactsV2.model_validate(_paired_artifacts("promotion"))


def test_a_realized_promotion_run_is_refused_and_its_pairing_still_binds() -> None:
    """The engine refuses the run; the artifact guard refuses only the grade.

    At 19c15f8 a real engine run under a promotion admission over a realized
    bundle completed with a promotion result. The issue 79 ruling disables
    that lane, so the engine refuses it. The control for the guard above then
    needs a hand-assembled pairing: a promotion result over a realized trace,
    whose decisions are ``strategy_decision``, still validates as an
    artifact, including after a JSON round trip.
    """
    from test_evaluator_engine import (
        BOOK_CODE,
        BOOK_NAMESPACE,
        ROLE_RECORDS,
        FixedTargetStrategy,
        _bundle,
        _cost_model,
        _engine,
        _protocol,
    )

    from drift.domain.evaluator_results import EvaluationRunArtifactsV2
    from drift.evaluator.engine import SessionEvaluatorEngine, SessionEvaluatorEvidence

    realized = _bundle()
    with pytest.raises(PromotionLaneDisabledError, match=PROMOTION_LANE_DISABLED):
        SessionEvaluatorEngine(
            bundle=realized,
            admission=promotion_admission(realized),
            protocol=_protocol(),
            cost_model=_cost_model(),
            evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )

    engine = _engine(bundle=realized)
    run = run_engine(engine, FixedTargetStrategy({}))
    kinds = [event.kind for event in run.trace.events]
    assert run.result.classification is EvaluationClassification.COMPLETE
    assert kinds.count("strategy_decision") >= 1
    assert "exploratory_strategy_decision" not in kinds

    artifacts = EvaluationRunArtifactsV2.model_validate(_as_promotion(engine, run))
    assert artifacts.result.lane == "promotion"
    rebound = EvaluationRunArtifactsV2.model_validate_json(artifacts.model_dump_json())
    assert rebound.result.lane == "promotion"
    assert rebound.trace.trace_hash == run.trace.trace_hash


# ==========================================================================
# Authorization: nothing here reaches promotion, brokers, or capital
# ==========================================================================


def test_the_reconstructed_path_authorizes_no_live_operation() -> None:
    forbidden_roots = {
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
    }
    paths = (
        SRC / "domain" / "evaluator_exploratory_strategy.py",
        SRC / "evaluator" / "engine.py",
        SRC / "evaluator" / "experiment_runner.py",
    )
    imported: set[str] = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
    assert imported, "the import scan read nothing"
    offending = sorted(
        name
        for name in imported
        if name.split(".")[0] in forbidden_roots
        or "adapters" in name.split(".")
        or "broker" in name.lower()
        or "alpaca" in name.lower()
        or "robinhood" in name.lower()
    )
    assert offending == []

    artifacts = run_engine(
        reconstructed_engine(bundle_of(early_close_sessions())),
        ReconstructedTargetStrategy({}),
    )
    assert artifacts.result.is_promotion_grade_evidence is False
    assert artifacts.result.lane == "exploratory"
    assert (
        artifacts.final_state.admission_hash
        == artifacts.result.admission.admission_hash
    )
