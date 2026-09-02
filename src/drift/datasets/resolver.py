"""Safe, bounded byte resolution for local dataset fixtures."""

import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from drift.domain.common import SHA256Hash
from drift.domain.manifests import PartitionDescriptorV1
from drift.errors import ArtifactIntegrityError, ArtifactResolutionError


@dataclass(frozen=True, slots=True)
class ResolverLimits:
    """Limits imposed while reading a local fixture artifact."""

    max_bytes: int


@dataclass(frozen=True, slots=True)
class VerifiedArtifactBytes:
    """The exact bytes read and verified from one opened descriptor."""

    data: bytes
    byte_size: int
    content_hash: SHA256Hash


def read_verified_local_artifact(
    root: Path,
    relative_path: str,
    expected_hash: SHA256Hash,
    limits: ResolverLimits,
) -> VerifiedArtifactBytes:
    """Read bounded, hash-verified bytes from a regular file below ``root``."""
    relative = Path(relative_path)
    if (
        not relative.parts
        or "\0" in relative_path
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ArtifactResolutionError("artifact path must be confined to its root")

    try:
        root_fd = os.open(root.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        raise ArtifactResolutionError("artifact root cannot be opened") from error

    opened_dirs: list[int] = [root_fd]
    try:
        directory_fd = root_fd
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            for part in relative.parts[:-1]:
                directory_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | nofollow,
                    dir_fd=directory_fd,
                )
                opened_dirs.append(directory_fd)
            file_fd = os.open(
                relative.parts[-1],
                os.O_RDONLY | os.O_NONBLOCK | nofollow,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise ArtifactResolutionError(
                "artifact path cannot be resolved within its confined root"
            ) from error

        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise ArtifactResolutionError("artifact must be a regular file")
            if opened.st_size > limits.max_bytes:
                raise ArtifactResolutionError("artifact exceeds configured size limit")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                data = stream.read(limits.max_bytes + 1)
            if len(data) > limits.max_bytes:
                raise ArtifactResolutionError("artifact exceeds configured size limit")
        except OSError as error:
            raise ArtifactResolutionError(
                "artifact bytes cannot be read safely"
            ) from error
        finally:
            os.close(file_fd)
    finally:
        for descriptor in reversed(opened_dirs):
            os.close(descriptor)

    digest = sha256(data).hexdigest()
    if digest != expected_hash:
        raise ArtifactIntegrityError("artifact SHA-256 does not match")
    return VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=digest)


def verify_partition_bytes(
    partition: PartitionDescriptorV1, verified: VerifiedArtifactBytes
) -> None:
    """Confirm verified bytes satisfy a retained partition descriptor."""
    if verified.byte_size != partition.byte_size:
        raise ArtifactIntegrityError("artifact byte size does not match partition")
    if verified.content_hash != partition.artifact.content_hash:
        raise ArtifactIntegrityError("artifact SHA-256 does not match partition")
