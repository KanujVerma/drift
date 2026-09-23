"""The EXPLORATORY reconstructed accounting price record and its trace event."""

from decimal import Decimal
from typing import Any

import pytest
from exploratory_decision_test_support import JAN5, JAN6, scheduled_session_case
from pydantic import ValidationError

from drift.domain.evaluator_exploratory_accounting import (
    ExploratoryReconstructedAccountingPriceV1,
    exploratory_accounting_price_hash,
    reconstructed_accounting_price,
)
from drift.domain.evaluator_lanes import ALPACA_LIMITATION_UNVERSIONED_BARS
from drift.domain.evaluator_trace import (
    EvaluationPhase,
    ExploratoryAccountingPriceTraceEventV1,
)


def _price(
    role: str = "close", day: Any = JAN5
) -> ExploratoryReconstructedAccountingPriceV1:
    observation, _ = scheduled_session_case(day, close="100.500")
    return reconstructed_accounting_price(observation, role)  # type: ignore[arg-type]


def _resealed(
    price: ExploratoryReconstructedAccountingPriceV1, **changes: Any
) -> dict[str, Any]:
    """A payload with ``changes`` applied and a hash recomputed to match."""
    draft = ExploratoryReconstructedAccountingPriceV1.model_construct(
        **(dict(price) | changes)
    )
    return dict(draft) | {"price_hash": exploratory_accounting_price_hash(draft)}


# --- the record -------------------------------------------------------------------


@pytest.mark.parametrize(("role", "value"), [("open", "100.000"), ("close", "100.500")])
def test_the_record_reads_its_role_and_binds_its_reconstruction(
    role: str, value: str
) -> None:
    observation, _ = scheduled_session_case(JAN5, close="100.500")
    price = reconstructed_accounting_price(observation, role)  # type: ignore[arg-type]
    field = next(item for item in observation.fields if item.field_name == role)

    assert price.field_role == role
    assert price.unadjusted_price == Decimal(value)
    assert price.price_basis == "unadjusted"
    assert price.evidence_grade == "exploratory_reconstructed"
    assert price.is_promotion_grade_evidence is False
    assert (price.security_id, price.listing_id, price.venue, price.session_key) == (
        observation.security_id,
        observation.listing_id,
        observation.venue,
        observation.session_key,
    )
    assert price.currency == observation.currency
    assert price.reconstruction_hash == observation.reconstruction_hash
    assert price.source_field_hash == field.source_field_hash
    assert price.scheduled_session_hash == observation.scheduled_session_hash
    assert price.generated_session_row_hash == observation.generated_session_row_hash
    assert price.acknowledged_limitations == observation.acknowledged_limitations


def test_a_tampered_price_breaks_its_hash() -> None:
    payload = dict(_price()) | {"unadjusted_price": Decimal("250.000")}

    with pytest.raises(ValidationError, match=r"accounting price hash mismatch"):
        ExploratoryReconstructedAccountingPriceV1.model_validate(payload)


@pytest.mark.parametrize("value", ["0", "-1.000"])
def test_a_price_must_be_strictly_positive(value: str) -> None:
    with pytest.raises(ValidationError, match=r"must be strictly positive"):
        ExploratoryReconstructedAccountingPriceV1.model_validate(
            _resealed(_price(), unadjusted_price=Decimal(value))
        )


def test_a_price_must_carry_its_retrospective_limitations() -> None:
    kept = tuple(
        item
        for item in _price().acknowledged_limitations
        if item != ALPACA_LIMITATION_UNVERSIONED_BARS
    )

    with pytest.raises(
        ValidationError, match=r"requires its retrospective limitations"
    ):
        ExploratoryReconstructedAccountingPriceV1.model_validate(
            _resealed(_price(), acknowledged_limitations=kept)
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("evidence_grade", "promotion_grade"), ("is_promotion_grade_evidence", True)],
)
def test_the_grade_cannot_be_raised(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ExploratoryReconstructedAccountingPriceV1.model_validate(
            _resealed(_price(), **{field: value})
        )


# --- the trace event ---------------------------------------------------------------


def _event(
    phase: EvaluationPhase, prices: tuple[Any, ...], session_key: Any = None
) -> ExploratoryAccountingPriceTraceEventV1:
    return ExploratoryAccountingPriceTraceEventV1(
        sequence=0,
        session_index=0,
        session_key=prices[0].session_key if session_key is None else session_key,
        phase=phase,  # type: ignore[arg-type]
        prices=prices,
    )


def test_each_phase_reads_its_own_role() -> None:
    _event(EvaluationPhase.OPEN_EXECUTION, (_price("open"),))
    _event(EvaluationPhase.CLOSE_MARK, (_price("close"),))

    with pytest.raises(ValidationError, match=r"reads open prices, not close"):
        _event(EvaluationPhase.OPEN_EXECUTION, (_price("close"),))
    with pytest.raises(ValidationError, match=r"reads close prices, not open"):
        _event(EvaluationPhase.CLOSE_MARK, (_price("open"),))


def test_only_the_open_and_close_phases_read_prices() -> None:
    with pytest.raises(ValidationError):
        _event(EvaluationPhase.POST_CLOSE_DECISION, (_price("close"),))


def test_a_price_from_another_session_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"belongs to another session"):
        _event(
            EvaluationPhase.CLOSE_MARK,
            (_price("close", JAN6),),
            session_key=_price("close", JAN5).session_key,
        )


def test_an_event_names_at_least_one_price_and_each_security_once() -> None:
    with pytest.raises(ValidationError, match=r"must name the prices it read"):
        ExploratoryAccountingPriceTraceEventV1(
            sequence=0,
            session_index=0,
            session_key=_price().session_key,
            phase=EvaluationPhase.CLOSE_MARK,
            prices=(),
        )
    with pytest.raises(ValidationError, match=r"unique by security"):
        _event(EvaluationPhase.CLOSE_MARK, (_price("close"), _price("close")))
