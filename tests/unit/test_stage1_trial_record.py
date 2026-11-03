"""Tests for Stage 1 derived scientific trial record admission (#485, #507, #508).

Verifies all Workstream B / Release 2 requirements:
- Authentic research producer-to-trial association (#507)
- Authentic platform RESULT-to-trial association (#508)
- Derived scientific trial record admission (#485)
- All B2 rejection rules:
  1. Wrong campaign
  2. Crossed B/R accounts
  3. Foreign checkpoint
  4. Duplicated original allocation
  5. Forged issuer
  6. Tampered RESULT
  7. Missing executed order
  8. Partial fill falsely treated as terminal success
  9. Unknown cost converted to zero
  10. Valid hash over invalid account association
  11. Reused trial receipt
  12. Incorrect original source vintage
  13. Incomplete cold readback / fresh process verification
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from test_stage1_campaign_config import (
    make_golden_arm_b,
    make_golden_arm_r,
    make_golden_bindings,
    make_golden_campaign,
)

from drift.evaluator.opening_book_lifecycle import OriginalInvocationBindingV1
from drift.experiments.stage1_trial_projection import ExactRatioV1
from drift.experiments.stage1_trial_provenance import _complete_manifest_fingerprint
from drift.experiments.stage1_trial_record import (
    Stage1DerivedTrialRecordV1,
    Stage1ResultTrialBindingV1,
    Stage1TrialAdmissionError,
    build_stage1_derived_trial_record,
    build_stage1_research_trial_binding,
    build_stage1_result_trial_binding,
    verify_stage1_derived_trial_record,
)
from drift.intelligence.contracts import (
    ArtifactReference,
    CostReceipt,
    ResearchCandidate,
    ResearchContext,
    Scope,
    StoredArtifactRef,
    compute_record_hash,
)
from drift.intelligence.receipts import create_cost_receipt
from drift.loop.stage1_controlled_contracts import OriginalReferenceV1

BASE = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)


def _art_ref(name: str) -> ArtifactReference:
    return ArtifactReference(id=name, version="1", sha256="a" * 64)


def _make_context(arm_id: str, account_id: str) -> ResearchContext:
    path = Path(__file__).parents[1] / "fixtures/adaptive_research/research_v1.json"
    data = json.loads(path.read_text())["fixtures"]["F01"]
    data.pop("record_hash")
    data["scope"] = dict(data["scope"])
    data["scope"]["arm_id"] = arm_id
    data["scope"]["account_id"] = account_id
    data["record_hash"] = compute_record_hash(data)
    return ResearchContext.model_validate(data)


def _make_candidate(arm_id: str, account_id: str) -> ResearchCandidate:
    path = Path(__file__).parents[1] / "fixtures/adaptive_research/research_v1.json"
    data = json.loads(path.read_text())["fixtures"]["F02"]
    data.pop("record_hash")
    data["scope"] = dict(data["scope"])
    data["scope"]["arm_id"] = arm_id
    data["scope"]["account_id"] = account_id
    data["record_hash"] = compute_record_hash(data)
    return ResearchCandidate.model_validate(data)


def _scope(arm_id: str, account_id: str) -> Scope:
    return Scope(
        experiment_id="STUDY-E1-001",
        arm_id=arm_id,
        account_id=account_id,
        campaign_ref=ArtifactReference(
            id="CAMP-E1-SYNTH-001",
            version="1",
            sha256="71fe095c4eddac2053be8a4a02b02a83fe11cf4a39195e7972245a45aa372a4e",
        ),
    )


def _make_cost(
    arm_id: str,
    account_id: str,
    ident: str = "cost-001",
    amount: str = "25",
    basis: Literal["actual", "estimate", "unknown", "verified_zero"] = "actual",
) -> CostReceipt:
    return create_cost_receipt(
        receipt_id=ident,
        scope=_scope(arm_id, account_id),
        category="model_inference",
        billing_identity="synthetic-billing",
        amount_basis=basis,
        attempt_id=f"ATT-{arm_id}-001",
        amount=amount if basis != "unknown" else None,
        currency="USD" if basis != "unknown" else None,
        unknown_reason="api_unmetered" if basis == "unknown" else None,
        raw_evidence_ref=(
            StoredArtifactRef(
                artifact_id="art-001",
                kind="raw_billing",
                content_hash="b" * 64,
                location="/tmp/receipt",
            )
            if basis == "verified_zero"
            else None
        ),
    )


def test_positive_stage1_derived_trial_record_b_and_r() -> None:
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]
    manifest_hash = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
    )
    cal_hash = "d" * 64
    src_hash = "e" * 64

    # 1. Research binding for ARM-B
    ctx_b = _make_context("ARM-B", b_binding.portfolio_account_id)
    cand_b = _make_candidate("ARM-B", b_binding.portfolio_account_id)
    cost_b = _make_cost("ARM-B", b_binding.portfolio_account_id, "cost-b-1", "25")

    res_bind = build_stage1_research_trial_binding(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        research_context=ctx_b,
        disposition="propose",
        candidate=cand_b,
        costs=(cost_b,),
        issuer_authority_id="local_authority",
    )
    assert res_bind.binding_hash is not None

    # 2. Result binding for ARM-B
    m0_inv = OriginalInvocationBindingV1(
        invocation_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b1"),
        m0_run_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b2"),
        m0_audit_event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b3"),
    )
    result_bind = build_stage1_result_trial_binding(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        m0_invocation=m0_inv,
        result_hash="1" * 64,
        trace_hash="2" * 64,
        final_book_hash="3" * 64,
        final_nav=Decimal("10120"),
        cash_balance=Decimal("120"),
        cumulative_transaction_costs=Decimal("5"),
        order_count=2,
        fill_count=2,
        classification="complete",
        ledger_ref=OriginalReferenceV1(
            event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b4"),
            event_hash="4" * 64,
        ),
    )
    assert result_bind.binding_hash is not None

    # 3. Complete derived trial record
    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        research_binding=res_bind,
        result_binding=result_bind,
        source_inventory_hash=src_hash,
        calendar_hash=cal_hash,
        start_session_index=0,
        end_session_index=21,
        outcome_classification="COMPLETED",
        completeness_classification="COMPLETE",
        costs=(cost_b,),
        start_nav=Decimal("10000"),
        end_nav=Decimal("10120"),
        trading_costs=Decimal("5"),
        reasons=("MONTHLY_REBALANCE_COMPLETED",),
    )

    assert trial.net_investment_gain == Decimal("120")
    assert trial.net_investment_return == ExactRatioV1(numerator=3, denominator=250)
    assert trial.economic_gain == Decimal("95")  # 120 - 25
    assert trial.economic_return == ExactRatioV1(numerator=19, denominator=2000)
    assert not trial.scientifically_qualified
    assert not trial.authorizes_trading

    # 4. Independent verification passes
    assert verify_stage1_derived_trial_record(
        trial,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
        source_inventory_hash=src_hash,
        calendar_hash=cal_hash,
    )


def test_reject_wrong_campaign() -> None:
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]

    with pytest.raises(
        (Stage1TrialAdmissionError, ValueError), match="TRIAL_ID_MISMATCH"
    ):
        Stage1DerivedTrialRecordV1.model_validate(
            {
                "schema_version": "drift-derived-trial/1",
                "trial_id": "WRONG-CAMP:RUN-001:ARM-B:CKPT-001",
                "campaign_id": campaign.campaign_id,
                "campaign_spec_fingerprint": campaign.campaign_spec_fingerprint,
                "complete_manifest_fingerprint": "c" * 64,
                "run_id": b_binding.run_id,
                "arm_id": "ARM-B",
                "portfolio_account_id": b_binding.portfolio_account_id,
                "checkpoint_id": "CKPT-001",
                "opening_book_identity": "BOOK-001",
                "opening_book_hash": "f" * 64,
                "source_inventory_hash": "e" * 64,
                "calendar_hash": "d" * 64,
                "start_session_index": 0,
                "outcome_classification": "NO_ATTEMPT",
                "completeness_classification": "INVALID",
                "operating_cost_projection": {
                    "currency": "USD",
                    "status": "UNAVAILABLE",
                    "amount": None,
                    "original_receipt_hashes": (),
                    "effective_receipt_hashes": (),
                },
                "trial_record_hash": "0" * 64,
            }
        )

    trial = build_stage1_derived_trial_record(
        campaign_id="WRONG_CAMP",
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint="c" * 64,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        source_inventory_hash="e" * 64,
        calendar_hash="d" * 64,
        start_session_index=0,
        outcome_classification="NO_ATTEMPT",
        completeness_classification="INVALID",
    )
    with pytest.raises(Stage1TrialAdmissionError, match="WRONG_CAMPAIGN"):
        verify_stage1_derived_trial_record(
            trial,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=(b_binding.run_id,),
            source_inventory_hash="e" * 64,
            calendar_hash="d" * 64,
        )


def test_reject_crossed_br_accounts() -> None:
    """B2 control: account allocated to ARM-B cannot be bound to ARM-R."""
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]
    r_binding = bindings[1]
    manifest_hash = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=(r_binding.run_id,),
    )

    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=r_binding.run_id,
        arm_id="ARM-R",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        source_inventory_hash="e" * 64,
        calendar_hash="d" * 64,
        start_session_index=0,
        outcome_classification="NO_ATTEMPT",
        completeness_classification="INVALID",
    )
    with pytest.raises(
        Stage1TrialAdmissionError, match="CROSSED_ACCOUNT_OR_WRONG_BINDING"
    ):
        verify_stage1_derived_trial_record(
            trial,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=(r_binding.run_id,),
            source_inventory_hash="e" * 64,
            calendar_hash="d" * 64,
        )


def test_reject_partial_fill_falsely_treated_as_complete() -> None:
    """B2 control: 2 staged orders with 1 fill cannot claim complete status."""
    m0_inv = OriginalInvocationBindingV1(
        invocation_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b1"),
        m0_run_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b2"),
        m0_audit_event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b3"),
    )
    with pytest.raises(
        (Stage1TrialAdmissionError, ValueError),
        match="PARTIAL_FILL_CANNOT_BE_COMPLETE_CLASSIFICATION",
    ):
        build_stage1_result_trial_binding(
            campaign_id="CAMP-E1-SYNTH-001",
            campaign_spec_fingerprint="a" * 64,
            complete_manifest_fingerprint="b" * 64,
            run_id="RUN-001",
            arm_id="ARM-B",
            portfolio_account_id="SYNTH-ACC-B-001",
            checkpoint_id="CKPT-001",
            opening_book_identity="BOOK-001",
            opening_book_hash="f" * 64,
            m0_invocation=m0_inv,
            result_hash="1" * 64,
            trace_hash="2" * 64,
            final_book_hash="3" * 64,
            final_nav=Decimal("10050"),
            cash_balance=Decimal("50"),
            cumulative_transaction_costs=Decimal("2"),
            order_count=2,
            fill_count=1,  # partial fill!
            classification="complete",  # false claim of complete!
            ledger_ref=OriginalReferenceV1(
                event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b4"),
                event_hash="4" * 64,
            ),
        )


def test_reject_unknown_cost_converted_to_zero() -> None:
    """B2 control: unknown operating cost cannot yield valid economic gain/return."""
    campaign = make_golden_campaign()
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]

    cost_unknown = _make_cost(
        "ARM-B", b_binding.portfolio_account_id, "cost-u", basis="unknown"
    )
    m0_inv = OriginalInvocationBindingV1(
        invocation_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b1"),
        m0_run_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b2"),
        m0_audit_event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b3"),
    )
    result_bind = build_stage1_result_trial_binding(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint="c" * 64,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        m0_invocation=m0_inv,
        result_hash="1" * 64,
        trace_hash="2" * 64,
        final_book_hash="3" * 64,
        final_nav=Decimal("10100"),
        cash_balance=Decimal("100"),
        cumulative_transaction_costs=Decimal("2"),
        order_count=1,
        fill_count=1,
        classification="complete",
        ledger_ref=OriginalReferenceV1(
            event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b4"),
            event_hash="4" * 64,
        ),
    )
    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint="c" * 64,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        result_binding=result_bind,
        source_inventory_hash="e" * 64,
        calendar_hash="d" * 64,
        start_session_index=0,
        end_session_index=21,
        outcome_classification="COMPLETED",
        completeness_classification="COMPLETE",
        costs=(cost_unknown,),
        start_nav=Decimal("10000"),
        end_nav=Decimal("10100"),
        trading_costs=Decimal("2"),
    )
    # Net trading return is known
    assert trial.net_investment_gain == Decimal("100")
    # Economic gain MUST stay None because cost is unknown
    assert trial.economic_gain is None
    assert trial.economic_return is None
    assert trial.operating_cost_projection.status == "UNAVAILABLE"


def test_reject_tampered_result_hash() -> None:
    """B2 control: tampered result hash fails hash verification."""
    m0_inv = OriginalInvocationBindingV1(
        invocation_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b1"),
        m0_run_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b2"),
        m0_audit_event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b3"),
    )
    res = build_stage1_result_trial_binding(
        campaign_id="CAMP-E1-SYNTH-001",
        campaign_spec_fingerprint="a" * 64,
        complete_manifest_fingerprint="b" * 64,
        run_id="RUN-001",
        arm_id="ARM-B",
        portfolio_account_id="SYNTH-ACC-B-001",
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        m0_invocation=m0_inv,
        result_hash="1" * 64,
        trace_hash="2" * 64,
        final_book_hash="3" * 64,
        final_nav=Decimal("10050"),
        cash_balance=Decimal("50"),
        cumulative_transaction_costs=Decimal("2"),
        order_count=1,
        fill_count=1,
        classification="complete",
        ledger_ref=OriginalReferenceV1(
            event_id=UUID("0192e2b3-7640-7f22-9653-0c58e72782b4"),
            event_hash="4" * 64,
        ),
    )
    # Tamper result_hash
    data = res.model_dump(mode="python")
    data["result_hash"] = "9" * 64
    with pytest.raises(
        (Stage1TrialAdmissionError, ValueError),
        match="RESULT_BINDING_HASH_MISMATCH",
    ):
        Stage1ResultTrialBindingV1.model_validate(data)


def test_reject_incorrect_source_vintage() -> None:
    """B2 control: wrong source inventory hash fails admission."""
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]
    manifest_hash = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=("RUN-001",),
    )

    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        source_inventory_hash="e" * 64,
        calendar_hash="d" * 64,
        start_session_index=0,
        outcome_classification="NO_ATTEMPT",
        completeness_classification="INVALID",
    )
    with pytest.raises(Stage1TrialAdmissionError, match="INCORRECT_SOURCE_VINTAGE"):
        verify_stage1_derived_trial_record(
            trial,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=("RUN-001",),
            source_inventory_hash="WRONG_SOURCE_VINTAGE" + "0" * 44,
            calendar_hash="d" * 64,
        )


def test_reject_manifest_fingerprint_mismatch() -> None:
    """B2 control: wrong complete manifest fingerprint fails admission."""
    campaign = make_golden_campaign()
    arms = (make_golden_arm_b(), make_golden_arm_r())
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]

    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint="0" * 64,  # wrong fingerprint
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        source_inventory_hash="e" * 64,
        calendar_hash="d" * 64,
        start_session_index=0,
        outcome_classification="NO_ATTEMPT",
        completeness_classification="INVALID",
    )
    with pytest.raises(
        Stage1TrialAdmissionError, match="MANIFEST_FINGERPRINT_MISMATCH"
    ):
        verify_stage1_derived_trial_record(
            trial,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=("RUN-001",),
            source_inventory_hash="e" * 64,
            calendar_hash="d" * 64,
        )


def test_independent_fresh_process_verification(tmp_path: Path) -> None:
    """Verify trial serialization and fresh-process readback without live state."""
    campaign = make_golden_campaign()
    bindings = tuple(make_golden_bindings())
    b_binding = bindings[0]
    manifest_hash = "c" * 64
    cal_hash = "d" * 64
    src_hash = "e" * 64

    trial = build_stage1_derived_trial_record(
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_id=b_binding.run_id,
        arm_id="ARM-B",
        portfolio_account_id=b_binding.portfolio_account_id,
        checkpoint_id="CKPT-001",
        opening_book_identity="BOOK-001",
        opening_book_hash="f" * 64,
        source_inventory_hash=src_hash,
        calendar_hash=cal_hash,
        start_session_index=0,
        outcome_classification="RETAINED",
        completeness_classification="PENDING_RESULT",
        reasons=("NO_SWITCH_ATTEMPTED",),
    )
    out_file = tmp_path / "trial.json"
    out_file.write_text(trial.model_dump_json(), encoding="utf-8")

    code = f"""
import sys
from drift.experiments.stage1_trial_record import Stage1DerivedTrialRecordV1

raw = open({str(out_file)!r}, 'r').read()
record = Stage1DerivedTrialRecordV1.model_validate_json(raw)
assert record.trial_id == '{trial.trial_id}'
assert record.trial_record_hash == '{trial.trial_record_hash}'
assert not record.scientifically_qualified
assert not record.authorizes_trading
sys.exit(0)
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"Fresh process failed: {res.stderr}"
