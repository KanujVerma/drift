"""Streaming market feed protocol and deterministic mock streamer (M15-3).

Specifies MarketDataStreamerProtocol interface and provides a reference
MockMarketDataStreamer enforcing temporal monotonicity and causal tick processing.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from drift.domain.paper_validation import MarketTickV1
from drift.errors import DriftError

__all__ = [
    "FeedEmptyError",
    "FeedError",
    "MarketDataStreamerProtocol",
    "MockMarketDataStreamer",
    "NonMonotonicTimestampError",
]


class FeedError(DriftError):
    """Base exception for market data feed operations."""


class NonMonotonicTimestampError(FeedError):
    """Raised when a market tick timestamp is earlier than previous ticks."""


class FeedEmptyError(FeedError):
    """Raised when next_tick is requested from an exhausted market feed."""


@runtime_checkable
class MarketDataStreamerProtocol(Protocol):
    """Protocol for streaming real-time or simulated market data ticks."""

    def next_tick(self) -> MarketTickV1 | None:
        """Return the next market tick, or None if the stream is exhausted."""
        ...

    def is_exhausted(self) -> bool:
        """Return True if no further ticks are available in the stream."""
        ...

    def reset(self) -> None:
        """Reset stream pointer to initial state for deterministic replay."""
        ...


class MockMarketDataStreamer:
    """Deterministic in-memory streamer enforcing temporal tick monotonicity."""

    def __init__(self, initial_ticks: Sequence[MarketTickV1] = ()) -> None:
        self._initial_ticks: list[MarketTickV1] = list(initial_ticks)
        self._queue: list[MarketTickV1] = list(initial_ticks)
        self._cursor: int = 0
        self._last_timestamp: datetime | None = None
        self._validate_initial_monotonicity()

    def _validate_initial_monotonicity(self) -> None:
        last: datetime | None = None
        for tick in self._initial_ticks:
            if last is not None and tick.timestamp < last:
                raise NonMonotonicTimestampError(
                    f"non-monotonic timestamp sequence: {tick.timestamp} < {last}"
                )
            last = tick.timestamp

    def push_tick(self, tick: MarketTickV1) -> None:
        """Enqueue a market tick, validating monotonicity against the latest tick."""
        if self._last_timestamp is not None and tick.timestamp < self._last_timestamp:
            raise NonMonotonicTimestampError(
                f"incoming tick timestamp {tick.timestamp} precedes "
                f"previous timestamp {self._last_timestamp}"
            )
        self._queue.append(tick)
        self._initial_ticks.append(tick)

    def next_tick(self) -> MarketTickV1 | None:
        """Deliver the next chronological market tick."""
        if self._cursor >= len(self._queue):
            return None

        tick = self._queue[self._cursor]
        self._cursor += 1
        self._last_timestamp = tick.timestamp
        return tick

    def is_exhausted(self) -> bool:
        """Whether all queued ticks have been consumed."""
        return self._cursor >= len(self._queue)

    def reset(self) -> None:
        """Reset streamer to initial sequence for replay testing."""
        self._queue = list(self._initial_ticks)
        self._cursor = 0
        self._last_timestamp = None

    @property
    def remaining_count(self) -> int:
        """Number of ticks remaining in the queue."""
        return max(0, len(self._queue) - self._cursor)

    @property
    def processed_count(self) -> int:
        """Number of ticks consumed so far."""
        return self._cursor
