"""Integration tests for Stage 1 G3 freeze and verify-freeze CLI subcommands.

Workstream G, Issue 575.
"""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from drift.experiments.stage1_g3_freeze_pipeline import (
    assemble_stage1_study_draft,
    create_multi_role_evidence_receipts,
)
from drift.experiments.stage1_study_freeze import (
    ConventionalSelectorPolicyV1,
    EvidenceRole,
    Stage1StudyDraftV1,
    StudyCostPolicyV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
)

H = "9" * 64
NOW = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
KEY = "integration-test-secret-key-multi-role"

AUTHORITIES: dict[EvidenceRole, str] = {
    "g2_integration": "auth-g2-lead",
    "dataset_qualification": "auth-data-reviewer",
    "mandate_review": "auth-compliance-officer",
    "comparator_review": "auth-quant-comparator-lead",
    "cost_review": "auth-operations-cost-lead",
    "model_replay": "auth-ai-governance-officer",
    "scientific_protocol_review": "auth-independent-statistician",
    "holdout_audit": "auth-holdout-custodian",
}


def _create_test_draft() -> Stage1StudyDraftV1:
    return assemble_stage1_study_draft(
        study_id="STUDY-CLI-G3-FREEZE",
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


def test_freeze_and_verify_freeze_cli_positive_pipeline(tmp_path: Path) -> None:
    draft = _create_test_draft()
    draft_file = tmp_path / "draft.json"
    draft_file.write_text(json.dumps(draft.model_dump(mode="json")), encoding="utf-8")

    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    host_config_data = {
        "trust_roots": {role: list(roots) for role, roots in trust_roots.items()},
        "receipt_store": store,
        "authenticated_issuers": auth_issuers,
        "evidence": [ev.model_dump(mode="json") for ev in evidence],
    }
    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps(host_config_data), encoding="utf-8")

    frozen_file = tmp_path / "frozen.json"

    # Step 1: Run freeze CLI
    proc_freeze = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "freeze",
            "--draft",
            str(draft_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(frozen_file),
        ],
        capture_output=True,
    )
    assert proc_freeze.returncode == 0, (
        f"freeze failed: {proc_freeze.stderr.decode('utf-8')}"
    )
    assert frozen_file.exists()

    frozen_data = json.loads(frozen_file.read_text(encoding="utf-8"))
    assert frozen_data["schema_version"] == "drift-stage1-freeze/1"
    assert "freeze_hash" in frozen_data

    # Step 2: Run verify-freeze CLI
    verify_report_file = tmp_path / "verify_report.json"
    proc_verify = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "verify-freeze",
            "--freeze",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(verify_report_file),
        ],
        capture_output=True,
    )
    assert proc_verify.returncode == 0, (
        f"verify-freeze failed: {proc_verify.stderr.decode('utf-8')}"
    )
    assert verify_report_file.exists()

    report_data = json.loads(verify_report_file.read_text(encoding="utf-8"))
    assert report_data["status"] == "READY_FOR_CONFIRMATORY_SCORING"
    assert len(report_data["verified_roles"]) == 8
    assert report_data["blockers"] == []


def test_freeze_cli_negative_control_missing_role(tmp_path: Path) -> None:
    draft = _create_test_draft()
    draft_file = tmp_path / "draft.json"
    draft_file.write_text(json.dumps(draft.model_dump(mode="json")), encoding="utf-8")

    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    # Incomplete evidence (missing dataset_qualification)
    incomplete_evidence = [
        ev.model_dump(mode="json")
        for ev in evidence
        if ev.role != "dataset_qualification"
    ]

    host_config_data = {
        "trust_roots": {role: list(roots) for role, roots in trust_roots.items()},
        "receipt_store": store,
        "authenticated_issuers": auth_issuers,
        "evidence": incomplete_evidence,
    }
    host_config_file = tmp_path / "host_config_incomplete.json"
    host_config_file.write_text(json.dumps(host_config_data), encoding="utf-8")

    frozen_file = tmp_path / "frozen_fail.json"

    proc_freeze = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "freeze",
            "--draft",
            str(draft_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(frozen_file),
        ],
        capture_output=True,
    )
    assert proc_freeze.returncode != 0
    assert b"G3_FREEZE_BLOCKED" in proc_freeze.stderr
    assert b"dataset_qualification" in proc_freeze.stderr
