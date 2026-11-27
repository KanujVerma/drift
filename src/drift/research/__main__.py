"""Prepare an isolated discovery review.

``python -m drift.research --help``

The process does not call a model and does not write the prospective books.
A supervisor supplies a native proposal file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from drift.errors import LedgerIntegrityError
from drift.historical.replay import (
    _json_object,
    assert_isolated,
    historical_session,
    normalize_proposal_json,
)
from drift.historical.sources import PriceBar
from drift.manager.models import InvestmentProposal
from drift.manager.service import ManagerError, PortfolioManager
from drift.prospective.collect import UserSuggestion, load_suggestions
from drift.prospective.config import MODELS
from drift.research.book import DiscoveryBook, assemble_book, choose_sessions
from drift.research.collect import (
    PRICE_START,
    collect_excerpts,
    collect_news,
    collect_prices,
    collect_statements,
    price_end,
    x_gap,
)
from drift.research.compact import (
    cited_ids_missing,
    compact_evidence,
    size_report,
)
from drift.research.screen import ClosePoint, screen
from drift.research.universe import (
    ORIGINAL_TRADING_SYMBOLS,
    RESEARCH_UNIVERSE,
    universe_by_symbol,
)

DEFAULT_STATE = Path(".local-artifacts/discovery")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m drift.research")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("prepare", help="collect, screen, and open an isolated book")
    propose = sub.add_parser("propose", help="record one supervised proposal")
    propose.add_argument("--model", choices=("terra", "sol"), required=True)
    propose.add_argument("--proposal", type=Path, required=True)
    detail = sub.add_parser("detail", help="print cached evidence")
    detail.add_argument("--evidence-id")
    detail.add_argument("--symbol")
    detail.add_argument("--kind")
    sub.add_parser("review", help="rewrite the prompt from the ledger's positions")
    sub.add_parser("execute", help="fill a pending trade from the next open")
    ingest = sub.add_parser("ingest", help="append one validated evidence batch")
    ingest.add_argument("--batch", type=Path, required=True)
    measure = sub.add_parser(
        "measure", help="compare a saved full context with its compact slice"
    )
    measure.add_argument("--context", type=Path, required=True)
    measure.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        if args.command == "measure":
            payload = measure_context(args.context, _as_of(args.as_of))
        else:
            _assert_state(args.state)
            if args.command == "prepare":
                payload = prepare(args.state)
            elif args.command == "propose":
                payload = propose_one(args.state, args.model, args.proposal)
            elif args.command == "review":
                payload = review(args.state)
            elif args.command == "detail":
                payload = detail_one(
                    args.state,
                    args.evidence_id,
                    symbol=args.symbol,
                    kind=args.kind,
                )
            elif args.command == "ingest":
                payload = ingest_one(args.state, args.batch)
            else:
                payload = execute(args.state)
    except (OSError, ValueError, ManagerError, LedgerIntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def prepare(state: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Collect a bounded window and open one isolated simulation book."""
    if (state / "book.sqlite").exists():
        message = "discovery book already exists; use a new state directory"
        raise ValueError(message)
    state.mkdir(parents=True, exist_ok=True)
    moment = datetime.now(UTC) if now is None else now
    end = price_end(moment)
    symbols = tuple(item.symbol for item in RESEARCH_UNIVERSE)
    bars, price_note, price_gaps = collect_prices(symbols, PRICE_START, end)
    statements, statement_gaps = collect_statements(state)
    suggestions = _suggestions(state)
    counts = Counter(bar.symbol for bar in bars)
    schedule = tuple(symbol for symbol in symbols if counts[symbol] >= 64)
    if not schedule:
        schedule = tuple(symbol for symbol in symbols if counts[symbol] > 0)
    decision_day, settlement_day = choose_sessions(bars, schedule)
    from drift.historical.replay import decision_time

    cutoff = decision_time(decision_day)
    suggestions = tuple(item for item in suggestions if item.observed_at <= cutoff)
    statements = tuple(
        item
        for item in statements
        if item.observed_at <= cutoff
        and (item.available_at is None or item.available_at <= cutoff)
    )
    deep = _deep_symbols(bars, decision_day, suggestions, holdings=frozenset())
    news_start = datetime.combine(
        decision_day - timedelta(days=14), datetime.min.time(), tzinfo=UTC
    )
    news, news_gaps = collect_news(
        tuple(sorted(deep)),
        news_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        datetime.combine(settlement_day, datetime.min.time(), tzinfo=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        state,
    )
    texts, excerpt_gaps = collect_excerpts(state, (*statements, *news), deep)
    gaps = (
        *price_gaps,
        *statement_gaps,
        *news_gaps,
        *excerpt_gaps,
        x_gap(),
        "company investor-relations pages are not scraped; "
        "SEC filings are the official-announcement record",
        "Alpaca news has no observed archive before the requested window; "
        "an empty page is a coverage gap, not proof that nothing was published",
    )
    book = assemble_book(
        bars,
        texts,
        suggestions=suggestions,
        price_limitation=price_note,
        decision_day=decision_day,
        settlement_day=settlement_day,
        gaps=gaps,
    )
    _write(state, book)
    _open(state, book)
    return _summary(book)


def propose_one(state: Path, model: str, proposal_path: Path) -> dict[str, object]:
    receipt = _receipt(state)
    raw = normalize_proposal_json(
        _json_object(proposal_path.read_text(encoding="utf-8"))
    )
    proposal = InvestmentProposal.model_validate_json(raw)
    expected = MODELS[model]
    proposal_ids = receipt.get("proposal_ids")
    if not isinstance(proposal_ids, dict):
        message = "discovery receipt is missing proposal ids"
        raise ValueError(message)
    if (
        proposal.inference != "native_supervised"
        or proposal.model_identity != expected
        or str(proposal.proposal_id) != proposal_ids.get(model)
        or proposal.as_of.isoformat() != receipt.get("as_of")
    ):
        message = f"{model} proposal does not match the discovery receipt"
        raise ValueError(message)
    manager = PortfolioManager.recover(state / "book.sqlite")
    recorded = manager.propose(proposal)
    (state / f"last-proposal-{model}.json").write_text(
        proposal.model_dump_json(), encoding="utf-8"
    )
    (state / f"last-result-{model}.json").write_text(
        json.dumps(recorded, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return _plain(recorded)


def detail_one(
    state: Path,
    evidence_id: str | None,
    *,
    symbol: str | None = None,
    kind: str | None = None,
) -> dict[str, object]:
    from drift.research.compact import lookup_evidence, lookup_matches, visible_through

    receipt = _receipt(state)
    cache = visible_through(
        _cache(state), datetime.fromisoformat(str(receipt["as_of"]))
    )
    if evidence_id:
        found = lookup_evidence(cache, evidence_id)
        if found is None:
            message = f"evidence {evidence_id} is not in the discovery cache"
            raise ValueError(message)
        return found
    if symbol is None and kind is None:
        message = "detail needs an evidence id or a symbol or kind"
        raise ValueError(message)
    return {"rows": lookup_matches(cache, symbol=symbol, kind=kind)}


def ingest_one(state: Path, batch_path: Path) -> dict[str, object]:
    from drift.manager.models import IngestBatch

    batch = IngestBatch.model_validate_json(batch_path.read_text(encoding="utf-8"))
    manager = PortfolioManager.recover(state / "book.sqlite")
    recorded = _plain(manager.ingest(batch))
    if recorded.get("status") == "ingested":
        cache = remember_ingested(
            _cache(state),
            [json.loads(item.model_dump_json()) for item in batch.evidence],
            accepted=True,
        )
        (state / "cache.json").write_text(
            json.dumps(cache, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    return recorded


def review(state: Path) -> dict[str, object]:
    """Rewrite the prompt from shares the ledger already holds."""
    from drift.historical.replay import decision_time, historical_session
    from drift.research.book import later_weekday, review_prompts

    receipt = _receipt(state)
    settlement = date.fromisoformat(str(receipt["settlement_day"]))
    review_day = later_weekday(settlement)
    fill_day = later_weekday(review_day)
    as_of = decision_time(review_day)
    manager = PortfolioManager.recover(state / "book.sqlite")
    viewed = manager.context(as_of)
    book = viewed.get("book") if isinstance(viewed, dict) else None
    if not isinstance(book, dict):
        message = "discovery ledger has no book"
        raise ValueError(message)
    cash = book.get("cash")
    if not isinstance(cash, str):
        message = "discovery ledger has no cash balance"
        raise ValueError(message)
    quantities: dict[str, int] = {}
    holdings = book.get("holdings")
    if isinstance(holdings, list):
        for item in holdings:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            quantity = item.get("quantity")
            if isinstance(symbol, str) and isinstance(quantity, int) and quantity > 0:
                quantities[symbol] = quantity
    ledger_evidence = viewed.get("evidence") if isinstance(viewed, dict) else None
    citable: list[dict[str, object]] = []
    if isinstance(ledger_evidence, list):
        for item in ledger_evidence:
            if isinstance(item, dict):
                citable.append({str(key): value for key, value in item.items()})
    prompts, proposal_ids, rows = review_prompts(
        _cache(state),
        ledger=citable,
        cash=cash,
        quantities=quantities,
        review_day=review_day,
    )
    (state / "prompt-terra.txt").write_text(prompts["terra"] + "\n", encoding="utf-8")
    (state / "prompt-sol.txt").write_text(prompts["sol"] + "\n", encoding="utf-8")
    updated = dict(receipt)
    updated["as_of"] = as_of.isoformat()
    updated["execute_as_of"] = historical_session(fill_day).closed_at.isoformat()
    updated["proposal_ids"] = proposal_ids
    updated["review_day"] = review_day.isoformat()
    updated["review_settlement_day"] = fill_day.isoformat()
    (state / "receipt.json").write_text(
        json.dumps(updated, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "as_of": as_of.isoformat(),
        "cash": cash,
        "holdings": quantities,
        "shortlist": [row.symbol for row in rows if row.shortlisted],
    }


def execute(state: Path) -> dict[str, object]:
    receipt = _receipt(state)
    when = datetime.fromisoformat(str(receipt["execute_as_of"]))
    manager = PortfolioManager.recover(state / "book.sqlite")
    return _plain(manager.execute_pending(when))


def measure_context(path: Path, as_of: datetime) -> dict[str, object]:
    """Compact a saved manager context and check that named evidence ids remain."""
    from drift.historical.replay import research_brief

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        message = "context is not an object"
        raise ValueError(message)
    evidence = loaded.get("evidence")
    if not isinstance(evidence, list):
        message = "context has no evidence list"
        raise ValueError(message)
    rows: list[dict[str, object]] = []
    names: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        row = {str(key): value for key, value in item.items()}
        rows.append(row)
        symbol = row.get("symbol")
        if isinstance(symbol, str):
            names.add(symbol)
    symbols = frozenset(names)
    compact = compact_evidence(rows, symbols=symbols, deep=symbols, as_of=as_of)
    brief = research_brief(loaded, as_of, policy="research")
    full = json.dumps(loaded, sort_keys=True)
    reduced = json.dumps({"evidence": compact}, sort_keys=True)
    report: dict[str, object] = dict(size_report(full, reduced))
    report["cited_ids_missing"] = cited_ids_missing(brief, compact)
    report["full_evidence"] = len(evidence)
    report["compact_evidence"] = len(compact)
    return report


def _deep_symbols(
    bars: tuple[PriceBar, ...],
    decision_day: date,
    suggestions: tuple[UserSuggestion, ...],
    holdings: frozenset[str],
) -> frozenset[str]:
    points: list[ClosePoint] = []
    for bar in bars:
        if bar.day > decision_day:
            continue
        volume = None if bar.volume is None else Decimal(bar.volume)
        points.append(
            ClosePoint(
                symbol=bar.symbol,
                day=bar.day,
                close=Decimal(bar.close_price),
                volume=volume,
                evidence_id=f"preview:{bar.symbol}:{bar.day.isoformat()}",
            )
        )
    suggested = frozenset(item.symbol for item in suggestions)
    rows = screen(
        points,
        as_of=decision_day,
        universe=frozenset(universe_by_symbol()),
        authorized=frozenset(ORIGINAL_TRADING_SYMBOLS),
        holdings=holdings,
        suggestions=suggested,
    )
    return frozenset(
        row.symbol
        for row in rows
        if row.shortlisted or row.trading_authorized or row.symbol in holdings
    )


def _suggestions(state: Path) -> tuple[UserSuggestion, ...]:
    path = state / "suggestions.json"
    if not path.is_file():
        return ()
    return load_suggestions(path)


def _write(state: Path, book: DiscoveryBook) -> None:
    (state / "cache.json").write_text(
        json.dumps(list(book.cache), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (state / "prompt-terra.txt").write_text(
        book.prompts["terra"] + "\n", encoding="utf-8"
    )
    (state / "prompt-sol.txt").write_text(book.prompts["sol"] + "\n", encoding="utf-8")
    (state / "prompt-baseline-terra.txt").write_text(
        book.baseline_prompts["terra"] + "\n", encoding="utf-8"
    )
    (state / "prompt-baseline-sol.txt").write_text(
        book.baseline_prompts["sol"] + "\n", encoding="utf-8"
    )
    receipt = {
        "as_of": book.as_of.isoformat(),
        "decision_day": book.decision_day.isoformat(),
        "execute_as_of": historical_session(book.settlement_day).closed_at.isoformat(),
        "model_identities": MODELS,
        "proposal_ids": book.proposal_ids,
        "settlement_day": book.settlement_day.isoformat(),
        "trading_authorized": list(ORIGINAL_TRADING_SYMBOLS),
    }
    (state / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    summary = _summary(book)
    (state / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _open(state: Path, book: DiscoveryBook) -> None:
    packet_path = state / "packet.json"
    mandate_path = state / "mandate.json"
    packet_path.write_text(book.packet.model_dump_json(indent=2), encoding="utf-8")
    mandate_path.write_text(book.mandate.model_dump_json(indent=2), encoding="utf-8")
    PortfolioManager.open(state / "book.sqlite", book.packet, book.mandate)


def _summary(book: DiscoveryBook) -> dict[str, object]:
    shortlist = [row.symbol for row in book.rows if row.shortlisted]
    outside = [
        row.symbol
        for row in book.rows
        if row.shortlisted and row.symbol not in ORIGINAL_TRADING_SYMBOLS
    ]
    return {
        "decision_day": book.decision_day.isoformat(),
        "follow_ups": list(book.follow_ups),
        "gaps": list(book.gaps),
        "measurement": book.measurement,
        "outside_original_universe": outside,
        "settlement_day": book.settlement_day.isoformat(),
        "shortlist": shortlist,
        "screen": [asdict(row) for row in book.rows if row.research_eligible],
    }


def _receipt(state: Path) -> dict[str, object]:
    loaded = json.loads((state / "receipt.json").read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        message = "discovery receipt is invalid"
        raise ValueError(message)
    return loaded


def remember_ingested(
    cache: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
    *,
    accepted: bool,
) -> list[dict[str, object]]:
    """Add ledger-confirmed rows once. A rejection leaves the cache unchanged."""
    if not accepted:
        return [dict(item) for item in cache]
    known = {item.get("evidence_id") for item in cache}
    updated = [dict(item) for item in cache]
    index = {
        item.get("evidence_id"): position
        for position, item in enumerate(updated)
        if item.get("evidence_id") is not None
    }
    for row in rows:
        evidence_key = row.get("evidence_id")
        if evidence_key in known:
            updated[index[evidence_key]] = dict(row)
            continue
        index[evidence_key] = len(updated)
        updated.append(dict(row))
        known.add(evidence_key)
    return updated


def _cache(state: Path) -> list[dict[str, object]]:
    loaded = json.loads((state / "cache.json").read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        message = "discovery cache is invalid"
        raise ValueError(message)
    rows: list[dict[str, object]] = []
    for item in loaded:
        if isinstance(item, dict):
            rows.append({str(key): value for key, value in item.items()})
    return rows


def _assert_state(state: Path) -> None:
    assert_isolated(state)
    resolved = state.resolve()
    if "src" in resolved.parts or "tests" in resolved.parts:
        message = "discovery state must stay outside the source tree"
        raise ValueError(message)
    if resolved.name in {"observation", "readiness"} or any(
        (resolved / f"{name}.sqlite").is_file() for name in ("terra", "sol")
    ):
        message = "discovery state cannot overwrite a prospective book"
        raise ValueError(message)


def _plain(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"status": "recorded"}
    return {str(key): item for key, item in value.items()}


def _as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        message = "as_of must include a timezone"
        raise ValueError(message)
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
