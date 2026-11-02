"""Unit tests for Stage 1 prospective study contracts and N12 operation boundaries."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
)
from drift.experiments.stage1_prospective_study import (
    ProductionProspectiveProducerVerifier,
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
    reg: ProspectiveRegistrationV1,
    session_index: int,
    session_date: date,
    *,
    custom_artifacts: dict[str, str] | None = None,
    authority_id: str = "drift.stage1.trusted_authority",
) -> tuple[ProspectiveSessionEvidenceV1, dict[str, Any]]:
    artifacts: dict[str, Any] = {}
    artifact_hashes: dict[str, str] = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": session_index,
            "session_date": session_date.isoformat(),
            "authority_id": authority_id,
            "execution_payload": {
                "status": "OK",
                "session_index": session_index,
                "recorded_orders": 2,
            },
        }
        h = content_hash(art_body)
        artifacts[h] = art_body
        artifact_hashes[art_name] = h

    if custom_artifacts is not None:
        artifact_hashes = custom_artifacts

    ev = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=session_index,
        session_date=session_date,
        evidence_artifacts=artifact_hashes,
    )
    return ev, artifacts


def make_producer_verifier(
    artifact_store: dict[str, Any],
    trust_roots: set[str] | None = None,
) -> ProductionProspectiveProducerVerifier:
    return ProductionProspectiveProducerVerifier(
        trust_roots=trust_roots or {"drift.stage1.trusted_authority", "trusted-root"},
        authenticated_artifact_hashes=set(artifact_store.keys()),
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

    # Advance session with verified evidence and artifact store
    ev, art_store = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    stepped = advance_prospective_session(
        reg,
        session_date=date(2026, 11, 3),
        session_evidence=ev,
        artifact_store=art_store,
        producer_verifier=make_producer_verifier(art_store),
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


def test_prospective_step_enforces_sequential_sessions_and_rejects_gaps() -> None:
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
    ev_early, store_early = make_prospective_evidence(reg, 0, date(2026, 1, 1))
    with pytest.raises(ValueError, match="SESSION_DATE_OUTSIDE_PLANNED_WINDOW"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 1, 1),
            session_evidence=ev_early,
            artifact_store=store_early,
            producer_verifier=make_producer_verifier(store_early),
        )

    # Valid first step (Nov 3, 2026 is Tuesday)
    ev1, store1 = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    s1 = advance_prospective_session(
        reg,
        session_date=date(2026, 11, 3),
        session_evidence=ev1,
        artifact_store=store1,
        producer_verifier=make_producer_verifier(store1),
    )
    assert s1.last_observed_session == date(2026, 11, 3)

    # Repeating same date
    ev_same, store_same = make_prospective_evidence(s1, 1, date(2026, 11, 3))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_SEQUENTIAL"):
        advance_prospective_session(
            s1,
            session_date=date(2026, 11, 3),
            session_evidence=ev_same,
            artifact_store=store_same,
            producer_verifier=make_producer_verifier(store_same),
        )

    # Skipping Wednesday 2026-11-04 and jumping to Thursday 2026-11-05 (GAP REJECTION)
    ev_skip, store_skip = make_prospective_evidence(s1, 1, date(2026, 11, 5))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_SEQUENTIAL"):
        advance_prospective_session(
            s1,
            session_date=date(2026, 11, 5),
            session_evidence=ev_skip,
            artifact_store=store_skip,
            producer_verifier=make_producer_verifier(store_skip),
        )

    # Valid exact next step (Nov 4, 2026 is Wednesday)
    ev2, store2 = make_prospective_evidence(s1, 1, date(2026, 11, 4))
    s2 = advance_prospective_session(
        s1,
        session_date=date(2026, 11, 4),
        session_evidence=ev2,
        artifact_store=store2,
        producer_verifier=make_producer_verifier(store2),
    )
    assert s2.observed_session_count == 2
    assert s2.last_observed_session == date(2026, 11, 4)

    # Skipping sessions with explicit calendar
    cal = [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
    # Next scheduled in calendar is Nov 5, jumping to Nov 6 must be rejected
    ev_cal_skip, store_cal_skip = make_prospective_evidence(s2, 2, date(2026, 11, 6))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_SEQUENTIAL"):
        advance_prospective_session(
            s2,
            session_date=date(2026, 11, 6),
            session_evidence=ev_cal_skip,
            artifact_store=store_cal_skip,
            calendar=cal,
            producer_verifier=make_producer_verifier(store_cal_skip),
        )


def test_prospective_step_enforces_store_and_evidence_verification() -> None:
    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    reg = register_prospective_study(
        registration_id="REG-STORE-VERIFY",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )

    ev, store = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    pv = make_producer_verifier(store)

    # 1. Missing artifact store entirely
    with pytest.raises(ValueError, match="EXECUTION_EVIDENCE_STORE_REQUIRED"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev,
            artifact_store=None,
            producer_verifier=pv,
        )

    # 1b. Missing producer verifier entirely
    with pytest.raises(ValueError, match="PRODUCER_VERIFIER_REQUIRED"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev,
            artifact_store=store,
            producer_verifier=None,
        )

    # 2. Invented artifact hash not found in store
    ev_invented = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts={
            "portfolio_state": "f" * 64,
            "decision": "e" * 64,
            "fills": "d" * 64,
        },
    )
    with pytest.raises(ValueError, match="ARTIFACT_NOT_FOUND_IN_STORE"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_invented,
            artifact_store=store,
            producer_verifier=pv,
        )

    # 3. Missing required artifact (e.g. fills missing)
    ev_missing_req = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts={
            "portfolio_state": list(store.keys())[0],
            "decision": list(store.keys())[1],
        },
    )
    with pytest.raises(ValueError, match="MISSING_REQUIRED_ARTIFACT"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_missing_req,
            artifact_store=store,
            producer_verifier=pv,
        )

    # 4. Non-hex artifact hash in evidence dict
    ev_non_hex_dict = {
        "schema_version": "drift-stage1-prospective-session-evidence/1",
        "registration_id": reg.registration_id,
        "freeze_hash": reg.frozen_study.freeze_hash,
        "session_index": 0,
        "session_date": "2026-11-03",
        "status": "COMPLETED",
        "evidence_artifacts": {
            "portfolio_state": "z" * 64,
            "decision": list(store.keys())[1],
            "fills": list(store.keys())[2],
        },
        "evidence_hash": "a" * 64,
    }
    with pytest.raises((ValueError, ValidationError)):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_non_hex_dict,
            artifact_store=store,
            producer_verifier=pv,
        )

    # 5. Content hash mismatch in artifact store
    corrupted_store = dict(store)
    first_hash = list(store.keys())[0]
    corrupted_store[first_hash] = {"corrupted": True}
    with pytest.raises(ValueError, match="ARTIFACT_CONTENT_HASH_MISMATCH"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev,
            artifact_store=corrupted_store,
            producer_verifier=pv,
        )

    # 6. Session index mismatch inside artifact object
    mismatched_store = {}
    mismatched_hashes = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": 99,  # Mismatched session index!
            "session_date": "2026-11-03",
            "authority_id": "drift.stage1.trusted_authority",
            "execution_payload": {"status": "OK"},
        }
        h = content_hash(art_body)
        mismatched_store[h] = art_body
        mismatched_hashes[art_name] = h

    ev_mismatched = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts=mismatched_hashes,
    )
    with pytest.raises(ValueError, match="ARTIFACT_SESSION_INDEX_MISMATCH"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_mismatched,
            artifact_store=mismatched_store,
            producer_verifier=make_producer_verifier(mismatched_store),
        )

    # 7. Empty artifact {} stored under its hash (Sol's Round 11 finding)
    empty_h = content_hash({})
    empty_store: dict[str, Any] = {empty_h: {}}
    ev_empty = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts={
            "portfolio_state": empty_h,
            "decision": empty_h,
            "fills": empty_h,
        },
    )
    with pytest.raises(
        ValueError, match="EMPTY_OR_INVALID_ARTIFACT|ARTIFACT_ROLE_MISMATCH"
    ):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_empty,
            artifact_store=empty_store,
            producer_verifier=make_producer_verifier(empty_store),
        )

    # 8. Empty execution payload inside artifact
    empty_payload_store = {}
    empty_payload_hashes = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "drift.stage1.trusted_authority",
            "execution_payload": {},  # Empty payload!
        }
        h = content_hash(art_body)
        empty_payload_store[h] = art_body
        empty_payload_hashes[art_name] = h
    ev_empty_payload = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts=empty_payload_hashes,
    )
    with pytest.raises(ValueError, match="EMPTY_EXECUTION_PAYLOAD"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_empty_payload,
            artifact_store=empty_payload_store,
            producer_verifier=make_producer_verifier(empty_payload_store),
        )

    # 9. Wrong artifact role
    wrong_role_store = {}
    wrong_role_hashes = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": "decision",  # Wrong role for portfolio_state and fills!
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "drift.stage1.trusted_authority",
            "execution_payload": {"status": "OK"},
        }
        h = content_hash(art_body)
        wrong_role_store[h] = art_body
        wrong_role_hashes[art_name] = h
    ev_wrong_role = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts=wrong_role_hashes,
    )
    with pytest.raises(ValueError, match="ARTIFACT_ROLE_MISMATCH"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_wrong_role,
            artifact_store=wrong_role_store,
            producer_verifier=make_producer_verifier(wrong_role_store),
        )

    # 10. Untrusted artifact authority
    untrusted_store = {}
    untrusted_hashes = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        art_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": 0,
            "session_date": "2026-11-03",
            "authority_id": "untrusted-self-author",
            "execution_payload": {"status": "OK"},
        }
        h = content_hash(art_body)
        untrusted_store[h] = art_body
        untrusted_hashes[art_name] = h
    ev_untrusted = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts=untrusted_hashes,
    )
    with pytest.raises(ValueError, match="UNTRUSTED_ARTIFACT_AUTHORITY"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_untrusted,
            artifact_store=untrusted_store,
            producer_verifier=make_producer_verifier(untrusted_store),
        )


def test_adversarial_fabricated_artifact_with_trusted_authority_is_rejected() -> None:
    """Adversarial test: caller fabricates artifact with matching trusted authority name

    and valid content hash, but producer verification independently rejects it.
    """
    plan, evidence, verifier = make_prospective_plan()
    frozen = freeze_prospective_study(
        plan, frozen_at=NOW, evidence=evidence, verifier=verifier
    )
    reg = register_prospective_study(
        registration_id="REG-ADVERSARIAL",
        registered_at=NOW,
        frozen_study=frozen,
        has_broker_dispatch_capability=False,
    )

    # Legitimate authentic artifacts known to independent producer verifier
    _ev_auth, store_auth = make_prospective_evidence(reg, 0, date(2026, 11, 3))
    prod_verifier = ProductionProspectiveProducerVerifier(
        trust_roots={"drift.stage1.trusted_authority"},
        authenticated_artifact_hashes=set(store_auth.keys()),
    )

    # Adversary constructs a fabricated artifact:
    # 1. Sets trusted authority name "drift.stage1.trusted_authority"
    # 2. Sets matching registration_id, freeze_hash, session_index, session_date
    # 3. Supplies arbitrary non-empty execution payload
    # 4. Computes valid content hash and places into artifact_store
    fab_store: dict[str, Any] = {}
    fab_hashes: dict[str, str] = {}
    for art_name in ("portfolio_state", "decision", "fills"):
        fab_body = {
            "schema_version": "drift-stage1-prospective-artifact/1",
            "artifact_role": art_name,
            "registration_id": reg.registration_id,
            "freeze_hash": reg.frozen_study.freeze_hash,
            "session_index": 0,
            "session_date": "2026-11-03",
            # Correct trusted authority name
            "authority_id": "drift.stage1.trusted_authority",
            "execution_payload": {
                "fabricated_pnl": 999999,
                "status": "FABRICATED_EXECUTION",
            },
        }
        h = content_hash(fab_body)
        fab_store[h] = fab_body
        fab_hashes[art_name] = h

    ev_fab = create_prospective_session_evidence(
        registration_id=reg.registration_id,
        freeze_hash=reg.frozen_study.freeze_hash,
        session_index=0,
        session_date=date(2026, 11, 3),
        evidence_artifacts=fab_hashes,
    )

    # Must be rejected by producer verification!
    with pytest.raises(ValueError, match="PRODUCER_AUTHENTICATION_FAILED"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_fab,
            artifact_store=fab_store,
            producer_verifier=prod_verifier,
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
        ev, store = make_prospective_evidence(invalid_reg, 0, date(2026, 11, 3))
        with pytest.raises(ValueError, match="CANNOT_ADVANCE_FROM_LIFECYCLE_STATE"):
            advance_prospective_session(
                invalid_reg,
                session_date=date(2026, 11, 3),
                session_evidence=ev,
                artifact_store=store,
                producer_verifier=make_producer_verifier(store),
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
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            artifact_store={},
            producer_verifier=make_producer_verifier({}),
        )

    # Weekend rejection (Nov 7, 2026 is Saturday)
    ev_wknd, store_wknd = make_prospective_evidence(reg, 0, date(2026, 11, 7))
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_A_TRADING_DAY"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 7),
            session_evidence=ev_wknd,
            artifact_store=store_wknd,
            producer_verifier=make_producer_verifier(store_wknd),
        )

    # Calendar membership / sequential gap rejection
    cal = {date(2026, 11, 4), date(2026, 11, 5)}
    ev_not_in_cal, store_not_in_cal = make_prospective_evidence(
        reg, 0, date(2026, 11, 3)
    )
    with pytest.raises(ValueError, match="SESSION_DATE_NOT_SEQUENTIAL"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_not_in_cal,
            calendar=cal,
            artifact_store=store_not_in_cal,
            producer_verifier=make_producer_verifier(store_not_in_cal),
        )

    # Evidence index mismatch
    ev_wrong_idx, store_wrong_idx = make_prospective_evidence(reg, 5, date(2026, 11, 3))
    with pytest.raises(ValueError, match="SESSION_EVIDENCE_INDEX_MISMATCH"):
        advance_prospective_session(
            reg,
            session_date=date(2026, 11, 3),
            session_evidence=ev_wrong_idx,
            artifact_store=store_wrong_idx,
            producer_verifier=make_producer_verifier(store_wrong_idx),
        )
