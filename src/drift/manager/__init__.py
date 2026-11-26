"""Offline supervised portfolio cycle.

The cycle accepts local inputs and a structured proposal, validates the
proposal against the book and an explicit simulation mandate, and applies
eligible fills through the retained portfolio accounting kernel.
"""

from drift.manager.service import PortfolioManager

__all__ = ["PortfolioManager"]
