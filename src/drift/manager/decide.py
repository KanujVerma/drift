"""Deterministic proposal checks. Model text cannot change the mandate."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from drift.domain.evaluator_portfolio import decimal_context
from drift.manager.models import (
    EvidenceItem,
    InvestmentProposal,
    ResearchPacket,
    SimulationMandate,
    parse_money,
)

DecisionStatus = Literal["accepted", "rejected", "escalated"]

SUPPORTING_KINDS = frozenset({"fundamental", "observation", "news"})


class RecordedOutcome:
    """A prior decision the ledger can cite. It is not new research."""

    def __init__(self, *, outcome_id: str, symbol: str, available_at: datetime) -> None:
        self.outcome_id = outcome_id
        self.symbol = symbol
        self.available_at = available_at


class Decision:
    """The validator's answer. A fill price is set only when the trade may run."""

    def __init__(
        self,
        *,
        status: DecisionStatus,
        reasons: tuple[str, ...],
        fill_price: str | None,
        price_evidence_id: str | None,
    ) -> None:
        self.status = status
        self.reasons = reasons
        self.fill_price = fill_price
        self.price_evidence_id = price_evidence_id


def citation_time(observed: datetime, available: datetime) -> datetime:
    """Age from the earlier clock. A later availability time cannot refresh it."""
    if observed <= available:
        return observed
    return available


def _within_age(as_of: datetime, available_at: datetime, hours: int) -> bool:
    return as_of - available_at <= timedelta(hours=hours)


def _exact_product(left: Decimal, right: Decimal) -> Decimal | None:
    with decimal_context():
        product = left * right
    if Fraction(product) != Fraction(left) * Fraction(right):
        return None
    return product


def _exact_add(left: Decimal, right: Decimal) -> Decimal | None:
    with decimal_context():
        total = left + right
    if Fraction(total) != Fraction(left) + Fraction(right):
        return None
    return total


def _exact_sub(left: Decimal, right: Decimal) -> Decimal | None:
    with decimal_context():
        total = left - right
    if Fraction(total) != Fraction(left) - Fraction(right):
        return None
    return total


def fill_limit_reasons(
    *,
    action: Literal["buy", "sell"],
    symbol: str,
    quantity: int,
    fill_price: str,
    mandate: SimulationMandate,
    cash: Decimal,
    cost_basis_by_symbol: Mapping[str, Decimal],
    quantity_by_symbol: Mapping[str, int],
) -> tuple[str, ...]:
    """Cash, position, and oversell checks for one known execution price."""
    reasons: list[str] = []
    price = parse_money(fill_price)
    fee = parse_money(mandate.fill_fee)
    if action == "buy":
        gross = _exact_product(price, Decimal(quantity))
        notional = None if gross is None else _exact_add(gross, fee)
        if notional is None:
            reasons.append(
                "unsafe_position_limit: proposed notional is not exact "
                "in the portfolio decimal context"
            )
        else:
            denominator: Decimal | None = cash
            for basis in cost_basis_by_symbol.values():
                if denominator is None:
                    break
                denominator = _exact_add(denominator, basis)
            existing = cost_basis_by_symbol.get(symbol, Decimal("0"))
            projected = _exact_add(existing, notional)
            if denominator is None or projected is None:
                reasons.append(
                    "unsafe_position_limit: position limit is not exact "
                    "in the portfolio decimal context"
                )
            else:
                limit = _exact_product(
                    parse_money(mandate.max_position_notional_fraction),
                    denominator,
                )
                if limit is None:
                    reasons.append(
                        "unsafe_position_limit: position limit is not exact "
                        "in the portfolio decimal context"
                    )
                elif projected > limit:
                    reasons.append(
                        "unsafe_position_limit: proposed position notional "
                        f"{notional} exceeds "
                        f"{mandate.max_position_notional_fraction} "
                        f"of the cost-basis denominator {denominator}"
                    )
            remaining = None if notional is None else _exact_sub(cash, notional)
            if remaining is None:
                reasons.append(
                    "unsafe_cash: cash after the fill is not exact "
                    "in the portfolio decimal context"
                )
            elif remaining < parse_money(mandate.min_cash_after):
                reasons.append(
                    "unsafe_cash: the fill would leave less cash than "
                    f"{mandate.min_cash_after}"
                )
    else:
        held = quantity_by_symbol.get(symbol, 0)
        if quantity > held:
            reasons.append(
                f"unsafe_oversell: sell quantity {quantity} exceeds "
                f"held quantity {held}"
            )
        else:
            proceeds = _exact_product(price, Decimal(quantity))
            net = None if proceeds is None else _exact_sub(proceeds, fee)
            remaining = None if net is None else _exact_add(cash, net)
            if proceeds is None or remaining is None:
                reasons.append(
                    "unsafe_cash: sale proceeds are not exact in the "
                    "portfolio decimal context"
                )
            elif remaining < parse_money(mandate.min_cash_after):
                reasons.append(
                    "unsafe_cash: the sale would leave less cash than "
                    f"{mandate.min_cash_after}"
                )
    return tuple(reasons)


def decide_proposal(
    *,
    proposal: InvestmentProposal,
    packet: ResearchPacket,
    mandate: SimulationMandate,
    cash: Decimal,
    cost_basis_by_symbol: Mapping[str, Decimal],
    quantity_by_symbol: Mapping[str, int],
    outcomes: Mapping[str, RecordedOutcome],
    current_session: datetime,
    session_date_ok: bool,
    session_in_future: bool,
    defer_execution: bool = False,
) -> Decision:
    """Accept, reject, or escalate one proposal without mutating the book."""
    reasons: list[str] = []
    escalate = False
    if not session_date_ok:
        if session_in_future:
            reasons.append(
                "decision_outside_session: as_of is outside the declared "
                "simulation calendar"
            )
        else:
            reasons.append(
                "decision_before_current_session: as_of is before the book session"
            )
    if proposal.as_of < current_session:
        reasons.append(
            "decision_before_recorded_state: as_of is before the latest book time"
        )
    if proposal.execution == "live":
        escalate = True
        reasons.append(
            "escalated_live_execution: live execution is outside the "
            "simulation-only mandate"
        )
    known = {item.symbol for item in packet.instruments}
    if proposal.symbol not in known:
        reasons.append(
            f"unknown_symbol: {proposal.symbol} is not in the supplied packet"
        )
    elif proposal.symbol not in mandate.allowed_symbols:
        escalate = True
        reasons.append(
            "escalated_symbol_outside_mandate: "
            f"{proposal.symbol} is outside the configured simulation mandate"
        )

    evidence = {item.evidence_id: item for item in packet.evidence}
    cited_items: list[EvidenceItem] = []
    cited_outcomes: list[RecordedOutcome] = []
    for evidence_id in proposal.evidence_ids:
        item = evidence.get(evidence_id)
        outcome = outcomes.get(evidence_id)
        if item is None and outcome is None:
            reasons.append(
                f"missing_evidence: {evidence_id} does not resolve to supplied "
                "evidence or a recorded outcome"
            )
            continue
        if item is not None:
            if item.symbol != proposal.symbol:
                reasons.append(
                    "unsupported_evidence: "
                    f"{evidence_id} is about {item.symbol}, not {proposal.symbol}"
                )
                continue
            if item.available_at > proposal.as_of or item.observed_at > proposal.as_of:
                reasons.append(
                    "evidence_not_yet_available: "
                    f"{evidence_id} is later than the decision time"
                )
                continue
            if not _within_age(
                proposal.as_of,
                citation_time(item.observed_at, item.available_at),
                mandate.max_evidence_age_hours,
            ):
                reasons.append(
                    f"stale_evidence: {evidence_id} is older than the configured age"
                )
                continue
            cited_items.append(item)
        if outcome is not None:
            if outcome.symbol != proposal.symbol:
                reasons.append(
                    "unsupported_evidence: "
                    f"{evidence_id} records {outcome.symbol}, not {proposal.symbol}"
                )
                continue
            if outcome.available_at > proposal.as_of:
                reasons.append(
                    "evidence_not_yet_available: "
                    f"{evidence_id} is later than the decision time"
                )
                continue
            if not _within_age(
                proposal.as_of, outcome.available_at, mandate.max_evidence_age_hours
            ):
                reasons.append(
                    f"stale_evidence: {evidence_id} is older than the configured age"
                )
                continue
            cited_outcomes.append(outcome)

    supporting = [item for item in cited_items if item.kind in SUPPORTING_KINDS]
    abstaining = proposal.action == "hold" and not proposal.evidence_ids
    if proposal.action == "buy" and not supporting:
        reasons.append(
            "unsupported_evidence: a buy needs cited fundamental, observation, "
            "or news evidence for the symbol"
        )
    if (
        not abstaining
        and proposal.action != "buy"
        and not supporting
        and not cited_outcomes
    ):
        reasons.append(
            "unsupported_evidence: the proposal has no supporting evidence "
            "for the symbol"
        )

    fill_price: str | None = None
    price_evidence_id: str | None = None
    if proposal.action in ("buy", "sell") and not defer_execution:
        priced = [item for item in cited_items if item.price is not None]
        prices = {item.price for item in priced}
        if len(prices) > 1:
            reasons.append("unsupported_evidence: cited observation prices disagree")
        elif not priced:
            reasons.append(
                "unsupported_evidence: no cited observation price is available "
                "for the fill"
            )
        else:
            chosen = sorted(
                priced, key=lambda item: (item.available_at, item.evidence_id)
            )[-1]
            fill_price = chosen.price
            price_evidence_id = chosen.evidence_id

    if (
        not defer_execution
        and proposal.action in ("buy", "sell")
        and fill_price is not None
    ):
        reasons.extend(
            fill_limit_reasons(
                action=proposal.action,
                symbol=proposal.symbol,
                quantity=proposal.quantity,
                fill_price=fill_price,
                mandate=mandate,
                cash=cash,
                cost_basis_by_symbol=cost_basis_by_symbol,
                quantity_by_symbol=quantity_by_symbol,
            )
        )
    elif proposal.action == "sell":
        held = quantity_by_symbol.get(proposal.symbol, 0)
        if proposal.quantity > held:
            reasons.append(
                f"unsafe_oversell: sell quantity {proposal.quantity} exceeds "
                f"held quantity {held}"
            )

    reject_prefixes = (
        "decision_",
        "unknown_symbol:",
        "missing_evidence:",
        "unsupported_evidence:",
        "evidence_not_yet_available:",
        "stale_evidence:",
        "unsafe_",
    )
    rejected = any(reason.startswith(reject_prefixes) for reason in reasons)
    if rejected:
        status: DecisionStatus = "rejected"
    elif escalate:
        status = "escalated"
    else:
        status = "accepted"
        if abstaining:
            reasons.append(
                "abstained: no cited evidence, so the cycle takes no simulated action"
            )
        elif not reasons:
            reasons.append("accepted: proposal is inside the simulation mandate")
    if status != "accepted":
        fill_price = None
        price_evidence_id = None
    return Decision(
        status=status,
        reasons=tuple(reasons),
        fill_price=fill_price,
        price_evidence_id=price_evidence_id,
    )
