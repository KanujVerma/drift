"""Tests for confined local fixture resolution."""

import os
from hashlib import sha256
from pathlib import Path

import pytest

from drift.datasets.resolver import (
    ResolverLimits,
    VerifiedArtifactBytes,
    read_verified_local_artifact,
    verify_partition_bytes,
)
from drift.domain.artifacts import ArtifactReference
from drift.domain.manifests import PartitionDescriptorV1
from drift.errors import ArtifactIntegrityError, ArtifactResolutionError

LIMITS = ResolverLimits(max_bytes=64)


@pytest.mark.parametrize(
    "relative",
    ("", "../secret.json", "/tmp/secret.json", "a/../../b", "data\0.json"),
)
def test_resolver_rejects_unconfined_paths(tmp_path: Path, relative: str) -> None:
    """Reject paths that could name a file outside the configured root."""
    with pytest.raises(ArtifactResolutionError, match="confined"):
        read_verified_local_artifact(tmp_path, relative, "0" * 64, LIMITS)


def test_resolver_rejects_hash_mismatch(tmp_path: Path) -> None:
    """Reject bytes whose digest differs from the expected artifact digest."""
    (tmp_path / "data.json").write_bytes(b"{}")

    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        read_verified_local_artifact(tmp_path, "data.json", "0" * 64, LIMITS)


def test_resolver_returns_bytes_from_the_verified_open_descriptor(
    tmp_path: Path,
) -> None:
    """Keep the checked bytes when the pathname is replaced after reading."""
    path = tmp_path / "data.json"
    original = b'{"value":1}'
    path.write_bytes(original)

    verified = read_verified_local_artifact(
        tmp_path, path.name, sha256(original).hexdigest(), LIMITS
    )
    path.write_bytes(b'{"value":9}')

    assert verified == VerifiedArtifactBytes(
        data=original,
        byte_size=11,
        content_hash="48208f9428d64634bd8e28ff345bf0eab60d53c18fa2fbdb0b9bc1e84df2b5f6",
    )


def test_resolver_rejects_symlink_path_component(tmp_path: Path) -> None:
    """Reject an intermediate symlink even when it points inside the root."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "data.json").write_bytes(b"{}")
    (tmp_path / "linked").symlink_to(target, target_is_directory=True)

    with pytest.raises(ArtifactResolutionError):
        read_verified_local_artifact(
            tmp_path, "linked/data.json", sha256(b"{}").hexdigest(), LIMITS
        )


def test_resolver_rejects_symlink_escape(tmp_path: Path) -> None:
    """Reject a symlink that points from the root to another directory."""
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b"outside")
    (tmp_path / "escape.json").symlink_to(outside)

    with pytest.raises(ArtifactResolutionError):
        read_verified_local_artifact(
            tmp_path, "escape.json", sha256(b"outside").hexdigest(), LIMITS
        )


def test_resolver_rejects_nonregular_file(tmp_path: Path) -> None:
    """Reject a FIFO rather than treating it as retained artifact bytes."""
    fifo = tmp_path / "stream"
    os.mkfifo(fifo)

    with pytest.raises(ArtifactResolutionError, match="regular file"):
        read_verified_local_artifact(tmp_path, fifo.name, "0" * 64, LIMITS)


def test_resolver_rejects_missing_file(tmp_path: Path) -> None:
    """Turn unresolved fixture paths into a typed resolution failure."""
    with pytest.raises(ArtifactResolutionError):
        read_verified_local_artifact(tmp_path, "missing.json", "0" * 64, LIMITS)


def test_resolver_rejects_file_above_maximum_size(tmp_path: Path) -> None:
    """Refuse a file whose descriptor-reported size exceeds the byte limit."""
    (tmp_path / "large.json").write_bytes(b"12345")

    with pytest.raises(ArtifactResolutionError, match="size limit"):
        read_verified_local_artifact(
            tmp_path, "large.json", sha256(b"12345").hexdigest(), ResolverLimits(4)
        )


def test_verify_partition_bytes_accepts_matching_descriptor() -> None:
    """Accept retained bytes that match a partition's declared identity."""
    data = b"partition"
    digest = sha256(data).hexdigest()
    partition = PartitionDescriptorV1.model_construct(
        byte_size=9,
        artifact=ArtifactReference.model_construct(content_hash=digest),
    )
    verified = VerifiedArtifactBytes(data=data, byte_size=9, content_hash=digest)

    verify_partition_bytes(partition, verified)


def test_verify_partition_bytes_rejects_declared_size_mismatch() -> None:
    """Reject bytes that cannot satisfy the partition's declared byte size."""
    data = b"partition"
    digest = sha256(data).hexdigest()
    partition = PartitionDescriptorV1.model_construct(
        byte_size=8,
        artifact=ArtifactReference.model_construct(content_hash=digest),
    )
    verified = VerifiedArtifactBytes(data=data, byte_size=9, content_hash=digest)

    with pytest.raises(ArtifactIntegrityError, match="byte size"):
        verify_partition_bytes(partition, verified)


def test_verify_partition_bytes_rejects_partition_hash_mismatch() -> None:
    """Reject bytes whose verified hash differs from the partition artifact."""
    data = b"partition"
    partition = PartitionDescriptorV1.model_construct(
        byte_size=9,
        artifact=ArtifactReference.model_construct(content_hash="0" * 64),
    )
    verified = VerifiedArtifactBytes(
        data=data,
        byte_size=9,
        content_hash=sha256(data).hexdigest(),
    )

    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        verify_partition_bytes(partition, verified)
