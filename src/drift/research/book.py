"""Build an isolated discovery book from prices and text the caller already has.

Nothing here fetches data or writes a prospective ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

from drift.historical.replay import Json as ReplayJson
from drift.historical.replay import (
    close_time,
    decision_time,
    historical_session,
    open_time,
    render_decision_prompt,
    research_brief,
)
from drift.historical.sources import PriceBar, TextInput
from drift.manager.models import (
    REQUIRED_CONTEXT_LIMITATIONS,
    REQUIRED_PACKET_LIMITATIONS,
    BenchmarkPoint,
    EvidenceItem,
    Instrument,
    PortfolioContext,
    ResearchPacket,
    SimulationMandate,
)
from drift.memory.recorder import deterministic_memory_uuid7
from drift.prospective.collect import UserSuggestion
from drift.prospective.config import MODELS, mandate
from drift.research.compact import compact_evidence, follow_ups, size_report
from drift.research.prompt import render_discovery_prompt
from drift.research.screen import (
    MIN_MEDIAN_DOLLAR_VOLUME,
    SHORTLIST_LIMIT,
    ClosePoint,
    FactPoint,
    ScreenRow,
    screen,
)
from drift.research.universe import (
    ORIGINAL_TRADING_SYMBOLS,
    ResearchName,
    universe_by_symbol,
)


@dataclass(frozen=True)
class DiscoveryBook:
    """The packet, the prompts, and the cache behind them."""

    packet: ResearchPacket
    mandate: SimulationMandate
    decision_day: date
    settlement_day: date
    review_day: date
    as_of: datetime
    rows: tuple[ScreenRow, ...]
    proposal_ids: dict[str, str]
    prompts: dict[str, str]
    baseline_prompts: dict[str, str]
    measurement: dict[str, int | str]
    follow_ups: tuple[str, ...]
    cache: tuple[dict[str, object], ...]
    gaps: tuple[str, ...]


def choose_sessions(
    bars: tuple[PriceBar, ...] | list[PriceBar],
    symbols: tuple[str, ...] = (),
) -> tuple[date, date]:
    """Last two observed market days. A missing research bar does not skip one.

    ``symbols`` is unused. The calendar is every date that has a bar, so one
    name's gap cannot pair a decision with a later fill across a real session.
    A name with no open on the fill day is left unfilled.
    """
    del symbols
    days = sorted({bar.day for bar in bars})
    if len(days) < 2:
        message = "discovery needs two market sessions to decide and settle"
        raise ValueError(message)
    return days[-2], days[-1]


def later_weekday(day: date) -> date:
    """The next weekday after ``day``. It can host a later review."""
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def assemble_book(
    bars: tuple[PriceBar, ...] | list[PriceBar],
    texts: tuple[TextInput, ...] | list[TextInput],
    *,
    suggestions: tuple[UserSuggestion, ...] = (),
    holdings: frozenset[str] = frozenset(),
    price_limitation: str,
    decision_day: date,
    settlement_day: date,
    authorized: tuple[str, ...] = ORIGINAL_TRADING_SYMBOLS,
    gaps: tuple[str, ...] = (),
    min_dollar_volume: Decimal | None = None,
    shortlist_limit: int | None = None,
) -> DiscoveryBook:
    """Screen through the decision day and keep the next open for a later fill."""
    names = universe_by_symbol()
    as_of = decision_time(decision_day)
    visible_texts = [
        item
        for item in texts
        if item.observed_at <= as_of
        and (item.available_at is None or item.available_at <= as_of)
    ]
    visible_suggestions = tuple(
        item for item in suggestions if item.observed_at <= as_of
    )
    cache = _cache_rows(
        bars,
        _limit_texts(visible_texts),
        visible_suggestions,
        price_limitation,
        decision_day,
    )
    closes = tuple(_close_point(item) for item in cache if _is_close(item))
    facts = tuple(
        FactPoint(
            symbol=str(item["symbol"]),
            day=_day(item),
            summary=str(item["summary"]),
        )
        for item in cache
        if item.get("kind") == "fundamental"
    )
    rows = screen(
        closes,
        as_of=decision_day,
        universe=frozenset(names),
        authorized=frozenset(authorized),
        holdings=holdings,
        suggestions=frozenset(item.symbol for item in visible_suggestions),
        facts=facts,
        min_dollar_volume=(
            MIN_MEDIAN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
        ),
        shortlist_limit=SHORTLIST_LIMIT if shortlist_limit is None else shortlist_limit,
    )
    deep = frozenset(
        row.symbol
        for row in rows
        if row.shortlisted or row.trading_authorized or row.symbol in holdings
    )
    symbols = frozenset(row.symbol for row in rows if row.research_eligible)
    compact = compact_evidence(cache, symbols=symbols, deep=deep, as_of=as_of)
    kinds = {item.symbol: item.kind for item in names.values()}
    missing = follow_ups(cache, deep=deep, kinds=kinds, as_of=as_of)
    brief_context = _context(cache, as_of)
    brief = research_brief(cast(ReplayJson, brief_context), as_of, policy="research")
    shown = _context(compact, as_of)
    proposal_ids = {
        model: str(
            deterministic_memory_uuid7(f"discovery:{decision_day.isoformat()}:{model}")
        )
        for model in ("terra", "sol")
    }
    prompts = {
        model: render_discovery_prompt(
            identity=MODELS[model],
            proposal_id=proposal_ids[model],
            as_of=as_of.isoformat(),
            brief=brief,
            rows=rows,
            context=shown,
            follow_ups=missing,
        )
        for model in ("terra", "sol")
    }
    baseline_evidence = [
        item
        for item in cache
        if item.get("symbol") in set(ORIGINAL_TRADING_SYMBOLS)
        and _visible_at(item, as_of)
    ]
    baseline_context = _context(baseline_evidence, as_of)
    baseline_brief = research_brief(
        cast(ReplayJson, baseline_context), as_of, policy="research"
    )
    baseline_json = json.dumps(baseline_context, indent=2, sort_keys=True)
    baseline_prompts = {
        model: render_decision_prompt(
            identity=MODELS[model],
            proposal_id=str(
                deterministic_memory_uuid7(
                    f"discovery-baseline:{decision_day.isoformat()}:{model}"
                )
            ),
            as_of=as_of.isoformat(),
            memory_line=(
                "Decision text was omitted. Do not invent a prior thesis. "
                "Positions are the book."
            ),
            brief=baseline_brief,
            context_json=baseline_json,
            policy="research",
        )
        for model in ("terra", "sol")
    }
    measurement = size_report(baseline_prompts["terra"], prompts["terra"])
    packet = _packet(
        names=names,
        suggestions=visible_suggestions,
        compact=compact,
        bars=bars,
        decision_day=decision_day,
        settlement_day=settlement_day,
        price_limitation=price_limitation,
        authorized=authorized,
        deep=deep,
    )
    rules = discovery_mandate(authorized)
    return DiscoveryBook(
        packet=packet,
        mandate=rules,
        decision_day=decision_day,
        settlement_day=settlement_day,
        review_day=later_weekday(settlement_day),
        as_of=as_of,
        rows=rows,
        proposal_ids=proposal_ids,
        prompts=prompts,
        baseline_prompts=baseline_prompts,
        measurement=measurement,
        follow_ups=missing,
        cache=tuple(cache),
        gaps=gaps,
    )


def review_prompts(
    cache: list[dict[str, object]],
    *,
    cash: str,
    quantities: dict[str, int],
    review_day: date,
    authorized: tuple[str, ...] = ORIGINAL_TRADING_SYMBOLS,
    min_dollar_volume: Decimal | None = None,
    shortlist_limit: int | None = None,
) -> tuple[dict[str, str], dict[str, str], tuple[ScreenRow, ...]]:
    """Prompt a later session from shares the ledger already holds."""
    names = universe_by_symbol()
    as_of = decision_time(review_day)
    visible = [item for item in cache if _visible_at(item, as_of)]
    closes = tuple(_close_point(item) for item in visible if _is_close(item))
    facts = tuple(
        FactPoint(
            symbol=str(item["symbol"]),
            day=_day(item),
            summary=str(item["summary"]),
        )
        for item in visible
        if item.get("kind") == "fundamental"
    )
    held = frozenset(symbol for symbol, qty in quantities.items() if qty > 0)
    rows = screen(
        closes,
        as_of=review_day,
        universe=frozenset(names),
        authorized=frozenset(authorized),
        holdings=held,
        facts=facts,
        min_dollar_volume=(
            MIN_MEDIAN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
        ),
        shortlist_limit=SHORTLIST_LIMIT if shortlist_limit is None else shortlist_limit,
    )
    deep = frozenset(
        row.symbol
        for row in rows
        if row.shortlisted or row.trading_authorized or row.symbol in held
    )
    symbols = frozenset(row.symbol for row in rows if row.research_eligible)
    compact = compact_evidence(visible, symbols=symbols, deep=deep, as_of=as_of)
    shown = _context(compact, as_of, cash=cash, quantities=quantities)
    brief = research_brief(
        cast(ReplayJson, _context(visible, as_of, cash=cash, quantities=quantities)),
        as_of,
        policy="research",
    )
    proposal_ids = {
        model: str(
            deterministic_memory_uuid7(
                f"discovery-review:{review_day.isoformat()}:{model}"
            )
        )
        for model in ("terra", "sol")
    }
    prompts = {
        model: render_discovery_prompt(
            identity=MODELS[model],
            proposal_id=proposal_ids[model],
            as_of=as_of.isoformat(),
            brief=brief,
            rows=rows,
            context=shown,
            follow_ups=(),
        )
        for model in ("terra", "sol")
    }
    return prompts, proposal_ids, rows


def discovery_mandate(authorized: tuple[str, ...]) -> SimulationMandate:
    """Local test limits. Research membership is not copied into this list."""
    base = mandate()
    notes = base.acknowledgements + (
        "discovery research membership is not trading authorization",
        "the discovery ledger is isolated from the prospective books",
        "screening does not authorize a trade",
        "research citations follow the evidence class",
    )
    return base.model_copy(
        update={
            "acknowledgements": notes,
            "allowed_symbols": authorized,
            "citation_policy": "research",
        }
    )


def _packet(
    *,
    names: dict[str, ResearchName],
    suggestions: tuple[UserSuggestion, ...],
    compact: list[dict[str, object]],
    bars: tuple[PriceBar, ...] | list[PriceBar],
    decision_day: date,
    settlement_day: date,
    price_limitation: str,
    authorized: tuple[str, ...],
    deep: frozenset[str],
) -> ResearchPacket:
    symbols = set(authorized) | set(deep)
    for row in compact:
        symbol = row.get("symbol")
        if isinstance(symbol, str):
            symbols.add(symbol)
    instruments = []
    for symbol in sorted(symbols):
        described = names.get(symbol)
        label = described.name if described is not None else symbol
        instruments.append(
            Instrument(
                symbol=symbol,
                security_id=deterministic_memory_uuid7(f"discovery-research:{symbol}"),
                name=label,
            )
        )
    for suggestion in suggestions:
        if suggestion.symbol not in symbols:
            instruments.append(
                Instrument(
                    symbol=suggestion.symbol,
                    security_id=deterministic_memory_uuid7(
                        f"discovery-research:{suggestion.symbol}"
                    ),
                    name=suggestion.symbol,
                )
            )
            symbols.add(suggestion.symbol)
    evidence = [_item(row) for row in compact]
    evidence.extend(
        _trade_opens(
            bars,
            settlement_day,
            price_limitation,
            frozenset(authorized) | deep,
        )
    )
    opened = open_time(decision_day)
    spy = _spy_level(bars, decision_day)
    benchmark: tuple[BenchmarkPoint, ...] = ()
    if spy is not None:
        benchmark = (
            BenchmarkPoint(
                available_at=close_time(decision_day),
                level=spy,
                limitations=(
                    "SPY close is a price-only substitute, not S&P 500 total return",
                ),
                series_kind="price_only_substitute",
            ),
        )
    return ResearchPacket(
        instruments=tuple(instruments),
        sessions=(
            historical_session(decision_day),
            historical_session(settlement_day),
            historical_session(later_weekday(settlement_day)),
        ),
        evidence=tuple(evidence),
        portfolio_context=PortfolioContext(
            as_of=opened,
            cash="10000",
            positions=(),
            limitations=REQUIRED_CONTEXT_LIMITATIONS,
        ),
        limitations=REQUIRED_PACKET_LIMITATIONS
        + (
            "discovery sessions are not the prospective observation calendar",
            "source gaps are recorded beside the collection and are not invented",
            price_limitation,
            "X posts were not collected",
        ),
        benchmark=benchmark,
        settlement_only_dates=(settlement_day,),
    )


def _limit_texts(
    texts: tuple[TextInput, ...] | list[TextInput],
) -> list[TextInput]:
    """Keep the two newest rows of each statement concept. Filings stay."""
    grouped: dict[tuple[str, str], list[TextInput]] = {}
    other: list[TextInput] = []
    for item in texts:
        if item.kind != "fundamental":
            other.append(item)
            continue
        parts = item.evidence_id.split(":")
        concept = parts[3] if len(parts) > 3 and parts[0] == "sec" else item.evidence_id
        grouped.setdefault((item.symbol, concept), []).append(item)
    kept = list(other)
    for rows in grouped.values():
        rows.sort(key=lambda item: item.observed_at)
        kept.extend(rows[-2:])
    return kept


def _cache_rows(
    bars: tuple[PriceBar, ...] | list[PriceBar],
    texts: tuple[TextInput, ...] | list[TextInput],
    suggestions: tuple[UserSuggestion, ...],
    price_limitation: str,
    decision_day: date,
) -> list[dict[str, object]]:
    as_of = decision_time(decision_day)
    rows: list[dict[str, object]] = []
    for bar in bars:
        if bar.day > decision_day:
            continue
        rows.append(_bar_row(bar, price_limitation))
    for text in texts:
        available = text.observed_at if text.available_at is None else text.available_at
        if text.observed_at > as_of or available > as_of:
            continue
        rows.append(_text_row(text, available))
    for item in suggestions:
        if item.observed_at > as_of:
            continue
        rows.append(
            {
                "available_at": item.observed_at.isoformat(),
                "evidence_id": (
                    f"suggestion:{item.symbol}:{item.observed_at.isoformat()}"
                ),
                "kind": "suggestion",
                "limitations": [
                    "user suggestion; not market evidence; not a trade signal"
                ],
                "observed_at": item.observed_at.isoformat(),
                "price": None,
                "price_role": None,
                "source_label": "user-suggestion",
                "summary": item.summary,
                "symbol": item.symbol,
            }
        )
    return rows


def _bar_row(bar: PriceBar, price_limitation: str) -> dict[str, object]:
    when = close_time(bar.day)
    volume = ""
    if bar.volume is not None:
        volume = f" Volume {bar.volume}."
    return {
        "available_at": when.isoformat(),
        "evidence_id": (
            f"discovery:{bar.source_label}:{bar.symbol}:close:{bar.day.isoformat()}"
        ),
        "kind": "observation",
        "limitations": [price_limitation],
        "observed_at": when.isoformat(),
        "price": bar.close_price,
        "price_role": "close",
        "source_label": bar.source_label,
        "summary": f"Daily close {bar.close_price} for {bar.symbol}.{volume}",
        "symbol": bar.symbol,
    }


def _text_row(text: TextInput, available: datetime) -> dict[str, object]:
    return {
        "available_at": available.isoformat(),
        "evidence_id": text.evidence_id,
        "kind": text.kind,
        "limitations": list(text.limitations),
        "observed_at": text.observed_at.isoformat(),
        "price": None,
        "price_role": None,
        "source_label": text.source_label,
        "summary": text.summary,
        "symbol": text.symbol,
    }


def _trade_opens(
    bars: tuple[PriceBar, ...] | list[PriceBar],
    day: date,
    price_limitation: str,
    symbols: frozenset[str],
) -> list[EvidenceItem]:
    found: list[EvidenceItem] = []
    seen: set[str] = set()
    when = open_time(day)
    for bar in bars:
        if bar.symbol not in symbols or bar.day != day or bar.symbol in seen:
            continue
        seen.add(bar.symbol)
        found.append(
            EvidenceItem.model_validate(
                {
                    "evidence_id": (
                        f"discovery:{bar.source_label}:{bar.symbol}:trade:"
                        f"{day.isoformat()}"
                    ),
                    "kind": "observation",
                    "symbol": bar.symbol,
                    "observed_at": when,
                    "available_at": when,
                    "limitations": (price_limitation,),
                    "summary": f"Daily open {bar.open_price} for {bar.symbol}.",
                    "source_label": bar.source_label,
                    "price": bar.open_price,
                    "price_role": "trade",
                }
            )
        )
    return found


def _item(row: dict[str, object]) -> EvidenceItem:
    payload = dict(row)
    for key in ("observed_at", "available_at"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = datetime.fromisoformat(value)
    limits = payload.get("limitations")
    if isinstance(limits, list):
        payload["limitations"] = tuple(limits)
    return EvidenceItem.model_validate(payload)


def _context(
    evidence: list[dict[str, object]],
    as_of: datetime,
    *,
    cash: str = "10000",
    quantities: dict[str, int] | None = None,
) -> dict[str, object]:
    visible = [item for item in evidence if _visible_at(item, as_of)]
    held = quantities or {}
    return {
        "as_of": as_of.isoformat(),
        "book": {
            "cash": cash,
            "holdings": [
                {"quantity": str(qty), "symbol": symbol}
                for symbol, qty in sorted(held.items())
                if qty > 0
            ],
        },
        "evidence": visible,
        "untrusted_text": True,
    }


def _visible_at(item: dict[str, object], as_of: datetime) -> bool:
    available = item.get("available_at")
    observed = item.get("observed_at")
    if not isinstance(available, str):
        return False
    if datetime.fromisoformat(available) > as_of:
        return False
    return not isinstance(observed, str) or datetime.fromisoformat(observed) <= as_of


def _is_close(item: dict[str, object]) -> bool:
    return item.get("price_role") == "close" and isinstance(item.get("price"), str)


def _close_point(item: dict[str, object]) -> ClosePoint:
    evidence_id = str(item["evidence_id"])
    day_text = evidence_id.rsplit(":", 1)[-1]
    volume = _volume(str(item.get("summary")))
    return ClosePoint(
        symbol=str(item["symbol"]),
        day=date.fromisoformat(day_text),
        close=Decimal(str(item["price"])),
        volume=volume,
        evidence_id=evidence_id,
    )


def _day(item: dict[str, object]) -> date:
    observed = str(item["observed_at"])
    return datetime.fromisoformat(observed).date()


def _volume(summary: str) -> Decimal | None:
    marker = " Volume "
    if marker not in summary:
        return None
    raw = summary.rsplit(marker, 1)[1]
    if raw.endswith("."):
        raw = raw[:-1]
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _spy_level(bars: tuple[PriceBar, ...] | list[PriceBar], day: date) -> str | None:
    for bar in bars:
        if bar.symbol == "SPY" and bar.day == day:
            return bar.close_price
    return None
