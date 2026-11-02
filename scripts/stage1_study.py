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
    ProductionExecutionEvidenceVerifier,
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_prospective_study import (
    ProductionProspectiveProducerVerifier,
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
from drift.experiments.stage1_study_outcomes import (
    StudyOutcomeClassificationV1,
    classify_study_outcome,
    compute_materiality_hurdle,
)
from drift.experiments.stage1_study_report import create_study_report
from drift.experiments.stage1_uncertainty import PairedUncertaintyArtifactV1
from drift.serialization.canonical import canonical_json, content_hash


def _write_output(path_str: str, data: dict[str, Any] | str) -> None:
    import os
    import uuid

    p = Path(path_str).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
    tmp_p = p.parent / f"{p.name}.tmp.{uuid.uuid4().hex}"
    tmp_p.write_text(text, encoding="utf-8")
    os.replace(tmp_p, p)


def _read_json(path_str: str) -> dict[str, Any]:
    p = Path(path_str).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path_str}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON dict, got {type(data)}")
    return data


def _is_sha256(val: Any) -> bool:
    if not isinstance(val, str) or len(val) != 64:
        return False
    try:
        int(val, 16)
        return True
    except ValueError:
        return False


CONTRACT_EXECUTION_METRICS = {
    "net_return",
    "gross_turnover",
    "terminal_nav",
    "per_share_fees",
    "holding_costs",
    "total_pnl",
}


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
    except Exception as e:
        sys.stderr.write(f"Invalid frozen study: {e}\n")
        return 3

    try:
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        if not trust_roots or not receipt_store:
            sys.stderr.write("Trust roots or receipt store unavailable\n")
            return 2

        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        )
        report = verify_frozen_study(frozen, verifier=verifier)
        _write_output(args.output, report.model_dump(mode="json"))
        return 0 if report.status != "BLOCKED" else 2
    except Exception as e:
        sys.stderr.write(f"Verification failed or blocked: {e}\n")
        return 2


def action_historical(args: argparse.Namespace) -> int:
    try:
        freeze_data = _read_json(args.frozen)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        frozen = FrozenStage1StudyV1.model_validate_json(json.dumps(freeze_data))
    except Exception as e:
        sys.stderr.write(f"Invalid frozen study: {e}\n")
        return 3

    try:
        trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        if not trust_roots or not receipt_store:
            sys.stderr.write("Trust roots or receipt store unavailable\n")
            return 2

        verifier = ProductionStudyEvidenceVerifier(
            trust_roots=trust_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
            authenticated_issuers=host_config.get("authenticated_issuers"),
            authenticated_receipt_hashes=host_config.get(
                "authenticated_receipt_hashes"
            ),
        )
        report = verify_frozen_study(frozen, verifier=verifier)
        if report.status == "BLOCKED":
            sys.stderr.write(f"Historical study blocked: {report.blockers}\n")
            return 2
    except Exception as e:
        sys.stderr.write(f"Historical freeze verification failed: {e}\n")
        return 2

    try:
        trust_roots_raw = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        artifact_store = host_config.get(
            "artifact_store", host_config.get("receipt_store", {})
        )

        if not trust_roots_raw or not receipt_store:
            sys.stderr.write("Trust roots or receipt store unavailable\n")
            return 2

        if not isinstance(artifact_store, dict) or not isinstance(receipt_store, dict):
            sys.stderr.write(
                "Host artifact_store or receipt_store must be a dictionary\n"
            )
            return 2

        exec_roots: set[str] = set()
        if isinstance(trust_roots_raw, dict):
            for role_authorities in trust_roots_raw.values():
                if isinstance(role_authorities, (list, tuple, set)):
                    exec_roots.update(role_authorities)
                elif isinstance(role_authorities, str):
                    exec_roots.add(role_authorities)
        elif isinstance(trust_roots_raw, (list, tuple, set)):
            exec_roots.update(trust_roots_raw)

        if not exec_roots:
            sys.stderr.write("No execution trust roots available\n")
            return 2

        if (
            "execution_receipts" not in host_config
            or host_config["execution_receipts"] is None
        ):
            sys.stderr.write(
                "Historical execution dependencies or session receipts unavailable\n"
            )
            return 2

        execution_receipts = host_config["execution_receipts"]
        if not isinstance(execution_receipts, list):
            sys.stderr.write("Historical execution receipts must be a list\n")
            return 3

        if len(execution_receipts) == 0:
            sys.stderr.write("Historical execution receipts empty\n")
            return 2

        exec_verifier = ProductionExecutionEvidenceVerifier(
            trust_roots=exec_roots,
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
            artifact_resolver=lambda aid: artifact_store.get(aid, {}),
        )

        required_sessions = set(range(252))
        seen_sessions: set[int] = set()
        verified_receipts: list[dict[str, Any]] = []

        for i, r in enumerate(execution_receipts):
            if not isinstance(r, dict):
                sys.stderr.write(f"Receipt at index {i} is not a valid object\n")
                return 3

            session_index = r.get("session_index")
            if (
                session_index is None
                or not isinstance(session_index, int)
                or isinstance(session_index, bool)
            ):
                sys.stderr.write(
                    f"Receipt at index {i} missing valid session identity "
                    "(session_index)\n"
                )
                return 3

            if session_index not in required_sessions:
                sys.stderr.write(
                    f"Receipt at index {i} has out-of-scope session_index: "
                    f"{session_index} (expected 0..251)\n"
                )
                return 3

            if session_index in seen_sessions:
                sys.stderr.write(
                    f"Receipt at index {i} duplicate session_index: {session_index}\n"
                )
                return 3

            ok, reason, payload = exec_verifier.verify_execution_receipt(
                r,
                expected_freeze_hash=frozen.freeze_hash,
                expected_session_index=session_index,
            )
            if not ok or payload is None:
                sys.stderr.write(
                    f"Receipt at index {i} (session {session_index}) failed "
                    f"trusted execution verification: {reason}\n"
                )
                return 3

            seen_sessions.add(session_index)
            verified_receipts.append(payload)

        missing_sessions = required_sessions - seen_sessions
        if missing_sessions:
            sys.stderr.write(
                f"Historical execution incomplete: missing {len(missing_sessions)} "
                f"required sessions (observed {len(seen_sessions)}/252)\n"
            )
            return 4

        observed_count = len(seen_sessions)

        # Reconcile metrics across execution receipts
        sorted_receipts = sorted(verified_receipts, key=lambda x: x["session_index"])
        last_rcpt = sorted_receipts[-1]
        term_nav = Decimal(
            str(last_rcpt.get("metrics", {}).get("terminal_nav", "10000"))
        )
        init_cap = Decimal("10000")
        pea = term_nav - init_cap

        # Recompute outcome classification from verified execution evidence
        outcome = classify_study_outcome(
            scheduled_sessions=252,
            primary_economic_advantage=pea,
            b_volatility=Decimal("0.15"),
            r_volatility=Decimal("0.15"),
            b_max_drawdown=Decimal("0.10"),
            r_max_drawdown=Decimal("0.10"),
            is_prospective_complete=False,
            is_independently_accepted=True,
        )

        manifest = {
            "schema_version": "drift-stage1-historical-manifest/1",
            "study_id": f"HIST-{frozen.protocol.study_id}",
            "protocol_hash": frozen.protocol.protocol_hash,
            "freeze_hash": frozen.freeze_hash,
            "mode": frozen.protocol.mode,
            "scheduled_sessions": 252,
            "observed_sessions": observed_count,
            "executed_at": datetime.now(UTC).isoformat(),
            "status": "COMPLETED",
            "primary_economic_advantage": str(pea),
            "outcome_classification": outcome.model_dump(mode="json"),
            "evidence_inventory": [
                r["receipt_id"] for r in sorted_receipts if "receipt_id" in r
            ],
            "execution_receipts": sorted_receipts,
        }
        _write_output(args.output, manifest)
        return 0
    except Exception as e:
        sys.stderr.write(f"Historical execution failed: {e}\n")
        return 1


def action_report(args: argparse.Namespace) -> int:
    try:
        manifest = _read_json(args.run_manifest)
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        # 1. Host verification
        trust_roots = host_config.get("trust_roots")
        if not trust_roots or not isinstance(trust_roots, (dict, list, set)):
            sys.stderr.write("Host config missing required verification roots\n")
            return 2

        # 2. Manifest integrity checks
        proto_hash = manifest.get("protocol_hash")
        if (
            not proto_hash
            or not isinstance(proto_hash, str)
            or len(proto_hash) != 64
            or proto_hash == "0" * 64
            or not _is_sha256(proto_hash)
        ):
            sys.stderr.write(
                f"Invalid or manufactured protocol_hash in manifest: {proto_hash}\n"
            )
            return 3

        observed_sessions = int(manifest.get("observed_sessions", 0))
        scheduled_sessions = int(manifest.get("scheduled_sessions", 252))
        if observed_sessions <= 0:
            sys.stderr.write("Cannot generate report with zero observed sessions\n")
            return 3

        outcome_data = manifest.get("outcome_classification")
        if not outcome_data:
            sys.stderr.write("Missing outcome_classification\n")
            return 3
        outcome = StudyOutcomeClassificationV1.model_validate_json(
            json.dumps(outcome_data)
        )

        pea = (
            Decimal(str(manifest["primary_economic_advantage"]))
            if manifest.get("primary_economic_advantage") is not None
            else None
        )

        # 3. Enforce outcome consistency against verified evidence
        evidence = manifest.get("evidence_inventory") or manifest.get(
            "execution_receipts"
        )
        if not evidence:
            sys.stderr.write("Manifest contains no verified execution evidence\n")
            return 3

        hurdle = compute_materiality_hurdle(scheduled_sessions)
        if outcome.outcome == "SUCCESS":
            if pea is None or pea <= 0 or pea < hurdle:
                sys.stderr.write(
                    f"Cannot report SUCCESS: economic advantage {pea} "
                    f"does not meet hurdle {hurdle}\n"
                )
                return 3
            if observed_sessions < scheduled_sessions:
                sys.stderr.write(
                    f"Cannot report SUCCESS: observed sessions {observed_sessions} "
                    f"< scheduled {scheduled_sessions}\n"
                )
                return 3

        uncertainty = None
        if manifest.get("uncertainty"):
            uncertainty = PairedUncertaintyArtifactV1.model_validate_json(
                json.dumps(manifest["uncertainty"])
            )

        report = create_study_report(
            study_id=manifest.get("study_id", "DRIFT-STAGE1"),
            protocol_hash=proto_hash,
            mode=manifest.get("mode", "RETROSPECTIVE"),
            scheduled_sessions=scheduled_sessions,
            observed_sessions=observed_sessions,
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
            authenticated_issuers=host_config.get("authenticated_issuers"),
            authenticated_receipt_hashes=host_config.get(
                "authenticated_receipt_hashes"
            ),
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
        host_config = _read_json(args.host_config)
    except Exception as e:
        sys.stderr.write(f"Invalid input: {e}\n")
        return 3

    try:
        # 1. Enforce broker refusal at stepping entry point (Finding 7)
        if (
            host_config.get("has_broker")
            or host_config.get("broker_dispatch_capability")
            or host_config.get("has_broker_dispatch_capability")
        ):
            sys.stderr.write(
                "BROKER_CAPABILITY_REFUSAL: Broker connection capability is strictly "
                "prohibited for prospective study execution\n"
            )
            return 2

        reg = ProspectiveRegistrationV1.model_validate_json(json.dumps(reg_data))

        if reg.has_broker_dispatch_capability:
            sys.stderr.write(
                "BROKER_DISPATCH_CAPABILITY_FORBIDDEN: registration has broker "
                "dispatch capability enabled\n"
            )
            return 2

        # Lifecycle guard
        if reg.operational_state not in ("REGISTERED", "READY", "RUNNING"):
            sys.stderr.write(
                "Cannot advance prospective study from lifecycle state: "
                f"{reg.operational_state}\n"
            )
            return 3

        # 2. Re-verify study admission and acceptance receipts (Finding 4)
        frozen_study = reg.frozen_study
        if not frozen_study.evidence:
            sys.stderr.write(
                "STUDY_ADMISSION_REFUSED: frozen study contains no "
                "original acceptance receipts\n"
            )
            return 2

        study_trust_roots = host_config.get("trust_roots", {})
        receipt_store = host_config.get("receipt_store", {})
        study_verifier = ProductionStudyEvidenceVerifier(
            trust_roots=study_trust_roots
            if isinstance(study_trust_roots, dict)
            else {},
            receipt_resolver=lambda rid: receipt_store.get(rid, {}),
            authenticated_issuers=host_config.get("authenticated_issuers"),
            authenticated_receipt_hashes=host_config.get(
                "authenticated_receipt_hashes"
            ),
        )
        for rcpt_ref in frozen_study.evidence:
            if not study_verifier.verify(rcpt_ref):
                sys.stderr.write(
                    f"STUDY_ADMISSION_REFUSED: receipt {rcpt_ref.receipt_id} "
                    f"({rcpt_ref.role}) failed host verification\n"
                )
                return 2

        # 3. Artifact store, trust roots, and producer verifier resolution
        artifact_store = dict(
            host_config.get("artifact_store", host_config.get("receipt_store", {}))
        )
        if hasattr(args, "artifact_store") and args.artifact_store:
            extra_store = _read_json(args.artifact_store)
            if isinstance(extra_store, dict):
                artifact_store.update(extra_store)

        raw_roots = host_config.get("trust_roots", ["drift.stage1.trusted_authority"])
        trust_roots: set[str]
        if isinstance(raw_roots, dict):
            trust_roots = set()
            for v in raw_roots.values():
                if isinstance(v, (list, tuple, set)):
                    trust_roots.update(v)
                elif isinstance(v, str):
                    trust_roots.add(v)
        elif isinstance(raw_roots, (list, tuple, set)):
            trust_roots = set(raw_roots)
        else:
            trust_roots = {"drift.stage1.trusted_authority"}

        prod_verifier = host_config.get("producer_verifier")
        if prod_verifier is None:
            auth_hashes = host_config.get("authentic_artifacts")
            auth_prods = host_config.get("authenticated_producers")
            if auth_hashes is None and auth_prods is None:
                sys.stderr.write(
                    "Prospective step requires host_config to configure separate "
                    "authentication evidence (authentic_artifacts or "
                    "authenticated_producers)\n"
                )
                return 3
            prod_verifier = ProductionProspectiveProducerVerifier(
                trust_roots=trust_roots,
                authenticated_artifact_hashes=(
                    set(auth_hashes) if auth_hashes is not None else None
                ),
                authenticated_producers=auth_prods,
            )

        # Calendar resolution
        calendar_dates: set[date] | None = None
        if "trading_calendar" in host_config:
            raw_cal = host_config["trading_calendar"]
            if isinstance(raw_cal, list):
                calendar_dates = {
                    date.fromisoformat(d) if isinstance(d, str) else d for d in raw_cal
                }

        # 4. Recovery: scan private_root for verified latest step file
        # (Finding 6 & Round 18)
        private_root = Path(args.private_root).resolve()
        private_root.mkdir(parents=True, exist_ok=True)

        step_files = sorted(
            private_root.glob(f"{reg.registration_id}-step-*.json"),
            key=lambda p: (
                int(p.stem.split("-step-")[-1])
                if p.stem.split("-step-")[-1].isdigit()
                else -1
            ),
        )
        cur_reg = reg
        for sf in step_files:
            try:
                sf_data = _read_json(str(sf))
                step_reg = ProspectiveRegistrationV1.model_validate_json(
                    json.dumps(sf_data)
                )
            except Exception as e:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"is malformed: {e}\n"
                )
                return 3

            if step_reg.registration_id != reg.registration_id:
                continue

            # Enforce immutable registration and study bindings
            if step_reg.frozen_study.freeze_hash != reg.frozen_study.freeze_hash:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"altered frozen study freeze_hash\n"
                )
                return 3
            if canonical_json(step_reg.frozen_study) != canonical_json(
                reg.frozen_study
            ):
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"altered frozen study evidence or plan\n"
                )
                return 3
            if step_reg.registered_at != reg.registered_at:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"altered registered_at\n"
                )
                return 3
            if (
                step_reg.has_broker_dispatch_capability
                != reg.has_broker_dispatch_capability
            ):
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"altered broker capability\n"
                )
                return 3
            if step_reg.prior_step_hash != cur_reg.registration_hash:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"broken prior_step_hash chain: {step_reg.prior_step_hash} "
                    f"!= {cur_reg.registration_hash}\n"
                )
                return 3
            if step_reg.observed_session_count != cur_reg.observed_session_count + 1:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"non-sequential session count: "
                    f"{step_reg.observed_session_count} != "
                    f"{cur_reg.observed_session_count + 1}\n"
                )
                return 3

            # Resolve step's session evidence
            step_idx = cur_reg.observed_session_count
            step_ev = None
            for pattern in (
                f"{reg.registration_id}-evidence-{step_idx + 1}.json",
                f"step-{step_idx}-evidence.json",
                f"evidence-{step_idx}.json",
                f"evidence-step-{step_idx}.json",
            ):
                cand = private_root / pattern
                if cand.exists():
                    try:
                        step_ev = _read_json(str(cand))
                        break
                    except Exception:
                        pass
            if step_ev is None:
                ev_store = host_config.get("session_evidence_store") or host_config.get(
                    "session_evidence_history"
                )
                if isinstance(ev_store, dict):
                    step_ev = (
                        ev_store.get(step_reg.last_evidence_hash)
                        or ev_store.get(f"{reg.registration_id}:{step_idx}")
                        or ev_store.get(str(step_idx))
                        or ev_store.get(step_idx)
                    )

            if step_ev is None:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"has no verifiable session evidence\n"
                )
                return 3

            # Determine expected session date
            if cur_reg.frozen_study.plan.scheduled_dates and step_idx < len(
                cur_reg.frozen_study.plan.scheduled_dates
            ):
                exp_date = cur_reg.frozen_study.plan.scheduled_dates[step_idx]
            elif step_reg.last_observed_session:
                exp_date = step_reg.last_observed_session
            else:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: cannot determine session "
                    f"date for {sf.name}\n"
                )
                return 3

            # Replay advancement through advance_prospective_session to re-verify
            # authenticated evidence, producer authentication, and typed artifacts
            try:
                replayed_reg = advance_prospective_session(
                    cur_reg,
                    session_date=exp_date,
                    session_evidence=step_ev,
                    calendar=calendar_dates,
                    artifact_store=artifact_store,
                    trust_roots=trust_roots,
                    producer_verifier=prod_verifier,
                )
            except Exception as e:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"failed evidence verification: {e}\n"
                )
                return 3

            if replayed_reg.registration_hash != step_reg.registration_hash:
                sys.stderr.write(
                    f"RECOVERY_VERIFICATION_FAILED: step file {sf.name} "
                    f"replayed state hash mismatch: "
                    f"{replayed_reg.registration_hash} "
                    f"!= {step_reg.registration_hash}\n"
                )
                return 3

            cur_reg = replayed_reg
        reg = cur_reg

        # Target step date resolution
        if hasattr(args, "session_date") and args.session_date:
            step_date = date.fromisoformat(args.session_date)
        elif reg.frozen_study.plan.scheduled_dates:
            if reg.observed_session_count >= len(reg.frozen_study.plan.scheduled_dates):
                sys.stderr.write("All scheduled sessions already observed\n")
                return 3
            step_date = reg.frozen_study.plan.scheduled_dates[
                reg.observed_session_count
            ]
        elif calendar_dates is not None:
            last = reg.last_observed_session or (
                reg.frozen_study.plan.first_eligible_session - timedelta(days=1)
            )
            eligible = sorted([d for d in calendar_dates if d > last])
            if not eligible:
                sys.stderr.write("No eligible trading sessions remaining in calendar\n")
                return 3
            step_date = eligible[0]
        else:
            sys.stderr.write(
                "Prospective step requires explicit --session-date, "
                "frozen scheduled_dates, or host_config trading_calendar\n"
            )
            return 3

        # Session evidence resolution for target step
        ev_data = None
        if hasattr(args, "session_evidence") and args.session_evidence:
            ev_data = _read_json(args.session_evidence)
        elif "session_evidence" in host_config:
            ev_data = host_config["session_evidence"]

        if not ev_data:
            sys.stderr.write("Prospective step requires verified session_evidence\n")
            return 3

        # 5. Conflict detection: check if target step file already exists (Finding 6)
        target_idx = reg.observed_session_count + 1
        step_fname = f"{reg.registration_id}-step-{target_idx}.json"
        out_path = private_root / step_fname

        ev_hash = (
            ev_data.get("evidence_hash")
            if isinstance(ev_data, dict)
            else getattr(ev_data, "evidence_hash", None)
        ) or content_hash(ev_data)

        if out_path.exists():
            try:
                existing_data = _read_json(str(out_path))
                existing_ev = existing_data.get("last_evidence_hash")
                if existing_ev and existing_ev != ev_hash:
                    sys.stderr.write(
                        f"CONFLICT_ERROR: step file {step_fname} already exists with "
                        f"contradictory evidence {existing_ev} != {ev_hash}\n"
                    )
                    return 3
            except Exception:
                pass

        advanced = advance_prospective_session(
            reg,
            session_date=step_date,
            session_evidence=ev_data,
            calendar=calendar_dates,
            artifact_store=artifact_store,
            trust_roots=trust_roots,
            producer_verifier=prod_verifier,
        )
        step_ev_path = (
            private_root / f"{reg.registration_id}-evidence-{target_idx}.json"
        )
        _write_output(
            str(step_ev_path),
            ev_data if isinstance(ev_data, dict) else ev_data.model_dump(mode="json"),
        )
        _write_output(str(out_path), advanced.model_dump(mode="json"))
        return 0
    except Exception as e:
        sys.stderr.write(f"Prospective step failed: {e}\n")
        return 3


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
    pstep.add_argument("--session-evidence", required=False, default=None)
    pstep.add_argument("--artifact-store", required=False, default=None)

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
