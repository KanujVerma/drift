"""Stage 1 development calibration orchestration over the 9-pair R grid.

Implements locked deterministic ranking key:
(-terminal_net_return, absolute_maximum_drawdown,
 total_gross_turnover, lambda_v, lambda_d)
Requires all nine combinations present and completed.
Permuting receipt order does not change ranking.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    CalibrationAttemptReceiptV1,
    CalibrationPairV1,
    CalibrationResultV1,
    DevelopmentCalibrationPlanV1,
    compute_ranking_proof,
    create_calibration_result,
)
from drift.experiments.stage1_study_freeze import StudyEvidenceReferenceV1


def calibration_ranking_key(
    attempt: CalibrationAttemptReceiptV1,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Deterministic ranking key:

    (-terminal_net_return, absolute_maximum_drawdown,
     total_gross_turnover, lambda_v, lambda_d)
    """
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


def rank_calibration_attempts(
    attempts: Sequence[CalibrationAttemptReceiptV1],
) -> list[CalibrationAttemptReceiptV1]:
    """Deterministically ranks attempts across all 9 required coefficient pairs.

    Requires exactly the 9 planned pairs to be present and COMPLETED.
    """
    completed = [att for att in attempts if att.status == "COMPLETED"]
    completed_pairs = {att.pair for att in completed}

    expected_pairs = set(ORDERED_CALIBRATION_PAIRS)
    if completed_pairs != expected_pairs:
        missing = sorted(
            [f"({p.lambda_v},{p.lambda_d})" for p in expected_pairs - completed_pairs]
        )
        raise ValueError(f"CALIBRATION_GRID_INCOMPLETE: missing {','.join(missing)}")

    return sorted(completed, key=calibration_ranking_key)


def execute_development_calibration(
    plan: DevelopmentCalibrationPlanV1,
    *,
    attempt_runner: Callable[[CalibrationPairV1], CalibrationAttemptReceiptV1],
    completed_at: datetime | None = None,
    original_acceptance_receipts: tuple[StudyEvidenceReferenceV1, ...] = (),
) -> CalibrationResultV1:
    """Executes development calibration over all 9 pairs in the accepted plan."""
    now = completed_at or datetime.now(UTC)
    attempts: list[CalibrationAttemptReceiptV1] = []

    for pair in plan.coefficient_pairs:
        receipt = attempt_runner(pair)
        attempts.append(receipt)

    ranked = rank_calibration_attempts(attempts)
    winner = ranked[0]
    ranking_proof = compute_ranking_proof(ranked)

    return create_calibration_result(
        plan_hash=plan.plan_hash,
        completed_at=now,
        attempts=tuple(attempts),
        selected_pair=winner.pair,
        selected_pair_receipt_hash=winner.receipt_hash,
        ranking_proof=ranking_proof,
        original_acceptance_receipts=original_acceptance_receipts,
    )
