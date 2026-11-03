"""Integration tests for Stage 1 historical execution producer adapter.

Workstream D, Issue 575.
"""

import json
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from drift.experiments.stage1_historical_execution import (
    HistoricalRunConfigV1,
    execute_historical_study,
)
from drift.experiments.stage1_mandate_feasibility import (
    create_stage1_study_mandate,
)
from drift.experiments.stage1_original_acceptance import (
    ProductionExecutionEvidenceVerifier,
    ProductionStudyEvidenceVerifier,
    create_original_study_evidence_receipt,
)
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    ConventionalSelectorPolicyV1,
    EvidenceRole,
    FrozenStage1StudyV1,
    Stage1StudyDraftV1,
    StudyCostPolicyV1,
    StudyDateWindowV1,
    StudyEvidenceReferenceV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
    freeze_study,
)

H = "a" * 64


def _create_frozen_study_fixture(
    tmp_path: Path,
) -> tuple[FrozenStage1StudyV1, dict[str, Any], dict[str, Any]]:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    draft = Stage1StudyDraftV1(
        study_id="STUDY-HIST-EXEC-01",
        created_at=now,
        mode="RETROSPECTIVE_DISCOVERY",
        prior_holdout_exposure="UNKNOWN",
        development=StudyDateWindowV1(start=date(2021, 1, 1), end=date(2023, 12, 31)),
        validation=StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        scoring=StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        decision_cutoff_policy_hash=H,
        seed_and_replication_policy_hash=H,
        mandate=create_stage1_study_mandate(feasibility_report_hash=H),
        comparator=ConventionalSelectorPolicyV1(
            formula="R:return-risk-drawdown-switchcost/1",
            volatility_penalty=Decimal("1"),
            drawdown_penalty=Decimal("1"),
            switching_cost_penalty=Decimal("1"),
            development_fit_hash=H,
            executable_formula_hash=H,
        ),
        model=StudyModelPolicyV1(
            provider="synthetic",
            immutable_model_revision="fixture-1",
            model_record_hash=H,
            prompt_hash=H,
            tools_policy_hash=H,
            context_policy_hash=H,
            feedback_policy_hash=H,
            decoding_policy_hash=H,
            seed=0,
            known_training_cutoff=date(2023, 1, 1),
        ),
        costs=StudyCostPolicyV1(trading_model_hash=H, dated_cost_evidence_hash=H),
        statistics=StudyStatisticalPolicyV1(
            alpha=Decimal("0.05"),
            minimum_economic_advantage_fraction=Decimal("0.01"),
            uncertainty_method="STATIONARY_BLOCK_BOOTSTRAP",
            bootstrap_repetitions=1000,
            bootstrap_seed=0,
            block_length_policy_hash=H,
            multiplicity_policy_hash=H,
            stopping_policy_hash=H,
            risk_free_policy_hash=H,
        ),
    )

    receipt_store: dict[str, Any] = {}
    evidence = []
    trust_roots: dict[EvidenceRole, set[str]] = {}
    for role in REQUIRED_ROLES:
        payload, r_hash = create_original_study_evidence_receipt(
            role=role,
            receipt_id=f"HIST-RCPT-{role}",
            protocol_hash=draft.protocol_hash,
            authority_id="trusted-historical-root",
            accepted_at=now,
            status="ACCEPTED",
            hmac_key="hist-secret",
        )
        receipt_store[f"HIST-RCPT-{role}"] = payload
        evidence.append(
            StudyEvidenceReferenceV1(
                role=role,
                receipt_id=f"HIST-RCPT-{role}",
                receipt_hash=r_hash,
                protocol_hash=draft.protocol_hash,
                accepted_at=now,
            )
        )
        trust_roots[role] = {"trusted-historical-root"}

    host_trust_roots = {role: list(roots) for role, roots in trust_roots.items()}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots=trust_roots,
        receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        authenticated_issuers={"trusted-historical-root": {"hmac_key": "hist-secret"}},
    )
    frozen = freeze_study(
        draft,
        frozen_at=now,
        evidence=tuple(evidence),
        verifier=verifier,
    )
    host_config = {
        "trust_roots": host_trust_roots,
        "receipt_store": receipt_store,
        "artifact_store": {},
        "authenticated_issuers": {
            "trusted-historical-root": {"hmac_key": "hist-secret"}
        },
    }
    return frozen, host_config, receipt_store


def test_execute_historical_study_produces_verifiable_evidence(tmp_path: Path) -> None:
    frozen, host_config, receipt_store = _create_frozen_study_fixture(tmp_path)
    artifact_store: dict[str, Any] = {}

    config = HistoricalRunConfigV1(
        frozen=frozen,
        origin_dir=tmp_path / "ledgers",
        session_count=20,
        authority_id="trusted-historical-root",
        initial_capital=Decimal("10000"),
        incremental_operating_costs=Decimal("15.00"),
    )

    result = execute_historical_study(
        config,
        receipt_store=receipt_store,
        artifact_store=artifact_store,
    )

    assert result.status == "COMPLETED"
    assert result.executed_sessions_count == 20
    assert len(result.candidate_receipt_refs) == 20
    assert len(result.reference_receipt_refs) == 20
    assert result.b_terminal_nav > Decimal("10000")
    assert result.r_terminal_nav > Decimal("10000")
    assert result.primary_economic_advantage.is_finite()

    # Verify that SQLite ledgers were created and populated
    assert Path(result.ledger_paths["ARM-B"]).exists()
    assert Path(result.ledger_paths["ARM-R"]).exists()

    # Verify that execution evidence verifier accepts candidate & ref receipts
    exec_verifier = ProductionExecutionEvidenceVerifier(
        trust_roots={"trusted-historical-root"},
        receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        artifact_resolver=lambda aid: artifact_store.get(aid, {}),
    )

    for ref in result.candidate_receipt_refs:
        ok, reason, payload = exec_verifier.verify_execution_receipt(
            ref,
            expected_freeze_hash=frozen.freeze_hash,
            expected_session_index=ref["session_index"],
        )
        assert ok, f"Candidate receipt failed: {reason}"
        assert payload is not None
        assert payload["arm"] == "B"

    for ref in result.reference_receipt_refs:
        ok, reason, payload = exec_verifier.verify_execution_receipt(
            ref,
            expected_freeze_hash=frozen.freeze_hash,
            expected_session_index=ref["session_index"],
        )
        assert ok, f"Reference receipt failed: {reason}"
        assert payload is not None
        assert payload["arm"] == "R"


def test_historical_run_cli_and_historical_verifier_pipeline(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "scripts" / "stage1_study.py"

    frozen, host_config, receipt_store = _create_frozen_study_fixture(tmp_path)
    frozen_file = tmp_path / "frozen.json"
    host_file = tmp_path / "host.json"
    run_out_file = tmp_path / "run_result.json"
    verify_out_file = tmp_path / "verify_result.json"

    frozen_file.write_text(frozen.model_dump_json(), encoding="utf-8")
    host_file.write_text(json.dumps(host_config), encoding="utf-8")

    # Step 1: Execute historical run with 15 sessions via CLI
    proc_run = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "historical-run",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_file),
            "--output",
            str(run_out_file),
            "--session-count",
            "15",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc_run.returncode == 0, (
        f"historical-run failed: {proc_run.stderr.decode('utf-8')}"
    )
    assert run_out_file.exists()

    run_manifest = json.loads(run_out_file.read_text(encoding="utf-8"))
    assert run_manifest["status"] == "COMPLETED"
    assert run_manifest["executed_sessions_count"] == 15

    # Verify host_config was updated with receipts
    updated_host = json.loads(host_file.read_text(encoding="utf-8"))
    assert len(updated_host["execution_receipts"]) == 15
    assert len(updated_host["reference_execution_receipts"]) == 15
    assert "incremental_operating_costs" in updated_host

    # Step 2: Feed updated host_config into the historical verifier
    # Set scheduled_sessions to 15 so historical verifier matches
    updated_host["scheduled_sessions"] = 15
    host_file.write_text(json.dumps(updated_host), encoding="utf-8")

    proc_verify = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "historical",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_file),
            "--output",
            str(verify_out_file),
        ],
        capture_output=True,
    )
    assert proc_verify.returncode == 0, (
        f"historical verify failed: {proc_verify.stderr.decode('utf-8')}"
    )
    assert verify_out_file.exists()

    verify_manifest = json.loads(verify_out_file.read_text(encoding="utf-8"))
    assert verify_manifest["status"] == "COMPLETED"
    assert verify_manifest["observed_sessions"] == 15
    assert verify_manifest["scheduled_sessions"] == 15
