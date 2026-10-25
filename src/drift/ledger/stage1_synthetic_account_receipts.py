"""Bounded local synthetic account receipts over Drift's existing SQLite ledger.

A configured origin is provided by a trusted *host harness*, never recovered
from a caller's receipt or a claimed issuer name. This is NOT a remote signature
or proof against a privileged host replacing its own trusted configuration.
Original account issuance and first observation are separate recorded events.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid7

from drift.domain.common import ImmutableJSONValue
from drift.domain.evaluator_portfolio import PortfolioStateV2
from drift.domain.events import AuditEvent
from drift.errors import DuplicateEventError
from drift.ledger.interface import AuditEventDraft
from drift.ledger.sqlite import SQLiteLedger
from drift.serialization.canonical import canonical_json, content_hash

PROFILE = "drift-stage1-synthetic-account-local/1-candidate"
ALLOCATION = "stage1.synthetic_account.allocation"
WITNESS = "stage1.synthetic_account.allocation_observed"
CLAIM = "stage1.synthetic_account.invocation_claim"
CONSUMED = "stage1.synthetic_account.book_consumed"
ENTITY = "stage1_synthetic_account"
MAX_BOOK_BYTES = 1_048_576
_EVENTS = frozenset({ALLOCATION, WITNESS, CLAIM, CONSUMED})


class LocalAccountReceiptError(ValueError):
    """Refusal from original account retention/readback, not a trading status."""


@dataclass(frozen=True, slots=True)
class LocalEventReferenceV1:
    event_id: UUID
    event_hash: str


@dataclass(frozen=True, slots=True)
class AccountAllocationFieldsV1:
    """Verified E1 and actual engine fields retained beside original book bytes."""

    campaign_id: str
    run_id: str
    arm_id: str
    portfolio_account_id: str
    binding_id: str
    bound_at: str
    binding_hash: str
    campaign_fingerprint: str
    arm_fingerprint: str
    complete_manifest_fingerprint: str
    admission_hash: str
    protocol_hash: str
    first_session_fingerprint: str
    initial_cash: str
    currency: str

    @property
    def allocation_key(self) -> str:
        # No checkpoint and no operational UUID: repeat requests cannot fund
        # a new account simply by changing either downstream identifier.
        return f"{self.campaign_id}:{self.run_id}:{self.arm_id}"


@dataclass(frozen=True, slots=True)
class OriginalLocalAccountReadbackV1:
    """Original bytes + independent ledger witness, not general issuer authority."""

    fields: AccountAllocationFieldsV1
    allocation_ref: LocalEventReferenceV1
    witness_ref: LocalEventReferenceV1
    allocation_id: UUID
    original_book_bytes: bytes
    opening_book: PortfolioStateV2
    receipt_observed_available_by_at: datetime

    @property
    def original_issuer_authenticated_for_e6b(self) -> bool:
        # Independent D2 approval and scheduler witness visibility remain open.
        return False


@dataclass(frozen=True, slots=True)
class ConfiguredLocalSyntheticOriginV1:
    """Trusted host configuration, supplied out of band from all receipts.

    This object alone is NOT a cryptographic capability. The caller must
    actually be the trusted host, since an arbitrary attacker can instantiate
    an equally shaped configuration using a forged SQLite file.
    """

    ledger_path: Path
    issuer_instance_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.ledger_path, Path) or not self.ledger_path.is_absolute():
            raise LocalAccountReceiptError("LOCAL_ORIGIN_NEEDS_ABSOLUTE_HOST_PATH")
        if (
            type(self.issuer_instance_id) is not UUID
            or self.issuer_instance_id.version != 7
        ):
            raise LocalAccountReceiptError("LOCAL_ORIGIN_NEEDS_UUID7_ISSUER")

    def verified_events(self) -> tuple[AuditEvent, ...]:
        # Never accept a path from receipt data. open_existing is read only and
        # will not create, restore, or silently repair a missing fake ledger.
        return SQLiteLedger.open_existing(self.ledger_path).verified_events()


def _event_ref(event: AuditEvent) -> LocalEventReferenceV1:
    return LocalEventReferenceV1(event.event_id, event.event_hash)


def _event_payload(event: AuditEvent) -> Mapping[str, ImmutableJSONValue]:
    """Verify a structured original event, not the general JSON scalar union."""
    payload = event.payload
    if not isinstance(payload, Mapping):
        raise LocalAccountReceiptError("ORIGINAL_EVENT_PAYLOAD_NOT_MAPPING")
    return payload


def _require_ref(ref: LocalEventReferenceV1) -> None:
    if (
        type(ref) is not LocalEventReferenceV1
        or type(ref.event_id) is not UUID
        or ref.event_id.version != 7
        or type(ref.event_hash) is not str
        or len(ref.event_hash) != 64
        or any(c not in "0123456789abcdef" for c in ref.event_hash)
    ):
        raise LocalAccountReceiptError("INVALID_ORIGINAL_EVENT_REFERENCE")


def read_configured_original(
    *,
    origin: ConfiguredLocalSyntheticOriginV1,
    reference: LocalEventReferenceV1,
    event_type: str,
    allocation_id: UUID,
) -> AuditEvent:
    """Verify one original in the host-configured ledger, never a claimed one."""
    _require_ref(reference)
    if event_type not in _EVENTS:
        raise LocalAccountReceiptError("INVALID_ORIGINAL_EVENT_TYPE")
    matches = [e for e in origin.verified_events() if e.event_id == reference.event_id]
    if len(matches) != 1:
        raise LocalAccountReceiptError("ORIGINAL_EVENT_NOT_IN_CONFIGURED_LEDGER")
    event = matches[0]
    payload = _event_payload(event)
    if (
        event.event_hash != reference.event_hash
        or event.event_type != event_type
        or event.entity_type != ENTITY
        or event.entity_id != allocation_id
        or event.schema_version != "1"
        or payload.get("profile") != PROFILE
        or payload.get("issuer_instance_id") != str(origin.issuer_instance_id)
    ):
        raise LocalAccountReceiptError("ORIGINAL_EVENT_OR_ISSUER_MISMATCH")
    return event


def _utc_now(clock: Callable[[], datetime]) -> datetime:
    observed = clock()
    if type(observed) is not datetime or observed.tzinfo is None:
        raise LocalAccountReceiptError("UNTRUSTED_OR_NAIVE_OBSERVATION_CLOCK")
    offset = observed.utcoffset()
    if offset is None:
        raise LocalAccountReceiptError("UNTRUSTED_OR_NAIVE_OBSERVATION_CLOCK")
    return observed.astimezone(UTC)


class LocalSyntheticAccountReceiptStoreV1:
    """Only this configured writer may append locally observed original events.

    An issuer identity string or self-consistent event hash from the caller
    does not authorize account origin. The supplied host origin must be pinned
    outside the untrusted record/experiment source.
    """

    def __init__(
        self,
        *,
        origin: ConfiguredLocalSyntheticOriginV1,
        clock: Callable[[], datetime],
    ) -> None:
        self.origin = origin
        self._clock = clock
        self._writer = SQLiteLedger(origin.ledger_path)

    def _append(
        self,
        *,
        kind: str,
        allocation_id: UUID,
        dedup_key: str,
        payload: Mapping[str, ImmutableJSONValue],
        minimum_time: datetime | None = None,
        precommit_guard: Callable[[], None] | None = None,
    ) -> LocalEventReferenceV1:
        now = _utc_now(self._clock)
        if minimum_time is not None and now < minimum_time:
            raise LocalAccountReceiptError("CLOCK_ROLLBACK_BEFORE_ORIGINAL")
        # A test-harness observation clock may be a callback into the
        # caller-owned E1 source. Recheck the captured-snapshot binding
        # *after* that callback, immediately before the append. This is a
        # refusal gate, not a cryptographic lock on other Python threads.
        if precommit_guard is not None:
            precommit_guard()
        draft = AuditEventDraft(
            event_id=uuid7(),
            event_type=kind,
            timestamp=now,
            entity_type=ENTITY,
            entity_id=allocation_id,
            payload={
                "profile": PROFILE,
                "issuer_instance_id": str(self.origin.issuer_instance_id),
                **payload,
            },
            deduplication_key=dedup_key,
            schema_version="1",
        )
        try:
            appended = self._writer.append(draft)
        except DuplicateEventError as exc:
            raise LocalAccountReceiptError("DUPLICATE_OR_CONFLICTING_ORIGINAL") from exc
        ref = _event_ref(appended)
        read_configured_original(
            origin=self.origin,
            reference=ref,
            event_type=kind,
            allocation_id=allocation_id,
        )
        return ref

    def append_allocation(
        self,
        *,
        fields: AccountAllocationFieldsV1,
        original_book: bytes,
        precommit_guard: Callable[[], None] | None = None,
    ) -> tuple[UUID, LocalEventReferenceV1]:
        if type(fields) is not AccountAllocationFieldsV1:
            raise LocalAccountReceiptError("INVALID_ALLOCATION_FIELDS")
        if (
            type(original_book) is not bytes
            or not original_book
            or len(original_book) > MAX_BOOK_BYTES
        ):
            raise LocalAccountReceiptError("INVALID_OR_OVERSIZE_ORIGINAL_BOOK")
        if type(fields.bound_at) is not str:
            raise LocalAccountReceiptError("NONCANONICAL_ACCOUNT_BOUND_AT")
        try:
            bound_at = datetime.fromisoformat(
                fields.bound_at.replace("Z", "+00:00")
            ).astimezone(UTC)
        except (TypeError, ValueError) as error:
            raise LocalAccountReceiptError("NONCANONICAL_ACCOUNT_BOUND_AT") from error
        if bound_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != fields.bound_at:
            raise LocalAccountReceiptError("NONCANONICAL_ACCOUNT_BOUND_AT")
        allocation_id = uuid7()
        ref = self._append(
            kind=ALLOCATION,
            allocation_id=allocation_id,
            dedup_key=f"stage1:allocation:{fields.allocation_key}",
            minimum_time=bound_at,
            precommit_guard=precommit_guard,
            payload={
                "allocation_id": str(allocation_id),
                "fields": asdict(fields),
                "original_book_utf8": original_book.decode("utf-8"),
                "original_book_sha256": sha256(original_book).hexdigest(),
            },
        )
        return allocation_id, ref

    def witness_original_readback(
        self,
        *,
        allocation_id: UUID,
        allocation_ref: LocalEventReferenceV1,
        precommit_guard: Callable[[], None] | None = None,
    ) -> LocalEventReferenceV1:
        alloc = read_configured_original(
            origin=self.origin,
            reference=allocation_ref,
            event_type=ALLOCATION,
            allocation_id=allocation_id,
        )
        # The clock is sampled only AFTER confirmed durable original readback.
        # This is a conservative observed-by instant for the ALLOCATION receipt,
        # not the exact moment the WITNESS itself first became visible.
        return self._append(
            kind=WITNESS,
            allocation_id=allocation_id,
            dedup_key=f"stage1:allocation-witness:{allocation_id}",
            minimum_time=alloc.timestamp,
            precommit_guard=precommit_guard,
            payload={
                "allocation_event_id": str(allocation_ref.event_id),
                "allocation_event_hash": allocation_ref.event_hash,
            },
        )

    def readback_allocation(
        self,
        *,
        allocation_id: UUID,
        allocation_ref: LocalEventReferenceV1,
        witness_ref: LocalEventReferenceV1,
        expected_fields: AccountAllocationFieldsV1,
        postread_guard: Callable[[], None] | None = None,
    ) -> OriginalLocalAccountReadbackV1:
        alloc = read_configured_original(
            origin=self.origin,
            reference=allocation_ref,
            event_type=ALLOCATION,
            allocation_id=allocation_id,
        )
        witness = read_configured_original(
            origin=self.origin,
            reference=witness_ref,
            event_type=WITNESS,
            allocation_id=allocation_id,
        )
        allocation_payload = _event_payload(alloc)
        witness_payload = _event_payload(witness)
        if (
            allocation_payload.get("allocation_id") != str(allocation_id)
            or allocation_payload.get("fields") != asdict(expected_fields)
            or witness_payload.get("allocation_event_id")
            != str(allocation_ref.event_id)
            or witness_payload.get("allocation_event_hash") != allocation_ref.event_hash
            or witness.timestamp < alloc.timestamp
        ):
            raise LocalAccountReceiptError(
                "ORIGINAL_ALLOCATION_SCOPE_OR_WITNESS_MISMATCH"
            )
        text = allocation_payload.get("original_book_utf8")
        if type(text) is not str:
            raise LocalAccountReceiptError("ORIGINAL_BOOK_BYTES_MISSING")
        original = text.encode("utf-8")
        if len(original) > MAX_BOOK_BYTES or sha256(
            original
        ).hexdigest() != allocation_payload.get("original_book_sha256"):
            raise LocalAccountReceiptError("ORIGINAL_BOOK_BYTES_HASH_MISMATCH")
        book = PortfolioStateV2.model_validate_json(original)
        if canonical_json(book) != original:
            raise LocalAccountReceiptError("ORIGINAL_BOOK_BYTES_NOT_CANONICAL")
        if (
            book.admission_hash != expected_fields.admission_hash
            or content_hash(book.session_key)
            != expected_fields.first_session_fingerprint
            or book.cash_balance != Decimal(expected_fields.initial_cash)
            or book.net_asset_value != book.cash_balance
            or book.holdings
            or book.pending_cash_claims
            or book.mark is not None
            or book.settled_claim_ids
            or book.applied_effect_ids
            or book.holdings_market_value != 0
            or book.pending_claims_value != 0
            or book.cumulative_transaction_costs != 0
            or book.realized_gross_pnl != 0
            or book.realized_net_pnl != 0
        ):
            raise LocalAccountReceiptError("ORIGINAL_BOOK_NOT_FRESH_ENGINE_SHAPE")
        if postread_guard is not None:
            postread_guard()
        return OriginalLocalAccountReadbackV1(
            fields=expected_fields,
            allocation_ref=allocation_ref,
            witness_ref=witness_ref,
            allocation_id=allocation_id,
            original_book_bytes=original,
            opening_book=book,
            receipt_observed_available_by_at=witness.timestamp,
        )

    def append_invocation_claim(
        self,
        *,
        original: OriginalLocalAccountReadbackV1,
        identity_hash: str,
        precommit_guard: Callable[[], None] | None = None,
    ) -> LocalEventReferenceV1:
        return self._append(
            kind=CLAIM,
            allocation_id=original.allocation_id,
            dedup_key=f"stage1:invocation:{original.allocation_id}",
            minimum_time=original.receipt_observed_available_by_at,
            precommit_guard=precommit_guard,
            payload={
                "allocation_event_hash": original.allocation_ref.event_hash,
                "witness_event_hash": original.witness_ref.event_hash,
                "identity_hash": identity_hash,
            },
        )

    def append_consumption(
        self,
        *,
        original: OriginalLocalAccountReadbackV1,
        claim_ref: LocalEventReferenceV1,
        identity_hash: str,
        precommit_guard: Callable[[], None] | None = None,
    ) -> LocalEventReferenceV1:
        claim = read_configured_original(
            origin=self.origin,
            reference=claim_ref,
            event_type=CLAIM,
            allocation_id=original.allocation_id,
        )
        claim_payload = _event_payload(claim)
        if (
            claim_payload.get("allocation_event_hash")
            != original.allocation_ref.event_hash
            or claim_payload.get("witness_event_hash")
            != original.witness_ref.event_hash
            or claim_payload.get("identity_hash") != identity_hash
        ):
            raise LocalAccountReceiptError("CONSUMPTION_CLAIM_SCOPE_MISMATCH")
        return self._append(
            kind=CONSUMED,
            allocation_id=original.allocation_id,
            dedup_key=f"stage1:consumed:{original.allocation_id}",
            minimum_time=claim.timestamp,
            precommit_guard=precommit_guard,
            payload={
                "claim_event_hash": claim_ref.event_hash,
                "allocation_event_hash": original.allocation_ref.event_hash,
                "identity_hash": identity_hash,
                "original_book_sha256": sha256(
                    original.original_book_bytes
                ).hexdigest(),
            },
        )
