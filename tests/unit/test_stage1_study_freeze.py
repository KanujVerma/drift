"""G3 refuses invented qualification, changed protocols and unverified holdouts."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    ConventionalSelectorPolicyV1,
    Stage1StudyDraftV1,
    StudyCostPolicyV1,
    StudyDateWindowV1,
    StudyEvidenceReferenceV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyStatisticalPolicyV1,
    assess_study_readiness,
    freeze_study,
)
from drift.serialization.canonical import content_hash

H = "a" * 64
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def draft() -> Stage1StudyDraftV1:
    return Stage1StudyDraftV1(
        study_id="SYNTHETIC-G3-SCHEMA-TEST-NOT-A-REAL-STUDY",
        created_at=NOW,
        mode="RETROSPECTIVE_DISCOVERY",
        prior_holdout_exposure="UNKNOWN",
        development=StudyDateWindowV1(start=date(2021, 1, 1), end=date(2023, 12, 31)),
        validation=StudyDateWindowV1(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        scoring=StudyDateWindowV1(start=date(2025, 1, 1), end=date(2025, 12, 31)),
    )


def complete_fixture() -> Stage1StudyDraftV1:
    # Deliberately synthetic values: no accepted investment policy is implied.
    return draft().model_copy(
        update={
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
                volatility_penalty=Decimal(1),
                drawdown_penalty=Decimal(1),
                switching_cost_penalty=Decimal(1),
                development_fit_hash=H,
                executable_formula_hash=H,
            ),
            "model": StudyModelPolicyV1(
                provider="synthetic",
                immutable_model_revision="fixture-1",
                model_record_hash=H,
                prompt_hash=H,
                tools_policy_hash=H,
                context_policy_hash=H,
                feedback_policy_hash=H,
                decoding_policy_hash=H,
                seed=0,
                known_training_cutoff=date(2023, 1, 1),
            ),
            "costs": StudyCostPolicyV1(
                trading_model_hash=H, dated_cost_evidence_hash=H
            ),
            "statistics": StudyStatisticalPolicyV1(
                alpha=Decimal("0.05"),
                minimum_economic_advantage_fraction=Decimal("0.01"),
                uncertainty_method="STATIONARY_BLOCK_BOOTSTRAP",
                bootstrap_repetitions=1000,
                bootstrap_seed=0,
                block_length_policy_hash=H,
                multiplicity_policy_hash=H,
                stopping_policy_hash=H,
                risk_free_policy_hash=H,
            ),
        }
    )


def refs(plan: Stage1StudyDraftV1) -> tuple[StudyEvidenceReferenceV1, ...]:
    return tuple(
        StudyEvidenceReferenceV1(
            role=role,
            receipt_id="synthetic:" + role,
            receipt_hash=content_hash(role),
            protocol_hash=plan.protocol_hash,
            accepted_at=NOW,
        )
        for role in REQUIRED_ROLES
    )


class SyntheticVerifier:
    def verify(self, reference: StudyEvidenceReferenceV1) -> bool:
        return reference.receipt_hash == content_hash(reference.role)


def test_incomplete_draft_never_freezes() -> None:
    report = assess_study_readiness(draft())
    assert report.status == "BLOCKED"
    assert "MISSING_CONFIGURATION:model" in report.blockers
    assert "MISSING_CONFIGURATION:mandate" in report.blockers
    with pytest.raises(ValueError, match="G3_FREEZE_BLOCKED"):
        freeze_study(draft(), frozen_at=NOW, evidence=(), verifier=SyntheticVerifier())


def test_matching_hashes_are_not_independent_acceptance() -> None:
    plan = complete_fixture()
    report = assess_study_readiness(plan, evidence=refs(plan))
    assert report.status == "BLOCKED"
    assert len(report.blockers) == len(REQUIRED_ROLES)


def test_complete_fixture_freezes_reproducibly_but_does_not_grant_trading() -> None:
    plan = complete_fixture()
    proof = refs(plan)
    a = freeze_study(plan, frozen_at=NOW, evidence=proof, verifier=SyntheticVerifier())
    b = freeze_study(
        plan, frozen_at=NOW, evidence=proof[::-1], verifier=SyntheticVerifier()
    )
    assert a == b
    report = assess_study_readiness(plan, evidence=proof, verifier=SyntheticVerifier())
    assert report.status == "READY_FOR_HISTORICAL_DISCOVERY"
    assert not report.authorizes_trading and not report.establishes_efficacy
    with pytest.raises(ValidationError, match="G3_FREEZE_HASH_MISMATCH"):
        a.model_copy(update={"freeze_hash": "f" * 64})


def test_changed_protocol_invalidates_all_old_acceptances() -> None:
    plan = complete_fixture()
    changed = plan.model_copy(update={"decision_cutoff_policy_hash": "b" * 64})
    report = assess_study_readiness(
        changed, evidence=refs(plan), verifier=SyntheticVerifier()
    )
    assert report.status == "BLOCKED"
    assert len(report.blockers) == len(REQUIRED_ROLES)


@pytest.mark.parametrize("exposure", ["UNKNOWN", "EXPOSED"])
def test_confirmation_requires_audited_holdout(exposure: Any) -> None:
    plan = complete_fixture().model_copy(
        update={
            "mode": "CONFIRMATORY_HISTORICAL",
            "prior_holdout_exposure": exposure,
        }
    )
    report = assess_study_readiness(
        plan, evidence=refs(plan), verifier=SyntheticVerifier()
    )
    assert "HOLDOUT_NOT_AUDITED_UNEXPOSED" in report.blockers


def test_pretraining_after_scoring_start_is_not_pristine() -> None:
    base = complete_fixture()
    assert base.model is not None
    plan = base.model_copy(
        update={
            "mode": "CONFIRMATORY_HISTORICAL",
            "prior_holdout_exposure": "AUDITED_UNEXPOSED",
            "model": base.model.model_copy(
                update={"known_training_cutoff": date(2025, 1, 1)}
            ),
        }
    )
    report = assess_study_readiness(
        plan, evidence=refs(plan), verifier=SyntheticVerifier()
    )
    assert "MODEL_PRETRAINING_CUTOFF_NOT_ELIGIBLE" in report.blockers


def test_duplicate_or_foreign_receipt_never_freezes() -> None:
    plan = complete_fixture()
    proof = refs(plan)
    report = assess_study_readiness(
        plan, evidence=proof + proof[:1], verifier=SyntheticVerifier()
    )
    assert report.status == "BLOCKED"
    bad = proof[0].model_copy(update={"receipt_hash": "f" * 64})
    report = assess_study_readiness(
        plan, evidence=(bad,) + proof[1:], verifier=SyntheticVerifier()
    )
    assert "ORIGINAL_EVIDENCE_NOT_ACCEPTED:g2_integration" in report.blockers


def test_verifier_outage_is_not_pass() -> None:
    class Broken:
        def verify(self, reference: StudyEvidenceReferenceV1) -> bool:
            raise OSError("original source unavailable")

    plan = complete_fixture()
    report = assess_study_readiness(plan, evidence=refs(plan), verifier=Broken())
    assert report.status == "BLOCKED"
    assert all(b.startswith("ORIGINAL_VERIFIER_FAILED:") for b in report.blockers)


def test_market_dates_and_stage1_boundaries_cannot_be_silently_changed() -> None:
    plan = complete_fixture()
    with pytest.raises(ValidationError):
        plan.model_copy(update={"warmup_sessions": 252})
    with pytest.raises(ValidationError, match="OVERLAP"):
        plan.model_copy(update={"validation": plan.development})
    with pytest.raises(ValidationError, match="UNIVERSE_OR_ACTION"):
        plan.model_copy(update={"universe": tuple(reversed(plan.universe))})


def test_deserialized_freeze_does_not_replace_original_acceptance() -> None:
    from drift.experiments.stage1_study_freeze import verify_frozen_study

    plan = complete_fixture()
    frozen = freeze_study(
        plan, frozen_at=NOW, evidence=refs(plan), verifier=SyntheticVerifier()
    )

    class Reject:
        def verify(self, reference: StudyEvidenceReferenceV1) -> bool:
            return False

    with pytest.raises(ValueError, match="G3_FROZEN_EVIDENCE_UNAVAILABLE"):
        verify_frozen_study(frozen, verifier=Reject())


def test_later_acceptance_cannot_backdate_a_freeze() -> None:
    from datetime import timedelta

    plan = complete_fixture()
    proof = refs(plan)
    late = proof[0].model_copy(update={"accepted_at": NOW + timedelta(days=1)})
    with pytest.raises(ValueError, match="ACCEPTANCE_NOT_YET_AVAILABLE"):
        freeze_study(
            plan,
            frozen_at=NOW,
            evidence=(late,) + proof[1:],
            verifier=SyntheticVerifier(),
        )
