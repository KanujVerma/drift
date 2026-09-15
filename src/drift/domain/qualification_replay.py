"""Domain models and algorithms for M1e offline replay,
attestations, and terminal bundles.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid7

from pydantic import model_validator

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import (
    AcquisitionPlanV1,
    AcquisitionReceiptV1,
    AcquisitionReconciliationV1,
)
from drift.domain.artifacts import ArtifactKind, ArtifactReference
from drift.domain.common import UUID7, FrozenModel, SHA256Hash, UTCDateTime
from drift.domain.environment_closure import EnvironmentClosureV1
from drift.domain.golden_cases import GoldenCaseResultV1
from drift.domain.qualification import (
    _ALL_DIMENSIONS,
    _PRE_REPLAY_DIMENSIONS,
    ConsumerPurpose,
    ContentDispositionRecordV1,
    DimensionQualificationResultV1,
    ExecutionReachability,
    ExternalDependencyResolutionV1,
    M1eCompletionKind,
    M1eCompletionRecordV1,
    M1ePilotStateV1,
    PilotStage,
    PreReplayQualificationReportV1,
    PurposeQualificationReportV1,
    PurposeStageStateV1,
    QualificationDimension,
    QualificationProfileV1,
    QualificationStatus,
    QualificationTargetV1,
    qualification_profile_hash,
)
from drift.domain.qualification_adapters import (
    QualifiedSourceHandoffV1,
    qualified_source_handoff_hash,
)
from drift.domain.rights import (
    RightsEvidenceContext,
    ValidatedRightsAssessment,
)
from drift.domain.source_snapshots import (
    CanonicalReplayInputEntryV1,
    CrossComponentConsistencyDecisionV1,
    RealSourceSnapshotV1,
)
from drift.qualification.adapters import (
    CandidateValidationContext,
    ValidatedCandidateFactSet,
)
from drift.qualification.harness import QualificationExecutionContext
from drift.qualification.rights import (
    AcquisitionAuthorizationVerificationBundle,
    ReplayAuthorizationVerificationBundle,
)
from drift.serialization.canonical import content_hash


class OfflineControlStatus(StrEnum):
    """Status of system-level network isolation enforcement."""

    ENFORCED = "enforced"
    NOT_ENFORCED = "not_enforced"
    UNKNOWN = "unknown"


class ReplayOutcome(StrEnum):
    """Closed classification of replay evaluation results."""

    MATCH = "MATCH"
    SOURCE_BYTES_UNAVAILABLE = "SOURCE_BYTES_UNAVAILABLE"
    USE_DENIED_BY_RIGHTS = "USE_DENIED_BY_RIGHTS"
    ENVIRONMENT_ARTIFACT_UNAVAILABLE = "ENVIRONMENT_ARTIFACT_UNAVAILABLE"
    PLATFORM_INCOMPATIBLE = "PLATFORM_INCOMPATIBLE"
    SEMANTIC_IDENTITY_MISMATCH = "SEMANTIC_IDENTITY_MISMATCH"
    OUTPUT_HASH_MISMATCH = "OUTPUT_HASH_MISMATCH"


class ReplayExecutionStatus(StrEnum):
    """Process execution state of a replay attempt."""

    NOT_STARTED = "not_started"
    EXECUTED = "executed"


class ExpectedOutputV1(FrozenModel):
    """Exact expected output descriptor for one dataset role."""

    schema_version: Literal["1"] = "1"
    role: str
    content_hash: SHA256Hash
    byte_size: int


class OfflineProbeResultV1(FrozenModel):
    """Evidence result of a single network probe under isolation."""

    schema_version: Literal["1"] = "1"
    probe_name: str
    destination_class: str
    attempted_at: UTCDateTime
    status: str
    exit_code: int
    log_evidence_hash: SHA256Hash


class IsolationExecutionPlanV1(FrozenModel):
    """Pre-run OS/VM isolation mechanism configuration and expected probes."""

    schema_version: Literal["1"] = "1"
    isolation_mechanism: str
    expected_vm_identity: str
    network_configuration: str
    probes: tuple[str, ...]
    control_owner: str
    policy_hash: SHA256Hash
    plan_hash: SHA256Hash


class CleanTargetPlanV1(FrozenModel):
    """Pre-run clean target workspace rules and disposal constraints."""

    schema_version: Literal["1"] = "1"
    target_identity_rule: str
    empty_base_requirements: tuple[str, ...]
    permitted_mounts: tuple[str, ...]
    environment_allowlist: tuple[str, ...]
    disposal_rule: str
    policy_hash: SHA256Hash
    plan_hash: SHA256Hash


def isolation_execution_plan_hash(plan: IsolationExecutionPlanV1) -> SHA256Hash:
    """Compute canonical hash for IsolationExecutionPlanV1 excluding plan_hash."""
    dump = plan.model_dump(mode="python")
    dump.pop("plan_hash", None)
    return content_hash(dump)


def clean_target_plan_hash(plan: CleanTargetPlanV1) -> SHA256Hash:
    """Compute canonical hash for CleanTargetPlanV1 excluding plan_hash."""
    dump = plan.model_dump(mode="python")
    dump.pop("plan_hash", None)
    return content_hash(dump)


def system_offline_attestation_hash(
    attestation: SystemOfflineAttestationV1,
) -> SHA256Hash:
    """Compute canonical hash for SystemOfflineAttestationV1
    excluding attestation_hash.
    """
    dump = attestation.model_dump(mode="python")
    dump.pop("attestation_hash", None)
    return content_hash(dump)


class SystemOfflineAttestationV1(FrozenModel):
    """Post-run system operator attestation of enforced offline network controls."""

    schema_version: Literal["1"] = "1"
    request_hash: SHA256Hash
    attempt_id: UUID7
    vm_identity: str
    process_tree_identity: str
    enforced_mechanism: str
    control_interval_start: UTCDateTime
    control_interval_end: UTCDateTime
    configuration_evidence_hash: SHA256Hash
    probe_results: tuple[OfflineProbeResultV1, ...]
    status: OfflineControlStatus
    attestor_id: str
    policy_hash: SHA256Hash
    attestation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        if self.control_interval_end < self.control_interval_start:
            raise ValueError(
                "control interval end cannot precede control interval start"
            )
        if self.status is OfflineControlStatus.ENFORCED:
            mech = self.enforced_mechanism.lower().strip()
            disallowed = (
                "uv",
                "pip",
                "flag",
                "npm",
                "package_manager",
                "cli",
                "conda",
                "poetry",
                "pdm",
                "yarn",
                "offline",
                "index",
                "no-index",
            )
            if mech.startswith("-") or any(bad in mech for bad in disallowed):
                raise ValueError(
                    f"package-manager flags ({self.enforced_mechanism}) "
                    "cannot satisfy system-level offline enforcement"
                )
            if not self.probe_results:
                raise ValueError(
                    "enforced system offline attestation requires probe results"
                )
        return self


def fresh_restore_attestation_hash(
    attestation: FreshRestoreAttestationV1,
) -> SHA256Hash:
    """Compute canonical hash for FreshRestoreAttestationV1
    excluding attestation_hash.
    """
    dump = attestation.model_dump(mode="python")
    dump.pop("attestation_hash", None)
    return content_hash(dump)


class FreshRestoreAttestationV1(FrozenModel):
    """Post-run attestation confirming execution in a clean, non-inherited target."""

    schema_version: Literal["1"] = "1"
    request_hash: SHA256Hash
    attempt_id: UUID7
    target_identity: str
    base_state_evidence_hash: SHA256Hash
    absence_of_inherited_state: bool
    creation_evidence_hash: SHA256Hash
    process_use_evidence_hash: SHA256Hash
    disposal_evidence_hash: SHA256Hash
    attestor_id: str
    policy_hash: SHA256Hash
    attestation_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_freshness(self) -> Self:
        if not self.absence_of_inherited_state:
            raise ValueError(
                "fresh restore attestation requires absence of inherited state"
            )
        return self


def replay_comparison_policy_hash(policy: ReplayComparisonPolicyV1) -> SHA256Hash:
    """Compute canonical hash for ReplayComparisonPolicyV1 excluding policy_hash."""
    dump = policy.model_dump(mode="python")
    dump.pop("policy_hash", None)
    return content_hash(dump)


class ReplayComparisonPolicyV1(FrozenModel):
    """Artifact roles compared and small exclusion list for replay equivalence."""

    schema_version: Literal["1"] = "1"
    compared_artifact_roles: tuple[str, ...]
    replay_envelope_exclusions: tuple[str, ...] = ()
    policy_hash: SHA256Hash


def replay_request_hash(request: ReplayRequestV1) -> SHA256Hash:
    """Compute canonical hash for ReplayRequestV1 excluding request_hash."""
    dump = request.model_dump(mode="python")
    dump.pop("request_hash", None)
    return content_hash(dump)


class ReplayRequestV1(FrozenModel):
    """Pre-execution request defining exact inputs and isolation requirements."""

    schema_version: Literal["1"] = "1"
    profile_hash: SHA256Hash
    target_hash: SHA256Hash
    snapshot_hash: SHA256Hash
    closure_hash: SHA256Hash
    pre_replay_report_hash: SHA256Hash
    expected_limitations: tuple[str, ...]
    authorization_hash: SHA256Hash
    isolation_plan: IsolationExecutionPlanV1
    clean_target_plan: CleanTargetPlanV1
    comparison_policy: ReplayComparisonPolicyV1
    requested_output_inventory: tuple[str, ...]
    request_hash: SHA256Hash

    @model_validator(mode="after")
    def validate_request(self) -> ReplayRequestV1:
        expected = replay_request_hash(self)
        if self.request_hash != expected:
            raise ValueError(
                f"request hash mismatch: expected {expected}, got {self.request_hash}"
            )
        return self


class ReplayAttemptEnvelopeV1(FrozenModel):
    """Transient run-specific diagnostics that are not historical equality inputs."""

    schema_version: Literal["1"] = "1"
    attempt_id: UUID7
    start_time: UTCDateTime
    end_time: UTCDateTime
    process_ids: tuple[int, ...]
    temporary_paths: tuple[str, ...]
    cache_layout: str
    diagnostics: tuple[str, ...]
    host_observations: tuple[str, ...]


def replay_execution_record_hash(record: ReplayExecutionRecordV1) -> SHA256Hash:
    """Compute canonical hash for ReplayExecutionRecordV1
    excluding execution_record_hash.
    """
    dump = record.model_dump(mode="python")
    dump.pop("execution_record_hash", None)
    return content_hash(dump)


class ReplayExecutionRecordV1(FrozenModel):
    """Factual execution record of a replay attempt before post-run attestations."""

    schema_version: Literal["1"] = "1"
    request_hash: SHA256Hash
    authorization_hash: SHA256Hash
    attempt_envelope: ReplayAttemptEnvelopeV1
    verified_inputs: tuple[SHA256Hash, ...]
    status: ReplayExecutionStatus
    preflight_outcome: ReplayOutcome | None = None
    actual_outputs: tuple[SHA256Hash, ...]
    process_tree_identity: str
    target_identity: str
    start_time: UTCDateTime
    end_time: UTCDateTime
    raw_outcome_evidence_hash: SHA256Hash
    execution_record_hash: SHA256Hash


def replay_result_hash(result: ReplayResultV1) -> SHA256Hash:
    """Compute canonical hash for ReplayResultV1 excluding result_hash."""
    dump = result.model_dump(mode="python")
    dump.pop("result_hash", None)
    return content_hash(dump)


class ReplayResultV1(FrozenModel):
    """Typed final outcome of evaluating an executed replay attempt."""

    schema_version: Literal["1"] = "1"
    result_id: UUID7
    evaluated_at: UTCDateTime
    request_hash: SHA256Hash
    authorization_hash: SHA256Hash
    outcome: ReplayOutcome
    verified_input_hashes: tuple[SHA256Hash, ...]
    actual_output_hashes: tuple[SHA256Hash, ...]
    offline_attestation_hash: SHA256Hash | None = None
    fresh_attestation_hash: SHA256Hash | None = None
    mismatch_classifications: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    attempt_envelope: ReplayAttemptEnvelopeV1
    replay_implementation_hash: SHA256Hash
    policy_hash: SHA256Hash
    result_hash: SHA256Hash


def compare_replay_outputs(
    expected: tuple[ExpectedOutputV1, ...],
    actual: tuple[ExpectedOutputV1, ...],
    policy: ReplayComparisonPolicyV1,
) -> ReplayOutcome:
    """Compare expected outputs against actual outputs according to policy."""
    expected_by_role = {item.role: item.content_hash for item in expected}
    actual_by_role = {item.role: item.content_hash for item in actual}

    for role in policy.compared_artifact_roles:
        if role not in expected_by_role or role not in actual_by_role:
            return ReplayOutcome.OUTPUT_HASH_MISMATCH
        if expected_by_role[role] != actual_by_role[role]:
            return ReplayOutcome.OUTPUT_HASH_MISMATCH
    return ReplayOutcome.MATCH


def finalize_replay_result(
    *,
    execution: ReplayExecutionRecordV1,
    offline: SystemOfflineAttestationV1 | None,
    fresh: FreshRestoreAttestationV1 | None,
    expected: tuple[ExpectedOutputV1, ...],
    actual: tuple[ExpectedOutputV1, ...],
    policy: ReplayComparisonPolicyV1,
    replay_implementation_hash: SHA256Hash,
) -> ReplayResultV1:
    """Evaluate replay outcome strictly applying hierarchy rules top to bottom."""
    from uuid import uuid7

    # 1. Preflight denial or unstarted execution
    if execution.status == ReplayExecutionStatus.NOT_STARTED:
        outcome = execution.preflight_outcome or ReplayOutcome.USE_DENIED_BY_RIGHTS
    elif execution.preflight_outcome in (
        ReplayOutcome.PLATFORM_INCOMPATIBLE,
        ReplayOutcome.SEMANTIC_IDENTITY_MISMATCH,
        ReplayOutcome.SOURCE_BYTES_UNAVAILABLE,
        ReplayOutcome.USE_DENIED_BY_RIGHTS,
    ):
        outcome = execution.preflight_outcome
    elif offline is None or fresh is None:
        outcome = ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE
    elif offline.status != OfflineControlStatus.ENFORCED:
        outcome = ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE
    elif not fresh.absence_of_inherited_state:
        outcome = ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE
    else:
        if offline.attempt_id != execution.attempt_envelope.attempt_id:
            raise ValueError(
                f"offline attestation attempt_id {offline.attempt_id} does not "
                f"match execution attempt_id {execution.attempt_envelope.attempt_id}"
            )
        if offline.request_hash != execution.request_hash:
            raise ValueError(
                "offline attestation request_hash does not match execution request_hash"
            )
        if offline.control_interval_end < execution.start_time:
            raise ValueError(
                "offline attestation interval cannot predate execution attempt"
            )
        if offline.control_interval_start > execution.start_time:
            raise ValueError(
                "offline attestation interval must cover execution start time"
            )
        if fresh.attempt_id != execution.attempt_envelope.attempt_id:
            raise ValueError(
                f"fresh restore attestation attempt_id {fresh.attempt_id} does not "
                f"match execution attempt_id {execution.attempt_envelope.attempt_id}"
            )
        if fresh.request_hash != execution.request_hash:
            raise ValueError(
                "fresh restore attestation request_hash does not match "
                "execution request_hash"
            )
        if (
            execution.process_tree_identity != "none"
            and offline.process_tree_identity != execution.process_tree_identity
        ):
            raise ValueError(
                "offline attestation process_tree_identity does not match execution"
            )
        if (
            execution.target_identity != "none"
            and fresh.target_identity != execution.target_identity
        ):
            raise ValueError(
                "fresh restore attestation target_identity does not match execution"
            )
        if any(
            probe.status != "blocked" or probe.exit_code == 0
            for probe in offline.probe_results
        ):
            outcome = ReplayOutcome.ENVIRONMENT_ARTIFACT_UNAVAILABLE
        elif tuple(sorted(o.content_hash for o in actual)) != execution.actual_outputs:
            outcome = ReplayOutcome.OUTPUT_HASH_MISMATCH
        else:
            outcome = compare_replay_outputs(expected, actual, policy)

    mismatches: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    if outcome != ReplayOutcome.MATCH:
        mismatches = (f"outcome_{outcome.value.lower()}",)
        limitations = (f"replay_did_not_match_{outcome.value.lower()}",)

    unhashed = ReplayResultV1.model_construct(
        schema_version="1",
        result_id=uuid7(),
        evaluated_at=execution.end_time,
        request_hash=execution.request_hash,
        authorization_hash=execution.authorization_hash,
        outcome=outcome,
        verified_input_hashes=execution.verified_inputs,
        actual_output_hashes=execution.actual_outputs,
        offline_attestation_hash=offline.attestation_hash if offline else None,
        fresh_attestation_hash=fresh.attestation_hash if fresh else None,
        mismatch_classifications=mismatches,
        limitations=limitations,
        attempt_envelope=execution.attempt_envelope,
        replay_implementation_hash=replay_implementation_hash,
        policy_hash=policy.policy_hash,
        result_hash="0" * 64,
    )
    return unhashed.model_copy(update={"result_hash": replay_result_hash(unhashed)})


def finalize_qualification_report(
    pre_replay: PreReplayQualificationReportV1,
    replay: ReplayResultV1,
) -> PurposeQualificationReportV1:
    """Derive the twelfth OFFLINE_REPLAY dimension and produce
    PurposeQualificationReportV1.
    """
    from uuid import uuid7

    is_match = replay.outcome == ReplayOutcome.MATCH
    status = QualificationStatus.PASS if is_match else QualificationStatus.FAIL
    limitations = () if is_match else (f"replay_{replay.outcome.value.lower()}",)

    dim12 = DimensionQualificationResultV1(
        schema_version="1",
        dimension=QualificationDimension.OFFLINE_REPLAY,
        purpose=pre_replay.purpose,
        status=status,
        reachability=ExecutionReachability.REACHED,
        evidence_hashes=(replay.result_hash,),
        tested_golden_case_ids=(),
        admitted_purpose=is_match,
        limitations=limitations,
        adjudication_policy_hash=pre_replay.results[0].adjudication_policy_hash,
    )

    all_results = (*pre_replay.results, dim12)
    return PurposeQualificationReportV1(
        schema_version="1",
        report_id=uuid7(),
        report_version="1",
        reported_at=replay.evaluated_at,
        purpose=pre_replay.purpose,
        target=pre_replay.target,
        results=all_results,
        pre_replay_report_hash=content_hash(pre_replay),
    )


@dataclass(frozen=True, slots=True)
class PositivePurposeTerminalBundle:
    profile: QualificationProfileV1
    target: QualificationTargetV1
    pre_replay_report: PreReplayQualificationReportV1
    final_report: PurposeQualificationReportV1
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    request: ReplayRequestV1
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    replay_authority: ReplayAuthorizationVerificationBundle
    execution: ReplayExecutionRecordV1
    offline: SystemOfflineAttestationV1
    fresh: FreshRestoreAttestationV1
    replay: ReplayResultV1
    qualification_context: QualificationExecutionContext
    artifacts: Mapping[str, VerifiedArtifactBytes]
    dispositions: tuple[ContentDispositionRecordV1, ...]


@dataclass(frozen=True, slots=True)
class ProfileExternalNegativeEvidence:
    profile: QualificationProfileV1
    external_dependency: ExternalDependencyResolutionV1
    evidence: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class RightsNegativeEvidence:
    assessment: ValidatedRightsAssessment
    evidence: RightsEvidenceContext


@dataclass(frozen=True, slots=True)
class AcquisitionNegativeEvidence:
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    plan: AcquisitionPlanV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    reconciliations: tuple[AcquisitionReconciliationV1, ...]
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class SnapshotNegativeEvidence:
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    receipts: tuple[AcquisitionReceiptV1, ...]
    validation_context: CandidateValidationContext
    validated_candidate: ValidatedCandidateFactSet | None
    consistency: CrossComponentConsistencyDecisionV1 | None
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class QualificationNegativeEvidence:
    context: QualificationExecutionContext
    pre_replay_report: PreReplayQualificationReportV1 | None
    golden_case_results: tuple[GoldenCaseResultV1, ...]


@dataclass(frozen=True, slots=True)
class ReplayNegativeEvidence:
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    request: ReplayRequestV1
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    replay_authority: ReplayAuthorizationVerificationBundle
    execution: ReplayExecutionRecordV1
    qualification_context: QualificationExecutionContext
    pre_replay_report: PreReplayQualificationReportV1
    offline: SystemOfflineAttestationV1 | None
    fresh: FreshRestoreAttestationV1 | None
    replay: ReplayResultV1
    artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class ReplayAuthorizationNegativeEvidence:
    snapshot: RealSourceSnapshotV1
    closure: EnvironmentClosureV1
    pre_replay_report: PreReplayQualificationReportV1
    qualification_context: QualificationExecutionContext
    replay_authority: ReplayAuthorizationVerificationBundle
    artifacts: Mapping[str, VerifiedArtifactBytes]


type NegativeStageEvidence = (
    ProfileExternalNegativeEvidence
    | RightsNegativeEvidence
    | AcquisitionNegativeEvidence
    | SnapshotNegativeEvidence
    | QualificationNegativeEvidence
    | ReplayAuthorizationNegativeEvidence
    | ReplayNegativeEvidence
)


@dataclass(frozen=True, slots=True)
class NegativePurposeTerminalBundle:
    profile: QualificationProfileV1
    target: QualificationTargetV1
    final_report: PurposeQualificationReportV1
    blocker_dimension: QualificationDimension
    blocker_evidence: Mapping[str, VerifiedArtifactBytes]
    stage_evidence: NegativeStageEvidence
    dispositions: tuple[ContentDispositionRecordV1, ...]
    disposition_evidence: Mapping[str, VerifiedArtifactBytes]
    external_dependency: ExternalDependencyResolutionV1 | None


type PurposeTerminalBundle = (
    PositivePurposeTerminalBundle | NegativePurposeTerminalBundle
)


def _deterministic_uuid7(hash_hex: str) -> UUID:
    """Derive a deterministic UUIDv7 value from a hash string."""
    raw = int(hash_hex[:32], 16)
    # Set version bits (bits 48-51 from MSB) to 7
    raw &= ~(0xF << 76)
    raw |= 0x7 << 76
    # Set variant bits (bits 64-65 from MSB) to 0b10 (RFC 4122 / RFC 9562)
    raw &= ~(0x3 << 62)
    raw |= 0x2 << 62
    return UUID(int=raw)


def derive_qualified_reference_inventory(
    bundle: PositivePurposeTerminalBundle,
) -> tuple[ArtifactReference, ...]:
    """Derive the immutable reference inventory for one positive qualified purpose."""
    references: list[ArtifactReference] = []

    # Include replay inputs for this purpose - strictly canonical model inputs only
    for entry in bundle.snapshot.replay_inputs:
        if (
            isinstance(entry, CanonicalReplayInputEntryV1)
            and entry.purpose is bundle.profile.purpose
        ):
            references.append(entry.artifact_reference)

    # Include expected outputs for this purpose
    for item in bundle.snapshot.expected_outputs:
        if item.purpose is bundle.profile.purpose:
            references.append(
                ArtifactReference(
                    artifact_id=_deterministic_uuid7(item.canonical_output_hash),
                    kind=ArtifactKind.RESULT,
                    content_hash=item.canonical_output_hash,
                    location=f"drift+sha256://{item.canonical_output_hash}",
                )
            )

    # Core identities with deterministic artifact UUIDs
    p_hash = qualification_profile_hash(bundle.profile)
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(p_hash),
            kind=ArtifactKind.OTHER,
            content_hash=p_hash,
            location=f"drift+sha256://{p_hash}",
        )
    )
    rep_hash = content_hash(bundle.final_report)
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(rep_hash),
            kind=ArtifactKind.RESULT,
            content_hash=rep_hash,
            location=f"drift+sha256://{rep_hash}",
        )
    )
    snap_hash = bundle.snapshot.snapshot_hash
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(snap_hash),
            kind=ArtifactKind.DATASET,
            content_hash=snap_hash,
            location=f"drift+sha256://{snap_hash}",
        )
    )
    rights_hash = content_hash(bundle.replay_authority.current_assessment.assessment)
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(rights_hash),
            kind=ArtifactKind.OTHER,
            content_hash=rights_hash,
            location=f"drift+sha256://{rights_hash}",
        )
    )
    closure_hash = bundle.closure.closure_hash
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(closure_hash),
            kind=ArtifactKind.OTHER,
            content_hash=closure_hash,
            location=f"drift+sha256://{closure_hash}",
        )
    )
    replay_hash = bundle.replay.result_hash
    references.append(
        ArtifactReference(
            artifact_id=_deterministic_uuid7(replay_hash),
            kind=ArtifactKind.RESULT,
            content_hash=replay_hash,
            location=f"drift+sha256://{replay_hash}",
        )
    )

    unique: dict[str, ArtifactReference] = {}
    for r in references:
        if r.location not in unique:
            unique[r.location] = r
    return tuple(unique[loc] for loc in sorted(unique.keys()))


def build_qualified_source_handoff(
    completion: M1eCompletionRecordV1,
    purpose: ConsumerPurpose,
    bundle: PositivePurposeTerminalBundle,
) -> QualifiedSourceHandoffV1:
    """Construct immutable handoff for a verified qualified source purpose."""
    if bundle.profile.purpose is not purpose:
        raise ValueError(
            f"bundle purpose {bundle.profile.purpose} does not match {purpose}"
        )
    if not completion.completion_id:
        raise ValueError("completion record must have a valid completion_id")

    universe_refs: list[str] = []
    economic_refs: list[str] = []
    obs_refs: list[str] = []
    sess_refs: list[str] = []

    for entry in bundle.snapshot.replay_inputs:
        if isinstance(entry, CanonicalReplayInputEntryV1) and entry.purpose is purpose:
            loc = entry.artifact_reference.location
            kind_str = str(entry.kind).lower()
            if "universe" in kind_str or "identity" in kind_str:
                universe_refs.append(loc)
            elif "economic" in kind_str:
                economic_refs.append(loc)
            elif "session" in kind_str:
                sess_refs.append(loc)
            else:
                obs_refs.append(loc)

    target_hash = content_hash(bundle.target)
    unhashed = QualifiedSourceHandoffV1.model_construct(
        schema_version="1",
        handoff_id=uuid7(),
        purpose=purpose,
        profile_hash=qualification_profile_hash(bundle.profile),
        report_hash=content_hash(bundle.final_report),
        target_hash=target_hash,
        snapshot_hash=bundle.snapshot.snapshot_hash,
        rights_assessment_hash=content_hash(
            bundle.replay_authority.current_assessment.assessment
        ),
        universe_references=tuple(sorted(set(universe_refs))),
        economic_outcome_references=tuple(sorted(set(economic_refs))),
        observation_view_references=tuple(sorted(set(obs_refs))),
        session_view_references=tuple(sorted(set(sess_refs))),
        environment_closure_hash=bundle.closure.closure_hash,
        replay_authorization_hash=content_hash(bundle.replay_authority.decision),
        limitations=bundle.final_report.results[-1].limitations,
        handoff_hash="0" * 64,
    )
    return unhashed.model_copy(
        update={"handoff_hash": qualified_source_handoff_hash(unhashed)}
    )


def require_qualified_purpose(
    completion: M1eCompletionRecordV1,
    purpose: ConsumerPurpose,
    bundle: PositivePurposeTerminalBundle,
) -> PurposeQualificationReportV1:
    """Return the verified final report for a qualified purpose."""
    if bundle.profile.purpose is not purpose:
        raise ValueError(
            f"bundle purpose {bundle.profile.purpose} does not match {purpose}"
        )
    return bundle.final_report


def finalize_pilot(
    state: M1ePilotStateV1,
    bundles: tuple[PurposeTerminalBundle, PurposeTerminalBundle],
) -> M1eCompletionRecordV1:
    """Construct terminal completion record from the verified purpose bundles."""
    if len(bundles) != 2:
        raise ValueError("finalize_pilot requires exactly two purpose bundles")

    b1, b2 = bundles
    if b1.profile.purpose == b2.profile.purpose:
        raise ValueError("finalize_pilot requires distinct consumer purposes")

    by_purpose = {b.profile.purpose: b for b in bundles}
    purposes = (
        ConsumerPurpose.HISTORICAL_DECISION_INPUT,
        ConsumerPurpose.RETROSPECTIVE_AUDIT,
    )

    for b in bundles:
        if isinstance(b, PositivePurposeTerminalBundle):
            if b.replay.outcome is not ReplayOutcome.MATCH:
                raise ValueError(
                    "positive terminal bundle requires ReplayOutcome.MATCH, "
                    f"got {b.replay.outcome}"
                )
        elif isinstance(b, NegativePurposeTerminalBundle):
            if isinstance(b.stage_evidence, ProfileExternalNegativeEvidence):
                if b.external_dependency is None:
                    raise ValueError(
                        "ProfileExternalNegativeEvidence requires external_dependency"
                    )
            elif isinstance(b.stage_evidence, RightsNegativeEvidence):
                if (
                    b.blocker_dimension
                    is not QualificationDimension.LICENSING_RETENTION
                ):
                    raise ValueError(
                        "RightsNegativeEvidence requires LICENSING_RETENTION "
                        "blocker dimension"
                    )
            elif isinstance(
                b.stage_evidence,
                (AcquisitionNegativeEvidence, SnapshotNegativeEvidence),
            ):
                if (
                    b.blocker_dimension
                    is not QualificationDimension.ACQUISITION_SNAPSHOT
                ):
                    evidence_type = type(b.stage_evidence).__name__
                    raise ValueError(
                        f"{evidence_type} requires ACQUISITION_SNAPSHOT "
                        "blocker dimension"
                    )
            elif isinstance(
                b.stage_evidence,
                (ReplayAuthorizationNegativeEvidence, ReplayNegativeEvidence),
            ):
                if b.blocker_dimension is not QualificationDimension.OFFLINE_REPLAY:
                    evidence_type = type(b.stage_evidence).__name__
                    raise ValueError(
                        f"{evidence_type} requires OFFLINE_REPLAY blocker dimension"
                    )
            elif isinstance(b.stage_evidence, QualificationNegativeEvidence):
                if b.blocker_dimension not in _PRE_REPLAY_DIMENSIONS:
                    raise ValueError(
                        "QualificationNegativeEvidence requires a pre-replay "
                        f"blocker dimension, got {b.blocker_dimension}"
                    )
            else:
                raise ValueError(
                    "unsupported negative stage evidence type: "
                    f"{type(b.stage_evidence)}"
                )

    all_positive = all(isinstance(b, PositivePurposeTerminalBundle) for b in bundles)
    completion_kind = (
        M1eCompletionKind.COMPLETED_POSITIVE
        if all_positive
        else M1eCompletionKind.COMPLETED_NEGATIVE
    )

    reports: list[PurposeQualificationReportV1] = []
    states: list[PurposeStageStateV1] = []
    blockers: list[QualificationDimension] = []
    blocker_ev: list[SHA256Hash] = []
    dispositions: list[ContentDispositionRecordV1] = []
    ext_deps: list[ExternalDependencyResolutionV1] = []

    for purpose in purposes:
        b = by_purpose[purpose]
        reports.append(b.final_report)
        dispositions.extend(b.dispositions)
        if isinstance(b, PositivePurposeTerminalBundle):
            states.append(
                PurposeStageStateV1.model_construct(
                    schema_version="1",
                    purpose=purpose,
                    profile_hash=qualification_profile_hash(b.profile),
                    stage=PilotStage.COMPLETED_POSITIVE,
                    reached_stage_artifact_hashes=(b.replay.result_hash,),
                    terminal_blocker=None,
                )
            )
        else:
            blockers.append(b.blocker_dimension)
            blocker_ev.extend(b.blocker_evidence.keys())
            if b.external_dependency:
                ext_deps.append(b.external_dependency)
            states.append(
                PurposeStageStateV1.model_construct(
                    schema_version="1",
                    purpose=purpose,
                    profile_hash=qualification_profile_hash(b.profile),
                    stage=PilotStage.COMPLETED_NEGATIVE,
                    reached_stage_artifact_hashes=tuple(
                        sorted(b.blocker_evidence.keys())
                    ),
                    terminal_blocker=b.blocker_dimension,
                )
            )

    return M1eCompletionRecordV1.model_construct(
        schema_version="1",
        completion_id=uuid7(),
        completion_version="1",
        completed_at=reports[0].reported_at,
        profile_set_hash=state.profile_set_hash,
        purpose_states=(states[0], states[1]),
        shared_artifact_hashes=state.shared_artifact_hashes,
        blocking_dimensions=tuple(sorted(set(blockers), key=_ALL_DIMENSIONS.index)),
        blocking_evidence_hashes=tuple(sorted(set(blocker_ev))),
        purpose_reports=(reports[0], reports[1]),
        content_dispositions=tuple(dispositions),
        external_dependencies=tuple(ext_deps),
        completion_kind=completion_kind,
    )
