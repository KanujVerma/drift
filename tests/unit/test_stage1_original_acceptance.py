"""Unit tests for ProductionStudyEvidenceVerifier and acceptance verification."""

from datetime import UTC, datetime

from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_study_freeze import StudyEvidenceReferenceV1
from drift.serialization.canonical import content_hash

H_PROTO = "1" * 64
NOW = datetime(2026, 11, 2, 5, 30, 0, tzinfo=UTC)


def test_production_verifier_accepts_valid_receipt() -> None:
    receipt_payload = {
        "role": "dataset_qualification",
        "receipt_id": "RCPT-DATASET-01",
        "protocol_hash": H_PROTO,
        "authority_id": "matthew-root-key",
        "status": "ACCEPTED",
    }
    r_hash = content_hash(receipt_payload)

    store = {"RCPT-DATASET-01": receipt_payload}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"dataset_qualification": {"matthew-root-key"}},
        receipt_resolver=lambda rid: store[rid],
    )

    ref = StudyEvidenceReferenceV1(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-01",
        receipt_hash=r_hash,
        protocol_hash=H_PROTO,
        accepted_at=NOW,
    )
    assert verifier.verify(ref) is True


def test_production_verifier_refuses_untrusted_authority() -> None:
    receipt_payload = {
        "role": "mandate_review",
        "receipt_id": "RCPT-MANDATE-01",
        "protocol_hash": H_PROTO,
        "authority_id": "untrusted-actor",
        "status": "ACCEPTED",
    }
    r_hash = content_hash(receipt_payload)

    store = {"RCPT-MANDATE-01": receipt_payload}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"mandate_review": {"matthew-root-key"}},
        receipt_resolver=lambda rid: store[rid],
    )

    ref = StudyEvidenceReferenceV1(
        role="mandate_review",
        receipt_id="RCPT-MANDATE-01",
        receipt_hash=r_hash,
        protocol_hash=H_PROTO,
        accepted_at=NOW,
    )
    assert verifier.verify(ref) is False


def test_production_verifier_fails_closed_on_outage() -> None:
    def broken_resolver(_rid: str) -> dict[str, str]:
        raise ConnectionError("RECEIPT_STORAGE_UNREACHABLE")

    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"comparator_review": {"krish-root-key"}},
        receipt_resolver=broken_resolver,
    )

    ref = StudyEvidenceReferenceV1(
        role="comparator_review",
        receipt_id="RCPT-COMP-01",
        receipt_hash="f" * 64,
        protocol_hash=H_PROTO,
        accepted_at=NOW,
    )
    assert verifier.verify(ref) is False
