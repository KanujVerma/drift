"""Durable research-only suggestions outside the simulated trading universe."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from drift.prospective.collect import UserSuggestion
from drift.research.universe import universe_by_symbol

_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}\Z")


def _record_hash(record: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def store_suggestions(
    state: Path, suggestions: tuple[UserSuggestion, ...], received_at: datetime
) -> None:
    if received_at.tzinfo is None:
        raise ValueError("suggestion receipt must be timezone-aware")
    known = universe_by_symbol()
    root = state / "external-suggestions"
    for item in suggestions:
        if item.symbol in known:
            continue
        if (
            not _SYMBOL.fullmatch(item.symbol)
            or not item.summary.strip()
            or item.observed_at.tzinfo is None
        ):
            raise ValueError("external suggestion has invalid symbol, text, or time")
        observed = item.observed_at.astimezone(UTC)
        received = (item.received_at or received_at).astimezone(UTC)
        if observed > received:
            raise ValueError("external suggestion was observed after its receipt")
        identity = {
            "symbol": item.symbol,
            "summary": item.summary,
            "observed_at": observed.isoformat(),
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        record = {
            **identity,
            "kind": "suggestion",
            "available_at": received.isoformat(),
            "evidence_id": f"suggestion:{digest}",
            "limitation": (
                "user-supplied observation time; suggestion is not market evidence"
            ),
        }
        record["record_hash"] = _record_hash(record)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{digest}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(existing, dict)
                or any(existing.get(k) != v for k, v in identity.items())
                or not isinstance(existing.get("record_hash"), str)
                or _record_hash(
                    {k: v for k, v in existing.items() if k != "record_hash"}
                )
                != existing["record_hash"]
            ):
                raise ValueError(
                    "external suggestion identity conflicts with recorded input"
                ) from None


def visible_suggestions(state: Path, as_of: datetime) -> list[dict[str, str]]:
    root = state / "external-suggestions"
    if not root.exists():
        return []
    rows: list[dict[str, str]] = []
    for path in sorted(root.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(item, dict) or any(
            not isinstance(item.get(k), str)
            for k in (
                "symbol",
                "summary",
                "observed_at",
                "available_at",
                "evidence_id",
                "kind",
                "limitation",
                "record_hash",
            )
        ):
            raise ValueError("stored external suggestion is invalid")
        identity = {key: item[key] for key in ("symbol", "summary", "observed_at")}
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        if (
            path.stem != digest
            or item["evidence_id"] != f"suggestion:{digest}"
            or _record_hash({k: v for k, v in item.items() if k != "record_hash"})
            != item["record_hash"]
        ):
            raise ValueError("stored external suggestion identity does not match")
        observed = datetime.fromisoformat(item["observed_at"])
        available = datetime.fromisoformat(item["available_at"])
        if observed.tzinfo is None or available.tzinfo is None or observed > available:
            raise ValueError("stored external suggestion timestamps are invalid")
        if available <= as_of and observed <= as_of:
            rows.append(
                {
                    key: item[key]
                    for key in (
                        "symbol",
                        "summary",
                        "observed_at",
                        "available_at",
                        "evidence_id",
                        "kind",
                        "limitation",
                    )
                }
            )
    return rows
