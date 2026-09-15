"""Real-source snapshot building, cross-component consistency,
and closure verification.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid7

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import AcquisitionReceiptV1
from drift.domain.assertions import BoundaryShape
from drift.domain.common import UUID7, SHA256Hash, UTCDateTime
from drift.domain.dataset_validation import ValidationResult
from drift.domain.qualification import PilotProfileSetV1, qualification_profile_hash
from drift.domain.source_snapshots import (
    ConsistencyStatus,
    CoordinatedCutoffRuleV1,
    CrossComponentConsistencyDecisionV1,
    ExpectedOutputV1,
    ProviderReleaseEvidenceV1,
    RawReplayInputEntryV1,
    RealSourceSnapshotV1,
    ReplayInputEntryV1,
    ReplayInputKind,
    SourceComponentRole,
    cross_component_consistency_decision_hash,
    real_source_snapshot_hash,
)
from drift.markets.economic_validation import (
    EconomicResolutionContext,
    economic_context_hash,
    validate_economic_context,
)
from drift.markets.observation_validation import (
    M1dResolutionContext,
    m1d_context_hash,
    validate_m1d_resolution_context,
)
from drift.markets.universes import StructuralResolutionContext
from drift.qualification.rights import AcquisitionAuthorizationVerificationBundle
from drift.serialization.canonical import content_hash


@dataclass(frozen=True, slots=True)
class ExistingContractContexts:
    """Retained audit inputs across accepted M1b, M1c, and M1d contracts."""

    m1b_contexts: tuple[StructuralResolutionContext, ...]
    m1c_context: EconomicResolutionContext
    m1d_context: M1dResolutionContext


def _verify_structural_context(ctx: StructuralResolutionContext) -> None:
    """Verify that all M1b structural datasets carry passing decisions."""
    for name, dataset in (
        ("assignments", ctx.universe.assignments),
        ("memberships", ctx.universe.memberships),
        ("source_definitions", ctx.universe.source_definitions),
        ("relationships", ctx.relationships),
        ("classifications", ctx.classifications),
        ("roles", ctx.roles),
        ("lifecycle", ctx.lifecycle),
        ("terminations", ctx.terminations),
        ("coverage", ctx.coverage),
    ):
        if dataset.decision.result is not ValidationResult.PASS:
            raise ValueError(f"structural context {name} decision is not PASS")


def evaluate_cross_component_consistency(
    rule: CoordinatedCutoffRuleV1,
    release_evidence: tuple[ProviderReleaseEvidenceV1, ...],
    policy_hash: SHA256Hash,
    *,
    decision_id: UUID7 | None = None,
    decided_at: UTCDateTime | None = None,
) -> CrossComponentConsistencyDecisionV1:
    """Evaluate cross-component temporal overlap against a coordinated cutoff rule."""
    conflicts_and_gaps: list[str] = []
    has_unknown = False
    has_malformed = False

    if not rule.per_component_cutoff_rules or not release_evidence:
        conflicts_and_gaps.append("cutoff rules or release evidence is empty")
        status = ConsistencyStatus.FAIL
    else:
        by_role: dict[SourceComponentRole, list[ProviderReleaseEvidenceV1]] = {}
        for ev in release_evidence:
            by_role.setdefault(ev.component_role, []).append(ev)

        # 1. Check all required component roles in the rule are present
        for role, cutoff_str in rule.per_component_cutoff_rules.items():
            role_evidence = by_role.get(role)
            if not role_evidence:
                conflicts_and_gaps.append(
                    f"missing release evidence for component role {role}"
                )
                continue

            try:
                cutoff_dt = datetime.fromisoformat(cutoff_str)
                if cutoff_dt.tzinfo is None:
                    cutoff_dt = cutoff_dt.replace(tzinfo=UTC)
            except Exception:
                conflicts_and_gaps.append(
                    f"malformed cutoff timestamp for component role {role}: "
                    f"{cutoff_str}"
                )
                has_malformed = True
                cutoff_dt = None

            for item in role_evidence:
                tb = item.temporal_boundary
                if tb.shape is BoundaryShape.UNKNOWN or tb.lower_bound is None:
                    has_unknown = True
                    conflicts_and_gaps.append(
                        f"component role {role} release "
                        f"{item.provider_release_id} has unknown temporal boundary"
                    )
                elif cutoff_dt is not None:
                    item_instant = tb.upper_bound or tb.lower_bound
                    if item_instant.tzinfo is None:
                        item_instant = item_instant.replace(tzinfo=UTC)
                    if item_instant > cutoff_dt:
                        conflicts_and_gaps.append(
                            f"component role {role} release "
                            f"{item.provider_release_id} instant "
                            f"{item_instant.isoformat()} is after "
                            f"coordinated cutoff {cutoff_str}"
                        )

        # 2. Check that every role in release_evidence is declared in rule
        for role, ev_items in by_role.items():
            if role not in rule.per_component_cutoff_rules:
                conflicts_and_gaps.append(
                    f"release evidence contains undeclared component role {role}"
                )
                for item in ev_items:
                    tb = item.temporal_boundary
                    if tb.shape is BoundaryShape.UNKNOWN or tb.lower_bound is None:
                        has_unknown = True
                        conflicts_and_gaps.append(
                            f"undeclared component role {role} release "
                            f"{item.provider_release_id} has unknown temporal boundary"
                        )

        if has_malformed or any(
            "missing" in g or "undeclared" in g for g in conflicts_and_gaps
        ):
            status = ConsistencyStatus.FAIL
        elif has_unknown:
            status = ConsistencyStatus.UNKNOWN
        elif conflicts_and_gaps:
            status = ConsistencyStatus.PARTIAL
        else:
            status = ConsistencyStatus.PASS

    rule_hash = content_hash(rule)
    component_hashes = tuple(sorted({content_hash(item) for item in release_evidence}))
    now = decided_at or datetime.now(tz=UTC)
    did = decision_id or uuid7()

    decision = CrossComponentConsistencyDecisionV1.model_construct(
        component_release_hashes=component_hashes,
        coordinated_rule_hash=rule_hash,
        result=status,
        conflicts_and_gaps=tuple(conflicts_and_gaps),
        decision_policy_hash=policy_hash,
        decision_id=did,
        decided_at=now,
        decision_hash=content_hash("placeholder"),
    )
    computed_hash = cross_component_consistency_decision_hash(decision)
    return decision.model_copy(update={"decision_hash": computed_hash})


def build_real_source_snapshot(
    profiles: PilotProfileSetV1,
    authorization: AcquisitionAuthorizationVerificationBundle,
    receipts: tuple[AcquisitionReceiptV1, ...],
    consistency: CrossComponentConsistencyDecisionV1,
    replay_inputs: tuple[ReplayInputEntryV1, ...],
    expected_outputs: tuple[ExpectedOutputV1, ...],
    *,
    release_evidence: tuple[ProviderReleaseEvidenceV1, ...] = (),
    grading_artifact_hashes: tuple[SHA256Hash, ...] = (),
    cutoff_assertions: tuple[str, ...] = (),
    coverage_assertions: tuple[str, ...] = (),
    methodology_schema_hashes: tuple[SHA256Hash, ...] = (),
    adapter_semantic_hashes: tuple[SHA256Hash, ...] = (),
    adapter_source_hashes: tuple[SHA256Hash, ...] = (),
    existing_manifest_hashes: tuple[SHA256Hash, ...] = (),
    validation_decision_hashes: tuple[SHA256Hash, ...] = (),
    validation_bundle_hashes: tuple[SHA256Hash, ...] = (),
    m1a_policy_hashes: tuple[SHA256Hash, ...] = (),
    snapshot_id: UUID7 | None = None,
    created_at: UTCDateTime | None = None,
) -> RealSourceSnapshotV1:
    """Construct an immutable RealSourceSnapshotV1 with verified self-excluding hash."""
    profile_set_hash = content_hash(profiles)
    all_profile_hashes = tuple(
        sorted({qualification_profile_hash(p) for p in profiles.profiles})
    )
    authorized_profile_hashes = tuple(
        sorted(set(authorization.approval.approved_profile_hashes))
    )
    rights_hashes = tuple(sorted({content_hash(a) for a in authorization.assessments}))
    receipt_hashes = tuple(sorted({content_hash(r) for r in receipts}))
    native_hashes = tuple(
        sorted(
            {
                inp.content_hash
                for inp in replay_inputs
                if inp.kind == ReplayInputKind.NATIVE_ARTIFACT
            }
        )
    )
    all_grading_hashes = tuple(
        sorted(
            set(grading_artifact_hashes)
            | {
                inp.content_hash
                for inp in replay_inputs
                if inp.kind == ReplayInputKind.GRADING_EVIDENCE
            }
        )
    )

    unhashed = RealSourceSnapshotV1.model_construct(
        snapshot_id=snapshot_id or uuid7(),
        snapshot_version="1",
        created_at=created_at or datetime.now(tz=UTC),
        profile_set_hash=profile_set_hash,
        profile_hashes=all_profile_hashes,
        authorized_profile_hashes=authorized_profile_hashes,
        rights_assessment_hashes=rights_hashes,
        receipt_hashes=receipt_hashes,
        native_artifact_hashes=native_hashes,
        grading_artifact_hashes=all_grading_hashes,
        release_evidence=release_evidence,
        consistency_decision=consistency,
        cutoff_assertions=tuple(sorted(set(cutoff_assertions))),
        coverage_assertions=tuple(sorted(set(coverage_assertions))),
        methodology_schema_hashes=tuple(sorted(set(methodology_schema_hashes))),
        adapter_semantic_hashes=tuple(sorted(set(adapter_semantic_hashes))),
        adapter_source_hashes=tuple(sorted(set(adapter_source_hashes))),
        existing_manifest_hashes=tuple(sorted(set(existing_manifest_hashes))),
        validation_decision_hashes=tuple(sorted(set(validation_decision_hashes))),
        validation_bundle_hashes=tuple(sorted(set(validation_bundle_hashes))),
        m1a_policy_hashes=tuple(sorted(set(m1a_policy_hashes))),
        replay_inputs=replay_inputs,
        expected_outputs=expected_outputs,
        snapshot_hash=content_hash("placeholder"),
    )

    computed = real_source_snapshot_hash(unhashed)
    return unhashed.model_copy(update={"snapshot_hash": computed})


def verify_real_source_snapshot(
    snapshot: RealSourceSnapshotV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
    contexts: ExistingContractContexts,
) -> None:
    """Verify real-source snapshot self-consistency, replay closure,
    and context validity.
    """
    # 1. Self-excluding hash verification
    expected_hash = real_source_snapshot_hash(snapshot)
    if snapshot.snapshot_hash != expected_hash:
        msg = (
            f"snapshot hash mismatch: declared {snapshot.snapshot_hash} "
            f"!= {expected_hash}"
        )
        raise ValueError(msg)

    # 2. Consistency decision check
    if snapshot.consistency_decision.result is not ConsistencyStatus.PASS:
        msg = (
            "snapshot consistency decision is not PASS: "
            f"{snapshot.consistency_decision.result}"
        )
        raise ValueError(msg)

    expected_decision_hash = cross_component_consistency_decision_hash(
        snapshot.consistency_decision
    )
    if snapshot.consistency_decision.decision_hash != expected_decision_hash:
        raise ValueError(
            f"consistency decision hash mismatch: declared "
            f"{snapshot.consistency_decision.decision_hash} != {expected_decision_hash}"
        )

    expected_release_hashes = tuple(
        sorted({content_hash(item) for item in snapshot.release_evidence})
    )
    if (
        snapshot.consistency_decision.component_release_hashes
        != expected_release_hashes
    ):
        raise ValueError(
            "consistency decision component release hashes do not match "
            "snapshot release evidence"
        )

    for ev in snapshot.release_evidence:
        tb = ev.temporal_boundary
        if tb.shape is BoundaryShape.UNKNOWN or tb.lower_bound is None:
            raise ValueError(
                f"release evidence {ev.provider_release_id} has unknown "
                "temporal boundary, cannot satisfy PASS consistency decision"
            )

    # 3. Closed-world replay inputs closure over all required categories
    present_kinds = {entry.kind for entry in snapshot.replay_inputs}
    missing_kinds = set(ReplayInputKind) - present_kinds
    if missing_kinds:
        missing_names = sorted([k.value for k in missing_kinds])
        raise ValueError(
            f"incomplete replay input closure: missing categories {missing_names}"
        )

    # 4. Byte verification for all replay inputs
    for entry in snapshot.replay_inputs:
        chash = entry.content_hash
        if chash not in artifacts:
            raise ValueError(f"missing required artifact bytes for hash: {chash}")
        vart = artifacts[chash]
        if vart.content_hash != chash:
            raise ValueError(
                f"artifact content hash {vart.content_hash} does not match {chash}"
            )
        actual_hash = sha256(vart.data).hexdigest()
        if actual_hash != chash:
            msg = (
                f"artifact byte hash mismatch for {chash}: "
                f"actual payload hash is {actual_hash}"
            )
            raise ValueError(msg)
        if len(vart.data) != vart.byte_size:
            msg = (
                f"artifact byte length mismatch for {chash}: "
                f"{len(vart.data)} != {vart.byte_size}"
            )
            raise ValueError(msg)

        # 5. Canonical model JSON validation
        if entry.discriminator == "canonical_model":
            try:
                json.loads(vart.data)
            except Exception as err:
                raise ValueError(
                    f"canonical replay input {entry.kind} ({chash}) is not "
                    f"valid JSON: {err}"
                ) from err

    # 6. Public verification of existing contract contexts
    if not isinstance(contexts.m1c_context, EconomicResolutionContext):
        raise ValueError(
            "m1c_context must be EconomicResolutionContext, "
            f"got {type(contexts.m1c_context)}"
        )
    try:
        validate_economic_context(contexts.m1c_context)
    except Exception as err:
        raise ValueError(f"m1c economic context validation failed: {err}") from err

    if not isinstance(contexts.m1d_context, M1dResolutionContext):
        raise ValueError(
            "m1d_context must be M1dResolutionContext, "
            f"got {type(contexts.m1d_context)}"
        )
    try:
        validate_m1d_resolution_context(contexts.m1d_context)
    except Exception as err:
        raise ValueError(f"m1d resolution context validation failed: {err}") from err

    for idx, m1b_ctx in enumerate(contexts.m1b_contexts):
        if not isinstance(m1b_ctx, StructuralResolutionContext):
            raise ValueError(
                f"m1b_contexts[{idx}] must be StructuralResolutionContext, "
                f"got {type(m1b_ctx)}"
            )
        _verify_structural_context(m1b_ctx)

    # 7. Context binding verification to replay inputs
    m1c_ctx_hash = economic_context_hash(contexts.m1c_context)
    m1d_ctx_hash = m1d_context_hash(contexts.m1d_context)

    for entry in snapshot.replay_inputs:
        if isinstance(entry, RawReplayInputEntryV1):
            continue
        if entry.kind == ReplayInputKind.M1C_QUERY_POLICY_CONTEXT_RESULT:
            if (
                entry.original_identity != m1c_ctx_hash
                and entry.content_hash != m1c_ctx_hash
            ):
                raise ValueError(
                    "m1c context hash mismatch: replay entry identity "
                    f"{entry.original_identity} does not match context hash "
                    f"{m1c_ctx_hash}"
                )
        elif entry.kind == ReplayInputKind.M1D_QUERY_POLICY_CONTEXT_RESULT:
            if (
                entry.original_identity != m1d_ctx_hash
                and entry.content_hash != m1d_ctx_hash
            ):
                raise ValueError(
                    "m1d context hash mismatch: replay entry identity "
                    f"{entry.original_identity} does not match context hash "
                    f"{m1d_ctx_hash}"
                )
