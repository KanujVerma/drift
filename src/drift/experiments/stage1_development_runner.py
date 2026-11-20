"""Compatibility boundary for the unqualified Stage 1 development runner.

The public entry point refuses before any execution or side effect. Original
historical execution requires the qualified producer tracked in issue #606.
The retained models are serialization contracts, not proof of data provenance.
"""

from __future__ import annotations

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
from drift.experiments.stage1_study_artifacts import (
    CalibrationAttemptReceiptV1,
    CalibrationPairV1,
    CalibrationResultV1,
    DevelopmentCalibrationPlanV1,
)
from drift.serialization.canonical import content_hash

DEVELOPMENT_TOTAL_SESSIONS: int = 754  # 2021-2023 trading days (~251-253/yr)
DECISION_INTERVAL_SESSIONS: int = 21  # Monthly decision cadence
LOOKBACK_SESSION_INTERVALS: int = 126  # 126 return intervals = 127 marks


class DevelopmentRunConfigV1(FrozenModel):
    """Configuration for executing 9-pair R development calibration runs."""

    plan: DevelopmentCalibrationPlanV1
    authority_id: NonBlankStr = "trusted-development-authority"
    cost_model: EvaluationCostModelV1 = Field(default_factory=create_stage1_cost_model)
    session_count: int | None = None
    initial_capital: Decimal = Decimal("10000.00")
    ledger_dir: Path | None = None


class DevelopmentRunResultV1(FrozenModel):
    """Immutable result of executing the 9 R calibration attempts."""

    schema_version: Literal["drift-stage1-development-run/1"] = (
        "drift-stage1-development-run/1"
    )
    run_id: NonBlankStr
    plan_hash: SHA256Hash
    status: Literal["COMPLETED", "FAILED"]
    completed_at: UTCDateTime
    evaluated_sessions_count: int = Field(ge=0, strict=True)
    attempts: tuple[CalibrationAttemptReceiptV1, ...]
    selected_pair: CalibrationPairV1 | None = None
    selected_pair_receipt_hash: SHA256Hash | None = None
    ranking_proof: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    ledger_paths: dict[str, str] = Field(default_factory=dict)
    run_result_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"run_result_hash"})
        computed = content_hash(body)
        if self.run_result_hash != computed:
            raise ValueError(
                f"DEVELOPMENT_RUN_RESULT_HASH_MISMATCH: expected {computed}, "
                f"got {self.run_result_hash}"
            )
        return self


def execute_development_run(
    config: DevelopmentRunConfigV1,
    *,
    artifact_store: dict[str, Any] | None = None,
    receipt_store: dict[str, Any] | None = None,
    allocated_accounts: set[str] | None = None,
) -> tuple[DevelopmentRunResultV1, CalibrationResultV1]:
    """Refuse unqualified execution without touching caller state or storage.

    A historical-looking plan, supplied authority label, ledger directory, or
    session count does not qualify generated returns as historical evidence.
    Ranking explicit test receipts belongs to the separate calibration API/CLI;
    this entry point has no synthetic opt-in or private simulation fallback.
    """
    raise ValueError("DEVELOPMENT_CALIBRATION_UNQUALIFIED: synthetic inputs only")
