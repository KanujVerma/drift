#!/usr/bin/env python3
"""Initialize and verify a local Drift SQLite ledger."""

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from drift.config.settings import LedgerSettings
from drift.errors import DriftError, LedgerIntegrityError
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
    """Initialize the requested database and return a process exit code."""
    arguments = _parser().parse_args(argv)
    settings = LedgerSettings(ledger_path=arguments.database)
    try:
        settings.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger = SQLiteLedger(settings.ledger_path)
        ledger.verify_chain()
    except LedgerIntegrityError as error:
        print(f"Ledger integrity check failed: {error}", file=sys.stderr)
        return 1
    except (DriftError, sqlite3.Error, OSError) as error:
        print(f"Ledger database error: {error}", file=sys.stderr)
        return 1
    print(f"Ledger initialized and verified: {settings.ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
