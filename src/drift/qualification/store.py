"""Private, isolated, content-addressed storage for M1e real source data."""

import fcntl
import json
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Self
from uuid import UUID, uuid7

from drift.datasets.resolver import ResolverLimits, VerifiedArtifactBytes
from drift.domain.acquisition import (
    PrivateStoreInventoryV1,
    PrivateStorePolicyV1,
    StoredContentObjectV1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.qualification import (
    ContentDispositionDuty,
    ContentDispositionRecordV1,
    ContentDispositionStatus,
)
from drift.domain.rights import ContentRightsBindingV1
from drift.serialization.canonical import canonical_json, content_hash


@dataclass(slots=True)
class PrivateStoreSession:
    """Noncanonical runtime session holding the open private store lock and policy."""

    root_path: Path
    approved_root_identifier: str
    approved_root_binding_evidence_hash: str
    policy: PrivateStorePolicyV1
    pilot_id: UUID
    lock_fd: int

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        close_private_store_session(self)


def _write_private_text(path: Path, text: str) -> None:
    """Write text to file with restrictive 0600 permissions and fsync."""
    data = text.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def open_private_store_session(
    root: Path,
    policy: PrivateStorePolicyV1,
    pilot_id: UUID,
    approved_root_binding_evidence: VerifiedArtifactBytes,
) -> PrivateStoreSession:
    """Validate binding, initialize layout, and acquire exclusive store lock."""
    resolved_root = root.resolve()
    if not approved_root_binding_evidence.data:
        raise ValueError("approved root binding evidence cannot be empty")
    if policy.approved_root_identifier != policy.approved_root_identifier.strip():
        raise ValueError("policy approved root identifier must not have whitespace")

    if (
        approved_root_binding_evidence.content_hash
        not in policy.access_control_evidence_hashes
    ):
        raise ValueError(
            "approved root binding mismatch: evidence hash "
            f"{approved_root_binding_evidence.content_hash} "
            "not in policy access control evidence hashes"
        )
    if (
        policy.approved_root_identifier.encode("utf-8")
        not in approved_root_binding_evidence.data
    ):
        raise ValueError(
            "approved root binding mismatch: identifier "
            f"'{policy.approved_root_identifier}' "
            "not attested in binding evidence"
        )

    # Create root layout with restrictive permissions (0700)
    for sub in (
        "objects/sha256",
        "object-rights",
        "descriptors",
        f"attempts/{pilot_id}",
        f"inventories/{pilot_id}",
        "locks",
        f"transactions/{pilot_id}",
        f"quarantine/{pilot_id}",
        "dispositions",
    ):
        dir_path = resolved_root / sub
        dir_path.mkdir(parents=True, exist_ok=True, mode=0o700)

    # Acquire exclusive flock on pilot lockfile
    lock_path = resolved_root / "locks" / f"{pilot_id}.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except Exception as exc:
        os.close(lock_fd)
        raise ValueError("failed to acquire store session lock") from exc

    return PrivateStoreSession(
        root_path=resolved_root,
        approved_root_identifier=policy.approved_root_identifier,
        approved_root_binding_evidence_hash=approved_root_binding_evidence.content_hash,
        policy=policy,
        pilot_id=pilot_id,
        lock_fd=lock_fd,
    )


def close_private_store_session(session: PrivateStoreSession) -> None:
    """Release exclusive store lock and close file descriptor."""
    if session.lock_fd >= 0:
        try:
            fcntl.flock(session.lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(session.lock_fd)
            session.lock_fd = -1


def _check_no_symlinks(path: Path, root: Path) -> None:
    """Ensure path and parent components are in root and contain no symlinks."""
    current = path
    resolved_root = root.resolve()
    while current != resolved_root:
        if current.is_symlink():
            raise ValueError(f"symlink detected at {current}")
        parent = current.parent
        if parent == current:
            raise ValueError(f"path {path} escaped root {root}")
        current = parent
    if resolved_root.is_symlink():
        raise ValueError(f"store root {root} is a symlink")


def store_content_object(
    session: PrivateStoreSession,
    artifact: VerifiedArtifactBytes,
    rights_binding: ContentRightsBindingV1,
    object_class: str,
) -> StoredContentObjectV1:
    """Transactionally store verified bytes, write rights binding, and update quota."""
    if object_class not in session.policy.allowed_object_classes:
        raise ValueError(f"object class '{object_class}' not in allowed policy classes")

    if artifact.byte_size > session.policy.max_object_bytes:
        raise ValueError(
            f"artifact size {artifact.byte_size} exceeds "
            f"max_object_bytes {session.policy.max_object_bytes}"
        )

    if rights_binding.content_hash != artifact.content_hash:
        raise ValueError(
            "rights binding content hash does not match artifact content hash"
        )

    if rights_binding.private_store_policy_hash != session.policy.policy_hash:
        raise ValueError(
            "rights binding private store policy hash does not "
            "match session policy hash"
        )

    c_hash = artifact.content_hash
    target_obj_dir = session.root_path / "objects" / "sha256" / c_hash[:2]
    target_obj_file = target_obj_dir / c_hash

    inventory_file = (
        session.root_path / "inventories" / str(session.pilot_id) / "current.json"
    )
    inventory_data: dict[str, Any] = {}
    if inventory_file.is_file():
        inventory_data = json.loads(inventory_file.read_text())

    cumulative_bytes = inventory_data.get("cumulative_unique_bytes", 0)
    existing_hashes = set(inventory_data.get("object_hashes", ()))

    # If object already exists in inventory and file verifies, reuse it
    if c_hash in existing_hashes and target_obj_file.is_file():
        _check_no_symlinks(target_obj_file, session.root_path)
        existing_bytes = target_obj_file.read_bytes()
        if sha256(existing_bytes).hexdigest() == c_hash:
            location_ref = ArtifactReference(
                artifact_id=uuid7(),
                kind=ArtifactKind.DATASET,
                content_hash=c_hash,
                location=f"drift+sha256://{c_hash}",
            )
            return StoredContentObjectV1(
                content_hash=c_hash,
                byte_size=len(existing_bytes),
                location_reference=location_ref,
                rights_binding_hash=content_hash(rights_binding),
                object_class=object_class,
                store_policy_hash=session.policy.policy_hash,
            )

    # Check cumulative quota
    if cumulative_bytes + artifact.byte_size > session.policy.max_total_pilot_bytes:
        raise ValueError(
            f"storing object would exceed max_total_pilot_bytes: "
            f"{cumulative_bytes + artifact.byte_size} > "
            f"{session.policy.max_total_pilot_bytes}"
        )

    # Transactional write in transactions/<pilot-id>/<tx-id>/
    tx_id = uuid7()
    tx_dir = session.root_path / "transactions" / str(session.pilot_id) / str(tx_id)
    tx_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    tx_obj_file = tx_dir / "object.bin"
    tx_rights_file = tx_dir / "rights.json"
    tx_manifest_file = tx_dir / "manifest.json"

    # Write object data with 0600 permissions
    fd = os.open(tx_obj_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, artifact.data)
        os.fsync(fd)
    finally:
        os.close(fd)

    # Re-read and verify hash
    re_read_bytes = tx_obj_file.read_bytes()
    if sha256(re_read_bytes).hexdigest() != c_hash:
        raise ValueError("written object byte verification failed")

    # Write rights binding with 0600 permissions
    binding_json = canonical_json(rights_binding)
    fd = os.open(tx_rights_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, binding_json)
        os.fsync(fd)
    finally:
        os.close(fd)

    # Write manifest
    manifest_data = {
        "transaction_id": str(tx_id),
        "pilot_id": str(session.pilot_id),
        "content_hash": c_hash,
        "byte_size": artifact.byte_size,
        "object_class": object_class,
    }
    _write_private_text(tx_manifest_file, json.dumps(manifest_data))

    # Commit marker published once staged in tx_dir
    committed_marker = tx_dir / "COMMITTED"
    _write_private_text(committed_marker, "COMMITTED")

    # Install object into place
    target_obj_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not target_obj_file.is_file():
        os.replace(tx_obj_file, target_obj_file)
        os.chmod(target_obj_file, 0o600)
        dfd = os.open(target_obj_dir, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    # Install rights binding into place:
    # object-rights/<sha256>/<rights-binding-hash>.json
    rights_dir = session.root_path / "object-rights" / c_hash
    rights_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    b_hash = content_hash(rights_binding)
    target_rights_file = rights_dir / f"{b_hash}.json"
    os.replace(tx_rights_file, target_rights_file)
    os.chmod(target_rights_file, 0o600)
    rfd = os.open(rights_dir, os.O_RDONLY)
    try:
        os.fsync(rfd)
    finally:
        os.close(rfd)

    # Update inventory atomically
    new_cumulative = cumulative_bytes + artifact.byte_size
    existing_hashes.add(c_hash)
    tx_ids = tuple(
        [
            *inventory_data.get("committed_transaction_ids", ()),
            str(tx_id),
        ]
    )
    inv_version = inventory_data.get("inventory_version", 0) + 1
    new_inventory = PrivateStoreInventoryV1(
        pilot_id=session.pilot_id,
        committed_transaction_ids=tuple(UUID(tid) for tid in tx_ids),
        object_hashes=tuple(sorted(existing_hashes)),
        descriptor_hashes=tuple(sorted(inventory_data.get("descriptor_hashes", ()))),
        cumulative_unique_bytes=new_cumulative,
        quota_bytes=session.policy.max_total_pilot_bytes,
        inventory_version=inv_version,
    )
    tmp_inv = inventory_file.with_name(f"current.json.tmp.{tx_id}")
    _write_private_text(
        tmp_inv,
        json.dumps(new_inventory.model_dump(mode="python"), default=str),
    )
    os.replace(tmp_inv, inventory_file)
    os.chmod(inventory_file, 0o600)
    ifd = os.open(inventory_file.parent, os.O_RDONLY)
    try:
        os.fsync(ifd)
    finally:
        os.close(ifd)

    location_ref = ArtifactReference(
        artifact_id=uuid7(),
        kind=ArtifactKind.DATASET,
        content_hash=c_hash,
        location=f"drift+sha256://{c_hash}",
    )
    return StoredContentObjectV1(
        content_hash=c_hash,
        byte_size=artifact.byte_size,
        location_reference=location_ref,
        rights_binding_hash=b_hash,
        object_class=object_class,
        store_policy_hash=session.policy.policy_hash,
    )


def read_content_object(
    session: PrivateStoreSession,
    stored: StoredContentObjectV1,
    limits: ResolverLimits,
) -> VerifiedArtifactBytes:
    c_hash = stored.content_hash
    target_path = session.root_path / "objects" / "sha256" / c_hash[:2] / c_hash

    _check_no_symlinks(target_path, session.root_path)

    if stored.store_policy_hash != session.policy.policy_hash:
        raise ValueError("stored object policy hash does not match session policy hash")

    inventory_file = (
        session.root_path / "inventories" / str(session.pilot_id) / "current.json"
    )
    committed_hashes: set[str] = set()
    if inventory_file.is_file():
        _check_no_symlinks(inventory_file, session.root_path)
        inventory_data = json.loads(inventory_file.read_text())
        committed_hashes = set(inventory_data.get("object_hashes", ()))

    if stored.content_hash not in committed_hashes:
        raise ValueError(
            f"stored object {stored.content_hash} not found in store inventory"
        )

    if not target_path.is_file():
        raise ValueError(f"stored object {c_hash} does not exist")

    stat_result = target_path.stat()
    if not stat.S_ISREG(stat_result.st_mode):
        raise ValueError(f"stored object {c_hash} is not a regular file")

    if stat_result.st_size > limits.max_bytes:
        raise ValueError(
            f"stored object exceeds limit: {stat_result.st_size} > {limits.max_bytes}"
        )

    data = target_path.read_bytes()
    if len(data) != stat_result.st_size or len(data) != stored.byte_size:
        raise ValueError("read size does not match stored descriptor size")

    if sha256(data).hexdigest() != c_hash:
        raise ValueError(f"stored object hash verification failed for {c_hash}")

    # Verify rights binding
    rights_file = (
        session.root_path
        / "object-rights"
        / c_hash
        / f"{stored.rights_binding_hash}.json"
    )
    if not rights_file.is_file():
        raise ValueError("rights binding file missing")

    _check_no_symlinks(rights_file, session.root_path)
    rights_bytes = rights_file.read_bytes()
    binding = ContentRightsBindingV1.model_validate_json(rights_bytes)
    if content_hash(binding) != stored.rights_binding_hash:
        raise ValueError("rights binding content hash mismatch")

    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=c_hash,
    )


def recover_incomplete_transactions(session: PrivateStoreSession) -> tuple[str, ...]:
    """Quarantine uncommitted transactions and record PENDING dispositions."""
    tx_root = session.root_path / "transactions" / str(session.pilot_id)
    if not tx_root.is_dir():
        return ()

    # Load committed object hashes from inventory to avoid cleaning committed data
    inventory_file = (
        session.root_path / "inventories" / str(session.pilot_id) / "current.json"
    )
    committed_hashes: set[str] = set()
    if inventory_file.is_file():
        try:
            inv_data = json.loads(inventory_file.read_text())
            committed_hashes = set(inv_data.get("object_hashes", ()))
        except Exception:
            pass

    quarantined: list[str] = []
    quarantine_root = session.root_path / "quarantine" / str(session.pilot_id)

    for item in tx_root.iterdir():
        if item.is_dir():
            committed_file = item / "COMMITTED"
            if not committed_file.is_file():
                manifest_file = item / "manifest.json"
                content_hash_val: str | None = None
                if manifest_file.is_file():
                    try:
                        m_data = json.loads(manifest_file.read_text())
                        content_hash_val = m_data.get("content_hash")
                    except Exception:
                        pass

                if content_hash_val:
                    c_hash = str(content_hash_val)
                    if c_hash not in committed_hashes:
                        partial_obj = (
                            session.root_path
                            / "objects"
                            / "sha256"
                            / c_hash[:2]
                            / c_hash
                        )
                        if partial_obj.is_file():
                            partial_obj.unlink()

                        partial_rights_dir = (
                            session.root_path / "object-rights" / c_hash
                        )
                        if partial_rights_dir.is_dir():
                            for rf in partial_rights_dir.glob("*.json"):
                                rf.unlink()

                    disp = ContentDispositionRecordV1(
                        content_hash=c_hash,
                        backup_hashes=(),
                        contractual_duty=ContentDispositionDuty.DELETE,
                        status=ContentDispositionStatus.PENDING,
                        evidence_hashes=(),
                        disposition_time=None,
                    )
                    d_hash = content_hash(disp)
                    disp_dir = session.root_path / "dispositions" / c_hash
                    disp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    disp_path = disp_dir / f"{d_hash}.json"
                    _write_private_text(disp_path, canonical_json(disp).decode("utf-8"))

                dest = quarantine_root / item.name
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.replace(item, dest)
                quarantined.append(item.name)

    return tuple(sorted(quarantined))
