"""Unit tests for Stage 1 immutable Model B binding and 2024 validation.

Workstream F, Issue 575.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_model_validation import (
    ImmutableModelBindingV1,
    ValidationRunConfigV1,
    ValidationRunResultV1,
    create_immutable_model_binding,
    create_study_model_policy,
    execute_2024_validation,
)
from drift.experiments.stage1_study_artifacts import CalibrationPairV1
from drift.experiments.stage1_study_freeze import StudyDateWindowV1


def _create_valid_binding() -> ImmutableModelBindingV1:
    return create_immutable_model_binding(
        binding_id="BINDING-CLAUDE-35-20241022",
        provider="anthropic",
        deployment_version="claude-3-5-sonnet-20241022",
        prompt_text="You are an asset allocator. Select B3, B4, or B5.",
        seed=42,
        token_ceiling=4096,
        monetary_ceiling=Decimal("10.00"),
        transport_kind="DIRECT_API",
        known_training_cutoff=date(2023, 12, 31),
    )


def test_immutable_model_binding_and_study_policy_conformance() -> None:
    binding = _create_valid_binding()
    assert binding.provider == "anthropic"
    assert binding.deployment_version == "claude-3-5-sonnet-20241022"
    assert binding.seed == 42
    assert binding.token_ceiling == 4096
    assert binding.known_training_cutoff == date(2023, 12, 31)

    policy = create_study_model_policy(binding)
    assert policy.provider == "anthropic"
    assert policy.immutable_model_revision == "claude-3-5-sonnet-20241022"
    assert policy.seed == 42
    assert policy.known_training_cutoff == date(2023, 12, 31)
    assert len(policy.model_record_hash) == 64
    assert len(policy.prompt_hash) == 64


def test_2024_validation_positive_control(tmp_path: Path) -> None:
    binding = _create_valid_binding()
    comparator = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50"))

    ledger_dir = tmp_path / "val_ledgers"
    config = ValidationRunConfigV1(
        model_binding=binding,
        comparator_pair=comparator,
        session_count=42,  # 2 rebalance boundaries
        ledger_dir=ledger_dir,
    )

    artifact_store: dict[str, Any] = {}
    receipt_store: dict[str, Any] = {}

    result = execute_2024_validation(
        config,
        artifact_store=artifact_store,
        receipt_store=receipt_store,
    )

    assert result.status == "COMPLETED"
    assert result.evaluated_sessions_count == 42
    assert result.b_terminal_nav > Decimal("9000")
    assert result.r_terminal_nav > Decimal("9000")
    assert len(result.b_receipt_refs) == 42
    assert len(result.r_receipt_refs) == 42
    assert len(result.model_replay_refs) > 0

    # Verify exposure inventory record
    assert len(result.exposure_record) == 3
    assert any("2024_VALIDATION" in exp for exp in result.exposure_record)
    assert any("FITTED_DEV_ONLY" in exp for exp in result.exposure_record)

    # Verify ledgers created
    assert Path(result.ledger_paths["ARM-B"]).exists()
    assert Path(result.ledger_paths["ARM-R"]).exists()
    assert Path(result.ledger_paths["ARM-B"]).stat().st_size > 0
    assert Path(result.ledger_paths["ARM-R"]).stat().st_size > 0


def test_validation_negative_control_fake_transport_rejected() -> None:
    with pytest.raises(ValueError, match="FAKE_TRANSPORT_NOT_AUTHENTIC_AI"):
        create_immutable_model_binding(
            binding_id="BINDING-FAKE",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-20241022",
            prompt_text="Alloc.",
            transport_kind="FAKE_TRANSPORT",
        )


def test_validation_negative_control_unpinned_revision_rejected() -> None:
    with pytest.raises(ValueError, match="VALIDATION_UNPINNED_MODEL_REVISION"):
        create_immutable_model_binding(
            binding_id="BINDING-UNPINNED",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-latest",
            prompt_text="Alloc.",
        )


def test_validation_negative_control_training_cutoff_overlaps_validation() -> None:
    with pytest.raises(ValueError, match="MODEL_TRAINED_ON_VALIDATION_DATA"):
        create_immutable_model_binding(
            binding_id="BINDING-LEAKED",
            provider="anthropic",
            deployment_version="claude-3-5-sonnet-20241022",
            prompt_text="Alloc.",
            known_training_cutoff=date(2024, 6, 1),
        )


def test_validation_negative_control_invalid_window() -> None:
    binding = _create_valid_binding()
    comparator = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50"))
    bad_window = StudyDateWindowV1(start=date(2023, 1, 1), end=date(2023, 12, 31))

    config = ValidationRunConfigV1(
        model_binding=binding,
        comparator_pair=comparator,
        validation_window=bad_window,
    )
    with pytest.raises(ValueError, match="INVALID_VALIDATION_WINDOW"):
        execute_2024_validation(config)


def test_validation_result_tamper_fails(tmp_path: Path) -> None:
    binding = _create_valid_binding()
    comparator = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50"))
    config = ValidationRunConfigV1(
        model_binding=binding,
        comparator_pair=comparator,
        session_count=5,
        ledger_dir=tmp_path / "ledgers",
    )
    res = execute_2024_validation(config)

    dump = res.model_dump(mode="python")
    dump["validation_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="VALIDATION_HASH_MISMATCH"):
        ValidationRunResultV1.model_validate(dump)
