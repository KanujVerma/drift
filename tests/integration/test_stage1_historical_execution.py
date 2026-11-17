"""Integration tests for Stage 1 historical execution producer adapter.

Workstream D, Issue 575.
"""

import json
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from drift.experiments.stage1_economic_costs import create_stage1_cost_model
from drift.experiments.stage1_historical_execution import (
    HistoricalRunConfigV1,
    execute_historical_account_simulation,
    execute_historical_study,
)
from drift.experiments.stage1_mandate_feasibility import (
    create_stage1_study_mandate,
)
from drift.experiments.stage1_original_acceptance import (
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


def test_historical_account_refuses_fabricated_results_without_mutating_stores() -> (
    None
):
    receipts: dict[str, Any] = {"sentinel": {"original": True}}
    artifacts: dict[str, Any] = {"sentinel": {"original": True}}
    with pytest.raises(ValueError, match="HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE"):
        execute_historical_account_simulation(
            freeze_hash=H,
            arm="B",
            session_count=1,
            authority_id="synthetic-only",
            initial_capital=Decimal("10000"),
            cost_model=create_stage1_cost_model(),
            artifact_store=artifacts,
            receipt_store=receipts,
            daily_returns=[Decimal("0.5")],
        )
    assert receipts == {"sentinel": {"original": True}}
    assert artifacts == {"sentinel": {"original": True}}


def test_historical_study_refuses_before_ledger_or_store_mutation(
    tmp_path: Path,
) -> None:
    frozen, _, _ = _create_frozen_study_fixture(tmp_path)
    ledger_dir = tmp_path / "must-not-exist"
    receipts: dict[str, Any] = {"sentinel": {"original": True}}
    artifacts: dict[str, Any] = {"sentinel": {"original": True}}
    with pytest.raises(ValueError, match="HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE"):
        execute_historical_study(
            HistoricalRunConfigV1(
                frozen=frozen, origin_dir=ledger_dir, session_count=1
            ),
            receipt_store=receipts,
            artifact_store=artifacts,
        )
    assert not ledger_dir.exists()
    assert receipts == {"sentinel": {"original": True}}
    assert artifacts == {"sentinel": {"original": True}}


def test_historical_study_preserves_existing_ledger_bytes(tmp_path: Path) -> None:
    frozen, _, _ = _create_frozen_study_fixture(tmp_path)
    ledger_dir = tmp_path / "existing"
    ledger_dir.mkdir()
    ledger = ledger_dir / "b_arm_original.sqlite3"
    ledger.write_bytes(b"synthetic sentinel")

    with pytest.raises(ValueError, match="HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE"):
        execute_historical_study(
            HistoricalRunConfigV1(
                frozen=frozen, origin_dir=ledger_dir, session_count=1
            ),
            receipt_store={},
            artifact_store={},
        )

    assert ledger.read_bytes() == b"synthetic sentinel"
    assert list(ledger_dir.iterdir()) == [ledger]


def test_historical_run_cli_refuses_without_writes(tmp_path: Path) -> None:
    frozen, host_config, _ = _create_frozen_study_fixture(tmp_path)
    frozen_file = tmp_path / "frozen.json"
    host_file = tmp_path / "host.json"
    output = tmp_path / "must-not-exist.json"
    ledger_dir = tmp_path / "must-not-exist-ledgers"
    frozen_file.write_text(frozen.model_dump_json(), encoding="utf-8")
    host_file.write_text(json.dumps(host_config), encoding="utf-8")
    before = host_file.read_bytes()
    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/stage1_study.py",
            "historical-run",
            "--frozen",
            str(frozen_file),
            "--host-config",
            str(host_file),
            "--output",
            str(output),
            "--ledger-dir",
            str(ledger_dir),
            "--session-count",
            "1",
            "--update-host-config",
        ],
        capture_output=True,
    )
    assert proc.returncode != 0
    assert b"HISTORICAL_ORIGINAL_EXECUTION_UNAVAILABLE" in proc.stderr
    assert host_file.read_bytes() == before
    assert not output.exists()
    assert not ledger_dir.exists()


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
