"""M2 adversarial acceptance: epistemic lanes, gatekeeper, and replay integrity.

This file attacks the ADR 0012 Absolute Non-Upgrade Rule from every direction
the type system, the hash graph, and the promotion gate expose. The claim it
has to establish is the strongest one in the milestone: no exploratory result,
and no evidence that only looks promotion-grade, can satisfy promotion
validation.

The last section carries the attack that reopened issue 31: a hand-built
``QualifiedReplayContextV1`` naming a foreign snapshot, valid under its own
contract because proving a containment witness needs a snapshot the model never
sees. It used to be admitted. The gate now takes the qualified context and the
snapshot and re-audits the witness, so the same construction is refused, and
each of those tests keeps its original attack so the coverage is unchanged and
only the verdict moved.

The final section carries the issue 79 ruling (option 1). The engine never ran
the gate, so a hand-made promotion admission produced promotion-grade results.
The promotion lane is now disabled: the engine and the experiment runner refuse
every ``PromotionEvaluationAdmissionV1``, a gate-valid one included, while the
gate tests above keep exercising the gate directly.
"""

# ruff: noqa: E402

import ast
import inspect
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

_UNIT_SUPPORT = Path(__file__).resolve().parents[1] / "unit"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))
_INTEGRATION_SUPPORT = Path(__file__).resolve().parents[1] / "integration"
if str(_INTEGRATION_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_INTEGRATION_SUPPORT))

import pytest
import test_replay_provenance as rp
from observation_test_support import NormalizationHarness
from pydantic import ValidationError
from replay_provenance_test_support import (
    admission_profile_hashes,
    qualified_snapshot,
    snapshot_over,
)
from test_evaluator_admission_gatekeeper import (
    copy_constructed,
    make_dimension_result,
    make_test_fixture,
    rebind_admission,
)
from test_evaluator_bundles import (
    _exploratory_admission,
    _harness,
    _realized_bundle,
    _scheduled_bundle,
    normalization_realized_clock,
    normalization_scheduled_clock,
    normalization_session_queries,
    resealed_clock,
    with_session_clock,
)
from test_evaluator_reconstruction import build_from_harness

from drift.domain.assertions import ResolutionMode
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV1,
    evaluation_input_bundle_hash,
    evaluation_run_identity_hash,
)
from drift.domain.evaluator_clock import SessionClockV1, session_clock_hash
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ALPACA_LIMITATION_TRUNCATED_CA,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_portfolio import (
    LANE_ADMISSIBLE_MARK_GRADES,
    LaneAdmissibilityError,
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioMarkV1,
    PortfolioStateV1,
)
from drift.domain.evaluator_reconstruction import (
    ExploratoryReconstructedSessionObservationV1,
)
from drift.domain.evaluator_results import (
    LANE_GRANTED_MARK_GRADE,
    EvaluationRunArtifactsV1,
    ExploratoryEvaluationResultV1,
    PromotionEvaluationResultV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    ObservationDecisionReferenceV1,
    ObservationOutcomeReferenceV1,
)
from drift.domain.qualification import (
    ConsumerPurpose,
    M1eCompletionKind,
    QualificationDimension,
    QualificationStatus,
    qualification_profile_hash,
)
from drift.domain.replay_provenance import (
    BundleProvenanceProofV1,
    QualifiedReplayContextV1,
    SnapshotBindingEntryV1,
    _build_bundle_provenance_proof,
    bind_context_identity_to_snapshot,
    bundle_component_hashes,
    bundle_provenance_proof_hash,
    context_supplied_artifact_hashes,
    qualified_replay_context_hash,
    snapshot_binding_witness_hash,
    verify_snapshot_binding,
)
from drift.domain.source_snapshots import (
    RealSourceSnapshotV1,
    real_source_snapshot_hash,
)
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_input_bundle,
    derive_replay_context_identity,
    mint_bundle_provenance_proof,
    qualify_replay_context,
    validate_exploratory_admission,
    validate_promotion_admission,
    verify_evaluation_input_bundle,
)
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
)
from drift.evaluator.experiment_runner import execute_experiment_run
from drift.evaluator.portfolio import (
    PortfolioAccountingKernel,
    initial_portfolio_state,
)
from drift.ledger.sqlite import SQLiteLedger
from drift.markets.normalization import (
    materialize_observation_decision,
    materialize_observation_outcome,
)
from drift.serialization.canonical import content_hash

H = {character: character * 64 for character in "0123456789abcdef"}


@cache
def _cached_decision_case() -> tuple[Any, Any, Any]:
    """One materialized M1d decision corpus, shared by every attack here."""
    return rp._decision_case()


@cache
def _cached_exploratory_result() -> ExploratoryEvaluationResultV1:
    import test_evaluator_engine as eng

    result = eng._run(eng._engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    return result


# ==========================================================================
# Lane-bound result artifacts: no relabelling, no conversion
# ==========================================================================


def _exploratory_result() -> ExploratoryEvaluationResultV1:
    return _cached_exploratory_result()


def test_a_promotion_result_cannot_carry_an_exploratory_admission() -> None:
    result = _exploratory_result()

    with pytest.raises(ValidationError) as error:
        PromotionEvaluationResultV1.model_validate(
            dict(result) | {"lane": "promotion", "is_promotion_grade_evidence": True}
        )

    assert [
        (item["type"], item["loc"]) for item in error.value.errors(include_url=False)
    ] == [("model_type", ("admission",))]


def test_an_exploratory_result_cannot_carry_a_promotion_admission() -> None:
    result = _exploratory_result()
    promotion_admission = make_test_fixture()["admission"]

    with pytest.raises(ValidationError) as error:
        ExploratoryEvaluationResultV1.model_validate(
            dict(result) | {"admission": promotion_admission}
        )

    # The admission field is refused on its type, not merely on a hash. A
    # hash-only rejection would leave the two lanes structurally swappable.
    assert [
        (item["type"], item["loc"]) for item in error.value.errors(include_url=False)
    ] == [("model_type", ("admission",))]


def test_the_promotion_grade_flag_cannot_be_flipped_on_an_exploratory_result() -> None:
    result = _exploratory_result()
    assert result.is_promotion_grade_evidence is False

    with pytest.raises(ValidationError) as error:
        ExploratoryEvaluationResultV1.model_validate(
            dict(result) | {"is_promotion_grade_evidence": True}
        )

    assert [item["loc"] for item in error.value.errors(include_url=False)] == [
        ("is_promotion_grade_evidence",)
    ]


def test_the_lane_literal_cannot_be_flipped_on_an_exploratory_result() -> None:
    result = _exploratory_result()

    with pytest.raises(ValidationError) as error:
        ExploratoryEvaluationResultV1.model_validate(
            dict(result) | {"lane": "promotion"}
        )

    assert ("lane",) in {item["loc"] for item in error.value.errors(include_url=False)}


def _evaluator_sources() -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[2] / "src" / "drift"
    return tuple(
        sorted(
            (
                *(root / "evaluator").glob("*.py"),
                *(root / "domain").glob("evaluator_*.py"),
                root / "domain" / "replay_provenance.py",
            )
        )
    )


def test_no_conversion_seam_exists_between_the_two_result_artifacts() -> None:
    """No helper anywhere in M2 turns exploratory evidence into a promotion claim."""
    inspected = 0
    offending: list[str] = []
    for path in _evaluator_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            inspected += 1
            returns = "" if node.returns is None else ast.unparse(node.returns)
            if "Promotion" not in returns:
                continue
            arguments = ast.unparse(node.args)
            if "Exploratory" in arguments:
                offending.append(f"{path.name}:{node.name}")

    assert inspected >= 100, "the conversion-seam scan inspected nothing"
    assert offending == []

    # Neither result model exposes any public callable beyond its own
    # validator, so there is no method seam through which a lane could change.
    for model in (ExploratoryEvaluationResultV1, PromotionEvaluationResultV1):
        callables = {
            name
            for name, member in vars(model).items()
            if callable(member)
            and not name.startswith("_")
            and not name.startswith("model_")
        }
        assert callables == {"validate_result"}


def test_the_promotion_result_surface_grants_no_strategy_approval() -> None:
    """Promotion grade is a statement about evidence, never about a strategy."""
    assert set(PromotionEvaluationResultV1.model_fields) == {
        "schema_version",
        "lane",
        "is_promotion_grade_evidence",
        "admission",
        "run_identity",
        "classification",
        "halted_session_index",
        "halt_reason",
        "metrics",
        "trace_hash",
        "result_hash",
    }


def test_two_lanes_over_one_input_produce_two_different_result_identities() -> None:
    """No identical rerun can turn exploratory output into promotion evidence.

    The admission hash is inside the run identity preimage, which is inside
    the result preimage. Two lanes over one input therefore cannot collide on
    a content address, whatever else they share.
    """
    result = _exploratory_result()
    identity = result.run_identity
    promotion_admission = make_test_fixture()["admission"]
    assert identity.admission_hash != promotion_admission.admission_hash

    relabelled = EvaluationRunIdentityV1.model_construct(
        **(dict(identity) | {"admission_hash": promotion_admission.admission_hash})
    )
    assert evaluation_run_identity_hash(relabelled) != identity.run_identity_hash

    resealed = EvaluationRunIdentityV1.model_validate(
        dict(relabelled)
        | {"run_identity_hash": evaluation_run_identity_hash(relabelled)}
    )
    assert resealed.run_identity_hash != identity.run_identity_hash


# ==========================================================================
# Lane-bound valuation: an exploratory mark can never reach a promotion book
# ==========================================================================


def test_the_lane_admissibility_table_is_pinned() -> None:
    assert LANE_ADMISSIBLE_MARK_GRADES == {
        "exploratory": frozenset({"promotion_grade", "exploratory"}),
        "promotion": frozenset({"promotion_grade"}),
    }


def test_a_promotion_book_refuses_an_exploratory_mark() -> None:
    import test_evaluator_corporate_actions as ca

    promotion_admission = make_test_fixture()["admission"]
    opening = initial_portfolio_state(
        session_key=ca._key(),
        initial_cash=Decimal("1000"),
        admission=promotion_admission,
    )
    state = opening.model_copy(
        update={"holdings": (ca._holding(quantity=10, basis="100"),)}
    )
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)

    with pytest.raises(
        LaneAdmissibilityError,
        match=r"^promotion lane refuses exploratory mark evidence",
    ):
        kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))

    # Control: the identical book accepts a promotion-grade mark.
    kernel.mark_close(
        (
            MarkPriceV1(
                security_id=ca.SEC_A,
                close_price=Decimal("10"),
                evidence=MarkEvidenceV1(grade="promotion_grade", evidence_hash=H["d"]),
            ),
        )
    )
    assert kernel.state.holdings_market_value == Decimal("100")


def test_a_promotion_mark_cannot_be_assembled_from_exploratory_prices() -> None:
    import test_evaluator_corporate_actions as ca

    with pytest.raises(
        ValidationError,
        match=r"promotion lane refuses exploratory mark evidence",
    ):
        PortfolioMarkV1(
            session_key=ca._key(),
            lane="promotion",
            prices=(ca._mark_price(ca.SEC_A, "10"),),
        )


def test_an_exploratory_book_cannot_be_relabelled_into_the_promotion_lane() -> None:
    import test_evaluator_corporate_actions as ca

    state = ca._state(holdings=(ca._holding(quantity=10, basis="100"),), cash="1000")
    kernel = PortfolioAccountingKernel(state, session_clock=ca.CLOCK)
    kernel.mark_close((ca._mark_price(ca.SEC_A, "10"),))
    marked = kernel.state
    assert marked.lane == "exploratory"

    with pytest.raises(
        ValidationError,
        match=r"mark was admitted under the exploratory lane",
    ):
        marked.model_copy(update={"lane": "promotion"})


def test_an_indeterminate_mark_is_refused_in_every_lane() -> None:
    import test_evaluator_corporate_actions as ca

    unbound = MarkPriceV1(
        security_id=ca.SEC_A,
        close_price=Decimal("10"),
        evidence=MarkEvidenceV1(grade="indeterminate", reason="no bound evidence"),
    )
    for lane in ("exploratory", "promotion"):
        with pytest.raises(
            ValidationError, match=rf"{lane} lane refuses indeterminate mark evidence"
        ):
            PortfolioMarkV1(session_key=ca._key(), lane=lane, prices=(unbound,))


def test_an_exploratory_run_grades_every_mark_from_its_own_admission() -> None:
    import test_evaluator_engine as eng

    artifacts = eng._run(eng._engine())
    mark = artifacts.final_state.mark
    assert mark is not None
    assert mark.lane == "exploratory"
    assert all(price.evidence.grade == "exploratory" for price in mark.prices)
    marked = [
        state
        for state in artifacts.result.metrics.equity_series
        if state.holdings_market_value > Decimal("0")
    ]
    assert marked, "the run must actually mark a position"
    assert artifacts.result.is_promotion_grade_evidence is False


def test_the_granted_mark_grade_table_is_the_engine_table() -> None:
    """The artifact type pairs a book with the grade its lane's run grants."""
    from drift.evaluator.engine import LANE_MARK_GRADE

    assert LANE_GRANTED_MARK_GRADE == LANE_MARK_GRADE
    assert LANE_GRANTED_MARK_GRADE == {
        "exploratory": "exploratory",
        "promotion": "promotion_grade",
    }


def _genuine_pair_json(*, trade: bool = True) -> dict[str, Any]:
    """One genuine exploratory run's artifacts as canonical JSON data."""
    import test_evaluator_engine as eng

    strategy = eng._buy_ten() if trade else eng.FixedTargetStrategy({})
    loaded: dict[str, Any] = json.loads(
        eng._run(eng._engine(), strategy).model_dump_json()
    )
    return loaded


@pytest.mark.parametrize("trade", [True, False], ids=["priced", "unpriced"])
def test_run_artifacts_refuse_a_final_state_in_another_lane(trade: bool) -> None:
    """Issue 124 (#120 review R5): the final book is paired by lane, not hash.

    The exploratory result keeps its own admission hash in the book, so the
    hash binding holds, while the book names the promotion lane and grades
    its marks promotion-grade. The book validates on its own. Unpriced, the
    book carries no graded mark, so only the lane pairing can refuse it.
    """
    data = _genuine_pair_json(trade=trade)
    state = data["final_state"]
    assert state["lane"] == "exploratory"
    state["lane"] = "promotion"
    state["mark"]["lane"] = "promotion"
    for price in state["mark"]["prices"]:
        price["evidence"]["grade"] = "promotion_grade"
    assert bool(state["mark"]["prices"]) is trade
    assert PortfolioStateV1.model_validate_json(json.dumps(state)).lane == "promotion"

    with pytest.raises(
        ValidationError,
        match=r"final portfolio state is in the promotion lane, its result is in "
        r"the exploratory lane",
    ):
        EvaluationRunArtifactsV1.model_validate_json(json.dumps(data))


def test_run_artifacts_refuse_a_final_state_marked_above_its_result_lane() -> None:
    """The exploratory lane admits promotion-grade evidence; its run grants none.

    Only the grade is raised, so the lane pairing holds and the book is valid
    on its own, yet it would present an exploratory run's valuation as
    promotion-grade.
    """
    data = _genuine_pair_json()
    state = data["final_state"]
    assert state["lane"] == state["mark"]["lane"] == "exploratory"
    assert state["mark"]["prices"]
    for price in state["mark"]["prices"]:
        assert price["evidence"]["grade"] == "exploratory"
        price["evidence"]["grade"] = "promotion_grade"
    assert PortfolioStateV1.model_validate_json(json.dumps(state)).lane == (
        "exploratory"
    )

    with pytest.raises(
        ValidationError,
        match=r"a result in the exploratory lane grants exploratory marks, its "
        r"final state marks security \S+ promotion_grade",
    ):
        EvaluationRunArtifactsV1.model_validate_json(json.dumps(data))

    # Control: the genuine pair validates.
    genuine = _genuine_pair_json()
    assert EvaluationRunArtifactsV1.model_validate_json(json.dumps(genuine))


# ==========================================================================
# Exploratory reconstruction can never masquerade as authentic evidence
# ==========================================================================


def test_a_reconstruction_is_not_a_derived_view_or_a_normalization_reference() -> None:
    observation = build_from_harness(_harness())

    assert isinstance(observation, ExploratoryReconstructedSessionObservationV1)
    assert not isinstance(observation, DerivedObservationViewV1)
    assert not isinstance(observation, ObservationDecisionReferenceV1)
    assert not isinstance(observation, ObservationOutcomeReferenceV1)


def test_a_reconstruction_is_structurally_rejected_by_the_decision_bucket() -> None:
    """A reconstruction lacks every field a derived view is required to carry."""
    observation = build_from_harness(_harness())

    with pytest.raises(ValidationError) as error:
        _realized_bundle(authentic_decision_views=(observation,))

    located = {item["loc"] for item in error.value.errors(include_url=False)}
    for field in ("role", "query", "query_hash", "source_session", "basis_mode"):
        assert ("authentic_decision_views", 0, field) in located


def test_an_outcome_role_view_cannot_enter_the_decision_bucket() -> None:
    """Ex-post evidence in the decision bucket would be a lookahead channel."""
    harness = NormalizationHarness()
    query = harness.normalization_query("source_basis")
    outcome_view = materialize_observation_outcome(
        harness.normalize(query).reference, query, harness.context
    )
    assert outcome_view.role == "outcome"

    with pytest.raises(
        (ValidationError, ValueError),
        match=r"authentic decision views require decision-role evidence",
    ):
        _realized_bundle(authentic_decision_views=(outcome_view,))


def test_a_reconstruction_always_carries_its_retrospective_limitations() -> None:
    # A reconstruction rides only a scheduled clock (issue 72).
    observation = build_from_harness(_harness())
    bundle = _scheduled_bundle(exploratory_reconstructed_observations=(observation,))

    assert observation.acknowledged_limitations
    for limitation in observation.acknowledged_limitations:
        assert limitation in bundle.required_limitations


def test_an_exploratory_admission_cannot_drop_a_reconstruction_limitation() -> None:
    # A reconstruction rides only a scheduled clock (issue 72).
    observation = build_from_harness(_harness())
    bundle = _scheduled_bundle(exploratory_reconstructed_observations=(observation,))
    dropped = tuple(
        item
        for item in bundle.required_limitations
        if item != observation.acknowledged_limitations[0]
    )
    assert len(dropped) < len(bundle.required_limitations)

    with pytest.raises(
        ValueError, match=r"^exploratory admission omits required bundle limitations"
    ):
        validate_exploratory_admission(
            admission=_exploratory_admission(bundle, limitations=dropped),
            bundle=bundle,
        )

    # Control: acknowledging every limitation is admissible in the exploratory
    # lane. ADR 0012 keeps lane one fully usable.
    validate_exploratory_admission(
        admission=_exploratory_admission(bundle), bundle=bundle
    )


def test_an_exploratory_bundle_cannot_wear_a_promotion_snapshot() -> None:
    bundle = _realized_bundle(source_snapshot_hash=H["5"])

    with pytest.raises(
        ValueError,
        match=r"^exploratory evaluation cannot bind a promotion source snapshot",
    ):
        validate_exploratory_admission(
            admission=_exploratory_admission(
                bundle, limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,)
            ),
            bundle=bundle,
        )


# ==========================================================================
# The promotion gate, attacked through its composed surface
# ==========================================================================


@cache
def _cached_admitted_case() -> dict[str, Any]:
    """A promotion case that the gate genuinely admits, for mutation.

    Cached because building it materializes a full M1d corpus. Every member is
    a frozen model and every attack below copies rather than mutates, so the
    cache cannot leak state between tests.
    """
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = rp._promotion_bundle(harness, query, reference, snapshot)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
    )
    return rp._promotion_case(bundle, proof, snapshot, qualified)


def _admitted_case() -> dict[str, Any]:
    return dict(_cached_admitted_case())


def _rebind(case: dict[str, Any], **updates: object) -> dict[str, Any]:
    """Rebind the admission so only the mutation under test remains."""
    rebound = dict(case)
    rebound["admission"] = rebind_admission(rebound, **updates)
    return rebound


def test_the_composed_gate_admits_a_fully_evidenced_promotion_case() -> None:
    """Control for every attack below: the honest case really is admitted."""
    validate_promotion_admission(**_admitted_case())


def test_the_composed_gate_rejects_a_missing_audit_purpose_report() -> None:
    case = _admitted_case()
    completion = copy_constructed(
        case["completion"], purpose_reports=(case["decision_report"],)
    )
    attacked = _rebind(
        {**case, "completion": completion},
        m1e_completion_record_hash=content_hash(completion),
    )

    with pytest.raises(
        ValueError, match=r"^missing retrospective_audit purpose report in completion"
    ):
        validate_promotion_admission(**attacked)


def test_the_composed_gate_rejects_a_failed_audit_critical_dimension() -> None:
    case = _admitted_case()
    audit_profile = case["audit_profile"]
    critical = audit_profile.critical_dimensions[0]
    results = tuple(
        make_dimension_result(
            item.dimension,
            status=QualificationStatus.FAIL,
            purpose=ConsumerPurpose.RETROSPECTIVE_AUDIT,
        )
        if item.dimension == critical
        else item
        for item in case["audit_report"].results
    )
    report = copy_constructed(case["audit_report"], results=results)
    completion = copy_constructed(
        case["completion"], purpose_reports=(case["decision_report"], report)
    )
    handoff = copy_constructed(case["audit_handoff"], report_hash=content_hash(report))
    handoff = copy_constructed(handoff, handoff_hash=_handoff_hash(handoff))
    attacked = _rebind(
        {
            **case,
            "audit_report": report,
            "completion": completion,
            "audit_handoff": handoff,
        },
        m1e_completion_record_hash=content_hash(completion),
        audit_handoff_hash=handoff.handoff_hash,
    )

    with pytest.raises(
        ValueError, match=rf"^critical dimension {critical.value} did not PASS"
    ):
        validate_promotion_admission(**attacked)


def _handoff_hash(handoff: Any) -> str:
    from drift.domain.qualification_adapters import qualified_source_handoff_hash

    digest: str = qualified_source_handoff_hash(handoff)
    return digest


def test_the_composed_gate_rejects_a_report_profile_hash_mismatch() -> None:
    case = _admitted_case()
    target = copy_constructed(case["decision_report"].target, profile_hash=H["a"])
    report = copy_constructed(case["decision_report"], target=target)
    completion = copy_constructed(
        case["completion"], purpose_reports=(report, case["audit_report"])
    )
    attacked = _rebind(
        {**case, "decision_report": report, "completion": completion},
        m1e_completion_record_hash=content_hash(completion),
    )

    with pytest.raises(
        ValueError,
        match=(r"^report target profile hash mismatch for historical_decision_input$"),
    ):
        validate_promotion_admission(**attacked)


def test_the_composed_gate_rejects_a_profile_outside_the_bound_profile_set() -> None:
    case = _admitted_case()
    foreign = copy_constructed(
        case["audit_profile"],
        critical_dimensions=(QualificationDimension.LICENSING_RETENTION,),
    )
    assert qualification_profile_hash(foreign) != qualification_profile_hash(
        case["audit_profile"]
    )

    with pytest.raises(
        ValueError, match=r"^audit profile is not a member of bound profile set"
    ):
        validate_promotion_admission(**{**case, "audit_profile": foreign})


def test_the_composed_gate_rejects_a_pass_report_over_a_negative_completion() -> None:
    """A fake PASS cannot outvote the M1e completion record itself."""
    case = _admitted_case()
    completion = copy_constructed(
        case["completion"], completion_kind=M1eCompletionKind.COMPLETED_NEGATIVE
    )
    attacked = _rebind(
        {**case, "completion": completion},
        m1e_completion_record_hash=content_hash(completion),
    )
    # The reports still say PASS on every dimension.
    for report in (case["decision_report"], case["audit_report"]):
        assert all(item.status is QualificationStatus.PASS for item in report.results)

    with pytest.raises(
        ValueError, match=r"^promotion admission requires positive M1e completion"
    ):
        validate_promotion_admission(**attacked)


def test_the_composed_gate_rejects_an_exploratory_reconstruction() -> None:
    case = _admitted_case()
    observation = build_from_harness(_harness())
    snapshot_hash = case["bundle"].source_snapshot_hash
    poisoned = _scheduled_bundle(
        source_snapshot_hash=snapshot_hash,
        exploratory_reconstructed_observations=(observation,),
    )
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
        match=(
            r"^promotion evaluation cannot consume exploratory reconstructed inputs"
        ),
    ):
        validate_promotion_admission(**attacked)


def test_the_composed_gate_rejects_a_bundle_declaring_any_limitation() -> None:
    """A promotion bundle that still declares development-grade limits is a
    self-contradiction, and must fail closed rather than be admitted."""
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    clock = normalization_realized_clock(harness)
    draft = SessionClockV1.model_construct(
        **(
            dict(clock)
            | {"acknowledged_limitations": (ALPACA_LIMITATION_ABSENT_HALTS,)}
        )
    )
    limited = SessionClockV1.model_validate(
        dict(draft) | {"clock_hash": session_clock_hash(draft)}
    )
    # The builder refuses this clock itself (issue 96), so it reaches minting
    # and the gate only in a bundle re-assembled by hand.
    bundle = with_session_clock(
        rp._promotion_bundle(harness, query, reference, snapshot), limited
    )
    assert bundle.has_exploratory_reconstructions is False
    assert bundle.required_limitations == (ALPACA_LIMITATION_ABSENT_HALTS,)
    # No canonical builder emits a realized clock declaring limitations, and
    # minting re-derives the clock (issue 80), so no proof can be minted.
    with pytest.raises(
        ValueError,
        match=r"^session clock does not match its canonical re-derivation",
    ):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )

    # A proof assembled directly still meets the gate's own refusal.
    proof = _build_bundle_provenance_proof(
        qualified_context_hash=qualified.qualified_hash,
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=bundle,
    )
    case = rp._promotion_case(bundle, proof, snapshot, qualified)

    with pytest.raises(
        ValueError,
        match=(r"^promotion evaluation cannot consume evidence declaring limitations"),
    ):
        validate_promotion_admission(**case)


def test_the_composed_gate_rejects_a_bundle_declaring_a_dataset_limitation() -> None:
    """Issue 92: a producer-declared dataset limitation is still a limitation.

    Nothing re-derives a producer's declaration, so unlike a limited clock a
    bundle declaring one builds and mints genuinely. It differs from the
    admitted control case only in that declaration, and the gate's own
    limitation refusal is what keeps it out of promotion.
    """
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = build_evaluation_input_bundle(
        evaluation_interval=rp._interval(),
        session_clock=normalization_realized_clock(harness),
        context=harness.context,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
        source_snapshot_hash=snapshot.snapshot_hash,
        dataset_limitations=(ALPACA_LIMITATION_TRUNCATED_CA,),
    )
    assert bundle.has_exploratory_reconstructions is False
    assert bundle.required_limitations == (ALPACA_LIMITATION_TRUNCATED_CA,)
    proof = mint_bundle_provenance_proof(
        qualified_context=qualified,
        context=harness.context,
        bundle=bundle,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
    )
    case = rp._promotion_case(bundle, proof, snapshot, qualified)

    with pytest.raises(
        ValueError,
        match=(
            r"^promotion evaluation cannot consume evidence declaring limitations: "
            rf"\('{ALPACA_LIMITATION_TRUNCATED_CA}',\)$"
        ),
    ):
        validate_promotion_admission(**case)


def test_a_promotion_admission_cannot_omit_its_provenance_proof_hash() -> None:
    admission = make_test_fixture()["admission"]
    payload = dict(admission)
    payload.pop("provenance_proof_hash")

    with pytest.raises(ValidationError) as error:
        PromotionEvaluationAdmissionV1.model_validate(payload)

    assert ("provenance_proof_hash",) in {
        item["loc"] for item in error.value.errors(include_url=False)
    }


def test_a_promotion_admission_is_never_an_exploratory_admission() -> None:
    fixture = make_test_fixture()
    admission = fixture["admission"]
    assert isinstance(admission, PromotionEvaluationAdmissionV1)

    with pytest.raises(ValidationError) as error:
        ExploratoryEvaluationAdmissionV1.model_validate(dict(admission))

    reported = {
        (item["type"], item["loc"]) for item in error.value.errors(include_url=False)
    }
    # The lane discriminator itself refuses the shape, not merely the extra
    # promotion fields that ride along with it.
    assert ("literal_error", ("lane",)) in reported
    assert ("extra_forbidden", ("provenance_proof_hash",)) in reported


# ==========================================================================
# Replay integrity: a view hash is not a replay
# ==========================================================================


def test_a_self_consistent_fabricated_view_is_refused_by_replay_verification() -> None:
    harness, query, reference = _cached_decision_case()
    genuine = materialize_observation_decision(reference, query, harness.context)
    forged = DerivedObservationViewV1.model_construct(
        **(dict(genuine) | {"derivation_hash": H["e"]})
    )
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=rp._interval(),
        session_clock=normalization_realized_clock(harness),
        authentic_decision_views=(forged,),
    )
    # The bundle is entirely self consistent: it carries the forged view and
    # its own hash checks out against its own contents.
    assert bundle.authentic_decision_views == (forged,)
    assert bundle.bundle_hash == evaluation_input_bundle_hash(bundle)

    with pytest.raises(
        ValueError, match=r"^decision views do not match exact upstream replay"
    ):
        verify_evaluation_input_bundle(
            bundle=bundle,
            context=harness.context,
            decision_requests=((reference, query),),
        )


def test_a_stripped_dataset_limitation_is_refused_by_hash_verification() -> None:
    """Issue 92: dropping a declared dataset limitation breaks the bundle hash."""
    declared = _scheduled_bundle(dataset_limitations=(ALPACA_LIMITATION_TRUNCATED_CA,))
    stripped = EvaluationInputBundleV1.model_construct(
        **(dict(declared) | {"dataset_limitations": ()})
    )
    assert stripped.bundle_hash == declared.bundle_hash
    assert ALPACA_LIMITATION_TRUNCATED_CA not in stripped.required_limitations

    with pytest.raises(ValueError, match=r"^bundle hash does not match its own"):
        verify_evaluation_input_bundle(bundle=stripped, context=_harness().context)
    with pytest.raises(ValidationError, match="bundle hash mismatch"):
        EvaluationInputBundleV1.model_validate(stripped.model_dump())


def test_minting_refuses_a_bundle_whose_views_replay_did_not_produce() -> None:
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    genuine = materialize_observation_decision(reference, query, harness.context)
    forged = DerivedObservationViewV1.model_construct(
        **(dict(genuine) | {"derivation_hash": H["e"]})
    )
    bundle = assemble_evaluation_input_bundle(
        evaluation_interval=rp._interval(),
        session_clock=normalization_realized_clock(harness),
        authentic_decision_views=(forged,),
        source_snapshot_hash=snapshot.snapshot_hash,
    )

    with pytest.raises(
        ValueError, match=r"^decision views do not match exact upstream replay"
    ):
        mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )


def test_a_bundle_member_missing_from_the_proof_fails_closed() -> None:
    """Coverage is total: an unproven authority-bearing member is not admitted."""
    case = _admitted_case()
    proof = case["proof"]
    assert set(proof.component_hashes) == set(bundle_component_hashes(case["bundle"]))
    draft = BundleProvenanceProofV1.model_construct(
        **(
            dict(proof)
            | {"component_hashes": proof.component_hashes[1:], "proof_hash": H["0"]}
        )
    )
    trimmed = BundleProvenanceProofV1.model_validate(
        dict(draft) | {"proof_hash": bundle_provenance_proof_hash(draft)}
    )
    attacked = _rebind(
        {**case, "proof": trimmed}, provenance_proof_hash=trimmed.proof_hash
    )

    with pytest.raises(
        ValueError, match=r"^provenance proof component coverage mismatch"
    ):
        validate_promotion_admission(**attacked)


# ==========================================================================
# Closed finding: the gate re-verifies the containment witness (issue 31)
# ==========================================================================


def _forge_qualified_context(
    *, identity: Any, source_snapshot_hash: str
) -> QualifiedReplayContextV1:
    """A structurally valid qualified context whose witness is fabricated.

    Every entry names a snapshot entry hash that was invented here. Nothing in
    ``QualifiedReplayContextV1`` can tell: proving the witness requires the
    snapshot, and the model never sees one.
    """
    witness = tuple(
        SnapshotBindingEntryV1(
            schema_version="1",
            artifact_hash=artifact_hash,
            snapshot_entry_hash=content_hash({"forged-entry-for": artifact_hash}),
        )
        for artifact_hash in context_supplied_artifact_hashes(identity)
    )
    ordered = tuple(sorted(witness, key=lambda entry: entry.artifact_hash))
    draft = QualifiedReplayContextV1.model_construct(
        schema_version="1",
        source_snapshot_hash=source_snapshot_hash,
        context_identity=identity,
        snapshot_binding_witness=ordered,
        snapshot_binding_proof_hash=snapshot_binding_witness_hash(ordered),
        qualified_hash=H["0"],
    )
    candidate = QualifiedReplayContextV1.model_construct(
        **(dict(draft) | {"qualified_hash": qualified_replay_context_hash(draft)})
    )
    return QualifiedReplayContextV1.model_validate(candidate.model_dump())


def test_a_forged_qualified_replay_context_validates_without_any_snapshot() -> None:
    """The contract cannot detect a fabricated witness on its own."""
    harness, _, _ = _cached_decision_case()
    identity = derive_replay_context_identity(harness.context)

    forged = _forge_qualified_context(identity=identity, source_snapshot_hash=H["5"])

    assert forged.source_snapshot_hash == H["5"]
    assert forged.qualified_hash == qualified_replay_context_hash(forged)
    assert tuple(
        entry.artifact_hash for entry in forged.snapshot_binding_witness
    ) == context_supplied_artifact_hashes(identity)


def test_pure_assembly_cannot_launder_an_arbitrary_context_hash_past_the_gate() -> None:
    """Inverted from the characterization test that documented P0-3.

    Same attack, opposite verdict. The unverified assembly function mints a
    structurally perfect proof over a context hash nobody ever qualified, and
    the gate used to admit it. It is now module-private, and even reaching past
    that boundary does not help: the gate demands the qualified context object
    the proof names and refuses when the hash does not match it.
    """
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    bundle = rp._promotion_bundle(harness, query, reference, snapshot)

    proof = _build_bundle_provenance_proof(
        qualified_context_hash=H["9"],
        source_snapshot_hash=snapshot.snapshot_hash,
        bundle=bundle,
    )

    assert proof.qualified_context_hash == H["9"]
    assert qualified.qualified_hash != H["9"]
    case = rp._promotion_case(bundle, proof, snapshot, qualified)

    with pytest.raises(
        ValueError,
        match=(
            r"^provenance proof qualified context mismatch: proof binds "
            rf"{H['9']}, context is {qualified.qualified_hash}$"
        ),
    ):
        validate_promotion_admission(**case)


def test_the_promotion_gate_refuses_a_proof_over_a_forged_qualified_context() -> None:
    """Inverted from the characterization test that documented P0-1.

    The attack construction is unchanged: a real M1d replay, a real
    ``mint_bundle_provenance_proof`` call, and a real
    ``validate_promotion_admission`` call, with the only hand-built artifact a
    ``QualifiedReplayContextV1`` that is fully valid under its own contract and
    names a snapshot attesting a completely different corpus. The gate now
    receives that context and the snapshot and re-audits the witness, so the
    evaluation is refused where it used to be admitted.
    """
    harness, query, reference = _cached_decision_case()
    foreign = snapshot_over(
        context_supplied_artifact_hashes(
            derive_replay_context_identity(rp._unrelated_context())
        )
    )
    identity = derive_replay_context_identity(harness.context)

    # The honest path refuses outright: this context is not in that snapshot.
    with pytest.raises(ValueError, match=r"absent from source snapshot"):
        qualify_replay_context(context=harness.context, snapshot=foreign)

    forged = _forge_qualified_context(
        identity=identity, source_snapshot_hash=foreign.snapshot_hash
    )
    bundle = rp._promotion_bundle(harness, query, reference, foreign)
    proof = mint_bundle_provenance_proof(
        qualified_context=forged,
        context=harness.context,
        bundle=bundle,
        session_queries=normalization_session_queries(harness),
        decision_requests=((reference, query),),
    )
    case = rp._promotion_case(bundle, proof, foreign, forged)

    # The gate reaches the same verdict the compensating control does, and it
    # names the exact fabricated witness entry rather than failing vaguely.
    entry = forged.snapshot_binding_witness[0]
    expected = (
        rf"^witness entry {entry.snapshot_entry_hash} does not resolve to a "
        rf"snapshot entry of {foreign.snapshot_hash}$"
    )
    with pytest.raises(ValueError, match=expected):
        validate_promotion_admission(**case)

    with pytest.raises(ValueError, match=expected):
        verify_snapshot_binding(qualified=forged, snapshot=foreign)


def test_the_promotion_gate_has_a_channel_to_re_verify_the_witness() -> None:
    """Inverted from the characterization test that pinned the missing channel.

    The parameters are the fix. Without both the qualified context and the
    snapshot there is no way for the gate to re-audit anything, which is why
    the unsafe signature is not preserved for compatibility.
    """
    parameters = inspect.signature(validate_promotion_admission).parameters

    for required in ("proof", "qualified_context", "snapshot"):
        assert required in parameters
        assert parameters[required].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[required].default is inspect.Parameter.empty

    annotations = {name: parameters[name].annotation for name in parameters}
    assert annotations["qualified_context"] is QualifiedReplayContextV1
    assert annotations["snapshot"] is RealSourceSnapshotV1


def test_the_witness_verifier_is_called_from_inside_the_promotion_gate() -> None:
    """The compensating control is now the gate, not a convention beside it.

    ``verify_snapshot_binding`` is the only thing that can catch a fabricated
    containment witness. It used to have zero production call sites, so the
    "trust flows from minting" argument rested on no production path at all.
    It is now called from the body of ``validate_promotion_admission`` and
    nowhere else under ``src``, so an edit that drops the call is visible here.
    """
    root = Path(__file__).resolve().parents[2] / "src"
    gate = root / "drift" / "evaluator" / "bundles.py"
    scanned = 0
    call_sites: list[str] = []
    for path in sorted(root.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "verify_snapshot_binding":
                    call_sites.append(f"{path.name}:{node.func.id}")

    assert scanned >= 40, "the production call-site scan found no modules"
    assert call_sites == ["bundles.py:verify_snapshot_binding"]

    gate_tree = ast.parse(gate.read_text(encoding="utf-8"))
    inside = [
        node
        for node in ast.walk(gate_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "validate_promotion_admission"
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "verify_snapshot_binding"
    ]
    assert len(inside) == 1


def test_the_rest_of_the_chain_stays_contract_only() -> None:
    """Minting and qualification still have no production caller.

    The promotion lane is unreachable while M1e Task 8 is deferred, so this is
    expected. It is asserted rather than assumed, because the day one of these
    gains a caller is the day the lane becomes live and this suite must be the
    thing that notices.
    """
    root = Path(__file__).resolve().parents[2] / "src"
    watched = {
        "qualify_replay_context",
        "mint_bundle_provenance_proof",
        "validate_promotion_admission",
    }
    scanned = 0
    call_sites: list[str] = []
    for path in sorted(root.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in watched:
                    call_sites.append(f"{path.name}:{node.lineno}:{node.func.id}")

    assert scanned >= 40, "the production call-site scan found no modules"
    assert call_sites == []


def test_witness_re_verification_needs_no_m1d_replay() -> None:
    """The gate stays cheap: hashes and lookups, no replay.

    This is the ruling the closing note got wrong. Re-verifying the witness
    reads only the snapshot's own replay input entries, so admitting it into
    the gate costs nothing the "no M1d replay inside admission" constraint was
    protecting.
    """
    harness, _, _ = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)

    source = inspect.getsource(verify_snapshot_binding)

    verify_snapshot_binding(qualified=qualified, snapshot=snapshot)
    assert "replay_inputs" in source
    for forbidden in (
        "materialize_observation",
        "normalize_observation",
        "M1dResolutionContext",
        "select_observation_records",
    ):
        assert forbidden not in source


# ==========================================================================
# Closed findings: every authority-bearing input is re-derived or bound
# (issue 80, the #31 Decision 4 ruling)
# ==========================================================================


@pytest.mark.parametrize(
    "swap", ["control", "invented_authority_late_close", "scheduled_row_relabelled"]
)
def test_the_sanctioned_path_re_derives_the_realized_clock(swap: str) -> None:
    """Causality F1: the probe that admitted a swapped clock in all three shapes.

    The genuine early-close bundle is rebuilt with its clock swapped: invented
    authority hashes with the close moved three hours later, and a scheduled
    calendar row relabelled as realized. Minting used to check neither, and
    the gate reads only the mode and authority labels. Minting now rebuilds the
    clock from its session queries, and so does the build that precedes it
    (issue 96), so only the control obtains a bundle and a proof.
    """
    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    genuine = normalization_realized_clock(harness)
    session = genuine.sessions[0]
    clock = {
        "control": genuine,
        "invented_authority_late_close": resealed_clock(
            genuine,
            closed_at=session.closed_at + timedelta(hours=3),
            authority_record_hashes=(H["e"],),
            authority_proof_hashes=(H["f"],),
        ),
        "scheduled_row_relabelled": resealed_clock(
            normalization_scheduled_clock(harness),
            mode="realized_session_authority",
            acknowledged_limitations=(),
            authority="realized",
        ),
    }[swap]

    def build(session_clock: SessionClockV1) -> EvaluationInputBundleV1:
        return build_evaluation_input_bundle(
            evaluation_interval=rp._interval(),
            session_clock=session_clock,
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
            source_snapshot_hash=snapshot.snapshot_hash,
        )

    def mint(bundle: EvaluationInputBundleV1) -> BundleProvenanceProofV1:
        return mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )

    if swap == "control":
        bundle = build(clock)
        validate_promotion_admission(
            **rp._promotion_case(bundle, mint(bundle), snapshot, qualified)
        )
        return
    refusal = (
        r"^session clock does not match its canonical re-derivation: bundle "
        rf"clock {clock.clock_hash}, re-derived {genuine.clock_hash}$"
    )
    with pytest.raises(ValueError, match=refusal):
        build(clock)
    # Minting still refuses the clock in a bundle re-assembled by hand.
    with pytest.raises(ValueError, match=refusal):
        mint(with_session_clock(build(genuine), clock))


def test_the_sanctioned_path_refuses_a_fabricated_universe() -> None:
    """Lanes F5: build, mint and gate admitted an invented AS_KNOWN universe.

    Spec 7.4 items 4 and 5 require M1b and M1c replay at preparation. The
    probe's fabricated eligibility carries invented resolution hashes under an
    AS_KNOWN label, and its clock invented authority hashes. Minting now
    re-derives both, so neither can obtain a proof, whichever it meets first.
    """
    import test_evaluator_engine as eng

    harness, query, reference = _cached_decision_case()
    snapshot = qualified_snapshot(harness.context)
    qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
    fabricated = eng._eligibility(eng.SEC_B, eng.LISTING_B)
    assert fabricated.normalized_query.resolution_mode is ResolutionMode.AS_KNOWN
    genuine_clock = normalization_realized_clock(harness)
    forged_clock = resealed_clock(
        genuine_clock,
        authority_record_hashes=(H["1"],),
        authority_proof_hashes=(H["2"],),
    )

    for clock, eligibilities, expected in (
        (
            forged_clock,
            (fabricated,),
            r"^structural eligibility count mismatch against replay: "
            r"expected 0, bundle carries 1$",
        ),
        (
            forged_clock,
            (),
            r"^session clock does not match its canonical re-derivation",
        ),
    ):
        built = build_evaluation_input_bundle(
            evaluation_interval=rp._interval(),
            session_clock=genuine_clock,
            context=harness.context,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
            structural_eligibilities=eligibilities,
            source_snapshot_hash=snapshot.snapshot_hash,
        )
        # The builder refuses the forged clock itself (issue 96), so it reaches
        # minting only in a bundle re-assembled by hand.
        bundle = with_session_clock(built, clock)
        with pytest.raises(ValueError, match=expected):
            mint_bundle_provenance_proof(
                qualified_context=qualified,
                context=harness.context,
                bundle=bundle,
                session_queries=normalization_session_queries(harness),
                decision_requests=((reference, query),),
            )


def test_the_gate_refuses_an_impostor_snapshot_wearing_the_qualified_hash() -> None:
    """Lanes F2: the issue 31 attack moved one object over.

    Corpus A is genuine and replayable, and unrelated to the qualified corpus
    Q whose snapshot S the admission names. A snapshot object that keeps S's
    hash while attesting A used to pass `verify_snapshot_binding`, which read
    the declared hash and never recomputed it. Both the binder and the gate's
    re-audit now recompute it.
    """
    harness, _, _ = _cached_decision_case()
    genuine = qualified_snapshot(harness.context)
    adversary = NormalizationHarness(
        outer_kind="decision",
        numeric_values=("900.00", "950.00", "850.00", "925.00", "1000"),
    )
    a_query = adversary.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    a_reference = adversary.normalize(a_query).reference
    a_identity = derive_replay_context_identity(adversary.context)
    with pytest.raises(ValueError, match=r"absent from source snapshot"):
        qualify_replay_context(context=adversary.context, snapshot=genuine)

    attesting = snapshot_over(context_supplied_artifact_hashes(a_identity))
    impostor = RealSourceSnapshotV1.model_construct(
        **(dict(attesting) | {"snapshot_hash": genuine.snapshot_hash})
    )
    recomputed = real_source_snapshot_hash(impostor)
    assert recomputed == attesting.snapshot_hash != genuine.snapshot_hash
    expected = (
        r"^source snapshot hash does not match its own contents: declared "
        rf"{genuine.snapshot_hash}, recomputed {recomputed}$"
    )
    # The sanctioned binder refuses the impostor outright.
    with pytest.raises(ValueError, match=expected):
        bind_context_identity_to_snapshot(identity=a_identity, snapshot=impostor)

    # A context bound over the attesting snapshot and renamed to S is valid
    # under its own contract, and minting cannot tell: it never sees a snapshot.
    honest = bind_context_identity_to_snapshot(identity=a_identity, snapshot=attesting)
    renamed = QualifiedReplayContextV1.model_validate(
        rp._rehash_qualified(
            QualifiedReplayContextV1.model_construct(
                **(dict(honest) | {"source_snapshot_hash": genuine.snapshot_hash})
            )
        ).model_dump()
    )
    bundle = rp._promotion_bundle(adversary, a_query, a_reference, impostor)
    proof = mint_bundle_provenance_proof(
        qualified_context=renamed,
        context=adversary.context,
        bundle=bundle,
        session_queries=normalization_session_queries(adversary),
        decision_requests=((a_reference, a_query),),
    )
    case = rp._promotion_case(bundle, proof, impostor, renamed)

    with pytest.raises(ValueError, match=expected):
        validate_promotion_admission(**case)


def test_the_gate_refuses_purpose_laundered_decision_evidence() -> None:
    """Lanes F4: decision views admitted over audit-only, foreign-profile input.

    M1e qualifies each purpose separately. The probe's snapshot attests every
    context artifact only as retrospective audit input, under a profile of no
    bound profile set, in a snapshot of a foreign profile set that authorizes
    neither admission profile. Entries used to be matched by content hash
    alone. Each binding now refuses on its own: repairing one exposes the next.
    """
    harness, query, reference = _cached_decision_case()
    set_hash, decision_hash, audit_hash = admission_profile_hashes()
    artifacts = context_supplied_artifact_hashes(
        derive_replay_context_identity(harness.context)
    )
    laundered = {
        "purpose": ConsumerPurpose.RETROSPECTIVE_AUDIT,
        "profile_hash": H["e"],
    }
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        (
            {
                **laundered,
                "profile_set_hash": H["0"],
                "authorized_profile_hashes": (H["3"],),
            },
            r"^source snapshot profile set mismatch with admission: snapshot binds "
            rf"{H['0']}, admission binds {set_hash}$",
        ),
        (
            {**laundered, "authorized_profile_hashes": (H["3"],)},
            rf"^source snapshot does not authorize the decision profile "
            rf"{decision_hash}$",
        ),
        (
            {**laundered, "authorized_profile_hashes": (decision_hash,)},
            rf"^source snapshot does not authorize the audit profile {audit_hash}$",
        ),
        (
            laundered,
            r"^witness entry [0-9a-f]{64} attests artifact [0-9a-f]{64} for "
            rf"retrospective_audit under profile {H['e']}, but the bundle's "
            r"decision views require historical_decision_input under profile "
            rf"{decision_hash}$",
        ),
    )
    for overrides, expected in cases:
        snapshot = snapshot_over(artifacts, **overrides)
        # Every snapshot here is genuinely valid, so its own hash is honest.
        RealSourceSnapshotV1.model_validate(snapshot.model_dump())
        qualified = qualify_replay_context(context=harness.context, snapshot=snapshot)
        bundle = rp._promotion_bundle(harness, query, reference, snapshot)
        proof = mint_bundle_provenance_proof(
            qualified_context=qualified,
            context=harness.context,
            bundle=bundle,
            session_queries=normalization_session_queries(harness),
            decision_requests=((reference, query),),
        )
        case = rp._promotion_case(bundle, proof, snapshot, qualified)
        with pytest.raises(ValueError, match=expected):
            validate_promotion_admission(**case)


# ==========================================================================
# The promotion lane is disabled (issue 79 ruling, option 1)
# ==========================================================================

PROMOTION_LANE_DISABLED = r"^the promotion lane is disabled \(issue 79 ruling\): "

# Computed on unmodified main at 19c15f8, before the promotion lane was
# disabled. Disabling it must leave both exploratory lanes byte-identical.
REALIZED_TRACE_HASH_AT_19C15F8 = (
    "80720399a140980ab0bc99b3d145a92b80e3aa7a907d097a8e6168178b46dd41"
)
REALIZED_RESULT_HASH_AT_19C15F8 = (
    "f37b894459102c54ea8f5a36f457a338f8063ef77f5b9bc0084e3b1a270bd126"
)
RECONSTRUCTED_TRACE_HASH_AT_19C15F8 = (
    "9224bab85f14f287e42448fa1c202a4321c1c6572565c0b708c2d8db7514c692"
)
RECONSTRUCTED_RESULT_HASH_AT_19C15F8 = (
    "32423c7459cfb9cd1a5087b0315fc8d6bca37be88260416fec868661f6f235c0"
)
# Issue 92 adds a hash-covered `dataset_limitations` field to every bundle, so
# every bundle hash moves once and, through the run identity that binds it,
# every result hash. Trace hashes do not bind the bundle and stay at 19c15f8.
# These are the same two runs' result hashes after that recorded change.
REALIZED_RESULT_HASH_SINCE_ISSUE_92 = (
    "152c914fa55c910437a2baf1e153db9e9d41fd0cbaa9dc0e14134bbaec51b0a4"
)
RECONSTRUCTED_RESULT_HASH_SINCE_ISSUE_92 = (
    "4ed8488ff7e2b63922cb574ae35db959a1f6d49cd273337f9007a908366cd240"
)
# Issue 107 edits `semantic_attestation.py`, a declared module of the
# `m1d-evidence-v1` closure, so the M1d evidence identity moves by design and,
# with it, every identity-bearing hash of runs over M1d evidence (session,
# reconstruction, context, mark and price hashes, then the trace and result).
# No quantity, price, cash, NAV or classification changes. These are the same
# two runs' hashes since that recorded change; each later declared-closure
# edit (issue 63 stage 2, issue 71) re-pins them the same way.
REALIZED_TRACE_HASH_SINCE_ISSUE_107 = (
    "ccba690be67b4e2296fc5a7187011a8af7d3cf26e6a8eb8514ec4b64880199a4"
)
REALIZED_RESULT_HASH_SINCE_ISSUE_107 = (
    "9c9c90774f128b6684c72b326b856c818e22a5abb00eed8a491ab1511664f546"
)
RECONSTRUCTED_TRACE_HASH_SINCE_ISSUE_107 = (
    "2aa1e3553f020d61fca2b948e76f73dc1a2f480eb71cffdf3d11ebefe2c31913"
)
RECONSTRUCTED_RESULT_HASH_SINCE_ISSUE_107 = (
    "81031d35feeaa7436884c259f4cef598689f764f51ab8e7418057caad8589e0c"
)


def _promotion_engine(bundle: Any, admission: Any) -> SessionEvaluatorEngine:
    import test_evaluator_engine as eng

    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=admission,
        protocol=eng._protocol(),
        cost_model=eng._cost_model(),
        evidence=SessionEvaluatorEvidence(),
        book_currency_namespace=eng.BOOK_NAMESPACE,
        book_currency_code=eng.BOOK_CODE,
    )


def test_the_engine_refuses_a_promotion_case_the_gate_genuinely_admits() -> None:
    """Gate validity grants no evaluation: the lane itself is disabled.

    This is the most genuine promotion case the suite builds: a replay-minted
    proof, a qualified context, a re-audited snapshot, and positive M1e
    evidence. The gate admits it, and the engine still refuses it.
    """
    case = _admitted_case()
    validate_promotion_admission(**case)
    admission = case["admission"]
    assert isinstance(admission, PromotionEvaluationAdmissionV1)
    assert admission.input_bundle_hash == case["bundle"].bundle_hash

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "engine construction refuses",
    ):
        _promotion_engine(case["bundle"], admission)


def test_the_engine_refuses_the_forged_admission_of_finding_f1() -> None:
    """F1: invented M1e and proof hashes over an exploratory, unsnapshotted bundle.

    At 19c15f8 this admission ran to a COMPLETE promotion-grade result, and
    the experiment runner recorded it as ``lane=promotion``.
    """
    import test_evaluator_engine as eng
    from exploratory_decision_test_support import promotion_admission

    bundle = eng._bundle()
    assert bundle.source_snapshot_hash is None
    forged = promotion_admission(bundle)
    assert forged.m1e_completion_record_hash == H["1"]
    assert forged.provenance_proof_hash == H["5"]

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "engine construction refuses",
    ):
        _promotion_engine(bundle, forged)

    # Control: the exploratory admission of the same bundle still runs.
    assert eng._run(eng._engine(bundle=bundle)).result.lane == "exploratory"


def test_no_public_engine_or_runner_entry_yields_promotion_evidence(
    tmp_path: Path,
) -> None:
    """Every public entry refuses a promotion admission, and records nothing.

    Construction refuses both the genuine and the forged admission. Past
    construction, in the state 19c15f8 built for a promotion admission, the
    run refuses, and so does the experiment runner, before any session is
    stepped and before anything reaches M0 or the audit ledger.
    """
    import test_evaluator_engine as eng
    import test_evaluator_experiment_run as run_support
    from exploratory_decision_test_support import promotion_admission

    genuine = _admitted_case()
    forged_bundle = eng._bundle()
    for bundle, admission in (
        (genuine["bundle"], genuine["admission"]),
        (forged_bundle, promotion_admission(forged_bundle)),
    ):
        with pytest.raises(
            PromotionLaneDisabledError,
            match=PROMOTION_LANE_DISABLED + "engine construction refuses",
        ):
            _promotion_engine(bundle, admission)

    strategy = eng._buy_ten()
    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "an engine run refuses",
    ):
        eng._run(eng._bypassed_promotion_engine(), strategy)

    ledger = SQLiteLedger(tmp_path / "audit.sqlite3")
    context = run_support._context(
        eng._bypassed_promotion_engine(), strategy=strategy, ledger=ledger
    )
    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "the experiment runner refuses",
    ):
        execute_experiment_run(run_support._specification(), context)

    assert strategy.seen == []
    assert ledger.verified_events() == ()


def _promotion_evidence_sites(path: Path) -> tuple[list[str], int]:
    """Source text that looks like building promotion evidence.

    A site is a call naming ``PromotionEvaluationResultV1``, a plain alias of
    that type, or a literal stating ``lane`` as ``"promotion"`` or
    ``is_promotion_grade_evidence`` as true. The lane literal is what selects
    the promotion member when a result is built through ``EvaluationResultV1``
    or ``EvaluationRunArtifactsV1``. An ``isinstance`` test names the type
    without building one, so it is not a site.
    """
    sites: list[str] = []
    calls = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        pairs: list[tuple[object, ast.expr]]
        if isinstance(node, ast.Assign | ast.AnnAssign) and (
            isinstance(node.value, ast.Name | ast.Attribute)
            and ast.unparse(node.value).endswith("PromotionEvaluationResultV1")
        ):
            sites.append(f"{path.name}:{node.lineno} aliases the promotion result")
            continue
        if isinstance(node, ast.Call):
            calls += 1
            if ast.unparse(node.func) != "isinstance" and any(
                "PromotionEvaluationResultV1" in ast.unparse(part)
                for part in (node.func, *node.args)
            ):
                sites.append(f"{path.name}:{node.lineno} builds a promotion result")
            pairs = [(keyword.arg, keyword.value) for keyword in node.keywords]
        elif isinstance(node, ast.Dict):
            pairs = [
                (key.value, value)
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
        else:
            continue
        for name, value in pairs:
            if not isinstance(value, ast.Constant):
                continue
            if name == "is_promotion_grade_evidence" and value.value is True:
                sites.append(f"{path.name}:{node.lineno} asserts promotion grade")
            if name == "lane" and value.value == "promotion":
                sites.append(f"{path.name}:{node.lineno} states the promotion lane")
    return sites, calls


def test_no_production_source_builds_a_promotion_result() -> None:
    """A tripwire, not a proof: no production text looks like promotion evidence.

    The engine sealed a promotion result at 19c15f8 with
    ``_seal(PromotionEvaluationResultV1, ...)`` and a promotion lane literal;
    this scan would flag that text, a plain alias of the type, or a literal
    lane or promotion-grade flag. It reads source text only, so indirection
    it does not model (a computed lane, a type reached through a container)
    escapes it. The behavioural refusal tests above are the proof; this only
    catches the obvious regression early. The model and the gate stay.
    """
    root = Path(__file__).resolve().parents[2]
    sources = sorted(
        (*(root / "src" / "drift").rglob("*.py"), *(root / "scripts").glob("*.py"))
    )
    offending: list[str] = []
    inspected = 0
    for path in sources:
        sites, calls = _promotion_evidence_sites(path)
        offending.extend(sites)
        inspected += calls

    assert inspected >= 1000, "the promotion-evidence scan inspected nothing"
    assert offending == []


def test_disabling_promotion_leaves_the_realized_lane_byte_identical() -> None:
    import test_evaluator_engine as eng

    artifacts = eng._run(eng._engine())

    assert artifacts.result.lane == "exploratory"
    assert artifacts.result.metrics.committed_fill_count == 1
    assert artifacts.trace.trace_hash == REALIZED_TRACE_HASH_SINCE_ISSUE_107
    assert artifacts.result.result_hash == REALIZED_RESULT_HASH_SINCE_ISSUE_107


def test_disabling_promotion_leaves_the_reconstructed_lane_byte_identical() -> None:
    from exploratory_decision_test_support import (
        JAN5,
        JAN6,
        SEC,
        ReconstructedTargetStrategy,
        bundle_of,
        reconstructed_engine,
        run_engine,
        three_regular_sessions,
    )

    artifacts = run_engine(
        reconstructed_engine(bundle_of(three_regular_sessions())),
        ReconstructedTargetStrategy({JAN5: ((SEC, 10),), JAN6: ((SEC, 10),)}),
    )

    assert artifacts.result.lane == "exploratory"
    assert artifacts.result.metrics.committed_fill_count == 1
    assert any(
        event.kind == "exploratory_strategy_decision"
        for event in artifacts.trace.events
    )
    assert artifacts.trace.trace_hash == RECONSTRUCTED_TRACE_HASH_SINCE_ISSUE_107
    assert artifacts.result.result_hash == RECONSTRUCTED_RESULT_HASH_SINCE_ISSUE_107
