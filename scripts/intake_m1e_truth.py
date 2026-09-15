"""Local-only intake boundary for externally obtained independent truth artifacts.

Produces TruthIntakeReceiptV1 without network access, credentials, or provider SDKs.
"""

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from drift.domain.common import SHA256Hash
from drift.domain.golden_cases import TruthIntakeReceiptV1, truth_intake_receipt_hash


def intake_truth_file(
    file_path: Path,
    source_id: str,
    description: str,
    origin_evidence_hash: SHA256Hash,
    rights_binding_hash: SHA256Hash,
    availability_evidence_hash: SHA256Hash,
    collector_id: str,
    expected_inventory_hash: SHA256Hash | None = None,
) -> TruthIntakeReceiptV1:
    """Read local truth artifact, compute byte hash, and generate receipt."""
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"truth input file not found: {file_path}")

    # Read bytes and compute sha256
    data = file_path.read_bytes()
    byte_hash = hashlib.sha256(data).hexdigest()

    now = datetime.now(tz=UTC)
    unhashed = TruthIntakeReceiptV1.model_construct(
        schema_version="1",
        receipt_id=uuid7(),
        source_id=source_id,
        description=description,
        byte_graph_hash=byte_hash,
        origin_evidence_hash=origin_evidence_hash,
        rights_binding_hash=rights_binding_hash,
        availability_evidence_hash=availability_evidence_hash,
        expected_inventory_hash=expected_inventory_hash,
        completeness_pass=expected_inventory_hash is not None,
        collector_id=collector_id,
        received_at=now,
        receipt_hash="0" * 64,
    )
    return unhashed.model_copy(
        update={"receipt_hash": truth_intake_receipt_hash(unhashed)}
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M1e Independent Truth Intake Boundary"
    )
    parser.add_argument(
        "--file", type=Path, required=True, help="Path to local truth file"
    )
    parser.add_argument(
        "--source-id", type=str, required=True, help="Source identifier"
    )
    parser.add_argument(
        "--description", type=str, required=True, help="Truth description"
    )
    parser.add_argument("--origin-evidence-hash", type=str, required=True)
    parser.add_argument("--rights-binding-hash", type=str, required=True)
    parser.add_argument("--availability-evidence-hash", type=str, required=True)
    parser.add_argument("--collector-id", type=str, required=True)
    parser.add_argument(
        "--expected-inventory-hash",
        type=str,
        default=None,
        help="Optional expected inventory hash for completeness verification",
    )

    args = parser.parse_args()
    receipt = intake_truth_file(
        file_path=args.file,
        source_id=args.source_id,
        description=args.description,
        origin_evidence_hash=args.origin_evidence_hash,
        rights_binding_hash=args.rights_binding_hash,
        availability_evidence_hash=args.availability_evidence_hash,
        collector_id=args.collector_id,
        expected_inventory_hash=args.expected_inventory_hash,
    )
    print(receipt.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
