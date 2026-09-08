"""Route only pinned M1c history nodes through their archived interpreter."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _pinned_m1c import (  # noqa: E402
    HISTORY_MODULE,
    REPLAY_TEST_NAMES,
    PinnedArchiveCache,
    PinnedReplayError,
    _run_archived_node_in_root,
    is_pinned_m1c_node,
    verify_history_test_definitions,
    verify_protected_inputs,
)


def _is_history_item(item: pytest.Item) -> bool:
    return Path(str(item.fspath)).resolve() == _history_path().resolve()


def _history_path() -> Path:
    return Path(__file__).parent / "integration" / Path(HISTORY_MODULE).name


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    history_items = [item for item in items if _is_history_item(item)]
    if not history_items:
        return
    try:
        verify_protected_inputs()
        verify_history_test_definitions(_history_path())
    except PinnedReplayError as error:
        raise pytest.UsageError(str(error)) from error
    selected = {item.name for item in history_items}
    if not selected <= REPLAY_TEST_NAMES:
        raise pytest.UsageError(
            "pinned M1c replay received unexpected selected nodes; "
            f"selected {sorted(selected)!r}"
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    if os.environ.get("DRIFT_PINNED_REPLAY_CHILD") == "1":
        return
    session.config._pinned_m1c_archive = None  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    archive = getattr(session.config, "_pinned_m1c_archive", None)
    if archive is not None:
        archive.close()


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if os.environ.get("DRIFT_PINNED_REPLAY_CHILD") == "1":
        return None
    if not is_pinned_m1c_node(pyfuncitem.nodeid):
        return None
    try:
        verify_protected_inputs()
        archive = getattr(pyfuncitem.config, "_pinned_m1c_archive", None)
        if archive is None:
            archive = PinnedArchiveCache()
            pyfuncitem.config._pinned_m1c_archive = archive  # type: ignore[attr-defined]
        _run_archived_node_in_root(archive.root, pyfuncitem.nodeid)
    except PinnedReplayError as error:
        pytest.fail(str(error), pytrace=False)
    return True
