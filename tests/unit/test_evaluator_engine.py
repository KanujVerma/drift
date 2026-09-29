"""Unit tests for the M2 Task 6 deterministic five-phase session evaluator.

Derived views are the engine's inputs, not its outputs. One genuinely
materialized M1d source-basis view anchors the price bridge test; the rest of
the view family is restated from that same template so the engine can be
exercised over several securities and sessions without rebuilding an entire
M1d corpus per session. Bundle-level replay verification is Task 2B's gate and
is tested there.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import cache
from typing import Any
from uuid import UUID

import pytest
from observation_test_support import NormalizationHarness, market_uid, uid
from pydantic import ValidationError
from session_test_support import boundary_at, revision
from test_assertions import exact_boundary

from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.assertions import (
    InformationRole,
    M1bSelectionPurpose,
    NormalizedSelectionQueryV1,
    ResolutionMode,
    TemporalIntervalClaimV1,
)
from drift.domain.common import UUID7
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV1,
)
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)
from drift.domain.evaluator_costs import (
    EvaluationCostModelV1,
    evaluation_cost_model_hash,
)
from drift.domain.evaluator_execution import (
    AtomicRebalanceCommitError,
    RebalancePlanV1,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PortfolioStateV2,
)
from drift.domain.evaluator_protocol import (
    EvaluationProtocolV1,
    evaluation_protocol_hash,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
    EvaluationSummaryMetricsV1,
    ExploratoryEvaluationResultV1,
    PromotionEvaluationResultV1,
    SessionEquityPointV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.normalization import (
    DerivedObservationViewV1,
    NormalizationQueryV1,
    derived_view_output_hash,
)
from drift.domain.observation_query import ObservationOutcomeQueryV1
from drift.domain.securities import (
    ListingRole,
    ListingRoleVersionV1,
    ListingV1,
    ListingVenue,
    SecurityV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.domain.universes import (
    StructuralEligibilityClassification,
    StructuralEligibilityResultV1,
)
from drift.evaluator.bundles import (
    assemble_evaluation_input_bundle,
    build_evaluation_run_identity,
)
from drift.evaluator.engine import (
    PromotionLaneDisabledError,
    SessionEvaluatorEngine,
    SessionEvaluatorEvidence,
    source_basis_price,
)
from drift.serialization.canonical import content_hash

BOOK_NAMESPACE = "ISO-4217"
BOOK_CODE = "USD"

SEC_A = market_uid(200)
SEC_B = market_uid(300)
ISSUER = market_uid(202)
LISTING_A = market_uid(201)
LISTING_B = market_uid(301)

DAY_0 = date(2026, 1, 5)
DAY_1 = date(2026, 1, 6)
DAY_2 = date(2026, 1, 7)
DAY_3 = date(2026, 1, 8)
DAYS = (DAY_0, DAY_1, DAY_2, DAY_3)

STRATEGY_CODE_HASH = "a" * 64
CODE_VERSION_HASH = "c" * 64
ENVIRONMENT_HASH = "e" * 64

H = {character: character * 64 for character in "0123456789abcdef"}

#: Exact unadjusted source-basis open and close prices per security per day.
PRICES: dict[UUID, dict[date, tuple[str, str]]] = {
    SEC_A: {
        DAY_0: ("100.00", "100.00"),
        DAY_1: ("100.00", "100.00"),
        DAY_2: ("100.00", "110.00"),
        DAY_3: ("110.00", "120.00"),
    },
    SEC_B: {
        DAY_0: ("50.00", "50.00"),
        DAY_1: ("50.00", "50.00"),
        DAY_2: ("50.00", "50.00"),
        DAY_3: ("50.00", "50.00"),
    },
}


# --- session clock -----------------------------------------------------


def _key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _close_of(day: date) -> datetime:
    return datetime.combine(day, time(21, 0), tzinfo=UTC)


def _session(day: date) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_key(day),
        opened_at=datetime.combine(day, time(14, 30), tzinfo=UTC),
        closed_at=_close_of(day),
        authority="realized",
        authority_record_hashes=(H["1"],),
        authority_proof_hashes=(H["2"],),
        session_hash=H["0"],
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _clock(days: Sequence[date] = DAYS) -> SessionClockV1:
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=tuple(_session(day) for day in days),
        acknowledged_limitations=(),
        clock_hash=H["0"],
    )
    candidate = draft.model_copy(update={"clock_hash": session_clock_hash(draft)})
    return SessionClockV1.model_validate(candidate.model_dump())


# --- derived observation views -----------------------------------------


@cache
def _template_view() -> DerivedObservationViewV1:
    """One genuinely materialized M1d source-basis decision view.

    Values are pinned so every restated view carries exact decimals whose
    provenance is a real normalization run rather than a hand-built payload.
    """
    from drift.markets.normalization import materialize_observation_decision

    harness = NormalizationHarness(
        source_only=True,
        numeric_values=("100.00", "101.00", "99.00", "100.00", "1000"),
    )
    query = harness.normalization_query("source_basis")
    result = harness.normalize(query)
    return materialize_observation_decision(result.reference, query, harness.context)


def _restated_view(
    *,
    role: str,
    observation: object,
    security_id: UUID7,
    listing_id: UUID7,
    source_day: date,
    open_price: str,
    close_price: str,
) -> DerivedObservationViewV1:
    template = _template_view()
    query = NormalizationQueryV1.model_construct(
        **(dict(template.query) | {"observation": observation})
    )
    values = {
        "open": Decimal(open_price),
        "high": Decimal(close_price),
        "low": Decimal(open_price),
        "close": Decimal(close_price),
        "volume": Decimal("1000"),
    }
    fields = tuple(
        item.model_copy(update={"source_value": values[item.field_name]})
        for item in template.fields
    )
    draft = DerivedObservationViewV1.model_construct(
        **(
            dict(template)
            | {
                "role": role,
                "query": query,
                "query_hash": content_hash(query),
                "source_session": _key(source_day),
                "listing_id": listing_id,
                "security_id": security_id,
                "fields": fields,
            }
        )
    )
    sealed = DerivedObservationViewV1.model_construct(
        **(dict(draft) | {"output_hash": derived_view_output_hash(draft)})
    )
    return DerivedObservationViewV1.model_validate(dict(sealed))


def _decision_view(
    security_id: UUID7,
    day: date,
    *,
    listing_id: UUID7 | None = None,
    source_day: date | None = None,
    decision_cutoff: datetime | None = None,
) -> DerivedObservationViewV1:
    """A decision-role source-basis view answerable exactly at a session close."""
    source = day if source_day is None else source_day
    cutoff = _close_of(day) if decision_cutoff is None else decision_cutoff
    listing = LISTING_A if listing_id is None else listing_id
    open_price, close_price = PRICES[security_id][source]
    observation = _template_view().query.observation.model_copy(
        update={
            "security_id": security_id,
            "listing_id": listing,
            "session_date": source,
            "decision_time": cutoff,
            "knowledge_cutoff": cutoff,
            "effective_cutoff": cutoff,
        }
    )
    return _restated_view(
        role="decision",
        observation=observation,
        security_id=security_id,
        listing_id=listing,
        source_day=source,
        open_price=open_price,
        close_price=close_price,
    )


def _accounting_view(
    security_id: UUID7,
    day: date,
    *,
    listing_id: UUID7 | None = None,
    open_price: str | None = None,
    close_price: str | None = None,
) -> DerivedObservationViewV1:
    """An outcome-role source-basis accounting view for one session."""
    listing = LISTING_A if listing_id is None else listing_id
    default_open, default_close = PRICES[security_id][day]
    base = dict(_template_view().query.observation)
    for field in ("kind", "decision_time", "knowledge_cutoff", "effective_cutoff"):
        base.pop(field, None)
    horizon = _close_of(day)
    observation = ObservationOutcomeQueryV1(
        **(
            base
            | {
                "kind": "outcome",
                "security_id": security_id,
                "listing_id": listing,
                "session_date": day,
                "economic_horizon": horizon,
                "evidence_vintage_cutoff": horizon,
            }
        )
    )
    return _restated_view(
        role="outcome",
        observation=observation,
        security_id=security_id,
        listing_id=listing,
        source_day=day,
        open_price=default_open if open_price is None else open_price,
        close_price=default_close if close_price is None else close_price,
    )


# --- structural eligibility --------------------------------------------


def _eligibility(
    security_id: UUID7,
    listing_id: UUID7,
    *,
    classification: StructuralEligibilityClassification = (
        StructuralEligibilityClassification.ELIGIBLE
    ),
    knowledge_cutoff: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    resolution_mode: ResolutionMode = ResolutionMode.AS_KNOWN,
) -> StructuralEligibilityResultV1:
    definition_hash = H["7"]
    methodology_id = "synthetic-universe-v1"
    subject_hash = content_hash(
        {
            "definition_hash": definition_hash,
            "issuer_id": ISSUER,
            "security_id": security_id,
            "listing_id": listing_id,
            "methodology_id": methodology_id,
        }
    )
    query = NormalizedSelectionQueryV1(
        schema_version="1",
        purpose=M1bSelectionPurpose.STRUCTURAL_ELIGIBILITY,
        information_role=(
            InformationRole.DECISION_INFORMATION
            if resolution_mode is ResolutionMode.AS_KNOWN
            else InformationRole.EX_POST_OUTCOME
        ),
        resolution_mode=resolution_mode,
        subject_hash=subject_hash,
        source_manifest_hash=H["1"],
        validation_decision_hash=H["2"],
        context_bundle_hashes=(H["3"], H["4"]),
        dataset_role_hash=H["5"],
        record_contract_hash=H["6"],
        schema_hash=H["8"],
        knowledge_cutoff=knowledge_cutoff,
        evaluation_time=knowledge_cutoff,
        requested_channel=_template_view().query.observation.requested_channel,
        policy_id="synthetic-universe-policy",
        policy_hash=H["9"],
    )
    values: dict[str, Any] = {
        "schema_version": "1",
        "issuer_id": ISSUER,
        "security_id": security_id,
        "listing_id": listing_id,
        "methodology_id": methodology_id,
        "definition_hash": definition_hash,
        "classification": classification,
        "reasons": ("synthetic",),
        "normalized_query": query,
        "identity_bundle_hash": H["3"],
        "universe_bundle_hash": H["4"],
        "identity_assignment_resolution_hashes": (H["a"], H["b"], H["c"]),
        "identity_resolution_hashes": (H["d"], H["e"]),
        "classification_resolution_hash": H["f"],
        "primary_listing_resolution_hash": H["0"],
        "lifecycle_resolution_hash": H["1"],
        "membership_resolution_hash": H["2"],
        "selection_proof_hashes": (H["5"],),
        "outcome_binding_hash": H["0"],
    }
    binding = content_hash(
        StructuralEligibilityResultV1.model_construct(**values).model_dump(
            mode="python", exclude={"outcome_binding_hash"}
        )
    )
    return StructuralEligibilityResultV1.model_validate(
        values | {"outcome_binding_hash": binding}
    )


# --- listing role evidence ---------------------------------------------


def _role_record(
    security_id: UUID7, listing_id: UUID7, *, suffix: int
) -> ListingRoleVersionV1:
    return ListingRoleVersionV1(
        schema_version="1",
        revision=revision(suffix),
        security_id=security_id,
        listing_id=listing_id,
        role=ListingRole.PRIMARY,
        methodology_id="synthetic-primary-v1",
        methodology_version="1",
        effective_interval=TemporalIntervalClaimV1(
            schema_version="1",
            start=boundary_at(datetime(2020, 1, 2, 14, 30, tzinfo=UTC), suffix + 100),
            end=None,
        ),
    )


ROLE_RECORDS = (
    _role_record(SEC_A, LISTING_A, suffix=900),
    _role_record(SEC_B, LISTING_B, suffix=920),
)

LISTINGS = (
    ListingV1(schema_version="1", listing_id=LISTING_A, venue=ListingVenue.XNYS),
    ListingV1(schema_version="1", listing_id=LISTING_B, venue=ListingVenue.XNYS),
)

SECURITIES = (
    SecurityV1(schema_version="1", security_id=SEC_A),
    SecurityV1(schema_version="1", security_id=SEC_B),
)


# --- protocol, costs, admission, bundle ---------------------------------


def _protocol(*, warmup: int = 2, cash: str = "10000.00") -> EvaluationProtocolV1:
    draft = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="task6-protocol-v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=warmup,
        initial_cash=Decimal(cash),
        protocol_hash=H["0"],
    )
    return draft.model_copy(update={"protocol_hash": evaluation_protocol_hash(draft)})


def _cost_model(
    *,
    model_id: str = "task6-zero-cost-v1",
    commission: str = "0.00",
    fixed_fee: str = "0.00",
    notional_bps: str = "0",
    slippage_bps: str = "0",
) -> EvaluationCostModelV1:
    draft = EvaluationCostModelV1.model_construct(
        schema_version="1",
        model_id=model_id,
        commission_per_share=Decimal(commission),
        fixed_fee_per_order=Decimal(fixed_fee),
        notional_fee_basis_points=Decimal(notional_bps),
        adverse_slippage_basis_points=Decimal(slippage_bps),
        cost_model_hash=H["0"],
    )
    return draft.model_copy(
        update={"cost_model_hash": evaluation_cost_model_hash(draft)}
    )


def _interval() -> TemporalIntervalClaimV1:
    return TemporalIntervalClaimV1(schema_version="1", start=exact_boundary(), end=None)


def _bundle(
    *,
    days: Sequence[date] = DAYS,
    decision_views: tuple[DerivedObservationViewV1, ...] | None = None,
    accounting_views: tuple[DerivedObservationViewV1, ...] | None = None,
    eligibilities: tuple[StructuralEligibilityResultV1, ...] | None = None,
    economic_outcomes: tuple[Any, ...] = (),
) -> EvaluationInputBundleV1:
    decision = (
        tuple(_decision_view(SEC_A, day) for day in days[1:])
        if decision_views is None
        else decision_views
    )
    accounting = (
        tuple(_accounting_view(SEC_A, day) for day in days)
        if accounting_views is None
        else accounting_views
    )
    universe = (
        (_eligibility(SEC_A, LISTING_A),) if eligibilities is None else eligibilities
    )
    return assemble_evaluation_input_bundle(
        evaluation_interval=_interval(),
        session_clock=_clock(days),
        security_identities=SECURITIES,
        listing_identities=LISTINGS,
        structural_eligibilities=universe,
        economic_outcomes=economic_outcomes,
        authentic_decision_views=decision,
        authentic_accounting_views=accounting,
    )


def _admission(bundle: EvaluationInputBundleV1) -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=bundle.bundle_hash,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash=H["0"],
    )
    candidate = draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )
    return ExploratoryEvaluationAdmissionV1.model_validate(candidate.model_dump())


def _run_identity(
    *,
    admission: EvaluationAdmissionV1,
    bundle: EvaluationInputBundleV1,
    protocol: EvaluationProtocolV1,
    cost_model: EvaluationCostModelV1,
    evidence_hash: str,
    strategy_hash: str = STRATEGY_CODE_HASH,
) -> EvaluationRunIdentityV1:
    return build_evaluation_run_identity(
        strategy_hash=strategy_hash,
        protocol_hash=protocol.protocol_hash,
        cost_model_hash=cost_model.cost_model_hash,
        admission=admission,
        bundle=bundle,
        evaluator_evidence_hash=evidence_hash,
        code_version_hash=CODE_VERSION_HASH,
        environment_closure_hash=ENVIRONMENT_HASH,
    )


# --- runtime strategy ---------------------------------------------------


STRATEGY_REFERENCE = StrategyReference(
    strategy_id=uid(700),
    strategy_version="1",
    code_hash=STRATEGY_CODE_HASH,
    artifact_reference=ArtifactReference(
        artifact_id=uid(701),
        kind=ArtifactKind.STRATEGY,
        content_hash=STRATEGY_CODE_HASH,
        location=f"drift+sha256://{STRATEGY_CODE_HASH}",
    ),
)


class FixedTargetStrategy:
    """A deterministic strategy emitting a pinned target set per session."""

    def __init__(self, targets: Mapping[date, tuple[tuple[UUID, int], ...]]) -> None:
        self.targets = targets
        self.seen: list[StrategyDecisionContextV1] = []

    @property
    def strategy_reference(self) -> StrategyReference:
        return STRATEGY_REFERENCE

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        self.seen.append(context)
        requested = self.targets.get(context.session_key.local_date, ())
        return StrategyDecisionIntentV1(
            session_key=context.session_key,
            decision_time=context.decision_cutoff,
            targets=tuple(
                SecurityTargetPositionV1(
                    security_id=security_id, target_quantity=quantity
                )
                for security_id, quantity in requested
            ),
        )


def _buy_ten() -> FixedTargetStrategy:
    return FixedTargetStrategy(
        {DAY_1: ((SEC_A, 10),), DAY_2: ((SEC_A, 10),), DAY_3: ((SEC_A, 10),)}
    )


def _engine(
    *,
    bundle: EvaluationInputBundleV1 | None = None,
    protocol: EvaluationProtocolV1 | None = None,
    cost_model: EvaluationCostModelV1 | None = None,
    evidence: SessionEvaluatorEvidence | None = None,
) -> SessionEvaluatorEngine:
    resolved_bundle = _bundle() if bundle is None else bundle
    return SessionEvaluatorEngine(
        bundle=resolved_bundle,
        admission=_admission(resolved_bundle),
        protocol=_protocol() if protocol is None else protocol,
        cost_model=_cost_model() if cost_model is None else cost_model,
        evidence=(
            SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS)
            if evidence is None
            else evidence
        ),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )


def _run(
    engine: SessionEvaluatorEngine,
    strategy: FixedTargetStrategy | None = None,
) -> EvaluationRunArtifactsV2:
    return engine.run(
        strategy=_buy_ten() if strategy is None else strategy,
        run_identity=_run_identity(
            admission=engine.admission,
            bundle=engine.bundle,
            protocol=engine.protocol,
            cost_model=engine.cost_model,
            evidence_hash=engine.evaluator_evidence_hash,
        ),
    )


# --- source-basis price bridge -----------------------------------------


def test_price_bridge_reads_the_exact_source_value_of_a_genuine_m1d_view() -> None:
    view = _template_view()

    assert view.basis_mode == "source_basis"
    assert source_basis_price(view, "open") == Decimal("100.00")
    assert source_basis_price(view, "close") == Decimal("100.00")


def test_price_bridge_refuses_a_split_normalized_view() -> None:
    from drift.markets.normalization import materialize_observation_decision

    harness = NormalizationHarness(outer_kind="decision")
    query = harness.normalization_query(
        "split_normalized", anchor_date=date(2026, 11, 30)
    )
    result = harness.normalize(query)
    view = materialize_observation_decision(result.reference, query, harness.context)

    with pytest.raises(
        IndeterminateValuationError, match="require source basis evidence"
    ):
        source_basis_price(view, "close")


def test_price_bridge_refuses_a_non_identity_transform_factor() -> None:
    view = _template_view()
    scaled = tuple(
        item.model_copy(
            update={
                "exact_factor": item.exact_factor.model_copy(
                    update={"denominator": "2"}
                )
            }
        )
        if item.field_name == "close"
        else item
        for item in view.fields
    )
    forged = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"fields": scaled})
    )

    with pytest.raises(IndeterminateValuationError, match="identity transform"):
        source_basis_price(forged, "close")


def test_price_bridge_refuses_a_non_positive_price() -> None:
    view = _template_view()
    zeroed = tuple(
        item.model_copy(update={"source_value": Decimal("0.00")})
        if item.field_name == "close"
        else item
        for item in view.fields
    )
    forged = DerivedObservationViewV1.model_construct(
        **(dict(view) | {"fields": zeroed})
    )

    with pytest.raises(IndeterminateValuationError, match="strictly positive"):
        source_basis_price(forged, "close")


# --- engine construction guards -----------------------------------------


def test_engine_requires_the_admission_to_admit_its_bundle() -> None:
    bundle = _bundle()
    other = _bundle(days=DAYS[:3])

    with pytest.raises(ValueError, match="admission must admit this exact bundle"):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=_admission(other),
            protocol=_protocol(),
            cost_model=_cost_model(),
            evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )


def test_engine_requires_a_session_beyond_the_warmup_window() -> None:
    bundle = _bundle(days=DAYS[:2])

    with pytest.raises(ValueError, match="requires at least one non-warmup session"):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=_admission(bundle),
            protocol=_protocol(warmup=2),
            cost_model=_cost_model(),
            evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )


def test_engine_accepts_exactly_one_session_beyond_the_warmup_window() -> None:
    bundle = _bundle(days=DAYS[:3])

    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=_admission(bundle),
        protocol=_protocol(warmup=2),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )

    assert engine.protocol.warmup_session_count == 2


def test_engine_requires_a_run_identity_bound_to_its_own_admission() -> None:
    engine = _engine()
    other_bundle = _bundle(days=DAYS[:3])
    foreign = _run_identity(
        admission=_admission(other_bundle),
        bundle=other_bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )

    with pytest.raises(ValueError, match="run identity must bind this evaluation"):
        engine.run(strategy=_buy_ten(), run_identity=foreign)


def test_engine_requires_a_run_identity_bound_to_its_own_cost_model() -> None:
    engine = _engine()
    foreign = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=_cost_model(model_id="task6-other-cost-v1"),
        evidence_hash=engine.evaluator_evidence_hash,
    )

    with pytest.raises(ValueError, match="run identity must bind this evaluation"):
        engine.run(strategy=_buy_ten(), run_identity=foreign)


# --- the promotion lane is disabled (issue 79 ruling) --------------------

PROMOTION_LANE_DISABLED = r"^the promotion lane is disabled \(issue 79 ruling\): "


def _promotion_admission(
    bundle: EvaluationInputBundleV1,
) -> PromotionEvaluationAdmissionV1:
    """The F1 admission: invented M1e and proof hashes, bound to this bundle."""
    from exploratory_decision_test_support import promotion_admission

    return promotion_admission(bundle)


def _construct(
    bundle: EvaluationInputBundleV1,
    admission: EvaluationAdmissionV1,
    *,
    protocol: EvaluationProtocolV1 | None = None,
) -> SessionEvaluatorEngine:
    return SessionEvaluatorEngine(
        bundle=bundle,
        admission=admission,
        protocol=_protocol() if protocol is None else protocol,
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(listing_role_records=ROLE_RECORDS),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )


def _bypassed_promotion_engine() -> SessionEvaluatorEngine:
    """An engine in exactly the state 19c15f8 built for a promotion admission.

    Construction refuses one now, so the state is reached by swapping the
    admitted lane of a genuine exploratory engine over the same realized
    bundle. Nothing else differs: over a bundle without reconstructions both
    lanes resolve no reconstructed lane, and only the mark grade follows the
    admission.
    """
    engine = _engine()
    engine._admission = _promotion_admission(engine.bundle)
    engine._mark_grade = "promotion_grade"
    return engine


def test_engine_refuses_a_promotion_admission_at_construction() -> None:
    bundle = _bundle()

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "engine construction refuses",
    ):
        _construct(bundle, _promotion_admission(bundle))

    # Control: the exploratory admission of the same bundle constructs.
    assert _construct(bundle, _admission(bundle)).admission.lane == "exploratory"


def test_the_promotion_refusal_precedes_every_other_construction_guard() -> None:
    """The refusal reads the admission alone, never the bundle it names.

    The bundle here fails its own revalidation, and the admission binds a
    different bundle. Either would be refused on its own; the promotion lane
    is refused first.
    """
    bundle = _bundle()
    corrupt = EvaluationInputBundleV1.model_construct(
        **(dict(bundle) | {"bundle_hash": "0" * 64})
    )
    with pytest.raises(ValidationError):
        _construct(corrupt, _admission(bundle))

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "engine construction refuses",
    ):
        _construct(corrupt, _promotion_admission(_bundle(days=DAYS[:3])))


def test_engine_refuses_a_promotion_admission_disguised_as_exploratory() -> None:
    """Revalidation cannot turn an admitted exploratory object into promotion.

    The disguised object is an exploratory admission by class and by lane, so
    only the refusal after revalidation can see the promotion admission its
    dump rebuilds into.
    """
    bundle = _bundle()
    promotion = _promotion_admission(bundle)

    class _Disguised(ExploratoryEvaluationAdmissionV1):
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return promotion.model_dump(*args, **kwargs)

    disguised = _Disguised.model_construct(**dict(_admission(bundle)))
    assert disguised.lane == "exploratory"

    with pytest.raises(
        PromotionLaneDisabledError,
        match=(
            PROMOTION_LANE_DISABLED
            + "engine construction on the revalidated admission refuses"
        ),
    ):
        _construct(bundle, disguised)


def test_engine_refuses_the_promotion_lane_by_type_and_by_declared_lane() -> None:
    """A relabelled object meets the named refusal, not a later validation error.

    One is a promotion admission declaring the exploratory lane, the other an
    exploratory admission declaring the promotion lane. Revalidation would
    refuse either with a validation error; the lane refusal names them first.
    """
    bundle = _bundle()
    by_type = PromotionEvaluationAdmissionV1.model_construct(
        **(dict(_promotion_admission(bundle)) | {"lane": "exploratory"})
    )
    by_lane = ExploratoryEvaluationAdmissionV1.model_construct(
        **(dict(_admission(bundle)) | {"lane": "promotion"})
    )

    for relabelled in (by_type, by_lane):
        with pytest.raises(
            PromotionLaneDisabledError,
            match=PROMOTION_LANE_DISABLED + "engine construction refuses",
        ):
            _construct(bundle, relabelled)


def test_an_engine_run_refuses_a_promotion_admission_before_any_session() -> None:
    engine = _bypassed_promotion_engine()
    strategy = _buy_ten()

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "an engine run refuses",
    ):
        _run(engine, strategy)

    # No session was stepped, so no decision was taken and nothing filled.
    assert strategy.seen == []


def test_result_sealing_refuses_a_promotion_admission() -> None:
    """The last guard: no promotion result is sealed even past the run guard."""
    genuine = _run(_engine())
    engine = _bypassed_promotion_engine()
    identity = _run_identity(
        admission=engine.admission,
        bundle=engine.bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )

    with pytest.raises(
        PromotionLaneDisabledError,
        match=PROMOTION_LANE_DISABLED + "result sealing refuses",
    ):
        engine._seal_result(
            run_identity=identity,
            halt=None,
            metrics=genuine.result.metrics,
            trace=genuine.trace,
        )


def test_the_promotion_lane_error_is_a_value_error_naming_its_prerequisites() -> None:
    engine = _bypassed_promotion_engine()

    with pytest.raises(ValueError) as error:
        _run(engine)

    assert isinstance(error.value, PromotionLaneDisabledError)
    assert str(error.value).endswith(
        "re-enabling it requires every prerequisite in issue 115"
    )


# --- complete five-phase run --------------------------------------------


def test_complete_run_executes_every_phase_and_classifies_complete() -> None:
    artifacts = _run(_engine())

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.halted_session_index is None
    assert artifacts.result.halt_reason is None
    assert artifacts.result.metrics.evaluated_session_count == 4


def test_complete_run_marks_every_session_in_the_equity_series() -> None:
    artifacts = _run(_engine())

    series = artifacts.result.metrics.equity_series
    assert tuple(point.session_key.local_date for point in series) == DAYS
    assert tuple(point.session_index for point in series) == (0, 1, 2, 3)


def test_complete_run_books_the_single_funded_buy_at_the_unadjusted_open() -> None:
    artifacts = _run(_engine())

    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert len(fills) == 1
    assert fills[0].fill.side == "buy"
    assert fills[0].fill.quantity == 10
    assert fills[0].fill.unadjusted_open_price == Decimal("100.00")
    assert fills[0].fill.listing_id == LISTING_A


def test_complete_run_reports_exact_terminal_metrics() -> None:
    metrics = _run(_engine()).result.metrics

    assert metrics.initial_cash == Decimal("10000.00")
    assert metrics.ending_cash == Decimal("9000.00")
    assert metrics.ending_net_asset_value == Decimal("10200.00")
    assert metrics.net_profit_and_loss == Decimal("200.00")
    assert metrics.gross_traded_notional == Decimal("1000.00")
    assert metrics.committed_fill_count == 1
    assert metrics.cumulative_transaction_costs == Decimal("0")


def test_warmup_defers_the_first_decision_to_session_w_minus_one() -> None:
    strategy = _buy_ten()
    _run(_engine(), strategy)

    assert [context.session_key.local_date for context in strategy.seen] == [
        DAY_1,
        DAY_2,
        DAY_3,
    ]


def test_warmup_defers_the_first_execution_to_session_w() -> None:
    artifacts = _run(_engine())

    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [event.session_index for event in fills] == [2]


def test_decision_context_is_anchored_to_the_session_close() -> None:
    strategy = _buy_ten()
    _run(_engine(), strategy)

    first = strategy.seen[0]
    assert first.decision_cutoff == _close_of(DAY_1)
    assert first.decision_session.session_key == _key(DAY_1)


def test_decision_context_carries_the_admitted_universe() -> None:
    strategy = _buy_ten()
    _run(_engine(), strategy)

    assert strategy.seen[0].admitted_universe == (SEC_A,)


def test_ineligible_securities_stay_out_of_the_admitted_universe() -> None:
    bundle = _bundle(
        eligibilities=(
            _eligibility(SEC_A, LISTING_A),
            _eligibility(
                SEC_B,
                LISTING_B,
                classification=StructuralEligibilityClassification.INDETERMINATE,
            ),
        )
    )
    strategy = _buy_ten()
    _run(_engine(bundle=bundle), strategy)

    assert strategy.seen[0].admitted_universe == (SEC_A,)


def test_trace_opens_one_session_start_per_evaluated_session() -> None:
    artifacts = _run(_engine())

    starts = [
        event for event in artifacts.trace.events if event.kind == "session_start"
    ]
    assert [event.session_index for event in starts] == [0, 1, 2, 3]


def test_trace_records_one_mark_per_evaluated_session() -> None:
    artifacts = _run(_engine())

    marks = [event for event in artifacts.trace.events if event.kind == "session_mark"]
    assert [event.net_asset_value for event in marks] == [
        Decimal("10000.00"),
        Decimal("10000.00"),
        Decimal("10100.00"),
        Decimal("10200.00"),
    ]


def test_trace_emits_no_corporate_action_event_without_a_mutation() -> None:
    artifacts = _run(_engine())

    assert not [
        event
        for event in artifacts.trace.events
        if event.kind == "corporate_action_applied"
    ]


def test_result_binds_the_trace_it_hashes() -> None:
    artifacts = _run(_engine())

    assert artifacts.result.trace_hash == artifacts.trace.trace_hash


def test_result_is_exploratory_and_not_promotion_grade_evidence() -> None:
    result = _run(_engine()).result

    assert result.lane == "exploratory"
    assert result.is_promotion_grade_evidence is False
    assert result.result_id == result.result_hash


def test_exploratory_marks_never_claim_promotion_grade_evidence() -> None:
    artifacts = _run(_engine())
    final = artifacts.result

    assert final.classification is EvaluationClassification.COMPLETE
    # The mark grade is taken from the admitted lane, so an exploratory run
    # cannot mint a promotion-grade valuation.
    assert artifacts.final_state.mark is not None
    assert {price.evidence.grade for price in artifacts.final_state.mark.prices} == {
        "exploratory"
    }


# --- replay determinism --------------------------------------------------


def test_identical_inputs_reproduce_identical_trace_and_result_hashes() -> None:
    first = _run(_engine())
    second = _run(_engine())

    assert first.trace.trace_hash == second.trace.trace_hash
    assert first.result.result_hash == second.result.result_hash


def test_a_changed_price_changes_the_result_hash() -> None:
    baseline = _run(_engine())
    shifted_views = tuple(
        _accounting_view(SEC_A, day, close_price="130.00")
        if day == DAY_3
        else _accounting_view(SEC_A, day)
        for day in DAYS
    )
    shifted = _run(_engine(bundle=_bundle(accounting_views=shifted_views)))

    assert baseline.result.result_hash != shifted.result.result_hash


# --- fatal indeterminacy --------------------------------------------------


def test_missing_open_price_halts_stepping_and_classifies_indeterminate() -> None:
    views = tuple(_accounting_view(SEC_A, day) for day in DAYS if day != DAY_2)
    artifacts = _run(_engine(bundle=_bundle(accounting_views=views)))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2
    assert artifacts.result.metrics.evaluated_session_count == 2


def test_missing_open_price_records_its_cause_in_the_trace() -> None:
    views = tuple(_accounting_view(SEC_A, day) for day in DAYS if day != DAY_2)
    artifacts = _run(_engine(bundle=_bundle(accounting_views=views)))

    causes = [
        event for event in artifacts.trace.events if event.kind == "indeterminate_cause"
    ]
    assert len(causes) == 1
    assert causes[0].phase.value == "open_execution"


def test_missing_close_price_for_a_held_position_fails_closed() -> None:
    views = (
        _accounting_view(SEC_A, DAY_0),
        _accounting_view(SEC_A, DAY_1),
        _accounting_view(SEC_A, DAY_2),
    )
    artifacts = _run(
        _engine(
            bundle=_bundle(accounting_views=views + (_accounting_view(SEC_B, DAY_3),))
        )
    )

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 3


def test_ambiguous_accounting_evidence_fails_closed() -> None:
    duplicated = tuple(_accounting_view(SEC_A, day) for day in DAYS) + (
        _accounting_view(SEC_A, DAY_2, close_price="111.00"),
    )
    artifacts = _run(_engine(bundle=_bundle(accounting_views=duplicated)))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halt_reason is not None
    assert "more than one" in artifacts.result.halt_reason


def test_a_decision_session_without_decision_evidence_fails_closed() -> None:
    bundle = _bundle(decision_views=(_decision_view(SEC_A, DAY_1),))
    artifacts = _run(_engine(bundle=bundle))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2


def test_a_price_bound_to_another_listing_fails_closed() -> None:
    views = tuple(
        _accounting_view(SEC_A, day, listing_id=LISTING_B)
        if day == DAY_2
        else _accounting_view(SEC_A, day)
        for day in DAYS
    )
    artifacts = _run(_engine(bundle=_bundle(accounting_views=views)))

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2


def test_an_unresolvable_execution_listing_fails_closed() -> None:
    engine = _engine(
        evidence=SessionEvaluatorEvidence(listing_role_records=(ROLE_RECORDS[1],))
    )
    artifacts = _run(engine)

    assert artifacts.result.classification is EvaluationClassification.INDETERMINATE
    assert artifacts.result.halted_session_index == 2


# --- rejection ------------------------------------------------------------


def test_unfunded_rebalance_commits_zero_fills_and_classifies_rejected() -> None:
    strategy = FixedTargetStrategy({DAY_1: ((SEC_A, 1000),)})
    artifacts = _run(_engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halted_session_index == 2
    assert artifacts.result.metrics.committed_fill_count == 0
    assert artifacts.final_state.holdings == ()


def test_unfunded_rebalance_records_its_shortfall_in_the_trace() -> None:
    strategy = FixedTargetStrategy({DAY_1: ((SEC_A, 1000),)})
    artifacts = _run(_engine(), strategy)

    rejections = [
        event for event in artifacts.trace.events if event.kind == "fill_rejection"
    ]
    assert len(rejections) == 1
    assert rejections[0].rejection.cash_shortfall == Decimal("90000.00")


def test_unfunded_rebalance_halts_every_later_session() -> None:
    strategy = FixedTargetStrategy({DAY_1: ((SEC_A, 1000),)})
    artifacts = _run(_engine(), strategy)

    starts = [
        event for event in artifacts.trace.events if event.kind == "session_start"
    ]
    assert [event.session_index for event in starts] == [0, 1, 2]


def test_an_unadmitted_entry_is_rejected_rather_than_executed() -> None:
    strategy = FixedTargetStrategy({DAY_1: ((SEC_B, 1),)})
    artifacts = _run(_engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halted_session_index == 1
    decisions = [
        event for event in artifacts.trace.events if event.kind == "strategy_decision"
    ]
    assert decisions[-1].outcome == "rejected"
    assert decisions[-1].staged_targets == ()


def test_a_zero_target_for_an_unadmitted_security_stays_permitted() -> None:
    strategy = FixedTargetStrategy(
        {
            DAY_1: ((SEC_A, 10), (SEC_B, 0)),
            DAY_2: ((SEC_A, 10), (SEC_B, 0)),
            DAY_3: ((SEC_A, 10), (SEC_B, 0)),
        }
    )
    artifacts = _run(_engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    assert artifacts.result.metrics.committed_fill_count == 1


def test_omitting_a_held_security_liquidates_it_at_the_next_open() -> None:
    strategy = FixedTargetStrategy({DAY_1: ((SEC_A, 10),), DAY_2: (), DAY_3: ()})
    artifacts = _run(_engine(), strategy)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [event.fill.side for event in fills] == ["buy", "sell"]
    assert fills[1].fill.unadjusted_open_price == Decimal("110.00")
    assert artifacts.final_state.holdings == ()


def test_a_commit_failure_is_a_fatal_halt_and_not_a_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from drift.evaluator import execution as execution_module

    def _explode(
        self: object, *, state: PortfolioStateV2, plan: RebalancePlanV1
    ) -> None:
        raise AtomicRebalanceCommitError("funded rebalance could not be booked")

    monkeypatch.setattr(
        execution_module.AtomicRebalanceEngine, "execute", _explode, raising=True
    )

    with pytest.raises(AtomicRebalanceCommitError):
        _run(_engine())


def test_a_strategy_failure_is_not_laundered_into_a_classification() -> None:
    class _Exploding(FixedTargetStrategy):
        def decide(
            self, context: StrategyDecisionContextV1
        ) -> StrategyDecisionIntentV1:
            raise RuntimeError("strategy defect")

    with pytest.raises(RuntimeError, match="strategy defect"):
        _run(_engine(), _Exploding({}))


# --- economic outcome binding --------------------------------------------


def test_engine_refuses_economic_evidence_its_bundle_does_not_carry() -> None:
    from test_evaluator_corporate_actions import _outcome

    outcome = _outcome(security_id=SEC_A)
    bundle = _bundle()

    with pytest.raises(ValueError, match="bundle does not carry"):
        SessionEvaluatorEngine(
            bundle=bundle,
            admission=_admission(bundle),
            protocol=_protocol(),
            cost_model=_cost_model(),
            evidence=SessionEvaluatorEvidence(
                listing_role_records=ROLE_RECORDS, economic_outcomes=(outcome,)
            ),
            book_currency_namespace=BOOK_NAMESPACE,
            book_currency_code=BOOK_CODE,
        )


# --- as-of admitted universe ---------------------------------------------


def test_an_eligibility_known_after_a_decision_stays_out_of_its_universe() -> None:
    """A security first known eligible later is not backdated into the set."""
    bundle = _bundle(
        eligibilities=(
            _eligibility(SEC_A, LISTING_A),
            _eligibility(SEC_B, LISTING_B, knowledge_cutoff=_close_of(DAY_2)),
        )
    )
    strategy = _buy_ten()
    _run(_engine(bundle=bundle), strategy)

    seen = {context.session_key.local_date: context for context in strategy.seen}
    assert seen[DAY_1].admitted_universe == (SEC_A,)
    assert seen[DAY_2].admitted_universe == (SEC_A, SEC_B)


def test_a_current_interpretation_eligibility_never_admits_a_security() -> None:
    """An ex-post universe reading cannot define a past decision's universe."""
    bundle = _bundle(
        eligibilities=(
            _eligibility(SEC_A, LISTING_A),
            _eligibility(
                SEC_B,
                LISTING_B,
                resolution_mode=ResolutionMode.CURRENT_INTERPRETATION,
            ),
        )
    )
    strategy = _buy_ten()
    _run(_engine(bundle=bundle), strategy)

    assert strategy.seen[0].admitted_universe == (SEC_A,)


def test_an_entry_into_a_not_yet_known_security_is_rejected() -> None:
    bundle = _bundle(
        eligibilities=(
            _eligibility(SEC_A, LISTING_A),
            _eligibility(SEC_B, LISTING_B, knowledge_cutoff=_close_of(DAY_2)),
        )
    )
    strategy = FixedTargetStrategy({DAY_1: ((SEC_B, 1),)})
    artifacts = _run(_engine(bundle=bundle), strategy)

    assert artifacts.result.classification is EvaluationClassification.REJECTED
    assert artifacts.result.halted_session_index == 1


# --- result artifact invariants --------------------------------------------


def _reseal_result(
    result: ExploratoryEvaluationResultV1, **changes: Any
) -> ExploratoryEvaluationResultV1:
    draft = ExploratoryEvaluationResultV1.model_construct(**(dict(result) | changes))
    sealed = ExploratoryEvaluationResultV1.model_construct(
        **(dict(draft) | {"result_hash": evaluation_result_hash(draft)})
    )
    return ExploratoryEvaluationResultV1.model_validate(dict(sealed))


def _unmarked_metrics() -> EvaluationSummaryMetricsV1:
    return EvaluationSummaryMetricsV1(
        evaluated_session_count=0,
        initial_cash=Decimal("10000.00"),
        initial_net_asset_value=Decimal("10000.00"),
        ending_cash=Decimal("10000.00"),
        ending_net_asset_value=Decimal("10000.00"),
        net_profit_and_loss=Decimal("0"),
        realized_gross_pnl=Decimal("0"),
        realized_net_pnl=Decimal("0"),
        cumulative_transaction_costs=Decimal("0"),
        gross_traded_notional=Decimal("0"),
        committed_fill_count=0,
        equity_series=(),
    )


def test_a_complete_result_requires_at_least_one_marked_session() -> None:
    result = _run(_engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)

    with pytest.raises(ValidationError, match="at least one marked session"):
        _reseal_result(result, metrics=_unmarked_metrics())


def test_a_halted_result_cannot_mark_more_sessions_than_it_stepped() -> None:
    result = _run(_engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)

    with pytest.raises(ValidationError, match="cannot mark more sessions"):
        _reseal_result(
            result,
            classification=EvaluationClassification.INDETERMINATE,
            halted_session_index=0,
            halt_reason="synthetic halt",
        )


def test_a_result_cannot_be_paired_with_a_trace_of_another_run() -> None:
    views = tuple(_accounting_view(SEC_A, day) for day in DAYS if day != DAY_2)
    halted = _run(_engine(bundle=_bundle(accounting_views=views)))
    complete = _run(_engine())
    assert isinstance(complete.result, ExploratoryEvaluationResultV1)
    forged = _reseal_result(complete.result, trace_hash=halted.trace.trace_hash)

    with pytest.raises(ValidationError, match="open exactly the sessions"):
        EvaluationRunArtifactsV2(
            result=forged, trace=halted.trace, final_state=complete.final_state
        )


def test_a_promotion_result_refuses_an_exploratory_admission() -> None:
    artifacts = _run(_engine())
    result = artifacts.result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    values = dict(result)
    values.pop("lane")
    values.pop("is_promotion_grade_evidence")

    with pytest.raises(ValidationError) as error:
        PromotionEvaluationResultV1.model_validate(values)

    assert any(entry["loc"] == ("admission",) for entry in error.value.errors())


# --- summary metrics invariants ---------------------------------------------


def _equity_point(
    index: int, day: date, cash: str, market: str
) -> SessionEquityPointV1:
    return SessionEquityPointV1(
        session_index=index,
        session_key=_key(day),
        cash_balance=Decimal(cash),
        holdings_market_value=Decimal(market),
        pending_claims_value=Decimal("0"),
        net_asset_value=Decimal(cash) + Decimal(market),
    )


def _metrics(**changes: Any) -> EvaluationSummaryMetricsV1:
    series = (
        _equity_point(0, DAY_0, "10000.00", "0"),
        _equity_point(1, DAY_1, "9000.00", "1100.00"),
    )
    values: dict[str, Any] = {
        "evaluated_session_count": 2,
        "initial_cash": Decimal("10000.00"),
        "initial_net_asset_value": Decimal("10000.00"),
        "ending_cash": Decimal("9000.00"),
        "ending_net_asset_value": Decimal("10100.00"),
        "net_profit_and_loss": Decimal("100.00"),
        "realized_gross_pnl": Decimal("0"),
        "realized_net_pnl": Decimal("0"),
        "cumulative_transaction_costs": Decimal("0"),
        "gross_traded_notional": Decimal("1000.00"),
        "committed_fill_count": 1,
        "equity_series": series,
    }
    values.update(changes)
    return EvaluationSummaryMetricsV1(**values)


def test_metrics_fixture_is_internally_consistent() -> None:
    assert _metrics().evaluated_session_count == 2


def test_metrics_session_count_must_match_the_equity_series() -> None:
    with pytest.raises(ValidationError, match="must equal the equity series length"):
        _metrics(evaluated_session_count=3)


def test_metrics_ending_cash_must_match_the_last_marked_session() -> None:
    with pytest.raises(ValidationError, match="ending cash must equal the last"):
        _metrics(
            ending_cash=Decimal("8000.00"),
            ending_net_asset_value=Decimal("10100.00"),
        )


def test_metrics_ending_value_must_match_the_last_marked_session() -> None:
    with pytest.raises(
        ValidationError, match="ending net asset value must equal the last"
    ):
        _metrics(
            ending_net_asset_value=Decimal("12000.00"),
            net_profit_and_loss=Decimal("2000.00"),
        )


def test_metrics_net_profit_and_loss_must_reconcile() -> None:
    with pytest.raises(ValidationError, match="net profit and loss must equal"):
        _metrics(net_profit_and_loss=Decimal("500.00"))


def test_metrics_turnover_requires_a_committed_fill() -> None:
    with pytest.raises(ValidationError, match="requires at least one committed fill"):
        _metrics(committed_fill_count=0)


def test_metrics_a_committed_fill_requires_positive_turnover() -> None:
    with pytest.raises(ValidationError, match="requires positive traded notional"):
        _metrics(gross_traded_notional=Decimal("0"))


def test_metrics_equity_series_must_run_contiguously_from_zero() -> None:
    with pytest.raises(ValidationError, match="must run contiguously from session"):
        _metrics(
            evaluated_session_count=1,
            equity_series=(_equity_point(1, DAY_1, "9000.00", "1100.00"),),
            ending_cash=Decimal("9000.00"),
            ending_net_asset_value=Decimal("10100.00"),
            net_profit_and_loss=Decimal("100.00"),
        )


def test_metrics_that_marked_no_session_must_end_where_it_started() -> None:
    with pytest.raises(ValidationError, match="ends at its initial cash"):
        _metrics(
            evaluated_session_count=0,
            equity_series=(),
            ending_cash=Decimal("9000.00"),
            ending_net_asset_value=Decimal("10000.00"),
            net_profit_and_loss=Decimal("0"),
            gross_traded_notional=Decimal("0"),
            committed_fill_count=0,
        )


def test_metrics_costs_must_be_non_negative() -> None:
    with pytest.raises(ValidationError, match="transaction costs must be non-negative"):
        _metrics(cumulative_transaction_costs=Decimal("-1.00"))


# --- result artifact hash and binding invariants -----------------------------


def test_a_halted_result_must_name_its_session_and_reason() -> None:
    result = _run(_engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)

    with pytest.raises(ValidationError, match="requires the session it halted on"):
        _reseal_result(result, classification=EvaluationClassification.INDETERMINATE)


def test_a_complete_result_cannot_declare_a_halt() -> None:
    result = _run(_engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)

    with pytest.raises(ValidationError, match="complete result cannot declare a halt"):
        _reseal_result(result, halted_session_index=3, halt_reason="synthetic")


def test_a_result_rejects_a_declared_hash_that_is_not_its_own() -> None:
    result = _run(_engine()).result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    forged = ExploratoryEvaluationResultV1.model_construct(
        **(dict(result) | {"result_hash": H["a"]})
    )

    with pytest.raises(ValidationError, match="result hash mismatch"):
        ExploratoryEvaluationResultV1.model_validate(dict(forged))


def test_a_result_run_identity_must_bind_its_own_admission() -> None:
    engine = _engine()
    result = _run(engine).result
    assert isinstance(result, ExploratoryEvaluationResultV1)
    other_bundle = _bundle(days=DAYS[:3])
    foreign = _run_identity(
        admission=_admission(other_bundle),
        bundle=other_bundle,
        protocol=engine.protocol,
        cost_model=engine.cost_model,
        evidence_hash=engine.evaluator_evidence_hash,
    )

    with pytest.raises(ValidationError, match="must bind the admission it carries"):
        _reseal_result(result, run_identity=foreign)


def test_artifacts_refuse_a_trace_the_result_does_not_hash() -> None:
    baseline = _run(_engine())
    shifted_views = tuple(
        _accounting_view(SEC_A, day, close_price="130.00")
        if day == DAY_3
        else _accounting_view(SEC_A, day)
        for day in DAYS
    )
    shifted = _run(_engine(bundle=_bundle(accounting_views=shifted_views)))
    assert baseline.trace.trace_hash != shifted.trace.trace_hash

    with pytest.raises(ValidationError, match="must bind the trace it is paired with"):
        EvaluationRunArtifactsV2(
            result=baseline.result,
            trace=shifted.trace,
            final_state=baseline.final_state,
        )


# --- phase 1 corporate actions ---------------------------------------------


def _forward_split_outcome(effective_at: str) -> Any:
    """A proven two-for-one forward split on the evaluated security."""
    from test_evaluator_corporate_actions import _effect, _outcome, _shares, _terms

    from drift.domain.economic_common import ActionKind

    component = _shares(
        numerator="2",
        denominator="1",
        component_id="split-shares",
        recipient=SEC_A,
        predecessor=SEC_A,
        meaning="resulting_per_predecessor",
    )
    terms = _terms(
        suffix=7100,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        security_id=SEC_A,
    )
    effect = _effect(
        suffix=7200,
        action_kind=ActionKind.FORWARD_SPLIT,
        components=(component,),
        terms=terms,
        occurrence_id="task6-split-1",
        effective_at=effective_at,
        security_id=SEC_A,
    )
    return _outcome(
        security_id=SEC_A,
        terms=(terms,),
        effects=(effect,),
        action_kinds=(ActionKind.FORWARD_SPLIT,),
    )


def _split_engine() -> tuple[SessionEvaluatorEngine, Any]:
    """An engine whose bundle carries a split effective on the final session."""
    outcome = _forward_split_outcome("2026-01-08T00:00:00Z")
    # The post-split session prints halved prices, so the split changes share
    # counts without inventing net asset value.
    views = (
        _accounting_view(SEC_A, DAY_0),
        _accounting_view(SEC_A, DAY_1),
        _accounting_view(SEC_A, DAY_2),
        _accounting_view(SEC_A, DAY_3, open_price="55.00", close_price="60.00"),
    )
    bundle = _bundle(accounting_views=views, economic_outcomes=(outcome.resolution,))
    engine = SessionEvaluatorEngine(
        bundle=bundle,
        admission=_admission(bundle),
        protocol=_protocol(),
        cost_model=_cost_model(),
        evidence=SessionEvaluatorEvidence(
            listing_role_records=ROLE_RECORDS, economic_outcomes=(outcome,)
        ),
        book_currency_namespace=BOOK_NAMESPACE,
        book_currency_code=BOOK_CODE,
    )
    return engine, outcome


def test_an_overnight_split_is_applied_exactly_once_per_session() -> None:
    engine, _ = _split_engine()

    artifacts = _run(engine)

    assert artifacts.result.classification is EvaluationClassification.COMPLETE
    # Ten shares held into a two-for-one split become twenty, never forty.
    assert [
        (holding.security_id, holding.quantity)
        for holding in artifacts.final_state.holdings
    ] == [(SEC_A, 20)]


def test_an_overnight_split_scales_the_staged_target() -> None:
    engine, _ = _split_engine()

    artifacts = _run(engine)

    applied = [
        event
        for event in artifacts.trace.events
        if event.kind == "corporate_action_applied"
    ]
    assert len(applied) == 1
    assert applied[0].session_index == 3
    assert [
        (target.security_id, target.target_quantity)
        for target in applied[0].staged_targets_before
    ] == [(SEC_A, 10)]
    assert [
        (target.security_id, target.target_quantity)
        for target in applied[0].staged_targets_after
    ] == [(SEC_A, 20)]


def test_a_split_scaled_target_commits_no_further_fill() -> None:
    engine, _ = _split_engine()

    artifacts = _run(engine)

    fills = [event for event in artifacts.trace.events if event.kind == "fill"]
    assert [event.session_index for event in fills] == [2]
    assert artifacts.result.metrics.committed_fill_count == 1


def test_a_split_preserves_net_asset_value_across_the_session() -> None:
    engine, _ = _split_engine()

    artifacts = _run(engine)

    marks = [event for event in artifacts.trace.events if event.kind == "session_mark"]
    # Twenty shares at the halved close of 60.00 against ten at 120.00.
    assert marks[-1].holdings_market_value == Decimal("1200.00")
    assert marks[-1].net_asset_value == Decimal("10200.00")
