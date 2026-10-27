"""Explicit local-synthetic G2 composition, never an external issuer credential.

All original K1, M0, account and financial identities keep their own versions.
These records join them under one configured, trusted, installed host. Numerical
mandates are mandatory inputs, not production defaults. Operational observation
instants are distinct from synthetic economic cutoffs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.domain.evaluator_clock import EvaluationSessionV1
from drift.domain.evaluator_strategy import StrategyDecisionIntentV1
from drift.evaluator.session_observer import (
    ExecutionAuthorizationV1,
    SessionObservationV1,
)
from drift.experiments.stage1_campaign_config import ArmSpecV1, CampaignSpecV1
from drift.intelligence.contracts import (
    ArtifactReference,
    AttemptRecord,
    CostReceipt,
    ResearchContext,
    TrustedInvocationBinding,
)
from drift.intelligence.learning import LearningSnapshot, TrialFeedbackRecord
from drift.intelligence.validation import ValidationResult
from drift.ledger.stage1_synthetic_account_receipts import AccountAllocationFieldsV1
from drift.serialization.canonical import canonical_json, content_hash

PROFILE: Literal["drift-local-synthetic-g2/1"] = "drift-local-synthetic-g2/1"
ENTITY = "stage1_controlled_campaign"
EVENT_PREFIX = "stage1.controlled."
MAX_RECORD_BYTES = 1_048_576
MAX_CONTEXT_BYTES = 33_554_432
Family = Literal["B3", "B4", "B5"]


def detached[M: BaseModel](cls: type[M], value: M) -> M:
    """Revalidate and detach concrete JSON leaves, including frozen model copies."""
    # Strict dataclasses require their concrete instance in Python mode, but
    # JSON mode correctly reconstructs them from canonical primitive leaves.
    return cls.model_validate_json(canonical_json(value))


def finite_fraction(value: Decimal) -> Fraction:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("CONTROLLED_FINITE_DECIMAL_REQUIRED")
    return Fraction(value)


class OriginalReferenceV1(FrozenModel):
    event_id: UUID7
    event_hash: SHA256Hash


class OriginalAccountDescriptorV1(FrozenModel):
    allocation_id: UUID7
    allocation: OriginalReferenceV1
    witness: OriginalReferenceV1
    fields: AccountAllocationFieldsV1
    original_book_hash: SHA256Hash


class RetainedCanonicalPayloadV1(FrozenModel):
    """Lossless bounded canonical bytes; hashes are not origin authentication."""

    encoding: Literal["zlib-base64"] = "zlib-base64"
    size: int = Field(strict=True, gt=0, le=MAX_CONTEXT_BYTES)
    sha256: SHA256Hash
    data: str = Field(strict=True, min_length=1, max_length=MAX_RECORD_BYTES)

    @classmethod
    def retain(cls, value: BaseModel) -> Self:
        original = canonical_json(value)
        if len(original) > MAX_CONTEXT_BYTES:
            raise ValueError("CONTROLLED_PAYLOAD_TOO_LARGE")
        return cls(
            size=len(original),
            sha256=hashlib.sha256(original).hexdigest(),
            data=base64.b64encode(zlib.compress(original, 9)).decode("ascii"),
        )

    def original_bytes(self) -> bytes:
        try:
            encoded = base64.b64decode(self.data, validate=True)
            if base64.b64encode(encoded).decode("ascii") != self.data:
                raise ValueError("CONTROLLED_PAYLOAD_NONCANONICAL_BASE64")
            decoder = zlib.decompressobj()
            original = decoder.decompress(encoded, self.size + 1)
        except (binascii.Error, zlib.error) as error:
            raise ValueError("CONTROLLED_PAYLOAD_ENCODING_INVALID") from error
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(original) != self.size
            or hashlib.sha256(original).hexdigest() != self.sha256
        ):
            raise ValueError("CONTROLLED_PAYLOAD_SIZE_OR_HASH_INVALID")
        return original

    def parse[M: BaseModel](self, cls: type[M]) -> M:
        original = self.original_bytes()
        result = cls.model_validate_json(original)
        if canonical_json(result) != original:
            raise ValueError("CONTROLLED_PAYLOAD_NOT_CANONICAL")
        return result


class SecurityMandateV1(FrozenModel):
    security_id: UUID7
    asset_class: NonBlankStr
    maximum_fraction: Decimal

    @model_validator(mode="after")
    def validate_fraction(self) -> Self:
        if not 0 <= finite_fraction(self.maximum_fraction) <= 1:
            raise ValueError("CONTROLLED_SECURITY_CAP_OUT_OF_RANGE")
        return self


class ClassMandateV1(FrozenModel):
    asset_class: NonBlankStr
    maximum_fraction: Decimal

    @model_validator(mode="after")
    def validate_fraction(self) -> Self:
        if not 0 <= finite_fraction(self.maximum_fraction) <= 1:
            raise ValueError("CONTROLLED_CLASS_CAP_OUT_OF_RANGE")
        return self


class SyntheticMandateV1(FrozenModel):
    """Explicit fixture inputs. No inferred numeric Balanced or live defaults."""

    policy_id: NonBlankStr
    revision: NonBlankStr
    securities: tuple[SecurityMandateV1, ...]
    classes: tuple[ClassMandateV1, ...]
    maximum_gross_fraction: Decimal
    maximum_turnover_fraction: Decimal
    maximum_price_age_sessions: int = Field(strict=True, ge=0, le=0)
    paused: bool = Field(strict=True)
    execution_knowledge: Literal["RESOLVED", "UNKNOWN", "PARTIAL"]
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        ids = tuple(item.security_id.bytes for item in self.securities)
        names = tuple(item.asset_class for item in self.classes)
        if not ids or ids != tuple(sorted(set(ids))):
            raise ValueError("CONTROLLED_POLICY_SECURITY_SET")
        if not names or names != tuple(sorted(set(names))):
            raise ValueError("CONTROLLED_POLICY_CLASS_SET")
        if set(names) != {item.asset_class for item in self.securities}:
            raise ValueError("CONTROLLED_POLICY_CLASS_COVERAGE")
        if not 0 <= finite_fraction(self.maximum_gross_fraction) <= 1:
            raise ValueError("CONTROLLED_GROSS_CAP_OUT_OF_RANGE")
        if not 0 <= finite_fraction(self.maximum_turnover_fraction) <= 2:
            raise ValueError("CONTROLLED_TURNOVER_CAP_OUT_OF_RANGE")
        return self

    @property
    def policy_hash(self) -> str:
        return content_hash(self)


class ControlledResearchFixtureV1(FrozenModel):
    """Frozen offline producer inputs, not a fitted R rule or a live AI model."""

    mode: Literal["scripted_fixture", "conventional_fixture"]
    disposition: Literal["propose", "hold", "abstain", "unavailable"]
    selected_family: Family | None
    candidate_families: tuple[Family, ...]
    scores: Mapping[str, Decimal]
    cost_amount: Decimal
    should_timeout: bool = Field(default=False, strict=True)
    malformed_output: str | None = None

    @model_validator(mode="after")
    def validate_fixture(self) -> Self:
        if finite_fraction(self.cost_amount) < 0:
            raise ValueError("CONTROLLED_NEGATIVE_COST")
        for score in self.scores.values():
            finite_fraction(score)
        if self.mode == "scripted_fixture":
            if self.candidate_families or self.scores:
                raise ValueError("CONTROLLED_SCRIPTED_COMPARATOR_FIELDS")
            if (self.disposition == "propose") != (self.selected_family is not None):
                raise ValueError("CONTROLLED_SCRIPTED_FAMILY_FIELDS")
        else:
            if (
                self.selected_family is not None
                or self.disposition != "propose"
                or not self.candidate_families
                or len(set(self.candidate_families)) != len(self.candidate_families)
                or set(self.scores) != set(self.candidate_families)
                or self.should_timeout
                or self.malformed_output is not None
                or self.cost_amount != 0
            ):
                raise ValueError("CONTROLLED_COMPARATOR_FIXTURE_FIELDS")
        return self


class ControlledCheckpointV1(FrozenModel):
    checkpoint_id: NonBlankStr
    session_index: int = Field(strict=True, ge=0)
    decision_cutoff: UTCDateTime
    not_before: UTCDateTime
    expires_at: UTCDateTime
    research_budget_usd: Decimal
    fixture: ControlledResearchFixtureV1
    revoked_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if self.not_before > self.expires_at:
            raise ValueError("CONTROLLED_GRANT_NEGATIVE_INTERVAL")
        if finite_fraction(self.research_budget_usd) < 0:
            raise ValueError("CONTROLLED_NEGATIVE_BUDGET")
        if self.revoked_at is not None and self.revoked_at < self.not_before:
            raise ValueError("CONTROLLED_REVOCATION_BEFORE_ISSUANCE_WINDOW")
        return self


class ControlledCampaignPlanV1(FrozenModel):
    profile: Literal["drift-local-synthetic-g2/1"] = PROFILE
    original_account: OriginalAccountDescriptorV1
    provenance_hash: SHA256Hash
    input_bundle_hash: SHA256Hash
    cost_model_hash: SHA256Hash
    protocol_hash: SHA256Hash
    admission_hash: SHA256Hash
    evaluator_evidence_hash: SHA256Hash
    source_inventory_hash: SHA256Hash
    securities: tuple[UUID7, ...]
    sessions: tuple[EvaluationSessionV1, ...]
    initial_decision_index: int = Field(strict=True, ge=0)
    coverage: Literal["DEVELOPMENT", "STAGE1_253_126_MONTHLY"]
    context_template: ResearchContext
    mandate: SyntheticMandateV1
    checkpoints: tuple[ControlledCheckpointV1, ...]
    clock_policy: ArtifactReference
    initial_family: Literal["B3"] = "B3"

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        fields = self.original_account.fields
        if (
            fields.currency != "USD"
            or finite_fraction(Decimal(fields.initial_cash)) != 10000
            or self.context_template.source_grade != "synthetic_fixture"
            or self.context_template.scope.experiment_id != fields.campaign_id
            or self.context_template.scope.arm_id != fields.arm_id
            or self.context_template.scope.account_id != fields.portfolio_account_id
            or self.context_template.scope.campaign_ref.id != fields.campaign_id
            or self.context_template.scope.campaign_ref.sha256
            != fields.campaign_fingerprint
        ):
            raise ValueError("CONTROLLED_PLAN_ACCOUNT_CONTEXT_SCOPE")
        ids = tuple(identifier.bytes for identifier in self.securities)
        if not ids or ids != tuple(sorted(set(ids))):
            raise ValueError("CONTROLLED_PLAN_SECURITY_SET")
        if self.securities != tuple(
            item.security_id for item in self.mandate.securities
        ):
            raise ValueError("CONTROLLED_PLAN_MANDATE_UNIVERSE")
        if self.initial_decision_index >= len(self.sessions) - 1:
            raise ValueError("CONTROLLED_PLAN_INITIAL_SESSION")
        if any(
            left.closed_at >= right.opened_at
            for left, right in zip(self.sessions, self.sessions[1:], strict=False)
        ):
            raise ValueError("CONTROLLED_PLAN_SESSION_CHRONOLOGY")
        indices = tuple(item.session_index for item in self.checkpoints)
        names = tuple(item.checkpoint_id for item in self.checkpoints)
        if (
            not indices
            or indices != tuple(sorted(set(indices)))
            or len(set(names)) != len(names)
        ):
            raise ValueError("CONTROLLED_PLAN_CHECKPOINT_SET")
        for item in self.checkpoints:
            if (
                not self.initial_decision_index
                < item.session_index
                < len(self.sessions) - 1
                or item.decision_cutoff != self.sessions[item.session_index].closed_at
            ):
                raise ValueError("CONTROLLED_PLAN_CHECKPOINT_SESSION")
        if self.coverage == "STAGE1_253_126_MONTHLY":
            if self.initial_decision_index != 378:
                raise ValueError("CONTROLLED_STAGE1_PREPARATION_253_126")
            start = self.sessions[
                self.initial_decision_index + 1
            ].session_key.local_date
            for item in self.checkpoints:
                day = self.sessions[item.session_index].session_key.local_date
                following = self.sessions[item.session_index + 1].session_key.local_date
                if (
                    item.session_index < self.initial_decision_index + 21
                    or (day.year, day.month) <= (start.year, start.month)
                    or (day.year, day.month) == (following.year, following.month)
                ):
                    raise ValueError("CONTROLLED_STAGE1_MONTHLY_CHECKPOINT")
            expected_indices = tuple(
                index
                for index in range(
                    self.initial_decision_index + 21, len(self.sessions) - 1
                )
                if (
                    self.sessions[index].session_key.local_date.year,
                    self.sessions[index].session_key.local_date.month,
                )
                > (start.year, start.month)
                and (
                    self.sessions[index].session_key.local_date.year,
                    self.sessions[index].session_key.local_date.month,
                )
                != (
                    self.sessions[index + 1].session_key.local_date.year,
                    self.sessions[index + 1].session_key.local_date.month,
                )
            )
            if indices != expected_indices:
                raise ValueError("CONTROLLED_STAGE1_MISSING_MONTHLY_OPPORTUNITY")
        return self

    @property
    def plan_hash(self) -> str:
        return content_hash(self)

    def trial_id(self, checkpoint_id: str) -> str:
        f = self.original_account.fields
        return f"{f.campaign_id}:{f.run_id}:{f.arm_id}:{checkpoint_id}"


def verify_declared_stage1_plan(
    plan: ControlledCampaignPlanV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
) -> None:
    """Couple the full-window profile to its original E1 study declaration.

    Development fixtures do not assert Stage 1 window conformance. Full-window
    callers cannot substitute a different window, mandate or comparator mode
    while retaining an otherwise valid E1 scope fingerprint. This is a local
    synthetic mapping, not qualified calendar or external policy evidence.
    """
    if plan.coverage != "STAGE1_253_126_MONTHLY":
        return
    selected = [a for a in arms if a.arm_id == plan.original_account.fields.arm_id]
    if len(selected) != 1:
        raise ValueError("CONTROLLED_STAGE1_ARM_NOT_DECLARED")
    arm = selected[0]
    scoring_count = len(plan.sessions) - plan.initial_decision_index - 1
    if (
        campaign.data_window.start_date
        != plan.sessions[0].session_key.local_date.isoformat()
        or campaign.data_window.end_date
        != plan.sessions[-1].session_key.local_date.isoformat()
        or campaign.warmup_window.sessions_count != 253
        or campaign.observation_window.sessions_count != 126
        or campaign.scoring_window.start_session != "SC-001"
        or campaign.scoring_window.end_session != f"SC-{scoring_count:03d}"
        or not campaign.scoring_window.fresh_accounts
        or campaign.decision_schedule.frequency != "MONTHLY"
        or campaign.decision_schedule.alignment != "LAST_COMPLETED_SESSION"
        or campaign.decision_schedule.execution_timing != "NEXT_OPEN"
    ):
        raise ValueError("CONTROLLED_STAGE1_WINDOW_NOT_DECLARED_E1")
    if (
        plan.mandate.policy_id != campaign.portfolio_mandate_reference
        or plan.mandate.policy_id != arm.mandate_reference
        or arm.initial_strategy_reference != plan.initial_family
    ):
        raise ValueError("CONTROLLED_STAGE1_POLICY_NOT_DECLARED_E1")
    expected_mode = {
        "ADAPTIVE_AI": "scripted_fixture",
        "DETERMINISTIC_COMPARATOR": "conventional_fixture",
    }.get(arm.selector_type)
    if expected_mode is None or any(
        point.fixture.mode != expected_mode for point in plan.checkpoints
    ):
        raise ValueError("CONTROLLED_STAGE1_SELECTOR_NOT_DECLARED_E1")


class ManifestRecordV1(FrozenModel):
    kind: Literal["manifest"] = "manifest"
    plan: ControlledCampaignPlanV1
    scheduler_witness_observed_at: UTCDateTime
    original_witness: OriginalReferenceV1
    m0_run_id: UUID7
    m0_audit_event_id: UUID7


class ObservationRecordV1(FrozenModel):
    kind: Literal["observation"] = "observation"
    observation: SessionObservationV1


class InputWitnessRecordV1(FrozenModel):
    kind: Literal["input_witness"] = "input_witness"
    checkpoint_id: NonBlankStr
    observation: OriginalReferenceV1
    context_kind: Literal["realized", "reconstructed"]
    decision_context: RetainedCanonicalPayloadV1
    research_context: ResearchContext
    learning: LearningSnapshot
    feedback: tuple[TrialFeedbackRecord, ...]
    original_available_at: UTCDateTime


class GrantRecordV1(FrozenModel):
    kind: Literal["grant"] = "grant"
    checkpoint_id: NonBlankStr
    input_witness: OriginalReferenceV1
    logical_request_id: NonBlankStr
    attempt_id: NonBlankStr
    not_before: UTCDateTime
    expires_at: UTCDateTime
    budget_usd: Decimal


class RevocationRecordV1(FrozenModel):
    kind: Literal["revocation"] = "revocation"
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1
    effective_at: UTCDateTime
    reason: NonBlankStr


class AttemptRecordV1(FrozenModel):
    kind: Literal["attempt"] = "attempt"
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1
    original: AttemptRecord


class CostRecordV1(FrozenModel):
    kind: Literal["cost"] = "cost"
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1
    original: CostReceipt


class ValidationRecordV1(FrozenModel):
    kind: Literal["validation"] = "validation"
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1
    raw_output_utf8: str = Field(strict=True, max_length=MAX_RECORD_BYTES)
    binding: TrustedInvocationBinding
    original: ValidationResult


class ResearchOutputRecordV1(FrozenModel):
    kind: Literal["research_output"] = "research_output"
    completed_observed_at: UTCDateTime
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1
    output_utf8: str = Field(strict=True, max_length=MAX_RECORD_BYTES)


class NoAttemptRecordV1(FrozenModel):
    kind: Literal["no_attempt"] = "no_attempt"
    checkpoint_id: NonBlankStr
    grant: OriginalReferenceV1 | None
    reason: Literal[
        "NOT_YET_VALID", "EXPIRED", "REVOKED", "INPUT_UNAVAILABLE", "BUDGET_UNAVAILABLE"
    ]


class DecisionRecordV1(FrozenModel):
    kind: Literal["decision"] = "decision"
    session_index: int = Field(strict=True, ge=0)
    checkpoint_id: NonBlankStr | None
    observation: OriginalReferenceV1
    context_kind: Literal["realized", "reconstructed"]
    decision_context: RetainedCanonicalPayloadV1
    previous_family: Family
    proposed_family: Family
    staged_family: Family
    candidate_hash: SHA256Hash | None
    intent: StrategyDecisionIntentV1
    disposition: Literal["INSTALLED", "SELECTED", "RETAINED", "REFUSED", "UNAVAILABLE"]
    reason: NonBlankStr


class ExecutionRecordV1(FrozenModel):
    kind: Literal["execution"] = "execution"
    preview: RetainedCanonicalPayloadV1
    authorization: ExecutionAuthorizationV1
    decision: OriginalReferenceV1


class ContainmentRecordV1(FrozenModel):
    kind: Literal["containment"] = "containment"
    observation: OriginalReferenceV1
    reason: NonBlankStr


class TerminalRecordV1(FrozenModel):
    kind: Literal["terminal"] = "terminal"
    m0_run_id: UUID7
    m0_audit_event_id: UUID7
    m0_status: Literal["completed", "failed"]
    result_association: OriginalReferenceV1 | None
    classification: Literal["complete", "rejected", "indeterminate"] | None


ControlledRecord = Annotated[
    ManifestRecordV1
    | ObservationRecordV1
    | InputWitnessRecordV1
    | GrantRecordV1
    | RevocationRecordV1
    | AttemptRecordV1
    | CostRecordV1
    | ValidationRecordV1
    | ResearchOutputRecordV1
    | NoAttemptRecordV1
    | DecisionRecordV1
    | ExecutionRecordV1
    | ContainmentRecordV1
    | TerminalRecordV1,
    Field(discriminator="kind"),
]
RECORD_ADAPTER: TypeAdapter[ControlledRecord] = TypeAdapter(ControlledRecord)


class ControlledEnvelopeV1(FrozenModel):
    profile: Literal["drift-local-synthetic-g2/1"] = PROFILE
    issuer_instance_id: UUID7
    allocation_id: UUID7
    campaign_id: NonBlankStr
    run_id: NonBlankStr
    arm_id: NonBlankStr
    account_id: NonBlankStr
    manifest_hash: SHA256Hash
    record: ControlledRecord

    @classmethod
    def create(
        cls, *, issuer: UUID7, plan: ControlledCampaignPlanV1, record: ControlledRecord
    ) -> Self:
        f = plan.original_account.fields
        return cls(
            issuer_instance_id=issuer,
            allocation_id=plan.original_account.allocation_id,
            campaign_id=f.campaign_id,
            run_id=f.run_id,
            arm_id=f.arm_id,
            account_id=f.portfolio_account_id,
            manifest_hash=plan.plan_hash,
            record=record,
        )


def account_descriptor_payload(
    descriptor: OriginalAccountDescriptorV1,
) -> dict[str, object]:
    """Use the existing producer's exact original allocation fields."""
    return asdict(descriptor.fields)


def exact_decimal(value: Fraction) -> Decimal:
    """Represent a terminating rational exactly, independent of Decimal context."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("CONTROLLED_NONTERMINATING_DECIMAL")
    scale = max(twos, fives)
    numerator = value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
    return Decimal(
        (int(numerator < 0), tuple(int(c) for c in str(abs(numerator))), -scale)
    )


def portfolio_mandate_reason(
    *,
    mandate: SyntheticMandateV1,
    quantities: Mapping[UUID7, int],
    prices: Mapping[UUID7, Decimal],
    cash: Decimal,
    pending_claims: Decimal,
) -> str | None:
    """Exact whole-book mandatory caps at the actual supplied valuation prices."""
    cash_f, pending_f = finite_fraction(cash), finite_fraction(pending_claims)
    if (
        cash_f < 0
        or pending_f < 0
        or any(type(q) is not int or q < 0 for q in quantities.values())
    ):
        return "SHORT_OR_LEVERAGED_BOOK"
    policies = {entry.security_id: entry for entry in mandate.securities}
    if any(security not in policies for security in quantities):
        return "FOREIGN_SECURITY"
    values: dict[UUID7, Fraction] = {}
    for security, quantity in quantities.items():
        if not quantity:
            continue
        if security not in prices:
            return "PRICE_UNAVAILABLE"
        price = finite_fraction(prices[security])
        if price <= 0:
            return "PRICE_INVALID"
        values[security] = quantity * price
    gross = sum(values.values(), Fraction(0))
    nav = cash_f + pending_f + gross
    if nav <= 0:
        return "NONPOSITIVE_NAV"
    if gross > nav * finite_fraction(mandate.maximum_gross_fraction):
        return "GROSS_CAP"
    class_values: dict[str, Fraction] = {}
    for security, value in values.items():
        rule = policies[security]
        if value > nav * finite_fraction(rule.maximum_fraction):
            return "SECURITY_CAP"
        class_values[rule.asset_class] = (
            class_values.get(rule.asset_class, Fraction(0)) + value
        )
    for class_rule in mandate.classes:
        if class_values.get(
            class_rule.asset_class, Fraction(0)
        ) > nav * finite_fraction(class_rule.maximum_fraction):
            return "CLASS_CAP"
    return None
