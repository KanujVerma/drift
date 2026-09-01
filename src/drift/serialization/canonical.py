"""Deterministic conversion of supported values into canonical JSON."""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Never
from uuid import UUID

from pydantic import BaseModel

from drift.errors import CanonicalSerializationError

type JSONValue = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


def canonical_data(value: object) -> JSONValue:
    """Normalize a supported value into the JSON data model."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            _reject(value, "non-finite floats are not supported")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            _reject(value, "naive datetimes are not supported")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return canonical_data(value.value)
    if isinstance(value, UUID | Path):
        return str(value)
    if isinstance(value, BaseModel):
        return canonical_data(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return _canonical_mapping(value)
    if isinstance(value, (list, tuple)):
        return [canonical_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return _canonical_set(value)
    if isinstance(value, bytes):
        _reject(value, "bytes are not supported")
    _reject(value, f"unsupported type: {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    """Serialize a value as canonical UTF-8 JSON bytes."""
    return json.dumps(
        canonical_data(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_hash(value: object) -> str:
    """Return the SHA-256 hash of a value's canonical JSON bytes."""
    return sha256(canonical_json(value)).hexdigest()


def _canonical_mapping(value: Mapping[object, object]) -> dict[str, JSONValue]:
    keys: list[str] = []
    for key in value:
        if not isinstance(key, str):
            _reject(key, "mapping keys must be strings")
        keys.append(key)
    normalized: dict[str, JSONValue] = {}
    for key in sorted(keys):
        normalized[key] = canonical_data(value[key])
    return normalized


def _canonical_set(value: set[object] | frozenset[object]) -> list[JSONValue]:
    normalized = [canonical_data(item) for item in value]
    return sorted(normalized, key=canonical_json)


def _reject(value: object, reason: str) -> Never:
    message = f"Cannot canonically serialize {value!r}: {reason}"
    raise CanonicalSerializationError(message)
