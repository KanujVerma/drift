from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from drift.experiments.stage1_campaign_config import (
    ArmSpecV1,
    CampaignSpecV1,
    RunAccountBindingV1,
    verify_experiment_configuration,
)
from drift.experiments.stage1_trial_events import (
    Stage1TrialEvent,
    append_stage1_trial_event,
    verify_stage1_trial_chain,
)
from drift.serialization.canonical import content_hash

PROVENANCE_SCHEMA_VERSION = "drift-trial-provenance/1-draft"
MANIFEST_SCHEMA_VERSION = "drift-trial-manifest/1-draft"
PROVENANCE_STATES = frozenset({"UNOBSERVED", "EVENTS_RECORDED"})
_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class Stage1TrialScopeV1:
    campaign_id: str
    run_id: str
    arm_id: str
    checkpoint_id: str
    trial_id: str
    campaign_spec_fingerprint: str
    arm_spec_fingerprint: str
    complete_manifest_fingerprint: str
    run_account_binding: RunAccountBindingV1


@dataclass(frozen=True, slots=True)
class Stage1TrialProvenanceSnapshotV1:
    schema_version: str
    scope: Stage1TrialScopeV1
    observation_state: str
    event_envelopes: tuple[Stage1TrialEvent, ...]
    event_count: int
    chain_head_event_hash: str | None
    snapshot_fingerprint: str


def _validate_scope_token(value: str, field_name: str) -> None:
    if type(value) is not str or not _SCOPE_ID.match(value):
        raise ValueError(
            f"{field_name} must be ASCII alphanumeric/._- string "
            f"without colons, got: {value!r}"
        )


def _validate_sha256(value: str, field_name: str) -> None:
    if type(value) is not str or not _SHA256.match(value):
        raise ValueError(
            f"{field_name} must be a 64-character lowercase hex "
            f"SHA-256 string, got: {value!r}"
        )


def _complete_manifest_preimage(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> dict[str, object]:
    sorted_expected_runs = sorted(expected_run_ids)
    sorted_arm_refs = sorted(arm.arm_spec_fingerprint for arm in arms)
    sorted_bindings = sorted(
        bindings,
        key=lambda b: (b.campaign_id, b.run_id, b.arm_id),
    )
    binding_records = [
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
        for b in sorted_bindings
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "campaign_spec_fingerprint": campaign.campaign_spec_fingerprint,
        "expected_run_ids": sorted_expected_runs,
        "arm_spec_references": sorted_arm_refs,
        "run_account_bindings": binding_records,
    }


def _complete_manifest_fingerprint(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> str:
    preimage = _complete_manifest_preimage(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    return content_hash(preimage)


def _provenance_preimage(
    snapshot: Stage1TrialProvenanceSnapshotV1,
) -> dict[str, object]:
    scope = snapshot.scope
    binding = scope.run_account_binding
    scope_dict = {
        "campaign_id": scope.campaign_id,
        "run_id": scope.run_id,
        "arm_id": scope.arm_id,
        "checkpoint_id": scope.checkpoint_id,
        "trial_id": scope.trial_id,
        "campaign_spec_fingerprint": scope.campaign_spec_fingerprint,
        "arm_spec_fingerprint": scope.arm_spec_fingerprint,
        "complete_manifest_fingerprint": scope.complete_manifest_fingerprint,
        "run_account_binding": {
            "schema_version": binding.schema_version,
            "binding_id": binding.binding_id,
            "campaign_id": binding.campaign_id,
            "run_id": binding.run_id,
            "arm_id": binding.arm_id,
            "portfolio_account_id": binding.portfolio_account_id,
            "initial_cash_allocated": binding.initial_cash_allocated,
            "bound_at": binding.bound_at,
        },
    }
    return {
        "schema_version": snapshot.schema_version,
        "scope": scope_dict,
        "observation_state": snapshot.observation_state,
        "event_count": snapshot.event_count,
        "chain_head_event_hash": snapshot.chain_head_event_hash,
        "event_hashes": [e.event_hash for e in snapshot.event_envelopes],
    }


def build_stage1_trial_provenance_snapshot(
    *,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
    run_id: str,
    arm_id: str,
    checkpoint_id: str,
    events: Sequence[Stage1TrialEvent],
) -> Stage1TrialProvenanceSnapshotV1:
    verify_experiment_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    _validate_scope_token(run_id, "run_id")
    _validate_scope_token(arm_id, "arm_id")
    _validate_scope_token(checkpoint_id, "checkpoint_id")

    if run_id not in expected_run_ids:
        raise ValueError(
            f"run_id {run_id!r} not in expected_run_ids: {list(expected_run_ids)!r}"
        )

    matching_arms = [a for a in arms if a.arm_id == arm_id]
    if len(matching_arms) != 1:
        raise ValueError(
            f"expected exactly one arm with arm_id {arm_id!r}, "
            f"found {len(matching_arms)}"
        )
    selected_arm = matching_arms[0]

    matching_bindings = [
        b
        for b in bindings
        if b.campaign_id == campaign.campaign_id
        and b.run_id == run_id
        and b.arm_id == arm_id
    ]
    if len(matching_bindings) != 1:
        raise ValueError(
            f"expected exactly one binding for "
            f"{(campaign.campaign_id, run_id, arm_id)}, "
            f"found {len(matching_bindings)}"
        )
    selected_binding = replace(matching_bindings[0])

    manifest_hash = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    trial_id = f"{campaign.campaign_id}:{run_id}:{arm_id}:{checkpoint_id}"

    scope = Stage1TrialScopeV1(
        campaign_id=campaign.campaign_id,
        run_id=run_id,
        arm_id=arm_id,
        checkpoint_id=checkpoint_id,
        trial_id=trial_id,
        campaign_spec_fingerprint=campaign.campaign_spec_fingerprint,
        arm_spec_fingerprint=selected_arm.arm_spec_fingerprint,
        complete_manifest_fingerprint=manifest_hash,
        run_account_binding=selected_binding,
    )

    if events is None or isinstance(
        events, (str, bytes, bytearray, memoryview, Mapping)
    ):
        raise ValueError("events must be a sequence of Stage1TrialEvent objects")
    if not isinstance(events, Sequence):
        raise ValueError("events must be a sequence of Stage1TrialEvent objects")

    if len(events) == 0:
        observation_state = "UNOBSERVED"
        event_envelopes: tuple[Stage1TrialEvent, ...] = ()
        event_count = 0
        chain_head_event_hash = None
    else:
        for idx, ev in enumerate(events):
            if type(ev) is not Stage1TrialEvent:
                raise ValueError(
                    f"events[{idx}] must be a Stage1TrialEvent instance, "
                    f"got: {type(ev)}"
                )
        copied_events = tuple(replace(ev) for ev in events)
        verify_stage1_trial_chain(trial_id=trial_id, events=copied_events)
        observation_state = "EVENTS_RECORDED"
        event_envelopes = copied_events
        event_count = len(copied_events)
        chain_head_event_hash = copied_events[-1].event_hash

    pre_snapshot = Stage1TrialProvenanceSnapshotV1(
        schema_version=PROVENANCE_SCHEMA_VERSION,
        scope=scope,
        observation_state=observation_state,
        event_envelopes=event_envelopes,
        event_count=event_count,
        chain_head_event_hash=chain_head_event_hash,
        snapshot_fingerprint="",
    )
    fingerprint = content_hash(_provenance_preimage(pre_snapshot))
    snapshot = replace(pre_snapshot, snapshot_fingerprint=fingerprint)

    verify_stage1_trial_provenance_snapshot(
        snapshot=snapshot,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    return snapshot


def verify_stage1_trial_provenance_snapshot(
    *,
    snapshot: Stage1TrialProvenanceSnapshotV1,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> bool:
    if type(snapshot) is not Stage1TrialProvenanceSnapshotV1:
        raise ValueError("snapshot must be a Stage1TrialProvenanceSnapshotV1 instance")

    if (
        type(snapshot.schema_version) is not str
        or snapshot.schema_version != PROVENANCE_SCHEMA_VERSION
    ):
        raise ValueError(f"unsupported schema_version: {snapshot.schema_version!r}")

    scope = snapshot.scope
    if type(scope) is not Stage1TrialScopeV1:
        raise ValueError("scope must be a Stage1TrialScopeV1 instance")

    verify_experiment_configuration(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    expected_manifest_fingerprint = _complete_manifest_fingerprint(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )
    if (
        type(scope.complete_manifest_fingerprint) is not str
        or scope.complete_manifest_fingerprint != expected_manifest_fingerprint
    ):
        raise ValueError(
            "complete_manifest_fingerprint mismatch: "
            f"expected {expected_manifest_fingerprint!r}, "
            f"got {scope.complete_manifest_fingerprint!r}"
        )

    _validate_scope_token(scope.campaign_id, "scope.campaign_id")
    _validate_scope_token(scope.run_id, "scope.run_id")
    _validate_scope_token(scope.arm_id, "scope.arm_id")
    _validate_scope_token(scope.checkpoint_id, "scope.checkpoint_id")

    if type(scope.campaign_id) is not str or scope.campaign_id != campaign.campaign_id:
        raise ValueError(
            f"scope.campaign_id mismatch: expected {campaign.campaign_id!r}, "
            f"got {scope.campaign_id!r}"
        )

    if (
        type(scope.campaign_spec_fingerprint) is not str
        or scope.campaign_spec_fingerprint != campaign.campaign_spec_fingerprint
    ):
        raise ValueError(
            f"scope.campaign_spec_fingerprint mismatch: "
            f"expected {campaign.campaign_spec_fingerprint!r}, "
            f"got {scope.campaign_spec_fingerprint!r}"
        )

    expected_trial_id = (
        f"{scope.campaign_id}:{scope.run_id}:{scope.arm_id}:{scope.checkpoint_id}"
    )
    if type(scope.trial_id) is not str or scope.trial_id != expected_trial_id:
        raise ValueError(
            f"scope.trial_id mismatch: expected {expected_trial_id!r}, "
            f"got {scope.trial_id!r}"
        )

    matching_arms = [a for a in arms if a.arm_id == scope.arm_id]
    if len(matching_arms) != 1:
        raise ValueError(
            f"expected exactly one arm for arm_id {scope.arm_id!r}, "
            f"found {len(matching_arms)}"
        )
    matching_arm = matching_arms[0]
    if (
        type(scope.arm_spec_fingerprint) is not str
        or scope.arm_spec_fingerprint != matching_arm.arm_spec_fingerprint
    ):
        raise ValueError(
            f"scope.arm_spec_fingerprint mismatch: "
            f"expected {matching_arm.arm_spec_fingerprint!r}, "
            f"got {scope.arm_spec_fingerprint!r}"
        )

    matching_bindings = [
        b
        for b in bindings
        if b.campaign_id == scope.campaign_id
        and b.run_id == scope.run_id
        and b.arm_id == scope.arm_id
    ]
    if len(matching_bindings) != 1:
        raise ValueError(
            f"expected exactly one binding for "
            f"{(scope.campaign_id, scope.run_id, scope.arm_id)}, "
            f"found {len(matching_bindings)}"
        )
    expected_binding = matching_bindings[0]

    binding = scope.run_account_binding
    if type(binding) is not RunAccountBindingV1:
        raise ValueError("run_account_binding must be a RunAccountBindingV1 instance")

    if (
        type(binding.schema_version) is not str
        or binding.schema_version != expected_binding.schema_version
    ):
        raise ValueError("run_account_binding.schema_version mismatch")
    if (
        type(binding.binding_id) is not str
        or binding.binding_id != expected_binding.binding_id
    ):
        raise ValueError("run_account_binding.binding_id mismatch")
    if (
        type(binding.campaign_id) is not str
        or binding.campaign_id != expected_binding.campaign_id
    ):
        raise ValueError("run_account_binding.campaign_id mismatch")
    if type(binding.run_id) is not str or binding.run_id != expected_binding.run_id:
        raise ValueError("run_account_binding.run_id mismatch")
    if type(binding.arm_id) is not str or binding.arm_id != expected_binding.arm_id:
        raise ValueError("run_account_binding.arm_id mismatch")
    if (
        type(binding.portfolio_account_id) is not str
        or binding.portfolio_account_id != expected_binding.portfolio_account_id
    ):
        raise ValueError("run_account_binding.portfolio_account_id mismatch")
    if (
        type(binding.initial_cash_allocated) is not str
        or binding.initial_cash_allocated != expected_binding.initial_cash_allocated
    ):
        raise ValueError("run_account_binding.initial_cash_allocated mismatch")
    if (
        type(binding.bound_at) is not str
        or binding.bound_at != expected_binding.bound_at
    ):
        raise ValueError("run_account_binding.bound_at mismatch")

    if type(snapshot.event_envelopes) is not tuple:
        raise ValueError("event_envelopes must be a tuple")

    if (
        type(snapshot.event_count) is not int
        or isinstance(snapshot.event_count, bool)
        or snapshot.event_count < 0
    ):
        raise ValueError(
            f"event_count must be a non-negative integer, got: {snapshot.event_count!r}"
        )

    if snapshot.event_count != len(snapshot.event_envelopes):
        raise ValueError(
            f"event_count mismatch: recorded {snapshot.event_count}, "
            f"actual envelopes {len(snapshot.event_envelopes)}"
        )

    for idx, ev in enumerate(snapshot.event_envelopes):
        if type(ev) is not Stage1TrialEvent:
            raise ValueError(
                f"event_envelopes[{idx}] must be a Stage1TrialEvent instance, "
                f"got: {type(ev)}"
            )

    if (
        type(snapshot.observation_state) is not str
        or snapshot.observation_state not in PROVENANCE_STATES
    ):
        raise ValueError(
            f"unsupported observation_state: {snapshot.observation_state!r}"
        )

    if len(snapshot.event_envelopes) == 0:
        if snapshot.observation_state != "UNOBSERVED":
            raise ValueError(
                f"observation_state must be 'UNOBSERVED' for empty events, "
                f"got: {snapshot.observation_state!r}"
            )
        if snapshot.chain_head_event_hash is not None:
            raise ValueError(
                "chain_head_event_hash must be None for empty events, "
                f"got: {snapshot.chain_head_event_hash!r}"
            )
    else:
        if snapshot.observation_state != "EVENTS_RECORDED":
            raise ValueError(
                f"observation_state must be 'EVENTS_RECORDED' for nonempty events, "
                f"got: {snapshot.observation_state!r}"
            )
        if type(snapshot.chain_head_event_hash) is not str or not _SHA256.match(
            snapshot.chain_head_event_hash
        ):
            raise ValueError(
                "chain_head_event_hash must be a 64-character lowercase hex string, "
                f"got: {snapshot.chain_head_event_hash!r}"
            )
        if snapshot.chain_head_event_hash != snapshot.event_envelopes[-1].event_hash:
            raise ValueError(
                "chain_head_event_hash mismatch: "
                f"expected {snapshot.event_envelopes[-1].event_hash!r}, "
                f"got {snapshot.chain_head_event_hash!r}"
            )
        verify_stage1_trial_chain(
            trial_id=scope.trial_id, events=snapshot.event_envelopes
        )

    _validate_sha256(snapshot.snapshot_fingerprint, "snapshot_fingerprint")
    expected_fingerprint = content_hash(_provenance_preimage(snapshot))
    if snapshot.snapshot_fingerprint != expected_fingerprint:
        raise ValueError(
            "snapshot_fingerprint mismatch: "
            f"expected {expected_fingerprint!r}, "
            f"got {snapshot.snapshot_fingerprint!r}"
        )

    return True


def append_stage1_trial_provenance_event(
    *,
    snapshot: Stage1TrialProvenanceSnapshotV1,
    event: Stage1TrialEvent,
    campaign: CampaignSpecV1,
    arms: Sequence[ArmSpecV1],
    bindings: Sequence[RunAccountBindingV1],
    expected_run_ids: Sequence[str],
) -> Stage1TrialProvenanceSnapshotV1:
    verify_stage1_trial_provenance_snapshot(
        snapshot=snapshot,
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
    )

    if type(event) is not Stage1TrialEvent:
        raise ValueError("event must be an exact Stage1TrialEvent instance")

    new_envelopes = append_stage1_trial_event(
        events=snapshot.event_envelopes,
        event=event,
    )

    if new_envelopes is snapshot.event_envelopes:
        return snapshot

    return build_stage1_trial_provenance_snapshot(
        campaign=campaign,
        arms=arms,
        bindings=bindings,
        expected_run_ids=expected_run_ids,
        run_id=snapshot.scope.run_id,
        arm_id=snapshot.scope.arm_id,
        checkpoint_id=snapshot.scope.checkpoint_id,
        events=new_envelopes,
    )
