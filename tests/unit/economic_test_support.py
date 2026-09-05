"""Shared, literal fixtures for M1c economic query contract tests."""

from datetime import UTC, datetime
from uuid import UUID

from drift.domain.economic_common import (
    CashComponentV1,
    EconomicUnitBasisV1,
    PositiveRatioV1,
)
from drift.domain.temporal import AvailabilityChannelV1, ChannelKind

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def uid(suffix: int) -> UUID:
    """Return a fixed UUIDv7, derived only from a fixture suffix."""
    return UUID(f"019b8240-0000-7000-8000-{suffix:012d}")


def instant(day: int) -> datetime:
    """Return an aware UTC instant in the hand-checked fixture window."""
    return datetime(2026, 1, day, 12, tzinfo=UTC)


def public_channel() -> AvailabilityChannelV1:
    """Return the fixed channel used by market-query fixtures."""
    return AvailabilityChannelV1(
        kind=ChannelKind.PUBLIC,
        identifier="issuer-filings",
        version="v1",
    )


def cash_component(component_id: str = "cash-1") -> CashComponentV1:
    """Return a literal source-reported cash component for projection tests."""
    return CashComponentV1(
        kind="cash",
        component_id=component_id,
        amount="1.25",
        currency_namespace="ISO-4217",
        currency_code="USD",
        unit_basis=EconomicUnitBasisV1(
            security_id=uid(1),
            denominator=PositiveRatioV1(numerator="1", denominator="1"),
            share_basis="predecessor_pre_action",
        ),
        amount_basis="gross",
        applicability="ordinary_passive_holder",
        conditions=(),
    )
