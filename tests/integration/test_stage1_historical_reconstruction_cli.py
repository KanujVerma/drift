"""Integration tests for Stage 1 G4 historical execution.

Includes independent reconstruction CLI verification (Workstream H, Issue 575).
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
from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_study_freeze import (
    ConventionalSelectorPolicyV1,
    EvidenceRole,
    FrozenStage1StudyV1,
    StudyCostPolicyV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
    freeze_study,
)

H = "b" * 64
NOW = datetime(2026, 11, 2, 11, 0, 0, tzinfo=UTC)
KEY = "historical-experiment-secret-key-multi-role"

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


def _setup_frozen_study(tmp_path: Path) -> tuple[FrozenStage1StudyV1, Path, Path]:
    draft = assemble_stage1_study_draft(
        study_id="STUDY-CLI-G4-EXPERIMENT",
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

    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    verifier = ProductionStudyEvidenceVerifier(
        trust_roots=trust_roots,
        receipt_resolver=lambda rid: store.get(rid, {}),
        authenticated_issuers=auth_issuers,
    )
    frozen = freeze_study(draft, frozen_at=NOW, evidence=evidence, verifier=verifier)

    frozen_file = tmp_path / "frozen.json"
    frozen_file.write_text(json.dumps(frozen.model_dump(mode="json")), encoding="utf-8")

    host_config_data = {
        "trust_roots": {role: list(roots) for role, roots in trust_roots.items()},
        "receipt_store": store,
        "authenticated_issuers": auth_issuers,
        "evidence": [ev.model_dump(mode="json") for ev in evidence],
        "incremental_operating_costs": "5.00",
    }
    host_config_file = tmp_path / "host_config.json"
    host_config_file.write_text(json.dumps(host_config_data), encoding="utf-8")

    return frozen, frozen_file, host_config_file


def test_synthetic_historical_run_cannot_verify_reconstruction(tmp_path: Path) -> None:
    frozen, frozen_file, host_config_file = _setup_frozen_study(tmp_path)
    run_out = tmp_path / "hist_run_result.json"

    # Step 1: Run historical-run CLI (25 sessions)
    proc_hrun = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "historical-run",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(run_out),
            "--session-count",
            "25",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc_hrun.returncode == 0, (
        f"historical-run failed: {proc_hrun.stderr.decode('utf-8')}"
    )
    assert run_out.exists()

    # Step 2: The generated fixture must remain unqualified diagnostics.
    recon_out = tmp_path / "reconstruction_report.json"
    proc_recon = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "reconstruct",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--run-manifest",
            str(run_out),
            "--output",
            str(recon_out),
        ],
        capture_output=True,
    )
    assert proc_recon.returncode == 2
    assert recon_out.exists()

    report_data = json.loads(recon_out.read_text(encoding="utf-8"))
    assert report_data["status"] == "RECONSTRUCTION_FAILED"
    assert report_data["total_sessions_verified"] == 0
    assert report_data["reconstructed_outcome"] == "UNAVAILABLE"
    assert report_data["uncertainty_verified"] is False
    assert "ORIGINAL_EVIDENCE_UNAUTHENTICATED" in report_data["discrepancies"]


def test_reconstruct_cli_refuses_missing_operating_costs(tmp_path: Path) -> None:
    _, frozen_file, host_config_file = _setup_frozen_study(tmp_path)
    host_data = json.loads(host_config_file.read_text(encoding="utf-8"))
    del host_data["incremental_operating_costs"]
    host_config_file.write_text(json.dumps(host_data), encoding="utf-8")
    output = tmp_path / "reconstruction.json"

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "reconstruct",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(output),
        ],
        capture_output=True,
    )

    assert proc.returncode != 0
    assert b"MISSING_INCREMENTAL_OPERATING_COSTS" in proc.stderr
    assert not output.exists()


def test_reconstruct_cli_negative_control_detects_tampering(tmp_path: Path) -> None:
    frozen, frozen_file, host_config_file = _setup_frozen_study(tmp_path)
    run_out = tmp_path / "hist_run_result.json"

    # Step 1: Run historical-run CLI
    subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "historical-run",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(run_out),
            "--session-count",
            "25",
            "--update-host-config",
        ],
        check=True,
    )

    # Tamper with host_config receipts: alter session 5 terminal NAV
    host_data = json.loads(host_config_file.read_text(encoding="utf-8"))
    for ref in host_data["execution_receipts"]:
        if ref.get("session_index") == 5:
            # Look up receipt in store and tamper
            rid = ref["receipt_id"]
            rcpt = host_data["receipt_store"][rid]
            rcpt["metrics"]["terminal_nav"] = "99999.0000"
            host_data["receipt_store"][rid] = rcpt
            break
    host_config_file.write_text(json.dumps(host_data), encoding="utf-8")

    recon_out = tmp_path / "reconstruction_tampered.json"
    proc_recon = subprocess.run(
        [
            sys.executable,
            "scripts/stage1_study.py",
            "reconstruct",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_config_file),
            "--run-manifest",
            str(run_out),
            "--output",
            str(recon_out),
        ],
        capture_output=True,
    )
    assert proc_recon.returncode == 2
    assert b"Reconstruction failed" in proc_recon.stderr
    assert recon_out.exists()

    report_data = json.loads(recon_out.read_text(encoding="utf-8"))
    assert report_data["status"] == "RECONSTRUCTION_FAILED"
    assert len(report_data["discrepancies"]) > 0
