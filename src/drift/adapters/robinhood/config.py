"""Robinhood agentic adapter configuration models (M16-1).

Specifies immutable configuration schemas for official Robinhood Agentic Trading
MCP adapter per ADR 0011.
"""

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import Field

from drift.domain.common import FrozenModel, NonBlankStr

ROBINHOOD_ADAPTER_SCHEMA_VERSION: Literal["1"] = "1"

__all__ = [
    "ROBINHOOD_ADAPTER_SCHEMA_VERSION",
    "RobinhoodAgenticConfigV1",
]


class RobinhoodAgenticConfigV1(FrozenModel):
    """Configuration for official Robinhood Agentic MCP brokerage adapter."""

    schema_version: Literal["1"] = ROBINHOOD_ADAPTER_SCHEMA_VERSION
    account_id: NonBlankStr
    dry_run: bool = True
    request_timeout_seconds: float = Field(default=10.0, gt=0.0)
    max_retries: int = Field(default=3, ge=0)
    symbol_map: Mapping[UUID, str] = Field(default_factory=dict)
