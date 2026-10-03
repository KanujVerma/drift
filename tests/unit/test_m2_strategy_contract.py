"""Unit tests and mutation proofs for the frozen M2 strategy surface contract.

Verifies the frozen Tier A contract inventory pinned in
tests/fixtures/contracts/m2-strategy-surface-v1.json, verifies mutation kill
proofs for all contract elements, and tests staging behaviors.
"""

import hashlib
import inspect
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import Field, ValidationError

from drift.domain.common import UUID7
from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    evaluation_session_hash,
)
from drift.domain.evaluator_exploratory_strategy import (
    EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE,
    RECONSTRUCTED_DECISION_LIMITATIONS,
    SCHEDULED_CLOCK_LIMITATIONS,
    ExploratoryReconstructedDecisionViewV1,
    ExploratoryReconstructedRuntimeStrategy,
    ExploratoryStrategyDecisionContextV1,
    stage_exploratory_decision_targets,
)
from drift.domain.evaluator_portfolio import SecurityHoldingV2
from drift.domain.evaluator_strategy import (
    DECISION_TIME_MISMATCH,
    ParameterizedStrategy,
    PositionViewV1,
    RuntimeStrategy,
    SecurityTargetPositionV1,
    StrategyDecisionContextV1,
    StrategyDecisionIntentV1,
    StrategyDecisionViewV1,
    StrategyIntentRejectedError,
    position_view,
    stage_decision_targets,
)
from drift.domain.sessions import SessionKeyV1
from drift.domain.strategies import StrategyReference

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contracts"
    / "m2-strategy-surface-v1.json"
)

SEC_A = UUID("00000000-0000-7000-8000-000000000001")
SEC_B = UUID("00000000-0000-7000-8000-000000000002")
SEC_C = UUID("00000000-0000-7000-8000-000000000003")

SESSION_DATE = date(2026, 11, 30)
CUTOFF = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)


def _schema_hash(model_cls: type[Any]) -> str:
    schema = model_cls.model_json_schema()
    raw = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _key(day: date = SESSION_DATE) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(
    day: date = SESSION_DATE,
    *,
    close: datetime | None = None,
    authority: str = "realized",
) -> EvaluationSessionV1:
    default_close = datetime.combine(day, time(21, 0), tzinfo=UTC)
    closed_at = default_close if close is None else close
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=_key(day),
        opened_at=closed_at - timedelta(hours=6, minutes=30),
        closed_at=closed_at,
        authority=authority,
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _context(
    admitted: tuple[UUID7, ...] = (SEC_A, SEC_B),
    holdings: tuple[SecurityHoldingV2, ...] = (),
) -> StrategyDecisionContextV1:
    positions = tuple(position_view(h) for h in holdings)
    session = _evaluation_session()
    return StrategyDecisionContextV1(
        schema_version="1",
        session_key=session.session_key,
        decision_session=session,
        decision_cutoff=session.closed_at,
        admitted_universe=admitted,
        current_holdings=positions,
        current_cash=Decimal("10000.00"),
        portfolio_nav=Decimal("10000.00"),
        decision_views=(),
    )


def _exploratory_context(
    cohort: tuple[UUID7, ...] = (SEC_A, SEC_B),
) -> ExploratoryStrategyDecisionContextV1:
    session = _evaluation_session(authority="scheduled_reconstruction")
    return ExploratoryStrategyDecisionContextV1.model_construct(
        schema_version="1",
        session_key=session.session_key,
        decision_session=session,
        decision_cutoff=session.closed_at,
        cohort_hash="f" * 64,
        admitted_cohort=cohort,
        reconstructed_decision_views=(),
        current_holdings=(),
        current_cash=Decimal("10000.00"),
        portfolio_nav=Decimal("10000.00"),
        acknowledged_limitations=RECONSTRUCTED_DECISION_LIMITATIONS,
    )


def test_contract_fixture_exists() -> None:
    assert FIXTURE_PATH.is_file(), f"Contract fixture missing at {FIXTURE_PATH}"


def test_m2_strategy_surface_tier_a_models_pin() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    pinned_models = fixture["tier_a_models"]
    model_map: dict[str, type[Any]] = {
        "PositionViewV1": PositionViewV1,
        "StrategyDecisionViewV1": StrategyDecisionViewV1,
        "StrategyDecisionContextV1": StrategyDecisionContextV1,
        "SecurityTargetPositionV1": SecurityTargetPositionV1,
        "StrategyDecisionIntentV1": StrategyDecisionIntentV1,
        "ExploratoryStrategyDecisionContextV1": (ExploratoryStrategyDecisionContextV1),
        "ExploratoryReconstructedDecisionViewV1": (
            ExploratoryReconstructedDecisionViewV1
        ),
        "StrategyReference": StrategyReference,
    }

    assert set(pinned_models.keys()) == set(model_map.keys())
    for name, expected_hash in pinned_models.items():
        actual_hash = _schema_hash(model_map[name])
        assert actual_hash == expected_hash, (
            "frozen M2 strategy contract changed; a new kind:contract issue is "
            f"required: {name} schema hash mismatch"
        )


def test_m2_strategy_surface_tier_a_protocols_and_signatures() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    protocols = fixture["tier_a_protocols"]
    signatures = fixture["tier_a_signatures"]

    def _public_members(cls: type[Any]) -> list[str]:
        return sorted(m for m in dir(cls) if not m.startswith("_"))

    assert _public_members(RuntimeStrategy) == protocols["RuntimeStrategy"]
    assert (
        _public_members(ExploratoryReconstructedRuntimeStrategy)
        == protocols["ExploratoryReconstructedRuntimeStrategy"]
    )
    assert _public_members(ParameterizedStrategy) == protocols["ParameterizedStrategy"]

    actual_signatures = {
        "RuntimeStrategy.decide": str(inspect.signature(RuntimeStrategy.decide)),
        "RuntimeStrategy.strategy_reference": str(
            inspect.signature(RuntimeStrategy.strategy_reference.fget)  # type: ignore[attr-defined]
        ),
        "ExploratoryReconstructedRuntimeStrategy.decide_exploratory": str(
            inspect.signature(
                ExploratoryReconstructedRuntimeStrategy.decide_exploratory
            )
        ),
        "ExploratoryReconstructedRuntimeStrategy.strategy_reference": str(
            inspect.signature(
                ExploratoryReconstructedRuntimeStrategy.strategy_reference.fget  # type: ignore[attr-defined]
            )
        ),
        "ParameterizedStrategy.strategy_parameters": str(
            inspect.signature(
                ParameterizedStrategy.strategy_parameters.fget  # type: ignore[attr-defined]
            )
        ),
        "stage_decision_targets": str(inspect.signature(stage_decision_targets)),
        "stage_exploratory_decision_targets": str(
            inspect.signature(stage_exploratory_decision_targets)
        ),
    }

    for key, expected_sig in signatures.items():
        assert actual_signatures[key] == expected_sig, (
            f"Signature mismatch for {key}: expected {expected_sig}, "
            f"got {actual_signatures[key]}"
        )


def test_m2_strategy_surface_tier_a_constants_and_errors() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    pinned = fixture["tier_a_errors_and_constants"]

    mro_names = [cls.__name__ for cls in StrategyIntentRejectedError.__mro__]
    assert mro_names == pinned["StrategyIntentRejectedError_mro"]
    assert DECISION_TIME_MISMATCH == pinned["DECISION_TIME_MISMATCH"]
    assert (
        EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE
        == pinned["EXPLORATORY_RECONSTRUCTED_EVIDENCE_GRADE"]
    )
    assert list(SCHEDULED_CLOCK_LIMITATIONS) == pinned["SCHEDULED_CLOCK_LIMITATIONS"]
    assert (
        list(RECONSTRUCTED_DECISION_LIMITATIONS)
        == pinned["RECONSTRUCTED_DECISION_LIMITATIONS"]
    )


# --- 5 Mutation Proofs for Contract Pins ---


def test_mutant_added_field_to_intent_fails_pin() -> None:
    class MutatedStrategyDecisionIntentV1(StrategyDecisionIntentV1):
        extra_mutant_field: str = "mutant"

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_hash = _schema_hash(MutatedStrategyDecisionIntentV1)
    assert mutant_hash != fixture["tier_a_models"]["StrategyDecisionIntentV1"]


def test_mutant_relaxed_target_quantity_fails_pin() -> None:
    class MutatedSecurityTargetPositionV1(SecurityTargetPositionV1):
        target_quantity: int = Field(ge=-1)

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_hash = _schema_hash(MutatedSecurityTargetPositionV1)
    assert mutant_hash != fixture["tier_a_models"]["SecurityTargetPositionV1"]


def test_mutant_renamed_decide_parameter_fails_pin() -> None:
    def decide_mutant(
        self: Any, ctx: StrategyDecisionContextV1
    ) -> StrategyDecisionIntentV1:
        raise NotImplementedError

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_sig = str(inspect.signature(decide_mutant))
    assert mutant_sig != fixture["tier_a_signatures"]["RuntimeStrategy.decide"]


def test_mutant_dropped_limitation_constant_fails_pin() -> None:
    mutated_limitations = list(RECONSTRUCTED_DECISION_LIMITATIONS)[:-1]

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    assert (
        mutated_limitations
        != fixture["tier_a_errors_and_constants"]["RECONSTRUCTED_DECISION_LIMITATIONS"]
    )


def test_mutant_altered_error_mro_fails_pin() -> None:
    class MutatedStrategyIntentRejectedError(Exception):
        pass

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_mro = [cls.__name__ for cls in MutatedStrategyIntentRejectedError.__mro__]
    assert (
        mutant_mro
        != fixture["tier_a_errors_and_constants"]["StrategyIntentRejectedError_mro"]
    )


# --- Staging & Type Contract Behaviors ---


def test_strict_whole_shares_integer_validation() -> None:
    assert (
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=10).target_quantity
        == 10
    )
    assert (
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=0).target_quantity
        == 0
    )

    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=-1)

    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=10.5)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(
            security_id=SEC_A,
            target_quantity=Decimal("10"),  # type: ignore[arg-type]
        )

    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity=True)

    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(security_id=SEC_A, target_quantity="10")  # type: ignore[arg-type]


def test_staging_omitted_holdings_are_zeroed_and_sorted() -> None:
    ctx = _context(
        admitted=(SEC_A, SEC_B),
        holdings=(
            SecurityHoldingV2(
                security_id=SEC_B,
                quantity=5,
                cost_basis=Decimal("500.00"),
                basis_status="known",
            ),
        ),
    )
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_A, target_quantity=10),),
    )
    staged = stage_decision_targets(intent, ctx)
    assert len(staged) == 2
    staged_dict = {t.security_id: t.target_quantity for t in staged}
    assert staged_dict[SEC_A] == 10
    assert staged_dict[SEC_B] == 0
    assert list(staged) == sorted(staged, key=lambda t: t.security_id.bytes)


def test_staging_unadmitted_positive_target_refused() -> None:
    ctx = _context(admitted=(SEC_A,))
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_B, target_quantity=5),),
    )
    with pytest.raises(
        StrategyIntentRejectedError,
        match="a positive target requires an admitted security",
    ):
        stage_decision_targets(intent, ctx)


def test_staging_unadmitted_zero_target_permitted() -> None:
    ctx = _context(admitted=(SEC_A,))
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_B, target_quantity=0),),
    )
    staged = stage_decision_targets(intent, ctx)
    assert len(staged) == 1
    assert staged[0].security_id == SEC_B
    assert staged[0].target_quantity == 0


def test_staging_mismatched_session_key_or_cutoff_refused() -> None:
    ctx = _context()
    wrong_key_intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=_key(date(2026, 12, 1)),
        decision_time=ctx.decision_cutoff,
        targets=(),
    )
    with pytest.raises(
        StrategyIntentRejectedError,
        match="decision intent session_key must match the decision context session",
    ):
        stage_decision_targets(wrong_key_intent, ctx)

    wrong_time_intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff - timedelta(minutes=5),
        targets=(),
    )
    with pytest.raises(StrategyIntentRejectedError, match=DECISION_TIME_MISMATCH):
        stage_decision_targets(wrong_time_intent, ctx)


def test_exploratory_staging_behavior() -> None:
    ctx = _exploratory_context(cohort=(SEC_A, SEC_B))
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_A, target_quantity=15),),
    )
    staged = stage_exploratory_decision_targets(intent, ctx)
    assert len(staged) == 1
    assert staged[0].security_id == SEC_A
    assert staged[0].target_quantity == 15

    # Positive target on unadmitted cohort member rejected
    unadmitted_intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_C, target_quantity=15),),
    )
    with pytest.raises(
        StrategyIntentRejectedError,
        match="a positive target requires an admitted security",
    ):
        stage_exploratory_decision_targets(unadmitted_intent, ctx)


# --- 3 Staging Rule Mutation Proofs ---


def test_mutant_omitted_holding_not_zeroed_is_killed() -> None:
    def buggy_stage(
        intent: StrategyDecisionIntentV1, ctx: StrategyDecisionContextV1
    ) -> tuple[SecurityTargetPositionV1, ...]:
        # Buggy implementation: skips zeroing omitted holdings
        return tuple(intent.targets)

    ctx = _context(
        admitted=(SEC_A, SEC_B),
        holdings=(
            SecurityHoldingV2(
                security_id=SEC_B,
                quantity=5,
                cost_basis=Decimal("500.00"),
                basis_status="known",
            ),
        ),
    )
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_A, target_quantity=10),),
    )
    staged = buggy_stage(intent, ctx)
    # The mutant is killed because SEC_B is absent from staged targets
    assert not any(t.security_id == SEC_B for t in staged)


def test_mutant_omitted_unadmitted_security_check_is_killed() -> None:
    def buggy_stage(
        intent: StrategyDecisionIntentV1, ctx: StrategyDecisionContextV1
    ) -> tuple[SecurityTargetPositionV1, ...]:
        # Buggy implementation: permits unadmitted securities
        return tuple(intent.targets)

    ctx = _context(admitted=(SEC_A,))
    intent = StrategyDecisionIntentV1(
        schema_version="1",
        session_key=ctx.session_key,
        decision_time=ctx.decision_cutoff,
        targets=(SecurityTargetPositionV1(security_id=SEC_B, target_quantity=10),),
    )
    # The mutant does not raise StrategyIntentRejectedError
    staged = buggy_stage(intent, ctx)
    assert staged[0].security_id == SEC_B


def test_mutant_relaxed_integer_type_check_is_killed() -> None:
    # A mutant that accepts float 10.0 or Decimal 10
    raw_target = 10.0
    with pytest.raises(ValidationError):
        SecurityTargetPositionV1(
            security_id=SEC_A,
            target_quantity=raw_target,  # type: ignore[arg-type]
        )
