"""Fictional bounded SIP pages; no market source or result is certified."""

import json
from datetime import UTC, date, datetime
from struct import pack
from typing import Any

import pytest

from drift.adapters import alpaca_exploratory as alpaca

DATES = (date(2023, 7, 3), date(2023, 7, 5))
TIMESTAMPS = {
    day: datetime(day.year, day.month, day.day, 4, tzinfo=UTC) for day in DATES
}


def _fictional_tzif() -> bytes:
    transitions = (
        int(datetime(2023, 3, 12, 7, tzinfo=UTC).timestamp()),
        int(datetime(2023, 11, 5, 6, tzinfo=UTC).timestamp()),
    )
    names = b"EST\0EDT\0"
    return (
        b"TZif\0"
        + b"\0" * 15
        + pack(">6l", 0, 0, 0, 2, 2, len(names))
        + b"".join(pack(">l", value) for value in transitions)
        + bytes((1, 0))
        + pack(">lbb", -18_000, 0, 0)
        + pack(">lbb", -14_400, 1, 4)
        + names
    )


def _parameters(symbol: str) -> dict[str, str]:
    return {
        "symbols": symbol,
        "start": "2023-07-03",
        "end": "2023-07-05",
        "feed": "sip",
        "adjustment": "raw",
        "timeframe": "1Day",
        "asof": "-",
        "currency": "USD",
        "sort": "asc",
        "limit": "1000",
    }


def _bar(day: date) -> dict[str, Any]:
    return {
        "t": TIMESTAMPS[day].isoformat(),
        "o": "100",
        "h": "102",
        "l": "99",
        "c": "101",
        "v": "1000",
        "n": 50,
    }


def _page(symbol: str, rows: list[dict[str, Any]], token: str | None) -> bytes:
    return json.dumps({"bars": {symbol: rows}, "next_page_token": token}).encode()


def _pages(symbol: str) -> tuple[alpaca.AlpacaDiagnosticBarPage, ...]:
    return (
        alpaca.AlpacaDiagnosticBarPage(None, _page(symbol, [_bar(DATES[0])], "next")),
        alpaca.AlpacaDiagnosticBarPage("next", _page(symbol, [_bar(DATES[1])], None)),
    )


@pytest.mark.parametrize(
    "symbol",
    (
        "VOO",
        "IJH",
        "IJR",
        "QQQ",
        "VEA",
        "VWO",
        "SHY",
        "IEF",
        "TLT",
        "TIP",
        "LQD",
        "GLD",
    ),
)
def test_each_synthetic_symbol_has_complete_diagnostic_pages(symbol: str) -> None:
    result = alpaca.parse_alpaca_diagnostic_bar_pages(
        pages=_pages(symbol),
        parameters=_parameters(symbol),
        expected_timestamps=TIMESTAMPS,
        timezone_tzif=_fictional_tzif(),
    )
    assert tuple(bar.session_date for bar in result.bars) == DATES
    assert all(bar.symbol == symbol for bar in result.bars)
    assert result.snapshot_status == "SNAPSHOT_UNVERIFIED"
    assert result.grade == "diagnostic"


@pytest.mark.parametrize(
    "defect",
    [
        "missing_page",
        "wrong_token",
        "duplicate_date",
        "unexpected_symbol",
        "bad_basis",
        "wrong_timestamp",
        "bad_price",
        "empty_nonterminal",
        "missing_token_field",
    ],
)
def test_synthetic_page_gaps_and_mismatches_fail_closed(defect: str) -> None:
    pages = list(_pages("VOO"))
    parameters = _parameters("VOO")
    if defect == "missing_page":
        pages.pop()
    elif defect == "wrong_token":
        pages[1] = alpaca.AlpacaDiagnosticBarPage("other", pages[1].body)
    elif defect == "duplicate_date":
        pages[1] = alpaca.AlpacaDiagnosticBarPage(
            "next", _page("VOO", [_bar(DATES[0])], None)
        )
    elif defect == "unexpected_symbol":
        pages[1] = alpaca.AlpacaDiagnosticBarPage(
            "next", _page("QQQ", [_bar(DATES[1])], None)
        )
    elif defect == "bad_basis":
        parameters["adjustment"] = "all"
    elif defect == "wrong_timestamp":
        wrong = _bar(DATES[1]) | {"t": "2023-07-05T05:00:00Z"}
        pages[1] = alpaca.AlpacaDiagnosticBarPage("next", _page("VOO", [wrong], None))
    elif defect == "bad_price":
        wrong = _bar(DATES[1]) | {"l": "103"}
        pages[1] = alpaca.AlpacaDiagnosticBarPage("next", _page("VOO", [wrong], None))
    elif defect == "empty_nonterminal":
        pages[0] = alpaca.AlpacaDiagnosticBarPage(None, _page("VOO", [], "next"))
    else:
        pages[1] = alpaca.AlpacaDiagnosticBarPage(
            "next", json.dumps({"bars": {"VOO": [_bar(DATES[1])]}}).encode()
        )
    with pytest.raises(alpaca.AlpacaBridgeIncompleteError):
        alpaca.parse_alpaca_diagnostic_bar_pages(
            pages=tuple(pages),
            parameters=parameters,
            expected_timestamps=TIMESTAMPS,
            timezone_tzif=_fictional_tzif(),
        )


def test_diagnostic_window_cannot_claim_a_verified_snapshot() -> None:
    with pytest.raises(TypeError):
        alpaca.AlpacaDiagnosticBarWindow(bars=(), snapshot_status="VERIFIED")  # type: ignore[call-arg]


def test_transient_page_repr_does_not_expose_body_or_token() -> None:
    page = alpaca.AlpacaDiagnosticBarPage(
        "synthetic-secret-token", b"private-bar-bytes"
    )
    assert "synthetic-secret-token" not in repr(page)
    assert "private-bar-bytes" not in repr(page)
