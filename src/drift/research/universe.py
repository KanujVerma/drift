"""Configured US research universe.

CIKs were read from the SEC company-ticker file on 2026-11-27, except
QQQ and MDY, which are the filing trusts named in their submissions
documents. Those two trusts have no companyfacts feed. This list is
research eligibility. It is not the prospective trading mandate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ResearchName:
    """One symbol the discovery workflow may investigate."""

    symbol: str
    cik: str
    name: str
    kind: Literal["stock", "etf"]
    sector: str


# Order is sector coverage, not a ranking and not a trade list.
RESEARCH_UNIVERSE: tuple[ResearchName, ...] = (
    ResearchName("AAPL", "0000320193", "Apple Inc.", "stock", "technology"),
    ResearchName("MSFT", "0000789019", "Microsoft Corp", "stock", "technology"),
    ResearchName("AMZN", "0001018724", "Amazon.com Inc.", "stock", "discretionary"),
    ResearchName("JPM", "0000019617", "JPMorgan Chase & Co", "stock", "financials"),
    ResearchName("JNJ", "0000200406", "Johnson & Johnson", "stock", "health"),
    ResearchName("XOM", "0002115436", "ExxonMobil Holdings Corp", "stock", "energy"),
    ResearchName("CAT", "0000018230", "Caterpillar Inc.", "stock", "industrials"),
    ResearchName("PG", "0000080424", "Procter & Gamble Co", "stock", "staples"),
    ResearchName("NEE", "0000753308", "NextEra Energy Inc.", "stock", "utilities"),
    ResearchName("LIN", "0001707925", "Linde plc", "stock", "materials"),
    ResearchName("SPY", "0000884394", "SPDR S&P 500 ETF Trust", "etf", "broad"),
    ResearchName("QQQ", "0001067839", "Invesco QQQ Trust", "etf", "growth"),
    ResearchName("MDY", "0000936958", "SPDR S&P MidCap 400 ETF Trust", "etf", "midcap"),
)

# The original four-name book. Discovery may research other names without
# adding them here. The prospective mandate is a separate object.
ORIGINAL_TRADING_SYMBOLS: tuple[str, ...] = ("AAPL", "MSFT", "JNJ", "SPY")


def universe_by_symbol() -> dict[str, ResearchName]:
    """Map each configured symbol to its research identity."""
    return {item.symbol: item for item in RESEARCH_UNIVERSE}
