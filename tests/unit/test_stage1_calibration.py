"""Unit tests for Stage 1 calibration orchestration and N9 grid ranking."""

import random
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, localcontext

import pytest

from drift.experiments import stage1_study_artifacts
from drift.experiments.stage1_calibration import (
    execute_development_calibration,
    rank_calibration_attempts,
)
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    CalibrationAttemptReceiptV1,
    CalibrationPairV1,
    CalibrationResultV1,
    DevelopmentCalibrationPlanV1,
    create_calibration_attempt_receipt,
    create_calibration_result,
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


@pytest.mark.parametrize("precision", [6, 28, 34, 50])
@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP])
@pytest.mark.parametrize("method", ["ranking", "result"])
@pytest.mark.parametrize(
    ("higher", "lower", "other"),
    [
        ("0.10000000000000000000000000002", "0.10000000000000000000000000001", "0"),
        (
            "-0.10000000000000000000000000001",
            "-0.10000000000000000000000000002",
            "-0.2",
        ),
    ],
    ids=["positive", "negative"],
)
def test_grid_ranking_preserves_close_returns_across_decimal_contexts(
    precision: int, rounding: str, method: str, higher: str, lower: str, other: str
) -> None:
    high_return = Decimal(higher)
    low_return = Decimal(lower)
    best_pair = CalibrationPairV1(lambda_v=Decimal("1"), lambda_d=Decimal("1"))
    lower_pair = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.25"))
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"SYNTHETIC-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=(
                high_return
                if pair == best_pair
                else low_return
                if pair == lower_pair
                else Decimal(other)
            ),
            absolute_maximum_drawdown=Decimal(0),
            total_gross_turnover=Decimal(0),
        )
        for pair in ORDERED_CALIBRATION_PAIRS
    ]
    assert high_return > low_return
    selected: CalibrationPairV1 | None
    with localcontext() as context:
        context.prec = precision
        context.rounding = rounding
        if method == "ranking":
            selected = rank_calibration_attempts(attempts)[0].pair
        else:
            selected = create_calibration_result(
                plan_hash=H, completed_at=NOW, attempts=tuple(attempts)
            ).selected_pair

    assert selected == best_pair


def test_grid_true_tie_uses_ascending_coefficients() -> None:
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"SYNTHETIC-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=Decimal("0.1"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.5"),
        )
        for pair in reversed(ORDERED_CALIBRATION_PAIRS)
    ]
    expected = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.25"))
    assert rank_calibration_attempts(attempts)[0].pair == expected
    result = create_calibration_result(
        plan_hash=H, completed_at=NOW, attempts=tuple(attempts)
    )
    assert result.selected_pair == expected


def test_legacy_rounded_winner_is_refused_without_rewriting_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    best_pair = CalibrationPairV1(lambda_v=Decimal("1"), lambda_d=Decimal("1"))
    old_winner = CalibrationPairV1(lambda_v=Decimal("0.25"), lambda_d=Decimal("0.25"))
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"SYNTHETIC-{pair.lambda_v}-{pair.lambda_d}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=(
                Decimal("0.10000000000000000000000000002")
                if pair == best_pair
                else Decimal("0.10000000000000000000000000001")
                if pair == old_winner
                else Decimal(0)
            ),
            absolute_maximum_drawdown=Decimal(0),
            total_gross_turnover=Decimal(0),
        )
        for pair in ORDERED_CALIBRATION_PAIRS
    ]

    def legacy_key(
        attempt: CalibrationAttemptReceiptV1,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        assert attempt.terminal_net_return is not None
        assert attempt.absolute_maximum_drawdown is not None
        assert attempt.total_gross_turnover is not None
        return (
            -attempt.terminal_net_return,
            attempt.absolute_maximum_drawdown,
            attempt.total_gross_turnover,
            attempt.pair.lambda_v,
            attempt.pair.lambda_d,
        )

    with localcontext() as context:
        context.prec = 28
        with monkeypatch.context() as patch:
            patch.setattr(stage1_study_artifacts, "calibration_ranking_key", legacy_key)
            legacy = create_calibration_result(
                plan_hash=H, completed_at=NOW, attempts=tuple(attempts)
            )
            assert legacy.selected_pair == old_winner
            original_bytes = legacy.model_dump_json().encode()

        with pytest.raises(ValueError, match="CALIBRATION_SELECTED_PAIR_NOT_WINNER"):
            CalibrationResultV1.model_validate_json(original_bytes)


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
