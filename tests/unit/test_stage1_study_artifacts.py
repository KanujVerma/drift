"""Unit tests for Stage 1 development calibration plan and result artifacts."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    create_calibration_attempt_receipt,
    create_calibration_result,
    create_development_calibration_plan,
)
from drift.experiments.stage1_study_freeze import StudyDateWindowV1

H = "b" * 64
NOW = datetime(2026, 11, 2, 4, 0, 0, tzinfo=UTC)


def test_create_valid_development_calibration_plan() -> None:
    plan = create_development_calibration_plan(
        plan_id="CAL-PLAN-2021-2023-V1",
        created_at=NOW,
        method_version="grid-9-conventional/1",
        owner_reference="kanuj@drift.local",
        reviewer_reference="matthew@drift.local",
        development_window=StudyDateWindowV1(
            start=date(2021, 1, 1), end=date(2023, 12, 31)
        ),
        prohibited_windows=(
            StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
            StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
        ),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        execution_policy_hash=H,
        cost_policy_hash=H,
        mandate_policy_hash=H,
        access_log_policy_hash=H,
    )
    assert plan.scope == "DEVELOPMENT_ONLY"
    assert len(plan.coefficient_pairs) == 9
    assert plan.coefficient_pairs == ORDERED_CALIBRATION_PAIRS
    assert len(plan.plan_hash) == 64


def test_calibration_plan_rejects_overlapping_prohibited_window() -> None:
    with pytest.raises(ValueError, match="CALIBRATION_PLAN_WINDOW_OVERLAPS_PROHIBITED"):
        create_development_calibration_plan(
            plan_id="CAL-PLAN-OVERLAP",
            created_at=NOW,
            method_version="grid-9-conventional/1",
            owner_reference="kanuj@drift.local",
            reviewer_reference="matthew@drift.local",
            development_window=StudyDateWindowV1(
                start=date(2021, 1, 1), end=date(2023, 12, 31)
            ),
            prohibited_windows=(
                StudyDateWindowV1(start=date(2023, 6, 1), end=date(2024, 12, 31)),
            ),
            installed_source_hash=H,
            dataset_manifest_hash=H,
            calendar_and_universe_hash=H,
            execution_policy_hash=H,
            cost_policy_hash=H,
            mandate_policy_hash=H,
            access_log_policy_hash=H,
        )


def test_calibration_plan_rejects_backdated_acceptance() -> None:
    with pytest.raises(ValueError, match="CALIBRATION_PLAN_BACKDATED_ACCEPTANCE"):
        create_development_calibration_plan(
            plan_id="CAL-PLAN-BACKDATED",
            created_at=NOW,
            accepted_at=datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC),
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


def test_calibration_attempt_receipt_validation() -> None:
    pair = ORDERED_CALIBRATION_PAIRS[0]
    rec = create_calibration_attempt_receipt(
        attempt_id="ATTEMPT-01",
        pair=pair,
        status="COMPLETED",
        terminal_net_return=Decimal("0.15"),
        absolute_maximum_drawdown=Decimal("0.08"),
        total_gross_turnover=Decimal("0.45"),
        operating_cost=Decimal("0.00"),
    )
    assert rec.status == "COMPLETED"
    assert rec.terminal_net_return == Decimal("0.15")

    with pytest.raises(ValueError, match="CALIBRATION_RECEIPT_MISSING_METRICS"):
        create_calibration_attempt_receipt(
            attempt_id="ATTEMPT-02",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=None,
        )


def test_calibration_result_requires_all_9_attempts_for_selection() -> None:
    attempts = tuple(
        create_calibration_attempt_receipt(
            attempt_id=f"ATTEMPT-{i:02d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=Decimal("0.10") + Decimal(f"0.0{i}"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.30"),
            operating_cost=Decimal("0.00"),
        )
        for i, pair in enumerate(ORDERED_CALIBRATION_PAIRS)
    )

    selected = ORDERED_CALIBRATION_PAIRS[8]
    selected_receipt = attempts[8].receipt_hash

    res = create_calibration_result(
        plan_hash=H,
        completed_at=NOW,
        attempts=attempts,
        selected_pair=selected,
        selected_pair_receipt_hash=selected_receipt,
    )
    assert res.selected_pair == selected
    assert len(res.attempts) == 9

    # Rejection if non-winning pair is selected
    with pytest.raises(ValueError, match="CALIBRATION_SELECTED_PAIR_NOT_WINNER"):
        create_calibration_result(
            plan_hash=H,
            completed_at=NOW,
            attempts=attempts,
            selected_pair=ORDERED_CALIBRATION_PAIRS[3],
            selected_pair_receipt_hash=attempts[3].receipt_hash,
        )

    # Rejection if incomplete attempts
    with pytest.raises(ValueError, match="CALIBRATION_RESULT_INCOMPLETE_ATTEMPTS"):
        create_calibration_result(
            plan_hash=H,
            completed_at=NOW,
            attempts=attempts[:5],
            selected_pair=selected,
            selected_pair_receipt_hash=selected_receipt,
        )
