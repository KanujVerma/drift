"""Unit tests for MarketDataStreamerProtocol and MockMarketDataStreamer (M15-3)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid7

import pytest

from drift.domain.paper_validation import MarketTickV1, build_market_tick
from drift.validation.feed import (
    MarketDataStreamerProtocol,
    MockMarketDataStreamer,
    NonMonotonicTimestampError,
)

NOW = datetime(2026, 3, 1, 14, 30, tzinfo=UTC)


def _make_tick(
    offset_seconds: int = 0, price: Decimal = Decimal("100.00")
) -> MarketTickV1:
    return build_market_tick(
        tick_id=uuid7(),
        security_id=uuid7(),
        timestamp=NOW + timedelta(seconds=offset_seconds),
        last_price=price,
        last_size=10,
    )


def test_streamer_protocol_structural_subtyping() -> None:
    """Verifies MockMarketDataStreamer conforms to MarketDataStreamerProtocol."""
    streamer = MockMarketDataStreamer()
    assert isinstance(streamer, MarketDataStreamerProtocol)


def test_streamer_sequential_consumption_and_exhaustion() -> None:
    """Verifies ticks are delivered chronologically until stream exhaustion."""
    t1 = _make_tick(offset_seconds=0, price=Decimal("100.00"))
    t2 = _make_tick(offset_seconds=1, price=Decimal("100.50"))
    t3 = _make_tick(offset_seconds=2, price=Decimal("101.00"))

    streamer = MockMarketDataStreamer([t1, t2, t3])
    assert streamer.remaining_count == 3
    assert streamer.processed_count == 0
    assert not streamer.is_exhausted()

    tick_out1 = streamer.next_tick()
    assert tick_out1 is not None
    assert tick_out1.tick_id == t1.tick_id
    assert streamer.remaining_count == 2
    assert streamer.processed_count == 1

    tick_out2 = streamer.next_tick()
    assert tick_out2 is not None
    assert tick_out2.tick_id == t2.tick_id

    tick_out3 = streamer.next_tick()
    assert tick_out3 is not None
    assert tick_out3.tick_id == t3.tick_id

    assert streamer.remaining_count == 0
    assert streamer.processed_count == 3
    assert streamer.is_exhausted()
    assert streamer.next_tick() is None


def test_streamer_reset_replay() -> None:
    """Verifies reset returns streamer cursor to start for deterministic replays."""
    t1 = _make_tick(offset_seconds=0)
    t2 = _make_tick(offset_seconds=5)
    streamer = MockMarketDataStreamer([t1, t2])

    streamer.next_tick()
    streamer.next_tick()
    assert streamer.is_exhausted()

    streamer.reset()
    assert not streamer.is_exhausted()
    assert streamer.remaining_count == 2
    assert streamer.processed_count == 0

    replayed1 = streamer.next_tick()
    assert replayed1 is not None
    assert replayed1.tick_id == t1.tick_id


def test_streamer_initial_monotonicity_enforcement() -> None:
    """Verifies out-of-order ticks raise NonMonotonicTimestampError."""
    t1 = _make_tick(offset_seconds=10)
    t2 = _make_tick(offset_seconds=5)  # precedes t1

    with pytest.raises(
        NonMonotonicTimestampError, match="non-monotonic timestamp sequence"
    ):
        MockMarketDataStreamer([t1, t2])


def test_streamer_dynamic_push_monotonicity_enforcement() -> None:
    """Verifies dynamic push_tick rejects past-dated ticks."""
    t1 = _make_tick(offset_seconds=10)
    streamer = MockMarketDataStreamer([t1])

    streamer.next_tick()

    # Attempting to push tick from the past
    past_tick = _make_tick(offset_seconds=5)
    with pytest.raises(NonMonotonicTimestampError, match="precedes previous timestamp"):
        streamer.push_tick(past_tick)

    # Pushing future tick succeeds
    future_tick = _make_tick(offset_seconds=15)
    streamer.push_tick(future_tick)
    assert streamer.remaining_count == 1
    consumed_future = streamer.next_tick()
    assert consumed_future is not None
    assert consumed_future.tick_id == future_tick.tick_id
