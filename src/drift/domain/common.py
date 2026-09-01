"""Shared validation primitives for immutable research domain models."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    PlainSerializer,
    PlainValidator,
    StringConstraints,
)

from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import JSONValue, canonical_data


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamps must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC)


def _require_uuid7(value: UUID) -> UUID:
    if value.version != 7:
        msg = "identifiers must be UUIDv7 values"
        raise ValueError(msg)
    return value


def _freeze_json(value: object) -> ImmutableJSONValue:
    try:
        return _freeze_canonical_value(canonical_data(value))
    except CanonicalSerializationError as error:
        raise ValueError(str(error)) from error


def _freeze_canonical_value(value: JSONValue) -> ImmutableJSONValue:
    if isinstance(value, list):
        return tuple(_freeze_canonical_value(item) for item in value)
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_canonical_value(item) for key, item in value.items()}
        )
    return value


def _thaw_json(value: ImmutableJSONValue) -> JSONValue:
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    return value


type ImmutableJSONValue = (
    None
    | bool
    | int
    | float
    | str
    | tuple["ImmutableJSONValue", ...]
    | Mapping[str, "ImmutableJSONValue"]
)
"""An immutable value compatible with canonical JSON serialization."""

type ImmutableJSON = Annotated[
    ImmutableJSONValue,
    PlainValidator(_freeze_json),
    PlainSerializer(_thaw_json, return_type=object),
]
"""A JSON value copied into immutable maps and tuples during validation."""

type NonBlankStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
"""A required string with non-whitespace content."""

type SHA256Hash = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64),
]
"""A lowercase hexadecimal SHA-256 digest."""

type UTCDateTime = Annotated[datetime, AfterValidator(_normalize_utc)]
"""A timezone-aware datetime normalized to UTC."""

type UUID7 = Annotated[UUID, AfterValidator(_require_uuid7)]
"""A UUIDv7 identifier."""


class FrozenModel(BaseModel):
    """Strict immutable base model for Drift provenance objects."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through validation while preserving normal shallow-copy semantics."""
        if update is None and not deep:
            return super().model_copy()
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update is not None:
            values.update(update)
        return type(self).model_validate(values)
