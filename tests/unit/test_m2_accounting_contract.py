"""Unit tests and mutation proofs for the frozen M2 accounting surface contract.

Verifies the frozen Tier A contract inventory pinned in
tests/fixtures/contracts/m2-accounting-surface-v1.json, verifies mutation kill
proofs for all contract elements, and tests behavioral accounting invariants.
"""

import hashlib
import inspect
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from drift.domain.evaluator_clock import (
    EvaluationSessionV1,
    SessionClockV1,
    evaluation_session_hash,
    session_clock_hash,
    session_order_key,
)
from drift.domain.evaluator_costs import EvaluationCostModelV1
from drift.domain.evaluator_lanes import (
    ALPACA_LIMITATION_BOUNDED_COHORT,
    ExploratoryEvaluationAdmissionV1,
    PromotionEvaluationAdmissionV1,
    exploratory_evaluation_admission_hash,
    promotion_evaluation_admission_hash,
)
from drift.domain.evaluator_portfolio import (
    APPLIED_EFFECT_ID_PROFILE,
    CLAIM_ID_PROFILE,
    PORTFOLIO_DECIMAL_PRECISION,
    EffectAlreadyAppliedError,
    IndeterminateBasisError,
    LaneAdmissibilityError,
    MarkEvidenceV1,
    MarkPriceV1,
    PendingCashClaimV1,
    PortfolioFillV1,
    PortfolioMarkV1,
    PortfolioStateV2,
    SecurityHoldingV2,
    applied_economic_effect_id,
    decimal_context,
    pending_cash_claim_id,
)
from drift.domain.evaluator_results import RealizedPnLCompletenessV1
from drift.domain.sessions import SessionKeyV1
from drift.evaluator.portfolio import PortfolioAccountingKernel, initial_portfolio_state

FIXTURE_PATH = (
    Path(__file__).parent.parent
    / "fixtures"
    / "contracts"
    / "m2-accounting-surface-v1.json"
)

SEC_A = UUID("00000000-0000-7000-8000-000000000001")
SEC_B = UUID("00000000-0000-7000-8000-000000000002")


def _schema_hash(model_cls: type[Any]) -> str:
    schema = model_cls.model_json_schema()
    raw = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _key(day: date) -> SessionKeyV1:
    return SessionKeyV1(mic="XNYS", session_scope="regular", local_date=day)


def _evaluation_session(
    key: SessionKeyV1, *, open_hour: int = 14, close_hour: int = 21
) -> EvaluationSessionV1:
    draft = EvaluationSessionV1.model_construct(
        schema_version="1",
        session_key=key,
        opened_at=datetime.combine(key.local_date, time(open_hour), tzinfo=UTC),
        closed_at=datetime.combine(key.local_date, time(close_hour), tzinfo=UTC),
        authority="realized",
        authority_record_hashes=("1" * 64,),
        authority_proof_hashes=("2" * 64,),
        session_hash="0" * 64,
    )
    return draft.model_copy(update={"session_hash": evaluation_session_hash(draft)})


def _session_clock(*sessions: EvaluationSessionV1) -> SessionClockV1:
    ordered = tuple(sorted(sessions, key=session_order_key))
    draft = SessionClockV1.model_construct(
        schema_version="1",
        mode="realized_session_authority",
        sessions=ordered,
        acknowledged_limitations=(),
        clock_hash="0" * 64,
    )
    return draft.model_copy(update={"clock_hash": session_clock_hash(draft)})


def _exploratory_admission() -> ExploratoryEvaluationAdmissionV1:
    draft = ExploratoryEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="exploratory",
        input_bundle_hash="3" * 64,
        acknowledged_limitations=(ALPACA_LIMITATION_BOUNDED_COHORT,),
        admission_hash="0" * 64,
    )
    return draft.model_copy(
        update={"admission_hash": exploratory_evaluation_admission_hash(draft)}
    )


def _promotion_admission() -> PromotionEvaluationAdmissionV1:
    draft = PromotionEvaluationAdmissionV1.model_construct(
        schema_version="1",
        lane="promotion",
        m1e_completion_record_hash="1" * 64,
        m1e_profile_set_hash="2" * 64,
        decision_handoff_hash="3" * 64,
        audit_handoff_hash="4" * 64,
        input_bundle_hash="5" * 64,
        provenance_proof_hash="6" * 64,
        admission_hash="0" * 64,
    )
    return draft.model_copy(
        update={"admission_hash": promotion_evaluation_admission_hash(draft)}
    )


def test_contract_fixture_exists() -> None:
    assert FIXTURE_PATH.is_file(), f"Contract fixture missing at {FIXTURE_PATH}"


def test_m2_accounting_surface_tier_a_models_pin() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    pinned_models = fixture["tier_a_models"]
    model_map: dict[str, type[Any]] = {
        "EvaluationCostModelV1": EvaluationCostModelV1,
        "MarkEvidenceV1": MarkEvidenceV1,
        "MarkPriceV1": MarkPriceV1,
        "PendingCashClaimV1": PendingCashClaimV1,
        "PortfolioFillV1": PortfolioFillV1,
        "PortfolioMarkV1": PortfolioMarkV1,
        "PortfolioStateV2": PortfolioStateV2,
        "RealizedPnLCompletenessV1": RealizedPnLCompletenessV1,
        "SecurityHoldingV2": SecurityHoldingV2,
    }

    assert set(pinned_models.keys()) == set(model_map.keys())
    for name, expected_hash in pinned_models.items():
        actual_hash = _schema_hash(model_map[name])
        assert actual_hash == expected_hash, (
            "frozen M2 accounting contract changed; a new kind:contract issue is "
            f"required: {name} schema hash mismatch"
        )


def test_m2_accounting_surface_tier_a_signatures_pin() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    signatures = fixture["tier_a_signatures"]
    actual_signatures = {
        "PortfolioAccountingKernel.__init__": str(
            inspect.signature(PortfolioAccountingKernel.__init__)
        ),
        "PortfolioAccountingKernel.advance_session": str(
            inspect.signature(PortfolioAccountingKernel.advance_session)
        ),
        "PortfolioAccountingKernel.apply_fill": str(
            inspect.signature(PortfolioAccountingKernel.apply_fill)
        ),
        "PortfolioAccountingKernel.mark_close": str(
            inspect.signature(PortfolioAccountingKernel.mark_close)
        ),
        "PortfolioAccountingKernel.record_claim": str(
            inspect.signature(PortfolioAccountingKernel.record_claim)
        ),
        "PortfolioAccountingKernel.settle_claims": str(
            inspect.signature(PortfolioAccountingKernel.settle_claims)
        ),
        "PortfolioAccountingKernel.supersede_claim": str(
            inspect.signature(PortfolioAccountingKernel.supersede_claim)
        ),
        "applied_economic_effect_id": str(
            inspect.signature(applied_economic_effect_id)
        ),
        "decimal_context": str(inspect.signature(decimal_context)),
        "pending_cash_claim_id": str(inspect.signature(pending_cash_claim_id)),
    }

    assert set(signatures.keys()) == set(actual_signatures.keys())
    for key, expected_sig in signatures.items():
        assert actual_signatures[key] == expected_sig, (
            f"Signature mismatch for {key}: expected {expected_sig}, "
            f"got {actual_signatures[key]}"
        )


def test_m2_accounting_surface_tier_a_constants_and_errors() -> None:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    pinned = fixture["tier_a_errors_and_constants"]
    assert APPLIED_EFFECT_ID_PROFILE == pinned["APPLIED_EFFECT_ID_PROFILE"]
    assert CLAIM_ID_PROFILE == pinned["CLAIM_ID_PROFILE"]
    assert PORTFOLIO_DECIMAL_PRECISION == pinned["PORTFOLIO_DECIMAL_PRECISION"]

    applied_mro = [cls.__name__ for cls in EffectAlreadyAppliedError.__mro__]
    assert applied_mro == pinned["EffectAlreadyAppliedError_mro"]

    indet_mro = [cls.__name__ for cls in IndeterminateBasisError.__mro__]
    assert indet_mro == pinned["IndeterminateBasisError_mro"]


# --- Mutation Kill Proofs ---


def test_mutant_added_field_to_fill_fails_pin() -> None:
    class MutatedPortfolioFillV1(PortfolioFillV1):
        extra_venue: str = "XNYS"

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_hash = _schema_hash(MutatedPortfolioFillV1)
    assert mutant_hash != fixture["tier_a_models"]["PortfolioFillV1"]


def test_mutant_added_field_to_holding_fails_pin() -> None:
    class MutatedSecurityHoldingV2(SecurityHoldingV2):
        extra_lot_tag: str = "lot1"

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_hash = _schema_hash(MutatedSecurityHoldingV2)
    assert mutant_hash != fixture["tier_a_models"]["SecurityHoldingV2"]


def test_mutant_signature_change_fails_pin() -> None:
    def fake_apply_fill(
        self: Any, fill: PortfolioFillV1, extra_flag: bool = False
    ) -> None:
        pass

    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fixture = json.load(f)

    mutant_sig = str(inspect.signature(fake_apply_fill))
    expected = fixture["tier_a_signatures"]["PortfolioAccountingKernel.apply_fill"]
    assert mutant_sig != expected


# --- Behavioral Contract Invariants ---


def test_rehydration_round_trip() -> None:
    """Kernel initialized from state preserves state identity bitwise."""
    key = _key(date(2026, 1, 15))
    sess = _evaluation_session(key)
    clock = _session_clock(sess)
    admission = _exploratory_admission()
    init_state = initial_portfolio_state(
        session_key=key,
        initial_cash=Decimal("50000.00"),
        admission=admission,
    )

    kernel = PortfolioAccountingKernel(init_state, session_clock=clock)
    assert kernel.state == init_state

    # Execute a buy fill and rehydrate
    fill = PortfolioFillV1(
        security_id=SEC_A,
        side="buy",
        quantity=10,
        fill_price=Decimal("100.00"),
        transaction_costs=Decimal("1.50"),
    )
    kernel.apply_fill(fill)
    after_fill = kernel.state

    kernel2 = PortfolioAccountingKernel(after_fill, session_clock=clock)
    assert kernel2.state == after_fill


def test_indeterminate_basis_sale_refusal() -> None:
    """Selling holding with indeterminate basis fails with IndeterminateBasisError."""
    key = _key(date(2026, 1, 15))
    sess = _evaluation_session(key)
    clock = _session_clock(sess)
    admission = _exploratory_admission()
    init_state = initial_portfolio_state(
        session_key=key,
        initial_cash=Decimal("50000.00"),
        admission=admission,
    )

    # Construct state with an indeterminate holding
    indet_cause = "e" * 64
    holding = SecurityHoldingV2(
        security_id=SEC_A,
        quantity=10,
        basis_status="indeterminate",
        cost_basis=None,
        basis_indeterminate_by=(indet_cause,),
    )
    state = init_state.model_copy(
        update={
            "holdings": (holding,),
            "applied_effect_ids": (indet_cause,),
        }
    )

    kernel = PortfolioAccountingKernel(state, session_clock=clock)
    sell_fill = PortfolioFillV1(
        security_id=SEC_A,
        side="sell",
        quantity=5,
        fill_price=Decimal("120.00"),
        transaction_costs=Decimal("1.00"),
    )

    with pytest.raises(IndeterminateBasisError):
        kernel.apply_fill(sell_fill)


def test_promotion_lane_mark_refusal_of_exploratory_evidence() -> None:
    """Promotion-lane book strictly refuses exploratory mark evidence."""
    key = _key(date(2026, 1, 15))
    sess = _evaluation_session(key)
    clock = _session_clock(sess)
    admission = _promotion_admission()
    init_state = initial_portfolio_state(
        session_key=key,
        initial_cash=Decimal("50000.00"),
        admission=admission,
    )
    # Buy 1 share
    kernel = PortfolioAccountingKernel(init_state, session_clock=clock)
    kernel.apply_fill(
        PortfolioFillV1(
            security_id=SEC_A,
            side="buy",
            quantity=1,
            fill_price=Decimal("100.00"),
        )
    )

    # Attempt to mark with exploratory evidence in promotion lane
    exploratory_mark = MarkPriceV1(
        security_id=SEC_A,
        close_price=Decimal("105.00"),
        evidence=MarkEvidenceV1(
            grade="exploratory",
            evidence_hash="a" * 64,
        ),
    )
    with pytest.raises(LaneAdmissibilityError):
        kernel.mark_close((exploratory_mark,))
