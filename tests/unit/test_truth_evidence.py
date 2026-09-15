"""Unit tests for truth intake receipts and extraction decisions."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

import pytest

from drift.domain.golden_cases import (
    IndependentTruthClaimV1,
    TruthExtractionDecisionV1,
    TruthExtractionMethod,
    TruthIntakeReceiptV1,
    independent_truth_claim_hash,
    truth_extraction_decision_hash,
    truth_intake_receipt_hash,
)

H = tuple(f"{index:x}" * 64 for index in range(1, 16))
NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def test_truth_intake_receipt_and_extraction_decision_binding() -> None:
    receipt_unhashed = TruthIntakeReceiptV1.model_construct(
        schema_version="1",
        receipt_id=uuid7(),
        source_id="sec_edgar",
        description="Meta 8-K filing",
        byte_graph_hash=H[0],
        origin_evidence_hash=H[1],
        rights_binding_hash=H[2],
        availability_evidence_hash=H[3],
        expected_inventory_hash=None,
        completeness_pass=True,
        collector_id="collector_1",
        received_at=NOW,
        receipt_hash=H[0],
    )
    receipt = receipt_unhashed.model_copy(
        update={"receipt_hash": truth_intake_receipt_hash(receipt_unhashed)}
    )

    decision_unhashed = TruthExtractionDecisionV1.model_construct(
        schema_version="1",
        decision_id=uuid7(),
        input_byte_hash=H[0],
        locator="Item 5.02 Page 3",
        method=TruthExtractionMethod.HUMAN_ADJUDICATED,
        canonical_extracted_value="Meta Platforms, Inc.",
        temporal_precision="second",
        adjudicator_id="human_analyst",
        policy_hash=H[4],
        decided_at=NOW,
        decision_hash=H[0],
    )
    decision = decision_unhashed.model_copy(
        update={"decision_hash": truth_extraction_decision_hash(decision_unhashed)}
    )

    # Truth claim requires value to match extraction decision
    claim_unhashed = IndependentTruthClaimV1.model_construct(
        schema_version="1",
        claim_id="TC-META-NAME",
        subject_id="META-CORP",
        claim_kind="entity_name",
        canonical_value="Meta Platforms, Inc.",
        temporal_lower_bound=NOW,
        temporal_upper_bound=NOW,
        evidence_hashes=(receipt.receipt_hash,),
        extraction_decision_hash=decision.decision_hash,
        limitations=(),
        claim_hash=H[0],
    )
    claim = claim_unhashed.model_copy(
        update={"claim_hash": independent_truth_claim_hash(claim_unhashed)}
    )
    assert claim.canonical_value == decision.canonical_extracted_value


def test_truth_claim_rejects_divergent_extracted_value() -> None:
    decision_unhashed = TruthExtractionDecisionV1.model_construct(
        schema_version="1",
        decision_id=uuid7(),
        input_byte_hash=H[0],
        locator="Item 1",
        method=TruthExtractionMethod.STRUCTURED_PRIMARY,
        canonical_extracted_value="True Value",
        temporal_precision="day",
        adjudicator_id="sec_scraper",
        policy_hash=H[4],
        decided_at=NOW,
        decision_hash=H[0],
    )
    decision = decision_unhashed.model_copy(
        update={"decision_hash": truth_extraction_decision_hash(decision_unhashed)}
    )
    # Fabricating a different claim value from the decision must be rejected
    with pytest.raises(ValueError, match="claim value must match extraction decision"):
        IndependentTruthClaimV1.create_and_validate(
            claim_id="TC-1",
            subject_id="SUBJ-1",
            claim_kind="name",
            canonical_value="Fabricated Value",
            temporal_lower_bound=NOW,
            temporal_upper_bound=NOW,
            evidence_hashes=(H[1],),
            extraction_decision=decision,
            limitations=(),
        )


def test_intake_truth_file_local_script(tmp_path: Path) -> None:
    import importlib.util

    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "intake_m1e_truth.py"
    )
    spec = importlib.util.spec_from_file_location("intake_m1e_truth", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    intake_truth_file = mod.intake_truth_file

    test_file = tmp_path / "truth.txt"
    test_file.write_bytes(b"sample SEC truth filing bytes")

    # 1. Intake without expected inventory has completeness_pass=False
    receipt1 = intake_truth_file(
        file_path=test_file,
        source_id="sec_edgar",
        description="Meta 8-K",
        origin_evidence_hash=H[0],
        rights_binding_hash=H[1],
        availability_evidence_hash=H[2],
        collector_id="analyst_1",
        expected_inventory_hash=None,
    )
    assert receipt1.completeness_pass is False
    assert receipt1.expected_inventory_hash is None

    # 2. Intake with expected inventory has completeness_pass=True
    receipt2 = intake_truth_file(
        file_path=test_file,
        source_id="sec_edgar",
        description="Meta 8-K with inventory",
        origin_evidence_hash=H[0],
        rights_binding_hash=H[1],
        availability_evidence_hash=H[2],
        collector_id="analyst_1",
        expected_inventory_hash=H[3],
    )
    assert receipt2.completeness_pass is True
    assert receipt2.expected_inventory_hash == H[3]
