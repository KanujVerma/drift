"""Unit tests for Stage 1 prospective study contracts and N12 operation boundaries."""

from datetime import UTC, date, datetime

import pytest

from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_prospective_study import (
    ProspectiveLifecycle,
    ProspectiveRegistrationV1,
    ProspectiveSessionEvidenceV1,
    ProspectiveStudyPlanV1,
    advance_prospective_session,
    assess_prospective_readiness,
    create_prospective_session_evidence,
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


def make_prospective_evidence(
    reg: ProspectiveRegistrationV1, session_index: int, session_date: date
) -> ProspectiveSessionEvidenceV1:
    return create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=session_index,
        session_date=session_date,
        evidence_artifacts={"observation_hash": H},
    )


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

    # Advance session with verified evidence
    ev = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    stepped = advance_prospective_session(
        reg, session_date=date(2026, 11, 3), session_evidence=ev
    )
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
    ev_early = make_prospective_evidence(reg, 0, date(2026, 1, 1))
    with pytest.raises(ValueError, match="SESSION_DATE_OUTSIDE_PLANNED_WINDOW"):
        advance_prospective_session(
            reg, session_date=date(2026, 1, 1), session_evidence=ev_early
        )

    # Valid first step (Nov 3, 2026 is Tuesday)
    ev1 = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    s1 = advance_prospective_session(
        reg, session_date=date(2026, 11, 3), session_evidence=ev1
    )
    assert s1.last_observed_session == date(2026, 11, 3)

    # Repeating same date
    ev_same = make_prospective_evidence(s1, 1, date(2026, 11, 3))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_CONSECUTIVE"):
        advance_prospective_session(
            s1, session_date=date(2026, 11, 3), session_evidence=ev_same
        )

    # Advance to 2026-11-05 (Thursday)
    ev2 = make_prospective_evidence(s1, 1, date(2026, 11, 5))
    s2 = advance_prospective_session(
        s1, session_date=date(2026, 11, 5), session_evidence=ev2
    )
    assert s2.observed_session_count == 2

    # Earlier date within window
    ev_past = make_prospective_evidence(s2, 2, date(2026, 11, 4))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_CONSECUTIVE"):
        advance_prospective_session(
            s2, session_date=date(2026, 11, 4), session_evidence=ev_past
        )


def test_prospective_step_enforces_lifecycle_states() -> None:
    from drift.serialization.canonical import canonical_json

    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    base_reg = register_prospective_study(
        registration_id="REG-LIFECYCLE",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )

    forbidden_states: list[ProspectiveLifecycle] = [
        "BLOCKED",
        "PAUSED",
        "SAFETY_TERMINATED",
        "INVALID",
        "ACCEPTED",
        "COMPLETED_PENDING_REVIEW",
    ]
    for state in forbidden_states:
        body = {
            "schema_version": "drift-stage1-prospective-registration/1",
            "registration_id": base_reg.registration_id,
            "registered_at": base_reg.registered_at,
            "frozen_study": base_reg.frozen_study,
            "operational_state": state,
            "observed_session_count": 0,
            "last_observed_session": None,
            "scheduled_sessions": 504,
            "has_broker_dispatch_capability": False,
        }
        h = content_hash(body)
        invalid_reg = base_reg.model_validate_json(
            canonical_json(body | {"registration_hash": h})
        )
        ev = make_prospective_evidence(invalid_reg, 0, date(2026, 11, 3))
        with pytest.raises(ValueError, match="CANNOT_ADVANCE_FROM_LIFECYCLE_STATE"):
            advance_prospective_session(
                invalid_reg, session_date=date(2026, 11, 3), session_evidence=ev
            )


def test_prospective_step_enforces_trading_calendar_and_evidence() -> None:
    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    reg = register_prospective_study(
        registration_id="REG-CAL-TEST",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )

    # Missing session evidence
    with pytest.raises(ValueError, match="SESSION_EVIDENCE_REQUIRED"):
        advance_prospective_session(reg, session_date=date(2026, 11, 3))

    # Weekend rejection (Nov 7, 2026 is Saturday)
    ev_wknd = make_prospective_evidence(reg, 0, date(2026, 11, 7))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_A_TRADING_DAY"):
        advance_prospective_session(
            reg, session_date=date(2026, 11, 7), session_evidence=ev_wknd
        )

    # Calendar membership rejection
    cal = {date(2026, 11, 4), date(2026, 11, 5)}
    ev_not_in_cal = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_IN_CALENDAR"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_not_in_cal,
            calendar=cal,
        )

    # Evidence index mismatch
    ev_wrong_idx = make_prospective_evidence(reg, 5, date(2026, 11, 3))
    with pytest.raises(ValueError, match="SESSION_EVIDENCE_INDEX_MISMATCH"):
        advance_prospective_session(
            reg, session_date=date(2026, 11, 3), session_evidence=ev_wrong_idx
        )
