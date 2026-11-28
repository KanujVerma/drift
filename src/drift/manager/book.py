"""Simulation book on the retained accounting kernel and SQLite ledger.

Session keys are a declared simulation calendar. They are not exchange
authority and they do not use realized-session stamp binding.
"""

import json
from datetime import date, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ValidationError

from drift.domain.common import ImmutableJSON
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
)
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_ABSENT_HALTS,
    ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
    ExploratoryEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    MarkEvidenceV1,
    MarkPriceV1,
    PortfolioFillV1,
)
from drift.domain.events import AuditEvent
from drift.domain.sessions import SessionKeyV1
from drift.errors import LedgerIntegrityError
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state
from drift.ledger.interface import AuditEventDraft, Ledger
from drift.manager.models import (
    CENT_BASIS_ALLOCATION,
    BenchmarkPoint,
    EvidenceItem,
    ResearchPacket,
    SimulationMandate,
    money_text,
    parse_money,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.serialization.canonical import canonical_json, content_hash

SIMULATION_MIC = "XNYS"
ENTITY_TYPE = "portfolio_book"
SCHEMA_VERSION = "1"
OPENED = "manager.book_opened"
DECISION = "manager.decision"
MARK = "manager.mark"
REFLECTION = "manager.reflection"
FEEDBACK = "manager.feedback"
INGEST = "manager.ingest"
FILL = "manager.fill"
PROSPECTIVE_REVIEW = "manager.prospective_review"
PROSPECTIVE_INTENT = "manager.prospective_intent"
PROSPECTIVE_SEAL = "manager.prospective_seal"
PROSPECTIVE_EXPIRED = "manager.prospective_expired"
PROSPECTIVE_CA_STATUS = "manager.prospective_corporate_action_status"
PROSPECTIVE_REQUEST_ATTEMPT = "manager.prospective_request_attempt"
PROSPECTIVE_REQUEST_COMPLETION = "manager.prospective_request_completion"

CLOCK_LIMITATIONS = tuple(
    sorted(
        (
            ALPACA_LIMITATION_ABSENT_HALTS,
            ALPACA_LIMITATION_SCHEDULED_SESSION_RECONSTRUCTION,
            "declared-local-calendar-not-exchange-authority",
        )
    )
)
ADMISSION_LIMITATIONS = tuple(
    sorted(
        (
            "content-hash-is-not-origin-authentication",
            "declared-local-calendar-not-exchange-authority",
            "not-promotion-evidence",
            "simulation-only-not-a-market-fill",
        )
    )
)

type Json = None | bool | int | str | list["Json"] | dict[str, "Json"]


def model_json(model: BaseModel) -> Json:
    """Canonical JSON data for a pydantic model."""
    loaded = json.loads(canonical_json(model.model_dump(mode="json")))
    return cast(Json, loaded)


def identity_hash(model: BaseModel) -> str:
    """Content hash of a model's canonical JSON."""
    return content_hash(model_json(model))


def thaw(payload: object) -> dict[str, Json]:
    """Return a plain JSON object for a ledger payload."""
    loaded = json.loads(canonical_json(payload))
    if not isinstance(loaded, dict):
        message = "ledger payload is not an object"
        raise LedgerIntegrityError(message)
    return cast(dict[str, Json], loaded)


def append_manager_event(
    ledger: Ledger,
    *,
    book_id: UUID,
    event_type: str,
    dedup_key: str,
    timestamp: datetime,
    payload: dict[str, Json],
    expected_previous_hash: str | None = None,
) -> AuditEvent:
    """Append one manager event. The dedup key is the idempotency identity."""
    draft = AuditEventDraft(
        event_id=deterministic_memory_uuid7(f"manager:{dedup_key}"),
        event_type=event_type,
        timestamp=timestamp,
        entity_type=ENTITY_TYPE,
        entity_id=book_id,
        payload=cast(ImmutableJSON, payload),
        deduplication_key=dedup_key,
        schema_version=SCHEMA_VERSION,
    )
    return ledger.append(draft, expected_previous_hash=expected_previous_hash)


def simulation_session_key(day: date) -> SessionKeyV1:
    """Session key for the declared simulation calendar."""
    return SessionKeyV1(mic=SIMULATION_MIC, session_scope="regular", local_date=day)


def _session_key(day: date) -> SessionKeyV1:
    return simulation_session_key(day)


def apply_fill_json(kernel: PortfolioAccountingKernel, fill: Json) -> None:
    """Apply one recorded fill payload to a kernel."""
    _apply_fill(kernel, fill)


def apply_mark_json(kernel: PortfolioAccountingKernel, mark: Json) -> None:
    """Apply one recorded mark payload to a kernel."""
    _apply_mark(kernel, mark)


def _evaluation_session(
    *,
    day: date,
    opened_at: datetime,
    closed_at: datetime,
) -> EvaluationSessionV1:
    record_hash = content_hash(
        {
            "role": "declared-simulation-calendar",
            "local_date": day.isoformat(),
            "opened_at": opened_at,
            "closed_at": closed_at,
        }
    )
    proof_hash = content_hash(
        {
            "role": "no-external-session-authority",
            "local_date": day.isoformat(),
        }
    )
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_session_key(day),
        opened_at=opened_at,
        closed_at=closed_at,
        authority="scheduled_reconstruction",
        authority_record_hashes=(record_hash,),
        authority_proof_hashes=(proof_hash,),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _clock(packet: ResearchPacket) -> SessionClockV1:
    sessions = tuple(
        _evaluation_session(
            day=item.local_date,
            opened_at=item.opened_at,
            closed_at=item.closed_at,
        )
        for item in packet.sessions
    )
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="scheduled_session_reconstruction",
        sessions=sessions,
        acknowledged_limitations=CLOCK_LIMITATIONS,
        clock_hash="0" * 64,
    )
    return draft.model_copy(update={"clock_hash": session_clock_hash(draft)})


def _admission(packet_hash: str) -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash=packet_hash,
        acknowledged_limitations=ADMISSION_LIMITATIONS,
        admission_hash="0" * 64,
    )
    return draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )


def symbol_for(packet: ResearchPacket, security_id: UUID) -> str:
    """Return the packet symbol for one security id."""
    for instrument in packet.instruments:
        if instrument.security_id == security_id:
            return instrument.symbol
    message = f"security {security_id} is not in the packet"
    raise LedgerIntegrityError(message)


def security_for(packet: ResearchPacket, symbol: str) -> UUID:
    """Return the packet security id for one symbol."""
    for instrument in packet.instruments:
        if instrument.symbol == symbol:
            return instrument.security_id
    message = f"symbol {symbol} is not in the packet"
    raise LedgerIntegrityError(message)


def take_snapshot(kernel: PortfolioAccountingKernel, packet: ResearchPacket) -> Json:
    """Integrity snapshot of cash, lots, and whether a mark is present."""
    state = kernel.state
    holdings: list[Json] = []
    for holding in state.holdings:
        cost = None if holding.cost_basis is None else money_text(holding.cost_basis)
        holdings.append(
            {
                "basis_status": holding.basis_status,
                "cost_basis": cost,
                "quantity": holding.quantity,
                "security_id": str(holding.security_id),
                "symbol": symbol_for(packet, holding.security_id),
            }
        )
    snapshot: dict[str, Json] = {
        "cash": money_text(state.cash_balance),
        "cumulative_transaction_costs": money_text(state.cumulative_transaction_costs),
        "holdings": holdings,
        "holdings_market_value": money_text(state.holdings_market_value),
        "marked": state.is_marked,
        "net_asset_value": money_text(state.net_asset_value),
        "realized_gross_pnl": money_text(state.realized_gross_pnl),
        "realized_net_pnl": money_text(state.realized_net_pnl),
        "session": state.session_key.local_date.isoformat(),
    }
    return cast(Json, json.loads(canonical_json(snapshot)))


def build_kernel(packet: ResearchPacket, packet_hash: str) -> PortfolioAccountingKernel:
    """Open a cash-only exploratory book on the declared calendar."""
    first = packet.sessions[0]
    state = initial_portfolio_state(
        session_key=_session_key(first.local_date),
        initial_cash=parse_money(packet.portfolio_context.cash),
        admission=_admission(packet_hash),
    )
    return PortfolioAccountingKernel(
        state,
        session_clock=_clock(packet),
        cent_basis_allocation=CENT_BASIS_ALLOCATION in packet.limitations,
    )


def _apply_advances(kernel: PortfolioAccountingKernel, advances: Json) -> None:
    if not isinstance(advances, list):
        message = "advances must be a list"
        raise LedgerIntegrityError(message)
    for item in advances:
        if not isinstance(item, str):
            message = "advance date must be text"
            raise LedgerIntegrityError(message)
        kernel.advance_session(_session_key(date.fromisoformat(item)))


def _apply_fill(kernel: PortfolioAccountingKernel, fill: Json) -> None:
    if not isinstance(fill, dict):
        message = "fill must be an object"
        raise LedgerIntegrityError(message)
    side = fill["side"]
    quantity = fill["quantity"]
    if side not in ("buy", "sell") or not isinstance(quantity, int):
        message = "fill side or quantity is malformed"
        raise LedgerIntegrityError(message)
    fill_side: Literal["buy", "sell"] = "buy" if side == "buy" else "sell"
    price = fill["fill_price"]
    costs = fill["transaction_costs"]
    security_id = fill["security_id"]
    if (
        not isinstance(price, str)
        or not isinstance(costs, str)
        or not isinstance(security_id, str)
    ):
        message = "fill fields are malformed"
        raise LedgerIntegrityError(message)
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=UUID(security_id),
            side=fill_side,
            quantity=quantity,
            fill_price=parse_money(price),
            transaction_costs=parse_money(costs),
        )
    )


def _apply_mark(kernel: PortfolioAccountingKernel, mark: Json) -> None:
    if not isinstance(mark, list):
        message = "mark must be a list"
        raise LedgerIntegrityError(message)
    prices: list[MarkPriceV1] = []
    for item in mark:
        if not isinstance(item, dict):
            message = "mark price must be an object"
            raise LedgerIntegrityError(message)
        evidence_hash = item["evidence_hash"]
        price = item["fill_price"] if "fill_price" in item else item["close_price"]
        security_id = item["security_id"]
        if (
            not isinstance(evidence_hash, str)
            or not isinstance(price, str)
            or not isinstance(security_id, str)
        ):
            message = "mark fields are malformed"
            raise LedgerIntegrityError(message)
        prices.append(
            MarkPriceV1(
                security_id=UUID(security_id),
                close_price=parse_money(price),
                evidence=MarkEvidenceV1(
                    grade="exploratory",
                    evidence_hash=evidence_hash,
                ),
            )
        )
    if not prices:
        message = "mark list is empty"
        raise LedgerIntegrityError(message)
    kernel.mark_close(prices)


def apply_recorded_effect(
    kernel: PortfolioAccountingKernel, packet: ResearchPacket, payload: dict[str, Json]
) -> None:
    """Replay advances, an optional fill, and an optional mark."""
    _apply_advances(kernel, payload.get("advances", []))
    fill = payload.get("fill")
    if fill is not None:
        _apply_fill(kernel, fill)
    mark = payload.get("mark")
    if mark is not None:
        _apply_mark(kernel, mark)
    expected = payload.get("snapshot")
    actual = take_snapshot(kernel, packet)
    if expected != actual:
        message = "replay snapshot does not match the recorded book"
        raise LedgerIntegrityError(message)


def load_inputs(
    events: tuple[AuditEvent, ...],
) -> tuple[ResearchPacket, SimulationMandate, str, str, UUID]:
    """Load the opening packet and mandate from a verified event stream."""
    if not events or events[0].event_type != OPENED:
        message = "ledger does not start with a portfolio book"
        raise LedgerIntegrityError(message)
    payload = thaw(events[0].payload)
    packet_data = payload["packet"]
    mandate_data = payload["mandate"]
    # Hash the stored JSON, not the model after new default fields are filled.
    # A ledger written before series_kind existed keeps its original book id.
    packet_hash = content_hash(packet_data)
    mandate_hash = content_hash(mandate_data)
    packet = ResearchPacket.model_validate_json(json.dumps(packet_data))
    mandate = SimulationMandate.model_validate_json(json.dumps(mandate_data))
    if payload.get("packet_hash") != packet_hash:
        message = "stored packet hash does not match the stored packet"
        raise LedgerIntegrityError(message)
    if payload.get("mandate_hash") != mandate_hash:
        message = "stored mandate hash does not match the stored mandate"
        raise LedgerIntegrityError(message)
    book_id = deterministic_memory_uuid7(f"manager-book:{packet_hash}")
    if events[0].entity_id != book_id:
        message = "book id does not match the packet hash"
        raise LedgerIntegrityError(message)
    return packet, mandate, packet_hash, mandate_hash, book_id


def extend_packet(
    packet: ResearchPacket,
    evidence: tuple[EvidenceItem, ...],
    benchmark: tuple[BenchmarkPoint, ...],
) -> ResearchPacket:
    """Return a packet with appended inputs. The opening hash is unchanged."""
    if not evidence and not benchmark:
        return packet
    merged = json.loads(packet.model_dump_json())
    if not isinstance(merged, dict):
        message = "packet JSON is not an object"
        raise LedgerIntegrityError(message)
    evidence_rows = merged["evidence"]
    benchmark_rows = merged["benchmark"]
    if not isinstance(evidence_rows, list) or not isinstance(benchmark_rows, list):
        message = "packet JSON is missing evidence or benchmark lists"
        raise LedgerIntegrityError(message)
    evidence_rows.extend(json.loads(item.model_dump_json()) for item in evidence)
    ordered = sorted(
        (*packet.benchmark, *benchmark),
        key=lambda point: point.available_at,
    )
    merged["benchmark"] = [json.loads(point.model_dump_json()) for point in ordered]
    return ResearchPacket.model_validate_json(json.dumps(merged))


def packet_through(
    events: tuple[AuditEvent, ...],
    *,
    until: datetime | None = None,
    inclusive: bool = True,
) -> ResearchPacket:
    """Opening packet plus ingests timestamped at or before ``until``.

    ``inclusive=False`` keeps an ingest that shares ``until`` out of the packet.
    """
    packet, *_rest = load_inputs(events)
    evidence: list[EvidenceItem] = []
    benchmark: list[BenchmarkPoint] = []
    for event in events[1:]:
        if event.event_type != INGEST:
            continue
        if until is not None:
            later = event.timestamp > until if inclusive else event.timestamp >= until
            if later:
                continue
        payload = thaw(event.payload)
        raw_evidence = payload.get("evidence")
        raw_benchmark = payload.get("benchmark")
        if not isinstance(raw_evidence, list) or not isinstance(raw_benchmark, list):
            message = "ingest payload is missing evidence or benchmark lists"
            raise LedgerIntegrityError(message)
        try:
            evidence.extend(
                EvidenceItem.model_validate_json(json.dumps(item))
                for item in raw_evidence
            )
            benchmark.extend(
                BenchmarkPoint.model_validate_json(json.dumps(item))
                for item in raw_benchmark
            )
        except ValidationError as error:
            message = "stored ingest payload is not valid"
            raise LedgerIntegrityError(message) from error
    if not evidence and not benchmark:
        return packet
    try:
        return extend_packet(packet, tuple(evidence), tuple(benchmark))
    except ValidationError as error:
        message = "ingested inputs are not consistent with the opening packet"
        raise LedgerIntegrityError(message) from error


def replay(
    events: tuple[AuditEvent, ...], *, until: datetime | None = None
) -> tuple[
    ResearchPacket, SimulationMandate, str, str, UUID, PortfolioAccountingKernel
]:
    """Rebuild the book from the ledger, optionally ignoring later events."""
    packet, mandate, packet_hash, mandate_hash, book_id = load_inputs(events)
    kernel = build_kernel(packet, packet_hash)
    opening = thaw(events[0].payload)
    if opening.get("snapshot") != take_snapshot(kernel, packet):
        message = "opening snapshot does not match a fresh book"
        raise LedgerIntegrityError(message)
    for event in events[1:]:
        if until is not None and event.timestamp > until:
            continue
        if event.entity_id != book_id:
            message = "ledger event belongs to a different book"
            raise LedgerIntegrityError(message)
        payload = thaw(event.payload)
        if event.event_type == INGEST:
            continue
        if event.event_type == DECISION and payload.get("status") != "accepted":
            continue
        if event.event_type == FILL and payload.get("status") != "filled":
            continue
        if event.event_type in (DECISION, MARK, FILL):
            apply_recorded_effect(kernel, packet, payload)
            continue
        if event.event_type in (
            REFLECTION,
            FEEDBACK,
            PROSPECTIVE_REVIEW,
            PROSPECTIVE_INTENT,
            PROSPECTIVE_SEAL,
            PROSPECTIVE_EXPIRED,
            PROSPECTIVE_CA_STATUS,
            PROSPECTIVE_REQUEST_ATTEMPT,
            PROSPECTIVE_REQUEST_COMPLETION,
        ):
            continue
        message = f"unknown manager event {event.event_type}"
        raise LedgerIntegrityError(message)
    return packet, mandate, packet_hash, mandate_hash, book_id, kernel


def session_for(packet: ResearchPacket, as_of: datetime) -> date | None:
    """Return the declared session date that contains ``as_of``, if any."""
    for session in packet.sessions:
        if session.opened_at <= as_of <= session.closed_at:
            return session.local_date
    return None


def advance_dates(packet: ResearchPacket, current: date, target: date) -> list[str]:
    """Local dates the kernel must enter to reach ``target``."""
    dates: list[str] = []
    for session in packet.sessions:
        if current < session.local_date <= target:
            dates.append(session.local_date.isoformat())
    return dates


def evidence_hash(item: BaseModel) -> str:
    """Consistency hash of one evidence item. This is not origin authentication."""
    return identity_hash(item)
