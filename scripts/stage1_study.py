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
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from drift.experiments.stage1_historical_execution import (
    HistoricalRunConfigV1,
    execute_historical_study,
)
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
from drift.experiments.stage1_uncertainty import (
    PairedUncertaintyArtifactV1,
    compute_paired_uncertainty_artifact,
)
from drift.serialization.canonical import canonical_json, content_hash


def _write_output(path_str: str, data: dict[str, Any] | str) -> None:
    p = Path(path_str).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
    tmp_p = p.parent / f"{p.name}.tmp.{uuid.uuid4().hex}"
    tmp_p.write_text(text, encoding="utf-8")
    os.replace(tmp_p, p)


@contextmanager
def _registration_lock(private_root: Path, registration_id: str) -> Generator[None]:
    """Serialize recovery and step publication per registration (Round 19)."""
    lock_path = private_root / f".{registration_id}.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(lock_fd)
        except OSError:
            pass


def _recover_uncommitted_publication(private_root: Path, registration_id: str) -> None:
    """Reconcile uncommitted or orphaned publication remnants (Round 20).

    If an earlier process was terminated after publishing evidence but before
    publishing step state, the orphaned evidence is rolled back to allow clean
    retry.
    """
    for ev_file in private_root.glob(f"{registration_id}-evidence-*.json"):
        stem = ev_file.stem
        if "-evidence-" in stem:
            idx_str = stem.split("-evidence-")[-1]
            step_file = private_root / f"{registration_id}-step-{idx_str}.json"
            if not step_file.exists():
                ev_file.unlink(missing_ok=True)

    for tmp_f in private_root.glob(f"{registration_id}-*.tmp.*"):
        tmp_f.unlink(missing_ok=True)


def _publish_prospective_step_pair(
    ev_path: Path,
    ev_data: dict[str, Any] | str,
    step_path: Path,
    step_data: dict[str, Any] | str,
) -> None:
    """Atomically commit evidence and step state pair with recoverable protocol."""
    ev_path.parent.mkdir(parents=True, exist_ok=True)
    step_path.parent.mkdir(parents=True, exist_ok=True)

    if ev_path.exists() and step_path.exists():
        raise FileExistsError(
            f"Step target file {step_path.name} and evidence {ev_path.name} "
            f"already exist"
        )

    # Clean any uncommitted single-file remnant before publishing
    if ev_path.exists():
        ev_path.unlink(missing_ok=True)
    if step_path.exists():
        step_path.unlink(missing_ok=True)

    ev_text = (
        ev_data
        if isinstance(ev_data, str)
        else json.dumps(ev_data, indent=2, default=str)
    )
    step_text = (
        step_data
        if isinstance(step_data, str)
        else json.dumps(step_data, indent=2, default=str)
    )

    tmp_ev = ev_path.parent / f"{ev_path.name}.tmp.{uuid.uuid4().hex}"
    tmp_step = step_path.parent / f"{step_path.name}.tmp.{uuid.uuid4().hex}"

    tmp_ev.write_text(ev_text, encoding="utf-8")
    tmp_step.write_text(step_text, encoding="utf-8")

    try:
        os.replace(tmp_ev, ev_path)

        if os.environ.get("_DRIFT_TEST_CRASH_AFTER_FIRST_RENAME") == "1":
            os._exit(42)

        os.replace(tmp_step, step_path)
    except Exception:
        tmp_ev.unlink(missing_ok=True)
        tmp_step.unlink(missing_ok=True)
        ev_path.unlink(missing_ok=True)
        step_path.unlink(missing_ok=True)
        raise


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


def action_verify_market_data(args: argparse.Namespace) -> int:
    try:
        from drift.qualification.alpaca_sip_verification import (
            create_mock_alpaca_sip_evidence_fixtures,
            verify_g1_alpaca_sip_qualification,
        )

        request_end = (
            datetime.fromisoformat(args.request_end.replace("Z", "+00:00"))
            if getattr(args, "request_end", None)
            else datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
        )
        now = (
            datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if getattr(args, "as_of", None)
            else datetime.now(UTC)
        )

        if getattr(args, "with_fixtures", False):
            intake_res, cov_ev, ca_records, rights = (
                create_mock_alpaca_sip_evidence_fixtures()
            )
            report = verify_g1_alpaca_sip_qualification(
                request_end=request_end,
                request_time=now,
                intake_result=intake_res,
                corporate_actions=ca_records,
                rights_assessment=rights,
                coverage_evidence=cov_ev,
                allow_synthetic=True,
            )
        else:
            report = verify_g1_alpaca_sip_qualification(
                request_end=request_end,
                request_time=now,
                allow_synthetic=False,
            )

        if getattr(args, "output", None):
            _write_output(args.output, report.model_dump(mode="json"))
        return 0 if report.overall_status == "VERIFIED" else 2
    except Exception as e:
        sys.stderr.write(f"Market data verification failed: {e}\n")
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


def action_historical_run(args: argparse.Namespace) -> int:
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
        trust_roots_raw = host_config.get("trust_roots", {})
        receipt_store = host_config.setdefault("receipt_store", {})
        artifact_store = host_config.setdefault("artifact_store", {})

        authority_id = getattr(args, "authority", None)
        if not authority_id:
            if isinstance(trust_roots_raw, dict):
                for role_authorities in trust_roots_raw.values():
                    if (
                        isinstance(role_authorities, (list, tuple, set))
                        and role_authorities
                    ):
                        authority_id = next(iter(role_authorities))
                        break
                    elif isinstance(role_authorities, str) and role_authorities:
                        authority_id = role_authorities
                        break
            elif isinstance(trust_roots_raw, (list, tuple, set)) and trust_roots_raw:
                authority_id = next(iter(trust_roots_raw))

        if not authority_id:
            authority_id = "trusted-historical-root"

        ledger_dir = (
            Path(args.ledger_dir).resolve()
            if getattr(args, "ledger_dir", None)
            else Path(tempfile.mkdtemp(prefix="drift-historical-ledger-"))
        )

        session_count = getattr(args, "session_count", None)
        if session_count is None:
            if "expected_sessions" in host_config and isinstance(
                host_config["expected_sessions"], (list, tuple)
            ):
                session_count = len(host_config["expected_sessions"])
            elif "scheduled_sessions" in host_config and isinstance(
                host_config["scheduled_sessions"], int
            ):
                session_count = host_config["scheduled_sessions"]
            elif (
                hasattr(frozen.protocol, "observation_sessions")
                and frozen.protocol.observation_sessions is not None
            ):
                session_count = frozen.protocol.observation_sessions
            else:
                session_count = 252

        operating_costs = Decimal(
            str(
                host_config.get(
                    "incremental_operating_costs",
                    host_config.get("attributable_costs", "10.00"),
                )
            )
        )

        config = HistoricalRunConfigV1(
            frozen=frozen,
            origin_dir=ledger_dir,
            authority_id=authority_id,
            initial_capital=Decimal(
                str(getattr(frozen.protocol, "initial_capital", "10000"))
            ),
            incremental_operating_costs=operating_costs,
            session_count=session_count,
        )

        result = execute_historical_study(
            config,
            receipt_store=receipt_store,
            artifact_store=artifact_store,
        )

        # Populate host_config with execution receipts and reference receipts
        host_config["execution_receipts"] = list(result.candidate_receipt_refs)
        host_config["reference_execution_receipts"] = list(
            result.reference_receipt_refs
        )
        host_config["incremental_operating_costs"] = str(operating_costs)

        # Write output manifest
        out_payload = result.model_dump(mode="json")
        out_payload["updated_host_config"] = host_config
        _write_output(args.output, out_payload)

        if getattr(args, "update_host_config", False):
            _write_output(args.host_config, host_config)

        return 0
    except Exception as e:
        sys.stderr.write(f"Historical run failed: {e}\n")
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

        if "expected_sessions" in host_config and isinstance(
            host_config["expected_sessions"], (list, tuple, set)
        ):
            required_sessions = set(host_config["expected_sessions"])
        elif "scheduled_sessions" in host_config and isinstance(
            host_config["scheduled_sessions"], int
        ):
            required_sessions = set(range(host_config["scheduled_sessions"]))
        elif (
            hasattr(frozen.protocol, "observation_sessions")
            and frozen.protocol.observation_sessions is not None
            and "execution_receipts" in host_config
            and isinstance(host_config["execution_receipts"], list)
            and len(host_config["execution_receipts"])
            == frozen.protocol.observation_sessions
        ):
            required_sessions = set(range(frozen.protocol.observation_sessions))
        else:
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
                f"required sessions "
                f"(observed {len(seen_sessions)}/{len(required_sessions)})\n"
            )
            return 4

        observed_count = len(seen_sessions)

        # Reconcile metrics across execution receipts
        sorted_receipts = sorted(verified_receipts, key=lambda x: x["session_index"])

        # Candidate arm B returns
        b_returns = [
            Decimal(str(r.get("metrics", {}).get("net_return", "0")))
            for r in sorted_receipts
        ]

        # Verified paired reference evidence (Round 21 & Round 22)
        ref_receipts_raw = host_config.get(
            "reference_execution_receipts"
        ) or host_config.get("reference_receipts")

        paired_ev_dict = host_config.get("paired_evidence")
        if paired_ev_dict and isinstance(paired_ev_dict, dict):
            if "reference_receipts" in paired_ev_dict:
                ref_receipts_raw = paired_ev_dict["reference_receipts"]
            elif "reference_execution_receipts" in paired_ev_dict:
                ref_receipts_raw = paired_ev_dict["reference_execution_receipts"]

        # Authorized reference binding:
        # must be explicit reference binding or frozen study comparison
        expected_ref_freeze_hash = (
            host_config.get("reference_freeze_hash")
            or host_config.get("reference_binding", {}).get("freeze_hash")
            or (
                paired_ev_dict.get("reference_freeze_hash")
                if isinstance(paired_ev_dict, dict)
                else None
            )
            or frozen.freeze_hash
        )

        r_returns: list[Decimal] | None = None
        seen_ref_sessions: set[int] = set()
        verified_ref_receipts: list[dict[str, Any]] = []
        candidate_receipt_ids = {
            r.get("receipt_id") for r in verified_receipts if "receipt_id" in r
        }

        if ref_receipts_raw is not None:
            if not isinstance(ref_receipts_raw, list):
                sys.stderr.write("Reference receipts must be a list\n")
                return 3
            if len(ref_receipts_raw) != len(required_sessions):
                sys.stderr.write(
                    f"Reference receipts count mismatch: "
                    f"expected {len(required_sessions)}, "
                    f"got {len(ref_receipts_raw)}\n"
                )
                return 3

            for rr in ref_receipts_raw:
                if not isinstance(rr, dict):
                    sys.stderr.write("Reference receipt is not a valid object\n")
                    return 3
                rr_idx = rr.get("session_index")
                if (
                    rr_idx is None
                    or not isinstance(rr_idx, int)
                    or isinstance(rr_idx, bool)
                    or rr_idx not in required_sessions
                ):
                    sys.stderr.write(
                        f"Invalid reference receipt session index: {rr_idx}\n"
                    )
                    return 3

                if rr_idx in seen_ref_sessions:
                    sys.stderr.write(
                        f"Duplicate reference receipt session index: {rr_idx}\n"
                    )
                    return 3

                ok_ref, reason_ref, payload_ref = (
                    exec_verifier.verify_execution_receipt(
                        rr,
                        expected_freeze_hash=expected_ref_freeze_hash,
                        expected_session_index=rr_idx,
                    )
                )
                if not ok_ref or payload_ref is None:
                    sys.stderr.write(
                        f"Reference receipt verification failed: {reason_ref}\n"
                    )
                    return 3

                # Distinct reference-arm identity check:
                # Reference receipt cannot be candidate arm's receipt
                ref_rid = payload_ref.get("receipt_id")
                if ref_rid and ref_rid in candidate_receipt_ids:
                    sys.stderr.write(
                        f"Candidate arm receipt re-used as reference: {ref_rid}\n"
                    )
                    return 3

                # Reference arm identity verification:
                # Receipt MUST identify as reference arm
                ref_arm = (
                    payload_ref.get("arm")
                    or payload_ref.get("arm_id")
                    or payload_ref.get("role")
                    or payload_ref.get("reference_arm")
                    or (
                        payload_ref.get("metrics", {}).get("arm")
                        if isinstance(payload_ref.get("metrics"), dict)
                        else None
                    )
                )
                if not ref_arm:
                    sys.stderr.write(
                        f"Reference receipt at session {rr_idx} missing "
                        "reference-arm identity\n"
                    )
                    return 3

                if str(ref_arm).upper() in ("B", "CANDIDATE"):
                    sys.stderr.write(
                        f"Reference receipt claims candidate arm identity: {ref_arm}\n"
                    )
                    return 3

                expected_ref_arm = host_config.get("reference_arm_id") or (
                    paired_ev_dict.get("reference_arm_id")
                    if isinstance(paired_ev_dict, dict)
                    else None
                )
                if expected_ref_arm and ref_arm != expected_ref_arm:
                    sys.stderr.write(
                        f"Reference receipt arm {ref_arm} does not match "
                        f"expected {expected_ref_arm}\n"
                    )
                    return 3

                seen_ref_sessions.add(rr_idx)
                verified_ref_receipts.append(payload_ref)

            if seen_ref_sessions != required_sessions:
                sys.stderr.write(
                    f"Incomplete reference receipts: observed "
                    f"{len(seen_ref_sessions)}/{len(required_sessions)}\n"
                )
                return 4

            sorted_ref = sorted(verified_ref_receipts, key=lambda x: x["session_index"])
            r_returns = [
                Decimal(str(r.get("metrics", {}).get("net_return", "0")))
                for r in sorted_ref
            ]
        else:
            sorted_ref = []

        # Operating costs: must be established from host config or paired evidence.
        # Freeze contract prohibits defaulting unknown operating costs to zero.
        raw_costs = None
        if "incremental_operating_costs" in host_config:
            raw_costs = host_config["incremental_operating_costs"]
        elif (
            paired_ev_dict
            and isinstance(paired_ev_dict, dict)
            and "incremental_operating_costs" in paired_ev_dict
        ):
            raw_costs = paired_ev_dict["incremental_operating_costs"]
        elif "attributable_costs" in host_config:
            raw_costs = host_config["attributable_costs"]

        costs: Decimal | None = None
        if raw_costs is not None:
            try:
                costs = Decimal(str(raw_costs))
            except Exception:
                costs = None

        pea: Decimal | None = None
        b_volatility: Decimal | None = None
        r_volatility: Decimal | None = None
        b_max_drawdown: Decimal | None = None
        r_max_drawdown: Decimal | None = None
        p_nav_lower: Decimal | None = None
        p_econ_lower: Decimal | None = None
        opt_b_length: int | None = None
        block_diagnostics: dict[str, Any] = {}

        unavailable_reasons: list[str] = []
        if r_returns is None or len(r_returns) != len(b_returns):
            unavailable_reasons.append("MISSING_PAIRED_REFERENCE_EVIDENCE")

        if costs is None:
            unavailable_reasons.append("MISSING_ATTRIBUTABLE_OPERATING_COSTS")

        if (
            r_returns is not None
            and len(r_returns) == len(b_returns)
            and costs is not None
        ):
            b_compound = Decimal("1")
            r_compound = Decimal("1")
            b_nav_marks = [Decimal("10000")]
            r_nav_marks = [Decimal("10000")]
            for b_ret, r_ret in zip(b_returns, r_returns, strict=True):
                b_compound *= Decimal("1") + b_ret
                r_compound *= Decimal("1") + r_ret
                b_nav_marks.append(Decimal("10000") * b_compound)
                r_nav_marks.append(Decimal("10000") * r_compound)

            delta_nav = (b_compound - Decimal("1")) - (r_compound - Decimal("1"))
            pea = (Decimal("10000") * delta_nav) - costs

            n_obs = Decimal(len(b_returns))
            b_mean = sum(b_returns) / n_obs
            b_var = sum((x - b_mean) ** 2 for x in b_returns) / (n_obs - Decimal("1"))
            b_volatility = b_var.sqrt() * Decimal("252").sqrt()

            r_mean = sum(r_returns) / n_obs
            r_var = sum((x - r_mean) ** 2 for x in r_returns) / (n_obs - Decimal("1"))
            r_volatility = r_var.sqrt() * Decimal("252").sqrt()

            def _calc_mdd(marks: list[Decimal]) -> Decimal:
                peak = marks[0]
                mdd = Decimal("0")
                for m in marks:
                    if m > peak:
                        peak = m
                    if peak > Decimal("0"):
                        dd = (peak - m) / peak
                        if dd > mdd:
                            mdd = dd
                return mdd

            b_max_drawdown = _calc_mdd(b_nav_marks)
            r_max_drawdown = _calc_mdd(r_nav_marks)

            # Prescribed automatic block length estimator applied to B, R,
            # and difference
            repo_root = Path(__file__).resolve().parent.parent
            worker_script = (
                repo_root / "tools" / "stage1-statistics" / "block_length_worker.py"
            )
            worker_dir = repo_root / "tools" / "stage1-statistics"

            if worker_script.is_file():
                diff_returns = [
                    b - r for b, r in zip(b_returns, r_returns, strict=True)
                ]
                input_payload = {
                    "schema_version": "drift-stage1-block-length-input/1",
                    "sessions": [f"S{i:03d}" for i in range(len(b_returns))],
                    "b_returns": [str(x) for x in b_returns],
                    "r_returns": [str(x) for x in r_returns],
                    "difference_returns": [str(x) for x in diff_returns],
                }
                env = os.environ.copy()
                env.pop("VIRTUAL_ENV", None)
                try:
                    proc_worker = subprocess.run(
                        [
                            "uv",
                            "--directory",
                            str(worker_dir),
                            "run",
                            "python",
                            str(worker_script),
                        ],
                        input=json.dumps(input_payload).encode("utf-8"),
                        capture_output=True,
                        check=True,
                        env=env,
                    )
                    worker_out = json.loads(proc_worker.stdout.decode("utf-8"))
                    series_results = worker_out.get("series_results", {})
                    all_finite = len(series_results) == 3 and all(
                        res.get("status") == "FINITE"
                        and res.get("stationary") is not None
                        for res in series_results.values()
                    )
                    agg_b = worker_out.get("aggregated_block_length")
                    if agg_b is not None and all_finite:
                        opt_b_length = int(agg_b)
                    else:
                        opt_b_length = None
                    block_diagnostics = {
                        "series_results": series_results,
                        "diagnostics": worker_out.get("diagnostics", []),
                        "aggregated_block_length": opt_b_length,
                        "all_series_finite": all_finite,
                        "worker_source_hash": worker_out.get("worker_source_hash"),
                        "package_identity": worker_out.get("package_identity"),
                    }
                except Exception as e:
                    opt_b_length = None
                    block_diagnostics = {
                        "series_results": {},
                        "diagnostics": [f"BLOCK_LENGTH_WORKER_ERROR:{e}"],
                        "aggregated_block_length": None,
                        "all_series_finite": False,
                    }
            else:
                block_diagnostics = {
                    "series_results": {},
                    "diagnostics": ["BLOCK_LENGTH_WORKER_NOT_FOUND"],
                    "aggregated_block_length": None,
                    "all_series_finite": False,
                }

            try:
                uncertainty_art = compute_paired_uncertainty_artifact(
                    b_returns=b_returns,
                    r_returns=r_returns,
                    initial_capital=Decimal("10000"),
                    incremental_operating_costs=costs,
                    mean_block_length=opt_b_length,
                )
                if uncertainty_art.primary_nav_diff_interval:
                    p_nav_lower = uncertainty_art.primary_nav_diff_interval[0]
                if uncertainty_art.primary_economic_interval:
                    p_econ_lower = uncertainty_art.primary_economic_interval[0]
            except Exception:
                pass

        # Compute exact reviewed result digest for acceptance binding
        cand_inventory = [r["receipt_id"] for r in sorted_receipts if "receipt_id" in r]
        ref_inventory = [r["receipt_id"] for r in sorted_ref] if sorted_ref else []
        exact_result_payload = {
            "freeze_hash": frozen.freeze_hash,
            "protocol_hash": frozen.protocol.protocol_hash,
            "observed_sessions": observed_count,
            "evidence_inventory": cand_inventory,
            "reference_evidence_inventory": ref_inventory,
            "primary_economic_advantage": str(pea) if pea is not None else None,
        }
        exact_result_digest = content_hash(exact_result_payload)

        # Verified independent acceptance
        is_independently_accepted = False
        acpt_rcpt_raw = host_config.get(
            "independent_acceptance_receipt"
        ) or host_config.get("acceptance_receipt")
        if acpt_rcpt_raw:
            acpt_rcpt: dict[str, Any] | None = None
            if isinstance(acpt_rcpt_raw, str):
                resolved_acpt = receipt_store.get(acpt_rcpt_raw)
                if isinstance(resolved_acpt, dict):
                    acpt_rcpt = resolved_acpt
                elif isinstance(resolved_acpt, (bytes, str)):
                    try:
                        acpt_rcpt = json.loads(
                            resolved_acpt
                            if isinstance(resolved_acpt, str)
                            else resolved_acpt.decode("utf-8")
                        )
                    except Exception:
                        pass
            elif isinstance(acpt_rcpt_raw, dict):
                acpt_rcpt = acpt_rcpt_raw

            if acpt_rcpt and isinstance(acpt_rcpt, dict):
                acpt_auth = acpt_rcpt.get("authority_id")
                auth_issuers = host_config.get("authenticated_issuers", {})

                # 1. Authority must have configured issuer credentials in host
                auth_configured = bool(
                    acpt_auth and acpt_auth in exec_roots and acpt_auth in auth_issuers
                )

                # 2. Reject contradictory binding fields
                binding_non_contradictory = True
                if (
                    acpt_rcpt.get("freeze_hash")
                    and acpt_rcpt["freeze_hash"] != frozen.freeze_hash
                ):
                    binding_non_contradictory = False
                if (
                    acpt_rcpt.get("protocol_hash")
                    and acpt_rcpt["protocol_hash"] != frozen.protocol.protocol_hash
                ):
                    binding_non_contradictory = False
                if acpt_rcpt.get("study_id") and acpt_rcpt["study_id"] not in (
                    frozen.protocol.study_id,
                    f"HIST-{frozen.protocol.study_id}",
                ):
                    binding_non_contradictory = False

                # Exact result binding: receipt must bind strictly to the exact
                # reviewed result digest
                acpt_result_digest = (
                    acpt_rcpt.get("result_digest")
                    or acpt_rcpt.get("result_hash")
                    or acpt_rcpt.get("reviewed_result_digest")
                    or acpt_rcpt.get("evidence_digest")
                )
                result_binding_ok = bool(
                    acpt_result_digest and acpt_result_digest == exact_result_digest
                )

                # 3. Status must be COMPLETED or ACCEPTED
                status_ok = acpt_rcpt.get("status") in ("COMPLETED", "ACCEPTED")

                # 4. Assessor independence and non-self-review explicitly verified
                indep_ok = (
                    acpt_rcpt.get("assessor_independence") is True
                    and acpt_rcpt.get("is_self_review") is False
                    and acpt_rcpt.get("conflicted") is not True
                    and bool(acpt_rcpt.get("independence_declaration"))
                )

                # 5. Authenticate receipt bytes (required content hash
                # AND valid cryptographic signature)
                rcpt_bytes_ok = False
                declared_hash = acpt_rcpt.get("receipt_hash") or acpt_rcpt.get(
                    "evidence_hash"
                )
                sig = (
                    acpt_rcpt.get("signature")
                    or acpt_rcpt.get("token")
                    or acpt_rcpt.get("hmac")
                )

                if auth_configured and declared_hash and sig:
                    body = {
                        k: v
                        for k, v in acpt_rcpt.items()
                        if k
                        not in (
                            "receipt_hash",
                            "evidence_hash",
                            "signature",
                            "token",
                            "hmac",
                        )
                    }
                    computed_hash = content_hash(body)
                    if declared_hash == computed_hash:
                        creds = auth_issuers[acpt_auth]
                        key = (
                            creds.get("hmac_key") if isinstance(creds, dict) else creds
                        )
                        if key:
                            key_b = key.encode("utf-8") if isinstance(key, str) else key
                            expected_sig = hmac.new(
                                key_b, canonical_json(body), hashlib.sha256
                            ).hexdigest()
                            if hmac.compare_digest(str(sig), expected_sig):
                                rcpt_bytes_ok = True

                if (
                    auth_configured
                    and binding_non_contradictory
                    and result_binding_ok
                    and status_ok
                    and indep_ok
                    and rcpt_bytes_ok
                ):
                    is_independently_accepted = True

        # Recompute outcome classification from verified execution evidence
        outcome = classify_study_outcome(
            scheduled_sessions=len(required_sessions),
            primary_economic_advantage=pea,
            primary_nav_diff_lower=p_nav_lower,
            primary_econ_lower=p_econ_lower,
            b_volatility=b_volatility,
            r_volatility=r_volatility,
            b_max_drawdown=b_max_drawdown,
            r_max_drawdown=r_max_drawdown,
            is_prospective_complete=False,
            is_independently_accepted=is_independently_accepted,
            unavailable_reasons=tuple(unavailable_reasons),
        )

        manifest = {
            "schema_version": "drift-stage1-historical-manifest/1",
            "study_id": f"HIST-{frozen.protocol.study_id}",
            "protocol_hash": frozen.protocol.protocol_hash,
            "freeze_hash": frozen.freeze_hash,
            "mode": frozen.protocol.mode,
            "scheduled_sessions": len(required_sessions),
            "observed_sessions": observed_count,
            "executed_at": datetime.now(UTC).isoformat(),
            "status": "COMPLETED",
            "primary_economic_advantage": str(pea) if pea is not None else None,
            "optimal_block_length": opt_b_length,
            "block_length_diagnostics": block_diagnostics,
            "outcome_classification": outcome.model_dump(mode="json"),
            "evidence_inventory": cand_inventory,
            "reference_evidence_inventory": ref_inventory,
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
        # (Finding 6, Round 18 & Round 19)
        private_root = Path(args.private_root).resolve()
        private_root.mkdir(parents=True, exist_ok=True)

        with _registration_lock(private_root, reg.registration_id):
            _recover_uncommitted_publication(private_root, reg.registration_id)

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
                if (
                    step_reg.observed_session_count
                    != cur_reg.observed_session_count + 1
                ):
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
                    ev_store = host_config.get(
                        "session_evidence_store"
                    ) or host_config.get("session_evidence_history")
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
                if reg.observed_session_count >= len(
                    reg.frozen_study.plan.scheduled_dates
                ):
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
                    sys.stderr.write(
                        "No eligible trading sessions remaining in calendar\n"
                    )
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
                sys.stderr.write(
                    "Prospective step requires verified session_evidence\n"
                )
                return 3

            # 5. Conflict detection: check if target step file or evidence file
            # already exists (Finding 6 & Round 19)
            target_idx = reg.observed_session_count + 1
            step_fname = f"{reg.registration_id}-step-{target_idx}.json"
            out_path = private_root / step_fname
            step_ev_fname = f"{reg.registration_id}-evidence-{target_idx}.json"
            step_ev_path = private_root / step_ev_fname

            if out_path.exists() and step_ev_path.exists():
                sys.stderr.write(
                    f"CONFLICT_ERROR: step file {step_fname} and evidence file "
                    f"already exist\n"
                )
                return 3

            if (
                reg.last_observed_session is not None
                and step_date <= reg.last_observed_session
            ):
                sys.stderr.write(
                    f"SESSION_DATE_NOT_SEQUENTIAL: session date {step_date} <= "
                    f"last observed session {reg.last_observed_session}\n"
                )
                return 3

            advanced = advance_prospective_session(
                reg,
                session_date=step_date,
                session_evidence=ev_data,
                calendar=calendar_dates,
                artifact_store=artifact_store,
                trust_roots=trust_roots,
                producer_verifier=prod_verifier,
            )
            _publish_prospective_step_pair(
                ev_path=step_ev_path,
                ev_data=(
                    ev_data
                    if isinstance(ev_data, dict)
                    else ev_data.model_dump(mode="json")
                ),
                step_path=out_path,
                step_data=advanced.model_dump(mode="json"),
            )
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

    hrun = subparsers.add_parser("historical-run")
    hrun.add_argument("--frozen", required=True)
    hrun.add_argument("--host-config", required=True)
    hrun.add_argument("--output", required=True)
    hrun.add_argument("--ledger-dir", required=False, default=None)
    hrun.add_argument("--session-count", type=int, required=False, default=None)
    hrun.add_argument("--authority", required=False, default=None)
    hrun.add_argument("--update-host-config", action="store_true", default=False)

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

    vmd = subparsers.add_parser("verify-market-data")
    vmd.add_argument("--request-end", required=False, default=None)
    vmd.add_argument("--as-of", required=False, default=None)
    vmd.add_argument("--with-fixtures", action="store_true", default=False)
    vmd.add_argument("--output", required=False, default=None)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "inventory": action_inventory,
        "assess": action_assess,
        "verify-market-data": action_verify_market_data,
        "calibrate": action_calibrate,
        "freeze": action_freeze,
        "verify-freeze": action_verify_freeze,
        "historical": action_historical,
        "historical-run": action_historical_run,
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
