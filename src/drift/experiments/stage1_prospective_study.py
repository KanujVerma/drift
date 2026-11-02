"""Stage 1 prospective study contracts, readiness assessment, and orchestration.

Implements broker-free prospective system:
- Strict lifecycle: DRAFT -> REGISTERED -> READY -> RUNNING
  -> COMPLETED_PENDING_REVIEW -> ACCEPTED
- Blocked on broker dispatch capability (strictly refused).
- 504 scheduled sessions, one final efficacy look, durable step resumption.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from drift.domain.common import FrozenModel, NonBlankStr, SHA256Hash, UTCDateTime
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    EvidenceRole,
    OriginalStudyEvidenceVerifier,
    StudyEvidenceReferenceV1,
)
from drift.serialization.canonical import canonical_json, content_hash

ProspectiveLifecycle = Literal[
    "DRAFT",
    "REGISTERED",
    "READY",
    "RUNNING",
    "COMPLETED_PENDING_REVIEW",
    "ACCEPTED",
    "BLOCKED",
    "PAUSED",
    "SAFETY_TERMINATED",
    "INVALID",
]


class ProspectiveStudyPlanV1(FrozenModel):
    schema_version: Literal["drift-stage1-prospective-plan/1"] = (
        "drift-stage1-prospective-plan/1"
    )
    plan_id: NonBlankStr
    created_at: UTCDateTime
    registered_at: UTCDateTime | None = None
    scheduled_sessions: Literal[504] = 504
    calendar_identity: NonBlankStr
    first_eligible_session: date
    planned_last_session: date
    initial_family: Literal["B3"] = "B3"
    initial_capital: Literal["10000"] = "10000"
    currency: Literal["USD"] = "USD"
    reference_lineage: Literal["THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"] = (
        "THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"
    )
    missing_session_policy: Literal["RETAIN_PREVIOUS_MARK_NO_FUTURE_EXTENSION"] = (
        "RETAIN_PREVIOUS_MARK_NO_FUTURE_EXTENSION"
    )
    one_final_efficacy_look: Literal[True] = True
    safety_termination: Literal["ALLOWED_WITH_ORIGINAL_REASON_AND_CARRY_FORWARD"] = (
        "ALLOWED_WITH_ORIGINAL_REASON_AND_CARRY_FORWARD"
    )
    operating_environment_hash: SHA256Hash
    model_binding_hash: SHA256Hash
    market_admission_hash: SHA256Hash
    mandate_hash: SHA256Hash
    cost_policy_hash: SHA256Hash
    evidence_receipts: tuple[StudyEvidenceReferenceV1, ...] = ()
    plan_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.first_eligible_session > self.planned_last_session:
            raise ValueError("PROSPECTIVE_DATES_REVERSED")
        body = self.model_dump(mode="python", exclude={"plan_hash"})
        if self.plan_hash != content_hash(body):
            raise ValueError("PROSPECTIVE_PLAN_HASH_MISMATCH")
        return self


def create_prospective_study_plan(
    *,
    plan_id: str,
    created_at: datetime,
    calendar_identity: str,
    first_eligible_session: date,
    planned_last_session: date,
    operating_environment_hash: str,
    model_binding_hash: str,
    market_admission_hash: str,
    mandate_hash: str,
    cost_policy_hash: str,
    evidence_receipts: tuple[StudyEvidenceReferenceV1, ...] = (),
    registered_at: datetime | None = None,
) -> ProspectiveStudyPlanV1:
    body = {
        "schema_version": "drift-stage1-prospective-plan/1",
        "plan_id": plan_id,
        "created_at": created_at,
        "registered_at": registered_at,
        "scheduled_sessions": 504,
        "calendar_identity": calendar_identity,
        "first_eligible_session": first_eligible_session,
        "planned_last_session": planned_last_session,
        "initial_family": "B3",
        "initial_capital": "10000",
        "currency": "USD",
        "reference_lineage": ("THREE_DISTINCT_ORIGINAL_FIXED_B3_B4_B5_CONTINUOUS"),
        "missing_session_policy": "RETAIN_PREVIOUS_MARK_NO_FUTURE_EXTENSION",
        "one_final_efficacy_look": True,
        "safety_termination": "ALLOWED_WITH_ORIGINAL_REASON_AND_CARRY_FORWARD",
        "operating_environment_hash": operating_environment_hash,
        "model_binding_hash": model_binding_hash,
        "market_admission_hash": market_admission_hash,
        "mandate_hash": mandate_hash,
        "cost_policy_hash": cost_policy_hash,
        "evidence_receipts": evidence_receipts,
    }
    h = content_hash(body)
    return ProspectiveStudyPlanV1.model_validate_json(
        canonical_json(body | {"plan_hash": h})
    )


class ProspectiveReadinessV1(FrozenModel):
    plan_hash: SHA256Hash
    status: Literal["BLOCKED", "READY_FOR_PROSPECTIVE_REGISTRATION"]
    blockers: tuple[str, ...]
    verified_roles: tuple[EvidenceRole, ...]


def assess_prospective_readiness(
    plan: ProspectiveStudyPlanV1,
    *,
    evidence: tuple[StudyEvidenceReferenceV1, ...] = (),
    verifier: OriginalStudyEvidenceVerifier | None = None,
    as_of: datetime | None = None,
) -> ProspectiveReadinessV1:
    plan = ProspectiveStudyPlanV1.model_validate_json(canonical_json(plan))
    cutoff = plan.created_at if as_of is None else as_of
    blockers: set[str] = set()

    verified: list[EvidenceRole] = []
    for role in REQUIRED_ROLES:
        matches = [ref for ref in evidence if ref.role == role]
        if len(matches) != 1:
            blockers.add(f"MISSING_OR_DUPLICATE_PROSPECTIVE_EVIDENCE:{role}")
            continue
        ref = matches[0]
        if ref.protocol_hash != plan.plan_hash:
            blockers.add(f"PROSPECTIVE_EVIDENCE_FOR_DIFFERENT_PLAN:{role}")
            continue
        if ref.accepted_at > cutoff:
            blockers.add(f"PROSPECTIVE_ACCEPTANCE_NOT_YET_AVAILABLE:{role}")
            continue
        if verifier is None:
            blockers.add(f"PROSPECTIVE_VERIFIER_UNAVAILABLE:{role}")
            continue
        try:
            if not verifier.verify(ref):
                blockers.add(f"PROSPECTIVE_EVIDENCE_NOT_ACCEPTED:{role}")
                continue
        except Exception:
            blockers.add(f"PROSPECTIVE_VERIFIER_FAILED:{role}")
            continue
        verified.append(role)

    status: Literal["BLOCKED", "READY_FOR_PROSPECTIVE_REGISTRATION"] = (
        "BLOCKED" if blockers else "READY_FOR_PROSPECTIVE_REGISTRATION"
    )

    return ProspectiveReadinessV1(
        plan_hash=plan.plan_hash,
        status=status,
        blockers=tuple(sorted(blockers)),
        verified_roles=tuple(verified),
    )


class FrozenProspectiveStudyV1(FrozenModel):
    schema_version: Literal["drift-stage1-prospective-freeze/1"] = (
        "drift-stage1-prospective-freeze/1"
    )
    plan: ProspectiveStudyPlanV1
    frozen_at: UTCDateTime
    evidence: tuple[StudyEvidenceReferenceV1, ...]
    freeze_hash: SHA256Hash

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        body = self.model_dump(mode="python", exclude={"freeze_hash"})
        if self.freeze_hash != content_hash(body):
            raise ValueError("PROSPECTIVE_FREEZE_HASH_MISMATCH")
        return self


def freeze_prospective_study(
    plan: ProspectiveStudyPlanV1,
    *,
    frozen_at: datetime,
    evidence: tuple[StudyEvidenceReferenceV1, ...],
    verifier: OriginalStudyEvidenceVerifier,
) -> FrozenProspectiveStudyV1:
    readiness = assess_prospective_readiness(
        plan, evidence=evidence, verifier=verifier, as_of=frozen_at
    )
    if readiness.status == "BLOCKED":
        raise ValueError("PROSPECTIVE_FREEZE_BLOCKED:" + ";".join(readiness.blockers))

    body = {
        "schema_version": "drift-stage1-prospective-freeze/1",
        "plan": plan,
        "frozen_at": frozen_at,
        "evidence": evidence,
    }
    h = content_hash(body)
    return FrozenProspectiveStudyV1.model_validate_json(
        canonical_json(body | {"freeze_hash": h})
    )


def verify_frozen_prospective_study(
    frozen: FrozenProspectiveStudyV1,
    *,
    verifier: OriginalStudyEvidenceVerifier,
) -> ProspectiveReadinessV1:
    return assess_prospective_readiness(
        frozen.plan,
        evidence=frozen.evidence,
        verifier=verifier,
        as_of=frozen.frozen_at,
    )


class ProspectiveRegistrationV1(FrozenModel):
    schema_version: Literal["drift-stage1-prospective-registration/1"] = (
        "drift-stage1-prospective-registration/1"
    )
    registration_id: NonBlankStr
    registered_at: UTCDateTime
    frozen_study: FrozenProspectiveStudyV1
    operational_state: ProspectiveLifecycle = "REGISTERED"
    observed_session_count: int = Field(ge=0, default=0)
    scheduled_sessions: Literal[504] = 504
    has_broker_dispatch_capability: bool = False
    registration_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_registration(self) -> Self:
        if self.has_broker_dispatch_capability:
            raise ValueError("BROKER_DISPATCH_CAPABILITY_FORBIDDEN")
        body = self.model_dump(mode="python", exclude={"registration_hash"})
        if self.registration_hash != content_hash(body):
            raise ValueError("REGISTRATION_HASH_MISMATCH")
        return self


def register_prospective_study(
    *,
    registration_id: str,
    registered_at: datetime,
    frozen_study: FrozenProspectiveStudyV1,
    has_broker_dispatch_capability: bool = False,
) -> ProspectiveRegistrationV1:
    body = {
        "schema_version": "drift-stage1-prospective-registration/1",
        "registration_id": registration_id,
        "registered_at": registered_at,
        "frozen_study": frozen_study,
        "operational_state": "REGISTERED",
        "observed_session_count": 0,
        "scheduled_sessions": 504,
        "has_broker_dispatch_capability": has_broker_dispatch_capability,
    }
    h = content_hash(body)
    return ProspectiveRegistrationV1.model_validate_json(
        canonical_json(body | {"registration_hash": h})
    )


def advance_prospective_session(
    registration: ProspectiveRegistrationV1,
    *,
    session_date: date,
) -> ProspectiveRegistrationV1:
    """Durably advances prospective observation by one session."""
    if registration.has_broker_dispatch_capability:
        raise ValueError("BROKER_DISPATCH_FORBIDDEN")

    new_count = registration.observed_session_count + 1
    new_state: ProspectiveLifecycle = (
        "COMPLETED_PENDING_REVIEW" if new_count >= 504 else "RUNNING"
    )

    body = {
        "schema_version": "drift-stage1-prospective-registration/1",
        "registration_id": registration.registration_id,
        "registered_at": registration.registered_at,
        "frozen_study": registration.frozen_study,
        "operational_state": new_state,
        "observed_session_count": new_count,
        "scheduled_sessions": 504,
        "has_broker_dispatch_capability": False,
    }
    h = content_hash(body)
    return ProspectiveRegistrationV1.model_validate_json(
        canonical_json(body | {"registration_hash": h})
    )
