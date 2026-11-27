"""Daily prospective simulation commands.

``python -m drift.prospective --help``

The process collects public inputs and updates two ledgers. It does not
call a model. Pass proposal files produced by the supervising models.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from drift.errors import LedgerIntegrityError
from drift.manager.service import ManagerError
from drift.prospective.collect import Collection, collect_live, load_suggestions
from drift.prospective.config import eligibility_message
from drift.prospective.run import perform_daily, status_report

DEFAULT_STATE = Path(".local-artifacts/prospective")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m drift.prospective")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command")
    collect = sub.add_parser("collect", help="fetch public inputs and write a report")
    _now(collect)
    daily = sub.add_parser("daily", help="collect, update books, and export contexts")
    _now(daily)
    daily.add_argument("--role", choices=("observation", "readiness"), required=True)
    daily.add_argument(
        "--proposal",
        action="append",
        default=[],
        help="name=path, for example terra=terra.json",
    )
    daily.add_argument(
        "--suggestions",
        type=Path,
        help="JSON list of {symbol, summary, observed_at} user notes",
    )
    status = sub.add_parser("status", help="recover both books and report")
    _now(status)
    status.add_argument("--role", choices=("observation", "readiness"), required=True)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        payload = _run(args)
    except (OSError, ValueError, ManagerError, LedgerIntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _now(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--now", help="timezone-aware timestamp, default UTC now")


def _run(args: argparse.Namespace) -> dict[str, object]:
    explicit_now = getattr(args, "now", None)
    if args.command == "daily" and args.role == "observation":
        # A caller-supplied clock must not open or backdate an observation session.
        # The review clock is the benchmark response time, not the time before
        # that request returns.
        collection = collect_live(None)
        moment = collection.benchmark_fetched_at
    elif explicit_now is None and args.command in {"collect", "daily"}:
        collection = collect_live(None)
        moment = collection.benchmark_fetched_at
    else:
        moment = _moment(explicit_now)
        collection = None
    if args.command == "collect":
        if collection is None:
            collection = collect_live(moment)
        return _write_collection(args.state, collection)
    if args.command == "status":
        return {
            "eligibility": eligibility_message(moment),
            "status": status_report(args.state, args.role, moment),
        }
    if args.command != "daily":
        message = f"unknown command {args.command}"
        raise ValueError(message)
    if collection is None:
        collection = collect_live(moment)
    suggestions_path = getattr(args, "suggestions", None)
    if suggestions_path is not None:
        collection = replace(collection, suggestions=load_suggestions(suggestions_path))
    report = _write_collection(args.state, collection)
    proposals: dict[str, Path] = {}
    for item in args.proposal:
        if not isinstance(item, str) or "=" not in item:
            message = "proposal must look like terra=path.json"
            raise ValueError(message)
        name, raw_path = item.split("=", 1)
        proposals[name] = Path(raw_path)
    outcome = perform_daily(args.state, args.role, moment, collection, proposals)
    outcome["collection"] = report
    return outcome


def _write_collection(state: Path, collection: Collection) -> dict[str, object]:
    state.mkdir(parents=True, exist_ok=True)
    body = {
        "collected_at": collection.collected_at.isoformat(),
        "gaps": list(collection.gaps),
        "headline_count": len(collection.headlines),
        "price_symbols": sorted({bar.symbol for bar in collection.bars}),
        "sources": list(collection.sources),
        "benchmark_kind": collection.benchmark_kind,
        "benchmark_level": collection.benchmark_level,
    }
    (state / "collection.json").write_text(
        json.dumps(body, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return body


def _moment(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        message = "timestamps must be timezone-aware"
        raise ValueError(message)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
