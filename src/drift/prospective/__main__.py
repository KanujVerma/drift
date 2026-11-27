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
from datetime import UTC, date, datetime
from pathlib import Path

from drift.errors import LedgerIntegrityError
from drift.manager.service import ManagerError
from drift.prospective.collect import Collection, collect_live, load_suggestions
from drift.prospective.config import (
    eligibility_message,
    in_settlement_window,
    observation_date,
)
from drift.prospective.run import (
    apply_proposal,
    pending_benchmark_after,
    pending_observation_reviews,
    pending_reviews_expired,
    pending_trade_requests,
    perform_daily,
    recover_shared_inputs,
    resolve_expired_review,
    restore_pending_observation_reviews,
    status_report,
    stored_price_feed,
    used_trade_ids,
)

DEFAULT_STATE = Path.home() / ".local" / "share" / "drift" / "prospective-pilot"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m drift.prospective")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command")
    collect = sub.add_parser("collect", help="fetch public inputs and write a report")
    _now(collect)
    configure = sub.add_parser(
        "configure-window", help="capture NYSE data and configure a future window"
    )
    configure.add_argument(
        "--start", type=date.fromisoformat, help="earliest desired date, YYYY-MM-DD"
    )
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
    submit = sub.add_parser("submit", help="record saved proposals without collecting")
    submit.add_argument("--role", choices=("observation", "readiness"), required=True)
    submit.add_argument("--proposal", action="append", required=True, help="name=path")
    resolve = sub.add_parser(
        "resolve-expired", help="record an unanswered expired review"
    )
    resolve.add_argument("--model", choices=("terra", "sol"), required=True)
    resolve.add_argument("--proposal-id", required=True)
    resolve.add_argument("--reason", required=True)
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
    from drift.prospective.locking import pilot_lock

    source_tree = Path(__file__).resolve().parents[3]
    args.state = args.state.resolve()
    if args.state.is_relative_to(source_tree):
        raise ValueError("prospective state must be outside the source tree")
    with pilot_lock(args.state):
        return _run_locked(args)


def _run_locked(args: argparse.Namespace) -> dict[str, object]:
    source_tree = Path(__file__).resolve().parents[3]
    args.state = args.state.resolve()
    if args.state.is_relative_to(source_tree):
        raise ValueError("prospective state must be outside the source tree")
    if args.command == "configure-window":
        from drift.prospective.window import PILOT_VERSION, configure_window

        window = configure_window(args.state, requested_start=args.start)
        return {
            "status": "configured",
            "pilot_version": PILOT_VERSION,
            "source_received_at": window.source_received_at.isoformat()
            if window.source_received_at
            else None,
            "source_sha256": window.source_sha256,
            "observation_dates": [day.isoformat() for day in window.observation_dates],
            "settlement_dates": [day.isoformat() for day in window.settlement_dates],
        }
    if args.command == "resolve-expired" or (
        args.command == "submit" and args.role == "observation"
    ):
        from drift.prospective.window import active_window, verify_current_window

        if active_window() is not None:
            verify_current_window(args.state)
    if args.command == "resolve-expired":
        return dict[str, object](
            resolve_expired_review(
                args.state, args.model, args.proposal_id, args.reason
            )
        )
    if args.command == "submit":
        proposals = _proposals(args.proposal)
        return {
            "proposals": {
                name: apply_proposal(args.state, args.role, name, path)
                for name, path in proposals.items()
            }
        }
    if args.command == "daily" and args.role == "observation" and args.proposal:
        raise ValueError("submit observation proposals before collecting new data")
    if args.command == "daily" and args.role == "observation":
        from drift.prospective.window import active_window

        if active_window() is None and not any(
            (args.state / "observation" / f"{name}.sqlite").exists()
            for name in ("terra", "sol")
        ):
            return {
                "status": "window_not_configured",
                "eligibility": (
                    "configure a source-checked future window before "
                    "opening observation books"
                ),
            }
    pending: list[str] = []
    if args.command == "daily" and args.role == "observation":
        recover_shared_inputs(args.state, args.role)
        pending = pending_observation_reviews(args.state)
        if pending:
            pending = restore_pending_observation_reviews(args.state)
            if not pending_reviews_expired(args.state, pending, datetime.now(UTC)):
                return {"status": "pending_reviews", "models": pending}
        from drift.prospective.window import active_window

        now = datetime.now(UTC)
        configured = active_window()
        if configured is not None:
            if (
                observation_date(now) != configured.dates[0]
                and now >= configured.calendar.open(configured.dates[0])
                and not any(
                    (args.state / "observation" / f"{name}.sqlite").exists()
                    for name in ("terra", "sol")
                )
            ):
                return {
                    "status": "fresh_window_required",
                    "eligibility": (
                        "the first session passed without opening books; "
                        "use a new state directory"
                    ),
                }
            if observation_date(now) is None and not in_settlement_window(now):
                return {
                    "status": "not_eligible",
                    "eligibility": eligibility_message(now),
                }
            from drift.prospective.window import verify_current_window

            verify_current_window(args.state)
    suggestions_path = getattr(args, "suggestions", None)
    suggestions = (
        load_suggestions(suggestions_path) if suggestions_path is not None else ()
    )
    explicit_now = getattr(args, "now", None)
    if args.command == "daily" and args.role == "observation":
        # A caller-supplied clock must not open or backdate an observation session.
        # The review clock is the benchmark response time, not the time before
        # that request returns.
        feed = stored_price_feed(args.state, args.role)
        requests = pending_trade_requests(args.state)
        used = used_trade_ids(args.state, args.role)
        benchmark_after = pending_benchmark_after(args.state)
        if used and benchmark_after is not None:
            collection = collect_live(
                None,
                preferred_feed=feed,
                trade_requests=requests,
                benchmark_after=benchmark_after,
                excluded_trades=used,
            )
        elif used and requests:
            collection = collect_live(
                None, preferred_feed=feed, trade_requests=requests, excluded_trades=used
            )
        elif benchmark_after is not None:
            collection = collect_live(
                None,
                preferred_feed=feed,
                trade_requests=requests,
                benchmark_after=benchmark_after,
            )
        elif requests:
            collection = collect_live(
                None, preferred_feed=feed, trade_requests=requests
            )
        elif feed is not None:
            collection = collect_live(None, preferred_feed=feed)
        else:
            collection = collect_live(None)
        moment = collection.benchmark_fetched_at
    elif explicit_now is None and args.command in {"collect", "daily"}:
        feed = (
            stored_price_feed(args.state, args.role)
            if args.command == "daily"
            else None
        )
        requests = (
            pending_trade_requests(args.state, args.role)
            if args.command == "daily"
            else ()
        )
        used = used_trade_ids(args.state, args.role) if requests else frozenset()
        if requests:
            collection = collect_live(
                None, preferred_feed=feed, trade_requests=requests, excluded_trades=used
            )
        else:
            collection = (
                collect_live(None)
                if feed is None
                else collect_live(None, preferred_feed=feed)
            )
        moment = collection.benchmark_fetched_at
    else:
        moment = _moment(explicit_now)
        collection = None
    if args.command == "collect":
        if collection is None:
            collection = collect_live(moment)
        return _write_collection(args.state, collection)
    if args.command == "status":
        from drift.prospective.window import active_window

        book_status = status_report(args.state, args.role, moment)
        configured = active_window()
        if (
            args.role == "observation"
            and configured is None
            and not any(
                (args.state / "observation" / f"{name}.sqlite").exists()
                for name in ("terra", "sol")
            )
        ):
            book_status["window_configuration"] = "not_configured"
            book_status["observation_dates"] = []
            return {
                "eligibility": "configure a source-checked future window",
                "status": book_status,
            }
        book_status["window_configuration"] = (
            "configured" if configured is not None else "legacy"
        )
        if configured is not None:
            from drift.prospective.window import PILOT_VERSION

            book_status["pilot_version"] = PILOT_VERSION
            book_status["window_source_sha256"] = configured.source_sha256
            book_status["window_source_received_at"] = (
                configured.source_received_at.isoformat()
                if configured.source_received_at is not None
                else None
            )
            book_status["window_binding"] = configured.binding
        return {
            "eligibility": eligibility_message(moment),
            "status": book_status,
        }
    if args.command != "daily":
        message = f"unknown command {args.command}"
        raise ValueError(message)
    if collection is None:
        feed = stored_price_feed(args.state, args.role)
        requests = pending_trade_requests(args.state, args.role)
        if requests:
            collection = collect_live(
                moment,
                preferred_feed=feed,
                trade_requests=requests,
                excluded_trades=used_trade_ids(args.state, args.role),
            )
        else:
            collection = (
                collect_live(moment)
                if feed is None
                else collect_live(moment, preferred_feed=feed)
            )
    if suggestions_path is not None:
        collection = replace(collection, suggestions=suggestions)
    report = _write_collection(args.state, collection)
    proposals = _proposals(args.proposal)
    outcome = perform_daily(
        args.state,
        args.role,
        moment,
        collection,
        proposals,
        suppress_reviews=bool(pending),
    )
    outcome["collection"] = report
    if pending:
        outcome["status"] = "pending_reviews"
        outcome["models"] = pending
    return outcome


def _proposals(items: list[str]) -> dict[str, Path]:
    proposals: dict[str, Path] = {}
    for item in items:
        if not isinstance(item, str) or "=" not in item:
            message = "proposal must look like terra=path.json"
            raise ValueError(message)
        name, raw_path = item.split("=", 1)
        if name not in {"terra", "sol"} or name in proposals or not raw_path:
            raise ValueError("proposal must name terra or sol once with a path")
        proposals[name] = Path(raw_path)
    return proposals


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
