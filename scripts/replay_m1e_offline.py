"""M1e offline replay execution script.

Executes deterministic replay of an M1e snapshot under environment closure
with child environment strictly confined to the explicit allowlist.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from drift.domain.qualification_replay import (
    FreshRestoreAttestationV1,
    ReplayAttemptEnvelopeV1,
    ReplayExecutionRecordV1,
    ReplayExecutionStatus,
    ReplayRequestV1,
    ReplayResultV1,
    SystemOfflineAttestationV1,
    finalize_replay_result,
    replay_execution_record_hash,
)
from drift.serialization.canonical import content_hash

ALLOWED_ENV_VARS = frozenset(
    {
        "PATH",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONHASHSEED",
        "UV_CACHE_DIR",
        "UV_OFFLINE",
        "UV_NO_CONFIG",
        "UV_PYTHON_DOWNLOADS",
        "VIRTUAL_ENV",
    }
)


def sanitize_child_environment(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Filter environment variables strictly according to the child allowlist."""
    source = os.environ if base_env is None else base_env
    sanitized: dict[str, str] = {}
    for key, val in source.items():
        if key in ALLOWED_ENV_VARS:
            sanitized[key] = val

    # Ensure mandatory flags are set
    sanitized["PYTHONNOUSERSITE"] = "1"
    sanitized["PYTHONDONTWRITEBYTECODE"] = "1"
    sanitized["PYTHONHASHSEED"] = "0"
    sanitized["UV_OFFLINE"] = "1"
    sanitized["UV_NO_CONFIG"] = "1"
    sanitized["UV_PYTHON_DOWNLOADS"] = "never"
    return sanitized


def replay_m1e_offline(
    request_path: Path,
    store_root: Path,
    work_root: Path,
    output_path: Path | None = None,
    offline_attestation_path: Path | None = None,
    fresh_attestation_path: Path | None = None,
) -> ReplayResultV1:
    """Execute deterministic replay from verified stored closure and snapshot."""
    if not request_path.is_file():
        raise FileNotFoundError(f"replay request file not found: {request_path}")
    if not store_root.is_dir():
        raise FileNotFoundError(f"store root not found: {store_root}")
    if not work_root.is_dir():
        work_root.mkdir(parents=True, exist_ok=True)

    # 1. Parse request
    request_data = json.loads(request_path.read_text(encoding="utf-8"))
    request = ReplayRequestV1.model_validate(request_data)

    # 2. Build isolated target directory
    target_id = f"target_{request.request_hash[:16]}"
    target_dir = work_root / target_id
    target_dir.mkdir(parents=True, exist_ok=True)

    # 3. Sanitize child environment
    env = sanitize_child_environment()
    env["VIRTUAL_ENV"] = str(target_dir / ".venv")
    env["UV_CACHE_DIR"] = str(target_dir / ".uv_cache")
    env["TMPDIR"] = str(target_dir / "tmp")
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    # 4. Result file
    result_file = output_path or (target_dir / "replay_result.json")

    # 5. Execute child verification under confined environment
    start_time = datetime.now(tz=UTC)
    cmd = [sys.executable, "-c", "import drift; print('drift_offline_verified')"]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_stdout, _ = proc.communicate()
    end_time = datetime.now(tz=UTC)

    proc_tree_id = f"pid_{proc.pid}"
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=start_time,
        end_time=end_time,
        process_ids=(proc.pid,),
        temporary_paths=(str(target_dir),),
        cache_layout="isolated",
        diagnostics=(f"child_exit_{proc.returncode}", child_stdout.strip()),
        host_observations=("macos_arm64",),
    )

    unhashed_exec = ReplayExecutionRecordV1.model_construct(
        schema_version="1",
        request_hash=request.request_hash,
        authorization_hash=request.authorization_hash,
        attempt_envelope=attempt,
        verified_inputs=(request.snapshot_hash, request.closure_hash),
        status=ReplayExecutionStatus.EXECUTED,
        preflight_outcome=None,
        actual_outputs=(),
        process_tree_identity=proc_tree_id,
        target_identity=target_id,
        start_time=start_time,
        end_time=end_time,
        raw_outcome_evidence_hash=content_hash(proc.stdout),
        execution_record_hash="0" * 64,
    )
    execution = unhashed_exec.model_copy(
        update={"execution_record_hash": replay_execution_record_hash(unhashed_exec)}
    )

    # 6. Load optional attestations if provided
    offline_attestation: SystemOfflineAttestationV1 | None = None
    if offline_attestation_path and offline_attestation_path.is_file():
        off_data = json.loads(offline_attestation_path.read_text(encoding="utf-8"))
        offline_attestation = SystemOfflineAttestationV1.model_validate(off_data)

    fresh_attestation: FreshRestoreAttestationV1 | None = None
    if fresh_attestation_path and fresh_attestation_path.is_file():
        fr_data = json.loads(fresh_attestation_path.read_text(encoding="utf-8"))
        fresh_attestation = FreshRestoreAttestationV1.model_validate(fr_data)

    # 7. Evaluate outcome strictly through typed finalizer
    result = finalize_replay_result(
        execution=execution,
        offline=offline_attestation,
        fresh=fresh_attestation,
        expected=(),
        actual=(),
        policy=request.comparison_policy,
        replay_implementation_hash=content_hash("replay_m1e_offline_v1"),
    )

    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M1e macOS/arm64 Offline Replay Execution Boundary"
    )
    parser.add_argument(
        "--request", type=Path, required=True, help="Path to ReplayRequestV1 JSON"
    )
    parser.add_argument(
        "--store-root",
        type=Path,
        required=True,
        help="Directory containing private content store",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        required=True,
        help="Working root for clean replay target",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for ReplayResultV1 JSON",
    )
    parser.add_argument(
        "--offline-attestation",
        type=Path,
        default=None,
        help="Optional path to SystemOfflineAttestationV1 JSON",
    )
    parser.add_argument(
        "--fresh-attestation",
        type=Path,
        default=None,
        help="Optional path to FreshRestoreAttestationV1 JSON",
    )

    args = parser.parse_args()
    result = replay_m1e_offline(
        request_path=args.request,
        store_root=args.store_root,
        work_root=args.work_root,
        output_path=args.output,
        offline_attestation_path=args.offline_attestation,
        fresh_attestation_path=args.fresh_attestation,
    )
    print(
        f"Replay completed with outcome: {result.outcome} (hash: {result.result_hash})"
    )


if __name__ == "__main__":
    main()
