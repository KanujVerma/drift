"""One original account through a bounded, offline, installed-strategy campaign.

The actual existing evaluator remains the only portfolio/accounting engine.
This host composes original research, explicit mandate checks and retained
observations. It is not a provider, broker, arbitrary Python sandbox or a claim
of historical efficacy. All operational identities stay out of financial
strategy parameters; original records retain them for independent joins.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, cast
from uuid import UUID, uuid7

from drift.baselines import (
    B3MonthlyEqualWeightRebalanceStrategy,
    B4MomentumStrategy,
    B5LowVolatilityStrategy,
)
from drift.baselines.common import (
    build_decision_intent,
    extract_security_history,
    get_admitted_securities,
    make_baseline_reference,
)
from drift.baselines.runner import (
    build_canonical_run_identity,
    build_canonical_specification,
    make_bundle_dataset_reference,
)
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_bundles import strategy_parameters_hash
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import (
    IndeterminateValuationError,
    PortfolioStateV2,
    decimal_context,
)
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.observation_query import drift_source_inventory_hash
from drift.domain.strategies import StrategyReference
from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.evaluator.session_observer import (
    ExecutionAuthorizationV1,
    RebalancePreviewV1,
    SessionObservationV1,
)
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CostReceipt,
    RawChoice,
    ResearchCandidate,
    ResearchContext,
    StrategySelection,
    TargetWeight,
    TrustedInvocationBinding,
    compute_record_hash,
)
from drift.intelligence.conventional_selector import (
    ConventionalSelectorResult,
    select_conventional_candidate,
)
from drift.intelligence.learning import (
    LearningSnapshot,
    TrialFeedbackRecord,
    advance_learning,
)
from drift.intelligence.proposal_producer import (
    FakeTransport,
    ProducerResult,
    produce_proposal,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.intelligence.validation import ResolvedDependencies, ValidationResult
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop import stage1_controlled_contracts as C
from drift.loop.stage1_controlled_journal import (
    ControlledJournalWriterV1,
    observed_time,
    reference,
)
from drift.loop.stage1_original_result_association import (
    Stage1OriginalResultAssociationV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.loop.stage1_synthetic_research_execution import (
    installed_registry_reference,
    installed_strategy_registration,
    synthetic_universe_reference,
)
from drift.serialization.canonical import canonical_json, content_hash

type DecisionContext = StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1
type Installed = (
    B3MonthlyEqualWeightRebalanceStrategy | B4MomentumStrategy | B5LowVolatilityStrategy
)
type ResearchOutput = ProducerResult | ConventionalSelectorResult


def installed(family: C.Family) -> Installed:
    if family == "B3":
        return B3MonthlyEqualWeightRebalanceStrategy()
    if family == "B4":
        return B4MomentumStrategy()
    if family == "B5":
        return B5LowVolatilityStrategy()
    raise ValueError("CONTROLLED_UNSUPPORTED_INSTALLED_FAMILY")


def context_kind(context: DecisionContext) -> Literal["realized", "reconstructed"]:
    return "realized" if type(context) is StrategyDecisionContextV1 else "reconstructed"


def parse_context(kind: str, payload: C.RetainedCanonicalPayloadV1) -> DecisionContext:
    if kind == "realized":
        return payload.parse(StrategyDecisionContextV1)
    if kind == "reconstructed":
        return payload.parse(ExploratoryStrategyDecisionContextV1)
    raise ValueError("CONTROLLED_UNKNOWN_CONTEXT_KIND")


def financial_parameters(plan: C.ControlledCampaignPlanV1) -> ImmutableJSONValue:
    """Installed study identity, excluding original operational IDs and clocks."""
    return cast(
        ImmutableJSONValue,
        json.loads(
            canonical_json(
                {
                    "profile": C.PROFILE,
                    "initial_family": "B3",
                    "initial_decision_index": plan.initial_decision_index,
                    "coverage": plan.coverage,
                    "mandate": plan.mandate,
                    "method": plan.context_template.method_ref,
                    "checkpoints": tuple(
                        {
                            "checkpoint_id": item.checkpoint_id,
                            "session_index": item.session_index,
                            "decision_cutoff": item.decision_cutoff,
                            "fixture": item.fixture,
                            "research_budget_usd": item.research_budget_usd,
                        }
                        for item in plan.checkpoints
                    ),
                }
            )
        ),
    )


def controlled_strategy_reference() -> StrategyReference:
    return make_baseline_reference(
        "stage1_controlled_installed_menu",
        version="1",
        custom_hash=content_hash(
            {"profile": C.PROFILE, "families": ("B3", "B4", "B5")}
        ),
    )


def hold_intent(context: DecisionContext) -> StrategyDecisionIntentV1:
    return build_decision_intent(
        context,
        tuple(
            SecurityTargetPositionV1(
                security_id=item.security_id, target_quantity=item.quantity
            )
            for item in context.current_holdings
        ),
    )


def installed_intent(
    family: C.Family,
    context: DecisionContext,
    sessions: tuple[EvaluationSessionV1, ...] = (),
) -> StrategyDecisionIntentV1:
    """Require nonvacuous original history before calling an unchanged baseline."""
    securities = get_admitted_securities(context)
    needed = 253 if family == "B4" else 61 if family == "B5" else 1
    if family != "B3" and len(securities) < 2:
        raise ValueError("CONTROLLED_FAMILY_UNIVERSE_UNAVAILABLE")
    expected = None
    if sessions:
        # A caller supplies the actual declared clock's keys, not weekdays.
        keys = tuple(item.session_key for item in sessions)
        index = keys.index(context.session_key)
        if index + 1 < needed:
            raise ValueError("CONTROLLED_FAMILY_WARMUP_UNAVAILABLE")
        expected = keys[index - needed + 1 : index + 1]
    for security in securities:
        history = extract_security_history(context, security)
        if len(history) < needed or history[-1].session_key != context.session_key:
            raise ValueError("CONTROLLED_FAMILY_HISTORY_UNAVAILABLE")
        selected = history[-needed:]
        if (
            expected is not None
            and tuple(item.session_key for item in selected) != expected
        ):
            raise ValueError("CONTROLLED_FAMILY_CALENDAR_GAP")
        if any(C.finite_fraction(item.close_price) <= 0 for item in selected):
            raise ValueError("CONTROLLED_FAMILY_PRICE_INVALID")
    strategy = installed(family)
    with decimal_context():
        intent = (
            strategy.decide(context)
            if isinstance(context, StrategyDecisionContextV1)
            else strategy.decide_exploratory(context)
        )
    if not any(item.target_quantity > 0 for item in intent.targets):
        raise ValueError("CONTROLLED_EMPTY_FAMILY_TARGET_UNAVAILABLE")
    return C.detached(StrategyDecisionIntentV1, intent)


def close_prices(context: DecisionContext) -> dict[UUID, Decimal]:
    prices: dict[UUID, Decimal] = {}
    for security in get_admitted_securities(context):
        history = extract_security_history(context, security)
        if not history or history[-1].session_key != context.session_key:
            raise ValueError("CONTROLLED_CURRENT_PRICE_UNAVAILABLE")
        price = history[-1].close_price
        if C.finite_fraction(price) <= 0:
            raise ValueError("CONTROLLED_CURRENT_PRICE_INVALID")
        prices[security] = price
    return prices


def current_book_reason(
    mandate: C.SyntheticMandateV1,
    state: PortfolioStateV2,
    prices: Mapping[UUID, Decimal] | None = None,
) -> str | None:
    if mandate.execution_knowledge != "RESOLVED":
        return "EXECUTION_STATE_UNRESOLVED"
    if prices is None:
        if state.mark is None:
            return "UNMARKED_CURRENT_BOOK"
        prices = {item.security_id: item.close_price for item in state.mark.prices}
    return C.portfolio_mandate_reason(
        mandate=mandate,
        quantities={h.security_id: h.quantity for h in state.holdings},
        prices=prices,
        cash=state.cash_balance,
        pending_claims=state.pending_claims_value,
    )


def decision_mandate_reason(
    mandate: C.SyntheticMandateV1,
    context: DecisionContext,
    state: PortfolioStateV2,
    intent: StrategyDecisionIntentV1,
) -> str | None:
    if mandate.paused:
        return "PAUSED"
    if mandate.execution_knowledge != "RESOLVED":
        return "EXECUTION_STATE_UNRESOLVED"
    prices = close_prices(context)
    targets = {t.security_id: t.target_quantity for t in intent.targets}
    if any(security not in prices for security in targets):
        return "PRICE_UNAVAILABLE"
    nav, pending = (
        C.finite_fraction(state.net_asset_value),
        C.finite_fraction(state.pending_claims_value),
    )
    gross = sum(
        (
            quantity * C.finite_fraction(prices[security])
            for security, quantity in targets.items()
        ),
        Fraction(0),
    )
    reason = C.portfolio_mandate_reason(
        mandate=mandate,
        quantities=targets,
        prices=prices,
        cash=C.exact_decimal(nav - pending - gross),
        pending_claims=state.pending_claims_value,
    )
    if reason is not None:
        return reason
    held = {h.security_id: h.quantity for h in state.holdings}
    turnover = sum(
        (
            abs(targets.get(s, 0) - held.get(s, 0)) * C.finite_fraction(prices[s])
            for s in set(targets) | set(held)
        ),
        Fraction(0),
    )
    if turnover > nav * C.finite_fraction(mandate.maximum_turnover_fraction):
        return "TURNOVER_CAP"
    return None


def authorize_preview(
    mandate: C.SyntheticMandateV1,
    preview: RebalancePreviewV1,
    *,
    execution_at: datetime | None = None,
    proposal_deadline: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ExecutionAuthorizationV1:
    mandate, preview = (
        C.detached(C.SyntheticMandateV1, mandate),
        C.detached(RebalancePreviewV1, preview),
    )
    prices = {p.security_id: p.quote.unadjusted_open_price for p in preview.open_prices}
    verdict: Literal["approve", "reject", "contain"] = "approve"
    reason = current_book_reason(mandate, preview.before_state, prices)
    if reason is not None:
        verdict = "contain"
    elif mandate.paused:
        verdict, reason = "reject", "PAUSED"
    elif proposal_deadline is not None and (
        execution_at is None
        or execution_at >= proposal_deadline
        or (revoked_at is not None and execution_at >= revoked_at)
    ):
        verdict, reason = "reject", "PROPOSAL_EXPIRED_OR_REVOKED_BEFORE_EXECUTION"
    elif preview.outcome.classification == "rejected":
        verdict, reason = "reject", "ACCOUNTING_REJECTED"
    else:
        reason = current_book_reason(mandate, preview.outcome.state, prices)
        if reason is not None:
            verdict = "reject"
        else:
            nav = C.finite_fraction(
                preview.before_state.cash_balance
            ) + C.finite_fraction(preview.before_state.pending_claims_value)
            nav += sum(
                (
                    h.quantity * C.finite_fraction(prices[h.security_id])
                    for h in preview.before_state.holdings
                ),
                Fraction(0),
            )
            turnover = sum(
                (
                    f.quantity * C.finite_fraction(f.unadjusted_open_price)
                    for f in preview.outcome.committed_fills
                ),
                Fraction(0),
            )
            if turnover > nav * C.finite_fraction(mandate.maximum_turnover_fraction):
                verdict, reason = "reject", "TURNOVER_CAP"
    return ExecutionAuthorizationV1(
        preview_hash=preview.financial_hash,
        policy_hash=mandate.policy_hash,
        verdict=verdict,
        reason=reason or "EXACT_OPEN_MANDATE_SATISFIED",
    )


def choice_for_family(
    family: C.Family,
    context: DecisionContext,
    sessions: tuple[EvaluationSessionV1, ...],
) -> RawChoice:
    """Finite display weights of actual installed quantities; never new targets.

    Floor only the *display* at 18 decimal places, with exact residual cash.
    Actual whole-share intent is retained, replayed and executed unchanged.
    """
    intent = installed_intent(family, context, sessions)
    prices = close_prices(context)
    nav = C.finite_fraction(context.portfolio_nav)
    if nav <= 0:
        raise ValueError("CONTROLLED_NONPOSITIVE_CONTEXT_NAV")
    scale = 10**18
    weights: list[TargetWeight] = []
    units = 0
    for target in intent.targets:
        if target.target_quantity <= 0:
            continue
        ratio = (
            target.target_quantity * C.finite_fraction(prices[target.security_id]) / nav
        )
        amount = ratio.numerator * scale // ratio.denominator
        if amount <= 0:
            raise ValueError("CONTROLLED_DISPLAY_PRECISION_INSUFFICIENT")
        units += amount
        weights.append(
            TargetWeight(
                security_id=str(target.security_id),
                weight=format(C.exact_decimal(Fraction(amount, scale)), "f"),
            )
        )
    if units > scale:
        raise ValueError("CONTROLLED_UNFUNDED_INSTALLED_TARGET")
    return RawChoice(
        disposition="propose",
        selection=StrategySelection(family_id=family, strategy_version="1"),
        targets=tuple(weights),
        cash_weight=format(C.exact_decimal(Fraction(scale - units, scale)), "f"),
        rationale="Offline installed-family quantity display; not an efficacy claim.",
    )


def research_dependencies(
    context: ResearchContext, incumbent: C.Family, securities: tuple[UUID, ...]
) -> ResolvedDependencies:
    return ResolvedDependencies(
        portfolio_ref=context.portfolio_ref,
        mandate_ref=context.mandate_ref,
        universe_ref=context.universe_ref,
        registry_ref=context.registry_ref,
        method_ref=context.method_ref,
        admitted_securities=tuple(str(s) for s in securities),
        strategy_registry={
            family: installed_strategy_registration(family)
            for family in ("B3", "B4", "B5")
        },
        current_selection=StrategySelection(family_id=incumbent, strategy_version="1"),
    )


def make_research_context(
    plan: C.ControlledCampaignPlanV1,
    checkpoint: C.ControlledCheckpointV1,
    context: DecisionContext,
    observation: SessionObservationV1,
    learning: LearningSnapshot,
    available_at: datetime,
    incumbent: C.Family,
) -> ResearchContext:
    payload = plan.context_template.model_dump(mode="python")
    payload.update(
        {
            "context_id": plan.trial_id(checkpoint.checkpoint_id) + ":context",
            "decision_cutoff": checkpoint.decision_cutoff,
            "built_at": available_at,
            "review_started_at": available_at,
            "review_reason": "Declared synthetic monthly checkpoint",
            "clock_policy_ref": plan.clock_policy.model_dump(mode="python"),
            "budget_ref": {
                "id": plan.trial_id(checkpoint.checkpoint_id) + ":budget",
                "version": C.PROFILE,
                "sha256": content_hash(checkpoint.research_budget_usd),
            },
            "portfolio_ref": {
                "id": plan.original_account.fields.portfolio_account_id
                + ":marked:"
                + checkpoint.checkpoint_id,
                "version": C.PROFILE,
                "sha256": content_hash(observation.state),
            },
            "mandate_ref": {
                "id": plan.mandate.policy_id,
                "version": plan.mandate.revision,
                "sha256": plan.mandate.policy_hash,
            },
            "universe_ref": synthetic_universe_reference(plan.securities).model_dump(
                mode="python"
            ),
            "registry_ref": installed_registry_reference().model_dump(mode="python"),
            "memory_snapshot_ref": {
                "id": learning.snapshot_id,
                "version": f"v{learning.version}",
                "sha256": learning.state_hash,
            },
            "memory_cutoff": learning.cutoff,
            "inputs": (
                {
                    "input_ref": {
                        "id": plan.trial_id(checkpoint.checkpoint_id)
                        + ":original-decision-context",
                        "version": C.PROFILE,
                        "sha256": content_hash(context),
                    },
                    "role": "original_synthetic_evaluator_context",
                    "transformation_ref": None,
                    "available_at": checkpoint.decision_cutoff,
                    "availability_basis_ref": {
                        "id": "synthetic:evaluator-clock:" + plan.input_bundle_hash,
                        "version": C.PROFILE,
                        "sha256": plan.input_bundle_hash,
                    },
                },
            ),
            "feedback_refs": tuple(
                {
                    "id": item.trial_id,
                    "version": C.PROFILE,
                    "sha256": content_hash(item),
                }
                for item in learning.matured_trials
            ),
            "limitations": (
                "SYNTHETIC_ENGINEERING_ONLY",
                "INSTALLED_HOST_TRUSTED",
                "NO_SOURCE_QUALIFICATION_OR_EFFICACY",
            ),
            "current_selection_ref": {
                "id": incumbent,
                "version": "1",
                "sha256": installed(incumbent).strategy_reference.code_hash,
            },
            "trigger_ref": None,
            "excluded_inputs_ref": None,
            "feed_state_ref": None,
        }
    )
    payload["record_hash"] = compute_record_hash(payload)
    return C.detached(ResearchContext, ResearchContext.model_validate(payload))


class _DurableResearchStore(ResearchReceiptStore):
    def __init__(
        self,
        writer: ControlledJournalWriterV1,
        checkpoint: str,
        grant: C.OriginalReferenceV1,
    ) -> None:
        super().__init__()
        self.writer, self.checkpoint, self.grant = writer, checkpoint, grant

    def record_attempt(self, attempt: AttemptRecord) -> None:
        super().record_attempt(attempt)
        self.writer.append(
            C.AttemptRecordV1(
                checkpoint_id=self.checkpoint, grant=self.grant, original=attempt
            ),
            key="attempt:" + attempt.attempt_event_id,
        )

    def record_cost_receipt(self, cost: CostReceipt) -> None:
        super().record_cost_receipt(cost)
        self.writer.append(
            C.CostRecordV1(
                checkpoint_id=self.checkpoint, grant=self.grant, original=cost
            ),
            key="cost:" + cost.receipt_id,
        )


@dataclass(frozen=True, slots=True)
class ControlledCampaignExecutionV1:
    allocation_id: UUID
    manifest: C.OriginalReferenceV1
    terminal: C.OriginalReferenceV1 | None
    m0_run_id: UUID
    m0_audit_event_id: UUID
    m0_status: str


class _ControlledStrategy:
    """One installed host controls one prepared account, never a fresh retry."""

    def __init__(
        self, plan: C.ControlledCampaignPlanV1, writer: ControlledJournalWriterV1
    ) -> None:
        self.plan, self.writer = plan, writer
        self.active: C.Family = "B3"
        self.observation: SessionObservationV1 | None = None
        self.observation_ref: C.OriginalReferenceV1 | None = None
        self.last_decision: C.DecisionRecordV1 | None = None
        self.last_decision_ref: C.OriginalReferenceV1 | None = None
        self.learning: LearningSnapshot | None = None
        self.previous_trial: (
            tuple[C.ControlledCheckpointV1, ResearchCandidate, Decimal] | None
        ) = None
        self.checkpoints = {c.session_index: c for c in plan.checkpoints}

    @property
    def strategy_reference(self) -> StrategyReference:
        return controlled_strategy_reference()

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return financial_parameters(self.plan)

    def observe_session(self, observation: SessionObservationV1) -> None:
        observation = C.detached(SessionObservationV1, observation)
        index = observation.session_index
        if observation.session != self.plan.sessions[index]:
            raise ValueError("CONTROLLED_WRONG_OBSERVED_SESSION")
        self.observation = observation
        self.observation_ref = reference(
            self.writer.append(
                C.ObservationRecordV1(observation=observation),
                key=f"observation:{index}",
            )
        )
        reason = current_book_reason(self.plan.mandate, observation.state)
        if reason is not None:
            self.writer.append(
                C.ContainmentRecordV1(observation=self.observation_ref, reason=reason),
                key=f"containment:{index}",
            )
            raise IndeterminateValuationError("CONTROLLED_CURRENT_BOOK:" + reason)

    def authorize_rebalance(
        self, preview: RebalancePreviewV1
    ) -> ExecutionAuthorizationV1:
        if self.last_decision is None or self.last_decision_ref is None:
            raise ValueError("CONTROLLED_EXECUTION_WITHOUT_ORIGINAL_DECISION")
        if (
            preview.decision_session
            != self.plan.sessions[self.last_decision.session_index]
        ):
            raise ValueError("CONTROLLED_EXECUTION_WRONG_DECISION_SESSION")
        execution_at = observed_time(self.writer.clock)
        checkpoint = self.checkpoints.get(self.last_decision.session_index)
        selected = (
            checkpoint is not None and self.last_decision.disposition == "SELECTED"
        )
        authorization = authorize_preview(
            self.plan.mandate,
            preview,
            execution_at=execution_at,
            proposal_deadline=checkpoint.expires_at
            if checkpoint and selected
            else None,
            revoked_at=checkpoint.revoked_at if checkpoint and selected else None,
        )
        self.writer.append(
            C.ExecutionRecordV1(
                preview=C.RetainedCanonicalPayloadV1.retain(preview),
                authorization=authorization,
                decision=self.last_decision_ref,
            ),
            key=f"execution:{preview.session_index}",
            at=execution_at,
        )
        if (
            authorization.verdict == "approve"
            and preview.outcome.classification != "rejected"
        ):
            self.active = self.last_decision.staged_family
            if (
                checkpoint is not None
                and selected
                and self.pending_candidate is not None
            ):
                assert self.observation is not None
                self.previous_trial = (
                    checkpoint,
                    self.pending_candidate,
                    self.observation.state.net_asset_value,
                )
        return authorization

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._decide(context)

    def decide_exploratory(
        self, context: ExploratoryStrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        return self._decide(context)

    def _research(
        self, checkpoint: C.ControlledCheckpointV1, context: DecisionContext
    ) -> tuple[C.Family | None, ResearchCandidate | None, str]:
        assert self.observation is not None and self.observation_ref is not None
        observation = self.observation
        feedback: tuple[TrialFeedbackRecord, ...] = ()
        if self.previous_trial is not None:
            prior, candidate, nav = self.previous_trial
            feedback = (
                TrialFeedbackRecord(
                    trial_id=self.plan.trial_id(prior.checkpoint_id),
                    arm_id=self.plan.original_account.fields.arm_id,
                    decision_cutoff=prior.decision_cutoff,
                    matured_at=checkpoint.decision_cutoff,
                    candidate_id=candidate.candidate_id,
                    status="completed",
                    pnl=format(
                        C.exact_decimal(
                            C.finite_fraction(observation.state.net_asset_value)
                            - C.finite_fraction(nav)
                        ),
                        "f",
                    ),
                    metrics={
                        "original_start_nav": format(nav, "f"),
                        "original_end_nav": format(
                            observation.state.net_asset_value, "f"
                        ),
                    },
                    is_complete=True,
                    is_holdout=False,
                ),
            )
        learning = advance_learning(
            previous_snapshot=self.learning,
            feedback_records=feedback,
            cutoff=checkpoint.decision_cutoff,
            arm_id=self.plan.original_account.fields.arm_id,
            method_ref=self.plan.context_template.method_ref,
            snapshot_id=self.plan.trial_id(checkpoint.checkpoint_id) + ":learning",
        )
        self.learning = learning
        # The preceding interval is matured once. A refused next proposal
        # cannot attribute incumbent performance to an unexecuted candidate.
        self.previous_trial = None
        at = observed_time(self.writer.clock)
        research_context = make_research_context(
            self.plan, checkpoint, context, observation, learning, at, self.active
        )
        witness = self.writer.append(
            C.InputWitnessRecordV1(
                checkpoint_id=checkpoint.checkpoint_id,
                observation=self.observation_ref,
                context_kind=context_kind(context),
                decision_context=C.RetainedCanonicalPayloadV1.retain(context),
                research_context=research_context,
                learning=learning,
                feedback=feedback,
                original_available_at=at,
            ),
            key="input:" + checkpoint.checkpoint_id,
            at=at,
        )
        trial = self.plan.trial_id(checkpoint.checkpoint_id)
        grant_record = C.GrantRecordV1(
            checkpoint_id=checkpoint.checkpoint_id,
            input_witness=reference(witness),
            logical_request_id=trial + ":REQUEST-001",
            attempt_id=trial + ":K1-001",
            not_before=checkpoint.not_before,
            expires_at=checkpoint.expires_at,
            budget_usd=checkpoint.research_budget_usd,
        )
        grant = reference(
            self.writer.append(grant_record, key="grant:" + checkpoint.checkpoint_id)
        )
        if checkpoint.revoked_at is not None:
            self.writer.append(
                C.RevocationRecordV1(
                    checkpoint_id=checkpoint.checkpoint_id,
                    grant=grant,
                    effective_at=checkpoint.revoked_at,
                    reason="Declared synthetic grant revocation",
                ),
                key="revocation:" + checkpoint.checkpoint_id,
            )
        start = observed_time(self.writer.clock)
        skip: (
            Literal[
                "NOT_YET_VALID",
                "EXPIRED",
                "REVOKED",
                "INPUT_UNAVAILABLE",
                "BUDGET_UNAVAILABLE",
            ]
            | None
        ) = None
        if start < checkpoint.not_before:
            skip = "NOT_YET_VALID"
        elif start >= checkpoint.expires_at:
            skip = "EXPIRED"
        elif checkpoint.revoked_at is not None and start >= checkpoint.revoked_at:
            skip = "REVOKED"
        elif checkpoint.fixture.cost_amount > checkpoint.research_budget_usd:
            skip = "BUDGET_UNAVAILABLE"
        pool: tuple[RawChoice, ...] = ()
        scripted: RawChoice | None = None
        try:
            fixture = checkpoint.fixture
            if fixture.mode == "conventional_fixture":
                pool = tuple(
                    choice_for_family(family, context, self.plan.sessions)
                    for family in fixture.candidate_families
                )
            elif fixture.disposition == "propose":
                assert fixture.selected_family is not None
                scripted = choice_for_family(
                    fixture.selected_family, context, self.plan.sessions
                )
            else:
                scripted = RawChoice(
                    disposition=fixture.disposition,
                    selection=StrategySelection(
                        family_id=self.active, strategy_version="1"
                    )
                    if fixture.disposition == "hold"
                    else None,
                    targets=(),
                    cash_weight=None,
                    rationale="Declared bounded synthetic nonproposal.",
                )
        except ValueError:
            if skip is None:
                skip = "INPUT_UNAVAILABLE"
        if skip is not None:
            self.writer.append(
                C.NoAttemptRecordV1(
                    checkpoint_id=checkpoint.checkpoint_id, grant=grant, reason=skip
                ),
                key="no-attempt:" + checkpoint.checkpoint_id,
                at=start,
            )
            self.previous_trial = None
            return None, None, skip
        recorder = _DurableResearchStore(self.writer, checkpoint.checkpoint_id, grant)
        resolved = research_dependencies(
            research_context, self.active, self.plan.securities
        )
        validation_policy = ArtifactReference(
            id="synthetic:controlled-original-validation",
            version=C.PROFILE,
            sha256=content_hash(C.PROFILE),
        )
        validation_index = 0

        def observe(
            raw: str, binding: TrustedInvocationBinding, result: ValidationResult
        ) -> None:
            nonlocal validation_index
            self.writer.append(
                C.ValidationRecordV1(
                    checkpoint_id=checkpoint.checkpoint_id,
                    grant=grant,
                    raw_output_utf8=raw,
                    binding=binding,
                    original=result,
                ),
                key=f"validation:{checkpoint.checkpoint_id}:{validation_index}",
            )
            validation_index += 1

        output: ResearchOutput
        selected_candidate: ResearchCandidate | None
        with decimal_context():
            if fixture.mode == "scripted_fixture":
                output = produce_proposal(
                    context=research_context,
                    resolved_inputs=resolved,
                    validation_policy=validation_policy,
                    recorder=recorder,
                    attempt_id=grant_record.attempt_id,
                    logical_request_id=grant_record.logical_request_id,
                    checked_at=start,
                    valid_until=checkpoint.expires_at,
                    validation_observer=observe,
                    frozen_method=research_context.method_ref,
                    transport=FakeTransport(
                        raw_choice=scripted,
                        should_timeout=fixture.should_timeout,
                        malformed_json=fixture.malformed_output,
                        cost_amount=format(fixture.cost_amount, "f"),
                    ),
                )
                selected_candidate = output.candidate
            else:

                def score(candidate: ResearchCandidate) -> Decimal:
                    if candidate.strategy is None:
                        raise ValueError("CONTROLLED_COMPARATOR_MISSING_FAMILY")
                    return fixture.scores[candidate.strategy.family_id]

                output = select_conventional_candidate(
                    context=research_context,
                    resolved_inputs=resolved,
                    validation_policy=validation_policy,
                    recorder=recorder,
                    attempt_id=grant_record.attempt_id,
                    logical_request_id=grant_record.logical_request_id,
                    checked_at=start,
                    valid_until=checkpoint.expires_at,
                    validation_observer=observe,
                    method_ref=research_context.method_ref,
                    candidate_pool=pool,
                    objective_fn=score,
                )
                selected_candidate = output.selected_candidate
        finished = observed_time(self.writer.clock)
        self.writer.append(
            C.ResearchOutputRecordV1(
                completed_observed_at=finished,
                checkpoint_id=checkpoint.checkpoint_id,
                grant=grant,
                output_utf8=canonical_json(output).decode(),
            ),
            key="output:" + checkpoint.checkpoint_id,
            at=finished,
        )
        costs = recorder.get_cost_receipts_for_attempt(grant_record.attempt_id)
        if not output.is_success or selected_candidate is None:
            self.previous_trial = None
            return None, selected_candidate, "RESEARCH_" + output.status
        if finished >= checkpoint.expires_at or (
            checkpoint.revoked_at is not None and finished >= checkpoint.revoked_at
        ):
            return None, selected_candidate, "RESEARCH_READY_OUTSIDE_GRANT"
        if any(cost.amount_basis == "unknown" for cost in costs) or not costs:
            return None, selected_candidate, "COST_UNAVAILABLE"
        total = sum(
            (
                Fraction(Decimal(cost.amount))
                for cost in costs
                if cost.amount is not None
            ),
            Fraction(0),
        )
        if total > C.finite_fraction(checkpoint.research_budget_usd):
            return None, selected_candidate, "BUDGET_EXCEEDED"
        if (
            selected_candidate.disposition != "propose"
            or selected_candidate.strategy is None
        ):
            return (
                None,
                selected_candidate,
                "RESEARCH_" + selected_candidate.disposition.upper(),
            )
        family = cast(C.Family, selected_candidate.strategy.family_id)
        expected = choice_for_family(family, context, self.plan.sessions)
        if (
            selected_candidate.targets != expected.targets
            or selected_candidate.cash_weight != expected.cash_weight
        ):
            raise ValueError("CONTROLLED_CANDIDATE_NOT_INSTALLED_TARGET")
        return family, selected_candidate, "VALIDATED_ORIGINAL_SELECTION"

    def _decide(self, context: DecisionContext) -> StrategyDecisionIntentV1:
        if self.observation is None or self.observation_ref is None:
            raise ValueError("CONTROLLED_DECISION_WITHOUT_OBSERVATION")
        observation = self.observation
        index = observation.session_index
        if (
            context.session_key != observation.session.session_key
            or context.portfolio_nav != observation.state.net_asset_value
            or context.current_cash != observation.state.cash_balance
        ):
            raise ValueError("CONTROLLED_CONTEXT_NOT_ORIGINAL_BOOK")
        context_holdings = tuple(
            (h.security_id, h.quantity) for h in context.current_holdings
        )
        actual_holdings = tuple(
            (h.security_id, h.quantity) for h in observation.state.holdings
        )
        if context_holdings != actual_holdings:
            raise ValueError("CONTROLLED_CONTEXT_HOLDINGS_MISMATCH")
        checkpoint = self.checkpoints.get(index)
        previous = proposed = staged = self.active
        candidate = None
        disposition: Literal[
            "INSTALLED", "SELECTED", "RETAINED", "REFUSED", "UNAVAILABLE"
        ] = "INSTALLED"
        reason = "INSTALLED_FAMILY_INTERNAL_DECISION"
        if checkpoint is not None:
            selected, candidate, reason = self._research(checkpoint, context)
            if selected is not None:
                proposed = selected
                disposition = "SELECTED"
            else:
                disposition = "RETAINED"
        if index < self.plan.initial_decision_index:
            intent = hold_intent(context)
            reason = "DECLARED_PREPARATION_CASH_NO_RESEARCH"
        else:
            try:
                intent = installed_intent(proposed, context, self.plan.sessions)
                refusal = decision_mandate_reason(
                    self.plan.mandate, context, observation.state, intent
                )
            except ValueError as error:
                refusal = str(error)
                intent = hold_intent(context)
            if refusal is not None:
                disposition, reason = "REFUSED", refusal
                # Current-state containment already ran independently. Rejection
                # preserves actual quantities, not a guessed liquidation.
                intent = hold_intent(context)
                staged = previous
            else:
                staged = proposed
        self.pending_candidate = (
            C.detached(ResearchCandidate, candidate)
            if candidate is not None and disposition == "SELECTED"
            else None
        )
        record = C.DecisionRecordV1(
            session_index=index,
            checkpoint_id=checkpoint.checkpoint_id if checkpoint else None,
            observation=self.observation_ref,
            context_kind=context_kind(context),
            decision_context=C.RetainedCanonicalPayloadV1.retain(context),
            previous_family=previous,
            proposed_family=proposed,
            staged_family=staged,
            candidate_hash=candidate.record_hash if candidate else None,
            intent=intent,
            disposition=disposition,
            reason=reason,
        )
        event = self.writer.append(record, key=f"decision:{index}")
        self.last_decision, self.last_decision_ref = record, reference(event)
        return C.detached(StrategyDecisionIntentV1, intent)


def execute_controlled_campaign(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    provenance: Stage1TrialProvenanceSnapshotV1,
    account: Stage1SyntheticAccountLifecycleV1,
    engine: SessionEvaluatorEngine,
    context: ResearchContext,
    clock: Callable[[], datetime],
    mandate: C.SyntheticMandateV1,
    checkpoints: tuple[C.ControlledCheckpointV1, ...],
    initial_decision_index: int,
    coverage: Literal["DEVELOPMENT", "STAGE1_253_126_MONTHLY"],
    clock_policy: ArtifactReference,
) -> ControlledCampaignExecutionV1:
    """Consume one prepared account exactly once; repeated checkpoints carry it."""
    if campaign.campaign_type != "SYNTHETIC_TEST":
        raise ValueError("CONTROLLED_SYNTHETIC_CAMPAIGN_ONLY")
    verify_stage1_trial_provenance_snapshot(
        snapshot=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    original = account.verified_original()
    observer = Stage1OriginalResultAssociationV1(
        origin=origin,
        account=account,
        provenance=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        clock=clock,
    )
    plan = C.ControlledCampaignPlanV1(
        original_account=C.OriginalAccountDescriptorV1(
            allocation_id=original.allocation_id,
            allocation=C.OriginalReferenceV1(
                event_id=original.allocation_ref.event_id,
                event_hash=original.allocation_ref.event_hash,
            ),
            witness=C.OriginalReferenceV1(
                event_id=original.witness_ref.event_id,
                event_hash=original.witness_ref.event_hash,
            ),
            fields=original.fields,
            original_book_hash=content_hash(original.opening_book),
        ),
        provenance_hash=provenance.snapshot_fingerprint,
        input_bundle_hash=engine.bundle.bundle_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        protocol_hash=engine.protocol.protocol_hash,
        admission_hash=engine.admission.admission_hash,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        source_inventory_hash=drift_source_inventory_hash(),
        securities=tuple(
            sorted(
                (s.security_id for s in engine.bundle.security_identities),
                key=lambda s: s.bytes,
            )
        ),
        sessions=engine.bundle.session_clock.sessions,
        initial_decision_index=initial_decision_index,
        coverage=coverage,
        context_template=C.detached(ResearchContext, context),
        mandate=mandate,
        checkpoints=checkpoints,
        clock_policy=clock_policy,
    )
    C.verify_declared_stage1_plan(plan, campaign, arms)
    allowed = next(
        arm for arm in arms if arm.arm_id == original.fields.arm_id
    ).eligible_strategy_references
    if any(
        f not in allowed or f not in campaign.allowed_strategy_families
        for f in ("B3", "B4", "B5")
    ):
        raise ValueError("CONTROLLED_FAMILIES_NOT_ALLOWED_BY_MANIFEST")
    if initial_decision_index < engine.protocol.warmup_session_count - 1:
        raise ValueError("CONTROLLED_INITIAL_BEFORE_ENGINE_WARMUP")
    writer = ControlledJournalWriterV1(origin=origin, plan=plan, clock=clock)
    run_id, audit_id = uuid7(), uuid7()
    witness_at = observed_time(clock)
    if witness_at < original.receipt_observed_available_by_at:
        raise ValueError("CONTROLLED_SCHEDULER_HAS_NOT_OBSERVED_WITNESS")
    manifest = writer.append(
        C.ManifestRecordV1(
            plan=plan,
            scheduler_witness_observed_at=witness_at,
            original_witness=plan.original_account.witness,
            m0_run_id=run_id,
            m0_audit_event_id=audit_id,
        ),
        key="manifest",
        at=witness_at,
    )
    strategy = _ControlledStrategy(plan, writer)
    identity = build_canonical_run_identity(
        strategy_hash=strategy.strategy_reference.code_hash,
        strategy_parameters_hash=strategy_parameters_hash(strategy.strategy_parameters),
        protocol_hash=engine.protocol.protocol_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        admission=engine.admission,
        bundle=engine.bundle,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        code_version_hash=plan.source_inventory_hash,
    )
    specification = build_canonical_specification(
        strategy=strategy,
        bundle=engine.bundle,
        dataset_reference=make_bundle_dataset_reference(
            engine.bundle,
            source=(
                "Controlled installed-family synthetic campaign; "
                "no historical qualification"
            ),
        ),
    )
    started_at = observed_time(clock)
    run = execute_experiment_run(
        specification,
        ExperimentRunnerContext(
            run_id=run_id,
            started_at=started_at,
            completed_at=started_at,
            engine=engine,
            strategy=strategy,
            run_identity=identity,
            result_artifact_id=uuid7(),
            trace_artifact_id=uuid7(),
            result_artifact_location=f"synthetic://{original.allocation_id}/result",
            trace_artifact_location=f"synthetic://{original.allocation_id}/trace",
            ledger=SQLiteLedger(origin.ledger_path),
            audit_event_id=audit_id,
            original_result_observer=observer,
            session_observer=strategy,
            completion_clock=clock,
        ),
    )
    terminal = None
    if run.status.value != "failed":
        result = observer.readback()
        terminal = reference(
            writer.append(
                C.TerminalRecordV1(
                    m0_run_id=run_id,
                    m0_audit_event_id=audit_id,
                    m0_status="completed",
                    result_association=C.OriginalReferenceV1(
                        event_id=result.association_ref.event_id,
                        event_hash=result.association_ref.event_hash,
                    ),
                    classification=cast(
                        Literal["complete", "rejected", "indeterminate"],
                        result.classification,
                    ),
                ),
                key="terminal",
            )
        )
    # A failed/uncertain invocation is intentionally not relabelled complete.
    # Its original M0 failure remains readable, and no account can be retried.
    return ControlledCampaignExecutionV1(
        original.allocation_id,
        reference(manifest),
        terminal,
        run_id,
        audit_id,
        run.status.value,
    )
