"""Unit tests for Stage 1 G3 multi-role evidence admission and freeze pipeline.

Workstream G, Issue 575.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_g3_freeze_pipeline import (
    assemble_stage1_study_draft,
    create_multi_role_evidence_receipts,
    execute_g3_admission_and_freeze,
)
from drift.experiments.stage1_study_freeze import (
    ConventionalSelectorPolicyV1,
    EvidenceRole,
    StudyCostPolicyV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
)

H = "8" * 64
NOW = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)
KEY = "test-secret-key-multi-role"

AUTHORITIES: dict[EvidenceRole, str] = {
    "g2_integration": "auth-g2-lead",
    "dataset_qualification": "auth-data-reviewer",
    "mandate_review": "auth-compliance-officer",
    "comparator_review": "auth-quant-comparator-lead",
    "cost_review": "auth-operations-cost-lead",
    "model_replay": "auth-ai-governance-officer",
    "scientific_protocol_review": "auth-independent-statistician",
    "holdout_audit": "auth-holdout-custodian",
}


def create_fixture_draft(
    mode: str = "CONFIRMATORY_HISTORICAL",
    prior_holdout_exposure: str = "AUDITED_UNEXPOSED",
    known_training_cutoff: date = date(2023, 10, 1),
) -> Any:
    return assemble_stage1_study_draft(
        study_id="STUDY-G3-PIPELINE-TEST",
        created_at=NOW,
        mode=mode,  # type: ignore[arg-type]
        prior_holdout_exposure=prior_holdout_exposure,  # type: ignore[arg-type]
        installed_source_hash=H,
        dataset_manifest_hash=H,
        calendar_and_universe_hash=H,
        decision_cutoff_policy_hash=H,
        seed_and_replication_policy_hash=H,
        mandate=StudyMandateV1(
            maximum_etf_fraction=Decimal("0.20"),
            maximum_equity_fraction=Decimal("0.70"),
            maximum_bond_fraction=Decimal("0.75"),
            maximum_gold_fraction=Decimal("0.20"),
            maximum_gross_fraction=Decimal("1"),
            maximum_turnover_fraction=Decimal("2"),
            existing_breach_policy_hash=H,
            feasibility_report_hash=H,
        ),
        comparator=ConventionalSelectorPolicyV1(
            formula="R:return-risk-drawdown-switchcost/1",
            volatility_penalty=Decimal("0.25"),
            drawdown_penalty=Decimal("0.50"),
            switching_cost_penalty=Decimal("0.00"),
            development_fit_hash=H,
            executable_formula_hash=H,
        ),
        model=StudyModelPolicyV1(
            provider="anthropic",
            immutable_model_revision="claude-3-5-sonnet-20241022",
            model_record_hash=H,
            prompt_hash=H,
            tools_policy_hash=H,
            context_policy_hash=H,
            feedback_policy_hash=H,
            decoding_policy_hash=H,
            seed=42,
            known_training_cutoff=known_training_cutoff,
        ),
        costs=StudyCostPolicyV1(
            trading_model_hash=H,
            dated_cost_evidence_hash=H,
        ),
        statistics=StudyStatisticalPolicyV1(
            alpha=Decimal("0.05"),
            minimum_economic_advantage_fraction=Decimal("0.01"),
            uncertainty_method="STATIONARY_BLOCK_BOOTSTRAP",
            bootstrap_repetitions=10000,
            bootstrap_seed=575,
            block_length_policy_hash=H,
            multiplicity_policy_hash=H,
            stopping_policy_hash=H,
            risk_free_policy_hash=H,
        ),
        development_start=date(2023, 7, 3),
        development_end=date(2023, 12, 29),
        validation_start=date(2024, 1, 2),
        validation_end=date(2024, 12, 31),
        scoring_start=date(2025, 1, 2),
        scoring_end=date(2025, 12, 31),
    )


def test_positive_g3_admission_and_freeze_pipeline() -> None:
    draft = create_fixture_draft()
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "READY_FOR_CONFIRMATORY_SCORING"
    assert result.freeze_hash is not None
    assert result.frozen_study is not None
    assert result.cold_read_readiness is not None
    assert result.cold_read_readiness.status == "READY_FOR_CONFIRMATORY_SCORING"
    assert len(result.readiness.verified_roles) == 8
    assert result.blockers == ()


def test_negative_control_missing_role_evidence() -> None:
    draft = create_fixture_draft()
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    # Omit holdout_audit evidence
    incomplete_evidence = tuple(ref for ref in evidence if ref.role != "holdout_audit")

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=incomplete_evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.frozen_study is None
    assert any("holdout_audit" in b for b in result.blockers)


def test_negative_control_unauthenticated_receipt_rejected() -> None:
    draft = create_fixture_draft()
    # Missing hmac_keys produces unsigned receipts
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=None,
    )

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert result.frozen_study is None
    assert len(result.blockers) == 8


def test_negative_control_authority_not_in_trust_roots() -> None:
    draft = create_fixture_draft()
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    # Disallow comparator_review authority
    modified_trust_roots = dict(trust_roots)
    modified_trust_roots["comparator_review"] = {"unauthorized-root"}

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=modified_trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert any("comparator_review" in b for b in result.blockers)


def test_negative_control_holdout_not_audited_unexposed() -> None:
    draft = create_fixture_draft(prior_holdout_exposure="UNKNOWN")
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert "HOLDOUT_NOT_AUDITED_UNEXPOSED" in result.blockers


def test_negative_control_model_training_cutoff_overlaps_scoring() -> None:
    draft = create_fixture_draft(known_training_cutoff=date(2025, 2, 1))
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )

    assert result.status == "BLOCKED"
    assert "MODEL_PRETRAINING_CUTOFF_NOT_ELIGIBLE" in result.blockers


def test_frozen_study_tamper_fails() -> None:
    draft = create_fixture_draft()
    hmac_keys = {auth: KEY for auth in AUTHORITIES.values()}
    evidence, store, trust_roots, auth_issuers = create_multi_role_evidence_receipts(
        protocol_hash=draft.protocol_hash,
        accepted_at=NOW,
        authorities=AUTHORITIES,
        hmac_keys=hmac_keys,
    )

    result = execute_g3_admission_and_freeze(
        draft,
        evidence=evidence,
        trust_roots=trust_roots,
        receipt_store=store,
        authenticated_issuers=auth_issuers,
        frozen_at=NOW,
    )
    assert result.frozen_study is not None

    with pytest.raises(ValidationError, match="G3_FREEZE_HASH_MISMATCH"):
        result.frozen_study.model_copy(update={"freeze_hash": "f" * 64})
