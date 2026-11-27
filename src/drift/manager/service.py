"""Supervised portfolio cycle: validate, simulate, persist, and review.

Reasoning stays in the proposal. This module does not call a model, a
broker, or a market-data provider.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from functools import wraps
from pathlib import Path
from typing import Concatenate, Literal, cast
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
    FILL,
    INGEST,
    MARK,
    OPENED,
    PROSPECTIVE_CA_STATUS,
    PROSPECTIVE_EXPIRED,
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
from drift.manager.corporate_actions import split_date
from drift.manager.decide import (
    Decision,
    RecordedOutcome,
    citation_time,
    decide_proposal,
    fill_limit_reasons,
)
from drift.manager.models import (
    PROSPECTIVE_READINESS,
    PROSPECTIVE_SEAL_REQUIRED,
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
    "cited fills use the cited observation price and are not market executions",
    "post-decision fills use a later trade observation and are not market executions",
    "investment results and system costs are separate",
    "missing system costs stay unknown and are not treated as zero",
    "the book is exploratory simulation, not promotion evidence",
    "this cycle does not use M1d observation validation, realized session stamps, "
    "broker routing, or promotion qualification",
    "unmarked holdings are not given a market value",
)

type Json = None | bool | int | str | list["Json"] | dict[str, "Json"]

# Return ratios are not cash. Exact values stay exact. Ordinary index
# returns do not terminate in the 34-digit portfolio context, so those
# are half-even at 12 decimal places and labeled inexact.
RETURN_RATIO_PLACES = 12
RETURN_RATIO_PRECISION = (
    "exact ratios stay exact in the 34-digit half-even portfolio context; "
    "every other finite ratio is half-even at 12 decimal places and is not cash"
)
_SERIES_LABELS = {
    "unspecified": ("caller did not label the series; it is not S&P 500 total return"),
    "sp500_total_return": "S&P 500 total return levels supplied by the caller",
    "price_only_substitute": "price-only substitute, not S&P 500 total return",
}


class ManagerError(DriftError):
    """The cycle refused to open or replay a book."""


def _pilot_book(mandate: SimulationMandate) -> bool:
    return any(
        item in mandate.acknowledgements
        for item in (PROSPECTIVE_SEAL_REQUIRED, PROSPECTIVE_READINESS)
    )


def _require_window_binding(packet: ResearchPacket, mandate: SimulationMandate) -> None:
    if PROSPECTIVE_SEAL_REQUIRED not in mandate.acknowledgements:
        return
    from drift.prospective.window import active_window

    markers = [
        item
        for item in packet.limitations
        if item.startswith("prospective-window-sha256:")
    ]
    configured = active_window()
    if not markers and configured is None:
        return  # Existing v0.2 pilot books retain their original calendar.
    if configured is None or markers != [
        f"prospective-window-sha256:{configured.binding}"
    ]:
        raise ValueError("book and configured prospective window do not match")


def _serialize_pilot_book[**P, R](
    method: Callable[Concatenate[PortfolioManager, P], R],
) -> Callable[Concatenate[PortfolioManager, P], R]:
    @wraps(method)
    def wrapped(self: PortfolioManager, *args: P.args, **kwargs: P.kwargs) -> R:
        path = self._ledger.path.resolve()
        if path.name in {"terra.sqlite", "sol.sqlite"} and path.parent.name in {
            "observation",
            "readiness",
        }:
            from drift.prospective.locking import pilot_lock

            with pilot_lock(path.parent.parent):
                packet, mandate, *_ = replay(self._ledger.verified_events())
                _require_window_binding(packet, mandate)
                return method(self, *args, **kwargs)
        return method(self, *args, **kwargs)

    return cast("Callable[Concatenate[PortfolioManager, P], R]", wrapped)


class PortfolioManager:
    """One local simulation book stored in the retained SQLite ledger."""

    def __init__(self, ledger: SQLiteLedger) -> None:
        self._ledger = ledger

    @classmethod
    def open(
        cls, path: Path, packet: ResearchPacket, mandate: SimulationMandate
    ) -> tuple[PortfolioManager, Json]:
        """Create a book or reopen the same packet and mandate."""
        resolved = path.resolve()
        if (
            _pilot_book(mandate)
            and resolved.name in {"terra.sqlite", "sol.sqlite"}
            and resolved.parent.name in {"observation", "readiness"}
        ):
            from drift.prospective.locking import pilot_lock

            with pilot_lock(resolved.parent.parent):
                return cls._open_locked(path, packet, mandate)
        return cls._open_locked(path, packet, mandate)

    @classmethod
    def _open_locked(
        cls, path: Path, packet: ResearchPacket, mandate: SimulationMandate
    ) -> tuple[PortfolioManager, Json]:
        _require_window_binding(packet, mandate)
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

    @_serialize_pilot_book
    def propose(
        self, proposal: InvestmentProposal, *, enforce_event_time: bool = False
    ) -> Json:
        """Validate one proposal and simulate it only when it is eligible."""
        events = self._ledger.verified_events()
        packet, mandate, _packet_hash, _mandate_hash, book_id, kernel = replay(events)
        packet = packet_through(events, until=proposal.as_of)
        dedup = f"proposal:{proposal.proposal_id}"
        existing = _find(events, dedup)
        if existing is not None:
            return _duplicate_view(events, existing, proposal)
        if _pilot_book(mandate) and not _pilot_invalidations_agree(
            self._ledger, proposal.as_of
        ):
            return _result(
                status="rejected",
                reasons=("shared_input_inconsistent",),
                proposal_id=str(proposal.proposal_id),
                snapshot=None,
                fill=None,
                inference=proposal.inference,
                model_identity=proposal.model_identity,
            )
        if enforce_event_time and proposal.as_of < max(
            event.timestamp for event in events
        ):
            return _result(
                status="rejected",
                reasons=(
                    "decision_before_recorded_state: as_of is before a ledger event",
                ),
                proposal_id=str(proposal.proposal_id),
                snapshot=_book_at(events, proposal.as_of),
                fill=None,
                inference=proposal.inference,
                model_identity=proposal.model_identity,
            )
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
        defer_execution = mandate.fill_price_source == "post_decision_execution"
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
            defer_execution=defer_execution,
        )
        if target is not None and target in packet.settlement_only_dates:
            kept = tuple(
                reason
                for reason in decision.reasons
                if not reason.startswith(("accepted:", "pending_execution:"))
            )
            decision = Decision(
                status="rejected",
                reasons=kept
                + (
                    "decision_outside_session: this session only settles "
                    "earlier decisions",
                ),
                fill_price=None,
                price_evidence_id=None,
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
        reasons = decision.reasons
        pending_trade = (
            decision.status == "accepted"
            and defer_execution
            and proposal.action != "hold"
        )
        if pending_trade:
            fill_state = "pending"
            reasons = reasons + (
                "pending_execution: the fill waits for a trade observation "
                "after this decision",
            )
        elif decision.status == "accepted" and proposal.action == "hold":
            fill_state = "not_applicable"
        elif decision.status == "accepted":
            fill_state = "filled"
        else:
            fill_state = "not_applicable"
        if decision.status == "accepted":
            if target is None:
                message = "accepted proposal has no session"
                raise ManagerError(message)
            advances = advance_dates(packet, current, target)
            for day in advances:
                kernel.advance_session(simulation_session_key(date.fromisoformat(day)))
            if proposal.action != "hold" and not defer_execution:
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
            "fill_state": fill_state,
            "inference": proposal.inference,
            "model_identity": proposal.model_identity,
            "outcome_id": f"outcome:{proposal.proposal_id}",
            "proposal": model_json(proposal),
            "proposal_hash": identity_hash(proposal),
            "reasons": cast(list[Json], list(reasons)),
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
            reasons=reasons,
            proposal_id=str(proposal.proposal_id),
            snapshot=_public_book(checked_kernel, checked, proposal.as_of),
            fill=fill,
            inference=proposal.inference,
            model_identity=proposal.model_identity,
        )

    @_serialize_pilot_book
    def execute_pending(
        self, as_of: datetime, *, execution_after: Mapping[str, datetime] | None = None
    ) -> Json:
        """Fill accepted trades from a later trade observation, once each.

        A cited-price book is refused. Missing, stale, future, and
        pre-decision observations do not become fills.
        """
        events = self._ledger.verified_events()
        packet, mandate, _ph, _mh, book_id, kernel = replay(events)
        packet = packet_through(events, until=as_of)
        if mandate.fill_price_source != "post_decision_execution":
            return {
                "results": [],
                "reasons": [
                    "unsupported_evidence: this book fills at the cited "
                    "observation price"
                ],
                "status": "rejected",
            }
        if _pilot_book(mandate):
            if not _pilot_coverage_available(self._ledger, as_of, reject_future=True):
                return {
                    "results": [],
                    "reasons": [
                        "corporate action coverage is unavailable or inconsistent"
                    ],
                    "status": "corporate_actions_unavailable",
                }
            if not _pilot_invalidations_agree(self._ledger, as_of):
                return {
                    "results": [],
                    "reasons": ["books disagree on trade invalidations"],
                    "status": "shared_input_inconsistent",
                }
        if PROSPECTIVE_SEAL_REQUIRED in mandate.acknowledgements:
            from drift.prospective.run import (
                _execution_barriers,
                _has_untrusted_decisions,
            )

            barriers = _execution_barriers(self._ledger, as_of)
            if _has_untrusted_decisions(events, barriers):
                return {
                    "results": [],
                    "reasons": ["pilot decision has no verified execution seal"],
                    "status": "untrusted_decision_time",
                }
            execution_after = (
                barriers
                if execution_after is None
                else {
                    identifier: max(when, execution_after[identifier])
                    for identifier, when in barriers.items()
                    if identifier in execution_after
                }
            )
        if _pilot_book(mandate):
            affected = _unadjusted_split_holdings(packet, events, kernel, as_of)
            if affected:
                return {
                    "results": [],
                    "reasons": [
                        "unadjusted split affects holdings: "
                        + ", ".join(sorted(affected))
                    ],
                    "status": "unadjusted_split",
                }
            if _invalidated_executions(packet, events, as_of):
                return {
                    "results": [],
                    "reasons": ["an executed trade was later invalidated"],
                    "status": "invalidated_execution",
                }
        clock = _kernel_time(events)
        if as_of < clock:
            return {
                "results": [],
                "reasons": [
                    "decision_before_recorded_state: "
                    "as_of is before the latest book time"
                ],
                "status": "rejected",
            }
        target = session_for(packet, as_of)
        current = kernel.state.session_key.local_date
        if target is None or target < current:
            return {
                "results": [],
                "reasons": [
                    "decision_outside_session: execution time is outside the "
                    "current simulation book"
                ],
                "status": "rejected",
            }
        pending, used = _pending_executions(events, as_of)
        if PROSPECTIVE_SEAL_REQUIRED in mandate.acknowledgements:
            from drift.prospective.run import _expired_review_ids

            expired = _expired_review_ids(
                tuple(event for event in events if event.timestamp <= as_of)
            )
            pending = [item for item in pending if item.proposal_id not in expired]
        if not pending:
            return {"results": [], "reasons": [], "status": "idle"}
        results: list[Json] = []
        head = _head(events)
        advanced = False
        advances = advance_dates(packet, current, target)
        for item in pending:
            from drift.prospective.config import NY

            if _pilot_book(mandate) and any(
                item.as_of.astimezone(NY).date() < day <= as_of.astimezone(NY).date()
                for day in _split_dates(packet, as_of).get(item.symbol, ())
            ):
                results.append(
                    {
                        "proposal_id": item.proposal_id,
                        "reasons": ["unadjusted split occurred after the decision"],
                        "status": "pending",
                    }
                )
                continue
            if execution_after is not None and item.proposal_id not in execution_after:
                results.append(
                    {
                        "proposal_id": item.proposal_id,
                        "reasons": [
                            "unverified_decision: no trusted execution boundary"
                        ],
                        "status": "pending",
                    }
                )
                continue
            boundary = item.as_of
            if execution_after is not None:
                boundary = max(boundary, execution_after[item.proposal_id])
            found = _next_trade_observation(
                packet,
                mandate,
                symbol=item.symbol,
                decision_at=boundary,
                as_of=as_of,
                used=used,
            )
            if found is None:
                results.append(
                    {
                        "proposal_id": item.proposal_id,
                        "reasons": [
                            "pending_execution: no trade observation after "
                            "the decision is available"
                        ],
                        "status": "pending",
                    }
                )
                continue
            chosen, refusal = found
            if _pilot_book(mandate) and not _pilot_coverage_available(
                self._ledger,
                as_of,
                reject_future=True,
                required_at=chosen.available_at,
            ):
                results.append(
                    {
                        "proposal_id": item.proposal_id,
                        "reasons": [
                            "corporate action coverage predates the trade observation"
                        ],
                        "status": "pending",
                    }
                )
                continue
            if refusal is not None:
                results.append(
                    _record_unfilled(
                        self._ledger,
                        book_id=book_id,
                        as_of=as_of,
                        item=item,
                        reason=refusal,
                        evidence_id=chosen.evidence_id,
                        head=head,
                    )
                )
                head = _head(self._ledger.verified_events())
                used.add(chosen.evidence_id)
                continue
            if chosen.price is None:
                message = "trade observation is missing a price"
                raise ManagerError(message)
            limit_reasons = fill_limit_reasons(
                action=item.action,
                symbol=item.symbol,
                quantity=item.quantity,
                fill_price=chosen.price,
                mandate=mandate,
                cash=kernel.state.cash_balance,
                cost_basis_by_symbol=_costs(kernel, packet),
                quantity_by_symbol=_quantities(kernel, packet),
            )
            if limit_reasons:
                results.append(
                    _record_unfilled(
                        self._ledger,
                        book_id=book_id,
                        as_of=as_of,
                        item=item,
                        reason=limit_reasons[0],
                        evidence_id=chosen.evidence_id,
                        head=head,
                    )
                )
                head = _head(self._ledger.verified_events())
                used.add(chosen.evidence_id)
                continue
            step_advances = advances if not advanced else []
            if not advanced:
                for day in advances:
                    kernel.advance_session(
                        simulation_session_key(date.fromisoformat(day))
                    )
                advanced = True
            fill = _execution_fill(packet, mandate, item, chosen)
            apply_fill_json(kernel, fill)
            payload: dict[str, Json] = {
                "advances": cast(list[Json], step_advances),
                "fill": fill,
                "price_evidence_id": chosen.evidence_id,
                "proposal_id": item.proposal_id,
                "reasons": ["filled: trade observation after the decision"],
                "snapshot": take_snapshot(kernel, packet),
                "status": "filled",
            }
            appended = append_manager_event(
                self._ledger,
                book_id=book_id,
                event_type=FILL,
                dedup_key=f"fill:{item.proposal_id}",
                timestamp=as_of,
                payload=payload,
                expected_previous_hash=head,
            )
            head = appended.event_hash
            used.add(chosen.evidence_id)
            _checked, *_ignored, checked_kernel = replay(self._ledger.verified_events())
            if take_snapshot(checked_kernel, packet) != payload["snapshot"]:
                message = "recorded fill does not replay"
                raise LedgerIntegrityError(message)
            kernel = checked_kernel
            results.append(
                {
                    "fill": fill,
                    "proposal_id": item.proposal_id,
                    "reasons": ["filled: trade observation after the decision"],
                    "status": "filled",
                }
            )
        status = "pending"
        if any(
            isinstance(row, dict) and row.get("status") == "filled" for row in results
        ):
            status = "filled"
        elif any(
            isinstance(row, dict) and row.get("status") == "rejected" for row in results
        ):
            status = "rejected"
        return {
            "reasons": [],
            "results": cast(Json, results),
            "snapshot": _public_book(kernel, packet, as_of),
            "status": status,
        }

    @_serialize_pilot_book
    def mark(self, as_of: datetime) -> Json:
        """Mark held names at cited close observations. Partial marks are refused."""
        events = self._ledger.verified_events()
        packet, mandate, _ph, _mh, book_id, kernel = replay(events)
        opening_packet = packet
        packet = packet_through(events, until=as_of)
        if _pilot_book(mandate):
            if not _pilot_coverage_available(self._ledger, as_of, reject_future=True):
                return _result(
                    status="rejected",
                    reasons=("corporate_actions_unavailable",),
                    proposal_id=None,
                    snapshot=None,
                    fill=None,
                    inference=None,
                    model_identity=None,
                )
            if not _pilot_invalidations_agree(self._ledger, as_of):
                return _result(
                    status="rejected",
                    reasons=("shared_input_inconsistent",),
                    proposal_id=None,
                    snapshot=None,
                    fill=None,
                    inference=None,
                    model_identity=None,
                )
            affected = _unadjusted_split_holdings(packet, events, kernel, as_of)
            if affected:
                return _result(
                    status="rejected",
                    reasons=(f"unadjusted_split: {', '.join(sorted(affected))}",),
                    proposal_id=None,
                    snapshot=None,
                    fill=None,
                    inference=None,
                    model_identity=None,
                )
            if _invalidated_executions(packet, events, as_of):
                return _result(
                    status="rejected",
                    reasons=("invalidated_execution",),
                    proposal_id=None,
                    snapshot=None,
                    fill=None,
                    inference=None,
                    model_identity=None,
                )
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
                opening_packet=opening_packet,
            )
            if isinstance(chosen, str):
                reasons.append(chosen)
                continue
            if _pilot_book(mandate) and not _pilot_coverage_available(
                self._ledger,
                as_of,
                reject_future=True,
                required_at=chosen.available_at,
            ):
                reasons.append(
                    "corporate_actions_unavailable: coverage predates the close"
                )
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

    @_serialize_pilot_book
    def context(self, as_of: datetime) -> Json:
        """Point-in-time inputs, decisions, and outcomes for a later review."""
        events = self._ledger.verified_events()
        packet, mandate, *_rest, kernel = replay(events, until=as_of)
        packet = packet_through(events, until=as_of)
        decisions: list[Json] = []
        feedback: list[Json] = []
        reflections: list[Json] = []
        settlements = _settlements(events, as_of)
        invalidated_proposals = (
            _invalidated_execution_proposals(packet, events, as_of)
            if _pilot_book(mandate)
            else set()
        )
        expired: set[str] = set()
        if PROSPECTIVE_SEAL_REQUIRED in mandate.acknowledgements:
            from drift.prospective.run import _expired_review_ids

            expired = _expired_review_ids(
                tuple(event for event in events if event.timestamp <= as_of)
            )
        for event in events:
            if event.timestamp > as_of:
                continue
            payload = thaw(event.payload)
            if event.event_type == DECISION:
                view = _decision_context(payload)
                proposal = payload.get("proposal")
                proposal_id = (
                    proposal.get("proposal_id") if isinstance(proposal, dict) else None
                )
                if isinstance(proposal_id, str) and proposal_id in settlements:
                    view = _with_settlement(view, settlements[proposal_id])
                if (
                    isinstance(proposal_id, str)
                    and proposal_id in expired
                    and isinstance(view, dict)
                ):
                    view = {**view, "status": "expired", "settlement_status": "expired"}
                if (
                    isinstance(proposal_id, str)
                    and proposal_id in invalidated_proposals
                    and isinstance(view, dict)
                ):
                    view = {
                        **view,
                        "status": "invalidated",
                        "settlement_status": "invalidated",
                        "fill": None,
                    }
                decisions.append(view)
            elif event.event_type == FEEDBACK:
                note = payload.get("feedback")
                if note is not None:
                    feedback.append(note)
            elif event.event_type == REFLECTION:
                note = payload.get("reflection")
                if note is not None:
                    reflections.append(note)
        evidence: list[Json] = []
        invalidated_prices = (
            _invalidated_trade_ids(packet, as_of) if _pilot_book(mandate) else set()
        )
        from drift.prospective.trade_identity import normalize_trade_id

        for item in packet.evidence:
            if (
                item.available_at <= as_of
                and normalize_trade_id(item.evidence_id) not in invalidated_prices
            ):
                evidence.append(_evidence_context(item))
        book = _public_book(kernel, packet, as_of)
        if _pilot_book(mandate):
            affected = _unadjusted_split_holdings(packet, events, kernel, as_of)
            coverage_missing = not _pilot_coverage_available(self._ledger, as_of)
            if coverage_missing and kernel.state.holdings and isinstance(book, dict):
                book.update(
                    {
                        "marked": False,
                        "holdings_market_value": None,
                        "net_asset_value": None,
                        "valuation": "unavailable",
                        "valuation_reason": (
                            "corporate action coverage is unavailable or inconsistent"
                        ),
                    }
                )
            if affected and isinstance(book, dict):
                book.update(
                    {
                        "marked": False,
                        "holdings_market_value": None,
                        "net_asset_value": None,
                        "valuation": "unavailable",
                        "valuation_reason": "unadjusted split affects "
                        + ", ".join(sorted(affected)),
                    }
                )
            if _invalidated_executions(packet, events, as_of) and isinstance(
                book, dict
            ):
                book.update(
                    {
                        "marked": False,
                        "holdings_market_value": None,
                        "net_asset_value": None,
                        "valuation": "unavailable",
                        "valuation_reason": "an executed trade was later invalidated",
                    }
                )
            if not _pilot_invalidations_agree(self._ledger, as_of) and isinstance(
                book, dict
            ):
                book.update(
                    {
                        "marked": False,
                        "holdings_market_value": None,
                        "net_asset_value": None,
                        "valuation": "unavailable",
                        "valuation_reason": "books disagree on trade invalidations",
                    }
                )
        body: dict[str, Json] = {
            "as_of": as_of.isoformat(),
            "book": book,
            "decisions": decisions,
            "evidence": evidence,
            "feedback": feedback,
            "limitations": list(REPORT_LIMITATIONS),
            "reflections": reflections,
            "untrusted_text": True,
        }
        return body

    @_serialize_pilot_book
    def report(self, as_of: datetime) -> Json:
        """Performance, risk inputs, benchmark, and system costs, kept apart."""
        events = self._ledger.verified_events()
        packet, mandate, *_rest, kernel = replay(events, until=as_of)
        packet = packet_through(events, until=as_of)
        valuation, market, unrealized, nav, valuation_reason = _valuation(kernel)
        if _pilot_book(mandate):
            if kernel.state.holdings and not _pilot_coverage_available(
                self._ledger, as_of
            ):
                valuation = "unavailable"
                market = unrealized = nav = None
                valuation_reason = (
                    "corporate action coverage is unavailable or inconsistent"
                )
            affected = _unadjusted_split_holdings(packet, events, kernel, as_of)
            if affected:
                valuation = "unavailable"
                market = unrealized = nav = None
                valuation_reason = "unadjusted split affects " + ", ".join(
                    sorted(affected)
                )
            if _invalidated_executions(packet, events, as_of):
                valuation = "unavailable"
                market = unrealized = nav = None
                valuation_reason = "an executed trade was later invalidated"
            if not _pilot_invalidations_agree(self._ledger, as_of):
                valuation = "unavailable"
                market = unrealized = nav = None
                valuation_reason = "books disagree on trade invalidations"
        requested_session = session_for(packet, as_of)
        if requested_session is None or (
            kernel.state.holdings
            and requested_session != kernel.state.session_key.local_date
        ):
            valuation = "unavailable"
            market = None
            unrealized = None
            nav = None
            valuation_reason = (
                "the requested time is outside the book's current session, "
                "so an earlier mark is not used"
            )
        price_benchmark = _price_benchmark(
            packet, events, as_of, nav, kernel.state.session_key.local_date
        )
        relative_benchmark = _benchmark(packet, as_of, nav)
        if PROSPECTIVE_SEAL_REQUIRED in mandate.acknowledgements:
            relative_benchmark = _paired_close_benchmark(
                self._ledger,
                as_of,
                nav,
                requested_session or kernel.state.session_key.local_date,
            )
        body: dict[str, Json] = {
            "benchmark_relative": (relative_benchmark),
            "book_session": kernel.state.session_key.local_date.isoformat(),
            "cash": money_text(kernel.state.cash_balance),
            "cumulative_simulation_transaction_costs": money_text(
                kernel.state.cumulative_transaction_costs
            ),
            "holdings_market_value": market,
            "lane": "exploratory",
            "limitations": list(REPORT_LIMITATIONS),
            "net_asset_value": nav,
            "portfolio_return": _portfolio_return(packet, nav),
            "exposure": _exposure(market, nav),
            "ratio_precision": RETURN_RATIO_PRECISION,
            "observed_drawdown": (
                {
                    "maximum": None,
                    "valuation_samples": None,
                    "limitation": valuation_reason,
                }
                if nav is None and _pilot_book(mandate)
                else _observed_drawdown(events, packet, as_of)
            ),
            "price_return_benchmark": price_benchmark,
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

    @_serialize_pilot_book
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
        if _pilot_book(mandate):
            from drift.prospective.trade_identity import normalize_trade_id

            if not _pilot_invalidations_agree(self._ledger, request.as_of):
                return _note_result("rejected", ("shared_input_inconsistent",))
            identity = normalize_trade_id(request.observation_evidence_id)
            if identity in _invalidated_trade_ids(packet, request.as_of):
                return _note_result("rejected", ("invalidated_evidence",))
            if str(request.proposal_id) in _invalidated_execution_proposals(
                packet, events, request.as_of
            ):
                return _note_result("rejected", ("invalidated_decision",))
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

    @_serialize_pilot_book
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

    @_serialize_pilot_book
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
        if event.event_type == FILL:
            moves = thaw(event.payload).get("status") == "filled"
        if moves and event.timestamp > latest:
            latest = event.timestamp
    return latest


def _head(events: tuple[AuditEvent, ...]) -> str:
    return events[-1].event_hash


def _latest_fill_id(events: tuple[AuditEvent, ...]) -> str:
    """Identity of the latest accepted fill. A restored lot is a new fill."""
    anchor = str(events[0].event_id)
    for event in events:
        if event.event_type == FILL:
            payload = thaw(event.payload)
            if payload.get("status") == "filled":
                anchor = str(event.event_id)
            continue
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
    expired: set[str] = set()
    if any(
        event.event_type == PROSPECTIVE_EXPIRED and event.timestamp <= as_of
        for event in events
    ):
        from drift.prospective.run import _expired_review_ids

        expired = _expired_review_ids(
            tuple(event for event in events if event.timestamp <= as_of)
        )
    invalidated_proposals = _invalidated_execution_proposals(
        packet_through(events, until=as_of), events, as_of
    )
    for event in events:
        if event.event_type != DECISION or event.timestamp > as_of:
            continue
        payload = thaw(event.payload)
        outcome_id = payload.get("outcome_id")
        proposal_data = payload.get("proposal")
        if not isinstance(outcome_id, str) or not isinstance(proposal_data, dict):
            continue
        if proposal_data.get("proposal_id") in expired | invalidated_proposals:
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


def _valid_pilot_close(
    item: EvidenceItem, symbol: str, opening_packet: ResearchPacket | None
) -> bool:
    from drift.prospective.config import NY, is_session_day, session_close_utc

    labels = {
        row.source_label
        for row in (opening_packet.evidence if opening_packet else ())
        if row.price_role == "close"
        and row.source_label in {"alpaca-bars-v2-iex-raw", "alpaca-bars-v2-sip-raw"}
    }
    day = item.observed_at.astimezone(NY).date()
    if not is_session_day(day):
        return False
    return (
        len(labels) == 1
        and item.source_label in labels
        and item.observed_at == session_close_utc(day)
        and item.available_at >= item.observed_at
        and item.evidence_id == f"{item.source_label}:{symbol}:close:{day.isoformat()}"
    )


def _close_observation(
    packet: ResearchPacket,
    mandate: SimulationMandate,
    symbol: str,
    *,
    as_of: datetime,
    session_open: datetime,
    session_close: datetime,
    opening_packet: ResearchPacket | None = None,
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
        and (
            not _pilot_book(mandate) or _valid_pilot_close(item, symbol, opening_packet)
        )
    ]
    fresh = [
        item
        for item in matches
        if as_of - citation_time(item.observed_at, item.available_at)
        <= timedelta(hours=mandate.max_evidence_age_hours)
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
    aged = citation_time(observation.observed_at, observation.available_at)
    if as_of - aged > timedelta(hours=mandate.max_evidence_age_hours):
        return "stale_evidence: the observation is older than the configured age"
    return None


def _evidence_context(item: EvidenceItem) -> Json:
    return {
        "available_at": item.available_at.isoformat(),
        "observed_at": item.observed_at.isoformat(),
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


def _settlements(
    events: tuple[AuditEvent, ...], as_of: datetime
) -> dict[str, dict[str, Json]]:
    found: dict[str, dict[str, Json]] = {}
    for event in events:
        if event.timestamp > as_of or event.event_type != FILL:
            continue
        payload = thaw(event.payload)
        proposal_id = payload.get("proposal_id")
        if isinstance(proposal_id, str):
            found[proposal_id] = payload
    return found


def _with_settlement(view: Json, settlement: dict[str, Json]) -> Json:
    if not isinstance(view, dict):
        return view
    updated = dict(view)
    updated["fill"] = settlement.get("fill")
    status = settlement.get("status")
    updated["settlement_status"] = status if isinstance(status, str) else None
    return updated


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
        "as_of": proposal.get("as_of") if isinstance(proposal, dict) else None,
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


def _pilot_invalidations_agree(ledger: SQLiteLedger, as_of: datetime) -> bool:
    """Both books must see identical invalidation notices at the cutoff."""
    if ledger.path.name not in {"terra.sqlite", "sol.sqlite"}:
        return False
    notices: list[tuple[EvidenceItem, ...]] = []
    for name in ("terra.sqlite", "sol.sqlite"):
        path = ledger.path.parent / name
        if not path.is_file():
            return False
        events = SQLiteLedger.open_existing(path).verified_events()
        packet = packet_through(events, until=as_of)
        notices.append(
            tuple(
                sorted(
                    (
                        item
                        for item in packet.evidence
                        if item.source_label == "alpaca-trade-invalidation"
                        and item.observed_at <= as_of
                        and item.available_at <= as_of
                    ),
                    key=lambda item: item.evidence_id,
                )
            )
        )
    return notices[0] == notices[1]


def _pilot_coverage_available(
    ledger: SQLiteLedger,
    as_of: datetime,
    *,
    reject_future: bool = False,
    required_at: datetime | None = None,
) -> bool:
    """Both books must agree on the latest recorded corporate-action coverage."""
    if ledger.path.name not in {"terra.sqlite", "sol.sqlite"}:
        return False
    states: list[tuple[datetime, str, datetime]] = []
    for name in ("terra.sqlite", "sol.sqlite"):
        path = ledger.path.parent / name
        if not path.is_file():
            return False
        events = SQLiteLedger.open_existing(path).verified_events()
        checks = [
            event for event in events if event.event_type == PROSPECTIVE_CA_STATUS
        ]
        if reject_future and any(event.timestamp > as_of for event in checks):
            return False
        visible = [event for event in checks if event.timestamp <= as_of]
        if not visible:
            return False
        latest = visible[-1]
        status = thaw(latest.payload).get("status")
        raw_coverage = thaw(latest.payload).get("coverage_at")
        if not isinstance(raw_coverage, str):
            return False
        try:
            coverage_at = datetime.fromisoformat(raw_coverage)
        except ValueError:
            return False
        if coverage_at.tzinfo is None or coverage_at > latest.timestamp:
            return False
        if status not in {"complete", "unavailable"}:
            return False
        if (
            latest.deduplication_key
            != f"prospective-ca:{status}:{latest.timestamp.isoformat()}"
        ):
            return False
        assert isinstance(status, str)
        states.append((latest.timestamp, status, coverage_at))
    return (
        states[0] == states[1]
        and states[0][1] == "complete"
        and (required_at is None or states[0][2] >= required_at)
    )


def _split_dates(
    packet: ResearchPacket, as_of: datetime
) -> dict[str, tuple[date, ...]]:
    from drift.prospective.config import NY

    found: dict[str, list[date]] = {}
    for item in packet.evidence:
        if item.available_at > as_of or item.observed_at > as_of:
            continue
        day = split_date(item.source_label, item.evidence_id, item.symbol)
        if day is not None and day <= as_of.astimezone(NY).date():
            found.setdefault(item.symbol, []).append(day)
    return {symbol: tuple(sorted(days)) for symbol, days in found.items()}


def _unadjusted_split_holdings(
    packet: ResearchPacket,
    events: tuple[AuditEvent, ...],
    kernel: PortfolioAccountingKernel,
    as_of: datetime,
) -> set[str]:
    splits = _split_dates(packet, as_of)
    held = {
        str(item.security_id): symbol_for(packet, item.security_id)
        for item in kernel.state.holdings
    }
    affected: set[str] = set()
    for security_id, symbol in held.items():
        for day in splits.get(symbol, ()):
            quantity = 0
            for event in events:
                if event.timestamp > as_of:
                    continue
                if event.event_type not in (DECISION, FILL):
                    continue
                payload = thaw(event.payload)
                fill = payload.get("fill")
                if not isinstance(fill, dict) or fill.get("security_id") != security_id:
                    continue
                evidence_id = fill.get("price_evidence_id")
                evidence = next(
                    (row for row in packet.evidence if row.evidence_id == evidence_id),
                    None,
                )
                if evidence is None:
                    affected.add(symbol)
                    break
                from drift.prospective.config import NY

                if evidence.observed_at.astimezone(NY).date() >= day:
                    continue
                amount = fill.get("quantity")
                if not isinstance(amount, int) or isinstance(amount, bool):
                    raise LedgerIntegrityError("recorded fill quantity is invalid")
                if fill.get("side") == "buy":
                    quantity += amount
                elif fill.get("side") == "sell":
                    quantity -= amount
            if quantity > 0 or symbol in affected:
                affected.add(symbol)
                break
    return affected


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
    with decimal_context():
        cost = sum(
            (
                holding.cost_basis
                for holding in state.holdings
                if holding.cost_basis is not None
            ),
            Decimal("0"),
        )
        recomputed = state.holdings_market_value - cost
    exact_cost = sum(
        (
            Fraction(holding.cost_basis)
            for holding in state.holdings
            if holding.cost_basis is not None
        ),
        Fraction(0),
    )
    if Fraction(recomputed) != Fraction(state.holdings_market_value) - exact_cost:
        return (
            "unavailable",
            None,
            None,
            None,
            "unrealized result is not exact in the portfolio decimal context",
        )
    return (
        "marked",
        money_text(state.holdings_market_value),
        money_text(recomputed),
        money_text(state.net_asset_value),
        "market value uses the recorded exploratory close mark",
    )


class _PendingFill:
    """One accepted trade that does not yet have an execution event."""

    def __init__(
        self,
        *,
        proposal_id: str,
        symbol: str,
        action: Literal["buy", "sell"],
        quantity: int,
        as_of: datetime,
    ) -> None:
        self.proposal_id = proposal_id
        self.symbol = symbol
        self.action = action
        self.quantity = quantity
        self.as_of = as_of


def _pending_executions(
    events: tuple[AuditEvent, ...], as_of: datetime
) -> tuple[list[_PendingFill], set[str]]:
    closed: set[str] = set()
    used: set[str] = set()
    for event in events:
        if event.timestamp > as_of or event.event_type != FILL:
            continue
        payload = thaw(event.payload)
        proposal_id = payload.get("proposal_id")
        if isinstance(proposal_id, str):
            closed.add(proposal_id)
        evidence_id = payload.get("price_evidence_id")
        if isinstance(evidence_id, str):
            used.add(evidence_id)
    pending: list[_PendingFill] = []
    for event in events:
        if event.timestamp > as_of or event.event_type != DECISION:
            continue
        payload = thaw(event.payload)
        pending_state = payload.get("fill_state") == "pending"
        accepted = payload.get("status") == "accepted"
        if not pending_state or not accepted:
            continue
        proposal = payload.get("proposal")
        if not isinstance(proposal, dict):
            continue
        proposal_id = proposal.get("proposal_id")
        symbol = proposal.get("symbol")
        action = proposal.get("action")
        quantity = proposal.get("quantity")
        recorded = proposal.get("as_of")
        if (
            not isinstance(proposal_id, str)
            or proposal_id in closed
            or not isinstance(symbol, str)
            or action not in ("buy", "sell")
            or not isinstance(quantity, int)
            or not isinstance(recorded, str)
        ):
            continue
        pending.append(
            _PendingFill(
                proposal_id=proposal_id,
                symbol=symbol,
                action=cast(Literal["buy", "sell"], action),
                quantity=quantity,
                as_of=datetime.fromisoformat(recorded),
            )
        )
    return pending, used


def _valid_pilot_trade(
    item: EvidenceItem,
    packet: ResearchPacket,
    mandate: SimulationMandate,
    symbol: str,
    *,
    benchmark: bool = False,
) -> bool:
    from drift.prospective.config import (
        NY,
        calendar_dates,
        is_session_day,
        session_close_utc,
        session_open_utc,
    )

    feeds = {
        feed
        for feed in ("iex", "sip")
        if any(
            row.source_label == f"alpaca-bars-v2-{feed}-raw"
            and row.price_role == "close"
            for row in packet.evidence
        )
    }
    if len(feeds) != 1:
        return False
    feed = next(iter(feeds))
    if item.source_label != f"alpaca-trades-v2-{feed}":
        return False
    prefix = f"alpaca-trades-v2-{feed}:{symbol}:"
    from drift.prospective.trade_identity import normalize_trade_id

    source_id = (
        item.evidence_id.removeprefix("alpaca:benchmark:")
        if benchmark
        else item.evidence_id
    )
    canonical = normalize_trade_id(source_id)
    if canonical is None or not canonical.startswith(prefix):
        return False
    raw_time, _exchange, _raw_id = canonical.removeprefix(prefix).rsplit(":", 2)
    try:
        observed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    day = item.observed_at.astimezone(NY).date()
    allowed = (
        calendar_dates()
        if PROSPECTIVE_SEAL_REQUIRED in mandate.acknowledgements
        else tuple(s.local_date for s in packet.sessions)
    )
    return bool(
        observed == item.observed_at
        and day in allowed
        and is_session_day(day)
        and session_open_utc(day) <= observed <= session_close_utc(day)
    )


def _next_trade_observation(
    packet: ResearchPacket,
    mandate: SimulationMandate,
    *,
    symbol: str,
    decision_at: datetime,
    as_of: datetime,
    used: set[str],
) -> tuple[EvidenceItem, str | None] | None:
    """Earliest unused trade print strictly after the decision."""
    pilot = _pilot_book(mandate)
    from drift.prospective.trade_identity import normalize_trade_id

    used_keys = {normalize_trade_id(value) for value in used} if pilot else set()
    invalidated = _invalidated_trade_ids(packet, as_of) if pilot else set()

    candidates = [
        item
        for item in packet.evidence
        if item.kind == "observation"
        and item.price_role == "trade"
        and item.symbol == symbol
        and item.price is not None
        and item.observed_at > decision_at
        and item.available_at > decision_at
        and item.observed_at <= as_of
        and item.available_at <= as_of
        and item.evidence_id not in used
        and (not pilot or normalize_trade_id(item.evidence_id) not in used_keys)
        and (not pilot or normalize_trade_id(item.evidence_id) not in invalidated)
        and (not pilot or _valid_pilot_trade(item, packet, mandate, symbol))
    ]
    if not candidates:
        return None
    chosen = sorted(
        candidates,
        key=lambda item: (item.observed_at, item.available_at, item.evidence_id),
    )[0]
    age = timedelta(hours=mandate.max_evidence_age_hours)
    observed_age = as_of - chosen.observed_at
    available_age = as_of - chosen.available_at
    if observed_age > age or available_age > age:
        return (
            chosen,
            f"stale_evidence: {chosen.evidence_id} is older than the configured age",
        )
    return chosen, None


def _invalidated_trade_ids(packet: ResearchPacket, as_of: datetime) -> set[str]:
    from drift.prospective.trade_identity import normalize_trade_id

    found: set[str] = set()
    for item in packet.evidence:
        prefix = "alpaca:trade-invalid:"
        if (
            item.source_label != "alpaca-trade-invalidation"
            or not item.evidence_id.startswith(prefix)
            or item.available_at > as_of
            or item.observed_at > as_of
        ):
            continue
        raw_id, separator, status = item.evidence_id.removeprefix(prefix).rpartition(
            ":"
        )
        canonical = normalize_trade_id(raw_id)
        if separator and status in {"canceled", "incorrect"} and canonical is not None:
            found.add(canonical)
    return found


def _invalidated_executions(
    packet: ResearchPacket, events: tuple[AuditEvent, ...], as_of: datetime
) -> set[str]:
    from drift.prospective.trade_identity import normalize_trade_id

    invalidated = _invalidated_trade_ids(packet, as_of)
    found: set[str] = set()
    for event in events:
        if event.event_type != FILL or event.timestamp > as_of:
            continue
        payload = thaw(event.payload)
        evidence_id = payload.get("price_evidence_id")
        if payload.get("status") == "filled" and isinstance(evidence_id, str):
            identity = normalize_trade_id(evidence_id)
            if identity is not None and identity in invalidated:
                found.add(identity)
    return found


def _invalidated_execution_proposals(
    packet: ResearchPacket, events: tuple[AuditEvent, ...], as_of: datetime
) -> set[str]:
    from drift.prospective.trade_identity import normalize_trade_id

    invalidated = _invalidated_executions(packet, events, as_of)
    found: set[str] = set()
    for event in events:
        if event.event_type != FILL or event.timestamp > as_of:
            continue
        payload = thaw(event.payload)
        identifier, price_id = (
            payload.get("proposal_id"),
            payload.get("price_evidence_id"),
        )
        if (
            isinstance(identifier, str)
            and isinstance(price_id, str)
            and normalize_trade_id(price_id) in invalidated
        ):
            found.add(identifier)
    return found


def _execution_fill(
    packet: ResearchPacket,
    mandate: SimulationMandate,
    item: _PendingFill,
    chosen: EvidenceItem,
) -> Json:
    return {
        "assumptions": {
            "causal_rule": ("observed_at and available_at are both after the decision"),
            "fee_source": "simulation_mandate.fill_fee",
            "not_a_market_execution": True,
            "price_source": "post_decision_trade_observation",
            "whole_shares_only": True,
        },
        "fill_price": chosen.price,
        "price_evidence_id": chosen.evidence_id,
        "quantity": item.quantity,
        "security_id": str(security_for(packet, item.symbol)),
        "side": item.action,
        "transaction_costs": mandate.fill_fee,
    }


def _record_unfilled(
    ledger: SQLiteLedger,
    *,
    book_id: UUID,
    as_of: datetime,
    item: _PendingFill,
    reason: str,
    evidence_id: str,
    head: str,
) -> Json:
    """Close one pending trade without a fill. A later price is not tried."""
    append_manager_event(
        ledger,
        book_id=book_id,
        event_type=FILL,
        dedup_key=f"fill:{item.proposal_id}",
        timestamp=as_of,
        payload={
            "fill": None,
            "price_evidence_id": evidence_id,
            "proposal_id": item.proposal_id,
            "reasons": [reason],
            "status": "rejected",
        },
        expected_previous_hash=head,
    )
    return {
        "proposal_id": item.proposal_id,
        "reasons": [reason],
        "status": "rejected",
    }


def _return_ratio(numerator: Decimal, denominator: Decimal) -> tuple[str, bool] | None:
    """Return a documented ratio. Inexact ratios are 12-place half-even."""
    if denominator == 0:
        return None
    exact = Fraction(numerator) / Fraction(denominator)
    with decimal_context():
        quotient = numerator / denominator
    if Fraction(quotient) == exact:
        return format(quotient, "f"), True
    quantum = Decimal("1").scaleb(-RETURN_RATIO_PLACES)
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        rounded = (Decimal(numerator) / Decimal(denominator)).quantize(quantum)
    return format(rounded, "f"), False


def _money_difference(left: Decimal, right: Decimal) -> Decimal | None:
    with decimal_context():
        result = left - right
    return result if Fraction(result) == Fraction(left) - Fraction(right) else None


def _portfolio_return(packet: ResearchPacket, nav: str | None) -> str | None:
    if nav is None:
        return None
    initial = parse_money(packet.portfolio_context.cash)
    difference = _money_difference(parse_money(nav), initial)
    if difference is None:
        return None
    ratio = _return_ratio(difference, initial)
    return None if ratio is None else ratio[0]


def _exposure(market: str | None, nav: str | None) -> str | None:
    if market is None or nav is None or parse_money(nav) == 0:
        return None
    ratio = _return_ratio(parse_money(market), parse_money(nav))
    return None if ratio is None else ratio[0]


def _observed_drawdown(
    events: tuple[AuditEvent, ...], packet: ResearchPacket, as_of: datetime
) -> Json:
    """Drawdown across recorded complete marks, not a continuous maximum."""
    initial = parse_money(packet.portfolio_context.cash)
    values = [initial]
    for event in events:
        if event.timestamp > as_of or event.event_type not in (MARK, FILL, DECISION):
            continue
        payload = thaw(event.payload)
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        if event.event_type != MARK and snapshot.get("holdings") != []:
            continue
        if event.event_type == MARK and snapshot.get("marked") is not True:
            continue
        nav = snapshot.get("net_asset_value")
        if isinstance(nav, str):
            value = parse_money(nav)
            if event.event_type == MARK or value != values[-1]:
                values.append(value)
    peak = initial
    worst = Fraction(0)
    numerator = Decimal(0)
    denominator = initial
    for value in values:
        peak = max(peak, value)
        decline = (Fraction(peak) - Fraction(value)) / Fraction(peak)
        if decline > worst:
            worst = decline
            denominator = peak
            difference = _money_difference(peak, value)
            if difference is None:
                return {
                    "maximum": None,
                    "valuation_samples": len(values),
                    "limitation": (
                        "drawdown difference is not exact in the money context"
                    ),
                }
            numerator = difference
    ratio = _return_ratio(numerator, denominator)
    return {
        "maximum": None if ratio is None else ratio[0],
        "valuation_samples": len(values),
        "limitation": "recorded marks only; missing marks can hide a larger drawdown",
    }


def _paired_close_benchmark(
    ledger: SQLiteLedger, as_of: datetime, nav: str | None, session_date: date
) -> Json:
    """Compare both books from their first jointly measurable post-decision close."""
    from drift.prospective.config import NY
    from drift.prospective.run import _execution_barriers

    unavailable: dict[str, Json] = {
        "status": "unavailable",
        "series_kind": "price_only_substitute",
        "reason": "a shared post-decision close and both book valuations are required",
    }
    if nav is None or ledger.path.name not in {"terra.sqlite", "sol.sqlite"}:
        return unavailable
    histories: list[tuple[AuditEvent, ...]] = []
    packets: list[ResearchPacket] = []
    first_seals: list[datetime] = []
    for name in ("terra.sqlite", "sol.sqlite"):
        path = ledger.path.parent / name
        if not path.is_file():
            return unavailable
        source = SQLiteLedger(path, create_schema=False)
        events = source.verified_events()
        barriers = _execution_barriers(source, as_of)
        first: datetime | None = None
        for event in events:
            if event.timestamp > as_of or event.event_type != DECISION:
                continue
            payload = thaw(event.payload)
            proposal = payload.get("proposal")
            identifier = (
                proposal.get("proposal_id") if isinstance(proposal, dict) else None
            )
            if (
                payload.get("status") == "accepted"
                and isinstance(identifier, str)
                and identifier in barriers
            ):
                first = barriers[identifier]
                break
        if first is None:
            return unavailable
        histories.append(events)
        packets.append(packet_through(events, until=as_of))
        first_seals.append(first)
    opening_packets = [replay(events)[0] for events in histories]
    closes: list[dict[str, EvidenceItem]] = []
    for packet, opening in zip(packets, opening_packets, strict=True):
        closes.append(
            {
                item.evidence_id: item
                for item in packet.evidence
                if item.symbol == "SPY"
                and item.price_role == "close"
                and item.price is not None
                and item.available_at <= as_of
                and item.observed_at > max(first_seals)
                and _valid_pilot_close(item, "SPY", opening)
            }
        )
    shared = sorted(
        (item for key, item in closes[0].items() if closes[1].get(key) == item),
        key=lambda item: item.observed_at,
    )
    ends = [
        item
        for item in shared
        if item.observed_at.astimezone(NY).date() == session_date
    ]
    if not ends:
        return unavailable
    end = ends[-1]
    own = 0 if ledger.path.name == "terra.sqlite" else 1
    for start in shared:
        day = start.observed_at.astimezone(NY).date()
        if day > session_date:
            break
        checkpoints = {start.available_at}
        for events in histories:
            checkpoints.update(
                event.timestamp
                for event in events
                if event.event_type == MARK
                and start.available_at <= event.timestamp <= as_of
                and event.timestamp.astimezone(NY).date() == day
            )
        for when in sorted(checkpoints):
            values: list[str] = []
            for events in histories:
                _packet, _rules, *_rest, kernel = replay(events, until=when)
                if kernel.state.holdings and kernel.state.session_key.local_date != day:
                    break
                valuation, _market, _unrealized, value, _reason = _valuation(kernel)
                if valuation not in ("marked", "cash_only") or value is None:
                    break
                values.append(value)
            if len(values) != 2:
                continue
            if any(
                day < split <= session_date
                for split in _split_dates(packets[own], as_of).get("SPY", ())
            ):
                return unavailable
            assert start.price is not None and end.price is not None
            series_difference = _money_difference(
                parse_money(end.price), parse_money(start.price)
            )
            portfolio_difference = _money_difference(
                parse_money(nav), parse_money(values[own])
            )
            if series_difference is None or portfolio_difference is None:
                return unavailable
            series = _return_ratio(series_difference, parse_money(start.price))
            portfolio = _return_ratio(portfolio_difference, parse_money(values[own]))
            if series is None or portfolio is None:
                return unavailable
            return {
                "status": "available",
                "series_kind": "price_only_substitute",
                "series_change": series[0],
                "portfolio_change": portfolio[0],
                "start_evidence_id": start.evidence_id,
                "end_evidence_id": end.evidence_id,
                "start_as_of": when.isoformat(),
                "start_portfolio_value": values[own],
                "limitation": (
                    "Comparison begins at the first shared close after both "
                    "decisions with both books valued; earlier performance and "
                    "dividends are excluded."
                ),
            }
    return unavailable


def _price_benchmark(
    packet: ResearchPacket,
    events: tuple[AuditEvent, ...],
    as_of: datetime,
    nav: str | None,
    session_date: date,
) -> Json:
    unavailable: dict[str, Json] = {
        "status": "unavailable",
        "series_kind": "price_only_substitute",
        "reason": "SPY opening and same-session closing observations are unavailable",
    }
    decisions = [
        event
        for event in events
        if event.event_type == DECISION
        and event.timestamp <= as_of
        and thaw(event.payload).get("status") == "accepted"
    ]
    if not decisions or nav is None:
        return unavailable
    first_decision = min(event.timestamp for event in decisions)
    opening = packet.sessions[0].opened_at
    original_packet, original_mandate, *_rest = replay(events)
    pilot = PROSPECTIVE_SEAL_REQUIRED in original_mandate.acknowledgements
    starts = [
        item
        for item in packet.evidence
        if item.symbol == "SPY"
        and item.price_role == "trade"
        and (
            (
                pilot
                and item.evidence_id.startswith("alpaca:benchmark:")
                and item.observed_at > first_decision
                and item.available_at <= as_of
            )
            or (
                not pilot
                and item.observed_at == opening
                and item.available_at <= first_decision
            )
        )
        and item.price is not None
    ]
    ends = [
        item
        for item in packet.evidence
        if item.symbol == "SPY"
        and item.price_role == "close"
        and item.observed_at.date() == session_date
        and item.available_at <= as_of
        and item.observed_at <= as_of
        and item.price is not None
        and (not pilot or _valid_pilot_close(item, "SPY", original_packet))
    ]
    if len(starts) != 1 or not ends:
        return unavailable
    start = starts[0]
    end = max(ends, key=lambda item: (item.observed_at, item.available_at))
    if pilot:
        from drift.prospective.trade_identity import normalize_trade_id

        baseline_id = normalize_trade_id(
            start.evidence_id.removeprefix("alpaca:benchmark:")
        )
        if (
            baseline_id is None
            or baseline_id in _invalidated_trade_ids(packet, as_of)
            or not _valid_pilot_trade(
                start, original_packet, original_mandate, "SPY", benchmark=True
            )
        ):
            return unavailable
    same_feed = start.source_label == end.source_label or any(
        start.source_label == f"alpaca-trades-v2-{feed}"
        and end.source_label == f"alpaca-bars-v2-{feed}-raw"
        for feed in ("iex", "sip")
    )
    if not same_feed or start.price is None or end.price is None:
        return unavailable
    if pilot and (
        start.observed_at > end.observed_at
        or any(
            event.event_type == FILL
            and event.timestamp <= as_of
            and thaw(event.payload).get("status") == "filled"
            and (
                event.timestamp <= start.available_at
                or not any(
                    item.evidence_id == thaw(event.payload).get("price_evidence_id")
                    and item.observed_at >= start.observed_at
                    for item in packet.evidence
                )
            )
            for event in events
        )
    ):
        return unavailable
    from drift.prospective.config import NY

    if any(
        start.observed_at.astimezone(NY).date()
        < day
        <= end.observed_at.astimezone(NY).date()
        for day in _split_dates(packet, as_of).get("SPY", ())
    ):
        return {
            **unavailable,
            "reason": "SPY price series crosses an unadjusted split",
        }
    start_price, end_price = parse_money(start.price), parse_money(end.price)
    difference = _money_difference(end_price, start_price)
    if difference is None:
        return unavailable
    change = _return_ratio(difference, start_price)
    return {
        "status": "available",
        "series_kind": "price_only_substitute",
        "series_change": None if change is None else change[0],
        "portfolio_change": _portfolio_return(packet, nav),
        "start_evidence_id": start.evidence_id,
        "end_evidence_id": end.evidence_id,
        "source_label": start.source_label,
        "limitation": (
            "SPY price return; dividends are not credited to either side"
            + (
                "; benchmark begins after both first decisions while books were in cash"
                if pilot
                else ""
            )
        ),
    }


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
    if start.series_kind != end.series_kind:
        return {
            "portfolio_change": None,
            "reason": "benchmark points do not share one series kind",
            "series_kind": end.series_kind,
            "series_label": _SERIES_LABELS[end.series_kind],
            "status": "unavailable",
        }
    difference = _money_difference(parse_money(end.level), parse_money(start.level))
    series = (
        None
        if difference is None
        else _return_ratio(difference, parse_money(start.level))
    )
    portfolio = None
    if nav is not None:
        initial = parse_money(packet.portfolio_context.cash)
        difference = _money_difference(parse_money(nav), initial)
        if difference is not None:
            portfolio = _return_ratio(difference, initial)
    series_change = None if series is None else series[0]
    portfolio_change = None if portfolio is None else portfolio[0]
    status = (
        "available"
        if series_change is not None and portfolio_change is not None
        else ("series_only" if series_change is not None else "unavailable")
    )
    return {
        "end_level": end.level,
        "limitations": list[Json](end.limitations)
        + (
            ["portfolio dividends are not credited; total-return series includes them"]
            if end.series_kind == "sp500_total_return"
            else []
        ),
        "portfolio_change": portfolio_change,
        "portfolio_change_exact": None if portfolio is None else portfolio[1],
        "ratio_precision": RETURN_RATIO_PRECISION,
        "reason": (
            "supplied series comparison at the documented return-ratio "
            "precision, not an index calculation or an edge"
        ),
        "series_change": series_change,
        "series_change_exact": None if series is None else series[1],
        "series_kind": end.series_kind,
        "series_label": _SERIES_LABELS[end.series_kind],
        "start_level": start.level,
        "status": status,
    }


@decimal_context()
def _system_costs(events: tuple[AuditEvent, ...], as_of: datetime) -> Json:
    entries: list[Json] = []
    currencies: set[str] = set()
    missing = False
    total = Decimal("0")
    exact_total = Fraction(0)
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
        exact_total += Fraction(parse_money(amount))
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
    if Fraction(total) != exact_total:
        return {
            "amount": None,
            "entries": entries,
            "reason": (
                "attested costs cannot be summed exactly in the portfolio context"
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
