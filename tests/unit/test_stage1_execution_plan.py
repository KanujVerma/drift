"""Unit tests for Stage 1 execution plan and cutoff policy binding."""

from datetime import UTC, datetime

import pytest

from drift.experiments.stage1_execution_plan import (
    create_cutoff_binding_v2,
    create_stage1_execution_plan,
    resolve_cutoff_binding,
)
from drift.serialization.canonical import content_hash

H_BASE = "c" * 64
NOW = datetime(2026, 11, 2, 4, 30, 0, tzinfo=UTC)


def test_create_execution_plan_and_binding() -> None:
    plan = create_stage1_execution_plan(
        plan_id="STAGE1-EXEC-PLAN-V1",
        created_at=NOW,
    )
    assert (
        plan.primary_economic_reporting_view == "FULL_ATTRIBUTABLE_EXPERIMENT_ECONOMICS"
    )
    assert len(plan.plan_hash) == 64

    binding = create_cutoff_binding_v2(
        base_cutoff_policy_hash=H_BASE,
        execution_plan_hash=plan.plan_hash,
    )
    assert binding.schema_version == "drift-stage1-cutoff-binding/2"
    assert binding.base_cutoff_policy_hash == H_BASE
    assert binding.execution_plan_hash == plan.plan_hash


def test_resolve_cutoff_binding_success() -> None:
    base_policy_dict = {"policy": "causal-month-end-cutoff", "v": 1}
    base_hash = content_hash(base_policy_dict)

    plan = create_stage1_execution_plan(
        plan_id="STAGE1-EXEC-PLAN-V1",
        created_at=NOW,
    )

    binding = create_cutoff_binding_v2(
        base_cutoff_policy_hash=base_hash,
        execution_plan_hash=plan.plan_hash,
    )

    store = {
        base_hash: base_policy_dict,
        plan.plan_hash: plan,
    }

    resolved_base, resolved_plan = resolve_cutoff_binding(binding, lambda h: store[h])

    assert resolved_base == base_policy_dict
    assert resolved_plan.plan_hash == plan.plan_hash


def test_resolve_cutoff_binding_detects_hash_mismatch() -> None:
    base_policy_dict = {"policy": "causal-month-end-cutoff", "v": 1}
    base_hash = content_hash(base_policy_dict)

    plan = create_stage1_execution_plan(
        plan_id="STAGE1-EXEC-PLAN-V1",
        created_at=NOW,
    )

    binding = create_cutoff_binding_v2(
        base_cutoff_policy_hash=base_hash,
        execution_plan_hash=plan.plan_hash,
    )

    # Corrupted base content
    store = {
        base_hash: {"policy": "corrupted"},
        plan.plan_hash: plan,
    }

    with pytest.raises(ValueError, match="BASE_CUTOFF_POLICY_HASH_MISMATCH"):
        resolve_cutoff_binding(binding, lambda h: store[h])
