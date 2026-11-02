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

    valid_host_config = {
        "trust_roots": {
            "scientific_protocol_review": ["trusted-root"],
        }
    }
    host_config_file.write_text(json.dumps(valid_host_config), encoding="utf-8")
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
        "evidence_inventory": ["HIST-RCPT-001"],
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

    # Adversarial checks for Finding 3
    # 1. Missing host verification trust roots -> exits 2
    empty_host = tmp_path / "empty_host.json"
    empty_host.write_text("{}", encoding="utf-8")
    proc_no_host = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(manifest_file),
            "--host-config",
            str(empty_host),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc_no_host.returncode == 2

    # 2. Zero observed sessions -> exits 3
    zero_manifest = tmp_path / "zero_manifest.json"
    zero_manifest.write_text(
        json.dumps(manifest_payload | {"observed_sessions": 0}), encoding="utf-8"
    )
    proc_zero = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(zero_manifest),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc_zero.returncode == 3

    # 3. All-zero protocol hash -> exits 3
    all_zero_proto = tmp_path / "all_zero_proto.json"
    all_zero_proto.write_text(
        json.dumps(manifest_payload | {"protocol_hash": "0" * 64}), encoding="utf-8"
    )
    proc_all_zero = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(all_zero_proto),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc_all_zero.returncode == 3

    # 4. Manufactured SUCCESS with negative economic advantage and zero evidence
    # -> exits 3
    manuf_class = {
        "schema_version": "drift-stage1-outcome/1",
        "outcome": "SUCCESS",
        "primary_economic_advantage": "-999.0",
        "materiality_hurdle": "100",
        "is_invalid": False,
        "is_available": True,
        "is_risk_comparable": True,
        "is_prospective_complete": True,
        "is_independently_accepted": True,
        "reasons": [],
    }
    manuf_class["classification_hash"] = content_hash(manuf_class)
    manuf_manifest = tmp_path / "manuf_manifest.json"
    manuf_manifest.write_text(
        json.dumps(
            {
                "study_id": "MANUFACTURED",
                "protocol_hash": "0" * 64,
                "scheduled_sessions": 252,
                "observed_sessions": 0,
                "primary_economic_advantage": "-999.0",
                "outcome_classification": manuf_class,
                "evidence_inventory": [],
            }
        ),
        encoding="utf-8",
    )
    proc_manuf = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "report",
            "--run-manifest",
            str(manuf_manifest),
            "--host-config",
            str(host_config_file),
            "--output",
            str(out_file),
        ],
        capture_output=True,
    )
    assert proc_manuf.returncode == 3


def test_cli_prospective_register_and_step(repo_root: Path, tmp_path: Path) -> None:
    from datetime import UTC, date, datetime

    from drift.experiments.stage1_original_acceptance import (
        create_original_study_evidence_receipt,
    )
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
        payload, r_hash = create_original_study_evidence_receipt(
            role=role,
            receipt_id=f"RCPT-{role}",
            protocol_hash=plan.plan_hash,
            authority_id="trusted-root",
            accepted_at=now,
            status="ACCEPTED",
            hmac_key="cli-test-secret",
        )
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
        "authenticated_issuers": {"trusted-root": {"hmac_key": "cli-test-secret"}},
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
    typed_payloads = {
        "portfolio_state": {
            "nav": "100000.00",
            "cash": "100000.00",
            "positions": {},
        },
        "decision": {
            "strategy_id": "drift-allocator",
            "allocations": {"SPY": "0.5"},
        },
        "fills": {
            "orders": [],
            "fills": [],
        },
    }
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": f"REG-{plan.plan_id}",
            "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "trusted-root",
            "execution_payload": typed_payloads[art_name],
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


def test_cli_prospective_step_adversarial_authentication_enforcement(
    repo_root: Path, tmp_path: Path
) -> None:
    from datetime import UTC, date, datetime

    from drift.experiments.stage1_original_acceptance import (
        create_original_study_evidence_receipt,
    )
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
    h = "8" * 64
    plan = create_prospective_study_plan(
        plan_id="PROSP-CLI-ADV-01",
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
        payload, r_hash = create_original_study_evidence_receipt(
            role=role,
            receipt_id=f"RCPT-ADV-{role}",
            protocol_hash=plan.plan_hash,
            authority_id="trusted-root",
            accepted_at=now,
            status="ACCEPTED",
            hmac_key="adv-secret",
        )
        receipts_store[f"RCPT-ADV-{role}"] = payload
        evidence.append(
            {
                "role": role,
                "receipt_id": f"RCPT-ADV-{role}",
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
        "authenticated_issuers": {"trusted-root": {"hmac_key": "adv-secret"}},
        "has_broker": False,
    }
    host_config_file.write_text(json.dumps(host_config), encoding="utf-8")

    # 1. Register prospective study
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
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))

    # Prepare store artifacts with typed execution payloads
    art_store: dict[str, Any] = {}
    art_hashes: dict[str, str] = {}
    typed_payloads = {
        "portfolio_state": {
            "nav": "100000.00",
            "cash": "100000.00",
            "positions": {},
        },
        "decision": {
            "strategy_id": "drift-adv",
            "allocations": {},
        },
        "fills": {
            "orders": [],
            "fills": [],
        },
    }
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": f"REG-{plan.plan_id}",
            "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "trusted-root",
            "execution_payload": typed_payloads[art_name],
        }
        ah = content_hash(art_body)
        art_store[ah] = art_body
        art_hashes[art_name] = ah

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

    # Base valid host config for stepping (with study admission auth roots)
    base_step_host = {
        "trust_roots": trust_roots,
        "receipt_store": receipts_store,
        "authenticated_issuers": {"trusted-root": {"hmac_key": "adv-secret"}},
        "has_broker": False,
    }

    # Adversarial Case 1: CLI treats store membership as authentication when
    # authentication config is absent.
    # The adversary supplies artifact_store, but omits authentic_artifacts /
    # authenticated_producers.
    # Must fail closed with exit code 3.
    host_config_no_auth = base_step_host | {
        "artifact_store": art_store,
    }
    host_config_file.write_text(json.dumps(host_config_no_auth), encoding="utf-8")
    proc_no_auth = subprocess.run(
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
    )
    assert proc_no_auth.returncode == 3
    assert "authentication evidence" in proc_no_auth.stderr

    # Adversarial Case 2: Config provides empty authentication mechanisms.
    # Must fail closed with exit code 3 (PRODUCER_AUTHENTICATION_MECHANISM_REQUIRED).
    host_config_empty_auth = base_step_host | {
        "artifact_store": art_store,
        "authentic_artifacts": [],
    }
    host_config_file.write_text(json.dumps(host_config_empty_auth), encoding="utf-8")
    proc_empty_auth = subprocess.run(
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
    )
    assert proc_empty_auth.returncode == 3
    assert "PRODUCER_AUTHENTICATION_MECHANISM_REQUIRED" in proc_empty_auth.stderr

    # Adversarial Case 3: Artifact exists in store with matching authority and hash,
    # but is omitted from configured authentic_artifacts.
    # Must fail closed with exit code 3 (PRODUCER_AUTHENTICATION_FAILED).
    host_config_unauth = base_step_host | {
        "artifact_store": art_store,
        "authentic_artifacts": [
            art_hashes["portfolio_state"]
        ],  # decision & fills omitted
    }
    host_config_file.write_text(json.dumps(host_config_unauth), encoding="utf-8")
    proc_unauth = subprocess.run(
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
    )
    assert proc_unauth.returncode == 3
    assert "PRODUCER_AUTHENTICATION_FAILED" in proc_unauth.stderr

    # Adversarial Case 4: Config supplies truthy producer allowlisting without
    # authentication credentials (e.g. {"trusted-root": True}).
    # Must fail closed with exit code 3 (INVALID_PRODUCER_CREDENTIALS).
    host_config_truthy_prod = base_step_host | {
        "artifact_store": art_store,
        "authenticated_producers": {"trusted-root": True},
    }
    host_config_file.write_text(json.dumps(host_config_truthy_prod), encoding="utf-8")
    proc_truthy_prod = subprocess.run(
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
    )
    assert proc_truthy_prod.returncode == 3
    assert "INVALID_PRODUCER_CREDENTIALS" in proc_truthy_prod.stderr

    # Adversarial Case 5: Config supplies static bearer tokens without
    # canonical content verification (e.g. {"tokens": ["foo"]}).
    # Must fail closed with exit code 3 (INVALID_PRODUCER_CREDENTIALS).
    host_config_static_tokens = base_step_host | {
        "artifact_store": art_store,
        "authenticated_producers": {"trusted-root": {"tokens": ["bearer-token"]}},
    }
    host_config_file.write_text(json.dumps(host_config_static_tokens), encoding="utf-8")
    proc_static_tokens = subprocess.run(
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
    )
    assert proc_static_tokens.returncode == 3
    assert "INVALID_PRODUCER_CREDENTIALS" in proc_static_tokens.stderr

    # Adversarial Case 6 (Finding 7): Broker capability refusal on stepping
    host_config_broker = base_step_host | {
        "artifact_store": art_store,
        "authentic_artifacts": list(art_store.keys()),
        "has_broker": True,
    }
    host_config_file.write_text(json.dumps(host_config_broker), encoding="utf-8")
    proc_broker = subprocess.run(
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
    )
    assert proc_broker.returncode == 2
    assert "BROKER_CAPABILITY_REFUSAL" in proc_broker.stderr

    # Adversarial Case 7 (Finding 4): Unauthenticated study admission receipts
    # If host lacks the receipt or credentials, stepping is refused with exit code 2
    host_config_no_admission = {
        "trust_roots": trust_roots,
        "receipt_store": {},  # Missing receipts
        "artifact_store": art_store,
        "authentic_artifacts": list(art_store.keys()),
        "has_broker": False,
    }
    host_config_file.write_text(json.dumps(host_config_no_admission), encoding="utf-8")
    proc_no_adm = subprocess.run(
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
    )
    assert proc_no_adm.returncode == 2
    assert "STUDY_ADMISSION_REFUSED" in proc_no_adm.stderr

    # Adversarial Case 8 (Finding 5): Calendar advancement skipping to Christmas Day
    jump_art_store: dict[str, Any] = {}
    jump_art_hashes: dict[str, str] = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": f"REG-{plan.plan_id}",
            "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
            "session_index": 0,
            "session_date": "2026-12-25",
            "authority_id": "trusted-root",
            "execution_payload": typed_payloads[art_name],
        }
        ah = content_hash(art_body)
        jump_art_store[ah] = art_body
        jump_art_hashes[art_name] = ah

    jump_ev_body = {
        "schema_version": "drift-stage1-prospective-session-evidence/1",
        "registration_id": f"REG-{plan.plan_id}",
        "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
        "session_index": 0,
        "session_date": "2026-12-25",
        "status": "COMPLETED",
        "evidence_artifacts": jump_art_hashes,
    }
    jump_ev_file = private_root / "step-jump-evidence.json"
    jump_ev_file.write_text(
        json.dumps(jump_ev_body | {"evidence_hash": content_hash(jump_ev_body)}),
        encoding="utf-8",
    )
    valid_step_host = base_step_host | {
        "artifact_store": jump_art_store,
        "authentic_artifacts": list(jump_art_store.keys()),
    }
    host_config_file.write_text(json.dumps(valid_step_host), encoding="utf-8")
    proc_calendar_jump = subprocess.run(
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
            "2026-12-25",  # Christmas Day instead of scheduled 2026-11-03
            "--session-evidence",
            str(jump_ev_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_calendar_jump.returncode == 3
    assert "SESSION_DATE_NOT_SEQUENTIAL" in proc_calendar_jump.stderr

    # Adversarial Case 9 (Round 18 Finding): Recovery refuses fabricated step
    # state with correctly recomputed registration_hash
    fab_body = reg_data.copy()
    fab_body["observed_session_count"] = 1
    fab_body["last_observed_session"] = "2026-11-03"
    fab_body["prior_step_hash"] = reg_data["registration_hash"]
    fab_body["last_evidence_hash"] = "9" * 64
    fab_body["evidence_chain"] = ["9" * 64]
    del fab_body["registration_hash"]
    fab_h = content_hash(fab_body)
    fab_step_file = private_root / f"REG-{plan.plan_id}-step-1.json"
    fab_step_file.write_text(
        json.dumps(fab_body | {"registration_hash": fab_h}), encoding="utf-8"
    )

    # 9a. Fabricated step with mismatched replayed state / evidence -> rejected
    host_config_file.write_text(json.dumps(valid_step_host), encoding="utf-8")
    proc_fab_no_ev = subprocess.run(
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
            "2026-11-04",
            "--session-evidence",
            str(ev_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_fab_no_ev.returncode == 3
    assert "RECOVERY_VERIFICATION_FAILED" in proc_fab_no_ev.stderr

    # 9b. Fabricated step with unauthenticated artifacts -> rejected
    fake_ev_body = {
        "schema_version": "drift-stage1-prospective-session-evidence/1",
        "registration_id": f"REG-{plan.plan_id}",
        "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
        "session_index": 0,
        "session_date": "2026-11-03",
        "status": "COMPLETED",
        "evidence_artifacts": {
            "portfolio_state": "e" * 64,
            "decision": "e" * 64,
            "fills": "e" * 64,
        },
    }
    fake_ev_file = private_root / f"REG-{plan.plan_id}-evidence-1.json"
    fake_ev_file.write_text(
        json.dumps(fake_ev_body | {"evidence_hash": content_hash(fake_ev_body)}),
        encoding="utf-8",
    )
    proc_fake_art = subprocess.run(
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
            "2026-11-04",
            "--session-evidence",
            str(ev_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_fake_art.returncode == 3
    assert "RECOVERY_VERIFICATION_FAILED" in proc_fake_art.stderr

    # 9c. Fabricated step altering frozen study bindings -> rejected
    tampered_freeze_body = fab_body.copy()
    tampered_frozen = reg_data["frozen_study"].copy()
    tampered_frozen["freeze_hash"] = "0" * 64
    tampered_freeze_body["frozen_study"] = tampered_frozen
    tf_h = content_hash(tampered_freeze_body)
    fab_step_file.write_text(
        json.dumps(tampered_freeze_body | {"registration_hash": tf_h}),
        encoding="utf-8",
    )
    proc_tf = subprocess.run(
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
            "2026-11-04",
            "--session-evidence",
            str(ev_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc_tf.returncode == 3
    assert "RECOVERY_VERIFICATION_FAILED" in proc_tf.stderr

    # Clean up fabricated artifacts
    fab_step_file.unlink(missing_ok=True)
    fake_ev_file.unlink(missing_ok=True)


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
        create_original_study_evidence_receipt,
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

    artifact_store: dict[str, Any] = {}

    def write_host_config(extra: dict[str, Any]) -> None:
        cfg = {
            "trust_roots": host_trust_roots,
            "receipt_store": receipt_store,
            "artifact_store": artifact_store,
            "authenticated_issuers": {
                "trusted-historical-root": {"hmac_key": "hist-secret"}
            },
        }
        cfg.update(extra)
        host_file.write_text(json.dumps(cfg), encoding="utf-8")

    # 2. 252-character string for execution_receipts returns exit 3 (invalid input)
    write_host_config({"execution_receipts": "a" * 252})
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
    write_host_config({"execution_receipts": [{}] * 252})
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
            "artifact_role": "portfolio_state",
            "authority_id": authority,
            "nav": "1000000.00",
            "cash": "1000000.00",
            "positions": {},
        }
        p_hash = content_hash(p_obj)
        artifact_store[p_hash] = p_obj

        d_obj = {
            "freeze_hash": frozen.freeze_hash,
            "session_index": s_idx,
            "artifact_role": "decision",
            "authority_id": authority,
            "strategy_id": "historical-allocator",
            "weights": {"AAPL": "0.10"},
        }
        d_hash = content_hash(d_obj)
        artifact_store[d_hash] = d_obj

        f_obj = {
            "freeze_hash": frozen.freeze_hash,
            "session_index": s_idx,
            "artifact_role": "fills",
            "authority_id": authority,
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
            "terminal_nav": "1000000.00",
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
    write_host_config({"execution_receipts": []})
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
    write_host_config({"execution_receipts": receipts_100})
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
    write_host_config({"execution_receipts": repeated_receipts})
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
    write_host_config({"execution_receipts": no_session_id})
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
    write_host_config(
        {
            "receipt_store": receipt_store_missing_0,
            "execution_receipts": self_authored_receipts,
        }
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
    write_host_config({"execution_receipts": untrusted_auth_receipts})
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
    write_host_config({"execution_receipts": no_journal_receipts})
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
    write_host_config({"execution_receipts": missing_artifact_receipts})
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
    write_host_config({"execution_receipts": nonhex_receipts})
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
    write_host_config({"execution_receipts": nonexistent_receipts})
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
    write_host_config({"execution_receipts": mismatched_session_receipts})
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
    write_host_config({"execution_receipts": arbitrary_metrics_receipts})
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
    write_host_config({"execution_receipts": tampered_receipts})
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
    write_host_config({"execution_receipts": out_of_scope_receipts})
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
    write_host_config({"execution_receipts": receipts_252})
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


def test_cli_prospective_step_concurrent_writers_serialization(
    repo_root: Path, tmp_path: Path
) -> None:
    """Test concurrent prospective steps serialization per registration (Round 19).

    Two concurrent invocations targeting the same step cannot interleave, overwrite
    evidence, or leave mismatched files. Exactly one succeeds; the duplicate is
    rejected with exit code 3. Subsequent recovery and sequential stepping succeed.
    """
    import concurrent.futures
    from datetime import UTC, date, datetime

    from drift.experiments.stage1_original_acceptance import (
        create_original_study_evidence_receipt,
    )
    from drift.experiments.stage1_prospective_study import (
        create_prospective_study_plan,
    )
    from drift.experiments.stage1_study_freeze import REQUIRED_ROLES
    from drift.serialization.canonical import content_hash

    script = repo_root / "scripts" / "stage1_study.py"
    private_root = tmp_path / "private_root"
    private_root.mkdir(parents=True, exist_ok=True)
    plan_file = tmp_path / "plan.json"
    reg_host_file = tmp_path / "reg_host.json"
    host_config_file = tmp_path / "host_config.json"

    now = datetime(2026, 11, 2, tzinfo=UTC)
    h = "8" * 64
    plan = create_prospective_study_plan(
        plan_id="PROSP-CONC-01",
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

    receipts_store: dict[str, Any] = {}
    evidence = []
    trust_roots: dict[str, list[str]] = {}
    for role in REQUIRED_ROLES:
        rcpt_body, r_hash = create_original_study_evidence_receipt(
            role=role,
            receipt_id=f"CONC-RCPT-{role}",
            protocol_hash=plan.plan_hash,
            authority_id="trusted-root",
            accepted_at=now,
            status="ACCEPTED",
            hmac_key="conc-secret",
        )
        receipts_store[f"CONC-RCPT-{role}"] = rcpt_body
        evidence.append(
            {
                "role": role,
                "receipt_id": f"CONC-RCPT-{role}",
                "receipt_hash": r_hash,
                "protocol_hash": plan.plan_hash,
                "accepted_at": now.isoformat(),
            }
        )
        trust_roots[role] = ["trusted-root"]

    reg_host = {
        "trust_roots": trust_roots,
        "receipt_store": receipts_store,
        "evidence": evidence,
        "authenticated_issuers": {"trusted-root": {"hmac_key": "conc-secret"}},
        "has_broker": False,
    }
    reg_host_file.write_text(json.dumps(reg_host), encoding="utf-8")

    # 1. Register prospective study
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
            str(reg_host_file),
            "--private-root",
            str(private_root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert reg_proc.returncode == 0
    reg_file = private_root / f"REG-{plan.plan_id}.json"
    reg_data = json.loads(reg_file.read_text(encoding="utf-8"))

    art_store: dict[str, Any] = {}

    def make_evidence(s_idx: int, s_date: str) -> Path:
        hashes = {}
        for role, payload in (
            (
                "portfolio_state",
                {"nav": "100000.00", "cash": "100000.00", "positions": {}},
            ),
            ("decision", {"strategy_id": "s1", "allocations": {}}),
            ("fills", {"orders": [], "fills": []}),
        ):
            full_art = {
                "schema_version": "drift-stage1-prospective-artifact/1",
                "artifact_role": role,
                "registration_id": f"REG-{plan.plan_id}",
                "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
                "session_index": s_idx,
                "session_date": s_date,
                "authority_id": "trusted-root",
                "execution_payload": payload,
            }
            h = content_hash(full_art)
            art_store[h] = full_art
            hashes[role] = h

        ev_body = {
            "schema_version": "drift-stage1-prospective-session-evidence/1",
            "registration_id": f"REG-{plan.plan_id}",
            "freeze_hash": reg_data["frozen_study"]["freeze_hash"],
            "session_index": s_idx,
            "session_date": s_date,
            "status": "COMPLETED",
            "evidence_artifacts": hashes,
        }
        ev_f = private_root / f"conc-step-{s_idx}-evidence.json"
        ev_f.write_text(
            json.dumps(ev_body | {"evidence_hash": content_hash(ev_body)}),
            encoding="utf-8",
        )
        return ev_f

    ev_file_1 = make_evidence(0, "2026-11-03")
    ev_file_2 = make_evidence(1, "2026-11-04")

    host_cfg = {
        "trust_roots": trust_roots,
        "receipt_store": receipts_store,
        "authenticated_issuers": {"trusted-root": {"hmac_key": "conc-secret"}},
        "artifact_store": art_store,
        "authentic_artifacts": list(art_store.keys()),
        "has_broker": False,
    }
    host_config_file.write_text(json.dumps(host_cfg), encoding="utf-8")

    def run_worker(s_date: str, ev_p: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
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
                s_date,
                "--session-evidence",
                str(ev_p),
            ],
            capture_output=True,
            text=True,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_worker, "2026-11-03", ev_file_1)
        f2 = executor.submit(run_worker, "2026-11-03", ev_file_1)
        res1 = f1.result()
        res2 = f2.result()

    results = [res1, res2]
    returncodes = sorted(r.returncode for r in results)
    assert returncodes == [0, 3], (
        f"Expected [0, 3], got {returncodes}.\n"
        f"Output 1: {res1.stderr}\nOutput 2: {res2.stderr}"
    )

    step_files = list(private_root.glob(f"REG-{plan.plan_id}-step-*.json"))
    ev_files = list(private_root.glob(f"REG-{plan.plan_id}-evidence-*.json"))
    assert len(step_files) == 1
    assert len(ev_files) == 1

    s1_data = json.loads(step_files[0].read_text(encoding="utf-8"))
    assert s1_data["observed_session_count"] == 1
    assert s1_data["last_observed_session"] == "2026-11-03"

    res_step2 = run_worker("2026-11-04", ev_file_2)
    assert res_step2.returncode == 0, f"Step 2 failed: {res_step2.stderr}"

    step_files_2 = sorted(private_root.glob(f"REG-{plan.plan_id}-step-*.json"))
    ev_files_2 = sorted(private_root.glob(f"REG-{plan.plan_id}-evidence-*.json"))
    assert len(step_files_2) == 2
    assert len(ev_files_2) == 2

    s2_data = json.loads(step_files_2[1].read_text(encoding="utf-8"))
    assert s2_data["observed_session_count"] == 2
    assert s2_data["last_observed_session"] == "2026-11-04"
