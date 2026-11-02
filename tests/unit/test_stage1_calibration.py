"""Unit tests for Stage 1 calibration orchestration and N9 grid ranking."""

import random
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from drift.experiments.stage1_calibration import (
    execute_development_calibration,
    rank_calibration_attempts,
)
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    CalibrationAttemptReceiptV1,
    CalibrationPairV1,
    DevelopmentCalibrationPlanV1,
    create_calibration_attempt_receipt,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1

H = "9" * 64
NOW = datetime(2026, 11, 2, 6, 0, 0, tzinfo=UTC)


def make_plan() -> DevelopmentCalibrationPlanV1:
    return create_development_calibration_plan(
        plan_id="CAL-PLAN-TEST",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=StudyDateWindowV1(
            start=date(2021, 1, 1), end=date(2023, 12, 31)
        ),
        prohibited_windows=(),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )


def test_n9_calibration_ranking_and_permutations() -> None:
    # 9 attempts with equal returns (0.10)
    # pair (0.25, 0.50) has lowest drawdown (0.04) -> must win!
    target = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.50"))
    attempts = []
    for pair in ORDERED_CALIBRATION_PAIRS:
        dd = Decimal("0.04") if pair == target else Decimal("0.08")
        att = create_calibration_attempt_receipt(
            attempt_id=f"ATT-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=Decimal("0.10"),
            absolute_maximum_drawdown=dd,
            total_gross_turnover=Decimal("0.50"),
            operating_cost=Decimal("0.00"),
        )
        attempts.append(att)

    ranked = rank_calibration_attempts(attempts)
    assert ranked[0].pair == target

    # Permuting receipt order does not change ranking
    permuted = list(attempts)
    random.Random(42).shuffle(permuted)
    ranked_permuted = rank_calibration_attempts(permuted)
    assert ranked_permuted[0].pair == ranked[0].pair
    assert [a.pair for a in ranked_permuted] == [a.pair for a in ranked]


def test_n9_calibration_rejects_incomplete_grid() -> None:
    # Only 8 pairs present
    incomplete = [
        create_calibration_attempt_receipt(
            attempt_id=f"ATT-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=Decimal("0.10"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.50"),
            operating_cost=Decimal("0.00"),
        )
        for pair in ORDERED_CALIBRATION_PAIRS[:8]
    ]

    with pytest.raises(ValueError, match="CALIBRATION_GRID_INCOMPLETE"):
        rank_calibration_attempts(incomplete)


def test_execute_development_calibration_end_to_end() -> None:
    plan = make_plan()

    def mock_runner(pair: CalibrationPairV1) -> CalibrationAttemptReceiptV1:
        target = ORDERED_CALIBRATION_PAIRS[2]
        ret = Decimal("0.12") if pair == target else Decimal("0.08")
        return create_calibration_attempt_receipt(
            attempt_id=f"ATT-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=ret,
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.40"),
            operating_cost=Decimal("0.00"),
        )

    result = execute_development_calibration(
        plan, attempt_runner=mock_runner, completed_at=NOW
    )
    assert result.selected_pair == ORDERED_CALIBRATION_PAIRS[2]
    assert len(result.attempts) == 9
    assert len(result.ranking_proof) == 9
    assert len(result.result_hash) == 64
