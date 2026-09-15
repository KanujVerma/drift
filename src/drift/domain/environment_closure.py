"""Domain models for macOS/arm64 environment closure and identities."""

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from drift.domain.common import UUID7, FrozenModel, SHA256Hash, UTCDateTime
from drift.serialization.canonical import content_hash


class EnvironmentArtifactKind(StrEnum):
    """Closed set of 19 environment artifact categories."""

    GIT_ARCHIVE = "git_archive"
    DRIFT_SDIST = "drift_sdist"
    DRIFT_WHEEL = "drift_wheel"
    PROJECT_METADATA = "project_metadata"
    UV_LOCK = "uv_lock"
    PYLOCK = "pylock"
    UV_EXECUTABLE = "uv_executable"
    PYTHON_DISTRIBUTION = "python_distribution"
    PACKAGE_WHEEL = "package_wheel"
    PACKAGE_SDIST = "package_sdist"
    BUILD_TOOLCHAIN = "build_toolchain"
    STANDARD_LIBRARY = "standard_library"
    SYSTEM_LIBRARY = "system_library"
    TZIF = "tzif"
    SOURCE_SNAPSHOT = "source_snapshot"
    RESTORE_RECIPE = "restore_recipe"
    VULNERABILITY_EVIDENCE = "vulnerability_evidence"
    OFFLINE_EVIDENCE = "offline_evidence"
    FRESH_TARGET_EVIDENCE = "fresh_target_evidence"


class EnvironmentArtifactV1(FrozenModel):
    """Exact reference, content hash, size, and rights for one environment artifact."""

    schema_version: Literal["1"] = "1"
    artifact_kind: EnvironmentArtifactKind
    artifact_reference: str
    content_hash: SHA256Hash
    byte_size: int
    media_type: str
    platform_applicability: str
    origin: str
    rights_binding_hash: SHA256Hash | None = None

    @model_validator(mode="after")
    def validate_artifact(self) -> EnvironmentArtifactV1:
        if self.byte_size < 0:
            raise ValueError("byte size cannot be negative")
        return self


class PythonRuntimeIdentityV1(FrozenModel):
    """Exact runtime identity for the Python interpreter."""

    schema_version: Literal["1"] = "1"
    implementation: str
    version: str
    build: str
    executable: str
    standard_library_inventory_hash: SHA256Hash
    distribution_artifact_hash: SHA256Hash
    native_library_links: tuple[str, ...]


class PackageArtifactV1(FrozenModel):
    """Exact package wheel or sdist artifact identity."""

    schema_version: Literal["1"] = "1"
    package_name: str
    version: str
    filename: str
    content_hash: SHA256Hash
    origin: str
    compatible_tags: tuple[str, ...]
    build_toolchain_hashes: tuple[SHA256Hash, ...] = ()
    installed_file_inventory_hash: SHA256Hash


class SystemLibraryIdentityV1(FrozenModel):
    """Exact system dynamic library identity."""

    schema_version: Literal["1"] = "1"
    library_name: str
    version_or_build: str
    architecture: Literal["arm64"] = "arm64"
    digest: SHA256Hash
    relevance: str


class PlatformIdentityV1(FrozenModel):
    """Declared host platform and kernel compatibility."""

    schema_version: Literal["1"] = "1"
    os_name: Literal["macos"] = "macos"
    architecture: Literal["arm64"] = "arm64"
    os_build: str
    kernel_compatibility: str
    hardware_class: str
    declared_host_assumptions: tuple[str, ...] = ()


def environment_closure_hash(closure: EnvironmentClosureV1) -> SHA256Hash:
    """Compute canonical hash for EnvironmentClosureV1 excluding closure_hash."""
    dump = closure.model_dump(mode="python")
    dump.pop("closure_hash", None)
    return content_hash(dump)


class EnvironmentClosureV1(FrozenModel):
    """Closed environment identity sealing Python, packages, libraries, and tools."""

    schema_version: Literal["1"] = "1"
    closure_id: UUID7
    closure_version: str = "1"
    created_at: UTCDateTime
    semantic_policy_hashes: tuple[SHA256Hash, ...]
    git_commit: str
    git_tree_hash: SHA256Hash
    git_archive_hash: SHA256Hash
    drift_wheel_hash: SHA256Hash
    drift_sdist_hash: SHA256Hash
    pyproject_toml_hash: SHA256Hash
    uv_lock_hash: SHA256Hash
    pylock_toml_hash: SHA256Hash
    uv_executable_hash: SHA256Hash
    python_runtime: PythonRuntimeIdentityV1
    package_artifacts: tuple[PackageArtifactV1, ...]
    system_libraries: tuple[SystemLibraryIdentityV1, ...] = ()
    tzif_hash: SHA256Hash
    source_snapshot_hash: SHA256Hash
    restore_recipe_hash: SHA256Hash
    platform: PlatformIdentityV1
    vulnerability_evidence_hash: SHA256Hash
    security_lane: str
    environment_artifacts: tuple[EnvironmentArtifactV1, ...] = ()
    closure_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_closure(self) -> EnvironmentClosureV1:
        expected = environment_closure_hash(self)
        if self.closure_hash != expected:
            raise ValueError(
                f"closure hash mismatch: expected {expected}, got {self.closure_hash}"
            )
        return self


# Re-export qualification helpers for convenience
