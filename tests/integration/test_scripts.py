import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from drift.config.settings import LedgerSettings

PROJECT_ROOT = Path(__file__).parents[2]
INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_local_db.py"
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_ledger.py"


def _run_script(
    script: Path, *arguments: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd or PROJECT_ROOT,
    )


def test_ledger_settings_accept_only_an_immutable_local_path(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    settings = LedgerSettings(ledger_path=path)

    assert settings.ledger_path == path
    with pytest.raises(ValidationError):
        LedgerSettings(ledger_path="https://example.com/ledger.db")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        settings.ledger_path = tmp_path / "other.db"


def test_init_and_verify_scripts_operate_on_requested_nested_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "ledger.db"

    initialized = _run_script(INIT_SCRIPT, str(path))
    verified = _run_script(VERIFY_SCRIPT, str(path))

    assert initialized.returncode == 0, initialized.stderr
    assert path.is_file()
    assert "initialized" in initialized.stdout.lower()
    assert str(path) in initialized.stdout
    assert verified.returncode == 0, verified.stderr
    assert "verified" in verified.stdout.lower()
    assert "0 events" in verified.stdout
    assert str(path) in verified.stdout


def test_init_script_uses_a_local_default_path(tmp_path: Path) -> None:
    initialized = _run_script(INIT_SCRIPT, cwd=tmp_path)

    assert initialized.returncode == 0, initialized.stderr
    assert (tmp_path / ".drift" / "ledger.db").is_file()


def test_verify_script_rejects_a_missing_database_without_creating_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing" / "ledger.db"

    verified = _run_script(VERIFY_SCRIPT, str(path))

    assert verified.returncode != 0
    assert "not found" in verified.stderr.lower()
    assert not path.exists()


@pytest.mark.parametrize("script", [INIT_SCRIPT, VERIFY_SCRIPT])
def test_scripts_report_corrupt_database_without_traceback_or_file_changes(
    tmp_path: Path, script: Path
) -> None:
    path = tmp_path / "ledger.db"
    original = b"this is not a SQLite database\n"
    path.write_bytes(original)

    result = _run_script(script, str(path))

    assert result.returncode != 0
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "database" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()
    assert path.read_bytes() == original


def test_verify_script_returns_nonzero_for_integrity_failure(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    initialized = _run_script(INIT_SCRIPT, str(path))
    assert initialized.returncode == 0, initialized.stderr
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO audit_event_checkpoints (sequence, event_hash) VALUES (?, ?)",
            (1, "f" * 64),
        )

    verified = _run_script(VERIFY_SCRIPT, str(path))

    assert verified.returncode != 0
    assert "integrity" in verified.stderr.lower()
    assert "traceback" not in verified.stderr.lower()
