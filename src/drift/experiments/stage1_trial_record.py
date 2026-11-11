"""Stage 1 derived scientific trial record admission.

Resolves #485, #507, and #508.
Binds exact E1 campaign/arm/account manifest, original research decision context,
candidate or reasoned absence, attempt and cost receipts, model replay, M0 invocation,
M2 RESULT, and carried account state. Rejects caller-supplied strings without genuine
producer origin or manifest alignment.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.evaluator.opening_book_lifecycle import (
    OriginalInvocationBindingV1,
)
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_projection import (
    ExactRatioV1,
    OperatingCostProjectionV1,
    project_operating_costs,
)
from drift.experiments.stage1_trial_provenance import _complete_manifest_fingerprint
from drift.intelligence.contracts import (
    AttemptRecord,
    CostReceipt,
    ModelReplayRecord,
    ResearchCandidate,
    ResearchContext,
)
from drift.intelligence.receipts import ResearchReceiptStore
from drift.loop.stage1_controlled_contracts import (
    OriginalReferenceV1,
    exact_decimal,
    finite_fraction,
)
from drift.serialization.canonical import content_hash


class Stage1TrialAdmissionError(ValueError):
    """Refusal on invalid, forged, or unauthenticated trial evidence."""


class Stage1ResearchTrialBindingV1(FrozenModel):
    """Research-to-trial association with structural consistency checks."""

    schema_version: Literal["drift-research-trial-binding/1"] = (
        "drift-research-trial-binding/1"
    )
    campaign_id: NonBlankStr
    campaign_spec_fingerprint: SHA256Hash
    complete_manifest_fingerprint: SHA256Hash
    run_id: NonBlankStr
    arm_id: NonBlankStr
    portfolio_account_id: NonBlankStr
    checkpoint_id: NonBlankStr
    trial_id: NonBlankStr
    research_context: ResearchContext
    disposition: Literal["propose", "hold", "abstain", "unavailable"]
    candidate: ResearchCandidate | None = None
    reasoned_absence_code: str | None = None
    attempts: tuple[AttemptRecord, ...] = ()
    costs: tuple[CostReceipt, ...] = ()
    model_replay: ModelReplayRecord | None = None
    issuer_authority_id: NonBlankStr
    binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        expected_trial_id = (
            f"{self.campaign_id}:{self.run_id}:{self.arm_id}:{self.checkpoint_id}"
        )
        if self.trial_id != expected_trial_id:
            raise Stage1TrialAdmissionError("TRIAL_ID_MISMATCH")

        # Causal and scope checks
        scope = self.research_context.scope
        if (
            scope.campaign_ref.id != self.campaign_id
            or scope.campaign_ref.sha256 != self.campaign_spec_fingerprint
        ):
            raise Stage1TrialAdmissionError("RESEARCH_CONTEXT_CAMPAIGN_MISMATCH")
        if scope.arm_id != self.arm_id:
            raise Stage1TrialAdmissionError("RESEARCH_CONTEXT_ARM_MISMATCH")
        if scope.account_id != self.portfolio_account_id:
            raise Stage1TrialAdmissionError("RESEARCH_CONTEXT_ACCOUNT_MISMATCH")

        if self.candidate is not None:
            if (
                self.candidate.scope.campaign_ref.id != self.campaign_id
                or self.candidate.scope.campaign_ref.sha256
                != self.campaign_spec_fingerprint
            ):
                raise Stage1TrialAdmissionError("CANDIDATE_CAMPAIGN_MISMATCH")
            if self.candidate.scope.account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("CANDIDATE_ACCOUNT_MISMATCH")
            if self.candidate.scope.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("CANDIDATE_ARM_MISMATCH")
            if (
                self.candidate.context_ref.id != self.research_context.context_id
                or self.candidate.context_ref.version != self.research_context.profile
                or self.candidate.context_ref.sha256
                != self.research_context.record_hash
            ):
                raise Stage1TrialAdmissionError("CANDIDATE_CONTEXT_MISMATCH")

        if self.disposition == "propose":
            if self.candidate is None:
                raise Stage1TrialAdmissionError(
                    "PROPOSE_DISPOSITION_REQUIRES_CANDIDATE"
                )
            if self.candidate.disposition != "propose":
                raise Stage1TrialAdmissionError("CANDIDATE_DISPOSITION_MISMATCH")
        else:
            if (
                self.candidate is not None
                and self.candidate.disposition != self.disposition
            ):
                raise Stage1TrialAdmissionError("NON_TRADING_DISPOSITION_MISMATCH")
            if not self.reasoned_absence_code:
                raise Stage1TrialAdmissionError("REASONED_ABSENCE_CODE_REQUIRED")

        attempt_store = ResearchReceiptStore()
        for attempt in self.attempts:
            if (
                attempt.scope.campaign_ref.id != self.campaign_id
                or attempt.scope.campaign_ref.sha256 != self.campaign_spec_fingerprint
            ):
                raise Stage1TrialAdmissionError("ATTEMPT_CAMPAIGN_MISMATCH")
            if attempt.scope.account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("ATTEMPT_ACCOUNT_MISMATCH")
            if attempt.scope.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("ATTEMPT_ARM_MISMATCH")
            try:
                attempt_store.record_attempt(attempt)
            except Exception as exc:
                msg = f"INVALID_ATTEMPT_CHAIN: {exc}"
                raise Stage1TrialAdmissionError(msg) from exc

        for cost in self.costs:
            if (
                cost.scope.campaign_ref.id != self.campaign_id
                or cost.scope.campaign_ref.sha256 != self.campaign_spec_fingerprint
            ):
                raise Stage1TrialAdmissionError("COST_CAMPAIGN_MISMATCH")
            if cost.scope.account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("COST_ACCOUNT_MISMATCH")
            if cost.scope.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("COST_ARM_MISMATCH")
            try:
                attempt_store.record_cost_receipt(cost)
            except Exception as exc:
                msg = f"INVALID_COST_RECEIPT: {exc}"
                raise Stage1TrialAdmissionError(msg) from exc

        if self.model_replay is not None:
            if (
                self.model_replay.scope.campaign_ref.id != self.campaign_id
                or self.model_replay.scope.campaign_ref.sha256
                != self.campaign_spec_fingerprint
            ):
                raise Stage1TrialAdmissionError("MODEL_REPLAY_CAMPAIGN_MISMATCH")
            if self.model_replay.scope.account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("MODEL_REPLAY_ACCOUNT_MISMATCH")
            if self.model_replay.scope.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("MODEL_REPLAY_ARM_MISMATCH")
            if (
                self.model_replay.context_ref.id != self.research_context.context_id
                or self.model_replay.context_ref.sha256
                != self.research_context.record_hash
            ):
                raise Stage1TrialAdmissionError("MODEL_REPLAY_CONTEXT_MISMATCH")
            if (
                self.candidate is not None
                and self.model_replay.attempt_id != self.candidate.attempt_id
            ):
                raise Stage1TrialAdmissionError("MODEL_REPLAY_ATTEMPT_MISMATCH")
            if self.attempts and self.model_replay.attempt_id not in {
                a.attempt_id for a in self.attempts
            }:
                raise Stage1TrialAdmissionError("MODEL_REPLAY_ATTEMPT_NOT_FOUND")

            if (
                self.candidate is not None
                and self.candidate.model_replay_ref is not None
            ):
                if (
                    self.candidate.model_replay_ref.id != self.model_replay.replay_id
                    or self.candidate.model_replay_ref.sha256
                    != self.model_replay.record_hash
                ):
                    raise Stage1TrialAdmissionError(
                        "CANDIDATE_MODEL_REPLAY_REF_MISMATCH"
                    )

            for attempt in self.attempts:
                if (
                    attempt.attempt_id == self.model_replay.attempt_id
                    and attempt.model_replay_ref is not None
                ):
                    if (
                        attempt.model_replay_ref.id != self.model_replay.replay_id
                        or attempt.model_replay_ref.sha256
                        != self.model_replay.record_hash
                    ):
                        raise Stage1TrialAdmissionError(
                            "ATTEMPT_MODEL_REPLAY_REF_MISMATCH"
                        )
        else:
            if (
                self.candidate is not None
                and self.candidate.model_replay_ref is not None
            ):
                raise Stage1TrialAdmissionError(
                    "MISSING_MODEL_REPLAY_FOR_CANDIDATE_REF"
                )
            for attempt in self.attempts:
                if attempt.model_replay_ref is not None:
                    raise Stage1TrialAdmissionError(
                        "MISSING_MODEL_REPLAY_FOR_ATTEMPT_REF"
                    )

        data = self.model_dump(mode="python", exclude={"binding_hash"})
        computed = content_hash(data)
        if self.binding_hash != computed:
            raise Stage1TrialAdmissionError("RESEARCH_BINDING_HASH_MISMATCH")
        return self


class InvocationBindingPayloadV1(FrozenModel):
    """Immutable Pydantic wrapper around OriginalInvocationBindingV1."""

    invocation_id: UUID
    m0_run_id: UUID
    m0_audit_event_id: UUID

    def as_binding(self) -> OriginalInvocationBindingV1:
        return OriginalInvocationBindingV1(
            invocation_id=self.invocation_id,
            m0_run_id=self.m0_run_id,
            m0_audit_event_id=self.m0_audit_event_id,
        )


class Stage1ResultTrialBindingV1(FrozenModel):
    """Platform RESULT-to-trial association with structural consistency checks."""

    schema_version: Literal["drift-result-trial-binding/1"] = (
        "drift-result-trial-binding/1"
    )
    campaign_id: NonBlankStr
    campaign_spec_fingerprint: SHA256Hash
    complete_manifest_fingerprint: SHA256Hash
    run_id: NonBlankStr
    arm_id: NonBlankStr
    portfolio_account_id: NonBlankStr
    checkpoint_id: NonBlankStr
    trial_id: NonBlankStr
    opening_book_identity: NonBlankStr
    opening_book_hash: SHA256Hash
    m0_invocation: InvocationBindingPayloadV1
    result_hash: SHA256Hash
    trace_hash: SHA256Hash
    final_book_hash: SHA256Hash
    final_nav: Decimal
    cash_balance: Decimal
    cumulative_transaction_costs: Decimal
    order_count: int = Field(ge=0)
    fill_count: int = Field(ge=0)
    classification: Literal["complete", "rejected", "halted", "indeterminate"]
    ledger_ref: OriginalReferenceV1
    binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        expected_trial_id = (
            f"{self.campaign_id}:{self.run_id}:{self.arm_id}:{self.checkpoint_id}"
        )
        if self.trial_id != expected_trial_id:
            raise Stage1TrialAdmissionError("TRIAL_ID_MISMATCH")

        if self.order_count < self.fill_count:
            raise Stage1TrialAdmissionError("FILL_COUNT_EXCEEDS_ORDER_COUNT")
        if self.order_count < 0 or self.fill_count < 0:
            raise Stage1TrialAdmissionError("NEGATIVE_ORDER_OR_FILL_COUNT")

        data = self.model_dump(mode="python", exclude={"binding_hash"})
        computed = content_hash(data)
        if self.binding_hash != computed:
            raise Stage1TrialAdmissionError("RESULT_BINDING_HASH_MISMATCH")
        return self


class Stage1DerivedTrialRecordV1(FrozenModel):
    """Immutable derived scientific trial record conforming to experiment.md (#485)."""

    schema_version: Literal["drift-derived-trial/1"] = "drift-derived-trial/1"
    trial_id: NonBlankStr
    campaign_id: NonBlankStr
    campaign_spec_fingerprint: SHA256Hash
    complete_manifest_fingerprint: SHA256Hash
    run_id: NonBlankStr
    arm_id: NonBlankStr
    portfolio_account_id: NonBlankStr
    checkpoint_id: NonBlankStr
    opening_book_identity: NonBlankStr
    opening_book_hash: SHA256Hash
    research_binding: Stage1ResearchTrialBindingV1 | None = None
    result_binding: Stage1ResultTrialBindingV1 | None = None
    source_inventory_hash: SHA256Hash
    calendar_hash: SHA256Hash
    start_session_index: int = Field(ge=0)
    end_session_index: int | None = Field(default=None, ge=0)
    outcome_classification: Literal[
        "COMPLETED",
        "RETAINED",
        "REFUSED",
        "NO_ATTEMPT",
        "FAILED_RESEARCH",
        "UNRESOLVED",
        "NOT_YET_DUE",
    ]
    completeness_classification: Literal[
        "COMPLETE",
        "PENDING_RESULT",
        "PARTIAL_FILL",
        "UNKNOWN_EXECUTION",
        "MISSING_COST",
        "INVALID",
    ]
    operating_cost_projection: OperatingCostProjectionV1
    start_nav: Decimal | None = None
    end_nav: Decimal | None = None
    trading_costs: Decimal | None = None
    net_investment_gain: Decimal | None = None
    net_investment_return: ExactRatioV1 | None = None
    economic_gain: Decimal | None = None
    economic_return: ExactRatioV1 | None = None
    reasons: tuple[NonBlankStr, ...] = ()
    trial_record_hash: SHA256Hash

    @property
    def scientifically_qualified(self) -> bool:
        return False

    @property
    def authorizes_trading(self) -> bool:
        return False

    @model_validator(mode="after")
    def validate_trial_record(self) -> Self:
        expected_trial_id = (
            f"{self.campaign_id}:{self.run_id}:{self.arm_id}:{self.checkpoint_id}"
        )
        if self.trial_id != expected_trial_id:
            raise Stage1TrialAdmissionError("TRIAL_ID_MISMATCH")

        if (
            self.end_session_index is not None
            and self.end_session_index < self.start_session_index
        ):
            raise Stage1TrialAdmissionError("TRIAL_NEGATIVE_INTERVAL")

        # Research binding consistency
        if self.research_binding is not None:
            rb = self.research_binding
            if rb.campaign_id != self.campaign_id:
                raise Stage1TrialAdmissionError("RESEARCH_CAMPAIGN_MISMATCH")
            if rb.run_id != self.run_id:
                raise Stage1TrialAdmissionError("RESEARCH_RUN_MISMATCH")
            if rb.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("RESEARCH_ARM_MISMATCH")
            if rb.portfolio_account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("RESEARCH_ACCOUNT_MISMATCH")
            if rb.checkpoint_id != self.checkpoint_id:
                raise Stage1TrialAdmissionError("RESEARCH_CHECKPOINT_MISMATCH")
            if rb.campaign_spec_fingerprint != self.campaign_spec_fingerprint:
                raise Stage1TrialAdmissionError(
                    "RESEARCH_CAMPAIGN_FINGERPRINT_MISMATCH"
                )
            if rb.complete_manifest_fingerprint != self.complete_manifest_fingerprint:
                raise Stage1TrialAdmissionError(
                    "RESEARCH_MANIFEST_FINGERPRINT_MISMATCH"
                )

        # Result binding consistency
        if self.result_binding is not None:
            res = self.result_binding
            if res.campaign_id != self.campaign_id:
                raise Stage1TrialAdmissionError("RESULT_CAMPAIGN_MISMATCH")
            if res.run_id != self.run_id:
                raise Stage1TrialAdmissionError("RESULT_RUN_MISMATCH")
            if res.arm_id != self.arm_id:
                raise Stage1TrialAdmissionError("RESULT_ARM_MISMATCH")
            if res.portfolio_account_id != self.portfolio_account_id:
                raise Stage1TrialAdmissionError("RESULT_ACCOUNT_MISMATCH")
            if res.checkpoint_id != self.checkpoint_id:
                raise Stage1TrialAdmissionError("RESULT_CHECKPOINT_MISMATCH")
            if res.campaign_spec_fingerprint != self.campaign_spec_fingerprint:
                raise Stage1TrialAdmissionError("RESULT_CAMPAIGN_FINGERPRINT_MISMATCH")
            if res.complete_manifest_fingerprint != self.complete_manifest_fingerprint:
                raise Stage1TrialAdmissionError("RESULT_MANIFEST_FINGERPRINT_MISMATCH")
            if res.opening_book_identity != self.opening_book_identity:
                raise Stage1TrialAdmissionError("RESULT_BOOK_IDENTITY_MISMATCH")
            if res.opening_book_hash != self.opening_book_hash:
                raise Stage1TrialAdmissionError("RESULT_BOOK_HASH_MISMATCH")

        # Arithmetic and completeness enforcement
        if self.completeness_classification in ("COMPLETE", "MISSING_COST"):
            if self.result_binding is None:
                raise Stage1TrialAdmissionError(
                    "COMPLETE_TRIAL_REQUIRES_RESULT_BINDING"
                )
            if self.start_nav is None or self.end_nav is None:
                raise Stage1TrialAdmissionError("COMPLETE_TRIAL_REQUIRES_NAVS")
            if self.trading_costs is None:
                raise Stage1TrialAdmissionError("COMPLETE_TRIAL_REQUIRES_TRADING_COSTS")
            if (
                self.end_session_index is None
                or self.end_session_index <= self.start_session_index
            ):
                raise Stage1TrialAdmissionError(
                    "COMPLETE_TRIAL_REQUIRES_POSITIVE_INTERVAL"
                )
            if self.result_binding.classification != "complete":
                raise Stage1TrialAdmissionError("UNACCEPTED_RESULT_CLASSIFICATION")
            if self.outcome_classification in ("UNRESOLVED", "NOT_YET_DUE"):
                raise Stage1TrialAdmissionError("UNRESOLVED_CANNOT_BE_COMPLETE")

            start, end = finite_fraction(self.start_nav), finite_fraction(self.end_nav)
            if start <= 0 or end < 0 or finite_fraction(self.trading_costs) < 0:
                raise Stage1TrialAdmissionError("INVALID_ACCOUNT_NAV_OR_COST")

            gain = end - start
            if self.net_investment_gain != exact_decimal(gain):
                raise Stage1TrialAdmissionError("NET_INVESTMENT_GAIN_MISMATCH")
            if self.net_investment_return != ExactRatioV1.from_fraction(gain / start):
                raise Stage1TrialAdmissionError("NET_INVESTMENT_RETURN_MISMATCH")

            if self.completeness_classification == "MISSING_COST":
                if self.economic_gain is not None or self.economic_return is not None:
                    raise Stage1TrialAdmissionError(
                        "MISSING_COST_CANNOT_CLAIM_ECONOMIC_GAIN"
                    )
                if self.operating_cost_projection.amount is not None:
                    raise Stage1TrialAdmissionError(
                        "KNOWN_COSTS_CANNOT_BE_MISSING_COST"
                    )
            else:
                if self.research_binding is None:
                    raise Stage1TrialAdmissionError(
                        "COMPLETE_TRIAL_REQUIRES_RESEARCH_BINDING"
                    )
                if self.operating_cost_projection.amount is None:
                    raise Stage1TrialAdmissionError("UNKNOWN_COST_CANNOT_BE_COMPLETE")
                if self.research_binding.disposition == "propose":
                    cand = self.research_binding.candidate
                    if cand is None:
                        raise Stage1TrialAdmissionError("PROPOSED_CANDIDATE_MISSING")
                    cand_attempts = [
                        a
                        for a in self.research_binding.attempts
                        if a.attempt_id == cand.attempt_id
                    ]
                    if not cand_attempts:
                        raise Stage1TrialAdmissionError(
                            "MISSING_CANDIDATE_ATTEMPT_LIFECYCLE"
                        )
                    terminal = cand_attempts[-1]
                    if terminal.status != "completed":
                        raise Stage1TrialAdmissionError(
                            "CANDIDATE_ATTEMPT_NOT_COMPLETED"
                        )
                    if (
                        terminal.candidate_ref is None
                        or terminal.candidate_ref.id != cand.candidate_id
                        or terminal.candidate_ref.sha256 != cand.record_hash
                    ):
                        raise Stage1TrialAdmissionError(
                            "ATTEMPT_CANDIDATE_REF_MISMATCH"
                        )
                economic = gain - finite_fraction(self.operating_cost_projection.amount)
                if self.economic_gain != exact_decimal(economic):
                    raise Stage1TrialAdmissionError("ECONOMIC_GAIN_MISMATCH")
                if self.economic_return != ExactRatioV1.from_fraction(economic / start):
                    raise Stage1TrialAdmissionError("ECONOMIC_RETURN_MISMATCH")
        else:
            if (
                self.net_investment_gain is not None
                or self.net_investment_return is not None
                or self.economic_gain is not None
                or self.economic_return is not None
            ):
                raise Stage1TrialAdmissionError("INCOMPLETE_TRIAL_CANNOT_CLAIM_GAIN")

        data = self.model_dump(mode="python", exclude={"trial_record_hash"})
        computed = content_hash(data)
        if self.trial_record_hash != computed:
            raise Stage1TrialAdmissionError("TRIAL_RECORD_HASH_MISMATCH")
        return self


# Experiment contract alias
TrialRecordV1 = Stage1DerivedTrialRecordV1


def build_stage1_research_trial_binding(
    *,
    campaign_id: str,
    campaign_spec_fingerprint: str,
    complete_manifest_fingerprint: str,
    run_id: str,
    arm_id: str,
    portfolio_account_id: str,
    checkpoint_id: str,
    research_context: ResearchContext,
    disposition: Literal["propose", "hold", "abstain", "unavailable"],
    candidate: ResearchCandidate | None = None,
    reasoned_absence_code: str | None = None,
    attempts: Sequence[AttemptRecord] = (),
    costs: Sequence[CostReceipt] = (),
    model_replay: ModelReplayRecord | None = None,
    issuer_authority_id: str,
) -> Stage1ResearchTrialBindingV1:
    trial_id = f"{campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"
    replay_data = model_replay.model_dump(mode="python") if model_replay else None
    data: dict[str, Any] = {
        "schema_version": "drift-research-trial-binding/1",
        "campaign_id": campaign_id,
        "campaign_spec_fingerprint": campaign_spec_fingerprint,
        "complete_manifest_fingerprint": complete_manifest_fingerprint,
        "run_id": run_id,
        "arm_id": arm_id,
        "portfolio_account_id": portfolio_account_id,
        "checkpoint_id": checkpoint_id,
        "trial_id": trial_id,
        "research_context": research_context.model_dump(mode="python"),
        "disposition": disposition,
        "candidate": candidate.model_dump(mode="python") if candidate else None,
        "reasoned_absence_code": reasoned_absence_code,
        "attempts": tuple(a.model_dump(mode="python") for a in attempts),
        "costs": tuple(c.model_dump(mode="python") for c in costs),
        "model_replay": replay_data,
        "issuer_authority_id": issuer_authority_id,
    }
    data["binding_hash"] = content_hash(data)
    return Stage1ResearchTrialBindingV1.model_validate(data)


def build_stage1_result_trial_binding(
    *,
    campaign_id: str,
    campaign_spec_fingerprint: str,
    complete_manifest_fingerprint: str,
    run_id: str,
    arm_id: str,
    portfolio_account_id: str,
    checkpoint_id: str,
    opening_book_identity: str,
    opening_book_hash: str,
    m0_invocation: OriginalInvocationBindingV1,
    result_hash: str,
    trace_hash: str,
    final_book_hash: str,
    final_nav: Decimal,
    cash_balance: Decimal,
    cumulative_transaction_costs: Decimal,
    order_count: int,
    fill_count: int,
    classification: Literal["complete", "rejected", "halted", "indeterminate"],
    ledger_ref: OriginalReferenceV1,
) -> Stage1ResultTrialBindingV1:
    trial_id = f"{campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"
    data: dict[str, Any] = {
        "schema_version": "drift-result-trial-binding/1",
        "campaign_id": campaign_id,
        "campaign_spec_fingerprint": campaign_spec_fingerprint,
        "complete_manifest_fingerprint": complete_manifest_fingerprint,
        "run_id": run_id,
        "arm_id": arm_id,
        "portfolio_account_id": portfolio_account_id,
        "checkpoint_id": checkpoint_id,
        "trial_id": trial_id,
        "opening_book_identity": opening_book_identity,
        "opening_book_hash": opening_book_hash,
        "m0_invocation": InvocationBindingPayloadV1(
            invocation_id=m0_invocation.invocation_id,
            m0_run_id=m0_invocation.m0_run_id,
            m0_audit_event_id=m0_invocation.m0_audit_event_id,
        ).model_dump(mode="python"),
        "result_hash": result_hash,
        "trace_hash": trace_hash,
        "final_book_hash": final_book_hash,
        "final_nav": final_nav,
        "cash_balance": cash_balance,
        "cumulative_transaction_costs": cumulative_transaction_costs,
        "order_count": order_count,
        "fill_count": fill_count,
        "classification": classification,
        "ledger_ref": ledger_ref.model_dump(mode="python"),
    }
    data["binding_hash"] = content_hash(data)
    return Stage1ResultTrialBindingV1.model_validate(data)


def build_stage1_derived_trial_record(
    *,
    campaign_id: str,
    campaign_spec_fingerprint: str,
    complete_manifest_fingerprint: str,
    run_id: str,
    arm_id: str,
    portfolio_account_id: str,
    checkpoint_id: str,
    opening_book_identity: str,
    opening_book_hash: str,
    research_binding: Stage1ResearchTrialBindingV1 | None = None,
    result_binding: Stage1ResultTrialBindingV1 | None = None,
    source_inventory_hash: str,
    calendar_hash: str,
    start_session_index: int,
    end_session_index: int | None = None,
    outcome_classification: Literal[
        "COMPLETED",
        "RETAINED",
        "REFUSED",
        "NO_ATTEMPT",
        "FAILED_RESEARCH",
        "UNRESOLVED",
        "NOT_YET_DUE",
    ],
    completeness_classification: Literal[
        "COMPLETE",
        "PENDING_RESULT",
        "PARTIAL_FILL",
        "UNKNOWN_EXECUTION",
        "MISSING_COST",
        "INVALID",
    ],
    costs: Sequence[CostReceipt] = (),
    start_nav: Decimal | None = None,
    end_nav: Decimal | None = None,
    trading_costs: Decimal | None = None,
    reasons: Sequence[str] = (),
) -> Stage1DerivedTrialRecordV1:
    trial_id = f"{campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"
    operating_costs = project_operating_costs(costs)
    net_gain: Decimal | None = None
    net_return: ExactRatioV1 | None = None
    econ_gain: Decimal | None = None
    econ_return: ExactRatioV1 | None = None

    if (
        completeness_classification in ("COMPLETE", "MISSING_COST")
        and start_nav is not None
        and end_nav is not None
    ):
        start = finite_fraction(start_nav)
        gain = finite_fraction(end_nav) - start
        net_gain = exact_decimal(gain)
        net_return = ExactRatioV1.from_fraction(gain / start)
        if (
            completeness_classification == "COMPLETE"
            and operating_costs.amount is not None
        ):
            economic = gain - finite_fraction(operating_costs.amount)
            econ_gain = exact_decimal(economic)
            econ_return = ExactRatioV1.from_fraction(economic / start)

    data: dict[str, Any] = {
        "schema_version": "drift-derived-trial/1",
        "trial_id": trial_id,
        "campaign_id": campaign_id,
        "campaign_spec_fingerprint": campaign_spec_fingerprint,
        "complete_manifest_fingerprint": complete_manifest_fingerprint,
        "run_id": run_id,
        "arm_id": arm_id,
        "portfolio_account_id": portfolio_account_id,
        "checkpoint_id": checkpoint_id,
        "opening_book_identity": opening_book_identity,
        "opening_book_hash": opening_book_hash,
        "research_binding": (
            research_binding.model_dump(mode="python") if research_binding else None
        ),
        "result_binding": (
            result_binding.model_dump(mode="python") if result_binding else None
        ),
        "source_inventory_hash": source_inventory_hash,
        "calendar_hash": calendar_hash,
        "start_session_index": start_session_index,
        "end_session_index": end_session_index,
        "outcome_classification": outcome_classification,
        "completeness_classification": completeness_classification,
        "operating_cost_projection": operating_costs.model_dump(mode="python"),
        "start_nav": start_nav,
        "end_nav": end_nav,
        "trading_costs": trading_costs,
        "net_investment_gain": net_gain,
        "net_investment_return": net_return,
        "economic_gain": econ_gain,
        "economic_return": econ_return,
        "reasons": tuple(reasons),
    }
    data["trial_record_hash"] = content_hash(data)
    return Stage1DerivedTrialRecordV1.model_validate(data)


def verify_stage1_derived_trial_record(
    record: Stage1DerivedTrialRecordV1,
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    source_inventory_hash: str,
    calendar_hash: str,
) -> bool:
    """Check trial structure against a synthetic configuration, not origin."""
    # Revalidate complete record and nested bindings via fresh validation
    try:
        validated = Stage1DerivedTrialRecordV1.model_validate_json(
            record.model_dump_json()
        )
    except Exception as exc:
        raise Stage1TrialAdmissionError(f"RECORD_INTEGRITY_VIOLATION: {exc}") from exc

    verify_stage1_synthetic_br_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    if validated.campaign_id != campaign.campaign_id:
        raise Stage1TrialAdmissionError("WRONG_CAMPAIGN")

    if validated.campaign_spec_fingerprint != campaign.campaign_spec_fingerprint:
        raise Stage1TrialAdmissionError("CAMPAIGN_FINGERPRINT_MISMATCH")

    expected_manifest_fingerprint = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    if validated.complete_manifest_fingerprint != expected_manifest_fingerprint:
        raise Stage1TrialAdmissionError("MANIFEST_FINGERPRINT_MISMATCH")

    # Revalidate nested bindings against expected complete manifest fingerprint
    if validated.research_binding is not None:
        try:
            Stage1ResearchTrialBindingV1.model_validate_json(
                validated.research_binding.model_dump_json()
            )
        except Exception as exc:
            raise Stage1TrialAdmissionError(
                f"RESEARCH_BINDING_INTEGRITY_VIOLATION: {exc}"
            ) from exc
        if (
            validated.research_binding.complete_manifest_fingerprint
            != expected_manifest_fingerprint
        ):
            raise Stage1TrialAdmissionError("RESEARCH_MANIFEST_FINGERPRINT_MISMATCH")

    if validated.result_binding is not None:
        try:
            Stage1ResultTrialBindingV1.model_validate_json(
                validated.result_binding.model_dump_json()
            )
        except Exception as exc:
            raise Stage1TrialAdmissionError(
                f"RESULT_BINDING_INTEGRITY_VIOLATION: {exc}"
            ) from exc
        if (
            validated.result_binding.complete_manifest_fingerprint
            != expected_manifest_fingerprint
        ):
            raise Stage1TrialAdmissionError("RESULT_MANIFEST_FINGERPRINT_MISMATCH")

    # Match exact binding in full manifest
    matching_bindings = [
        b
        for b in bindings
        if b.campaign_id == validated.campaign_id
        and b.run_id == validated.run_id
        and b.arm_id == validated.arm_id
    ]
    if len(matching_bindings) != 1:
        raise Stage1TrialAdmissionError("BINDING_NOT_FOUND_IN_MANIFEST")

    matching = matching_bindings[0]
    if matching.portfolio_account_id != validated.portfolio_account_id:
        raise Stage1TrialAdmissionError("CROSSED_ACCOUNT_OR_WRONG_BINDING")

    # Source & calendar vintage verification
    if validated.source_inventory_hash != source_inventory_hash:
        raise Stage1TrialAdmissionError("INCORRECT_SOURCE_VINTAGE")
    if validated.calendar_hash != calendar_hash:
        raise Stage1TrialAdmissionError("INCORRECT_CALENDAR_HASH")

    # Reconciled interval verification:
    if validated.completeness_classification in ("COMPLETE", "MISSING_COST"):
        if validated.result_binding is None:
            raise Stage1TrialAdmissionError("COMPLETE_WITHOUT_RESULT_BINDING")
        if validated.result_binding.classification != "complete":
            raise Stage1TrialAdmissionError("UNACCEPTED_RESULT_CLASSIFICATION")
        if validated.completeness_classification == "MISSING_COST":
            if (
                validated.economic_gain is not None
                or validated.economic_return is not None
            ):
                raise Stage1TrialAdmissionError("UNKNOWN_COST_CONVERTED_TO_ZERO")
        elif validated.completeness_classification == "COMPLETE":
            if validated.research_binding is None:
                raise Stage1TrialAdmissionError("COMPLETE_WITHOUT_RESEARCH_BINDING")
            if validated.research_binding.disposition == "propose":
                cand = validated.research_binding.candidate
                if cand is None or cand.strategy is None:
                    raise Stage1TrialAdmissionError("PROPOSED_STRATEGY_MISSING")
                cand_attempts = [
                    a
                    for a in validated.research_binding.attempts
                    if a.attempt_id == cand.attempt_id
                ]
                if not cand_attempts:
                    raise Stage1TrialAdmissionError(
                        "MISSING_CANDIDATE_ATTEMPT_LIFECYCLE"
                    )
                terminal = cand_attempts[-1]
                if terminal.status != "completed":
                    raise Stage1TrialAdmissionError("CANDIDATE_ATTEMPT_NOT_COMPLETED")
                if (
                    terminal.candidate_ref is None
                    or terminal.candidate_ref.id != cand.candidate_id
                    or terminal.candidate_ref.sha256 != cand.record_hash
                ):
                    raise Stage1TrialAdmissionError("ATTEMPT_CANDIDATE_REF_MISMATCH")
                if cand.strategy.family_id not in campaign.allowed_strategy_families:
                    raise Stage1TrialAdmissionError("DISALLOWED_STRATEGY_FAMILY")
                arm_spec = next((a for a in arms if a.arm_id == validated.arm_id), None)
                if arm_spec is None:
                    raise Stage1TrialAdmissionError("ARM_NOT_FOUND_IN_MANIFEST")
                if (
                    cand.strategy.family_id not in arm_spec.eligible_strategy_references
                    and cand.strategy.strategy_ref.id
                    not in arm_spec.eligible_strategy_references
                ):
                    raise Stage1TrialAdmissionError("DISALLOWED_ARM_STRATEGY")
            if validated.operating_cost_projection.status == "UNAVAILABLE":
                raise Stage1TrialAdmissionError("UNKNOWN_COST_CONVERTED_TO_ZERO")

    return True
