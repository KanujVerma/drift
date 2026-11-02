"""Integration tests for scripts/stage1_study.py CLI orchestrator."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_cli_inventory(repo_root: Path, tmp_path: Path) -> None:
    script = repo_root / "scripts" / "stage1_study.py"
    out_file = tmp_path / "inventory.json"

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "inventory",
            "--repo-root",
            str(repo_root),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        check=True,
    )
    assert proc.returncode == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "python_version" in data
    assert data["repo_root"] == str(repo_root)


def test_cli_report(repo_root: Path, tmp_path: Path) -> None:
    script = repo_root / "scripts" / "stage1_study.py"
    manifest_file = tmp_path / "manifest.json"
    host_config_file = tmp_path / "host.json"
    out_file = tmp_path / "report.json"

    host_config_file.write_text("{}", encoding="utf-8")
    classification_payload = {
        "schema_version": "drift-stage1-outcome/1",
        "outcome": "UNSUCCESSFUL",
        "primary_economic_advantage": "0",
        "materiality_hurdle": "100",
        "is_invalid": False,
        "is_available": True,
        "is_risk_comparable": True,
        "is_prospective_complete": False,
        "is_independently_accepted": False,
        "reasons": ["ECONOMIC_ADVANTAGE_NON_POSITIVE"],
    }
    from drift.serialization.canonical import content_hash

    classification_payload["classification_hash"] = content_hash(classification_payload)

    manifest_payload = {
        "study_id": "STUDY-CLI-TEST",
        "protocol_hash": "a" * 64,
        "mode": "RETROSPECTIVE",
        "scheduled_sessions": 252,
        "observed_sessions": 252,
        "primary_economic_advantage": "100.0",
        "outcome_classification": classification_payload,
    }

    manifest_file.write_text(json.dumps(manifest_payload), encoding="utf-8")

    proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(manifest_file),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        check=True,
    )
    assert proc.returncode == 0
    report_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert report_data["schema_version"] == "drift-stage1-study-report/1"
    assert report_data["study_id"] == "STUDY-CLI-TEST"


def test_cli_prospective_register_and_step(repo_root: Path, tmp_path: Path) -> None:
    from datetime import UTC, date, datetime

    from drift.experiments.stage1_prospective_study import (
        create_prospective_study_plan,
    )
    from drift.experiments.stage1_study_freeze import REQUIRED_ROLES
    from drift.serialization.canonical import content_hash

    script = repo_root / "scripts" / "stage1_study.py"
    plan_file = tmp_path / "plan.json"
    host_config_file = tmp_path / "host.json"
    private_root = tmp_path / "private"
    private_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    h = "7" * 64
    plan = create_prospective_study_plan(
        plan_id="PROSP-CLI-01",
        created_at=now,
        calendar_identity="XNYS-2026-2027",
        first_eligible_session=date(2026, 11, 3),
        planned_last_session=date(2028, 11, 3),
        operating_environment_hash=h,
        model_binding_hash=h,
        market_admission_hash=h,
        mandate_hash=h,
        cost_policy_hash=h,
    )
    plan_file.write_text(plan.model_dump_json(), encoding="utf-8")

    receipts_store = {}
    evidence = []
    trust_roots = {}
    for role in REQUIRED_ROLES:
        payload = {
            "role": role,
            "receipt_id": f"RCPT-{role}",
            "protocol_hash": plan.plan_hash,
            "authority_id": "trusted-root",
            "status": "ACCEPTED",
        }
        r_hash = content_hash(payload)
        receipts_store[f"RCPT-{role}"] = payload
        evidence.append(
            {
                "role": role,
                "receipt_id": f"RCPT-{role}",
                "receipt_hash": r_hash,
                "protocol_hash": plan.plan_hash,
                "accepted_at": now.isoformat(),
            }
        )
        trust_roots[role] = ["trusted-root"]

    host_config = {
        "trust_roots": trust_roots,
        "receipt_store": receipts_store,
        "evidence": evidence,
        "has_broker": False,
    }
    host_config_file.write_text(json.dumps(host_config), encoding="utf-8")

    # 1. Register
    reg_proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "prospective-register",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_config_file),
            "--private-root",
            str(private_root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert reg_proc.returncode == 0
    reg_file = private_root / f"REG-{plan.plan_id}.json"
    assert reg_file.is_file()
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))
    assert reg_data["registration_id"] == f"REG-{plan.plan_id}"
    assert reg_data["observed_session_count"] == 0

    # 2. Step
    art_store: dict[str, Any] = {}
    art_hashes: dict[str, str] = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": f"REG-{plan.plan_id}",
            "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "trusted-root",
            "execution_payload": {"status": "OK", "step": 0},
        }
        ah = content_hash(art_body)
        art_store[ah] = art_body
        art_hashes[art_name] = ah

    host_config["artifact_store"] = art_store
    host_config["authentic_artifacts"] = list(art_store.keys())
    host_config_file.write_text(json.dumps(host_config), encoding="utf-8")

    ev_body = {
        "schema_version": "drift-stage1-prospective-session-evidence/1",
        "registration_id": f"REG-{plan.plan_id}",
        "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
        "session_index": 0,
        "session_date": "2026-11-03",
        "status": "COMPLETED",
        "evidence_artifacts": art_hashes,
    }
    ev_file = private_root / "step-0-evidence.json"
    ev_file.write_text(
        json.dumps(ev_body | {"evidence_hash": content_hash(ev_body)}), encoding="utf-8"
    )

    step_proc = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "prospective-step",
            "--registration",
            str(reg_file),
            "--host-config",
            str(host_config_file),
            "--private-root",
            str(private_root),
            "--session-date",
            "2026-11-03",
            "--session-evidence",
            str(ev_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert step_proc.returncode == 0
    step_file = private_root / f"REG-{plan.plan_id}-step-1.json"
    assert step_file.is_file()
    step_data = json.loads(step_file.read_text(encoding="utf-8"))
    assert step_data["observed_session_count"] == 1
    assert step_data["last_observed_session"] == "2026-11-03"


def test_cli_calibrate_and_historical_handlers(repo_root: Path, tmp_path: Path) -> None:
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from drift.experiments.stage1_study_artifacts import (
        ORDERED_CALIBRATION_PAIRS,
        create_calibration_attempt_receipt,
        create_development_calibration_plan,
    )
    from drift.experiments.stage1_study_freeze import StudyDateWindowV1

    script = repo_root / "scripts" / "stage1_study.py"
    plan_file = tmp_path / "cal_plan.json"
    host_file = tmp_path / "cal_host.json"
    out_file = tmp_path / "cal_result.json"

    H = "1" * 64
    plan = create_development_calibration_plan(
        plan_id="CAL-CLI-01",
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
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
    plan_file.write_text(plan.model_dump_json(), encoding="utf-8")

    # 1. Calibrate with empty host config exits 2
    host_file.write_text("{}", encoding="utf-8")
    proc_empty = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "calibrate",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc_empty.returncode == 2

    # 2. Calibrate with 9 valid attempts succeeds and outputs winner and proof
    attempts = [
        create_calibration_attempt_receipt(
            attempt_id=f"ATT-{i}",
            pair=pair,
            status="COMPLETED",
            terminal_net_return=Decimal("0.10") + Decimal(f"0.0{i}"),
            absolute_maximum_drawdown=Decimal("0.05"),
            total_gross_turnover=Decimal("0.30"),
            operating_cost=Decimal("0.00"),
        ).model_dump(mode="json")
        for i, pair in enumerate(ORDERED_CALIBRATION_PAIRS)
    ]
    host_file.write_text(json.dumps({"attempts": attempts}), encoding="utf-8")

    proc_ok = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "calibrate",
            "--plan",
            str(plan_file),
            "--host-config",
            str(host_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc_ok.returncode == 0
    res_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert res_data["selected_pair"] is not None
    assert len(res_data["ranking_proof"]) == 9


def test_cli_historical_regression_suite(repo_root: Path, tmp_path: Path) -> None:
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from drift.experiments.stage1_original_acceptance import (
        ProductionStudyEvidenceVerifier,
    )
    from drift.experiments.stage1_study_freeze import (
        REQUIRED_ROLES,
        ConventionalSelectorPolicyV1,
        EvidenceRole,
        Stage1StudyDraftV1,
        StudyCostPolicyV1,
        StudyDateWindowV1,
        StudyEvidenceReferenceV1,
        StudyMandateV1,
        StudyModelPolicyV1,
        StudyStatisticalPolicyV1,
        freeze_study,
    )
    from drift.serialization.canonical import content_hash

    script = repo_root / "scripts" / "stage1_study.py"
    frozen_file = tmp_path / "frozen.json"
    host_file = tmp_path / "hist_host.json"
    out_file = tmp_path / "hist_manifest.json"

    now = datetime(2026, 11, 2, tzinfo=UTC)
    h = "b" * 64
    draft = Stage1StudyDraftV1(
        study_id="STUDY-HIST-CLI-01",
        created_at=now,
        mode="RETROSPECTIVE_DISCOVERY",
        prior_holdout_exposure="UNKNOWN",
        development=StudyDateWindowV1(start=date(2021, 1, 1), end=date(2023, 12, 31)),
        validation=StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        scoring=StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
        installed_source_hash=h,
        dataset_manifest_hash=h,
        calendar_and_universe_hash=h,
        decision_cutoff_policy_hash=h,
        seed_and_replication_policy_hash=h,
        mandate=StudyMandateV1(
            maximum_etf_fraction=Decimal("0.20"),
            maximum_equity_fraction=Decimal("0.70"),
            maximum_bond_fraction=Decimal("0.75"),
            maximum_gold_fraction=Decimal("0.20"),
            maximum_gross_fraction=Decimal("1"),
            maximum_turnover_fraction=Decimal("2"),
            existing_breach_policy_hash=h,
            feasibility_report_hash=h,
        ),
        comparator=ConventionalSelectorPolicyV1(
            formula="R:return-risk-drawdown-switchcost/1",
            volatility_penalty=Decimal("1"),
            drawdown_penalty=Decimal("1"),
            switching_cost_penalty=Decimal("1"),
            development_fit_hash=h,
            executable_formula_hash=h,
        ),
        model=StudyModelPolicyV1(
            provider="synthetic",
            immutable_model_revision="fixture-1",
            model_record_hash=h,
            prompt_hash=h,
            tools_policy_hash=h,
            context_policy_hash=h,
            feedback_policy_hash=h,
            decoding_policy_hash=h,
            seed=0,
            known_training_cutoff=date(2023, 1, 1),
        ),
        costs=StudyCostPolicyV1(trading_model_hash=h, dated_cost_evidence_hash=h),
        statistics=StudyStatisticalPolicyV1(
            alpha=Decimal("0.05"),
            minimum_economic_advantage_fraction=Decimal("0.01"),
            uncertainty_method="STATIONARY_BLOCK_BOOTSTRAP",
            bootstrap_repetitions=1000,
            bootstrap_seed=0,
            block_length_policy_hash=h,
            multiplicity_policy_hash=h,
            stopping_policy_hash=h,
            risk_free_policy_hash=h,
        ),
    )

    receipt_store: dict[str, Any] = {}
    evidence = []
    trust_roots: dict[EvidenceRole, set[str]] = {}
    for role in REQUIRED_ROLES:
        payload = {
            "role": role,
            "receipt_id": f"HIST-RCPT-{role}",
            "protocol_hash": draft.protocol_hash,
            "authority_id": "trusted-historical-root",
            "status": "ACCEPTED",
        }
        r_hash = content_hash(payload)
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
    )
    frozen = freeze_study(
        draft,
        frozen_at=now,
        evidence=tuple(evidence),
        verifier=verifier,
    )
    frozen_file.write_text(frozen.model_dump_json(), encoding="utf-8")

    # 1. Empty host config returns exit 2 (BLOCKED / unavailable)
    host_file.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 2

    # 2. 252-character string for execution_receipts returns exit 3 (invalid input)
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "execution_receipts": "a" * 252,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 3. 252 empty objects for execution_receipts returns exit 3 (freeze_hash mismatch)
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "execution_receipts": [{}] * 252,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    artifact_store: dict[str, Any] = {}

    def make_execution_receipt(
        s_idx: int,
        *,
        authority: str = "trusted-historical-root",
        status: str = "COMPLETED",
        omit_journal: bool = False,
        omit_artifacts: bool = False,
        omit_portfolio_state: bool = False,
        nonhex_hash: bool = False,
        nonexistent_artifact: bool = False,
        mismatched_session: bool = False,
        arbitrary_metrics: bool = False,
        boolean_metric: bool = False,
        tamper_hash: bool = False,
        store_in_receipts: bool = True,
    ) -> dict[str, Any]:
        p_obj = {
            "freeze_hash": frozen.freeze_hash,
            "session_index": 999 if mismatched_session else s_idx,
            "artifact_type": "PORTFOLIO_STATE",
            "cash": "1000000.00",
        }
        p_hash = content_hash(p_obj)
        artifact_store[p_hash] = p_obj

        d_obj = {
            "freeze_hash": frozen.freeze_hash,
            "session_index": s_idx,
            "artifact_type": "DECISION",
            "weights": {"AAPL": "0.10"},
        }
        d_hash = content_hash(d_obj)
        artifact_store[d_hash] = d_obj

        f_obj = {
            "freeze_hash": frozen.freeze_hash,
            "session_index": s_idx,
            "artifact_type": "FILLS",
            "trades": [],
        }
        f_hash = content_hash(f_obj)
        artifact_store[f_hash] = f_obj

        r_id = f"HIST-EXEC-{s_idx}"
        arts: dict[str, Any] = {
            "portfolio_state": (
                "z" * 64
                if nonhex_hash
                else ("f" * 64 if nonexistent_artifact else p_hash)
            ),
            "decision": d_hash,
            "fills": f_hash,
        }
        if omit_portfolio_state:
            del arts["portfolio_state"]
        if omit_artifacts:
            arts = {}

        metrics: dict[str, Any] = {
            "net_return": "0.0005" if not boolean_metric else True,
            "gross_turnover": "0.015",
        }
        if arbitrary_metrics:
            metrics["claimed"] = True

        body = {
            "schema_version": "drift-stage1-execution-receipt/1",
            "receipt_id": r_id,
            "freeze_hash": frozen.freeze_hash,
            "session_index": s_idx,
            "authority_id": authority,
            "status": status,
            "execution_journal": (
                {"session_index": s_idx, "executed_ticks": 390}
                if not omit_journal
                else {}
            ),
            "artifacts": arts,
            "metrics": metrics,
        }
        r_payload = body | {
            "receipt_hash": "e" * 64 if tamper_hash else content_hash(body)
        }
        if store_in_receipts:
            receipt_store[r_id] = r_payload

        return {
            "receipt_id": r_id,
            "session_index": s_idx,
            "receipt_hash": r_payload["receipt_hash"],
        }

    # 3a. Empty execution receipts list returns exit 2 (BLOCKED / unavailable)
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": [],
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 2

    # 4. Incomplete execution receipts (100 sessions < 252) returns exit 4 (INCOMPLETE)
    receipts_100 = [make_execution_receipt(i) for i in range(100)]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": receipts_100,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 4

    # 5. Repeated receipts (252 copies of session_index 0) returns exit 3
    # (duplicate session)
    repeated_receipts = [make_execution_receipt(0)] * 252
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": repeated_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 6. Absent session identity (missing session_index) returns exit 3
    no_session_id = [
        {"receipt_id": f"HIST-EXEC-{i}", "receipt_hash": "a" * 64} for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": no_session_id,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 7. Self-authored receipt (not in receipt_store) returns exit 3
    receipt_store_missing_0 = {
        k: v for k, v in receipt_store.items() if k != "HIST-EXEC-0"
    }
    self_authored_receipts = [
        make_execution_receipt(i, store_in_receipts=(i != 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store_missing_0,
                "artifact_store": artifact_store,
                "execution_receipts": self_authored_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 8. Untrusted authority returns exit 3
    untrusted_auth_receipts = [
        make_execution_receipt(
            i, authority="attacker" if i == 0 else "trusted-historical-root"
        )
        for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": untrusted_auth_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 9. Missing execution journal returns exit 3
    no_journal_receipts = [
        make_execution_receipt(i, omit_journal=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": no_journal_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10a. Missing required artifact (portfolio_state) returns exit 3
    missing_artifact_receipts = [
        make_execution_receipt(i, omit_portfolio_state=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": missing_artifact_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10b. Non-hex artifact hash returns exit 3
    nonhex_receipts = [
        make_execution_receipt(i, nonhex_hash=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": nonhex_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10c. Nonexistent artifact reference returns exit 3
    nonexistent_receipts = [
        make_execution_receipt(i, nonexistent_artifact=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": nonexistent_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10d. Bound session mismatch in artifact object returns exit 3
    mismatched_session_receipts = [
        make_execution_receipt(i, mismatched_session=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": mismatched_session_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10e. Arbitrary unsupported metrics returns exit 3
    arbitrary_metrics_receipts = [
        make_execution_receipt(i, arbitrary_metrics=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": arbitrary_metrics_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 10f. Tampered receipt hash returns exit 3
    tampered_receipts = [
        make_execution_receipt(i, tamper_hash=(i == 0)) for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": tampered_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 11. Out-of-scope session index (e.g. 999 instead of 0..251) returns exit 3
    out_of_scope_receipts = [
        (
            {
                "receipt_id": "HIST-EXEC-999",
                "session_index": 999,
                "receipt_hash": "a" * 64,
            }
            if i == 0
            else make_execution_receipt(i)
        )
        for i in range(252)
    ]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": out_of_scope_receipts,
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc.returncode == 3

    # 12. Complete 252 valid execution receipts returns exit 0 with manifest
    receipts_252 = [make_execution_receipt(i) for i in range(252)]
    host_file.write_text(
        json.dumps(
            {
                "trust_roots": host_trust_roots,
                "receipt_store": receipt_store,
                "artifact_store": artifact_store,
                "execution_receipts": receipts_252,
            }
        ),
        encoding="utf-8",
    )
    proc_ok = subprocess.run(
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
            str(out_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc_ok.returncode == 0
    manifest = json.loads(out_file.read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["observed_sessions"] == 252
    assert manifest["freeze_hash"] == frozen.freeze_hash
