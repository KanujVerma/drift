"""Exact-input validation reuse cannot confer trust on changed evidence."""

from __future__ import annotations

import json
from contextlib import nullcontext

import pytest
from pydantic import TypeAdapter, ValidationError
from test_evaluator_reconstruction import _ready_harness, build_from_harness

from drift.domain import evaluator_reconstruction as R
from drift.serialization.canonical import canonical_json

Observation = R.ExploratoryReconstructedSessionObservationV1


@pytest.fixture
def original() -> bytes:
    return canonical_json(build_from_harness(_ready_harness()))


def test_identical_json_observations_validate_once_per_scope(
    original: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original_hash = R.exploratory_reconstruction_hash

    def measured(value: Observation) -> str:
        nonlocal calls
        calls += 1
        return original_hash(value)

    monkeypatch.setattr(R, "exploratory_reconstruction_hash", measured)
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        adapter = TypeAdapter(tuple[Observation, ...])
        values = adapter.validate_json(b"[" + b",".join([original] * 10) + b"]")
        assert len(values) == 10
        assert all(canonical_json(value) == original for value in values)
        assert all(a is not b for a, b in zip(values, values[1:], strict=False))
    assert calls == 1, "identical complete observation was validated repeatedly"


def test_changed_body_cannot_borrow_a_valid_claimed_hash(original: bytes) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        Observation.model_validate_json(original)
        changed = json.loads(original)
        changed["fields"][0]["source_value"] = "12345"
        with pytest.raises(ValidationError, match="reconstruction hash mismatch"):
            Observation.model_validate_json(json.dumps(changed))
        changed = json.loads(original)
        changed["source_context_hash"] = "b" * 64
        with pytest.raises(ValidationError, match="reconstruction hash mismatch"):
            Observation.model_validate_json(json.dumps(changed))


def test_decimal_representation_is_not_a_cache_equality_shortcut(
    original: bytes,
) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        Observation.model_validate_json(original)
        changed = json.loads(original)
        changed["fields"][0]["source_value"] += "0"
        with pytest.raises(ValidationError):
            Observation.model_validate_json(json.dumps(changed))


def test_returned_objects_cannot_poison_private_cached_values(original: bytes) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        first = Observation.model_validate_json(original)
        object.__setattr__(first, "currency", "POISON")
        object.__setattr__(first.fields[0], "source_value", 777)
        again = Observation.model_validate_json(original)
        assert canonical_json(again) == original
        object.__setattr__(again.session_key, "session_label", "POISON")
        assert canonical_json(Observation.model_validate_json(original)) == original


def test_cache_does_not_cross_calls_or_failed_scope(
    original: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original_hash = R.exploratory_reconstruction_hash

    def measured(value: Observation) -> str:
        nonlocal calls
        calls += 1
        return original_hash(value)

    monkeypatch.setattr(R, "exploratory_reconstruction_hash", measured)
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with pytest.raises(RuntimeError), scope():
        Observation.model_validate_json(original)
        raise RuntimeError("later original record invalid")
    with scope():
        Observation.model_validate_json(original)
    Observation.model_validate_json(original)
    assert calls == 3


def test_python_mode_still_requires_strict_original_values(original: bytes) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        Observation.model_validate_json(original)
        with pytest.raises(ValidationError):
            Observation.model_validate(json.loads(original))


def test_failed_validation_never_populates_cache(original: bytes) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    invalid = json.loads(original)
    invalid["reconstruction_hash"] = "a" * 64
    with scope():
        for _ in range(2):
            with pytest.raises(ValidationError):
                Observation.model_validate_json(json.dumps(invalid))
        assert canonical_json(Observation.model_validate_json(original)) == original


def test_retained_entry_and_byte_limits_fall_back_to_strict_validation(
    original: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope() as cache:
        if cache is None:
            pytest.fail("bounded observation reuse not implemented")
        cache.max_entries = 1
        cache.max_bytes = 1
        first = Observation.model_validate_json(original)
        second = Observation.model_validate_json(original)
        assert first == second
        assert not cache.entries
        assert cache.retained_bytes == 0


def test_explicit_validation_context_never_reuses_default_parse(
    original: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original_hash = R.exploratory_reconstruction_hash

    def measured(value: Observation) -> str:
        nonlocal calls
        calls += 1
        return original_hash(value)

    monkeypatch.setattr(R, "exploratory_reconstruction_hash", measured)
    scope = getattr(R, "_reconstruction_validation_scope", nullcontext)
    with scope():
        Observation.model_validate_json(original)
        Observation.model_validate_json(original, context={"untrusted": True})
    assert calls == 2
