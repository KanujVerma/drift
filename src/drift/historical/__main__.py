"""Prepare and step an isolated historical replay.

``python -m drift.historical --help``

The process does not call a model. A supervisor supplies native proposal files.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from time import sleep
from typing import Literal

from drift.errors import LedgerIntegrityError
from drift.historical.replay import (
    Study,
    apply_native,
    assert_isolated,
    missing_dates,
    prepare_review,
    texts_for_window,
)
from drift.historical.select import Close, Window, select_windows
from drift.historical.sources import (
    PriceBar,
    TextInput,
    fetch_json,
    parse_company_facts,
    parse_submission_filings,
    parse_yahoo_chart,
    probe_alpaca,
    submission_file_names,
    yahoo_adjustment_note,
    yahoo_split_dates,
)
from drift.manager.service import ManagerError
from drift.prospective.config import UNIVERSE

DEFAULT_STATE = Path(".local-artifacts/historical")
PERIOD_START = int(datetime(2020, 12, 1, tzinfo=UTC).timestamp())
PERIOD_END = int(datetime(2026, 1, 15, tzinfo=UTC).timestamp())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m drift.historical")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("prepare", help="fetch public inputs and freeze windows")
    review = sub.add_parser(
        "review", help="write the next prompt, or record a proposal"
    )
    review.add_argument("--regime", required=True)
    review.add_argument("--book", choices=("memory", "nomemory"), required=True)
    review.add_argument("--model", choices=("terra", "sol"), required=True)
    review.add_argument("--proposal", type=Path)
    sub.add_parser("report", help="summarize recorded books")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        assert_isolated(args.state)
        if args.command == "prepare":
            payload = prepare(args.state)
        elif args.command == "review":
            payload = review_one(
                args.state,
                regime=args.regime,
                book=args.book,
                model=args.model,
                proposal=args.proposal,
            )
        else:
            payload = report(args.state)
    except (OSError, ValueError, ManagerError, LedgerIntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def prepare(state: Path) -> dict[str, object]:
    """Fetch inputs, select windows, and write the frozen criteria."""
    state.mkdir(parents=True, exist_ok=True)
    _feed, alpaca_gaps = probe_alpaca()
    gaps = list(alpaca_gaps)
    bars, splits, price_note, price_gaps = _yahoo_prices(state)
    gaps.extend(price_gaps)
    levels, kind, limitation, bench_gaps = _yahoo_benchmark(state)
    gaps.extend(bench_gaps)
    texts, text_gaps = _edgar(state)
    gaps.extend(text_gaps)
    gaps.append(
        "X posts are not collected; no authorized X API credential is configured"
    )
    gaps.append("historical news and Alpaca news were not available")
    study = Study(
        bars=tuple(bars),
        texts=tuple(texts),
        benchmark_levels=tuple(levels),
        benchmark_kind=kind,
        benchmark_limitation=limitation,
        price_limitation=price_note,
    )
    closes = tuple(Close(day, Decimal(level)) for day, level in levels)
    forbidden = set(splits)
    windows = select_windows(closes, forbidden=frozenset(forbidden))
    for _pass in range(8):
        blocked = False
        for name, window in list(windows.items()):
            missing = missing_dates(study, window)
            if not missing:
                continue
            forbidden.update(missing)
            blocked = True
            gaps.append(
                f"{name} block overlapped incomplete prices on "
                + ", ".join(sorted(day.isoformat() for day in missing))
            )
        if not blocked:
            break
        windows = select_windows(closes, forbidden=frozenset(forbidden))
    frozen: dict[str, object] = {
        "alpaca": list(alpaca_gaps),
        "benchmark_kind": kind,
        "benchmark_limitation": limitation,
        "gaps": gaps,
        "price_limitation": price_note,
        "splits": sorted(day.isoformat() for day in splits),
        "windows": {
            name: {
                "decision_days": [day.isoformat() for day in window.decision_days],
                "max_drawdown": format(window.max_drawdown, "f"),
                "max_runup": format(window.max_runup, "f"),
                "settlement_day": window.settlement_day.isoformat(),
                "threshold_index": window.threshold_index,
                "total_return": format(window.total_return, "f"),
                "warmup_day": window.warmup_day.isoformat(),
            }
            for name, window in sorted(windows.items())
        },
    }
    (state / "criteria.json").write_text(
        json.dumps(frozen, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _cache_study(state, study)
    return frozen


def review_one(
    state: Path,
    *,
    regime: str,
    book: str,
    model: str,
    proposal: Path | None,
) -> dict[str, object]:
    study, window = _load(state, regime)
    if proposal is None:
        return prepare_review(state, study, window, book=book, model=model)
    return apply_native(
        state,
        study,
        window,
        book=book,
        model=model,
        proposal_path=proposal,
    )


def report(state: Path) -> dict[str, object]:
    """Read frozen windows and any reports already appended. It does not infer."""
    criteria_path = state / "criteria.json"
    if not criteria_path.is_file():
        message = "historical criteria have not been frozen"
        raise ValueError(message)
    criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
    books: dict[str, object] = {}
    windows = criteria.get("windows") if isinstance(criteria, dict) else None
    if isinstance(windows, dict):
        for regime in windows:
            for book in ("memory", "nomemory"):
                for model in ("terra", "sol"):
                    path = state / str(regime) / book / model / "reports.jsonl"
                    key = f"{regime}/{book}/{model}"
                    if not path.is_file():
                        books[key] = "not_started"
                        continue
                    rows = [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    books[key] = {
                        "reports": len(rows),
                        "last": rows[-1] if rows else None,
                    }
    return {"books": books, "criteria": criteria}


def _load(state: Path, regime: str) -> tuple[Study, Window]:
    raw = json.loads((state / "criteria.json").read_text(encoding="utf-8"))
    cached = json.loads((state / "study.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(cached, dict):
        message = "historical cache is invalid"
        raise ValueError(message)
    windows = raw.get("windows")
    if not isinstance(windows, dict) or regime not in windows:
        message = f"regime {regime} was not frozen"
        raise ValueError(message)
    item = windows[regime]
    if not isinstance(item, dict):
        message = f"regime {regime} is invalid"
        raise ValueError(message)
    window = Window(
        regime=regime,
        warmup_day=date.fromisoformat(str(item["warmup_day"])),
        decision_days=tuple(
            date.fromisoformat(day)
            for day in item["decision_days"]
            if isinstance(day, str)
        ),
        settlement_day=date.fromisoformat(str(item["settlement_day"])),
        threshold_index=int(str(item["threshold_index"])),
        total_return=Decimal(str(item["total_return"])),
        max_drawdown=Decimal(str(item["max_drawdown"])),
        max_runup=Decimal(str(item["max_runup"])),
    )
    bars = tuple(
        PriceBar(
            symbol=row["symbol"],
            day=date.fromisoformat(row["day"]),
            open_price=row["open_price"],
            close_price=row["close_price"],
            volume=row["volume"],
            source_label=row["source_label"],
        )
        for row in cached["bars"]
    )
    texts = tuple(
        TextInput(
            evidence_id=row["evidence_id"],
            symbol=row["symbol"],
            kind=row["kind"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            summary=row["summary"],
            source_label=row["source_label"],
            limitations=tuple(row["limitations"]),
        )
        for row in cached["texts"]
    )
    kind = cached["benchmark_kind"]
    if kind not in {"sp500_total_return", "price_only_substitute"}:
        message = "benchmark kind is not labeled"
        raise ValueError(message)
    study = Study(
        bars=bars,
        texts=texts_for_window(texts, window),
        benchmark_levels=tuple(
            (date.fromisoformat(day), level)
            for day, level in cached["benchmark_levels"]
        ),
        benchmark_kind=kind,
        benchmark_limitation=str(cached["benchmark_limitation"]),
        price_limitation=str(cached["price_limitation"]),
    )
    return study, window


def _cache_study(state: Path, study: Study) -> None:
    payload = {
        "bars": [
            {
                "close_price": row.close_price,
                "day": row.day.isoformat(),
                "open_price": row.open_price,
                "source_label": row.source_label,
                "symbol": row.symbol,
                "volume": row.volume,
            }
            for row in study.bars
        ],
        "benchmark_kind": study.benchmark_kind,
        "benchmark_levels": [
            [day.isoformat(), level] for day, level in study.benchmark_levels
        ],
        "benchmark_limitation": study.benchmark_limitation,
        "price_limitation": study.price_limitation,
        "texts": [
            {
                "evidence_id": item.evidence_id,
                "kind": item.kind,
                "limitations": list(item.limitations),
                "observed_at": item.observed_at.isoformat(),
                "source_label": item.source_label,
                "summary": item.summary,
                "symbol": item.symbol,
            }
            for item in study.texts
        ],
    }
    (state / "study.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _yahoo_prices(
    state: Path,
) -> tuple[list[PriceBar], frozenset[date], str, list[str]]:
    bars: list[PriceBar] = []
    splits: set[date] = set()
    gaps: list[str] = []
    notes: list[str] = []
    for symbol, _cik, _name in UNIVERSE:
        payload, error = _chart(state, symbol)
        if error is not None or payload is None:
            gaps.append(f"{symbol} prices: {error}")
            continue
        parsed = parse_yahoo_chart(symbol, payload)
        if not parsed:
            gaps.append(f"{symbol} prices: Yahoo chart returned no bars")
            continue
        bars.extend(parsed)
        splits.update(yahoo_split_dates(payload))
        note = yahoo_adjustment_note(payload)
        if note is not None:
            notes.append(f"{symbol}: {note}")
    limitation = (
        "Yahoo chart v8 quote open and close, rounded half-up to cents; "
        "not an official exchange print; not dividend-adjusted. " + " ".join(notes)
    ).strip()
    return bars, frozenset(splits), limitation, gaps


def _yahoo_benchmark(
    state: Path,
) -> tuple[
    list[tuple[date, str]],
    Literal["sp500_total_return", "price_only_substitute"],
    str,
    list[str],
]:
    payload, error = _chart(state, "^SP500TR")
    if error is None and payload is not None:
        rows = parse_yahoo_chart("^SP500TR", payload)
        if rows:
            return (
                [(row.day, row.close_price) for row in rows],
                "sp500_total_return",
                "Yahoo ^SP500TR close used as the S&P 500 total-return level; "
                "not an official index vendor print",
                [],
            )
    message = f"^SP500TR: {error or 'no rows'}"
    spy = list(parse_yahoo_chart("SPY", payload or {}))
    if not spy:
        cached, _cached_error = _chart(state, "SPY")
        spy = list(parse_yahoo_chart("SPY", cached or {}))
    return (
        [(row.day, row.close_price) for row in spy],
        "price_only_substitute",
        "SPY close is a price-only substitute, not S&P 500 total return",
        [message],
    )


def _edgar(state: Path) -> tuple[list[TextInput], list[str]]:
    texts: list[TextInput] = []
    gaps: list[str] = []
    for symbol, cik, _name in UNIVERSE:
        submissions, error = _sec(
            state, symbol, f"https://data.sec.gov/submissions/CIK{cik}.json"
        )
        if error is not None or submissions is None:
            gaps.append(f"{symbol} filings: {error}")
        else:
            texts.extend(parse_submission_filings(symbol, submissions))
            for name in submission_file_names(submissions):
                extra, extra_error = _sec(
                    state,
                    f"{symbol}-{name}",
                    f"https://data.sec.gov/submissions/{name}",
                )
                if extra_error is not None or extra is None:
                    gaps.append(f"{symbol} filings {name}: {extra_error}")
                    continue
                texts.extend(parse_submission_filings(symbol, extra))
        facts, fact_error = _sec(
            state,
            f"{symbol}-facts",
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        )
        if fact_error is not None or facts is None:
            gaps.append(f"{symbol} companyfacts: {fact_error}")
            continue
        found = parse_company_facts(symbol, facts)
        if not found:
            gaps.append(f"{symbol} companyfacts: no revenue or EPS rows")
        texts.extend(found)
    return texts, gaps


def _chart(state: Path, symbol: str) -> tuple[object | None, str | None]:
    safe = symbol.replace("^", "idx-")
    path = state / "raw" / f"yahoo-{safe}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), None
    quoted = urllib.parse.quote(symbol)
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quoted}?interval=1d&period1={PERIOD_START}&period2={PERIOD_END}"
        "&events=div%7Csplit&includeAdjustedClose=true"
    )
    payload, error = fetch_json(url)
    if payload is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return payload, error


def _sec(state: Path, name: str, url: str) -> tuple[object | None, str | None]:
    path = state / "raw" / f"sec-{name}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), None
    payload, error = fetch_json(url)
    sleep(0.2)
    if payload is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return payload, error


if __name__ == "__main__":
    raise SystemExit(main())
