"""Exploratory modeled cash-dividend accounting for reconstructed lane (Option B).

Models hypothetical cash dividend distributions for historical simulations
without fabricating M1c occurred corporate action events or verified settlements.
Every modeled dividend entitlement and cash flow is strictly:
- EXPLORATORY
- HYPOTHETICAL
- NON-PROMOTION-GRADE
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from drift.domain.common import UUID7, FrozenModel, NonBlankStr, SHA256Hash
from drift.domain.economic_closed_world import exact_date
from drift.domain.evaluator_portfolio import CanonicalMoney, decimal_context
from drift.serialization.canonical import content_hash

EXPLORATORY_DIVIDEND_LIMITATION: NonBlankStr = (
    "hypothetical-exploratory-modeled-cash-dividends"
)
ZERO = Decimal("0")


class ExploratoryCashDividendTermsV1(FrozenModel):
    """One declared cash dividend terms record for exploratory simulation."""

    schema_version: Literal["1"] = "1"
    native_id: NonBlankStr
    security_id: UUID7
    symbol: NonBlankStr
    rate: CanonicalMoney
    ex_date: date
    record_date: date
    payable_date: date
    source_id: NonBlankStr = "alpaca-exploratory-dividends"
    response_sha256: SHA256Hash | None = None
    acknowledged_limitations: tuple[NonBlankStr, ...] = (
        EXPLORATORY_DIVIDEND_LIMITATION,
    )

    @field_validator("ex_date", "record_date", "payable_date")
    @classmethod
    def canonical_dates(cls, value: date) -> date:
        return exact_date(value)

    @model_validator(mode="after")
    def validate_terms(self) -> Self:
        with decimal_context():
            if self.rate <= ZERO:
                raise ValueError(f"rate must be strictly positive, got {self.rate}")
        if self.payable_date < self.ex_date:
            raise ValueError(
                f"payable date cannot precede ex-dividend date: "
                f"payable {self.payable_date}, ex {self.ex_date}"
            )
        return self


def exploratory_dividend_policy_hash(
    dividends: Sequence[ExploratoryCashDividendTermsV1],
) -> SHA256Hash:
    """Content-addressed semantic identity of an exploratory dividend policy."""
    payload = {
        "schema_version": "1",
        "dividends": sorted(
            (
                {
                    "native_id": div.native_id,
                    "security_id": str(div.security_id),
                    "symbol": div.symbol,
                    "rate": str(div.rate),
                    "ex_date": div.ex_date.isoformat(),
                    "record_date": div.record_date.isoformat(),
                    "payable_date": div.payable_date.isoformat(),
                    "source_id": div.source_id,
                }
                for div in dividends
            ),
            key=lambda item: (item["symbol"], item["native_id"], item["ex_date"]),
        ),
    }
    return content_hash(payload)


class ExploratoryDividendPolicyV1(FrozenModel):
    """Declared cash dividends recognized in exploratory evaluation."""

    schema_version: Literal["1"] = "1"
    dividends: tuple[ExploratoryCashDividendTermsV1, ...] = ()
    terms_hash: SHA256Hash = Field(default="0" * 64)

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_policy(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            import json

            raw_divs = data.get("dividends", ())
            declared_hash = data.get("terms_hash")
            if declared_hash == "0" * 64:
                declared_hash = None
            deduped: dict[tuple[UUID, str], ExploratoryCashDividendTermsV1] = {}
            for item in raw_divs:
                div = (
                    item
                    if isinstance(item, ExploratoryCashDividendTermsV1)
                    else ExploratoryCashDividendTermsV1.model_validate(item)
                    if not isinstance(item, Mapping)
                    or not isinstance(item.get("security_id"), str)
                    else ExploratoryCashDividendTermsV1.model_validate_json(
                        json.dumps(dict(item))
                    )
                )
                key = (div.security_id, div.native_id)
                if key in deduped:
                    existing = deduped[key]
                    if (
                        existing.rate != div.rate
                        or existing.ex_date != div.ex_date
                        or existing.payable_date != div.payable_date
                    ):
                        raise ValueError(
                            f"conflicting dividend terms for security "
                            f"{div.security_id} and native id {div.native_id}"
                        )
                else:
                    deduped[key] = div

            canonical_dividends = tuple(
                sorted(
                    deduped.values(),
                    key=lambda item: (item.symbol, item.ex_date, item.native_id),
                )
            )
            computed_hash = exploratory_dividend_policy_hash(canonical_dividends)
            if declared_hash is not None and declared_hash != computed_hash:
                raise ValueError(
                    f"terms hash mismatch: expected {computed_hash}, "
                    f"got {declared_hash}"
                )
            return {
                "schema_version": data.get("schema_version", "1"),
                "dividends": canonical_dividends,
                "terms_hash": computed_hash,
            }
        return data

    def is_handled(self, security_id: UUID, native_id: str) -> bool:
        """Whether a corporate action ID is accounted for under this policy."""
        return any(
            div.security_id == security_id and div.native_id == native_id
            for div in self.dividends
        )

    def dividends_in_window(
        self, security_id: UUID, start: date, end: date
    ) -> tuple[ExploratoryCashDividendTermsV1, ...]:
        """All dividends of security_id whose ex_date falls in [start, end]."""
        start_canonical, end_canonical = exact_date(start), exact_date(end)
        return tuple(
            div
            for div in self.dividends
            if div.security_id == security_id
            and start_canonical <= div.ex_date <= end_canonical
        )

    def terms_for(
        self, security_id: UUID, native_id: str
    ) -> ExploratoryCashDividendTermsV1 | None:
        """Find the terms record for (security_id, native_id)."""
        for div in self.dividends:
            if div.security_id == security_id and div.native_id == native_id:
                return div
        return None
