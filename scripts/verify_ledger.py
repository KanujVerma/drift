#!/usr/bin/env python3
"""Verify a local Drift SQLite ledger and report its event count."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from drift.config.settings import LedgerSettings
from drift.errors import LedgerIntegrityError
from drift.ledger.replay import replay_events
from drift.ledger.sqlite import SQLiteLedger


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=LedgerSettings().ledger_path,
        help="local SQLite database path (default: .drift/ledger.db)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Verify the requested database and return a process exit code."""
    arguments = _parser().parse_args(argv)
    settings = LedgerSettings(ledger_path=arguments.database)
    if not settings.ledger_path.is_file():
        print(f"Ledger not found: {settings.ledger_path}", file=sys.stderr)
        return 2
    ledger = SQLiteLedger(settings.ledger_path)
    try:
        events = replay_events(ledger)
    except LedgerIntegrityError as error:
        print(f"Ledger integrity check failed: {error}", file=sys.stderr)
        return 1
    print(f"Ledger verified: {settings.ledger_path} ({len(events)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
