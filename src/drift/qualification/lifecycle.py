"""Pure nonterminal state transitions for the M1e pilot lifecycle."""

from drift.domain.qualification import (
    M1ePilotStateV1,
    M1eTransitionV1,
    PilotStage,
)

_NEXT_STAGE: dict[PilotStage | None, PilotStage] = {
    None: PilotStage.PROFILE_FROZEN,
    PilotStage.PROFILE_FROZEN: PilotStage.RIGHTS_ASSESSED,
    PilotStage.RIGHTS_ASSESSED: PilotStage.ACQUISITION_AUTHORIZED,
    PilotStage.ACQUISITION_AUTHORIZED: PilotStage.ACQUIRED,
    PilotStage.ACQUIRED: PilotStage.SNAPSHOT_FROZEN,
    PilotStage.SNAPSHOT_FROZEN: PilotStage.QUALIFIED,
    PilotStage.QUALIFIED: PilotStage.REPLAY_AUTHORIZED,
    PilotStage.REPLAY_AUTHORIZED: PilotStage.REPLAYED,
}


def transition_pilot(
    state: M1ePilotStateV1,
    transition: M1eTransitionV1,
) -> M1ePilotStateV1:
    """Advance exactly one matching purpose lane along one normative edge."""

    matches = tuple(
        item for item in state.purpose_states if item.purpose is transition.purpose
    )
    if len(matches) != 1:
        raise ValueError("transition purpose is not present exactly once")
    current = matches[0]
    if current.profile_hash != transition.profile_hash:
        raise ValueError("transition profile hash does not match its purpose lane")
    if current.stage != transition.from_stage:
        raise ValueError("transition from-stage does not match current state")
    expected = _NEXT_STAGE.get(current.stage)
    if expected is None or transition.to_stage is not expected:
        raise ValueError("transition is not a permitted nonterminal lifecycle edge")

    new_hashes = tuple(item.artifact_hash for item in transition.artifacts)
    advanced = current.model_copy(
        update={
            "stage": transition.to_stage,
            "reached_stage_artifact_hashes": (
                *current.reached_stage_artifact_hashes,
                *new_hashes,
            ),
        }
    )
    purpose_states = tuple(
        advanced if item.purpose is transition.purpose else item
        for item in state.purpose_states
    )
    shared_hashes = tuple(
        sorted(
            {
                *state.shared_artifact_hashes,
                *transition.shared_artifact_hashes,
            }
        )
    )
    return state.model_copy(
        update={
            "purpose_states": purpose_states,
            "shared_artifact_hashes": shared_hashes,
        }
    )
