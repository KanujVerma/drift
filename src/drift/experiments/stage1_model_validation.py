"""Stage 1 model-binding metadata and unavailable 2024 validation.

Binding hashes provide structural consistency, not authentication of weights,
training cutoff, provider execution, or original receipts. Validation remains
unavailable until the original model and account evidence can be authenticated.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import (
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.experiments.stage1_economic_costs import create_stage1_cost_model
from drift.experiments.stage1_study_artifacts import CalibrationPairV1
from drift.experiments.stage1_study_freeze import (
    StudyDateWindowV1,
    StudyModelPolicyV1,
)
from drift.serialization.canonical import content_hash

VALIDATION_DEFAULT_SESSIONS: int = 252  # 2024 trading days
DECISION_INTERVAL_SESSIONS: int = 21  # Monthly decision cadence
LOOKBACK_SESSION_INTERVALS: int = 126  # 126 return intervals = 127 marks


class ImmutableModelBindingV1(FrozenModel):
    """Self-declared, hash-consistent metadata for candidate Model B."""

    schema_version: Literal["drift-stage1-model-binding/1"] = (
        "drift-stage1-model-binding/1"
    )
    binding_id: NonBlankStr
    provider: NonBlankStr
    deployment_version: NonBlankStr
    prompt_text: NonBlankStr
    context_policy_name: NonBlankStr = "stage1-strict-causal-v1"
    tools_policy_name: NonBlankStr = "stage1-portfolio-read-only-v1"
    decoding_params: dict[str, Any] = Field(
        default_factory=lambda: {"temperature": 0.0, "top_p": 1.0}
    )
    seed: int = Field(ge=0, strict=True)
    token_ceiling: int = Field(ge=1, strict=True, default=4096)
    monetary_ceiling: Decimal = Decimal("10.00")
    allowed_families: tuple[Literal["B3", "B4", "B5", "ABSTAIN"], ...] = (
        "B3",
        "B4",
        "B5",
        "ABSTAIN",
    )
    transport_kind: Literal["DIRECT_API", "REPLAY_STORE", "FAKE_TRANSPORT"] = (
        "DIRECT_API"
    )
    known_training_cutoff: date = date(2023, 12, 31)
    binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.transport_kind == "FAKE_TRANSPORT":
            raise ValueError(
                "FAKE_TRANSPORT_NOT_AUTHENTIC_AI: FakeTransport cannot be "
                "presented as actual AI inference"
            )
        if (
            "latest" in self.deployment_version.lower()
            or "preview" in self.deployment_version.lower()
            or "unpinned" in self.deployment_version.lower()
        ):
            raise ValueError(
                "VALIDATION_UNPINNED_MODEL_REVISION: model deployment version "
                "must be strictly pinned to an immutable revision"
            )
        if self.known_training_cutoff >= date(2024, 1, 1):
            raise ValueError(
                "MODEL_TRAINED_ON_VALIDATION_DATA: model training cutoff "
                f"{self.known_training_cutoff} overlaps validation window "
                "(>= 2024-01-01)"
            )
        body = self.model_dump(mode="python", exclude={"binding_hash"})
        computed = content_hash(body)
        if self.binding_hash != computed:
            raise ValueError(
                f"MODEL_BINDING_HASH_MISMATCH: expected {computed}, "
                f"got {self.binding_hash}"
            )
        return self


def create_immutable_model_binding(
    *,
    binding_id: str,
    provider: str,
    deployment_version: str,
    prompt_text: str,
    context_policy_name: str = "stage1-strict-causal-v1",
    tools_policy_name: str = "stage1-portfolio-read-only-v1",
    decoding_params: dict[str, Any] | None = None,
    seed: int = 42,
    token_ceiling: int = 4096,
    monetary_ceiling: Decimal = Decimal("10.00"),
    transport_kind: Literal[
        "DIRECT_API", "REPLAY_STORE", "FAKE_TRANSPORT"
    ] = "DIRECT_API",
    known_training_cutoff: date = date(2023, 12, 31),
) -> ImmutableModelBindingV1:
    decoding = decoding_params or {"temperature": 0.0, "top_p": 1.0}
    allowed: tuple[Literal["B3", "B4", "B5", "ABSTAIN"], ...] = (
        "B3",
        "B4",
        "B5",
        "ABSTAIN",
    )
    body: dict[str, Any] = {
        "schema_version": "drift-stage1-model-binding/1",
        "binding_id": binding_id,
        "provider": provider,
        "deployment_version": deployment_version,
        "prompt_text": prompt_text,
        "context_policy_name": context_policy_name,
        "tools_policy_name": tools_policy_name,
        "decoding_params": decoding,
        "seed": seed,
        "token_ceiling": token_ceiling,
        "monetary_ceiling": monetary_ceiling,
        "allowed_families": allowed,
        "transport_kind": transport_kind,
        "known_training_cutoff": known_training_cutoff,
    }
    h = content_hash(body)
    return ImmutableModelBindingV1(
        schema_version="drift-stage1-model-binding/1",
        binding_id=binding_id,
        provider=provider,
        deployment_version=deployment_version,
        prompt_text=prompt_text,
        context_policy_name=context_policy_name,
        tools_policy_name=tools_policy_name,
        decoding_params=decoding,
        seed=seed,
        token_ceiling=token_ceiling,
        monetary_ceiling=monetary_ceiling,
        allowed_families=allowed,
        transport_kind=transport_kind,
        known_training_cutoff=known_training_cutoff,
        binding_hash=h,
    )


def create_study_model_policy(
    binding: ImmutableModelBindingV1,
) -> StudyModelPolicyV1:
    """Project self-declared metadata without authenticating the original model."""
    prompt_hash = content_hash({"prompt": binding.prompt_text})
    tools_hash = content_hash({"tools": binding.tools_policy_name})
    context_hash = content_hash({"context": binding.context_policy_name})
    feedback_hash = content_hash({"feedback": "zero_in_session_feedback"})
    decoding_hash = content_hash({"decoding": binding.decoding_params})
    model_record_hash = binding.binding_hash

    return StudyModelPolicyV1(
        provider=binding.provider,
        immutable_model_revision=binding.deployment_version,
        model_record_hash=model_record_hash,
        prompt_hash=prompt_hash,
        tools_policy_hash=tools_hash,
        context_policy_hash=context_hash,
        feedback_policy_hash=feedback_hash,
        decoding_policy_hash=decoding_hash,
        seed=binding.seed,
        known_training_cutoff=binding.known_training_cutoff,
    )


class ValidationRunConfigV1(FrozenModel):
    """Configuration for executing 2024 validation."""

    model_binding: ImmutableModelBindingV1
    comparator_pair: CalibrationPairV1
    validation_window: StudyDateWindowV1 = Field(
        default_factory=lambda: StudyDateWindowV1(
            start=date(2024, 1, 1), end=date(2024, 12, 31)
        )
    )
    session_count: int | None = None
    initial_capital: Decimal = Decimal("10000.00")
    cost_model: EvaluationCostModelV1 = Field(default_factory=create_stage1_cost_model)
    authority_id: NonBlankStr = "trusted-validation-authority"
    ledger_dir: Path | None = None


class ValidationRunResultV1(FrozenModel):
    """Immutable outcome of 2024 validation execution with exposure record."""

    schema_version: Literal["drift-stage1-validation-run/1"] = (
        "drift-stage1-validation-run/1"
    )
    run_id: NonBlankStr
    status: Literal["COMPLETED", "FAILED"]
    completed_at: UTCDateTime
    model_binding_hash: SHA256Hash
    comparator_pair: CalibrationPairV1
    validation_window: StudyDateWindowV1
    evaluated_sessions_count: int = Field(ge=0, strict=True)
    b_terminal_nav: Decimal
    r_terminal_nav: Decimal
    b_net_return: Decimal
    r_net_return: Decimal
    b_receipt_refs: tuple[dict[str, Any], ...]
    r_receipt_refs: tuple[dict[str, Any], ...]
    model_replay_refs: tuple[dict[str, Any], ...]
    exposure_record: tuple[str, ...]
    ledger_paths: dict[str, str] = Field(default_factory=dict)
    validation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"validation_hash"})
        computed = content_hash(body)
        if self.validation_hash != computed:
            raise ValueError(
                f"VALIDATION_HASH_MISMATCH: expected {computed}, "
                f"got {self.validation_hash}"
            )
        return self


def execute_2024_validation(
    config: ValidationRunConfigV1,
    *,
    artifact_store: dict[str, Any] | None = None,
    receipt_store: dict[str, Any] | None = None,
    daily_b_returns: Sequence[Decimal] | None = None,
    daily_r_returns: Sequence[Decimal] | None = None,
) -> ValidationRunResultV1:
    """Refuse until original model and account evidence can be authenticated."""
    win = config.validation_window
    if win.start < date(2024, 1, 1) or win.end > date(2024, 12, 31):
        raise ValueError(
            f"INVALID_VALIDATION_WINDOW: must be strictly within 2024, "
            f"got {win.start} to {win.end}"
        )
    session_count = (
        config.session_count
        if config.session_count is not None
        else VALIDATION_DEFAULT_SESSIONS
    )
    if session_count < 1:
        raise ValueError(f"INVALID_SESSION_COUNT: must be >= 1, got {session_count}")
    raise ValueError("VALIDATION_ORIGINAL_EVIDENCE_UNAVAILABLE")
