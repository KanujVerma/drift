"""Exploratory modeled cash-dividend accounting for reconstructed lane (Option B).

Models hypothetical cash dividend distributions for historical simulations
without fabricating M1c occurred corporate action events or verified settlements.
Every modeled dividend entitlement and cash flow is strictly:
- EXPLORATORY
- HYPOTHETICAL
- NON-PROMOTION-GRADE
"""

import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from hashlib import sha256
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
    source_id: NonBlankStr = "alpaca-corporate-actions-closed-world"
    response_sha256: SHA256Hash
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
                    "response_sha256": div.response_sha256,
                    "acknowledged_limitations": sorted(div.acknowledged_limitations),
                }
                for div in dividends
            ),
            key=lambda item: (item["symbol"], item["native_id"], item["ex_date"]),
        ),
    }
    return content_hash(payload)


def verify_dividend_source_payloads(
    dividends: Sequence[ExploratoryCashDividendTermsV1],
    source_payloads: Sequence[bytes],
) -> None:
    """Verify declared dividends against retained provider source bytes."""
    if not source_payloads:
        if dividends:
            raise ValueError(
                "dividend policy requires retained source bytes to verify authenticity"
            )
        return

    retained_entries: dict[tuple[str, str, str], dict[str, Any]] = {}
    payload_hashes: set[str] = set()

    for payload in source_payloads:
        payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
        p_hash = sha256(payload_bytes).hexdigest()
        payload_hashes.add(p_hash)
        try:
            doc = json.loads(payload_bytes.decode("utf-8"), parse_float=Decimal)
        except Exception as exc:
            raise ValueError(f"malformed source payload JSON: {exc}") from exc

        entries: list[Any] = []
        if isinstance(doc, dict):
            grouped = doc.get("corporate_actions")
            if isinstance(grouped, dict):
                entries = grouped.get("cash_dividends", [])
            elif "cash_dividends" in doc:
                entries = doc.get("cash_dividends", [])
            elif "dividends" in doc:
                entries = doc.get("dividends", [])
        elif isinstance(doc, list):
            entries = doc

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            prov_id = entry.get("id")
            corp_id = entry.get("corporate_action_id")
            if prov_id is not None and corp_id is not None and prov_id != corp_id:
                raise ValueError(
                    "conflicting corporate action identifiers in source payload"
                )
            nid = prov_id if prov_id is not None else corp_id
            sym = entry.get("symbol")
            if (
                not nid
                or not sym
                or not isinstance(nid, str)
                or not isinstance(sym, str)
            ):
                continue
            key = (p_hash, sym, nid)
            retained_entries[key] = entry

    for div in dividends:
        if div.response_sha256 not in payload_hashes:
            raise ValueError(
                f"dividend {div.native_id} ({div.symbol}) response_sha256 "
                f"{div.response_sha256} does not match any provided source payload"
            )
        key = (div.response_sha256, div.symbol, div.native_id)
        if key not in retained_entries:
            raise ValueError(
                f"dividend {div.native_id} for symbol {div.symbol} "
                "is absent from retained provider source payload"
            )
        entry = retained_entries[key]

        raw_rate = entry.get("rate")
        if raw_rate is None:
            raise ValueError(f"dividend {div.native_id} in source payload lacks rate")
        try:
            parsed_rate = Decimal(str(raw_rate))
        except Exception as exc:
            raise ValueError(f"invalid rate in source payload: {raw_rate}") from exc
        if parsed_rate != div.rate:
            raise ValueError(
                f"dividend rate mismatch for {div.native_id}: "
                f"source payload has {parsed_rate}, declared term has {div.rate}"
            )

        for field_name, term_date in (
            ("ex_date", div.ex_date),
            ("record_date", div.record_date),
            ("payable_date", div.payable_date),
        ):
            raw_val = entry.get(field_name)
            if raw_val is None:
                raise ValueError(
                    f"dividend {div.native_id} in source payload lacks {field_name}"
                )
            try:
                parsed_date = date.fromisoformat(str(raw_val))
            except Exception as exc:
                raise ValueError(
                    f"invalid date in source payload for {field_name}: {raw_val}"
                ) from exc
            if parsed_date != term_date:
                raise ValueError(
                    f"dividend {field_name} mismatch for {div.native_id}: "
                    f"source payload has {parsed_date}, declared term has {term_date}"
                )


class ExploratoryDividendPolicyV1(FrozenModel):
    """Declared cash dividends recognized in exploratory evaluation."""

    schema_version: Literal["1"] = "1"
    dividends: tuple[ExploratoryCashDividendTermsV1, ...] = ()
    terms_hash: SHA256Hash = Field(default="0" * 64)
    source_payloads: tuple[bytes, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_policy(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            raw_divs = data.get("dividends", ())
            raw_payloads = data.get("source_payloads", ())
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
                        or existing.response_sha256 != div.response_sha256
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

            canonical_payloads = tuple(
                item.encode("utf-8") if isinstance(item, str) else item
                for item in (
                    raw_payloads
                    if isinstance(raw_payloads, (tuple, list))
                    else (raw_payloads,)
                    if raw_payloads
                    else ()
                )
            )

            # Authenticate declared dividends against source payload bytes
            verify_dividend_source_payloads(canonical_dividends, canonical_payloads)

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
                "source_payloads": canonical_payloads,
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

    def is_policy_claim(self, claim: Any) -> bool:
        """Whether a pending cash claim was minted by this exploratory policy."""
        from drift.domain.economic_common import ActionKind

        term = self.terms_for(claim.security_id, claim.occurrence_id)
        if term is None:
            return False
        return (
            claim.source_id == term.source_id
            and getattr(claim, "action_kind", None) == ActionKind.REGULAR_CASH_DIVIDEND
            and getattr(claim, "component_id", None) == "cash_dividend"
            and claim.cash_per_share == term.rate
            and claim.payable_session == term.payable_date
        )
