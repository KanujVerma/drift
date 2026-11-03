"""Stage 1 G3 multi-role evidence admission and freeze pipeline.

Workstream G, Issue 575.
Executes the locked G3 admission and immutable freeze procedure:
1. Validates each exact original study input (mandate, comparator, model, costs,
   statistics, dates).
2. Verifies all 8 required multi-role acceptance receipts (no impersonation,
   no self-appointment).
3. Executes assess_study_readiness, preserving explicit blockers if not ready.
4. If ready, executes freeze_study with deterministic hash.
5. Performs cold-read deserialization in an independent verification step.
6. Verifies frozen study hash and readiness report match.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import Field

from drift.domain.common import FrozenModel, SHA256Hash
from drift.experiments.stage1_original_acceptance import (
    ProductionStudyEvidenceVerifier,
    create_original_study_evidence_receipt,
)
from drift.experiments.stage1_study_freeze import (
    REQUIRED_ROLES,
    ConventionalSelectorPolicyV1,
    EvidenceRole,
    FrozenStage1StudyV1,
    Stage1StudyDraftV1,
    StudyCostPolicyV1,
    StudyDateWindowV1,
    StudyEvidenceReferenceV1,
    StudyMandateV1,
    StudyModelPolicyV1,
    StudyReadinessV1,
    StudyStatisticalPolicyV1,
    assess_study_readiness,
    freeze_study,
    verify_frozen_study,
)
from drift.serialization.canonical import canonical_json


class G3FreezePipelineResultV1(FrozenModel):
    """Result of executing the G3 admission and freeze pipeline."""

    schema_version: Literal["drift-stage1-g3-freeze-result/1"] = (
        "drift-stage1-g3-freeze-result/1"
    )
    status: Literal[
        "READY_FOR_HISTORICAL_DISCOVERY", "READY_FOR_CONFIRMATORY_SCORING", "BLOCKED"
    ]
    protocol_hash: SHA256Hash
    freeze_hash: SHA256Hash | None = None
    readiness: StudyReadinessV1
    cold_read_readiness: StudyReadinessV1 | None = None
    frozen_study: FrozenStage1StudyV1 | None = None
    blockers: tuple[str, ...] = Field(default_factory=tuple)


def assemble_stage1_study_draft(
    *,
    study_id: str,
    created_at: datetime,
    mode: Literal[
        "RETROSPECTIVE_DISCOVERY", "CONFIRMATORY_HISTORICAL"
    ] = "CONFIRMATORY_HISTORICAL",
    prior_holdout_exposure: Literal[
        "UNKNOWN", "EXPOSED", "AUDITED_UNEXPOSED"
    ] = "AUDITED_UNEXPOSED",
    installed_source_hash: str,
    dataset_manifest_hash: str,
    calendar_and_universe_hash: str,
    decision_cutoff_policy_hash: str,
    seed_and_replication_policy_hash: str,
    mandate: StudyMandateV1,
    comparator: ConventionalSelectorPolicyV1,
    model: StudyModelPolicyV1,
    costs: StudyCostPolicyV1,
    statistics: StudyStatisticalPolicyV1,
    development_start: date = date(2023, 7, 3),
    development_end: date = date(2023, 12, 29),
    validation_start: date = date(2024, 1, 2),
    validation_end: date = date(2024, 12, 31),
    scoring_start: date = date(2025, 1, 2),
    scoring_end: date = date(2025, 12, 31),
) -> Stage1StudyDraftV1:
    """Assembles and validates a complete Stage1StudyDraftV1 from verified inputs."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return Stage1StudyDraftV1(
        study_id=study_id,
        created_at=created_at,
        mode=mode,
        prior_holdout_exposure=prior_holdout_exposure,
        development=StudyDateWindowV1(start=development_start, end=development_end),
        validation=StudyDateWindowV1(start=validation_start, end=validation_end),
        scoring=StudyDateWindowV1(start=scoring_start, end=scoring_end),
        installed_source_hash=installed_source_hash,
        dataset_manifest_hash=dataset_manifest_hash,
        calendar_and_universe_hash=calendar_and_universe_hash,
        decision_cutoff_policy_hash=decision_cutoff_policy_hash,
        seed_and_replication_policy_hash=seed_and_replication_policy_hash,
        mandate=mandate,
        comparator=comparator,
        model=model,
        costs=costs,
        statistics=statistics,
    )


def create_multi_role_evidence_receipts(
    *,
    protocol_hash: str,
    accepted_at: datetime,
    authorities: Mapping[EvidenceRole, str],
    hmac_keys: Mapping[str, str | bytes] | None = None,
    status: str = "ACCEPTED",
    assessor_independence: bool = True,
) -> tuple[
    tuple[StudyEvidenceReferenceV1, ...],
    dict[str, Any],
    dict[EvidenceRole, set[str]],
    dict[str, Any],
]:
    """Creates signed acceptance receipts for all 8 required roles.

    Returns:
        (evidence_references, receipt_store, trust_roots, authenticated_issuers)
    """
    if accepted_at.tzinfo is None:
        accepted_at = accepted_at.replace(tzinfo=UTC)

    keys = hmac_keys or {}
    evidence_refs: list[StudyEvidenceReferenceV1] = []
    receipt_store: dict[str, Any] = {}
    trust_roots: dict[EvidenceRole, set[str]] = {}
    auth_issuers: dict[str, Any] = {}

    for role in REQUIRED_ROLES:
        auth_id = authorities[role]
        trust_roots[role] = {auth_id}
        key = keys.get(auth_id)
        receipt_id = f"RCPT-G3-{role.upper().replace('_', '-')}-01"

        payload, r_hash = create_original_study_evidence_receipt(
            role=role,
            receipt_id=receipt_id,
            protocol_hash=protocol_hash,
            authority_id=auth_id,
            accepted_at=accepted_at,
            status=status,
            assessor_independence=assessor_independence,
            hmac_key=key,
        )
        receipt_store[receipt_id] = payload
        if key is not None:
            auth_issuers[auth_id] = {"hmac_key": key}

        evidence_refs.append(
            StudyEvidenceReferenceV1(
                role=role,
                receipt_id=receipt_id,
                receipt_hash=r_hash,
                protocol_hash=protocol_hash,
                accepted_at=accepted_at,
            )
        )

    return tuple(evidence_refs), receipt_store, trust_roots, auth_issuers


def execute_g3_admission_and_freeze(
    draft: Stage1StudyDraftV1,
    *,
    evidence: tuple[StudyEvidenceReferenceV1, ...],
    trust_roots: Mapping[EvidenceRole, set[str] | Mapping[str, Any]],
    receipt_store: Mapping[str, Any],
    authenticated_issuers: Mapping[str, Any] | None = None,
    authenticated_receipt_hashes: set[str] | None = None,
    frozen_at: datetime | None = None,
) -> G3FreezePipelineResultV1:
    """Executes the full G3 multi-role admission, assessment, and freeze procedure.

    Performs cold-read validation in an independent deserialization step to ensure
    byte-for-byte reproducibility and tamper resistance.
    """
    freeze_time = frozen_at or datetime.now(UTC)
    if freeze_time.tzinfo is None:
        freeze_time = freeze_time.replace(tzinfo=UTC)

    verifier = ProductionStudyEvidenceVerifier(
        trust_roots=trust_roots,
        receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        authenticated_issuers=authenticated_issuers,
        authenticated_receipt_hashes=authenticated_receipt_hashes,
    )

    readiness = assess_study_readiness(
        draft,
        evidence=evidence,
        verifier=verifier,
        as_of=freeze_time,
    )

    if readiness.status == "BLOCKED":
        return G3FreezePipelineResultV1(
            status="BLOCKED",
            protocol_hash=draft.protocol_hash,
            readiness=readiness,
            blockers=readiness.blockers,
        )

    # Genuinely ready: freeze study
    frozen = freeze_study(
        draft,
        frozen_at=freeze_time,
        evidence=evidence,
        verifier=verifier,
    )

    # Cold read: serialize and re-validate in fresh verifier instance
    serialized = canonical_json(frozen)
    cold_read = FrozenStage1StudyV1.model_validate_json(serialized)

    cold_verifier = ProductionStudyEvidenceVerifier(
        trust_roots=trust_roots,
        receipt_resolver=lambda rid: receipt_store.get(rid, {}),
        authenticated_issuers=authenticated_issuers,
        authenticated_receipt_hashes=authenticated_receipt_hashes,
    )
    cold_read_readiness = verify_frozen_study(cold_read, verifier=cold_verifier)

    if cold_read_readiness.status == "BLOCKED":
        return G3FreezePipelineResultV1(
            status="BLOCKED",
            protocol_hash=draft.protocol_hash,
            readiness=readiness,
            cold_read_readiness=cold_read_readiness,
            blockers=cold_read_readiness.blockers,
        )

    return G3FreezePipelineResultV1(
        status=readiness.status,
        protocol_hash=draft.protocol_hash,
        freeze_hash=frozen.freeze_hash,
        readiness=readiness,
        cold_read_readiness=cold_read_readiness,
        frozen_study=frozen,
        blockers=(),
    )
