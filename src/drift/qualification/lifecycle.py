"""Verified profile-freeze start for the M1e pilot lifecycle."""

from collections.abc import Mapping

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import (
    AcquisitionPlanV1,
    AcquisitionReceiptV1,
    AcquisitionReconciliationV1,
)
from drift.domain.qualification import (
    M1ePilotStateV1,
    M1eTransitionV1,
    PilotStage,
    qualification_profile_hash,
)
from drift.domain.rights import ValidatedRightsAssessment
from drift.qualification.rights import (
    AcquisitionAuthorizationVerificationBundle,
    validate_rights_assessment,
    verify_acquisition_authorization,
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


def transition_rights_assessed(
    state: M1ePilotStateV1,
    assessment: ValidatedRightsAssessment,
) -> M1ePilotStateV1:
    """Advance one frozen purpose only after reverifying its exact rights evidence."""
    validated = validate_rights_assessment(
        assessment.profile,
        assessment.assessment,
        assessment.evidence,
    )
    if validated != assessment:
        raise ValueError("rights assessment does not reverify")
    profile_hash = qualification_profile_hash(assessment.profile)
    matches = tuple(
        item
        for item in state.purpose_states
        if item.purpose is assessment.profile.purpose
    )
    if len(matches) != 1 or matches[0].profile_hash != profile_hash:
        raise ValueError("rights assessment profile does not match pilot state")
    current = matches[0]
    if current.stage is not PilotStage.PROFILE_FROZEN:
        raise ValueError("rights assessment requires a frozen profile")
    assessment_hash = content_hash(assessment.assessment)
    topology_hash = content_hash(assessment.topology)
    advanced = current.model_copy(
        update={
            "stage": PilotStage.RIGHTS_ASSESSED,
            "reached_stage_artifact_hashes": (
                *current.reached_stage_artifact_hashes,
                topology_hash,
                assessment_hash,
            ),
        }
    )
    purpose_states = tuple(
        advanced if item.purpose is assessment.profile.purpose else item
        for item in state.purpose_states
    )
    return state.model_copy(
        update={
            "purpose_states": purpose_states,
            "shared_artifact_hashes": tuple(
                sorted(
                    {
                        *state.shared_artifact_hashes,
                        topology_hash,
                        assessment_hash,
                    }
                )
            ),
        }
    )


def transition_acquisition_authorized(
    state: M1ePilotStateV1,
    bundle: AcquisitionAuthorizationVerificationBundle,
) -> M1ePilotStateV1:
    """Advance only purpose lanes named by a reverified acquisition authority."""
    verify_acquisition_authorization(bundle)
    if state.profile_set_hash != content_hash(bundle.profiles):
        raise ValueError("acquisition profile set does not match pilot state")
    authorized = set(bundle.authorization.authorized_profile_hashes)
    assessments = {item.assessment.profile_hash: item for item in bundle.assessments}
    purpose_states_by_profile = {
        item.profile_hash: item for item in state.purpose_states
    }
    for profile_hash, assessment in assessments.items():
        recorded = purpose_states_by_profile.get(profile_hash)
        if (
            recorded is None
            or recorded.stage is not PilotStage.RIGHTS_ASSESSED
            or recorded.reached_stage_artifact_hashes[-2:]
            != (
                content_hash(assessment.topology),
                content_hash(assessment.assessment),
            )
        ):
            raise ValueError(
                "acquisition bundle does not match recorded rights assessment"
            )
    purpose_states = []
    for item in state.purpose_states:
        if item.profile_hash not in authorized:
            purpose_states.append(item)
            continue
        if item.stage is not PilotStage.RIGHTS_ASSESSED:
            raise ValueError("acquisition authorization requires assessed rights")
        purpose_states.append(
            item.model_copy(
                update={
                    "stage": PilotStage.ACQUISITION_AUTHORIZED,
                    "reached_stage_artifact_hashes": (
                        *item.reached_stage_artifact_hashes,
                        content_hash(bundle.eligibility),
                        content_hash(bundle.approval),
                        content_hash(bundle.authorization),
                    ),
                }
            )
        )
    if not authorized or not authorized.issubset(
        {item.profile_hash for item in state.purpose_states}
    ):
        raise ValueError("authorization names an unknown purpose profile")
    shared = tuple(
        sorted(
            {
                *state.shared_artifact_hashes,
                content_hash(bundle.eligibility),
                content_hash(bundle.approval),
                content_hash(bundle.authorization),
            }
        )
    )
    return state.model_copy(
        update={
            "purpose_states": tuple(purpose_states),
            "shared_artifact_hashes": shared,
        }
    )


def transition_acquired(
    state: M1ePilotStateV1,
    receipt: AcquisitionReceiptV1,
    plan: AcquisitionPlanV1,
    reconciliation: AcquisitionReconciliationV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> M1ePilotStateV1:
    """Advance purpose lanes to ACQUIRED upon verified receipts and reconciliation."""
    from drift.domain.acquisition import AcquisitionCompleteness
    from drift.qualification.acquisition import verify_acquisition_receipt

    verify_acquisition_receipt(receipt, artifacts)

    if reconciliation.result is not AcquisitionCompleteness.PASS:
        raise ValueError(
            f"acquisition completeness is {reconciliation.result.value}; "
            "cannot advance to ACQUIRED"
        )

    receipt_recon_hash = content_hash(reconciliation)
    if receipt.reconciliation_hash != receipt_recon_hash:
        raise ValueError(
            "receipt reconciliation hash does not match reconciliation content"
        )

    receipt_plan_hash = content_hash(plan)
    if receipt.acquisition_plan_hash != receipt_plan_hash:
        raise ValueError("receipt acquisition plan hash does not match plan content")

    if receipt.authorization_hash != plan.authorization_hash:
        raise ValueError("receipt authorization hash does not match acquisition plan")

    if receipt.expected_inventory_hash != plan.expected_inventory_hash:
        raise ValueError(
            "receipt expected inventory hash does not match acquisition plan"
        )

    if content_hash(receipt.native_layer_rule) != plan.planned_native_layer_rule_hash:
        raise ValueError(
            "receipt native layer rule hash does not match acquisition plan"
        )

    if receipt.native_layer_rule.profile_set_hash != state.profile_set_hash:
        raise ValueError(
            "receipt native layer rule profile set does not match pilot state"
        )

    if plan.request_scope_hash != content_hash(receipt.request):
        raise ValueError(
            "acquisition plan request scope hash does not match request content"
        )

    if len(receipt.pages) > plan.max_pages:
        raise ValueError(
            f"receipt page count {len(receipt.pages)} "
            f"exceeds plan max_pages {plan.max_pages}"
        )

    if len(receipt.observed_objects) > plan.max_objects:
        raise ValueError(
            f"receipt observed objects count {len(receipt.observed_objects)} "
            f"exceeds plan max_objects {plan.max_objects}"
        )

    total_bytes = sum(obj.byte_size for obj in receipt.byte_graph.objects)
    if total_bytes > plan.max_bytes:
        raise ValueError(
            f"total byte size {total_bytes} exceeds plan max_bytes {plan.max_bytes}"
        )

    if state.profile_set_hash != receipt.profile_set_hash:
        raise ValueError("receipt profile set does not match pilot state")

    supported_profiles = set(receipt.native_layer_rule.supported_profile_hashes)
    purpose_states = []
    advanced_count = 0
    receipt_hash = content_hash(receipt)

    for item in state.purpose_states:
        if item.profile_hash not in supported_profiles:
            purpose_states.append(item)
            continue
        if item.stage is not PilotStage.ACQUISITION_AUTHORIZED:
            raise ValueError(
                "advancement to ACQUIRED requires ACQUISITION_AUTHORIZED stage"
            )
        if (
            not item.reached_stage_artifact_hashes
            or item.reached_stage_artifact_hashes[-1] != receipt.authorization_hash
        ):
            raise ValueError(
                "receipt authorization does not match purpose state authorization"
            )

        advanced_count += 1
        purpose_states.append(
            item.model_copy(
                update={
                    "stage": PilotStage.ACQUIRED,
                    "reached_stage_artifact_hashes": (
                        *item.reached_stage_artifact_hashes,
                        receipt_plan_hash,
                        receipt_recon_hash,
                        receipt_hash,
                    ),
                }
            )
        )

    if advanced_count == 0:
        raise ValueError("receipt does not match any profile in pilot state")

    shared = tuple(
        sorted(
            {
                *state.shared_artifact_hashes,
                receipt_plan_hash,
                receipt_recon_hash,
                receipt_hash,
            }
        )
    )
    return state.model_copy(
        update={
            "purpose_states": tuple(purpose_states),
            "shared_artifact_hashes": shared,
        }
    )
