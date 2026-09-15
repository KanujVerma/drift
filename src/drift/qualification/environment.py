"""Environment closure builders and verifiers for macOS/arm64 offline replay."""

import hashlib
from collections.abc import Mapping

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.common import UUID7, SHA256Hash, UTCDateTime
from drift.domain.environment_closure import (
    EnvironmentArtifactKind,
    EnvironmentArtifactV1,
    EnvironmentClosureV1,
    PackageArtifactV1,
    PlatformIdentityV1,
    PythonRuntimeIdentityV1,
    SystemLibraryIdentityV1,
    environment_closure_hash,
)


def build_environment_closure(
    *,
    closure_id: UUID7,
    created_at: UTCDateTime,
    git_commit: str,
    git_tree_hash: SHA256Hash,
    git_archive_hash: SHA256Hash,
    drift_wheel_hash: SHA256Hash,
    drift_sdist_hash: SHA256Hash,
    pyproject_toml_hash: SHA256Hash,
    uv_lock_hash: SHA256Hash,
    pylock_toml_hash: SHA256Hash,
    uv_executable_hash: SHA256Hash,
    python_runtime: PythonRuntimeIdentityV1,
    package_artifacts: tuple[PackageArtifactV1, ...],
    system_libraries: tuple[SystemLibraryIdentityV1, ...] = (),
    tzif_hash: SHA256Hash,
    source_snapshot_hash: SHA256Hash,
    restore_recipe_hash: SHA256Hash,
    platform: PlatformIdentityV1,
    vulnerability_evidence_hash: SHA256Hash,
    semantic_policy_hashes: tuple[SHA256Hash, ...] = (),
    security_lane: str = "safe_development",
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> EnvironmentClosureV1:
    """Build an authentic EnvironmentClosureV1 and compute its canonical hash."""
    env_artifacts: list[EnvironmentArtifactV1] = []

    # Map key artifacts to EnvironmentArtifactV1
    artifact_mappings = [
        (git_archive_hash, EnvironmentArtifactKind.GIT_ARCHIVE, "application/gzip"),
        (drift_wheel_hash, EnvironmentArtifactKind.DRIFT_WHEEL, "application/x-wheel"),
        (drift_sdist_hash, EnvironmentArtifactKind.DRIFT_SDIST, "application/gzip"),
        (
            pyproject_toml_hash,
            EnvironmentArtifactKind.PROJECT_METADATA,
            "application/toml",
        ),
        (uv_lock_hash, EnvironmentArtifactKind.UV_LOCK, "application/toml"),
        (pylock_toml_hash, EnvironmentArtifactKind.PYLOCK, "application/toml"),
        (
            uv_executable_hash,
            EnvironmentArtifactKind.UV_EXECUTABLE,
            "application/octet-stream",
        ),
        (
            python_runtime.distribution_artifact_hash,
            EnvironmentArtifactKind.PYTHON_DISTRIBUTION,
            "application/gzip",
        ),
        (tzif_hash, EnvironmentArtifactKind.TZIF, "application/octet-stream"),
        (
            source_snapshot_hash,
            EnvironmentArtifactKind.SOURCE_SNAPSHOT,
            "application/json",
        ),
        (
            restore_recipe_hash,
            EnvironmentArtifactKind.RESTORE_RECIPE,
            "text/x-shellscript",
        ),
        (
            vulnerability_evidence_hash,
            EnvironmentArtifactKind.VULNERABILITY_EVIDENCE,
            "application/json",
        ),
    ]

    for h, kind, mtype in artifact_mappings:
        if h not in artifacts:
            raise ValueError(
                f"required closure artifact {h} ({kind.value}) missing from artifacts"
            )
        vb = artifacts[h]
        env_artifacts.append(
            EnvironmentArtifactV1(
                schema_version="1",
                artifact_kind=kind,
                artifact_reference=f"drift+sha256://{h}",
                content_hash=h,
                byte_size=vb.byte_size,
                media_type=mtype,
                platform_applicability="all",
                origin="repo",
                rights_binding_hash=None,
            )
        )

    for pkg in package_artifacts:
        if pkg.content_hash not in artifacts:
            raise ValueError(
                f"package artifact {pkg.content_hash} missing from artifacts"
            )
        vb = artifacts[pkg.content_hash]
        kind = (
            EnvironmentArtifactKind.PACKAGE_SDIST
            if pkg.filename.endswith(".tar.gz") or pkg.filename.endswith(".zip")
            else EnvironmentArtifactKind.PACKAGE_WHEEL
        )
        env_artifacts.append(
            EnvironmentArtifactV1(
                schema_version="1",
                artifact_kind=kind,
                artifact_reference=f"drift+sha256://{pkg.content_hash}",
                content_hash=pkg.content_hash,
                byte_size=vb.byte_size,
                media_type="application/octet-stream",
                platform_applicability="macos_arm64",
                origin=pkg.origin,
                rights_binding_hash=None,
            )
        )

    unhashed = EnvironmentClosureV1.model_construct(
        schema_version="1",
        closure_id=closure_id,
        closure_version="1",
        created_at=created_at,
        semantic_policy_hashes=semantic_policy_hashes,
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
        package_artifacts=package_artifacts,
        system_libraries=system_libraries,
        tzif_hash=tzif_hash,
        source_snapshot_hash=source_snapshot_hash,
        restore_recipe_hash=restore_recipe_hash,
        platform=platform,
        vulnerability_evidence_hash=vulnerability_evidence_hash,
        security_lane=security_lane,
        environment_artifacts=tuple(env_artifacts),
        closure_hash="0" * 64,
    )
    return unhashed.model_copy(
        update={"closure_hash": environment_closure_hash(unhashed)}
    )


def verify_environment_closure(
    closure: EnvironmentClosureV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None:
    """Verify that an EnvironmentClosureV1 is valid and all component
    hashes match retained bytes.
    """
    expected_hash = environment_closure_hash(closure)
    if closure.closure_hash != expected_hash:
        raise ValueError(
            f"closure hash mismatch: expected {expected_hash}, "
            f"got {closure.closure_hash}"
        )

    # Check that required hashes are in artifacts and match bytes
    required_hashes = {
        closure.git_archive_hash,
        closure.drift_wheel_hash,
        closure.drift_sdist_hash,
        closure.pyproject_toml_hash,
        closure.uv_lock_hash,
        closure.pylock_toml_hash,
        closure.uv_executable_hash,
        closure.python_runtime.distribution_artifact_hash,
        closure.tzif_hash,
        closure.source_snapshot_hash,
        closure.restore_recipe_hash,
        closure.vulnerability_evidence_hash,
    }
    for pkg in closure.package_artifacts:
        required_hashes.add(pkg.content_hash)
    for sys_lib in closure.system_libraries:
        required_hashes.add(sys_lib.digest)
    for ea in closure.environment_artifacts:
        required_hashes.add(ea.content_hash)

    for h in required_hashes:
        if h not in artifacts:
            raise ValueError(f"missing required closure artifact: {h}")
        vb = artifacts[h]
        if vb.content_hash != h:
            raise ValueError(
                f"artifact descriptor hash mismatch: claimed {h}, "
                f"descriptor {vb.content_hash}"
            )
        actual_data_hash = hashlib.sha256(vb.data).hexdigest()
        if actual_data_hash != h:
            raise ValueError(
                f"artifact content hash mismatch: claimed {h}, "
                f"actual data hash {actual_data_hash}"
            )

    for ea in closure.environment_artifacts:
        vb = artifacts[ea.content_hash]
        if ea.byte_size != vb.byte_size or ea.byte_size != len(vb.data):
            raise ValueError(
                f"environment artifact byte size mismatch for {ea.content_hash}: "
                f"claimed {ea.byte_size}, actual {len(vb.data)}"
            )
