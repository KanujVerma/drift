"""Original controlled-campaign records in the existing append-only ledger.

A read captures one verified original prefix. All downstream account/result
readers receive that same prefix, not a moving ledger. This is consistency under
the declared trusted local host, not authentication against a hostile host.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from drift.domain.events import AuditEvent
from drift.intelligence.contracts import CostReceipt
from drift.intelligence.receipts import ResearchReceiptStore
from drift.ledger.sqlite import SQLiteLedger
from drift.ledger.stage1_synthetic_account_receipts import (
    ConfiguredLocalSyntheticOriginV1,
)
from drift.loop.stage1_controlled_contracts import (
    ENTITY,
    EVENT_PREFIX,
    ControlledCampaignPlanV1,
    ControlledEnvelopeV1,
    ControlledRecord,
    CostRecordV1,
    GrantRecordV1,
    ManifestRecordV1,
    OriginalReferenceV1,
    ResearchOutputRecordV1,
    detached,
)
from drift.loop.stage1_controlled_transport import (
    append_envelope,
    decode_original_events,
)
from drift.serialization.canonical import canonical_json


def observed_time(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("CONTROLLED_CLOCK_REQUIRES_AWARE_ORIGINAL_INSTANT")
    return value.astimezone(UTC)


def reference(event: AuditEvent) -> OriginalReferenceV1:
    return OriginalReferenceV1(
        event_id=UUID(int=event.event_id.int), event_hash=event.event_hash
    )


class _CapturedOrigin(ConfiguredLocalSyntheticOriginV1):
    """Private read-only origin adapter, created only by reading the real root."""

    def __init__(
        self, origin: ConfiguredLocalSyntheticOriginV1, as_of_event_hash: str | None
    ) -> None:
        if type(origin) is not ConfiguredLocalSyntheticOriginV1:
            raise ValueError("CONTROLLED_EXACT_CONFIGURED_ORIGIN_REQUIRED")
        super().__init__(origin.ledger_path, UUID(int=origin.issuer_instance_id.int))
        original = origin.verified_events()
        if as_of_event_hash is not None:
            positions = [
                i
                for i, event in enumerate(original)
                if event.event_hash == as_of_event_hash
            ]
            if len(positions) != 1:
                raise ValueError("CONTROLLED_SNAPSHOT_TIP_NOT_ORIGINAL")
            original = original[: positions[0] + 1]
        object.__setattr__(
            self, "_captured_bytes", tuple(canonical_json(event) for event in original)
        )

    def verified_events(self) -> tuple[AuditEvent, ...]:
        # Consumers cannot mutate the stored snapshot through a returned UUID,
        # object.__setattr__, or a previously retained event reference.
        originals: tuple[bytes, ...] = object.__getattribute__(self, "_captured_bytes")
        return tuple(AuditEvent.model_validate_json(data) for data in originals)


@dataclass(frozen=True, slots=True)
class ControlledRowV1:
    sequence: int
    event: AuditEvent
    envelope: ControlledEnvelopeV1

    @property
    def record(self) -> ControlledRecord:
        return self.envelope.record

    @property
    def ref(self) -> OriginalReferenceV1:
        return reference(self.event)


class CapturedControlledJournalV1:
    """One consistent actual prefix plus complete controlled-namespace inventory."""

    def __init__(
        self,
        *,
        origin: ConfiguredLocalSyntheticOriginV1,
        allocation_id: UUID,
        observed_at: datetime,
        as_of_event_hash: str | None = None,
    ) -> None:
        self.origin = _CapturedOrigin(origin, as_of_event_hash)
        self.events = self.origin.verified_events()
        self.observed_at = observed_time(lambda: observed_at)
        self.by_id = {
            event.event_id: (index, event) for index, event in enumerate(self.events)
        }
        self.by_hash = {
            event.event_hash: (index, event) for index, event in enumerate(self.events)
        }
        self.tip = reference(self.events[-1]) if self.events else None
        decoded = decode_original_events(self.events, self.origin.issuer_instance_id)
        all_rows = [ControlledRowV1(*row) for row in decoded.rows]
        manifests: dict[UUID, ControlledRowV1] = {}
        for row in all_rows:
            if isinstance(row.record, ManifestRecordV1):
                ident = row.envelope.allocation_id
                if ident in manifests:
                    raise ValueError("CONTROLLED_DUPLICATE_MANIFEST")
                manifests[ident] = row
        # Do not make a foreign entity ID a filtering escape. Every controlled
        # row must name one real original manifest and agree with its scope.
        for row in all_rows:
            manifest = manifests.get(row.envelope.allocation_id)
            if manifest is None or not isinstance(manifest.record, ManifestRecordV1):
                raise ValueError("CONTROLLED_ORPHAN_RECORD_WITHOUT_MANIFEST")
            expected = ControlledEnvelopeV1.create(
                issuer=self.origin.issuer_instance_id,
                plan=manifest.record.plan,
                record=row.record,
            )
            if row.envelope != expected or row.sequence < manifest.sequence:
                raise ValueError("CONTROLLED_MANIFEST_SCOPE_OR_ORDER_MISMATCH")
        selected = manifests.get(allocation_id)
        if selected is None or not isinstance(selected.record, ManifestRecordV1):
            raise ValueError("CONTROLLED_ORIGINAL_MANIFEST_UNAVAILABLE")
        self.manifest = selected
        self.plan = detached(ControlledCampaignPlanV1, selected.record.plan)
        self.rows = tuple(
            row for row in all_rows if row.envelope.allocation_id == allocation_id
        )
        self.rows_by_id = {row.event.event_id: row for row in self.rows}
        self.rows_by_hash = {row.event.event_hash: row for row in self.rows}
        physical_ids = {
            ident for row in self.rows for ident in decoded.members[row.event.event_id]
        }
        self.physical_events = tuple(
            event for event in self.events if event.event_id in physical_ids
        )
        if any(row.event.timestamp > self.observed_at for row in self.rows):
            raise ValueError("CONTROLLED_READ_BEFORE_ORIGINAL_AVAILABILITY")
        if any(
            left.event.timestamp > right.event.timestamp
            for left, right in zip(self.rows, self.rows[1:], strict=False)
        ):
            raise ValueError("CONTROLLED_ORIGINAL_CLOCK_ROLLBACK")

    def resolve(
        self, ref: OriginalReferenceV1, *, before: ControlledRowV1 | None = None
    ) -> ControlledRowV1:
        ref = detached(OriginalReferenceV1, ref)
        found = self.rows_by_id.get(ref.event_id)
        if found is None or found.event.event_hash != ref.event_hash:
            raise ValueError("CONTROLLED_REFERENCE_NOT_IN_ORIGINAL_SCOPE")
        if before is not None and (
            found.sequence >= before.sequence
            or found.event.timestamp > before.event.timestamp
        ):
            raise ValueError("CONTROLLED_REFERENCE_NOT_CAUSAL")
        return found

    def original(
        self, ref: OriginalReferenceV1, *, before: ControlledRowV1 | None = None
    ) -> AuditEvent:
        ref = detached(OriginalReferenceV1, ref)
        found = self.by_id.get(ref.event_id)
        if found is None or found[1].event_hash != ref.event_hash:
            raise ValueError("CONTROLLED_ORIGINAL_REFERENCE_UNAVAILABLE")
        if before is not None and (
            found[0] >= before.sequence or found[1].timestamp > before.event.timestamp
        ):
            raise ValueError("CONTROLLED_ORIGINAL_REFERENCE_NOT_CAUSAL")
        return found[1]


class ControlledJournalWriterV1:
    """Single-run writer with a terminal uncertainty latch, never a retry service."""

    def __init__(
        self,
        *,
        origin: ConfiguredLocalSyntheticOriginV1,
        plan: ControlledCampaignPlanV1,
        clock: Callable[[], datetime],
    ) -> None:
        if type(origin) is not ConfiguredLocalSyntheticOriginV1:
            raise ValueError("CONTROLLED_EXACT_CONFIGURED_ORIGIN_REQUIRED")
        self.origin = origin
        self.plan = detached(ControlledCampaignPlanV1, plan)
        self.clock = clock
        events = origin.verified_events()
        allocation = plan.original_account.allocation_id
        if any(
            (event.event_type.startswith(EVENT_PREFIX) or event.entity_type == ENTITY)
            and (
                event.entity_id == allocation
                or (
                    isinstance(event.payload, Mapping)
                    and event.payload.get("allocation_id") == str(allocation)
                )
            )
            for event in events
        ):
            raise ValueError("CONTROLLED_ACCOUNT_ALREADY_RESERVED_NO_RETRY")
        witness = next(
            (e for e in events if e.event_id == plan.original_account.witness.event_id),
            None,
        )
        if (
            witness is None
            or witness.event_hash != plan.original_account.witness.event_hash
        ):
            raise ValueError("CONTROLLED_ORIGINAL_WITNESS_UNAVAILABLE")
        self._last_time = witness.timestamp
        self._failed = False
        self._terminal = False
        self._keys: set[str] = set()
        self._ledger = SQLiteLedger.open_existing(origin.ledger_path)
        # Open read-only first, verifying schema protections, before obtaining
        # an ordinary writer. This never repairs a missing/damaged cold root.
        self._ledger.verify_chain()
        self._ledger = SQLiteLedger(origin.ledger_path)

    def append(
        self, record: ControlledRecord, *, key: str, at: datetime | None = None
    ) -> AuditEvent:
        if self._failed or self._terminal:
            raise ValueError("CONTROLLED_WRITER_CLOSED_OR_UNCERTAIN")
        if type(key) is not str or not key or key in self._keys:
            raise ValueError("CONTROLLED_DUPLICATE_PHASE_NO_RETRY")
        self._keys.add(key)
        try:
            when = (
                observed_time(self.clock) if at is None else observed_time(lambda: at)
            )
            if when < self._last_time:
                raise ValueError("CONTROLLED_WRITER_CLOCK_ROLLBACK")
            envelope = ControlledEnvelopeV1.create(
                issuer=self.origin.issuer_instance_id, plan=self.plan, record=record
            )
            event = append_envelope(
                self._ledger,
                envelope,
                when=when,
                key=f"stage1:controlled:{self.plan.original_account.allocation_id}:{key}",
            )
            self._last_time = when
            self._terminal = record.kind == "terminal"
            return event
        except Exception:
            # This includes committed-but-unacknowledged appends. Only cold
            # readback may report what exists; this object never repeats it.
            self._failed = True
            raise


def append_controlled_cost_correction(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    allocation_id: UUID,
    checkpoint_id: str,
    correction: CostReceipt,
    clock: Callable[[], datetime],
) -> OriginalReferenceV1:
    """Retain one actual-cost correction without retrying research or execution.

    The configured origin and current verified prefix are read independently.
    A competing correction uses the same durable supersession deduplication key,
    so concurrent writers cannot turn two estimates into independent expenses.
    An append error is surfaced, including a lost acknowledgement. Callers may
    cold-read the ledger; this function never loops or reallocates an account.
    """
    when = observed_time(clock)
    captured = CapturedControlledJournalV1(
        origin=origin, allocation_id=allocation_id, observed_at=when
    )
    correction = CostReceipt.model_validate_json(canonical_json(correction))
    if (
        correction.amount_basis != "actual"
        or correction.supersedes_receipt_id is None
        or correction.raw_evidence_ref is None
        or correction.recorded_at is None
        or correction.recorded_at > when
    ):
        raise ValueError("CONTROLLED_CORRECTION_REQUIRES_ORIGINAL_ACTUAL_EVIDENCE")
    if checkpoint_id not in {item.checkpoint_id for item in captured.plan.checkpoints}:
        raise ValueError("CONTROLLED_CORRECTION_UNDECLARED_CHECKPOINT")
    costs = ResearchReceiptStore()
    original_row: ControlledRowV1 | None = None
    grant_row: ControlledRowV1 | None = None
    output_row: ControlledRowV1 | None = None
    for row in captured.rows:
        record = row.record
        if isinstance(record, GrantRecordV1) and record.checkpoint_id == checkpoint_id:
            if grant_row is not None:
                raise ValueError("CONTROLLED_CORRECTION_DUPLICATE_GRANT")
            grant_row = row
        if (
            isinstance(record, ResearchOutputRecordV1)
            and record.checkpoint_id == checkpoint_id
        ):
            if output_row is not None:
                raise ValueError("CONTROLLED_CORRECTION_DUPLICATE_OUTPUT")
            output_row = row
        if isinstance(record, CostRecordV1):
            costs.record_cost_receipt(record.original)
            if record.original.receipt_id == correction.receipt_id:
                if (
                    record.checkpoint_id != checkpoint_id
                    or record.original != correction
                ):
                    raise ValueError("CONTROLLED_CORRECTION_IDENTITY_CONFLICT")
                return row.ref
            if record.original.receipt_id == correction.supersedes_receipt_id:
                original_row = row
    if original_row is None or grant_row is None or output_row is None:
        raise ValueError("CONTROLLED_CORRECTION_MISSING_ORIGINAL_COST_OR_OUTPUT")
    assert isinstance(original_row.record, CostRecordV1)
    assert isinstance(grant_row.record, GrantRecordV1)
    if (
        original_row.record.checkpoint_id != checkpoint_id
        or captured.resolve(original_row.record.grant, before=original_row) != grant_row
        or correction.attempt_id != grant_row.record.attempt_id
        or correction.recorded_at < output_row.event.timestamp
        or original_row.record.original.recorded_at is None
        or correction.recorded_at < original_row.record.original.recorded_at
    ):
        raise ValueError("CONTROLLED_CORRECTION_WRONG_ORIGINAL_OR_CHRONOLOGY")
    costs.record_cost_receipt(correction)
    envelope = ControlledEnvelopeV1.create(
        issuer=origin.issuer_instance_id,
        plan=captured.plan,
        record=CostRecordV1(
            checkpoint_id=checkpoint_id, grant=grant_row.ref, original=correction
        ),
    )
    ledger = SQLiteLedger(origin.ledger_path)
    event = append_envelope(
        ledger,
        envelope,
        when=when,
        key=(
            f"stage1:controlled:{allocation_id}:correction:"
            + correction.supersedes_receipt_id
        ),
    )
    return reference(event)
