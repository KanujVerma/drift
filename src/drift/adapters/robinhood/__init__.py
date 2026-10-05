"""Official Robinhood Agentic Trading MCP adapter (M16).

Provides configuration schemas, transport protocols, deterministic mock transports,
and broker adapter implementations for Robinhood Agentic MCP tools per ADR 0011.
"""

from drift.adapters.robinhood.adapter import RobinhoodAgenticAdapter
from drift.adapters.robinhood.config import (
    ROBINHOOD_ADAPTER_SCHEMA_VERSION,
    RobinhoodAgenticConfigV1,
)
from drift.adapters.robinhood.transport import (
    MockRobinhoodMcpTransport,
    RobinhoodMcpError,
    RobinhoodMcpTransportProtocol,
)

__all__ = [
    "MockRobinhoodMcpTransport",
    "ROBINHOOD_ADAPTER_SCHEMA_VERSION",
    "RobinhoodAgenticAdapter",
    "RobinhoodAgenticConfigV1",
    "RobinhoodMcpError",
    "RobinhoodMcpTransportProtocol",
]
