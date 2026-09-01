"""Local-file configuration for the Drift evidence ledger."""

from pathlib import Path

from drift.domain.common import FrozenModel


class LedgerSettings(FrozenModel):
    """Immutable configuration for one local SQLite ledger file."""

    ledger_path: Path = Path(".drift/ledger.db")
