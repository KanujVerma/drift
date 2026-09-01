from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel

from drift.errors import CanonicalSerializationError
from drift.serialization.canonical import canonical_data, canonical_json, content_hash


class Status(Enum):
    READY = "ready"


class Measurement(BaseModel):
    name: str
    amount: Decimal


def test_mapping_order_does_not_change_canonical_bytes() -> None:
    assert canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_datetime_is_normalized_to_utc() -> None:
    value = datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))

    assert canonical_json(value) == b'"2026-01-01T00:00:00.000000Z"'


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(CanonicalSerializationError):
        canonical_json(datetime(2026, 1, 1))


def test_supported_scalars_and_pydantic_models_are_normalized() -> None:
    value = {
        "model": Measurement(name="alpha", amount=Decimal("1.50")),
        "date": date(2026, 1, 2),
        "enum": Status.READY,
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "path": Path("evidence/result.json"),
        "decimal": Decimal("2.50"),
        "none": None,
    }

    assert canonical_data(value) == {
        "model": {"name": "alpha", "amount": "1.50"},
        "date": "2026-01-02",
        "enum": "ready",
        "uuid": "12345678-1234-5678-1234-567812345678",
        "path": "evidence/result.json",
        "decimal": "2.50",
        "none": None,
    }


def test_sets_are_sorted_by_canonical_json_for_mixed_json_values() -> None:
    value = {"values": {"alpha", 10, 2, None}}

    assert canonical_json(value) == b'{"values":["alpha",10,2,null]}'


def test_lists_and_tuples_are_normalized_as_json_arrays() -> None:
    value = {"list": [1, "two"], "tuple": ("alpha", None)}

    assert canonical_json(value) == b'{"list":[1,"two"],"tuple":["alpha",null]}'


def test_bool_and_int_have_distinct_canonical_representations() -> None:
    assert canonical_json(True) == b"true"
    assert canonical_json(1) == b"1"
    assert content_hash(True) != content_hash(1)


def test_canonicalization_does_not_mutate_caller_input() -> None:
    items = [3, 1]
    value = {"nested": {"items": items}, "flag": True}

    normalized = canonical_data(value)

    assert normalized == {"flag": True, "nested": {"items": [3, 1]}}
    assert value == {"nested": {"items": [3, 1]}, "flag": True}
    assert normalized is not value
    items.append(2)
    assert normalized == {"flag": True, "nested": {"items": [3, 1]}}


@pytest.mark.parametrize("value", [iter([1, 2]), range(2)])
def test_unsupported_general_iterables_are_rejected(value: object) -> None:
    with pytest.raises(CanonicalSerializationError, match="unsupported type"):
        canonical_json(value)


@pytest.mark.parametrize(
    "value",
    [
        {1: "value"},
        {"key": "value", 1: "value"},
        float("nan"),
        float("inf"),
        b"bytes",
        object(),
    ],
)
def test_unsupported_values_are_rejected(value: object) -> None:
    with pytest.raises(CanonicalSerializationError):
        canonical_json(value)


def test_content_hash_is_stable_and_uses_sha256_hex() -> None:
    assert content_hash({"b": 2, "a": 1}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
