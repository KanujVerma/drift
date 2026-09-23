"""Unit tests for the EXPLORATORY reconstructed decision trace event (issue 46).

A decision taken on reconstructed evidence is recorded under its own event
kind, so a trace can never present it as a decision on authentic evidence, and
it names the reconstructions read and the limitations carried, so the weaker
grade is auditable from the trace alone.
"""

import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from drift.domain.evaluator_exploratory_strategy import (
    RECONSTRUCTED_DECISION_LIMITATIONS,
)
from drift.domain.evaluator_strategy import SecurityTargetPositionV1
from drift.domain.evaluator_trace import (
    EvaluatorTraceEventV1,
    ExploratoryStrategyDecisionTraceEventV1,
    StrategyDecisionTraceEventV1,
)
from drift.domain.sessions import SessionKeyV1

KEY = SessionKeyV1(mic="XNYS", session_scope="regular", local_date=date(2026, 1, 6))
EARLY_CLOSE = datetime(2026, 1, 6, 18, 0, tzinfo=UTC)
SECURITY = SecurityTargetPositionV1(
    security_id=UUID("019b8240-0000-7000-8000-000000000200"), target_quantity=10
)


def _values(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "sequence": 1,
        "session_index": 0,
        "session_key": KEY,
        "decision_cutoff": EARLY_CLOSE,
        "context_hash": "a" * 64,
        "intent_hash": "b" * 64,
        "reconstruction_hashes": ("d" * 64, "c" * 64),
        "acknowledged_limitations": tuple(reversed(RECONSTRUCTED_DECISION_LIMITATIONS)),
        "outcome": "staged",
        "staged_targets": (),
        "rejection_reason": None,
    }
    values.update(overrides)
    return values


def test_an_exploratory_decision_event_records_its_grade_and_evidence() -> None:
    event = ExploratoryStrategyDecisionTraceEventV1(**_values())

    assert event.kind == "exploratory_strategy_decision"
    assert event.evidence_grade == "exploratory_reconstructed"
    assert event.is_promotion_grade_evidence is False
    assert event.reconstruction_hashes == ("c" * 64, "d" * 64)
    assert event.acknowledged_limitations == RECONSTRUCTED_DECISION_LIMITATIONS


def test_an_exploratory_decision_event_must_name_what_it_read() -> None:
    with pytest.raises(
        ValidationError,
        match="an exploratory decision event must name the reconstructions it read",
    ):
        ExploratoryStrategyDecisionTraceEventV1(**_values(reconstruction_hashes=()))


def test_an_exploratory_decision_event_cannot_drop_any_required_limitation() -> None:
    assert RECONSTRUCTED_DECISION_LIMITATIONS, "no required limitation to drop"
    for limitation in RECONSTRUCTED_DECISION_LIMITATIONS:
        kept = tuple(
            item for item in RECONSTRUCTED_DECISION_LIMITATIONS if item != limitation
        )
        with pytest.raises(
            ValidationError,
            match=(
                "an exploratory decision event omits required limitations: "
                + re.escape(repr((limitation,)))
            ),
        ):
            ExploratoryStrategyDecisionTraceEventV1(
                **_values(acknowledged_limitations=kept)
            )


def test_an_exploratory_decision_event_cannot_claim_promotion_grade() -> None:
    event = ExploratoryStrategyDecisionTraceEventV1(**_values())
    for field, value in (
        ("is_promotion_grade_evidence", True),
        ("evidence_grade", "authentic_decision_views"),
        ("kind", "strategy_decision"),
    ):
        with pytest.raises(ValidationError) as error:
            ExploratoryStrategyDecisionTraceEventV1.model_validate(
                dict(event) | {field: value}
            )
        assert {item["loc"] for item in error.value.errors(include_url=False)} == {
            (field,)
        }


def test_a_rejected_exploratory_decision_stages_nothing_and_states_why() -> None:
    with pytest.raises(
        ValidationError, match="a rejected decision requires its reason"
    ):
        ExploratoryStrategyDecisionTraceEventV1(**_values(outcome="rejected"))
    with pytest.raises(ValidationError, match="a rejected decision stages no target"):
        ExploratoryStrategyDecisionTraceEventV1(
            **_values(
                outcome="rejected",
                rejection_reason="refused",
                staged_targets=(SECURITY,),
            )
        )
    with pytest.raises(
        ValidationError, match="a staged decision carries no rejection reason"
    ):
        ExploratoryStrategyDecisionTraceEventV1(**_values(rejection_reason="refused"))


def test_an_exploratory_decision_event_is_never_a_strong_decision_event() -> None:
    event = ExploratoryStrategyDecisionTraceEventV1(**_values())
    adapter: TypeAdapter[EvaluatorTraceEventV1] = TypeAdapter(EvaluatorTraceEventV1)

    assert not isinstance(event, StrategyDecisionTraceEventV1)
    assert isinstance(
        adapter.validate_python(dict(event)), ExploratoryStrategyDecisionTraceEventV1
    )
    with pytest.raises(ValidationError) as error:
        adapter.validate_python(dict(event) | {"kind": "strategy_decision"})

    reported = {
        (item["type"], item["loc"][-1])
        for item in error.value.errors(include_url=False)
    }
    for field in (
        "evidence_grade",
        "is_promotion_grade_evidence",
        "reconstruction_hashes",
        "acknowledged_limitations",
    ):
        assert ("extra_forbidden", field) in reported
