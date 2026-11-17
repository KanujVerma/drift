"""Unit tests for Stage 1 model binding and runtime authorization."""

from datetime import date
from decimal import Decimal

import pytest

from drift.intelligence.stage1_model_binding import (
    create_stage1_model_binding,
    create_study_runtime_authorization,
)

H = "d" * 64


def test_create_valid_model_binding() -> None:
    binding = create_stage1_model_binding(
        provider="anthropic",
        immutable_model_revision="claude-3-5-sonnet-20241022",
        provider_evidence_hash=H,
        model_record_hash=H,
        prompt_bytes_hash=H,
        tools_policy_hash=H,
        context_policy_hash=H,
        family_registry_hash=H,
        reflection_policy_hash=H,
        decoding_parameters={"temperature": 0.0, "max_tokens": 1024},
        seed=575,
    )
    assert binding.provider == "anthropic"
    assert binding.seed == 575
    assert len(binding.binding_hash) == 64


def test_model_binding_rejects_latest_alias() -> None:
    with pytest.raises(ValueError, match="MODEL_REVISION_CANNOT_BE_LATEST"):
        create_stage1_model_binding(
            provider="openai",
            immutable_model_revision="gpt-4o-latest",
            provider_evidence_hash=H,
            model_record_hash=H,
            prompt_bytes_hash=H,
            tools_policy_hash=H,
            context_policy_hash=H,
            family_registry_hash=H,
            reflection_policy_hash=H,
            decoding_parameters={"temperature": 0.0},
            seed=575,
        )


def test_create_study_runtime_authorization() -> None:
    auth = create_study_runtime_authorization(
        grant_id="GRANT-2026-STAGE1-EVAL",
        grant_hash=H,
        allowed_provider="anthropic",
        allowed_model="claude-3-5-sonnet-20241022",
        date_scope_start=date(2026, 11, 1),
        date_scope_end=date(2026, 11, 30),
        per_request_monetary_ceiling=Decimal("0.50"),
        total_monetary_ceiling=Decimal("100.00"),
        token_context_bound=64000,
        deadline_seconds=30,
        private_storage_root="/private/receipts",
    )
    assert auth.allowed_operation == "OFFLINE_READ_ONLY_INFERENCE_REPLAY"
    assert "BROKER_DISPATCH" in auth.forbidden_capabilities
    assert len(auth.auth_hash) == 64


def test_study_runtime_authorization_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError, match="AUTH_DATE_SCOPE_REVERSED"):
        create_study_runtime_authorization(
            grant_id="GRANT-REVERSED",
            grant_hash=H,
            allowed_provider="anthropic",
            allowed_model="claude-3-5-sonnet-20241022",
            date_scope_start=date(2026, 11, 30),
            date_scope_end=date(2026, 11, 1),
            per_request_monetary_ceiling=Decimal("0.50"),
            total_monetary_ceiling=Decimal("100.00"),
            token_context_bound=64000,
            deadline_seconds=30,
            private_storage_root="/private/receipts",
        )
