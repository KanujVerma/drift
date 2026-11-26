"""Synthetic observations are evidence candidates, never broker authority."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid7

import pytest


def test_unknown_contains_no_current_broker_fact() -> None:
    from drift.domain.execution_observation import (
        SyntheticExecutionObservationV2,
        build_synthetic_observation,
    )

    observation = build_synthetic_observation(
        observation_id=uuid7(),
        attempt_id=uuid7(),
        intent_id=uuid7(),
        intent_hash="a" * 64,
        account_key="synthetic-account-1",
        observed_at=datetime(2026, 3, 1, tzinfo=UTC),
        knowledge="UNKNOWN",
        reason_code="submission_unconfirmed",
    )
    assert observation.broker_fact is None
    assert observation.last_confirmed_report_hash is None
    assert (
        SyntheticExecutionObservationV2.model_validate_json(
            observation.model_dump_json()
        )
        == observation
    )
    with pytest.raises(ValueError):
        observation.model_copy(update={"knowledge": "CONFIRMED"})


def test_synthetic_confirmed_missing_fee_stays_unknown() -> None:
    from drift.domain.execution_observation import (
        SyntheticBrokerFactV2,
        build_synthetic_observation,
    )

    fact = SyntheticBrokerFactV2(status="filled", cumulative_quantity=2)
    observation = build_synthetic_observation(
        observation_id=uuid7(),
        attempt_id=uuid7(),
        intent_id=uuid7(),
        intent_hash="a" * 64,
        account_key="synthetic-account-1",
        observed_at=datetime(2026, 3, 1, tzinfo=UTC),
        knowledge="CONFIRMED",
        reason_code=None,
        broker_fact=fact,
    )
    assert observation.broker_fact == fact
    assert fact.cumulative_quantity == 2
    assert fact.cumulative_fee is None
    assert fact.cumulative_fee != Decimal(0)


def test_not_sent_has_no_broker_fact() -> None:
    from drift.domain.execution_observation import build_synthetic_observation

    observation = build_synthetic_observation(
        observation_id=uuid7(),
        attempt_id=uuid7(),
        intent_id=uuid7(),
        intent_hash="a" * 64,
        account_key="synthetic-account-1",
        observed_at=datetime(2026, 3, 1, tzinfo=UTC),
        knowledge="NOT_SENT",
        reason_code="authorization_refused",
    )
    assert observation.broker_fact is None


def test_unrecognized_broker_status_and_invalid_measurements_refuse() -> None:
    from pydantic import ValidationError

    from drift.domain.execution_observation import SyntheticBrokerFactV2

    with pytest.raises(ValidationError):
        SyntheticBrokerFactV2.model_validate({"status": "unrecognized"})
    with pytest.raises(ValidationError):
        SyntheticBrokerFactV2(status="filled", cumulative_quantity=-1)
    with pytest.raises(ValidationError):
        SyntheticBrokerFactV2(status="filled", cumulative_fee=Decimal("NaN"))


def test_unknown_cannot_claim_current_fact_or_use_unrecognized_version() -> None:
    from drift.domain.execution_observation import (
        SyntheticBrokerFactV2,
        build_synthetic_observation,
    )

    observation = build_synthetic_observation(
        observation_id=uuid7(),
        attempt_id=uuid7(),
        intent_id=uuid7(),
        intent_hash="a" * 64,
        account_key="synthetic-account-1",
        observed_at=datetime(2026, 3, 1, tzinfo=UTC),
        knowledge="UNKNOWN",
        reason_code="submission_unconfirmed",
    )
    with pytest.raises(ValueError):
        observation.model_copy(
            update={"broker_fact": SyntheticBrokerFactV2(status="rejected")}
        )
    with pytest.raises(ValueError):
        observation.model_copy(update={"schema_version": "3"})
    with pytest.raises(ValueError):
        observation.model_copy(update={"account_key": "real-account"})
