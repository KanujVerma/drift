"""Command line for the offline supervised portfolio cycle.

The process does not call a model. A supervising agent supplies proposals
as JSON. Run ``python -m drift.manager --help``.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from drift.errors import LedgerIntegrityError
from drift.manager.models import (
    FeedbackNote,
    IngestBatch,
    InvestmentProposal,
    ReflectionRequest,
    ResearchPacket,
    SimulationMandate,
)
from drift.manager.service import ManagerError, PortfolioManager

type Json = None | bool | int | str | list["Json"] | dict[str, "Json"]


def main(argv: list[str] | None = None) -> int:
    """Run one portfolio-cycle command and print JSON."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        payload = _run(args)
    except ValidationError as error:
        print(error, file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except (ManagerError, LedgerIntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 3
    _emit(payload)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m drift.manager",
        description=(
            "Offline simulation-only portfolio cycle. "
            "Proposals are validated and, when eligible, filled on the "
            "retained accounting kernel. This does not connect to a broker."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    open_cmd = sub.add_parser("open", help="create a ledger from a packet and mandate")
    _ledger(open_cmd)
    open_cmd.add_argument("--packet", type=Path, required=True)
    open_cmd.add_argument("--mandate", type=Path, required=True)
    propose = sub.add_parser("propose", help="validate and maybe simulate a proposal")
    _ledger(propose)
    propose.add_argument("--proposal", type=Path, required=True)
    mark = sub.add_parser("mark", help="mark holdings from cited close observations")
    _ledger(mark)
    mark.add_argument("--as-of", required=True)
    context = sub.add_parser("context", help="show point-in-time review context")
    _ledger(context)
    context.add_argument("--as-of", required=True)
    report = sub.add_parser("report", help="report performance and costs")
    _ledger(report)
    report.add_argument("--as-of", required=True)
    reflect = sub.add_parser("reflect", help="record a reflection without trading")
    _ledger(reflect)
    reflect.add_argument("--request", type=Path, required=True)
    feedback = sub.add_parser("feedback", help="record supervising-user feedback")
    _ledger(feedback)
    feedback.add_argument("--note", type=Path, required=True)
    ingest = sub.add_parser(
        "ingest",
        help="append evidence or benchmark points after they become available",
    )
    _ledger(ingest)
    ingest.add_argument("--batch", type=Path, required=True)
    session = sub.add_parser("session", help="supervised command session")
    _ledger(session)
    return parser


def _ledger(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", type=Path, required=True)


def _run(args: argparse.Namespace) -> Json:
    if args.command == "session":
        return _session(args.ledger)
    if args.command == "open":
        packet = ResearchPacket.model_validate_json(_read(args.packet))
        mandate = SimulationMandate.model_validate_json(_read(args.mandate))
        _manager, payload = PortfolioManager.open(args.ledger, packet, mandate)
        return payload
    manager = PortfolioManager.recover(args.ledger)
    if args.command == "propose":
        proposal = InvestmentProposal.model_validate_json(_read(args.proposal))
        return manager.propose(proposal)
    if args.command == "mark":
        return manager.mark(_as_of(args.as_of))
    if args.command == "context":
        return manager.context(_as_of(args.as_of))
    if args.command == "report":
        return manager.report(_as_of(args.as_of))
    if args.command == "reflect":
        request = ReflectionRequest.model_validate_json(_read(args.request))
        return manager.reflect(request)
    if args.command == "feedback":
        note = FeedbackNote.model_validate_json(_read(args.note))
        return manager.feedback(note)
    if args.command == "ingest":
        batch = IngestBatch.model_validate_json(_read(args.batch))
        return manager.ingest(batch)
    message = f"unknown command {args.command}"
    raise ValueError(message)


def _session(path: Path) -> Json:
    print(
        "simulation-only session. Commands: context, report, propose, "
        "mark, reflect, feedback, ingest, help, quit.",
        file=sys.stderr,
    )
    last: Json = {"status": "session"}
    for line in sys.stdin:
        parts = line.strip().split(maxsplit=1)
        if not parts:
            continue
        command = parts[0]
        argument = parts[1] if len(parts) > 1 else ""
        if command in {"quit", "exit"}:
            break
        if command == "help":
            last = {
                "commands": [
                    "context ASOF",
                    "report ASOF",
                    "propose PATH",
                    "mark ASOF",
                    "reflect PATH",
                    "feedback PATH",
                    "ingest PATH",
                    "quit",
                ]
            }
            _emit(last)
            continue
        manager = PortfolioManager.recover(path)
        if command == "context":
            last = manager.context(_as_of(argument))
        elif command == "report":
            last = manager.report(_as_of(argument))
        elif command == "propose":
            proposal = InvestmentProposal.model_validate_json(_read(Path(argument)))
            last = manager.propose(proposal)
        elif command == "mark":
            last = manager.mark(_as_of(argument))
        elif command == "reflect":
            request = ReflectionRequest.model_validate_json(_read(Path(argument)))
            last = manager.reflect(request)
        elif command == "feedback":
            note = FeedbackNote.model_validate_json(_read(Path(argument)))
            last = manager.feedback(note)
        elif command == "ingest":
            batch = IngestBatch.model_validate_json(_read(Path(argument)))
            last = manager.ingest(batch)
        else:
            message = f"unknown session command {command}"
            raise ValueError(message)
        _emit(last)
    return last


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _as_of(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        message = "timestamps must be timezone-aware"
        raise ValueError(message)
    return parsed.astimezone(UTC)


def _emit(payload: Json) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
