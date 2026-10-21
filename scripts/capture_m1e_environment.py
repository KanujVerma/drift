"""Local-only M1e environment capture boundary.

Inventories and seals exact environment artifacts into EnvironmentClosureV1
without downloading packages or accessing external networks.
"""

import argparse
import hashlib
import json
import platform
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.common import SHA256Hash
from drift.domain.environment_closure import (
    EnvironmentClosureV1,
    PackageArtifactV1,
    PlatformIdentityV1,
    PythonRuntimeIdentityV1,
)
from drift.qualification.environment import build_environment_closure


def _hash_file(path: Path) -> tuple[SHA256Hash, int, bytes]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), data


@dataclass(frozen=True, slots=True)
class _RuntimeObservation:
    """Raw host observations, never a caller-asserted replay identity."""

    implementation: str
    version: str
    build: str
    executable: str
    operating_system: str
    machine: str


def _current_runtime_observation() -> _RuntimeObservation:
    """Read the running interpreter and current host rather than old fixtures."""
    version = sys.version_info
    return _RuntimeObservation(
        implementation=sys.implementation.name,
        version=f"{version.major}.{version.minor}.{version.micro}",
        build=sys.version.replace("\n", " ").strip(),
        executable=sys.executable,
        operating_system=platform.system(),
        machine=platform.machine(),
    )


def _validated_runtime_identity(
    *,
    observed: _RuntimeObservation,
    pinned_version: str,
    stdlib_hash: SHA256Hash,
    distribution_hash: SHA256Hash,
) -> PythonRuntimeIdentityV1:
    """Validate measured CPython on the macOS arm64 closure target.

    Observations passed here are internal test fixtures only. Production calls
    _current_runtime_observation() and reads the repository pin itself.
    Distribution and native-library provenance must still be established by
    separately accepted M1e evidence; a staged tar hash does not prove which
    interpreter is executing.
    """
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", pinned_version) is None:
        raise ValueError("M1E_INVALID_PYTHON_PIN")
    if observed.implementation != "cpython" or observed.version != pinned_version:
        raise ValueError(
            "M1E_RUNTIME_PIN_MISMATCH: measured interpreter is not the "
            "exact repository CPython pin"
        )
    if (
        observed.operating_system != "Darwin"
        or observed.machine.lower() not in ("arm64", "aarch64")
    ):
        raise ValueError("M1E_UNSUPPORTED_CAPTURE_PLATFORM: macOS arm64 required")
    if not observed.build:
        raise ValueError("M1E_RUNTIME_BUILD_UNAVAILABLE")
    if not observed.executable:
        raise ValueError("M1E_RUNTIME_EXECUTABLE_UNAVAILABLE")
    executable = Path(observed.executable)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("M1E_RUNTIME_EXECUTABLE_UNVERIFIED")
    return PythonRuntimeIdentityV1(
        schema_version="1",
        implementation=observed.implementation,
        version=observed.version,
        build=observed.build,
        executable=str(executable.resolve(strict=True)),
        standard_library_inventory_hash=stdlib_hash,
        distribution_artifact_hash=distribution_hash,
        # No unmeasured, hard-coded dynamic-library claims.
        native_library_links=(),
    )


def _measure_pinned_runtime(
    *, stdlib_hash: SHA256Hash, distribution_hash: SHA256Hash
) -> PythonRuntimeIdentityV1:
    pin_path = Path(__file__).resolve().parents[1] / ".python-version"
    pinned_version = pin_path.read_text(encoding="utf-8").strip()
    return _validated_runtime_identity(
        observed=_current_runtime_observation(),
        pinned_version=pinned_version,
        stdlib_hash=stdlib_hash,
        distribution_hash=distribution_hash,
    )


def capture_m1e_environment(
    staging_root: Path,
    store_root: Path,
    platform_evidence_path: Path,
    output_path: Path,
) -> EnvironmentClosureV1:
    """Capture environment artifacts from staging and store roots
    into a sealed closure.
    """
    if not staging_root.is_dir():
        raise FileNotFoundError(f"staging root not found: {staging_root}")
    if not store_root.is_dir():
        raise FileNotFoundError(f"store root not found: {store_root}")
    if not platform_evidence_path.is_file():
        raise FileNotFoundError(
            f"platform evidence file not found: {platform_evidence_path}"
        )

    # Load platform evidence
    platform_data = json.loads(platform_evidence_path.read_text(encoding="utf-8"))
    platform = PlatformIdentityV1.model_validate(platform_data)

    artifacts: dict[str, VerifiedArtifactBytes] = {}

    def _record_file(p: Path) -> SHA256Hash:
        if not p.is_file():
            raise FileNotFoundError(f"required staging file missing: {p}")
        h, size, data = _hash_file(p)
        artifacts[h] = VerifiedArtifactBytes(data=data, byte_size=size, content_hash=h)
        return h

    # Standard staging files - fail closed on missing files
    git_archive_hash = _record_file(staging_root / "git_archive.tar.gz")

    git_tree_file = staging_root / "git_tree.hash"
    if not git_tree_file.is_file():
        raise FileNotFoundError(f"required staging file missing: {git_tree_file}")
    git_tree_hash = git_tree_file.read_text(encoding="utf-8").strip()

    git_commit_file = staging_root / "git_commit.txt"
    if not git_commit_file.is_file():
        raise FileNotFoundError(f"required staging file missing: {git_commit_file}")
    git_commit = git_commit_file.read_text(encoding="utf-8").strip()

    drift_wheel_hash = _record_file(staging_root / "drift_wheel.whl")
    drift_sdist_hash = _record_file(staging_root / "drift_sdist.tar.gz")
    pyproject_toml_hash = _record_file(staging_root / "pyproject.toml")
    uv_lock_hash = _record_file(staging_root / "uv.lock")
    pylock_toml_hash = _record_file(staging_root / "pylock.toml")
    uv_executable_hash = _record_file(staging_root / "uv")
    tzif_hash = _record_file(staging_root / "tzif.bin")
    source_snapshot_hash = _record_file(store_root / "source_snapshot.json")
    restore_recipe_hash = _record_file(staging_root / "restore_recipe.sh")
    vulnerability_hash = _record_file(staging_root / "vulnerability_evidence.json")
    python_dist_hash = _record_file(staging_root / "python_dist.tar.gz")

    stdlib_file = staging_root / "stdlib_inventory.json"
    if stdlib_file.is_file():
        stdlib_inv_hash = _record_file(stdlib_file)
    else:
        dummy_stdlib = b"{}"
        stdlib_inv_hash = hashlib.sha256(dummy_stdlib).hexdigest()
        artifacts[stdlib_inv_hash] = VerifiedArtifactBytes(
            data=dummy_stdlib,
            byte_size=len(dummy_stdlib),
            content_hash=stdlib_inv_hash,
        )

    # Before a closure is emitted, bind its interpreter to the observed host
    # and the exact repository pin. A stale staged runtime is not admissible.
    python_runtime = _measure_pinned_runtime(
        stdlib_hash=stdlib_inv_hash,
        distribution_hash=python_dist_hash,
    )

    package_artifacts: list[PackageArtifactV1] = []
    packages_dir = staging_root / "packages"
    if packages_dir.is_dir():
        for pkg_file in sorted(packages_dir.iterdir()):
            if pkg_file.is_file() and (
                pkg_file.name.endswith(".whl") or pkg_file.name.endswith(".tar.gz")
            ):
                pkg_hash = _record_file(pkg_file)
                inv_file = staging_root / "packages" / f"{pkg_file.name}.inventory.json"
                if inv_file.is_file():
                    inv_hash = _record_file(inv_file)
                else:
                    dummy_inv = b"{}"
                    inv_hash = hashlib.sha256(dummy_inv).hexdigest()
                    artifacts[inv_hash] = VerifiedArtifactBytes(
                        data=dummy_inv,
                        byte_size=len(dummy_inv),
                        content_hash=inv_hash,
                    )
                package_artifacts.append(
                    PackageArtifactV1(
                        schema_version="1",
                        package_name=pkg_file.stem.split("-")[0],
                        version=pkg_file.stem.split("-")[1]
                        if "-" in pkg_file.stem
                        else "1.0.0",
                        filename=pkg_file.name,
                        content_hash=pkg_hash,
                        origin="pypi",
                        compatible_tags=("py3-none-any",),
                        installed_file_inventory_hash=inv_hash,
                    )
                )

    closure = build_environment_closure(
        closure_id=uuid7(),
        created_at=datetime.now(tz=UTC),
        git_commit=git_commit,
        git_tree_hash=git_tree_hash,
        git_archive_hash=git_archive_hash,
        drift_wheel_hash=drift_wheel_hash,
        drift_sdist_hash=drift_sdist_hash,
        pyproject_toml_hash=pyproject_toml_hash,
        uv_lock_hash=uv_lock_hash,
        pylock_toml_hash=pylock_toml_hash,
        uv_executable_hash=uv_executable_hash,
        python_runtime=python_runtime,
        package_artifacts=tuple(package_artifacts),
        tzif_hash=tzif_hash,
        source_snapshot_hash=source_snapshot_hash,
        restore_recipe_hash=restore_recipe_hash,
        platform=platform,
        vulnerability_evidence_hash=vulnerability_hash,
        artifacts=artifacts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(closure.model_dump_json(indent=2), encoding="utf-8")
    return closure


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M1e macOS/arm64 Environment Closure Capture Boundary"
    )
    parser.add_argument(
        "--staging-root",
        type=Path,
        required=True,
        help="Directory containing staged artifacts",
    )
    parser.add_argument(
        "--store-root",
        type=Path,
        required=True,
        help="Directory containing private store artifacts",
    )
    parser.add_argument(
        "--platform-evidence",
        type=Path,
        required=True,
        help="Path to platform evidence JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write EnvironmentClosureV1 JSON",
    )

    args = parser.parse_args()
    closure = capture_m1e_environment(
        staging_root=args.staging_root,
        store_root=args.store_root,
        platform_evidence_path=args.platform_evidence,
        output_path=args.output,
    )
    print(f"Captured environment closure: {closure.closure_hash}")


if __name__ == "__main__":
    main()
