"""Immutable Pydantic contract types and wire profile for adaptive research.

Defines the 'drift-research/1-draft' profile specifications under ADR 0017
and Decision Packet DP-R1. All models are frozen and forbid extra attributes.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from drift.serialization.canonical import content_hash

# G2 has not qualified a released research wire profile. No silent upgrade.
SUPPORTED_PROFILES = ("drift-research/1-draft",)
type ProfileLiteral = Literal["drift-research/1-draft"]


class ImmutableModel(BaseModel):
    """Base model enforcing immutability and strict schema keys."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=False,
    )


class ArtifactReference(ImmutableModel):
    """Reference wrapper conforming to {id, version, sha256}."""

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v):
            raise ValueError(f"sha256 digest must be 64 lowercase hex characters: {v}")
        return v


class StoredArtifactRef(ImmutableModel):
    """Stored artifact pointer with UUIDv7 id, kind, content_hash, and location."""

    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    location: str = Field(min_length=1)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("stored artifact content_hash must be lowercase SHA-256")
        return value


class Scope(ImmutableModel):
    """Scope identifying experiment, arm, account, and campaign reference."""

    experiment_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    campaign_ref: ArtifactReference


class ContextInput(ImmutableModel):
    """Context input entry with causal availability timestamp."""

    input_ref: ArtifactReference
    role: str = Field(min_length=1)
    available_at: datetime
    availability_basis_ref: ArtifactReference
    transformation_ref: ArtifactReference | None = None


class ResearchContext(ImmutableModel):
    """Point-in-time bounded context presented to research decision-makers."""

    profile: ProfileLiteral
    kind: Literal["context"] = "context"
    context_id: str = Field(min_length=1)
    scope: Scope
    decision_cutoff: datetime
    built_at: datetime
    review_started_at: datetime
    review_reason: str = Field(min_length=1)
    trigger_ref: ArtifactReference | None = None
    clock_policy_ref: ArtifactReference
    method_ref: ArtifactReference
    budget_ref: ArtifactReference
    portfolio_ref: ArtifactReference
    mandate_ref: ArtifactReference
    universe_ref: ArtifactReference
    registry_ref: ArtifactReference
    memory_snapshot_ref: ArtifactReference
    memory_cutoff: datetime
    inputs: tuple[ContextInput, ...] = ()
    excluded_inputs_ref: ArtifactReference | None = None
    feed_state_ref: ArtifactReference | None = None
    feedback_refs: tuple[ArtifactReference, ...] = ()
    source_grade: str = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    current_selection_ref: ArtifactReference | None = None
    record_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def verify_record_hash(self) -> ResearchContext:
        # The wire hash proves only byte consistency; temporal semantics must
        # also be validated before a context can be treated as causal.
        instants = (
            self.decision_cutoff, self.built_at,
            self.review_started_at, self.memory_cutoff,
        )
        if any(ts.tzinfo is None or ts.utcoffset() is None for ts in instants):
            raise ValueError("INDETERMINATE_TIMEZONE: context timestamps need offsets")
        if self.memory_cutoff > self.decision_cutoff:
            raise ValueError("FUTURE_MEMORY_IN_CONTEXT")
        if self.built_at > self.review_started_at:
            raise ValueError("NON_CAUSAL_REVIEW_CLOCK")
        for inp in self.inputs:
            if inp.available_at.tzinfo is None or inp.available_at.utcoffset() is None:
                raise ValueError("INDETERMINATE_TIMEZONE: input availability lacks offset")
            if inp.available_at > self.decision_cutoff:
                raise ValueError("FUTURE_INPUT_IN_CONTEXT")
        calc = compute_record_hash(self)
        if self.record_hash != calc:
            raise ValueError(
                f"record_hash mismatch for ResearchContext: "
                f"expected {calc}, got {self.record_hash}"
            )
        return self


class StrategySelection(ImmutableModel):
    """Selection intent inside a RawChoice or candidate."""

    family_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    parameters: Mapping[str, Any] = Field(default_factory=dict)


class TargetWeight(ImmutableModel):
    """Target weight allocation for a single admitted security."""

    security_id: str = Field(min_length=1)
    weight: str = Field(min_length=1)

    @field_validator("weight", mode="before")
    @classmethod
    def validate_weight_str(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError("invalid: JSON float is not Weight")
        if not isinstance(v, str):
            raise ValueError(f"Weight must be a string: {v!r}")
        try:
            d = Decimal(v)
        except InvalidOperation as e:
            raise ValueError(f"Invalid DecimalText: {v}") from e
        if not d.is_finite():
            raise ValueError(f"Non-finite weight rejected: {v}")
        if d < Decimal("0.0") or d > Decimal("1.0"):
            raise ValueError(f"Target weight must be between 0.0 and 1.0: {v}")
        if "e" in v.lower():
            raise ValueError(f"Scientific notation forbidden in DecimalText: {v}")
        return v


class RawChoice(ImmutableModel):
    """Unvalidated candidate output emitted by model or scripted producer."""

    disposition: Literal["propose", "hold", "abstain", "unavailable"]
    selection: StrategySelection | None = None
    targets: tuple[TargetWeight, ...] = ()
    cash_weight: str | None = None
    evidence_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()

    @field_validator("cash_weight", mode="before")
    @classmethod
    def validate_cash_weight(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, float):
            raise ValueError("invalid: JSON float is not Weight")
        if not isinstance(v, str):
            raise ValueError(f"Cash weight must be a string: {v!r}")
        try:
            d = Decimal(v)
        except InvalidOperation as e:
            raise ValueError(f"Invalid DecimalText: {v}") from e
        if not d.is_finite():
            raise ValueError(f"Non-finite cash weight rejected: {v}")
        if d < Decimal("0.0") or d > Decimal("1.0"):
            raise ValueError(f"Cash weight must be between 0.0 and 1.0: {v}")
        if "e" in v.lower():
            raise ValueError(f"Scientific notation forbidden in DecimalText: {v}")
        return v


class CandidateStrategy(ImmutableModel):
    """Fully qualified and resolved candidate strategy reference."""

    family_id: str = Field(min_length=1)
    strategy_ref: ArtifactReference
    envelope_ref: ArtifactReference
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    parameters_hash: str = Field(min_length=64, max_length=64)
    eligibility_ref: ArtifactReference


class ResearchCandidate(ImmutableModel):
    """Normalized, validated, immutable candidate decision record."""

    profile: ProfileLiteral
    kind: Literal["candidate"] = "candidate"
    candidate_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    scope: Scope
    context_ref: ArtifactReference
    portfolio_ref: ArtifactReference
    mandate_ref: ArtifactReference
    universe_ref: ArtifactReference
    registry_ref: ArtifactReference
    method_ref: ArtifactReference
    producer: str = Field(min_length=1)
    completed_at: datetime
    valid_until: datetime | None = None
    disposition: Literal["propose", "hold", "abstain", "unavailable"]
    strategy: CandidateStrategy | None = None
    targets: tuple[TargetWeight, ...] = ()
    cash_weight: str | None = None
    evidence_refs: tuple[ArtifactReference, ...] = ()
    rationale: str = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()
    model_replay_ref: ArtifactReference | None = None
    cost_receipt_ids: tuple[str, ...] = ()
    record_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def verify_record_hash(self) -> ResearchCandidate:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("INDETERMINATE_TIMEZONE: candidate completion lacks offset")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None or self.valid_until.utcoffset() is None:
                raise ValueError("INDETERMINATE_TIMEZONE: candidate TTL lacks offset")
            if self.valid_until < self.completed_at:
                raise ValueError("INVALID_CANDIDATE_TTL")
        if self.disposition in ("abstain", "unavailable", "hold"):
            if self.targets or self.cash_weight is not None:
                raise ValueError("INCONSISTENT_NON_TRADING_DISPOSITION")
        if self.disposition in ("abstain", "unavailable") and self.strategy is not None:
            raise ValueError("INCONSISTENT_NON_TRADING_DISPOSITION")
        if self.disposition == "propose" and self.strategy is None:
            raise ValueError("PROPOSAL_WITHOUT_STRATEGY")
        if len({t.security_id for t in self.targets}) != len(self.targets):
            raise ValueError("DUPLICATE_TARGET_SECURITY")
        calc = compute_record_hash(self)
        if self.record_hash != calc:
            raise ValueError(
                f"record_hash mismatch for ResearchCandidate: "
                f"expected {calc}, got {self.record_hash}"
            )
        return self


class AttemptRecord(ImmutableModel):
    """Lifecycle tracking record for a research decision attempt."""

    profile: ProfileLiteral
    kind: Literal["attempt"] = "attempt"
    attempt_id: str = Field(min_length=1)
    logical_request_id: str = Field(min_length=1)
    attempt_event_id: str = Field(min_length=1)
    event_index: int = Field(ge=0)
    previous_event_ref: ArtifactReference | None = None
    retry_of: str | None = None
    duplicate_of: str | None = None
    scope: Scope
    context_ref: ArtifactReference
    method_ref: ArtifactReference
    budget_ref: ArtifactReference
    producer: str = Field(min_length=1)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: Literal["started", "completed", "failed", "rejected"]
    validation_ref: ArtifactReference | None = None
    candidate_ref: ArtifactReference | None = None
    model_replay_ref: ArtifactReference | None = None
    cost_receipt_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    failure_artifact_ref: ArtifactReference | None = None
    budget_authorization_ref: ArtifactReference | None = None
    record_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def verify_record_hash(self) -> AttemptRecord:
        calc = compute_record_hash(self)
        if self.record_hash != calc:
            raise ValueError(
                f"record_hash mismatch for AttemptRecord: "
                f"expected {calc}, got {self.record_hash}"
            )
        return self


class UsageEntry(ImmutableModel):
    """Detailed resource usage breakdown."""

    unit: str = Field(min_length=1)
    quantity: int | str | None = None
    unknown_reason: str | None = None


class CostReceipt(ImmutableModel):
    """Authoritative research cost receipt for downstream scientific attribution."""

    profile: ProfileLiteral
    kind: Literal["raw_cost"] = "raw_cost"
    receipt_id: str = Field(min_length=1)
    scope: Scope
    attempt_id: str | None = None
    category: str = Field(min_length=1)
    billing_identity: str = Field(min_length=1)
    raw_evidence_ref: StoredArtifactRef | None = None
    incurred_start: datetime | None = None
    incurred_end: datetime | None = None
    recorded_at: datetime | None = None
    amount: str | None = None
    currency: str | None = None
    amount_basis: Literal["actual", "estimate", "unknown", "verified_zero"]
    unknown_reason: str | None = None
    pricing_ref: ArtifactReference | None = None
    usage: tuple[UsageEntry, ...] = ()
    shared_work_ref: ArtifactReference | None = None
    supersedes_receipt_id: str | None = None
    record_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def verify_record_hash(self) -> CostReceipt:
        calc = compute_record_hash(self)
        if self.record_hash != calc:
            raise ValueError(
                f"record_hash mismatch for CostReceipt: "
                f"expected {calc}, got {self.record_hash}"
            )
        return self


class ModelReplayRecord(ImmutableModel):
    """Model request and response replay provenance record."""

    profile: ProfileLiteral
    kind: Literal["model_replay"] = "model_replay"
    replay_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    scope: Scope
    context_ref: ArtifactReference
    method_ref: ArtifactReference
    adapter_ref: ArtifactReference
    parser_schema_ref: ArtifactReference
    provider_identity: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    resolved_model_revision: str | None = None
    resolution_limitation: str = Field(min_length=1)
    training_horizon_limitation: str = Field(min_length=1)
    request_ref: StoredArtifactRef
    response_ref: StoredArtifactRef | None = None
    request_sent_at: datetime
    response_received_at: datetime | None = None
    parse_completed_at: datetime | None = None
    measured_latency_ms: int | None = Field(default=None, ge=0)
    latency_unknown_reason: str | None = None
    usage_ref: ArtifactReference | None = None
    provider_call_id: str | None = None
    finish_reason: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    original_replay_ref: ArtifactReference | None = None
    retention_limitation: str | None = None
    replay_started_at: datetime | None = None
    replay_completed_at: datetime | None = None
    record_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def verify_record_hash(self) -> ModelReplayRecord:
        calc = compute_record_hash(self)
        if self.record_hash != calc:
            raise ValueError(
                f"record_hash mismatch for ModelReplayRecord: "
                f"expected {calc}, got {self.record_hash}"
            )
        return self


class TrustedInvocationBinding(ImmutableModel):
    """Caller-provided trusted execution and resolution wrapper."""

    attempt_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    validation_id: str = Field(min_length=1)
    policy_ref: ArtifactReference
    raw_output_ref: ArtifactReference
    producer: str = Field(min_length=1)
    completed_at: datetime
    checked_at: datetime
    valid_until: datetime | None = None
    model_replay_ref: ArtifactReference | None = None
    cost_receipt_ids: tuple[str, ...] = ()


def compute_record_hash(model: BaseModel | Mapping[str, Any]) -> str:
    """Compute the canonical SHA-256 hash of all fields excluding 'record_hash'."""
    if isinstance(model, BaseModel):
        data = model.model_dump(mode="python")
    else:
        data = dict(model)
    data.pop("record_hash", None)
    return content_hash(data)
