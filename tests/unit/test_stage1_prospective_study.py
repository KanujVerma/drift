"""Unit tests for Stage 1 prospective study contracts and N12 operation boundaries."""

from datetime import UTC, date, datetime

import pytest

from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_prospective_study import (
    ProspectiveStudyPlanV1,
    advance_prospective_session,
    assess_prospective_readiness,
    create_prospective_study_plan,
    freeze_prospective_study,
    register_prospective_study,
)
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    StudyEvidenceReferenceV1,
)
from drift.serialization.canonical import content_hash

H = "8" * 64
NOW = datetime(2026, 11, 2, 6, 30, 0, tzinfo=UTC)


def make_prospective_plan() -> tuple[
    ProspectiveStudyPlanV1,
    tuple[StudyEvidenceReferenceV1, ...],
    ProductionStudyEvidenceVerifier,
]:
    plan = create_prospective_study_plan(
        plan_id="PROSP-2026-V1",
        created_at=NOW,
        calendar_identity="XNYS-2026-2027",
        first_eligible_session=date(2026, 11, 3),
        planned_last_session=date(2028, 11, 3),
        operating_environment_hash=H,
        model_binding_hash=H,
        market_admission_hash=H,
        mandate_hash=H,
        cost_policy_hash=H,
    )

    receipts_store = {}
    evidence = []
    trust_roots = {}
    for role in REQUIRED_ROLES:
        payload = {
            "role": role,
            "receipt_id": f"RCPT-{role}",
            "protocol_hash": plan.plan_hash,
            "authority_id": "trusted-root",
            "status": "ACCEPTED",
        }
        r_hash = content_hash(payload)
        receipts_store[f"RCPT-{role}"] = payload
        evidence.append(
            StudyEvidenceReferenceV1(
                role=role,
                receipt_id=f"RCPT-{role}",
                receipt_hash=r_hash,
                protocol_hash=plan.plan_hash,
                accepted_at=NOW,
            )
        )
        trust_roots[role] = {"trusted-root"}

    verifier = ProductionStudyEvidenceVerifier(
        trust_roots=trust_roots,
        receipt_resolver=lambda rid: receipts_store[rid],
    )
    return plan, tuple(evidence), verifier


def test_n12_prospective_study_readiness_and_freeze() -> None:
    plan, evidence, verifier = make_prospective_plan()
    readiness = assess_prospective_readiness(plan, evidence=evidence, verifier=verifier)
    assert readiness.status == "READY_FOR_PROSPECTIVE_REGISTRATION"
    assert len(readiness.verified_roles) == 8

    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    assert len(frozen.freeze_hash) == 64

    # Register without broker capability
    reg = register_prospective_study(
        registration_id="REG-PROSP-01",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )
    assert reg.operational_state == "REGISTERED"
    assert reg.observed_session_count == 0

    # Advance session
    stepped = advance_prospective_session(reg, session_date=date(2026, 11, 3))
    assert stepped.observed_session_count == 1
    assert stepped.operational_state == "RUNNING"


def test_n12_prospective_rejects_broker_dispatch_capability() -> None:
    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )

    with pytest.raises(ValueError, match="BROKER_DISPATCH_CAPABILITY_FORBIDDEN"):
        register_prospective_study(
            registration_id="REG-FORBIDDEN-BROKER",
            registered_at=NOW,
            frozen_study=frozen,
            has_broker_dispatch_capability=True,
        )


def test_prospective_plan_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError, match="PROSPECTIVE_DATES_REVERSED"):
        create_prospective_study_plan(
            plan_id="PROSP-REVERSED",
            created_at=NOW,
            calendar_identity="XNYS-2026-2027",
            first_eligible_session=date(2028, 11, 3),
            planned_last_session=date(2026, 11, 3),
            operating_environment_hash=H,
            model_binding_hash=H,
            market_admission_hash=H,
            mandate_hash=H,
            cost_policy_hash=H,
        )


def test_prospective_step_enforces_monotonicity_and_window() -> None:
    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    reg = register_prospective_study(
        registration_id="REG-WINDOW-TEST",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )

    # Date before first_eligible_session
    with pytest.raises(ValueError, match="SESSION_DATE_OUTSIDE_PLANNED_WINDOW"):
        advance_prospective_session(reg, session_date=date(2026, 1, 1))

    # Valid first step
    s1 = advance_prospective_session(reg, session_date=date(2026, 11, 3))
    assert s1.last_observed_session == date(2026, 11, 3)

    # Repeating same date
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_CONSECUTIVE"):
        advance_prospective_session(s1, session_date=date(2026, 11, 3))

    # Advance to 2026-11-05
    s2 = advance_prospective_session(s1, session_date=date(2026, 11, 5))
    assert s2.observed_session_count == 2

    # Earlier date within window
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_CONSECUTIVE"):
        advance_prospective_session(s2, session_date=date(2026, 11, 4))
