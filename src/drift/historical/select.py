"""Window rules fixed before any model sees a case.

Blocks are consecutive benchmark closes. The earliest block that matches a
regime is kept. A larger move later in the pool is not preferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

BLOCK_LENGTH = 12
POOL_START = date(2021, 1, 4)
POOL_END = date(2025, 12, 31)
# JNJ distributed Kenvue shares in this span. Those blocks stay ineligible
# because cash and share corporate actions are not settled by this replay.
CORPORATE_ACTION_EXCLUSION = (date(2023, 8, 14), date(2023, 8, 25))

BULL_RETURNS = (Decimal("0.04"), Decimal("0.03"), Decimal("0.02"))
BULL_DRAWDOWN_FLOOR = Decimal("-0.03")
BEAR_RETURNS = (Decimal("-0.04"), Decimal("-0.03"), Decimal("-0.02"))
SIDE_ABS = (Decimal("0.01"), Decimal("0.015"), Decimal("0.02"))
SIDE_BANDS = (Decimal("0.02"), Decimal("0.03"), Decimal("0.04"))


@dataclass(frozen=True)
class Close:
    """One benchmark close on a trading date."""

    day: date
    level: Decimal


@dataclass(frozen=True)
class BlockStats:
    """Path statistics of one candidate block. These are not model results."""

    total_return: Decimal
    max_drawdown: Decimal
    max_runup: Decimal


@dataclass(frozen=True)
class Window:
    """One selected regime. The threshold index is the precommitted rule."""

    regime: str
    warmup_day: date
    decision_days: tuple[date, ...]
    settlement_day: date
    threshold_index: int
    total_return: Decimal
    max_drawdown: Decimal
    max_runup: Decimal


def select_windows(
    closes: tuple[Close, ...],
    *,
    forbidden: frozenset[date] | None = None,
) -> dict[str, Window]:
    """Return the earliest eligible block for each regime that can be filled."""
    blocked = set(forbidden or ())
    ordered = _pool(closes)
    blocks = _blocks(ordered, blocked)
    chosen: dict[str, Window] = {}
    used: set[int] = set()
    for threshold in range(3):
        for regime in ("bullish", "bearish", "sideways"):
            if regime in chosen:
                continue
            for index, (stats, window) in enumerate(blocks):
                if index in used or not _matches(regime, stats, threshold):
                    continue
                chosen[regime] = Window(
                    regime=regime,
                    warmup_day=window[0],
                    decision_days=window[1],
                    settlement_day=window[2],
                    threshold_index=threshold,
                    total_return=stats.total_return,
                    max_drawdown=stats.max_drawdown,
                    max_runup=stats.max_runup,
                )
                used.add(index)
                break
    return chosen


def _pool(closes: tuple[Close, ...]) -> tuple[Close, ...]:
    rows = [item for item in closes if POOL_START <= item.day <= POOL_END]
    rows.sort(key=lambda item: item.day)
    days = [item.day for item in rows]
    if len(days) != len(set(days)):
        message = "benchmark closes must have unique dates"
        raise ValueError(message)
    if any(item.level <= 0 for item in rows):
        message = "benchmark closes must be strictly positive"
        raise ValueError(message)
    return tuple(rows)


def _blocks(
    closes: tuple[Close, ...],
    forbidden: set[date],
) -> list[tuple[BlockStats, tuple[date, tuple[date, ...], date]]]:
    found: list[tuple[BlockStats, tuple[date, tuple[date, ...], date]]] = []
    start = BLOCK_LENGTH
    while start + BLOCK_LENGTH < len(closes):
        warmup = closes[start - 1]
        decision = closes[start : start + BLOCK_LENGTH]
        settlement = closes[start + BLOCK_LENGTH]
        days = tuple(item.day for item in decision)
        span = (warmup.day, *days, settlement.day)
        if any(_excluded(day, forbidden) for day in span):
            start += BLOCK_LENGTH
            continue
        found.append(
            (
                _stats(tuple(item.level for item in decision)),
                (warmup.day, days, settlement.day),
            )
        )
        start += BLOCK_LENGTH
    return found


def _excluded(day: date, forbidden: set[date]) -> bool:
    if day in forbidden:
        return True
    first, last = CORPORATE_ACTION_EXCLUSION
    return first <= day <= last


def _stats(levels: tuple[Decimal, ...]) -> BlockStats:
    first = levels[0]
    total = (levels[-1] - first) / first
    peak = first
    trough = first
    drawdown = Decimal(0)
    runup = Decimal(0)
    for level in levels:
        if level > peak:
            peak = level
        if level < trough:
            trough = level
        drop = (level - peak) / peak
        rise = (level - trough) / trough
        if drop < drawdown:
            drawdown = drop
        if rise > runup:
            runup = rise
    return BlockStats(total_return=total, max_drawdown=drawdown, max_runup=runup)


def _matches(regime: str, stats: BlockStats, threshold: int) -> bool:
    if regime == "bullish":
        return (
            stats.total_return >= BULL_RETURNS[threshold]
            and stats.max_drawdown > BULL_DRAWDOWN_FLOOR
        )
    if regime == "bearish":
        return stats.total_return <= BEAR_RETURNS[threshold]
    if regime == "sideways":
        band = SIDE_BANDS[threshold]
        return (
            abs(stats.total_return) <= SIDE_ABS[threshold]
            and stats.max_drawdown > -band
            and stats.max_runup < band
        )
    message = f"unknown regime {regime}"
    raise ValueError(message)
