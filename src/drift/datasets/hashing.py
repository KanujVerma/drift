"""Canonical preimages and hashes for immutable dataset manifests."""

from collections.abc import Sequence

from drift.domain.datasets import TemporalCoverage
from drift.domain.manifests import (
    DatasetManifestV1,
    PartitionDescriptorV1,
    SchemaDescriptorV1,
)
from drift.serialization.canonical import JSONValue, canonical_data, content_hash


def schema_body(schema: SchemaDescriptorV1) -> dict[str, JSONValue]:
    """Return the stored schema's self-excluding canonical hash preimage."""
    body = canonical_data(schema)
    assert isinstance(body, dict)
    del body["schema_hash"]
    return body


def schema_hash(schema: SchemaDescriptorV1) -> str:
    """Hash every canonical schema field except its stored digest."""
    return content_hash(schema_body(schema))


def manifest_body(manifest: DatasetManifestV1) -> dict[str, JSONValue]:
    """Return every canonical manifest field as its hash preimage."""
    body = canonical_data(manifest)
    assert isinstance(body, dict)
    return body


def manifest_hash(manifest: DatasetManifestV1) -> str:
    """Return the canonical immutable manifest digest."""
    return content_hash(manifest_body(manifest))


def derived_temporal_coverage(
    partitions: Sequence[PartitionDescriptorV1],
) -> TemporalCoverage:
    """Derive inclusive coverage from the earliest and latest partitions."""
    if not partitions:
        msg = "cannot derive temporal coverage from empty partitions"
        raise ValueError(msg)
    return TemporalCoverage(
        started_at=min(partition.coverage.started_at for partition in partitions),
        ended_at=max(partition.coverage.ended_at for partition in partitions),
    )
