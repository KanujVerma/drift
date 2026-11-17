"""Local synthetic original M0/M2 RESULT retention, dependent on #547/#549.

This adapter is invoked only after M0 canonicalizes the *actual* returned
evaluator artifacts and appends the original completed M0 audit event. It
retains those bytes in the independently configured local ledger and binds
them to verified original allocation, witnessed readback, one claim, and one
consumption. A result being retained is NOT scientifically qualified and
does not establish a generally authenticated account issuer.

No evaluator, ledger schema, core RESULT hash, E1 hash, cost ledger, or broker
implementation is replaced or bypassed.
"""

from __future__ import annotations

import base64
import binascii
import zlib
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid7

from drift.domain.artifacts import ArtifactKind
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_results import (
    EvaluationClassification,
    EvaluationRunArtifactsV2,
)
from drift.domain.events import AuditEvent
from drift.domain.experiments import ExperimentRun, ExperimentRunStatus
from drift.errors import DuplicateEventError
from drift.evaluator.opening_book_lifecycle import (
    OpeningBookLifecycleError,
    OriginalInvocationBindingV1,
    invocation_binding_payload,
    parse_original_invocation_binding,
)
from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_stage1_synthetic_br_configuration,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ALLOCATION,
    BOUND_PROFILE,
    CLAIM,
    CONSUMED,
    ENTITY,
    PROFILE,
    WITNESS,
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    LocalSyntheticAccountReceiptStoreV1,
    OriginalLocalAccountReadbackV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json, content_hash

RESULT_EVENT = "stage1.synthetic_result.original_retained"
CHUNK_EVENT = "stage1.synthetic_result.original_artifact_chunk"
M0_USE_EVENT = "stage1.synthetic_result.original_m0_claim"
RESULT_ENTITY = "stage1_synthetic_result"
RESULT_PROFILE = "stage1-m0-original-association/2-candidate"
M0_EVENT = "m2.evaluation.run.recorded"
MAX_ARTIFACT_BYTES = 4_194_304
# Keep the original v2 single-event limit, while allowing complete original
# evidence under a strictly bounded, chunked v3 original association.
MAX_ORIGINAL_ARTIFACT_BYTES = 134_217_728
MAX_COMPRESSED_ARTIFACT_BYTES = 67_108_864
ARTIFACT_CHUNK_BYTES = 262_144
MAX_ARTIFACT_CHUNKS = 256
CHUNK_ENCODING = "zlib+base64/1"


class OriginalResultAssociationError(ValueError):
    """Missing/contradictory original evidence; no E6B eligibility implied."""


@dataclass(frozen=True, slots=True)
class LocalOriginalResultReadbackV1:
    """One independently readable local association, not a scored sample."""

    association_ref: LocalEventReferenceV1
    allocation_ref: LocalEventReferenceV1
    result_hash: str
    trace_hash: str
    final_book_hash: str
    operational_m0_run_id: UUID
    invocation_binding: OriginalInvocationBindingV1
    campaign_id: str
    run_id: str
    arm_id: str
    checkpoint_id: str
    trial_id: str
    account_id: str
    complete_manifest_fingerprint: str
    classification: str
    original_artifacts_bytes: bytes
    original_artifacts: EvaluationRunArtifactsV2
    observed_readback_at: datetime

    @property
    def original_issuer_authenticated_for_e6b(self) -> bool:
        return False

    @property
    def scientifically_qualified(self) -> bool:
        return False


def _mapping(value: object, cause: str) -> Mapping[str, ImmutableJSONValue]:
    if not isinstance(value, Mapping):
        raise OriginalResultAssociationError(cause)
    if any(type(key) is not str for key in value):
        raise OriginalResultAssociationError(cause)
    return value


def _utc_now(clock: Callable[[], datetime]) -> datetime:
    result = clock()
    if type(result) is not datetime or result.tzinfo is None:
        raise OriginalResultAssociationError("RESULT_CLOCK_NOT_TRUSTED_UTC")
    if result.utcoffset() is None:
        raise OriginalResultAssociationError("RESULT_CLOCK_NOT_TRUSTED_UTC")
    return result.astimezone(UTC)


def _invocation_binding(
    payload: Mapping[str, ImmutableJSONValue],
) -> OriginalInvocationBindingV1:
    try:
        return parse_original_invocation_binding(payload.get("invocation_binding"))
    except OpeningBookLifecycleError as error:
        raise OriginalResultAssociationError(
            "ORIGINAL_INVOCATION_BINDING_INVALID"
        ) from error


def _captured_reference(reference: LocalEventReferenceV1) -> LocalEventReferenceV1:
    """Detach canonical locator leaves before comparison or caller copy hooks."""
    if type(reference) is not LocalEventReferenceV1:
        raise OriginalResultAssociationError("RESULT_REFERENCE_INVALID")
    try:
        identifier = reference.event_id
        digest = reference.event_hash
        if type(identifier) is not UUID or type(digest) is not str:
            raise OriginalResultAssociationError("RESULT_REFERENCE_INVALID")
        bits = identifier.int
    except AttributeError as error:
        raise OriginalResultAssociationError("RESULT_REFERENCE_INVALID") from error
    if type(bits) is not int or not 0 <= bits < 1 << 128:
        raise OriginalResultAssociationError("RESULT_REFERENCE_INVALID")
    captured = UUID(int=bits)
    if (
        captured.version != 7
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise OriginalResultAssociationError("RESULT_REFERENCE_INVALID")
    return LocalEventReferenceV1(captured, digest)


def _exact_event(
    events: tuple[AuditEvent, ...],
    *,
    kind: str,
    entity_id: UUID,
) -> tuple[int, AuditEvent]:
    selected = [
        (index, event)
        for index, event in enumerate(events)
        if event.event_type == kind and event.entity_id == entity_id
    ]
    if len(selected) != 1:
        raise OriginalResultAssociationError("MISSING_OR_DUPLICATE_ORIGINAL_EVENT")
    return selected[0]


def _original_event(
    events: tuple[AuditEvent, ...],
    *,
    index_ref: LocalEventReferenceV1,
    kind: str,
    entity_id: UUID,
    issuer: UUID,
) -> tuple[int, AuditEvent]:
    position, original = _exact_event(events, kind=kind, entity_id=entity_id)
    payload = _mapping(original.payload, "ORIGINAL_EVENT_NOT_STRUCTURED")
    if (
        original.event_id != index_ref.event_id
        or original.event_hash != index_ref.event_hash
        or original.entity_type != ENTITY
        or original.schema_version != "1"
        or payload.get("profile") != PROFILE
        or payload.get("issuer_instance_id") != str(issuer)
    ):
        raise OriginalResultAssociationError("ORIGINAL_EVENT_HASH_OR_ISSUER_MISMATCH")
    return position, original


def _account_artifact_chunks(
    events: tuple[AuditEvent, ...],
    *,
    allocation_id: UUID,
    allocation_hash: str,
    m0_event_hash: object,
) -> list[tuple[int, AuditEvent]]:
    """Inventory every chunk naming this original account, body or envelope.

    Both inline and chunked RESULT readers must use the same complete
    allocation-touching inventory. A foreign event envelope cannot hide a
    chunk whose retained body still cites the original allocation or M0.
    """
    return [
        (position, event)
        for position, event in enumerate(events)
        if event.event_type == CHUNK_EVENT
        and (
            event.entity_id == allocation_id
            or (
                isinstance(event.payload, Mapping)
                and (
                    event.payload.get("allocation_event_hash") == allocation_hash
                    or event.payload.get("m0_event_hash") == m0_event_hash
                )
            )
        )
    ]


def _read_original_chunked_artifacts(
    *,
    events: tuple[AuditEvent, ...],
    result_position: int,
    data: Mapping[str, ImmutableJSONValue],
    issuer: UUID,
    allocation_id: UUID,
    allocation_hash: str,
) -> bytes:
    """Cold-read every original chunk from the single verified ledger snapshot.

    Chunk references are identities within the trusted configured origin, not
    alternative caller-supplied paths or URLs. Every chunk, its ordering and
    byte payload must be accounted for before decompression or RESULT scoring.
    """
    expected_count = data.get("artifact_chunk_count")
    expected_length = data.get("artifact_original_size")
    expected_packed_length = data.get("artifact_compressed_size")
    expected_hashes = data.get("artifact_chunk_event_hashes")
    expected_ids = data.get("artifact_chunk_event_ids")
    if (
        data.get("artifact_encoding") != CHUNK_ENCODING
        or type(expected_count) is not int
        or not 1 <= expected_count <= MAX_ARTIFACT_CHUNKS
        or type(expected_length) is not int
        or not MAX_ARTIFACT_BYTES < expected_length <= MAX_ORIGINAL_ARTIFACT_BYTES
        or type(expected_packed_length) is not int
        or not 1 <= expected_packed_length <= MAX_COMPRESSED_ARTIFACT_BYTES
        or type(expected_hashes) is not tuple
        or len(expected_hashes) != expected_count
        or any(type(item) is not str for item in expected_hashes)
        or type(expected_ids) is not tuple
        or len(expected_ids) != expected_count
        or any(type(item) is not str for item in expected_ids)
    ):
        raise OriginalResultAssociationError("RESULT_CHUNK_MANIFEST_INVALID")
    parts = _account_artifact_chunks(
        events,
        allocation_id=allocation_id,
        allocation_hash=allocation_hash,
        m0_event_hash=data.get("m0_event_hash"),
    )
    if len(parts) != expected_count:
        raise OriginalResultAssociationError("RESULT_CHUNK_INVENTORY_INCOMPLETE")
    compressed = bytearray()
    for index, (position, event) in enumerate(parts):
        fields = _mapping(event.payload, "RESULT_CHUNK_NOT_STRUCTURED")
        encoded = fields.get("data_base64")
        if (
            position >= result_position
            or event.entity_id != allocation_id
            or event.entity_type != RESULT_ENTITY
            or event.schema_version != "1"
            or event.event_id.version != 7
            or str(event.event_id) != expected_ids[index]
            or event.event_hash != expected_hashes[index]
            or event.deduplication_key != f"stage1:result-chunk:{allocation_id}:{index}"
            or fields.get("profile") != RESULT_PROFILE
            or fields.get("issuer_instance_id") != str(issuer)
            or fields.get("allocation_event_hash") != allocation_hash
            or fields.get("m0_event_hash") != data.get("m0_event_hash")
            or fields.get("original_artifacts_sha256")
            != data.get("original_artifacts_sha256")
            or fields.get("compressed_sha256") != data.get("artifact_compressed_sha256")
            or type(fields.get("chunk_index")) is not int
            or fields.get("chunk_index") != index
            or type(fields.get("chunk_count")) is not int
            or fields.get("chunk_count") != expected_count
            or type(encoded) is not str
            or not encoded
            or len(encoded) > ((ARTIFACT_CHUNK_BYTES + 2) // 3) * 4
        ):
            raise OriginalResultAssociationError("RESULT_CHUNK_ORIGINAL_MISMATCH")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise OriginalResultAssociationError(
                "RESULT_CHUNK_ENCODING_INVALID"
            ) from error
        if (
            not raw
            or len(raw) > ARTIFACT_CHUNK_BYTES
            or base64.b64encode(raw).decode("ascii") != encoded
            or sha256(raw).hexdigest() != fields.get("chunk_sha256")
        ):
            raise OriginalResultAssociationError("RESULT_CHUNK_BYTES_INVALID")
        compressed.extend(raw)
        if len(compressed) > MAX_COMPRESSED_ARTIFACT_BYTES:
            raise OriginalResultAssociationError("RESULT_COMPRESSED_ARTIFACT_TOO_LARGE")
    if len(compressed) != expected_packed_length or sha256(
        compressed
    ).hexdigest() != data.get("artifact_compressed_sha256"):
        raise OriginalResultAssociationError("RESULT_COMPRESSED_ARTIFACT_HASH_INVALID")
    decoder = zlib.decompressobj()
    try:
        original = decoder.decompress(compressed, MAX_ORIGINAL_ARTIFACT_BYTES + 1)
        if (
            len(original) != expected_length
            or decoder.unconsumed_tail
            or decoder.unused_data
            or not decoder.eof
            or sha256(original).hexdigest() != data.get("original_artifacts_sha256")
        ):
            raise OriginalResultAssociationError(
                "RESULT_ORIGINAL_ARTIFACT_REBUILD_INVALID"
            )
    except zlib.error as error:
        raise OriginalResultAssociationError(
            "RESULT_ARTIFACT_COMPRESSION_INVALID"
        ) from error
    return original


class _OriginalResultVerifier:
    """Shared verification for live observation and fresh-process readback."""

    def __init__(
        self,
        *,
        origin: ConfiguredLocalSyntheticOriginV1,
        read_account: Callable[[], OriginalLocalAccountReadbackV1],
        provenance: Stage1TrialProvenanceSnapshotV1,
        campaign: CampaignSpecV1,
        arms: Sequence[ArmSpecV1],
        bindings: Sequence[RunAccountBindingV1],
        expected_run_ids: Sequence[str],
        clock: Callable[[], datetime],
    ) -> None:
        self._origin = origin
        self._read_account = read_account
        self._clock = clock
        self._source = provenance
        self._provenance = deepcopy(provenance)
        self._campaign = deepcopy(campaign)
        self._arms = deepcopy(tuple(arms))
        self._bindings = deepcopy(tuple(bindings))
        self._runs = deepcopy(tuple(expected_run_ids))
        if self._campaign.campaign_type != "SYNTHETIC_TEST":
            raise OriginalResultAssociationError("ONLY_SYNTHETIC_ORIGINAL_RESULT")
        self._check_e1()
        original = read_account()
        scope = self._provenance.scope
        fields = original.fields
        matches = [
            binding
            for binding in self._bindings
            if binding.campaign_id == scope.campaign_id
            and binding.run_id == scope.run_id
            and binding.arm_id == scope.arm_id
        ]
        if len(matches) != 1:
            raise OriginalResultAssociationError("E1_ACCOUNT_OUTSIDE_MANIFEST")
        matching = matches[0]
        if (
            fields.campaign_id != scope.campaign_id
            or fields.run_id != scope.run_id
            or fields.arm_id != scope.arm_id
            or fields.portfolio_account_id != matching.portfolio_account_id
            or fields.binding_id != matching.binding_id
            or fields.binding_hash != content_hash(asdict(matching))
            or fields.complete_manifest_fingerprint
            != scope.complete_manifest_fingerprint
            or fields.campaign_fingerprint != scope.campaign_spec_fingerprint
            or original.original_book_bytes != canonical_json(original.opening_book)
        ):
            raise OriginalResultAssociationError("E1_TO_ACCOUNT_ORIGINAL_MISMATCH")
        self._fields: AccountAllocationFieldsV1 = deepcopy(fields)
        self._original_allocation = original

    def _check_e1(self) -> None:
        try:
            verify_stage1_synthetic_br_configuration(
                campaign=self._campaign,
                arms=self._arms,
                bindings=self._bindings,
                expected_run_ids=self._runs,
            )
            verify_stage1_trial_provenance_snapshot(
                snapshot=self._provenance,
                campaign=self._campaign,
                arms=self._arms,
                bindings=self._bindings,
                expected_run_ids=self._runs,
            )
            verify_stage1_trial_provenance_snapshot(
                snapshot=self._source,
                campaign=self._campaign,
                arms=self._arms,
                bindings=self._bindings,
                expected_run_ids=self._runs,
            )
        except (TypeError, ValueError) as error:
            raise OriginalResultAssociationError("E1_SOURCE_NOT_VERIFIED") from error
        if self._source != self._provenance:
            raise OriginalResultAssociationError("E1_SOURCE_CHANGED_AFTER_VALIDATION")

    def _verified_chain(
        self,
        *,
        identity_hash: str,
        m0_event_id: UUID,
        m0_run_id: UUID,
        result_hash: str,
        trace_hash: str,
        final_book_hash: str,
        captured_events: tuple[AuditEvent, ...] | None = None,
    ) -> tuple[tuple[AuditEvent, ...], AuditEvent, AuditEvent, AuditEvent]:
        # Cold RESULT and chunks must be checked against one immutable prefix;
        # a live writer must not splice a later ledger view into this proof.
        events = (
            captured_events
            if captured_events is not None
            else self._origin.verified_events()
        )
        proof = self._read_account()
        if (
            proof.fields != self._fields
            or proof.allocation_id != self._original_allocation.allocation_id
            or proof.original_book_bytes
            != self._original_allocation.original_book_bytes
        ):
            raise OriginalResultAssociationError("ACCOUNT_ORIGINAL_CHANGED")
        allocation_id = proof.allocation_id
        i_alloc, alloc = _original_event(
            events,
            index_ref=proof.allocation_ref,
            kind=ALLOCATION,
            entity_id=allocation_id,
            issuer=self._origin.issuer_instance_id,
        )
        i_witness, witness = _original_event(
            events,
            index_ref=proof.witness_ref,
            kind=WITNESS,
            entity_id=allocation_id,
            issuer=self._origin.issuer_instance_id,
        )
        allocations = _mapping(alloc.payload, "ALLOCATION_PAYLOAD_MISSING")
        if allocations.get("fields") != asdict(self._fields):
            raise OriginalResultAssociationError("ALLOCATION_FIELD_ORIGINAL_MISMATCH")
        witness_data = _mapping(witness.payload, "WITNESS_PAYLOAD_MISSING")
        if witness_data.get(
            "allocation_event_hash"
        ) != alloc.event_hash or witness_data.get("allocation_event_id") != str(
            alloc.event_id
        ):
            raise OriginalResultAssociationError("WITNESS_NOT_ORIGINAL_ALLOCATION")
        i_claim, claim = _exact_event(events, kind=CLAIM, entity_id=allocation_id)
        i_cons, consumed = _exact_event(events, kind=CONSUMED, entity_id=allocation_id)
        if (
            claim.entity_type != ENTITY
            or consumed.entity_type != ENTITY
            or claim.schema_version != "2"
            or consumed.schema_version != "2"
        ):
            raise OriginalResultAssociationError("NOT_ORIGINAL_ACCOUNT_EVENT")
        claimed = _mapping(claim.payload, "CLAIM_NOT_STRUCTURED")
        used = _mapping(consumed.payload, "CONSUMPTION_NOT_STRUCTURED")
        binding = _invocation_binding(claimed)
        bound_payload = invocation_binding_payload(binding)
        if (
            claimed.get("profile") != BOUND_PROFILE
            or used.get("profile") != BOUND_PROFILE
            or invocation_binding_payload(_invocation_binding(used)) != bound_payload
            or claim.event_id != binding.invocation_id
            or used.get("claim_event_id") != str(binding.invocation_id)
            or binding.m0_run_id != m0_run_id
            or binding.m0_audit_event_id != m0_event_id
        ):
            raise OriginalResultAssociationError("ACCOUNT_M0_INVOCATION_MISMATCH")
        if any(
            payload.get("issuer_instance_id") != str(self._origin.issuer_instance_id)
            for payload in (claimed, used)
        ):
            raise OriginalResultAssociationError("CLAIM_CONSUMPTION_WRONG_ISSUER")
        if (
            claimed.get("allocation_event_hash") != alloc.event_hash
            or claimed.get("witness_event_hash") != witness.event_hash
            or claimed.get("identity_hash") != identity_hash
            or used.get("claim_event_hash") != claim.event_hash
            or used.get("allocation_event_hash") != alloc.event_hash
            or used.get("identity_hash") != identity_hash
            or used.get("original_book_sha256")
            != sha256(proof.original_book_bytes).hexdigest()
            or not i_alloc < i_witness < i_claim < i_cons
            or not alloc.timestamp <= witness.timestamp <= claim.timestamp
            or not claim.timestamp <= consumed.timestamp
        ):
            raise OriginalResultAssociationError("ORIGINAL_CONSUMPTION_NOT_PROVEN")
        m0_matches = [
            (i, event)
            for i, event in enumerate(events)
            if event.event_type == M0_EVENT and event.entity_id == m0_run_id
        ]
        if len(m0_matches) != 1:
            raise OriginalResultAssociationError("M0_RUN_MISSING_OR_DUPLICATE")
        i_m0, m0_event = m0_matches[0]
        m0_payload = _mapping(m0_event.payload, "M0_AUDIT_PAYLOAD_INVALID")
        m0_metrics = _mapping(m0_payload.get("metrics"), "M0_METRICS_INVALID")
        if (
            m0_event.event_id != m0_event_id
            or m0_event.entity_type != "experiment_run"
            or m0_event.schema_version != "3"
            or invocation_binding_payload(_invocation_binding(m0_payload))
            != bound_payload
            or m0_payload.get("status") != "completed"
            or m0_payload.get("artifact_hashes") != (result_hash, trace_hash)
            or m0_metrics.get("result_hash") != result_hash
            or m0_metrics.get("trace_hash") != trace_hash
            or m0_metrics.get("run_identity_hash") != identity_hash
            # The opt-in M0 V3 audit itself commits to the real final book,
            # before this observer receives any post-hoc artifact copy.
            or m0_payload.get("original_final_book_hash") != final_book_hash
            or i_m0 <= i_cons
            or m0_event.timestamp < consumed.timestamp
        ):
            raise OriginalResultAssociationError("NOT_THE_ORIGINAL_COMPLETED_M0")
        return events, claim, consumed, m0_event

    def _verify_account_artifacts(self, artifacts: EvaluationRunArtifactsV2) -> None:
        result = artifacts.result
        identity = result.run_identity
        book = artifacts.final_state
        # Metrics describe completed close marks. Advancing into the next
        # session clears the old mark, so a genuine pre-close halt can leave
        # the original final holdings unvalued. Its numeric book NAV then
        # covers only cash and claims, not a completed valuation. The exact
        # result, trace and final book still require the original M0 binding.
        unmarked_halt = (
            book.mark is None
            and result.classification is not EvaluationClassification.COMPLETE
            and result.halted_session_index == result.metrics.evaluated_session_count
            and any(
                event.kind == "session_start"
                and event.session_index == result.halted_session_index
                and event.session_key == book.session_key
                for event in artifacts.trace.events
            )
            and not any(
                event.kind == "session_mark"
                and event.session_index == result.halted_session_index
                for event in artifacts.trace.events
            )
        )
        if (
            identity.admission_hash != self._fields.admission_hash
            or identity.protocol_hash != self._fields.protocol_hash
            or result.metrics.initial_cash != Decimal(self._fields.initial_cash)
            or result.metrics.initial_net_asset_value
            != Decimal(self._fields.initial_cash)
            or (
                result.metrics.ending_net_asset_value != book.net_asset_value
                and not unmarked_halt
            )
            or book.admission_hash != self._fields.admission_hash
        ):
            raise OriginalResultAssociationError("RESULT_BOOK_M0_ACCOUNT_MISMATCH")

    def _readback(
        self, reference: LocalEventReferenceV1
    ) -> LocalOriginalResultReadbackV1:
        """Independently re-open and verify original local result event bytes."""
        reference = _captured_reference(reference)
        self._check_e1()
        events = self._origin.verified_events()
        position, receipt = _exact_event(
            events,
            kind=RESULT_EVENT,
            entity_id=self._original_allocation.allocation_id,
        )
        data = _mapping(receipt.payload, "RESULT_PAYLOAD_NOT_STRUCTURED")
        binding = _invocation_binding(data)
        bound_payload = invocation_binding_payload(binding)
        scope = self._provenance.scope
        if (
            receipt.event_id != reference.event_id
            or receipt.event_hash != reference.event_hash
            or receipt.entity_type != RESULT_ENTITY
            or receipt.schema_version not in ("2", "3")
            or receipt.deduplication_key
            != f"stage1:result:{self._original_allocation.allocation_id}"
            or data.get("profile") != RESULT_PROFILE
            or data.get("issuer_instance_id") != str(self._origin.issuer_instance_id)
            or data.get("campaign_id") != scope.campaign_id
            or data.get("run_id") != scope.run_id
            or data.get("arm_id") != scope.arm_id
            or data.get("checkpoint_id") != scope.checkpoint_id
            or data.get("trial_id") != scope.trial_id
            or data.get("account_id") != self._fields.portfolio_account_id
            or data.get("complete_manifest_fingerprint")
            != scope.complete_manifest_fingerprint
            or data.get("scientifically_qualified") is not False
        ):
            raise OriginalResultAssociationError("RESULT_E1_SCOPE_ORIGIN_MISMATCH")
        if receipt.schema_version == "3":
            if "original_artifacts_utf8" in data:
                raise OriginalResultAssociationError("RESULT_CHUNK_MANIFEST_INVALID")
            original = _read_original_chunked_artifacts(
                events=events,
                result_position=position,
                data=data,
                issuer=self._origin.issuer_instance_id,
                allocation_id=self._original_allocation.allocation_id,
                allocation_hash=self._original_allocation.allocation_ref.event_hash,
            )
        else:
            if _account_artifact_chunks(
                events,
                allocation_id=self._original_allocation.allocation_id,
                allocation_hash=self._original_allocation.allocation_ref.event_hash,
                m0_event_hash=data.get("m0_event_hash"),
            ):
                raise OriginalResultAssociationError(
                    "RESULT_UNDECLARED_ARTIFACT_CHUNKS"
                )
            original_text = data.get("original_artifacts_utf8")
            if type(original_text) is not str:
                raise OriginalResultAssociationError("RESULT_ORIGINAL_BYTES_MISSING")
            original = original_text.encode("utf-8")
            if len(original) > MAX_ARTIFACT_BYTES or sha256(
                original
            ).hexdigest() != data.get("original_artifacts_sha256"):
                raise OriginalResultAssociationError(
                    "RESULT_ORIGINAL_BYTES_HASH_INVALID"
                )
        artifacts = EvaluationRunArtifactsV2.model_validate_json(original)
        self._verify_account_artifacts(artifacts)
        if (
            canonical_json(artifacts) != original
            or artifacts.result.result_hash != data.get("result_hash")
            or artifacts.trace.trace_hash != data.get("trace_hash")
            or content_hash(artifacts.final_state) != data.get("final_book_hash")
            or artifacts.result.classification.value
            != data.get("evaluator_classification")
        ):
            raise OriginalResultAssociationError("RESULT_TRACE_BOOK_ORIGINAL_CONFLICT")
        m0_run_id_text = data.get("m0_run_id")
        m0_event_text = data.get("m0_event_id")
        if type(m0_run_id_text) is not str or type(m0_event_text) is not str:
            raise OriginalResultAssociationError("RESULT_M0_ID_INVALID")
        try:
            m0_run_id, m0_id = UUID(m0_run_id_text), UUID(m0_event_text)
        except ValueError as error:
            raise OriginalResultAssociationError("RESULT_M0_ID_INVALID") from error
        if (
            str(m0_run_id) != m0_run_id_text
            or str(m0_id) != m0_event_text
            or m0_run_id.version != 7
            or m0_id.version != 7
        ):
            raise OriginalResultAssociationError("RESULT_M0_ID_INVALID")
        if position == 0:
            raise OriginalResultAssociationError("RESULT_WITHOUT_PREDECESSORS")
        history, claim, used, m0 = self._verified_chain(
            identity_hash=artifacts.result.run_identity.run_identity_hash,
            m0_event_id=m0_id,
            m0_run_id=m0_run_id,
            result_hash=artifacts.result.result_hash,
            trace_hash=artifacts.trace.trace_hash,
            final_book_hash=content_hash(artifacts.final_state),
            captured_events=events,
        )
        m0_position = next(
            index
            for index, event in enumerate(history)
            if event.event_id == m0.event_id
        )
        # The ledger's unique deduplication key on original M0 event ID
        # ensures two different accounts cannot both reserve one operational
        # run. Independently verify that reservation's scope, original event,
        # issuer and position before accepting a retained result.
        uses = [
            (index, event)
            for index, event in enumerate(history)
            if event.event_type == M0_USE_EVENT
            and isinstance(event.payload, Mapping)
            and event.payload.get("m0_event_id") == str(m0.event_id)
        ]
        if len(uses) != 1:
            raise OriginalResultAssociationError("M0_EVENT_NOT_UNIQUELY_RESERVED")
        use_position, m0_use = uses[0]
        use_payload = _mapping(m0_use.payload, "M0_USE_ORIGINAL_PAYLOAD_INVALID")
        if (
            m0_use.entity_type != RESULT_ENTITY
            or m0_use.entity_id != self._original_allocation.allocation_id
            or m0_use.schema_version != "2"
            or m0_use.deduplication_key != f"stage1:original-m0-use:{m0.event_id}"
            or use_payload.get("issuer_instance_id")
            != str(self._origin.issuer_instance_id)
            or use_payload.get("profile") != RESULT_PROFILE
            or invocation_binding_payload(_invocation_binding(use_payload))
            != bound_payload
            or use_payload.get("m0_event_hash") != m0.event_hash
            or use_payload.get("allocation_event_hash")
            != self._original_allocation.allocation_ref.event_hash
            or use_payload.get("consumption_event_hash") != used.event_hash
            or data.get("m0_use_event_hash") != m0_use.event_hash
            or not m0_position < use_position < position
            or not m0.timestamp <= m0_use.timestamp <= receipt.timestamp
        ):
            raise OriginalResultAssociationError("M0_EVENT_RESERVATION_SCOPE_MISMATCH")
        if receipt.schema_version == "3" and any(
            not (
                m0_position < index < use_position
                and m0.timestamp <= event.timestamp <= m0_use.timestamp
            )
            for index, event in enumerate(history)
            if event.event_type == CHUNK_EVENT
            and event.entity_id == self._original_allocation.allocation_id
        ):
            raise OriginalResultAssociationError(
                "ORIGINAL_CHUNK_NOT_BETWEEN_M0_AND_USE"
            )
        if (
            data.get("allocation_event_hash")
            != self._original_allocation.allocation_ref.event_hash
            or data.get("witness_event_hash")
            != self._original_allocation.witness_ref.event_hash
            or data.get("claim_event_hash") != claim.event_hash
            or data.get("consumption_event_hash") != used.event_hash
            or data.get("m0_event_hash") != m0.event_hash
            or invocation_binding_payload(
                _invocation_binding(_mapping(m0.payload, "M0_AUDIT_PAYLOAD_INVALID"))
            )
            != bound_payload
            or data.get("run_identity_hash")
            != artifacts.result.run_identity.run_identity_hash
            or receipt.timestamp < m0.timestamp
        ):
            raise OriginalResultAssociationError("RESULT_ORIGINAL_LINEAGE_MISMATCH")
        observed = _utc_now(self._clock)
        self._check_e1()
        if observed < receipt.timestamp:
            raise OriginalResultAssociationError("RESULT_READBACK_CLOCK_ROLLBACK")
        return LocalOriginalResultReadbackV1(
            association_ref=LocalEventReferenceV1(
                UUID(int=receipt.event_id.int), receipt.event_hash
            ),
            allocation_ref=self._original_allocation.allocation_ref,
            result_hash=artifacts.result.result_hash,
            trace_hash=artifacts.trace.trace_hash,
            final_book_hash=content_hash(artifacts.final_state),
            operational_m0_run_id=m0_run_id,
            invocation_binding=binding,
            campaign_id=scope.campaign_id,
            run_id=scope.run_id,
            arm_id=scope.arm_id,
            checkpoint_id=scope.checkpoint_id,
            trial_id=scope.trial_id,
            account_id=self._fields.portfolio_account_id,
            complete_manifest_fingerprint=scope.complete_manifest_fingerprint,
            classification=artifacts.result.classification.value,
            original_artifacts_bytes=original,
            original_artifacts=artifacts,
            observed_readback_at=observed,
        )


class Stage1OriginalResultAssociationV1(_OriginalResultVerifier):
    """One-shot M0 callback for one verified synthetic E1 account/trial.

    Original account events, the actual M0 audit and the retained result must
    share a configured origin and one bound invocation. Independent issuer
    acceptance and scheduler evidence remain separate prerequisites.
    """

    def __init__(
        self,
        *,
        origin: ConfiguredLocalSyntheticOriginV1,
        account: Stage1SyntheticAccountLifecycleV1,
        provenance: Stage1TrialProvenanceSnapshotV1,
        campaign: CampaignSpecV1,
        arms: Sequence[ArmSpecV1],
        bindings: Sequence[RunAccountBindingV1],
        expected_run_ids: Sequence[str],
        clock: Callable[[], datetime],
    ) -> None:
        self._account = account
        self._receipt: LocalEventReferenceV1 | None = None
        self._used = False
        super().__init__(
            origin=origin,
            read_account=account.verified_original,
            provenance=provenance,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_run_ids,
            clock=clock,
        )

    def observe_canonical_result(
        self,
        *,
        run: ExperimentRun,
        artifacts: EvaluationRunArtifactsV2,
        m0_audit_event_id: UUID,
    ) -> None:
        """Store only actual post-M0-audit artifacts, exactly once."""
        if self._used:
            raise OriginalResultAssociationError("ORIGINAL_RESULT_ALREADY_ATTEMPTED")
        self._used = True
        self._check_e1()
        if type(m0_audit_event_id) is not UUID or m0_audit_event_id.version != 7:
            raise OriginalResultAssociationError("RESULT_M0_ID_INVALID")
        if self._account.local_phase != "consumed":
            raise OriginalResultAssociationError("ORIGINAL_ACCOUNT_NOT_CONSUMED")
        # Validate detached values and original producer-computed hashes.
        try:
            canonical_run = ExperimentRun.model_validate_json(run.model_dump_json())
            original_bytes = canonical_json(artifacts)
            rebuilt = EvaluationRunArtifactsV2.model_validate_json(original_bytes)
        except (TypeError, ValueError) as error:
            raise OriginalResultAssociationError("M0_RESULT_NOT_CANONICAL") from error
        if (
            canonical_run.status is not ExperimentRunStatus.COMPLETED
            or not original_bytes
            or len(original_bytes) > MAX_ORIGINAL_ARTIFACT_BYTES
            or canonical_json(rebuilt) != original_bytes
            or canonical_run.completed_at is None
        ):
            raise OriginalResultAssociationError("M0_COMPLETED_ARTIFACTS_UNAVAILABLE")
        result = rebuilt.result
        trace = rebuilt.trace
        book = rebuilt.final_state
        identity = result.run_identity
        self._verify_account_artifacts(rebuilt)
        by_kind = {
            ref.kind: ref.content_hash for ref in canonical_run.artifact_references
        }
        if (
            len(canonical_run.artifact_references) != 2
            or len(by_kind) != 2
            or by_kind.get(ArtifactKind.RESULT) != result.result_hash
            or by_kind.get(ArtifactKind.LOG) != trace.trace_hash
            or canonical_run.dataset_hash != identity.bundle_hash
        ):
            raise OriginalResultAssociationError("RESULT_BOOK_M0_ACCOUNT_MISMATCH")
        _, claim, consumed, m0 = self._verified_chain(
            identity_hash=identity.run_identity_hash,
            m0_event_id=m0_audit_event_id,
            m0_run_id=canonical_run.run_id,
            result_hash=result.result_hash,
            trace_hash=trace.trace_hash,
            final_book_hash=content_hash(book),
        )
        if m0.timestamp != canonical_run.completed_at:
            raise OriginalResultAssociationError("M0_COMPLETION_TIMESTAMP_CONFLICT")
        observed = _utc_now(self._clock)
        self._check_e1()
        if observed < m0.timestamp or observed < consumed.timestamp:
            raise OriginalResultAssociationError("RESULT_RECORD_PRECEDES_ORIGINAL")
        scope = self._provenance.scope
        original = self._original_allocation
        result_hash = result.result_hash
        trace_hash = trace.trace_hash
        chunked = len(original_bytes) > MAX_ARTIFACT_BYTES
        packed: bytes | None = None
        chunk_count = 0
        if chunked:
            packed = zlib.compress(original_bytes, level=6)
            chunk_count = (
                len(packed) + ARTIFACT_CHUNK_BYTES - 1
            ) // ARTIFACT_CHUNK_BYTES
            if (
                not packed
                or len(packed) > MAX_COMPRESSED_ARTIFACT_BYTES
                or not 1 <= chunk_count <= MAX_ARTIFACT_CHUNKS
            ):
                raise OriginalResultAssociationError(
                    "M0_ORIGINAL_CHUNK_BUDGET_EXCEEDED"
                )
        fields: dict[str, ImmutableJSONValue] = {
            "invocation_binding": invocation_binding_payload(
                _invocation_binding(_mapping(m0.payload, "M0_AUDIT_PAYLOAD_INVALID"))
            ),
            "campaign_id": scope.campaign_id,
            "run_id": scope.run_id,
            "arm_id": scope.arm_id,
            "checkpoint_id": scope.checkpoint_id,
            "trial_id": scope.trial_id,
            "account_id": self._fields.portfolio_account_id,
            "complete_manifest_fingerprint": scope.complete_manifest_fingerprint,
            "allocation_event_hash": original.allocation_ref.event_hash,
            "witness_event_hash": original.witness_ref.event_hash,
            "claim_event_hash": claim.event_hash,
            "consumption_event_hash": consumed.event_hash,
            "m0_event_id": str(m0.event_id),
            "m0_event_hash": m0.event_hash,
            "m0_run_id": str(canonical_run.run_id),
            "run_identity_hash": identity.run_identity_hash,
            "result_hash": result_hash,
            "trace_hash": trace_hash,
            "final_book_hash": content_hash(book),
            "evaluator_classification": result.classification.value,
            "original_artifacts_sha256": sha256(original_bytes).hexdigest(),
            "scientifically_qualified": False,
        }
        if not chunked:
            fields["original_artifacts_utf8"] = original_bytes.decode("utf-8")
        else:
            assert packed is not None
            # Chunk commits occur after original M0 completion and before
            # the unique M0-result reservation; a torn append is unresolved.
            writer = SQLiteLedger(self._origin.ledger_path)
            chunk_events: list[AuditEvent] = []
            compressed_hash = sha256(packed).hexdigest()
            for index in range(chunk_count):
                start = index * ARTIFACT_CHUNK_BYTES
                raw_chunk = packed[start : start + ARTIFACT_CHUNK_BYTES]
                draft_chunk = AuditEventDraft(
                    event_id=uuid7(),
                    event_type=CHUNK_EVENT,
                    timestamp=observed,
                    entity_type=RESULT_ENTITY,
                    entity_id=original.allocation_id,
                    payload={
                        "profile": RESULT_PROFILE,
                        "issuer_instance_id": str(self._origin.issuer_instance_id),
                        "allocation_event_hash": original.allocation_ref.event_hash,
                        "m0_event_hash": m0.event_hash,
                        "original_artifacts_sha256": fields[
                            "original_artifacts_sha256"
                        ],
                        "compressed_sha256": compressed_hash,
                        "chunk_index": index,
                        "chunk_count": chunk_count,
                        "chunk_sha256": sha256(raw_chunk).hexdigest(),
                        "data_base64": base64.b64encode(raw_chunk).decode("ascii"),
                    },
                    deduplication_key=f"stage1:result-chunk:{original.allocation_id}:{index}",
                    schema_version="1",
                )
                try:
                    chunk_events.append(writer.append(draft_chunk))
                except DuplicateEventError as error:
                    raise OriginalResultAssociationError(
                        "ORIGINAL_RESULT_CHUNK_ALREADY_RETAINED"
                    ) from error
            fields.update(
                artifact_encoding=CHUNK_ENCODING,
                artifact_original_size=len(original_bytes),
                artifact_compressed_sha256=compressed_hash,
                artifact_compressed_size=len(packed),
                artifact_chunk_count=chunk_count,
                artifact_chunk_event_ids=tuple(str(e.event_id) for e in chunk_events),
                artifact_chunk_event_hashes=tuple(e.event_hash for e in chunk_events),
            )
        # Reserve the operational M0 event with its own ledger-unique key
        # BEFORE publishing the account-scoped RESULT. A key scoped only to
        # the allocation cannot stop ARM-B and ARM-R from consuming the same
        # M0 event when both have matching evaluator hashes. This first
        # append is a durable fail-closed claim, even if a later RESULT append
        # fails and must remain UNKNOWN rather than become a phantom result.
        writer = SQLiteLedger(self._origin.ledger_path)
        m0_use = AuditEventDraft(
            event_id=uuid7(),
            event_type=M0_USE_EVENT,
            timestamp=observed,
            entity_type=RESULT_ENTITY,
            entity_id=original.allocation_id,
            payload={
                "profile": RESULT_PROFILE,
                "issuer_instance_id": str(self._origin.issuer_instance_id),
                "m0_event_id": str(m0.event_id),
                "m0_event_hash": m0.event_hash,
                "allocation_event_hash": original.allocation_ref.event_hash,
                "consumption_event_hash": consumed.event_hash,
                "invocation_binding": fields["invocation_binding"],
            },
            deduplication_key=f"stage1:original-m0-use:{m0.event_id}",
            schema_version="2",
        )
        try:
            reserved = writer.append(m0_use)
        except DuplicateEventError as error:
            raise OriginalResultAssociationError(
                "ORIGINAL_M0_EVENT_ALREADY_ASSOCIATED"
            ) from error
        # A single original invocation also cannot become multiple independent
        # results merely by changing the M0 UUID or E1 checkpoint.
        fields["m0_use_event_hash"] = reserved.event_hash
        draft = AuditEventDraft(
            event_id=uuid7(),
            event_type=RESULT_EVENT,
            timestamp=observed,
            entity_type=RESULT_ENTITY,
            entity_id=original.allocation_id,
            payload={
                "profile": RESULT_PROFILE,
                "issuer_instance_id": str(self._origin.issuer_instance_id),
                **fields,
            },
            deduplication_key=f"stage1:result:{original.allocation_id}",
            schema_version="3" if chunked else "2",
        )
        # The configured original ledger is the same trusted-host root that
        # holds original allocation + M0, not one named by a caller receipt.
        try:
            appended = writer.append(draft)
        except DuplicateEventError as error:
            raise OriginalResultAssociationError("DUPLICATE_ORIGINAL_RESULT") from error
        # No fallible clock/readback operation AFTER this durable commit.
        # A later explicit readback may independently refuse evidence; that
        # does not retroactively classify this successful append as failed.
        self._receipt = LocalEventReferenceV1(appended.event_id, appended.event_hash)

    def readback(self) -> LocalOriginalResultReadbackV1:
        """Verify the exact association retained by this live callback."""
        if self._receipt is None:
            raise OriginalResultAssociationError("ORIGINAL_RESULT_NOT_RETAINED")
        return self._readback(self._receipt)


def read_original_result(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    original_account: OriginalLocalAccountReadbackV1,
    association_ref: LocalEventReferenceV1,
    provenance: Stage1TrialProvenanceSnapshotV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    clock: Callable[[], datetime],
) -> LocalOriginalResultReadbackV1:
    """Verify retained evidence after restart without reviving a writer.

    Supplied references locate evidence; they do not authenticate it. The
    configured host origin is independently reopened for the original
    allocation, witness, bound claim, consumption, M0, reservation and RESULT.
    E1 scope and complete original artifact bytes are verified again. This
    read path neither prepares a new account nor permits another callback.
    """
    reference = _captured_reference(association_ref)
    captured = deepcopy(original_account)
    store = LocalSyntheticAccountReceiptStoreV1.open_existing(
        origin=origin, clock=clock
    )

    def read_account() -> OriginalLocalAccountReadbackV1:
        original = store.readback_allocation(
            allocation_id=captured.allocation_id,
            allocation_ref=captured.allocation_ref,
            witness_ref=captured.witness_ref,
            expected_fields=captured.fields,
        )
        if (
            original.original_book_bytes != captured.original_book_bytes
            or canonical_json(captured.opening_book) != original.original_book_bytes
        ):
            raise OriginalResultAssociationError("ACCOUNT_ORIGINAL_CHANGED")
        return original

    verifier = _OriginalResultVerifier(
        origin=origin,
        read_account=read_account,
        provenance=provenance,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        clock=clock,
    )
    return verifier._readback(reference)
