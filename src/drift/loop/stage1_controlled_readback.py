"""Cold reconstruction of a controlled campaign from one original ledger prefix.

No writer, account capability or dispatch is reconstructed. Every relevant
record is accounted for, including suffixes and incomplete opportunities. The
configured installed host is the declared origin boundary; scientific and
operational permission cannot be manufactured by a successful local read.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, cast
from uuid import UUID

from drift.domain.evaluator_bundles import (
    EvaluationRunIdentityV2,
    strategy_parameters_hash,
)
from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.evaluator_trace import (
    ExecutionAuthorizationTraceEventV1,
    ExploratoryStrategyDecisionTraceEventV1,
    FillTraceEventV1,
    SessionObservationTraceEventV1,
    StrategyDecisionTraceEventV1,
)
from drift.domain.observation_query import drift_source_inventory_hash
from drift.evaluator.opening_book_lifecycle import parse_original_invocation_binding
from drift.evaluator.session_observer import RebalancePreviewV1, SessionObservationV1
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
)
from drift.experiments.stage1_metric_math import (
    MetricArithmeticValue,
    calculate_comparative_economic_advantage,
    calculate_economic_gain,
    calculate_maximum_drawdown,
)
from drift.experiments.stage1_trial_projection import (
    ControlledTrialProjectionV1,
    OperatingCostProjectionV1,
    make_trial_projection,
    project_operating_costs,
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
    TrustedInvocationBinding,
)
from drift.intelligence.conventional_selector import select_conventional_candidate
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
from drift.intelligence.validation import ValidationResult
from drift.ledger.stage1_synthetic_account_receipts import (
    CLAIM,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
)
from drift.loop import stage1_controlled_contracts as C
from drift.loop.stage1_controlled_campaign import (
    DecisionContext,
    ResearchOutput,
    authorize_preview,
    choice_for_family,
    context_kind,
    controlled_strategy_reference,
    current_book_reason,
    decision_mandate_reason,
    financial_parameters,
    hold_intent,
    installed_intent,
    make_research_context,
    parse_context,
    research_dependencies,
)
from drift.loop.stage1_controlled_journal import (
    CapturedControlledJournalV1,
    ControlledRowV1,
    observed_time,
)
from drift.loop.stage1_original_result_association import (
    LocalOriginalResultReadbackV1,
    read_original_result,
)
from drift.serialization.canonical import canonical_json, content_hash


def _local(ref: C.OriginalReferenceV1) -> LocalEventReferenceV1:
    return LocalEventReferenceV1(ref.event_id, ref.event_hash)


@dataclass(frozen=True, slots=True)
class ControlledCampaignEconomicsV1:
    """Whole scoring interval, including initial B3 before the first research call.

    No funds are reset and checkpoint gains are never summed as independent
    account returns. Original posted costs are already reflected in these NAVs.
    Sharpe, significance, superiority and annualization are deliberately absent:
    this synthetic profile supplies neither a risk-free convention nor enough
    independent runs to support those conclusions.
    """

    campaign_id: str
    campaign_fingerprint: str
    full_manifest_fingerprint: str
    run_id: str
    arm_id: str
    account_id: str
    comparability_hash: str
    start_session_index: int
    end_session_index: int
    complete: bool
    initial_net_nav: Decimal | None
    terminal_net_nav: Decimal | None
    trading_costs: Decimal | None
    gross_filled_notional: Decimal | None
    operating_cost: OperatingCostProjectionV1
    economic_gain: MetricArithmeticValue
    maximum_drawdown: MetricArithmeticValue


@dataclass(frozen=True, slots=True)
class ControlledCampaignReadbackV1:
    allocation_id: UUID
    manifest_hash: str
    snapshot_tip: C.OriginalReferenceV1
    status: Literal["VERIFIED_COMPLETE", "VERIFIED_PARTIAL", "UNRESOLVED"]
    reasons: tuple[str, ...]
    declared_opportunities: int
    accounted_event_hashes: tuple[str, ...]
    trials: tuple[ControlledTrialProjectionV1, ...]
    original_result: LocalOriginalResultReadbackV1 | None
    source_coverage: str
    economics: ControlledCampaignEconomicsV1
    independent_account_count: Literal[1] = 1

    @property
    def g2_accepted(self) -> bool:
        # Release acceptance is recorded by independent reviewers, not this API.
        return False

    @property
    def scientifically_qualified(self) -> bool:
        return False

    @property
    def authorizes_trading(self) -> bool:
        return False


class _ReplayStore(ResearchReceiptStore):
    def __init__(self) -> None:
        super().__init__()
        self.observations: list[tuple[str, bytes]] = []

    def record_attempt(self, attempt: AttemptRecord) -> None:
        super().record_attempt(attempt)
        self.observations.append(("attempt", canonical_json(attempt)))

    def record_cost_receipt(self, cost: CostReceipt) -> None:
        super().record_cost_receipt(cost)
        self.observations.append(("cost", canonical_json(cost)))


def _choices(
    plan: C.ControlledCampaignPlanV1,
    checkpoint: C.ControlledCheckpointV1,
    context: DecisionContext,
    incumbent: C.Family,
) -> tuple[RawChoice | None, tuple[RawChoice, ...]]:
    fixture = checkpoint.fixture
    if fixture.mode == "conventional_fixture":
        return None, tuple(
            choice_for_family(f, context, plan.sessions)
            for f in fixture.candidate_families
        )
    if fixture.disposition == "propose":
        assert fixture.selected_family is not None
        return choice_for_family(fixture.selected_family, context, plan.sessions), ()
    return RawChoice(
        disposition=fixture.disposition,
        selection=StrategySelection(family_id=incumbent, strategy_version="1")
        if fixture.disposition == "hold"
        else None,
        targets=(),
        cash_weight=None,
        rationale="Declared bounded synthetic nonproposal.",
    ), ()


def _replay(
    plan: C.ControlledCampaignPlanV1,
    checkpoint: C.ControlledCheckpointV1,
    context: DecisionContext,
    research: ResearchContext,
    incumbent: C.Family,
    grant: C.GrantRecordV1,
    at: datetime,
) -> tuple[ResearchOutput, _ReplayStore]:
    scripted, pool = _choices(plan, checkpoint, context, incumbent)
    recorder = _ReplayStore()
    resolved = research_dependencies(research, incumbent, plan.securities)
    policy = ArtifactReference(
        id="synthetic:controlled-original-validation",
        version=C.PROFILE,
        sha256=content_hash(C.PROFILE),
    )

    def observe(
        raw: str, binding: TrustedInvocationBinding, result: ValidationResult
    ) -> None:
        recorder.observations.append(
            (
                "validation",
                canonical_json({"raw": raw, "binding": binding, "result": result}),
            )
        )

    output: ResearchOutput
    with decimal_context():
        if checkpoint.fixture.mode == "scripted_fixture":
            output = produce_proposal(
                context=research,
                resolved_inputs=resolved,
                frozen_method=research.method_ref,
                validation_policy=policy,
                recorder=recorder,
                attempt_id=grant.attempt_id,
                logical_request_id=grant.logical_request_id,
                checked_at=at,
                valid_until=grant.expires_at,
                validation_observer=observe,
                transport=FakeTransport(
                    raw_choice=scripted,
                    should_timeout=checkpoint.fixture.should_timeout,
                    malformed_json=checkpoint.fixture.malformed_output,
                    cost_amount=format(checkpoint.fixture.cost_amount, "f"),
                ),
            )
        else:

            def score(candidate: ResearchCandidate) -> Decimal:
                if candidate.strategy is None:
                    raise ValueError("CONTROLLED_REPLAY_MISSING_FAMILY")
                return checkpoint.fixture.scores[candidate.strategy.family_id]

            output = select_conventional_candidate(
                context=research,
                resolved_inputs=resolved,
                method_ref=research.method_ref,
                validation_policy=policy,
                recorder=recorder,
                attempt_id=grant.attempt_id,
                logical_request_id=grant.logical_request_id,
                checked_at=at,
                valid_until=grant.expires_at,
                validation_observer=observe,
                candidate_pool=pool,
                objective_fn=score,
            )
    recorder.observations.append(("research_output", canonical_json(output)))
    return output, recorder


@dataclass(frozen=True, slots=True)
class _Opportunity:
    family: C.Family | None
    candidate: ResearchCandidate | None
    reason: str
    complete: bool
    no_attempt: bool
    failed_research: bool
    costs: tuple[CostReceipt, ...]
    rows: tuple[ControlledRowV1, ...]


class _Verifier:
    def __init__(self, captured: CapturedControlledJournalV1) -> None:
        self.journal = captured
        self.plan = captured.plan
        self.accounted: set[UUID] = set()
        self.reasons: set[str] = set()
        self.observations: dict[int, ControlledRowV1] = {}
        self.decisions: dict[int, ControlledRowV1] = {}
        self.executions: dict[int, ControlledRowV1] = {}
        self.missing_executions: set[int] = set()
        self.containments: dict[int, ControlledRowV1] = {}
        self.opportunity_rows: dict[str, list[ControlledRowV1]] = {
            c.checkpoint_id: [] for c in self.plan.checkpoints
        }
        self.terminal: ControlledRowV1 | None = None
        for row in captured.rows:
            record = row.record
            if isinstance(record, C.ManifestRecordV1):
                if row != captured.manifest:
                    raise ValueError("CONTROLLED_EXTRA_MANIFEST")
            elif isinstance(record, C.ObservationRecordV1):
                self._index(self.observations, record.observation.session_index, row)
            elif isinstance(record, C.DecisionRecordV1):
                self._index(self.decisions, record.session_index, row)
            elif isinstance(record, C.ExecutionRecordV1):
                preview = record.preview.parse(RebalancePreviewV1)
                self._index(self.executions, preview.session_index, row)
            elif isinstance(record, C.ContainmentRecordV1):
                source = captured.resolve(record.observation, before=row)
                if not isinstance(source.record, C.ObservationRecordV1):
                    raise ValueError("CONTROLLED_CONTAINMENT_WRONG_OBSERVATION")
                self._index(
                    self.containments, source.record.observation.session_index, row
                )
            elif isinstance(record, C.TerminalRecordV1):
                if self.terminal is not None:
                    raise ValueError("CONTROLLED_DUPLICATE_TERMINAL")
                self.terminal = row
            else:
                checkpoint_id = record.checkpoint_id
                if checkpoint_id not in self.opportunity_rows:
                    raise ValueError("CONTROLLED_UNDECLARED_OPPORTUNITY")
                self.opportunity_rows[checkpoint_id].append(row)
        if self.terminal is not None:
            for row in captured.rows:
                if row.sequence > self.terminal.sequence and not (
                    isinstance(row.record, C.CostRecordV1)
                    and row.record.original.supersedes_receipt_id is not None
                ):
                    raise ValueError("CONTROLLED_UNDECLARED_POST_TERMINAL_PHASE")
        self.take(captured.manifest)

    def _index(
        self, collection: dict[int, ControlledRowV1], index: int, row: ControlledRowV1
    ) -> None:
        if index < 0 or index >= len(self.plan.sessions) or index in collection:
            raise ValueError("CONTROLLED_DUPLICATE_OR_UNDECLARED_SESSION_PHASE")
        collection[index] = row

    def take(self, row: ControlledRowV1) -> None:
        if row.event.event_id in self.accounted:
            raise ValueError("CONTROLLED_DUPLICATE_EVENT_ACCOUNTING")
        self.accounted.add(row.event.event_id)

    def _one(
        self, rows: Sequence[ControlledRowV1], kind: str
    ) -> ControlledRowV1 | None:
        matches = [r for r in rows if r.record.kind == kind]
        if len(matches) > 1:
            raise ValueError("CONTROLLED_DUPLICATE_PHASE:" + kind)
        return matches[0] if matches else None

    def verify_observations(
        self, result: LocalOriginalResultReadbackV1 | None, binding: object
    ) -> None:
        for index, row in self.observations.items():
            record = row.record
            assert isinstance(record, C.ObservationRecordV1)
            observation = record.observation
            if (
                observation.session != self.plan.sessions[index]
                or observation.invocation_binding != binding
            ):
                raise ValueError("CONTROLLED_OBSERVATION_SESSION_OR_INVOCATION")
            if (
                observation.state.admission_hash
                != self.plan.original_account.fields.admission_hash
            ):
                raise ValueError("CONTROLLED_OBSERVATION_FOREIGN_ADMISSION")
            prefix = observation.trace_prefix
            if (
                not prefix
                or not isinstance(prefix[-1], SessionObservationTraceEventV1)
                or prefix[-1].book_hash != content_hash(observation.state)
            ):
                raise ValueError("CONTROLLED_OBSERVATION_NOT_ORIGINAL_MARKED_BOOK")
            if result is not None:
                actual = tuple(
                    e
                    for e in result.original_artifacts.trace.events
                    if e.session_index == index and e.sequence <= prefix[-1].sequence
                )
                if prefix != actual:
                    raise ValueError("CONTROLLED_OBSERVATION_NOT_ORIGINAL_TRACE_PREFIX")
            if index <= self.plan.initial_decision_index and (
                observation.state.holdings
                or observation.state.cash_balance != Decimal("10000")
                or observation.state.pending_cash_claims
                or observation.state.cumulative_transaction_costs != 0
            ):
                raise ValueError("CONTROLLED_PREPARATION_NOT_FRESH_UNTRADED_BOOK")
            reason = current_book_reason(self.plan.mandate, observation.state)
            containment = self.containments.get(index)
            if reason is None:
                if containment is not None:
                    raise ValueError("CONTROLLED_FALSE_CURRENT_BOOK_CONTAINMENT")
            elif containment is None:
                self.reasons.add("MISSING_CURRENT_BOOK_CONTAINMENT")
            else:
                assert isinstance(containment.record, C.ContainmentRecordV1)
                if containment.record.reason != reason or index in self.decisions:
                    raise ValueError("CONTROLLED_UNSAFE_BOOK_REACHED_DECISION")
                self.take(containment)
            self.take(row)
        indices = sorted(self.observations)
        if indices and indices != list(range(indices[-1] + 1)):
            self.reasons.add("MISSING_ORIGINAL_OBSERVATIONS")
        if result is not None:
            required = {
                e.session_index
                for e in result.original_artifacts.trace.events
                if isinstance(e, SessionObservationTraceEventV1)
            }
            if required != set(self.observations):
                self.reasons.add("MISSING_ORIGINAL_OBSERVATIONS")

    def verify_execution_inventory(
        self, result: LocalOriginalResultReadbackV1 | None
    ) -> None:
        if result is None:
            return
        originals = [
            e.session_index
            for e in result.original_artifacts.trace.events
            if isinstance(e, ExecutionAuthorizationTraceEventV1)
        ]
        if len(originals) != len(set(originals)):
            raise ValueError("CONTROLLED_DUPLICATE_ORIGINAL_EXECUTION_AUTHORIZATION")
        if set(self.executions) - set(originals):
            raise ValueError("CONTROLLED_EXECUTION_AUTHORIZATION_NOT_ORIGINAL")
        self.missing_executions = set(originals) - set(self.executions)
        if self.missing_executions:
            self.reasons.add("MISSING_ORIGINAL_EXECUTION_RECORD")

    def verify_execution(
        self,
        row: ControlledRowV1,
        result: LocalOriginalResultReadbackV1 | None,
        binding: object,
    ) -> None:
        record = row.record
        assert isinstance(record, C.ExecutionRecordV1)
        decision_row = self.journal.resolve(record.decision, before=row)
        if not isinstance(decision_row.record, C.DecisionRecordV1):
            raise ValueError("CONTROLLED_EXECUTION_WRONG_ORIGINAL_DECISION")
        decision = decision_row.record
        preview = record.preview.parse(RebalancePreviewV1)
        if (
            preview.invocation_binding != binding
            or preview.session != self.plan.sessions[preview.session_index]
            or preview.session_index != decision.session_index + 1
            or preview.decision_session != self.plan.sessions[decision.session_index]
        ):
            raise ValueError("CONTROLLED_EXECUTION_SCOPE_OR_CHRONOLOGY")
        checkpoint = next(
            (
                c
                for c in self.plan.checkpoints
                if c.session_index == decision.session_index
            ),
            None,
        )
        selected = checkpoint is not None and decision.disposition == "SELECTED"
        expected = authorize_preview(
            self.plan.mandate,
            preview,
            execution_at=row.event.timestamp,
            proposal_deadline=checkpoint.expires_at
            if checkpoint and selected
            else None,
            revoked_at=checkpoint.revoked_at if checkpoint and selected else None,
        )
        if expected != record.authorization:
            raise ValueError("CONTROLLED_FALSE_EXECUTION_AUTHORIZATION")
        # An authorization journal row cannot be recorded after the marked
        # book that already includes the outcome of that authorization. UTC
        # timestamps can legitimately be equal, so enforce original append
        # order rather than comparing the clock values alone.
        observed = self.observations.get(preview.session_index)
        if observed is not None:
            self.journal.resolve(row.ref, before=observed)
        if result is not None:
            trace = result.original_artifacts.trace.events
            originals = [
                e
                for e in trace
                if isinstance(e, ExecutionAuthorizationTraceEventV1)
                and e.session_index == preview.session_index
            ]
            if len(originals) != 1:
                raise ValueError("CONTROLLED_EXECUTION_AUTHORIZATION_NOT_ORIGINAL")
            event = originals[0]
            if (
                event.preview_hash != expected.preview_hash
                or event.policy_hash != expected.policy_hash
                or event.verdict != expected.verdict
                or event.reason != expected.reason
            ):
                raise ValueError("CONTROLLED_EXECUTION_NOT_ORIGINAL_TRACE")
            fills = tuple(
                e.fill
                for e in trace
                if isinstance(e, FillTraceEventV1)
                and e.session_index == preview.session_index
            )
            expected_fills = (
                preview.outcome.committed_fills
                if expected.verdict == "approve"
                and preview.outcome.classification == "executed"
                else ()
            )
            if fills != expected_fills:
                raise ValueError("CONTROLLED_FALSE_COMMITTED_FILLS")
        self.take(row)

    def opportunity(
        self,
        checkpoint: C.ControlledCheckpointV1,
        context: DecisionContext,
        observation: SessionObservationV1,
        observation_row: ControlledRowV1,
        incumbent: C.Family,
        previous_learning: LearningSnapshot | None,
        feedback: tuple[TrialFeedbackRecord, ...],
    ) -> tuple[_Opportunity, LearningSnapshot | None]:
        rows = self.opportunity_rows[checkpoint.checkpoint_id]
        witness_row = self._one(rows, "input_witness")
        grant_row = self._one(rows, "grant")
        no_attempt = self._one(rows, "no_attempt")
        output_row = self._one(rows, "research_output")
        revocation = self._one(rows, "revocation")
        if witness_row is None:
            if rows:
                raise ValueError("CONTROLLED_PHASE_WITHOUT_ORIGINAL_INPUT_WITNESS")
            return _Opportunity(
                None, None, "ORIGINAL_INPUT_MISSING", False, False, False, (), ()
            ), previous_learning
        witness = witness_row.record
        assert isinstance(witness, C.InputWitnessRecordV1)
        resolved_observation = self.journal.resolve(
            witness.observation, before=witness_row
        )
        if (
            resolved_observation != observation_row
            or witness.context_kind != context_kind(context)
            or witness.decision_context.original_bytes() != canonical_json(context)
        ):
            raise ValueError("CONTROLLED_INPUT_NOT_ORIGINAL_DECISION_CONTEXT")
        if witness.original_available_at != witness_row.event.timestamp:
            raise ValueError("CONTROLLED_FALSE_INPUT_AVAILABILITY_WITNESS")
        learning = advance_learning(
            previous_snapshot=previous_learning,
            feedback_records=feedback,
            cutoff=checkpoint.decision_cutoff,
            arm_id=self.plan.original_account.fields.arm_id,
            method_ref=self.plan.context_template.method_ref,
            snapshot_id=self.plan.trial_id(checkpoint.checkpoint_id) + ":learning",
        )
        if witness.feedback != feedback or witness.learning != learning:
            raise ValueError("CONTROLLED_FALSE_OR_FOREIGN_OR_FUTURE_LEARNING")
        research = make_research_context(
            self.plan,
            checkpoint,
            context,
            observation,
            learning,
            witness.original_available_at,
            incumbent,
        )
        if witness.research_context != research:
            raise ValueError("CONTROLLED_RESEARCH_CONTEXT_NOT_ORIGINAL_INPUTS")
        self.take(witness_row)
        if grant_row is None:
            if len(rows) != 1:
                raise ValueError("CONTROLLED_PHASE_WITHOUT_ORIGINAL_GRANT")
            return _Opportunity(
                None,
                None,
                "ORIGINAL_GRANT_MISSING",
                False,
                False,
                False,
                (),
                tuple(rows),
            ), learning
        grant = grant_row.record
        assert isinstance(grant, C.GrantRecordV1)
        if self.journal.resolve(grant.input_witness, before=grant_row) != witness_row:
            raise ValueError("CONTROLLED_GRANT_WRONG_WITNESS")
        trial = self.plan.trial_id(checkpoint.checkpoint_id)
        expected_grant = C.GrantRecordV1(
            checkpoint_id=checkpoint.checkpoint_id,
            input_witness=witness_row.ref,
            logical_request_id=trial + ":REQUEST-001",
            attempt_id=trial + ":K1-001",
            not_before=checkpoint.not_before,
            expires_at=checkpoint.expires_at,
            budget_usd=checkpoint.research_budget_usd,
        )
        if grant != expected_grant:
            raise ValueError("CONTROLLED_GRANT_NOT_DECLARED_ORIGINAL_POLICY")
        self.take(grant_row)
        if revocation is not None:
            record = revocation.record
            assert isinstance(record, C.RevocationRecordV1)
            if (
                self.journal.resolve(record.grant, before=revocation) != grant_row
                or record.effective_at != checkpoint.revoked_at
                or record.reason != "Declared synthetic grant revocation"
            ):
                raise ValueError("CONTROLLED_FALSE_GRANT_REVOCATION")
            self.take(revocation)
        elif checkpoint.revoked_at is not None:
            self.reasons.add("ORIGINAL_REVOCATION_MISSING")
        attempt_rows = [r for r in rows if isinstance(r.record, C.AttemptRecordV1)]
        starts = [
            r
            for r in attempt_rows
            if isinstance(r.record, C.AttemptRecordV1)
            and r.record.original.status == "started"
        ]
        if len(starts) > 1:
            raise ValueError("CONTROLLED_GRANT_REUSED_OR_DUPLICATE_START")
        for row in rows:
            record = row.record
            if isinstance(
                record,
                (
                    C.AttemptRecordV1,
                    C.CostRecordV1,
                    C.ValidationRecordV1,
                    C.ResearchOutputRecordV1,
                    C.NoAttemptRecordV1,
                ),
            ):
                if (
                    record.grant is None
                    or self.journal.resolve(record.grant, before=row) != grant_row
                ):
                    raise ValueError("CONTROLLED_PHASE_WRONG_ORIGINAL_GRANT")
        if no_attempt is not None:
            if (
                starts
                or attempt_rows
                or output_row is not None
                or any(r.record.kind in ("cost", "validation") for r in rows)
            ):
                raise ValueError("CONTROLLED_NO_ATTEMPT_CONTRADICTS_RESEARCH")
            at = no_attempt.event.timestamp
            expected_skip = None
            if at < checkpoint.not_before:
                expected_skip = "NOT_YET_VALID"
            elif at >= checkpoint.expires_at:
                expected_skip = "EXPIRED"
            elif checkpoint.revoked_at is not None and at >= checkpoint.revoked_at:
                expected_skip = "REVOKED"
            elif checkpoint.fixture.cost_amount > checkpoint.research_budget_usd:
                expected_skip = "BUDGET_UNAVAILABLE"
            else:
                try:
                    _choices(self.plan, checkpoint, context, incumbent)
                except ValueError:
                    expected_skip = "INPUT_UNAVAILABLE"
            assert isinstance(no_attempt.record, C.NoAttemptRecordV1)
            if expected_skip != no_attempt.record.reason:
                raise ValueError("CONTROLLED_FALSE_NO_ATTEMPT_REASON")
            self.take(no_attempt)
            return _Opportunity(
                None, None, expected_skip, True, True, False, (), tuple(rows)
            ), learning
        if not starts:
            if any(
                r.record.kind in ("attempt", "cost", "validation", "research_output")
                for r in rows
            ):
                raise ValueError("CONTROLLED_RESEARCH_WITHOUT_ORIGINAL_START")
            return _Opportunity(
                None,
                None,
                "ORIGINAL_START_MISSING",
                False,
                False,
                False,
                (),
                tuple(rows),
            ), learning
        start_row = starts[0]
        assert isinstance(start_row.record, C.AttemptRecordV1)
        start = start_row.record.original.started_at
        if (
            start is None
            or start < grant_row.event.timestamp
            or start > start_row.event.timestamp
            or not checkpoint.not_before <= start < checkpoint.expires_at
            or (checkpoint.revoked_at is not None and start >= checkpoint.revoked_at)
        ):
            raise ValueError("CONTROLLED_START_NOT_AUTHORIZED_BY_ORIGINAL_GRANT")
        output, replay = _replay(
            self.plan, checkpoint, context, research, incumbent, grant, start
        )
        original_phases: list[tuple[str, bytes]] = []
        all_costs: list[CostReceipt] = []
        replay_costs = ResearchReceiptStore()
        for row in rows:
            record = row.record
            if isinstance(record, C.AttemptRecordV1):
                original_phases.append(("attempt", canonical_json(record.original)))
                if (
                    record.original.started_at is None
                    or record.original.started_at > row.event.timestamp
                    or (
                        record.original.completed_at is not None
                        and record.original.completed_at > row.event.timestamp
                    )
                ):
                    raise ValueError("CONTROLLED_ATTEMPT_RECORDED_BEFORE_ORIGINAL")
                self.take(row)
            elif isinstance(record, C.CostRecordV1):
                cost = record.original
                if (
                    cost.recorded_at is None
                    or cost.recorded_at > row.event.timestamp
                    or cost.attempt_id != grant.attempt_id
                    or cost.scope != research.scope
                ):
                    raise ValueError("CONTROLLED_COST_NOT_ORIGINAL_ATTEMPT")
                replay_costs.record_cost_receipt(cost)
                all_costs.append(cost)
                if cost.supersedes_receipt_id is None:
                    original_phases.append(("cost", canonical_json(cost)))
                elif (
                    output_row is None
                    or row.sequence <= output_row.sequence
                    or cost.recorded_at < output_row.event.timestamp
                    or cost.amount_basis != "actual"
                    or cost.raw_evidence_ref is None
                ):
                    raise ValueError(
                        "CONTROLLED_CORRECTION_BEFORE_ORIGINAL_OUTPUT_OR_UNVERIFIED"
                    )
                self.take(row)
            elif isinstance(record, C.ValidationRecordV1):
                if (
                    record.binding.checked_at > row.event.timestamp
                    or record.binding.completed_at > row.event.timestamp
                ):
                    raise ValueError("CONTROLLED_VALIDATION_PRECEDES_ACTUAL_CALL")
                original_phases.append(
                    (
                        "validation",
                        canonical_json(
                            {
                                "raw": record.raw_output_utf8,
                                "binding": record.binding,
                                "result": record.original,
                            }
                        ),
                    )
                )
                self.take(row)
            elif isinstance(record, C.ResearchOutputRecordV1):
                if record.completed_observed_at != row.event.timestamp:
                    raise ValueError("CONTROLLED_FALSE_OUTPUT_AVAILABILITY")
                original_phases.append(
                    ("research_output", record.output_utf8.encode("utf-8"))
                )
                self.take(row)
        expected_phases = replay.observations
        if original_phases != expected_phases[: len(original_phases)] or len(
            original_phases
        ) > len(expected_phases):
            raise ValueError("CONTROLLED_ORIGINAL_PRODUCER_REPLAY_MISMATCH")
        complete = original_phases == expected_phases
        candidate = (
            output.candidate
            if isinstance(output, ProducerResult)
            else output.selected_candidate
        )
        # This is a structural replay result, not evidence that a missing output
        # was actually produced. Incomplete original prefixes stay unresolved.
        if not complete or output_row is None:
            return _Opportunity(
                None,
                None,
                "ORIGINAL_RESEARCH_INCOMPLETE",
                False,
                False,
                False,
                tuple(all_costs),
                tuple(rows),
            ), learning
        assert isinstance(output_row.record, C.ResearchOutputRecordV1)
        reason = "VALIDATED_ORIGINAL_SELECTION"
        family = None
        if not output.is_success or candidate is None:
            reason = "RESEARCH_" + output.status
        elif output_row.event.timestamp >= checkpoint.expires_at or (
            checkpoint.revoked_at is not None
            and output_row.event.timestamp >= checkpoint.revoked_at
        ):
            reason = "RESEARCH_READY_OUTSIDE_GRANT"
        else:
            initial_costs = replay.get_cost_receipts_for_attempt(grant.attempt_id)
            if not initial_costs or any(
                c.amount_basis == "unknown" for c in initial_costs
            ):
                reason = "COST_UNAVAILABLE"
            elif sum(
                (
                    Fraction(Decimal(c.amount))
                    for c in initial_costs
                    if c.amount is not None
                ),
                Fraction(0),
            ) > C.finite_fraction(checkpoint.research_budget_usd):
                reason = "BUDGET_EXCEEDED"
            elif candidate.disposition != "propose" or candidate.strategy is None:
                reason = "RESEARCH_" + candidate.disposition.upper()
            else:
                family = cast(C.Family, candidate.strategy.family_id)
        return _Opportunity(
            family,
            candidate,
            reason,
            True,
            False,
            not output.is_success,
            tuple(all_costs),
            tuple(rows),
        ), learning

    def verify_decisions(
        self, result: LocalOriginalResultReadbackV1 | None
    ) -> dict[str, _Opportunity]:
        active: C.Family = "B3"
        learning: LearningSnapshot | None = None
        previous: tuple[C.ControlledCheckpointV1, ResearchCandidate, Decimal] | None = (
            None
        )
        opportunities: dict[str, _Opportunity] = {}
        by_index = {c.session_index: c for c in self.plan.checkpoints}
        trace_decisions = {}
        if result is not None:
            trace_decisions = {
                e.session_index: e
                for e in result.original_artifacts.trace.events
                if isinstance(
                    e,
                    (
                        StrategyDecisionTraceEventV1,
                        ExploratoryStrategyDecisionTraceEventV1,
                    ),
                )
            }
            if set(trace_decisions) != set(self.decisions):
                self.reasons.add("ORIGINAL_DECISION_RECORD_MISSING")
        for index in range(len(self.plan.sessions)):
            execution = self.executions.get(index)
            if execution is not None:
                assert isinstance(execution.record, C.ExecutionRecordV1)
                earlier = self.journal.resolve(
                    execution.record.decision, before=execution
                )
                assert isinstance(earlier.record, C.DecisionRecordV1)
                preview = execution.record.preview.parse(RebalancePreviewV1)
                if (
                    execution.record.authorization.verdict == "approve"
                    and preview.outcome.classification == "executed"
                ):
                    active = earlier.record.staged_family
                    checkpoint = by_index.get(earlier.record.session_index)
                    known = (
                        opportunities.get(checkpoint.checkpoint_id)
                        if checkpoint
                        else None
                    )
                    if (
                        checkpoint
                        and earlier.record.disposition == "SELECTED"
                        and known
                        and known.candidate
                    ):
                        prior_observation_record = self.observations[
                            earlier.record.session_index
                        ].record
                        assert isinstance(
                            prior_observation_record, C.ObservationRecordV1
                        )
                        previous = (
                            checkpoint,
                            known.candidate,
                            prior_observation_record.observation.state.net_asset_value,
                        )
            row = self.decisions.get(index)
            checkpoint = by_index.get(index)
            decision: C.DecisionRecordV1 | None = None
            if row is None:
                if (
                    checkpoint is None
                    or not self.opportunity_rows[checkpoint.checkpoint_id]
                ):
                    continue
                witness_row = self._one(
                    self.opportunity_rows[checkpoint.checkpoint_id], "input_witness"
                )
                if witness_row is None or not isinstance(
                    witness_row.record, C.InputWitnessRecordV1
                ):
                    raise ValueError("CONTROLLED_ORPHAN_OPPORTUNITY_PHASES")
                source = self.journal.resolve(
                    witness_row.record.observation, before=witness_row
                )
                context = parse_context(
                    witness_row.record.context_kind, witness_row.record.decision_context
                )
                self.reasons.add(
                    "OPPORTUNITY_WITHOUT_ORIGINAL_DECISION:" + checkpoint.checkpoint_id
                )
            else:
                if not isinstance(row.record, C.DecisionRecordV1):
                    raise ValueError("CONTROLLED_WRONG_DECISION_RECORD")
                decision = row.record
                source = self.journal.resolve(decision.observation, before=row)
                context = parse_context(
                    decision.context_kind, decision.decision_context
                )
            if (
                not isinstance(source.record, C.ObservationRecordV1)
                or source.record.observation.session_index != index
            ):
                raise ValueError("CONTROLLED_DECISION_WRONG_OBSERVATION")
            observation = source.record.observation
            if (
                context.session_key != observation.session.session_key
                or context.portfolio_nav != observation.state.net_asset_value
                or context.current_cash != observation.state.cash_balance
                or tuple((h.security_id, h.quantity) for h in context.current_holdings)
                != tuple(
                    (h.security_id, h.quantity) for h in observation.state.holdings
                )
            ):
                raise ValueError("CONTROLLED_DECISION_CONTEXT_NOT_ORIGINAL_BOOK")
            if decision is not None and decision.previous_family != active:
                raise ValueError("CONTROLLED_FAMILY_CHANGED_WITHOUT_EXECUTION")
            trace = trace_decisions.get(index)
            if (
                decision is not None
                and trace is not None
                and (
                    trace.context_hash != content_hash(context)
                    or trace.intent_hash != content_hash(decision.intent)
                )
            ):
                raise ValueError("CONTROLLED_DECISION_NOT_ORIGINAL_TRACE")
            if decision is not None and result is not None and trace is None:
                raise ValueError("CONTROLLED_DECISION_ABSENT_FROM_ORIGINAL_RESULT")
            checkpoint = by_index.get(index)
            proposed, staged = active, active
            candidate = None
            disposition = "INSTALLED"
            reason = "INSTALLED_FAMILY_INTERNAL_DECISION"
            if checkpoint is None:
                if decision is not None and decision.checkpoint_id is not None:
                    raise ValueError("CONTROLLED_UNDECLARED_DECISION_CHECKPOINT")
            else:
                if (
                    decision is not None
                    and decision.checkpoint_id != checkpoint.checkpoint_id
                ):
                    raise ValueError("CONTROLLED_DECISION_CHECKPOINT_MISMATCH")
                feedback: tuple[TrialFeedbackRecord, ...] = ()
                if previous is not None:
                    prior, old_candidate, nav = previous
                    feedback = (
                        TrialFeedbackRecord(
                            trial_id=self.plan.trial_id(prior.checkpoint_id),
                            arm_id=self.plan.original_account.fields.arm_id,
                            decision_cutoff=prior.decision_cutoff,
                            matured_at=checkpoint.decision_cutoff,
                            candidate_id=old_candidate.candidate_id,
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
                previous = None
                known, learning = self.opportunity(
                    checkpoint, context, observation, source, active, learning, feedback
                )
                opportunities[checkpoint.checkpoint_id] = known
                if row is not None:
                    # Research, including a legitimate no-attempt terminal,
                    # must exist before the decision that consumes it. A cost
                    # correction may be genuinely later and is not decision
                    # authorization; its original lineage is checked separately.
                    for original_row in known.rows:
                        if (
                            isinstance(original_row.record, C.CostRecordV1)
                            and original_row.record.original.supersedes_receipt_id
                            is not None
                        ):
                            continue
                        self.journal.resolve(original_row.ref, before=row)
                if not known.complete:
                    self.reasons.add(
                        "INCOMPLETE_ORIGINAL_RESEARCH:" + checkpoint.checkpoint_id
                    )
                proposed = known.family or active
                candidate = known.candidate
                reason, disposition = (
                    known.reason,
                    "SELECTED" if known.family else "RETAINED",
                )
            if decision is None:
                continue
            assert row is not None
            if index < self.plan.initial_decision_index:
                expected_intent = hold_intent(context)
                reason = "DECLARED_PREPARATION_CASH_NO_RESEARCH"
            else:
                try:
                    expected_intent = installed_intent(
                        proposed, context, self.plan.sessions
                    )
                    refusal = decision_mandate_reason(
                        self.plan.mandate, context, observation.state, expected_intent
                    )
                except ValueError as error:
                    refusal = str(error)
                    expected_intent = hold_intent(context)
                if refusal is not None:
                    disposition, reason = "REFUSED", refusal
                    expected_intent = hold_intent(context)
                else:
                    staged = proposed
            if (
                decision.intent != expected_intent
                or decision.proposed_family != proposed
                or decision.staged_family != staged
                or decision.disposition != disposition
                or decision.reason != reason
                or decision.candidate_hash
                != (candidate.record_hash if candidate else None)
            ):
                if checkpoint and not opportunities[checkpoint.checkpoint_id].complete:
                    # Do not certify a decision when its original research is
                    # absent, even if the evaluator independently finished.
                    self.reasons.add(
                        "UNVERIFIABLE_DECISION:" + checkpoint.checkpoint_id
                    )
                else:
                    raise ValueError("CONTROLLED_FALSE_RESEARCH_OR_MANDATE_DECISION")
            self.take(row)
        return opportunities


def read_controlled_campaign(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    allocation_id: UUID,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    provenance: Stage1TrialProvenanceSnapshotV1,
    clock: Callable[[], datetime],
    as_of_event_hash: str | None = None,
) -> ControlledCampaignReadbackV1:
    observed = observed_time(clock)
    captured = CapturedControlledJournalV1(
        origin=origin,
        allocation_id=allocation_id,
        observed_at=observed,
        as_of_event_hash=as_of_event_hash,
    )
    verifier = _Verifier(captured)
    plan = captured.plan
    if plan.source_inventory_hash != drift_source_inventory_hash():
        raise ValueError("CONTROLLED_REPLAY_REQUIRES_ORIGINAL_INSTALLED_SOURCE")
    manifest = captured.manifest.record
    assert isinstance(manifest, C.ManifestRecordV1)
    verify_stage1_trial_provenance_snapshot(
        snapshot=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    C.verify_declared_stage1_plan(plan, campaign, arms)
    fields = plan.original_account.fields
    scope = provenance.scope
    matching = [
        b
        for b in bindings
        if b.run_id == fields.run_id
        and b.arm_id == fields.arm_id
        and b.campaign_id == fields.campaign_id
    ]
    if (
        campaign.campaign_type != "SYNTHETIC_TEST"
        or plan.provenance_hash != provenance.snapshot_fingerprint
        or len(matching) != 1
        or fields.binding_hash != content_hash(asdict(matching[0]))
        or fields.portfolio_account_id != matching[0].portfolio_account_id
        or fields.complete_manifest_fingerprint != scope.complete_manifest_fingerprint
        or fields.campaign_fingerprint != scope.campaign_spec_fingerprint
        or fields.arm_id != scope.arm_id
        or fields.run_id != scope.run_id
    ):
        raise ValueError("CONTROLLED_MANIFEST_NOT_ORIGINAL_E1_SCOPE")
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=captured.origin, clock=lambda: observed
    )
    original = store.readback_allocation(
        allocation_id=allocation_id,
        allocation_ref=_local(plan.original_account.allocation),
        witness_ref=_local(plan.original_account.witness),
        expected_fields=fields,
    )
    if content_hash(original.opening_book) != plan.original_account.original_book_hash:
        raise ValueError("CONTROLLED_OPENING_BOOK_SUBSTITUTED")
    witness = captured.original(manifest.original_witness, before=captured.manifest)
    if (
        manifest.original_witness != plan.original_account.witness
        or manifest.scheduler_witness_observed_at != captured.manifest.event.timestamp
        or manifest.scheduler_witness_observed_at < witness.timestamp
    ):
        raise ValueError("CONTROLLED_SCHEDULER_WITNESS_NOT_ORIGINAL")
    claims = [
        (index, event)
        for index, event in enumerate(captured.events)
        if event.event_type == CLAIM and event.entity_id == allocation_id
    ]
    binding = None
    if len(claims) > 1:
        raise ValueError("CONTROLLED_MULTIPLE_ORIGINAL_ACCOUNT_INVOCATIONS")
    if claims:
        index, claim = claims[0]
        if index <= captured.manifest.sequence or not isinstance(
            claim.payload, Mapping
        ):
            raise ValueError("CONTROLLED_ACCOUNT_CLAIM_PRECEDES_MANIFEST")
        binding = parse_original_invocation_binding(
            claim.payload.get("invocation_binding")
        )
        if (
            binding.m0_run_id != manifest.m0_run_id
            or binding.m0_audit_event_id != manifest.m0_audit_event_id
        ):
            raise ValueError("CONTROLLED_MANIFEST_M0_INVOCATION_MISMATCH")
        if any(row.sequence <= index for row in verifier.observations.values()):
            raise ValueError("CONTROLLED_OBSERVATION_BEFORE_ACCOUNT_CLAIM")
    elif verifier.observations or verifier.decisions or verifier.executions:
        raise ValueError("CONTROLLED_EXECUTION_WITHOUT_ORIGINAL_ACCOUNT_CLAIM")
    result = None
    if verifier.terminal is not None:
        terminal = verifier.terminal.record
        assert isinstance(terminal, C.TerminalRecordV1)
        if (
            terminal.m0_run_id != manifest.m0_run_id
            or terminal.m0_audit_event_id != manifest.m0_audit_event_id
        ):
            raise ValueError("CONTROLLED_TERMINAL_WRONG_M0")
        m0 = captured.by_id.get(manifest.m0_audit_event_id)
        if (
            m0 is None
            or m0[0] >= verifier.terminal.sequence
            or m0[1].timestamp > verifier.terminal.event.timestamp
            or not isinstance(m0[1].payload, Mapping)
            or m0[1].payload.get("status") != terminal.m0_status
        ):
            raise ValueError("CONTROLLED_TERMINAL_WITHOUT_ORIGINAL_M0")
        if terminal.m0_status == "completed":
            # A completed original M0 audit is the completion of the actual
            # evaluator execution, not merely an identifier which happens to
            # precede the later RESULT/terminal receipts. Every original
            # campaign phase which is required to have happened during that
            # execution must be retained *before* this M0 audit, even when
            # their operational timestamps compare equal. An explicitly
            # superseding cost receipt is different: it may be appended after
            # completion and can only change a later derived as-of report.
            if any(
                row.sequence >= m0[0]
                for row in captured.rows
                if not isinstance(row.record, C.TerminalRecordV1)
                and not (
                    isinstance(row.record, C.CostRecordV1)
                    and row.record.original.supersedes_receipt_id is not None
                )
            ):
                raise ValueError("CONTROLLED_ORIGINAL_M0_BEFORE_CAMPAIGN_EVIDENCE")
            if terminal.result_association is None:
                raise ValueError("CONTROLLED_COMPLETION_WITHOUT_RESULT")
            captured.original(terminal.result_association, before=verifier.terminal)
            result = read_original_result(
                origin=captured.origin,
                original_account=original,
                association_ref=_local(terminal.result_association),
                provenance=provenance,
                campaign=campaign,
                arms=arms,
                bindings=bindings,
                expected_run_ids=expected_run_ids,
                clock=lambda: observed,
            )
            identity = result.original_artifacts.result.run_identity
            if not isinstance(identity, EvaluationRunIdentityV2):
                raise ValueError("CONTROLLED_RESULT_NOT_V2_IDENTITY")
            if (
                result.classification != terminal.classification
                or result.operational_m0_run_id != manifest.m0_run_id
                or result.invocation_binding != binding
                or identity.strategy_hash != controlled_strategy_reference().code_hash
                or identity.strategy_parameters_hash
                != strategy_parameters_hash(financial_parameters(plan))
                or identity.bundle_hash != plan.input_bundle_hash
                or identity.code_version_hash != plan.source_inventory_hash
                or identity.cost_model_hash != plan.cost_model_hash
                or identity.protocol_hash != plan.protocol_hash
                or identity.admission_hash != plan.admission_hash
                or identity.evaluator_evidence_hash != plan.evaluator_evidence_hash
            ):
                raise ValueError("CONTROLLED_RESULT_NOT_DECLARED_INSTALLED_CAMPAIGN")
        elif (
            terminal.result_association is not None
            or terminal.classification is not None
        ):
            raise ValueError("CONTROLLED_FAILED_M0_HAS_SUCCESSFUL_RESULT")
        verifier.take(verifier.terminal)
    verifier.verify_observations(result, binding)
    verifier.verify_execution_inventory(result)
    for row in verifier.executions.values():
        verifier.verify_execution(row, result, binding)
    opportunities = verifier.verify_decisions(result)
    if set(captured.rows_by_id) != verifier.accounted:
        raise ValueError("CONTROLLED_UNACCOUNTED_ORIGINAL_JOURNAL_ENTRY")
    assert captured.tip is not None
    trials: list[ControlledTrialProjectionV1] = []
    observed_indices = set(verifier.observations)
    last_observed = max(observed_indices, default=-1)
    terminated = (
        verifier.terminal is not None or manifest.m0_audit_event_id in captured.by_id
    )
    for number, checkpoint in enumerate(plan.checkpoints):
        info = opportunities.get(checkpoint.checkpoint_id)
        end = (
            plan.checkpoints[number + 1].session_index
            if number + 1 < len(plan.checkpoints)
            else len(plan.sessions) - 1
        )
        start_row, end_row = (
            verifier.observations.get(checkpoint.session_index),
            verifier.observations.get(end),
        )
        start_state = (
            start_row.record.observation.state
            if start_row is not None
            and isinstance(start_row.record, C.ObservationRecordV1)
            else None
        )
        end_state = (
            end_row.record.observation.state
            if end_row is not None and isinstance(end_row.record, C.ObservationRecordV1)
            else None
        )
        outcome: Literal[
            "COMPLETED",
            "RETAINED",
            "REFUSED",
            "NO_ATTEMPT",
            "FAILED_RESEARCH",
            "UNRESOLVED",
            "NOT_YET_DUE",
        ] = "UNRESOLVED"
        reason = "ORIGINAL_OPPORTUNITY_UNAVAILABLE"
        family = None
        if info is None or not info.complete:
            if checkpoint.session_index > last_observed and not terminated:
                outcome, reason = "NOT_YET_DUE", "DECLARED_FUTURE_OPPORTUNITY"
            else:
                verifier.reasons.add(
                    "MISSING_DUE_OPPORTUNITY:" + checkpoint.checkpoint_id
                )
        elif info.no_attempt:
            outcome, reason = "NO_ATTEMPT", info.reason
        elif info.failed_research:
            outcome, reason = "FAILED_RESEARCH", info.reason
        elif checkpoint.session_index not in verifier.decisions:
            outcome, reason = "UNRESOLVED", "ORIGINAL_DECISION_UNAVAILABLE"
            verifier.reasons.add(
                "MISSING_ORIGINAL_DECISION:" + checkpoint.checkpoint_id
            )
        else:
            decision_row = verifier.decisions.get(checkpoint.session_index)
            execution_row = verifier.executions.get(checkpoint.session_index + 1)
            assert decision_row is not None and isinstance(
                decision_row.record, C.DecisionRecordV1
            )
            approved = (
                execution_row is not None
                and isinstance(execution_row.record, C.ExecutionRecordV1)
                and execution_row.record.authorization.verdict == "approve"
            )
            if decision_row.record.disposition == "SELECTED" and approved:
                outcome, reason, family = "COMPLETED", info.reason, info.family
            elif decision_row.record.disposition == "RETAINED" and approved:
                outcome, reason = "RETAINED", decision_row.record.reason
            elif execution_row is None and decision_row.record.disposition != "REFUSED":
                outcome, reason = "UNRESOLVED", "ORIGINAL_EXECUTION_UNAVAILABLE"
            elif (
                execution_row is not None
                and isinstance(execution_row.record, C.ExecutionRecordV1)
                and execution_row.record.authorization.verdict == "reject"
                and decision_row.record.disposition != "REFUSED"
            ):
                outcome, reason = "REFUSED", execution_row.record.authorization.reason
            else:
                outcome, reason = "REFUSED", decision_row.record.reason
        if any(
            checkpoint.session_index < index <= end
            for index in verifier.missing_executions
        ):
            outcome, reason, family = (
                "UNRESOLVED",
                "MISSING_ORIGINAL_EXECUTION_RECORD",
                None,
            )
        complete_interval = (
            result is not None
            and start_state is not None
            and end_state is not None
            and info is not None
            and info.complete
            and outcome not in ("UNRESOLVED", "NOT_YET_DUE")
            and all(
                i in observed_indices for i in range(checkpoint.session_index, end + 1)
            )
        )
        result_ref = (
            C.OriginalReferenceV1(
                event_id=result.association_ref.event_id,
                event_hash=result.association_ref.event_hash,
            )
            if result
            else None
        )
        projection_rows = (
            info.rows
            if info
            else tuple(verifier.opportunity_rows[checkpoint.checkpoint_id])
        )
        costs = (
            info.costs
            if info
            else tuple(
                r.record.original
                for r in projection_rows
                if isinstance(r.record, C.CostRecordV1)
            )
        )
        trading = (
            C.exact_decimal(
                C.finite_fraction(end_state.cumulative_transaction_costs)
                - C.finite_fraction(start_state.cumulative_transaction_costs)
            )
            if start_state is not None and end_state is not None
            else None
        )
        trials.append(
            make_trial_projection(
                campaign_id=fields.campaign_id,
                run_id=fields.run_id,
                arm_id=fields.arm_id,
                account_id=fields.portfolio_account_id,
                checkpoint_id=checkpoint.checkpoint_id,
                trial_id=plan.trial_id(checkpoint.checkpoint_id),
                manifest_hash=plan.plan_hash,
                original_allocation=plan.original_account.allocation,
                original_result=result_ref,
                snapshot_tip=captured.tip,
                original_event_hashes=tuple(
                    r.event.event_hash for r in projection_rows
                ),
                start_session_index=checkpoint.session_index,
                end_session_index=end if end_state else None,
                outcome=outcome,
                complete_interval=complete_interval,
                selected_family=family,
                start_nav=start_state.net_asset_value if start_state else None,
                end_nav=end_state.net_asset_value if end_state else None,
                trading_costs=trading,
                costs=costs,
                reason=reason,
            )
        )
    status: Literal["VERIFIED_COMPLETE", "VERIFIED_PARTIAL", "UNRESOLVED"] = (
        "UNRESOLVED"
    )
    if result is not None and not verifier.reasons:
        full = (
            result.classification == "complete"
            and observed_indices == set(range(len(plan.sessions)))
            and all(t.complete_interval for t in trials)
        )
        status = "VERIFIED_COMPLETE" if full else "VERIFIED_PARTIAL"
    if result is None:
        verifier.reasons.add("ORIGINAL_TERMINAL_RESULT_UNAVAILABLE")
    # Start immediately before the first scoring open. This includes the initial
    # B3 interval and prevents reporting only the later adaptive windows.
    scoring_indices = range(plan.initial_decision_index, len(plan.sessions))
    navs: list[Decimal | None] = []
    fees: list[Decimal | None] = []
    for index in scoring_indices:
        observed_row = verifier.observations.get(index)
        state = (
            observed_row.record.observation.state
            if observed_row is not None
            and isinstance(observed_row.record, C.ObservationRecordV1)
            else None
        )
        navs.append(state.net_asset_value if state is not None else None)
        fees.append(state.cumulative_transaction_costs if state is not None else None)
    full_costs = tuple(
        row.record.original
        for row in captured.rows
        if isinstance(row.record, C.CostRecordV1)
    )
    operating = project_operating_costs(full_costs)
    complete = status == "VERIFIED_COMPLETE" and all(n is not None for n in navs)
    trading = (
        C.exact_decimal(C.finite_fraction(fees[-1]) - C.finite_fraction(fees[0]))
        if complete and fees[0] is not None and fees[-1] is not None
        else None
    )
    notional = None
    if complete and result is not None:
        scoring_keys = {
            s.session_key for s in plan.sessions[plan.initial_decision_index + 1 :]
        }
        notional = C.exact_decimal(
            sum(
                (
                    C.finite_fraction(event.fill.unadjusted_open_price)
                    * event.fill.quantity
                    for event in result.original_artifacts.trace.events
                    if isinstance(event, FillTraceEventV1)
                    and event.session_key in scoring_keys
                ),
                Fraction(0),
            )
        )
    economics = ControlledCampaignEconomicsV1(
        campaign_id=fields.campaign_id,
        campaign_fingerprint=fields.campaign_fingerprint,
        full_manifest_fingerprint=fields.complete_manifest_fingerprint,
        run_id=fields.run_id,
        arm_id=fields.arm_id,
        account_id=fields.portfolio_account_id,
        comparability_hash=content_hash(
            {
                "input": plan.input_bundle_hash,
                "cost": plan.cost_model_hash,
                "protocol": plan.protocol_hash,
                "admission": plan.admission_hash,
                "evaluator_evidence": plan.evaluator_evidence_hash,
                "source": plan.source_inventory_hash,
                "mandate": plan.mandate,
                "sessions": plan.sessions,
                "initial": plan.initial_decision_index,
                "coverage": plan.coverage,
                "clock_policy": plan.clock_policy,
                "opportunities": tuple(
                    (
                        c.checkpoint_id,
                        c.session_index,
                        c.decision_cutoff,
                        c.not_before,
                        c.expires_at,
                        c.revoked_at,
                        c.research_budget_usd,
                    )
                    for c in plan.checkpoints
                ),
            }
        ),
        start_session_index=plan.initial_decision_index,
        end_session_index=len(plan.sessions) - 1,
        complete=complete,
        initial_net_nav=navs[0],
        terminal_net_nav=navs[-1],
        trading_costs=trading,
        gross_filled_notional=notional,
        operating_cost=operating,
        economic_gain=calculate_economic_gain(
            initial_net_nav=navs[0] if complete else None,
            terminal_net_nav=navs[-1] if complete else None,
            attributed_operating_cost=operating.amount,
        ),
        maximum_drawdown=calculate_maximum_drawdown(navs if complete else [None]),
    )
    return ControlledCampaignReadbackV1(
        allocation_id=allocation_id,
        manifest_hash=plan.plan_hash,
        snapshot_tip=captured.tip,
        status=status,
        reasons=tuple(sorted(verifier.reasons)),
        declared_opportunities=len(plan.checkpoints),
        accounted_event_hashes=tuple(r.event.event_hash for r in captured.rows),
        trials=tuple(trials),
        original_result=result,
        source_coverage=plan.coverage,
        economics=economics,
    )


@dataclass(frozen=True, slots=True)
class ControlledComparisonReadbackV1:
    """One matched synthetic B/R run, never checkpoint-count significance."""

    test: ControlledCampaignReadbackV1
    comparator: ControlledCampaignReadbackV1
    economic_advantage: MetricArithmeticValue
    evidence_hash: str
    independent_account_count: Literal[2] = 2
    independent_paired_run_count: Literal[1] = 1
    scientific_conclusion: Literal["INSUFFICIENT_INDEPENDENT_QUALIFIED_RUNS"] = (
        "INSUFFICIENT_INDEPENDENT_QUALIFIED_RUNS"
    )

    @property
    def authorizes_trading(self) -> bool:
        return False


def compare_controlled_campaigns(
    *,
    test_origin: ConfiguredLocalSyntheticOriginV1,
    comparator_origin: ConfiguredLocalSyntheticOriginV1,
    test_allocation_id: UUID,
    comparator_allocation_id: UUID,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    test_provenance: Stage1TrialProvenanceSnapshotV1,
    comparator_provenance: Stage1TrialProvenanceSnapshotV1,
    clock: Callable[[], datetime],
    test_as_of: str | None = None,
    comparator_as_of: str | None = None,
) -> ControlledComparisonReadbackV1:
    """Cold-verify both original accounts; caller-made reports cannot substitute.

    Each original ledger is read at one captured prefix and both use the same
    observation instant. Different journals need not share a global transaction;
    the returned evidence pins both exact original prefix tips explicitly.
    """
    observed = observed_time(clock)
    test = read_controlled_campaign(
        origin=test_origin,
        allocation_id=test_allocation_id,
        provenance=test_provenance,
        as_of_event_hash=test_as_of,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        clock=lambda: observed,
    )
    comparator = read_controlled_campaign(
        origin=comparator_origin,
        allocation_id=comparator_allocation_id,
        provenance=comparator_provenance,
        as_of_event_hash=comparator_as_of,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        clock=lambda: observed,
    )
    left, right = test.economics, comparator.economics
    if (
        test.allocation_id == comparator.allocation_id
        or left.account_id == right.account_id
        or left.arm_id != campaign.primary_comparison.test_arm_id
        or right.arm_id != campaign.primary_comparison.comparator_arm_id
        or left.run_id != right.run_id
        or left.campaign_fingerprint != right.campaign_fingerprint
        or left.full_manifest_fingerprint != right.full_manifest_fingerprint
        or left.comparability_hash != right.comparability_hash
        or (
            test.original_result is not None
            and comparator.original_result is not None
            and test.original_result.invocation_binding
            == comparator.original_result.invocation_binding
        )
    ):
        raise ValueError("CONTROLLED_COMPARISON_NOT_DISTINCT_MATCHED_B_R")
    advantage = calculate_comparative_economic_advantage(
        left.economic_gain, right.economic_gain
    )
    return ControlledComparisonReadbackV1(
        test=test,
        comparator=comparator,
        economic_advantage=advantage,
        evidence_hash=content_hash(
            {
                "test_tip": test.snapshot_tip,
                "comparator_tip": comparator.snapshot_tip,
                "test": asdict(left),
                "comparator": asdict(right),
                "advantage": asdict(advantage),
            }
        ),
    )
