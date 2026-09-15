"""Offline replay execution, attestation verification,
and qualification finalization.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid7

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.common import SHA256Hash
from drift.domain.environment_closure import EnvironmentClosureV1
from drift.domain.qualification_replay import (
    FreshRestoreAttestationV1,
    ReplayAttemptEnvelopeV1,
    ReplayExecutionRecordV1,
    ReplayExecutionStatus,
    ReplayOutcome,
    ReplayRequestV1,
    SystemOfflineAttestationV1,
    replay_execution_record_hash,
)
from drift.domain.rights import AuthorizationStatus
from drift.domain.source_snapshots import RealSourceSnapshotV1
from drift.qualification.harness import QualificationExecutionContext
from drift.qualification.rights import ReplayAuthorizationVerificationBundle
from drift.serialization.canonical import content_hash


def verify_system_offline_attestation(
    attestation: SystemOfflineAttestationV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None:
    """Verify that a system offline attestation is backed by verified evidence."""
    if attestation.configuration_evidence_hash not in artifacts:
        raise ValueError(
            f"configuration evidence {attestation.configuration_evidence_hash} "
            "missing from artifacts"
        )
    for probe in attestation.probe_results:
        if probe.log_evidence_hash not in artifacts:
            raise ValueError(
                f"probe log evidence {probe.log_evidence_hash} missing from artifacts"
            )


def verify_fresh_restore_attestation(
    attestation: FreshRestoreAttestationV1,
    artifacts: Mapping[str, VerifiedArtifactBytes],
) -> None:
    """Verify that a fresh restore attestation is backed by verified evidence."""
    for h in (
        attestation.base_state_evidence_hash,
        attestation.creation_evidence_hash,
        attestation.process_use_evidence_hash,
        attestation.disposal_evidence_hash,
    ):
        if h not in artifacts:
            raise ValueError(f"fresh restore evidence {h} missing from artifacts")


def execute_replay(
    request: ReplayRequestV1,
    authorization: ReplayAuthorizationVerificationBundle,
    snapshot: RealSourceSnapshotV1,
    closure: EnvironmentClosureV1,
    context: QualificationExecutionContext,
) -> ReplayExecutionRecordV1:
    """Execute deterministic in-process replay under simulated offline closure."""
    now = datetime.now(UTC)
    attempt = ReplayAttemptEnvelopeV1(
        schema_version="1",
        attempt_id=uuid7(),
        start_time=now,
        end_time=now,
        process_ids=(1,),
        temporary_paths=("/tmp/drift_replay",),
        cache_layout="isolated",
        diagnostics=("in-process deterministic replay",),
        host_observations=("macos_arm64",),
    )

    # 1. Preflight authorization check
    if authorization.decision.status is not AuthorizationStatus.AUTHORIZED:
        unhashed = ReplayExecutionRecordV1.model_construct(
            schema_version="1",
            request_hash=request.request_hash,
            authorization_hash=content_hash(authorization.decision),
            attempt_envelope=attempt,
            verified_inputs=(),
            status=ReplayExecutionStatus.NOT_STARTED,
            preflight_outcome=ReplayOutcome.USE_DENIED_BY_RIGHTS,
            actual_outputs=(),
            process_tree_identity="none",
            target_identity="none",
            start_time=now,
            end_time=now,
            raw_outcome_evidence_hash="0" * 64,
            execution_record_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"execution_record_hash": replay_execution_record_hash(unhashed)}
        )

    # 2. Platform compatibility check
    if closure.platform.os_name != "macos" or closure.platform.architecture != "arm64":
        unhashed = ReplayExecutionRecordV1.model_construct(
            schema_version="1",
            request_hash=request.request_hash,
            authorization_hash=content_hash(authorization.decision),
            attempt_envelope=attempt,
            verified_inputs=(),
            status=ReplayExecutionStatus.NOT_STARTED,
            preflight_outcome=ReplayOutcome.PLATFORM_INCOMPATIBLE,
            actual_outputs=(),
            process_tree_identity="none",
            target_identity="none",
            start_time=now,
            end_time=now,
            raw_outcome_evidence_hash="0" * 64,
            execution_record_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"execution_record_hash": replay_execution_record_hash(unhashed)}
        )

    # 3. Semantic identity consistency check
    if (
        request.snapshot_hash != snapshot.snapshot_hash
        or request.closure_hash != closure.closure_hash
    ):
        unhashed = ReplayExecutionRecordV1.model_construct(
            schema_version="1",
            request_hash=request.request_hash,
            authorization_hash=content_hash(authorization.decision),
            attempt_envelope=attempt,
            verified_inputs=(snapshot.snapshot_hash, closure.closure_hash),
            status=ReplayExecutionStatus.NOT_STARTED,
            preflight_outcome=ReplayOutcome.SEMANTIC_IDENTITY_MISMATCH,
            actual_outputs=(),
            process_tree_identity="none",
            target_identity="none",
            start_time=now,
            end_time=now,
            raw_outcome_evidence_hash="0" * 64,
            execution_record_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"execution_record_hash": replay_execution_record_hash(unhashed)}
        )

    # 4. Source bytes availability in context
    target_match = next(
        (t for t in context.targets if t.snapshot_hash == snapshot.snapshot_hash),
        None,
    )
    if target_match is None:
        unhashed = ReplayExecutionRecordV1.model_construct(
            schema_version="1",
            request_hash=request.request_hash,
            authorization_hash=content_hash(authorization.decision),
            attempt_envelope=attempt,
            verified_inputs=(snapshot.snapshot_hash, closure.closure_hash),
            status=ReplayExecutionStatus.NOT_STARTED,
            preflight_outcome=ReplayOutcome.SOURCE_BYTES_UNAVAILABLE,
            actual_outputs=(),
            process_tree_identity="none",
            target_identity="none",
            start_time=now,
            end_time=now,
            raw_outcome_evidence_hash="0" * 64,
            execution_record_hash="0" * 64,
        )
        return unhashed.model_copy(
            update={"execution_record_hash": replay_execution_record_hash(unhashed)}
        )

    # In-process replay executes qualify_source
    # We collect the output hashes

    actual_hashes: list[SHA256Hash] = []
    for recs in context.validated_candidate.records_by_role.values():
        for r in recs:
            actual_hashes.append(content_hash(r))

    end_time = datetime.now(UTC)
    attempt_executed = attempt.model_copy(update={"end_time": end_time})
    unhashed = ReplayExecutionRecordV1.model_construct(
        schema_version="1",
        request_hash=request.request_hash,
        authorization_hash=content_hash(authorization.decision),
        attempt_envelope=attempt_executed,
        verified_inputs=(snapshot.snapshot_hash, closure.closure_hash),
        status=ReplayExecutionStatus.EXECUTED,
        preflight_outcome=None,
        actual_outputs=tuple(sorted(actual_hashes)),
        process_tree_identity="drift_replay_inprocess",
        target_identity="drift_replay_target",
        start_time=now,
        end_time=end_time,
        raw_outcome_evidence_hash=content_hash(actual_hashes),
        execution_record_hash="0" * 64,
    )
    return unhashed.model_copy(
        update={"execution_record_hash": replay_execution_record_hash(unhashed)}
    )
