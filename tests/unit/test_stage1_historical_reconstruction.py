"""Unit tests for Stage 1 G4 historical experiment reconstruction.

Workstream H, Issue 575.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_g3_freeze_pipeline import assemble_stage1_study_draft
from drift.experiments.stage1_historical_reconstruction import (
    reconstruct_and_verify_historical_experiment,
)
from drift.experiments.stage1_study_freeze import (
    ConventionalSelectorPolicyV1,
    FrozenStage1StudyV1,
    StudyCostPolicyV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
)
from drift.serialization.canonical import content_hash

H = "a" * 64
NOW = datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC)


def _create_frozen_fixture() -> FrozenStage1StudyV1:
    draft = assemble_stage1_study_draft(
        study_id="STUDY-RECON-UNIT-01",
        created_at=NOW,
        mode="CONFIRMATORY_HISTORICAL",
        prior_holdout_exposure="AUDITED_UNEXPOSED",
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        decision_cutoff_policy_hash=H,
        seed_and_replication_policy_hash=H,
        mandate=StudyMandateV1(
            maximum_etf_fraction=Decimal("0.20"),
            maximum_equity_fraction=Decimal("0.70"),
            maximum_bond_fraction=Decimal("0.75"),
            maximum_gold_fraction=Decimal("0.20"),
            maximum_gross_fraction=Decimal("1"),
            maximum_turnover_fraction=Decimal("2"),
            existing_breach_policy_hash=H,
            feasibility_report_hash=H,
        ),
        comparator=ConventionalSelectorPolicyV1(
            formula="R:return-risk-drawdown-switchcost/1",
            volatility_penalty=Decimal("0.25"),
            drawdown_penalty=Decimal("0.50"),
            switching_cost_penalty=Decimal("0.00"),
            development_fit_hash=H,
            executable_formula_hash=H,
        ),
        model=StudyModelPolicyV1(
            provider="anthropic",
            immutable_model_revision="claude-3-5-sonnet-20241022",
            model_record_hash=H,
            prompt_hash=H,
            tools_policy_hash=H,
            context_policy_hash=H,
            feedback_policy_hash=H,
            decoding_policy_hash=H,
            seed=42,
            known_training_cutoff=date(2023, 10, 1),
        ),
        costs=StudyCostPolicyV1(
            trading_model_hash=H,
            dated_cost_evidence_hash=H,
        ),
        statistics=StudyStatisticalPolicyV1(
            alpha=Decimal("0.05"),
            minimum_economic_advantage_fraction=Decimal("0.01"),
            uncertainty_method="STATIONARY_BLOCK_BOOTSTRAP",
            bootstrap_repetitions=10000,
            bootstrap_seed=575,
            block_length_policy_hash=H,
            multiplicity_policy_hash=H,
            stopping_policy_hash=H,
            risk_free_policy_hash=H,
        ),
        development_start=date(2023, 7, 3),
        development_end=date(2023, 12, 29),
        validation_start=date(2024, 1, 2),
        validation_end=date(2024, 12, 31),
        scoring_start=date(2025, 1, 2),
        scoring_end=date(2025, 12, 31),
    )
    body = {
        "schema_version": "drift-stage1-freeze/1",
        "protocol": draft,
        "frozen_at": NOW,
        "evidence": (),
    }
    h = content_hash(body)
    return FrozenStage1StudyV1.model_validate(body | {"freeze_hash": h})


def _generate_synthetic_receipts(
    arm: str,
    n_sessions: int = 25,
    base_ret: Decimal = Decimal("0.0006"),
    fee_per_session: Decimal = Decimal("0.00"),
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    nav = Decimal("10000")
    for s_idx in range(n_sessions):
        ret = base_ret + Decimal(str(((s_idx % 5) - 2) * 0.0001))
        nav = (nav * (Decimal("1") + ret)) - fee_per_session
        receipts.append(
            {
                "receipt_id": f"HIST-{arm}-{s_idx}",
                "session_index": s_idx,
                "arm": arm,
                "metrics": {
                    "net_return": str(ret),
                    "per_share_fees": str(fee_per_session),
                    "terminal_nav": str(nav.quantize(Decimal("0.0001"))),
                },
            }
        )
    return receipts


def test_positive_historical_reconstruction() -> None:
    frozen = _create_frozen_fixture()
    b_receipts = _generate_synthetic_receipts(
        "B", n_sessions=25, base_ret=Decimal("0.0008")
    )
    r_receipts = _generate_synthetic_receipts(
        "R", n_sessions=25, base_ret=Decimal("0.0004")
    )

    b_term_nav = Decimal(b_receipts[-1]["metrics"]["terminal_nav"])
    r_term_nav = Decimal(r_receipts[-1]["metrics"]["terminal_nav"])
    operating_costs = Decimal("5.00")
    expected_pea = (
        (b_term_nav - Decimal("10000"))
        - (r_term_nav - Decimal("10000"))
        - operating_costs
    )

    report = reconstruct_and_verify_historical_experiment(
        frozen=frozen,
        b_receipts=b_receipts,
        r_receipts=r_receipts,
        incremental_operating_costs=operating_costs,
        expected_sessions=list(range(25)),
        reported_b_terminal_nav=b_term_nav,
        reported_r_terminal_nav=r_term_nav,
        reported_primary_economic_advantage=expected_pea,
    )

    assert report.status == "VERIFIED"
    assert report.total_sessions_verified == 25
    assert report.uncertainty_verified is True
    assert report.discrepancies == ()
    assert report.reconstruction_hash is not None


def test_negative_control_nav_tamper_detected() -> None:
    frozen = _create_frozen_fixture()
    b_receipts = _generate_synthetic_receipts(
        "B", n_sessions=25, base_ret=Decimal("0.0008")
    )
    r_receipts = _generate_synthetic_receipts(
        "R", n_sessions=25, base_ret=Decimal("0.0004")
    )

    # Tamper with session 10 terminal NAV in B
    b_receipts[10]["metrics"]["terminal_nav"] = "15000.0000"

    report = reconstruct_and_verify_historical_experiment(
        frozen=frozen,
        b_receipts=b_receipts,
        r_receipts=r_receipts,
        incremental_operating_costs=Decimal("5.00"),
        expected_sessions=list(range(25)),
    )

    assert report.status == "RECONSTRUCTION_FAILED"
    assert any(
        "B_NAV_COMPUTATION_DISCREPANCY at session 10" in d for d in report.discrepancies
    )


def test_negative_control_receipt_count_mismatch() -> None:
    frozen = _create_frozen_fixture()
    b_receipts = _generate_synthetic_receipts("B", n_sessions=25)
    r_receipts = _generate_synthetic_receipts("R", n_sessions=24)

    report = reconstruct_and_verify_historical_experiment(
        frozen=frozen,
        b_receipts=b_receipts,
        r_receipts=r_receipts,
        incremental_operating_costs=Decimal("5.00"),
    )

    assert report.status == "RECONSTRUCTION_FAILED"
    assert any("RECEIPT_COUNT_MISMATCH" in d for d in report.discrepancies)


def test_negative_control_reported_pea_mismatch() -> None:
    frozen = _create_frozen_fixture()
    b_receipts = _generate_synthetic_receipts(
        "B", n_sessions=25, base_ret=Decimal("0.0008")
    )
    r_receipts = _generate_synthetic_receipts(
        "R", n_sessions=25, base_ret=Decimal("0.0004")
    )

    report = reconstruct_and_verify_historical_experiment(
        frozen=frozen,
        b_receipts=b_receipts,
        r_receipts=r_receipts,
        incremental_operating_costs=Decimal("5.00"),
        reported_primary_economic_advantage=Decimal("9999.99"),  # False PEA
    )

    assert report.status == "RECONSTRUCTION_FAILED"
    assert any("REPORTED_PEA_MISMATCH" in d for d in report.discrepancies)


def test_reconstruction_report_tamper_fails() -> None:
    frozen = _create_frozen_fixture()
    b_receipts = _generate_synthetic_receipts("B", n_sessions=10)
    r_receipts = _generate_synthetic_receipts("R", n_sessions=10)

    report = reconstruct_and_verify_historical_experiment(
        frozen=frozen,
        b_receipts=b_receipts,
        r_receipts=r_receipts,
        incremental_operating_costs=Decimal("5.00"),
    )

    with pytest.raises(ValidationError, match="RECONSTRUCTION_HASH_MISMATCH"):
        report.model_copy(update={"reconstruction_hash": "f" * 64})
