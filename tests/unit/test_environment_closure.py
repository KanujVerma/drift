"""Unit tests for M1e macOS/arm64 environment closure contracts and verification."""

from datetime import UTC, datetime
from uuid import uuid7

import pytest

from drift.datasets.resolver import VerifiedArtifactBytes
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
from drift.qualification.environment import (
    build_environment_closure,
    verify_environment_closure,
)

H = tuple(f"{index:064x}" for index in range(1, 35))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _make_verified(data: bytes) -> VerifiedArtifactBytes:
    import hashlib

    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=hashlib.sha256(data).hexdigest(),
    )


def test_environment_artifact_kind_enumeration() -> None:
    # Closed set of 19 environment artifact categories
    assert len(EnvironmentArtifactKind) == 19
    expected = {
        "git_archive",
        "drift_sdist",
        "drift_wheel",
        "project_metadata",
        "uv_lock",
        "pylock",
        "uv_executable",
        "python_distribution",
        "package_wheel",
        "package_sdist",
        "build_toolchain",
        "standard_library",
        "system_library",
        "tzif",
        "source_snapshot",
        "restore_recipe",
        "vulnerability_evidence",
        "offline_evidence",
        "fresh_target_evidence",
    }
    actual = {kind.value for kind in EnvironmentArtifactKind}
    assert actual == expected
    # Copied venv is explicitly rejected as an artifact class
    assert "venv" not in actual
    assert "copied_venv" not in actual


def test_platform_identity_macos_arm64_confinement() -> None:
    # Platform must be macos and arm64
    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A348",
        kernel_compatibility="Darwin 24.0.0",
        hardware_class="Apple Silicon",
        declared_host_assumptions=("posix_signals", "deterministic_fs"),
    )
    assert platform.os_name == "macos"
    assert platform.architecture == "arm64"


def test_package_and_system_library_identities() -> None:
    pkg = PackageArtifactV1(
        schema_version="1",
        package_name="pydantic-core",
        version="2.14.0",
        filename="pydantic_core-2.14.0-cp314-cp314-macosx_11_0_arm64.whl",
        content_hash=H[0],
        origin="pypi",
        compatible_tags=("cp314-cp314-macosx_11_0_arm64",),
        build_toolchain_hashes=(H[1],),
        installed_file_inventory_hash=H[2],
    )
    assert pkg.package_name == "pydantic-core"

    sys_lib = SystemLibraryIdentityV1(
        schema_version="1",
        library_name="libSystem.B.dylib",
        version_or_build="1345.100.2",
        architecture="arm64",
        digest=H[3],
        relevance="core_c_runtime",
    )
    assert sys_lib.architecture == "arm64"


def test_python_runtime_identity() -> None:
    runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=H[4],
        distribution_artifact_hash=H[5],
        native_library_links=("libSystem.B.dylib",),
    )
    assert runtime.version == "3.14.5"
    assert runtime.implementation == "cpython"


def test_environment_closure_hash_integrity_and_mutation() -> None:
    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A348",
        kernel_compatibility="Darwin 24.0.0",
        hardware_class="Apple Silicon",
        declared_host_assumptions=("posix",),
    )
    runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=H[4],
        distribution_artifact_hash=H[5],
        native_library_links=("libSystem.B.dylib",),
    )
    pkg = PackageArtifactV1(
        schema_version="1",
        package_name="pydantic",
        version="2.14.0",
        filename="pydantic-2.14.0-py3-none-any.whl",
        content_hash=H[6],
        origin="pypi",
        compatible_tags=("py3-none-any",),
        build_toolchain_hashes=(),
        installed_file_inventory_hash=H[7],
    )
    sys_lib = SystemLibraryIdentityV1(
        schema_version="1",
        library_name="libSystem.B.dylib",
        version_or_build="1345.100.2",
        architecture="arm64",
        digest=H[8],
        relevance="system",
    )
    env_art = EnvironmentArtifactV1(
        schema_version="1",
        artifact_kind=EnvironmentArtifactKind.PROJECT_METADATA,
        artifact_reference=f"drift+sha256://{H[9]}",
        content_hash=H[9],
        byte_size=1234,
        media_type="application/toml",
        platform_applicability="all",
        origin="repo",
        rights_binding_hash=None,
    )

    unhashed = EnvironmentClosureV1.model_construct(
        schema_version="1",
        closure_id=uuid7(),
        closure_version="1",
        created_at=NOW,
        semantic_policy_hashes=(H[10],),
        git_commit="e072665",
        git_tree_hash=H[11],
        git_archive_hash=H[12],
        drift_wheel_hash=H[13],
        drift_sdist_hash=H[14],
        pyproject_toml_hash=H[9],
        uv_lock_hash=H[15],
        pylock_toml_hash=H[16],
        uv_executable_hash=H[17],
        python_runtime=runtime,
        package_artifacts=(pkg,),
        system_libraries=(sys_lib,),
        tzif_hash=H[18],
        source_snapshot_hash=H[19],
        restore_recipe_hash=H[20],
        platform=platform,
        vulnerability_evidence_hash=H[21],
        security_lane="safe_development",
        environment_artifacts=(env_art,),
        closure_hash="0" * 64,
    )
    closure = unhashed.model_copy(
        update={"closure_hash": environment_closure_hash(unhashed)}
    )
    assert len(closure.closure_hash) == 64

    # Any semantic mutation without updating hash fails validation
    with pytest.raises(ValueError, match="closure hash mismatch"):
        closure.model_copy(update={"git_commit": "mutated_commit"})

    with pytest.raises(ValueError, match="closure hash mismatch"):
        closure.model_copy(update={"git_tree_hash": H[0]})

    with pytest.raises(ValueError, match="closure hash mismatch"):
        closure.model_copy(
            update={
                "package_artifacts": (pkg.model_copy(update={"version": "2.14.1"}),)
            }
        )

    with pytest.raises(ValueError, match="closure hash mismatch"):
        closure.model_copy(
            update={"platform": platform.model_copy(update={"os_build": "24B999"})}
        )

    for field in (
        "git_archive_hash",
        "drift_wheel_hash",
        "drift_sdist_hash",
        "pyproject_toml_hash",
        "uv_lock_hash",
        "pylock_toml_hash",
        "uv_executable_hash",
        "tzif_hash",
        "source_snapshot_hash",
        "restore_recipe_hash",
        "vulnerability_evidence_hash",
    ):
        with pytest.raises(ValueError, match="closure hash mismatch"):
            closure.model_copy(update={field: H[30]})

    with pytest.raises(ValueError, match="closure hash mismatch"):
        closure.model_copy(
            update={"python_runtime": runtime.model_copy(update={"version": "3.14.6"})}
        )


def test_build_and_verify_environment_closure() -> None:
    git_archive_bytes = _make_verified(b"git archive mock bytes")
    wheel_bytes = _make_verified(b"drift wheel mock bytes")
    sdist_bytes = _make_verified(b"drift sdist mock bytes")
    pyproject_bytes = _make_verified(b"pyproject.toml mock bytes")
    uv_lock_bytes = _make_verified(b"uv.lock mock bytes")
    pylock_bytes = _make_verified(b"pylock.toml mock bytes")
    uv_bin_bytes = _make_verified(b"uv executable mock bytes")
    python_archive_bytes = _make_verified(b"python distribution mock bytes")
    pkg_wheel_bytes = _make_verified(b"pkg wheel bytes")
    tzif_bytes = _make_verified(b"tzif mock bytes")
    snapshot_bytes = _make_verified(b"snapshot mock bytes")
    recipe_bytes = _make_verified(b"restore recipe mock script")
    vuln_bytes = _make_verified(b"vulnerability assessment json")

    artifacts = {
        git_archive_bytes.content_hash: git_archive_bytes,
        wheel_bytes.content_hash: wheel_bytes,
        sdist_bytes.content_hash: sdist_bytes,
        pyproject_bytes.content_hash: pyproject_bytes,
        uv_lock_bytes.content_hash: uv_lock_bytes,
        pylock_bytes.content_hash: pylock_bytes,
        uv_bin_bytes.content_hash: uv_bin_bytes,
        python_archive_bytes.content_hash: python_archive_bytes,
        pkg_wheel_bytes.content_hash: pkg_wheel_bytes,
        tzif_bytes.content_hash: tzif_bytes,
        snapshot_bytes.content_hash: snapshot_bytes,
        recipe_bytes.content_hash: recipe_bytes,
        vuln_bytes.content_hash: vuln_bytes,
    }

    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A348",
        kernel_compatibility="Darwin 24.0.0",
        hardware_class="Apple Silicon",
        declared_host_assumptions=("posix",),
    )

    runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=H[0],
        distribution_artifact_hash=python_archive_bytes.content_hash,
        native_library_links=("libSystem.B.dylib",),
    )

    pkg = PackageArtifactV1(
        schema_version="1",
        package_name="test-pkg",
        version="1.0.0",
        filename="test_pkg-1.0.0-py3-none-any.whl",
        content_hash=pkg_wheel_bytes.content_hash,
        origin="pypi",
        compatible_tags=("py3-none-any",),
        build_toolchain_hashes=(),
        installed_file_inventory_hash=H[1],
    )

    closure = build_environment_closure(
        closure_id=uuid7(),
        created_at=NOW,
        git_commit="e072665",
        git_tree_hash=H[2],
        git_archive_hash=git_archive_bytes.content_hash,
        drift_wheel_hash=wheel_bytes.content_hash,
        drift_sdist_hash=sdist_bytes.content_hash,
        pyproject_toml_hash=pyproject_bytes.content_hash,
        uv_lock_hash=uv_lock_bytes.content_hash,
        pylock_toml_hash=pylock_bytes.content_hash,
        uv_executable_hash=uv_bin_bytes.content_hash,
        python_runtime=runtime,
        package_artifacts=(pkg,),
        system_libraries=(),
        tzif_hash=tzif_bytes.content_hash,
        source_snapshot_hash=snapshot_bytes.content_hash,
        restore_recipe_hash=recipe_bytes.content_hash,
        platform=platform,
        vulnerability_evidence_hash=vuln_bytes.content_hash,
        semantic_policy_hashes=(H[3],),
        security_lane="safe_development",
        artifacts=artifacts,
    )

    # Verify closure passes
    verify_environment_closure(closure, artifacts)

    # Missing artifact fails verification
    missing_artifacts = dict(artifacts)
    del missing_artifacts[wheel_bytes.content_hash]
    with pytest.raises(ValueError, match="missing required closure artifact"):
        verify_environment_closure(closure, missing_artifacts)

    # Tampered byte content fails verification
    tampered_artifacts = dict(artifacts)
    tampered_wheel = VerifiedArtifactBytes(
        data=b"tampered wheel bytes",
        byte_size=len(b"tampered wheel bytes"),
        content_hash=wheel_bytes.content_hash,  # Claimed hash differs from data
    )
    tampered_artifacts[wheel_bytes.content_hash] = tampered_wheel
    with pytest.raises(ValueError, match="content hash mismatch"):
        verify_environment_closure(closure, tampered_artifacts)


def test_build_environment_closure_rejects_missing_artifacts() -> None:
    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A348",
        kernel_compatibility="Darwin 24.0.0",
        hardware_class="Apple Silicon",
        declared_host_assumptions=("posix",),
    )
    runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=H[0],
        distribution_artifact_hash=H[1],
        native_library_links=(),
    )
    with pytest.raises(ValueError, match="missing from artifacts"):
        build_environment_closure(
            closure_id=uuid7(),
            created_at=NOW,
            git_commit="e072665",
            git_tree_hash=H[2],
            git_archive_hash=H[3],
            drift_wheel_hash=H[4],
            drift_sdist_hash=H[5],
            pyproject_toml_hash=H[6],
            uv_lock_hash=H[7],
            pylock_toml_hash=H[8],
            uv_executable_hash=H[9],
            python_runtime=runtime,
            package_artifacts=(),
            system_libraries=(),
            tzif_hash=H[10],
            source_snapshot_hash=H[11],
            restore_recipe_hash=H[12],
            platform=platform,
            vulnerability_evidence_hash=H[13],
            semantic_policy_hashes=(),
            security_lane="safe_development",
            artifacts={},
        )


def test_verify_environment_closure_system_libraries_and_byte_sizes() -> None:
    git_archive_bytes = _make_verified(b"git archive mock bytes")
    wheel_bytes = _make_verified(b"drift wheel mock bytes")
    sdist_bytes = _make_verified(b"drift sdist mock bytes")
    pyproject_bytes = _make_verified(b"pyproject.toml mock bytes")
    uv_lock_bytes = _make_verified(b"uv.lock mock bytes")
    pylock_bytes = _make_verified(b"pylock.toml mock bytes")
    uv_bin_bytes = _make_verified(b"uv executable mock bytes")
    python_archive_bytes = _make_verified(b"python distribution mock bytes")
    tzif_bytes = _make_verified(b"tzif mock bytes")
    snapshot_bytes = _make_verified(b"snapshot mock bytes")
    recipe_bytes = _make_verified(b"restore recipe mock script")
    vuln_bytes = _make_verified(b"vulnerability assessment json")
    sys_lib_bytes = _make_verified(b"libSystem.B.dylib binary bytes")

    artifacts = {
        git_archive_bytes.content_hash: git_archive_bytes,
        wheel_bytes.content_hash: wheel_bytes,
        sdist_bytes.content_hash: sdist_bytes,
        pyproject_bytes.content_hash: pyproject_bytes,
        uv_lock_bytes.content_hash: uv_lock_bytes,
        pylock_bytes.content_hash: pylock_bytes,
        uv_bin_bytes.content_hash: uv_bin_bytes,
        python_archive_bytes.content_hash: python_archive_bytes,
        tzif_bytes.content_hash: tzif_bytes,
        snapshot_bytes.content_hash: snapshot_bytes,
        recipe_bytes.content_hash: recipe_bytes,
        vuln_bytes.content_hash: vuln_bytes,
        sys_lib_bytes.content_hash: sys_lib_bytes,
    }

    platform = PlatformIdentityV1(
        schema_version="1",
        os_name="macos",
        architecture="arm64",
        os_build="24A348",
        kernel_compatibility="Darwin 24.0.0",
        hardware_class="Apple Silicon",
        declared_host_assumptions=("posix",),
    )
    runtime = PythonRuntimeIdentityV1(
        schema_version="1",
        implementation="cpython",
        version="3.14.5",
        build="v3.14.5:darwin",
        executable="bin/python3.14",
        standard_library_inventory_hash=H[0],
        distribution_artifact_hash=python_archive_bytes.content_hash,
        native_library_links=("libSystem.B.dylib",),
    )
    sys_lib = SystemLibraryIdentityV1(
        schema_version="1",
        library_name="libSystem.B.dylib",
        version_or_build="1345.100.2",
        architecture="arm64",
        digest=sys_lib_bytes.content_hash,
        relevance="system",
    )

    closure = build_environment_closure(
        closure_id=uuid7(),
        created_at=NOW,
        git_commit="e072665",
        git_tree_hash=H[2],
        git_archive_hash=git_archive_bytes.content_hash,
        drift_wheel_hash=wheel_bytes.content_hash,
        drift_sdist_hash=sdist_bytes.content_hash,
        pyproject_toml_hash=pyproject_bytes.content_hash,
        uv_lock_hash=uv_lock_bytes.content_hash,
        pylock_toml_hash=pylock_bytes.content_hash,
        uv_executable_hash=uv_bin_bytes.content_hash,
        python_runtime=runtime,
        package_artifacts=(),
        system_libraries=(sys_lib,),
        tzif_hash=tzif_bytes.content_hash,
        source_snapshot_hash=snapshot_bytes.content_hash,
        restore_recipe_hash=recipe_bytes.content_hash,
        platform=platform,
        vulnerability_evidence_hash=vuln_bytes.content_hash,
        semantic_policy_hashes=(),
        security_lane="safe_development",
        artifacts=artifacts,
    )
    verify_environment_closure(closure, artifacts)

    # Missing system library digest fails verification
    missing_syslib = dict(artifacts)
    del missing_syslib[sys_lib_bytes.content_hash]
    with pytest.raises(ValueError, match="missing required closure artifact"):
        verify_environment_closure(closure, missing_syslib)

    # Byte size mismatch in environment artifact fails verification
    tampered_size = VerifiedArtifactBytes(
        data=wheel_bytes.data,
        byte_size=len(wheel_bytes.data) + 10,
        content_hash=wheel_bytes.content_hash,
    )
    tampered_artifacts = dict(artifacts)
    tampered_artifacts[wheel_bytes.content_hash] = tampered_size
    with pytest.raises(ValueError, match="byte size mismatch"):
        verify_environment_closure(closure, tampered_artifacts)
