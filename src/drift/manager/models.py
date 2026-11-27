"""Inputs, mandate, and proposals for the offline portfolio cycle.

Money is canonical decimal text. Nothing in this module contacts a broker,
a data provider, or a model.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, UTCDateTime
from drift.domain.evaluator_portfolio import canonical_money

_MONEY = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}")

REQUIRED_PACKET_LIMITATIONS = (
    "declared sessions are a simulation calendar, not exchange session authority",
    "local supplied inputs are untrusted and are not source authentication",
)
REQUIRED_MANDATE_ACKNOWLEDGEMENTS = (
    "content hashes do not authenticate origin",
    "simulation-only; not a broker order or a market fill",
    "thresholds are test or local configuration, not an approved product mandate",
)
REQUIRED_CONTEXT_LIMITATIONS = (
    "opening book accepts declared cash only; existing positions are not imported",
)


def parse_money(value: str) -> Decimal:
    """Return the canonical Decimal for one nonnegative money string."""
    if not isinstance(value, str) or _MONEY.fullmatch(value) is None:
        message = "cash requires canonical nonnegative decimal text"
        raise ValueError(message)
    return canonical_money(Decimal(value))


def money_text(value: Decimal) -> str:
    """Spell a portfolio Decimal in canonical money text, including negatives."""
    spelled = canonical_money(value)
    return format(spelled, "f")


class Instrument(FrozenModel):
    """One locally declared instrument. The id is not a market listing proof."""

    symbol: NonBlankStr
    security_id: UUID7
    name: NonBlankStr

    @field_validator("symbol")
    @classmethod
    def require_symbol_shape(cls, value: str) -> str:
        if _SYMBOL.fullmatch(value) is None:
            message = "symbol must be 1 to 10 uppercase letters or digits"
            raise ValueError(message)
        return value


class SimulationSession(FrozenModel):
    """One declared simulation session. It is not an exchange session."""

    local_date: date
    opened_at: UTCDateTime
    closed_at: UTCDateTime

    @model_validator(mode="after")
    def require_same_utc_date(self) -> Self:
        if self.closed_at <= self.opened_at:
            message = "session close must follow open"
            raise ValueError(message)
        opened = self.opened_at.date()
        closed = self.closed_at.date()
        if opened != self.local_date or closed != self.local_date:
            message = "declared session timestamps must fall on their local date"
            raise ValueError(message)
        return self


class EvidenceItem(FrozenModel):
    """One untrusted local input. Its text is data, not an instruction."""

    evidence_id: NonBlankStr
    kind: Literal["fundamental", "observation", "news", "suggestion"]
    symbol: NonBlankStr
    observed_at: UTCDateTime
    available_at: UTCDateTime
    limitations: tuple[NonBlankStr, ...] = Field(min_length=1)
    summary: NonBlankStr
    source_label: NonBlankStr
    price: str | None = None
    price_role: Literal["close", "trade"] | None = None

    @field_validator("symbol")
    @classmethod
    def require_symbol_shape(cls, value: str) -> str:
        if _SYMBOL.fullmatch(value) is None:
            message = "symbol must be 1 to 10 uppercase letters or digits"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def require_observation_price(self) -> Self:
        if self.observed_at > self.available_at:
            message = "observed_at cannot follow available_at"
            raise ValueError(message)
        if self.kind == "observation":
            if self.price is None or self.price_role is None:
                message = "an observation requires a price and a price role"
                raise ValueError(message)
            parsed = parse_money(self.price)
            if parsed <= Decimal("0"):
                message = "an observation price must be strictly positive"
                raise ValueError(message)
            return self
        if self.price is not None or self.price_role is not None:
            message = "only an observation may carry a price"
            raise ValueError(message)
        return self


class PositionContext(FrozenModel):
    """A caller-claimed opening position. Importing one is refused."""

    symbol: NonBlankStr
    quantity: int = Field(ge=0)


class PortfolioContext(FrozenModel):
    """Caller-supplied opening context. It cannot override the ledger."""

    as_of: UTCDateTime
    cash: str
    positions: tuple[PositionContext, ...]
    limitations: tuple[NonBlankStr, ...] = Field(min_length=1)

    @field_validator("cash")
    @classmethod
    def require_cash(cls, value: str) -> str:
        parsed = parse_money(value)
        if parsed <= Decimal("0"):
            message = "opening cash must be strictly positive"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def require_cash_only_opening(self) -> Self:
        missing = [
            item
            for item in REQUIRED_CONTEXT_LIMITATIONS
            if item not in self.limitations
        ]
        if missing:
            message = f"portfolio context lacks limitations: {missing}"
            raise ValueError(message)
        if self.positions:
            message = (
                "opening context cannot import positions; cost basis would be invented"
            )
            raise ValueError(message)
        return self


class BenchmarkPoint(FrozenModel):
    """One supplied benchmark level. Absence is reported, not filled in.

    ``series_kind`` is a caller label. ``unspecified`` is not treated as
    S&P 500 total return. ``price_only_substitute`` is a price series, not
    a total-return index.
    """

    available_at: UTCDateTime
    level: str
    limitations: tuple[NonBlankStr, ...] = Field(min_length=1)
    series_kind: Literal[
        "unspecified",
        "sp500_total_return",
        "price_only_substitute",
    ] = "unspecified"

    @field_validator("level")
    @classmethod
    def require_level(cls, value: str) -> str:
        parsed = parse_money(value)
        if parsed <= Decimal("0"):
            message = "benchmark level must be strictly positive"
            raise ValueError(message)
        return value


class ResearchPacket(FrozenModel):
    """The local inputs available to one offline book."""

    schema_version: Literal["1"] = "1"
    instruments: tuple[Instrument, ...] = Field(min_length=1)
    sessions: tuple[SimulationSession, ...] = Field(min_length=1)
    evidence: tuple[EvidenceItem, ...] = Field(min_length=1)
    portfolio_context: PortfolioContext
    limitations: tuple[NonBlankStr, ...] = Field(min_length=1)
    benchmark: tuple[BenchmarkPoint, ...] = ()
    settlement_only_dates: tuple[date, ...] = ()

    @model_validator(mode="after")
    def require_consistent_packet(self) -> Self:
        missing = [
            item for item in REQUIRED_PACKET_LIMITATIONS if item not in self.limitations
        ]
        if missing:
            message = f"packet lacks limitations: {missing}"
            raise ValueError(message)
        symbols = tuple(item.symbol for item in self.instruments)
        if len(set(symbols)) != len(symbols):
            message = "instrument symbols must be unique"
            raise ValueError(message)
        security_ids = tuple(item.security_id for item in self.instruments)
        if len(set(security_ids)) != len(security_ids):
            message = "instrument ids must be unique"
            raise ValueError(message)
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            message = "evidence ids must be unique"
            raise ValueError(message)
        known = set(symbols)
        for item in self.evidence:
            if item.symbol not in known:
                message = f"evidence {item.evidence_id} names unknown symbol"
                raise ValueError(message)
        sessions = self.sessions
        for earlier, current in zip(sessions, sessions[1:], strict=False):
            if current.local_date <= earlier.local_date:
                message = "simulation sessions must have increasing local dates"
                raise ValueError(message)
            if current.opened_at < earlier.closed_at:
                message = "simulation sessions must not overlap"
                raise ValueError(message)
        first = sessions[0]
        context = self.portfolio_context
        if context.as_of != first.opened_at:
            message = "portfolio context as_of must match the first session open"
            raise ValueError(message)
        if context.cash != money_text(parse_money(context.cash)):
            message = "portfolio context cash must already be canonical"
            raise ValueError(message)
        times = tuple(point.available_at for point in self.benchmark)
        if len(set(times)) != len(times):
            message = "benchmark timestamps must be unique"
            raise ValueError(message)
        if tuple(sorted(times)) != times:
            message = "benchmark points must be in time order"
            raise ValueError(message)
        session_days = {item.local_date for item in self.sessions}
        unknown = [
            day.isoformat()
            for day in self.settlement_only_dates
            if day not in session_days
        ]
        if unknown:
            message = f"settlement dates are not sessions: {unknown}"
            raise ValueError(message)
        return self


class SimulationMandate(FrozenModel):
    """Caller-configured simulation limits. These are not a product mandate."""

    schema_version: Literal["1"] = "1"
    mode: Literal["simulation_only"]
    allowed_symbols: tuple[NonBlankStr, ...] = Field(min_length=1)
    max_position_notional_fraction: str
    min_cash_after: str
    max_evidence_age_hours: int = Field(gt=0)
    citation_policy: Literal["uniform_age", "research"] = "uniform_age"
    fill_fee: str
    fill_price_source: Literal[
        "cited_observation_price",
        "post_decision_execution",
    ]
    position_check: Literal["cost_basis_denominator"]
    whole_shares_only: Literal[True]
    acknowledgements: tuple[NonBlankStr, ...] = Field(min_length=1)

    @field_validator("allowed_symbols")
    @classmethod
    def require_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for symbol in value:
            if _SYMBOL.fullmatch(symbol) is None:
                message = "allowed symbol must be 1 to 10 uppercase letters or digits"
                raise ValueError(message)
        if len(set(value)) != len(value):
            message = "allowed symbols must be unique"
            raise ValueError(message)
        return tuple(sorted(value))

    @model_validator(mode="after")
    def require_explicit_limits(self) -> Self:
        missing = [
            item
            for item in REQUIRED_MANDATE_ACKNOWLEDGEMENTS
            if item not in self.acknowledgements
        ]
        if missing:
            message = f"mandate lacks acknowledgements: {missing}"
            raise ValueError(message)
        fraction = parse_money(self.max_position_notional_fraction)
        if fraction <= Decimal("0") or fraction > Decimal("1"):
            message = "max position fraction must be greater than 0 and at most 1"
            raise ValueError(message)
        parse_money(self.min_cash_after)
        parse_money(self.fill_fee)
        return self


class ExitCondition(FrozenModel):
    """A structured exit condition. Narrative text is not auto-traded."""

    kind: Literal["price_below", "price_above", "narrative"]
    threshold: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def require_shape(self) -> Self:
        if self.kind == "narrative":
            if (
                self.text is None
                or self.text.strip() == ""
                or self.threshold is not None
            ):
                message = "narrative exit condition needs text and no threshold"
                raise ValueError(message)
            return self
        if self.threshold is None or self.text is not None:
            message = "price exit condition needs a threshold and no text"
            raise ValueError(message)
        parsed = parse_money(self.threshold)
        if parsed <= Decimal("0"):
            message = "exit threshold must be strictly positive"
            raise ValueError(message)
        return self


class SystemCost(FrozenModel):
    """A cost the caller attests. Omission means unknown, not zero."""

    amount: str
    currency: NonBlankStr
    description: NonBlankStr

    @field_validator("currency")
    @classmethod
    def require_currency_code(cls, value: str) -> str:
        if len(value) != 3 or value != value.upper() or not value.isalpha():
            message = "currency must be a three-letter uppercase code"
            raise ValueError(message)
        return value

    @field_validator("amount")
    @classmethod
    def require_amount(cls, value: str) -> str:
        parse_money(value)
        return value


class InvestmentProposal(FrozenModel):
    """A structured proposal from a supervising agent or a scripted fixture."""

    schema_version: Literal["1"] = "1"
    proposal_id: UUID7
    as_of: UTCDateTime
    action: Literal["buy", "sell", "hold"]
    symbol: NonBlankStr
    quantity: int = Field(ge=0)
    thesis: NonBlankStr
    evidence_ids: tuple[NonBlankStr, ...] = ()
    uncertainty: NonBlankStr
    allocation_reasoning: NonBlankStr
    exit_conditions: tuple[ExitCondition, ...] = ()
    execution: Literal["simulation", "live"]
    inference: Literal["scripted", "native_supervised"]
    model_identity: str | None = None
    system_cost: SystemCost | None = None

    @field_validator("symbol")
    @classmethod
    def require_symbol_shape(cls, value: str) -> str:
        if _SYMBOL.fullmatch(value) is None:
            message = "symbol must be 1 to 10 uppercase letters or digits"
            raise ValueError(message)
        return value

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            message = "evidence ids must be unique"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def require_action_shape(self) -> Self:
        if self.action == "hold" and self.quantity != 0:
            message = "a hold proposal must use quantity 0"
            raise ValueError(message)
        if self.action != "hold" and self.quantity <= 0:
            message = "a buy or sell proposal requires a positive whole-share quantity"
            raise ValueError(message)
        abstaining = self.action == "hold" and not self.evidence_ids
        if self.action != "hold" and not self.evidence_ids:
            message = "a buy or sell proposal requires cited evidence"
            raise ValueError(message)
        if not abstaining and not self.exit_conditions:
            message = "a trade or a cited hold requires an exit condition"
            raise ValueError(message)
        if self.inference == "scripted" and self.model_identity is not None:
            message = "a scripted proposal cannot claim a model identity"
            raise ValueError(message)
        if self.inference == "native_supervised" and (
            self.model_identity is None or self.model_identity.strip() == ""
        ):
            message = "native supervised inference requires a model identity"
            raise ValueError(message)
        return self


class ReflectionRequest(FrozenModel):
    """An evidence note about a recorded decision. It does not trade."""

    schema_version: Literal["1"] = "1"
    reflection_id: UUID7
    proposal_id: UUID7
    as_of: UTCDateTime
    observation_evidence_id: NonBlankStr
    note: NonBlankStr


class FeedbackNote(FrozenModel):
    """Supervising-user feedback. It is untrusted text and does not trade."""

    schema_version: Literal["1"] = "1"
    feedback_id: UUID7
    proposal_id: UUID7
    as_of: UTCDateTime
    note: NonBlankStr


class IngestBatch(FrozenModel):
    """Evidence or benchmark points appended after the book is open.

    Every item in one batch shares one availability time. That time is the
    ledger timestamp, so earlier reviews cannot see the batch.
    """

    schema_version: Literal["1"] = "1"
    evidence: tuple[EvidenceItem, ...] = ()
    benchmark: tuple[BenchmarkPoint, ...] = ()

    @model_validator(mode="after")
    def require_one_availability_time(self) -> Self:
        if not self.evidence and not self.benchmark:
            message = "ingest batch is empty"
            raise ValueError(message)
        times = [item.available_at for item in self.evidence]
        times.extend(point.available_at for point in self.benchmark)
        if len(set(times)) != 1:
            message = "one ingest batch must share a single available_at"
            raise ValueError(message)
        return self

    @property
    def available_at(self) -> datetime:
        if self.evidence:
            return self.evidence[0].available_at
        return self.benchmark[0].available_at
