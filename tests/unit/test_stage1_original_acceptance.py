"""Unit tests for ProductionStudyEvidenceVerifier and acceptance verification."""

from datetime import UTC, datetime
from typing import Any

from drift.experiments.stage1_original_acceptance import (
    ProductionExecutionEvidenceVerifier,
    ProductionStudyEvidenceVerifier,
    create_historical_execution_artifact,
    create_historical_execution_receipt,
    create_original_study_evidence_receipt,
)
from drift.experiments.stage1_study_freeze import StudyEvidenceReferenceV1
from drift.serialization.canonical import content_hash

H_PROTO = "1" * 64
H_FREEZE = "2" * 64
NOW = datetime(2026, 11, 2, 5, 30, 0, tzinfo=UTC)
KEY = "test-secret-key-123"


def test_production_verifier_accepts_valid_signed_receipt() -> None:
    receipt_payload, r_hash = create_original_study_evidence_receipt(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-01",
        protocol_hash=H_PROTO,
        authority_id="matthew-root-key",
        accepted_at=NOW,
        assessor_independence=True,
        hmac_key=KEY,
    )

    store = {"RCPT-DATASET-01": receipt_payload}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"dataset_qualification": {"matthew-root-key": {"hmac_key": KEY}}},
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


def test_production_verifier_refuses_unsigned_or_mismatched_receipt_id() -> None:
    # Finding 1: Unsigned receipt or mismatched receipt ID must fail
    raw_unsigned = {
        "role": "dataset_qualification",
        "receipt_id": "RCPT-DIFFERENT-ID",
        "protocol_hash": H_PROTO,
        "authority_id": "matthew-root-key",
        "status": "ACCEPTED",
        "accepted_at": NOW.isoformat(),
        "assessor_independence": True,
    }
    r_hash = content_hash(raw_unsigned)
    store = {"RCPT-REF-ID": raw_unsigned}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"dataset_qualification": {"matthew-root-key": {"hmac_key": KEY}}},
        receipt_resolver=lambda rid: store[rid],
    )

    # Mismatched receipt ID
    ref = StudyEvidenceReferenceV1(
        role="dataset_qualification",
        receipt_id="RCPT-REF-ID",
        receipt_hash=r_hash,
        protocol_hash=H_PROTO,
        accepted_at=NOW,
    )
    assert verifier.verify(ref) is False


def test_production_verifier_refuses_mismatched_time_or_independence() -> None:
    # Finding 1: Mismatched acceptance time
    later = datetime(2026, 11, 3, 5, 30, 0, tzinfo=UTC)
    receipt_payload, r_hash = create_original_study_evidence_receipt(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-02",
        protocol_hash=H_PROTO,
        authority_id="matthew-root-key",
        accepted_at=later,
        assessor_independence=True,
        hmac_key=KEY,
    )
    store = {"RCPT-DATASET-02": receipt_payload}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"dataset_qualification": {"matthew-root-key": {"hmac_key": KEY}}},
        receipt_resolver=lambda rid: store[rid],
    )
    ref = StudyEvidenceReferenceV1(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-02",
        receipt_hash=r_hash,
        protocol_hash=H_PROTO,
        accepted_at=NOW,  # Mismatched reference time
    )
    assert verifier.verify(ref) is False

    # Assessor lack of independence
    payload_dependent, dep_hash = create_original_study_evidence_receipt(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-03",
        protocol_hash=H_PROTO,
        authority_id="matthew-root-key",
        accepted_at=NOW,
        assessor_independence=False,  # Not independent
        hmac_key=KEY,
    )
    store["RCPT-DATASET-03"] = payload_dependent
    ref_dep = StudyEvidenceReferenceV1(
        role="dataset_qualification",
        receipt_id="RCPT-DATASET-03",
        receipt_hash=dep_hash,
        protocol_hash=H_PROTO,
        accepted_at=NOW,
    )
    assert verifier.verify(ref_dep) is False


def test_production_verifier_refuses_untrusted_authority() -> None:
    receipt_payload, r_hash = create_original_study_evidence_receipt(
        role="mandate_review",
        receipt_id="RCPT-MANDATE-01",
        protocol_hash=H_PROTO,
        authority_id="untrusted-actor",
        accepted_at=NOW,
        hmac_key=KEY,
    )
    store = {"RCPT-MANDATE-01": receipt_payload}
    verifier = ProductionStudyEvidenceVerifier(
        trust_roots={"mandate_review": {"matthew-root-key": {"hmac_key": KEY}}},
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
        trust_roots={"comparator_review": {"krish-root-key": {"hmac_key": KEY}}},
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


def test_execution_verifier_rejects_fabricated_artifacts() -> None:
    # Finding 2: Rejection of fabricated untyped artifacts and unreconciled metrics
    artifact_store: dict[str, Any] = {}

    p_art, p_hash = create_historical_execution_artifact(
        artifact_type="portfolio_state",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        payload={"nav": "10000.00", "cash": "10000.00", "positions": {}},
    )
    artifact_store[p_hash] = p_art

    d_art, d_hash = create_historical_execution_artifact(
        artifact_type="decision",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        payload={"strategy_id": "B3", "action": {"VOO": "0.50", "IEF": "0.50"}},
    )
    artifact_store[d_hash] = d_art

    f_art, f_hash = create_historical_execution_artifact(
        artifact_type="fills",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        payload={"fills": []},
    )
    artifact_store[f_hash] = f_art

    # Valid receipt
    rcpt, r_hash = create_historical_execution_receipt(
        receipt_id="RCPT-EXEC-0",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        execution_journal={"status": "OK"},
        artifacts={"portfolio_state": p_hash, "decision": d_hash, "fills": f_hash},
        metrics={"terminal_nav": "10000.00", "net_return": "0.0"},
    )
    receipt_store = {"RCPT-EXEC-0": rcpt}

    exec_verifier = ProductionExecutionEvidenceVerifier(
        trust_roots={"matthew-root-key"},
        receipt_resolver=lambda rid: receipt_store[rid],
        artifact_resolver=lambda aid: artifact_store[aid],
    )

    ok, reason, _ = exec_verifier.verify_execution_receipt(
        "RCPT-EXEC-0", expected_freeze_hash=H_FREEZE, expected_session_index=0
    )
    assert ok is True
    assert reason == "OK"

    # 1. Fabricated integer decision
    bad_d_hash = content_hash(12345)
    artifact_store[bad_d_hash] = 12345
    bad_rcpt1, _ = create_historical_execution_receipt(
        receipt_id="RCPT-BAD-1",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        execution_journal={"status": "OK"},
        artifacts={"portfolio_state": p_hash, "decision": bad_d_hash, "fills": f_hash},
        metrics={"terminal_nav": "10000.00"},
    )
    receipt_store["RCPT-BAD-1"] = bad_rcpt1
    ok1, reason1, _ = exec_verifier.verify_execution_receipt(
        "RCPT-BAD-1", expected_freeze_hash=H_FREEZE, expected_session_index=0
    )
    assert ok1 is False
    assert "ARTIFACT_NOT_DICT" in reason1

    # 2. Fabricated string-list fills
    bad_f_obj = {
        "artifact_type": "fills",
        "freeze_hash": H_FREEZE,
        "session_index": 0,
        "authority_id": "matthew-root-key",
        "fills": ["fill1", "fill2"],  # List of strings
    }
    bad_f_hash = content_hash(bad_f_obj)
    artifact_store[bad_f_hash] = bad_f_obj
    bad_rcpt2, _ = create_historical_execution_receipt(
        receipt_id="RCPT-BAD-2",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        execution_journal={"status": "OK"},
        artifacts={"portfolio_state": p_hash, "decision": d_hash, "fills": bad_f_hash},
        metrics={"terminal_nav": "10000.00"},
    )
    receipt_store["RCPT-BAD-2"] = bad_rcpt2
    ok2, reason2, _ = exec_verifier.verify_execution_receipt(
        "RCPT-BAD-2", expected_freeze_hash=H_FREEZE, expected_session_index=0
    )
    assert ok2 is False
    assert "FILLS_RECORD_MUST_BE_OBJECT" in reason2

    # 3. Invented terminal NAV (reconciliation failure)
    bad_rcpt3, _ = create_historical_execution_receipt(
        receipt_id="RCPT-BAD-3",
        freeze_hash=H_FREEZE,
        session_index=0,
        authority_id="matthew-root-key",
        execution_journal={"status": "OK"},
        artifacts={"portfolio_state": p_hash, "decision": d_hash, "fills": f_hash},
        # Differs from portfolio_state nav 10000.00
        metrics={"terminal_nav": "999999.00"},
    )
    receipt_store["RCPT-BAD-3"] = bad_rcpt3
    ok3, reason3, _ = exec_verifier.verify_execution_receipt(
        "RCPT-BAD-3", expected_freeze_hash=H_FREEZE, expected_session_index=0
    )
    assert ok3 is False
    assert "METRIC_RECONCILIATION_FAILED" in reason3
