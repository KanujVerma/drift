"""Immutable M1e acquisition domain models, byte graph, and receipts."""

from collections import deque
from enum import StrEnum
from typing import Literal, Self

from pydantic import field_validator, model_validator

from drift.domain.artifacts import ArtifactReference
from drift.domain.common import (
    UUID7,
    FrozenModel,
    ImmutableJSON,
    NonBlankStr,
    SHA256Hash,
    UTCDateTime,
)
from drift.domain.provenance_references import validate_safe_provenance_reference
from drift.serialization.canonical import content_hash


class ByteLayerKind(StrEnum):
    """Specific physical/logical layer of an acquired byte payload."""

    TRANSPORT_ENTITY = "transport_entity"
    STORED_ARCHIVE_OR_FILE = "stored_archive_or_file"
    DECOMPRESSED_PAYLOAD = "decompressed_payload"
    ARCHIVE_MEMBER = "archive_member"
    DECODED_PROVIDER_NATIVE_RECORD = "decoded_provider_native_record"
    DRIFT_CANONICAL_RECORD = "drift_canonical_record"


class AcquisitionCompleteness(StrEnum):
    """Closed-world evaluation status of an acquisition."""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


class OriginStatus(StrEnum):
    """Provenance resolution state for acquired content."""

    VERIFIED = "verified"
    UNKNOWN = "unknown"


class ByteTransformationOperation(StrEnum):
    """Closed set of operations transforming byte layers."""

    TRANSFER_DECODE = "transfer_decode"
    STORE_ARCHIVE = "store_archive"
    DECOMPRESS = "decompress"
    EXTRACT_ARCHIVE_MEMBER = "extract_archive_member"
    DECODE_PROVIDER_NATIVE_RECORD = "decode_provider_native_record"
    NORMALIZE_CANONICAL = "normalize_canonical"


def _sorted_unique(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


class ByteObjectV1(FrozenModel):
    """Immutable descriptor of a specific byte layer."""

    schema_version: Literal["1"] = "1"
    layer: ByteLayerKind
    artifact_reference: ArtifactReference
    byte_size: int
    content_hash: SHA256Hash
    media_type: NonBlankStr
    content_encoding: NonBlankStr | None = None
    archive_identity: NonBlankStr | None = None
    member_identity: NonBlankStr | None = None

    @property
    def descriptor_hash(self) -> SHA256Hash:
        """Deterministic canonical descriptor hash distinguishing this layer."""
        return content_hash(self)

    @field_validator("byte_size")
    @classmethod
    def validate_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("byte size cannot be negative")
        return value

    @field_validator("artifact_reference")
    @classmethod
    def validate_ref(cls, value: ArtifactReference) -> ArtifactReference:
        return validate_safe_provenance_reference(value)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.artifact_reference.content_hash != self.content_hash:
            raise ValueError("artifact reference content hash must match object hash")
        if self.layer is ByteLayerKind.ARCHIVE_MEMBER and not self.member_identity:
            raise ValueError("archive member layer requires member identity")
        return self


class ByteTransformationV1(FrozenModel):
    """Lineage edge connecting input and output byte descriptors."""

    schema_version: Literal["1"] = "1"
    input_descriptor_hash: SHA256Hash
    output_descriptor_hash: SHA256Hash
    operation: ByteTransformationOperation
    tool_implementation_hash: SHA256Hash
    parameters: ImmutableJSON = None
    lossless: bool

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        if self.input_descriptor_hash == self.output_descriptor_hash:
            raise ValueError("transformation input and output cannot be identical")
        return self


class NativeByteGraphV1(FrozenModel):
    """Acyclic lineage graph of byte transformations."""

    schema_version: Literal["1"] = "1"
    objects: tuple[ByteObjectV1, ...]
    transformations: tuple[ByteTransformationV1, ...]
    retained_root_descriptor_hashes: tuple[SHA256Hash, ...]
    provider_native_leaf_descriptor_hashes: tuple[SHA256Hash, ...]

    @property
    def graph_hash(self) -> SHA256Hash:
        """Canonical hash of the byte graph."""
        return content_hash(self)

    @field_validator(
        "retained_root_descriptor_hashes",
        "provider_native_leaf_descriptor_hashes",
    )
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="byte graph boundary hashes")

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        obj_hashes = {obj.descriptor_hash for obj in self.objects}
        if len(obj_hashes) != len(self.objects):
            raise ValueError("byte graph objects must have unique descriptor hashes")

        # Check transformation endpoints exist
        adjacency: dict[str, list[str]] = {h: [] for h in obj_hashes}
        in_degrees: dict[str, int] = {h: 0 for h in obj_hashes}
        out_degrees: dict[str, int] = {h: 0 for h in obj_hashes}

        for t in self.transformations:
            if t.input_descriptor_hash not in obj_hashes:
                raise ValueError(
                    f"transformation input {t.input_descriptor_hash} "
                    "not in graph objects"
                )
            if t.output_descriptor_hash not in obj_hashes:
                raise ValueError(
                    f"transformation output {t.output_descriptor_hash} "
                    "not in graph objects"
                )
            adjacency[t.input_descriptor_hash].append(t.output_descriptor_hash)
            in_degrees[t.output_descriptor_hash] += 1
            out_degrees[t.input_descriptor_hash] += 1

        # Check for cycles using Kahn's algorithm
        kahn_in_degrees = dict(in_degrees)
        queue = deque([h for h, deg in kahn_in_degrees.items() if deg == 0])
        visited_count = 0
        while queue:
            node = queue.popleft()
            visited_count += 1
            for neighbor in adjacency[node]:
                kahn_in_degrees[neighbor] -= 1
                if kahn_in_degrees[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(obj_hashes):
            raise ValueError("byte graph must be acyclic")

        # Check roots have in-degree 0 and leaves have out-degree 0
        for root in self.retained_root_descriptor_hashes:
            if root not in obj_hashes:
                raise ValueError(f"declared root {root} not in graph objects")
            if in_degrees[root] != 0:
                raise ValueError(f"declared root {root} has in-degree > 0")

        for leaf in self.provider_native_leaf_descriptor_hashes:
            if leaf not in obj_hashes:
                raise ValueError(f"declared leaf {leaf} not in graph objects")
            if out_degrees[leaf] != 0:
                raise ValueError(f"declared leaf {leaf} has out-degree > 0")

        # Every node with in-degree 0 must be declared in retained roots
        for h, deg in in_degrees.items():
            if deg == 0 and h not in self.retained_root_descriptor_hashes:
                raise ValueError(f"undeclared root {h} in byte graph")

        # Every node with out-degree 0 must be declared in leaves
        for h, deg in out_degrees.items():
            if deg == 0 and h not in self.provider_native_leaf_descriptor_hashes:
                raise ValueError(f"undeclared leaf {h} in byte graph")

        # Reachability: every object must be on a path from at least one root
        # to at least one leaf
        forward_reachable = set(self.retained_root_descriptor_hashes)
        q = deque(self.retained_root_descriptor_hashes)
        while q:
            curr = q.popleft()
            for nxt in adjacency[curr]:
                if nxt not in forward_reachable:
                    forward_reachable.add(nxt)
                    q.append(nxt)

        backward_adjacency: dict[str, list[str]] = {h: [] for h in obj_hashes}
        for src, dsts in adjacency.items():
            for dst in dsts:
                backward_adjacency[dst].append(src)

        backward_reachable = set(self.provider_native_leaf_descriptor_hashes)
        q_back = deque(self.provider_native_leaf_descriptor_hashes)
        while q_back:
            curr = q_back.popleft()
            for prev in backward_adjacency[curr]:
                if prev not in backward_reachable:
                    backward_reachable.add(prev)
                    q_back.append(prev)

        for h in obj_hashes:
            if h not in forward_reachable or h not in backward_reachable:
                raise ValueError(
                    f"object {h} is disconnected from root or leaf in byte graph"
                )

        return self


class ProviderNativeLayerRuleV1(FrozenModel):
    """Product-specific declaration of the authoritative provider-native layer."""

    schema_version: Literal["1"] = "1"
    profile_set_hash: SHA256Hash
    supported_profile_hashes: tuple[SHA256Hash, ...]
    product_schema_hash: SHA256Hash
    methodology_hash: SHA256Hash
    authoritative_native_layer: ByteLayerKind
    exclusions: tuple[NonBlankStr, ...] = ()

    @field_validator("supported_profile_hashes")
    @classmethod
    def canonicalize_supported_profiles(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not values:
            raise ValueError("supported profile hashes cannot be empty")
        return _sorted_unique(values, label="supported profile hashes")

    @field_validator("exclusions")
    @classmethod
    def canonicalize_exclusions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="rule exclusions")

    @model_validator(mode="after")
    def validate_native_layer(self) -> Self:
        if self.authoritative_native_layer is ByteLayerKind.DRIFT_CANONICAL_RECORD:
            raise ValueError(
                "provider-native layer precedes Drift normalization "
                "and cannot be canonical record"
            )
        return self


class RequestIdentityV1(FrozenModel):
    """Credential-free identity of an acquisition request."""

    schema_version: Literal["1"] = "1"
    method: NonBlankStr
    authenticated_provider_host: NonBlankStr
    route_template: NonBlankStr
    canonical_parameters: ImmutableJSON = None
    requested_universe: tuple[NonBlankStr, ...]
    requested_fields: tuple[NonBlankStr, ...]
    requested_date_range: tuple[NonBlankStr, NonBlankStr]
    requested_cutoff: UTCDateTime | None = None
    request_start: UTCDateTime
    request_end: UTCDateTime
    client_request_id: NonBlankStr

    @field_validator("requested_universe", "requested_fields")
    @classmethod
    def canonicalize_request_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="request scope lists")

    @model_validator(mode="after")
    def validate_request_bounds(self) -> Self:
        if self.request_end < self.request_start:
            raise ValueError("request end cannot precede request start")
        if "@" in self.authenticated_provider_host:
            raise ValueError(
                "authenticated provider host must not contain user credentials"
            )
        return self


class OriginEvidenceV1(FrozenModel):
    """Proof of provider origin for acquired bytes."""

    schema_version: Literal["1"] = "1"
    origin_status: OriginStatus
    provider_request_id: NonBlankStr | None = None
    provider_object_id: NonBlankStr | None = None
    safe_response_metadata: ImmutableJSON = None
    tls_endpoint_identity: NonBlankStr | None = None
    provider_checksums: tuple[NonBlankStr, ...] = ()
    provider_signatures: tuple[NonBlankStr, ...] = ()
    provider_manifest_references: tuple[ArtifactReference, ...] = ()
    evidence_references: tuple[ArtifactReference, ...] = ()

    @field_validator("provider_checksums", "provider_signatures")
    @classmethod
    def canonicalize_evidence_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="origin evidence collections")

    @model_validator(mode="after")
    def validate_origin_claims(self) -> Self:
        if self.origin_status is OriginStatus.VERIFIED:
            has_evidence = bool(
                self.tls_endpoint_identity
                or self.provider_checksums
                or self.provider_signatures
                or self.provider_manifest_references
            )
            if not has_evidence:
                raise ValueError("verified origin status requires external evidence")
        return self


class PageReceiptV1(FrozenModel):
    """Receipt for one acquired page or chunk."""

    schema_version: Literal["1"] = "1"
    page_identity: NonBlankStr
    page_order: int
    cursor_in: NonBlankStr | None = None
    cursor_out: NonBlankStr | None = None
    byte_object_descriptor_hashes: tuple[SHA256Hash, ...]
    attempt_identity: NonBlankStr
    result: NonBlankStr
    duplicates: tuple[NonBlankStr, ...] = ()
    failure_evidence: tuple[ArtifactReference, ...] = ()

    @field_validator("page_order")
    @classmethod
    def validate_order(cls, value: int) -> int:
        if value < 0:
            raise ValueError("page order must be non-negative")
        return value

    @field_validator("byte_object_descriptor_hashes", "duplicates")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="page receipt hashes")


class RetryReceiptV1(FrozenModel):
    """Receipt for a failed or superseded acquisition attempt."""

    schema_version: Literal["1"] = "1"
    attempt_identity: NonBlankStr
    attempt_order: int
    page_identity: NonBlankStr
    byte_object_descriptor_hashes: tuple[SHA256Hash, ...] = ()
    result: NonBlankStr
    failure_evidence: tuple[ArtifactReference, ...] = ()

    @field_validator("attempt_order")
    @classmethod
    def validate_order(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempt order must be positive")
        return value


class ExpectedObjectV1(FrozenModel):
    """Specification of one expected object in the closed-world inventory."""

    schema_version: Literal["1"] = "1"
    object_key: NonBlankStr
    endpoint_or_file: NonBlankStr
    as_of_universe_rule: NonBlankStr
    fields: tuple[NonBlankStr, ...]
    dates: tuple[NonBlankStr, ...]
    partitions: tuple[NonBlankStr, ...] = ()
    expected_count: int | None = None
    source_of_enumeration: NonBlankStr
    justification: NonBlankStr

    @field_validator("fields", "dates", "partitions")
    @classmethod
    def canonicalize_spec_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="expected object collections")


class ExpectedInventoryV1(FrozenModel):
    """Pre-request closed-world manifest of expected objects."""

    schema_version: Literal["1"] = "1"
    inventory_id: UUID7
    objects: tuple[ExpectedObjectV1, ...]
    enumeration_source: NonBlankStr
    justification: NonBlankStr
    frozen_at: UTCDateTime

    @field_validator("objects")
    @classmethod
    def canonicalize_objects(
        cls, values: tuple[ExpectedObjectV1, ...]
    ) -> tuple[ExpectedObjectV1, ...]:
        keys = [obj.object_key for obj in values]
        if len(keys) != len(set(keys)):
            raise ValueError("expected objects must have unique object keys")
        return tuple(sorted(values, key=lambda o: o.object_key))


class AcquisitionPlanV1(FrozenModel):
    """Pre-request immutable authorization binding and scope limits."""

    schema_version: Literal["1"] = "1"
    plan_id: UUID7
    authorization_hash: SHA256Hash
    request_scope_hash: SHA256Hash
    expected_inventory_hash: SHA256Hash
    planned_native_layer_rule_hash: SHA256Hash
    max_bytes: int
    max_objects: int
    max_pages: int
    frozen_at: UTCDateTime

    @property
    def plan_hash(self) -> SHA256Hash:
        return content_hash(self)

    @field_validator("max_bytes", "max_objects", "max_pages")
    @classmethod
    def validate_positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("acquisition limits must be strictly positive")
        return value


class ObservedObjectV1(FrozenModel):
    """One observed object mapped to origin and byte evidence."""

    schema_version: Literal["1"] = "1"
    provider_object_identity: NonBlankStr
    matched_expected_key: NonBlankStr | None = None
    page_identity: NonBlankStr
    byte_object_descriptor_hashes: tuple[SHA256Hash, ...]
    origin_evidence: OriginEvidenceV1
    observation_status: NonBlankStr

    @field_validator("byte_object_descriptor_hashes")
    @classmethod
    def canonicalize_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="observed object descriptor hashes")


class AcquisitionReconciliationV1(FrozenModel):
    """Deterministic closed-world reconciliation result."""

    schema_version: Literal["1"] = "1"
    expected_keys: tuple[NonBlankStr, ...]
    received_keys: tuple[NonBlankStr, ...]
    missing_keys: tuple[NonBlankStr, ...]
    duplicate_keys: tuple[NonBlankStr, ...]
    extra_keys: tuple[NonBlankStr, ...]
    cursor_cycle_detected: bool
    cursor_chain: tuple[NonBlankStr | None, ...]
    count_reconciled: bool
    snapshot_token_consistent: bool
    snapshot_tokens: tuple[NonBlankStr, ...]
    result: AcquisitionCompleteness
    reasons: tuple[NonBlankStr, ...]

    @field_validator("expected_keys", "missing_keys", "duplicate_keys", "extra_keys")
    @classmethod
    def canonicalize_key_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="reconciliation keys")


class AcquisitionExecutionContextV1(FrozenModel):
    """Safe runtime execution metadata for the acquisition invocation."""

    schema_version: Literal["1"] = "1"
    collector_id: NonBlankStr
    collector_version: NonBlankStr
    collector_source_hash: SHA256Hash
    invocation_id: UUID7
    executable_evidence_hashes: tuple[SHA256Hash, ...]
    receipt_id: UUID7
    receipt_version: NonBlankStr
    creation_time: UTCDateTime
    safe_execution_metadata: ImmutableJSON = None

    @field_validator("executable_evidence_hashes")
    @classmethod
    def canonicalize_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="executable evidence hashes")


class AcquisitionReceiptV1(FrozenModel):
    """Immutable evidence receipt of an executed acquisition."""

    schema_version: Literal["1"] = "1"
    receipt_id: UUID7
    receipt_version: NonBlankStr
    created_at: UTCDateTime
    acquisition_plan_hash: SHA256Hash
    authorization_hash: SHA256Hash
    profile_set_hash: SHA256Hash
    request: RequestIdentityV1
    native_layer_rule: ProviderNativeLayerRuleV1
    byte_graph: NativeByteGraphV1
    byte_graph_hash: SHA256Hash
    pages: tuple[PageReceiptV1, ...]
    retries: tuple[RetryReceiptV1, ...]
    observed_objects: tuple[ObservedObjectV1, ...]
    expected_inventory_hash: SHA256Hash
    reconciliation_hash: SHA256Hash
    schema_evidence_hashes: tuple[SHA256Hash, ...]
    methodology_evidence_hashes: tuple[SHA256Hash, ...]
    license_evidence_hashes: tuple[SHA256Hash, ...]
    collector_source_hash: SHA256Hash
    collector_version: NonBlankStr

    @field_validator(
        "schema_evidence_hashes",
        "methodology_evidence_hashes",
        "license_evidence_hashes",
    )
    @classmethod
    def canonicalize_evidence_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="receipt evidence hashes")

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> Self:
        if self.byte_graph_hash != content_hash(self.byte_graph):
            raise ValueError("byte graph hash must match canonical byte graph content")
        return self


class PrivateStorePolicyV1(FrozenModel):
    """Externally approved policy for private content-addressed storage."""

    schema_version: Literal["1"] = "1"
    policy_id: UUID7
    policy_version: NonBlankStr
    approved_root_identifier: NonBlankStr
    access_control_evidence_hashes: tuple[SHA256Hash, ...]
    encryption_evidence_hashes: tuple[SHA256Hash, ...]
    allowed_object_classes: tuple[NonBlankStr, ...]
    backup_locations: tuple[NonBlankStr, ...]
    max_object_bytes: int
    max_total_pilot_bytes: int

    @property
    def policy_hash(self) -> SHA256Hash:
        return content_hash(self)

    @field_validator("access_control_evidence_hashes", "encryption_evidence_hashes")
    @classmethod
    def canonicalize_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="policy evidence hashes")

    @field_validator("allowed_object_classes", "backup_locations")
    @classmethod
    def canonicalize_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="policy scopes")

    @field_validator("max_object_bytes", "max_total_pilot_bytes")
    @classmethod
    def validate_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("private store quota limits must be strictly positive")
        return value


class PrivateStoreInventoryV1(FrozenModel):
    """Committed contents and cumulative quota tracking for one pilot store."""

    schema_version: Literal["1"] = "1"
    pilot_id: UUID7
    committed_transaction_ids: tuple[UUID7, ...]
    object_hashes: tuple[SHA256Hash, ...]
    descriptor_hashes: tuple[SHA256Hash, ...]
    cumulative_unique_bytes: int
    quota_bytes: int
    inventory_version: int

    @property
    def inventory_hash(self) -> SHA256Hash:
        """Canonical hash of the store inventory."""
        return content_hash(self)

    @field_validator("object_hashes", "descriptor_hashes")
    @classmethod
    def canonicalize_inventory_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(values, label="store inventory hashes")

    @field_validator("cumulative_unique_bytes")
    @classmethod
    def validate_bytes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("cumulative bytes cannot be negative")
        return value


class StoredContentObjectV1(FrozenModel):
    """Immutable index entry of a verified object stored in the private store."""

    schema_version: Literal["1"] = "1"
    content_hash: SHA256Hash
    byte_size: int
    location_reference: ArtifactReference
    rights_binding_hash: SHA256Hash
    object_class: NonBlankStr
    store_policy_hash: SHA256Hash

    @field_validator("byte_size")
    @classmethod
    def validate_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("byte size cannot be negative")
        return value

    @field_validator("location_reference")
    @classmethod
    def validate_ref(cls, value: ArtifactReference) -> ArtifactReference:
        return validate_safe_provenance_reference(value)

    @model_validator(mode="after")
    def validate_stored_consistency(self) -> Self:
        if self.location_reference.content_hash != self.content_hash:
            raise ValueError("location reference content hash must match object hash")
        return self
