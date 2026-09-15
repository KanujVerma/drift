"""Provider-neutral qualification adapter protocol and candidate facts validation."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from drift.datasets.resolver import VerifiedArtifactBytes
from drift.domain.acquisition import AcquisitionReceiptV1
from drift.domain.common import FrozenModel, SHA256Hash
from drift.domain.dataset_validation import (
    DatasetValidationDecisionV2,
    ValidatedDatasetBundleV1,
    ValidationResult,
    ValidationRunContextV1,
)
from drift.domain.manifests import DatasetManifestV2
from drift.domain.qualification import PilotProfileSetV1
from drift.domain.qualification_adapters import (
    AdapterIdentityV1,
    CandidateContextBlueprintV1,
    ProviderMappingReportV1,
    provider_mapping_report_hash,
)
from drift.qualification.rights import AcquisitionAuthorizationVerificationBundle
from drift.qualification.snapshots import ExistingContractContexts
from drift.serialization.canonical import content_hash


@dataclass(frozen=True, slots=True)
class QualificationAdapterInput:
    """Inputs supplied to a qualification adapter to map provider records."""

    profile_set: PilotProfileSetV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    native_artifacts: Mapping[str, VerifiedArtifactBytes]
    methodology_artifacts: Mapping[str, VerifiedArtifactBytes]
    schema_artifacts: Mapping[str, VerifiedArtifactBytes]


@dataclass(frozen=True, slots=True)
class CandidateDatasetInput:
    """One candidate dataset emitted by an adapter."""

    manifest: DatasetManifestV2
    validation_run: ValidationRunContextV1
    artifacts: Mapping[str, VerifiedArtifactBytes]
    supporting_artifacts: Mapping[str, VerifiedArtifactBytes]
    blueprint_hash: SHA256Hash


@dataclass(frozen=True, slots=True)
class CandidateFactSet:
    """Complete collection of candidate datasets emitted by an adapter."""

    blueprint: CandidateContextBlueprintV1
    m1b_datasets: tuple[CandidateDatasetInput, ...]
    m1c_datasets: tuple[CandidateDatasetInput, ...]
    m1d_datasets: tuple[CandidateDatasetInput, ...]
    mapping_report: ProviderMappingReportV1


@dataclass(frozen=True, slots=True)
class ValidatedCandidateFactSet:
    """Candidate facts verified through unchanged public validator contracts."""

    mapping_report: ProviderMappingReportV1
    validation_decisions: tuple[DatasetValidationDecisionV2, ...]
    bundles: tuple[ValidatedDatasetBundleV1, ...]
    records_by_role: Mapping[str, tuple[FrozenModel, ...]]
    contexts: ExistingContractContexts


class QualificationAdapter(Protocol):
    """Protocol for provider-neutral qualification adapters."""

    identity: AdapterIdentityV1

    def map(self, value: QualificationAdapterInput) -> CandidateFactSet: ...


@dataclass(frozen=True, slots=True)
class CandidateValidationContext:
    """Context required to validate candidate facts against authentic contracts."""

    profiles: PilotProfileSetV1
    receipts: tuple[AcquisitionReceiptV1, ...]
    acquisition_authority: AcquisitionAuthorizationVerificationBundle
    native_artifacts: Mapping[str, VerifiedArtifactBytes]
    adjudication_policy_artifacts: Mapping[str, VerifiedArtifactBytes]
    existing_contexts: ExistingContractContexts | None = None


def verify_mapping_report_integrity(report: ProviderMappingReportV1) -> None:
    """Verify self-excluding hash and internal mapping coverage of a mapping report."""
    expected = provider_mapping_report_hash(report)
    if report.report_hash != expected:
        raise ValueError(
            f"report hash mismatch: expected {expected}, got {report.report_hash}"
        )
    if report.native_records_count < 0 or report.emitted_records_count < 0:
        raise ValueError("record counts must not be negative")
    if not report.coverage_reconciliation_pass:
        raise ValueError("mapping report did not pass coverage reconciliation")


def validate_candidate_facts(
    candidate: CandidateFactSet,
    context: CandidateValidationContext,
) -> ValidatedCandidateFactSet:
    """Validate candidate datasets emitted by an adapter via public contracts."""
    verify_mapping_report_integrity(candidate.mapping_report)

    # 1. Verify profile set hash binding
    if candidate.mapping_report.profile_set_hash != content_hash(context.profiles):
        actual_ps_hash = candidate.mapping_report.profile_set_hash
        expected_ps_hash = content_hash(context.profiles)
        raise ValueError(
            f"mapping report profile set hash {actual_ps_hash} "
            f"does not match validation context profile set {expected_ps_hash}"
        )

    # 2. Verify blueprint binding across all datasets
    bp_hash = candidate.blueprint.blueprint_hash
    all_datasets = (
        *candidate.m1b_datasets,
        *candidate.m1c_datasets,
        *candidate.m1d_datasets,
    )
    for ds in all_datasets:
        if ds.blueprint_hash != bp_hash:
            raise ValueError(
                f"dataset {ds.manifest.dataset_id} blueprint hash mismatch: "
                f"expected {bp_hash}, got {ds.blueprint_hash}"
            )

    # 3. Replay public validators for each layer
    from drift.markets.economic_validation import validate_economic_dataset
    from drift.markets.observation_validation import validate_observation_dataset
    from drift.markets.session_validation import validate_session_dataset
    from drift.markets.validation import (
        _parse_identity_records,
        validate_identity_dataset,
    )

    validation_decisions: list[DatasetValidationDecisionV2] = []
    bundles: list[ValidatedDatasetBundleV1] = []
    records_by_role: dict[str, tuple[FrozenModel, ...]] = {}

    # Validate M1b datasets
    for ds in candidate.m1b_datasets:
        vbytes = tuple(ds.artifacts.values())
        decision = validate_identity_dataset(ds.manifest, vbytes, ds.validation_run)
        if decision.result is not ValidationResult.PASS:
            err_msg = (
                f"M1b candidate dataset {ds.manifest.dataset_id} "
                f"validation failed: {decision.findings}"
            )
            raise ValueError(err_msg)
        validation_decisions.append(decision)
        m1b_recs: list[FrozenModel] = []
        role = ds.manifest.dataset_role.name
        for artifact in vbytes:
            parsed, parse_findings = _parse_identity_records(artifact, role)
            m1b_recs.extend(parsed)
        records_by_role[role] = tuple(m1b_recs)

    # Validate M1c datasets
    for ds in candidate.m1c_datasets:
        vbytes = tuple(ds.artifacts.values())
        decision, recs = validate_economic_dataset(
            ds.manifest,
            vbytes,
            ds.validation_run,
        )
        if decision.result is not ValidationResult.PASS:
            err_msg = (
                f"M1c candidate dataset {ds.manifest.dataset_id} "
                f"validation failed: {decision.findings}"
            )
            raise ValueError(err_msg)
        validation_decisions.append(decision)
        records_by_role[ds.manifest.dataset_role.name] = recs

    # Validate M1d datasets
    for ds in candidate.m1d_datasets:
        role = ds.manifest.dataset_role.name
        if role in {"source_observation", "observation_coverage"}:
            decision, obs_recs = validate_observation_dataset(
                ds.manifest,
                ds.artifacts,
                ds.validation_run,
                ds.supporting_artifacts,
            )
            if decision.result is not ValidationResult.PASS:
                err_msg = (
                    f"M1d observation dataset {ds.manifest.dataset_id} "
                    f"validation failed: {decision.findings}"
                )
                raise ValueError(err_msg)
            validation_decisions.append(decision)
            records_by_role[role] = obs_recs
        elif role in {"scheduled_session", "realized_session", "session_coverage"}:
            decision, sess_recs = validate_session_dataset(
                ds.manifest,
                ds.artifacts,
                ds.validation_run,
                ds.supporting_artifacts,
            )
            if decision.result is not ValidationResult.PASS:
                err_msg = (
                    f"M1d session dataset {ds.manifest.dataset_id} "
                    f"validation failed: {decision.findings}"
                )
                raise ValueError(err_msg)
            validation_decisions.append(decision)
            records_by_role[role] = sess_recs

    contexts = context.existing_contexts
    if contexts is None:
        contexts = ExistingContractContexts(
            m1b_contexts=(),
            m1c_context=None,  # type: ignore[arg-type]
            m1d_context=None,  # type: ignore[arg-type]
        )

    return ValidatedCandidateFactSet(
        mapping_report=candidate.mapping_report,
        validation_decisions=tuple(validation_decisions),
        bundles=tuple(bundles),
        records_by_role=records_by_role,
        contexts=contexts,
    )
