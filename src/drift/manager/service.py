"""Supervised portfolio cycle: validate, simulate, persist, and review.

Reasoning stays in the proposal. This module does not call a model, a
broker, or a market-data provider.
"""

import os
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from drift.domain.evaluator_portfolio import decimal_context
from drift.domain.events import AuditEvent
from drift.errors import DriftError, DuplicateEventError, LedgerIntegrityError
from drift.evaluator.portfolio import PortfolioAccountingKernel
from drift.ledger.sqlite import SQLiteLedger
from drift.manager.book import (
    DECISION,
    FEEDBACK,
    INGEST,
    MARK,
    OPENED,
    REFLECTION,
    advance_dates,
    append_manager_event,
    apply_fill_json,
    apply_mark_json,
    evidence_hash,
    extend_packet,
    identity_hash,
    model_json,
    packet_through,
    replay,
    security_for,
    session_for,
    simulation_session_key,
    symbol_for,
    take_snapshot,
    thaw,
)
from drift.manager.decide import Decision, RecordedOutcome, decide_proposal
from drift.manager.models import (
    EvidenceItem,
    FeedbackNote,
    IngestBatch,
    InvestmentProposal,
    ReflectionRequest,
    ResearchPacket,
    SimulationMandate,
    money_text,
    parse_money,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.serialization.canonical import canonical_json

REPORT_LIMITATIONS = (
    "configured simulation fees are not a market fee schedule",
    "content hashes check consistency only and do not authenticate origin",
    "fills use the cited observation price and are not market executions",
    "investment results and system costs are separate",
    "missing system costs stay unknown and are not treated as zero",
    "the book is exploratory simulation, not promotion evidence",
    "this cycle does not use M1d observation validation, realized session stamps, "
    "broker routing, or promotion qualification",
    "unmarked holdings are not given a market value",
)

type Json = None | bool | int | str | list["Json"] | dict[str, "Json"]


class ManagerError(DriftError):
    """The cycle refused to open or replay a book."""


class PortfolioManager:
    """One local simulation book stored in the retained SQLite ledger."""

    def __init__(self, ledger: SQLiteLedger) -> None:
        self._ledger = ledger

    @classmethod
    def open(
        cls, path: Path, packet: ResearchPacket, mandate: SimulationMandate
    ) -> tuple[PortfolioManager, Json]:
        """Create a book or reopen the same packet and mandate."""
        _require_mandate_alignment(packet, mandate)
        if path.exists():
            return cls._reopen(path, packet, mandate)

        def build(private: Path) -> None:
            _append_opening(SQLiteLedger(private), packet, mandate)

        if not _publish_new_ledger(path, build):
            return cls._reopen(path, packet, mandate)
        ledger = SQLiteLedger(path, create_schema=False)
        replay(ledger.verified_events())
        return cls(ledger), {"status": "opened"}

    @classmethod
    def _reopen(
        cls, path: Path, packet: ResearchPacket, mandate: SimulationMandate
    ) -> tuple[PortfolioManager, Json]:
        """Reopen an existing ledger without writing into an unrelated file."""
        ledger = _open_verified(path)
        events = ledger.verified_events()
        if not events:
            message = "ledger has no portfolio book"
            raise ManagerError(message)
        stored_packet, stored_mandate, *_rest = replay(events)
        if identity_hash(stored_packet) != identity_hash(packet):
            message = "ledger packet does not match the supplied packet"
            raise ManagerError(message)
        if identity_hash(stored_mandate) != identity_hash(mandate):
            message = "ledger mandate does not match the supplied mandate"
            raise ManagerError(message)
        return cls(ledger), {"status": "already_open"}

    @classmethod
    def recover(cls, path: Path) -> PortfolioManager:
        """Reload a book from its ledger and refuse a broken chain."""
        ledger = _open_verified(path)
        try:
            replay(ledger.verified_events())
        except LedgerIntegrityError as error:
            raise ManagerError(str(error)) from error
        return cls(ledger)

    def propose(self, proposal: InvestmentProposal) -> Json:
        """Validate one proposal and simulate it only when it is eligible."""
        events = self._ledger.verified_events()
        packet, mandate, _packet_hash, _mandate_hash, book_id, kernel = replay(events)
        packet = packet_through(events, until=proposal.as_of)
        dedup = f"proposal:{proposal.proposal_id}"
        existing = _find(events, dedup)
        if existing is not None:
            return _duplicate_view(events, existing, proposal)
        clock = _kernel_time(events)
        if proposal.as_of < clock:
            return _result(
                status="rejected",
                reasons=(
                    "decision_before_recorded_state: "
                    "as_of is before the latest book time",
                ),
                proposal_id=str(proposal.proposal_id),
                snapshot=_book_at(events, proposal.as_of),
                fill=None,
                inference=proposal.inference,
                model_identity=proposal.model_identity,
            )
        target = session_for(packet, proposal.as_of)
        current = kernel.state.session_key.local_date
        session_ok = target is not None and target >= current
        decision = decide_proposal(
            proposal=proposal,
            packet=packet,
            mandate=mandate,
            cash=kernel.state.cash_balance,
            cost_basis_by_symbol=_costs(kernel, packet),
            quantity_by_symbol=_quantities(kernel, packet),
            outcomes=_outcomes(events, proposal.as_of),
            current_session=clock,
            session_date_ok=session_ok,
            session_in_future=target is None and proposal.as_of > clock,
        )
        if _indeterminate(kernel):
            decision = Decision(
                status="rejected",
                reasons=decision.reasons
                + ("unsafe_position_limit: a holding cost basis is indeterminate",),
                fill_price=None,
                price_evidence_id=None,
            )
        advances: list[str] = []
        fill: Json = None
        if decision.status == "accepted":
            if target is None:
                message = "accepted proposal has no session"
                raise ManagerError(message)
            advances = advance_dates(packet, current, target)
            for day in advances:
                kernel.advance_session(simulation_session_key(date.fromisoformat(day)))
            if proposal.action != "hold":
                if decision.fill_price is None or decision.price_evidence_id is None:
                    message = "accepted trade is missing a fill price"
                    raise ManagerError(message)
                fill = {
                    "assumptions": {
                        "fee_source": "simulation_mandate.fill_fee",
                        "not_a_market_execution": True,
                        "price_source": "cited_observation_price",
                        "whole_shares_only": True,
                    },
                    "fill_price": decision.fill_price,
                    "price_evidence_id": decision.price_evidence_id,
                    "quantity": proposal.quantity,
                    "security_id": str(security_for(packet, proposal.symbol)),
                    "side": proposal.action,
                    "transaction_costs": mandate.fill_fee,
                }
                apply_fill_json(kernel, fill)
        payload: dict[str, Json] = {
            "advances": cast(list[Json], advances),
            "fill": fill,
            "inference": proposal.inference,
            "model_identity": proposal.model_identity,
            "outcome_id": f"outcome:{proposal.proposal_id}",
            "proposal": model_json(proposal),
            "proposal_hash": identity_hash(proposal),
            "reasons": cast(list[Json], list(decision.reasons)),
            "snapshot": take_snapshot(kernel, packet),
            "status": decision.status,
            "system_cost": (
                None
                if proposal.system_cost is None
                else model_json(proposal.system_cost)
            ),
        }
        try:
            append_manager_event(
                self._ledger,
                book_id=book_id,
                event_type=DECISION,
                dedup_key=dedup,
                timestamp=proposal.as_of,
                payload=payload,
                expected_previous_hash=_head(events),
            )
        except DuplicateEventError as error:
            message = "proposal id was already recorded"
            raise ManagerError(message) from error
        except LedgerIntegrityError as error:
            if "ledger head changed" in str(error):
                message = "the ledger changed before this proposal was recorded"
                raise ManagerError(message) from error
            raise
        appended = self._ledger.verified_events()
        appended_id = deterministic_memory_uuid7(f"manager:{dedup}")
        prefix = _events_through(appended, appended_id)
        checked, _mandate, *_ignored, checked_kernel = replay(prefix)
        if take_snapshot(checked_kernel, checked) != payload["snapshot"]:
            message = "recorded decision does not replay"
            raise LedgerIntegrityError(message)
        return _result(
            status=decision.status,
            reasons=decision.reasons,
            proposal_id=str(proposal.proposal_id),
            snapshot=_public_book(checked_kernel, checked, proposal.as_of),
            fill=fill,
            inference=proposal.inference,
            model_identity=proposal.model_identity,
        )

    def mark(self, as_of: datetime) -> Json:
        """Mark held names at cited close observations. Partial marks are refused."""
        events = self._ledger.verified_events()
        packet, mandate, _ph, _mh, book_id, kernel = replay(events)
        packet = packet_through(events, until=as_of)
        clock = _kernel_time(events)
        target = session_for(packet, as_of)
        current = kernel.state.session_key.local_date
        if target is None or target < current or as_of < clock:
            return _result(
                status="rejected",
                reasons=(
                    "decision_outside_session: mark time is outside the "
                    "current simulation book",
                ),
                proposal_id=None,
                snapshot=_book_at(events, as_of),
                fill=None,
                inference=None,
                model_identity=None,
            )
        dedup = f"mark:{target.isoformat()}:{_latest_fill_id(events)}"
        if _find(events, dedup) is not None:
            return _result(
                status="duplicate",
                reasons=("duplicate_mark: this session already has a mark",),
                proposal_id=None,
                snapshot=_book_at(events, as_of),
                fill=None,
                inference=None,
                model_identity=None,
            )
        advances = advance_dates(packet, current, target)
        session_open, session_close = _session_bounds(packet, target)
        prices: list[Json] = []
        reasons: list[str] = []
        for holding in kernel.state.holdings:
            symbol = symbol_for(packet, holding.security_id)
            chosen = _close_observation(
                packet,
                mandate,
                symbol,
                as_of=as_of,
                session_open=session_open,
                session_close=session_close,
            )
            if isinstance(chosen, str):
                reasons.append(chosen)
                continue
            prices.append(
                {
                    "close_price": chosen.price,
                    "evidence_hash": evidence_hash(chosen),
                    "evidence_id": chosen.evidence_id,
                    "security_id": str(holding.security_id),
                }
            )
        if reasons or (
            kernel.state.holdings and len(prices) != len(kernel.state.holdings)
        ):
            return _result(
                status="rejected",
                reasons=tuple(reasons)
                or ("unsupported_evidence: a held name has no close observation",),
                proposal_id=None,
                snapshot=_public_book(kernel, packet, as_of),
                fill=None,
                inference=None,
                model_identity=None,
            )
        if not prices:
            return _result(
                status="rejected",
                reasons=("unsupported_evidence: there is no holding to mark",),
                proposal_id=None,
                snapshot=_public_book(kernel, packet, as_of),
                fill=None,
                inference=None,
                model_identity=None,
            )
        for day in advances:
            kernel.advance_session(simulation_session_key(date.fromisoformat(day)))
        apply_mark_json(kernel, cast(Json, prices))
        payload: dict[str, Json] = {
            "advances": cast(list[Json], advances),
            "fill": None,
            "mark": cast(Json, prices),
            "snapshot": take_snapshot(kernel, packet),
        }
        append_manager_event(
            self._ledger,
            book_id=book_id,
            event_type=MARK,
            dedup_key=dedup,
            timestamp=as_of,
            payload=payload,
            expected_previous_hash=_head(events),
        )
        replay(self._ledger.verified_events())
        return _result(
            status="marked",
            reasons=("marked: holdings are marked from cited close observations",),
            proposal_id=None,
            snapshot=_public_book(kernel, packet, as_of),
            fill=None,
            inference=None,
            model_identity=None,
        )

    def context(self, as_of: datetime) -> Json:
        """Point-in-time inputs, decisions, and outcomes for a later review."""
        events = self._ledger.verified_events()
        packet, _mandate, *_rest, kernel = replay(events, until=as_of)
        packet = packet_through(events, until=as_of)
        decisions: list[Json] = []
        feedback: list[Json] = []
        reflections: list[Json] = []
        for event in events:
            if event.timestamp > as_of:
                continue
            payload = thaw(event.payload)
            if event.event_type == DECISION:
                decisions.append(_decision_context(payload))
            elif event.event_type == FEEDBACK:
                note = payload.get("feedback")
                if note is not None:
                    feedback.append(note)
            elif event.event_type == REFLECTION:
                note = payload.get("reflection")
                if note is not None:
                    reflections.append(note)
        evidence: list[Json] = []
        for item in packet.evidence:
            if item.available_at <= as_of:
                evidence.append(_evidence_context(item))
        body: dict[str, Json] = {
            "as_of": as_of.isoformat(),
            "book": _public_book(kernel, packet, as_of),
            "decisions": decisions,
            "evidence": evidence,
            "feedback": feedback,
            "limitations": list(REPORT_LIMITATIONS),
            "reflections": reflections,
            "untrusted_text": True,
        }
        return body

    def report(self, as_of: datetime) -> Json:
        """Performance, risk inputs, benchmark, and system costs, kept apart."""
        events = self._ledger.verified_events()
        packet, _mandate, *_rest, kernel = replay(events, until=as_of)
        packet = packet_through(events, until=as_of)
        valuation, market, unrealized, nav, valuation_reason = _valuation(kernel)
        if session_for(packet, as_of) != kernel.state.session_key.local_date:
            valuation = "unavailable"
            market = None
            unrealized = None
            nav = None
            valuation_reason = (
                "the requested time is outside the book's current session, "
                "so an earlier mark is not used"
            )
        body: dict[str, Json] = {
            "benchmark_relative": _benchmark(packet, as_of, nav),
            "book_session": kernel.state.session_key.local_date.isoformat(),
            "cash": money_text(kernel.state.cash_balance),
            "cumulative_simulation_transaction_costs": money_text(
                kernel.state.cumulative_transaction_costs
            ),
            "holdings_market_value": market,
            "lane": "exploratory",
            "limitations": list(REPORT_LIMITATIONS),
            "net_asset_value": nav,
            "not_a_broker_connection": True,
            "not_promotion_evidence": True,
            "positions": _position_rows(kernel, packet),
            "realized_gross_pnl": money_text(kernel.state.realized_gross_pnl),
            "realized_net_pnl": money_text(kernel.state.realized_net_pnl),
            "requested_as_of": as_of.isoformat(),
            "system_costs": _system_costs(events, as_of),
            "unrealized_pnl": unrealized,
            "valuation": valuation,
            "valuation_reason": valuation_reason,
        }
        return body

    def reflect(self, request: ReflectionRequest) -> Json:
        """Record an evidence-based reflection. It does not trade or retune."""
        events = self._ledger.verified_events()
        packet, mandate, _ph, _mh, book_id, kernel = replay(events)
        packet = packet_through(events, until=request.as_of)
        if request.as_of < _kernel_time(events):
            return _note_result(
                "rejected",
                ("decision_before_recorded_state: reflection is before the book",),
            )
        existing = _find(events, f"reflection:{request.reflection_id}")
        if existing is not None:
            return _note_result(
                "duplicate",
                ("duplicate_reflection: this reflection was already recorded",),
            )
        decision_event = _decision_event(events, request.proposal_id)
        if decision_event is None:
            return _note_result(
                "rejected",
                ("missing_evidence: the proposal has not been recorded",),
            )
        payload = thaw(decision_event.payload)
        proposal_data = payload["proposal"]
        proposal = InvestmentProposal.model_validate_json(
            canonical_json(proposal_data).decode("utf-8")
        )
        observation = _item(packet, request.observation_evidence_id)
        refusal = _observation_refusal(observation, proposal, mandate, request.as_of)
        if refusal is not None:
            return _note_result("rejected", (refusal,))
        assert observation is not None
        assert observation.price is not None
        price = parse_money(observation.price)
        evaluations: list[Json] = []
        for condition in proposal.exit_conditions:
            if condition.kind == "narrative":
                result = "not_evaluable"
            else:
                assert condition.threshold is not None
                threshold = parse_money(condition.threshold)
                if condition.kind == "price_below":
                    triggered = price < threshold
                else:
                    triggered = price > threshold
                result = "triggered" if triggered else "not_triggered"
            evaluations.append({"kind": condition.kind, "result": result})
        before = take_snapshot(kernel, packet)
        reflection: dict[str, Json] = {
            "as_of": request.as_of.isoformat(),
            "evaluations": evaluations,
            "note": request.note,
            "observation_evidence_id": request.observation_evidence_id,
            "positions_unchanged": True,
            "proposal_id": str(request.proposal_id),
            "reflection_id": str(request.reflection_id),
            "untrusted_text": True,
        }
        append_manager_event(
            self._ledger,
            book_id=book_id,
            event_type=REFLECTION,
            dedup_key=f"reflection:{request.reflection_id}",
            timestamp=request.as_of,
            payload={"reflection": reflection},
            expected_previous_hash=_head(events),
        )
        _checked, *_rest, checked_kernel = replay(self._ledger.verified_events())
        if take_snapshot(checked_kernel, packet) != before:
            message = "reflection changed the book"
            raise LedgerIntegrityError(message)
        return reflection

    def feedback(self, note: FeedbackNote) -> Json:
        """Store supervising-user feedback without changing the book."""
        events = self._ledger.verified_events()
        packet, _mandate, _ph, _mh, book_id, kernel = replay(events)
        if note.as_of < _kernel_time(events):
            return _note_result(
                "rejected",
                ("decision_before_recorded_state: feedback is before the book",),
            )
        if _find(events, f"feedback:{note.feedback_id}") is not None:
            return _note_result(
                "duplicate",
                ("duplicate_feedback: this feedback was already recorded",),
            )
        if _decision_event(events, note.proposal_id) is None:
            return _note_result(
                "rejected",
                ("missing_evidence: the proposal has not been recorded",),
            )
        before = take_snapshot(kernel, packet)
        body: dict[str, Json] = {
            "as_of": note.as_of.isoformat(),
            "feedback_id": str(note.feedback_id),
            "note": note.note,
            "proposal_id": str(note.proposal_id),
            "untrusted_text": True,
        }
        append_manager_event(
            self._ledger,
            book_id=book_id,
            event_type=FEEDBACK,
            dedup_key=f"feedback:{note.feedback_id}",
            timestamp=note.as_of,
            payload={"feedback": body},
            expected_previous_hash=_head(events),
        )
        _checked, *_rest, checked_kernel = replay(self._ledger.verified_events())
        if take_snapshot(checked_kernel, packet) != before:
            message = "feedback changed the book"
            raise LedgerIntegrityError(message)
        return body

    def ingest(self, batch: IngestBatch) -> Json:
        """Append inputs that stay invisible before their availability time."""
        events = self._ledger.verified_events()
        _opening, _mandate, _ph, _mh, book_id, kernel = replay(events)
        latest = max(event.timestamp for event in events)
        when = batch.available_at
        dedup = f"ingest:{identity_hash(batch)}"
        if _find(events, dedup) is not None:
            return {
                "reasons": ["duplicate_ingest: this batch was already recorded"],
                "status": "duplicate",
            }
        if _ingest_rewrites_history(events, when, latest):
            return {
                "reasons": [
                    "decision_before_recorded_state: "
                    "ingest is not later than the latest ledger event"
                ],
                "status": "rejected",
            }
        visible = packet_through(events)
        try:
            extend_packet(visible, batch.evidence, batch.benchmark)
        except ValidationError as error:
            message = "ingest is not consistent with the book"
            raise ManagerError(message) from error
        before = take_snapshot(kernel, visible)
        payload: dict[str, Json] = {
            "benchmark": [model_json(item) for item in batch.benchmark],
            "evidence": [model_json(item) for item in batch.evidence],
        }
        append_manager_event(
            self._ledger,
            book_id=book_id,
            event_type=INGEST,
            dedup_key=dedup,
            timestamp=when,
            payload=payload,
            expected_previous_hash=_head(events),
        )
        appended = self._ledger.verified_events()
        ingest_id = deterministic_memory_uuid7(f"manager:{dedup}")
        prefix = _events_through(appended, ingest_id)
        replayed_packet, *_rest, replayed_kernel = replay(prefix)
        if take_snapshot(replayed_kernel, replayed_packet) != before:
            message = "ingest changed the book"
            raise LedgerIntegrityError(message)
        checked = packet_through(appended, until=when)
        earlier = packet_through(appended, until=when, inclusive=False)
        new_ids = {item.evidence_id for item in batch.evidence}
        checked_ids = {item.evidence_id for item in checked.evidence}
        earlier_ids = {item.evidence_id for item in earlier.evidence}
        if not new_ids <= checked_ids or new_ids & earlier_ids:
            message = "ingested evidence leaked across its availability time"
            raise LedgerIntegrityError(message)
        new_times = {point.available_at for point in batch.benchmark}
        checked_times = {point.available_at for point in checked.benchmark}
        earlier_times = {point.available_at for point in earlier.benchmark}
        if not new_times <= checked_times or new_times & earlier_times:
            message = "ingested benchmark leaked across its availability time"
            raise LedgerIntegrityError(message)
        return {
            "available_at": when.isoformat(),
            "benchmark_count": len(batch.benchmark),
            "evidence_ids": [item.evidence_id for item in batch.evidence],
            "status": "ingested",
        }


def _fresh(
    packet: ResearchPacket, mandate: SimulationMandate
) -> tuple[
    ResearchPacket,
    SimulationMandate,
    str,
    str,
    UUID,
    PortfolioAccountingKernel,
]:
    from drift.manager.book import build_kernel

    packet_hash = identity_hash(packet)
    mandate_hash = identity_hash(mandate)
    book_id = deterministic_memory_uuid7(f"manager-book:{packet_hash}")
    return (
        packet,
        mandate,
        packet_hash,
        mandate_hash,
        book_id,
        build_kernel(packet, packet_hash),
    )


def _require_mandate_alignment(
    packet: ResearchPacket, mandate: SimulationMandate
) -> None:
    known = {item.symbol for item in packet.instruments}
    extra = sorted(set(mandate.allowed_symbols) - known)
    if extra:
        message = f"mandate allows symbols that are not in the packet: {extra}"
        raise ManagerError(message)


def _append_opening(
    ledger: SQLiteLedger, packet: ResearchPacket, mandate: SimulationMandate
) -> None:
    """Write the opening event into a ledger that does not yet have one."""
    packet_hash = identity_hash(packet)
    book_id = deterministic_memory_uuid7(f"manager-book:{packet_hash}")
    _packet, _mandate, _ph, _mh, _bid, kernel = _fresh(packet, mandate)
    payload: dict[str, Json] = {
        "mandate": model_json(mandate),
        "mandate_hash": identity_hash(mandate),
        "packet": model_json(packet),
        "packet_hash": packet_hash,
        "snapshot": take_snapshot(kernel, packet),
    }
    append_manager_event(
        ledger,
        book_id=book_id,
        event_type=OPENED,
        dedup_key="book-opened",
        timestamp=packet.sessions[0].opened_at,
        payload=payload,
        expected_previous_hash=None,
    )
    replay(ledger.verified_events())


def _publish_new_ledger(path: Path, build: Callable[[Path], None]) -> bool:
    """Initialize a ledger privately and link it into place if path is absent."""
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    os.close(descriptor)
    private = Path(name)
    try:
        build(private)
        try:
            os.link(private, path)
        except FileExistsError:
            return False
        return True
    finally:
        private.unlink(missing_ok=True)


def _open_verified(path: Path) -> SQLiteLedger:
    """Open an existing ledger without installing schema into another database."""
    if not path.is_file():
        message = f"no portfolio ledger at {path}"
        raise ManagerError(message)
    probe = SQLiteLedger.open_existing(path)
    try:
        probe.verify_chain()
    except LedgerIntegrityError as error:
        raise ManagerError(str(error)) from error
    return SQLiteLedger(path, create_schema=False)


def _ingest_rewrites_history(
    events: tuple[AuditEvent, ...], when: datetime, latest: datetime
) -> bool:
    """Reject an ingest that would appear in an already recorded non-ingest."""
    if when < latest:
        return True
    if when > latest:
        return False
    return any(
        event.timestamp == when and event.event_type != INGEST for event in events
    )


def _kernel_time(events: tuple[AuditEvent, ...]) -> datetime:
    """Latest time that changed the book. Refusals do not move it."""
    latest = events[0].timestamp
    for event in events:
        moves = event.event_type in (OPENED, MARK)
        if event.event_type == DECISION:
            moves = thaw(event.payload).get("status") == "accepted"
        if moves and event.timestamp > latest:
            latest = event.timestamp
    return latest


def _head(events: tuple[AuditEvent, ...]) -> str:
    return events[-1].event_hash


def _latest_fill_id(events: tuple[AuditEvent, ...]) -> str:
    """Identity of the latest accepted fill. A restored lot is a new fill."""
    anchor = str(events[0].event_id)
    for event in events:
        if event.event_type != DECISION:
            continue
        payload = thaw(event.payload)
        if payload.get("status") == "accepted" and payload.get("fill") is not None:
            anchor = str(event.event_id)
    return anchor


def _events_through(
    events: tuple[AuditEvent, ...], event_id: object
) -> tuple[AuditEvent, ...]:
    """Ledger prefix ending at one appended event, ignoring later commits."""
    prefix: list[AuditEvent] = []
    for event in events:
        prefix.append(event)
        if event.event_id == event_id:
            return tuple(prefix)
    message = "appended event is missing from the ledger"
    raise LedgerIntegrityError(message)


def _snapshot_through(
    events: tuple[AuditEvent, ...], event_id: object, as_of: datetime
) -> Json:
    """Caller-facing book for one committed event, excluding later commits."""
    prefix = _events_through(events, event_id)
    packet, _mandate, *_rest, kernel = replay(prefix)
    return _public_book(kernel, packet, as_of)


def _book_at(events: tuple[AuditEvent, ...], as_of: datetime) -> Json:
    """Caller-facing book replayed only through the requested time."""
    packet, _mandate, *_rest, kernel = replay(events, until=as_of)
    return _public_book(kernel, packet, as_of)


def _public_book(
    kernel: PortfolioAccountingKernel, packet: ResearchPacket, as_of: datetime
) -> Json:
    """Caller-facing book. Unmarked or stale marks are not reported as value."""
    raw = take_snapshot(kernel, packet)
    if not isinstance(raw, dict):
        message = "book snapshot is not an object"
        raise ManagerError(message)
    valuation, market, _unrealized, nav, reason = _valuation(kernel)
    if session_for(packet, as_of) != kernel.state.session_key.local_date:
        valuation = "unavailable"
        market = None
        nav = None
        reason = (
            "the requested time is outside the book's current session, "
            "so an earlier mark is not used"
        )
    return {
        "cash": raw["cash"],
        "cumulative_transaction_costs": raw["cumulative_transaction_costs"],
        "holdings": raw["holdings"],
        "holdings_market_value": market,
        "marked": valuation == "marked",
        "net_asset_value": nav,
        "realized_gross_pnl": raw["realized_gross_pnl"],
        "realized_net_pnl": raw["realized_net_pnl"],
        "session": raw["session"],
        "valuation": valuation,
        "valuation_reason": reason,
    }


def _find(events: tuple[AuditEvent, ...], dedup_key: str) -> AuditEvent | None:
    for event in events:
        if event.deduplication_key == dedup_key:
            return event
    return None


def _decision_event(
    events: tuple[AuditEvent, ...], proposal_id: UUID
) -> AuditEvent | None:
    return _find(events, f"proposal:{proposal_id}")


def _costs(
    kernel: PortfolioAccountingKernel, packet: ResearchPacket
) -> dict[str, Decimal]:
    costs: dict[str, Decimal] = {}
    for holding in kernel.state.holdings:
        if holding.cost_basis is None:
            continue
        costs[symbol_for(packet, holding.security_id)] = holding.cost_basis
    return costs


def _quantities(
    kernel: PortfolioAccountingKernel, packet: ResearchPacket
) -> dict[str, int]:
    return {
        symbol_for(packet, holding.security_id): holding.quantity
        for holding in kernel.state.holdings
    }


def _indeterminate(kernel: PortfolioAccountingKernel) -> bool:
    return any(holding.cost_basis is None for holding in kernel.state.holdings)


def _outcomes(
    events: tuple[AuditEvent, ...], as_of: datetime
) -> dict[str, RecordedOutcome]:
    found: dict[str, RecordedOutcome] = {}
    for event in events:
        if event.event_type != DECISION or event.timestamp > as_of:
            continue
        payload = thaw(event.payload)
        outcome_id = payload.get("outcome_id")
        proposal_data = payload.get("proposal")
        if not isinstance(outcome_id, str) or not isinstance(proposal_data, dict):
            continue
        symbol = proposal_data.get("symbol")
        recorded_as_of = proposal_data.get("as_of")
        if not isinstance(symbol, str) or not isinstance(recorded_as_of, str):
            continue
        found[outcome_id] = RecordedOutcome(
            outcome_id=outcome_id,
            symbol=symbol,
            available_at=datetime.fromisoformat(recorded_as_of),
        )
    return found


def _duplicate_view(
    events: tuple[AuditEvent, ...],
    event: AuditEvent,
    proposal: InvestmentProposal,
) -> Json:
    payload = thaw(event.payload)
    same = payload.get("proposal_hash") == identity_hash(proposal)
    status = "duplicate" if same else "duplicate_conflict"
    reason = (
        "duplicate_proposal: the identical proposal was already recorded"
        if same
        else "duplicate_proposal: this proposal id was recorded with different contents"
    )
    original = payload.get("status")
    original_status = original if isinstance(original, str) else "unknown"
    return _result(
        status=status,
        reasons=(reason, f"original_status: {original_status}"),
        proposal_id=str(proposal.proposal_id),
        snapshot=_snapshot_through(events, event.event_id, proposal.as_of),
        fill=None,
        inference=proposal.inference,
        model_identity=proposal.model_identity,
    )


def _result(
    *,
    status: str,
    reasons: tuple[str, ...],
    proposal_id: str | None,
    snapshot: Json,
    fill: Json,
    inference: str | None,
    model_identity: str | None,
) -> Json:
    return {
        "fill": fill,
        "inference": inference,
        "model_identity": model_identity,
        "proposal_id": proposal_id,
        "reasons": list(reasons),
        "snapshot": snapshot,
        "status": status,
    }


def _note_result(status: str, reasons: tuple[str, ...]) -> Json:
    return {"reasons": list(reasons), "status": status}


def _session_bounds(packet: ResearchPacket, day: date) -> tuple[datetime, datetime]:
    for session in packet.sessions:
        if session.local_date == day:
            return session.opened_at, session.closed_at
    message = "session is not in the packet"
    raise ManagerError(message)


def _close_observation(
    packet: ResearchPacket,
    mandate: SimulationMandate,
    symbol: str,
    *,
    as_of: datetime,
    session_open: datetime,
    session_close: datetime,
) -> EvidenceItem | str:
    from datetime import timedelta

    matches = [
        item
        for item in packet.evidence
        if item.kind == "observation"
        and item.symbol == symbol
        and item.price_role == "close"
        and item.price is not None
        and session_open <= item.observed_at <= session_close
        and item.available_at <= as_of
    ]
    fresh = [
        item
        for item in matches
        if as_of - item.available_at <= timedelta(hours=mandate.max_evidence_age_hours)
    ]
    if not fresh:
        return (
            f"unsupported_evidence: {symbol} has no close observation "
            "in the mark session"
        )
    prices = {item.price for item in fresh}
    if len(prices) != 1:
        return f"unsupported_evidence: {symbol} close observations disagree"
    return sorted(fresh, key=lambda item: (item.available_at, item.evidence_id))[-1]


def _item(packet: ResearchPacket, evidence_id: str) -> EvidenceItem | None:
    for item in packet.evidence:
        if item.evidence_id == evidence_id:
            return item
    return None


def _observation_refusal(
    observation: EvidenceItem | None,
    proposal: InvestmentProposal,
    mandate: SimulationMandate,
    as_of: datetime,
) -> str | None:
    from datetime import timedelta

    if observation is None or observation.price is None:
        return "missing_evidence: the reflection observation does not resolve"
    if observation.symbol != proposal.symbol:
        return "unsupported_evidence: the observation is for a different symbol"
    if observation.available_at > as_of or observation.observed_at > as_of:
        return (
            "evidence_not_yet_available: the observation is later than the reflection"
        )
    if as_of - observation.available_at > timedelta(
        hours=mandate.max_evidence_age_hours
    ):
        return "stale_evidence: the observation is older than the configured age"
    return None


def _evidence_context(item: EvidenceItem) -> Json:
    return {
        "available_at": item.available_at.isoformat(),
        "evidence_id": item.evidence_id,
        "integrity_hash": evidence_hash(item),
        "kind": item.kind,
        "limitations": list(item.limitations),
        "price": item.price,
        "price_role": item.price_role,
        "source_label": item.source_label,
        "summary": item.summary,
        "symbol": item.symbol,
        "untrusted_text": True,
    }


def _decision_context(payload: dict[str, Json]) -> Json:
    proposal = payload.get("proposal")
    thesis = None
    symbol = None
    action = None
    if isinstance(proposal, dict):
        thesis = proposal.get("thesis")
        symbol = proposal.get("symbol")
        action = proposal.get("action")
    return {
        "action": action if isinstance(action, str) else None,
        "fill": payload.get("fill"),
        "inference": payload.get("inference"),
        "model_identity": payload.get("model_identity"),
        "outcome_id": payload.get("outcome_id"),
        "reasons": payload.get("reasons"),
        "status": payload.get("status"),
        "symbol": symbol if isinstance(symbol, str) else None,
        "thesis": thesis if isinstance(thesis, str) else None,
        "untrusted_text": True,
    }


def _position_rows(
    kernel: PortfolioAccountingKernel, packet: ResearchPacket
) -> list[Json]:
    rows: list[Json] = []
    for holding in kernel.state.holdings:
        cost = None if holding.cost_basis is None else money_text(holding.cost_basis)
        rows.append(
            {
                "cost_basis": cost,
                "quantity": holding.quantity,
                "symbol": symbol_for(packet, holding.security_id),
            }
        )
    return rows


def _valuation(
    kernel: PortfolioAccountingKernel,
) -> tuple[str, str | None, str | None, str | None, str]:
    state = kernel.state
    if not state.holdings:
        return (
            "cash_only",
            "0",
            "0",
            money_text(state.cash_balance),
            "no holdings, so net asset value is the cash balance",
        )
    if not state.is_marked or any(
        holding.cost_basis is None for holding in state.holdings
    ):
        return (
            "unavailable",
            None,
            None,
            None,
            "a held position has no mark or no known cost basis, so market "
            "value is not reported",
        )
    cost = sum(
        (
            holding.cost_basis
            for holding in state.holdings
            if holding.cost_basis is not None
        ),
        Decimal("0"),
    )
    unrealized = state.holdings_market_value - cost
    with decimal_context():
        recomputed = state.holdings_market_value - cost
    if Fraction(recomputed) != Fraction(state.holdings_market_value) - Fraction(cost):
        return (
            "unavailable",
            None,
            None,
            None,
            "unrealized result is not exact in the portfolio decimal context",
        )
    del unrealized
    return (
        "marked",
        money_text(state.holdings_market_value),
        money_text(recomputed),
        money_text(state.net_asset_value),
        "market value uses the recorded exploratory close mark",
    )


def _exact_ratio(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    with decimal_context():
        quotient = numerator / denominator
    if Fraction(quotient) != Fraction(numerator) / Fraction(denominator):
        return None
    return format(quotient, "f")


def _benchmark(packet: ResearchPacket, as_of: datetime, nav: str | None) -> Json:
    if not packet.benchmark:
        return {
            "portfolio_change": None,
            "reason": "no benchmark series was supplied",
            "status": "unavailable",
        }
    opening = packet.sessions[0].opened_at
    start_points = [
        point for point in packet.benchmark if point.available_at <= opening
    ]
    end_points = [point for point in packet.benchmark if point.available_at <= as_of]
    if not start_points or not end_points:
        return {
            "portfolio_change": None,
            "reason": "the supplied benchmark does not cover the reported window",
            "status": "unavailable",
        }
    start = start_points[-1]
    end = end_points[-1]
    series_change = _exact_ratio(
        parse_money(end.level) - parse_money(start.level), parse_money(start.level)
    )
    portfolio_change = None
    if nav is not None:
        initial = parse_money(packet.portfolio_context.cash)
        portfolio_change = _exact_ratio(parse_money(nav) - initial, initial)
    status = (
        "available"
        if series_change is not None and portfolio_change is not None
        else ("series_only" if series_change is not None else "unavailable")
    )
    return {
        "end_level": end.level,
        "limitations": list(end.limitations),
        "portfolio_change": portfolio_change,
        "reason": "supplied series comparison, not an index calculation or an edge",
        "series_change": series_change,
        "start_level": start.level,
        "status": status,
    }


def _system_costs(events: tuple[AuditEvent, ...], as_of: datetime) -> Json:
    entries: list[Json] = []
    currencies: set[str] = set()
    missing = False
    total = Decimal("0")
    for event in events:
        if event.event_type != DECISION or event.timestamp > as_of:
            continue
        payload = thaw(event.payload)
        cost = payload.get("system_cost")
        proposal_id = payload.get("outcome_id")
        inference = payload.get("inference")
        model_identity = payload.get("model_identity")
        if not isinstance(cost, dict):
            missing = True
            continue
        amount = cost.get("amount")
        currency = cost.get("currency")
        description = cost.get("description")
        if not isinstance(amount, str) or not isinstance(currency, str):
            missing = True
            continue
        currencies.add(currency)
        total += parse_money(amount)
        entries.append(
            {
                "amount": amount,
                "currency": currency,
                "description": description if isinstance(description, str) else "",
                "inference": inference if isinstance(inference, str) else None,
                "model_identity": (
                    model_identity if isinstance(model_identity, str) else None
                ),
                "proposal_id": proposal_id if isinstance(proposal_id, str) else None,
            }
        )
    if not entries and missing:
        return {
            "amount": None,
            "entries": [],
            "reason": "no decision attested a system cost; missing cost is not zero",
            "status": "unknown",
        }
    if not entries:
        return {
            "amount": None,
            "entries": [],
            "reason": "no decision has been recorded",
            "status": "unknown",
        }
    if missing or len(currencies) != 1:
        return {
            "amount": None,
            "entries": entries,
            "reason": (
                "at least one decision did not attest a system cost, or currencies "
                "differ; missing cost is not zero"
            ),
            "status": "unknown",
        }
    return {
        "amount": money_text(total),
        "currency": next(iter(currencies)),
        "entries": entries,
        "reason": "sum of caller-attested system costs only",
        "status": "attested",
    }
