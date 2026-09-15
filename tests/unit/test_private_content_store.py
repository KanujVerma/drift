"""Task 4 private content-addressed store and transactional quarantine tests."""

import os
import stat
from hashlib import sha256
from pathlib import Path
from uuid import uuid7

import pytest

from drift.datasets.resolver import ResolverLimits, VerifiedArtifactBytes
from drift.domain.acquisition import (
    PrivateStorePolicyV1,
    StoredContentObjectV1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.qualification import ConsumerPurpose, ContentDispositionDuty
from drift.domain.rights import ContentRightsBindingV1, RightsDisposition
from drift.qualification.store import (
    close_private_store_session,
    open_private_store_session,
    read_content_object,
    recover_incomplete_transactions,
    store_content_object,
)
from drift.serialization.canonical import content_hash


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _make_evidence(root_id: str = "approved-store-root-01") -> VerifiedArtifactBytes:
    data = f"Approved storage location signed certificate: {root_id}".encode()
    return VerifiedArtifactBytes(
        data=data,
        byte_size=len(data),
        content_hash=_digest(data),
    )


def _make_policy(
    root_id: str = "approved-store-root-01",
    max_object_bytes: int = 10_000,
    max_total_pilot_bytes: int = 50_000,
    evidence_hash: str | None = None,
) -> PrivateStorePolicyV1:
    ev_hash = evidence_hash or _make_evidence(root_id).content_hash
    return PrivateStorePolicyV1(
        policy_id=uuid7(),
        policy_version="1",
        approved_root_identifier=root_id,
        access_control_evidence_hashes=(ev_hash,),
        encryption_evidence_hashes=("ee" + "0" * 62,),
        allowed_object_classes=("raw_transport", "decompressed_source", "metadata"),
        backup_locations=("backup_vault_local",),
        max_object_bytes=max_object_bytes,
        max_total_pilot_bytes=max_total_pilot_bytes,
    )


def _make_binding(
    content_hash: str,
    policy_hash: str,
) -> ContentRightsBindingV1:
    return ContentRightsBindingV1(
        content_hash=content_hash,
        policy_hash="0" * 64,
        provider_contractual_class="internal_research_only",
        controlling_provision_hashes=("10" + "0" * 62,),
        permitted_purposes=(ConsumerPurpose.HISTORICAL_DECISION_INPUT,),
        permitted_user_ids=("user_1",),
        permitted_contractor_ids=(),
        permitted_service_provider_ids=(),
        permitted_location_ids=("loc_1",),
        permitted_backup_location_ids=("backup_1",),
        machine_identity="host-01",
        shared_account=False,
        real_data_ci=False,
        cloud_processing=False,
        private_store_policy_hash=policy_hash,
        retention_until=None,
        post_termination_use=RightsDisposition.DENIED,
        disposition_duty=ContentDispositionDuty.DELETE,
        backup_allowed=True,
        backup_rule="encrypted_cold_storage",
        frozen_assessment_hash="a" * 64,
    )


def test_open_session_matches_approved_root(tmp_path: Path) -> None:
    policy = _make_policy("my-root-id")
    evidence = _make_evidence("my-root-id")
    pilot_id = uuid7()

    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    )
    try:
        assert session.approved_root_identifier == "my-root-id"
        assert session.root_path == tmp_path.resolve()
        # Verify required directory layout exists
        assert (tmp_path / "objects" / "sha256").is_dir()
        assert (tmp_path / "locks").is_dir()
        assert (tmp_path / "transactions" / str(pilot_id)).is_dir()
    finally:
        close_private_store_session(session)


def test_open_session_wrong_root_binding_fails(tmp_path: Path) -> None:
    policy = _make_policy("my-root-id")
    # Empty or mismatched evidence
    evidence = _make_evidence("different-root")
    bad_policy = policy.model_copy(
        update={"approved_root_identifier": "different-root"}
    )
    with pytest.raises(ValueError, match="approved root|binding mismatch"):
        open_private_store_session(
            root=tmp_path,
            policy=bad_policy,
            pilot_id=uuid7(),
            approved_root_binding_evidence=evidence,
        )


def test_store_and_read_content_object(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    pilot_id = uuid7()

    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"market-data-payload-123"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))

        stored = store_content_object(
            session=session,
            artifact=art,
            rights_binding=binding,
            object_class="raw_transport",
        )

        assert stored.content_hash == c_hash
        assert stored.byte_size == len(data)
        assert stored.object_class == "raw_transport"
        # Verify physical path follows:
        # <approved-root>/objects/sha256/<first-two>/<sha256>
        expected_obj_path = tmp_path / "objects" / "sha256" / c_hash[:2] / c_hash
        assert expected_obj_path.is_file()
        # Verify file mode is 0600
        mode = stat.S_IMODE(expected_obj_path.stat().st_mode)
        assert mode == 0o600

        # Read back
        read_back = read_content_object(
            session, stored, ResolverLimits(max_bytes=10_000)
        )
        assert read_back.data == data
        assert read_back.content_hash == c_hash
    finally:
        close_private_store_session(session)


def test_store_rejects_oversize_object(tmp_path: Path) -> None:
    policy = _make_policy(max_object_bytes=100)
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"x" * 200  # exceeds 100 max_object_bytes
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))

        with pytest.raises(ValueError, match="quota|max_object_bytes|size limit"):
            store_content_object(session, art, binding, "raw_transport")
    finally:
        close_private_store_session(session)


def test_store_rejects_total_pilot_quota_overflow(tmp_path: Path) -> None:
    policy = _make_policy(max_object_bytes=1000, max_total_pilot_bytes=150)
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data1 = b"x" * 100
        c1 = _digest(data1)
        art1 = VerifiedArtifactBytes(data=data1, byte_size=len(data1), content_hash=c1)
        store_content_object(
            session, art1, _make_binding(c1, content_hash(policy)), "raw_transport"
        )

        data2 = b"y" * 100  # total would be 200 > 150
        c2 = _digest(data2)
        art2 = VerifiedArtifactBytes(data=data2, byte_size=len(data2), content_hash=c2)
        with pytest.raises(ValueError, match="quota|total_pilot_bytes"):
            store_content_object(
                session, art2, _make_binding(c2, content_hash(policy)), "raw_transport"
            )
    finally:
        close_private_store_session(session)


def test_store_rejects_unallowed_object_class(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"data"
        c = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c)
        with pytest.raises(ValueError, match="allowed_object_classes|object class"):
            store_content_object(
                session, art, _make_binding(c, content_hash(policy)), "forbidden_class"
            )
    finally:
        close_private_store_session(session)


def test_store_reuses_existing_verified_object(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"identical-payload"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))

        stored1 = store_content_object(session, art, binding, "raw_transport")
        stored2 = store_content_object(session, art, binding, "raw_transport")

        assert stored1.content_hash == stored2.content_hash
    finally:
        close_private_store_session(session)


def test_recovery_quarantines_incomplete_transaction(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    pilot_id = uuid7()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    )
    try:
        # Simulate interrupted transaction without COMMITTED marker
        tx_id = str(uuid7())
        tx_dir = tmp_path / "transactions" / str(pilot_id) / tx_id
        tx_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = tx_dir / "manifest.json"
        manifest_file.write_text('{"status": "in_progress"}')

        # Run recovery
        quarantined = recover_incomplete_transactions(session)
        assert tx_id in quarantined

        # Transaction dir should have been moved to quarantine/<pilot-id>/<tx-id>
        quarantine_dir = tmp_path / "quarantine" / str(pilot_id) / tx_id
        assert quarantine_dir.is_dir()
        assert (quarantine_dir / "manifest.json").is_file()
        assert not tx_dir.exists()
    finally:
        close_private_store_session(session)


def test_symlink_attack_rejected(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    # Make a symlink inside root
    target = tmp_path / "outside_secret"
    target.write_text("secret")
    link = tmp_path / "objects" / "sha256" / "01"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, link)

    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        sym_hash = "01" + "0" * 62
        fake_stored = StoredContentObjectV1(
            content_hash=sym_hash,
            byte_size=6,
            location_reference=ArtifactReference(
                artifact_id=uuid7(),
                kind=ArtifactKind.DATASET,
                content_hash=sym_hash,
                location=f"drift+sha256://{sym_hash}",
            ),
            rights_binding_hash="02" + "0" * 62,
            object_class="raw_transport",
            store_policy_hash=content_hash(policy),
        )
        with pytest.raises(ValueError, match="symlink"):
            read_content_object(session, fake_stored, ResolverLimits(max_bytes=100))
    finally:
        close_private_store_session(session)


def test_store_rejects_rights_binding_content_hash_mismatch(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"content-1"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        bad_binding = _make_binding("ff" * 32, content_hash(policy))
        with pytest.raises(ValueError, match="rights binding content hash"):
            store_content_object(session, art, bad_binding, "raw_transport")
    finally:
        close_private_store_session(session)


def test_store_rejects_rights_binding_policy_hash_mismatch(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"content-2"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        bad_binding = _make_binding(c_hash, "99" * 32)
        with pytest.raises(
            ValueError, match="rights binding private store policy hash"
        ):
            store_content_object(session, art, bad_binding, "raw_transport")
    finally:
        close_private_store_session(session)


def test_read_content_object_rejects_policy_mismatch(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"content-3"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))
        stored = store_content_object(session, art, binding, "raw_transport")

        tampered_stored = stored.model_copy(update={"store_policy_hash": "ee" * 32})
        with pytest.raises(ValueError, match="policy hash does not match"):
            read_content_object(
                session, tampered_stored, ResolverLimits(max_bytes=1000)
            )
    finally:
        close_private_store_session(session)


def test_read_content_object_rejects_uninventoried_object(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"content-4"
        c_hash = _digest(data)
        target_dir = tmp_path / "objects" / "sha256" / c_hash[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / c_hash).write_bytes(data)

        fake_ref = ArtifactReference(
            artifact_id=uuid7(),
            kind=ArtifactKind.DATASET,
            content_hash=c_hash,
            location=f"drift+sha256://{c_hash}",
        )
        fake_stored = StoredContentObjectV1(
            content_hash=c_hash,
            byte_size=len(data),
            location_reference=fake_ref,
            rights_binding_hash="aa" * 32,
            object_class="raw_transport",
            store_policy_hash=content_hash(policy),
        )
        with pytest.raises(ValueError, match="not found in store inventory"):
            read_content_object(session, fake_stored, ResolverLimits(max_bytes=1000))
    finally:
        close_private_store_session(session)


def test_read_content_object_rejects_missing_or_tampered_rights_file(
    tmp_path: Path,
) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=uuid7(),
        approved_root_binding_evidence=evidence,
    )
    try:
        data = b"content-5"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))
        stored = store_content_object(session, art, binding, "raw_transport")

        # Tamper with rights file
        rights_file = (
            tmp_path / "object-rights" / c_hash / f"{stored.rights_binding_hash}.json"
        )
        assert rights_file.is_file()
        rights_file.unlink()

        with pytest.raises(ValueError, match="rights binding file missing"):
            read_content_object(session, stored, ResolverLimits(max_bytes=1000))
    finally:
        close_private_store_session(session)


def test_recovery_cleans_uncommitted_targets_and_writes_disposition(
    tmp_path: Path,
) -> None:
    import json

    policy = _make_policy()
    evidence = _make_evidence()
    pilot_id = uuid7()
    session = open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    )
    try:
        tx_id = str(uuid7())
        tx_dir = tmp_path / "transactions" / str(pilot_id) / tx_id
        tx_dir.mkdir(parents=True, exist_ok=True)
        content_data = b"uncommitted-test-bytes"
        c_hash = _digest(content_data)

        # Place partial target file in objects and object-rights
        part_obj = tmp_path / "objects" / "sha256" / c_hash[:2] / c_hash
        part_obj.parent.mkdir(parents=True, exist_ok=True)
        part_obj.write_bytes(content_data)

        part_rights = tmp_path / "object-rights" / c_hash / f"{'11' * 32}.json"
        part_rights.parent.mkdir(parents=True, exist_ok=True)
        part_rights.write_text("{}")

        manifest_data = {
            "transaction_id": tx_id,
            "pilot_id": str(pilot_id),
            "content_hash": c_hash,
            "byte_size": len(content_data),
            "object_class": "raw_transport",
        }
        (tx_dir / "manifest.json").write_text(json.dumps(manifest_data))

        # Run recovery
        quarantined = recover_incomplete_transactions(session)
        assert tx_id in quarantined

        # Target files must be cleaned up because they were not committed in inventory
        assert not part_obj.exists()
        assert not part_rights.exists()

        # Quarantined directory must exist
        assert (tmp_path / "quarantine" / str(pilot_id) / tx_id).is_dir()

        # Disposition record must be written
        disp_dir = tmp_path / "dispositions" / c_hash
        assert disp_dir.is_dir()
        disp_files = list(disp_dir.glob("*.json"))
        assert len(disp_files) == 1
        disp_content = json.loads(disp_files[0].read_text())
        assert disp_content["content_hash"] == c_hash
        assert disp_content["status"] == "pending"
        assert disp_content["contractual_duty"] == "delete"
    finally:
        close_private_store_session(session)


def test_private_store_session_context_manager(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    pilot_id = uuid7()
    with open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    ) as session:
        assert session.lock_fd >= 0

    assert session.lock_fd == -1


def test_private_store_file_permissions(tmp_path: Path) -> None:
    policy = _make_policy()
    evidence = _make_evidence()
    pilot_id = uuid7()
    with open_private_store_session(
        root=tmp_path,
        policy=policy,
        pilot_id=pilot_id,
        approved_root_binding_evidence=evidence,
    ) as session:
        data = b"private-file-bytes"
        c_hash = _digest(data)
        art = VerifiedArtifactBytes(data=data, byte_size=len(data), content_hash=c_hash)
        binding = _make_binding(c_hash, content_hash(policy))
        stored = store_content_object(session, art, binding, "raw_transport")

        obj_file = tmp_path / "objects" / "sha256" / c_hash[:2] / c_hash
        assert stat.S_IMODE(obj_file.stat().st_mode) == 0o600

        rights_file = (
            tmp_path / "object-rights" / c_hash / f"{stored.rights_binding_hash}.json"
        )
        assert stat.S_IMODE(rights_file.stat().st_mode) == 0o600

        inv_file = tmp_path / "inventories" / str(pilot_id) / "current.json"
        assert stat.S_IMODE(inv_file.stat().st_mode) == 0o600
