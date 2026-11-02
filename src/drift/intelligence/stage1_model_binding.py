"""Stage 1 immutable experimental model binding and runtime authorization.

Enforces:
- Specific immutable model revisions and prompts, rejecting 'latest'.
- Host-enforced seed policy and response replay contracts.
- Explicit study runtime authorizations with spending limits and forbidden capabilities.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash
from drift.serialization.canonical import canonical_json, content_hash


class Stage1ModelBindingV1(FrozenModel):
    schema_version: Literal["drift-stage1-model-binding/1"] = (
        "drift-stage1-model-binding/1"
    )
    provider: NonBlankStr
    immutable_model_revision: NonBlankStr
    provider_evidence_hash: SHA256Hash
    model_record_hash: SHA256Hash
    prompt_bytes_hash: SHA256Hash
    tools_policy_hash: SHA256Hash
    context_policy_hash: SHA256Hash
    family_registry_hash: SHA256Hash
    reflection_policy_hash: SHA256Hash
    decoding_parameters: dict[str, Any]
    seed_policy: Literal["HOST_ENFORCED_SEEDED_OR_RECORDED_REPLAY"] = (
        "HOST_ENFORCED_SEEDED_OR_RECORDED_REPLAY"
    )
    seed: int = Field(ge=0)
    timeout_seconds: int = Field(gt=0)
    max_retries: Literal[1] = 1
    captured_response_replay: Literal["REPRODUCIBILITY_ONLY"] = "REPRODUCIBILITY_ONLY"
    binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if "latest" in self.immutable_model_revision.lower():
            raise ValueError("MODEL_REVISION_CANNOT_BE_LATEST")
        body = self.model_dump(mode="python", exclude={"binding_hash"})
        if self.binding_hash != content_hash(body):
            raise ValueError("MODEL_BINDING_HASH_MISMATCH")
        return self


def create_stage1_model_binding(
    *,
    provider: str,
    immutable_model_revision: str,
    provider_evidence_hash: str,
    model_record_hash: str,
    prompt_bytes_hash: str,
    tools_policy_hash: str,
    context_policy_hash: str,
    family_registry_hash: str,
    reflection_policy_hash: str,
    decoding_parameters: dict[str, Any],
    seed: int,
    timeout_seconds: int = 30,
) -> Stage1ModelBindingV1:
    body = {
        "schema_version": "drift-stage1-model-binding/1",
        "provider": provider,
        "immutable_model_revision": immutable_model_revision,
        "provider_evidence_hash": provider_evidence_hash,
        "model_record_hash": model_record_hash,
        "prompt_bytes_hash": prompt_bytes_hash,
        "tools_policy_hash": tools_policy_hash,
        "context_policy_hash": context_policy_hash,
        "family_registry_hash": family_registry_hash,
        "reflection_policy_hash": reflection_policy_hash,
        "decoding_parameters": decoding_parameters,
        "seed_policy": "HOST_ENFORCED_SEEDED_OR_RECORDED_REPLAY",
        "seed": seed,
        "timeout_seconds": timeout_seconds,
        "max_retries": 1,
        "captured_response_replay": "REPRODUCIBILITY_ONLY",
    }
    h = content_hash(body)
    return Stage1ModelBindingV1.model_validate_json(
        canonical_json(body | {"binding_hash": h})
    )


FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "BROKER_DISPATCH",
    "LIVE_CAPITAL",
    "UNBOUND_WEB_SEARCH",
    "CODE_EXECUTION",
)


class StudyRuntimeAuthorizationV1(FrozenModel):
    schema_version: Literal["drift-stage1-runtime-auth/1"] = (
        "drift-stage1-runtime-auth/1"
    )
    grant_id: NonBlankStr
    grant_hash: SHA256Hash
    allowed_provider: NonBlankStr
    allowed_model: NonBlankStr
    allowed_operation: Literal["OFFLINE_READ_ONLY_INFERENCE_REPLAY"] = (
        "OFFLINE_READ_ONLY_INFERENCE_REPLAY"
    )
    date_scope_start: date
    date_scope_end: date
    per_request_monetary_ceiling: Decimal = Field(ge=0)
    total_monetary_ceiling: Decimal = Field(ge=0)
    token_context_bound: int = Field(gt=0)
    deadline_seconds: int = Field(gt=0)
    private_storage_root: NonBlankStr
    forbidden_capabilities: tuple[str, ...] = FORBIDDEN_CAPABILITIES
    auth_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_auth(self) -> Self:
        if self.date_scope_start > self.date_scope_end:
            raise ValueError("AUTH_DATE_SCOPE_REVERSED")
        body = self.model_dump(mode="python", exclude={"auth_hash"})
        if self.auth_hash != content_hash(body):
            raise ValueError("RUNTIME_AUTH_HASH_MISMATCH")
        return self


def create_study_runtime_authorization(
    *,
    grant_id: str,
    grant_hash: str,
    allowed_provider: str,
    allowed_model: str,
    date_scope_start: date,
    date_scope_end: date,
    per_request_monetary_ceiling: Decimal,
    total_monetary_ceiling: Decimal,
    token_context_bound: int,
    deadline_seconds: int,
    private_storage_root: str,
) -> StudyRuntimeAuthorizationV1:
    body = {
        "schema_version": "drift-stage1-runtime-auth/1",
        "grant_id": grant_id,
        "grant_hash": grant_hash,
        "allowed_provider": allowed_provider,
        "allowed_model": allowed_model,
        "allowed_operation": "OFFLINE_READ_ONLY_INFERENCE_REPLAY",
        "date_scope_start": date_scope_start,
        "date_scope_end": date_scope_end,
        "per_request_monetary_ceiling": per_request_monetary_ceiling,
        "total_monetary_ceiling": total_monetary_ceiling,
        "token_context_bound": token_context_bound,
        "deadline_seconds": deadline_seconds,
        "private_storage_root": private_storage_root,
        "forbidden_capabilities": FORBIDDEN_CAPABILITIES,
    }
    h = content_hash(body)
    return StudyRuntimeAuthorizationV1.model_validate_json(
        canonical_json(body | {"auth_hash": h})
    )
