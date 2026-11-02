"""Immutable study artifacts for development calibration and execution plans.

Maintains acyclic evidence dependencies:
calibration plan -> calibration result -> fitted protocol -> final freeze.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.experiments.stage1_study_freeze import (
    STAGE1_UNIVERSE,
    StudyDateWindowV1,
    StudyEvidenceReferenceV1,
)
from drift.serialization.canonical import canonical_json, content_hash


class CalibrationPairV1(FrozenModel):
    lambda_v: Decimal = Field(ge=0, allow_inf_nan=False)
    lambda_d: Decimal = Field(ge=0, allow_inf_nan=False)


ORDERED_CALIBRATION_PAIRS: tuple[CalibrationPairV1, ...] = (
    CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.25")),
    CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50")),
    CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("1.00")),
    CalibrationPairV1(lambda_v=Decimal("0.50"), lambda_d=Decimal("0.25")),
    CalibrationPairV1(lambda_v=Decimal("0.50"), lambda_d=Decimal("0.50")),
    CalibrationPairV1(lambda_v=Decimal("0.50"), lambda_d=Decimal("1.00")),
    CalibrationPairV1(lambda_v=Decimal("1.00"), lambda_d=Decimal("0.25")),
    CalibrationPairV1(lambda_v=Decimal("1.00"), lambda_d=Decimal("0.50")),
    CalibrationPairV1(lambda_v=Decimal("1.00"), lambda_d=Decimal("1.00")),
)

DEFAULT_RANKING_KEY_DEFINITION: tuple[str, ...] = (
    "-terminal_net_return",
    "absolute_maximum_drawdown",
    "total_gross_turnover",
    "lambda_v",
    "lambda_d",
)


class DevelopmentCalibrationPlanV1(FrozenModel):
    schema_version: Literal["drift-stage1-calibration-plan/1"] = (
        "drift-stage1-calibration-plan/1"
    )
    plan_id: NonBlankStr
    created_at: UTCDateTime
    accepted_at: UTCDateTime | None = None
    method_version: NonBlankStr
    owner_reference: NonBlankStr
    reviewer_reference: NonBlankStr
    scope: Literal["DEVELOPMENT_ONLY"] = "DEVELOPMENT_ONLY"
    development_window: StudyDateWindowV1
    prohibited_windows: tuple[StudyDateWindowV1, ...]
    universe: tuple[str, ...] = STAGE1_UNIVERSE
    initial_family: Literal["B3"] = "B3"
    initial_capital: Literal["10000"] = "10000"
    currency: Literal["USD"] = "USD"
    coefficient_pairs: tuple[CalibrationPairV1, ...] = ORDERED_CALIBRATION_PAIRS
    ranking_key_definition: tuple[str, ...] = DEFAULT_RANKING_KEY_DEFINITION
    installed_source_hash: SHA256Hash
    dataset_manifest_hash: SHA256Hash
    calendar_and_universe_hash: SHA256Hash
    execution_policy_hash: SHA256Hash
    cost_policy_hash: SHA256Hash
    mandate_policy_hash: SHA256Hash
    access_log_policy_hash: SHA256Hash
    plan_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.universe != STAGE1_UNIVERSE:
            raise ValueError("CALIBRATION_PLAN_UNIVERSE_CHANGED")
        if self.coefficient_pairs != ORDERED_CALIBRATION_PAIRS:
            raise ValueError("CALIBRATION_PLAN_COEFFICIENT_PAIRS_INVALID")
        if self.ranking_key_definition != DEFAULT_RANKING_KEY_DEFINITION:
            raise ValueError("CALIBRATION_PLAN_RANKING_KEY_INVALID")
        if self.accepted_at is not None and self.accepted_at < self.created_at:
            raise ValueError("CALIBRATION_PLAN_BACKDATED_ACCEPTANCE")
        for window in self.prohibited_windows:
            if not (
                self.development_window.end < window.start
                or self.development_window.start > window.end
            ):
                raise ValueError("CALIBRATION_PLAN_WINDOW_OVERLAPS_PROHIBITED")
        body = self.model_dump(mode="python", exclude={"plan_hash"})
        if self.plan_hash != content_hash(body):
            raise ValueError("CALIBRATION_PLAN_HASH_MISMATCH")
        return self


def create_development_calibration_plan(
    *,
    plan_id: str,
    created_at: datetime,
    method_version: str,
    owner_reference: str,
    reviewer_reference: str,
    development_window: StudyDateWindowV1,
    prohibited_windows: tuple[StudyDateWindowV1, ...],
    installed_source_hash: str,
    dataset_manifest_hash: str,
    calendar_and_universe_hash: str,
    execution_policy_hash: str,
    cost_policy_hash: str,
    mandate_policy_hash: str,
    access_log_policy_hash: str,
    accepted_at: datetime | None = None,
) -> DevelopmentCalibrationPlanV1:
    body = {
        "schema_version": "drift-stage1-calibration-plan/1",
        "plan_id": plan_id,
        "created_at": created_at,
        "accepted_at": accepted_at,
        "method_version": method_version,
        "owner_reference": owner_reference,
        "reviewer_reference": reviewer_reference,
        "scope": "DEVELOPMENT_ONLY",
        "development_window": development_window,
        "prohibited_windows": prohibited_windows,
        "universe": STAGE1_UNIVERSE,
        "initial_family": "B3",
        "initial_capital": "10000",
        "currency": "USD",
        "coefficient_pairs": ORDERED_CALIBRATION_PAIRS,
        "ranking_key_definition": DEFAULT_RANKING_KEY_DEFINITION,
        "installed_source_hash": installed_source_hash,
        "dataset_manifest_hash": dataset_manifest_hash,
        "calendar_and_universe_hash": calendar_and_universe_hash,
        "execution_policy_hash": execution_policy_hash,
        "cost_policy_hash": cost_policy_hash,
        "mandate_policy_hash": mandate_policy_hash,
        "access_log_policy_hash": access_log_policy_hash,
    }
    h = content_hash(body)
    return DevelopmentCalibrationPlanV1.model_validate_json(
        canonical_json(body | {"plan_hash": h})
    )


class CalibrationAttemptReceiptV1(FrozenModel):
    attempt_id: NonBlankStr
    pair: CalibrationPairV1
    status: Literal["COMPLETED", "FAILED"]
    plan_hash: SHA256Hash | None = None
    development_execution_hash: SHA256Hash | None = None
    terminal_net_return: Decimal | None = None
    absolute_maximum_drawdown: Decimal | None = None
    total_gross_turnover: Decimal | None = None
    operating_cost: Decimal | None = None
    receipt_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        body = self.model_dump(mode="python", exclude={"receipt_hash"})
        if self.receipt_hash != content_hash(body):
            raise ValueError("CALIBRATION_RECEIPT_HASH_MISMATCH")
        if self.status == "COMPLETED":
            if (
                self.terminal_net_return is None
                or self.absolute_maximum_drawdown is None
                or self.total_gross_turnover is None
            ):
                raise ValueError("CALIBRATION_RECEIPT_MISSING_METRICS")
        return self


def create_calibration_attempt_receipt(
    *,
    attempt_id: str,
    pair: CalibrationPairV1,
    status: Literal["COMPLETED", "FAILED"],
    plan_hash: str | None = None,
    development_execution_hash: str | None = None,
    terminal_net_return: Decimal | None = None,
    absolute_maximum_drawdown: Decimal | None = None,
    total_gross_turnover: Decimal | None = None,
    operating_cost: Decimal | None = None,
) -> CalibrationAttemptReceiptV1:
    body = {
        "attempt_id": attempt_id,
        "pair": pair,
        "status": status,
        "plan_hash": plan_hash,
        "development_execution_hash": development_execution_hash,
        "terminal_net_return": terminal_net_return,
        "absolute_maximum_drawdown": absolute_maximum_drawdown,
        "total_gross_turnover": total_gross_turnover,
        "operating_cost": operating_cost,
    }
    h = content_hash(body)
    return CalibrationAttemptReceiptV1.model_validate_json(
        canonical_json(body | {"receipt_hash": h})
    )


def calibration_ranking_key(
    attempt: CalibrationAttemptReceiptV1,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    if (
        attempt.terminal_net_return is None
        or attempt.absolute_maximum_drawdown is None
        or attempt.total_gross_turnover is None
    ):
        raise ValueError("INCOMPLETE_ATTEMPT_METRICS_CANNOT_BE_RANKED")

    return (
        -attempt.terminal_net_return,
        attempt.absolute_maximum_drawdown,
        attempt.total_gross_turnover,
        attempt.pair.lambda_v,
        attempt.pair.lambda_d,
    )


def compute_ranking_proof(
    ranked_attempts: Sequence[CalibrationAttemptReceiptV1],
) -> tuple[str, ...]:
    return tuple(
        hashlib.sha256(
            f"{att.pair.lambda_v}:{att.pair.lambda_d}:{att.receipt_hash}".encode()
        ).hexdigest()
        for att in ranked_attempts
    )


class CalibrationResultV1(FrozenModel):
    schema_version: Literal["drift-stage1-calibration-result/1"] = (
        "drift-stage1-calibration-result/1"
    )
    plan_hash: SHA256Hash
    completed_at: UTCDateTime
    attempts: tuple[CalibrationAttemptReceiptV1, ...]
    selected_pair: CalibrationPairV1 | None = None
    selected_pair_receipt_hash: SHA256Hash | None = None
    ranking_proof: tuple[str, ...] = ()
    exposure_record: tuple[str, ...] = ()
    original_acceptance_receipts: tuple[StudyEvidenceReferenceV1, ...] = ()
    result_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        body = self.model_dump(mode="python", exclude={"result_hash"})
        if self.result_hash != content_hash(body):
            raise ValueError("CALIBRATION_RESULT_HASH_MISMATCH")
        if self.selected_pair is not None:
            completed_attempts = [
                att for att in self.attempts if att.status == "COMPLETED"
            ]
            completed_pairs = [att.pair for att in completed_attempts]
            if len(completed_pairs) != len(set(completed_pairs)):
                raise ValueError(
                    "CALIBRATION_RESULT_DUPLICATE_ATTEMPTS: repeated grid runs for "
                    "the same coefficient pair are prohibited"
                )
            if set(completed_pairs) != set(ORDERED_CALIBRATION_PAIRS):
                raise ValueError("CALIBRATION_RESULT_INCOMPLETE_ATTEMPTS")
            if len(completed_attempts) != len(ORDERED_CALIBRATION_PAIRS):
                raise ValueError("CALIBRATION_RESULT_ATTEMPT_COUNT_MISMATCH")

            for att in completed_attempts:
                if att.plan_hash is not None and att.plan_hash != self.plan_hash:
                    raise ValueError(
                        f"CALIBRATION_ATTEMPT_PLAN_MISMATCH: attempt {att.attempt_id} "
                        f"plan {att.plan_hash} does not match result {self.plan_hash}"
                    )

            if self.selected_pair not in set(completed_pairs):
                raise ValueError("CALIBRATION_SELECTED_PAIR_NOT_COMPLETED")

            ranked = sorted(completed_attempts, key=calibration_ranking_key)
            winner = ranked[0]
            if self.selected_pair != winner.pair:
                raise ValueError(
                    f"CALIBRATION_SELECTED_PAIR_NOT_WINNER: expected "
                    f"{winner.pair}, got {self.selected_pair}"
                )
            if self.selected_pair_receipt_hash != winner.receipt_hash:
                raise ValueError("CALIBRATION_SELECTED_PAIR_RECEIPT_MISMATCH")
            expected_proof = compute_ranking_proof(ranked)
            if self.ranking_proof != expected_proof:
                raise ValueError("CALIBRATION_RANKING_PROOF_MISMATCH")
        return self


def create_calibration_result(
    *,
    plan_hash: str,
    completed_at: datetime,
    attempts: tuple[CalibrationAttemptReceiptV1, ...],
    selected_pair: CalibrationPairV1 | None = None,
    selected_pair_receipt_hash: str | None = None,
    ranking_proof: tuple[str, ...] = (),
    exposure_record: tuple[str, ...] = (),
    original_acceptance_receipts: tuple[StudyEvidenceReferenceV1, ...] = (),
) -> CalibrationResultV1:
    completed = [att for att in attempts if att.status == "COMPLETED"]
    if (
        selected_pair is not None
        or {att.pair for att in completed} == set(ORDERED_CALIBRATION_PAIRS)
    ) and completed:
        ranked = sorted(completed, key=calibration_ranking_key)
        winner = ranked[0]
        if selected_pair is None:
            selected_pair = winner.pair
            selected_pair_receipt_hash = winner.receipt_hash
        if not ranking_proof:
            ranking_proof = compute_ranking_proof(ranked)

    body = {
        "schema_version": "drift-stage1-calibration-result/1",
        "plan_hash": plan_hash,
        "completed_at": completed_at,
        "attempts": attempts,
        "selected_pair": selected_pair,
        "selected_pair_receipt_hash": selected_pair_receipt_hash,
        "ranking_proof": ranking_proof,
        "exposure_record": exposure_record,
        "original_acceptance_receipts": original_acceptance_receipts,
    }
    h = content_hash(body)
    return CalibrationResultV1.model_validate_json(
        canonical_json(body | {"result_hash": h})
    )
