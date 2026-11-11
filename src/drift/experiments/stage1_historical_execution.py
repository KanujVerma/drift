"""Unavailable historical execution boundary pending original evidence.

The historical producer cannot authenticate an original account or result yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from drift.domain.common import (
    FrozenModel,
    SHA256Hash,
)
from drift.domain.evaluator_bundles import (
    EvaluationInputBundleV1,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.experiments.stage1_study_freeze import (
    STAGE1_UNIVERSE,
    FrozenStage1StudyV1,
    StudyMandateV1,
)
from drift.serialization.canonical import content_hash

# Exact Stage 1 12-ETF Universe
STAGE1_12_ETFS: tuple[str, ...] = STAGE1_UNIVERSE
DEFAULT_INITIAL_CAPITAL = Decimal("10000")


@dataclass(frozen=True)
class HistoricalRunConfigV1:
    """Configuration for historical study execution."""

    frozen: FrozenStage1StudyV1
    origin_dir: Path
    bundle: EvaluationInputBundleV1 | None = None
    cost_model: EvaluationCostModelV1 | None = None
    mandate: StudyMandateV1 | None = None
    authority_id: str = "trusted-historical-root"
    initial_capital: Decimal = DEFAULT_INITIAL_CAPITAL
    incremental_operating_costs: Decimal = Decimal("10.00")
    run_comparator_arm: bool = True
    session_count: int | None = None


class HistoricalRunResultV1(FrozenModel):
    """Historical result schema; values are not independently authenticated."""

    schema_version: Literal["drift-stage1-historical-run/1"] = (
        "drift-stage1-historical-run/1"
    )
    status: Literal["COMPLETED", "FAILED"]
    freeze_hash: SHA256Hash
    executed_sessions_count: int
    candidate_arm_id: str = "ARM-B"
    comparator_arm_id: str = "ARM-R"
    candidate_receipt_refs: tuple[dict[str, Any], ...]
    reference_receipt_refs: tuple[dict[str, Any], ...]
    b_terminal_nav: Decimal
    r_terminal_nav: Decimal
    primary_economic_advantage: Decimal
    candidate_allocation_id: str
    reference_allocation_id: str
    ledger_paths: dict[str, str]
    run_result_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"run_result_hash"})
        computed = content_hash(body)
        if self.run_result_hash != computed:
            raise ValueError(
                f"HISTORICAL_RUN_RESULT_HASH_MISMATCH: expected {computed}, "
                f"got {self.run_result_hash}"
            )
        return self


def execute_historical_account_simulation(
    *,
    freeze_hash: str,
    arm: Literal["B", "R"],
    session_count: int,
    authority_id: str,
    initial_capital: Decimal,
    cost_model: EvaluationCostModelV1,
    artifact_store: dict[str, Any],
    receipt_store: dict[str, Any],
    prices_by_session: Sequence[Mapping[str, Decimal]] | None = None,
    daily_returns: Sequence[Decimal] | None = None,
) -> tuple[list[dict[str, Any]], Decimal]:
    """Refuse until authenticated original execution is available."""
    raise ValueError("HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE")


def execute_historical_study(
    config: HistoricalRunConfigV1,
    *,
    receipt_store: dict[str, Any],
    artifact_store: dict[str, Any],
) -> HistoricalRunResultV1:
    """Refuse until authenticated original execution is available."""
    raise ValueError("HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE")
