"""G3 default-omission regressions; all policy/evidence inputs are synthetic."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_g3_freeze_pipeline import assemble_stage1_study_draft
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    ConventionalSelectorPolicyV1,
    FrozenStage1StudyV1,
    Stage1StudyDraftV1,
    StudyCostPolicyV1,
    StudyEvidenceReferenceV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
    assess_study_readiness,
    freeze_study,
    verify_frozen_study,
)
from drift.serialization.canonical import canonical_json

H = "8" * 64
NOW = datetime(2026, 11, 9, tzinfo=UTC)


def _assemble(**overrides: Any) -> Stage1StudyDraftV1:
    """Supply synthetic required inputs, omitting all eight corrected defaults."""
    inputs: dict[str, Any] = {
        "study_id": "SYNTHETIC-G3-DEFAULTS",
        "created_at": NOW,
        "installed_source_hash": H,
        "dataset_manifest_hash": H,
        "calendar_and_universe_hash": H,
        "decision_cutoff_policy_hash": H,
        "seed_and_replication_policy_hash": H,
        "mandate": StudyMandateV1(
            maximum_etf_fraction=Decimal("0.20"),
            maximum_equity_fraction=Decimal("0.70"),
            maximum_bond_fraction=Decimal("0.75"),
            maximum_gold_fraction=Decimal("0.20"),
            maximum_gross_fraction=Decimal("1"),
            maximum_turnover_fraction=Decimal("2"),
            existing_breach_policy_hash=H,
            feasibility_report_hash=H,
        ),
        "comparator": ConventionalSelectorPolicyV1(
            formula="R:return-risk-drawdown-switchcost/1",
            volatility_penalty=Decimal("0.25"),
            drawdown_penalty=Decimal("0.50"),
            switching_cost_penalty=Decimal("1"),
            development_fit_hash=H,
            executable_formula_hash=H,
        ),
        "model": StudyModelPolicyV1(
            provider="SYNTHETIC-TEST-ONLY",
            immutable_model_revision="SYNTHETIC-REVISION-1",
            model_record_hash=H,
            prompt_hash=H,
            tools_policy_hash=H,
            context_policy_hash=H,
            feedback_policy_hash=H,
            decoding_policy_hash=H,
            seed=42,
            known_training_cutoff=date(2023, 1, 1),
        ),
        "costs": StudyCostPolicyV1(
            trading_model_hash=H,
            dated_cost_evidence_hash=H,
        ),
        "statistics": StudyStatisticalPolicyV1(
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
    }
    return assemble_stage1_study_draft(**(inputs | overrides))


class _SyntheticVerifier:
    """A unit-test double, never a source of original scientific acceptance."""

    def verify(self, reference: StudyEvidenceReferenceV1) -> bool:
        return reference.receipt_id == f"SYNTHETIC-{reference.role}"


def _synthetic_evidence(
    draft: Stage1StudyDraftV1,
) -> tuple[StudyEvidenceReferenceV1, ...]:
    return tuple(
        StudyEvidenceReferenceV1(
            role=role,
            receipt_id=f"SYNTHETIC-{role}",
            receipt_hash=H,
            protocol_hash=draft.protocol_hash,
            accepted_at=NOW,
        )
        for role in REQUIRED_ROLES
    )


def test_omitted_mode_and_exposure_do_not_assert_confirmatory_eligibility() -> None:
    draft = _assemble()

    assert draft.mode == "RETROSPECTIVE_DISCOVERY"
    assert draft.prior_holdout_exposure == "UNKNOWN"


def test_default_windows_match_full_locked_calendar_years() -> None:
    draft = _assemble()

    assert (draft.development.start, draft.development.end) == (
        date(2021, 1, 1),
        date(2023, 12, 31),
    )
    assert (draft.validation.start, draft.validation.end) == (
        date(2024, 1, 1),
        date(2024, 12, 31),
    )
    assert (draft.scoring.start, draft.scoring.end) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


def test_defaults_still_require_all_original_evidence_roles() -> None:
    report = assess_study_readiness(_assemble())

    assert report.status == "BLOCKED"
    assert report.verified_roles == ()
    assert set(report.blockers) == {
        f"MISSING_OR_DUPLICATE_ORIGINAL_EVIDENCE:{role}" for role in REQUIRED_ROLES
    }
    assert not report.authorizes_trading
    assert not report.establishes_efficacy


def test_explicit_confirmatory_mode_with_omitted_exposure_is_blocked() -> None:
    draft = _assemble(mode="CONFIRMATORY_HISTORICAL")
    evidence = _synthetic_evidence(draft)
    report = assess_study_readiness(
        draft, evidence=evidence, verifier=_SyntheticVerifier()
    )

    assert report.verified_roles == REQUIRED_ROLES
    assert report.status == "BLOCKED"
    assert report.blockers == ("HOLDOUT_NOT_AUDITED_UNEXPOSED",)
    with pytest.raises(ValueError, match="HOLDOUT_NOT_AUDITED_UNEXPOSED"):
        freeze_study(
            draft, frozen_at=NOW, evidence=evidence, verifier=_SyntheticVerifier()
        )


@pytest.mark.parametrize("exposure", ["UNKNOWN", "EXPOSED", "AUDITED_UNEXPOSED"])
def test_explicit_exposure_does_not_promote_default_mode(exposure: str) -> None:
    draft = _assemble(prior_holdout_exposure=exposure)

    assert draft.prior_holdout_exposure == exposure
    assert draft.mode == "RETROSPECTIVE_DISCOVERY"


def test_explicit_audited_confirmatory_inputs_remain_explicit() -> None:
    draft = _assemble(
        mode="CONFIRMATORY_HISTORICAL", prior_holdout_exposure="AUDITED_UNEXPOSED"
    )
    report = assess_study_readiness(
        draft, evidence=_synthetic_evidence(draft), verifier=_SyntheticVerifier()
    )

    assert draft.mode == "CONFIRMATORY_HISTORICAL"
    assert draft.prior_holdout_exposure == "AUDITED_UNEXPOSED"
    assert report.status == "READY_FOR_CONFIRMATORY_SCORING"
    assert not report.establishes_efficacy


def test_cold_read_preserves_discovery_and_unknown_exposure() -> None:
    draft = _assemble()
    frozen = freeze_study(
        draft,
        frozen_at=NOW,
        evidence=_synthetic_evidence(draft),
        verifier=_SyntheticVerifier(),
    )
    cold_read = FrozenStage1StudyV1.model_validate_json(canonical_json(frozen))
    report = verify_frozen_study(cold_read, verifier=_SyntheticVerifier())

    assert cold_read.protocol.mode == "RETROSPECTIVE_DISCOVERY"
    assert cold_read.protocol.prior_holdout_exposure == "UNKNOWN"
    assert report.status == "READY_FOR_HISTORICAL_DISCOVERY"


def test_receipts_for_previous_defaults_cannot_admit_corrected_protocol() -> None:
    old_draft = _assemble(
        mode="CONFIRMATORY_HISTORICAL",
        prior_holdout_exposure="AUDITED_UNEXPOSED",
        development_start=date(2023, 7, 3),
        development_end=date(2023, 12, 29),
        validation_start=date(2024, 1, 2),
        scoring_start=date(2025, 1, 2),
    )
    corrected = _assemble()
    report = assess_study_readiness(
        corrected,
        evidence=_synthetic_evidence(old_draft),
        verifier=_SyntheticVerifier(),
    )

    assert corrected.protocol_hash != old_draft.protocol_hash
    assert report.status == "BLOCKED"
    assert set(report.blockers) == {
        f"EVIDENCE_FOR_DIFFERENT_PROTOCOL:{role}" for role in REQUIRED_ROLES
    }


def test_explicit_date_windows_are_not_overwritten() -> None:
    draft = _assemble(
        development_start=date(2021, 2, 1),
        development_end=date(2022, 12, 30),
        validation_start=date(2023, 1, 3),
        validation_end=date(2023, 12, 29),
        scoring_start=date(2024, 1, 2),
        scoring_end=date(2024, 12, 30),
    )

    assert (draft.development.start, draft.development.end) == (
        date(2021, 2, 1),
        date(2022, 12, 30),
    )
    assert (draft.validation.start, draft.validation.end) == (
        date(2023, 1, 3),
        date(2023, 12, 29),
    )
    assert (draft.scoring.start, draft.scoring.end) == (
        date(2024, 1, 2),
        date(2024, 12, 30),
    )


def test_explicit_overlapping_windows_still_fail() -> None:
    with pytest.raises(ValidationError, match="G3_CHRONOLOGICAL_SPLITS_OVERLAP"):
        _assemble(development_end=date(2024, 1, 1))
