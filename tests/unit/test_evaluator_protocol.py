"""Unit tests for M2 evaluation protocol contract."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.domain.evaluator_protocol import (
    EvaluationProtocolV1,
    evaluation_protocol_hash,
)

H0 = "0" * 64
H1 = "1" * 64


def test_protocol_valid_and_hash_verification() -> None:
    unhashed = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="standard_daily_v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=5,
        initial_cash=Decimal("100000.00"),
        protocol_hash=H0,
    )
    expected_hash = evaluation_protocol_hash(unhashed)
    protocol = unhashed.model_copy(update={"protocol_hash": expected_hash})

    assert protocol.schema_version == "1"
    assert protocol.protocol_id == "standard_daily_v1"
    assert protocol.decision_clock == "post_close_decision_next_open_execution"
    assert protocol.session_scope == "regular"
    assert protocol.warmup_session_count == 5
    assert protocol.initial_cash == Decimal("100000.00")
    assert protocol.protocol_hash == expected_hash


def test_protocol_warmup_session_count_bounds() -> None:
    # warmup >= 1 is accepted
    unhashed = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="standard_daily_v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=1,
        initial_cash=Decimal("100000.00"),
        protocol_hash=H0,
    )
    h = evaluation_protocol_hash(unhashed)
    p = unhashed.model_copy(update={"protocol_hash": h})
    assert p.warmup_session_count == 1

    # warmup = 0 is rejected
    unhashed_zero = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="standard_daily_v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=0,
        initial_cash=Decimal("100000.00"),
        protocol_hash=H0,
    )
    h_zero = evaluation_protocol_hash(unhashed_zero)
    with pytest.raises(ValidationError, match="warmup_session_count"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=0,
            initial_cash=Decimal("100000.00"),
            protocol_hash=h_zero,
        )

    # negative warmup is rejected
    with pytest.raises(ValidationError, match="warmup_session_count"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=-1,
            initial_cash=Decimal("100000.00"),
            protocol_hash=H1,
        )


def test_protocol_initial_cash_bounds_and_exact_decimal() -> None:
    # initial_cash <= 0 is rejected
    with pytest.raises(ValidationError, match="initial_cash"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=1,
            initial_cash=Decimal("0.00"),
            protocol_hash=H1,
        )

    # float is rejected
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=1,
            initial_cash=100000.0,  # type: ignore[arg-type]
            protocol_hash=H1,
        )

    # NaN / Inf is rejected
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=1,
            initial_cash=Decimal("NaN"),
            protocol_hash=H1,
        )


def test_protocol_tampered_hash_rejected() -> None:
    with pytest.raises(ValidationError, match="protocol hash mismatch"):
        EvaluationProtocolV1(
            schema_version="1",
            protocol_id="standard_daily_v1",
            decision_clock="post_close_decision_next_open_execution",
            session_scope="regular",
            warmup_session_count=1,
            initial_cash=Decimal("100000.00"),
            protocol_hash=H1,
        )


def test_protocol_immutable_frozen() -> None:
    unhashed = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="standard_daily_v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=1,
        initial_cash=Decimal("100000.00"),
        protocol_hash=H0,
    )
    h = evaluation_protocol_hash(unhashed)
    p = unhashed.model_copy(update={"protocol_hash": h})

    with pytest.raises(ValidationError):
        p.warmup_session_count = 2


def test_protocol_rejects_unsupported_clock_and_scope() -> None:
    base: dict[str, Any] = {
        "schema_version": "1",
        "protocol_id": "standard_daily_v1",
        "decision_clock": "post_close_decision_next_open_execution",
        "session_scope": "regular",
        "warmup_session_count": 5,
        "initial_cash": Decimal("100000.00"),
        "protocol_hash": H0,
    }
    with pytest.raises(ValidationError):
        EvaluationProtocolV1(**{**base, "decision_clock": "pre_close_decision"})
    with pytest.raises(ValidationError):
        EvaluationProtocolV1(**{**base, "session_scope": "extended"})


def test_protocol_initial_cash_negative_and_infinite_rejected() -> None:
    base: dict[str, Any] = {
        "schema_version": "1",
        "protocol_id": "standard_daily_v1",
        "warmup_session_count": 5,
        "initial_cash": Decimal("100000.00"),
        "protocol_hash": H0,
    }
    with pytest.raises(ValidationError, match="initial_cash"):
        EvaluationProtocolV1(**{**base, "initial_cash": Decimal("-1.00")})
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationProtocolV1(**{**base, "initial_cash": Decimal("Infinity")})
    with pytest.raises(ValidationError, match="exact decimal"):
        EvaluationProtocolV1(**{**base, "initial_cash": Decimal("-Infinity")})


def test_protocol_accepts_exact_json_decimal_string() -> None:
    unhashed = EvaluationProtocolV1.model_construct(
        schema_version="1",
        protocol_id="standard_daily_v1",
        decision_clock="post_close_decision_next_open_execution",
        session_scope="regular",
        warmup_session_count=5,
        initial_cash=Decimal("100000.50"),
        protocol_hash=H0,
    )
    real_hash = evaluation_protocol_hash(unhashed)
    payload = (
        '{"schema_version": "1", "protocol_id": "standard_daily_v1", '
        '"warmup_session_count": 5, "initial_cash": "100000.50", '
        '"protocol_hash": "'
        + real_hash
        + '", "decision_clock": "post_close_decision_next_open_execution", '
        '"session_scope": "regular"}'
    )
    parsed = EvaluationProtocolV1.model_validate_json(payload)
    assert parsed.initial_cash == Decimal("100000.50")
    assert parsed.protocol_hash == real_hash


def test_protocol_hash_changes_with_each_protocol_input() -> None:
    base: dict[str, Any] = {
        "schema_version": "1",
        "protocol_id": "standard_daily_v1",
        "decision_clock": "post_close_decision_next_open_execution",
        "session_scope": "regular",
        "warmup_session_count": 5,
        "initial_cash": Decimal("100000.00"),
        "protocol_hash": H0,
    }
    baseline = evaluation_protocol_hash(EvaluationProtocolV1.model_construct(**base))
    for field, replacement in (
        ("protocol_id", "alt_daily_v1"),
        ("warmup_session_count", 6),
        ("initial_cash", Decimal("100000.01")),
    ):
        alt_hash = evaluation_protocol_hash(
            EvaluationProtocolV1.model_construct(**{**base, field: replacement})
        )
        assert alt_hash != baseline
