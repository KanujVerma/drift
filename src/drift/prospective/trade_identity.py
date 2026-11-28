"""Canonical identity for an Alpaca trade, retaining exchange and nanoseconds."""

import re
from datetime import UTC, datetime

_STAMP = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)$"
)


def canonical_trade_id(
    feed: str, symbol: str, stamp: str, exchange: str, trade_id: int
) -> str:
    match = _STAMP.fullmatch(stamp)
    if not match or not exchange or not exchange.isalnum() or trade_id < 0:
        raise ValueError("invalid Alpaca trade identity")
    moment = datetime.fromisoformat(
        match[1] + match[3].replace("Z", "+00:00")
    ).astimezone(UTC)
    fraction = (match[2] or "").ljust(9, "0")
    date_time = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return (
        f"alpaca-trades-v2-{feed}:{symbol}:{date_time}.{fraction}Z:"
        f"{exchange}:{trade_id}"
    )


def normalize_trade_id(value: str) -> str | None:
    try:
        prefix, symbol, rest = value.split(":", 2)
        stamp, exchange, raw_id = rest.rsplit(":", 2)
        if not prefix.startswith("alpaca-trades-v2-") or not raw_id.isdigit():
            return None
        return canonical_trade_id(
            prefix.removeprefix("alpaca-trades-v2-"),
            symbol,
            stamp,
            exchange,
            int(raw_id),
        )
    except ValueError, OverflowError:
        return None
