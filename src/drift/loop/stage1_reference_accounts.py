"""Original isolated B3/B4/B5 books and causal completed-reference views.

The installed host supplies the original E1 configuration and ledger origin.
Every reference is a distinct engine-created account consumed by the ordinary
M0 runner. This module never calculates a parallel cash or holdings ledger.
Its public context contains only completed marks at the requested cutoff;
original terminal locators and later classifications stay in the audit layer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, fields
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal, Self, cast
from uuid import UUID, uuid7

from pydantic import Field, model_validator

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
from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSONValue,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    strategy_parameters_hash,
)
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_exploratory_strategy import (
    ExploratoryStrategyDecisionContextV1,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_protocol import EvaluationProtocolV1
from drift.domain.evaluator_reconstruction import _with_reconstruction_validation_reuse
from drift.domain.evaluator_results import EvaluationRunArtifactsV2
from drift.domain.evaluator_strategy import (
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
)
from drift.domain.observation_query import drift_source_inventory_hash
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference
from drift.evaluator.engine import SessionEvaluatorEngine
from drift.evaluator.experiment_runner import (
    ExperimentRunnerContext,
    execute_experiment_run,
)
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    build_arm_spec,
    build_campaign_spec,
    build_run_account_binding,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    build_stage1_trial_provenance_snapshot,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop.stage1_original_result_association import (
    Stage1OriginalResultAssociationV1,
    read_original_result,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json, content_hash

PROFILE: Literal["drift-stage1-original-reference-accounts/1"] = (
    "drift-stage1-original-reference-accounts/1"
)
EVENT = "stage1.reference_account.original_retained"
ENTITY = "stage1_reference_account"
type Family = Literal["B3", "B4", "B5"]
FAMILIES: tuple[Family, ...] = ("B3", "B4", "B5")
REQUIRED_HISTORY = {"B3": 1, "B4": 253, "B5": 61}
OBSERVATION_INTERVALS = 126
type DecisionContext = StrategyDecisionContextV1 | ExploratoryStrategyDecisionContextV1


def _copy[M: FrozenModel](cls: type[M], value: M) -> M:
    return cls.model_validate_json(canonical_json(value))


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError("REFERENCE_CLOCK_REQUIRES_AWARE_INSTANT")
    return value.astimezone(UTC)


class ReferenceEventV1(FrozenModel):
    event_id: UUID7
    event_hash: SHA256Hash

    def local(self) -> LocalEventReferenceV1:
        return LocalEventReferenceV1(UUID(int=self.event_id.int), self.event_hash)


class ReferenceArmV1(FrozenModel):
    family: Family
    arm_id: NonBlankStr


class ReferenceEnvironmentV1(FrozenModel):
    """Expected source identities supplied by the trusted installed host."""

    input_bundle_hash: SHA256Hash
    admission_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    evaluator_evidence_hash: SHA256Hash
    source_inventory_hash: SHA256Hash
    protocol: EvaluationProtocolV1
    sessions: tuple[EvaluationSessionV1, ...] = Field(min_length=2)
    securities: tuple[UUID7, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_reference_protocol(self) -> Self:
        if self.protocol.warmup_session_count != 1:
            raise ValueError("REFERENCE_ENGINE_REQUIRES_EXPLICIT_WARMUP_ONE")
        if self.protocol.initial_cash != Decimal("10000"):
            raise ValueError("REFERENCE_REQUIRES_FRESH_10000")
        keys = tuple(s.session_key for s in self.sessions)
        if len(set(keys)) != len(keys) or any(
            left.closed_at >= right.opened_at for left, right in pairwise(self.sessions)
        ):
            raise ValueError("REFERENCE_SESSION_ORDER")
        if self.securities != tuple(
            sorted(set(self.securities), key=lambda s: s.bytes)
        ):
            raise ValueError("REFERENCE_SECURITY_ORDER")
        return self


class ReferenceCampaignConfigurationV1(FrozenModel):
    """Explicit E1 reference controls; no claimed issuer flag authenticates them."""

    profile: Literal["drift-stage1-original-reference-accounts/1"] = PROFILE
    campaign: CampaignSpecV1
    arms: tuple[ArmSpecV1, ...]
    bindings: tuple[RunAccountBindingV1, ...]
    expected_run_ids: tuple[str, ...]
    run_id: NonBlankStr
    checkpoint_id: NonBlankStr = "REFERENCE-ORIGINAL"
    reference_arms: tuple[ReferenceArmV1, ...]
    environment: ReferenceEnvironmentV1

    @model_validator(mode="after")
    def require_isolated_declared_controls(self) -> Self:
        verify_stage1_synthetic_br_configuration(
            campaign=self.campaign,
            arms=self.arms,
            bindings=self.bindings,
            expected_run_ids=self.expected_run_ids,
        )
        if self.run_id not in self.expected_run_ids:
            raise ValueError("REFERENCE_RUN_OUTSIDE_MANIFEST")
        if tuple(a.family for a in self.reference_arms) != FAMILIES:
            raise ValueError("REFERENCE_REQUIRES_ORDERED_B3_B4_B5")
        if len({a.arm_id for a in self.reference_arms}) != 3:
            raise ValueError("REFERENCE_ACCOUNTS_MUST_BE_DISTINCT")
        for reference in self.reference_arms:
            matches = [a for a in self.arms if a.arm_id == reference.arm_id]
            if len(matches) != 1:
                raise ValueError("REFERENCE_ARM_OUTSIDE_MANIFEST")
            arm = matches[0]
            if (
                arm.arm_id not in self.campaign.control_arm_references
                or arm.selector_type != "FROZEN_BASELINE"
                or arm.arm_account_role != "COUNTERFACTUAL_REFERENCE"
                or arm.initial_strategy_reference != reference.family
                or arm.eligible_strategy_references != (reference.family,)
                or arm.model_configuration_reference != "NONE"
            ):
                raise ValueError("REFERENCE_REQUIRES_EXPLICIT_FIXED_FAMILY_CONTROL")
        return self


class ReferenceDecisionV1(FrozenModel):
    """Installed wrapper eligibility, bound to its actual evaluator decision."""

    session_index: int = Field(ge=0, strict=True)
    context_hash: SHA256Hash
    intent_hash: SHA256Hash
    eligible: bool
    reason: NonBlankStr | None

    @model_validator(mode="after")
    def require_reason(self) -> Self:
        if self.eligible == (self.reason is not None):
            raise ValueError("REFERENCE_ELIGIBILITY_REASON")
        return self


class ReferenceAccountReceiptV1(FrozenModel):
    family: Family
    allocation_id: UUID7
    allocation: ReferenceEventV1
    witness: ReferenceEventV1
    fields: AccountAllocationFieldsV1
    original_book_hash: SHA256Hash
    m0_run_id: UUID7
    m0_audit_event_id: UUID7
    m0_status: Literal["completed", "failed"]
    result_association: ReferenceEventV1 | None
    decisions: tuple[ReferenceDecisionV1, ...]

    @model_validator(mode="after")
    def require_original_result_shape(self) -> Self:
        if (self.m0_status == "completed") != (self.result_association is not None):
            raise ValueError("REFERENCE_RESULT_STATUS_MISMATCH")
        indices = tuple(d.session_index for d in self.decisions)
        if indices != tuple(sorted(set(indices))):
            raise ValueError("REFERENCE_DECISION_ORDER")
        if any(
            d.eligible and d.session_index + 1 < REQUIRED_HISTORY[self.family]
            for d in self.decisions
        ):
            raise ValueError("REFERENCE_ELIGIBILITY_BEFORE_WARMUP")
        return self


class ReferenceAccountsReceiptV1(FrozenModel):
    """Retained original locators, separate from the candidate-facing view."""

    configuration_hash: SHA256Hash
    originals: tuple[ReferenceEventV1, ...]

    @model_validator(mode="after")
    def require_three_originals(self) -> Self:
        if len(self.originals) != 3 or len({r.event_id for r in self.originals}) != 3:
            raise ValueError("REFERENCE_REQUIRES_THREE_ORIGINAL_RECEIPTS")
        return self


class ReferenceMarkV1(FrozenModel):
    session_index: int = Field(ge=0, strict=True)
    session_key: SessionKeyV1
    completed_at: UTCDateTime
    net_asset_value: Decimal
    mark_hash: SHA256Hash


class ReferenceIntervalV1(FrozenModel):
    start_session_index: int = Field(ge=0, strict=True)
    end_session_index: int = Field(gt=0, strict=True)
    completed_at: UTCDateTime
    net_return: Decimal
    transaction_costs: Decimal
    gross_traded_notional: Decimal


class ReferenceFamilyViewV1(FrozenModel):
    family: Family
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: NonBlankStr | None
    required_indicator_sessions: int
    first_eligible_decision_index: int | None
    completed_interval_count: int = Field(ge=0, le=126, strict=True)
    marks: tuple[ReferenceMarkV1, ...]
    intervals: tuple[ReferenceIntervalV1, ...]
    eligible_trace_prefix_hash: SHA256Hash


class CommonReferenceViewV1(FrozenModel):
    """The same detached causal value is eligible for either selector."""

    profile: Literal["drift-stage1-original-reference-accounts/1"] = PROFILE
    decision_cutoff: UTCDateTime
    required_intervals: Literal[126] = 126
    families: tuple[ReferenceFamilyViewV1, ...]

    @model_validator(mode="after")
    def require_common_order_and_cutoff(self) -> Self:
        if tuple(f.family for f in self.families) != FAMILIES:
            raise ValueError("REFERENCE_CONTEXT_FAMILY_ORDER")
        for family in self.families:
            if any(mark.completed_at > self.decision_cutoff for mark in family.marks):
                raise ValueError("REFERENCE_FUTURE_MARK")
            if any(i.completed_at > self.decision_cutoff for i in family.intervals):
                raise ValueError("REFERENCE_FUTURE_INTERVAL")
            if family.completed_interval_count != len(family.intervals):
                raise ValueError("REFERENCE_INTERVAL_COUNT")
            if family.status == "AVAILABLE" and (
                len(family.marks) != 127
                or len(family.intervals) != 126
                or family.reason is not None
            ):
                raise ValueError("REFERENCE_COMPLETE_HISTORY_REQUIRES_127_MARKS")
        return self


def _environment(engines: Sequence[SessionEvaluatorEngine]) -> ReferenceEnvironmentV1:
    if len(engines) != 3 or len({id(e) for e in engines}) != 3:
        raise ValueError("REFERENCE_REQUIRES_THREE_FRESH_ENGINES")
    if any(type(e) is not SessionEvaluatorEngine for e in engines):
        raise ValueError("REFERENCE_REQUIRES_INSTALLED_ENGINE")
    engine = engines[0]
    environment = ReferenceEnvironmentV1(
        input_bundle_hash=engine.bundle.bundle_hash,
        admission_hash=engine.admission.admission_hash,
        cost_model_hash=engine.cost_model.cost_model_hash,
        evaluator_evidence_hash=engine.evaluator_evidence_hash,
        source_inventory_hash=drift_source_inventory_hash(),
        protocol=engine.protocol,
        sessions=engine.bundle.session_clock.sessions,
        securities=tuple(
            sorted(
                (s.security_id for s in engine.bundle.security_identities),
                key=lambda s: s.bytes,
            )
        ),
    )
    for other in engines[1:]:
        if (
            other.bundle.bundle_hash != environment.input_bundle_hash
            or other.admission.admission_hash != environment.admission_hash
            or other.cost_model.cost_model_hash != environment.cost_model_hash
            or other.evaluator_evidence_hash != environment.evaluator_evidence_hash
            or other.protocol != environment.protocol
        ):
            raise ValueError("REFERENCE_ENVIRONMENTS_MUST_MATCH")
    return _copy(ReferenceEnvironmentV1, environment)


def build_reference_configuration(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    run_id: str,
    reference_campaign_id: str,
    bound_at: datetime,
    engines: Sequence[SessionEvaluatorEngine],
) -> ReferenceCampaignConfigurationV1:
    """Build a separate explicit E1 manifest without changing active B/R books.

    The existing E1 synthetic profile requires declared ARM-B/ARM-R anchors.
    They remain unexecuted declarations here. Only the three explicitly named
    FROZEN_BASELINE controls receive original allocations or run results.
    """
    verify_stage1_synthetic_br_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    if reference_campaign_id == campaign.campaign_id:
        raise ValueError("REFERENCE_REQUIRES_SEPARATE_CAMPAIGN_ID")
    rebuilt_arms = []
    for source in arms:
        if source.arm_id not in ("ARM-B", "ARM-R"):
            continue
        kwargs = {
            f.name: getattr(source, f.name)
            for f in fields(source)
            if f.name not in ("schema_version", "arm_spec_fingerprint")
        }
        kwargs["campaign_id"] = reference_campaign_id
        rebuilt_arms.append(build_arm_spec(**kwargs))
    reference_arms = tuple(
        ReferenceArmV1(family=f, arm_id=f"REFERENCE-{f}") for f in FAMILIES
    )
    for reference in reference_arms:
        rebuilt_arms.append(
            build_arm_spec(
                arm_id=reference.arm_id,
                campaign_id=reference_campaign_id,
                selector_type="FROZEN_BASELINE",
                eligible_strategy_references=(reference.family,),
                initial_strategy_reference=reference.family,
                initial_capital="10000",
                currency="USD",
                arm_account_role="COUNTERFACTUAL_REFERENCE",
                mandate_reference=campaign.portfolio_mandate_reference,
                execution_policy_reference=campaign.execution_policy_reference,
                research_budget_reference="NONE",
                information_visibility_policy="COMPLETED_REFERENCE_ONLY",
                feedback_policy_reference="NONE",
                model_configuration_reference="NONE",
                deterministic_seed_reference="DETERMINISTIC_INSTALLED_BASELINE",
                frozen_configuration_reference=content_hash(
                    {
                        "profile": PROFILE,
                        "family": reference.family,
                        "source_campaign": campaign.campaign_spec_fingerprint,
                    }
                ),
            )
        )
    campaign_args = {
        f.name: getattr(campaign, f.name)
        for f in fields(campaign)
        if f.name not in ("schema_version", "campaign_spec_fingerprint")
    }
    campaign_args.update(
        campaign_id=reference_campaign_id,
        created_at=datetime.fromisoformat(campaign.created_at),
        frozen_at=datetime.fromisoformat(campaign.frozen_at),
        accepted_contract_revisions=dict(campaign.accepted_contract_revisions),
        arm_spec_references=tuple(a.arm_spec_fingerprint for a in rebuilt_arms),
        control_arm_references=tuple(a.arm_id for a in reference_arms),
        authorization_evidence={
            "purpose": "ORIGINAL_COUNTERFACTUAL_REFERENCE",
            "source_campaign_fingerprint": campaign.campaign_spec_fingerprint,
            "scientifically_qualified": False,
        },
    )
    reference_campaign = build_campaign_spec(**campaign_args)
    reference_bindings = tuple(
        build_run_account_binding(
            campaign_id=reference_campaign_id,
            run_id=run,
            arm_id=arm.arm_id,
            portfolio_account_id=f"{reference_campaign_id}.{run}.{arm.arm_id}.account",
            initial_cash_allocated="10000",
            bound_at=bound_at,
        )
        for run in expected_run_ids
        for arm in rebuilt_arms
    )
    return _copy(
        ReferenceCampaignConfigurationV1,
        ReferenceCampaignConfigurationV1(
            campaign=reference_campaign,
            arms=tuple(rebuilt_arms),
            bindings=reference_bindings,
            expected_run_ids=tuple(expected_run_ids),
            run_id=run_id,
            reference_arms=reference_arms,
            environment=_environment(engines),
        ),
    )


class _FixedReferenceStrategy:
    def __init__(self, family: Family, environment: ReferenceEnvironmentV1) -> None:
        self.family = family
        self.environment = environment
        self.decisions: list[ReferenceDecisionV1] = []
        sessions = environment.sessions
        # Calendar boundaries come only from the admitted original clock.
        monthly_dates = tuple(
            left.session_key.local_date
            for left, right in pairwise(sessions)
            if left.session_key.local_date.month != right.session_key.local_date.month
        )
        self.installed = (
            B3MonthlyEqualWeightRebalanceStrategy(rebalance_dates=monthly_dates)
            if family == "B3"
            else B4MomentumStrategy()
            if family == "B4"
            else B5LowVolatilityStrategy()
        )

    @property
    def strategy_parameters(self) -> ImmutableJSONValue:
        return {
            "profile": PROFILE,
            "family": self.family,
            "required_indicator_sessions": REQUIRED_HISTORY[self.family],
            "unavailable_action": "hold_original_quantities",
            "installed_parameters": self.installed.strategy_parameters,
        }

    @property
    def strategy_reference(self) -> StrategyReference:
        return make_baseline_reference(
            name=f"stage1_fixed_reference_{self.family.lower()}",
            custom_hash=content_hash(
                {
                    "profile": PROFILE,
                    "installed_strategy": self.installed.strategy_reference,
                    "parameters": self.strategy_parameters,
                }
            ),
        )

    def _decide(self, context: DecisionContext) -> StrategyDecisionIntentV1:
        keys = tuple(s.session_key for s in self.environment.sessions)
        index = keys.index(context.session_key)
        needed = REQUIRED_HISTORY[self.family]
        securities = get_admitted_securities(context)
        reason = None
        if index + 1 < needed:
            reason = "INDICATOR_WARMUP_INCOMPLETE"
        elif tuple(securities) != self.environment.securities:
            reason = "COMMON_REFERENCE_UNIVERSE_UNAVAILABLE"
        elif self.family in ("B4", "B5") and len(securities) < 2:
            reason = "REFERENCE_FAMILY_NEEDS_TWO_SECURITIES"
        else:
            expected = keys[index + 1 - needed : index + 1]
            for security in securities:
                history = extract_security_history(context, security)
                tail = history[-needed:]
                if tuple(s.session_key for s in tail) != expected or any(
                    not s.close_price.is_finite() or s.close_price <= 0 for s in tail
                ):
                    reason = "CONTIGUOUS_REFERENCE_HISTORY_UNAVAILABLE"
                    break
        if reason is None:
            with decimal_context():
                intent = (
                    self.installed.decide(context)
                    if isinstance(context, StrategyDecisionContextV1)
                    else self.installed.decide_exploratory(context)
                )
            if not any(t.target_quantity > 0 for t in intent.targets):
                reason = "REFERENCE_FAMILY_TARGET_UNAVAILABLE"
        if reason is not None:
            intent = build_decision_intent(
                context,
                tuple(
                    SecurityTargetPositionV1(
                        security_id=h.security_id, target_quantity=h.quantity
                    )
                    for h in context.current_holdings
                ),
            )
        intent = _copy(StrategyDecisionIntentV1, intent)
        self.decisions.append(
            ReferenceDecisionV1(
                session_index=index,
                context_hash=content_hash(context),
                intent_hash=content_hash(intent),
                eligible=reason is None,
                reason=reason,
            )
        )
        return _copy(StrategyDecisionIntentV1, intent)

    def decide(self, context: StrategyDecisionContextV1) -> StrategyDecisionIntentV1:
        return self._decide(context)

    def decide_exploratory(
        self,
        context: ExploratoryStrategyDecisionContextV1,
    ) -> StrategyDecisionIntentV1:
        return self._decide(context)


def _provenance(
    configuration: ReferenceCampaignConfigurationV1, arm_id: str
) -> Stage1TrialProvenanceSnapshotV1:
    return build_stage1_trial_provenance_snapshot(
        campaign=configuration.campaign,
        arms=configuration.arms,
        bindings=configuration.bindings,
        expected_run_ids=configuration.expected_run_ids,
        run_id=configuration.run_id,
        arm_id=arm_id,
        checkpoint_id=configuration.checkpoint_id,
        events=(),
    )


@_with_reconstruction_validation_reuse
def execute_reference_accounts(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    configuration: ReferenceCampaignConfigurationV1,
    engines: Sequence[SessionEvaluatorEngine],
    clock: Callable[[], datetime],
) -> ReferenceAccountsReceiptV1:
    """Allocate and consume three original fixed-family accounts exactly once."""
    configuration = _copy(ReferenceCampaignConfigurationV1, configuration)
    if _environment(engines) != configuration.environment:
        raise ValueError("REFERENCE_ENGINE_NOT_CONFIGURED_ORIGINAL")
    configuration_hash = content_hash(configuration)
    originals = []
    for reference, engine in zip(configuration.reference_arms, engines, strict=True):
        provenance = _provenance(configuration, reference.arm_id)
        account = Stage1SyntheticAccountLifecycleV1(
            campaign=configuration.campaign,
            arms=configuration.arms,
            bindings=configuration.bindings,
            expected_run_ids=configuration.expected_run_ids,
            provenance=provenance,
            store=LocalSyntheticAccountReceiptStoreV1(origin=origin, clock=clock),
        )
        engine.prepare_opening_book(lifecycle=account)
        original = account.verified_original()
        observer = Stage1OriginalResultAssociationV1(
            origin=origin,
            account=account,
            provenance=provenance,
            campaign=configuration.campaign,
            arms=configuration.arms,
            bindings=configuration.bindings,
            expected_run_ids=configuration.expected_run_ids,
            clock=clock,
        )
        strategy = _FixedReferenceStrategy(reference.family, configuration.environment)
        identity = build_canonical_run_identity(
            strategy_hash=strategy.strategy_reference.code_hash,
            strategy_parameters_hash=strategy_parameters_hash(
                strategy.strategy_parameters
            ),
            protocol_hash=engine.protocol.protocol_hash,
            cost_model_hash=engine.cost_model.cost_model_hash,
            admission=engine.admission,
            bundle=engine.bundle,
            evaluator_evidence_hash=engine.evaluator_evidence_hash,
            code_version_hash=configuration.environment.source_inventory_hash,
        )
        specification = build_canonical_specification(
            strategy=strategy,
            bundle=engine.bundle,
            dataset_reference=make_bundle_dataset_reference(
                engine.bundle,
                source="Original installed-family counterfactual reference account",
            ),
        )
        run_id, audit_id, started_at = uuid7(), uuid7(), _now(clock)
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
                completion_clock=clock,
            ),
        )
        result = observer.readback() if run.status.value == "completed" else None
        receipt = ReferenceAccountReceiptV1(
            family=reference.family,
            allocation_id=original.allocation_id,
            allocation=ReferenceEventV1(
                event_id=original.allocation_ref.event_id,
                event_hash=original.allocation_ref.event_hash,
            ),
            witness=ReferenceEventV1(
                event_id=original.witness_ref.event_id,
                event_hash=original.witness_ref.event_hash,
            ),
            fields=original.fields,
            original_book_hash=content_hash(original.opening_book),
            m0_run_id=run_id,
            m0_audit_event_id=audit_id,
            m0_status=cast(Literal["completed", "failed"], run.status.value),
            result_association=(
                ReferenceEventV1(
                    event_id=result.association_ref.event_id,
                    event_hash=result.association_ref.event_hash,
                )
                if result is not None
                else None
            ),
            decisions=tuple(strategy.decisions),
        )
        event = SQLiteLedger(origin.ledger_path).append(
            AuditEventDraft(
                event_id=uuid7(),
                event_type=EVENT,
                timestamp=_now(clock),
                entity_type=ENTITY,
                entity_id=original.allocation_id,
                schema_version="1",
                deduplication_key=f"{PROFILE}:{original.fields.allocation_key}",
                payload={
                    "profile": PROFILE,
                    "issuer_instance_id": str(origin.issuer_instance_id),
                    "configuration_hash": configuration_hash,
                    "receipt": receipt.model_dump(mode="json"),
                },
            )
        )
        originals.append(
            ReferenceEventV1(event_id=event.event_id, event_hash=event.event_hash)
        )
    return ReferenceAccountsReceiptV1(
        configuration_hash=configuration_hash, originals=tuple(originals)
    )


def _family_view(
    *,
    family: Family,
    environment: ReferenceEnvironmentV1,
    receipt: ReferenceAccountReceiptV1,
    artifacts: EvaluationRunArtifactsV2 | None,
    decision_cutoff: datetime,
) -> ReferenceFamilyViewV1:
    sessions = environment.sessions
    eligible_indices = tuple(
        i for i, s in enumerate(sessions) if s.closed_at <= decision_cutoff
    )
    cutoff_index = eligible_indices[-1] if eligible_indices else -1
    # Filter the original trace before deriving any candidate-facing field.
    prefix = (
        tuple(e for e in artifacts.trace.events if e.session_index <= cutoff_index)
        if artifacts is not None
        else ()
    )
    trace_decisions = {
        e.session_index: e
        for e in prefix
        if e.kind in ("strategy_decision", "exploratory_strategy_decision")
    }
    decisions = (
        tuple(d for d in receipt.decisions if d.session_index <= cutoff_index)
        if artifacts is not None
        else ()
    )
    if len({d.session_index for d in decisions}) != len(decisions):
        raise ValueError("REFERENCE_DUPLICATE_DECISION")
    for decision in decisions:
        event = trace_decisions.get(decision.session_index)
        if event is None or (event.context_hash, event.intent_hash) != (
            decision.context_hash,
            decision.intent_hash,
        ):
            raise ValueError("REFERENCE_DECISION_NOT_ORIGINAL_TRACE")
    if set(trace_decisions) != {d.session_index for d in decisions}:
        raise ValueError("REFERENCE_ORIGINAL_DECISION_OMITTED")
    first = next((d.session_index for d in decisions if d.eligible), None)
    marks_by_index = {e.session_index: e for e in prefix if e.kind == "session_mark"}
    if len(marks_by_index) != sum(e.kind == "session_mark" for e in prefix):
        raise ValueError("REFERENCE_DUPLICATE_MARK")
    reason = None
    if artifacts is None:
        reason = "ORIGINAL_RESULT_UNAVAILABLE"
    elif first is None:
        reason = "INDICATOR_HISTORY_UNAVAILABLE"
    elif cutoff_index not in marks_by_index:
        reason = "COMPLETED_CUTOFF_MARK_UNAVAILABLE"
    else:
        latest_start = max(first, cutoff_index - OBSERVATION_INTERVALS)
        if any(i not in marks_by_index for i in range(latest_start, cutoff_index + 1)):
            reason = "CONTIGUOUS_COMPLETED_MARKS_UNAVAILABLE"
        elif any(not d.eligible for d in decisions if d.session_index >= latest_start):
            reason = "CONTIGUOUS_ELIGIBLE_REFERENCE_HISTORY_UNAVAILABLE"
        elif cutoff_index - latest_start < OBSERVATION_INTERVALS:
            reason = "COMPLETED_126_INTERVALS_UNAVAILABLE"
    marks: tuple[ReferenceMarkV1, ...] = ()
    intervals: tuple[ReferenceIntervalV1, ...] = ()
    if first is not None and cutoff_index in marks_by_index:
        start = max(first, cutoff_index - OBSERVATION_INTERVALS)
        if all(i in marks_by_index for i in range(start, cutoff_index + 1)):
            marks = tuple(
                ReferenceMarkV1(
                    session_index=i,
                    session_key=sessions[i].session_key,
                    completed_at=sessions[i].closed_at,
                    net_asset_value=marks_by_index[i].net_asset_value,
                    mark_hash=marks_by_index[i].mark_hash,
                )
                for i in range(start, cutoff_index + 1)
            )
            if any(mark.net_asset_value <= 0 for mark in marks):
                reason = "POSITIVE_REFERENCE_NAV_UNAVAILABLE"
                marks = ()
            else:
                with decimal_context():
                    intervals = tuple(
                        ReferenceIntervalV1(
                            start_session_index=left.session_index,
                            end_session_index=right.session_index,
                            completed_at=right.completed_at,
                            net_return=right.net_asset_value / left.net_asset_value - 1,
                            transaction_costs=sum(
                                (
                                    e.fill.transaction_costs
                                    for e in prefix
                                    if e.kind == "fill"
                                    and e.session_index == right.session_index
                                ),
                                Decimal("0"),
                            ),
                            gross_traded_notional=sum(
                                (
                                    e.fill.gross_notional
                                    for e in prefix
                                    if e.kind == "fill"
                                    and e.session_index == right.session_index
                                ),
                                Decimal("0"),
                            ),
                        )
                        for left, right in pairwise(marks)
                    )
    return ReferenceFamilyViewV1(
        family=family,
        status="AVAILABLE" if reason is None else "UNAVAILABLE",
        reason=reason,
        required_indicator_sessions=REQUIRED_HISTORY[family],
        first_eligible_decision_index=first,
        completed_interval_count=len(intervals),
        marks=marks,
        intervals=intervals,
        eligible_trace_prefix_hash=content_hash(prefix),
    )


def read_reference_accounts(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    configuration: ReferenceCampaignConfigurationV1,
    receipt: ReferenceAccountsReceiptV1,
    decision_cutoff: datetime,
    clock: Callable[[], datetime],
) -> CommonReferenceViewV1:
    """Reopen actual account/M0/RESULT chains, then expose only causal prefixes.

    Receipt fields select originals in the separately supplied trusted origin.
    They never select their own issuer, path, strategy implementation or source.
    A later indeterminate halt cannot alter an earlier completed prefix.
    """
    # Import at the call boundary so controlled contracts can embed the public
    # reference models without creating a module initialization cycle. Reuse
    # the existing exact-host immutable original snapshot, not a receipt-named
    # origin or a caller-supplied "already verified" capability.
    from drift.loop.stage1_controlled_journal import _CapturedOrigin

    configuration = _copy(ReferenceCampaignConfigurationV1, configuration)
    receipt = _copy(ReferenceAccountsReceiptV1, receipt)
    if receipt.configuration_hash != content_hash(configuration):
        raise ValueError("REFERENCE_CONFIGURATION_MISMATCH")
    if configuration.environment.source_inventory_hash != drift_source_inventory_hash():
        raise ValueError("REFERENCE_INSTALLED_SOURCE_CHANGED")
    if type(decision_cutoff) is not datetime or decision_cutoff.tzinfo is None:
        raise ValueError("REFERENCE_CUTOFF_REQUIRES_AWARE_INSTANT")
    decision_cutoff = decision_cutoff.astimezone(UTC)
    observed_at = _now(clock)
    if type(origin) is not _CapturedOrigin:
        origin = _CapturedOrigin(origin, None)
    events = origin.verified_events()
    rows = {event.event_id: event for event in events}
    positions = {event.event_id: index for index, event in enumerate(events)}
    views = []
    allocation_ids: set[UUID] = set()
    account_ids: set[str] = set()
    for declared, locator in zip(
        configuration.reference_arms, receipt.originals, strict=True
    ):
        event = rows.get(locator.event_id)
        if event is None or not isinstance(event.payload, Mapping):
            raise ValueError("REFERENCE_ORIGINAL_NOT_FOUND")
        payload = event.payload
        if (
            event.event_hash != locator.event_hash
            or event.event_type != EVENT
            or event.entity_type != ENTITY
            or event.schema_version != "1"
            or event.timestamp > observed_at
            or payload.get("profile") != PROFILE
            or payload.get("issuer_instance_id") != str(origin.issuer_instance_id)
            or payload.get("configuration_hash") != receipt.configuration_hash
        ):
            raise ValueError("REFERENCE_ORIGINAL_SCOPE_MISMATCH")
        account_receipt = ReferenceAccountReceiptV1.model_validate_json(
            canonical_json(payload.get("receipt"))
        )
        if (
            event.deduplication_key
            != f"{PROFILE}:{account_receipt.fields.allocation_key}"
            or sum(
                row.event_type == EVENT
                and row.entity_id == account_receipt.allocation_id
                for row in events
            )
            != 1
        ):
            raise ValueError("REFERENCE_ORIGINAL_RECEIPT_NOT_UNIQUE")
        if (
            account_receipt.family != declared.family
            or account_receipt.fields.arm_id != declared.arm_id
            or event.entity_id != account_receipt.allocation_id
            or account_receipt.allocation_id in allocation_ids
            or account_receipt.fields.portfolio_account_id in account_ids
        ):
            raise ValueError("REFERENCE_ORIGINAL_ACCOUNTS_NOT_DISTINCT")
        allocation_ids.add(account_receipt.allocation_id)
        account_ids.add(account_receipt.fields.portfolio_account_id)
        provenance = _provenance(configuration, declared.arm_id)
        binding = provenance.scope.run_account_binding
        m0_event = rows.get(account_receipt.m0_audit_event_id)
        if (
            account_receipt.fields.campaign_id != configuration.campaign.campaign_id
            or account_receipt.fields.run_id != configuration.run_id
            or account_receipt.fields.portfolio_account_id
            != binding.portfolio_account_id
            or account_receipt.fields.binding_hash != content_hash(asdict(binding))
            or account_receipt.fields.complete_manifest_fingerprint
            != provenance.scope.complete_manifest_fingerprint
            or m0_event is None
            or m0_event.event_type != "m2.evaluation.run.recorded"
            or m0_event.entity_id != account_receipt.m0_run_id
            or positions[m0_event.event_id] >= positions[event.event_id]
            or m0_event.timestamp > event.timestamp
            or not isinstance(m0_event.payload, Mapping)
            or m0_event.payload.get("status") != account_receipt.m0_status
        ):
            raise ValueError("REFERENCE_ORIGINAL_M0_OR_MANIFEST_MISMATCH")
        original = LocalSyntheticAccountReceiptStoreV1.open_existing(
            origin=origin, clock=lambda: observed_at
        ).readback_allocation(
            allocation_id=account_receipt.allocation_id,
            allocation_ref=account_receipt.allocation.local(),
            witness_ref=account_receipt.witness.local(),
            expected_fields=account_receipt.fields,
        )
        if content_hash(original.opening_book) != account_receipt.original_book_hash:
            raise ValueError("REFERENCE_ORIGINAL_BOOK_MISMATCH")
        artifacts = None
        if account_receipt.result_association is not None:
            result_position = positions.get(account_receipt.result_association.event_id)
            if result_position is None or not (
                positions[m0_event.event_id]
                < result_position
                < positions[event.event_id]
            ):
                raise ValueError("REFERENCE_ORIGINAL_RESULT_CHRONOLOGY")
            result = read_original_result(
                origin=origin,
                original_account=original,
                association_ref=account_receipt.result_association.local(),
                provenance=provenance,
                campaign=configuration.campaign,
                arms=configuration.arms,
                bindings=configuration.bindings,
                expected_run_ids=configuration.expected_run_ids,
                clock=lambda: observed_at,
            )
            artifacts = result.original_artifacts
            identity = artifacts.result.run_identity
            if not isinstance(identity, EvaluationRunIdentityV2):
                raise ValueError("REFERENCE_REQUIRES_PARAMETER_BOUND_ORIGINAL")
            environment = configuration.environment
            strategy = _FixedReferenceStrategy(declared.family, environment)
            if (
                result.operational_m0_run_id != account_receipt.m0_run_id
                or result.invocation_binding.m0_audit_event_id
                != account_receipt.m0_audit_event_id
                or identity.strategy_hash != strategy.strategy_reference.code_hash
                or identity.strategy_parameters_hash
                != strategy_parameters_hash(strategy.strategy_parameters)
                or identity.bundle_hash != environment.input_bundle_hash
                or identity.protocol_hash != environment.protocol.protocol_hash
                or identity.cost_model_hash != environment.cost_model_hash
                or identity.admission_hash != environment.admission_hash
                or identity.evaluator_evidence_hash
                != environment.evaluator_evidence_hash
                or identity.code_version_hash != environment.source_inventory_hash
            ):
                raise ValueError("REFERENCE_ORIGINAL_INSTALLED_RUN_MISMATCH")
            for trace_event in artifacts.trace.events:
                if (
                    trace_event.session_index >= len(environment.sessions)
                    or trace_event.session_key
                    != environment.sessions[trace_event.session_index].session_key
                ):
                    raise ValueError("REFERENCE_ORIGINAL_CLOCK_MISMATCH")
        views.append(
            _family_view(
                family=declared.family,
                environment=configuration.environment,
                receipt=account_receipt,
                artifacts=artifacts,
                decision_cutoff=decision_cutoff,
            )
        )
    return _copy(
        CommonReferenceViewV1,
        CommonReferenceViewV1(
            decision_cutoff=decision_cutoff,
            families=tuple(views),
        ),
    )
