"""Serialize writes to the two books belonging to one pilot state directory."""

import fcntl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Concatenate, cast

_held: ContextVar[frozenset[Path]] = ContextVar("pilot_locks", default=frozenset())


@contextmanager
def pilot_lock(state: Path) -> Iterator[None]:
    state = state.resolve()
    held = _held.get()
    if state in held:
        yield
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".pilot.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("pilot state is busy") from None
        token = _held.set(held | {state})
        try:
            yield
        finally:
            _held.reset(token)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def serialized[**P, R](
    function: Callable[Concatenate[Path, P], R],
) -> Callable[Concatenate[Path, P], R]:
    @wraps(function)
    def wrapped(state: Path, *args: P.args, **kwargs: P.kwargs) -> R:
        with pilot_lock(state):
            return function(state, *args, **kwargs)

    return cast(Callable[Concatenate[Path, P], R], wrapped)
