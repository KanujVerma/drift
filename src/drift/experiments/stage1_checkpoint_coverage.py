"""Immutable synthetic checkpoint submission coverage, not study completeness."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_experiment_configuration,
)
from drift.experiments.stage1_trial_provenance import (
    Stage1TrialProvenanceSnapshotV1,
    verify_stage1_trial_provenance_snapshot,
)
from drift.serialization.canonical import content_hash

COVERAGE_SCHEMA_VERSION = "drift-stage1-coverage/1-draft"
CHECKPOINT_MANIFEST_SCHEMA_VERSION = "drift-stage1-checkpoint-manifest/1-draft"
COVERAGE_STATES = frozenset({"MISSING_SNAPSHOT", "UNOBSERVED", "EVENTS_RECORDED"})
PAIR_STATES = frozenset(
    {"BOTH_SUBMITTED", "TEST_MISSING", "COMPARATOR_MISSING", "BOTH_MISSING"}
)

_E1_MANIFEST_SCHEMA_VERSION = "drift-trial-manifest/1-draft"
_SCOPE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class Stage1RunCheckpointDeclarationV1:
    run_id: str
    checkpoint_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage1CoverageSlotV1:
    run_id: str
    checkpoint_id: str
    arm_id: str
    trial_id: str
    coverage_state: str
    provenance_snapshot: Stage1TrialProvenanceSnapshotV1 | None


@dataclass(frozen=True, slots=True)
class Stage1PairCoverageV1:
    run_id: str
    checkpoint_id: str
    test_arm_id: str
    comparator_arm_id: str
    pair_state: str


@dataclass(frozen=True, slots=True)
class Stage1CoverageCountsV1:
    declared_slots: int
    missing_snapshots: int
    unobserved_snapshots: int
    events_recorded_snapshots: int
    submitted_snapshots: int
    declared_pairs: int
    both_submitted_pairs: int


@dataclass(frozen=True, slots=True)
class Stage1CheckpointCoverageAuditV1:
    schema_version: str
    campaign_id: str
    campaign_spec_fingerprint: str
    complete_manifest_fingerprint: str
    checkpoint_manifest_fingerprint: str
    checkpoint_declarations: tuple[Stage1RunCheckpointDeclarationV1, ...]
    slots: tuple[Stage1CoverageSlotV1, ...]
    pairs: tuple[Stage1PairCoverageV1, ...]
    counts: Stage1CoverageCountsV1
    audit_fingerprint: str


def _require_token(value: object, label: str) -> None:
    if type(value) is not str or _SCOPE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}: {value!r}")


def _require_sha(value: object, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"invalid {label}: expected lowercase SHA-256")


def _require_sequence(value: object, label: str) -> None:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview, Mapping)
    ):
        raise ValueError(f"{label} must be a non-string sequence")


def _full_manifest_fingerprint(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> str:
    """Reconstruct the accepted E1 manifest preimage, without private imports."""
    records = [
        {
            "schema_version": b.schema_version,
            "binding_id": b.binding_id,
            "campaign_id": b.campaign_id,
            "run_id": b.run_id,
            "arm_id": b.arm_id,
            "portfolio_account_id": b.portfolio_account_id,
            "initial_cash_allocated": b.initial_cash_allocated,
            "bound_at": b.bound_at,
        }
        for b in sorted(
            bindings, key=lambda item: (item.campaign_id, item.run_id, item.arm_id)
        )
    ]
    return content_hash(
        {
            "schema_version": _E1_MANIFEST_SCHEMA_VERSION,
            "campaign_spec_fingerprint": campaign.campaign_spec_fingerprint,
            "expected_run_ids": sorted(expected_run_ids),
            "arm_spec_references": sorted(a.arm_spec_fingerprint for a in arms),
            "run_account_bindings": records,
        }
    )


def _checked_declarations(
    declarations: Sequence[Stage1RunCheckpointDeclarationV1],
    expected_run_ids: Sequence[str],
    *,
    require_sorted: bool,
) -> tuple[Stage1RunCheckpointDeclarationV1, ...]:
    _require_sequence(declarations, "checkpoint_declarations")
    seen: set[str] = set()
    detached: list[Stage1RunCheckpointDeclarationV1] = []

    for index, declaration in enumerate(declarations):
        if type(declaration) is not Stage1RunCheckpointDeclarationV1:
            raise ValueError(f"checkpoint_declarations[{index}] has invalid type")
        _require_token(declaration.run_id, "declaration.run_id")
        if declaration.run_id in seen:
            raise ValueError(f"duplicate checkpoint declaration: {declaration.run_id}")
        seen.add(declaration.run_id)
        if (
            type(declaration.checkpoint_ids) is not tuple
            or not declaration.checkpoint_ids
        ):
            raise ValueError("checkpoint_ids must be a nonempty immutable tuple")
        checkpoints: set[str] = set()
        for checkpoint in declaration.checkpoint_ids:
            _require_token(checkpoint, "checkpoint_id")
            if checkpoint in checkpoints:
                raise ValueError(f"duplicate checkpoint_id: {checkpoint}")
            checkpoints.add(checkpoint)

        # Reconstruct an independent frozen value, not the caller's object.
        copy = replace(declaration, checkpoint_ids=tuple(declaration.checkpoint_ids))
        if type(copy) is not Stage1RunCheckpointDeclarationV1:
            raise ValueError("invalid copied checkpoint declaration")
        detached.append(copy)

    if seen != set(expected_run_ids) or len(detached) != len(expected_run_ids):
        raise ValueError("checkpoint declarations must cover exactly all E1 runs")
    canonical = tuple(sorted(detached, key=lambda declaration: declaration.run_id))
    if require_sorted and tuple(declarations) != canonical:
        # Do not silently sort or repair an already persisted audit.
        raise ValueError(
            "stored checkpoint declarations are not in canonical run order"
        )
    return canonical


def _checkpoint_manifest_fingerprint(
    *,
    campaign: CampaignSpecV1,
    complete_manifest_fingerprint: str,
    declarations: tuple[Stage1RunCheckpointDeclarationV1, ...],
) -> str:
    return content_hash(
        {
            "schema_version": CHECKPOINT_MANIFEST_SCHEMA_VERSION,
            "campaign_id": campaign.campaign_id,
            "campaign_spec_fingerprint": campaign.campaign_spec_fingerprint,
            "complete_manifest_fingerprint": complete_manifest_fingerprint,
            "runs": [
                {
                    "run_id": declaration.run_id,
                    "checkpoint_ids": list(declaration.checkpoint_ids),
                }
                for declaration in declarations
            ],
        }
    )


def _detach_snapshot(
    snapshot: Stage1TrialProvenanceSnapshotV1,
) -> Stage1TrialProvenanceSnapshotV1:
    copied_scope = replace(
        snapshot.scope,
        run_account_binding=replace(snapshot.scope.run_account_binding),
    )
    copied_events = tuple(replace(event) for event in snapshot.event_envelopes)
    return replace(snapshot, scope=copied_scope, event_envelopes=copied_events)


def _audit_preimage(audit: Stage1CheckpointCoverageAuditV1) -> dict[str, object]:
    counts = audit.counts
    return {
        "schema_version": audit.schema_version,
        "campaign_id": audit.campaign_id,
        "campaign_spec_fingerprint": audit.campaign_spec_fingerprint,
        "complete_manifest_fingerprint": audit.complete_manifest_fingerprint,
        "checkpoint_manifest_fingerprint": audit.checkpoint_manifest_fingerprint,
        "slots": [
            {
                "trial_id": slot.trial_id,
                "coverage_state": slot.coverage_state,
                "snapshot_fingerprint": (
                    slot.provenance_snapshot.snapshot_fingerprint
                    if slot.provenance_snapshot is not None
                    else None
                ),
            }
            for slot in audit.slots
        ],
        "pairs": [
            {
                "run_id": pair.run_id,
                "checkpoint_id": pair.checkpoint_id,
                "test_arm_id": pair.test_arm_id,
                "comparator_arm_id": pair.comparator_arm_id,
                "pair_state": pair.pair_state,
            }
            for pair in audit.pairs
        ],
        "counts": {
            "declared_slots": counts.declared_slots,
            "missing_snapshots": counts.missing_snapshots,
            "unobserved_snapshots": counts.unobserved_snapshots,
            "events_recorded_snapshots": counts.events_recorded_snapshots,
            "submitted_snapshots": counts.submitted_snapshots,
            "declared_pairs": counts.declared_pairs,
            "both_submitted_pairs": counts.both_submitted_pairs,
        },
    }


def _assemble_audit(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    checkpoint_declarations: Sequence[Stage1RunCheckpointDeclarationV1],
    submitted_snapshots: Sequence[Stage1TrialProvenanceSnapshotV1],
) -> Stage1CheckpointCoverageAuditV1:
    """Audit declared synthetic submissions without inventing missing snapshots."""
    verify_experiment_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    declarations = _checked_declarations(
        checkpoint_declarations, expected_run_ids, require_sorted=False
    )
    _require_sequence(submitted_snapshots, "submitted_snapshots")

    manifest_hash = _full_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    checkpoint_hash = _checkpoint_manifest_fingerprint(
        campaign=campaign,
        complete_manifest_fingerprint=manifest_hash,
        declarations=declarations,
    )

    checkpoints_by_run = {
        decl.run_id: set(decl.checkpoint_ids) for decl in declarations
    }
    arm_ids = {arm.arm_id for arm in arms}
    submissions: dict[tuple[str, str, str], Stage1TrialProvenanceSnapshotV1] = {}

    for index, snapshot in enumerate(submitted_snapshots):
        if type(snapshot) is not Stage1TrialProvenanceSnapshotV1:
            raise ValueError(f"submitted_snapshots[{index}] has invalid type")
        verify_stage1_trial_provenance_snapshot(
            snapshot=snapshot,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_run_ids,
        )
        scope = snapshot.scope
        key = (scope.run_id, scope.checkpoint_id, scope.arm_id)
        if (
            scope.run_id not in checkpoints_by_run
            or scope.checkpoint_id not in checkpoints_by_run[scope.run_id]
            or scope.arm_id not in arm_ids
        ):
            raise ValueError(f"submitted snapshot outside checkpoint matrix: {key}")
        if scope.complete_manifest_fingerprint != manifest_hash:
            raise ValueError("submitted snapshot belongs to a different E1 manifest")
        if key in submissions:
            raise ValueError(f"duplicate submitted provenance snapshot: {key}")
        detached = _detach_snapshot(snapshot)
        verify_stage1_trial_provenance_snapshot(
            snapshot=detached,
            campaign=campaign,
            arms=arms,
            bindings=bindings,
            expected_run_ids=expected_run_ids,
        )
        submissions[key] = detached

    ordered_arms = sorted(arm_ids)
    slots: list[Stage1CoverageSlotV1] = []
    pairs: list[Stage1PairCoverageV1] = []
    test_arm = campaign.primary_comparison.test_arm_id
    comparator_arm = campaign.primary_comparison.comparator_arm_id

    for declaration in declarations:
        for checkpoint_id in declaration.checkpoint_ids:
            for arm_id in ordered_arms:
                snap = submissions.get((declaration.run_id, checkpoint_id, arm_id))
                state = (
                    snap.observation_state if snap is not None else "MISSING_SNAPSHOT"
                )
                slots.append(
                    Stage1CoverageSlotV1(
                        run_id=declaration.run_id,
                        checkpoint_id=checkpoint_id,
                        arm_id=arm_id,
                        trial_id=(
                            f"{campaign.campaign_id}:{declaration.run_id}:"
                            f"{arm_id}:{checkpoint_id}"
                        ),
                        coverage_state=state,
                        provenance_snapshot=snap,
                    )
                )
            test_present = (declaration.run_id, checkpoint_id, test_arm) in submissions
            comparator_present = (
                declaration.run_id,
                checkpoint_id,
                comparator_arm,
            ) in submissions
            if test_present and comparator_present:
                pair_state = "BOTH_SUBMITTED"
            elif not test_present and not comparator_present:
                pair_state = "BOTH_MISSING"
            elif not test_present:
                pair_state = "TEST_MISSING"
            else:
                pair_state = "COMPARATOR_MISSING"
            pairs.append(
                Stage1PairCoverageV1(
                    run_id=declaration.run_id,
                    checkpoint_id=checkpoint_id,
                    test_arm_id=test_arm,
                    comparator_arm_id=comparator_arm,
                    pair_state=pair_state,
                )
            )

    missing_count = sum(s.coverage_state == "MISSING_SNAPSHOT" for s in slots)
    unobserved_count = sum(s.coverage_state == "UNOBSERVED" for s in slots)
    recorded_count = sum(s.coverage_state == "EVENTS_RECORDED" for s in slots)
    counts = Stage1CoverageCountsV1(
        declared_slots=len(slots),
        missing_snapshots=missing_count,
        unobserved_snapshots=unobserved_count,
        events_recorded_snapshots=recorded_count,
        submitted_snapshots=unobserved_count + recorded_count,
        declared_pairs=len(pairs),
        both_submitted_pairs=sum(p.pair_state == "BOTH_SUBMITTED" for p in pairs),
    )

    before = Stage1CheckpointCoverageAuditV1(
        schema_version=COVERAGE_SCHEMA_VERSION,
        campaign_id=campaign.campaign_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        checkpoint_manifest_fingerprint=checkpoint_hash,
        checkpoint_declarations=declarations,
        slots=tuple(slots),
        pairs=tuple(pairs),
        counts=counts,
        audit_fingerprint="",
    )
    return replace(before, audit_fingerprint=content_hash(_audit_preimage(before)))


def build_stage1_checkpoint_coverage_audit(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    checkpoint_declarations: Sequence[Stage1RunCheckpointDeclarationV1],
    submitted_snapshots: Sequence[Stage1TrialProvenanceSnapshotV1],
) -> Stage1CheckpointCoverageAuditV1:
    """Build and independently verify a deterministic immutable coverage audit."""
    result = _assemble_audit(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        checkpoint_declarations=checkpoint_declarations,
        submitted_snapshots=submitted_snapshots,
    )
    verify_stage1_checkpoint_coverage_audit(
        audit=result,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    return result


def verify_stage1_checkpoint_coverage_audit(
    *,
    audit: Stage1CheckpointCoverageAuditV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool:
    """Fail closed on original stored coverage data, even if an attacker rehashes it."""
    if type(audit) is not Stage1CheckpointCoverageAuditV1:
        raise ValueError("audit must be an exact Stage1CheckpointCoverageAuditV1")
    if (
        type(audit.schema_version) is not str
        or audit.schema_version != COVERAGE_SCHEMA_VERSION
    ):
        raise ValueError("invalid coverage schema version")

    verify_experiment_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    if type(audit.campaign_id) is not str or audit.campaign_id != campaign.campaign_id:
        raise ValueError("coverage campaign ID mismatch")
    _require_sha(audit.campaign_spec_fingerprint, "campaign fingerprint")
    if audit.campaign_spec_fingerprint != campaign.campaign_spec_fingerprint:
        raise ValueError("coverage campaign fingerprint mismatch")
    manifest_hash = _full_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    _require_sha(audit.complete_manifest_fingerprint, "complete manifest fingerprint")
    if audit.complete_manifest_fingerprint != manifest_hash:
        raise ValueError("complete manifest fingerprint mismatch")

    if type(audit.checkpoint_declarations) is not tuple:
        raise ValueError("stored checkpoint declarations must be tuple")
    declarations = _checked_declarations(
        audit.checkpoint_declarations, expected_run_ids, require_sorted=True
    )
    _require_sha(
        audit.checkpoint_manifest_fingerprint, "checkpoint manifest fingerprint"
    )
    expected_checkpoint_sha = _checkpoint_manifest_fingerprint(
        campaign=campaign,
        complete_manifest_fingerprint=manifest_hash,
        declarations=declarations,
    )
    if audit.checkpoint_manifest_fingerprint != expected_checkpoint_sha:
        raise ValueError("checkpoint manifest fingerprint mismatch")

    if type(audit.slots) is not tuple or type(audit.pairs) is not tuple:
        raise ValueError("stored slots and pairs must be tuples")
    if type(audit.counts) is not Stage1CoverageCountsV1:
        raise ValueError("stored counts must be exact Stage1CoverageCountsV1")
    for field in fields(Stage1CoverageCountsV1):
        value = getattr(audit.counts, field.name)
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid non-Boolean count {field.name}")

    original_submissions: list[Stage1TrialProvenanceSnapshotV1] = []
    for index, slot in enumerate(audit.slots):
        if type(slot) is not Stage1CoverageSlotV1:
            raise ValueError(f"stored slot[{index}] has invalid type")
        _require_token(slot.run_id, "slot.run_id")
        _require_token(slot.arm_id, "slot.arm_id")
        _require_token(slot.checkpoint_id, "slot.checkpoint_id")
        if type(slot.trial_id) is not str:
            raise ValueError("slot.trial_id must be a string")
        if (
            type(slot.coverage_state) is not str
            or slot.coverage_state not in COVERAGE_STATES
        ):
            raise ValueError("invalid slot coverage_state")
        snap = slot.provenance_snapshot
        if snap is None:
            if slot.coverage_state != "MISSING_SNAPSHOT":
                raise ValueError("missing snapshot must be marked MISSING_SNAPSHOT")
        else:
            if type(snap) is not Stage1TrialProvenanceSnapshotV1:
                raise ValueError("stored slot provenance snapshot has invalid type")
            verify_stage1_trial_provenance_snapshot(
                snapshot=snap,
                campaign=campaign,
                arms=arms,
                bindings=bindings,
                expected_run_ids=expected_run_ids,
            )
            if slot.coverage_state != snap.observation_state:
                raise ValueError("slot state disagrees with submitted provenance")
            scope = snap.scope
            if (
                scope.run_id != slot.run_id
                or scope.checkpoint_id != slot.checkpoint_id
                or scope.arm_id != slot.arm_id
                or scope.trial_id != slot.trial_id
            ):
                raise ValueError("stored slot identity does not match provenance")
            original_submissions.append(snap)

    for index, pair in enumerate(audit.pairs):
        if type(pair) is not Stage1PairCoverageV1:
            raise ValueError(f"stored pair[{index}] has invalid type")
        _require_token(pair.run_id, "pair.run_id")
        _require_token(pair.checkpoint_id, "pair.checkpoint_id")
        _require_token(pair.test_arm_id, "pair.test_arm_id")
        _require_token(pair.comparator_arm_id, "pair.comparator_arm_id")
        if type(pair.pair_state) is not str or pair.pair_state not in PAIR_STATES:
            raise ValueError("invalid pair_state")

    # The canonical builder independently reconstructs all expected slots,
    # rejects duplicate submissions, and recalculates every pair and count.
    expected = _assemble_audit(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        checkpoint_declarations=declarations,
        submitted_snapshots=original_submissions,
    )
    if (
        audit.checkpoint_declarations != expected.checkpoint_declarations
        or audit.slots != expected.slots
        or audit.pairs != expected.pairs
        or audit.counts != expected.counts
    ):
        raise ValueError("stored audit does not match canonical coverage matrix")
    _require_sha(audit.audit_fingerprint, "audit fingerprint")
    if audit.audit_fingerprint != content_hash(_audit_preimage(audit)):
        raise ValueError("audit fingerprint mismatch")
    return True
