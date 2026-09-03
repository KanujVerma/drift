"""Pinned M1a compatibility across additive M1b contracts."""

from hashlib import sha256
from pathlib import Path

from test_m1_dataset_audit import DECISION, MANIFEST, MANIFEST_REFERENCE

from drift.datasets.events import (
    build_manifest_recorded_event,
    build_validation_completed_event,
)
from drift.datasets.resolver import VerifiedArtifactBytes
from drift.datasets.validation import parse_synthetic_fact_bytes
from drift.serialization.canonical import canonical_json, content_hash

FIXTURE = Path(__file__).parents[1] / "fixtures/datasets/m1a/late-fundamental.json"


def test_m1a_manifest_decision_and_events_keep_their_canonical_identity() -> None:
    """Any inherited-field or V1 event change must break these pinned digests."""
    manifest_draft = build_manifest_recorded_event(MANIFEST, MANIFEST_REFERENCE)
    decision_draft = build_validation_completed_event(MANIFEST, DECISION)
    assert (len(canonical_json(MANIFEST)), content_hash(MANIFEST)) == (
        3453,
        "adeb6f2aed97093ff44623633d9cff5102d7a67f14c84f0e01b456428f493bd9",
    )
    assert (len(canonical_json(DECISION)), content_hash(DECISION)) == (
        761,
        "c1ec0af28e04238a51eb9aeb25a38594346eba7c9433f17ab8ad6ff33241612b",
    )
    assert (len(canonical_json(manifest_draft)), content_hash(manifest_draft)) == (
        481,
        "256f6777bbc910e8022461498d11a4bb0251239ab597a921b665022a23ece1f7",
    )
    assert (len(canonical_json(decision_draft)), content_hash(decision_draft)) == (
        490,
        "03a0b016f12c9773da3913c7e945d8215e36707cf37a808ba18c99aa00f9498f",
    )


def test_m1a_fact_version_keeps_its_canonical_identity() -> None:
    """M1b assertion envelopes must not reinterpret persisted M1a facts."""
    data = FIXTURE.read_bytes()
    versions = parse_synthetic_fact_bytes(
        VerifiedArtifactBytes(
            data=data,
            byte_size=len(data),
            content_hash=sha256(data).hexdigest(),
        )
    )
    version = versions[0]
    assert (len(canonical_json(version)), content_hash(version)) == (
        1265,
        "026fe6d703cd0283012f7d58d4149faeeed32c69aa5b5a32abdea63fab9003a7",
    )
    assert version.payload_hash == (
        "16e540dbcc8a45e9dc5249596826fb2b7b030caf6bab440be3720ea0221323d6"
    )
