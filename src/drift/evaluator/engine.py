"""The deterministic five-phase M2 session evaluator.

The engine steps an authority-bound session clock and, for each session, runs
the canonical phase order: pre-open corporate-action effects, next-open atomic
execution, intrasession settlement, close mark, and post-close decision. It
owns no evidence of its own. Every price, every session boundary, and every
economic effect comes from the input bundle it was constructed against, and
anything it cannot prove from that bundle fails closed.

Three halting rules are absolute:

* A fatal indeterminacy (a price, a listing, or an entitlement the evidence
  cannot settle) records its cause, stops session stepping, and classifies the
  run ``INDETERMINATE``.
* An unfunded rebalance, or an intent the strategy contract forbids, commits
  zero fills, stops session stepping, and classifies the run ``REJECTED``.
* A commit failure on an already-funded plan is a defect, not a scientific
  outcome. It propagates, so the M0 experiment run records ``FAILED`` rather
  than laundering a broken book into a classification.

Source-basis policy. Execution and accounting read **unadjusted source-basis**
prices, per the accepted architecture ruling. `EvaluationInputBundleV1` already
requires `basis_mode == "source_basis"` on accounting views; this module
carries that constraint across the view-to-price bridge in `source_basis_price`
by refusing any other basis, refusing a non-identity transform factor, and
reading `FieldTransformV1.source_value`. M1d materializes a source-basis view
with `exact_factor = 1/1` and leaves both `exact_transformed_value` and
`quantized_value` unset, so `source_value` is the only field that carries the
exact unadjusted native decimal; the other two would be a silent `None`.

Decision lanes (issue 46, the issue 42 adjudication of ADR 0012 Option B).
The post-close decision phase has exactly two lanes, fixed at construction.
The realized lane hands a `RuntimeStrategy` the strong
`StrategyDecisionContextV1` built from authentic decision views, unchanged. The
EXPLORATORY reconstructed lane is taken only by an exploratory admission over
a `scheduled_session_reconstruction` clock with its declared cohort, and hands
an `ExploratoryReconstructedRuntimeStrategy` the weaker
`ExploratoryStrategyDecisionContextV1` built from reconstructed observations.
A promotion admission is refused at construction over any bundle carrying
exploratory reconstructions. In the reconstructed lane, execution and marks
read EXPLORATORY accounting prices from the same re-derived reconstructions
(issue 54): the execution session's open fills, and each session's close marks.
The realized lane keeps reading authorized accounting views only.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from drift.domain.assertions import ResolutionMode
from drift.domain.common import UUID7
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
    EvaluationRunIdentityV1,
)
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_corporate_actions import (
    CashInLieuRateV1,
    DueBillRuleV1,
    SecurityEconomicOutcomeV1,
    TieBreakingRuleV1,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_execution import (
    IndeterminateExecutionError,
    ListingOpenPriceV1,
    positions_digest,
)
from drift.domain.evaluator_exploratory_accounting import (
    ExploratoryAccountingPriceRole,
    ExploratoryReconstructedAccountingPriceV1,
    reconstructed_accounting_price,
)
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryReconstructedRuntimeStrategy,
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
from drift.domain.evaluator_lanes import (
    EvaluationAdmissionV1,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    MarkEvidenceGrade,
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioStateV1,
    decimal_context,
)
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.domain.evaluator_reconstruction import (
    ExploratoryCohortAuthorizationV1,
    ExploratoryReconstructedSessionObservationV1,
    cohort_required_limitations,
)
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationResultV1,
    EvaluationRunArtifactsV1,
    EvaluationSummaryMetricsV1,
    ExploratoryEvaluationResultV1,
    PromotionEvaluationResultV1,
    SessionEquityPointV1,
    evaluation_result_hash,
)
from drift.domain.evaluator_strategy import (
    RuntimeStrategy,
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionViewV1,
    StrategyIntentRejectedError,
    position_view,
    stage_decision_targets,
)
from drift.domain.evaluator_trace import (
    ClaimSettledTraceEventV1,
    CorporateActionAppliedTraceEventV1,
    EvaluationPhase,
    EvaluationTraceLogV1,
    EvaluatorTraceEventV1,
    ExploratoryAccountingPriceTraceEventV1,
    ExploratoryStrategyDecisionTraceEventV1,
    FillRejectionTraceEventV1,
    FillTraceEventV1,
    IndeterminateCauseTraceEventV1,
    SessionMarkTraceEventV1,
    SessionStartTraceEventV1,
    StrategyDecisionTraceEventV1,
    seal_evaluation_trace_log,
)
from drift.domain.normalization import DerivedObservationViewV1
from drift.domain.observation_query import ObservationDecisionQueryV1
from drift.domain.securities import (
    ListingLifecycleVersionV1,
    ListingRoleVersionV1,
    ListingTerminationVersionV1,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.universes import StructuralEligibilityClassification
from drift.evaluator.bundles import validate_exploratory_admission
from drift.evaluator.corporate_actions import CorporateActionProcessor
from drift.evaluator.execution import AtomicRebalanceEngine, resolve_execution_listings
from drift.evaluator.portfolio import (
    PortfolioAccountingKernel,
    initial_portfolio_state,
)
from drift.evaluator.reconstruction import (
    ExploratoryReconstructionReplay,
    require_scheduled_calendar_row,
    verify_exploratory_reconstructions,
)
from drift.serialization.canonical import content_hash

ZERO = Decimal("0")
IDENTITY_NUMERATOR = "1"
IDENTITY_DENOMINATOR = "1"

type SourceBasisField = Literal["open", "high", "low", "close"]

#: Mark grade granted to accounting evidence, by the lane that admitted it.
#: An exploratory run can never mint a promotion-grade valuation, because the
#: grade is read from the admission rather than asserted alongside it.
LANE_MARK_GRADE: dict[str, MarkEvidenceGrade] = {
    "exploratory": "exploratory",
    "promotion": "promotion_grade",
}


def _security_order(security_id: UUID) -> bytes:
    """Canonical collection order for securities: raw UUID bytes."""
    return security_id.bytes


def source_basis_price(
    view: DerivedObservationViewV1, field_name: SourceBasisField
) -> Decimal:
    """Read one exact unadjusted price out of a source-basis derived view.

    Fails closed on anything that is not an unadjusted source-basis number.
    A split-normalized view would double-count the M1c adjustments the
    accounting kernel applies itself, and a transformed value is not what the
    source printed.
    """
    if view.basis_mode != "source_basis":
        raise IndeterminateValuationError(
            "execution and accounting require source basis evidence, view for "
            f"security {view.security_id} carries basis {view.basis_mode}"
        )
    transform = next(
        (item for item in view.fields if item.field_name == field_name), None
    )
    if transform is None:
        raise IndeterminateValuationError(
            f"derived view for security {view.security_id} carries no "
            f"{field_name} field"
        )
    # A source-basis view is materialized against the identity factor. A view
    # that claims source basis while carrying a scaling factor is describing
    # an adjusted number under an unadjusted label.
    if (
        transform.exact_factor.numerator != IDENTITY_NUMERATOR
        or transform.exact_factor.denominator != IDENTITY_DENOMINATOR
    ):
        raise IndeterminateValuationError(
            "source basis evidence requires an identity transform factor for "
            f"{field_name} of security {view.security_id}, got "
            f"{transform.exact_factor.numerator}/"
            f"{transform.exact_factor.denominator}"
        )
    value = transform.source_value
    if not value.is_finite() or value <= ZERO:
        raise IndeterminateValuationError(
            f"unadjusted {field_name} must be strictly positive for security "
            f"{view.security_id}, got {value}"
        )
    return value


@dataclass(frozen=True)
class SessionEvaluatorEvidence:
    """Evidence the evaluator consults that the input bundle does not carry.

    M1b listing role, termination, and lifecycle records resolve the execution
    listing. The economic outcomes are the record-bound form of the bundle's
    own `EconomicOutcomeResolutionV1` members, and the three interpretation
    registries are human source readings the processor refuses to invent.

    ``exploratory_cohort`` is the predeclared bounded cohort a
    scheduled-reconstruction evaluation is scoped by, in place of a historical
    universe. It is required exactly when the EXPLORATORY reconstructed
    decision lane is taken, and refused everywhere else.

    ``exploratory_reconstruction_replay`` carries the exact source inputs the
    bundle's reconstructions derive from. The same rule applies: required
    exactly on the reconstructed lane, refused everywhere else. The lane gate
    re-derives every reconstruction from it before any decision reads one.
    """

    listing_role_records: tuple[ListingRoleVersionV1, ...] = ()
    listing_termination_records: tuple[ListingTerminationVersionV1, ...] = ()
    listing_lifecycle_records: tuple[ListingLifecycleVersionV1, ...] = ()
    economic_outcomes: tuple[SecurityEconomicOutcomeV1, ...] = ()
    tie_breaking_rules: tuple[TieBreakingRuleV1, ...] = ()
    due_bill_rules: tuple[DueBillRuleV1, ...] = ()
    cash_in_lieu_rates: tuple[CashInLieuRateV1, ...] = ()
    exploratory_cohort: ExploratoryCohortAuthorizationV1 | None = None
    exploratory_reconstruction_replay: ExploratoryReconstructionReplay | None = None


@dataclass(frozen=True)
class _Halt:
    """Why and where session stepping stopped."""

    session_index: int
    classification: EvaluationClassification
    reason: str


@dataclass(frozen=True)
class _Checkpoint:
    """The complete result snapshot taken at one session's close mark."""

    point: SessionEquityPointV1
    realized_gross_pnl: Decimal
    realized_net_pnl: Decimal
    cumulative_transaction_costs: Decimal
    gross_traded_notional: Decimal
    committed_fill_count: int


@dataclass
class _Loop:
    """Mutable working set carried across the session loop."""

    state: PortfolioStateV1
    staged_targets: tuple[SecurityTargetPositionV1, ...] = ()
    has_staged_decision: bool = False
    events: list[EvaluatorTraceEventV1] = field(default_factory=list)
    checkpoints: list[_Checkpoint] = field(default_factory=list)
    gross_traded_notional: Decimal = ZERO
    committed_fill_count: int = 0


type LaneDispatchStrategy = RuntimeStrategy | ExploratoryReconstructedRuntimeStrategy
"""What ``SessionEvaluatorEngine.run`` accepts, and the only place both meet.

This is a union of strategy *interfaces* at the lane-dispatch boundary, not a
union of decision *inputs*. The engine's lane, fixed at construction from the
admission and the clock, decides which method is called: ``decide`` with a
strong ``StrategyDecisionContextV1`` in the realized lane, or
``decide_exploratory`` with an ``ExploratoryStrategyDecisionContextV1`` in the
EXPLORATORY scheduled-reconstruction lane. The canonical strong decision input
never admits reconstructed evidence.
"""

type _DecisionPhase = Callable[[_Loop, int, EvaluationSessionV1], _Halt | None]


@dataclass(frozen=True)
class _ReconstructedDecisionLane:
    """The admitted EXPLORATORY scheduled-reconstruction decision path.

    It can only be built from an ``ExploratoryEvaluationAdmissionV1``, so no
    promotion admission can ever stand behind a decision this lane takes.
    """

    admission: ExploratoryEvaluationAdmissionV1
    cohort: ExploratoryCohortAuthorizationV1


def _resolve_reconstructed_lane(
    *,
    bundle: EvaluationInputBundleV1,
    admission: EvaluationAdmissionV1,
    cohort: ExploratoryCohortAuthorizationV1 | None,
    replay: ExploratoryReconstructionReplay | None,
) -> _ReconstructedDecisionLane | None:
    """Fix the decision lane at construction, refusing every upgrade path.

    * A promotion admission never evaluates exploratory reconstructed
      evidence or an exploratory cohort, whatever clock the bundle carries.
      ``validate_promotion_admission`` already refuses such a bundle; this
      refuses it again here, so an engine built without that gate cannot be
      the seam through which the weaker grade reaches a promotion result.
    * Every exploratory admission is validated against its bundle, in either
      lane, so it acknowledges every limitation the bundle's evidence obliges
      (issue 42 ruling, invariant 4; issue 56). A realized bundle can carry
      reconstructions too, and their limitations may not be dropped merely
      because the realized lane does not decide on them.
    * An exploratory admission over a realized clock keeps the realized lane
      exactly as it was. Reconstructions riding such a bundle never become
      decision evidence.
    * An exploratory admission over a scheduled-reconstruction clock takes
      the reconstructed lane, and only after proving its admission, its
      cohort, and every reconstruction against the bundle, then re-deriving
      every reconstruction from its exact source inputs (issue 55). A
      self-consistent reconstruction no source produces never reaches a
      decision.
    """
    if isinstance(admission, PromotionEvaluationAdmissionV1):
        if bundle.has_exploratory_reconstructions:
            raise ValueError(
                "a promotion admission cannot evaluate exploratory reconstructed "
                "evidence"
            )
        if cohort is not None:
            raise ValueError(
                "a promotion admission cannot evaluate an exploratory cohort"
            )
        if replay is not None:
            raise ValueError(
                "a promotion admission cannot evaluate exploratory "
                "reconstruction replay evidence"
            )
        return None
    validate_exploratory_admission(admission=admission, bundle=bundle)
    if bundle.session_clock.mode != "scheduled_session_reconstruction":
        if cohort is not None:
            raise ValueError(
                "an exploratory cohort scopes only a scheduled session "
                "reconstruction evaluation"
            )
        if replay is not None:
            raise ValueError(
                "exploratory reconstruction replay evidence scopes only a "
                "scheduled session reconstruction evaluation"
            )
        return None
    if cohort is None:
        raise ValueError(
            "a scheduled session reconstruction evaluation requires its "
            "predeclared exploratory cohort"
        )
    missing = tuple(
        limitation
        for limitation in cohort_required_limitations(cohort)
        if limitation not in admission.acknowledged_limitations
    )
    if missing:
        raise ValueError(
            f"exploratory admission omits the bounded cohort limitation: {missing}"
        )
    sessions = {
        session.session_key: session for session in bundle.session_clock.sessions
    }
    for observation in bundle.exploratory_reconstructed_observations:
        _bind_reconstruction(observation, sessions[observation.session_key], cohort)
    if replay is None:
        raise ValueError(
            "a scheduled session reconstruction evaluation requires the replay "
            "evidence its reconstructions re-derive from"
        )
    verify_exploratory_reconstructions(
        bundle.exploratory_reconstructed_observations, replay=replay, cohort=cohort
    )
    return _ReconstructedDecisionLane(admission=admission, cohort=cohort)


def reconstructed_history_sessions(
    sessions: Sequence[EvaluationSessionV1], index: int
) -> frozenset[SessionKeyV1]:
    """The sessions whose reconstructions are history at session ``index``.

    History is what the clock has stepped and what had closed by the decision
    cutoff: the stepped sessions whose ``closed_at`` is at or before the
    decision session's own. The clock orders by open time first, so on a
    multi-venue clock a same-date session can be stepped earlier while closing
    later; it has not closed at this cutoff and is not history here (#66).
    """
    cutoff = sessions[index].closed_at
    return frozenset(
        item.session_key for item in sessions[: index + 1] if item.closed_at <= cutoff
    )


def _bind_reconstruction(
    observation: ExploratoryReconstructedSessionObservationV1,
    session: EvaluationSessionV1,
    cohort: ExploratoryCohortAuthorizationV1,
) -> None:
    """Bind one reconstruction to the cohort and the clock session it describes.

    The bundle already proves the session is in its clock. That is not enough
    to let the clock time a decision on this bar; see
    ``require_scheduled_calendar_row``.
    """
    key = observation.session_key
    where = f"{key.mic} {key.local_date.isoformat()}"
    if observation.cohort_hash != cohort.cohort_hash:
        raise ValueError(
            f"exploratory reconstruction on {where} binds cohort "
            f"{observation.cohort_hash}, and does not bind the declared cohort "
            f"{cohort.cohort_hash}"
        )
    if observation.security_id not in cohort.security_ids:
        raise ValueError(
            f"exploratory reconstruction on {where} describes security "
            f"{observation.security_id}, which the declared cohort does not admit"
        )
    require_scheduled_calendar_row(observation, session)


class SessionEvaluatorEngine:
    """Runs the canonical five-phase evaluation loop over one input bundle."""

    def __init__(
        self,
        *,
        bundle: EvaluationInputBundleV1,
        admission: EvaluationAdmissionV1,
        protocol: EvaluationProtocolV1,
        cost_model: EvaluationCostModelV1,
        evidence: SessionEvaluatorEvidence,
        book_currency_namespace: str,
        book_currency_code: str,
    ) -> None:
        if admission.input_bundle_hash != bundle.bundle_hash:
            raise ValueError(
                "the admission must admit this exact bundle: admission binds "
                f"{admission.input_bundle_hash}, bundle is {bundle.bundle_hash}"
            )
        if len(bundle.session_clock.sessions) <= protocol.warmup_session_count:
            raise ValueError(
                "an evaluation requires at least one non-warmup session: the "
                f"clock holds {len(bundle.session_clock.sessions)} sessions for "
                f"a warmup of {protocol.warmup_session_count}"
            )
        self._bundle = bundle
        self._admission = admission
        self._protocol = protocol
        self._cost_model = cost_model
        self._evidence = evidence
        self._mark_grade = LANE_MARK_GRADE[admission.lane]
        self._validate_economic_evidence(evidence, bundle)
        self._reconstructed_lane = _resolve_reconstructed_lane(
            bundle=bundle,
            admission=admission,
            cohort=evidence.exploratory_cohort,
            replay=evidence.exploratory_reconstruction_replay,
        )
        self._accounting_index = self._index_accounting_views(bundle)
        self._book_currency_code = book_currency_code
        # Issue 54: only the reconstructed lane reads this index, and only
        # after its gate re-derived every reconstruction (issue 55).
        # Reconstructions riding a realized bundle never price anything.
        self._reconstructed_prices = self._index_reconstructed_prices(bundle)
        self._corporate_actions = CorporateActionProcessor(
            session_clock=bundle.session_clock,
            book_currency_namespace=book_currency_namespace,
            book_currency_code=book_currency_code,
            tie_breaking_rules=evidence.tie_breaking_rules,
            due_bill_rules=evidence.due_bill_rules,
            cash_in_lieu_rates=evidence.cash_in_lieu_rates,
        )
        self._rebalance = AtomicRebalanceEngine(
            cost_model=cost_model, session_clock=bundle.session_clock
        )

    # -- accessors ---------------------------------------------------------

    @property
    def bundle(self) -> EvaluationInputBundleV1:
        """The immutable input bundle this engine evaluates."""
        return self._bundle

    @property
    def admission(self) -> EvaluationAdmissionV1:
        """The lane admission authorizing this evaluation."""
        return self._admission

    @property
    def protocol(self) -> EvaluationProtocolV1:
        """The cadence, warmup, and seed capital protocol."""
        return self._protocol

    @property
    def cost_model(self) -> EvaluationCostModelV1:
        """The versioned cost and slippage model applied to every fill."""
        return self._cost_model

    def admitted_universe_at(self, session: EvaluationSessionV1) -> tuple[UUID7, ...]:
        """Securities the structural evidence admits as of one decision close.

        Admission is an as-of question, not a property of the interval. Three
        conditions must all hold, and each closes a distinct leak:

        * The result must classify the security ``ELIGIBLE``. An
          ``INDETERMINATE`` membership is not an admission.
        * The result must have been resolved ``AS_KNOWN``. A
          ``CURRENT_INTERPRETATION`` result is an ex-post audit answer, and
          admitting one would let today's view of the universe define what a
          past decision was allowed to hold.
        * Its knowledge cutoff must not follow this decision cutoff. A result
          answered with later knowledge is not information the decision could
          have had, so a security that only became eligible afterwards is
          excluded rather than backdated into the universe.

        Among the as-known results the decision could have had, only the latest
        answers for a security (issue 85, spec 9.1): an INELIGIBLE result known
        after an ELIGIBLE one removes the security, and conflicting answers
        known at one instant admit nothing.
        """
        cutoff = session.closed_at
        latest: dict[UUID, tuple[tuple[datetime, datetime], set[bool]]] = {}
        for result in self._bundle.structural_eligibilities:
            query = result.normalized_query
            if (
                query.resolution_mode is not ResolutionMode.AS_KNOWN
                or query.knowledge_cutoff > cutoff
                or query.evaluation_time > cutoff
            ):
                continue
            key = (query.evaluation_time, query.knowledge_cutoff)
            eligible = (
                result.classification is StructuralEligibilityClassification.ELIGIBLE
            )
            known = latest.get(result.security_id)
            if known is None or key > known[0]:
                latest[result.security_id] = (key, {eligible})
            elif key == known[0]:
                known[1].add(eligible)
        return tuple(
            sorted(
                (
                    security_id
                    for security_id, (_, answers) in latest.items()
                    if answers == {True}
                ),
                key=_security_order,
            )
        )

    # -- construction guards ------------------------------------------------

    @staticmethod
    def _validate_economic_evidence(
        evidence: SessionEvaluatorEvidence, bundle: EvaluationInputBundleV1
    ) -> None:
        """Bind every corporate-action record set to the bundle's own outcome.

        `SecurityEconomicOutcomeV1` carries the source records the bundle's
        audit-only `EconomicOutcomeResolutionV1` names by hash. Accepting one
        the bundle never declared would let unauthorized share and cash
        mutations enter an otherwise proof-carrying evaluation.
        """
        declared = {content_hash(item) for item in bundle.economic_outcomes}
        seen: set[UUID] = set()
        for outcome in evidence.economic_outcomes:
            if outcome.security_id in seen:
                raise ValueError(
                    "economic outcomes must be unique by security: "
                    f"{outcome.security_id}"
                )
            seen.add(outcome.security_id)
            if content_hash(outcome.resolution) not in declared:
                raise ValueError(
                    "the input bundle does not carry the economic outcome "
                    f"resolution for security {outcome.security_id}"
                )

    @staticmethod
    def _index_accounting_views(
        bundle: EvaluationInputBundleV1,
    ) -> dict[tuple[UUID, SessionKeyV1], list[DerivedObservationViewV1]]:
        index: dict[tuple[UUID, SessionKeyV1], list[DerivedObservationViewV1]] = {}
        for view in bundle.authentic_accounting_views:
            index.setdefault((view.security_id, view.source_session), []).append(view)
        return index

    @staticmethod
    def _index_reconstructed_prices(
        bundle: EvaluationInputBundleV1,
    ) -> dict[
        tuple[UUID, SessionKeyV1], list[ExploratoryReconstructedSessionObservationV1]
    ]:
        index: dict[
            tuple[UUID, SessionKeyV1],
            list[ExploratoryReconstructedSessionObservationV1],
        ] = {}
        for observation in bundle.exploratory_reconstructed_observations:
            index.setdefault(
                (observation.security_id, observation.session_key), []
            ).append(observation)
        return index

    def _require_bound_identity(self, run_identity: EvaluationRunIdentityV1) -> None:
        if (
            run_identity.admission_hash != self._admission.admission_hash
            or run_identity.bundle_hash != self._bundle.bundle_hash
            or run_identity.protocol_hash != self._protocol.protocol_hash
            or run_identity.cost_model_hash != self._cost_model.cost_model_hash
        ):
            raise ValueError(
                "the run identity must bind this evaluation's admission, "
                "bundle, protocol, and cost model"
            )

    # -- run ----------------------------------------------------------------

    def run(
        self, *, strategy: LaneDispatchStrategy, run_identity: EvaluationRunIdentityV1
    ) -> EvaluationRunArtifactsV1:
        """Step every session through all five phases, halting fail-closed.

        The decision lane was fixed at construction. The strategy is bound to
        that lane's one decision method before any session is stepped.
        """
        self._require_bound_identity(run_identity)
        decide = self._lane_decision(strategy)
        sessions = self._bundle.session_clock.sessions
        loop = _Loop(
            state=initial_portfolio_state(
                session_key=sessions[0].session_key,
                initial_cash=self._protocol.initial_cash,
                admission=self._admission,
            )
        )
        halt: _Halt | None = None
        for index, session in enumerate(sessions):
            if index > 0:
                loop.state = self._advance(loop.state, session.session_key)
            self._emit_session_start(loop, index, session)
            halt = self._step_session(loop, index, session, decide)
            if halt is not None:
                break
        trace = seal_evaluation_trace_log(loop.events)
        result = self._seal_result(
            run_identity=run_identity,
            halt=halt,
            metrics=self._metrics(loop),
            trace=trace,
        )
        return EvaluationRunArtifactsV1(
            result=result, trace=trace, final_state=loop.state
        )

    def _advance(
        self, state: PortfolioStateV1, session_key: SessionKeyV1
    ) -> PortfolioStateV1:
        kernel = PortfolioAccountingKernel(
            state, session_clock=self._bundle.session_clock
        )
        kernel.advance_session(session_key)
        return kernel.state

    def _emit_session_start(
        self, loop: _Loop, index: int, session: EvaluationSessionV1
    ) -> None:
        loop.events.append(
            SessionStartTraceEventV1(
                sequence=len(loop.events),
                session_index=index,
                session_key=session.session_key,
                session_hash=session.session_hash,
                opening_cash=loop.state.cash_balance,
                opening_net_asset_value=loop.state.net_asset_value,
            )
        )

    def _step_session(
        self,
        loop: _Loop,
        index: int,
        session: EvaluationSessionV1,
        decide: _DecisionPhase,
    ) -> _Halt | None:
        phase = EvaluationPhase.PRE_OPEN_EFFECTS
        try:
            self._pre_open_effects(loop, index, session)
            phase = EvaluationPhase.OPEN_EXECUTION
            rejected = self._open_execution(loop, index, session)
            if rejected is not None:
                return rejected
            phase = EvaluationPhase.INTRASESSION_ECONOMIC_EFFECTS
            self._intrasession_effects(loop, index, session)
            phase = EvaluationPhase.CLOSE_MARK
            self._close_mark(loop, index, session)
            phase = EvaluationPhase.POST_CLOSE_DECISION
            return decide(loop, index, session)
        except (IndeterminateValuationError, IndeterminateExecutionError) as error:
            cause = str(error) or type(error).__name__
            kind: Literal["indeterminate_valuation", "indeterminate_execution"] = (
                "indeterminate_valuation"
                if isinstance(error, IndeterminateValuationError)
                else "indeterminate_execution"
            )
            loop.events.append(
                IndeterminateCauseTraceEventV1(
                    sequence=len(loop.events),
                    session_index=index,
                    session_key=session.session_key,
                    phase=phase,
                    cause_kind=kind,
                    cause=cause,
                )
            )
            return _Halt(index, EvaluationClassification.INDETERMINATE, cause)

    # -- phase 1: pre-open effects -------------------------------------------

    def _pre_open_effects(
        self, loop: _Loop, index: int, session: EvaluationSessionV1
    ) -> None:
        """Fold this session's proven corporate actions in, exactly once.

        `apply_pre_open_actions` is not idempotent for share mutations, so it
        is called once per session and never re-run for the same session.
        """
        before_holdings = positions_digest(loop.state.holdings)
        before_targets = loop.staged_targets
        before_claims = {claim.claim_id for claim in loop.state.pending_cash_claims}
        state, targets = self._corporate_actions.apply_pre_open_actions(
            loop.state,
            loop.staged_targets,
            self._evidence.economic_outcomes,
            session.session_key,
        )
        loop.state = state
        loop.staged_targets = targets
        after_holdings = positions_digest(state.holdings)
        recorded = tuple(
            sorted(
                {claim.claim_id for claim in state.pending_cash_claims} - before_claims
            )
        )
        if (
            after_holdings == before_holdings
            and targets == before_targets
            and not recorded
        ):
            return
        loop.events.append(
            CorporateActionAppliedTraceEventV1(
                sequence=len(loop.events),
                session_index=index,
                session_key=session.session_key,
                holdings_hash_before=before_holdings,
                holdings_hash_after=after_holdings,
                staged_targets_before=before_targets,
                staged_targets_after=targets,
                recorded_claim_ids=recorded,
            )
        )

    # -- phase 2: open execution ----------------------------------------------

    def _open_execution(
        self, loop: _Loop, index: int, session: EvaluationSessionV1
    ) -> _Halt | None:
        if not loop.has_staged_decision:
            return None
        targets = {
            target.security_id: target.target_quantity for target in loop.staged_targets
        }
        held = {
            holding.security_id: holding.quantity for holding in loop.state.holdings
        }
        # Only a non-zero delta trades, so only a traded security needs a
        # resolved listing and an open price. Demanding either for an
        # untouched holding would fail closed on evidence the rebalance never
        # consumes.
        trading = tuple(
            sorted(
                (
                    security_id
                    for security_id in set(targets) | set(held)
                    if targets.get(security_id, 0) != held.get(security_id, 0)
                ),
                key=_security_order,
            )
        )
        listings = resolve_execution_listings(
            security_ids=trading,
            execution_session=session,
            role_records=self._evidence.listing_role_records,
            listings=self._bundle.listing_identities,
            termination_records=self._evidence.listing_termination_records,
            lifecycle_records=self._evidence.listing_lifecycle_records,
        )
        if self._reconstructed_lane is None:
            prices = {
                security_id: self._open_price(security_id, session)
                for security_id in trading
            }
        else:
            records = tuple(
                self._reconstructed_price(security_id, session.session_key, "open")
                for security_id in trading
            )
            prices = {
                record.security_id: ListingOpenPriceV1(
                    listing_id=record.listing_id,
                    venue=record.venue,
                    unadjusted_open_price=record.unadjusted_price,
                )
                for record in records
            }
            if records:
                loop.events.append(
                    ExploratoryAccountingPriceTraceEventV1(
                        sequence=len(loop.events),
                        session_index=index,
                        session_key=session.session_key,
                        phase=EvaluationPhase.OPEN_EXECUTION,
                        prices=records,
                        acknowledged_limitations=(
                            self._reconstructed_lane.admission.acknowledged_limitations
                        ),
                    )
                )
        outcome = self._rebalance.rebalance(
            state=loop.state,
            staged_targets=loop.staged_targets,
            open_prices=prices,
            execution_listings=listings,
        )
        # The staged decision is consumed whether or not it executed, so a
        # stale intent can never be executed twice.
        loop.staged_targets = ()
        loop.has_staged_decision = False
        if outcome.classification == "rejected":
            rejection = outcome.rejection
            if rejection is None:  # pragma: no cover - model invariant
                raise IndeterminateExecutionError(
                    "a rejected rebalance must carry its rejection"
                )
            loop.events.append(
                FillRejectionTraceEventV1(
                    sequence=len(loop.events),
                    session_index=index,
                    session_key=session.session_key,
                    rejection=rejection,
                )
            )
            reason = (
                "unfunded rebalance on "
                f"{session.session_key.local_date.isoformat()}: cash shortfall "
                f"{rejection.cash_shortfall}"
            )
            return _Halt(index, EvaluationClassification.REJECTED, reason)
        with decimal_context():
            for position, fill in enumerate(outcome.committed_fills):
                loop.events.append(
                    FillTraceEventV1(
                        sequence=len(loop.events),
                        session_index=index,
                        session_key=session.session_key,
                        commit_index=position,
                        fill=fill,
                    )
                )
                loop.gross_traded_notional += fill.gross_notional
                loop.committed_fill_count += 1
        loop.state = outcome.state
        return None

    def _open_price(
        self, security_id: UUID7, session: EvaluationSessionV1
    ) -> ListingOpenPriceV1:
        """Bridge one accounting view into the open price of its own listing.

        The price is bound to the listing the evidence was observed on, not to
        whichever listing execution resolved. Stamping the resolved listing
        here would defeat the execution guard that refuses a price from a
        venue the security no longer trades on.
        """
        view = self._accounting_view(security_id, session.session_key)
        return ListingOpenPriceV1(
            listing_id=view.listing_id,
            venue=view.query.observation.venue,
            unadjusted_open_price=source_basis_price(view, "open"),
        )

    def _reconstructed_price(
        self,
        security_id: UUID7,
        session_key: SessionKeyV1,
        field_role: ExploratoryAccountingPriceRole,
    ) -> ExploratoryReconstructedAccountingPriceV1:
        """Read one EXPLORATORY accounting price, failing closed on any doubt."""
        where = f"{session_key.mic} {session_key.local_date}"
        observations = self._reconstructed_prices.get((security_id, session_key), [])
        if not observations:
            raise IndeterminateValuationError(
                "no exploratory reconstructed accounting price for security "
                f"{security_id} on {where}"
            )
        if len(observations) > 1:
            raise IndeterminateValuationError(
                "more than one exploratory reconstruction for security "
                f"{security_id} on {where}"
            )
        observation = observations[0]
        value = next(
            item.source_value
            for item in observation.fields
            if item.field_name == field_role
        )
        # A re-derived reconstruction only guarantees a finite number. A price
        # that cannot fill or mark is missing evidence, not a failed run.
        if value <= ZERO:
            raise IndeterminateValuationError(
                f"exploratory reconstructed {field_role} price for security "
                f"{security_id} on {where} is not strictly positive: {value}"
            )
        price = reconstructed_accounting_price(observation, field_role)
        if price.currency != self._book_currency_code:
            raise IndeterminateValuationError(
                f"exploratory reconstructed {field_role} price for security "
                f"{security_id} on {where} is in {price.currency}, not the book "
                f"currency {self._book_currency_code}"
            )
        return price

    def _accounting_view(
        self, security_id: UUID7, session_key: SessionKeyV1
    ) -> DerivedObservationViewV1:
        views = self._accounting_index.get((security_id, session_key), [])
        if not views:
            raise IndeterminateValuationError(
                "no authorized accounting view for security "
                f"{security_id} on {session_key.mic} {session_key.local_date}"
            )
        if len(views) > 1:
            # Two admissible answers is not an answer. Picking one would make
            # the book depend on member ordering inside the bundle.
            raise IndeterminateValuationError(
                "more than one authorized accounting view for security "
                f"{security_id} on {session_key.mic} {session_key.local_date}"
            )
        return views[0]

    # -- phase 3: intrasession economic effects --------------------------------

    def _intrasession_effects(
        self, loop: _Loop, index: int, session: EvaluationSessionV1
    ) -> None:
        before_settled = set(loop.state.settled_claim_ids)
        before_cash = loop.state.cash_balance
        state = self._corporate_actions.apply_intrasession_settlements(
            loop.state, self._evidence.economic_outcomes, session.session_key
        )
        loop.state = state
        settled = tuple(sorted(set(state.settled_claim_ids) - before_settled))
        if not settled:
            return
        with decimal_context():
            delivered = state.cash_balance - before_cash
        loop.events.append(
            ClaimSettledTraceEventV1(
                sequence=len(loop.events),
                session_index=index,
                session_key=session.session_key,
                claim_ids=settled,
                settled_cash=delivered,
            )
        )

    # -- phase 4: close mark -----------------------------------------------------

    def _close_mark(
        self, loop: _Loop, index: int, session: EvaluationSessionV1
    ) -> None:
        if self._reconstructed_lane is None:
            marks = tuple(
                self._mark_price(holding.security_id, session)
                for holding in loop.state.holdings
            )
        else:
            records = tuple(
                self._reconstructed_price(
                    holding.security_id, session.session_key, "close"
                )
                for holding in loop.state.holdings
            )
            marks = tuple(
                MarkPriceV1(
                    security_id=record.security_id,
                    close_price=record.unadjusted_price,
                    evidence=MarkEvidenceV1(
                        grade=self._mark_grade, evidence_hash=record.price_hash
                    ),
                )
                for record in records
            )
            if records:
                loop.events.append(
                    ExploratoryAccountingPriceTraceEventV1(
                        sequence=len(loop.events),
                        session_index=index,
                        session_key=session.session_key,
                        phase=EvaluationPhase.CLOSE_MARK,
                        prices=records,
                        acknowledged_limitations=(
                            self._reconstructed_lane.admission.acknowledged_limitations
                        ),
                    )
                )
        kernel = PortfolioAccountingKernel(
            loop.state, session_clock=self._bundle.session_clock
        )
        kernel.mark_close(marks)
        loop.state = kernel.state
        mark = loop.state.mark
        if mark is None:  # pragma: no cover - kernel invariant
            raise IndeterminateValuationError("close mark did not take")
        loop.events.append(
            SessionMarkTraceEventV1(
                sequence=len(loop.events),
                session_index=index,
                session_key=session.session_key,
                mark_hash=content_hash(mark),
                cash_balance=loop.state.cash_balance,
                holdings_market_value=loop.state.holdings_market_value,
                pending_claims_value=loop.state.pending_claims_value,
                net_asset_value=loop.state.net_asset_value,
            )
        )
        loop.checkpoints.append(
            _Checkpoint(
                point=SessionEquityPointV1(
                    session_index=index,
                    session_key=session.session_key,
                    cash_balance=loop.state.cash_balance,
                    holdings_market_value=loop.state.holdings_market_value,
                    pending_claims_value=loop.state.pending_claims_value,
                    net_asset_value=loop.state.net_asset_value,
                ),
                realized_gross_pnl=loop.state.realized_gross_pnl,
                realized_net_pnl=loop.state.realized_net_pnl,
                cumulative_transaction_costs=loop.state.cumulative_transaction_costs,
                gross_traded_notional=loop.gross_traded_notional,
                committed_fill_count=loop.committed_fill_count,
            )
        )

    def _mark_price(
        self, security_id: UUID7, session: EvaluationSessionV1
    ) -> MarkPriceV1:
        view = self._accounting_view(security_id, session.session_key)
        return MarkPriceV1(
            security_id=security_id,
            close_price=source_basis_price(view, "close"),
            evidence=MarkEvidenceV1(
                grade=self._mark_grade, evidence_hash=content_hash(view)
            ),
        )

    # -- phase 5: post-close decision ----------------------------------------------

    def _post_close_decision(
        self,
        loop: _Loop,
        index: int,
        session: EvaluationSessionV1,
        strategy: RuntimeStrategy,
    ) -> _Halt | None:
        if index < self._protocol.warmup_session_count - 1:
            return None
        context = self._decision_context(loop.state, session)
        intent = strategy.decide(context)
        context_hash = content_hash(context)
        intent_hash = content_hash(intent)
        try:
            staged = stage_decision_targets(intent, context)
        except StrategyIntentRejectedError as error:
            reason = str(error) or type(error).__name__
            loop.events.append(
                StrategyDecisionTraceEventV1(
                    sequence=len(loop.events),
                    session_index=index,
                    session_key=session.session_key,
                    decision_cutoff=session.closed_at,
                    context_hash=context_hash,
                    intent_hash=intent_hash,
                    outcome="rejected",
                    staged_targets=(),
                    rejection_reason=reason,
                )
            )
            return _Halt(index, EvaluationClassification.REJECTED, reason)
        loop.events.append(
            StrategyDecisionTraceEventV1(
                sequence=len(loop.events),
                session_index=index,
                session_key=session.session_key,
                decision_cutoff=session.closed_at,
                context_hash=context_hash,
                intent_hash=intent_hash,
                outcome="staged",
                staged_targets=staged,
                rejection_reason=None,
            )
        )
        loop.staged_targets = staged
        loop.has_staged_decision = True
        return None

    def _decision_context(
        self, state: PortfolioStateV1, session: EvaluationSessionV1
    ) -> StrategyDecisionContextV1:
        return StrategyDecisionContextV1(
            session_key=session.session_key,
            decision_session=session,
            decision_cutoff=session.closed_at,
            admitted_universe=self.admitted_universe_at(session),
            current_holdings=tuple(
                position_view(holding) for holding in state.holdings
            ),
            current_cash=state.cash_balance,
            portfolio_nav=state.net_asset_value,
            decision_views=self._decision_views(session),
        )

    def _decision_views(
        self, session: EvaluationSessionV1
    ) -> tuple[StrategyDecisionViewV1, ...]:
        """Select the decision evidence answerable exactly at this cutoff.

        Selection is on the query's own decision time, which is the identity
        of the decision the evidence was produced for. Every other causality
        rule is left to `StrategyDecisionContextV1` rather than being
        pre-filtered here: silently dropping an acausal view would let a
        poisoned bundle run to COMPLETE instead of failing loudly.
        """
        grouped: dict[UUID, list[DerivedObservationViewV1]] = {}
        for view in self._bundle.authentic_decision_views:
            observation = view.query.observation
            if not isinstance(observation, ObservationDecisionQueryV1):
                continue
            if observation.decision_time != session.closed_at:
                continue
            grouped.setdefault(view.security_id, []).append(view)
        if not grouped:
            raise IndeterminateValuationError(
                "no authorized decision evidence for the decision cutoff "
                f"{session.closed_at.isoformat()}"
            )
        return tuple(
            StrategyDecisionViewV1(
                security_id=security_id, views=tuple(grouped[security_id])
            )
            for security_id in sorted(grouped, key=_security_order)
        )

    def _lane_decision(self, strategy: LaneDispatchStrategy) -> _DecisionPhase:
        """Bind the strategy to the one decision method this engine's lane allows.

        Checked once, before any session is stepped, so a strategy that cannot
        answer its lane is a configuration defect rather than a halted run.
        """
        lane = self._reconstructed_lane
        if lane is None:
            if not isinstance(strategy, RuntimeStrategy):
                raise TypeError(
                    "a realized session evaluation hands the strategy strong "
                    "decision evidence, so its strategy must answer decide"
                )
            realized = strategy

            def realized_decision(
                loop: _Loop, index: int, session: EvaluationSessionV1
            ) -> _Halt | None:
                return self._post_close_decision(loop, index, session, realized)

            return realized_decision
        if not isinstance(strategy, ExploratoryReconstructedRuntimeStrategy):
            raise TypeError(
                "a scheduled session reconstruction evaluation supplies only "
                "EXPLORATORY reconstructed decision evidence, so its strategy "
                "must answer decide_exploratory"
            )
        exploratory = strategy

        def reconstructed_decision(
            loop: _Loop, index: int, session: EvaluationSessionV1
        ) -> _Halt | None:
            return self._post_close_reconstructed_decision(
                loop, index, session, exploratory, lane
            )

        return reconstructed_decision

    # -- phase 5, EXPLORATORY scheduled reconstruction ------------------------

    def _post_close_reconstructed_decision(
        self,
        loop: _Loop,
        index: int,
        session: EvaluationSessionV1,
        strategy: ExploratoryReconstructedRuntimeStrategy,
        lane: _ReconstructedDecisionLane,
    ) -> _Halt | None:
        """Phase 5 over EXPLORATORY-only reconstructed evidence.

        Mirrors the realized decision step one for one, except that the
        context is the weaker type, the strategy is asked through
        ``decide_exploratory``, and the trace records the decision under its
        own event kind with every reconstruction read and every limitation
        carried.
        """
        if index < self._protocol.warmup_session_count - 1:
            return None
        context = self._reconstructed_decision_context(loop.state, index, session, lane)
        intent = strategy.decide_exploratory(context)
        common: dict[str, Any] = {
            "sequence": len(loop.events),
            "session_index": index,
            "session_key": session.session_key,
            "decision_cutoff": context.decision_cutoff,
            "context_hash": content_hash(context),
            "intent_hash": content_hash(intent),
            "reconstruction_hashes": tuple(
                sorted(
                    observation.reconstruction_hash
                    for view in context.reconstructed_decision_views
                    for observation in view.observations
                )
            ),
            "acknowledged_limitations": context.acknowledged_limitations,
        }
        try:
            staged = stage_exploratory_decision_targets(intent, context)
        except StrategyIntentRejectedError as error:
            reason = str(error) or type(error).__name__
            loop.events.append(
                ExploratoryStrategyDecisionTraceEventV1(
                    **common,
                    outcome="rejected",
                    staged_targets=(),
                    rejection_reason=reason,
                )
            )
            return _Halt(index, EvaluationClassification.REJECTED, reason)
        loop.events.append(
            ExploratoryStrategyDecisionTraceEventV1(
                **common,
                outcome="staged",
                staged_targets=staged,
                rejection_reason=None,
            )
        )
        loop.staged_targets = staged
        loop.has_staged_decision = True
        return None

    def _reconstructed_decision_context(
        self,
        state: PortfolioStateV1,
        index: int,
        session: EvaluationSessionV1,
        lane: _ReconstructedDecisionLane,
    ) -> ExploratoryStrategyDecisionContextV1:
        return ExploratoryStrategyDecisionContextV1(
            session_key=session.session_key,
            decision_session=session,
            decision_cutoff=session.closed_at,
            cohort_hash=lane.cohort.cohort_hash,
            admitted_cohort=lane.cohort.security_ids,
            current_holdings=tuple(
                position_view(holding) for holding in state.holdings
            ),
            current_cash=state.cash_balance,
            portfolio_nav=state.net_asset_value,
            reconstructed_decision_views=self._reconstructed_decision_views(
                index, session
            ),
            # The admission already acknowledges every limitation the bundle
            # obliges and the bounded cohort, so the decision carries them all.
            acknowledged_limitations=lane.admission.acknowledged_limitations,
        )

    def _reconstructed_decision_views(
        self, index: int, session: EvaluationSessionV1
    ) -> tuple[ExploratoryReconstructedDecisionViewV1, ...]:
        """Select the reconstructed history the scheduled clock has closed.

        Unlike the realized path this must select by session, because a
        scheduled bundle legitimately carries reconstructions for sessions
        after this one: they are the evidence for later decisions, not poison
        to be flagged. What is history at this cutoff is exactly what the
        clock has already stepped, this session included. The context then
        re-checks business-time order on its own, so a broken selection here
        fails loudly rather than leaking the future.
        """
        stepped = reconstructed_history_sessions(
            self._bundle.session_clock.sessions, index
        )
        grouped: dict[UUID, list[ExploratoryReconstructedSessionObservationV1]] = {}
        read_current_session = False
        for observation in self._bundle.exploratory_reconstructed_observations:
            if observation.session_key not in stepped:
                continue
            members = grouped.setdefault(observation.security_id, [])
            if any(item.session_key == observation.session_key for item in members):
                # Two admissible answers is not an answer.
                raise IndeterminateValuationError(
                    "more than one reconstructed observation for security "
                    f"{observation.security_id} on {observation.session_key.mic} "
                    f"{observation.session_key.local_date}"
                )
            members.append(observation)
            if observation.session_key == session.session_key:
                read_current_session = True
        if not read_current_session:
            # A scheduled session expected open whose bar is missing is
            # unknown. It is never read as a halt and never skipped.
            raise IndeterminateValuationError(
                "no reconstructed decision evidence for the scheduled decision "
                f"session {session.session_key.mic} "
                f"{session.session_key.local_date.isoformat()}"
            )
        return tuple(
            ExploratoryReconstructedDecisionViewV1(
                security_id=security_id,
                observations=tuple(grouped[security_id]),
                acknowledged_limitations=tuple(
                    sorted(
                        {
                            limitation
                            for observation in grouped[security_id]
                            for limitation in observation.acknowledged_limitations
                        }
                    )
                ),
            )
            for security_id in sorted(grouped, key=_security_order)
        )

    # -- results ----------------------------------------------------------------

    def _metrics(self, loop: _Loop) -> EvaluationSummaryMetricsV1:
        initial = self._protocol.initial_cash
        with decimal_context():
            if loop.checkpoints:
                last = loop.checkpoints[-1]
                ending_cash = last.point.cash_balance
                ending_nav = last.point.net_asset_value
                realized_gross = last.realized_gross_pnl
                realized_net = last.realized_net_pnl
                costs = last.cumulative_transaction_costs
                turnover = last.gross_traded_notional
                fills = last.committed_fill_count
            else:
                ending_cash = initial
                ending_nav = initial
                realized_gross = ZERO
                realized_net = ZERO
                costs = ZERO
                turnover = ZERO
                fills = 0
            net_pnl = ending_nav - initial
        return EvaluationSummaryMetricsV1(
            evaluated_session_count=len(loop.checkpoints),
            initial_cash=initial,
            initial_net_asset_value=initial,
            ending_cash=ending_cash,
            ending_net_asset_value=ending_nav,
            net_profit_and_loss=net_pnl,
            realized_gross_pnl=realized_gross,
            realized_net_pnl=realized_net,
            cumulative_transaction_costs=costs,
            gross_traded_notional=turnover,
            committed_fill_count=fills,
            equity_series=tuple(item.point for item in loop.checkpoints),
        )

    def _seal_result(
        self,
        *,
        run_identity: EvaluationRunIdentityV1,
        halt: _Halt | None,
        metrics: EvaluationSummaryMetricsV1,
        trace: EvaluationTraceLogV1,
    ) -> EvaluationResultV1:
        common: dict[str, object] = {
            "schema_version": "1",
            "run_identity": run_identity,
            "classification": (
                EvaluationClassification.COMPLETE
                if halt is None
                else halt.classification
            ),
            "halted_session_index": None if halt is None else halt.session_index,
            "halt_reason": None if halt is None else halt.reason,
            "metrics": metrics,
            "trace_hash": trace.trace_hash,
            "result_hash": "0" * 64,
        }
        if isinstance(self._admission, PromotionEvaluationAdmissionV1):
            return _seal(
                PromotionEvaluationResultV1,
                common
                | {
                    "lane": "promotion",
                    "is_promotion_grade_evidence": True,
                    "admission": self._admission,
                },
            )
        return _seal(
            ExploratoryEvaluationResultV1,
            common
            | {
                "lane": "exploratory",
                "is_promotion_grade_evidence": False,
                "admission": self._admission,
            },
        )


def _seal[T: ExploratoryEvaluationResultV1 | PromotionEvaluationResultV1](
    model: type[T], values: dict[str, object]
) -> T:
    """Attach a result's self-excluding content hash and validate it."""
    draft = model.model_construct(_fields_set=None, **cast(Any, values))
    sealed = model.model_construct(
        _fields_set=None,
        **cast(Any, dict(draft) | {"result_hash": evaluation_result_hash(draft)}),
    )
    return cast(T, model.model_validate(dict(sealed)))
