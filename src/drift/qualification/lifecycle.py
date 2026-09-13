"""Verified profile-freeze start for the M1e pilot lifecycle."""

from drift.domain.qualification import (
    M1ePilotStateV1,
    M1eTransitionV1,
    PilotStage,
    qualification_profile_hash,
)
from drift.serialization.canonical import content_hash


def transition_pilot(
    state: M1ePilotStateV1,
    transition: M1eTransitionV1,
) -> M1ePilotStateV1:
    """Freeze one exact profile from the state's actual two-profile set."""

    profile_set_hash = content_hash(transition.profile_set)
    if state.profile_set_hash != profile_set_hash:
        raise ValueError("profile freeze set does not match pilot state")
    expected_profiles = {
        item.purpose: qualification_profile_hash(item)
        for item in transition.profile_set.profiles
    }
    actual_profiles = {item.purpose: item.profile_hash for item in state.purpose_states}
    if actual_profiles != expected_profiles:
        raise ValueError("pilot state purpose profiles do not match profile set")
    matches = tuple(
        item
        for item in state.purpose_states
        if item.purpose is transition.profile.purpose
    )
    if len(matches) != 1:
        raise ValueError("profile freeze purpose is not present exactly once")
    current = matches[0]
    profile_hash = qualification_profile_hash(transition.profile)
    if current.profile_hash != profile_hash:
        raise ValueError("profile freeze hash does not match its purpose lane")
    if current.stage is not None:
        raise ValueError("profile purpose has already started")

    reached_hashes = (
        profile_set_hash,
        profile_hash,
        transition.profile.golden_case_instance_manifest_hash,
    )
    advanced = current.model_copy(
        update={
            "stage": PilotStage.PROFILE_FROZEN,
            "reached_stage_artifact_hashes": reached_hashes,
        }
    )
    purpose_states = tuple(
        advanced if item.purpose is transition.profile.purpose else item
        for item in state.purpose_states
    )
    shared_hashes = tuple(
        sorted(
            {
                *state.shared_artifact_hashes,
                profile_set_hash,
                transition.profile.golden_case_instance_manifest_hash,
            }
        )
    )
    return state.model_copy(
        update={
            "purpose_states": purpose_states,
            "shared_artifact_hashes": shared_hashes,
        }
    )
