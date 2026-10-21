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

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid7

from drift.domain.artifacts import ArtifactKind
from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_results import EvaluationRunArtifactsV2
from drift.domain.events import AuditEvent
from drift.domain.experiments import ExperimentRun, ExperimentRunStatus
from drift.errors import DuplicateEventError
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
    CLAIM,
    CONSUMED,
    ENTITY,
    WITNESS,
    AccountAllocationFieldsV1,
    ConfiguredLocalSyntheticOriginV1,
    LocalEventReferenceV1,
    OriginalLocalAccountReadbackV1,
)
from drift.loop.stage1_synthetic_account_lifecycle import (
    Stage1SyntheticAccountLifecycleV1,
)
from drift.serialization.canonical import canonical_json, content_hash

RESULT_EVENT = "stage1.synthetic_result.original_retained"
RESULT_ENTITY = "stage1_synthetic_result"
RESULT_PROFILE = "stage1-m0-original-association/1-candidate"
M0_EVENT = "m2.evaluation.run.recorded"
MAX_ARTIFACT_BYTES = 4_194_304


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
        or payload.get("issuer_instance_id") != str(issuer)
    ):
        raise OriginalResultAssociationError("ORIGINAL_EVENT_HASH_OR_ISSUER_MISMATCH")
    return position, original


class Stage1OriginalResultAssociationV1:
    """One-shot M0 callback for one verified synthetic E1 account/trial.

    The same configured origin must contain the durable allocation, witness,
    claim, consumption, actual original M0 audit, and original result record.
    This checks a local trust boundary; independent Matthew issuer acceptance
    and scheduler evidence remain separate prerequisites.
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
        self._origin = origin
        self._account = account
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
        original = account.verified_original()
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
        self._receipt: LocalEventReferenceV1 | None = None
        self._used = False

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
        self, *, identity_hash: str, m0_event_id: UUID, m0_run_id: UUID,
        result_hash: str, trace_hash: str, final_book_hash: str,
    ) -> tuple[tuple[AuditEvent, ...], AuditEvent, AuditEvent, AuditEvent]:
        events = self._origin.verified_events()
        proof = self._account.verified_original()
        if (
            proof.fields != self._fields
            or proof.allocation_id != self._original_allocation.allocation_id
            or proof.original_book_bytes
            != self._original_allocation.original_book_bytes
        ):
            raise OriginalResultAssociationError("ACCOUNT_ORIGINAL_CHANGED")
        allocation_id = proof.allocation_id
        i_alloc, alloc = _original_event(
            events, index_ref=proof.allocation_ref, kind=ALLOCATION,
            entity_id=allocation_id, issuer=self._origin.issuer_instance_id,
        )
        i_witness, witness = _original_event(
            events, index_ref=proof.witness_ref, kind=WITNESS,
            entity_id=allocation_id, issuer=self._origin.issuer_instance_id,
        )
        allocations = _mapping(alloc.payload, "ALLOCATION_PAYLOAD_MISSING")
        if allocations.get("fields") != asdict(self._fields):
            raise OriginalResultAssociationError("ALLOCATION_FIELD_ORIGINAL_MISMATCH")
        witness_data = _mapping(witness.payload, "WITNESS_PAYLOAD_MISSING")
        if (
            witness_data.get("allocation_event_hash") != alloc.event_hash
            or witness_data.get("allocation_event_id") != str(alloc.event_id)
        ):
            raise OriginalResultAssociationError("WITNESS_NOT_ORIGINAL_ALLOCATION")
        i_claim, claim = _exact_event(events, kind=CLAIM, entity_id=allocation_id)
        i_cons, consumed = _exact_event(events, kind=CONSUMED, entity_id=allocation_id)
        if (
            claim.entity_type != ENTITY
            or consumed.entity_type != ENTITY
            or claim.schema_version != "1"
            or consumed.schema_version != "1"
        ):
            raise OriginalResultAssociationError("NOT_ORIGINAL_ACCOUNT_EVENT")
        claimed = _mapping(claim.payload, "CLAIM_NOT_STRUCTURED")
        used = _mapping(consumed.payload, "CONSUMPTION_NOT_STRUCTURED")
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
            or used.get("original_book_sha256") != sha256(
                proof.original_book_bytes
            ).hexdigest()
            or not i_alloc < i_witness < i_claim < i_cons
            or not alloc.timestamp <= witness.timestamp <= claim.timestamp
            or not claim.timestamp <= consumed.timestamp
        ):
            raise OriginalResultAssociationError("ORIGINAL_CONSUMPTION_NOT_PROVEN")
        m0_matches = [
            (i, event) for i, event in enumerate(events)
            if event.event_type == M0_EVENT and event.entity_id == m0_run_id
        ]
        if len(m0_matches) != 1:
            raise OriginalResultAssociationError("M0_RUN_MISSING_OR_DUPLICATE")
        i_m0, m0_event = m0_matches[0]
        m0_payload = _mapping(m0_event.payload, "M0_AUDIT_PAYLOAD_INVALID")
        if (
            m0_event.event_id != m0_event_id
            or m0_event.entity_type != "experiment_run"
            or m0_event.schema_version != "2"
            or m0_payload.get("status") != "completed"
            or m0_payload.get("artifact_hashes") != (result_hash, trace_hash)
            # The opt-in M0 V2 audit itself commits to the real final book,
            # before this observer receives any post-hoc artifact copy.
            or m0_payload.get("original_final_book_hash") != final_book_hash
            or i_m0 <= i_cons
            or m0_event.timestamp < consumed.timestamp
        ):
            raise OriginalResultAssociationError("NOT_THE_ORIGINAL_COMPLETED_M0")
        return events, claim, consumed, m0_event

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
            or len(original_bytes) > MAX_ARTIFACT_BYTES
            or canonical_json(rebuilt) != original_bytes
            or canonical_run.completed_at is None
        ):
            raise OriginalResultAssociationError("M0_COMPLETED_ARTIFACTS_UNAVAILABLE")
        result = rebuilt.result
        trace = rebuilt.trace
        book = rebuilt.final_state
        identity = result.run_identity
        by_kind = {
            ref.kind: ref.content_hash
            for ref in canonical_run.artifact_references
        }
        if (
            len(canonical_run.artifact_references) != 2
            or len(by_kind) != 2
            or by_kind.get(ArtifactKind.RESULT) != result.result_hash
            or by_kind.get(ArtifactKind.LOG) != trace.trace_hash
            or identity.admission_hash != self._fields.admission_hash
            or identity.protocol_hash != self._fields.protocol_hash
            or result.metrics.initial_cash != Decimal(self._fields.initial_cash)
            or result.metrics.initial_net_asset_value != Decimal(
                self._fields.initial_cash
            )
            or result.metrics.ending_net_asset_value != book.net_asset_value
            or book.admission_hash != self._fields.admission_hash
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
        if observed < m0.timestamp or observed < consumed.timestamp:
            raise OriginalResultAssociationError("RESULT_RECORD_PRECEDES_ORIGINAL")
        scope = self._provenance.scope
        original = self._original_allocation
        result_hash = result.result_hash
        trace_hash = trace.trace_hash
        fields = {
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
            "original_artifacts_utf8": original_bytes.decode("utf-8"),
            "scientifically_qualified": False,
        }
        # A single original invocation cannot become multiple independent
        # results merely by changing an M0 UUID or E1 checkpoint.
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
            schema_version="1",
        )
        # The configured original ledger is the same trusted-host root that
        # holds original allocation + M0, not one named by a caller receipt.
        writer = SQLiteLedger(self._origin.ledger_path)
        try:
            appended = writer.append(draft)
        except DuplicateEventError as error:
            raise OriginalResultAssociationError(
                "DUPLICATE_ORIGINAL_RESULT"
            ) from error
        # No fallible clock/readback operation AFTER this durable commit.
        # A later explicit readback may independently refuse evidence; that
        # does not retroactively classify this successful append as failed.
        self._receipt = LocalEventReferenceV1(
            appended.event_id, appended.event_hash
        )

    def readback(self) -> LocalOriginalResultReadbackV1:
        """Independently re-open and verify original local result event bytes."""
        reference = self._receipt
        if reference is None:
            raise OriginalResultAssociationError("ORIGINAL_RESULT_NOT_RETAINED")
        events = self._origin.verified_events()
        position, receipt = _exact_event(
            events, kind=RESULT_EVENT,
            entity_id=self._original_allocation.allocation_id,
        )
        data = _mapping(receipt.payload, "RESULT_PAYLOAD_NOT_STRUCTURED")
        scope = self._provenance.scope
        if (
            receipt.event_id != reference.event_id
            or receipt.event_hash != reference.event_hash
            or receipt.entity_type != RESULT_ENTITY
            or receipt.schema_version != "1"
            or data.get("profile") != RESULT_PROFILE
            or data.get("issuer_instance_id") != str(
                self._origin.issuer_instance_id
            )
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
        original_text = data.get("original_artifacts_utf8")
        if type(original_text) is not str:
            raise OriginalResultAssociationError("RESULT_ORIGINAL_BYTES_MISSING")
        original = original_text.encode("utf-8")
        if (
            len(original) > MAX_ARTIFACT_BYTES
            or sha256(original).hexdigest()
            != data.get("original_artifacts_sha256")
        ):
            raise OriginalResultAssociationError("RESULT_ORIGINAL_BYTES_HASH_INVALID")
        artifacts = EvaluationRunArtifactsV2.model_validate_json(original)
        if (
            canonical_json(artifacts) != original
            or artifacts.result.result_hash != data.get("result_hash")
            or artifacts.trace.trace_hash != data.get("trace_hash")
            or content_hash(artifacts.final_state) != data.get("final_book_hash")
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
        if position == 0:
            raise OriginalResultAssociationError("RESULT_WITHOUT_PREDECESSORS")
        history, claim, used, m0 = self._verified_chain(
            identity_hash=artifacts.result.run_identity.run_identity_hash,
            m0_event_id=m0_id,
            m0_run_id=m0_run_id,
            result_hash=artifacts.result.result_hash,
            trace_hash=artifacts.trace.trace_hash,
            final_book_hash=content_hash(artifacts.final_state),
        )
        m0_position = next(
            index for index, event in enumerate(history)
            if event.event_id == m0.event_id
        )
        if position <= m0_position:
            raise OriginalResultAssociationError(
                "RESULT_PREDATES_ORIGINAL_M0_EVENT"
            )
        if (
            data.get("allocation_event_hash")
            != self._original_allocation.allocation_ref.event_hash
            or data.get("witness_event_hash")
            != self._original_allocation.witness_ref.event_hash
            or data.get("claim_event_hash") != claim.event_hash
            or data.get("consumption_event_hash") != used.event_hash
            or data.get("m0_event_hash") != m0.event_hash
            or data.get("run_identity_hash")
            != artifacts.result.run_identity.run_identity_hash
            or receipt.timestamp < m0.timestamp
        ):
            raise OriginalResultAssociationError("RESULT_ORIGINAL_LINEAGE_MISMATCH")
        observed = _utc_now(self._clock)
        if observed < receipt.timestamp:
            raise OriginalResultAssociationError("RESULT_READBACK_CLOCK_ROLLBACK")
        return LocalOriginalResultReadbackV1(
            association_ref=reference,
            allocation_ref=self._original_allocation.allocation_ref,
            result_hash=artifacts.result.result_hash,
            trace_hash=artifacts.trace.trace_hash,
            final_book_hash=content_hash(artifacts.final_state),
            operational_m0_run_id=m0_run_id,
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
