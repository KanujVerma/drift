"""Unit tests for Stage 1 study report serialization and hash verification."""

from decimal import Decimal

from drift.experiments.stage1_study_outcomes import classify_study_outcome
from drift.experiments.stage1_study_report import create_study_report

H = "7" * 64


def test_create_valid_study_report() -> None:
    outcome = classify_study_outcome(
        scheduled_sessions=252,
        primary_economic_advantage=Decimal("-100"),
        b_volatility=Decimal("0.10"),
        r_volatility=Decimal("0.10"),
        b_max_drawdown=Decimal("0.10"),
        r_max_drawdown=Decimal("0.10"),
    )

    report = create_study_report(
        study_id="STUDY-HISTORICAL-2025",
        protocol_hash=H,
        mode="RETROSPECTIVE_DISCOVERY",
        scheduled_sessions=252,
        observed_sessions=252,
        outcome_classification=outcome,
        primary_economic_advantage=Decimal("-100"),
        limitations=("Historical single-path market evidence only",),
    )

    assert report.study_id == "STUDY-HISTORICAL-2025"
    assert report.outcome_classification.outcome == "UNSUCCESSFUL"
    assert len(report.report_hash) == 64
