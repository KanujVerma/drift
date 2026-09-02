"""Asset-neutral immutable dataset manifest contracts."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.datasets import TemporalCoverage
from drift.domain.temporal import AvailabilityChannelV1


class DatasetKind(StrEnum):
    """Whether retained bytes came directly from a source or a transformation."""

    SOURCE_FACTS = "source_facts"
    DERIVED_FACTS = "derived_facts"


class LogicalType(StrEnum):
    """Storage-neutral logical field types for a dataset schema."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    STRING = "string"
    DATE = "date"
    DATETIME = "datetime"
    JSON = "json"


class EvidenceGranularity(StrEnum):
    """The level at which a dataset retains availability evidence."""

    RECORD = "record"


class DeterminismClaim(StrEnum):
    """Declared repeatability of a retained transformation."""

    DETERMINISTIC = "deterministic"
    UNKNOWN = "unknown"
    NOT_DETERMINISTIC = "not_deterministic"


class SourceDescriptorV1(FrozenModel):
    """Identity and retained provenance for the upstream source."""

    source_id: NonBlankStr
    publisher: NonBlankStr
    product: NonBlankStr
    source_version: NonBlankStr | None = None
    evidence_reference: ArtifactReference

    @field_validator("evidence_reference")
    @classmethod
    def reject_credential_bearing_locator(
        cls, evidence_reference: ArtifactReference
    ) -> ArtifactReference:
        """Prevent source credentials from becoming immutable provenance."""
        location = urlsplit(evidence_reference.location)
        if location.username is not None or location.password is not None:
            msg = "source evidence locator must not contain credentials"
            raise ValueError(msg)
        return evidence_reference


class AcquisitionDescriptorV1(FrozenModel):
    """How and when Drift acquired a source snapshot."""

    acquired_at: UTCDateTime
    collector_id: NonBlankStr
    collector_version: NonBlankStr
    evidence_reference: ArtifactReference


class LicenseDescriptorV1(FrozenModel):
    """Retained legal-source provenance without operational rights conclusions."""

    provider_legal_name: NonBlankStr
    license_reference: NonBlankStr
    license_version: NonBlankStr | None = None
    acquired_at: UTCDateTime
    terms_evidence_reference: ArtifactReference


class FieldDescriptorV1(FrozenModel):
    """One stable schema field identity and its logical representation."""

    field_id: NonBlankStr
    name: NonBlankStr
    logical_type: LogicalType
    nullable: bool
    unit: NonBlankStr | None = None


class SchemaDescriptorV1(FrozenModel):
    """A canonically ordered, hash-bound logical dataset schema."""

    schema_version: NonBlankStr
    fields: tuple[FieldDescriptorV1, ...]
    schema_hash: SHA256Hash

    @field_validator("fields")
    @classmethod
    def canonicalize_fields(
        cls, fields: tuple[FieldDescriptorV1, ...]
    ) -> tuple[FieldDescriptorV1, ...]:
        """Reject ambiguous identities and retain fields in stable order."""
        if not fields:
            msg = "schema fields must not be empty"
            raise ValueError(msg)
        if len({field.field_id for field in fields}) != len(fields):
            msg = "schema field IDs must be unique"
            raise ValueError(msg)
        if len({field.name for field in fields}) != len(fields):
            msg = "schema field names must be unique"
            raise ValueError(msg)
        return tuple(sorted(fields, key=lambda field: field.field_id))

    @model_validator(mode="after")
    def validate_schema_hash(self) -> Self:
        """Bind the supplied digest to the fully canonicalized schema body."""
        from drift.datasets.hashing import schema_hash

        if self.schema_hash != schema_hash(self):
            msg = "schema hash does not match canonical schema body"
            raise ValueError(msg)
        return self


class PartitionDescriptorV1(FrozenModel):
    """One retained physical partition and its asserted inclusive coverage."""

    partition_id: UUID7
    partition_key: NonBlankStr
    artifact: ArtifactReference
    byte_size: Annotated[int, Field(ge=0)]
    media_type: NonBlankStr
    format_version: NonBlankStr
    row_count: Annotated[int, Field(ge=0)]
    schema_hash: SHA256Hash
    coverage: TemporalCoverage


class RecordTemporalContractV1(FrozenModel):
    """Schema bindings for record-level fact validity and availability evidence."""

    contract_version: Literal["1"] = "1"
    evidence_granularity: Literal[EvidenceGranularity.RECORD] = (
        EvidenceGranularity.RECORD
    )
    logical_key_field_ids: tuple[NonBlankStr, ...]
    valid_start_field_id: NonBlankStr
    valid_end_field_id: NonBlankStr
    availability_field_id: NonBlankStr
    revision_id_field_id: NonBlankStr
    supersedes_field_id: NonBlankStr
    source_sequence_field_id: NonBlankStr
    value_field_id: NonBlankStr
    null_reason_field_id: NonBlankStr
    declared_channels: tuple[AvailabilityChannelV1, ...]

    @field_validator("logical_key_field_ids")
    @classmethod
    def require_unique_logical_keys(
        cls, field_ids: tuple[NonBlankStr, ...]
    ) -> tuple[NonBlankStr, ...]:
        """A composite key cannot repeat a component."""
        if not field_ids:
            msg = "logical key field IDs must not be empty"
            raise ValueError(msg)
        if len(set(field_ids)) != len(field_ids):
            msg = "logical key field IDs must be unique"
            raise ValueError(msg)
        return field_ids

    @field_validator("declared_channels")
    @classmethod
    def canonicalize_channels(
        cls, channels: tuple[AvailabilityChannelV1, ...]
    ) -> tuple[AvailabilityChannelV1, ...]:
        """Keep a nonempty, unambiguous claimed-channel set."""
        if not channels:
            msg = "declared channels must not be empty"
            raise ValueError(msg)
        if len(set(channels)) != len(channels):
            msg = "declared channels must be unique"
            raise ValueError(msg)
        return tuple(
            sorted(
                channels,
                key=lambda channel: (
                    channel.kind.value,
                    channel.identifier,
                    channel.version or "",
                ),
            )
        )

    def field_ids(self) -> tuple[NonBlankStr, ...]:
        """Return every schema field identity bound by this contract."""
        return (
            *self.logical_key_field_ids,
            self.valid_start_field_id,
            self.valid_end_field_id,
            self.availability_field_id,
            self.revision_id_field_id,
            self.supersedes_field_id,
            self.source_sequence_field_id,
            self.value_field_id,
            self.null_reason_field_id,
        )


class LineageDescriptorV1(FrozenModel):
    """Immutable provenance for bytes derived from other manifests."""

    input_manifest_hashes: tuple[SHA256Hash, ...]
    transformation_reference: ArtifactReference
    configuration_hash: SHA256Hash
    implementation_reference: ArtifactReference
    environment_hash: SHA256Hash
    output_schema_hash: SHA256Hash
    executed_at: UTCDateTime
    determinism: DeterminismClaim

    @field_validator("input_manifest_hashes")
    @classmethod
    def canonicalize_input_hashes(
        cls, hashes: tuple[SHA256Hash, ...]
    ) -> tuple[SHA256Hash, ...]:
        """Derived lineage must name each input manifest exactly once."""
        if not hashes:
            msg = "lineage input manifest hashes must not be empty"
            raise ValueError(msg)
        if len(set(hashes)) != len(hashes):
            msg = "lineage input manifest hashes must be unique"
            raise ValueError(msg)
        return tuple(sorted(hashes))


class DatasetManifestV1(FrozenModel):
    """The complete immutable provenance manifest for one dataset version."""

    manifest_schema_version: Literal["1"] = "1"
    hash_profile: Literal["drift-canonical-json-sha256-v1"] = (
        "drift-canonical-json-sha256-v1"
    )
    dataset_id: UUID7
    dataset_version: NonBlankStr
    dataset_kind: DatasetKind
    created_at: UTCDateTime
    source: SourceDescriptorV1
    acquisition: AcquisitionDescriptorV1
    license: LicenseDescriptorV1
    schema_definition: SchemaDescriptorV1
    partitions: tuple[PartitionDescriptorV1, ...]
    temporal_contract: RecordTemporalContractV1
    lineage: LineageDescriptorV1 | None = None

    @field_validator("partitions")
    @classmethod
    def canonicalize_partitions(
        cls, partitions: tuple[PartitionDescriptorV1, ...]
    ) -> tuple[PartitionDescriptorV1, ...]:
        """Retain partitions in a stable physical-content order."""
        if not partitions:
            msg = "manifest partitions must not be empty"
            raise ValueError(msg)
        if len({item.partition_id for item in partitions}) != len(partitions):
            msg = "partition IDs must be unique"
            raise ValueError(msg)
        if len({item.partition_key for item in partitions}) != len(partitions):
            msg = "partition keys must be unique"
            raise ValueError(msg)
        return tuple(
            sorted(
                partitions,
                key=lambda item: (item.partition_key, item.artifact.content_hash),
            )
        )

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        """Validate schema, partition, temporal, and lineage bindings together."""
        schema_hash = self.schema_definition.schema_hash
        if any(partition.schema_hash != schema_hash for partition in self.partitions):
            msg = "partition schema hash must match manifest schema hash"
            raise ValueError(msg)

        schema_field_ids = {field.field_id for field in self.schema_definition.fields}
        unknown_field_ids = set(self.temporal_contract.field_ids()) - schema_field_ids
        if unknown_field_ids:
            msg = "temporal contract field IDs must exist in the schema"
            raise ValueError(msg)

        if self.dataset_kind is DatasetKind.SOURCE_FACTS:
            if self.lineage is not None:
                msg = "source facts must not include lineage"
                raise ValueError(msg)
        elif self.lineage is None:
            msg = "derived facts require lineage"
            raise ValueError(msg)
        elif self.lineage.output_schema_hash != schema_hash:
            msg = "lineage output schema hash must match manifest schema hash"
            raise ValueError(msg)
        return self
