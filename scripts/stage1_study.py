#!/usr/bin/env python3
"""Stage 1 Study CLI orchestrator.

Implements declared actions:
- inventory
- assess
- calibrate
- freeze
- verify-freeze
- historical
- report
- prospective-register
- prospective-step

Exits:
0 = action completed as specified (including valid negative outcome)
2 = unmet dependency / admission / permission
3 = invalid or tampered input
4 = contained incomplete runtime execution
1 = unexpected implementation failure
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_prospective_study import (
    ProspectiveRegistrationV1,
    ProspectiveStudyPlanV1,
    advance_prospective_session,
    assess_prospective_readiness,
    freeze_prospective_study,
    register_prospective_study,
)
from drift.experiments.stage1_study_artifacts import (
    ORDERED_CALIBRATION_PAIRS,
    CalibrationAttemptReceiptV1,
    DevelopmentCalibrationPlanV1,
    calibration_ranking_key,
    compute_ranking_proof,
    create_calibration_result,
)
from drift.experiments.stage1_study_freeze import (
    FrozenStage1StudyV1,
    Stage1StudyDraftV1,
    StudyEvidenceReferenceV1,
    assess_study_readiness,
    freeze_study,
    verify_frozen_study,
)
from drift.experiments.stage1_study_outcomes import StudyOutcomeClassificationV1
from drift.experiments.stage1_study_report import create_study_report
from drift.experiments.stage1_uncertainty import PairedUncertaintyArtifactV1


def _write_output(path_str: str, data: dict[str, Any] | str) -> None:
    p = Path(path_str).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
    p.write_text(text, encoding="utf-8")


def _read_json(path_str: str) -> dict[str, Any]:
    p = Path(path_str).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path_str}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON dict, got {type(data)}")
    return data


def action_inventory(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    installed = {
        "python_version": sys.version,
        "repo_root": str(repo_root),
        "checked_at": datetime.now(UTC).isoformat(),
    }
    _write_output(args.output, installed)
    return 0


def action_assess(args: argparse.Namespace) -> int:
    try:
        draft_data = _read_json(args.draft)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        draft = Stage1StudyDraftV1.model_validate_json(json.dumps(draft_data))
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        evidence = tuple(
            StudyEvidenceReferenceV1.model_validate_json(json.dumps(r))
            for r in host_config.get("evidence", [])
        )
        now = datetime.now(UTC)
        readiness = assess_study_readiness(
            draft, evidence=evidence, verifier=verifier, as_of=now
        )
        _write_output(args.output, readiness.model_dump(mode="json"))
        return 0 if readiness.status != "BLOCKED" else 2
    except Exception as e:
        sys.stderr.write(f"Assessment failed: {e}\n")
        return 1


def action_calibrate(args: argparse.Namespace) -> int:
    try:
        plan_data = _read_json(args.plan)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        plan = DevelopmentCalibrationPlanV1.model_validate_json(json.dumps(plan_data))
        attempts_data = host_config.get("attempts", [])
        if not attempts_data:
            sys.stderr.write("No attempts provided in host_config\n")
            return 2
        attempts = tuple(
            CalibrationAttemptReceiptV1.model_validate_json(json.dumps(a))
            for a in attempts_data
        )
        completed = [a for a in attempts if a.status == "COMPLETED"]
        completed_pairs = {a.pair for a in completed}
        if completed_pairs != set(ORDERED_CALIBRATION_PAIRS):
            sys.stderr.write(
                f"Calibration incomplete: expected 9 pairs, "
                f"got {len(completed_pairs)}\n"
            )
            return 2

        ranked = sorted(completed, key=calibration_ranking_key)
        winner = ranked[0]
        ranking_proof = compute_ranking_proof(ranked)

        res = create_calibration_result(
            plan_hash=plan.plan_hash,
            completed_at=datetime.now(UTC),
            attempts=attempts,
            selected_pair=winner.pair,
            selected_pair_receipt_hash=winner.receipt_hash,
            ranking_proof=ranking_proof,
        )
        _write_output(args.output, res.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Calibration failed: {e}\n")
        return 1


def action_freeze(args: argparse.Namespace) -> int:
    try:
        draft_data = _read_json(args.draft)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        draft = Stage1StudyDraftV1.model_validate_json(json.dumps(draft_data))
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        evidence = tuple(
            StudyEvidenceReferenceV1.model_validate_json(json.dumps(r))
            for r in host_config.get("evidence", [])
        )
        now = datetime.now(UTC)
        frozen = freeze_study(
            draft,
            frozen_at=now,
            evidence=evidence,
            verifier=verifier,
        )
        _write_output(args.output, frozen.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Freeze failed: {e}\n")
        return 1


def action_verify_freeze(args: argparse.Namespace) -> int:
    try:
        freeze_data = _read_json(args.freeze)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        frozen = FrozenStage1StudyV1.model_validate_json(json.dumps(freeze_data))
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        report = verify_frozen_study(frozen, verifier=verifier)
        _write_output(args.output, report.model_dump(mode="json"))
        return 0 if report.status != "BLOCKED" else 2
    except Exception as e:
        sys.stderr.write(f"Verification failed: {e}\n")
        return 1


def action_historical(args: argparse.Namespace) -> int:
    try:
        freeze_data = _read_json(args.frozen)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        frozen = FrozenStage1StudyV1.model_validate_json(json.dumps(freeze_data))
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        report = verify_frozen_study(frozen, verifier=verifier)
        if report.status == "BLOCKED":
            sys.stderr.write(f"Historical study blocked: {report.blockers}\n")
            return 2

        execution_receipts = host_config.get("execution_receipts", [])
        if not execution_receipts:
            sys.stderr.write(
                "Historical execution dependencies or session receipts unavailable\n"
            )
            return 2

        observed_count = len(execution_receipts)
        if observed_count < 252:
            sys.stderr.write(
                f"Historical execution incomplete: got {observed_count} "
                "sessions, need 252\n"
            )
            return 4

        manifest = {
            "schema_version": "drift-stage1-historical-manifest/1",
            "study_id": f"HIST-{frozen.protocol.study_id}",
            "freeze_hash": frozen.freeze_hash,
            "scheduled_sessions": 252,
            "observed_sessions": observed_count,
            "executed_at": datetime.now(UTC).isoformat(),
            "status": "COMPLETED",
            "execution_receipts": execution_receipts,
        }
        _write_output(args.output, manifest)
        return 0
    except Exception as e:
        sys.stderr.write(f"Historical execution failed: {e}\n")
        return 1


def action_report(args: argparse.Namespace) -> int:
    try:
        manifest = _read_json(args.run_manifest)
        _ = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        outcome_data = manifest.get("outcome_classification")
        if not outcome_data:
            sys.stderr.write("Missing outcome_classification\n")
            return 3
        outcome = StudyOutcomeClassificationV1.model_validate_json(
            json.dumps(outcome_data)
        )

        uncertainty = None
        if manifest.get("uncertainty"):
            uncertainty = PairedUncertaintyArtifactV1.model_validate_json(
                json.dumps(manifest["uncertainty"])
            )

        pea = (
            Decimal(str(manifest["primary_economic_advantage"]))
            if manifest.get("primary_economic_advantage") is not None
            else None
        )

        report = create_study_report(
            study_id=manifest.get("study_id", "DRIFT-STAGE1"),
            protocol_hash=manifest.get("protocol_hash", "0" * 64),
            mode=manifest.get("mode", "RETROSPECTIVE"),
            scheduled_sessions=int(manifest.get("scheduled_sessions", 252)),
            observed_sessions=int(manifest.get("observed_sessions", 252)),
            outcome_classification=outcome,
            primary_economic_advantage=pea,
            uncertainty=uncertainty,
            limitations=tuple(manifest.get("limitations", ())),
            evidence_inventory=tuple(manifest.get("evidence_inventory", ())),
        )
        _write_output(args.output, report.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Report generation failed: {e}\n")
        return 1


def action_prospective_register(args: argparse.Namespace) -> int:
    try:
        plan_data = _read_json(args.plan)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        plan = ProspectiveStudyPlanV1.model_validate_json(json.dumps(plan_data))
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        evidence = tuple(
            StudyEvidenceReferenceV1.model_validate_json(json.dumps(r))
            for r in host_config.get("evidence", [])
        )
        now = datetime.now(UTC)
        readiness = assess_prospective_readiness(
            plan, evidence=evidence, verifier=verifier, as_of=now
        )
        if readiness.status == "BLOCKED":
            sys.stderr.write(
                f"Prospective registration blocked: {readiness.blockers}\n"
            )
            return 2

        frozen = freeze_prospective_study(
            plan,
            frozen_at=now,
            evidence=evidence,
            verifier=verifier,
        )
        reg = register_prospective_study(
            registration_id=f"REG-{plan.plan_id}",
            registered_at=now,
            frozen_study=frozen,
            has_broker_dispatch_capability=host_config.get("has_broker", False),
        )
        out_path = Path(args.private_root) / f"{reg.registration_id}.json"
        _write_output(str(out_path), reg.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Prospective registration failed: {e}\n")
        return 1


def action_prospective_step(args: argparse.Namespace) -> int:
    try:
        reg_data = _read_json(args.registration)
        _ = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        reg = ProspectiveRegistrationV1.model_validate_json(json.dumps(reg_data))
        if hasattr(args, "session_date") and args.session_date:
            step_date = date.fromisoformat(args.session_date)
        elif reg.last_observed_session is not None:
            step_date = reg.last_observed_session + timedelta(days=1)
        else:
            step_date = reg.frozen_study.plan.first_eligible_session

        advanced = advance_prospective_session(reg, session_date=step_date)
        step_fname = (
            f"{advanced.registration_id}-step-{advanced.observed_session_count}.json"
        )
        out_path = Path(args.private_root) / step_fname
        _write_output(str(out_path), advanced.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Prospective step failed: {e}\n")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drift Stage 1 Study CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inv = subparsers.add_parser("inventory")
    inv.add_argument("--repo-root", required=True)
    inv.add_argument("--output", required=True)

    ass = subparsers.add_parser("assess")
    ass.add_argument("--draft", required=True)
    ass.add_argument("--host-config", required=True)
    ass.add_argument("--output", required=True)

    cal = subparsers.add_parser("calibrate")
    cal.add_argument("--plan", required=True)
    cal.add_argument("--host-config", required=True)
    cal.add_argument("--output", required=True)

    frz = subparsers.add_parser("freeze")
    frz.add_argument("--draft", required=True)
    frz.add_argument("--host-config", required=True)
    frz.add_argument("--output", required=True)

    vf = subparsers.add_parser("verify-freeze")
    vf.add_argument("--freeze", required=True)
    vf.add_argument("--host-config", required=True)
    vf.add_argument("--output", required=True)

    hist = subparsers.add_parser("historical")
    hist.add_argument("--frozen", required=True)
    hist.add_argument("--host-config", required=True)
    hist.add_argument("--output", required=True)

    rep = subparsers.add_parser("report")
    rep.add_argument("--run-manifest", required=True)
    rep.add_argument("--host-config", required=True)
    rep.add_argument("--output", required=True)

    preg = subparsers.add_parser("prospective-register")
    preg.add_argument("--plan", required=True)
    preg.add_argument("--host-config", required=True)
    preg.add_argument("--private-root", required=True)

    pstep = subparsers.add_parser("prospective-step")
    pstep.add_argument("--registration", required=True)
    pstep.add_argument("--host-config", required=True)
    pstep.add_argument("--private-root", required=True)
    pstep.add_argument("--session-date", required=False, default=None)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "inventory": action_inventory,
        "assess": action_assess,
        "calibrate": action_calibrate,
        "freeze": action_freeze,
        "verify-freeze": action_verify_freeze,
        "historical": action_historical,
        "report": action_report,
        "prospective-register": action_prospective_register,
        "prospective-step": action_prospective_step,
    }

    handler = handlers.get(args.command)
    if not handler:
        sys.exit(1)
    code = handler(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
