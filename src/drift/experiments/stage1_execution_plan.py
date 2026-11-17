"""Execution plan supplement and cutoff policy binding.

Enforces acyclic evidence binding:
Stage1CutoffBindingV2 references base causal policy and Stage1ExecutionPlanV1.
The execution plan does not reference its future final freeze hash.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.serialization.canonical import canonical_json, content_hash

PhaseBoundaries = Literal["SEPARATE_PHASE_ACCOUNTS_USD_10000_INITIAL_B3"]
RGridPolicy = Literal["CONTINUOUS_2021_2023_NO_ANNUAL_RESET"]
RefLineage = Literal["THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"]
MemInit = Literal["EMPTY_PRIVATE_PHASE_MEMORY_FROZEN_PROMPT"]
InitialInstall = Literal["FIRST_ELIGIBLE_SCORED_OPEN_INCLUDED_IN_SCORED_NAV"]
FinalCheckpoint = Literal["TERMINAL_DECISION_OUTSIDE_WINDOW_NOT_EXECUTED"]
PrimaryView = Literal["FULL_ATTRIBUTABLE_EXPERIMENT_ECONOMICS"]
SecondaryView = Literal["RECURRING_DEPLOYMENT_ECONOMICS"]
CostAlloc = Literal[
    "DIRECT_STAYS_WITH_RESPONSIBLE_ARM_SHARED_BY_USAGE_OR_PREREGISTERED"
]
SourceRules = Literal["EXACT_HISTORICAL_SESSION_CUTOFF_NO_FUTURE_FETCH"]
TermBehavior = Literal["CONTAINED_INCOMPLETE_RETAIN_REMAINDER"]


class Stage1CutoffBindingV2(FrozenModel):
    schema_version: Literal["drift-stage1-cutoff-binding/2"] = (
        "drift-stage1-cutoff-binding/2"
    )
    base_cutoff_policy_hash: SHA256Hash
    execution_plan_hash: SHA256Hash
    binding_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        body = self.model_dump(mode="python", exclude={"binding_hash"})
        if self.binding_hash != content_hash(body):
            raise ValueError("CUTOFF_BINDING_HASH_MISMATCH")
        return self


def create_cutoff_binding_v2(
    *,
    base_cutoff_policy_hash: str,
    execution_plan_hash: str,
) -> Stage1CutoffBindingV2:
    body = {
        "schema_version": "drift-stage1-cutoff-binding/2",
        "base_cutoff_policy_hash": base_cutoff_policy_hash,
        "execution_plan_hash": execution_plan_hash,
    }
    h = content_hash(body)
    return Stage1CutoffBindingV2.model_validate_json(
        canonical_json(body | {"binding_hash": h})
    )


class Stage1ExecutionPlanV1(FrozenModel):
    schema_version: Literal["drift-stage1-execution-plan/1"] = (
        "drift-stage1-execution-plan/1"
    )
    plan_id: NonBlankStr
    created_at: UTCDateTime
    phase_account_boundaries: PhaseBoundaries = (
        "SEPARATE_PHASE_ACCOUNTS_USD_10000_INITIAL_B3"
    )
    r_grid_account_policy: RGridPolicy = "CONTINUOUS_2021_2023_NO_ANNUAL_RESET"
    reference_lineage: RefLineage = "THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"
    memory_initialization: MemInit = "EMPTY_PRIVATE_PHASE_MEMORY_FROZEN_PROMPT"
    initial_installation_timing: InitialInstall = (
        "FIRST_ELIGIBLE_SCORED_OPEN_INCLUDED_IN_SCORED_NAV"
    )
    final_checkpoint_handling: FinalCheckpoint = (
        "TERMINAL_DECISION_OUTSIDE_WINDOW_NOT_EXECUTED"
    )
    primary_economic_reporting_view: PrimaryView = (
        "FULL_ATTRIBUTABLE_EXPERIMENT_ECONOMICS"
    )
    secondary_economic_reporting_views: tuple[SecondaryView, ...] = (
        "RECURRING_DEPLOYMENT_ECONOMICS",
    )
    cost_allocation_policy: CostAlloc = (
        "DIRECT_STAYS_WITH_RESPONSIBLE_ARM_SHARED_BY_USAGE_OR_PREREGISTERED"
    )
    source_and_as_of_rules: SourceRules = (
        "EXACT_HISTORICAL_SESSION_CUTOFF_NO_FUTURE_FETCH"
    )
    termination_behavior: TermBehavior = "CONTAINED_INCOMPLETE_RETAIN_REMAINDER"
    plan_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        body = self.model_dump(mode="python", exclude={"plan_hash"})
        if self.plan_hash != content_hash(body):
            raise ValueError("EXECUTION_PLAN_HASH_MISMATCH")
        return self


def create_stage1_execution_plan(
    *,
    plan_id: str,
    created_at: datetime,
) -> Stage1ExecutionPlanV1:
    body = {
        "schema_version": "drift-stage1-execution-plan/1",
        "plan_id": plan_id,
        "created_at": created_at,
        "phase_account_boundaries": "SEPARATE_PHASE_ACCOUNTS_USD_10000_INITIAL_B3",
        "r_grid_account_policy": "CONTINUOUS_2021_2023_NO_ANNUAL_RESET",
        "reference_lineage": ("THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"),
        "memory_initialization": "EMPTY_PRIVATE_PHASE_MEMORY_FROZEN_PROMPT",
        "initial_installation_timing": (
            "FIRST_ELIGIBLE_SCORED_OPEN_INCLUDED_IN_SCORED_NAV"
        ),
        "final_checkpoint_handling": ("TERMINAL_DECISION_OUTSIDE_WINDOW_NOT_EXECUTED"),
        "primary_economic_reporting_view": ("FULL_ATTRIBUTABLE_EXPERIMENT_ECONOMICS"),
        "secondary_economic_reporting_views": ("RECURRING_DEPLOYMENT_ECONOMICS",),
        "cost_allocation_policy": (
            "DIRECT_STAYS_WITH_RESPONSIBLE_ARM_SHARED_BY_USAGE_OR_PREREGISTERED"
        ),
        "source_and_as_of_rules": ("EXACT_HISTORICAL_SESSION_CUTOFF_NO_FUTURE_FETCH"),
        "termination_behavior": "CONTAINED_INCOMPLETE_RETAIN_REMAINDER",
    }
    h = content_hash(body)
    return Stage1ExecutionPlanV1.model_validate_json(
        canonical_json(body | {"plan_hash": h})
    )


def resolve_cutoff_binding(
    binding_artifact: Stage1CutoffBindingV2 | bytes | str | dict[str, Any],
    resolver: Callable[[str], Any],
) -> tuple[dict[str, Any], Stage1ExecutionPlanV1]:
    """Resolves and verifies nested base cutoff policy and execution plan."""
    if isinstance(binding_artifact, Stage1CutoffBindingV2):
        binding = binding_artifact
    elif isinstance(binding_artifact, (bytes, str)):
        binding = Stage1CutoffBindingV2.model_validate_json(binding_artifact)
    elif isinstance(binding_artifact, dict):
        binding = Stage1CutoffBindingV2.model_validate(binding_artifact)
    else:
        raise TypeError(f"Unsupported binding artifact type: {type(binding_artifact)}")

    # Resolve base policy
    raw_base = resolver(binding.base_cutoff_policy_hash)
    if isinstance(raw_base, (bytes, str)):
        base_dict = (
            json.loads(raw_base)
            if isinstance(raw_base, str)
            else json.loads(raw_base.decode("utf-8"))
        )
    elif isinstance(raw_base, dict):
        base_dict = raw_base
    else:
        raise TypeError(f"Base cutoff policy must be dict/json, got {type(raw_base)}")

    actual_base_hash = content_hash(base_dict)
    if actual_base_hash != binding.base_cutoff_policy_hash:
        raise ValueError(
            "BASE_CUTOFF_POLICY_HASH_MISMATCH: expected "
            f"{binding.base_cutoff_policy_hash}, got {actual_base_hash}"
        )

    # Resolve execution plan
    raw_plan = resolver(binding.execution_plan_hash)
    if isinstance(raw_plan, Stage1ExecutionPlanV1):
        plan = raw_plan
    elif isinstance(raw_plan, (bytes, str)):
        plan = Stage1ExecutionPlanV1.model_validate_json(raw_plan)
    elif isinstance(raw_plan, dict):
        plan = Stage1ExecutionPlanV1.model_validate(raw_plan)
    else:
        raise TypeError(
            f"Execution plan must be Stage1ExecutionPlanV1, got {type(raw_plan)}"
        )

    if plan.plan_hash != binding.execution_plan_hash:
        raise ValueError(
            "EXECUTION_PLAN_HASH_MISMATCH: expected "
            f"{binding.execution_plan_hash}, got {plan.plan_hash}"
        )

    return base_dict, plan
