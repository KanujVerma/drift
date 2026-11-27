"""Build one prospective review from the evidence visible in its own book."""

from dataclasses import asdict
from datetime import date, datetime
from typing import cast

from drift.historical.replay import Json as ReplayJson
from drift.historical.replay import research_brief
from drift.manager.corporate_actions import split_date
from drift.prospective.config import NY, TRADING_SYMBOLS
from drift.research.book import (
    _close_point,
    _is_close,
    _retain_displayed,
    _visible_at,
)
from drift.research.compact import compact_evidence
from drift.research.screen import FactPoint, screen
from drift.research.universe import universe_by_symbol


def review_context(context: dict[str, object], as_of: datetime) -> dict[str, object]:
    """Keep decision memory while exposing a screened, citable evidence slice."""
    raw = context.get("evidence")
    if not isinstance(raw, list):
        raise ValueError("review context has no evidence list")
    evidence = [
        item for item in raw if isinstance(item, dict) and _visible_at(item, as_of)
    ]
    splits: dict[str, date] = {}
    for item in evidence:
        day = split_date(
            item.get("source_label"), item.get("evidence_id"), item.get("symbol")
        )
        symbol = item.get("symbol")
        if (
            day is not None
            and day <= as_of.astimezone(NY).date()
            and isinstance(symbol, str)
        ):
            splits[symbol] = max(day, splits.get(symbol, day))
    evidence = [
        item
        for item in evidence
        if item.get("price_role") != "close"
        or item.get("symbol") not in splits
        or datetime.fromisoformat(str(item["observed_at"])).astimezone(NY).date()
        >= splits[str(item["symbol"])]
    ]
    book = context.get("book")
    if not isinstance(book, dict):
        raise ValueError("review context has no portfolio book")
    holdings = book.get("holdings")
    held = (
        frozenset(
            item["symbol"]
            for item in holdings
            if isinstance(item, dict) and isinstance(item.get("symbol"), str)
        )
        if isinstance(holdings, list)
        else frozenset()
    )
    suggestions = frozenset(
        item["symbol"]
        for item in evidence
        if item.get("kind") == "suggestion" and isinstance(item.get("symbol"), str)
    )
    external_raw = context.get("external_suggestions")
    external = (
        [
            item
            for item in external_raw
            if isinstance(item, dict) and _visible_at(item, as_of)
        ]
        if isinstance(external_raw, list)
        else []
    )
    suggestions |= frozenset(
        item["symbol"] for item in external if isinstance(item.get("symbol"), str)
    )
    closes = [_close_point(item) for item in evidence if _is_close(item)]
    facts = [
        FactPoint(
            symbol=str(item["symbol"]),
            day=datetime.fromisoformat(str(item["observed_at"])).astimezone(NY).date(),
            summary=str(item["summary"]),
        )
        for item in evidence
        if item.get("kind") == "fundamental"
    ]
    rows = screen(
        closes,
        as_of=as_of.astimezone(NY).date(),
        universe=frozenset(universe_by_symbol()),
        authorized=frozenset(TRADING_SYMBOLS),
        holdings=held,
        suggestions=suggestions,
        facts=facts,
    )
    deep = frozenset(
        row.symbol for row in rows if row.shortlisted or row.trading_authorized
    )
    eligible = frozenset(row.symbol for row in rows if row.research_eligible)
    compact = compact_evidence(evidence, symbols=eligible, deep=deep, as_of=as_of)
    compact = _retain_displayed(compact, evidence, rows)
    memories: list[dict[str, object]] = []
    decisions = context.get("decisions")
    for decision in decisions if isinstance(decisions, list) else []:
        if not isinstance(decision, dict) or decision.get("status") != "accepted":
            continue
        stamp, symbol, identifier = (
            decision.get("as_of"),
            decision.get("symbol"),
            decision.get("outcome_id"),
        )
        if not all(isinstance(value, str) for value in (stamp, symbol, identifier)):
            continue
        assert isinstance(stamp, str)
        decision_time = datetime.fromisoformat(stamp)
        later = [
            item
            for item in evidence
            if item.get("symbol") == symbol
            and _is_close(item)
            and datetime.fromisoformat(str(item["observed_at"])) > decision_time
            and (
                symbol not in splits
                or decision_time.astimezone(NY).date() >= splits[str(symbol)]
            )
        ]
        if not later:
            continue
        outcome = max(
            later, key=lambda item: (str(item["observed_at"]), str(item["evidence_id"]))
        )
        memories.append(
            {
                "decision_id": identifier,
                "symbol": symbol,
                "evidence_id": outcome["evidence_id"],
                "price": outcome["price"],
                "observed_at": outcome["observed_at"],
            }
        )
        if not any(
            item.get("evidence_id") == outcome["evidence_id"] for item in compact
        ):
            compact.append(outcome)
    ids = frozenset(str(item["evidence_id"]) for item in compact)
    research_context = dict(context)
    research_context["evidence"] = evidence
    brief = research_brief(cast(ReplayJson, research_context), as_of, citable_ids=ids)
    result = dict(context)
    result["evidence"] = compact
    result["screen"] = [asdict(row) for row in rows]
    result["research"] = brief
    result["external_suggestions"] = external
    result["unadjusted_splits"] = {
        symbol: day.isoformat() for symbol, day in splits.items()
    }
    result["outcome_observations"] = memories
    result["escalations"] = [
        {
            "symbol": symbol,
            "reason": "outside simulated trading authorization",
            "evidence_ids": sorted(
                str(item["evidence_id"])
                for item in (*evidence, *external)
                if item.get("symbol") == symbol
                and item.get("kind") == "suggestion"
                and isinstance(item.get("evidence_id"), str)
            ),
        }
        for symbol in sorted(suggestions - frozenset(TRADING_SYMBOLS))
    ]
    return result
